/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/mw/mw.h - the cart chip's MegaWire subsystem (built with FW_MW, board/board.h; test build S3b on).
 *
 * The cart chip (the STM32 microcontroller on the real cartridge) runs a MegaWire driver for the ESP8266 module that
 * plugs into the cart: a TIM7-rate task (0x080219CC, ~9.8 Hz), the module driver step (0x0801E824), the $1B20
 * information block (0x08021728), the status word in $1FE6 bits 0-2 (0x080221EE-0x08022292), its init (0x080218FC,
 * from C6 and AA58) and the gates and bodies of the MegaWire posts (A4 / A6 / A8 / A9 / AA / E7,
 * core/dispatch/disp.c). This code was written by our team from our own study of how the cart behaves, and does
 * what the cart does, at the cart chip's addresses, with nothing plugged in: the presence probe (the ADC read of the
 * module's detect pin) reads 0 here, as the ADC of our model of the cart chip does (what a real cart's empty pin
 * reads is not measured; any reading outside the cart chip's 31..60 band takes the same path, and only DRV+0x107E
 * keeps the value), so the status stays 0 ("MODEM : NONE", no MEGAWIRE row), as on a cart with no module. The probe
 * cycle, the information block and the status writes run every tick as the cart's do.
 *
 * Where it runs: the code and its rodata in the Pocket SRAM image (carried in the Little-Man Firmware file,
 * docs/MCU_INTERFACE.md 3.7; run in place), the state at SRAM 0x08018C00 (.sram_bss: after CPU MATE's rate hash
 * 0x18000-0x18BFF). The task runs in the thread (L3, the lowest level of core/sched), below every reply path, as the
 * cart's TIM7 runs below its music interrupts (NVIC 4 under 1-3), one of the cart chip's own steps at a time, none of
 * which starts while the game's sprite frame is open (AE to AF, for up to 33.4 ms): the cart's MegaWire work never
 * delays its sprite replies, and ours waits for them (core/sched/sched.c). The resident parts (the gates, the image
 * check, which the thread runs first after the 68000's release) are in the IROM (the MCU's code memory).
 *
 * Done here: the init 0x080218FC with 0x0801D63C (the driver block, the server name: ours, www.koalakoa.com,
 * docs/ALLOWLIST.md, row B51) and 0x08021890 (the cart identity), the task 0x080219CC in full for the no-module
 * path (the request byte, task state 2 with the E7 packet read 0x08021388, task state 3's steps 0-2 with their
 * give-up, the driver step, the status word, the change checks and counters), the driver step 0x0801E824 in state 1
 * sub-states 0-5 (the presence probe and the link-up), the information block 0x08021728, the result post 0x08021338
 * and the driver request 0x08020EDC. The game's attract mode posts A9 + E7 with no module (its packet goes to state
 * 3, which gives up after 451 ticks: $1C10 = 0x2485, $1FE6 bit 5): that path is the cart's.
 * The A858 screen, which needs NO module (the game's Options pad code posts A858 with nothing plugged in): the screen
 * loop 0x080225F8 with its page loader, page A (our 68000 program) and page B (the ROM's font), the 68000 held and
 * started on page A, the lines from the cart program's text, which core/mw/mw_text.c unpacks from the player's ROM
 * (mw_screen.c; its states 4 and 5, the update, need a module).
 * Not built yet (mw_not_ported() marks where the cart would go on; TEST counts it): what needs a module or the cart's
 * network text - the AT command stack (the driver's states 2-7 and sub-states 6-21: 0x0801D6A8-0x0801E0CC, the reply
 * classifier 0x0801E0CC), the HTTP text (0x08020F8C, the request line of 0x08020EFC) and the reply parse
 * (0x080211D0, state 3 step 3), the task's state 5 and the answer steps of states 4 and 6 (the MegaWire menu's
 * packets 0x82 / 0x84: their requests and their 451-tick give-ups are built), the host round robin, the EEPROM
 * save of the MegaWire record (0x080215C0, 0x08021548), the update writer and the screen's update states 4-5. */
#ifndef CORE_MW_H
#define CORE_MW_H

#include <stdint.h>

/* ---- the cart chip's MegaWire RAM blocks, at their sizes; fields are read at its offsets --------------------- */
#define MW_BLK_BYTES            0x1BCu  /* 0x20006D70: the task block (MW+0 = the MegaWire byte, disp_g.mw_ready) */
#define MW_DRV_BYTES            0x1140u /* 0x200100AC: the driver block (0x0801D63C clears it) */
#define MW_EEP_BYTES            0x64u   /* 0x20012A6C: the MegaWire EEPROM record (slot 9, 96 B); the information
                                           block reads 2 B past it (+0x52..+0x61, the password): kept here */
#define MW_TXB_BYTES            0x454u  /* 0x20013098: the USART3 TX DMA buffer (up to the E7 staging) */
#define MW_E7B_BYTES            0x100u  /* 0x200134EC: the E7 packet staging (E7 body 0x0801C3FA) */
#define MW_RXR_BYTES            0x2000u /* 0x2000DB1C: the USART3 RX DMA ring (MegaWire init fills it with 0xFF) */

typedef struct {
    uint8_t mw[MW_BLK_BYTES + 4u];      /* +0 is unused here: the MegaWire byte lives in disp_g.mw_ready (resident) */
    uint8_t drv[MW_DRV_BYTES];
    uint8_t eep[MW_EEP_BYTES];
    uint8_t txb[MW_TXB_BYTES];
    uint8_t e7b[MW_E7B_BYTES];
    uint8_t rxr[MW_RXR_BYTES];
} mw_ram_t;
extern mw_ram_t mw_ram;                 /* .sram_bss: cleared once a boot by the image check (the chip's .bss) */

/* byte / halfword / word at a cart chip offset of a block (the blocks are word-aligned; every offset used is aligned
   to its width, as the cart chip's own ldrh / ldr need) */
#define MW8(blk, off)           (mw_ram.blk[(off)])
#define MW16(blk, off)          (*(volatile uint16_t *)(void *)&mw_ram.blk[(off)])
#define MW32(blk, off)          (*(volatile uint32_t *)(void *)&mw_ram.blk[(off)])
/* the cart chip's pointer fields (DRV+0x106C, +0x1070: into its reply buffers) hold offsets into mw_ram here: the
   same object, a value no game code reads, 32 bits on any host */
#define MW_PTR_OF(p)            ((uint32_t)((const uint8_t *)(p) - (const uint8_t *)(const void *)&mw_ram))
#define MW_PTR(v)               ((volatile uint8_t *)((uint8_t *)(void *)&mw_ram + (v)))

/* task block fields (MW + offset) the resident gates use */
#define MW_REQ                  0x001u  /* A4 stores its low byte here; the task's next tick acts on it */
#define MW_STATE                0x002u  /* the task state (u8) */
#define MW_HOME                 0x00Cu  /* u32 := 1 when C6's EEPROM read of slot 9 succeeds (job step 0x0801A50A) */
#define MW_SCRCNT               0x008u  /* u32: the screen loop's call count (0x20006D78) */
#define MW_SCREEN               0x010u  /* u16: the screen state, := 1 by an accepted A858 (0x0801CD38); the cart
                                           chip's main loop calls the screen loop 0x080225F8 while it is not 0 */
#define MW_E7_PEND              0x122u  /* E7 accepted, the packet not sent yet (A9 clears it with $1FE6 bit 4) */
#define MW_RESULT               0x123u  /* a result is in $1C10 (A6 clears it with $1FE6 bit 5 and $1C10) */
#define MW_ERRBYTE              0x19Cu  /* the last error byte ($1B83) */

/* ---- the resident side (IROM) ---------------------------------------------------------------------------------- */
extern volatile uint8_t mw_due;         /* L2a's TIM7 ticks, mod 256 (L2a, the timer interrupt, is the only writer) */
extern uint8_t mw_ran;                  /* the ticks the thread has run the task for: mw_due - mw_ran are pending.
                                           The cart's TIM7 runs the task every period; here a long job holds the
                                           thread (C6's set-up, ~1 s), so a late tick runs late, never dropped */
extern volatile uint8_t mw_aa_pending;  /* AA58 accepted: the task's next tick runs its reset and init (disp.c f_aa) */
extern uint8_t s3_mw_on;                /* the cart's MegaWire code runs this boot: the SRAM image passed its check
                                           (whatever the MegaWire option: On runs it too). 0: no image, or a
                                           refused one, or not checked yet: test build 5's MegaWire with the
                                           option Off (status 0, no module) */
extern uint8_t s3_mw_checked;           /* the image check has run this boot */
void s3_mw_boot(void);                  /* the thread's first work after the 68000's release: s3_mw_on from the image
                                           check (the option is not read) */
void mw_init_irqoff(void);              /* 0x08021936-0x080219AA: the init's interrupts-off block (mw_res.c) */
void mw_e7_body(void);                  /* 0x0801C3FA: E7's body after its gates (mw_res.c, resident) */
void mw_a9_body(void);                  /* 0x0801C29E: A9's body after its gates (mw_res.c, resident) */
void mw_a6_body(void);                  /* 0x0801C2B8: A6's body after its gates (mw_res.c, resident) */

/* MW_BUG: planted bugs for the negative controls of tests/equiv/mw_oracle.py only (the host harness builds
   mw_host_bug1..3, fwbuild.json s1.host.programs); every image builds with 0 */
#ifndef MW_BUG
#define MW_BUG 0
#endif

/* ---- the SRAM image's entry points (called only while s3_mw_on) --------------------------------------------- */
void mw_init(void);                     /* 0x080218FC: from C6's set-up job and from AA58 (after 0x0802171C) */
void mw_reset(void);                    /* 0x0802171C: AA58's first call (the record's EEPROM save: not built yet) */
void mw_tick(void);                     /* 0x080219CC: the TIM7 task whole (the host harness) */
/* the thread runs the task one step at a time, a step being one of the cart chip's own steps (mw_task.c); none starts
   while the game's sprite frame is open, for up to 33.4 ms (core/sched/sched.c) */
#define MW_IB_STEP              18u     /* the information block's RAMDP stores a step (even; 52 words: 3 steps) */
typedef struct {
    uint8_t  save_167, save_49, save_164;   /* what part (a) saved for the tail (the cart chip's registers) */
    uint8_t  ii;                        /* the information block's next word to store (0-52) */
    uint32_t r4;                        /* the cart chip's r4 after part (a) (the block's stack word) */
    uint8_t  ib[0x68];                  /* the information block as the cart chip builds it on its stack (0x08021728) */
} mw_tk_t;
extern mw_tk_t mw_tk;                   /* .sram_bss: cleared once a boot with mw_ram */
enum {                                  /* mw_tk_ph: the task's next step */
    MW_PH_A = 0,                        /* (a) a new tick: the request byte and the task state's step */
    MW_PH_DRV,                          /* (b) the driver step 0x0801E824 */
    MW_PH_ST,                           /* (c) the status word, and the test of 81 bit 3 */
    MW_PH_IB,                           /* (c) the information block's bytes */
    MW_PH_IBST,                         /* (c) its RAMDP stores, MW_IB_STEP words a step */
    MW_PH_TAIL                          /* (c) the tail */
};
extern uint8_t mw_tk_ph;                /* resident (WRAM): the next step (MW_PH_A = a new tick); the thread's idle path
                                           reads no SRAM (docs/MCU_INTERFACE.md 3.7, the costs) */
extern uint8_t mw_scr_on;               /* resident (WRAM): an accepted A858 set the screen state; until then the thread
                                           does not read it from SRAM */
extern uint8_t mw_chk_par;              /* resident (WRAM): the multiplex count (disp_g.af_parity) the thread saw at its
                                           sprite check, with the interrupts off */
#define MW_STEP_YIELD           2u      /* mw_tick_part: an AE came as the interrupts opened; nothing done */
uint32_t mw_tick_part(uint32_t s);      /* the next step, entered with the interrupts off (s: what to restore, which it
                                           does first); 0 = more steps, 1 when the tick is complete, MW_STEP_YIELD */
uint32_t mw_tick_a(void);               /* part (a): 0 = the tick ends there */
uint32_t mw_tick_c(void);               /* the status word: 1 = 81 bit 3 asks for the information block */
void mw_not_ported(uint32_t chip_addr); /* TEST: count a path not built yet (RELEASE: nothing) */

/* ---- the A858 screen (core/mw/mw_screen.c, SRAM image) ------------------------------------------------------ */
/* The cart chip's main loop calls the screen loop 0x080225F8 at the end of every pass while the screen state (MW+0x10)
   is not 0 and the job queue is empty; each call starts with a 10 ms SysTick wait and state 1 has 64 ms and 300 ms
   ones, during which the cart chip's interrupts (TIM7, the mailboxes) go on. Here the thread runs the call in steps
   between those waits (mw_scr.due), below the MegaWire task and never between two of its steps, so the task keeps its
   period; the one exception is the step that unpacks the cart program's text (mw_s1_end, ~0.27 s on the RV32 board
   model, an estimated timing), after which the ticks it held run late (mw_due), as after a long job. */
typedef struct {
    uint8_t  ph;                        /* where the current call is: 0 = a new call, else after a wait (mw_screen.c) */
    uint8_t  pad[3];
    uint32_t due;                       /* brd_now() at which the wait ends (when ph != 0) */
} mw_scr_t;
extern mw_scr_t mw_scr;                 /* .sram_bss: cleared once a boot with mw_ram */
void mw_screen_step(void);              /* the thread: one step of the cart chip's screen loop */
#define MW_PAGE_A_WORDS         382u    /* page A, our 68000 program (core/mw/mw_page_a.c, tools/mkpagea.py) */
extern const uint16_t mw_page_a[MW_PAGE_A_WORDS];

/* ---- the cart program's text from the player's ROM (core/mw/mw_text.c, SRAM image) -------------------------- */
#define MW_TEXT_BASE            0x08010000u /* the cart program's addresses: 0x08010000-0x0803FFFF */
#define MW_TEXT_BYTES           0x30000u
typedef struct {
    uint32_t src;                       /* ROM byte offset of the next code byte */
    uint32_t out;                       /* bytes unpacked so far */
    uint8_t  st;                        /* 0 not started, 1 running, 2 checked (readable), 3 refused */
    uint8_t  pad[3];                    /* not used; kept zero (the layout mwboot.py reads stays) */
} mw_txt_t;
extern mw_txt_t mw_txt;                 /* .sram_bss: cleared once a boot with mw_ram */
void mw_text_start(void);               /* begin unpacking it (the first time the screen needs it this boot) */
uint32_t mw_text_run(uint32_t n);       /* unpack it all (n is not used); 1 when finished (checked or refused) */
uint32_t mw_text_ok(void);              /* unpacked and checked: the cart chip's addresses can be read */
uint8_t mw_text8(uint32_t chip_addr);   /* the cart program's byte at a cart chip address */

/* TEST: the task's counters (RELEASE keeps the zeros) */
typedef struct {
    uint32_t ticks;                     /* mw_tick calls */
    uint32_t not_ported;                /* times the code reached a path not built yet: a module's path (never on the
                                           Pocket), the init's network text, or the A858 screen (the pad code) */
    uint32_t last_np;                   /* the chip address of the last such path */
} mw_stats_t;
extern mw_stats_t mw_stats;

#endif
