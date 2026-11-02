/* Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later) */

#include "appmain.h"

#define MDP_TIMEOUT     100
#define MDP_OK          0
#define MDP_ERR_TOUT    1
#define MDP_ERR_ID      2
#define MDP_ERR_NOCD    3

#define MDP_CMD_VER     0x1000
#define MDP_CMD_PLAY_S  0x1100
#define MDP_CMD_PLAY_L  0x1200
#define MDP_CMD_PLAY_D  0x1A00 //loop offsed in args
#define MDP_CMD_PLAY_X  0x1B00
#define MDP_CMD_PAUSE   0x1300
#define MDP_CMD_RESUME  0x1400
#define MDP_CMD_VOL     0x1500
#define MDP_CMD_STAT    0x1600
#define MDP_CMD_TNUM    0x2700

#define MDP_OVLKEY      0xCD54
#define MDP_ID0         0x5241
#define MDP_ID1         0x5445

typedef struct {
    vu16 id[2];
    vu16 overlay;
    vu16 resp;
    vu16 cmd;
    u8 data[4096];
} Mdp;

#define MDP             ((Mdp *) (ADDR_MDP + 0x3F7F6))

u8 mdp_cmd(u16 cmd);
u8 mdp_init_();

u8 mdp_on;

#if FW_S1
#include "s1_interim.h"     // the new firmware (FW_S1): TEST's ordered audio-call log
#endif

#if FW_S1 && !PPM_RELEASE
/* TEST, debug save version 6 (2026-10-19): the album's state in the debug save. B Jam heard no Blue Bar street
 * music in a hardware test although the game posts 8C8B there and this file then writes MD+ 0x120B (track 11, loop):
 * the record tells whether the command reached the adapter, which track the CDDA fetch holds and whether it plays, and
 * whether its ring starved (paprium_mdp_adapter.sv: the result word {current_track, 7'b0, playing} and the command word
 * it last took; paprium_xlink.sv 0x14 / 0x18). The words are s1_audio_stats' alb_* (interim/s1/s1_interim.h): the album
 * calls below note themselves (interrupts off: an L1 8D and the 8C job can meet the debug save's write), and
 * board/pocket/dbgsave.c calls s1_album_poll at every write with the VS count it extends to 32 bits. */
#ifdef POCKET_XLINK_BASE
#define ALB_XL(off)     (*(volatile u32 *)(uintptr_t)(POCKET_XLINK_BASE + (off)))
#else
#define ALB_XL(off)     0u                  /* the host board has no XLINK */
#endif
#define ALB_XL_UNDERRUN 0x14u               /* XLINK: [15:0] CDDA underruns, [31:16] snoop overflows */
#define ALB_XL_LOST     0x18u               /* XLINK: [15:0] SRAM loader words lost, [31:16] CRAM ring writes lost */
static struct { u32 vs, fresh; } alb __attribute__((section(".bss_upper")));   /* the last play request's VSCNT; set
                                                                                until the next write has taken it */

/* an album call: cmd = its command word (0 the init); kind ALB_INIT, ALB_PLAY, ALB_STOP: written only while the album
   is on (mdp_on), else marked S1_ALB_OFF; ALB_VOL: always written. Out of line and for size: five callers, a few a
   minute */
#define ALB_INIT        0u
#define ALB_PLAY        1u
#define ALB_STOP        2u
#define ALB_VOL         3u
#define ALB_OS          __attribute__((noinline, optimize("Os")))
static ALB_OS void album_call(u32 cmd, u32 play)
{
    s1_audio_stats_t *a = &s1_audio_stats;
    u32 s = brd_irq_save();
    if (!mdp_on && play != ALB_VOL)
        cmd |= S1_ALB_OFF;
    a->alb_calls = (a->alb_calls & 0xFFFFu) | (cmd << 16);
    if (play == ALB_PLAY) {
        a->alb_calls = cmd | (cmd << 16);
        a->alb_wait = S1_ALB_WAITING;
        alb.vs = brd_vs_count();
        alb.fresh = 1u;
    } else if (play == ALB_STOP && (a->alb_wait & S1_ALB_WAITING))
        a->alb_wait ^= S1_ALB_WAITING | S1_ALB_STOPPED;     /* a stop ends the wait: the track never played */
    brd_irq_restore(s);
}

ALB_OS void s1_album_poll(u32 frames)
{
    s1_audio_stats_t *a = &s1_audio_stats;
    u32 s = brd_irq_save(), r, w;
    r = MDP->resp | ((u32)MDP->cmd << 16);
    a->alb_res = r;
    a->alb_xl14 = ALB_XL(ALB_XL_UNDERRUN);
    a->alb_xl18 = ALB_XL(ALB_XL_LOST);
    if (alb.fresh) {                        /* the first write after a play request: its frame, the underruns now */
        alb.fresh = 0u;
        a->alb_play_f = frames - ((brd_vs_count() - alb.vs) & BRD_VS_COUNT_MASK);
        a->alb_play_und = a->alb_xl14 & 0xFFFFu;
    }
    w = a->alb_wait;
    if (w & S1_ALB_WAITING) {
        w = frames - a->alb_play_f;
        a->alb_wait = (r & 1u) ? w : (w | S1_ALB_WAITING);
        if (w > a->alb_wait_max)
            a->alb_wait_max = w;
    }
    brd_irq_restore(s);
}
#define ALB_CALL(cmd, play)     album_call((cmd), (play))
#else
#define ALB_CALL(cmd, play)     ((void)0)
#endif

void mdp_init() {
#if FW_S1 && !PPM_RELEASE
    s1_au_note(10u, 0u);
#endif

    u8 resp = mdp_init_();

    if (resp) {
        printf("mdp error: %x\n", resp);
    }
    ALB_CALL(0u, ALB_INIT);
}

u8 mdp_init_() {

    u8 resp;
    printf("mdp init...\n");

    mdp_on = 0;


    MDP->overlay = MDP_OVLKEY; //unlock md+ overlay

    if (MDP->id[0] != MDP_ID0 || MDP->id[1] != MDP_ID1) {
        return MDP_ERR_ID;
    }

    u8 cue_path[1024];
    ed_fifo_flush();
    resp = ed_cmd_rom_path(cue_path, 1);
    if (resp)return resp;
    if (cue_path[0] == 0)return MDP_ERR_NOCD;
    
    printf("cd mount... %s\n", cue_path);
    resp = ed_cmd_cd_mount(cue_path);
    if (resp)return resp;


    /*
    printf("mdp id: %x\n", (MDP->id[0] << 16) | MDP->id[1]);

    if (MDP->id[0] != MDP_ID0 || MDP->id[1] != MDP_ID1) {
        return MDP_ERR_ID;
    }

    resp = mdp_cmd(MDP_CMD_TNUM);
    if (resp)return resp;
    printf("tacks : %i\n", MDP->resp >> 8);

    resp = mdp_cmd(MDP_CMD_STAT);
    if (resp)return resp;
    printf("status: %x\n", MDP->resp);*/

    resp = mdp_cmd(MDP_CMD_PAUSE);
    if (resp)return resp;

    mdp_set_vol(0xff);

    mdp_on = 1;

    return MDP_OK;
}

void mdp_play(u8 track) {
#if FW_S1 && !PPM_RELEASE
    s1_au_note(11u, track);
#endif

    ALB_CALL(MDP_CMD_PLAY_L | track, ALB_PLAY);
    if (!mdp_on) {
        return;
    }

    MDP->cmd = MDP_CMD_PLAY_L | track;
}

// paprium-pocket: one-shot playback, for the bit-7-clear cues cmd_8C used to
// throw away. MDP_CMD_PLAY_S ($11xx) is the MD+ play-once command, which this
// core's paprium_mdp_adapter already decodes as track_loop = 0.
void mdp_play_once(u8 track) {
#if FW_S1 && !PPM_RELEASE
    s1_au_note(12u, track);
#endif

    ALB_CALL(MDP_CMD_PLAY_S | track, ALB_PLAY);
    if (!mdp_on) {
        return;
    }

    MDP->cmd = MDP_CMD_PLAY_S | track;
}

void mdp_stop() {
#if FW_S1 && !PPM_RELEASE
    s1_au_note(13u, 0u);
#endif

    ALB_CALL(MDP_CMD_PAUSE, ALB_STOP);
    if (!mdp_on) {
        return;
    }

    MDP->cmd = MDP_CMD_PAUSE; // | fade;
}

void mdp_set_vol(u8 vol) {
#if FW_S1 && !PPM_RELEASE
    s1_au_note(14u, vol);
#endif

    ALB_CALL(MDP_CMD_VOL | vol, ALB_VOL);
    MDP->cmd = MDP_CMD_VOL | vol;
}

u8 mdp_cmd(u16 cmd) {

#if FW_S1
    // the new firmware: the RTL ms counter is retired (docs/MCU_INTERFACE.md 4.3, and finding 7 of its section 0); the
    // same 100 ms on the board timer
    u32 t0 = brd_now();

    MDP->cmd = cmd;
    asm("nop");

    while (MDP->cmd == 0xffff) {
        if ((u32) (brd_now() - t0) > MDP_TIMEOUT * s1_clk(CLK_MS_CYCLES)) {
            return MDP_ERR_TOUT;
        }
    }

    return MDP_OK;
#else
    u32 time = FPGAIO->time + MDP_TIMEOUT;

    MDP->cmd = cmd;
    asm("nop");

    while (MDP->cmd == 0xffff) {
        if (FPGAIO->time > time) {
            return MDP_ERR_TOUT;
        }
    }

    return MDP_OK;
#endif
}