"""Instrument GPGX's Paprium cart to log every read of the stream window.

    python scripts/apply_gpgx_winlog.py ../gpgx-build/core/cart_hw/paprium.h

Idempotent: refuses to apply twice. Adds a PAPRIUM_WINLOG build switch and,
when it is 1, appends one record per event to paprium_winlog.bin in the
current directory of the running frontend (RetroArch's working directory).

Why every read goes through ONE hook: bank 0 of the 68000 map carries a
read16 handler (paprium_r16), and vdp_dma_68k_ext takes the handler when
one is set (vdp_ctrl.c:3179). So CPU reads and 68k-bus VDP DMA reads of
0xC000-0xFFFF both land in paprium_r16's default branch. Page turns are
trapped at the top of the same function. Byte reads go via paprium_r8.

Record, 8 bytes, little-endian:
    u8   kind     0 word read        address = 68000 address
                  1 byte read        address = 68000 address
                  2 page turn        address = page size in bytes
                  3 0xDB command     address = offset word at 0x1E12, pad = size at 0x1E14 / 64
                  4 0xDA command     address = command low byte (mode)
                  5 0xAF frame end
                  8 word read of 0x1FEA (mailbox command word)
                  9 word/byte read of 0x1FE4..0x1FEB (status words)   address = address
                 10 PC of the 68000 at a 0xDB write   pad = PC bits 23..16, address = bits 15..0
                 11 0xAE frame start
    u8   pad      see above
    u16  address
    u32  stamp    frame counter (high 16) | v_counter (low 16)

This file is written with the Write tool on purpose: every heredoc that
carried escape sequences arrived with a backslash stripped, and a broken
version of this applier produced three stale-core runs before anyone
noticed the build had been dying at this step. No backslash escapes below:
tabs and newlines are built with chr().
"""
import sys

MARK = "PAPRIUM_WINLOG"
TAB = chr(9)
NL = chr(10)
Q = chr(34)


def main():
    p = sys.argv[1]
    s = open(p, encoding='utf-8', errors='surrogateescape').read()
    if MARK in s:
        raise SystemExit("already applied")

    # 1. switch + writer, next to DEBUG_MODE
    old = "#define DEBUG_MODE 0"
    assert old in s, "DEBUG_MODE"
    s = s.replace(old, old + NL.join([
        "",
        "",
        "/* paprium-pocket: window read logger. See scripts/apply_gpgx_winlog.py. */",
        "#define PAPRIUM_WINLOG 1",
        "#if PAPRIUM_WINLOG",
        "#include <stdio.h>",
        "static FILE *winlog_fp = NULL;",
        "static unsigned int winlog_frames = 0;",
        "static void winlog_raw(unsigned char kind, unsigned char pad, unsigned short address, unsigned int stamp)",
        "{",
        "    unsigned char rec[8];",
        "    if (!winlog_fp) {",
        "        winlog_fp = fopen(" + Q + "paprium_winlog.bin" + Q + ", " + Q + "wb" + Q + ");",
        "        if (!winlog_fp) return;",
        "    }",
        "    rec[0] = kind; rec[1] = pad;",
        "    rec[2] = address & 0xFF; rec[3] = address >> 8;",
        "    rec[4] = stamp & 0xFF; rec[5] = (stamp >> 8) & 0xFF;",
        "    rec[6] = (stamp >> 16) & 0xFF; rec[7] = (stamp >> 24) & 0xFF;",
        "    fwrite(rec, 1, 8, winlog_fp);",
        "}",
        "static void winlog(unsigned char kind, unsigned short address)",
        "{",
        "    winlog_raw(kind, 0, address, (winlog_frames << 16) | (v_counter & 0xFFFF));",
        "}",
        "#endif",
    ]))

    # 2. page turn: right after decoder_ptr advances
    old = NL.join([TAB + TAB + "paprium_s.decoder_ptr += size;",
                   TAB + TAB + "paprium_s.decoder_size -= size;",
                   TAB + "}"])
    assert old in s, "page turn"
    s = s.replace(old, NL.join([TAB + TAB + "paprium_s.decoder_ptr += size;",
                                TAB + TAB + "paprium_s.decoder_size -= size;",
                                "#if PAPRIUM_WINLOG",
                                TAB + TAB + "winlog(2, (unsigned short) size);",
                                "#endif",
                                TAB + "}"]))

    # 3. word reads of the window: the default branch of paprium_r16
    old = NL.join([TAB + "default:",
                   TAB + TAB + "data = *(uint16 *)(paprium_s.ram + address);",
                   TAB + TAB + "break;",
                   TAB + "}"])
    assert old in s, "r16 default"
    s = s.replace(old, NL.join([TAB + "default:",
                                TAB + TAB + "data = *(uint16 *)(paprium_s.ram + address);",
                                "#if PAPRIUM_WINLOG",
                                TAB + TAB + "if (address >= 0xC000) winlog(0, (unsigned short) address);",
                                "#endif",
                                TAB + TAB + "break;",
                                TAB + "}"]))

    # 3b. word reads of the mailbox command/status words through paprium_r16
    old = NL.join([TAB + "switch( address ) {", TAB + "case 0x1FE4:"])
    assert old in s, "r16 switch head"
    s = s.replace(old, NL.join(["#if PAPRIUM_WINLOG",
                                TAB + "if (address == 0x1FEA) winlog(8, 0x1FEA);",
                                TAB + "else if (address == 0x1FE4 || address == 0x1FE6) winlog(9, (unsigned short) address);",
                                "#endif",
                                TAB + "switch( address ) {", TAB + "case 0x1FE4:"]), 1)

    # 4. byte reads of the window, and byte reads of the mailbox words
    old = TAB + "int data = paprium_s.ram[address^1];"
    assert s.count(old) == 1, ("r8", s.count(old))
    s = s.replace(old, NL.join([old,
                                "#if PAPRIUM_WINLOG",
                                TAB + "if (address >= 0xC000) winlog(1, (unsigned short) address);",
                                TAB + "else if (address >= 0x1FE4 && address <= 0x1FEB) winlog(9, (unsigned short) address);",
                                "#endif"]))

    # 5. the commands: paprium_cmd(int data) derives cmd = data >> 8 first
    old = NL.join(["static void paprium_cmd(int data)", "{", TAB + "int cmd = data >> 8;"])
    assert old in s, "paprium_cmd head"
    s = s.replace(old, old + NL + NL.join([
        "#if PAPRIUM_WINLOG",
        TAB + "{",
        TAB + TAB + "unsigned int pc = m68k.pc;",
        TAB + TAB + "unsigned short off = *(uint16 *)(paprium_s.ram + 0x1E12);",
        TAB + TAB + "unsigned short sz  = *(uint16 *)(paprium_s.ram + 0x1E14);",
        TAB + TAB + "unsigned int stamp = (winlog_frames << 16) | (v_counter & 0xFFFF);",
        TAB + TAB + "if (cmd == 0xDB) { winlog_raw(3, (unsigned char)(sz >> 6), off, stamp); winlog_raw(10, (pc >> 16) & 0xFF, (unsigned short)(pc & 0xFFFF), stamp); }",
        TAB + TAB + "else if (cmd == 0xDA) winlog_raw(4, 0, (unsigned short)(data & 0xFF), stamp);",
        TAB + TAB + "else if (cmd == 0xAF) winlog_raw(5, 0, 0, stamp);",
        TAB + TAB + "else if (cmd == 0xAE) winlog_raw(11, 0, 0, stamp);",
        TAB + "}",
        "#endif",
    ]), 1)

    # 6. frame counter: paprium_audio(int cycles) runs once per frame's audio step
    old = NL.join(["void paprium_audio(int cycles)", "{"])
    assert old in s, "paprium_audio"
    s = s.replace(old, old + NL + NL.join(["#if PAPRIUM_WINLOG", TAB + "winlog_frames++;", "#endif"]), 1)

    open(p, 'w', encoding='utf-8', errors='surrogateescape').write(s)
    print("applied to", p)


if __name__ == '__main__':
    main()
