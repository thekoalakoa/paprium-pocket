/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/sprite/spr_compose.c - the composer: one object, one frame (the cart chip, the STM32 microcontroller on the
 * real cartridge, runs it from RAM at 0x20002F9C; its flash copy is 0x0802F02C, and the offsets below are the flash
 * copy's).
 *   entry: the five budget words read once (0x0802F03A-0x0802F068: $1F12, $1F14, $1F10, $1F18, $1F16);
 *   the pose budget pre-check (0x0802F09A-0x0802F0C4): the pose's block count (frame word bits 24-28) at $110
 *     each against what is left; when it does not fit, a hold if the whole-frame budget could take it
 *     (0x0802F2A0-0x0802F2AA), else a pre-load pass from lists A and B that shows the pose only once every block is
 *     resident (0x0802F2AC-0x0802F5B2);
 *   the frame advance (0x0802F0C6-0x0802F0EC): the next frame; the 50 Hz skip (frame word bit 30 at rate $32,
 *     0x0802F5B4-0x0802F5C2; dormant at 60 Hz); the queued anim at the cycle's end; the terminal end writes the
 *     record's anim 0;
 *   pose bit 29 clears the object's palette (0x0802F104-0x0802F112); the piece word, the object word and id x 16
 *     are one 16-bit sum (0x0802F186-0x0802F192), the H-flip path moving $800 between the two words;
 *   per piece (0x0802F14E on; H-flip 0x0802F41E on): the offsets, the block's hit (countdown $20) or miss, then the
 *     clip, X only ($61..$1BF, 0x0802F15A-0x0802F166), and the SAT entry;
 *   a miss (0x0802F1C2-0x0802F29E): the budget gate ($1F12 - $1F10 >= $110) and the 15-load cap, then a claim from
 *     list A, list B, the piece's related block, list C, each list taken from its end (the lowest id), else the piece
 *     is dropped (no entry, the object's other pieces drawn);
 *   the claim (0x0802F666-0x0802F6FC): the id retargeted, its 8-word DMA descriptor, the block listed;
 *   exit (0x0802F3CA-0x0802F3E6): $1F10, $1F18 and $1F16 written back.
 * The cart chip repeats the list search and the claim at each of its three sites (the two draw loops, the pre-load
 * pass); here they are shared static functions with the same steps.
 *
 * SPR_BUG (planted, for the negative controls of the lockstep test against the cart chip only; fwbuild.json s1 host
 * variants bug_spr*, never an image that ships): 1 = 0.2.6's clip (X and Y by the piece size), 2 = $1F1C never written
 * (spr_frame.c), 4 = the stash taken from entries 0-13 (spr_frame.c), 5 = 0.2.6's field-wise attribute rule and door
 * fix, 6 = pose bit 29 ignored, 7 = the H-flip path composed as the plain one.
 */
#include "spr.h"
#include "spr_board.h"
#include "tdiag.h"

#ifndef SPR_BUG
#define SPR_BUG 0
#endif

#define AW(off)         (*(const uint32_t *)(spr_anim + ((off) & ~1u)))
#define U16(p)          (*(const uint16_t *)(p))
/* a SAT entry (0x0802F16E-0x0802F19A; H-flip 0x0802F462-0x0802F492): Y, size bits + link, the attribute word, X, as
   two 32-bit stores (the entry is 8-aligned in RAMDP) */
#define SAT_ENTRY(e, y, pw, link, aw, x) do { \
        ((volatile uint32_t *)(e))[0] = (uint16_t)(y) | ((uint32_t)(uint16_t)(((pw) & 0xF00u) + (link)) << 16); \
        ((volatile uint32_t *)(e))[1] = (uint16_t)(aw) | ((uint32_t)(uint16_t)(x) << 16); } while (0)

#if !PPM_RELEASE && !TDIAG_LEAN
/* TEST: the cache counters TEST's SAT snapshot keeps in the debug save (interim, to be dropped later) */
uint16_t spr_cnt_starved;       /* misses the budget gate refused */
uint16_t spr_cnt_noslot;        /* misses with no id to claim */
uint32_t spr_cnt_loads;         /* claims */
uint32_t spr_cnt_evict;         /* claims that took an id holding another block */
#define TCNT(x)         ((x)++)
#define TSAT(x)         do { if ((x) != 0xFFFFu) (x)++; } while (0)
#else
#define TCNT(x)         ((void)0)
#define TSAT(x)         ((void)0)
#endif

/* the composer's working copies of the budget words (the cart chip's stack slots sp+0 .. sp+0x24) */
typedef struct {
    uint32_t used;                  /* $1F10 */
    uint32_t budget;                /* $1F12 */
    uint32_t ndma;                  /* $1F16 */
    volatile uint16_t *dma;         /* RAMDP $1400 + $1F16 x 16 */
} spr_cx;

/* one list, taken from its end (the lowest id); an entry that fails its countdown test is dropped as it is passed
   (the shortened count stored back). A: countdown 0; B and C: <= $1F, not used this frame. Returns the id or 0. */
static uint32_t spr_take(const uint8_t *list, uint16_t *len, uint32_t maxcd)
{
    uint32_t i = *len, id;

    while (i != 0u) {
        i--;
        id = list[i];
        if (SPR.cd[id] <= maxcd) {
            *len = (uint16_t)i;
            return id;
        }
    }
    *len = 0u;
    return 0u;
}

/* the gate (0x0802F1CC-0x0802F1DE): no load unless $1F12 - $1F10 >= $110 and fewer than 15 are listed */
static int spr_gate(const spr_cx *x)
{
    if (x->budget <= x->used + 0x10Fu) {
        TSAT(spr_cnt_starved);
        return 0;
    }
    return SPR.nload <= 14u;
}

/* the claim (0x0802F666-0x0802F6FC): the id's old block leaves the index, the new one enters; the descriptor's eight
   words (the VDP registers, then the id's two command words: 0x08025EF0 and 0x08025DF0, i.e. the id's VRAM address
   id << 9 as a VDP write command); $1F10 += $110, $1F16 += 1; the block appended to the load list */
static void spr_claim(spr_cx *x, uint32_t id, uint32_t blk)
{
    volatile uint16_t *d = x->dma;
    uint32_t old = SPR.id_blk[id];

    if (old != 0u && old != blk)
        TCNT(spr_cnt_evict);
    TCNT(spr_cnt_loads);
    spr_bid_set(old, 0u);
    SPR.id_blk[id] = (uint16_t)blk;
    spr_bid_set(blk, id);
    if (SPR_DMA_FITS(x->ndma)) {        /* past $1FE0 nothing is stored (a list the game never clears: row B58) */
        ((volatile uint32_t *)d)[0] = SPR_VDP_INC2 | (SPR_VDP_LEN_LO << 16);               /* +0 $8F02, +2 $9300 */
        ((volatile uint32_t *)d)[1] = SPR_VDP_SRC_LO | ((SPR_VDP_LEN_HI | 0x01u) << 16);    /* +4 $9500, +6 $9401 */
        ((volatile uint32_t *)d)[2] = SPR_VDP_SRC_HI | ((SPR_VDP_SRC_MI | 0x60u) << 16);    /* +8 $9700, +A $9660 */
        ((volatile uint32_t *)d)[3] = (0x4000u + ((id & 0x1Fu) << 9)) | ((0x80u + (id >> 5)) << 16);   /* +C, +E */
    }
    x->dma = d + 8;
    x->used = (x->used + 0x110u) & 0xFFFFu;
    x->ndma = (x->ndma + 1u) & 0xFFFFu;
    SPR.load[SPR.nload] = (uint16_t)blk;
    SPR.nload++;
}

/* a miss in a draw loop: the gate, then list A, list B, the related block (block + (size byte >> 4) - 9: taken only if
   it is resident in an id not used this frame), list C; 0 = the piece is dropped */
static uint32_t spr_miss(spr_cx *x, uint32_t blk, uint32_t size)
{
    uint32_t id, rel;

    if (!spr_gate(x))
        return 0u;
    id = spr_take(SPR.la, &SPR.na, 0u);
    if (id == 0u)
        id = spr_take(SPR.lb, &SPR.nb, 0x1Fu);
    if (id == 0u) {
        rel = (blk + (size >> 4) - 9u) & 0xFFFFu;
        if (rel != blk && (id = spr_bid_get(rel)) != 0u && SPR.cd[id] <= 0x1Fu)
            goto claim;
        id = spr_take(SPR.lc, &SPR.nc, 0x1Fu);
        if (id == 0u) {
            TSAT(spr_cnt_noslot);
            return 0u;
        }
    }
claim:
    spr_claim(x, id, blk);
    return id;
}

/* the clip (0x0802F15A-0x0802F166): an entry when $61 <= X <= $1BF, one unsigned 16-bit compare; Y is never tested */
static inline int spr_clip(int16_t px, int16_t py, uint32_t size)
{
#if SPR_BUG == 1
    int w = (int)(((size >> 2) & 3u) + 1u) * 8, h = (int)((size & 3u) + 1u) * 8;
    return !(px >= 320 + 128 || py >= 240 + 128 || px < 128 - w || py < 128 - h);
#else
    (void)py;
    (void)size;
    return (uint16_t)(px - 0x61) <= 0x15Eu;
#endif
}

uint32_t spr_compose(spr_handle *h, volatile uint16_t *rec)
{
    spr_cx x;
    uint32_t whole, nsat, cur, fw, n, cnt, blk, id, attr, ret;
    int complete;
    int16_t px, py;
    const uint8_t *pose, *p, *end;
    volatile uint16_t *sat;

    x.budget = SPR_RD(SPR_RD_BUDGET);
    whole = SPR_RD(SPR_RD_WHOLE);
    x.used = SPR_RD(SPR_RD_USED);
    nsat = SPR_RD(SPR_RD_NSAT);
    cur = h->cur;
    x.ndma = SPR_RD(SPR_RD_NDMA);
    if (cur == 0u) {                            /* (the AD wrapper never calls it with no frame) */
        rec[0] = 0u;
        return 1u;
    }
    x.dma = &SPR_RD(SPR_RD_DMA + x.ndma * 16u);
    attr = rec[4];
    px = (int16_t)rec[6];
    py = (int16_t)rec[7];
    fw = AW(cur);
    n = (fw >> 24) & 0x1Fu;

    /* the pose budget pre-check */
    if (n * 0x110u + x.used > x.budget) {
        if (n * 0x110u <= whole)
            goto hold;
        /* the pre-load pass: lists A and B only, no SAT; the pose is shown once every block was resident */
        pose = spr_anim + (fw & 0x7FFFEu);
        cnt = (uint16_t)(int8_t)pose[1];
        if (cnt != 0u) {
            complete = 1;
            end = pose + 2 + ((cnt - 1u) & 0xFFFFu) * 8u + 8u;
            for (p = pose + 2; p != end; p += 8) {
                blk = U16(p + 4);
                if (blk == 0u)
                    continue;
                id = spr_bid_get(blk);
                if (id != 0u) {
                    SPR.cd[id] = 0x20u;
                    continue;
                }
                complete = 0;
                if (!spr_gate(&x))
                    continue;
                id = spr_take(SPR.la, &SPR.na, 0u);
                if (id == 0u)
                    id = spr_take(SPR.lb, &SPR.nb, 0x1Fu);
                if (id == 0u) {
                    TSAT(spr_cnt_noslot);
                    continue;
                }
                spr_claim(&x, id, blk);
                SPR.cd[id] = 0x20u;
            }
            if (!complete)
                goto hold;
            cur = h->cur;
        }
    }

    /* the frame advance (0x0802F0C6): the frame pointer steps, then the frame that was current is drawn */
    h->prev = cur;
    if ((int32_t)fw < 0) {
        if ((fw & 0x40000000u) && SPR_RATE() == 0x32u)
            h->cur = cur + 8u;                  /* at 50 Hz the next frame is skipped */
        else
            h->cur = cur + 4u;
    } else if (h->next != 0u) {
        h->cur = h->next;                       /* the queued anim at the cycle's end */
        h->next = 0u;
    } else {
        h->cur = AW(cur + 4u) & 0x7FFFFu;       /* the loop target; 0 = the terminal end */
        if (h->cur == 0u)
            rec[0] = 0u;                        /* the terminal end: the record's anim := 0 */
    }
    fw = AW(cur);
    ret = 1u;

draw:
    pose = spr_anim + (fw & 0x7FFFEu);
#if SPR_BUG != 6
    if (fw & 0x20000000u)
        attr &= 0xFFFF9FFFu;                    /* pose bit 29 clears the object's palette */
#endif
    sat = &SPR_RD(SPR_RD_SAT + nsat * 8u);
    cnt = (uint16_t)(int8_t)pose[1];
    if (cnt == 0u)
        goto out;
    end = pose + 2 + ((cnt - 1u) & 0xFFFFu) * 8u + 8u;
#if SPR_BUG != 7
    if (attr & 0x800u) {
        /* the H-flip loop (0x0802F41E): the X offsets from piece byte 2; the entry's word (piece ^ $800) + (object -
           $800) + id x 16 */
        uint32_t fattr = (attr - 0x800u) & 0xFFFFu;
        for (p = pose + 2; p != end; p += 8) {
            py = (int16_t)(py + (int8_t)p[0]);
            px = (int16_t)(px + (int8_t)p[2]);
            blk = U16(p + 4);
            if (blk == 0u)
                continue;
            id = spr_bid_get(blk);
            if (id == 0u && (id = spr_miss(&x, blk, p[3])) == 0u)
                continue;                       /* the piece is dropped */
            SPR.cd[id] = 0x20u;
            if (spr_clip(px, py, p[3])) {
                nsat = (nsat + 1u) & 0xFFFFu;
                SAT_ENTRY(sat, py, U16(p + 2), nsat, (U16(p + 6) ^ 0x800u) + fattr + id * 16u, px);
                sat += 4;
            }
        }
        goto out;
    }
#endif
    /* the plain loop (0x0802F14E-0x0802F1C2) */
    for (p = pose + 2; p != end; p += 8) {
#if SPR_BUG == 7
        px = (int16_t)(px + (int8_t)p[(attr & 0x800u) ? 2 : 1]);
#else
        px = (int16_t)(px + (int8_t)p[1]);
#endif
        py = (int16_t)(py + (int8_t)p[0]);
        blk = U16(p + 4);
        if (blk == 0u)
            continue;
        id = spr_bid_get(blk);
        if (id == 0u && (id = spr_miss(&x, blk, p[3])) == 0u)
            continue;                           /* the piece is dropped */
        SPR.cd[id] = 0x20u;
        if (spr_clip(px, py, p[3])) {
            nsat = (nsat + 1u) & 0xFFFFu;
#if SPR_BUG == 5
            sat[0] = (uint16_t)py;
            sat[1] = (uint16_t)((U16(p + 2) & 0xF00u) + nsat);
            {   /* 0.2.6's rule: priority and palette from the piece when set, flip and tile index XORed; the door */
                uint32_t ta = (uint32_t)(p[7] & 0xF8u) << 8, oa = attr & 0xFFFFu, ti = id * 16u + p[6], a;
                a = ((ta & 0x8000u) ? ta & 0x8000u : oa & 0x8000u) | ((ta & 0x6000u) ? ta & 0x6000u : oa & 0x6000u)
                    | ((ta ^ oa) & 0x1800u) | ((oa ^ ti) & 0x7FFu);
                if ((rec[2] & 0xFFu) == 107u && (uint32_t)(p - pose - 2) == 4u * 8u)
                    a &= ~0x2000u;
                sat[2] = (uint16_t)a;
            }
            sat[3] = (uint16_t)px;
#else
            SAT_ENTRY(sat, py, U16(p + 2), nsat, U16(p + 6) + attr + id * 16u, px);   /* one 16-bit ADD */
#endif
            sat += 4;
        }
    }
out:
    SPR_RD(SPR_RD_USED) = (uint16_t)x.used;
    SPR_RD(SPR_RD_NSAT) = (uint16_t)nsat;
    SPR_RD(SPR_RD_NDMA) = (uint16_t)x.ndma;
    return ret;

hold:
    /* 0x0802F3C0: nothing advances; the previous frame is drawn again if there is one (0x0802F404-0x0802F41C) */
    ret = 0u;
    if (h->prev == 0u)
        goto out;
    fw = AW(h->prev);
    goto draw;
}
