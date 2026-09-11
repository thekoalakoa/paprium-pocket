"""Instrument GPGX to log the Z80 sound driver: YM2612 writes and bank reads.

    python scripts/apply_gpgx_fmlog.py ../gpgx-build/core/memz80.c

Paprium's YM2612 is not driven by the 68000 - no reference to $A04000-$A04003
exists anywhere in the 8 MiB image. It is driven by a Z80 driver the cartridge
uploads (ROM 0x16AFC8, type-0x81, 4352 bytes, loads at Z80 $0000), which fetches
32-byte FM patches from Z80 $C000 + program*32, i.e. offset 0x4000 inside the
32 KiB 68000 bank window. On real hardware the STM32F446 is believed to serve
that window, which would make FM firmware-locked. Nobody has ever observed the
path running, because GPGX substitutes the released soundtrack exactly as this
port does (see scripts/build_gpgx_music.py), so the question this log answers is:

    does the Z80 driver run at all, and if it does, what comes back when it goes
    looking for a patch?

Everything is hooked in memz80.c on purpose. Both halves of the driver's traffic
pass through this one file - the YM2612 ports at Z80 $4000-$5FFF and the banked
68000 window at $8000-$FFFF - so one patch catches the whole conversation with
Z80.cycles as a common clock. A 68000-side YM write would NOT be logged here;
that is deliberate, and the negative result above is why.

Records are 8 bytes little-endian, matching the winlog so the same readers work:

    u8   kind    40 YM2612 write   pad = port (0..3: 0/2 = register select,
                                         1/3 = data), address = byte written
                 41 bank read      pad = 68000 address bits 23..16,
                                   address = bits 15..0
                 42 bank register  address = the new window base >> 15
    u8   pad
    u16  address
    u32  stamp   Z80.cycles, low 32 bits

Written to paprium_fmlog.bin in the frontend's working directory. No fflush: the
libretro build transforms FILE/fopen/fwrite to its own RFILE wrappers but leaves
fflush alone, so calling it is a type error - close the frontend cleanly. PAPRIUM_FMLOG
= 1 enables it; FMLOG_BANK_ALL = 0 keeps only the patch region (bank offsets
0x4000-0x5FFF, the 256 possible patch slots) instead of every sample fetch.
Idempotent: refuses to apply twice.
"""
import os
import sys

MARK = "PAPRIUM_FMLOG"
TAB = chr(9)
NL = chr(10)
Q = chr(34)


def main():
    p = sys.argv[1]
    s = open(p, encoding='utf-8', errors='surrogateescape').read()
    if MARK in s:
        raise SystemExit("already applied")

    anchor = '#include ' + Q + 'shared.h' + Q
    if anchor not in s:
        raise SystemExit("anchor not found: " + anchor)

    writer = NL.join([
        anchor,
        "",
        "#define PAPRIUM_FMLOG 1",
        "#define FMLOG_BANK_ALL 0",
        "#define FMLOG_SKIP_DAC 1",
        "#if PAPRIUM_FMLOG",
        "#include <stdio.h>",
        "static FILE *fmlog_fp = 0;",
        "static unsigned int fmlog_n = 0;",
        "static int fmlog_pend[2] = {-1, -1};",
        "static unsigned int fmlog_dac = 0;",
        "static void fmlog_raw(unsigned char kind, unsigned char pad, unsigned short address, unsigned int stamp)",
        "{",
        TAB + "unsigned char rec[8];",
        TAB + "if (fmlog_n > 8000000u) return;",
        TAB + "if (!fmlog_fp) {",
        TAB + TAB + "fmlog_fp = fopen(" + Q + "paprium_fmlog.bin" + Q + ", " + Q + "wb" + Q + ");",
        TAB + TAB + "if (!fmlog_fp) return;",
        TAB + "}",
        TAB + "rec[0] = kind; rec[1] = pad;",
        TAB + "rec[2] = (unsigned char)(address & 0xFF); rec[3] = (unsigned char)((address >> 8) & 0xFF);",
        TAB + "rec[4] = (unsigned char)(stamp & 0xFF); rec[5] = (unsigned char)((stamp >> 8) & 0xFF);",
        TAB + "rec[6] = (unsigned char)((stamp >> 16) & 0xFF); rec[7] = (unsigned char)((stamp >> 24) & 0xFF);",
        TAB + "fwrite(rec, 1, 8, fmlog_fp);",
        TAB + "fmlog_n++;",
        "}",
        "#endif",
    ])
    s = s.replace(anchor, writer, 1)

    # 1. the banked 68000 window, in z80_memory_r, right where the Z80 address
    #    has been resolved to a 68000 one.
    SP6 = chr(32) * 6
    SP10 = chr(32) * 10
    # the same line exists in the write handler; the comment above it differs
    old = NL.join([SP6 + "/* read from 68k banked area */",
                   SP6 + "address = zbank | (address & 0x7FFF);"])
    if s.count(old) != 1:
        raise SystemExit("bank read anchor count: " + str(s.count(old)))
    s = s.replace(old, NL.join([
        old,
        "",
        "#if PAPRIUM_FMLOG",
        TAB + TAB + "#if !FMLOG_BANK_ALL",
        TAB + TAB + "if (((address & 0x7FFF) >= 0x4000) && ((address & 0x7FFF) < 0x6000))",
        TAB + TAB + "#endif",
        TAB + TAB + "fmlog_raw(41, (unsigned char)((address >> 16) & 0xFF),",
        TAB + TAB + TAB + " (unsigned short)(address & 0xFFFF), (unsigned int) Z80.cycles);",
        "#endif",
    ]), 1)

    # 2. the YM2612 ports, in z80_memory_w. "case 2:" appears in both the read
    #    and write handlers, so anchor on the write call itself.
    old = SP6 + "fm_write(Z80.cycles, address & 3, data);"
    if s.count(old) != 1:
        raise SystemExit("YM write anchor count: " + str(s.count(old)))
    s = s.replace(old, NL.join([
        "#if PAPRIUM_FMLOG",
        TAB + TAB + "{",
        TAB + TAB + TAB + "int fp = (address & 2) >> 1;",
        TAB + TAB + TAB + "if (!(address & 1)) fmlog_pend[fp] = data & 0xFF;",
        TAB + TAB + TAB + "#if FMLOG_SKIP_DAC",
        TAB + TAB + TAB + "/* the driver re-selects register 0x2A before every sample, so the",
        TAB + TAB + TAB + "   address write has to go as well or the stream is only halved */",
        TAB + TAB + TAB + "if (fmlog_pend[fp] == 0x2A) fmlog_dac++; else",
        TAB + TAB + TAB + "#endif",
        TAB + TAB + TAB + "fmlog_raw(40, (unsigned char)(address & 3), (unsigned short) data, (unsigned int) Z80.cycles);",
        TAB + TAB + "}",
        "#endif",
        old,
    ]), 1)

    # 3. the bank register, so the window base is in the same stream
    old = SP10 + "gen_zbank_w(data & 1);"
    if s.count(old) != 1:
        raise SystemExit("bank register anchor not found")
    s = s.replace(old, NL.join([
        old,
        "#if PAPRIUM_FMLOG",
        TAB + TAB + TAB + "fmlog_raw(42, 0, (unsigned short)(zbank >> 15), (unsigned int) Z80.cycles);",
        "#endif",
    ]), 1)

    open(p, 'w', encoding='utf-8', errors='surrogateescape').write(s)
    print("instrumented " + p)

    # the 68000 side, for completeness. No reference to $A04000-$A04003 exists
    # anywhere in the 8 MiB image, so this is expected to stay empty - and an
    # expectation worth actually testing.
    q = os.path.join(os.path.dirname(p), "mem68k.c")
    if not os.path.exists(q):
        print("no mem68k.c next to it, skipped the 68000 side")
        return
    t = open(q, encoding='utf-8', errors='surrogateescape').read()
    if MARK in t:
        print("mem68k.c already instrumented")
        return
    anchor68 = SP6 + "fm_write(m68k.cycles, address & 3, data);"
    if t.count(anchor68) != 1:
        print("68000 YM anchor not found, skipped")
        return
    # rename the symbols only - "paprium_fmlog.bin" has a dot, not an
    # underscore, so the filename survives and is replaced separately
    w68 = writer.replace("fmlog_", "fmlog68_").replace(
        "paprium_fmlog.bin", "paprium_fmlog68k.bin")
    if anchor not in t:
        print("mem68k.c has no shared.h include, skipped")
        return
    t = t.replace(anchor, w68, 1)
    t = t.replace(anchor68, NL.join([
        "#if PAPRIUM_FMLOG",
        SP6 + "fmlog68_raw(43, (unsigned char)(address & 3), (unsigned short) data, (unsigned int) m68k.cycles);",
        "#endif",
        anchor68,
    ]), 1)
    open(q, 'w', encoding='utf-8', errors='surrogateescape').write(t)
    print("instrumented " + q)


if __name__ == '__main__':
    main()
