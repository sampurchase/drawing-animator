"""The dance engine: everything needed to turn extracted drawings into a video.

Used by the command line (animate.py) and by the web app. Nothing in here prints or exits; problems are
raised as EngineError so the caller can show them however it likes.

    settings = Settings(background="samples/dancefloor.jpg", seconds=8)
    layers = extract_drawing("kid.heic")                  # slow part, can be saved with E.save_layers
    render_video([layers], settings, "out/dance.mp4", progress=lambda done, total: print(done, total))
"""
from __future__ import annotations

import math
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
import os
import subprocess
import tempfile
from dataclasses import dataclass, fields

import cv2
import numpy as np

from . import choreo as C
from . import extract as E
from . import music as M
from . import rig as R
from . import template as T

T_CX = T.CX

# Reference points in template space for placing a character on a floor.
HEAD_Y_T = 380      # top of the hair
FEET_Y_T = 2090     # bottom of the shoes
CHAR_W_T = 1454     # arm tip to arm tip

BACK_SCALE = 0.92   # dancers in a back row are a little smaller...
BACK_DROP = 0.03    # ...and stand this fraction of the frame height further up the floor
EDGE = 0.04         # keep this fraction of the frame width clear at each side


class EngineError(RuntimeError):
    """Something the user can fix (a bad photo, a missing file). The message is meant to be shown."""


class RenderCancelled(Exception):
    """Raise this from a progress callback to stop a render part way."""


@dataclass
class Settings:
    """Everything that controls a video. Field names match the command line options."""
    seconds: float = 16.0
    fps: int = 24
    size: str = "1280x720"
    background: str | None = None
    char_height: float | None = None       # None = automatic
    feet_y: float = 0.94
    bg_anchor: float = 0.7
    travel: float = 0.6
    leg_seconds: float | None = None
    turn_seconds: float | None = None
    choreo: str = "dance"                   # dance | march
    turn: str = "squash"                    # squash | none
    lean: float = 4.0
    mode: str = "unison"                    # unison | mirror | conga
    follow_delay: float | None = None
    stagger: float = 0.0
    bpm: float = 120.0
    music: str = "auto"                     # auto | none | path
    music_offset: float = 0.0

    @classmethod
    def from_namespace(cls, ns) -> "Settings":
        return cls(**{f.name: getattr(ns, f.name) for f in fields(cls) if hasattr(ns, f.name)})


# --------------------------------------------------------------- drawings
def extract_drawing(photo_path: str, debug: dict | None = None) -> list[E.Layer]:
    """Photo of a sheet -> body-part layers. Raises EngineError with a helpful message on failure."""
    try:
        return E.extract_character(E.load_photo(photo_path), debug=debug)
    except E.ExtractError as e:
        raise EngineError(str(e)) from e


# --------------------------------------------------------------- helpers
def ground_view_matrix(slot_x0, slot_w, out_h, char_h, feet_y):
    """Scale so hair-to-feet is char_h * out_h tall, feet at pixel row feet_y, centred in the slot."""
    s = min(char_h * out_h / (FEET_Y_T - HEAD_Y_T), 0.96 * slot_w / CHAR_W_T)
    cx_o = slot_x0 + slot_w / 2
    return np.array([[s, 0, cx_o - s * T_CX],
                     [0, s, feet_y - s * FEET_Y_T],
                     [0, 0, 1]], np.float64), s


def load_background(path, w, h, anchor=0.7):
    """Resize to cover w x h; crop the excess, `anchor` = share cropped from the top."""
    bg = cv2.imread(path, cv2.IMREAD_COLOR)
    if bg is None:
        raise EngineError(f"Could not read background: {path}")
    bg = cv2.cvtColor(bg, cv2.COLOR_BGR2RGB)
    sc = max(w / bg.shape[1], h / bg.shape[0])
    bg = cv2.resize(bg, (int(round(bg.shape[1] * sc)), int(round(bg.shape[0] * sc))), interpolation=cv2.INTER_CUBIC)
    ex, ey = bg.shape[1] - w, bg.shape[0] - h
    x0, y0 = int(round(ex / 2)), int(round(ey * anchor))
    return bg[y0:y0 + h, x0:x0 + w].astype(np.float32)


def darken_shadow(frame, cx, feet_y, rx, ry, strength):
    """Multiply a soft dark ellipse into `frame` (float32 HxWx3) in place."""
    h, w = frame.shape[:2]
    pad = int(ry * 2 + 6)
    x0, x1 = max(0, int(cx - rx - pad)), min(w, int(cx + rx + pad))
    y0, y1 = max(0, int(feet_y - ry - pad)), min(h, int(feet_y + ry + pad))
    if x1 <= x0 or y1 <= y0:
        return
    m = np.zeros((y1 - y0, x1 - x0), np.float32)
    cv2.ellipse(m, (int(cx - x0), int(feet_y - ry * 0.3 - y0)), (max(1, int(rx)), max(1, int(ry))),
                0, 0, 360, 1.0, -1, cv2.LINE_AA)
    m = cv2.GaussianBlur(m, (0, 0), max(2.0, ry * 0.45)) * strength
    frame[y0:y1, x0:x1] *= (1.0 - m[..., None])


def parse_size(size: str) -> tuple[int, int]:
    try:
        w, h = (int(v) for v in size.lower().split("x"))
    except ValueError:
        raise EngineError(f"Bad size '{size}', expected something like 1280x720")
    return w, h


# ------------------------------------------------------------------- path
def _smooth(u):
    return u * u * (3 - 2 * u)


def travel_state(t, leg_s, turn_s, lean_deg, turn_mode="squash"):
    """Position along the path and facing for time t (seconds; may be negative).

    Returns (p, flip_x, lean_deg): p in 0..1 (0 = left end, 1 = right end), flip_x for the
    squash-turn (1 = as drawn, -1 = mirrored), lean to apply to the body in degrees.
    The path is endless: walk right for one leg, turn, walk left for one leg, turn, ...
    """
    k = math.floor(t / leg_s)
    tl = t - k * leg_s
    walk_s = max(1e-3, leg_s - turn_s)
    right = (k % 2 == 0)
    sign = 1.0 if right else -1.0
    mirrored = (turn_mode == "squash")
    base_flip = sign if mirrored else 1.0
    if tl < walk_s:
        u = tl / walk_s
        q = 0.5 * u + 0.5 * _smooth(u)          # gentle ease in/out, mostly steady walking
        ramp = max(0.0, min(1.0, tl / 0.3, (walk_s - tl) / 0.3))
        # The lean is applied before the mirror flip. When the drawing is flipped for the walk
        # back, the flip already turns a clockwise lean into an anticlockwise one, so the sign
        # must NOT also be reversed (doing both made her lean backwards walking left).
        return (q if right else 1 - q), base_flip, (lean_deg if mirrored else sign * lean_deg) * ramp
    u = (tl - walk_s) / max(1e-3, turn_s)
    flip = sign * math.cos(math.pi * u) if mirrored else 1.0
    return (1.0 if right else 0.0), flip, 0.0


# ------------------------------------------------------------- formations
def place_view(s, x_px, feet_px, bottom_t=FEET_Y_T):
    """Template px -> output px: scale s, the bottom of the drawing (template row bottom_t) on pixel row
    feet_px, centre line at x_px. bottom_t is measured per drawing, so short drawings still touch the floor."""
    return np.array([[s, 0, x_px - s * T_CX],
                     [0, s, feet_px - s * bottom_t],
                     [0, 0, 1]], np.float64)


def build_dancers(n, mode, w, h, args, beat_s, leg_s, turn_s):
    """Decide where every drawing stands and how it moves.

    `args` is a Settings (or anything with the same fields). Returns one dict per drawing: feet (pixel
    row of the feet), s (template px -> output px scale) and state(t) -> (x_px, flip, lean_deg,
    beats_late). `beats_late` is how many beats behind the routine this dancer is (always 0 except
    in conga mode).
    """
    s0 = (args.char_height or 0.74) * h / (FEET_Y_T - HEAD_Y_T)
    explicit = args.char_height is not None
    feet_front = args.feet_y * h
    drop = BACK_DROP * h

    def walk(t):
        if args.travel <= 0:
            return 0.5, 1.0, 0.0                     # dancing on the spot: no walking, no turning
        return travel_state(t, leg_s, turn_s, args.lean, args.turn)

    dancers = []

    if mode == "conga":
        late = max(1, round((args.follow_delay or 2 * beat_s) / beat_s))
        lo, hi = w * (0.5 - args.travel / 2), w * (0.5 + args.travel / 2)
        for i in range(n):
            def state(t, i=i):
                p, flip, lean = walk(t - i * late * beat_s)
                return lo + p * (hi - lo), flip, lean, i * late
            dancers.append(dict(feet=feet_front, s=s0, state=state))
        return dancers

    if mode == "unison":
        # Everyone shares one path and one set of moves; each keeps their own lane. Three or more
        # alternate between a front and a back row so neighbours can stand closer without clashing.
        factor = 0.85 if n == 2 else 0.55            # lane spacing, in arm spans
        extent = (n - 1) * factor + 1                # whole group width, in arm spans
        s = s0 if explicit else min(s0, 0.58 * w / (extent * CHAR_W_T))
        group_w = extent * CHAR_W_T * s
        half_range = max(0.0, min(args.travel * w / 2, w / 2 - EDGE * w - group_w / 2))
        for i in range(n):
            back = n >= 3 and i % 2 == 1
            lane = (i - (n - 1) / 2) * factor * CHAR_W_T * s

            def state(t, lane=lane):
                p, flip, lean = walk(t)
                return w / 2 + (p - 0.5) * 2 * half_range + lane, flip, lean, 0
            dancers.append(dict(feet=feet_front - (drop if back else 0),
                                s=s * (BACK_SCALE if back else 1.0), state=state))
        return dancers

    # mirror: dancers pair up (1st+2nd, 3rd+4th, ...). The 1st of a pair is on the left and the 2nd is its
    # exact mirror image on the right. They walk towards each other, turn together, walk apart, turn.
    # Further pairs dance in the same phase, nested a little further out and alternately in the back row
    # (the same trick as the three-or-more unison line). An odd one out dances on the centre line, at the back.
    pairs = n // 2
    span_max = w * (0.35 - EDGE) / (1.1 + 0.55 * max(0, pairs - 1))   # leaves >= 15% of the width to travel
    s = s0 if explicit else min(s0, span_max / CHAR_W_T)
    span = CHAR_W_T * s
    lane_step = 0.55 * span
    inner0 = w / 2 - 0.6 * span                      # nearest to the centre, leaving a gap between arm tips
    room = inner0 - lane_step * max(0, pairs - 1) - EDGE * w - span / 2
    travel_px = 0.0 if args.travel <= 0 else max(0.0, min(args.travel * w / 2, room))
    for i in range(n):
        pair = i // 2
        back = pair % 2 == 1
        if n % 2 == 1 and i == n - 1:
            dancers.append(dict(feet=feet_front - drop, s=s * BACK_SCALE,
                                state=lambda t: (w / 2, 1.0, 0.0, 0)))
            continue
        inner = inner0 - pair * lane_step

        def state(t, inner=inner, right=(i % 2 == 1)):
            p, flip, lean = walk(t)
            xl = inner - travel_px + p * travel_px
            return (w - xl, -flip, lean, 0) if right else (xl, flip, lean, 0)
        dancers.append(dict(feet=feet_front - (drop if back else 0),
                            s=s * (BACK_SCALE if back else 1.0), state=state))
    return dancers


# ------------------------------------------------------------------ scene
class Scene:
    """Drawings + settings, ready to produce frames. Cheap to build, so each worker process makes its own."""

    def __init__(self, layer_sets: list[list[E.Layer]], settings: Settings):
        s = self.settings = settings
        self.w, self.h = parse_size(s.size)
        self.period = 120.0 / s.bpm                       # seconds per full left+right step cycle
        self.beat_s = 60.0 / s.bpm
        leg_seconds = s.leg_seconds or 8 * self.beat_s    # one crossing = 8 beats, the last one is the turn
        turn_seconds = s.turn_seconds or self.beat_s
        self.routine = C.ROUTINE if s.choreo == "dance" else C.MARCH_ROUTINE
        self.puppets = [R.Puppet(layers) for layers in layer_sets]
        n = self.n = len(self.puppets)
        mode = s.mode
        if n == 1 and mode != "unison":
            mode = "unison"                          # nothing to mirror or follow with one drawing
        elif mode == "mirror" and n < 2:
            mode = "unison"
        elif mode == "conga" and s.travel <= 0:
            mode = "unison"                          # a conga line needs somewhere to walk
        self.mode = mode
        if s.background:
            self.base_bg = load_background(s.background, self.w, self.h, s.bg_anchor)
            self.shadow_strength = 0.5
        else:
            self.base_bg = np.full((self.h, self.w, 3), 255, np.float32)
            self.shadow_strength = 0.18
        self.dancers = build_dancers(n, mode, self.w, self.h, s, self.beat_s, leg_seconds, turn_seconds)

    def frame(self, t: float) -> np.ndarray:
        """The picture at time t seconds, as uint8 RGB (h x w x 3)."""
        w, h = self.w, self.h
        bg = self.base_bg.copy()
        placed = []
        for i, d in enumerate(self.dancers):
            x_px, flip, lean, late = d["state"](t)
            placed.append((d["feet"], i, place_view(d["s"], x_px, d["feet"], self.puppets[i].bottom),
                           flip, lean, late))
            darken_shadow(bg, x_px, d["feet"], d["s"] * 330 * max(0.15, abs(flip)), d["s"] * 60,
                          self.shadow_strength)
        canvas = np.zeros((h, w, 4), np.float32)
        # back row first; within a row the first drawing is drawn last, so it is on top
        for feet, i, view, flip, lean, late in sorted(placed, key=lambda r: (r[0], -r[1])):
            phase = (t / self.period + i * self.settings.stagger) % 1.0     # legs: a foot lands on every beat
            pose, spin = C.pose_at(t / self.beat_s - late, phase, lean, self.routine)
            self.puppets[i].render(pose, (w, h), view, flip_x=flip * spin, canvas=canvas)
        out = canvas[..., :3] + bg * (1.0 - canvas[..., 3:4] / 255.0)
        return np.clip(out, 0, 255).astype(np.uint8)


def contact_sheet(layer_sets, settings: Settings, times: list[float], out_png: str) -> None:
    """A grid of frames at the given times, for checking movement without rendering a video."""
    scene = Scene(layer_sets, settings)
    tiles = []
    for t in times:
        img = cv2.resize(scene.frame(t), (scene.w // 2, scene.h // 2), interpolation=cv2.INTER_AREA)
        cv2.putText(img, f"t={t:.1f}s", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        tiles.append(img)
    while len(tiles) % 2:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + 2]) for i in range(0, len(tiles), 2)]
    cv2.imwrite(out_png, cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR))


# ------------------------------------------------------------------ video
_SCENE: Scene | None = None


def _init_worker(layer_sets, settings):
    global _SCENE
    cv2.setNumThreads(1)                      # we run one process per core, so keep each one single-threaded
    _SCENE = Scene(layer_sets, settings)


def _render_one(i):
    return _SCENE.frame(i / _SCENE.settings.fps).tobytes()


def default_workers() -> int:
    return max(1, min((os.cpu_count() or 1) - 1, 6))      # leave a core for ffmpeg


def _stop_ffmpeg(ff: subprocess.Popen) -> None:
    ff.kill()
    try:
        ff.stdin.close()
    except OSError:
        pass
    ff.wait()


def render_video(layer_sets, settings: Settings, out_path: str, progress=None, workers: int | None = None) -> dict:
    """Render the dance to an mp4. `progress(done, total)` is called after every frame.

    Frames are drawn by several worker processes in parallel (one per CPU core by default).
    Returns a small summary dict.
    """
    s = settings
    w, h = parse_size(s.size)
    total = int(round(s.seconds * s.fps))
    duration = total / s.fps
    workers = default_workers() if workers is None else max(1, workers)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    # build one scene up front: validates the settings and the background before any work is started
    scene = Scene(layer_sets, s)

    audio, tmp = None, None
    if s.music == "auto":
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        M.write_wav(tmp.name, M.generate(s.bpm, duration + 0.5))
        audio = tmp.name
    elif s.music != "none":
        if not os.path.exists(s.music):
            raise EngineError(f"Music file not found: {s.music}")
        audio = s.music

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{w}x{h}", "-r", str(s.fps), "-i", "-"]
    if audio:
        cmd += ["-ss", str(s.music_offset), "-i", audio, "-map", "0:v", "-map", "1:a",
                "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-t", f"{duration:.3f}", out_path]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    pool = None
    try:
        if workers > 1 and total >= 2 * workers:
            pool = ProcessPoolExecutor(workers, mp_context=mp.get_context("spawn"),
                                       initializer=_init_worker, initargs=(layer_sets, s))
            frames = pool.map(_render_one, range(total), chunksize=2)
        else:
            frames = (scene.frame(f / s.fps).tobytes() for f in range(total))
        for done, data in enumerate(frames, 1):
            ff.stdin.write(data)
            if progress:
                progress(done, total)
        ff.stdin.close()
        rc = ff.wait()
    except BrokenPipeError:
        rc = ff.wait()
    except BrokenProcessPool:
        _stop_ffmpeg(ff)
        raise EngineError("A rendering process stopped unexpectedly (out of memory?). Try --workers 1.")
    except BaseException:                      # includes a cancel raised from the progress callback
        _stop_ffmpeg(ff)
        if os.path.exists(out_path):
            os.unlink(out_path)                # never leave a half-written video behind
        raise
    finally:
        if pool:
            pool.shutdown(wait=False, cancel_futures=True)
        if tmp:
            os.unlink(tmp.name)
    if rc != 0:
        raise EngineError("ffmpeg failed while writing the video")
    return dict(frames=total, fps=s.fps, characters=scene.n, mode=scene.mode, audio=bool(audio), out=out_path)
