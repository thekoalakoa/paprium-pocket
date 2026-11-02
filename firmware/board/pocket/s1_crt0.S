/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/s1_crt0.S - the new-core start-up code (docs/BOOT_SPEC.md step P1; docs/MCU_INTERFACE.md 1, 7, 8).
 *
 * Replaces the NEORV32 crt0 of 0.2.6 for the s1 images (the new-core source set) only. Differences, each on purpose:
 *   - no IO sweep: 0.2.6 zeroed 0xFFFFFF80-0xFFFFFFFC and relied on a dummy handler to skip the faults of the units
 *     that are not built; v1.0 removes MTIME, UART and WDT (a store there is a bus-timeout fault), so only the
 *     implemented IO is touched, by the board code;
 *   - mtvec = the one trap entry (s1_trap.S) from the first instruction; the 0.2.6 dummy handler (which swaps s0 and
 *     s1 on every trap it takes) is not linked;
 *   - the 68000 hold is written first (CTRL resets to 0x09 on every reset in v1.0; a firmware restart arrives here
 *     with HOLD already set), then the interface checks, before any RAM is written: NEORV32 SYSINFO_CLK must equal
 *     BRD_CLK_HZ and USER_CODE must be MCU interface v1.(>= ours). On a mismatch the stop code goes to the boot record
 *     and the MCU stops with the 68000 held. (A pocket72k image on a 0.2.6 bitstream reads USER_CODE 0 and stops
 *     here, before its 48 KB layout could corrupt the 32 KB WRAM.) Test build 4b's images, built with S1_CACHE4B
 *     (s1_boot.h), are v1.3 images: they also read FEAT (FPGAIO slot 23) and stop (code S1_STOP_FEAT) unless the
 *     bitstream carries every block they drive (the cache slot, the bar, the interim FIFOs, the MD+ block) and at least
 *     their 72 KB of IROM (MCU_INTERFACE.md 1 rule 2, 4.10). Only registers and the boot record are used up to here: no
 *     stack, no .data;
 *   - S1_CACHE4B (test build 4b on): then the boot-cache stub (board/pocket/boot/boot_cache.c boot_cache_boot, with the
 *   .noinit record
 *     c4b_rec) on the stack, before .data and .bss exist: it touches nothing on a warm boot (CACHE.VALID) and else
 *     enters the WRAM boot overlay, which lives where .bss_upper is about to be cleared (board/pocket/boot/c4b.h);
 *   - .data copied and .bss cleared bytewise (as 0.2.6), the wram_upper .bss (.bss_upper) cleared a word at a time;
 *     TEST: the stack is filled with S1_STACK_FILL;
 *   - the cycle counters cleared, then the board boot (s1_board.c brd_boot), which never returns. */
#include "s1_boot.h"

    .section .text.boot,"ax",@progbits
    .globl  _start
    .balign 4
_start:
    /* registers cleared (as 0.2.6's crt0): the same start state after a firmware restart, and no undefined value
       reaching memory through a trap frame in an RTL simulation (measured: GHDL showed 20 'X' stack words without) */
    .irp    r, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31
    addi    x\r, x0, 0
    .endr
    csrw    mie, zero
    li      t0, 0x1800              /* mstatus: MPP = machine, MIE = 0 */
    csrw    mstatus, t0
    la      t0, s1_trap_entry
    csrw    mtvec, t0
.option push
.option norelax
    lui     sp, %hi(__crt0_stack_begin)     /* absolute, not pc-relative: tools/fwstack.py counts the low part */
    addi    sp, sp, %lo(__crt0_stack_begin) /* as a frame (4 B here, wherever crt0 sits) */
    la      gp, __global_pointer$
.option pop
    li      t0, S1_A_FIO_CTRL       /* hold the 68000: CTRL byte 0 read-modify-write */
    lw      t1, 0(t0)
    andi    t1, t1, 0xFF
    ori     t1, t1, S1_A_CTRL_HOLD
    sw      t1, 0(t0)
    li      t0, S1_A_SYSINFO_CLK    /* the clock this image was built for */
    lw      a1, 0(t0)
    li      t1, BRD_CLK_HZ
    li      a0, S1_STOP_CLOCK
    bne     a1, t1, .Lstop
    lw      a1, 4(t0)               /* the MCU interface: same major, minor >= ours */
    srli    t1, a1, 8
    li      t2, S1_A_IFACE_PI_MAJOR
    li      a0, S1_STOP_IFACE
    bne     t1, t2, .Lstop
    andi    t1, a1, 0xFF
    li      t2, S1_A_IFACE_MINOR
    bltu    t1, t2, .Lstop
#if S1_CACHE4B
    li      t0, S1_A_FIO_FEAT       /* v1.3 rule 2 (MCU_INTERFACE.md 1): every block this image drives, and the IROM */
    lw      a1, 0(t0)
    li      a0, S1_STOP_FEAT
    andi    t1, a1, S1_A_FEAT_NEED
    li      t2, S1_A_FEAT_NEED
    bne     t1, t2, .Lstop
    srli    t1, a1, 16
    andi    t1, t1, 0xFF
    li      t2, S1_A_FEAT_IROM_KB
    bltu    t1, t2, .Lstop
    la      a0, c4b_rec                 /* test build 4b: the sound cache (warm: nothing; else the
                                           overlay), 68000 held */
    call    boot_cache_boot
#endif
    la      a0, __crt0_copy_data_src_begin
    la      a1, __crt0_copy_data_dst_begin
    la      a2, __crt0_copy_data_dst_end
1:  bgeu    a1, a2, 2f
    lbu     t0, 0(a0)
    sb      t0, 0(a1)
    addi    a0, a0, 1
    addi    a1, a1, 1
    j       1b
2:  la      a0, __crt0_bss_start
    la      a1, __crt0_bss_end
3:  bgeu    a0, a1, 4f
    sb      zero, 0(a0)
    addi    a0, a0, 1
    j       3b
4:  la      a0, __crt0_upper_bss_start  /* word-aligned at both ends (the linker script asserts it) */
    la      a1, __crt0_upper_bss_end
5:  bgeu    a0, a1, 6f
    sw      zero, 0(a0)
    addi    a0, a0, 4
    j       5b
6:
#if !PPM_RELEASE
    la      a0, __stack_floor
    li      t0, S1_STACK_FILL
7:  bgeu    a0, sp, 8f
    sw      t0, 0(a0)
    addi    a0, a0, 4
    j       7b
8:
#endif
    csrw    mcycle, zero
    csrw    mcycleh, zero
    csrw    minstret, zero
    csrw    minstreth, zero
    call    brd_boot
.Lstop:                             /* a0 = the stop code, a1 = the word that did not match */
    la      t0, s1_boot_rec
    li      t1, S1_REC_MAGIC
    sw      t1, 0(t0)
    sw      a0, 4(t0)
    sw      zero, 8(t0)
    sw      a1, 12(t0)
9:  j       9b
