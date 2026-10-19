"""Tests for the web API.  Run:  python3 -m unittest discover -s tests -v   (or pytest)"""
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from animator import engine as G, extract as E  # noqa: E402
from webapp.app import create_app  # noqa: E402
from webapp.config import Config  # noqa: E402

SAMPLES = os.path.join(ROOT, "samples")


def sample(name):
    with open(os.path.join(SAMPLES, name), "rb") as f:
        return f.read()


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = Config(data_dir=self.tmp.name, max_upload_mb=25.0)
        self.app = create_app(self.config)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def upload(self, name, filename="photo.jpg", ctype="image/jpeg", client=None, label=""):
        return (client or self.client).post(
            "/api/drawings", files={"file": (filename, sample(name), ctype)}, data={"name": label})

    # ---------------------------------------------------------------
    def test_health_and_page(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.json(), {"ok": True, "drawings": 0})
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("text/html", page.headers["content-type"])

    def test_upload_each_template(self):
        for fname, template in (("fake_photo.jpg", "hero"), ("fake_photo_huggable.jpg", "huggable"),
                                ("fake_photo_dancer.jpg", "dancer"), ("fake_photo_original.jpg", "original")):
            r = self.upload(fname, label=f"my {template}")
            self.assertEqual(r.status_code, 201, r.text)
            d = r.json()
            self.assertEqual(d["template"], template)
            self.assertEqual(d["name"], f"my {template}")
            cut = self.client.get(d["cutout_url"])
            self.assertEqual(cut.status_code, 200)
            img = cv2.imdecode(np.frombuffer(cut.content, np.uint8), cv2.IMREAD_UNCHANGED)
            self.assertEqual(img.shape[2], 4)
            self.assertGreater((img[..., 3] > 128).mean(), 0.2)         # a real drawing, mostly opaque
            thumb = cv2.imdecode(np.frombuffer(self.client.get(d["thumb_url"]).content, np.uint8), cv2.IMREAD_UNCHANGED)
            self.assertLessEqual(max(thumb.shape[:2]), 480)
            self.assertTrue(os.path.exists(self.app.state.store.layers_path(d["id"])))

    @unittest.skipUnless(os.path.exists(os.path.join(SAMPLES, "IMG_0154.HEIC")),
                         "no HEIC sample (drop an iPhone photo of a sheet at samples/IMG_0154.HEIC to run this)")
    def test_heic_upload(self):
        r = self.upload("IMG_0154.HEIC", "IMG_0154.HEIC", "image/heic")
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["template"], "original")

    @unittest.skipUnless(os.path.exists(os.path.join(SAMPLES, "IMG_0154.HEIC")), "no HEIC sample")
    def test_wrong_extension_still_sniffed(self):
        r = self.upload("IMG_0154.HEIC", "image.jpg", "image/jpeg")     # iPad can mislabel HEIC as JPEG
        self.assertEqual(r.status_code, 201, r.text)

    def test_sniffing_by_content_not_name(self):
        from webapp.drawings import sniff_extension
        self.assertEqual(sniff_extension(b"\xff\xd8\xff" + b"0" * 20), ".jpg")
        self.assertEqual(sniff_extension(b"\x89PNG\r\n\x1a\n" + b"0" * 20), ".png")
        self.assertEqual(sniff_extension(b"\x00\x00\x00\x18ftypheic" + b"0" * 20), ".heic")

    def test_not_a_photo(self):
        r = self.client.post("/api/drawings", files={"file": ("notes.txt", b"hello there", "text/plain")})
        self.assertEqual(r.status_code, 422)
        self.assertIn("doesn't look like a photo", r.json()["error"])
        self.assertEqual(self.client.get("/api/drawings").json(), [])

    def test_corrupt_photo(self):
        bad = b"\xff\xd8\xff" + b"\x00" * 500                           # JPEG header, garbage after
        r = self.client.post("/api/drawings", files={"file": ("a.jpg", bad, "image/jpeg")})
        self.assertEqual(r.status_code, 422)
        self.assertIn("error", r.json())
        self.assertEqual(os.listdir(self.app.state.store.drawings_dir), [])      # nothing left behind

    def test_no_corner_markers_gives_friendly_error(self):
        r = self.upload("dancefloor.jpg")                               # a photo with no sheet in it
        self.assertEqual(r.status_code, 422)
        self.assertIn("corner", r.json()["error"])
        self.assertNotIn("['", r.json()["error"])                       # no raw code in a message for a child
        self.assertEqual(os.listdir(self.app.state.store.drawings_dir), [])

    def test_too_big(self):
        small = TestClient(create_app(Config(data_dir=self.tmp.name, max_upload_mb=1.0)))
        big = b"\xff\xd8\xff" + os.urandom(2 * 1024 * 1024)
        r = small.post("/api/drawings", files={"file": ("big.jpg", big, "image/jpeg")})
        self.assertEqual(r.status_code, 413)
        self.assertIn("too big", r.json()["error"])

    def test_missing_file(self):
        r = self.client.post("/api/drawings", data={"name": "x"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/drawings", files={"file": ("a.jpg", b"", "image/jpeg")})
        self.assertEqual(r.status_code, 400)

    def test_list_rename_delete(self):
        a = self.upload("fake_photo.jpg", label="first").json()
        b = self.upload("fake_photo_dancer.jpg", label="  second \n one  ").json()
        self.assertEqual(b["name"], "second one")
        listing = self.client.get("/api/drawings").json()
        self.assertEqual([d["id"] for d in listing], [b["id"], a["id"]])        # newest first
        r = self.client.patch(f"/api/drawings/{a['id']}", json={"name": "Sparkle Robot"})
        self.assertEqual(r.json()["name"], "Sparkle Robot")
        self.assertEqual(self.client.get(f"/api/drawings/{a['id']}").json()["name"], "Sparkle Robot")
        self.assertEqual(self.client.patch(f"/api/drawings/{a['id']}", json={"nope": 1}).status_code, 400)
        folder = self.app.state.store.drawing_dir(a["id"])
        self.assertTrue(os.path.isdir(folder))
        self.assertEqual(self.client.delete(f"/api/drawings/{a['id']}").status_code, 200)
        self.assertFalse(os.path.exists(folder))
        self.assertEqual(self.client.get(f"/api/drawings/{a['id']}").status_code, 404)
        self.assertEqual(self.client.get(a["cutout_url"]).status_code, 404)
        self.assertEqual(len(self.client.get("/api/drawings").json()), 1)

    def test_bad_ids_and_files(self):
        for path in ("/api/drawings/../../etc/passwd", "/api/drawings/zzzz", "/files/drawings/..%2f..%2fdb.sqlite/cutout.png"):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        d = self.upload("fake_photo.jpg").json()
        self.assertEqual(self.client.get(f"/files/drawings/{d['id']}/layers.npz").status_code, 404)   # only the images are public
        self.assertEqual(self.client.get(f"/files/drawings/{d['id']}/photo.jpg").status_code, 404)

    def test_persists_across_restart(self):
        d = self.upload("fake_photo_huggable.jpg", label="kept").json()
        again = TestClient(create_app(Config(data_dir=self.tmp.name)))
        listing = again.get("/api/drawings").json()
        self.assertEqual([x["id"] for x in listing], [d["id"]])
        self.assertEqual(again.get(d["thumb_url"]).status_code, 200)

    def test_saved_layers_dance(self):
        """What the upload saved is exactly what the dance engine needs."""
        d = self.upload("fake_photo_dancer.jpg").json()
        saved = E.load_layers(self.app.state.store.layers_path(d["id"]))
        fresh = G.extract_drawing(os.path.join(SAMPLES, "fake_photo_dancer.jpg"))
        s = G.Settings(background=os.path.join(SAMPLES, "dancefloor.jpg"))
        self.assertTrue(np.array_equal(G.Scene([saved], s).frame(2.5), G.Scene([fresh], s).frame(2.5)))

    def test_simultaneous_uploads(self):
        clients = [TestClient(self.app) for _ in range(3)]
        names = ["fake_photo.jpg", "fake_photo_dancer.jpg", "fake_photo_huggable.jpg"]
        with ThreadPoolExecutor(3) as pool:
            results = list(pool.map(lambda a: self.upload(a[1], client=a[0]), zip(clients, names)))
        self.assertEqual([r.status_code for r in results], [201, 201, 201])
        self.assertEqual(len({r.json()["id"] for r in results}), 3)
        self.assertEqual(len(self.client.get("/api/drawings").json()), 3)


if __name__ == "__main__":
    unittest.main()
