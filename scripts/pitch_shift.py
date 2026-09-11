#!/usr/bin/env python3
"""Measure the pitch ratio between two recordings of the same music.

    python scripts/pitch_shift.py REFERENCE.mkv SHIFTED.mkv [--start S] [--dur D]

Built for Paprium's "crisis"/out-of-tune state: the game plays a track with a
pitch effect applied, and the cartridge's command log documents two candidates -
0x8000 "tiny pitch" at 31/32 speed (-55.0 cents) and 0x2000 "huge pitch" at half
speed (-1200 cents).  Comparing a crisis capture against the ordinary capture of
the same track measures which, if either, is actually happening.

Method: a long-term average spectrum of each file, resampled onto a log-frequency
axis so that a constant pitch ratio becomes a constant TRANSLATION, then
cross-correlated.  The peak of the correlation is the shift.  This needs no note
tracking and tolerates the two recordings not starting at the same instant,
because the long-term average washes out which notes are sounding when.

Reports the shift in cents and as a ratio, alongside the exact cent values of the
candidate effects so the answer can be read off directly.
"""

import argparse
import os
import subprocess

import numpy as np

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
SR = 48000
NFFT = 16384
FMIN, FMAX = 50.0, 6000.0
BINS_PER_OCT = 480.0                       # 2.5 cents per bin
MAXSHIFT = 1500.0                          # cents to search either way

CANDIDATES = [
    ("31/32 'tiny pitch'", 31.0 / 32.0),
    ("half speed 'huge pitch'", 0.5),
    ("one semitone down", 2.0 ** (-1.0 / 12.0)),
    ("no shift", 1.0),
]


def ltas(path, start, dur):
    """Long-term average magnitude spectrum, mono, over the chosen window."""
    cmd = [FFMPEG, "-v", "error", "-ss", "%.3f" % start, "-t", "%.3f" % dur,
           "-i", path, "-map", "a:0", "-ac", "1", "-ar", str(SR),
           "-f", "f32le", "-"]
    raw = subprocess.run(cmd, stdout=subprocess.PIPE, check=True).stdout
    x = np.frombuffer(raw, dtype="<f4").astype(np.float64)
    if len(x) < NFFT:
        raise SystemExit("%s: window too short" % os.path.basename(path))
    win = np.hanning(NFFT)
    acc = np.zeros(NFFT // 2 + 1)
    n = 0
    for i in range(0, len(x) - NFFT + 1, NFFT // 2):
        acc += np.abs(np.fft.rfft(x[i:i + NFFT] * win))
        n += 1
    return np.fft.rfftfreq(NFFT, 1.0 / SR), acc / max(n, 1)


def logaxis(freqs, mag, fmin=FMIN, fmax=FMAX):
    """Resample onto a log-frequency grid; a pitch ratio becomes a shift."""
    nb = int(np.log2(fmax / fmin) * BINS_PER_OCT)
    grid = fmin * 2.0 ** (np.arange(nb) / BINS_PER_OCT)
    v = np.interp(grid, freqs, mag)
    v = np.log(np.maximum(v, 1e-12))
    v -= v.mean()
    # flatten the broad spectral slope so the correlation follows the partials
    k = int(BINS_PER_OCT / 4)
    sm = np.convolve(v, np.ones(k) / k, mode="same")
    return v - sm


def shift_cents(a, b, maxshift=MAXSHIFT):
    """Cents to move b onto a, by cross-correlation, parabolically refined.

    maxshift bounds the search. Keep it tight for a per-band detune measurement:
    over one octave of spectrum a wide search can lock onto a harmonic of the
    right answer instead of the answer, and report a confident nonsense value.
    """
    lim = int(maxshift / 1200.0 * BINS_PER_OCT)
    best, scores = None, []
    for s in range(-lim, lim + 1):
        bb = np.roll(b, s)
        if s > 0:
            bb[:s] = 0.0
        elif s < 0:
            bb[s:] = 0.0
        r = float(np.dot(a, bb) / (np.linalg.norm(a) * np.linalg.norm(bb) + 1e-30))
        scores.append(r)
        if best is None or r > best[1]:
            best = (s, r)
    i = best[0] + lim
    c = np.array(scores)
    if 0 < i < len(c) - 1:
        d = c[i - 1] - 2 * c[i] + c[i + 1]
        frac = 0.5 * (c[i - 1] - c[i + 1]) / d if d else 0.0
    else:
        frac = 0.0
    return (best[0] + frac) * 1200.0 / BINS_PER_OCT, best[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reference")
    ap.add_argument("shifted")
    ap.add_argument("--start", type=float, default=5.0)
    ap.add_argument("--dur", type=float, default=40.0)
    ap.add_argument("--bands", action="store_true",
                    help="measure each octave band separately - a per-voice effect "
                         "shifts some bands and leaves others alone")
    a = ap.parse_args()

    fa, ma = ltas(a.reference, a.start, a.dur)
    fb, mb = ltas(a.shifted, a.start, a.dur)

    if a.bands:
        print("%-28s -> %-28s" % (os.path.basename(a.reference)[:28],
                                  os.path.basename(a.shifted)[:28]))
        lo = 55.0
        while lo < 3520.0:
            hi = lo * 2.0
            c, rr = shift_cents(logaxis(fa, ma, lo, hi),
                                logaxis(fb, mb, lo, hi), maxshift=200.0)
            print("   %6.0f-%6.0f Hz   %+8.1f cents   correlation %.3f" % (lo, hi, c, rr))
            lo = hi
        return

    cents, r = shift_cents(logaxis(fa, ma), logaxis(fb, mb))
    ratio = 2.0 ** (cents / 1200.0)

    print("%-28s -> %-28s" % (os.path.basename(a.reference)[:28],
                              os.path.basename(a.shifted)[:28]))
    print("   shift %+8.1f cents   ratio %.6f   peak correlation %.3f"
          % (cents, ratio, r))
    print("   nearest candidate: " + min(
        CANDIDATES,
        key=lambda c: abs(1200 * np.log2(c[1]) - cents))[0])
    for name, cand in CANDIDATES:
        cc = 1200 * np.log2(cand)
        print("      %-26s %+8.1f cents   (off by %6.1f)" % (name, cc, cents - cc))


if __name__ == "__main__":
    main()
