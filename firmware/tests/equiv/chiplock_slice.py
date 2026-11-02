#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""chiplock_slice.py - the chip lockstep's short slice (a short replay) that tests/run_all.py --s1-rigs passes or fails
on. The stage-1 host build is FW_S1, our new firmware's core; test build 4 is a firmware build B Jam tested on his
hardware; D-numbers are the differences of our firmware audit (not in this tree).

    python -I -B tests/equiv/chiplock_slice.py [--to 3700] [--keep DIR]

Runs tests/equiv/chiplock_s1.py (the cart program in the cart-music runner, our test harness outside this tree, the
stage-1 host build, the final 0.2.6 host build; every field per
tests/equiv/s1_scope.json) on the solo capture and decides on the EXIT CODES:

  release   RELEASE, frames 0 - --to, the synthetic list (synth.py SYNTH_S1_MID) posted at frame 3600, the AF unit
            (--af-unit: the chip's frame end on synthetic tables, every count 0-140 x modes, both parities) and the tail
            (SYNTH_S1_TAIL: the refusal forms, a second C6, EXTI 13, 85) after the last frame: exit 0 required
  test      TEST (--test), frames 0-1,000: exit 0 required
  consoles  --consoles, frames 0-400: the 68000's $1FE4 = 0x0004 | model after C6 and the composer rule at every post,
            for every Console model x MegaWire x region word (20 runs, no chip): exit 0 required
  n1        s1_ours_bug_disp1 (RELEASE with DISP_BUG=1: a queued job's bit 14 not stored before the finish), frames
            0-400: exit 1 with a 'regwrites' failure required
  n2        a scope file without the 'T-S5 fifoA' transform, frames 0-400: exit 1 with a 'regwrites' failure required
            (the chip's 9494 FIFO-A writes are allowed by that row and nothing else)
  n3        --plant stored@300 (a $1FE6 bit the chip never sets in new's stored-word read): exit 1, 'stored'
  n4        --plant fe4@300 (bit 7 in new's $1FE4 view): exit 1, 'fe4_view'
  n5-n8     since the sprite-values update, the sprite values'
  planted bugs (fwbuild.json s1 host program variants bug_spr1..4):
            n5 s1_ours_bug_spr1 (0.2.6's clip back), frames 0-1,700 (the route's first piece the two clips treat apart is
            at frame 1,682): exit 1, 'sprite_chip'; n6 bug_spr2 ($1F1C never written), n7 bug_spr3 (B0 does not bump
            the parity) and n8 bug_spr4 (the stash taken from entries 0-13), frames 0-400 and the AF unit: exit 1 with
            'sprite_chip', 'af_unit' and 'sprite_chip'
  n9-n11    since test build 4 (D23 done the chip's way: the chip's
  attribute ADD and pose bit 29; the lockstep compares the attribute word):
            n9 s1_ours_bug_spr5 (0.2.6's field-wise attribute rule and door fix back; stage 2: SPR_BUG 5 in core/sprite,
            as the other plants: SPR_BUG 1 is 0.2.6's clip there), frames 0-1,100
            (the route's first entry the two rules compose apart is at frame 1,040: an AF02 table drawn on palette line 2
            by the chip, 1 by 0.2.6); n10 bug_spr6 (pose bit 29 ignored), frames 0-2,300 (first at 2,249); n11 bug_spr7
            (the H-flip path composed as the plain one), frames 0-12,000 (the solo route's only exposed pieces: an H-flipped
            object $0D whose piece attr byte has bit 3, frames 11,995-11,996, measured from the capture's poses): each
            exit 1 with 'sprite_chip'

Inputs: paths.local.json "equiv" (capture_solo, rom, ref_host.test / .release, chip_runner); the host builds from
tools/fwbuild.py s1. Outputs go to a temporary directory OUTSIDE the tree (kept when something fails; --keep DIR).
Exit status: 0 = every run as required, 1 = something failed, 2 = setup error. Measured 2026-10-13: 1 min 40 s - 1 min
50 s (since the sprite-values update, with n5-n8 and the AF unit: 1 min 51 s, measured 2026-10-17; test build 4 adds
n9-n11, ~7 min more: n11 replays 12,000 frames)."""
import argparse, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PY = [sys.executable, '-I', '-B']


def setup_error(msg):
    print('SETUP ERROR: ' + msg)
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--to', type=int, default=3700)
    ap.add_argument('--keep', help='write the run outputs here and keep them (must be outside the tree)')
    a = ap.parse_args()
    lp = os.path.join(ROOT, 'paths.local.json')
    cfg = (json.load(open(lp)) if os.path.exists(lp) else {}).get('equiv')
    if not cfg:
        setup_error('paths.local.json has no "equiv" block')
    cap, rom, refs, runner = cfg.get('capture_solo'), cfg.get('rom'), cfg.get('ref_host') or {}, cfg.get('chip_runner')
    for what, p in (('capture_solo', cap), ('rom', rom), ('ref_host.test', refs.get('test')),
                    ('ref_host.release', refs.get('release'))):
        if not p or not os.path.isfile(p):
            setup_error('equiv.%s missing: %r' % (what, p))
    if not runner or not os.path.isfile(os.path.join(runner, 'cartmcu.py')):
        setup_error('equiv.chip_runner missing: %r (the cartaudio runner directory)' % runner)
    new = {v: os.path.join(ROOT, 'build', 's1', 'host', 's1_ours_%s.exe' % v)
           for v in ('test', 'release', 'bug_disp1', 'bug_spr1', 'bug_spr2', 'bug_spr3', 'bug_spr4', 'bug_spr5', 'bug_spr6',
                     'bug_spr7')}
    for v, p in new.items():
        if not os.path.isfile(p):
            setup_error('%s missing: build it with tools/fwbuild.py s1' % p)
    if a.keep:
        if os.path.abspath(a.keep).startswith(ROOT):
            setup_error('--keep must be outside the tree')
        out = a.keep
        os.makedirs(out, exist_ok=True)
    else:
        out = tempfile.mkdtemp(prefix='chiplock_slice_')
    scope = json.load(open(os.path.join(HERE, 's1_scope.json')))
    scope['transforms'] = [t for t in scope['transforms'] if t['id'] != 'T-S5 fifoA']
    n2_scope = os.path.join(out, 'scope_without_fifoA.json')
    json.dump(scope, open(n2_scope, 'w'), indent=1)
    common = ['--capture', cap, '--rom', rom, '--runner', runner]
    runs = [('release', ['--new', new['release'], '--ref', refs['release'], '--to', str(a.to), '--synth-at', '3600', '--af-unit',
                         '--tail'], 0, None),
            ('test', ['--new', new['test'], '--ref', refs['test'], '--test', '--to', '1000'], 0, None),
            ('consoles', ['--consoles', '--new', new['release'], '--ref', refs['release'], '--to', '400'], 0, None),
            ('n1', ['--new', new['bug_disp1'], '--ref', refs['release'], '--to', '400'], 1, 'regwrites'),
            ('n2', ['--new', new['release'], '--ref', refs['release'], '--to', '400', '--scope', n2_scope], 1, 'regwrites'),
            ('n3', ['--new', new['release'], '--ref', refs['release'], '--to', '400', '--plant', 'stored@300'], 1, 'stored'),
            ('n4', ['--new', new['release'], '--ref', refs['release'], '--to', '400', '--plant', 'fe4@300'], 1, 'fe4_view'),
            ('n5', ['--new', new['bug_spr1'], '--ref', refs['release'], '--to', '1700'], 1, 'sprite_chip'),
            ('n6', ['--new', new['bug_spr2'], '--ref', refs['release'], '--to', '400', '--af-unit'], 1, 'sprite_chip'),
            ('n7', ['--new', new['bug_spr3'], '--ref', refs['release'], '--to', '400', '--af-unit'], 1, 'af_unit'),
            ('n8', ['--new', new['bug_spr4'], '--ref', refs['release'], '--to', '400', '--af-unit'], 1, 'sprite_chip'),
            ('n9', ['--new', new['bug_spr5'], '--ref', refs['release'], '--to', '1100'], 1, 'sprite_chip'),
            ('n10', ['--new', new['bug_spr6'], '--ref', refs['release'], '--to', '2300'], 1, 'sprite_chip'),
            ('n11', ['--new', new['bug_spr7'], '--ref', refs['release'], '--to', '12000'], 1, 'sprite_chip')]
    bad = 0
    for name, extra, want, kind in runs:
        od = os.path.join(out, name)
        r = subprocess.run(PY + [os.path.join(HERE, 'chiplock_s1.py'), od] + common + extra, capture_output=True, text=True)
        ok = r.returncode == want
        if ok and kind:
            try:
                ok = kind in json.load(open(os.path.join(od, 'summary.json')))['failures_by_kind']
            except (OSError, ValueError, KeyError):
                ok = False
        last = (r.stdout.strip().splitlines() or [''])[-1]
        print('%-4s %-8s exit %d (want %d%s): %s' % ('ok' if ok else 'BAD', name, r.returncode, want,
                                                    ', ' + kind if kind else '', last[:160]))
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
