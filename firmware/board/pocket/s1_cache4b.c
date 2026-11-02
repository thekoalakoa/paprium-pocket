/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/s1_cache4b.c - test build 4b's boot-cache record in the TEST debug save, TEST image only
 * (S1_CACHE4B_REC; the plan in s1_cache4b.h). The code sits in the WRAM code window (pocket72k.json wcode_text: the
 * TEST IROM is full), as test build 4a's sound-cache probe did; it only copies words (the boot cache ran in crt0). */
#include <stdint.h>
#include "board.h"
#include "s1_boot.h"
#include "dbgsave.h"
#include "boot/boot_cache.h"
#include "s1_cache4b.h"

#if S1_CACHE4B_REC
_Static_assert(sizeof(s1_c4b_block_t) == 4u * DBG_CACHE_WORDS && C4B_REC_WORDS == DBG_CACHE_ENTRY_WORDS &&
               1u + DBG_CACHE_HIST == 5u, "DBG_B_CACHE's layout (version 8)");

#define C4B_OS                  __attribute__((noinline, optimize("Os")))   /* once a boot, 68000 held: size first */
#define DW(i)                   (((volatile uint32_t *)(void *)(brd_save() + DBG_SAVE_OFF))[i])
#define DBG_WORDS               (DBG_SAVE_BYTES / 4u)

s1_c4b_block_t s1_c4b __attribute__((section(".bss_upper")));              /* zero from crt0 at every boot */

/* the debug record in the save RAM, if it is one of this version: the data index of block `id` (0 = none; the walk
   stops at an empty or end header or a block past the region, as dbgsave.c's old_index); n = its length */
static C4B_OS uint32_t rec_block(uint32_t id, uint32_t *n)
{
    uint32_t i = 0u;
#if FW_S5                                       /* FW_S5 (test build 5 on): a version-8 record's DBG_B_CACHE has
                                                   the same layout */
    if (DW(0) >> 16 != DBG_B_HEAD || DW(1) != DBG_MAGIC || DW(2) < 8u || DW(2) > DBG_VERSION)
        return 0u;
#else
    if (DW(0) >> 16 != DBG_B_HEAD || DW(1) != DBG_MAGIC || DW(2) != DBG_VERSION)
        return 0u;
#endif
    while (i < DBG_WORDS) {
        uint32_t h = DW(i), bid = h >> 16, len = h & 0xFFFFu;
        if (bid == 0u || bid == DBG_B_END || i + 1u + len > DBG_WORDS)
            return 0u;
        if (bid == id) {
            *n = len;
            return i + 1u;
        }
        i += 1u + len;
    }
    return 0u;
}

void C4B_OS s1_cache4b_take(void)
{
    uint32_t at, n, i;
    const uint32_t *r = (const uint32_t *)(const void *)&c4b_rec;
    if ((at = rec_block(DBG_B_CACHE, &n)) != 0u && n == DBG_CACHE_WORDS) {   /* a version-8 (or 9) record's: carried */
        s1_c4b.boots = DW(at);
        for (i = 0u; i < DBG_CACHE_HIST * C4B_REC_WORDS; i++)
            ((uint32_t *)(void *)&s1_c4b.e[1])[i] = DW(at + 1u + i);
    }
    s1_c4b.boots++;
    for (i = 0u; i < C4B_REC_WORDS; i++)
        ((uint32_t *)(void *)&s1_c4b.e[0])[i] = r[i];
    brd_milestone(S1_MS_CACHE4A);
}

/* DBG_B_CACHE right after the new record's PREV2 block (dbgsave.c DBG_CACHE_AT): only when dbgsave_start wrote a
   record of this version (none with a 4 KB save RAM, whose 0x1000 is the game's 0x000), and only inside the region */
void C4B_OS s1_cache4b_record(void)
{
    uint32_t at, n, i;
    const uint32_t *w = (const uint32_t *)(const void *)&s1_c4b;
    if ((at = rec_block(DBG_B_PREV2, &n)) == 0u)
        return;
    at += n;
    if (at + 1u + DBG_CACHE_WORDS > DBG_WORDS)
        return;
    DW(at) = ((uint32_t)DBG_B_CACHE << 16) | DBG_CACHE_WORDS;
    for (i = 0u; i < DBG_CACHE_WORDS; i++)
        DW(at + 1u + i) = w[i];
}
#endif
