#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""slice.py - the short replay slice that tests/run_all.py passes or fails on (stage 0, the tree's first step,
2026-10-10).

    python -I -B tests/equiv/slice.py [--part host|rv32|neg|all] [--to 3000] [--fw-root DIR] [--keep DIR]

Runs the two equivalence rigs on the first --to frames of the solo capture (default 0-3,000: 11,121 posts, the first
F5 posts at frame 2,174, so the scaling path is in it) and decides on their EXIT CODES:

  host  equivA.py: the paprium-fw host build, TEST and RELEASE, against the committed reference digests of final
        0.2.6 (expected/host_final026.json, runs test_solo / release_solo; every 1,000-frame mark reached), plus
        the reference host executable as a second side, post by post, when paths.local.json names one.
  rv32  rvboard.py: the pocket72k (72 KB) RV32 images against the host build of the same variant, post by post:
        TEST in call mode, RELEASE in board mode (the polling loop; Boom Box VU words = allow-list A5).
  neg   the rigs must FAIL on a real difference (frames 0-300 / 0-1,000, a few seconds each):
        n1 equivA, TEST host vs RELEASE host (BRAM debug window differs, allow-list A1 not applied) -> exit 1;
        n2 equivA, the RELEASE host against the TEST digests (--expect) -> exit 1;
        n3 rvboard, the RELEASE image against the TEST host -> exit 1.
        A control passes only if the rig exits 1 for the expected reason (not a crash).

Inputs come from paths.local.json "equiv" (not tracked):
  {"capture_solo": "<the solo capture's capture.bin>", "rom": "<the dev ROM it was recorded with>",
   "ref_host": {"test": "<final026_test.exe>", "release": "<final026_release.exe>"}}   (ref_host optional)
The capture is identified by the md5 of its first MiB, the ROM by the expected file's md5 (else exit 2).
Outputs go to a temporary directory OUTSIDE the tree (kept and named when something fails; --keep DIR to keep them).
Exit status: 0 = every run as required, 1 = something failed, 2 = setup error (missing config, inputs or builds)."""
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PY = [sys.executable, '-I', '-B']
EXPECTED = os.path.join(HERE, 'expected', 'host_final026.json')
SOLO_HEAD_MD5 = '2987a01072341dd8f28322ae173d1111'   # md5 of the solo capture's first MiB (equivA 'capture_md5_head')


def setup_error(msg):
    print('SETUP ERROR: ' + msg)
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--part', choices=('host', 'rv32', 'neg', 'all'), default='all')
    ap.add_argument('--to', type=int, default=3000)
    ap.add_argument('--fw-root', default=ROOT, help='tree whose build/ is replayed (default: this tree)')
    ap.add_argument('--keep', help='write the run outputs here and keep them (must be outside the tree)')
    a = ap.parse_args()
    lp = os.path.join(ROOT, 'paths.local.json')
    cfg = (json.load(open(lp)) if os.path.exists(lp) else {}).get('equiv')
    if not cfg:
        setup_error('paths.local.json has no "equiv" block (capture_solo, rom[, ref_host])')
    cap, rom = cfg.get('capture_solo'), cfg.get('rom')
    for what, p in (('capture_solo', cap), ('rom', rom)):
        if not p or not os.path.isfile(p):
            setup_error('equiv.%s missing: %r' % (what, p))
    with open(cap, 'rb') as f:
        if hashlib.md5(f.read(1 << 20)).hexdigest() != SOLO_HEAD_MD5:
            setup_error('equiv.capture_solo is not the solo capture the digests were made with (first-MiB md5 differs)')
    exp = json.load(open(EXPECTED))['runs']
    with open(rom, 'rb') as f:
        if hashlib.md5(f.read()).hexdigest() != exp['test_solo']['rom_md5']:
            setup_error('equiv.rom is not the ROM the expected digests were made with')
    fw = os.path.abspath(a.fw_root)
    host = {v: os.path.join(fw, 'build', 'host', v, 'ours_host.exe') for v in ('test', 'release')}
    img = {v: os.path.join(fw, 'build', 'pocket', 'pocket72k', v) for v in ('test', 'release')}
    for p in list(host.values()) + [os.path.join(d, 'main.elf') for d in img.values()]:
        if not os.path.isfile(p):
            setup_error('build product missing: %s (run tools/fwbuild.py all)' % p)
    ref = cfg.get('ref_host') or {}
    for v, p in ref.items():
        if not os.path.isfile(p):
            setup_error('equiv.ref_host.%s missing: %s' % (v, p))
    if a.keep:
        out = os.path.abspath(a.keep)
        if out.startswith(os.path.abspath(ROOT) + os.sep):
            setup_error('--keep must be outside the tree')
        os.makedirs(out, exist_ok=True)
    else:
        out = tempfile.mkdtemp(prefix='pfw_slice_')
    eq, rv = os.path.join(HERE, 'equivA.py'), os.path.join(HERE, 'rvboard.py')
    common = ['--capture', cap, '--rom', rom]
    T = str(a.to)
    runs = []          # (name, cmd, want_fail, want_reason)
    if a.part in ('host', 'all'):
        for v in ('test', 'release'):
            cmd = PY + [eq, None] + common + ['--side', 'new=' + host[v]]
            if v in ref:
                cmd += ['--side', 'ref=' + ref[v]]
            cmd += ['--to', T, '--expect', '%s:%s_solo' % (EXPECTED, v)]
            runs.append(('host %s == final 0.2.6 digests%s, frames 0-%s' % (v.upper(), ' + reference exe' if v in ref else '', T),
                         cmd, False, None))
    if a.part in ('rv32', 'all'):
        runs.append(('RV32 pocket72k TEST image == host TEST (call mode), frames 0-%s' % T,
                     PY + [rv, None, '--build', img['test'], '--host', host['test']] + common + ['--to', T, '--mode', 'call'],
                     False, None))
        runs.append(('RV32 pocket72k RELEASE image == host RELEASE (board mode), frames 0-%s' % T,
                     PY + [rv, None, '--build', img['release'], '--host', host['release']] + common + ['--to', T, '--mode', 'board'],
                     False, None))
    if a.part in ('neg', 'all'):
        runs.append(('n1 equivA catches TEST vs RELEASE host (BRAM debug window), frames 0-300',
                     PY + [eq, None] + common + ['--side', 't=' + host['test'], '--side', 'r=' + host['release'], '--to', '300'],
                     True, 'bram_snapshot_900'))
        runs.append(('n2 equivA --expect catches RELEASE host vs the TEST digests, frames 0-1000',
                     PY + [eq, None] + common + ['--side', 'r=' + host['release'], '--to', '1000',
                                                 '--expect', '%s:test_solo' % EXPECTED], True, '--expect'))
        runs.append(('n3 rvboard catches the RELEASE image vs the TEST host, frames 0-300',
                     PY + [rv, None, '--build', img['release'], '--host', host['test']] + common + ['--to', '300'],
                     True, 'bram'))
    bad = 0
    for k, (name, cmd, want_fail, why) in enumerate(runs):
        d = os.path.join(out, 'run%d' % k)
        cmd[cmd.index(None)] = d
        t0 = time.time()
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'stdout.txt'), 'w') as lf:
            rc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT).returncode
        sp = os.path.join(d, 'summary.json')
        s = json.load(open(sp)) if os.path.exists(sp) else {}
        reasons = s.get('fail_reasons', [])
        if want_fail:
            ok = rc == 1 and s.get('result') == 'FAIL' and any(why in r for r in reasons)
            info = 'rig exit %d: %s' % (rc, (reasons[0] if reasons else 'no summary (crashed?)')[:150])
        else:
            ok = rc == 0 and s.get('result') == 'PASS'
            info = 'rig exit %d, %s posts%s' % (rc, s.get('posts', '?'), (', ' + '; '.join(reasons)[:300]) if reasons else '')
            if 'expect' in s:
                info += ', %d digest marks' % s['expect']['marks_checked']
        bad += not ok
        print('%-4s %s: %s (%.0f s)' % ('PASS' if ok else 'FAIL', name, info, time.time() - t0), flush=True)
    if bad:
        print('%d of %d runs not as required; outputs kept in %s' % (bad, len(runs), out))
    elif not a.keep:
        shutil.rmtree(out, ignore_errors=True)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
