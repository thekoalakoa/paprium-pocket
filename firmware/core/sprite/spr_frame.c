/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/sprite/spr_frame.c - AD, the object wrapper around the composer (0x080194BC; 0x080194C2 is the same body with
 * the record base in r12): the restart rule, the queue move, the composer call, the ready flag; and AF's frame end
 * after its flush (0x080190B8 from 0x080190D6): the end mark, entry 79's link, the first DMA, $1F1C, the second
 * 14-entry DMA and the $1F20 stash, and the multiplex above 80 entries (0x080191F8-0x080193AC). The hex numbers are
 * the cart chip's addresses; the cart chip is the STM32 microcontroller on the real cartridge.
 */
#include "spr.h"
#include "spr_board.h"

#ifndef SPR_BUG
#define SPR_BUG 0
#endif

#define AW(off)         (*(const uint32_t *)(spr_anim + ((off) & ~1u)))
#define AH(off)         (*(const uint16_t *)(spr_anim + (off)))
#define SATW(i, w)      SPR_RD(SPR_RD_SAT + (i) * 8u + (w) * 2u)
#if SPR_BUG == 2
#define SPR_MUX(v)      ((void)(v))                             /* planted: $1F1C never written */
#else
#define SPR_MUX(v)      (SPR_RD(SPR_RD_MUX) = (uint16_t)(v))    /* $1F1C: 1 = the multiplex is on */
#endif
/* an anim's first frame (0x08019506-0x08019518, 0x0801956E-0x08019582): the object's directory long at (obj + 1) x 4
   gives its anim table as a word offset; the anim's entry is the long at that table + anim x 4 */
/* the end mark at entry[i] (0x080190D6-0x080190F4): Y := 0, then the link byte cleared: one 32-bit read and store of
   the entry's first two words */
#define END_MARK(i)     (SPR_RD32(SPR_RD_SAT + (i) * 8u) &= 0x0F000000u)
/* a DMA descriptor from the RAMDP SAT copy to VRAM (0x08019102-0x08019180, 0x08019186-0x080191C6): $8F02, the length
   low, the source low, the length high, $9700, $9605, the VRAM write command, $0083, as four 32-bit stores */
#define DESC(d, r93, src, r94, dst) do { volatile uint32_t *q_ = (volatile uint32_t *)(d); \
        q_[0] = SPR_VDP_INC2 | ((uint32_t)(r93) << 16); q_[1] = (src) | ((uint32_t)(r94) << 16); \
        q_[2] = SPR_VDP_SRC_HI | ((SPR_VDP_SRC_MI | 0x05u) << 16); q_[3] = (dst) | (0x83u << 16); } while (0)
#define FRAME_PTR(obj, anim)    AW(((AW(((obj) + 1u) * 4u) >> 1) + (anim) * 2u) * 2u)

/* anims per object (H+$404 + objID, a byte). The cart chip indexes its 256-byte table with the record's whole objID;
   the game's objIDs are below its object count (< 256) once the first AD has cleared bit 15 (the game sets bit 15
   together with the restart flag +$A), so a larger index is not reached in play. Past the table the cart chip reads
   its own working RAM (docs/ALLOWLIST.md, row B52; B Jam's decision of 2026-10-28: ours reads it the same way): H+$504
   the block directory as the cart chip's 16-bit flash view address (0x6C000000 + the ROM offset, 0x080196EA), H+$508
   the directory long as C6 gave it (0x080196EE), 0x20010028 the load count; ours gives those twelve bytes from its
   own state, as the cart chip holds them. From objID 268 on the cart chip's bytes are other live state (0x2001002C: a
   byte of its audio init, then the rest of its RAM), which ours does not hold in the cart chip's layout: it reads 0
   there (the rest of row B52; ours never reads past its own state). spr_state keeps those twelve bytes right after
   frames[] in the cart chip's order (spr.h), so one byte read of the state serves 0..267 */
static inline uint32_t spr_frames(uint32_t obj)
{
    return obj < 268u ? ((const uint8_t *)&SPR)[offsetof(spr_state, frames) + obj] : 0u;
}

/* ---- AD: 0x080194BC(idx) ---- */
uint32_t spr_ad(uint32_t idx)
{
    volatile uint16_t *rec = &SPR_RD(SPR_RD_OBJ + idx * 16u);
    spr_handle *h = &SPR.h[idx];
    uint32_t obj = rec[2], a, an, q;

    if (obj == 0u)                              /* 0x080194DA-0x080194E0: objID 0 = no object */
        return 0u;
    if (rec[5] != 0u) {                         /* 0x080194E2-0x080194E6: only +$A restarts */
        a = obj & 0x3FFFu;
        if (a >= AH(0u))                        /* 0x0801953E-0x0801954C: past the object count */
            return 0u;
        an = rec[0];
        if (spr_frames(a) <= an)                /* 0x0801954E-0x08019564: past the object's anims */
            return 0u;
        if (obj & 0x8000u) {                    /* 0x08019566 -> 0x080195B8: objID bit 15 = no previous frame */
            rec[2] = (uint16_t)a;
            h->prev = 0u;
            obj = a;
        }
        h->cur = FRAME_PTR(obj, an);            /* 0x0801956E-0x08019584: the anim from its first frame */
        h->next = 0u;
        h->drawn = 0u;
        rec[5] = 0u;
    }
    q = rec[1];                                 /* 0x080194EC-0x08019522: the queue moves into the handle */
    if (q != 0u) {
        if (q == 0xFFFFu || spr_frames(obj) <= q) {
            h->next = 0u;                       /* 0x08019590: $FFFF or past the anims cancels */
        } else {
            h->next = FRAME_PTR(obj, q);
            rec[0] = (uint16_t)q;
        }
        rec[1] = 0u;
    }
    if (h->cur == 0u || spr_compose(h, rec) != 0u) {
        h->drawn = 1u;                          /* 0x0801952A-0x08019530 */
        return 1u;
    }
    if (h->drawn == 0u)
        SPR_RD(SPR_RD_READY) = 0u;              /* 0x080195A4-0x080195B4: a held restart clears $1F1A */
    return 1u;
}

/* the $1F20 stash (0x080191C8-0x080191E6): entries 14-27 (planted bug 4: entries 0-13), 56 halfwords ascending, as 28
   aligned 32-bit copies written out; one copy of it, reached by a tail call from both paths to the second descriptor */
static __attribute__((noinline)) void spr_af_stash(void)
{
    volatile uint32_t *dst = &SPR_RD32(SPR_RD_STASH);
    const volatile uint32_t *src = &SPR_RD32(SPR_RD_SAT + (SPR_BUG == 4 ? 0u : 14u * 8u));
    __asm__ ("" : "+r" (dst), "+r" (src));          /* two base registers, so each copy is one load and one store */
#define STASH4(j)   do { dst[j] = src[j]; dst[(j) + 1] = src[(j) + 1]; dst[(j) + 2] = src[(j) + 2]; \
                         dst[(j) + 3] = src[(j) + 3]; } while (0)
    STASH4(0); STASH4(4); STASH4(8); STASH4(12); STASH4(16); STASH4(20); STASH4(24);
#undef STASH4
}

/* ---- AF: the frame end 0x080190B8 after the flush, with the post's mode (lo & 3) and the AE count H+$403 ---- */
void spr_af_close(uint32_t mode, uint32_t parity)
{
    uint32_t n, n1, len, r93, r94, src, dst, sec, base, sh, end, k, i, nd;
    volatile uint16_t *d;

    n = SPR_RD(SPR_RD_NSAT);
    if (n <= 80u) {
        END_MARK(n);                            /* the end mark at entry[count]: Y 0, link 0 */
        n1 = n + 1u;
        SPR_RD(SPR_RD_LINK79) &= 0xF00u;        /* entry 79's link */
        if (n1 == 81u) {
            len = 0x150u;
            r93 = SPR_VDP_LEN_LO | 0x40u;
            r94 = SPR_VDP_LEN_HI | 0x01u;
        } else {
            r93 = SPR_VDP_LEN_LO + ((n1 * 4u) & 0xFFu);
            len = (n1 + 4u) * 4u;
            r94 = SPR_VDP_LEN_HI + ((n1 * 4u) >> 8);
        }
        SPR_MUX(0u);                /* 0x0801912C-0x0801912E */
        dst = 0x7000u;
        src = SPR_VDP_SRC_LO | 0x80u;
        sec = 14u;
        goto first;
    }
    /* more than 80 entries; lo & 3 picks the mode (0x080191F8-0x08019202); never more than 80 uploaded */
    switch (mode) {
    case 0:                                     /* AF00: truncate at 80 */
        END_MARK(80u);
        SPR_RD(SPR_RD_LINK79) &= 0xF00u;
        len = 0x150u;
        r93 = SPR_VDP_LEN_LO | 0x40u;
        r94 = SPR_VDP_LEN_HI | 0x01u;
        SPR_MUX(0u);
        dst = 0x7000u;
        src = SPR_VDP_SRC_LO | 0x80u;
        sec = 14u;
        goto first;
    case 1:                                     /* AF01: the overflow swapped into the tail on even AE counts */
        sh = 0x30u; base = 0x50u; len = 0x150u; dst = 0x7000u; src = SPR_VDP_SRC_LO | 0x80u;
        r93 = SPR_VDP_LEN_LO | 0x40u; sec = 0u;
        break;
    case 2:                                     /* AF02: entries 14-27 kept for the stash, the tail rotated */
        sh = 0x22u; base = 0x5Eu; len = 0x118u; dst = 0x7070u; src = SPR_VDP_SRC_LO | 0xF0u;
        r93 = SPR_VDP_LEN_LO | 0x08u; sec = 14u;
        break;
    default:
        /* AF03 (0x0801929E -> 0x08019186): no end mark, no first DMA, no $1F1C; the second descriptor's eight stores
           go through r6, which on this path still holds the AF fragment's sl (0 or $4000: the STM32's flash alias,
           read-only, so they change nothing the game can see), then $1F10 / $1F16 count it and the stash is filled.
           The game posts AF00-AF02 only */
        sec = 14u;
        d = NULL;
        goto second;
    }
    if (n > 0x80u) {
        if (!(parity & 1u)) {
            n = 0x80u;
            end = 0x80u;
            goto move;
        }
        if (sec == 0u) {
            n = 0x80u;
            goto plain;
        }
        goto relink;
    }
    if (parity & 1u)
        goto after_move;
    if (base < n) {
        sh = (n - base) & 0xFFFFu;
        end = n;
        goto move;
    }
    if (sec == 0u)
        goto plain;
    base = n;
    goto relink;
move:
    for (k = base; k < end; k++) {              /* the overflow moves down by sh, relinked */
        i = k - sh;
        SATW(i, 0) = SATW(k, 0);
        SATW(i, 1) = (uint16_t)((SATW(k, 1) & 0xF00u) + k + 1u - sh);
        SATW(i, 2) = SATW(k, 2);
        SATW(i, 3) = SATW(k, 3);
    }
after_move:
    if (sec == 0u)
        goto plain;
    if (n < base)
        base = n;
relink:
    for (k = sec; (int32_t)k < (int32_t)(base - 1u); k++)
        SATW(k, 1) = (uint16_t)((SATW(k, 1) & 0xF00u) + k + 1u - sec);
    SATW(base - 1u, 1) &= 0xF00u;
    SPR_MUX(1u);
    r94 = SPR_VDP_LEN_HI | 0x01u;
    goto first;
plain:
    END_MARK(n);
    SPR_RD(SPR_RD_LINK79) &= 0xF00u;
    SPR_MUX(0u);
    len = 0x150u;
    dst = 0x7000u;
    r94 = SPR_VDP_LEN_HI | 0x01u;
    src = SPR_VDP_SRC_LO | 0x80u;
    r93 = SPR_VDP_LEN_LO | 0x40u;
first:
    /* the first DMA (0x08019102-0x08019180) at descriptor $1F16. The game clears $1F10 / $1F16 after its VBlank DMA;
       a list it never clears runs on past $1FE0, where the cart chip writes on through its FPGA window and ours stores
       nothing (docs/ALLOWLIST.md, row B58) */
    nd = SPR_RD(SPR_RD_NDMA);
    d = &SPR_RD(SPR_RD_DMA + nd * 16u);
    if (SPR_DMA_FITS(nd))
        DESC(d, r93, src, r94, dst);
    SPR_RD(SPR_RD_USED) = (uint16_t)(SPR_RD(SPR_RD_USED) + len);
    SPR_RD(SPR_RD_NDMA) = (uint16_t)(SPR_RD(SPR_RD_NDMA) + 1u);
    if (sec == 0u)
        return;
    d = SPR_DMA_FITS(nd + 1u) ? d + 8 : NULL;
second:
    /* entries 0-13 again (56 words, 0x08019186-0x080191C6), then entries 14-27 into the $1F20 stash, which the
       game's HBlank event copies to VRAM $F000 every frame (0x080191C8-0x080191E6). Every path here has sec = 14:
       the descriptor's words are constants, $1F10 += 72, and the stash's 56 halfwords, ascending, are
       28 aligned 32-bit copies written out (as test build 5's close: the same stores in the same order, no loop to
       run) */
    if (d != NULL)
        DESC(d, SPR_VDP_LEN_LO + 56u, SPR_VDP_SRC_LO | 0x80u, SPR_VDP_LEN_HI, 0x7000u);
    SPR_RD(SPR_RD_USED) = (uint16_t)(SPR_RD(SPR_RD_USED) + 72u);
    SPR_RD(SPR_RD_NDMA) = (uint16_t)(SPR_RD(SPR_RD_NDMA) + 1u);
    spr_af_stash();
}
