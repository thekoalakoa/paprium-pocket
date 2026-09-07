#!/usr/bin/env python3
"""Decode paprium_vdplog.bin - the GPGX VDP control-write census.

Written for the FX68K soak (ISA lane, 2026-09-07). The question it exists to
answer: does VDP register $8B (scroll mode) actually churn mid-frame, or is it
written once per scene with a constant value? If it is constant, then the
DTACK->w213 latency the +14 campaign has been optimising cannot move the
picture, because latching a constant late is invisible.

Secondary: $8C carries RS0/RS1, which decide H32 vs H40. The sim harness needs
that to be told which mode the failing scenes actually run in.

Record layout (8 bytes, little-endian), written by ppm_vdplog() in
gpgx-build/core/vdp_ctrl.c:
    [0]   reg    bit7 = 1 -> Z80-issued write; bits 4..0 = register number
    [1]   value
    [2:4] hpos   cycles modulo MCYCLES_PER_LINE (3420)
    [4:6] vcounter
    [6:8] frame

Usage:
    python3 decode_vdplog.py paprium_vdplog.bin
    python3 decode_vdplog.py paprium_vdplog.bin --reg 0x0B --dump
"""

import argparse
import struct
import sys
from collections import Counter, defaultdict

REC = 8
MCYCLES_PER_LINE = 3420

# Names for the registers that matter to this investigation. Others print bare.
REG_NAMES = {
    0x00: "mode1",
    0x01: "mode2",
    0x02: "plane A nametable",
    0x03: "window nametable",
    0x04: "plane B nametable",
    0x05: "sprite attr table",
    0x07: "backdrop colour",
    0x0A: "H interrupt counter",
    0x0B: "mode3 (scroll mode)",
    0x0C: "mode4 (RS0/RS1, interlace)",
    0x0D: "hscroll table",
    0x0F: "auto-increment",
    0x10: "plane size",
    0x11: "window H",
    0x12: "window V",
    0x13: "DMA length lo",
    0x14: "DMA length hi",
    0x15: "DMA source lo",
    0x16: "DMA source mid",
    0x17: "DMA source hi",
}


def decode_0b(v):
    """Register $0B. Netlist: ym7101.v:3391-3393 latches bit0->lscr, 1->hscr,
    2->vscr on w213."""
    lscr, hscr, vscr = v & 1, (v >> 1) & 1, (v >> 2) & 1
    if hscr:
        hmode = "per-cell"
    elif lscr:
        hmode = "per-line"
    else:
        hmode = "full-screen"
    return "HSCR=%s VSCR=%s IE2=%d" % (
        hmode,
        "2-cell" if vscr else "full-screen",
        (v >> 3) & 1,
    )


def decode_0c(v):
    """Register $0C. RS0 = bit7, RS1 = bit0. H40 needs both.
    ym7101.v:2245 - RS0 also switches the dot clock to the external EDCLK pin."""
    rs0, rs1 = (v >> 7) & 1, v & 1
    if rs0 and rs1:
        mode = "H40 (320px, dclk from EDCLK)"
    elif not rs0 and not rs1:
        mode = "H32 (256px, dclk from prescaler)"
    else:
        mode = "INVALID/odd (RS0=%d RS1=%d)" % (rs0, rs1)
    ilm = (v >> 1) & 3
    return "%s interlace=%d shadow/hilight=%d" % (mode, ilm, (v >> 3) & 1)


DECODERS = {0x0B: decode_0b, 0x0C: decode_0c}


def load(path):
    with open(path, "rb") as f:
        blob = f.read()
    n, extra = divmod(len(blob), REC)
    if extra:
        print("warning: %d trailing bytes (partial record, truncated capture)"
              % extra, file=sys.stderr)
    out = []
    for i in range(n):
        r, val, hpos, vc, fr = struct.unpack_from("<BBHHH", blob, i * REC)
        out.append((r & 0x1F, bool(r & 0x80), val, hpos, vc, fr))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--reg", type=lambda s: int(s, 0), default=None,
                    help="focus on one register, e.g. 0x0B")
    ap.add_argument("--dump", action="store_true",
                    help="print every write for the focused register")
    ap.add_argument("--frames", type=int, default=0,
                    help="limit to the first N frames")
    args = ap.parse_args()

    recs = load(args.path)
    if not recs:
        print("empty log - the emulator wrote no VDP register writes.")
        print("If that is unexpected: the DLL may not be the instrumented one,")
        print("or PAPRIUM_VDPLOG_MAX was set to 0.")
        return 1

    if args.frames:
        first = recs[0][5]
        recs = [r for r in recs if r[5] - first < args.frames]

    frames = sorted({r[5] for r in recs})
    nframes = len(frames)
    z80n = sum(1 for r in recs if r[1])

    print("=" * 72)
    print("VDP control-write census: %s" % args.path)
    print("=" * 72)
    print("records          : %d" % len(recs))
    print("frames covered   : %d  (frame %d .. %d)"
          % (nframes, frames[0], frames[-1]))
    print("68k / Z80 writes : %d / %d" % (len(recs) - z80n, z80n))
    print()

    # Per-register rollup.
    by_reg = defaultdict(list)
    for r in recs:
        by_reg[r[0]].append(r)

    print("%-5s %-26s %7s %8s %7s %-9s %s"
          % ("reg", "name", "writes", "per-fr", "values", "constant?", "mid-frame?"))
    print("-" * 96)
    for reg in sorted(by_reg):
        rs = by_reg[reg]
        vals = Counter(x[2] for x in rs)
        per_frame = len(rs) / float(nframes) if nframes else 0.0
        # "mid-frame" = written at more than one vcounter within some frame
        vc_by_frame = defaultdict(set)
        for x in rs:
            vc_by_frame[x[5]].add(x[4])
        midframe = max((len(v) for v in vc_by_frame.values()), default=0) > 1
        const = len(vals) == 1
        vshow = "0x%02X" % next(iter(vals)) if const else "%d distinct" % len(vals)
        print("$%02X   %-26s %7d %8.2f %7s %-9s %s"
              % (reg, REG_NAMES.get(reg, ""), len(rs), per_frame,
                 vshow if const else len(vals),
                 "YES" if const else "no",
                 "YES" if midframe else "no"))
    print()

    # The two registers this capture exists for.
    for reg in (0x0B, 0x0C):
        print("-" * 72)
        print("$%02X  %s" % (reg, REG_NAMES.get(reg, "")))
        print("-" * 72)
        rs = by_reg.get(reg)
        if not rs:
            print("  NEVER WRITTEN in this capture.")
            if reg == 0x0B:
                print("  => DTACK->w213 latency cannot affect this scene at all.")
            else:
                print("  => mode never changed from its power-on/init value;")
                print("     read it from a savestate or the init sequence instead.")
            print()
            continue

        vals = Counter(x[2] for x in rs)
        print("  writes: %d over %d frames (%.2f per frame)"
              % (len(rs), nframes, len(rs) / float(nframes) if nframes else 0))
        print("  distinct values: %d" % len(vals))
        for v, c in vals.most_common(12):
            dec = DECODERS[reg](v) if reg in DECODERS else ""
            print("    0x%02X  x%-7d %s" % (v, c, dec))

        vc_by_frame = defaultdict(set)
        for x in rs:
            vc_by_frame[x[5]].add(x[4])
        worst = max(vc_by_frame.items(), key=lambda kv: len(kv[1]),
                    default=(None, set()))
        print("  max distinct vcounters in one frame: %d (frame %s)"
              % (len(worst[1]), worst[0]))
        if len(vals) == 1 and len(worst[1]) <= 1:
            print("  VERDICT: constant and written at most once per frame.")
            if reg == 0x0B:
                print("           Late w213 is INVISIBLE. The +14 metric cannot")
                print("           produce a scroll-phase error in this scene.")
        else:
            print("  VERDICT: this register churns. Latency here is observable.")
        print()

    # Which registers actually churn - the follow-on question if $8B is constant.
    print("-" * 72)
    print("Registers that churn mid-frame, most active first")
    print("(these are where a write-timing error COULD be visible)")
    print("-" * 72)
    churn = []
    for reg, rs in by_reg.items():
        vc_by_frame = defaultdict(set)
        for x in rs:
            vc_by_frame[x[5]].add(x[4])
        m = max((len(v) for v in vc_by_frame.values()), default=0)
        if m > 1:
            churn.append((m, reg, len(rs), len({x[2] for x in rs})))
    if not churn:
        print("  none - every register is written at most once per frame.")
    for m, reg, n, nv in sorted(churn, reverse=True):
        print("  $%02X %-26s up to %3d writes/frame, %d distinct values"
              % (reg, REG_NAMES.get(reg, ""), m, nv))
    print()

    if args.reg is not None and args.dump:
        print("-" * 72)
        print("Every write to $%02X" % args.reg)
        print("-" * 72)
        print("%-8s %-6s %-6s %-7s %s" % ("frame", "vcnt", "hpos", "src", "value"))
        for r, z80, val, hpos, vc, fr in recs:
            if r == args.reg:
                print("%-8d %-6d %-6d %-7s 0x%02X"
                      % (fr, vc, hpos, "Z80" if z80 else "68k", val))

    return 0


if __name__ == "__main__":
    sys.exit(main())
