#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""f83lock.py - test build S3a (a firmware build B Jam tested on his hardware): 83's frame-period check of a BUILT
stage-5 IMAGE (FW_S5, our own song engine; core/dispatch/disp.c disp_83_check) against the cart chip's own routine at
0x080209B4, both in Unicorn (the CPU emulator library).

    python -I -B tests/equiv/f83lock.py --build build/s1/pocket88k/s5release
    python -I -B tests/equiv/f83lock.py --build build/s1/pocket88k/s5release --negative

Sides:
  chip  the cart program in the audit harness (our test harness outside this tree; paths.local.json "harness_dir":
        harness.ChipSide, its boot
        snapshot after C6; read in place): 0x080209B4(0) with SysTick VAL = V0, then 0x080209B4(n) with VAL = V0 minus the
        elapsed time in 96 MHz ticks (a 24-bit down counter, so the elapsed time wraps); the HSI trim it calls inside a
        window (0x08020864) and its delay (0x08020880) return at once (the chip's own clock plumbing, not reproduced:
        allow-list B12), their calls counted.
  ours  the image's disp_83_check (main.elf / main.nm) in Unicorn RV32, the board TIMER (FPGAIO slot 10) set to T0, then
        T0 plus the same time in cycles at BRD_CLK_HZ (53,693,175 Hz).
Cases: every n from 1 to 15 x frame periods half a microsecond either side of each window end (15,489 / 17,888 /
18,621 / 21,620 us), the two targets, and periods outside both (14,000, 18,000, 25,000 us): 195 cases; n x period
passes the chip's 24-bit wrap (174,762.7 us) from n = 7 on (76 cases), so the wrap is covered. The accept / refuse result must be equal in
every case. --negative: the planted RELEASE images s5release_bug_83a (no wrap) and s5release_bug_83b (window A one
microsecond longer), rebuilt with tools/fwbuild.py, must each differ from the chip in at least one case.
Exit 0 = PASS, 1 = FAIL, 2 = setup error. The last line printed is 'RESULT: ...'."""
import argparse, json, os, struct, subprocess, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

F_83, F_TRIM, F_DELAY = 0x080209B4, 0x08020864, 0x08020880
TIMER = 0x01000028
CLK = 53693175
NS = tuple(range(1, 16))
PERIODS = (14000.0, 15488.5, 15489.5, 16688.0, 17887.5, 17888.5, 18000.0, 18620.5, 18621.5, 20120.0, 21619.5, 21620.5,
           25000.0)
NEG = ['s5release_bug_83a', 's5release_bug_83b']


def setup_error(msg):
    print('RESULT: setup error: ' + msg)
    sys.exit(2)


class Chip:
    def __init__(self):
        from harness import ChipSide
        from unicorn import UC_HOOK_CODE
        from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC
        self.c = ChipSide()
        self.m = self.c.m
        self.stubbed = {F_TRIM: 0, F_DELAY: 0}

        def skip(uc, addr, size, ud):
            a = addr & ~1
            if a in self.stubbed:
                self.stubbed[a] += 1
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
        for a in (F_TRIM, F_DELAY):
            self.m.mu.hook_add(UC_HOOK_CODE, skip, begin=a, end=a + 1)

    def check(self, n, ticks, v0=0x800000):
        st = self.m.systick
        st['next'] = None
        st['VAL'] = v0
        self.m.call(F_83, (0,))
        st['VAL'] = (v0 - ticks) & 0xFFFFFF
        return self.m.call(F_83, (n,)) & 0xFFFFFFFF


class Ours:
    def __init__(self, img):
        from unicorn import Uc, UC_ARCH_RISCV, UC_MODE_RISCV32
        E = open(os.path.join(img, 'main.elf'), 'rb').read()
        self.sym = {}
        for ln in open(os.path.join(img, 'main.nm')):
            p = ln.split()
            if len(p) >= 3:
                self.sym[p[-1]] = int(p[0], 16)
        for need in ('disp_83_check', '__global_pointer$'):
            if need not in self.sym:
                setup_error('symbol %s missing in %s' % (need, img))
        u = self.u = Uc(UC_ARCH_RISCV, UC_MODE_RISCV32)
        u.mem_map(0x00000000, 0x20000)
        u.mem_map(0x80000000, 0xC000)
        u.mem_map(0x01000000, 0x1000)
        phoff, = struct.unpack_from('<I', E, 28)
        phsz, phn = struct.unpack_from('<HH', E, 42)
        for i in range(phn):
            t, off, va, pa, fs, ms, fl, al = struct.unpack_from('<8I', E, phoff + i * phsz)
            if t == 1 and fs and (va < 0x20000 or 0x80000000 <= va < 0x8000C000):
                u.mem_write(va, E[off:off + fs])
        u.mem_write(0x1FFF0, struct.pack('<I', 0x0000006F))

    def call(self, n, timer):
        from unicorn import riscv_const as RC
        u = self.u
        u.mem_write(TIMER, struct.pack('<I', timer & 0xFFFFFFFF))
        u.reg_write(RC.UC_RISCV_REG_SP, 0x8000BFF0)
        u.reg_write(RC.UC_RISCV_REG_RA, 0x1FFF0)
        u.reg_write(RC.UC_RISCV_REG_GP, self.sym['__global_pointer$'])
        u.reg_write(RC.UC_RISCV_REG_A0, n)
        u.emu_start(self.sym['disp_83_check'], 0x1FFF0, count=100000)
        return u.reg_read(RC.UC_RISCV_REG_A0)

    def check(self, n, cycles, t0=0x12345678):
        self.call(0, t0)
        return self.call(n, t0 + cycles)


def sweep(chip, ours, out):
    res = {'cases': 0, 'equal': 0, 'accepted': 0, 'wrapped': 0, 'differ': []}
    for n in NS:
        for p in PERIODS:
            us = p * n
            ticks = int(round(us * 96))
            cyc = int(round(us * CLK / 1e6))
            a, b = chip.check(n, ticks), ours.check(n, cyc)
            res['cases'] += 1
            res['wrapped'] += ticks >= 1 << 24
            if (a != 0) == (b != 0):
                res['equal'] += 1
                res['accepted'] += a != 0
            else:
                res['differ'].append('n %d period %.1f us: chip %d ours %d' % (n, p, a, b))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default=os.path.join(ROOT, 'build', 's1', 'pocket88k', 's5release'))
    ap.add_argument('--negative', action='store_true')
    a = ap.parse_args()
    lp = os.path.join(ROOT, 'paths.local.json')
    loc = json.load(open(lp)) if os.path.exists(lp) else {}
    hd = os.environ.get('PAPRIUM_HARNESS_DIR') or loc.get('harness_dir')
    if not hd or not os.path.isdir(hd):
        setup_error('paths.local.json "harness_dir" (the audit harness) missing')
    if not os.path.exists(os.path.join(a.build, 'main.nm')):
        setup_error('no built image at %s' % a.build)
    sys.path.insert(0, hd)
    chip = Chip()
    if not a.negative:
        r = sweep(chip, Ours(a.build), print)
        for d in r['differ']:
            print('DIFFER ' + d)
        print('f83lock %s: %d cases (%d past the 24-bit wrap), %d equal (%d accepted by both), %d differ; the chip trimmed '
              '%d times, its delay %d times (stubbed)' % (os.path.basename(a.build), r['cases'], r['wrapped'], r['equal'],
                                                          r['accepted'], len(r['differ']), chip.stubbed[F_TRIM],
                                                          chip.stubbed[F_DELAY]))
        ok = r['cases'] == len(NS) * len(PERIODS) and not r['differ'] and 0 < r['accepted'] < r['cases'] and r['wrapped']
        print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
        sys.exit(0 if ok else 1)
    base = os.path.dirname(a.build)
    cmd = [sys.executable, '-I', '-B', os.path.join(ROOT, 'tools', 'fwbuild.py'), 's1', '--images-only',
           '--out', os.path.dirname(os.path.dirname(base))]
    for v in NEG:
        cmd += ['--variant', v]
    rr = subprocess.run(cmd, capture_output=True, text=True)
    if rr.returncode:
        setup_error('building %s failed:\n%s' % (NEG, (rr.stdout + rr.stderr)[-2000:]))
    ok = True
    for v in NEG:
        r = sweep(chip, Ours(os.path.join(base, v)), print)
        caught = bool(r['differ'])
        print('%-4s %s: %d of %d cases differ from the chip%s' % ('PASS' if caught else 'FAIL', v, len(r['differ']),
                                                                 r['cases'], (' (e.g. %s)' % r['differ'][0]) if caught else ''))
        ok &= caught
    print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
