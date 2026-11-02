/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* interim/s1/vu_s1.c - the Boom Box VU rows, moved from legacy/026/paprium.c.
 *
 * The 0.2.6 code unchanged (its notes are in paprium.c: the 26 voices' {L, R} words at cart RAM $1B98-$1BFF, the row
 * clock = (2 * header[0x07] + the 0xFA operand) ticks of 10.01257 ms), except its time base: 0.2.6 read the RTL's
 * ms counter (FPGAIO slot 1, CLK_FREQ / 1000 cycles a tick), which MCU interface v1.0 retires. s1_ms() rebuilds the
 * same counter from the board timer (CLK_MS_CYCLES cycles a tick, the 0.2.6 truncation kept), so the row grid is
 * the 0.2.6 grid at either clock.
 * The rows run on the timer wheel (interim/s1/audio_s1.c wh_vu, L2a, the timer interrupt level) at the instant the row
 * is due (s1_vu_deadline: the board time at which s1_ms() reaches vu_due), where 0.2.6's main loop polled for it.
 * 0.2.6 ran start, stop and the rows in one loop; here start (the 8C job, L3) and stop (8D, L1) can come in the middle
 * of a row (L2a, MEI open), so start runs with interrupts off, every voice of a row is one interrupts-off section, and
 * a generation count bumped by start and stop drops a row they cut (the stop's zeros are not overwritten). */
#include "appmain.h"
#include "s1_interim.h"

#define PPM_VU_BASE     0x1B98      /* 68000 address of voice 0's L word */
#define PPM_VU_VOICES   26
#define PPM_VU_ON       0x00E0      /* level the cart writes for a sounding voice */

/* the 0.2.6 ms counter, from the board timer; called often enough (the timer wraps in 80 s NTSC) by every user.
   The divisor goes through s1_clk (appmain.h), so the code divides with divu at every clock. */
static u32 ms_last, ms_frac, ms_count;
static u32 s1_ms(void)
{
    u32 s = brd_irq_save();
    u32 now = brd_now();
    u32 div = s1_clk(CLK_MS_CYCLES);
    ms_frac += now - ms_last;
    ms_last = now;
    ms_count += ms_frac / div;
    ms_frac %= div;
    now = ms_count;
    brd_irq_restore(s);
    return now;
}

static u32 vu_mod   = 0;
static u16 vu_secs  = 0;
static u16 vu_loop  = 0;
static u16 vu_bars  = 0;
static u16 vu_seg   = 0;
static u16 vu_row   = 0;
static u32 vu_due   = 0;
static u32 vu_rem   = 0;
static u16 vu_base  = 8;
static u8  vu_fa    = 0;
static u8  vu_on    = 0;
static u32 vu_gen   = 0;    /* start / stop since a row began */
#ifndef AUDIO_BUG
#define AUDIO_BUG 0         /* tests/s1/audio_tests.c's negative control 2: a row cut by a stop is not dropped */
#endif

static u8 vu_mb(u32 off) { return ppmio.sdram[(vu_mod + off) ^ 1]; }

static void vu_put(u32 a, u16 v)
{
    vu8 *ram = (vu8 *)ppmio.ramdp;
    ram[a + 1] = (u8)(v >> 8);
    ram[a] = (u8)v;
}

static void vu_all(u16 v)
{
    for (int ch = 0; ch < PPM_VU_VOICES; ch++) {
        vu_put(PPM_VU_BASE + ch * 4, v);
        vu_put(PPM_VU_BASE + ch * 4 + 2, v);
    }
}

void s1_vu_start(u32 mod_addr)
{
    u32 s = brd_irq_save();
    vu_gen++;
    vu_mod = mod_addr;
    vu_base = 2 * (vu_mb(0x07) ? vu_mb(0x07) : 4);
    vu_fa = 0;
    vu_secs = vu_mb(0x08);
    vu_loop = (vu_mb(0x09) < vu_secs) ? vu_mb(0x09) : 0;
    vu_bars = vu_mb(0x0A) ? vu_mb(0x0A) : 0x100;
    vu_seg = 0;
    vu_row = 0;
    vu_rem = 0;
    vu_due = s1_ms();
    vu_on = (vu_secs != 0);
    if (!vu_on)
        vu_all(0);
    brd_irq_restore(s);
    s1_vu_kick();
}

void s1_vu_stop(void)
{
    u32 s = brd_irq_save();
    vu_gen++;
    vu_on = 0;
    vu_all(0);
    brd_irq_restore(s);
    s1_vu_kick();
}

uint32_t s1_vu_deadline(uint32_t *t)
{
    u32 s = brd_irq_save(), on = vu_on;
    if (on) {
        s32 ahead = (s32)(vu_due - s1_ms());                /* s1_ms leaves ms_last / ms_frac at this instant */
        *t = ahead <= 0 ? brd_now() : ms_last - ms_frac + (u32)ahead * s1_clk(CLK_MS_CYCLES);
    }
    brd_irq_restore(s);
    return on;
}

uint32_t s1_vu_update(void)
{
    u32 s = brd_irq_save(), gen = vu_gen;
    if (!vu_on || (s32)(s1_ms() - vu_due) < 0) {
        u32 on = vu_on;
        brd_irq_restore(s);
        return on;
    }
    brd_irq_restore(s);
    for (int ch = 0; ch < PPM_VU_VOICES; ch++) {
        s = brd_irq_save();
        if (vu_gen != gen && AUDIO_BUG != 2) {              /* a start / stop cut this row: dropped */
            u32 on = vu_on;
            brd_irq_restore(s);
            return on;
        }
        u32 po = 0xD8 + ((u32)ch * vu_secs + vu_seg) * 2;
        u32 ptr = ((u32)vu_mb(po) << 8) | vu_mb(po + 1);
        u8 idx = vu_mb(ptr + vu_row);
        u16 lvl = idx ? PPM_VU_ON : 0;
        vu_put(PPM_VU_BASE + ch * 4, lvl);
        vu_put(PPM_VU_BASE + ch * 4 + 2, lvl);
        if (idx) {
            u32 ev = ptr + vu_bars + (u32)idx * 8;
            for (int k = 2; k < 8; k += 2)
                if (vu_mb(ev + k) == 0xFA)
                    vu_fa = vu_mb(ev + k + 1) & 0x0F;
        }
        brd_irq_restore(s);
    }
    s = brd_irq_save();
    if (vu_gen != gen) {
        u32 on = vu_on;
        brd_irq_restore(s);
        return on;
    }
    u32 num = (u32)(vu_base + vu_fa) * 1001257u + vu_rem;
    vu_due += num / 100000u;
    vu_rem = num % 100000u;
    if (++vu_row >= vu_bars) {
        vu_row = 0;
        if (++vu_seg >= vu_secs)
            vu_seg = vu_loop;
    }
    brd_irq_restore(s);
    return 1u;
}
