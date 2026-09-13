#!/usr/bin/env python3
"""Render an MWMM module with the cartridge's own instrument samples.

    python scripts/render_wave.py <moduledir> <track> <wave-bank.wav> out.wav
                                  [--anchor C] [--seconds 60] [--rate 32000]

Unlike the old render_mwmm.py (which predates the decoded format and plays square
waves), this uses the real model and the real samples:

  * order list at +0xD8, voice-major, 26 voices x npos positions
  * a pattern is G one-byte grid rows indexing an 8-byte event table
  * word 0 of an event is the note - byte0 is a pitch class 1..12, byte1 an
    octave, 0x0E is a gate release
  * words 1-3 are (command, operand); 0x0F selects the instrument program and
    0xFA sets the row period
  * row period T = 2*header[+0x07] + (0xFA operand & 0x0F) ticks at 99.8745 Hz
  * playback repeats from position header[+0x09]

Pitch is `12*byte1 + byte0 + C`. **C is the one unknown**, and it is known only
modulo 12: byte0 = 1 is a C, established by rotating module pitch-class
histograms against hardware captures. The octave is open, so --anchor renders a
candidate and the answer is audible - which is the point of this script. The
candidates are -13, -1, 11, 23, 35.

Each program's root pitch is measured from its own sample (scripts/wave_roots.py)
because the program table carries no root field. A program whose sample has no
stable pitch - percussion, noise - is played at its base rate regardless of the
note, which is the right behaviour for a drum.

Derived from a commercial ROM: keep the output local.
"""

import argparse
import collections
import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mwmm
from wave_roots import load_bank, pitch as measure_pitch, RATES

CLK = 99.8745


def program_table(b):
    be32 = lambda o: int.from_bytes(b[o:o + 4].tobytes(), "big")
    be16 = lambda o: int.from_bytes(b[o:o + 2].tobytes(), "big")
    out = {}
    for p in range(256):
        ptr, ln, typ = be32(p * 16), be32(p * 16 + 4), be16(p * 16 + 12)
        if not ln or ptr >= len(b):
            continue
        ridx = typ + 1 if typ + 1 < len(RATES) else 1
        sr = 48000 // RATES[ridx]
        sig = b[ptr:ptr + ln]
        r = measure_pitch(sig[:min(len(sig), 200000)], sr)
        root = None
        if r and r[1] >= 0.75 and r[0] > 0:
            root = 69 + 12 * np.log2(r[0] / 440.0)
        out[p] = (sig.astype(np.float64) - 128.0, sr, root)
    return out


def render(m, progs, C, seconds, rate):
    n = int(seconds * rate)
    buf = np.zeros(n + rate, dtype=np.float64)
    h09, base = m.d[0x09], 2 * m.d[0x07]
    seq = list(range(m.npos)) + [p for _ in range(40) for p in range(h09, m.npos)]
    cur = {v: None for v in range(26)}
    # a voice's static program, if the module sets one
    for v in range(26):
        b = m.d[0x2A + (v ^ 1)]
        if b:
            cur[v] = b
    t, T = 0.0, base
    placed = 0
    for p in seq:
        for r in range(m.G):
            if t > seconds:
                return buf[:n], placed
            for v in range(26):
                order = m.voice_order(v)
                if p >= len(order):
                    continue
                g, ev = m.pat[order[p]]
                i = g[r] if r < len(g) else 0
                if not i or i >= len(ev):
                    continue
                e = ev[i]
                for k in (2, 4, 6):
                    if e[k] == 0xFA:
                        T = base + (e[k + 1] & 0x0F)
                    elif e[k] == 0x0F:
                        cur[v] = e[k + 1]
                if not (1 <= e[0] <= 12):
                    continue
                entry = progs.get(cur[v])
                if entry is None:
                    continue
                sig, sr, root = entry
                if len(sig) < 64:
                    continue
                # The cartridge cannot know its samples' recorded pitches: it can
                # only set a playback RATE from the note number, with one constant
                # for the whole synth. What you hear is the sample's own pitch
                # transposed by that. So the renderer needs no per-sample root.
                semi = 12 * e[1] + e[0]
                step = (sr / rate) * 2.0 ** ((semi - C) / 12.0)
                if not np.isfinite(step) or step <= 0 or step > 64:
                    continue
                count = int(min(len(sig) / step, 1.2 * rate))   # cap one note at 1.2 s
                if count < 8:
                    continue
                idx = (np.arange(count) * step).astype(np.int64)
                idx = idx[idx < len(sig)]
                start = int(t * rate)
                seg = sig[idx] * np.linspace(1.0, 0.0, len(idx)) ** 0.5   # simple decay
                room = len(buf) - start
                if room <= 0:
                    continue
                seg = seg[:room]
                buf[start:start + len(seg)] += seg
                placed += 1
            t += T / CLK
    return buf[:n], placed


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("moduledir")
    ap.add_argument("track", type=int)
    ap.add_argument("bank")
    ap.add_argument("out")
    ap.add_argument("--anchor", type=int, default=60,
                    help="REF in rate = base * 2^((semitone - REF)/12)")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--rate", type=int, default=32000)
    a = ap.parse_args()

    b = load_bank(a.bank)
    progs = program_table(b)
    m = {x.n: x for x in mwmm.load_all(a.moduledir)}[a.track]
    buf, placed = render(m, progs, a.anchor, a.seconds, a.rate)
    peak = np.abs(buf).max()
    if peak > 0:
        buf = buf / peak * 0.89
    w = wave.open(a.out, "wb")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(a.rate)
    w.writeframes((buf * 32767).astype("<i2").tobytes())
    w.close()
    print("track %d %s -> %s   REF = %d, %d notes placed, %.1f s"
          % (m.n, m.title, a.out, a.anchor, placed, a.seconds))


if __name__ == "__main__":
    main()
