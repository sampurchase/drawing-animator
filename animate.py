#!/usr/bin/env python3
"""Turn photos of filled-in character sheets into a dancing video: marching back and forth on a
still background (or white), to music.

    python3 animate.py kid.heic --background samples/dancefloor.jpg --out out/dance.mp4
    python3 animate.py a.heic b.heic c.heic --background floor.jpg    # chorus line: all in unison (default)
    python3 animate.py a.heic b.heic --mode mirror --background floor.jpg   # pairs, mirror image of each other
    python3 animate.py a.heic b.heic --mode conga --background floor.jpg    # follow the leader, 2 beats apart
    python3 animate.py kid.jpg --travel 0 --music none          # dance on the spot, no sound
    python3 animate.py kid.jpg --music mysong.mp3 --bpm 118     # your own track (first beat at 0s)
"""
from __future__ import annotations

import argparse
import os
import sys

import cv2

from animator import engine as G
from animator import extract as E
# kept importable from here for the helper tools
from animator.engine import ground_view_matrix, place_view, travel_state, build_dancers  # noqa: F401


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photos", nargs="+", help="photo(s) of filled-in template sheets (JPEG, PNG or iPhone HEIC)")
    ap.add_argument("--out", default="out/dance.mp4")
    ap.add_argument("--seconds", type=float, default=16.0)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--size", default="1280x720", help="video size WxH")
    ap.add_argument("--background", metavar="IMAGE", help="still image to dance in front of (default: white)")
    ap.add_argument("--char-height", type=float, default=None,
                    help="hair-to-feet height as a fraction of the frame (default 0.74 for one drawing; "
                         "with several drawings they shrink automatically so the group fits and can still travel)")
    ap.add_argument("--feet-y", type=float, default=0.94,
                    help="where the feet land, as a fraction of frame height (default 0.94)")
    ap.add_argument("--bg-anchor", type=float, default=0.7,
                    help="share of any vertical background crop taken off the top, 0..1 (default 0.7)")
    # movement
    ap.add_argument("--travel", type=float, default=0.6,
                    help="fraction of the frame width she walks across, back and forth; 0 = march on the spot")
    ap.add_argument("--leg-seconds", type=float, default=None,
                    help="seconds per crossing including the turn (default: 8 beats, two bars)")
    ap.add_argument("--turn-seconds", type=float, default=None,
                    help="seconds spent turning round at each end (default: 1 beat)")
    ap.add_argument("--choreo", choices=["dance", "march"], default="dance",
                    help="dance = the move routine in animator/choreo.py; march = just the original arm swing")
    ap.add_argument("--turn", choices=["squash", "none"], default="squash",
                    help="squash = paper-puppet flip at each end (mirrors the drawing going left); none = just reverse")
    ap.add_argument("--lean", type=float, default=4.0, help="degrees she leans into the direction of travel")
    ap.add_argument("--mode", choices=["unison", "mirror", "conga"], default="unison",
                    help="several drawings. unison = chorus line, everyone does the same thing at the same time "
                         "(default); mirror = pairs that are mirror images of each other, walking in from opposite "
                         "sides; conga = follow the leader, each one a few beats behind")
    ap.add_argument("--follow-delay", type=float, default=None,
                    help="conga mode: seconds between dancers, rounded to whole beats (default 2 beats)")
    ap.add_argument("--stagger", type=float, default=0.0,
                    help="phase offset between characters' steps, 0..1 of a cycle (0 = all in step)")
    # music
    ap.add_argument("--bpm", type=float, default=120.0, help="tempo; one step per beat, a full left+right cycle = 2 beats")
    ap.add_argument("--music", default="auto", help="auto = built-in synthesized beat, none, or a path to an audio file")
    ap.add_argument("--music-offset", type=float, default=0.0, help="skip this many seconds of your audio file")
    # utilities
    ap.add_argument("--save-cutouts", metavar="DIR", help="also save each cut-out PNG here")
    ap.add_argument("--contact-sheet", metavar="PNG", help="write a grid of frames to this PNG and stop")
    ap.add_argument("--sheet-times", default="0.3,1.5,3.0,3.8,4.2,4.8,6.0,7.8",
                    help="seconds of the frames for --contact-sheet, comma separated")
    ap.add_argument("--workers", type=int, default=None,
                    help="processes used to draw frames in parallel (default: one fewer than the CPU cores, up to 6)")
    args = ap.parse_args(argv)
    settings = G.Settings.from_namespace(args)

    layer_sets = []
    for i, path in enumerate(args.photos):
        dbg = {}
        try:
            layer_sets.append(G.extract_drawing(path, debug=dbg))
        except G.EngineError as e:
            sys.exit(f"{path}: {e}")
        if args.save_cutouts:
            os.makedirs(args.save_cutouts, exist_ok=True)
            cv2.imwrite(os.path.join(args.save_cutouts, f"cutout_{i + 1}.png"),
                        cv2.cvtColor(dbg["cutout"], cv2.COLOR_RGBA2BGRA))
        print(f"[{i + 1}/{len(args.photos)}] extracted {path}")

    try:
        if args.contact_sheet:
            times = [float(x) for x in args.sheet_times.split(",")]
            G.contact_sheet(layer_sets, settings, times, args.contact_sheet)
            print(f"wrote {args.contact_sheet}")
            return
        info = G.render_video(layer_sets, settings, args.out, workers=args.workers)
    except G.EngineError as e:
        sys.exit(str(e))
    print(f"{info['characters']} drawing(s), {info['mode']} mode")
    print(f"wrote {args.out}  ({info['frames']} frames, {info['fps']} fps, {info['characters']} character(s)"
          f"{', with music' if info['audio'] else ''})")


if __name__ == "__main__":
    main()
