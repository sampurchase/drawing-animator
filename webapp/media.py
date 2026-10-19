"""Backgrounds and music: checking what was uploaded and saving it."""
from __future__ import annotations

import os
import shutil
import subprocess

import cv2
import numpy as np

from .store import Store, clean_name

MAX_BG_WIDTH = 1920
BG_THUMB_WIDTH = 320
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".oga", ".flac", ".mp4", ".caf", ".aif", ".aiff"}
MIN_BPM, MAX_BPM = 40.0, 220.0
MAX_TRACK_SECONDS = 20 * 60


class BadMedia(Exception):
    """The upload can't be used. The message is written to be shown on screen."""


# ---------------------------------------------------------------- backgrounds
def save_background(store: Store, data: bytes, name: str = "") -> dict:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if data else None
    if img is None:
        raise BadMedia("I couldn't read that picture. Please choose a JPEG or PNG.")
    h, w = img.shape[:2]
    if w < 320 or h < 180:
        raise BadMedia("That picture is too small to use as a background.")
    if w > MAX_BG_WIDTH:
        img = cv2.resize(img, (MAX_BG_WIDTH, round(h * MAX_BG_WIDTH / w)), interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
    bg_id = store.new_id("backgrounds")
    folder = store.folder("backgrounds", bg_id)
    os.makedirs(folder)
    try:
        cv2.imwrite(os.path.join(folder, "image.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        thumb = cv2.resize(img, (BG_THUMB_WIDTH, max(1, round(h * BG_THUMB_WIDTH / w))), interpolation=cv2.INTER_AREA)
        cv2.imwrite(os.path.join(folder, "thumb.jpg"), thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return store.add_background(bg_id, name or "My background")
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def seed_starter_background(store: Store) -> None:
    """On a brand new data folder, add one background so the app is usable straight away."""
    if store.get_meta("seeded_backgrounds"):
        return
    store.set_meta("seeded_backgrounds", "1")
    path = os.path.join(os.path.dirname(__file__), "starter", "dancefloor.jpg")
    if os.path.exists(path) and not store.list_backgrounds():
        with open(path, "rb") as f:
            save_background(store, f.read(), "Disco dance floor")


# ---------------------------------------------------------------- music
def clamp_bpm(value) -> float:
    try:
        bpm = float(value)
    except (TypeError, ValueError):
        raise BadMedia("The tempo (beats per minute) should be a number, like 120.")
    if not MIN_BPM <= bpm <= MAX_BPM:
        raise BadMedia(f"The tempo should be between {MIN_BPM:g} and {MAX_BPM:g} beats per minute.")
    return bpm


def probe_duration(path: str) -> float:
    """Length in seconds of an audio file, or raise BadMedia if it isn't playable audio."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path], capture_output=True, text=True, timeout=30)
        duration = float(out.stdout.strip())
    except (ValueError, subprocess.SubprocessError, OSError):
        raise BadMedia("I couldn't read that music file. Try an MP3, M4A or WAV.")
    if not duration > 0:
        raise BadMedia("I couldn't read that music file. Try an MP3, M4A or WAV.")
    return duration


def save_music(store: Store, data: bytes, filename: str, name: str, bpm) -> dict:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in AUDIO_EXTS:
        raise BadMedia("That doesn't look like a music file. Try an MP3, M4A or WAV.")
    bpm = clamp_bpm(bpm)
    music_id = store.new_id("music")
    folder = store.folder("music", music_id)
    os.makedirs(folder)
    try:
        path = os.path.join(folder, f"track{ext}")
        with open(path, "wb") as f:
            f.write(data)
        duration = probe_duration(path)
        if duration > MAX_TRACK_SECONDS:
            raise BadMedia("That track is very long. Please use one under 20 minutes.")
        default_name = clean_name(os.path.splitext(os.path.basename(filename))[0]) or "My music"
        return store.add_music(music_id, name or default_name, bpm, duration, ext)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
