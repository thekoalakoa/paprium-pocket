/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/dispatch/disp.c - the mailbox entry, both dispatchers and their 55-entry tables, as the cart chip has them.
 *
 * The cart chip is the STM32 microcontroller on the real cartridge (it runs the cart program). Written by our team
 * from our own study of how the cart behaves, step for step the same as the cart chip wherever the effect is the
 * dispatcher's own: the request test, the entry clears, every gate in order with its refusal code, the job pushes, the
 * register sequences and the finish. Each fragment below names its cart chip entry (mailbox B table 0x08025AC8 /
 * mailbox A table 0x080259EC), except the audio commands' (C6, 88, C9, CA, 8C-8E, D0-D6, the tick); the other hex
 * numbers are cart chip addresses too, kept as references. The engine work behind an accepted post is a body
 * (disp_bodies.h; in the first version of this firmware, the 0.2.6 bodies, re-hosted in interim/s1).
 *
 * Words used below. A post is a command word the 68000 writes to a mailbox: mailbox B is RAMDP $1FEA and mailbox A is
 * RAMDP $1FEC (RAMDP = the cart RAM that both the 68000 and the MCU see; the MCU is the processor this firmware runs
 * on). Commands are named by their hex bytes (81, C6, 9494 ...). L1 is the level-1 interrupt handler that reads a
 * post (core/sched). G is the cart chip's global block (disp_state_t in disp.h). FW_S5 (board/board.h) builds the
 * full firmware on MCU interface v1.3, and FW_MW the MegaWire code (core/mw); v1.2 and v1.3 are versions of the MCU
 * interface (docs/MCU_INTERFACE.md). Row numbers such as B12 are rows of docs/ALLOWLIST.md, the list of our known
 * differences from the cart chip. TEST is the build with debug aids; RELEASE is the one without.
 *
 * The cart chip's fragments share mailbox_irq's frame: r4 = the mailbox (1 A, 2 B), r6 = the word & 0x3FFF (B) or
 * & 0x3F00 (A: the low byte is dropped), sl = bit 14, the argument flag (B; the A entries force 0), sb = RAMDP
 * $1E10, the argument words. A refusal sets $1FE6 bit 10 (A) or bit 9 (B), posts trace code | r6 << 8 and finishes;
 * every path ends in 0x0801AC64: $1FEC := 0 (A) or $1FEA := 0 (B), then $1FE6 bit 15 through the helper.
 * Gates the first version of this dispatcher left to a later module are marked in the fragment with the module that
 * has them (README.md lists them). */
#include <stdint.h>
#include "board.h"
#include "sched.h"
#include "sched_hooks.h"
#include "disp.h"
#include "disp_bodies.h"
#include "stats.h"
#if FW_S5
#include "song.h"
#endif
#if FW_MW
#include "mw.h"
#endif

disp_state_t disp_g;

typedef struct {
    uint32_t mbx;               /* MBX_A / MBX_B */
    uint16_t r6;                /* B: word & 0x3FFF; A: word & 0x3F00 */
    uint8_t  args;              /* sl: B bit 14; A 0 */
    uint8_t  lo;                /* r6 & 0xFF */
    uint8_t  deferred;          /* disp_post does not finish it: the tick end does (FW_S5), or TEST's AF already did */
} post_t;

typedef void (*frag_fn)(post_t *p);

#define ARGS_W                  (0x1E10u >> 1)              /* sb: RAMDP $1E10, the argument words (halfword index) */
#define ARG(i)                  (brd_cart_ram()[ARGS_W + (i)])
#define FAIL_ON                 1u

/* DISP_BUG: planted bugs for the negative controls only (the host fuzz test tests/s1/disp_tests.c, fwbuild.json s1.host
   "negative"; the RV32 fuzz test tests/equiv/fuzz_s1.py, s1 variants test_bug_disp*; never defined in an image that
   ships): 1 = a queued job's bit 14 is not stored before the finish, 2 = mailbox A's finish loses its $1FEC := 0. 3 and
   4 are in jobs.c and status.c; 8 / 9 (83) and 11 (DF's RAM bound) belong to the FW_S5 checks (tests/equiv/f83lock.py,
   gatelock.py; fwbuild.json s1 variants s5release_bug_83a / _83b / _gate1). */
#ifndef DISP_BUG
#define DISP_BUG 0
#endif
/* SPR_BUG 3 (the negative control of the lockstep test, which runs the cart chip's program and ours side by side:
   fwbuild.json s1 host program variant bug_spr3; never in an image that ships): an accepted B0 does not bump the
   multiplex parity. SPR_BUG 1, 2 and 4-7 are in core/sprite. */
#ifndef SPR_BUG
#define SPR_BUG 0
#endif

static uint32_t tick_mbx;       /* the mailbox whose finish waits for the tick end (FW_S5) */

/* ---- finish and refusals ------------------------------------------------------------------------------------- */
#define NOINLINE                __attribute__((noinline))

static NOINLINE void finish(uint32_t mbx)                   /* 0x0801AC64 */
{
    if (mbx == MBX_A) {
#if DISP_BUG != 2
        brd_freg_wr(BRD_FREG_FEC, 0u);                      /* 0x0801ACD8 */
#endif
    }
    else {
        brd_freg_wr(BRD_FREG_FEA, 0u);                      /* 0x0801ACC2 */
    }
    st_set(1u, ST_FE6, 0x8000u);                            /* 0x0801AC6C-0x0801AC76 */
}

static NOINLINE void refuse_t(post_t *p, uint32_t trace)
{
    st_set(1u, ST_FE6, p->mbx == MBX_A ? 0x400u : 0x200u);  /* e.g. 0x0801C4A4 (A) / 0x0801C4E2 (B) */
    chip_trace(trace, 0u, 0u);                              /* event_post(code | r6 << 8, 0, 0) */
#if !PPM_RELEASE
    disp_g.refusals++;
#endif
}
static NOINLINE void refuse(post_t *p, uint32_t code) { refuse_t(p, code | ((uint32_t)p->r6 << 8)); }

/* ---- the job queue (the slot pointer and push used by the fragments) -------------------------------------- */
static disp_job_t *slot(uint32_t ahead)
{
    disp_job_t *j = disp_job_slot(ahead);
    j->s1_hi = disp_g.cur_mbx == MBX_B ? (uint8_t)(disp_g.cur_word >> 8) : 0u;
    return j;
}
static NOINLINE void job_queued(void)
{
#if DISP_BUG != 1
    st_set(1u, ST_FE6, 0x4000u);                            /* bit 14: jobs pending */
#endif
    st_set(0u, ST_FE6, 0x100u);                             /* bit 8: the last job's failure, cleared */
}

/* ---- register sequences the chip writes for the decoder / stream ------------------------------------------ */
/* one queue entry (0x0801906C / 0x08019076, 0x08017EB0-0x08017EB8, 0x0801D230 / 0x0801D236): $1FF4 = 0x200 | the
   address bits 22:16, then $1FF6 = its low half, even (a push); a is the stream's type byte, a 23-bit even ROM offset */
static NOINLINE void push_entry(uint32_t a)
{
    brd_freg_wr(BRD_FREG_FF4, (uint16_t)(0x200u | (a >> 16)));
    brd_freg_wr(BRD_FREG_FF6, (uint16_t)a);
}

/* 0x08018FFC: the load-list flush (AF close, B1). The cart's FPGA decodes the listed blocks itself and the cart chip
   never waits for it (no read of $1FF0-$1FF6, no decode-done interrupt); on ours the RTL does the same (MCU interface
   v1.2, docs/MCU_INTERFACE.md section 4.9), so the post finishes as soon as the cart chip's handler does */
static NOINLINE void flush_regs(void)
{
    const uint32_t *list, *q;
    uint32_t n = body_load_list(&list);                     /* the frame's loads, in load order (core/sprite's
                                                               composer list, as the cart chip's composer makes it;
                                                               each block's table entry read here as its flush does) */
    brd_freg_wr(BRD_FREG_FF6, 1u);                          /* 0x0801900C: queue clear */
    st_set(0u, ST_FE4, 0x100u);                             /* 0x08019018 */
    for (q = list + n; q != list; ) {                       /* 0x08019020-0x0801907A: last to first, push_entry's two */
        uint32_t a = *--q & 0x7FFFFEu;                      /* writes in line, for a faster AF reply; the table */
        brd_freg_wr(BRD_FREG_FF4, (uint16_t)(0x200u | (a >> 16)));  /* offset rounded down to even, 23 bits */
        brd_freg_wr(BRD_FREG_FF6, (uint16_t)a);
    }
    /* 0x0801907C-0x0801907E: count := 0 (the body's: body_af / body_b1, core/sprite) */
    body_dec_scratch();                                     /* the board: the decoder's output base (v1.2) */
    brd_freg_wr(BRD_FREG_FF2, 0x8000u);                     /* 0x08019082: start the decoder */
    st_set(1u, ST_FE4, 0x100u);                             /* 0x0801908E: armed */
}

/* ================================================================================================================
 * Fragments (table index: B entry / A entry)
 * ================================================================================================================ */

/* default: B 0x0801B6F0, A 0x0801BA3C (also every index > 0x36) */
static void f_default(post_t *p) { refuse(p, 2u); }
/* the A-only refusals that set bit 10 and trace 7: C6, D3, DB 0x0801B9D6, E7 0x0801B992,
   F4 0x0801BA1A, F5 0x0801B9F8 */
static void f_refuse7(post_t *p) { refuse(p, 7u); }

/* 01 81: 0x0801AFC4 (both) */
static void f_81(post_t *p)
{
    disp_g.f81[0] = (uint8_t)((p->r6 >> 1) & 1u);          /* G+9: debug counters to RAMDP $1B00 (disp_s5_pass) */
    disp_g.f81[1] = (uint8_t)((p->r6 >> 2) & 1u);          /* G+0xA: Boom Box feed (the song engine) */
    disp_g.f81[2] = (uint8_t)((p->r6 >> 3) & 1u);          /* G+0xB: MegaWire task (core/mw) */
    disp_g.f81[3] = (uint8_t)((p->r6 >> 4) & 1u);          /* G+0xC: the watchdog may reset the MCU (core/wdog) */
    disp_g.wd_arm = 1u;                                     /* G+0x190 := 1 (0x0801AFE2) */
}

/* 02 82: 0x0801B6DC (both): $1FF2 := low byte bit 0 (0x0801B6EA / 0x0801BE84) */
static void f_82(post_t *p) { brd_freg_wr(BRD_FREG_FF2, (uint16_t)(p->r6 & 1u)); }

#if FW_S5
/* 03 83 (test build S3a on): 0x0801B0C8 (both), the cart chip's frame-period check 0x080209B4(n = r6 & 0xF). n = 0
   (also every mailbox-A 83: its low byte is dropped) stamps the start and is accepted; n > 0 takes the time since that
   stamp over n frames as the cart chip measures it on its SysTick (24 bits at 96 MHz: the time wraps at CLK_83_WRAP)
   and accepts a frame period inside either of the cart chip's windows (18,621-21,619 us around the PAL target 20,120;
   15,489-17,887 us around the NTSC target 16,688); outside both, refusal 7 (0x0801B0D4-0x0801B0E4: $1FE6 bit 10 (A)
   or 9 (B), trace 7 | r6 << 8). Inside a window the cart chip then trims its own HSI oscillator toward the target
   (0x08020864 and its delay 0x08020880): that is the cart chip's clock plumbing, which ours leaves out (row B12);
   its RAM copies of the period (S+0x174 / S+0x176) are read by nothing the game sees. */
static uint32_t f83_t0;                                     /* S+0x17C: the stamp of the last n = 0 */
NOINLINE uint32_t disp_83_check(uint32_t n)                 /* 0x080209B4: 1 = accepted, 0 = refused */
{
    uint32_t now = brd_now(), d;
    if (!n) {
        f83_t0 = now;                                       /* SysTick VAL -> S+0x17C */
        return 1u;
    }
#if DISP_BUG == 8
    d = (now - f83_t0) / n;                                 /* planted (f83lock.py): the SysTick wrap left out */
#else
    d = ((now - f83_t0) % CLK_83_WRAP) / n;                 /* ((S+0x17C - VAL) & 0xFFFFFF) / 96 / n */
#endif
#if DISP_BUG == 9
    return (d - CLK_83_A < CLK_83_A_END - CLK_83_A + BRD_CYC_US(1)) ||   /* planted: window A 1 us longer */
           (d - CLK_83_B < CLK_83_B_END - CLK_83_B);
#else
    return (d - CLK_83_A < CLK_83_A_END - CLK_83_A) || (d - CLK_83_B < CLK_83_B_END - CLK_83_B);
#endif
}
static void f_83(post_t *p)
{
    if (!disp_83_check(p->r6 & 0xFu))                     /* 0x0801B0C8-0x0801B0D2 */
        refuse(p, 7u);
}
#else
/* 03 83: 0x0801B0C8 (both): the frame-period measurement 0x080209B4(lo & 0xF), refusal 7 when the period fits
   neither window. The FW_S5 = 0 build keeps 0.2.6's 83 (muted: accepted, nothing done); the FW_S5 build does what
   the cart chip does (above; row B12; test build S3a on). */
static void f_83(post_t *p) { (void)p; }
#endif

/* 04 84: 0x0801B69E (both) */
static void f_84(post_t *p)
{
    uint32_t end = brd_now() + CLK_84_DELAY;               /* delay(9,600 SysTick) 0x08020880 = 100 us */
    (void)p;
    while (brd_until(end) > 0)                              /* a deadline: the 100 us comes from the build's clock */
        ;
    brd_freg_wr(BRD_FREG_FEE, 0xAF5Bu);                     /* 0x0801B6AA */
    ST_84(brd_now() - brd_stamp_b());                       /* TEST: the window off, from the post's RTL stamp */
    st_set(0u, ST_FE4, 0x18u);                              /* 0x0801B6B4 */
    brd_freg_wr(BRD_FREG_FE8, 0u);                          /* 0x0801B6C2 */
    brd_cart_ram()[0x0006u >> 1] = 0x8200u;                 /* 0x0801B6C4: the 68000 reset vector's low word */
    disp_g.f81[3] = 0u;                                     /* G+0xC */
    disp_g.wd_arm = 0u;                                     /* G+0x190 */
    disp_g.wd_count = 0u;                                   /* G+0x192 */
}

/* 05 85: 0x0801B680 (both): never returns */
static void f_85(post_t *p)
{
    (void)p;
    (void)sched_crit_enter();                               /* cpsid i, never re-enabled */
    brd_freg_wr(BRD_FREG_FEE, 0xAF5Bu);                     /* 0x0801B688 */
    st_raw_fe4(0x4000u);                                    /* 0x0801B68E: no helper, the shadow keeps its value */
    chip_trace(0x400000FAu, 0x80u, 0x28u);                  /* 0x0801B694: event_post, fatal: never returns */
    for (;;)                                                /* (fatal_halt is noreturn; this keeps 85 noreturn too) */
        ;
}

/* 06 C6 (B; on A, refusal 7) */
static void f_c6(post_t *p)
{
    unsigned i;
    disp_job_t *j;
    if (!p->args) {
        refuse(p, 7u);
        return;
    }
#if FW_S5
    if (G.ready)                                            /* the song engine's own word: a second C6
                                                               completes, no job */
        return;
    S.ready = 0u;
    SFX.ready = 0u;
#else
    if (disp_g.mixer)                                       /* a second C6 completes, no job */
        return;
#endif
    disp_g.seq_ready = 0u;
    disp_g.sfx_ready = 0u;
    disp_g.mw_ready = 0u;
    for (i = 0; i < 8u; i++)                                /* the C600 arguments from $1E10.. */
        disp_g.c6_longs[i] = ((uint32_t)ARG(2u * i) << 16) + ARG(2u * i + 1u);
    brd_cart_ram()[0x1800u >> 1] = 0u;
    brd_cart_ram()[0x1802u >> 1] = 0u;
    disp_g.c6_t = brd_stamp_b();                            /* ours (row B34): the C6 hold counts from the C600 write */
    disp_g.c6_v = (uint16_t)brd_vs_count();
    job_queued();
    j = slot(0u);
    j->type = JOB_SETUP;
    j->fail_en = FAIL_ON;
    disp_job_commit(1u);
    ST_MARK(ST_MS_C6_POSTED);
}

#if !FW_S5
/* 08 88 (both tables) */
static void f_88(post_t *p)
{
    if (!disp_g.mixer) {
        refuse(p, 6u);
        return;
    }
    body_88((uint8_t)(p->lo & 0x7Fu));                      /* the 88 configuration */
}

/* 09 C9 and 0A CA (both tables; on A, no arguments) */
static void f_c9(post_t *p)
{
    if (!disp_g.mixer) {
        refuse(p, 6u);
        return;
    }
    body_c9(p->lo);                                         /* level target, pan / step from the args */
}
static void f_ca(post_t *p)
{
    if (!disp_g.mixer) {
        refuse(p, 6u);
        return;
    }
    body_ca(p->lo);
}

/* 0C 8C (both tables) */
static void f_8c(post_t *p)
{
    disp_job_t *j;
    if (disp_queue_full(1u)) {
        refuse(p, 5u);
        return;
    }
    if (!disp_g.seq_ready) {
        refuse(p, 6u);
        return;
    }
    /* in the song engine (its tables): n = lo & 0x3F, refusal 7 when n = 0 or above the module
       count; a null slot is ignored (the old music keeps playing); refusal 7 + trace 0xD unless the
       module's byte 0 is 0x81 or its byte 2 is 0x0E. The FW_S5 = 0 build keeps 0.2.6: every 8C is played by the album
       player in interim/album (row B12). */
    /* the music stops now, loop flag := lo bit 7 (in the song engine), then the job */
    job_queued();
    j = slot(0u);
    j->type = JOB_UNPACK_8C;
    j->fail_en = 0u;                                        /* no failure report for 8C */
    j->s1_lo = p->lo;
    disp_job_commit(1u);
}

/* 0D 8D (both tables) */
static void f_8d(post_t *p)
{
    if (!disp_g.seq_ready) {
        refuse(p, 6u);
        return;
    }
    body_8d(p->lo);                                         /* fade, lo = step (0 stops now) */
}

/* 0E 8E (both tables) */
static void f_8e(post_t *p)
{
    if (!disp_g.mixer || !disp_g.seq_ready) {
        refuse(p, 6u);
        return;
    }
    /* n = lo & 0x3F > module count -> refusal 7; n = 0: loop flag := lo bit 7; else queue track n: in the
       song engine. 0.2.6 had no 8E (it printed "unknown"): nothing done (row B12). */
}

/* 10 D0 (both tables; on A, no arguments) */
static void f_d0(post_t *p)
{
    if (p->lo == 0u || ARG(0) > 0x19u || !p->args) {
        refuse(p, 7u);
        return;
    }
    if (!disp_g.seq_ready) {
        refuse(p, 6u);
        return;
    }
    /* note-on on voice a0 (in the song engine); 0.2.6 muted D0 */
}

/* 11 D1 (both tables; on A, no arguments) */
static void f_d1(post_t *p)
{
    /* in the song engine: (lo & 0x7F) >= the SFX count -> refusal 7 */
    if ((p->lo & 0x7Fu) == 0u) {
        refuse(p, 7u);
        return;
    }
    if (p->args && (ARG(0) & 0xFFu) == 0u) {
        refuse(p, 7u);
        return;
    }
    if (!disp_g.sfx_ready) {                                /* with or without args */
        refuse(p, 6u);
        return;
    }
    body_d1(p->lo);                                         /* the SFX start */
}

/* 12 D2 (both tables; on A, no arguments) */
static void f_d2(post_t *p)
{
    if (p->lo == 0u) {
        refuse(p, 7u);
        return;
    }
    if (!disp_g.sfx_ready) {
        refuse(p, 6u);
        return;
    }
    body_d2(p->lo);
}

/* 13 D3 (B; on A, refusal 7) */
static void f_d3(post_t *p)
{
    if (p->lo == 0u || !p->args) {
        refuse(p, 7u);
        return;
    }
    if (!disp_g.sfx_ready) {
        refuse(p, 6u);
        return;
    }
    body_d3(p->lo);
}

#endif

/* 14 the frame tick (both tables: 9494 on $1FEC; 94xx / D4xx on $1FEA take the same path) */
#if !FW_S5
static void f_tick(post_t *p)
{
    uint32_t stamp = brd_now();
    ST_9494();                                              /* TEST telemetry: the freeze record's frame count */
    disp_g.wd_count = 0u;                                   /* the watchdog is fed */
    if (disp_g.wd_arm)                                      /* armed by 81 -> running */
        disp_g.wd_arm = 2u;
    if (!disp_g.mixer)                                      /* bail: the flush timer off, */
        return;                                             /* PSG volumes, the finish (no song engine parts here) */
    /* the song engine's: the mixer-busy bail, the frame counter, the 50 / 60 Hz skip */
    st_set(0u, ST_FE6, 0x2000u);                            /* bit 13, synth frame work pending */
    /* the song engine's: the synth tick, then the TIM14 packet flush */
    if (audio_tick_begin(stamp)) {                          /* song engine: the tick runs in L2b, the finish follows */
        tick_mbx = p->mbx;
        p->deferred = 1u;
        sched_tick_start(stamp);
    }
}

/* 15 D5 (both tables; on A, no arguments) */
static void f_d5(post_t *p)
{
    if (!disp_g.sfx_ready) {
        refuse(p, 6u);
        return;
    }
    if (p->lo > 1u || (p->lo == 1u && !p->args)) {
        refuse(p, 7u);
        return;
    }
    body_d5(p->lo);                                         /* echo off (0) / on with gain and delay (1) */
}

/* 16 D6 (both tables; on A, no arguments) */
static void f_d6(post_t *p)
{
    if (!disp_g.seq_ready) {
        refuse(p, 6u);
        return;
    }
    if (p->lo > 7u) {
        refuse(p, 7u);
        return;
    }
    if (p->lo == 5u && (!p->args || (ARG(0) & 0x7Fu) > 0x19u)) {   /* voice mute */
        refuse(p, 7u);
        return;
    }
    /* sub-table: reset, echo, crisis, tempo, transpose, voice mute, sax flags, boost (in the song engine);
       0.2.6 muted D6 */
}
#else
/* ---- FW_S5: the audio fragments and the 9494 on the ordered engine queue ------------------------------------------
 * 88, C9, CA, 8C, 8D, 8E, D0-D3, D5, D6 (both tables) and the tick: core/song's song_arrive() runs the cart chip's
 * gates in the cart chip's order with their refusals and the parts the 68000 can see (song_gate: the gates of the
 * fragments above, with the gaps they leave filled as the cart chip has them: 8C's module range / null slot / header
 * check, D1's SFX count, 8E's range), and queues the engine part with the post's arrival number. The post is then
 * finished at once (row B39), or later by the queue when it was full (SONG_ARR_HELD: the 68000 waits, as it does for a
 * busy cart chip). The C6-done flags the gates read are the song engine's own words (the mixer, the sequencer and
 * the SFX engine ready flags: the same cart chip words as disp_g.mixer / seq_ready / sfx_ready; the C6 audio init
 * sets both) */
static void f_song(post_t *p)
{
    if (song_arrive(p->mbx == MBX_A ? 1u : 2u, disp_g.cur_word, &brd_cart_ram()[ARGS_W], disp_g.cur_seq,
                    disp_g.cur_stamp) == SONG_ARR_HELD)
        p->deferred = 1u;
}

/* 14 the frame tick: the watchdog feed (in L1, as the cart chip's head), then the tick's gate (bit 13) and
   its item: the sequencer half and the packet flush run in L2b (the level-2 software interrupt), in arrival order, and
   the urgent finish 1.8 ms after STAMP_A (the RTL's time stamp of the mailbox A post) */
static void f_tick(post_t *p)
{
    ST_9494();                                              /* TEST telemetry: the freeze record's frame count */
    disp_g.wd_count = 0u;                                   /* the watchdog is fed */
    if (disp_g.wd_arm)                                      /* armed by 81 -> running */
        disp_g.wd_arm = 2u;
    f_song(p);                                              /* the bail, bit 13, the tick (item) */
}

#define f_88 f_song
#define f_c9 f_song
#define f_ca f_song
#define f_8c f_song
#define f_8d f_song
#define f_8e f_song
#define f_d0 f_song
#define f_d1 f_song
#define f_d2 f_song
#define f_d3 f_song
#define f_d5 f_song
#define f_d6 f_song
#define f_d3_a f_song                                       /* A's D3: song_gate's refusal 7 */
#endif

/* 1A DA: B 0x0801B488; A 0x0801B93E (queue full -> 5, else 7) */
static void da_direct(uint32_t src, uint16_t dst, uint8_t mode)     /* 0x0801D1FE */
{
    uint32_t a = (src + 1u) & 0x7FFFFEu;                    /* 0x0801D20A: past the type byte, rounded up */
    brd_freg_wr(BRD_FREG_FE8, 1u);                          /* 0x0801D214: window on */
    brd_freg_wr(BRD_FREG_FF6, 1u);                          /* 0x0801D216: queue clear */
    st_set(0u, ST_FE4, 0x100u);                             /* 0x0801D222 */
    push_entry(a);                                          /* 0x0801D230 / 0x0801D236 */
    body_da_direct(src, dst, mode);                         /* the board: the decoder's output base (v1.2) */
    brd_freg_wr(BRD_FREG_FF2, 0x8000u);                     /* 0x0801D238: start; the RTL decodes, busy holds the
                                                               game until its GO */
    st_set(1u, ST_FE4, 0x100u);                             /* 0x0801D244: armed */
}

static void f_da(post_t *p)
{
    uint32_t src;
    uint16_t dst;
    uint8_t mode, t;
    disp_job_t *j;
    if (disp_queue_full(1u)) {                              /* 0x0801B488-0x0801B494 */
        refuse(p, 5u);
        return;
    }
    if (!p->args) {                                         /* 0x0801B49E -> 0x0801C04C */
        refuse(p, 7u);
        return;
    }
    dst = ARG(0);                                           /* sl := a0 >> 1 */
    mode = p->lo;                                           /* r8 */
    if (mode != 2u && mode != 6u && mode != 7u) {           /* 0x0801B4C8 */
        refuse(p, 7u);
        return;
    }
    if (mode == 7u) {                                       /* 0x0801C2FC */
        brd_freg_wr(BRD_FREG_FF2, 0u);                      /* 0x0801D500: port 6 stopped (+ its DMA, plumbing) */
        brd_freg_wr(BRD_FREG_FF2, 0x8000u);                 /* 0x0801C30A: the prelude */
    }
    j = slot(0u);
    j->p18 = dst;                                           /* 0x0801C326 (the chip: SDRAM + (a0 & ~1); mode 6: a0 >> 1) */
    src = ((uint32_t)ARG(1) << 16) | ARG(2);                /* 0x0801C328-0x0801C332 */
    if (src > 0x800000u) {                                  /* 0x0801C338 */
        refuse(p, 7u);
        return;
    }
    j->p20 = src;                                           /* 0x0801C684 (the chip: byte view + (src & ~1)) */
    t = brd_rom_byte(src & ~1u);                            /* 0x0801C686 */
    if ((uint8_t)(t - 0x80u) > 2u) {                        /* 0x0801C690: type 0x80-0x82 only */
        refuse(p, 7u);
        return;
    }
    if (mode == 6u) {                                       /* 0x0801CE3E: mode 6 streams type 0x80 only */
        if (t == 0x80u)
            da_direct(src, dst, mode);
        else
            refuse(p, 7u);
        return;
    }
    if (mode == 7u && t == 0x80u) {                         /* 0x0801CBEC-0x0801CBF6 */
        da_direct(src, dst, mode);
        return;
    }
    job_queued();                                           /* 0x0801CC02, 0x0801CC12 */
    j->type = JOB_UNPACK_DA;                                /* 0x0801CC20 */
    j->fail_en = FAIL_ON;                                   /* 0x0801CC24 */
    j->s1_mode = mode;
    disp_job_commit(1u);
}
/* the A entries of DA 0x0801B93E, DF 0x0801B90C, E0 0x0801B886: queue full -> 5, else 7 */
static void f_full5_else7(post_t *p) { refuse(p, disp_queue_full(1u) ? 5u : 7u); }

/* 1B DB: B 0x0801B42C; A 0x0801B9D6 (refusal 7) */
static void f_db(post_t *p)
{
    uint16_t a0, a1, a2, len;
    uint8_t mode = p->lo;
    if (!p->args) {                                         /* 0x0801B432 -> 0x0801BB04 */
        refuse(p, 7u);
        return;
    }
    a0 = ARG(0);
    a1 = ARG(1);
    a2 = ARG(2);
    len = (uint16_t)(a2 >> 1);                              /* 0x0801B436-0x0801B43A: words */
    if (mode == 3u) {                                       /* 0x0801C226: SDRAM -> cart RAM at a0, bounded by the page */
        if ((uint32_t)(a0 >> 1) + len > 0x1000u) {
            refuse(p, 7u);
            return;
        }
    } else if (mode != 6u) {                                /* 0x0801C270 */
        refuse(p, 7u);
        return;
    }
    if ((uint32_t)(a1 >> 1) + len > 0x8000u) {              /* 0x0801B45A-0x0801B460 */
        refuse(p, 7u);
        return;
    }
    /* 0x0801C730 -> 0x0801D3AC(6, SDRAM + (a1 & ~1), src, mode, len) */
    brd_freg_wr(BRD_FREG_FF2, 0u);                          /* 0x0801D3DE: stop (+ the DMA stop, plumbing) */
    if (mode == 3u) {
        brd_freg_wr(BRD_FREG_FF2, 0x8000u);                 /* 0x0801D44C (the copy DMA: the body) */
        body_db(a0, a1, a2, mode);
        return;
    }
    /* 0x0801D45E: G+4 := len, G+0 := source (the FIFO-B refill state: no refills on ours) */
    brd_freg_wr(BRD_FREG_FF6, 1u);                          /* 0x0801D46C */
    st_set(0u, ST_FE4, 0x100u);                             /* 0x0801D478 */
    brd_freg_wr(BRD_FREG_FE8, 1u);                          /* 0x0801D482: window on */
    brd_freg_wr(BRD_FREG_FF2, 0xC002u);                     /* 0x0801D488 */
    brd_freg_wr(BRD_FREG_FF2, 0xC002u);                     /* 0x0801D48A */
    if (disp_g.app_ready && len <= 0x78u)                   /* 0x0801D48C-0x0801D498 */
        brd_freg_wr(BRD_FREG_FF2, 0x4000u);                 /* 0x0801D4C6: the first chunk is the last */
    body_db(a0, a1, a2, mode);                              /* the first-chunk hook: SPTR then GO */
}

/* 1F DF: B 0x0801B634; A 0x0801B90C (queue full -> 5, else 7) */
static void f_df(post_t *p)
{
    disp_job_t *j;
    if (disp_queue_full(1u)) {                              /* 0x0801B634-0x0801B642 -> 0x0801BB84 */
        refuse(p, 5u);
        return;
    }
#if DISP_BUG == 11
    if (!p->args || ARG(0) > 0x1E00u) {                     /* planted (gatelock.py): the RAM bound one word longer */
#else
    if (!p->args || ARG(0) > 0x1DFFu) {                     /* 0x0801B64A, 0x0801B654 */
#endif
        refuse(p, 7u);
        return;
    }
    j = slot(0u);                                           /* 0x0801C9A8 */
    j->b1c = p->lo;                                         /* the save slot */
    j->p18 = ARG(0);                                        /* the RAMDP destination */
    j->fail_en = FAIL_ON;
    j->p24 = EEP_KEY;
    job_queued();                                           /* 0x0801C9D6, 0x0801C9E6 */
    j->type = JOB_EEP_READ;                                 /* 0x0801C9EE */
    disp_job_commit(1u);
}

/* 20 E0: B 0x0801B5B2; A 0x0801B886 (queue full -> 5, else 7) */
static void f_e0(post_t *p)
{
    disp_job_t *j;
    if (disp_queue_full(1u)) {                              /* 0x0801B5B2-0x0801B5BE -> 0x0801BEAC */
        refuse(p, 5u);
        return;
    }
    if (!p->args || ARG(0) != 0xBEEFu || ARG(1) > 0x1DFFu) {   /* 0x0801B5C4-0x0801B5D2, 0x0801C904 */
        refuse(p, 7u);
        return;
    }
    j = slot(0u);                                           /* 0x0801CE70 */
    j->b16 = p->lo;
    j->p20 = ARG(1);                                        /* the RAMDP source */
    j->fail_en = FAIL_ON;
    j->p24 = EEP_KEY;
    job_queued();                                           /* 0x0801CE9E, 0x0801CEAE */
    j->type = JOB_EEP_WRITE;                                /* 0x0801CEB6 */
    disp_job_commit(1u);
}

/* 24 A4: B 0x0801B1C4; A 0x0801B858 (mailbox A's low byte is 0). With FW_MW (the cart's MegaWire code runs on this
   boot): the MegaWire byte gate (refusal 6, 0x0801B1CC / 0x0801B85E), the arguments (7, B only) and the body
   0x0801C046: MW+1 := the low byte (the task acts on it at its next tick). Without FW_MW, test build 5's
   fragment (0.2.6 muted A4). */
static void f_a4(post_t *p)
{
#if FW_MW
    if (s3_mw_on) {
        if (!disp_g.mw_ready) {
            refuse(p, 6u);
            return;
        }
        if (p->args) {                                      /* 0x0801B1D6 -> 0x0801CCBC / 0x0801CCA8 */
            refuse(p, 7u);
            return;
        }
        MW8(mw, MW_REQ) = p->lo;                            /* 0x0801C046 */
        return;
    }
#endif
    if (p->args)                                            /* 0x0801B1D0 */
        refuse(p, 7u);
}

/* 26 A6: B 0x0801B19C, A 0x0801B7CE; 29 A9: B 0x0801B588, A 0x0801B7A0. The arguments first (7, B only), then
   (with FW_MW) the MegaWire byte gate (6) and the bodies: A6 0x0801C2B8 (MW+0x123 := 0, $1C10 := 0, $1FE6 &= ~0x20),
   A9 0x0801C29E (MW+0x122 := 0, $1FE6 &= ~0x10). Without FW_MW both are one fragment, as in test build 5. */
#if !FW_MW
static void f_noargs(post_t *p)
{
    if (p->args)
        refuse(p, 7u);
}
#define f_a6 f_noargs
#define f_a9 f_noargs
#else
static void f_a6(post_t *p)
{
    if (p->args) {
        refuse(p, 7u);
        return;
    }
#if FW_MW
    if (s3_mw_on) {
        if (!disp_g.mw_ready) {                             /* 0x0801B7D0-0x0801B7D4 */
            refuse(p, 6u);
            return;
        }
        mw_a6_body();                                       /* 0x0801C2B8 (core/mw/mw_res.c) */
    }
#endif
}
static void f_a9(post_t *p)
{
    if (p->args) {
        refuse(p, 7u);
        return;
    }
#if FW_MW
    if (s3_mw_on) {
        if (!disp_g.mw_ready) {                             /* 0x0801B7A2-0x0801B7A6 */
            refuse(p, 6u);
            return;
        }
        mw_a9_body();                                       /* 0x0801C29E (core/mw/mw_res.c) */
    }
#endif
}
#endif

/* 27 E7: B 0x0801B39C; A 0x0801B992 (refusal 7). With FW_MW: the arguments (7), the MegaWire byte and the
   send-pending gates (6: 0x0801B3AE, 0x0801B3BC), the length (7 above 0xFB), then the body 0x0801C3FA: the packet
   from $1E10 into the E7 staging (byte-swapped words, then its length bytes swapped), MW+0x122 := 1 (sending), the
   error byte := 0, $1FE6 |= 0x10, MW+0x123 := 0, $1C10 := 0, $1FE6 &= ~0x20. Without FW_MW, test build 5's
   0.2.6 stand-in. */
static void f_e7(post_t *p)
{
#if FW_MW
    if (s3_mw_on) {
        uint32_t len;
        if (!p->args) {                                     /* 0x0801B3A2 -> 0x0801BF3E */
            refuse(p, 7u);
            return;
        }
        if (!disp_g.mw_ready || MW8(mw, MW_E7_PEND) == 1u) {    /* 0x0801B3AE / 0x0801B3BC -> 0x0801BF7E */
            refuse(p, 6u);
            return;
        }
        len = ARG(1);                                       /* 0x0801B3C2-0x0801B3C6 */
        if (len > 0xFBu) {
            refuse(p, 7u);
            return;
        }
        mw_e7_body();                                       /* 0x0801C3FA (core/mw/mw_res.c) */
        return;
    }
#endif
    if (!p->args || ARG(1) > 0xFBu) {                       /* 0x0801B3A0, 0x0801B3C4 */
        refuse(p, 7u);
        return;
    }
    body_e7();                                              /* 0x0801C3FA */
}

/* 28 A8: B 0x0801B348; A 0x0801B82A (mailbox A's low byte is 0: refusal 7 past the gate). With FW_MW: the MegaWire
   byte gate first (6: 0x0801B350 / 0x0801B832), then the arguments and the low byte (7), the queue (5) and the body
   0x0801CD34: the screen request MW+0x10 := 1, the watchdog disarmed. The game posts A858 with no module too (the
   Options pad code), and the cart then shows its MegaWire screen: the screen loop 0x080225F8 with its pages A / B,
   which the thread runs (core/mw/mw_screen.c). */
static void f_a8(post_t *p)
{
#if FW_MW
    if (s3_mw_on && !disp_g.mw_ready) {
        refuse(p, 6u);
        return;
    }
#endif
    if (p->args || p->lo != 0x58u) {                        /* 0x0801B354, 0x0801C1A2 */
        refuse(p, 7u);
        return;
    }
    if (disp_queue_full(1u)) {                              /* 0x0801C1AA-0x0801C1B4 */
        refuse(p, 5u);
        return;
    }
#if FW_MW
    if (s3_mw_on) {
        mw_scr_on = 1u;                                     /* ours: the thread may now read the screen state */
        MW16(mw, MW_SCREEN) = 1u;                           /* 0x0801CD38: the thread's screen loop takes it from
                                                               here (core/mw/mw_screen.c; nothing of it runs in L1) */
    }
#endif
    disp_g.wd_arm = 0u;                                     /* 0x0801CD3E: the watchdog disarmed */
    disp_g.f81[3] = 0u;                                     /* 0x0801CD42 */
    disp_g.wd_count = 0u;                                   /* 0x0801CD44 */
}

/* 2A AA: B 0x0801B320, A 0x0801B7FC (no MegaWire byte gate). With FW_MW: the body 0x0801CCD0, the MegaWire reset and
   init (0x0802171C, 0x080218FC). Ours runs them at the task's next tick, in the thread, not inside the mailbox
   interrupt (the init writes 12.8 KB of SRAM: far more time than L1 may take); AA58 is posted only from the MegaWire
   menu (status 1 or more), so the Pocket never posts it. */
static void f_aa(post_t *p)
{
    if (p->args || p->lo != 0x58u)                          /* 0x0801B324, 0x0801B800 */
        refuse(p, 7u);
#if FW_MW
    else if (s3_mw_on)
        mw_aa_pending = 1u;
#endif
}

/* 2C EC: B 0x0801B152; A 0x0801B8DA (engine set -> 7, else 6) */
static void f_ec(post_t *p)
{
    if (!disp_g.eng_ready) {                                /* 0x0801B15A */
        refuse(p, 6u);
        return;
    }
    if (!p->args || ARG(0) != 0u || ARG(1) > 0x80u) {       /* 0x0801B162-0x0801B176 */
        refuse(p, 7u);
        return;
    }
    body_ec(ARG(1));                                        /* 0x0801CD5E -> 0x08017EE0(0, a1) */
}
static void f_ec_a(post_t *p) { refuse(p, disp_g.eng_ready ? 7u : 6u); }

/* 2D AD: 0x0801AD9C (both): the engine flag, then 0x0801BE18-0x0801BE20: an object index above $3F is refused (7),
   the end of the 64-entry handle table */
static void f_ad(post_t *p)
{
    if (!disp_g.eng_ready) {
        refuse(p, 6u);
        return;
    }
    if (p->lo > 0x3Fu) {                                    /* 0x0801BE1C-0x0801BE1E */
        refuse(p, 7u);
        return;
    }
    body_ad(p->lo);                                         /* 0x0801C2DA -> 0x080194BC(lo) */
}

/* 2E AE: 0x0801ADCC (both) */
static void f_ae(post_t *p)
{
    if (!disp_g.eng_ready) {
        refuse(p, 6u);
        return;
    }
    body_ae();                                              /* 0x08018FBC: slot aging (0x08017FDC) */
    disp_g.af_parity++;                                     /* 0x08018FC2-0x08018FCA: H+$403 += 1 */
    brd_freg_wr(BRD_FREG_FF6, 1u);                          /* 0x08018FD2 */
    st_set(0u, ST_FE4, 0x100u);                             /* 0x08018FDC */
    disp_g.frame_open = 1u;                                 /* 0x0801BFB4 */
}

/* 2F AF: 0x0801AD6C (both) -> 0x0801BCE6. An AF that no AE opened only finishes (no flush, no frame end, the open flag
   left as it is: 0x0801BCE6-0x0801BCEE). Otherwise the cart chip's frame end 0x080190B8(lo & 3): the flush first
   (0x080190D2), then the close with the mode and the multiplex parity (body_af), then the open flag cleared and the
   finish */
static void f_af(post_t *p)
{
    if (!disp_g.eng_ready) {
        refuse(p, 6u);
        return;
    }
    if (!disp_g.frame_open)                                 /* 0x0801BCE6-0x0801BCEC -> the finish 0x0801BCEE */
        return;
    flush_regs();                                           /* 0x080190B8 calls the flush at 0x080190D2 */
    body_af((uint8_t)(p->lo & 3u), disp_g.af_parity);       /* 0x0801BCF2-0x0801BCF6: the frame end, mode = lo & 3 */
    disp_g.frame_open = 0u;                                 /* 0x0801BCFA-0x0801BCFC */
#if !PPM_RELEASE && !TDIAG_LEAN
    finish(p->mbx);                                         /* TEST: the finish 0x0801BCEE here, so that */
    p->deferred = 1u;                                       /* (not finished again) TEST's SAT-snapshot bookkeeping */
    body_af_replied();                                      /* comes after AF's reply, not before it */
#endif
}

/* 30 B0: 0x0801AD3C (both) */
static void f_b0(post_t *p)
{
    if (!disp_g.eng_ready) {
        refuse(p, 6u);
        return;
    }
    body_b0();                                              /* 0x0801940C */
#if SPR_BUG != 3
    disp_g.af_parity++;                                     /* 0x08019414-0x0801941C: H+$403 += 1 */
#endif
    brd_freg_wr(BRD_FREG_FF6, 1u);                          /* 0x08019426 */
    st_set(0u, ST_FE4, 0x100u);                             /* 0x08019432 */
}

/* 31 B1: 0x0801AD0C (both) */
static void f_b1(post_t *p)
{
    if (!disp_g.eng_ready) {
        refuse(p, 6u);
        return;
    }
    flush_regs();                                           /* 0x0801BFBA -> 0x08018FFC */
    body_b1();
}

/* 32 F2: B 0x0801B5FA; A 0x0801B8B8 (engine clear -> 6, else 7) */
static void f_f2(post_t *p)
{
    uint32_t a;
    uint16_t blk;
    if (!disp_g.eng_ready) {                                /* 0x0801B602 -> 0x0801BD9E */
        refuse(p, 6u);
        return;
    }
    if (!p->args) {                                         /* 0x0801B60C */
        refuse(p, 7u);
        return;
    }
    blk = ARG(0);                                           /* 0x0801C294 */
    brd_freg_wr(BRD_FREG_FE8, 1u);                          /* 0x08017E6E */
    brd_freg_wr(BRD_FREG_FF6, 1u);                          /* 0x08017E70 */
    st_set(0u, ST_FE4, 0x100u);                             /* 0x08017E7E */
    a = body_block_addr(blk) & 0x7FFFFEu;                   /* 0x08017E84-0x08017EAE: the block table entry */
    push_entry(a);                                          /* 0x08017EB0 / 0x08017EB2 */
    push_entry(a);                                          /* 0x08017EB4 / 0x08017EB8: the same entry twice */
    body_dec_scratch();                                     /* the board: the decoder's output base (v1.2) */
    brd_freg_wr(BRD_FREG_FF2, 0x8000u);                     /* 0x08017EBA */
    st_set(1u, ST_FE4, 0x100u);                             /* 0x08017EC6 */
}
static void f_f2_a(post_t *p) { refuse(p, disp_g.eng_ready ? 7u : 6u); }

/* 34 F4: B 0x0801B4EA; A 0x0801BA1A (refusal 7) */
static void f_f4(post_t *p)
{
    uint32_t src;
    uint8_t t;
    disp_job_t *j, *k;
    if (!p->args) {                                         /* 0x0801B4EE -> 0x0801BE62 */
        refuse(p, 7u);
        return;
    }
    if (disp_queue_full(1u) || disp_queue_full(2u)) {       /* 0x0801B4F4-0x0801B50C: two free slots */
        refuse(p, 5u);
        return;
    }
    src = ((uint32_t)ARG(0) << 16) | ARG(1);                /* 0x0801B512-0x0801B51A */
    if (src > 0x800000u) {                                  /* 0x0801B520 */
        refuse(p, 7u);
        return;
    }
    t = brd_rom_byte(src & ~1u);                            /* 0x0801C946-0x0801C954 */
    if ((uint8_t)(t - 0x80u) > 1u) {                        /* 0x0801C95A: type 0x80 / 0x81 only */
        refuse_t(p, 7u | ((uint32_t)p->r6 << 8) | ((uint32_t)(ARG(0) & 0xFFu) << 8));   /* 0x0801C970-0x0801C97C */
        return;
    }
    j = slot(0u);                                           /* 0x0801CFF6 */
    j->p20 = src;
    j->p18 = 0u;                                            /* the chip: SRAM 0x200119EC (the scaling source) */
    job_queued();                                           /* 0x0801D012, 0x0801D022 */
    j->type = JOB_UNPACK_F4;                                /* 0x0801D02E */
    j->fail_en = FAIL_ON;                                   /* 0x0801D030 */
    k = slot(1u);                                           /* 0x0801D034-0x0801D048 */
    k->fail_en = FAIL_ON;
    k->p20 = 0u;
    k->b16 = 0u;
    k->p24 = 0u;
    k->type = JOB_SCALE_SAVE;
    disp_g.sc_session = 0u;                                 /* 0x0801D04E */
    disp_g.sc_pending = 0u;                                 /* 0x0801D050 */
    disp_job_commit(2u);                                    /* 0x0801D052 */
}

/* 35 F5: B 0x0801B54A; A 0x0801B9F8 (refusal 7) */
static void f_f5(post_t *p)
{
    disp_job_t *j;
    unsigned i;
    if (!p->args) {                                         /* 0x0801B54E -> 0x0801BE44 */
        refuse(p, 7u);
        return;
    }
    if (disp_queue_full(1u)) {                              /* 0x0801B554-0x0801B560 */
        refuse(p, 5u);
        return;
    }
    if (!disp_g.sc_session || disp_g.sc_pending)            /* 0x0801BFD6-0x0801BFE8: ignored, no error */
        return;
    for (i = 0; i < 4u; i++)                                /* 0x0801BFEC-0x0801C006 */
        disp_g.sc_args[i] = ARG(i);
    disp_g.sc_pending = 1u;                                 /* 0x0801C00A */
    j = slot(0u);
    j->p20 = 0u;                                            /* 0x0801C012-0x0801C018 */
    j->b16 = 0u;
    j->p24 = 0u;
    j->fail_en = FAIL_ON;
    job_queued();                                           /* 0x0801C022, 0x0801C032 */
    j->type = JOB_RESCALE;                                  /* 0x0801C03A */
    disp_job_commit(1u);
}

/* 36 B6: B 0x0801B2F8; A 0x0801B76C (the B entry after its argument test) */
static void f_b6_a(post_t *p)
{
    disp_job_t *j;
    if (disp_queue_full(1u)) {                              /* 0x0801B76C-0x0801B778 */
        refuse(p, 5u);
        return;
    }
    if (!disp_g.sc_session)                                 /* 0x0801C13E-0x0801C148: ignored, no session */
        return;
    j = slot(0u);
    j->p20 = 0u;                                            /* 0x0801C15C-0x0801C162 */
    j->b16 = 0u;
    j->p24 = 0u;
    j->fail_en = FAIL_ON;
    disp_g.sc_session = 0u;                                 /* 0x0801C164 */
    job_queued();                                           /* 0x0801C16E, 0x0801C17E */
    j->type = JOB_RESTORE;                                  /* 0x0801C186 */
    disp_job_commit(1u);
}
static void f_b6(post_t *p)
{
    if (p->args) {                                          /* 0x0801B2FA-0x0801B2FE */
        refuse(p, 7u);
        return;
    }
    f_b6_a(p);
}

/* ---- the two tables: 55 entries each (the chip's 0x08025AC8 and 0x080259EC) -------------------------------- */
#if !FW_S5
#define f_d3_a f_refuse7                                    /* A's D3: refusal 7 (0x0801B970) */
#endif
#define N_IDX                   0x37u
static const frag_fn tab_b[N_IDX] = {
    [0x00] = f_default, [0x01] = f_81,      [0x02] = f_82,      [0x03] = f_83,      [0x04] = f_84,
    [0x05] = f_85,      [0x06] = f_c6,      [0x07] = f_default, [0x08] = f_88,      [0x09] = f_c9,
    [0x0A] = f_ca,      [0x0B] = f_default, [0x0C] = f_8c,      [0x0D] = f_8d,      [0x0E] = f_8e,
    [0x0F] = f_default, [0x10] = f_d0,      [0x11] = f_d1,      [0x12] = f_d2,      [0x13] = f_d3,
    [0x14] = f_tick,    [0x15] = f_d5,      [0x16] = f_d6,      [0x17] = f_default, [0x18] = f_default,
    [0x19] = f_default, [0x1A] = f_da,      [0x1B] = f_db,      [0x1C] = f_default, [0x1D] = f_default,
    [0x1E] = f_default, [0x1F] = f_df,      [0x20] = f_e0,      [0x21] = f_default, [0x22] = f_default,
    [0x23] = f_default, [0x24] = f_a4,      [0x25] = f_default, [0x26] = f_a6,     [0x27] = f_e7,
    [0x28] = f_a8,      [0x29] = f_a9,      [0x2A] = f_aa,      [0x2B] = f_default, [0x2C] = f_ec,
    [0x2D] = f_ad,      [0x2E] = f_ae,      [0x2F] = f_af,      [0x30] = f_b0,      [0x31] = f_b1,
    [0x32] = f_f2,      [0x33] = f_default, [0x34] = f_f4,      [0x35] = f_f5,      [0x36] = f_b6,
};
/* mailbox A: r6's low byte is 0 and sl is 0 (the A entries of C9, CA, D0, D1, D2, D5 and D6
   set it before the B code); the argument-taking commands refuse */
/* with FW_MW: mailbox A's A4 and A8 get their own entries (the MegaWire byte gate first, 0x0801B858 /
   0x0801B82A); without FW_MW they keep test build 5's (the same answers there: A's low byte is 0) */
#if FW_MW
#define A_24 f_a4
#define A_28 f_a8
#else
#define A_24 f_noargs
#define A_28 f_aa
#endif
static const frag_fn tab_a[N_IDX] = {
    [0x00] = f_default, [0x01] = f_81,      [0x02] = f_82,      [0x03] = f_83,      [0x04] = f_84,
    [0x05] = f_85,      [0x06] = f_refuse7, [0x07] = f_default, [0x08] = f_88,      [0x09] = f_c9,
    [0x0A] = f_ca,      [0x0B] = f_default, [0x0C] = f_8c,      [0x0D] = f_8d,      [0x0E] = f_8e,
    [0x0F] = f_default, [0x10] = f_d0,      [0x11] = f_d1,      [0x12] = f_d2,      [0x13] = f_d3_a,
    [0x14] = f_tick,    [0x15] = f_d5,      [0x16] = f_d6,      [0x17] = f_default, [0x18] = f_default,
    [0x19] = f_default, [0x1A] = f_full5_else7,    [0x1B] = f_refuse7, [0x1C] = f_default, [0x1D] = f_default,
    [0x1E] = f_default, [0x1F] = f_full5_else7,    [0x20] = f_full5_else7,    [0x21] = f_default, [0x22] = f_default,
    [0x23] = f_default, [0x24] = A_24,      [0x25] = f_default, [0x26] = f_a6,     [0x27] = f_refuse7,
    [0x28] = A_28,      [0x29] = f_a9,      [0x2A] = f_aa,      [0x2B] = f_default, [0x2C] = f_ec_a,
    [0x2D] = f_ad,      [0x2E] = f_ae,      [0x2F] = f_af,      [0x30] = f_b0,      [0x31] = f_b1,
    [0x32] = f_f2_a,    [0x33] = f_default, [0x34] = f_refuse7, [0x35] = f_refuse7, [0x36] = f_b6_a,
};

/* ---- the dispatchers ------------------------------------------------------------------------------------------ */
static void dispatch_b(post_t *p)                           /* 0x0801BA4E */
{
    uint16_t w = brd_freg_rd(BRD_FREG_FEA);                 /* 0x0801BA5E: the word is read again */
    uint32_t idx;
    disp_g.cur_word = w;
    disp_g.cur_mbx = MBX_B;
    st_set(0u, ST_FE6, 0x8200u);                            /* 0x0801BA6C: idle and refused, cleared */
    p->args = (uint8_t)((w >> 14) & 1u);                    /* sl */
    p->r6 = (uint16_t)(w & 0x3FFFu);
    p->lo = (uint8_t)w;
    idx = p->r6 >> 8;
    if (idx >= N_IDX) {                                     /* 0x0801BA7E: > 0x36 -> 0x0801B6F0 */
        f_default(p);
        return;
    }
    tab_b[idx](p);                                          /* 0x0801BA84-0x0801BA8A */
}

static void dispatch_a(post_t *p)                           /* 0x0801B712 */
{
    uint16_t w = brd_freg_rd(BRD_FREG_FEC);
    uint32_t idx;
    disp_g.cur_word = w;
    disp_g.cur_mbx = MBX_A;
    p->r6 = (uint16_t)(w & 0x3F00u);                        /* the low byte is dropped */
    p->lo = 0u;
    p->args = 0u;
    st_set(0u, ST_FE6, 0x8400u);                            /* 0x0801B726 */
    idx = p->r6 >> 8;
    if (idx >= N_IDX) {                                     /* -> 0x0801BA3C */
        f_default(p);
        return;
    }
    tab_a[idx](p);
}

/* ---- the mailbox entry (L1; sched.c calls it after acknowledging the cause bit and reading the word) ------- */
void disp_post(uint32_t mbx, uint16_t word)                 /* mailbox_irq 0x0801AC3C */
{
    post_t p = { mbx, 0u, 0u, 0u, 0u };
    if (!disp_g.app_ready) {                                /* 0x0801AC4A-0x0801AC50: G+8 */
        st_set(1u, ST_FE6, mbx == MBX_A ? 0x400u : 0x200u); /* 0x0801ACDC / 0x0801ACFA */
        chip_trace(6u, 0u, 0u);                             /* 0x0801AC5A-0x0801AC60 */
        finish(mbx);
        return;
    }
    if (mbx == MBX_A) {
        if (word & 0x80u)                                   /* 0x0801ACCE: the request = the low byte's bit 7 */
            dispatch_a(&p);
    } else {
        if (word & 0x8000u)                                 /* 0x0801ACB6-0x0801ACBA: the request = bit 15 */
            dispatch_b(&p);
    }
    if (!p.deferred)
        finish(mbx);
}

/* the engine posts that are held while a tick runs (88, C9, CA, 8C/8D/8E, D0-D6 incl. 95/96, and 83) */
uint32_t disp_holdable(uint32_t mbx, uint16_t word)
{
    uint32_t idx = (word >> 8) & 0x3Fu;
    if (mbx == MBX_A ? !(word & 0x80u) : !(word & 0x8000u))
        return 0u;                                          /* not dispatched at all */
    return idx == 0x03u || (idx >= 0x08u && idx <= 0x0Eu && idx != 0x0Bu) || (idx >= 0x10u && idx <= 0x16u);
}

void disp_tick_tail(void) { finish(tick_mbx); }             /* FW_S5: the deferred finish of the tick post */

void disp_console_reset(void) { }                           /* EXTI 13 (0x08015474): the chip only acknowledges */

#if FW_S5
/* ---- FW_S5: L1's entry with the arrival number, and the engine queue's dispatcher hooks ------------------------- */
void disp_post_s5(uint32_t mbx, uint16_t word, uint16_t seq, uint32_t stamp)
{
    disp_g.cur_seq = seq;
    disp_g.cur_stamp = stamp;
    disp_post(mbx, word);
}

/* a post the full engine queue held back: the queue has taken it now (its gates ran), so it is finished now */
void board_post_finish(uint32_t mbox) { finish(mbox == 1u ? MBX_A : MBX_B); }

/* The cart chip's u16 that is event_post's trace counter 11 is ALSO the underrun count:
   the Z80 packet build (on ours this count is made in the firmware: the YM-DAC flush found the
   frame's blocks unmixed) and the DT block mix (on ours this count is made in the synth's logic:
   a DT half incomplete) increment it as a u16, beside
   event_post's code-11 count, and the main-loop pass copies it to $1B00 word 11. Ours uses the same word; the DT half
   comes from the synth's DIAG.INCOMPLETE (docs/MCU_INTERFACE.md v1.3 section 3.10.1), folded in by its delta (a read
   only, so it may run beside a block).
   DIAG's counts saturate and any write clears all four, so a count the logic made between the last read and the clear
   would be lost. The clear is therefore made only inside the tick's item (in_item: the flush, between synth_begin and
   synth_end of a 9494, so DONE < its arrival <= ARR), once a count is high, and only when STATUS, read BEFORE the last
   DIAG read, shows BUSY = 0 and QDEPTH <= 1. Then no TIM6 instant (the synth's timer) can be serviced before the clear:
   by v1.3 section 3.10.5 a newer instant gets NEED = ARR > DONE and waits for DONE, which only this firmware moves;
   the one queued instant, if any, is the latest, younger than a TIM6 period of 2.09 ms, so it cannot reach the 5 ms
   TIMEOUT; the queue holds 8. And INCOMPLETE and TIMEOUTS (counted at a service) and WBUSY (MCU writes while RUN = 1)
   cannot move in the window. Otherwise the clear waits for a later tick (s5_diag_defer), unless INCOMPLETE has reached
   0xF0, where saturation would lose counts for certain (s5_diag_forced). UNDERRUN (DT playback, TEST telemetry) may
   still count inside the window, at most one per clear: v1.3 gives no instant to clear it against. s5_diag_acc keeps
   all four DIAG counts as totals (TEST telemetry; a clear zeroes the register, not these). */
uint8_t  s5_diag_base[4];
uint32_t s5_diag_acc[4];
uint32_t s5_diag_defer, s5_diag_forced;
static uint32_t diag_fold(uint32_t d)
{
    uint32_t i, n, high = 0u;
    for (i = 0; i < 4u; i++) {
        n = ((d >> (8u * i)) - s5_diag_base[i]) & 0xFFu;
        s5_diag_base[i] = (uint8_t)(d >> (8u * i));
        s5_diag_acc[i] += n;
        if (i == 0u)
            disp_g.trace_cnt[11] = (uint16_t)(disp_g.trace_cnt[11] + n);     /* DIAG.INCOMPLETE */
        high |= s5_diag_base[i] & 0x80u;
    }
    return high;
}
void board_underrun(void) { disp_g.trace_cnt[11]++; }
void board_trace_fold(uint32_t in_item)
{
    uint32_t s = sched_crit_enter(), i, quiet;
    if (diag_fold(brd_synth_diag()) && in_item) {
#if SONG_BUG == 19
        quiet = 1u;                                 /* planted: the clear without the STATUS test */
#else
        uint32_t st;
#if SONG_BUG == 20
        (void)diag_fold(brd_synth_diag());          /* planted: the last DIAG read before the STATUS read */
#endif
        st = brd_synth_status();
        quiet = (st & BRD_SYNTH_BUSY) == 0u && BRD_SYNTH_QDEPTH(st) <= 1u;
#endif
        if (quiet || s5_diag_base[0] >= 0xF0u) {
            if (!quiet)
                s5_diag_forced++;
#if SONG_BUG != 19 && SONG_BUG != 20
            (void)diag_fold(brd_synth_diag());      /* what the synth counted up to the STATUS read */
#endif
            brd_synth_diag_clear();                 /* any write clears all four */
            for (i = 0; i < 4u; i++)
                s5_diag_base[i] = 0u;
        } else {
            s5_diag_defer++;
#if SONG_BUG == 21
            for (i = 0; i < 4u; i++)                /* planted: a put-off clear forgets the folded counts */
                s5_diag_base[i] = 0u;
#endif
        }
    }
    sched_crit_leave(s);
}

/* the status helper and event_post, as the song engine calls them (reg 3 = $1FE6, 2 = $1FE4: the chip's numbers) */
void board_status(uint32_t set, uint32_t reg, uint32_t mask) { st_set(set, reg, (uint16_t)mask); }

/* the cart chip's main loop: a job queued -> the job (its tail runs the pass after it); none -> the pass, again
   and again (no WFI). A queued or running job therefore holds
   the pass: $1FE6 bit 3 and the feed stay as they were across an 8C's job */
uint32_t disp_s5_jobs(void)
{
    return SONG_BUG != 35 && ((disp_g.q_wr ^ disp_g.q_rd) & 0xFu) != 0u;
}

/* the pass with the dispatcher's 81 flags: 81 bit 1 the 16 counters to $1B00, 81 bit 2 the Boom Box feed */
void disp_s5_pass(void) { song_main_pass(disp_g.f81[0] ? disp_g.trace_cnt : 0, disp_g.f81[1]); }
void board_trace(uint32_t code, uint32_t a, uint32_t b) { chip_trace(code, a, b); }

/* 8C's job (song_gate did the gates and bits 14 / 8): queue full (gate 5) and the push of the unpack job (type 2,
   no failure report, the module: the BGM table entry); ours keeps the track for the store decoded at C6 */
uint32_t board_job_full(void) { return disp_queue_full(1u); }
void board_job_8c(uint32_t src_bus, uint32_t track)
{
    disp_job_t *j = slot(0u);
    j->type = JOB_UNPACK_8C;
    j->fail_en = 0u;
    j->p20 = src_bus;
    j->s1_lo = (uint8_t)track;
    disp_job_commit(1u);
}
#endif
