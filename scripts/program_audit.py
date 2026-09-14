#!/usr/bin/env python3
"""Audit the path from an MWMM event to an audible sound, and find where it breaks.

    python scripts/program_audit.py <moduledir> <wave-bank.wav>
           [--rom paprium.md] [--timbres fm_timbre.csv]
           [--tracks 30,57] [--corpus] [--anchor 11] [--rate 32000] [--csv out.csv]

"Is an instrument missing?" is not an audio question. A module names its
instruments explicitly - command 0x0F carries a program number on every voice -
so the question can be answered by walking the same state machine
scripts/render_wave.py walks and asking, for each (voice, program) pair that has
notes, whether the renderer emits anything for it.

There are only a few ways to lose an instrument, and this checks all of them:

  wave voices 10-25   the program must exist in the 256 x 16-byte table at
                      offset 0 of the decoded bank, with a non-zero length, a
                      pointer inside the file, and a sample that is not silence.
                      render_wave does `progs.get(prog[v])` and `continue`s on a
                      miss, so a missing entry is SILENCE, not a wrong noise.
                      A program with no measurable root pitch, or a note more
                      than two octaves from that root, is played at the sample's
                      own base rate - right for a drum, wrong for a melody.
  FM voices 0-5       a measured timbre in fm_timbre.csv is used if the patch has
                      one at grade A/B/C. Otherwise the modelled 4-op synth runs,
                      which sounds different; and if the patch number is past the
                      135-record ROM bank, or --rom was never passed, the note is
                      dropped entirely.
  PSG voices 6-9      render_wave ignores the program completely on these voices
                      and always plays the same square. Every 0x0F on a PSG voice
                      is therefore a selection the renderer throws away.
  any voice           a voice carrying the sax-man marker (command 0x55) is muted
                      by default, and a note whose frequency lands outside
                      20 Hz .. 0.45*rate is skipped.

The output is a DROPPED list: every (voice, program) with notes in the module
that yields no sound or falls back to something else. That list is the direct
answer to "which instruments are missing".

It also audits the event stream itself for records the parser may be discarding
silently - occupancy masks, parameter-only records with byte0 = 0, grid indices
past the end of their event table, and every command byte with no known meaning,
by frequency and by voice. An unknown command that is common on a voice that
sounds wrong is a lead, not a conclusion.

BANK READING. scripts/wave_roots.load_bank() reads the decoded bank as 16-bit
and keeps the high byte of each sample, which is right for the s16 WAV ffmpeg
produces by default and WRONG for a u8 WAV - it silently returns every second
byte, inverted. The program table does not survive that. This script reads the
bank according to its own WAV header, then re-reads it the way the renderer does
and compares the two tables, because a bank the renderer cannot parse is by far
the largest way to lose instruments and it is invisible from the audio alone.

Derived from a commercial ROM: modules, bank and any CSV of measurements stay
local. This script does not.
"""

import argparse
import collections
import csv
import io
import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mwmm
import wave_roots

CLK = 99.8745
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Commands whose meaning is established. Everything else is reported as unknown.
KNOWN_CMDS = {
    0x0F: "program select",
    0xFA: "row period",
    0x02: "pan",
    0x55: "sax-man marker",
}
# Commands tested for volume and refuted (see the project notes). Still unknown,
# but knowing they are not volume is worth carrying into the report.
REFUTED_VOLUME = {0x01, 0x07, 0x08, 0x1A}

FM, PSG, WAVE = "FM", "PSG", "WAVE"


def vclass(v):
    return FM if v < 6 else (PSG if v < 10 else WAVE)


# --------------------------------------------------------------------- bank


def read_bank_native(path):
    """The bank as the bytes its own WAV header says it holds.

    u8 -> the frames are the bytes. s16 -> the cartridge's 8-bit data sits in
    the high byte (dump_wave.py: "the low byte of each 16-bit sample is zero").
    """
    w = wave.open(path)
    sw, ch, n = w.getsampwidth(), w.getnchannels(), w.getnframes()
    raw = w.readframes(n)
    w.close()
    if sw == 1:
        return np.frombuffer(raw, dtype=np.uint8).copy(), "u8 frames as bytes"
    if sw == 2:
        a = np.frombuffer(raw, dtype="<i2")
        if ch > 1:
            a = a[::ch]
        return ((((a >> 8) & 0xFF) ^ 0x80).astype(np.uint8)), "s16 high byte ^0x80"
    raise SystemExit("unsupported sample width %d in %s" % (sw, path))


def table_entries(b):
    """The 256 x 16-byte program table at offset 0, exactly as the bank stores it."""
    be32 = lambda o: int.from_bytes(b[o:o + 4].tobytes(), "big")
    be16 = lambda o: int.from_bytes(b[o:o + 2].tobytes(), "big")
    out = {}
    for p in range(256):
        out[p] = dict(ptr=be32(p * 16), len=be32(p * 16 + 4),
                      loop=be32(p * 16 + 8), type=be16(p * 16 + 12),
                      tail=be16(p * 16 + 14))
    return out


def table_score(b):
    """How well a byte stream parses as the program table.

    A real table has entries that are either empty or wholly inside the file,
    never start inside the 4096-byte table itself, and carry a type in the small
    range the rate lookup accepts. Garbage scores near zero on all three.
    """
    t = table_entries(b)
    n = len(b)
    coherent = sum(1 for e in t.values()
                   if e["len"] and 0x1000 <= e["ptr"] and e["ptr"] + e["len"] <= n)
    empty = sum(1 for e in t.values() if e["len"] == 0)
    typ_ok = sum(1 for e in t.values() if e["len"] and e["type"] < len(wave_roots.RATES))
    live = sum(1 for e in t.values() if e["len"] and e["ptr"] < n)
    return dict(coherent=coherent, empty=empty, type_ok=typ_ok, live=live,
                total_nonempty=256 - empty)


def program_table(b, conf=0.5, measure=True):
    """program -> facts the renderer needs, plus the ones that say if it will sound."""
    t = table_entries(b)
    n = len(b)
    out = {}
    for p, e in t.items():
        ln, ptr = e["len"], e["ptr"]
        if not ln:
            continue
        ridx = e["type"] + 1 if e["type"] + 1 < len(wave_roots.RATES) else 1
        sr = 48000 // wave_roots.RATES[ridx]
        inside = ptr < n
        sig = b[ptr:ptr + ln] if inside else np.zeros(0, np.uint8)
        got = len(sig)
        if got:
            x = sig.astype(np.int16) - 128
            peak = int(np.abs(x).max())
            rms = float(np.sqrt((x.astype(np.float64) ** 2).mean()))
        else:
            peak, rms = 0, 0.0
        root = conf_v = None
        if measure and got >= 2048:
            r = wave_roots.pitch(sig[:200000], sr)
            if r and r[1] >= conf and r[0] > 0:
                root = 69 + 12 * float(np.log2(r[0] / 440.0))
                conf_v = r[1]
            elif r:
                conf_v = r[1]
        out[p] = dict(ptr=ptr, len=ln, got=got, inside=inside, rate=sr,
                      type=e["type"], loop=(e["loop"] if e["loop"] != 0xFFFFFFFF
                                            and e["loop"] < ln else None),
                      peak=peak, rms=rms, secs=got / float(sr) if sr else 0.0,
                      root=root, conf=conf_v)
    return out


# --------------------------------------------------------------- FM material


def load_timbres_meta(path, grades=("A", "B", "C")):
    """{patch: grade} for every row, and the subset render_wave would actually use.

    render_wave.load_timbres keeps grades A/B/C and needs a non-zero harmonic
    profile, so a row outside that set is a silent fallback to the 4-op model.
    """
    all_rows, usable = {}, set()
    if not path or not os.path.exists(path):
        return all_rows, usable, 0
    n = 0
    for r in csv.DictReader(io.open(path, encoding="utf-8")):
        n += 1
        try:
            p = int(r["patch"], 16)
        except (KeyError, ValueError):
            continue
        g = (r.get("grade") or "").strip()
        all_rows[p] = g
        if g not in grades:
            continue
        h = [float(r[k]) for k in ("h%d_norm" % i for i in range(1, 40)) if k in r]
        if h and max(h) > 0:
            usable.add(p)
    return all_rows, usable, n


def load_fm_bank(rom):
    if not rom:
        return None
    import fm_patches
    t = fm_patches.load(rom)
    return {p: fm_patches.decode(t[p]) for p in range(len(t))}


# ------------------------------------------------------------------- walking


def walk(m, passes=0):
    """Every event of a module with its time, voice and live program state.

    Mirrors render_wave.render(): the program starts from array B read with the
    byte-swap `d[0x2A + (v ^ 1)]`, command 0x0F replaces it, 0x02 sets pan, and
    the row period is `2*d[0x07] + (0xFA operand & 0x0F)` ticks of 99.8745 Hz.
    Returns (events, seconds) where each event is a dict.

    render_wave applies 0xFA from a 26-event lookback rather than from the row
    it sits on; this applies it in place, as scripts/voice_notes.py does. The two
    agree except where a tempo change and a dense row coincide, and it changes
    only times, never which program a note lands on.
    """
    h09, base = m.d[0x09], 2 * m.d[0x07]
    seq = list(range(m.npos)) + [p for _ in range(passes) for p in range(h09, m.npos)]
    prog = {v: (m.d[0x2A + (v ^ 1)] or None) for v in range(26)}
    initial = dict(prog)
    pan = {v: 0x80 for v in range(26)}
    orders = [m.voice_order(v) for v in range(26)]
    evs, t, T = [], 0.0, base
    oob = 0
    seen_0F = set()
    for p in seq:
        for r in range(m.G):
            for v in range(26):
                order = orders[v]
                if p >= len(order):
                    continue
                g, ev = m.pat[order[p]]
                i = g[r] if r < len(g) else 0
                if not i:
                    continue
                if i >= len(ev):
                    oob += 1
                    continue
                e = ev[i]
                for k in (2, 4, 6):
                    if e[k] == 0x0F:
                        prog[v] = e[k + 1]
                        seen_0F.add(v)
                    elif e[k] == 0x02:
                        pan[v] = e[k + 1]
                    elif e[k] == 0xFA:
                        T = base + (e[k + 1] & 0x0F)
                evs.append(dict(t=t, v=v, e=bytes(e), prog=prog[v], pan=pan[v],
                                pos=p, row=r, seen_0F=(v in seen_0F)))
            t += T / CLK
    # a note lasts until the voice's next note or gate release (render_wave's
    # second pass); parameter-only records must not cut it short
    nxt = {}
    for i in range(len(evs) - 1, -1, -1):
        d = evs[i]
        d["end"] = nxt.get(d["v"], t + 2.0)
        b0 = d["e"][0]
        if (1 <= b0 <= 12) or b0 == 0x0E:
            nxt[d["v"]] = d["t"]
    return evs, t, initial, oob


# ------------------------------------------------------------------- verdict

SILENT = "SILENT"
FALLBACK = "FALLBACK"
OK = "OK"
MUTED = "MUTED"
IGNORED = "IGNORED"


def audit_track(m, progs, fm_bank, timbres_usable, timbres_all, anchor, rate,
                passes=0, has_rom=True):
    """Per (voice, program) verdicts for one module, plus event-stream stats."""
    import render_wave
    evs, total_s, initial, oob = walk(m, passes)
    muted = render_wave.sax_voices(m)

    rows = {}
    for d in evs:
        e, v = d["e"], d["v"]
        if not (1 <= e[0] <= 12):
            continue
        key = (v, d["prog"])
        r = rows.setdefault(key, dict(v=v, prog=d["prog"], cls=vclass(v), n=0,
                                      t0=d["t"], t1=d["t"], semis=[],
                                      drop_freq=0, drop_step=0, base_rate=0,
                                      transposed=0, before_first_0F=0))
        r["n"] += 1
        if not d["seen_0F"]:
            r["before_first_0F"] += 1
        r["t1"] = max(r["t1"], d["t"])
        r["t0"] = min(r["t0"], d["t"])
        target = 12 * e[1] + e[0] + anchor
        r["semis"].append(target)
        f = 440.0 * 2.0 ** ((target - 69) / 12.0)
        if f < 20 or f > rate * 0.45:
            r["drop_freq"] += 1
            continue
        if d["prog"] is None and initial[v] is None:
            r["before_first_0F"] += 1
        if r["cls"] == WAVE:
            ent = progs.get(d["prog"])
            if ent is None or not ent["inside"] or ent["got"] < 32:
                continue
            root = ent["root"]
            if root is None or abs(target - root) > 24:
                r["base_rate"] += 1
                step = ent["rate"] / float(rate)
            else:
                step = (ent["rate"] / float(rate)) * 2.0 ** ((target - root) / 12.0)
                r["transposed"] += 1
            if not np.isfinite(step) or step <= 0 or step > 40:
                r["drop_step"] += 1

    for key, r in rows.items():
        v, p = key
        r["lo"], r["hi"] = min(r["semis"]), max(r["semis"])
        r["nsemi"] = len(set(r["semis"]))
        r["median"] = float(np.median(r["semis"]))
        r["octaves"], r["residual"] = octave_check(r, progs)
        r["verdict"], r["why"] = classify(v, p, r, progs, fm_bank, timbres_usable,
                                          timbres_all, muted, has_rom)
        del r["semis"]

    return rows, evs, total_s, muted, oob, initial


def octave_check(r, progs):
    """Is a too-far root an OCTAVE error, or genuinely unrelated to the music?

    render_wave refuses to transpose a sample more than two octaves from its
    measured root and plays it at its own base rate instead - right for a drum,
    wrong for an instrument whose root was measured an octave or three out.
    Those two cases look identical in the fallback count and are not the same
    bug, so separate them: take the median note the music writes for the
    program, subtract the measured root, and split the difference into whole
    octaves plus a remainder.

    A remainder near zero means the root is the written pitch to within a
    semitone or two and only the octave is wrong - wave_roots picking a partial
    or a subharmonic. A large remainder means the sample's pitch has nothing to
    do with the written note, which is what percussion looks like.

    Returns (octaves, remainder in semitones), or (None, None) with no root.
    """
    if r["cls"] != WAVE:
        return None, None
    ent = progs.get(r["prog"])
    if ent is None or ent.get("root") is None:
        return None, None
    d = r["median"] - ent["root"]
    k = int(round(d / 12.0))
    return k, float(d - 12 * k)


def classify(v, p, r, progs, fm_bank, timbres_usable, timbres_all, muted, has_rom):
    cls = vclass(v)
    if v in muted:
        return MUTED, "voice carries the 0x55 sax marker; muted unless --sax"
    if cls == PSG:
        if p is None:
            return OK, "PSG square (renderer ignores the program on 6-9)"
        return IGNORED, ("program 0x%02X selected but render_wave ignores the "
                         "program on PSG voices" % p)
    if cls == FM:
        pn = p if p is not None else 0
        note = "" if p is not None else "no 0x0F ever; renderer defaults to patch 0x00. "
        if pn in timbres_usable:
            return OK, note + "measured timbre, grade %s" % timbres_all.get(pn, "?")
        g = timbres_all.get(pn)
        if not has_rom:
            return SILENT, note + ("no --rom and no usable timbre for 0x%02X: "
                                   "render_wave drops every note" % pn)
        if fm_bank is not None and pn not in fm_bank:
            return SILENT, note + ("patch 0x%02X is past the %d-record ROM bank and "
                                   "has no timbre: notes dropped"
                                   % (pn, len(fm_bank)))
        if g:
            return FALLBACK, note + ("timbre row exists but grade %s is outside "
                                     "A/B/C: falls back to the modelled 4-op synth" % g)
        return FALLBACK, note + ("no measured timbre for patch 0x%02X: falls back to "
                                 "the modelled 4-op synth" % pn)
    # wave
    if p is None:
        return SILENT, ("no program ever selected on this voice and array B is "
                        "zero: progs.get(None) misses and every note is dropped")
    ent = progs.get(p)
    if ent is None:
        return SILENT, ("program 0x%02X has length 0 in the wave table: "
                        "render_wave drops every note" % p)
    if not ent["inside"]:
        return SILENT, ("program 0x%02X points to 0x%X, past the end of the bank: "
                        "dropped" % (p, ent["ptr"]))
    if ent["got"] < 32:
        return SILENT, "program 0x%02X resolves to %d bytes: too short to play" % (p, ent["got"])
    if ent["peak"] <= 2:
        return SILENT, ("program 0x%02X is %d bytes of silence (peak %d LSB)"
                        % (p, ent["got"], ent["peak"]))
    if r["drop_step"]:
        return FALLBACK, "%d of %d notes need a resample step past 40x and are dropped" % (
            r["drop_step"], r["n"])
    if ent["root"] is None:
        return FALLBACK, ("no measurable root for 0x%02X (conf %s): every note plays "
                          "at the sample's %d Hz base rate"
                          % (p, "%.2f" % ent["conf"] if ent["conf"] else "-", ent["rate"]))
    if r["base_rate"]:
        how = ("%d of %d notes are" % (r["base_rate"], r["n"])
               if r["transposed"] else "every note is")
        tag = octave_tag(r)
        return FALLBACK, ("%s more than 2 octaves from the measured root %.1f (%s) "
                          "and play%s untransposed%s"
                          % (how, ent["root"], midi_name(ent["root"]),
                             "" if r["transposed"] else "s", tag))
    if r["drop_freq"]:
        return FALLBACK, "%d of %d notes fall outside 20 Hz..Nyquist and are dropped" % (
            r["drop_freq"], r["n"])
    return OK, "sample %d bytes @ %d Hz, root %s" % (
        ent["got"], ent["rate"], midi_name(ent["root"]))


def cross_check(m, evs):
    """walk() against scripts/voice_notes.timeline(), the reference clock.

    Both must agree on (time, voice, program, byte0, byte1) for every note, or
    this audit is measuring a different song from the one that gets rendered.
    """
    import voice_notes
    ref, _ = voice_notes.timeline(m, set(range(26)), 0)
    ref = [(round(t, 4), v, p, b0, b1) for t, v, p, b0, b1 in ref]
    mine = [(round(d["t"], 4), d["v"], d["prog"], d["e"][0], d["e"][1])
            for d in evs if 1 <= d["e"][0] <= 12]
    bad = sum(1 for x, y in zip(ref, mine) if x != y) + abs(len(ref) - len(mine))
    return len(ref), bad


def octave_tag(r):
    """The human half of octave_check(), for a fallback line."""
    k, res = r.get("octaves"), r.get("residual")
    if k is None:
        return ""
    if abs(res) <= 2.0:
        return ("  <- ROOT IS %+d OCTAVES OUT (remainder %+.1f semitones): shifting it "
                "puts the music back in range" % (k, res))
    return ("  <- root is %+d octaves %+.1f semitones from the written notes: "
            "unrelated pitch, consistent with percussion" % (k, res))


def midi_name(m):
    i = int(round(m))
    return "%s%d" % (NAMES[i % 12], i // 12 - 1)


# -------------------------------------------------------------- event stream


def event_stats(m):
    """Occupancy masks, byte0 census and command census for one module."""
    s = dict(events=0, oob=0, notes=0, release=0, paramonly=0, weird_b0=0,
             mask=collections.Counter(), b0=collections.Counter(),
             cmd=collections.Counter(), cmd_by_voice=collections.defaultdict(
                 collections.Counter), after_zero=collections.Counter(),
             short_grid=0, patterns=0)
    for off, (g, ev) in m.pat.items():
        s["patterns"] += 1
        if len(g) < m.G:
            s["short_grid"] += 1
    for v in range(26):
        for off in m.voice_order(v):
            g, ev = m.pat[off]
            for r in range(m.G):
                i = g[r] if r < len(g) else 0
                if not i:
                    continue
                if i >= len(ev):
                    s["oob"] += 1
                    continue
                e = ev[i]
                s["events"] += 1
                s["b0"][e[0]] += 1
                if 1 <= e[0] <= 12:
                    s["notes"] += 1
                elif e[0] == 0x0E:
                    s["release"] += 1
                elif e[0] == 0:
                    s["paramonly"] += 1
                else:
                    s["weird_b0"] += 1
                mask = 0
                for k, bit in ((0, 1), (2, 2), (4, 4), (6, 8)):
                    if e[k] or e[k + 1]:
                        mask |= bit
                s["mask"][mask] += 1
                zero = False
                for k in (2, 4, 6):
                    if not e[k] and not e[k + 1]:
                        zero = True
                        continue
                    if e[k]:
                        s["cmd"][e[k]] += 1
                        s["cmd_by_voice"][v][e[k]] += 1
                    if zero:
                        s["after_zero"][e[k]] += 1
    return s


# ---------------------------------------------------------------- reporting


def hr(c="-", n=78):
    return c * n


def pfmt(p):
    return "--" if p is None else "0x%02X" % p


def report_bank(path, b, how, alt, alt_how, progs):
    print(hr("="))
    print("WAVE BANK  %s" % path)
    print(hr("="))
    sc = table_score(b)
    print("  read as %-22s %d bytes" % (how, len(b)))
    print("    program table at offset 0: %d entries with a length, %d empty, "
          "%d wholly inside the file" % (sc["total_nonempty"], sc["empty"], sc["coherent"]))
    if alt is not None:
        sa = table_score(alt)
        print("  render_wave reads it via wave_roots.load_bank() -> %s, %d bytes"
              % (alt_how, len(alt)))
        print("    program table at offset 0: %d entries with a length, %d empty, "
              "%d wholly inside the file" % (sa["total_nonempty"], sa["empty"],
                                             sa["coherent"]))
        if sa["coherent"] < sc["coherent"]:
            print()
            print("  ** BANK READ MISMATCH **")
            print("     The renderer's reader does not parse this bank. Under its read")
            print("     only %d program entries even point inside the file (%s), against"
                  % (sa["live"], ", ".join(pfmt(p) for p in sorted(
                      p for p in range(256)
                      if table_entries(alt)[p]["len"]
                      and table_entries(alt)[p]["ptr"] < len(alt)))))
            print("     %d under the header-correct read. Every wave voice whose program"
                  % sc["live"])
            print("     is not in that short list is dropped in silence.")
    live = len(progs)
    silent = sum(1 for e in progs.values() if e["inside"] and e["got"] >= 32 and e["peak"] <= 2)
    outside = sum(1 for e in progs.values() if not e["inside"])
    rooted = sum(1 for e in progs.values() if e["root"] is not None)
    print()
    print("  %d programs carry a sample: %d pointer outside the file, %d silent, "
          "%d with a measurable root" % (live, outside, silent, rooted))
    print()


def report_track(m, rows, evs, total_s, muted, oob, initial, progs, args):
    print(hr("="))
    print("TRACK %d  %s   (%s)" % (m.n, m.title, m.composer))
    print(hr("="))
    voices = sorted({r["v"] for r in rows.values()})
    notes = sum(r["n"] for r in rows.values())
    print("  %d positions of %d rows, %d events, %d notes on %d voices, %.1f s per pass"
          % (m.npos, m.G, len(evs), notes, len(voices), total_s))
    if muted:
        print("  sax-man voices muted by default: %s" % sorted(muted))
    if oob:
        print("  grid indices past the end of their event table: %d" % oob)
    pre = sum(r["before_first_0F"] for r in rows.values())
    if pre:
        vs = sorted({r["v"] for r in rows.values() if r["before_first_0F"]})
        print("  %d notes on voices %s play BEFORE their voice's first 0x0F, on whatever "
              "array B supplies" % (pre, vs))
        print("  array B is read as d[0x2A + (v^1)] - a byte-swap. Here it is %s."
              % ("all zero, so those notes have no program at all"
                 if not any(m.d[0x2A:0x44]) else "non-zero, so the swap decides them"))
    print()
    print("  %-4s %-5s %-6s %6s %8s %8s %7s  %-9s %s"
          % ("v", "class", "prog", "notes", "first s", "last s", "semis", "verdict", "detail"))
    for key in sorted(rows, key=lambda k: (k[0], -rows[k]["n"])):
        r = rows[key]
        print("  v%02d  %-5s %-6s %6d %8.1f %8.1f %3d-%-3d  %-9s %s"
              % (r["v"], r["cls"], pfmt(r["prog"]), r["n"], r["t0"], r["t1"],
                 r["lo"], r["hi"], r["verdict"], r["why"]))
    print()

    dropped = [r for r in rows.values() if r["verdict"] != OK]
    lost = sum(r["n"] for r in rows.values() if r["verdict"] in (SILENT, MUTED))
    fell = sum(r["n"] for r in rows.values() if r["verdict"] == FALLBACK)
    ign = sum(r["n"] for r in rows.values() if r["verdict"] == IGNORED)
    print(hr())
    print("  DROPPED LIST - track %d: %d of %d note-events do not sound as written"
          % (m.n, lost + fell + ign, notes))
    print("  (%d silent or muted, %d falling back to something else, %d selecting a "
          "program the renderer ignores)" % (lost, fell, ign))
    print(hr())
    if not dropped:
        print("  nothing: every (voice, program) pair sounds as written.")
    for r in sorted(dropped, key=lambda x: (x["verdict"] != SILENT, -x["n"])):
        print("   %-8s v%02d %-5s %-6s %5d notes  %6.1f-%6.1f s   %s"
              % (r["verdict"], r["v"], r["cls"], pfmt(r["prog"]), r["n"],
                 r["t0"], r["t1"], r["why"]))
    by_cls = collections.Counter()
    for r in rows.values():
        if r["verdict"] in (SILENT, MUTED):
            by_cls[r["cls"]] += r["n"]
    tot_cls = collections.Counter()
    for r in rows.values():
        tot_cls[r["cls"]] += r["n"]
    print()
    for c in (FM, PSG, WAVE):
        if tot_cls[c]:
            print("   %-5s %5d notes, %5d silent (%.0f%%)"
                  % (c, tot_cls[c], by_cls[c], 100.0 * by_cls[c] / tot_cls[c]))
    print()


def report_events(m, s, args):
    print(hr())
    print("  EVENT STREAM - track %d" % m.n)
    print(hr())
    print("   %d events in %d patterns; %d notes, %d gate releases (0x0E), "
          "%d parameter-only (byte0 = 0), %d byte0 with no meaning"
          % (s["events"], s["patterns"], s["notes"], s["release"],
             s["paramonly"], s["weird_b0"]))
    print("   grid indices past the event table: %d ; patterns shorter than G: %d"
          % (s["oob"], s["short_grid"]))
    print("   occupancy (which of the four words are non-zero):")
    lab = {1: "note only", 3: "note + cmd1", 7: "note + cmd1,2", 15: "note + cmd1,2,3",
           2: "cmd1 only, NO note", 6: "cmd1,2 only, NO note",
           14: "cmd1,2,3 only, NO note", 0: "wholly empty"}
    for mk, n in sorted(s["mask"].items(), key=lambda x: -x[1]):
        print("      mask %2d  %-22s %6d  %5.1f%%"
              % (mk, lab.get(mk, "irregular"), n, 100.0 * n / max(s["events"], 1)))
    odd = {mk: n for mk, n in s["mask"].items() if mk not in lab}
    if odd:
        print("      ** irregular masks (a gap between command words): %s" % odd)
    if s["after_zero"]:
        print("      ** %d commands sit AFTER a zero word. The format is described as "
              "zero-terminated, so a strict player stops there while render_wave "
              "reads all three slots: %s"
              % (sum(s["after_zero"].values()),
                 ", ".join("0x%02X x%d" % (c, n) for c, n in s["after_zero"].most_common(8))))
    else:
        print("      zero-termination holds: no command word follows a zero word.")
    print("   commands:")
    for c, n in s["cmd"].most_common(40):
        who = KNOWN_CMDS.get(c)
        tag = who if who else ("UNKNOWN (refuted as volume)" if c in REFUTED_VOLUME
                               else "UNKNOWN")
        vs = sorted(v for v in s["cmd_by_voice"] if s["cmd_by_voice"][v][c])
        cls = "".join(sorted({vclass(v)[0] for v in vs}))
        print("      0x%02X x%-6d %-28s voices %-28s %s"
              % (c, n, tag, ",".join(str(v) for v in vs[:12]) + ("..." if len(vs) > 12 else ""), cls))
    print()


def report_corpus(allrows, allstats, nmods):
    print(hr("="))
    print("CORPUS - %d modules" % nmods)
    print(hr("="))
    tot = collections.Counter()
    notes = collections.Counter()
    for (tn, v, p), r in allrows.items():
        tot[(r["cls"], r["verdict"])] += 1
        notes[(r["cls"], r["verdict"])] += r["n"]
    print("  %-6s %-9s %8s %10s" % ("class", "verdict", "pairs", "notes"))
    for c in (FM, PSG, WAVE):
        for vd in (OK, FALLBACK, SILENT, MUTED, IGNORED):
            if tot[(c, vd)]:
                print("  %-6s %-9s %8d %10d" % (c, vd, tot[(c, vd)], notes[(c, vd)]))
    allnotes = sum(notes.values())
    bad = sum(n for (c, vd), n in notes.items() if vd in (SILENT, MUTED))
    fb = sum(n for (c, vd), n in notes.items() if vd == FALLBACK)
    print("  %d note-events total: %d silent (%.1f%%), %d falling back (%.1f%%)"
          % (allnotes, bad, 100.0 * bad / max(allnotes, 1), fb, 100.0 * fb / max(allnotes, 1)))

    print()
    print("  worst silent (voice, program) pairs corpus-wide:")
    agg = collections.Counter()
    why = {}
    for (tn, v, p), r in allrows.items():
        if r["verdict"] in (SILENT,):
            agg[(r["cls"], p)] += r["n"]
            why[(r["cls"], p)] = r["why"]
    for (c, p), n in agg.most_common(15):
        print("     %-5s %-6s %6d notes   %s" % (c, pfmt(p), n, why[(c, p)]))

    print()
    print("  commands corpus-wide:")
    cmd = collections.Counter()
    cmd_cls = collections.defaultdict(collections.Counter)
    ev = 0
    for tn, s in allstats.items():
        ev += s["events"]
        for c, n in s["cmd"].items():
            cmd[c] += n
        for v, cc in s["cmd_by_voice"].items():
            for c, n in cc.items():
                cmd_cls[c][vclass(v)] += n
    print("   %d events across the corpus" % ev)
    for c, n in cmd.most_common(50):
        tag = KNOWN_CMDS.get(c) or ("UNKNOWN (refuted as volume)" if c in REFUTED_VOLUME
                                    else "UNKNOWN")
        spread = " ".join("%s:%d" % (k, cmd_cls[c][k]) for k in (FM, PSG, WAVE)
                          if cmd_cls[c][k])
        print("      0x%02X x%-7d %-28s %s" % (c, n, tag, spread))
    print()


# -------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("moduledir")
    ap.add_argument("bank")
    ap.add_argument("--rom", default=None, help="paprium.md, for the 135-patch FM bank")
    ap.add_argument("--timbres", default=None, help="fm_timbre.csv as passed to render_wave")
    ap.add_argument("--tracks", default="30,57", help="tracks to report in full")
    ap.add_argument("--corpus", action="store_true", help="also audit all 52 modules")
    ap.add_argument("--anchor", type=int, default=11)
    ap.add_argument("--rate", type=int, default=32000)
    ap.add_argument("--passes", type=int, default=0, help="extra loop passes to walk")
    ap.add_argument("--conf", type=float, default=0.5, help="root-pitch confidence floor")
    ap.add_argument("--as-renderer", action="store_true",
                    help="read the bank the way render_wave does, even if its own WAV "
                         "header says otherwise - shows what the player is hearing")
    ap.add_argument("--csv", default=None, help="write every (track, voice, program) row")
    a = ap.parse_args()

    native, how = read_bank_native(a.bank)
    rend = wave_roots.load_bank(a.bank)
    same = len(rend) == len(native) and bool((rend == native).all())
    b = rend if a.as_renderer else native
    used_how = ("s16 high byte ^0x80 (render_wave's reader)" if a.as_renderer else how)

    progs = program_table(b, a.conf)
    report_bank(a.bank, b, used_how,
                None if (same or a.as_renderer) else rend,
                "s16 high byte ^0x80", progs)
    if not same and not a.as_renderer:
        print("  Re-run with --as-renderer to audit what render_wave actually plays.")
        print()
    if not same and a.as_renderer:
        print("  Auditing the RENDERER'S read of a bank whose own header says u8.")
        print("  This is what the player is hearing, not what the cartridge holds.")
        print()

    timbres_all, timbres_usable, nrows = load_timbres_meta(a.timbres)
    if a.timbres:
        print("FM timbres: %s - %d rows, %d usable at grade A/B/C"
              % (a.timbres, nrows, len(timbres_usable)))
    else:
        print("FM timbres: none given; every FM patch falls back to the modelled synth.")
    fm_bank = load_fm_bank(a.rom)
    print("FM patch bank: %s" % ("%d records from %s" % (len(fm_bank), a.rom)
                                 if fm_bank else "none given (--rom unset)"))
    print()

    mods = {m.n: m for m in mwmm.load_all(a.moduledir)}
    focus = [int(x) for x in a.tracks.split(",") if x.strip()]
    todo = sorted(mods) if a.corpus else focus

    allrows, allstats = {}, {}
    checked = mismatch = notes_checked = 0
    for tn in todo:
        m = mods[tn]
        rows, evs, total_s, muted, oob, initial = audit_track(
            m, progs, fm_bank, timbres_usable, timbres_all, a.anchor, a.rate,
            a.passes, has_rom=fm_bank is not None)
        if a.passes == 0:
            n, bad = cross_check(m, evs)
            checked += 1
            notes_checked += n
            mismatch += bad
        s = event_stats(m)
        allstats[tn] = s
        for k, r in rows.items():
            allrows[(tn, k[0], k[1])] = r
        if tn in focus:
            report_track(m, rows, evs, total_s, muted, oob, initial, progs, a)
            report_events(m, s, a)

    if checked:
        print("SELF-TEST  %d modules, %d notes cross-checked against "
              "voice_notes.timeline(): %d disagreements on (time, voice, program, "
              "byte0, byte1)%s" % (checked, notes_checked, mismatch,
                                   "" if not mismatch else "  ** FAILED **"))
        print()

    if a.corpus:
        report_corpus(allrows, allstats, len(todo))

    if a.csv:
        with io.open(a.csv, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["track", "title", "voice", "class", "program", "notes",
                        "first_s", "last_s", "semi_lo", "semi_hi", "distinct_semis",
                        "verdict", "base_rate_notes", "transposed_notes",
                        "dropped_freq", "dropped_step", "detail"])
            for (tn, v, p), r in sorted(allrows.items(),
                                        key=lambda kv: (kv[0][0], kv[0][1],
                                                        -1 if kv[0][2] is None else kv[0][2])):
                w.writerow([tn, mods[tn].title, v, r["cls"], pfmt(p), r["n"],
                            "%.2f" % r["t0"], "%.2f" % r["t1"], r["lo"], r["hi"],
                            r["nsemi"], r["verdict"], r["base_rate"], r["transposed"],
                            r["drop_freq"], r["drop_step"], r["why"]])
        print("wrote %s (%d rows)" % (a.csv, len(allrows)))


if __name__ == "__main__":
    main()
