"""Instrument GPGX to log every write that moves a plane horizontally or vertically.

    python scripts/apply_gpgx_scrolllog.py ../gpgx-build/core/vdp_ctrl.c

Apply AFTER apply_gpgx_vdplog.py and apply_gpgx_vbllog.py - this block sits below
them and reuses the stdio/stdlib includes the first one adds. Idempotent.

WHY: the user reports that in the Tug room the FOREGROUND bounces left and right
while the stage, background and enemies are fine - "as if a layer is glitching".
On a Mega Drive that is one plane's scroll value being wrong on some frames, and
it is a much smaller target than "sprites and logos flicker".

The register census (paprium_vdplog.bin, tug room, 5796 frames) already fixed the
surrounding facts:
    $0B = 0x00 written ONCE      -> HSCROLL full-screen, VSCROLL full-screen
    $0D = 0x3D written ONCE      -> hscroll table base = 0x3D << 10 = 0xF400
    $11/$0C/$02 constant, once per frame at vcounter 224 (vblank housekeeping)
    $0A written 6.26x per frame  -> a chain of raster splits, HINT-driven
So with full-screen mode the whole plane's horizontal position is ONE WORD read
at the top of the frame:
    hscroll table + 0 : plane A
    hscroll table + 2 : plane B
and the vertical equivalent is VSRAM word 0 (plane A) and word 2 (plane B).

Those four words are what this logs. If the foreground bounce is a scroll defect,
it is visible here as a write that is late, duplicated, or carrying a stale value.
If those words are written cleanly once per frame at a stable raster position,
the bounce is NOT a scroll-write defect and a whole family dies.

The register census could not answer this: scroll VALUES go through the DATA port,
which paprium_vdplog.bin does not record. This closes that gap.

Record, 12 bytes, little-endian:
    u16 frame      counted by watching v_counter decrease
    u16 line       v_counter at the write
    u16 hpos       cycles % MCYCLES_PER_LINE
    u16 addr       VDP address register at the write
    u16 data       the value written
    u8  kind       0 = HSCROLL 68k, 1 = HSCROLL Z80, 2 = VSRAM 68k, 3 = VSRAM Z80
    u8  pad

FILTER: a VRAM write (code & 0x0F == 1) whose addr lands in
[hbase, hbase + PAPRIUM_SCROLLLOG_WIN) where hbase = reg[0x0D] << 10 and the
window defaults to 32 bytes; or a VSRAM write (code & 0x0F == 5) with addr < 8.
Everything else is ignored, so the log stays small even over thousands of frames.

CAVEAT: DMA into the hscroll table is NOT captured here. The census shows the game
runs ~21 DMA setups per frame, so if the decoder reports no hscroll writes at all,
suspect DMA and check the DMA source/length registers rather than concluding the
table is never written.

Decode with scripts/decode_scrolllog.py.

Written with the Write tool, no backslash escapes: tabs, newlines and quotes built
with chr(), per the note in apply_gpgx_winlog.py.
"""
import sys

Q = chr(34)
LF = chr(10)
CR = chr(13)


def main():
    p = sys.argv[1] if len(sys.argv) > 1 else '../gpgx-build/core/vdp_ctrl.c'
    s = open(p, encoding='utf-8', newline='').read()

    if 'ppm_scroll' in s:
        print('already instrumented, nothing to do: ' + p)
        return 0
    if 'ppm_vbl' not in s:
        print('apply_gpgx_vbllog.py must be applied first (this block sits below it)')
        return 1

    nl = CR + LF if s.count(CR + LF) > s.count(LF) // 2 else LF

    body = [
        '',
        '/* paprium-pocket: scroll-word census (FX68K soak, tug-room foreground bounce).',
        '   Logs only the four words that can move a plane in full-screen scroll mode:',
        '   hscroll table +0/+2 (plane A/B) and VSRAM +0/+2. See',
        '   scripts/apply_gpgx_scrolllog.py for why this exists and what it rules out.',
        '   Writes paprium_scrolllog.bin. Set PAPRIUM_SCROLLLOG_MAX=0 to disable. */',
        '#define PAPRIUM_SCROLLLOG 1',
        '#if PAPRIUM_SCROLLLOG',
        'static FILE *ppm_scroll_fp = NULL;',
        'static unsigned int ppm_scroll_n = 0;',
        'static unsigned int ppm_scroll_frame = 0;',
        'static int ppm_scroll_lastv = -1;',
        'static int ppm_scroll_max = -1;',
        'static int ppm_scroll_win = -1;',
        '',
        'static void ppm_scroll(unsigned int data, unsigned int cycles, int z80)',
        '{',
        '  unsigned char rec[12];',
        '  unsigned int hpos, hbase, a;',
        '  int kind;',
        '',
        '  if (ppm_scroll_max < 0)',
        '  {',
        '    const char *e = getenv(' + Q + 'PAPRIUM_SCROLLLOG_MAX' + Q + ');',
        '    ppm_scroll_max = e ? atoi(e) : 2000000;',
        '    e = getenv(' + Q + 'PAPRIUM_SCROLLLOG_WIN' + Q + ');',
        '    ppm_scroll_win = e ? atoi(e) : 32;',
        '  }',
        '  if (ppm_scroll_max == 0) return;',
        '  if (ppm_scroll_n >= (unsigned int)ppm_scroll_max) return;',
        '',
        '  /* only the writes that can move a plane; everything else is dropped */',
        '  a = addr;',
        '  kind = -1;',
        '  if ((code & 0x0F) == 0x01)',
        '  {',
        '    hbase = ((unsigned int)reg[0x0D]) << 10;',
        '    if ((a >= hbase) && (a < hbase + (unsigned int)ppm_scroll_win))',
        '      kind = z80 ? 1 : 0;',
        '  }',
        '  else if ((code & 0x0F) == 0x05)',
        '  {',
        '    if (a < 8) kind = z80 ? 3 : 2;',
        '  }',
        '  if (kind < 0) return;',
        '',
        '  if (!ppm_scroll_fp)',
        '  {',
        '    ppm_scroll_fp = fopen(' + Q + 'paprium_scrolllog.bin' + Q + ', ' + Q + 'wb' + Q + ');',
        '    if (!ppm_scroll_fp) { ppm_scroll_max = 0; return; }',
        '  }',
        '',
        '  if ((ppm_scroll_lastv >= 0) && ((int)v_counter < ppm_scroll_lastv)) ppm_scroll_frame++;',
        '  ppm_scroll_lastv = (int)v_counter;',
        '',
        '  hpos = cycles % MCYCLES_PER_LINE;',
        '',
        '  rec[0]  = (unsigned char)(ppm_scroll_frame & 0xFF);',
        '  rec[1]  = (unsigned char)((ppm_scroll_frame >> 8) & 0xFF);',
        '  rec[2]  = (unsigned char)(v_counter & 0xFF);',
        '  rec[3]  = (unsigned char)((v_counter >> 8) & 0xFF);',
        '  rec[4]  = (unsigned char)(hpos & 0xFF);',
        '  rec[5]  = (unsigned char)((hpos >> 8) & 0xFF);',
        '  rec[6]  = (unsigned char)(a & 0xFF);',
        '  rec[7]  = (unsigned char)((a >> 8) & 0xFF);',
        '  rec[8]  = (unsigned char)(data & 0xFF);',
        '  rec[9]  = (unsigned char)((data >> 8) & 0xFF);',
        '  rec[10] = (unsigned char)kind;',
        '  rec[11] = 0;',
        '  fwrite(rec, 1, 12, ppm_scroll_fp);',
        '',
        '  /* libretro VFS remaps FILE/fopen/fwrite but not fflush */',
        '  if ((++ppm_scroll_n & 0x3F) == 0) filestream_flush(ppm_scroll_fp);',
        '}',
        '#else',
        '#define ppm_scroll(d,c,z) do {} while (0)',
        '#endif',
        '',
    ]

    # This block READS the file-static `addr` and `code`, so unlike the vdplog and
    # vbllog blocks it cannot sit up with the includes - it must land AFTER their
    # declarations or the compile fails with 'addr undeclared'. Anchor on the last
    # of them and insert after that whole line.
    marker = 'static uint16 addr_latch;'
    if s.count(marker) != 1:
        print('anchor not found once (' + str(s.count(marker)) + '): ' + marker)
        return 1
    cut = s.index(marker)
    eol = s.index(nl, cut) + len(nl)
    s = s[:eol] + nl.join(body) + s[eol:]

    # The two data-port writes already carry ppm_vbl as their first statement, so
    # anchor on that: it puts ppm_scroll before `addr` is incremented, which is the
    # only place the write's own target address is still readable.
    hooks = [
        ('static void vdp_68k_data_w_m5(unsigned int data)' + nl + '{' + nl + '  ppm_vbl(1, 0);' + nl,
         '  ppm_scroll(data, m68k.cycles, 0);' + nl, '68000 data port'),
        ('static void vdp_z80_data_w_m5(unsigned int data)' + nl + '{' + nl + '  ppm_vbl(1, 0);' + nl,
         '  ppm_scroll(data, Z80.cycles, 1);' + nl, 'Z80 data port'),
    ]

    for head, call, what in hooks:
        if s.count(head) != 1:
            print('anchor not found once (' + str(s.count(head)) + '): ' + what)
            return 1
        s = s.replace(head, head + call, 1)

    open(p, 'w', encoding='utf-8', newline='').write(s)
    print('instrumented ' + p + ' with the scroll-word census')
    print('rebuild: recompile core/vdp_ctrl.c and relink')
    return 0


if __name__ == '__main__':
    sys.exit(main())
