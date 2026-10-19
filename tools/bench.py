"""Time a fixed test render so machines can be compared.

    python3 tools/bench.py

Renders 8 seconds of video (two dancers, dance floor background, 1280x720) from the sample drawings,
once with a single worker process and once with the default number, and prints how long each took
(not counting the one-off time to read the photos).
"""
import os, platform, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
from animator import engine as G  # noqa: E402

SECONDS = 8


def main():
    print(f"machine: {platform.machine()}, {os.cpu_count()} threads, python {platform.python_version()}")
    t0 = time.time()
    layers = [G.extract_drawing(p) for p in ("samples/fake_photo.jpg", "samples/fake_photo_dancer.jpg")]
    print(f"reading 2 photos took {time.time() - t0:.1f}s (once per drawing, only when it is added)")
    s = G.Settings(background="samples/dancefloor.jpg", seconds=SECONDS, music="none")
    out = os.path.join(tempfile.gettempdir(), "bench.mp4")
    for w in sorted({1, G.default_workers()}):
        t0 = time.time()
        G.render_video(layers, s, out, workers=w)
        dt = time.time() - t0
        print(f"{SECONDS}s video, {w} worker(s): {dt:.1f}s  ->  about {dt * 16 / SECONDS:.0f}s for a 16s video")


if __name__ == "__main__":
    main()
