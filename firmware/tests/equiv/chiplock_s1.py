#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""chiplock_s1.py - stage 1: the chip lockstep on every command. The stage-1 firmware's host build (FW_S1: our new
firmware's own core), the cart's own program and (optionally) the final 0.2.6 host build ("final026") get the same
68000-side input, event by event, and every field is compared with the reference tests/equiv/s1_scope.json names for
that command and field. Stages are the steps of the 0.3.0 work (docs/ALLOWLIST.md lists them); Bnn are the rows of the
allow-list (docs/ALLOWLIST.md); test build 4 and S3a are firmware builds B Jam tested on his hardware; D-numbers are
the differences of our firmware audit (not in this tree).

Sides:
  chip  the cart's program in the cart-music runner on Unicorn, the CPU emulator library (its cartmcu.Machine and
        host68k.Host, read in place from paths.local.json "equiv"."chip_runner" or --runner; the runner checks its own
        image and ROM md5s); every
        MCU write to the register page 0x68040000-0x6804001F is logged with its PC and, for the status helper's two
        stores, the helper's caller; its FIFO-B data (a pointer with bit 14 = the $C000 window) is kept as the bytes
        the window serves (docs/CART_FPGA_SPEC.md section 15.1, allowed transform T2). Power-on, the boot page, app init
        (0.3 s), then the events. With frame time (the default) the chip runs 1/59.92 s of emulated time at every FRAME
        record, so its timers, the 83 trim's period and its main-loop tasks run as on the cart; the posts themselves run
        untimed ("fast mode": post -> the handler -> the job queue drained), as on ours.
  new   build/s1/host/s1_ours_<variant>.exe (tests/s1/s1_ours.c: the stage-1 core, the 0.2.6 bodies re-hosted, the
        fake board): its register-write log ('X'), the stored words ('Y'), the 68000 view ('V').
  ref   (--ref) the final 0.2.6 host build (the protocol of the audit harness, our test harness outside this tree), for
        the fields whose reference is final026.

Events: the capture from power-on, in order. RAMW (type 3) -> a cart-RAM write on every side (a word write of $1FEC is
the 68000's mailbox-A post: the 9494 frame tick on chip and new; final 0.2.6 never served mailbox A); CMD (type 2) ->
the 16 argument words at $1E10, then the post. FRAME (type 1) -> the chip's frame time (its writes there must all be
transforms). Per event the fields of s1_scope.json "fields" are compared; a difference FAILS unless a transform or an
exception of the scope file names its allow-list row (each counted). Plus, once per run: the boot (app init) writes.
The sprite words (since the sprite-values update of 2026-10-17; s1_scope.json "sprite" and "sprite_words",
tests/equiv/sprwords.py): after every
accepted AD the chip's $1F10 / $1F16 / $1F18 / $1F1A, after every accepted AF those and $1F1C, the AF's DMA descriptors,
SAT entries 0-129 and the $1F20 stash, every word (since test build 4: the attribute word too, D23 done the chip's way;
until test build 4 masked to
Y / link / X; s1_scope.json "chip_sat_words") ('sprite_chip'); against final 0.2.6 each sprite word may
start to differ only at a post that writes it the chip's way (AD: the SAT, $1F18; AF: all; C6: $1800 / $1802, B10), and
is counted until both sides agree again ('ramdp_sprite' when one starts anywhere else).

Synthetic list (--synth-at F): at frame F synth.py SYNTH_S1_MID (stage 0's list of the never-posted forms, with the
game's own arguments, 82, mailbox-A words) is posted on every side, then the capture continues, every field compared.
--tail posts synth.py SYNTH_S1_TAIL after the last frame: the chip's refusal forms and a second C6 (from there on only
the chip-referenced fields are compared: 0.2.6 acted on several of these forms, allow-list B28), EXTI 13 on the chip
only (it must write nothing), then 85, the fatal post that stops both MCUs.

Consoles (--consoles): no chip; for each option word of the Console table (paprium_opts: every model nibble, MegaWire
Off / On, Console region US / JP) new and ref replay the capture to --to and the fe4_view rule is checked at every
post (0x0004 | model before the first GO and after C6, the word the game reads at $BCA22; bit 2 = busy and the rest
= model at every post), plus new against ref with bit 2 masked (B2).

AF unit (--af-unit, since the sprite-values update; section 4.3 of our sprite-values specification, not in this tree):
after the capture's last frame (before the tail), the chip's frame end (its routine at 0x080190B8) against ours on
synthetic tables, through the real posts on both sides: every count 0-140 with AF00, AF01, AF02 (and AF03 up to 80;
above 80 the chip writes through a register that path never set: not done the chip's way), each on
both parities, on pseudo-random SAT contents (entries 0-143, every word) with $1F16 / $1F10 random; an
AF that no AE opened, and a B0 / F0 now and then (the parity must count them). Per case the 68000 writes the table and
posts AE, then the AF: every field of an AF is compared ('sprite_chip' included), and every word of SAT entries 0-143
and of the stash ('af_unit': the close copies the attribute word too). Final 0.2.6 takes no part.

Checkpoints (long corpora in segments of ~10 minutes): --save-at F stops at frame F and writes OUT/ckpt_F/ (the chip's
machine state, the rig's state); --resume DIR starts from one: the chip state is loaded and new / ref are
fast-forwarded from power-on by replaying the same records without comparing ('p' quiet posts on new). --merge
DIR... adds up finished segments and checks that they chain.

Exit 0 = PASS, 1 = FAIL (a difference outside the scope file's allowances, a post the chip did not finish, no event),
2 = setup error. The last line printed is 'RESULT: PASS' or 'RESULT: FAIL: ...'.
--plant KIND@N (negative controls, event N): regw = ours' log loses its last register write; stored = $1FE6 bit 6
(never set by the chip) forced into new's stored-word read; fe4 = new's $1FE4 view with bit 7 set.

usage: python -I -B chiplock_s1.py OUT --capture CAP --rom ROM --new EXE [--ref EXE] [--to F] [--opt W] [--test]
       [--no-frame-time] [--synth-at F] [--af-unit] [--tail] [--save-at F] [--resume DIR] [--sdram-every N] [--runner DIR]
       python -I -B chiplock_s1.py OUT --consoles --capture CAP --rom ROM --new EXE --ref EXE [--to F]
       python -I -B chiplock_s1.py OUT --merge SEGDIR [SEGDIR ...]"""
import argparse, collections, hashlib, json, mmap, os, pickle, struct, sys, time
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from hostside import HostSide   # noqa: E402
from sprwords import SpriteWords   # noqa: E402

REGNAME = {0: 'FE0', 2: 'FE2', 4: 'FE4', 6: 'FE6', 8: 'FE8', 0xA: 'FEA', 0xC: 'FEC', 0xE: 'FEE', 0x10: 'FF0',
           0x12: 'FF2', 0x14: 'FF4', 0x16: 'FF6', 0x18: 'FF8', 0x1A: 'FFA', 0x1C: 'FFC', 0x1E: 'FFE'}
HELPER_ST = ()                              # the chip's status helper stores ($1FE6 / $1FE4): s1_scope.json chip_sites
JOB_STEP_CALLER = None                      # the job step's bit-14 store (the C6 special transform): chip_sites
FE6_SPLIT = 0x2008                          # $1FE6 bits 3 and 13: row B12 until stage 5 (row B10's split)
FE6_MW_SEND = 0x0030                        # $1FE6 bits 4 / 5: E7's MegaWire send status (stage 3; see compare_event)
FE6_B10 = 0xE708                            # $1FE6 bits allow-list row B10 changes to
                                            # the chip reference (the rest: final026)
E7_KEY = ("E7 with MegaWire On: $1FE6 bits 4 / 5 = 0.2.6's signed-in look (bit 5 set) against the chip's no-module send "
          "(4 set then cleared by its task, 5 cleared, $1C10 := 0) - B6 (MegaWire On labelled; scope widening to bits 4 / 5 "
          "proposed, W13)")
MODEL_MASK = 0x740                          # option word bits 6, 8-10 = the $1FE4 Console model bits
MW_MASK = 0x70000                           # option word bits 16-18: MegaWire On (7)
SDR_S1 = 0x200000                           # the 2 MB workspace (both host builds)
BRAM_N = 0x2000                             # the 8 KB save (new); the 0.2.6 reference has 4 KB
FRAME_S = 1 / 59.922743
W8200 = struct.pack('<H', 0x8200)
SAVE_CMDS = {0x06, 0x1F, 0x20, 0x04, 0x05}  # table indexes whose post can touch the battery save
# the Console table (rtl/PAPRIUM/paprium_addons.sv paprium_opts): the model nibbles {bit 10, 9, 8, 6} of Console 0-8
# (every combined Mega CD unit forces 0) as option-word bits
CONSOLE_MODELS = [0x000, 0x700, 0x400, 0x600, 0x040]
REGPAGE_KEYS = ['register page vs final026: $%04X (%s)' % (0x1FE0 + 2 * i, 'B10' if i in (3, 5, 6) else 'not read by the game')
                for i in range(16)]


def h16(s):
    return int(s, 16) if isinstance(s, str) else s


def md5f(p):
    return hashlib.md5(open(p, 'rb').read()).hexdigest()


def load_scope(path):
    global HELPER_ST, JOB_STEP_CALLER
    sc = json.load(open(path))
    HELPER_ST = tuple(h16(x) for x in sc['chip_sites']['status_helper_stores'])
    JOB_STEP_CALLER = h16(sc['chip_sites']['job_step_bit14_caller'])
    tf = []
    for t in sc['transforms']:
        e = {'id': t['id'], 'row': t['row']}
        if 'pc' in t:
            e['pc'] = {h16(x) for x in t['pc']}
        if 'off' in t:
            e['off'] = h16(t['off'])
        if 'helper_caller' in t:
            e['caller'] = (h16(t['helper_caller'][0]), h16(t['helper_caller'][1]))
        if 'special' in t:
            e['special'] = t['special']
        tf.append(e)
    sc['_tf'] = tf
    sc['_exc'] = {e['id']: e for e in sc['exceptions']}
    return sc


def cmd_index(word, mbx):
    """the chip's table index for a post: (word & 0x3FFF) >> 8 on mailbox B, (word & 0x3F00) >> 8 on A"""
    return ((word & 0x3FFF) if mbx == 'B' else (word & 0x3F00)) >> 8


def scope_of(sc, idx):
    key = '%02X' % idx
    base = dict(sc['commands']['default']['fields'])
    c = sc['commands'].get(key)
    if c is None:
        return 'default', base, {}
    base.update(c.get('fields', {}))
    return key, base, c


# ------------------------------------------------------------------ the chip side
class Chip:
    def __init__(self, runner, frame_time=True, ckpt=None):
        if runner not in sys.path:
            sys.path.insert(0, runner)
        import cartmcu
        import host68k
        from unicorn import UC_HOOK_MEM_WRITE
        from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP
        self.cartmcu = cartmcu
        m = cartmcu.Machine(verbose=0, log_mmio=False)
        m.watchdog_us = 300_000_000             # the runner's wall-clock fallback to counted mode: under heavy machine
                                                # load (measured 2026-10-15, load ~53 on 12 cores) the C6 job's
                                                # emulation passed the old 20 s, the runner left fast mode and ended the
                                                # post before its job ran (a rig artifact:
                                                # 'stored' / 't2_bytes' at C6 / DA02 / DB06)
        self.m = m
        self.frame_time = frame_time
        self.seq = []
        self.bytew = 0
        FPGA = cartmcu.FPGA

        def hk(uc, acc, a, sz, v, ud):
            pc = uc.reg_read(UC_ARM_REG_PC)
            caller = 0
            if pc in HELPER_ST:
                sp = uc.reg_read(UC_ARM_REG_SP)
                caller = struct.unpack('<I', bytes(uc.mem_read(sp + 0xC, 4)))[0] & ~1
            off = a - FPGA
            if sz == 4:
                self.seq.append((off, v & 0xFFFF, pc, caller))
                self.seq.append((off + 2, (v >> 16) & 0xFFFF, pc, caller))
            elif sz == 1:
                self.bytew += 1
                self.seq.append((off, v & 0xFF, pc, caller | 1))
            else:
                self.seq.append((off, v & 0xFFFF, pc, caller))
        m.mu.hook_add(UC_HOOK_MEM_WRITE, hk, begin=FPGA, end=FPGA + 0x1F)
        self.h = host68k.Host(m, verbose=0)                 # the boot page into RAMDP (power-on)
        # FIFO B (CART_FPGA_SPEC.md 15.1, allowed transform T2): the runner writes every FIFO port's halfwords into
        # RAMDP at the port pointer (its model of FIFO A, the Z80 packet). A FIFO-B pointer with bit 14 (DB06: 0xC002)
        # is the $C000 window, not cart RAM, so those halfwords are kept here as
        # the bytes the window serves (the audit harness's rule)
        self.fifo_b = bytearray()
        orig = m.fifo_write

        def fifo_write(port, data, _orig=orig):
            if port == 1 and struct.unpack('<H', bytes(m.mu.mem_read(FPGA + 0x12, 2)))[0] & 0x4000:
                self.fifo_b += data
                return
            _orig(port, data)
        m.fifo_write = fifo_write
        self.md5s = {'cartmcu.py': md5f(cartmcu.__file__), 'host68k.py': md5f(host68k.__file__),
                     'chip_image': md5f(cartmcu.IMG_PATH), 'chip_rom': md5f(cartmcu.ROM_PATH)}
        if ckpt:
            m.load_state(ckpt)

    def take(self):
        s, self.seq = self.seq, []
        return s

    def take_fifo_b(self):
        b, self.fifo_b = bytes(self.fifo_b), bytearray()
        return b

    def boot(self):
        self.m.run(seconds=0.3)
        return self.take()

    def post(self, word, args, timeout=10.0):
        m = self.m
        if args is not None:
            for i, w in enumerate(args):
                m.w68(0x1E10 + 2 * i, w)
        m.wreg68(0x1FEA, word)
        m.raise_exti(14)
        ok = m.run(seconds=timeout, until=lambda mm: not (mm.reg68(0x1FEA) & 0x8000))
        return bool(ok) and not (m.reg68(0x1FEA) & 0x8000) and m.fault is None

    def tick(self, word, timeout=0.05):
        m = self.m
        m.wreg68(0x1FEC, word)
        m.raise_exti(15)
        ok = m.run(seconds=timeout, until=lambda mm: mm.reg68(0x1FEC) == 0)
        return bool(ok) and m.reg68(0x1FEC) == 0 and m.fault is None

    def frame(self):
        if self.frame_time:
            self.m.run(seconds=FRAME_S)

    def exti13(self):
        self.m.raise_exti(13)
        self.m.run(seconds=0.002)

    def ram(self, a, n=2):
        return bytes(self.m.ramdp[a:a + n])

    def w68(self, a, data):
        m = self.m
        if len(data) == 2:
            w = struct.unpack('<H', data)[0]
            if a >= 0x1FE0:
                m.wreg68(a, w)
            else:
                m.w68(a, w)
        else:
            if a >= 0x1FE0:
                m.mu.mem_write(self.cartmcu.FPGA + (a - 0x1FE0), data)
            else:
                m.ramdp[a] = data[0]

    def stored(self):
        b = bytes(self.m.mu.mem_read(self.cartmcu.FPGA, 0x20))
        return struct.unpack('<16H', b)


# ------------------------------------------------------------------ the transforms (chip writes of later stages)
def chip_filter(seq, tf, ev_idx, cnt):
    out = []
    for w in seq:
        off, v, pc, caller = w
        hit = None
        for t in tf:
            if 'special' in t:
                continue
            if 'pc' in t and pc in t['pc'] and ('off' not in t or t['off'] == off):
                hit = t
                break
            if 'caller' in t and pc in HELPER_ST and t['caller'][0] <= caller <= t['caller'][1]:
                hit = t
                break
        if hit:
            cnt[hit['id']] += 1
            continue
        out.append(w)
    if ev_idx == 0x06:                      # C6: the job-step bit-14 stores while the MegaWire job 6 is still queued
        t = next(t for t in tf if t.get('special') == 'c6_job_steps')
        ends = [i for i, x in enumerate(out) if x[3] == JOB_STEP_CALLER]
        for i in reversed(ends[:-1]):
            del out[i]
            cnt[t['id']] += 1
    return out


def norm(off, v, mw=False):
    if off == 6:
        return (off, v & ~(FE6_SPLIT | (7 if mw else 0)))
    return (off, v)


# ------------------------------------------------------------------ the host sides
class New(HostSide):
    def q_x(self):
        self.q(b'X')

    def r_x(self):
        n = struct.unpack('<I', self.read(4))[0]
        return list(struct.unpack('<%dI' % n, self.read(4 * n))) if n else []

    def q_y(self):
        self.q(b'Y')

    def r_y(self):
        b = self.read(64)
        return struct.unpack_from('<16H', b, 0), struct.unpack_from('<16H', b, 32)

    def q_v(self):
        self.q(b'V')

    def r_v(self):
        n = struct.unpack('<I', self.read(4))[0]
        b = self.read(n)
        view = struct.unpack_from('<16H', b, 0)
        fl = b[32 + 7] if n >= 40 else 0
        return view, {'guard': fl & 1, 'valid': (fl >> 1) & 1, 'window': (fl >> 2) & 1, 'mini': (fl >> 3) & 1}

    def q_quiet(self, word):
        self.q(b'p' + struct.pack('<H', word))


def records(cap):
    f = open(cap, 'rb')
    return f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)


# ------------------------------------------------------------------ the rig's state
class Rig:
    KEYS = ('fails', 'allowed', 'transforms', 'counted', 'per_cmd', 'per_cmd_fail', 'first', 'events', 'posts',
            'ticks', 'frames', 'notdone', 'first_go_seen', 'c6_window', 'frame_open', 'gos', 'starts',
            'synth_rows', 'fe4_checks', 'after84', 'in_tail', 'frame_open_at_post', 't2_events', 't2_bytes', 'mw_send', 'last_fe6',
            'prev_ptr', 'ptr_div', 'pushes', 'spr_sd', 'in_unit', 'unit_cases', 'zoom_div', 'zoom_bram', 'zoom_ram')

    def __init__(self, a, sc):
        self.a, self.sc = a, sc
        self.fails = collections.Counter()
        self.allowed = collections.Counter()
        self.transforms = collections.Counter()
        self.counted = collections.Counter()
        self.per_cmd = collections.Counter()
        self.per_cmd_fail = collections.Counter()
        self.first = []
        self.events = self.posts = self.ticks = self.frames = self.notdone = 0
        self.first_go_seen = False
        self.c6_window = False
        self.frame_open = False
        self.frame_open_at_post = False
        self.gos = self.starts = 0
        self.synth_rows = []
        self.fe4_checks = 0
        self.after84 = False
        self.in_tail = False
        self.in_unit = False                 # --af-unit: synthetic AE / AF cases, chip and ours only
        self.unit_cases = collections.Counter()
        self.mw_send = False
        self.last_fe6 = [None, None]
        self.t2_events = self.t2_bytes = 0
        self.prev_ptr = [None, None]         # row B38: the (final026, stage-1) pointers after the last post
        self.ptr_div = None
        self.pushes = 0                      # the decoder entries ours pushed (compared with the chip's, write for write)
        self.spr = SpriteWords(sc)           # the sprite words (chip at AD / AF; final026 by word)
        self.zoom_div = False                # stage 3 (test build S3a, row B53): the zoom page differs from final 0.2.6
        self.zoom_bram = {}                  # B53: save slot -> its 0.2.6 BRAM range, written from the zoom page
        self.zoom_ram = set()                # B53: cart-RAM words a DF filled from such a slot
        self.cur_word, self.cur_aw = 0, None
        self.spr_sd = self.spr.state()

    def fail(self, kind, ev, info):
        self.fails[kind] += 1
        self.per_cmd_fail['%s %s' % (ev.get('cmd'), kind)] += 1
        if len(self.first) < 300:
            self.first.append(dict(ev, kind=kind, info=info))

    def state(self):
        self.spr_sd = self.spr.state()
        return {k: getattr(self, k) for k in self.KEYS}

    def restore(self, st):
        for k, v in st.items():
            setattr(self, k, collections.Counter(v) if isinstance(getattr(self, k), collections.Counter) else v)
        self.spr.restore(self.spr_sd)


def fmt_w(ws, chip=False):
    if chip:
        return ['%s=%04X@%08X%s' % (REGNAME.get(o, '%02X' % o), v, pc, ('<%08X' % c) if c else '') for o, v, pc, c in ws]
    return ['%s=%04X' % (REGNAME.get(o, '%02X' % o), v) for o, v in ws]


def compare_event(rig, ev, idx, chip_seq, new_log, new_y, new_v, chip_stored, opt):
    """the chip-referenced fields and the rules for one event (post, tick, frame time, boot)"""
    sc = rig.sc
    fields = scope_of(sc, idx)[1] if idx is not None else {}
    cs = chip_filter(chip_seq, sc['_tf'], idx, rig.transforms)
    regs = [((e >> 16) & 0x1F, e & 0xFFFF) for e in new_log if not (e >> 30)]
    board = [({0x40: 'SPTR', 0x41: 'GO', 0x42: 'DECB', 0x43: 'RTLGO'}.get(e >> 24, 'TAG%02X' % (e >> 24)), e & 0xFFFFFF)
             for e in new_log if (e >> 30)]
    mw = bool(opt & MW_MASK)                # MegaWire On: $1FE6 bits 0-2 are the option's, the runner has no module (B6)
    A = [norm(o, v, mw) for o, v, _, _ in cs]
    B = [norm(o, v, mw) for o, v in regs]
    if mw and ev.get('ev') == 'boot':
        # MegaWire On: the board boot stores the option's status in $1FE6 bits 0-2 (BOOT_SPEC, MegaWire status); the
        # runner's chip finds no module and writes nothing there. A write that changes only bits 0-2 is B6's label
        prev, keep = None, []
        for o, v in regs:
            if o == 6 and prev is not None and (prev & ~7) == (v & ~7):
                rig.allowed['boot: $1FE6 bits 0-2 := the MegaWire option (B6, labelled)'] += 1
            else:
                keep.append(norm(o, v, mw))
            if o == 6:
                prev = v
        B = keep
    e7 = mw and (rig.mw_send or idx == 0x27)
    if e7:
        # E7 with MegaWire On (row B6: the plan's decision 6 keeps 0.2.6's signed-in look; the game posts E7 only when
        # $1FE6 bits 0-2 != 0): from the first E7 on, $1FE6 bits 4 / 5 are compared with neither side, and a $1FE6 write
        # that changes only them (after the masks) is dropped on both sides, counted under E7_KEY. With MegaWire Off
        # the chip's no-module path is the reference: a difference there FAILS
        mask = FE6_SPLIT | FE6_MW_SEND | (7 if mw else 0)

        def dedupe(ws, prev):
            out = []
            for o, v in ws:
                if o == 6:
                    if prev is not None and (v & ~mask) == (prev & ~mask):
                        rig.allowed[E7_KEY] += 1
                        continue
                    prev = v
                    v &= ~mask
                out.append((o, v))
            return out
        A = dedupe(A, rig.last_fe6[0])
        B = dedupe(B, rig.last_fe6[1])
    # ours never sets $1FE6 bits 3 / 13 (stage 1 sets neither; row B12 until stage 5)
    if any(o == 6 and (v & FE6_SPLIT) for o, v in regs):
        rig.fail('fe6_split_bit_set_by_ours', ev, fmt_w(regs))
    # regwrites
    if A != B and fields.get('regwrites', 'chip') == 'chip':
        rig.fail('regwrites', ev, {'chip': fmt_w(cs, True)[:24], 'new': fmt_w(regs)[:24]})
    # T4: every FIFO-B start (0xC002) is followed by a firmware GO in the same event; every decoder start (0x8000) with
    # a push since the last queue clear has the board's DEC_BASE write after its last push (MCU interface v1.2: the RTL
    # loads SPTR with it) and the RTL decoder's own GO after it (the host board's model decodes at the START); an
    # empty-queue start (app init, a load-less flush, DA07's prelude) serves nothing and is counted
    queued, decb = False, False
    for i, e in enumerate(new_log):
        if e >> 30:
            if (e >> 24) == 0x42:
                decb = True
            continue
        off, val = (e >> 16) & 0x1F, e & 0xFFFF
        if off == 0x16:
            queued = not (val & 1)
            decb = False
            if queued:
                rig.pushes += 1
                rig.counted['decoder entries pushed (stage 1j: compared write for write with the chip, regwrites)'] += 1
        elif off == 0x12 and val in (0x8000, 0xC002):
            if val == 0xC002:
                rig.starts += 1
                if not any((x >> 24) == 0x41 for x in new_log[i + 1:]):
                    rig.fail('go_after_start', ev, {'new': fmt_w(regs), 'board': board})
            elif queued:
                rig.starts += 1
                if not decb:
                    rig.fail('dec_base_before_start', ev, {'new': fmt_w(regs), 'board': board})
                if not any((x >> 24) == 0x43 for x in new_log[i + 1:]):
                    rig.fail('rtl_go_after_start', ev, {'new': fmt_w(regs), 'board': board})
            else:
                rig.counted['decoder start with an empty queue (no decoder effect, MCU interface v1.2)'] += 1
            queued, decb = False, False
    rig.gos += sum(1 for k, v in board if k in ('GO', 'RTLGO'))
    if any(k in ('GO', 'RTLGO') for k, v in board):
        rig.first_go_seen = True
    # stored words (the MCU side): the chip's register page against ours' stored $1FE4 / 6 / A / C
    if chip_stored is not None and new_y is not None:
        st_new = new_y[0]
        bad = []
        for off in (4, 6, 0xA, 0xC):
            c, n = chip_stored[off >> 1], st_new[off >> 1]
            if off == 6:
                c, n = c & ~FE6_SPLIT, n & ~FE6_SPLIT
                if e7 and (c & FE6_MW_SEND) != (n & FE6_MW_SEND):
                    rig.allowed[E7_KEY] += 1
                    c, n = c & ~FE6_MW_SEND, n & ~FE6_MW_SEND
                if mw and (c & 7) != (n & 7):
                    rig.allowed['$1FE6 bits 0-2 with MegaWire On: the runner has no module (B6, labelled)'] += 1
                    c, n = c & ~7, n & ~7
            if c != n:
                bad.append('%s chip %04X new %04X' % (REGNAME[off], chip_stored[off >> 1], st_new[off >> 1]))
        if bad:
            rig.fail('stored', ev, bad)
    if chip_stored is not None:
        rig.last_fe6 = [chip_stored[3], new_y[0][3] if new_y is not None else rig.last_fe6[1]]
    # the 68000's $1FE4 (composer rule) and the register page words the game does not read
    if new_v is not None:
        view, fl = new_v
        busy = 1 if (fl['guard'] or not fl['valid']) else 0
        want = (busy << 2) | (opt & MODEL_MASK)
        rig.fe4_checks += 1
        if view[2] != want:
            rig.fail('fe4_view', ev, '%04X, composer %04X (busy %d model %03X)' % (view[2], want, busy, opt & MODEL_MASK))
        elif not rig.first_go_seen and view[2] != (0x0004 | (opt & MODEL_MASK)):
            rig.fail('fe4_view_before_go', ev, '%04X' % view[2])
        for off in (0, 2, 8, 0xE, 0x10, 0x12, 0x14, 0x16, 0x18, 0x1A, 0x1C, 0x1E):
            if view[off >> 1]:
                rig.fail('regpage_other_nonzero', ev, '%s = %04X' % (REGNAME[off], view[off >> 1]))
    return cs, regs, board


def compare_ref(rig, ev, idx, nr, rr, centry):
    """the final026-referenced fields of a mailbox-B post (as s1_equiv.py, with the scope file's chip words)"""
    x, y = rr, nr                    # x = final 0.2.6, y = stage 1
    chip_words = {h16(w) for w in centry.get('ram_chip_words', [])}
    started, bad, differ = rig.spr.ref_step(idx, x[0], y[0])
    if started:
        rig.counted['%s sprite words: started to differ from final 0.2.6 at a post of %s (update s1-sprval: chip-referenced)' % (
            rig.spr.row, ev.get('cmd'))] += 1
    if differ:
        rig.counted['%s sprite words: differ from final 0.2.6 after the post (posts; chip-referenced at AD / AF)' % rig.spr.row] += 1
    if bad:
        rig.fail('ramdp_sprite', ev, ['started to differ from final 0.2.6 at a post that does not write them: ' + ', '.join(bad[:8])])
    # B53 carried: an E0 that saves from the zoom page while it differs takes the difference into its slot of the
    # battery save (0.2.6's layout: slot 4 at $000-$1FF, slots 1-3 at $200 + slot x $200, $100 each), and a DF of
    # such a slot into the cart-RAM words it fills
    lo8, aw = rig.cur_word & 0xFF, rig.cur_aw or [0] * 16
    if idx in (0x1F, 0x20) and lo8 in (1, 2, 3, 4):
        nb = 0x200 if lo8 == 4 else 0x100
        blo = 0 if lo8 == 4 else 0x200 + 0x200 * lo8
        if idx == 0x20:
            if rig.zoom_div and aw[1] < 0xA00 and aw[1] + nb > 0x200:
                rig.zoom_bram[lo8] = (blo, blo + nb)
            else:
                rig.zoom_bram.pop(lo8, None)
        elif lo8 in rig.zoom_bram:
            rig.zoom_ram |= set(range(aw[0] & ~1, (aw[0] & ~1) + nb, 2))
    # stage 3 (test build S3a, allow-list row B53): the zoom page $0200-$09FF is the chip's (its F5 rescale and
    # copy-out, job 8's save, B6's restore: core/zoom), held to the chip after every mailbox-B post (the event loop);
    # against final 0.2.6 it may start to differ only at an F5 or
    # a B6, and is counted, not compared, until both agree again
    if x[0][0x200:0xA00] != y[0][0x200:0xA00]:
        if idx in (0x35, 0x36) or rig.zoom_div:
            rig.zoom_div = True
            rig.allowed['B53 zoom page $0200-$09FF: differs from final 0.2.6 since an F5 / B6 (the chip\'s zoom, held to the chip)'] += 1
        else:
            zw = [w_ for w_ in range(0x200, 0xA00, 2) if x[0][w_:w_ + 2] != y[0][w_:w_ + 2]]
            rig.fail('ramdp_zoom', ev, ['started to differ at a post that is no F5 / B6: %d words from $%04X' % (
                len(zw), zw[0])])
    else:
        rig.zoom_div = False
    rngs = [(r0, r1) for r0, r1 in rig.spr.ranges if x[0][r0:r1] != y[0][r0:r1]]
    if rngs:
        left = []
        for wa in (w_ for r0, r1 in rngs for w_ in range(r0, r1, 2)):
            p, q = x[0][wa:wa + 2], y[0][wa:wa + 2]
            if p == q or 0x200 <= wa < 0xA00:
                rig.zoom_ram.discard(wa)
                continue
            if wa in rig.zoom_ram:
                rig.allowed['B53 zoom page carried: cart RAM a DF filled from a save written from the zoom page'] += 1
                continue
            if wa == 0x1E4 and q == b'\x00\xff':
                rig.allowed['$1E4 = $FF00 (B20)'] += 1
            elif wa in (0x1800, 0x1802) and rig.c6_window:
                rig.allowed["C6's $1800 / $1802 := 0 until the next 88 (B10)"] += 1
            elif wa in chip_words:
                rig.allowed['%s: chip word $%04X (%s)' % (ev['cmd'], wa, centry.get('final026_row', '?'))] += 1
            elif wa == 0x0006 and rig.after84 and q == W8200:
                rig.allowed["84's $0006 := $8200 left in cart RAM after it (B26, Z5 proposed)"] += 1
            else:
                left.append('$%04X %04X/%04X' % (wa, struct.unpack('<H', p)[0], struct.unpack('<H', q)[0]))
        if left:
            rig.fail('ramdp', ev, left[:12] + (['... %d words' % len(left)] if len(left) > 12 else []))
    # the 68000's register page against final 0.2.6: $1FE4 bit 2 masked (B2), $1FE6 / $1FEA / $1FEC a change of
    # reference (B10, compared with the chip), the rest not read by the game (counted)
    px, py = x[0][0x1FE0:], y[0][0x1FE0:]
    if px != py:
        rx, ry = struct.unpack('<16H', px), struct.unpack('<16H', py)
        for i in range(16):
            if rx[i] != ry[i]:
                if i == 2:
                    if (rx[2] & ~4) != (ry[2] & ~4):
                        rig.fail('fe4_view_vs_final026', ev, '%04X/%04X' % (rx[2], ry[2]))
                elif i == 3 and (rx[3] & ~FE6_B10) != (ry[3] & ~FE6_B10):
                    rig.fail('fe6_vs_final026', ev, '%04X/%04X (bits outside B10: %04X/%04X)' % (
                        rx[3], ry[3], rx[3] & ~FE6_B10, ry[3] & ~FE6_B10))
                else:
                    rig.counted[REGPAGE_KEYS[i]] += 1
    fx, fy = struct.unpack('<6I', x[1]), struct.unpack('<6I', y[1])
    if fx[2] != fy[2]:
        pp = rig.prev_ptr
        if idx in (0x2F, 0x31) and fy[2] == pp[1] and fx[2] != pp[0]:
            rig.allowed['B38: an empty flush leaves SPTR (the cart\'s START with no entry), 0.2.6 rewound it'] += 1
            rig.ptr_div = [fx[2], fy[2]]
        elif idx == 0x31 and fx[2] == pp[0] and fy[2] != pp[1]:
            rig.allowed['B38: a B1 with loads points the window at its decode (0.2.6 left it)'] += 1
            rig.ptr_div = [fx[2], fy[2]]
        elif rig.ptr_div == [fx[2], fy[2]]:
            rig.allowed['B38: the pointer pair an empty flush left, carried (no window read)'] += 1
        else:
            rig.fail('pointer', ev, ['%06X' % fx[2], '%06X' % fy[2]])
    else:
        rig.ptr_div = None
    rig.prev_ptr = [fx[2], fy[2]]
    if (fx[3] & 0xFF, fx[4] & 0xFF) != (fy[3] & 0xFF, fy[4] & 0xFF):
        rig.fail('volumes', ev, [fx[3], fx[4], fy[3], fy[4]])
    if x[3] != y[3]:
        rig.fail('audio', ev, [x[3].hex(), y[3].hex()])


def bram_check(rig, new, ref, ev):
    new.q_bram(0, BRAM_N)
    ref.q_bram(0, 0x1000)
    new.flush()
    ref.flush()
    bn, br = new.read(BRAM_N), ref.read(0x1000)
    if bn[:0x900] != br[:0x900] and rig.zoom_bram:     # B53 carried: the slots an E0 wrote from the zoom page
        bn, br = bytearray(bn), bytearray(br)
        for lo, hi in rig.zoom_bram.values():
            if bn[lo:hi] != br[lo:hi]:
                rig.allowed['B53 zoom page carried: a save slot written from the zoom page'] += 1
            bn[lo:hi] = br[lo:hi] = bytes(hi - lo)
    if bn[:0x900] != br[:0x900]:
        rig.fail('bram_saves', ev, None)
    if bn[0x900:0x1000] != br[0x900:0x1000]:
        if rig.a.test:
            rig.allowed['TEST BRAM $900-$FFF (A1)'] += 1
        else:
            rig.fail('bram_900', ev, None)
    if any(bn[0x1000:]):
        if rig.a.test:
            rig.allowed['TEST debug record $1000-$1FFF (A1, B33)'] += 1
        else:
            rig.fail('bram_1000_release', ev, None)


def sdram_check(rig, new, ref, ev):
    new.q_mem(0, SDR_S1)
    ref.q_mem(0, SDR_S1)
    new.flush()
    ref.flush()
    sn, sr = new.read(SDR_S1), ref.read(SDR_S1)
    rig.counted['sdram checkpoints'] += 1
    if sn != sr:
        gran = [g for g in range(0, SDR_S1, 256) if sn[g:g + 256] != sr[g:g + 256]]
        rig.fail('sdram', ev, '%d granules differ, first %s' % (len(gran), ['%06X' % g for g in gran[:6]]))


def synth_args(new, sets):
    """the 16 argument words: the cart RAM's (new's view) with the list's values set (synth.py's rule)"""
    new.q_all()
    new.flush()
    ram, _ = new.r_all()
    w16 = list(struct.unpack_from('<16H', ram, 0x1E10))
    for i, v in sets.items():
        w16[i] = v
    return struct.pack('<16H', *w16)


def ff_post(new, ref, word, args, mbx):
    """fast-forward: the same inputs as the compared run, replies not read until ff_drain"""
    if args is not None:
        new.q_w(0x1E10, args)
        if ref:
            ref.q_w(0x1E10, args)
    if mbx == 'B':
        new.q_quiet(word)
        new.pend = getattr(new, 'pend', 0) + 1
        if ref:                     # one post at a time: its 8 KB replies would fill the pipe and deadlock a batch
            ref.q_post(word)
            ref.flush()
            ref.r_post()
    else:
        new.q_w(0x1FEC, struct.pack('<H', word))
        if ref:
            ref.q_w(0x1FEC, struct.pack('<H', word))


def ff_drain(new, ref):
    new.flush()
    if ref:
        ref.flush()
    for _ in range(getattr(new, 'pend', 0)):
        new.k()
    new.pend = 0


def save_ckpt(a, chip, rig, offset, post_no, synth_done, f):
    dd = os.path.join(a.out, 'ckpt_%d' % f)
    os.makedirs(dd, exist_ok=True)
    chip.m.save_state(os.path.join(dd, 'chip.pkl'))
    pickle.dump({'offset': offset, 'frame': f, 'post_no': post_no, 'synth_done': synth_done, 'rig': rig.state(),
                 'capture_md5': md5f(a.capture), 'new_md5': md5f(a.new), 'ref_md5': md5f(a.ref) if a.ref else None,
                 'opt': a.opt, 'synth_at': a.synth_at}, open(os.path.join(dd, 'rig.pkl'), 'wb'))


def rows_of(sc, cnt):
    out = collections.Counter()
    rows = {t['id']: t['row'] for t in sc['_tf']}
    for k, v in cnt.items():
        out[rows.get(k, '?')] += v
    return dict(out)


# ------------------------------------------------------------------ the lockstep
def lockstep(a, sc, runner):
    t0 = time.time()
    rom = open(a.rom, 'rb').read()
    rig = Rig(a, sc)
    plant_kind, plant_at = (a.plant.split('@')[0], int(a.plant.split('@')[1])) if a.plant else (None, -1)
    resume = None
    if a.resume:
        resume = pickle.load(open(os.path.join(a.resume, 'rig.pkl'), 'rb'))
        if (resume['capture_md5'] != md5f(a.capture) or resume['new_md5'] != md5f(a.new) or resume['opt'] != a.opt
                or resume['ref_md5'] != (md5f(a.ref) if a.ref else None) or resume['synth_at'] != a.synth_at):
            print('RESULT: setup error: the checkpoint is for another capture, build, option word or synthetic point')
            return 2
    chip = Chip(runner, not a.no_frame_time, os.path.join(a.resume, 'chip.pkl') if resume else None)
    new = New('new', a.new)
    ref = HostSide('ref', a.ref) if a.ref else None
    hosts = [new] + ([ref] if ref else [])
    for h in hosts:
        h.q_load(rom)
        h.q_opt(a.opt)
        h.q_reset()
        h.flush()
    for h in hosts:
        h.k(); h.k(); h.k()
    import synth
    synth_list = list(synth.SYNTH_S1_MID)
    capf, d = records(a.capture)
    o, frame = 0, -1
    post_no = 0
    synth_done = False
    seg_from = 0
    if resume:
        # fast-forward new / ref from power-on to the checkpoint's record offset (no comparison)
        rig.restore(resume['rig'])
        new.q_x(); new.flush(); new.r_x()
        o_end = resume['offset']
        nq = 0
        while o + 20 <= len(d) and o < o_end:
            t, ln, f = struct.unpack_from('<HHI', d, o)
            po = o + 20
            o = po + ln
            if t == 1:
                frame = f
                if a.synth_at >= 0 and f >= a.synth_at and not synth_done:
                    for word, sets, what, mbx in synth_list:
                        ff_drain(new, ref)
                        ff_post(new, ref, word, synth_args(new, sets) if mbx == 'B' else None, mbx)
                    synth_done = True
                continue
            if t == 3:
                ad, wd, v = struct.unpack_from('<HHH', d, po)
                if ad >= 0x2000:
                    continue
                off, data = (ad & ~1, struct.pack('<H', v)) if wd == 2 else (ad ^ 1, bytes([v & 0xFF]))
                for h in hosts:
                    h.q_w(off, data)
                continue
            if t == 2:
                wv = struct.unpack_from('<18H', d, po)
                ff_post(new, ref, wv[0], struct.pack('<16H', *wv[2:18]), 'B')
                nq += 1
                if nq >= 256:
                    ff_drain(new, ref)
                    nq = 0
        ff_drain(new, ref)
        new.q_x(); new.flush(); new.r_x()          # the fast-forward's log is not this segment's
        seg_from = resume['frame']
        synth_done = resume['synth_done']
        post_no = resume['post_no']
    else:
        # the boot: app init on the chip, the stage-1 boot on new
        cw = chip.boot()
        new.q_x(); new.q_y(); new.q_v(); new.flush()
        log, y, v = new.r_x(), new.r_y(), new.r_v()
        compare_event(rig, {'ev': 'boot', 'cmd': 'boot', 'frame': -1}, None, cw, log, y, v, chip.stored(), a.opt)
        if ref:
            ref.q_all(); new.q_all()
            ref.flush(); new.flush()
            (r0, _), (n0, _) = ref.r_all(), new.r_all()
            diff = [x for x in range(0, 0x1FE0, 2) if r0[x:x + 2] != n0[x:x + 2]]
            if any(x != 0x1E4 for x in diff) or struct.unpack_from('<H', n0, 0x1E4)[0] != 0xFF00:
                rig.fail('boot_ramdp', {'ev': 'boot', 'cmd': 'boot'}, ['$%04X' % x for x in diff[:12]])
            else:
                rig.allowed['$1E4 = $FF00 (B20)'] += len(diff)
            sdram_check(rig, new, ref, {'ev': 'checkpoint', 'cmd': 'boot', 'frame': -1})
    sdram_next = (max(seg_from, 0) // a.sdram_every + 1) * a.sdram_every if a.sdram_every else None

    def do_post(word, args, mbx, f, tag=None):
        nonlocal post_no
        ev = {'ev': 'post' if mbx == 'B' else 'A', 'word': '%04X' % word, 'frame': f, 'post_no': post_no}
        idx = cmd_index(word, mbx)
        ev['cmd'] = sc['commands'].get('%02X' % idx, {}).get('name', '%02X' % idx) + ('' if mbx == 'B' else ' (A)')
        rig.per_cmd[ev['cmd']] += 1
        rig.frame_open_at_post = rig.frame_open
        spr_mode = sc['commands'].get('%02X' % idx, {}).get('sprite_chip') if mbx == 'B' else None
        pre_spr = chip.ram(0x1F10, 0x10) if spr_mode else None
        if idx == 0x2F and mbx == 'B' and not rig.frame_open:
            rig.counted['AF without an open frame: the finish only, chip and ours (D38, copied since update s1-sprval)'] += 1
        fatal = idx == 0x05
        if fatal:
            chip.m.watchdog_us = 500_000            # 85 halts the chip: do not spin for the full wall watchdog
        aw = list(struct.unpack('<16H', args)) if args is not None else None
        rig.cur_word, rig.cur_aw = word, aw             # (B53 carried: compare_ref reads E0 / DF's arguments)
        if mbx == 'B':
            ok = chip.post(word, aw, 0.01 if fatal else 10.0)
        else:
            if aw is not None:
                for i, w_ in enumerate(aw):
                    chip.m.w68(0x1E10 + 2 * i, w_)
            ok = chip.tick(word, 0.01 if fatal else 0.05)
        cw = chip.take()
        rf = ref if (ref and not (rig.in_tail or rig.in_unit)) else None    # the tail never reaches final 0.2.6 (B28;
                                                                             # some forms crash it), nor the AF unit
        if args is not None:
            new.q_w(0x1E10, args)
            if rf:
                rf.q_w(0x1E10, args)
        if mbx == 'B':
            new.q_post(word)
            if rf:
                rf.q_post(word)
        else:
            new.q_w(0x1FEC, struct.pack('<H', word))
            if rf:
                rf.q_w(0x1FEC, struct.pack('<H', word))
        new.q_x(); new.q_y(); new.q_v()
        new.flush()
        if rf:
            rf.flush()
        nr = new.r_post() if mbx == 'B' else None
        log, y, v = new.r_x(), new.r_y(), new.r_v()
        rr = rf.r_post() if (rf and mbx == 'B') else None
        if plant_kind and post_no == plant_at:
            if plant_kind == 'regw' and log:
                log = log[:-1]
            elif plant_kind == 'stored':
                y = (tuple(y[0][:3]) + (y[0][3] | 0x0040,) + tuple(y[0][4:]), y[1])
            elif plant_kind == 'fe4':
                v = (tuple(v[0][:2]) + (v[0][2] | 0x0080,) + tuple(v[0][3:]), v[1])
        if not ok and not fatal:
            rig.notdone += 1
            rig.fail('chip_not_done', ev, 'the chip did not finish the post (fault %s)' % (chip.m.fault,))
        cs, regs, board = compare_event(rig, ev, idx, cw, log, y, v, chip.stored(), a.opt)
        # allowed transform T2 (CART_FPGA_SPEC.md 15.1, row B4): what the window serves. The chip's FIFO-B first chunk
        # (up to 0x78 words from its SDRAM; no refills without EXTI 12) against
        # ours' workspace at SPTR for the GO's length: same bytes
        fb = chip.take_fifo_b()
        if fb and mbx == 'B':
            gos = [v_ for k_, v_ in board if k_ == 'GO']
            if not gos:
                rig.fail('t2_no_go', ev, '%d chip FIFO-B bytes, no GO on ours' % len(fb))
            else:
                n = min(len(fb), 2 * gos[-1])
                sptr = struct.unpack_from('<6I', nr[1])[2]
                new.q_mem(sptr, n)
                new.flush()
                ours = new.read(n)
                rig.t2_events += 1
                rig.t2_bytes += n
                if ours != fb[:n]:
                    k = next(i for i in range(n) if ours[i] != fb[i])
                    rig.fail('t2_bytes', ev, 'SPTR %06X, %d bytes, first difference at +%d: chip %s ours %s' % (
                        sptr, n, k, fb[k:k + 8].hex(), ours[k:k + 8].hex()))
        elif fb:
            rig.fail('t2_fifo_b_outside_a_post', ev, len(fb))
        # cart-RAM words a command fragment that works as the chip's writes (only when the post was
        # accepted: no refusal bit 9 / 10)
        centry = sc['commands'].get('%02X' % idx, {})
        accepted = not any(o_ == 6 and (v_ & 0x0600) for o_, v_ in regs)
        if spr_mode and accepted:
            sbad = rig.spr.chip_check(spr_mode, pre_spr, chip.ram(0, 0x2000), nr[0])   # strict: no allowance (stage 2)
            rig.counted['sprite words compared with the chip after an accepted %s (update s1-sprval)' % spr_mode.upper()] += 1
            if sbad:
                rig.fail('sprite_chip', ev, sbad[:14])
        # stage 3 (test build S3a, row B53): the zoom page $0200-$09FF against the chip after every mailbox-B post
        if mbx == 'B':
            cz, nz = chip.ram(0x200, 0x800), nr[0][0x200:0xA00]
            rig.counted['zoom page $0200-$09FF compared with the chip after a mailbox-B post (stage 3, B53)'] += 1
            if cz != nz:
                zk = next(i_ for i_ in range(0x800) if cz[i_] != nz[i_]) & ~1
                rig.fail('zoom_chip', ev, '$%04X chip %s new %s (%d bytes differ)' % (
                    0x200 + zk, cz[zk:zk + 2].hex(), nz[zk:zk + 2].hex(), sum(1 for i_ in range(0x800) if cz[i_] != nz[i_])))
        wrote = accepted and (centry.get('ram_chip_when') != 'job_queued' or any(o_ == 6 and (v_ & 0x4000) for o_, v_ in regs))
        for w_ in centry.get('ram_chip_words', []):
            wa = h16(w_)
            if mbx == 'B' and wrote and chip.ram(wa) != nr[0][wa:wa + 2]:
                rig.fail('ram_chip', ev, '$%04X chip %s new %s' % (wa, chip.ram(wa).hex(), nr[0][wa:wa + 2].hex()))
        # the final026-referenced fields (mailbox-B posts only: 0.2.6 never served mailbox A); off in the tail (B28)
        if rf and mbx == 'B':
            compare_ref(rig, ev, idx, nr, rr, centry)
            if idx in SAVE_CMDS:
                bram_check(rig, new, ref, ev)
        elif ref and mbx == 'B' and rig.in_unit:
            rig.counted['AF unit: final026 not posted (synthetic tables, chip and ours only)'] += 1
        elif ref and mbx == 'B':
            rig.counted['tail: final026 fields not compared (the chip refusal forms 0.2.6 acted on: B28)'] += 1
        if mbx == 'B':
            if idx == 0x04 and accepted:
                rig.after84 = True
            if idx == 0x27 and accepted:
                rig.mw_send = True
            if idx == 0x06:
                rig.c6_window = True
            if idx == 0x08:
                rig.c6_window = False
            if idx == 0x2E:
                rig.frame_open = True
            if idx == 0x2F:
                rig.frame_open = False
        if tag:
            rig.synth_rows.append({'frame': f, 'post': '%04X' % word, 'mbx': mbx, 'what': tag, 'chip': fmt_w(cs, True)[:12],
                                   'new': fmt_w(regs)[:12], 'board': ['%s=%X' % bv for bv in board]})
        rig.events += 1
        post_no += 1
        if mbx == 'B':
            rig.posts += 1
        else:
            rig.ticks += 1
        return nr

    def af_unit():
        """--af-unit: the chip's frame end against ours on synthetic tables (see the module text)"""
        import random
        rnd = random.Random(0x1F1C)
        rig.in_unit = True
        sat0, nsat = 0x0B00, 144
        cases = [(n, m) for n in range(0, 141) for m in (0, 1, 2, 3) if m != 3 or n <= 0x50]
        k = 0
        uf = end_frame
        for n, m in cases:
            for rep_ in (0, 1):                     # the same table on both parities (each AE adds 1)
                k += 1
                if k % 97 == 0:
                    do_post(0xAF02, None, 'B', uf, None)                # an AF no AE opened (D38): the finish only
                    rig.unit_cases['AF without an open frame'] += 1
                if k % 53 == 0:
                    do_post(0xB000 if k % 2 else 0xF000, None, 'B', uf, None)   # B0 / F0: the parity counts them too
                    rig.unit_cases['B0 / F0'] += 1
                tab = bytes(rnd.getrandbits(8) for _ in range(8 * nsat))
                words = {0x1F10: rnd.randrange(0x240, 0x2000), 0x1F16: rnd.randrange(0, 100), 0x1F18: n, 0x1F1C: 0}
                chip.m.ramdp[sat0:sat0 + 8 * nsat] = tab                # the 68000's word writes (MCU halfword A = word A)
                new.q_w(sat0, tab)
                for w_, v_ in words.items():
                    chip.w68(w_, struct.pack('<H', v_))
                    new.q_w(w_, struct.pack('<H', v_))
                do_post(0xAE00, None, 'B', uf, None)
                nr = do_post(0xAF00 | m, None, 'B', uf, None)
                rig.unit_cases['AF%02X %s' % (m, 'count <= 80' if n <= 0x50 else 'count 81-94' if n <= 94 else
                                               'count 95-128' if n <= 0x80 else 'count 129-140')] += 1
                c = chip.ram(0, 0x2000)
                bad = []
                for e_ in range(nsat):
                    x_ = sat0 + 8 * e_
                    if c[x_:x_ + 8] != nr[0][x_:x_ + 8]:
                        bad.append('SAT %d chip %s new %s' % (e_, c[x_:x_ + 8].hex(), nr[0][x_:x_ + 8].hex()))
                if c[0x1F20:0x1F90] != nr[0][0x1F20:0x1F90]:
                    bad.append('stash chip %s new %s' % (c[0x1F20:0x1F40].hex(), nr[0][0x1F20:0x1F40].hex()))
                if bad:
                    rig.fail('af_unit', {'ev': 'af_unit', 'cmd': 'AF', 'frame': uf, 'count': n, 'mode': m}, bad[:8])
        rig.in_unit = False
        rig.counted['AF unit: cases (count 0-140 x modes 0-2, 3 up to 80, two parities each)'] += 2 * len(cases)

    stop_frame = None
    save_done = False
    while o + 20 <= len(d):
        t, ln, f = struct.unpack_from('<HHI', d, o)
        po = o + 20
        o_rec = o
        o = po + ln
        if t == 1:
            if f > a.to:
                stop_frame = f
                break
            if a.save_at >= 0 and f >= a.save_at and not save_done and f > seg_from:
                save_ckpt(a, chip, rig, o_rec, post_no, synth_done, f)
                save_done = True
                stop_frame = f
                break
            frame = f
            if f >= 1:
                chip.frame()
                cw = chip.take()
                if cw:
                    compare_event(rig, {'ev': 'frame', 'cmd': 'frame time', 'frame': f}, None, cw, [], None, None, chip.stored(), a.opt)
                fb = chip.take_fifo_b()
                if fb:
                    rig.fail('t2_fifo_b_outside_a_post', {'ev': 'frame', 'cmd': 'frame time', 'frame': f}, len(fb))
                rig.frames += 1
            if a.synth_at >= 0 and f >= a.synth_at and not synth_done:
                for word, sets, what, mbx in synth_list:
                    do_post(word, synth_args(new, sets) if mbx == 'B' else None, mbx, f, what)
                synth_done = True
            if sdram_next is not None and f >= sdram_next and ref:
                sdram_check(rig, new, ref, {'ev': 'checkpoint', 'cmd': 'sdram', 'frame': f})
                bram_check(rig, new, ref, {'ev': 'checkpoint', 'cmd': 'bram', 'frame': f})
                sdram_next += a.sdram_every
            continue
        if t == 3:
            ad, wd, v = struct.unpack_from('<HHH', d, po)
            if ad >= 0x2000:
                continue
            if wd == 2:
                w = ad & ~1
                data = struct.pack('<H', v)
                if w == 0x1FEC:
                    do_post(v, None, 'A', frame)
                    continue
                chip.w68(w, data)
                for h in hosts:
                    h.q_w(w, data)
                if w >= 0x1FE0:
                    rig.counted['68000 word write to $%04X (not $1FEC)' % w] += 1
            else:
                mo = ad ^ 1
                chip.w68(mo, bytes([v & 0xFF]))
                for h in hosts:
                    h.q_w(mo, bytes([v & 0xFF]))
                rig.counted['68000 byte write'] += 1
            continue
        if t == 2:
            wv = struct.unpack_from('<18H', d, po)
            do_post(wv[0], struct.pack('<16H', *wv[2:18]), 'B', frame)
            if chip.m.fault is not None:
                break
    end_frame = frame
    if ref and not save_done:
        sdram_check(rig, new, ref, {'ev': 'checkpoint', 'cmd': 'end', 'frame': end_frame})
        bram_check(rig, new, ref, {'ev': 'checkpoint', 'cmd': 'end', 'frame': end_frame})
    if not save_done and a.af_unit:
        af_unit()
    if not save_done and a.tail:
        rig.in_tail = True
        for word, sets, what, mbx in synth.SYNTH_S1_TAIL:
            if mbx == 'EXTI13':
                chip.exti13()
                cw = chip.take()
                new.q_x(); new.flush()
                log = new.r_x()
                cs = chip_filter(cw, sc['_tf'], None, rig.transforms)
                if cs or log:
                    rig.fail('exti13', {'ev': 'exti13', 'cmd': 'EXTI 13', 'frame': end_frame}, {'chip': fmt_w(cs, True), 'new': len(log)})
                rig.synth_rows.append({'frame': end_frame, 'post': 'EXTI13', 'what': what, 'chip': fmt_w(cs, True), 'new': []})
                continue
            do_post(word, synth_args(new, sets) if mbx == 'B' else None, mbx, end_frame, what)
    for h in hosts:
        h.close()
    reasons = []
    if not rig.events:
        reasons.append('no event compared')
    if rig.fails:
        reasons.append('%d differences outside the scope file: %s' % (sum(rig.fails.values()), dict(rig.fails)))
    if a.synth_at >= 0 and not synth_done and not save_done:
        reasons.append('the synthetic list was not posted (--synth-at past --to or the capture)')
    if a.tail and not save_done and not any(r['post'] == 'EXTI13' for r in rig.synth_rows):
        reasons.append('the tail was not posted')
    if a.af_unit and not save_done and not rig.unit_cases:
        reasons.append('the AF unit did not run')
    summ = {'label': a.label, 'capture': a.capture, 'capture_md5': md5f(a.capture), 'rom_md5': hashlib.md5(rom).hexdigest(),
            'new': {'exe': a.new, 'md5': md5f(a.new)}, 'ref': {'exe': a.ref, 'md5': md5f(a.ref)} if a.ref else None,
            'chip': chip.md5s, 'scope_md5': md5f(a.scope), 'opt': '%08X' % a.opt, 'frame_time': not a.no_frame_time,
            'from_frame': seg_from, 'to_frame': end_frame, 'stopped_for_checkpoint': save_done,
            'events': rig.events, 'posts': rig.posts, 'ticks': rig.ticks, 'frames': rig.frames, 'chip_not_done': rig.notdone,
            'stream_starts': rig.starts, 'gos': rig.gos, 'fe4_checks': rig.fe4_checks,
            't2_fifo_b_events': rig.t2_events, 't2_fifo_b_bytes': rig.t2_bytes,
            'per_cmd': dict(sorted(rig.per_cmd.items())), 'transforms_by_id': dict(rig.transforms),
            'transforms_by_row': rows_of(sc, rig.transforms), 'allowed': dict(rig.allowed), 'counted': dict(rig.counted),
            'failures_by_kind': dict(rig.fails), 'failures_by_cmd': dict(rig.per_cmd_fail), 'chip_byte_writes': chip.bytew,
            'synth_rows': rig.synth_rows, 'af_unit_cases': dict(rig.unit_cases), 'wall_s': round(time.time() - t0), 'plant': a.plant,
            'result': 'FAIL' if reasons else 'PASS', 'fail_reasons': reasons}
    capf.close()
    with open(os.path.join(a.out, 'mismatch.jsonl'), 'w') as fm:
        for r in rig.first:
            fm.write(json.dumps(r) + '\n')
    json.dump(summ, open(os.path.join(a.out, 'summary.json'), 'w'), indent=1)
    print(json.dumps({k: summ[k] for k in ('label', 'from_frame', 'to_frame', 'events', 'posts', 'ticks', 'transforms_by_row',
                                          'allowed', 'failures_by_kind', 'wall_s')}))
    print('RESULT: PASS' if not reasons else 'RESULT: FAIL: ' + ' | '.join(reasons))
    return 1 if reasons else 0


# ------------------------------------------------------------------ the visible $1FE4 for every Console setting
def consoles(a, sc):
    t0 = time.time()
    rom = open(a.rom, 'rb').read()
    rows = []
    reasons = []
    for model in CONSOLE_MODELS:
        for mw in (0, MW_MASK):
            for jap in (0, 1 << 25):
                opt = model | mw | jap
                new, ref = New('new', a.new), HostSide('ref', a.ref)
                for h, w in ((new, opt), (ref, opt & 0xFFFFFF)):     # 0.2.6 knows bits 0-18 only
                    h.q_load(rom)
                    h.q_opt(w)
                    h.q_reset()
                    h.flush()
                for h in (new, ref):
                    h.k(); h.k(); h.k()
                capf, d = records(a.capture)
                o = 0
                n_posts = n_bad = 0
                first_go = False
                at_read = None
                bad = []
                while o + 20 <= len(d):
                    t, ln, f = struct.unpack_from('<HHI', d, o)
                    po = o + 20
                    o = po + ln
                    if f > a.to:
                        break
                    if t == 3:
                        ad, wd, v = struct.unpack_from('<HHH', d, po)
                        if ad >= 0x2000:
                            continue
                        off, data = (ad & ~1, struct.pack('<H', v)) if wd == 2 else (ad ^ 1, bytes([v & 0xFF]))
                        for h in (new, ref):
                            h.q_w(off, data)
                        continue
                    if t != 2:
                        continue
                    wv = struct.unpack_from('<18H', d, po)
                    args = struct.pack('<16H', *wv[2:18])
                    for h in (new, ref):
                        h.q_w(0x1E10, args)
                        h.q_post(wv[0])
                    new.q_x(); new.q_v()
                    new.flush(); ref.flush()
                    nr, rr = new.r_post(), ref.r_post()
                    log, (view, fl) = new.r_x(), new.r_v()
                    n_posts += 1
                    if any((e >> 24) == 0x41 for e in log):
                        first_go = True
                    busy = 1 if (fl['guard'] or not fl['valid']) else 0
                    want = (busy << 2) | (opt & MODEL_MASK)
                    v68 = struct.unpack_from('<H', nr[0], 0x1FE4)[0]
                    vr = struct.unpack_from('<H', rr[0], 0x1FE4)[0]
                    if v68 != view[2] or v68 != want or (v68 & ~4) != (vr & ~4) or \
                            (not first_go and v68 != (0x0004 | (opt & MODEL_MASK))):
                        n_bad += 1
                        if len(bad) < 5:
                            bad.append({'post': '%04X' % wv[0], 'frame': f, 'new': '%04X' % v68, 'ref': '%04X' % vr, 'want': '%04X' % want})
                    if (wv[0] >> 8) == 0xC6 and at_read is None:
                        at_read = {'post': '%04X' % wv[0], 'frame': f, 'new': '%04X' % v68, 'ref': '%04X' % vr,
                                   'expect': '%04X' % (0x0004 | (opt & MODEL_MASK))}
                capf.close()
                new.close()
                ref.close()
                ok = n_posts > 0 and n_bad == 0 and at_read is not None and at_read['new'] == at_read['expect'] == at_read['ref']
                rows.append({'opt': '%08X' % opt, 'model_bits': '%03X' % model, 'megawire': bool(mw), 'jap': bool(jap),
                             'posts': n_posts, 'differences': n_bad, 'after_c6': at_read, 'examples': bad, 'ok': ok})
                if not ok:
                    reasons.append('opt %08X: %d posts differ (%s)' % (opt, n_bad, bad[:2]))
                print('%s opt %08X posts %d bad %d after C6 %s' % ('OK ' if ok else 'BAD', opt, n_posts, n_bad, at_read))
    summ = {'mode': 'consoles', 'capture': a.capture, 'to': a.to, 'new': {'exe': a.new, 'md5': md5f(a.new)},
            'ref': {'exe': a.ref, 'md5': md5f(a.ref)}, 'rows': rows, 'wall_s': round(time.time() - t0),
            'result': 'FAIL' if reasons else 'PASS', 'fail_reasons': reasons}
    json.dump(summ, open(os.path.join(a.out, 'summary.json'), 'w'), indent=1)
    print('RESULT: PASS' if not reasons else 'RESULT: FAIL: ' + ' | '.join(reasons))
    return 1 if reasons else 0


def merge(a):
    """segments carry the rig's counters on (a resumed run restores them), so the last segment's summary is the
    whole corpus; here: every segment passed, each starts where the one before stopped, the last one finished"""
    segs = []
    reasons = []
    prev_stop = None
    last = None
    for dd in a.merge:
        s = json.load(open(os.path.join(dd, 'summary.json')))
        segs.append({'dir': dd, 'from': s['from_frame'], 'to': s['to_frame'], 'result': s['result'],
                     'events_so_far': s['events'], 'checkpoint_stop': s['stopped_for_checkpoint'], 'wall_s': s['wall_s']})
        if s['result'] != 'PASS':
            reasons.append('%s: %s' % (dd, s['fail_reasons']))
        if prev_stop is not None and s['from_frame'] != prev_stop:
            reasons.append('%s starts at frame %s, the previous segment stopped at %s' % (dd, s['from_frame'], prev_stop))
        if prev_stop is None and last is not None:
            reasons.append('%s follows a segment that did not stop at a checkpoint' % dd)
        prev_stop = s['to_frame'] + 1 if s['stopped_for_checkpoint'] else None
        last = s
    if last is None or last['stopped_for_checkpoint']:
        reasons.append('the last segment stopped at a checkpoint: the corpus is not finished')
    keys = ('events', 'posts', 'ticks', 'frames', 'chip_not_done', 'stream_starts', 'gos', 'fe4_checks', 'per_cmd',
            'transforms_by_id', 'transforms_by_row', 'allowed', 'counted', 'failures_by_kind', 'failures_by_cmd', 'synth_rows')
    summ = {'segments': segs, 'totals': {k: last.get(k) for k in keys} if last else {},
            'wall_s': sum(x['wall_s'] for x in segs), 'result': 'FAIL' if reasons else 'PASS', 'fail_reasons': reasons}
    json.dump(summ, open(os.path.join(a.out, 'summary.json'), 'w'), indent=1)
    print(json.dumps({k: summ['totals'].get(k) for k in ('events', 'posts', 'ticks', 'frames', 'chip_not_done')}))
    print('RESULT: PASS' if not reasons else 'RESULT: FAIL: ' + ' | '.join(reasons))
    return 1 if reasons else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--capture')
    ap.add_argument('--rom')
    ap.add_argument('--new')
    ap.add_argument('--ref')
    ap.add_argument('--scope', default=os.path.join(HERE, 's1_scope.json'))
    ap.add_argument('--runner', help='the cartaudio runner directory (default: paths.local.json equiv.chip_runner)')
    ap.add_argument('--to', type=int, default=10 ** 9)
    ap.add_argument('--opt', type=lambda s: int(s, 0), default=0,
                    help='the option word (Console model, MegaWire bits 16-18, region); replay a capture with the MegaWire '
                         'setting it was recorded with (the attract capture: 0x70000)')
    ap.add_argument('--test', action='store_true', help='TEST builds: BRAM $900-$FFF and $1000-$1FFF under A1')
    ap.add_argument('--no-frame-time', action='store_true')
    ap.add_argument('--synth-at', type=int, default=-1)
    ap.add_argument('--tail', action='store_true')
    ap.add_argument('--af-unit', action='store_true', help='after the last frame: the chip\'s frame end on synthetic tables')
    ap.add_argument('--save-at', type=int, default=-1)
    ap.add_argument('--resume')
    ap.add_argument('--sdram-every', type=int, default=1000)
    ap.add_argument('--consoles', action='store_true')
    ap.add_argument('--merge', nargs='+')
    ap.add_argument('--plant')
    ap.add_argument('--label', default='')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.merge:
        return merge(a)
    for what, p in (('--capture', a.capture), ('--rom', a.rom), ('--new', a.new)):
        if not p or not os.path.exists(p):
            print('RESULT: setup error: %s %s missing' % (what, p))
            return 2
    if a.ref and not os.path.exists(a.ref):
        print('RESULT: setup error: --ref %s missing' % a.ref)
        return 2
    sc = load_scope(a.scope)
    if a.consoles:
        if not a.ref:
            print('RESULT: setup error: --consoles needs --ref')
            return 2
        return consoles(a, sc)
    runner = a.runner
    if not runner:
        lp = os.path.join(ROOT, 'paths.local.json')
        runner = ((json.load(open(lp)) if os.path.exists(lp) else {}).get('equiv') or {}).get('chip_runner')
    if not runner or not os.path.exists(os.path.join(runner, 'cartmcu.py')):
        print('RESULT: setup error: no chip runner (paths.local.json equiv.chip_runner or --runner)')
        return 2
    return lockstep(a, sc, runner)


if __name__ == '__main__':
    sys.exit(main())
