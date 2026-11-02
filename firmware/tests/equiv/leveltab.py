#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""leveltab.py - stage 3: the song engine's level table T of a BUILT stage-5 IMAGE, which the firmware builds in working
RAM at power-on (core/tables chip_level_init) instead of holding it in the image, against the table's SHA-256 (the
hash is kept here, not the bytes). Stage numbers are the steps of the 0.3.0 work (README.md, "Terms"): stage 3 the
unpackers, the zoom, the saves and MegaWire; the stage-5 images (FW_S5) carry the song engine.

    python -I -B tests/equiv/leveltab.py --build build/s1/pocket88k/s5release [--negative]

Checks (each must hold):
  1. the generator: core/tables/gen_chip_tables.py level_table(), as 512 little-endian u16, hashes to LEVEL_T_SHA256;
  2. the image holds no table: chip_level_T is a 1,024-byte object in working RAM (0x80000000-0x8000BFFF), not in IROM;
  3. the image's chip_level_init, run alone in Unicorn (the CPU emulator library) on the image's own code, leaves 1,024
     bytes that hash to LEVEL_T_SHA256;
  4. the image on the board model (tests/equiv/rtlmodel.py, MCU interface v1.3) from power-on to the 68000's release:
     chip_level_T in its RAM hashes to LEVEL_T_SHA256 (the boot builds it before any post can arrive);
  5. with the comparison harness (paths.local.json "harness_dir"): the cart chip's own table in its RAM after its C6
     (1,024 bytes) hashes to LEVEL_T_SHA256.
--negative: the planted image s5release_bug_lvl (a wrong rounding), rebuilt with tools/fwbuild.py, must fail check 3.
Exit 0 = PASS, 1 = FAIL, 2 = setup error. The last line printed is 'RESULT: ...'."""
import argparse, hashlib, json, os, struct, subprocess, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

LEVEL_T_SHA256 = '25b62083bc5a90a0864315d33c067c9d61bacde56f4c8953e8b137585ec296b4'
CHIP_LEVEL_T = 0x2000D71C                   # the chip's table in its RAM
WRAM = (0x80000000, 0x8000C000)


def setup_error(msg):
    print('RESULT: setup error: ' + msg)
    sys.exit(2)


def syms(img):
    s = {}
    for ln in open(os.path.join(img, 'main.nm')):
        p = ln.split()
        if len(p) >= 4:
            s[p[-1]] = (int(p[0], 16), int(p[1], 16))
        elif len(p) == 3:
            s[p[-1]] = (int(p[0], 16), 0)
    return s


def run_init(img):
    """chip_level_init alone on the image's own code (Unicorn RV32: IROM and WRAM from main.elf's load segments)"""
    from unicorn import Uc, UC_ARCH_RISCV, UC_MODE_RISCV32
    from unicorn import riscv_const as RC
    s = syms(img)
    for need in ('chip_level_init', 'chip_level_T', '__global_pointer$'):
        if need not in s:
            setup_error('symbol %s missing in %s' % (need, img))
    E = open(os.path.join(img, 'main.elf'), 'rb').read()
    u = Uc(UC_ARCH_RISCV, UC_MODE_RISCV32)
    u.mem_map(0x00000000, 0x20000)
    u.mem_map(WRAM[0], WRAM[1] - WRAM[0])
    phoff, = struct.unpack_from('<I', E, 28)
    phsz, phn = struct.unpack_from('<HH', E, 42)
    for i in range(phn):
        t, off, va, pa, fs, ms, fl, al = struct.unpack_from('<8I', E, phoff + i * phsz)
        if t == 1 and fs and (va < 0x20000 or WRAM[0] <= va < WRAM[1]):
            u.mem_write(va, E[off:off + fs])
    a, n = s['chip_level_T']
    u.mem_write(a, b'\x5A' * 1024)           # not zero: every entry must be written
    u.mem_write(0x1FFF0, struct.pack('<I', 0x0000006F))
    u.reg_write(RC.UC_RISCV_REG_SP, 0x8000BDF0)
    u.reg_write(RC.UC_RISCV_REG_RA, 0x1FFF0)
    u.reg_write(RC.UC_RISCV_REG_GP, s['__global_pointer$'][0])
    u.emu_start(s['chip_level_init'][0], 0x1FFF0, count=2_000_000)
    return bytes(u.mem_read(a, 1024))


def run_boot(img, rom):
    """the image on the board model from power-on to the 68000's release; chip_level_T's bytes then"""
    import rtlmodel
    b = rtlmodel.Board(img, rom, opt=0, seed=1, save=bytes([0xFF]) * 0x2000)
    if not b.run_to('brd_boot', 400_000_000):
        setup_error('the image did not reach brd_boot')
    k = 0
    while b.ctrl & 1:
        b.take()
        b.step(400)
        k += 1
        if k > 2_000_000:
            setup_error('the 68000 was never released')
    a = b.sym['chip_level_T'][0]
    return bytes(b.uc.mem_read(a, 1024))


def h(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default=os.path.join(ROOT, 'build', 's1', 'pocket88k', 's5release'))
    ap.add_argument('--negative', action='store_true')
    a = ap.parse_args()
    lp = os.path.join(ROOT, 'paths.local.json')
    loc = json.load(open(lp)) if os.path.exists(lp) else {}
    if not os.path.exists(os.path.join(a.build, 'main.nm')):
        setup_error('no built image at %s' % a.build)
    if a.negative:
        base = os.path.dirname(os.path.normpath(a.build))
        rr = subprocess.run([sys.executable, '-I', '-B', os.path.join(ROOT, 'tools', 'fwbuild.py'), 's1', '--images-only',
                             '--out', os.path.dirname(os.path.dirname(base)), '--variant', 's5release_bug_lvl'],
                            capture_output=True, text=True)
        if rr.returncode:
            setup_error('building s5release_bug_lvl failed:\n%s' % (rr.stdout + rr.stderr)[-2000:])
        got = run_init(os.path.join(base, 's5release_bug_lvl'))
        caught = h(got) != LEVEL_T_SHA256
        print('%-4s s5release_bug_lvl: chip_level_init\'s table hashes to %s (%s)' % (
            'PASS' if caught else 'FAIL', h(got)[:16], 'differs, caught' if caught else 'the same: NOT caught'))
        print('RESULT: %s' % ('PASS' if caught else 'FAIL'))
        sys.exit(0 if caught else 1)
    ok = True
    sys.path.insert(0, os.path.join(ROOT, 'core', 'tables'))
    import gen_chip_tables
    ref = struct.pack('<512H', *gen_chip_tables.level_table())
    r1 = h(ref) == LEVEL_T_SHA256
    print('%-4s 1 the formula\'s table (gen_chip_tables level_table, 60 digits) hashes to %s' % ('PASS' if r1 else 'FAIL', h(ref)[:16]))
    s = syms(a.build)
    adr, n = s.get('chip_level_T', (0, 0))
    r2 = n == 1024 and WRAM[0] <= adr < WRAM[1]
    print('%-4s 2 chip_level_T is a %d-byte object at 0x%08X (working RAM: %s); the image holds no table' % (
        'PASS' if r2 else 'FAIL', n, adr, WRAM[0] <= adr < WRAM[1]))
    got = run_init(a.build)
    r3 = h(got) == LEVEL_T_SHA256
    print('%-4s 3 the image\'s chip_level_init leaves a table hashing to %s%s' % (
        'PASS' if r3 else 'FAIL', h(got)[:16], '' if r3 else ' (%d of 512 entries differ)' % sum(
            1 for i in range(512) if got[2 * i:2 * i + 2] != ref[2 * i:2 * i + 2])))
    romf = (loc.get('refs') or {}).get('rom') or (loc.get('equiv') or {}).get('rom')
    if not romf or not os.path.exists(romf):
        setup_error('paths.local.json refs.rom (the player\'s ROM, for the board model\'s boot)')
    bt = run_boot(a.build, open(romf, 'rb').read())
    r4 = h(bt) == LEVEL_T_SHA256
    print('%-4s 4 after the boot on the board model (the 68000 released) the table in RAM hashes to %s' % (
        'PASS' if r4 else 'FAIL', h(bt)[:16]))
    ok = r1 and r2 and r3 and r4
    hd = os.environ.get('PAPRIUM_HARNESS_DIR') or loc.get('harness_dir')
    if hd and os.path.isdir(hd):
        sys.path.insert(0, hd)
        from harness import ChipSide
        c = ChipSide()
        ct = bytes(c.m.mu.mem_read(CHIP_LEVEL_T, 1024))
        r5 = h(ct) == LEVEL_T_SHA256
        print('%-4s 5 the cart chip\'s own table after its C6 (RAM 0x%08X) hashes to %s' % ('PASS' if r5 else 'FAIL', CHIP_LEVEL_T, h(ct)[:16]))
        ok = ok and r5
    else:
        print('SKIP 5 the cart chip\'s own table (no paths.local.json "harness_dir")')
    print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
