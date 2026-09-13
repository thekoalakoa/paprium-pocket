#!/usr/bin/env python3
"""Solve the absolute pitch anchor C against the hardware captures.

    python scripts/solve_anchor.py <moduledir> <capturedir>

Notes are stored as a pitch class 1..12 (byte 0) and an octave (byte 1), giving
`semitone = 12*byte1 + byte0`. Everything about the music follows from that
except one constant:

    MIDI note = 12*byte1 + byte0 + C

C is what ties the note numbering to real pitch. Get it wrong and every track
plays in the wrong key or octave - the right tune, transposed.

**Answer: C = +11.** So byte0 = 1 is a C in every octave, and byte1 = 4 with
byte0 = 1 is middle C.

How it is measured, and why this works where earlier attempts failed: the row
clock is solved (see PORT_PLAN), so every note's time is known to a few ppm.
That allows the spectrum to be sampled in the exact window of each individual
note rather than averaged over a whole track. For a candidate C, energy is
summed at the predicted fundamental and its 2nd and 3rd harmonics across every
note of one voice; the correct C aligns hundreds of notes at once.

Pooling per-track z-scores over 11 tracks:

    C = +11   z = 23.8   <-- best
    C = +12   z = 17.4       adjacent-bin leakage, not a competitor
    C = +23   z = 16.6       one octave up
    C =  -1   z =  9.1

Three independent checks agree. C = 11 (mod 12) is what rotating module
pitch-class histograms against capture chroma gives, by a completely different
route. C = +11 puts the sax lead of Dark Rock at MIDI 54-78, a real saxophone
range, where -13 would demand MIDI 30. And it makes byte0 = 1 a C, which is what
a 1..12 pitch class starting at C requires.

NOTE this supersedes a reading that there is no global C and that pitch is
relative to each program's own sample root. Sample roots sit at C3, C4, C5 and
C6, and solving per-program gave a different REF for each - but the same C. The
cartridge compensates the octave through the program table's rate field, so the
roots cancel and one global C governs everything.
"""

import argparse
import os
import re
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mwmm
import voice_notes as vn

SR = 22050
NF = 4096
# (track, the voice to follow, capture filename)
CASES = [(60, 10, "3C Urban.mkv"), (15, 0, "0F Cyber Ninja.mkv"),
         (52, 16, "34 Spiral.mkv"), (39, 25, "27 Indie Break Beat.mkv"),
         (57, 0, "39 Theme of Pap.mkv"), (30, 2, "1E Gothic.mkv"),
         (62, 0, "3E Waterfront Beat.mkv"), (22, 0, "16 Dark Rock.mkv"),
         (37, 0, "25 House.mkv"), (6, 0, "06 Blade FM.mkv"),
         (47, 0, "2F Sadness.mkv")]


def decode(path, seconds=150):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-t", str(seconds), "-i", path,
                          "-map", "a:0", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         stdout=subprocess.PIPE, check=True).stdout
    return np.frombuffer(raw, dtype="<f4").astype(np.float64)


def music_start(x):
    """Captures open with a second or so of lead-in before the track begins."""
    fr = int(0.01 * SR)
    e = np.sqrt(np.convolve(x * x, np.ones(fr) / fr, "same"))
    thr = max(np.percentile(e[:SR], 50) * 20, e.max() * 0.02)
    return int(np.argmax(e > thr)) / SR


def note_spectra(x, off, notes):
    """One normalised spectrum per note, taken in that note's own window."""
    w = np.hanning(NF)
    df = np.fft.rfftfreq(NF, 1.0 / SR)[1]
    out = []
    for i, (t, s) in enumerate(notes):
        dur = (notes[i + 1][0] - t) if i + 1 < len(notes) else 0.25
        st = int((t + off + 0.02) * SR)
        if st + NF > len(x) or dur < 0.08:
            continue
        mag = np.abs(np.fft.rfft(x[st:st + NF] * w))
        out.append((s, mag / (mag[int(50 / df):int(4000 / df)].sum() + 1e-30)))
    return out, df


def score(specs, df, C):
    tot = 0.0
    for s, mag in specs:
        f = 440.0 * 2.0 ** ((s + C - 69) / 12.0)
        if f < 45 or f > 3000:
            continue
        for h, wt in ((1, 1.0), (2, 0.55), (3, 0.3)):
            k = int(round(h * f / df))
            if 2 <= k < len(mag) - 2:
                tot += wt * mag[k - 1:k + 2].max()
    return tot


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("moduledir")
    ap.add_argument("capturedir")
    ap.add_argument("--lo", type=int, default=-24)
    ap.add_argument("--hi", type=int, default=36)
    a = ap.parse_args()

    mods = {m.n: m for m in mwmm.load_all(a.moduledir)}
    cs = list(range(a.lo, a.hi + 1))
    pool = np.zeros(len(cs))
    used = 0
    print("%-24s %6s %7s" % ("capture", "notes", "best C"))
    for trk, voice, fn in CASES:
        path = os.path.join(a.capturedir, fn)
        if not os.path.exists(path) or trk not in mods:
            continue
        x = decode(path)
        if len(x) < SR * 20:
            continue
        off = music_start(x)
        rows, _ = vn.timeline(mods[trk], {voice}, 1)
        notes = [(t, 12 * b1 + b0) for t, v, p, b0, b1 in rows
                 if t + off + 0.3 < len(x) / SR]
        specs, df = note_spectra(x, off, notes)
        if len(specs) < 60:
            continue
        v = np.array([score(specs, df, C) for C in cs])
        pool += (v - v.mean()) / (v.std() + 1e-30)
        used += 1
        print("%-24s %6d %7d" % (fn[:24], len(specs), cs[int(np.argmax(v))]))

    order = np.argsort(-pool)
    print("\npooled over %d tracks:" % used)
    for i in order[:6]:
        print("   C = %+3d   z = %6.2f%s" % (cs[i], pool[i], "   <== ANSWER" if i == order[0] else ""))


if __name__ == "__main__":
    main()
