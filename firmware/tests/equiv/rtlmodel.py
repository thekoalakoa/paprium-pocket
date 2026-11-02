#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""rtlmodel.py - the stage-1 Pocket board (MCU interface v1.2 + the cart register file) for an RV32 (32-bit RISC-V)
image on Unicorn, the CPU emulator library (used by tests/equiv/fuzz_s1.py and rvboard.py's stage-1 board mode; the
stage-1 images are the FW_S1 builds of our new firmware). Boards are named after the firmware test builds B Jam ran on
his hardware: 4 (MCU interface v1.2), 4a (v1.3 with the sound-cache slot and the bar), 4b (the boot cache) and 5 (the
first stage-5 build, with our own song engine and synth); FEAT_4A / FEAT_5 below are their FEAT words. Since 2026-10-21
the board is by default test build 4a's, MCU interface v1.3 as docs/MCU_INTERFACE.md froze it (written from the page,
not from the RTL, docs/MCU_INTERFACE.md test I15): USER_CODE 0x5049_0103, FPGAIO slot 14 STAMP_A and slot 23 FEAT
(test build 4a's 0x0048_001B: the cache slot, the bar, the interim FIFOs and MD+ block, IROM 72), XLINK 0x40 CACHE
(power-on only, one-shot while VALID = 0; since test build 4b: cache=, by default VALID: the boot cache done), 0x44
CACHE_LOADED (the bytes the modelled Pocket loaded at this power-on: cache_loaded=), 0x48 BAR (EN / PX reset by every
reset, W = bar_w once a frame of model time has passed since the power-on, 0 before; bar_w=0 models no video during
the hold), 0x18 LOST (xl_lost=), 0x4C-0x7C read 0, and the CRAM die-0 window 0x09000000-0x093FFFFF (4 MB; its
contents survive a Soft Reset; cram= gives them at power-on: the modelled file load or the last core's image). With
user_code=IFACE_V12 and feat=None the board is test build 4's (v1.2): slots 14 / 23 read 0xFFFFFFFF and XLINK 0x40-0x7C
alias 0x00-0x3C (addr[5:2]). Since test build 5: feat defaults to 'auto' = test build 5's FEAT 0x0058_0047 (CACHE, BAR,
SYNTH, GS3, IROM 88) for an image that links the stage-5 engine, test build 4a's for the others; a rig passes feat= to
put an image on another board (cache4b --s5: test build 4a's board must be refused). FPGAIO = the core's register block
for the MCU (a "slot" is one of its 32-bit registers); XLINK = the core's register block for the Mega CD link and the
cache slot; RAMDP = the cart RAM both the 68000 and the MCU see; CRAM = the Pocket's cellular RAM.

The model is written from the frozen documents, not from the RTL: docs/MCU_INTERFACE.md v1.0 (sections 2-6; a section
number in parentheses below is where the page says it) and docs/CART_FPGA_SPEC.md (the 68000 side: busy, guard,
window, view switch). Every access that v1.0 does not define, or that the stage-1 firmware must not make, is a
VIOLATION the rigs fail on.

  IROM   0x00000000  72 KB from the image files the bitstream carries (mcu.txt 8,192 words + mcu_ext.txt 10,240 words);
                     read and fetch only (a store is a violation; v1.0 acks and drops it); 0x12000-0x1FFFF unbacked.
  WRAM   0x80000000  48 KB from wram_hi.txt / wram_lo.txt (24,576 lines each); a store into the constant lock (the code
                     window KB 11-26) or into a WLOCK'd KB 27-47 is a violation; past 48 KB unbacked.
  FPGAIO 0x01000000  slots on addr[6:2] (section 4): CTRL (reset 0x09; read {CAUSE.B, LSTAT, ctrl}), SPTR, VOL_SFX, GO
                     ({valid, remaining}; N > 0 starts N words and clears the guard, 0 stops), CAUSE {V,S,A,B} W1C,
                     MSIP, TIMER, TCMP, TCTRL, STAMP_B, WLOCK (W1S), VSCNT (v1.1, slot 16: {16'0, the VDP's vertical
                     syncs since the reset}, one every FRAME_CYCLES of model time from the reset while the modelled VDP
                     runs; vdp_stop() freezes it), the sprite decoder's slots 17-22 (v1.2, below); slot 1 (retired), 6
                     (legacy ack), 4, 5, 14 and 23-31 read 0xFFFFFFFF; an access to 1 or 6 is a violation.
  RAMDP  0x02000000  8 KB, MCU halfword at +A = 68000 word A; an MCU access to $1FE0-$1FFF is a violation (the 68000 sees
                     the register file there, section 3.3). Byte view 0x02800000: read only, MCU byte A = 68000 byte A.
  SDRAM  0x03000000  the 2 MB workspace.   FLASH 0x04000000 the ROM, 16-bit words in MCU order (writable: the boot
                     patch); byte view 0x04800000 read only.   BRAM 0x05000000 the battery save, 8 KB (or 4 KB with
                     save_kb=4, aliased every 4 KB as the 0.2.x RTL decodes it).
  SFX    0x06000000  8 channels x 8 B (status: bit 0 empty, bit 1 full; type; pan; flags; vol; sample = push); FIFO depth
                     256, one sample out every CLK_HZ x div / 48,000 cycles while not empty (the rate divider table).
  MDP / EverDrive FIFO 0x07000000 / 0x07800000: zeros (no CD: the album init gives up at once).
  SRAM   0x08000000  256 KB.   XLINK 0x0A000000: XCFG, ID 'XRM2', LSTAT (posts in [31:16]), LCLR, D_WORD, D_BUSY, PEND,
                     ARM, LCTRL (section 3.9); a sub-CPU post sets send pending + busy and CAUSE.S.
  FREG   0x0B000000  the register file's MCU side (section 3.4):
  $1FE4/6/A/C stored (read back), $1FE8 / $1FEE / $1FF2 act on
                     write and read 0, $1FF0 dropped; v1.2: $1FF2 / $1FF4 / $1FF6 also drive the sprite decoder.
  DECODER (v1.2, docs/MCU_INTERFACE.md section 4.9 and sections 2-4 of the decoder's specification; modelled from the
                     specification, not from the RTL): $1FF4 latches HI, $1FF6 odd
                     clears (a run in progress aborted) and even pushes {HI[6:0], v & 0xFFFE} (16 deep, a 17th sets OVF),
                     $1FF2 = 0x8000 with entries queued aborts a run, loads SPTR with DEC_BASE (slot 17) and starts a run
                     over the entries last-pushed first, $1FF2 = 0 or 0xC0xx stops one. The bytes are the chip's 0x80
                     unpacker's (chipdec below), contiguous from DEC_BASE in the workspace's MCU byte order (byte p at
                     p ^ 1). Timing: an entry costs one port-2 access per 16-bit ROM word read and per workspace word
                     written, dec_ns each (default 140 ns, the specification's worst outside a VBlank DMA), after a
                     start latency; an entry's bytes land in the workspace when it is complete (its time D_k), and GO
                     (remaining = the words decoded - the words the window delivered since the START, guard cleared) at
                     the last one. A window word read during a run at an output offset not yet complete counts LATE
                     (slot 22, the specification's rule R-T1); slot 21 keeps the smallest (first read after a START) -
                     (its GO) (rule R-T2).
  IO     0xFFFFFF80  GPIO input (the option word, MENU = bit 24), GPIO output, SYSINFO CLK / USER_CODE; MTIME, UART, WDT
                     are removed in v1.0 (section 2): any access is a violation.
68000 side (docs/CART_FPGA_SPEC.md sections 3, 5 and 7): w68_post_b / w68_post_a (a write of $1FEA / $1FEC: CAUSE.B +
STAMP_B and the guard for a high byte DA / DB / F2; CAUSE.A), r68 (the 68000 view: $1FE4 = busy << 2 | the model bits,
busy = guard | ~stream_valid; $1FE6 / $1FEA / $1FEC stored), consume (the 68000 reading the $C000 window: a word only
while window_en, not the mini view, and the stream valid; each word decrements the length and advances SPTR by 2).
Interrupts (NEORV32 1.4.8.1, as docs/MCU_INTERFACE.md finding 5 says): a latch per line, buf = mie_bit & (buf | line),
cleared for the line taken; taken at a checkpoint when mstatus.MIE and a buf, MEI > MTI > MSI; re-evaluated after every
instruction that writes mie and after every MMIO write that raises a line. Time: TIMER = cycles, each instruction CPI
cycles (estimated at 6: the measured NEORV32 table gives 4-12 a class), trap entry 14 (measured with a CPI bench outside
this tree). The time is exact at the step boundaries; inside one step a TIMER read advances it by one cycle only, so a
busy wait on TIMER (chip_wait, 84's delay, the fatal halt's LED waits) stretches with the step length: keep steps short
(<= 48 instructions) where one runs. mcycle reads are the model's
cycle count (the image is patched in the model's memory: see __init__).
Stage 5: an image that links the engine queue (song_run_one: FW_S5) gets the v1.3 board: IROM 88 KB when
its mcu_ext.txt is 56 KB; ARR (every 68000 write of $1FEA / $1FEC is the next arrival), SEQLAT, STAMP_A (slot 14);
region 0x06 = the synth (MCU interface v1.3 section 3.10): ID,
SEQ {DONE, ARR}, DONE (written: never backwards, never past ARR),
STATUS (BUSY 0, BLKCNT 0: no block model here; tests/equiv/fuzz_sched_s5.py has one), SEQLAT; CONFIG / ARM / FLAGS and
the rest taken and dropped; CRAM die 0's MCU window 0x09000000, 4 MB, as plain memory (test build 4a's map,
above: cram= gives its power-on content, zero by default; v1.3 section 3.8: C6 clears the dac_buf rings there and
reads the wave bank's directory). A stage-1 image sees test build 4a's board (region 0x06 = the SFX FIFOs).
The whole board is a model written from the documents; the RTL was not run here."""
import os, re, struct
from unicorn import Uc, UcError, UC_ARCH_RISCV, UC_MODE_RISCV32, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ, \
    UC_HOOK_MEM_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED, UC_HOOK_MEM_WRITE_PROT, UC_PROT_READ, UC_PROT_EXEC, UC_PROT_ALL
from unicorn import riscv_const as RC

NTSC = 53693175
IFACE_V10 = 0x50490100
IFACE_V11 = 0x50490101                   # v1.1: FPGAIO slot 16 VSCNT
IFACE_V12 = 0x50490102                   # v1.2: the RTL sprite decoder, slots 17-22 (test build 4)
IFACE_V13 = 0x50490103                   # v1.3: STAMP_A, FEAT, CAUSE.BLK, XLINK 0x40-0x48,
                                         # the CRAM map (test build 4a: the default)
FEAT_4A = 0x0048001B                     # test build 4a's FEAT (MCU_INTERFACE.md 4.10
                                         # / 21.5): CACHE, BAR, SFXFIFO, MDP, IROM 72
FEAT_5 = 0x00580047                      # test build 5's FEAT (4.10 / 21.5): CACHE, BAR, SYNTH, GS3, IROM 88
FEAT_AUTO = 'auto'                       # since test build 5: FEAT_5 for an image
                                         # that links the stage-5 engine, else FEAT_4A
CRAM, CRAM_BYTES = 0x09000000, 0x400000  # CRAM die 0 (MCU_INTERFACE.md 3.8)
CACHE_VALID, CACHE_SIZE = 1 << 31, 0x7FFFFF
BAR_EN, BAR_PX = 1 << 31, 0x7FF
BAR_W_H40 = 320                          # the active width W the bar reads once the video ran a line (H40)
DEC_NS = 140.0                           # one 16-bit port-2 access of the decoder (its
                                         # specification's estimated worst outside a
                                         # VBlank DMA; 93 uncontended, 208 inside a DMA)
DEC_START_CYC = 8                        # clk_sys from the START write to the decoder's first request (estimated)
DEC_FLAG_OVF, DEC_FLAG_BADTYPE, DEC_FLAG_D0, DEC_FLAG_PRE, DEC_FLAG_LATE, DEC_FLAG_ABORT = (1 << b for b in range(16, 22))
DEC_OUT_MAX = 0x100000                   # a stream with no end code stops here (never in the data)


def chipdec(rom, a, prev, ws_byte):
    """the chip's 0x80 unpacker (its routine at RAM 0x20003EE8; the decoder specification's section 3.1) on the stream
    whose type byte is ROM byte a (even), appending to prev (the START's output so far: a copy may reach into the
    entries before, byte by byte forward). ws_byte(k) = the workspace byte k bytes before the START's base (k >= 1: a
    reference before it, the chip's semantics; the RTL reads a stale ring
    byte and flags PRE). Returns (bytes read incl. the type byte, flags)"""
    if rom[a] != 0x80:
        return 1, DEC_FLAG_BADTYPE
    p, fl, n_rom = a + 1, 0, len(rom)
    while len(prev) < DEC_OUT_MAX and p < n_rom:
        t = rom[p]
        p += 1
        n = t & 0x3F
        k = t >> 6
        if k == 0:
            if not n:
                break
            prev += rom[p:p + n]
            p += n
        elif k == 1:
            prev += bytes((rom[p],)) * n
            p += 1
        elif k == 2:
            d = rom[p]
            p += 1
            if not d:
                fl |= DEC_FLAG_D0
                prev += bytes(n)                    # (the RTL writes nothing there: the model writes zeros, flagged)
                continue
            for _ in range(n):
                o = len(prev)
                if o < d:
                    fl |= DEC_FLAG_PRE
                    prev.append(ws_byte(d - o))
                else:
                    prev.append(prev[o - d])
        else:
            prev += bytes(n)
    return p - a, fl
FRAME_CYCLES = 896040                    # one NTSC frame at the MCU clock: 262 lines x 3,420 MCLK (clk_sys = MCLK)
IROM_BYTES, WRAM, WRAM_BYTES = 0x12000, 0x80000000, 0xC000
IROM88_BYTES = 0x16000                   # the stage-5 images (pocket88k)
FIO, RAMDP, RAMDP_BV, SDRAM, FLASH, FLASH_BV, BRAM = 0x01000000, 0x02000000, 0x02800000, 0x03000000, 0x04000000, \
    0x04800000, 0x05000000
SFX, MDP, EDFIFO, SRAM, XLINK, FREG, IOPAGE = 0x06000000, 0x07000000, 0x07800000, 0x08000000, 0x0A000000, 0x0B000000, \
    0xFFFFF000
WIN_LO, WIN_HI = 0x2C00, 0x6C00          # the constant-locked code window (WRAM offsets)
LS_SEND, LS_RESTART, LS_AIOFF, LS_LATE, LS_BUSY, LS_ARMED, LS_SRES, LS_SBRQ = 1, 2, 4, 8, 0x10, 0x20, 0x40, 0x80
RATE_DIV = (1, 2, 4, 5, 8, 10, 10, 10)
MEI, MTI, MSI = 11, 7, 3
GUARD_BYTES = (0xDA, 0xDB, 0xF2)
STACK_FILL = 0x5AC3A55A
ABI = ['zero', 'ra', 'sp', 'gp', 'tp', 't0', 't1', 't2', 's0', 's1', 'a0', 'a1', 'a2', 'a3', 'a4', 'a5', 'a6', 'a7', 's2', 's3',
       's4', 's5', 's6', 's7', 's8', 's9', 's10', 's11', 't3', 't4', 't5', 't6']


class Stop(Exception):
    pass


def read_txt_words(p):
    out = bytearray()
    for tok in open(p).read().split():
        out += bytes.fromhex(tok)
    return bytes(out)


def read_txt_bytes(p):
    return bytes(int(t, 16) for t in open(p).read().split())


def load_image(build):
    """(irom 72 KB, wram 48 KB) from the image files in build/img, the shape the stage-1 RTL reads"""
    img = os.path.join(build, 'img')
    rom0 = read_txt_words(os.path.join(img, 'mcu.txt'))
    ext = read_txt_words(os.path.join(img, 'mcu_ext.txt'))
    if len(rom0) != 0x8000 or len(ext) not in (IROM_BYTES - 0x8000, IROM88_BYTES - 0x8000):
        raise ValueError('image files: rom0 %d B, extension %d B (want 32,768 and 40,960: the 72 KB stage-1 IROM, or '
                         '57,344: the 88 KB stage-5 one)' % (len(rom0), len(ext)))
    hi = read_txt_bytes(os.path.join(img, 'wram_hi.txt'))
    lo = read_txt_bytes(os.path.join(img, 'wram_lo.txt'))
    if len(hi) != WRAM_BYTES // 2 or len(lo) != WRAM_BYTES // 2:
        raise ValueError('image files: wram_hi %d / wram_lo %d lines (want 24,576: the 48 KB stage-1 WRAM)' % (len(hi), len(lo)))
    w = bytearray(WRAM_BYTES)
    w[0::2], w[1::2] = hi, lo
    return rom0 + ext, bytes(w)


def nm(path):
    out = {}
    for ln in open(path):
        p = ln.split()
        if len(p) == 4:
            out.setdefault(p[3], (int(p[0], 16), int(p[1], 16)))
        elif len(p) == 3:
            out.setdefault(p[2], (int(p[0], 16), 0))
    return out


def swz(b):
    b = bytearray(b)
    if len(b) & 1:
        b.append(0)
    o = bytearray(len(b))
    o[0::2] = b[1::2]
    o[1::2] = b[0::2]
    return bytes(o)


class Board:
    """the stage-1 board around one image; the rig drives it with step() and take() and plays the 68000 / sub CPU"""

    def __init__(self, build, rom, opt=0, seed=0, save=None, save_kb=8, sysinfo_clk=NTSC, user_code=IFACE_V13, cpi=6,
                 listener=None, sram_fill=None, dec_ns=DEC_NS, feat=FEAT_AUTO, cram=None, cache_loaded=0, xl_lost=0,
                 bar_w=BAR_W_H40, cram_watch=False, cache=None, sram_loaded=0):
        self.build, self.opt, self.cpi = build, opt, cpi
        self.rom = rom
        # v1.3 (test build 4a): the power-on domain (XLINK CACHE / CACHE_LOADED / LOST, the CRAM) is set here only
        self.feat = feat
        # since test build 4b: XLINK CACHE at the power-on. None (the default) = VALID | the image size: the boot cache
        # already done in this power-on, so crt0's stub takes the warm path and the board boot follows at once: every
        # rig but tests/equiv/cache4b.py tests what comes after the boot cache (the unpack is ~230 M instructions);
        # cache4b.py passes 0, a real power-on
        cache = (CACHE_VALID | 0x152100) if cache is None else cache
        self.cache, self.cache_loaded, self.xl_lost, self.bar_w = cache, cache_loaded & CACHE_SIZE, xl_lost, bar_w
        # stage 3 (test build S3b, MCU_INTERFACE.md 3.7): XLINK LOADED, the SRAM halfwords the APF data slot's loader
        # wrote since the power-on (0 by default: no file, as every
        # rig before test build S3b); sram_fill is what it wrote
        self.sram_loaded = sram_loaded & 0xFFFFFFFF
        self.cache_log, self.bar_log = [], []               # (model time, value) of every CACHE / BAR write
        self.cram_writes, self.cram_first_w, self.cram_last_w, self.cram_last_addr = 0, None, None, None
        self.cram_first_addr = None
        self.dec_acc = dec_ns * sysinfo_clk / 1e9          # model cycles per decoder access
        self.dec_log = []                                   # every run: dict (rigs read it)
        self.sym = nm(os.path.join(build, 'main.nm'))
        self.sysinfo_clk, self.user_code = sysinfo_clk, user_code
        self.listener = listener
        self.violations = []
        self.time = 0
        self.tread = 0
        self.irom, self.wram0 = load_image(build)
        self.synth = 'song_run_one' in self.sym              # a stage-5 image: the v1.3 board (above)
        if self.feat == FEAT_AUTO:                          # a stage-5 image sees test build 5's board by default
            self.feat = FEAT_5 if self.synth else FEAT_4A
        self.sy_bad = 0
        # board state (every reset: MCU_INTERFACE 8)
        self.reset_state()
        self.vol_sfx = 0xFF
        self.vol_bgm = 0
        self.save_kb = save_kb
        self.save = bytearray(save_kb * 1024)
        if save is not None:
            self.save[:len(save)] = save[:len(self.save)]
        # XLINK / sub CPU
        self.ls = LS_RESTART
        self.posts_s, self.lctrl, self.xcfg = 0, 0, 0
        self.arms = []
        # SFX FIFOs
        self.fl, self.ftype, self.fdue = [0] * 8, [0] * 8, [0] * 8
        self.fpush = [0] * 8
        self.underruns, self.overflow, self.pushes = [0] * 8, [0] * 8, [0] * 8
        self.last_push, self.under_log = [0] * 8, []
        u = self.uc = Uc(UC_ARCH_RISCV, UC_MODE_RISCV32)
        u.mem_map(0, len(self.irom), UC_PROT_READ | UC_PROT_EXEC)
        u.mem_write(0, self.irom)
        u.mem_map(WRAM, WRAM_BYTES, UC_PROT_ALL)
        u.mem_write(WRAM, self.wram0)
        u.mem_map(RAMDP, 0x2000, UC_PROT_ALL)
        u.mem_map(SDRAM, 0x200000, UC_PROT_ALL)
        u.mem_map(FLASH, 0x800000, UC_PROT_ALL)
        u.mem_write(FLASH, swz(rom[:0x800000]))
        u.mem_map(FLASH_BV, 0x800000, UC_PROT_READ)
        u.mem_write(FLASH_BV, bytes(rom[:0x800000]))
        u.mem_map(MDP, 0x50000, UC_PROT_ALL)
        u.mem_map(EDFIFO, 0x10000, UC_PROT_ALL)
        u.mem_map(SRAM, 0x40000, UC_PROT_ALL)
        if sram_fill:
            u.mem_write(SRAM, sram_fill)
        u.mem_map(CRAM, CRAM_BYTES, UC_PROT_ALL)            # v1.3 3.8 (plain memory: fast; cram_watch hooks the writes)
        if cram:
            u.mem_write(CRAM, bytes(cram[:CRAM_BYTES]))
        elif self.synth and (self.cache & CACHE_VALID) and len(rom) > 0xAF780:
            # since test build 5: the warm default (the boot cache done in this power-on) for a stage-5 image: the cache
            # header's ROM key word (board/pocket/boot/c4b.h C4B_H_STREAM, word 8) names the game's WavPack stream, so
            # C6 takes the bank as made (board_impl.h brd_bank_ok). The bank itself stays zero here (no game data in the
            # model's default); tests/equiv/cache4b.py --s5 makes the real one with the image's own unpack
            a0 = struct.unpack_from('>I', rom, 0xAF77C)[0]
            if a0 + 0x778 <= len(rom):
                u.mem_write(CRAM + 4 * 8, struct.pack('<I', struct.unpack_from('>I', rom, a0 + 0x774)[0]))
        if cram_watch:
            u.hook_add(UC_HOOK_MEM_WRITE, self.cram_w, begin=CRAM, end=CRAM + CRAM_BYTES - 1)
        u.mmio_map(FIO, 0x1000, self.fio_r, None, self.fio_w, None)
        u.mmio_map(FREG, 0x1000, self.freg_r, None, self.freg_w, None)
        u.mmio_map(IOPAGE, 0x1000, self.io_r, None, self.io_w, None)
        u.mmio_map(RAMDP_BV, 0x2000, self.rbv_r, None, self.ro_w, 'the RAMDP byte view')
        u.mmio_map(BRAM, 0x2000, self.bram_r, None, self.bram_w, None)
        if self.synth:
            u.mmio_map(SFX, 0x1000, self.sy_r, None, self.sy_w, None)   # (the CRAM window: mapped above for every
                                                                        # v1.3 board, test build 4a)
        else:
            u.mmio_map(SFX, 0x1000, self.sfx_r, None, self.sfx_w, None)
        u.mmio_map(XLINK, 0x1000, self.xl_r, None, self.xl_w, None)
        u.hook_add(UC_HOOK_MEM_UNMAPPED | UC_HOOK_MEM_FETCH_UNMAPPED, self.unmapped)
        u.hook_add(UC_HOOK_MEM_WRITE_PROT, self.prot_w)
        # the WRAM store check: the constant-locked window always; KB 27-47 only once WLOCK is written (a lazily added
        # hook, the same violations: an unlocked KB has nothing to check), so the decoder of test build 4b's boot
        # overlay (tens of millions of stores into wram_upper, wram_data and the stack) runs at Unicorn's speed
        u.hook_add(UC_HOOK_MEM_WRITE, self.wram_w, begin=WRAM + WIN_LO, end=WRAM + WIN_HI - 1)
        self.wlock_hooked = False
        u.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self.page_rw, begin=RAMDP + 0x1FE0, end=RAMDP + 0x1FFF)
        # instructions that write mie: the CPU latch is re-evaluated right after each. Reads of the cycle counter
        # (mcycle / mcycleh: the TEST counters) are replaced, in the model's memory only, by a load from a model register
        # (0xFFFFF800 / 0xFFFFF804 in the IO page) that returns the model's cycle count: Unicorn's own counter is host
        # time, and the TEST code branches on what it reads, so a run would not repeat (measured: three runs of one
        # seed took three paths; with the replacement, one)
        self.mie_hooks = self.cycle_reads = 0
        for ln in open(os.path.join(build, 'main.dis')):
            m = re.match(r'^\s*([0-9a-f]+):\t[0-9a-f]+\s*\tcsrr?[swc]i?\t(?:[a-z0-9]+,)?mie,', ln)
            if m:
                a = int(m.group(1), 16) + 4
                u.hook_add(UC_HOOK_CODE, self.mie_written, begin=a, end=a)
                self.mie_hooks += 1
            m = re.match(r'^\s*([0-9a-f]+):\t[0-9a-f]+\s*\tcsrr\t([a-z0-9]+),(mcycle|mcycleh|cycle|cycleh)\s*$', ln)
            if m:
                a, rd = int(m.group(1), 16), ABI.index(m.group(2))
                imm = 0x804 if m.group(3).endswith('h') else 0x800
                u.mem_write(a, struct.pack('<I', (imm << 20) | (2 << 12) | (rd << 7) | 0x03))   # lw rd, imm(zero)
                self.cycle_reads += 1
        u.reg_write(RC.UC_RISCV_REG_PC, 0)      # the reset vector (Unicorn's own RISC-V reset pc is not 0)

    # ------------------------------------------------------------------------------------------- reset
    def reset_state(self):
        """the RTL state every reset clears (MCU_INTERFACE.md 8): CTRL 0x09, CAUSE, MSIP, TCMP, TCTRL, STAMP_B, GO,
        TIMER, SPTR, the register file, window, mini view, stream, guard; WLOCK 0. The CPU latch is empty (mie = 0)."""
        self.ctrl, self.cause, self.msip, self.tcmp, self.ten, self.stamp_b = 0x09, 0, 0, 0, 0, 0
        self.stamp_a, self.bar = 0, 0           # v1.3: STAMP_A (every reset), XLINK BAR EN / PX (od_reset = sys_reset)
        self.sptr, self.remaining, self.valid, self.wlock = 0, 0, 0, 0
        self.freg = {0x04: 0, 0x06: 0, 0x0A: 0, 0x0C: 0}
        self.guard, self.window_en, self.mini_view = 0, 0, 0
        self.buf = {MEI: 0, MTI: 0, MSI: 0}
        self.taken = {MEI: 0, MTI: 0, MSI: 0}
        self.unacked = {0: False, 1: False}
        self.t0 = self.time                 # TIMER resets to 0
        self.vs_t0, self.vs_frozen = self.time, None   # VSCNT resets to 0 and counts from here (v1.1)
        self.tread = self.time
        # v1.2: the sprite decoder (every reset: queue empty, idle, HI, DEC_BASE and the slots cleared, MARGIN max)
        self.dq, self.dhi, self.dbase, self.drun, self.dflags = [], 0, 0, None, 0
        self.dtime, self.dmargin, self.dlate = 0, 0x7FFFFFFF, 0
        # v1.3 (stage 5): the arrivals and the synth's DONE (every reset: ARR = DONE = 0)
        self.arr, self.seqlat, self.stamp_a, self.sy_done = 0, 0, 0, 0

    def soft_reset(self):
        """a Soft Reset (sys_reset): the CPU from its reset vector, the RTL registers reset; WRAM, RAMDP, the battery save,
        SDRAM, SRAM and XLINK's XCFG kept (MCU_INTERFACE.md section 8); v1.3: XLINK CACHE / CACHE_LOADED / LOST and the
        CRAM kept (power-on domain), BAR's EN / PX and STAMP_A cleared (reset_state). The Pocket's Quit is such a reset
        (Reset Enter reboots the MCU while the Pocket reads the nonvolatile slots back)"""
        self.reset_state()
        self.ls = (self.ls & ~(LS_SEND | LS_LATE | LS_ARMED | LS_BUSY)) | LS_RESTART
        u = self.uc
        for r in range(1, 32):
            u.reg_write(getattr(RC, 'UC_RISCV_REG_X%d' % r), 0)
        u.reg_write(RC.UC_RISCV_REG_MIE, 0)
        u.reg_write(RC.UC_RISCV_REG_MSTATUS, 0)
        u.reg_write(RC.UC_RISCV_REG_PC, 0)

    # ------------------------------------------------------------------------------------------- memory model
    def viol(self, what):
        if len(self.violations) < 40:
            self.violations.append('t=%d pc=%#x %s' % (self.time, self.uc.reg_read(RC.UC_RISCV_REG_PC), what))

    def unmapped(self, uc, access, addr, size, value, ud):
        self.viol('unmapped access %#x (size %d)' % (addr, size))
        return False

    def prot_w(self, uc, access, addr, size, value, ud):
        self.viol('store into read-only memory %#x (IROM or a byte view)' % addr)
        return False

    def ro_w(self, uc, off, size, value, ud):
        self.viol('store through %s +%#x' % (ud, off))

    def wram_w(self, uc, access, addr, size, value, ud):
        o = addr - WRAM
        if WIN_LO <= o < WIN_HI:
            self.viol('store into the locked code window %#x' % addr)
        kb = o >> 10
        if 27 <= kb <= 47 and (self.wlock >> (kb - 27)) & 1:
            self.viol('store into a WLOCK-locked KB %d (%#x)' % (kb, addr))

    def page_rw(self, uc, access, addr, size, value, ud):
        self.viol('MCU access to RAMDP $%04X (the register page: the 68000 sees the register file there)' % (addr - RAMDP))

    def cram_w(self, uc, access, addr, size, value, ud):
        """(cram_watch) every MCU store into the CRAM window: count, first / last time, the last address; a store into
        the cache image while CACHE.VALID = 1 is a violation (MCU_INTERFACE.md 3.9 / 6.3 rule 8: the Pocket may be
        reading it back)"""
        self.cram_writes += 1
        if self.cram_first_w is None:
            self.cram_first_w, self.cram_first_addr = self.time, addr
        self.cram_last_w, self.cram_last_addr = self.time, addr
        if (self.cache & CACHE_VALID) and addr - CRAM < (self.cache & CACHE_SIZE):
            self.viol('a CRAM store into the cache image (+%#x) while CACHE.VALID = 1' % (addr - CRAM))

    def now(self):
        self.tread = max(self.tread + 1, self.time)
        return (self.tread - self.t0) & 0xFFFFFFFF

    def timer(self):
        return (self.time - self.t0) & 0xFFFFFFFF

    def vs_count(self):
        """VSCNT before its 16-bit wrap: the VDP's vertical syncs since the reset (v1.1)"""
        return self.vs_frozen if self.vs_frozen is not None else (self.time - self.vs_t0) // FRAME_CYCLES

    def vdp_stop(self):
        """a dead VDP (or its clock): VSCNT stops where it is (the freeze-telemetry tests)"""
        self.vs_frozen = self.vs_count()

    def vs_align(self, t_edge):
        """the modelled VDP's phase: the next VS start at model time t_edge (now < t_edge <= now + FRAME_CYCLES), then
        one every FRAME_CYCLES; the count goes on from its value now (no step back): the C6 hold rig places the VDP's
        frames against the capture's timeline (tests/equiv/c6count.py)"""
        c = self.vs_count()
        if not (self.time < t_edge <= self.time + FRAME_CYCLES):
            raise ValueError('vs_align: the next VS start must come within one frame')
        self.vs_t0 = t_edge - (c + 1) * FRAME_CYCLES
        self.vs_frozen = None

    # ---- v1.2: the sprite decoder (its specification's sections 2-4) -----------------------------------------------
    def ws_byte(self, p):
        return self.uc.mem_read(SDRAM + ((p & 0x1FFFFF) ^ 1), 1)[0]

    def dec_start(self):
        """$1FF2 = 0x8000 with entries queued (the caller checked): abort a run, SPTR := DEC_BASE, the run's schedule"""
        self.dec_abort()
        base = self.dbase & 0x1FFFFE
        out, ents, t = bytearray(), [], self.time + DEC_START_CYC
        for a in reversed(self.dq):                 # last pushed, first served
            o0 = len(out)
            nread, fl = chipdec(self.rom, a & 0x7FFFFE, out, lambda k: self.ws_byte(base - k))
            self.dflags |= fl
            reads = ((a & 0x7FFFFE) + nread + 1) // 2 - (a & 0x7FFFFE) // 2
            writes = (len(out) + 1) // 2 - o0 // 2
            t += (reads + writes) * self.dec_acc
            ents.append(dict(a=a, o0=o0, o1=len(out), t=int(t), written=False))
        self.dq = []
        self.sptr = base
        r = self.drun = dict(S=self.time, base=base, out=out, ents=ents, go_t=ents[-1]['t'], done=False, aborted=False,
                             delivered=0, first_read=None, owner=True, late=0, post=None)
        self.dec_log.append(r)
        self.event('dec_start', run=r)

    def dec_write(self, e):
        r = self.drun
        b = bytes(r['out'][e['o0']:e['o1']])
        p = r['base'] + e['o0']
        for i, v in enumerate(b):                   # the workspace in MCU byte order (byte p at p ^ 1)
            self.uc.mem_write(SDRAM + (((p + i) & 0x1FFFFF) ^ 1), bytes((v,)))
        e['written'] = True

    def dec_sync(self, t=None):
        """the run up to model time t (default now): complete entries land in the workspace, then GO at the last"""
        r = self.drun
        if r is None or r['done'] or r['aborted']:
            return
        t = self.time if t is None else t
        for e in r['ents']:
            if not e['written'] and e['t'] <= t:
                self.dec_write(e)
        if r['go_t'] <= t:
            r['done'] = True
            n = max(0, (len(r['out']) >> 1) - r['delivered'])
            if n:
                self.remaining, self.valid, self.guard = n, 1, 0
            else:
                self.valid, self.guard = 0, 0
            self.dtime = (r['go_t'] - r['S']) & 0xFFFFFF
            self.event('go', n=n, rtl=True, run=r)

    def dec_abort(self):
        r = self.drun
        if r is not None and not r['done'] and not r['aborted']:
            self.dec_sync()
            if not r['done']:
                r['aborted'] = True
                self.dflags |= DEC_FLAG_ABORT
                self.event('dec_abort', run=r)

    def dec_acked(self, t):
        """the output bytes of the current run complete at model time t (whole entries: rule R-T1 per entry)"""
        r = self.drun
        if r is None:
            return 0
        if r['done']:
            return len(r['out'])
        k = 0
        for e in r['ents']:
            if e['t'] <= t and not (r['aborted'] and not e['written']):
                k = e['o1']
            else:
                break
        return k

    def dec_freg(self, off, v):
        """the decoder's part of an MCU register write (after the stream rules of the same write)"""
        if off == 0x14:
            self.dhi = v
        elif off == 0x16:
            if v & 1:
                self.dq = []
                self.dec_abort()
            else:
                self.dec_abort()                    # a push while a run is in progress (never: every path clears first)
                if len(self.dq) < 16:
                    self.dq.append(((self.dhi & 0x7F) << 16) | (v & 0xFFFE))
                else:
                    self.dflags |= DEC_FLAG_OVF
        elif off == 0x12:
            if v == 0x8000:
                if self.dq:
                    self.dec_start()
            elif v == 0 or (v & 0xC000) == 0xC000:
                self.dec_abort()

    def dec_stat(self):
        r = self.drun
        run = r is not None and not r['done'] and not r['aborted']
        left = sum(1 for e in r['ents'] if not e['written']) if run else 0
        return (len(self.dq) & 0x1F) | ((left & 0x1F) << 5) | (int(run) << 10) | (int(r is not None and r['done']) << 11) \
            | (self.dflags & 0x3F0000)

    def dec_words(self):
        r = self.drun
        return (self.dec_acked(self.time) >> 1) if r is not None else 0

    def lines(self):
        mti = self.ten and ((self.timer() - self.tcmp) & 0xFFFFFFFF) < 0x80000000
        return {MEI: 1 if self.cause & 0xF else 0, MTI: 1 if mti else 0, MSI: 1 if self.msip else 0}

    def latch(self):
        mie = self.uc.reg_read(RC.UC_RISCV_REG_MIE)
        L = self.lines()
        for k in self.buf:
            self.buf[k] = 1 if ((mie >> k) & 1) and (self.buf[k] or L[k]) else 0

    def mie_written(self, uc, addr, size, ud):
        self.latch()

    def event(self, kind, **kw):
        if self.listener:
            self.listener(kind, kw)

    # ---- FPGAIO
    def fio_r(self, uc, off, size, ud):
        slot = (off >> 2) & 31
        if slot == 0:
            return (self.ctrl & 0xFF) | ((self.ls & 0x7F) << 8) | ((self.cause & 1) << 15)
        if slot == 2:
            return self.sptr
        if slot == 7:
            return (self.valid << 31) | self.remaining
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
        if slot == 14 and (self.feat is not None or self.synth):
            return self.stamp_a                             # v1.3 (4.6)
        if slot == 23 and self.feat is not None:
            return self.feat                                # v1.3 (4.10): a constant
        if slot == 15:
            return self.wlock
        if slot == 16:
            return self.vs_count() & 0xFFFF
        if 17 <= slot <= 22:
            self.dec_sync()
            if slot == 17:
                return self.dbase
            if slot == 18:
                return self.dec_stat()
            if slot == 19:
                return self.dec_words()
            if slot == 20:
                return (0x80000000 if self.drun is not None and self.drun['done'] else 0) | self.dtime
            if slot == 21:
                return self.dmargin & 0xFFFFFFFF
            return min(self.dlate, 0xFFFF)
        if slot in (1, 6):
            self.viol('read of FPGAIO slot %d (retired / legacy)' % slot)
        return 0xFFFFFFFF

    def fio_w(self, uc, off, size, value, ud):
        slot = (off >> 2) & 31
        if slot == 0:
            self.ctrl = value & 0xFF
            self.event('ctrl', v=self.ctrl)
        elif slot == 2:
            self.sptr = value & 0x1FFFFF
            if self.drun is not None:
                self.drun['owner'] = False          # the window left the decoder's output
            self.event('sptr', v=self.sptr)
        elif slot == 3:
            self.vol_sfx = value & 0xFF
        elif slot == 4:
            self.vol_bgm = value & 0xFF                     # no RTL consumer (MCU_INTERFACE.md
                                                            # 4): kept for the rigs' comparison
        elif slot == 7:
            n = value & 0x1FFFFF
            if n:
                self.remaining, self.valid, self.guard = n, 1, 0
            else:
                self.valid = 0
            self.event('go', n=n)
        elif slot == 8:
            for k in (0, 1):
                if value & (1 << k):
                    self.unacked[k] = False
            self.cause &= ~value & 0xF
            self.event('ack', bits=value & 0xF)
        elif slot == 9:
            self.msip = value & 1
        elif slot == 11:
            self.tcmp = value & 0xFFFFFFFF
        elif slot == 12:
            self.ten = value & 1
        elif slot == 15:
            self.wlock |= value & 0x1FFFFF
            if self.wlock and not self.wlock_hooked:
                self.wlock_hooked = True
                self.uc.hook_add(UC_HOOK_MEM_WRITE, self.wram_w, begin=WRAM + 27 * 1024, end=WRAM + WRAM_BYTES - 1)
        elif slot == 17:
            self.dbase = value & 0x1FFFFE
            self.event('dec_base', v=self.dbase)
        elif slot == 18:
            self.dflags &= ~(value & 0x3F0000)
        elif slot == 21:
            self.dmargin = 0x7FFFFFFF
        elif slot == 22:
            self.dlate = 0
        elif slot in (1, 6):
            self.viol('write to FPGAIO slot %d (retired / legacy)' % slot)
        self.latch()

    # ---- the register file, MCU side
    def freg_r(self, uc, off, size, ud):
        off &= 0x1E
        if size == 4:
            return self.freg_r1(off) | (self.freg_r1(off + 2) << 16)
        return self.freg_r1(off)

    def freg_r1(self, off):
        if off == 0x0A and self.unacked[0]:
            self.viol('FZ5: mailbox B read before its CAUSE bit was acknowledged')
        if off == 0x0C and self.unacked[1]:
            self.viol('FZ5: mailbox A read before its CAUSE bit was acknowledged')
        v = self.freg.get(off, 0)
        if off in (0x0A, 0x0C):
            self.event('mbx_read', off=off, v=v)
        return v

    def freg_w(self, uc, off, size, value, ud):
        off &= 0x1E
        if size == 4:
            self.freg_w1(off, value & 0xFFFF)
            self.freg_w1(off + 2, (value >> 16) & 0xFFFF)
        else:
            self.freg_w1(off, value & 0xFFFF)

    def freg_w1(self, off, v):
        old6 = self.freg[0x06]
        if off in self.freg:
            self.freg[off] = v
        if off == 0x0A:
            self.guard = 0
        elif off == 0x08:
            if v & 1:
                self.window_en = 1
            else:
                self.window_en, self.mini_view, self.valid = 0, 1, 0
        elif off == 0x0E:
            if v == 0xAF5B:
                self.window_en, self.mini_view, self.valid = 0, 1, 0
        elif off == 0x12:
            if v == 0 or v & 0x8000:
                self.valid, self.guard = 0, 0
        if off in (0x12, 0x14, 0x16):
            self.dec_sync()
            self.dec_freg(off, v)
        self.event('freg_w', off=off, v=v, old6=old6)

    # ---- the 68000 side (the rig calls these between segments)
    def w68_post_b(self, word):
        self.freg[0x0A] = word & 0xFFFF
        self.cause |= 1
        self.stamp_b = self.timer()
        self.arr = (self.arr + 1) & 0xFFFF                  # v1.3: arrival n
        self.seqlat = (self.seqlat & 0xFFFF0000) | self.arr
        if (word >> 8) in GUARD_BYTES:
            self.guard = 1
        self.unacked[0] = True

    def w68_post_a(self, word):
        self.freg[0x0C] = word & 0xFFFF
        self.cause |= 2
        self.stamp_a = self.timer()                         # v1.3: STAMP_A as STAMP_B (4.6)
        self.arr = (self.arr + 1) & 0xFFFF                  # v1.3: arrival n (F1)
        self.seqlat = (self.seqlat & 0xFFFF) | (self.arr << 16)
        self.unacked[1] = True

    def busy(self):
        self.dec_sync()                     # v1.2: a run's GO up to now (the 68000 polls busy after DA06 / DA07)
        return 1 if (self.guard or not self.valid) else 0

    def r68(self, off):
        if off == 0x04:
            m = self.opt & 0x740
            return (self.busy() << 2) | m
        return self.freg.get(off, 0) if off in (0x06, 0x0A, 0x0C) else 0

    def consume(self, n, t=None, dma=False):
        """the 68000 reads n words of the $C000 window at model time t (default now); returns the words delivered.
        The window serves while window_en and not the mini view whatever stream_valid says (a later rule): a read the
        busy handshake keeps behind GO (DA / DB) stops at the stream's end; a VBlank DMA (dma=True: AF / B1 / F2, no
        handshake) reads its n words regardless. v1.2: a word of the decoder's output read during its run before the
        word's entry is complete counts LATE (slot 22), and the first read after a START sets the margin (slot 21)"""
        t = self.time if t is None else t
        self.dec_sync(t)
        r = self.drun
        got = 0
        while got < n and self.window_en and not self.mini_view:
            if not (self.valid and self.remaining) and not dma:
                break
            if r is not None and r['owner']:
                o = self.sptr - r['base']
                if r['first_read'] is None:
                    r['first_read'] = t
                    self.dmargin = min(self.dmargin, int(t - r['go_t']))
                if not r['done'] and 0 <= o < len(r['out']) and o + 2 > self.dec_acked(t):
                    r['late'] += 1
                    self.dlate += 1
                    self.dflags |= DEC_FLAG_LATE
                    self.event('dec_late', run=r, o=o, t=t)
                if not r['done']:
                    r['delivered'] += 1
            if self.valid and self.remaining:
                self.remaining -= 1
                if not self.remaining:
                    self.valid = 0
            self.sptr = (self.sptr + 2) & 0x1FFFFF
            got += 1
        return got

    def w68_ram(self, off, data):
        """a 68000 write of cart RAM below the register page (MCU byte order, as the capture's RAMW records give it)"""
        if off + len(data) > 0x1FE0:
            data = data[:max(0, 0x1FE0 - off)]
        if data:
            self.uc.mem_write(RAMDP + off, bytes(data))

    # ---- NEORV32 IO
    def io_r(self, uc, off, size, ud):
        a = IOPAGE + off
        if a == 0xFFFFFFE0:
            return self.sysinfo_clk
        if a == 0xFFFFFFE4:
            return self.user_code
        if a == 0xFFFFFF80:
            return self.opt
        if a == 0xFFFFF800:
            return self.time & 0xFFFFFFFF                   # the model's cycle counter (the mcycle note in __init__)
        if a == 0xFFFFF804:
            return self.time >> 32
        if a == 0xFFFFFF84 or 0xFFFFFFE8 <= a <= 0xFFFFFFFC:
            return 0
        self.viol('NEORV32 IO read %#x (removed or not built in v1.0)' % a)
        return 0

    def io_w(self, uc, off, size, value, ud):
        a = IOPAGE + off
        if a != 0xFFFFFF84:
            self.viol('NEORV32 IO write %#x (removed or not built in v1.0)' % a)

    # ---- byte views and the battery save
    def rbv_r(self, uc, off, size, ud):
        v = 0
        for k in range(size):
            a = (off + k) & 0x1FFF
            v |= self.uc.mem_read(RAMDP + (a ^ 1), 1)[0] << (8 * k)
        return v

    def bram_r(self, uc, off, size, ud):
        m = len(self.save) - 1
        return int.from_bytes(bytes(self.save[(off + k) & m] for k in range(size)), 'little')

    def bram_w(self, uc, off, size, value, ud):
        m = len(self.save) - 1
        for k in range(size):
            self.save[(off + k) & m] = (value >> (8 * k)) & 0xFF

    # ---- the synth (v1.3, the stage-5 images): the order registers
    def sy_r(self, uc, off, size, ud):
        off &= 0xFFC
        if off == 0x000:
            return 0x53350001
        if off == 0x028:
            return self.arr | (self.sy_done << 16)
        if off == 0x02C:
            return self.sy_done
        if off == 0x048:
            return self.seqlat
        return 0                                            # STATUS: BUSY 0, BLKCNT 0; the rest

    def sy_w(self, uc, off, size, value, ud):
        off &= 0xFFC
        if off != 0x02C:
            return
        n = value & 0xFFFF
        d = (n - self.sy_done) & 0xFFFF
        if d >= 0x8000 or ((self.arr - n) & 0xFFFF) >= 0x8000:
            self.sy_bad += 1
            self.viol('DONE %#x after %#x with ARR %#x: backwards or past ARR (MCU_INTERFACE v1.3 3.10.5)' % (
                n, self.sy_done, self.arr))
        self.sy_done = n

    # ---- SFX FIFOs
    def sfx_sync(self):
        for ch in range(8):
            if self.fl[ch] <= 0:
                self.fdue[ch] = self.time
                continue
            per = self.sysinfo_clk * RATE_DIV[(self.ftype[ch] >> 4) & 7] // 48000
            while self.fl[ch] > 0 and self.fdue[ch] <= self.time:
                self.fl[ch] -= 1
                self.fdue[ch] += per

    def sfx_r(self, uc, off, size, ud):
        ch, reg = (off >> 3) & 7, off & 7
        if reg == 0:
            self.sfx_sync()
            return (1 if self.fl[ch] == 0 else 0) | (2 if self.fl[ch] >= 256 else 0)
        return 0

    def sfx_w(self, uc, off, size, value, ud):
        ch, reg = (off >> 3) & 7, off & 7
        if reg == 1:
            self.ftype[ch] = value & 0xFF
        elif reg == 6:
            self.sfx_sync()
            if self.fl[ch] == 0:
                self.fdue[ch] = self.time + self.sysinfo_clk * RATE_DIV[(self.ftype[ch] >> 4) & 7] // 48000
            if self.fl[ch] >= 256:
                self.overflow[ch] += 1
            self.fl[ch] = min(self.fl[ch] + 1, 256)
            self.fpush[ch] += 1
            self.pushes[ch] += 1
            self.last_push[ch] = self.time

    def sfx_check(self):
        """an underrun: a FIFO empty while its channel record (interim/s1/sfx_s1.c sfx_chan[ch].size) still has samples
        after it was fed"""
        if 'sfx_chan' not in self.sym:
            return
        self.sfx_sync()
        base = self.sym['sfx_chan'][0]
        for ch in range(8):
            size = struct.unpack('<I', self.uc.mem_read(base + 40 * ch + 8, 4))[0]
            if not size:
                self.fpush[ch] = 0
                continue
            if self.fl[ch] == 0 and self.fpush[ch]:
                self.underruns[ch] += 1
                if len(self.under_log) < 8:
                    per = self.sysinfo_clk * RATE_DIV[(self.ftype[ch] >> 4) & 7] // 48000
                    self.under_log.append(dict(ch=ch, t=self.time, size=size, type=self.ftype[ch],
                                               last_push=self.last_push[ch], ran_dry_at=self.fdue[ch] - per,
                                               pushes=self.fpush[ch], pc=self.pc()))
                self.fpush[ch] = 0

    # ---- XLINK
    def bar_w_now(self):
        """BAR's W (MCU_INTERFACE.md 3.9): the active width of the last complete line, 0 before one (modelled: bar_w
        once a frame of model time has passed since the power-on)"""
        return self.bar_w if self.time >= FRAME_CYCLES else 0

    def xl_r(self, uc, off, size, ud):
        off &= 0x7C if self.feat is not None else 0x3C      # v1.3 decodes addr[6:2]; v1.2 addr[5:2] (aliases)
        if off == 0x00:
            return self.xcfg
        if off == 0x04:
            return 0x58524D32
        if off == 0x0C and self.feat is not None:          # v1.3 LOADED (stage 3, MCU_INTERFACE.md 3.7)
            return self.sram_loaded
        if off == 0x18:
            return self.xl_lost & 0xFFFFFFFF
        if off == 0x20:
            return (self.ls & 0xFF) | ((self.posts_s & 0xFFFF) << 16)
        if off == 0x3C:
            return self.lctrl
        if off == 0x40:
            return self.cache
        if off == 0x44:
            return self.cache_loaded
        if off == 0x48:
            return (self.bar & (BAR_EN | BAR_PX)) | ((self.bar_w_now() & 0x7FF) << 16)
        return 0

    def xl_w(self, uc, off, size, value, ud):
        off &= 0x7C if self.feat is not None else 0x3C
        if off == 0x40:                                     # v1.3 CACHE: one-shot until the next power-on
            self.cache_log.append((self.time, value & 0xFFFFFFFF))
            if not (self.cache & CACHE_VALID):
                self.cache = value & (CACHE_VALID | CACHE_SIZE)
            self.event('cache', v=value)
        elif off == 0x48:                                   # v1.3 BAR: EN and PX
            self.bar = value & (BAR_EN | BAR_PX)
            self.bar_log.append((self.time, self.bar))
        elif off == 0x00:
            self.xcfg = value
        elif off == 0x24:
            self.ls &= ~(value & (LS_SEND | LS_RESTART | LS_AIOFF | LS_LATE))
        elif off == 0x34:
            self.ls = (self.ls | LS_ARMED) & ~LS_BUSY
            self.arms.append(self.time)
        elif off == 0x3C:
            self.lctrl = value

    def send(self):
        """the sub CPU posts (its $3C10 call): send pending + busy, the post count, CAUSE.S"""
        self.posts_s += 1
        self.ls = (self.ls | LS_SEND | LS_BUSY) & ~LS_ARMED
        self.cause |= 4
        self.event('send')

    def sub_release(self):
        self.ls = (self.ls | LS_SRES) & ~LS_SBRQ

    # ------------------------------------------------------------------------------------------- the CPU
    def take(self):
        """at a checkpoint: re-latch, then take the highest pending level if mstatus.MIE"""
        uc = self.uc
        self.latch()
        ms = uc.reg_read(RC.UC_RISCV_REG_MSTATUS)
        if not (ms & 8):
            return None
        for k in (MEI, MTI, MSI):
            if self.buf[k]:
                self.buf[k] = 0
                self.taken[k] += 1
                uc.reg_write(RC.UC_RISCV_REG_MEPC, uc.reg_read(RC.UC_RISCV_REG_PC))
                uc.reg_write(RC.UC_RISCV_REG_MCAUSE, 0x80000000 | k)
                uc.reg_write(RC.UC_RISCV_REG_MSTATUS, (ms & ~0x1888) | ((ms & 8) << 4) | 0x1800)
                uc.reg_write(RC.UC_RISCV_REG_PC, uc.reg_read(RC.UC_RISCV_REG_MTVEC) & ~3)
                self.time += 14
                return k
        return None

    def step(self, n):
        uc = self.uc
        pc = uc.reg_read(RC.UC_RISCV_REG_PC)
        try:
            uc.emu_start(pc, 0xFFFFFFF0, count=n)
        except UcError as e:
            self.viol('CPU fault: %s' % e)
            raise Stop()
        self.time = max(self.time + n * self.cpi, self.tread)
        if self.drun is not None and not self.drun['done']:
            self.dec_sync()
        if self.violations:
            raise Stop()

    def run_to(self, sym, limit):
        """from the current pc until the entry of sym (no interrupts can be taken: the boot); True if reached"""
        a = self.sym[sym][0]
        uc = self.uc
        uc.ctl_remove_cache(a, a + 4)           # a block cached in an earlier run holds no stop check for this 'until'
        try:                                    # (Unicorn 2.1.4: tests/equiv/rvboard.py run)
            uc.emu_start(uc.reg_read(RC.UC_RISCV_REG_PC), a, count=limit)
        except UcError as e:
            self.viol('CPU fault: %s' % e)
            raise Stop()
        ok = uc.reg_read(RC.UC_RISCV_REG_PC) == a
        self.time += (limit if not ok else 0) * self.cpi
        return ok

    def pc(self):
        return self.uc.reg_read(RC.UC_RISCV_REG_PC)

    def mie_open(self):
        return bool(self.uc.reg_read(RC.UC_RISCV_REG_MSTATUS) & 8)

    def rd32(self, name, k=0):
        return struct.unpack('<I', self.uc.mem_read(self.sym[name][0] + 4 * k, 4))[0]

    def rd8(self, name, off=0):
        return self.uc.mem_read(self.sym[name][0] + off, 1)[0]

    def rd16(self, name, off=0):
        return struct.unpack('<H', self.uc.mem_read(self.sym[name][0] + off, 2))[0]

    def stack_depth(self):
        lo, top = self.sym['__stack_floor'][0], self.sym['__crt0_stack_begin'][0]
        words = struct.unpack('<%dI' % ((top - lo) // 4), self.uc.mem_read(lo, top - lo))
        first = next((i for i, w in enumerate(words) if w != STACK_FILL), len(words))
        return top - (lo + 4 * first), first == 0
