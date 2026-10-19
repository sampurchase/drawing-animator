"""Tests for backgrounds, music and video rendering.  Run:  python3 -m unittest discover -s tests -v"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from starlette.testclient import TestClient  # noqa: E402

from animator import music as M  # noqa: E402
from webapp.app import create_app  # noqa: E402
from webapp.config import Config  # noqa: E402

SAMPLES = os.path.join(ROOT, "samples")


def sample(name):
    with open(os.path.join(SAMPLES, name), "rb") as f:
        return f.read()


def wav_bytes(seconds=3.0, bpm=100):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.wav")
        M.write_wav(p, M.generate(bpm, seconds))
        with open(p, "rb") as f:
            return f.read()


def probe(path, entries):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", entries, "-of", "json", path],
                         capture_output=True, text=True)
    return json.loads(out.stdout)


class MediaRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.config = Config(data_dir=cls.tmp.name, render_workers=1)
        cls.app = create_app(cls.config)
        cls.client = TestClient(cls.app)
        cls.d1 = cls.upload_drawing("fake_photo.jpg", "Hero Boy")
        cls.d2 = cls.upload_drawing("fake_photo_dancer.jpg", "Ballerina")

    @classmethod
    def tearDownClass(cls):
        cls.app.state.runner.shutdown()
        cls.tmp.cleanup()

    @classmethod
    def upload_drawing(cls, fname, name):
        r = cls.client.post("/api/drawings", files={"file": (fname, sample(fname), "image/jpeg")}, data={"name": name})
        assert r.status_code == 201, r.text
        return r.json()

    def wait_for(self, render_id, states=("done", "failed", "cancelled"), timeout=120):
        end = time.time() + timeout
        while time.time() < end:
            r = self.client.get(f"/api/renders/{render_id}").json()
            if r["status"] in states:
                return r
            time.sleep(0.3)
        self.fail(f"render {render_id} did not finish: {r}")

    def body(self, **kw):
        base = {"drawings": [self.d1["id"], self.d2["id"]], "mode": "unison", "background": "none", "music": "builtin",
                "quality": "preview", "seconds": 4}
        base.update(kw)
        return base

    # ---------------------------------------------------------------- backgrounds
    def test_starter_background_and_upload(self):
        listing = self.client.get("/api/backgrounds").json()
        self.assertTrue(any(b["name"] == "Disco dance floor" for b in listing))
        r = self.client.post("/api/backgrounds", files={"file": ("floor.jpg", sample("dancefloor.jpg"), "image/jpeg")},
                             data={"name": "Mine"})
        self.assertEqual(r.status_code, 201, r.text)
        b = r.json()
        self.assertEqual(self.client.get(b["thumb_url"]).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/backgrounds/{b['id']}").status_code, 200)
        self.assertEqual(self.client.get(b["thumb_url"]).status_code, 404)

    def test_bad_backgrounds(self):
        r = self.client.post("/api/backgrounds", files={"file": ("a.jpg", b"not a picture", "image/jpeg")})
        self.assertEqual(r.status_code, 422)
        self.assertIn("couldn't read", r.json()["error"])
        import cv2, numpy as np
        ok, tiny = cv2.imencode(".png", np.zeros((50, 50, 3), np.uint8))
        r = self.client.post("/api/backgrounds", files={"file": ("tiny.png", tiny.tobytes(), "image/png")})
        self.assertEqual(r.status_code, 422)
        self.assertIn("too small", r.json()["error"])

    def test_starter_not_reseeded_after_delete(self):
        with tempfile.TemporaryDirectory() as d:
            app = create_app(Config(data_dir=d, render_workers=1))
            c = TestClient(app)
            first = c.get("/api/backgrounds").json()
            self.assertEqual(len(first), 1)
            c.delete(f"/api/backgrounds/{first[0]['id']}")
            again = TestClient(create_app(Config(data_dir=d, render_workers=1)))
            self.assertEqual(again.get("/api/backgrounds").json(), [])
            app.state.runner.shutdown()

    # ---------------------------------------------------------------- music
    def test_music_upload_and_errors(self):
        r = self.client.post("/api/music", files={"file": ("party.wav", wav_bytes(), "audio/wav")},
                             data={"name": "Party", "bpm": "100"})
        self.assertEqual(r.status_code, 201, r.text)
        m = r.json()
        self.assertEqual((m["name"], m["bpm"]), ("Party", 100.0))
        self.assertAlmostEqual(m["duration"], 3.0, delta=0.3)
        self.assertEqual(self.client.delete(f"/api/music/{m['id']}").status_code, 200)
        self.assertEqual(self.client.get("/api/music").json(), [])
        bad = self.client.post("/api/music", files={"file": ("x.mp3", b"definitely not audio", "audio/mpeg")}, data={"bpm": "100"})
        self.assertEqual(bad.status_code, 422)
        self.assertIn("couldn't read", bad.json()["error"])
        bad = self.client.post("/api/music", files={"file": ("x.txt", b"hi", "text/plain")}, data={"bpm": "100"})
        self.assertEqual(bad.status_code, 422)
        bad = self.client.post("/api/music", files={"file": ("p.wav", wav_bytes(), "audio/wav")}, data={"bpm": "900"})
        self.assertEqual(bad.status_code, 422)
        self.assertIn("between", bad.json()["error"])
        bad = self.client.post("/api/music", files={"file": ("p.wav", wav_bytes(), "audio/wav")}, data={"bpm": "fast"})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(os.listdir(os.path.join(self.tmp.name, "music")), [])      # nothing left behind

    # ---------------------------------------------------------------- request checks
    def test_request_validation(self):
        before = len(self.client.get("/api/renders").json())
        bg = self.client.get("/api/backgrounds").json()[0]["id"]
        cases = [
            ({"drawings": []}, "at least one"),
            ({"drawings": ["0123456789ab"]}, "isn't in the gallery"),
            ({"drawings": [self.d1["id"]] * 9}, "8 or fewer"),
            (self.body(mode="polka"), "group style"),
            (self.body(seconds=1), "between"),
            (self.body(seconds="long"), "number of seconds"),
            (self.body(background="0123456789ab"), "background"),
            (self.body(music="0123456789ab"), "music track"),
            (self.body(bpm=1000), "tempo"),
            (self.body(quality="ultra"), "quality"),
        ]
        for body, text in cases:
            r = self.client.post("/api/renders", json=body)
            self.assertEqual(r.status_code, 400, body)
            self.assertIn(text, r.json()["error"], body)
        self.assertEqual(self.client.post("/api/renders", content=b"nope").status_code, 400)
        self.assertEqual(len(self.client.get("/api/renders").json()), before)      # nothing was queued

    # ---------------------------------------------------------------- real render
    def test_render_end_to_end(self):
        bg = self.client.get("/api/backgrounds").json()[0]["id"]
        track = self.client.post("/api/music", files={"file": ("p.wav", wav_bytes(6, 100), "audio/wav")},
                                 data={"name": "Mine", "bpm": "100"}).json()
        r = self.client.post("/api/renders", json=self.body(background=bg, music=track["id"], mode="mirror"))
        self.assertEqual(r.status_code, 201, r.text)
        job = r.json()
        self.assertEqual(job["name"], "Hero Boy and Ballerina dance")
        self.assertEqual(job["request"]["bpm"], 100.0)                              # taken from the track
        done = self.wait_for(job["id"])
        self.assertEqual(done["status"], "done", done)
        self.assertEqual(done["progress"], 1.0)
        self.assertGreater(done["seconds_taken"], 0)
        # the video
        v = self.client.get(done["video_url"])
        self.assertEqual(v.status_code, 200)
        path = os.path.join(self.tmp.name, "renders", job["id"], "video.mp4")
        info = probe(path, "stream=codec_name,width,height:format=duration")
        self.assertEqual({s["codec_name"] for s in info["streams"]}, {"h264", "aac"})
        video = [s for s in info["streams"] if s["codec_name"] == "h264"][0]
        self.assertEqual((video["width"], video["height"]), (640, 360))
        self.assertAlmostEqual(float(info["format"]["duration"]), 4.0, delta=0.2)
        # iPad Safari needs range requests to play video
        part = self.client.get(done["video_url"], headers={"Range": "bytes=0-99"})
        self.assertEqual(part.status_code, 206)
        self.assertEqual(len(part.content), 100)
        self.assertEqual(self.client.get(done["poster_url"]).status_code, 200)
        dl = self.client.get(done["download_url"])
        self.assertIn("attachment", dl.headers["content-disposition"])
        self.assertIn("Hero%20Boy%20and%20Ballerina%20dance.mp4", dl.headers["content-disposition"])
        # no leftovers in the render folder
        self.assertEqual(sorted(os.listdir(os.path.dirname(path))), ["poster.jpg", "video.mp4"])
        # deleting a finished video removes it
        self.assertEqual(self.client.delete(f"/api/renders/{job['id']}").json(), {"deleted": True})
        self.assertFalse(os.path.exists(os.path.dirname(path)))
        self.assertEqual(self.client.get(f"/api/renders/{job['id']}").status_code, 404)
        self.client.delete(f"/api/music/{track['id']}")

    def test_queue_and_cancel(self):
        # a long one keeps the worker busy while we line up a second and cancel both
        first = self.client.post("/api/renders", json=self.body(quality="full", seconds=60, name="Long one")).json()
        second = self.client.post("/api/renders", json=self.body(name="Waiting")).json()
        self.assertEqual(second["status"], "queued")
        self.assertEqual(second["queue_position"], 1)
        # wait for the first to start producing frames
        end = time.time() + 60
        while time.time() < end:
            cur = self.client.get(f"/api/renders/{first['id']}").json()
            if cur["status"] == "running" and cur["progress"] > 0:
                break
            time.sleep(0.2)
        self.assertEqual(cur["status"], "running")
        self.assertLess(cur["progress"], 1)
        self.assertEqual(self.client.delete(f"/api/renders/{second['id']}").json(), {"cancelled": True})
        self.assertEqual(self.client.get(f"/api/renders/{second['id']}").json()["status"], "cancelled")
        self.assertEqual(self.client.delete(f"/api/renders/{first['id']}").json(), {"cancelled": True})
        self.assertEqual(self.wait_for(first["id"])["status"], "cancelled")
        # the cancelled ones never produced a video and left no half-made file
        for j in (first, second):
            self.assertEqual(self.client.get(f"/files/renders/{j['id']}/video.mp4").status_code, 404)
            self.assertNotIn("partial.mp4", os.listdir(os.path.join(self.tmp.name, "renders", j["id"])))
        # and the queue still works afterwards
        again = self.client.post("/api/renders", json=self.body()).json()
        self.assertEqual(self.wait_for(again["id"])["status"], "done")
        for j in (first, second, again):
            self.client.delete(f"/api/renders/{j['id']}")

    def test_drawing_deleted_before_render_runs(self):
        extra = self.upload_drawing("fake_photo_huggable.jpg", "Soon gone")
        store, runner = self.app.state.store, self.app.state.runner
        rid = store.new_id("renders")
        os.makedirs(store.folder("renders", rid))
        req, names = __import__("webapp.jobs", fromlist=["x"]).clean_request(store, self.body(drawings=[extra["id"]]))
        store.add_render(rid, "Doomed", req, names)
        self.client.delete(f"/api/drawings/{extra['id']}")
        runner._run(rid)
        rec = self.client.get(f"/api/renders/{rid}").json()
        self.assertEqual(rec["status"], "failed")
        self.assertIn("deleted", rec["error"])
        self.client.delete(f"/api/renders/{rid}")

    def test_restart_marks_unfinished_as_failed(self):
        with tempfile.TemporaryDirectory() as d:
            app = create_app(Config(data_dir=d, render_workers=1))
            store = app.state.store
            rid = store.new_id("renders")
            os.makedirs(store.folder("renders", rid))
            store.add_render(rid, "Interrupted", {"drawings": []}, [])
            store.update_render(rid, status="running")
            app.state.runner.shutdown()
            app2 = create_app(Config(data_dir=d, render_workers=1))
            rec = TestClient(app2).get(f"/api/renders/{rid}").json()
            self.assertEqual(rec["status"], "failed")
            self.assertIn("restarted", rec["error"])
            app2.state.runner.shutdown()


if __name__ == "__main__":
    unittest.main()
