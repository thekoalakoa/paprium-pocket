/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/s1_cache4b.h - test build 4b's boot-cache record in the TEST debug save (S1_CACHE4B_REC in s1_boot.h).
 *
 * The boot cache itself runs from crt0, before .data / .bss (board/pocket/boot: boot_cache.c's stub and the WRAM boot
 * overlay c4b_ovl.c; the flow and the record's words in boot/c4b.h); its result is the .noinit record c4b_rec. The
 * TEST image copies it to the debug save's DBG_B_CACHE block (version 8): the boots the chain of records has counted,
 * this boot's entry, then the previous DBG_CACHE_HIST boots' (newest first) carried from the old record, so the .sav
 * read after a Quit (whose reboot is a warm boot that touches nothing) still holds the session's first-boot unpack or
 * check, with the bank's CRC-32 (B Jam's request for the hardware test: "TEST shows the bank CRC"); tools/dbgsave.py
 * prints it. RELEASE runs the same boot cache and carries none of this. */
#ifndef S1_CACHE4B_H
#define S1_CACHE4B_H

#include <stdint.h>
#include "boot/c4b.h"

/* the debug save's DBG_B_CACHE block (board/pocket/dbgsave.h, version 8) as this module keeps it */
typedef struct {
    uint32_t boots;
    c4b_rec_t e[5];                             /* e[0] = this boot's; e[1..4] carried (dbgsave.h DBG_CACHE_HIST = 4) */
} s1_c4b_block_t;

#if S1_CACHE4B_REC
extern s1_c4b_block_t s1_c4b;
void s1_cache4b_take(void);                     /* brd_boot, before dbgsave_start clears the region: the old record's
                                                   DBG_B_CACHE (a version-8 record's) into e[1..4], this boot's into e[0] */
void s1_cache4b_record(void);                   /* brd_boot right after dbgsave_start (interrupts still off): writes
                                                   DBG_B_CACHE after the new record's PREV2 block; nothing when the debug
                                                   save is off (a 4 KB save RAM) */
#endif

#endif
