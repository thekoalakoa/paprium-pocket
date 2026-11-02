/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/sprite/spr_posts.c - the engine halves of the sprite posts and C6's sprite init, as core/dispatch's bodies
 * call them (disp_bodies.h). The dispatcher writes every register sequence these routines have (the flush's queue
 * writes and its $1FE4 bit 8, AE's and B0's FPGA +$16 and bit 8, F2's), keeps the engine flag (H+$400), the open frame
 * (H+$401) and the AE count (H+$403); the rest of each routine is here (the hex numbers are the cart chip's
 * addresses; the cart chip is the STM32 microcontroller on the real cartridge):
 *   AE   0x08018FBC: the aging (0x08017FDC), then the load count := 0 (0x08018FE2-0x08018FE8);
 *   AF   0x080190B8: the flush (0x08018FFC, the dispatcher's flush_regs, its list from spr_load_list) leaves the count
 *        0 (0x0801907C-0x0801907E), then the close with the post's mode and the AE count;
 *   B0   0x0801940C: the aging (0x08019410), then everything cleared (0x08019438-0x0801948A);
 *   B1   0x08018FFC only (the flush; no SAT write);
 *   the block-table read of the flush and F2 (0x08019038-0x08019076, 0x08017E84-0x08017EAE);
 *   C6   the sprite init 0x08019734 that C6's set-up job runs: B0's steps (0x0801973C-0x080197B8), then the anim
 *        set-up's results (0x080195E0: anims per object, the block directory) and the engine flag (the dispatcher's).
 */
#include "spr.h"
#include "spr_board.h"

#if FW_S5
spr_state SPR;                                      /* wram_data */
#else
spr_state SPR __attribute__((section(".bss_upper")));   /* the FW_S5 = 0 images, with the interim audio: their wram_data
                                                           holds the interim album's and SFX feeder's state */
#endif
uint8_t  *spr_anim;
uint8_t  spr_bid_head[256] __attribute__((section(".bss_upper")));        /* 768 B in wram_upper on the Pocket (TEST's
                                                                              wram_data cannot hold them) */
spr_bid_node spr_bid_nodes[SPR_IDS] __attribute__((section(".bss_upper")));
static uint32_t spr_list_addr[16];                  /* the flush's entries as ROM byte offsets */

void spr_post_ae(void)
{
    spr_age();
    SPR.nload = 0u;
}

void spr_post_af(uint32_t mode, uint32_t parity)
{
    SPR.nload = 0u;
    spr_af_close(mode, parity);
}

static void spr_reset(void)                         /* 0x08019410-0x0801948A without the dispatcher's register writes */
{
    spr_handle *h;

    spr_age();                                      /* 0x08019410 (its lists and countdowns are cleared next) */
    SPR.nload = 0u;                                 /* 0x08019438-0x0801943E */
    SPR.na = 0u;                                    /* 0x08019440-0x0801944C */
    SPR.nb = 0u;
    SPR.nc = 0u;
    memset(SPR.id_blk, 0, sizeof SPR.id_blk);       /* 0x0801944E-0x08019468: id -> block, countdowns, block -> id */
    memset(SPR.cd, 0, sizeof SPR.cd);
    spr_bid_clear();
    for (h = SPR.h; h != SPR.h + SPR_OBJS; h++) {   /* 0x0801946C-0x08019482: all 64 handles */
        h->drawn = 0u;
        h->prev = 0u;
        h->cur = 0u;
        h->next = 0u;
    }
    SPR.nslots = 0u;                                /* 0x08019484-0x0801948A: until the next EC */
}

void spr_post_b0(void)
{
    spr_reset();
}

void spr_post_b1(void)
{
    SPR.nload = 0u;
}

/* the block-table read: the directory's long for the block (two flash words, high first), halved and doubled as a
   signed number (an even offset, rounded toward zero), added to the directory's place, 23 bits */
uint32_t spr_blk_addr(uint32_t blk)
{
    uint32_t dir = SPR.blkdir, e = dir + (blk << 2), off;

    off = ((uint32_t)SPR_FL16(e) << 16) + SPR_FL16(e + 2u);
    return (dir + (uint32_t)(((int32_t)off / 2) * 2)) & 0x7FFFFFu;
}

uint32_t spr_load_list(const uint32_t **list)
{
    uint32_t i, n = SPR.nload;

    for (i = 0; i < n; i++)
        spr_list_addr[i] = spr_blk_addr(SPR.load[i]);
    *list = spr_list_addr;
    return n;
}

/* C6: the sprite init on the container C6's set-up unpacked (anim_ws = its workspace offset); the anims per object
   from the set-up's count (max_index[o] + 1 for the container's objects, as the cart chip's anim set-up counts them),
   the block directory = C6's long 6 */
void spr_c6(uint32_t anim_ws, const uint16_t *max_index, uint32_t blkdir)
{
    uint32_t o, n;

    spr_reset();
    spr_anim = (uint8_t *)(uintptr_t)(brd_workspace() + anim_ws);
    memset(SPR.frames, 0, sizeof SPR.frames);
    n = *(const uint16_t *)spr_anim;
    if (n < 0x100u)
        for (o = 0; o < n; o++)
            SPR.frames[o] = (uint8_t)(max_index[o] + 1u);
    SPR.blkdir = blkdir & ~1u;
    SPR.blkdir_bus = 0x6C000000u + SPR.blkdir;      /* 0x080196EA (row B52: only an objID of 256 or more reads it) */
}

#if FW_S5
/* FW_S5 (test build S3a on): C6's sprite init 0x08019734 (its resets, as B0's: the aging 0x08017FDC first) and the
   start of its anim set-up 0x080195E0 (the 256 anims-per-object bytes at 0x2000FF20 cleared); the container is not read
   yet */
void spr_c6_begin(void)
{
    spr_reset();
    memset(SPR.frames, 0, sizeof SPR.frames);         /* 0x080195E8-0x080195F4 */
}

/* the rest of 0x080195E0, on the container decoded and swapped at anim: the object count n (its first halfword) must
   be below 0x100 (else 0x16); object k (1..n) starts at the container offset of its long at 4k, plus one when that
   long's upper halfword is negative, even and below 32 MB (0x0801965C-0x08019672), and its anims are the words up to
   the first 0xFFFF 0xFFFF pair, counted as a byte (0x201 of them: 0x1A, the count stays unwritten); then the block
   directory C6 named (long 6) is taken, and its first halfword must be 0 (else 0x1B, the directory kept) */
uint32_t spr_c6_count(const uint8_t *anim, uint32_t blkdir)
{
    uint32_t k, n = *(const uint16_t *)(const void *)anim, c;
    spr_anim = anim;
    if (n >= 0x100u)
        return 0x16u;                                 /* 0x08019626 */
    for (k = 1u; k <= n; k++) {
        uint32_t l = *(const uint32_t *)(const void *)(anim + 4u * k);
        int32_t hi = *(const int16_t *)(const void *)(anim + 4u * k + 2u);
        const uint16_t *p = (const uint16_t *)(const void *)(anim + ((l - (uint32_t)(hi >> 15)) & 0x1FFFFFEu));
        for (c = 0u; p[0] != 0xFFFFu || p[1] != 0xFFFFu; p += 2) {
            if (++c == 0x201u)
                return 0x1Au;                         /* 0x0801968A */
        }
        SPR.frames[k - 1u] = (uint8_t)c;              /* 0x2000FF1F + k */
    }
    SPR.blkdir = blkdir & ~1u;                        /* 0x080196EA / 0x080196EE */
    SPR.blkdir_bus = 0x6C000000u + SPR.blkdir;
    return SPR_FL16(SPR.blkdir) ? 0x1Bu : 0u;         /* 0x080196F2 */
}
#endif
