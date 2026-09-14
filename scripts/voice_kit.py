#!/usr/bin/env python3
"""Build a per-voice listening kit: every voice of a track alone, plus the
hardware capture cut to the moment that voice is most exposed.

    python scripts/voice_kit.py <moduledir> <track> <bank> <outdir>
           [--seconds 90] [--timbres CSV] [--rom paprium.md] [--sax]
           [--capture X.mkv] [--vu X.npz] [--audio-lag S] [--vu-lag S]
           [--vu-gain JSON] [--raw-roots] [--windows N]

Why this exists: a 26-voice mix cannot be argued about from the full mix. Three
whole-track tests once said the sax man was absent from a capture he was playing
all over, because three voices out of twenty-six do not move a whole-track
average. The only honest way to make a claim about one voice is to hear it alone,
and to look at the hardware in the moment that voice is most exposed.

The hardware cannot supply a true solo. The Boom Box level meter shows how many
voices are lit at once, and across four decoded tracks - 54,748 frames - there is
no run of 150 ms anywhere with a single voice above the floor; at most nine
isolated frames in a whole song. So the renderer's solos are the ground truth for
what one voice is doing, and the capture can only be cut to where that voice
dominates the meter.

Finding that moment is what --vu does: per voice, the windows where its meter
level is the largest share of everything lit. Two different offsets are involved
and they are NOT the same number - the meter is a video overlay and lags its own
audio by 165 to 229 ms - so --vu-lag maps meter time to module time and
--audio-lag maps module time to capture audio time.

Derived from a commercial ROM: keep the output local.
"""

import argparse
import collections
import json
import os
import subprocess
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mwmm
import render_wave as RW
from wave_roots import load_bank

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
GROUPS = [("FM", range(0, 6)), ("PSG", range(6, 10)), ("wave", range(10, 26))]


def note_name(midi):
    return "%s%d" % (NAMES[int(round(midi)) % 12], int(round(midi)) // 12 - 1)


def write_wav(path, buf, rate):
    peak = np.abs(buf).max()
    if peak > 0:
        buf = buf / peak * 0.89
    w = wave.open(path, "wb")
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes((buf.reshape(-1) * 32767).astype("<i2").tobytes())
    w.close()


def voice_parts(m):
    """{voice: (note count, Counter of programs, [MIDI notes])}.

    Programs are tracked exactly the way render() tracks them - the static byte
    at +0x2A as the initial value, then command 0x0F wherever it appears.
    """
    out = {}
    for v in range(26):
        prog = m.d[0x2A + (v ^ 1)] or None
        progs, notes = collections.Counter(), []
        for _, ev in m.timeline(v):
            for k in (2, 4, 6):
                if ev[k] == 0x0F:
                    prog = ev[k + 1]
            if ev[0] and ev[0] != 0x0E and prog is not None:
                progs[prog] += 1
                notes.append(12 * ev[1] + ev[0] + 11)
        if notes:
            out[v] = (len(notes), progs, notes)
    return out


def exposed_windows(npz, voice, n, width, vu_lag):
    """[(module time, share of the lit meter)] where this voice dominates."""
    d = np.load(npz)
    q = int(d["quantum"]) or 9
    lv = np.maximum(d["heights"].astype(int) // q - 1, 0)[d["valid"], :26]
    t = d["t"][d["valid"]]
    tot = lv.sum(1).astype(float)
    share = np.where(tot > 0, lv[:, voice] / np.maximum(tot, 1e-9), 0.0)
    fps = float(d["fps"]) or 60.0
    w = max(int(width * fps), 1)
    if len(share) < w:
        return []
    run = np.convolve(share, np.ones(w) / w, mode="valid")
    out, taken = [], np.zeros(len(run), bool)
    for _ in range(n):
        masked = np.where(taken, -1.0, run)
        i = int(np.argmax(masked))
        if masked[i] <= 0:
            break
        out.append((float(t[i]) - vu_lag, float(run[i])))
        taken[max(0, i - w):i + w] = True
    return out


def cut(capture, t0, dur, path, rate):
    subprocess.run(["ffmpeg", "-v", "error", "-ss", "%.3f" % max(t0, 0.0),
                    "-t", "%.3f" % dur, "-i", capture, "-ac", "2",
                    "-ar", str(rate), "-y", path], check=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("moduledir")
    ap.add_argument("track", type=int)
    ap.add_argument("bank")
    ap.add_argument("outdir")
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--rate", type=int, default=32000)
    ap.add_argument("--anchor", type=int, default=11)
    ap.add_argument("--timbres")
    ap.add_argument("--rom")
    ap.add_argument("--sax", action="store_true")
    ap.add_argument("--raw-roots", action="store_true")
    ap.add_argument("--vu-gain")
    ap.add_argument("--capture")
    ap.add_argument("--vu")
    ap.add_argument("--audio-lag", type=float, default=0.0)
    ap.add_argument("--vu-lag", type=float, default=0.0)
    ap.add_argument("--windows", type=int, default=2)
    ap.add_argument("--window-width", type=float, default=4.0)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    mods = {m.n: m for m in mwmm.load_all(a.moduledir)}
    m = mods[a.track]
    b = load_bank(a.bank)
    progs = RW.program_table(b, moddir=None if a.raw_roots else a.moduledir)
    live = sum(1 for v in progs.values() if len(v[0]) >= 32)
    if live < 90:
        ap.error("%s yields only %d live programs (expected ~94)" % (a.bank, live))

    fm = {}
    if a.rom:
        import fm_patches
        t = fm_patches.load(a.rom)
        fm = {p: fm_patches.decode(t[p]) for p in range(len(t))}
    timbres = RW.load_timbres(a.timbres) if a.timbres else None
    vgain = ({int(k): float(v) for k, v in json.load(open(a.vu_gain)).items()}
             if a.vu_gain else None)

    def make(name, only):
        buf, placed = RW.render(m, progs, a.anchor, a.seconds, a.rate, only=only,
                                fm=fm, timbres=timbres, vgain=vgain, sax=a.sax)
        write_wav(os.path.join(a.outdir, name), buf, a.rate)
        return placed

    parts = voice_parts(m)
    index = []
    print("track %d %s -> %s" % (a.track, m.title, a.outdir))

    make("00_full.wav", None)
    index.append(("00_full.wav", "all 26 voices", "", ""))
    for gname, rng in GROUPS:
        vs = set(rng) & set(parts)
        if not vs:
            continue
        n = make("01_group_%s.wav" % gname, vs)
        index.append(("01_group_%s.wav" % gname,
                      "%s only (voices %s)" % (gname, ",".join(str(x) for x in sorted(vs))),
                      "%d notes" % n, ""))

    for v in sorted(parts):
        nn, pc, notes = parts[v]
        top = pc.most_common(1)[0][0]
        klass = "FM" if v < 6 else ("PSG" if v < 10 else "wave")
        fn = "v%02d_%s_prog%02X.wav" % (v, klass, top)
        placed = make(fn, {v})
        desc = ("%s voice %d, prog 0x%02X, %d notes, %s..%s"
                % (klass, v, top, nn, note_name(min(notes)), note_name(max(notes))))
        tags = []
        if a.vu and a.capture:
            for mt, sh in exposed_windows(a.vu, v, a.windows, a.window_width, a.vu_lag):
                if mt < 0 or mt > a.seconds:
                    continue
                cf = "v%02d_HW_%06.2fs.wav" % (v, mt)
                cut(a.capture, mt + a.audio_lag, a.window_width,
                    os.path.join(a.outdir, cf), a.rate)
                tags.append("render %.2fs / capture %.2fs (%.0f%% of meter)"
                            % (mt, mt + a.audio_lag, sh * 100))
        index.append((fn, desc, "%d placed" % placed, "; ".join(tags)))
        print("  %-28s %s  %s" % (fn, desc, "; ".join(tags)))

    with open(os.path.join(a.outdir, "INDEX.txt"), "w") as f:
        f.write("%s - track %d - %.0f s window\n" % (m.title, a.track, a.seconds))
        f.write("Listen to the render file, then the capture at the timestamp given.\n")
        f.write("No true hardware solo exists - the capture clip is the moment that\n")
        f.write("voice owns the largest share of the on-screen level meter.\n\n")
        for row in index:
            f.write("%-30s %-52s %-12s %s\n" % row)
    print("wrote %s/INDEX.txt" % a.outdir)


if __name__ == "__main__":
    main()
