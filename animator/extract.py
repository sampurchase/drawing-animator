"""Photo of a filled-in template -> transparent per-body-part layers.

Steps:
 1. find the four ArUco markers and warp the photo flat into template space
 2. flatten uneven lighting using the empty paper margins
 3. pick out the child's ink (colour or dark), ignoring paper and the light grey outline
 4. build a clean alpha cutout and split it into body parts using the template
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from . import template as T


class ExtractError(RuntimeError):
    pass


@dataclass
class Layer:
    name: str
    rgba: np.ndarray      # uint8 H'xW'x4 (straight alpha, RGB order)
    origin: tuple[int, int]  # (x, y) of the crop's top-left in template px
    version: int = T.DEFAULT_VERSION   # which template sheet this drawing was made on


# ---------------------------------------------------------------- 1. flatten
def detect_and_rectify(photo_bgr: np.ndarray) -> tuple[np.ndarray, int]:
    """Find the corner markers, work out which template version the sheet is, and straighten it."""
    aruco = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    det = cv2.aruco.ArucoDetector(aruco, cv2.aruco.DetectorParameters())
    gray = cv2.cvtColor(photo_bgr, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = det.detectMarkers(gray)
    found = {}
    if ids is not None:
        for c, i in zip(corners, ids.flatten()):
            found[int(i)] = c.reshape(4, 2)
    best = None   # (markers seen, version) for the error message
    for ver in sorted(T.LAYOUTS, reverse=True):
        mids = T.LAYOUTS[ver].marker_ids
        seen = sum(mid in found for mid in mids.values())
        if seen == 4:
            src = [found[mid] for mid in mids.values()]
            dst = [T.marker_corners(key) for key in mids]
            Hm, _ = cv2.findHomography(np.concatenate(src), np.concatenate(dst), cv2.RANSAC, 5.0)
            flat = cv2.warpPerspective(photo_bgr, Hm, (T.W, T.H), flags=cv2.INTER_CUBIC,
                                       borderMode=cv2.BORDER_REPLICATE)
            return flat, ver
        if best is None or seen > best[0]:
            best = (seen, ver)
    mids = T.LAYOUTS[best[1]].marker_ids
    words = {"tl": "top-left", "tr": "top-right", "br": "bottom-right", "bl": "bottom-left"}
    missing = [words[k] for k, mid in mids.items() if mid not in found]
    if len(missing) == 4:
        raise ExtractError("I can't see a drawing sheet in this photo. Make sure the whole page is in the photo, "
                           "including all four black corner squares.")
    raise ExtractError(
        f"I can't see the {' and '.join(missing)} corner square{'s' if len(missing) > 1 else ''}. Make sure all four "
        "black corner squares are in the photo, flat and not covered by hands or shadows.")


def rectify(photo_bgr: np.ndarray) -> np.ndarray:
    return detect_and_rectify(photo_bgr)[0]


# --------------------------------------------------------------- 2. lighting
def _paper_sample_mask(sil: np.ndarray, version: int = 1) -> np.ndarray:
    """Pixels that should be plain paper: away from figure, markers, title, edges."""
    m = np.full((T.H, T.W), 255, np.uint8)
    near_fig = cv2.dilate(sil, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (181, 181)))
    m[near_fig > 0] = 0
    for key in T.MARKER_KEYS:
        x, y = T.marker_origin(key)
        m[max(0, y - 30): y + T.MARKER_SIZE + 30, max(0, x - 30): x + T.MARKER_SIZE + 30] = 0
    m[170:340, :] = 0          # title
    if version != 1:
        m[100:260, :] = 0      # title sits higher on newer sheets
    m[2160:2260, :] = 0        # hint text
    if version != 1:
        m[2260:2290, :] = 0
    m[:45, :] = 0; m[-45:, :] = 0; m[:, :45] = 0; m[:, -45:] = 0  # paper edge / table
    return m


def flatten_lighting(img_bgr: np.ndarray, sil: np.ndarray, version: int = 1) -> np.ndarray:
    """Divide out a smooth (quadratic) brightness field fitted to the empty paper."""
    img = img_bgr.astype(np.float32)
    step = 6
    ys, xs = np.mgrid[0:T.H:step, 0:T.W:step]
    ok = _paper_sample_mask(sil, version)[::step, ::step] > 0
    xn = (xs / T.W - 0.5) * 2
    yn = (ys / T.H - 0.5) * 2

    def design(x, y):
        return np.stack([np.ones_like(x), x, y, x * y, x * x, y * y], -1)

    A = design(xn[ok], yn[ok])
    full = design(((np.mgrid[0:T.H, 0:T.W][1] / T.W) - 0.5) * 2,
                  ((np.mgrid[0:T.H, 0:T.W][0] / T.H) - 0.5) * 2)
    out = np.empty_like(img)
    for c in range(3):
        v = img[::step, ::step, c][ok]
        keep = np.ones_like(v, bool)
        # Some Mac numpy builds (Apple Accelerate) print spurious "divide by zero / overflow in matmul"
        # warnings here even though the numbers are fine, so silence them and check the result instead.
        with np.errstate(all="ignore"):
            for _ in range(3):  # a few robust passes to shed shadows / smudges
                coef, *_ = np.linalg.lstsq(A[keep], v[keep], rcond=None)
                res = v - A @ coef
                keep = np.abs(res) < 2.5 * (res[keep].std() + 1e-3)
            field = np.clip(full @ coef, 40, 255)
        if not np.isfinite(field).all():
            raise ExtractError("Could not work out the lighting on this photo. Try again with the whole page in view.")
        out[..., c] = np.clip(img[..., c] / field, 0, 1.2)
    return np.clip(out, 0, 1)  # float BGR, paper ~= 1.0


# ------------------------------------------------------------------- 3. ink
def ink_strength(norm_bgr: np.ndarray) -> np.ndarray:
    """0..1 'how much like marker ink' per pixel (paper and grey outline -> 0)."""
    u8 = (norm_bgr * 255).astype(np.uint8)
    hsv = cv2.cvtColor(u8, cv2.COLOR_BGR2HSV).astype(np.float32)
    s, v = hsv[..., 1] / 255, hsv[..., 2] / 255
    ink_dark = np.clip((0.70 - v) / 0.20, 0, 1)      # grey outline sits at ~0.745
    ink_col = np.clip((s - 0.03) / 0.06, 0, 1)       # pale pencil sits around S 0.1-0.2; paper < 0.02
    return np.maximum(ink_dark, ink_col)


# ------------------------------------------------------------------ 4. parts
def _nearest_part_distances(masks: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    return {n: cv2.distanceTransform((m == 0).astype(np.uint8), cv2.DIST_L2, 5)
            for n, m in masks.items()}


def extract_character(photo_bgr: np.ndarray, margin: int = 90, joint_overlap: int = 14,
                      debug: dict | None = None) -> list[Layer]:
    flat, version = detect_and_rectify(photo_bgr)
    masks = T.part_masks(version)
    sil = np.maximum.reduce(list(masks.values()))
    norm = flatten_lighting(flat, sil, version)

    ink = ink_strength(norm)
    allowed = cv2.dilate(sil, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * margin + 1,) * 2))
    # pencil leaves paper showing between strokes, so also count areas that are *mostly* inked
    ink_soft = cv2.GaussianBlur(ink, (0, 0), 4)
    ink_bin = (((ink > 0.5) | (ink_soft > 0.28)) & (allowed > 0)).astype(np.uint8) * 255

    # drop specks, bridge small gaps in outlines, fill the inside of closed shapes
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink_bin, connectivity=8)
    keep = np.zeros_like(ink_bin)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= 40:
            keep[lab == i] = 255
    closed = cv2.morphologyEx(keep, cv2.MORPH_CLOSE,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))
    if closed.sum() == 0:
        raise ExtractError("No drawing found inside the template. Is the sheet still blank?")

    # Keep only what was actually drawn. Blank paper that connects to the outside of the
    # drawing (e.g. the part of the template arm a thinner drawn arm doesn't cover) becomes
    # transparent. Blank paper fully enclosed by the child's lines (eyes, an uncoloured
    # face or shirt) stays opaque, as long as it lies inside the template silhouette.
    sil_near = cv2.dilate(sil, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    n_bg, bg_lab, bg_stats, _ = cv2.connectedComponentsWithStats((closed == 0).astype(np.uint8), connectivity=4)
    outside = bg_lab[0, 0]
    solid = np.maximum(keep, cv2.bitwise_and(closed, sil_near))  # bridge tiny gaps only near the figure
    for i in range(1, n_bg):
        if i == outside:
            continue
        comp = bg_lab == i
        if (sil_near[comp] > 0).mean() >= 0.5:
            solid[comp] = 255
    # trim ~2px so the pale paper fringe around pencil edges doesn't show as a white halo
    solid = cv2.erode(solid, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    alpha = cv2.GaussianBlur(solid, (0, 0), 1.4)

    # colour: normalised paper -> white; scrub leftover grey outline inside the shape
    rgb = cv2.cvtColor((norm * 255).astype(np.uint8), cv2.COLOR_BGR2RGB)
    hsv = cv2.cvtColor((norm * 255).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32) / 255
    greyish = (ink < 0.15) & (hsv[..., 1] < 0.08) & (hsv[..., 2] < 0.92) & (hsv[..., 2] > 0.68)
    rgb[greyish] = 255
    # leftover soft shadow on 'white' areas: snap near-white, unsaturated pixels to pure white
    rgb[(hsv[..., 1] < 0.04) & (hsv[..., 2] > 0.80)] = 255
    rgba = np.dstack([rgb, alpha])

    if debug is not None:
        debug.update(version=version, flat=flat, norm=(norm * 255).astype(np.uint8), ink=(ink * 255).astype(np.uint8),
                     filled=solid, cutout=rgba)

    # split into parts: each pixel goes to its nearest template part, and also to
    # parts within `joint_overlap` px so joints keep covering when limbs rotate
    dists = _nearest_part_distances(masks)
    stack = np.stack([dists[n] for n in T.PART_ORDER])
    dmin = stack.min(0)
    nearest = stack.argmin(0)
    index = {n: i for i, n in enumerate(T.PART_ORDER)}
    layers = []
    for idx, name in enumerate(T.PART_ORDER):
        # share the overlap zone only with joined parts (parent / children), never with
        # siblings such as the other leg, or stray outline bits ride along with the limb
        joined = {name, T.PARENT[name]} | {c for c, p in T.PARENT.items() if p == name}
        near_ok = np.isin(nearest, [index[j] for j in joined if j is not None])
        sel = (stack[idx] <= dmin + joint_overlap) & (dmin <= margin) & near_ok
        a = np.where(sel, alpha, 0).astype(np.uint8)
        ys, xs = np.nonzero(a)
        if len(xs) == 0:
            # nothing drawn on this part; keep a 1px transparent placeholder
            layers.append(Layer(name, np.zeros((1, 1, 4), np.uint8), (0, 0), version))
            continue
        x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
        crop = np.dstack([rgb[y0:y1, x0:x1], a[y0:y1, x0:x1]])
        layers.append(Layer(name, crop, (int(x0), int(y0)), version))
    return layers


def save_layers(layers: list[Layer], path: str) -> None:
    """Save the body-part layers of one drawing so they can be reused without re-extracting."""
    data = {"names": np.array([l.name for l in layers]), "version": np.array(layers[0].version)}
    for l in layers:
        data[f"rgba_{l.name}"] = l.rgba
        data[f"origin_{l.name}"] = np.array(l.origin)
    np.savez_compressed(path, **data)


def load_layers(path: str) -> list[Layer]:
    z = np.load(path)
    version = int(z["version"])
    return [Layer(str(n), z[f"rgba_{n}"], tuple(int(v) for v in z[f"origin_{n}"]), version) for n in z["names"]]


def load_photo(path: str) -> np.ndarray:
    """Read a photo as BGR. Handles JPEG/PNG and iPhone HEIC."""
    if path.lower().endswith((".heic", ".heif")):
        try:  # easiest route when installed: pip install pillow-heif
            from pillow_heif import register_heif_opener
            from PIL import Image, ImageOps
            register_heif_opener()
            rgb = np.array(ImageOps.exif_transpose(Image.open(path)).convert("RGB"))
        except ImportError:
            from .heic import read_heic_rgb
            rgb = read_heic_rgb(path)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise ExtractError(f"Could not read image: {path}")
    return img
