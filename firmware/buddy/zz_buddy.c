/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * zz_buddy.c - the hook-free CPU MATE buddy glue (option D). See buddy.h for the design summary.
 * First written for a 0.2.6 test firmware, in a research build outside this tree. "Shipping" and "today" here mean
 * the 0.2.6 firmware without this glue. MCU = the cart's microcontroller (the NEORV32 in our core); SFX = sound
 * effects; VU = the Boom Box level meter rows; ISR = interrupt service routine; MTIME = the RISC-V machine timer.
 *
 * The file name sorts after every shipping source, and every variable here lives in .noinit.zz_buddy (not cleared
 * by crt0, placed after .bss), so the shipping objects keep their link order, every shipping variable keeps its
 * address and crt0 runs the same loops (a check script of the 0.2.6 work, outside this tree, proved it per build).
 *
 * Needs from the shipping objects (no source change): ppm_cmd_handler, sfx_player_update, ppm_music_vu_update
 * (global), sfx_chan[], ppm_sfx_base_addr, ppmio (global), and vu_due / vu_on, which are static in paprium.c:
 * the build globalises those two symbols in paprium.c.o with objcopy (no recompile, so its code is unchanged).
 */
#include "appmain.h"
#include "buddy.h"

/* Not cleared by crt0 (an orphan NOBITS section after .bss): the boot path keeps its exact length. buddy_event
   zeroes it at the first event of each MCU boot, told by MTIME_HI bit 31 (crt0 zeroes every internal IO register,
   MTIME included, at every boot; the glue sets the bit; MTIME_HI would reach it after ~1.3 million years). */
#define BSS __attribute__((section(".noinit.zz_buddy")))
#define NOINL __attribute__((noinline))
/* cold code (boot-time slices, init, rate table, publish, the slow path's bookkeeping): size over speed; the
   per-tick / per-post paths and the run start stay -O2 */
#define COLD __attribute__((noinline, optimize("Os")))

/* ------------------------------------------------------------------ shipping symbols */
typedef struct {                        /* sfx.c's SfxChan, same layout (10 words) */
    u32 age, ptr, size, step, step_num, decay, looped, ptr_base, size_base, flags;
} BudSfxChan;
extern BudSfxChan sfx_chan[8];
extern u32 ppm_sfx_base_addr;
extern u32 vu_due;                      /* paprium.c statics, globalised in the object by the build (objcopy) */
extern u8 vu_on;
void ppm_cmd_handler(void);
void sfx_player_update(void);
void ppm_music_vu_update(void);
extern void __crt0_dummy_trap_handler(void);
extern char __crt0_bss_end[];

/* zz_buddy_trap.c */
extern void buddy_trap(void);
extern u32 buddy_call_brain(u32 h2, u32 h1, u32 *word);
extern volatile u32 buddy_jmp_sp;       /* != 0 while a brain call is in flight */
extern volatile u32 buddy_abort_req;
extern volatile u32 buddy_code_lo, buddy_code_hi;

#if BUDDY_STUB_BRAIN
extern const BudEntry buddy_stub_entry; /* zz_buddy_stub.c */
#endif
#if BUDDY_LINKED_BRAIN
extern const BudEntry buddy_linked_entry; /* zz_buddy_brain.c (the linked brain) */
#define PBUD_LOADER 0
#else
#define PBUD_LOADER (!BUDDY_STUB_BRAIN)
#endif

/* ------------------------------------------------------------------ small helpers */
#define REG32(a)        (*(volatile u32 *) (a))
#define REG16(a)        (*(volatile u16 *) (a))
#define XL(off)         REG32(BUD_XLINK_BASE + (off))
#define CTRL()          REG32(BUD_FPGAIO_CTRL)
#define MS_NOW()        REG32(BUD_FPGAIO_TIME)
#define MTIME_NOW()     REG32(MTIME_LO_ADDR)
#define REGCMD()        (ppmio.ramdp->reg_cmd)

#define CSR_SET(csr, v)   __asm__ volatile ("csrs " #csr ", %0" :: "r" (v))
#define CSR_CLR(csr, v)   __asm__ volatile ("csrc " #csr ", %0" :: "r" (v))
#define CSR_W(csr, v)     __asm__ volatile ("csrw " #csr ", %0" :: "r" (v))
/* a two-instruction interrupt window (MIE = 1) inside a handler that runs with MIE = 0: a pending mailbox post is
   taken here (MTIE is off inside a tick, so never a tick) */
#define MIE_WINDOW()    do { CSR_SET(mstatus, MST_MIE); __asm__ volatile ("nop\n\tnop"); CSR_CLR(mstatus, MST_MIE); } while (0)
#define MIE_MEIE        (1u << 11)
#define MIE_MTIE        (1u << 7)
#define MST_MIE         (1u << 3)

/* ------------------------------------------------------------------ state (all in .bss.zz_buddy) */
enum { ST_NEW = 0, ST_DISABLED, ST_LOADING, ST_READY };
enum { LD_CRC = 0, LD_COPY, LD_VERIFY, LD_DONE };

typedef struct {
    u32 state;
    const BudEntry *ent;
    /* sliced work */
    u8 restart_pending;                 /* restart seen, waiting for the release (SRES = 1, SBRQ = 0) */
    u8 restore_pending;                 /* release seen: Word RAM pattern still being written */
    u8 brain_flag_pending;              /* raise the brain's restart flag before the next call */
    u8 rate_pending;                    /* SFX rate table still being built */
    u32 rs_rec, rs_pos;                 /* restore record / byte position */
    u32 rt_idx, rt_n, rt_base;          /* rate table build */
    u32 ld_step, ld_pos, ld_crc, ld_crc_fast, ld_crc_copy;
    /* calibration of FPGAIO ms vs MTIME: the edge of ms t_ref happened at MTIME in (e_lo, e_hi] (mod 2^32) */
    u32 cal_have, t_ref, e_lo, e_hi;
} BudState;

typedef struct {                        /* the MTIME feeder + VU scheduler of one brain run */
    u32 mask;                           /* channels fed */
    u32 playing;                        /* channels with samples left at the last scan */
    u32 next;                           /* next grid deadline (MTIME_LO) */
    u8 k[8];                            /* pushes per tick, by the channel's rate */
    u32 vu_armed, vu_at, vu_poll;       /* VU check at vu_at; vu_poll = 1 while polling (phase not known) */
    u32 rescan_armed, rescan_at;
    u32 resolve;                        /* fed channels whose rate is still to be looked up (k = 24 kHz's meanwhile) */
    u32 tail_pending;                   /* a post ISR inside a tick's window left its scan / VU schedule to the tick */
} BudFeed;

typedef struct { u32 ptr, size, rate; u32 key_ok; } BudChanRate;

BSS BudState bud;
BSS BudFeed bfeed;
BSS BudChanRate bud_chrate[8];
BSS BudStats bud_stats;
BSS volatile u32 bud_in_tick;

/* sfx table rate index -> pushes per BUDDY_FEED_PERIOD: k = ceil((P + J) / T) + 1, P = 7,168, J = 400,
   T = 1,118.6 x the divider (/1 /2 /4 /5 /8 /9 as the RTL's audio_sfx.sv divides; /10 gives the same k). The + 1
   makes a fed FIFO gain >= 1 sample a tick, so a young channel climbs during a run instead of only holding. */
static const u8 bud_k_by_rate[8] __attribute__((section(".rodata.zz_buddy"))) = {8, 5, 3, 3, 2, 2, 2, 2};

/* ------------------------------------------------------------------ MTIME / ms phase calibration */
/* One sample: m1 = MTIME, t = FPGAIO ms counter, m2 = MTIME. time_st follows ctr_t while the bus is idle, so the
   value read was the counter at a clock between the two MTIME reads: E(t) <= m2 and E(t + 1) > m1 (+-4 margin). */
COLD static void cal_sample(void)
{
    u32 m1 = MTIME_NOW();
    u32 t = MS_NOW();
    u32 m2 = MTIME_NOW();
    u32 lo = m1 - 4u - BUDDY_MS_CYCLES, hi = m2 + 4u;         /* bounds on E(t) */
    bud_stats.cal_samples++;
    if (!bud.cal_have || (u32) (t - bud.t_ref) > 20000u) {
        bud.cal_have = 1; bud.t_ref = t; bud.e_lo = lo; bud.e_hi = hi;
    } else {
        u32 d = (t - bud.t_ref) * BUDDY_MS_CYCLES;            /* < 2^31 for |t - t_ref| <= 20 s */
        lo -= d; hi -= d;                                       /* the same bounds moved to E(t_ref) */
        if ((s32) (hi - bud.e_hi) < 0) bud.e_hi = hi;
        if ((s32) (lo - bud.e_lo) > 0) bud.e_lo = lo;
        if ((s32) (bud.e_hi - bud.e_lo) <= 0) {                 /* inconsistent (should not happen): start again */
            bud.t_ref = t; bud.e_lo = m1 - 4u - BUDDY_MS_CYCLES; bud.e_hi = m2 + 4u;
        } else if ((u32) (t - bud.t_ref) > 10000u) {            /* keep t_ref recent (no overflow, MTIME wraps 80 s) */
            bud.e_lo += d; bud.e_hi += d; bud.t_ref = t;
        }
    }
    bud_stats.cal_width = bud.e_hi - bud.e_lo;
}

/* ------------------------------------------------------------------ R-VU: schedule the due check */
COLD static void vu_schedule(u32 now)
{
    if (!vu_on) { bfeed.vu_armed = 0; return; }
    u32 t = MS_NOW();
    s32 ahead = (s32) (vu_due - t);
    if (ahead > 30000) { bfeed.vu_armed = 0; return; }        /* not due within any run */
    u32 at;
    if (ahead <= 0) at = now;                                   /* due already */
    else if (bud.cal_have && (bud.e_hi - bud.e_lo) <= BUDDY_VU_CAL_MAX && (u32) (vu_due - bud.t_ref) < 30000u) {
        at = bud.e_hi + (vu_due - bud.t_ref) * BUDDY_MS_CYCLES + 8u;      /* latest possible edge of vu_due */
        bfeed.vu_poll = 0;
    } else {
        /* not calibrated: wake at the earliest possible edge, then poll */
        at = now + (u32) (ahead - 1) * BUDDY_MS_CYCLES;
        bfeed.vu_poll = 1;
    }
    bfeed.vu_armed = 1; bfeed.vu_at = at;
}

/* the check itself (MTIME tick or after a mailbox service): the row runs if due, exactly as the main loop runs it */
COLD static void vu_service(u32 now)
{
    u32 before = vu_due;
    cal_sample();
    ppm_music_vu_update();
    if (vu_due != before) {
        bud_stats.vu_rows++;
        vu_schedule(MTIME_NOW());
    } else if (vu_on) {
        bud_stats.vu_polls++;
        vu_schedule(now);
        if (bfeed.vu_armed && (s32) (bfeed.vu_at - now) < (s32) BUDDY_VU_POLL) bfeed.vu_at = now + BUDDY_VU_POLL;
    } else {
        bfeed.vu_armed = 0;
    }
}

/* ------------------------------------------------------------------ R-SFX: rates */
/* Rate hash in the SRAM scratch: each entry = {ptr, size, rate | 0x100 valid}; ptr/size as sfx_play stores them. */
#define RATE_SLOT(i)    ((volatile u32 *) (BUDDY_SCRATCH_ADDR + (i) * 12u))
static u32 rate_hash(u32 ptr) { return ((ptr >> 1) ^ (ptr >> 9) ^ (ptr >> 17)) & (BUDDY_RATE_SLOTS - 1u); }

COLD static void rate_insert(u32 ptr, u32 size, u32 rate)
{
    u32 h = rate_hash(ptr);
    for (u32 n = 0; n < BUDDY_RATE_SLOTS; n++, h = (h + 1u) & (BUDDY_RATE_SLOTS - 1u)) {
        volatile u32 *s = RATE_SLOT(h);
        if (!(s[2] & 0x100u)) { s[0] = ptr; s[1] = size; s[2] = 0x100u | rate; return; }
        if (s[0] == ptr && s[1] == size) {                      /* same sample twice: keep the faster rate */
            if (rate < (s[2] & 7u)) s[2] = 0x100u | rate;
            return;
        }
    }
}

COLD static int rate_lookup(u32 ptr, u32 size)
{
    u32 h = rate_hash(ptr);
    for (u32 n = 0; n < BUDDY_RATE_SLOTS; n++, h = (h + 1u) & (BUDDY_RATE_SLOTS - 1u)) {
        volatile u32 *s = RATE_SLOT(h);
        if (!(s[2] & 0x100u)) return -1;
        if (s[0] == ptr && s[1] == size) return (int) (s[2] & 7u);
    }
    return -1;
}

/* one slice of the table build: sfx_play's own reads of entry `arg` (ptr, size, type) */
COLD static void rate_build_slice(void)
{
    if (bud.rt_idx == 0) {
        for (u32 i = 0; i < BUDDY_RATE_SLOTS; i++) RATE_SLOT(i)[2] = 0;
        bud.rt_base = ppm_sfx_base_addr;
        bud.rt_n = *(u16 *) &ppmio.flash[bud.rt_base + 6];          /* ppm_sfx_data[0].length, as mame.c reads it */
        if (bud.rt_n > 255u) bud.rt_n = 255u;
        bud.rt_idx = 1;
        return;
    }
    for (u32 n = 0; n < BUDDY_SLICE_RATE && bud.rt_idx <= bud.rt_n; n++, bud.rt_idx++) {
        u8 *sfx = &ppmio.flash[bud.rt_base + bud.rt_idx * 8];
        u32 ptr = bud.rt_base + swapshorts(*(u32 *) &sfx[0]);
        u32 size = (sfx[4] << 16) | *(u16 *) &sfx[6];
        rate_insert(ptr, size, (sfx[5] >> 4) & 7u);
    }
    if (bud.rt_idx > bud.rt_n) {                                /* done: forget the misses cached meanwhile */
        bud.rate_pending = 0;
        for (u32 ch = 0; ch < 8; ch++) bud_chrate[ch].key_ok = 0;
    }
}

/* the channel's consumption rate index as sfx_play programmed it (flag 0x0100 steps it down, saturating at 5) */
COLD static u32 chan_k(u32 ch)
{
    BudChanRate *c = &bud_chrate[ch];
    u32 ptr = sfx_chan[ch].ptr_base, size = sfx_chan[ch].size_base;
    if (!c->key_ok || c->ptr != ptr || c->size != size) {
        int r = -1;
        if (!bud.rate_pending && bud.rt_base == ppm_sfx_base_addr) r = rate_lookup(ptr, size);
        if (r < 0) { bud_stats.rate_miss++; c->rate = 0xFF; }
        else {
            bud_stats.rate_hits++;
            if ((sfx_chan[ch].flags & 0x0100u) && r < 5) r++;
            c->rate = (u32) r;
        }
        c->ptr = ptr; c->size = size; c->key_ok = 1;
    }
    return c->rate > 7u ? BUDDY_FEED_K_UNKNOWN : bud_k_by_rate[c->rate];
}

/* ------------------------------------------------------------------ R-SFX: the feeder */
/* the channel's pushes per tick: the cached rate's k, else 24 kHz's until a tick resolves the rate */
static inline __attribute__((always_inline)) void feed_price(u32 ch)
{
    BudChanRate *c = &bud_chrate[ch];
    if (c->key_ok && c->ptr == sfx_chan[ch].ptr_base && c->size == sfx_chan[ch].size_base)
        bfeed.k[ch] = (u8) (c->rate > 7u ? BUDDY_FEED_K_UNKNOWN : bud_k_by_rate[c->rate]);
    else { bfeed.k[ch] = BUDDY_FEED_K_UNKNOWN; bfeed.resolve |= 1u << ch; }
}

/* channels with samples left (sfx_player_update's first test) */
static inline __attribute__((always_inline)) u32 playing_mask(void)
{
    u32 playing = 0;
#pragma GCC unroll 8
    for (u32 ch = 0; ch < 8; ch++) playing |= (u32) (sfx_chan[ch].size != 0) << ch;
    return playing;
}

/* scan: fed = channels with samples left and a FIFO not full (sfx_player_update's own two tests). Returns the
   channels new to the feeder (the caller decides when they are fed: run_call's first round, or the grid) */
static u32 feed_scan(u32 now)
{
    u32 m = 0, playing = playing_mask();                        /* the common case: all idle */
    for (u32 ch = 0; playing >> ch; ch++) {
        if (!(playing & (1u << ch))) continue;
        if (ppmio.sfx[ch].status.fifo_full) continue;
        m |= 1u << ch;
        feed_price(ch);
    }
    u32 nw = m & ~bfeed.mask;
    bfeed.mask = m;
    bfeed.playing = playing;
    bfeed.rescan_armed = (playing & ~m) != 0;                   /* a full channel drains: look again later */
    bfeed.rescan_at = now + BUDDY_FEED_RESCAN;
    if (m > bud_stats.feed_mask_max) bud_stats.feed_mask_max = m;
    bud_stats.rescans++;
    return nw;
}

/* rate look-ups left by feed_scan, `max` channels (after the pushes: a young channel is fed first) */
COLD static void feed_resolve(u32 max)
{
    for (u32 ch = 0; ch < 8 && bfeed.resolve && max; ch++) {
        if (!(bfeed.resolve & (1u << ch))) continue;
        bfeed.resolve &= ~(1u << ch); max--;
        u32 k = chan_k(ch);
        if (bfeed.mask & (1u << ch)) bfeed.k[ch] = (u8) k;
    }
}

/* m rounds of pushes into every fed channel, k per round. The per-channel code is sfx_player_update's (same flash
   byte, same 4/8-bit conversion, same ptr / size / step / loop bookkeeping, same FIFO-full test before each push);
   ptr / size / step are kept in registers across the channel's pushes and written back once, and a 4-bit
   channel's byte is read once for its two nibbles (the same byte: part A of the glue's unit test, outside this tree,
   checks values and end state against the shipping function on random states).
   win = 1 (the MTIME tick): between two channels MIE opens for one instruction, so a mailbox post never waits
   behind the whole feeder - only behind one channel's batch. Nothing is held across the window: the channel's
   state is written back before it, and the mask and k are re-read after it (a nested 0xD1 may change them). */
/* up to k pushes into channel ch; 0 = the channel left the feeder (no samples, or its FIFO read full) */
static inline __attribute__((always_inline)) u32 chan_batch(u32 ch, u32 k, u32 *pushed)
{
    BudSfxChan *c = &sfx_chan[ch];
    SfxIO *io = &ppmio.sfx[ch];
    u8 *fl = ppmio.flash;
    u32 ptr = c->ptr, size = c->size, step = c->step, keep = 1, n = 0;
    const u32 four = (c->step_num == 2);
    int byte = -1;
    for (; k; k--) {
        if (size == 0) { keep = 0; break; }
        if (io->status.fifo_full) { keep = 0; bfeed.rescan_armed = 1; break; }
        int sample;
        if (four) {
            if (byte < 0) byte = fl[ptr ^ 1];                   /* the byte both nibbles come from */
            sample = byte;
            if (step == 0) { sample >>= 4; step = 1; }
            else { step = 0; ptr++; byte = -1; }
            sample = (((sample & 0x0F) * 65536) / 16) - 32768;
        } else {
            sample = fl[ptr ^ 1]; //use flash_sw
            ptr++;
            sample = (((sample & 0xFF) * 65536) / 256) - 32768;
        }
        io->sample = sample;
        n++;
        if (--size == 0 && c->looped) { ptr = c->ptr_base; size = c->size_base; byte = -1; }
    }
    c->ptr = ptr; c->size = size; c->step = step;
    *pushed += n;
    return keep;
}

/* a channel chan_batch left the feeder with: FIFO full (it stays playing; a rescan looks again) or no samples left
   (it leaves bfeed.playing too, so a 0xD1 that starts it again in this run is seen as a start) */
static inline __attribute__((always_inline)) void chan_dropped(u32 ch, u32 bit)
{
    bfeed.mask &= ~bit;
    if (sfx_chan[ch].size == 0) bfeed.playing &= ~bit;
}

/* One round: k * m pushes into every fed channel, in channel order (an RTL simulation showed it: ordering by rate and a
   round-robin phase first both cost more cycles before the batches than they saved, and left a young 24 kHz channel
   dry). win = 1 (the MTIME tick): MIE opens for two instructions after every channel, so a mailbox post never waits
   behind the feeder, only behind one channel's batch; nothing is held across the window (the channel's state is
   written back first, the mask and k are re-read after: a nested 0xD1 may change them). Called with MIE = 0. */
static void feed_push(u32 m, u32 win)
{
    u32 n = 0;
    for (u32 ch = 0; ch < 8; ch++) {
        u32 bit = 1u << ch;
        if (!(bfeed.mask & bit)) continue;
        u32 k = bfeed.k[ch];
        if (m > 1) { k *= m; if (k > BUDDY_FEED_KMAX) k = BUDDY_FEED_KMAX; }
        if (!chan_batch(ch, k, &n)) chan_dropped(ch, bit);
        if (win) { CSR_SET(mstatus, MST_MIE); __asm__ volatile ("nop\n\tnop"); CSR_CLR(mstatus, MST_MIE); }
    }
    bud_stats.pushes += n;
}

/* an out-of-line copy of chan_batch for the post ISR's first batch (the tick keeps its own inlined copy) */
static NOINL u32 chan_batch_ool(u32 ch, u32 k, u32 *pushed) { return chan_batch(ch, k, pushed); }

/* A channel started inside a run (a 0xD1 serviced by the post ISR) has at most one sample in its FIFO by the
   body's sfx_player_update: its first batch goes in right after the command's service, before that update and
   before the full scan, instead of at the next grid tick behind every other channel's batch (a 24 kHz channel at
   level 1 lasts 2 x 2,237 cycles). nw = channels playing after the command that were not playing before it
   (bfeed.playing is kept exact inside a run: set by the first round and the scans, refreshed after every ISR body,
   and a channel the feeder empties leaves it at once - chan_dropped; the glue's unit test, case D3: without that, a
   channel that ended and was started again in the same run missed this batch). Everything else waits for the full
   scan after the body (an RTL simulation showed a full scan ahead of sfx_player_update delaying a young channel's
   push past its pop).
   Called with MIE = 0. */
static void feed_started(u32 nw)
{
    u32 old = bfeed.mask, n = 0;
    bfeed.playing |= nw;
    for (u32 ch = 0; nw >> ch; ch++) {
        u32 bit = 1u << ch;
        if (!(nw & bit) || ppmio.sfx[ch].status.fifo_full) continue;
        feed_price(ch);
        bfeed.mask |= bit;
        if (!chan_batch_ool(ch, bfeed.k[ch], &n)) chan_dropped(ch, bit);
    }
    if (!old && bfeed.mask) bfeed.next = MTIME_NOW() + BUDDY_FEED_PERIOD;   /* an idle grid starts after it */
    bud_stats.pushes += n;
    bud_stats.first_batches++;
}

/* The run's first round, fused with the scan: each channel with samples left and a FIFO not full is priced and
   gets its batch at once, in channel order. RTL-sim sixB_arm at L16 = 19 (v18): with the scan as a separate pass
   first (~1,100 cycles), the third young 24 kHz channel's batch came 18 cycles after its FIFO ran dry. */
static void feed_round_first(u32 now)
{
    u32 playing = playing_mask(), m = 0, n = 0;
    for (u32 ch = 0; playing >> ch; ch++) {
        u32 bit = 1u << ch;
        if (!(playing & bit) || ppmio.sfx[ch].status.fifo_full) continue;
        feed_price(ch);
        if (chan_batch(ch, bfeed.k[ch], &n)) m |= bit;
        else if (sfx_chan[ch].size == 0) playing &= ~bit;       /* emptied by this batch */
    }
    bfeed.mask = m;
    bfeed.playing = playing;
    bfeed.rescan_armed = (playing & ~m) != 0;
    bfeed.rescan_at = now + BUDDY_FEED_RESCAN;
    if (m > bud_stats.feed_mask_max) bud_stats.feed_mask_max = m;
    bud_stats.rescans++;
    bud_stats.pushes += n;
}

/* the next MTIME edge: the earliest of the grid (while feeding), the VU check and the rescan. NEORV32 1.4.8.1 makes
   an interrupt only on the 0 -> 1 edge of (mtime >= mtimecmp): a compare written already in the past gives no edge,
   and the tick chain would stop for the rest of the run. So the compare goes BUDDY_CMP_LEAD ahead at least, and is
   checked again after the write landed. */
#define BUDDY_CMP_LEAD  256
static void feed_program(void)
{
    for (u32 tries = 0; tries < 4; tries++) {
        u32 now = MTIME_NOW();
        s32 d = 0x3FFFFFFF;
        if (bfeed.mask) { s32 x = (s32) (bfeed.next - now); if (x < d) d = x; }
        if (bfeed.vu_armed) { s32 x = (s32) (bfeed.vu_at - now); if (x < d) d = x; }
        if (bfeed.rescan_armed) { s32 x = (s32) (bfeed.rescan_at - now); if (x < d) d = x; }
        if (d < BUDDY_CMP_LEAD) d = BUDDY_CMP_LEAD;
        u32 c = now + (u32) d;
        REG32(MTIMECMP_LO_ADDR) = c;
        if ((s32) (c - MTIME_NOW()) >= 16) return;
    }
}

static int run_must_abort(void)
{
    u32 c = CTRL();
    /* a restart (SRES 0) or AI off (SBRQ 1) while the call runs: rule 2, the call in flight is reset */
    return !(c & CT_SRES) || (c & CT_SBRQ);
}

/* after a mailbox service: the ms/MTIME phase sample, the feeder's full scan (a channel back from FIFO-full joins;
   into an idle grid it ticks now), the VU schedule */
static void post_tail(void)
{
    u32 now = MTIME_NOW();
    cal_sample();
    u32 old = bfeed.mask;
    if (feed_scan(now) && !old) bfeed.next = now;
    vu_schedule(now);
}

/* MTIME interrupt (from zz_buddy_trap.c, every caller-saved register saved) */
void buddy_isr_tick(void)
{
    if (bud_in_tick) return;                                    /* taken in a window of the tick itself: nothing to do,
                                                                   the outer tick programs the next edge */
    bud_in_tick = 1;
    CSR_CLR(mie, MIE_MTIE);                                     /* the windows below let a mailbox post in, never a
                                                                   tick (RTL-sim v11: a nested tick cost ~580 cycles
                                                                   of a young channel's margin each); set again below,
                                                                   after the next edge is programmed >= 256 ahead */
    u32 now = MTIME_NOW();
    bud_stats.ticks++;
    if (bfeed.mask && (s32) (now - bfeed.next) >= 0) {
        u32 m = 1, d = bfeed.next + BUDDY_FEED_PERIOD;
        while ((s32) (now - d) >= 0 && m <= BUDDY_FEED_CATCHUP) { d += BUDDY_FEED_PERIOD; m++; }
        if ((s32) (now - d) >= 0) d = now + BUDDY_FEED_PERIOD; /* far behind (a long service): restart the grid */
        if (m > 1) bud_stats.catchups++;
        bfeed.next = d;
        feed_push(m, 1);
    }
    if (bfeed.vu_armed && (s32) (now - bfeed.vu_at) >= 0) {
        if (vu_on && (s32) (MS_NOW() - vu_due) >= 0 && bfeed.mask) feed_push(BUDDY_FEED_VU_TOPUP, 0);   /* a row is due */
        vu_service(now);
    }
    if (bfeed.rescan_armed && (s32) (now - bfeed.rescan_at) >= 0) {
        u32 old = bfeed.mask;                                   /* a channel back from FIFO-full joins the grid (it
                                                                   was full a rescan ago); an idle grid restarts now */
        if (feed_scan(now) && !old) bfeed.next = now;
    }
    /* a post serviced in a window above left its scan / VU schedule here; a window after each of these pieces (and
       after the rate look-up) lets the next post in (RTL-sim newinB v21: a 0xC9 that arrived during this ~3,200-cycle
       stretch waited 4,049 cycles for its reply) */
    while (bfeed.tail_pending) { bfeed.tail_pending = 0; post_tail(); MIE_WINDOW(); }
    if (bfeed.resolve) {                                        /* one rate look-up a tick, after its pushes */
        feed_resolve(1); MIE_WINDOW();
        while (bfeed.tail_pending) { bfeed.tail_pending = 0; post_tail(); MIE_WINDOW(); }
    }
    if (run_must_abort()) buddy_abort_req = 1;
    feed_program();
    bud_in_tick = 0;
    CSR_SET(mie, MIE_MTIE);
}

/* Mailbox interrupt: today's main-loop body until the mailbox is quiet (a nonzero response is polled again, as the
   next pass would), then the feeder's scan and the VU schedule are refreshed. A channel a command started (0xD1)
   gets its first batch right after that command's service (the reply is out by then), before the body's
   sfx_player_update (RTL-sim newinB v13: with it after the body, the new 24 kHz channel's batch came 2,250 cycles
   after the reply). The pushes are the same per-channel stream in the same order; only their timing moves. */
void buddy_isr_post(void)
{
    REG32(BUD_FPGAIO_IRQCLR) = 1;                              /* clear the latch first ... */
    CSR_CLR(mie, MIE_MEIE);                                     /* ... then drop what irq_buf caught meanwhile */
    CSR_SET(mie, MIE_MEIE);
    bud_stats.mbx_isr++;
    u32 n = 0;
    do {
        if (REGCMD() != 0) bud_stats.mbx_cmds++;
        ppm_cmd_handler();
        u32 nw = playing_mask() & ~bfeed.playing;               /* started by this command: first batch now */
        if (nw) feed_started(nw);
        sfx_player_update();
        ppm_music_vu_update();
        bfeed.playing = playing_mask();                         /* exact again: a channel this body ended (its last
                                                                   sample, or a 0xD2) leaves; the feeder clears the
                                                                   ones it ends itself (chan_dropped) */
    } while (REGCMD() != 0 && ++n < 8);
    if (run_must_abort()) buddy_abort_req = 1;
    if (bud_in_tick) {                                          /* inside a tick's window: the channels after this one
                                                                   still wait for their batches - the scan, the VU
                                                                   schedule and the next edge are the tick's, at its end
                                                                   (RTL-sim sixB L16 = 19, v17: this tail, ~2,000
                                                                   cycles, made a young channel's batch late by ~500) */
        bfeed.tail_pending = 1;
        return;
    }
    post_tail();
    feed_program();
}

/* an exception while a brain call is in flight (zz_buddy_trap.c decides firmware vs brain code by mepc) */
COLD void buddy_exc_brain(void)
{
    bud_stats.exc_brain++;
    (void) XL(XL_ID);                                           /* absorb a stale xbus ack (found in a review) */
    buddy_abort_req = 1;
    bud.state = ST_DISABLED;
}

/* ------------------------------------------------------------------ boot-time work (sliced) */
#if PBUD_LOADER
COLD static u32 crc32_nib(u32 crc, u8 b)
{
    static const u32 t[16] = {
        0x00000000, 0x1DB71064, 0x3B6E20C8, 0x26D930AC, 0x76DC4190, 0x6B6B51F4, 0x4DB26158, 0x5005713C,
        0xEDB88320, 0xF00F9344, 0xD6D6A3E8, 0xCB61B38C, 0x9B64C2B0, 0x86D3D2D4, 0xA00AE278, 0xBDBDF21C};
    crc ^= b;
    crc = (crc >> 4) ^ t[crc & 15u];
    crc = (crc >> 4) ^ t[crc & 15u];
    return crc;
}
#endif

/* restore: the sub-CPU init's Word RAM pattern into the SRAM mirror (objects / records 0, terrain $00FF,
   header +0..+9 = 0), BUDDY_SLICE_WORDS halfwords a slice */
static void restore_slice(void)
{
    const BudEntry *e = bud.ent;
    u32 left = BUDDY_SLICE_WORDS;
    while (left) {
        if (bud.rs_rec >= e->nrestore + e->ncopy) {
            bud.restore_pending = 0; bud_stats.restores_done++;
            if (e->t16_key) REG32(e->t16_key) = 0;              /* linked brain: T16 rebuilt after every release */
            return;
        }
        if (bud.rs_rec >= e->nrestore) {                        /* linked brain: the copy records, halfwords */
            u32 k = bud.rs_rec - e->nrestore, pos = bud.rs_pos, bytes = e->copy[k].bytes;
            u32 s = e->copy[k].src, d = e->copy[k].dst;
            for (; left && pos < bytes; left--, pos += 2u) REG16(d + pos) = REG16(s + pos);
            if (pos >= bytes) { bud.rs_rec++; pos = 0; }
            bud.rs_pos = pos;
            continue;
        }
        u32 a = e->restore[bud.rs_rec].addr, bytes = e->restore[bud.rs_rec].bytes;
        u32 f = e->restore[bud.rs_rec].fill16 & 0xFFFFu, pos = bud.rs_pos;
        u32 w = f | (f << 16);                                  /* two 68000 words per SRAM long (16-bit native) */
        for (; left && pos + 4u <= bytes; left--, pos += 4u) REG32(a + pos) = w;
        if (left && pos < bytes) { REG16(a + pos) = (u16) f; pos += 2u; left--; }
        if (pos >= bytes) { bud.rs_rec++; pos = 0; }
        bud.rs_pos = pos;
    }
}

#if PBUD_LOADER
/* PBUD image: CRC of the payload, copy of the fast section into WRAM, CRC of the copy */
COLD static void load_slice(void)
{
    const BudPbudHdr *h = (const BudPbudHdr *) BUDDY_IMG_ADDR;
    const u8 *pl = (const u8 *) (BUDDY_IMG_ADDR + 32u);
    if (bud.ld_step == LD_CRC) {
        for (u32 n = 0; n < BUDDY_SLICE_CRC_BYTES && bud.ld_pos < h->length; n++, bud.ld_pos++) {
            u8 b = pl[bud.ld_pos];
            bud.ld_crc = crc32_nib(bud.ld_crc, b);
            if (bud.ld_pos >= h->fast_lma && bud.ld_pos < h->fast_lma + h->fast_len) bud.ld_crc_fast = crc32_nib(bud.ld_crc_fast, b);
        }
        if (bud.ld_pos >= h->length) {
            bud_stats.img_crc_calc = ~bud.ld_crc;
            if (~bud.ld_crc != h->crc32) { bud.state = ST_DISABLED; bud_stats.img_state = 0xBAD1; return; }
            bud.ld_step = LD_COPY; bud.ld_pos = 0;
        }
    } else if (bud.ld_step == LD_COPY) {
        for (u32 n = 0; n < BUDDY_SLICE_WORDS && bud.ld_pos < h->fast_len; n++, bud.ld_pos += 4)
            REG32(h->fast_vma + bud.ld_pos) = REG32(BUDDY_IMG_ADDR + 32u + h->fast_lma + bud.ld_pos);
        if (bud.ld_pos >= h->fast_len) { bud.ld_step = LD_VERIFY; bud.ld_pos = 0; bud.ld_crc_copy = 0xFFFFFFFFu; }
    } else if (bud.ld_step == LD_VERIFY) {
        for (u32 n = 0; n < BUDDY_SLICE_CRC_BYTES && bud.ld_pos < h->fast_len; n++, bud.ld_pos++)
            bud.ld_crc_copy = crc32_nib(bud.ld_crc_copy, *(const u8 *) (h->fast_vma + bud.ld_pos));
        if (bud.ld_pos >= h->fast_len) {
            if (bud.ld_crc_copy != bud.ld_crc_fast) { bud.state = ST_DISABLED; bud_stats.img_state = 0xBAD2; return; }
            bud.ld_step = LD_DONE;
            bud.state = ST_READY;
            bud_stats.img_state = 0x600D;
        }
    }
}

COLD static int image_check(void)
{
    const BudPbudHdr *h = (const BudPbudHdr *) BUDDY_IMG_ADDR;
    if (h->magic != PBUD_MAGIC || h->version != 1 || h->length == 0 || h->length > 0x10000u - 32u) return 0;
    if (h->entry_off + sizeof(BudEntry) > h->length) return 0;
    if (h->fast_len) {
        if ((h->fast_len & 3u) || (h->fast_vma & 3u) || h->fast_lma + h->fast_len > h->length) return 0;
        if (h->fast_vma < (((u32) __crt0_bss_end + 15u) & ~15u) || h->fast_vma + h->fast_len > BUDDY_WRAM_CODE_HI) return 0;
    }
    const BudEntry *e = (const BudEntry *) (BUDDY_IMG_ADDR + 32u + h->entry_off);
    if (e->magic != PBE_MAGIC || e->nrestore > 4u) return 0;
    bud.ent = e;
    buddy_code_lo = e->code_lo; buddy_code_hi = e->code_hi;
    return 1;
}
#endif

/* one slice of whatever boot-time work is pending; returns 1 while work remains */
COLD static int work_slice(void)
{
#if PBUD_LOADER
    if (bud.state == ST_LOADING) { load_slice(); return 1; }
#endif
    if (bud.restore_pending) { restore_slice(); return 1; }
    if (bud.rate_pending) { rate_build_slice(); return bud.rate_pending; }
    return 0;
}

COLD static void buddy_init(void)
{
    bud_stats.inits++;
    if (XL(XL_ID) != XLINK_ID_STAGE2) { bud.state = ST_DISABLED; return; }
    XL(XL_XCFG) = XL(XL_XCFG) | XCFG_LOCK;                      /* protect the loaded image from stray stores */
    REG32(MTIMECMP_HI_ADDR) = 0;                                /* the compare is used 32-bit (mtimecmp_hi = 0) */
#if BUDDY_STUB_BRAIN
    bud.ent = &buddy_stub_entry;
    buddy_code_lo = bud.ent->code_lo; buddy_code_hi = bud.ent->code_hi;
    bud.state = ST_READY;
    bud_stats.img_state = 0x5703;
#elif BUDDY_LINKED_BRAIN
    bud.ent = &buddy_linked_entry;                              /* the linked brain: code already in block RAM */
    buddy_code_lo = bud.ent->code_lo; buddy_code_hi = bud.ent->code_hi;
    bud.state = ST_READY;
    bud_stats.img_state = 0x11AB;
#else
    if (!image_check()) { bud.state = ST_DISABLED; bud_stats.img_state = 0xBAD0; return; }
    const BudPbudHdr *h = (const BudPbudHdr *) BUDDY_IMG_ADDR;
    bud.ld_step = LD_CRC; bud.ld_pos = 0; bud.ld_crc = 0xFFFFFFFFu; bud.ld_crc_fast = 0xFFFFFFFFu;
    if (h->fast_len == 0) bud.ld_step = LD_CRC;               /* CRC still checked; LD_COPY ends at once */
    bud.state = ST_LOADING;
#endif
    bud.brain_flag_pending = 1;                                 /* WRAM survives a soft reset: always restart once */
    bud.restart_pending = 1;                                    /* wait for the release before the first call */
    bud.rate_pending = 1; bud.rt_idx = 0;
}

/* option D on (honest BUSY + COMSTAT2) only once the brain can answer; LCTRL[15:8] = HOLD is written back as read
   (a review found that a plain write of bit 0 would also set HOLD = 0) */
COLD static void option_d(u32 on)
{
    u32 v = XL(XL_LCTRL);
    XL(XL_LCTRL) = (v & 0xFF00u) | (on ? 1u : 0u);
}

/* ------------------------------------------------------------------ one brain call */
COLD static void publish(u32 word, u32 posts0)
{
    volatile u32 *co = (volatile u32 *) bud.ent->cnt_out;
    u32 dw = co[1] & 0xFFFFFFu, db = co[2] & 0xFFFFFFu;
    if (db < dw) { db = dw; bud_stats.dbusy_fixed++; }         /* from a review: D_BUSY >= D_WORD always */
    XL(XL_DWORD) = dw;
    XL(XL_DBUSY) = db;
    XL(XL_PEND) = word & 0xFFFFu;
    XL(XL_ARM) = 1;
    /* found in a review: an ARM toggle that lands on the clk_md clock of a $A12001 write or a post is lost. Read
       back: taken = armed, or busy already released (late ARM). A lost ARM is sent again (idempotent: same values,
       and the stub ignores an ARM once the timer has stopped). */
    for (u32 tries = 0; tries < 3; tries++) {
        u32 ls = 0;
        for (u32 r = 0; r < 3; r++) {                           /* ~6 clk_sys for the toggle + LSTAT round trip */
            ls = XL(XL_LSTAT);
            if (ls & LS_ARMED) break;
        }
        if ((ls & LS_ARMED) || !(ls & LS_BUSY)) {
            if (ls & LS_LATE) bud_stats.late_seen++;
            bud_stats.published++;
            return;
        }
        if ((ls >> 16) != posts0 || !(ls & LS_SRES) || (ls & LS_SBRQ)) { bud_stats.discarded++; return; }
        bud_stats.rearms++;
        XL(XL_ARM) = 1;
    }
    bud_stats.arm_lost++;
}

static void run_call(void)
{
    const BudEntry *e = bud.ent;
    u32 t0 = MTIME_NOW();
    bfeed.mask = 0; bfeed.vu_armed = 0; bfeed.rescan_armed = 0; bfeed.resolve = 0; bfeed.tail_pending = 0;
    bud_in_tick = 0;
    buddy_abort_req = 0;
    buddy_jmp_sp = 0;
    /* R-SFX: the run's first round right here, before anything else and with the interrupts still off, in plain
       per-channel batches fused with the scan (RTL-sim exp_on sixB: a post serviced inside the first round, a
       round-robin phase of single pushes first, or two stages of batches (v16: the round took twice as long, a 0xD3
       reply waited 7,290 cycles and two young channels underran) all did worse) */
    feed_round_first(t0);
    bfeed.next = t0 + BUDDY_FEED_PERIOD;
    /* arm the interrupts (MIE stays 0 for now): latch cleared, then MEIE; MTIE before any compare is written (NEORV32
       1.4.8.1 buffers the one-clock MTIME edge only while MTIE is set) */
    REG32(BUD_FPGAIO_IRQCLR) = 1;
    CSR_W(mtvec, (u32) buddy_trap);
    CSR_SET(mie, MIE_MEIE | MIE_MTIE);
    if (REGCMD() != 0) buddy_isr_post();                        /* posted before the clear: no latch for it */

    u32 ls0 = XL(XL_LSTAT);
    u32 posts0 = ls0 >> 16;
    u32 word = 0, rc = 2;
    if (!(ls0 & LS_SRES) || (ls0 & LS_SBRQ)) { bud_stats.ignored_halted++; goto out; }

    /* the call's inputs: the mirror and the PRG tables are in SRAM (snooped), T1-T3 in the flash window; the
       firmware only sets the counter's W and, after a restart, the brain's flag */
    volatile u32 *co = (volatile u32 *) e->cnt_out;
    co[3] = 0;                                                  /* Wf = 0: W lives in the stub's tick (12.5 MHz) */
    if (bud.brain_flag_pending) { REG16(e->flag) = 1; bud.brain_flag_pending = 0; }
    vu_schedule(t0);                                            /* rate look-ups wait for the ticks (k = 24 kHz's) */
    feed_program();
    CSR_SET(mstatus, MST_MIE);

    rc = buddy_abort_req ? 1u : buddy_call_brain(e->h2, e->h1, &word);
out:
    CSR_CLR(mstatus, MST_MIE);
    CSR_CLR(mie, MIE_MEIE | MIE_MTIE);
    CSR_W(mtvec, (u32) __crt0_dummy_trap_handler);
    bfeed.mask = 0; bfeed.vu_armed = 0; bfeed.rescan_armed = 0;

    if (rc == 2) return;                                        /* halted / restarted since the post: no call */
    u32 dt = MTIME_NOW() - t0;
    bud_stats.run_cycles_last = dt;
    if (dt > bud_stats.run_cycles_max) bud_stats.run_cycles_max = dt;
    bud_stats.calls++;
    if (rc) {
        bud_stats.aborted++;
        if (e->t16_key) REG32(e->t16_key) = 0;                  /* linked brain: a cut T16 build must not be kept */
        return;
    }

    u32 ls1 = XL(XL_LSTAT);
    if ((ls1 >> 16) != posts0 || !(ls1 & LS_SRES) || (ls1 & LS_SBRQ) || (ls1 & ~ls0 & (LS_RESTART | LS_AIOFF))) {
        bud_stats.discarded++;                                  /* reset / halt / a new post during the call */
        return;
    }
    publish(word, posts0);
}

/* ------------------------------------------------------------------ the slow path (main loop, end of a pass) */
void buddy_event(u32 ctrl)
{
    /* A send: today's next pass would push into every channel at once (its ppm_cmd_handler finds the mailbox empty,
       then sfx_player_update). Do exactly that before anything else - a young channel may be down to its last sample
       (the glue's unit test, part D: any later, and a 24 kHz channel at level 0 underruns where today's loop
       does not). */
    u32 go = (ctrl & CT_SEND) && !(ctrl & CT_RESTART) && REGCMD() == 0 && bud.state == ST_READY;
    if (go) sfx_player_update();
    if (!(REG32(MTIME_HI_ADDR) & 0x80000000u)) {                /* first event since this MCU boot */
        memset(&bud, 0, sizeof bud);
        memset(&bfeed, 0, sizeof bfeed);
        memset(bud_chrate, 0, sizeof bud_chrate);
        memset(&bud_stats, 0, sizeof bud_stats);
        buddy_jmp_sp = 0; buddy_abort_req = 0;
        REG32(MTIME_HI_ADDR) = REG32(MTIME_HI_ADDR) | 0x80000000u;
    }
    bud_stats.events++;
    if (bud.state == ST_NEW) buddy_init();
    if (bud.state == ST_DISABLED) {                             /* a plain stub: acknowledge and forget */
        if (bud_stats.img_state != 0xD15A) {                    /* once: BUSY / COMSTAT2 back to today's stub answers */
            if (XL(XL_ID) == XLINK_ID_STAGE2) option_d(0);
            bud_stats.img_state = 0xD15A;
        }
        XL(XL_LCLR) = LS_SEND | LS_RESTART | LS_AIOFF | LS_LATE;
        return;
    }
    /* The send first: between the pass end and the brain only what the call needs (the not-before slacks of the
       shortest calls are ~1,300 MCU cycles). run_call feeds every needy channel before anything else; it checks SRES /
       SBRQ itself (a restart or a halt since the post: no call). */
    if (go && bud.state == ST_READY && !(bud.restart_pending | bud.restore_pending)) {
        XL(XL_LCLR) = LS_SEND;
        bud_stats.sends++;
        run_call();
    }
    u32 ls = XL(XL_LSTAT);
    u32 clr = 0;
    if (ls & LS_RESTART) { bud_stats.restarts++; bud.restart_pending = 1; bud.brain_flag_pending = 1; clr |= LS_RESTART; }
    if (ls & LS_AIOFF) bud_stats.aioffs++;
    if (ls & LS_LATE) { bud_stats.late_seen++; clr |= LS_LATE; }
    if (bud.restart_pending && (ls & LS_SRES) && !(ls & LS_SBRQ)) {
        /* the release: the sub init writes its Word RAM pattern now (main writes the mirror only at its sends) */
        bud.restart_pending = 0;
        bud.restore_pending = 1; bud.rs_rec = 0; bud.rs_pos = 0;
        bud_stats.releases++;
    }
    /* a send still pending here waits for boot-time work (never seen in play: that work ends ~2,900 frames before the
       first send): the main loop goes on as today, the work a slice a pass, and the call runs as soon as it is done
       (late, so the stub releases at once). It is never dropped, which would leave BUSY set. */
    if ((ls & LS_SEND) && bud.state == ST_READY) bud_stats.ignored_notready++;

    cal_sample();
    /* the rate table follows the SFX base: 0xC6 (cmd_C6_setup_data) sets it, and the first event (the Mega CD init's
       AI off) may come before it. Until a build ends, look-ups are refused and the feeder prices a channel as 24 kHz
       (BUDDY_FEED_K_UNKNOWN, the bank's fastest rate), so a send never waits for this. */
    if (!bud.rate_pending && bud.rt_base != ppm_sfx_base_addr) { bud.rate_pending = 1; bud.rt_idx = 0; }
    int more = work_slice();
    if (bud.state == ST_READY && !(XL(XL_LCTRL) & 1u)) option_d(1);
    /* AI off is held set (the slow path runs every pass) while boot work remains, while waiting for a release, and
       while the sub is halted (a give-up stays halted until a reboot, whose restart edge raises no new AI off) */
    if (!more && !bud.restart_pending && !(ls & LS_SBRQ)) clr |= LS_AIOFF;
    if (clr) XL(XL_LCLR) = clr;
}
