#!/usr/bin/env python3
"""Extract Paprium's YM2612 FM patch bank from the cartridge ROM.

    python scripts/fm_patches.py <paprium.md> [--patch N] [--csv]

**Location: ROM 0x004000, 135 records of 32 bytes, stored under a repeating
word XOR of 0xA8A2** - 0xA8 on even byte offsets, 0xA2 on odd. That is the third
obfuscation key this cartridge uses: module text is XOR 0xA5, the ROM UI string
tables are XOR 0xAA, and the FM bank is XOR 0xA8A2. Anything searched for in
plain bytes will not be found.

Record layout is operator-major - each field appears four times in a row, once
per operator, in the YM2612's own register order Op1, Op3, Op2, Op4:

    +0x00  4  TL          total level, 0..127
    +0x04  4  DT/MUL      detune in bits 4-6, multiple in bits 0-3
    +0x08  4  RS/AR       rate scaling in bits 6-7, attack rate in bits 0-4
    +0x0C  4  AM/D1R      AM enable in bit 7, first decay in bits 0-4
    +0x10  4  D2R         second decay, 0..31
    +0x14  4  D1L/RR      sustain level in bits 4-7, release in bits 0-3
    +0x18  4  SSG-EG      0..15
    +0x1C  1  FB/ALGO     feedback in bits 3-5, algorithm in bits 0-2
    +0x1D  1  LFO/AMS-PMS zero in 132 of 135 records
    +0x1E  2  zero in every record

Why this is certainly the bank, measured over all 135 records:

  * every YM2612 field limit holds, with no exceptions: TL <= 127, AR <= 31,
    D1R <= 31, D2R <= 31, SSG-EG <= 15, ALGO <= 7, FB <= 7, every unused bit
    zero, and the last two bytes zero. Random data does not do that.
  * there are exactly 135 records, and the music's own command-0x0F arguments on
    FM voices 0-5 span exactly 0x00..0x86 = 135 values.
  * scanning the whole ROM at every even offset under this key yields exactly
    one run of four or more consecutive valid records - this one, of length 135
    - against 52 scattered singles in 4.19 million positions.
  * the key itself is pinned independently of any padding assumption: of the 256
    keys the field constraints allow, only 0xA8A2 also satisfies "SSG-EG nonzero
    implies bit 3 set" across all 58 nonzero SSG-EG bytes.
  * the algorithm histogram spans all eight values (12/11/30/13/24/36/6/3) and
    feedback peaks at 7 and 0, which is what a hand-made bank looks like.

DT = 4 occurs 13 times and is legal: on the YM2612 the detune field's top bit is
a sign, so 4 is negative zero.

Voices 0-5 of a music module are the FM voices and index this bank through
command 0x0F. Voices 6-9 are PSG, 10-25 are the cartridge's own wave voices.

Derived from a commercial ROM. Keep extracted data local.
"""

import argparse
import struct

import numpy as np

BASE, COUNT, REC = 0x4000, 135, 32
KEY = (0xA8, 0xA2)
# register order is Op1, Op3, Op2, Op4; which slots are carriers per algorithm
CARRIERS = {0: {3}, 1: {3}, 2: {3}, 3: {3},
            4: {1, 3}, 5: {1, 2, 3}, 6: {1, 2, 3}, 7: {0, 1, 2, 3}}


def load(path):
    d = open(path, "rb").read()
    raw = np.frombuffer(d[BASE:BASE + COUNT * REC], dtype=np.uint8)
    key = np.tile(np.array(KEY, dtype=np.uint8), raw.size // 2)
    return (raw ^ key).reshape(COUNT, REC)


def decode(rec):
    """One record as YM2612 fields, per operator in register order."""
    ops = []
    for i in range(4):
        ops.append(dict(
            TL=int(rec[0 + i]),
            DT=int(rec[4 + i] >> 4) & 7, MUL=int(rec[4 + i]) & 15,
            RS=int(rec[8 + i] >> 6) & 3, AR=int(rec[8 + i]) & 31,
            AM=int(rec[12 + i] >> 7) & 1, D1R=int(rec[12 + i]) & 31,
            D2R=int(rec[16 + i]) & 31,
            D1L=int(rec[20 + i] >> 4) & 15, RR=int(rec[20 + i]) & 15,
            SSG=int(rec[24 + i]) & 15))
    return dict(ALGO=int(rec[28]) & 7, FB=int(rec[28] >> 3) & 7,
                LFO=int(rec[29]), ops=ops)


def check(t):
    """Every YM2612 field limit, over the whole bank."""
    bad = []
    if (t[:, 0:4] > 127).any(): bad.append("TL > 127")
    if (t[:, 4:8] > 127).any(): bad.append("DT/MUL bit 7 set")
    if ((t[:, 8:12] >> 5) & 1).any(): bad.append("RS/AR bit 5 set")
    if (((t[:, 12:16] >> 5) & 3)).any(): bad.append("AM/D1R bits 5-6 set")
    if (t[:, 16:20] > 31).any(): bad.append("D2R > 31")
    if (t[:, 24:28] > 15).any(): bad.append("SSG-EG > 15")
    if (t[:, 28] > 63).any(): bad.append("FB/ALGO > 63")
    if (t[:, 30:32] != 0).any(): bad.append("trailing bytes nonzero")
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("rom")
    ap.add_argument("--patch", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--csv", action="store_true")
    a = ap.parse_args()

    t = load(a.rom)
    bad = check(t)
    print("FM bank at 0x%04X: %d records of %d bytes, XOR %02X%02X"
          % (BASE, COUNT, REC, *KEY))
    print("field-limit violations: %s" % (", ".join(bad) if bad else "none"))

    if a.csv:
        cols = ["patch", "algo", "fb"] + [
            "%s%d" % (f, i + 1) for i in range(4)
            for f in ("tl", "mul", "dt", "ar", "d1r", "d2r", "d1l", "rr", "ssg")]
        print(",".join(cols))
        for p in range(COUNT):
            v = decode(t[p])
            row = [p, v["ALGO"], v["FB"]]
            for o in v["ops"]:
                row += [o["TL"], o["MUL"], o["DT"], o["AR"], o["D1R"],
                        o["D2R"], o["D1L"], o["RR"], o["SSG"]]
            print(",".join(str(x) for x in row))
        return

    todo = [a.patch] if a.patch is not None else range(COUNT)
    for p in todo:
        v = decode(t[p])
        car = CARRIERS[v["ALGO"]]
        print("\npatch 0x%02X   algorithm %d   feedback %d%s"
              % (p, v["ALGO"], v["FB"], "   LFO %d" % v["LFO"] if v["LFO"] else ""))
        print("   op  role       TL  MUL  DT   AR  D1R  D2R  D1L   RR  SSG")
        for i, o in enumerate(v["ops"]):
            print("   %d   %-9s %3d  %3d  %2d  %3d  %3d  %3d  %3d  %3d  %3d"
                  % (i + 1, "carrier" if i in car else "modulator",
                     o["TL"], o["MUL"], o["DT"], o["AR"], o["D1R"],
                     o["D2R"], o["D1L"], o["RR"], o["SSG"]))


if __name__ == "__main__":
    main()
