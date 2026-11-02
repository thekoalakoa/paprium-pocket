#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""s1_slice.py - the stage-1 replay slice (a short replay) that tests/run_all.py passes or fails on (2026-10-11). The
stage-1 build is the FW_S1 build of our new firmware.

    python -I -B tests/equiv/s1_slice.py [--to 3000] [--keep DIR]

Runs tests/equiv/s1_equiv.py, the stage-1 host build (build/s1/host/s1_ours_<variant>.exe: the dispatcher that works as
the chip's, the 0.2.6 bodies re-hosted under the chip's command map, the fake board) against the final 0.2.6 reference
host build on the first --to frames of the solo capture, post by post, and decides on the EXIT CODES:

  release  s1_ours_release vs final026_release: exit 0 required
  test     s1_ours_test vs final026_test (--test: BRAM $900-$FFF under the debug allow): exit 0 required
  n1       release, cart RAM $0100 poked on the stage-1 side before post 500: exit 1 with a 'ramdp' failure required
  n2       release, the low byte of the first SFX post (D1) + 1 on the stage-1 side: exit 1 with an 'audio' failure
           required

Inputs: paths.local.json "equiv" (capture_solo, rom, ref_host.test / .release), as tests/equiv/slice.py. Outputs go to
a temporary directory OUTSIDE the tree (kept and named when something fails; --keep DIR to keep them).
Exit status: 0 = every run as required, 1 = something failed, 2 = setup error."""
import argparse, json, mmap, os, shutil, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PY = [sys.executable, '-I', '-B']


def setup_error(msg):
    print('SETUP ERROR: ' + msg)
    sys.exit(2)


def first_post(cap, cmd, to):
    """index of the first post of command byte cmd in the capture (records as s1_equiv reads them)"""
    with open(cap, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as d:
        o, n = 0, 0
        while o + 20 <= len(d):
            t, ln, fr = struct.unpack_from('<HHI', d, o)
            po = o + 20
            o = po + ln
            if fr > to:
                break
            if t != 2:
                continue
            if struct.unpack_from('<H', d, po)[0] >> 8 == cmd:
                return n
            n += 1
    return -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--to', type=int, default=3000)
    ap.add_argument('--keep', help='write the run outputs here and keep them (must be outside the tree)')
    a = ap.parse_args()
    lp = os.path.join(ROOT, 'paths.local.json')
    cfg = (json.load(open(lp)) if os.path.exists(lp) else {}).get('equiv')
    if not cfg:
        setup_error('paths.local.json has no "equiv" block')
    cap, rom, refs = cfg.get('capture_solo'), cfg.get('rom'), cfg.get('ref_host') or {}
    for what, p in (('capture_solo', cap), ('rom', rom), ('ref_host.test', refs.get('test')),
                    ('ref_host.release', refs.get('release'))):
        if not p or not os.path.isfile(p):
            setup_error('equiv.%s missing: %r' % (what, p))
    new = {v: os.path.join(ROOT, 'build', 's1', 'host', 's1_ours_%s.exe' % v) for v in ('test', 'release')}
    for v, p in new.items():
        if not os.path.isfile(p):
            setup_error('%s missing: build it with tools/fwbuild.py s1 --variant %s' % (p, v))
    if a.keep:
        if os.path.abspath(a.keep).startswith(ROOT):
            setup_error('--keep must be outside the tree')
        out = a.keep
        os.makedirs(out, exist_ok=True)
    else:
        out = tempfile.mkdtemp(prefix='s1_slice_')
    neg_to = min(a.to, 1000)
    sfx = first_post(cap, 0xD1, neg_to)
    if sfx < 0:
        setup_error('no D1 post in frames 0-%d' % neg_to)
    runs = [('release', 'release', [], 0, None),
            ('test', 'test', ['--test'], 0, None),
            ('n1', 'release', ['--plant', 'ram@500'], 1, 'ramdp'),
            ('n2', 'release', ['--plant', 'word@%d' % sfx], 1, 'audio')]
    bad = 0
    for name, var, extra, want, kind in runs:
        od = os.path.join(out, name)
        cmd = PY + [os.path.join(HERE, 's1_equiv.py'), od, '--capture', cap, '--rom', rom, '--ref', refs[var],
                    '--new', new[var], '--to', str(a.to if want == 0 else neg_to)] + extra
        r = subprocess.run(cmd, capture_output=True, text=True)
        ok = r.returncode == want
        if ok and kind:
            try:
                ok = kind in json.load(open(os.path.join(od, 'summary.json')))['failures_by_kind']
            except (OSError, ValueError, KeyError):
                ok = False
        last = (r.stdout.strip().splitlines() or [''])[-1]
        print('%-4s %-8s %-8s exit %d (want %d%s): %s' % ('ok' if ok else 'BAD', name, var, r.returncode, want,
                                                          ', ' + kind if kind else '', last))
        if not ok:
            bad += 1
            print(r.stdout[-2000:], r.stderr[-2000:])
    if bad:
        print('outputs kept in %s' % out)
        return 1
    if not a.keep:
        shutil.rmtree(out, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
