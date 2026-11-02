#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""s1_rv_slice.py - the stage-1 RV32 board-mode slice (the stage-1 images are the FW_S1 builds of our new firmware;
RV32 = 32-bit RISC-V; a slice is a short replay the test run passes or fails on): tests/equiv/rvboard.py --mode s1,
the stage-1 Pocket
images on the stage-1 board model (tests/equiv/rtlmodel.py) against the stage-1 host build of the same variant, post by
post on the solo capture, decided on the EXIT CODES:

  test     build/s1/pocket72k/test     vs build/s1/host/s1_ours_test.exe      frames 0 - --to: exit 0 required
  release  build/s1/pocket72k/release  vs build/s1/host/s1_ours_release.exe   frames 0 - --to: exit 0 required
  n1       build/s1/pocket72k/test_bug_disp1 (bit 14 not stored before the finish) vs the clean test host, frames 0-400:
           exit 1 with a 'register_writes' or 'register_page_68000_view' failure required
  n2       the RELEASE image against the TEST host, frames 0-400: exit 1 required (the TEST snapshots in the save RAM, the
           TEST-only register writes): the comparer sees a variant mix-up

    python -I -B tests/equiv/s1_rv_slice.py [--to 3000] [--keep DIR]

Inputs: paths.local.json "equiv" (capture_solo, rom). The planted-bug image is built on demand (tools/fwbuild.py s1
--images-only --variant test_bug_disp1). Outputs go to a temporary directory OUTSIDE the tree (kept when something
fails). Exit status: 0 = every run as required, 1 = something failed, 2 = setup error."""
import argparse, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PY = [sys.executable, '-I', '-B']


def setup_error(msg):
    print('SETUP ERROR: ' + msg)
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--to', type=int, default=3000)
    ap.add_argument('--build', default=os.path.join(ROOT, 'build'))
    ap.add_argument('--keep')
    a = ap.parse_args()
    lp = os.path.join(ROOT, 'paths.local.json')
    cfg = (json.load(open(lp)) if os.path.exists(lp) else {}).get('equiv')
    if not cfg:
        setup_error('paths.local.json has no "equiv" block')
    cap, rom = cfg.get('capture_solo'), cfg.get('rom')
    for what, p in (('capture_solo', cap), ('rom', rom)):
        if not p or not os.path.isfile(p):
            setup_error('equiv.%s missing: %r' % (what, p))
    img = lambda v: os.path.join(a.build, 's1', 'pocket72k', v)
    host = lambda v: os.path.join(a.build, 's1', 'host', 's1_ours_%s.exe' % v)
    for p in (img('test'), img('release')):
        if not os.path.exists(os.path.join(p, 'main.nm')):
            setup_error('%s missing: tools/fwbuild.py s1' % p)
    for v in ('test', 'release'):
        if not os.path.isfile(host(v)):
            setup_error('%s missing: tools/fwbuild.py s1' % host(v))
    if not os.path.exists(os.path.join(img('test_bug_disp1'), 'main.nm')):
        r = subprocess.run(PY + [os.path.join(ROOT, 'tools', 'fwbuild.py'), 's1', '--images-only', '--variant', 'test_bug_disp1',
                                 '--out', a.build], capture_output=True, text=True)
        if r.returncode:
            setup_error('building test_bug_disp1 failed: ' + (r.stdout + r.stderr)[-1500:])
    if a.keep:
        if os.path.abspath(a.keep).startswith(ROOT):
            setup_error('--keep must be outside the tree')
        out = a.keep
        os.makedirs(out, exist_ok=True)
    else:
        out = tempfile.mkdtemp(prefix='s1_rv_slice_')
    runs = [('test', img('test'), host('test'), a.to, 0, None),
            ('release', img('release'), host('release'), a.to, 0, None),
            ('n1', img('test_bug_disp1'), host('test'), min(a.to, 400), 1, ('register_writes', 'register_page_68000_view')),
            ('n2', img('release'), host('test'), min(a.to, 400), 1, ())]
    bad = 0
    for name, build, exe, to, want, kinds in runs:
        od = os.path.join(out, name)
        r = subprocess.run(PY + [os.path.join(HERE, 'rvboard.py'), od, '--mode', 's1', '--build', build, '--host', exe,
                                 '--capture', cap, '--rom', rom, '--to', str(to)], capture_output=True, text=True)
        ok = r.returncode == want
        if ok and kinds:
            try:
                got = json.load(open(os.path.join(od, 'summary.json')))['failures_by_kind']
                ok = any(k in got for k in kinds)
            except (OSError, ValueError, KeyError):
                ok = False
        last = (r.stdout.strip().splitlines() or [''])[-1]
        print('%-4s %-8s exit %d (want %d): %s' % ('ok' if ok else 'BAD', name, r.returncode, want, last[:160]))
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
