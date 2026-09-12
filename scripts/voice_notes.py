#!/usr/bin/env python3
"""Expected note timeline for chosen voices of an MWMM module, in SECONDS.

    python scripts/voice_notes.py <moduledir> <track> [--voices 23,24,25]
                                  [--passes 2] [--csv] [--anchor C]

This is the reference half of the per-program root-pitch measurement. The sax
layer lives on voices 23-25 (see docs/PORT_PLAN.md), and toggling it in the
boombox while recording isolates programs 0x55 and 0x94 by subtraction. This
script says what those voices are PLAYING and exactly when, so a measured
frequency can be matched to a known note.

Row timing uses the solved clock:

    T = 2 * header[+0x07] + (operand of command 0xFA & 0x0F)   ticks
    tick = 1 / 99.8745 s

applied per row, with 0xFA taking effect where it sits. Playback runs positions
0..npos-1, then repeats from header[+0x09].

Pitch is `12*byte1 + byte0 + C`. **C is not established** - that is the whole
point of the exercise - so --anchor lets a candidate be tried and prints the
frequency each note would then have. Measure one sustained sax note in the
isolated audio, find the C that puts it on the printed frequency, and check that
the same C explains the rest.

Note the synth is sample-based: a single global C may not exist, and each program
may carry its own root pitch. Solve per program, which is why the program (from
command 0x0F) is carried on every row of output.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mwmm

CLK = 99.8745
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def timeline(m, voices, passes):
    """[(t, voice, program, byte0, byte1)] plus the total duration."""
    h09, base = m.d[0x09], 2 * m.d[0x07]
    seq = list(range(m.npos)) + [p for _ in range(passes) for p in range(h09, m.npos)]
    prog = {v: None for v in range(26)}
    for v in range(26):                      # static array B, where it is set
        b = m.d[0x2A + ((v) ^ 1)] if (0x2A + (v ^ 1)) < 0x44 else 0
        prog[v] = b or None
    out, t, T = [], 0.0, base
    for p in seq:
        for r in range(m.G):
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
                        prog[v] = e[k + 1]
                if v in voices and 1 <= e[0] <= 12:
                    out.append((t, v, prog[v], e[0], e[1]))
            t += T / CLK
    return out, t


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("moduledir")
    ap.add_argument("track", type=int)
    ap.add_argument("--voices", default="23,24,25")
    ap.add_argument("--passes", type=int, default=2)
    ap.add_argument("--csv", action="store_true")
    ap.add_argument("--anchor", type=int, default=None,
                    help="candidate C in pitch = 12*byte1 + byte0 + C; prints Hz")
    a = ap.parse_args()

    voices = {int(v) for v in a.voices.split(",")}
    m = {x.n: x for x in mwmm.load_all(a.moduledir)}[a.track]
    rows, total = timeline(m, voices, a.passes)

    if a.csv:
        print("seconds,voice,program,byte0,byte1,semitone")
        for t, v, p, b0, b1 in rows:
            print("%.4f,%d,%s,%d,%d,%d" % (t, v, "" if p is None else p, b0, b1, 12 * b1 + b0))
        return

    print("track %d  %s   %d voices %s   %.1f s over %d passes"
          % (m.n, m.title, len(voices), sorted(voices), total, a.passes + 1))
    if a.anchor is not None:
        print("anchor C = %d, so frequency = 440 * 2^((12*b1 + b0 + C - 69)/12)" % a.anchor)
    print("\n%9s %4s %8s %4s %4s %9s %s"
          % ("seconds", "v", "program", "b0", "b1", "semitone", "note / Hz" if a.anchor is not None else "note"))
    for t, v, p, b0, b1 in rows[:60]:
        semi = 12 * b1 + b0
        if a.anchor is None:
            tail = "%s%d?" % (NAMES[(b0 - 1) % 12], b1)
        else:
            midi = semi + a.anchor
            tail = "%-4s %8.2f Hz" % (NAMES[midi % 12] + str(midi // 12 - 1),
                                      440.0 * 2.0 ** ((midi - 69) / 12.0))
        print("%9.3f %4d %8s %4d %4d %9d %s"
              % (t, v, "0x%02X" % p if p is not None else "--", b0, b1, semi, tail))
    if len(rows) > 60:
        print("... %d more (use --csv for all)" % (len(rows) - 60))

    print("\ndistinct (program, semitone) pairs, most common first:")
    import collections
    c = collections.Counter((p, 12 * b1 + b0) for _, _, p, b0, b1 in rows)
    for (p, s), n in c.most_common(12):
        print("   program %-6s semitone %-4d  x%d"
              % ("0x%02X" % p if p is not None else "--", s, n))


if __name__ == "__main__":
    main()
