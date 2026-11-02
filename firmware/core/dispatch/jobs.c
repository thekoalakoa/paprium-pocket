/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/dispatch/jobs.c - the 16-slot job queue and the main loop's job step, as the cart chip has them. The cart chip
 * is the STM32 microcontroller on the real cartridge; this does the same steps (written by our team from our own study
 * of how the cart behaves). Hex numbers in the comments are cart chip addresses, kept as references; $B4468-style
 * numbers are 68000 addresses in the game.
 *
 * Queue (the cart chip's G+0x12 write index, G+0x13 read index, 16 x 20-byte slots from G+0x14; G is its global
 * block): L1 (the level-1 interrupt that reads a post) fills the slot at (wr & 0xF) and advances wr, and raises MSI,
 * the software interrupt; L2c (core/sched l2b_msi; in earlier versions the thread, as in the cart chip's main loop)
 * runs the slot at (rd & 0xF), then advances rd and rewrites $1FE6 bit 14 = "queue not empty" in one interrupts-off
 * section (0x0801A5E6-0x0801A608). Full = ((wr + 1) ^ rd) & 0xF == 0, so 15 slots are usable; F4 needs two
 * (0x0801B4F4-0x0801B50C).
 * Job step (0x0801A3AC-0x0801A5E4, one job per main-loop pass): a type outside 1-12 fails (trace 1); 1-4 unpack
 * (failure: trace 0x11 / 0x12 / 4; 8C's module init: trace 0xD); 5/6 EEPROM read (the driver reports itself);
 * 7 EEPROM write (failure: trace 9); 8 the scaling save once, then the session; 9 the rescale when a session is
 * open, then pending := 0; 10 the restore when saved, then the session closes; 11/12 the setup. A failure sets
 * $1FE6 bit 8 when the slot's fail flag (+0x14) is set. The rest of the main-loop pass (bit 3 := music playing,
 * the 81 trace counters and Boom Box feed, the MegaWire screen) belongs to the MegaWire code and the song engine
 * (README.md). FW_S5 (board/board.h) builds the full firmware on MCU interface v1.3, FW_MW the MegaWire code; the
 * FW_S5 = 0 build is the earlier firmware. */
#include <stdint.h>
#include "board.h"
#include "sched.h"
#include "sched_hooks.h"
#include "disp.h"
#include "disp_bodies.h"
#include "stats.h"
#if FW_MW
#include "mw.h"
#endif
#if FW_S5
#include "song.h"
#endif

uint32_t disp_queue_full(uint32_t free_needed)
{
    return ((((uint32_t)disp_g.q_wr + free_needed) ^ disp_g.q_rd) & 0xFu) == 0u;
}

disp_job_t *disp_job_slot(uint32_t ahead) { return &disp_g.q[(disp_g.q_wr + ahead) & 0xFu]; }

void disp_job_commit(uint32_t n)
{
    disp_g.q_wr = (uint8_t)(disp_g.q_wr + n);
    sched_work_post();                                      /* L2c runs it, above the thread's brain call */
}

/* ---- the C6 hold (docs/ALLOWLIST.md, row B34; B Jam's decision of 2026-10-16) -------------------------------------
 * The game waits for C6 in a loop ($B4468-$B458A): count = 14, then after the C600 post it reads $1FEA (and $1FE6),
 * and while bit 15 / bit 14 is set it adds 1 and waits for the next VBlank START (the VDP status bit 3); on a clear
 * read it leaves with the count, and $80F2A keeps the low byte: the start of its random-number table ($8102E). The
 * cart's own C6 job lasts 80 of those polls: count 94. This was measured from B Jam's three CDX power-ons by matching
 * all 256 attract demos (95 once). Ours sets up in ~45-55 frames, so the C6 job holds $1FE6 bit 14 (the queue is not
 * empty while the job runs: the cart chip's own bit, property FZ4 of tests/s1/disp_tests.c) until the game has
 * polled 80 times: at the post (poll 0) and at VBlank starts 1-79, and lets it go mid-frame before VBlank start 80.
 * It counts frames on the VDP, not time on the MCU: VSCNT (MCU interface v1.1) counts the VS starts, and the VS start
 * comes C6_VS_LAG after the VBlank start (measured in the Nuked-MD emulator: NTSC 224 lines, 37,572 MCLK = 10.99
 * lines, every frame). The game's first read comes C6_POLL0 after its C600 write ($B4394-$B4536: 96 68000 cycles,
 * estimated from the game's code), and its later reads at the VBlank starts after that first read. So VS start k
 * after the post follows the k-th of those VBlank starts, unless the first read fell between a VBlank start and its
 * VS start: then the first VS start belongs to the VBlank before the reads, and the hold spans one more (the case
 * check: a VS start by post + C6_POLL0 + C6_VS_LAG; one already counted in the L1's read needs no more). The release
 * comes C6_TAIL after the last VS start of the hold: 120 + 11 lines after VBlank
 * start 79, half a frame before VBlank start 80. If our set-up is still running then, the hold adds nothing (the
 * count is ours, higher). The guard CLK_C6_HOLD_MAX ends a hold whose VS count stops (a dead VDP: the game would
 * otherwise reach its own 960-count timeout). The MCU clock is the master clock (BRD_CLK_HZ = MCLK), so a VDP line is
 * 3,420 timer cycles at NTSC and PAL alike. PAL: 80 polls as well (the cart's PAL count is not known).
 * Pocket only (docs/ALLOWLIST.md, row B7: the Pocket menu): the VDP keeps running while the Pocket menu pauses the
 * 68000, so a menu opened during the hold costs the game its polls of those frames. */
#define C6_HOLD_EDGES           79u                         /* VS starts after the post the hold waits for (case A) */
#define VDP_LINE_MCLK           3420u                       /* master clocks (= timer cycles) per VDP line */
#define C6_VS_LAG               (10u * VDP_LINE_MCLK + 3372u)   /* 37,572: VBlank start -> VS start (measured) */
#define C6_TAIL                 (120u * VDP_LINE_MCLK)      /* the last VS start of the hold -> the release */
#define C6_POLL0                (96u * 7u)                  /* the C600 write -> the game's first read: 96 68000 cycles
                                                               (MCLK / 7) */
#define C6_SPIN                 64u                         /* idle loops between two VSCNT reads (~64 x 3 instructions) */

/* DISP_BUG 5 / 6 (tests/equiv/c6count.py's negative controls only; fwbuild.json test_bug_c6a / test_bug_c6b; never in an
   image that ships): 5 = no hold (the job step right after the set-up, as before); 6 = no case check (a post between a
   VBlank start and its VS start is let go one poll early); 3 is disp.c's */
#ifndef DISP_BUG
#define DISP_BUG 0
#endif
#if !PPM_RELEASE && !TDIAG_LEAN
uint32_t c6_hold_test;
#define C6_TEST(x)              (c6_hold_test = (x))
#else
#define C6_TEST(x)              ((void)0)
#endif

static uint32_t vs_since_post(void) { return (brd_vs_count() - disp_g.c6_v) & BRD_VS_COUNT_MASK; }

static void c6_spin(void)
{
    uint32_t n;
    for (n = 0; n < C6_SPIN; n++)
        __asm__ volatile ("" : : : "memory");
}

/* before the set-up (the job starts right after the post's L1, 0.7 ms before the deadline): did a VS start come after
   the L1's read and by the game's first read + C6_VS_LAG? Then that read fell inside a VBlank, before its VS start. A
   tight loop: the VS count is read before each TIMER read, and the last count read before the deadline decides (to
   within one pass, a few cycles). A job that starts after the deadline cannot tell: it takes no VS start (TEST: case
   3). Returns the VS starts the hold waits for */
static __attribute__((noinline)) uint32_t c6_hold_target(void)
{
    uint32_t t = disp_g.c6_t + C6_POLL0 + C6_VS_LAG, v = disp_g.c6_v, s, late = 1u, b;
    for (;;) {
        s = brd_vs_count();
        if (brd_until(t) <= 0)
            break;
        v = s;
        late = 0u;
    }
    b = ((v - disp_g.c6_v) & BRD_VS_COUNT_MASK) != 0u;
#if DISP_BUG == 6
    b = 0u;
#endif
    C6_TEST(late ? 3u : 1u + b);
    (void)late;
    return C6_HOLD_EDGES + b;
}

/* after the set-up: wait for the n-th VS start since the post, then C6_TAIL; the job step clears bit 14 after it */
static __attribute__((noinline)) void c6_hold(uint32_t n)
{
    uint32_t t, e = vs_since_post();
#if !PPM_RELEASE && !TDIAG_LEAN
    uint32_t rec = (c6_hold_test & 0xFFu) | (e << 16);     /* the case (c6_hold_target), the VS starts so far */
#endif
    if (DISP_BUG == 5 || e >= n) {                          /* our set-up took longer than the cart's: no wait */
        C6_TEST(rec | 0x200u);
        return;
    }
    while (vs_since_post() < n) {
        if (brd_now() - disp_g.c6_t > CLK_C6_HOLD_MAX) {    /* the VS count stopped: a dead VDP */
            C6_TEST(rec | 0x300u);
            return;
        }
        c6_spin();
    }
    t = brd_now() + C6_TAIL;
    while (brd_until(t) > 0)
        c6_spin();
    C6_TEST(rec | 0x100u);
}

#if FW_S5
/* FW_S5: 8C's job (kind 2). The module comes from the store decoded at C6 (board_module), and its start
   is an engine item, so it runs in arrival order with the posts and the ticks; the job leaves only
   after that item has run, so the job step rewrites $1FE6 bit 14 after the module start, as the cart chip's tail
   does. L2c runs with MSI open, so the raise takes a fresh L2b above this pass at once, and that L2b runs the queue
   (the item included).
   The cart chip decodes the module in this job; ours took it from the store, and the job holds the cart chip's time
   (CLK_JOB8C + CLK_JOB8C_KB a thousand decoded bytes) before the module start, so the game sees the cart's song-start
   timing ($1FE6 bit 14, bit 3 and the feed held, the start's tick). A module the store does not hold is the cart
   chip's failed decode (an empty 0x80 / 0x81 decode: trace 0x11, no module start; a stream that is no 0x80-0x83 one:
   trace 4). Ours
   leaves out 0x82 / 0x83 module streams: the game has none (measured). Returns the job step's failure code */
static uint32_t job_8c_s5(const disp_job_t *j)
{
    uint32_t trk = j->s1_lo & 0x3Fu, t0 = brd_now(), len, t;
    const uint8_t *m = board_module(trk), *p;
    len = m ? board_module_len(trk) : 0u;
    t = CLK_JOB8C + len / 1000u * CLK_JOB8C_KB + (len % 1000u) * CLK_JOB8C_KB / 1000u;
    if (SONG_BUG != 22)
        while (brd_until(t0 + t) > 0)                       /* the cart chip's decode time; L2b runs above this */
            ;
    if (!m) {
        p = SONG_FLASH8(j->p20);
        return (p[0] & 0xFCu) == 0x80u ? 0x11u : 4u;
    }
    while (!song_job_done(m))                               /* the queue full: L2b makes room */
        sched_work_post();
#if SONG_BUG != 12
    while (song_job_waiting())
        sched_work_post();
#endif
    return 0u;
}

/* FW_S5: C6's audio init (the C6 job's audio set-up, C600 longs 0-4: core/song/song_c6.c), after the
   sprite and MegaWire stand-ins of job_setup: its two engine parts as items, in order with the posts (the job waits
   for each), the decodes and our module pre-decode in the job itself. Returns SETUP_SFX / SETUP_SEQ */
static void c6_item(void (*fn)(uint32_t), uint32_t arg)
{
    while (!song_call(fn, arg))                             /* the queue full: L2b makes room */
        sched_work_post();
    while (song_job_waiting())
        sched_work_post();
}

static uint32_t job_c6_s5(const uint32_t longs[8])
{
    uint32_t level;
    song_c6_begin();
    c6_item(song_c6_init, longs[4]);
    level = song_c6_banks(longs);
    if (level == 2u)
        (void)song_store_modules(longs[0]);
    c6_item(song_c6_ready, level);
    return (SFX.ready ? SETUP_SFX : 0u) | (S.ready ? SETUP_SEQ : 0u);
}
#endif

uint32_t l3_job(void)
{
    uint8_t rd = disp_g.q_rd;
    disp_job_t *j;
    uint32_t code = 0u, s;
    if (((disp_g.q_wr ^ rd) & 0xFu) == 0u)                  /* 0x0801A3B2-0x0801A3BE: nothing queued */
        return 0u;
    j = &disp_g.q[rd & 0xFu];
    ST_ENTER(ST_L3_JOB);                                    /* TEST counters */
#if FW_S5
    song_pass_hold = 1u;                                    /* no main-loop pass while a job runs (the cart chip's
                                                               pass is the thread the job holds) */
#endif
    switch (j->type) {                                      /* 0x0801A3C8-0x0801A3D2 + the byte table 0x0801A3D6 */
#if FW_S5
    case JOB_UNPACK_8C:                                     /* 0x0801A3E2, kind 2 */
        code = job_8c_s5(j);
        break;
    case JOB_UNPACK_1: case JOB_UNPACK_DA: case JOB_UNPACK_F4:
#else
    case JOB_UNPACK_1: case JOB_UNPACK_8C: case JOB_UNPACK_DA: case JOB_UNPACK_F4:   /* 0x0801A3E2 */
#endif
        code = job_unpack(j);
        break;
    case JOB_EEP_READ: case JOB_EEP_READ_MW:                /* 0x0801A4EC */
#if FW_MW
        if (job_eep_read(j) == 0u) {                        /* 0x0801A4F8-0x0801A500: the read found no good copy */
            if (j->type == JOB_EEP_READ_MW && s3_mw_on)
                MW32(mw, MW_HOME) = 1u;                     /* 0x0801A502-0x0801A50A */
        }
        else if (j->type == JOB_EEP_READ_MW && s3_mw_on)
            mw_not_ported(0x08021548u);                     /* 0x0801A50E-0x0801A512: a good copy of the record goes
                                                               on to 0x08021548, not built. Ours never writes slot 9
                                                               (its save, 0x080215C0, is not built either), so the
                                                               read finds none: the record is zero-filled and MW+0xC
                                                               set, as the cart chip does with a blank slot 9 */
#else
        (void)job_eep_read(j);
#endif
        break;
    case JOB_EEP_WRITE:                                     /* 0x0801A518 */
#if FW_S5                                                   /* the cart chip's write job answers 0 when it wrote nothing: */
        code = job_eep_write(j) ? 0u : 9u;                  /* then bit 8 when asked and trace 9 (0x0801A528-0x0801A544) */
#else
        code = job_eep_write(j);                            /* the FW_S5 = 0 body answers the trace code itself */
#endif
        break;
    case JOB_SCALE_SAVE:                                    /* 0x0801A582 */
        if (!disp_g.sc_saved) {
            job_scale_save();                               /* 0x08022CD0 */
            disp_g.sc_saved = 1u;
        }
        job_scale_setup();                                  /* 0x08022D34: the stamps := 0 */
        disp_g.sc_session = 1u;                             /* 0x0801A5C2 */
        break;
    case JOB_RESCALE:                                       /* 0x0801A59A */
        if (disp_g.sc_session) {
            job_rescale(disp_g.sc_args);                    /* 0x08022D84, 0x08022D48 */
            disp_g.sc_pending = 0u;                         /* 0x0801A5AC */
        }
        break;
    case JOB_RESTORE:                                       /* 0x0801A5B0 */
        if (disp_g.sc_saved) {
            job_restore();                                  /* 0x08022D04 */
            disp_g.sc_saved = 0u;
        }
        disp_g.sc_session = 0u;                             /* 0x0801A5C2 */
        break;
    case JOB_SETUP: case JOB_SETUP_MW: {                    /* 0x0801A54A */
        uint32_t n = c6_hold_target();                      /* ours (row B34): the C6 hold's frame count */
        uint32_t f = job_setup(disp_g.c6_longs, j->type == JOB_SETUP_MW);
#if FW_S5
        f = (f & ~(SETUP_SFX | SETUP_SEQ)) | job_c6_s5(disp_g.c6_longs);   /* the cart chip's audio set-up */
#endif
#if FW_S5                                                   /* test build S3a on: the cart chip's order
                                                               (interim/s1 job_setup) */
        disp_g.af_parity++;                                 /* 0x08019740-0x08019748: H+$403 += 1, whatever the data */
        if (f & SETUP_ENG)
            disp_g.eng_ready = 1u;                          /* 0x080197C2: after a good anim set-up */
#else
        if (f & SETUP_ENG) {                                /* the sprite init 0x08019734: */
            disp_g.af_parity++;                             /* 0x08019740-0x08019748: H+$403 += 1 */
            disp_g.eng_ready = 1u;                          /* 0x080197C2 */
        }
#endif
        if (f & SETUP_MW)
            disp_g.mw_ready = 1u;
        disp_g.mixer = 1u;                                  /* the C6 one-shot, set whatever the data */
        if (f & SETUP_SFX)
            disp_g.sfx_ready = 1u;
        if (f & SETUP_SEQ)
            disp_g.seq_ready = 1u;
        c6_hold(n);                                         /* ours (row B34): the cart's 80 polls; then the job step */
        ST_MARK(ST_MS_C6_DONE);
        break;
    }
    default:                                                /* 0x0801A5C6: unknown type */
        code = 1u;
        break;
    }
    if (code) {                                             /* e.g. 0x0801A3FE-0x0801A41A */
        if (j->fail_en)
            st_set(1u, ST_FE6, 0x100u);
        chip_trace(code, 0u, 0u);
#if !PPM_RELEASE
        disp_g.jobs_failed++;
#endif
    }
#if !PPM_RELEASE && !TDIAG_LEAN
    disp_g.jobs_run++;
#endif
    s = sched_crit_enter();                                 /* 0x0801A5E6 */
#if DISP_BUG == 3                                           /* planted (disp.c): bit 14 from the index before the advance */
    st_set(((disp_g.q_rd ^ disp_g.q_wr) & 0xFu) != 0u, ST_FE6, 0x4000u);
    disp_g.q_rd = (uint8_t)(disp_g.q_rd + 1u);
#else
    disp_g.q_rd = (uint8_t)(disp_g.q_rd + 1u);
    st_set(((disp_g.q_rd ^ disp_g.q_wr) & 0xFu) != 0u, ST_FE6, 0x4000u);   /* 0x0801A604 */
#endif
#if FW_S5
    song_pass_hold = 0u;                                    /* the job's tail runs the pass next (0x0801A60A) */
#endif
    sched_crit_leave(s);
#if FW_S5 && SONG_BUG != 34
    sched_pass_post();                                      /* then the main-loop pass (0x0801A60A) */
#endif
    ST_LEAVE();
    return 1u;
}
