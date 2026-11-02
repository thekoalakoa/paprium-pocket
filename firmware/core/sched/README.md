# core/sched - the scheduler

The scheduler's four levels on MCU interface v1.0 (`docs/MCU_INTERFACE.md` section 6, `docs/STAGE1_PLAN.md`).
It is board-independent: it sees the board through `board/board.h` only. The Pocket's crt0 and trap entry are
`board/pocket/s1_crt0.S` and `board/pocket/s1_trap.S`; the host's are the fake board's model (`board/host/s1_board.c`).

Words used on this page. The MCU is the processor this firmware runs on (the NEORV32, a RISC-V soft CPU inside the
FPGA); its three interrupt lines are MEI (external), MTI (timer) and MSI (software), and MSIP is the software
interrupt's pending bit. CAUSE is the RTL register whose bits say why MEI was raised (V = console reset, B and A = the
two mailboxes, SEND = a CPU MATE post). The cart chip is the STM32 microcontroller on the real cartridge; EXTI is its
external-interrupt unit. The 68000 posts command words to mailbox B (RAMDP `$1FEA`) and mailbox A (RAMDP `$1FEC`);
RAMDP is the cart RAM that both the 68000 and the MCU see. CPU MATE is the computer-controlled partner; the thread
calls its brain. FW_S5 (`board/board.h`) builds the full firmware on MCU interface v1.3 (the s5test / s5release /
s5probe images); the FW_S5 = 0 build is the earlier firmware, still built and tested. TEST is the build with debug
aids, RELEASE the one without. The RV32 board model (`tests/equiv/rtlmodel.py`) is our model of the MCU and its
board, on which the tests in `tests/equiv` run the firmware images.

| level | entry | runs with | does |
|---|---|---|---|
| L1 | `l1_mei` (MEI) | interrupts off | per CAUSE bit, in the cart chip's EXTI order (V, B, A) then SEND: acknowledge, read the mailbox, hold the post (an engine post while the tick runs) or `disp_post` it; SEND -> brain pending (no interrupt: the call is the thread's); loops until CAUSE is 0, then flushes MEI |
| L2a | `l2a_mti` (MTI) | MEI open | the timer wheel: every due slot, lowest first, disarmed under MIE off, its callback with MEI open; the compare always holds the earliest armed deadline. A slot in `WH_LOW_SLOTS` (work with no deadline: TEST's debug save, `WH_TEST`) is only marked due here; its callback runs in the thread, below the brain call (an earlier version ran it in L2c). No slot is ever held for a brain call (an earlier version held the SFX feeder's) |
| L2b | `l2b_msi` (MSI) | MEI, MTI open | loop: clear MSIP, then one tick slice (MTI masked for the slice), the tick end after the last, else one L2c pass; returns when nothing is left. (There is no firmware decoder level: the cart FPGA's sprite decoder is RTL since MCU interface v1.2; earlier versions ran a stand-in on the wheel, in L2c, then in L2b) |
| L2c | inside `l2b_msi` | MEI, MTI and MSI open | one pass of the cart chip's main-loop work: one job of the cart chip's queue (`l3_job`), through `sched_l2c_once` (guarded by `l2c_active`, so a nested L2b, or a host harness's own drain, never runs a second pass on top of one). A tick start during a pass takes a fresh L2b on top of it at once. A queued job raises MSI (`sched_work_post`, from the dispatcher's job commit) |
| L3 | `l3_thread` | everything open | `sched_thread_once` in a loop: the CPU MATE brain call when one is pending (`l3_brain`, the buddy glue), else (with FW_MW, the MegaWire code) the SRAM image's check once after the 68000's release, the MegaWire task one of the cart chip's own steps a thread step (none starts while the game's sprite frame is open, AE to AF, for up to 33.4 ms after the thread first sees it open, or while a post waits in mailbox B: checked with the interrupts off and entered with them off; a step running when AE comes ends, the next waits for the AF or the 33.4 ms; a frame open longer, as the game keeps some, no longer holds the task) and the A858 screen's steps (never between two steps of the task), else TEST's diagnostics (`wheel_low_run`: the debug save; `l3_test_work`: the SAT snapshot), else the idle housekeeping (`l3_idle`) |

- **The tick** (the song engine's; in the FW_S5 = 0 build, the TEST probe's): `sched_tick_start(stamp)` (from the
  9494 handler) arms the urgent slot at `stamp + CLK_URGENT` and raises MSI. The tick end (`audio_tick_end`, then
  `disp_tick_tail`, then the held posts in arrival order) runs with interrupts off, from L2b after the last slice or
  from the urgent slot in L2a (when L2b cannot run: it is masked).
- **The CPU MATE brain call takes the time that is left** (B Jam's decision of 2026-10-15: "we can't have the CPU
  buddy, which isn't used all the time, slow everything else down"). The call is the thread's: L1, the wheel (the SFX
  feeder included) and the jobs all preempt it, and nothing is held for it; its abort lands
  through the trap exit of L1, L2a or L2b, whichever interrupted it. Earlier versions had it the other way round (the
  call in L2b above the decoder and the jobs, the feeder's slot held for it); on test build 2 a call sat between AF
  and the decode its reply waits for, and the game took its own late-frame path. Proofs: `tests/s1/sched_tests.c` 6a
  (a tick ends inside a long call), 7b (a job runs inside a call; a tick start nests L2b above a job),
  7c (the feeder and the watchdog run inside a call at their deadlines; planted bug `sched_tests_bug7` = the call
  masks MTI), `tests/equiv/fuzz_s1.py` FZ13 / FZ14 (planted bugs `test_bug_l2c` = the call masks MSI, `test_bug_hold`
  = the call masks MTI).
- **The pass looks again when a nested L2b left it alone** (2026-10-18; `l2c_missed`). A nested L2b clears
  MSIP before it looks; when it finds an L2c pass running (`l2c_active`) it leaves that pass alone, and the raise it
  cleared may be a job the pass has already looked past: l3_job has read the queue's indices (an L1 taken anywhere
  from the instruction after its `q_wr` load through its 'nothing queued' return) or is back in l2b_msi before its
  `l2c_active = 0` store. Before this fix the pass then returned 0 and L2b left: the job stayed queued with
  MSIP clear, and the 68000 spun on `$1FE6` bit 14 for good (a DA02 / C6 / save post) or on busy (a DA07 0x81 / 0x82
  GO). On the RV32 board model the full image froze on it twice in 26 runs (attract TEST at frame 4,425: an L2a
  preemption stretched the window to ~9,600 cycles and the game's next DA02 came inside it; Arena at frame 175); every
  FW_S5 = 0 image had it, including test build 3's, which we had tested on hardware (an audit lost 30 of 30 planted jobs
  in the window on four images). Now the nested L2b sets
  `l2c_missed`, and the pass, which clears it before it opens MSI and reads it after it has masked MSI again (so no
  nested L2b can set it unseen), loops on `ran || l2c_missed`. Proofs: the audit's exhaustive interleaving model on
  the built images (no lost wake-up and no drain failure with 2 or 3 jobs, a timer deadline, a plain post, two SENDs,
  the song engine's tick; the image without the fix loses the job at every window boundary); `tests/equiv/race_s1.py`
  (the job planted at every window boundary and the control on the RV32 board model, TEST and RELEASE: it runs at
  each; `--negative`: `test_bug_r1`, `SCHED_BUG` 9 = the fix left out, loses it); `tests/s1/sched_tests.c` 7d
  (planted bug `sched_tests_bug9`). Cost (measured in the built image's listing, main.dis): l2b_msi +8 B TEST / +20 B
  RELEASE, sched_init +4 B, 4 B wram; per L2b entry about 10 instructions more (GCC now keeps two constants in saved
  registers) and one less per pass that ran a job.
- **Held posts:** one slot per mailbox, kept in arrival order; an overflow (impossible under the 68000 protocol) is
  served at once and counted. A tick post (9494 / 94xx / D4xx, index 0x14) that comes while a tick runs is held too
  (`disp_holdable`), so the tick end finishes exactly one tick post and the held one starts the next tick (the audit
  had assumed a tick post was not held, which would leave one `tick_mbx` for two mailboxes; with the hold modelled,
  no finish is lost).
- **The wheel's own cost** (`wheel.c`): with an SFX channel playing the wheel runs every 133.5 us, so its fixed work
  is a steady share of the MCU (measured in a co-simulation of the RTL and the firmware: `wheel_program` and
  `l2a_mti` alone 20-28% of every
  frame with SFX). While `l2a_mti` runs (`w_in_l2a`), an arm or disarm only edits the slot: `l2a_mti` finds due slots
  by their deadlines, not by the compare, and MTI stays masked until its trap exit, so it programs the compare once,
  in the critical section of its last look (`l2a_look`), from the TIMER value it read there; an L1 nested in L2a edits
  the slots the same way (that last look sees its edit); every other level programs at once. `l2a_look` walks the
  five slots unrolled and finds the next deadline in the same walk; being a function of its own, it leaves `l2a_mti`
  3 saved registers instead of 13. Same deadlines, same callback order, the same compare when L2a returns.
  `tests/s1/sched_tests.c` 7 checks the compare after arms from outside L2a; planted bug `sched_tests_bug8`
  (`SCHED_BUG` 8: `w_in_l2a` left set) must fail it.
- **The full firmware (FW_S5; the s5test / s5release / s5probe images, MCU interface v1.3).** The tick slot, the
  held posts and the deferred finish are gone: the engine's ordered queue (core/song/song_oeq.c, `core/song/README.md`)
  takes them over. L1 reads SEQLAT (B in [15:0], A in [31:16]) and STAMP_A with each post, so every post carries its
  arrival number (`disp_post_s5`, `song_l1_seen`), and serves the two mailboxes in ARRIVAL order (both pending: the
  older by SEQLAT first; B Jam's decision 3(a), `docs/ALLOWLIST.md` row B39; `docs/MCU_INTERFACE.md` v1.3 sections
  3.10.5 / 6.1; ours does not keep
  the cart chip's EXTI line order B before A, because that order depends on when the cart chip's own entries make
  both pend); at the end of the
  entry `song_l1_end` writes DONE when nothing
  waits, else L1 raises MSI. L2b runs one engine item per look (`song_work` / `song_run_one`) with MTI masked around
  it, then re-arms the urgent slot, before the unchanged L2c pass (`l2c_active` / `l2c_missed` kept). The urgent slot
  (`s5_urgent_arm`, `wh_urgent`) is armed at the oldest waiting tick's STAMP_A + `CLK_URGENT5` (1.8 ms, board/clock.h)
  and runs items with interrupts off while a tick's deadline has passed. `s5_glue.c` is the board side of the
  engine's contract (synth_begin waits for STATUS.BUSY to drop; synth_end writes DONE; BLKCNT; the critical sections;
  the packet copy; weak `board_module` / `board_dac_mode` defaults). Planted (`SCHED_BUG`): 10 MTI open during
  an item, 11 L1 raises no MSI for its items, 12 the urgent finish does nothing, 13 L1 serves B before A whatever
  their arrival order. Proofs: `tests/s1/s5_tests.c`
  (host, 9 cases), `tests/equiv/fuzz_sched_s5.py` (FZ5 / FZ7 / FZ8 / FZ9 / FZ11 on the s5probe image under a v1.3
  model with TIM6 instants, NEED, BUSY and the 5 ms TIMEOUT), `tests/equiv/race_s1.py` on s5test / s5release (R1 at
  every window boundary; the images without the fix above lose the job), and the audit's interleaving model rerun on
  the FW_S5 images (its L1 is a Python stub, so L1's own arrival order rests on s5_tests and the test runs on the
  RV32 board model).
- **The synth's fields and the main-loop pass (FW_S5).** `s5_mirror.c` copies the engine's fields to and
  from region 0x06 (synth_begin reads the logic-owned ones back once BLKCNT has moved; every item ends with
  `board_synth_put`, the changed fields, before its DONE). The pass runs as the cart chip's thread runs it
  (core/song/README.md): in an item (`board_item_pass`), and from L2b in its own bracket (`board_pass_bracket`,
  MTI masked like an item) after a block (L1 acknowledges CAUSE.BLK: `blk_seen`), after an L1 entry that served a
  post and queued no item (`post_seen`), and at every job's tail (`sched_pass_post` from core/dispatch/jobs.c);
  none while a job is queued or running. The boot sets CTRL.BLKIE (board/pocket/s1_board.c). A bracketed pass has no
  arrival behind it, so a block can start while it reads (v1.3 section 3.10.5 holds blocks only behind an arrival not
  yet DONE): it reads the 16 ENV_LEVEL words, then STATUS again, and reads them all again if a block ran (so it sees
  a whole block or none; `s5_pass_stats.retry`). Planted (`SONG_BUG`): 33 no pass after a block, 36 none after a
  post with no item, 37 no second STATUS read (core/song/song.h lists 29-37).
- **Test build 5 (TEST): the synth's assertions.** `s5_glue.c` keeps `s5_test` (sched.h): the DONE stores with no
  hold-off before them (`board_done_free`, from core/song/song_oeq.c: L1's after a post with no item, one after an item
  with no arrival) and the DIAG.WBUSY they added (DIAG read just before and just after each store, interrupts off:
  `done_wbusy`), the DT starts (CONFIG with MODE = DT), the module starts + C6 items (the items with no arrival:
  SQ_JOB, the 8C's module start; SQ_CALL, C6's song_c6_init and song_c6_ready) and the DIAG.WBUSY their own stores
  added, the first CONFIG write's time. Planted: `SONG_BUG` 38, the free DONE store's WBUSY not counted; 39, every
  item's stores excused (tests/s1/s5_tests.c case 20). The debug save (version 9) turns them into assertions
  (board/pocket/dbgsave.h DBG_SY_*: A1 excuses the free DONE stores and the stores of the module starts + C6 items,
  which are counted apart as a diagnostic; a post's or a tick's store that meets a block fails it). RELEASE builds
  none of it.
- **Hooks** (`sched_hooks.h`): each names the module that defines it; `sched_stubs.c` gives weak defaults for the
  builds without that module, and `tools/stack_s1.json` stands a PROXY depth in for each default.
- **TEST counters:** `sched_stats` (the debug save, board/pocket/dbgsave.c, stores them); `SCHED_BUG` = the planted bugs
  of the negative controls on the RV32 board model (probe variants only).

Proofs (measured 2026-10-11; `tests/run_all.py` runs them):
- `tests/equiv/fuzz_sched.py`: the probe image under a model of v1.0 with the NEORV32 interrupt latch, interrupts and
  68000 actions at random instruction boundaries: FZ5, FZ7, FZ8, FZ9, FZ11; five planted bugs each caught.
- `tests/s1/sched_tests.c`: host scenarios (two held posts in one tick, both orders; a tick inside a long brain call
  and the urgent deadline with L2b masked (6a / 6b); the wheel's order and wrap; the jobs, a tick nested in a job and
  TEST's debug save around a brain call (7b); the wheel inside a brain call (7c); the empty MEI entry; exceptions).
- `tools/fwstack.py` with `tools/stack_s1.json`: the stack bound per level and nesting chain, which fails the build
  when it is over, in every Pocket build of the s1 source set (the FW_S5 images too): 2,132 of 5,120 B in the first
  skeleton (the real levels measured, stand-ins for the bodies not written then).
- GHDL nesting (a bench outside this tree): the probe image on the repo's NEORV32
  1.4.8.1 VHDL, unmodified, with the v1.0 generics and the three interrupt lines modelled: all three nestings occur
  (L1 inside a brain call 7 times, the urgent L2a tick end inside it once, L1 inside the promoted slices 3 times), no
  empty MEI entry (the flush rule holds on the real latch), every post dispatched in order and finished, the tick ended
  49,918 cycles after its start with a 150,000-cycle brain call running, stack 440 B. **Found there:**
  `neorv32_top_stdlogic.vhd` (1.4.8.1, as `mcu_core.sv` instantiates it) never assigns `mtime_irq_i_int` from its
  `mtime_irq_i` port (only `msw` and `mext`): with `IO_MTIME_USE = false` the timer interrupt never reaches the CPU
  (measured: line high for 146,000 cycles, 0 MTI taken; through `neorv32_top` directly, 139 taken). The RTL must add
  `mtime_irq_i_int <= std_ulogic(mtime_irq_i);` or instantiate `neorv32_top`.

## TEST counters: `stats.c`, `stats.h`

TEST images and host builds only (RELEASE and the probe compile the hooks to nothing; their arguments are not
evaluated). Per level (L1, L2a, L2b, the thread's board work and jobs; idle is the rest): runs, exclusive cycles (a
level nested in a run is subtracted) and the longest inclusive run; the boot milestones (the first board time of the
board's boot codes and of the first post, C6 posted / done, the first 9494, the fatal halt); the L1 latency of mailbox B
posts and 84's window-off time, both from the RTL's post stamp STAMP_B (checked on hardware too); the freeze telemetry
(the 9494 count and the last one's time, the last post; the MCU heartbeat is the watchdog's TIM7 tick count). The board
copies them into the battery save (`board/pocket/dbgsave.c`, decoded by `tools/dbgsave.py`). The new firmware
(every FW_S1 build) has no UART: `printf` is dropped at compile time (`interim/s1/appmain.h`).
Proof (measured 2026-10-11): on an RV32 test bench outside this tree (four seeds) the
.sav made from the image's save RAM decodes and its blocks equal the image's counters; L1 / L2a / L2b runs equal the
interrupts the bench made the CPU take, posts / 9494s / SENDs equal the 68000's, the milestones are in boot order, the
84 window-off time is 126-137 us (CPI 6, estimated). Host: `tests/s1/sched_tests.c` checks the per-level runs.
