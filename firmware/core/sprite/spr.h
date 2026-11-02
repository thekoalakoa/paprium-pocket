/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/sprite/spr.h - the cart chip's sprite engine: the state and the routines. The cart chip is the STM32
 * microcontroller on the real cartridge; this engine was written by our team from our own study of how the cart
 * behaves.
 *
 * One function for each routine of the cart chip (cart chip addresses in the comments): the composer, the AE aging, the
 * AD wrapper, the AF frame end with its multiplex above 80 entries, the EC worker, B0's reset, the flush's and F2's
 * block-table read and the C6 init's hand-over. The dispatcher (core/dispatch) keeps every gate, refusal, status write
 * and register sequence of those posts (the flush, AE, B0, F2); the routines here do only the engine half, as the
 * bodies of disp_bodies.h call them.
 *
 * Two adaptations, neither removes a case or a branch:
 *   - the aging is the loop the cart chip unrolls into one chain per slot count (0x08017FDC + the jump table
 *     0x08025838);
 *   - the cart chip's 16 KB block -> id table (0x20008164) is a sparse index (256 bucket heads + one node per id,
 *     768 B): an id holds at most one block and a block sits in at most one id, so it answers every read the cart chip
 *     makes (a block never written reads 0) with the same value.
 * The cart chip's state is gathered into one struct; each field names its cart chip address.
 */
#ifndef CORE_SPR_H
#define CORE_SPR_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define SPR_IDS         128u    /* VRAM ids 0..$7F: id << 9 = the id's VRAM byte address */
#define SPR_OBJS        64u     /* object handles (records $0F80 + 16 x i) */
#define SPR_LOAD_CAP    15u     /* loads listed per frame: the composer stops at 15 (0x0802F1D8-0x0802F1DE) */
#define SPR_SLOTS_MAX   0x35u   /* the slot table's last real entry (0x08025DB8[$35] = id $7C) */

/* object handle (cart chip 0x2000FB1C + 16 x i) */
typedef struct {
    uint32_t cur;               /* +0  frame pointer: the frame to draw next (anim container offset; 0 = none) */
    uint32_t prev;              /* +4  the frame last drawn (a held pose draws it again) */
    uint32_t next;              /* +8  the queued anim's first frame (0 = none) */
    uint8_t  drawn;             /* +C  0 = restarted and not drawn since */
    uint8_t  pad[3];
} spr_handle;

/* sparse block -> id index node: node i belongs to id i */
typedef struct {
    uint16_t block;
    uint8_t  id;
    uint8_t  next;              /* node index + 1 of the next node in the bucket, 0 = end */
} spr_bid_node;

typedef struct {
    spr_handle h[SPR_OBJS];     /* 0x2000FB1C  64 x 16 B */
    uint8_t  nslots;            /* 0x2000FF1E  H+$402: the slot count (EC); the flag H+$400, the open frame H+$401
                                   and the AE count H+$403 are core/dispatch's (disp_g) */
    uint8_t  pad0[3];
    uint8_t  frames[256];       /* 0x2000FF20  H+$404: anims per object (C6's anim set-up) */
    uint32_t blkdir_bus;        /* 0x20010020  H+$504: the block directory as the cart chip's 16-bit flash
                                   view address (0x6C000000 + the ROM offset, 0x080196EA); read only for an objID of
                                   256 or more (docs/ALLOWLIST.md, row B52; spr_frame.c) */
    uint32_t blkdir;            /* 0x20010024  H+$508: the block directory long (0x080196EE; ours: C6 long 6 as a ROM
                                   byte offset, even) */
    uint16_t nload;             /* 0x20010028  loads listed since AE / the last flush */
    uint16_t nload_pad;         /* 0x2001002A  (no cart chip writer: 0) */
    uint16_t load[16];          /* 0x200136F0  the blocks to list at the flush (AF / B1), in load order */
    uint8_t  cd[SPR_IDS];       /* 0x200129EC  countdown per id: $20 on use, aged at AE */
    uint16_t id_blk[SPR_IDS];   /* 0x20012AD4  id -> block */
    uint16_t na;                /* 0x20013730  list A: free (countdown 0) */
    uint16_t nb;                /* 0x20012AD0  list B: idle 2..$1F frames */
    uint16_t nc;                /* 0x20013094  list C: used last frame */
    uint8_t  la[SPR_IDS];       /* 0x2001346C */
    uint8_t  lb[SPR_IDS];       /* 0x200070E4 */
    uint8_t  lc[SPR_IDS];       /* 0x20013298 */
} spr_state;
/* docs/ALLOWLIST.md, row B52 (B Jam's decision of 2026-10-28): the twelve bytes after frames[] are the cart chip's
   H+$504..$50F in its order (spr_frame.c) */
_Static_assert(offsetof(spr_state, blkdir_bus) == offsetof(spr_state, frames) + 256u, "B52: H+$504");
_Static_assert(offsetof(spr_state, blkdir) == offsetof(spr_state, frames) + 260u, "B52: H+$508");
_Static_assert(offsetof(spr_state, nload) == offsetof(spr_state, frames) + 264u, "B52: 0x20010028");
_Static_assert(offsetof(spr_state, nload_pad) == offsetof(spr_state, frames) + 266u, "B52: 0x2001002A");

extern spr_state SPR;
extern uint8_t  *spr_anim;                          /* the anim container in the workspace (set at C6) */
extern uint8_t  spr_bid_head[256];                  /* the sparse index (in wram_upper on the Pocket) */
extern spr_bid_node spr_bid_nodes[SPR_IDS];

/* the slot -> VRAM id table 0x08025DB8 (56 bytes): slots 1-$31 take ids 1-$31, slots $32-$35 take $7F down to
   $7C, entries 0, $36 and $37 are 0. Read only for slots 0..$35 (EC is kept to $35: spr_ec_set) */
static inline uint32_t spr_slot_id(uint32_t s)
{
    if (s >= 1u && s <= 0x31u)
        return s;
    if (s >= 0x32u && s <= SPR_SLOTS_MAX)
        return 0xB1u - s;
    return 0u;
}

/* the sparse index (spr_cache.c) */
uint32_t spr_bid_get(uint32_t block);
void     spr_bid_set(uint32_t block, uint32_t id);  /* id 0 deletes */
void     spr_bid_clear(void);

/* the cart chip's routines */
void     spr_age(void);                             /* 0x08017FDC and its chains */
void     spr_ec_set(uint32_t n);                    /* 0x08017EE0(0, n) */
uint32_t spr_compose(spr_handle *h, volatile uint16_t *rec);   /* the composer (RAM 0x20002F9C) */
uint32_t spr_ad(uint32_t idx);                      /* the AD wrapper 0x080194BC */
void     spr_af_close(uint32_t mode, uint32_t parity);   /* the frame end 0x080190B8 after its flush */
uint32_t spr_blk_addr(uint32_t blk);                /* the block-table read of the flush and F2 */

/* the engine halves of the posts (spr_posts.c), for the dispatcher's bodies */
void     spr_post_ae(void);                         /* 0x08018FBC: aging, the load count := 0 */
void     spr_post_af(uint32_t mode, uint32_t parity);    /* 0x080190B8 after the flush */
void     spr_post_b0(void);                         /* 0x0801940C */
void     spr_post_b1(void);                         /* 0x08018FFC's count := 0 (B1 only flushes) */
uint32_t spr_load_list(const uint32_t **list);      /* the flush's entries as ROM byte offsets, in load order */
void     spr_c6(uint32_t anim_ws, const uint16_t *max_index, uint32_t blkdir);   /* C6's sprite init 0x08019734 */
#if FW_S5
/* FW_S5 (the full firmware, board/board.h; test build S3a on): C6's sprite part as the cart chip's, in two steps around
   the container's decode (interim/s1/bodies_s1.c job_setup): spr_c6_begin = 0x08019734's resets and the start of
   0x080195E0 (the anims table cleared); spr_c6_count = the rest of 0x080195E0 on the decoded, swapped container: the
   anims per object counted as the cart chip counts them, the block directory taken; returns 0 or the cart chip's trace
   code (0x16 / 0x1A / 0x1B) */
void     spr_c6_begin(void);
uint32_t spr_c6_count(const uint8_t *anim, uint32_t blkdir);
#endif

#endif
