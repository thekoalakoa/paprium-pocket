/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/s1_trap.S - the one trap entry of the new-core firmware (docs/MCU_INTERFACE.md section 6).
 *
 * mtvec (direct mode) points here for every interrupt and exception; it sits in the IROM (rule 6.3.6).
 * Frame: 16 caller-saved registers + mepc + mstatus + mie = 76 bytes in an 80-byte frame (16-byte aligned stack).
 * Levels (MEI > MTI > MSI; NEORV32 1.4.8.1 clears MIE on entry, so nesting is software):
 *   MEI 11 -> l1_mei(), interrupts off throughout;
 *   MTI  7 -> l2a_mti() with mie = the saved enables & MEI, MIE on;
 *   MSI  3 -> l2b_msi() with mie = the saved enables & (MEI | MTI), MIE on;
 *   other interrupt (a FIRQ: none is enabled in v1.0) -> its enable is cleared in the saved mie;
 *   exception -> sched_exception(mcause, mepc, mtval) returns where to resume.
 * The brain-call abort (buddy/s1_glue.c): after L1, L2a or L2b, while s1_brain_abort is set,
 * s1_brain_resume(mepc) says where the interrupted code resumes: buddy_abort_land when that code is the call itself
 * (the brain, its helpers, the wrapper: the thread's since an earlier scheduler change, so L2b can interrupt it too),
 * else mepc (a level nested deeper returns as usual; its own caller's exit asks again). Two loads and a branch on
 * every exit otherwise.
 * On the way out mie is written back from the frame: the level's own line goes from off to on, which drops a request
 * the CPU latched before the source was acknowledged (rule 6.3.3); for MEI the line is switched off first here, since
 * L1 runs without touching mie. mepc and mstatus come back from the frame, so a nested trap (which overwrites both) can
 * never make a level return to the wrong place or with interrupts in the wrong state.
 * Callee-saved registers, gp and tp are left alone (C saves s0-s11; nothing writes gp; the brain's tp is its own). */
#include "s1_boot.h"

    .section .text.s1_trap_entry,"ax",@progbits
    .globl  s1_trap_entry
    .balign 4
s1_trap_entry:
    addi    sp, sp, -80
    sw      ra,  0(sp)
    sw      t0,  4(sp)
    sw      t1,  8(sp)
    sw      t2, 12(sp)
    sw      a0, 16(sp)
    sw      a1, 20(sp)
    sw      a2, 24(sp)
    sw      a3, 28(sp)
    sw      a4, 32(sp)
    sw      a5, 36(sp)
    sw      a6, 40(sp)
    sw      a7, 44(sp)
    sw      t3, 48(sp)
    sw      t4, 52(sp)
    sw      t5, 56(sp)
    sw      t6, 60(sp)
    csrr    t0, mepc
    sw      t0, 64(sp)
    csrr    t0, mstatus
    sw      t0, 68(sp)
    csrr    t2, mie
    sw      t2, 72(sp)
    csrr    a0, mcause
    bgez    a0, .Lexc
    andi    t0, a0, 31
    li      t1, S1_A_IRQ_MEI
    beq     t0, t1, .Lmei
    li      t1, S1_A_IRQ_MTI
    beq     t0, t1, .Lmti
    li      t1, S1_A_IRQ_MSI
    beq     t0, t1, .Lmsi
    li      t1, 1                   /* another interrupt: keep its enable off from now on */
    sll     t1, t1, t0
    not     t1, t1
    and     t2, t2, t1
    sw      t2, 72(sp)
    j       .Lout
.Lmei:
    call    l1_mei
    li      t0, S1_A_MIE_MEIE
    csrc    mie, t0
    j       .Lres
.Lmti:
    li      t0, S1_A_MIE_MEIE
    and     t0, t2, t0
    csrw    mie, t0
    csrsi   mstatus, 8
    call    l2a_mti
    csrci   mstatus, 8
.Lres:
    lui     t1, %hi(s1_brain_abort)
    lw      t0, %lo(s1_brain_abort)(t1)
    beqz    t0, .Lout
    lw      a0, 64(sp)
    call    s1_brain_resume
    sw      a0, 64(sp)
    j       .Lout
.Lmsi:
    li      t0, S1_A_MIE_MEIE | S1_A_MIE_MTIE
    and     t0, t2, t0
    csrw    mie, t0
    csrsi   mstatus, 8
    call    l2b_msi
    csrci   mstatus, 8
    j       .Lres
.Lexc:
    lw      a1, 64(sp)
    csrr    a2, mtval
    call    sched_exception
    sw      a0, 64(sp)
.Lout:
    lw      t0, 72(sp)
    csrw    mie, t0
    lw      t0, 64(sp)
    csrw    mepc, t0
    lw      t0, 68(sp)
    csrw    mstatus, t0
    lw      ra,  0(sp)
    lw      t0,  4(sp)
    lw      t1,  8(sp)
    lw      t2, 12(sp)
    lw      a0, 16(sp)
    lw      a1, 20(sp)
    lw      a2, 24(sp)
    lw      a3, 28(sp)
    lw      a4, 32(sp)
    lw      a5, 36(sp)
    lw      a6, 40(sp)
    lw      a7, 44(sp)
    lw      t3, 48(sp)
    lw      t4, 52(sp)
    lw      t5, 56(sp)
    lw      t6, 60(sp)
    addi    sp, sp, 80
    mret
