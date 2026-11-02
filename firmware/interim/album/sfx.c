/* Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later) */

#include "appmain.h"

//based on libretro

#define SFX_CHAN_NUM    8

#define SFX_FLAG_AMP    0x0100//6db gain?
#define SFX_FLAG_PI_H   0x2000
#define SFX_FLAG_ECHO   0x4000
#define SFX_FLAG_PI_T   0x8000

typedef struct {
    u32 age;
    u32 ptr;
    u32 size;
    u32 step;
    u32 step_num;
    u32 decay;
    u32 looped;
    u32 ptr_base;
    u32 size_base;
    u32 flags;
} SfxChan;


SfxChan sfx_chan[SFX_CHAN_NUM];

void sfx_play(u8 arg) {

    u8 chan_idx = 0;
    u32 oldest_age = 0;

    u8 *sfx = &ppmio.flash[ppm_sfx_base_addr + arg * 8];
    u8 cmask = ppmio.ramdp->cmd_args[0];
    u16 vol = ppmio.ramdp->cmd_args[1];
    u16 pan = ppmio.ramdp->cmd_args[2];
    u16 flags = ppmio.ramdp->cmd_args[3];

    //seek free chan
    for (int i = 0; i < SFX_CHAN_NUM; i++, cmask >>= 1) {

        if ((cmask & 1) == 0) {
            continue;
        }

        if (sfx_chan[i].size || !ppmio.sfx[i].status.fifo_empry) {

            //oldest chan will be used in case if no free channels
            if (sfx_chan[i].age < oldest_age) {
                oldest_age = sfx_chan[i].age;
                chan_idx = i;
            }
            continue;
        }

        chan_idx = i;
        break;
    }

    sfx_chan[chan_idx].age = tick_ctr;
    sfx_chan[chan_idx].flags = flags;

    sfx_chan[chan_idx].ptr = ppm_sfx_base_addr + swapshorts(*(u32 *) & sfx[0]);
    sfx_chan[chan_idx].size = (sfx[4] << 16) | *(u16 *) & sfx[6];
    sfx_chan[chan_idx].step_num = sfx[5] & 0x03;
    sfx_chan[chan_idx].step = 0;
    sfx_chan[chan_idx].looped = 0;
    sfx_chan[chan_idx].decay = 0;
    sfx_chan[chan_idx].ptr_base = sfx_chan[chan_idx].ptr;
    sfx_chan[chan_idx].size_base = sfx_chan[chan_idx].size;


    // paprium-pocket: flag 0x0100 STEPS THE SAMPLE RATE DOWN ONE TABLE INDEX.
    //
    // GPGX calls that bit "amplify" and this port rendered it as x1.25 gain. It is
    // not gain: the large grunt's death is the ordinary grunt's sample (sfx 0x1A,
    // table rate index 3 = 9600 Hz) played at 6000 Hz - index 4. That 0.625x ratio
    // was identified by ear against pitched copies restricted to the rates the
    // engine can produce, and the whole 127-entry bank was auditioned and contains
    // no separate fat-death sample, so it cannot be a different id.
    //
    // Gain was never it: the fat death measures 0.90x the grunt's amplitude.
    // And 0x2100 - bit 0 with bit 5 - is not redundant, because bit 5 is a
    // sample-skip halver while bit 0 steps the rate table.
    //
    // DONE HERE, NOT IN RTL. The same +1 in audio_sfx.sv put an adder in front of
    // the aclk mux and cost 0.4 ns of setup; three fitter seeds all landed between
    // -2.72 and -2.98, and -2.715 was measured NOT TO BOOT. This costs zero logic.
    //
    // Hardware bit 0 is cleared on the way out so the RTL's amp path cannot also
    // fire - amp stays implemented, it just never gets asserted.
    u8 type = sfx[5];

    if (flags & 0x0100) {
        u8 sr = (type >> 4) & 7;
        if (sr < 5) {                   // saturate: 5 = 5333 Hz is the last rate
            sr++;
        }
        type = (type & ~0x70) | (sr << 4);
    }

    ppmio.sfx[chan_idx].type = type; //sample rate
    ppmio.sfx[chan_idx].flags = (flags >> 8) & ~0x01;
    ppmio.sfx[chan_idx].vol = vol * 96 / 128; //reduce sample vol a bit?
    ppmio.sfx[chan_idx].pan = pan;


    /*
    if (flags) {
        printf("flags: %x\n", flags);
    }*/

    //printf("d: %i\n", sfx_chan[chan_idx].type & 0x03); 
    //printf("d: %i\n", ppmio.ramdp->cmd_args[1]); 
}

void sfx_loop(u8 arg) {

    //printf("+lop: %x\n", arg);

    for (int i = 0; i < SFX_CHAN_NUM; i++, arg >>= 1) {

        if ((arg & 1) == 0) {
            continue;
        }

        ppmio.sfx[i].vol = ppmio.ramdp->cmd_args[0];
        ppmio.sfx[i].pan = ppmio.ramdp->cmd_args[1];
        sfx_chan[i].decay = ppmio.ramdp->cmd_args[2];
        sfx_chan[i].looped = 1;

        // paprium-pocket fix: re-arm a channel that has already finished.
        // sfx_player_update() skips any channel with size == 0, so the restart at
        // the bottom of its loop is unreachable once a sample has ended. sfx_play()
        // clears `looped`, and the game enables looping LATER - the punk-TV cue is
        // started at volume 0 and only looped and ramped up as the player
        // approaches, by which time the 4.99 s sample has run out and the channel
        // is dead. Measured on hardware: 29,920 PCM words pushed (exactly the
        // sample length), FIFO empty, then the volume ramp climbing 0x00 -> 0xC0
        // with nothing playing.
        if (sfx_chan[i].size == 0) {
            sfx_chan[i].ptr = sfx_chan[i].ptr_base;
            sfx_chan[i].size = sfx_chan[i].size_base;
        }

        //break; //rem me?
    }
}

void sfx_stop(u8 arg) {

    int flags = ppmio.ramdp->cmd_args[0];

    //printf("-stp: %x\n", arg);

    for (int i = 0; i < SFX_CHAN_NUM; i++) {

        if (!(arg & (1 << i))) {
            continue;
        }

        if (flags == 0) {
            sfx_chan[i].size = 0;
        }

        sfx_chan[i].decay = flags;
        sfx_chan[i].looped = 0;

        //break;//rem me?
    }
}

void sfx_player_update() {

    int sample;

#if PPM_SFX_QUIET_DMA
    if (ppm_list_pending) {
        if (ppmio.ramdp->dma_cmd_count == 0) ppm_list_pending = 0;   // the runner zeroed it
        else return;                                                  // the VDP is reading the window
    }
#endif
    for (int ch = 0; ch < SFX_CHAN_NUM; ch++) {

        if (sfx_chan[ch].size == 0) {
            continue;
        }

        if (ppmio.sfx[ch].status.fifo_full) {
            //printf("fifo full\n");
            continue;
        }

        sample = ppmio.flash[sfx_chan[ch].ptr^1]; //use flash_sw


        if (sfx_chan[ch].step_num == 2) {

            if (sfx_chan[ch].step == 0) {
                sample >>= 4;
                sfx_chan[ch].step = 1;
            } else {
                sfx_chan[ch].step = 0;
                sfx_chan[ch].ptr++;
            }

            sample = (((sample & 0x0F) * 65536) / 16) - 32768;

        } else {

            sfx_chan[ch].ptr++;
            sample = (((sample & 0xFF) * 65536) / 256) - 32768;
        }

        ppmio.sfx[ch].sample = sample;

        sfx_chan[ch].size--;

        if (sfx_chan[ch].size == 0 && sfx_chan[ch].looped) {
            sfx_chan[ch].ptr = sfx_chan[ch].ptr_base;
            sfx_chan[ch].size = sfx_chan[ch].size_base;
        }
    }
}
