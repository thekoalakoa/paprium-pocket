/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* buddy/s1_glue.c - the CPU MATE glue on the new firmware's levels (FW_S1; the plan: docs/STAGE1_PLAN.md, work item
 * W8; the interface: docs/MCU_INTERFACE.md sections 4.2 and 6). The levels are the scheduler's (core/sched/sched.h):
 * L1 the mailbox interrupt, L2a the timer wheel, L2b / L2c the song tick and the jobs, the thread (L3) the time left.
 * XLINK = the core's register block with the Mega CD link stub's registers; SFX = sound effects; VU = the Boom Box
 * level meter rows; MTIME = the RISC-V machine timer; FW_S5 = the images with our own song engine.
 *
 * The brain, its counting helpers (cf.bin), its image tables and its data stay where 0.2.6 put them, byte for byte
 * (LAYOUT.md "What never moves"; tests/check_images.py s1), and it is called through the same wrapper
 * (buddy/zz_buddy_trap.c buddy_call_brain: H2, then H1, the word in a0) with the same inputs (the counter's Wf = 0, the
 * restart flag raised once after a release). What changes is who calls it and when (0.2.6: zz_buddy.c buddy_event from
 * the main loop's slow path, the trap switched to buddy_trap for the call):
 *   - SEND: XLINK's post count raises CAUSE.S; L1 acknowledges it and posts the brain (core/sched sched_brain_post);
 *     the thread calls l3_brain when nothing of the game's is left (B Jam's decision of 2026-10-15: the CPU MATE, which
 *     the game does not use all the time, must not slow the rest down), and l3_brain runs the call when the glue is
 *     ready (rule 6.3.2: S is acknowledged before the answer is published). The call runs with every interrupt open:
 *     posts (L1), the timer wheel (L2a: the SFX feeder, the VU rows, the watchdog, the FW_S5 images' urgent tick), the
 *     decoder stand-in and the jobs (L2b / L2c) all preempt it, as 0.2.6's buddy_isr_post / buddy_isr_tick did for
 *     the first two (earlier versions ran the call above the decoder and the jobs and held the SFX feeder for it);
 *   - the abort (rule 2 of the 0.2.6 glue: a restart (SRES 0) or AI off (SBRQ 1) while the call runs resets it): L1
 *     and L2a poll XLINK LSTAT while a call is in flight (brain_poll) and raise s1_brain_abort; the trap entry's
 *     exit then sends the level that interrupted the call itself (its mepc in the brain, its helpers or the wrapper)
 *     to buddy_abort_land (s1_brain_resume), never a level nested deeper; an exception in that code aborts the call
 *     and turns the buddy off (brain_fault, as 0.2.6's buddy_exc_brain);
 *   - housekeeping (the first-event init, the restart / release / Word RAM pattern restore, AI off, LATE, option D):
 *     the thread's idle (l3_idle), sliced as 0.2.6's main loop sliced it, gated on the same LSTAT bits (send pending,
 *     AI off); a send that could not run when it came is posted again here once it can;
 *   - no MTIME: the glue keeps no time base (the SFX feeder and the VU rows are interim/s1/audio_s1.c on the wheel).
 * State: .bss_upper (wram_upper, cleared by the new firmware's crt0 at every boot: the 0.2.6 "first event since this
 * MCU boot" test on MTIME_HI is not needed). Where a part does what the 0.2.6 glue (zz_buddy.c) does, its comment
 * says "as 0.2.6's ...". */
#include <stdint.h>
#include "board.h"
#include "sched.h"
#include "sched_hooks.h"
#include "buddy.h"
#include "s1_glue.h"
#include "tdiag.h"

#if !BUDDY_LINKED_BRAIN
#error "the stage-1 glue calls the brain linked into block RAM (fwbuild.json: -DBUDDY_LINKED_BRAIN=1)"
#endif

#define UPPER                   __attribute__((section(".bss_upper")))
#define REG32(a)                (*(volatile uint32_t *)(uintptr_t)(a))
#define REG16(a)                (*(volatile uint16_t *)(uintptr_t)(a))
#define XL(off)                 REG32(BUD_XLINK_BASE + (off))

/* zz_buddy_trap.c (the 0.2.6 wrapper, unchanged) and zz_buddy_brain.c (the entry table, the code-window labels) */
extern uint32_t buddy_call_brain(uint32_t h2, uint32_t h1, uint32_t *word);
extern void buddy_abort_land(void);
extern volatile uint32_t buddy_jmp_sp;
extern volatile uint32_t buddy_abort_req;
extern const BudEntry buddy_linked_entry;
extern char buddy_cf_lo[], buddy_cf_hi[];

enum { ST_NEW = 0, ST_DISABLED, ST_READY };

static UPPER struct {
    uint32_t state;
    uint8_t restart_pending;            /* restart seen, waiting for the release (SRES = 1, SBRQ = 0) */
    uint8_t restore_pending;            /* release seen: the Word RAM pattern still being written */
    uint8_t brain_flag_pending;         /* raise the brain's restart flag before the next call */
    uint8_t disabled_once;
    uint32_t rs_rec, rs_pos;            /* restore record / halfword position */
} bud;

UPPER s1_glue_stats_t s1_glue_stats;

#if PPM_RELEASE
#define GS(f)                   ((void)0)
#elif TDIAG_LEAN                /* the lean TEST images (test build S3a on;
                                   core/trace/tdiag.h): of the counters, discarded and aborted only */
#define GS(f)                   GS_##f
#define GS_discarded            (s1_glue_stats.discarded++)
#define GS_aborted              (s1_glue_stats.aborted++)
#define GS_abort_landings       ((void)0)
#define GS_aioffs               ((void)0)
#define GS_arm_lost             ((void)0)
#define GS_calls                ((void)0)
#define GS_dbusy_fixed          ((void)0)
#define GS_deferred             ((void)0)
#define GS_events               ((void)0)
#define GS_exc_brain            ((void)0)
#define GS_ignored_halted       ((void)0)
#define GS_ignored_notready     ((void)0)
#define GS_inits                ((void)0)
#define GS_published            ((void)0)
#define GS_rearms               ((void)0)
#define GS_releases             ((void)0)
#define GS_restarts             ((void)0)
#define GS_restores_done        ((void)0)
#define GS_sends                ((void)0)
#else
#define GS(f)                   (s1_glue_stats.f++)
#endif

/* ---- boot (rule 6.3.1) --------------------------------------------------------------------------------------- */
void buddy_s1_boot(void)
{
    buddy_jmp_sp = 0u;                                  /* .noinit (the 0.2.6 wrapper's): stale after a restart */
    buddy_abort_req = 0u;
    s1_brain_abort = 0u;
    XL(XL_LCLR) = LS_SEND | LS_LATE;                    /* the send / late flags of before this boot */
}

/* ---- the sliced boot-time work ------------------------------------------------------------------------------- */
/* the sub-CPU init's Word RAM pattern into the SRAM mirror, then the captured sub tables, BUDDY_SLICE_WORDS a slice
   (as 0.2.6's zz_buddy.c restore_slice) */
static void restore_slice(void)
{
    const BudEntry *e = &buddy_linked_entry;
    uint32_t left = BUDDY_SLICE_WORDS;
    while (left) {
        if (bud.rs_rec >= e->nrestore + e->ncopy) {
            bud.restore_pending = 0u;
            GS(restores_done);
            if (e->t16_key)
                REG32(e->t16_key) = 0u;                 /* the T16 table is rebuilt after every release */
            return;
        }
        if (bud.rs_rec >= e->nrestore) {                /* the copy records, halfwords */
            uint32_t k = bud.rs_rec - e->nrestore, pos = bud.rs_pos, bytes = e->copy[k].bytes;
            uint32_t s = e->copy[k].src, d = e->copy[k].dst;
            for (; left && pos < bytes; left--, pos += 2u)
                REG16(d + pos) = REG16(s + pos);
            if (pos >= bytes) {
                bud.rs_rec++;
                pos = 0u;
            }
            bud.rs_pos = pos;
            continue;
        }
        {
            uint32_t a = e->restore[bud.rs_rec].addr, bytes = e->restore[bud.rs_rec].bytes;
            uint32_t f = e->restore[bud.rs_rec].fill16 & 0xFFFFu, pos = bud.rs_pos;
            uint32_t w = f | (f << 16);                 /* two 68000 words per SRAM long (16-bit native) */
            for (; left && pos + 4u <= bytes; left--, pos += 4u)
                REG32(a + pos) = w;
            if (left && pos < bytes) {
                REG16(a + pos) = (uint16_t)f;
                pos += 2u;
                left--;
            }
            if (pos >= bytes) {
                bud.rs_rec++;
                pos = 0u;
            }
            bud.rs_pos = pos;
        }
    }
}

/* An image built without the brain (tools/fwbuild.py, a "nobrain" variant: the images committed to the RTL tree) has
   zeros in the brain's place, and nothing else differs. Zero is no RV32 instruction (the defined illegal one), so the
   two entry words tell; the glue then acts as 0.2.6's BUDDY_NO_BRAIN build did: disabled at its first event, the link
   keeps the stub's answers (BUSY 0, COMSTAT2 0) and the CPU MATE gets no input from the cart. */
static uint32_t brain_present(void)
{
    return REG32(buddy_linked_entry.h1) != 0u && REG32(buddy_linked_entry.h2) != 0u;
}

static void buddy_init(void)                        /* as 0.2.6's zz_buddy.c buddy_init, the linked-brain branch */
{
    GS(inits);
    if (XL(XL_ID) != XLINK_ID_STAGE2 || !brain_present()) {
        bud.state = ST_DISABLED;
        return;
    }
    XL(XL_XCFG) = XL(XL_XCFG) | XCFG_LOCK;              /* the SRAM image below 0x10000 protected from stray stores */
    bud.state = ST_READY;
    bud.brain_flag_pending = 1u;                        /* WRAM survives a soft reset: always restart once */
    bud.restart_pending = 1u;                           /* wait for the release before the first call */
}

/* option D on (honest BUSY + COMSTAT2) only once the brain can answer; LCTRL[15:8] = HOLD written back as read */
static void option_d(uint32_t on)
{
    uint32_t v = XL(XL_LCTRL);
    XL(XL_LCTRL) = (v & 0xFF00u) | (on ? 1u : 0u);
}

/* ---- one brain call (the thread, every interrupt open) ------------------------------------------------------- */
#if !PPM_RELEASE
/* TEST: this answer's lateness. publish lowered the stub's sticky LATE flag just before its ARM, so the flag
   in an LSTAT read that shows the ARM taken (ARMED, or BUSY down) is this ARM's own: paprium_mcd_link sets it in the
   ARM's clock when the tick is already at D_WORD or past it, and an event wins over a clear in the same clock. The two
   toggles cross on the same two-flop path in write order, so the clear lands no later than the ARM. TICK freezes at
   the busy release (at once for an ARM past D_BUSY too); before it, the read is a few sub cycles after the ARM.
   TICK counts from the LAST post: a post that lands after the call's (posts0) restarts it, so the reading is kept for
   late_max only when LSTAT's post count read AFTER it is still the call's (posts0, not ls's own count, which may
   already be a newer post's when BUSY is down for another reason). Fixed on 2026-10-19: measured on the RV32 model, a
   post between the LSTAT read and the TICK read gave late_max 16,776,751 = 2^24 - 465, the newer post's tick minus
   D_WORD; GLUE_BUG 3, tests/equiv/tdiag_s1.py's planted variant, leaves the test out). The answer still counts. */
static void late_note(uint32_t ls, uint32_t dw, uint32_t posts0)
{
#if TDIAG_LEAN                                          /* lean TEST (test build S3a on): the late count only */
    (void)dw;
    (void)posts0;
    if (ls & LS_LATE)
        s1_glue_stats.late++;
#else
    if (dw < S1_SHORT_DWORD)
        s1_glue_stats.short_calls++;
    if (ls & LS_LATE) {
        uint32_t by = ((XL(XL_TICK) & 0xFFFFFFu) - dw) & 0xFFFFFFu;
        s1_glue_stats.late++;
#if GLUE_BUG != 3
        if ((XL(XL_LSTAT) >> 16) != posts0)
            return;                                     /* TICK is a newer post's: no lateness from it */
#else
        (void)posts0;
#endif
        if (by > s1_glue_stats.late_max)
            s1_glue_stats.late_max = by;
    }
#endif
}
#endif

static void publish(uint32_t word, uint32_t posts0)  /* as 0.2.6's zz_buddy.c publish */
{
    volatile uint32_t *co = (volatile uint32_t *)(uintptr_t)buddy_linked_entry.cnt_out;
    uint32_t dw = co[1] & 0xFFFFFFu, db = co[2] & 0xFFFFFFu, tries;
    if (db < dw) {
        db = dw;                                        /* D_BUSY >= D_WORD always */
        GS(dbusy_fixed);
    }
    XL(XL_DWORD) = dw;
    XL(XL_DBUSY) = db;
    XL(XL_PEND) = word & 0xFFFFu;
#if !PPM_RELEASE && GLUE_BUG != 1                       /* (GLUE_BUG 1: tdiag_s1.py's negative control; 2, 3 below) */
    XL(XL_LCLR) = LS_LATE;                              /* TEST: the flag down, so the read below shows this ARM's own */
#endif
    XL(XL_ARM) = 1u;
    for (tries = 0; tries < 3u; tries++) {              /* an ARM toggle lost on a clk_md edge: read back, re-send */
        uint32_t ls = 0, r;
        for (r = 0; r < 3u; r++) {
            ls = XL(XL_LSTAT);
            if (ls & LS_ARMED)
                break;
        }
        if ((ls & LS_ARMED) || !(ls & LS_BUSY)) {
#if !PPM_RELEASE
            late_note(ls, dw, posts0);
#endif
            GS(published);
            return;
        }
        if ((ls >> 16) != posts0 || !(ls & LS_SRES) || (ls & LS_SBRQ)) {
#if !PPM_RELEASE && GLUE_BUG != 2
            /* TEST (fixed on 2026-10-19): the flag up here is this ARM's own (only an ARM sets it, and it was cleared
               just before): the ARM was taken late, the busy released (at D_BUSY, or at once past it) and the game
               posted again before this read (publish preempted that long; measured on the RV32 model, seeds 5 / 11: the
               stub 532 / 518 late ARMs, the count 530 / 516 without this). It counts. The answer was delivered but
               stays under 'discarded': an on-time ARM overtaken the same way shows nothing that tells it from a lost
               one. GLUE_BUG 2 (tests/equiv/tdiag_s1.py's planted variant): not counted, as before the fix. */
            if (ls & LS_LATE)
                s1_glue_stats.late++;
#endif
            GS(discarded);
            return;
        }
        GS(rearms);
        XL(XL_ARM) = 1u;
    }
    GS(arm_lost);
}

static void run_call(void)                          /* as 0.2.6's zz_buddy.c run_call, the brain part */
{
    const BudEntry *e = &buddy_linked_entry;
    volatile uint32_t *co = (volatile uint32_t *)(uintptr_t)e->cnt_out;
    uint32_t ls0, ls1, posts0, word = 0u, rc;
#if !PPM_RELEASE
    uint32_t t0 = brd_cycles(), dt;
#endif
    ls0 = XL(XL_LSTAT);
    posts0 = ls0 >> 16;
    if (!(ls0 & LS_SRES) || (ls0 & LS_SBRQ)) {          /* halted or restarted since the post: no call */
        GS(ignored_halted);
        return;
    }
    co[3] = 0u;                                         /* Wf = 0: W lives in the stub's 12.5 MHz tick */
    if (bud.brain_flag_pending) {
        REG16(e->flag) = 1u;                            /* the brain clears its AI block itself (its H2 entry) */
        bud.brain_flag_pending = 0u;
    }
    {
        uint32_t s = brd_irq_save();                    /* an abort asked before the call starts: no call */
        rc = buddy_abort_req;
        s1_brain_abort = 0u;
        brd_irq_restore(s);
    }
    if (!rc)
        rc = buddy_call_brain(e->h2, e->h1, &word);     /* every interrupt stays open (the thread) */
    brd_irq_enable();                                   /* the abort landing leaves MIE off */
    {
        uint32_t s = brd_irq_save();
        buddy_abort_req = 0u;
        s1_brain_abort = 0u;
        brd_irq_restore(s);
    }
#if !PPM_RELEASE
    dt = brd_cycles() - t0;
#if !TDIAG_LEAN                                          /* (lean TEST, test build S3a on: the longest call only) */
    s1_glue_stats.cycles_last = dt;
#endif
    if (dt > s1_glue_stats.cycles_max)
        s1_glue_stats.cycles_max = dt;
#endif
    GS(calls);
    if (rc) {
        GS(aborted);
        if (e->t16_key)
            REG32(e->t16_key) = 0u;                     /* a T16 build cut by the abort must not be kept */
        return;
    }
    ls1 = XL(XL_LSTAT);
    if ((ls1 >> 16) != posts0 || !(ls1 & LS_SRES) || (ls1 & LS_SBRQ) || (ls1 & ~ls0 & (LS_RESTART | LS_AIOFF))) {
        GS(discarded);                                  /* reset / halt / a new post during the call */
        return;
    }
    publish(word, posts0);
}

static uint32_t can_call(uint32_t ls)
{
    return (ls & (LS_SEND | LS_RESTART)) == LS_SEND && bud.state == ST_READY && !bud.restart_pending &&
           !bud.restore_pending;
}

/* the thread (core/sched): a send is pending (CAUSE.S): the call, when the glue can make it */
void l3_brain(void)
{
    uint32_t ls = XL(XL_LSTAT);
    if (!can_call(ls)) {                                /* not now: the thread's housekeeping posts it again */
        GS(deferred);
        return;
    }
    XL(XL_LCLR) = LS_SEND;
    GS(sends);
    run_call();
}

/* L1 and L2a while a call is in flight (core/sched): a restart or AI off resets the call (as 0.2.6's run_must_abort) */
void brain_poll(void)
{
    uint32_t ls = XL(XL_LSTAT);
    if (!(ls & LS_SRES) || (ls & LS_SBRQ)) {
        buddy_abort_req = 1u;
        s1_brain_abort = 1u;
    }
}

/* the code a brain call runs: the brain, its helpers in the code window, the wrapper */
static uint32_t in_call(uint32_t pc)
{
    return (pc >= buddy_linked_entry.code_lo && pc < buddy_linked_entry.code_hi) ||
           (pc >= (uint32_t)(uintptr_t)buddy_cf_lo && pc < (uint32_t)(uintptr_t)buddy_cf_hi) ||
           (pc >= (uint32_t)(uintptr_t)buddy_call_brain && pc < (uint32_t)(uintptr_t)buddy_abort_land);
}

/* the trap entry's exit (board/pocket/s1_trap.S), while s1_brain_abort is set: the level that interrupted the call
   itself returns into buddy_abort_land; a level nested deeper returns as usual (its own exit comes back here) */
uint32_t s1_brain_resume(uint32_t mepc)
{
    if (buddy_jmp_sp && in_call(mepc)) {
        s1_brain_abort = 0u;
        GS(abort_landings);
        return (uint32_t)(uintptr_t)buddy_abort_land;
    }
    return mepc;
}

/* sched_exception: an exception in the call's code aborts it and turns the buddy off (as 0.2.6's buddy_exc_brain) */
uint32_t brain_fault(uint32_t mepc)
{
    if (!buddy_jmp_sp || !in_call(mepc))
        return 0u;
    GS(exc_brain);
    (void)XL(XL_ID);                                    /* absorb a stale xbus ack */
    buddy_abort_req = 1u;
    bud.state = ST_DISABLED;
    return (uint32_t)(uintptr_t)buddy_abort_land;
}

/* ---- the thread's idle housekeeping (0.2.6: buddy_event after the call) ------------------------------------- */
/* One interrupts-off section from the LSTAT read to the LCLR write: the brain call (in L2b in earlier versions, in the
   thread now: the race below stays guarded) preempted the thread, and a
   sub restart or AI off that comes while it runs must not be cleared by a decision made on the LSTAT read before it
   (measured on the RV32 model, with a test bench outside this tree: an AI-off flag set during a call was cleared
   by the thread's stale read). 0.2.6 could not race here: its call ran inside this same routine. A slice is ~16
   SRAM halfwords. */
static void idle_work(void);
void l3_idle(void)
{
    uint32_t s;
    if (!(XL(XL_LSTAT) & (LS_SEND | LS_AIOFF)))         /* the 0.2.6 main loop's test: send pending, AI off */
        return;
    s = brd_irq_save();
    idle_work();
    brd_irq_restore(s);
}

static void idle_work(void)
{
    uint32_t ls = XL(XL_LSTAT), clr = 0u, more;
    if (!(ls & (LS_SEND | LS_AIOFF)))
        return;
    GS(events);
    if (bud.state == ST_NEW)
        buddy_init();
    if (bud.state == ST_DISABLED) {                     /* a plain stub: acknowledge and forget */
        if (!bud.disabled_once) {
            if (XL(XL_ID) == XLINK_ID_STAGE2)
                option_d(0u);                           /* BUSY / COMSTAT2 back to the stub's own answers */
            bud.disabled_once = 1u;
        }
        XL(XL_LCLR) = LS_SEND | LS_RESTART | LS_AIOFF | LS_LATE;
        return;
    }
    if (ls & LS_RESTART) {
        GS(restarts);
        bud.restart_pending = 1u;
        bud.brain_flag_pending = 1u;
        clr |= LS_RESTART;
    }
    if (ls & LS_AIOFF)
        GS(aioffs);
    if (ls & LS_LATE)                                   /* cleared, not counted: publish counts each late answer */
        clr |= LS_LATE;
    if (bud.restart_pending && (ls & LS_SRES) && !(ls & LS_SBRQ)) {   /* the release: the Word RAM pattern now */
        bud.restart_pending = 0u;
        bud.restore_pending = 1u;
        bud.rs_rec = 0u;
        bud.rs_pos = 0u;
        GS(releases);
    }
    more = bud.restore_pending;
    if (more)
        restore_slice();
    if ((ls & LS_SEND) && !(ls & LS_RESTART) && bud.state == ST_READY) {
        if (!bud.restart_pending && !bud.restore_pending)
            sched_brain_post();                         /* a send that waited for this work: the call now */
        else
            GS(ignored_notready);
    }
    if (bud.state == ST_READY && !(XL(XL_LCTRL) & 1u))
        option_d(1u);
    if (!more && !bud.restart_pending && !(ls & LS_SBRQ))
        clr |= LS_AIOFF;                                /* AI off stays held while boot work remains or halted */
    if (clr)
        XL(XL_LCLR) = clr;
}
