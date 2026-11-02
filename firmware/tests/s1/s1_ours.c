/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/s1/s1_ours.c - the stage-1 firmware (FW_S1, our new firmware) on the x86 fake board, as a replay side over the
 * pipe protocol of the audit harness (our test harness outside this tree)
 * (tests/equiv/hostside.py; board/host/ours_host.c is the 0.2.6 side). Built by tools/fwbuild.py s1 (not run
 * there); driven by the stage-1 equivalence and oracle rigs, which live outside the tree with their inputs.
 *
 * What runs: the stage-1 boot of board/pocket/s1_board.c (the boot page, the interim modules, app start / app init,
 * the MegaWire status, the enables, the acknowledges, the release), then per post the 68000's write of $1FEA on the
 * fake board (CAUSE.B, the busy guard), the board point at which L1 takes it, and L2c drained (board work, then
 * jobs) before the reply: the "fast mode" of the plan (post -> L1 -> L3 drained -> compare). A 68000 write of $1FEC in
 * the RAM stream ('w' / 'W' covering it) is a mailbox-A post the same way (the 9494 frame tick).
 *
 * Protocol (requests on stdin, replies on stdout, little-endian): as ours_host.c -
 *   L u32 n + n bytes   ROM (68000 byte order)              R   boot (power-on)               O u32  option word
 *   W/w u16 off, u16 n + n bytes  RAMDP bytes at MCU offset off (the register page: only $1FEC, as a post)
 *   P u16 word          post -> 8192 B cart RAM (68000 view of $1FE0-$1FFF), 24 B "FPGAIO" {ctrl: hold | window << 2,
 *                       0, SPTR, VOL_SFX, VOL_BGM, 0}, u32 0 (no printf), u32 n + n x 8 B audio log
 *   M u32 off, u32 n    SDRAM (workspace, 2 MB) / flash (off >= 0x1000000) bytes   D / S  SDRAM diff / shadow
 *   A                   cart RAM + FPGAIO      B u32 off, u32 n  battery save bytes      G  u32 0 (no globals)
 *   Q quit
 * plus the stage-1 requests:
 *   X                   the register-write log since the boot or the last X: u32 n, n x u32 (off << 16 | value, or
 *                       tag << 24 | value for SPTR / GO; the fake board keeps 4,096)
 *   T u16 word          a 68000 write of $1FEC (mailbox A) -> 'k'
 *   V                   the 68000 view of $1FE0-$1FFF (16 x u16) and disp_g's flags -> u32 n + n bytes
 * and the chip lockstep's (tests/equiv/chiplock_s1.py):
 *   p u16 word          post as 'P', reply 'k' only (the rig's fast-forward to a checkpoint)
 *   Y                   the MCU side of the register file: the 16 stored words as an MCU read returns them (only
 *                       $1FE4/6/A/C are stored, docs/MCU_INTERFACE.md 3.4), then the 16 accessor shadows: 64 bytes */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <io.h>
#include <fcntl.h>
#include <setjmp.h>
#include "board.h"
#include "sched.h"
#include "sched_hooks.h"
#include "disp.h"
#include "appinit.h"
#include "s1_interim.h"
#include "s1_host_album.h"
#include "wdog.h"

#define ROM_WORDS               (BRD_ROM_BYTES / 2u)
/* the ROM twice: the flash view aliases every 8 MB (docs/MCU_INTERFACE.md
   section 3), so a wild offset reads the mirror */
#define SDR_SPAN                BRD_WORKSPACE_BYTES
static uint16_t rom_words[2u * ROM_WORDS];
static uint8_t sdr_shadow[SDR_SPAN];
static uint8_t save_keep[BRD_SAVE_BYTES];
static uint32_t log_from;

/* event_post's fatal half (in the image: fatal_halt, core/trace/fatal.c):
   here the post ends where the chip's MCU halts; nothing is finished */
static jmp_buf post_jb;
static int in_post;
static uint32_t fatal_code;
void fatal_halt(uint32_t code, uint32_t a, uint32_t b)
{
    (void)a;
    (void)b;
    fatal_code = code;
    if (in_post)
        longjmp(post_jb, 1);
    exit(8);
}

static void rd(void *p, size_t n) { if (n && fread(p, 1, n, stdin) != n) exit(0); }
static void wr(const void *p, size_t n) { fwrite(p, 1, n, stdout); }
static void w32(uint32_t v) { wr(&v, 4); }

static void drain(void)
{
    while (sched_l2c_once() || sched_thread_once())     /* L2c's pass (the thread in an
                                                           earlier version), then the thread's
                                                           TEST diagnostics (the SAT snapshot; no brain here) */
        ;
}

static void boot(void)
{
    uint32_t opt = hb.options;
    memcpy(save_keep, hb.save, sizeof save_keep);           /* battery save survives a reset */
    hb_reset();
    memcpy(hb.save, save_keep, sizeof save_keep);
    hb.options = opt;
    hb.rom = rom_words;
    /* board/pocket/s1_board.c brd_boot, in its order */
    sched_init();
    boot_page();
    s1_interim_boot();
    app_start();
    boot_mw_status();
    brd_menu_mute(1u);
    brd_opt_at_reset(0u);
    brd_cause_ack(BRD_CAUSE_ALL);
    brd_msi(0u);
    brd_timer_disarm();
    wdog_start();
    brd_lines_on(BRD_LINES_ALL);
    brd_irq_enable();
    brd_md_hold(0u);
    drain();
}

static void ram_image(uint8_t *out)
{
    unsigned off;
    memcpy(out, hb.ram, 0x2000);
    for (off = 0; off < 0x20u; off += 2u) {
        uint16_t v = hb_68k_read(off);
        memcpy(out + 0x1FE0 + off, &v, 2);
    }
}

static void fpgaio(uint8_t *out)
{
    uint32_t f[6] = { hb.hold | (hb.window_en << 2), 0u, hb.sptr, hb.vol_sfx, hb.vol_bgm, 0u };
    memcpy(out, f, 24);
}

static void mbx_post(unsigned off, uint16_t v)
{
    in_post = 1;
    if (setjmp(post_jb) == 0) {
        hb_68k_write(off, v);
        (void)brd_now();                                    /* a board point: L1 takes the post */
        drain();
    } else {                                                /* 85 / a fatal path: the MCU stops here */
        hb.no_irq = 1;
    }
    in_post = 0;
}

static void ram_write(uint16_t off, const uint8_t *data, uint16_t n)
{
    uint32_t a;
    for (a = off; a < (uint32_t)off + n && a < 0x2000u; a++) {
        if (a >= 0x1FE0u)
            continue;                                       /* the register page is not RAM */
        ((uint8_t *)hb.ram)[a] = data[a - off];
    }
    if (off <= 0x1FECu && (uint32_t)off + n >= 0x1FEEu) {   /* the 68000's word write of $1FEC */
        uint16_t v;
        memcpy(&v, data + (0x1FECu - off), 2);
        mbx_post(BRD_FREG_FEC, v);
    }
}

int main(void)
{
    static uint8_t buf[0x2000 + 64];
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
    hb_reset();
    hb.rom = rom_words;
    for (;;) {
        int op = fgetc(stdin);
        if (op == EOF || op == 'Q')
            break;
        if (op == 'L') {
            uint32_t n, i;
            uint8_t *b;
            rd(&n, 4);
            b = (uint8_t *)malloc(n ? n : 1u);
            rd(b, n);
            memset(rom_words, 0, sizeof rom_words);
            for (i = 0; i + 1u < n && i / 2u < ROM_WORDS; i += 2u)
                rom_words[i / 2u] = (uint16_t)((b[i] << 8) | b[i + 1u]);
            memcpy(rom_words + ROM_WORDS, rom_words, ROM_WORDS * 2u);
            free(b);
            wr("k", 1);
        } else if (op == 'O') {
            uint32_t w;
            rd(&w, 4);
            hb.options = w;
            wr("k", 1);
        } else if (op == 'R') {
            s1_au_n = 0;
            boot();
            wr("k", 1);
        } else if (op == 'W' || op == 'w') {
            uint16_t off, n;
            rd(&off, 2);
            rd(&n, 2);
            rd(buf, n);
            ram_write(off, buf, n);
            if (op == 'W')
                wr("k", 1);
            else
                continue;
        } else if (op == 'P') {
            uint16_t word;
            rd(&word, 2);
            s1_au_n = 0;
            mbx_post(BRD_FREG_FEA, word);
            ram_image(buf);
            wr(buf, 0x2000);
            fpgaio(buf);
            wr(buf, 24);
            w32(0u);
            w32((uint32_t)s1_au_n);
            wr(s1_au, (size_t)s1_au_n * 8u);
        } else if (op == 'T') {
            uint16_t word;
            rd(&word, 2);
            mbx_post(BRD_FREG_FEC, word);
            wr("k", 1);
        } else if (op == 'p') {
            uint16_t word;
            rd(&word, 2);
            s1_au_n = 0;
            mbx_post(BRD_FREG_FEA, word);
            wr("k", 1);
        } else if (op == 'Y') {
            unsigned off;
            for (off = 0; off < 0x20u; off += 2u) {
                uint16_t v = (off == BRD_FREG_FE4 || off == BRD_FREG_FE6 || off == BRD_FREG_FEA || off == BRD_FREG_FEC)
                    ? hb.freg[off >> 1] : 0u;
                wr(&v, 2);
            }
            wr(hb.shadow, sizeof hb.shadow);
        } else if (op == 'M') {
            uint32_t off, n, i;
            rd(&off, 4);
            rd(&n, 4);
            for (i = 0; i < n; i++) {
                uint32_t a = off + i;
                uint8_t v = 0;
                if (a >= 0x1000000u) {
                    a -= 0x1000000u;
                    if (a < BRD_ROM_BYTES)
                        v = ((uint8_t *)rom_words)[a];
                } else if (a < SDR_SPAN) {
                    v = hb.workspace[a];
                }
                fputc(v, stdout);
            }
        } else if (op == 'D' || op == 'S') {
            static uint32_t offs[SDR_SPAN / 256u];
            uint32_t c = 0, g;
            for (g = 0; g < SDR_SPAN; g += 256u) {
                if (memcmp(hb.workspace + g, sdr_shadow + g, 256)) {
                    if (op == 'D')
                        offs[c++] = g;
                    memcpy(sdr_shadow + g, hb.workspace + g, 256);
                }
            }
            if (op == 'D') {
                w32(c);
                wr(offs, (size_t)c * 4u);
            } else {
                wr("k", 1);
            }
        } else if (op == 'A') {
            ram_image(buf);
            wr(buf, 0x2000);
            fpgaio(buf);
            wr(buf, 24);
        } else if (op == 'B') {
            uint32_t off, n, i;
            rd(&off, 4);
            rd(&n, 4);
            for (i = 0; i < n; i++)
                fputc(off + i < BRD_SAVE_BYTES ? hb.save[off + i] : 0, stdout);
        } else if (op == 'G') {
            w32(0u);
        } else if (op == 'X') {
            uint32_t n = hb.nlog - log_from;
            w32(n);
            wr(hb.log + log_from, (size_t)n * 4u);
            hb.nlog = 0u;                                   /* restart the log (4,096 entries) */
            log_from = 0u;
        } else if (op == 'V') {
            unsigned off;
            uint8_t st[64];
            uint32_t k = 0;
            for (off = 0; off < 0x20u; off += 2u) {
                uint16_t v = hb_68k_read(off);
                memcpy(st + k, &v, 2);
                k += 2u;
            }
            st[k++] = disp_g.app_ready;
            st[k++] = disp_g.mixer;
            st[k++] = disp_g.eng_ready;
            st[k++] = (uint8_t)disp_g.wd_arm;
            st[k++] = (uint8_t)disp_g.wd_count;
            st[k++] = disp_g.q_wr;
            st[k++] = disp_g.q_rd;
            st[k++] = (uint8_t)(hb.guard | (hb.stream_valid << 1) | (hb.window_en << 2) | (hb.mini_view << 3));
            w32(k);
            wr(st, k);
        } else {
            fprintf(stderr, "s1_ours: bad op %d\n", op);
            return 9;
        }
        fflush(stdout);
    }
    return 0;
}
