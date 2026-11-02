#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""rvboard.py - rig (b) of stage 0 (the tree's first step: the 0.2.6 firmware moved in): an RV32 (32-bit RISC-V)
runner of the Pocket cart MCU board on Unicorn (the CPU emulator library), running a paprium-fw BLOCK-RAM IMAGE (mcu.txt + mcu_ext.txt + wram_hi.txt + wram_lo.txt, the files
the bitstream is updated with), driven by a capture recorded in GPGX (the Genesis Plus GX emulator), compared post by
post with the HOST build of the same tree on the same posts.

Board model (pocket72k; as read in board/pocket/include/pocket_map.h, paprium.h and neorv32.h; modelled where noted):
  IROM  0x00000000  72 KB = mcu.txt (rom0 32 KB) + mcu_ext.txt (40 KB). Nothing else is mapped there.
  WRAM  0x80000000  48 KB = wram_hi/wram_lo (even/odd bytes). No 256 KB alias: an access past 48 KB FAULTS (strict).
  FPGAIO 0x01000000 MMIO: slot 0 ctrl (written bits kept; status inputs md_rst_status/buddy bits read 0), 1 time
         (ms counter, modelled from the capture timeline T = frame x 896,040
         + cy MCLK; frozen at 0 in call mode, as on the host), 2 sdram_ptr,
         3 vol_sfx, 4 vol_bgm, 5 stream_cnt (reads 0: no 68000 stream reads modelled), 6 mailbox-latch clear (W1C bit 0).
  RAMDP 0x02000000  8 KB dual-port cart RAM (plain memory; the 68000 side writes it between MCU segments). A 68000
         write of $1FEA sets the MAILBOX LATCH (paprium_cart mbx_irq -> mext_irq_i, MEI 11), cleared by slot 6.
  SDRAM 0x03000000  16 MB, stores hooked (256-byte granules per post).   FLASH 0x04000000  the 8 MB ROM, byte-swapped.
  BRAM  0x05000000  64 KB.  SFX 0x06000000 / MDP 0x07000000 / FIFO 0x07800000: plain memory (the album/SFX entry points
         are stubbed exactly as the host build stubs them: logged with their arguments, not executed).
  SRAM  0x08000000 256 KB, XLINK 0x0A000000: plain, every access counted (0.2.6 firmware should touch neither).
  NEORV32 IO 0xFFFFFF80.. MMIO: GPIO_INPUT (read-only option word), GPIO out, MTIME/MTIMECMP (modelled at 53.693175
         MHz from the same timeline), UART CT (TX never busy) / DATA (bytes collected), SYSINFO_CLK; crt0's zeroing
         writes to read-only registers are ignored.
  Interrupts: mie/mstatus are read after every segment; with the default options the firmware never enables one
         (measured per run). Injection is not modelled (a run that enables one is flagged).

Modes:
  call   crt0 from the reset vector up to main (the image initialises its own .data/.bss), then ppm_reset() and
         ppm_cmd_handler() per post with SP = __crt0_stack_begin: the host harness's semantics, on the real image.
  board  reset vector -> crt0 -> main -> neorv32_uart_setup -> ppm_start -> ppm_reset -> the polling loop. The
         68000 side is applied while the MCU sits at the loop's poll point (the jal to ppm_cmd_handler); a post runs
         one loop iteration (the handler, then sfx_player_update, the Boom Box VU update, tick, the buddy check);
         every FRAME record runs one idle iteration at the frame's
         time. The MCU takes no time (fast mode, a modelling choice).

Per post, RV32 vs host (same variant): RAMDP 8 KB; FPGAIO (ctrl, sdram_ptr, vol_sfx, vol_bgm, stream_cnt; time
too in call mode); printf TEXT (RV32: the arguments of each neorv32_uart_printf call, formatted with C printf rules
like the host's vsnprintf; the raw UART bytes are counted apart, their %x/'\r' format differs by design);
audio entry log; SDRAM: union of host-changed and RV32-written granules, contents compared (after every non-AD post;
an AD's changes are compared cumulatively at the frame's AF, as in equivA.py); BRAM $000-$FFF.
Checkpoints: SDRAM 8 MB, flash, BRAM 64 KB. Board mode adds classified main-loop effects (VU words $1B98-$1BFF).

Exit status (the rig fails loudly): 0 = PASS; 1 = FAIL: the image files disagree with the ELF load image, a boot or
run fault, any per-post or checkpoint difference outside the allowed classes above (A5 in board mode, the C6 elapsed
time printf in board mode), an interrupt enabled (the model does not inject interrupts, so such a run proves nothing),
an SRAM / XLINK / unexpected IO access, a write into wram_upper (pocket72k: unused at stage 0), the stack pattern
overwritten to the bottom of the stack region, or no post replayed; 2 = bad arguments.
'--informational irq|odd|wram_upper' counts that kind without failing. The last line printed is 'RESULT: PASS' or
'RESULT: FAIL: <reasons>'; summary.json carries 'result' and 'fail_reasons'.

usage: python -I -B rvboard.py OUTDIR --build POCKET_BUILD_DIR --host EXE --capture CAP --rom ROM
                               [--mode call|board] [--to F] [--opt W] [--full-every N]
                               [--informational irq|odd|wram_upper]

Stage-1 board mode (--mode s1): the stage-1 image (FW_S1, our new firmware) (build/s1/pocket72k/test or release) on the
stage-1 board (tests/equiv/rtlmodel.py: MCU interface v1.0 with CAUSE, MSI, TIMER, the register file with its busy /
guard / window rules, the menu bit, the SFX FIFOs), interrupts
taken at random instruction boundaries (seeded), against the stage-1
HOST build of the same variant (build/s1/host/s1_ours_<variant>.exe, the fake board of board/host) on the same capture,
post by post: each 68000 post ($1FEA, or a $1FEC write: the 9494) is made on both, and both run it to the end (finished,
jobs and board work drained: the host's fast mode). Compared after every B post: cart RAM $0000-$1FDF; the 68000 view of
the register page $1FE0-$1FFF (busy, model, status, mailboxes); hold, window, SPTR, VOL_SFX, VOL_BGM; the album / SFX
entry calls with their arguments (stubbed on both sides, as the host stubs them); the SDRAM granules written and their
bytes; the battery save $000-$FFF; and the register-write sequence (every MCU write of $1FE4-$1FF6, SPTR and GO, in
order) since the last compare. Two models of one frozen interface, two builds of one source: no allow category.
usage: python -I -B rvboard.py OUTDIR --mode s1 --build build/s1/pocket72k/test --host build/s1/host/s1_ours_test.exe
                               --capture CAP --rom ROM [--to F] [--opt W] [--seed S]
"""
import argparse, bisect, hashlib, json, mmap, os, re, struct, sys, time, collections
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hostside import HostSide, runs, SDR_SPAN, OFF_FLASH, BRAM_N   # noqa: E402
from unicorn import Uc, UcError, UC_ARCH_RISCV, UC_MODE_RISCV32, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, \
    UC_HOOK_MEM_READ, UC_HOOK_MEM_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED   # noqa: E402
from unicorn import riscv_const as RC   # noqa: E402

LAYOUTS = {   # irom = bytes of the image (rom0 + ext); wram = image bytes; wram_map = what the runner maps
    'pocket72k': dict(irom=0x12000, wram=0xC000, wram_map=0xC000, sent=0x11FF0,
                      # pre-filled before reset (a power-on image has zeros there; garbage = a retained-WRAM reset):
                      # wram_sched (.bss_noclear, never cleared by crt0) random; wram_upper and the stack a pattern,
                      # checked at the end (upper untouched; stack high-water mark)
                      fill={'sched': (0x2AC0, 0x2C00), 'upper': (0x6C00, 0xAC00), 'stack': (0xAC00, 0xC000)}),
    # the shipped 0.2.6 layout, as a control: 32 KB WRAM decoded over 256 KB on the 0.2.6 RTL (crt0 stack 0x8003FFFC);
    # the runner maps 256 KB of plain memory instead of aliasing it (a modelling choice, as our earlier rigs made it)
    'legacy54k': dict(irom=0xD800, wram=0x8000, wram_map=0x40000, sent=0xDFF0),
}
L = dict(LAYOUTS['pocket72k'])
ROM0_BYTES = 0x8000
WRAM = 0x80000000
FPGIO, RAMDP, SDR, FLA, BRM, SFX, MDP, FIFO = 0x1000000, 0x2000000, 0x3000000, 0x4000000, 0x5000000, 0x6000000, \
    0x7000000, 0x7800000
SRAM, XLINK = 0x8000000, 0xA000000
IOPAGE = 0xFFFFF000
F_MCU = 53_693_175                      # NEORV32 clock = the MD master clock (PPM_BUSY_PULSE_LOOPS note, mame.h)
FRAME_MCLK = 896_040                    # 262 lines x 3,420 MCLK; capture 'cy' = MCLK since the record frame's start
                                        # (line 224), as measured in the stage-0 census
VU0, VU1 = 0x1B98, 0x1C00               # Boom Box VU words, written by the main loop (paprium.c PPM_VU_BASE)
AUDIO = {'sfx_play': 1, 'sfx_loop': 2, 'sfx_stop': 3, 'mdp_init': 10, 'mdp_play': 11, 'mdp_play_once': 12,
         'mdp_stop': 13, 'mdp_set_vol': 14}
FMT = re.compile(r'%([-+ #0]*)(\d*)(?:\.(\d+))?(hh|h|ll|l|z|j|t)?([diouxXcsp%])')


def read_txt_words(p):
    """mcu.txt / mcu_ext.txt: 8-hex-digit words, 4 bytes each in address order"""
    out = bytearray()
    for tok in open(p).read().split():
        out += bytes.fromhex(tok)
    return bytes(out)


def read_txt_bytes(p):
    return bytes(int(t, 16) for t in open(p).read().split())


class Image:
    def __init__(self, d):
        self.dir = d
        img = os.path.join(d, 'img')
        rom0 = read_txt_words(os.path.join(img, 'mcu.txt'))
        ext = read_txt_words(os.path.join(img, 'mcu_ext.txt'))
        assert len(rom0) == ROM0_BYTES and len(ext) == L['irom'] - ROM0_BYTES, (len(rom0), len(ext))
        self.irom = rom0 + ext
        hi = read_txt_bytes(os.path.join(img, 'wram_hi.txt'))
        lo = read_txt_bytes(os.path.join(img, 'wram_lo.txt'))
        assert len(hi) == len(lo) == L['wram'] // 2
        w = bytearray(L['wram'])
        w[0::2], w[1::2] = hi, lo
        self.wram = bytes(w)
        # cross-check against the ELF load image the image files were made from
        rb = open(os.path.join(img, 'rom.bin'), 'rb').read()
        self.check = {'irom_eq_rom.bin': self.irom[:len(rb)] == rb and not any(self.irom[len(rb):]),
                      'rom.bin_len': len(rb)}
        wc = open(os.path.join(img, 'wcode.bin'), 'rb').read()
        self.check['wram_window_eq_wcode.bin'] = self.wram[0x2C00:0x2C00 + len(wc)] == wc
        self.check['wram_zero_outside_window'] = not any(self.wram[:0x2C00]) and not any(self.wram[0x2C00 + len(wc):])
        self.check['md5'] = {'irom': hashlib.md5(self.irom).hexdigest(), 'wram': hashlib.md5(self.wram).hexdigest()}
        self.sym = {}
        self.fn = []
        for ln in open(os.path.join(d, 'main.nm')):
            p = ln.split()
            if len(p) >= 3:
                a, name = int(p[0], 16), p[-1]
                self.sym[name] = a
                if p[-2] in 'tT':
                    self.fn.append((a, name))
        self.fn.sort()
        self.fa = [a for a, n in self.fn]
        # the poll point: the jal to ppm_cmd_handler inside ppm_start
        loop = None
        inside = False
        for ln in open(os.path.join(d, 'main.dis')):
            if re.match(r'^[0-9a-f]+ <ppm_start>:', ln):
                inside = True
                continue
            if inside and re.match(r'^[0-9a-f]+ <', ln):
                break
            m = re.match(r'^\s*([0-9a-f]+):\s+\S+\s+jal\s+\S+\s+<ppm_cmd_handler>', ln)
            if inside and m:
                loop = int(m.group(1), 16)
        assert loop is not None, 'poll point not found'
        self.loop_jal, self.loop_ret = loop, loop + 4
        assert not any(self.irom[L['sent']:L['sent'] + 4])

    def func(self, a):
        i = bisect.bisect_right(self.fa, a) - 1
        return self.fn[i][1] if i >= 0 else '?'


def cfmt(fmt, args, rdstr):
    """C printf (as vsnprintf) for the conversions the firmware uses; args = 32-bit words in order"""
    out = []
    pos = 0
    k = 0
    for m in FMT.finditer(fmt):
        out.append(fmt[pos:m.start()])
        pos = m.end()
        flags, width, prec, _, conv = m.groups()
        if conv == '%':
            out.append('%')
            continue
        v = args[k] if k < len(args) else 0
        k += 1
        if conv in 'di':
            v = v - (1 << 32) if v & 0x80000000 else v
            conv = 'd'
        elif conv == 'u':
            conv = 'd'
        elif conv == 's':
            v = rdstr(v)
        elif conv == 'c':
            v = chr(v & 0xFF)
        elif conv == 'p':
            conv, flags = 'x', '#'
        spec = '%' + flags + width + (('.' + prec) if prec is not None else '') + conv
        out.append(spec % v)
    out.append(fmt[pos:])
    return ''.join(out)


class Board:
    def __init__(self, img, rom, opt, mode):
        self.img, self.mode, self.opt = img, mode, opt
        uc = self.uc = Uc(UC_ARCH_RISCV, UC_MODE_RISCV32)
        uc.mem_map(0, (L['irom'] + 0xFFF) & ~0xFFF)
        uc.mem_write(0, img.irom)
        uc.mem_map(WRAM, L['wram_map'])
        uc.mem_write(WRAM, img.wram)
        self.fill = L.get('fill')
        if self.fill:
            import random
            rng = random.Random(0x030E0)
            lo, hi = self.fill['sched']
            uc.mem_write(WRAM + lo, bytes(rng.getrandbits(8) for _ in range(hi - lo)))
            for k, pat in (('upper', 0x5A), ('stack', 0xA5)):
                lo, hi = self.fill[k]
                uc.mem_write(WRAM + lo, bytes([pat]) * (hi - lo))
        for base, size in ((RAMDP, 0x10000), (SDR, 0x1000000), (FLA, 0x1000000), (BRM, 0x10000), (SFX, 0x10000),
                           (MDP, 0x100000), (FIFO, 0x10000), (SRAM, 0x40000), (XLINK, 0x10000)):
            uc.mem_map(base, size)
        sw = bytearray(len(rom))
        sw[0::2] = rom[1::2]
        sw[1::2] = rom[0::2]
        uc.mem_write(FLA, bytes(sw[:0x1000000]))
        # FPGAIO and NEORV32 IO as MMIO
        self.fio = [0] * 16
        self.mmio = collections.Counter()    # MMIO coverage: reads/writes per FPGAIO slot and IO register
        uc.mmio_map(FPGIO, 0x1000, self._fio_r, None, self._fio_w, None)
        self.io = {}
        uc.mmio_map(IOPAGE, 0x1000, self._io_r, None, self._io_w, None)
        self.t = 0.0                      # board time, seconds (modelled; frozen at 0 in call mode)
        self.latch = 0
        self.latch_sets = self.latch_clears = 0
        self.uart = bytearray()
        self.uart_total = 0
        self.pf = []                      # formatted printf text of the current post
        self.au = bytearray()
        self.gran = set()
        self.gran_outside = 0
        self.in_post = False
        self.odd = collections.Counter()  # SRAM/XLINK accesses, unexpected IO
        self.fault = None
        self.irq_seen = collections.Counter()
        uc.hook_add(UC_HOOK_MEM_WRITE, self._sdr_w, begin=SDR, end=SDR + 0xFFFFFF)
        uc.hook_add(UC_HOOK_MEM_READ, self._odd, begin=SRAM, end=SRAM + 0x3FFFF, user_data='sram_r')
        uc.hook_add(UC_HOOK_MEM_WRITE, self._odd, begin=SRAM, end=SRAM + 0x3FFFF, user_data='sram_w')
        uc.hook_add(UC_HOOK_MEM_READ, self._odd, begin=XLINK, end=XLINK + 0xFFFF, user_data='xlink_r')
        uc.hook_add(UC_HOOK_MEM_WRITE, self._odd, begin=XLINK, end=XLINK + 0xFFFF, user_data='xlink_w')
        uc.hook_add(UC_HOOK_MEM_UNMAPPED | UC_HOOK_MEM_FETCH_UNMAPPED, self._unmapped)
        for name, kind in AUDIO.items():
            if name in img.sym:
                uc.hook_add(UC_HOOK_CODE, self._audio, begin=img.sym[name], end=img.sym[name], user_data=kind)
        self.has_printf = 'neorv32_uart_printf' in img.sym
        if self.has_printf:
            a = img.sym['neorv32_uart_printf']
            uc.hook_add(UC_HOOK_CODE, self._printf, begin=a, end=a)
        self.sp0 = img.sym['__crt0_stack_begin'] & ~3

    # ---- MMIO
    def _fio_r(self, uc, off, size, ud):
        s = off >> 2
        self.mmio['fpgaio_r%d' % s] += 1
        if s == 0:
            v = self.fio[0] & ~0x8          # md_rst_status (no MD reset pressed); buddy/stub inputs 0
        elif s == 1:
            v = int(self.t * 1000) & 0xFFFFFFFF
        elif s == 5:
            v = 0
        else:
            v = self.fio[s]
        sh = (off & 3) * 8
        return (v >> sh) & ((1 << (8 * size)) - 1)

    def _fio_w(self, uc, off, size, value, ud):
        s = off >> 2
        self.mmio['fpgaio_w%d' % s] += 1
        sh = (off & 3) * 8
        m = ((1 << (8 * size)) - 1) << sh
        nv = (self.fio[s] & ~m) | ((value << sh) & m)
        if s == 6:
            if nv & 1:
                if self.latch:
                    self.latch_clears += 1
                self.latch = 0
            return
        if s in (1, 5):
            self.odd['fpgaio_write_ro_slot%d' % s] += 1
            return
        self.fio[s] = nv & 0xFFFFFFFF

    def _mtime(self):
        return int(self.t * F_MCU)

    def _io_r(self, uc, off, size, ud):
        a = IOPAGE + off
        w = a & ~3
        self.mmio['io_r_%02X' % (w & 0xFF)] += 1
        sh = (a & 3) * 8
        if w == 0xFFFFFF80:
            v = self.opt                                  # GPIO_INPUT
        elif w == 0xFFFFFF90:
            v = self._mtime() & 0xFFFFFFFF
        elif w == 0xFFFFFF94:
            v = self._mtime() >> 32
        elif w == 0xFFFFFFA0:
            v = self.io.get(w, 0) & ~(1 << 31)            # UART_CT: TX never busy
        elif w == 0xFFFFFFE0:
            v = F_MCU                                     # SYSINFO_CLK
        elif w >= 0xFFFFFFE0:
            v = 0
            self.odd['sysinfo_read_%08X' % w] += 1
        elif w >= 0xFFFFFF80:
            v = self.io.get(w, 0)
        else:
            self.odd['io_read_%08X' % w] += 1
            v = 0
        return (v >> sh) & ((1 << (8 * size)) - 1)

    def _io_w(self, uc, off, size, value, ud):
        a = IOPAGE + off
        w = a & ~3
        self.mmio['io_w_%02X' % (w & 0xFF)] += 1
        if w in (0xFFFFFF80, 0xFFFFFF90, 0xFFFFFF94) or w >= 0xFFFFFFE0:
            return                                        # read-only (crt0 zeroes the whole IO page)
        if w == 0xFFFFFFA4:
            if self.io.get(0xFFFFFFA0, 0) & (1 << 28):     # UART_CT_EN: a disabled UART sends nothing
                self.uart.append(value & 0xFF)
                self.uart_total += 1
            return
        if w < 0xFFFFFF80:
            self.odd['io_write_%08X' % w] += 1
        sh = (a & 3) * 8
        m = ((1 << (8 * size)) - 1) << sh
        self.io[w] = (self.io.get(w, 0) & ~m) | ((value << sh) & m)

    # ---- hooks
    def _sdr_w(self, uc, access, addr, size, value, ud):
        o = addr - SDR
        self.gran.add(o & ~0xFF)
        if (o + size - 1) & ~0xFF != o & ~0xFF:
            self.gran.add((o + size - 1) & ~0xFF)
        if not self.in_post:
            self.gran_outside += 1

    def _odd(self, uc, access, addr, size, value, ud):
        self.odd[ud] += 1

    def _unmapped(self, uc, access, addr, size, value, ud):
        pc = uc.reg_read(RC.UC_RISCV_REG_PC)
        self.fault = {'access': access, 'addr': '%08X' % addr, 'size': size, 'pc': '%08X' % pc,
                      'func': self.img.func(pc)}
        return False

    def _ret(self, uc):
        uc.reg_write(RC.UC_RISCV_REG_PC, uc.reg_read(RC.UC_RISCV_REG_RA))

    def _audio(self, uc, addr, size, kind):
        a0 = uc.reg_read(RC.UC_RISCV_REG_A0) & 0xFF
        if kind in (10, 13):
            a0 = 0
        args = struct.unpack('<3H', bytes(uc.mem_read(RAMDP + 0x1E10, 6)))
        if len(self.au) < 256 * 8:
            self.au += struct.pack('<BBHHH', kind, a0, *args)
        self._ret(uc)                                     # stubbed, as the host build stubs it

    def _rdstr(self, a):
        b = bytearray()
        while len(b) < 512:
            c = self.uc.mem_read(a + len(b), 1)[0]
            if c == 0:
                break
            b.append(c)
        return b.decode('latin-1')

    def _printf(self, uc, addr, size, ud):
        regs = [uc.reg_read(r) for r in (RC.UC_RISCV_REG_A0, RC.UC_RISCV_REG_A1, RC.UC_RISCV_REG_A2,
                                         RC.UC_RISCV_REG_A3, RC.UC_RISCV_REG_A4, RC.UC_RISCV_REG_A5,
                                         RC.UC_RISCV_REG_A6, RC.UC_RISCV_REG_A7)]
        fmt = self._rdstr(regs[0])
        args = regs[1:]
        n = sum(1 for m in FMT.finditer(fmt) if m.group(5) != '%')
        if n > 7:                                          # ilp32: the 8th vararg on is on the caller's stack
            sp = uc.reg_read(RC.UC_RISCV_REG_SP)
            args += list(struct.unpack('<%dI' % (n - 7), bytes(uc.mem_read(sp, 4 * (n - 7)))))
        self.pf.append(cfmt(fmt, args, self._rdstr))

    # ---- execution
    def run(self, begin, until, limit=200_000_000):
        # a translation block cached during an earlier segment holds no stop check for this segment's 'until':
        # drop the cached block(s) covering it, so the stop is compiled in (Unicorn 2.1.4, measured: without this
        # the second idle iteration ran through the poll point)
        self.uc.ctl_remove_cache(until, until + 4)
        try:
            self.uc.emu_start(begin, until, count=limit)
        except UcError as e:
            if self.fault is None:
                self.fault = {'error': str(e), 'pc': '%08X' % self.uc.reg_read(RC.UC_RISCV_REG_PC)}
        pc = self.uc.reg_read(RC.UC_RISCV_REG_PC)
        if self.fault is None and pc != until:
            self.fault = {'error': 'segment did not reach %08X' % until, 'pc': '%08X' % pc, 'func': self.img.func(pc)}
        mie = self.uc.reg_read(RC.UC_RISCV_REG_MIE)
        mst = self.uc.reg_read(RC.UC_RISCV_REG_MSTATUS)
        if mie:
            self.irq_seen['mie_nonzero'] += 1
        if mst & 8:
            self.irq_seen['mstatus_MIE_set'] += 1
        return self.fault is None

    def call(self, name):
        uc = self.uc
        uc.reg_write(RC.UC_RISCV_REG_SP, self.sp0)
        uc.reg_write(RC.UC_RISCV_REG_RA, L['sent'])
        return self.run(self.img.sym[name], L['sent'])

    def boot(self):
        if self.mode == 'call':
            ok = self.run(0, self.img.sym['main'])       # crt0: stack, gp, mtvec, IO reset, .bss, .data
            gp_ok = self.uc.reg_read(RC.UC_RISCV_REG_GP) == self.img.sym.get('__global_pointer$')
            ok = ok and self.call('ppm_reset')
            return ok, {'gp_set_by_crt0': gp_ok}
        ok = self.run(0, self.img.loop_jal)              # crt0 -> main -> ppm_start -> ppm_reset -> poll point
        return ok, {}

    def w68(self, off, data):
        self.uc.mem_write(RAMDP + off, data)
        if off <= 0x1FEB and off + len(data) > 0x1FEA:    # paprium_cart.sv: any 68000 write of word $1FEA
            self.latch = 1
            self.latch_sets += 1

    def post(self):
        """run one post: returns after ppm_cmd_handler has returned (the reply is in RAMDP)"""
        self.pf, self.au, self.gran = [], bytearray(), set()
        self.in_post = True
        if self.mode == 'call':
            ok = self.call('ppm_cmd_handler')
        else:
            ok = self.run(self.img.loop_jal, self.img.loop_ret)
        self.in_post = False
        return ok

    def loop_rest(self):
        """board mode: the rest of the loop iteration after the handler (sfx, VU, tick, buddy check)"""
        return self.run(self.img.loop_ret, self.img.loop_jal)

    def idle_iteration(self):
        rc = struct.unpack('<H', bytes(self.uc.mem_read(RAMDP + 0x1FEA, 2)))[0]
        self.in_post = True
        ok = self.run(self.img.loop_jal, self.img.loop_ret)
        self.in_post = False
        return ok and self.loop_rest(), rc

    def fpgaio24(self):
        return struct.pack('<6I', self.fio[0], (int(self.t * 1000) & 0xFFFFFFFF) if self.mode == 'board' else 0,
                           self.fio[2], self.fio[3], self.fio[4], 0)

    def mem(self, a, n):
        return bytes(self.uc.mem_read(a, n))

    def wram_report(self):
        if not self.fill:
            return None
        lo, hi = self.fill['upper']
        up = self.mem(WRAM + lo, hi - lo)
        lo, hi = self.fill['stack']
        st = self.mem(WRAM + lo, hi - lo)
        k = 0
        while k < len(st) and st[k] == 0xA5:
            k += 1
        return {'wram_upper_untouched': up == bytes([0x5A]) * len(up),
                'stack_high_water_bytes_below_top': hi - (lo + (k & ~3)),
                'stack_region_bytes': hi - lo, 'note': 'pattern-fill high-water mark (MEASURED in the model)'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--build', required=True, help='paprium-fw pocket build dir (img/, main.nm, main.dis)')
    ap.add_argument('--host', required=True, help='host ours_host.exe of the same variant')
    ap.add_argument('--capture', required=True)
    ap.add_argument('--rom', required=True)
    ap.add_argument('--mode', choices=('call', 'board', 's1'), default='call')
    ap.add_argument('--seed', type=int, default=1, help='s1 mode: the interrupt-phase seed')
    ap.add_argument('--layout', choices=sorted(LAYOUTS), default='pocket72k')
    ap.add_argument('--to', type=int, default=10 ** 9)
    ap.add_argument('--opt', type=lambda s: int(s, 0), default=0)
    ap.add_argument('--full-every', type=int, default=2000)
    ap.add_argument('--sdram-every-post', action='store_true',
                    help='host SDRAM diff after AD posts too (default: compared cumulatively at the next non-AD post)')
    ap.add_argument('--informational', action='append', default=[], choices=('irq', 'odd', 'wram_upper'),
                    help='count this kind without failing (default: it fails)')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.mode == 's1':
        return run_s1(a)
    t0 = time.time()
    log = open(os.path.join(a.out, 'log.txt'), 'w')

    def say(*x):
        m = ' '.join(str(y) for y in x)
        print(m, flush=True)
        log.write(m + '\n')
        log.flush()

    def early_fail(reason, **extra):
        """a run that cannot start or boot: write the summary, say why, exit 1"""
        summ = dict(provenance=prov, result='FAIL', fail_reasons=[reason], wall_s=round(time.time() - t0), **extra)
        open(os.path.join(a.out, 'summary.json'), 'w').write(json.dumps(summ, indent=1, default=str))
        say('RESULT: FAIL: ' + reason)
        return 1

    rom = open(a.rom, 'rb').read()
    L.update(LAYOUTS[a.layout])
    img = Image(a.build)
    prov = {'build': a.build, 'image_check': img.check, 'poll_point': '%08X' % img.loop_jal, 'host': a.host,
            'host_md5': hashlib.md5(open(a.host, 'rb').read()).hexdigest(), 'capture': a.capture,
            'rom_md5': hashlib.md5(rom).hexdigest(), 'mode': a.mode, 'layout': a.layout, 'opt': '%08X' % a.opt, 'to': a.to}
    say('rvboard', json.dumps(prov))
    bad_img = [k for k in ('irom_eq_rom.bin', 'wram_window_eq_wcode.bin', 'wram_zero_outside_window') if not img.check[k]]
    if bad_img:
        return early_fail('the image files disagree with the ELF load image: %s' % ', '.join(bad_img))
    bd = Board(img, rom, a.opt, a.mode)
    hs = HostSide('host', a.host)
    hs.q_load(rom); hs.q_opt(a.opt); hs.q_reset(); hs.q_shadow(); hs.flush()
    for _ in range(4):
        hs.k()
    ok, binfo = bd.boot()
    say('boot ok=%s %s uart=%r printf=%r' % (ok, binfo, bytes(bd.uart[:200]), bd.pf[:4]))
    boot_uart = bytes(bd.uart)
    bd.uart = bytearray()
    if not ok:
        say('BOOT FAULT', bd.fault)
        hs.close()
        return early_fail('boot fault: %s' % bd.fault, fault=bd.fault)
    if a.mode == 'call' and not binfo.get('gp_set_by_crt0'):
        hs.close()
        return early_fail('crt0 did not set gp to __global_pointer$', boot=binfo)
    bd.gran = set()
    fails = collections.Counter()
    allowed = collections.Counter()
    regions = collections.Counter()
    first = []
    ck = []

    def fail(kind, f, w, info):
        fails[kind] += 1
        if len(first) < 200:
            first.append({'kind': kind, 'frame': f, 'post': '%04X' % w, 'info': info})

    def checkpoint(tag):
        hs.q_mem(0, SDR_SPAN); hs.q_mem(OFF_FLASH, len(rom)); hs.q_bram(0, 0x10000); hs.q_all(); hs.flush()
        hsd, hfl, hbr = hs.read(SDR_SPAN), hs.read(len(rom)), hs.read(0x10000)
        hrd, hfp = hs.r_all()
        rsd, rbr = bd.mem(SDR, SDR_SPAN), bd.mem(BRM, 0x10000)
        rfl = bd.mem(FLA, len(rom))                   # both hold the ROM byte-swapped per word, as the cart bus does
        res = {'tag': tag, 'sdram': hsd == rsd, 'flash': hfl == rfl, 'bram64k': hbr == rbr,
               'ramdp': hrd == bd.mem(RAMDP, 0x2000)}
        if a.mode == 'board' and not res['ramdp']:
            rr = bd.mem(RAMDP, 0x2000)
            res['ramdp_outside_vu_equal'] = hrd[:VU0] == rr[:VU0] and hrd[VU1:] == rr[VU1:]
        for k in ('sdram', 'flash', 'bram64k'):
            if not res[k]:
                fail('checkpoint_' + k, -1, 0, tag)
        if not res['ramdp'] and not res.get('ramdp_outside_vu_equal'):
            fail('checkpoint_ramdp', -1, 0, tag)
        ck.append(res)
        return res

    say('checkpoint after boot:', checkpoint('after_boot'))
    capf = open(a.capture, 'rb')
    d = mmap.mmap(capf.fileno(), 0, access=mmap.ACCESS_READ)
    o, nbytes = 0, len(d)
    frame = -1
    nposts = naf = nram = 0
    nidle = 0
    redispatch = collections.Counter()
    vu_posts = vu_words = 0
    pf_posts = 0
    gran_posts = 0
    per_cmd = collections.Counter()
    bad_posts = 0
    r_gran_acc = set()
    while o + 20 <= nbytes:
        t, ln, f, vl, _z, cy, pc68 = struct.unpack_from('<HHIHHII', d, o)
        po = o + 20
        o = po + ln
        if f > a.to:
            break
        if a.mode == 'board':
            bd.t = (f * FRAME_MCLK + cy) / F_MCU
        if t == 1:
            frame = f
            if a.mode == 'board' and f > 0:
                ok, rc = bd.idle_iteration()
                nidle += 1
                if rc:
                    redispatch['%04X' % rc] += 1
                if not ok:
                    say('FAULT in idle iteration', frame, bd.fault)
                    break
            continue
        if t == 3:
            ad, wd, v = struct.unpack_from('<HHH', d, po)
            if ad >= 0x2000:
                continue
            if wd == 2:
                off, data = ad & ~1, struct.pack('<H', v & 0xFFFF)
            else:
                off, data = ad ^ 1, bytes([v & 0xFF])
            bd.w68(off, data)
            hs.q_w(off, data)
            nram += 1
            continue
        if t != 2:
            continue
        wv = struct.unpack_from('<18H', d, po)
        word = wv[0]
        cmd = word >> 8
        args = struct.pack('<16H', *wv[2:18])
        dodiff = a.sdram_every_post or cmd != 0xAD
        hs.q_w(0x1E10, args); hs.q_post(word)
        if dodiff:
            hs.q_diff()
        hs.q_bram(0, BRAM_N); hs.flush()
        bd.w68(0x1E10, args)
        bd.w68(0x1FEA, struct.pack('<H', word))
        ok = bd.post()
        r_ram = bd.mem(RAMDP, 0x2000)
        r_fp = bd.fpgaio24()
        r_txt = ''.join(bd.pf).encode('latin-1')
        r_au = bytes(bd.au)
        r_gran_acc |= bd.gran
        r_br = bd.mem(BRM, BRAM_N)
        h_ram, h_fp, h_txt, h_au = hs.r_post()
        h_gran = hs.r_diff() if dodiff else ()
        h_br = hs.read(BRAM_N)
        if dodiff:
            G = sorted(r_gran_acc | set(h_gran))
            r_gran_acc = set()
        else:
            G = []
        if G:
            rr = runs(G)
            for g, n in rr:
                hs.q_mem(g, n)
            hs.flush()
            h_sd = b''.join(hs.read(n) for g, n in rr)
            r_sd = b''.join(bd.mem(SDR + g, n) for g, n in rr)
            gran_posts += 1
        else:
            h_sd = r_sd = b''
        nposts += 1
        per_cmd[cmd] += 1
        if not ok:
            say('FAULT in post', frame, '%04X' % word, bd.fault)
            fail('fault', frame, word, bd.fault)
            break
        bad = False
        if r_ram != h_ram:
            left = []
            for i in (j for c in range(0, 0x2000, 64) if r_ram[c:c + 64] != h_ram[c:c + 64] for j in range(c, c + 64, 2)):
                if r_ram[i:i + 2] != h_ram[i:i + 2]:
                    if a.mode == 'board' and VU0 <= i < VU1:
                        vu_words += 1
                        continue
                    left.append(i)
            if a.mode == 'board' and len(left) == 0:
                vu_posts += 1
                allowed['ramdp_vu_words_main_loop'] += 1
            if left:
                bad = True
                for i in left:
                    regions['%04X' % (i & ~0xFF)] += 1
                fail('ramdp', frame, word, ['$%04X host %04X rv %04X' % (i, struct.unpack_from('<H', h_ram, i)[0],
                                                                        struct.unpack_from('<H', r_ram, i)[0]) for i in left[:10]])
        if a.mode == 'board':
            hf, rf = list(struct.unpack('<6I', h_fp)), list(struct.unpack('<6I', r_fp))
            hf[1] = rf[1] = 0                                 # the ms counter: modelled time vs the host's 0
            fp_eq = hf == rf
        else:
            fp_eq = h_fp == r_fp
        if not fp_eq:
            bad = True
            fail('fpgaio', frame, word, [struct.unpack('<6I', h_fp), struct.unpack('<6I', r_fp)])
        if r_txt != h_txt:
            if a.mode == 'board' and cmd == 0xC6:
                allowed['printf_C6_elapsed_time'] += 1
            else:
                bad = True
                fail('printf', frame, word, [h_txt[:200].decode('latin-1'), r_txt[:200].decode('latin-1')])
        if r_txt:
            pf_posts += 1
        if r_au != h_au:
            bad = True
            fail('audio', frame, word, [h_au.hex(), r_au.hex()])
        if r_sd != h_sd:
            bad = True
            fail('sdram_bytes', frame, word, [len(G), sum(1 for g, n in runs(G))])
        if r_br != h_br:
            bad = True
            fail('bram', frame, word, None)
        if bad:
            bad_posts += 1
        if a.mode == 'board':
            if not bd.loop_rest():
                say('FAULT in loop', frame, bd.fault)
                fail('fault_loop', frame, word, bd.fault)
                break
        if cmd == 0xAF:
            naf += 1
            if a.full_every and naf % a.full_every == 0:
                checkpoint('af%d_frame%d' % (naf, frame))
        if nposts % 50000 == 0:
            say('frame %d posts %d wall %.0f s fails %s' % (frame, nposts, time.time() - t0, dict(fails)))
    checkpoint('end_frame%d' % frame)
    summ = {'provenance': prov, 'boot': binfo, 'boot_uart_bytes': len(boot_uart), 'boot_uart': boot_uart.decode('latin-1')[:400],
            'frames_to': frame, 'posts': nposts, 'ramw': nram, 'afs': naf, 'idle_iterations': nidle,
            'posts_with_failure': bad_posts, 'failures_by_kind': dict(fails), 'allowed_by_category': dict(allowed),
            'ramdp_failure_words_by_page': dict(regions), 'board_vu_words_differing_total': vu_words,
            'posts_with_printf': pf_posts, 'uart_bytes_after_boot': bd.uart_total - len(boot_uart),
            'posts_with_sdram_granules': gran_posts, 'sdram_stores_outside_posts': bd.gran_outside,
            'mailbox_latch': {'sets': bd.latch_sets, 'clears': bd.latch_clears, 'pending_at_end': bd.latch},
            'interrupt_enable_seen': dict(bd.irq_seen),
            'mmio_accesses': dict(sorted(bd.mmio.items())), 'odd_accesses': dict(bd.odd),
            'idle_redispatch_of_nonzero_reg_cmd': dict(redispatch), 'checkpoints': ck, 'wram': bd.wram_report(),
            'per_cmd': {'%02X' % k: v for k, v in sorted(per_cmd.items())}, 'fault': bd.fault,
            'wall_s': round(time.time() - t0)}
    # ---- the verdict: every difference nobody allowed is a failure
    reasons = []
    if not nposts:
        reasons.append('no post replayed (capture empty or --to before the first post): nothing was compared')
    if fails:
        reasons.append('%d posts fail, failures by kind %s' % (bad_posts, dict(fails)))
    if bd.fault is not None and 'fault' not in fails and 'fault_loop' not in fails:
        reasons.append('run fault: %s' % bd.fault)
    for kind, seen, what in (('irq', bd.irq_seen, 'an interrupt was enabled (the model does not inject interrupts)'),
                             ('odd', bd.odd, 'SRAM / XLINK / unexpected IO accesses')):
        if seen:
            if kind in a.informational:
                allowed['%s (informational)' % kind] += sum(seen.values())
            else:
                reasons.append('%s: %s' % (what, dict(seen)))
    wr = summ['wram']
    if wr:
        if not wr['wram_upper_untouched']:
            if 'wram_upper' in a.informational:
                allowed['wram_upper written (informational)'] += 1
            else:
                reasons.append('the firmware wrote into wram_upper (unused at stage 0)')
        if wr['stack_high_water_bytes_below_top'] >= wr['stack_region_bytes']:
            reasons.append('the stack fill pattern is overwritten to the bottom of the stack region (possible overflow)')
    summ['allowed_by_category'] = dict(allowed)
    summ['result'] = 'FAIL' if reasons else 'PASS'
    summ['fail_reasons'] = reasons
    with open(os.path.join(a.out, 'mismatch.jsonl'), 'w') as fm:
        for x in first:
            fm.write(json.dumps(x) + '\n')
    open(os.path.join(a.out, 'summary.json'), 'w').write(json.dumps(summ, indent=1))
    say(json.dumps({k: v for k, v in summ.items() if k not in ('checkpoints', 'provenance', 'per_cmd', 'fail_reasons')},
                   indent=1))
    say('RESULT: PASS' if not reasons else 'RESULT: FAIL: ' + ' | '.join(reasons))
    hs.close()
    return 1 if reasons else 0


# ================================================================================================================
# The stage-1 board mode
# ================================================================================================================
S1_AUDIO = {'sfx_play': 1, 'sfx_loop': 2, 'sfx_stop': 3, 'sfx_d2': 3, 'sfx_player_update': 0, 'sfx_fade_tick': 0,
            'sfx_mode88': 0,
            'mdp_init': 10, 'mdp_play': 11, 'mdp_play_once': 12, 'mdp_stop': 13, 'mdp_set_vol': 14, 's1_sfx_kick': 0,
            's1_vu_kick': 0}


class S1Side:
    """the RV32 side: the image on rtlmodel.Board; posts run to their end with random interrupt phases"""

    def __init__(self, build, rom, opt, seed):
        import random
        import rtlmodel
        self.rtlmodel = rtlmodel
        self.rnd = random.Random(seed)
        self.log = []
        self.au = bytearray()
        self.gran = set()
        self.b = rtlmodel.Board(build, rom, opt=opt, listener=self.ev)
        b, u = self.b, self.b.uc
        for name, kind in S1_AUDIO.items():         # stubbed as the host stubs them (tests/s1/s1_host_album.c)
            if name in b.sym:
                a0 = b.sym[name][0]
                u.hook_add(UC_HOOK_CODE, self.audio, begin=a0, end=a0, user_data=kind)
        u.hook_add(UC_HOOK_MEM_WRITE, self.sdr_w, begin=rtlmodel.SDRAM, end=rtlmodel.SDRAM + 0x1FFFFF)
        # the thread is idle when the CPU is in its loop or its idle housekeeping (not in board work or a job)
        self.idle_pc = [(b.sym[n][0], b.sym[n][0] + b.sym[n][1]) for n in ('l3_thread', 'l3_idle')]
        self.dg = b.sym['disp_g'][0]
        self.rtl_go = []                            # v1.2: the RTL decoder's GOs of this post (compared as a list)
        # TEST's SAT snapshot: AF's close asks for it and the thread takes it; settled = taken, as the host's
        # drain takes it before the next post (on the board a frame start that comes first drops it: TEST only)
        self.snap = b.sym['snap_later'][0] if 'snap_later' in b.sym else None

    def ev(self, kind, kw):
        if kind == 'freg_w':
            self.log.append((kw['off'] << 16) | kw['v'])
        elif kind == 'sptr':
            self.log.append((0x40 << 24) | (kw['v'] & 0xFFFFFF))
        elif kind == 'go' and kw.get('rtl'):        # v1.2: the RTL decoder's GO comes at its run's end (the host's at
            r = kw['run']                           # the START): compared as a list, not in the write order
            self.rtl_go.append((0x43 << 24) | kw['n'])
            for g in range(r['base'] & ~0xFF, r['base'] + len(r['out']), 0x100):
                self.gran.add(g & 0x1FFF00)         # the decoder's writes (no CPU store: no write hook)
        elif kind == 'go':
            self.log.append((0x41 << 24) | kw['n'])
        elif kind == 'dec_base':
            self.log.append((0x42 << 24) | (kw['v'] & 0xFFFFFF))

    def audio(self, uc, addr, size, kind):
        if kind:
            a0 = uc.reg_read(RC.UC_RISCV_REG_A0) & 0xFF
            if kind in (10, 13):
                a0 = 0
            args = struct.unpack('<3H', bytes(uc.mem_read(RAMDP + 0x1E10, 6)))
            if len(self.au) < 256 * 8:
                self.au += struct.pack('<BBHHH', kind, a0, *args)
        uc.reg_write(RC.UC_RISCV_REG_PC, uc.reg_read(RC.UC_RISCV_REG_RA))

    def sdr_w(self, uc, access, addr, size, value, ud):
        o = addr - self.rtlmodel.SDRAM
        self.gran.add(o & ~0xFF)
        if (o + size - 1) & ~0xFF != o & ~0xFF:
            self.gran.add((o + size - 1) & ~0xFF)

    def boot(self):
        b = self.b
        if not b.run_to('brd_boot', 200000):
            return False
        n = 0
        while b.ctrl & 1:
            b.take()
            b.step(400)
            n += 1
            if n > 300000:
                return False
        return self.settle()

    def idle(self):
        b = self.b
        q = b.uc.mem_read(self.dg + 5, 2)
        if b.drun is not None and not b.drun['done'] and not b.drun['aborted']:
            return False                            # v1.2: the RTL decoder still running (the host's is instant)
        if self.snap is not None and any(b.uc.mem_read(self.snap, 4)):
            return False                            # the thread has not taken TEST's SAT snapshot yet
        return ((q[0] ^ q[1]) & 0xF) == 0 and not (b.cause & 0xF) and not b.msip

    def settle(self, limit=300_000_000):
        """run with interrupts until the mailboxes are finished and the thread is idle"""
        b, r = self.b, self.rnd
        end = b.time + limit
        while b.time < end:
            pc = b.pc()
            if b.mie_open() and any(lo <= pc < hi for lo, hi in self.idle_pc) and self.idle() and                     b.freg[0x0A] == 0 and b.freg[0x0C] == 0:
                return True                         # (MIE on: L1 has returned; the thread idle in its loop)
            b.take()
            b.step(r.randint(1, 200))
        return False

    def post(self, mbx, word):
        if mbx == 'B':
            self.b.w68_post_b(word)
        else:
            self.b.w68_post_a(word)
        return self.settle()


def run_s1(a):
    """the stage-1 board mode: see the module text"""
    import rtlmodel
    t0 = time.time()
    rom = open(a.rom, 'rb').read()
    out = open(os.path.join(a.out, 'log.txt'), 'w')

    def say(*x):
        m = ' '.join(str(y) for y in x)
        print(m, flush=True)
        out.write(m + '\n')

    try:
        irom, wram = rtlmodel.load_image(a.build)
    except ValueError as e:
        say('RESULT: FAIL: %s' % e)
        return 1
    rb = open(os.path.join(a.build, 'img', 'rom.bin'), 'rb').read()
    wc = open(os.path.join(a.build, 'img', 'wcode.bin'), 'rb').read()
    img_check = {'irom_eq_rom.bin': irom[:len(rb)] == rb and not any(irom[len(rb):]),
                 'wram_window_eq_wcode.bin': wram[0x2C00:0x2C00 + len(wc)] == wc}
    if not all(img_check.values()):
        say('RESULT: FAIL: the image files disagree with the ELF load image: %s' % img_check)
        return 1
    rv = S1Side(a.build, rom, a.opt, a.seed)
    hs = HostSide('host', a.host)
    hs.q_load(rom); hs.q_opt(a.opt); hs.q_reset(); hs.q_shadow(); hs.flush()
    for _ in range(4):
        hs.k()
    fails = collections.Counter()
    first = []

    def fail(kind, f, w, info):
        fails[kind] += 1
        if len(first) < 200:
            first.append({'kind': kind, 'frame': f, 'post': '%04X' % w, 'info': info})

    try:
        ok = rv.boot()
    except rtlmodel.Stop:
        ok = False
    if not ok:
        say('RESULT: FAIL: the RV32 boot did not reach a settled release: %s' % rv.b.violations[:4])
        return 1
    hs.q(b'X'); hs.flush()
    n = struct.unpack('<I', hs.read(4))[0]
    hs.read(4 * n)
    rv.log, rv.au, rv.gran, rv.rtl_go = [], bytearray(), set(), []
    capf = open(a.capture, 'rb')
    d = mmap.mmap(capf.fileno(), 0, access=mmap.ACCESS_READ)
    o, frame, nposts, na = 0, -1, 0, 0
    b = rv.b
    stopped = None
    while o + 20 <= len(d) and stopped is None:
        t, ln, f = struct.unpack_from('<HHI', d, o)
        po = o + 20
        o = po + ln
        if f > a.to:
            break
        if t == 1:
            frame = f
            continue
        try:
            if t == 3:
                ad, wd, v = struct.unpack_from('<HHH', d, po)
                if ad >= 0x2000:
                    continue
                if wd == 2:
                    off, data = ad & ~1, struct.pack('<H', v & 0xFFFF)
                else:
                    off, data = ad ^ 1, bytes([v & 0xFF])
                hs.q_w(off, data)
                if off >= 0x1FE0:
                    if off == 0x1FEC and len(data) == 2:
                        hs.flush()
                        if not rv.post('A', v & 0xFFFF):
                            stopped = 'A post %04X did not settle' % v
                        na += 1
                    continue
                b.w68_ram(off, data)
                continue
            if t != 2:
                continue
            wv = struct.unpack_from('<18H', d, po)
            word = wv[0]
            args = struct.pack('<16H', *wv[2:18])
            hs.q_w(0x1E10, args); hs.q_post(word); hs.q_diff(); hs.q_bram(0, BRAM_N); hs.q(b'X'); hs.flush()
            b.w68_ram(0x1E10, args)
            if not rv.post('B', word):
                stopped = 'B post %04X did not settle (violations %s)' % (word, b.violations[:3])
            h_ram, h_fp, h_txt, h_au = hs.r_post()
            h_gran = hs.r_diff()
            h_br = hs.read(BRAM_N)
            nlog = struct.unpack('<I', hs.read(4))[0]
            h_log = list(struct.unpack('<%dI' % nlog, hs.read(4 * nlog)))
        except rtlmodel.Stop:
            stopped = 'model violation: %s' % b.violations[:3]
            break
        nposts += 1
        r_ram = bytearray(b.uc.mem_read(RAMDP, 0x1FE0))
        for k in range(0, 0x20, 2):
            r_ram += struct.pack('<H', b.r68(k))
        if bytes(r_ram[:0x1FE0]) != h_ram[:0x1FE0]:
            bad = [i for i in range(0, 0x1FE0, 2) if r_ram[i:i + 2] != h_ram[i:i + 2]]
            fail('ramdp', frame, word, ['$%04X host %04X rv %04X' % (i, struct.unpack_from('<H', h_ram, i)[0],
                                                                    struct.unpack_from('<H', r_ram, i)[0]) for i in bad[:8]])
        if bytes(r_ram[0x1FE0:]) != h_ram[0x1FE0:0x2000]:
            fail('register_page_68000_view', frame, word, [struct.unpack('<16H', h_ram[0x1FE0:0x2000]),
                                                           struct.unpack('<16H', bytes(r_ram[0x1FE0:]))])
        hf = struct.unpack('<6I', h_fp)
        rf = ((b.ctrl & 1) | (b.window_en << 2), 0, b.sptr, b.vol_sfx, b.vol_bgm, 0)
        if (hf[0], hf[2], hf[3] & 0xFF, hf[4] & 0xFF) != (rf[0], rf[2], rf[3], rf[4]):
            fail('fpgaio', frame, word, [hf, rf])
        if bytes(rv.au) != h_au:
            fail('audio', frame, word, [h_au.hex(), bytes(rv.au).hex()])
        G = sorted(rv.gran | set(h_gran))
        if G:
            rr = runs(G)
            for g, n in rr:
                hs.q_mem(g, n)
            hs.flush()
            h_sd = b''.join(hs.read(n) for g, n in rr)
            r_sd = b''.join(bytes(b.uc.mem_read(rtlmodel.SDRAM + g, n)) for g, n in rr)
            if h_sd != r_sd:
                fail('sdram_bytes', frame, word, [len(G)])
        if bytes(b.save[:BRAM_N]) != h_br:
            fail('bram', frame, word, None)
        h_rtl = [x for x in h_log if (x >> 24) == 0x43]
        h_log = [x for x in h_log if (x >> 24) != 0x43]
        if rv.rtl_go != h_rtl:
            fail('rtl_decoder_go', frame, word, [['%08X' % x for x in h_rtl], ['%08X' % x for x in rv.rtl_go]])
        if rv.log != h_log:
            k = next((i for i, (x, y) in enumerate(zip(rv.log, h_log)) if x != y), min(len(rv.log), len(h_log)))
            fail('register_writes', frame, word, ['first difference at write %d of %d / %d' % (k, len(h_log), len(rv.log)),
                                                  ['%08X' % x for x in h_log[max(0, k - 2):k + 4]],
                                                  ['%08X' % x for x in rv.log[max(0, k - 2):k + 4]]])
        rv.log, rv.au, rv.gran, rv.rtl_go = [], bytearray(), set(), []
        if stopped:
            break
        if nposts % 2000 == 0:
            say('frame %d posts %d wall %.0f s fails %s' % (frame, nposts, time.time() - t0, dict(fails)))
    hs.close()
    reasons = []
    if not nposts:
        reasons.append('no post replayed')
    if fails:
        reasons.append('differences: %s' % dict(fails))
    if stopped:
        reasons.append(stopped)
    if b.violations:
        reasons.append('model violations: %s' % b.violations[:3])
    summ = dict(mode='s1', build=a.build, host=a.host, seed=a.seed, frames_to=frame, posts=nposts, a_posts=na,
                taken={'MEI': b.taken[11], 'MTI': b.taken[7], 'MSI': b.taken[3]}, failures_by_kind=dict(fails),
                image_check=img_check, cycle_reads_patched=b.cycle_reads, wall_s=round(time.time() - t0),
                result='FAIL' if reasons else 'PASS', fail_reasons=reasons)
    with open(os.path.join(a.out, 'mismatch.jsonl'), 'w') as fm:
        for x in first:
            fm.write(json.dumps(x, default=str) + '\n')
    open(os.path.join(a.out, 'summary.json'), 'w').write(json.dumps(summ, indent=1, default=str))
    say(json.dumps({k: v for k, v in summ.items() if k not in ('fail_reasons',)}, default=str))
    for x in first[:6]:
        say(json.dumps(x, default=str)[:400])
    say('RESULT: PASS' if not reasons else 'RESULT: FAIL: ' + ' | '.join(reasons))
    return 1 if reasons else 0


if __name__ == '__main__':
    sys.exit(main())
