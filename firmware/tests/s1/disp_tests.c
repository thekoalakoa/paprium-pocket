/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/s1/disp_tests.c - host test of the dispatcher, status layer and job queue, which work as the cart chip's, on
 * the x86 fake board. Built and run by tools/fwbuild.py s1; exit 1 on a failed check. The bodies are this test's
 * recorders (disp_bodies.h), so the test is about the chip's structure only; the 0.2.6 bodies are proven by
 * tests/equiv/s1_equiv.py and the chip's register order by the chip-runner oracle (outside the tree).
 *
 * Part 1, scenarios: the job queue (15 usable slots, the refusal 5 when full, F4's two slots), the job failure bit 8,
 *   the C6 one-shot, the 9494 head, 82, the default refusal on both mailboxes, a word with no request bit, the A
 *   mailbox forms, DA06/07 direct vs job, the scaling session gates of F5 / B6.
 * Part 2, the fuzz (FZ1, FZ2, FZ3, FZ4, FZ6, FZ7 of docs/STAGE1_PLAN.md section 4.7): the 68000 plays the game's post
 *   protocol from inside the fake board's points (wait for $1FEA bit 15 clear, write the arguments and the post; the
 *   tick on $1FEC), at random points of the thread's jobs and board work, with random job lengths and random job
 *   failures (bit 8, the thread's own status write); posts that wait for bit 14 and posts that do not, with bursts of
 *   no-wait job posts against slow jobs that fill the queue (refusal 5 is required on every seed). Every menu entry
 *   must be accepted at least once. Seeds x posts; every point checks:
 *   FZ1  every $1FEA post gets exactly one MCU $1FEA := 0, refusals included; FZ6 the same for $1FEC;
 *   FZ2  when the 68000 first sees its post finished, $1FE6 already holds what the chip stores before its finish:
 *        bit 14 set for an accepted job post (its job cannot have run before that point), bit 9 for a refusal;
 *   FZ3  a job body's GO is stored before the job step clears bit 14;
 *   FZ4  after the first job, outside the mailbox handler, $1FE6 bit 14 = the queue is not empty (or runs a job);
 *        it is clear when the thread is idle;
 *   FZ7  $1FE6 / $1FE4 = the status helper's shadows at every point outside a critical section.
 *   Since MCU interface v1.2 the sprite decoder is the RTL's (the fake board decodes at the START): AF / B1 push
 *   the frame's load list last to first, F2 its block twice, DA06 / DA07 with a 0x80 source their stream, each with the
 *   decoder's output base before the START, and every one finishes at once (scenarios: the chip's write order, the
 *   decode, the GO; fuzz: every AF / F2 / DA direct post finished in its own L1).
 * Negative controls (fwbuild.json s1.host "negative"): the same test built with a planted bug (-DDISP_BUG=1..4 in
 * core/dispatch) must fail, or the build stops. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "board.h"
#include "sched.h"
#include "sched_hooks.h"
#include "disp.h"
#include "disp_bodies.h"
#include "appinit.h"

static int fails, checks;
#define CHECK(c) do { checks++; if (!(c)) { fails++; if (fails < 40) printf("FAIL disp_tests.c:%d %s\n", __LINE__, #c); } } while (0)

/* ---- recorders --------------------------------------------------------------------------------------------- */
static uint32_t n_body, n_job, job_cost, job_fail_code, n_direct;
static uint8_t af_mode, af_par;                    /* what the dispatcher handed AF's frame
                                                      end (since the sprite-values update) */
static uint32_t go_at, go_seen;                     /* the log index of the last GO (FZ3) */
static uint32_t load_list[15], load_n;              /* the load list body_load_list gives the flush */
static void burn(uint32_t points) { while (points--) (void)brd_now(); }   /* every call is a board point */
void body_88(uint8_t lo) { (void)lo; n_body++; }
void body_c9(uint8_t lo) { (void)lo; n_body++; }
void body_ca(uint8_t lo) { (void)lo; n_body++; }
void body_8d(uint8_t lo) { (void)lo; n_body++; }
void body_d1(uint8_t lo) { (void)lo; n_body++; }
void body_d2(uint8_t lo) { (void)lo; n_body++; }
void body_d3(uint8_t lo) { (void)lo; n_body++; }
void body_d5(uint8_t lo) { (void)lo; n_body++; }
void body_ad(uint8_t lo) { (void)lo; n_body++; }
void body_ae(void) { n_body++; }
void body_af(uint8_t m, uint8_t q) { af_mode = m; af_par = q; n_body++; }
#if !PPM_RELEASE
static uint32_t n_replied, replied_early;           /* TEST (since 2026-10-18): AF's SAT-snapshot
                                                       bookkeeping, after its reply */
void body_af_replied(void)
{
    n_replied++;
    replied_early += hb_68k_read(BRD_FREG_FEA) != 0u || !(hb_68k_read(BRD_FREG_FE6) & 0x8000u);   /* not replied yet */
}
#endif
void body_b0(void) { n_body++; }
void body_b1(void) { n_body++; }
void body_ec(uint16_t s) { (void)s; n_body++; }
uint32_t body_block_addr(uint16_t b);              /* below: the ROM's streams */
uint32_t body_load_list(const uint32_t **list) { *list = load_list; return load_n; }
void body_dec_scratch(void) { brd_dec_base(0x1E0000u); }
void body_db(uint16_t a0, uint16_t a1, uint16_t a2, uint8_t mode)
{
    (void)mode;
    n_body++;
    brd_stream_ptr(((uint32_t)a0 << 16) | a1);
    brd_stream_go(a2 >> 1);
}
void body_da_direct(uint32_t src, uint16_t dst, uint8_t mode) { (void)src; (void)mode; n_direct++; brd_dec_base(dst); }
void body_e7(void) { n_body++; }
static void job_go(void) { brd_stream_ptr(0x9000u); brd_stream_go(0x80u); go_at = hb.nlog; go_seen = 1u; }
uint32_t job_unpack(const disp_job_t *j)
{
    n_job++;
    burn(job_cost);
    if (j->type == JOB_UNPACK_DA && j->s1_mode == 7u)
        job_go();                                   /* FZ3: the GO before the job step's bit-14 store */
    return job_fail_code;
}
uint32_t job_eep_read(const disp_job_t *j) { (void)j; n_job++; burn(job_cost); return 0u; }
uint32_t job_eep_write(const disp_job_t *j) { (void)j; n_job++; burn(job_cost); return job_fail_code ? 9u : 0u; }
void job_scale_save(void) { n_job++; }
void job_scale_setup(void) { }
void job_rescale(const uint16_t a[4]) { (void)a; n_job++; burn(job_cost); }
void job_restore(void) { n_job++; }
uint32_t job_setup(const uint32_t l[8], uint32_t mw) { (void)l; (void)mw; n_job++; burn(job_cost); return SETUP_ENG | SETUP_MW | SETUP_SFX | SETUP_SEQ; }

/* ---- a ROM with 0x80 streams, one 0x81 and one 0x90 (the DA / F4 type checks read the byte view); the 0x80 streams
   decode on the fake board's RTL decoder (v1.2): SRC80 = 8 x 0xAA, SRC80B = 3 literals, 5 zeros and a copy (d 2) ---- */
static uint16_t rom[BRD_ROM_BYTES / 2u];
#define SRC80                   0x00100000u
#define SRC81                   0x00100100u
#define SRC90                   0x00100200u
#define SRC80B                  0x00100300u
uint32_t body_block_addr(uint16_t b) { return (b & 1u) ? SRC80B : SRC80; }

static void boot(void)
{
    hb_reset();
    memset(rom, 0, sizeof rom);
    rom[SRC80 / 2u] = 0x8048u;                      /* 80, 48 AA (RLE 8 x AA), 00 (end) */
    rom[SRC80 / 2u + 1u] = 0xAA00u;
    rom[SRC81 / 2u] = 0x8100u;
    rom[SRC90 / 2u] = 0x9000u;
    rom[SRC80B / 2u] = 0x8003u;                     /* 80, 03 11 22 33 (3 literals), C5 (5 zeros), 84 02 (copy 4 at d 2), 00 */
    rom[SRC80B / 2u + 1u] = 0x1122u;
    rom[SRC80B / 2u + 2u] = 0x33C5u;
    rom[SRC80B / 2u + 3u] = 0x8402u;
    rom[SRC80B / 2u + 4u] = 0x0000u;
    hb.rom = rom;
    sched_init();
    boot_page();
    app_start();
    boot_mw_status();
    brd_cause_ack(BRD_CAUSE_ALL);
    brd_lines_on(BRD_LINES_ALL);
    brd_irq_enable();
    brd_md_hold(0u);
    n_body = n_job = n_direct = 0u;
    job_cost = 0u;
    job_fail_code = 0u;
    load_n = 0u;
}

/* the workspace byte p as the MCU stores it (the RTL decoder's view: byte p at p ^ 1, as ppm_unpack's) */
static uint8_t wsb(uint32_t p) { return hb.workspace[p ^ 1u]; }

/* the decoder's and the window's register writes ($1FE8, $1FF2, $1FF4, $1FF6), the finish ($1FEA) and the DEC_BASE
   board write logged since index i0, exactly want[0..n) in order (the status words and the other board tags skipped) */
static int log_has(uint32_t i0, const uint32_t *want, uint32_t n)
{
    uint32_t i, k = 0u;
    for (i = i0; i < hb.nlog; i++) {
        uint32_t e = hb.log[i], off = (e >> 16) & 0x1Fu;
        if (e >> 30) {
            if ((e >> 24) != HB_LOG_DECB)
                continue;
        } else if (off != BRD_FREG_FE8 && off != BRD_FREG_FF2 && off != BRD_FREG_FF4 && off != BRD_FREG_FF6 &&
                   off != BRD_FREG_FEA) {
            continue;
        }
        if (k >= n || e != want[k])
            return 0;
        k++;
    }
    return k == n;
}

static void args(const uint16_t *a, unsigned n) { unsigned i; for (i = 0; i < n; i++) hb.ram[0x1E10u / 2u + i] = a[i]; }
static void drain(void) { while (sched_l2c_once()) ; }   /* L2c's pass, guarded against a nested L2b's */
static void post(uint16_t w) { hb_68k_write(BRD_FREG_FEA, w); (void)brd_now(); }   /* L1 takes it at the point */
static uint16_t fe6(void) { return hb_68k_read(BRD_FREG_FE6); }

/* ================================================================================================================
 * Part 1: scenarios
 * ================================================================================================================ */
static void scenarios(void)
{
    static const uint16_t c6a[16] = { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16 };
    uint16_t a[4];
    int i;

    boot();
    brd_lines_off(BRD_LINE_MSI);                    /* a queued job raises MSI and L2c would run it at the next
                                                       point; the scenarios hold the jobs until drain() looks at them */
    /* before C6: the C6-done gates refuse (code 6, bit 9) */
    post(0x8802);
    CHECK(fe6() & 0x200u);
    CHECK(n_body == 0u);
    CHECK(hb.freg[BRD_FREG_FEA >> 1] == 0u && (fe6() & 0x8000u));
    /* C6: bit 14 queued, the job runs in the thread, bit 14 clear after; the flags come up */
    args(c6a, 16);
    post(0xC600);
    CHECK((fe6() & 0xC300u) == 0xC000u);            /* bit 15 (finished), 14 (queued); 9 and 8 clear */
    CHECK(disp_g.c6_longs[0] == 0x00010002u && disp_g.c6_longs[7] == 0x000F0010u);
    CHECK(hb.ram[0x1800u / 2u] == 0u && hb.ram[0x1802u / 2u] == 0u);
    drain();
    CHECK(n_job == 1u && !(fe6() & 0x4000u));
    CHECK(disp_g.mixer && disp_g.seq_ready && disp_g.sfx_ready && disp_g.eng_ready);
    CHECK(disp_g.af_parity == 1u && !disp_g.frame_open);    /* the sprite init: H+$403 += 1 (0x08019740) */
    /* a second C6: completes, no job (0x0801B204) */
    post(0xC600);
    CHECK(!(fe6() & 0x4000u) && !(fe6() & 0x200u));
    drain();
    CHECK(n_job == 1u);
    /* a C6 without arguments: refusal 7 */
    post(0x8600);
    CHECK(fe6() & 0x200u);
    /* the queue: 15 usable slots, the 16th post is refused with code 5 */
    a[0] = 0x0800; a[1] = 0x0080;
    args(a, 2);
    for (i = 0; i < 15; i++) {
        post(0xDF01);
        CHECK(!(fe6() & 0x200u));
    }
    CHECK(((disp_g.q_wr - disp_g.q_rd) & 0xFFu) == 15u);
    post(0xDF01);
    CHECK((fe6() & 0x200u) && (disp_g.trace_cnt[5] >= 1u));
    /* F4 needs two slots: refused with one free */
    drain();
    CHECK(((disp_g.q_wr ^ disp_g.q_rd) & 0xFu) == 0u && !(fe6() & 0x4000u));
    for (i = 0; i < 14; i++)
        post(0xDF01);
    a[0] = (uint16_t)(SRC80 >> 16); a[1] = (uint16_t)SRC80;
    args(a, 2);
    post(0xF400);
    CHECK(fe6() & 0x200u);                          /* only one slot free */
    drain();
    post(0xF400);
    CHECK(!(fe6() & 0x200u) && ((disp_g.q_wr - disp_g.q_rd) & 0xFFu) == 2u);
    drain();
    CHECK(disp_g.sc_session == 1u);                 /* job 8 opened the session */
    /* F5 queues once (pending), a second F5 before the job is ignored, B6 ends the session */
    a[0] = 0; a[1] = 0x28; a[2] = 9; a[3] = 0x3A;
    args(a, 4);
    post(0xF500);
    CHECK(disp_g.sc_pending == 1u);
    post(0xF500);
    CHECK(((disp_g.q_wr - disp_g.q_rd) & 0xFFu) == 1u);
    drain();
    CHECK(disp_g.sc_pending == 0u);
    post(0xB600);
    CHECK(disp_g.sc_session == 0u);
    drain();
    post(0xF500);                                   /* no session: ignored, no job, no refusal */
    CHECK(((disp_g.q_wr ^ disp_g.q_rd) & 0xFu) == 0u && !(fe6() & 0x200u));
    /* a job failure sets bit 8 (the slot's fail flag); the next queued post clears it */
    job_fail_code = 9u;
    a[0] = 0xBEEF; a[1] = 0x0800;
    args(a, 2);
    post(0xE001);
    drain();
    CHECK(fe6() & 0x100u);
    job_fail_code = 0u;
    post(0xE001);
    CHECK(!(fe6() & 0x100u));
    drain();
    /* DA: mode 7 with a 0x80 source = direct (no bit 14; the RTL decodes at the DA's destination and GOes), 0x81 = a
       job, 0x90 = refusal 7 */
    a[0] = 0x9000; a[1] = (uint16_t)(SRC80 >> 16); a[2] = (uint16_t)SRC80;
    args(a, 3);
    {
        uint32_t i0 = hb.nlog, s0 = hb.dec_starts;
        static const uint32_t want[] = { (BRD_FREG_FF2 << 16) | 0u, (BRD_FREG_FF2 << 16) | 0x8000u,
            (BRD_FREG_FE8 << 16) | 1u, (BRD_FREG_FF6 << 16) | 1u,
            (BRD_FREG_FF4 << 16) | 0x0210u, (BRD_FREG_FF6 << 16) | 0x0000u, (HB_LOG_DECB << 24) | 0x9000u,
            (BRD_FREG_FF2 << 16) | 0x8000u, (BRD_FREG_FEA << 16) | 0u };
        post(0xDA07);
        CHECK(log_has(i0, want, sizeof want / sizeof want[0]));   /* the chip's order (0x0801C2FC, 0x0801D1FE) */
        CHECK(!(fe6() & 0x4000u) && n_direct == 1u && hb.window_en);
        CHECK(hb.dec_starts == s0 + 1u && hb.sptr == 0x9000u && hb.dec_words == 4u && hb.remaining == 4u);
        CHECK(wsb(0x9000u) == 0xAAu && wsb(0x9007u) == 0xAAu);
        CHECK((hb_68k_read(BRD_FREG_FE4) & 4u) == 0u);   /* busy fell with the RTL's GO, and the post is finished */
        CHECK(hb.freg[BRD_FREG_FEA >> 1] == 0u);
    }
    a[2] = (uint16_t)SRC81;
    args(a, 3);
    post(0xDA07);
    CHECK(fe6() & 0x4000u);
    a[2] = (uint16_t)SRC90;
    args(a, 3);
    drain();
    post(0xDA07);
    CHECK(fe6() & 0x200u);
    post(0xDA06);                                   /* mode 6 with a non-0x80 source: refusal 7 */
    CHECK(fe6() & 0x200u);
    /* the 9494 head and the A mailbox */
    hb_68k_write(BRD_FREG_FEC, 0x9494u);
    (void)brd_now();
    CHECK(hb.freg[BRD_FREG_FEC >> 1] == 0u && (fe6() & 0x8000u) && !(fe6() & 0x2400u));
    hb_68k_write(BRD_FREG_FEC, 0x9C80u);            /* A index 0x1C: the A default refusal sets bit 10 */
    (void)brd_now();
    CHECK(fe6() & 0x400u);
    hb_68k_write(BRD_FREG_FEC, 0x9400u);            /* no request bit (low byte bit 7): finished, nothing else */
    (void)brd_now();
    CHECK(hb.freg[BRD_FREG_FEC >> 1] == 0u);
    /* B: no request bit: finished, not dispatched (bits 9 / 8 untouched) */
    post(0x0042);
    CHECK(hb.freg[BRD_FREG_FEA >> 1] == 0u);
    /* 82: $1FF2 := low byte bit 0 */
    post(0x8201);
    CHECK(hb.shadow[BRD_FREG_FF2 >> 1] == 1u);
    /* default refusals, both mailboxes */
    post(0xB700);
    CHECK(fe6() & 0x200u);
    /* AF: the flush pushes the load list last to first, the output base, START; the RTL decodes the list in load order
       contiguous from the base and GOes; the post finishes at once (0x080190B8: the flush, the compose, the finish) */
    post(0xAE00);
    load_list[0] = SRC80;
    load_list[1] = SRC80B;
    load_list[2] = SRC80 | 1u;                      /* (an odd table offset: the chip rounds it down) */
    load_n = 3u;
    {
        uint32_t i0 = hb.nlog, s0 = hb.dec_starts;
        static const uint32_t want[] = { (BRD_FREG_FF6 << 16) | 1u,
            (BRD_FREG_FF4 << 16) | 0x0210u, (BRD_FREG_FF6 << 16) | 0x0000u,      /* list[2] first */
            (BRD_FREG_FF4 << 16) | 0x0210u, (BRD_FREG_FF6 << 16) | 0x0300u,      /* list[1] */
            (BRD_FREG_FF4 << 16) | 0x0210u, (BRD_FREG_FF6 << 16) | 0x0000u,      /* list[0] last */
            (HB_LOG_DECB << 24) | 0x1E0000u, (BRD_FREG_FF2 << 16) | 0x8000u, (BRD_FREG_FEA << 16) | 0u };
        post(0xAF01);
        CHECK(log_has(i0, want, sizeof want / sizeof want[0]));
        CHECK(hb.freg[BRD_FREG_FEA >> 1] == 0u && (fe6() & 0x8000u));            /* finished at once */
        CHECK(hb.dec_starts == s0 + 1u && hb.sptr == 0x1E0000u && hb.dec_words == 14u && hb.stream_valid);   /* 8 + 12 + 8 B */
        CHECK(wsb(0x1E0000u) == 0xAAu && wsb(0x1E0007u) == 0xAAu);               /* list[0] = SRC80 first */
        CHECK(wsb(0x1E0008u) == 0x11u && wsb(0x1E000Au) == 0x33u && wsb(0x1E000Bu) == 0u && wsb(0x1E000Fu) == 0u);
        CHECK(wsb(0x1E0010u) == 0u && wsb(0x1E0013u) == 0u);                     /* the copy at d 2 of the zeros */
        CHECK(wsb(0x1E0014u) == 0xAAu && wsb(0x1E001Bu) == 0xAAu);               /* list[2] = SRC80 */
        CHECK(!(hb.dec_flags & (HB_DEC_OVF | HB_DEC_BADTYPE | HB_DEC_D0 | HB_DEC_PRE)));
    }
    /* an AF with an empty list: the empty START has no decoder effect (no SPTR, no GO); B1 the same flush */
    load_n = 0u;
    hb.sptr = 0x9000u;
    post(0xAE00);                                   /* a frame open (D38: an AF without one does not flush) */
    {
        uint32_t s0 = hb.dec_starts;
        post(0xAF01);
        CHECK(hb.dec_starts == s0 && hb.sptr == 0x9000u && !hb.stream_valid && hb.freg[BRD_FREG_FEA >> 1] == 0u);
        load_list[0] = SRC80;
        load_n = 1u;
        post(0xB100);
        CHECK(hb.dec_starts == s0 + 1u && hb.sptr == 0x1E0000u && hb.dec_words == 4u);
        load_n = 0u;
    }
    /* D38 (since the sprite-values update): an AF that no AE opened only finishes: no flush (no queue, START or
       DEC_BASE write), no frame end (no body); with an AE first, the frame end gets the mode (lo & 3) and the parity
       H+$403, which counts every AE, accepted B0 (F0 too: the
       same table entry) and the first C6's sprite init (above) */
    {
        uint32_t i0, b0 = n_body, s0 = hb.dec_starts;
        uint8_t p0 = disp_g.af_parity;
        static const uint32_t fin[] = { (BRD_FREG_FEA << 16) | 0u };
        load_list[0] = SRC80;
        load_n = 1u;
        CHECK(!disp_g.frame_open);                  /* closed by the AF above */
        i0 = hb.nlog;
#if !PPM_RELEASE
        uint32_t r0 = n_replied;
#endif
        post(0xAF02);
        CHECK(log_has(i0, fin, 1u) && n_body == b0 && hb.dec_starts == s0 && (fe6() & 0x8000u) && !(fe6() & 0x200u));
        post(0xAE00);
        CHECK(disp_g.af_parity == (uint8_t)(p0 + 1u) && disp_g.frame_open && n_body == b0 + 1u);
        post(0xAF03);
        CHECK(n_body == b0 + 2u && af_mode == 3u && af_par == (uint8_t)(p0 + 1u) && !disp_g.frame_open);
        CHECK(hb.dec_starts == s0 + 1u);            /* the list kept by the ignored AF is flushed now */
#if !PPM_RELEASE
        CHECK(n_replied == r0 + 1u && replied_early == 0u);   /* TEST: the bookkeeping after the reply, only for a
                                                                 frame end (since 2026-10-18) */
#endif
        post(0xB000);
        CHECK(disp_g.af_parity == (uint8_t)(p0 + 2u) && n_body == b0 + 3u);
        post(0xF000);
        CHECK(disp_g.af_parity == (uint8_t)(p0 + 3u) && n_body == b0 + 4u);
        post(0xAE00);
        post(0xAF02);
        CHECK(af_mode == 2u && af_par == (uint8_t)(p0 + 4u));
        load_n = 0u;
    }
    /* F2: the block twice, the output base, START; the RTL decodes two copies; finished at once */
    a[0] = 3;
    args(a, 1);
    {
        uint32_t s0 = hb.dec_starts;
        post(0xF200);
        CHECK(hb.freg[BRD_FREG_FEA >> 1] == 0u && hb.dec_starts == s0 + 1u && hb.dec_words == 12u);
        CHECK(!(hb_68k_read(BRD_FREG_FE4) & 4u) && hb.sptr == 0x1E0000u);
        CHECK(wsb(0x1E0000u) == 0x11u && wsb(0x1E000Cu) == 0x11u);               /* two copies of SRC80B */
    }
    printf("scenarios done\n");
}

/* ================================================================================================================
 * Part 2: the fuzz
 * ================================================================================================================ */
static uint32_t rng;
static uint32_t rnd(void) { rng = rng * 1103515245u + 12345u; return rng >> 8; }

typedef struct { uint16_t word; uint16_t a[4]; uint8_t job; uint8_t wait14; } fz_post_t;
static const fz_post_t menu[] = {
    { 0xAE00, {0}, 0, 0 }, { 0xAD05, {0}, 0, 0 }, { 0xAF01, {0}, 0, 0 }, { 0xB100, {0}, 0, 0 },
    { 0xD130, { 0x0180, 0x0080, 0x0080, 0 }, 0, 0 }, { 0x9600, {0}, 0, 0 }, { 0xC9FF, { 0x0080, 0 }, 0, 0 },
    { 0xDB06, { 0, 0x9000, 0x0080 }, 0, 0 }, { 0xDA02, { 0x9000, SRC81 >> 16, SRC81 & 0xFFFF }, 1, 1 },
    { 0xDA07, { 0x9000, SRC80 >> 16, SRC80 & 0xFFFF }, 0, 0 }, { 0xDA07, { 0x9000, SRC81 >> 16, SRC81 & 0xFFFF }, 1, 1 },
    { 0xDF01, { 0x0800, 0x0080 }, 1, 1 }, { 0xE001, { 0xBEEF, 0x0800 }, 1, 1 }, { 0x8C81, {0}, 1, 0 },
    { 0xDF02, { 0x0800, 0x0080 }, 1, 0 }, { 0xEC00, { 0, 0x34 }, 0, 0 }, { 0xB700, {0}, 0, 0 },
    { 0xD001, { 1 }, 0, 0 }, { 0x8201, {0}, 0, 0 }, { 0xF200, { 3 }, 0, 0 },
    { 0xDF03, { 0x0800, 0x0080 }, 1, 0 },          /* last: the burst post */
};
#define N_MENU                  (sizeof menu / sizeof menu[0])

static struct {
    int busy;                   /* a $1FEA post is outstanding (bit 15 set) */
    int stage;                  /* 0 idle, 1 posted (waiting for the finish), 2 waiting for bit 14 */
    const fz_post_t *p;
    uint32_t posts_b, posts_a, fin_b, fin_a;        /* 68000 posts, MCU finishes (from the log) */
    uint32_t log_seen;
    int tick_due;
    uint32_t burst;                                 /* no-wait job posts back to back (DF02): the queue fills, refusal 5 */
    uint32_t jobs_done_once;
    int in_check;
    uint32_t done[N_MENU], refused[N_MENU];         /* per menu entry: finished, of which refused */
} fz;

static void scan_log(void)
{
    uint32_t i;
    for (i = fz.log_seen; i < hb.nlog; i++) {
        uint32_t e = hb.log[i];
        if (e >> 30)
            continue;
        if ((e >> 16) == BRD_FREG_FEA && (e & 0xFFFFu) == 0u)
            fz.fin_b++;
        if ((e >> 16) == BRD_FREG_FEC && (e & 0xFFFFu) == 0u)
            fz.fin_a++;
        /* FZ3: a job step's bit-14 clear must follow its job's GO (the GO is logged before it) */
        if ((e >> 16) == BRD_FREG_FE6 && go_seen && !(e & 0x4000u)) {
            CHECK(go_at <= i);
            go_seen = 0u;
        }
    }
    fz.log_seen = hb.nlog;
}

static void on_point(void)
{
    uint16_t s6;
    if (fz.in_check)
        return;
    fz.in_check = 1;
    scan_log();
    CHECK(fz.fin_b <= fz.posts_b && fz.fin_a <= fz.posts_a);                       /* FZ1 / FZ6: never more */
    if (hb.mstatus_mie && hb.level != BRD_LINE_MEI) {
        CHECK(hb.freg[BRD_FREG_FE6 >> 1] == st_shadow(ST_FE6));                     /* FZ7 */
        CHECK(hb.freg[BRD_FREG_FE4 >> 1] == st_shadow(ST_FE4));
        if (fz.jobs_done_once) {                                                    /* FZ4 */
            uint32_t pending = ((disp_g.q_wr ^ disp_g.q_rd) & 0xFu) != 0u;
            CHECK(((hb.freg[BRD_FREG_FE6 >> 1] >> 14) & 1u) == pending);
        }
    }
    /* the 68000 spins on $1FEA bit 15 after a post (every point: the game's wait loop); other actions at random points */
    s6 = hb_68k_read(BRD_FREG_FE6);
    CHECK(((disp_g.q_wr - disp_g.q_rd) & 0xFFu) <= 15u);                           /* 15 usable slots */
    if (fz.stage == 1 || fz.burst || rnd() % 7u == 0u) {
        if (fz.stage == 1 && !(hb_68k_read(BRD_FREG_FEA) & 0x8000u)) {             /* its post is finished */
            CHECK(fz.fin_b == fz.posts_b);                                          /* FZ1 */
            /* FZ2: what the chip stores before its finish is visible with it (bit 15 follows the finish, as on
               the chip: the 68000 may see $1FEA = 0 a few cycles before $1FE6 bit 15; the game never reads 15) */
            if (fz.p->job && !(s6 & 0x200u))
                CHECK(s6 & 0x4000u);                                                /* FZ2: queued before the finish */
            fz.done[fz.p - menu]++;
            if (s6 & 0x200u)
                fz.refused[fz.p - menu]++;
            fz.stage = fz.p->wait14 ? 2 : 0;
            if (fz.burst)
                fz.burst--;
        } else if (fz.stage == 2 && !(s6 & 0x4000u)) {
            fz.stage = 0;
        } else if (fz.stage == 1) {
            ;                                                                       /* still spinning */
        } else if (fz.stage == 0 && (fz.burst || (rnd() & 3u))) {
            const fz_post_t *p = fz.burst ? &menu[N_MENU - 1u] : &menu[rnd() % N_MENU];
            unsigned i;
            for (i = 0; i < 4u; i++)
                hb.ram[0x1E10u / 2u + i] = p->a[i];
            fz.p = p;
            fz.stage = 1;
            fz.posts_b++;
            hb_68k_write(BRD_FREG_FEA, p->word);
        } else if (fz.tick_due && hb.freg[BRD_FREG_FEC >> 1] == 0u) {
            fz.tick_due = 0;
            fz.posts_a++;
            hb_68k_write(BRD_FREG_FEC, 0x9494u);
        }
    }
    fz.in_check = 0;
}

static void fuzz(uint32_t seed, uint32_t loops)
{
    static const uint16_t c6a[16] = { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16 };
    uint32_t k, jf0;
    boot();
    jf0 = disp_g.jobs_failed;
    args(c6a, 16);
    post(0xC600);
    drain();
    memset(&fz, 0, sizeof fz);
    fz.log_seen = hb.nlog;
    fz.jobs_done_once = 1u;
    go_seen = 0u;
    rng = seed;
    hb.on_point = on_point;
    for (k = 0; k < loops; k++) {
        load_n = rnd() % 16u;                       /* the next flush's list: 0-15 blocks of the ROM's streams */
        {
            uint32_t i;
            for (i = 0; i < load_n; i++)
                load_list[i] = (rnd() & 1u) ? SRC80B : SRC80;
        }
        job_cost = rnd() % 64u;
        if (rnd() % 400u == 0u)
            fz.burst = 24u;
        if (fz.burst)
            job_cost = 64u + rnd() % 64u;           /* slow jobs under a burst */
        job_fail_code = (rnd() % 6u == 0u) ? 9u : 0u;  /* the failure bit 8 is the thread's own status write */
        if (rnd() % 50u == 0u)
            fz.tick_due = 1;
        if (!sched_l2c_once())
            burn(1u + rnd() % 8u);                  /* the idle thread: points where the 68000 acts */
        if (hb.nlog > 3500u) {                      /* the fake board keeps 4,096 log entries: restart it */
            scan_log();
            hb.nlog = 0u;
            fz.log_seen = 0u;
            go_seen = 0u;
        }
    }
    /* let everything finish */
    for (k = 0; k < 5000u && (fz.stage == 1 || ((disp_g.q_wr ^ disp_g.q_rd) & 0xFu)); k++) {
        if (!sched_l2c_once())
            burn(4u);
    }
    hb.on_point = 0;
    scan_log();
    CHECK(fz.fin_b == fz.posts_b && fz.fin_a == fz.posts_a);                       /* FZ1 / FZ6: one each */
    CHECK(!(hb.freg[BRD_FREG_FE6 >> 1] & 0x4000u));                                /* FZ4: not stuck */
    printf("fuzz seed %u: %u B posts, %u A posts, %u jobs (%u failed), %u DA direct, %u decoder starts; refusals: "
           "queue full %u, not ready %u, arguments %u, default %u\n", (unsigned)seed, (unsigned)fz.posts_b,
           (unsigned)fz.posts_a, (unsigned)n_job, (unsigned)(disp_g.jobs_failed - jf0), (unsigned)n_direct,
           (unsigned)hb.dec_starts, (unsigned)disp_g.trace_cnt[5],
           (unsigned)disp_g.trace_cnt[6], (unsigned)disp_g.trace_cnt[7], (unsigned)disp_g.trace_cnt[2]);
    CHECK(disp_g.trace_cnt[5] != 0u);               /* the bursts reached a full queue */
    CHECK(hb.dec_starts != 0u && n_direct != 0u);   /* the decoder ran (AF / B1 / F2 / DA direct) */
    CHECK(!(hb.dec_flags & (HB_DEC_OVF | HB_DEC_BADTYPE | HB_DEC_D0 | HB_DEC_PRE)));
    for (k = 0; k < N_MENU; k++)                    /* every entry reaches its accept path (B700 is the default) */
        if (menu[k].word != 0xB700u && fz.done[k]) {
            CHECK(fz.refused[k] < fz.done[k]);
            if (fz.refused[k] * 2u > fz.done[k])
                printf("  %04X: %u of %u refused\n", menu[k].word, (unsigned)fz.refused[k], (unsigned)fz.done[k]);
        }
    job_fail_code = 0u;
}

int main(void)
{
    uint32_t s;
    scenarios();
    for (s = 1; s <= 8u; s++)
        fuzz(s * 7919u, 20000u);
    printf("disp_tests: %d checks, %d failed\n", checks, fails);
    return fails ? 1 : 0;
}
