"""Rendering videos in the background: validating requests, a one-at-a-time queue, progress and cancelling."""
from __future__ import annotations

import os
import queue
import shutil
import threading
import time

import cv2

from animator import engine as G
from animator import extract as E

from .media import MAX_BPM, MIN_BPM
from .store import Store, clean_name, now

MODES = ("unison", "mirror", "conga")
QUALITY_SIZES = {"preview": "640x360", "full": "1280x720", "hd": "1920x1080"}
PREVIEW_SECONDS = 8
MIN_SECONDS, MAX_SECONDS = 4, 120
MAX_DANCERS = 8


class RequestError(ValueError):
    """The render request doesn't make sense. The message is meant to be shown on screen."""


class Cancelled(Exception):
    pass


def clean_request(store: Store, body: dict) -> tuple[dict, list[str]]:
    """Check what the browser asked for and return (a tidy request, the drawing names). Raises RequestError."""
    if not isinstance(body, dict):
        raise RequestError("I didn't understand that request.")
    ids = body.get("drawings")
    if not isinstance(ids, list) or not ids:
        raise RequestError("Pick at least one drawing to dance.")
    if len(ids) > MAX_DANCERS:
        raise RequestError(f"That's a lot of dancers! Please pick {MAX_DANCERS} or fewer.")
    names = []
    for i in ids:
        try:
            names.append(store.get(str(i))["name"] or "Untitled")
        except KeyError:
            raise RequestError("One of those drawings isn't in the gallery any more. Please pick again.")
    mode = body.get("mode", "unison")
    if mode not in MODES:
        raise RequestError("Pick unison, mirror or conga for the group style.")
    quality = body.get("quality", "full")
    if quality not in QUALITY_SIZES:
        raise RequestError("Pick preview, full or HD for the quality.")
    try:
        seconds = float(body.get("seconds", 16))
    except (TypeError, ValueError):
        raise RequestError("The length should be a number of seconds.")
    if not MIN_SECONDS <= seconds <= MAX_SECONDS:
        raise RequestError(f"The video should be between {MIN_SECONDS} and {MAX_SECONDS} seconds long.")
    background = body.get("background", "none") or "none"
    if background != "none":
        try:
            store.get_background(str(background))
        except KeyError:
            raise RequestError("That background isn't in the library any more. Please pick another.")
    music = body.get("music", "builtin") or "builtin"
    track_bpm = None
    if music not in ("builtin", "none"):
        try:
            track_bpm = store.get_music(str(music))["bpm"]
        except KeyError:
            raise RequestError("That music track isn't in the library any more. Please pick another.")
    bpm = body.get("bpm")
    if bpm in (None, ""):
        bpm = track_bpm or 120.0
    try:
        bpm = float(bpm)
    except (TypeError, ValueError):
        raise RequestError("The tempo should be a number, like 120.")
    if not MIN_BPM <= bpm <= MAX_BPM:
        raise RequestError(f"The tempo should be between {MIN_BPM:g} and {MAX_BPM:g} beats per minute.")
    req = {
        "drawings": [str(i) for i in ids], "mode": mode, "quality": quality, "seconds": seconds,
        "background": str(background), "music": str(music), "bpm": bpm, "walk": bool(body.get("walk", True)),
    }
    return req, names


def make_settings(store: Store, req: dict) -> G.Settings:
    seconds = min(req["seconds"], PREVIEW_SECONDS) if req["quality"] == "preview" else req["seconds"]
    if req["music"] == "builtin":
        music = "auto"
    elif req["music"] == "none":
        music = "none"
    else:
        music = store.music_path(req["music"])
    return G.Settings(
        seconds=seconds, size=QUALITY_SIZES[req["quality"]], mode=req["mode"], bpm=req["bpm"],
        travel=0.6 if req["walk"] else 0.0, music=music,
        background=None if req["background"] == "none" else store.background_path(req["background"]))


def default_name(names: list[str]) -> str:
    uniq = list(dict.fromkeys(names))
    if len(uniq) <= 3:
        return clean_name(" and ".join(uniq) + " dance")
    return clean_name(f"{uniq[0]}, {uniq[1]} and {len(uniq) - 2} more dance")


class JobRunner:
    """Runs one render at a time on a background thread."""

    def __init__(self, store: Store, workers: int | None = None):
        self.store = store
        self.workers = workers
        self.q: queue.Queue[str | None] = queue.Queue()
        self.progress: dict[str, tuple[int, int]] = {}
        self.cancel_requested: set[str] = set()
        self.lock = threading.Lock()
        for r in store.list_renders():           # anything unfinished when we last stopped can't continue
            if r["status"] in ("queued", "running"):
                store.update_render(r["id"], status="failed", finished=now(),
                                    error="The app was restarted before this finished. Please make it again.")
                shutil.rmtree(store.folder("renders", r["id"]), ignore_errors=True)
        self.thread = threading.Thread(target=self._loop, name="renders", daemon=True)
        self.thread.start()

    # ------------------------------------------------------------ public
    def submit(self, body: dict) -> dict:
        req, names = clean_request(self.store, body)
        render_id = self.store.new_id("renders")
        os.makedirs(self.store.folder("renders", render_id))
        name = clean_name(body.get("name")) or default_name(names)
        record = self.store.add_render(render_id, name, req, names)
        self.q.put(render_id)
        return record

    def cancel(self, render_id: str) -> None:
        """Stop a queued or running render. Does nothing if it has already finished."""
        rec = self.store.get_render(render_id)
        if rec["status"] == "queued":
            self.store.update_render(render_id, status="cancelled", finished=now())
        elif rec["status"] == "running":
            with self.lock:
                self.cancel_requested.add(render_id)

    def view(self, rec: dict) -> dict:
        """A render record as the browser sees it, with live progress and queue position."""
        rid = rec["id"]
        status = rec["status"]
        with self.lock:
            done, total = self.progress.get(rid, (0, 0))
        if status == "done":
            fraction = 1.0
        elif status == "running":
            fraction = done / total if total else 0.0
        else:
            fraction = 0.0
        out = {
            "id": rid, "name": rec["name"], "status": status, "error": rec["error"], "progress": round(fraction, 3),
            "created": rec["created"], "finished": rec["finished"], "seconds_taken": rec["seconds_taken"],
            "request": rec["request"], "drawing_names": rec["drawing_names"],
        }
        if status == "queued":
            waiting = sorted((r for r in self.store.list_renders() if r["status"] == "queued"),
                             key=lambda r: r["created"])
            ids = [r["id"] for r in waiting]
            out["queue_position"] = ids.index(rid) + 1 if rid in ids else 1
        if status == "done":
            out["video_url"] = f"/files/renders/{rid}/video.mp4"
            out["poster_url"] = f"/files/renders/{rid}/poster.jpg"
            out["download_url"] = f"/files/renders/{rid}/video.mp4?download=1"
        return out

    def shutdown(self) -> None:
        self.q.put(None)

    # ------------------------------------------------------------ worker
    def _loop(self) -> None:
        while True:
            rid = self.q.get()
            if rid is None:
                return
            try:
                self._run(rid)
            except Exception:                                   # never let one bad job stop the queue
                try:
                    self.store.update_render(rid, status="failed", finished=now(), error="Something went wrong while making the video.")
                except Exception:
                    pass

    def _run(self, rid: str) -> None:
        try:
            rec = self.store.get_render(rid)
        except KeyError:
            return                                              # deleted while waiting
        if rec["status"] != "queued":
            return                                              # cancelled while waiting
        started = time.time()
        self.store.update_render(rid, status="running", started=now())
        folder = self.store.folder("renders", rid)
        partial = os.path.join(folder, "partial.mp4")
        try:
            req = rec["request"]
            layer_sets = []
            for i in req["drawings"]:
                try:
                    layer_sets.append(E.load_layers(self.store.layers_path(i)))
                except (KeyError, OSError):
                    raise G.EngineError("One of the drawings was deleted before the video could be made.")
            settings = make_settings(self.store, req)

            def on_progress(done, total):
                with self.lock:
                    self.progress[rid] = (done, total)
                    if rid in self.cancel_requested:
                        raise Cancelled()

            G.render_video(layer_sets, settings, partial, progress=on_progress, workers=self.workers)
            os.replace(partial, self.store.video_path(rid))
            self._poster(rid)
            self.store.update_render(rid, status="done", finished=now(), seconds_taken=round(time.time() - started, 1))
        except Cancelled:
            self.store.update_render(rid, status="cancelled", finished=now())
        except (G.EngineError, KeyError) as e:
            self.store.update_render(rid, status="failed", finished=now(), error=str(e))
        except Exception:
            self.store.update_render(rid, status="failed", finished=now(), error="Something went wrong while making the video.")
        finally:
            if os.path.exists(partial):
                os.remove(partial)
            with self.lock:
                self.cancel_requested.discard(rid)
                self.progress.pop(rid, None)

    def _poster(self, rid: str) -> None:
        """A still picture from the video to show before it is played."""
        cap = cv2.VideoCapture(self.store.video_path(rid))
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 24
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(fps * 1.5))
            ok, frame = cap.read()
            if not ok:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = cap.read()
            if ok:
                cv2.imwrite(os.path.join(self.store.folder("renders", rid), "poster.jpg"), frame,
                            [cv2.IMWRITE_JPEG_QUALITY, 85])
        finally:
            cap.release()
