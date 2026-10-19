"""A small synthesized disco-ish backing track (numpy only), so videos have music out of the box.

It is a placeholder: four-on-the-floor kick, claps on 2 and 4, off-beat hats, an octave-pumping bass,
off-beat chord stabs and a quiet sparkly arpeggio over Am - F - C - G (one bar each).
Bar 1 beat 1 is at t = 0, so a character whose feet land at the start of each step lines up.
"""
from __future__ import annotations

import wave

import numpy as np

SR = 44100

# chord progression: (bass root Hz, chord tones Hz in the middle octave)
_PROG = [
    (110.00, [220.00, 261.63, 329.63]),   # Am
    (87.31,  [174.61, 220.00, 261.63]),   # F
    (130.81, [261.63, 329.63, 392.00]),   # C
    (98.00,  [196.00, 246.94, 293.66]),   # G
]


def _t(dur):
    return np.arange(int(dur * SR)) / SR


def _saw_like(freq, t, harmonics=8):
    """Band-limited-ish saw built from the first few harmonics (no filters needed)."""
    out = np.zeros_like(t)
    for k in range(1, harmonics + 1):
        out += np.sin(2 * np.pi * freq * k * t) / k
    return out * 0.6


def _kick():
    t = _t(0.38)
    f = 46 + 120 * np.exp(-t * 30)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t * 8.5) + 0.25 * np.exp(-t * 400) * np.sin(2 * np.pi * 1800 * t)


def _hat(rng, open_=False):
    t = _t(0.22 if open_ else 0.07)
    n = rng.standard_normal(t.size)
    n = np.diff(n, prepend=0.0)
    n = np.diff(n, prepend=0.0)  # crude high-pass
    return n * np.exp(-t * (16 if open_ else 55))


def _clap(rng):
    t = _t(0.28)
    n = rng.standard_normal(t.size)
    n = np.diff(n, prepend=0.0)
    k = np.ones(5) / 5
    n = np.convolve(n, k, mode="same")  # rough band-limiting
    env = (np.exp(-((t) * 400)) + 0.8 * np.exp(-((t - 0.011) ** 2) * 6e4)
           + 0.7 * np.exp(-((t - 0.022) ** 2) * 6e4)) * 0.6 + np.exp(-t * 16)
    return n * env * 1.4


def _bass(freq, dur):
    t = _t(dur)
    env = np.minimum(1, t * 400) * np.exp(-t * 7.0)
    return (np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(4 * np.pi * freq * t)
            + 0.25 * np.sin(6 * np.pi * freq * t)) * env


def _stab(freqs, dur=0.22):
    t = _t(dur)
    env = np.minimum(1, t * 600) * np.exp(-t * 11)
    return sum(_saw_like(f, t, 6) for f in freqs) * env / len(freqs)


def _pluck(freq, dur=0.16):
    t = _t(dur)
    env = np.minimum(1, t * 800) * np.exp(-t * 22)
    return (np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t)) * env


def _mix_in(buf, snd, at_s, gain=1.0, pan=0.0):
    i = int(round(at_s * SR))
    if i >= buf.shape[0]:
        return
    n = min(snd.size, buf.shape[0] - i)
    l, r = gain * (1 - max(0, pan)), gain * (1 + min(0, pan))
    buf[i:i + n, 0] += snd[:n] * l
    buf[i:i + n, 1] += snd[:n] * r


def generate(bpm: float = 120.0, seconds: float = 16.0, seed: int = 3) -> np.ndarray:
    """Return float32 stereo samples, shape (n, 2), peak-normalised."""
    rng = np.random.default_rng(seed)
    beat = 60.0 / bpm
    eighth = beat / 2
    sixteenth = beat / 4
    buf = np.zeros((int((seconds + 1.0) * SR), 2), np.float32)

    kick, clap = _kick(), _clap(rng)
    hat_c, hat_o = _hat(rng), _hat(rng, True)
    n_beats = int(seconds / beat) + 1
    for b in range(n_beats):
        t0 = b * beat
        bar, in_bar = divmod(b, 4)
        root, chord = _PROG[bar % 4]
        _mix_in(buf, kick, t0, 1.0)
        if in_bar in (1, 3):
            _mix_in(buf, clap, t0, 0.38)
        _mix_in(buf, hat_o, t0 + eighth, 0.20, pan=0.15)       # off-beat open hat
        _mix_in(buf, hat_c, t0 + sixteenth, 0.07, pan=-0.2)     # ghost 16ths
        _mix_in(buf, hat_c, t0 + 3 * sixteenth, 0.07, pan=-0.2)
        # octave-pumping bass: low on the beat, octave up on the off-beat
        _mix_in(buf, _bass(root, eighth * 0.9), t0, 0.50)
        _mix_in(buf, _bass(root * 2, eighth * 0.85), t0 + eighth, 0.42)
        # off-beat chord stab
        _mix_in(buf, _stab(chord), t0 + eighth, 0.16, pan=0.25)
        # sparkly arpeggio on 16ths
        for s in range(4):
            note = chord[[0, 1, 2, 1][s]] * 2
            _mix_in(buf, _pluck(note), t0 + s * sixteenth, 0.07, pan=-0.3 if s % 2 else 0.3)

    out = buf[:int(seconds * SR)]
    fade = int(0.4 * SR)
    out[-fade:] *= np.linspace(1, 0, fade)[:, None]
    peak = np.abs(out).max() or 1.0
    out = np.tanh(out / peak * 1.6) / np.tanh(1.6) * 0.9  # gentle soft clip, then ~-1 dB headroom
    return out.astype(np.float32)


def write_wav(path: str, samples: np.ndarray) -> None:
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    import sys
    bpm = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 16.0
    out = sys.argv[3] if len(sys.argv) > 3 else "out/track.wav"
    write_wav(out, generate(bpm, secs))
    print(f"wrote {out}")
