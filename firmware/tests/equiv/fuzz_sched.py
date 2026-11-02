#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""fuzz_sched.py - the stage-1 scheduler on its RV32 image, under a model of MCU interface v1.0, with the 68000 side
played by the rig and interrupts taken at random instruction boundaries (fuzz_s1.py extends it to the full images).
The stage-1 scheduler is the one of our new firmware (FW_S1; core/sched/sched.h describes its levels L1, L2a, L2b,
L2c and the thread); FZ5, FZ7, FZ8, FZ9 and FZ11 are this rig's named checks (docs/STAGE1_PLAN.md section 4.7).

    python -I -B tests/equiv/fuzz_sched.py [--build build/s1/pocket72k/probe] [--seeds N] [--cycles C] [--json OUT]
    python -I -B tests/equiv/fuzz_sched.py --negative        (every planted-bug probe must FAIL; the clean probe PASS)
    python -I -B tests/equiv/fuzz_sched.py --boot-checks     (crt0's interface checks: SYSINFO_CLK and USER_CODE)

The image is a stage-1 "probe" build (fwbuild.json s1.pocket.variants: the scheduler + tests/s1/sched_probe.c).
Board model (a model written from docs/MCU_INTERFACE.md v1.0;
a section number in parentheses is where the page says it):
  IROM 72 KB read-only (a store faults), WRAM 48 KB (wcode.bin at 0x2C00; a store into the locked window 0x2C00-0x6BFF
  or past 48 KB is a violation), RAMDP 8 KB, SDRAM 2 MB. Anything else unmapped: an access is a violation.
  FPGAIO slots by addr[6:2] (section 4): CTRL (HOLD tracked), CAUSE {V,S,A,B} W1C with set-wins, MSIP, TIMER, TCMP,
  TCTRL, STAMP_B, GO/SPTR (stored), WLOCK; retired / reserved slots read 0xFFFFFFFF.  Register file 0x0B000000 (section
  3.4): $1FE4/6/A/C stored, the rest read 0.  NEORV32 IO: GPIO (options, 0), SYSINFO CLK / USER_CODE; MTIME / UART / WDT
  addresses are removed in v1.0: any access is a violation (section 2).
  Interrupts (as read in neorv32_cpu_control.vhd, lines 1389-1446): per line a latch buf = mie_bit & (buf | line),
  cleared for the line taken; taken when mstatus.MIE and any buf,
  MEI > MTI > MSI; trap entry = mepc, mcause, MPIE <- MIE, MIE <- 0,
  MPP = M, pc <- mtvec. The latch is updated at every checkpoint, after every instruction that writes mie, and when an
  MMIO write raises a line, so the 1.4.8.1 re-latch after an acknowledge is modelled (docs/MCU_INTERFACE.md finding 5).
  Time: TIMER = cycles; each executed instruction counts CPI = 6 cycles (estimated: the measured NEORV32 table gives
  4-12 a class); a run is cut into segments of 1-48 instructions at random; checkpoints sit between segments, where
  the 68000 side acts and interrupts are taken.
The 68000 side: mailbox B posts (bit 15 set; bit 14 = an engine post, held while the tick runs; bit 0 = the probe
queues one job for L2c, raising MSI), each waiting for the MCU's $1FEA := 0; mailbox A posts (0x9494 starts
the probe's synthetic tick, finished by the tick tail's $1FEC := 0; 0x80A0 is finished at once), each waiting for
$1FEC := 0; SEND events (CAUSE.S), some right before a 0x9494 so that a brain call (the thread's since 2026-10-15) runs
when the tick starts.

Invariants (docs/STAGE1_PLAN.md section 4.7):
  FZ5  no post lost: every post dispatched exactly once, in order per mailbox, every post finished, the MCU reads a
       mailbox only after acknowledging its CAUSE bit, every SEND followed by a brain call; no finish write without an
       outstanding post.
  FZ7  wherever MIE = 1: the $1FE6 register == the probe's shadow == the parity of the three writers' counts (a lost
       or torn read-modify-write shows).
  FZ8  in the probe's log, no engine post is dispatched between a TICK_START and its TICK_END; every engine post held
       by a tick is dispatched after that tick's TAIL (ordering among several held posts is the host test's: the
       68000 protocol leaves at most one held post per tick).
  FZ9  every tick ends within CLK_URGENT + slices x slice cycles + 24,000 cycles of its start (24k estimated for L1 and
       trap work), even with a 150k-cycle brain call running (since 2026-10-15 the call is the thread's, below L2b, so
       the bound holds without the urgent promotion; the planted bug is a call that masks MSI and MTI).
  FZ11 the stack fill word at the stack floor is intact; the high-water depth (measured) <= fwstack's static bound
       for the image.
  plus: no violation (fault, removed IO, a store into the code window), the boot reached the scheduler.
Exit 0 = PASS, 1 = FAIL (or, with --negative, a planted bug that passed), 2 = setup error."""
import argparse, json, os, random, re, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
from unicorn import Uc, UcError, UC_ARCH_RISCV, UC_MODE_RISCV32, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, \
    UC_HOOK_MEM_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED, UC_PROT_READ, UC_PROT_EXEC, UC_PROT_ALL   # noqa: E402
from unicorn import riscv_const as RC   # noqa: E402

CPI = 6
NTSC = 53693175
FIO, FREG, RAMDP, SDRAM, WRAM, IOPAGE = 0x01000000, 0x0B000000, 0x02000000, 0x03000000, 0x80000000, 0xFFFFF000
CLK_URGENT = (737500 * NTSC + 500000000) // 1000000000          # board/clock.h CLK_URGENT at the probe's clock
SLACK = 24000
LG = {1: 'DISPATCH', 2: 'TICK_START', 3: 'TICK_END', 4: 'BRAIN_START', 5: 'BRAIN_END', 6: 'WHEEL', 7: 'TAIL'}
S1_STACK_FILL = 0x5AC3A55A


def nm(path):
    out = {}
    for ln in open(path):
        p = ln.split()
        if len(p) == 4:
            out[p[3]] = (int(p[0], 16), int(p[1], 16))
        elif len(p) == 3:
            out[p[2]] = (int(p[0], 16), 0)
    return out


class Stop(Exception):
    pass


class Rig:
    def __init__(self, build, seed, cycles, cfg=None, sysinfo_clk=NTSC, user_code=0x50490102, quiet=True, feat=0x0048001B):
        self.build, self.seed, self.cycles, self.quiet = build, seed, cycles, quiet
        self.rnd = random.Random(seed)
        self.sym = nm(os.path.join(build, 'main.nm'))
        self.sysinfo_clk, self.user_code, self.feat = sysinfo_clk, user_code, feat   # feat: slot 23 on a v1.3 board
        self.violations, self.notes = [], []
        self.time = 0
        self.tread = 0
        # board state
        self.cause, self.msip, self.tcmp, self.ten, self.stamp_b = 0, 0, 0, 0, 0
        self.ctrl, self.sptr, self.go, self.wlock = 0x09, 0, 0, 0
        self.freg = {0x04: 0, 0x06: 0, 0x0A: 0, 0x0C: 0}
        self.buf = {11: 0, 7: 0, 3: 0}
        self.taken = {11: 0, 7: 0, 3: 0}
        # 68000 side
        self.b = None          # outstanding post dict
        self.a = None
        self.posts, self.sends = [], []
        self.seq = 0
        self.next_a = 40000
        self.unacked = {0: False, 1: False}
        self.fe6_checks = 0
        self.p_send = self.rnd.choice((0.0005, 0.002, 0.006))   # per checkpoint: rare, frequent, back-to-back calls
        u = self.uc = Uc(UC_ARCH_RISCV, UC_MODE_RISCV32)
        rom = open(os.path.join(build, 'img', 'rom.bin'), 'rb').read()
        u.mem_map(0, 0x12000, UC_PROT_READ | UC_PROT_EXEC)
        u.mem_write(0, rom)
        u.mem_map(WRAM, 0xC000, UC_PROT_ALL)
        u.mem_write(WRAM + 0x2C00, open(os.path.join(build, 'img', 'wcode.bin'), 'rb').read())
        u.mem_map(RAMDP, 0x2000, UC_PROT_ALL)
        u.mem_map(SDRAM, 0x200000, UC_PROT_ALL)
        u.mmio_map(FIO, 0x1000, self.fio_r, None, self.fio_w, None)
        u.mmio_map(FREG, 0x1000, self.freg_r, None, self.freg_w, None)
        u.mmio_map(IOPAGE, 0x1000, self.io_r, None, self.io_w, None)
        # since test build 4b (a firmware build B Jam tested on his hardware): crt0's boot-cache stub reads XLINK CACHE
        # (0x0A000040): VALID | the image size here (the warm path: the boot cache is
        # tests/equiv/cache4b.py's), BAR (0x48) reads 0; writes are ignored. The probe never reads it
        u.mmio_map(0x0A000000, 0x1000, lambda uc, off, size, ud: 0x80152100 if (off & 0x7C) == 0x40 else 0, None,
                   lambda uc, off, size, value, ud: None, None)
        u.hook_add(UC_HOOK_MEM_UNMAPPED | UC_HOOK_MEM_FETCH_UNMAPPED, self.unmapped)
        u.hook_add(UC_HOOK_MEM_WRITE, self.window_w, begin=WRAM + 0x2C00, end=WRAM + 0x6BFF)
        # instructions that write mie: the CPU latch is re-evaluated right after each
        self.mie_hooks = 0
        for ln in open(os.path.join(build, 'main.dis')):
            m = re.match(r'^\s*([0-9a-f]+):\t[0-9a-f]+\s*\tcsrr?[swc]i?\t(?:[a-z0-9]+,)?mie,', ln)
            if m:
                a = int(m.group(1), 16) + 4
                u.hook_add(UC_HOOK_CODE, self.mie_written, begin=a, end=a)
                self.mie_hooks += 1
        self.knob_hook = None
        self.cfg_brain = cfg[3] if cfg else 0
        if cfg is not None and 'brd_boot' in self.sym:
            a = self.sym['brd_boot'][0]
            self.knob_hook = u.hook_add(UC_HOOK_CODE, self.set_knobs, user_data=cfg, begin=a, end=a)

    # ---------------------------------------------------------------------------------------------- memory model
    def viol(self, what):
        if len(self.violations) < 40:
            self.violations.append('t=%d pc=%#x %s' % (self.time, self.uc.reg_read(RC.UC_RISCV_REG_PC), what))

    def unmapped(self, uc, access, addr, size, value, ud):
        self.viol('unmapped access %#x (size %d)' % (addr, size))
        return False

    def window_w(self, uc, access, addr, size, value, ud):
        self.viol('store into the locked code window %#x' % addr)

    def now(self):
        self.tread = max(self.tread + 1, self.time)
        return self.tread & 0xFFFFFFFF

    def lines(self):
        mti = self.ten and ((self.time - self.tcmp) & 0xFFFFFFFF) < 0x80000000
        return {11: 1 if self.cause & 0xF else 0, 7: 1 if mti else 0, 3: 1 if self.msip else 0}

    def latch(self):
        mie = self.uc.reg_read(RC.UC_RISCV_REG_MIE)
        L = self.lines()
        for k in self.buf:
            self.buf[k] = 1 if ((mie >> k) & 1) and (self.buf[k] or L[k]) else 0

    def mie_written(self, uc, addr, size, ud):
        self.latch()

    def fio_r(self, uc, off, size, ud):
        slot = (off >> 2) & 31
        if slot == 0:
            return self.ctrl | ((self.cause & 1) << 15)
        if slot == 2:
            return self.sptr
        if slot == 7:
            return self.go
        if slot == 8:
            return self.cause
        if slot == 9:
            return self.msip
        if slot == 10:
            return self.now()
        if slot == 11:
            return self.tcmp
        if slot == 12:
            return self.ten
        if slot == 13:
            return self.stamp_b
        if slot == 15:
            return self.wlock
        if slot == 16 and (self.user_code & 0xFF) >= 1:
            return (self.time // 896040) & 0xFFFF          # v1.1 VSCNT: one VDP frame every 896,040 cycles (NTSC)
        if slot == 23 and (self.user_code & 0xFF) >= 3:
            return self.feat                                # v1.3 FEAT (test build 4a's by
                                                            # default: MCU_INTERFACE.md 4.10)
        if slot == 1:
            self.viol('read of the retired ms counter (slot 1)')
        return 0xFFFFFFFF

    def fio_w(self, uc, off, size, value, ud):
        slot = (off >> 2) & 31
        if slot == 0:
            self.ctrl = value & 0xFF
        elif slot == 2:
            self.sptr = value & 0x1FFFFF
        elif slot == 7:
            self.go = value & 0x1FFFFF
        elif slot == 8:
            if value & 1:
                self.unacked[0] = False
            if value & 2:
                self.unacked[1] = False
            self.cause &= ~value & 0xF
        elif slot == 9:
            self.msip = value & 1
        elif slot == 11:
            self.tcmp = value & 0xFFFFFFFF
        elif slot == 12:
            self.ten = value & 1
        elif slot == 15:
            self.wlock |= value & 0x1FFFFF
        elif slot in (1, 6):
            self.viol('write to FPGAIO slot %d (retired / legacy)' % slot)
        self.latch()

    def freg_r(self, uc, off, size, ud):
        off &= 0x1E
        if off == 0x0A and self.b and self.unacked[0]:
            self.viol('FZ5: mailbox B read before its CAUSE bit was acknowledged')
        if off == 0x0C and self.a and self.unacked[1]:
            self.viol('FZ5: mailbox A read before its CAUSE bit was acknowledged')
        return self.freg.get(off, 0)

    def freg_w(self, uc, off, size, value, ud):
        off &= 0x1E
        value &= 0xFFFF
        if off in self.freg:
            self.freg[off] = value
        if off == 0x0A:
            if value != 0 or self.b is None:
                self.viol('FZ5: $1FEA := %#x with %s' % (value, 'no post outstanding' if self.b is None else 'a non-zero value'))
            else:
                self.b['t_fin'] = self.time
                self.b = None
        elif off == 0x0C:
            if value != 0 or self.a is None:
                self.viol('FZ5: $1FEC := %#x with %s' % (value, 'no post outstanding' if self.a is None else 'a non-zero value'))
            else:
                self.a['t_fin'] = self.time
                self.a = None

    def io_r(self, uc, off, size, ud):
        a = IOPAGE + off
        if a == 0xFFFFFFE0:
            return self.sysinfo_clk
        if a == 0xFFFFFFE4:
            return self.user_code
        if a in (0xFFFFFF80, 0xFFFFFF84) or 0xFFFFFFE8 <= a <= 0xFFFFFFFC:
            return 0
        self.viol('NEORV32 IO read %#x (removed or not built in v1.0)' % a)
        return 0

    def io_w(self, uc, off, size, value, ud):
        a = IOPAGE + off
        if a != 0xFFFFFF84:
            self.viol('NEORV32 IO write %#x (removed or not built in v1.0)' % a)

    def set_knobs(self, uc, addr, size, cfg):
        a = self.sym['probe_cfg'][0]
        for i, v in enumerate(cfg):
            uc.mem_write(a + 4 * i, struct.pack('<I', v))

    def rd32(self, name, k=0):
        return struct.unpack('<I', self.uc.mem_read(self.sym[name][0] + 4 * k, 4))[0]

    # ---------------------------------------------------------------------------------------------- the 68000 side
    def post(self, mbx, word):
        p = dict(mbx=mbx, word=word, t_post=self.time, t_fin=None, seq=len(self.posts))
        self.posts.append(p)
        if mbx == 0:
            self.b = p
            self.freg[0x0A] = word
            self.cause |= 1
            self.stamp_b = self.time & 0xFFFFFFFF
        else:
            self.a = p
            self.freg[0x0C] = word
            self.cause |= 2
        self.unacked[mbx] = True

    def side_68000(self):
        r = self.rnd
        if self.time > self.cycles:
            return
        if self.b is None and r.random() < 0.02:
            self.seq += 1
            self.post(0, 0x8000 | (0x4000 if r.random() < 0.4 else 0) | (self.seq & 0x3FFF))
        if self.a is None and self.time >= self.next_a:
            if r.random() < 0.85:
                if r.random() < 0.35:
                    self.cause |= 4
                    self.sends.append(self.time)
                self.post(1, 0x9494)
            else:
                self.post(1, 0x80A0)
            self.next_a = self.time + r.randint(20000, 90000)
        # B posts come far more often while L2b runs out of work (mie = MEI | MTI is the trap entry's L2b mask; nothing
        # pending, no tick): that is where a lost raise of MSIP would hide (between L2b's last look and its return); a
        # B post with bit 0 queues a job and raises MSI (the brain call raises nothing, it is the thread's)
        ending = (self.uc.reg_read(RC.UC_RISCV_REG_MIE) & 0x888) == 0x880 and not self.rd32('probe_jobs') \
            and not self.rd32('tick_running')
        if ending and self.b is None and r.random() < 0.5:
            self.seq += 1
            self.post(0, 0x8000 | (self.seq & 0x3FFF) | 1)
        if r.random() < self.p_send:
            self.cause |= 4
            self.sends.append(self.time)

    # ---------------------------------------------------------------------------------------------- interrupts
    def take(self):
        uc = self.uc
        self.latch()
        ms = uc.reg_read(RC.UC_RISCV_REG_MSTATUS)
        if not (ms & 8):
            return
        for k in (11, 7, 3):
            if self.buf[k]:
                self.buf[k] = 0
                self.taken[k] += 1
                uc.reg_write(RC.UC_RISCV_REG_MEPC, uc.reg_read(RC.UC_RISCV_REG_PC))
                uc.reg_write(RC.UC_RISCV_REG_MCAUSE, 0x80000000 | k)
                uc.reg_write(RC.UC_RISCV_REG_MSTATUS, (ms & ~0x1888) | ((ms & 8) << 4) | 0x1800)
                uc.reg_write(RC.UC_RISCV_REG_PC, uc.reg_read(RC.UC_RISCV_REG_MTVEC) & ~3)
                self.time += 14                                     # trap entry: 14 cycles, measured (our cycle bench,
                                                                    # docs/MCU_INTERFACE.md section 12 row I2)
                return

    def fz7(self):
        if not (self.uc.reg_read(RC.UC_RISCV_REG_MSTATUS) & 8):
            return
        shadow = struct.unpack('<H', self.uc.mem_read(self.sym['probe_fe6'][0], 2))[0]
        exp = (self.rd32('probe_n_disp') & 1) | ((self.rd32('probe_n_l3') & 1) << 1) | ((self.rd32('probe_n_tail') & 1) << 2)
        self.fe6_checks += 1
        if not (self.freg[0x06] == shadow == exp):
            self.viol('FZ7: $1FE6 %#x, shadow %#x, writers\' parity %#x' % (self.freg[0x06], shadow, exp))
        # FZ5 (no lost work): outside L2b, with interrupts open, pending L2b work (a job, the tick) always has MSIP up
        # (the brain call is the thread's since 2026-10-15: the end-state check below sees every SEND answered)
        if not self.rd32('sched_stats', 20) and not self.msip and (self.rd32('probe_jobs') or
                                                                     (self.rd32('tick_running') and self.rd32('probe_slices_left'))):
            self.viol('FZ5: L2b work pending (jobs %d, tick %d) with MSIP down and L2b not running: a lost raise' % (
                self.rd32('probe_jobs'), self.rd32('tick_running')))

    # ---------------------------------------------------------------------------------------------- run
    def step(self, n):
        uc = self.uc
        pc = uc.reg_read(RC.UC_RISCV_REG_PC)
        try:
            uc.emu_start(pc, 0xFFFFFFF0, count=n)
        except UcError as e:
            self.viol('CPU fault: %s' % e)
            raise Stop()
        self.time = max(self.time + n * CPI, self.tread)
        if self.violations:
            raise Stop()

    def boot(self, limit=400000, until='l3_thread'):
        """from the reset vector until the scheduler's thread loop (or a crt0 stop): no interrupt can be taken yet.
        until='brd_boot': stop where crt0 enters the board boot ('board boot'): crt0's checks passed (the stage-1
        test / release images, whose boot needs the full board model: rvboard.py's stage-1 board mode)"""
        uc = self.uc
        l3 = self.sym[until][0]
        try:
            uc.emu_start(0, l3, count=limit)
        except UcError as e:
            self.viol('CPU fault in the boot: %s' % e)
            raise Stop()
        self.time += limit * CPI if uc.reg_read(RC.UC_RISCV_REG_PC) != l3 else 0
        if uc.reg_read(RC.UC_RISCV_REG_PC) == l3:
            return 'scheduler' if until == 'l3_thread' else 'board boot'
        rec = [self.rd32('s1_boot_rec', k) for k in range(4)]
        return 'stopped code %#x value %#x hold %d' % (rec[1], rec[3], self.ctrl & 1)

    def run(self):
        r = self.rnd
        try:
            where = self.boot()
            if where != 'scheduler':
                self.viol('boot did not reach the scheduler: %s' % where)
                raise Stop()
            rec = [self.rd32('s1_boot_rec', k) for k in range(2)]
            if rec[0] != 0x53314254 or rec[1] != 0x02:
                self.viol('boot record %#x / %#x, wanted the IRQ-on milestone' % tuple(rec))
            if not (self.ctrl & 1):
                self.viol('the 68000 was released by the skeleton boot')
            drain_until = idle_since = None
            while True:
                self.side_68000()
                self.take()
                self.fz7()
                self.step(r.randint(1, 48))
                if self.time > self.cycles:
                    # quiet: nothing outstanding on either side, for longer than the longest brain call
                    idle = self.b is None and self.a is None and not (self.cause & 0xF) and not self.msip \
                        and not self.rd32('tick_running') and not self.rd32('held_n') and not self.rd32('brain_pending') \
                        and not self.rd32('probe_jobs')
                    if not idle:
                        idle_since = None
                    elif idle_since is None:
                        idle_since = self.time
                    elif self.time - idle_since > 2 * self.cfg_brain + 50000:
                        break
                    if drain_until is None:
                        drain_until = self.time + 4000000
                    elif self.time > drain_until:
                        self.viol('FZ5: not idle 4,000,000 cycles after the last 68000 action (B %s, A %s, cause %#x, tick %d, '
                                  'held %d, brain pending %d)' % (self.b, self.a, self.cause, self.rd32('tick_running'),
                                                                  self.rd32('held_n'), self.rd32('brain_pending')))
                        raise Stop()
        except Stop:
            pass
        return self.verdict()

    def verdict(self):
        out = dict(seed=self.seed, time=self.time, posts=len(self.posts), sends=len(self.sends), taken=self.taken,
                   fe6_checks=self.fe6_checks, mie_hooks=self.mie_hooks)
        bad = list(self.violations)
        try:
            n = self.rd32('probe_nlog')
            if self.rd32('probe_nlost'):
                bad.append('probe log overflow (%d lost): run shorter' % self.rd32('probe_nlost'))
            raw = self.uc.mem_read(self.sym['probe_log'][0], 8 * n)
            log = [(w >> 24, w & 0xFFFFFF, t) for w, t in struct.iter_unpack('<II', raw)]
        except Exception as e:      # noqa: BLE001
            bad.append('log unreadable: %s' % e)
            log = []
        # FZ5: dispatch == posts, in order per mailbox, exactly once; all finished; sends -> brain calls (the end-state
        # checks only when the run reached its end: a run stopped by a violation leaves work outstanding by design)
        disp = [(d >> 16, d & 0xFFFF, t) for k, d, t in log if k == 1]
        ended = not self.violations
        for mbx in (0, 1):
            want = [p['word'] for p in self.posts if p['mbx'] == mbx]
            got = [w for m, w, t in disp if m == mbx]
            if want[:len(got)] != got or (ended and want != got):
                bad.append('FZ5: mailbox %s dispatched %d posts, %d posted (first difference at %s)' % (
                    'BA'[mbx], len(got), len(want), next((i for i, (x, y) in enumerate(zip(want, got)) if x != y), min(len(want), len(got)))))
        unf = [p for p in self.posts if p['t_fin'] is None]
        if unf and not self.violations:
            bad.append('FZ5: %d posts never finished (first %s)' % (len(unf), unf[0]))
        bstarts = [t for k, d, t in log if k == 4]
        for ts in (self.sends if ended else []):
            if not any(b >= (ts & 0xFFFFFFFF) for b in bstarts):
                bad.append('FZ5: the SEND at t=%d has no brain call after it' % ts)
                break
        # FZ8: no engine post dispatched while a tick runs; held ones after the tail
        running = False
        for k, d, t in log:
            if k == 2:
                running = True
            elif k == 3:
                running = False
            elif k == 1 and running and (d & 0x4000):
                bad.append('FZ8: engine post %#x dispatched inside a tick (t=%d)' % (d & 0xFFFF, t))
                break
        ticks = []
        cur = None
        for k, d, t in log:
            if k == 2:
                cur = [t, None]
            elif k == 3 and cur:
                cur[1] = t
                ticks.append(cur)
                cur = None
        # FZ9: each tick ends within its deadline
        cfg = [self.rd32('probe_cfg', i) for i in range(6)]
        bound = CLK_URGENT + cfg[1] * cfg[2] + SLACK
        worst = max([e - s for s, e in ticks] or [0])
        late = [(s, e) for s, e in ticks if e - s > bound]
        if late:
            bad.append('FZ9: %d of %d ticks ended late (worst %d cycles, bound %d)' % (len(late), len(ticks), worst, bound))
        # FZ11: the stack
        lo = self.sym['__stack_floor'][0]
        top = self.sym['__crt0_stack_begin'][0]
        words = struct.unpack('<%dI' % ((top - lo) // 4), self.uc.mem_read(lo, top - lo))
        first = next((i for i, w in enumerate(words) if w != S1_STACK_FILL), len(words))
        depth = top - (lo + 4 * first)
        if first == 0:
            bad.append('FZ11: the stack floor word was overwritten')
        sb = json.load(open(os.path.join(self.build, 'stack.json')))
        static = max(s['worst']['bytes'] for s in sb['schemes'] if s['gate'])
        if depth > static:
            bad.append('FZ11: MEASURED stack depth %d B > the static bound %d B' % (depth, static))
        wheel = [d for k, d, t in log if k == 6]
        out.update(ticks=len(ticks), tick_worst=worst, tick_bound=bound, brain_calls=len(bstarts), dispatches=len(disp),
                   stack_depth=depth, stack_bound=static, wheel_runs=len(wheel), wheel_late_max=max(wheel or [0]),
                   held=self.rd32('sched_stats', 8) if 'sched_stats' in self.sym else None,
                   urgent=self.rd32('sched_stats', 12) if 'sched_stats' in self.sym else None,
                   l1_empty=self.rd32('sched_stats', 1) if 'sched_stats' in self.sym else None, bad=bad)
        return out


def run_seeds(build, seeds, cycles, first=1):
    agg = dict(seeds=0, posts=0, sends=0, ticks=0, brain_calls=0, fe6_checks=0, held=0, urgent=0, l1_empty=0,
               tick_worst=0, stack_depth=0, wheel_runs=0, wheel_late_max=0, taken={11: 0, 7: 0, 3: 0})
    fails = []
    for sd in range(first, first + seeds):
        k = random.Random(1000 + sd)
        cfg = [1, k.randint(1, 8), k.choice((500, 2000, 4000)), k.choice((20000, 80000, 150000)), k.choice((3000, 7168, 20000)),
               k.choice((16, 64, 256))]
        rg = Rig(build, sd, cycles, cfg)
        o = rg.run()
        agg['seeds'] += 1
        for k in ('posts', 'sends', 'ticks', 'brain_calls', 'fe6_checks', 'held', 'urgent', 'l1_empty', 'wheel_runs'):
            agg[k] += o.get(k) or 0
        for k in ('tick_worst', 'stack_depth', 'wheel_late_max'):
            agg[k] = max(agg[k], o.get(k) or 0)
        for k in (11, 7, 3):
            agg['taken'][k] += o['taken'][k]
        agg['tick_bound'], agg['stack_bound'] = o.get('tick_bound'), o.get('stack_bound')
        if o['bad']:
            fails.append((sd, o['bad']))
    return agg, fails


def boot_checks(build):
    """crt0's interface checks (docs/MCU_INTERFACE.md sections 1 and 7): the right clock and v1.(>= 2) run on; anything
    else stops, 68000 held. The images are built for v1.2 (the RTL sprite decoder, 2026-10-15), so a v1.1 or v1.0
    bitstream (an older minor: no decoder, no sprite would ever be decoded) stops them"""
    cases = [('NTSC clock, v1.2', NTSC, 0x50490102, 'scheduler'),
             ('NTSC clock, v1.3 (a later minor)', NTSC, 0x50490103, 'scheduler'),
             ('NTSC clock, v1.1 (an older minor)', NTSC, 0x50490101, 'stopped code 0xc2 value 0x50490101 hold 1'),
             ('NTSC clock, v1.0 (an older minor)', NTSC, 0x50490100, 'stopped code 0xc2 value 0x50490100 hold 1'),
             ('PAL clock on an NTSC build', 53203424, 0x50490102, 'stopped code 0xc1 value %#x hold 1' % 53203424),
             ('0.2.6 bitstream (USER_CODE 0)', NTSC, 0x00000000, 'stopped code 0xc2 value 0x0 hold 1'),
             ('major 2', NTSC, 0x50490200, 'stopped code 0xc2 value 0x50490200 hold 1')]
    ok = True
    for name, clk, uc, want in cases:
        rg = Rig(build, 0, 0, None, sysinfo_clk=clk, user_code=uc)
        try:
            got = rg.boot(limit=60000)
        except Stop:
            got = 'fault: %s' % rg.violations
        good = got == want and not rg.violations
        ok &= good
        print('%-4s boot: %-36s -> %s' % ('PASS' if good else 'FAIL', name, got))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default=os.path.join(ROOT, 'build', 's1', 'pocket72k', 'probe'))
    ap.add_argument('--seeds', type=int, default=12)
    ap.add_argument('--first', type=int, default=1)
    ap.add_argument('--cycles', type=int, default=3000000, help='model cycles of 68000 activity per seed')
    ap.add_argument('--negative', action='store_true')
    ap.add_argument('--boot-checks', action='store_true')
    ap.add_argument('--json')
    a = ap.parse_args()
    if not os.path.exists(os.path.join(a.build, 'main.nm')):
        print('SETUP: no probe build at %s (tools/fwbuild.py s1)' % a.build)
        sys.exit(2)
    if a.boot_checks:
        ok = boot_checks(a.build)
        print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
        sys.exit(0 if ok else 1)
    if a.negative:
        base = os.path.dirname(a.build)
        ok = True
        for v, want in (('probe', 'PASS'), ('probe_bug1', 'FZ5'), ('probe_bug2', 'FZ5'), ('probe_bug3', 'FZ8'),
                        ('probe_bug4', 'FZ9'), ('probe_bug5', 'FZ7')):
            agg, fails = run_seeds(os.path.join(base, v), a.seeds, a.cycles, a.first)
            cats = sorted({(re.search(r'FZ\d+', b) or re.search(r'\w+', b)).group(0) for sd, bs in fails for b in bs})
            got = 'PASS' if not fails else ' '.join(cats)
            hit = (want == 'PASS' and not fails) or (want != 'PASS' and fails and want in got)
            ok &= bool(hit)
            print('%-4s %-11s expected %-4s: %d of %d seeds failed  [%s]' % ('PASS' if hit else 'FAIL', v, want, len(fails),
                                                                         agg['seeds'], got[:90]))
        print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
        sys.exit(0 if ok else 1)
    agg, fails = run_seeds(a.build, a.seeds, a.cycles, a.first)
    print('fuzz_sched %s: %d seeds x %d cycles: %d posts, %d SENDs, %d ticks (%d promoted by the urgent slot, worst %d of %s '
          'cycles), %d brain calls, %d held posts, %d FZ7 checks, taken MEI %d MTI %d MSI %d, empty MEI entries %d, '
          'wheel runs %d (latest %d cycles), stack MEASURED %d B of the static %s B' % (
              os.path.basename(a.build), agg['seeds'], a.cycles, agg['posts'], agg['sends'], agg['ticks'], agg['urgent'],
              agg['tick_worst'], agg.get('tick_bound'), agg['brain_calls'], agg['held'], agg['fe6_checks'], agg['taken'][11],
              agg['taken'][7], agg['taken'][3], agg['l1_empty'], agg['wheel_runs'], agg['wheel_late_max'], agg['stack_depth'],
              agg.get('stack_bound')))
    for sd, bs in fails[:6]:
        print('  seed %d: %s' % (sd, '; '.join(bs[:3])))
    if a.json:
        json.dump(dict(agg=agg, fails=fails), open(a.json, 'w'), indent=1)
    print('RESULT: %s' % ('PASS' if not fails else 'FAIL: %d of %d seeds' % (len(fails), agg['seeds'])))
    sys.exit(0 if not fails else 1)


if __name__ == '__main__':
    main()
