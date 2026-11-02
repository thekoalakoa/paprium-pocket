#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""c6sprite.py - test build S3a (a firmware build B Jam tested on his hardware): C6's sprite part of a BUILT stage-5
image (FW_S5, our own song engine) (interim/s1/bodies_s1.c job_setup, core/sprite
spr_c6_begin / spr_c6_count) against the cart chip's state after C6.

    python -I -B tests/equiv/c6sprite.py --build build/s1/pocket88k/s5test

Sides:
  ours  the image on rtlmodel.py's board (test build 5's) through the solo capture's boot to the game's C6 exit
        (tests/equiv/c6count.py run(), its board kept): the anims-per-object table SPR.frames (H+$404, 256 B), the block
        directory SPR.blkdir_bus / blkdir (H+$504 / $508), the anim container in the workspace at C6_ANIM_WS for 512 KB;
  chip  the cart program in the audit harness (our test harness outside this tree; paths.local.json "harness_dir":
        harness.ChipSide, its boot snapshot after C6): 0x2000FF20 (256
        B), 0x20010020 / 0x20010024, its SDRAM 0xC0000000 for 512 KB.
Checked: the 256 table bytes equal, the directory equal, the container's 518,174 bytes equal, and the game's boot count
byte 94 (the C6 hold: c6count's own check). Exit 0 = PASS, 1 = FAIL, 2 = setup error. The results are measured (both
sides run their own code; the board model's timing is c6count's)."""
import argparse, json, os, struct, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
C6_ANIM_WS = 0x11800             # interim/s1/bodies_s1.c (the workspace place of the anim container)
CONTAINER = 518174               # the game's anim container's decoded length (measured when the unpacking was built)


def setup_error(msg):
    print('RESULT: setup error: ' + msg)
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default=os.path.join(ROOT, 'build', 's1', 'pocket88k', 's5test'))
    a = ap.parse_args()
    lp = os.path.join(ROOT, 'paths.local.json')
    loc = json.load(open(lp)) if os.path.exists(lp) else {}
    hd = os.environ.get('PAPRIUM_HARNESS_DIR') or loc.get('harness_dir')
    eq = loc.get('equiv', {})
    cap, romf = eq.get('capture_solo'), eq.get('rom')
    if not hd or not os.path.isdir(hd) or not cap or not romf or not os.path.exists(cap) or not os.path.exists(romf):
        setup_error('paths.local.json "harness_dir" and "equiv" capture_solo / rom')
    if not os.path.exists(os.path.join(a.build, 'main.nm')):
        setup_error('no built image at %s' % a.build)
    sys.path.insert(0, hd)
    import c6count   # noqa: E402
    import rtlmodel  # noqa: E402
    held = {}

    class B(rtlmodel.Board):
        def __init__(self, *k, **kw):
            super().__init__(*k, **kw)
            held['b'] = self
    c6count.Board = B
    rom = open(romf, 'rb').read()
    r = c6count.run(a.build, rom, c6count.boot_records(cap), 1, 'capture')
    b = held['b']
    if 'SPR' not in b.sym:
        setup_error('symbol SPR missing')
    spr = b.sym['SPR'][0]
    o_frames = bytes(b.uc.mem_read(spr + 0x404, 256))
    o_bus, o_dir = struct.unpack('<2I', bytes(b.uc.mem_read(spr + 0x504, 8)))
    o_anim = bytes(b.uc.mem_read(rtlmodel.SDRAM + C6_ANIM_WS, 0x80000))
    from harness import ChipSide
    mu = ChipSide().m.mu
    c_frames = bytes(mu.mem_read(0x2000FF20, 256))
    c_bus, c_dir = struct.unpack('<2I', bytes(mu.mem_read(0x20010020, 8)))
    c_anim = bytes(mu.mem_read(0xC0000000, 0x80000))
    n = struct.unpack_from('<H', c_anim, 0)[0]
    fd = [i for i in range(256) if o_frames[i] != c_frames[i]]
    dirs = (o_bus, o_dir & ~1) == (c_bus, c_dir & ~1)
    ad = [i for i in range(0, CONTAINER, 2) if o_anim[i:i + 2] != c_anim[i:i + 2]]
    print('c6sprite %s: the game\'s boot count byte %s; the chip\'s container names %d objects' % (
        os.path.basename(os.path.normpath(a.build)), r.get('byte'), n))
    print('%-4s anims per object: %d of 256 bytes differ %s (nonzero: ours %d, chip %d)' % (
        'PASS' if not fd else 'FAIL', len(fd), fd[:8], sum(1 for x in o_frames if x), sum(1 for x in c_frames if x)))
    print('%-4s block directory: ours %#x / %#x, chip %#x / %#x' % ('PASS' if dirs else 'FAIL', o_bus, o_dir, c_bus, c_dir))
    print('%-4s the anim container: %d of %d halfwords differ%s' % ('PASS' if not ad else 'FAIL', len(ad), CONTAINER // 2,
                                                                   (' (first at %#x)' % ad[0]) if ad else ''))
    print('%-4s the C6 hold: count byte %s (want 94)' % ('PASS' if r.get('byte') == 94 else 'FAIL', r.get('byte')))
    ok = not fd and dirs and not ad and r.get('byte') == 94 and n == 241
    print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
