# interim/album - the 0.2.x sound path, kept until the synth took over (the FW_S5 build)

Words used on this page. The cart chip is the STM32 microcontroller on the real Paprium cartridge; the MCU is the
processor this firmware runs on (the NEORV32, a RISC-V soft CPU inside the FPGA). FW_S1 is defined for every build of
the new firmware's source set (`fwbuild.json`, `tools/fwbuild.py`); the 0.2.6 milestone builds compile without it.
FW_S5 (`board/board.h`) builds the full firmware, with the cart chip's song engine (`core/song`) and the synth in our
RTL; the FW_S5 = 0 build is the earlier firmware, which still uses the interim parts in this folder and is still built
and tested. The firmware was written in steps; the dates below say when each part landed. L1, L2a, L2b, L2c and L3 are
the scheduler's levels (`core/sched/README.md`): L1 reads the 68000's posts, L2a is the timer interrupt, L2b and L2c
run below it, L3 is the thread. RAMDP is the cart RAM that both the 68000 and the MCU see. CPU MATE is the
computer-controlled partner; its brain call runs on the MCU. The RV32 board model (`tests/equiv/rtlmodel.py`) is our
model of the MCU and its board, which runs the firmware images; a co-simulation runs the firmware on the simulated
RTL. TEST is the build with debug aids, RELEASE the one without. Row numbers such as B7 are rows of
`docs/ALLOWLIST.md`. "Measured" figures come from a run or a file; "estimated" ones are arithmetic on measured
figures.

As-is from final 0.2.6 (md5 = its `src_md5.txt`): `mdp.c/h` (MD+ CD audio adapter: the album), `everdrive.c/h` (the
EverDrive FIFO stub used by mdp_init), `sfx.c/h` (the SFX FIFO feeder). Until the song engine landed every build still
needed the album, the SFX feeder and the VU code, or it would have been silent. The FW_S5 build leaves the album path
out; its history credit goes to the 0.3.0 "History" section.

The first new-firmware step (stage 1, 2026-10-11; work item W6 of docs/STAGE1_PLAN.md, test T-B10 of
docs/BOOT_SPEC.md section 9) adds `#if FW_S1` guards, compiled only into the new firmware's images:
`mdp_cmd` times out on the board timer (the RTL millisecond counter is retired, `docs/MCU_INTERFACE.md` 4.3), and every
EverDrive FIFO wait in `everdrive.c` is bounded (50 ms; a missing MD+ adapter makes `mdp_init` give up instead of
hanging the boot). Without `FW_S1` both files compile to the same code as final 0.2.6.
The interim audio work adds two more `FW_S1` guards: `sfx_play` keeps the type byte it programs in `s1_sfx_type` (the
feeder's rate), and the TEST images log every album / SFX entry call (`s1_au_note`, the host's kinds).
2026-10-19, TEST only (`FW_S1 && !PPM_RELEASE`; B Jam heard no Blue Bar street music in a hardware test): the album
recorder. Every album call notes its command word in `s1_audio_stats.alb_calls` (the last call, and the last play
request; bit 15 = not written, the album off), a play request also its VSCNT; `s1_album_poll`, called first by every
debug-save write (board/pocket/dbgsave.c), reads the MD+ result word ({current_track, 7'b0, playing}) and the command
word the adapter last took, XLINK 0x14 (CDDA underruns, snoop overflows) and 0x18 (CRAM ring writes, loader words
lost), resolves the request's frame and runs the wait for a requested track to play (frozen at the first write that
sees playing; a stop ends it as 'stopped without playing'). `album_call` and the poll are out of line and compiled for
size (+424 B TEST irom). The record is debug save version 6's (board/pocket/README.md); `tools/dbgsave.py` prints it as
"music: track 11 requested 3.20 s before this write, playing = no", also for the previous session after a quit.
2026-10-17 (B Jam's decisions of 2026-10-16 on D31 and the SFX faults in his punk-TV captures; docs/ALLOWLIST.md,
row B12) put the cart chip's SFX laws
into `sfx.c` under `FW_S1` (the 0.2.6 builds compile as before): D1 and D3 levels are the cart chip's (from its
level table, built at boot, `sfx_level_init`; FF still writes 191), D1's flags bit 15 is the channel's loop byte and never reaches the RTL's pitch bits (flags[7]
there skipped one tick in 32: every looped SFX played at 31/32 speed), D3 (`sfx_loop`, 0.2.6's name) sets a target
level / pan and a step on the lowest channel of its mask and never loops or re-arms, D2 (`sfx_d2`, new; `sfx_stop`
stays 0.2.6's for D5's body) frees at once or fades by its step and frees, and `sfx_fade_tick` is the cart chip's
per-channel fade, run from the song-tick hook on the 9494 (`audio_s1.c`: the NTSC frame skip). A freed channel stops
feeding and its RTL volume goes to 0. Proofs: `tests/s1/audio_tests.c` A7-A10; against the cart program frame by frame
and the cart chip mixer's sample order (a tool outside this tree; measured 0 differences).
2026-10-19 (after B Jam's Block 888 cell alarm that never stopped; his rule: do what the cart chip does) the SFX of the
FW_S5 = 0 build moved out of this folder: those builds link `interim/s1/sfx_s1.c` (below) instead of `sfx.c`, and
`sfx.c` is back to final 0.2.6's text (the 0.2.6 builds as before). `sfx.h` keeps the declarations of the new entry
points.

# interim/s1 - the 0.2.6 command bodies under the cart chip's command map

The dispatcher (`core/dispatch`), which does what the cart chip's does, calls these bodies for every effect. They are
final 0.2.6's, moved from `legacy/026/paprium.c` one per cart chip command; `legacy/026/mame.c` (sprites) and
`interim/album` are used in place, behind `FW_S1` guards (`mame.c`: the old F5 copy is left out; the sprite blocks a
compose loads are listed for the flush, which the RTL decodes since MCU interface v1.2; TEST's SAT snapshot leaves L1,
below). Since 2026-10-27 the sprite bodies call the cart chip's sprite engine as `core/sprite` has it, on every form of
the sprite commands and on both mailboxes, C6 hands it the container `ppm_setup_data` unpacked, and `mame.c`'s sprite
engine is no longer linked into any new firmware image (it stays for the 0.2.6 milestone builds); TEST's SAT snapshot
stays, fed by the engine's TEST counters. Later, to make room, the FW_S5 TEST images no longer carry the snapshot (from
test build S3a on) (`appmain.h`); the FW_S5 = 0 TEST image keeps it for its test rigs.

- `appmain.h`: the new firmware's replacement of the 0.2.6 `main.h` (board.h + the 0.2.6 headers, no NEORV32 HAL,
  `printf` dropped). First on the new firmware's include path.
- `bodies_s1.c`: the bodies, the DA job's decode, the board half of the RTL decoder (the load list the flush pushes,
  the output base before each START), the job bodies, the C6 body after the cart chip's set-up writes.
- `vu_s1.c`: 0.2.6's Boom Box VU rows with their millisecond clock rebuilt from the board timer.
- (`f5_s1.c`, 0.2.6's float F5 rescale as a job, is gone: the zoom jobs are the cart chip's, `core/zoom`.)
- In the FW_S5 images (test build S3a on) the unpack jobs and C6's set-up decode through the cart chip's own decoders as
  ours has them (`bodies_s1.c` s5_unpack: the type byte picks 0x80 / 0x81, core/song's song_unpack80 / 81; the DA job
  then swaps each halfword as the cart chip's type-3 tail does, two halfwords per 32-bit SDRAM word (s5_rev16: the same
  bytes);
  F4 writes the cart chip's F4 source; C6's three containers are
  swapped into 0.2.6's workspace layout for their readers), so 0.2.6's decoder (`mame.c` ppm_unpack_scal, its 0x81
  case from Genesis Plus GX) is no longer linked there. The FW_S5 = 0 images keep it (no pointer view of the ROM bytes
  on their board interface; no hardware test build carries them now).
- `audio_s1.c`: the SFX feeder and the VU rows on the timer wheel (below), the empty song-tick hooks, TEST's
  ordered audio-call log.
- `sfx_s1.c` (since 2026-10-19; the SFX laws of 2026-10-17 moved here from `interim/album/sfx.c`): the cart chip's SFX
  channels behind 0.2.6's entry names (`sfx_play` = D1, `sfx_d2`, `sfx_loop` = D3, `sfx_stop` = D5's body,
  `sfx_fade_tick`): the cart chip's channel records (level, pan, targets, step, free flag, loop byte, the sound's id,
  position, length, start delay, retrigger), its channel choice (a free channel of the mask, else
  the quietest / furthest along, never one outside the mask), the SFX start's voices (the echo voice for flags 0x4000
  and the two-sided spread for 0x2000 in the cart-DAC mode, the 88 bit `sfx_mode88` gives; the retrigger, the start
  delay, 0x0100's rate step and trim), D5 touching no channel, and the mixer's bookkeeping worked out from a block
  count (`sfx_sync`: a 300 Hz grid on the board timer, `SFX_BLOCKS`; the harness replays the cart chip's own). A start
  that waits (a delay, the two voices of a spread, or a FIFO still holding samples: muted, drained at 48 kHz) is
  pending: the feeder's grid starts it (`sfx_pend_run`). Linked in the code window (`pocket72k.json` `wcode_text`; the
  cold parts compiled for size, the D1 and synth-tick paths at -O2; its one clock figure comes from `audio_s1.c`).
  Proofs: `tests/s1/audio_tests.c` A11-A18 (negative controls 6-8); against the cart program frame by frame on seven
  corpora (a tool outside this tree).
- `s1_interim.h`: the boot step and the two board hooks (volumes, SFX FIFO base) the album path still needs.

**0.2.6 behaviour is kept per byte.** The cart chip dispatches on the whole word, so the bit-14 twins (95/D5, 89/C9
...) reach the same fragment. 0.2.6 served only the byte it knew. Each body checks the posted word (`is026()`) and does
nothing for the other form until the cart chip's own body replaces it. Proof: `tests/equiv/s1_slice.py` (the new
firmware's host build vs final 0.2.6, solo frames 0-3,000, TEST and RELEASE, every post).

Retired with the new firmware: 0.2.6's busy rule and its `$1FE6` bit 8 / 9 / 14 writes (the cart chip's status layer
and the RTL own them), its own copies of the EC / B0 gates and the C6 engine rule (the cart chip's are in
`core/dispatch`).

## The decoder stand-in: the sprite decode out of L1 (2026-10-13; gone since MCU interface v1.2: the RTL decodes, below)

0.2.6 decoded every sprite block an AD loads inside the post (`mame.c` `ppm_vram_load_block`), so an AD held the
mailbox interrupt with interrupts off for up to 8.3-8.5 ms (measured in a co-simulation). On the cart the cart chip
never decodes sprite art: the AD compose lists the blocks, AF / B1 push their flash addresses to the FPGA, and the FPGA
decodes them while the 68000's DMA reads `$C000` (D43; `docs/CART_FPGA_SPEC.md` 9). This version did the same split:
- the compose stays in L1, where the cart chip runs it (its mailbox interrupt); it queues each block it loads instead
  of decoding it (`s1_block_decode`, one `FW_S1` guard in `mame.c`);
- the board decodes the queue outside L1, in request order, into the same scratch slots: in L2c from 2026-10-14
  (below, "The decoder below the brain call"); the first version ran it on the wheel (slot `WH_DEC`, L2a, below the
  SFX feeder and the VU rows);
- F2's two decodes go through the same queue, so they never overtake an earlier block;
- AF and F2 hand their GO and their finish to the decoder while it still has work (`disp_board_tail`); the game
  waits for those replies before its DMA reads the window (`$33072` after AF, `$B3D16` after F2), so it reads the same
  words as before. Nothing else the 68000 sees moves: the same register writes in the same order, the same window
  words, the same SDRAM (RV32 vs host per post and host vs final 0.2.6 per post, both PASS, also with 22 F2 posts
  inserted into the solo capture).
- TEST only: 0.2.6's SAT snapshot diagnostic (`PPM_SAT_SNAPSHOT`, a 640-byte copy into the save at `$900`) made TEST's
  AF ~0.45 ms at the hardware CPI in play; `ppm_obj_frame_end` now only flags it (a fourth `FW_S1` guard) and AF hands
  it to the decoder with its GO and finish (`DEC_SNAP`). It is taken after the sprite table's close, not just before
  it, so the end-mark entry and this frame's clobber count are in it; the 68000 never reads save `$900-$FFF`.
- **Not moved: the compose.** The game's post routine (`$B43A0`) waits only for the PREVIOUS post's finish, writes the
  word and returns; the caller then writes the object's own record (`attrs` +8, `posX` +$C) right after posting AD
  (`$1153C-$1154C`, verified in the game's code), so composing later would change what the compose reads. It is over the
  L1 budget for big objects (up to 1,161 us RELEASE / 1,303 us TEST in the RV32 model, about 1.4-1.6 ms at the hardware
  CPI) until the cart chip's sprite engine (core/sprite) replaces `mame.c`. The 84 never waits behind it: the game
  posts 84 on mailbox B through the same routine, after the previous post's finish.
- An earlier co-simulation's "D1 3.5 ms" and "B6 3.0 ms" were AD bodies: the co-simulation credits an L1 entry to its
  first post, and in both entries the 68000 posted AD00 2-3 us after the D1 / B6 finish, inside the same entry
  (measured in the co-simulation log). D1 alone is 213 us there; in the RV32 model D1 <= 183 us, B6 <= 40 us.

## The decoder below the brain call: L2c (2026-10-14; turned round on 2026-10-15, below)

On the wheel (L2a) the decoder ran above the CPU MATE brain call (L2b). A co-simulation (TEST + brain, 752 calls in
play, measured) showed what that costs: the SEND comes 389-460 us after the frame's AF post, while the frame's decode
(and TEST's SAT snapshot) still runs, so the call waited up to 8 ms for it, and a call already running was held each
time an AD queued more blocks (109 ms once, frame 3236); 422 of 752 words were armed after the original's release
instant, and from frame 3236 the game read before the ARM 8 times (9 calls with a stale read it could see). The
original has no such wait: the CPU MATE runs on the Mega CD's sub-CPU (all its interrupts off; a call starts within
one 98-cycle pass of its spin loop) and the cart's FPGA decodes the blocks beside the cart chip. So the board's
stand-ins now run at the lowest interrupt level, under the brain call ("L2c", core/sched `l2b_msi`):
- `l2b_msi` runs, in order: a pending brain call; the song tick's slices (the song engine's); then **one L2c
  request**: the decoder's next request (`l2c_run`), or else one wheel slot whose work has no deadline (TEST's debug
  save, `WH_L2C_SLOTS`: L2a only marks it due). A request runs with MSI open again, so a SEND (or a tick start) takes
  a fresh L2b on top of it at once; the nested L2b leaves L2c to the one below it, so requests are still served by
  one context, in order;
- a request runs with MTI masked: the wheel (the SFX feeder, the VU rows, the watchdog) runs between two requests, as
  it did when the decoder was a wheel slot (from 2026-10-15: with more requests queued, L2b leaves through the trap
  exit and raises MSI to come back, so a due wheel slot runs however short the window between two requests is;
  measured on the RV32 board model, where an interrupt is taken only at a step boundary: back-to-back requests in one
  L2b pass let a started SFX channel run dry, 3.9 ms without a push, in two runs). Letting a feeder tick preempt every
  request (the first version) starved the decoder in SFX-heavy frames: the feeder's fixed cost a tick is ~74 us of
  every 133.5 us in the model, and AF replies reached 16 ms (6.4 ms on the wheel); a nested L2b re-opens MTI, as
  every L2b runs with MEI and MTI;
- `dec_put` raises MSI when the queue goes from empty to busy (instead of arming the wheel slot);
- the jobs and the thread still wait for the decoder; AF and F2 still hand it their GO and finish, so the game reads
  the same words (and the test rigs check the window stream is complete when the frame's DMA reads it); a brain call
  can now come between a frame's blocks and AF's reply (one call a frame; its own run, 0.03-0.9 ms in the
  co-simulation);
- TEST counts L2c's decoder time as board work (the FPGA stand-in), like the thread's DA06 / DA07 decode.
Proof: `tests/equiv/fuzz_s1.py` FZ13 (decoder code never runs with interrupts open while a brain call is pending and
MSI masked; planted bug `test_bug_l2c` = L2c with MSI closed), `tests/s1/sched_tests.c` 7b (nesting, order, the wheel
between requests, the deferred slot), and a timed test rig on the RV32 board model (outside this tree: the game's
posts paced from a capture, one CPU MATE call a frame with a recorded call's inputs, sent at the co-simulation's
instant after AF, the reference brain on the same inputs; a model of the board, the brain's real code). Before ->
after, TEST, model time (CPI 6): `sw_05_fight` on the solo route: word ARMs late (tick >= D_WORD) 390 -> 261 of
2,479, the latest 5.65 -> 0.99 ms, the decoder's share of the waits 60% -> 1%; `mp3_01_fight_p3rand7` and
`arena3_fight_p3rand7` on the Arcade 3P route: late 694 -> 449 and 737 -> 520, the latest 16.8 -> 2.0 and 16.4 -> 3.8
ms, the game's reads that saw the old word or busy (open loop on the CART-TIMED run) 76 -> 2 and 121 -> 9; the
answers equal the reference brain's on every call; SFX underruns 0 -> 0; L1 and interrupts-off maxima unchanged or
lower. The cost: the frame's AF reply is later when a brain call lands in the decode (AE -> AF reply mean +1% RELEASE
/ +7% TEST solo, +13-17% Arcade 3P). What is left is almost all the SFX feeder's ticks preempting the call
(`docs/STAGE1_FW.md` 5); the next version held the feeder for the call (next section).

## The brain call holds the SFX feeder (2026-10-14; undone on 2026-10-15, below)

After L2c the brain call still ran with MTI open, so the interim SFX feeder's 133.5 us grid preempted it (in the
timed rig ~90% of what was left: the tick's fixed cost - trap, `l2a_mti`, `wheel_program`, `wh_feed` - is ~74 us of
every 133.5 us in the model). The sub-CPU runs a CPU MATE call with every interrupt off, so on the cart nothing
lengthens a call. Two ways were on the table:
- **the feeder grid at 534 us** (a measured option, `CLK_FEED_NS 534000u`). Not taken: the cart chip's own SFX mixer
  runs every 2,085 us (inferred) and renders 160-sample blocks (3.33 ms at 48 kHz) into the free half of a
  1,920-sample circular buffer (20 ms). 534 us is not the cart chip's period, and the 0.2.6 grid stays locked by `tests/check_clock.py`;
- **what the cart chip does:** the call does not wait for the mixer and the mixer has a deep buffer. Here core/sched
  held the feeder's wheel slot (`WH_BRAIN_HOLD` = `WH_FEED`) from the brain post (L1) to the call's end (L2b): the slot
  stayed armed with its deadline but was neither programmed nor run; at the release (after `brain_active` drops) a
  deadline passed meanwhile fired at once, and `wh_feed`'s catch-up (late by m periods, the same fill-to-full pass)
  refilled the 256-sample FIFOs, which hold 10.7 ms at 24 kHz, the fastest rate the SFX bank uses (index 0, 48 kHz,
  is used by no entry). The urgent song tick, the watchdog and the VU rows were not held. The hold started at the post
  because this NEORV32 takes a pending MTI before MSI (`neorv32_cpu_control.vhd` `trap_priority`: MEI, MTI, MSI).
Proof: `tests/s1/sched_tests.c` 7c (no feeder tick inside a call, the watchdog still inside it, the feeder at once
after it, a slot armed during the call waits too; planted bug `sched_tests_bug7`), `tests/equiv/fuzz_s1.py` FZ14
(`wh_feed` never starts with a brain call in flight; planted bug `test_bug_hold`), and the timed rig re-run on the new
images (outside this tree; the same corpora, captures and pacing). L2c -> L2c with the hold, model time (CPI 6): word
ARMs late 261 -> 9 (solo `sw_05_fight` TEST), 93 -> 2 (RELEASE), 350 -> 22 (`ex_17_bigfoe_fight` TEST: 22 is that
corpus's floor, the calls whose brain run alone is longer than the original's D_WORD), 449 -> 13 / 520 -> 10 (Arcade
3P `mp3_01` / `arena3`, TEST), 166 -> 6 (`mp3_1E`, RELEASE); the latest 0.99 / 0.85 / 2.73 / 1.98 / 3.75 / 1.82 ms ->
0.14 / 0.28 / 0.34 / 0.13 / 0.13 / 0.92 ms; the game's stale reads (open loop, model and x1.2 the hardware CPI) 0 in
every run (L2c alone left 2 + 4, 9 + 12 and 1 + 1 in the Arcade runs); the call's run p99 0.76-1.05 ms (L2c alone
1.6-4.1 ms); the answers equal the reference brain's; SFX underruns 0 (the rig's FIFO model); AE -> AF reply mean
between L2c's and the 534 us option (e.g. `arena3` 5,117 -> 4,689 us, before L2c 4,384). The hold beat the 534 us grid
on every lateness figure, with the 0.2.6 grid kept.

## The CPU MATE brain call takes the time that is left; AF's reply (2026-10-15; its decoder parts were on a side branch, not taken: see "The decoder in logic" below)

B Jam on test build 2 (the version above), in busy Solarium fights with CPU MATE: the game slowed down, sound
effects lagging with it. B Jam's decision of 2026-10-15: "we can't have the CPU buddy, which isn't used all the time,
slow everything else down. Ensure we implement cart accuracy over being right." The cause (measured in co-simulations):
the game has its own late-frame check (ROM `$33256`): right after AF's reply it reads the VDP line, and at line 176 or
later it skips that frame's phase work and arms its slow-down gate (`$FF99A4 = 25`). The cart chip replies to AF
within tens of microseconds; ours replied only after the frame's blocks were decoded, and in the version before a
brain call sat in front of that decode (the SEND comes ~0.4 ms after AF). Late passes, frames 2511-3199 / the fight
3200-3430: test build 1 23 / 56, test build 2 44 / 55, the cart model 0 / 1.

**What the game reads after AF's reply, before its VBlank DMA reads the window** (measured in the game's code):
`$9C3CC` writes AF; `$3307A` waits for `$1FEA` bit 15 (the reply); `$33256` reads the line and takes the late path
or the phase work; `$333E6` tests VBlank (the lag count `$FF995C`); `$FF5F00` (RAM copy of `$BC364`) waits for the
next VBlank start; `$33428` waits for `$1FEA` bit 15 again; `$FF5E00` (RAM copy of `$11100`) writes the DMA list from
RAMDP `$1400` (count `$1F16`, written by AF's compose in L1) to the VDP, which reads the window. Every caller of
`$FF5E00` has the same "VBlank, then `$1FEA` bit 15" pair. The game posts nothing on mailbox B between AF and that
flush (0 of 2,932 frames in a co-simulation; the GPGX captures' few posts after AF are menus and loads), so `$33428`
finds the bit clear: it is not a handshake for AF. Neither the GO nor the busy bit is read there
(`docs/CART_FPGA_SPEC.md` 9 / 10; the window serves at SPTR whatever `stream_valid` says). The cart chip's AF
(`0x080190B8`) runs its flush (`0x08018FFC`: queue clear, pushes, `$1FF2 = 0x8000`) first, then composes, then
replies: the cart's FPGA decodes behind the reply with no handshake at all (in time, or streaming as the DMA reads:
not known).
So **this version did not give AF's at-once reply**: with the decode in firmware it could only be made safe by a time
argument (the decode beating the next VBlank), and a late decode would put old tiles on screen with nothing to stop
it. AF kept the rule that is safe by construction: its finish comes when its blocks are decoded, at once when the
decoder has kept up with the ADs. F2 is different: its path waits for the next VBlank and only then for `$1FEA` bit 15
(`$B3CEC-$B3D16`), so its finish after the decode is a real handshake and its reply time is invisible while the decode
beats that VBlank (unchanged). AE has nothing deferred; D1 / D3's first batch stays in L1 (the cart chip's mixer
starts an SFX on its next 2,085 us block; the interim feeder has no deep buffer, and moving the batch out risks a
start-of-sound underrun behind a decoder request, for ~40 us of reply).

**B Jam's rule, as levels** (core/sched): the brain call is the thread's (`sched_thread_once`, `l3_brain`), with every
interrupt open: L1, the wheel (the SFX feeder is no longer held for a call), the decoder stand-in (L2b, one request a
pass, MTI masked per request, so the wheel runs between two) and the jobs and DA06 / DA07 board work (L2c inside L2b,
MSI open, a decoder request nesting above a job) all preempt it; TEST's diagnostics (the debug save, the SAT
snapshot) run in the thread below the call. TEST's SAT snapshot left AF's tail (the earlier versions took it before
AF's finish): AF's close asks for it, the thread takes it, a frame start (AE) that comes first drops it (TEST only: a
copy the thread is still making when the next frame's first posts change the table can be torn; the 68000 never reads
it).

**The decode itself (on a side branch, not merged):** with the brain call out of the way the late frames left were AF replies spent decoding, so that branch made the firmware decoder faster (the same bytes) and kept 192 decoded blocks in the workspace (a block memo; an allow-list row was proposed there). The next version took neither: the decode left the firmware (below, "The decoder in logic"). The table below is that branch's, kept for the record.

**Measured** (on the RV32 board model, with tools outside this tree: the 68000 played in each GPGX capture's own
master-clock timing, closed loop: each record at its offset from its VBlank plus the waits our firmware caused
earlier in the frame; the late check = AF reply 13.03 ms or more after the VBlank, a fit from an earlier analysis; the
cart model = the capture's AF write + 30 us; a model of the board on the priced clock: every instruction at the
NEORV32 cost measured for its class and memory region (the flat CPI 6 of the earlier rigs makes the decode ~1.2x too
fast and agrees in direction); the brain's real code; one CPU MATE call a frame at the co-simulation's delay after AF
with a recorded call's inputs, the reference brain on the same inputs). Test build 1 (the L2c version) /
test build 2 (the feeder hold) / this version; the cart model's count in brackets:

| corpus (frames) | image | late passes (cart model) | lag VBlanks | AF reply mean / max, us | CPU MATE calls with a stale game read | latest CPU MATE word, ms | SFX underruns |
|---|---|---|---|---|---|---|---|
| solo, `sw_05_fight` (0-3,000) | TEST | 12 / 15 / 2 (1) | 22 / 23 / 22 | 711 / 8,158 -> 217 / 6,187 | 3 / 0 / 4 | 7.5 / 0.0 / 66.2 | 0 / 0 / 0 |
| solo, `sw_05_fight` | RELEASE | 1 / 10 / 1 (1) | 21 / 21 / 21 | 279 / 7,999 -> 185 / 5,919 | 1 / 0 / 2 | 7.3 / 0.1 / 40.9 | 0 / 0 / 0 |
| solo, `ex_17_bigfoe_fight` | TEST | 12 / 17 / 2 (1) | 22 / 23 / 22 | 741 / 8,959 -> 217 / 6,173 | 4 / 0 / 3 | 8.2 / 0.4 / 63.9 | 0 / 0 / 0 |
| Arcade 3P, `mp3_01_fight_p3rand7` (0-2,900) | TEST | 102 / 123 / 37 (1) | 27 / 31 / 16 | 1,298 / 8,944 -> 422 / 6,987 | 80 / 0 / 96 | 8.5 / 0.2 / 66.8 | 0 / 0 / 0 |
| Arena, `arena3_fight_p3rand7` | TEST | 104 / 135 / 41 (1) | 30 / 39 / 18 | 1,358 / 8,913 -> 423 / 6,739 | 100 / 0 / 81 | 10.1 / 0.3 / 68.1 | 0 / 0 / 0 |
| Arcade 3P, `mp3_1E_fight_p3walkL` | RELEASE | 65 / 78 / 28 (1) | 14 / 15 / 13 | 697 / 8,621 -> 334 / 5,935 | 64 / 0 / 27 | 6.7 / 0.1 / 27.3 | 0 / 0 / 0 |
| duo (0-4,000; no CPU MATE) | TEST | - / 215 / 101 (12) | - / 117 / 86 | 751 / 7,977 -> 289 / 6,147 | - / - / - | - / - / - | - / 2 / 0 |
| attract (7,000-9,000; no CPU MATE) | TEST | - / 300 / 226 (21) | - / 130 / 117 | 1,654 / 69,491 -> 1,159 / 83,883 | - / - / - | - / - / - | - / 2 / 0 |
| stage 04 (0-3,000; no CPU MATE) | TEST | - / 5 / 2 (1) | - / 72 / 71 | 506 / 7,977 -> 228 / 6,147 | - / - / - | - / - / - | - / 0 / 0 |

In every run: 0 VDP DMA reads of a block not yet decoded and 0 window words changed after the DMA read them (4,454
checked streams in test build 2's and this version's runs, 2,547 in test build 1's); the 68000's wait at
`$33428` 0 (AF's finish is the last thing it waits for); the longest L1 body and interrupts-off section unchanged
(1.27-1.33 ms TEST, 1.10-1.16 ms RELEASE: the AF compose). SFX underruns: none with this version (test build 2: 2
in duo, 2 in attract). CPU MATE: its answers equal the reference brain's (0 diffs), but they come late again, as B
Jam's rule accepts: the call waits behind the decoder, the SFX feeder and the stage loads' DA decodes (the 40-68 ms
words are at stage loads, 1-2 calls a run; otherwise at most 9 ms; sends that found the buddy still busy, so the game
skipped them: 0 -> 2-8 a run).

Two lessons from the test rig: the board model takes an interrupt only between its steps, so the few instructions L2b
first left between two decoder requests let a burst of requests starve the SFX feeder (a started channel ran dry
after its first batch, 3.9 ms without a push, twice); L2b now leaves through the trap exit between two requests
(above). And the rig's idle fast-forward turned time into instructions at the flat CPI on the priced clock, so the
68000 started frames up to ~1.2 ms late; the numbers above are from the corrected rig.

**What is left:** the solo route and stage 04 are at the cart model but for one frame each (135-146 us past the
check). The Arcade 3P / Arena stage start, duo and attract still reply late: AF replies spent decoding first-time
blocks asked for late in the frame (63-70% of their excess reply time on the CPU MATE routes; the memo serves 41% of
the stage start's blocks) and running the SFX feeder between the requests (16-32% there, 55% in attract, whose
longest replies, 70-84 ms in test build 2 and here, are mostly the feeder's own passes; see the feeder section
below). They end 0.7-1.4 ms (median) past the check; a decode twice as fast again would remove about half of them
(estimated from those overshoots). The cart's count needs the decode off AF's reply: an at-once reply with a
handshake the cart chip does not have (B Jam's hardware test, his to-do item of 2026-10-15, decides what the cart
does there), or the decoder in logic (the 0.3.0 plan's decision 4).
## The decoder in logic: AF replies at once (2026-10-15, MCU interface v1.2, then PROPOSED)

B Jam's decision of 2026-10-15: "We are going for preservation here": the cart chip replies to AF at once, the cart's
FPGA decodes the sprite blocks itself, the game's line-176 check almost never fires, and the sprites are always ready
before the game's VBlank DMA reads the window; no timing bets, no busy-guard waits. The version before showed a
firmware decoder cannot give that (an early reply is safe only by a time argument). So the decoder and its queue go
into our RTL (`paprium_hwdec`), as the 0.3.0 plan's decision 4 had it for stage 5 (the song engine), and the firmware
does exactly what the cart chip does on its side:
- **The flush pushes the load list** (`core/dispatch` `flush_regs`, cart chip `0x08018FFC`): queue clear, `$1FE4` bit
  8 off, the frame's blocks last to first (`$1FF4 = 0x200 | a >> 16`, `$1FF6 = a & 0xFFFE`), then `$1FF2 = 0x8000` and
  bit 8 on. The list is 0.2.6's engine's own (`mame.c` keeps `ppm_chip_load_addr[15]` beside the cart chip's count
  `ppm_chip_loads`: the same cap of 15 and the same clears at AE, B0, B1 and the AF close), so the pushes equal the
  cart chip's write for write (the lockstep test against the cart chip compares them now: 3,179 AF and 159 B1 posts
  of the solo route, 0 differences). F2 pushes its block twice; DA06 / DA07 with a 0x80 source push the stream once.
- **One board write before each START:** the decoder's output base (`brd_dec_base`, FPGAIO slot 17): 0.2.6's block
  scratch (`PPM_SCRATCH_BASE`) for AF / B1 / F2, the DA's destination for DA06 / DA07. The RTL loads SPTR with it,
  decodes the entries contiguously from there (the k-th block at base + 0x200 x k, as 0.2.6's `ppm_block_unpack_addr`)
  and GOes when the last word is written, so the window serves the bytes 0.2.6 served, from the same workspace bytes
  (the new firmware's host build vs final 0.2.6: equal at every flush, row B38).
- **Every one of these posts finishes at once,** in its own L1 (the cart chip's order: flush, compose, finish). Gone:
  the decoder stand-in (its queue, the deferred AF / F2 finish `disp_board_tail`, L2b's decoder level), the DA06 /
  DA07 board work, the firmware decoder queue in `board/pocket/s1_freg.c`, and AF's window pointer write at the frame
  end. 0.2.6's `ppm_unpack` stays for the cart chip's own decodes (DA02 and the 0x81 / 0x82 DA07 jobs, C6, F4).
- **AF's frame end without the slot-age pass** (`mame.c`, `FW_S1` with `PPM_CHIP_CACHE_LISTS`): 0.2.6 aged its 64
  slots at every AF for its own victim search; with the cart chip's cache lists (D02) nothing reads a slot's age, so the
  new firmware leaves the pass out of AF's reply (measured in the RV32 model, TEST, priced: AF reply 134 -> 72 us mean,
  the pass was 62-66 us of it). The result of every compose is unchanged (the replays below).
- The levels are those of the version before (B Jam's rule: the CPU MATE brain call in the thread, below the game's
  work); L2c runs the jobs only. TEST's SAT snapshot stays in the thread. The TEST debug save (version 4) keeps the
  decoder's FPGAIO read-backs (slots 18-22: LATECNT, the smallest GO -> first-read margin, the flags) for the hardware
  soak test; version 5 carries them into the next boot's record (`prev2`), because the Pocket's quit restarts the core
  first.

**The test rigs** model the RTL decoder in the board (`tests/equiv/rtlmodel.py`, from the decoder's specification:
the cart chip's 0x80 algorithm, measured byte-identical to the specification's reference on all 12,326 ROM blocks of
both ROM files; one port-2 access per ROM word read and per workspace word written at 140 ns, the specification's
worst outside a VBlank DMA; a block in the workspace when complete; GO at the last). `fuzz_s1.py` DEC and the timed rig
(outside this tree) read each block by the game's own VBlank DMA no earlier than the specification's lower bounds (the
reply + 106 us, then 175 us a block; in the timed rig, at the capture's own flush DMA) and count a word read before its
block is complete as LATE.

RESULTS (2026-10-16, estimated: the RV32 board model on the priced clock, the 68000 in each capture's own timing, the
RTL decoder at 140 ns an access; images = this version's TEST / RELEASE with the s1 brain (fwbuild.json "s1"."brain")).
"Faster decoder" = the side branch's faster firmware decoder and block memo; the cart model = the capture's AF write +
30 us (the cart chip replies at once; every other post answered in no time). The window starts at the first CPU MATE
call on the CPU MATE corpora (frame 280).

| corpus | image | late passes: test build 2 / faster decoder / this (cart model) | lag VBlanks test build 2 / this | AF reply mean / max us | RTL decoder: runs, window blocks read, words read early, aborts | smallest GO -> first window read, us | SFX underruns | CPU MATE calls with a stale read, 2nd build / this (answer diffs) |
|---|---|---|---|---|---|---|---|---|
| solo, sw_05_fight (CPU MATE) | TEST | 15 / 2 / **1** (1) | 23 / 10 | 72.6 / 156.7 | 190, 529, 0, 0 | 4,377 | 0 | 0 / 2 (0) |
| solo, sw_05_fight (CPU MATE) | RELEASE | 10 / 1 / **1** (1) | 21 / 10 | 50.2 / 132.4 | 190, 529, 0, 0 | 4,460 | 0 | 0 / 2 (0) |
| solo, ex_17_bigfoe_fight (CPU MATE) | TEST | 17 / 2 / **1** (1) | 23 / 10 | 72.6 / 155.2 | 190, 529, 0, 0 | 4,349 | 0 | 0 / 2 (0) |
| solo, frames 0-3,600 | TEST | - / - / **13** (5) | - / 64 | 73.8 / 189.5 | 431, 1,304, 0, 0 | 2,292 | 0 | - |
| solo, frames 0-3,600 | RELEASE | - / - / **12** (5) | - / 64 | 51.3 / 112.8 | 431, 1,304, 0, 0 | 2,534 | 0 | - |
| Arcade 3P, mp3_01_fight_p3rand7 (CPU MATE) | TEST | 123 / 37 / **2** (1) | 31 / 4 | 78.2 / 199.3 | 669, 1,920, 0, 0 | 3,235 | 0 | 0 / 1 (0) |
| Arena, arena3_fight_p3rand7 (CPU MATE, Arcade 3P capture) | TEST | 135 / 41 / **2** (1) | 39 / 5 | 78.2 / 237.3 | 669, 1,920, 0, 0 | 3,179 | 0 | 0 / 8 (0) |
| Arcade 3P, mp3_1E_fight_p3walkL (CPU MATE) | RELEASE | 78 / 28 / **2** (1) | 15 / 4 | 54.8 / 175.5 | 669, 1,920, 0, 0 | 3,268 | 0 | 0 / 1 (0) |
| Arcade 3P, frames 0-2,900 | TEST | - / - / **2** (1) | - / 57 | 78.4 / 205.2 | 669, 1,920, 0, 0 | 3,212 | 0 | - |
| duo, frames 0-4,000 | TEST | 215 / 101 / **30** (12) | 117 / 65 | 75.9 / 196.9 | 632, 1,985, 0, 0 | 1,406 | 0 | - |
| duo, frames 0-4,000 | RELEASE | - / - / **28** (12) | - / 63 | 52.3 / 137.9 | 632, 1,985, 0, 0 | 464 | 0 | - |
| attract, frames 7,000-9,000 | TEST | 300 / 226 / **62** (21) | 130 / 28 | 79.6 / 204.5 | 1,142, 3,835, 0, 0 | 906 | 0 | - |
| stage 04, frames 0-3,000 | TEST | 5 / 2 / **1** (1) | 72 / 60 | 73.3 / 189.5 | 164, 484, 0, 0 | 6,844 | 0 | - |

What this shows:
- **The decoder half is the cart's.** On every corpus: no window word read before its block was decoded, no decoder
  run aborted, every block of a frame decoded before the game's first window read of that frame (the smallest
  margin 0.46 ms, duo RELEASE), no SFX underrun, no fuzz or model fault; AF replies in 50-80 us on average (the cart
  chip's handler order: flush, compose, finish). CPU MATE answers equal the reference on all five corpora.
- **What is left is not AF.** In every frame that is late here and not in the cart model, AF's own reply is 50-150
  us; the 68000 reaches AF 0.5-3.6 ms later than in the capture because of the posts BEFORE AF in that frame (8-15 AD
  composes, AE, D1, D6, EC: 0.2.6's sprite engine and the interim SFX start, which the cart answers in
  microseconds). Arcade 3P frame 2,195 (profiled post by post, with a tool outside this tree): 1,820 us of AD replies
  before AF, 930 us of it in 0.2.6's block lookups (`ppm_vram_load_block`, the pose pre-load); that frame was late in
  every variant before this one too.
  The cart's count on those corpora needs the sprite compose at the cart chip's speed: the cart chip's sprite engine,
  with the sparse block -> id index (`core/sprite`).
- The Arena capture is not usable in this rig: 0.2.6's close reads past RAMDP at frame 281 there, as in test build 2 and
  every run of the version before (it was there already); the Arena coverage is the `arena3` corpus.

## TEST's SAT snapshot, layout 2: the crowded frame and its true count (2026-10-17)

B Jam's second TEST save of 2026-10-17 from a hardware test held a frame with more than 80 sprite entries that could
only be inferred (entry 79 linked on to entry 80): 0.2.6's snapshot (save `$900-$FFF`, `legacy/026/mame.c`
`ppm_snapshot_sat`) stored the count capped at 80 and kept the LAST frame of 20 or more, which is whatever was on
screen at the quit. The game composes up to 128 or more entries a frame; the console's table holds 80. TEST only
(`PPM_SAT_SNAPSHOT`; the RELEASE images are byte-identical to the version before), `FW_S1` only (the 0.2.6 builds keep
layout 1):
- AF (`s1_sat_snapshot_later`, L1; after AF's reply since 2026-10-18) latches the count it closed and keeps the
  session's most and the number of frame ends over 80: a load, two compares and their stores, no loop (18
  instructions, was 3).
- The thread keeps two tables: the session's MOST CROWDED frame (the latest of equals) at `$918` with its true count
  (16 bits) beside the capped one at `$914`, its object record copy at `$B98`; and the LATEST frame of 20 or more
  (0.2.6's rule) at `$D18`, in the counter arena the rings leave free, its true count at `$908`. The session's most is
  at `$90A`, its frame ends over 80 at `$90C`, the tag `S2` at `$906`, the frame numbers in the dispatch block (`$F9C`
  latest, `$FA4` crowded) and 2 in the last byte (a layout-1 image's write clears it, so no reader takes one layout
  for the other). Both fit: the arena's 1,024 bytes are the object record copy's 384 and the latest table's 640.
- The copies run in the thread with every interrupt open (after the brain call); a frame start that comes after the
  thread took the request sets bit 15 of that table's true count (a torn copy: the next frame's table may be mixed
  in), one that comes before the thread takes it drops the request, as before (so the session's most can exceed the
  kept frame's count; the reader says so). The thread reads the frame-start count in the same interrupts-off section
  as its take (a review found that read later, inside `ppm_snapshot_sat`, a frame start between the take and that
  read gave a torn copy with no flag). How often either happens on hardware: not known (the model's 68000 runs its
  frames back to back, not at 60 Hz).
- The lines the console would show over 320 px and over 20 sprites are left to the reader (`tools/dbgsave.py`, the
  H40 rules of an earlier analysis on the stored table): the save holds the table, and the IROM placement has 12 B of
  plan slack.
- `tools/dbgsave.py` prints both frames in plain words ("crowded frame (frame end N): 86 sprite pieces (over the
  console's 80: 6 not in its table that frame); the console would show ... lines over 320 px and ... over 20
  sprites") and still reads layout 1 (0.2.6 TEST, and the new firmware before this): "more than 80 sprite pieces"
  when entry 79 links on to entry 80. On B Jam's two saves: 72 pieces, 30 lines over 320 px, 0 over 20 sprites; more
  than 80, 48 and 25 (that earlier analysis's numbers).
- Proof: `tests/equiv/q1_save.py` section H on RV32 (planted tables of 86, 83, 86, 40 and 10 entries closed by AF; a
  race replay for the torn flag). Measured: legacy debug aids 2,067 B TEST irom (+260), 237 B wram (+20); the
  re-hosted bodies 4,014 B (+60).
- 2026-10-18: AF's close became the cart chip's (`PPM_CHIP_AF_END`), and it runs before the thread's copy. A frame of
  more than 80 entries posted AF02 (the game's usual close) is then stored as the cart chip's multiplex: entries
  14..top-2 relinked to k - 13 (the console's slots 14-79 hold entries 28-93; its slots 0-13 hold entries 0-13 above
  line 48 and, through the game's H-int stash, 14-27 below it; the pieces past 94 take turns frame by frame).
  `tools/dbgsave.py` recognises it (every stored entry 14-79 linking to k - 13), prints "N sprite pieces (over the
  console's 80: the chip's AF02 multiplex: ...)", gives no line totals for it (entries 80-93 are not in the save; the
  stash's mid-screen rewrite is not modelled), and reads "more than 80" from it in a layout-1 save too. AF00 / AF01
  keep the links (the stored 80 are what the console gets), so their line totals stand. Section H checks both, plus
  the take race (planted: a frame start at the take path's first instruction and at `ppm_snapshot_sat`'s entry, the
  next frame's table under the copy: flagged; unflagged without the fix, measured on the RV32 model). Measured: the
  bodies 4,026 B (+12, ae0 read with the take), legacy debug aids 2,059 B (-8); TEST IROM free 428 B.
- Later on 2026-10-18: the snapshot's AF bookkeeping (the AF count, `s1_sat_snapshot_later`'s latch, its two compares
  and the request) runs after AF's reply; the count it latches is read before the reply. A timing check measured the
  bookkeeping in the reply: AF reply +1.53 to +1.66 us against the version of 2026-10-17 before the layout-2 snapshot
  (whose AF only set the request),
  which put duo 0.25 over that check's noise band. Now TEST's `f_af` (core/dispatch) makes the finish itself and then
  calls `body_af_replied`, still in AF's L1, so the thread finds the request and the counts as before. The count
  (`$1F18`) is read in `body_af`, before the reply, beside the close's own read, into `snap_af_read` (2 B; 5
  instructions, one RAMDP read), and `s1_sat_snapshot_later` latches it from there: after the reply the 68000 may
  write the next frame's count at once. As first committed the bookkeeping read `$1F18` after the reply too, on the
  argument that the game writes `$1F18` only after the next VBlank (measured in every capture: solo, duo, attract,
  Arcade 3P, stage 04, the first write after an AF post comes after a frame record; the Arena capture has none). That
  holds for the game's timing, not for the firmware: in an unpaced replay on the RV32 model (duo frames 0-19,000) the
  68000 wrote `$1F18` first in 2,022 of 18,425 closes, which latched the next frame's 14 or 0 and counted 106 frame
  ends over 80 instead of 114. With the read before the reply, the same replay latches, close by close, the count the
  cart chip's close read, and the session's most and the frame ends over 80 equal those of the version before (114,
  equal to the sprite values' check) (measured). RELEASE unchanged (no snapshot). Measured: the bodies 4,062 B TEST
  (+36: `body_af_replied`'s own is026 check and call; the read moved, 0 B) and 92 B wram (+2), the dispatcher 7,568 B
  TEST (+20), the sprite engine 4,172 B TEST (-20); the planted bug `test_bug_l1len` (the 640-B copy back in AF's L1)
  is planted in `body_af_replied` and still fails FZ12 (the L1 body is timed to its return, past the reply).

## The interim audio on the wheel

0.2.6's main loop pushed one SFX sample per playing channel per pass (its FIFOs stayed nearly full) and polled the VU
row; while a brain call ran, the CPU MATE glue fed the FIFOs from an MTIME grid instead. The new firmware has no main
loop:
- **SFX** (`audio_s1.c`): the glue's feeder on the wheel slot `WH_FEED` every `CLK_FEED` (133.5 us) while a channel
  plays, its per-sample code (`chan_batch`, = `sfx_player_update`'s); each tick and each start (D1, D3, right after the
  body in L1) pushes a channel until its FIFO reads full, at most 48. The glue's rate-aware k (a level-keeper for a
  call that starts with full FIFOs) is not enough as the only feeder: measured in the host FIFO model, k for the start
  and the grid gave 5 underruns in 4 x 120 s and a start followed by a long post ran dry; filling gives 0. The rate
  comes from `sfx_play` (`s1_sfx_type`), not the glue's SRAM hash (MegaWire RAM once the MegaWire code landed). One
  channel's batch is one interrupts-off section.
- **VU** (`vu_s1.c`): the row runs on `WH_VU` at the instant the 0.2.6 millisecond count reaches it; start (the 8C job)
  and stop (8D) can now come in the middle of a row, so start is one interrupts-off section, each voice of a row is
  one, and a generation count drops a row a start or stop cut.
- The host replay (`tests/s1/s1_ours.c`) keeps final 0.2.6's host behaviour: no feeder and no rows on the wheel
  (`s1_sfx_kick` / `s1_vu_kick` are no-ops there), as the 0.2.6 host replay runs neither.
- MENU_MUTE_EN = 1 is written by the board boot: the RTL pauses the album and zeroes the SFX pair while the Pocket menu
  is open; the feeder goes on filling the FIFOs.

Proofs (measured 2026-10-11): `tests/s1/audio_tests.c` (both clocks; FIFO model 256 deep at the six rates under random
L1 posts, one 17.3k-cycle post a frame, long jobs, VU rows): 82,417 starts, 42.5 M pushes, 0 underruns, 0 overflows;
every start followed at once by a 17.3k-cycle post: 0 underruns; 50 VU rows each at its due instant, 80.1 ms apart; a
stop inside a row leaves every bar at 0. Negative controls: the first batch only k, and the row not dropped, each fail.
On RV32 (a bench outside this tree): the TEST and RELEASE images after the game's C6 and 88, with D1 / D3 / D2 / 9494
posts and the CPU MATE call sequences running: 0 underruns, 0 overflows, every brain answer still equal to the
reference, 5,000-9,000 feeder ticks taken inside brain calls.

## The feeder's cost: the same pushes, cheaper (2026-10-15)

B Jam's decision of 2026-10-15, after test build 2: the CPU MATE, which is not used all the time, must not slow
everything else down; cart accuracy over being right. The largest steady load on the MCU is this feeder and the wheel
under it: in a co-simulation (TEST + brain, measured) L2a takes 42% of the MCU over the attract intro (59% in its
frames with SFX), 56% over the character select (67% at frames 1990-2010) and 56% in the CPU MATE fight at frames
3200-3430 (83% at most). Most of it is fixed work a 7,168-cycle tick: `wheel_program` three times a tick, `l2a_mti`'s
13 saved registers and slot scans, `wh_feed`'s pass over all eight channels and its `playing_mask()`. This version
makes the same pushes cheaper; what is pushed, to which FIFO, in which tick, does not change:
- **the wheel** (`core/sched/wheel.c`, core/sched/README.md "The wheel's own cost"): the compare is programmed once per
  L2a entry, in `l2a_mti`'s last look; the look walks the five slots unrolled and finds the next deadline in the same
  walk; `l2a_mti` saves 3 registers instead of 13;
- **the feeder** (`audio_s1.c`): one leaf, `feed_chans`, with the per-sample code inlined; the grid's pass looks only
  at `feed_playing`'s channels (a start's kick sets the bit in the same L1 as `sfx_play` / `sfx_loop`, the only
  writers of a nonzero size, so every channel with samples left is in it; it is exact again at each tick end) and
  reads it again after each channel it fed, so a channel an L1 starts above it in the middle of the pass is fed in
  that pass, as before; the full flag is read before the channel record is loaded (a FIFO still full from the last
  tick costs one read: the slow rates' common case); 4-bit and 8-bit samples have their own loops with one taken
  branch a sample; the tick end rebuilds `playing_mask()` over `feed_playing`'s bits only; TEST's push count is added
  once a pass, inside the tick end's section;
- **unchanged:** the per-sample code (the same flash byte, the same 4- / 8-bit conversion, the same pointer / size /
  step / loop bookkeeping), the status read (the same halfword) before every push, the 48-push cap, the channel order,
  one interrupts-off section per channel, the grid (133.5 us, `CLK_FEED`), the catch-up rule, the kick in L1 after
  D1 / D3, the VU top-up, the brain call's hold.

Proof that the sound does not change (measured):
- **host differential** (a tool outside this tree): the same driver built against the version before and against
  this tree, on the x86 fake board with the firmware's code taking no time (`hb.step` 0), so both see the same FIFO
  model (`audio_tests.c`'s: 256 deep, the six rates) at the same instants; every push logged with its time, channel
  and sample, every grid tick with its deadline. Byte-identical logs, TEST and RELEASE, on three capture corpora
  (every mailbox-B post of a GPGX capture at its paced instant, through the dispatcher's gates, with the ROM's own SFX
  bank: Arcade 3P 8,139 frames / 3.32 M pushes / 671,770 ticks; the solo route 72,422 frames / 8.48 M / 2.69 M; the
  duo route 59,553 frames / 7.34 M / 2.21 M) and on `audio_tests`' random load (all six rates, 4- and 8-bit, loops,
  stops, VU rows, a 17.3k-cycle post a frame) for 5 seeds, three of them 60 s with ~63,000 SFX starts and stops posted
  between two channels in the middle of a pass; 0 underruns, 0 overflows. Five planted differences (no refresh in the
  pass, 47 pushes a tick, a stale tick-end mask, a due test off by one, one full-flag read skipped) each make the logs
  differ.
- **RV32** (a tool outside this tree: the real images on `tests/equiv/rtlmodel.py`, the solo capture to frame 3,600,
  paced): the earlier image and this one push, play by play, the same channel, type byte and samples in 116 of 117
  plays; the 117th is the play still running when the run stops (its first 64 samples equal); the kicks' pushes
  5,616 = 5,616; 0 underruns, 0 overflows, TEST and RELEASE.
- **in the tree:** `tests/s1/audio_tests.c` A6 (every channel with samples left is in `feed_playing` at every board
  point with no section open; a start made in the middle of the pass, right after channel 2's batch, is fed in that
  pass above channel 2 (48 + 48 pushes) and only by its kick below it), planted bugs `audio_tests_bug4` (no refresh)
  and `audio_tests_bug5` (the kick leaves the channel out) caught; `sched_tests_bug8` caught; `run_all --s1-rigs`
  (FZ1-FZ14 with the SFX FIFO model on both images).

Cost (estimated: the RV32 model's instructions priced with our table of NEORV32 costs, measured on the RTL to
+-0.2%; the same model reproduces the co-simulation's measured 4,494 cycles a tick at frame 401 within 5%; L2a cycles
a feeder tick and L2a's share of the MCU in windows of the solo capture, paced; a tool outside this tree):

| scene (solo capture frames) | TEST before -> after, a tick | TEST share | RELEASE before -> after, a tick | RELEASE share |
|---|---|---|---|---|
| attract: logos and jingles (540-1080) | 4,698 -> 2,642 | 29.5 -> 16.7% | 3,934 -> 1,997 | 25.0 -> 12.7% |
| title (1710-1980) | 4,978 -> 2,900 | 35.8 -> 20.9% | 4,205 -> 2,228 | 30.8 -> 16.4% |
| character select (2250-2450) | 4,937 -> 3,046 | 23.2 -> 14.5% | 4,177 -> 2,382 | 20.4 -> 11.8% |
| Solarium fight, no CPU MATE (2790-3600) | 5,267 -> 3,148 | 22.6 -> 13.7% | 4,461 -> 2,489 | 20.2 -> 11.4% |
| the same fight with a CPU MATE call a frame (2790-3600; `sw_05_fight` inputs, 3,079 calls, the call holds the feeder) | 5,272 -> 3,162 | 21.8 -> 13.3% | - | - |

The capture's scenes keep the feeder armed 38-66 ticks a frame (the co-simulation's route: up to 125); scaled by the
same per-tick ratio (estimated), the co-simulation's measured TEST shares become about: attract 42 -> 24% (59 -> 33%
with SFX), character select 56 -> 35% (67 -> 41% at frames 1990-2010), the CPU MATE fight at frames 3200-3430 56 ->
34% (its worst frame 83 -> 50%). What is left a tick (TEST): the trap entry and exit, 546 cycles (16 registers and 3
CSRs saved and restored); the wheel's two looks ~500; `wh_feed` and its re-arm ~500; `l2a_mti` ~300; TEST's per-level
counters (`stats_enter` / `stats_leave`) ~400; the channel work ~370-740.
