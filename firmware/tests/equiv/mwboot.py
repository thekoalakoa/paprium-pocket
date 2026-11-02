#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""mwboot.py - stage 3 (the MegaWire port, test build S3b): the MegaWire SRAM image on RV32, on the board model of test
build 5 (tests/equiv/rtlmodel.py). Test builds 5 and S3b are firmware builds B Jam tested on his hardware.

The rig of tests/equiv/c6count.py (interrupts at random instruction boundaries, the solo capture's boot posts, the
game's C6 loop), with the SRAM image in SRAM (the build's own img/sram.bin) as the core's boot stub leaves it: from
0.3.0 the image comes inside the firmware file (docs/FAFRIUM.md), the stub copies it into SRAM before the firmware
starts and the APF data loader writes nothing there, so XLINK LOADED reads 0 and LOST 0. Each boot is one case:
  valid                      the build's image, LOADED 0, LOST 0                          -> check state 1, lock set
  no file                    SRAM zero                                                    -> 2 (magic)
  bad magic / bad version    one header word changed                                      -> 2
  another build              the link id changed                                          -> 3
  length odd / past the end / over 64 KB   the length word changed                         -> 4
  the loader's counts        LOADED = the image's halfwords (as an old SRAM data slot left it), or LOST 1: the check
                             no longer reads them (state 5 is no longer given)          -> 1
  damaged                    one byte of the hot part changed, the header's CRC not       -> 6
  hot end wrong              the header's hot end (word 5) changed                        -> 4
  cold part damaged          one byte of the cold part changed: the hot part's check passes (1); the cold part's own
                             check (s3_sram_cold_ok, right after it) refuses it (2) and the screen's code is never
                             called
Every case: the image check runs in the thread after the 68000's release (core/mw/mw_boot.c): no instruction is
fetched from SRAM before the release, and the check has ended within --check-ms of it (the game's first post comes
169 frames after its start, measured in the solo capture); the game's boot count byte = 94 (the cart's, allow-list
row B34, docs/ALLOWLIST.md) and the hold record; the MegaWire status $1FE6 bits 0-2 = 0 after C6 ("MODEM : NONE": no
module); no store into the image area once the lock is set.
The valid case: the code ran from SRAM (instructions fetched there), the init ran inside C6's set-up and the task
ticked after it (task state 2), TEST's counters (the init's one not-built mark, the server's request line); the
information block $1B20-$1B87 equals the chip's (the cart-engine runner's boot snapshot after two ticks) when the runner
is configured; the gates of the MegaWire posts (core/dispatch/disp.c) against the chip's, post by post: before the
init (the MegaWire byte 0: refusal 6) and after it (the arguments: the command word's bit 14; the length; the
send-pending gate; last an accepted A858, the screen request the game's Options pad code posts with no module), the
reply word $1FEA, the refusal bit ($1FE6 bit 9), the MegaWire $1FE6 bits and the task block bytes the gates and bodies
write (MW+1, +0x10, +0x122, +0x123); the accepted A858 starts the screen loop in the thread (core/mw/mw_screen.c),
not in L1: no not-built mark any more; on the RV32 board model at its prices the 68000 is held and released within
--scr-tol-ms of the chip's own waits (10 + 64 ms to the hold, 300 ms more to the release: 0x0802266E, 0x080226A0,
0x080226DC), and the cart program's text is unpacked and the lines written after the release.
The refused cases: no instruction fetched from SRAM, no lock (test build 5's MegaWire, with the option Off).
--opt-on: every case once more with the MegaWire option On (0x70000), at its first phase: the same results (On runs
our MegaWire port too; a missing or refused image gives test build 5's Off).
--negative: four planted faults must each fail their check: the hot part's CRC compare forced to pass (the damaged
image then runs), the lock bit lost after the check, the chip's information block one byte off, and the A858 screen's
hold 10 ms late.
usage: python -I -B tests/equiv/mwboot.py --build build/s1/pocket88k/s5test [--phase P ...] [--opt-on] [--negative]
Exit 0 = every check passed (and every planted fault was caught), 1 = a failure, 2 = setup error.
The board and the game's loop are models (rtlmodel, c6count); the chip side is the cart's own program in the
cart-engine runner (our test harness outside this tree); the count 94 is the value measured on the cart."""
import argparse, json, os, random, struct, sys, time
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import rtlmodel   # noqa: E402
from rtlmodel import Board, Stop, FRAME_CYCLES, SRAM, RAMDP   # noqa: E402
from c6count import boot_records, VS_LAG, POLL0, POLL, POLL_FE6, COUNT_START, CART_COUNT, TIMEOUT   # noqa: E402

HDR = 0x40                      # the image header (board/pocket/s3_sram.c)
LOCK = 1 << 16                  # XCFG bit 16, the image lock (MCU_INTERFACE.md 3.7)
IMG_AREA = 0x10000
MWB = 0x37                      # the $1FE6 bits only MegaWire code writes
MW_OFFS = (1, 0x10, 0x122, 0x123)   # the task block bytes the gates and bodies write
CHIP_MW, CHIP_RAMDP, CHIP_TIM7_RET = 0x20006D70, 0x68060000, 0x08015414
SCR_HOLD_MS, SCR_REL_MS = 74.0, 374.0   # the chip's screen loop: 10 + 64 waits of 96,000 SysTicks at 96 MHz to the
                                        # hold ($1FE4 bit 14 cleared), then 300 more to the release
PHASES8 = ('capture', '1', '20000', '36850', '37000', '600000', '895350', '895450')


def packet(t, n, fill):
    """an E7 packet as the game stores it at $1E10 (type << 8, the length, n bytes of our own filler)"""
    b = bytes((fill + i) & 0xFF for i in range(n)) + (b'\0' if n & 1 else b'')
    return (t << 8, n) + tuple((b[i] << 8) | b[i + 1] for i in range(0, len(b), 2))


PKT = packet(0x24, 13, 1)
# the posts: the command word's bit 14 says the post has arguments (the dispatcher's sl); a refusal sets $1FE6 bit 9
# (mailbox B), compared with the MegaWire bits after each post (REFB)
REFB = 0x0200
# before the init (the MegaWire byte 0): each refused (6)
PRE = (('A480 before the init', 0xA480, ()), ('A600 before the init', 0xA600, ()), ('A900 before the init', 0xA900, ()),
       ('E7 before the init', 0xE700, PKT), ('A800 before the init', 0xA800, ()), ('A858 before the init', 0xA858, ()))
# after it: the argument, length and send-pending gates (7 / 7 / 6) and the bodies of A4 / A6 / A9 / E7 (accepted)
POST = (('A4 with arguments', 0xE480, (1,)), ('A480', 0xA480, ()), ('A6 with arguments', 0xE600, (1,)),
        ('A600', 0xA600, ()), ('A9 with arguments', 0xE900, (1,)), ('A900', 0xA900, ()),
        ('E7 with no arguments', 0xA700, ()), ('E7 length 0xFC', 0xE700, packet(0x24, 0xFC, 1)[:2]),
        ('E7', 0xE700, PKT), ('E7 while one is pending', 0xE700, PKT), ('A900 (clears it)', 0xA900, ()),
        ('A8 low byte not 58', 0xA800, ()), ('A858 with arguments', 0xE858, (1,)),
        ('AA low byte not 58', 0xAA00, ()), ('AA58 with arguments', 0xEA58, (1,)),
        ('A858 (accepted, last: the cart then runs its screen loop)', 0xA858, ()))


def image_cases(img):
    """(name, SRAM bytes, LOADED, LOST, the check's state)"""
    n = len(img)
    magic, ver, length, crc, lid = struct.unpack_from('<5I', img, 0)
    if length != n:
        raise SystemExit('SETUP ERROR: the image header says %d B, the file is %d B' % (length, n))

    def word(off, v):
        b = bytearray(img)
        struct.pack_into('<I', b, off, v)
        return bytes(b)
    dam = bytearray(img)
    dam[HDR + 5] ^= 0x01
    hot = struct.unpack_from('<I', img, 20)[0]
    cold = bytearray(img)
    cold[hot + 9] ^= 0x10
    # From 0.3.0 the boot stub places the image (the firmware file), so the loader's count LOADED is 0 in every case
    # but the one that sets it on purpose: the check must not read it.
    return [('valid', img, 0, 0, 1),
            ('no file', bytes(n), 0, 0, 2),
            ('bad magic', word(0, magic ^ 1), 0, 0, 2),
            ('bad version', word(4, ver ^ 0x100), 0, 0, 2),
            ('another build (link id)', word(16, lid ^ 4), 0, 0, 3),
            ('length odd', word(8, n - 2), 0, 0, 4),
            ('length past the end', word(8, n + 4), 0, 0, 4),
            ('length over 64 KB', word(8, IMG_AREA + 4), 0, 0, 4),
            ('LOADED as a data slot left it (not read)', img, n >> 1, 0, 1),
            ('a lost loader word (LOST, not read)', img, 0, 1, 1),
            ('hot end wrong', word(20, hot + 4), 0, 0, 4),
            ('cold part damaged', bytes(cold), 0, 0, 1),
            ('damaged (CRC)', bytes(dam), 0, 0, 6)]


class Chip:
    """the cart's chip in the cart-engine runner: its information block and its answers to the MegaWire posts"""

    def __init__(self, runner):
        sys.path.insert(0, runner)
        import cartmcu
        from host68k import Host
        from unicorn import UC_HOOK_CODE
        self.cartmcu, self.Host, self.HOOK = cartmcu, Host, UC_HOOK_CODE
        self.runner = runner

    def _machine(self, snap):
        m = self.cartmcu.Machine(verbose=0)
        ticks = [0]
        m.mu.hook_add(self.HOOK, lambda uc, a, s, u: ticks.__setitem__(0, ticks[0] + 1),
                      begin=CHIP_TIM7_RET, end=CHIP_TIM7_RET + 1)
        if snap:
            m.load_state(os.path.join(self.runner, 'snap', 'boot.pkl'))
            m.verbose = 0
            h = self.Host.__new__(self.Host)
            h.m = m; h.verbose = 0; h.log = []
        else:
            m.run(seconds=0.3)
            h = self.Host(m, verbose=0)
        return m, h, ticks

    def info_block(self):
        m, h, ticks = self._machine(True)
        h.start_vblank(59.922743)
        n = ticks[0]
        m.run(seconds=1.0, until=lambda mm: ticks[0] >= n + 2)
        return struct.unpack('<52H', bytes(m.mu.mem_read(CHIP_RAMDP + 0x1B20, 0x68)))

    def gates(self, pre):
        """pre: the posts after 3 x 810E from reset (no init yet); else after the boot snapshot, right after a tick"""
        m, h, ticks = self._machine(not pre)
        if pre:
            for _ in range(3):
                h.post(0x810E)
            seq = PRE
        else:
            h.start_vblank(59.922743)
            n = ticks[0]
            m.run(seconds=1.0, until=lambda mm: ticks[0] >= n + 1)
            seq = POST
        out, t0 = [], ticks[0]
        for name, word, args in seq:
            h.post(word, args)
            blk = bytes(m.mu.mem_read(CHIP_MW, 0x124))
            out.append((name, m.reg68(0x1FEA), m.reg68(0x1FE6) & (MWB | REFB), tuple(blk[o] for o in MW_OFFS)))
        return out, ticks[0] - t0


def run(build, rom, recs, seed, phase, sram, loaded, lost, opt=0, plant=None, gates=False):
    """one boot to the game's C6 exit (c6count.run's protocol) with the SRAM image; returns a dict"""
    rnd = random.Random(seed)
    b = Board(build, rom, opt=opt, seed=seed, sram_fill=sram, sram_loaded=loaded, xl_lost=lost)
    sy = b.sym
    img_end = len(sram)
    st = {'fetch': 0, 'lock_stores': 0, 'ticks': 0, 'scr': 0}
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn import riscv_const as RC

    def fetch(uc, a, s, u):
        st['fetch'] += 1
    b.uc.hook_add(UC_HOOK_CODE, fetch, begin=SRAM, end=SRAM + IMG_AREA - 1)

    def store(uc, acc, a, s, v, u):
        if b.xcfg & LOCK:
            st['lock_stores'] += 1
    b.uc.hook_add(UC_HOOK_MEM_WRITE, store, begin=SRAM, end=SRAM + IMG_AREA - 1)
    tick_sym = 'mw_tick_a' if 'mw_tick_a' in sy else 'mw_tick'     # the thread runs the task in parts: (a) starts one
    if tick_sym in sy:
        b.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: st.__setitem__('ticks', st['ticks'] + 1),
                      begin=sy[tick_sym][0], end=sy[tick_sym][0])
    if 'mw_screen_step' in sy:
        b.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: st.__setitem__('scr', st['scr'] + 1),
                      begin=sy['mw_screen_step'][0], end=sy['mw_screen_step'][0])
    if plant == 'scr' and 'brd_md_hold' in sy:  # planted: the A858 screen's hold 10 ms late (its timing check)
        late = [False]

        def late_hold(uc, a, s, u):
            if not late[0] and not (b.ctrl & 1) and uc.reg_read(RC.UC_RISCV_REG_A0) == 1:
                late[0] = True
                b.time += int(FRAME_CYCLES * 59.922743 / 100)
        b.uc.hook_add(UC_HOOK_CODE, late_hold, begin=sy['brd_md_hold'][0], end=sy['brd_md_hold'][0])
    if plant == 'crc':                          # planted: boot_crc32_words, called by the image check, answers it
        ret = sy['boot_crc32_words'][0]
        chk0, chkn = sy['brd_sram_image_ok']

        def crc_ok(uc, a, s, u):
            ra = uc.reg_read(RC.UC_RISCV_REG_RA)
            if not chk0 <= ra < chk0 + max(chkn, 4):
                return                          # another caller (the boot cache): untouched
            uc.reg_write(RC.UC_RISCV_REG_A0, struct.unpack_from('<I', sram, 12)[0])
            uc.reg_write(RC.UC_RISCV_REG_PC, ra)
        b.uc.hook_add(UC_HOOK_CODE, crc_ok, begin=ret, end=ret)
    fine = [0]

    def until(t, cond=None):
        while b.time < t or (cond is not None and not cond()):
            b.take()
            b.step(rnd.randint(1, 4) if b.time < fine[0] else rnd.randint(1, 48))
            if b.time - t > 300_000_000:
                raise Stop()

    def post68(word, args):
        until(b.time, lambda: not (b.r68(0x0A) & 0x8000))
        if args:
            b.w68_ram(0x1E10, struct.pack('<%dH' % len(args), *args))
        b.w68_post_b(word)
        until(b.time, lambda: not (b.r68(0x0A) & 0x8000))
        mw = b.uc.mem_read(sy['mw_ram'][0], 0x124) if 'mw_ram' in sy else bytes(0x124)
        return b.r68(0x0A), b.r68(0x06) & (MWB | REFB), tuple(mw[o] for o in MW_OFFS)

    if not b.run_to('brd_boot', 200_000):
        raise Stop()
    n = 0
    while b.ctrl & 1:                               # until the 68000's release
        b.take()
        b.step(400)
        n += 1
        if n > 300000:
            raise Stop()
    fetch_boot, t_rel = st['fetch'], b.time     # the release: no SRAM instruction before it
    if 's3_mw_checked' in sy:                   # the thread's first work: the image check (a valid image: to the RAM
        until(b.time, lambda: b.rd8('s3_mw_checked') and    # clear's end, s3_mw_on)
              (b.rd32('s3_sram_state') not in (0, 1) or b.rd8('s3_mw_on')))
    check_ms = round((b.time - t_rel) / (FRAME_CYCLES * 59.922743) * 1e3, 2)
    if plant == 'lock':                         # planted: the lock bit lost after the check
        b.xcfg &= ~LOCK
    res = dict(state=b.rd32('s3_sram_state'), mw_on=b.rd8('s3_mw_on'), lock=bool(b.xcfg & LOCK),
               fetch_boot=fetch_boot, check_ms=check_ms)
    posts = [r for r in recs if r[0] == 'B']
    t6 = posts[-1][3]
    ph = t6 % FRAME_CYCLES if phase == 'capture' else int(phase)
    base = b.time + 2_000_000 - posts[0][3]
    vb0 = base + t6 - ph
    first_vs = vb0 + VS_LAG - FRAME_CYCLES * ((vb0 + VS_LAG - b.time) // FRAME_CYCLES)
    if first_vs <= b.time:
        first_vs += FRAME_CYCLES
    b.vs_align(first_vs)
    pre = []
    for r in recs:
        if r[0] == 'W':
            b.w68_ram(r[1], r[2])
            continue
        _, word, args, tc = r
        if word == 0xC600 and gates:                # the gates with the MegaWire byte 0, just before C600
            until(base + tc - 400_000)
            pre = [(nm_,) + post68(w_, a_) for nm_, w_, a_ in PRE]
        until(base + tc, lambda: not (b.r68(0x0A) & 0x8000))
        b.w68_ram(0x1E10, args)
        b.w68_post_b(word)
    tw = b.time
    fine[0] = tw + POLL0 + VS_LAG + 20000
    vb_next = lambda t: vb0 + FRAME_CYCLES * ((t - vb0) // FRAME_CYCLES + 1)
    count, t = COUNT_START, tw + POLL0
    while True:
        until(t)
        busy = bool(b.r68(0x0A) & 0x8000)
        if not busy:
            until(t + POLL_FE6)
            busy = bool(b.r68(0x06) & 0x4000)
        if not busy:
            break
        count += 1
        if count > TIMEOUT:
            break
        t = vb_next(t) + POLL
    rec = b.rd32('c6_hold_test') if 'c6_hold_test' in sy else None
    res.update(count=count, byte=count & 0xFF, phase=ph,
               hold=None if rec is None else dict(case=rec & 0xFF, end=(rec >> 8) & 0xFF, edges=rec >> 16),
               ticks_c6=st['ticks'])
    if res['mw_on']:                                # three more task ticks (the idle state after the init's first), as
        k0 = st['ticks']                            # the chip's block is read two ticks after its snapshot
        until(b.time, lambda: st['ticks'] >= k0 + 3)
        until(b.time + 60_000)
    res.update(fe6_mw=b.r68(0x06) & 7, fetch=st['fetch'], lock_stores=st['lock_stores'], ticks=st['ticks'],
               violations=b.violations[:3], pre=pre)
    if 'mw_ram' in sy:
        mw = b.uc.mem_read(sy['mw_ram'][0], 4)
        res['task_state'] = mw[2]
    if 'mw_stats' in sy:
        res['stats'] = list(struct.unpack('<3I', b.uc.mem_read(sy['mw_stats'][0], 12)))
    res['info'] = struct.unpack('<52H', bytes(b.uc.mem_read(RAMDP + 0x1B20, 0x68)))
    if gates:                                       # right after a task tick, as on the chip
        k = st['ticks']
        until(b.time, lambda: st['ticks'] > k)
        until(b.time + 60_000)
        k = st['ticks']
        if 'mw_stats' in sy:
            res['stats_gate0'] = list(struct.unpack('<3I', b.uc.mem_read(sy['mw_stats'][0], 12)))
        res['post'] = [(nm_,) + post68(w_, a_) for nm_, w_, a_ in POST]
        res['post_ticks'] = st['ticks'] - k
        if 'mw_stats' in sy:                        # TEST: the accepted A858 adds no not-built mark (its screen loop
            res['stats_gate1'] = list(struct.unpack('<3I', b.uc.mem_read(sy['mw_stats'][0], 12)))   # is the thread's)
    if res['mw_on'] and 's3_sram_cold' in sy:   # the A858 screen's first steps: the cold part's own check first
        if not gates:
            post68(0xA858, ())
        until(b.time + 1_200_000)
        res['cold'] = b.rd8('s3_sram_cold')
        res['scr_steps'] = st['scr']
        res['scr_state'] = b.uc.mem_read(sy['mw_ram'][0] + 0x10, 1)[0] if 'mw_ram' in sy else None
        if gates and res['cold'] == 1 and 'mw_txt' in sy:   # the screen on RV32 at the board's prices: the hold, the
            t_post = b.time - 1_200_000                     # release, then the cart program's text unpacked whole
            hold = []                                       # and the lines written (modelled timing, measured here)
            last = [b.ctrl & 1]

            def held():
                if (b.ctrl & 1) != last[0]:
                    last[0] = b.ctrl & 1
                    hold.append((last[0], round((b.time - t_post) / (FRAME_CYCLES * 59.922743) * 1e3, 1)))
                st_ = b.uc.mem_read(sy['mw_txt'][0] + 8, 1)[0]
                return st_ >= 2 and b.uc.mem_read(sy['mw_ram'][0] + 0x10, 1)[0] in (2, 3)
            until(b.time, lambda: held() or b.time - t_post > 200_000_000)
            k0 = b.time
            until(b.time + 1_200_000)
            res['scr_hold'] = hold
            res['scr_text'] = (b.uc.mem_read(sy['mw_txt'][0] + 8, 1)[0], round((k0 - t_post) / (FRAME_CYCLES * 59.922743) * 1e3, 1))
            res['scr_state2'] = b.uc.mem_read(sy['mw_ram'][0] + 0x10, 1)[0]
            lines = bytes(b.uc.mem_read(RAMDP + 0x1E10, 0x80))
            res['scr_lines_set'] = sum(1 for i in range(0, 0x80, 2) if lines[i + 1] == 0x84)
    return res


def inputs(a):
    loc = json.load(open(os.path.join(ROOT, 'paths.local.json'))) if os.path.exists(os.path.join(ROOT, 'paths.local.json')) else {}
    eq = loc.get('equiv', {})
    cap, rom = a.capture or eq.get('capture_solo'), a.rom or eq.get('rom')
    if not cap or not rom or not os.path.exists(cap) or not os.path.exists(rom):
        print('SETUP ERROR: --capture / --rom (or paths.local.json "equiv" capture_solo / rom)')
        sys.exit(2)
    runner = a.runner or eq.get('chip_runner')
    return cap, open(rom, 'rb').read(), runner if runner and os.path.isdir(runner) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default=os.path.join(ROOT, 'build', 's1', 'pocket88k', 's5test'))
    ap.add_argument('--capture')
    ap.add_argument('--rom')
    ap.add_argument('--runner')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--phase', action='append', help="the valid case's C600 phases (c6count.py); default 'capture'")
    ap.add_argument('--opt-on', action='store_true', help='every case also with the MegaWire option On')
    ap.add_argument('--negative', action='store_true')
    ap.add_argument('--check-ms', type=float, default=50.0, help='the image check ends within this after the release')
    ap.add_argument('--scr-tol-ms', type=float, default=2.0, help="the A858 hold / release against the chip's waits")
    ap.add_argument('--json')
    a = ap.parse_args()
    cap, rom, runner = inputs(a)
    imgp = os.path.join(a.build, 'img', 'sram.bin')
    if not os.path.isfile(imgp):
        print('SETUP ERROR: no SRAM image %s (a build without the MegaWire port?)' % imgp)
        sys.exit(2)
    img = open(imgp, 'rb').read()
    recs = boot_records(cap)
    t0 = time.time()
    chip = Chip(runner) if runner else None
    test = 'release' not in os.path.basename(os.path.normpath(a.build))
    ref_info = chip.info_block() if chip else None
    # the version word $1B32 (MW+0x162: 0 if ROM word 0x10012 is 0xFFFF, else ROM word 0x1000A, 0x08021890) comes from
    # each side's own ROM: when the rig's ROM and the runner's differ there, $1B32 is checked against our ROM instead
    rv16 = lambda r, a: (r[a] << 8) | r[a + 1]
    ver_ours = 0 if rv16(rom, 0x10012) == 0xFFFF else rv16(rom, 0x1000A)
    same_ver = True
    if chip:
        crom = open(chip.cartmcu.ROM_PATH, 'rb').read()
        same_ver = (0 if rv16(crom, 0x10012) == 0xFFFF else rv16(crom, 0x1000A)) == ver_ours
    ref_post = chip.gates(False) if chip else None
    ref_pre = chip.gates(True) if chip else None
    ok, out = True, []

    def check(case, opt, r):
        name, _sram, _ld, _lost, want = case
        bad = []
        if r.get('violations'):
            bad.append('model violations %s' % r['violations'])
        if r['byte'] != CART_COUNT:
            bad.append('count byte %s (the cart: %d)' % (r['byte'], CART_COUNT))
        if r['state'] != want:
            bad.append('image check state %d (want %d)' % (r['state'], want))
        if r['fe6_mw'] != 0:
            bad.append('$1FE6 bits 0-2 = %d after C6 (no module: 0)' % r['fe6_mw'])
        if r['lock_stores']:
            bad.append('%d stores into the locked image area' % r['lock_stores'])
        if r['fetch_boot']:
            bad.append("%d SRAM instructions before the 68000's release (the check comes after it)" % r['fetch_boot'])
        if r['check_ms'] > a.check_ms:
            bad.append('the image check ended %.2f ms after the release (at most %.1f)' % (r['check_ms'], a.check_ms))
        if want == 1 and 'cold' in r:           # the cold part: checked at the screen's first step
            if name.startswith('cold') and (r['cold'] != 2 or r['scr_steps']):
                bad.append('cold part damaged: its check %s, screen steps %d (want 2, none)' % (r['cold'], r['scr_steps']))
            if not name.startswith('cold') and (r['cold'] != 1 or not r['scr_steps'] or r['scr_state'] != 1):
                bad.append('the A858 screen: cold check %s, screen steps %d, state %s (want 1, some, 1)' % (
                    r['cold'], r['scr_steps'], r['scr_state']))
            if 'scr_text' in r and (r['scr_text'][0] != 2 or r['scr_state2'] not in (2, 3) or
                                    [h[0] for h in r['scr_hold']] != [1, 0] or r['scr_lines_set'] < 30):
                bad.append('the A858 screen on RV32: hold %s, text %s, state %s, %d line words written (want the hold '
                           'and the release, text 2, state 2 or 3, the lines)' % (r['scr_hold'], r['scr_text'],
                                                                               r['scr_state2'], r['scr_lines_set']))
            elif 'scr_hold' in r:               # the hold and the release at the chip's waits (modelled board timing)
                for (k, t_), want_ms in zip(r['scr_hold'], (SCR_HOLD_MS, SCR_REL_MS)):
                    if abs(t_ - want_ms) > a.scr_tol_ms:
                        bad.append("the A858 screen on RV32: the 68000 %s at +%.1f ms (the chip's waits: +%.1f, "
                                   'tolerance %.1f)' % ('held' if k else 'released', t_, want_ms, a.scr_tol_ms))
        if want == 1:
            if not (r['mw_on'] and r['lock']):
                bad.append('mw_on %d lock %s' % (r['mw_on'], r['lock']))
            if not r['fetch'] or r.get('task_state') != 2 or not r['ticks']:
                bad.append('the port did not run: SRAM fetches %d, task state %s, ticks %d' % (
                    r['fetch'], r.get('task_state'), r['ticks']))
            if test and 'stats' in r and (r['stats'][1] != 1 or r['stats'][2] != 0x08020EFC or r['stats'][0] < 2):
                bad.append('TEST counters %s (ticks, not-built marks, last: one mark, the init\'s 0x08020EFC)' % r['stats'])
            if ref_info is not None:
                dif = [('$%04X' % (0x1B20 + 2 * i), '%04X/%04X' % (ref_info[i], r['info'][i]))
                       for i in range(52) if ref_info[i] != r['info'][i] and (same_ver or i != 9)]
                if dif:
                    bad.append('$1B20 block differs from the chip (chip/ours) %s' % dif[:6])
                if not same_ver and r['info'][9] != ver_ours:
                    bad.append('$1B32 %04X, the version word of our ROM %04X' % (r['info'][9], ver_ours))
            if 'post' in r and ref_post is not None:
                cp, cticks = ref_post
                if cticks or r['post_ticks']:
                    bad.append('a task tick inside the gate sequence (chip %d, ours %d): rerun' % (cticks, r['post_ticks']))
                for c_, o_ in zip(cp, r['post']):
                    if c_ != o_:
                        bad.append('post %s: chip %s ours %s' % (c_[0], c_[1:], o_[1:]))
            if test and 'stats_gate1' in r and r['stats_gate1'][1] != r['stats_gate0'][1]:
                bad.append('TEST counters after the gate posts %s (before %s): the accepted A858 must add no '
                           'not-built mark (its screen loop runs in the thread)' % (r['stats_gate1'], r['stats_gate0']))
            if 'pre' in r and r['pre'] and ref_pre is not None:
                for c_, o_ in zip(ref_pre[0], r['pre']):
                    if c_[:3] != o_[:3]:
                        bad.append('post %s: chip %s ours %s' % (c_[0], c_[1:3], o_[1:3]))
        else:
            if r['mw_on'] or r['lock'] or r['fetch']:
                bad.append('a refused image: mw_on %d lock %s SRAM fetches %d' % (r['mw_on'], r['lock'], r['fetch']))
        return bad

    cases = image_cases(img)
    if a.negative:
        valid, dam = cases[0], cases[-1]
        plants = (('crc', dam, 'the CRC compare forced to pass: the damaged image runs'),
                  ('lock', valid, 'the lock bit lost after the check'),
                  ('info', valid, 'the chip\'s information block one byte off'),
                  ('scr', valid, 'the A858 screen\'s hold 10 ms late on RV32'))
        for plant, case, what in plants:
            if plant == 'info' and ref_info is None:
                print('SKIP planted %s (no chip runner)' % plant)
                continue
            saved = ref_info
            if plant == 'info':
                ref_info = tuple(ref_info[:5]) + ((ref_info[5] ^ 1),) + tuple(ref_info[6:])
            try:
                r = run(a.build, rom, recs, a.seed, 'capture', case[1], case[2], case[3],
                        plant=plant if plant != 'info' else None, gates=plant == 'scr')
                bad = check(case, 0, r)
            except Stop:
                bad = ['the model stopped']
            ref_info = saved
            key = {'crc': 'image check state', 'lock': 'lock False', 'info': '$1B20 block',
                   'scr': 'the A858 screen on RV32: the 68000 held'}[plant]
            hit = [x for x in bad if key in x]       # caught by the check named for it
            caught = bool(hit)
            ok &= caught
            print('%-4s planted %-5s (%s): %s' % ('PASS' if caught else 'FAIL', plant, what,
                                                 ('caught: ' + hit[0]) if caught else 'NOT CAUGHT %s' % bad), flush=True)
        print('RESULT: %s (%.0f s)' % ('PASS' if ok else 'FAIL', time.time() - t0))
        sys.exit(0 if ok else 1)
    runs = []
    for case in cases:
        phases = (a.phase or ['capture']) if case[0] == 'valid' else ['capture']
        for ph in phases:
            runs.append((case, 0, ph, case[0] == 'valid' and ph == phases[0]))
        if a.opt_on:                            # the option On: once more, at the first phase
            runs.append((case, 0x70000, phases[0], case[0] == 'valid'))
    for case, opt, ph, gates in runs:
        try:
            r = run(a.build, rom, recs, a.seed, ph, case[1], case[2], case[3], opt=opt, gates=gates)
            bad = check(case, opt, r)
        except Stop:
            r, bad = {}, ['the model stopped']
        good = not bad
        ok &= good
        r2 = {k: v for k, v in r.items() if k not in ('info',)}
        out.append(dict(case=case[0], opt=opt, phase=ph, res=r2, bad=bad))
        print('%-4s %s %-24s opt %05X phase %-7s state %s (check +%s ms) mw_on %s lock %s count byte %s hold %s; SRAM '
              'fetches %s, ticks %s (%s at the C6 exit), task %s%s%s%s' % (
                  'PASS' if good else 'FAIL', os.path.basename(a.build), case[0], opt, ph, r.get('state'), r.get('check_ms'),
                  r.get('mw_on'), r.get('lock'), r.get('byte'), r.get('hold'), r.get('fetch'), r.get('ticks'),
                  r.get('ticks_c6'), r.get('task_state'), (', %d gate posts compared' % len(r.get('post', [])) if gates else ''),
                  (', screen hold %s text %s' % (r['scr_hold'], r.get('scr_text')) if 'scr_hold' in r else ''),
                               ('' if good else ' | ' + ' | '.join(bad))), flush=True)
    if not chip:
        print('SKIP the chip comparisons (the information block, the gates): no chip runner')
    if a.json:
        json.dump(out, open(a.json, 'w'), indent=1)
    print('RESULT: %s (%d boots, %.0f s)' % ('PASS' if ok else 'FAIL', len(runs), time.time() - t0))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
