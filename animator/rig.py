"""2D puppet rig: poses for a march cycle and rendering of the cut-out body parts.

Each part has a full transform F (rotation + scale about its pivot) and a rigid
transform G (rotation only). A child hangs off its parent's *full* transform at its
joint, but only inherits the parent's *rigid* motion, so a leg that foreshortens
(knee lifting toward the camera) does not squash the shin as well.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import template as T
from .extract import Layer


# --------------------------------------------------------------- matrices
def _trans(tx, ty):
    return np.array([[1, 0, tx], [0, 1, ty], [0, 0, 1]], np.float64)


def _rot(deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], np.float64)


def _scale(sx, sy):
    return np.array([[sx, 0, 0], [0, sy, 0], [0, 0, 1]], np.float64)


def _about(p, m):
    """Apply linear matrix m about point p."""
    return _trans(*p) @ m @ _trans(-p[0], -p[1])


@dataclass
class Pose:
    root_offset: tuple[float, float] = (0.0, 0.0)
    rot: dict[str, float] = field(default_factory=dict)       # degrees, relative to parent
    scale_y: dict[str, float] = field(default_factory=dict)   # foreshortening along y
    arms_front: bool = False   # draw the arms over the torso (for moves that cross the body)


def solve(pose: Pose, version: int = T.DEFAULT_VERSION) -> dict[str, np.ndarray]:
    """Return the full 3x3 transform (template px -> template px) of every part."""
    pivots = T.layout(version).pivots
    full: dict[str, np.ndarray] = {}
    rigid: dict[str, np.ndarray] = {}

    def visit(name):
        if name in full:
            return
        parent = T.PARENT[name]
        p = pivots[name]
        if parent is None:
            base = _trans(*pose.root_offset)
        else:
            visit(parent)
            pv = np.array([p[0], p[1], 1.0])
            moved = full[parent] @ pv          # where the joint ends up
            held = rigid[parent] @ pv          # where rigid-only inheritance would put it
            base = _trans(moved[0] - held[0], moved[1] - held[1]) @ rigid[parent]
        r = _rot(pose.rot.get(name, 0.0))
        s = _scale(1.0, pose.scale_y.get(name, 1.0))
        full[name] = base @ _about(p, r @ s)
        rigid[name] = base @ _about(p, r)

    for n in T.PART_ORDER:
        visit(n)
    return full


# ------------------------------------------------------------ march cycle
def march_pose(phase: float, *, step_deg: float = 14.0, knee_deg: float = 22.0,
               lift_squash: float = 0.32, arm_deg: float = 24.0, bob_px: float = 16.0,
               sway_deg: float = 2.5, lean_deg: float = 0.0) -> Pose:
    """phase in [0, 1): one full left+right step cycle."""
    ph = 2 * math.pi * phase
    s = math.sin(ph)
    lift_R = max(0.0, s)         # character's right leg lifts first (viewer's left)
    lift_L = max(0.0, -s)
    # ease the lifts so feet plant softly
    lift_R = lift_R ** 0.8
    lift_L = lift_L ** 0.8
    rot, sy = {}, {}
    rot["thigh_R"], rot["shin_R"] = +step_deg * lift_R, -knee_deg * lift_R
    rot["thigh_L"], rot["shin_L"] = -step_deg * lift_L, +knee_deg * lift_L
    sy["thigh_R"], sy["thigh_L"] = 1 - lift_squash * lift_R, 1 - lift_squash * lift_L
    # arms swing opposite to the legs; for both arms negative-of-sin raises the proper one
    rot["upper_arm_R"] = -arm_deg * s
    rot["upper_arm_L"] = -arm_deg * s
    rot["forearm_R"] = -0.55 * arm_deg * math.sin(ph - 0.8)
    rot["forearm_L"] = -0.55 * arm_deg * math.sin(ph - 0.8)
    rot["torso"] = sway_deg * s + lean_deg        # lean_deg: tilt the whole body into the direction of travel
    rot["head"] = -1.6 * sway_deg * math.sin(ph - 0.5) - 0.4 * lean_deg
    bob = -bob_px * abs(s)       # body rises while a foot is up
    return Pose(root_offset=(0.0, bob), rot=rot, scale_y=sy)


# ----------------------------------------------------------------- render
@dataclass
class Puppet:
    layers: list[Layer]

    @property
    def version(self) -> int:
        return self.layers[0].version if self.layers else T.DEFAULT_VERSION

    @property
    def bottom(self) -> float:
        """Lowest drawn row of the resting figure, in template px (where the feet really are)."""
        if not hasattr(self, "_bottom"):
            low = None
            for l in self.layers:
                a = l.rgba[..., 3]
                rows = np.nonzero((a > 128).any(axis=1))[0]
                if len(rows):
                    y = l.origin[1] + int(rows.max()) + 1
                    low = y if low is None else max(low, y)
            self._bottom = float(low if low is not None else T.layout(self.version).foot[3])
        return self._bottom

    def _premult(self):
        out = []
        for l in self.layers:
            f = l.rgba.astype(np.float32)
            f[..., :3] *= f[..., 3:4] / 255.0
            out.append(f)
        return out

    def render(self, pose: Pose, out_size: tuple[int, int], view: np.ndarray,
               flip_x: float = 1.0, canvas: np.ndarray | None = None) -> np.ndarray:
        """Draw onto a premultiplied float32 RGBA canvas (h x w x 4) and return it.

        `view` is a 3x3 matrix taking template px to output px (pan/zoom).
        `flip_x` squashes the whole figure horizontally about its centre line: 1 = normal,
        0 = edge-on, -1 = mirrored. Sweeping 1 -> -1 looks like a paper puppet turning round.
        If `canvas` is given the figure is drawn over what is already there, in place, so several
        dancers can share one canvas. Each body part is only warped into the small box it covers.
        """
        if not hasattr(self, "_pm"):
            self._pm = self._premult()
        w, h = out_size
        if canvas is None:
            canvas = np.zeros((h, w, 4), np.float32)
        full = solve(pose, self.version)
        if abs(flip_x) < 0.10:       # never fully edge-on, so a turn reads as a thin sliver, not a vanish
            flip_x = 0.10 if flip_x >= 0 else -0.10
        A = _about((T.CX, 0.0), _scale(flip_x, 1.0))
        by_name = {l.name: (l, pm) for l, pm in zip(self.layers, self._pm)}
        order = list(T.PART_ORDER)
        if pose.arms_front:
            # legs, torso, then arms, then head: arms cross the chest but stay under the face
            arms = [n for n in order if "arm" in n]
            order = [n for n in order if "arm" not in n and n != "head"] + arms + ["head"]
        for name in order:
            layer, pm = by_name[name]
            if layer.rgba.shape[0] <= 1:
                continue
            ox, oy = layer.origin
            M = view @ A @ full[layer.name] @ _trans(ox, oy)   # layer px -> output px
            lh, lw = pm.shape[:2]
            corners = M @ np.array([[0, lw, lw, 0], [0, 0, lh, lh], [1, 1, 1, 1]], np.float64)
            x0 = max(0, int(math.floor(corners[0].min())) - 1)
            x1 = min(w, int(math.ceil(corners[0].max())) + 2)
            y0 = max(0, int(math.floor(corners[1].min())) - 1)
            y1 = min(h, int(math.ceil(corners[1].max())) + 2)
            if x1 <= x0 or y1 <= y0:
                continue
            M2 = M.copy()
            M2[0, 2] -= x0
            M2[1, 2] -= y0
            warped = cv2.warpAffine(pm, M2[:2], (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR,
                                    borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
            sub = canvas[y0:y1, x0:x1]
            sub *= (1.0 - warped[..., 3:4] / 255.0)
            sub += warped
        return canvas


def over_white(premult_rgba: np.ndarray) -> np.ndarray:
    """Composite a premultiplied RGBA float image onto white -> uint8 RGB."""
    a = premult_rgba[..., 3:4] / 255.0
    rgb = premult_rgba[..., :3] + 255.0 * (1.0 - a)
    return np.clip(rgb, 0, 255).astype(np.uint8)
