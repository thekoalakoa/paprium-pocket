#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""fuzz_s1.py - the stage-1 TEST / RELEASE image on the stage-1 board model (tests/equiv/rtlmodel.py), the 68000 side
played from a GPGX capture with the game's post protocol, interrupts taken at random instruction boundaries
(docs/STAGE1_PLAN.md section 4.7 defines FZ1-FZ12; plus the GO check). The stage-1 image is the FW_S1 build of our new
firmware (stages are the steps of the 0.3.0 work, README.md "Terms": stage 3 added the unpackers, the zoom, the
saves and MegaWire, stage 5 the song engine); GPGX is the Genesis Plus GX emulator the capture was recorded in; L1,
L2c and the thread are the scheduler's levels (core/sched/sched.h).

    python -I -B tests/equiv/fuzz_s1.py [--build build/s1/pocket72k/test] [--seeds N] [--frames F] [--wdog] [--json OUT]
    python -I -B tests/equiv/fuzz_s1.py --negative       every planted-bug image fails with its invariant, the clean passes
                                                         (test_bug_l1 replays to frame 1,200 at least, test_bug_l1len
                                                         to 2,000: FZ12 needs the intro's / play's sprite frames)
    python -I -B tests/equiv/fuzz_s1.py --q1             the battery save on RV32 (B Jam's Q1): a 0.2.x 4 KB save loads
                                                         unchanged, a fatal halt reaches the .sav, a Soft Reset keeps it;
                                                         TEST's SAT snapshot layout 2 (q1_save.py section H)

Inputs: paths.local.json "equiv" (capture_solo, rom), as tests/equiv/slice.py. The planted-bug images are on-demand
fwbuild variants (test_bug_*): --negative rebuilds them all first, and the clean image when it is missing
(tools/fwbuild.py s1 --images-only); a planted-bug image left from older sources would test those sources.

The 68000 (a model written from docs/CART_FPGA_SPEC.md sections 7-8 and the census): the capture's records in order, in
"fast mode" (a post as soon as the protocol allows, plus a random gap): a cart RAM write is applied; a $1FEC write is a
mailbox-A post (the 9494), made when the previous A post is finished; a $1FEA post is made when the previous B post is
finished and its waits are done: after DA, C6, DF and E0 (accepted) the game spins on $1FE6 bit 14; after DB06 and DA07
(accepted) it polls busy ($1FE4 bit 2) for at most 65,534 loops (~0.5 s), then reads the window (one word per ~84 MCU
cycles); the AF (and B1) stream is read by the next VBlank's DMA list: at the next frame record, each window descriptor
the firmware left in cart RAM ($1400, count $1F16) reads its 256 words, the first no earlier than DMA_FIRST after the
post's finish and each next DMA_STEP later (section 4.2 of the decoder specification, not in this tree: the game waits
for the reply, then for the next VBlank, and its first flush DMA comes >= 110.7 us after VBlank start; the next block >=
175 us after; estimated lower bounds, the game's own
structure); F2's 512 words at the next frame record, no earlier than F2_DMA_MIN after its finish (the game waits for the
next VBlank: $B3CEC-$B3D16). Random on top: segment lengths (1-48 instructions
around 68000 actions, up to 400 while it waits on a long job), sub-CPU SENDs (CAUSE.S, after the sub's release), extra
mailbox-A words without the request bit ($9400: L1 at random instants), Pocket-menu openings (the 68000 and the sub
paused, MENU = GPIO bit 24).

Invariants (docs/STAGE1_PLAN.md section 4.7, on the full stage-1 image):
  FZ1  every $1FEA post gets exactly one MCU $1FEA := 0, refusals included; no finish without a post.
  FZ2  at the finish of a post that queued a job (the job queue's write index moved in its L1), $1FE6 bit 14 is set.
  FZ3  a DA07 job's GO lands before the job step clears $1FE6 bit 14; the 68000 never sees "ready" (busy 0) for an
       accepted DB06 / DA07 before that post's GO (no stale ready); no busy timeout.
  FZ4  wherever MIE = 1 after the first job: $1FE6 bit 14 = the job queue is not empty; bit 14 never stuck.
  FZ5  the MCU reads a mailbox only after acknowledging its CAUSE bit (rtlmodel); every post dispatched before its
       finish; every post finished; every SEND after the first brain call is followed by a brain call.
  FZ6  every $1FEC post gets exactly one $1FEC := 0.
  FZ7  wherever MIE = 1: $1FE6 / $1FE4 == the status helper's shadows (status.c sh_fe6 / sh_fe4).
  FZ8, FZ9  stage 1 has no song tick (audio_tick_begin returns 0): held posts and urgent promotions stay 0; the
       probe image proves them (fuzz_sched.py). Reported as vacuous, failed if either is ever nonzero.
  FZ10 (--wdog, a scenario after the replay) the Pocket menu open for 45 TIM7 periods with no 9494: no trip; then
       the menu closed and no 9494: the watchdog trips after 39-41 periods, never earlier (a fatal halt, TEST: in the
       debug save).
  FZ11 the stack floor word intact; the measured high-water depth <= fwstack's static bound for the image.
  FZ12 the L1 budget (docs/STAGE1_PLAN.md: 0.32 ms; docs/CART_FPGA_SPEC.md 6 / 7, docs/MCU_INTERFACE.md 6.2): no post
       body in L1 (disp_post's entry to its return into l1_mei) longer than L1_BUDGET model cycles (0.32 ms at the
       hardware's CPI: the model's CPI 6 x HW_CPI_RATIO, measured against a co-simulation of the RTL and the firmware),
       timed at the model's step boundaries; and no block decoder instruction (the stage-1 images: ppm_unpack_scal; the
       stage-5 images since stage 3: the decoders that work as the cart chip's 0x80 / 0x81 decoders, song_unpack80 /
       song_unpack81) inside an L1 body: the decodes are the board's stand-in's (in L2c; in an early version, the wheel
       slot WH_DEC). One listed exception to the length: an AD's body is the 0.2.6 compose, which stays in L1 (the
       chip composes in its mailbox interrupt, and the game writes the object's record right after the post:
       $1153C-$1154C) and is over the budget for big objects in play until stage 2's sprite engine (measured by an
       early census); its decode is checked like every other body's. Failures read 'FZ12 length' / 'FZ12 decode'
       (the planted bugs test_bug_l1len / test_bug_l1 each must fail with its own).
  FZ13 (B Jam's decision of 2026-10-15: the CPU MATE brain call never delays the game's own work) no job waits for a
       brain call: at every model checkpoint where the CPU is in the call's code (the brain, its cf.bin helpers, the
       wrapper) with interrupts open, the job queue is empty (the call is the thread's: a queued job would have raised
       MSI and been taken at this checkpoint, so one pending there is a mask or a lost raise; since 2026-10-15 the
       sprite decoder is RTL, no firmware level decodes). Reported, not failed: the brain calls, and the longest wait
       from a brain post to its call (the call takes the time that is left). The planted bug test_bug_l2c (the call runs
       with MSI masked: the jobs wait for it, as in earlier versions) must fail.
  FZ14 the SFX feeder (and the whole wheel) never waits for a brain call: at the same checkpoints the call runs
       with MTI open (mie.MTIE = 1). Reported: the feeder ticks checked at their entry (wh_feed), how many ran inside a
       call, and the ones that began late by more than one grid period. The planted bug test_bug_hold (the call masks
       MTI, as an earlier version held the feeder's slot) must fail.
  GO   every firmware GO lands while the post it serves (DB06, a DA07 job) is the 68000's latest B post and has been
       dispatched, and at most one per post: no GO after a later post's guard is set, no GO with no post behind it; the
       RTL decoder's GO (v1.2) serves the post whose $1FF2 = 0x8000 started its run (AF / B1 / F2 / DA06 / DA07), once.
  DEC  (MCU interface v1.2: the sprite decoder in RTL, the board model's timing; B Jam's decision of 2026-10-15:
       "sprites already done, never wait") every AF / B1 / F2 / DA06 / DA07 finishes in its own L1 (no deferred finish);
       no word of the decoder's output is read by the 68000 before its entry is complete (the board's LATE count, the
       decoder rule R-T1) and no run is aborted; no OVF / BADTYPE / D0 / PRE flag; every AF's window descriptors are
       served by a run of as many blocks. Reported: the runs, their decode time, the margin from the last block to the
       first DMA read (rule R-T2). The control: the clean image with
       a decoder 40 times slower must fail with DEC late (--negative).
  plus: no violation of the board model (rtlmodel.py), no fatal halt or exception in the replay, 0 SFX FIFO underruns or
  overflows (at the modelled rate), the 68000 released by the boot.
Exit 0 = PASS, 1 = FAIL (or, with --negative, a planted bug that passed), 2 = setup error."""
import argparse, json, mmap, os, random, re, struct, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import rtlmodel   # noqa: E402
from rtlmodel import Board, Stop, RAMDP   # noqa: E402
RC_MIE = __import__('unicorn').riscv_const.UC_RISCV_REG_MIE
RC_MSTATUS = __import__('unicorn').riscv_const.UC_RISCV_REG_MSTATUS

TIM7 = 5482275                          # board/clock.h CLK_TIM7 at the NTSC build clock (102,103.75 us)
FEED_CYCLES = 7168                      # board/clock.h CLK_FEED at the NTSC build clock (133.5 us, the feeder grid)
BUSY_TIMEOUT = 65534 * 410              # the game's 65,534-loop busy wait (~0.5 s, CART_FPGA_SPEC.md 7) in MCU cycles
WORD_CYCLES = 84                        # the 68000 reading one window word (estimated: ~12 cycles at 7.67 MHz)
WAIT_LIMIT = 100_000_000                # a bit-14 or finish wait longer than this (1.9 s): stuck (the longest measured
                                        # in the model: the C6 job, ~40 M cycles)
WAIT14 = (0xDA, 0xC6, 0xDF, 0xE0)       # the game spins on $1FE6 bit 14 after these (CART_FPGA_SPEC.md 8)
HW_CPI_RATIO = 1.2                      # NEORV32 cycles / model cycles for the same L1 body: measured 1.14-1.19 (an RTL
                                        # co-simulation of the RELEASE images vs this
                                        # model: 88 234.8 / 197 us, DB06 58.3 / 51.1,
                                        # DA02 53.8 / 44.6-50.5), rounded up
L1_BUDGET = int(0.32e-3 * rtlmodel.NTSC / HW_CPI_RATIO)   # 0.32 ms of hardware time, in model cycles (14,318)
L1_BUDGET_EXEMPT = (0xAD,)              # FZ12's listed exception (the 0.2.6 compose; its decode is still checked)
FZ12_FRAMES = 1200                      # the intro's sprite frames (the first AD with a load near frame 600)
FZ12_PLAY_FRAMES = 2000                 # into play (TEST's SAT snapshot works from about frame 1,750: sat_count >= 20)
def fw_streams(word):
    """does this post's service start a stream with a firmware GO? DB06 (L1) and a DA07 job (a 0x81 / 0x82 source; the
    GO in the job). Since MCU interface v1.2 the RTL decoder GOes AF / B1 / F2 / DA06 / DA07-0x80 itself.
    DA02 and DB03 stream nothing"""
    hb, lo = word >> 8, word & 0xFF
    return (hb == 0xDA and lo == 7) or (hb == 0xDB and lo == 6)


def window_dmas(b):
    """the VBlank DMA list the firmware left in cart RAM ($1400, 8 words each, count $1F16): the length in words of
    each descriptor whose source is the $C000 window, in list order (registers 0x93 / 0x94 length, 0x95-0x97 source)"""
    n = struct.unpack('<H', b.uc.mem_read(RAMDP + 0x1F16, 2))[0]
    out = []
    for i in range(min(n, 121)):
        w = struct.unpack('<8H', b.uc.mem_read(RAMDP + 0x1400 + 16 * i, 16))
        reg = {x >> 8: x & 0xFF for x in w[:6]}
        if not all(k in reg for k in (0x93, 0x94, 0x95, 0x96, 0x97)):
            continue
        src = ((reg[0x97] & 0x7F) << 17) | (reg[0x96] << 9) | (reg[0x95] << 1)
        if 0xC000 <= src < 0x10000:
            out.append((reg[0x94] << 8) | reg[0x93] or 0x10000)
    return out
VARIANT_BUGS = (('test', 'PASS'), ('test_bug_disp1', 'FZ2'), ('test_bug_disp2', 'FZ6'), ('test_bug_disp3', 'FZ4'),
                ('test_bug_sched1', 'FZ5'), ('test_bug_wdog', 'FZ10'), ('test_bug_go1', 'FZ3'), ('test_bug_go2', 'GO'),
                ('test_bug_l1', 'FZ12 decode'), ('test_bug_l1len', 'FZ12 length'), ('test_bug_l2c', 'FZ13'),
                ('test_bug_hold', 'FZ14'), ('test@slowdec', 'DEC'))
SLOW_DEC_NS = rtlmodel.DEC_NS * 40      # the DEC control: a decoder 40 x slower (a block ~2.9 ms) must read late
US = rtlmodel.NTSC / 1e6                # model cycles per microsecond
DMA_FIRST = int(106 * US)               # AF / B1 reply -> the first VBlank flush DMA, at least (decoder spec. 4.2,
                                        # estimated: GPGX's measured 110.7 us from VBlank start, fx68k up to 4 % faster)
DMA_STEP = int(175 * US)                # one 256-word block DMA and the descriptor loop, at least (decoder spec. 4.2)
F2_DMA_MIN = int(1000 * US)             # F2 -> its own DMA, at least (the game waits for the next VBlank: about a frame;
                                        # 1 ms is far below it, so the check is conservative)
VARIANT_FRAMES = {'test_bug_l1': FZ12_FRAMES,           # at least this many frames (the others: --frames)
                  'test_bug_l1len': FZ12_PLAY_FRAMES,
                  'test_bug_l2c': FZ12_PLAY_FRAMES,     # SENDs while the decoder has a queue: the intro's and play's frames
                  'test_bug_hold': FZ12_PLAY_FRAMES,    # SENDs while SFX play: the intro's and play's frames
                  'test@slowdec': FZ12_FRAMES}          # the intro's first AF load lists (near frame 600)
BRAIN_CODE = ((0x5360, 0xD2EC), (0x80002C00, 0x80004648))   # the brain's IROM bytes, cf.bin + rodata (fixed places)


def cut(recs, frames):
    """the records up to (and with) the frame record of `frames`"""
    for k, r in enumerate(recs):
        if r[0] == 'F' and r[1] > frames:
            return recs[:k]
    return recs


def load_capture(path, to_frame):
    """the records up to to_frame: ('F', f) | ('W', off, bytes) | ('A', word) | ('B', word, args)"""
    out = []
    with open(path, 'rb') as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as d:
        o = 0
        while o + 20 <= len(d):
            t, ln, f = struct.unpack_from('<HHI', d, o)
            po = o + 20
            o = po + ln
            if f > to_frame:
                break
            if t == 1:
                out.append(('F', f))
            elif t == 3:
                ad, wd, v = struct.unpack_from('<HHH', d, po)
                if ad >= 0x2000:
                    continue
                if ad >= 0x1FE0:
                    if (ad & ~1) == 0x1FEC and wd == 2:
                        out.append(('A', v & 0xFFFF))
                    continue                    # the rest of the page: the register file (a 68000 write has no effect)
                if wd == 2:
                    out.append(('W', ad & ~1, struct.pack('<H', v & 0xFFFF)))
                else:
                    out.append(('W', ad ^ 1, bytes([v & 0xFF])))
            elif t == 2:
                wv = struct.unpack_from('<18H', d, po)
                out.append(('B', wv[0], struct.pack('<16H', *wv[2:18])))
    return out


class Fuzz:
    def __init__(self, build, rom, recs, seed, save=None, quiet=True, sfx_strict=False, dec_ns=rtlmodel.DEC_NS):
        self.rnd = random.Random(seed)
        self.sfx_strict = sfx_strict
        self.seed = seed
        self.b = Board(build, rom, opt=0, seed=seed, save=save, listener=self.on_ev, dec_ns=dec_ns)
        self.sym = self.b.sym
        self.recs = recs
        self.i = 0
        self.bad = []
        self.notes = {}
        self.cur_b = None                   # the 68000's latest B post
        self.cur_a = None
        self.posts_b = self.posts_a = 0
        self.fin_b = self.fin_a = 0
        self.state = 'idle'
        self.wait_t0 = 0
        self.gap_until = 0
        self.menu_until = 0
        self.af_pending = False
        self.sends, self.brain_starts = [], []
        self.f2_pending = None              # an F2 post whose 512-word DMA comes at the next frame record
        self.dma_q = []                     # the VBlank DMA's window reads due: [model time, words]
        self.dec = dict(runs=0, entries=0, af_runs=0, dma_blocks=0, dma_words=0, late=0, aborts=0, flags=0,
                        list_short=0, t_max=0, margin_min=None, deferred=0)   # list_short: the cart-RAM window
                                                                               # descriptors != the run's entries
                                                                               # (counted, not failed)
        self.sub_released = False
        self.jobs_once = False
        self.job_go_pending = None          # a DA07 job post whose GO has not landed
        self.fz7_checks = self.fz4_checks = 0
        self.stale = self.timeouts = 0
        self.extra_a = 0
        self.menus = 0
        self.gos = 0
        self.t9494 = None
        self.inject = []                    # synthetic posts to make before the next capture record
        self.da02 = None
        self.synth = 0
        self.released_t = None
        self.dg = self.sym['disp_g'][0]
        self.sh = (self.sym['sh_fe4'][0], self.sym['sh_fe6'][0]) if 'sh_fe4' in self.sym and 'sh_fe6' in self.sym else None
        self.stopped = False
        self.fatal_t = None
        from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
        a = self.sym['buddy_call_brain'][0]
        self.b.uc.hook_add(UC_HOOK_CODE, self.brain_hook, begin=a, end=a)
        a = self.sym['fatal_halt'][0]
        self.b.uc.hook_add(UC_HOOK_CODE, self.fatal_hook, begin=a, end=a)
        # FZ12: a post's L1 body = disp_post's entry to the return into l1_mei (l1_post tail-calls disp_post; stage 5's
        # l1_serve_a / l1_serve_b, when not inlined, tail-call disp_post_s5: their return point counts too)
        self.l1p = None
        self.l1_max = {}                    # high byte -> (model cycles, word), the longest body seen
        self.l1_bodies = self.l1_over = self.l1_exempt_over = 0
        a = self.sym['disp_post'][0]
        self.b.uc.hook_add(UC_HOOK_CODE, self.l1_in, begin=a, end=a)
        n = 0
        for ln in open(os.path.join(build, 'main.dis')):
            m = re.match(r'^\s*([0-9a-f]+):\t[0-9a-f]+\s*\tjal\t[0-9a-f]+ <(l1_post|l1_post_s5|disp_post_s5|l1_serve_a|l1_serve_b)>\s*$', ln)
            if m:
                a = int(m.group(1), 16) + 4
                self.b.uc.hook_add(UC_HOOK_CODE, self.l1_out, begin=a, end=a)
                n += 1
        if not n:
            raise ValueError('FZ12: no call of l1_post in main.dis')
        # the block decoders the image links (since stage 3 the stage-5
        # images' jobs and C6 decode with ours, which work as the chip's)
        self.l1_dec_names = [k for k in ('ppm_unpack_scal', 'song_unpack80', 'song_unpack81') if k in self.sym]
        if not self.l1_dec_names:
            raise ValueError('FZ12: no block decoder in main.nm')
        for k in self.l1_dec_names:
            a = self.sym[k][0]
            self.b.uc.hook_add(UC_HOOK_CODE, self.l1_dec, begin=a, end=a, user_data=k)
        # FZ13 / FZ14: at the checkpoints inside the call's code, no game work pending and MTI open; per call, the wait
        # from the brain post (the store of brain_pending = 1: sched_brain_post is inlined into l1_mei, so a code hook
        # would see only the thread's posts) to the call's entry (reported)
        self.fz13 = None
        self.fz13_calls = self.fz13_dec_max = self.fz13_wait_max = self.fz13_checks = 0
        self.fz13_pend = self.sym['brain_pending'][0]
        self.fz13_ranges = list(BRAIN_CODE)
        if 'buddy_call_brain' in self.sym and 'buddy_abort_land' in self.sym:
            self.fz13_ranges.append((self.sym['buddy_call_brain'][0], self.sym['buddy_abort_land'][0]))
        self.b.uc.hook_add(UC_HOOK_MEM_WRITE, self.fz13_post, begin=self.fz13_pend, end=self.fz13_pend + 3)
        self.fz14_checks = self.fz14_late = self.fz14_inside = self.fz14_mti = 0
        self.fz14_active = self.sym['brain_active'][0]
        a = self.sym['wh_feed'][0]
        self.b.uc.hook_add(UC_HOOK_CODE, self.fz14_feed, begin=a, end=a)

    # ------------------------------------------------------------------------------------------- checks at events
    def fail(self, what):
        if len(self.bad) < 30:
            self.bad.append('t=%d %s' % (self.b.time, what))

    def q_idx(self):
        m = self.b.uc.mem_read(self.dg + 5, 2)
        return m[0], m[1]

    def brain_hook(self, uc, addr, size, ud):
        self.brain_starts.append(self.b.time)
        w, self.fz13 = self.fz13, None
        if w is not None:
            self.fz13_calls += 1
            self.fz13_dec_max = max(self.fz13_dec_max, w[1])
            self.fz13_wait_max = max(self.fz13_wait_max, self.b.time - w[0])

    def fz13_post(self, uc, access, addr, size, value, ud):
        if value:
            self.fz13 = [self.b.time, 0]            # a call follows the latest post (the glue may post a deferred send again)

    def fz13_check(self, pc=None):
        """FZ13 / FZ14 at a checkpoint (after the model took what was pending): inside the call's code with interrupts
        open, no decoder request, job or board work is pending (FZ13) and MTI is open (FZ14)"""
        b = self.b
        pc = b.pc() if pc is None else pc
        for lo, hi in self.fz13_ranges:
            if lo <= pc < hi:
                if not (b.uc.reg_read(RC_MSTATUS) & 8):
                    return                              # a section (the wrapper's abort landing): not the call's body
                self.fz13_checks += 1
                mie = b.uc.reg_read(RC_MIE)
                qw, qr = self.q_idx()
                if (qw ^ qr) & 0xF:
                    self.fail('FZ13: game work pending while the brain call runs at %#x (jobs %d; mie %#x): the work waits '
                              'for the call' % (pc, (qw - qr) & 0xF, mie))
                if not (mie & 0x80):
                    self.fz14_mti += 1
                    self.fail('FZ14: the brain call runs at %#x with MTI masked (mie %#x): the SFX feeder and the rest of the '
                              'wheel wait for the call' % (pc, mie))
                return

    def fz14_feed(self, uc, addr, size, ud):
        """at each wh_feed entry (reported): inside a brain call or not; a0 = the tick's due time (late by > one grid
        period: a catch-up)"""
        from unicorn import riscv_const as RC
        self.fz14_checks += 1
        if struct.unpack('<I', uc.mem_read(self.fz14_active, 4))[0]:
            self.fz14_inside += 1
        late = (self.b.timer() - uc.reg_read(RC.UC_RISCV_REG_A0)) & 0xFFFFFFFF
        if FEED_CYCLES < late < 0x80000000:
            self.fz14_late += 1

    def fatal_hook(self, uc, addr, size, ud):
        if self.fatal_t is None:
            self.fatal_t = self.b.time

    def l1_in(self, uc, addr, size, ud):
        from unicorn import riscv_const as RC
        self.l1p = dict(word=uc.reg_read(RC.UC_RISCV_REG_A1) & 0xFFFF, mbx=uc.reg_read(RC.UC_RISCV_REG_A0), t0=self.b.time)

    def l1_out(self, uc, addr, size, ud):
        p, self.l1p = self.l1p, None
        if p is None:
            return                          # a held post (stage 5): l1_post returned without a body
        dt = self.b.time - p['t0']          # step-start times: within one step (<= 48 instructions here) of the truth
        hb = p['word'] >> 8
        self.l1_bodies += 1
        if dt > self.l1_max.get(hb, (0, 0))[0]:
            self.l1_max[hb] = (dt, p['word'])
        if dt > L1_BUDGET:
            if hb in L1_BUDGET_EXEMPT and p['mbx'] == 0:
                self.l1_exempt_over += 1
            else:
                self.l1_over += 1
                self.fail('FZ12 length: the L1 body of post %04X took %d model cycles (%.0f us at the hardware CPI), over the '
                          '%d-cycle budget' % (p['word'], dt, dt * HW_CPI_RATIO / rtlmodel.NTSC * 1e6, L1_BUDGET))

    def l1_dec(self, uc, addr, size, ud):
        if self.l1p is not None:
            self.fail('FZ12 decode: a block decode (%s) inside the L1 body of post %04X' % (ud, self.l1p['word']))
            self.l1p['dec'] = True

    def on_ev(self, kind, kw):
        b = self.b
        if kind == 'mbx_read':
            if kw['off'] == 0x0C and kw['v'] == 0x9494:
                self.t9494 = b.time                 # the watchdog is fed in this post's L1 (FZ10)
            p = self.cur_b if kw['off'] == 0x0A else self.cur_a
            if p is not None and p.get('fin') is None and kw['v'] == p['word'] and not p.get('disp'):
                p['disp'] = b.time
                p['qw'] = self.q_idx()[0]
        elif kind == 'freg_w':
            off, v = kw['off'], kw['v']
            if off == 0x0A and v == 0 and self.released_t is not None:
                p = self.cur_b
                if p is None or p.get('fin') is not None:
                    self.fail('FZ1: $1FEA := 0 with no B post outstanding')
                    return
                p['fin'] = b.time
                self.fin_b += 1
                if (p['word'] >> 8) in (0xAF, 0xB1, 0xF2, 0xDA) and self.l1p is None:
                    self.dec['deferred'] += 1
                    self.fail('DEC: post %04X finished outside its L1 (a deferred finish)' % p['word'])
                if (p['word'] >> 8) in (0xAF, 0xB1):
                    p['win_desc'] = sum(1 for n in window_dmas(b) if n == 0x100)
                if (b.freg[0x06] & 0x200) and p.get('gos'):
                    self.fail('GO: refused post %04X started a stream' % p['word'])
                if not p.get('disp'):
                    self.fail('FZ5: B post %04X finished but never read' % p['word'])
                if p.get('qw') is not None and self.q_idx()[0] != p['qw']:
                    p['job'] = True
                    self.jobs_once = True
                    if not (b.freg[0x06] & 0x4000):
                        self.fail('FZ2: post %04X queued a job but $1FE6 bit 14 is clear at its finish' % p['word'])
                    if (p['word'] >> 8) == 0xDA and (p['word'] & 0xFF) == 7:
                        self.job_go_pending = p
            elif off == 0x0C and v == 0 and self.released_t is not None:
                p = self.cur_a
                if p is None or p.get('fin') is not None:
                    self.fail('FZ6: $1FEC := 0 with no A post outstanding')
                    return
                p['fin'] = b.time
                self.fin_a += 1
            elif off == 0x06 and (kw['old6'] & 0x4000) and not (v & 0x4000) and self.job_go_pending is not None:
                self.fail('FZ3: $1FE6 bit 14 cleared before the GO of the DA07 job of post %04X' % self.job_go_pending['word'])
                self.job_go_pending = None
        elif kind == 'dec_start':
            p = self.cur_b                          # the START is written in the L1 of the post being served
            kw['run']['post'] = p
            self.dec['runs'] += 1
            self.dec['entries'] += len(kw['run']['ents'])
        elif kind == 'dec_abort':
            self.dec['aborts'] += 1
            p = kw['run'].get('post')
            self.fail('DEC abort: a decoder run (post %s, %d entries) cut before its end' % (
                '%04X' % p['word'] if p else '-', len(kw['run']['ents'])))
        elif kind == 'dec_late':
            self.dec['late'] += 1
            if self.dec['late'] <= 3:
                p = kw['run'].get('post')
                self.fail('DEC late: the window read output byte %d of a run (post %s) before its entry was decoded' % (
                    kw['o'], '%04X' % p['word'] if p else '-'))
        elif kind == 'go' and kw.get('rtl') and self.released_t is not None:
            self.gos += 1
            r = kw['run']
            p = r.get('post')
            self.dec['t_max'] = max(self.dec['t_max'], r['go_t'] - r['S'])
            if p is None:
                self.fail('GO: the decoder GOed a run no post started')
                return
            p['gos'] = p.get('gos', 0) + 1
            if p['gos'] > 1:
                self.fail('GO: a second GO for post %04X (the RTL decoder\'s)' % p['word'])
        elif kind == 'go' and self.released_t is not None:
            self.gos += 1
            p = self.cur_b
            if self.job_go_pending is not None:
                self.job_go_pending['gos'] = self.job_go_pending.get('gos', 0) + 1
                if self.job_go_pending is not p:
                    self.fail('GO: the DA07 job GO of post %04X landed after the later post %s' % (
                        self.job_go_pending['word'], '%04X' % p['word'] if p else '-'))
                self.job_go_pending = None
                return
            if p is None or not fw_streams(p['word']):
                self.fail('GO: a GO (%d words) with no stream post behind it (the latest B post: %s)' % (
                    kw['n'], '%04X' % p['word'] if p else 'none'))
                return
            if not p.get('disp'):
                self.fail('GO: a GO landed after post %04X was written (its guard set) and before its dispatch' % p['word'])
                return
            p['gos'] = p.get('gos', 0) + 1
            if p['gos'] > 1:
                self.fail('GO: a second GO for post %04X' % p['word'])

    def checkpoint_checks(self):
        b = self.b
        if not b.mie_open():
            return
        if self.sh is not None:
            s4 = struct.unpack('<H', b.uc.mem_read(self.sh[0], 2))[0]
            s6 = struct.unpack('<H', b.uc.mem_read(self.sh[1], 2))[0]
            self.fz7_checks += 1
            if b.freg[0x06] != s6 or b.freg[0x04] != s4:
                self.fail('FZ7: $1FE6 %#06x / $1FE4 %#06x, shadows %#06x / %#06x' % (b.freg[0x06], b.freg[0x04], s6, s4))
        if self.jobs_once:
            w, r = self.q_idx()
            self.fz4_checks += 1
            if bool(b.freg[0x06] & 0x4000) != (((w ^ r) & 0xF) != 0):
                self.fail('FZ4: $1FE6 bit 14 = %d with the queue at wr %d rd %d' % ((b.freg[0x06] >> 14) & 1, w, r))

    # ------------------------------------------------------------------------------------------- the 68000
    def post_b(self, word, args, synth=False):
        b = self.b
        b.w68_ram(0x1E10, args)
        self.cur_b = dict(word=word, t=b.time, seq=self.posts_b, synth=synth)
        if (word >> 8) == 0xF2:
            self.f2_pending = self.cur_b
        if word == 0xDA02:
            self.da02 = args
        self.posts_b += 1
        b.w68_post_b(word)
        self.state = 'wait_fin'
        self.wait_t0 = b.time

    def post_a(self, word, extra=False):
        self.cur_a = dict(word=word, t=self.b.time, extra=extra)
        self.posts_a += 1
        self.b.w68_post_a(word)

    def side_68000(self):
        b, r = self.b, self.rnd
        t = b.time
        if self.menu_until:
            if t < self.menu_until:
                return False
            b.opt &= ~(1 << 24)
            self.menu_until = 0
        # random extras (between any two 68000 steps)
        if self.sub_released and not (b.ls & rtlmodel.LS_BUSY) and r.random() < 0.002:
            b.send()                                # the sub CPU posts again once its last answer is published
            self.sends.append(t)
        if (self.cur_a is None or self.cur_a.get('fin') is not None) and r.random() < 0.002:
            self.post_a(0x9400, extra=True)
            self.extra_a += 1
        if self.state == 'idle' and r.random() < 0.00005:
            b.opt |= 1 << 24
            self.menu_until = t + r.randint(100_000, 2_000_000)
            self.menus += 1
            return False
        if not self.sub_released and t > self.released_t + 3_000_000:
            b.sub_release()
            self.sub_released = True
        if t < self.gap_until:
            return False
        p = self.cur_b
        if self.state == 'wait_fin':
            if b.r68(0x0A) == 0:
                fe6 = b.r68(0x06)
                hb, lo = p['word'] >> 8, p['word'] & 0xFF
                refused = bool(fe6 & 0x200)
                if not refused and hb in WAIT14:
                    self.state = 'wait14'
                elif not refused and ((hb == 0xDB and lo == 6) or (hb == 0xDA and lo == 7)):
                    self.state, self.wait_t0 = 'wait_busy', t
                else:
                    self.state = 'idle'
                self.wait_t0 = t if self.state != 'idle' else self.wait_t0
            elif t - self.wait_t0 > WAIT_LIMIT:
                self.fail('FZ1: post %04X not finished in %d cycles' % (p['word'], WAIT_LIMIT))
                raise Stop()
            return True
        if self.state == 'wait14':
            if not (b.r68(0x06) & 0x4000):
                hb, lo = p['word'] >> 8, p['word'] & 0xFF
                self.state = 'wait_busy' if (hb == 0xDA and lo == 7) else 'idle'
                self.wait_t0 = t
                if p['word'] == 0xDA02 and not p['synth'] and self.da02 is not None and (not self.synth or r.random() < 0.5):
                    # the same decode again as a DA07 (same source, same destination: the workspace ends as it was),
                    # so a 0x81 source exercises the DA07 job's GO and a 0x80 one the board work's (the solo route
                    # has DA07 only with 0x80 sources, and the first at frame 441)
                    self.inject.append(('B', 0xDA07, self.da02))
            elif t - self.wait_t0 > WAIT_LIMIT:
                self.fail('FZ4: $1FE6 bit 14 stuck after post %04X (%d cycles)' % (p['word'], WAIT_LIMIT))
                raise Stop()
            return True
        if self.state == 'wait_busy':
            if not b.busy():
                if not p.get('gos'):
                    self.fail('FZ3: stale ready: busy clear after post %04X before its GO' % p['word'])
                    self.stale += 1
                self.state, self.wait_t0 = 'read', t
            elif t - self.wait_t0 > BUSY_TIMEOUT:
                self.fail('FZ3: busy timeout after post %04X (the game reads the window anyway)' % p['word'])
                self.timeouts += 1
                self.state = 'idle'
            return True
        if self.state == 'read':
            n = max(1, (t - self.wait_t0) // WORD_CYCLES)
            self.wait_t0 = t
            if not b.consume(n):
                self.state = 'idle'
            return True
        if self.state == 'dma':                     # the VBlank DMA list: each window block at its time
            while self.dma_q and self.dma_q[0][0] <= t:
                due, n = self.dma_q.pop(0)
                b.consume(n, t=t, dma=True)
                self.dec['dma_words'] += n
            if self.dma_q:
                self.gap_until = self.dma_q[0][0]
                return True
            self.state = 'idle'
            return True                             # (the timed rig plays the next record at its own time)
        # idle: a synthetic post first, then the next record
        if self.inject:
            rec = self.inject.pop(0)
            self.post_b(rec[1], rec[2], synth=True)
            self.synth += 1
            return True
        while self.i < len(self.recs):
            rec = self.recs[self.i]
            k = rec[0]
            if k == 'W':
                b.w68_ram(rec[1], rec[2])
                self.i += 1
                continue
            if k == 'F':
                self.i += 1
                if self.vblank_dma(t):              # the VBlank DMA reads the AF / B1 / F2 streams
                    return True
                self.gap_until = t + r.choice((0, 0, 200, 2000, 20000))
                return True
            if k == 'A':
                if self.cur_a is not None and self.cur_a.get('fin') is None:
                    if t - self.cur_a['t'] > WAIT_LIMIT:
                        self.fail('FZ6: A post %04X not finished in %d cycles' % (self.cur_a['word'], WAIT_LIMIT))
                        raise Stop()
                    return True
                self.post_a(rec[1])
                self.i += 1
                return True
            if k == 'B':
                self.post_b(rec[1], rec[2])
                if (rec[1] >> 8) in (0xAF, 0xB1):
                    self.af_pending = True
                self.i += 1
                self.gap_until = t + r.choice((0, 0, 0, 100, 1000))
                return True
        return False

    def vblank_dma(self, t, r0=None):
        """the frame's VBlank DMA list (at a frame record, or at the capture's flush with r0 = its first DMA): the AF /
        B1 post's window blocks from max(t, r0, its finish + DMA_FIRST), DMA_STEP apart; F2's 512 words from its finish +
        F2_DMA_MIN. Returns True when reads were queued (the 68000 is in its DMA list until the last)"""
        b = self.b
        q = []
        p = self.cur_b
        if self.af_pending and p is not None and p.get('fin') is not None:
            self.af_pending = False
            runs = [x for x in b.dec_log[-4:] if x.get('post') is p]
            if runs:                                # one 256-word DMA per entry (the
                                                    # chip's descriptor: decoder spec. 2)
                run = runs[-1]
                t0 = max(t, r0 or 0, p['fin'] + DMA_FIRST)
                q += [[t0 + k * DMA_STEP, 0x100] for k in range(len(run['ents']))]
                self.dec['af_runs'] += 1
                self.dec['dma_blocks'] += len(run['ents'])
                if p.get('win_desc') is not None and p['win_desc'] != len(run['ents']):
                    self.dec['list_short'] += 1     # (the capture's own $1400 / $1F16 writes can clobber ours: counted)
                m = t0 - run['go_t']
                self.dec['margin_min'] = m if self.dec['margin_min'] is None else min(self.dec['margin_min'], m)
        f2 = self.f2_pending
        if f2 is not None and f2.get('fin') is not None:
            self.f2_pending = None
            q.append([max(t, f2['fin'] + F2_DMA_MIN), 0x200])
        if not q:
            return False
        self.dma_q = sorted(self.dma_q + q)
        self.state = 'dma'
        self.gap_until = self.dma_q[0][0]
        return True

    # ------------------------------------------------------------------------------------------- run
    def boot(self):
        b = self.b
        if not b.run_to('brd_boot', 200_000):
            self.fail('the boot did not reach brd_boot (crt0 stopped: boot record %s)' % [b.rd32('s1_boot_rec', k) for k in range(4)])
            raise Stop()
        n = 0
        while b.ctrl & 1:                       # until the release (HOLD cleared), interrupts as they come
            b.take()
            b.step(400)
            n += 1
            if n > 300000:
                self.fail('the 68000 was never released (boot record %s)' % [b.rd32('s1_boot_rec', k) for k in range(4)])
                raise Stop()
        self.released_t = b.time

    def run(self, wdog=False):
        b, r = self.b, self.rnd
        try:
            self.boot()
            while True:
                active = self.side_68000()
                b.take()
                self.checkpoint_checks()
                self.fz13_check()
                long_wait = self.state == 'wait14' or (self.state == 'idle' and self.i >= len(self.recs)) or                     (self.state == 'wait_fin' and b.time - self.wait_t0 > 2_000_000) or                     (self.cur_a is not None and self.cur_a.get('fin') is None and b.time - self.cur_a['t'] > 2_000_000)
                b.step(r.randint(1, 400) if long_wait and r.random() < 0.7 else r.randint(1, 48))
                if (b.time & 0x3FFF) < 300:
                    b.sfx_check()
                if self.i >= len(self.recs) and not self.inject and self.state == 'idle' and                         (self.cur_a is None or self.cur_a.get('fin') is not None):
                    break
            self.drain()
            if wdog:
                self.watchdog()
        except Stop:
            self.stopped = True
        return self.verdict(wdog)

    def drain(self):
        """the 68000 done: run until the queue is empty and nothing is outstanding, the sub's last post answered
        included (bounded)"""
        b = self.b
        end = b.time + 60_000_000
        while b.time < end:
            w, rr = self.q_idx()
            if ((w ^ rr) & 0xF) == 0 and not (b.cause & 0xF) and not b.msip and                     not (self.sends and self.brain_starts and self.sends[-1] > self.brain_starts[-1]):
                break
            b.take()
            self.checkpoint_checks()
            self.fz13_check()
            b.step(self.rnd.randint(1, 400))
        else:
            self.fail('FZ4: the job queue did not drain after the replay')

    def watchdog(self):
        """FZ10: the menu open for 45 TIM7 periods, no 9494: no trip; closed, no 9494: a trip after 39-41 periods"""
        b = self.b
        self.wd = {}
        b.opt |= 1 << 24
        t0 = b.time
        while b.time - t0 < 45 * TIM7:
            b.take()
            b.step(self.rnd.randint(500, 4000))
            if self.fatal_t is not None:
                self.fail('FZ10: the watchdog tripped with the Pocket menu open (%.2f TIM7 periods after it opened)' % (
                    (self.fatal_t - t0) / TIM7))
                return
        b.opt &= ~(1 << 24)
        t1 = b.time
        while b.time - t1 < 46 * TIM7 and self.fatal_t is None:
            b.take()
            b.step(self.rnd.randint(500, 4000))
        # the counting time: from the last 9494 (its L1 feeds the watchdog) to the trip, less the menu-open stretch
        dt = (self.fatal_t - self.t9494 - (t1 - t0)) / TIM7 if self.fatal_t is not None and self.t9494 is not None else None
        self.wd = dict(menu_open_periods=45, counted_periods_to_trip=round(dt, 2) if dt is not None else None,
                       fatal_code='%#x' % self.fatal_code() if self.fatal_code() else None)
        if dt is None:
            self.fail('FZ10: no watchdog trip 46 TIM7 periods after the menu closed with no 9494')
        elif dt <= 38.0 or dt > 39.2:
            self.fail('FZ10: the watchdog tripped after %.2f counted TIM7 periods with no 9494 (the 39th tick: 38-39)' % dt)

    def fatal_code(self):
        return self.b.rd32('fatal_rec') if 'fatal_rec' in self.sym and not self.release() else 0

    def release(self):
        return 'stats_enter' not in self.sym           # RELEASE images build no TEST counters

    def verdict(self, wdog):
        b = self.b
        bad = list(b.violations) + list(self.bad)
        ended = not b.violations and not self.stopped
        if self.released_t is None:
            bad.append('the 68000 was never released')
        if ended and (self.fin_b != self.posts_b):
            bad.append('FZ1: %d B posts, %d finishes' % (self.posts_b, self.fin_b))
        if ended and (self.fin_a != self.posts_a):
            bad.append('FZ6: %d A posts, %d finishes' % (self.posts_a, self.fin_a))
        if self.brain_starts and ended:
            first = self.brain_starts[0]
            for ts in self.sends:
                if ts > first and not any(x >= ts for x in self.brain_starts):
                    bad.append('FZ5: the SEND at t=%d has no brain call after it' % ts)
                    break
        if not self.release() and 'sched_stats' in self.sym:
            held, urgent = b.rd32('sched_stats', 8), b.rd32('sched_stats', 12)
            if held or urgent:
                bad.append('FZ8/FZ9: held %d, urgent %d on a stage-1 image (no song tick)' % (held, urgent))
            if b.rd32('sched_stats', 16):
                bad.append('exception: %d (first cause %#x at %#x)' % (b.rd32('sched_stats', 16), b.rd32('sched_stats', 17),
                                                                       b.rd32('sched_stats', 18)))
        if self.fatal_t is not None and not wdog:
            bad.append('fatal halt in the replay (code %#x)' % self.fatal_code())
        depth, floor_hit = b.stack_depth() if not self.release() else (0, False)
        sb = json.load(open(os.path.join(b.build, 'stack.json')))
        static = max(s['worst']['bytes'] for s in sb['schemes'] if s['gate'])
        if floor_hit:
            bad.append('FZ11: the stack floor word was overwritten')
        if depth > static:
            bad.append('FZ11: MEASURED stack depth %d B > the static bound %d B' % (depth, static))
        if (sum(b.underruns) and self.sfx_strict) or sum(b.overflow):
            bad.append('SFX FIFO: underruns %s, overflows %s' % (b.underruns, b.overflow))
        if b.dflags & (rtlmodel.DEC_FLAG_OVF | rtlmodel.DEC_FLAG_BADTYPE | rtlmodel.DEC_FLAG_D0 | rtlmodel.DEC_FLAG_PRE):
            bad.append('DEC flags %#x (OVF / BADTYPE / D0 / PRE)' % b.dflags)
        if b.dlate and not any(x.startswith('DEC late') for x in self.bad):
            bad.append('DEC late: %d window words read before their entry was decoded' % b.dlate)
        worst = max(self.l1_max.items(), key=lambda kv: kv[1][0]) if self.l1_max else (0, (0, 0))
        worst_x = max(((k, v) for k, v in self.l1_max.items() if k not in L1_BUDGET_EXEMPT), key=lambda kv: kv[1][0],
                      default=(0, (0, 0)))
        return dict(seed=self.seed, time=b.time, posts_b=self.posts_b, posts_a=self.posts_a, extra_a=self.extra_a,
                    menus=self.menus, sends=len(self.sends), brain_calls=len(self.brain_starts), gos=self.gos, synth=self.synth,
                    taken={'MEI': b.taken[11], 'MTI': b.taken[7], 'MSI': b.taken[3]}, fz4_checks=self.fz4_checks,
                    fz7_checks=self.fz7_checks, stack_depth=depth, stack_bound=static, sfx_pushes=sum(b.pushes),
                    records=self.i, wd=getattr(self, 'wd', None), underruns=sum(b.underruns), under_log=b.under_log[:4],
                    l1_bodies=self.l1_bodies, l1_max=worst[1][0], l1_max_word=worst[1][1], l1_max_x=worst_x[1][0],
                    l1_max_x_word=worst_x[1][1], l1_exempt_over=self.l1_exempt_over, fz13_calls=self.fz13_calls,
                    fz13_dec_max=self.fz13_dec_max, fz13_wait_max=self.fz13_wait_max, fz13_checks=self.fz13_checks,
                    fz14_checks=self.fz14_checks, fz14_late=self.fz14_late, fz14_inside=self.fz14_inside,
                    dec=dict(self.dec, late_words=b.dlate, flags=b.dflags), bad=bad)


def inputs():
    lp = os.path.join(ROOT, 'paths.local.json')
    cfg = (json.load(open(lp)) if os.path.exists(lp) else {}).get('equiv') or {}
    cap, rom = cfg.get('capture_solo'), cfg.get('rom')
    if not cap or not rom or not os.path.isfile(cap) or not os.path.isfile(rom):
        print('SETUP ERROR: paths.local.json "equiv" needs capture_solo and rom')
        sys.exit(2)
    return cap, open(rom, 'rb').read()


def run_seeds(build, rom, recs, seeds, first, wdog_seed=None, quiet=False, sfx_strict=False, stop_at_fail=False,
              dec_ns=rtlmodel.DEC_NS):
    agg = dict(seeds=0, posts_b=0, posts_a=0, extra_a=0, menus=0, sends=0, brain_calls=0, gos=0, fz4_checks=0, fz7_checks=0,
               sfx_pushes=0, underruns=0, stack_depth=0, taken={'MEI': 0, 'MTI': 0, 'MSI': 0}, l1_bodies=0, l1_max=0,
               l1_max_word=0, l1_max_x=0, l1_max_x_word=0, l1_exempt_over=0, fz13_calls=0, fz13_dec_max=0, fz13_wait_max=0,
               fz13_checks=0, fz14_checks=0, fz14_late=0, fz14_inside=0,
               dec=dict(runs=0, entries=0, af_runs=0, dma_blocks=0, dma_words=0, late_words=0, aborts=0, t_max=0,
                        margin_min=None))
    fails = []
    wd = None
    for sd in range(first, first + seeds):
        t0 = time.time()
        o = Fuzz(build, rom, recs, sd, sfx_strict=sfx_strict, dec_ns=dec_ns).run(wdog=(sd == wdog_seed))
        agg['seeds'] += 1
        for k in ('runs', 'entries', 'af_runs', 'dma_blocks', 'dma_words', 'late_words', 'aborts'):
            agg['dec'][k] += o['dec'][k]
        agg['dec']['t_max'] = max(agg['dec']['t_max'], o['dec']['t_max'])
        if o['dec']['margin_min'] is not None:
            m = agg['dec']['margin_min']
            agg['dec']['margin_min'] = o['dec']['margin_min'] if m is None else min(m, o['dec']['margin_min'])
        for k in ('posts_b', 'posts_a', 'extra_a', 'menus', 'sends', 'brain_calls', 'gos', 'fz4_checks', 'fz7_checks', 'sfx_pushes',
                  'underruns', 'l1_bodies', 'l1_exempt_over', 'fz13_calls', 'fz13_checks', 'fz14_checks', 'fz14_late',
                  'fz14_inside'):
            agg[k] += o[k]
        for k in ('fz13_dec_max', 'fz13_wait_max'):
            agg[k] = max(agg[k], o[k])
        for k in ('l1_max', 'l1_max_x'):
            if o[k] > agg[k]:
                agg[k], agg[k + '_word'] = o[k], o[k + '_word']
        agg['stack_depth'] = max(agg['stack_depth'], o['stack_depth'])
        agg['stack_bound'] = o['stack_bound']
        for k in agg['taken']:
            agg['taken'][k] += o['taken'][k]
        if o.get('wd'):
            wd = o['wd']
        if not quiet:
            print('  seed %d: %d B / %d A posts, %d GOs, %d SENDs, %d brain calls, %.1f s%s' % (
                sd, o['posts_b'], o['posts_a'], o['gos'], o['sends'], o['brain_calls'], time.time() - t0,
                '' if not o['bad'] else ' FAIL: ' + '; '.join(o['bad'][:3])), flush=True)
        if o['bad']:
            fails.append((sd, o['bad']))
            if stop_at_fail:
                break
    agg['wd'] = wd
    return agg, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default=os.path.join(ROOT, 'build', 's1', 'pocket72k', 'test'))
    ap.add_argument('--seeds', type=int, default=4)
    ap.add_argument('--first', type=int, default=1)
    ap.add_argument('--frames', type=int, default=500, help='replay the capture up to this frame (fast mode)')
    ap.add_argument('--only', action='append', help='--negative: run only these variants')
    ap.add_argument('--wdog', action='store_true', help='FZ10: the watchdog scenario after the first seed')
    ap.add_argument('--negative', action='store_true')
    ap.add_argument('--q1', action='store_true')
    ap.add_argument('--sfx-strict', action='store_true', help='fail on an SFX FIFO underrun (default: counted and printed)')
    ap.add_argument('--json')
    a = ap.parse_args()
    cap, rom = inputs()
    recs = load_capture(cap, max([a.frames] + (list(VARIANT_FRAMES.values()) if a.negative else [])))
    if a.q1:
        import q1_save
        sys.exit(q1_save.main(a.build, rom, recs))
    if a.negative:
        base = os.path.dirname(a.build)
        # every planted-bug image is rebuilt, not only the missing ones: a stale one tests old sources (from a fresh clone
        # 2026-10-12's test_bug_go1 failed its stack check while an image left from an older build passed the rig)
        need = [v for v, w in VARIANT_BUGS if '@' not in v and (v != 'test' or not os.path.exists(os.path.join(base, v, 'main.nm')))]
        if need:
            cmd = [sys.executable, '-I', '-B', os.path.join(ROOT, 'tools', 'fwbuild.py'), 's1', '--images-only',
                   '--out', os.path.dirname(os.path.dirname(base))]
            for v in need:
                cmd += ['--variant', v]
            rr = subprocess.run(cmd, capture_output=True, text=True)
            if rr.returncode:
                print('SETUP ERROR: building %s failed:\n%s' % (need, rr.stdout[-2000:] + rr.stderr[-2000:]))
                sys.exit(2)
        ok = True
        for v, want in VARIANT_BUGS:
            if a.only and v not in a.only:
                continue
            wdog = want == 'FZ10'
            vrecs = cut(recs, max(a.frames, VARIANT_FRAMES.get(v, 0)))
            agg, fails = run_seeds(os.path.join(base, v.split('@')[0]), rom, vrecs, 1 if wdog else a.seeds, a.first,
                                   wdog_seed=a.first if wdog else None, quiet=True, stop_at_fail=want != 'PASS',
                                   dec_ns=SLOW_DEC_NS if v.endswith('@slowdec') else rtlmodel.DEC_NS)
            cats = sorted({(re.search(r'FZ\d+(?: length| decode)?|GO|DEC', x) or re.search(r'\w+', x)).group(0)
                           for sd, bs in fails for x in bs})
            got = 'PASS' if not fails else ' '.join(cats)
            hit = (want == 'PASS' and not fails) or (want != 'PASS' and fails and want in cats)
            ok &= bool(hit)
            print('%-4s %-16s expected %-4s: %d of %d seeds run failed  [%s]' % ('PASS' if hit else 'FAIL', v, want,
                                                                              len(fails), agg['seeds'], got[:90]), flush=True)
            if fails and not hit:
                print('      ' + '; '.join(fails[0][1][:3]))
        print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
        sys.exit(0 if ok else 1)
    if not os.path.exists(os.path.join(a.build, 'main.nm')):
        print('SETUP ERROR: no image at %s (tools/fwbuild.py s1)' % a.build)
        sys.exit(2)
    t0 = time.time()
    agg, fails = run_seeds(a.build, rom, recs, a.seeds, a.first, wdog_seed=a.first if a.wdog else None, sfx_strict=a.sfx_strict)
    us = lambda c: c * HW_CPI_RATIO / rtlmodel.NTSC * 1e6
    print('fuzz_s1 %s: %d seeds, capture frames 0-%d: %d B posts, %d A posts (%d extra), %d GOs, %d SENDs, %d brain calls, '
          '%d menu openings; taken MEI %d MTI %d MSI %d; FZ4 checks %d, FZ7 checks %d; SFX pushes %d, underruns %d (MODELLED, '
          'not failed without --sfx-strict); stack MEASURED %d B of the static %s B%s; FZ12: %d L1 bodies, the longest %04X '
          '%.0f us, outside the listed AD exception %04X %.0f us (budget 320 us at the hardware CPI; MODELLED), AD over it %d; '
          'FZ13 / FZ14: %d checks inside brain calls; %d brain calls, the longest wait from a brain post to its call %.0f us '
          '(the call takes the time that is left); %d feeder ticks, %d inside a brain call, %d of them catch-ups (late by '
          'more than one grid period); '
          '%.0f s' % (
              os.path.basename(a.build), agg['seeds'], a.frames, agg['posts_b'], agg['posts_a'], agg['extra_a'], agg['gos'],
              agg['sends'], agg['brain_calls'], agg['menus'], agg['taken']['MEI'], agg['taken']['MTI'], agg['taken']['MSI'],
              agg['fz4_checks'], agg['fz7_checks'], agg['sfx_pushes'], agg['underruns'], agg['stack_depth'], agg.get('stack_bound'),
              ('; FZ10: %s' % agg['wd']) if agg.get('wd') else '', agg['l1_bodies'], agg['l1_max_word'], us(agg['l1_max']),
              agg['l1_max_x_word'], us(agg['l1_max_x']), agg['l1_exempt_over'], agg['fz13_checks'], agg['fz13_calls'],
              us(agg['fz13_wait_max']), agg['fz14_checks'], agg['fz14_inside'], agg['fz14_late'], time.time() - t0))
    d = agg['dec']
    print('DEC (the RTL decoder, MODELLED at %.0f ns an access): %d runs, %d entries; %d AF / B1 DMA lists, %d window '
          'blocks, %d words read; late words %d, aborted runs %d; the longest run %.0f us; the smallest margin from a '
          'run\'s GO to its first DMA read %s' % (
              rtlmodel.DEC_NS, d['runs'], d['entries'], d['af_runs'], d['dma_blocks'], d['dma_words'], d['late_words'],
              d['aborts'], d['t_max'] / US, ('%.0f us' % (d['margin_min'] / US)) if d['margin_min'] is not None else '-'))
    print('FZ8 / FZ9: vacuous on a stage-1 image (no song tick; held posts and urgent promotions checked 0); proven on the '
          'probe by fuzz_sched.py')
    for sd, bs in fails[:6]:
        print('  seed %d: %s' % (sd, '; '.join(bs[:4])))
    if a.json:
        json.dump(dict(agg=agg, fails=fails), open(a.json, 'w'), indent=1)
    print('RESULT: %s' % ('PASS' if not fails else 'FAIL: %d of %d seeds' % (len(fails), agg['seeds'])))
    sys.exit(0 if not fails else 1)


if __name__ == '__main__':
    main()
