/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* ours_host.c - paprium-fw board/host: OUR cart firmware compiled for the x86 host, driven over a pipe. This is the
 * "ours" side of our comparison harness, which runs the cart chip's program and this firmware side by side (the
 * harness is not in this repository; its Python side drives this program as OursSide(exe=...)).
 *
 * Derived from the harness's own host program of the same name (md5 9799ff8b): same pipe protocol, plus the 'O'
 * request (option word).
 * Unity build of the SAME sources the Pocket images are built from (fwbuild.json "host"): legacy/026/mame.c and
 * legacy/026/paprium.c, through board/host/appmain.h. Nothing in the firmware logic is re-implemented: ppm_reset(),
 * ppm_cmd_handler() and every command handler run as compiled from the tree. Only the board edges are stubbed: printf
 * (captured; compiled out in the release variant, as on the Pocket), the MD+ / everdrive CD path (mdp_*), the SFX
 * player entry points (sfx_*), which are LOGGED with their arguments (the interface the 68000 drives), not executed,
 * and the CPU MATE glue's buddy_event (only reachable from ppm_start's main loop, which the harness does not run).
 *
 * Memory: memmap.c reserves 0x1000000..0x7900000 so ADDR_FPGIO / ADDR_RAMDP / ADDR_SDR / ADDR_FLA / ADDR_BRM / ADDR_SFX /
 * ADDR_MDP are real host memory at the firmware's own addresses (the same trick our earlier host models used).
 *
 * Pipe protocol (stdin requests, stdout replies, little-endian, binary):
 *   'L' u32 n, n bytes   load ROM (68000 byte order) into flash at ADDR_FLA, byte-swapped per word like the cart's bus
 *   'R'                  ppm_reset()
 *   'W' u16 off, u16 n, n bytes   raw write into RAMDP at MCU byte offset off (the caller does the 68000 A^1 swap)
 *   'w'                  same as 'W' without the 'k' reply (bulk replay)
 *   'P' u16 word         post: ramdp->reg_cmd = word; ppm_cmd_handler()     -> reply block (below)
 *   'M' u32 off, u32 n   read SDRAM bytes                                    -> n bytes
 *   'D'                  SDRAM diff since the last 'D' (or 'S'), 8 MB, 256-byte granules -> u32 count, count x (u32 off)
 *   'S'                  re-take the SDRAM shadow (no reply but 'k')
 *   'A'                  read RAMDP (8192) + FPGAIO (24) without posting
 *   'G'                  globals block                                       -> u32 n, n bytes (layout in our harness)
 *   'O' u32 word         set the MCU GPIO input (the core's option word: Console $1FE4 bits, MegaWire $1FE6 field in
 *                        [18:16]); read by the next 'R'. 0 = the default options. (paprium-fw addition)
 *   'B' u32 off, u32 n   read BRAM bytes                                     -> n bytes
 *   'Q'                  quit
 * Reply block for 'P': 8192 bytes RAMDP after, 24 bytes FPGAIO, u32 printf bytes + text, u32 audio-log entries x 8 bytes.
 */
#include "mame.c"
#include "paprium.c"
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <io.h>
#include <fcntl.h>

int host_map(void);
volatile uint32_t host_gpio_input = 0;      /* GPIO_INPUT (board/host/host_neorv32.h) */
void buddy_event(uint32_t ctrl) { (void) ctrl; }

static char pf_buf[8192];
static int pf_len = 0;
int host_printf(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt);
    int n = vsnprintf(pf_buf + pf_len, sizeof pf_buf - pf_len, fmt, ap);
    va_end(ap);
    if (n > 0) { pf_len += n; if (pf_len > (int) sizeof pf_buf - 1) pf_len = sizeof pf_buf - 1; }
    return n;
}
void printHex(void *src, u32 size) { (void) src; (void) size; }

/* audio entry points: logged (kind, arg, cmd_args[0..2]) */
typedef struct { uint8_t kind, arg; uint16_t a0, a1, a2; } AuLog;
static AuLog au[256]; static int au_n = 0;
static void au_put(uint8_t k, uint8_t a) {
    if (au_n < 256) { au[au_n].kind = k; au[au_n].arg = a; au[au_n].a0 = ppmio.ramdp->cmd_args[0];
                      au[au_n].a1 = ppmio.ramdp->cmd_args[1]; au[au_n].a2 = ppmio.ramdp->cmd_args[2]; au_n++; }
}
void sfx_play(u8 a) { au_put(1, a); }
void sfx_loop(u8 a) { au_put(2, a); }
void sfx_stop(u8 a) { au_put(3, a); }
void sfx_player_update() {}
void mdp_init() { au_put(10, 0); }
void mdp_play(u8 t) { au_put(11, t); }
void mdp_play_once(u8 t) { au_put(12, t); }
void mdp_stop() { au_put(13, 0); }
void mdp_set_vol(u8 v) { au_put(14, v); }

#define SDR_SPAN 0x800000u
static uint8_t *sdr_shadow;

static void rd(void *p, size_t n) { if (n && fread(p, 1, n, stdin) != n) exit(0); }
static void wr(const void *p, size_t n) { fwrite(p, 1, n, stdout); }
static void w32(uint32_t v) { wr(&v, 4); }

static void globals(void) {
    /* layout: u32 version=1; ppm_vram_slots[64] (6 B each); u16 ppm_vram_max_slot; u16 pad;
       ppm_object_handles[64] as raw bytes (sizeof ppm_obj each); u32 sizeof(ppm_obj); u32 ppm_block_unpack_addr;
       u32 ppm_sptr_shadow; u32 tick_ctr; u16 cmd_resp; u16 pad; u32 ppm_anim_data_base_addr; u32 ppm_gfx_blocks_base_addr;
       u32 ppm_sfx_base_addr */
    static uint8_t b[16384]; uint32_t n = 0;
#define PUT(p, s) do { memcpy(b + n, (p), (s)); n += (s); } while (0)
    uint32_t v = 1; PUT(&v, 4);
    PUT(ppm_vram_slots, sizeof ppm_vram_slots);
    uint16_t ms = ppm_vram_max_slot, z = 0; PUT(&ms, 2); PUT(&z, 2);
    v = sizeof(ppm_obj); PUT(&v, 4);
    PUT(ppm_object_handles, sizeof ppm_object_handles);
    v = ppm_block_unpack_addr; PUT(&v, 4);
    v = ppm_sptr_shadow; PUT(&v, 4);
    v = tick_ctr; PUT(&v, 4);
    uint16_t cr = cmd_resp; PUT(&cr, 2); PUT(&z, 2);
    v = ppm_anim_data_base_addr; PUT(&v, 4);
    v = ppm_gfx_blocks_base_addr; PUT(&v, 4);
    v = ppm_sfx_base_addr; PUT(&v, 4);
#undef PUT
    w32(n); wr(b, n);
}

int main(void) {
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
    _Static_assert(sizeof(ppm_ramdp) == 0x2000, "ramdp size");
    _Static_assert(offsetof(ppm_ramdp, sat_data) == 0xB00, "sat");
    _Static_assert(offsetof(ppm_ramdp, obj_data) == 0xF80, "obj");
    _Static_assert(offsetof(ppm_ramdp, dma_cmd) == 0x1400, "dma");
    _Static_assert(offsetof(ppm_ramdp, cmd_args) == 0x1E10, "args");
    _Static_assert(offsetof(ppm_ramdp, dma_total) == 0x1F10, "regs");
    _Static_assert(offsetof(ppm_ramdp, reg_cmd) == 0x1FEA, "reg_cmd");
    if (!host_map()) { fprintf(stderr, "cannot map 0x1000000..0x7900000\n"); return 3; }
    ppmio.ramdp = (ppm_ramdp *) ADDR_RAMDP; ppmio.flash = (u8 *) ADDR_FLA; ppmio.sdram = (u8 *) ADDR_SDR;
    ppmio.bram = (u8 *) ADDR_BRM; ppmio.sfx = (SfxIO *) ADDR_SFX;
    sdr_shadow = (uint8_t *) malloc(SDR_SPAN);
    memset(sdr_shadow, 0, SDR_SPAN);
    for (;;) {
        int op = fgetc(stdin);
        if (op == EOF || op == 'Q') break;
        if (op == 'L') {
            uint32_t n; rd(&n, 4); uint8_t *fl = (uint8_t *) ADDR_FLA; rd(fl, n);
            for (uint32_t a = 0; a + 1 < n; a += 2) { uint8_t t = fl[a]; fl[a] = fl[a + 1]; fl[a + 1] = t; }
            wr("k", 1);
        } else if (op == 'R') {
            pf_len = 0; au_n = 0;
            ppm_reset();
            wr("k", 1);
        } else if (op == 'W' || op == 'w') {
            uint16_t off, n; rd(&off, 2); rd(&n, 2);
            uint8_t tmp[8192]; rd(tmp, n);
            if ((uint32_t) off + n <= 0x2000) memcpy((uint8_t *) ppmio.ramdp + off, tmp, n);
            if (op == 'W') wr("k", 1);
            else continue;              /* 'w' = no reply (bulk replay writes) */
        } else if (op == 'P' || op == 'p') {
            uint16_t word; rd(&word, 2);
            int sd = (op == 'P');      /* 'p' = no SDRAM diff afterwards ('D' is sent by the caller when wanted) */
            (void) sd;
            pf_len = 0; au_n = 0;
            ppmio.ramdp->reg_cmd = word;
            ppm_cmd_handler();
            wr((const void *) ppmio.ramdp, 0x2000);
            wr((const void *) ADDR_FPGIO, 24);
            w32((uint32_t) pf_len); wr(pf_buf, pf_len);
            w32((uint32_t) au_n); wr(au, (size_t) au_n * 8);
        } else if (op == 'M') {
            uint32_t off, n; rd(&off, 4); rd(&n, 4);
            wr((const uint8_t *) ADDR_SDR + off, n);
        } else if (op == 'B') {
            uint32_t off, n; rd(&off, 4); rd(&n, 4);
            wr((const uint8_t *) ADDR_BRM + off, n);
        } else if (op == 'D' || op == 'S') {
            const uint8_t *s = (const uint8_t *) ADDR_SDR;
            static uint32_t offs[SDR_SPAN / 256]; uint32_t c = 0;
            for (uint32_t g = 0; g < SDR_SPAN; g += 256) {
                if (memcmp(s + g, sdr_shadow + g, 256)) { if (op == 'D') offs[c++] = g; memcpy(sdr_shadow + g, s + g, 256); }
            }
            if (op == 'D') { w32(c); wr(offs, (size_t) c * 4); } else wr("k", 1);
        } else if (op == 'A') {
            wr((const void *) ppmio.ramdp, 0x2000);
            wr((const void *) ADDR_FPGIO, 24);
        } else if (op == 'G') {
            globals();
        } else if (op == 'O') {
            uint32_t w; rd(&w, 4); host_gpio_input = w;
            wr("k", 1);
        } else {
            fprintf(stderr, "bad op %d\n", op); return 9;
        }
        fflush(stdout);
    }
    return 0;
}
