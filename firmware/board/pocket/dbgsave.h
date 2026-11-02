/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/dbgsave.h - the TEST debug save: the new-core firmware's counters, milestones, freeze telemetry and
 * logs, written into the battery save, where the Pocket writes them to the .sav file our hardware tester (B Jam) sends
 * back (tools/dbgsave.py decodes it).
 *
 * Where: save bytes 0x1000-0x1FFF, the upper half of the 8 KB save (docs/MCU_INTERFACE.md 3.6, docs/STAGE1_PLAN.md
 * question Q1, and the first batch of errata: the TEST debug region of stages 1 and 2, README.md "Terms"). The lower
 * half keeps the 0.2.x layout in those stages: 0x000-0x8FF the game's saves, 0x900-0xFFF 0.2.6's SAT snapshot in TEST
 * builds (legacy/026/mame.c, PPM_SAT_SNAPSHOT); the cart's own format came in stage 3 (docs/ALLOWLIST.md, row B11):
 * from test build S3a on, the FW_S5 images keep the cart's copies in 0x000-0xADF (their TEST no longer
 * writes 0x900: no snapshot) and import a 0.2.x save once (interim/s1/bodies_s1.c). So a 0.2.x 4 KB .sav loads into
 * 0x000-0xFFF as it is, and the upper half holds whatever the RAM held: the boot reads it as the previous session's
 * record if it is one, then clears it. A size probe at the boot (68000 held) turns the debug save off if the save RAM
 * is 4 KB (a write at 0x1000 would land on the game's 0x000).
 * Format (version 6). Older versions hold less: version 5 is the same without the glue's and the audio block's TEST
 * words of version 6, and with DBG_B_PREV2 in its version-5 layout; version 4 is version 5 without DBG_B_PREV2;
 * version 3 also lacks DBG_B_DEC; version 2 also lacks DBG_B_VS and the two DBG_PREV_VS_* words; version 1 also lacks
 * DBG_B_PREV. The words are 32-bit little-endian as the MCU
 * stores them (the .sav swaps the bytes of each 16-bit half); blocks, each a header word (id << 16 | words) then its
 * words, ids DBG_B_* below, the last one DBG_B_END. Every write stays inside the region (dbgsave.c: a static bound and a
 * runtime one). RELEASE builds none of it.
 * Version 5 (2026-10-17): the Pocket's quit restarts the MCU about 0.3 s before the save is read (B Jam's two saves
 * from the RTL sprite-decoder test build: the record was a 316.704 ms boot both times), and every reset clears the RTL
 * decoder's slots 18-22 and
 * the MCU's counters, so DBG_B_PREV's summary was all that survived of a session. DBG_B_PREV2 carries the previous
 * session's lateness counters too, and the worst of them over every session chained since (DBG_P2_* below).
 * Version 6 (2026-10-19): (1) the CPU MATE glue block's late_seen is retired (it counted every publish while the stub's
 * sticky LATE flag was up: in a long hardware play test by B Jam, 31,629 of 36,904 calls); three TEST words follow
 * cycles_max: late (the answers armed after the original's instant, the flag cleared just before each ARM), late_max
 * (sub cycles) and short_calls (buddy/s1_glue.h); a late answer is no lateness sign any more (expected since an earlier
 * scheduler change). (2) The
 * audio block carries the album's state after its five counters (interim/s1/s1_interim.h alb_*: the MD+ result word,
 * the command word the adapter took, XLINK's CDDA underruns and ring writes lost, the last album call and play request,
 * how long a requested track has waited with playing 0), refreshed at every write (B Jam heard no Blue Bar street
 * music in that test). DBG_B_PREV2 carries them across the quit in its version-6 layout; the chain is carried from a
 * version-6 record only (a version-4 or -5 record gives part 1 and starts the chain again). The record is then 1,024
 * words, the whole region.
 * Version 7 (2026-10-21, test build 4a, the first sound-cache build): DBG_B_CACHE after DBG_B_PREV2, the sound-cache
 * probe (board/pocket/s1_cache4a.h, MCU interface v1.3 21.1): the number of probe boots the chain of records has seen,
 * this boot's entry,
 * then the previous DBG_C4A_HIST boots' entries (newest first) carried from the old record, so the .sav read after a
 * Quit (whose reboot is a warm boot that touches nothing) still holds the session's check. Written once at the boot,
 * like PREV2 (constant for the session), by the probe's module (s1_cache4a_record, right after dbgsave_start: the
 * periodic write steps over it). It is carried from a version-7 record only (its layout); DBG_B_PREV2's layout
 * is version 6's, so its chain is carried from a version-6 or -7 record. To make room the ordered audio-call log keeps
 * S1_AU_LOG = 128 calls (was 256; TEST only, interim/s1: it leaves with the album path for the synth). Record: 978 of
 * 1,024 words.
 * Version 8 (2026-10-22, test build 4b, the boot overlay): DBG_B_CACHE holds the boot cache's record instead of the
 * probe's (board/ pocket/s1_cache4b.h, boot/c4b.h c4b_rec_t: what this boot found and did, the bank's CRC-32, the
 * check, the unpack, the times): the boots the chain has counted, this boot's entry, the previous DBG_CACHE_HIST boots'
 * (newest first, carried from a version-8 record only). Same place and size (81 words: 5 entries of 16 instead of 8 of
 * 10), so every other block is version 7's; PREV2's chain is carried from a version-6, -7 or -8 record.
 * Version 9 (test build 5, the synth build; the FW_S5 images only, the other s1 images stay version 8): the interim
 * audio is gone, so DBG_B_AUDIO and the audio-call log DBG_B_AULOG are too (DBG_B_INTERIM, the 0.2.6 sprite bodies'
 * counters, stays);
 * DBG_B_SYNTH takes DBG_B_AUDIO's place in the
 * write order (DBG_SY_* below: the synth's DIAG totals, the counts behind its TEST assertions A1-A3
 * (core/sched/sched.h s5_test_stats_t) and which of them failed, the synth's registers at the write, the main-loop pass
 * counts). DBG_B_PREV2 keeps version 8's layout, its seven audio words carrying the synth's instead (DBG_P2_SY_*
 * below), so a Quit (whose warm reboot rewrites the record) still shows the session's assertions; its chain is carried
 * from a version-9 record only (a version-8 record's audio words mean another thing: the chain starts again).
 * DBG_B_CACHE as version 8 (also carried from a version-8 record: the same layout).
 * Version 10 (the FW_S5 TEST images from test build S3a on; core/trace/tdiag.h TDIAG_LEAN): the record is cut to
 * the lateness signs, the freeze telemetry and the CPU MATE counters (below), carried across the Quit's reboot as
 * before; no image builds version 9 any more (tools/dbgsave.py still reads it, and every older one). */
#ifndef BOARD_POCKET_DBGSAVE_H
#define BOARD_POCKET_DBGSAVE_H

#include <stdint.h>
#include "tdiag.h"

#define DBG_SAVE_OFF            0x1000u
#define DBG_SAVE_BYTES          0x1000u
#define DBG_MAGIC               0x42443153u     /* "S1DB" as the MCU stores it */
#if TDIAG_LEAN
#define DBG_VERSION             10u             /* test build S3a on: the FW_S5 TEST record (version 10,
                                                   below) */
#else
#define DBG_VERSION             8u              /* the other s1 TEST images */
#endif

enum {
    DBG_B_HEAD = 1,     /* magic, version, writes, board time, mcycle, BRD_CLK_HZ, total words, flags */
    DBG_B_BOOT,         /* the crt0 / boot record (board/pocket/s1_boot.h) */
    DBG_B_STATS,        /* core/sched/stats.h st_stats */
    DBG_B_SCHED,        /* core/sched/sched.h sched_stats */
    DBG_B_WDOG,         /* core/wdog/wdog.h wdog_stats: ticks = the MCU heartbeat */
    DBG_B_FATAL,        /* core/trace/fatal.h fatal_rec */
    DBG_B_GLUE,         /* buddy/s1_glue.h s1_glue_stats */
    DBG_B_AUDIO,        /* interim/s1 s1_audio_stats */
    DBG_B_DISP,         /* the dispatcher's TEST counters and state (dbgsave.c) */
    DBG_B_STACK,        /* the stack high-water (bytes) and whether the floor word is intact */
    DBG_B_INTERIM,      /* interim/s1 s1_interim_stats */
    DBG_B_AULOG,        /* the ordered audio-call log: n, then the ring */
    DBG_B_ORACLE,       /* the register-write oracle log: n, then the ring */
    DBG_B_PREV,         /* version 2: the previous session's record as this boot found it (DBG_PREV_* below) */
    DBG_B_VS,           /* version 3: the VDP's vertical syncs (MCU interface v1.1 VSCNT, brd_vs_count): the count since
                           the boot extended to 32 bits, the last 16-bit reading, and the board time it last moved. Beside
                           the MCU heartbeat (DBG_B_WDOG ticks) and the 9494 count (DBG_B_STATS), it tells a dead VDP
                           (no vertical sync) from a dead 68000 (vertical syncs, no 9494) */
    DBG_B_DEC,          /* version 4: the RTL sprite decoder's TEST read-backs (MCU interface v1.2, FPGAIO slots 18-22):
                           DEC_STAT, DEC_WORDS, DEC_TIME, DEC_MARGIN, DEC_LATECNT at the write */
    DBG_B_PREV2,        /* version 5: the previous session's lateness counters as this boot found them, and their worst
                           over the chained sessions (DBG_P2_* below); written once at the boot (constant for the
                           session: the later writes step over it) */
    DBG_B_CACHE,        /* version 7 (test build 4a, the cache probe), version 8 (test build 4b, the overlay): the boot
                           cache: boots seen, this boot's record, the previous DBG_CACHE_HIST boots' (c4b_rec_t each,
                           board/pocket/boot/c4b.h); written once at the boot right after DBG_B_PREV2, by
                           s1_cache4b_record */
    DBG_B_SYNTH,        /* version 9 (test build 5): the synth and its TEST assertions (DBG_SY_* below), every write */
    DBG_B_END = 0xFFFF
};
#define DBG_CACHE_HIST          4u      /* DBG_B_CACHE: the previous boots carried (5 entries with this boot's) */
#define DBG_CACHE_ENTRY_WORDS   16u     /* == C4B_REC_WORDS (dbgsave.c asserts it) */
#define DBG_CACHE_WORDS         (1u + DBG_CACHE_ENTRY_WORDS * (1u + DBG_CACHE_HIST))   /* 81, as version 7's */

/* DBG_B_SYNTH (version 9): words, in order. DIAG counts are totals since the boot (core/dispatch/disp.c s5_diag_acc
   plus what the register holds since its last fold); the assertions: A1 WBUSY <= DONE_WBUSY + JOB_WBUSY ("no non-DONE
   write while RUN", except the stores of the module-start item and of C6's two engine call items, song_c6_init /
   song_c6_ready: the module starts + C6 items, the chip's preemptible engine items, done as the chip does them;
   JOB_WBUSY counts their stores apart as a diagnostic, in no failed bit and not in the lateness sign), A2 UNDERRUN <=
   DT_STARTS, A3 TIMEOUTS = 0 (sched.h s5_test_stats_t) */
enum {
    DBG_SY_INCOMPLETE = 0,      /* DIAG totals: DT halves incomplete, instants on TIMEOUT, MCU writes while RUN, DT */
    DBG_SY_TIMEOUTS,            /* playback reads not served by their sample (MCU_INTERFACE v1.3 3.10.1) */
    DBG_SY_WBUSY,
    DBG_SY_UNDERRUN,
    DBG_SY_DONE_FREE,           /* DONE stores with no hold-off before them */
    DBG_SY_DONE_WBUSY,          /* the WBUSY those stores added (DIAG read just before and after each): A1's legal */
    DBG_SY_DT_STARTS,           /* CONFIG writes with MODE = DT (A2's bound) */
    DBG_SY_JOBS,                /* items with no arrival (module starts + C6 items: the 8C's module starts and C6's
                                   two engine items a boot) and those a block started during */
    DBG_SY_OVERLAPS,
    DBG_SY_JOB_WBUSY,           /* the WBUSY the stores of the module starts + C6 items added (a diagnostic, excused
                                   from A1 by a project decision) */
    DBG_SY_FAILS,               /* bit 0 A1 failed, bit 1 A2, bit 2 A3 (DBG_SY_FAIL_*) */
    DBG_SY_DIAG_DEFER,          /* DIAG clears put off / forced (disp.c) */
    DBG_SY_DIAG_FORCED,
    DBG_SY_Q_MAX,               /* the engine queue's deepest (core/song song_q_max) */
    DBG_SY_C6_HOLD,             /* core/dispatch jobs.c c6_hold_test: C6's case, end, the VS starts when its set-up ended */
    DBG_SY_T_CONFIG,            /* the board time of this boot's first CONFIG write (0: none yet) */
    DBG_SY_CONFIG,              /* the synth's registers at the write: CONFIG, STATUS, FLAGS, SEQ, DTOUT, SCHED */
    DBG_SY_STATUS,
    DBG_SY_FLAGS,
    DBG_SY_SEQ,
    DBG_SY_DTOUT,
    DBG_SY_SCHED,
    DBG_SY_PASS,                /* core/sched s5_pass_stats_t, 8 words: blk, item, bracket, tail, skip_job, skip_same, post,
                                   retry */
    DBG_SY_WORDS = DBG_SY_PASS + 8
};
#define DBG_SY_FAIL_A1          1u
#define DBG_SY_FAIL_A2          2u
#define DBG_SY_FAIL_A3          4u

/* DBG_B_PREV: what the boot found in the region before clearing it. A Soft Reset after a freeze or a fatal halt starts
   a new session whose first write would otherwise overwrite the record of the one that stopped. */
enum {
    DBG_PREV_STATE = 0,         /* 0 no record (a blank save, a 0.2.x 4 KB import, a RELEASE session), 1-7 a record
                                   of that version, 0xFFFFFFFF a record of a version this image cannot read */
    DBG_PREV_WRITES,            /* its head: writes, board time and mcycle at its last write */
    DBG_PREV_NOW,
    DBG_PREV_MCYCLE,
    DBG_PREV_BOOT_CODE,         /* its boot record: the last milestone and its time */
    DBG_PREV_BOOT_TIME,
    DBG_PREV_HEARTBEAT,         /* wdog_stats.ticks: the MCU heartbeat */
    DBG_PREV_GATED,             /* wdog_stats.gated: TIM7 ticks with the Pocket menu open */
    DBG_PREV_N9494,             /* st_stats: the frame ticks (the 68000 alive), the last one, the last post */
    DBG_PREV_T9494,
    DBG_PREV_TPOST,
    DBG_PREV_LASTWORD,
    DBG_PREV_EXC,               /* sched_stats: exceptions, the first one's cause and pc */
    DBG_PREV_EXC_CAUSE,
    DBG_PREV_EXC_EPC,
    DBG_PREV_FATAL_AGE,         /* the latest fatal halt among the sessions before this one: 0 none, 1 the previous
                                   session, n carried from n sessions back (until a newer halt replaces it) */
    DBG_PREV_FATAL_CODE,        /* its fatal_rec: code, a, b, board time, polls */
    DBG_PREV_FATAL_A,
    DBG_PREV_FATAL_B,
    DBG_PREV_FATAL_TIME,
    DBG_PREV_FATAL_POLLS,
    DBG_PREV_VS_COUNT,          /* version 3: its DBG_B_VS count and the board time the count last moved (0 when the
                                   previous record is version 1 or 2) */
    DBG_PREV_T_VS,
    DBG_PREV_WORDS
};

/* DBG_B_PREV2 (version 5; this layout version 6): read by the boot from the previous record's blocks, at this image's
   offsets (a record of version 4, 5 or 6: the same block layouts up to the words version 6 appended, which read 0 from
   an older record). Part 1 = the previous session's own values at its last write; part 2 = the
   CHAIN: the worst of part 1 over every session folded since the chain began. Each boot folds the session before it:
   the decoder flags ORed, every other word an unsigned maximum of a form in which larger is worse (the margin stored
   as margin ^ 0x7FFFFFFF, so the maximum is the smallest margin and 0 none; the stack floor as 1 = overwritten), so
   every chain word starts at 0. A quit (it restarts the MCU) and quick relaunches after a session therefore keep that
   session's worst values in every later record. The chain begins at the first boot that finds a version-4 or -5 record
   (or a version-6 one with no chain), and starts again when the region holds no record this image can read (a blank
   save, a 0.2.x import, a record before version 4 or of a later version); DBG_P2_BOOTS says how many sessions it holds
   and DBG_P2_DIRTY_AGE which one last showed a lateness sign. */
enum {
    DBG_P2_STATE = 0,           /* 0 no previous record; 4-7 the record's version (the values below are carried);
                                   1-3 a record before version 4, 0xFFFFFFFF one of a version this image cannot read
                                   (nothing carried) */
    DBG_P2_DEC_STAT,            /* its DBG_B_DEC: DEC_STAT (flags in bits 16-21), DEC_MARGIN, DEC_LATECNT */
    DBG_P2_DEC_MARGIN,
    DBG_P2_DEC_LATECNT,
    DBG_P2_LATE,                /* its DBG_B_GLUE (CPU MATE): late (version 6: the answers armed late; 0 from an older
                                   record, whose late_seen is not carried), discarded, aborted, abort_landings,
                                   cycles_max */
    DBG_P2_DISCARDED,
    DBG_P2_ABORTED,
    DBG_P2_ABORT_LANDINGS,
    DBG_P2_CYCLES_MAX,
    DBG_P2_CATCHUPS,            /* its DBG_B_AUDIO: the SFX feeder's catch-ups (ticks late by a period or more; the
                                   firmware counts no FIFO underrun: the feeder never reads the empty bit) */
    DBG_P2_EXC,                 /* its DBG_B_SCHED: exceptions */
    DBG_P2_REFUSALS,            /* its DBG_B_DISP: refusals, failed jobs */
    DBG_P2_JOBS_FAILED,
    DBG_P2_STACK_HW,            /* its DBG_B_STACK: the high-water (bytes), the floor word intact */
    DBG_P2_FLOOR_OK,
    DBG_P2_LATE_MAX,            /* version 6: its glue late_max; its audio block's alb_wait_max */
    DBG_P2_ALB_WAIT_MAX,
    DBG_P2_DEC_WORDS,           /* context, not folded: DEC_WORDS, DEC_TIME, the CPU MATE calls, the first exception */
    DBG_P2_DEC_TIME,
    DBG_P2_CALLS,
    DBG_P2_EXC_CAUSE,
    DBG_P2_EXC_EPC,
    DBG_P2_EXC_TVAL,
    DBG_P2_SHORT_CALLS,         /* version 6, context: its glue short_calls; its album state at its last write (alb_res,
                                   alb_xl14, alb_xl18, alb_calls, alb_wait; XLINK's CRAM counters count from the
                                   power-on, so a later record holds them anyway: not folded) */
    DBG_P2_ALB_RES,
    DBG_P2_ALB_UNDER,
    DBG_P2_ALB_LOST,
    DBG_P2_ALB_CALLS,
    DBG_P2_ALB_WAIT,
    DBG_P2_BOOTS,               /* the chain: the sessions folded into it (0 = no chain) */
    DBG_P2_DIRTY_AGE,           /* the newest session in the chain with a lateness sign (below): 0 none, 1 the
                                   previous session, n the one n sessions back */
    DBG_P2_W_BASE               /* the chain's worst of part 1: word DBG_P2_W(k) for k = DBG_P2_DEC_STAT .. ALB_WAIT_MAX:
                                   the flags ORed (DBG_DEC_FLAGS), the margin ^ DBG_P2_MARGIN_X, the floor as 1 =
                                   overwritten (FLOOR_OK ^ 1), the rest as they are; all but the flags folded by max */
};
#define DBG_P2_W(k)             (DBG_P2_W_BASE - DBG_P2_DEC_STAT + (k))
/* version 9 (test build 5): the audio block's seven words of PREV2 carry the synth's (DBG_B_SYNTH): TIMEOUTS and the
   failed assertions (FAILS, 0-7) in the two folded slots (their chain forms: larger = worse; both also count in the
   lateness sign), the rest as context (DONE_WBUSY in version 8's ALB_UNDER: A1's inputs WBUSY, DONE_WBUSY, JOB_WBUSY
   all kept) */
#define DBG_P2_SY_TIMEOUTS      DBG_P2_CATCHUPS
#define DBG_P2_SY_FAILS         DBG_P2_ALB_WAIT_MAX
#define DBG_P2_SY_WBUSY         DBG_P2_ALB_RES
#define DBG_P2_SY_DONE_WBUSY    DBG_P2_ALB_UNDER
#define DBG_P2_SY_UNDERRUN      DBG_P2_ALB_LOST
#define DBG_P2_SY_DT_STARTS     DBG_P2_ALB_CALLS
#define DBG_P2_SY_JOB_WBUSY     DBG_P2_ALB_WAIT
#define DBG_P2_WORDS            DBG_P2_W(DBG_P2_ALB_WAIT_MAX + 1)
#define DBG_P2_MARGIN_X         0x7FFFFFFFu     /* DEC_MARGIN's chain form: signed order reversed onto unsigned, the
                                                   "none" value 0x7FFFFFFF onto 0 */
#define DBG_DEC_FLAGS           0x003F0000u     /* DEC_STAT bits 16-21: OVF, BADTYPE, D0, PRE, LATE, ABORT (ORed) */
#define DBG_DEC_BAD             0x001F0000u     /* the flags of the lateness sign: OVF, BADTYPE, D0, PRE, LATE */
/* the lateness sign of a session (DBG_P2_DIRTY_AGE): what the criteria of the long play test (the soak) want 0 - a
   window word served before its block was decoded (LATECNT), an OVF / BADTYPE / D0 / PRE / LATE flag, an exception,
   the stack floor overwritten. ABORT, the margin and (version 6) the CPU MATE answers armed late are reported, not
   counted: a late ARM is expected since an earlier scheduler change and harmful only if the game reads first. */

/* ---- version 10 (the FW_S5 TEST images from test build S3a on, core/trace/tdiag.h TDIAG_LEAN) ------------------
   The record keeps only what has caught problems on hardware: the lateness signs, the freeze telemetry and the CPU
   MATE counters. Blocks in write order (ids as above, layouts of version 10):
     DBG_B_HEAD   8: magic, version 10, writes, board time, mcycle, BRD_CLK_HZ, total words, 0
     DBG_B_STATS  4: the frame ticks (the 68000 alive), the last one's board time, the last post's board time, its word
     DBG_B_SCHED  4: exceptions, the first one's cause, epc, tval
     DBG_B_WDOG   1: the MCU heartbeat (TIM7 ticks)
     DBG_B_FATAL  5: the fatal halt: code (0 none), a, b, board time, 0
     DBG_B_GLUE   4: CPU MATE (DBG_GL_*): discarded, aborted, the answers armed late, the longest call (cycles, wall time)
     DBG_B_SYNTH  1: the synth's TIMEOUTs (DIAG total since the boot)
     DBG_B_DISP   2: refusals, failed jobs
     DBG_B_STACK  2: the stack high-water (bytes), whether the floor word is intact
     DBG_B_PREV   DBG_PV_WORDS: the previous session's record as this boot found it (DBG_PV_* below)
     DBG_B_VS     3: the VDP's vertical syncs since the boot (32 bits), the last 16-bit reading, the board time it moved
     DBG_B_DEC    5: the RTL sprite decoder's DEC_STAT, DEC_WORDS, DEC_TIME, DEC_MARGIN, DEC_LATECNT at the write
     DBG_B_PREV2  DBG_Q_WORDS: the previous session's lateness signs and CPU MATE counters, and their worst over the
                  chained sessions (DBG_Q_* below); written once at the boot
     DBG_B_END
   PREV and PREV2 are carried from a version-10 record only; a record of another version (the version 9 of test build
   S2, or the version 8 of the other s1 TEST images, above) is named in their STATE word and the chain starts again.
   Which side stopped: the record's last write shows
   the MCU running (it wrote it), the frame ticks the 68000, the VS count the VDP; a fatal halt writes the record at
   once. The lateness sign (DBG_Q_DIRTY_AGE): a decoder LATECNT or OVF / BADTYPE / D0 / PRE / LATE flag, a TIMEOUT, an
   exception, the stack floor overwritten; refusals, failed jobs, ABORT, the margin and the CPU MATE counters are
   reported, not counted. */
#define DBG_SC_WORDS            4u      /* DBG_B_SCHED: sched_stats exc .. exc_first_tval */
#define DBG_DEC_WORDS           5u      /* DBG_B_DEC: FPGAIO slots 18-22 */
enum { DBG_GL_DISCARDED = 0, DBG_GL_ABORTED, DBG_GL_LATE, DBG_GL_CYCLES_MAX, DBG_GL_WORDS };
enum {
    DBG_PV_STATE = 0,           /* 0 no record; 10 a version-10 record (the words below carried); another value: that
                                   record's version, nothing carried */
    DBG_PV_WRITES,              /* its head: writes, board time at its last write */
    DBG_PV_NOW,
    DBG_PV_HEARTBEAT,           /* the MCU heartbeat */
    DBG_PV_N9494,               /* the frame ticks, the last one's time, the last post's time and word */
    DBG_PV_T9494,
    DBG_PV_TPOST,
    DBG_PV_LASTWORD,
    DBG_PV_EXC,                 /* exceptions, the first one's cause and epc */
    DBG_PV_EXC_CAUSE,
    DBG_PV_EXC_EPC,
    DBG_PV_FATAL_AGE,           /* the latest fatal halt among the sessions before this one: 0 none, 1 the previous
                                   session, n carried from n sessions back */
    DBG_PV_FATAL_CODE,          /* its code, a, b, board time */
    DBG_PV_FATAL_A,
    DBG_PV_FATAL_B,
    DBG_PV_FATAL_TIME,
    DBG_PV_VS_COUNT,            /* its VS count and the time the count last moved */
    DBG_PV_T_VS,
    DBG_PV_WORDS
};
enum {
    DBG_Q_STATE = 0,            /* as DBG_PV_STATE */
    DBG_Q_DEC_STAT,             /* part 1, folded into the chain (larger = worse): the decoder's flags, margin, LATECNT */
    DBG_Q_DEC_MARGIN,
    DBG_Q_DEC_LATECNT,
    DBG_Q_TIMEOUTS,             /* the synth's TIMEOUTs */
    DBG_Q_EXC,                  /* exceptions */
    DBG_Q_FLOOR_OK,             /* the stack floor intact, the high-water */
    DBG_Q_STACK_HW,
    DBG_Q_REFUSALS,             /* refusals, failed jobs */
    DBG_Q_JOBS_FAILED,
    DBG_Q_DISCARDED,            /* CPU MATE: discarded, aborted, armed late, the longest call */
    DBG_Q_ABORTED,
    DBG_Q_LATE,
    DBG_Q_CYCLES_MAX,
    DBG_Q_DEC_WORDS,            /* context, not folded: DEC_WORDS, DEC_TIME, the first exception */
    DBG_Q_DEC_TIME,
    DBG_Q_EXC_CAUSE,
    DBG_Q_EXC_EPC,
    DBG_Q_EXC_TVAL,
    DBG_Q_BOOTS,                /* the chain: the sessions folded into it (0 = no chain) */
    DBG_Q_DIRTY_AGE,            /* the newest session in it with a lateness sign: 0 none, 1 the previous, n back */
    DBG_Q_W_BASE                /* the chain's worst of DBG_Q_DEC_STAT .. DBG_Q_CYCLES_MAX: the flags ORed, the margin
                                   ^ DBG_P2_MARGIN_X, the floor as 1 = overwritten, the rest as they are */
};
#define DBG_Q_W(k)              (DBG_Q_W_BASE - DBG_Q_DEC_STAT + (k))
#define DBG_Q_WORDS             DBG_Q_W(DBG_Q_CYCLES_MAX + 1)

void dbgsave_start(void);       /* the board boot (68000 held): the old record kept as PREV and PREV2, the size probe,
                                   the region cleared, the first write, the period */
void dbgsave_now(void);         /* write the record now (the fatal halt: interrupts stay off for good, so the wheel's
                                   write never comes again; board/pocket/s1_board.c brd_milestone) */

#endif
