#!/usr/bin/env python3
"""Measure each FM patch's timbre from the hardware captures.

    python scripts/fm_timbre.py <moduledir> <capturedir> <out.csv> [--min-notes 6]

The cartridge does not contain a YM2612 - it renders FM in its own firmware -
so modelling the chip reproduces the patch data but not the sound. What works is
measuring the real thing: the solved row clock gives every note's time to a few
ppm, so a capture can be windowed at the exact millisecond a known patch plays a
known pitch, and its harmonic profile read off directly.

For each patch this pools the harmonic amplitudes (relative to the fundamental,
so measurements at different pitches combine) over every usable note, and
estimates attack and decay from the envelope. Notes are ranked by EXPOSURE -
how few other voices start within +/-120 ms - because the confound here is other
instruments bleeding into the window, not noise.

Output feeds scripts/render_wave.py --timbres.

Derived from a commercial ROM and from recordings of it. Keep the output local.
"""

import argparse
import collections
import csv
import glob
import os
import re
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mwmm
import voice_notes as vn

SR = 32000
NH = 14
ANCHOR = 11


def captures(d):
    out = {}
    for p in glob.glob(os.path.join(d, "*.mkv")):
        b = os.path.basename(p)
        if re.search(r"no ?track|after ", b, re.I):
            continue
        m = re.match(r"([0-9A-Fa-f]{2}) ", b)
        if m:
            out.setdefault(int(m.group(1), 16), p)
    return out


def decode(path, seconds):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-t", str(seconds), "-i", path,
                          "-map", "a:0", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         stdout=subprocess.PIPE, check=True).stdout
    return np.frombuffer(raw, dtype="<f4").astype(np.float64)


def music_start(x):
    fr = int(0.01 * SR)
    e = np.sqrt(np.convolve(x * x, np.ones(fr) / fr, "same"))
    thr = max(np.percentile(e[:SR], 50) * 20, e.max() * 0.02)
    return int(np.argmax(e > thr)) / SR


def harmonics(seg, f0):
    """Amplitude at each harmonic of f0, and a crude noise floor for SNR."""
    n = 1 << 16
    X = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n))
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    df = freqs[1]
    amps = []
    for h in range(1, NH + 1):
        k = int(round(h * f0 / df))
        if k < 2 or k >= len(X) - 3:
            amps.append(0.0)
            continue
        amps.append(float(X[k - 3:k + 4].max()))
    band = X[int(40 / df):int(6000 / df)]
    floor = float(np.median(band)) + 1e-12
    return np.array(amps), floor


def envelope(seg):
    fr = max(int(0.005 * SR), 1)
    e = np.array([np.sqrt((seg[i:i + fr] ** 2).mean())
                  for i in range(0, len(seg) - fr, fr)])
    if len(e) < 4 or e.max() <= 0:
        return None, None
    db = 20 * np.log10(np.maximum(e, 1e-9) / e.max())
    k = int(np.argmax(e))
    atk = k * fr / SR * 1000.0
    tail = db[k:]
    if len(tail) > 3:
        t = np.arange(len(tail)) * fr / SR
        dec = float(np.polyfit(t, tail, 1)[0])
    else:
        dec = 0.0
    return atk, dec


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("moduledir")
    ap.add_argument("capturedir")
    ap.add_argument("out")
    ap.add_argument("--min-notes", type=int, default=6)
    ap.add_argument("--seconds", type=float, default=150.0)
    ap.add_argument("--per-track", type=int, default=40,
                    help="best-exposed notes to take per patch per track")
    a = ap.parse_args()

    caps = captures(a.capturedir)
    mods = {m.n: m for m in mwmm.load_all(a.moduledir)}
    acc = collections.defaultdict(list)
    env = collections.defaultdict(list)
    lvl = collections.defaultdict(list)

    for trk in sorted(set(caps) & set(mods)):
        m = mods[trk]
        rows, _ = vn.timeline(m, set(range(26)), 1)
        fm = [(t, v, p, 12 * b1 + b0) for t, v, p, b0, b1 in rows if v < 6 and p is not None]
        if not fm:
            continue
        onsets = np.array(sorted(t for t, _, _, _, _ in rows))
        x = decode(caps[trk], a.seconds)
        if len(x) < SR * 5:
            continue
        off = music_start(x)
        dur = len(x) / SR
        # reference level for this capture, so per-patch loudness is comparable
        # ACROSS tracks. Without this every patch renders at the same level and
        # quiet background voices punch through as loudly as leads.
        ref_db = 20 * np.log10(np.sqrt((x[int(off * SR):] ** 2).mean()) + 1e-12)

        cand = collections.defaultdict(list)
        for i, (t, v, p, semi) in enumerate(fm):
            if t + off + 0.30 > dur:
                continue
            near = int(np.searchsorted(onsets, t + 0.12) - np.searchsorted(onsets, t - 0.12))
            nxt = min([tt for tt, _, _, _ in fm if tt > t + 1e-6] or [t + 0.5])
            cand[p].append((near, t, semi, min(nxt - t, 0.30)))
        for p, lst in cand.items():
            lst.sort(key=lambda z: (z[0], -z[3]))
            for near, t, semi, hold in lst[:a.per_track]:
                if hold < 0.06:
                    continue
                f0 = 440.0 * 2.0 ** ((semi + ANCHOR - 69) / 12.0)
                if f0 < 35 or f0 * 2 > SR * 0.45:
                    continue
                st = int((t + off + 0.015) * SR)
                ln = int(min(hold, 0.22) * SR)
                if st + ln > len(x) or ln < 1024:
                    continue
                seg = x[st:st + ln]
                amps, floor = harmonics(seg, f0)
                if amps[0] <= 0 or amps.max() <= 0:
                    continue
                snr = 20 * np.log10(amps.max() / floor)
                if snr < 6:
                    continue
                acc[p].append(amps / amps.max())
                lvl[p].append(20 * np.log10(amps.max()) - ref_db)
                at, de = envelope(seg)
                if at is not None:
                    env[p].append((at, de, snr, near, trk))
        print("  track %02X: %d patches sampled" % (trk, len(cand)), flush=True)

    with open(a.out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["patch", "n_notes", "n_tracks", "snr_db", "grade",
                    "attack_ms", "decay_db_s", "level_db"]
                   + ["h%d_norm" % i for i in range(1, NH + 1)])
        ngrade = collections.Counter()
        for p in sorted(acc):
            v = np.array(acc[p])
            if len(v) < a.min_notes:
                continue
            med = np.median(v, axis=0)
            if med.max() <= 0:
                continue
            med = med / med.max()
            spread = float(np.median(np.abs(v - med).mean(axis=1)))
            e = env[p]
            atk = float(np.median([z[0] for z in e])) if e else 20.0
            dec = float(np.median([z[1] for z in e])) if e else -15.0
            snr = float(np.median([z[2] for z in e])) if e else 0.0
            ntr = len({z[4] for z in e})
            g = "A" if (len(v) >= 25 and ntr >= 2 and spread <= 0.12 and snr >= 12) else \
                "B" if (len(v) >= 12 and spread <= 0.20 and snr >= 9) else "C"
            ngrade[g] += 1
            lv = float(np.median(lvl[p])) if lvl[p] else 0.0
            w.writerow(["0x%02X" % p, len(v), ntr, "%.1f" % snr, g,
                        "%.1f" % atk, "%.1f" % dec, "%.1f" % lv]
                       + ["%.4f" % z for z in med])
    print("\nwrote %s   grades %s" % (a.out, dict(ngrade)))


if __name__ == "__main__":
    main()
