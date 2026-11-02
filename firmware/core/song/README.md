# core/song: the cart chip's song engine on the ordered engine queue

The music player of the cart program, written by our team: we reverse engineered the STM32F4's commands as close as
possible, with hardware verification. It holds the sequencer, the module commands, the voice back-ends, the PSG
envelope, the Z80 messages and the per-frame packet (with the $1880 YM-DAC stream copy), the masters and fades, SFX
control, the Boom Box feed, 88's configuration and the audio posts 9494 / 88 / C9 / CA / 8C / 8D / 8E / D0-D3 / D5 / D6.
The FW_S5 images link it (`tools/fwbuild.py s1`, variants `s5test` / `s5release`, layout pocket88k: the 88 KB IROM;
built with `-DFW_S5=1`, this directory at -Os): core/dispatch's audio fragments and the 9494 call `song_arrive`,
core/sched runs the queue (below). The interim audio code (audio_s1, sfx_s1, vu_s1, the album) is left out of those
images.

Words used on this page. The cart chip is the STM32 microcontroller on the real cartridge. The MCU is the processor
this firmware runs on (the NEORV32, a RISC-V soft CPU inside the FPGA); IROM is its code memory, WRAM its working RAM,
and CRAM the Pocket's cellular RAM, a RAM chip our core maps into the MCU's address space. RAMDP is the cart RAM that
both the 68000 and the MCU see. S, G and SFX are the cart chip's sequencer, global and SFX state blocks. L1, L2a, L2b
and L2c are the scheduler's levels (core/sched/README.md): L1 reads the posts, L2a is the timer interrupt, L2b runs
the engine items, L2c the jobs. The synth is our RTL sound engine; ARM, DONE, SEQLAT, STATUS, DIAG, SCHED and CONFIG
are its registers, and ARR is its count of the 68000's writes to the two mailboxes, the low half of its SEQ register
(`docs/MCU_INTERFACE.md` v1.3 sections 3.10.1 and 3.10.5). DT and YM-DAC are the game's two music modes.

| file | what |
|---|---|
| `song.h` | the engine's state in the cart chip's layouts (S, G, SFX, the SFX and BGM tables, the Z80 queue, the packet staging), the routines, the queue API |
| `song_board.h` | the board contract: memory views with their bus addresses, status / trace / packet / flush / random / mode / job hooks, synth_begin / synth_end, BLKCNT |
| `song_seq.c` | the sequencer, the module start, the module commands, the per-tick voice effects, the note functions |
| `song_voice.c` | the wave and PSG program and note back-ends, the PSG envelope, the pitch and gain helpers |
| `song_z80.c` | the Z80 message builders and the per-frame packet |
| `song_sfx.c` | the masters and fades, the SFX table init, SFX channel pick / start / stop / update, the Boom Box feed |
| `song_posts.c` | the audio posts split in two: `song_gate` (L1: gates, refusals, the parts the 68000 can see) and `song_body` (L2b); the 9494's two halves; the 8C job tail |
| `song_oeq.c` | the ordered engine queue and the L1 / L2 split: `song_l1_seen` / `song_arrive` / `song_l1_end` (L1), `song_run_one` (L2b and the urgent finish: one item, arrival order, synth_begin / end per item, DONE), `song_tick_due` (the urgent's deadline), `song_job_done` / `song_job_waiting` (L2c), the held posts, the lazy meter decay, the main-loop pass (the cart chip runs it on every main-loop iteration, so ours after every item and every mixed block) |
| `song_cfg.c` | the 88 configuration |
| `song_c6.c` | C6: the cart chip's audio init as the C6 job's parts, the 0x80 stream decoder, the BGM table entry; our 8C pre-decode, which unpacks every music module once, at C6, into the module store |
| `unpack81.c`, `unpack81.h` | our own decoder for the 0x81 streams (the format known publicly as LZO1X). Three entries: `song_unpack81` (the whole stream, no limit), `song_unpack81_to` (stops at an end address; the zoom start-up command F4 uses it) and `unpack81_checked` (every read and write limited, for input that may not be the game's). It writes the same bytes as the cart chip on every 0x81 stream the game has |
| `song_tables.c` | the state; the cart chip's two hand-typed tables (note pitch 108, FM fnum 13: tools/leak_allow.json) and the 12 bytes after the note table |

## The ordered queue

The cart chip serves every audio post and the 9494 in one interrupt context, each to its end, in arrival order. Ours:
L1 (`song_arrive`, at the arrival) does the cart chip's gates and refusals in the cart chip's order
(core/dispatch/disp.c's, with the gaps it leaves to the song engine filled: 8C's module range, null slot and header
check, D1's SFX count, 8E's range), copies the arguments and does the parts the 68000 can see (the 8C job push with
$1FE6 bits 14 / 8, the tick's bit 13); the dispatcher then finishes the post at once. The engine part is an item with
its arrival number; L2b (`song_run_one`, one item per look, MTI masked around it) runs the items in arrival order,
each between `board_synth_begin` and `board_synth_end(DONE)`. The 8C job's module start comes back as an item
(`song_job_done`), so it also runs in order, and the job leaves ($1FE6 bit 14) only after it. Every gate reads only
boot-time state or the job queue, so L1 decides exactly what the cart chip decides at the same arrival.

The queue's rules (code comments in song_oeq.c and core/sched/sched.c):
- **Arrival order** (B Jam's decision 3(a), `docs/ALLOWLIST.md` row B39; `docs/MCU_INTERFACE.md` v1.3 3.10.5, 6.1,
  rule 6.3.8): L1 serves the two mailboxes in arrival order (both pending: the older by SEQLAT first), so the queue,
  the held posts and the items are in arrival order: a block between two arrivals sees the older one's writes only.
  Planted: `SCHED_BUG` 13 (B first whatever came first).
- **DONE** (`docs/MCU_INTERFACE.md` v1.3 3.10.5) is not an item's own number: a post with no engine part takes no slot
  and only moves "served", so DONE := the oldest arrival still pending (queued with an arrival, or held back) minus 1,
  else the newest arrival L1 has served. A refused post's DONE goes out with the next DONE written (at the end of its
  L1 entry when nothing waits). Planted: `SONG_BUG` 9 (DONE := own number: left behind a refused post), 13 (no DONE at
  an item end: DONE left behind).
- **A full queue** (`SONG_Q_N` = 8 items: the game's own worst is 7 arrivals + the 8C's module-start item, measured in
  a census of the game's posts) holds the post back before its gates run (`SONG_ARR_HELD`): the dispatcher does not
  finish it, so the 68000 waits on that mailbox as on a busy cart chip; while one is held every new post is held too;
  the next item end takes them, oldest arrival first, and finishes them. Planted: `SONG_BUG` 11 (dropped instead).
- **The urgent finish**: a tick item still waiting `CLK_URGENT5` (1.8 ms) after its 9494 (STAMP_A) runs from L2a
  with interrupts off, with every item ahead of it, so the Z80 never reads a late packet even behind a brain call.
  Interrupts off, it holds L1 for as long as the queue ahead of the tick takes (the design says interrupts off;
  `docs/MCU_INTERFACE.md` v1.3 6.1 / 6.2 give L2a MEI open and L1 only short MIE-off sections): on the RV32 board
  model, at the probe's costs and CPI 6, L1 waits at most 3.3k cycles without bursts, up to 4.0 ms with 16 slots and
  up to 1.4 ms with 8 (the depth taken) under bursts of 4-24 back-to-back engine posts (estimated); the game's own
  post sequence replayed on the model never held a post or raised L1 past 3.1k cycles at either depth.
- **The module-start item is not atomic against the blocks** (it has no arrival, so the synth may start a block
  while it writes the new module's voices), as the cart chip's job tail is preemptible by its mixer.

What the logic owns (the synth contract): the wave voices' POS, LAST L/R, DECLICK and envelope state / level /
counter; the echo ring indexes; the SFX channels' PTR / POS / ID / filter state / DELAY; G's BLKCNT, frame pending,
YM filter states, halves and count. The FM / PSG meters of voices 0-9 are the firmware's, decayed lazily from BLKCNT
(`song_meters`) at each item's start.

## The board side

- The tick (`docs/MCU_INTERFACE.md` v1.3 3.10.1 / 3.10.5 / 21.3 items 4-5; `core/sched/s5_glue.c`): the frame_pending
  stores go to the synth's ARM register (`board_frame_arm`), since the logic owns the flag; the flush's YM-DAC underrun
  test reads the frame's block count from the synth's SCHED (`board_frame_cnt`); the $1880 stream reads the synth's
  dac_buf_L in CRAM (DACBUF_L 0x170000) and the packet goes to RAMDP $1800 by `board_packet_dma`, both views set at
  boot by `board_views_init` (sched_init).
- Counter 11: the cart chip's underrun count is also event_post's trace counter 11, which the main-loop pass copies to
  $1B00 word 11. Ours: `board_underrun` counts the YM half in the dispatcher's `trace_cnt[11]`; the synth counts the
  DT half in DIAG.INCOMPLETE and `board_trace_fold` adds the new ones to the same word before the pass copies the
  counters. Any DIAG write clears all four counts, so the clear is made only when STATUS shows that no instant can be
  serviced before it (`docs/MCU_INTERFACE.md` v1.3 3.10.5), or when INCOMPLETE has reached 0xF0 (forced).
- The module store: the SDRAM workspace from `BRD_MODSTORE_OFF` (0x0A0000, 598,016 B: a directory, magic `MSTR` written
  last, then the 52 modules as C6 decodes them); `board_module` reads its directory (weak: the host tests and
  harnesses hand their own).
- C6 (`song_c6.c`, called by core/dispatch/jobs.c's C6 job under FW_S5): the views (`board_c6_views`), both dac_buf
  rings cleared, then `song_c6_init` as an engine item, `song_c6_banks` (the wave bank itself is test build 4b's
  first-boot unpack, in board/pocket/boot: `board_bank_ok`), our pre-decode (`song_store_modules`, with our own 0x81
  decoder, unpack81.c), then `song_c6_ready` as an item. The game posts no audio before C6 is done (it waits on $1FE6
  bit 14), so the split changes nothing it can see (inferred).
- The 8C job (core/dispatch/jobs.c `job_8c_s5`) plays the stored module and holds the cart chip's job time first
  (`CLK_JOB8C` + `CLK_JOB8C_KB` a thousand decoded bytes, board/clock.h: the cart chip's instruction count is
  measured, its speed estimated), so the module starts on the tick it starts on the cart. `song_pass_hold` is set
  around every job (jobs.c): the main-loop pass returns at once while a job runs; the job's tail runs the pass next.
- CONFIG (core/sched/s5_glue.c `board_dac_mode`): every run of the 88 configuration writes MODE (DT 1 / YM 2), PAL and
  SEQ = the arrival of the item that runs it (the 88's, or C6's DONE), `docs/MCU_INTERFACE.md` v1.3 3.10.2.
- The synth's fields (`docs/MCU_INTERFACE.md` v1.3 3.10.1 / 3.10.3 / 3.10.4; `core/sched/s5_mirror.c`): the engine
  keeps the cart chip's records in WRAM. At synth_begin the logic-owned fields come back into the records (only when
  BLKCNT has moved since the last read); at every item's end, before its DONE (`board_synth_put`), every field the
  item changed goes to the synth.
- The main-loop pass (`song_main_pass`) runs where the cart chip's thread runs it: inside every item's bracket after
  its body (`board_item_pass`), after every block the synth mixes (`board_pass_bracket`, which reads a whole block or
  none), after an L1 entry that served a post and queued no item, and once after every job; never while a job is
  queued or running (`disp_s5_jobs`). The 81 flags pick the outputs (`disp_s5_pass`: bit 1 the counters to $1B00,
  bit 2 the Boom Box feed).
- The interim audio is out of the FW_S5 images (tests/check_images.py s1 checks it); the FW_S5 = 0 images keep it.

## How it is checked

We reverse engineered the STM32F4's commands as close as possible, with hardware verification. In this tree,
tests/s1/s5_tests.c (host), tests/equiv/fuzz_sched_s5.py (on the RV32 board model, FZ8 / FZ9) and race_s1 on s5test /
s5release cover the order, DONE, the held posts and the urgent finish; each planted bug above (`SONG_BUG` and
`SCHED_BUG` in song.h and core/sched) fails in at least one of them.

Still left out (by name): the 0x82 / 0x83 module streams (the game's 52 modules are all 0x81, measured); the
Boom Box feed words 56-63 (ours are 0); the note reads past the bytes kept after the note table (counted in
`song_note_far`); the D1 / D3 level index above 0x1FF (masked; never posted); the pass's preemption (on the cart a
mixed block can cut its pass between two voices' feed words; ours runs it between blocks, like the atomic blocks).

One known difference, which the game never meets: a tick posted on mailbox B in the very cycle of a 9494 makes two
tick items and two packet flushes in ours, where the cart flushes once. Only the Z80 message queue and the packet
differ (the engine state stays equal), until the queue's backlog drains (measured: from about 0.3 s to 6.9 s on the
tracks measured). The game never posts a tick on mailbox B (docs/CENSUS.md 1).
