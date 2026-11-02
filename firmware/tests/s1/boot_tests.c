/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/s1/boot_tests.c - host test of the stage-1 boot (FW_S1, our new firmware; T-B1 to T-B10 are
 * the boot tests of docs/BOOT_SPEC.md section 9) on the x86 fake board, with a synthetic ROM (no game byte in this
 * test). Built and run by tools/fwbuild.py s1; exit 1 on a failed check.
 *
 * The boot under test is board/pocket/s1_board.c brd_boot's order (the board-independent steps: core/boot): the page,
 * the patches and header (bootpage.c), app start / app init (appinit.c), the MegaWire status, the enables, the
 * acknowledges, the release. The 0.2.6 interim modules are not linked (their own proof is tests/equiv/s1_equiv.py);
 * the album's bounded waits (T-B10) are tested on the real interim/album sources over host memory mapped at their
 * fixed addresses (board/host/memmap.c), with the MD+ block answering and the EverDrive FIFO stalled.
 *   T-B1  $1FEA bit 15 = 0 at the release            T-B2  $1FE6 bit 12 = 0, bits 0-2 = the MegaWire option
 *   T-B4  $1E4 = $FF00; $1E0-$1E3 = the ROM's own letters for every Console (BOOT-07 dropped 2026-10-16: the letters
 *         are the cart's, not the console's)
 *   T-B5  cart RAM $0000-$1FDF = ROM except the four D45 words (our
 *   firmware audit's difference D45) and $1E4; the ROM image's $81104 patch
 *   T-B6  the 68000's $1FE4 = 0004 | model for every model value (busy at rest, nothing streamed)
 *   T-B8  no stale post: CAUSE clear, the mailboxes 0, at the release            T-B9  the watchdog state (D35)
 *   T-B10 the album stalled: mdp_init returns within its bound, the boot carries on
 *   + the chip's app-init register writes in order (docs/CART_FPGA_SPEC.md
 *   3.2; the oracle run checked them against the chip) */
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
#define CHECK(c) do { checks++; if (!(c)) { fails++; printf("FAIL boot_tests.c:%d %s\n", __LINE__, #c); } } while (0)

/* ---- bodies: none runs in this test (no post reaches one); the album hooks are the T-B10 part --------------- */
void body_88(uint8_t lo) { (void)lo; }
void body_c9(uint8_t lo) { (void)lo; }
void body_ca(uint8_t lo) { (void)lo; }
void body_8d(uint8_t lo) { (void)lo; }
void body_d1(uint8_t lo) { (void)lo; }
void body_d2(uint8_t lo) { (void)lo; }
void body_d3(uint8_t lo) { (void)lo; }
void body_d5(uint8_t lo) { (void)lo; }
void body_ad(uint8_t lo) { (void)lo; }
void body_ae(void) { }
void body_af(uint8_t m, uint8_t q) { (void)m; (void)q; }
#if !PPM_RELEASE
void body_af_replied(void) { }
#endif
void body_b0(void) { }
void body_b1(void) { }
void body_ec(uint16_t s) { (void)s; }
uint32_t body_block_addr(uint16_t b) { return (uint32_t)b * 0x200u; }
uint32_t body_load_list(const uint32_t **l) { static const uint32_t none[1]; *l = none; return 0u; }
void body_dec_scratch(void) { }
void body_db(uint16_t a0, uint16_t a1, uint16_t a2, uint8_t mode) { (void)a0; (void)a1; (void)a2; (void)mode; }
void body_da_direct(uint32_t src, uint16_t dst, uint8_t mode) { (void)src; (void)dst; (void)mode; }
void body_e7(void) { }
uint32_t job_unpack(const disp_job_t *j) { (void)j; return 0u; }
uint32_t job_eep_read(const disp_job_t *j) { (void)j; return 0u; }
uint32_t job_eep_write(const disp_job_t *j) { (void)j; return 0u; }
void job_scale_save(void) { }
void job_scale_setup(void) { }
void job_rescale(const uint16_t a[4]) { (void)a; }
void job_restore(void) { }
uint32_t job_setup(const uint32_t l[8], uint32_t mw) { (void)l; (void)mw; return SETUP_ENG | SETUP_MW | SETUP_SFX | SETUP_SEQ; }
void s1_au_note(uint32_t kind, uint32_t arg) { (void)kind; (void)arg; }   /* interim/album's TEST audio-call log */
#if !PPM_RELEASE
#include "s1_interim.h"
s1_audio_stats_t s1_audio_stats;                    /* interim/album/mdp.c's TEST album record (stage 1td) */
#endif

/* ---- a synthetic 8 MB ROM: word i = a hash of i (every word distinct enough to see a stray write) -------------- */
static uint16_t rom[BRD_ROM_BYTES / 2u];
static uint16_t rom_w(uint32_t i) { return (uint16_t)(i * 0x9E37u ^ (i >> 7) ^ 0x5A5Au); }

static void boot(uint32_t options)
{
    uint32_t i;
    hb_reset();
    for (i = 0; i < BRD_ROM_BYTES / 2u; i++)
        rom[i] = rom_w(i);
    hb.rom = rom;
    hb.options = options;
    sched_init();
    boot_page();
    app_start();
    boot_mw_status();
    brd_menu_mute(1u);
    brd_opt_at_reset(0u);
    brd_cause_ack(BRD_CAUSE_ALL);
    brd_msi(0u);
    brd_timer_disarm();
    brd_lines_on(BRD_LINES_ALL);
    brd_irq_enable();
    brd_md_hold(0u);
}

/* ---- T-B10: the interim album over host memory at the firmware's fixed MMIO addresses ----------------------- */
int host_map(void);                                 /* board/host/memmap.c: 0x1000000..0x7900000 */
void mdp_init(void);
extern unsigned char mdp_on;
#define MDP_BLOCK               (0x7000000u + 0x3F7F6u)    /* interim/album/mdp.c MDP: ADDR_MDP + 0x3F7F6 */
#define ED_FIFO                 0x7800000u                 /* interim/album/everdrive.c EDFIFO: ADDR_FIFO */

static void test_album_stall(void)
{
    volatile uint16_t *mdp = (volatile uint16_t *)(uintptr_t)MDP_BLOCK;
    volatile uint32_t *fifo = (volatile uint32_t *)(uintptr_t)ED_FIFO;
    uint32_t t0, dt;
    if (!host_map()) {
        printf("FAIL boot_tests.c: cannot map host memory for T-B10\n");
        fails++;
        return;
    }
    hb_reset();
    mdp[0] = 0x5241;                                /* the MD+ id words: the block answers (mdp.c MDP_ID0/1) */
    mdp[1] = 0x5445;
    fifo[1] = 0x80u;                                /* status: cpu_rxf = 1 = the CPU FIFO is empty, forever */
    t0 = brd_now();
    mdp_init();                                     /* must give up, bounded (FW_S1 guards, BOOT-02) */
    dt = brd_now() - t0;
    CHECK(mdp_on == 0u);                            /* the album stays off */
    CHECK(dt < 4u * 50u * CLK_MS_CYCLES);           /* bound: the flush wait + one read wait (50 ms each) + slack */
    CHECK(dt >= 50u * CLK_MS_CYCLES);               /* it really waited for its bound (the stall was seen) */
    printf("T-B10: mdp_init gave up after %u cycles (%u ms)\n", (unsigned)dt, (unsigned)(dt / CLK_MS_CYCLES));
}

int main(void)
{
    static const uint32_t models[] = { 0x000u, 0x700u, 0x400u, 0x600u, 0x040u, 0x100u, 0x200u, 0x300u };
    uint32_t i, k, n0;
    uint16_t w;

    /* T-B1, T-B2, T-B4, T-B5, T-B8, T-B9 and the app-init writes, MegaWire Off */
    boot(0u);
    CHECK(!hb.hold);
    CHECK((hb_68k_read(BRD_FREG_FEA) & 0x8000u) == 0u && hb_68k_read(BRD_FREG_FEA) == 0u);    /* T-B1, BOOT-08 */
    CHECK((hb_68k_read(BRD_FREG_FE6) & 0x1000u) == 0u);                                       /* T-B2 */
    CHECK((hb_68k_read(BRD_FREG_FE6) & 7u) == 0u);
    CHECK(hb_68k_read(BRD_FREG_FE6) == 0xC000u);    /* app init 0x4000 + app start bit 15 (chip: the same word) */
    CHECK(hb.ram[0x1E4u / 2u] == 0xFF00u);                                                    /* T-B4, BOOT-06 */
    CHECK(hb.ram[0x1E0u / 2u] == rom_w(0x1E0u / 2u) && hb.ram[0x1E2u / 2u] == rom_w(0x1E2u / 2u));   /* letters */
    for (i = 0, k = 0; i < 0x1FE0u / 2u; i++) {                                               /* T-B5, BOOT-04/05 */
        uint32_t a = i * 2u;
        if (a == 0x1D1Cu)
            CHECK(hb.ram[i] == 0x0004u);
        else if (a == 0x1D2Cu)
            CHECK(hb.ram[i] == (uint16_t)(rom_w(i) | 0x0100u));
        else if (a == 0x1562u)
            CHECK(hb.ram[i] == 0x0001u);
        else if (a == 0x1564u)
            CHECK(hb.ram[i] == 0x0100u);
        else if (a == 0x1E4u)
            ;
        else
            k += hb.ram[i] != rom_w(i);
    }
    CHECK(k == 0u);
    CHECK(hb.ram[0x1FE0u / 2u] == 0u);              /* the register page is never written as RAM */
    CHECK(rom[0x81104u / 2u] == 0x4E71u);           /* the ROM image patch */
    CHECK(hb.cause == 0u && hb.freg[BRD_FREG_FEC >> 1] == 0u);                                 /* T-B8 */
    CHECK(hb.menu_mute == 1u && hb.opt_at_reset == 0u);                                       /* the enables */
    CHECK(!hb.window_en && !hb.mini_view && !hb.stream_valid);                                /* BOOT-12/13 */
    CHECK(disp_g.app_ready == 1u);
    CHECK(disp_g.wd_arm == 1u && disp_g.wd_count == 1u);                     /* T-B9: app init 0x0801F9F8 / 0x0801FA04 */
    /* the chip's app-init register writes, in order (CART_FPGA_SPEC.md 3.2; the appinit phase of the chip trace) */
    {
        static const uint32_t want[] = { (BRD_FREG_FF0 << 16) | 0x8000u, (BRD_FREG_FF2 << 16) | 0x8000u,
                                         (BRD_FREG_FE6 << 16) | 0x4000u, (BRD_FREG_FE4 << 16) | 0x46F8u,
                                         (BRD_FREG_FEC << 16) | 0x0000u, (BRD_FREG_FE6 << 16) | 0xC000u,
                                         (BRD_FREG_FE4 << 16) | 0x66F8u };
        CHECK(hb.nlog == sizeof want / sizeof want[0]);
        for (i = 0; i < hb.nlog && i < sizeof want / sizeof want[0]; i++)
            CHECK(hb.log[i] == want[i]);
    }
    /* T-B9: the 9494 runs the watchdog (armed -> 2, count 0); 84 disarms it */
    n0 = hb.nlog;
    hb_68k_write(BRD_FREG_FEC, 0x9494u);
    (void)brd_now();
    CHECK(disp_g.wd_arm == 2u && disp_g.wd_count == 0u);
    CHECK(hb.nlog > n0 && hb.freg[BRD_FREG_FEC >> 1] == 0u);
    hb_68k_write(BRD_FREG_FEA, 0x8400u);
    (void)brd_now();
    CHECK(disp_g.wd_arm == 0u && disp_g.wd_count == 0u);
    CHECK(hb.ram[0x0006u / 2u] == 0x8200u);                                   /* 84: the reset vector's low word */
    CHECK(!hb.window_en && hb.mini_view);                                     /* 84: window off, the mini view */

    /* T-B2: MegaWire On (option bits 16-18 = 7) */
    boot(0x70000u);
    CHECK((hb_68k_read(BRD_FREG_FE6) & 7u) == 7u);
    CHECK((hb_68k_read(BRD_FREG_FE6) & 0x1000u) == 0u);
    CHECK(st_shadow(ST_FE6) == hb.freg[BRD_FREG_FE6 >> 1]);  /* the status helper's shadow keeps the bits */

    /* T-B6: the 68000's $1FE4 = busy at rest | the model bits, for every model value; region bit: letters unchanged */
    for (i = 0; i < sizeof models / sizeof models[0]; i++) {
        boot(models[i] | (i & 1u ? BRD_OPT_JAP : 0u));
        w = hb_68k_read(BRD_FREG_FE4);
        CHECK(w == (uint16_t)(0x0004u | models[i]));
        CHECK(hb.ram[0x1E0u / 2u] == rom_w(0x1E0u / 2u) && hb.ram[0x1E2u / 2u] == rom_w(0x1E2u / 2u));
    }

    test_album_stall();
    printf("boot_tests: %d checks, %d failed\n", checks, fails);
    return fails ? 1 : 0;
}
