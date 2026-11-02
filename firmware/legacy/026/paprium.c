/* Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later) */
// D08, D20, D25 and the other D numbers in this file's notes name the differences between this 0.2.6 code and the
// cart's chip that our own study of how the cart behaves listed. MCU = the cart's NEORV32 soft CPU in the core;
// RAMDP = the cart RAM that both the 68000 and the cart chip (here the MCU) see.

#include "appmain.h"
#include "buddy.h"  // pocket: the CPU MATE glue (zz_buddy.c)

// paprium-pocket: initialise the YM2612 DAC stream buffer. SHIPPING - this is
// the fix for the VM DAC static, not a probe. See cmd_88_audio_cfg.
#define PPM_DAC_STREAM_FILL     1


void ppm_reset();
void ppm_md_rst(u8 rst);
void ppm_init_cmd_ptr();
void ppm_cmd_handler();
void cmd_unknown();
void cmd_unknown_muted();
void cmd_00();
void cmd_81_init();
void cmd_84_sdram_off();
void cmd_B0_sprite_init();
void cmd_88_audio_cfg();
void cmd_8C_bgm_play();
void cmd_8D_bgm_cfg();
void ppm_music_vu_start(u32 mod_addr);
void ppm_music_vu_stop();
void ppm_music_vu_update();
void cmd_AD_obj_add();
void cmd_AE_frame_start();
void cmd_AF_frame_end();
void cmd_B1_sprite_pause();
void cmd_C6_setup_data();
void cmd_C9_vol_bgm();
void cmd_CA_vol_sfx();
void cmd_D1_sfx_play();
void cmd_D2_sfx_stop();
void cmd_D3_sfx_loop();
void cmd_D5_sfx_stopall();
void cmd_DA_unpack();
void cmd_DB_set_dma_ptr();
void cmd_DF_eep_rd();
void cmd_E0_eep_wr();
void cmd_E7_mwire();
void cmd_EC_vram_budget();
void cmd_F2_unpack();
void cmd_F4_unpack_scal();
void cmd_F5_stamp_rescale();

void sfx_player_update();

ppm_io ppmio;
u32 tick_ctr;

void (*cmp_ptr[256])();

#if PPM_CHIP_EC || PPM_CHIP_B0
// D08, D20 (2026-10-08): the chip's sprite-engine flag, byte $2000FB1C+$400. Set to 1 by
// the engine init $08019734 at $080197C2-$080197CA, which the C6 setup job runs
// ($0801A54A-$0801A552); cleared only at app init ($0801F9E6-$0801F9EA,
// $0801FAFE-$0801FB02), i.e. our power-on bss. EC ($0801B152-$0801B15E) and B0
// ($0801AD3C-$0801AD46) are refused while it is 0. The first C6 also resets the sprite
// engine (PPM_CHIP_B0): see cmd_C6_setup_data and mame.c, CHIP EC, B0 AND 81.
static u8 ppm_chip_engine_ready;
#endif

void ppm_start() {

    tick_ctr = 0;
    ppm_reset();

    printf("\n");

    while (1) {

        ppm_cmd_handler();
        sfx_player_update();
        ppm_music_vu_update();
        tick_ctr++;
        ppm_hb_idle();

        // pocket: CPU MATE (option D) - the same ctrl read and the same four instructions; the
        // test also sees the Mega CD stub's send-pending and AI-off bits (ctrl[8], ctrl[10]). Neither can be
        // set with Mega CD Mode off, so every pass is today's. buddy_event = zz_buddy.c.
        {
            u32 ctrl = *(vu32 *) &FPGAIO->ctrl, hit;
            // srli + andi kept as two instructions (gcc would fold them into one andi): today's exact cost
            __asm__ ("srli %0, %1, 3\n\tandi %0, %0, %2" : "=r" (hit) : "r" (ctrl), "i" (BUDDY_LOOP_MASK));
            if (hit) {
                if (ctrl & CT_MDRST) {
                    ppm_hb_exit();
                    return;
                }
                buddy_event(ctrl);
            }
        }
    }
}

void ppm_reset() {

    ppm_md_rst(1);
    FPGAIO->ctrl.sdram_en = 1;
    {
        u32 prev_ptr = ppm_sptr_shadow;
        u32 new_ptr = 0;
        FPGAIO->sdram_ptr = new_ptr;
        ppm_sptr_shadow = new_ptr;
#if PPM_EPOCH_RING
        snap_epoch_note(prev_ptr);
#endif
    }

    printf("ppm init...\n");

    ppmio.ramdp = (ppm_ramdp *) ADDR_RAMDP;
    ppmio.flash = (u8 *) ADDR_FLA;
    ppmio.sdram = (u8 *) ADDR_SDR;
    ppmio.bram = (u8 *) ADDR_BRM;
    ppmio.sfx = (SfxIO *) ADDR_SFX;

    memcpy(ppmio.ramdp, ppmio.flash, 8192);

    ppmio.ramdp->reg_cmd = 0;
    {
        // pocket: (0.2.6 final) the OSD's Console and MegaWire options, from the core's option registers
        // on the MCU GPIO input (paprium_cart.sv). [10:8] and [6] = the console's $1FE4 model bits: 0x700 Model 2,
        // 0x000 Genesis 3, 0x400 Nomad, 0x600 Mega Jet, bit 6 unknown console, 0 for Model 1 and for every combined
        // Mega CD unit. [18:16] = the $1FE6 MegaWire status: 7 plugged and signed in (the old fixed value), 0 none,
        // as on the chip (difference D01). The game reads both once, in its hardware check ($BC944) at boot.
        u32 opt = GPIO_INPUT;
#if PPM_BUSY_REST
        ppmio.ramdp->reg_status_1 = 0x0004 | (u16) opt;   // busy at rest, as the retail hardware evidently is
#else
        ppmio.ramdp->reg_status_1 = (u16) opt;
#endif
        ppmio.ramdp->reg_status_2.word = opt >> 16;
    }

    // boot check
    ((u16 *) ppmio.ramdp)[0x1d1c / 2] = 0x0004; //SWAP_WORD(0x0004); // 0xc00004
    ((u16 *) ppmio.ramdp)[0x1d2c / 2] |= 0x0100; //SWAP_WORD(0x0100); // switch to beq.s (0x670e)

    // post splash jump location
    ((u16 *) ppmio.ramdp)[0x1562 / 2] = 0x0001; //SWAP_WORD(0x0001);
    ((u16 *) ppmio.ramdp)[0x1564 / 2] = 0x0100; //SWAP_WORD(0x0100);

    ppm_init_mame();
    ppm_init_cmd_ptr();

    mdp_init();

    FPGAIO->vol_sfx = 0xff;
    FPGAIO->vol_bgm = 0xff;

    //rom patches  (flash should be writable)
    *(u16 *)&ppmio.flash[0x81104] = 0x4e71; // emulator check
    //printf("f: %x\n", *(u32 *) & ppmio.flash[0x81104]);


    //printHex((u8 *) 0x00000, 128);
    //printHex((u8 *) 0x10000, 128);

    //should be last init step
    printf("rom ver: %x\n", *(u16 *) & ppmio.flash[0x1000a]);
    ppm_md_rst(0);
}

void ppm_md_rst(u8 rst) {

    if (rst) {
        FPGAIO->ctrl.md_rst = 1;
    } else {

        FPGAIO->ctrl.md_rst = 0;

        while (FPGAIO->ctrl.md_rst_status) {

            FPGAIO->ctrl.md_rst_status = 0;
            asm("nop");
        }
    }
}

void ppm_init_cmd_ptr() {

    for (int i = 0; i < 256; i++) {
        cmp_ptr[i] = cmd_unknown;
    }

    cmp_ptr[0x83] = cmd_unknown_muted; // unk startup thing
    cmp_ptr[0x88] = cmd_88_audio_cfg; // set audio config
    cmp_ptr[0x95] = cmd_unknown_muted; // (bgm related)
    cmp_ptr[0x96] = cmd_unknown_muted; // (bgm related)
    cmp_ptr[0xA4] = cmd_unknown_muted; // megawire settings
    //cmp_ptr[0xB1] = cmd_unknown_muted; // seems used to keep previous SAT data in VRAM, do nothing?
    cmp_ptr[0xB6] = cmd_unknown_muted; // likely instructs to restore boot code to allow back HW reset
    cmp_ptr[0xD6] = cmd_unknown_muted; //???

    //unknown stuff
    cmp_ptr[0xB0] = cmd_B0_sprite_init;
    cmp_ptr[0xD0] = cmd_unknown_muted;

    cmp_ptr[0x00] = cmd_00;
    cmp_ptr[0x81] = cmd_81_init;
    cmp_ptr[0x84] = cmd_84_sdram_off;
    cmp_ptr[0x8C] = cmd_8C_bgm_play;
    cmp_ptr[0x8D] = cmd_8D_bgm_cfg;
    cmp_ptr[0xAD] = cmd_AD_obj_add;
    cmp_ptr[0xAE] = cmd_AE_frame_start;
    cmp_ptr[0xAF] = cmd_AF_frame_end;
    cmp_ptr[0xB1] = cmd_B1_sprite_pause;
    cmp_ptr[0xC6] = cmd_C6_setup_data;
    cmp_ptr[0xDA] = cmd_DA_unpack;
    cmp_ptr[0xDB] = cmd_DB_set_dma_ptr;
    cmp_ptr[0xDF] = cmd_DF_eep_rd;
    cmp_ptr[0xE0] = cmd_E0_eep_wr;
    cmp_ptr[0xE7] = cmd_E7_mwire;
    cmp_ptr[0xEC] = cmd_EC_vram_budget;
#if PPM_CHIP_EC
    cmp_ptr[0xAC] = cmd_EC_vram_budget;     // D08: the chip's table entry $2C ($08025AC8) serves $AC and $EC; its gate refuses $AC
#endif
#if PPM_CHIP_B0
    cmp_ptr[0xF0] = cmd_B0_sprite_init;     // D20: the chip's table entry $30 serves $B0 and $F0 alike ($0801AD3C)
#endif
#if PPM_CHIP_81
    cmp_ptr[0xC1] = cmd_81_init;            // D25: the chip's table entry $01 serves $81 and $C1 alike ($0801AFC4)
#endif
    // paprium-pocket: 0xF2 RESTORED to stock. Muting it was tested on hardware
    // and changed nothing - consistent with krikzz's comment calling it the
    // "sprites test menu" unpack, i.e. it likely never fires in normal play.
    // Left enabled so measurements run against shipping behaviour rather than a
    // probe variant. It is logged in Probe B because it also moves the stream
    // pointer (sdram_ptr = 0x9000).
    cmp_ptr[0xF2] = cmd_F2_unpack;
    cmp_ptr[0xF4] = cmd_F4_unpack_scal;
    cmp_ptr[0xF5] = cmd_F5_stamp_rescale;

    cmp_ptr[0xC9] = cmd_C9_vol_bgm;
    cmp_ptr[0xCA] = cmd_CA_vol_sfx;
    cmp_ptr[0xD1] = cmd_D1_sfx_play;
    cmp_ptr[0xD2] = cmd_D2_sfx_stop;
    cmp_ptr[0xD3] = cmd_D3_sfx_loop;
    cmp_ptr[0xD5] = cmd_D5_sfx_stopall;
}
//============================================================================== cmd handler

u16 cmd_resp;

void ppm_cmd_handler() {

    if (ppmio.ramdp->reg_cmd == 0) {
        return;
    }

    ppmio.ramdp->reg_status_1 |= 0x0004;
    ppmio.ramdp->reg_status_2.bits.busy = 1;

    u16 posted = ppmio.ramdp->reg_cmd;
    u8 cmd = (u8)(posted >> 8);

    cmd_resp = 0;

    hb_w8(8, (u8) cmd); hb_w8(9, 1); hb_w32(36, ppm_hb_sp());
    cmp_ptr[cmd]();
    hb_w8(9, 0);

#if PPM_BUSY_REST
  #if PPM_BUSY_CLEAR_THROUGH_RESP
    // v2. The pointer (or whatever the command changed) is in place. For the
    // pointer-moving commands clear busy now and LEAVE it clear through the
    // response: the readers that poll right after posting (0x0B4276, 0x07F46E,
    // 0x09DA9A) see it fall here, and the one that waits for the response first
    // (0x0B41C4, after a mode-7 0xDA) sees it clear when it looks. It is raised
    // again below, the moment the game posts its next command - before that
    // post's own poll can see stale-clear. Everything else stays up at rest.
    u8 pointer_cmd = (cmd == 0xDB || cmd == 0xDA);
    if (pointer_cmd) {
        ppmio.ramdp->reg_status_1 &= ~0x0004;
    } else {
        ppmio.ramdp->reg_status_1 |= 0x0004;   // stays up at rest
    }
  #else
    // v1: pulse. Raised again BEFORE the response, which the 0x0B41C4 reader
    // cannot see (it polls after the response) - 0.56 s timeout per mode-7 0xDA.
    if (cmd == 0xDB || cmd == 0xDA) {
        ppmio.ramdp->reg_status_1 &= ~0x0004;
        for (volatile u32 i = 0; i < PPM_BUSY_PULSE_LOOPS; i++) { }
        ppmio.ramdp->reg_status_1 |= 0x0004;
    } else {
        ppmio.ramdp->reg_status_1 |= 0x0004;   // stays up at rest
    }
  #endif
#else
    ppmio.ramdp->reg_status_1 &= ~0x0004;
#endif
    ppmio.ramdp->reg_status_2.bits.busy = 0;

    ppm_hb_overwrite(posted, ppmio.ramdp->reg_cmd);
    hb_w8(9, 10);
    ppmio.ramdp->reg_cmd = cmd_resp;
#if PPM_BUSY_REST && PPM_BUSY_CLEAR_THROUGH_RESP
    if (pointer_cmd) {
        // Busy is clear and the response is out. Hold busy clear until the
        // game's next post, then raise it before that post's immediate poll.
        // No other work here (sfx_player_update would open the window again).
        for (u32 i = 0; i < PPM_BUSY_WAIT_LOOPS; i++) {
            if (ppmio.ramdp->reg_cmd & 0x8000) {
                break;
            }
        }
        ppmio.ramdp->reg_status_1 |= 0x0004;
    }
#endif
}

void cmd_unknown() {

    printf("unknown cmd: %x\n", ppmio.ramdp->reg_cmd);
}

void cmd_unknown_muted() {
    //cmd_unknown();
}

void cmd_00() {

    u8 arg = ppmio.ramdp->reg_cmd;

    if (arg == 0xaa) {
        cmd_resp = 0x00ff;
    } else {
        cmd_resp = 0x0000;
    }
}

void cmd_81_init() {

    // initial startup/reset? - 3 0w8100 writes on startup
    // finding arcade mode sends 0x810f

    FPGAIO->ctrl.sdram_en = 1;
#if PPM_CHIP_81
    // D25, the chip's 81 handler $0801AFC4-$0801AFE4 (no engine gate, no argument test):
    // G+9 := bit 1, G+$A := bit 2, G+$B := bit 3, G+$C := bit 4 of the posted word
    // ($0801AFC4-$0801AFE0), G+$190 := 1 ($0801AFD8-$0801AFE2), completion ($0801AFE4).
    // Those flags are the trace counters to RAMDP $1B00, the Boom Box feed, the MegaWire
    // task step and the watchdog reset, none of which exists here. It touches
    // no sprite state and no RAMDP: the slot count, the cache, the handles and the
    // 68000's object records $0F80-$137F are left as they are. sdram_en above is ours'
    // own FPGA mapper bit (the pair of 84), not a chip field, and stays.
#else
    ppm_vram_set_budget(0);
    ppm_obj_reset();
#endif
}

void cmd_84_sdram_off() {
    FPGAIO->ctrl.sdram_en = 0;
}

void cmd_AD_obj_add() {

#if PPM_SAT_SNAPSHOT
    snap_cnt_ad++;
#endif
    u8 arg = ppmio.ramdp->reg_cmd;

    ppm_obj_add(arg);
}

void cmd_AE_frame_start() {

    // Counted HERE, one call before the tick inside ppm_obj_frame_start, so the
    // pair says whether 0xAE is dispatched at all or only mis-reported.
#if PPM_SAT_SNAPSHOT
    snap_cnt_ae++;
#endif
    // frame begin
    ppm_obj_frame_start();
}

void cmd_AF_frame_end() {

#if PPM_SAT_SNAPSHOT
    snap_cnt_af++;
#endif

    // frame finish
    // af01: no scaling ongoing
    // af02: must reserve bandwith for scaling buffer?

    ppm_obj_frame_end();
}

void cmd_B1_sprite_pause() {

#if PPM_CHIP_CACHE_MISS && PPM_CHIP_LOAD_CAP
    // cachefix: on the chip B1 runs the load-list flush ($0801BFBA -> $08018FFC),
    // which empties the list, so the 15-load cap starts again (mame.c).
    ppm_chip_flush_loads();
#endif
    if (ppmio.ramdp->sat_count == 0) {
        memset(&ppmio.ramdp->sat_data[0], 0, 8);
    }
}

void cmd_C6_setup_data() {

#if PPM_SAT_SNAPSHOT
    ppm_snapshot_boot();
#endif

    // load/setup base data

    u32 time = FPGAIO->time;

    printf("===== data setup =====\n");


    ppm_setup_data(
            swapshorts(ppmio.ramdp->cmd_args_long[0]),
            swapshorts(ppmio.ramdp->cmd_args_long[1]),
            swapshorts(ppmio.ramdp->cmd_args_long[2]),
            swapshorts(ppmio.ramdp->cmd_args_long[3]),
            swapshorts(ppmio.ramdp->cmd_args_long[4]),
            swapshorts(ppmio.ramdp->cmd_args_long[5]),
            swapshorts(ppmio.ramdp->cmd_args_long[6])
            );

    time = FPGAIO->time - time;
    printf("setup time: %i\n", time); //just for mcu core speed test
    printf("======================\n");
#if PPM_CHIP_EC || PPM_CHIP_B0
    // The chip's C6 job runs the engine init $08019734 for the first C6 only: a later C6
    // completes at $0801B204-$0801B20C without the job, because the job set $2001341C := 1
    // ($0801A346) and only the reset path clears it ($0801FAE4). See mame.c.
    if (!ppm_chip_engine_ready) {
#if PPM_CHIP_B0
        ppm_chip_b0_reset();        // $0801973C-$080197B8: the B0 worker's steps ($08019410-$0801948A)
#endif
        ppm_chip_engine_ready = 1;  // $080197C2-$080197CA: flag H+$400 := 1
                                    // (when the chip's setup $080195E0 succeeds; ours cannot fail)
    }
#endif
}

void cmd_DA_unpack() {

    // unpack request

    u32 src = (ppmio.ramdp->cmd_args[1] << 16) + ppmio.ramdp->cmd_args[2];
    u32 dst = ppmio.ramdp->cmd_args[0];

    u32 da_len = ppm_unpack(src, dst);
#if PPM_SAT_SNAPSHOT
    snap_da_note_src(src, da_len, dst);
#endif
#if PPM_DA_PAD
    {
        // mode is the 0xDA command word's low byte; the dispatcher split the
        // command off as reg_cmd >> 8 and leaves the word in place until the
        // handler returns (it writes cmd_resp afterwards).
        u32 mode = ppmio.ramdp->reg_cmd & 0xFF;
        u32 P = (mode == 2) ? 0x4000 : 0x800;
        u32 T = da_len % P;
        // Only a short tail can be over-read, and only a payload at least one
        // page long has a "previous page" to mirror. Stay inside SDRAM.
        if (T && da_len >= P && dst + da_len + P <= 0x100000) {
            u8 *b = (u8 *) ppmio.sdram;
            memcpy(b + dst + da_len,           b + dst + da_len - P, P - T);   // previous page's tail
            memcpy(b + dst + da_len + (P - T), b + dst + da_len - T, T);       // this page's head
        }
    }
#endif

    // paprium-pocket: RESTORED. Dropping this write was tested on hardware and
    // REGRESSED the game - the cell room background glitched, which it had not
    // before - while the elevator was unchanged. So despite krikzz's "optional ?"
    // and the existence of 0xDB, the game genuinely relies on 0xDA leaving the
    // stream pointer at the decoded data. 0xDA is a real consumer of the window,
    // not a stray write. Do not remove it again.
#if PPM_SAT_SNAPSHOT
    snap_da_count++;
    snap_da_last_dest = dst;
    snap_da_reset_high();   // a fresh payload: the loader has not touched it yet
    if (dst == 0x9000) {
        snap_da_dest_9000++;    // rewind would be a no-op for this one
    } else {
        snap_da_pending_set();  // a pointer 0xAF would throw away
        snap_da_note_other(dst);
    }
#endif
    {
        u32 prev_ptr = ppm_sptr_shadow;
        if (ppmio.ramdp->dma_cmd_count != 0) snap_ptr_while_list_pending++;
        u32 new_ptr = ppmio.ramdp->cmd_args[0]; // optional ? - but load-bearing
        FPGAIO->sdram_ptr = new_ptr;
        ppm_sptr_shadow = new_ptr;
#if PPM_EPOCH_RING
        snap_epoch_note(prev_ptr);
#endif
    }
}

void cmd_DB_set_dma_ptr() {
    // setup sdram pointer for read
#if PPM_SAT_SNAPSHOT
    // If this fires often the game re-points before it reads, and the 0xAF rewind
    // cannot be hurting anything.
    snap_db_count++;
    snap_da_pending_clear();
    snap_db_note(swapshorts(ppmio.ramdp->cmd_args_long[0]));
#endif
    {
        u32 prev_ptr = ppm_sptr_shadow;
        if (ppmio.ramdp->dma_cmd_count != 0) snap_ptr_while_list_pending++;
        u32 new_ptr = swapshorts(ppmio.ramdp->cmd_args_long[0]);
        FPGAIO->sdram_ptr = new_ptr;
        ppm_sptr_shadow = new_ptr;
#if PPM_EPOCH_RING
        snap_epoch_note(prev_ptr);
#endif
    }
}

void cmd_DF_eep_rd() {

    u8 arg = ppmio.ramdp->reg_cmd;

    u8 *ram_dp = (u8 *) ppmio.ramdp;

    switch (arg) {
        case 1:
        case 2:
        case 3:
            memcpy(&ram_dp[ppmio.ramdp->cmd_args[0]], &ppmio.bram[(0x200 + arg * 0x200)], 0x100);
            break;
        case 4:
            memcpy(&ram_dp[ppmio.ramdp->cmd_args[0]], &ppmio.bram[0], 0x200);
            break;
    }

    /*
    printf("eep rd %i: ", arg);
    //u32 *ptr = (u32 *) & ram_dp[ppmio.ramdp->cmd_args[0]];
    u32 *ptr = (u32 *) & ppmio.bram[(arg * 0x200)];
    for (int i = 0; i < 32 / 4; i++) {
        printf("%x", ptr[i]);
    }
    printf("\n", arg);*/
}

void cmd_E0_eep_wr() {

    // eeprom save (command_args[0]=0xbeef)

    u8 arg = ppmio.ramdp->reg_cmd;

    u8 *ram_dp = (u8 *) ppmio.ramdp;

    switch (arg) {
        case 1:
        case 2:
        case 3:
            memcpy(&ppmio.bram[(0x200 + arg * 0x200)], &ram_dp[ppmio.ramdp->cmd_args[1]], 0x100);
            break;
        case 4:
            memcpy(&ppmio.bram[0], &ram_dp[ppmio.ramdp->cmd_args[1]], 0x200);
            break;
    }

    ppmio.ramdp->reg_status_2.bits.eep_error1 = 0;
    ppmio.ramdp->reg_status_2.bits.eep_error2 = 0;

}

void cmd_E7_mwire() {

    // send some data over network
    ppmio.ramdp->reg_status_2.bits.mwire_data_in = 1; // pretend data is in
    ppmio.ramdp->net_data[0x10 / 2] = ppmio.ramdp->cmd_args[0] + 16; // pretend 16 bytes in?
}

void cmd_EC_vram_budget() {

    // set vram block budget
#if PPM_CHIP_EC
    // D08, the chip's EC gate $0801B152-$0801B178. A refusal changes no state here (the
    // chip's $1FE6 bit 9 and error log are not followed: see mame.c, CHIP EC, B0 AND 81).
    // reg_cmd still holds the posted word: the dispatcher writes cmd_resp after the handler.
    if (!ppm_chip_engine_ready) {                   // $0801B152-$0801B15E: engine flag H+$400 == 0 -> refusal (code 6)
        return;
    }
    if (!(ppmio.ramdp->reg_cmd & 0x4000)) {         // $0801B162-$0801B166: bit 14 clear, the $AC form -> refusal (code 7)
        return;
    }
    if (ppmio.ramdp->cmd_args[0] != 0) {            // $0801B168-$0801B16E: arg0 ($1E10) != 0 -> refusal (code 7)
        return;
    }
    if (ppmio.ramdp->cmd_args[1] > 0x80) {          // $0801B170-$0801B176: arg1 ($1E12) > $80 (bhi) -> refusal (code 7)
        return;
    }
    ppm_chip_ec_count(ppmio.ramdp->cmd_args[1]);    // $0801B178 -> $0801CD5E-$0801CD60: worker $08017EE0(0, arg1)
#else

    //u16 blocks = SWAP_WORD(ppmio.ramdp->cmd_args[1]);
    u16 blocks = ppmio.ramdp->cmd_args[1];
    ppm_vram_set_budget(blocks);

    if (ppmio.ramdp->cmd_args[0]) {
        printf("PPM command 0xec: unk arg 0 (0x%x)", ppmio.ramdp->cmd_args[0]);
    }
#endif
}

void cmd_F2_unpack() {

    // todF2o: check block range
    //used in sprites test menu

    ppm_unpack(ppm_block_addr(ppmio.ramdp->cmd_args[0]), PPM_SCRATCH_BASE);
    ppm_unpack(ppm_block_addr(ppmio.ramdp->cmd_args[0]), (PPM_SCRATCH_BASE + 0x200));
    //ppm_sdram_pointer = &ppm_sdram[PPM_SCRATCH_BASE / 2];
    {
        u32 prev_ptr = ppm_sptr_shadow;
        u32 new_ptr = PPM_SCRATCH_BASE;
        FPGAIO->sdram_ptr = new_ptr;
        ppm_sptr_shadow = new_ptr;
#if PPM_EPOCH_RING
        snap_epoch_note(prev_ptr);
#endif
    }
}

void cmd_F4_unpack_scal() {
    ppm_unpack_scal(swapshorts(ppmio.ramdp->cmd_args_long[0]), 0, true);
}

void cmd_F5_stamp_rescale() {
    ppm_stamp_rescale(ppmio.ramdp->cmd_args[0], ppmio.ramdp->cmd_args[1], ppmio.ramdp->cmd_args[2], ppmio.ramdp->cmd_args[3]);
}
//============================================================================== audio

void cmd_B0_sprite_init() {

#if PPM_CHIP_B0
    // D20, the chip's B0 entry $0801AD3C-$0801AD6A (no bit-14 or argument test). It
    // writes no RAMDP: GPGX's $1F20-$1F8F clear (the #else below) is not the chip's;
    // that region is the chip's AF02 stash, which this firmware never writes.
    if (!ppm_chip_engine_ready) {   // $0801AD3C-$0801AD46: engine flag H+$400 == 0 -> refusal (code 6), $0801AD4C-$0801AD6A
        return;
    }
    ppm_chip_b0_reset();            // $0801AD48 -> $0801BFC2: worker $0801940C-$0801948E (mame.c), completion $0801BFC6
#else
    // paprium-pocket: stock mega-ppm mutes this. GPGX implements it as a clear of
    // 112 bytes of the DMA/sprite table (paprium.h, paprium_sprite_init):
    //     memset(paprium_s.ram + 0x1F20, 0, 14*8);
    // Without it stale DMA entries survive initialisation. MisterPezz82 suspected
    // this command in the elevator corruption and never followed it up.
    vu8 *ram = (vu8 *) ppmio.ramdp;
    for (int i = 0; i < 14 * 8; i++) {
        ram[0x1F20 + i] = 0;
    }
#endif
}

void cmd_88_audio_cfg() {

    // paprium-pocket: stock mega-ppm mutes this command, so the game's audio
    // configuration is written and then read back as stale memory. GPGX
    // implements it (paprium.h, paprium_audio_setting): the game stores its DAC
    // and NTSC selection at cart RAM 0x1800/0x1801 and reads it back later.
    // bit 0 is the DAC select - the in-game "VM DAC" option, choosing the
    // YM2612 DAC over the cartridge's own. bit 1 is NTSC.
    //
    // Byte indices are GPGX's verbatim, which is correct here rather than
    // lucky: ramdp_io.sv puts a 68000 byte at address A into MCU byte A^1, and
    // GPGX's ram[] carries the same relationship, so the two agree. Observed on
    // hardware firing five times during boot with args 0x02 and 0x0A.
    u8 arg = ppmio.ramdp->reg_cmd;
    vu8 *ram = (vu8 *) ppmio.ramdp;

    ram[0x1801] = arg & 0x01;
    ram[0x1800] = ((arg & 0x01) ? 0x80 : 0x00) + ((arg & 0x02) ? 0x40 : 0x00);

#if PPM_DAC_STREAM_FILL
    // Cart RAM 0x1802-0x19FF is an unsigned 8-bit PCM stream buffer that the
    // 68000 reads and pushes to YM2612 register 0x2A when the in-game "VM DAC"
    // box is ticked - the option that swaps the cartridge's DT128VALT converter
    // for the YM2612's own. Confirmed on hardware: with the window uninitialised
    // the game streamed whatever ramdp happened to hold, which is what the
    // long-standing "VM DAC produces static" report was.
    //
    // 0x80 is mid-scale for an unsigned 8-bit DAC, so filling it is a DC level.
    // That silences the YM2612 path instead of feeding it noise. The cartridge
    // audio is unaffected and plays as it does with the option off.
    //
    // WHAT THIS IS NOT: hardware also THINS the mix, because the cartridge's PCM
    // is routed through the YM2612's 8-bit DAC instead of its own - same cues,
    // worse converter, and FM channel 6 spent. We do not reproduce that; see
    // docs/PORT_PLAN.md for the design and why it was not built. Here the option
    // is inert rather than wrong.
    //
    // Filled here rather than at reset because cmd_88 fires several times during
    // boot AND again whenever the option is toggled, so the window is fresh
    // whenever the setting changes.
    //
    // The range is even-aligned and of even length, so it is closed under the
    // ramdp_io.sv byte swap (MCU index = 68000 address ^ 1) and a constant fill
    // is identical in either address order. 0x1800/0x1801 are deliberately left
    // alone - they carry the DAC and NTSC settings the game reads back, and
    // stomping them would undo the 0x88 fix above.
    for (int i = 0x1802; i < 0x1A00; i++) {
        ram[i] = 0x80;
    }
#endif
}

// ---------------------------------------------------------------------------
// paprium-pocket: Boom Box VU bars.
//
// Cart RAM 0x1B98..0x1BFF is a per-voice stereo level feed - 26 voices of
// {u16 L, u16 R} = 104 bytes, ending exactly at 0x1C00. On real hardware the
// cartridge's music engine rewrites it every row with "does this voice have a
// pattern this row"; GPGX's interpreter does the same (paprium.h:472-473,
// `index ? 0xE0 : 0`). The Boom Box's 26-bar graph is drawn straight from it,
// one bar per voice.
//
// This port substitutes CDDA and never sequences the module, so nothing wrote
// that window at all and the game rendered its bars out of uninitialised cart
// RAM - they sat permanently lit. Note the neighbouring 0x1802..0x19FF fill in
// cmd_88_audio_cfg stops at 0x1A00 and never reached this.
//
// Rather than smear one playback level across 26 identical columns, drive the
// bars from the module we ALREADY unpack in cmd_8C_bgm_play and then discard.
// That is the real per-voice arrangement, at the module's own tempo, and costs
// no RTL.
//
// Tempo: the row clock is the synth's own, measured against the hardware
// captures (paprium-pocket docs/PORT_PLAN.md, "Absolute tempo, solved"):
//
//     row = 2*header[0x07] + (0xFA operand & 0x0F)   ticks of 1/99.8745 s
//
// applied per row - an 0xFA takes effect on the row it sits on and holds until
// the next one. It is NOT frames-per-row at 60 Hz. That was GPGX's reading, and
// under it Stage Clear looped every 4.86 s where the capture loops every 5.82 s
// (audio envelope autocorrelation 5.824 s; the bars themselves 5.83-5.85 s;
// 97 rows x 6 ticks = 5.827 s). The same code also ran 8 rows past the end of
// every pattern into its null event record: header 0x0A IS the row count.
// ---------------------------------------------------------------------------
#define PPM_VU_BASE     0x1B98      // 68000 address of voice 0's L word
#define PPM_VU_VOICES   26
#define PPM_VU_ON       0x00E0      // level the cart writes for a sounding voice

static u32 vu_mod   = 0;            // SDRAM address of the unpacked module
static u16 vu_secs  = 0;            // order-list positions per voice (header 0x08)
static u16 vu_loop  = 0;            // position playback repeats from (header 0x09)
static u16 vu_bars  = 0;            // rows per pattern (header 0x0A, 0 = 256)
static u16 vu_seg   = 0;
static u16 vu_row   = 0;
static u32 vu_due   = 0;            // ms tick the next row falls on
static u32 vu_rem   = 0;            // remainder in 1/100000 ms, keeps the grid drift-free
static u16 vu_base  = 8;            // 2 * header[0x07]: ticks per row before any 0xFA
static u8  vu_fa    = 0;            // current 0xFA operand & 0x0F
static u8  vu_on    = 0;

// ppm_unpack writes through ppmio.sdram with ^1 on every byte, so read it back
// the same way.
static u8 vu_mb(u32 off) {
    return ppmio.sdram[(vu_mod + off) ^ 1];
}

// ramdp is indexed MCU-side as (68000 address ^ 1), so a big-endian word at
// 68000 address `a` splits as ram[a+1] = high byte, ram[a] = low byte.
static void vu_put(u32 a, u16 v) {
    vu8 *ram = (vu8 *) ppmio.ramdp;
    ram[a + 1] = (u8) (v >> 8);
    ram[a] = (u8) v;
}

static void vu_all(u16 v) {
    for (int ch = 0; ch < PPM_VU_VOICES; ch++) {
        vu_put(PPM_VU_BASE + ch * 4, v);
        vu_put(PPM_VU_BASE + ch * 4 + 2, v);
    }
}

void ppm_music_vu_start(u32 mod_addr) {
    vu_mod = mod_addr;
    vu_base = 2 * (vu_mb(0x07) ? vu_mb(0x07) : 4);
    vu_fa = 0;
    vu_secs = vu_mb(0x08);
    vu_loop = (vu_mb(0x09) < vu_secs) ? vu_mb(0x09) : 0;
    vu_bars = vu_mb(0x0A) ? vu_mb(0x0A) : 0x100;
    vu_seg = 0;
    vu_row = 0;
    vu_rem = 0;
    vu_due = FPGAIO->time;
    vu_on = (vu_secs != 0);
    if (!vu_on) vu_all(0);
}

void ppm_music_vu_stop() {
    vu_on = 0;
    vu_all(0);
}

// Called from ppm_start()'s loop, which runs far faster than the row rate, so at
// most one row is advanced per call and the grid stays accurate.
void ppm_music_vu_update() {

    if (!vu_on) return;
    if ((s32) (FPGAIO->time - vu_due) < 0) return;

    for (int ch = 0; ch < PPM_VU_VOICES; ch++) {
        u32 po = 0xD8 + ((u32) ch * vu_secs + vu_seg) * 2;
        u32 ptr = ((u32) vu_mb(po) << 8) | vu_mb(po + 1);
        u8 idx = vu_mb(ptr + vu_row);       // grid byte: index into this pattern's event table
        u16 lvl = idx ? PPM_VU_ON : 0;
        vu_put(PPM_VU_BASE + ch * 4, lvl);
        vu_put(PPM_VU_BASE + ch * 4 + 2, lvl);
        if (idx) {
            // the 8-byte event record sits after the vu_bars grid bytes; words
            // 1..3 are (command, operand) and 0xFA sets the row period
            u32 ev = ptr + vu_bars + (u32) idx * 8;
            for (int k = 2; k < 8; k += 2)
                if (vu_mb(ev + k) == 0xFA) vu_fa = vu_mb(ev + k + 1) & 0x0F;
        }
    }

    // this row's length: (vu_base + vu_fa) ticks of 10.01257 ms, the remainder
    // carried in 1/100000 ms so the grid does not drift
    u32 num = (u32) (vu_base + vu_fa) * 1001257u + vu_rem;
    vu_due += num / 100000u;
    vu_rem = num % 100000u;

    if (++vu_row >= vu_bars) {
        vu_row = 0;
        if (++vu_seg >= vu_secs) vu_seg = vu_loop;
    }
}

void cmd_8C_bgm_play() {

    // bgm play, check & 0x80
    u8 arg = ppmio.ramdp->reg_cmd;
    {
        hb_w8(9, 5); hb_w32(28, ppm_bgm_unpack_addr);
        u32 bl = ppm_unpack(ppm_bgm_addr(arg & 0x7f), ppm_bgm_unpack_addr);
        hb_w32(32, bl);
        if (ppm_bgm_unpack_addr + bl > PPM_SCRATCH_BASE) snap_bgm_over++;   // module reached the MCU scratch (counted, no UART on the Pocket)
        ppm_music_vu_start(ppm_bgm_unpack_addr);   // paprium-pocket: Boom Box bars
    }

    if ((arg & 0x80)) {
        mdp_play(arg & 0x7f);
    } else {
        // paprium-pocket: bit 7 clear marks a ONE-SHOT cue - Stage Clear,
        // Continue, Game Over, High Score, Ending. Stock mega-ppm stops the
        // music instead of playing them, so those cues are simply silent.
        // Captured on hardware: cmd_8C track 0x35 (53), bit 7 clear, at the end
        // of a stage - and 53 is one of the tracks the cue sheet marks NOLOOP.
        mdp_play_once(arg & 0x7f);
    }
}

void cmd_8D_bgm_cfg() {

    u8 arg = ppmio.ramdp->reg_cmd;

    if (arg == 0 || arg == 8) {
        mdp_stop();
        ppm_music_vu_stop();   // paprium-pocket: park the Boom Box bars
    }
}

void cmd_C9_vol_bgm() {

    FPGAIO->vol_bgm = ppmio.ramdp->reg_cmd;
}

void cmd_CA_vol_sfx() {
    FPGAIO->vol_sfx = ppmio.ramdp->reg_cmd;
}

void cmd_D1_sfx_play() {

    sfx_play(ppmio.ramdp->reg_cmd);
}

void cmd_D2_sfx_stop() {
    sfx_stop(ppmio.ramdp->reg_cmd);
}

void cmd_D3_sfx_loop() {
    sfx_loop(ppmio.ramdp->reg_cmd);
}

void cmd_D5_sfx_stopall() {
    //not sure about this cmd, but game execute looped sfx at chan 0x40
    //then execute this cmd. looped sfx keep playing on score screen
    sfx_stop(0xC0);
}

//============================================================================== 
