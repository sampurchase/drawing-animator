"""Choreography: named dance moves keyed to the beat, strung together into a routine.

The legs always do the beat-locked march from rig.march_pose (a foot lands on every beat).
A *move* only controls the upper body: arms, torso lean, head, a little sideways shift or hop,
and optionally a spin. Moves are plain functions of `b`, the number of beats since the move began,
so they stay on the beat whatever the tempo.

Arm angles use a mirrored "up" convention so both arms read the same way:
    up_deg   0 = arm straight out sideways,  +90 = straight up,  -90 = hanging down,
             beyond -90 swings the arm across the front of the body
    bend_deg forearm bend relative to the upper arm, + = hand lifts, - = hand folds toward the body

Add a move: write a function returning an `Upper`, register it in MOVES, then use it in ROUTINE.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, fields

from . import rig as R

TAU = 2 * math.pi


@dataclass
class Upper:
    up_R: float = 0.0       # character's right arm (the viewer's left)
    up_L: float = 0.0
    bend_R: float = 0.0
    bend_L: float = 0.0
    torso: float = 0.0      # extra torso rotation, degrees, + = clockwise on screen
    head: float = 0.0
    dx: float = 0.0         # sideways body shift, template px
    dy: float = 0.0         # vertical shift, template px (negative = up)
    flip: float = 1.0       # 1 = facing front, 0 = edge-on, -1 = mirrored (spin)
    arms_front: bool = False


def _lerp(a: Upper, b: Upper, w: float) -> Upper:
    out = Upper()
    for f in fields(Upper):
        if f.name == "arms_front":
            continue
        setattr(out, f.name, getattr(a, f.name) * (1 - w) + getattr(b, f.name) * w)
    out.arms_front = b.arms_front if w >= 0.5 else a.arms_front
    return out


def _smooth(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


# ------------------------------------------------------------------- moves
def arms_out(b, **_):
    """Plain T-pose arms. Used on the turn-around beat so the spin reads cleanly."""
    return Upper(up_R=4 * math.sin(math.pi * b), up_L=-4 * math.sin(math.pi * b))


def march(b, **_):
    """The original: arms swing opposite to the legs."""
    s = math.sin(math.pi * b)
    f = -13.2 * math.sin(math.pi * b - 0.8)
    return Upper(up_R=-24 * s, up_L=24 * s, bend_R=f, bend_L=f)


def swing_across(b, amp=75.0, **_):
    """Both arms sweep from one side to the other across the body, hitting each side on a beat."""
    s = -math.cos(math.pi * b)                   # -1 (left) at b=0, +1 (right) at b=1, ...
    cross_R, cross_L = max(0.0, s), max(0.0, -s)  # which arm is currently crossing the chest
    return Upper(up_R=-45 - amp * s, up_L=-45 + amp * s,
                 bend_R=-25 * cross_R + 15 * (1 - cross_R) * cross_L,
                 bend_L=-25 * cross_L + 15 * (1 - cross_L) * cross_R,
                 torso=7 * s, head=-3 * s, dx=14 * s, arms_front=True)


def wave(b, side="R", **_):
    """One arm up, hand waving every beat; the other hand rests on the hip."""
    sg = 1.0 if side == "R" else -1.0           # sign used to tilt the head toward the waving hand
    up_wave = 82 + 6 * math.sin(TAU * b)
    bend_wave = 38 * math.sin(TAU * b)
    hip_up, hip_bend = -50 + 3 * math.sin(math.pi * b), -95
    if side == "R":
        return Upper(up_R=up_wave, bend_R=bend_wave, up_L=hip_up, bend_L=hip_bend,
                     torso=-3, head=-6 * sg, arms_front=True)
    return Upper(up_L=up_wave, bend_L=bend_wave, up_R=hip_up, bend_R=hip_bend,
                 torso=3, head=-6 * sg, arms_front=True)


def point(b, side="R", **_):
    """Disco point: one arm sweeps from high diagonal to low diagonal and back; other hand on hip."""
    sg = 1.0 if side == "R" else -1.0
    c = math.cos(math.pi * b)                    # +1 high on the beat, -1 low a beat later
    up_p = 8 + 43 * c
    hip_up, hip_bend = -50, -95
    if side == "R":
        return Upper(up_R=up_p, bend_R=4, up_L=hip_up, bend_L=hip_bend,
                     torso=-4 * c, head=-4 * sg * c, dx=-8 * c, arms_front=True)
    return Upper(up_L=up_p, bend_L=4, up_R=hip_up, bend_R=hip_bend,
                 torso=4 * c, head=-4 * sg * c, dx=8 * c, arms_front=True)


def pump(b, **_):
    """Raise the roof: both arms up, hands pumping every beat, body bouncing."""
    p = math.sin(TAU * b)
    return Upper(up_R=62, up_L=62, bend_R=30 * p, bend_L=30 * p,
                 dy=-12 * abs(math.sin(math.pi * b)), arms_front=True)


def clap_over(b, **_):
    """Arms open and meet above the head, clapping on every beat."""
    up = 85 + 20 * math.cos(TAU * b)             # 105 (hands meet) on the beat, 65 half a beat later
    return Upper(up_R=up, up_L=up, dy=-8 * (0.5 + 0.5 * math.cos(TAU * b)), arms_front=True)


def shimmy(b, **_):
    """Hips sway side to side, shoulders counter-rotate, hands low and loose."""
    s = math.sin(math.pi * b)
    q = math.sin(TAU * b)
    return Upper(up_R=-38 + 10 * q, up_L=-38 - 10 * q, bend_R=-20, bend_L=-20,
                 torso=-6 * s, head=4 * s, dx=26 * s, dy=-6 * abs(q), arms_front=True)


def twirl(b, **_):
    """A full spin in place over two beats, arms up in a ring."""
    spin = math.cos(math.pi * b)                 # 1 -> -1 -> 1 across b = 0..2
    return Upper(up_R=100, up_L=100, bend_R=-12, bend_L=-12,
                 dy=-18 * math.sin(math.pi * b), flip=spin, arms_front=True)


MOVES = {f.__name__: f for f in
         (arms_out, march, swing_across, wave, point, pump, clap_over, shimmy, twirl)}

# ----------------------------------------------------------------- routine
# (move name, beats, options). One crossing is 8 beats: 7 of dancing and a 1-beat turn at the end.
# Total 32 beats = 16 s at 120 bpm; it repeats.
ROUTINE = [
    ("swing_across", 4, {}), ("wave", 3, {"side": "R"}), ("arms_out", 1, {}),
    ("point", 4, {"side": "R"}), ("pump", 3, {}), ("arms_out", 1, {}),
    ("swing_across", 4, {}), ("wave", 3, {"side": "L"}), ("arms_out", 1, {}),
    ("clap_over", 4, {}), ("twirl", 2, {}), ("shimmy", 1, {}), ("arms_out", 1, {}),
]
BLEND_BEATS = 0.5

MARCH_ROUTINE = [("march", 8, {})]


def _upper_at(routine, beats: float) -> Upper:
    total = sum(d for _, d, _ in routine)
    beats = beats % total
    start = 0.0
    for i, (name, dur, opts) in enumerate(routine):
        if beats < start + dur:
            b = beats - start
            cur = MOVES[name](b, **opts)
            if b < BLEND_BEATS:
                pname, pdur, popts = routine[i - 1]            # i-1 wraps to the last move at i=0
                prev = MOVES[pname](pdur + b, **popts)
                cur = _lerp(prev, cur, _smooth(b / BLEND_BEATS))
            return cur
        start += dur
    return Upper()


def pose_at(beats: float, leg_phase: float, lean_deg: float = 0.0, routine=None) -> tuple[R.Pose, float]:
    """Pose for a moment `beats` into the routine, with the legs at `leg_phase` (0..1 per 2 beats).

    Returns (pose, flip_x). flip_x is 1 facing front; multiply it into any other turn.
    """
    routine = routine or ROUTINE
    u = _upper_at(routine, beats)
    pose = R.march_pose(leg_phase, lean_deg=lean_deg)
    rot = pose.rot
    rot["upper_arm_R"] = u.up_R
    rot["upper_arm_L"] = -u.up_L
    rot["forearm_R"] = u.bend_R
    rot["forearm_L"] = -u.bend_L
    rot["torso"] = rot.get("torso", 0.0) + u.torso
    rot["head"] = rot.get("head", 0.0) + u.head
    ox, oy = pose.root_offset
    pose.root_offset = (ox + u.dx, oy + u.dy)
    pose.arms_front = u.arms_front
    return pose, u.flip
