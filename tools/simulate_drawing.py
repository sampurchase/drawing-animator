"""Make a fake 'kid drawing' on the template and a fake skewed, unevenly lit phone photo of it.
Only for testing the pipeline before real drawings exist."""
import sys
import cv2
import numpy as np

sys.path.insert(0, ".")
from animator import template as T

rng = np.random.default_rng(7)


def wobble(mask, amt=5):
    """Make a mask edge slightly irregular, like hand colouring."""
    noise = cv2.GaussianBlur(rng.normal(0, 1, mask.shape).astype(np.float32), (0, 0), 14)
    noise = noise / (noise.std() + 1e-6) * amt
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5) - cv2.distanceTransform(255 - mask, cv2.DIST_L2, 5)
    return ((dist + noise) > 0).astype(np.uint8) * 255


def make_drawing(out_png="samples/fake_drawing.png", variant="bold", version=None):
    L = T.layout(version)
    sheet = np.array(T.make_template(version=L.version))[:, :, ::-1].copy()  # BGR
    masks = T.part_masks(L.version)
    colours = {  # BGR
        "head": (170, 205, 255), "torso": (230, 120, 40),
        "upper_arm_R": (230, 120, 40), "upper_arm_L": (230, 120, 40),
        "forearm_R": (170, 205, 255), "forearm_L": (170, 205, 255),
        "thigh_R": (80, 170, 60), "thigh_L": (80, 170, 60),
        "shin_R": (60, 60, 220), "shin_L": (60, 60, 220),
    }
    if variant == "outline":   # black outline only, nothing coloured in; thin pen
        colours = {k: (255, 255, 255) for k in colours}
    if variant == "pastel":
        colours = {k: tuple(int(255 - (255 - c) * 0.35) for c in v) for k, v in colours.items()}
    for name in ["thigh_R", "thigh_L", "shin_R", "shin_L", "upper_arm_R", "upper_arm_L",
                 "forearm_R", "forearm_L", "torso", "head"]:
        m = wobble(masks[name], 4)
        if variant != "outline" or True:
            sheet[m > 0] = colours[name]
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.polylines(sheet, cnts, True, (30, 30, 30), 5 if variant == "outline" else 9, cv2.LINE_AA)
    cy, r = L.head
    if variant == "blob":   # fill the whole template shape white with a bold outline, two dot eyes
        sil = T.silhouette_mask(L.version)
        sheet[sil > 0] = (245, 245, 245)
        cnts, _ = cv2.findContours(sil, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.polylines(sheet, cnts, True, (30, 30, 30), 9, cv2.LINE_AA)
        for ex in (-0.45, 0.45):
            cv2.circle(sheet, (T.CX + int(ex * r), cy), 18, (30, 30, 30), -1, cv2.LINE_AA)
        cv2.line(sheet, (T.CX - int(.45 * r), cy), (T.CX + int(.45 * r), cy), (30, 30, 30), 8, cv2.LINE_AA)
        cv2.imwrite(out_png, sheet)
        return sheet
    if variant == "ballerina":   # slim: thin limbs and a tutu, mostly empty template
        sheet[:] = np.array(T.make_template(version=L.version))[:, :, ::-1]
        k_, ink, skin = 30, (30, 30, 30), (170, 205, 255)
        cv2.circle(sheet, (T.CX, cy), int(r * .55), skin, -1, cv2.LINE_AA)
        cv2.circle(sheet, (T.CX, cy), int(r * .55), ink, 7, cv2.LINE_AA)
        top = L.torso[1]
        cv2.rectangle(sheet, (T.CX - 70, top - 10), (T.CX + 70, top + 380), (200, 120, 240), -1)
        cv2.fillPoly(sheet, [np.array([[T.CX - 70, top + 330], [T.CX + 70, top + 330],
                                       [T.CX + 380, top + 520], [T.CX - 380, top + 520]])], (190, 80, 220))
        sh, el = L.pivots["upper_arm_R"], L.pivots["forearm_R"]
        for sx in (1, -1):
            c = lambda p: (int(T.CX + sx * (T.CX - p[0])) if True else 0, int(p[1]))
            cv2.line(sheet, (T.CX + sx * 60, top + 30), (T.CX + sx * (T.CX - 150), L.hand[1] - 40), skin, 34, cv2.LINE_AA)
        for lx in (L.pivots["thigh_R"][0], T.W - L.pivots["thigh_R"][0]):
            cv2.line(sheet, (lx, top + 700), (lx, L.foot[3] - 60), skin, 44, cv2.LINE_AA)
            cv2.ellipse(sheet, (lx + (-40 if lx < T.CX else 40), L.foot[3] - 45), (100, 36), 0, 0, 360, (80, 60, 200), -1, cv2.LINE_AA)
        cv2.imwrite(out_png, sheet)
        return sheet
    k = r / 165.0                                  # scale face features to the head size
    top, bottom = L.torso[1], L.torso[2]
    if variant == "dress":   # a skirt that fills the gap between the legs: a wide shape across both thighs
        hw = L.torso[0]
        pts = np.array([[T.CX - hw, top + 250], [T.CX + hw, top + 250],
                        [T.CX + hw + 170, 1700], [T.CX - hw - 170, 1700]])
        pts[:, 0] = np.clip(pts[:, 0], L.thigh[0] - 20, T.W - L.thigh[0] + 20)
        cv2.fillPoly(sheet, [pts], (190, 60, 200)); cv2.polylines(sheet, [pts], True, (30, 30, 30), 9, cv2.LINE_AA)
    # hair spikes poking outside the head
    base = int(cy - 140 * k)
    for dx in range(int(-120 * k), int(120 * k) + 1, int(40 * k)):
        pts = np.array([[T.CX + dx - 22, base], [T.CX + dx, base - 80 - abs(dx) // 6], [T.CX + dx + 22, base]])
        cv2.fillPoly(sheet, [pts], (20, 120, 240)); cv2.polylines(sheet, [pts], False, (30, 30, 30), 8, cv2.LINE_AA)
    # face and a button
    for ex in (-60, 60):
        cv2.circle(sheet, (T.CX + int(ex * k), cy - int(20 * k)), 20, (30, 30, 30), -1, cv2.LINE_AA)
    cv2.ellipse(sheet, (T.CX, cy + int(60 * k)), (int(60 * k), int(35 * k)), 0, 10, 170, (30, 30, 200), 9, cv2.LINE_AA)
    by = top + 230
    cv2.circle(sheet, (T.CX, by), 28, (0, 220, 255), -1, cv2.LINE_AA)
    cv2.circle(sheet, (T.CX, by), 28, (30, 30, 30), 7, cv2.LINE_AA)
    if variant == "short":   # only coloured down to the knees: the dancer is shorter than the template
        sheet[1760:2240, 300:1354] = np.where(sheet[1760:2240, 300:1354] < 250, 255, 255)
        cv2.polylines(sheet, cv2.findContours(T.silhouette_mask(L.version), cv2.RETR_EXTERNAL,
                                              cv2.CHAIN_APPROX_NONE)[0], True, (190,) * 3, 5, cv2.LINE_AA)
    cv2.imwrite(out_png, sheet)
    return sheet


def make_photo(sheet, out_jpg="samples/fake_photo.jpg"):
    CW, CH = 3024, 4032  # phone-ish portrait photo
    table = np.full((CH, CW, 3), (60, 95, 140), np.float32)
    table += cv2.GaussianBlur(rng.normal(0, 18, (CH, CW, 3)).astype(np.float32), (0, 0), 6)
    # sheet placed with perspective + a little rotation
    src = np.float32([[0, 0], [T.W, 0], [T.W, T.H], [0, T.H]])
    dst = np.float32([[330, 260], [2720, 350], [2800, 3680], [250, 3750]])
    Hm = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(sheet, Hm, (CW, CH), flags=cv2.INTER_CUBIC, borderValue=(0, 0, 0))
    mask = cv2.warpPerspective(np.full((T.H, T.W), 255, np.uint8), Hm, (CW, CH))
    paper = np.where(mask[..., None] > 0, warped.astype(np.float32) * 0.93, table)
    # uneven light: bright top-left, dim bottom-right, plus a soft shadow band
    yy, xx = np.mgrid[0:CH, 0:CW]
    light = 1.08 - 0.30 * (xx / CW * 0.6 + yy / CH * 0.8)
    light *= 1 - 0.15 * np.exp(-(((yy - 2600) / 260) ** 2))
    paper = paper * light[..., None]
    paper += rng.normal(0, 3.5, paper.shape)
    paper = cv2.GaussianBlur(paper, (0, 0), 1.2)
    cv2.imwrite(out_jpg, np.clip(paper, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 88])


if __name__ == "__main__":
    import glob, os
    for f in glob.glob("samples/fake_*"):
        os.remove(f)
    # a standard coloured-in drawing on every template. Hero is the default and has no suffix.
    for ver, suffix in ((2, ""), (3, "_huggable"), (4, "_dancer"), (1, "_original")):
        sheet = make_drawing(f"samples/fake_drawing{suffix}.png", "bold", ver)
        make_photo(sheet, f"samples/fake_photo{suffix}.jpg")
    # special cases: pale pencil / outline only, a skirt across both legs, a short drawing
    for v in ("outline", "pastel", "dress", "short"):
        make_photo(make_drawing(f"samples/fake_drawing_{v}.png", v, 2), f"samples/fake_photo_{v}.jpg")
    # a white blob on the huggable sheet and a slim ballerina on the dancer sheet
    make_photo(make_drawing("samples/fake_drawing_blob.png", "blob", 3), "samples/fake_photo_blob.jpg")
    make_photo(make_drawing("samples/fake_drawing_ballerina.png", "ballerina", 4), "samples/fake_photo_ballerina.jpg")
    print("wrote samples/fake_*.png and fake_photo*.jpg")
