/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/mw/mw_screen.c - the cart chip's MegaWire screen (A858) (test build S3b on; see mw.h).
 *
 * In the SRAM image. With nothing plugged in, the game's Options pad code (Start x4, C, C) posts A858 and jumps to its
 * cart RAM at $200; the cart chip then loads page A (a 68000 program) and page B (a font) into the cart RAM, holds the
 * 68000 while it does, starts it again on page A and keeps two 32-character lines at RAMDP $1E10 / $1E50 for it to
 * show. This file does what the cart chip (the STM32 microcontroller on the real cartridge) does there, at its
 * addresses: the screen loop 0x080225F8 (its states 1, 2, 3, 6 and 7 and the default), the page loader 0x08022404
 * with its three parts 0x08020D6C (page A), 0x08020CC6 (page B) and 0x08020D2C (the "..." line), the access point's
 * default 0x08022460 and the line writer 0x080224B4. States 4 and 5 (the update's download and its write to the cart's
 * flash) need a module and are not built yet (TEST counts them); on the Pocket nothing can reach them.
 *
 * What is ours (the cart's own parts are not in the game's ROM): page A is our 68000 program (core/mw/mw_page_a.c,
 * tools/mkpagea.py, rebuilt from a real cart's screen); page B is the font the cart's screen shows, which the game's ROM
 * holds at 0x126200 (read from the player's ROM here, never kept in this tree); both are packed as the cart chip's
 * loader expects (format 0x80) in SRAM. The strings are the cart program's, read from the player's ROM
 * (core/mw/mw_text.c), which this screen unpacks when its state 1 ends (after the music has stopped and the 68000 has
 * started page A), before the rest of that call: the access point's default and the lines then come as the cart's do,
 * only later by the unpack's time (~0.27 s on the RV32 board model, an estimated timing); page A shows the lines about
 * 1.8 s after it starts. The 68000 hold: on the cart, clearing $1FE4 bit 14 holds the 68000 and setting it starts it
 * on the vectors in its cart RAM (docs/BOOT_SPEC.md section 11: the cart chip's own order of stores, as its code
 * has it; not measured on a cart); the Pocket's hold is CTRL.HOLD (brd_md_hold), which holds the whole console, so the
 * VDP and the sound chips start from reset with page A. Ours holds it when the cart chip's waits end, just before the
 * page work (the cart chip clears the bit just after it): that work takes ours ~7 ms on the RV32 board model, and a
 * held 68000 sees none of it.
 * Time: the cart chip's waits are SysTick counts (0x08020880) at its 96 MHz clock; here they are the board timer's,
 * and the thread runs each call in steps between them (mw_scr), below the MegaWire task and never between two of its
 * steps, as the cart chip's TIM7 interrupts its waits. Each address cited is where the cart chip does the step. */
#include <stdint.h>
#include <string.h>
#include "board.h"
#include "disp.h"
#include "song.h"
#include "mw.h"
#include "mw_int.h"

mw_scr_t mw_scr __attribute__((section(".sram_bss"), aligned(4)));

#define MW_CHIP_HZ              96000000u                           /* the chip's SysTick clock */
#define MW_WAIT(ticks)          ((uint32_t)((uint64_t)(ticks) * BRD_CLK_HZ / MW_CHIP_HZ))

/* the strings the screen loop takes from the cart program (0x080225F8-0x0802266A): address, length with its NUL */
#define S_SPACES                0x08025C61u, 0x21u
#define S_CONNECTING            0x08025C82u, 0x0Eu
#define S_APCON                 0x08025C90u, 0x1Du
#define S_SUCCESS               0x08025CDDu, 0x1Fu
#define S_ERROR                 0x08025CFCu, 0x18u
#define S_NOFOUND               0x08025D14u, 0x16u
#define S_NOPOWER               0x08025D2Au, 0x16u
#define S_HOME                  0x08025C5Cu, 0x05u

enum { PH_CALL = 0, PH_BODY, PH_S1A, PH_S1B };

/* the packed pages (format 0x80: literal runs of up to 63 bytes, then the end code) */
#define PG_ROOM(n)              (1u + (n) + ((n) + 62u) / 63u + 1u)
static uint8_t mw_pga[PG_ROOM(2u * MW_PAGE_A_WORDS)] __attribute__((section(".sram_bss")));
static uint8_t mw_pgb[PG_ROOM(0x1000u)] __attribute__((section(".sram_bss")));
#define MW_FONT_ROM             0x126200u   /* the game's ROM: the terminal font, characters 0x00-0x7F, 32 B each */

static void mw_str(uint8_t *d, uint32_t chip_addr, uint32_t n)
{
    uint32_t i;
    for (i = 0; i < n; i++)
        d[i] = mw_text8(chip_addr + i);
}

/* the cart's packing of a page: [0x80] [count, count bytes]... [0] */
static void mw_pack(uint8_t *p, uint32_t n, uint32_t (*get)(uint32_t))
{
    uint32_t i = 0, k;
    *p++ = 0x80u;
    while (i < n) {
        k = n - i > 63u ? 63u : n - i;
        *p++ = (uint8_t)k;
        while (k--)
            *p++ = (uint8_t)get(i++);
    }
    *p = 0u;
}
static uint32_t mw_pga_byte(uint32_t i) { uint16_t w = mw_page_a[i >> 1]; return (i & 1u) ? (w & 0xFFu) : (w >> 8); }
static uint32_t mw_pgb_byte(uint32_t i) { return brd_flash8()[MW_FONT_ROM + i]; }

/* 0x080251B0: the 0x80 form's unpacker (the byte after the format byte), into the chip's SDRAM 0xC0000000 (our
   SDRAM workspace); returns the bytes written */
static uint32_t mw_unpack80(const uint8_t *s, volatile uint8_t *d)
{
    uint32_t n = 0, c, k, v;
    while ((c = *s++) != 0u) {
        k = c & 0x3Fu;
        switch (c >> 6) {
        case 0: while (k--) d[n++] = *s++; break;
        case 1: v = *s++; while (k--) d[n++] = (uint8_t)v; break;
        case 2: v = n - *s++; while (k--) d[n++] = d[v++]; break;
        default: while (k--) d[n++] = 0u; break;
        }
    }
    return n;
}

static uint16_t ws16(uint32_t off)          /* the chip's ldrh from its SDRAM, then rev16 */
{
    const volatile uint8_t *w = brd_workspace();
    return (uint16_t)(w[off] << 8 | w[off + 1u]);
}

/* 0x08020D6C: page A into RAMDP $0000-$07FF, at most 0x800 B, the bytes from $200 on first, then the first half */
static uint32_t mw_page_a_load(const uint8_t *p)
{
    volatile uint16_t *ram = brd_cart_ram();
    uint32_t n, i;
    if (p[0] != 0x80u)                                      /* 0x08020D78-0x08020D7C */
        return 0u;
    n = mw_unpack80(p + 1, brd_workspace()) & 0xFFFFu;      /* 0x08020D80-0x08020D8C */
    if (n > 0x800u)                                         /* 0x08020D8E-0x08020D96 */
        n = 0x800u;
    for (i = 0x100u; i < (n >> 1); i++)                     /* 0x08020DA6-0x08020DBE */
        ram[i] = ws16(2u * i);
    for (i = 0; i < ((n >> 2) << 1); i += 2u)               /* 0x08020DC0-0x08020DD4 */
        ram[i >> 1] = ws16(i);
    return 1u;
}

/* 0x08020CC6: page B into RAMDP $0800-$17FF, at most 0x1000 B */
static uint32_t mw_page_b_load(const uint8_t *p)
{
    volatile uint16_t *ram = brd_cart_ram();
    uint32_t n, i;
    if (p[0] != 0x80u)                                      /* 0x08020CD0-0x08020CD4 */
        return 0u;
    n = mw_unpack80(p + 1, brd_workspace()) & 0xFFFFu;      /* 0x08020CD6-0x08020CE4 */
    if (n > 0x1000u)                                        /* 0x08020CE6-0x08020CEE */
        n = 0x1000u;
    for (i = 0; i < ((n >> 1) << 1); i += 2u)               /* 0x08020CF0-0x08020D18 */
        ram[(0x800u + i) >> 1] = ws16(i);
    return 1u;
}

/* 0x08020D2C: the lines cleared, then "..." on the first ($842E x 3) */
static uint32_t mw_dots(void)
{
    volatile uint16_t *ram = brd_cart_ram();
    uint32_t a;
    for (a = 0x1E10u; a < 0x1E90u; a += 2u)
        ram[a >> 1] = 0u;
    ram[0x1E10u >> 1] = 0x842Eu;
    ram[0x1E12u >> 1] = 0x842Eu;
    ram[0x1E14u >> 1] = 0x842Eu;
    return 1u;
}

/* 0x08022404 / 0x0802240C: the watchdog's counts cleared (G+0x190, G+0xC, G+0x192), page A (when the 68000 is not
   parked yet), page B, the "..." line; a page that is not a 0x80 block posts the chip's fatal code */
static void mw_pages(uint32_t a)
{
    disp_g.wd_arm = 0u;                                     /* 0x0802240E */
    disp_g.f81[3] = 0u;                                     /* 0x08022412 */
    disp_g.wd_count = 0u;                                   /* 0x08022414 */
    if (a && !mw_page_a_load(mw_pga))                       /* 0x08022416-0x08022428 */
        chip_trace(0x40000007u, 0x80u, 0x28u);
    if (!mw_page_b_load(mw_pgb))                            /* 0x0802242C-0x0802243C */
        chip_trace(0x40000000u, 0x80u, 0x28u);
    if (!mw_dots())                                         /* 0x08022440-0x08022450 */
        chip_trace(0x40000000u, 0x80u, 0x28u);
}

/* 0x08022460: the access point and its password both "home" (the cart program's default), no BSSID */
static void mw_home(void)
{
    uint8_t s[5];
    uint32_t i;
    mw_str(s, S_HOME);                                      /* 0x08022462-0x08022468 */
    for (i = 0; i < 4u; i++) {                              /* 0x0802246C-0x0802247E */
        MW8(drv, 0x10u + i) = s[i];
        MW8(drv, i) = s[i];
    }
    for (i = 0x31u; i <= 0x34u; i++)                        /* 0x08022480-0x08022498 */
        MW8(drv, i) = 0u;
    MW8(drv, 0x14) = 0u;                                    /* 0x0802249C */
    MW8(drv, 0x04) = 0u;                                    /* 0x0802249E */
    MW8(drv, 0x35) = 0u;                                    /* 0x080224A4 */
    MW8(drv, 0x36) = 0u;                                    /* 0x080224A6 */
}

/* 0x080224B4: line 1 to $1E10 and line 2 to $1E50 as char + $8400, each to its NUL or 32 characters, the rest 0 */
static void mw_lines(const uint8_t *l1, const uint8_t *l2)
{
    volatile uint16_t *ram = brd_cart_ram();
    uint32_t i;
    for (i = 0; i < 32u && l1[i]; i++)
        ram[(0x1E10u >> 1) + i] = (uint16_t)(l1[i] + 0x8400u);
    for (; i < 32u; i++)
        ram[(0x1E10u >> 1) + i] = 0u;
    for (i = 0; i < 32u && l2[i]; i++)
        ram[(0x1E50u >> 1) + i] = (uint16_t)(l2[i] + 0x8400u);
    for (; i < 32u; i++)
        ram[(0x1E50u >> 1) + i] = 0u;
}

/* the lines a call ends with: line 1 a string of the cart program (0) or "...", line 2 the spaces or buf; nothing
   if the player's ROM did not give the cart program's text (mw_text.c refused it) */
static void mw_show(uint32_t a1, uint32_t n1, const uint8_t *l2)
{
    uint8_t l1[0x21], sp[0x21];
    if (!mw_text_ok())
        return;
    if (a1) {
        mw_str(l1, a1, n1);
    } else {
        l1[0] = l1[1] = l1[2] = 0x2Eu;                      /* 0x0802261A: 0x002E2E2E, "..." */
        l1[3] = 0u;
    }
    if (!l2) {
        mw_str(sp, S_SPACES);
        l2 = sp;
    }
    mw_lines(l1, l2);
}

/* states 2 and 3 (0x08022744-0x08022832): line 2 = '@', the access point, '(' (overwritten when the password is as
   long as the name), the password (state 3) or '*' for each of its characters (state 2), ')'; line 1 from the module's
   state, and the waits that try "home" (6000 calls) or ask the driver to start again (12000) */
static void mw_s23(uint32_t cnt)
{
    uint8_t b[100];
    uint32_t i, n, k, st = MW16(mw, MW_SCREEN);
    for (i = 0; i < 0x20u; i++)                             /* 0x08022744-0x08022750 */
        b[i] = 0x20u;
    b[0] = 0x40u;                                           /* 0x08022752-0x08022756 */
    for (n = 0; n != 0x21u; ) {                             /* 0x08022758-0x0802276A */
        uint8_t c = MW8(drv, 0x10u + n);
        if (!c)
            break;
        b[++n] = c;
    }
    b[2u * n + 1u] = 0x28u;                                 /* 0x0802276C-0x08022772 */
    for (k = 0; k < 0x10u; k++) {                           /* 0x08022778-0x080227A6 */
        uint8_t c = MW8(drv, k);
        if (!c)
            break;
        b[n + k + 2u] = st == 3u ? c : 0x2Au;
    }
    b[2u * k + n + 2u] = 0x29u;                             /* 0x080227A8-0x080227AE */
    if (!MW8(drv, 0x58)) {                                  /* 0x080227B0-0x080227BA: no module */
        mw_show(S_NOFOUND, b);
        return;
    }
    if (MW8(drv, 0x48) && MW8(drv, 0x107F) == 1u) {         /* 0x080227BC-0x080227CE: ready, the power profile AUTO */
        mw_show(S_NOPOWER, b);
        return;
    }
    if (MW8(drv, 0x49)) {                                   /* 0x080227D0-0x08022804: joined */
        if (cnt > 0x2EE0u) {
            mw_op(1u);
            MW16(mw, MW_SCREEN) = 1u;
        }
        else if (MW8(mw, 0x164)) {
            MW16(mw, MW_SCREEN) = 4u;
            MW16(mw, 0x12) = 0xFFFFu;
            MW32(mw, MW_SCRCNT) = 0u;
        }
        mw_show(0u, 0u, b);
        return;
    }
    if (st == 2u) {                                         /* 0x08022806-0x08022820 */
        if (cnt > 0x1770u) {
            mw_home();
            MW32(mw, MW_SCRCNT) = 0u;
            MW16(mw, MW_SCREEN) = 3u;
        }
        mw_show(S_CONNECTING, b);
    }
    else {                                                  /* 0x08022822-0x08022832 */
        if (cnt > 0x1770u) {
            mw_op(1u);
            MW32(mw, MW_SCRCNT) = 0u;
        }
        mw_show(S_APCON, b);
    }
}

/* the end of state 1 (0x08022720-0x08022742): the count, the music and the sound effects stopped (the sequencer's
   and the SFX engine's ready words), state 3 with "home" if C6's read of the MegaWire record succeeded, else 2 */
static void mw_s1_end(void)
{
    MW32(mw, MW_SCRCNT) = 0u;                               /* 0x08022724 */
    S.ready = 0u;                                           /* 0x08022726: 0x2000C164 */
    SFX.ready = 0u;                                         /* 0x0802272A: 0x20012BD4 */
    mw_text_start();                                        /* ours: the cart program's text, from the ROM, whole */
    while (!mw_text_run(0x4000u))
        ;
    if (MW32(mw, MW_HOME)) {                                /* 0x0802272C-0x08022738 */
        mw_home();
        MW16(mw, MW_SCREEN) = 3u;
    }
    else
        MW16(mw, MW_SCREEN) = 2u;
    mw_show(0u, 0u, 0);                                     /* 0x0802273E: "..." and the spaces */
}

/* one step of the screen loop 0x080225F8 (the thread, once due) */
__attribute__((optimize("no-jump-tables")))
void mw_screen_step(void)
{
    uint32_t cnt;
    switch (mw_scr.ph) {
    case PH_CALL:                                           /* 0x0802266E: each call waits 960,000 SysTick counts */
        mw_scr.due = brd_now() + MW_WAIT(960000u);
        mw_scr.ph = PH_BODY;
        return;
    case PH_S1A:                                            /* 0x080226AE-0x080226CA: after the 64 waits */
        MW8(drv, 0x107F) = 2u;
        if (brd_freg_rd(BRD_FREG_FEA) == 0x1234u) {         /* the 68000 already parked */
            mw_pages(0u);                                   /* 0x080226FC-0x08022710 */
            st_set(0u, ST_FE4, 0x660u);
            st_set(1u, ST_FE4, 0x4010u);                    /* 0x08022712-0x0802271E */
            mw_s1_end();
            mw_scr.ph = PH_CALL;
        }
        else {
            brd_md_hold(1u);                                /* ours: the 68000 held when the chip's waits end
                                                               (+74 ms), then the page work, which takes ours ~7 ms
                                                               on the RV32 board model; held, the 68000 sees no
                                                               page store, and it restarts from reset on page A */
            mw_pages(1u);                                   /* 0x080226C8-0x080226DA */
            st_set(0u, ST_FE4, 0x4660u);                    /* bit 14 cleared: the cart's hold (docs/BOOT_SPEC.md 11) */
            mw_scr.due += MW_WAIT(300u * 96000u);           /* 0x080226DC-0x080226EA: 300 waits of 96,000 */
            mw_scr.ph = PH_S1B;
        }
        return;
    case PH_S1B:                                            /* 0x080226EC-0x0802271E */
        brd_freg_wr(BRD_FREG_FEA, 0x1234u);                 /* the park word */
        st_set(1u, ST_FE4, 0x4010u);
        brd_md_hold(0u);                                    /* ours: bit 14 set = the 68000 starts on page A */
        mw_s1_end();
        mw_scr.ph = PH_CALL;
        return;
    default:                                                /* PH_BODY: after the call's first wait */
        break;
    }
    cnt = MW32(mw, MW_SCRCNT) + 1u;                         /* 0x08022674-0x0802267E */
    MW32(mw, MW_SCRCNT) = cnt;
    mw_scr.ph = PH_CALL;
    switch (MW16(mw, MW_SCREEN)) {                          /* 0x08022680-0x08022688 */
    case 1:                                                 /* 0x080226A0-0x080226AC: 64 waits of 96,000 */
        mw_pack(mw_pga, 2u * MW_PAGE_A_WORDS, mw_pga_byte); /* ours: the pages packed as the chip's loader reads them
                                                               (the cart's sit packed in its flash), here inside the
                                                               wait, so the hold comes at the chip's time */
        mw_pack(mw_pgb, 0x1000u, mw_pgb_byte);
        mw_scr.due += MW_WAIT(64u * 96000u);
        mw_scr.ph = PH_S1A;
        return;
    case 2: case 3:
        mw_s23(cnt);
        return;
    case 4: case 5:                                         /* 0x08022834 / 0x08022B38: the update (a module) */
        mw_not_ported(0x08022834u);
        return;
    case 6:                                                 /* 0x08022BEC-0x08022C12: the update done */
        if (cnt > 0x1C2u)
            brd_full_reset();                               /* 0x0801FCC8: the chip's own reset (BOOT-9) */
        if (cnt == 0x190u)
            st_set(0u, ST_FE4, 0x4000u);
        mw_show(S_SUCCESS, 0);
        return;
    case 7:                                                 /* 0x0802269A */
        mw_show(S_ERROR, 0);
        return;
    default:                                                /* 0x0802273E: any other state */
        mw_show(0u, 0u, 0);
        return;
    }
}
