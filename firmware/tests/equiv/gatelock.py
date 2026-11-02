#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""gatelock.py - stage 3, the gate check (every command x every gate input class equals the chip): the mailbox
gates of a BUILT stage-5 IMAGE against the cart chip's own, every command at every state, posted through both mailboxes
the way the 68000 posts them, the forms the game never posts included. The stage-5 images are the FW_S5 builds with
our own song engine; stages are the steps of the 0.3.0 work (docs/ALLOWLIST.md lists them); B12, B58 and B59 are rows
of the allow-list (docs/ALLOWLIST.md); test build 5 is a firmware build B Jam tested on his hardware.

    python -I -B tests/equiv/gatelock.py --build build/s1/pocket88k/s5release [--state pre|post|both] [--table FILE]
    python -I -B tests/equiv/gatelock.py --build build/s1/pocket88k/s5release --check-table docs/GATE_TABLES.md
    python -I -B tests/equiv/gatelock.py --build build/s1/pocket88k/s5release --negative
    python -I -B tests/equiv/gatelock.py --build build/s1/pocket88k/s5release --state post --no-clear

Sides:
  chip  our model of the cart chip (the harness's cartmcu.py and host68k.py, paths.local.json "harness_dir"; read in
        place) from power-on: the boot page, the app init (0.3 s of emulated time), then the
        posts through the real mailbox interrupts (EXTI 14 for $1FEA, 15 for $1FEC) in the runner's fast mode. The cart's
        main loop never waits (no WFI): it runs its pass (the 81 counters' copy to $1B00, $1FE6 bit 3, the Boom Box feed)
        again and again; the runner stops it at the pass's end (its idle point 0x0801A676) and lets it run on only after a
        job, so this rig lets one more pass through after every post, as ours runs one.
  ours  the image (main.elf / main.nm) on tests/equiv/rtlmodel.py's
  board (MCU interface v1.3, test build 5's FEAT; a blank
        8 KB save) from its power-on to the 68000's release, then the same posts as the 68000 writes them, interrupts at
        seeded random instruction boundaries. When the build has a MegaWire SRAM image (img/sram.bin), the board holds it
        as the Pocket's data slot loads it (the image in SRAM, XLINK LOADED = its halfwords), so the image runs the cart's
        MegaWire code and its MegaWire forms are compared strictly; --no-sram leaves the SRAM empty.
States: 'pre' = after the app init, before any C6 (every C6-done flag clear); 'post' = after the game's own boot posts
(810E three times, then C600 with the game's 14 argument words from the ROM), its job ended on both sides. Each state
is its own run from power-on. Inside a run the forms are posted one after another on both sides (a form that changes
state changes it on both), in this order: every other form; 84; the frame tick; the MegaWire indexes; then (pre) the C6
itself, or (post) the corner forms whose chip side writes its own live RAM (allow-list B48 / B57), a second C6 and A858
(after an A858 the chip's main loop runs its MegaWire screen and no job: so A858 is posted after C6 only). Before each form the
68000 side clears $1F10 / $1F16, as the game does after its VBlank DMA; --no-clear leaves them, so the AF closes
list their DMA descriptors on and on, over $1F10 and past cart RAM's end, where ours drops a descriptor (allow-list
B58).
Per form, after its finish, the end of every job it queued (the job queue's indexes equal: the chip's global block
+0x12 / +0x13, ours' disp_g, found in the image's own disp_queue_full) and 2 ms of emulated time more, and then, on an
image that runs the cart's MegaWire code, the aligned sampling below:
  regs     the register file's stored words $1FE4 / $1FE6 / $1FEA / $1FEC (the MCU side);
  events   every event the post raised (the chip's event_post 0x08020B24 / ours' chip_trace): code | r6 << 8, a, b; a
           refusal is its code (2 default, 5 queue full, 6 not ready, 7 bad arguments) with $1FE6 bit 9 (B) / 10 (A);
  counted  what event_post's 16 counters counted in the form (the chip's global block +0x196, ours' disp_g);
  regw     the register-file writes in order to $1FE8 (window), $1FEE (watchdog word), $1FF2 / $1FF4 / $1FF6 (the
           decoder / stream queue);
  ramdp    every cart RAM word $0000-$1FDF the form changed on either side must end equal on both ($1B00-$1B1F, the
           counters' copy, through 'counted'; a word that differed before the form and neither side changed is not
           the form's: e.g. the boot page's patched words);
  zoom     after F4 / F5 / B6, every byte either side changed in the chip's zoom block (stamps 0x200111EC 2 KB, F4
           source and save 0x200119EC 4 KB) == ours' zoom_st / zoom_ss (both use the stamps as the save jobs' scratch
           too, so they differ there before any zoom);
  save     the 8 KB battery save (a TEST image keeps its debug record at $1000-$1FFF: the first 4 KB there).
Aligned sampling (an image running the cart's MegaWire code; --no-align turns it off): the cart's chip runs its MegaWire
task from a timer interrupt about ten times a second (TIM7, 0x080219CC, started by the MegaWire init), and some posts
leave work for the task's next run (A4's request byte, an E7 packet, the init's first step; ours also AA58's reset and
init). The two sides' timers are not in step, so a form's 2 ms window can hold a task run on one side and not on the
other. So when, at a form's normal sample point, either side has run its task since the post, or either side holds
such work for the task's next run, both sides are run on until each has completed the same number of task runs since
the post, at least one more than any that still had work waiting, with no run half done and none held back (ours runs
its task in the thread, in steps, and a long job holds its runs: they run late), then their queued jobs and 2 ms more,
and only then sampled. This is a stricter sampling, not a mask: nothing is left out of the comparison, every word
either side changed from the post to that later point must end equal, and the task's deferred work is compared too,
where the normal window would see it on one side only. The boot posts of the 'post' state are aligned the same way.
Two forms are built to leave their work for the next form: 'E7 (a send)' and 'E7 again (send pending)', so that the
second E7 and 'A9 after E7' meet a send still waiting (the E7 gate's refusal 6 for it, A9's clearing of it); they are
sampled at their normal point unless a task run fell in their window on either side, and the alignment comes after
'A9 after E7'.
Before the chip's first MegaWire init its timer does not run, so a side with no task yet is not waited for; a side
whose next task run does not come within the time limit is a difference. The task's own behaviour run by run is
tests/equiv/mw_oracle.py's (every run against the cart's program); when it runs is the board rig's and the
co-simulation's.
Forms: every table index 0x00-0x3F on mailbox B with the argument flag (bit 14) clear and set and with the low bytes
that choose a gate (0, 1, 2, 5, 7, 0x3F, 0x40, 0x58, 0x7F, 0x80, 0xFF); the argument edges of every gate that reads
an argument (DA's modes x source types x the 8 MB edge, DB's modes and its page / workspace bounds, DF / E0's slot ids,
key and RAM bounds, E7's length, EC's (0, n), D0's voice, D1's id and level byte, D2 / D3, D5 / D6's sub-commands and
D6 05's voice, 88 / C9 / CA, 8C / 8E's module range and null slots, 8D, AD's index, AE / AF / B0 / B1 / F0 / F1, F2's
block numbers, F4's source type and edge, F5 / B6 with and without a session); words without the request bit (B bit
15, A bit 7); every index on mailbox A (its low byte dropped, the argument flag forced 0). The sources DA / F4 take are
read at run time from the player's ROM through the solo capture's own posts (the game's first zoom picture, DA streams
of both types), never typed in; the module count and its null slots and the SFX count from the chip's RAM after its C6.
Left out on purpose, with what covers them: 83 with n > 0 (its answer is the frame time: tests/equiv/f83lock.py); 85
(the fatal halt stops both MCUs: the chip lockstep's tail, tests/equiv/chiplock_s1.py); 81 with bit 4 (a watchdog trip
would then reset the MCU); DB06 longer than one FIFO chunk (the chip's FIFO-B refills are its plumbing); the sprite
engine's and the song engine's own work past their gates (their own locks: chiplock_s1 / the stage-2 unit lockstep,
the song engine's).
Classes (counted and listed, never silent; a difference in none of them FAILS):
  megawire     a MegaWire form (A4, A6, A8, A9, AA, E7) on an image that does not run our MegaWire port this boot;
               the chip's MegaWire task's publication ($1B20-$1B87), its status bits ($1FE6 bits 0-2, 4, 5) and C6's
               MegaWire init clearing the receive length $1C10, likewise;
  B12          the words the chip's main-loop pass writes at $1C00-$1C0F after the Boom Box feed (ours'
               feed writes zeros there), the VU feed ($1B90-$1BFF), the Z80 packet page ($1800-$18FF) at a frame tick
               and counter 11 (also the audio underrun count): the audio engine's timing and words (allow-list B12; this
               rig has no audio block model).
  B59          AA58 on mailbox B (the MegaWire menu's restart): the cart chip saves the MegaWire record to the EEPROM's
               slot 9 (its two copies at 0xA00 and 0xA80, 96 bytes each); ours does not build that save (allow-list
               row B59; B Jam's decision of 2026-10-31: approved). Only the save bytes inside those two copies, written
               by the chip alone in that form, are let through; any other difference of the form still fails. The forms
               after it compare strictly (with the aligned sampling they are equal).
  A858 page    A858 after C6: the cart chip's screen code loads its two screen pages at once; when page A is not a
               packed block (format 0x80) it stops the chip for good with its fatal code 0x40000007 (event_post
               0x08020B24 with b = 0x28: interrupts off, a light blink, no more answers until the 68000 sends "WE SUX").
               A real cart has those pages (its start-up program leaves them in memory; they are not in the game's ROM),
               so its screen appears; our model of the chip has none, so it stops there. Measured: with the pages a real
               cart has, given to our model as tests/equiv/mw_screen.py gives them, the model raises no such code, goes
               on with the screen and answers the 68000 afterwards, and the A858 gate itself then equals ours; the
               screen after the gate equals ours in mw_screen.py. Ours has its pages and never raises it. So exactly
               this one event (code 0x40000007, a = 0x80, b = 0x28, raised by the screen's page loader, 0x08022428)
               is left out of the A858 form's events when the model's page A is not a packed block and ours raised
               none; everything else in the form compares strictly. B Jam's decision of 2026-10-31 allows this only
               because the game sees no difference.
--table FILE writes the chip's answer to every form, state by state (docs/GATE_TABLES.md, the gate tables; ROM-derived
arguments shown as such, not as numbers); --check-table FILE fails when this run's chip answers differ from that file.
--negative: the planted images s5release_bug_gate1 (DF's RAM bound one word longer) and s5release_bug_gate2 (D608
taken), rebuilt with tools/fwbuild.py, must each differ from the chip at their planted form; and the two named
exceptions (B59, the A858 page rule) must each take their own synthetic case and refuse every case next to it.
Exit 0 = PASS, 1 = FAIL, 2 = setup error. The last line printed is 'RESULT: ...'.
The board is a model (rtlmodel, written from the documents); the chip side is our model of the cart chip."""
import argparse, collections, json, os, random, re, struct, subprocess, sys, time
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

EVENT_POST = 0x08020B24                     # the chip's event_post entry
CHIP_Q = 0x20006F3E                         # the chip's job queue write / read indexes (its global block + 0x12 / 0x13)
CHIP_CNT = 0x200070C2                       # event_post's 16 counters (its global block + 0x196)
CHIP_MW = 0x20006D70                        # the chip's MegaWire byte
CHIP_G = 0x20006F2C                         # the chip's global block (G+0x188 / +0x18C: the MegaWire screen's pages)
A858_PAGE_EVENT = (0x40000007, 0x80, 0x28)  # the screen's page loader: page A is not a packed block (fatal)
A858_PAGE_LR = 0x0802242C                   # the return address of that call (0x08022428)
SLOT9 = ((0xA00, 0xA60), (0xA80, 0xAE0))    # the EEPROM's slot 9: the MegaWire record's two copies (allow-list B59)
CHIP_ZST, CHIP_ZSS = 0x200111EC, 0x200119EC  # its zoom block: the stamps (2 KB), the F4 source and the save (4 KB)
REGW_OFFS = (0x08, 0x0E, 0x12, 0x14, 0x16)  # $1FE8, $1FEE, $1FF2, $1FF4, $1FF6
MW_IDX = (0x24, 0x26, 0x27, 0x28, 0x29, 0x2A)
CNT_COPY = (0x1B00, 0x1B20)                 # cart RAM the main-loop pass copies the counters to (81 bit 1)
MW_TASK = (0x1B20, 0x1B88)                  # cart RAM the MegaWire task publishes its state to (81 bit 3)
VU_FEED = (0x1B90, 0x1C00)                  # the VU feed (allow-list B12)
JOB_WORDS = (0x1C00, 0x1C10)                # cart RAM the chip writes at a job (allow-list B12)
PACKET = (0x1800, 0x1900)                   # the Z80 packet page (the song engine's packets)
MW_FE6 = 0x0037                             # $1FE6 bits 0-2 (MegaWire status), 4 / 5 (send / receive)
MW_LEN = 0x1C10                             # the MegaWire receive length word (its init, A6 and E7 clear it)
CHIP_MW_END = 0x080223C4                    # the chip's MegaWire task (0x080219CC) ends here on every path
CHIP_TIM7 = 0x40001400                      # the chip's TIM7, the task's timer (started by the MegaWire init)
MW_REQ_OFF, MW_STATE_OFF, MW_E7_OFF = 0x001, 0x002, 0x122   # task block: request byte, task state, E7 pending
ALIGN_MAX_RUNS = 64                         # aligned sampling: at most this many task runs a form, each side
ALIGN_RUN_S = 0.3                           # and this much emulated time for each run to come (the period ~0.1 s)
HOLD_FORMS = ('E7 (a send)', 'E7 again (send pending)')    # forms that leave their send for the next form (docstring)
SETTLE_S = 0.002
HZ = 53693175
NEG = [('s5release_bug_gate1', 'DF to 1E00'), ('s5release_bug_gate2', 'D6 08')]


def setup_error(msg):
    print('RESULT: setup error: ' + msg)
    sys.exit(2)


# ------------------------------------------------------------------ the chip side
class Chip:
    def __init__(self, hd):
        cd = os.path.join(hd, 'chip')
        if cd not in sys.path:
            sys.path.insert(0, cd)
        import cartmcu
        import host68k
        from unicorn import UC_HOOK_MEM_WRITE, UC_HOOK_CODE
        from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_LR
        self.FPGA = cartmcu.FPGA

        class Machine(cartmcu.Machine):
            pass_due = 0

            def _idle_hook(self, uc, addr, size, ud):
                if self.pass_due:               # one more main-loop pass (the module text)
                    self.pass_due -= 1
                    return
                return cartmcu.Machine._idle_hook(self, uc, addr, size, ud)
        m = self.m = Machine(verbose=0, log_mmio=False)
        m.watchdog_us = 300_000_000
        self.regw, self.ev, self.ev_lr = [], [], []

        def hw(uc, acc, a, sz, v, ud):
            off = a - self.FPGA
            if sz == 4:
                parts = ((off, v & 0xFFFF), (off + 2, (v >> 16) & 0xFFFF))
            elif sz == 1:
                parts = ((off & ~1, ('byte', off, v & 0xFF)),)
            else:
                parts = ((off, v & 0xFFFF),)
            for o, x in parts:
                if o in REGW_OFFS:
                    self.regw.append((o, x))
        m.mu.hook_add(UC_HOOK_MEM_WRITE, hw, begin=self.FPGA, end=self.FPGA + 0x1F)

        def he(uc, addr, size, ud):
            self.ev.append((uc.reg_read(UC_ARM_REG_R0) & 0xFFFFFFFF, uc.reg_read(UC_ARM_REG_R1) & 0xFFFFFFFF,
                            uc.reg_read(UC_ARM_REG_R2) & 0xFFFFFFFF))
            self.ev_lr.append(uc.reg_read(UC_ARM_REG_LR) & 0xFFFFFFFE)
        m.mu.hook_add(UC_HOOK_CODE, he, begin=EVENT_POST, end=EVENT_POST + 1)
        self.mw_runs = 0                     # MegaWire task runs completed (aligned sampling)

        def hmw(uc, addr, size, ud):
            self.mw_runs += 1
        m.mu.hook_add(UC_HOOK_CODE, hmw, begin=CHIP_MW_END, end=CHIP_MW_END + 1)
        self.rom_path = cartmcu.ROM_PATH
        orig = m.fifo_write

        def fifo_write(port, data, _orig=orig):   # FIFO B with bit 14 in its pointer is the $C000 window, not cart RAM
            if port == 1 and struct.unpack('<H', bytes(m.mu.mem_read(self.FPGA + 0x12, 2)))[0] & 0x4000:
                return
            _orig(port, data)
        m.fifo_write = fifo_write
        self.h = host68k.Host(m, verbose=0)  # the boot page into cart RAM (power-on)
        m.run(seconds=0.3)                   # the app init
        self.take()

    def take(self):
        r, e = self.regw, self.ev
        self.regw, self.ev, self.ev_lr = [], [], []
        return r, e

    def screen_page_a_missing(self):
        """the screen's page A (the pointer at G+0x188) is not a packed block: our model has no screen pages"""
        mu = self.m.mu
        p = struct.unpack('<I', bytes(mu.mem_read(CHIP_G + 0x188, 4)))[0]
        try:
            return mu.mem_read(p, 1)[0] != 0x80
        except Exception:                   # noqa: BLE001 (nothing mapped there: no page either)
            return True

    def c6_args(self):
        return list(self.h.c6_args())

    def queue_empty(self):
        w, r = self.m.mu.mem_read(CHIP_Q, 2)
        return ((w ^ r) & 0xF) == 0

    def counters(self):
        return struct.unpack('<16H', bytes(self.m.mu.mem_read(CHIP_CNT, 32)))

    def zoom(self):
        return bytes(self.m.mu.mem_read(CHIP_ZST, 0x800)), bytes(self.m.mu.mem_read(CHIP_ZSS, 0x1000))

    def w68(self, a, w):
        self.m.w68(a, w)

    def regs(self):
        v = struct.unpack('<16H', bytes(self.m.mu.mem_read(self.FPGA, 0x20)))
        return {0x04: v[2], 0x06: v[3], 0x0A: v[5], 0x0C: v[6]}

    def ram(self):
        return bytes(self.m.ramdp[:0x1FE0])

    def save(self):
        return bytes(self.m.eeprom)

    def post(self, mbx, word, args, job_s=30.0):
        m = self.m
        if args is not None:
            for i, w in enumerate(args):
                m.w68(0x1E10 + 2 * i, w)
        reg, line = (0x1FEA, 14) if mbx == 'B' else (0x1FEC, 15)
        m.wreg68(reg, word)
        m.raise_exti(line)
        ok = m.run(seconds=10.0, until=lambda mm: mm.reg68(reg) == 0)
        done = m.reg68(reg) == 0
        m.run(seconds=job_s, until=lambda mm: self.queue_empty())
        idle = self.queue_empty()
        m.pass_due = 1
        m.run(seconds=SETTLE_S)
        m.pass_due = 0
        return bool(ok) and done and m.fault is None, idle

    # aligned sampling (the docstring): the MegaWire task's timer, its deferred work, a run to its next runs
    def mw_timer_on(self):
        t = self.m.timers[CHIP_TIM7]
        return bool(t['CR1'] & 1 and t['DIER'] & 1)

    def mw_work(self):
        """the task's next run has work: the request byte, the init's first step (state 1), an E7 packet (state 2)"""
        mu = self.m.mu
        req, st, e7 = (mu.mem_read(CHIP_MW + o, 1)[0] for o in (MW_REQ_OFF, MW_STATE_OFF, MW_E7_OFF))
        return req != 0 or st == 1 or (st == 2 and e7 == 1)

    def mw_run_to(self, n, job_s=30.0):
        """run on until n task runs have completed (counted from power-on), then the jobs and 2 ms more"""
        m = self.m
        ok = m.run(seconds=ALIGN_RUN_S * max(1, n - self.mw_runs), until=lambda mm: self.mw_runs >= n)
        ok = bool(ok) and self.mw_runs >= n and m.fault is None
        m.run(seconds=job_s, until=lambda mm: self.queue_empty())
        m.pass_due = 1
        m.run(seconds=SETTLE_S)
        m.pass_due = 0
        return ok and self.queue_empty()


# ------------------------------------------------------------------ ours
def dis_offsets(build, fn, op, n):
    """the first n immediate offsets of the loads 'op' in the image's function fn (main.dis)"""
    on, offs = False, []
    for ln in open(os.path.join(build, 'main.dis')):
        if ln.rstrip().endswith('<%s>:' % fn):
            on = True
            continue
        if on:
            m = re.search(r'\t%s\t[a-z0-9]+,(\d+)\([a-z0-9]+\)' % op, ln)
            if m:
                offs.append(int(m.group(1)))
            if not ln.strip() or len(offs) == n:
                break
    if len(offs) != n:
        setup_error('%s: the %s offsets were not found' % (fn, op))
    return offs


class Ours:
    def __init__(self, build, rom, seed, sram=None):
        import rtlmodel
        from unicorn import UC_HOOK_CODE
        from unicorn import riscv_const as RC
        self.rnd = random.Random(seed)
        self.rom = rom
        self.regw, self.ev = [], []

        def listener(kind, kw):
            if kind == 'freg_w' and kw['off'] in REGW_OFFS:
                self.regw.append((kw['off'], kw['v']))
        b = self.b = rtlmodel.Board(build, rom, opt=0, seed=seed, save=bytes([0xFF]) * 0x2000, listener=listener,
                                    sram_fill=sram, sram_loaded=(len(sram) >> 1) if sram else 0)
        for need in ('chip_trace', 'disp_g', 'zoom_ss', 'zoom_st'):
            if need not in b.sym:
                setup_error('symbol %s missing in %s' % (need, build))

        def he(uc, addr, size, ud):
            self.ev.append((uc.reg_read(RC.UC_RISCV_REG_A0) & 0xFFFFFFFF, uc.reg_read(RC.UC_RISCV_REG_A1) & 0xFFFFFFFF,
                            uc.reg_read(RC.UC_RISCV_REG_A2) & 0xFFFFFFFF))
        a = b.sym['chip_trace'][0]
        b.uc.hook_add(UC_HOOK_CODE, he, begin=a, end=a)
        self.Stop = rtlmodel.Stop
        self.RAMDP = rtlmodel.RAMDP
        self.dg = b.sym['disp_g'][0]
        self.qoff = dis_offsets(build, 'disp_queue_full', 'lbu', 2)
        self.cnt_off = dis_offsets(build, 'chip_trace', 'lhu', 1)[0]
        if not b.run_to('brd_boot', 400_000_000):
            setup_error('the image did not reach brd_boot')
        n = 0
        while b.ctrl & 1:                   # until the 68000's release
            b.take()
            b.step(400)
            n += 1
            if n > 2_000_000:
                setup_error('the 68000 was never released')
        self.run_for(200_000)
        if sram and 's3_mw_checked' in b.sym:
            # the thread's first work after the release is the SRAM image's check (within 50 ms of it): the forms
            # start once it has run, as the game's first MegaWire post comes with its C6, seconds later
            if not self.run_until(lambda: b.rd8('s3_mw_checked') != 0 and (b.rd32('s3_sram_state') not in (0, 1) or
                                                                    b.rd8('s3_mw_on') != 0), 6_000_000):
                setup_error('the SRAM image check did not end within 6,000,000 cycles of the release')
        self.take()

    def run_until(self, cond, cycles):
        b = self.b
        end = b.time + cycles
        while not cond():
            if b.time > end:
                return False
            b.take()
            b.step(self.rnd.randint(8, 160))
        return True

    def run_for(self, cycles):
        end = self.b.time + cycles
        self.run_until(lambda: self.b.time >= end, cycles + 1)

    def take(self):
        r, e = self.regw, self.ev
        self.regw, self.ev = [], []
        return r, e

    def queue_empty(self):
        w, r = (self.b.uc.mem_read(self.dg + o, 1)[0] for o in self.qoff)
        return ((w ^ r) & 0xF) == 0

    def counters(self):
        return struct.unpack('<16H', bytes(self.b.uc.mem_read(self.dg + self.cnt_off, 32)))

    def zoom(self):
        u, s = self.b.uc, self.b.sym
        return bytes(u.mem_read(s['zoom_st'][0], 0x800)), bytes(u.mem_read(s['zoom_ss'][0], 0x1000))

    def w68(self, a, w):
        self.b.w68_ram(a, struct.pack('<H', w))

    def regs(self):
        f = self.b.freg
        return {0x04: f.get(0x04, 0), 0x06: f.get(0x06, 0), 0x0A: f.get(0x0A, 0), 0x0C: f.get(0x0C, 0)}

    def ram(self):
        return bytes(self.b.uc.mem_read(self.RAMDP, 0x1FE0))

    def save(self):
        return bytes(self.b.save)

    def mw_running(self):
        return 's3_mw_on' in self.b.sym and self.b.rd8('s3_mw_on') != 0

    # aligned sampling (the docstring). The thread starts a task run when mw_ran catches up with mw_due (the timer's
    # count) and runs it in steps (mw_tk_ph: 0 = no run half done); mw_ram holds the task block at the chip's offsets
    def mw_started(self):
        return self.b.rd8('mw_ran')

    def mw_busy(self):
        b = self.b
        return b.rd8('mw_tk_ph') != 0 or b.rd8('mw_due') != b.rd8('mw_ran')

    def mw_work(self):
        b = self.b
        req, st, e7 = (b.rd8('mw_ram', o) for o in (MW_REQ_OFF, MW_STATE_OFF, MW_E7_OFF))
        return b.rd8('mw_aa_pending') != 0 or req != 0 or st == 1 or (st == 2 and e7 == 1)

    def mw_run_to(self, ran0, n, job_s=30.0):
        """run on until n task runs have started since mw_ran was ran0, none is half done and none is held back,
        then the jobs and 2 ms more"""
        ok = self.run_until(lambda: ((self.mw_started() - ran0) & 0xFF) >= n and not self.mw_busy(),
                            int(ALIGN_RUN_S * max(1, n) * HZ))
        idle = self.run_until(self.queue_empty, int(job_s * HZ))
        self.run_for(int(SETTLE_S * HZ))
        return ok and idle and not self.b.violations

    def post(self, mbx, word, args, job_s=30.0):
        b = self.b
        if args is not None:
            b.w68_ram(0x1E10, struct.pack('<16H', *args))
        reg = 0x0A if mbx == 'B' else 0x0C
        (b.w68_post_b if mbx == 'B' else b.w68_post_a)(word)
        done = self.run_until(lambda: b.freg.get(reg, 0) == 0, int(10.0 * HZ))
        idle = self.run_until(self.queue_empty, int(job_s * HZ))
        self.run_for(int(SETTLE_S * HZ))
        return done and not b.violations, idle


# ------------------------------------------------------------------ the forms
def form(mbx, word, sets=None, what='', last=0, rom_args=False):
    """(mailbox, word, the 16 argument words or None (mailbox A), what, order class, arguments read from the ROM).
    Order classes: 0 every other form, 1 84, 2 the frame tick, 3 the MegaWire indexes, 4 (post) the corner forms and a
    second C6, 5 (post) A858, 6 (pre) the C6 itself"""
    if (word >> 8) & 0x3F in MW_IDX:
        last = max(last, 3)
    if mbx == 'A':
        return ('A', word & 0xFFFF, None, what, last, rom_args)
    a = [0] * 16
    for k, v in (sets or {}).items():
        a[k] = v & 0xFFFF
    return ('B', word & 0xFFFF, a, what, last, rom_args)


def rom_sources(rom, cap):
    """the sources the forms use, read at run time: the game's first zoom picture (its first F4 post's source) and DA
    streams of type 0x80 and 0x81 (its DA posts' sources), from the solo capture's own posts; an even offset whose type
    byte is none of 0x80-0x82"""
    import mmap
    out = {'t80': [], 't81': [], 'other': None, 'zoom': None}
    with open(cap, 'rb') as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as d:
        o = 0
        while o + 20 <= len(d) and (not out['t80'] or not out['t81'] or out['zoom'] is None):
            t, ln, f, vl, _z, cy, pc68 = struct.unpack_from('<HHIHHII', d, o)
            po = o + 20
            o = po + ln
            if t != 2:
                continue
            wv = struct.unpack_from('<18H', d, po)
            w, a = wv[0], wv[2:18]
            if w >> 8 == 0xF4 and out['zoom'] is None and ((a[0] << 16) | a[1]) < len(rom):
                out['zoom'] = (a[0] << 16) | a[1]
            elif w >> 8 == 0xDA and ((a[1] << 16) | a[2]) < len(rom):
                s = (a[1] << 16) | a[2]
                k = 't%02x' % rom[s & ~1]
                if k in out and not out[k]:
                    out[k].append(s)
    for off in range(0x200, 0x10000, 2):
        if rom[off] not in (0x80, 0x81, 0x82):
            out['other'] = off
            break
    return out


def forms_for(state, src, nbgm, nsfx, nulls, c6):
    F = []
    lows = (0x00, 0x01, 0x02, 0x05, 0x07, 0x3F, 0x40, 0x58, 0x7F, 0x80, 0xFF)
    special = {0x01, 0x03, 0x04, 0x05, 0x06, 0x14, 0x28}    # below (81, 83 n > 0, 84, 85, C6, the tick, A8)
    s80 = src['t80'][0] if src['t80'] else None
    s81 = src['t81'][0] if src['t81'] else None

    def srcs(s):
        return s >> 16, s & 0xFFFF
    for idx in range(0x40):                 # every index, both argument flags, the low-byte classes (mailbox B)
        if idx in special:
            continue
        for af in (0, 1):
            for lo in lows:
                F.append(form('B', 0x8000 | af << 14 | idx << 8 | lo, {}, 'index %02X, flag %d, low %02X' % (idx, af, lo)))
    for w in (0x0042, 0x4000, 0x1A02, 0x7FFF):
        F.append(form('B', w, {}, 'no request bit'))
    for lo in (0x00, 0x02, 0x04, 0x08, 0x0E, 0x0F):
        F.append(form('B', 0x8100 | lo, {}, '81 flags %02X' % lo))
        F.append(form('B', 0xC100 | lo, {0: 0x1234}, '81 flags %02X with the argument flag' % lo))
    for w in (0x8300, 0x8310, 0x83F0, 0xC300):
        F.append(form('B', w, {}, '83 n = 0 (the stamp)'))
    F.append(form('B', 0x8600, {}, 'C6 without the argument flag'))
    for mode in (0, 1, 2, 3, 5, 6, 7, 8, 0xFF):  # DA: modes x types x the 8 MB edge
        for k, s in (('0x80', s80), ('0x81', s81), ('another type', src['other'])):
            if s is not None:
                h, l = srcs(s)
                F.append(form('B', 0xDA00 | mode, {0: 0x0100, 1: h, 2: l}, 'DA mode %X, a %s stream' % (mode, k),
                              rom_args=True))
        for s in (0x800000, 0x800001, 0x800002, 0xFFFFFE):
            F.append(form('B', 0xDA00 | mode, {0: 0x0100, 1: s >> 16, 2: s & 0xFFFF}, 'DA mode %X, source %06X' % (mode, s)))
    for mode in (0, 2, 3, 6, 7):            # DB: 3 (workspace -> cart RAM) and 6 (stream), the page / workspace bounds
        for a0, a1, a2 in ((0x0000, 0x0000, 0x0010), (0x1F00, 0x0000, 0x0100), (0x1F00, 0x0000, 0x0102),
                           (0x0000, 0xFF00, 0x0100), (0x0000, 0xFF00, 0x0102), (0x0400, 0x2000, 0x00F0),
                           (0x0400, 0x2000, 0x00F2), (0xFFFE, 0x0000, 0x0002), (0x0000, 0xFFFE, 0x0002)):
            if mode == 6 and a2 > 0xF0:
                continue                    # longer than one FIFO chunk (left out: the module text)
            F.append(form('B', 0xDB00 | mode, {0: a0, 1: a1, 2: a2}, 'DB mode %X (%04X, %04X, %04X)' % (mode, a0, a1, a2)))
    for sid in (0, 1, 2, 3, 4, 5, 8, 9, 10, 0x7F, 0xFF):    # DF / E0: the slot ids, the key, the RAM bounds
        F.append(form('B', 0xDF00 | sid, {0: 0x1C00}, 'DF slot %d' % sid))
        F.append(form('B', 0xE000 | sid, {0: 0xBEEF, 1: 0x0200}, 'E0 slot %d' % sid))
    for a0 in (0x1DFE, 0x1DFF, 0x1E00, 0xFFFF):
        F.append(form('B', 0xDF01, {0: a0}, 'DF to %04X' % a0))
    for a0, a1 in ((0xBEEE, 0x0200), (0xBEEF, 0x1DFF), (0xBEEF, 0x1E00), (0x0000, 0x0200), (0xEFBE, 0x0200)):
        F.append(form('B', 0xE001, {0: a0, 1: a1}, 'E0 key %04X from %04X' % (a0, a1)))
    for a1 in (0x0000, 0x00FB, 0x00FC, 0xFFFF):
        F.append(form('B', 0xE700, {0: 0x0000, 1: a1}, 'E7 length %04X' % a1))
    for a0, a1 in ((0, 0x28), (0, 0x35), (0, 0x81), (1, 0x28), (0, 0), (0, 0xFFFF), (0, 0x28)):
        F.append(form('B', 0xEC00, {0: a0, 1: a1}, 'EC (%X, %X)' % (a0, a1)))
    for lo, a0 in ((0, 1), (1, 0), (1, 0x19), (1, 0x1A), (5, 0x19), (5, 0xFFFF)):
        F.append(form('B', 0xD000 | lo, {0: a0, 1: 0x3C, 2: 0x40}, 'D0 %02X voice %04X' % (lo, a0)))
        F.append(form('B', 0x9000 | lo, {0: a0}, 'D0 %02X without the argument flag' % lo))
    for lo in sorted({0, 1, 2, max(1, nsfx - 1) & 0xFF, nsfx & 0xFF, (nsfx + 1) & 0xFF, 0x7F, 0x80, 0x81, 0xFF}):
        F.append(form('B', 0x9100 | lo, {}, 'D1 id %02X without arguments' % lo))
        for a0 in (0x0000, 0x0080, 0x0100, 0x01FF):
            F.append(form('B', 0xD100 | lo, {0: a0, 1: 0x80, 2: 0x80}, 'D1 id %02X level %04X' % (lo, a0)))
    for lo in (0, 1, 0xFF):
        F.append(form('B', 0x9200 | lo, {}, 'D2 %02X' % lo))
        F.append(form('B', 0xD300 | lo, {0: 0x80, 1: 0x10}, 'D3 %02X' % lo))
        F.append(form('B', 0x9300 | lo, {}, 'D3 %02X without arguments' % lo))
    for lo in (0, 1, 2, 3, 0xFF):
        F.append(form('B', 0x9500 | lo, {}, 'D5 %02X without arguments' % lo))
        F.append(form('B', 0xD500 | lo, {0: 0x40, 1: 0x10}, 'D5 %02X' % lo))
    for lo in range(0, 10):
        F.append(form('B', 0x9600 | lo, {}, 'D6 %02X without arguments' % lo))
        F.append(form('B', 0xD600 | lo, {0: 0x0001, 1: 0x0000}, 'D6 %02X' % lo))
    for a0 in (0x0000, 0x0019, 0x001A, 0x0099, 0x009A, 0x007F):
        F.append(form('B', 0xD605, {0: a0, 1: 1}, 'D6 05 voice %04X' % a0))
    for lo in (0x00, 0x7F, 0x80, 0xFF):
        if lo in (0x00, 0x7F):
            F.append(form('B', 0x8800 | lo, {}, '88 %02X' % lo))
        F.append(form('B', 0x8900 | lo, {}, 'C9 %02X without arguments' % lo))
        F.append(form('B', 0xC900 | lo, {0: 0x40, 1: 0x02}, 'C9 %02X' % lo))
        F.append(form('B', 0x8A00 | lo, {}, 'CA %02X without arguments' % lo))
        F.append(form('B', 0xCA00 | lo, {0: 0xC0, 1: 0x02}, 'CA %02X' % lo))
    F.append(form('B', 0x8802, {}, '88 02 (the game\'s audio mode)'))
    for n in sorted({0, 1, nbgm, nbgm + 1, 0x3F} | set(nulls[:2])):
        for hi in (0x00, 0x80):
            F.append(form('B', 0x8C00 | hi | n, {}, '8C %02X%s%s' % (n, ' loop' if hi else '', ' (a null slot)' if n in nulls else '')))
            F.append(form('B', 0x8E00 | hi | n, {}, '8E %02X%s' % (n, ' loop' if hi else '')))
    for lo in (0x00, 0x01, 0x20, 0xFF):
        F.append(form('B', 0x8D00 | lo, {}, '8D %02X' % lo))
    for lo in (0x00, 0x3F, 0x40, 0xFF):
        F.append(form('B', 0xAD00 | lo, {}, 'AD %02X' % lo))
    for w in (0xAF00, 0xAE00, 0xAF01, 0xB000, 0xB100, 0xF000, 0xF100):
        F.append(form('B', w, {}, '%04X' % w))
    for blk in (0, 1, 2, 12325, 12326, 12327, 0x7FFF, 0xFFFF):
        F.append(form('B', 0xF200, {0: blk}, 'F2 block %d' % blk))
    if src['zoom'] is not None:             # the zoom: F4 on the game's picture, F5 / B6 with and without a session
        h, l = srcs(src['zoom'])
        F.append(form('B', 0xF400, {0: h, 1: l}, 'F4 the game\'s first zoom picture', rom_args=True))
    for args in ({0: 0x0100, 1: 0x0100, 2: 0x0020, 3: 0x0020}, {0: 0, 1: 0, 2: 0, 3: 0}):
        F.append(form('B', 0xF500, args, 'F5 (%04X, %04X, %04X, %04X)' % tuple(args[i] for i in range(4))))
    F.append(form('B', 0xB600, {}, 'B6'))
    F.append(form('B', 0xF600, {}, 'B6 with the argument flag'))
    F.append(form('B', 0xB600, {}, 'B6 again (no session)'))
    if src['other'] is not None:
        h, l = srcs(src['other'])
        F.append(form('B', 0xF400, {0: h, 1: l}, 'F4 a source of another type', rom_args=True))
    for s in (0x800000, 0x800002):
        F.append(form('B', 0xF400, {0: s >> 16, 1: s & 0xFFFF}, 'F4 source %06X' % s))
    for idx in range(0x40):                 # mailbox A: every index (its low byte dropped), the request bit
        if idx in (0x05, 0x14, 0x28):
            continue
        F.append(form('A', idx << 8 | 0x80, None, 'mailbox A index %02X' % idx))
        F.append(form('A', 0xC000 | idx << 8 | 0xFF, None, 'mailbox A index %02X, high bits and low byte set' % idx))
    for w in (0x0000, 0x0100, 0x9400, 0xDA7F):
        F.append(form('A', w, None, 'mailbox A without the request bit'))
    F.append(form('B', 0x8400, {}, '84', last=1))
    F.append(form('A', 0x0480, None, 'mailbox A 84', last=1))
    F.append(form('B', 0x9494, {}, '94 on mailbox B (the frame tick path)', last=2))
    F.append(form('B', 0xD400, {0: 1}, 'D4 on mailbox B (the frame tick path)', last=2))
    F.append(form('A', 0x9494, None, '9494 (the frame tick)', last=2))
    F.append(form('A', 0x1480, None, 'mailbox A index 14', last=2))
    for w in (0xA400, 0xA401, 0xE400, 0xA600, 0xE600, 0xA900, 0xE900, 0xAA00, 0xAA57, 0xEA58, 0xA800, 0xE858):
        F.append(form('B', w, {}, 'MegaWire %04X' % w))
    F.append(form('A', 0x2880, None, 'mailbox A A8'))
    F.append(form('B', 0xE700, {0: 0, 1: 0x10}, 'E7 (a send)'))
    F.append(form('B', 0xE700, {0: 0, 1: 0x10}, 'E7 again (send pending)'))
    F.append(form('B', 0xA900, {}, 'A9 after E7'))
    if state == 'post':                     # the corners where the chip writes its own live RAM
        F.append(form('B', 0xEC00, {0: 0, 1: 0x80}, 'EC (0, 80): above card 5\'s cap (allow-list B48)', last=4))
        F.append(form('B', 0xEC00, {0: 0, 1: 0x28}, 'EC (0, 28) after it (allow-list B48)', last=4))
        for k, s in (('0x81', s81), ('0x80', s80)):
            if s is not None:
                h, l = srcs(s)
                F.append(form('B', 0xF400, {0: h, 1: l}, 'F4 a %s stream that is no zoom picture (allow-list B57)' % k,
                              last=4, rom_args=True))
        F.append(form('B', 0xC600, dict(enumerate(c6)), 'a second C6', last=4, rom_args=True))
    if state == 'post':
        F.append(form('B', 0xA858, {}, 'A858 (the MegaWire screen)', last=5))
    else:
        F.append(form('B', 0xC600, dict(enumerate(c6)), 'C6 (the set-up)', last=6, rom_args=True))
    return sorted(F, key=lambda f: f[4])


def outcome(mbx, word, regs, evs):
    """the answer in words: refused k / accepted / finish only"""
    if not ((word & 0x8000) if mbx == 'B' else (word & 0x80)):
        return 'finish only'
    bit = 0x400 if mbx == 'A' else 0x200
    codes = [c & 0xFF for c, a, b in evs if (c >> 30) == 0 and (c & 0xFF) <= 0xF]   # the event's low byte (F4's type
                                                                                  # refusal also carries the source's
                                                                                  # high byte in bits 8-15)
    if regs[0x06] & bit:
        return 'refused %s' % (codes[0] if codes else '?')
    return 'accepted'


def align(chip, ours, c0, r0, hold=False):
    """the aligned sampling (the docstring): run both sides on until each has completed the same number of MegaWire
    task runs since the post (c0: the chip's count then, r0: ours' mw_ran then), at least one more than any run that
    still had work waiting, none half done or held back. Returns (ok, chip runs, ours' runs, aligned: True when either
    side was run on). Before the chip's first MegaWire init its timer is off: no task there yet, nothing to wait for."""
    if not chip.mw_timer_on():
        return True, 0, (ours.mw_started() - r0) & 0xFF, False
    if hold and chip.mw_runs == c0 and ours.mw_started() == r0 and not ours.mw_busy() and not ours.b.rd8('mw_aa_pending'):
        return True, 0, 0, False            # a form that leaves its send for the next form, no task run in its window
    ok, target, moved = True, 0, False
    for _ in range(ALIGN_MAX_RUNS + 1):
        nc, no = chip.mw_runs - c0, (ours.mw_started() - r0) & 0xFF
        busy, work = ours.mw_busy(), chip.mw_work() or ours.mw_work()
        t = max(nc, no, target)
        if nc == no == t and not busy:
            if not work:
                return ok, nc, no, moved
            t += 1                          # equal, but the next run has work on a side: one more each
        elif t == 0:
            t = 1                           # ours has a run held back or half done: the chip runs one too
        if t > ALIGN_MAX_RUNS:
            break
        if nc < t:
            ok &= chip.mw_run_to(c0 + t)
        if no < t or ours.mw_busy():
            ok &= ours.mw_run_to(r0, t)
        target, moved = t, True
        if not ok:
            break
    return False, chip.mw_runs - c0, (ours.mw_started() - r0) & 0xFF, moved


def b59_save_ok(mw_on, mbx, word, s0c, s1c, s0o, s1o):
    """allow-list B59 (the docstring's classes): AA58 on mailbox B, on an image that runs the cart's MegaWire code; ours
    changed nothing in the save; every byte the chip changed and every byte that ends different lies in slot 9's two
    copies"""
    if not (mw_on and mbx == 'B' and word == 0xAA58 and s1o == s0o):
        return False
    in9 = lambda i: any(lo <= i < hi for lo, hi in SLOT9)
    return all(in9(i) for i in range(len(s1c)) if s1c[i] != s1o[i] or s1c[i] != s0c[i])


def a858_page_ok(mw_on, state, mbx, word, evc, evo, chip_lr, page_a_missing):
    """the A858 page rule (the docstring's classes): the post-C6 A858 on mailbox B, on an image that runs the cart's
    MegaWire code; the chip's only event is the page loader's fatal code for page A (its caller returns to 0x0802242C)
    while our model's page A is not a packed block; ours raised none"""
    return bool(mw_on and state == 'post' and mbx == 'B' and word == 0xA858 and evc == [A858_PAGE_EVENT] and not evo
                and chip_lr == [A858_PAGE_LR] and page_a_missing)


def rule_controls():
    """--negative: each named exception must take its own case and nothing near it (synthetic inputs)"""
    z = bytes(0x1000)
    def put(b, at, n=1, v=0x5A):
        b = bytearray(b)
        for i in range(at, at + n):
            b[i] = v
        return bytes(b)
    rec = put(put(z, 0xA00, 0x52), 0xA80, 0x30)
    cases = [('B59: the record in slot 9', True, b59_save_ok(True, 'B', 0xAA58, z, rec, z, z)),
             ('B59: a byte between the copies (0xA60)', False, b59_save_ok(True, 'B', 0xAA58, z, put(rec, 0xA60), z, z)),
             ('B59: a byte before slot 9 (0x9FF)', False, b59_save_ok(True, 'B', 0xAA58, z, put(rec, 0x9FF), z, z)),
             ('B59: a byte after slot 9 (0xAE0)', False, b59_save_ok(True, 'B', 0xAA58, z, put(rec, 0xAE0), z, z)),
             ('B59: ours wrote a byte', False, b59_save_ok(True, 'B', 0xAA58, z, rec, z, put(z, 0x10))),
             ('B59: an older difference outside slot 9', False, b59_save_ok(True, 'B', 0xAA58, put(z, 0x100), put(rec, 0x100),
                                                                          z, z)),
             ('B59: AA57', False, b59_save_ok(True, 'B', 0xAA57, z, rec, z, z)),
             ('B59: mailbox A', False, b59_save_ok(True, 'A', 0xAA58, z, rec, z, z)),
             ('B59: no MegaWire code', False, b59_save_ok(False, 'B', 0xAA58, z, rec, z, z))]
    ev, lr = [A858_PAGE_EVENT], [A858_PAGE_LR]
    cases += [('A858: the code of the page loader', True, a858_page_ok(True, 'post', 'B', 0xA858, ev, [], lr, True)),
              ('A858: the same code with b = 0', False, a858_page_ok(True, 'post', 'B', 0xA858, [(0x40000007, 0x80, 0)], [],
                                                                   lr, True)),
              ('A858: the code for page B', False, a858_page_ok(True, 'post', 'B', 0xA858, [(0x40000000, 0x80, 0x28)], [],
                                                         [0x08022440], True)),
              ('A858: another caller', False, a858_page_ok(True, 'post', 'B', 0xA858, ev, [], [0x08022440], True)),
              ('A858: ours raised an event', False, a858_page_ok(True, 'post', 'B', 0xA858, ev, ev, lr, True)),
              ('A858: a second chip event', False, a858_page_ok(True, 'post', 'B', 0xA858, ev + [(7, 0, 0)], [], lr + lr,
                                                              True)),
              ('A858: the model has page A', False, a858_page_ok(True, 'post', 'B', 0xA858, ev, [], lr, False)),
              ('A858: before C6', False, a858_page_ok(True, 'pre', 'B', 0xA858, ev, [], lr, True)),
              ('A858: another form', False, a858_page_ok(True, 'post', 'B', 0xA857, ev, [], lr, True)),
              ('A858: no MegaWire code', False, a858_page_ok(False, 'post', 'B', 0xA858, ev, [], lr, True))]
    return cases


def sweep(state, chip, ours, F, test_image, log, clear=True, aligned=True):
    res = {'forms': 0, 'equal': 0, 'inside': 0, 'differ': [], 'classes': collections.Counter(), 'rows': [],
           'class_rows': [], 'aligned': 0, 'aligned_runs': [0, 0]}
    mw_on = ours.mw_running()
    aligned = aligned and mw_on
    ver = lambda r: 0 if (r[0x10012] << 8 | r[0x10013]) == 0xFFFF else (r[0x1000A] << 8 | r[0x1000B])
    ver_ours = ver(ours.rom)
    same_ver = ver(open(chip.rom_path, 'rb').read()) == ver_ours
    save_n = 0x1000 if test_image else 0x2000
    for mbx, word, args, what, last, rom_args in F:
        for side in (chip, ours) if clear else ():
            side.w68(0x1F10, 0)
            side.w68(0x1F16, 0)
        k0c, k0o = chip.counters(), ours.counters()
        r0c, r0o = chip.ram(), ours.ram()
        idx = (word >> 8) & 0x3F
        if idx in (0x34, 0x35, 0x36):
            z0c, z0o = chip.zoom(), ours.zoom()
        s0c, s0o = chip.save()[:save_n], ours.save()[:save_n]
        chip.take()
        ours.take()
        c0, r0 = chip.mw_runs, (ours.mw_started() if aligned else 0)
        okc, idc = chip.post(mbx, word, args)
        try:
            oko, ido = ours.post(mbx, word, args)
            al = align(chip, ours, c0, r0, hold=what in HOLD_FORMS) if aligned else (True, 0, 0, False)
        except ours.Stop:
            res['differ'].append((state, mbx, '%04X' % word, what, ['ours stopped: %s' % ours.b.violations[:3]]))
            log('DIFFER %s %s %04X %s: ours stopped %s' % (state, mbx, word, what, ours.b.violations[:3]))
            break
        if al[3]:
            res['aligned'] += 1
            res['aligned_runs'][0] += al[1]
            res['aligned_runs'][1] += al[2]
        chip_lr = list(chip.ev_lr)
        rwc, evc = chip.take()
        rwo, evo = ours.take()
        rc, ro = chip.regs(), ours.regs()
        r1c, r1o = chip.ram(), ours.ram()
        s1c, s1o = chip.save()[:save_n], ours.save()[:save_n]
        k1c, k1o = chip.counters(), ours.counters()
        mwf = idx in MW_IDX and not mw_on
        bad, cls = [], set()
        if not (okc and idc):
            bad.append('chip: not finished / job not ended')
        if not (oko and ido):
            bad.append('ours: not finished / job not ended %s' % (ours.b.violations[:2] or ''))
        if not al[0]:
            bad.append('aligned sampling: the sides did not reach the same MegaWire task runs (chip %d, ours %d)' % al[1:3])
        for off in (0x04, 0x06, 0x0A, 0x0C):
            if rc[off] != ro[off]:
                if off == 0x06 and not mw_on and not ((rc[off] ^ ro[off]) & ~MW_FE6):
                    cls.add('megawire: status bits')
                    continue
                bad.append('$1F%02X chip %04X ours %04X' % (0xE0 + off, rc[off], ro[off]))
        dkc = [y - x for x, y in zip(k0c, k1c)]
        dko = [y - x for x, y in zip(k0o, k1o)]
        if dkc[11] != dko[11]:
            cls.add('B12: counter 11 (the audio underrun count)')
            dkc[11] = dko[11] = 0
        if dkc != dko:
            bad.append('counted chip %s ours %s' % ({i: v for i, v in enumerate(dkc) if v}, {i: v for i, v in enumerate(dko) if v}))
        evc_cmp = [e for e in evc if (e[0] & 0xFF) != 0x0B]
        evo_cmp = [e for e in evo if (e[0] & 0xFF) != 0x0B]
        if a858_page_ok(mw_on, state, mbx, word, evc_cmp, evo_cmp, chip_lr, chip.screen_page_a_missing()):
            cls.add('A858 page: our model of the chip has no screen pages (its fatal code 0x40000007)')
        elif evc_cmp != evo_cmp:
            bad.append('events chip %s ours %s' % (['%X' % c for c, a, b in evc][:6], ['%X' % c for c, a, b in evo][:6]))
        if rwc != rwo:
            bad.append('register writes chip %s ours %s' % (rwc[:8], rwo[:8]))
        diff = []
        for a in range(0, 0x1FE0, 2):
            vc, vo = r1c[a:a + 2], r1o[a:a + 2]
            ch_c, ch_o = vc != r0c[a:a + 2], vo != r0o[a:a + 2]
            if not (ch_c or ch_o) or vc == vo or CNT_COPY[0] <= a < CNT_COPY[1]:
                continue
            if a == 0x1B32 and mw_on and not same_ver and struct.unpack('<H', vo)[0] == ver_ours:
                continue                    # the version word comes from each side's own ROM (tests/equiv/mwboot.py)
            if MW_TASK[0] <= a < MW_TASK[1] and not ch_o and not mw_on:
                cls.add('megawire: task publication')
            elif a == MW_LEN and idx == 0x06 and not ch_o and not mw_on:
                cls.add('megawire: C6 init')
            elif VU_FEED[0] <= a < VU_FEED[1]:
                cls.add('B12: VU feed')
            elif JOB_WORDS[0] <= a < JOB_WORDS[1] and not ch_o:
                cls.add('B12: the $1C00 words')
            elif PACKET[0] <= a < PACKET[1] and idx == 0x14:
                cls.add('B12: Z80 packet page')
            else:
                diff.append(a)
        if diff:
            bad.append('cart RAM %d words differ (%s)' % (len(diff), ', '.join(
                '$%04X chip %s->%s ours %s->%s' % (a, r0c[a:a + 2][::-1].hex(), r1c[a:a + 2][::-1].hex(),
                                                 r0o[a:a + 2][::-1].hex(), r1o[a:a + 2][::-1].hex()) for a in diff[:4])))
        if idx in (0x34, 0x35, 0x36):
            zc, zo = chip.zoom(), ours.zoom()
            for nm, x0, x, y0, y in (('stamps', z0c[0], zc[0], z0o[0], zo[0]),
                                     ('F4 source and save', z0c[1], zc[1], z0o[1], zo[1])):
                n = sum(1 for i in range(len(x)) if (x[i] != x0[i] or y[i] != y0[i]) and x[i] != y[i])
                if n:
                    bad.append('zoom block %s: %d bytes differ' % (nm, n))
        if (s1c != s0c or s1o != s0o) and s1c != s1o:
            if b59_save_ok(mw_on, mbx, word, s0c, s1c, s0o, s1o):
                cls.add('B59: the MegaWire record save of AA58 to the EEPROM slot 9 (%d bytes)' % sum(
                    1 for x, y in zip(s1c, s1o) if x != y))
            else:
                bad.append('the save differs (%d bytes)' % sum(1 for x, y in zip(s1c, s1o) if x != y))
        res['forms'] += 1
        oc = outcome(mbx, word, rc, evc)
        row = {'state': state, 'mbx': mbx, 'word': '%04X' % word, 'what': what, 'chip': oc,
               'ours': outcome(mbx, word, ro, evo),
               'args': None if args is None else ('from the ROM' if rom_args else ' '.join('%04X' % x for x in args[:4])),
               'classes': sorted(cls), 'equal': not bad, 'aligned': list(al[1:3]) if al[3] else None}
        if bad and mwf:
            cls.add('megawire: the form')
            row['classes'] = sorted(cls)
            row['equal'] = 'megawire'
            bad = []
        for c in cls:
            res['classes'][c] += 1
        if cls:
            res['class_rows'].append('%s %s %04X %s: %s' % (state, mbx, word, what, ', '.join(sorted(cls))))
        if not bad and not cls:
            res['equal'] += 1
        elif not bad:
            res['inside'] += 1
        else:
            res['differ'].append((state, mbx, '%04X' % word, what, bad))
            log('DIFFER %s %s %04X %s: %s' % (state, mbx, word, what, '; '.join(bad)))
        res['rows'].append(row)
    return res


def chip_counts(hd):
    """the module count and its null slots (the cart's BGM pointer table in the chip's RAM after its C6: the count,
    then a pointer per module) and the SFX count: the tables the image reads from the ROM"""
    c = Chip(hd)
    if not c.h.boot_c6():
        setup_error('the chip did not finish its C6')
    n = c.m.mu.mem_read(0x20012F94, 1)[0]
    ptr = struct.unpack('<%dI' % n, bytes(c.m.mu.mem_read(0x20012F98, 4 * n)))
    return n, c.m.mu.mem_read(0x2000CD1C + 7, 1)[0], [i + 1 for i, v in enumerate(ptr) if v == 0]


def run_state(state, a, build, rom, src, counts, test_image, log):
    chip = Chip(a.hd)
    ours = Ours(build, rom, a.seed, sram_image(a, build))
    c6 = chip.c6_args()
    aligned = not a.no_align and ours.mw_running()
    boot_al = []
    if state == 'post':
        for w, args in ((0x810E, [0] * 16),) * 3 + ((0xC600, c6 + [0, 0]),):
            c0, r0 = chip.mw_runs, (ours.mw_started() if aligned else 0)
            okc, idc = chip.post('B', w, args)
            oko, ido = ours.post('B', w, args, job_s=60.0)
            if not (okc and idc and oko and ido):
                setup_error('the boot post %04X did not end on both sides (chip %s %s, ours %s %s)' % (w, okc, idc, oko, ido))
            if aligned:                     # the boot posts are aligned too (the docstring)
                al = align(chip, ours, c0, r0)
                if not al[0]:
                    setup_error('the boot post %04X: the sides did not reach the same MegaWire task runs (chip %d, '
                                'ours %d)' % ((w,) + al[1:3]))
                boot_al.append('%04X: %d / %d' % (w, al[1], al[2]))
        chip.take()
        ours.take()
    F = [f for f in forms_for(state, src, counts[0], counts[1], counts[2], c6) if not any(k in f[3] for k in a.skip)]
    r = sweep(state, chip, ours, F, test_image, log, clear=not a.no_clear, aligned=aligned)
    r['boot_aligned'] = boot_al
    r['mw_running'] = ours.mw_running()
    r['counters_end'] = {'chip': chip.counters(), 'ours': ours.counters()}
    return r


def table_md(rows, n_states):
    out = ['# The mailbox gate tables', '',
           'Written by `tests/equiv/gatelock.py --table` from the cart chip\'s behaviour and checked against it on',
           'every run (`tests/run_all.py`: `--check-table`). For each command index, on',
           'mailbox B (`$1FEA`) and mailbox A (`$1FEC`), before C6 (after the app init) and after the game\'s own boot posts',
           'and C6, every form the check posts and the cart chip\'s answer: `accepted`, `refused N` (2 default, 5 queue',
           'full, 6 not ready, 7 bad arguments: `$1FE6` bit 9 for B, 10 for A, and the event N | r6 << 8) or `finish only`',
           '(no request bit). The forms are posted one after another, so an answer can depend on the forms before it (a',
           'second E7 while a send is pending, B6 without a session, 8C while a song is loading). Our firmware gives the same',
           'answer, register words, events, register writes, cart RAM, zoom block and save in every row. A build that',
           'runs the cart\'s MegaWire code is compared on the MegaWire rows too, each sampled after both sides\' next',
           'MegaWire task runs where the task has work waiting (the aligned sampling, tests/equiv/gatelock.py); on a',
           'build without it those rows are marked `(megawire)`. Two named exceptions are listed in gatelock.py',
           '(docs/ALLOWLIST.md, row B59, and the A858 page rule). Arguments read from the player\'s ROM (stream addresses,',
           'C6\'s arguments) are not written here.', '']
    by = collections.OrderedDict()
    for r in rows:
        by.setdefault(int(r['word'], 16) >> 8 & 0x3F, []).append(r)
    for idx in sorted(by):
        out += ['## Index %02X' % idx, '', '| state | mailbox | word | arguments | form | the cart chip |', '|---|---|---|---|---|---|']
        grp = collections.OrderedDict()     # the low-byte classes of one flag and one answer: one row
        for r in by[idx]:
            st = 'before C6' if r['state'] == 'pre' else 'after C6'
            ans = r['chip'] + (' (megawire)' if r['equal'] == 'megawire' else '')
            if r['what'].startswith('index '):
                w = int(r['word'], 16)
                grp.setdefault((st, r['mbx'], '%02Xxx' % (w >> 8), ans), []).append('%02X' % (w & 0xFF))
            else:
                grp[(st, r['mbx'], r['word'], ans, r['args'] or '-', r['what'], len(grp))] = None
        for key, lows in grp.items():
            if lows is None:
                st, mbx, word, ans, args, what, _ = key
                out.append('| %s | %s | %s | %s | %s | %s |' % (st, mbx, word, args, what, ans))
            else:
                st, mbx, word, ans = key
                out.append('| %s | %s | %s | - | low byte %s | %s |' % (st, mbx, word, ' '.join(lows), ans))
        out.append('')
    return '\n'.join(out)


def table_rows(path):
    rows = []
    for ln in open(path, encoding='utf-8'):
        if ln.startswith('| before C6 |') or ln.startswith('| after C6 |'):
            rows.append(tuple(x.strip() for x in ln.strip().strip('|').split('|')))
    return rows


def sram_image(a, build):
    """the build's MegaWire SRAM image (img/sram.bin), or None (no file, an empty one, or --no-sram)"""
    p = os.path.join(build, 'img', 'sram.bin')
    if getattr(a, 'no_sram', False) or not os.path.isfile(p) or not os.path.getsize(p):
        return None
    return open(p, 'rb').read()


def run(a, build, rom, src, counts, states, log):
    test_image = 'dbgsave_now' in open(os.path.join(build, 'main.nm')).read()
    allr = {}
    t0 = time.time()
    for st in states:
        r = allr[st] = run_state(st, a, build, rom, src, counts, test_image, log)
        print('gatelock %s %s: %d forms: %d equal the chip, %d differ only inside the listed classes, %d differ outside '
              'them; classes: %s; MegaWire code running: %s; aligned sampling: %s (%.0f s)' % (
            os.path.basename(build), st, r['forms'], r['equal'], r['inside'], len(r['differ']),
            ', '.join('%s %d' % kv for kv in sorted(r['classes'].items())) or 'none', r['mw_running'],
            ('%d forms sampled after the next MegaWire task runs (chip %d runs, ours %d)%s' % (
                r['aligned'], r['aligned_runs'][0], r['aligned_runs'][1],
                '; boot posts chip / ours runs: ' + ', '.join(r['boot_aligned']) if r['boot_aligned'] else ''))
            if r['mw_running'] and not a.no_align else 'off', time.time() - t0),
            flush=True)
    return allr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default=os.path.join(ROOT, 'build', 's1', 'pocket88k', 's5release'))
    ap.add_argument('--rom')
    ap.add_argument('--capture')
    ap.add_argument('--state', default='both', choices=('pre', 'post', 'both'))
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--table')
    ap.add_argument('--check-table')
    ap.add_argument('--json')
    ap.add_argument('--negative', action='store_true')
    ap.add_argument('--skip', action='append', default=[], help='leave out the forms whose text contains this')
    ap.add_argument('--no-clear', action='store_true', help='the 68000 side does not clear $1F10 / $1F16 before a form')
    ap.add_argument('--no-sram', action='store_true', help='leave the SRAM empty even when the build has a MegaWire image')
    ap.add_argument('--no-align', action='store_true', help='sample every form at its normal point only (no aligned '
                    'sampling of the MegaWire task: a diagnostic, the gate is the aligned one)')
    a = ap.parse_args()
    lp = os.path.join(ROOT, 'paths.local.json')
    loc = json.load(open(lp)) if os.path.exists(lp) else {}
    a.hd = os.environ.get('PAPRIUM_HARNESS_DIR') or loc.get('harness_dir')
    if not a.hd or not os.path.isdir(a.hd):
        setup_error('paths.local.json "harness_dir" (the comparison harness) missing')
    romf = a.rom or loc.get('refs', {}).get('rom')
    cap = a.capture or loc.get('equiv', {}).get('capture_solo')
    if not romf or not os.path.exists(romf) or not cap or not os.path.exists(cap):
        setup_error('no ROM / solo capture (--rom / --capture or paths.local.json refs.rom, equiv.capture_solo)')
    if not os.path.exists(os.path.join(a.build, 'main.nm')):
        setup_error('no built image at %s' % a.build)
    rom = open(romf, 'rb').read()
    src = rom_sources(rom, cap)
    if not (src['t80'] and src['t81'] and src['zoom'] is not None and src['other'] is not None):
        setup_error('the solo capture gave no DA stream of each type or no zoom picture')
    counts = chip_counts(a.hd)
    print('the chip after C6: %d modules (%d null slots), SFX count %d; sources: DA 0x80 and 0x81 streams, the first '
          'zoom picture, another type (all from the ROM)' % (counts[0], len(counts[2]), counts[1]))
    if a.negative:
        base = os.path.dirname(a.build)
        cmd = [sys.executable, '-I', '-B', os.path.join(ROOT, 'tools', 'fwbuild.py'), 's1', '--images-only',
               '--out', os.path.dirname(os.path.dirname(base))]
        for v, _ in NEG:
            cmd += ['--variant', v]
        rr = subprocess.run(cmd, capture_output=True, text=True)
        if rr.returncode:
            setup_error('building the planted images failed:\n%s' % (rr.stdout + rr.stderr)[-2000:])
        cases = rule_controls()
        bad = [c for c in cases if c[1] != c[2]]
        ok = not bad
        print('%-4s the controls of the named exceptions: %d cases, %d wrong%s' % (
            'PASS' if ok else 'FAIL', len(cases), len(bad), ''.join('; ' + c[0] for c in bad)))
        for v, at in NEG:
            r = run(a, os.path.join(base, v), rom, src, counts, ('post',), lambda s: None)['post']
            hit = [d for d in r['differ'] if at in d[3]]
            caught = bool(hit)
            ok &= caught
            print('%-4s %s: %d forms differ from the chip, %s at its planted form (%s)' % (
                'PASS' if caught else 'FAIL', v, len(r['differ']), len(hit), at))
        print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
        sys.exit(0 if ok else 1)
    states = ('pre', 'post') if a.state == 'both' else (a.state,)
    allr = run(a, a.build, rom, src, counts, states, print)
    rows = [x for st in states for x in allr[st]['rows']]
    for st in states:
        for ln in allr[st]['class_rows']:
            print('CLASS ' + ln)
    if a.table:
        open(a.table, 'w', newline='\n', encoding='utf-8').write(table_md(rows, len(states)))
    tab_ok = True
    if a.check_table:
        want = table_rows(a.check_table)
        got = [tuple(x.strip() for x in ln.strip().strip('|').split('|'))
               for ln in table_md(rows, len(states)).splitlines() if ln.startswith('| before C6 |') or ln.startswith('| after C6 |')]
        tab_ok = want == got
        print('gate tables %s: %d rows, %d in this run%s' % (a.check_table, len(want), len(got), '' if tab_ok else ', DIFFERENT'))
    if a.json:
        json.dump(allr, open(a.json, 'w'), indent=1, default=str)
    ok = tab_ok and all(not allr[st]['differ'] and allr[st]['forms'] for st in states)
    print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
