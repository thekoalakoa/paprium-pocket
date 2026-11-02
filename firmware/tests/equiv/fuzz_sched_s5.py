#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""fuzz_sched_s5.py - the stage-5 scheduler path (FW_S5, the builds with our own song engine: the ordered engine queue
and the split between the scheduler's levels L1 and L2, core/sched/sched.h) on
its RV32 probe image, under a model of MCU interface v1.3 with the 68000 and the synth played by the rig and the
interrupts taken at random instruction boundaries. The stage-1 rig's FZ5 / FZ7 / FZ8 / FZ9 / FZ11 (tests/equiv/
fuzz_sched.py), redone for stage 5, where FZ8 and FZ9 were vacuous on the stage-1 images (FW_S1, without the song
engine). FZ5, FZ7, FZ8, FZ9 and FZ11 are this rig's named checks.

    python -I -B tests/equiv/fuzz_sched_s5.py [--build build/s1/pocket88k/s5probe] [--seeds N] [--cycles C] [--json OUT]
    python -I -B tests/equiv/fuzz_sched_s5.py --negative     (every planted bug FAILS its check; the clean probe and the
                                                             positive control s5probe_bug6 PASS; three plants run in
                                                             their scenarios (SCEN: long brain calls, A + B pair
                                                             storms, forced urgent finishes), the clean probe too;
                                                             the planted images,
                                                             on-demand variants, are rebuilt first next to --build)

The image is fwbuild.json's s5probe (tests/s1/sched_probe_s5.c over the real core/sched FW_S5, core/song/song_oeq.c and
core/sched/s5_glue.c). Board model (a model written from MCU interface v1.3; the stage-1 rig's v1.0 parts unchanged):
  IROM 88 KB (pocket88k), WRAM 48 KB, RAMDP 8 KB, SDRAM 2 MB; FPGAIO as fuzz_sched.py plus slot 14 STAMP_A (TIMER when
  CAUSE.A was set); the register file; NEORV32 IO; the interrupt
  latch and priorities (as read in neorv32_cpu_control.vhd);
  CPI 6 cycles an instruction, segments of 1-48 instructions with checkpoints between them.
  ARR (3.10.5): every 68000 write of $1FEA / $1FEC is the next arrival n (16 bits); SEQLAT [15:0] B, [31:16] A.
  The synth (region 0x06: SEQ 0x028, DONE 0x02C, STATUS 0x030 [0] BUSY [27:16] BLKCNT, SEQLAT 0x048): TIM6 instants
  every T6 cycles (per seed, 20,000-112,000; the chip's 111,975), each queued with NEED = ARR at its instant; the head is
  serviced when (DONE - NEED) as a signed 16-bit number >= 0, or once it has waited TIMEOUT (5 ms, counted); a
  serviced instant mixes a block: RUN for BLK cycles (per block 2,000-36,000: 0.04-0.67 ms), then BLKCNT + 1.
  BUSY = RUN or (an instant queued and its head serviceable). Instants start at checkpoints.
The 68000: mailbox B posts, each waiting for its finish ($1FEA := 0; a post the full queue holds back stays
outstanding): bit 14 = an engine post (bit 13 too: refused by its gate, no item), bit 0 (no bit 14) = a probe job,
neither = a plain post; at times a run of engine posts back to back (the queue fills: held posts); mailbox A: 0x9494
every 100,000-896,040 cycles (a frame is 896,040; per seed 100k-300k or 300k-896k) or 0x80A0 (plain); SEND events (a brain call in the thread).
  A + B pairs (per seed 10-60 % of the A posts): both pending at one L1 entry, in either arrival order (an A post that
  draws a pair waits up to 50,000 cycles for mailbox B to be free); half the pair's B words are refused by their gate.
Invariants:
  FZ5  no post lost: every post dispatched exactly once, in order per mailbox, every post finished, the MCU reads a
       mailbox only after acknowledging it, every SEND followed by a brain call; outside L2b, with interrupts open, a
       waiting item always has MSIP up (or is running).
  FZ7  wherever MIE = 1: $1FE6 == the probe's shadow == the parity of its two writers' counts.
  FZ8  (stage 5) L1 dispatched the posts of both mailboxes in ARRIVAL order (the rig's own ARR count, not L1's: B Jam's
       decision of 2026-10-21, number 3(a), MCU interface v1.3 section 3.10.5); every accepted engine post and every
       9494 got exactly one item, the refused and plain ones none, and the items started in arrival order; every DONE
       write is monotone and <= ARR, and every accepted arrival up to it has finished its item; DONE is never left
       behind: wherever the MCU idles in the thread (no brain call) with no post pending in L1, DONE = ARR; no block
       starts while an item's body runs (the module-start item excepted: it has no arrival of its own, as the chip's
       thread-mode job tail is preemptible by TIM6; such blocks are counted and printed); every block waited for its
       NEED (no instant serviced on the 5 ms TIMEOUT: in the design's words, "blocks run on the timeout with stale
       state"); DONE = ARR when the run ends quiet; every module item (L2c's song_job_done) ran before its job left.
       (A change of 2026-10-22 had made the TIMEOUT a count and excused a block inside an item that the TIMEOUT
       serviced; a repair restored both, as our working rules require. The longest wait of an instant and the TIMEOUT
       services inside an item are printed too.)
  FZ9  (stage 5) every tick item ends within CLK_URGENT5 + (its own and the items ahead of it) x their cost + 2 blocks
       + 40,000 cycles of its 9494, even with a 150,000-cycle brain call running: the urgent finish (L2a, interrupts
       off) runs the queue when L2b cannot. Printed beside it, not a check (the packet margin itself is checked by our
       separate rig at test build 4's costs, outside this tree; test build 4 is a firmware build B Jam tested on his
       hardware): the tick items that ended after the
       Z80's packet read, Z80_READ (~3.0 ms after the 9494: the console's Z80 driver, as seen in a co-simulation), and
       the worst tick end, estimated at this rig's CPI 6 and the probe's costs.
  FZ11 the stack floor word intact; the high-water depth (measured) <= fwstack's static bound.
  plus: no violation (fault, removed IO, a store into the code window), the boot reached the scheduler.
Printed (estimated; the queue side of an edge case of our stage-5 design): the 8C posts that arrived while an older 8C's
job had not yet run its module-start item (the second job then queues behind the first: FZ8's module checks cover both).
Printed, not a check (estimated at CPI 6 and the probe's costs; added after a review found it missing):
the L1 latency of every post, from the 68000's write to L1's dispatch of it (p50 / p99 / max, and the posts over
the L1 figure of MCU interface v1.3 section 6.2, 17,300 cycles = 0.32 ms, the figure the busy guard and the 84 deadline
use), and the finish latency (the write to $1FEA / $1FEC := 0, held posts included). The urgent finish drains the queue
with interrupts off (by design), which holds L1 for as long as the queue ahead of the tick takes: a pass / fail check
on it is proposed for our separate rig that runs at test build 4's costs (outside this tree).
Exit 0 = PASS, 1 = FAIL (or, with --negative, a planted bug that passed), 2 = setup error."""
import argparse, json, os, random, re, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
from unicorn import Uc, UcError, UC_ARCH_RISCV, UC_MODE_RISCV32, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, \
    UC_HOOK_MEM_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED, UC_PROT_READ, UC_PROT_EXEC, UC_PROT_ALL   # noqa: E402
from unicorn import riscv_const as RC   # noqa: E402

CPI = 6
NTSC = 53693175
FIO, FREG, RAMDP, SDRAM, WRAM, IOPAGE, SY = 0x01000000, 0x0B000000, 0x02000000, 0x03000000, 0x80000000, 0xFFFFF000, 0x06000000
IROM_BYTES = 0x16000                                           # pocket88k: 88 KB
CLK_URGENT5 = (1800000 * NTSC + 500000000) // 1000000000       # board/clock.h CLK_URGENT5 at the probe's clock
TIMEOUT = NTSC // 200                                          # MCU_INTERFACE v1.3 3.10.1 TIMEOUT reset value (5 ms)
Z80_READ = (3 * NTSC) // 1000                                  # the Z80 reads the packet ~3.0 ms after the 9494 (M3)
L1_FIG = 17300                                                 # MCU_INTERFACE v1.3 6.2: L1 waits <= 17.3k cycles (0.32 ms)
SLACK = 40000
S1_STACK_FILL = 0x5AC3A55A
LG_DISPATCH, LG_ITEM_START, LG_ITEM_END, LG_BRAIN_START, LG_BRAIN_END, LG_WHEEL, LG_FIN_HELD, LG_JOB, LG_MODITEM = range(1, 10)
PK = ['PK_BRAIN_CYC', 'PK_WHEEL_PER', 'PK_ITEM_CYC', 'PK_TICK_CYC', 'PK_MOD_EVERY']


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


def s16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


class Rig:
    def __init__(self, build, seed, cycles, cfg, user_code=0x50490103):
        self.build, self.seed, self.cycles = build, seed, cycles
        self.rnd = random.Random(seed)
        self.sym = nm(os.path.join(build, 'main.nm'))
        self.user_code = user_code
        self.violations = []
        self.time = 0
        self.tread = 0
        self.cause, self.msip, self.tcmp, self.ten, self.stamp_b, self.stamp_a = 0, 0, 0, 0, 0, 0
        self.ctrl, self.sptr, self.go, self.wlock = 0x09, 0, 0, 0
        self.freg = {0x04: 0, 0x06: 0, 0x0A: 0, 0x0C: 0}
        self.buf = {11: 0, 7: 0, 3: 0}
        self.taken = {11: 0, 7: 0, 3: 0}
        self.unacked = {0: False, 1: False}
        # v1.3: arrivals and the synth
        self.arr, self.seqlat, self.done = 0, 0, 0
        self.done_writes = 0
        self.inst = []                  # queued instants: [need, t_queued]
        self.run_until = None           # a block runs until this time
        self.blkcnt, self.blocks, self.timeouts, self.block_in_item, self.block_in_mod = 0, 0, 0, 0, 0
        self.block_in_item_to, self.lag_max, self.idle_checks, self.idle_behind = 0, 0, 0, 0
        self.idle_first = None
        self.need_bad = 0
        self.t6 = cfg['t6']
        self.blk = cfg['blk']
        self.next_t6 = self.t6
        # the 68000
        self.b = None
        self.a = None
        self.posts, self.sends = [], []
        self.seq = 0
        self.next_a = 40000
        self.burst_left = 0
        self.pairs = 0
        self.want_pair, self.pair_since = None, 0
        self.p_send = self.rnd.choice((0.0005, 0.002, 0.006))
        self.p_burst = cfg['p_burst']
        self.fe6_checks = 0
        u = self.uc = Uc(UC_ARCH_RISCV, UC_MODE_RISCV32)
        rom = open(os.path.join(build, 'img', 'rom.bin'), 'rb').read()
        u.mem_map(0, IROM_BYTES, UC_PROT_READ | UC_PROT_EXEC)
        u.mem_write(0, rom)
        u.mem_map(WRAM, 0xC000, UC_PROT_ALL)
        u.mem_write(WRAM + 0x2C00, open(os.path.join(build, 'img', 'wcode.bin'), 'rb').read())
        u.mem_map(RAMDP, 0x2000, UC_PROT_ALL)
        u.mem_map(SDRAM, 0x200000, UC_PROT_ALL)
        u.mmio_map(FIO, 0x1000, self.fio_r, None, self.fio_w, None)
        u.mmio_map(FREG, 0x1000, self.freg_r, None, self.freg_w, None)
        u.mmio_map(SY, 0x1000, self.sy_r, None, self.sy_w, None)
        u.mmio_map(IOPAGE, 0x1000, self.io_r, None, self.io_w, None)
        u.hook_add(UC_HOOK_MEM_UNMAPPED | UC_HOOK_MEM_FETCH_UNMAPPED, self.unmapped)
        self.idle_ranges = [(self.sym[f][0], self.sym[f][0] + self.sym[f][1]) for f in ('l3_thread', 'sched_thread_once',
                                                                                       'l3_idle') if f in self.sym]
        u.hook_add(UC_HOOK_MEM_WRITE, self.window_w, begin=WRAM + 0x2C00, end=WRAM + 0x6BFF)
        self.mie_hooks = 0
        for ln in open(os.path.join(build, 'main.dis')):
            m = re.match(r'^\s*([0-9a-f]+):\t[0-9a-f]+\s*\tcsrr?[swc]i?\t(?:[a-z0-9]+,)?mie,', ln)
            if m:
                a = int(m.group(1), 16) + 4
                u.hook_add(UC_HOOK_CODE, self.mie_written, begin=a, end=a)
                self.mie_hooks += 1
        self.cfg = cfg
        a = self.sym['brd_boot'][0]
        u.hook_add(UC_HOOK_CODE, self.set_knobs, begin=a, end=a)

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
        if slot == 14:
            return self.stamp_a
        if slot == 15:
            return self.wlock
        if slot == 16:
            return (self.time // 896040) & 0xFFFF
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

    # ---- the synth (region 0x06) ----
    def busy(self):
        if self.run_until is not None:
            return 1
        return 1 if self.inst and self.serviceable(self.inst[0]) else 0

    def serviceable(self, ins):
        return s16(self.done - ins[0]) >= 0 or self.time - ins[1] >= TIMEOUT

    def sy_r(self, uc, off, size, ud):
        off &= 0xFFC
        if off == 0x000:
            return 0x53350001
        if off == 0x028:
            return (self.arr & 0xFFFF) | (self.done << 16)
        if off == 0x02C:
            return self.done
        if off == 0x030:
            return self.busy() | (1 << 1 if self.run_until is not None else 0) | ((self.blkcnt & 0xFFF) << 16) | \
                (min(len(self.inst), 15) << 5)
        if off == 0x048:
            return self.seqlat
        return 0

    def sy_w(self, uc, off, size, value, ud):
        off &= 0xFFC
        if off != 0x02C:
            return
        n = value & 0xFFFF
        self.done_writes += 1
        if self.done_writes > 1 and s16(n - self.done) < 0:
            self.viol('FZ8: DONE went backwards %#x -> %#x' % (self.done, n))
        if s16(self.arr - n) < 0:
            self.viol('FZ8: DONE %#x passes ARR %#x' % (n, self.arr))
        # every accepted arrival up to n has finished its item (items run in arrival-served order: FZ8's order check)
        ended = self.rd32('probe_items')
        need = sum(1 for p in self.posts if p['item'] and s16(n - p['seq']) >= 0)
        if self.done_writes > 1 and need > ended:
            self.viol('FZ8: DONE %#x with %d accepted arrivals up to it but %d items ended' % (n, need, ended))
        self.done = n

    def synth_step(self):
        """the TIM6 instants, the block in progress, the next block"""
        while self.time >= self.next_t6:
            self.inst.append([self.arr & 0xFFFF, self.next_t6])
            self.next_t6 += self.t6
        if self.run_until is not None and self.time >= self.run_until:
            self.run_until = None
            self.blkcnt = (self.blkcnt + 1) & 0xFFF
            self.blocks += 1
        if self.run_until is None and self.inst and self.serviceable(self.inst[0]):
            need, tq = self.inst.pop(0)
            to = s16(self.done - need) < 0
            if to:
                self.timeouts += 1                      # FZ8 (no instant serviced on the TIMEOUT)
            self.lag_max = max(self.lag_max, self.time - tq)
            if self.rd32('probe_item_open'):
                self.block_in_item += 1                 # FZ8, whatever serviced it
                if to:
                    self.block_in_item_to += 1          # (of those, serviced on the TIMEOUT: printed)
            if self.rd32('probe_mod_open'):
                self.block_in_mod += 1          # (allowed: the chip's job tail is preemptible too; counted)
            self.run_until = self.time + self.rnd.randint(*self.blk)

    def io_r(self, uc, off, size, ud):
        a = IOPAGE + off
        if a == 0xFFFFFFE0:
            return NTSC
        if a == 0xFFFFFFE4:
            return self.user_code
        if a in (0xFFFFFF80, 0xFFFFFF84) or 0xFFFFFFE8 <= a <= 0xFFFFFFFC:
            return 0
        self.viol('NEORV32 IO read %#x (removed or not built)' % a)
        return 0

    def io_w(self, uc, off, size, value, ud):
        a = IOPAGE + off
        if a != 0xFFFFFF84:
            self.viol('NEORV32 IO write %#x (removed or not built)' % a)

    def set_knobs(self, uc, addr, size, ud):
        a = self.sym['probe_cfg'][0]
        for i, k in enumerate(PK):
            uc.mem_write(a + 4 * i, struct.pack('<I', self.cfg[k]))

    def rd32(self, name, k=0):
        return struct.unpack('<I', self.uc.mem_read(self.sym[name][0] + 4 * k, 4))[0]

    def rd8(self, name):
        return self.uc.mem_read(self.sym[name][0], 1)[0]

    # ---------------------------------------------------------------------------------------------- the 68000 side
    def post(self, mbx, word):
        self.arr = (self.arr + 1) & 0xFFFF
        item = (mbx == 0 and (word & 0x4000) and not (word & 0x2000)) or (mbx == 1 and word == 0x9494)
        p = dict(mbx=mbx, word=word, t_post=self.time, t_fin=None, n=len(self.posts), seq=self.arr, item=bool(item),
                 tick=mbx == 1 and word == 0x9494)
        self.posts.append(p)
        if mbx == 0:
            self.b = p
            self.freg[0x0A] = word
            self.cause |= 1
            self.stamp_b = self.time & 0xFFFFFFFF
            self.seqlat = (self.seqlat & 0xFFFF0000) | self.arr
        else:
            self.a = p
            self.freg[0x0C] = word
            self.cause |= 2
            self.stamp_a = self.time & 0xFFFFFFFF
            self.seqlat = (self.seqlat & 0xFFFF) | (self.arr << 16)
        self.unacked[mbx] = True

    def b_word(self):
        r = self.rnd
        self.seq += 1
        x = r.random()
        if x < 0.40:
            return 0xC000 | 0x0100 | (self.seq & 0xFE)              # an engine post (table index 0x01)
        if x < 0.45:
            return 0xC000 | 0x0C00 | (self.seq & 0xFE)              # an 8C: its job hands a module back
        if x < 0.55:
            return 0xE000 | 0x0100 | (self.seq & 0xFE)              # refused by its gate (bit 13)
        if x < 0.75:
            return 0x8000 | (self.seq & 0x1FFE) | 1                 # a probe job
        return 0x8000 | (self.seq & 0x1FFE)                         # plain

    def pair_word(self):
        """a pair's B word: half of them refused by the gate (a post with no engine part next to the 9494: SONG_BUG 9
        leaves DONE behind it), the rest drawn as any B word"""
        if self.rnd.random() < 0.5:
            self.seq += 1
            return 0xE000 | 0x0100 | (self.seq & 0xFE)
        return self.b_word()

    def side_68000(self):
        r = self.rnd
        if self.time > self.cycles:
            return
        if self.b is None:
            if self.burst_left:
                self.burst_left -= 1
                self.seq += 1
                self.post(0, 0xC000 | 0x0100 | (self.seq & 0xFE))
            elif r.random() < 0.02:
                if r.random() < self.p_burst:
                    self.burst_left = r.randint(4, 24)
                self.post(0, self.b_word())
        if self.a is None and self.time >= self.next_a:
            if self.want_pair is None:
                self.want_pair = r.random() < self.cfg['p_pair']
                self.pair_since = self.time
            if self.want_pair and self.b is not None and self.time - self.pair_since < 50000:
                pass                                # a pair waits (a while) for mailbox B to be free
            else:
                pair = self.want_pair and self.b is None
                self.want_pair = None
                if pair and r.random() < 0.5:       # B first, then the 9494: both pending at one L1 entry, B older
                    self.post(0, self.pair_word())
                if r.random() < 0.85:
                    if r.random() < 0.35:
                        self.cause |= 4
                        self.sends.append(self.time)
                    self.post(1, 0x9494)
                else:
                    self.post(1, 0x80A0)
                if pair and self.b is None:         # the 9494 first, then B: both pending, the 9494 (A) older: L1
                    self.post(0, self.pair_word())  # must serve it first (SCHED_BUG 13 serves B first)
                    self.pairs += 1
                self.next_a = self.time + r.randint(*self.cfg['a_gap'])
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
                self.time += 14
                return

    def qstate(self):
        return self.rd8('q_wr'), self.rd8('q_rd'), self.rd8('q_busy')

    def idle_check(self):
        """FZ8 liveness: the MCU idles in the thread (outside a brain call) with every post served: DONE = ARR"""
        pc = self.uc.reg_read(RC.UC_RISCV_REG_PC)
        if not any(lo <= pc < hi for lo, hi in self.idle_ranges):
            return
        if self.cause & 3 or self.rd32('brain_active'):
            return
        self.idle_checks += 1
        if s16(self.arr - self.done) != 0:
            self.idle_behind += 1
            if self.idle_behind == 1:               # kept, not a stop: the run goes on to its other checks
                self.idle_first = 't=%d pc=%#x FZ8: the MCU idles with every post served and DONE %#x behind ARR %#x ' \
                    '(DONE left behind)' % (self.time, pc, self.done, self.arr)

    def fz7(self):
        if not (self.uc.reg_read(RC.UC_RISCV_REG_MSTATUS) & 8):
            return
        shadow = struct.unpack('<H', self.uc.mem_read(self.sym['probe_fe6'][0], 2))[0]
        exp = (self.rd32('probe_n_disp') & 1) | ((self.rd32('probe_n_l3') & 1) << 1)
        self.fe6_checks += 1
        if not (self.freg[0x06] == shadow == exp):
            self.viol('FZ7: $1FE6 %#x, shadow %#x, writers\' parity %#x' % (self.freg[0x06], shadow, exp))
        # FZ5 (no lost work): outside L2b, a waiting item or job always has MSIP up
        wr, rd, busy = self.qstate()
        if not self.rd32('sched_stats', 20) and not self.msip and not busy and (wr != rd or self.rd32('probe_jobs')):
            self.viol('FZ5: L2b work pending (queue %d, jobs %d) with MSIP down and L2b not running: a lost raise' % (
                (wr - rd) & 0xFF, self.rd32('probe_jobs')))

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

    def boot(self, limit=400000):
        uc = self.uc
        l3 = self.sym['l3_thread'][0]
        try:
            uc.emu_start(0, l3, count=limit)
        except UcError as e:
            self.viol('CPU fault in the boot: %s' % e)
            raise Stop()
        if uc.reg_read(RC.UC_RISCV_REG_PC) == l3:
            return 'scheduler'
        return 'stopped at %#x' % uc.reg_read(RC.UC_RISCV_REG_PC)

    def run(self):
        r = self.rnd
        try:
            where = self.boot()
            if where != 'scheduler':
                self.viol('boot did not reach the scheduler: %s' % where)
                raise Stop()
            drain_until = idle_since = None
            while True:
                self.side_68000()
                self.synth_step()
                self.take()
                self.fz7()
                self.idle_check()
                self.step(r.randint(1, 48))
                if self.time > self.cycles:
                    wr, rd, busy = self.qstate()
                    idle = self.b is None and self.a is None and not (self.cause & 0xF) and not self.msip \
                        and wr == rd and not self.rd32('brain_pending') and not self.rd32('probe_jobs')
                    # (the synth's blocks go on for ever: they are not the MCU's work)
                    if not idle:
                        idle_since = None
                    elif idle_since is None:
                        idle_since = self.time
                    elif self.time - idle_since > 2 * self.cfg['PK_BRAIN_CYC'] + 50000:
                        break
                    if drain_until is None:
                        drain_until = self.time + 8000000
                    elif self.time > drain_until:
                        self.viol('FZ5: not idle 8,000,000 cycles after the last 68000 action (B %s, A %s, cause %#x, '
                                  'queue %d)' % (self.b, self.a, self.cause, (wr - rd) & 0xFF))
                        raise Stop()
        except Stop:
            pass
        return self.verdict()

    def verdict(self):
        out = dict(seed=self.seed, time=self.time, posts=len(self.posts), sends=len(self.sends), taken=self.taken,
                   fe6_checks=self.fe6_checks, mie_hooks=self.mie_hooks, blocks=self.blocks, timeouts=self.timeouts,
                   block_in_item=self.block_in_item, block_in_mod=self.block_in_mod, done_writes=self.done_writes,
                   block_in_item_to=self.block_in_item_to, lag_max=self.lag_max, idle_checks=self.idle_checks,
                   pairs=self.pairs, cfg=self.cfg)
        bad = list(self.violations)
        if self.idle_first:
            bad.append('%s (%d idle checks behind)' % (self.idle_first, self.idle_behind))
        ended = not self.violations
        try:
            n = self.rd32('probe_nlog')
            if self.rd32('probe_nlost'):
                bad.append('probe log overflow (%d lost): run shorter' % self.rd32('probe_nlost'))
            raw = self.uc.mem_read(self.sym['probe_log'][0], 8 * n)
            log = [(w >> 24, w & 0xFFFFFF, t) for w, t in struct.iter_unpack('<II', raw)]
        except Exception as e:      # noqa: BLE001
            bad.append('log unreadable: %s' % e)
            log = []
        # FZ5: dispatched exactly once, in order per mailbox, all finished, SENDs answered
        disp = [(d >> 16, d & 0xFFFF, t) for k, d, t in log if k == LG_DISPATCH]
        for mbx in (0, 1):
            want = [p['word'] for p in self.posts if p['mbx'] == mbx]
            got = [w for m, w, t in disp if m == mbx]
            if want[:len(got)] != got or (ended and want != got):
                bad.append('FZ5: mailbox %s dispatched %d posts, %d posted' % ('BA'[mbx], len(got), len(want)))
        unf = [p for p in self.posts if p['t_fin'] is None]
        if unf and ended:
            bad.append('FZ5: %d posts never finished (first %s)' % (len(unf), unf[0]))
        bstarts = [t for k, d, t in log if k == LG_BRAIN_START]
        for ts in (self.sends if ended else []):
            if not any(b >= (ts & 0xFFFFFFFF) for b in bstarts):
                bad.append('FZ5: the SEND at t=%d has no brain call after it' % ts)
                break
        # FZ8: L1 in arrival order; items = the accepted posts, in arrival order (the rig's own ARR count: self.posts is
        # the 68000's write order); the blocks; DONE at the end
        served = []                         # the posts in L1's service order (the dispatch log; per mailbox in order:
        idx = {0: 0, 1: 0}                  # FZ5), mapped to the rig's posts
        per = {0: [p for p in self.posts if p['mbx'] == 0], 1: [p for p in self.posts if p['mbx'] == 1]}
        l1_lat = []                         # printed: each post's L1 latency (its write to L1's dispatch of it)
        for m, w, t in disp:
            if idx[m] < len(per[m]):
                served.append(per[m][idx[m]])
                l1_lat.append((t - per[m][idx[m]]['t_post']) & 0xFFFFFFFF)
                idx[m] += 1
        fin_lat = [p['t_fin'] - p['t_post'] for p in self.posts if p['t_fin'] is not None]
        back = [(x['n'], y['n']) for x, y in zip(served, served[1:]) if y['n'] < x['n']]
        if back:
            bad.append('FZ8: L1 served %d posts after a newer one (first: post %d after post %d)' % (
                len(back), back[0][1], back[0][0]))
        items = [p for p in self.posts if p['item']]
        want_items = [(1, p['word'] & 0x3F00) if p['mbx'] == 1 else (2, p['word'] & 0x3FFF) for p in items]
                                            # (an item keeps the word as its fragment sees it: A & 0x3F00, B & 0x3FFF)
        starts = [(d >> 16, d & 0xFFFF, t) for k, d, t in log if k == LG_ITEM_START]
        ends = [(d >> 16, d & 0xFFFF, t) for k, d, t in log if k == LG_ITEM_END]
        got_items = [(m, w) for m, w, t in starts]
        if want_items[:len(got_items)] != got_items or (ended and want_items != got_items):
            first = next((i for i, (x, y) in enumerate(zip(want_items, got_items)) if x != y), min(len(want_items), len(got_items)))
            bad.append('FZ8: items %d, accepted posts %d, first difference at %d (%s / %s)' % (
                len(got_items), len(want_items), first, want_items[first:first + 2], got_items[first:first + 2]))
        if len(ends) != len(starts) and ended:
            bad.append('FZ8: %d items started, %d ended' % (len(starts), len(ends)))
        if self.block_in_item:
            bad.append('FZ8: %d blocks started while an item\'s body ran (%d of them serviced on the TIMEOUT)' % (
                self.block_in_item, self.block_in_item_to))
        if self.timeouts:
            bad.append('FZ8: %d instants serviced on the 5 ms timeout (the longest wait of an instant %d cycles)' % (
                self.timeouts, self.lag_max))
        if ended and self.done != self.arr:
            bad.append('FZ8: the run ended quiet with DONE %#x, ARR %#x' % (self.done, self.arr))
        if self.rd32('probe_mod_wait_bad'):
            bad.append('FZ8: %d jobs left before their module item ran' % self.rd32('probe_mod_wait_bad'))
        n8c = sum(1 for p in self.posts if p['item'] and p['mbx'] == 0 and (p['word'] & 0x3F00) == 0x0C00)
        if ended and self.rd32('probe_mod_items') != n8c:
            bad.append('FZ8: %d 8Cs, %d module items' % (n8c, self.rd32('probe_mod_items')))
        # FZ9: each tick item ends within its bound (from the 9494's write; the items between its arrival and its end)
        cfg = self.cfg
        cmax = max(cfg['PK_ITEM_CYC'], cfg['PK_TICK_CYC'])
        ticks = [p for p in items if p['tick']]
        # the end of each item, in item (= arrival) order
        end_t = [t for m, w, t in ends]
        late, worst, z80_late = [], 0, 0
        for i, p in enumerate(items):
            if not p['tick'] or i >= len(end_t):
                continue
            ahead = sum(1 for k in range(i + 1) if ((end_t[k] - p['t_post']) & 0xFFFFFFFF) < 0x80000000)   # still to run
            bound = CLK_URGENT5 + ahead * (cmax + cfg['blk'][1]) + 2 * cfg['blk'][1] + SLACK
            d = (end_t[i] - p['t_post']) & 0xFFFFFFFF
            worst = max(worst, d)
            if d > Z80_READ:
                z80_late += 1               # printed: packet margin is F4's (card-4 prices)
            if d > bound:
                late.append((p['n'], d, bound))
        # printed: 8C posts that came while an older 8C's job had not run its module-start item yet (k-th 8C item =
        # k-th module item: the module jobs run in order)
        mod_t = [t for k, d, t in log if k == LG_MODITEM]
        c8s = [p for p in items if p['mbx'] == 0 and (p['word'] & 0x3F00) == 0x0C00]
        c8_overlap = sum(1 for k, p in enumerate(c8s) if any(j >= len(mod_t) or mod_t[j] > (p['t_post'] & 0xFFFFFFFF)
                                                             for j in range(k)))
        if late:
            bad.append('FZ9: %d of %d ticks ended late (first post %d: %d cycles, bound %d)' % (
                len(late), len(ticks), late[0][0], late[0][1], late[0][2]))
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
        out.update(l1_lat=l1_lat, l1_lat_max=max(l1_lat) if l1_lat else 0, l1_over=sum(1 for x in l1_lat if x > L1_FIG),
                   fin_max=max(fin_lat) if fin_lat else 0)
        out.update(ticks=len(ticks), tick_worst=worst, z80_late=z80_late, c8_overlap=c8_overlap, c8s=len(c8s),
                   items=len(starts), brain_calls=len(bstarts), dispatches=len(disp),
                   stack_depth=depth, stack_bound=static, held=self.rd32('song_q_over'), qmax=self.rd32('song_q_max'),
                   urgent=self.rd32('sched_stats', 12), mod_items=self.rd32('probe_mod_items'),
                   wheel_runs=self.rd32('probe_wheel_runs'), wheel_late_max=self.rd32('probe_wheel_late_max'), bad=bad)
        return out


def seed_cfg(sd):
    """per seed: the probe's knobs and the synth's timing. A block takes at most 32 % of a TIM6 period, as the chip's
    worst block (~0.67 ms, estimated) of its 2.085 ms; TIM6 rates faster than the chip's stress the
    order"""
    k = random.Random(5000 + sd)
    t6 = k.choice((20000, 50000, 111975))
    hi = k.choice((0.08, 0.2, 0.32))
    return dict(PK_BRAIN_CYC=k.choice((20000, 80000, 150000)), PK_WHEEL_PER=k.choice((3000, 7168, 20000)),
                PK_ITEM_CYC=k.choice((500, 1000, 2200)), PK_TICK_CYC=k.choice((4000, 8000, 22300, 35900, 55800)),
                PK_MOD_EVERY=k.choice((2, 4, 8)), t6=t6, blk=(int(t6 * 0.02), int(t6 * hi)),
                p_burst=k.choice((0.0, 0.05, 0.2)), a_gap=k.choice(((100000, 300000), (300000, 896040))),
                p_pair=k.choice((0.1, 0.3, 0.6)))


# the negative table's scenarios (overrides of seed_cfg): 'pairs' = 9494s every 30,000-60,000 cycles, 90 % of them
# paired with a B post in either order, light items and no bursts (SCHED_BUG 13's case: both pending, the older A);
# 'brain' =
# brain calls of 400,000 cycles (7.4 ms), so a tick that waits for the call ends past its FZ9 bound (SCHED_BUG 4);
# 'urgent' = items of 8,000 cycles, ticks of 35,900 and bursts in 20 % of the runs, so a tick waits past CLK_URGENT5
# behind the items ahead of it while L2b runs one and the urgent finish fires often (SCHED_BUG 10, an item not atomic
# against L2a: at SONG_Q_N = 8 the plain row saw 1-4 urgent finishes in 6 seeds and was caught on only some seed
# sets, as a check run found; in 'urgent' the clean probe makes 11-104 per 6 seeds with no TIMEOUT and the plant fails
# 5-6 of 6 on each of seven seed sets, measured)
SCEN = {'pairs': dict(a_gap=(30000, 60000), p_pair=0.9, PK_TICK_CYC=4000, PK_ITEM_CYC=500, p_burst=0.0),
        'brain': dict(PK_BRAIN_CYC=400000, PK_TICK_CYC=8000),
        'urgent': dict(PK_ITEM_CYC=8000, PK_TICK_CYC=35900, p_burst=0.2)}


def run_seeds(build, seeds, cycles, first=1, scen=None):
    agg = dict(seeds=0, posts=0, sends=0, ticks=0, items=0, brain_calls=0, fe6_checks=0, held=0, urgent=0, blocks=0,
               done_writes=0, mod_items=0, qmax=0, tick_worst=0, stack_depth=0, taken={11: 0, 7: 0, 3: 0}, pairs=0,
               block_in_mod=0, timeouts=0, block_in_item_to=0, lag_max=0, idle_checks=0, to_seeds=[], z80_late=0,
               z80_seeds=[], c8_overlap=0, c8s=0, l1_over=0, l1_seeds=[], fin_max=0)
    fails = []
    lats = []
    for sd in range(first, first + seeds):
        cfg = seed_cfg(sd)
        cfg.update(SCEN.get(scen, {}))
        rg = Rig(build, sd, cycles, cfg)
        o = rg.run()
        agg['seeds'] += 1
        lats += o.pop('l1_lat', None) or []
        for k in ('posts', 'sends', 'ticks', 'items', 'brain_calls', 'fe6_checks', 'held', 'urgent', 'blocks', 'done_writes',
                  'mod_items', 'pairs', 'block_in_mod', 'timeouts', 'block_in_item_to', 'idle_checks', 'z80_late',
                  'c8_overlap', 'c8s', 'l1_over'):
            agg[k] += o.get(k) or 0
        for k in ('qmax', 'tick_worst', 'stack_depth', 'lag_max', 'fin_max'):
            agg[k] = max(agg[k], o.get(k) or 0)
        if o.get('timeouts'):
            agg['to_seeds'].append(sd)
        if o.get('z80_late'):
            agg['z80_seeds'].append(sd)
        if o.get('l1_over'):
            agg['l1_seeds'].append(sd)
        agg.setdefault('per_seed', []).append({k: o.get(k) for k in (
            'seed', 'cfg', 'posts', 'items', 'ticks', 'held', 'qmax', 'urgent', 'timeouts', 'lag_max', 'block_in_item',
            'block_in_item_to', 'block_in_mod', 'tick_worst', 'z80_late', 'c8s', 'c8_overlap', 'pairs', 'l1_lat_max',
            'l1_over', 'fin_max')})
        for k in (11, 7, 3):
            agg['taken'][k] += o['taken'][k]
        agg['stack_bound'] = o.get('stack_bound')
        if o['bad']:
            fails.append((sd, o['bad']))
    lats.sort()
    agg['l1_n'] = len(lats)
    for nm_, f in (('l1_p50', 0.5), ('l1_p99', 0.99)):
        agg[nm_] = lats[min(len(lats) - 1, int(f * len(lats)))] if lats else 0
    agg['l1_max'] = lats[-1] if lats else 0
    return agg, fails


# s5probe_bug6 is the urgent finish's positive control: the brain call masks MSI, the items wait for it (FZ8's
# timeouts may follow), and every tick is still in time (no FZ9): 'noFZ9'
NEG = [('s5probe', 'PASS'), ('s5probe_bug1', 'FZ5'), ('s5probe_bug2', 'FZ5'), ('s5probe', 'PASS', 'brain'),
       ('s5probe_bug4', 'FZ9', 'brain'),
       ('s5probe_bug6', 'noFZ9'), ('s5probe', 'PASS', 'urgent'), ('s5probe_bug10', 'FZ', 'urgent'),
       ('s5probe_bug11', 'FZ5'), ('s5probe_sbug6', 'FZ8'),
       ('s5probe_sbug9', 'FZ8'), ('s5probe', 'PASS', 'pairs'), ('s5probe_bug13', 'FZ8', 'pairs'),
       ('s5probe_sbug11', 'FZ8'), ('s5probe_sbug13', 'FZ8')]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default=os.path.join(ROOT, 'build', 's1', 'pocket88k', 's5probe'))
    ap.add_argument('--seeds', type=int, default=12)
    ap.add_argument('--first', type=int, default=1)
    ap.add_argument('--cycles', type=int, default=2000000, help='model cycles of 68000 activity per seed')
    ap.add_argument('--negative', action='store_true')
    ap.add_argument('--json')
    a = ap.parse_args()
    if not os.path.exists(os.path.join(a.build, 'main.nm')):
        print('SETUP: no s5probe build at %s (tools/fwbuild.py s1 --variant s5probe)' % a.build)
        sys.exit(2)
    if a.negative:
        base = os.path.dirname(a.build)
        cmd = [sys.executable, '-I', '-B', os.path.join(ROOT, 'tools', 'fwbuild.py'), 's1', '--images-only',
               '--out', os.path.dirname(os.path.dirname(base))]
        for v in sorted({e[0] for e in NEG}):
            cmd += ['--variant', v]
        rr = subprocess.run(cmd, capture_output=True, text=True)         # rebuilt every time: a stale image tests old
        if rr.returncode:                                                # sources
            print('SETUP: building the planted images failed:' + chr(10) + rr.stdout[-2000:] + rr.stderr[-2000:])
            sys.exit(2)
        ok = True
        res = {}
        for e in NEG:
            v, want, scen = e[0], e[1], (e[2] if len(e) > 2 else None)
            if not os.path.exists(os.path.join(base, v, 'main.nm')):
                print('SETUP: %s not built (tools/fwbuild.py s1 --variant %s)' % (v, v))
                sys.exit(2)
            agg, fails = run_seeds(os.path.join(base, v), a.seeds, a.cycles, a.first, scen)
            cats = sorted({(re.search(r'FZ\d+', b) or re.search(r'\w+', b)).group(0) for sd, bs in fails for b in bs})
            got = 'PASS' if not fails else ' '.join(cats)
            if want == 'noFZ9':
                hit = 'FZ9' not in got and agg['urgent'] > 0
            else:
                hit = (want == 'PASS' and not fails) or (want != 'PASS' and fails and want in got)
            ok &= bool(hit)
            name = v + ('@' + scen if scen else '')
            res[name] = dict(want=want, got=got, failed=len(fails), urgent=agg['urgent'], held=agg['held'],
                             pairs=agg['pairs'])
            print('%-4s %-21s expected %-4s: %d of %d seeds failed  [%s] (urgent %d, held %d, pairs %d)' % (
                'PASS' if hit else 'FAIL', name, want, len(fails), agg['seeds'], got[:90], agg['urgent'], agg['held'],
                agg['pairs']))
        if a.json:
            json.dump(res, open(a.json, 'w'), indent=1)
        print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
        sys.exit(0 if ok else 1)
    agg, fails = run_seeds(a.build, a.seeds, a.cycles, a.first)
    print('fuzz_sched_s5 %s: %d seeds x %d cycles: %d posts, %d SENDs, %d ticks, %d items (%d module items), %d blocks, '
          '%d DONE writes, queue max %d, held %d, %d urgent finishes, tick worst %d cycles, %d brain calls, %d FZ7 checks, '
          '%d A+B pairs, %d blocks inside a module-start item (the chip job tail is preemptible too), '
          '%d idle checks (DONE = ARR at each), taken MEI %d MTI %d MSI %d, stack MEASURED %d B of the static %s B; '
          'FZ8: %d instants serviced on the 5 ms TIMEOUT (seeds %s; %d of them inside an item), the longest wait of an '
          'instant %d cycles; packet margin (printed, F4\'s gate; MODELLED at CPI 6 and the probe costs): %d tick items '
          'ended after the Z80 read (%d cycles after the 9494; seeds %s); %d of %d 8C posts came while an older 8C\'s '
          'job had not run its module start; L1 latency (printed, MODELLED; MCU_INTERFACE v1.3 6.2 figure %d cycles) of '
          '%d posts: p50 %d, p99 %d, max %d cycles (%.2f ms), %d posts over the figure (seeds %s); finish latency max '
          '%d cycles' % (
              os.path.basename(a.build), agg['seeds'], a.cycles, agg['posts'], agg['sends'], agg['ticks'], agg['items'],
              agg['mod_items'], agg['blocks'], agg['done_writes'], agg['qmax'], agg['held'], agg['urgent'],
              agg['tick_worst'], agg['brain_calls'], agg['fe6_checks'], agg['pairs'], agg['block_in_mod'],
              agg['idle_checks'], agg['taken'][11], agg['taken'][7],
              agg['taken'][3], agg['stack_depth'], agg.get('stack_bound'), agg['timeouts'],
              ' '.join(str(x) for x in agg['to_seeds']) or '-', agg['block_in_item_to'], agg['lag_max'],
              agg['z80_late'], Z80_READ, ' '.join(str(x) for x in agg['z80_seeds']) or '-', agg['c8_overlap'],
              agg['c8s'], L1_FIG, agg['l1_n'], agg['l1_p50'], agg['l1_p99'], agg['l1_max'], agg['l1_max'] * 1000.0 / NTSC,
              agg['l1_over'], ' '.join(str(x) for x in agg['l1_seeds']) or '-', agg['fin_max']))
    for sd, bs in fails[:6]:
        print('  seed %d: %s' % (sd, '; '.join(bs[:3])))
    if a.json:
        json.dump(dict(agg=agg, fails=fails), open(a.json, 'w'), indent=1)
    print('RESULT: %s' % ('PASS' if not fails else 'FAIL: %d of %d seeds' % (len(fails), agg['seeds'])))
    sys.exit(0 if not fails else 1)


if __name__ == '__main__':
    main()
