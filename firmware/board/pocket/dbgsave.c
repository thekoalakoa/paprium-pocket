/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/dbgsave.c - the TEST debug save (format in dbgsave.h, decoder tools/dbgsave.py).
 *
 * Written from the wheel's TEST slot (WH_TEST, L2a) every CLK_TIM7 (102 ms) and once at the boot, so a freeze leaves
 * the last tenth of a second in the .sav: the MCU heartbeat (the watchdog's TIM7 ticks) shows the MCU alive, the frame
 * count and the last 9494 / post times show when the 68000 stopped posting, and (version 3, MCU interface v1.1) the
 * VDP's vertical-sync count and the time it last moved show whether the VDP kept running. Each write copies the
 * counters (~140 words,
 * ~1.5k cycles) and the next 64-word slice of the two logs (refreshed every ~1.3 s); the stack high-water is rescanned
 * every 10th write (1,280 words). Nothing here is on a reply path; RELEASE builds empty functions.
 *
 * Version 2 (with the 8 KB save of docs/STAGE1_PLAN.md question Q1):
 *   - the fatal halt writes the record itself (dbgsave_now from brd_milestone(ST_MS_FATAL), core/trace/fatal.c): it
 *     turns interrupts off for good, so the wheel's next write never comes;
 *   - the boot keeps the previous session's record as DBG_B_PREV before it clears the region (a Soft Reset after a
 *     freeze or a halt would otherwise overwrite it with the new session's first write), and carries the latest fatal
 *     halt forward until a newer one replaces it;
 *   - the region is cleared before the first write, so nothing of an older record, a 0.2.x import or an earlier image
 *     stays between the blocks;
 *   - every store stays inside 0x1000-0x1FFF: the whole record is bounded at compile time (DBG_REC_WORDS) and each store
 *     checks the bound (on an 8 KB RAM a store past 0x1FFF would wrap onto the game's 0x000).
 * Version 3 (the VS counter; B Jam's decision of 2026-10-13): every write first polls VSCNT (16 bits, wrapping every
 * 65,536 frames, 18.2 min) and extends it to 32 bits (a write every 102 ms sees at most a handful of frames); the block
 * DBG_B_VS and two PREV words carry it.
 * Version 4 (MCU interface v1.2: the RTL sprite decoder): every write copies the decoder's TEST read-backs, FPGAIO
 * slots 18-22 (DEC_STAT, DEC_WORDS, DEC_TIME, DEC_MARGIN, DEC_LATECNT), into the block DBG_B_DEC, so the .sav of a
 * long play test (a soak) says whether the window ever served a word before its block was decoded (LATECNT), the
 * smallest margin from a run's GO to its first window read and any OVF / BADTYPE / D0 / PRE / ABORT flag (the
 * decoder's own test criteria).
 * Version 5 (2026-10-17): the Pocket's quit restarts the MCU ~0.3 s before the .sav is read (seen in B Jam's saves from
 * the RTL sprite-decoder test build), and every reset clears the decoder's slots and the counters, so a session's
 * LATECNT never reached the .sav.
 * The boot now reads the previous record's decoder, CPU MATE, audio, scheduler, dispatcher and stack blocks into
 * DBG_B_PREV2 and folds them into the chain's worst (dbgsave.h), before the 68000 is released. The old record's block
 * chain is walked once (old_index; it used to be walked again for every word read), and the block is written once, by
 * dbgsave_start after the boot's write: the periodic write steps over it, so its cost there is one addition. The region
 * clear skips the words those two writes rewrite, which pays for the block at the boot (the release no later than
 * before in the board model, tests/equiv/q1_save.py G for the format).
 * Version 6 (2026-10-19): the CPU MATE glue's true late count, its largest lateness and its short-path calls
 * (buddy/s1_glue.h; the old late_seen counted every publish while the stub's sticky flag was up), and the album's state
 * (interim/album/mdp.c s1_album_poll, called first at every write: the MD+ result word, XLINK's CDDA underruns and ring
 * writes lost, the last album call and play request, how long a requested track has waited with playing 0) in the
 * glue and audio blocks' TEST words; PREV2 carries them across the quit and folds the largest lateness and the longest
 * wait into the chain; a late CPU MATE answer is no lateness sign any more (tests/equiv/
 * tdiag_s1.py). The stack block is stored from its own two words (stk), one block call.
 * Version 7 (2026-10-21, test build 4a, the first sound-cache build): DBG_B_CACHE, the sound-cache probe's entries
 * (this boot's and the previous seven,
 * carried from a version-7 record), right after PREV2 (DBG_CACHE_AT) and stepped over by the periodic write, as PREV2.
 * The probe's own module writes it (board/pocket/s1_cache4a.c: it reads the old record's block before this boot's
 * clear and writes the new one right after dbgsave_start, interrupts still off), so this file only leaves its room
 * (the record's TEST code size is unchanged: the plan row "debug aids" is at its allocation). PREV2's chain is carried
 * from a version-6 or -7 record (the same layout); the audio-call log keeps 128 calls (interim/s1/s1_interim.h
 * S1_AU_LOG), which makes the room.
 * Version 8 (2026-10-22, test build 4b, the boot overlay): DBG_B_CACHE is the boot cache's record
 * (board/pocket/s1_cache4b.c writes it, the same way and place; 81 words as before); PREV2's chain is carried from a
 * version-6, -7 or -8 record.
 * Version 9 (test build 5, the synth build; the FW_S5 images; dbgsave.h): no interim audio (its blocks and the
 * audio-call log go), DBG_B_SYNTH in DBG_B_AUDIO's place (the synth's DIAG totals and TEST assertions, read at every
 * write), PREV2's audio words carrying the synth's. The other s1 images build version 8 exactly as before.
 * Version 10 (the FW_S5 TEST images from test build S3a on; dbgsave.h): the record cut to the lateness signs, the
 * freeze telemetry and the CPU MATE counters, fixed blocks (the lean section below); version 9 is built no more, so the
 * full section is the other s1 images' version 8 only. */
#include <stdint.h>
#include <stddef.h>
#include "board.h"
#include "s1_boot.h"
#include "sched.h"
#include "sched_hooks.h"
#include "stats.h"
#include "dbgsave.h"
#include "boot/c4b.h"

#if PPM_RELEASE
void dbgsave_start(void) { }
void dbgsave_now(void) { }
void wh_test(uint32_t due) { (void)due; }
#elif TDIAG_LEAN
/* ---- version 10 (the FW_S5 TEST images from test build S3a on, core/trace/tdiag.h; format in dbgsave.h) --------
   The record keeps only the lateness signs, the freeze telemetry and the CPU MATE counters, as fixed blocks; the boot
   keeps the previous session's (PREV) and the chain of the sessions before it (PREV2) from a version-10 record, as
   versions 5-9 did, so the Quit's reboot (which rewrites the record) keeps the session played. Written once at the
   boot, every CLK_TIM7 from the wheel's TEST slot, and at a fatal halt. */
#include "disp.h"
#include "wdog.h"
#include "fatal.h"
#include "s1_glue.h"
#include "song.h"
extern uint8_t  s5_diag_base[4];                        /* core/dispatch/disp.c: DIAG's last folded value, its totals */
extern uint32_t s5_diag_acc[4];

extern char __stack_floor[], __crt0_stack_begin[];

static uint32_t on, writes, pos;
static struct { uint32_t hw_bytes, floor_ok; } stk;    /* DBG_B_STACK as stored */
static struct { uint32_t count, raw, t_last; } vs __attribute__((section(".bss_upper")));   /* DBG_B_VS */
static uint32_t prev[DBG_PV_WORDS + DBG_Q_WORDS] __attribute__((section(".bss_upper")));   /* PREV, then PREV2 (p2) */
#define p2                      (prev + DBG_PV_WORDS)
static uint32_t old_at[DBG_B_SYNTH + 1u] __attribute__((section(".bss_upper")));   /* the old record's blocks: data word
                                                               index << 16 | words, 0 absent */
#define DW(i)                   (((volatile uint32_t *)(void *)(brd_save() + DBG_SAVE_OFF))[i])
#define BOOT_OS                 __attribute__((noinline, optimize("Os")))   /* once a boot, 68000 held: size first */
#define DBG_WORDS               (DBG_SAVE_BYTES / 4u)
#define WORDS(x)                ((uint32_t)(sizeof(x) / 4u))
/* the record: every block's header and words in dbg_write's order; DBG_Q_AT = where PREV2's header lands */
#define DBG_Q_AT                (1u + 8u + 1u + WORDS(st_stats) + 1u + DBG_SC_WORDS + 1u + 1u + 1u + WORDS(fatal_rec) + \
                                 1u + DBG_GL_WORDS + 1u + 1u + 1u + 2u + 1u + WORDS(stk) + 1u + DBG_PV_WORDS + \
                                 1u + WORDS(vs) + 1u + DBG_DEC_WORDS)
#define DBG_REC_WORDS           (DBG_Q_AT + 1u + DBG_Q_WORDS + 1u)
_Static_assert(DBG_REC_WORDS <= DBG_WORDS, "the debug record does not fit 0x1000-0x1FFF");
_Static_assert(WORDS(st_stats) == 4u && WORDS(fatal_rec) == 5u && WORDS(stk) == 2u && WORDS(vs) == 3u,
               "version 10's block sizes (dbgsave.h)");

static void put(uint32_t v)
{
    if (pos < DBG_WORDS)
        DW(pos) = v;
    pos++;
}

static __attribute__((noinline)) void block(uint32_t id, const void *p, uint32_t n)   /* n words */
{
    const volatile uint32_t *w = (const volatile uint32_t *)p;
    uint32_t i;
    put((id << 16) | n);
    for (i = 0; i < n; i++)
        put(w[i]);
}

static void stack_scan(void)
{
    const uint32_t *lo = (const uint32_t *)(void *)__stack_floor, *top = (const uint32_t *)(void *)__crt0_stack_begin;
    const uint32_t *p = lo;
    while (p < top && *p == S1_STACK_FILL)
        p++;
    stk.hw_bytes = (uint32_t)((const char *)top - (const char *)p);
    stk.floor_ok = *lo == S1_STACK_FILL;
}

static void vs_poll(void)                               /* VSCNT's 16 bits extended to 32 (0 at every reset) */
{
    uint32_t raw = brd_vs_count(), d = (raw - vs.raw) & BRD_VS_COUNT_MASK;
    if (d) {
        vs.count += d;
        vs.t_last = brd_now();
    }
    vs.raw = raw;
}

static void dbg_write(void)
{
    uint32_t w[DBG_GL_WORDS];
    vs_poll();
    pos = 0;
    writes++;
    if (writes % 10u == 1u)
        stack_scan();
    put((DBG_B_HEAD << 16) | 8u);
    put(DBG_MAGIC);
    put(DBG_VERSION);
    put(writes);
    put(brd_now());
    put(brd_cycles());
    put(BRD_CLK_HZ);
    put(DBG_WORDS);
    put(0u);
    block(DBG_B_STATS, &st_stats, WORDS(st_stats));     /* the frame ticks and the last post */
    block(DBG_B_SCHED, &sched_stats.exc, DBG_SC_WORDS); /* exc, its first cause, epc, tval (sched.h, in order) */
    block(DBG_B_WDOG, &wdog_stats.ticks, 1u);           /* the MCU heartbeat */
    block(DBG_B_FATAL, (const void *)&fatal_rec, WORDS(fatal_rec));
    w[DBG_GL_DISCARDED] = s1_glue_stats.discarded;
    w[DBG_GL_ABORTED] = s1_glue_stats.aborted;
    w[DBG_GL_LATE] = s1_glue_stats.late;
    w[DBG_GL_CYCLES_MAX] = s1_glue_stats.cycles_max;
    block(DBG_B_GLUE, w, DBG_GL_WORDS);
    w[0] = s5_diag_acc[1] + (((brd_synth_diag() >> 8) - s5_diag_base[1]) & 0xFFu);   /* DIAG.TIMEOUTS: the folded total
                                                               and what the register counted since (read only) */
    block(DBG_B_SYNTH, w, 1u);
    w[0] = disp_g.refusals;
    w[1] = disp_g.jobs_failed;
    block(DBG_B_DISP, w, 2u);
    block(DBG_B_STACK, &stk, WORDS(stk));
    block(DBG_B_PREV, prev, DBG_PV_WORDS);
    block(DBG_B_VS, &vs, WORDS(vs));
    block(DBG_B_DEC, (const void *)(uintptr_t)POCKET_FIO_DEC_STAT, DBG_DEC_WORDS);   /* the RTL decoder's slots 18-22 */
    pos += 1u + DBG_Q_WORDS;                            /* PREV2, constant for the session: dbgsave_start writes it */
    put((uint32_t)DBG_B_END << 16);
}
_Static_assert(offsetof(sched_stats_t, exc_first_tval) == offsetof(sched_stats_t, exc) + 12u, "DBG_B_SCHED (version 10)");

/* the old record's block chain, walked once (as versions 5-9) */
static BOOT_OS void old_index(void)
{
    uint32_t i = 0u;
    while (i < DBG_WORDS) {
        uint32_t h = DW(i), bid = h >> 16, len = h & 0xFFFFu;
        if (bid == 0u || bid == DBG_B_END || i + 1u + len > DBG_WORDS)
            return;
        if (bid <= DBG_B_SYNTH && !old_at[bid])
            old_at[bid] = ((i + 1u) << 16) | len;
        i += 1u + len;
    }
}

static __attribute__((noinline)) uint32_t old_word(uint32_t id, uint32_t k)
{
    uint32_t a = old_at[id];
    return k < (a & 0xFFFFu) ? DW((a >> 16) + k) : 0u;
}

/* where PREV's words and PREV2's part 1 come from in a version-10 record: block id, word */
static const uint8_t old_src[DBG_PV_WORDS + DBG_Q_BOOTS][2] = {
    [DBG_PV_WRITES] = { DBG_B_HEAD, 2u },
    [DBG_PV_NOW] = { DBG_B_HEAD, 3u },
    [DBG_PV_HEARTBEAT] = { DBG_B_WDOG, 0u },
    [DBG_PV_N9494] = { DBG_B_STATS, 0u },
    [DBG_PV_T9494] = { DBG_B_STATS, 1u },
    [DBG_PV_TPOST] = { DBG_B_STATS, 2u },
    [DBG_PV_LASTWORD] = { DBG_B_STATS, 3u },
    [DBG_PV_EXC] = { DBG_B_SCHED, 0u },
    [DBG_PV_EXC_CAUSE] = { DBG_B_SCHED, 1u },
    [DBG_PV_EXC_EPC] = { DBG_B_SCHED, 2u },
    [DBG_PV_VS_COUNT] = { DBG_B_VS, 0u },
    [DBG_PV_T_VS] = { DBG_B_VS, 2u },
    [DBG_PV_WORDS + DBG_Q_DEC_STAT] = { DBG_B_DEC, 0u },
    [DBG_PV_WORDS + DBG_Q_DEC_MARGIN] = { DBG_B_DEC, 3u },
    [DBG_PV_WORDS + DBG_Q_DEC_LATECNT] = { DBG_B_DEC, 4u },
    [DBG_PV_WORDS + DBG_Q_TIMEOUTS] = { DBG_B_SYNTH, 0u },
    [DBG_PV_WORDS + DBG_Q_EXC] = { DBG_B_SCHED, 0u },
    [DBG_PV_WORDS + DBG_Q_FLOOR_OK] = { DBG_B_STACK, 1u },
    [DBG_PV_WORDS + DBG_Q_STACK_HW] = { DBG_B_STACK, 0u },
    [DBG_PV_WORDS + DBG_Q_REFUSALS] = { DBG_B_DISP, 0u },
    [DBG_PV_WORDS + DBG_Q_JOBS_FAILED] = { DBG_B_DISP, 1u },
    [DBG_PV_WORDS + DBG_Q_DISCARDED] = { DBG_B_GLUE, DBG_GL_DISCARDED },
    [DBG_PV_WORDS + DBG_Q_ABORTED] = { DBG_B_GLUE, DBG_GL_ABORTED },
    [DBG_PV_WORDS + DBG_Q_LATE] = { DBG_B_GLUE, DBG_GL_LATE },
    [DBG_PV_WORDS + DBG_Q_CYCLES_MAX] = { DBG_B_GLUE, DBG_GL_CYCLES_MAX },
    [DBG_PV_WORDS + DBG_Q_DEC_WORDS] = { DBG_B_DEC, 1u },
    [DBG_PV_WORDS + DBG_Q_DEC_TIME] = { DBG_B_DEC, 2u },
    [DBG_PV_WORDS + DBG_Q_EXC_CAUSE] = { DBG_B_SCHED, 1u },
    [DBG_PV_WORDS + DBG_Q_EXC_EPC] = { DBG_B_SCHED, 2u },
    [DBG_PV_WORDS + DBG_Q_EXC_TVAL] = { DBG_B_SCHED, 3u },
};
/* the words of part 1 whose chain form counts in the lateness sign (with DEC_STAT & DBG_DEC_BAD; dbgsave.h) */
#define Q_SIGN                  ((1u << DBG_Q_DEC_LATECNT) | (1u << DBG_Q_TIMEOUTS) | (1u << DBG_Q_EXC) | \
                                 (1u << DBG_Q_FLOOR_OK))

/* prev[] and p2[] are .bss_upper: zero from crt0 at this boot; this runs once, before the size probe and the clear */
static BOOT_OS void prev_take(void)
{
    uint32_t v, i, x, d, age = 0u;
    if (DW(0) >> 16 != DBG_B_HEAD || DW(1) != DBG_MAGIC)
        return;                                         /* no record */
    v = DW(2);
    prev[DBG_PV_STATE] = p2[DBG_Q_STATE] = v;
    if (v != DBG_VERSION)                               /* another version's layout (test build S2's version 9
                                                           included): named in STATE, nothing carried; the chain
                                                           starts again */
        return;
    old_index();
    for (i = 0; i < DBG_PV_WORDS + DBG_Q_BOOTS; i++)
        if (old_src[i][0])
            prev[i] = old_word(old_src[i][0], old_src[i][1]);
    if (old_word(DBG_B_FATAL, 0u)) {                    /* the previous session halted */
        for (i = 0; i < 4u; i++)
            prev[DBG_PV_FATAL_CODE + i] = old_word(DBG_B_FATAL, i);
        age = 1u;
    } else if ((age = old_word(DBG_B_PREV, DBG_PV_FATAL_AGE)) != 0u) {   /* an older one, carried */
        for (i = 0; i < 4u; i++)
            prev[DBG_PV_FATAL_CODE + i] = old_word(DBG_B_PREV, DBG_PV_FATAL_CODE + i);
        age++;
    }
    prev[DBG_PV_FATAL_AGE] = age;
    if (old_word(DBG_B_PREV2, DBG_Q_BOOTS))             /* the old record's chain */
        for (i = DBG_Q_BOOTS; i < DBG_Q_WORDS; i++)
            p2[i] = old_word(DBG_B_PREV2, i);
    p2[DBG_Q_BOOTS]++;
    p2[DBG_Q_W(DBG_Q_DEC_STAT)] |= p2[DBG_Q_DEC_STAT] & DBG_DEC_FLAGS;
    d = p2[DBG_Q_DEC_STAT] & DBG_DEC_BAD;
    for (i = DBG_Q_DEC_MARGIN; i <= DBG_Q_CYCLES_MAX; i++) {   /* the chain forms: larger = worse */
        x = p2[i] ^ (i == DBG_Q_DEC_MARGIN ? DBG_P2_MARGIN_X : i == DBG_Q_FLOOR_OK);
        if (x > p2[DBG_Q_W(i)])
            p2[DBG_Q_W(i)] = x;
        if ((Q_SIGN >> i) & 1u)
            d |= x;
    }
    x = p2[DBG_Q_DIRTY_AGE];
    p2[DBG_Q_DIRTY_AGE] = d ? 1u : x + (x != 0u);        /* the lateness sign: this session, else one older */
    SONG_FRAME_PAD16();                                 /* brain hygiene (core/song/song.h) */
}

void dbgsave_start(void)
{
    volatile uint8_t *s = brd_save();
    uint8_t v0, w;
    uint32_t i;
    prev_take();
    v0 = s[0];
    w = (uint8_t)(v0 ^ 0x5Au);
    s[DBG_SAVE_OFF] = w;                                /* the size probe: 4 KB save RAM aliases 0x1000 to 0 */
    if (s[0] == w) {
        s[0] = v0;                                      /* the game's byte back; no debug save */
        on = 0u;
        return;
    }
    on = 1u;
    for (i = DBG_REC_WORDS; i < DBG_WORDS; i++)         /* nothing of an older record stays after this one */
        DW(i) = 0u;
    dbg_write();
    pos = DBG_Q_AT;
    block(DBG_B_PREV2, p2, DBG_Q_WORDS);                /* once (dbg_write steps over it) */
    wheel_arm(WH_TEST, brd_now() + CLK_TIM7);
}

void dbgsave_now(void)
{
    if (on)
        dbg_write();
}

void wh_test(uint32_t due)
{
    uint32_t next = due + CLK_TIM7;
    if (!on)
        return;
    dbg_write();
    while (brd_until(next) <= 0)                        /* periods missed (a long section) merge into one */
        next += CLK_TIM7;
    wheel_arm(WH_TEST, next);
}
#else
#include "disp.h"
#include "wdog.h"
#include "fatal.h"
#include "s1_glue.h"
#include "s1_interim.h"
#include "s1_freg.h"

extern char __stack_floor[], __crt0_stack_begin[];

static uint32_t on, writes, pos, slice;
static struct { uint32_t hw_bytes, floor_ok; } stk;    /* DBG_B_STACK as stored (stack_scan): one block call, no copy */
static uint32_t prev[DBG_PREV_WORDS + DBG_P2_WORDS] __attribute__((section(".bss_upper")));   /* wram_data is tight
                                                               (STAGE1_PLAN.md 5.3); then DBG_B_PREV2's words (p2) */
#define p2                      (prev + DBG_PREV_WORDS)
#define DBG_B_OLD_LAST          DBG_B_PREV2
static uint32_t old_at[DBG_B_OLD_LAST + 1u] __attribute__((section(".bss_upper")));   /* the old record's blocks: data
                                                               word index << 16 | words, 0 absent (old_index) */
_Static_assert(DBG_CACHE_ENTRY_WORDS == C4B_REC_WORDS && DBG_CACHE_WORDS == 81u && DBG_B_CACHE == DBG_B_PREV2 + 1,
               "DBG_B_CACHE (version 8: the size of version 7's)");
static struct { uint32_t count, raw, t_last; } vs __attribute__((section(".bss_upper")));   /* DBG_B_VS (zero at boot) */
#define DW(i)                   (((volatile uint32_t *)(void *)(brd_save() + DBG_SAVE_OFF))[i])
#define BOOT_OS                 __attribute__((noinline, optimize("Os")))   /* once a boot, 68000 held: size first */
#define DBG_WORDS               (DBG_SAVE_BYTES / 4u)
#define SLICE                   64u
#define WORDS(x)                ((uint32_t)(sizeof(x) / 4u))
#define DISP_WORDS              16u
#if S1_ORACLE
#define ORACLE_WORDS            (2u + S1_ORACLE_N)
#else
#define ORACLE_WORDS            0u
#endif
/* the whole record: each block's header word and data, the two logs (header, n, ring), the end word; DBG_P2_AT =
   where DBG_B_PREV2's header lands (every block before it has a fixed size: dbg_write's order) */
#define DEC_WORDS_N             5u      /* DBG_B_DEC: FPGAIO slots 18-22 (version 4) */
#define DBG_P2_AT               (1u + 8u + 1u + WORDS(s1_boot_rec) + 1u + WORDS(st_stats) + 1u + WORDS(sched_stats) + \
                                 1u + WORDS(wdog_stats) + 1u + WORDS(fatal_rec) + 1u + WORDS(s1_glue_stats) + \
                                 1u + WORDS(s1_audio_stats) + 1u + DISP_WORDS + 1u + 2u + 1u + WORDS(s1_interim_stats) + \
                                 1u + DBG_PREV_WORDS + 1u + WORDS(vs) + 1u + DEC_WORDS_N)
#define DBG_CACHE_AT            (DBG_P2_AT + 1u + DBG_P2_WORDS)    /* version 7: DBG_B_CACHE's header, after PREV2 */
#define DBG_REC_WORDS           (DBG_CACHE_AT + 1u + DBG_CACHE_WORDS + 2u + S1_AU_LOG + ORACLE_WORDS + 1u)
_Static_assert(DBG_REC_WORDS <= DBG_SAVE_BYTES / 4u, "the debug record does not fit 0x1000-0x1FFF");

static void put(uint32_t v)
{
    if (pos < DBG_WORDS)
        DW(pos) = v;
    pos++;
}

static __attribute__((noinline)) void block(uint32_t id, const void *p, uint32_t bytes)   /* out of line: 13 users */
{
    const volatile uint32_t *w = (const volatile uint32_t *)p;
    uint32_t i, n = bytes / 4u;
    put((id << 16) | n);
    for (i = 0; i < n; i++)
        put(w[i]);
}

static void stack_scan(void)
{
    const uint32_t *lo = (const uint32_t *)(void *)__stack_floor, *top = (const uint32_t *)(void *)__crt0_stack_begin;
    const uint32_t *p = lo;
    while (p < top && *p == S1_STACK_FILL)
        p++;
    stk.hw_bytes = (uint32_t)((const char *)top - (const char *)p);
    stk.floor_ok = *lo == S1_STACK_FILL;
}

/* a log: header, n, then the ring; only the words of [slice, slice + SLICE) of the two logs together are rewritten */
static __attribute__((noinline)) void log_block(uint32_t id, uint32_t n, const uint32_t *e, uint32_t len, uint32_t *at)
{
    uint32_t i;
    put((id << 16) | (len + 1u));
    put(n);
    for (i = 0; i < len; i++, (*at)++) {
        if (*at >= slice && *at < slice + SLICE && pos < DBG_WORDS)
            DW(pos) = e[i];
        pos++;
    }
}

/* the VS counter: 16 bits in RTL, 32 here; the count VSCNT gave since the boot (it is 0 at every reset) */
static void vs_poll(void)
{
    uint32_t raw = brd_vs_count(), d = (raw - vs.raw) & BRD_VS_COUNT_MASK;
    if (d) {
        vs.count += d;
        vs.t_last = brd_now();
    }
    vs.raw = raw;
}


static void dbg_write(void)
{
    uint32_t at = 0, d[DISP_WORDS], i;
    i = brd_irq_save();                                     /* test build 4b: the VS count and the album's poll at
                                                               one */
    vs_poll();                                              /* instant: a play request that preempted this write */
    s1_album_poll(vs.count);                                /* between them took the older count as its frame */
    brd_irq_restore(i);                                     /* (tdiag_s1 seed 5 M4: 2 frames early, 27 ms) */
    pos = 0;                                                /* version 6: the album's state into DBG_B_AUDIO's words */
    writes++;
    if (writes % 10u == 1u)
        stack_scan();
    put((DBG_B_HEAD << 16) | 8u);
    put(DBG_MAGIC);
    put(DBG_VERSION);
    put(writes);
    put(brd_now());
    put(brd_cycles());
    put(BRD_CLK_HZ);
    put(DBG_WORDS);
    put(S1_ORACLE);
    block(DBG_B_BOOT, (const void *)&s1_boot_rec, sizeof s1_boot_rec);
    block(DBG_B_STATS, &st_stats, sizeof st_stats);
    block(DBG_B_SCHED, &sched_stats, sizeof sched_stats);
    block(DBG_B_WDOG, &wdog_stats, sizeof wdog_stats);
    block(DBG_B_FATAL, (const void *)&fatal_rec, sizeof fatal_rec);
    block(DBG_B_GLUE, &s1_glue_stats, sizeof s1_glue_stats);
    block(DBG_B_AUDIO, &s1_audio_stats, sizeof s1_audio_stats);
    d[0] = disp_g.refusals;
    d[1] = disp_g.last_trace;
    d[2] = disp_g.jobs_run;
    d[3] = disp_g.jobs_failed;
    d[4] = disp_g.q_wr | ((uint32_t)disp_g.q_rd << 8) | ((uint32_t)disp_g.app_ready << 16) | ((uint32_t)disp_g.mixer << 24);
    d[5] = disp_g.wd_arm | ((uint32_t)disp_g.wd_count << 16);
    d[6] = disp_g.g194 | ((uint32_t)disp_g.f81[0] << 16) | ((uint32_t)disp_g.f81[1] << 20) |
           ((uint32_t)disp_g.f81[2] << 24) | ((uint32_t)disp_g.f81[3] << 28);
    d[7] = st_shadow(ST_FE4) | ((uint32_t)st_shadow(ST_FE6) << 16);
    for (i = 0; i < 8u; i++)
        d[8u + i] = disp_g.trace_cnt[2u * i] | ((uint32_t)disp_g.trace_cnt[2u * i + 1u] << 16);
    block(DBG_B_DISP, d, sizeof d);
    block(DBG_B_STACK, &stk, sizeof stk);
    block(DBG_B_INTERIM, &s1_interim_stats, sizeof s1_interim_stats);   /* (the 0.2.6 sprite bodies' stats: kept in 9) */
    block(DBG_B_PREV, prev, DBG_PREV_WORDS * 4u);
    block(DBG_B_VS, &vs, sizeof vs);
    block(DBG_B_DEC, (const void *)(uintptr_t)POCKET_FIO_DEC_STAT, DEC_WORDS_N * 4u);   /* version 4: the RTL decoder's
                                                               slots 18-22, read in place (consecutive FPGAIO words) */
    pos += 1u + DBG_P2_WORDS + 1u + DBG_CACHE_WORDS;        /* version 5: DBG_B_PREV2 at DBG_P2_AT and (version 7)
                                                               DBG_B_CACHE after it, constant for the session:
                                                               dbgsave_start writes them once */
    log_block(DBG_B_AULOG, s1_au_log.n, s1_au_log.e, S1_AU_LOG, &at);
#if S1_ORACLE
    log_block(DBG_B_ORACLE, s1_oracle_log.n, s1_oracle_log.e, S1_ORACLE_N, &at);
#endif
    if (at)
        slice = (slice + SLICE) % at;
    put((uint32_t)DBG_B_END << 16);
}

/* ---- the previous session's record (read before the size probe and the clear) ---------------------------------- */
/* the old record's block chain, walked once: where each known block's data starts and its length (the first block of
   an id, as the old per-word walk found it); the walk stops at an empty or end header or a block past the region */
static BOOT_OS void old_index(void)
{
    uint32_t i = 0u;
    while (i < DBG_WORDS) {
        uint32_t h = DW(i), bid = h >> 16, len = h & 0xFFFFu;
        if (bid == 0u || bid == DBG_B_END || i + 1u + len > DBG_WORDS)
            return;
        if (bid <= DBG_B_OLD_LAST && !old_at[bid])
            old_at[bid] = ((i + 1u) << 16) | len;
        i += 1u + len;
    }
}

static __attribute__((noinline)) uint32_t old_word(uint32_t id, uint32_t k)   /* word k of block id found, 0 if absent */
{
    uint32_t a = old_at[id];
    return k < (a & 0xFFFFu) ? DW((a >> 16) + k) : 0u;
}

/* where the words of prev[] (DBG_PREV_*) and of p2[]'s part 1 (DBG_P2_DEC_STAT .. DBG_P2_EXC_TVAL, from a version-4 or
   -5 record only) come from in the old record: block id, word; { 0, 0 } = none here (old_word finds no block 0) */
#define P2(k)                   (DBG_PREV_WORDS + (k))
static const uint8_t old_src[P2(DBG_P2_BOOTS)][2] = {
    [DBG_PREV_WRITES] = { DBG_B_HEAD, 2u },
    [DBG_PREV_NOW] = { DBG_B_HEAD, 3u },
    [DBG_PREV_MCYCLE] = { DBG_B_HEAD, 4u },
    [DBG_PREV_BOOT_CODE] = { DBG_B_BOOT, offsetof(s1_boot_rec_t, code) / 4u },
    [DBG_PREV_BOOT_TIME] = { DBG_B_BOOT, offsetof(s1_boot_rec_t, time) / 4u },
    [DBG_PREV_HEARTBEAT] = { DBG_B_WDOG, offsetof(wdog_stats_t, ticks) / 4u },
    [DBG_PREV_GATED] = { DBG_B_WDOG, offsetof(wdog_stats_t, gated) / 4u },
    [DBG_PREV_N9494] = { DBG_B_STATS, offsetof(st_stats_t, n9494) / 4u },
    [DBG_PREV_T9494] = { DBG_B_STATS, offsetof(st_stats_t, t_last_9494) / 4u },
    [DBG_PREV_TPOST] = { DBG_B_STATS, offsetof(st_stats_t, t_last_post) / 4u },
    [DBG_PREV_LASTWORD] = { DBG_B_STATS, offsetof(st_stats_t, last_word) / 4u },
    [DBG_PREV_EXC] = { DBG_B_SCHED, offsetof(sched_stats_t, exc) / 4u },
    [DBG_PREV_EXC_CAUSE] = { DBG_B_SCHED, offsetof(sched_stats_t, exc_first_cause) / 4u },
    [DBG_PREV_EXC_EPC] = { DBG_B_SCHED, offsetof(sched_stats_t, exc_first_epc) / 4u },
    [DBG_PREV_VS_COUNT] = { DBG_B_VS, 0u },                 /* version 3 (no VS block before it: 0) */
    [DBG_PREV_T_VS] = { DBG_B_VS, 2u },
    [P2(DBG_P2_DEC_STAT)] = { DBG_B_DEC, 0u },
    [P2(DBG_P2_DEC_MARGIN)] = { DBG_B_DEC, 3u },
    [P2(DBG_P2_DEC_LATECNT)] = { DBG_B_DEC, 4u },
    [P2(DBG_P2_LATE)] = { DBG_B_GLUE, offsetof(s1_glue_stats_t, late) / 4u },   /* version 6 (an older record's glue
                                                               block ends before it: 0, its late_seen not carried) */
    [P2(DBG_P2_DISCARDED)] = { DBG_B_GLUE, offsetof(s1_glue_stats_t, discarded) / 4u },
    [P2(DBG_P2_ABORTED)] = { DBG_B_GLUE, offsetof(s1_glue_stats_t, aborted) / 4u },
    [P2(DBG_P2_ABORT_LANDINGS)] = { DBG_B_GLUE, offsetof(s1_glue_stats_t, abort_landings) / 4u },
    [P2(DBG_P2_CYCLES_MAX)] = { DBG_B_GLUE, offsetof(s1_glue_stats_t, cycles_max) / 4u },
    [P2(DBG_P2_CATCHUPS)] = { DBG_B_AUDIO, offsetof(s1_audio_stats_t, catchups) / 4u },
    [P2(DBG_P2_EXC)] = { DBG_B_SCHED, offsetof(sched_stats_t, exc) / 4u },
    [P2(DBG_P2_REFUSALS)] = { DBG_B_DISP, 0u },             /* dbg_write's d[0] */
    [P2(DBG_P2_JOBS_FAILED)] = { DBG_B_DISP, 3u },          /* d[3] */
    [P2(DBG_P2_STACK_HW)] = { DBG_B_STACK, 0u },
    [P2(DBG_P2_FLOOR_OK)] = { DBG_B_STACK, 1u },
    [P2(DBG_P2_LATE_MAX)] = { DBG_B_GLUE, offsetof(s1_glue_stats_t, late_max) / 4u },   /* version 6 (0 from an older */
    [P2(DBG_P2_ALB_WAIT_MAX)] = { DBG_B_AUDIO, offsetof(s1_audio_stats_t, alb_wait_max) / 4u },   /* record: its blocks
                                                                                                 end before them) */
    [P2(DBG_P2_DEC_WORDS)] = { DBG_B_DEC, 1u },
    [P2(DBG_P2_DEC_TIME)] = { DBG_B_DEC, 2u },
    [P2(DBG_P2_CALLS)] = { DBG_B_GLUE, offsetof(s1_glue_stats_t, calls) / 4u },
    [P2(DBG_P2_EXC_CAUSE)] = { DBG_B_SCHED, offsetof(sched_stats_t, exc_first_cause) / 4u },
    [P2(DBG_P2_EXC_EPC)] = { DBG_B_SCHED, offsetof(sched_stats_t, exc_first_epc) / 4u },
    [P2(DBG_P2_EXC_TVAL)] = { DBG_B_SCHED, offsetof(sched_stats_t, exc_first_tval) / 4u },
    [P2(DBG_P2_SHORT_CALLS)] = { DBG_B_GLUE, offsetof(s1_glue_stats_t, short_calls) / 4u },     /* version 6 */
    [P2(DBG_P2_ALB_RES)] = { DBG_B_AUDIO, offsetof(s1_audio_stats_t, alb_res) / 4u },
    [P2(DBG_P2_ALB_UNDER)] = { DBG_B_AUDIO, offsetof(s1_audio_stats_t, alb_xl14) / 4u },
    [P2(DBG_P2_ALB_LOST)] = { DBG_B_AUDIO, offsetof(s1_audio_stats_t, alb_xl18) / 4u },
    [P2(DBG_P2_ALB_CALLS)] = { DBG_B_AUDIO, offsetof(s1_audio_stats_t, alb_calls) / 4u },
    [P2(DBG_P2_ALB_WAIT)] = { DBG_B_AUDIO, offsetof(s1_audio_stats_t, alb_wait) / 4u },
};
_Static_assert(DBG_P2_DEC_MARGIN == DBG_P2_DEC_STAT + 1 && DBG_P2_FLOOR_OK == DBG_P2_STACK_HW + 1 &&
               DBG_P2_LATE_MAX == DBG_P2_FLOOR_OK + 1 && DBG_P2_ALB_WAIT_MAX == DBG_P2_LATE_MAX + 1 &&
               DBG_P2_W(DBG_P2_DEC_STAT) == DBG_P2_DIRTY_AGE + 1, "DBG_P2_W: the folded words in their order");
/* the words of part 1 whose chain form counts in the lateness sign (with DEC_STAT & DBG_DEC_BAD; dbgsave.h; version 6:
   no longer the CPU MATE's late answers) */
#define P2_SIGN                 ((1u << DBG_P2_DEC_LATECNT) | (1u << DBG_P2_EXC) | (1u << DBG_P2_FLOOR_OK))

/* prev[] and p2[] are .bss_upper: zero from crt0 at this boot (also every chain word's start value), and this runs
   once per boot, before the size probe and the clear */
static BOOT_OS void prev_take(void)
{
    uint32_t v, i, x, d, from = 0u, age = 0u;
    if (DW(0) >> 16 != DBG_B_HEAD || DW(1) != DBG_MAGIC)
        return;                                             /* no record (with a 4 KB RAM this reads the game's 0x000:
                                                               no magic there) */
    v = DW(2);
    if (v < 1u || v > DBG_VERSION) {                        /* versions 1-8 (4 = 3 + the decoder block, 5 = + PREV2,
                                                               6 = + the glue's and the album's TEST words, 7 = + the
                                                               cache probe, 8 = the boot cache's record there) */
        prev[DBG_PREV_STATE] = p2[DBG_P2_STATE] = 0xFFFFFFFFu;
        return;
    }
    old_index();
    for (i = 0; i < (v >= 4u ? P2(DBG_P2_BOOTS) : DBG_PREV_WORDS); i++)   /* PREV2's part 1: a version 4 or 5 */
        prev[i] = old_word(old_src[i][0], old_src[i][1]);                 /* record only (the same layouts) */
    prev[DBG_PREV_STATE] = p2[DBG_P2_STATE] = v;
    if (old_word(DBG_B_FATAL, offsetof(fatal_rec_t, code) / 4u)) {            /* the previous session halted */
        from = DBG_B_FATAL;
        age = 1u;
    } else if (v >= 2u && (age = old_word(DBG_B_PREV, DBG_PREV_FATAL_AGE)) != 0u) {   /* an older one, carried */
        from = DBG_B_PREV;
        age++;
    }
    if (age) {
        for (i = 0; i < 5u; i++)
            prev[DBG_PREV_FATAL_CODE + i] = old_word(from, (from == DBG_B_PREV ? DBG_PREV_FATAL_CODE : 0u) + i);
        prev[DBG_PREV_FATAL_AGE] = age;
    }
    if (v < 4u)                                             /* no decoder block, older layouts: nothing carried */
        return;
    /* PREV2's part 2: the old record's chain (this layout only, version 6's, which versions 7 and 8 keep: a version-5 chain
       starts again), then the previous session folded in (dbgsave.h) */
    if (v >= 6u && old_word(DBG_B_PREV2, DBG_P2_BOOTS))
        for (i = DBG_P2_BOOTS; i < DBG_P2_WORDS; i++)
            p2[i] = old_word(DBG_B_PREV2, i);
    p2[DBG_P2_BOOTS]++;
    p2[DBG_P2_W(DBG_P2_DEC_STAT)] |= p2[DBG_P2_DEC_STAT] & DBG_DEC_FLAGS;
    d = p2[DBG_P2_DEC_STAT] & DBG_DEC_BAD;
    for (i = DBG_P2_DEC_MARGIN; i <= DBG_P2_ALB_WAIT_MAX; i++) {   /* the chain forms: larger = worse */
        x = p2[i] ^ (i == DBG_P2_DEC_MARGIN ? DBG_P2_MARGIN_X : i == DBG_P2_FLOOR_OK);
        if (x > p2[DBG_P2_W(i)])
            p2[DBG_P2_W(i)] = x;
        if ((P2_SIGN >> i) & 1u)
            d |= x;
    }
    x = p2[DBG_P2_DIRTY_AGE];
    p2[DBG_P2_DIRTY_AGE] = d ? 1u : x + (x != 0u);          /* the lateness sign: this session, else one older */
}
_Static_assert(sizeof(fatal_rec_t) == 20u && offsetof(fatal_rec_t, polls) == 16u, "DBG_PREV_FATAL_* follow fatal_rec_t");

void dbgsave_start(void)
{
    volatile uint8_t *s = brd_save();
    uint8_t v0, w;
    uint32_t i;
    prev_take();
    v0 = s[0];
    w = (uint8_t)(v0 ^ 0x5Au);
    s[DBG_SAVE_OFF] = w;                                    /* the size probe: 4 KB save RAM aliases 0x1000 to 0 */
    if (s[0] == w) {
        s[0] = v0;                                          /* the game's byte back; no debug save */
        on = 0u;
        return;
    }
    on = 1u;
    for (i = DBG_CACHE_AT + 1u + DBG_CACHE_WORDS; i < DBG_WORDS; i++)   /* nothing of an older record or an import stays: */
        DW(i) = 0u;                                         /* the words below are all rewritten by the boot's write and
                                                               the PREV2 and (version 7) cache blocks (version 5: ~230
                                                               fewer stores than the whole-region clear, which pays for
                                                               PREV2's boot cost) */
    dbg_write();
    pos = DBG_P2_AT;                                        /* version 5: DBG_B_PREV2, once (dbg_write steps over it) */
    block(DBG_B_PREV2, p2, DBG_P2_WORDS * 4u);              /* version 7: DBG_B_CACHE right after it (DBG_CACHE_AT) is
                                                               written by board/pocket/s1_cache4b.c s1_cache4b_record
                                                               next, before interrupts open (brd_boot) */
    wheel_arm(WH_TEST, brd_now() + CLK_TIM7);
}

void dbgsave_now(void)
{
    if (on)
        dbg_write();
}

void wh_test(uint32_t due)
{
    uint32_t next = due + CLK_TIM7;
    if (!on)
        return;
    dbg_write();
    while (brd_until(next) <= 0)                            /* periods missed (a long section) merge into one */
        next += CLK_TIM7;
    wheel_arm(WH_TEST, next);
}
#endif
