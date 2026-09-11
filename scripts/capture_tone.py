#!/usr/bin/env python3
"""Characterise a quiet window of a hardware capture.

Written for the boombox "no track" slots: the ten null entries in the cart's
BGM pointer table, which docs/PORT_PLAN.md predicted would be silent on real
hardware.  They are reported not to be - a faint tone on some, a hum on others,
and audibly different from one another.  Before that can mean anything the
capture chain's own noise floor has to be measured, because a hum at 50/60 Hz
and its harmonics is mains, not cartridge.

Reports, per channel, for the chosen window:

  peak/RMS dBFS        how loud the window is at all
  DC                   a constant offset - a stuck DAC reads as one
  flatness             spectral flatness, 0 = pure tone, 1 = white noise
  mains                share of power in the 50 Hz or 60 Hz harmonic family
  peaks                strongest spectral lines, parabolically interpolated

Usage:
  python scripts/capture_tone.py [--start S] [--dur D] [--top N] FILE...
  python scripts/capture_tone.py --start 0 --dur 3 "og hardware music tests"/*.mkv
"""

import argparse
import os
import subprocess
import sys

import numpy as np

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
SR = 48000
NFFT = 16384


def decode(path, start, dur):
    """Decode one window of a capture to float32 stereo at SR."""
    cmd = [FFMPEG, "-v", "error", "-ss", "%.3f" % start, "-t", "%.3f" % dur,
           "-i", path, "-map", "a:0", "-ac", "2", "-ar", str(SR),
           "-f", "f32le", "-"]
    raw = subprocess.run(cmd, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, check=True).stdout
    a = np.frombuffer(raw, dtype="<f4")
    a = a[: (len(a) // 2) * 2].reshape(-1, 2)
    return a.astype(np.float64)


def spectrum(x):
    """Averaged power spectrum over Hann-windowed half-overlapping frames."""
    if len(x) < NFFT:
        x = np.pad(x, (0, NFFT - len(x)))
    win = np.hanning(NFFT)
    hop = NFFT // 2
    acc = np.zeros(NFFT // 2 + 1)
    n = 0
    for i in range(0, len(x) - NFFT + 1, hop):
        acc += np.abs(np.fft.rfft(x[i:i + NFFT] * win)) ** 2
        n += 1
    acc /= max(n, 1)
    return np.fft.rfftfreq(NFFT, 1.0 / SR), acc


def interp_peak(freqs, p, k):
    """Parabolic interpolation around bin k, in log power."""
    if k <= 0 or k >= len(p) - 1:
        return freqs[k]
    a, b, c = (np.log(max(v, 1e-30)) for v in (p[k - 1], p[k], p[k + 1]))
    denom = a - 2 * b + c
    if denom == 0:
        return freqs[k]
    return freqs[k] + 0.5 * (a - c) / denom * (freqs[1] - freqs[0])


def peaks(freqs, p, top, fmin=20.0):
    """Strongest local maxima above fmin, strongest first."""
    lo = int(fmin / (freqs[1] - freqs[0]))
    idx = [k for k in range(max(lo, 1), len(p) - 1)
           if p[k] > p[k - 1] and p[k] >= p[k + 1]]
    idx.sort(key=lambda k: -p[k])
    out, total = [], p[lo:].sum()
    for k in idx[:top]:
        out.append((interp_peak(freqs, p, k), p[k] / max(total, 1e-30)))
    return out


def mains_share(freqs, p, base):
    """Fraction of power sitting on base and its harmonics, +/- 1.5 Hz."""
    df = freqs[1] - freqs[0]
    lo = int(20.0 / df)
    total = p[lo:].sum()
    got = 0.0
    f = base
    while f < SR / 2:
        k0 = max(int((f - 1.5) / df), 0)
        k1 = min(int((f + 1.5) / df) + 1, len(p))
        got += p[k0:k1].sum()
        f += base
    return got / max(total, 1e-30)


def db(v):
    return -999.0 if v <= 0 else 20.0 * np.log10(v)


def analyse(path, start, dur, top):
    a = decode(path, start, dur)
    if len(a) == 0:
        print("%-28s  no audio in window" % os.path.basename(path)[:28])
        return
    name = os.path.basename(path)
    print("\n%s   [%.1fs .. %.1fs]" % (name, start, start + dur))
    for ch in (0, 1):
        x = a[:, ch]
        dc = x.mean()
        freqs, p = spectrum(x - dc)
        lo = int(20.0 / (freqs[1] - freqs[0]))
        band = p[lo:]
        flat = float(np.exp(np.log(np.maximum(band, 1e-30)).mean()) /
                     max(band.mean(), 1e-30))
        pk = peaks(freqs, p, top)
        print("  %s  peak %7.1f dBFS   rms %7.1f dBFS   DC %+9.2e   "
              "flat %.4f   50Hz %5.1f%%  60Hz %5.1f%%"
              % ("L" if ch == 0 else "R", db(np.abs(x).max()),
                 db(np.sqrt((x * x).mean())), dc, flat,
                 100 * mains_share(freqs, p, 50.0),
                 100 * mains_share(freqs, p, 60.0)))
        print("     peaks  " + "  ".join("%8.2f Hz (%4.1f%%)" % (f, 100 * s)
                                          for f, s in pk))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=float, default=0.0, help="window start, seconds")
    ap.add_argument("--dur", type=float, default=3.0, help="window length, seconds")
    ap.add_argument("--top", type=int, default=5, help="spectral peaks to list")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()
    for f in args.files:
        try:
            analyse(f, args.start, args.dur, args.top)
        except subprocess.CalledProcessError as e:
            print("%s: ffmpeg failed: %s"
                  % (os.path.basename(f), e.stderr.decode(errors="replace").strip()[:200]),
                  file=sys.stderr)


if __name__ == "__main__":
    main()
