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
import io
import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mwmm
from wave_roots import load_bank, pitch as measure_pitch, RATES

CLK = 99.8745



# ---------------------------------------------------------------- YM2612 FM

# Algorithm topology, operators numbered 1..4 in the logical sense.
# mods[c] lists which operators modulate operator c; carriers are summed.
ALGO = {
    0: ({1: [0], 2: [1], 3: [2]}, [3]),
    1: ({2: [0, 1], 3: [2]}, [3]),
    2: ({2: [1], 3: [0, 2]}, [3]),
    3: ({1: [0], 3: [1, 2]}, [3]),
    4: ({1: [0], 3: [2]}, [1, 3]),
    5: ({1: [0], 2: [0], 3: [0]}, [1, 2, 3]),
    6: ({1: [0]}, [1, 2, 3]),
    7: ({}, [0, 1, 2, 3]),
}
# the bank stores operators in the YM2612's register order Op1, Op3, Op2, Op4,
# so logical op 1..4 reads table slots 0, 2, 1, 3
SLOT = [0, 2, 1, 3]
DETUNE = [0.0, 0.0012, 0.0024, 0.0036, 0.0, -0.0012, -0.0024, -0.0036]


def eg_rate_db_s(rate):
    """YM2612 envelope rate -> decibels per second. An approximation: the real
    chip advances an attenuation counter in steps whose size depends on rate and
    key code. Rate 0 means the phase never advances."""
    return 0.0 if rate <= 0 else 96.0 / (0.0015 * 26667.0 ** ((31 - rate) / 30.0))


def fm_envelope(op, ns, rate):
    """Amplitude envelope for one operator: attack, first decay to the sustain
    level, then second decay. Release is handled by the caller's note length."""
    t = np.arange(ns) / rate
    ar, d1r, d2r, d1l = op["AR"], op["D1R"], op["D2R"], op["D1L"]
    if ar >= 31:
        atk = 0.0005
    else:
        atk = min(2.0, 0.0015 * 26667.0 ** ((31 - ar) / 30.0))
    env_db = np.zeros(ns)
    rising = t < atk
    env_db[rising] = -60.0 * (1.0 - t[rising] / max(atk, 1e-9))
    td = np.maximum(t - atk, 0.0)
    sus_db = -3.0 * d1l if d1l < 15 else -96.0
    r1 = eg_rate_db_s(d1r)
    d1_db = np.maximum(-r1 * td, sus_db)
    reached = np.where(d1_db <= sus_db)[0]
    out = d1_db.copy()
    if len(reached):
        k = reached[0]
        r2 = eg_rate_db_s(d2r)
        out[k:] = sus_db - r2 * (t[k:] - t[k])
    out[rising] = env_db[rising]
    return 10.0 ** (np.clip(out, -96.0, 0.0) / 20.0)


def fm_note(patch, f, ns, rate):
    """Render one note of a YM2612 patch. Modulation is applied to phase, which
    is what FM is; feedback on operator 1 is approximated by one iteration
    rather than a true per-sample recursion."""
    algo, fb = patch["ALGO"], patch["FB"]
    mods, carriers = ALGO[algo]
    n = np.arange(ns)
    outs = [None] * 4
    envs, amps, phases = [], [], []
    for i in range(4):
        op = patch["ops"][SLOT[i]]
        mul = op["MUL"] if op["MUL"] else 0.5
        if i in carriers:
            # A real YM2612 multiplies EVERY operator's frequency by MUL, so a
            # carrier at MUL 8 sounds three octaves above the written note. This
            # bank is full of them - patch 0x01's carrier is x0.5 and 0x02's are
            # x4, x8 and x12 - and those two patches are played in UNISON on
            # voices 0 and 1 of Theme Of Paprium, 508 notes on identical
            # semitones. Rendered the YM2612 way they split octaves apart, which
            # is what the player heard as "two instruments at the wrong timing",
            # and it put Dark Rock's 46 Hz opening at 368 Hz.
            # The cartridge synthesises FM in its own firmware and evidently
            # does not do this: holding carriers at the written note and using
            # MUL only as a modulator ratio measures better against hardware on
            # both chroma (0.818 vs 0.806) and band balance (0.246 vs 0.272).
            mul = 1.0
        fo = f * mul * (1.0 + DETUNE[op["DT"] & 7])
        if fo > rate * 0.48:
            fo = rate * 0.48
        phases.append(2 * np.pi * fo * n / rate)
        envs.append(fm_envelope(op, ns, rate))
        amps.append(2.0 ** (-op["TL"] / 8.0))
    for i in range(4):
        ph = phases[i]
        if i in mods:
            m = np.zeros(ns)
            for src in mods[i]:
                if outs[src] is not None:
                    m += outs[src]
            ph = ph + 3.0 * m
        y = np.sin(ph)
        if i == 0 and fb:
            y = np.sin(ph + (fb / 7.0) * 1.5 * y)
        outs[i] = y * envs[i] * amps[i]
    return sum(outs[c] for c in carriers) / max(len(carriers), 1)



def load_timbres(path, grades=("A", "B", "C")):
    """Measured FM timbres: {patch: (harmonic amplitudes, attack s, decay dB/s)}.

    These come from the hardware captures, not from theory - each patch's
    harmonic profile was measured by windowing individual notes whose time and
    pitch are known from the solved clock. That matters because the cartridge
    does NOT contain a YM2612: it renders FM in its own firmware, so its patch
    data is in YM2612 format while its synthesis is its own. Modelling the chip
    reproduces the data but not the sound - on Dark Rock's opening note the chip
    model puts the 3rd harmonic 22 dB below where hardware has it.
    """
    import csv
    out = {}
    for r in csv.DictReader(io.open(path, encoding="utf-8")):
        if r.get("grade") not in grades:
            continue
        try:
            h = [float(r["h%d_norm" % i]) for i in range(1, 15)]
            atk = float(r["attack_ms"]) / 1000.0
            dec = abs(float(r["decay_db_s"]))
            lvl = float(r.get("level_db") or 0.0)
        except (KeyError, ValueError):
            continue
        if max(h) <= 0:
            continue
        out[int(r["patch"], 16)] = [np.array(h) / max(h), max(atk, 0.002), dec, lvl]

    # Each profile is shape-normalised, so without this every patch would render
    # at the same loudness and quiet background voices would punch through as
    # hard as leads - which is exactly what a listener notices first. level_db is
    # each patch's measured level relative to its own capture's RMS; recentre on
    # the median so the typical patch keeps the calibrated gain and the rest sit
    # where hardware puts them.
    if out:
        mid = float(np.median([v[3] for v in out.values()]))
        for v in out.values():
            v[3] = float(np.clip(10.0 ** ((v[3] - mid) / 20.0), 0.05, 6.0))
    return out


def measured_note(timbre, f, ns, rate):
    """Additive synthesis from a measured harmonic profile, at its measured level."""
    h, atk, dec, gain = timbre
    n = np.arange(ns)
    t = n / rate
    y = np.zeros(ns)
    for i, amp in enumerate(h):
        fh = (i + 1) * f
        if amp <= 0.001 or fh >= rate * 0.45:
            continue
        y += amp * np.sin(2 * np.pi * fh * n / rate)
    env = np.where(t < atk, t / max(atk, 1e-9), 10.0 ** (-dec * (t - atk) / 20.0))
    return y * env * gain / max(np.abs(h).sum(), 1e-9)


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


def render(m, progs, C, seconds, rate, only=None, fm=None, timbres=None, wavelvl=None):
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
            # YM2612 FM, rendered from the cartridge's own patch bank at ROM
            # 0x004000 (see scripts/fm_patches.py). Before the bank was found
            # this was a generic harmonic stack, which is why FM-led tracks
            # sounded synthetic no matter how exact the pitch was.
            pn = prog[v] if prog[v] is not None else 0
            meas = timbres.get(pn) if timbres else None
            if meas is not None:
                seg = measured_note(meas, f, ns, rate) * 260.0
            else:
                patch = fm.get(pn)
                if patch is None:
                    continue
                seg = fm_note(patch, f, ns, rate) * 118.0
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
            seg *= 128.0
            seg *= np.exp(-np.arange(ns) / (0.45 * rate))
        else:
            entry = progs.get(prog[v])
            if entry is None:
                continue
            sig, sr, root, loop = entry
            # A root is only believable if the note sits within a couple of
            # octaves of it. Gothic asks for shifts of -59 and +27 semitones
            # around 22 s, which are step 0.02 and step 4.5 - a sample dragged
            # into sub-audio rumble, or screeching with aliasing. Those are
            # percussion entries and mis-detected roots, not instrument design,
            # so play them at their own rate rather than transposing wildly.
            if len(sig) < 32 or root is None or abs(target - root) > 24:
                step = sr / rate
            else:
                step = (sr / rate) * 2.0 ** ((target - root) / 12.0)
            if not np.isfinite(step) or step <= 0 or step > 40:
                continue
            seg = take(sig, step, ns, loop)
            if len(seg) < 16:
                continue
            # Sample amplitude alone does not say how loud a program is in the
            # mix - two instruments recorded at the same peak can sit 20 dB
            # apart. wavelvl carries each program's level as measured from the
            # captures, the same treatment the FM patches get.
            if wavelvl:
                seg = seg * wavelvl.get(prog[v], 1.0)

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
    ap.add_argument("--wave-levels", default=None,
                    help="MEASURED AND REJECTED - see the note in main(); leave unset")
    ap.add_argument("--timbres", default=None,
                    help="fm_timbre.csv - measured FM timbres, preferred over the model")
    ap.add_argument("--rom", default=None,
                    help="paprium.md, to render FM voices from the real patch bank")
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
    fm = {}
    if a.rom:
        import fm_patches
        t = fm_patches.load(a.rom)
        fm = {p: fm_patches.decode(t[p]) for p in range(len(t))}
        print("FM bank: %d patches from %s" % (len(fm), a.rom))
    timbres = load_timbres(a.timbres) if a.timbres else None
    if timbres:
        print("measured timbres: %d patches" % len(timbres))
    # Calibrating WAVE levels the way FM levels were calibrated does not work,
    # and the reason is instructive. FM needed a measured level because
    # load_timbres normalises each harmonic profile and throws the loudness
    # away. A wave sample never loses it - the cartridge plays the sample as
    # recorded, so its own amplitude already IS the level. Applying a measured
    # level on top double-counts (Theme Of Paprium chroma 0.823 -> 0.565) and
    # applying the residual over the sample's RMS is no better (0.559).
    # It is NOT that wave notes are harder to isolate: measured over the whole
    # corpus, 3.7% of wave notes have two or fewer other onsets within 120 ms
    # against 3.8% of FM notes. The flag stays for reproducing the negative.
    wavelvl = None
    if a.wave_levels:
        # A wave sample already carries its own loudness, so the measured level
        # must not be applied on top of it - that double-counts and wrecks the
        # balance (it cost Theme Of Paprium 0.823 -> 0.565 chroma). What the
        # cartridge adds is the RESIDUAL: measured level minus the sample's own
        # RMS. That is what gets applied here.
        import csv as _csv
        raw = {}
        for r in _csv.DictReader(io.open(a.wave_levels, encoding="utf-8")):
            try:
                raw[int(r["patch"], 16)] = float(r["level_db"])
            except (KeyError, ValueError):
                continue
        res = {}
        for pn, lvl in raw.items():
            e = progs.get(pn)
            if e is None or len(e[0]) < 64:
                continue
            srms = float(np.sqrt((e[0].astype(np.float64) ** 2).mean()))
            if srms <= 0:
                continue
            res[pn] = lvl - 20.0 * np.log10(srms)
        if res:
            mid = float(np.median(list(res.values())))
            wavelvl = {pn: float(np.clip(10.0 ** ((v - mid) / 20.0), 0.15, 4.0))
                       for pn, v in res.items()}
            print("wave levels: %d programs (residual over sample RMS)" % len(wavelvl))
    buf, placed = render(m, progs, a.anchor, a.seconds, a.rate, only, fm, timbres, wavelvl)
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
