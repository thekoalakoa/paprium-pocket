/* Copyright (C) 2026 Marsupial Solutions LLC
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * board/pocket/fafrium/fafrium_stub.S - the boot stub the bitstream carries for Fafrium, the cart firmware file
 * (docs/FAFRIUM.md).
 *
 * From 0.3.0 the cart MCU's firmware is not compiled into the bitstream. The bitstream's IROM image is this stub at
 * 0x0 and nothing else; its WRAM image is all zero. The firmware arrives as one file, Fafrium (the IROM image, the
 * initialised WRAM window and the MegaWire SRAM code, docs/FAFRIUM.md), through one APF data slot that the ROM loader
 * puts at SDRAM byte 0x0100_0000 (cartridge.sv); the MCU reads it through the boot view 0x0380_0000-0x0387_FFFF
 * (paprium_mcu_mem, open until the cart reset after GO): the file in the first 256 KB, scratch after it.
 *
 * The stub uses registers and one WRAM stash (WRAM 0x8000_0000 .. +STUB_LEN: never locked and zero in every image;
 * the finisher zeroes it again), no stack, so every RAM byte it does not copy keeps its bitstream value (0), as in a
 * bitstream with the firmware built in. The 68000 stays held the whole time (CTRL.HOLD is the reset value; the stub
 * never writes CTRL).
 *   1. The header. First the magic. Then the length of the load: the core keeps a length mark (XLINK FAFRIUM, see
 *      XL_FAF below) that, for a file up to 32 MB, reads 0 only when the slot's last load ended exactly at byte
 *      256 KB. So a shorter or a longer file is refused whatever the window held before, even when a longer file's
 *      extra bytes repeat its own first bytes. (The core sees a word's offset modulo 32 MB, so a file of 256 KB plus
 *      a multiple of 32 MB is not caught here; see docs/FAFRIUM.md.) Then the header CRC-32, the format version and
 *      header length, the reserved words 0x54-0x7B (they must be zero), the file length, the layout, the section
 *      table and the end word, the file's last word. Last come the words that must match this bitstream: the
 *      firmware epoch, the MCU interface version, the FEAT word and the clock. Any mismatch: refuse.
 *   2. one pass over the rest of the file, in file order: the CRC-32 of every word, each word stored as it is read:
 *      payload IROM [0, STUB_LEN) (this stub's own place) into the WRAM stash, IROM [STUB_LEN, 0x16000) and the WRAM
 *      window 0x8000_2C00-0x8000_ABFF in place (the IROM takes word stores and the code window is open until GO), the
 *      MegaWire SRAM code into the Pocket SRAM at 0x0800_0000 (its own length, at most 64 KB). The zero fill and the
 *      end word come last and only go into the CRC. The stub refuses the file when the payload CRC is wrong or when a
 *      zero-fill byte is not zero. What it has written by then is harmless: nothing runs it, the MCU stays in the
 *      stub, and a good file writes all of it again. So every byte in the 256 KB window is checked. The kind and
 *      build words are information only (the kind word also carries the firmware version), and the header CRC covers
 *      them.
 *   3. the finisher (fin_begin .. fin_end, written by this stub into the boot view's scratch, past the file) moves
 *      the stash into IROM [0, STUB_LEN) and zeroes the stash, so every byte placed is a byte the payload CRC saw;
 *      then it zeroes the file's magic and end word in SDRAM, so the window no longer holds a whole file; it clears
 *      x1-x31 and stores GO (a byte at 0x7FF). From the next clock core_top holds the cart in reset, restarts the
 *      APF-load reset envelope, and the MCU starts the firmware's own crt0 from that reset, with IROM, WRAM and the
 *      bus map exactly as a bitstream with the firmware built in has them.
 *      The finisher's first IROM store sets mcu_core's fw_fin_q: a reset of the MCU from then until GO (a new load in
 *      that window) holds the MCU in reset until a bitstream load (fw_hold_q), so a half-written IROM never runs. A
 *      reset before that store finds this stub and the file's magic intact, and the stub runs again from the start.
 * Refusal: the 68000 stays held, nothing of the firmware runs, and the screen goes plain red (255, 0, 0), steady,
 * with no text: the stub keeps XLINK BAR at EN | PX 2047, the value paprium_holdvid draws as the refusal screen
 * (the firmware's own bar never reaches 2047). It stores it again and again, so a Soft Reset, which clears BAR, leaves
 * it dark only while the reset lasts (a store into XLINK held in reset faults; the trap vector points back into the
 * loop, so the stub neither restarts nor stops). The reason for the refusal stays in register a0:
 *   1  no file: the magic is missing
 *   2  the header is damaged: its CRC is wrong
 *   3  another format version or header length
 *   4  not this file's layout: a load that was not exactly 256 KB, a reserved word or a zero-fill byte that is not
 *      zero, another file length, layout or section table, or no end word
 *   5  another version: the epoch, the MCU interface, FEAT or the clock does not match this bitstream
 *   6  the payload is damaged: its CRC is wrong
 * A new load (the stub then runs again on the new file) or a bitstream load is the only way out.
 */
    .equ FW,        0x03800000      /* boot view: the file (FLEN bytes) */
    .equ SCR,       0x03840000      /* boot view: scratch past the file */
    .equ FLEN,      0x40000         /* the file is exactly 256 KB, the size of the loader's window */
    .equ HLEN,      0x80
    .equ IROM_LEN,  0x16000         /* 88 KB */
    .equ W_DST,     0x80002C00
    .equ W_LEN,     0x8000
    .equ S_DST,     0x08000000      /* the Pocket SRAM (xram) */
    .equ S_MAX,     0x10000
    .equ S_OFF,     HLEN + IROM_LEN + W_LEN
    .equ STUB_LEN,  0x800           /* IROM [0, STUB_LEN) holds this stub (mkfafrium.py checks it fits) */
    .equ STASH,     0x80000000      /* WRAM KB 0-1: payload IROM [0, STUB_LEN) waits here for the finisher */
    .equ MAGIC,     0x52464146      /* 'F' 'A' 'F' 'R' */
    .equ ENDW,      0x444E4546      /* 'F' 'E' 'N' 'D': the file's last word */
    .equ HVER,      0x00800001      /* format version 1, header length 0x80 */
    .equ LAYOUT,    0x00583001      /* IROM 88 KB, WRAM 48 KB, platform 1 = Analogue Pocket */
    .equ EPOCH,     0x46410001      /* this bitstream's firmware epoch ('F' 'A', 1): changed with the RTL */
    .equ IFACE,     0x50490103      /* MCU interface v1.3 (mcu_core IFACE_ID) */
    .equ FEAT,      0x00580047      /* FPGAIO FEAT of this bitstream (core_top PAPRIUM_FEAT) */
    .equ CLKHZ,     53693175        /* core_top CLK_HZ */
    .equ XLINK,     0x0A000000      /* XLINK: the core's register block for its external memories */
    .equ BAR,       XLINK + 0x48    /* XLINK BAR, the loading bar: bit 31 = EN, bits 10-0 = PX */
    .equ XL_FAF,    XLINK + 0x4C    /* XLINK FAFRIUM (read only): bit 0 = 1 unless the last load was exactly 256 KB */
    .equ BAR_RED,   0x800007FF      /* EN | PX 2047: paprium_holdvid's refusal screen */

/* a3 = CRC-32 (reflected, poly 0xEDB88320) state after the word \w (little-endian bytes): crc ^= w; 4 x byte step */
.macro CRCW w
    xor     a3, a3, \w
    .rept   4
    andi    t1, a3, 0xFF
    slli    t1, t1, 2
    add     t1, t1, s5
    lw      t1, 0(t1)
    srli    a3, a3, 8
    xor     a3, a3, t1
    .endr
.endm

/* refuse with code \c unless \a == \b */
.macro CHK a, b, c
    li      a0, \c
    bne     \a, \b, refuse
.endm

    .section .text
    .globl  _start
_start:
    li      s0, FW
    la      s5, crc_tab
    /* 1: a file at all */
    lw      t0, 0(s0)
    li      t2, MAGIC
    CHK     t0, t2, 1
    /* 4: refuse a load that was not exactly 256 KB. A longer load's bytes past 256 KB wrapped onto the start of
       the window, and a shorter one left older bytes after its own, so only the core's length mark can show it */
    li      t0, XLINK
    lw      t0, XL_FAF - XLINK(t0)
    CHK     t0, zero, 4
    /* 2: the header CRC over bytes 0x00-0x7B, with no stores. The run stops at 0x54 once, so that the reserved
       words 0x54-0x7B are OR-ed into s7 on the way */
    li      a3, -1
    mv      s1, s0
    addi    s4, s0, 0x54
    li      s8, 1
    jal     ra, crcrun
    li      s7, 0
    addi    s4, s0, 0x7C
    jal     ra, crcrun
    not     a3, a3
    lw      t0, 0x7C(s0)
    CHK     a3, t0, 2
    /* 3: format version and header length */
    lw      t0, 0x04(s0)
    li      t2, HVER
    CHK     t0, t2, 3
    /* 4: the reserved words must be zero (s7 holds them OR-ed together). Then the file length, the layout, the
       section count and the section table. The SRAM code's length must be 4-aligned and at most S_MAX */
    CHK     s7, zero, 4
    lw      t0, 0x08(s0)
    li      t2, FLEN
    CHK     t0, t2, 4
    lw      t0, 0x0C(s0)
    li      t2, LAYOUT
    CHK     t0, t2, 4
    lw      t0, 0x28(s0)
    li      t2, 3
    CHK     t0, t2, 4
    lui     t0, FLEN >> 12              /* the end word, the file's last word */
    add     t0, t0, s0
    lw      t0, -4(t0)
    li      t2, ENDW
    CHK     t0, t2, 4
    la      s1, sect_tab
    addi    s2, s0, 0x30
    addi    s3, s1, 28
2:  lw      t0, 0(s1)
    lw      t2, 0(s2)
    CHK     t0, t2, 4
    addi    s1, s1, 4
    addi    s2, s2, 4
    bltu    s1, s3, 2b
    lw      t0, 0x50(s0)
    li      t2, S_OFF
    CHK     t0, t2, 4
    lw      s9, 0x4C(s0)
    andi    t0, s9, 3
    CHK     t0, zero, 4
    li      t2, S_MAX
    bltu    t2, s9, refuse
    /* 5: the version words tied to this bitstream */
    lw      t0, 0x10(s0)
    li      t2, EPOCH
    CHK     t0, t2, 5
    lw      t0, 0x14(s0)
    li      t2, IFACE
    CHK     t0, t2, 5
    lw      t0, 0x18(s0)
    li      t2, FEAT
    CHK     t0, t2, 5
    lw      t0, 0x1C(s0)
    li      t2, CLKHZ
    CHK     t0, t2, 5
    /* the payload: one pass in file order, the CRC of every word, every section word stored */
    li      a3, -1
    addi    s1, s0, HLEN
    li      s8, 0
    li      s2, STASH                   /* IROM [0, STUB_LEN): kept in the stash for the finisher */
    li      s4, FW + HLEN + STUB_LEN
    jal     ra, crcrun
    li      s2, STUB_LEN                /* IROM [STUB_LEN, 0x16000) */
    li      s4, FW + HLEN + IROM_LEN
    jal     ra, crcrun
    li      s2, W_DST                   /* WRAM 0x8000_2C00-0x8000_ABFF */
    li      s4, FW + S_OFF
    jal     ra, crcrun
    li      s2, S_DST                   /* the MegaWire SRAM code: its own length */
    add     s4, s1, s9
    jal     ra, crcrun
    li      s8, 1                       /* the zero fill only goes into the CRC; crcrun ORs it into s7, still 0 */
    li      s4, FW + FLEN - 4
    jal     ra, crcrun
    mv      a4, s7
    li      s4, FW + FLEN               /* the end word, checked with the header: here only into the CRC */
    jal     ra, crcrun
    not     a3, a3
    lw      t0, 0x2C(s0)
    CHK     a3, t0, 6
    CHK     a4, zero, 4                 /* a fill byte not zero: 4. After the CRC, so a damaged fill byte gives 6 */
    /* the finisher into the scratch (written there from this stub, so it is the bitstream's code), then run it */
    la      s1, fin_begin
    la      s3, fin_end
    li      s2, SCR
6:  lw      t0, 0(s1)
    sw      t0, 0(s2)
    addi    s1, s1, 4
    addi    s2, s2, 4
    bltu    s1, s3, 6b
    li      s1, STASH                   /* the finisher's work: the stash -> IROM [0, STUB_LEN), the stash zeroed */
    li      s2, 0
    li      s3, STUB_LEN
    li      t0, SCR
    jr      t0

    .balign 4
fin_begin:                              /* runs at SCR (position-independent) */
7:  lw      t0, 0(s1)
    sw      t0, 0(s2)                   /* the first one sets mcu_core's fw_fin_q */
    sw      zero, 0(s1)
    addi    s1, s1, 4
    addi    s2, s2, 4
    bltu    s2, s3, 7b
    sw      zero, 0(s0)                 /* the file's magic and end word: the window no longer holds a whole file */
    lui     t0, FLEN >> 12
    add     t0, t0, s0
    sw      zero, -4(t0)
    lw      t0, 0(s0)                   /* the zeroed magic (port 2's read register ends at 0) */
    .irp    r, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31
    addi    x\r, x0, 0
    .endr
    sb      x0, 0x7FF(x0)               /* GO */
8:  j       8b                          /* never runs a turn: the cart is in reset from the next clock */
    .word   0, 0, 0, 0
fin_end:

/* crcrun: for each word from s1 (in the file) up to s4, update the CRC state in a3. When s8 is 0, store the word
   at s2. When s8 is not 0, OR the word into s7 instead. s1 and s2 move on by 4 each word. It uses t0 and t1, returns
   through ra (there is no stack) and does nothing when s1 >= s4. The OR is on a side path, so a stored word runs the
   same few instructions as always: lw, the four CRC steps, bnez, sw, addi, addi, bltu */
crcrun:
    bgeu    s1, s4, 3f
1:  lw      t0, 0(s1)
    CRCW    t0
    bnez    s8, 5f
    sw      t0, 0(s2)
4:  addi    s1, s1, 4
    addi    s2, s2, 4
    bltu    s1, s4, 1b
3:  ret
5:  or      s7, s7, t0
    j       4b

refuse:                                 /* a0 = the code (1-6): the plain red screen, kept */
    la      t0, 9f                      /* a store that faults comes back into the loop: a Soft Reset holds XLINK in */
    csrw    mtvec, t0                   /* reset, the store times out, and the trap returns here, not to _start */
    li      s4, BAR
    li      s6, BAR_RED
9:  sw      s6, 0(s4)
    j       9b

    .balign 4
sect_tab:                               /* the only layout this bitstream takes: {dest, length, file offset} ... */
    .word   0x00000000, IROM_LEN, HLEN
    .word   W_DST, W_LEN, HLEN + IROM_LEN
    .word   S_DST                       /* ... then the SRAM code's dest; its length and offset are checked above */

    .balign 4
crc_tab:
    .include "crc_tab.inc"
stub_end:
