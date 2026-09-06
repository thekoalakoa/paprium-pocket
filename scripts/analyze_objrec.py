"""Read the object-record records (kinds 18/19/20) out of a GPGX window log.

    python scripts/analyze_objrec.py vdp-capture/paprium_winlog.bin [--obj N] [--from F --to G]

Written 2026-09-06 for the walk-in stall. scripts/apply_gpgx_winlog.py logs, on
every 0xAD, the object record exactly as the game left it:

    kind 18  pad = +0xA (reset) low byte    address = index | (anim & 0xFF) << 8
    kind 19  pad = +0xA (reset) high byte   address = raw +4 word (objID; bit 15 = 'fresh')
    kind 20  pad = 0                        address = +2 (nextAnim)

mega-ppm reads +0xA as a frame counter it increments every draw and RESTARTS the
animation on any mismatch; GPGX restarts only on exactly 1. So the question this
answers is: what does the game write there, per object, per frame, and in
particular around a screen transition? A value other than 0/1 that is rewritten
on consecutive draws is a restart-every-frame on mega-ppm.
"""
import struct
import sys
from collections import defaultdict, Counter


def load(path):
    d = open(path, 'rb').read()
    n = len(d) // 8
    recs = []
    for i in range(n):
        k, pad, addr, stamp = struct.unpack_from('<BBHI', d, i * 8)
        recs.append((k, pad, addr, stamp >> 16, stamp & 0xFFFF))
    return recs


def main():
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)
    path = args[0]
    only = None
    f0, f1 = 0, 1 << 30
    if '--obj' in args:
        only = int(args[args.index('--obj') + 1], 0)
    if '--from' in args:
        f0 = int(args[args.index('--from') + 1])
    if '--to' in args:
        f1 = int(args[args.index('--to') + 1])

    recs = load(path)
    print("records %d, frames %d" % (len(recs), recs[-1][3] if recs else 0))

    # Stitch 18/19/20 triples (emitted back to back in that order).
    draws = []
    i = 0
    while i < len(recs):
        k, pad, addr, fr, vc = recs[i]
        if k == 18 and i + 2 < len(recs) and recs[i + 1][0] == 19 and recs[i + 2][0] == 20:
            index = addr & 0xFF
            anim = addr >> 8
            reset = pad | (recs[i + 1][1] << 8)
            obj_raw = recs[i + 1][2]
            next_anim = recs[i + 2][2]
            draws.append((fr, vc, index, anim, reset, obj_raw, next_anim))
            i += 3
        else:
            i += 1
    print("draws (0xAD with record) %d" % len(draws))
    if not draws:
        return

    # 1. What values does +0xA ever hold at draw time?
    vals = Counter(d[4] for d in draws)
    print("\n+0xA (reset) values seen at draw time:")
    for v, c in sorted(vals.items(), key=lambda x: -x[1])[:16]:
        print("  0x%04X  x%d" % (v, c))

    # 2. Per object: runs of consecutive draws where +0xA is the same non-0/1 value,
    #    and runs where it changes on every draw - both restart-every-frame on mega-ppm.
    by_obj = defaultdict(list)
    for d in draws:
        if f0 <= d[0] <= f1 and (only is None or d[2] == only):
            by_obj[d[2]].append(d)

    print("\nPer object: draws, distinct anims, +0xA values, longest run of draws with +0xA not in {0,1}")
    print("  obj  draws  anims  resets                         longest-bad-run  (frames)")
    suspicious = []
    for idx in sorted(by_obj):
        ds = by_obj[idx]
        anims = sorted(set(d[3] for d in ds))
        resets = Counter(d[4] for d in ds)
        best, cur, best_span, start = 0, 0, None, None
        for d in ds:
            if d[4] not in (0, 1):
                cur += 1
                if start is None:
                    start = d[0]
                if cur > best:
                    best, best_span = cur, (start, d[0])
            else:
                cur, start = 0, None
        rs = ' '.join('%X:%d' % (v, c) for v, c in sorted(resets.items())[:6])
        print("  %3d  %5d  %5d  %-30s %5d  %s" % (idx, len(ds), len(anims), rs, best, best_span or ''))
        if best >= 8:
            suspicious.append((idx, best, best_span))

    # 3. The restart-every-frame test proper: consecutive draws of one object where
    #    +0xA is not 1 and DIFFERS from what mega-ppm's counter would hold. mega-ppm
    #    sets counter = value at a restart, then increments; the game's value is
    #    'ours' only if it equals last+1. Anything else on a draw = restart on mega-ppm.
    print("\nmega-ppm restarts implied (value != 1 and != previous+1), per object, and the frames they span:")
    for idx in sorted(by_obj):
        ds = by_obj[idx]
        prev = None
        restarts = []
        for d in ds:
            v = d[4]
            if prev is not None and v != 1 and v != ((prev + 1) & 0xFFFF) and v != prev:
                restarts.append(d[0])
            prev = v
        if restarts:
            print("  obj %3d: %d implied restarts, frames %d..%d, e.g. %s" %
                  (idx, len(restarts), restarts[0], restarts[-1], restarts[:8]))

    # 4. Rewritten-every-frame: same non-{0,1} value on consecutive draws does NOT
    #    restart on mega-ppm after the first (counter catches up: value == prev means
    #    the game did not touch it... but mega-ppm would have incremented it, so a
    #    value equal to the previous draw's means the game REWROTE it). Flag those.
    print("\nvalues rewritten on consecutive draws (game re-stores the same +0xA each frame):")
    for idx in sorted(by_obj):
        ds = by_obj[idx]
        prev = None
        same = 0
        spans = []
        for d in ds:
            v = d[4]
            if prev is not None and v == prev and v not in (0,):
                same += 1
                spans.append(d[0])
            prev = v
        if same:
            print("  obj %3d: %d draws with +0xA identical to the previous draw (value non-zero), frames %d..%d" %
                  (idx, same, spans[0], spans[-1]))

    if suspicious:
        print("\nSUSPECTS (>= 8 consecutive draws with +0xA outside {0,1}):")
        for idx, best, span in suspicious:
            print("  obj %d: run %d, frames %s" % (idx, best, span))


if __name__ == '__main__':
    main()
