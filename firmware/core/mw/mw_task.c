/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/mw/mw_task.c - the cart chip's MegaWire init, TIM7 task and information block (test build S3b on; see mw.h).
 *
 * In the SRAM image (run in place). Each function does what the cart chip (the STM32 microcontroller on the real
 * cartridge) does at the address cited, with its RAM layout (mw_ram, mw.h) and its order of stores; the status words
 * go through the cart chip's status helper (st_set, resident), every call inside a critical section as the cart
 * chip's cpsid / cpsie brackets them.
 * The STM32 plumbing the cart chip calls here has no counterpart on the Pocket's board and is replaced:
 * TIM7's start (0x0801FF38: HAL_TIM_Base_Start_IT + the NVIC; ours runs the tick from boot, core/wdog), USART3's
 * set-up (0x0801FCE0) and its RX DMA start (0x0801FB6C).
 * The no-module path is checked tick by tick against the cart chip, run in our model of the cart
 * (tests/equiv/mw_oracle.py with tests/s1/mw_host.c). */
#include <stdint.h>
#include <string.h>
#include "board.h"
#include "sched.h"
#include "disp.h"
#include "mw.h"
#include "mw_int.h"

mw_ram_t mw_ram __attribute__((section(".sram_bss"), aligned(4)));
mw_stats_t mw_stats __attribute__((section(".sram_bss"), aligned(4)));

/* ---- a path not built yet: the cart goes on there (a module's path, which the Pocket never takes, the init's
   network text, or the A858 screen, mw.h) ------------------------------------------------------------------ */
void mw_not_ported(uint32_t chip_addr)
{
#if !PPM_RELEASE
    mw_stats.not_ported++;
    mw_stats.last_np = chip_addr;
#else
    (void)chip_addr;
#endif
}

/* 0x08020EDC: a request to the driver (its op word DRV+0x62, done flag DRV+0x64, the reply buffer's first byte) */
void mw_op(uint16_t op)
{
    MW16(drv, 0x62) = op;                                   /* 0x08020EE4 */
    MW8(drv, 0x64) = 0u;                                    /* 0x08020EEA */
    *MW_PTR(MW32(drv, 0x1070)) = 0u;                        /* 0x08020EF0: through the pointer at DRV+0x1070 */
}

/* 0x08021338: post a result: $1C10 = sub << 8 | code, $1C12 = len, $1FE6 bit 5 (unless MW+0x124 holds it back);
   the task state := 2 */
void mw_result(uint32_t sub, uint32_t code, uint32_t store, uint32_t len)
{
    if (MW8(mw, 0x124) == 0u) {                             /* 0x08021340-0x08021344 */
        MW8(mw, MW_RESULT) = 1u;                            /* 0x0802134C */
        if (store) {                                        /* 0x0802134E */
            volatile uint16_t *ram = brd_cart_ram();
            ram[0x1C10u >> 1] = (uint16_t)(code | (sub << 8));      /* 0x0802135E */
            ram[0x1C12u >> 1] = (uint16_t)len;                      /* 0x08021362 */
        }
        st_set(1u, ST_FE6, 0x20u);                          /* 0x08021364-0x08021370 */
    }
    MW8(mw, MW_STATE) = 2u;                                 /* 0x08021374 */
}

/* the MegaWire server's name (ours in place of the cart's: docs/ALLOWLIST.md, row B51) */
static const char mw_host[] = "www.koalakoa.com";

/* 0x0801D63C: the driver block cleared and set up */
static void mw_esp_init(void)
{
    uint32_t i;
    memset(mw_ram.drv, 0, MW_DRV_BYTES);                    /* 0x0801D648: the memset at 0x08012190 */
    MW8(drv, 0x5E) = 1u;                                    /* 0x0801D652 */
    MW32(drv, 0x1070) = MW_PTR_OF(&mw_ram.drv[0x65]);       /* 0x0801D65A: the reply buffer (DRV+0x65) */
    MW32(drv, 0x106C) = MW_PTR_OF(&mw_ram.drv[0x65]);       /* 0x0801D65E */
    MW16(drv, 0x60) = 1u;                                   /* 0x0801D664: driver state 1 (detect) */
    /* 0x0801D666: 0x08020EFC(the server name): the name at DRV+0x1086 (up to 47 characters and a NUL) and the request
       line at DRV+0x10B6 (the name between two pieces of the cart's HTTP text: not built yet). The name is ours,
       www.koalakoa.com, where the cart names its own server (docs/ALLOWLIST.md, row B51). Read by the AT stack only. */
    for (i = 0; mw_host[i] && i < 0x2Fu; i++)
        MW8(drv, 0x1086u + i) = (uint8_t)mw_host[i];
    MW8(drv, 0x1086u + i) = 0u;
    mw_not_ported(0x08020EFCu);
    /* 0x0801D66E: USART3 at 115,200 (0x0801FCE0) and 0x0801D67C: its RX DMA into the ring (0x0801FB6C): STM32
       plumbing, no counterpart on the Pocket (no module socket) */
    MW16(drv, 0x1084) = 0u;                                 /* 0x0801D686: the RX read index */
}

/* 0x08021890: the cart's identity from the Mega Drive header (domestic name, product code) and the flash version
   word; always succeeds */
static uint32_t mw_ident(void)
{
    volatile uint16_t *rom = brd_rom();
    uint32_t i;
    for (i = 0; i < 0x30u; i++)                             /* 0x0802189A-0x080218AC: header +0x120, 48 B */
        MW8(mw, 0x126u + i) = brd_rom_byte(0x120u + i);
    for (i = 0; i < 0xBu; i++)                              /* 0x080218B0-0x080218C0: header +0x183, 11 B */
        MW8(mw, 0x156u + i) = brd_rom_byte(0x183u + i);
    MW16(mw, 0x162) = rom[0x10012u >> 1] == 0xFFFFu ? 0u : rom[0x1000Au >> 1];     /* 0x080218C8-0x080218DE */
    return 1u;
}

/* 0x080218FC: the MegaWire init (C6's set-up job, and AA58 after 0x0802171C) */
void mw_init(void)
{
    disp_g.mw_ready = 0u;                                   /* 0x0802190A: memset(MW, 0, 0x1BC) - MW+0 is the byte */
    memset(&mw_ram.mw[1], 0, MW_BLK_BYTES - 1u);
    MW8(mw, MW_STATE) = 1u;                                 /* 0x0802190E */
    mw_esp_init();                                          /* 0x08021910 */
    MW8(eep, 0x10) = 0u;                                    /* 0x08021918 */
    if (mw_ident())                                         /* 0x0802191A-0x08021922 */
        disp_g.mw_ready = 1u;
    memset(mw_ram.rxr, 0xFF, MW_RXR_BYTES);                 /* 0x08021924-0x08021934 (the chip's byte loop: the same
                                                               bytes; the IROM's memset fills SRAM ~10x faster) */
    mw_init_irqoff();                                       /* 0x08021936-0x080219AA: interrupts off (resident) */
}

/* 0x0802171C: AA58's first call, 0x080215C0(1): the MegaWire record's EEPROM save (not built yet) */
void mw_reset(void)
{
    mw_not_ported(0x0802171Cu);
}

/* 0x08021728: the information block, RAMDP $1B20-$1B87 (the MegaWire screens read it), in two steps of the task
   (mw_tick_part): the block's bytes as the chip builds them on its stack (here in mw_tk.ib, so that the thread may take
   a sprite reply between the two), then the stores to RAMDP in the chip's order */
__attribute__((noinline))
static void mw_info_build(uint32_t r4)
{
    uint8_t *buf = mw_tk.ib;
    uint32_t w;
    uint16_t n;
    w = MW32(drv, 0x40); w = (w >> 16) | (w << 16);         /* 0x08021730-0x08021736: ror 16 */
    memcpy(&buf[0], &w, 4);
    w = MW32(drv, 0x44); w = (w >> 16) | (w << 16);         /* 0x08021738-0x08021740 */
    memcpy(&buf[4], &w, 4);
    w = (uint32_t)MW16(mw, 0x194) << 16;                    /* 0x08021746-0x0802174C */
    memcpy(&buf[8], &w, 4);
    n = MW16(mw, 0x196);                                    /* 0x08021752-0x08021754 */
    memcpy(&buf[0xC], &n, 2);
    buf[0x14] = MW8(drv, 0x48);                             /* 0x0802175C: ready */
    buf[0x15] = MW8(drv, 0x59);                             /* 0x08021764: the RX line high */
    buf[0x16] = MW8(drv, 0x58);                             /* 0x0802176C: present */
    buf[0x17] = MW8(drv, 0x107F);                           /* 0x08021774: the power profile */
    /* the byte loops below fill the chip's stack buffer, which nothing else reads: here memcpy / memset (IROM) fill
       the same bytes with fewer SRAM instructions */
    if (MW8(eep, 0x10)) {                                   /* 0x08021778-0x0802177E */
        buf[0x18] = MW8(eep, 0x12);                         /* 0x08021782 */
        buf[0x4A] = MW8(eep, 0x11);                         /* 0x08021786 */
        memcpy(&buf[0x19], &mw_ram.eep[0x52], 0x10u);       /* 0x0802178A-0x0802179E */
        memcpy(&buf[0x29], &mw_ram.eep[0x17], 0x21u);       /* 0x080217A2-0x080217B2 */
    }
    else {
        buf[0x18] = 0u;                                     /* 0x080217BA */
        buf[0x4A] = 0u;                                     /* 0x080217BE */
        memset(&buf[0x19], 0, 0x10u);                       /* 0x080217C0-0x080217CE */
        memset(&buf[0x29], 0, 0x21u);                       /* 0x080217D4-0x080217E4 */
    }
    memcpy(&buf[0x4B], &mw_ram.mw[0x19D], 0x18u);           /* 0x080217E8-0x080217FC: the update text */
    n = (uint16_t)(MW16(mw, 0x1BA) + 1u);                   /* 0x08021804-0x0802180A: the error byte's age */
    MW16(mw, 0x1BA) = n;
    buf[0x63] = n > 0xA0u ? 0u : MW8(mw, MW_ERRBYTE);       /* 0x08021812-0x08021820 */
    n = MW16(mw, 0x19A); memcpy(&buf[0xE], &n, 2);          /* 0x08021826-0x0802182A */
    n = MW16(mw, 0x198); memcpy(&buf[0x10], &n, 2);         /* 0x08021830-0x08021832 */
    n = MW16(mw, 0x162); memcpy(&buf[0x12], &n, 2);         /* 0x08021838-0x0802183A: the version word */
    /* buf[0x64..0x67] is never written by the cart chip: its stack holds there the register r4 the driver step
       0x0801E824 pushed first, the task's r4 at that call (the caller passes it: 0x122 or the driver block's address).
       Measured in our model of the cart chip: $1B84 / $1B86 = 0x2201 / 0x0000 on idle ticks, 0xAC00 / 0x0120 after a
       state-1 tick */
    memcpy(&buf[0x64], &r4, 4);
    mw_tk.ii = 0u;
}

/* 0x0802184E-0x08021876: the block to RAMDP, $1B20-$1B33 as stored, then $1B34-$1B87 byte-swapped, in the chip's
   order, MW_IB_STEP words a step (two a load: the block is word-aligned); 1 after the last */
__attribute__((noinline))
static uint32_t mw_info_store(void)
{
    volatile uint16_t *ram = brd_cart_ram() + (0x1B20u >> 1);
    const uint32_t *b = (const uint32_t *)(const void *)mw_tk.ib;
    uint32_t i = mw_tk.ii, e = i + MW_IB_STEP;
    if (e > 0x34u)
        e = 0x34u;
    for (; i < e; i += 2u) {
        uint32_t w = b[i >> 1];                             /* the block's halfwords i and i + 1 */
        if (i >= 0xAu)                                      /* 0x0802185E-0x08021876: $1B34-$1B87 byte-swapped */
            w = ((w & 0x00FF00FFu) << 8) | ((w >> 8) & 0x00FF00FFu);
        ram[i] = (uint16_t)w;                               /* 0x0802184E-0x0802185A: $1B20-$1B33 as stored */
        ram[i + 1u] = (uint16_t)(w >> 16);
    }
    mw_tk.ii = (uint8_t)i;
    return i >= 0x34u;
}

/* 0x08021388 (movs r1, #0x26 into 0x0802138A): the staged E7 packet read. The type byte (staging +0) and the length
   (+2 / +3, swapped by the E7 body) pick the next task state: a game packet (type below 0x80, length 1-255) goes
   to MW+0x22 for the server (3); 0x82 / 0x83 / 0x84 are the MegaWire menu's (4, a stored network, 6); a bad one posts
   an error result. The type byte is kept at MW+0x125 for the result. */
static uint32_t mw_e7_parse(void)
{
    uint8_t *e = mw_ram.e7b;
    uint32_t b0 = e[0], len = (uint32_t)e[2] | (uint32_t)e[3] << 8, sub, code, i;
    MW8(mw, 0x125) = (uint8_t)b0;                           /* 0x08021396 */
    if (!(b0 & 0x80u)) {                                    /* 0x0802139C */
        if (b0 & 0x40u) {                                   /* 0x080213A2 -> 0x08021534 */
            MW16(mw, 4) = 0u;
            return 2u;
        }
        if (len - 1u <= 0xFEu) {                            /* 0x080213A8-0x080213B4 */
            e[2] = (uint8_t)(len >> 8);                     /* 0x080213CC-0x080213D4: rev16, the bytes back */
            e[3] = (uint8_t)len;
            for (i = 0; i <= len + 3u; i++)                 /* 0x080213D6-0x080213E8 */
                MW8(mw, 0x22u + i) = e[i];
            MW16(mw, 0x20) = (uint16_t)(len + 4u);          /* 0x080213EC-0x080213EE */
            MW16(mw, 4) = 0u;                               /* 0x080213F0 */
            return 3u;
        }
        MW8(mw, MW_ERRBYTE) = 0x47u;                        /* 0x080213B6-0x080213C0 */
        MW16(mw, 0x1BA) = 0u;
        sub = b0; code = 0x84u;
    }
    else if (b0 == 0x83u) {                                 /* 0x08021430 */
        if (len == 0x37u) {
            for (i = 0; i < 6u; i++)                        /* 0x08021454-0x08021468 */
                MW8(drv, 0x31u + i) = e[4u + i];
            for (i = 0; i < 0x21u; i++)                     /* 0x0802146A-0x08021478 */
                MW8(drv, 0x10u + i) = e[0xAu + i];
            for (i = 0; i < 0x10u; i++)                     /* 0x0802147A-0x08021488 */
                MW8(drv, i) = e[0x2Bu + i];
            MW8(drv, 0x49) = 0u;                            /* 0x0802148A-0x08021496 */
            MW8(drv, 0x4C) = 0u;
            mw_result(0x83u, 1u, 1u, 0u);                   /* 0x0802149E */
            MW16(mw, 4) = 0u;                               /* 0x080214A2 */
            return 2u;
        }
        MW8(mw, MW_ERRBYTE) = 0x27u;                        /* 0x0802143C-0x08021450 */
        MW16(mw, 0x1BA) = 0u;
        sub = 0x83u; code = 0x82u;
    }
    else if (b0 == 0x84u) {                                 /* 0x080214A6 */
        if (len == 0x20u) {
            for (i = 0; i < 0x10u; i++)                     /* 0x080214CA-0x080214DC */
                MW8(mw, 0x168u + i) = e[4u + i];
            for (i = 0; i < 0x10u; i++)                     /* 0x080214DE-0x080214F0 */
                MW8(mw, 0x178u + i) = e[0x14u + i];
            MW8(mw, 0x167) = 0u;                            /* 0x080214F2-0x0802150E */
            MW32(mw, 0x188) = 0u;
            MW32(mw, 0x18C) = 0u;
            MW32(mw, 0x190) = 0u;
            MW16(mw, 0x194) = 0u;
            MW16(mw, 0x196) = 0u;
            MW16(mw, 4) = 0u;
            return 6u;
        }
        MW8(mw, MW_ERRBYTE) = 0x37u;                        /* 0x080214B2-0x080214C6 */
        MW16(mw, 0x1BA) = 0u;
        sub = 0x84u; code = 0x83u;
    }
    else if (b0 == 0x82u) {                                 /* 0x08021404 */
        if (len == 1u) {                                    /* 0x08021428-0x0802142E */
            MW16(mw, 4) = 0u;
            return 4u;
        }
        MW8(mw, MW_ERRBYTE) = 0x17u;                        /* 0x08021410-0x08021424 */
        MW16(mw, 0x1BA) = 0u;
        sub = 0x82u; code = 0x81u;
    }
    else {                                                  /* 0x08021514-0x0802152A */
        MW8(mw, MW_ERRBYTE) = 0x47u;
        MW16(mw, 0x1BA) = 0u;
        sub = b0; code = 0x84u;
    }
    mw_result(sub, code, 1u, 0u);                           /* 0x0802152C */
    MW8(mw, MW_STATE) = 2u;                                 /* 0x08021530-0x08021532 */
    MW16(mw, 4) = 0u;                                       /* 0x08021534-0x08021536 */
    return 2u;
}

/* 0x080219CC: the TIM7 MegaWire task (the chip's TIM7 interrupt calls it third, after the watchdog and heartbeat):
   (a) the request byte and the task state's step, (b) the driver step 0x0801E824, (c) the status word, the information
   block and the tail. Ours: the thread runs the task one step at a time, a step being one of the chip's own steps
   (a, b, the status word, the block's bytes, the block's stores MW_IB_STEP words at a time, the tail), and starts none
   while the game's sprite frame is open, for up to 33.4 ms (core/sched/sched.c); the values the chip keeps in registers
   or on its stack from one step to the next (the three saved bytes, r4, the block) are kept in mw_tk. The steps run in
   the chip's order and nothing else of the task runs between them; a mailbox post may land between two steps, as one
   may interrupt the chip's TIM7 task at any instruction (its mailbox interrupts are above TIM7). */
mw_tk_t mw_tk __attribute__((section(".sram_bss"), aligned(4)));

/* (a) 0x080219CC-0x08021A3A and the states: 0 = the task ends here (no MegaWire byte, or a request taken), 1 = go on */
__attribute__((optimize("no-jump-tables"), noinline))      /* the stack check follows no jump table */
uint32_t mw_tick_a(void)
{
    uint8_t req;
    uint32_t r4, nx;
#if !PPM_RELEASE
    mw_stats.ticks++;
#endif
    if (mw_aa_pending) {                                    /* ours: AA58's body 0x0801CCD0, deferred from the mailbox */
        mw_aa_pending = 0u;
        mw_reset();
        mw_init();
    }
    if (!disp_g.mw_ready)                                   /* 0x080219DC-0x080219E4 */
        return 0u;
    req = MW8(mw, MW_REQ);                                  /* 0x080219E8 */
    if (req) {
        MW8(mw, MW_REQ) = 0u;                               /* 0x080219F2 */
        if (!(req & 0x80u))                                 /* 0x080219F4-0x080219FA */
            mw_init();
        MW8(drv, 0x107F) = req & 3u;                        /* 0x08021A04: the power profile */
        MW8(drv, 0x1080) = req & 0x40u;                     /* 0x08021A0E: the RESTORE request */
        return 0u;                                          /* 0x08021A10: to the epilogue 0x080223C4 */
    }
    mw_tk.save_167 = MW8(mw, 0x167);                        /* 0x08021A14-0x08021A1A */
    mw_tk.save_49 = MW8(drv, 0x49);                         /* 0x08021A1C-0x08021A22 */
    mw_tk.save_164 = MW8(mw, 0x164);                        /* 0x08021A24-0x08021A2A */
    r4 = 0x200100ACu;                                       /* 0x080219EA: the chip's r4, the driver block (mw_info) */
    switch (MW8(mw, MW_STATE)) {                            /* 0x08021A2C-0x08021A3A */
    case 1:                                                 /* 0x08021A46 */
        MW16(mw, 4) = 0u;
        mw_op(1u);
        MW8(mw, MW_STATE) = 2u;                             /* 0x08021C80 */
        break;
    case 2:                                                 /* 0x08021A52 */
        if (MW8(mw, MW_RESULT) == 1u)
            break;
        r4 = 0x122u;                                        /* 0x08021A64: movs r4, r3 (MW_E7_PEND's offset) */
        if (MW8(mw, MW_E7_PEND) != 1u)
            break;
        /* 0x08021A6C: an accepted E7 (the game posts A9 + E7 in its attract mode, with no module too) */
        nx = mw_e7_parse();
        MW8(mw, MW_STATE) = (uint8_t)nx;                    /* 0x08021A70-0x08021A72 */
        if (nx != 2u)                                       /* 0x08021A74-0x08021A7E */
            MW8(mw, 0x124) = 0u;
        if (MW8(mw, MW_E7_PEND) == 0u)                      /* 0x08021A80-0x08021A88 */
            MW8(mw, MW_STATE) = 2u;
        MW8(mw, MW_E7_PEND) = 0u;                           /* 0x08021A90 */
        st_set(0u, ST_FE6, 0x10u);                          /* 0x08021A92-0x08021A9C */
        break;
    case 3:                                                 /* 0x08021AA0: the packet to the server, step MW+4 */
        switch (MW16(mw, 4)) {
        case 0:                                             /* 0x08021AB0 */
            MW16(mw, 6) = 0u;
            MW16(mw, 4) = (uint16_t)(MW16(mw, 4) + 1u);     /* 0x08021DE4-0x08021DE8 -> 0x08021B18 */
            break;
        case 1:                                             /* 0x08021AB6 */
            if (MW16(drv, 0x60) != 4u) {
                /* 0x08021AC6: 0x08020F8C writes the HTTP request for the packet MW+0x22 into DRV+0x865 and returns its
                   length (the cart's network text: not built yet; the driver sends it only with a module) */
                mw_not_ported(0x08021AC6u);
                MW16(drv, 0x107A) = 0u;                     /* 0x08021AD0: the request's length */
                MW16(drv, 0x1076) = 0u;                     /* 0x08021AD6 */
                MW8(drv, 0x1078) = 0u;                      /* 0x08021ADA */
                MW32(drv, 0x1070) = MW_PTR_OF(&mw_ram.drv[0x65]);   /* 0x08021ADE: the reply buffer */
                mw_op(4u);                                  /* 0x08021AE0 */
                MW16(mw, 6) = 0u;                           /* 0x08021AE4 */
                MW16(mw, 4) = (uint16_t)(MW16(mw, 4) + 1u); /* 0x08021DE4 */
            }
            else {
                MW16(mw, 6) = (uint16_t)(MW16(mw, 6) + 1u); /* 0x08021AE8-0x08021AF2 */
                if (MW16(mw, 6) > 0x1C2u)                   /* 0x08021AF4: 451 ticks, ~46 s */
                    mw_result(MW8(mw, 0x125), 0x84u, 1u, 0u);       /* 0x08021AFA-0x08021B08 -> 0x08021C7C */
            }
            break;
        case 2:                                             /* 0x08021B0A: the driver's done flag DRV+0x64 */
            r4 = 0x20010110u;                               /* adds r4, #0x64 (the chip's r4 at the driver step) */
            if (MW8(drv, 0x64)) {
                MW16(mw, 6) = 0u;                           /* 0x08021B12-0x08021B18 */
                MW16(mw, 4) = 3u;
            }
            else {
                MW16(mw, 6) = (uint16_t)(MW16(mw, 6) + 1u); /* 0x08021B1C-0x08021B26 */
                if (MW16(mw, 6) > 0x1C2u - (MW_BUG == 1))   /* 0x08021B28: no answer in 451 ticks: $1C10 = type | 0x85
                                                               (planted bug 1: 450) */
                    mw_result(MW8(mw, 0x125), 0x85u, 1u, 0u);       /* 0x08021B2E-0x08021B3A -> 0x08021C7C */
            }
            break;
        case 3:                                             /* 0x08021B3C: the server's reply (DRV+0x65 'M'); the driver
                                                               sets the done flag only with a module (not built yet) */
            mw_not_ported(0x08021B3Cu);
            break;
        default:                                            /* 0x08021AA6: above 3, nothing */
            break;
        }
        break;
    case 4:                                                 /* 0x080220FE: the access-point scan (packet 0x82) */
        switch (MW16(mw, 4)) {
        case 0:                                             /* 0x0802210E-0x08022116 */
            MW16(mw, 6) = 0u;
            MW16(mw, 4) = 1u;
            mw_op(7u);                                      /* 0x08021ED4: the driver's scan */
            break;
        case 1:                                             /* 0x08022118: the driver's done flag DRV+0x64 */
            r4 = 0x20010110u;                               /* adds r4, #0x64 */
            if (MW8(drv, 0x64)) {                           /* 0x08022120 -> 0x08021C56 */
                MW16(mw, 6) = 0u;
                MW16(mw, 4) = 2u;
            }
            else {
                MW16(mw, 6) = (uint16_t)(MW16(mw, 6) + 1u); /* 0x08022122-0x0802212C */
                if (MW16(mw, 6) > 0x1C2u)                   /* 0x0802212E: no scan in 451 ticks: $1C10 = 0x8292 */
                    mw_result(MW8(mw, 0x125), 0x92u, 1u, 0u);       /* 0x08022132-0x0802213C -> 0x08021C7A */
            }
            break;
        case 2:                                             /* 0x0802213E: the access points to $1C14 (a module's
                                                               scan only; not built yet) */
            mw_not_ported(0x0802213Eu);
            break;
        default:                                            /* 0x0802210C: above 2, nothing */
            break;
        }
        break;
    case 5:                                                 /* 0x08021BDE: the hello to the server (a module joined;
                                                               not built yet) */
        mw_not_ported(0x08021BDEu);
        break;
    case 6:                                                 /* 0x08021E0C: the sign-in (packet 0x84) */
        switch (MW16(mw, 4)) {
        case 0: {                                           /* 0x08021E1E-0x08021F02: the 'B' message, then its request */
            uint32_t sid = MW32(mw, 0x188), n = sid ? 0x17u : 0x37u, i;
            MW16(mw, 4) = 1u;                               /* 0x08021E20 */
            MW16(mw, 6) = 0u;                               /* 0x08021E28 */
            MW16(mw, 0x20) = (uint16_t)n;                   /* 0x08021E36: its length */
            MW8(mw, 0x22) = 0x42u;                          /* 0x08021E3A: 'B' */
            MW8(mw, 0x23) = 1u;                             /* 0x08021E40 */
            MW8(mw, 0x24) = 0u;                             /* 0x08021E48 */
            MW8(mw, 0x25) = (uint8_t)(n - 4u);              /* 0x08021E4E */
            for (i = 0; i < 0xBu; i++)                      /* 0x08021E50-0x08021E62: the cart's product code */
                MW8(mw, 0x26u + i) = MW8(mw, 0x156u + i);
            MW8(mw, 0x31) = (uint8_t)(MW16(mw, 0x162) >> 8);    /* 0x08021E64-0x08021E76: the version word */
            MW8(mw, 0x32) = (uint8_t)MW16(mw, 0x162);
            MW8(mw, 0x33) = 0u;                             /* 0x08021E7E */
            MW8(mw, 0x34) = 0u;                             /* 0x08021E84 */
            MW8(mw, 0x35) = (uint8_t)(sid >> 24);           /* 0x08021E86-0x08021EA8: the session id */
            MW8(mw, 0x36) = (uint8_t)(sid >> 16);
            MW8(mw, 0x37) = (uint8_t)(sid >> 8);
            MW8(mw, 0x38) = (uint8_t)sid;
            if (sid == 0u) {                                /* 0x08021EDA-0x08021F00: the nick and the password */
                for (i = 0; i < 0x10u; i++)
                    MW8(mw, 0x39u + i) = MW8(mw, 0x168u + i);
                for (i = 0; i < 0x10u; i++)
                    MW8(mw, 0x49u + i) = MW8(mw, 0x178u + i);
            }
            MW32(mw, 0x190) = 0u;                           /* 0x08021EAE-0x08021EB4 */
            /* 0x08021EB6-0x08021EBC: 0x08020F8C writes the HTTP request for the message MW+0x22 into DRV+0x865 and
               returns its length (the cart's network text: not built, docs/ALLOWLIST.md, row B49); the driver sends
               it only with a module */
            mw_not_ported(0x08021EBCu);
            MW16(drv, 0x107A) = 0u;                         /* 0x08021EC2: the request's length */
            MW16(drv, 0x1076) = 0u;                         /* 0x08021EC6 */
            MW8(drv, 0x1078) = 0u;                          /* 0x08021ECA */
            MW32(drv, 0x1070) = MW_PTR_OF(&mw_ram.drv[0x65]);   /* 0x08021ECE-0x08021ED2: the reply buffer */
            mw_op(4u);                                      /* 0x08021ED4 */
            break;
        }
        case 1:                                             /* 0x08021F04: the driver's done flag DRV+0x64 */
            r4 = 0x20010110u;                               /* adds r4, #0x64 */
            if (MW8(drv, 0x64)) {                           /* 0x08021F0A -> 0x08021C56 */
                MW16(mw, 6) = 0u;
                MW16(mw, 4) = 2u;
            }
            else {
                MW16(mw, 6) = (uint16_t)(MW16(mw, 6) + 1u); /* 0x08021F0E-0x08021F18 */
                if (MW16(mw, 6) > 0x1C2u)                   /* 0x08021F1A: no answer in 451 ticks: $1C10 = 0x848D */
                    mw_result(MW8(mw, 0x125), 0x8Du, 1u, 0u);       /* 0x08021F20-0x08021F2A -> 0x08021C7A */
            }
            break;
        case 2:                                             /* 0x08021F2C: the server's answer (a module only; not
                                                               built yet) */
            mw_not_ported(0x08021F2Cu);
            break;
        default:                                            /* 0x08021E1C: above 2, nothing */
            break;
        }
        break;
    default:                                                /* 0x08021A34: any other value */
        break;
    }
    mw_tk.r4 = r4;
    return 1u;
}

/* (c) 0x080221EE-0x08022292: the status word, after the driver step; then 0x08022294-0x0802229C: the information
   block only when the game's 81 asked for it (bit 3, G+0xB): 1 = it did */
__attribute__((noinline))
uint32_t mw_tick_c(void)
{
    uint32_t st;
    st = 0u;
    if (MW8(drv, 0x58)) {                                   /* present */
        st = 1u;
        if (MW8(drv, 0x48)) {                               /* the AT bring-up done */
            if (!MW8(drv, 0x49))                            /* no access point yet: 2, or 3 while joining */
                st = MW16(drv, 0x60) == 6u ? 3u : 2u;
            else if (!MW8(mw, 0x164))                       /* joined, hello not answered */
                st = 4u;
            else if (MW8(mw, 0x167))                        /* signed in */
                st = 7u;
            else                                            /* 5, or 6 while signing in */
                st = MW8(mw, MW_STATE) == 6u ? 6u : 5u;
        }
    }
    st_set((st & 4u) != 0u, ST_FE6, 0x4u);                  /* 0x08022244-0x0802225C */
    st_set((st & 2u) != 0u, ST_FE6, 0x2u);                  /* 0x0802225E-0x08022276 */
    st_set(st & 1u, ST_FE6, 0x1u);                          /* 0x08022278-0x08022292 */
    return disp_g.f81[2] != 0u;                             /* 0x08022294-0x0802229C: 81 bit 3 (G+0xB) */
}

/* (c) 0x080222A0-0x080223C2: the tail, after the information block */
__attribute__((noinline))
static void mw_tick_tail(void)
{
    uint8_t save_167 = mw_tk.save_167, save_49 = mw_tk.save_49, save_164 = mw_tk.save_164;
    /* 0x080222A0-0x080222BE: the record's EEPROM save when signed in or joined changes to set (needs a module) */
    if ((MW8(mw, 0x167) != save_167 && MW8(mw, 0x167) != 0u) || (MW8(drv, 0x49) != save_49 && MW8(drv, 0x49) != 0u))
        mw_not_ported(0x080222BEu);
    if (MW8(drv, 0x49) != save_49)                          /* 0x080222C2-0x080222D4 */
        MW16(mw, 0x1B6) = 0u;
    if (MW8(drv, 0x49) && !MW8(mw, 0x164) && !(MW16(mw, 0x1B6) & 0x7Fu))
        mw_not_ported(0x080222EEu);                         /* 0x080222D6-0x0802233E: the host round robin */
    if (MW8(mw, 0x164) != save_164) {                       /* 0x08022340-0x08022356 */
        MW16(mw, 0x1B6) = 0u;
        MW16(mw, 0x1B8) = 0u;
    }
    if (MW8(mw, 0x164) && !MW8(mw, 0x167))
        mw_not_ported(0x0802235Cu);                         /* 0x08022358-0x080223B8: the sign-in retry */
    MW16(mw, 0x1B6) = (uint16_t)(MW16(mw, 0x1B6) + 1u);     /* 0x080223BA-0x080223C2 */
}

/* the thread's step (sched.c): the task's next step; 1 after its last, MW_STEP_YIELD when it did nothing. The thread
   calls it with the interrupts off (s = what to restore), right after it found the sprite frame closed (or open past
   its bound) and noted the multiplex count (mw_chk_par): the step opens them first and leaves at once if the count moved
   (an AE taken as they opened), so the check and the start of the step's work are one step against the sprite AE */
__attribute__((optimize("no-jump-tables")))      /* the stack check follows no jump table */
uint32_t mw_tick_part(uint32_t s)
{
    sched_crit_leave(s);
    if (disp_g.af_parity != mw_chk_par)
        return MW_STEP_YIELD;
    switch (mw_tk_ph) {
    case MW_PH_A:
        if (!mw_tick_a())
            return 1u;
        mw_tk_ph = MW_PH_DRV;
        return 0u;
    case MW_PH_DRV:
        mw_drv_step();                                      /* 0x080221EA: 0x0801E824 */
        mw_tk_ph = MW_PH_ST;
        return 0u;
    case MW_PH_ST:
        mw_tk_ph = mw_tick_c() ? MW_PH_IB : MW_PH_TAIL;
        return 0u;
    case MW_PH_IB:
        mw_info_build(mw_tk.r4);                            /* the chip's call 0x08021728(r4) after the test */
        mw_tk_ph = MW_PH_IBST;
        return 0u;
    case MW_PH_IBST:
        if (mw_info_store())
            mw_tk_ph = MW_PH_TAIL;
        return 0u;
    default:
        mw_tick_tail();
        mw_tk_ph = MW_PH_A;
        return 1u;
    }
}

/* the whole task at once (the host harness, tests/s1/mw_host.c) */
void mw_tick(void)
{
    uint32_t r;
    do {
        mw_chk_par = disp_g.af_parity;
        r = mw_tick_part(sched_crit_enter());
    } while (r != 1u);
}
