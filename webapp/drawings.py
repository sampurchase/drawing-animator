"""Turn an uploaded photo into a saved drawing."""
from __future__ import annotations

import os
import shutil
import threading

import cv2
import numpy as np

from animator import engine as G
from animator import extract as E
from animator import template as T

from .store import Store

# Reading a photo is heavy (a few seconds of CPU), so only one at a time; others wait their turn.
_extract_lock = threading.Lock()

HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1"}
THUMB_SIDE = 480


class BadPhoto(Exception):
    """The upload can't be used. The message is written to be shown to a child or parent."""


def sniff_extension(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[4:8] == b"ftyp" and data[8:12] in HEIC_BRANDS:
        return ".heic"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    raise BadPhoto("That doesn't look like a photo. Please choose a picture from your camera (JPEG, PNG or HEIC).")


def _crop_to_drawing(rgba: np.ndarray, pad: int = 10) -> np.ndarray:
    ys, xs = np.nonzero(rgba[..., 3] > 8)
    if len(xs) == 0:
        return rgba
    y0, y1 = max(0, ys.min() - pad), min(rgba.shape[0], ys.max() + 1 + pad)
    x0, x1 = max(0, xs.min() - pad), min(rgba.shape[1], xs.max() + 1 + pad)
    return rgba[y0:y1, x0:x1]


def save_drawing(store: Store, data: bytes, name: str = "") -> dict:
    """Extract the drawing from the photo bytes and save everything. Raises BadPhoto with a friendly message."""
    ext = sniff_extension(data)
    drawing_id = store.new_id("drawings")
    folder = store.drawing_dir(drawing_id)
    os.makedirs(folder)
    try:
        photo_path = os.path.join(folder, f"photo{ext}")
        with open(photo_path, "wb") as f:
            f.write(data)
        dbg: dict = {}
        with _extract_lock:
            try:
                layers = G.extract_drawing(photo_path, debug=dbg)
            except G.EngineError as e:
                raise BadPhoto(str(e)) from e
            except Exception as e:                      # unreadable image data, etc.
                raise BadPhoto("I couldn't read that photo. Please try taking it again.") from e
        E.save_layers(layers, os.path.join(folder, "layers.npz"))
        cutout = _crop_to_drawing(dbg["cutout"])
        bgra = cv2.cvtColor(cutout, cv2.COLOR_RGBA2BGRA)
        cv2.imwrite(os.path.join(folder, "cutout.png"), bgra)
        scale = THUMB_SIDE / max(cutout.shape[:2])
        thumb = cv2.resize(bgra, (max(1, round(cutout.shape[1] * scale)), max(1, round(cutout.shape[0] * scale))),
                           interpolation=cv2.INTER_AREA) if scale < 1 else bgra
        cv2.imwrite(os.path.join(folder, "thumb.png"), thumb)
        layout = T.layout(layers[0].version)
        return store.add(drawing_id, name, layout.name, layout.version)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)       # never leave half a drawing behind
        raise
