/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * zz_buddy_trap.c - trap entry and brain-call wrapper of the CPU MATE buddy (file-scope assembly in a .c file, so
 * the core repository's build_mcu.sh, which compiles *.c only, builds it unchanged). It was first written for a
 * 0.2.6 test firmware.
 *
 * buddy_trap is mtvec only while a brain call runs (zz_buddy.c run_call); everywhere else mtvec is crt0's
 * __crt0_dummy_trap_handler, as today.
 *   - interrupts: MEI (the machine external interrupt, cause 11: the mailbox latch) -> buddy_isr_post(); MTI (the
 *     machine timer interrupt, cause 7) -> buddy_isr_tick().
 *     mepc and mstatus are saved in the frame and written back before mret, so a nested exception inside a
 *     handler (its mret clobbers MPIE / mepc) cannot leave interrupts off or return to the wrong place.
 *   - an abort request (restart / AI off while a call is in flight, or an exception in brain code) turns the
 *     return into a jump to buddy_abort_land, which unwinds to buddy_call_brain's frame and returns 1.
 *   - an exception in firmware code: every register restored, then crt0's dummy handler, exactly today's path.
 * Frame: 16 caller-saved registers + mepc + mstatus = 72 bytes (80 reserved, 16-byte aligned).
 * The brain is entered with the RV ABI: ra, sp, gp, tp and s0-s11 are restored by the wrapper (the counter build
 * keeps its accumulator in tp and saves it itself; the wrapper restores it anyway, for the abort path).
 */
#include <stdint.h>

/* The linked brain: with the glue in the WRAM code window, crt0's dummy handler (IROM) is out of `j` reach (1 MB): the
   firmware-exception path goes through this 8-byte trampoline, which stays in the IROM (section .text.buddy_tramp);
   t0 rides in mscratch (the firmware does not use mscratch) */
#ifndef BUDDY_TRAP_TRAMP
#define BUDDY_TRAP_TRAMP 0
#endif
#if BUDDY_TRAP_TRAMP && !FW_S1
__asm__(
"    .section .text.buddy_tramp,\"ax\",@progbits\n"
"    .globl buddy_fw_tramp\n"
"    .balign 4\n"
"buddy_fw_tramp:\n"
"    csrrw t0, mscratch, t0\n"
"    j     __crt0_dummy_trap_handler\n"
"    .text\n"
);
#endif

__attribute__((section(".noinit.zz_buddy"))) volatile uint32_t buddy_jmp_sp;
__attribute__((section(".noinit.zz_buddy"))) volatile uint32_t buddy_abort_req;
__attribute__((section(".noinit.zz_buddy"))) volatile uint32_t buddy_code_lo;
__attribute__((section(".noinit.zz_buddy"))) volatile uint32_t buddy_code_hi;

/* The new firmware (FW_S1) links only the call wrapper below: the one trap entry is board/pocket/s1_trap.S, and the
   abort landing is reached through its exit (buddy/s1_glue.c) */
__asm__(
#if !FW_S1
"    .section .text.zz_buddy_trap,\"ax\",@progbits\n"
"    .globl buddy_trap\n"
"    .balign 4\n"
"buddy_trap:\n"
"    addi  sp, sp, -80\n"
"    sw    ra,  0(sp)\n"
"    sw    t0,  4(sp)\n"
"    sw    t1,  8(sp)\n"
"    sw    t2, 12(sp)\n"
"    sw    a0, 16(sp)\n"
"    sw    a1, 20(sp)\n"
"    sw    a2, 24(sp)\n"
"    sw    a3, 28(sp)\n"
"    sw    a4, 32(sp)\n"
"    sw    a5, 36(sp)\n"
"    sw    a6, 40(sp)\n"
"    sw    a7, 44(sp)\n"
"    sw    t3, 48(sp)\n"
"    sw    t4, 52(sp)\n"
"    sw    t5, 56(sp)\n"
"    sw    t6, 60(sp)\n"
"    csrr  t0, mepc\n"
"    sw    t0, 64(sp)\n"
"    csrr  t1, mstatus\n"
"    sw    t1, 68(sp)\n"
"    csrr  t0, mcause\n"
"    bgez  t0, .Lbt_exc\n"
"    andi  t0, t0, 31\n"
"    li    t1, 11\n"
"    beq   t0, t1, .Lbt_mei\n"
"    li    t1, 7\n"
"    beq   t0, t1, .Lbt_mti\n"
"    j     .Lbt_out\n"
".Lbt_mei:\n"
"    call  buddy_isr_post\n"
"    j     .Lbt_out\n"
".Lbt_mti:\n"
"    call  buddy_isr_tick\n"
".Lbt_out:\n"
"    lw    t0, 64(sp)\n"
"    csrw  mepc, t0\n"
"    lw    t0, 68(sp)\n"
"    csrw  mstatus, t0\n"
"    lui   t1, %hi(buddy_abort_req)\n"
"    lw    t0, %lo(buddy_abort_req)(t1)\n"
"    beqz  t0, 1f\n"
"    lui   t1, %hi(buddy_jmp_sp)\n"
"    lw    t0, %lo(buddy_jmp_sp)(t1)\n"
"    beqz  t0, 1f\n"
"    lui   t0, %hi(buddy_abort_land)\n"
"    addi  t0, t0, %lo(buddy_abort_land)\n"
"    csrw  mepc, t0\n"
"1:\n"
"    lw    ra,  0(sp)\n"
"    lw    t0,  4(sp)\n"
"    lw    t1,  8(sp)\n"
"    lw    t2, 12(sp)\n"
"    lw    a0, 16(sp)\n"
"    lw    a1, 20(sp)\n"
"    lw    a2, 24(sp)\n"
"    lw    a3, 28(sp)\n"
"    lw    a4, 32(sp)\n"
"    lw    a5, 36(sp)\n"
"    lw    a6, 40(sp)\n"
"    lw    a7, 44(sp)\n"
"    lw    t3, 48(sp)\n"
"    lw    t4, 52(sp)\n"
"    lw    t5, 56(sp)\n"
"    lw    t6, 60(sp)\n"
"    addi  sp, sp, 80\n"
"    mret\n"
/* exception: in brain code while a call is in flight -> abort + disable; anything else -> today's handler */
".Lbt_exc:\n"
"    lw    t0, 64(sp)\n"
"    lui   t1, %hi(buddy_jmp_sp)\n"
"    lw    t1, %lo(buddy_jmp_sp)(t1)\n"
"    beqz  t1, .Lbt_fw\n"
"    lui   t1, %hi(buddy_code_lo)\n"
"    lw    t1, %lo(buddy_code_lo)(t1)\n"
"    bltu  t0, t1, .Lbt_fw\n"
"    lui   t1, %hi(buddy_code_hi)\n"
"    lw    t1, %lo(buddy_code_hi)(t1)\n"
"    bgeu  t0, t1, .Lbt_fw\n"
"    call  buddy_exc_brain\n"
"    j     .Lbt_out\n"
".Lbt_fw:\n"
"    lw    ra,  0(sp)\n"
"    lw    t0,  4(sp)\n"
#if BUDDY_TRAP_TRAMP
"    csrw  mscratch, t0\n"
#endif
"    lw    t1,  8(sp)\n"
"    lw    t2, 12(sp)\n"
"    lw    a0, 16(sp)\n"
"    lw    a1, 20(sp)\n"
"    lw    a2, 24(sp)\n"
"    lw    a3, 28(sp)\n"
"    lw    a4, 32(sp)\n"
"    lw    a5, 36(sp)\n"
"    lw    a6, 40(sp)\n"
"    lw    a7, 44(sp)\n"
"    lw    t3, 48(sp)\n"
"    lw    t4, 52(sp)\n"
"    lw    t5, 56(sp)\n"
"    lw    t6, 60(sp)\n"
"    addi  sp, sp, 80\n"
#if BUDDY_TRAP_TRAMP
"    lui   t0, %hi(buddy_fw_tramp)\n"
"    addi  t0, t0, %lo(buddy_fw_tramp)\n"
"    jr    t0\n"
#else
"    j     __crt0_dummy_trap_handler\n"
#endif
"\n"
#endif
/* uint32_t buddy_call_brain(uint32_t h2, uint32_t h1, uint32_t *word): H2 then H1; 0 = done, 1 = aborted */
"    .section .text.zz_buddy_call,\"ax\",@progbits\n"
"    .globl buddy_call_brain\n"
"    .globl buddy_abort_land\n"
"    .balign 4\n"
"buddy_call_brain:\n"
"    addi  sp, sp, -64\n"
"    sw    ra,  0(sp)\n"
"    sw    s0,  4(sp)\n"
"    sw    s1,  8(sp)\n"
"    sw    s2, 12(sp)\n"
"    sw    s3, 16(sp)\n"
"    sw    s4, 20(sp)\n"
"    sw    s5, 24(sp)\n"
"    sw    s6, 28(sp)\n"
"    sw    s7, 32(sp)\n"
"    sw    s8, 36(sp)\n"
"    sw    s9, 40(sp)\n"
"    sw    s10, 44(sp)\n"
"    sw    s11, 48(sp)\n"
"    sw    tp, 52(sp)\n"
"    sw    gp, 56(sp)\n"
"    mv    s0, a1\n"
"    mv    s1, a2\n"
"    lui   t0, %hi(buddy_jmp_sp)\n"
"    sw    sp, %lo(buddy_jmp_sp)(t0)\n"
"    jalr  ra, 0(a0)\n"
"    jalr  ra, 0(s0)\n"
"    sw    a0, 0(s1)\n"
"    lui   t0, %hi(buddy_jmp_sp)\n"
"    sw    zero, %lo(buddy_jmp_sp)(t0)\n"
"    li    a0, 0\n"
".Lcb_ret:\n"
"    lw    ra,  0(sp)\n"
"    lw    s0,  4(sp)\n"
"    lw    s1,  8(sp)\n"
"    lw    s2, 12(sp)\n"
"    lw    s3, 16(sp)\n"
"    lw    s4, 20(sp)\n"
"    lw    s5, 24(sp)\n"
"    lw    s6, 28(sp)\n"
"    lw    s7, 32(sp)\n"
"    lw    s8, 36(sp)\n"
"    lw    s9, 40(sp)\n"
"    lw    s10, 44(sp)\n"
"    lw    s11, 48(sp)\n"
"    lw    tp, 52(sp)\n"
"    lw    gp, 56(sp)\n"
"    addi  sp, sp, 64\n"
"    ret\n"
"buddy_abort_land:\n"
"    csrci mstatus, 8\n"
"    lui   t0, %hi(buddy_jmp_sp)\n"
"    lw    sp, %lo(buddy_jmp_sp)(t0)\n"
"    sw    zero, %lo(buddy_jmp_sp)(t0)\n"
"    li    a0, 1\n"
"    j     .Lcb_ret\n"
"    .text\n"
);
