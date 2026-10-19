"""Printable character template: geometry, body-part masks and the A4 sheet.

All coordinates are in "template pixels": A4 at 200 dpi (1654 x 2339).
The character is drawn arms-out, front-on. "R"/"L" are the character's own
right/left, so R is on the viewer's left. The figure is symmetric about
x = CX, so mirroring a point is x -> W - x.

There are several template versions. Each uses its own set of four corner markers, so a photo of a
sheet says which version it is and the right geometry is picked automatically:

    original   the first tall, narrow figure (kept so existing drawings still work)
    hero       a sturdy all-rounder (default)
    huggable   a big round body, small head, stubby limbs (marshmallow robots, blob monsters)
    dancer     a slim figure with long arms and long legs

To tweak a version, edit its numbers in LAYOUTS below. Rectangles are (x0, y0, x1, y1) for the
character's right side (the viewer's left); the left side is the mirror image.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1654, 2339
CX = W // 2
DPI = 200

# Light grey outline colour (printed). Kept clearly lighter than any marker ink
# so the extractor can treat it as paper.
OUTLINE_GREY = 190
OUTLINE_WIDTH = 5

# ArUco corner markers used to straighten the photo (same positions in every version).
MARKER_SIZE = 150
MARKER_MARGIN = 60
MARKER_KEYS = ("tl", "tr", "br", "bl")


def marker_origin(key: str) -> tuple[int, int]:
    x = MARKER_MARGIN if key in ("tl", "bl") else W - MARKER_MARGIN - MARKER_SIZE
    y = MARKER_MARGIN if key in ("tl", "tr") else H - MARKER_MARGIN - MARKER_SIZE
    return x, y


def marker_corners(key: str) -> np.ndarray:
    """Four corners (TL, TR, BR, BL order, as ArUco reports) in template px."""
    x, y = marker_origin(key)
    s = MARKER_SIZE
    return np.array([[x, y], [x + s, y], [x + s, y + s], [x, y + s]], np.float32)


# --------------------------------------------------------------------------
# Body parts. Order here is the paint order (back to front) when animating.
# --------------------------------------------------------------------------
PART_ORDER = [
    "thigh_R", "shin_R", "thigh_L", "shin_L",
    "upper_arm_R", "forearm_R", "upper_arm_L", "forearm_L",
    "torso", "head",
]

# Parent of each part in the skeleton (None = root).
PARENT = {
    "torso": None,
    "head": "torso",
    "upper_arm_R": "torso", "forearm_R": "upper_arm_R",
    "upper_arm_L": "torso", "forearm_L": "upper_arm_L",
    "thigh_R": "torso", "shin_R": "thigh_R",
    "thigh_L": "torso", "shin_L": "thigh_L",
}


@dataclass(frozen=True)
class Layout:
    version: int
    name: str                 # friendly name of the sheet
    marker_ids: dict          # corner key -> ArUco id
    head: tuple               # (centre y, radius), circle centred on x = CX
    torso: tuple              # (half width, top y, bottom y)
    upper_arm: tuple          # rect, character's right side
    forearm: tuple            # rect
    hand: tuple               # (centre x, centre y, radius)
    thigh: tuple              # rect
    shin: tuple               # rect
    foot: tuple               # rounded-rect box
    foot_radius: int
    torso_radius: int         # corner rounding of the torso
    pivots: dict              # joint of every part, template px. A part rotates about its pivot.
    title: str = "Draw your character!"   # printed at the top of the sheet


def _pivots(torso, head, shoulder, elbow, hip, knee):
    """Joint table from the right-side joint positions (the left side is mirrored)."""
    return {
        "torso": torso, "head": head,
        "upper_arm_R": shoulder, "forearm_R": elbow,
        "upper_arm_L": (W - shoulder[0], shoulder[1]), "forearm_L": (W - elbow[0], elbow[1]),
        "thigh_R": hip, "shin_R": knee,
        "thigh_L": (W - hip[0], hip[1]), "shin_L": (W - knee[0], knee[1]),
    }


LAYOUTS = {
    1: Layout(
        version=1, name="original",
        marker_ids={"tl": 0, "tr": 1, "br": 2, "bl": 3},
        head=(620, 165),
        torso=(160, 770, 1340),
        upper_arm=(427, 800, 690, 940),
        forearm=(270, 800, 440, 940),
        hand=(235, 870, 88),
        thigh=(667, 1320, 812, 1710),
        shin=(667, 1700, 812, 2030),
        foot=(590, 1985, 810, 2090), foot_radius=50, torso_radius=0,
        pivots=_pivots(torso=(CX, 1330), head=(CX, 790), shoulder=(680, 870), elbow=(437, 870),
                       hip=(740, 1345), knee=(740, 1705)),
    ),
    # Hero: the all-rounder. A sturdy person shape with room for costumes, robots and capes.
    2: Layout(
        version=2,
        marker_ids={"tl": 4, "tr": 5, "br": 6, "bl": 7},
        head=(570, 200),
        torso=(357, 780, 1480), torso_radius=80,
        upper_arm=(383, 830, 493, 1090),
        forearm=(278, 830, 393, 1090),
        hand=(278, 960, 105),
        thigh=(470, 1470, 797, 1790),
        shin=(470, 1780, 797, 1990),
        foot=(330, 1950, 797, 2090), foot_radius=50,
        pivots=_pivots(torso=(CX, 1470), head=(CX, 780), shoulder=(478, 960), elbow=(388, 960),
                       hip=(640, 1490), knee=(635, 1785)),
        name="hero", title="Draw your hero!",
    ),
    # Huggable: a big round body with a small head and stubby limbs (a marshmallow robot, a blob monster).
    3: Layout(
        version=3,
        marker_ids={"tl": 8, "tr": 9, "br": 10, "bl": 11},
        head=(600, 175),
        torso=(520, 740, 1560), torso_radius=330,
        upper_arm=(330, 900, 440, 1130),
        forearm=(205, 900, 340, 1130),
        hand=(205, 1015, 95),
        thigh=(497, 1540, 797, 1830),
        shin=(497, 1820, 797, 2000),
        foot=(357, 1960, 797, 2090), foot_radius=50,
        pivots=_pivots(torso=(CX, 1540), head=(CX, 760), shoulder=(425, 1015), elbow=(335, 1015),
                       hip=(660, 1560), knee=(650, 1825)),
        name="huggable", title="Draw your huggable buddy!",
    ),
    # Dancer: a slim figure with a short body, long arms and long legs (ballerinas, skaters, tall characters).
    4: Layout(
        version=4,
        marker_ids={"tl": 12, "tr": 13, "br": 14, "bl": 15},
        head=(610, 180),
        torso=(220, 790, 1260), torso_radius=40,
        upper_arm=(400, 810, 625, 950),
        forearm=(225, 810, 415, 950),
        hand=(205, 880, 88),
        thigh=(607, 1240, 807, 1700),
        shin=(607, 1690, 807, 2030),
        foot=(520, 1985, 807, 2090), foot_radius=50,
        pivots=_pivots(torso=(CX, 1250), head=(CX, 800), shoulder=(615, 880), elbow=(410, 880),
                       hip=(705, 1255), knee=(705, 1695)),
        name="dancer", title="Draw your dancer!",
    ),
}
DEFAULT_VERSION = 2
STYLES = {l.name: v for v, l in LAYOUTS.items()}     # name -> version number


def layout(version: int | None = None) -> Layout:
    v = DEFAULT_VERSION if version is None else version
    if v not in LAYOUTS:
        raise ValueError(f"unknown template version {v}; known: {sorted(LAYOUTS)}")
    return LAYOUTS[v]


def _mirror_box(box):
    x0, y0, x1, y1 = box
    return (W - x1, y0, W - x0, y1)


def _draw_part(name: str, L: Layout) -> Image.Image:
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    side = name[-1] if name[-1] in "RL" else None
    base = name[:-2] if side else name

    def rect(box):
        b = _mirror_box(box) if side == "L" else box
        d.rectangle(b, fill=255)

    def circle(cx, cy, r):
        if side == "L":
            cx = W - cx
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)

    def rrect(box, r):
        b = _mirror_box(box) if side == "L" else box
        d.rounded_rectangle(b, radius=r, fill=255)

    if base == "head":
        cy, r = L.head
        d.ellipse((CX - r, cy - r, CX + r, cy + r), fill=255)
    elif base == "torso":
        half, top, bottom = L.torso
        d.rounded_rectangle((CX - half, top, CX + half, bottom), radius=L.torso_radius, fill=255)
    elif base == "upper_arm":
        rect(L.upper_arm)
    elif base == "forearm":
        rect(L.forearm)
        circle(*L.hand)                    # hand
    elif base == "thigh":
        rect(L.thigh)
    elif base == "shin":
        rect(L.shin)
        rrect(L.foot, L.foot_radius)       # foot, pointing outward
    return m


def part_masks(version: int | None = None) -> dict[str, np.ndarray]:
    """Binary (0/255) uint8 mask of every body part, H x W."""
    L = layout(version)
    return {n: (np.array(_draw_part(n, L)) > 127).astype(np.uint8) * 255 for n in PART_ORDER}


def silhouette_mask(version: int | None = None) -> np.ndarray:
    masks = part_masks(version)
    out = np.zeros((H, W), np.uint8)
    for m in masks.values():
        out = np.maximum(out, m)
    return out


# --------------------------------------------------------------------------
# The printable sheet
# --------------------------------------------------------------------------
def _font(size: int):
    for p in ("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf",
              "/System/Library/Fonts/Helvetica.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_template(title: str | None = None, version: int | None = None) -> Image.Image:
    L = layout(version)
    title = title or L.title
    sheet = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(sheet)

    # Outline of the whole silhouette in light grey.
    sil = silhouette_mask(L.version)
    contours, _ = cv2.findContours(sil, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    arr = np.array(sheet)
    cv2.polylines(arr, contours, True, (OUTLINE_GREY,) * 3, OUTLINE_WIDTH, cv2.LINE_AA)
    sheet = Image.fromarray(arr)
    d = ImageDraw.Draw(sheet)

    # Corner markers on a white quiet zone. The ids tell the software which version of the sheet it is.
    aruco = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for key, mid in L.marker_ids.items():
        x, y = marker_origin(key)
        img = cv2.aruco.generateImageMarker(aruco, mid, MARKER_SIZE)
        sheet.paste(Image.fromarray(img).convert("RGB"), (x, y))

    # Title (kept well away from the figure) and a hint line.
    size = 84
    f = _font(size)
    while d.textlength(title, font=f) > W - 2 * (MARKER_MARGIN + MARKER_SIZE + 40) and size > 40:
        size -= 4                         # long titles shrink so they never touch the corner markers
        f = _font(size)
    tw = d.textlength(title, font=f)
    d.text(((W - tw) / 2, 230 if L.version == 1 else 125), title, fill=(60, 60, 60), font=f)
    f2 = _font(38)
    hint = "Colour inside the grey lines, then take a photo!"
    hw = d.textlength(hint, font=f2)
    d.text(((W - hw) / 2, 2190 if L.version == 1 else 2215), hint, fill=(120, 120, 120), font=f2)
    return sheet


def layout_by_name(name: str) -> Layout:
    for L in LAYOUTS.values():
        if L.name == name:
            return L
    raise ValueError(f"unknown template '{name}'; known: {[l.name for l in LAYOUTS.values()]}")


if __name__ == "__main__":
    import argparse, os
    names = [L.name for L in LAYOUTS.values()]
    ap = argparse.ArgumentParser(description="Write the printable templates as PNG and PDF.")
    ap.add_argument("which", nargs="?", default="all", choices=names + ["all"],
                    help="which template (default: all of them except the legacy 'original')")
    ap.add_argument("--out", default="templates", help="output folder")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    todo = [L for L in LAYOUTS.values() if a.which == L.name or (a.which == "all" and L.name != "original")]
    for L in todo:
        sheet = make_template(version=L.version)
        sheet.save(f"{a.out}/template_{L.name}.png")
        sheet.save(f"{a.out}/template_{L.name}.pdf", resolution=DPI)
        print(f"wrote {a.out}/template_{L.name}.pdf and .png (marker ids {list(L.marker_ids.values())})")
