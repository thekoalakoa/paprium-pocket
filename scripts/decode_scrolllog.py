#!/usr/bin/env python3
"""Decode paprium_scrolllog.bin - the scroll-word census.

The question it exists to answer: in the Tug room the FOREGROUND bounces left and
right while the stage, background and enemies are fine. With the game in
full-screen scroll mode ($0B = 0x00, confirmed by the register census) a plane's
horizontal position is ONE WORD read at the top of the frame. So either that word
is being written wrong on some frames, or the bounce is not a scroll defect at all.

This decoder looks for the three ways it could be wrong:

    MISSED     a frame with no write at all -> the plane holds last frame's
               position, then snaps. This is what a lost vblank looks like.
    DUPLICATE  more than one write in a frame -> the last one wins, and if the
               raster has already passed the top of the frame the plane moved
               mid-frame.
    REGRESSION the value goes backward and then forward again within a few
               frames. THIS IS THE BOUNCE SIGNATURE. A plane scrolling smoothly
               produces a monotone or slowly-turning sequence; a stale write
               produces value N, N-1, N+1.

A clean result - exactly one write per frame per plane, at a stable raster
position, with a smooth value sequence - kills the whole scroll-write family and
says the bounce comes from somewhere else. That is a useful answer too.

Record layout (12 bytes, little-endian), written by ppm_scroll() in
gpgx-build/core/vdp_ctrl.c:
    u16 frame
    u16 line       v_counter at the write
    u16 hpos       cycles % MCYCLES_PER_LINE
    u16 addr       VDP address register
    u16 data       value written
    u8  kind       0 = HSCROLL 68k, 1 = HSCROLL Z80, 2 = VSRAM 68k, 3 = VSRAM Z80
    u8  pad

Usage:
    python3 decode_scrolllog.py paprium_scrolllog.bin
    python3 decode_scrolllog.py paprium_scrolllog.bin --hbase 0xF400 --trace 40
"""

import argparse
import struct
import sys
from collections import defaultdict, Counter

REC = 12
KIND = {0: 'HSCROLL/68k', 1: 'HSCROLL/Z80', 2: 'VSRAM/68k', 3: 'VSRAM/Z80'}


def load(path):
    with open(path, 'rb') as f:
        blob = f.read()
    n, extra = divmod(len(blob), REC)
    if extra:
        print('warning: %d trailing bytes (truncated capture)' % extra, file=sys.stderr)
    out = []
    for i in range(n):
        fr, line, hpos, addr, data, kind, _pad = struct.unpack_from('<HHHHHBB', blob, i * REC)
        out.append((fr, line, hpos, addr, data, kind))
    return out


def s16(v):
    """hscroll words are 10-bit signed-ish; treat as a wrapping counter"""
    return v & 0x3FF


def analyse(name, rows, nframes, trace):
    """rows: (frame, line, hpos, addr, data, kind) for ONE address"""
    print('-' * 74)
    print('%s' % name)
    print('-' * 74)
    if not rows:
        print('  no writes at all.')
        print('  If you expected some: the game may be writing this via DMA, which this')
        print('  logger does not capture. Check the DMA source/length registers.')
        print()
        return

    by_frame = defaultdict(list)
    for fr, line, hpos, addr, data, kind in rows:
        by_frame[fr].append((line, hpos, data))

    seen = sorted(by_frame)
    lo, hi = seen[0], seen[-1]
    span = hi - lo + 1

    counts = Counter(len(v) for v in by_frame.values())
    missed = [f for f in range(lo, hi + 1) if f not in by_frame]
    dupes = [f for f, v in by_frame.items() if len(v) > 1]

    lines = Counter(r[1] for r in rows)
    print('  writes            : %d over %d frames (%.2f per frame)'
          % (len(rows), span, len(rows) / float(span)))
    print('  writes per frame  : %s' % sorted(counts.items()))
    print('  raster position   : top vcounters %s' % lines.most_common(5))

    print()
    print('  MISSED frames     : %d (%.2f%%)  <- plane holds last position, then snaps'
          % (len(missed), 100.0 * len(missed) / span))
    if missed[:12]:
        print('    first few: %s' % missed[:12])
    print('  DUPLICATE frames  : %d (%.2f%%)  <- more than one write in a frame'
          % (len(dupes), 100.0 * len(dupes) / span))
    if dupes[:12]:
        print('    first few: %s' % sorted(dupes)[:12])

    # Value sequence: the LAST write of a frame is what the plane actually uses.
    # A plane scrolling normally has a roughly constant per-frame delta, so measure
    # that first and judge everything against it.
    seq = [(f, by_frame[f][-1][2]) for f in seen]

    def delta(a, b):
        """signed wrap-aware b-a on a 10-bit scroll word"""
        d = (b - a) & 0x3FF
        return d - 0x400 if d > 0x200 else d

    steps = []
    for i in range(1, len(seq)):
        if seq[i][0] == seq[i - 1][0] + 1:
            steps.append((seq[i][0], delta(seq[i - 1][1], seq[i][1])))
    nz = sorted(abs(d) for _f, d in steps if d)
    typ = nz[len(nz) // 2] if nz else 0

    # Two shapes, both of which look like a bounce on screen:
    #   STALL    the value does not change, then the next frame jumps to catch up.
    #            This is what a MISSED or STALE write produces - the plane freezes
    #            for one frame and then snaps forward. It is the likelier of the two.
    #   REVERSAL the value goes backward and immediately forward again.
    stalls, reversals = [], []
    for i in range(1, len(steps)):
        pf, pd = steps[i - 1]
        cf, cd = steps[i]
        if cf != pf + 1:
            continue
        if typ and pd == 0 and abs(cd) >= 1.5 * typ:
            stalls.append((pf, cd))
        elif pd and cd and (pd < 0) != (cd < 0) and typ and abs(pd) <= 4 * typ and abs(cd) <= 4 * typ:
            reversals.append((pf, pd, cd))

    print('  typical step      : %d units/frame (median of non-zero deltas)' % typ)
    print('  STALL+CATCHUP     : %d (%.2f%%)  <- plane freezes one frame then snaps'
          % (len(stalls), 100.0 * len(stalls) / span))
    for f, d in stalls[:8]:
        print('    frame %-6d  no movement, then %+d' % (f, d))
    print('  REVERSALS         : %d (%.2f%%)  <- value goes back then forward'
          % (len(reversals), 100.0 * len(reversals) / span))
    for f, a, b in reversals[:8]:
        print('    frame %-6d  %+d then %+d' % (f, a, b))
    print('  => BOUNCE EVENTS  : %d total (%.2f%% of frames)'
          % (len(stalls) + len(reversals),
             100.0 * (len(stalls) + len(reversals)) / span))

    print()
    if trace:
        print('  first %d frames, value sequence:' % trace)
        for f, v in seq[:trace]:
            n = len(by_frame[f])
            print('    frame %-6d line %-4d  value %4d (0x%03X)%s'
                  % (f, by_frame[f][-1][0], v, v, '   <-- %d writes' % n if n > 1 else ''))
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--hbase', type=lambda x: int(x, 0), default=None,
                    help='hscroll table base (default: infer from the lowest hscroll addr seen)')
    ap.add_argument('--trace', type=int, default=0,
                    help='print the first N frames of each value sequence')
    args = ap.parse_args()

    recs = load(args.path)
    if not recs:
        print('empty log. If unexpected: wrong DLL, PAPRIUM_SCROLLLOG_MAX=0, or the game')
        print('writes its scroll words by DMA (not captured - see the applier caveat).')
        return 1

    nframes = max(r[0] for r in recs) + 1
    kinds = Counter(r[5] for r in recs)

    print('=' * 74)
    print('scroll-word census: %s' % args.path)
    print('=' * 74)
    print('records           : %d' % len(recs))
    print('frames covered    : %d' % nframes)
    print('by kind           : %s' % {KIND.get(k, k): v for k, v in kinds.items()})

    hs = [r for r in recs if r[5] in (0, 1)]
    if hs:
        hbase = args.hbase if args.hbase is not None else min(r[3] for r in hs)
        print('hscroll table base: 0x%04X %s'
              % (hbase, '(given)' if args.hbase is not None else '(inferred from lowest write)'))
    else:
        hbase = args.hbase or 0
    print()

    addrs = Counter(r[3] for r in recs)
    print('addresses written : %s' % {('0x%04X' % a): c for a, c in addrs.most_common(10)})
    print()

    if hs:
        analyse('PLANE A horizontal  (hscroll table + 0)  <-- the foreground',
                [r for r in hs if r[3] == hbase], nframes, args.trace)
        analyse('PLANE B horizontal  (hscroll table + 2)  <-- the background',
                [r for r in hs if r[3] == hbase + 2], nframes, args.trace)

    vs = [r for r in recs if r[5] in (2, 3)]
    if vs:
        analyse('PLANE A vertical    (VSRAM + 0)',
                [r for r in vs if r[3] == 0], nframes, args.trace)
        analyse('PLANE B vertical    (VSRAM + 2)',
                [r for r in vs if r[3] == 2], nframes, args.trace)

    print('-' * 74)
    print('READING THIS')
    print('-' * 74)
    print('  GPGX does NOT exhibit the bounce, so this is the CORRECT baseline: whatever')
    print('  it shows is what the hardware has to reproduce. If plane A here is exactly')
    print('  one clean write per frame with a smooth value sequence, then on hardware the')
    print('  bounce is NOT the game writing a bad value - it is the write landing wrong,')
    print('  and the search moves to WHEN the write is admitted (cpu_as / slot timing) or')
    print('  to a lost vblank. If GPGX itself shows missed or duplicated frames, the game')
    print('  tolerates them and the mechanism is elsewhere entirely.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
