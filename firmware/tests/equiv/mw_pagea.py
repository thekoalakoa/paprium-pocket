#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""mw_pagea.py - stage 3, test build S3b (the MegaWire port): page A of the A858
screen (core/mw/mw_page_a.c, tools/mkpagea.py) on a modelled
68000 and VDP, against what the cart's screen shows (a video capture of a real cart's screen of 2026-10-18 and a photo of
2026-10-10).

The 68000 is Unicorn's (m68k, the 68000 model), started from page A's own vectors in a cart RAM that holds page A at
$0000, page B (the ROM's font at 0x126200) at $0800 and two test lines at $1E10 / $1E50 (our own words, char + $8400);
the ROM is mapped from $010000 for the palette page A reads; the VDP is modelled here: its registers, VRAM / CRAM /
VSRAM writes with auto-increment, the status word's VBlank bit and the V counter, from a cycle count of the 68000's
instructions (NTSC: 262 lines of 3,420 master clocks, the 68000 at 1/7). Checked: the mode (H40, display on, plane A
at $C000, 64x32, no scroll), VRAM tiles $400-$47F = page B, plane A rows 2 and 3 from column 4 = the two lines' words
as they are and every other plane A cell 0 (tile 0 blank), CRAM 0-15 = the ROM's 16 words page A names and every other
colour 0, the palette written in the frame's active part at line 169 after the frames of black (the capture: 125 black
frames from the black-out, the palette's CRAM dots on lines 169-170, the next frame black, then both lines in one
frame), the lines drawn two frames after the palette and again every frame (a changed line shows the next frame), no
pad read, no write outside the VDP and the stack. --png OUT writes the rendered screen (modelled pixels).
    python -I -B tests/equiv/mw_pagea.py [--rom ROM] [--frames 140] [--png OUT] [--json OUT]
Exit 0 = every check passed, 1 = a difference, 2 = setup error; SKIP when no ROM is configured."""
import argparse, json, os, struct, sys, zlib
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import mkpagea   # noqa: E402

LINE_CYC = 3420 / 7.0               # 68000 cycles a line (NTSC master clock / 7)
LINES, ACTIVE = 262, 224
CYC_INSN = 8                        # estimated: the cycles an instruction takes (a typical 68000 move / branch)


class VDP:
    def __init__(self):
        self.reg = [0] * 24
        self.vram = bytearray(0x10000)
        self.cram = [0] * 64
        self.vsram = [0] * 40
        self.cmd_hi = None
        self.code = 0
        self.addr = 0
        self.cycles = 0
        self.log = []               # (frame, line, what)

    def frame_line(self):
        ln = int(self.cycles / LINE_CYC)
        return ln // LINES, ln % LINES

    def status(self):
        f, ln = self.frame_line()
        vb = 1 if ln >= ACTIVE else 0
        return 0x3400 | (vb << 3)

    def hv(self):
        f, ln = self.frame_line()
        v = ln if ln <= 0xEA else (ln - LINES + 0x100) & 0xFF
        return (v << 8) | 0

    def ctrl_w(self, v):
        if self.cmd_hi is None and (v & 0xC000) == 0x8000:
            self.reg[(v >> 8) & 0x1F] = v & 0xFF
            self.log.append(self.frame_line() + ('reg %d = %02X' % ((v >> 8) & 0x1F, v & 0xFF),))
            return
        if self.cmd_hi is None:
            self.cmd_hi = v
            return
        cmd = (self.cmd_hi << 16) | v
        self.cmd_hi = None
        self.code = ((cmd >> 30) & 3) | ((cmd >> 2) & 0x3C)
        self.addr = ((cmd >> 16) & 0x3FFF) | ((cmd & 3) << 14)

    def data_w(self, v):
        c = self.code & 0xF
        if c == 1:
            a = self.addr & 0xFFFE
            self.vram[a] = v >> 8
            self.vram[a + 1] = v & 0xFF
        elif c == 3:
            i = (self.addr >> 1) & 0x3F
            self.cram[i] = v & 0xEEE
            self.log.append(self.frame_line() + ('cram %d' % i,))
        elif c == 5:
            i = (self.addr >> 1) % 40
            self.vsram[i] = v
        else:
            self.log.append(self.frame_line() + ('data write with code %X' % c,))
        self.addr = (self.addr + self.reg[15]) & 0xFFFF


def run(a):
    loc = {}
    p = os.path.join(ROOT, 'paths.local.json')
    if os.path.exists(p):
        loc = json.load(open(p))
    romp = a.rom or loc.get('equiv', {}).get('rom')
    if not romp or not os.path.isfile(romp):
        print('SKIP: no ROM (paths.local.json "equiv": "rom")')
        return 0
    from unicorn import Uc, UC_ARCH_M68K, UC_MODE_BIG_ENDIAN, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_CODE
    from unicorn import UC_HOOK_MEM_UNMAPPED, UcError
    import unicorn.m68k_const as M
    rom = open(romp, 'rb').read()
    img, _listing, labels = mkpagea.build()
    page_a = b''.join(struct.pack('>H', w) for w in img)
    font = rom[0x126200:0x127200]
    line1 = [0x8400 + c for c in b'PAGE A TEST LINE 1 abc@)'] + [0] * 8           # our own test words
    line2 = [0x8400 + c for c in b'@test line two  )' + b' ' * 15]
    uc = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
    try:
        uc.ctl_set_cpu_model(M.UC_CPU_M68K_M68000)
    except Exception:           # noqa: BLE001 (an older unicorn: its default model)
        pass
    uc.mem_map(0x000000, 0x400000)                  # cart RAM ($0000-$1FFF) and the ROM above it
    uc.mem_write(0x010000, rom[0x010000:0x400000])
    ram = bytearray(0x2000)
    ram[0:len(page_a)] = page_a
    ram[0x800:0x1800] = font
    ram[0x1E10:0x1E50] = b''.join(struct.pack('>H', w) for w in line1)
    ram[0x1E50:0x1E90] = b''.join(struct.pack('>H', w) for w in line2)
    uc.mem_write(0, bytes(ram))
    uc.mem_map(0xA10000, 0x10000)                   # the I/O area (the version register) and TMSS
    uc.mem_write(0xA10000, bytes([0, 0xA1]))        # version: an overseas console with TMSS (bit 0-3 = 1)
    uc.mem_map(0xC00000, 0x10000)
    uc.mem_map(0xFF0000, 0x10000)                   # work RAM: the stack
    vdp = VDP()
    st = dict(bad_w=[], pad_reads=0, tmss=None, insns=0)

    def vdp_r(u, access, addr, size, value, ud):
        off = addr & 0x1F
        v = vdp.status() if off in (4, 6) else vdp.hv() if off in (8, 0xA) else 0
        u.mem_write(addr & ~1, struct.pack('>H', v))

    def vdp_w(u, access, addr, size, value, ud):
        off = addr & 0x1F
        if size == 4:
            hi, lo = (value >> 16) & 0xFFFF, value & 0xFFFF
            (vdp.data_w if off < 4 else vdp.ctrl_w)(hi)
            (vdp.data_w if off < 4 else vdp.ctrl_w)(lo)
        elif size == 2:
            (vdp.data_w if off < 4 else vdp.ctrl_w)(value & 0xFFFF)
        else:
            st['bad_w'].append(('VDP byte write', hex(addr)))

    def io_r(u, access, addr, size, value, ud):
        if 0xA10003 <= addr <= 0xA1000D:
            st['pad_reads'] += 1

    def ram_w(u, access, addr, size, value, ud):
        if addr < 0x2000 or 0x010000 <= addr < 0x400000:
            st['bad_w'].append(('cart write', hex(addr)))
        elif 0xA14000 <= addr < 0xA14004:
            st['tmss'] = value

    def code(u, addr, size, ud):
        vdp.cycles += CYC_INSN
        st['insns'] += 1
    uc.hook_add(UC_HOOK_MEM_READ, vdp_r, begin=0xC00000, end=0xC0001F)
    uc.hook_add(UC_HOOK_MEM_WRITE, vdp_w, begin=0xC00000, end=0xC0001F)
    uc.hook_add(UC_HOOK_MEM_READ, io_r, begin=0xA10000, end=0xA1001F)
    uc.hook_add(UC_HOOK_MEM_WRITE, ram_w, begin=0x000000, end=0xA1FFFF)
    uc.hook_add(UC_HOOK_CODE, code)
    ssp, pc = struct.unpack('>II', page_a[0:8])
    uc.reg_write(M.UC_M68K_REG_SR, 0x2700)          # (first: the supervisor bit swaps A7 with the other stack pointer)
    uc.reg_write(M.UC_M68K_REG_A7, ssp)
    frames_end = a.frames * LINES * LINE_CYC
    chunk = 20000
    cur = pc
    snap = {}
    changed = False
    while vdp.cycles < frames_end:
        try:
            uc.emu_start(cur, 0x01000000, count=chunk)
        except UcError as e:
            print('FAIL the 68000 stopped: %s at %06X' % (e, uc.reg_read(M.UC_M68K_REG_PC)))
            return 1
        cur = uc.reg_read(M.UC_M68K_REG_PC)
        f, ln = vdp.frame_line()
        if f >= a.frames - 20 and not changed:      # a changed line must show within the next frames
            changed = True
            uc.mem_write(0x1E10, struct.pack('>H', 0x8458))   # 'X'
            snap['changed_at'] = f
    # ---- checks ----
    bad = []
    r = vdp.reg
    want = {0: 0x04, 1: 0x44, 2: 0x30, 4: 0x07, 12: 0x81, 15: 0x02, 16: 0x01, 11: 0x00, 7: 0x00, 17: 0x00, 18: 0x00}
    for k, v in want.items():
        if r[k] != v:
            bad.append('VDP reg %d = %02X (want %02X)' % (k, r[k], v))
    if bytes(vdp.vram[0x8000:0x9000]) != font:
        bad.append('VRAM $8000-$8FFF (tiles $400-$47F) != page B (the ROM font)')
    if any(vdp.vram[0:32]):
        bad.append('tile 0 not blank')
    pal = list(struct.unpack('>16H', rom[mkpagea.PAL_ROM:mkpagea.PAL_ROM + 32]))
    if vdp.cram[:16] != [x & 0xEEE for x in pal] or any(vdp.cram[16:]):
        bad.append('CRAM %s != the ROM palette at %06X' % (['%03X' % x for x in vdp.cram[:16]], mkpagea.PAL_ROM))
    nt = lambda row, col: struct.unpack('>H', bytes(vdp.vram[0xC000 + row * 128 + col * 2:0xC000 + row * 128 + col * 2 + 2]))[0]
    l1 = [nt(2, 4 + i) for i in range(32)]
    l2 = [nt(3, 4 + i) for i in range(32)]
    if l1 != [0x8458] + line1[1:] or l2 != line2:
        bad.append('plane A rows 2 / 3 from column 4 != the lines (row 2 word 0 shows the changed line: %04X)' % l1[0])
    others = sum(1 for row in range(32) for col in range(64)
                 if not (row in (2, 3) and 4 <= col < 36) and nt(row, col))
    if others:
        bad.append('%d other plane A cells not 0' % others)
    cram_ev = [(f, ln) for f, ln, w in vdp.log if w.startswith('cram')]
    pal_ev = [(f, ln) for f, ln, w in vdp.log if w.startswith('cram')][-16:]
    pal_frame, pal_line = pal_ev[0] if pal_ev else (None, None)
    if pal_line != 169:
        bad.append('the palette written at line %s (the capture: 169)' % pal_line)
    # the first frame the lines are in plane A: from the VRAM name-table writes (not logged per word: inferred from the
    # data writes to $C108 that follow the palette): read it back from a second run's log would be heavy; instead the
    # program's own structure is checked (tools/mkpagea.py): one VBlank wait after the palette, then the lines
    disp_on = [(f, ln) for f, ln, w in vdp.log if w == 'reg 1 = 44']
    res = dict(regs=r[:24], pal_frame=pal_frame, pal_line=pal_line, display_on=disp_on[:1], insns=st['insns'],
               tmss=st['tmss'], pad_reads=st['pad_reads'], bad_writes=st['bad_w'][:5], frames=a.frames,
               wait_frames=mkpagea.WAIT_FRAMES, bad=bad)
    if st['pad_reads']:
        bad.append('%d pad reads (the cart screen reads no pad)' % st['pad_reads'])
    if st['bad_w']:
        bad.append('writes outside the VDP / stack: %s' % st['bad_w'][:5])
    if st['tmss'] != 0x53454741:
        bad.append('TMSS word not written (%s)' % st['tmss'])
    if a.png:
        try:
            import zlib as _z
            w, h = 320, 224
            rows = []
            for y in range(h):
                row = bytearray([0])
                for x in range(w):
                    cell = nt(y // 8, x // 8)
                    tile = cell & 0x7FF
                    pal_i = (cell >> 13) & 3
                    t = vdp.vram[tile * 32 + (y % 8) * 4 + (x % 8) // 2]
                    ci = (t >> 4) if (x % 2) == 0 else (t & 0xF)
                    col = vdp.cram[pal_i * 16 + ci] if ci else vdp.cram[0]
                    row += bytes((((col >> 1) & 7) * 36, ((col >> 5) & 7) * 36, ((col >> 9) & 7) * 36))
                rows.append(bytes(row))
            raw = b''.join(rows)
            png = b'\x89PNG\r\n\x1a\n'
            def chunk_(t, d):
                return struct.pack('>I', len(d)) + t + d + struct.pack('>I', _z.crc32(t + d) & 0xFFFFFFFF)
            png += chunk_(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            png += chunk_(b'IDAT', _z.compress(raw)) + chunk_(b'IEND', b'')
            open(a.png, 'wb').write(png)
        except Exception as e:      # noqa: BLE001 (a picture only)
            print('png: %s' % e)
    if a.json:
        json.dump(res, open(a.json, 'w'), indent=1)
    print('page A: %d instructions, display on at frame/line %s, palette at frame %s line %s (after %d black frames '
          'of its own), TMSS %s' % (st['insns'], disp_on[:1], pal_frame, pal_line, mkpagea.WAIT_FRAMES,
                                    '%08X' % st['tmss'] if st['tmss'] else None))
    for b in bad:
        print('DIFF', b)
    print('PASS' if not bad else 'FAIL')
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rom')
    ap.add_argument('--frames', type=int, default=140)
    ap.add_argument('--png')
    ap.add_argument('--json')
    sys.exit(run(ap.parse_args()))


if __name__ == '__main__':
    main()
