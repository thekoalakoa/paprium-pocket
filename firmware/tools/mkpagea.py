#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""mkpagea.py - builds core/mw/mw_page_a.c: page A of the MegaWire screen, the small 68000 program the cart runs
while its chip shows the MegaWire screen (the Options pad code's A858; from test build S3b on; see core/mw/mw_screen.c).

The cart's own page A is not in the game's ROM (the cart loads it from elsewhere), so this one is written by our team
from the screen's behaviour on a real cart (a video capture of the screen of 2026-10-18 and a photo of 2026-10-10):
H40, the two 32-character lines of RAMDP $1E10 / $1E50 shown as they are at rows 2-3 from column 4,
the font of page B (RAMDP $0800-$17FF: tile $400 + character), the NX terminal's palette line 0 (read here from the
game's own ROM, where it lies as 16 words), a long black, the palette, the text two frames later, then the lines
redrawn every frame; it reads no pad, and only a reset leaves it. The chip loads page A into RAMDP $0000-$07FF (vectors
and code at $200) and starts the 68000 on it (core/mw/mw_screen.c).

    python -I -B tools/mkpagea.py [--check]     (writes the file; --check: exit 1 if the file differs from the output)

A two-pass assembler for the few 68000 forms the program uses (no other 68000 tool is needed to rebuild it)."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'core', 'mw', 'mw_page_a.c')

PAL_ROM = 0x173ADE      # the NX terminal's palette line 0 in the game's ROM (16 words; the 68000 reads it from there)
WAIT_FRAMES = 102       # black frames from the program's start to the palette (with the set-up: ~1.8 s, the capture)
PAL_LINE = 169          # the palette is written in the frame's active part at this line (the capture's CRAM dots)


class Asm:
    def __init__(self):
        self.items = []          # (address, words or a callable that returns words, text)
        self.labels = {}
        self.pc = 0x200

    def label(self, name):
        self.labels[name] = self.pc

    def emit(self, n, f, text):
        self.items.append((self.pc, n, f, text))
        self.pc += 2 * n

    # ---- the forms used ------------------------------------------------------------------------------------
    def raw(self, words, text):
        self.emit(len(words), lambda: list(words), text)

    def move_w_imm_sr(self, v):
        self.raw([0x46FC, v], 'move.w  #$%04X,sr' % v)

    def move_b_absl_d(self, a, d):
        self.raw([0x1039 | (d << 9), a >> 16, a & 0xFFFF], 'move.b  $%06X,d%d' % (a, d))

    def andi_b_d(self, v, d):
        self.raw([0x0200 | d, v & 0xFF], 'andi.b  #$%02X,d%d' % (v, d))

    def move_l_imm_absl(self, v, a):
        self.raw([0x23FC, v >> 16, v & 0xFFFF, a >> 16, a & 0xFFFF], 'move.l  #$%08X,$%06X' % (v, a))

    def lea_absl(self, a, n):
        self.raw([0x41F9 | (n << 9), a >> 16, a & 0xFFFF], 'lea     $%06X,a%d' % (a, n))

    def lea_absw(self, a, n):
        self.raw([0x41F8 | (n << 9), a & 0xFFFF], 'lea     $%04X.w,a%d' % (a, n))

    def lea_pc(self, lab, n):
        pc = self.pc
        self.emit(2, lambda: [0x41FA | (n << 9), (self.labels[lab] - (pc + 2)) & 0xFFFF], 'lea     %s(pc),a%d' % (lab, n))

    def move_l_imm_ind(self, v, a):
        self.raw([0x20BC | (a << 9), v >> 16, v & 0xFFFF], 'move.l  #$%08X,(a%d)' % (v, a))

    def move_w_imm_ind(self, v, a):
        self.raw([0x30BC | (a << 9), v], 'move.w  #$%04X,(a%d)' % (v, a))

    def move_w_d_ind(self, d, a):
        self.raw([0x3080 | (a << 9) | d], 'move.w  d%d,(a%d)' % (d, a))

    def move_w_postinc_ind(self, s, a):
        self.raw([0x3080 | (a << 9) | 0x18 | s], 'move.w  (a%d)+,(a%d)' % (s, a))

    def move_w_ind_d(self, a, d):
        self.raw([0x3010 | (d << 9) | a], 'move.w  (a%d),d%d' % (a, d))

    def move_w_disp_d(self, disp, a, d):
        self.raw([0x3028 | (d << 9) | a, disp & 0xFFFF], 'move.w  %d(a%d),d%d' % (disp, a, d))

    def moveq(self, v, d):
        self.raw([0x7000 | (d << 9) | (v & 0xFF)], 'moveq   #%d,d%d' % (v, d))

    def move_w_imm_d(self, v, d):
        self.raw([0x303C | (d << 9), v & 0xFFFF], 'move.w  #%d,d%d' % (v, d))

    def lsr_w_8(self, d):
        self.raw([0xE048 | d], 'lsr.w   #8,d%d' % d)

    def cmpi_w_d(self, v, d):
        self.raw([0x0C40 | d, v & 0xFFFF], 'cmpi.w  #%d,d%d' % (v, d))

    def btst_imm_d(self, b, d):
        self.raw([0x0800 | d, b], 'btst    #%d,d%d' % (b, d))

    def dbra(self, d, lab):
        pc = self.pc
        self.emit(2, lambda: [0x51C8 | d, (self.labels[lab] - (pc + 2)) & 0xFFFF], 'dbra    d%d,%s' % (d, lab))

    def bcc_s(self, cond, lab, name):
        pc = self.pc

        def f():
            disp = self.labels[lab] - (pc + 2)
            assert -128 <= disp <= 127 and disp != 0, (lab, disp)
            return [0x6000 | (cond << 8) | (disp & 0xFF)]
        self.emit(1, f, '%-7s %s' % (name, lab))

    def bra_s(self, lab):
        self.bcc_s(0x0, lab, 'bra.s')

    def bsr_s(self, lab):
        self.bcc_s(0x1, lab, 'bsr.s')

    def bne_s(self, lab):
        self.bcc_s(0x6, lab, 'bne.s')

    def beq_s(self, lab):
        self.bcc_s(0x7, lab, 'beq.s')

    def rts(self):
        self.raw([0x4E75], 'rts')

    def rte(self):
        self.raw([0x4E73], 'rte')

    def words(self, lab, ws, text):
        self.label(lab)
        self.raw(ws, text)


def program():
    a = Asm()
    VDP_C, VDP_D = 0xC00004, 0xC00000
    a.label('start')
    a.move_w_imm_sr(0x2700)                      # interrupts off: the program polls the VDP
    # the console's TMSS (the hold before page A reset it): the 'SEGA' word when the version register asks for it
    a.move_b_absl_d(0xA10001, 0)
    a.andi_b_d(0x0F, 0)
    a.beq_s('vdp')
    a.move_l_imm_absl(0x53454741, 0xA14000)
    a.label('vdp')
    a.lea_absl(VDP_C, 5)                         # a5: the VDP's control port, a4: its data port
    a.lea_absl(VDP_D, 4)
    a.lea_pc('regs', 2)                          # the registers: H40, display off for the clears
    a.moveq(len(REGS) - 1, 3)
    a.label('reg')
    a.move_w_postinc_ind(2, 5)
    a.dbra(3, 'reg')
    a.moveq(0, 6)                                # d6 = 0: the clears' word
    a.move_l_imm_ind(0x40000000, 5)              # VRAM from 0: all 64 KB (the planes, the sprites, tile 0 blank)
    a.move_w_imm_d(0x7FFF, 3)
    a.label('vram')
    a.move_w_d_ind(6, 4)
    a.dbra(3, 'vram')
    a.move_l_imm_ind(0xC0000000, 5)              # CRAM: all 64 colours black
    a.moveq(63, 3)
    a.label('cram')
    a.move_w_d_ind(6, 4)
    a.dbra(3, 'cram')
    a.move_l_imm_ind(0x40000010, 5)              # VSRAM: no vertical scroll
    a.moveq(39, 3)
    a.label('vsram')
    a.move_w_d_ind(6, 4)
    a.dbra(3, 'vsram')
    a.move_l_imm_ind(0x40000002, 5)              # the font: page B (RAMDP $0800-$17FF) to VRAM $8000 = tile $400
    a.lea_absw(0x0800, 3)
    a.move_w_imm_d(0x07FF, 3)
    a.label('font')
    a.move_w_postinc_ind(3, 4)
    a.dbra(3, 'font')
    a.move_w_imm_ind(0x8144, 5)                  # the display on (black: every colour is 0)
    a.move_w_imm_d(WAIT_FRAMES - 1, 7)           # the long black
    a.label('black')
    a.bsr_s('vbl')
    a.dbra(7, 'black')
    a.label('line')                              # the palette in the frame's active part, at the capture's line
    a.move_w_disp_d(4, 5, 0)                     # the H/V counter ($C00008): V in the high byte
    a.lsr_w_8(0)
    a.cmpi_w_d(PAL_LINE, 0)
    a.bne_s('line')
    a.move_l_imm_ind(0xC0000000, 5)
    a.lea_absl(PAL_ROM, 3)
    a.moveq(15, 3)
    a.label('pal')
    a.move_w_postinc_ind(3, 4)
    a.dbra(3, 'pal')
    a.bsr_s('vbl')                               # the text two frames later (the next frame stays black), both
    a.label('loop')                              # lines in one frame; then every frame: the two lines from RAMDP
    a.bsr_s('vbl')
    a.move_l_imm_ind(0x41080003, 5)              # VRAM $C108: plane A row 2, column 4
    a.lea_absw(0x1E10, 3)
    a.moveq(31, 3)
    a.label('l1')
    a.move_w_postinc_ind(3, 4)
    a.dbra(3, 'l1')
    a.move_l_imm_ind(0x41880003, 5)              # VRAM $C188: row 3, column 4 (a3 is at $1E50 now)
    a.moveq(31, 3)
    a.label('l2')
    a.move_w_postinc_ind(3, 4)
    a.dbra(3, 'l2')
    a.bra_s('loop')
    a.label('vbl')                               # to the start of the next VBlank (status bit 3)
    a.move_w_ind_d(5, 1)
    a.btst_imm_d(3, 1)
    a.bne_s('vbl')
    a.label('vbl2')
    a.move_w_ind_d(5, 1)
    a.btst_imm_d(3, 1)
    a.beq_s('vbl2')
    a.rts()
    a.label('trap')                              # every other vector: return
    a.rte()
    a.words('regs', REGS, 'the registers, in this order: 0, 1, 12, 2, 4, 3, 5, 13, 7, 10, 11, 15, 16, 17, 18, 6')
    return a


REGS = [0x8004, 0x8104, 0x8C81, 0x8230, 0x8407, 0x832C, 0x8578, 0x8D3F, 0x8700, 0x8AFF, 0x8B00, 0x8F02,
        0x9001, 0x9100, 0x9200, 0x8600]


def build():
    a = program()
    code = {}
    listing = []
    for pc, n, f, text in a.items:
        ws = f()
        assert len(ws) == n
        for i, w in enumerate(ws):
            code[pc + 2 * i] = w & 0xFFFF
        listing.append((pc, ws, text))
    end = a.pc
    img = [0] * (end // 2)
    img[0], img[1] = 0x00FF, 0xFE00              # the stack pointer: the top of work RAM less 512 B
    img[2], img[3] = 0x0000, 0x0200              # the start
    trap = a.labels['trap']
    for v in range(2, 64):
        img[2 * v], img[2 * v + 1] = 0x0000, trap
    for pc, w in code.items():
        img[pc // 2] = w
    assert end <= 0x800
    return img, listing, a.labels


def render(img, listing, labels):
    out = []
    out.append('/* Copyright (C) 2026 Marsupial Solutions LLC')
    out.append('   SPDX-License-Identifier: GPL-3.0-or-later */')
    out.append('/* core/mw/mw_page_a.c - page A of the MegaWire screen: our 68000 program for the cart\'s A858 screen (test')
    out.append(' * build S3b on). GENERATED by tools/mkpagea.py (its docstring says what the program does and why): edit the')
    out.append(' * tool, not this file. In the SRAM image; core/mw/mw_screen.c packs it as a page and the cart chip\'s loader puts it')
    out.append(' * in RAMDP $0000-$%03X (the vectors at $0000, the code at $200). The listing:' % (2 * len(img) - 1))
    for pc, ws, text in listing:
        out.append(' *   %04X  %-24s %s' % (pc, ' '.join('%04X' % w for w in ws), text))
    out.append(' * Labels: ' + ', '.join('%s %04X' % (k, v) for k, v in sorted(labels.items(), key=lambda x: x[1])) + ' */')
    out.append('#include <stdint.h>')
    out.append('#include "mw.h"')
    out.append('')
    out.append('const uint16_t mw_page_a[MW_PAGE_A_WORDS] = {')
    for i in range(0, len(img), 12):
        out.append('    ' + ', '.join('0x%04X' % w for w in img[i:i + 12]) + ',')
    out.append('};')
    return '\n'.join(out) + '\n', len(img)


def main():
    img, listing, labels = build()
    text, n = render(img, listing, labels)
    if '--check' in sys.argv:
        cur = open(OUT, encoding='utf-8').read() if os.path.exists(OUT) else ''
        print('mw_page_a.c %s the generator (%d words)' % ('==' if cur == text else 'DIFFERS FROM', n))
        sys.exit(0 if cur == text else 1)
    open(OUT, 'w', encoding='utf-8', newline='\n').write(text)
    print('wrote %s: %d words (%d B); MW_PAGE_A_WORDS must be %d' % (OUT, n, 2 * n, n))


if __name__ == '__main__':
    main()
