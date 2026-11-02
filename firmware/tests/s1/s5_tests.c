/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/s1/s5_tests.c - host unit test of the stage-5 firmware path (FW_S5, the builds with our own song engine): the
 * ordered engine queue and the split between the scheduler's levels L1 and L2 (core/sched/sched.h), with
 * core/song/song_oeq.c, core/sched FW_S5, core/dispatch FW_S5 and the real song engine, on the x86 fake
 * board (board/host/s1_board.c with its MCU interface v1.3 ARR / SEQLAT / STAMP_A / DONE). Built and run by
 * tools/fwbuild.py s1 (fwbuild.json s1.host test_defines: -DFW_S5=1 -DSONG_TEST_HOOKS=1); exit 1 on a failed check.
 *
 * Deterministic cases the 68000 protocol lets through and the RV32 test rig (tests/equiv/fuzz_sched_s5.py) meets only
 * by chance (SCHED_BUG / SONG_BUG n are the planted bugs each case must catch):
 *   1 a 9494 (A) and a C9 (B) pending in one L1 entry, in both arrival orders: L1 serves the older first (arrival
 *     order, SEQLAT: B Jam's decision of 2026-10-21, number 3(a), MCU interface v1.3 section 3.10.5), so the items run
 *     in arrival order and DONE moves one arrival at a time (SCHED_BUG 13, B always first, fails the A-first half);
 *   2 a 9494 (A) and a refused D1 (B, the newer) in one L1 entry: the refusal writes no DONE in L1 (the 9494 waits),
 *     and DONE reaches the refused arrival after the 9494's item (SONG_BUG 9, DONE := the item's own number, leaves
 *     it behind);
 *   3 a full queue (SONG_Q_N): the next post is held back, not finished, then taken and finished at the next item
 *     end
 *     (SONG_BUG 11 drops it);
 *   4 8C: the job runs after the 8C body, its module-start item runs before the job step rewrites $1FE6 bit 14
 *     (SONG_BUG 12: the job does not wait for it);
 *   5 the urgent finish: a tick that L2b cannot run (MSI masked) is run by L2a CLK_URGENT5 after STAMP_A, not before
 *     (SCHED_BUG 12: it does nothing);
 *   6 the KB case of a scheduler audit: a tick on A and one on B pending at once: both finished in L1 (no finish waits
 *     for a tick end any more), both items in arrival order, DONE = ARR at the end;
 *   7 the 16-bit arrival wrap: A at 0xFFFF and B at 0x0000 pending at once: A (the older across the wrap) first;
 *   8 L1 raises MSI for its items (SCHED_BUG 11 does not), a post with no engine part gets its DONE at its L1's end;
 *   9 (added by a repair) counter 11's fold and DIAG's clear (board_trace_fold): with two instants queued the head may
 *     be serviced (time out) at any board call, and the count it makes is folded, never cleared away, whichever call it
 *     lands on; the clear waits while STATUS is not quiet (BUSY, QDEPTH 2), is made once it is, is forced at
 *     INCOMPLETE 0xF0, never outside an item (SONG_BUG 19: no STATUS test; 20: the last DIAG read before STATUS;
 *     21: a put-off clear forgets the folded counts);
 *  10 C6 on a hand-made flash: the C600 post's job runs the chip's audio set-up (core/song/song_c6.c): the
 *     state, both dac_buf rings cleared (SONG_BUG 23), one CONFIG write (DT NTSC, SEQ = C6's arrival: SONG_BUG 27),
 *     G+0 / SFX+0 / S+0, the wave programs and PSG presets decoded from 0x80 streams and zero-padded (SONG_BUG 28),
 *     the BGM table with an odd entry rounded to even (SONG_BUG 26), the module store holding the 0x81 module (its
 *     magic last), both engine parts as items with the pass held; a second C6 is ignored;
 *  11 the 8C job holds the chip's busy time (CLK_JOB8C + CLK_JOB8C_KB a thousand bytes of the module's
 *     length) before its module-start item (SONG_BUG 22), and no main-loop pass runs while the job runs (SONG_BUG
 *     24), one runs after it; a track the store lacks gives the chip's trace 0x11 and no module start;
 *  12 the two decoders on hand-made streams: every 0x80 code, and the 0x81 forms: a start run, a near copy,
 *     a mid copy, a short copy after a copy, the tail literals and the end (SONG_BUG 25: the mid copy's distance one short);
 *  13 the synth's fields written at synth_end: a D1 starts SFX 1 on channel 0 and the SFX window holds
 *     the channel record as MCU interface v1.3 section 3.10.4 converts it (PTR / BASE as CRAM SFXBANK bytes, FORMAT,
 *     RATE, ID, GAINs, LOOP, FILT, Y, DELAY), the globals (FLAGS, SMASTER, ...) as 3.10.1 has them, and a voice's BASE
 *     as its CRAM BANK byte (SONG_BUG 30: the SFX windows not written; 31: BASE with the SFX bank's offset);
 *  14 the logic's fields read back at synth_begin once BLKCNT has moved, and only then (SONG_BUG 29: never);
 *  15 the main-loop pass inside an item: the Boom Box feed and $1FE6 bit 3 after a post (SONG_BUG 32: not run);
 *  16 the pass after a block: CAUSE.BLK with CTRL.BLKIE runs it in its own bracket on the read-back ENV_LEVEL;
 *     a second block-done event with BLKCNT unmoved skips it (SONG_BUG 33: no pass after a block);
 *  17 a queued or running job holds the pass (the chip's thread runs the job): an 8C's body item and its
 *     module-start item run none, the job's tail runs exactly one (SONG_BUG 34: no tail pass; 35: passes while
 *     the job is queued, so the feed moves inside the 8C's job, as the chip's never does);
 *  18 a post with no item (a refused D1) still gets the pass: $1B00 (81 bit 1) shows the refusal's trace count
 *     (SONG_BUG 36: no pass after it);
 *  19 (a design decision) a block during the bracketed pass's ENV_LEVEL reads: the set is read again, the pass sees a
 *     whole block (SONG_BUG 37: no re-check, the set straddles the block);
 *  20 (since test build 5, a firmware build B Jam tested on his hardware: the counts of check A1, core/sched/s5_glue.c
 *     s5_test) with a block running at the DONE store (the
 *     board counting DIAG.WBUSY there): L1's DONE after a post with no item counts as a free store and its WBUSY in
 *     done_wbusy (SONG_BUG 38: not), an item's DONE (held off) is not excused, a module start's own stores that
 *     meet a block go to job_wbusy (it moves no DONE: no newer arrival; the diagnostic that showed WBUSY >
 *     done_wbusy); A1 (WBUSY <= done_wbusy + job_wbusy, which excuses the free DONE stores and the module-start
 *     item's own stores) holds or fails where it should; and (added by a repair after a
 *     review) an 82 posted while a module start runs gets no DONE inside the module start's window
 *     (song_l1_end writes none while an item is queued or running), so job_wbusy is the module start's own stores
 *     only and the 82's answer is the free DONE store after the item; and (since a later repair)
 *     A1 excuses the module starts + C6 items and nothing else: one store planted at the begin of an item of each
 *     other kind meets a block: C6's two engine call items (SQ_CALL, case 10's flow) go to job_wbusy and jobs (+2)
 *     and A1 holds; a post's item (SQ_POST, CAFF) and a tick's (SQ_TICK, 9494) are not excused and A1 fails, on
 *     the debug save's WBUSY total (DIAG folds included) (SONG_BUG 39: every item excused).
 * The engine runs on a cleared state with the ready words set (no module plays: every tick takes the sequencer's
 * "not playing" path, the 8C's module fails its header check, so the job's item traces 0xD): this is the queue's test,
 * the engine is proven by the song engine's lockstep against the chip (outside this tree). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "board.h"
#include "sched.h"
#include "sched_hooks.h"
#include "stats.h"
#include "disp.h"
#include "song.h"
#include "chip_tables.h"                         /* chip_level_init: the level table, built at boot */

static int fails, checks;
/* no __FILE__: the executable must not carry the tree's path */
#define CHECK(c) do { checks++; if (!(c)) { fails++; printf("FAIL s5_tests.c:%d %s\n", __LINE__, #c); } } while (0)

/* ---- the item log (the queue's test hook) and the DONE log ---------------------------------------------------- */
static struct { uint32_t kind, seq, done, fe6, hold, now, pass_wr, feed0; } it[64];
static int nit;
static int pass_probe;                          /* case 11: run the main-loop pass at every item's start */
static int wb_run;                              /* case 20: a block runs at every DONE store (DIAG.WBUSY + 1) */
static int wb_job;                              /* and a module start's stores meet one (WBUSY + this at its begin) */
static uint32_t wb_kind = SQ_JOB;               /* 20e-20g: the item kind wb_job plants in */
static int wb_post;                             /* 20d: an 82 posted as the module start begins, a block at every
                                                   DONE store from then on */
static void on_begin(uint32_t kind, uint32_t seq)
{
    if (wb_job && kind == wb_kind)
        hb.sy_diag += (uint32_t)wb_job << 16;
    if (wb_post && kind == SQ_JOB) {
        wb_post = 0;
        wb_run = 1;
        hb_68k_write(BRD_FREG_FEA, 0x8200u);    /* L1 takes it at the module start's next board call */
    }
    if (nit < 64) {
        it[nit].kind = kind;
        it[nit].seq = seq;
        it[nit].done = hb.done;
        it[nit].fe6 = hb.freg[BRD_FREG_FE6 >> 1];
        it[nit].hold = song_pass_hold;
        it[nit].now = hb.now;
        it[nit].pass_wr = 0;
        if (pass_probe) {                       /* the pass's $1B00 copy: a marker word changes only if it ran */
            static const uint16_t dbg[16] = { 0xBEEF };
            hb.ram[0x1B00 / 2] = 0;
            song_main_pass(dbg, 0u);
            it[nit].pass_wr = hb.ram[0x1B00 / 2] == 0xBEEFu;
        }
        it[nit].feed0 = hb.ram[0x1B90 / 2];     /* the Boom Box feed's word 0 as the item starts */
        nit++;
    }
}
static uint32_t dlog[64];
static int ndl, done_back;
static void on_done(uint32_t n)
{
    if (wb_run)
        hb.sy_diag += 1u << 16;
    if (ndl && (uint16_t)(n - dlog[ndl - 1]) > 0x7FFFu)
        done_back++;
    if (ndl < 64)
        dlog[ndl++] = n;
}

/* the dispatcher's non-audio bodies and jobs (none posted here) */
void body_ad(uint8_t lo) { (void)lo; }
void body_ae(void) { }
void body_af(uint8_t mode, uint8_t parity) { (void)mode; (void)parity; }
void body_af_replied(void) { }
void body_b0(void) { }
void body_b1(void) { }
void body_ec(uint16_t slots) { (void)slots; }
uint32_t body_block_addr(uint16_t block) { (void)block; return 0; }
uint32_t body_load_list(const uint32_t **list) { static const uint32_t z = 0; *list = &z; return 0; }
void body_dec_scratch(void) { }
void body_db(uint16_t a0, uint16_t a1, uint16_t a2, uint8_t mode) { (void)a0; (void)a1; (void)a2; (void)mode; }
void body_da_direct(uint32_t src, uint16_t dst, uint8_t mode) { (void)src; (void)dst; (void)mode; }
void body_e7(void) { }
uint32_t job_unpack(const disp_job_t *j) { (void)j; return 0; }
uint32_t job_eep_read(const disp_job_t *j) { (void)j; return 0; }
uint32_t job_eep_write(const disp_job_t *j) { (void)j; return 0; }
void job_scale_save(void) { }
void job_scale_setup(void) { }
void job_rescale(const uint16_t args[4]) { (void)args; }
void job_restore(void) { }
uint32_t job_setup(const uint32_t longs[8], uint32_t mw_screen) { (void)longs; (void)mw_screen; return 0; }

/* the module store (F2 / F3's on the Pocket): a module that fails the module start's header check */
static uint8_t fake_mod[0x400];
static uint32_t mod_asks;
static int mod_none;                            /* case 11: the store holds no module for the track */
const uint8_t *board_module(uint32_t track) { (void)track; mod_asks++; return mod_none ? 0 : fake_mod; }
static uint8_t flash8[0x200];                   /* the 8C gate's flash view: the BGM table entry's header bytes */

/* case 9: the fold's state (core/dispatch/disp.c) and a model of the synth's head instant timing out at the k-th
   board call after the arm (only while two instants are queued: v1.3 3.10.5; it counts one incomplete DT half and
   leaves the queue) */
extern uint8_t  s5_diag_base[4];
extern uint32_t s5_diag_defer, s5_diag_forced;
extern uint32_t s5_diag_acc[4];
/* case 20e-20g: DIAG.WBUSY since the boot as the debug save totals it (board/pocket/dbgsave.c synth_block: the folded
   counts plus what the register counted since the last fold), so a tick item's DIAG clear (the packet flush's fold)
   would lose nothing */
static uint32_t wbusy_total(void)
{
    return s5_diag_acc[2] + (((hb.sy_diag >> 16) - s5_diag_base[2]) & 0xFFu);
}
static int w_k, w_calls, w_fired;
static void on_point_w(void)
{
    if (w_k && ++w_calls == w_k && BRD_SYNTH_QDEPTH(hb.sy_status) >= 2u) {
        hb.sy_diag += 1u;
        hb.sy_status = (hb.sy_status & ~0x1E0u) | (1u << 5);
        w_fired = 1;
    }
}

/* case 19: a block in the middle of a bracketed pass's 16 ENV_LEVEL reads (after the 8th): new levels, BLKCNT + 1 */
static int st_on, st_fired;
static uint32_t st_rd0;
static void blk_move(uint32_t n);
static void sw32_set(uint32_t off, uint32_t v);
static void on_point_straddle(void)
{
    if (st_on && hb.sy_rd_n - st_rd0 == 8u) {
        for (uint32_t v = 0; v < 16u; v++)
            sw32_set(BRD_SY_VOICE(v) + 0x1Cu, 0x0200u + v);
        blk_move(1u);
        st_on = 0;
        st_fired++;
    }
}

static void post_b(uint16_t w) { hb_68k_write(BRD_FREG_FEA, w); }
static void post_a(uint16_t w) { hb_68k_write(BRD_FREG_FEC, w); }
static void settle(void) { for (int i = 0; i < 64; i++) (void)brd_now(); }
static uint16_t fea(void) { return hb.freg[BRD_FREG_FEA >> 1]; }
static uint16_t fec(void) { return hb.freg[BRD_FREG_FEC >> 1]; }
static uint16_t fe6(void) { return hb.freg[BRD_FREG_FE6 >> 1]; }

static void boot(uint32_t arr0)
{
    hb_reset();
    hb.arr = arr0 & 0xFFFFu;
    hb.seqlat = (hb.arr << 16) | hb.arr;
    hb.done = hb.arr;
    hb.on_done = on_done;
    memset(&sched_stats, 0, sizeof sched_stats);
    memset(&S, 0, sizeof S);
    memset(&G, 0, sizeof G);
    memset(&SFX, 0, sizeof SFX);
    chip_level_init();                          /* the level table T, as the board's boot builds it */
    memset(bgm_table, 0, sizeof bgm_table);
    memset(&disp_g, 0, sizeof disp_g);
    disp_g.app_ready = 1u;
    disp_g.mixer = disp_g.seq_ready = disp_g.sfx_ready = 1u;
    G.ready = 1u;
    S.ready = 1u;
    SFX.ready = 1u;
    G.rate = 0x3C;                              /* NTSC */
    sfx_table[0].l0 = 8;                        /* SFX count + 1 */
    bgm_table[0] = 1;                           /* one module, at flash byte 0x100 */
    bgm_table[1] = 0x6C800100u;
    flash8[0x100] = 0x81;
    song_v.flash8 = flash8;
    song_v.flash8_bus = 0x6C800000u;
    song_v.ramdp = hb.ram;
    song_test_begin = on_begin;
    nit = 0;
    ndl = 0;
    done_back = 0;
    mod_asks = 0;
    st_init_words(0x8000u, 0u);
    st_store(ST_FE6);
    sched_init();                               /* song_oeq_init(ARR): DONE := ARR */
    ndl = 0;
    brd_cause_ack(BRD_CAUSE_ALL);
    brd_lines_on(BRD_LINES_ALL);
    brd_irq_enable();
}
static void args(uint16_t a0, uint16_t a1) { hb.ram[0x1E10 / 2] = a0; hb.ram[0x1E10 / 2 + 1] = a1; }

/* case 21 (from stage 3 of the 0.3.0 work): the warm vector page seen at each board point while CAUSE.V is pending */
static const uint16_t *warm_rom;
static int warm_seen, warm_whole;
static int warm_ok(void)
{
    uint32_t i;
    for (i = 0; i < 0x100u / 2u; i++) {
        uint16_t w = i == 2u ? 0x0001u : i == 3u ? 0x0100u : warm_rom[i];
        if (hb.ram[i] != w)
            return 0;
    }
    return 1;
}
static void warm_point(void)
{
    if (hb.cause & BRD_CAUSE_V) {
        warm_seen++;
        warm_whole = warm_ok();
    }
}

/* cases 10-12: a hand-made flash (byte view and word view) */
static uint8_t rom8[0x8000], rom16[0x8000];
static void rom_mirror(void)
{
    for (int i = 0; i < (int)sizeof rom8; i += 2) {
        rom16[i] = rom8[i + 1];
        rom16[i + 1] = rom8[i];
    }
}
static void rom_put(uint32_t a, const uint8_t *b, uint32_t n) { memcpy(rom8 + a, b, n); }
static void rom_w16(uint32_t a, uint16_t v) { rom8[a] = (uint8_t)(v >> 8); rom8[a + 1] = (uint8_t)v; }   /* 68000 word */
static void rom_l32(uint32_t a, uint32_t v) { rom_w16(a, (uint16_t)(v >> 16)); rom_w16(a + 2, (uint16_t)v); }
/* the 0x80 stream: 3 literals, 5 fills, 4 back from 3 (overlapping), 6 zeros, the end; then bytes a decoder that ran
   past the end would take */
static const uint8_t s80_wp[] = { 0x80, 0x03, 'A', 'B', 'C', 0x45, 0x11, 0x84, 0x03, 0xC6, 0x00, 0x01, 0x77, 0x00 };
static const uint8_t x80_wp[] = { 'A', 'B', 'C', 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0, 0, 0, 0, 0, 0 };
static const uint8_t s80_pe[] = { 0x80, 0x42, 0x22, 0x00 };
/* the 0x81 stream: a start run of 5 literals, a near copy of 3 from 3, a literal run of 4, a mid copy of 5 from 9 with
   one tail literal, a short copy of 2 from 2 after it, the end (a far-copy code with distance 0) */
static const uint8_t s81[] = { 0x81, 22, 'H', 'E', 'L', 'L', 'O', 0x48, 0x00, 0x01, 'A', 'B', 'C', 'D', 0x23, 0x21, 0x00, 'Z',
                               0x04, 0x00, 0x11, 0x00, 0x00 };
static const char x81[] = "HELLOLLOABCDLOLLOZOZ";
static void c6_flash(void)
{
    memset(rom8, 0, sizeof rom8);
    rom_put(0x1000, s80_wp, sizeof s80_wp);             /* C6 long 1: the wave programs */
    rom_put(0x2000, s80_pe, sizeof s80_pe);             /* long 3: the PSG presets */
    rom_w16(0x3000, 0);                                 /* long 0: the BGM table, count byte 2 (entries 1-2) */
    rom8[0x3003] = 2;                                   /* (the word view's byte 2 = ROM byte 3) */
    rom_l32(0x3004, 0x101);                             /* entry 1: odd, the chip rounds it to 0x100 */
    rom_l32(0x3008, 0);                                 /* entry 2: a null slot */
    rom_put(0x3100, s81, sizeof s81);                   /* entry 1's module stream */
    rom8[0x4000] = 0x77;                                /* long 2: the wave bank's stream */
    rom_w16(0x5000, 0);                                 /* long 4: the SFX table, one record */
    rom8[0x5007] = 1;
    rom_l32(0x5008, 0x100);
    rom_mirror();
    hb.flash8 = rom8;
    hb.flash16 = rom16;
}
static void c6_post(void)
{
    static const uint32_t L[7] = { 0x3000, 0x1000, 0x4000, 0x2000, 0x5000, 0, 0 };
    for (int i = 0; i < 7; i++) {
        hb.ram[0x1E10 / 2 + 2 * i] = (uint16_t)(L[i] >> 16);
        hb.ram[0x1E10 / 2 + 2 * i + 1] = (uint16_t)L[i];
    }
    post_b(0xC600u);
}
static int run_until_job_done(void)
{
    for (int i = 0; i < 4000; i++) {
        settle();
        if (!(fe6() & 0x4000u))
            return 1;
        for (int k = 0; k < 4000; k++)          /* the C6 hold waits ~80 VDP frames of the model's time */
            (void)brd_now();
    }
    return 0;
}
/* region 0x06 (the synth) as the host board holds it (little endian) */
static uint32_t sw32(uint32_t off)
{
    return (uint32_t)hb.sy_win[off] | (uint32_t)hb.sy_win[off + 1u] << 8 | (uint32_t)hb.sy_win[off + 2u] << 16 |
           (uint32_t)hb.sy_win[off + 3u] << 24;
}
static void sw32_set(uint32_t off, uint32_t v)
{
    hb.sy_win[off] = (uint8_t)v;
    hb.sy_win[off + 1u] = (uint8_t)(v >> 8);
    hb.sy_win[off + 2u] = (uint8_t)(v >> 16);
    hb.sy_win[off + 3u] = (uint8_t)(v >> 24);
}
static void blk_move(uint32_t n) { hb.sy_status = (hb.sy_status & ~0x0FFF0000u) | ((BRD_SYNTH_BLKCNT(hb.sy_status) + n) & 0xFFFu) << 16; }

int main(void)
{
    int i;

    /* 1a. 9494 (A, arrival 1) and C9 (B, arrival 2) pending in one L1 entry, L2 closed: the 9494 (the older) is
       queued first; DONE moves to 1 after its item, then to 2 */
    boot(0);
    brd_lines_off(BRD_LINE_MSI | BRD_LINE_MTI);
    args(0x0080, 0);
    post_a(0x9494u);
    post_b(0xC9FFu);
    settle();
    CHECK(song_q_depth() == 2u && fea() == 0u && fec() == 0u);   /* both finished at once, both queued */
    CHECK(hb.done == 0u && ndl == 0);
    brd_lines_on(BRD_LINE_MSI | BRD_LINE_MTI);
    settle();
    CHECK(nit == 2 && it[0].kind == SQ_TICK && it[0].seq == 1u && it[1].kind == SQ_POST && it[1].seq == 2u);
    CHECK(nit == 2 && it[0].done == 0u && it[1].done == 1u);     /* each item began with DONE just before it */
    CHECK(ndl == 2 && dlog[0] == 1u && dlog[1] == 2u);
    CHECK(hb.done == 2u && hb.arr == 2u && song_q_depth() == 0u && done_back == 0);
    CHECK(S.lvl_target != 0u && (fe6() & 0x2000u));   /* C9's body ran; the tick's flush set bit 13 again */

    /* 1b. the other order: C9 (B, arrival 1) and 9494 (A, arrival 2) pending in one L1 entry: C9 first */
    boot(0);
    brd_lines_off(BRD_LINE_MSI | BRD_LINE_MTI);
    args(0x0080, 0);
    post_b(0xC9FFu);
    post_a(0x9494u);
    settle();
    CHECK(song_q_depth() == 2u && fea() == 0u && fec() == 0u && hb.done == 0u && ndl == 0);
    brd_lines_on(BRD_LINE_MSI | BRD_LINE_MTI);
    settle();
    CHECK(nit == 2 && it[0].kind == SQ_POST && it[0].seq == 1u && it[1].kind == SQ_TICK && it[1].seq == 2u);
    CHECK(nit == 2 && it[0].done == 0u && it[1].done == 1u && ndl == 2 && dlog[0] == 1u && dlog[1] == 2u);
    CHECK(hb.done == 2u && hb.arr == 2u && song_q_depth() == 0u && done_back == 0);

    /* 2. a 9494 (A, 1) and a refused D1 (B, 2) in one L1 entry: the refusal writes no DONE in L1 (the 9494 waits); one
       DONE after the 9494's item covers both */
    boot(0);
    brd_lines_off(BRD_LINE_MSI | BRD_LINE_MTI);
    post_a(0x9494u);
    post_b(0xD100u);                            /* D1 with id 0: refusal 7 (0x0801AF4E) */
    settle();
    CHECK(song_q_depth() == 1u && hb.done == 0u && ndl == 0 && (fe6() & 0x0200u) && fea() == 0u);
    CHECK(disp_g.trace_cnt[7] == 1u);
    brd_lines_on(BRD_LINE_MSI | BRD_LINE_MTI);
    settle();
    CHECK(nit == 1 && it[0].kind == SQ_TICK && it[0].done == 0u && hb.done == 2u && ndl == 1);

    /* 3. the queue full: SONG_Q_N posts queued with L2 closed, the next held back (not finished), then taken at the
       first item end and finished; SONG_Q_N + 1 items in arrival order, DONE = ARR */
    boot(0);
    brd_lines_off(BRD_LINE_MSI | BRD_LINE_MTI);
    for (i = 0; i < (int)SONG_Q_N + 1; i++) {
        post_b(0x9600u);                        /* D6 00, no arguments */
        settle();
    }
    CHECK(song_q_depth() == SONG_Q_N && song_q_over == 1u && fea() == 0x9600u && hb.done == 0u);
    brd_lines_on(BRD_LINE_MSI | BRD_LINE_MTI);
    settle();
    CHECK(nit == (int)SONG_Q_N + 1 && fea() == 0u && song_q_depth() == 0u && hb.done == SONG_Q_N + 1u &&
          hb.arr == SONG_Q_N + 1u);
    for (i = 0; i < nit && i < (int)SONG_Q_N + 1; i++)
        CHECK(it[i].seq == (uint32_t)i + 1u && it[i].done == (uint32_t)i);
    CHECK(song_q_max == SONG_Q_N);
    song_q_over = 0u;
    song_q_max = 0u;

    /* 4. 8C81: the gate pushes the job (bits 14 / 8), the 8C body item runs, then the job (L2c), whose module-start
       item runs (bit 14 still set) before the job step clears bit 14 */
    boot(0);
    post_b(0x8C81u);
    settle();
    CHECK(mod_asks == 1u && nit == 2 && it[0].kind == SQ_POST && it[1].kind == SQ_JOB);
    CHECK(nit == 2 && (it[1].fe6 & 0x4000u));    /* the module start came before the job step's bit-14 store */
    CHECK(!(fe6() & 0x4000u) && disp_g.q_rd == disp_g.q_wr && S.loading == 0u && S.track == 1u);
    CHECK(disp_g.trace_cnt[0xD] == 1u && hb.done == 1u && song_q_depth() == 0u);   /* the fake module fails: 0xD */

    /* 5. the urgent finish: L2b cannot run (MSI masked), the 9494's item runs in L2a CLK_URGENT5 after STAMP_A */
    boot(0);
    brd_lines_off(BRD_LINE_MSI);
    post_a(0x9494u);
    settle();
    {
        uint32_t t0 = hb.stamp_a;
        CHECK(song_q_depth() == 1u && fec() == 0u && (wheel_armed() & (1u << WH_URGENT)));
        while ((int32_t)(hb.now - (t0 + CLK_URGENT5)) < -200)
            (void)brd_now();
        CHECK(song_q_depth() == 1u && hb.done == 0u);  /* not before its deadline */
        for (i = 0; i < 400; i++)
            (void)brd_now();
        CHECK(song_q_depth() == 0u && hb.done == 1u && sched_stats.ticks_urgent >= 1u && nit == 1);
        CHECK(!(wheel_armed() & (1u << WH_URGENT)));
    }
    brd_lines_on(BRD_LINE_MSI);

    /* 6. the KB case: a tick on A (1) and one on B (2) at once: both finished in L1, both run, A's (the older) first */
    boot(0);
    brd_lines_off(BRD_LINE_MSI | BRD_LINE_MTI);
    post_a(0x9494u);
    post_b(0x9400u);
    settle();
    CHECK(song_q_depth() == 2u && fea() == 0u && fec() == 0u);
    brd_lines_on(BRD_LINE_MSI | BRD_LINE_MTI);
    settle();
    CHECK(nit == 2 && it[0].kind == SQ_TICK && it[0].seq == 1u && it[1].kind == SQ_TICK && it[1].seq == 2u);
    CHECK(nit == 2 && it[0].done == 0u && it[1].done == 1u && hb.done == 2u && G.frame == 2u);

    /* 7. the arrival wrap: ARR 0xFFFE, then 9494 (0xFFFF) and C9 (0x0000) in one L1 entry: the 9494 is the older */
    boot(0xFFFEu);
    brd_lines_off(BRD_LINE_MSI | BRD_LINE_MTI);
    args(0x0080, 0);
    post_a(0x9494u);
    post_b(0xC9FFu);
    settle();
    brd_lines_on(BRD_LINE_MSI | BRD_LINE_MTI);
    settle();
    CHECK(nit == 2 && it[0].seq == 0xFFFFu && it[0].done == 0xFFFEu && it[1].seq == 0u && it[1].done == 0xFFFFu);
    CHECK(hb.done == 0u && hb.arr == 0u && done_back == 0);

    /* 8. L1 raises MSI for its items (they run at once); a post with no engine part gets its DONE at its L1's end */
    boot(0);
    args(0x0080, 0);
    post_b(0xCAFFu);
    settle();
    CHECK(song_q_depth() == 0u && nit == 1 && hb.done == 1u);
    post_b(0x8200u);                            /* 82: no engine part */
    settle();
    CHECK(hb.done == 2u && nit == 1 && ndl == 2);

    /* 9. counter 11's fold and DIAG's clear (added by a repair): INCOMPLETE 0x80 (high), two instants queued; the head
       times out at board call k of the first fold (counting one more half); a second, quiet fold clears. Every k: the
       counter gets 0x80 + the half, once; DIAG and the base end at 0 */
    {
        int k, fired = 0;
        uint16_t c0;
        uint32_t d0, f0, c;
        for (k = 1; k <= 8; k++) {
            boot(0);
            memset(s5_diag_base, 0, sizeof s5_diag_base);
            hb.sy_diag = 0x80u;
            hb.sy_status = 2u << 5;
            c0 = disp_g.trace_cnt[11];
            d0 = s5_diag_defer;
            c = hb.diag_clears;
            w_k = k;
            w_calls = 0;
            w_fired = 0;
            hb.on_point = on_point_w;
            board_trace_fold(1u);
            hb.on_point = 0;
            w_k = 0;
            if (!w_fired)
                CHECK(s5_diag_defer == d0 + 1u && hb.diag_clears == c);   /* not quiet: put off */
            hb.sy_status &= ~0x1E0u;
            board_trace_fold(1u);
            CHECK(disp_g.trace_cnt[11] == (uint16_t)(c0 + 0x80u + (w_fired ? 1u : 0u)));
            CHECK(hb.sy_diag == 0u && s5_diag_base[0] == 0u && hb.diag_clears == c + 1u);
            fired += w_fired;
        }
        CHECK(fired >= 2);                          /* the half landed on calls of the first fold */
        /* BUSY (a block running or a head serviceable): put off */
        boot(0);
        memset(s5_diag_base, 0, sizeof s5_diag_base);
        hb.sy_diag = 0x80u;
        hb.sy_status = BRD_SYNTH_BUSY;
        c = hb.diag_clears;
        d0 = s5_diag_defer;
        board_trace_fold(1u);
        CHECK(hb.diag_clears == c && s5_diag_defer == d0 + 1u && hb.sy_diag == 0x80u);
        /* outside an item: never cleared */
        hb.sy_status = 0u;
        board_trace_fold(0u);
        CHECK(hb.diag_clears == c && hb.sy_diag == 0x80u);
        /* INCOMPLETE at 0xF0 with two instants queued: the clear is forced (saturation would lose counts) */
        boot(0);
        memset(s5_diag_base, 0, sizeof s5_diag_base);
        hb.sy_diag = 0xF0u;
        hb.sy_status = 2u << 5;
        c0 = disp_g.trace_cnt[11];
        c = hb.diag_clears;
        f0 = s5_diag_forced;
        board_trace_fold(1u);
        CHECK(hb.diag_clears == c + 1u && s5_diag_forced == f0 + 1u && hb.sy_diag == 0u);
        CHECK(disp_g.trace_cnt[11] == (uint16_t)(c0 + 0xF0u) && s5_diag_base[0] == 0u);
    }

    /* 10. C6: the chip's audio set-up on a hand-made flash, from a cleared engine (arrival 6 = the C600) */
    {
        volatile uint16_t *db;
        const uint8_t *m;
        uint32_t i, z = 0, ok80 = 1, items = 0, held = 0;
        c6_flash();
        boot(5);
        G.ready = 0u;
        S.ready = 0u;
        SFX.ready = 0u;
        disp_g.mixer = disp_g.seq_ready = disp_g.sfx_ready = 0u;
        memset(bgm_table, 0, sizeof bgm_table);
        db = brd_dacbuf();
        for (i = 0; i < 2u * BRD_DACBUF_N; i++)
            db[i] = 0x5A5Au;
        hb.cfg_n = 0;
        c6_post();
        CHECK(run_until_job_done());
        for (i = 0; i < 2u * BRD_DACBUF_N; i++)
            z += db[i] != 0;
        CHECK(z == 0u);                                 /* both rings cleared (a design decision) */
        CHECK(hb.cfg_n == 1u && hb.cfg_log[0] == (1u | (6u << 16)));  /* DT NTSC, dated at C6's arrival */
        CHECK(G.ready == 1u && SFX.ready == 1u && S.ready == 1u && G.rate == 0x3C && G.last_cfg == 2u);
        CHECK(G.q_budget == 0xFFFu && G.r38 == 1u && G.r3a == 0xFFu && G.ymdac == 0u && G.samples == 960u);
        CHECK(disp_g.mixer == 1u && disp_g.seq_ready == 1u && disp_g.sfx_ready == 1u);
        for (i = 0; i < sizeof x80_wp; i++)
            ok80 &= song_v.wprog[i] == x80_wp[i];
        for (; i < 0x1000u; i++)
            ok80 &= song_v.wprog[i] == 0;
        CHECK(ok80);                                    /* the 0x80 stream, then zeros to 0x1000 */
        CHECK(song_v.psgenv[0] == 0x22u && song_v.psgenv[1] == 0x22u && song_v.psgenv[2] == 0u && song_v.psgenv[0x7FF] == 0u);
        CHECK(bgm_table[0] == 3u && bgm_table[1] == 0x6C803100u && bgm_table[2] == 0u && bgm_table[63] == 0u);
        m = board_module(1);                            /* (s5_tests' own: the fake module) */
        CHECK(m == fake_mod && board_module_len(1) == sizeof x81 - 1u && board_module_len(2) == 0u);
        {
            const volatile uint32_t *dir = (const volatile uint32_t *)(const volatile void *)(brd_workspace() + BRD_MODSTORE_OFF);
            CHECK(dir[0] == BRD_MODSTORE_MAGIC && dir[1] == 1u && dir[3] == BRD_MODSTORE_DIR);
            CHECK(memcmp((const void *)(brd_workspace() + BRD_MODSTORE_OFF + dir[3]), x81, sizeof x81 - 1u) == 0);
        }
        for (i = 0; i < (uint32_t)nit; i++) {
            items += it[i].kind == SQ_CALL;
            held += it[i].kind == SQ_CALL && it[i].hold;
        }
        CHECK(items == 2u && held == 2u && !song_pass_hold);   /* two engine parts, the pass held during the job */
        post_b(0xC600u);                                /* a second C6: ignored (G+0), no job, no state change */
        settle();
        CHECK(hb.cfg_n == 1u && S.ready == 1u && !(fe6() & 0x4000u) && disp_g.q_rd == disp_g.q_wr);
        hb.flash8 = 0;
        hb.flash16 = 0;
    }

    /* 11. the 8C job's busy time and the pass hold: the store says track 1 is 20,000 B */
    {
        uint32_t t_body = 0, t_mod = 0, i, want = CLK_JOB8C + 20u * CLK_JOB8C_KB;
        int ib = -1, im = -1;
        boot(0);
        board_store_begin();
        {
            uint32_t room;
            (void)board_store_slot(&room);
            board_store_put(1, 20000u);
        }
        board_store_end(1u);
        pass_probe = 1;
        post_b(0x8C81u);
        for (i = 0; i < 64; i++)
            settle();
        pass_probe = 0;
        for (i = 0; i < (uint32_t)nit; i++) {
            if (it[i].kind == SQ_POST && ib < 0)
                ib = (int)i;
            if (it[i].kind == SQ_JOB)
                im = (int)i;
        }
        CHECK(ib >= 0 && im > ib);
        if (ib >= 0 && im > ib) {
            t_body = it[ib].now;
            t_mod = it[im].now;
            CHECK((int32_t)(t_mod - t_body) >= (int32_t)want);    /* the chip's busy time held */
            CHECK((int32_t)(t_mod - t_body) < (int32_t)(want + 4000u));
            CHECK(it[im].hold == 1u && it[im].pass_wr == 0u);    /* no pass while the job runs */
            CHECK(it[ib].hold == 0u && it[ib].pass_wr == 1u);    /* before the job: the pass runs */
        }
        CHECK(!song_pass_hold && !(fe6() & 0x4000u) && disp_g.trace_cnt[0xD] == 1u);
        /* a track the store lacks: the chip's failed decode, trace 0x11, no module start */
        boot(0);
        board_store_begin();
        board_store_end(1u);
        {
            disp_g.last_trace = 0;
            mod_none = 1;
            post_b(0x8C81u);
            for (i = 0; i < 64; i++)
                settle();
            mod_none = 0;
            CHECK(disp_g.last_trace == 0x11u && S.loading == 1u && S.playing == 0u);
            for (i = 0; i < (uint32_t)nit; i++)
                CHECK(it[i].kind != SQ_JOB);
        }
    }

    /* 12. the decoders on hand-made streams */
    {
        static uint8_t out[64];
        memset(out, 0xEE, sizeof out);
        CHECK(song_unpack80(s80_wp + 1, out) == sizeof x80_wp && memcmp(out, x80_wp, sizeof x80_wp) == 0);
        memset(out, 0xEE, sizeof out);
        CHECK(song_unpack81(s81 + 1, out) == sizeof x81 - 1u && memcmp(out, x81, sizeof x81 - 1u) == 0);
        CHECK(out[sizeof x81 - 1u] == 0xEEu);
    }

    /* 13. the synth's fields: a D1 (SFX 1 on channel 0, mask 1, level 0xFF, pan 0x80, flags 0x9000:
       the loop byte and the 0x1000 low-pass) writes the channel record, and synth_end puts it in SFX[0] as v1.3
       3.10.4 converts it; the globals and a voice's BASE (written straight into the record here) too */
    boot(0);
    song_v.flash16_bus = 0x6C000000u;
    song_v.sfx_bus = 0x6C000000u + 0x25ECA4u;  /* the game's SFX table address */
    song_v.sdir_bus = 0xC0089800u;
    sfx_table[1].ptr = song_v.sfx_bus + 0x1230u;
    sfx_table[1].flags = 0x21u;                 /* 8-bit (1), rate 2 */
    sfx_table[1].l2 = 0u;
    sfx_table[1].l1 = 0x10u;
    sfx_table[1].l0 = 0x40u;
    S.v[10 + 3].wdata = song_v.sdir_bus + 0x4560u;
    hb.ram[0x1E10 / 2 + 2] = 0x0080u;
    hb.ram[0x1E10 / 2 + 3] = 0x9000u;
    args(0x0001u, 0x00FFu);
    post_b(0xD101u);
    settle();
    {
        const sfx_ch *r = &SFX.ch[0];
        uint32_t o = BRD_SY_SFX(0);
        CHECK(nit == 1 && r->id == 1u && hb.done == 1u);
        CHECK(sw32(o + 0x00u) == 0x200000u + 0x1230u && sw32(o + 0x04u) == 0x200000u + 0x1230u);
        CHECK(sw32(o + 0x08u) == r->pos && sw32(o + 0x0Cu) == r->len && r->len != 0u);
        CHECK(sw32(o + 0x10u) == ((r->rate_type & 0xFFu) | (r->rate_mul & 0xFFu) << 8 | 1u << 16));
        CHECK(sw32(o + 0x14u) == ((uint32_t)r->gain2 | (uint32_t)r->gain3 << 16) && r->gain2 != 0u);
        CHECK(sw32(o + 0x18u) == ((uint32_t)r->neg | (uint32_t)r->shift << 8 | (uint32_t)r->r2a << 16));
        CHECK(r->neg == 1u && r->shift != 0u && sw32(o + 0x1Cu) == r->pitch);
        CHECK(sw32(BRD_SY_FLAGS) == 0x5u);       /* SEQON, SFXON (S.ready, SFX.ready; nothing playing) */
        CHECK(sw32(BRD_SY_SMASTER) == ((uint32_t)SFX.gain2 | (uint32_t)SFX.gain3 << 16));
        CHECK(sw32(BRD_SY_VOICE(3) + 0x0Cu) == 0x100u + 0x4560u);
    }

    /* 14. the read-back: the logic moves voice 13's ENV_LEVEL and channel 0's POS in its windows; with BLKCNT
       unmoved the next item does not read them (the logic writes only while it mixes a block), once it has moved
       it does */
    {
        uint32_t r0 = s5_mirror_stats.reads, o = BRD_SY_VOICE(3) + 0x1Cu;
        sw32_set(o, (sw32(o) & 0xFFFF0000u) | 0x0345u);
        sw32_set(BRD_SY_SFX(0) + 0x08u, 0x777u);
        post_b(0x9600u);
        settle();
        CHECK(s5_mirror_stats.reads == r0 && S.v[13].env_level != 0x0345 && SFX.ch[0].pos != 0x777u);
        blk_move(1u);
        post_b(0x9600u);
        settle();
        CHECK(s5_mirror_stats.reads == r0 + 1u && S.v[13].env_level == 0x0345 && SFX.ch[0].pos == 0x777u);
        CHECK(G.blkcnt == BRD_SYNTH_BLKCNT(hb.sy_status));
    }

    /* 15. the pass inside an item (81 bit 2 on: the Boom Box feed; word 0 = the track): a post's item writes the
       feed and $1FE6 bit 3 (music playing) */
    boot(0);
    disp_g.f81[1] = 1u;
    S.track = 0x1234u;
    S.playing = 1u;
    hb.ram[0x1B90 / 2] = 0xBEEFu;
    post_b(0x9600u);
    settle();
    CHECK(nit == 1 && hb.ram[0x1B90 / 2] == 0x1234u && (fe6() & 0x8u) && s5_pass_stats.item >= 1u);

    /* 16. the pass after a block: the logic moves voice 13's ENV_LEVEL, BLKCNT moves, CAUSE.BLK (CTRL.BLKIE): L2b
       runs the pass on the read-back level (the feed's voice-13 words); a second CAUSE.BLK with BLKCNT unmoved
       skips it */
    {
        uint32_t b0 = s5_pass_stats.bracket, s0 = s5_pass_stats.skip_same, o = BRD_SY_VOICE(3) + 0x1Cu;
        uint16_t f0 = hb.ram[0x1B90 / 2 + 4 + 2 * 13];
        S.v[13].gain0 = 0x600u;
        S.v[13].gain1 = 0x600u;
        brd_synth_blkie(1u);
        sw32_set(o, (sw32(o) & 0xFFFF0000u) | 0x0400u);
        blk_move(1u);
        hb.cause |= BRD_CAUSE_BLK;
        settle();
        CHECK(s5_pass_stats.blk >= 1u && s5_pass_stats.bracket == b0 + 1u && S.v[13].env_level == 0x0400);
        CHECK(hb.ram[0x1B90 / 2 + 4 + 2 * 13] == (uint16_t)(((0x400 * 0x600 / 0x600) * 5) >> 2) &&
              hb.ram[0x1B90 / 2 + 4 + 2 * 13] != f0);
        hb.cause |= BRD_CAUSE_BLK;
        settle();
        CHECK(s5_pass_stats.bracket == b0 + 1u && s5_pass_stats.skip_same == s0 + 1u && !(hb.cause & BRD_CAUSE_BLK));
    }

    /* 17. a job holds the pass: 8C81 (case 4's flow): the 8C's body item and the module-start item run no pass (the
       job is queued, then running), the job's tail runs one; the feed is first written after the module start */
    boot(0);
    disp_g.f81[1] = 1u;
    S.track = 0x0055u;
    hb.ram[0x1B90 / 2] = 0xBEEFu;
    {
        uint32_t i0 = s5_pass_stats.item, j0 = s5_pass_stats.skip_job, t0 = s5_pass_stats.tail;
        post_b(0x8C81u);
        settle();
        CHECK(nit == 2 && it[0].kind == SQ_POST && it[1].kind == SQ_JOB && it[1].feed0 == 0xBEEFu);
        CHECK(s5_pass_stats.item == i0 && s5_pass_stats.skip_job == j0 + 2u && s5_pass_stats.tail == t0 + 1u);
        CHECK(hb.ram[0x1B90 / 2] == S.track && S.track == 1u && disp_g.q_rd == disp_g.q_wr);
    }

    /* 18. a refused D1 (id 0: refusal 7) queues no item; L1 asks for the pass all the same: $1B00 word 7 */
    boot(0);
    disp_g.f81[0] = 1u;
    {
        uint32_t p0 = s5_pass_stats.post;
        post_b(0xD100u);
        settle();
        CHECK(nit == 0 && disp_g.trace_cnt[7] == 1u && hb.ram[0x1B00 / 2 + 7] == 1u && s5_pass_stats.post == p0 + 1u);
    }

    /* 19. (a design decision) the pass after a block sees a whole block or none: another block runs while the pass
       reads the 16 ENV_LEVEL words (after the 8th read); the pass reads the whole set again, so every voice's level is
       the later block's, and the FM / PSG meters decay to that block's BLKCNT too (SONG_BUG 37: no second STATUS read,
       voices 10-17 keep the earlier block's levels and the meters miss a block) */
    boot(0);
    {
        uint32_t r0 = s5_pass_stats.retry, b0 = s5_pass_stats.bracket, v, ok = 1;
        brd_synth_blkie(1u);
        for (v = 0; v < 16u; v++)
            sw32_set(BRD_SY_VOICE(v) + 0x1Cu, 0x0100u + v);
        S.v[3].env_level = 0x200;               /* an FM meter (voice 3): the chip decays it one a block */
        song_meter_blk = (uint16_t)BRD_SYNTH_BLKCNT(hb.sy_status);
        blk_move(100u);                         /* (away from any block count an earlier case's pass saw) */
        hb.cause |= BRD_CAUSE_BLK;
        st_rd0 = hb.sy_rd_n;
        st_fired = 0;
        st_on = 1;
        hb.on_point = on_point_straddle;
        settle();
        hb.on_point = 0;
        st_on = 0;
        for (v = 0; v < 16u; v++)
            ok &= S.v[10u + v].env_level == (int16_t)(0x0200u + v);
        CHECK(st_fired == 1 && ok);
        CHECK(S.v[3].env_level == 0x200 - 101); /* 100 blocks + the one during the reads */
        CHECK(s5_pass_stats.retry == r0 + 1u && s5_pass_stats.bracket == b0 + 1u);
    }

    /* 20. the counts of check A1 (since test build 5): WBUSY = what the DONE stores with no hold-off added + the
       module starts' + C6 items' own (the WBUSY diagnostic); anything else fails A1 */
    boot(0);
    {
        s5_test_stats_t t0 = s5_test;
        uint32_t w0 = (hb.sy_diag >> 16) & 0xFFu, dw, w;
        wb_run = 1;                             /* 20a. 82 (no engine part): L1's free DONE meets a block */
        post_b(0x8200u);
        settle();
        wb_run = 0;
        w = ((hb.sy_diag >> 16) & 0xFFu) - w0;
        dw = s5_test.done_wbusy - t0.done_wbusy;
        CHECK(hb.done == 1u && nit == 0 && s5_test.done_free == t0.done_free + 1u);
        CHECK(w == 1u && dw == 1u && w <= dw && s5_test.job_wbusy == t0.job_wbusy);       /* A1 holds, no B2 */
        t0 = s5_test;
        w0 = (hb.sy_diag >> 16) & 0xFFu;
        args(0x0080, 0);
        wb_run = 1;                             /* 20b. CAFF (an item): its DONE is held off, so meeting a block */
        post_b(0xCAFFu);                        /* is a protocol fault A1 must not excuse */
        settle();
        wb_run = 0;
        w = ((hb.sy_diag >> 16) & 0xFFu) - w0;
        dw = s5_test.done_wbusy - t0.done_wbusy;
        CHECK(hb.done == 2u && nit == 1 && s5_test.done_free == t0.done_free && dw == 0u);
        CHECK(w == 1u && w > dw && w > dw + (s5_test.job_wbusy - t0.job_wbusy));         /* A1 fails (not B2's) */
    }
    boot(0);
    {
        s5_test_stats_t t0 = s5_test;
        uint32_t w0 = (hb.sy_diag >> 16) & 0xFFu, w;
        wb_job = 2;                             /* 20c. 8C81 (case 4's flow): the module start's stores meet a */
        post_b(0x8C81u);                        /* block twice, its DONE none */
        settle();
        wb_job = 0;
        w = ((hb.sy_diag >> 16) & 0xFFu) - w0;
        CHECK(nit == 2 && it[1].kind == SQ_JOB && s5_test.jobs == t0.jobs + 1u);
        CHECK(w == 2u && s5_test.job_wbusy == t0.job_wbusy + 2u && s5_test.done_wbusy == t0.done_wbusy);
        CHECK(s5_test.done_free == t0.done_free && hb.done == 1u);  /* no newer arrival: no DONE after it */
        CHECK(w > (s5_test.done_wbusy - t0.done_wbusy));    /* B2: a module start's own store met a block */
        CHECK(w <= (s5_test.done_wbusy - t0.done_wbusy) + (s5_test.job_wbusy - t0.job_wbusy));   /* A1 holds */
    }
    boot(0);
    {
        s5_test_stats_t t0 = s5_test;
        uint32_t w0 = (hb.sy_diag >> 16) & 0xFFu, w, dw, n0 = (uint32_t)ndl;
        wb_job = 2;                             /* 20d. 8C81 again, and an 82 (no engine part) posted as its module */
        wb_post = 1;                            /* start begins, a block running at every DONE store from then on */
        post_b(0x8C81u);
        settle();
        wb_job = 0;
        wb_run = 0;
        w = ((hb.sy_diag >> 16) & 0xFFu) - w0;
        dw = s5_test.done_wbusy - t0.done_wbusy;
        CHECK(wb_post == 0 && nit == 2 && it[1].kind == SQ_JOB && s5_test.jobs == t0.jobs + 1u);
        CHECK(s5_test.job_wbusy == t0.job_wbusy + 2u);  /* the module start's own stores only: no DONE in its window */
        CHECK(hb.done == 2u && ndl == (int)n0 + 2 && dlog[ndl - 2] == 1u && dlog[ndl - 1] == 2u);  /* 8C's, then the 82's
                                                                                                   after the item */
        CHECK(dw == 1u && s5_test.done_free == t0.done_free + 1u && w == 3u);  /* that DONE: free, its WBUSY excused */
        CHECK(w > dw && w <= dw + (s5_test.job_wbusy - t0.job_wbusy));         /* B2 counted, A1 holds */
    }

    /* 20e-20g (the wider rule of a later repair): A1 excuses the stores of the module starts + C6 items (the items with
       no arrival: SQ_JOB, 20c; SQ_CALL, C6's song_c6_init and song_c6_ready) and nothing else. One store planted at the
       begin of an item of each other kind meets a block (WBUSY + 1 there); WBUSY is the debug save's total (DIAG folds
       included: a tick item may clear DIAG) */
    {
        s5_test_stats_t t0;
        uint32_t wt0, w, dw, jw, k, n = 0;
        c6_flash();
        boot(5);
        memset(s5_diag_base, 0, sizeof s5_diag_base);
        memset(s5_diag_acc, 0, sizeof s5_diag_acc);
        G.ready = 0u;
        S.ready = 0u;
        SFX.ready = 0u;
        disp_g.mixer = disp_g.seq_ready = disp_g.sfx_ready = 0u;
        memset(bgm_table, 0, sizeof bgm_table);
        t0 = s5_test;
        wt0 = wbusy_total();
        wb_kind = SQ_CALL;                      /* 20e. C6 (case 10's flow): a store of each of its two engine call */
        wb_job = 1;                             /* items meets a block: theirs (B2), excused, A1 holds */
        c6_post();
        CHECK(run_until_job_done());
        wb_job = 0;
        wb_kind = SQ_JOB;
        w = wbusy_total() - wt0;
        dw = s5_test.done_wbusy - t0.done_wbusy;
        jw = s5_test.job_wbusy - t0.job_wbusy;
        for (k = 0; k < (uint32_t)nit; k++)
            n += it[k].kind == SQ_CALL;
        CHECK(n == 2u && w == 2u && jw == 2u && dw == 0u && s5_test.jobs == t0.jobs + 2u);
        CHECK(w <= dw + jw);                    /* A1 holds: C6's two items are excused */
        hb.flash8 = 0;
        hb.flash16 = 0;
    }
    boot(0);
    {
        s5_test_stats_t t0 = s5_test;
        uint32_t wt0, w, dw, jw;
        memset(s5_diag_base, 0, sizeof s5_diag_base);
        memset(s5_diag_acc, 0, sizeof s5_diag_acc);
        wt0 = wbusy_total();
        args(0x0080, 0);
        wb_kind = SQ_POST;                      /* 20f. CAFF (a post's item: it has an arrival): its store meets a */
        wb_job = 1;                             /* block: not excused, A1 fails */
        post_b(0xCAFFu);
        settle();
        wb_job = 0;
        wb_kind = SQ_JOB;
        w = wbusy_total() - wt0;
        dw = s5_test.done_wbusy - t0.done_wbusy;
        jw = s5_test.job_wbusy - t0.job_wbusy;
        CHECK(nit == 1 && it[0].kind == SQ_POST && hb.done == 1u);
        CHECK(w == 1u && dw == 0u && jw == 0u && s5_test.jobs == t0.jobs);
        CHECK(w > dw + jw);                     /* A1 fails: a post's store is not excused */
    }
    boot(0);
    {
        s5_test_stats_t t0 = s5_test;
        uint32_t wt0, w, dw, jw;
        memset(s5_diag_base, 0, sizeof s5_diag_base);
        memset(s5_diag_acc, 0, sizeof s5_diag_acc);
        wt0 = wbusy_total();
        wb_kind = SQ_TICK;                      /* 20g. 9494 (a tick's item: it has an arrival): its store meets a */
        wb_job = 1;                             /* block: not excused, A1 fails */
        post_a(0x9494u);
        settle();
        wb_job = 0;
        wb_kind = SQ_JOB;
        w = wbusy_total() - wt0;
        dw = s5_test.done_wbusy - t0.done_wbusy;
        jw = s5_test.job_wbusy - t0.job_wbusy;
        CHECK(nit == 1 && it[0].kind == SQ_TICK && hb.done == 1u);
        CHECK(w == 1u && dw == 0u && jw == 0u && s5_test.jobs == t0.jobs);
        CHECK(w > dw + jw);                     /* A1 fails: a tick's store is not excused */
    }

    /* 21. (stage 3, the plan's item S3-20) a console Reset (CAUSE.V) on the stage-5 L1: the warm vector page (RAMDP
       $0000-$00FF = the boot page's vectors, the reset PC $00010100) is
       whole BEFORE V is acknowledged (the RTL holds the 68000 until then);
       RAMDP $0100-$1FDF, the queue, DONE and the register file stay as they were; no post, no item */
    boot(0);
    {
        static uint16_t wrom[0x100u / 2u];
        static uint16_t before[0x2000u / 2u];
        uint32_t i, k, d0 = hb.done, n0 = (uint32_t)nit, mei0 = hb.taken[0];
        uint16_t fea0 = fea(), fec0 = fec(), fe60 = fe6();
        for (i = 0; i < 0x100u / 2u; i++)
            wrom[i] = (uint16_t)(0x0200u + 6u * i);  /* a stand-in vector table (no game byte here) */
        hb.rom = wrom;
        for (i = 0; i < 0x2000u / 2u; i++)
            hb.ram[i] = (uint16_t)(0x5A00u ^ i);      /* the game's moved vectors, stamps and data */
        memcpy(before, (const void *)hb.ram, sizeof before);
        warm_rom = wrom;
        warm_seen = warm_whole = 0;
        hb.on_point = warm_point;
        hb.cause |= BRD_CAUSE_V;
        settle();
        hb.on_point = 0;
        hb.rom = 0;
        CHECK((hb.cause & BRD_CAUSE_V) == 0u);           /* acknowledged */
        CHECK(warm_seen >= 1 && warm_whole == 1);        /* the page was whole at the acknowledgement */
        CHECK(warm_ok());
        for (i = 0x100u / 2u, k = 0; i < 0x1FE0u / 2u; i++)
            k += hb.ram[i] != before[i];
        CHECK(k == 0u);                                  /* RAMDP above the vectors as it was */
        CHECK(hb.done == d0 && (uint32_t)nit == n0 && song_q_depth() == 0u);   /* no item, DONE unmoved */
        CHECK(fea() == fea0 && fec() == fec0 && fe6() == fe60);   /* the register file untouched: the chip only acks */
        CHECK(hb.taken[0] >= mei0 + 1u);
    }

    printf("s5_tests: %d checks, %d failed\n", checks, fails);
    return fails ? 1 : 0;
}
