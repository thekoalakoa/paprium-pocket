"""Instrument GPGX to measure how much vblank margin Paprium actually has.

    python scripts/apply_gpgx_vbllog.py ../gpgx-build/core/vdp_ctrl.c

Apply AFTER apply_gpgx_vdplog.py - this block sits below it and reuses the
stdio/stdlib includes it adds. Idempotent: refuses to apply twice.

WHY: the FX68K soak's OSD-freeze test (2026-09-07) showed the frozen picture is
CLEAN while the running picture is not. VRAM is correct at all times, so the
defect is not corrupt data - the VDP is scanning a region while the CPU is still
writing it. That means the game's per-frame update is spilling out of vblank
into active display. Whether a small CPU throughput difference can cause that
depends entirely on how much margin the game has, and nobody has measured it.

If Paprium finishes its updates with 200 lines to spare, no plausible slowdown
pushes it into active display and the whole timing family is dead. If it
finishes with 5 lines to spare, it is fragile by construction and a small
throughput loss breaks it exactly as observed. Either way the answer is a
number, and it tells the ISA lane how much slowdown the design can absorb.

VOLUME: data-port writes are far too frequent to log individually - a
full-screen tile update is around 18,000 words, over a million a second. So
this aggregates per (frame, line) and emits one record when the line or frame
changes. At most 262 records per frame, usually far fewer.

Record, 8 bytes, little-endian:
    u16  frame        counted by watching v_counter decrease
    u16  line         v_counter
    u16  data_writes  data-port writes on that line (saturates at 65535)
    u16  dma_words    DMA words initiated on that line (saturates)

HOOKS:
    vdp_68k_data_w_m5   68000 data port    -> 1 data write
    vdp_z80_data_w_m5   Z80 data port      -> 1 data write
    vdp_dma_68k_ext / _ram / _io / copy / fill  -> `length` DMA words

LIMITATION worth stating in any write-up: GPGX performs DMA instantaneously,
so the START line of a transfer is faithful but its SPAN is not. On hardware a
long transfer occupies many lines. So this measures WHEN THE GAME INITIATES
work, which is the right quantity for a margin calculation, but it does not
model a transfer overrunning on its own.

Also: GPGX does not exhibit the defect. That is deliberate. This measures the
game's own timing budget on a correct run - the baseline the hardware has to
fit inside.

Decode with scripts/decode_vbllog.py.

Written with the Write tool, no backslash escapes: tabs, newlines and quotes
built with chr(), per the note in apply_gpgx_winlog.py.
"""
import sys

Q = chr(34)
LF = chr(10)
CR = chr(13)


def main():
    p = sys.argv[1] if len(sys.argv) > 1 else '../gpgx-build/core/vdp_ctrl.c'
    s = open(p, encoding='utf-8', newline='').read()

    if 'ppm_vbl' in s:
        print('already instrumented, nothing to do: ' + p)
        return 0
    if 'ppm_vdplog' not in s:
        print('apply_gpgx_vdplog.py must be applied first (this block reuses its includes)')
        return 1

    nl = CR + LF if s.count(CR + LF) > s.count(LF) // 2 else LF

    body = [
        '',
        '/* paprium-pocket: vblank-margin census (ISA lane, FX68K soak).',
        '   Aggregates data-port writes and DMA words per (frame, line) so a scene',
        '   capture can answer how much vblank margin the game actually has. See',
        '   scripts/apply_gpgx_vbllog.py for why, and for the DMA-span limitation.',
        '   Writes paprium_vbllog.bin. Set PAPRIUM_VBLLOG_MAX=0 to disable. */',
        '#define PAPRIUM_VBLLOG 1',
        '#if PAPRIUM_VBLLOG',
        'static FILE *ppm_vbl_fp = NULL;',
        'static unsigned int ppm_vbl_n = 0;',
        'static unsigned int ppm_vbl_frame = 0;',
        'static unsigned int ppm_vbl_curframe = 0;',
        'static int ppm_vbl_lastv = -1;',
        'static int ppm_vbl_curline = -1;',
        'static unsigned int ppm_vbl_ndata = 0;',
        'static unsigned int ppm_vbl_ndma = 0;',
        'static int ppm_vbl_max = -1;',
        '',
        'static void ppm_vbl_flush(void)',
        '{',
        '  unsigned char rec[8];',
        '  if (ppm_vbl_curline < 0) return;',
        '  if (!ppm_vbl_fp)',
        '  {',
        '    ppm_vbl_fp = fopen(' + Q + 'paprium_vbllog.bin' + Q + ', ' + Q + 'wb' + Q + ');',
        '    if (!ppm_vbl_fp) { ppm_vbl_max = 0; return; }',
        '  }',
        '  rec[0] = (unsigned char)(ppm_vbl_curframe & 0xFF);',
        '  rec[1] = (unsigned char)((ppm_vbl_curframe >> 8) & 0xFF);',
        '  rec[2] = (unsigned char)(ppm_vbl_curline & 0xFF);',
        '  rec[3] = (unsigned char)(((unsigned int)ppm_vbl_curline >> 8) & 0xFF);',
        '  rec[4] = (unsigned char)(ppm_vbl_ndata & 0xFF);',
        '  rec[5] = (unsigned char)((ppm_vbl_ndata >> 8) & 0xFF);',
        '  rec[6] = (unsigned char)(ppm_vbl_ndma & 0xFF);',
        '  rec[7] = (unsigned char)((ppm_vbl_ndma >> 8) & 0xFF);',
        '  fwrite(rec, 1, 8, ppm_vbl_fp);',
        '  if ((++ppm_vbl_n & 0xFF) == 0) filestream_flush(ppm_vbl_fp);',
        '  ppm_vbl_ndata = 0;',
        '  ppm_vbl_ndma = 0;',
        '}',
        '',
        'static void ppm_vbl(unsigned int ndata, unsigned int ndma)',
        '{',
        '  int line;',
        '',
        '  if (ppm_vbl_max < 0)',
        '  {',
        '    const char *e = getenv(' + Q + 'PAPRIUM_VBLLOG_MAX' + Q + ');',
        '    ppm_vbl_max = e ? atoi(e) : 4000000;',
        '  }',
        '  if (ppm_vbl_max == 0) return;',
        '  if (ppm_vbl_n >= (unsigned int)ppm_vbl_max) return;',
        '',
        '  line = (int)v_counter;',
        '  if ((ppm_vbl_lastv >= 0) && (line < ppm_vbl_lastv)) ppm_vbl_frame++;',
        '  ppm_vbl_lastv = line;',
        '',
        '  if ((line != ppm_vbl_curline) || (ppm_vbl_frame != ppm_vbl_curframe))',
        '  {',
        '    ppm_vbl_flush();',
        '    ppm_vbl_curline = line;',
        '    ppm_vbl_curframe = ppm_vbl_frame;',
        '  }',
        '',
        '  /* saturating, so a 65535-word DMA cannot wrap the counter */',
        '  if (ndata >= 65535u - ppm_vbl_ndata) ppm_vbl_ndata = 65535u;',
        '  else ppm_vbl_ndata += ndata;',
        '  if (ndma >= 65535u - ppm_vbl_ndma) ppm_vbl_ndma = 65535u;',
        '  else ppm_vbl_ndma += ndma;',
        '}',
        '#else',
        '#define ppm_vbl(a,b) do {} while (0)',
        '#endif',
        '',
    ]

    anchor = ('#else' + nl
              + '#define ppm_vdplog(r,d,c,s) do {} while (0)' + nl
              + '#endif' + nl)
    if s.count(anchor) != 1:
        print('anchor not found once (' + str(s.count(anchor)) + '): end of the vdplog block')
        return 1
    s = s.replace(anchor, anchor + nl.join(body), 1)

    hooks = [
        ('static void vdp_68k_data_w_m5(unsigned int data)' + nl + '{' + nl,
         '  ppm_vbl(1, 0);' + nl, '68000 data port'),
        ('static void vdp_z80_data_w_m5(unsigned int data)' + nl + '{' + nl,
         '  ppm_vbl(1, 0);' + nl, 'Z80 data port'),
    ]
    for fn in ('vdp_dma_68k_ext', 'vdp_dma_68k_ram', 'vdp_dma_68k_io',
               'vdp_dma_copy', 'vdp_dma_fill'):
        hooks.append(('static void ' + fn + '(unsigned int length)' + nl + '{' + nl,
                      '  ppm_vbl(0, length);' + nl, fn))

    for head, call, what in hooks:
        # the forward declaration ends in ');' so only the definition matches
        if s.count(head) != 1:
            print('anchor not found once (' + str(s.count(head)) + '): ' + what)
            return 1
        s = s.replace(head, head + call, 1)

    open(p, 'w', encoding='utf-8', newline='').write(s)
    print('instrumented ' + p + ' with the vblank-margin census')
    print('rebuild: recompile core/vdp_ctrl.c and relink')
    return 0


if __name__ == '__main__':
    sys.exit(main())
