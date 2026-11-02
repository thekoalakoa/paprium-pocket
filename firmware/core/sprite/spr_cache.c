/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/sprite/spr_cache.c - the sprite cache's bookkeeping: the AE aging (0x08017FDC), the EC worker (0x08017EE0)
 * and the sparse block -> id index that stands in for the cart chip's 16 KB table (0x20008164). The hex numbers are
 * the cart chip's addresses; the cart chip is the STM32 microcontroller on the real cartridge.
 */
#include "spr.h"
#include "spr_board.h"

/* ---- the aging, 0x08017FDC: the slot count picks a chain through the jump table 0x08025838; above $35 there is
   none and nothing is aged (0x08017FE0-0x08017FEE). Each chain walks the slots count..1 once (ids from the slot
   table), so appending while walking down leaves the highest slot first and slot 1 last in each list:
     countdown $20      -> $1F, list C (used last frame)
     countdown 0 or 1   -> 0,   list A (free)
     countdown 2..$1F   -> - 1, list B (idle)
   then the three counts are stored (0x0801870A-0x08018714). Written as the loop the chains unroll. ---- */
void spr_age(void)
{
    uint32_t s = SPR.nslots, id, c, na = 0, nb = 0, nc = 0;

    if (s > SPR_SLOTS_MAX)
        return;
    for (; s != 0; s--) {
        id = spr_slot_id(s);
        c = SPR.cd[id];
        if (c == 0x20u) {
            SPR.cd[id] = 0x1Fu;
            SPR.lc[nc++] = (uint8_t)id;
        } else if (c <= 1u) {
            SPR.cd[id] = 0u;
            SPR.la[na++] = (uint8_t)id;
        } else {
            SPR.cd[id] = (uint8_t)(c - 1u);
            SPR.lb[nb++] = (uint8_t)id;
        }
    }
    SPR.na = (uint16_t)na;
    SPR.nb = (uint16_t)nb;
    SPR.nc = (uint16_t)nc;
}

/* ---- the EC worker 0x08017EE0(0, n), behind core/dispatch's gate (0x0801B152-0x0801B178: the $EC form, arg0 0,
   n <= $80, the engine flag):
     0x08017EF4-0x08017EF6  old := count, count := n
     0x08017EFA-0x08017EFC  old <= n: return (a grow stores the count only; the new slots join the lists at the next
                            aging, so they can be claimed in that frame)
     0x08017F18-0x08017F3A  a shrink: for the slots n..old INCLUSIVE, the id's block (if any) leaves the index, the id
                            and its countdown are cleared; slot n itself is flushed although it stays in the count
     0x08017F3C-0x08017F90  the lists rebuilt from the slots n..1, countdowns untouched: $1F -> C, 0 -> A, else B.
   Above $35 the gate's range reaches past the cart chip's 56-byte slot table: the aging then skips every AE and a
   later shrink reads the cart chip's next table (the DMA command words at 0x08025DF0) as ids up to $81 and the RAM
   beyond its 128-entry arrays. The game never posts such a count (its EC routine $3106E at its 24 call sites:
   $01..$35; every captured EC is $EC00 with arg0 0 and a count $01..$35), so the count is kept to $35, as test build 5
   kept it (docs/ALLOWLIST.md, row B48). ---- */
void spr_ec_set(uint32_t n)
{
    uint32_t old = SPR.nslots, s, id, blk, na = 0, nb = 0, nc = 0;

    if (n > SPR_SLOTS_MAX)
        n = SPR_SLOTS_MAX;
    SPR.nslots = (uint8_t)n;
    if (old <= n)
        return;
    for (s = n; s <= old; s++) {
        id = spr_slot_id(s);
        blk = SPR.id_blk[id];
        if (blk != 0u) {
            spr_bid_set(blk, 0u);
            SPR.id_blk[id] = 0u;
            SPR.cd[id] = 0u;
        }
    }
    for (s = n; s != 0; s--) {
        id = spr_slot_id(s);
        if (SPR.cd[id] == 0x1Fu)
            SPR.lc[nc++] = (uint8_t)id;
        else if (SPR.cd[id] != 0u)
            SPR.lb[nb++] = (uint8_t)id;
        else
            SPR.la[na++] = (uint8_t)id;
    }
    SPR.nb = (uint16_t)nb;
    SPR.nc = (uint16_t)nc;
    SPR.na = (uint16_t)na;
}

/* ---- the sparse block -> id index. The cart chip's table answers three writes (the claim's two, the EC flush) and
   five reads (the composer's hit test in each draw loop and in the pre-load pass, the related block); B0 clears it.
   Node i belongs to id i: an id holds at most one block and a block sits in at most one id, so a block that was never
   written, or was deleted, reads 0 as in the cart chip's table. ---- */
uint32_t spr_bid_get(uint32_t block)
{
    uint32_t i;

    block &= 0xFFFFu;
    for (i = spr_bid_head[block & 0xFFu]; i != 0u; i = spr_bid_nodes[i - 1u].next)
        if (spr_bid_nodes[i - 1u].block == block)
            return spr_bid_nodes[i - 1u].id;
    return 0u;
}

void spr_bid_set(uint32_t block, uint32_t id)
{
    uint8_t *pp;
    spr_bid_node *n;

    block &= 0xFFFFu;
    for (pp = &spr_bid_head[block & 0xFFu]; *pp != 0u; pp = &n->next) {
        n = &spr_bid_nodes[*pp - 1u];
        if (n->block == block) {
            *pp = n->next;
            break;
        }
    }
    if (id != 0u) {
        n = &spr_bid_nodes[id];
        n->block = (uint16_t)block;
        n->id = (uint8_t)id;
        n->next = spr_bid_head[block & 0xFFu];
        spr_bid_head[block & 0xFFu] = (uint8_t)(id + 1u);
    }
}

void spr_bid_clear(void)
{
    memset(spr_bid_head, 0, sizeof spr_bid_head);
}
