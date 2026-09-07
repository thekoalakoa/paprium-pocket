"""Instrument GPGX's VDP control port to log every register write.

    python scripts/apply_gpgx_vdplog.py ../gpgx-build/core/vdp_ctrl.c

Idempotent: refuses to apply twice. Adds a PAPRIUM_VDPLOG build switch and,
when it is 1, appends one record per VDP register write to paprium_vdplog.bin
in the working directory of the running frontend (RetroArch's cwd).

WHY: the FX68K soak measured CPU-to-VDP write latency against register $8B,
whose latch (w213 in ym7101.v:2988, feeding reg_lscr/reg_hscr/reg_vscr at
:3391) sets the plane scroll mode. Optimising that latency only matters if the
game actually writes $8B while a frame is on screen. Latching a CONSTANT late
is invisible. Nobody had looked, because the flash carries no Abs.L
$8B-to-$C00004 writes and a savestate is a one-shot snapshot, not mid-frame
churn. This answers it from a live run.

It also reports $8C, which carries RS0 (bit 7) and RS1 (bit 0) and therefore
decides H32 vs H40 - the mode a VDP sim harness has to be told, and which no
note in the campaign stated.

Result when this was first run (2026-09-07, menu + doors, 6044 frames,
668,712 register writes): $8B was written TWICE across both captures combined,
value 0x00 each time, i.e. set at init and never again. $8C was H40 in both.
The heavy traffic is DMA - about 20 setups per frame in gameplay.

TWO HOOK SITES, because a register write can arrive from either bus master:
    vdp_ctrl.c  the 68000 control port  vdp_reg_w((data >> 8) & 0x1F, ...)
    vdp_ctrl.c  the Z80 control port    vdp_reg_w(data & 0x1F, addr_latch, ...)
Init-time writes (vdp_reset and friends) call vdp_reg_w directly and are NOT
logged, which is what we want: the question is what the game does at runtime.

Record, 8 bytes, little-endian:
    u8   reg      bit 7 = 1 means the Z80 issued it; bits 4..0 are the register
    u8   value
    u16  hpos     cycles modulo MCYCLES_PER_LINE (3420), i.e. position in line
    u16  vcounter
    u16  frame    counted here by watching v_counter decrease, since the frame
                  counter in paprium.h is static to another translation unit

Decode with scripts/decode_vdplog.py.

TWO TRAPS, both of which cost a build here:

  * The libretro VFS layer remaps FILE, fopen, fwrite and fclose to its RFILE
    equivalents, but NOT fflush. The obvious line does not compile. Use
    filestream_flush(), declared via streams/file_stream.h which the transforms
    header already pulls in. This is also why the winlog in paprium.h never
    flushes at all - so a capture ended by killing the emulator rather than
    closing it can lose its tail.

  * vdp_ctrl.c is CRLF. An anchor built with plain newlines matches nothing and
    the applier reports zero hits rather than failing loudly. Line endings are
    detected below and the inserted text follows the file.

Written with the Write tool, and with no backslash escapes: tabs, newlines and
quotes are built with chr(), per the note in apply_gpgx_winlog.py about heredocs
arriving with a backslash stripped.
"""
import sys

Q = chr(34)
LF = chr(10)
CR = chr(13)


def main():
    p = sys.argv[1] if len(sys.argv) > 1 else '../gpgx-build/core/vdp_ctrl.c'
    s = open(p, encoding='utf-8', newline='').read()

    if 'ppm_vdplog' in s:
        print('already instrumented, nothing to do: ' + p)
        return 0

    nl = CR + LF if s.count(CR + LF) > s.count(LF) // 2 else LF

    body = [
        '',
        '/* paprium-pocket: VDP control-write census (ISA lane, FX68K soak).',
        '   Logs every VDP register write issued at runtime with (reg, value, line',
        '   position, vcounter, frame), so a scene capture can answer whether a register',
        '   churns mid-frame or is written once with a constant value. Self-contained on',
        '   purpose: it does not touch the paprium.h window logger or its file.',
        '   Writes paprium_vdplog.bin in the emulator working directory.',
        '   Set PAPRIUM_VDPLOG_MAX=0 to disable, or to a record count to cap it. */',
        '#define PAPRIUM_VDPLOG 1',
        '#if PAPRIUM_VDPLOG',
        '#include <stdio.h>',
        '#include <stdlib.h>',
        'static FILE *ppm_vdplog_fp = NULL;',
        'static unsigned int ppm_vdplog_n = 0;',
        'static unsigned int ppm_vdplog_frame = 0;',
        'static int ppm_vdplog_lastv = -1;',
        'static int ppm_vdplog_max = -1;',
        '',
        'static void ppm_vdplog(unsigned int r, unsigned int d, unsigned int cycles, int src)',
        '{',
        '  unsigned char rec[8];',
        '  unsigned int hpos;',
        '',
        '  if (ppm_vdplog_max < 0)',
        '  {',
        '    const char *e = getenv(' + Q + 'PAPRIUM_VDPLOG_MAX' + Q + ');',
        '    ppm_vdplog_max = e ? atoi(e) : 4000000;',
        '  }',
        '  if (ppm_vdplog_max == 0) return;',
        '  if (ppm_vdplog_n >= (unsigned int)ppm_vdplog_max) return;',
        '',
        '  if (!ppm_vdplog_fp)',
        '  {',
        '    ppm_vdplog_fp = fopen(' + Q + 'paprium_vdplog.bin' + Q + ', ' + Q + 'wb' + Q + ');',
        '    if (!ppm_vdplog_fp) { ppm_vdplog_max = 0; return; }',
        '  }',
        '',
        '  /* v_counter is monotonic within a frame, so a decrease is a frame boundary */',
        '  if ((ppm_vdplog_lastv >= 0) && ((int)v_counter < ppm_vdplog_lastv)) ppm_vdplog_frame++;',
        '  ppm_vdplog_lastv = (int)v_counter;',
        '',
        '  hpos = cycles % MCYCLES_PER_LINE;',
        '',
        '  rec[0] = (unsigned char)((r & 0x1F) | (src ? 0x80 : 0x00));',
        '  rec[1] = (unsigned char)(d & 0xFF);',
        '  rec[2] = (unsigned char)(hpos & 0xFF);',
        '  rec[3] = (unsigned char)((hpos >> 8) & 0xFF);',
        '  rec[4] = (unsigned char)(v_counter & 0xFF);',
        '  rec[5] = (unsigned char)((v_counter >> 8) & 0xFF);',
        '  rec[6] = (unsigned char)(ppm_vdplog_frame & 0xFF);',
        '  rec[7] = (unsigned char)((ppm_vdplog_frame >> 8) & 0xFF);',
        '  fwrite(rec, 1, 8, ppm_vdplog_fp);',
        '',
        '  /* libretro VFS remaps FILE/fopen/fwrite but not fflush; use the native call */',
        '  if ((++ppm_vdplog_n & 0xFF) == 0) filestream_flush(ppm_vdplog_fp);',
        '}',
        '#else',
        '#define ppm_vdplog(r,d,c,s) do {} while (0)',
        '#endif',
        '',
    ]

    # The logger goes after the forward declarations, so v_counter (declared
    # near the top of the file) and MCYCLES_PER_LINE (via shared.h -> system.h)
    # are both in scope.
    anchor = 'static void vdp_dma_fill(unsigned int length);' + nl
    if s.count(anchor) != 1:
        print('anchor not found once (' + str(s.count(anchor)) + '): forward declarations')
        return 1
    s = s.replace(anchor, anchor + nl.join(body), 1)

    hooks = [
        ('      vdp_reg_w((data >> 8) & 0x1F, data & 0xFF, m68k.cycles);',
         '      ppm_vdplog((data >> 8) & 0x1F, data & 0xFF, m68k.cycles, 0);',
         '68000 control port'),
        ('        vdp_reg_w(data & 0x1F, addr_latch, Z80.cycles);',
         '        ppm_vdplog(data & 0x1F, addr_latch, Z80.cycles, 1);',
         'Z80 control port'),
    ]
    for call, hook, what in hooks:
        if s.count(call + nl) != 1:
            print('anchor not found once (' + str(s.count(call + nl)) + '): ' + what)
            return 1
        s = s.replace(call + nl, hook + nl + call + nl, 1)

    open(p, 'w', encoding='utf-8', newline='').write(s)
    print('instrumented ' + p)
    print('rebuild: recompile core/vdp_ctrl.c and relink; see docs for the flags')
    return 0


if __name__ == '__main__':
    sys.exit(main())
