/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * zz_buddy_brain.c - the CPU MATE brain's entry table and its three files, written by a generator script outside this
 * tree. First written for a 0.2.6 test firmware: the real brain (with its counter, the cm9 version, assembled for the
 * layout B Jam chose) linked into block RAM, behind the glue's BudEntry ABI.
 * paprium-fw: the three .incbin inputs (brain.bin, cf.bin, rodata.bin) are NOT in this tree (the brain is a
 * reverse-engineered emulation of the game's CPU partner). The assembler finds them on its include path:
 * tools/fwbuild.py passes -Wa,-I<brain dir> and checks their md5s first (fwbuild.json "brain"). Only the paths
 * changed; the object code is the same.
 */
#include "buddy.h"

#if BUDDY_LINKED_BRAIN
__asm__(
"    .section .brain_irom,\"ax\",@progbits\n"
"    .incbin \"brain.bin\"\n"
"    .section .wram_cf,\"ax\",@progbits\n"
#if FW_S1
"    .globl buddy_cf_lo\n"                     /* FW_S1: the helpers' range, for the abort (buddy/s1_glue.c) */
"buddy_cf_lo:\n"
#endif
"    .incbin \"cf.bin\"\n"
#if FW_S1
"    .globl buddy_cf_hi\n"
"buddy_cf_hi:\n"
#endif
"    .fill 64, 1, 0\n"
"    .incbin \"rodata.bin\"\n"
"    .text\n"
);

const BudEntry buddy_linked_entry = {
    PBE_MAGIC, 0x0000859Cu, 0x00008504u, 0x80002230u, 0x800022BEu, 0x00005360u, 0x0000D2ECu,
    4, {   /* the sub-CPU init's Word RAM pattern in the SRAM mirror's direct window */
        { 0x08020000u, 0x1000u, 0x0000u },    /* objects $600000-$600FFF = 0 */
        { 0x08024000u, 0x0140u, 0x0000u },    /* records $604000-$60413F = 0 */
        { 0x08028000u, 0x1080u, 0x00FFu },    /* terrain $608000-$60907F = $00FF words */
        { 0x08030000u, 0x000Au, 0x0000u },    /* header +0..+9 = 0 */
    },
    3, {   /* the captured sub tables: PRG $5F4-$723, $9C0-$BBF, $1C92-$1D31 -> $16E800 / $16E930 / $16EB30 */
        { 0x080105F4u, 0x80001820u, 0x130u },
        { 0x080109C0u, 0x80001950u, 0x200u },
        { 0x08011C92u, 0x80001B50u, 0x0A0u },
    },
    0x80002220u
};
#endif
