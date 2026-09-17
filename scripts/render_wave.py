#!/usr/bin/env python3
"""Render an MWMM module with the cartridge's own instrument samples.

    python scripts/render_wave.py <moduledir> <track> <wave-bank.wav> out.wav
                                  [--anchor C] [--seconds 60] [--rate 32000]
                                  [--voices 0-5,12,20-25] [--mute 6-9]
    python scripts/render_wave.py <moduledir> <track> --dry-list

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
import json
import io
import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mwmm
from wave_roots import (load_bank, pitch as measure_pitch, RATES,
                        octave_fix, requested_notes)

CLK = 99.8745
NVOICES = 26


def parse_voices(spec, what="--voices"):
    """"0-5,12,20-25" -> {0..5, 12, 20..25}.

    A comma list of ranges and singletons. The old single-range form "lo-hi" is
    just the one-element case of it, so every existing command line still means
    what it meant. Out-of-range numbers are an error rather than a silent no-op:
    a mistyped solo that renders nothing looks exactly like a voice that is
    silent, and that is a trap when the whole point is isolated A/B evidence.
    """
    out = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        lo, sep, hi = part.partition("-")
        try:
            a = int(lo)
            b = int(hi) if sep else a
        except ValueError:
            raise SystemExit("%s: cannot parse %r in %r" % (what, part, spec))
        if b < a:
            a, b = b, a
        if a < 0 or b >= NVOICES:
            raise SystemExit("%s: voice %r out of range 0-%d" % (what, part, NVOICES - 1))
        out.update(range(a, b + 1))
    if not out:
        raise SystemExit("%s: no voices in %r" % (what, spec))
    return out


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
            h = [float(r[k]) for k in ("h%d_norm" % i for i in range(1, 40)) if k in r]
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
        # CLAMPED to +/-6 dB. The raw spread is 30.4 to 65.2 dB and it correlates
        # with each patch's own measurement SNR at Pearson r = +0.73 - the quietest
        # level in the table, patch 0x32, is also the hardest patch to measure. A
        # genuinely quiet instrument has no reason to be noisy to measure, so most
        # of that spread is measurement confidence being used as a mix level. It
        # buried Gothic voice 4 nineteen decibels under the mix while the cartridge's
        # own meter ranks that voice the LOUDEST of all 26.
        for v in out.values():
            v[3] = float(np.clip(10.0 ** ((v[3] - mid) / 20.0), 0.5, 2.0))
    return out


def patch_attack(patch):
    """Attack time in seconds from the patch's own fastest carrier, or None.

    fm_timbre.csv's `attack_ms` column is NOT an attack time. Against the real
    attack rate in the cartridge's patch bank it measures Spearman -0.044 over
    102 patches (p = 0.66) - no relationship at all - and 69 of those patches
    have a carrier at AR >= 30, which on a YM2612 is near instantaneous, yet the
    column gives them a median of 45 ms. Every patch in Dark Rock's opening
    unison is AR 31, about 1.5 ms, and the column says 40 to 55 ms.

    That matters twice over. A note ramped in over 50 ms has no transient, and
    the transient is where the high-frequency energy of an attack lives - which
    is why the opening measures four times too dark. And an onset detector keys
    on a sharp rise, so a slow ramp is not counted as an onset at all, which is
    where the "31% fewer onsets than hardware" came from. The notes were always
    there; they were fading in.
    """
    try:
        algo = patch["ALGO"] & 7
        carriers = ALGO[algo][1]
        ars = [patch["ops"][SLOT[c]]["AR"] for c in carriers if SLOT[c] < len(patch["ops"])]
    except (KeyError, IndexError, TypeError):
        return None
    if not ars:
        return None
    rate = eg_rate_db_s(max(ars))
    if rate <= 0:
        return None
    return float(np.clip(96.0 / rate, 0.0005, 0.25))


def measured_note(timbre, f, ns, rate, attack=None):
    """Additive synthesis from a measured harmonic profile, at its measured level."""
    h, atk, dec, gain = timbre
    if attack is not None:
        atk = attack
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


def program_table(b, conf=0.5, moddir=None):
    """program -> (samples, native rate, root MIDI or None, loop point or None)

    With `moddir`, each measured root is octave-corrected against how the music
    uses that program (wave_roots.octave_fix). That correction is UNVALIDATED and
    measurably harmful - see its docstring - so main() passes moddir only under
    --octave-fix, and the default is the raw measured root.
    """
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

    if moddir:
        fix = octave_fix({p: v[2] for p, v in out.items()}, requested_notes(moddir))
        for p, k in fix.items():
            if k and out[p][2] is not None:
                sig, sr, root, lp = out[p]
                out[p] = (sig, sr, root + 12 * k, lp)
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


def sax_voices(m):
    """Voices carrying the sax-layer marker: command 0x55 at position 0, row 0.

    Ten modules have this on voices 23-25 (see docs/PORT_PLAN.md). The sax man is
    an option the player enables, so rendering those voices unconditionally puts
    him in every performance - audible immediately on Asian Chill, one of the ten.

    The identification rests on the MODULE data, not on audio: programs 0x55 and
    0x94 appear in exactly those ten modules and in none of the other 42. Audio
    cannot settle it - two separate captures of a looping track drift apart, so a
    frame-by-frame A/B between a sax and non-sax recording shows a median
    difference of 0.42 even where they should match, and any average long enough
    to be stable washes three voices out of twenty-six away entirely.
    """
    out = set()
    for v in range(26):
        order = m.voice_order(v)
        if not order:
            continue
        g, ev = m.pat[order[0]]
        for i in g:
            if i and i < len(ev) and any(ev[i][k] == 0x55 for k in (2, 4, 6)):
                out.add(v)
                break
    return out


def event_timeline(m, seconds):
    """[(t, voice, event, end)] for the window a render of `seconds` would cover.

    Lifted out of render() unchanged so --dry-list reports on exactly the events
    the renderer would place, rather than a second implementation of the clock
    that could drift away from it.
    """
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
    return evs


def render(m, progs, C, seconds, rate, only=None, fm=None, timbres=None, wavelvl=None,
           fm_low=0.0,
           vgain=None,
           sax=False, mute=None):
    n = int(seconds * rate)
    left = np.zeros(n + rate)
    right = np.zeros(n + rate)
    evs = event_timeline(m, seconds)

    prog = {v: (m.d[0x2A + (v ^ 1)] or None) for v in range(26)}
    pan = {v: 0x80 for v in range(26)}
    # The sax man stays off unless --sax, exactly as before; --mute only ever
    # adds to that set, so it can never switch him on by accident.
    muted = set() if sax else sax_voices(m)

    if mute:
        muted = muted | set(mute)
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
        if v in muted:
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
            # A measured harmonic profile stops at its last measured harmonic, so
            # it band-limits a note in proportion to how LOW that note is. Dark
            # Rock opens on a three-voice unison at E1-F#2, 41 to 92 Hz, where a
            # 24-harmonic profile holds nothing above 1 kHz - and the capture's
            # spectral centroid there is 1226 Hz against our 299. Below that the
            # profile stops describing the timbre, so fall through to the
            # cartridge's own patch, which has no ceiling.
            # --fm-low swaps a low note to the cartridge's own patch, because a
            # measured profile band-limits a note in proportion to how low it is
            # (Dark Rock's 41-92 Hz opening: 24 harmonics reach barely 1 kHz and
            # the capture's centroid there is 1226 against our 299). It is OFF by
            # default: it overshoots to 2035. Continuing the profile with the
            # patch's own shape instead was tried and is WORSE - it puts 66% of
            # the opening in 1-3 kHz where hardware has 5%. The FM darkness is
            # not solved; both known fixes overshoot.
            if meas is not None and fm_low and pn in fm and f * len(meas[0]) < fm_low:
                meas = None
            if meas is not None:
                seg = measured_note(meas, f, ns, rate,
                                    attack=patch_attack(fm[pn]) if pn in fm else None) * 260.0
            else:
                patch = fm.get(pn)
                if patch is None:
                    continue
                seg = fm_note(patch, f, ns, rate) * 118.0
        # Voices 6-9 are WAVE voices, not PSG square waves. The 6 FM / 4 PSG / 16 wave
        # split was GPGX's ch<6 / ch<10 / else branch, never a hardware measurement.
        # Their 0x0F programs land on live bank samples 249 times out of 249 (0x0C is a
        # 1.15 s bass-guitar sample, 0x04 a 2.9 s LOOPED pad - the three-minute
        # steady meter level on Theme Of Paprium's voice 9), and on 2026-09-16 the
        # player confirmed by ear that Gothic's voice 6 rendered as bank sample 0x0C
        # at its measured root IS the bass guitar the square wave had replaced.
        # Voices 6-25 therefore take the wave path below, same pitch law, same roots.
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
            if len(sig) < 32 or root is None:
                step = sr / rate
            else:
                # NO GUARD. Transposing from a correctly measured root is
                # self-cancelling - the sounding pitch is the sample's own pitch
                # times 2^((target - root)/12), and when `root` IS that pitch the
                # result is exactly the written note. The sax A/B confirmed on
                # hardware that the cartridge plays the written note (program
                # 0x56, 33 of 41 pitches within 0.6 semitone, median error 0.22).
                #
                # The +/-24 guard threw that away. Dark Rock 35-42 s has voices
                # 10, 11 and 12 all writing G3, and they came out at 41, 2715 and
                # 30 Hz - six and a half octaves apart on one written note, which
                # is why the 250 Hz-1 kHz body of that section was 16% against
                # the capture's 53%. Removing the guard puts voice 10 at 199.7 Hz
                # against a written 196.0.
                #
                # What remains is root QUALITY, not the guard: a program whose
                # root is mis-measured transposes the error straight through, and
                # one whose root is not measured at all still plays untransposed.
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
        # Per-voice mix level, read off the cartridge's own VU meter
        # (scripts/vu_gain.py). It is not in the module - array A at +0x10 is a
        # flat 0x10 everywhere - and the renderer has no other source for it.
        if vgain:
            seg = seg * vgain.get(v, 1.0)
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


def dry_list(m, seconds, only=None, mute=None, sax=False):
    """Per voice: note count, distinct programs, total sounding seconds.

    An inventory of the module over the same window a render would cover, so a
    solo can be aimed before any audio is made. Programs are tracked exactly the
    way render() tracks them - the static byte at +0x2A as the initial value,
    then command 0x0F wherever it appears, on every event including ones on
    voices that are muted or filtered out.
    """
    evs = event_timeline(m, seconds)
    saxv = sax_voices(m)
    muted = (set() if sax else set(saxv)) | set(mute or ())
    prog = {v: (m.d[0x2A + (v ^ 1)] or None) for v in range(26)}
    notes = collections.Counter()
    secs = collections.defaultdict(float)
    used = collections.defaultdict(list)
    for tt, v, e, end in evs:
        for k in (2, 4, 6):
            if e[k] == 0x0F:
                prog[v] = e[k + 1]
        if not (1 <= e[0] <= 12):
            continue
        notes[v] += 1
        # the same clamp render() applies, so this is sounding time as RENDERED
        secs[v] += min(max(end - tt, 0.05), 4.0)
        if prog[v] not in used[v]:
            used[v].append(prog[v])

    print("track %d  %s   G=%d, %d positions, loop at %d, %d of 26 voices sounding"
          % (m.n, m.title, m.G, m.npos, m.d[0x09], sum(1 for v in range(26) if notes[v])))
    print("window %.1f s; sounding = sum of note lengths clamped to [0.05, 4.00] s,"
          % seconds)
    print("the same clamp the renderer uses, so voices never overlap themselves.")
    print("\n%3s %5s %-11s %7s %10s  %s"
          % ("v", "kind", "state", "notes", "sounding s", "programs"))
    tot_n, tot_s = 0, 0.0
    for v in range(26):
        kind = "FM" if v < 6 else "wave"
        if only is not None and v not in only:
            state = "off:-voices"
        elif v in (mute or ()):
            state = "off:-mute"
        elif v in muted:
            state = "off:sax"
        elif not notes[v]:
            state = "silent"
        else:
            state = "render"
        ps = " ".join("--" if p is None else "0x%02X" % p for p in used[v]) or "--"
        print("%3d %5s %-11s %7d %10.2f  %s"
              % (v, kind, state, notes[v], secs[v], ps))
        tot_n += notes[v]
        tot_s += secs[v]
    print("%3s %5s %-11s %7d %10.2f" % ("", "", "total", tot_n, tot_s))
    if saxv:
        print("\nsax-man voices (command 0x55): %s%s"
              % (sorted(saxv), "" if sax else "  - muted, pass --sax to hear them"))
    print("\nMETHOD BLIND: this reads the MODULE only. It cannot see whether a note"
          "\nsurvives rendering - a wave program missing from the bank, an FM patch"
          "\nwith no measured timbre, or a pitch outside the band is dropped in"
          "\nrender() and still counted here. Compare against 'notes placed'.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("moduledir")
    ap.add_argument("track", type=int)
    # optional ONLY so --dry-list, which needs neither, can be run without
    # naming a bank and an output file it would never touch
    ap.add_argument("bank", nargs="?")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--anchor", type=int, default=11,
                    help="C in MIDI = 12*byte1 + byte0 + C; solved value is 11")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--rate", type=int, default=32000)
    ap.add_argument("--sax", action="store_true",
                    help="play the sax-man layer (voices marked 0x55). OFF by default: "
                         "the ordinary captures were recorded without him, and he is "
                         "an option the player enables in the boombox")
    ap.add_argument("--wave-levels", default=None,
                    help="MEASURED AND REJECTED - see the note in main(); leave unset")
    ap.add_argument("--timbres", default=None,
                    help="fm_timbre.csv - measured FM timbres, preferred over the model")
    ap.add_argument("--rom", default=None,
                    help="paprium.md, to render FM voices from the real patch bank")
    ap.add_argument("--vu-gain", default=None,
                    help="per-voice gain table from scripts/vu_gain.py (JSON), measured "
                         "from the hardware capture's on-screen level meter")
    ap.add_argument("--fm-low", type=float, default=0.0,
                    help="below this top-harmonic frequency (Hz), render FM from the ROM "
                         "patch instead of the measured profile, whose harmonic ceiling "
                         "band-limits low notes. 0 disables.")
    ap.add_argument("--octave-fix", action="store_true",
                    help="apply the corpus octave correction of wave roots. OFF by default: "
                         "it is NOT validated and it moves 24 confidence-1.00 programs by up "
                         "to five octaves. See wave_roots.octave_fix.")
    ap.add_argument("--voices", default=None,
                    help="render only these voices: a comma list of ranges and "
                         "singletons, e.g. 0-5 for FM, 10-25 for wave, "
                         "0-5,12,20-25 for a mixture. Default: all")
    ap.add_argument("--mute", default=None,
                    help="silence these voices, same syntax as --voices, applied "
                         "after it. The sax-man default is unaffected: this only "
                         "ever adds to what is muted")
    ap.add_argument("--dry-list", action="store_true",
                    help="print per-voice note count, programs and sounding "
                         "seconds, then exit without rendering")
    a = ap.parse_args()

    m = {x.n: x for x in mwmm.load_all(a.moduledir)}[a.track]
    only = parse_voices(a.voices, "--voices") if a.voices else None
    mute = parse_voices(a.mute, "--mute") if a.mute else None
    if a.dry_list:
        dry_list(m, a.seconds, only, mute, a.sax)
        return
    if not a.bank or not a.out:
        ap.error("bank and out are required unless --dry-list is given")

    b = load_bank(a.bank)
    progs = program_table(b, moddir=a.moduledir if a.octave_fix else None)
    live = sum(1 for v in progs.values() if len(v[0]) >= 32)
    if live < 90:
        ap.error("%s yields only %d live programs (expected ~94). Wrong bank or "
                 "wrong sample width - check that load_bank matches the file." % (a.bank, live))
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
    vgain = None
    if a.vu_gain:
        vgain = {int(k): float(v) for k, v in json.load(open(a.vu_gain)).items()}
        print("VU gain: %d voices, %+.1f to %+.1f dB"
              % (len(vgain), 20 * np.log10(min(vgain.values())),
                 20 * np.log10(max(vgain.values()))))
    buf, placed = render(m, progs, a.anchor, a.seconds, a.rate, only=only, fm=fm,
                         timbres=timbres, wavelvl=wavelvl, vgain=vgain,
                         fm_low=a.fm_low, sax=a.sax, mute=mute)
    peak = np.abs(buf).max()
    if peak > 0:
        buf = buf / peak * 0.89
    w = wave.open(a.out, "wb")
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(a.rate)
    w.writeframes((buf.reshape(-1) * 32767).astype("<i2").tobytes())
    w.close()
    print("track %d %s -> %s   C = %+d, %d notes placed, %.1f s%s%s"
          % (m.n, m.title, a.out, a.anchor, placed, a.seconds,
             "" if only is None else "   voices %s" % sorted(only),
             "" if not mute else "   muted %s" % sorted(mute)))


if __name__ == "__main__":
    main()
