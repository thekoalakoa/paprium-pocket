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


def program_table(b, conf=0.5):
    """program -> (samples, native rate, root MIDI or None, loop point or None)"""
    be32 = lambda o: int.from_bytes(b[o:o + 4].tobytes(), "big")
    be16 = lambda o: int.from_bytes(b[o:o + 2].tobytes(), "big")
    out = {}
    for p in range(256):
        ptr, ln, loop, typ = be32(p * 16), be32(p * 16 + 4), be32(p * 16 + 8), be16(p * 16 + 12)
        if not ln or ptr >= len(b):
            continue
        ridx = typ + 1 if typ + 1 < len(RATES) else 1
        sr = 48000 // RATES[ridx]
        sig = b[ptr:ptr + ln].astype(np.float64) - 128.0
        r = measure_pitch(b[ptr:ptr + min(ln, 200000)], sr)
        root = 69 + 12 * np.log2(r[0] / 440.0) if (r and r[1] >= conf and r[0] > 0) else None
        lp = loop if loop != 0xFFFFFFFF and loop < ln else None
        out[p] = (sig, sr, root, lp)
    return out


def take(sig, step, n, loop):
    """n output samples of sig read at `step`, looping from `loop` if it runs out.

    LINEARLY interpolated. Nearest-neighbour was used first and it audibly
    distorts the bass: a low note off a high-rooted sample reads at step ~0.04,
    so each input sample is held for ~25 outputs and the waveform becomes a
    staircase with a harsh harmonic skirt. That reads as clipping even though
    nothing is near full scale.
    """
    pos = np.arange(n) * step
    end = len(sig) - 1
    if loop is None:
        pos = pos[pos <= end - 1]
    else:
        over = pos > end - 1
        if over.any():
            span = (end - 1) - loop
            if span <= 1:
                pos = pos[~over]
            else:
                pos = np.where(over, loop + np.mod(pos - (end - 1), span), pos)
    if not len(pos):
        return np.zeros(0)
    i0 = pos.astype(np.int64)
    frac = pos - i0
    i1 = np.minimum(i0 + 1, end)
    return sig[i0] * (1.0 - frac) + sig[i1] * frac


def render(m, progs, C, seconds, rate, only=None):
    n = int(seconds * rate)
    left = np.zeros(n + rate)
    right = np.zeros(n + rate)
    h09, base = m.d[0x09], 2 * m.d[0x07]
    seq = list(range(m.npos)) + [p for _ in range(60) for p in range(h09, m.npos)]

    # first pass: every event, with its absolute time
    evs = []
    t, T = 0.0, base
    for p in seq:
        if t > seconds + 4:
            break
        for r in range(m.G):
            for v in range(26):
                order = m.voice_order(v)
                if p >= len(order):
                    continue
                g, ev = m.pat[order[p]]
                i = g[r] if r < len(g) else 0
                if i and i < len(ev):
                    evs.append((t, v, ev[i]))
            for _, v, e in evs[-26:]:
                for k in (2, 4, 6):
                    if e[k] == 0xFA:
                        T = base + (e[k + 1] & 0x0F)
            t += T / CLK

    # Second pass: a note lasts until the voice's next NOTE or gate release.
    # It must NOT be cut short by a parameter-only record (byte 0 == 0), which is
    # about 6% of all events - doing that turned sustained notes into taps.
    nxt = {}
    for i in range(len(evs) - 1, -1, -1):
        tt, v, e = evs[i]
        end = nxt.get(v, seconds + 2.0)
        evs[i] = (tt, v, e, end)
        if (1 <= e[0] <= 12) or e[0] == 0x0E:
            nxt[v] = tt

    prog = {v: (m.d[0x2A + (v ^ 1)] or None) for v in range(26)}
    pan = {v: 0x80 for v in range(26)}
    placed = 0
    for tt, v, e, end in evs:
        for k in (2, 4, 6):
            if e[k] == 0x0F:
                prog[v] = e[k + 1]
            elif e[k] == 0x02:
                pan[v] = e[k + 1]
        if not (1 <= e[0] <= 12):
            continue
        if only is not None and v not in only:
            continue
        target = 12 * e[1] + e[0] + C
        f = 440.0 * 2.0 ** ((target - 69) / 12.0)
        dur = min(max(end - tt, 0.05), 4.0)
        ns = int(dur * rate)
        if ns < 16 or f < 20 or f > rate * 0.45:
            continue

        if v < 6:
            # YM2612 FM. The FM patch table has never been located, so this is a
            # stand-in: a harmonic stack, not the real timbre. Rendering these
            # with a WAVE sample was an earlier bug - voices 0-5 index a
            # different table, and playing FM notes through a 70 Hz sample made
            # the whole track sound like drums.
            #
            # Level and decay matter as much as timbre. At 40.0 with a 0.55 s
            # decay these six voices summed to a crest factor of 7.8 dB and ran
            # 10 dB hotter than all sixteen wave voices together, which is what
            # saturation sounds like even with no sample near full scale.
            th = 2 * np.pi * f * np.arange(ns) / rate
            seg = np.sin(th) * 15.0
            for h, amp in ((2, 0.5), (3, 0.25)):
                if h * f < rate * 0.45:                 # never alias a partial in
                    seg += np.sin(h * th) * 15.0 * amp
            seg *= np.exp(-np.arange(ns) / (0.30 * rate))
        elif v < 10:
            # PSG square, built from its odd harmonics so nothing lands past
            # Nyquist. np.sign() is the same wave with infinite bandwidth, and at
            # this sample rate its upper partials fold back as audible grit.
            th = 2 * np.pi * f * np.arange(ns) / rate
            seg = np.zeros(ns)
            for h in range(1, 40, 2):
                if h * f >= rate * 0.45:
                    break
                seg += np.sin(h * th) / h
            seg *= 20.0
            seg *= np.exp(-np.arange(ns) / (0.45 * rate))
        else:
            entry = progs.get(prog[v])
            if entry is None:
                continue
            sig, sr, root, loop = entry
            if len(sig) < 32 or root is None:
                step = sr / rate
            else:
                step = (sr / rate) * 2.0 ** ((target - root) / 12.0)
            if not np.isfinite(step) or step <= 0 or step > 40:
                continue
            seg = take(sig, step, ns, loop)
            if len(seg) < 16:
                continue

        a = min(int(0.003 * rate), len(seg) // 4)
        d = min(int(0.040 * rate), len(seg) // 3)
        env = np.ones(len(seg))
        if a: env[:a] = np.linspace(0, 1, a)
        if d: env[len(seg) - d:] = np.linspace(1, 0, d)
        seg = seg * env
        pv = pan[v] / 255.0
        start = int(tt * rate)
        room = len(left) - start
        if room <= 0:
            continue
        seg = seg[:room]
        left[start:start + len(seg)] += seg * (1.0 - pv * 0.8)
        right[start:start + len(seg)] += seg * (0.2 + pv * 0.8)
        placed += 1
    return np.stack([left[:n], right[:n]], axis=1), placed


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("moduledir")
    ap.add_argument("track", type=int)
    ap.add_argument("bank")
    ap.add_argument("out")
    ap.add_argument("--anchor", type=int, default=11,
                    help="C in MIDI = 12*byte1 + byte0 + C; solved value is 11")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--rate", type=int, default=32000)
    ap.add_argument("--voices", default=None,
                    help="render only these voices, e.g. 0-5 for FM, 10-25 for wave")
    a = ap.parse_args()

    b = load_bank(a.bank)
    progs = program_table(b)
    m = {x.n: x for x in mwmm.load_all(a.moduledir)}[a.track]
    only = None
    if a.voices:
        lo, _, hi = a.voices.partition("-")
        only = set(range(int(lo), int(hi or lo) + 1))
    buf, placed = render(m, progs, a.anchor, a.seconds, a.rate, only)
    peak = np.abs(buf).max()
    if peak > 0:
        buf = buf / peak * 0.89
    w = wave.open(a.out, "wb")
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(a.rate)
    w.writeframes((buf.reshape(-1) * 32767).astype("<i2").tobytes())
    w.close()
    print("track %d %s -> %s   C = %+d, %d notes placed, %.1f s"
          % (m.n, m.title, a.out, a.anchor, placed, a.seconds))


if __name__ == "__main__":
    main()
