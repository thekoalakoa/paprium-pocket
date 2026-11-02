#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""host_smoke.py - smoke test of the host build (board/host, the 'ours' side of the audit harness: our test harness
outside this tree that runs a firmware build against the cart chip's program).

    python -I -B tests/host_smoke.py --harness <audit harness dir> [--build <repo>/build] [--posts N]

Uses the audit harness's own OursSide driver (harness.py, imported from --harness; nothing is copied) on both host
variants (build/host/{test,release}/ours_host.exe), with the game ROM the harness is configured for (read in place):
  1. boot: ppm_reset + the harness's boot posts (3 x 810E, C600 + the game's 14 words, 9494, 12 x 8300/8302);
  2. the option word ('O', the paprium-fw protocol addition): $1FE4 / $1FE6 after a reset for the default options and
     for Console = Model 2 (0x700) with MegaWire on (7 << 16): expected 0004|model and the MegaWire field;
  3. TEST vs RELEASE: the 68000-visible view (RAMDP + register page) after every post of a fixed post sequence must be
     identical (the release switch removes only debug aids; measured for the RV32 images of the final 0.2.6 firmware).
Prints PASS/FAIL lines; exit status 1 on any FAIL."""
import argparse, os, struct, sys

ap = argparse.ArgumentParser()
ap.add_argument('--harness', required=True)
ap.add_argument('--build', default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'build'))
ap.add_argument('--posts', type=int, default=400)
a = ap.parse_args()
sys.path.insert(0, a.harness)
import harness as H   # noqa: E402  (audit harness; pulls in its chip runner module but we only use the ours side)

ok_all = True


def res(name, ok, info=''):
    global ok_all
    ok_all &= bool(ok)
    print('%-4s %s %s' % ('PASS' if ok else 'FAIL', name, info))


def opt_reset(o, word):
    o._send(b'O' + struct.pack('<I', word)); o._k()
    o.reset()
    ram, _ = o.read_all()
    w = lambda off: struct.unpack_from('<H', ram, off)[0]   # MCU halfword at off = the 68000 word at off
    return w(0x1FE4), w(0x1FE6)


exe = {v: os.path.join(a.build, 'host', v, 'ours_host.exe') for v in ('test', 'release')}
for v, p in exe.items():
    res('exists %s' % v, os.path.exists(p), p)
sides = {v: H.OursSide(exe=p) for v, p in exe.items()}

for v, o in sides.items():
    s1, s2 = opt_reset(o, 0)
    res('%s default options: $1FE4/$1FE6' % v, (s1, s2 & 7) == (0x0004, 0), '%04X/%04X' % (s1, s2))
    s1, s2 = opt_reset(o, 0x700 | (7 << 16))
    res('%s Model 2 + MegaWire on: $1FE4/$1FE6' % v, (s1, s2 & 7) == (0x0704, 7), '%04X/%04X' % (s1, s2))
    s1, s2 = opt_reset(o, 0)

boots = {}
for v, o in sides.items():
    boots[v] = [r['view68'] for r in H.boot_ours(o)]
res('boot posts: TEST view == RELEASE view after each', boots['test'] == boots['release'], '%d posts' % len(boots['test']))
res('boot C600 reply', all(b is not None for b in boots['test']))

# a fixed, safe post sequence (no object records, so no pointer into unloaded data): sprite init, then frames of
# AE frame start (the game's sender words) and AF01/AF02 frame end with an empty SAT
seq = [('p', 0xB000)]
for f in range(a.posts // 2):
    seq += [('w', 0x1F16, 0), ('w', 0x1F10, 0x240), ('w', 0x1F1A, 1), ('w', 0x1F1C, 0), ('w', 0x1F18, 14), ('p', 0xAE00),
            ('p', 0xAF01 if f & 1 else 0xAF02)]
diffs = 0; n = 0
views = {}
for v, o in sides.items():
    vs = []
    for op, x, *y in seq:
        if op == 'w':
            o.w68(x, y[0])
        else:
            vs.append(o.post(x)['view68']); n += 1
    views[v] = vs
diffs = sum(1 for p, q in zip(views['test'], views['release']) if p != q)
res('sprite post sequence: TEST view == RELEASE view', diffs == 0, '%d posts, %d differ' % (len(views['test']), diffs))
for o in sides.values():
    o._send(b'Q')
print('ALL PASS' if ok_all else 'SOME FAIL')
sys.exit(0 if ok_all else 1)
