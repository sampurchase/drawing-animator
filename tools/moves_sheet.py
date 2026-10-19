#!/usr/bin/env python3
"""Contact sheet of every dance move: one row per move, frames at several points in its cycle.

    python3 tools/moves_sheet.py samples/fake_photo.jpg out/moves.png
"""
import sys

import cv2
import numpy as np

sys.path.insert(0, ".")
from animator import choreo as C
from animator import extract as E
from animator import rig as R
from animate import ground_view_matrix


def main(photo, out, times=(0.0, 0.5, 1.0, 1.5), w=300, h=340):
    pup = R.Puppet(E.extract_character(E.load_photo(photo)))
    view, _ = ground_view_matrix(0, w, h, 0.80, 0.94 * h)
    rows = []
    for name in C.MOVES:
        row = []
        for b in times:
            u = C.MOVES[name](b)
            pose = R.march_pose((b / 2) % 1.0)
            r = pose.rot
            r["upper_arm_R"], r["upper_arm_L"] = u.up_R, -u.up_L
            r["forearm_R"], r["forearm_L"] = u.bend_R, -u.bend_L
            r["torso"] = r.get("torso", 0) + u.torso
            r["head"] = r.get("head", 0) + u.head
            pose.root_offset = (pose.root_offset[0] + u.dx, pose.root_offset[1] + u.dy)
            pose.arms_front = u.arms_front
            img = R.over_white(pup.render(pose, (w, h), view, flip_x=u.flip)).copy()
            cv2.putText(img, f"{name} b={b:g}", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
            row.append(img)
        rows.append(np.hstack(row))
    cv2.imwrite(out, cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR))
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
