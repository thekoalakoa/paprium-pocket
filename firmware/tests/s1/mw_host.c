/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/s1/mw_host.c - the MegaWire port (core/mw) on the host, driven one input line at a time from stdin by
 * tests/equiv/mw_oracle.py, which runs the cart's chip in the cart-engine runner (our test harness outside this tree)
 * on the same steps and compares.
 *
 *   rom <path>                  the game ROM (read in place; for the cart identity 0x08021890)
 *   ready <0|1>                 the MegaWire byte (MW+0, disp_g.mw_ready)
 *   f81 <b2>                    G+0xB (81 bit 3: the information block)
 *   fe6 <hex>                   the $1FE6 status shadow (the chip's G+0x10)
 *   set <mw|drv|eep|e7b> <off> <hex bytes>   RAM block bytes (the chip's state at the oracle's start)
 *   tick | init | req <byte>    mw_tick(), mw_init(), MW+1 := byte (what an accepted A4 stores)
 *   e7 <hex words> | a9 | a6    the E7 body (the words at $1E10 first) / the A9 / A6 body, as after their gates
 *   fe4 <hex> | fea <hex>       the $1FE4 shadow / $1FEA as the screen starts (the chip's values)
 *   ram <off> <hex bytes>       cart RAM bytes (the 68000's order) from the chip's, as the screen starts
 *   text                        unpack the cart program from the game ROM given by `rom` (core/mw/mw_text.c):
 *                               "X <state> <crc32>"
 *   a858                        what an accepted A858 stores (MW+0x10 := 1)
 *   scr <ms>                    the thread for ms of board time: the TIM7 task every period and the screen loop's
 *                               steps once due; events "H <hold> <us>", "FA <word> <us>", "S4 <word> <us>",
 *                               "ST <state> <us>", then "Z <S.ready> <SFX.ready> <MW+8> <MW+0xC>",
 *                               "C <crc32 of RAMDP $0000-$17FF> <crc32 of $1E10-$1E8F> <crc32 of DRV+0..0x36>"
 *                               (CRCs only: the lines and page B are the cart's bytes) and "E"
 * After each step: "W <addr> <word>" for every cart RAM word the step wrote (the RAM is filled with 0xA5A5
 * before it, but an E7's packet words), "S <word>" for every $1FE6 store in order, "J <type> <slot>" for each job queued, then
 * "D <blk> <hex>" listings of mw / drv / eep / e7b (MW+0 is the MegaWire byte) and "E" (end of step).
 * Stubs here: the status helper (st_set: the shadow, set or clear, store), the job queue, sched_work_post. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "board.h"
#include "sched.h"
#include "disp.h"
#include "song.h"
#include "mw.h"

uint16_t mwh_ram[0x1000];
uint16_t mwh_romw[0x400000];
uint8_t mwh_rom8[0x800000];
#define rom_b mwh_rom8
uint32_t mwh_time;
uint16_t mwh_fea;
uint8_t mwh_ws[0x20000];
uint8_t mwh_text[0x30000];
song_seq S;
song_sfx SFX;
static uint32_t scr_on;              /* inside a "scr" run: the events are printed with their time */
uint32_t mwh_options, mwh_irq;
uint8_t s3_mw_on = 1u;
uint8_t mw_tk_ph;                       /* core/mw/mw_boot.c's (resident): the task's next step */
uint8_t mw_chk_par;                     /* core/mw/mw_boot.c's (resident): the multiplex count at the thread's check */
volatile uint8_t mw_due;
uint8_t mw_ran;
volatile uint8_t mw_aa_pending;
disp_state_t disp_g;
static uint16_t sh_fe6, sh_fe4;
static uint32_t home_pending;      /* a queued type-6 job: the chip's main loop runs it before the next tick (the read
                                       succeeds: MW+0xC := 1, job step 0x0801A50A) */
static char out[1 << 16];

uint8_t mwh_rom_byte(uint32_t a) { return rom_b[a & 0x7FFFFFu]; }

void st_set(uint32_t on, uint32_t reg, uint16_t mask)
{
    if (reg == ST_FE6) {
        sh_fe6 = on ? (uint16_t)(sh_fe6 | mask) : (uint16_t)(sh_fe6 & ~mask);
        printf("S %04X\n", sh_fe6);
    }
    else if (reg == ST_FE4) {
        sh_fe4 = on ? (uint16_t)(sh_fe4 | mask) : (uint16_t)(sh_fe4 & ~mask);
        if (scr_on)
            printf("S4 %04X %u\n", sh_fe4, (unsigned)((uint64_t)mwh_time * 1000000u / BRD_CLK_HZ));
        else
            printf("S4 %04X\n", sh_fe4);
    }
}
void mwh_freg_wr(unsigned off, uint16_t v)
{
    if (off == 0x0Au) {
        mwh_fea = v;
        printf("FA %04X %u\n", v, (unsigned)((uint64_t)mwh_time * 1000000u / BRD_CLK_HZ));
    }
}
void brd_md_hold(uint32_t hold) { printf("H %u %u\n", hold, (unsigned)((uint64_t)mwh_time * 1000000u / BRD_CLK_HZ)); }
void brd_full_reset(void) { printf("RESET %u\n", (unsigned)((uint64_t)mwh_time * 1000000u / BRD_CLK_HZ)); fflush(stdout); exit(3); }
void chip_trace(uint32_t code, uint32_t a, uint32_t b) { printf("T %08X %X %X\n", code, a, b); }
uint32_t s3_sram_cold_ok(void) { return 1u; }

static uint32_t crc32b(const uint8_t *p, uint32_t n)
{
    uint32_t c = 0xFFFFFFFFu;
    while (n--) {
        c ^= *p++;
        for (int k = 0; k < 8; k++)
            c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1u)));
    }
    return ~c;
}
static uint32_t crc_ram(uint32_t a, uint32_t n)     /* the 68000's bytes of RAMDP [a, a + n) */
{
    static uint8_t b[0x2000];
    uint32_t i;
    for (i = 0; i < n; i += 2u) {
        b[i] = (uint8_t)(mwh_ram[(a + i) >> 1] >> 8);
        b[i + 1u] = (uint8_t)mwh_ram[(a + i) >> 1];
    }
    return crc32b(b, n);
}
disp_job_t *disp_job_slot(uint32_t ahead) { return &disp_g.q[(disp_g.q_wr + ahead) & 0xFu]; }
void disp_job_commit(uint32_t n)
{
    disp_job_t *j = &disp_g.q[disp_g.q_wr & 0xFu];
    printf("J %u %u\n", j->type, j->b1c);
    if (j->type == JOB_EEP_READ_MW)
        home_pending = 1u;
    disp_g.q_wr = (uint8_t)(disp_g.q_wr + n);
}
void sched_work_post(void) { }

static void dump(const char *name, const uint8_t *p, uint32_t n)
{
    uint32_t i, k = 0;
    k += (uint32_t)sprintf(out + k, "D %s ", name);
    for (i = 0; i < n; i++)
        k += (uint32_t)sprintf(out + k, "%02X", p[i]);
    puts(out);
}

static void step_end(const uint16_t *before)
{
    uint32_t i;
    uint8_t mw0 = mw_ram.mw[0];
    for (i = 0; i < 0x1000u; i++)
        if (mwh_ram[i] != before[i])
            printf("W %04X %04X\n", 2u * i, mwh_ram[i]);
    mw_ram.mw[0] = disp_g.mw_ready;
    dump("mw", mw_ram.mw, MW_BLK_BYTES);
    mw_ram.mw[0] = mw0;
    dump("drv", mw_ram.drv, MW_DRV_BYTES);
    dump("eep", mw_ram.eep, MW_EEP_BYTES);
    dump("e7b", mw_ram.e7b, sizeof mw_ram.e7b);
    puts("E");
    fflush(stdout);
}

int main(void)
{
    static char line[1 << 16];
    static uint16_t before[0x1000];
    while (fgets(line, sizeof line, stdin)) {
        char cmd[16], arg[1 << 15];
        unsigned a = 0, off = 0;
        arg[0] = 0;
        if (sscanf(line, "%15s", cmd) != 1)
            continue;
        if (!strcmp(cmd, "rom")) {
            FILE *f;
            uint32_t i;
            sscanf(line, "%*s %32767[^\n]", arg);
            f = fopen(arg, "rb");
            if (!f || fread(rom_b, 1, sizeof rom_b, f) == 0) {
                fprintf(stderr, "mw_host: cannot read %s\n", arg);
                return 2;
            }
            fclose(f);
            for (i = 0; i < 0x400000u; i++)
                mwh_romw[i] = (uint16_t)((rom_b[2u * i] << 8) | rom_b[2u * i + 1u]);
        }
        else if (!strcmp(cmd, "ready")) {
            sscanf(line, "%*s %u", &a);
            disp_g.mw_ready = (uint8_t)a;
        }
        else if (!strcmp(cmd, "f81")) {
            sscanf(line, "%*s %u", &a);
            disp_g.f81[2] = (uint8_t)a;
        }
        else if (!strcmp(cmd, "fe6")) {
            sscanf(line, "%*s %x", &a);
            sh_fe6 = (uint16_t)a;
        }
        else if (!strcmp(cmd, "set")) {
            char blk[8];
            uint8_t *p;
            uint32_t i, n;
            sscanf(line, "%*s %7s %x %32767s", blk, &off, arg);
            p = !strcmp(blk, "mw") ? mw_ram.mw : !strcmp(blk, "drv") ? mw_ram.drv :
                !strcmp(blk, "e7b") ? mw_ram.e7b : mw_ram.eep;
            n = (uint32_t)strlen(arg) / 2u;
            for (i = 0; i < n; i++) {
                unsigned b;
                sscanf(arg + 2u * i, "%2x", &b);
                p[off + i] = (uint8_t)b;
            }
            if (p == mw_ram.mw && off == 0u && n)
                disp_g.mw_ready = mw_ram.mw[0];
            /* the pointers the chip keeps in DRV+0x106C / +0x1070 are its addresses: ours point at our reply buffer */
            MW32(drv, 0x1070) = MW_PTR_OF(&mw_ram.drv[0x65]);
            MW32(drv, 0x106C) = MW_PTR_OF(&mw_ram.drv[0x65]);
        }
        else if (!strcmp(cmd, "req")) {
            sscanf(line, "%*s %x", &a);
            MW8(mw, MW_REQ) = (uint8_t)a;
        }
        else if (!strcmp(cmd, "e7") || !strcmp(cmd, "a9") || !strcmp(cmd, "a6")) {
            char *q = line + 2;
            uint32_t i = 0, n = 0;
            unsigned w;
            int k;
            static uint16_t pk[0x80];
            while (cmd[0] == 'e' && n < 0x80u && sscanf(q, "%x%n", &w, &k) == 1) {
                pk[n++] = (uint16_t)w;
                q += k;
            }
            for (i = 0; i < 0x1000u; i++)          /* every word a body stores shows, whatever its old value */
                mwh_ram[i] = 0xA5A5u;
            for (i = 0; i < n; i++)
                mwh_ram[(0x1E10u >> 1) + i] = pk[i];
            memcpy(before, mwh_ram, sizeof before);
            if (cmd[0] == 'e')
                mw_e7_body();
            else if (cmd[1] == '9')
                mw_a9_body();
            else
                mw_a6_body();
            step_end(before);
        }
        else if (!strcmp(cmd, "ram")) {
            uint32_t i, n;
            sscanf(line, "%*s %x %32767s", &off, arg);
            n = (uint32_t)strlen(arg) / 4u;
            for (i = 0; i < n && (off >> 1) + i < 0x1000u; i++) {
                unsigned w;
                sscanf(arg + 4u * i, "%4x", &w);
                mwh_ram[(off >> 1) + i] = (uint16_t)w;
            }
        }
        else if (!strcmp(cmd, "fe4") || !strcmp(cmd, "fea")) {
            sscanf(line, "%*s %x", &a);
            if (cmd[2] == '4')
                sh_fe4 = (uint16_t)a;
            else
                mwh_fea = (uint16_t)a;
        }
        else if (!strcmp(cmd, "text")) {
            mw_text_start();
            while (!mw_text_run(0x10000u))
                ;
            printf("X %u %08X\n", mw_txt.st, crc32b(mwh_text, sizeof mwh_text));
            puts("E");
            fflush(stdout);
        }
        else if (!strcmp(cmd, "a858")) {
            MW16(mw, MW_SCREEN) = 1u;
            puts("E");
            fflush(stdout);
        }
        else if (!strcmp(cmd, "scr")) {
            const uint32_t per = (uint32_t)((uint64_t)BRD_CLK_HZ * 1024u / 10000u);   /* TIM7: 1,024 / 10 kHz */
            uint32_t end, next = mwh_time + per, st0 = MW16(mw, MW_SCREEN);
            uint8_t b[0x37];
            unsigned ms = 0, left, piece;
            sscanf(line, "%*s %u", &ms);
            scr_on = 1u;
            for (left = ms; left; left -= piece) {      /* in pieces of at most 20 s: the loop's int32 time compares hold
                                                           for ~40 s of board time (the event times wrap after ~79 s) */
                piece = left > 20000u ? 20000u : left;
                end = mwh_time + piece * (BRD_CLK_HZ / 1000u);
                while ((int32_t)(end - mwh_time) > 0) {
                    if ((int32_t)(mwh_time - next) >= 0) {
                        if (home_pending) {
                            home_pending = 0u;
                            MW32(mw, MW_HOME) = 1u;
                        }
                        mw_tick();
                        next += per;
                        continue;
                    }
                    if (MW16(mw, MW_SCREEN) && (mw_scr.ph == 0u || brd_until(mw_scr.due) <= 0)) {
                        mw_screen_step();
                        mwh_time += BRD_CLK_HZ / 100000u;       /* a step's own time: 10 us (the chip's: a few us) */
                        if (MW16(mw, MW_SCREEN) != st0) {
                            st0 = MW16(mw, MW_SCREEN);
                            printf("ST %u %u\n", st0, (unsigned)((uint64_t)mwh_time * 1000000u / BRD_CLK_HZ));
                        }
                        continue;
                    }
                    {
                        uint32_t t = next;
                        if (MW16(mw, MW_SCREEN) && mw_scr.ph && (int32_t)(mw_scr.due - t) < 0)
                            t = mw_scr.due;
                        if ((int32_t)(end - t) < 0)
                            t = end;
                        mwh_time = t;
                    }
                }
            }
            scr_on = 0u;
            memcpy(b, mw_ram.drv, sizeof b);
            printf("Z %u %u %u %u\n", (unsigned)S.ready, (unsigned)SFX.ready, (unsigned)MW32(mw, MW_SCRCNT),
                   (unsigned)MW32(mw, MW_HOME));
            printf("C %08X %08X %08X\n", crc_ram(0u, 0x1800u), crc_ram(0x1E10u, 0x80u), crc32b(b, sizeof b));
            puts("E");
            fflush(stdout);
        }
        else if (!strcmp(cmd, "tick") || !strcmp(cmd, "init")) {
            uint32_t i;
            if (home_pending) {
                home_pending = 0u;
                MW32(mw, MW_HOME) = 1u;
            }
            for (i = 0; i < 0x1000u; i++)
                mwh_ram[i] = 0xA5A5u;
            memcpy(before, mwh_ram, sizeof before);
            if (cmd[0] == 't')
                mw_tick();
            else
                mw_init();
            step_end(before);
        }
    }
    return 0;
}
