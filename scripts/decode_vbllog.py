#!/usr/bin/env python3
"""Decode paprium_vbllog.bin - the vblank-margin census.

The question it exists to answer: how much room does Paprium actually leave
between finishing its per-frame VDP updates and the start of active display?

Written for the FX68K soak. The OSD-freeze test (2026-09-07) showed the frozen
picture is clean while the running picture is not, so VRAM is correct at all
times and the defect is that the VDP scans a region while the CPU is still
writing it. Whether a small CPU throughput difference can cause that depends
entirely on the margin, and nobody had measured it.

    hundreds of spare lines  -> no plausible slowdown reaches active display,
                                and the whole timing family is dead
    a handful of spare lines -> fragile by construction; a small throughput
                                loss produces exactly the observed symptom

Record layout (8 bytes, little-endian), written by ppm_vbl() in
gpgx-build/core/vdp_ctrl.c. One record per (frame, line) that saw any traffic:
    u16 frame
    u16 line          v_counter
    u16 data_writes   data-port writes on that line (saturating)
    u16 dma_words     DMA words initiated on that line (saturating)

Geometry: NTSC is 262 lines per frame, PAL 313. Active display is 224 lines in
this game's mode ($8C = 0x81 -> H40, confirmed by the register census), so
lines 0..223 are ACTIVE and 224..end are VBLANK. Override with --active / --total
if a capture says otherwise; the decoder reports what it observes either way.

CAVEAT carried from the applier: GPGX performs DMA instantaneously, so a
transfer's START line is faithful but its SPAN is not. This measures when the
game INITIATES work, which is the right quantity for a margin calculation, but
it does not model a long transfer overrunning by itself.

Usage:
    python3 decode_vbllog.py paprium_vbllog.bin
    python3 decode_vbllog.py paprium_vbllog.bin --active 224 --hist
"""

import argparse
import struct
import sys
from collections import defaultdict

REC = 8


def load(path):
    with open(path, 'rb') as f:
        blob = f.read()
    n, extra = divmod(len(blob), REC)
    if extra:
        print('warning: %d trailing bytes (truncated capture)' % extra, file=sys.stderr)
    out = []
    for i in range(n):
        fr, line, nd, nm = struct.unpack_from('<HHHH', blob, i * REC)
        out.append((fr, line, nd, nm))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--active', type=int, default=224,
                    help='first vblank line (default 224 = H40 NTSC active height)')
    ap.add_argument('--total', type=int, default=0,
                    help='lines per frame (default: infer from the data)')
    ap.add_argument('--hist', action='store_true', help='print the per-line histogram')
    ap.add_argument('--dma-rate', type=int, default=167,
                    help='hardware DMA words per scanline (default 167 = H40 vblank '
                         '68k->VRAM; H32 vblank is ~205). This is the figure GPGX cannot '
                         'model, and it decides whether the margin is real.')
    args = ap.parse_args()

    recs = load(args.path)
    if not recs:
        print('empty log. If unexpected: wrong DLL, or PAPRIUM_VBLLOG_MAX=0.')
        return 1

    maxline = max(r[1] for r in recs)
    # Do NOT infer lines-per-frame from the highest line written: the game does
    # not write on the tail of the frame, and that tail IS the margin. Inferring
    # collapses total onto the last write and reports margin 0 every time.
    if args.total:
        total = args.total
        inferred = 'given'
    elif maxline < 262:
        total = 262
        inferred = 'assumed NTSC'
    elif maxline < 313:
        total = 313
        inferred = 'assumed PAL'
    else:
        total = maxline + 1
        inferred = 'from data (line %d seen)' % maxline
    active = args.active

    frames = defaultdict(list)
    for fr, line, nd, nm in recs:
        frames[fr].append((line, nd, nm))

    nfr = len(frames)
    all_data = sum(r[2] for r in recs)
    all_dma = sum(r[3] for r in recs)

    print('=' * 74)
    print('vblank-margin census: %s' % args.path)
    print('=' * 74)
    print('records            : %d' % len(recs))
    print('frames             : %d' % nfr)
    print('highest line written: %d' % maxline)
    print('lines per frame    : %d  (%s)' % (total, inferred))
    if maxline >= total:
        print('  WARNING: writes seen at or past the assumed frame end; pass --total')
    print('active display     : lines 0..%d      vblank: lines %d..%d (%d lines)'
          % (active - 1, active, total - 1, total - active))
    print('data-port writes   : %d  (%.0f per frame)' % (all_data, all_data / nfr))
    print('DMA words          : %d  (%.0f per frame)' % (all_dma, all_dma / nfr))
    print()

    # per-line totals
    by_line_d = defaultdict(int)
    by_line_m = defaultdict(int)
    for fr, line, nd, nm in recs:
        by_line_d[line] += nd
        by_line_m[line] += nm

    act_d = sum(v for k, v in by_line_d.items() if k < active)
    vbl_d = sum(v for k, v in by_line_d.items() if k >= active)
    act_m = sum(v for k, v in by_line_m.items() if k < active)
    vbl_m = sum(v for k, v in by_line_m.items() if k >= active)

    print('-' * 74)
    print('WHERE THE WORK HAPPENS')
    print('-' * 74)
    tot_d = act_d + vbl_d or 1
    tot_m = act_m + vbl_m or 1
    print('  data writes  in vblank: %9d (%5.1f%%)   in active display: %9d (%5.1f%%)'
          % (vbl_d, 100.0 * vbl_d / tot_d, act_d, 100.0 * act_d / tot_d))
    print('  DMA words    in vblank: %9d (%5.1f%%)   in active display: %9d (%5.1f%%)'
          % (vbl_m, 100.0 * vbl_m / tot_m, act_m, 100.0 * act_m / tot_m))
    print()

    # Per-frame margin. The vblank burst runs from `active` up to total-1; the
    # slack is the untouched tail of that window.
    margins, spills, bursts = [], [], []
    for fr, rows in frames.items():
        vb = [ln for ln, nd, nm in rows if ln >= active and (nd or nm)]
        ac = [ln for ln, nd, nm in rows if ln < active and (nd or nm)]
        if vb:
            margins.append((total - 1) - max(vb))
            bursts.append(max(vb) - min(vb) + 1)
        spills.append(len(ac))

    print('-' * 74)
    print('VBLANK MARGIN  (lines left between the last vblank write and end of frame)')
    print('-' * 74)
    if margins:
        margins.sort()
        n = len(margins)
        def pct(p): return margins[min(n - 1, int(n * p))]
        print('  frames with vblank traffic : %d / %d' % (n, nfr))
        print('  margin  min=%d  p5=%d  median=%d  p95=%d  max=%d  (lines)'
              % (margins[0], pct(0.05), pct(0.50), pct(0.95), margins[-1]))
        print('  vblank window is %d lines; burst length median %d lines'
              % (total - active, sorted(bursts)[len(bursts) // 2] if bursts else 0))
        print()
        tight = sum(1 for m in margins if m <= 2)
        print('  frames finishing within 2 lines of the end of vblank: %d (%.1f%%)'
              % (tight, 100.0 * tight / n))
    else:
        print('  no vblank traffic recorded')
    print()

    print('-' * 74)
    print('SPILL INTO ACTIVE DISPLAY  (on a CORRECT run - GPGX has no defect)')
    print('-' * 74)
    nsp = sum(1 for s in spills if s)
    print('  frames with any write during active display: %d / %d (%.1f%%)'
          % (nsp, nfr, 100.0 * nsp / nfr))
    if act_d or act_m:
        lines_hit = sorted(k for k in set(list(by_line_d) + list(by_line_m)) if k < active)
        print('  active lines touched: %d distinct, from line %d to %d'
              % (len(lines_hit), lines_hit[0], lines_hit[-1]))
    print()

    print('-' * 74)
    print('HARDWARE DMA OCCUPANCY  (the number GPGX cannot show you)')
    print('-' * 74)
    vbl_lines = total - active
    dma_per_frame = all_dma / float(nfr)
    hw_lines = dma_per_frame / float(args.dma_rate)
    occ = 100.0 * hw_lines / vbl_lines
    print('  DMA words per frame        : %.0f' % dma_per_frame)
    print('  hardware rate assumed      : %d words/line (%s)'
          % (args.dma_rate, 'H40 vblank 68k->VRAM' if args.dma_rate == 167 else 'given'))
    print('  => real lines of DMA       : %.1f of the %d-line vblank window' % (hw_lines, vbl_lines))
    print('  => vblank occupancy        : %.0f%%' % occ)
    print()
    print('  GPGX runs DMA instantaneously, so the margin above is an UPPER BOUND.')
    print('  Subtract the occupancy to get the real slack:')
    print('  effective free lines ~ %.1f' % max(0.0, vbl_lines - hw_lines))
    print()

    print('-' * 74)
    print('READING THIS')
    print('-' * 74)
    if occ >= 40:
        print('  DMA alone consumes %.0f%% of vblank on hardware. That is NOT comfortable.' % occ)
        print('  A CPU that reaches its vblank routine late pushes the tail of an already')
        print('  half-full window past the end of vblank, and the VDP begins scanning')
        print('  while the last transfer is still landing. Consistent with a clean frozen')
        print('  frame and a broken running one.')
    elif occ >= 20:
        print('  DMA consumes %.0f%% of vblank on hardware - moderate. Whether that is' % occ)
        print('  survivable depends on how late the CPU starts; worth comparing against')
        print('  a scene where the defect does NOT appear.')
    else:
        print('  DMA consumes only %.0f%% of vblank on hardware. There is real slack here,' % occ)
        print('  so a deadline overrun is unlikely to be the mechanism in THIS scene.')
    if margins:
        med = margins[len(margins) // 2]
        print('  (GPGX-reported margin: median %d lines - upper bound only, see above.)' % med)
    print()

    if args.hist:
        print('-' * 74)
        print('PER-LINE HISTOGRAM (data writes + DMA words, summed over all frames)')
        print('-' * 74)
        peak = max(max(by_line_d.values(), default=1), max(by_line_m.values(), default=1))
        for ln in range(total):
            d, m = by_line_d.get(ln, 0), by_line_m.get(ln, 0)
            if not (d or m):
                continue
            bar = '#' * int(40.0 * (d + m) / peak)
            tag = 'ACTIVE' if ln < active else 'vblank'
            print('  %3d %s  data=%-7d dma=%-7d %s' % (ln, tag, d, m, bar))
    return 0


if __name__ == '__main__':
    sys.exit(main())
