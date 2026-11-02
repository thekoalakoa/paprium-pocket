/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/s1/wdog_tests.c - host test of the watchdog, heartbeat and fatal halt, which work as the cart chip's (D35 of
 * our firmware audit; docs/BOOT_SPEC.md BOOT-16; test T10 of our 0.3.0 study, cited in docs/STAGE1_PLAN.md section
 * 2 row 8; the fuzz check FZ10 of docs/STAGE1_PLAN.md section 4.7; W1-W10 below are this test's cases) on the x86 fake
 * board, through the real dispatcher (81, 9494, 84, A858 posted by the 68000 side) and the real timer wheel. Built and
 * run by tools/fwbuild.py s1 at the build clock; tests/check_clock.py --images runs every s1 host test again at the PAL
 * clock (53,203,424 Hz), so FZ10 is checked at both clocks. Exit 1 on a failed check.
 *
 *   W1  app init leaves the count at 1 (0x0801F9F8: armed, not running): no trip in 10 s without a 9494, with or
 *       without 81 (T-B9); the first 9494 starts it even without an 81, as on the chip
 *   W2  9494 every frame for 30 s: no trip; the count stays at 2-4
 *   W3  the 9494s stop: the trip comes on the 39th TIM7 tick (count 2 -> 41), 38-39 periods after the last 9494, with
 *       the chip's writes: $1FEE := 0xAF5B, $1FE4 := 0x4200 (direct: the shadow keeps its value), event 0x400000FA
 *   W4  FZ10 menu gate: the Pocket menu open 10 s (no 9494) -> no trip; the gated ticks do not count; after the menu
 *       closes the count goes on from where it was
 *   W5  84 (the blank-save mini-game): no trip in 30 s, and the 9494s that follow do not start it again; A858 the
 *       same
 *   W6  81 bit 4: the trip resets the MCU: $1FE4 := 0, 300 ms, $1FE4 := 0, brd_full_reset
 *   W7  the fatal halt: the LED waits (10 ms + 1 ms per clear code bit + 10 ms), then the "WE SUX" poll every 10 us;
 *       W, E, space, S, U, X, 0 one per poll resets the MCU; a broken sequence does not
 *   W8  the heartbeat: inert at app start's 1; armed (> 1) it clears $1FE4 bit 13 after 2,400 ticks and stops; with
 *       $1FE4 bit 11 set it is fatal (0x400000FB)
 *   W9  85 is fatal (0x400000FA) through the same halt
 *   W10 the TIM7 grid: one tick per CLK_TIM7, a held-up L2a merges the missed periods into one tick */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#include "board.h"
#include "sched.h"
#include "sched_hooks.h"
#include "disp.h"
#include "disp_bodies.h"
#include "appinit.h"
#include "wdog.h"
#include "fatal.h"

static int fails, checks;
#define CHECK(c) do { checks++; if (!(c)) { fails++; printf("FAIL wdog_tests.c:%d %s\n", __LINE__, #c); } } while (0)

/* ---- bodies: none is reached by the posts of this test -------------------------------------------------------- */
void body_88(uint8_t lo) { (void)lo; }
void body_c9(uint8_t lo) { (void)lo; }
void body_ca(uint8_t lo) { (void)lo; }
void body_8d(uint8_t lo) { (void)lo; }
void body_d1(uint8_t lo) { (void)lo; }
void body_d2(uint8_t lo) { (void)lo; }
void body_d3(uint8_t lo) { (void)lo; }
void body_d5(uint8_t lo) { (void)lo; }
void body_ad(uint8_t lo) { (void)lo; }
void body_ae(void) { }
void body_af(uint8_t m, uint8_t q) { (void)m; (void)q; }
#if !PPM_RELEASE
void body_af_replied(void) { }
#endif
void body_b0(void) { }
void body_b1(void) { }
void body_ec(uint16_t s) { (void)s; }
uint32_t body_block_addr(uint16_t b) { return (uint32_t)b * 0x200u; }
uint32_t body_load_list(const uint32_t **l) { static const uint32_t none[1]; *l = none; return 0u; }
void body_dec_scratch(void) { }
void body_db(uint16_t a0, uint16_t a1, uint16_t a2, uint8_t mode) { (void)a0; (void)a1; (void)a2; (void)mode; }
void body_da_direct(uint32_t src, uint16_t dst, uint8_t mode) { (void)src; (void)dst; (void)mode; }
void body_e7(void) { }
uint32_t job_unpack(const disp_job_t *j) { (void)j; return 0u; }
uint32_t job_eep_read(const disp_job_t *j) { (void)j; return 0u; }
uint32_t job_eep_write(const disp_job_t *j) { (void)j; return 0u; }
void job_scale_save(void) { }
void job_scale_setup(void) { }
void job_rescale(const uint16_t a[4]) { (void)a; }
void job_restore(void) { }
uint32_t job_setup(const uint32_t l[8], uint32_t mw) { (void)l; (void)mw; return SETUP_ENG | SETUP_MW | SETUP_SFX | SETUP_SEQ; }

/* ---- the halt and the reset end a scenario: the board point inside the poll / the reset jumps back here --------- */
static jmp_buf jb;
static int halted, reset_seen, watch_halt;
static uint32_t halt_t, reset_t;
static const uint8_t *seq;              /* bytes the 68000 writes into $1FEA, one per poll (NULL: none) */
static uint32_t seq_n, seq_at, polls_max;
static uint32_t log_mark;               /* hb.log index where the scenario's halt writes start */
static uint32_t log_scan, fe4zero_t;    /* the time of the first $1FE4 := 0 after log_mark (W6) */

void hb_full_reset_hook(void)
{
    reset_seen = 1;
    reset_t = hb.now;
    longjmp(jb, 2);
}

static void on_point(void)
{
    if (watch_halt && !fe4zero_t) {
        if (log_scan < log_mark)
            log_scan = log_mark;
        for (; log_scan < hb.nlog; log_scan++)
            if (hb.log[log_scan] == (BRD_FREG_FE4 << 16)) {
                fe4zero_t = hb.now;
                break;
            }
    }
    if (!watch_halt || !fatal_rec.code)
        return;
    if (!halted) {
        halted = 1;
        halt_t = hb.now;
    }
    if (fatal_rec.polls >= polls_max)
        longjmp(jb, 1);                                     /* the poll would go on for ever: the scenario ends */
    if (seq && fatal_rec.polls >= seq_at && fatal_rec.polls < seq_n) {
        seq_at = fatal_rec.polls + 1u;                      /* one byte per poll: written right after poll n */
        hb.freg[BRD_FREG_FEA >> 1] = seq[fatal_rec.polls];  /* the 68000's word write (its low byte is polled) */
    }
}

/* ---- time ------------------------------------------------------------------------------------------------------ */
static void adv(uint64_t cyc)          /* fake time in steps of 16k cycles: the wheel fires within one step */
{
    while (cyc) {
        uint32_t d = cyc > 16384u ? 16384u : (uint32_t)cyc;
        hb.now += d;
        hb.cycles += d;
        cyc -= d;
        (void)brd_now();
    }
}
#define MS(x)   ((uint64_t)(x) * CLK_MS_CYCLES)
#define FRAME   (CLK_MS_CYCLES * 16u + CLK_MS_CYCLES * 2u / 3u)   /* 16.67 ms */

static void ticks(uint32_t n)           /* until n more TIM7 ticks have run */
{
    uint32_t t0 = wdog_stats.ticks;
    while (wdog_stats.ticks - t0 < n)
        adv(16384u);
}

static void post_b(uint16_t w) { hb_68k_write(BRD_FREG_FEA, w); (void)brd_now(); CHECK(brd_freg_rd(BRD_FREG_FEA) == 0u); }
static void post_a(uint16_t w) { hb_68k_write(BRD_FREG_FEC, w); (void)brd_now(); CHECK(brd_freg_rd(BRD_FREG_FEC) == 0u); }
static uint32_t last_9494, ticks_9494;
static void frames(uint32_t n, int tick)
{
    while (n--) {
        if (tick) {
            post_a(0x9494u);
            last_9494 = hb.now;
            ticks_9494 = wdog_stats.ticks;
        }
        adv(FRAME);
    }
}

static void boot(void)
{
    hb_reset();
    hb.on_point = on_point;
    memset((void *)&fatal_rec, 0, sizeof fatal_rec);
    memset(&wdog_stats, 0, sizeof wdog_stats);
    halted = reset_seen = watch_halt = 0;
    log_scan = fe4zero_t = 0u;
    seq = NULL;
    seq_n = seq_at = 0u;
    polls_max = 50u;
    sched_init();
    app_start();
    boot_mw_status();
    brd_cause_ack(BRD_CAUSE_ALL);
    brd_msi(0u);
    brd_timer_disarm();
    wdog_start();
    brd_lines_on(BRD_LINES_ALL);
    brd_irq_enable();
    brd_md_hold(0u);
}

/* the halt's register writes since log_mark: $1FEE := 0xAF5B then $1FE4 := 0x4200 */
static int halt_writes_ok(void)
{
    uint32_t i, k = 0;
    static const uint32_t want[2] = { (BRD_FREG_FEE << 16) | 0xAF5Bu, (BRD_FREG_FE4 << 16) | 0x4200u };
    for (i = log_mark; i < hb.nlog && k < 2u; i++)
        if (hb.log[i] == want[k])
            k++;
        else if ((hb.log[i] >> 24) == 0u)
            return 0;
    return k == 2u;
}

/* run until the halt or a reset (or the time is up); returns 1 halt, 2 reset, 0 nothing */
static uint64_t run_left;               /* static: kept across the longjmp */
static int run_until_halt(uint64_t cyc, int tick)
{
    int r;
    run_left = cyc;
    watch_halt = 1;
    hb.nlog = 0u;                                           /* the fake board keeps 4,096 log entries */
    log_mark = 0u;
    r = setjmp(jb);
    if (r == 0) {
        while (run_left >= FRAME) {
            frames(1u, tick);
            run_left -= FRAME;
        }
        adv(run_left);
        watch_halt = 0;
        return 0;
    }
    watch_halt = 0;
    hb.on_point = on_point;
    return r;
}

int main(void)
{
    int r;
    uint32_t t, k;

    /* W1: app init arms (1), the count runs only from the first 9494 */
    boot();
    CHECK(disp_g.wd_arm == 1u && disp_g.wd_count == 1u && disp_g.g194 == 1u);   /* app start + app init */
    r = run_until_halt(MS(10000), 0);
    CHECK(r == 0 && disp_g.wd_arm == 1u && wdog_stats.ticks >= 97u);
    post_a(0x9494u);                                        /* a 9494 with no 81 before it: running */
    CHECK(disp_g.wd_arm == 2u && disp_g.wd_count == 0u);
    boot();
    post_b(0x810Eu);
    CHECK(disp_g.wd_arm == 1u && disp_g.f81[3] == 0u);
    r = run_until_halt(MS(10000), 0);
    CHECK(r == 0 && disp_g.wd_arm == 1u);

    /* W2: 9494 every frame for 30 s */
    r = run_until_halt(MS(30000), 1);
    CHECK(r == 0 && disp_g.wd_arm >= 2u && disp_g.wd_arm <= 4u && wdog_stats.arm_max <= 4u);

    /* W3: the 9494s stop: the trip on the 39th tick */
    r = run_until_halt(MS(6000), 0);
    CHECK(r == 1 && fatal_rec.code == 0x400000FAu && fatal_rec.a == 0x80u && fatal_rec.b == 0x28u);
    CHECK(wdog_stats.ticks - ticks_9494 == 39u && disp_g.wd_arm == 41u);
    k = (uint32_t)(halt_t - last_9494);
    CHECK(k > 38u * CLK_TIM7 - 2u * 16384u && k <= 39u * CLK_TIM7 + 2u * 16384u);
    printf("trip %u cycles (%.3f s) after the last 9494, %u ticks\n", k, (double)k / BRD_CLK_HZ,
           wdog_stats.ticks - ticks_9494);
    CHECK(halt_writes_ok() && st_shadow(ST_FE4) != 0x4200u);

    /* W4: FZ10, the menu gate */
    boot();
    post_b(0x810Fu);
    frames(10u, 1);
    hb.options |= BRD_OPT_MENU;                             /* the Pocket menu opens: the 68000 is paused */
    t = wdog_stats.ticks;
    r = run_until_halt(MS(10000), 0);
    CHECK(r == 0 && wdog_stats.gated == wdog_stats.ticks - t && wdog_stats.gated >= 97u && disp_g.wd_arm <= 4u);
    k = disp_g.wd_arm;
    hb.options &= ~BRD_OPT_MENU;
    r = run_until_halt(MS(1000), 0);                        /* closed, the game has not posted yet: the count goes on */
    CHECK(r == 0 && disp_g.wd_arm > k);
    r = run_until_halt(MS(30000), 1);                       /* the 9494s come back */
    CHECK(r == 0 && disp_g.wd_arm <= 4u);
    hb.options |= BRD_OPT_MENU;                             /* menu open 20 s, then closed with no 9494: trips 39 */
    r = run_until_halt(MS(20000), 0);                       /* counted ticks after the last 9494 */
    CHECK(r == 0);
    hb.options &= ~BRD_OPT_MENU;
    t = wdog_stats.ticks;
    k = disp_g.wd_arm;
    r = run_until_halt(MS(6000), 0);
    CHECK(r == 1 && wdog_stats.ticks - t == 41u - k);

    /* W5: 84 and A858 switch it off; app start leaves it off */
    boot();
    post_b(0x810Eu);
    frames(10u, 1);
    post_b(0x8400u);                                        /* the blank-save mini-game: posts nothing for ~29 s */
    CHECK(disp_g.wd_arm == 0u && disp_g.wd_count == 0u && disp_g.f81[3] == 0u);
    r = run_until_halt(MS(30000), 0);
    CHECK(r == 0 && disp_g.wd_arm == 0u);
    r = run_until_halt(MS(10000), 1);                       /* 9494s after the 84 do not start it again */
    CHECK(r == 0 && disp_g.wd_arm == 0u);
    r = run_until_halt(MS(10000), 0);
    CHECK(r == 0);
    boot();
    post_b(0x810Eu);
    frames(10u, 1);
    post_b(0xA858u);
    CHECK(disp_g.wd_arm == 0u);
    r = run_until_halt(MS(30000), 0);
    CHECK(r == 0);

    /* W6: 81 bit 4: the trip resets the MCU */
    boot();
    post_b(0x811Eu);
    CHECK(disp_g.f81[3] == 1u);
    frames(10u, 1);
    r = run_until_halt(MS(6000), 0);
    CHECK(r == 2 && reset_seen && fatal_rec.code == 0u && fe4zero_t);
    k = (uint32_t)(reset_t - fe4zero_t);                    /* 300 x 1 ms between the trip's store and the reset */
    CHECK(k >= 300u * CLK_MS_CYCLES && k <= 300u * CLK_MS_CYCLES + 300u * 64u);
    printf("trip with 81 bit 4: reset %u cycles (%.3f ms) after $1FE4 := 0\n", k, 1000.0 * k / BRD_CLK_HZ);
    {
        uint32_t i, z = 0, first = 0, last = 0;             /* $1FE4 := 0 twice: the trip, then the reset routine */
        for (i = log_mark; i < hb.nlog; i++)
            if (hb.log[i] == (BRD_FREG_FE4 << 16)) {
                if (!z++)
                    first = i;
                last = i;
            }
        CHECK(z == 2u && last > first);
    }

    /* W7: the fatal halt and the backdoor */
    {
        static const uint8_t ok_seq[7] = { 'W', 'E', ' ', 'S', 'U', 'X', 0 };
        static const uint8_t bad_seq[9] = { 'W', 'E', 'E', ' ', 'S', 'U', 'X', 0, 0 };
        boot();
        post_b(0x810Eu);
        frames(10u, 1);
        seq = ok_seq;
        seq_n = 7u;
        polls_max = 100u;
        r = run_until_halt(MS(6000), 0);
        CHECK(r == 2 && reset_seen && fatal_rec.polls == 7u);
        /* the LED waits: 10 ms, 1 ms for each clear bit of 0x00FA (bits 0, 2, 8-15: 10), 10 ms; then 7 polls of 10 us */
        k = (uint32_t)(reset_t - halt_t);
        CHECK(k >= 30u * CLK_MS_CYCLES + 6u * CLK_FATAL_POLL && k <= 30u * CLK_MS_CYCLES + 8u * CLK_FATAL_POLL + 4096u);
        printf("halt to reset %u cycles (%.3f ms)\n", k, 1000.0 * k / BRD_CLK_HZ);
        boot();
        post_b(0x810Eu);
        frames(10u, 1);
        seq = bad_seq;
        seq_n = 9u;
        polls_max = 60u;
        r = run_until_halt(MS(6000), 0);
        CHECK(r == 1 && !reset_seen && fatal_rec.polls == 60u);
    }

    /* W8: the heartbeat */
    boot();
    r = run_until_halt(MS(300000), 0);                      /* app start's 1: inert for 300 s */
    CHECK(r == 0 && disp_g.g194 == 1u && (st_shadow(ST_FE4) & 0x2000u));
    disp_g.g194 = 2u;                                       /* armed (the chip itself never does this) */
    ticks(2398u);
    CHECK(disp_g.g194 == 2400u && (st_shadow(ST_FE4) & 0x2000u));
    ticks(1u);
    CHECK(disp_g.g194 == 0u && !(st_shadow(ST_FE4) & 0x2000u) && !(brd_freg_rd(BRD_FREG_FE4) & 0x2000u));
    ticks(100u);
    CHECK(disp_g.g194 == 0u);
    boot();
    disp_g.g194 = 2u;
    st_set(1u, ST_FE4, 0x0800u);                            /* the EEPROM-job flag */
    r = run_until_halt(MS(200), 0);
    CHECK(r == 1 && fatal_rec.code == 0x400000FBu && halt_writes_ok());

    /* W9: 85 */
    boot();
    hb.nlog = 0u;                                           /* the fake board keeps 4,096 log entries */
    log_mark = 0u;
    watch_halt = 1;
    if ((r = setjmp(jb)) == 0) {
        hb_68k_write(BRD_FREG_FEA, 0x8500u);
        (void)brd_now();
        adv(MS(100));
    }
    watch_halt = 0;
    CHECK(r == 1 && fatal_rec.code == 0x400000FAu);

    /* W10: the TIM7 grid and the merge */
    boot();
    t = wdog_stats.ticks;
    adv((uint64_t)CLK_TIM7 * 10u + CLK_TIM7 / 2u);
    CHECK(wdog_stats.ticks - t == 10u && wdog_stats.merged == 0u);
    hb.now += 5u * CLK_TIM7;                                /* L2a held up for 5 periods (the next tick was about */
    adv(CLK_TIM7 / 4u);                                     /* half a period away): one tick, 4 periods merged */
    CHECK(wdog_stats.ticks - t == 11u && wdog_stats.merged == 4u);
    adv((uint64_t)CLK_TIM7 * 3u);
    CHECK(wdog_stats.ticks - t == 14u && (wheel_armed() & (1u << WH_WDOG)));

    printf("wdog_tests: %d checks, %d failed\n", checks, fails);
    return fails ? 1 : 0;
}
