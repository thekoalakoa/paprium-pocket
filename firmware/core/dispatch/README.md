# core/dispatch - the dispatcher, status layer and job queue, as the cart chip has them

The cart chip is the STM32 microcontroller on the real Paprium cartridge. This module is the cart chip's mailbox code,
written by our team from our own study of how the cart behaves (`docs/STAGE1_PLAN.md`, `docs/MCU_INTERFACE.md`
sections 3 and 6). It is board-independent: it sees the board through `board/board.h` only.

Words used on this page. The 68000 posts a command word to one of two mailboxes in RAMDP (the cart RAM that both the
68000 and the MCU see; the MCU is the processor this firmware runs on): mailbox B is `$1FEA`, mailbox A is `$1FEC`.
Commands are named by their hex bytes (81, C6, 9494, AF ...). L1 is the level-1 interrupt handler that reads a post
(core/sched). VS is the VDP's vertical sync, and VSCNT the counter of VS starts that MCU interface v1.1 added. Row
numbers such as B34 are rows of `docs/ALLOWLIST.md`, the list of our known differences from the cart chip. TEST is
the build with debug aids, RELEASE the one without.

The firmware was built in steps. The first one put this dispatcher in front of the 0.2.6 effect bodies, re-hosted under
the cart chip's command map (`interim/s1/`). Later steps replace those bodies with the cart chip's own, one subsystem at
a time, without touching this module (the sprite engine is in `core/sprite`, the MegaWire code in `core/mw`, scaling in
`core/zoom` and the song engine in `core/song`). The full firmware is the FW_S5 build (`board/board.h`; the s5test and
s5release images), which also builds the MegaWire code (FW_MW).

## What is in it

| file | cart chip routines | does |
|---|---|---|
| `disp.c` | mailbox entry and finish, dispatch B, dispatch A, both 55-entry handler tables, every handler fragment | the request bit, the table index (`(word & 0x3FFF) >> 8`, above 0x36 = default), the per-command gates and refusals, the finish (`$1FEA := 0` / `$1FEC := 0`, then `$1FE6` bit 15) |
| `status.c` | the status helper | the ONLY writer of `$1FE4` / `$1FE6`: shadow, mask, store, inside one critical section |
| `jobs.c` | the queue indexes, the job step and its byte jump table | 16 slots of 20 bytes, 15 usable; one job per pass; failure -> bit 8 when the slot asks; the job end advances the read index and rewrites bit 14 in one interrupts-off section |
| `event.c` | event post | the 16 trace counters; a nonzero third argument is fatal (`fatal_halt`, `core/trace/fatal.c`) |
| `disp_stubs.c` | - | weak defaults for the two hooks other modules define (`fatal_halt` in `core/trace`, `audio_tick_begin` the song tick) |
| `disp_bodies.h` | - | the body interface: what the dispatcher calls for each effect |

- **Refusals:** the cart chip's three forms are kept: set bit 10 (mailbox A) or 9 (B), post the event
  `code | r6 << 8`, finish. Codes: 5 queue full, 6 not ready, 7 bad arguments, 2 default.
- **The 9494 head** (watchdog feed, the mixer bail, bit 13 clear) runs inline in L1; the song tick behind it belongs
  to the song engine (`audio_tick_begin` returns 0 without it, so L1 finishes inline).
- **The full firmware (FW_S5; the s5test / s5release images).** The audio fragments (88, C9, CA, 8C, 8D, 8E,
  D0-D3, D5, D6) and the 9494 are one fragment, `f_song`: the 9494 keeps its head (the watchdog feed, its re-arm),
  then every one calls `song_arrive` (core/song: the cart chip's gates and refusals in the cart chip's order, the
  argument copy, the parts the 68000 can see, and the engine part queued as an item with the post's arrival number,
  which `disp_post_s5` takes from SEQLAT in L1). A post that the full engine queue holds back is left unfinished
  (`deferred`); `board_post_finish` finishes it when the queue takes it. The 8C job (`jobs.c` `job_8c_s5`) hands
  the module to the engine (`song_job_done`, the module from `board_module`: the store C6 fills) and waits for
  that item before the job end rewrites bit 14, as the cart chip's job tail starts the module before its
  end. The job first holds the cart chip's decode time (board/clock.h `CLK_JOB8C`, `CLK_JOB8C_KB`), and a
  track the store lacks gives the cart chip's failed-decode trace 0x11; C6's job runs the cart chip's audio set-up after
  the sprite / MegaWire stand-ins (`job_c6_s5`: core/song/song_c6.c, two engine items); every job sets
  `song_pass_hold` (no main-loop pass while a job runs, as in the cart chip's thread); the C6 gate reads the song
  engine's mixer flag and clears the sequencer's and the SFX engine's.
  D3 on mailbox A goes to `f_song` too, and song_gate refuses it (7, as the cart chip does).
  The FW_S5 = 0 images keep their own fragments byte for byte (their image files are unchanged by the full
  firmware's code).
- **C6 one-shot**, **81 / 82 / 84 / 85** do all that the cart chip's do: arguments check, the mixer flag, the C6
  long words, the `$1800` / `$1802` clear, the job 11 set-up; 84's delay and `$1FEE` word; 85's raw `$1FE4` store
  and trace.
- **The C6 hold** (row B34; `jobs.c` `c6_hold_target` / `c6_hold`): the cart's C6 job lasts the game's 80 VBlank
  polls, so the game keeps count byte 94, its random start (measured on B Jam's CDX power-ons). Ours sets up in
  ~45-55 frames, so job 11 waits after the set-up until the 79th VS start since the C600 post (VSCNT; the 80th when
  the game's first read, 672 MCLK after its C600 write, fell between a VBlank start and its VS start: checked in a
  tight loop to post + 38,244 cycles), then 120 lines
  more, and only then does the job step clear `$1FE6` bit 14, as the cart chip's does: the queue is not empty while
  the job runs (property FZ4 of `tests/s1/disp_tests.c`), and the C6 event's register writes are unchanged. A count
  that stops (a dead VDP) ends the wait 2 s after the post (`CLK_C6_HOLD_MAX`). TEST: `c6_hold_test` (the case, the
  end, the VS starts at the set-up's end). Proof: `tests/equiv/c6count.py`.
- **Whole-word dispatch** (the cart chip's own rule; not question Q2 of `docs/STAGE1_PLAN.md`, which is the RTL's
  handling of 68000 byte writes into cart RAM): the cart chip dispatches on `word & 0x3FFF`, so the bit-14 twins
  (95/D5, 89/C9, F0/B0 ...) reach the same fragment. 0.2.6 dispatched on the whole high byte. The re-hosted 0.2.6
  bodies read the posted word (`disp_g.cur_word`) and keep 0.2.6's per-byte behaviour until the cart chip's own
  body replaces them, so this first step changed no effect the game sees (proved by `tests/equiv/s1_slice.py`).
- **The sprite decoder's posts finish at once, as the cart chip's do** (MCU interface v1.2; B Jam's decision of
  2026-10-15: "preservation"). The cart chip never waits for its FPGA's decoder (no read of `$1FF0-$1FF6`, no
  decode-done interrupt): AF calls the load-list flush (`0x08018FFC`: queue clear, `$1FE4` bit 8 off, the frame's list
  pushed last to first through `$1FF4` / `$1FF6`, `$1FF2 = 0x8000`, bit 8 on) before its compose and its finish; B1
  flushes and finishes; F2 pushes its block twice and starts; DA06 / DA07 with a 0x80 source push the stream and start.
  `flush_regs()` now pushes the list (`body_load_list()`: 0.2.6's engine lists its loads where the cart chip's
  composer would, in the same order and with the same cap of 15, until the sprite engine in `core/sprite` took over),
  and the RTL decoder (`paprium_hwdec`) decodes them before the game's VBlank DMA reads the window. The only board
  part is one write before each START, the decoder's output base (`body_dec_scratch()` / `body_da_direct()` ->
  `brd_dec_base`: 0.2.6's layout). Earlier versions decoded in firmware and finished AF / F2 after the decode
  (`deferred`, `disp_board_tail()`, now gone): the game then took its late-frame path (`$33256`) far more often than
  the cart's at-once reply allows.
  AF's reply was made faster later: `flush_regs()` writes each entry's two queue registers in line (`push_entry()`'s
  call left out of the loop; the same writes in the same order), about 1.35 us less per listed load (estimated).
- **The sprite values the game reads as data** (B Jam's decision of 2026-10-15/16). Two pieces of the cart chip's
  sprite-engine state live here, beside the engine flag (H+$400): the open frame H+$401 and the multiplex parity
  H+$403. `f_af` has the cart chip's gate (`0x0801BCE6-0x0801BCEE`): an AF that no AE opened only finishes (no flush,
  no frame end, no register write but the finish); otherwise the flush, then the frame end with the post's mode
  (`lo & 3`) and the parity (`body_af(mode, parity)`: the cart chip's `0x080190B8`, in legacy/026/mame.c
  `PPM_CHIP_AF_END`), then H+$401 := 0. `af_parity` is a byte: 0 at the boot (.bss), +1 at every AE (`f_ae`,
  `0x08018FC2-0x08018FCA`), every accepted B0 / F0 (`f_b0`, `0x08019414-0x0801941C`) and the first C6's sprite init
  (the job step, `0x08019740-0x08019748`); its bit 0 picks the frames on which an 80+ table rotates its overflow in
  (`0x08019228`, `0x080192CA`). Measured by running the cart chip's program in our test runner: 0 after app init, 1
  after C6, 2 after the boot B0, +1 a frame. Host test: `disp_tests.c` (the gate, the mode and parity handed over,
  the three bumps); the planted bug `disp_tests_spr3` (B0 does not bump it) is caught.

## Which gates the first version had

From the first version on: every gate that reads dispatcher state: the arguments flag, argument ranges, the C6-done
flags (mixer, sequencer, SFX), the engine flag, the scaling session flag, queue full.
Left for the later steps, and marked in the fragment:
- sprites: the AD sprite index. The AF frame-open check is here (see above);
- MegaWire: the byte and send-flag gates, MegaWire init and job 6, the trace counters to RAMDP `$1B00`
  (81 bit 1). 83's frame-period windows and its refusal 7 are the cart chip's in the FW_S5 images since test build S3a
  (`disp_83_check`;
  `tests/equiv/f83lock.py` against the cart chip's 0x080209B4); the cart chip's HSI trim is left out (row B12);
- songs and SFX: 8C / 8E track range and null slots, D1's SFX id range, the main loop's bit 3, the song
  tick.

## Proofs (measured 2026-10-11, the gate sweep 2026-10-30)

- **Every gate against the cart chip, in the FW_S5 images (test build S3a, 2026-10-30)**: `tests/equiv/gatelock.py`
  posts every table index on both mailboxes x the argument flag x the low bytes that choose a gate, every argument edge
  and the forms the game never posts, before C6 and after it, into the image on the board model and into the cart chip's
  program in the test harness: the register words, events, counters, register writes, cart RAM, the zoom block and the
  save equal the cart chip's in every form (MegaWire's forms counted apart until an image runs the cart's MegaWire
  code).
  The cart chip's answers are written down as `docs/GATE_TABLES.md`, and every run is held to them. What the sweep
  found, and what was then made the same as the cart chip's: E0's job result (the cart chip's write job answers
  1 = written; its job step makes a 0 its code 9), DB03's copy (the workspace into cart RAM), F4's decode stopped at
  the end of the cart chip's zoom block (row B57).
- **Test runner comparison** (a bench outside this tree): the cart chip's program run on an ARM runner and our host
  build fed the same 81 posts (app init, C6, 88, 9494, 8C, 95/96, C9/CA, the sprite posts, DA02 / DA06 / DA07 direct
  and as a job, DB06 x2, F2, DF, E0, F4, F5, B6, 81, 82, 84, 85, 30+ refusal forms, the mailbox A forms): 81 of 81
  give the same register-write sequence after the documented transforms of the FW_S5 = 0 build.
- **Fuzz** (`tests/s1/disp_tests.c`, run by every `tools/fwbuild.py s1`): 8 seeds x 20,000 thread steps, the 68000
  posting from inside the fake board's points; about 13,000 B posts, 380 A posts, 4,700 jobs (400 failed on purpose)
  and 500 queue-full refusals per seed; 14,103,473 checks, 0 failed. Properties FZ1, FZ2, FZ3, FZ4, FZ6 and FZ7 (named
  in `tests/s1/disp_tests.c`) at every point.
- **Negative controls:** four planted bugs (`-DDISP_BUG=1..4`: bit 14 not stored before the finish, mailbox A's finish
  losing `$1FEC := 0`, bit 14 from the index before the advance, the status read-modify-write outside its critical
  section): each one fails the fuzz, or the build stops.
- **Replay** (`tests/equiv/s1_slice.py`; `tests/run_all.py --s1-replay`): the FW_S5 = 0 host build against the final
  0.2.6 host build on solo frames 0-3,000 (11,121 posts), TEST and RELEASE: no difference outside the allowed
  categories (`$1E4 = $FF00`, C6's `$1800` / `$1802`, the register page by design), and two planted differences
  caught.

## Size (measured, `tools/budget.json`)

6,872 B TEST / 6,960 B RELEASE of IROM (the MCU's code memory), 476 B of WRAM (its working RAM), against the plan's
3,236 B (estimated) dispatcher allocation. The cart chip's per-mailbox fragments are kept as separate fragments, as
the cart chip has them. `tools/budget.json` links this module to the plan row (`stage1_by`, printed in `budget.txt`, not
checked against a limit) and leaves the allocation to B Jam: `docs/BUDGET.md` section 7.

## Open

- `fatal_halt` and the watchdog tick: `core/trace` and `core/wdog`. The song tick behind 9494: the song engine. The
  debug save of the comparison log: the TEST telemetry.
- DA07 with a 0x81 source runs as a job whose stream GO is not known on the cart chip (the test runner has no SDRAM
  model for it); the FW_S5 = 0 body keeps 0.2.6's.
