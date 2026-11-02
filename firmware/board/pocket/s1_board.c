/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/s1_board.c - the Pocket board layer of the new-core firmware: the out-of-line board functions of
 * board/board.h, the boot crt0 enters, and the two interim board hooks.
 *
 * brd_boot = steps P1-P6 of docs/BOOT_SPEC.md section 1, with the 68000 held from the reset's first clock (CTRL resets
 * to 0x09, BOOT-01; crt0 writes HOLD again first):
 *   P3/P4  the boot page (the ROM file's own header letters), the 0.2.6 boot patches, the ROM patch, $1E4 = $FF00
 *          (core/boot/bootpage.c);
 *   -      the 0.2.6 modules and the album (interim/s1: ppmio, the sprite engine's init, mdp_init with bounded waits,
 *          the volumes), as 0.2.6's ppm_reset ran them before its release;
 *   P5     the chip's app start / app init (core/boot/appinit.c), then the MegaWire option status (BOOT-09);
 *   -      the board-control enables: MENU_MUTE_EN = 1 (a decision of the project plan; docs/STAGE1_PLAN.md item F1),
 *          OPT_AT_RESET_EN = 0 (question Q4);
 *   P6     acknowledge before enable (docs/MCU_INTERFACE.md 6.3.1), enable, then the release (bounded), last.
 * S1_CACHE4B images (test build 4b on): crt0 has already run the boot cache (board/pocket/boot: the stub and the
 * overlay, MCU_INTERFACE.md v1.3 21.1); the TEST image copies its record to the debug save (s1_cache4b.c).
 * Every wait before the release is bounded (BOOT-02): the album's in interim/album (FW_S1 guards), the release's here.
 * TEST: a boot milestone at each step (s1_boot_rec; the TEST telemetry stores it in the debug save). */
#include <stdint.h>
#include "board.h"
#include "s1_boot.h"
#include "sched.h"
#include "appinit.h"
#include "s1_interim.h"
#include "wdog.h"
#include "s1_glue.h"
#include "stats.h"
#include "dbgsave.h"
#include "s1_cache4b.h"
#if FW_MW
#include "mw.h"
#endif

/* the assembler's copies of pocket_map.h values (s1_boot.h) */
_Static_assert(S1_A_FIO_CTRL == POCKET_FIO_CTRL, "S1_A_FIO_CTRL");
_Static_assert(S1_A_CTRL_HOLD == POCKET_CTRL_HOLD, "S1_A_CTRL_HOLD");
_Static_assert(S1_A_SYSINFO_CLK == POCKET_SYSINFO_CLK && S1_A_SYSINFO_CLK + 4u == POCKET_SYSINFO_USER, "S1_A_SYSINFO");
#if S1_CACHE4B && FW_S5 && C4B_BUG != 16   /* the FW_S5 images: v1.3, FEAT checked for test build 5's
                                               blocks */
_Static_assert(S1_A_IFACE_PI_MAJOR == (POCKET_IFACE_ID >> 8) && S1_A_IFACE_MINOR == (POCKET_IFACE_ID & 0xFFu), "S1_A_IFACE");
_Static_assert(S1_A_FIO_FEAT == POCKET_FIO_FEAT &&
               S1_A_FEAT_NEED == (POCKET_FEAT_CACHE | POCKET_FEAT_BAR | POCKET_FEAT_SYNTH) &&
               S1_A_FEAT_IROM_KB == POCKET88_IROM_BYTES / 1024u &&
               (POCKET_FEAT_CARD5 & S1_A_FEAT_NEED) == S1_A_FEAT_NEED && !(POCKET_FEAT_CARD5 & POCKET_FEAT_SFXFIFO) &&
               ((POCKET_FEAT_CARD5 & POCKET_FEAT_IROM_MASK) >> POCKET_FEAT_IROM_SHIFT) == S1_A_FEAT_IROM_KB &&
               (POCKET_FEAT_CARD4A & S1_A_FEAT_NEED) != S1_A_FEAT_NEED,
               "S1_A_FEAT: card 5's FEAT carries what the stage-5 images drive, and card 4a's does not");
#elif S1_CACHE4B                        /* the S1_CACHE4B images (test build 4b on): v1.3 images (the
                                           header's version), FEAT checked */
_Static_assert(S1_A_IFACE_PI_MAJOR == (POCKET_IFACE_ID >> 8) && S1_A_IFACE_MINOR == (POCKET_IFACE_ID & 0xFFu), "S1_A_IFACE");
_Static_assert(S1_A_FIO_FEAT == POCKET_FIO_FEAT &&
               S1_A_FEAT_NEED == (POCKET_FEAT_CACHE | POCKET_FEAT_BAR | POCKET_FEAT_SFXFIFO | POCKET_FEAT_MDP) &&
               S1_A_FEAT_IROM_KB == POCKET_IROM_BYTES / 1024u &&
               (POCKET_FEAT_CARD4A & S1_A_FEAT_NEED) == S1_A_FEAT_NEED && !(POCKET_FEAT_CARD4A & POCKET_FEAT_SYNTH) &&
               ((POCKET_FEAT_CARD4A & POCKET_FEAT_IROM_MASK) >> POCKET_FEAT_IROM_SHIFT) == S1_A_FEAT_IROM_KB,
               "S1_A_FEAT: card 4a's FEAT carries what card 4b's images drive");
#else                                   /* the scheduler probe: no v1.3 register, so v1.2 boards still run it */
_Static_assert(S1_A_IFACE_PI_MAJOR == (POCKET_IFACE_ID >> 8) && S1_A_IFACE_MINOR == 2u &&
               S1_A_IFACE_MINOR <= (POCKET_IFACE_ID & 0xFFu), "S1_A_IFACE");
#endif
_Static_assert(S1_A_IRQ_MEI == POCKET_IRQ_MEI && S1_A_IRQ_MTI == POCKET_IRQ_MTI && S1_A_IRQ_MSI == POCKET_IRQ_MSI, "S1_A_IRQ");
_Static_assert(S1_A_MIE_MEIE == POCKET_MIE_MEIE && S1_A_MIE_MTIE == POCKET_MIE_MTIE && S1_A_MIE_MSIE == POCKET_MIE_MSIE,
               "S1_A_MIE");
_Static_assert(S1_A_MIE_MEIE == BRD_LINE_MEI && S1_A_MIE_MTIE == BRD_LINE_MTI && S1_A_MIE_MSIE == BRD_LINE_MSI, "BRD_LINE");

volatile s1_boot_rec_t s1_boot_rec __attribute__((section(".noinit.s1")));

/* the brain-call abort (buddy/s1_glue.c): the trap exit (s1_trap.S) reads the flag after L1 / L2a; images
   without the glue (the probe) keep this default: never an abort */
volatile uint32_t s1_brain_abort;
__attribute__((weak)) uint32_t s1_brain_resume(uint32_t mepc) { return mepc; }

static const board_handoff s1_handoff;      /* BOOT_SPEC.md 3: page_a = page_b = 0 in the new core */
const board_handoff *board_get_handoff(void) { return &s1_handoff; }

/* CTRL byte 0, read-modify-write (MCU_INTERFACE.md 4.1: bits 0, 4, 5 live there) */
static void ctrl_bit(uint32_t bit, uint32_t on)
{
    uint32_t s = brd_irq_save();
    uint32_t v = BRD_IO32(POCKET_FIO_CTRL) & 0xFFu;
    BRD_IO32(POCKET_FIO_CTRL) = on ? (v | bit) : (v & ~bit);
    brd_irq_restore(s);
}
void brd_md_hold(uint32_t hold) { ctrl_bit(POCKET_CTRL_HOLD, hold); }
void brd_menu_mute(uint32_t on) { ctrl_bit(POCKET_CTRL_MENU_MUTE, on); }
void brd_opt_at_reset(uint32_t on) { ctrl_bit(POCKET_CTRL_OPT_AT_RST, on); }
#if FW_S5
void brd_synth_blkie(uint32_t on) { ctrl_bit(POCKET_CTRL_BLKIE, on); }   /* the main-loop pass after a block */

/* FW_S5 (test build 5 on): the DT analogue stand-in (MCU_INTERFACE.md v1.3 3.10.1 DTOUT: [15:0] GAIN Q8.8, [16] INVERT,
   [20:17] DCK; reset 0 = silent, so every boot writes it; the board layer's, no chip field). Decision 5 of the synth
   design, "plain first": one gain, a DC blocker, the polarity. Estimated; none of it is established from a capture:
     GAIN 1410 (x 5.51): the DT wave level the cart-engine renders B Jam heard as right in both modes give, the
          YM-DAC level x 269/256 (from our cart-engine balance study), on this core's YM-DAC scale: 48 output units a
          DAC step (Nuked's 2612 DAC through audio_cond: 2 x 3 x 4 x 2, read in the RTL); over 18 tracks' renders
          1,274-1,485 (1.33 dB spread), 1,410 the upper of the two middle values (track 0F; the median, 1,402, is
          0.05 dB lower, far inside the model's spread);
     INVERT 0 (the polarity: no capture yet); DCK 11 (a one-pole DC blocker at 48,000 / (2 pi 2^11) = 3.7 Hz, the
          coupling capacitor; the renders' console high-pass is 5 Hz).
   The GAIN assumes test build 5's core_top sums the synth's DT pair into the mix 1:1, as it sums the cart SFX
   pair (paprium-pocket target/pocket/core_top.sv mix_l), not through the album's 294/256 CDDA multiplier (that would
   be +1.2 dB). The regression on the raw DT captures gave no stable balance or sign, so no value here is from a
   capture; docs/ALLOWLIST.md, row B44 (decision 5, approved) names the stand-in.
   These are the starting values (a project decision): a listening session on test build 5 checks the DT / YM
   balance by ear against B Jam's cart; a level fix is a firmware swap. */
#define BRD_DTOUT_GAIN          1410u
#define BRD_DTOUT_INVERT        0u
#define BRD_DTOUT_DCK           11u
#define BRD_SY_DTOUT            0x03Cu
_Static_assert(POCKET_SYN_DTOUT == POCKET_SY_BASE + BRD_SY_DTOUT && BRD_DTOUT_GAIN <= 0xFFFFu && BRD_DTOUT_DCK <= 15u,
               "DTOUT (MCU_INTERFACE v1.3 3.10.1)");
_Static_assert(C4B_H_STREAM == 8u, "brd_bank_ok reads the cache header's ROM key at word 8 (board_impl.h)");
#endif

void brd_milestone(uint32_t code)
{
#if PPM_RELEASE
    (void)code;
#elif TDIAG_LEAN                                            /* lean FW_S5 TEST (test build S3a on; core/trace/tdiag.h):
                                                               no milestones; the fatal halt's debug save write stays */
    if (code == ST_MS_FATAL)
        dbgsave_now();
#else
    s1_boot_rec.magic = S1_REC_MAGIC;
    s1_boot_rec.code = code;
    s1_boot_rec.time = brd_now();
    ST_MARK(code);                                          /* the TEST telemetry: every milestone's first time */
#if !S1_PROBE                                               /* (test build 5: the FW_S5 images' debug save is version
                                                               9) */
    if (code == ST_MS_FATAL)                                /* the fatal halt (core/trace/fatal.c): interrupts are off */
        dbgsave_now();                                      /* for good, so the debug save is written here (Q1) */
#endif
#endif
}

/* the cart's MCU-only reset (docs/ALLOWLIST.md, row B17): hold the 68000, mask everything, run crt0 again; the RTL
   state stays */
void brd_full_reset(void)
{
    brd_md_hold(1u);
    __asm__ volatile ("csrci mstatus, 8\n\tcsrw mie, zero\n\tj _start" : : : "memory");
    __builtin_unreachable();
}

/* ---- interim board hooks (s1_interim.h; removed with the album path for the synth) ------------------------------ */
void s1_board_vol(uint32_t which, uint8_t v)
{
    BRD_IO32(which == S1_VOL_BGM ? POCKET_FIO_VOL_BGM : POCKET_FIO_VOL_SFX) = v;
}
void *s1_board_sfx(void) { return (void *)(uintptr_t)POCKET_SFX_BASE; }

#if S1_PROBE
/* the scheduler probe image (tests/s1/sched_probe.c, the RV32 fuzz rig and the GHDL bench): the skeleton boot of the
   trap entry and crt0, no boot page, no interim modules, the 68000 kept held (the rig plays it) */
void brd_boot(void)
{
    brd_milestone(S1_MS_CRT0);
    sched_init();
    brd_cause_ack(BRD_CAUSE_ALL);
    brd_msi(0u);
    brd_timer_disarm();
    brd_lines_on(BRD_LINES_ALL);
    brd_irq_enable();
    brd_milestone(S1_MS_IRQ_ON);
    l3_thread();
}
#else
/* ---- the release: HOLD and RSTSEEN cleared in one read-modify-write, then HOLD read back (bounded) ----------- */
#define S1_RELEASE_TRIES        1000u
static void s1_release(void)
{
    uint32_t n;
    uint32_t v = BRD_IO32(POCKET_FIO_CTRL) & 0xFFu;
    BRD_IO32(POCKET_FIO_CTRL) = v & ~(POCKET_CTRL_HOLD | POCKET_CTRL_RSTSEEN);
    for (n = 0; n < S1_RELEASE_TRIES && (BRD_IO32(POCKET_FIO_CTRL) & POCKET_CTRL_HOLD); n++)
        ;
    brd_milestone(n < S1_RELEASE_TRIES ? S1_MS_RELEASED : S1_MS_RELEASE_SLOW);
}

void brd_boot(void)
{
    brd_milestone(S1_MS_CRT0);
    sched_init();
#if S1_CACHE4B_REC
    s1_cache4b_take();                  /* test build 4b, TEST: the old record's cache entries, before
                                           dbgsave_start clears them */
#endif
    boot_page();                        /* P3, P4 */
    brd_milestone(S1_MS_PAGE);
    s1_interim_boot();                  /* the 0.2.6 modules and the album (bounded) */
    brd_milestone(S1_MS_INTERIM);
    app_start();                        /* P5: app start / app init, as the chip's */
#if !FW_MW
    boot_mw_status();                   /* P5: the MegaWire option status (the first new-core firmware; nothing with
                                           the option Off). With the MegaWire code: the SRAM image's check is the
                                           thread's first work after the release (core/mw/mw_boot.c), so the 68000
                                           starts at test build 5's time (the synth build tested on hardware) */
#endif
    brd_milestone(S1_MS_APPINIT);
    brd_menu_mute(1u);                  /* CTRL.MENU_MUTE_EN: music and SFX pause while the Pocket menu is open */
    brd_opt_at_reset(0u);               /* CTRL.OPT_AT_RESET_EN: the dormant latch stays off (0.2.6's live options) */
#if FW_S5
    brd_synth_blkie(1u);                /* CTRL.BLKIE: every block the synth mixes raises CAUSE.BLK, and
                                           L2b runs the chip's main-loop pass after it (core/sched/sched.c) */
    brd_synth_wr32(BRD_SY_DTOUT, BRD_DTOUT_GAIN | BRD_DTOUT_INVERT << 16 | BRD_DTOUT_DCK << 17);   /* FW_S5 (test build
                                                                                                      5 on, above) */
    brd_cause_ack(BRD_CAUSE_ALL | BRD_CAUSE_BLK);
#else
    brd_cause_ack(BRD_CAUSE_ALL);       /* rule 6.3.1: acknowledge before enable (the 68000 is held: no real post) */
#endif
    brd_msi(0u);
    brd_timer_disarm();
    buddy_s1_boot();                    /* XLINK LCLR of CPU MATE's (buddy) send / late flags */
    dbgsave_start();                    /* TEST: the debug save: the size probe, then a write every TIM7 period
                                           (test build 5's FW_S5 images: version 9) */
#if S1_CACHE4B_REC
    s1_cache4b_record();                /* S1_CACHE4B TEST (test build 4b on): the boot cache's block (version 8; 9 in
                                           the FW_S5 images) behind the record's PREV2 */
#endif
    wdog_start();                       /* the TIM7 tick: a deadline CLK_TIM7 ahead, so the MTI level is low */
    brd_lines_on(BRD_LINES_ALL);        /* mie was 0, so the CPU latch is empty */
    brd_irq_enable();
    sched_work_post();                  /* a job app init queued (the MegaWire screen boot; unreachable on ours, row
                                           B18): L2c runs it (since an earlier scheduler change, jobs no longer run in
                                           the thread) */
    brd_milestone(S1_MS_IRQ_ON);
    s1_release();                       /* P6: the last step (BOOT-02) */
    l3_thread();
}
#endif
