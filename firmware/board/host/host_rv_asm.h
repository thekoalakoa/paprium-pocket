/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/host/host_rv_asm.h - lets the x86 host build assemble the shared sources' RISC-V inline-assembly templates.
 *
 * The legacy modules contain three inline-asm statements (all moved in unchanged from 0.2.6):
 *   paprium.c  ppm_start   "srli %0, %1, 3 ; andi %0, %0, %2"   (BUDDY_LOOP_MASK test, kept as two instructions)
 *   mame.c     trap record "mv %0, sp"                           (debug snapshot, TEST builds)
 *   mame.h     ppm_hb_sp   "mv %0, sp"                           (heartbeat, TEST builds)
 *   paprium.c  ppm_md_rst  "nop"                                 (also an x86 instruction)
 * GCC substitutes x86 registers into the templates (e.g. "srli %eax,%ecx,3", "andi %eax,%eax,$161"), so assembler
 * macros with the RISC-V names, defined once at the top of the translation unit, turn them into the same operation
 * on x86. Only valid with -fno-toplevel-reorder (fwbuild.json "host"), which keeps this block ahead of every function.
 * Not used by the Pocket build. */
#ifndef HOST_RV_ASM_H
#define HOST_RV_ASM_H
__asm__(
"    .macro srli rd, rs, sh\n"
"    movl \\rs, \\rd\n"
"    shrl $\\sh, \\rd\n"
"    .endm\n"
"    .macro andi rd, rs, imm\n"
"    movl \\rs, \\rd\n"
"    andl \\imm, \\rd\n"
"    .endm\n"
"    .macro mv rd, rs\n"
"    .ifc \\rs,sp\n"
"    movl %esp, \\rd\n"
"    .else\n"
"    movl \\rs, \\rd\n"
"    .endif\n"
"    .endm\n"
);
#endif
