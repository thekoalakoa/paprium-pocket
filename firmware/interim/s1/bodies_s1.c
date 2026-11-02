/* Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later) */
/* interim/s1/bodies_s1.c - the 0.2.6 command bodies, re-hosted under the cart chip's command map. The cart chip is the
 * STM32 microcontroller on the real cartridge; the 0x0801xxxx-0x0803xxxx, 0x2000xxxx / 0x2001xxxx and 0x68060000
 * numbers below are its program, RAM and cart-RAM addresses. FW_S5 (board/board.h) builds
 * the full firmware; the FW_S5 = 0 build is the earlier firmware.
 *
 * D08, D20 and the other D numbers name the differences between the 0.2.6 code and the cart's chip that our own study
 * of how the cart behaves listed.
 *
 * Moved from legacy/026/paprium.c (final 0.2.6), one body per cart chip command, with only these changes:
 *   - the post's argument byte is a parameter (0.2.6 read it back from RAMDP $1FEA, which the new firmware never
 *     reads; RAMDP is the cart RAM that both the 68000 and the MCU see);
 *   - every gate is the cart chip's, in core/dispatch (0.2.6's own copies of the EC / B0 gates and the C6 engine rule
 *     went there); every status bit is the cart chip's (0.2.6's busy rule and its $1FE6 bits 8/9/14 writes are retired:
 *     the RTL makes busy, docs/CART_FPGA_SPEC.md 7);
 *   - the window pointer goes through the board (brd_stream_ptr = FPGAIO slot 2, as 0.2.6 wrote it), and a body that
 *     ends a stream then writes GO with its length (docs/MCU_INTERFACE.md 4.5; GO follows each stream start, rule T4 of
 *     the comparison with the cart chip);
 *   - the cart's FPGA decodes the sprite blocks the cart chip lists (AF / B1's load list, F2's block) and DA06 / DA07's
 *     0x80 streams, and so does ours (MCU interface v1.2: the RTL decoder): 0.2.6's engine keeps the list of the blocks
 *     it loads (mame.c, FW_S1), the dispatcher pushes it as the cart chip does (core/dispatch flush_regs), and the
 *     bodies here only give the decoder its output base (brd_dec_base), 0.2.6's layout, so the window serves the same
 *     words from the same workspace bytes as 0.2.6; F5's 4 KB buffer is static (interim/s1/f5_s1.c);
 *   - the jobs raise MSI when queued (core/sched sched_work_post): L2c runs them, above the thread's CPU MATE brain
 *     call;
 *   - the volume writes and the SFX FIFO base go through two interim board hooks (s1_interim.h).
 * Everything else is the 0.2.6 code, TEST diagnostics (PPM_SAT_SNAPSHOT) included. BOOT-nn names are rows of
 * docs/BOOT_SPEC.md; row numbers such as B12 are rows of docs/ALLOWLIST.md. */
#include "appmain.h"
#include "sched.h"
#include "disp.h"
#include "disp_bodies.h"
#include "s1_interim.h"
#include "stats.h"
#include "spr.h"
#include "zoom.h"
#if FW_S5
uint32_t song_unpack80(const uint8_t *src, uint8_t *dst);   /* the 0x80 and 0x81 stream decoders, core/song/song_c6.c */
uint32_t song_unpack81(const uint8_t *src, uint8_t *dst);   /* and core/song/unpack81.c (song.h is not usable here) */
#if FW_S5
void chip_level_init(void);                                 /* core/tables: the level table T, built at power-on */
#endif
#endif
#if FW_MW
#include "mw.h"
#endif

ppm_io ppmio;
u32 tick_ctr;               /* paprium.c: 0.2.6 counted main-loop passes (its sfx.c stamped a channel's age with it;
                               the cart chip's channel choice, interim/s1/sfx_s1.c, has no age); the new firmware counts
                               the SFX feeder's grid ticks (interim/s1/audio_s1.c) */
s1_interim_stats_t s1_interim_stats;

/* S1_BUG: planted bugs for the negative controls of the RV32 fuzz test only (tests/equiv/fuzz_s1.py; fwbuild.json s1
   variants test_bug_*; never defined in an image that ships): 1 = a DA07 job's GO is left to the thread's next pass,
   after the job step has cleared $1FE6 bit 14 (FZ3); 2 = DA06 / DA07 with a 0x80 source GOes from the firmware too, as
   the earlier board work did, on top of the RTL decoder's own GO (the GO check: two GOs for one post); 3 = the sprite
   blocks an AD loads are decoded inside L1 again, 0.2.6's place (FZ12 decode; legacy/026/mame.c); 4 = TEST's SAT
   snapshot made inside AF's L1 body again, 0.2.6's place (FZ12 length) */
#ifndef S1_BUG
#define S1_BUG 0
#endif

/* 0.2.6 served each high byte on its own (cmp_ptr[256]) and never mailbox A: a body runs only for the byte 0.2.6 ran
   it for (disp_bodies.h). The cart chip's other form of the command (bit 14 the other way) was "unknown" there: no
   effect. */
static int is026(uint8_t hi) { return disp_g.cur_mbx == MBX_B && (uint8_t)(disp_g.cur_word >> 8) == hi; }

/* ================================================================================================================
 * The sprite decoder is the RTL's (MCU interface v1.2; B Jam's decision of 2026-10-15: "preservation: reply at once,
 * sprites already done, never wait"). The cart chip lists the frame's blocks and F2's block as flash addresses in the
 * FPGA's queue and replies at once; the cart's FPGA decodes them before the game's VBlank DMA reads the window, and the
 * cart chip never waits for it. Ours: the dispatcher writes the cart chip's queue sequence, the board half here sets
 * the decoder's output base before each START (0.2.6's layout: the frame's blocks at PPM_SCRATCH_BASE + 0x200 x k,
 * F2's two copies there, a DA's stream at its destination), and the RTL loads SPTR, decodes and GOes by itself.
 * Earlier versions decoded in firmware (a stand-in on the wheel, then L2c, then L2b) and had AF / F2 finish after the
 * decode; that and its board work are gone. 0.2.6's ppm_unpack stays, in the FW_S5 = 0 images, for the cart chip's own
 * decodes (in the FW_S5 images the cart chip's own decoders do them: s5_unpack below) (DA02 and the 0x81 / 0x82 DA07
 * jobs, C6's containers, F4's stamps).
 * TEST only: 0.2.6's SAT snapshot (a 640-B copy into the save, PPM_SAT_SNAPSHOT) is a diagnostic: it never delays a
 * reply. AF's close asks for it and the thread takes it below the brain call (l3_test_work); a frame start (AE) that
 * comes first drops the request, so the copy is always this frame's closed table (the 68000 never reads it: save
 * $900-$FFF). Since layout 2 (mame.c), the thread keeps two tables, the session's most crowded frame (its true count
 * beside the capped one) and the latest frame of 20 or more as before; AF latches the count it closed and counts the
 * session's most and its AFs over 80 (a compare / store each, s1_sat_snapshot_later); a frame start that comes after
 * the thread took the request (its count is read with the take, interrupts off), so before or while the thread copies
 * (interrupts open), marks that copy torn (bit 15 of its count) instead of passing unseen.
 * With the cart chip's sprite engine (core/sprite): the snapshot stayed for test build S2; the sprite
 * engine's TEST counters feed its cache figures (budget refusals, no-slot drops, loads, live evictions); the eviction
 * ring and its reload count (0.2.6's slot loader) are gone and read 0.
 * ================================================================================================================ */
#if PPM_SAT_SNAPSHOT
static volatile uint32_t snap_later;                        /* set by AF's frame end (mame.c, FW_S1); the thread takes it */
static uint16_t snap_af_read;                               /* $1F18 as body_af read it, before AF's reply */
__attribute__((noinline))                                   /* (a function of its own: q1_save.py H hooks its entry) */
void s1_sat_snapshot_later(void)                            /* AF's L1, after its reply (body_af_replied; layout 2
                                                               of the snapshot: mame.c): the count AF closed (read
                                                               in body_af before the reply) is latched for the
                                                               thread, and
                                                               the session's most and its AFs over 80 are two compares; no
                                                               loop here, the copies are the thread's */
{
    uint32_t n = snap_af_read;
    snap_af_n = n;
    if (n > snap_n_max)
        snap_n_max = n;
    if (n > 80u)
        snap_n_over80++;
    snap_later = 1u;
}
#endif
#if S1_BUG == 1 || S1_BUG == 2
static volatile uint32_t bug_go;
#endif

uint32_t l3_test_work(void)                                 /* the thread, below the brain call */
{
#if S1_BUG == 1
    if (bug_go) {                                           /* planted: a late GO from the firmware */
        brd_stream_go(bug_go & 0x1FFFFFu);
        bug_go = 0u;
        return 1u;
    }
#elif S1_BUG == 2
    /* planted: a second GO on top of the RTL decoder's, sent only once the RTL's run has ended (DEC_STAT [10] RUN = 0,
       MCU interface 4.9), so it always lands after the RTL's GO and the GO check alone must catch it (test build 4b's
       repair, 2026-10-22: sent as soon as the thread ran, it could land inside the run in test build 4b's timing and
       cut it, which the DEC checks caught instead; the plant is now independent of the thread's scheduling) */
    if (bug_go && !(*(volatile uint32_t *)(uintptr_t)POCKET_FIO_DEC_STAT & (1u << 10))) {
        brd_stream_go(bug_go & 0x1FFFFFu);
        bug_go = 0u;
        return 1u;
    }
#endif
#if PPM_SAT_SNAPSHOT
    uint32_t s = brd_irq_save(), take = snap_later, ae0 = snap_cnt_ae;   /* the request and the frame-start count
                                                               together: a frame start after this, even before the
                                                               copy reads anything, marks the copy torn */
    snap_later = 0u;
    brd_irq_restore(s);
    if (take) {
        ST_ENTER(ST_L3_WORK);
        ppm_snapshot_sat(ae0);                              /* TEST: interrupts open; nothing waits for it */
        ST_LEAVE();
        return 1u;
    }
#endif
    return 0u;
}

uint32_t body_load_list(const uint32_t **list)              /* the flush: the engine's list (core/sprite) */
{
    uint32_t n = spr_load_list(list);
#if !PPM_RELEASE && !TDIAG_LEAN
    s1_interim_stats.dec_flushes++;
    s1_interim_stats.dec_entries += n;
    if (n > s1_interim_stats.dec_list_max)
        s1_interim_stats.dec_list_max = n;
#endif
    return n;
}

void body_dec_scratch(void)                                 /* the flush's and F2's output base: 0.2.6's block scratch */
{
    brd_dec_base(PPM_SCRATCH_BASE);
}

static void s1_go(uint32_t words)
{
    brd_stream_go(words);
#if !PPM_RELEASE && !TDIAG_LEAN
    s1_interim_stats.go_words_last = words;
#endif
}

static void s1_point(u32 new_ptr)                           /* 0.2.6's pointer write, everywhere it set it */
{
    if (ppmio.ramdp->dma_cmd_count != 0)
        snap_ptr_while_list_pending++;
    brd_stream_ptr(new_ptr);
    ppm_sptr_shadow = new_ptr;
}

#if !FW_S5                                                  /* (FW_S5: s5_unpack gives the code, below) */
/* the cart chip's job-step failure codes for an unpack (0x0801A3E2-0x0801A48E) from the source type and the length */
static uint32_t unpack_code(uint8_t t, u32 len)
{
    if (t == 0x80u || t == 0x81u)
        return len ? 0u : 0x11u;
    if (t == 0x82u)
        return 0u;
    if (t == 0x83u)
        return len ? 0u : 0x12u;
    return 4u;
}
#endif

#if FW_S5
/* FW_S5 (test build S3a on): an unpack job's decode as the cart chip's job step makes it (0x0801A3E2-0x0801A44C): the
   stream's type byte at src & ~1 picks 0x80 (0x080251B0 -> 0x20003EE8) or 0x81 (0x0801D390 -> 0x08015008), the cart
   chip's own decoders as ours has them, written to dst byte by byte; an empty result is the job's failure 0x11. 0x82
   (0x080251C0, a copy of length 0) writes nothing and is no failure; 0x83 (WavPack) is refused with 0x12 (the decoder
   is the first boot's only); any other type 4. Neither 0x82 nor 0x83 can reach these jobs in play: DA and F4 refuse
   0x83 at their gates, and no stream the game names is 0x82 (measured: every DA / F4 source of the four test-rig
   corpora, the 53 BGM entries, the three set-up containers and all 12,326 sprite blocks are 0x80 / 0x81, one null BGM
   entry aside).
   Returns the length */
static __attribute__((noinline)) u32 s5_unpack(u32 src, uint8_t *dst, uint32_t *code)
{
    const uint8_t *p = brd_flash8() + (src & ~1u);
    u32 n;
    *code = 0u;
    switch (p[0]) {
    case 0x80u:
        n = song_unpack80(p + 1, dst);
        break;
    case 0x81u:
        n = song_unpack81(p + 1, dst);
        break;
    case 0x82u:
        return 0u;
    case 0x83u:
        *code = 0x12u;
        return 0u;
    default:
        *code = 4u;
        return 0u;
    }
    if (!n)
        *code = 0x11u;
    return n;
}

/* each halfword of the first len & ~1 bytes at d swapped: the cart chip's DA tail (0x0801A49C-0x0801A4B2, type 3).
   The same bytes as the cart chip's halfword loop; ours swaps two halfwords per 32-bit SDRAM word once d is on a word
   boundary (word-wide SDRAM access saves time), with a single halfword before the boundary and after the last word
   where the length needs one. d is even: every caller passes an even address */
static __attribute__((noinline)) void s5_rev16(uint8_t *d, u32 len)
{
    uint8_t *e = d + (len & ~1u);
    uint16_t *h;
    if (((uintptr_t)d & 2u) && d != e) {                    /* a halfword up to the word boundary */
        h = (uint16_t *)(void *)d;
        *h = (uint16_t)((*h << 8) | (*h >> 8));
        d += 2;
    }
    for (uint32_t *w = (uint32_t *)(void *)d, *we = (uint32_t *)(void *)(d + ((u32)(e - d) & ~3u)); w != we; w++) {
        uint32_t x = *w;
        *w = ((x & 0x00FF00FFu) << 8) | ((x >> 8) & 0x00FF00FFu);
        d += 4;
    }
    if (d != e) {                                           /* a last halfword */
        h = (uint16_t *)(void *)d;
        *h = (uint16_t)((*h << 8) | (*h >> 8));
    }
}

/* C6's set-up (legacy/026/mame.c ppm_setup_data, FW_S5): a container into the workspace at dst through the cart
   chip's decoders, then each halfword swapped, so the workspace holds what 0.2.6's decoder left there (its readers:
   the window, the sprite engine's container view); every container the game has is 0x80 and even (measured) */
u32 s5_unpack_ws(u32 src, u32 dst)
{
    uint32_t code;
    uint8_t *d = (uint8_t *)(uintptr_t)brd_workspace() + dst;
    u32 n = s5_unpack(src, d, &code);
    s5_rev16(d, n);
    return n;
}
#endif

/* ================================================================================================================
 * boot
 * ================================================================================================================ */
void s1_interim_boot(void)
{
    ppmio.ramdp = (ppm_ramdp *)(uintptr_t)brd_cart_ram();
    ppmio.flash = (u8 *)(uintptr_t)brd_rom();
    ppmio.sdram = (u8 *)(uintptr_t)brd_workspace();
    ppmio.bram = (u8 *)(uintptr_t)brd_save();
#if !FW_S5                                                  /* (region 0x06 is the synth on an FW_S5
                                                               bitstream, not the interim SFX FIFOs) */
    ppmio.sfx = (SfxIO *)s1_board_sfx();
#endif
                                                            /* (no 0.2.6 sprite engine to set up; core/sprite
                                                               starts at C6's sprite init, its state zero from crt0) */
#if !FW_S5                                                  /* (FW_S5: the engine and its tables, core/song; the
                                                               FW_S5 images link no interim album or SFX) */
    mdp_init();                                             /* bounded (FW_S1 guards in interim/album: BOOT-02) */
    sfx_level_init();                                       /* the cart chip's level table T (D1 / D3 levels) */
#endif
#if !FW_S5                                                  /* (FW_S5: the interim volume registers retire) */
    s1_board_vol(S1_VOL_SFX, 0xFFu);
    s1_board_vol(S1_VOL_BGM, 0xFFu);
#else
    chip_level_init();                                      /* the level table T (core/tables), in RAM: before any
                                                               post can read it */
    save_boot();                                            /* test build S3a on: the saves' slot table, the 0.2.x
                                                               import */
#endif
}

/* ================================================================================================================
 * L1 bodies
 * ================================================================================================================ */

#if !FW_S5
uint16_t spr_rate;                                          /* the interim builds' G+0x08 (core/sprite's 50 Hz skip) */
static uint8_t spr_rate_cfg;                                /* and G+0x3E (0 at power-on, $FF from C6) */
#endif

/* 88: paprium.c cmd_88_audio_cfg. GPGX's byte indices (MCU byte A^1 = 68000 byte A), and the DAC stream fill. */
void body_88(uint8_t lo)
{
    vu8 *ram = (vu8 *)ppmio.ramdp;
    if (is026(0x88)) {
        ram[0x1801] = lo & 0x01;
        ram[0x1800] = ((lo & 0x01) ? 0x80 : 0x00) + ((lo & 0x02) ? 0x40 : 0x00);
        for (int i = 0x1802; i < 0x1A00; i++)               /* PPM_DAC_STREAM_FILL (shipping in 0.2.6) */
            ram[i] = 0x80;
    }
    sfx_mode88(lo);                                         /* the cart chip's 88 configuration, both mailboxes: bit 0
                                                               the YM-DAC mode (an SFX start has no echo / spread voice
                                                               there) */
#if !FW_S5
    if (lo != spr_rate_cfg) {                               /* the 88 configuration's rate word, which the */
        spr_rate_cfg = (uint8_t)(lo & 0x7Fu);               /* sprite engine's 50 Hz skip reads: written unless the */
        spr_rate = (lo & 2u) ? 0x3Cu : 0x32u;               /* config is the last one; C6 resets that to $FF */
    }
#endif
}

void body_c9(uint8_t lo) { if (is026(0xC9)) s1_board_vol(S1_VOL_BGM, lo); }  /* cmd_C9_vol_bgm */
void body_ca(uint8_t lo) { if (is026(0xCA)) s1_board_vol(S1_VOL_SFX, lo); }  /* cmd_CA_vol_sfx */

void body_8d(uint8_t lo)                                    /* cmd_8D_bgm_cfg */
{
    if (is026(0x8D) && (lo == 0 || lo == 8)) {
        mdp_stop();
        s1_vu_stop();
    }
}

void body_d1(uint8_t lo) { if (is026(0xD1)) { sfx_play(lo); s1_sfx_kick(); } }  /* the cart chip's D1 (interim/s1/
                                                                   sfx_s1.c: the SFX start, channel choice, voices),
                                                                   then the first batch; 91xx (the cart chip's form with
                                                                   no arguments) is never posted (measured, 7 corpora):
                                                                   0.2.6's no effect (row B12) */
void body_d2(uint8_t lo) { if (is026(0xD2)) sfx_d2(lo); }      /* the cart chip's D2 (interim/s1/sfx_s1.c: free now, or
                                                                   a fade then free; 92xx never posted: row B12) */
void body_d3(uint8_t lo) { if (is026(0xD3)) sfx_loop(lo); }     /* the cart chip's D3: level / pan (D31: it never loops
                                                                   or re-arms a channel, so it starts nothing to
                                                                   feed) */
void body_d5(uint8_t lo) { (void)lo; if (is026(0xD5)) sfx_stop(0xC0); }   /* 0.2.6's cmd_D5_sfx_stopall call (the
                                                                   audit logs keep it; 95xx: muted); its body is now the
                                                                   cart chip's D5: the SFX echo only, no channel touched
                                                                   (interim/s1/sfx_s1.c) */

/* ---- sprites: the cart chip's sprite engine (core/sprite). The cart chip runs its sprite engine for every form of
   these commands on both mailboxes once the dispatcher's gates pass (0.2.6's per-byte, mailbox-B-only rule is gone) - */
void body_ad(uint8_t lo)                                    /* AD: 0x080194BC(lo) */
{
#if S1_BUG == 3
    uint32_t k = SPR.nload;
#endif
#if PPM_SAT_SNAPSHOT
    snap_cnt_ad++;
#endif
    spr_ad(lo);
#if S1_BUG == 3
    for (; k < SPR.nload; k++)                              /* planted (fuzz_s1 FZ12 decode): the blocks this AD listed
                                                               decoded inside L1, 0.2.6's place */
        ppm_unpack(spr_blk_addr(SPR.load[k]), PPM_SCRATCH_BASE + 0x200u * k);
#endif
}

void body_ae(void)                                          /* AE: 0x08018FBC's engine part */
{
#if PPM_SAT_SNAPSHOT
    snap_cnt_ae++;
    snap_later = 0u;                                        /* the last frame's snapshot not taken yet: dropped (the
                                                               table is about to change; TEST only) */
#endif
    spr_post_ae();
}

void body_af(uint8_t mode, uint8_t parity)                  /* AF: 0x080190B8 after its flush (disp.c): the close */
{
#if PPM_SAT_SNAPSHOT
    snap_af_read = ppmio.ramdp->sat_count;                  /* TEST: the count this close reads ($1F18: the close only
                                                               reads it), taken before AF's reply: after the reply the
                                                               68000 may write $1F18 before the bookkeeping runs */
#endif
    spr_post_af(mode, parity);
}

#if !PPM_RELEASE && !TDIAG_LEAN
void body_af_replied(void)                                  /* TEST: the same AF's L1, after its reply (before it,
                                                               the bookkeeping cost AF's reply ~1.6 us, measured) */
{
#if PPM_SAT_SNAPSHOT
    snap_cnt_af++;
    s1_sat_snapshot_later();                                /* the count body_af read before the reply, the session's
                                                               most, the request for the thread */
#if S1_BUG == 4
    if (snap_later) {
        snap_later = 0u;
        ppm_snapshot_sat(snap_cnt_ae);                      /* planted: inside the post again (FZ12 length) */
    }
#endif
#endif
}
#endif

void body_b0(void) { spr_post_b0(); }                       /* B0 / F0: 0x0801940C's engine part (D20) */

void body_b1(void) { spr_post_b1(); }                       /* B1: only the flush (D47; the queue writes are
                                                               disp.c's) */

void body_ec(uint16_t slots) { spr_ec_set(slots); }         /* EC: 0x08017EE0(0, a1) (D08) */

uint32_t body_block_addr(uint16_t block) { return spr_blk_addr(block); }   /* F2: 0x08017E84-0x08017EAE */

/* ---- streams ------------------------------------------------------------------------------------------------- */
void body_db(uint16_t a0, uint16_t a1, uint16_t a2, uint8_t mode)   /* cmd_DB_set_dma_ptr, then GO */
{
    u32 new_ptr = ((u32)a0 << 16) | a1;                     /* swapshorts(cmd_args_long[0]) */
#if PPM_SAT_SNAPSHOT
    snap_db_count++;
    snap_da_pending_clear();
    snap_db_note(new_ptr);
#endif
    s1_point(new_ptr);
    if (mode == 6u)
        s1_go(a2 >> 1);                                     /* the chip's length: a2 bytes, in words */
#if FW_S5
    else if (mode == 3u) {                                  /* DB03 as the cart chip's: its DMA channel 6 copies a2
                                                               bytes, as halfwords, from SDRAM + (a1 & ~1) into the
                                                               cart RAM at a0 & ~1 (0x0801D43C-0x0801D454; disp.c checked
                                                               the page bound). The game never posts DB03 (measured: every
                                                               DB of the test-rig corpora is DB06). The cart chip's copy
                                                               runs as a DMA after the post's finish, ours in the post;
                                                               words from $1FE0 on are the register file the 68000 sees
                                                               there, so they are left out */
        const uint16_t *s = (const uint16_t *)(uintptr_t)(brd_workspace() + (a1 & ~1u));
        volatile uint16_t *d = brd_cart_ram() + (a0 >> 1);
        uint32_t n = (uint32_t)(a2 >> 1), room = (a0 >> 1) < 0xFF0u ? 0xFF0u - (a0 >> 1) : 0u;
        if (n > room)
            n = room;
        while (n--)
            *d++ = *s++;
    }
#endif
}

/* TEST: 0.2.6's notes for a DA stream (the decode's source, destination and the pointer clobber counters) */
static void s1_da_notes(u32 src, u32 len, u32 dst)
{
#if PPM_SAT_SNAPSHOT
    snap_da_note_src(src, len, dst);
    snap_da_count++;
    snap_da_last_dest = dst;
    snap_da_reset_high();
    if (dst == 0x9000) {
        snap_da_dest_9000++;
    } else {
        snap_da_pending_set();
        snap_da_note_other(dst);
    }
#else
    (void)src;
    (void)len;
    (void)dst;
#endif
}

/* the DA decode of the DA job (modes 2 / 7: DA02, and DA07 with a 0x81 / 0x82 source): cmd_DA_unpack */
static uint32_t s1_da(u32 src, u32 dst, u32 go)
{
#if FW_S5                                                   /* FW_S5 (test build S3a on): the cart chip's decode at
                                                               SDRAM + */
    uint32_t code;                                          /* (a0 & ~1), then its type-3 halfword swap */
    uint8_t *d = (uint8_t *)(uintptr_t)brd_workspace() + (dst & ~1u);
    u32 da_len = s5_unpack(src, d, &code);
    if (!code)
        s5_rev16(d, da_len);
#else
    uint8_t t = brd_rom_byte(src & ~1u);
    u32 da_len = ppm_unpack(src, dst);
#endif
    s1_da_notes(src, da_len, dst);
    s1_point(dst);                                          /* load-bearing in 0.2.6: the cell-room background */
#if S1_BUG == 1
    if (go == 2u)
        bug_go = 0x80000000u | (da_len >> 1);
    else
#endif
    if (go)
        s1_go(da_len >> 1);
#if FW_S5
    return code;
#else
    return unpack_code(t, da_len);
#endif
}

/* DA06 / DA07 with a 0x80 source, before the cart chip's START (0x0801D1FE): the cart's FPGA decodes the stream; ours
   (the RTL, MCU interface v1.2) decodes it at the DA's destination, 0.2.6's place, loads SPTR there and GOes; busy
   (RTL) holds the game until that GO. 0.2.6's pointer write is the RTL's now (it counts as one for the TEST clobber
   counter) */
void body_da_direct(uint32_t src, uint16_t dst, uint8_t mode)
{
    (void)mode;
    brd_dec_base(dst);
    if (ppmio.ramdp->dma_cmd_count != 0)
        snap_ptr_while_list_pending++;
    ppm_sptr_shadow = dst;
    s1_da_notes(src, 0u, dst);                              /* (the length is the RTL's: no TEST note needs it) */
#if !PPM_RELEASE && !TDIAG_LEAN
    s1_interim_stats.da_direct++;
#endif
#if S1_BUG == 2
    bug_go = 0x80000001u;                                   /* planted: the old board work's GO, on top of the RTL's */
#endif
}

/* ---- MegaWire -------------------------------------------------------------------------------------------------- */
void body_e7(void)                                          /* cmd_E7_mwire: "pretend data is in" */
{
    st_set(1u, ST_FE6, 0x20u);                              /* 0.2.6 reg_status_2.bits.mwire_data_in = 1 */
    ppmio.ramdp->net_data[0x10 / 2] = ppmio.ramdp->cmd_args[0] + 16;
}

/* ================================================================================================================
 * job bodies (thread)
 * ================================================================================================================ */
#if !FW_S5
static void s1_bgm(uint8_t arg)                             /* cmd_8C_bgm_play */
{
    hb_w8(9, 5);
    hb_w32(28, ppm_bgm_unpack_addr);
    u32 bl = ppm_unpack(ppm_bgm_addr(arg & 0x7f), ppm_bgm_unpack_addr);
    hb_w32(32, bl);
    if (ppm_bgm_unpack_addr + bl > PPM_SCRATCH_BASE)
        snap_bgm_over++;
#if !FW_S5                                                  /* (FW_S5: 8C is the engine's job, core/dispatch/jobs.c) */
    s1_vu_start(ppm_bgm_unpack_addr);
    if (arg & 0x80)
        mdp_play(arg & 0x7f);
    else
        mdp_play_once(arg & 0x7f);
#endif
}
#endif

uint32_t job_unpack(const disp_job_t *j)
{
    switch (j->type) {
    case JOB_UNPACK_DA:                                     /* DA02, and DA07 with a 0x81 / 0x82 source */
#if S1_BUG == 1
        return s1_da(j->p20, j->p18, j->s1_mode == 7u ? 2u : 0u);
#else
        return s1_da(j->p20, j->p18, j->s1_mode == 7u);
#endif
#if !FW_S5                                                  /* (FW_S5: 8C is the engine's job, core/dispatch/jobs.c;
                                                               the interim unpack for the VU retires) */
    case JOB_UNPACK_8C:
        if (j->s1_hi == 0x8C)                               /* CCxx: unknown in 0.2.6 */
            s1_bgm(j->s1_lo);
        return 0u;
#endif
    case JOB_UNPACK_F4: {                                   /* F4's stream into the cart chip's F4 source (core/zoom) */
#if FW_S5                                                   /* FW_S5: through the cart chip's decoders, in the */
        return zoom_f4_decode(j->p20);                      /* order they write it (job type 4: no swap), stopped at
                                                               the cart chip's zoom block's end (core/zoom) */
#else                                                       /* the FW_S5 = 0 images: 0.2.6's decoder, its order undone */
        uint8_t t = brd_rom_byte(j->p20 & ~1u);
        u32 len = ppm_unpack_scal(j->p20, 0, true);
        zoom_f4_order(len);
        return unpack_code(t, len);
#endif
    }
    default:                                                /* type 1: no post makes it */
        return 4u;
    }
}

#if FW_S5
/* ---- test build S3a on: the saves in the cart's own format (the cart chip's jobs 5 / 7: 0x0801A734 read, 0x0801A86C
   write, their validator 0x0801A69C), on the Pocket's 8 KB battery save in place of the cart's EEPROM
   ------------------------------- The chip keeps each save id in copies at the places its slot table names (id, EEPROM
   offset, size; ended by id 0): every copy ends in an 8-byte trailer (a 32-bit sequence number 1..0xFFFFFFFE, the id, a
   byte that makes the copy's XOR 0, the magic 0x3FC2) and its payload is scrambled with the job's key ((~i | key[i &
   3]) ^ b). A read takes the valid copy with the highest sequence (the first one at a tie), unscrambles it and copies
   the whole copy, trailer included, as halfwords to the cart RAM; with no valid copy it zero-fills the size and still
   succeeds (the job ignores the result: no $1FE6 bit 8). A write builds the copy from the cart RAM, then takes the
   valid copy with the lowest sequence (the first at a tie) and writes it with that sequence + 1 (0xFFFFFFFD at the
   top), or, with no valid copy, the first invalid one with sequence 2; with neither it fails (bit 8, trace 9). Both
   jobs read each copy into the zoom stamps of the cart chip (its scratch 0x200111EC) and the write builds its copy in
   the second half (0x200115EC): ours uses zoom_st the same way. $1FE4 bit 11 is set while a job runs. The EEPROM's own
   I2C reads, its 3-try write with a read back and its "write failed" event 0x1F are the cart chip's EEPROM plumbing:
   the battery save is written in place and always reads back.
   The slot table is the cart program's (0x0802E2A4); this tree does not hold it: the boot reads it from the player's
   ROM, where the game carries the cart program as a packed block (format 0x81 at ROM 0x101A18, 196,608 B unpacked: the
   chip's 0x08010000-0x0803FFFF; core/song's 0x81 decoder), unpacked into a workspace span no job writes before C6
   (EEP_CP_WS) as far as the boot reads it (EEP_CP_NEED: the slot table, then the 12 bytes after the note table that
   core/song's song_note_tail holds; the decode stops there, the bytes before it the same), and the table's entries
   copied to RAM. A ROM whose block does not unpack that far gives no table and a zero note tail: every read then
   zero-fills nothing and every write fails, as the chip with an empty table. */
#define EEP_CP_ROM              0x101A18u               /* the cart program's packed block in the game's ROM */
#define EEP_CP_BYTES            0x30000u                /* unpacked: 0x08010000-0x0803FFFF */
#define EEP_NOTE_TAIL_AT        0x1E430u                /* the bytes after the note table */
#define EEP_NOTE_TAIL_N         12u                     /* core/song SONG_NOTE_TAIL_N */
#define EEP_CP_NEED             (EEP_NOTE_TAIL_AT + EEP_NOTE_TAIL_N)   /* the decode stops here (< EEP_CP_BYTES) */
#define EEP_CP_WS               0x1A0000u               /* where the boot unpacks it (the workspace span C6's tables
                                                           and the game's jobs leave free: board.h BRD_C6TAB_OFF) */
#define EEP_TAB_AT              0x1E2A4u                /* the slot table: chip 0x0802E2A4 */
#define EEP_TAB_MAX             32u                     /* the write job's tried flags (0x0801A890-0x0801A8A0) */
#define EEP_TRAILER             8u
#define EEP_MAGIC               0x3FC2u
static uint16_t eep_tab[EEP_TAB_MAX][3];                /* id, offset, size per copy; id 0 ends it */
extern uint8_t song_note_tail[EEP_NOTE_TAIL_N];         /* core/song (song_tables.c): the note lookup's edge read */
uint32_t song_unpack81_to(const uint8_t *src, uint8_t *dst, const uint8_t *end);   /* core/song: stops at end */
static uint32_t eep_n;                                  /* the copies the table holds */

static uint32_t eep_size(uint32_t i) { return eep_tab[i][2]; }

/* 0x0801A69C: copy i read into buf (0x0801D600: inside the 8 KB, size 8..0x400) and checked; its sequence to *seq */
static __attribute__((noinline)) uint32_t eep_valid(uint32_t i, uint8_t *buf, uint32_t *seq)
{
    uint32_t n = eep_size(i), off = (uint16_t)eep_tab[i][1], k;
    const volatile uint8_t *e = brd_save();
    uint8_t x = 0u;
    const uint8_t *t;
    if (((n - EEP_TRAILER) & 0xFFFFu) >= 0x3F9u)
        return 0u;
    if (off + n > 0x2000u) {                            /* 0x0801D600 refuses: the chip posts 0x20 */
        chip_trace(0x20u, 0u, 0u);
        return 0u;
    }
    for (k = 0u; k < n; k++)
        buf[k] = e[off + k];
    t = buf + n - EEP_TRAILER;
    k = (uint32_t)t[0] | (uint32_t)t[1] << 8 | (uint32_t)t[2] << 16 | (uint32_t)t[3] << 24;
    if ((uint32_t)(t[6] | t[7] << 8) != EEP_MAGIC || k - 1u >= 0xFFFFFFFEu || (uint32_t)t[4] != eep_tab[i][0])
        return 0u;
    *seq = k;
    for (k = 0u; k < n; k++)
        x ^= buf[k];
    return x == 0u;
}

static void eep_scramble(uint8_t *b, uint32_t n, uint32_t key)   /* (~i | key[i & 3]) ^ b, the payload's n bytes */
{
    uint32_t i;
    for (i = 0u; i < n; i++)
        b[i] ^= (uint8_t)(~i | (key >> (8u * (i & 3u))));
}

/* the boot (68000 held): the slot table from the player's ROM, then the one-time import of a 0.2.x save */
static void eep_import(void);
void save_boot(void)
{
    uint8_t *w = (uint8_t *)(uintptr_t)brd_workspace() + EEP_CP_WS;
    const uint8_t *f = brd_flash8() + EEP_CP_ROM;
    uint32_t i;
    eep_n = 0u;
    if (f[0] != 0x81u || song_unpack81_to(f + 1, w, w + EEP_CP_NEED) != EEP_CP_NEED)
        return;                                         /* not the expected ROM: no table, no note tail */
    for (i = 0u; i < EEP_NOTE_TAIL_N; i++)
        song_note_tail[i] = w[EEP_NOTE_TAIL_AT + i];
    for (i = 0u; i < EEP_TAB_MAX - 1u; i++) {
        const uint16_t *e = (const uint16_t *)(const void *)(w + EEP_TAB_AT + 8u * i);
        if (!e[0])
            break;
        eep_tab[i][0] = e[0];
        eep_tab[i][1] = e[1];
        eep_tab[i][2] = e[2];
    }
    eep_n = i;
    eep_import();
}

/* job 5 (DF) and job 6 (the MegaWire init's read of slot 9): 0x0801A734 */
uint32_t job_eep_read(const disp_job_t *j)
{
    uint32_t i, best = 0xFFu, bseq = 0u, seq, n = 0u, id = j->b1c, k;
    uint8_t *buf = zoom_st;
    volatile uint16_t *d = brd_cart_ram() + ((j->p18 & 0x1FFEu) >> 1);   /* 0x68060000 + (a0 & ~1) */
#if FW_MW
    if (j->type == JOB_EEP_READ_MW)                     /* job 6: the chip's destination is its own MegaWire record
                                                           (0x20012A6C, ours mw_ram.eep, 100 B), not the cart RAM; the
                                                           same zeros or copy (a slot-9 copy is 96 B) land there */
        d = (volatile uint16_t *)(void *)mw_ram.eep;
#endif
    st_set(1u, ST_FE4, 0x800u);                         /* 0x0801A73E-0x0801A748 */
    for (i = 0u; i < eep_n; i++) {
        if (eep_tab[i][0] != id)
            continue;
        n = eep_size(i);
        if (eep_valid(i, buf, &seq) && (best == 0xFFu || bseq < seq)) {
            best = i;
            bseq = seq;
        }
    }
    if (best == 0xFFu || !eep_valid(best, buf, &seq)) {
        for (k = 0u; k < (n >> 1); k++)                 /* 0x0801A7B8: n bytes of zeros */
            d[k] = 0u;
        st_set(0u, ST_FE4, 0x800u);
        return 0u;
    }
    eep_scramble(buf, n - EEP_TRAILER, j->p24);         /* 0x0801A7EC-0x0801A80A */
    for (k = 0u; k < (n >> 1); k++)                     /* 0x0801A818-0x0801A82A: the whole copy, as halfwords */
        d[k] = (uint16_t)(buf[2u * k] | buf[2u * k + 1u] << 8);
    st_set(0u, ST_FE4, 0x800u);
    return 1u;
}

/* the copy for id in wb (its n bytes already there): the payload scrambled, the trailer with seq, the XOR byte */
static __attribute__((noinline)) void eep_seal(uint8_t *wb, uint32_t n, uint32_t id, uint32_t seq, uint32_t key)
{
    uint32_t k;
    uint8_t x = 0u;
    eep_scramble(wb, n - EEP_TRAILER, key);             /* 0x0801A970-0x0801A98C */
    wb[n - 2u] = (uint8_t)EEP_MAGIC;
    wb[n - 1u] = (uint8_t)(EEP_MAGIC >> 8);
    for (k = 0u; k < 4u; k++)
        wb[n - EEP_TRAILER + k] = (uint8_t)(seq >> (8u * k));
    wb[n - 4u] = (uint8_t)id;
    wb[n - 3u] = 0u;
    for (k = 0u; k < n; k++)
        x ^= wb[k];
    wb[n - 3u] = x;
}

/* job 7 (E0): 0x0801A86C; 0 = failed (bit 8, trace 9 when asked: the job step) */
uint32_t job_eep_write(const disp_job_t *j)
{
    uint32_t i, inv = 0xFFu, old = 0xFFu, mseq = 0xFFFFFFFFu, seq, n, id = j->b16, k;
    uint8_t *buf = zoom_st, *wb = zoom_st + 0x400u;
    volatile uint8_t *e = brd_save();
    st_set(1u, ST_FE4, 0x800u);                         /* 0x0801A880-0x0801A88E */
    for (i = 0u; i < eep_n; i++) {
        if (eep_tab[i][0] != id)
            continue;
        if (!eep_valid(i, buf, &seq)) {
            if (inv == 0xFFu)
                inv = i;
#if DISP_BUG == 10
        } else if (old == 0xFFu || seq > mseq || mseq == 0xFFFFFFFFu) {   /* planted (eeplock.py): the newest copy */
#else
        } else if (old == 0xFFu || seq < mseq) {
#endif
            old = i;
            mseq = seq;
        }
    }
    if (old == 0xFFu) {
        if (inv == 0xFFu) {                             /* 0x0801AA1C: no copy to write */
            st_set(0u, ST_FE4, 0x800u);
            return 0u;
        }
        old = inv;
        seq = 2u;                                       /* 0x0801A908-0x0801A912 */
    } else
        seq = mseq < 0xFFFFFFFDu ? mseq + 1u : 0xFFFFFFFDu;   /* 0x0801A90E-0x0801A918 */
    n = eep_size(old);
    {
        const volatile uint16_t *src = brd_cart_ram() + ((j->p20 & 0x1FFEu) >> 1);   /* 0x68060000 + (a1 & ~1) */
        for (k = 0u; k < (n >> 1); k++) {               /* 0x0801A958-0x0801A96E: n & ~1 bytes, as halfwords */
            uint32_t h = src[k];
            wb[2u * k] = (uint8_t)h;
            wb[2u * k + 1u] = (uint8_t)(h >> 8);
        }
    }
    eep_seal(wb, n, id, seq, j->p24);
    if (!(n & 3u) && !((uint16_t)eep_tab[old][1] & 3u) && (uint16_t)eep_tab[old][1] + n <= 0x2000u) {
        for (k = 0u; k < n; k++)                        /* 0x0801D59C: the copy written (and read back: equal) */
            e[(uint16_t)eep_tab[old][1] + k] = wb[k];
        for (k = 0u; k < n; k++)
            buf[k] = e[(uint16_t)eep_tab[old][1] + k];
        st_set(0u, ST_FE4, 0x800u);
        return 1u;
    }
    chip_trace(0x1Fu, 0u, 0u);                          /* 0x0801AA06: a copy the EEPROM driver refuses (never in */
    st_set(0u, ST_FE4, 0x800u);                         /* the table): ours stops, the chip tries the others */
    return 0u;
}

/* the one-time import of a 0.2.x save (0.2.x kept id 4's 0x200 B at 0x000 and ids 1-3's 0x100 B at 0x400, 0x600,
   0x800, plain): when no id 1-4 has a valid copy, each 0.2.x slot that is not blank (all 0x00 or all 0xFF) becomes
   what the cart chip's first write of it would store (its first table copy, which the cart puts at those same places,
   sequence 2), so the game reads back its own bytes and the trailer where a cart has one. Never again once a copy is
   valid; a blank save stays as it is */
static void eep_import(void)
{
    uint32_t id, i, k, seq, o, n;
    uint8_t *buf = zoom_st, *wb = zoom_st + 0x400u;
    volatile uint8_t *e = brd_save();
    for (i = 0u; i < eep_n; i++)
        if (eep_tab[i][0] >= 1u && eep_tab[i][0] <= 4u && eep_valid(i, buf, &seq))
            return;
    for (id = 1u; id <= 4u; id++) {
        uint8_t or_ = 0u, and_ = 0xFFu;
        for (i = 0u; i < eep_n && eep_tab[i][0] != id; i++)
            ;
        if (i == eep_n)
            continue;
        o = (uint16_t)eep_tab[i][1];
        n = eep_size(i);
        if (o != (id == 4u ? 0u : 0x200u + 0x200u * id) || n != (id == 4u ? 0x200u : 0x100u))
            continue;                                   /* (not the cart's layout: no import) */
        for (k = 0u; k < n; k++) {
            or_ |= e[o + k];
            and_ &= e[o + k];
        }
        if (!or_ || and_ == 0xFFu)
            continue;
        for (k = 0u; k < n; k++)
            wb[k] = e[o + k];
        eep_seal(wb, n, id, 2u, EEP_KEY);
        for (k = 0u; k < n; k++)
            e[o + k] = wb[k];
    }
}
#else
uint32_t job_eep_read(const disp_job_t *j)                  /* cmd_DF_eep_rd */
{
    u8 arg = j->b1c;
    u8 *ram_dp = (u8 *)ppmio.ramdp;
    switch (arg) {
    case 1: case 2: case 3:
        memcpy(&ram_dp[j->p18], &ppmio.bram[(0x200 + arg * 0x200)], 0x100);
        break;
    case 4:
        memcpy(&ram_dp[j->p18], &ppmio.bram[0], 0x200);
        break;
    }
    return 0u;
}

uint32_t job_eep_write(const disp_job_t *j)                 /* cmd_E0_eep_wr (its $1FE6 bit 8/9 clears: the chip's now) */
{
    u8 arg = j->b16;
    u8 *ram_dp = (u8 *)ppmio.ramdp;
    switch (arg) {
    case 1: case 2: case 3:
        memcpy(&ppmio.bram[(0x200 + arg * 0x200)], &ram_dp[j->p20], 0x100);
        break;
    case 4:
        memcpy(&ppmio.bram[0], &ram_dp[j->p20], 0x200);
        break;
    case 9:                                                 /* the cart chip's MegaWire record (96 B): core/mw's */
        break;
    default:                                                /* the lockstep test: the cart chip's writer 0x0801A86C finds */
        return 9u;                                          /* no such slot id in its table (ids 1-4, 9) and fails: */
    }                                                       /* $1FE6 bit 8 when asked, trace 9 (0x0801A52C-0x0801A544) */
    return 0u;
}
#endif

/* the zoom jobs 8-10 (the save, the set-up, F5's rescale and copy-out, the restore) are the cart chip's: core/zoom */

extern uint32_t ppm_anim_data_base_addr;                    /* legacy/026/mame.c ppm_setup_data: the anim container's */
extern uint16_t ppm_anim_max_index[256];                    /* workspace offset, and each object's anims - 1 */

#if FW_S5
/* test build S3a on: C6's sprite part as the cart chip's (the C6 job's 0x08019734 with its anim set-up 0x080195E0):
   only the anim container (C6's long 5) is decoded here; the cart chip's audio init (core/song, the job's next part)
   decodes its own two, which 0.2.6's set-up also decoded. The cart chip decodes the container at its SDRAM's start,
   ours at the workspace place 0.2.6's set-up gave it (C6_ANIM_WS: nothing reads the 6 KB before it any more); both then
   swap the halfwords of the whole 512 KB the decode may fill, whatever its length, and count. 1 bad container: the cart
   chip's trace code (0x17 no container or no directory, 0x18 not a 0x80 stream, 0x19 longer than 512 KB; 0x16 / 0x1A /
   0x1B from the count), no engine flag (SETUP_ENG); unreachable in play. The cart chip's call hands its 0x80 routine a
   length of 0x80000 (through 0x080251B0), which the routine (0x20003EE8) never reads: both decode the whole stream,
   then 0x19 tests the length. Where the container sits is ours (docs/ALLOWLIST.md, row B56). */
#define C6_ANIM_WS              0x11800u
uint32_t job_setup(const uint32_t longs[8], uint32_t mw_screen)   /* the C6 job's sprite part */
{
    uint8_t *a = (uint8_t *)(uintptr_t)brd_workspace() + C6_ANIM_WS;
    uint32_t src = longs[5] & ~1u, code;
    (void)mw_screen;                                        /* the MegaWire screen (job 12): the MegaWire code's */
    spr_c6_begin();                                         /* 0x08019734-0x080197BA, 0x080195E0-0x080195F4 */
    brd_freg_wr(BRD_FREG_FF6, 1u);                          /* 0x08019752: queue clear */
    st_set(0u, ST_FE4, 0x100u);                             /* 0x0801975E */
    *(volatile uint32_t *)(void *)a = 0u;                   /* 0x080195F6-0x080195FC: the container's first word */
    if (!longs[5] || !longs[6])
        code = 0x17u;                                       /* 0x08019600 */
    else if (brd_flash8()[src] != 0x80u)
        code = 0x18u;                                       /* 0x0801960E */
    else if (song_unpack80(brd_flash8() + src + 1u, a) > 0x80000u)
        code = 0x19u;                                       /* 0x0801961A */
    else {
        s5_rev16(a, 0x80000u);                              /* 0x0801961E-0x0801962E: all 512 KB */
        code = spr_c6_count(a, longs[6]);
    }
    if (code)
        chip_trace(code, 0u, 0u);                           /* 0x080196FE */
#if FW_MW
    if (s3_mw_on) {                                         /* the cart chip's MegaWire init 0x080218FC, the C6 job's
                                                               next part (it sets the MW byte itself and queues the
                                                               record's EEPROM read) */
        mw_init();
        return (code ? 0u : SETUP_ENG) | SETUP_SFX | SETUP_SEQ;
    }
#endif
    return (code ? 0u : SETUP_ENG) | SETUP_MW | SETUP_SFX | SETUP_SEQ;
}
#else
uint32_t job_setup(const uint32_t longs[8], uint32_t mw_screen)   /* cmd_C6_setup_data */
{
    (void)mw_screen;                                        /* the MegaWire screen (job 12): the MegaWire code's */
    brd_freg_wr(BRD_FREG_FF6, 1u);                          /* the cart chip's sprite init 0x08019752: queue clear */
    st_set(0u, ST_FE4, 0x100u);                             /* 0x0801975E */
#if PPM_SAT_SNAPSHOT
    ppm_snapshot_boot();
#endif
    ppm_setup_data(longs[0], longs[1], longs[2], longs[3], longs[4], longs[5], longs[6]);
    spr_c6(ppm_anim_data_base_addr, ppm_anim_max_index, longs[6]);   /* the sprite init 0x08019734 (core/sprite) on the
                                                               anim container the set-up unpacked */
    spr_rate_cfg = 0xFFu;                                   /* the audio init's G+0x3E := $FF: the next 88 sets the rate */
    /* the cart chip's MegaWire init (in the MegaWire code) sets the MW byte when the RAMDP header check passes; ours
       stands in */
    return SETUP_ENG | SETUP_MW | SETUP_SFX | SETUP_SEQ;
}
#endif

void printHex(void *src, u32 size) { (void)src; (void)size; }
