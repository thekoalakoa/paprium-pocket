# Board interface v1.0: what the core sees of the board

Paprium 0.3.0, the first new-core firmware (written when the interface was frozen, 2026-10-11). `board/board.h` is the
**only** header the chip-exact core (`core/`) includes; `tests/check_tree.py` refuses any other board header, board
identifier or board address in `core/`. The board behind it is the Pocket cart MCU on MCU interface v1.0
(`docs/MCU_INTERFACE.md`, frozen) or the x86 fake board for host builds; a MiSTer board supplies the same file set
(docs/MCU_INTERFACE.md section 10).

**Marks.** "frozen, MCU_INTERFACE.md N" = frozen with MCU interface v1.0 in that section of docs/MCU_INTERFACE.md;
"host model" = the host model's rule (a model of the frozen text, not an RTL run). Version: `BRD_IFACE_MAJOR` changes
when a meaning changes, `BRD_IFACE_MINOR` when something is added. v1.2 now (2026-10-15, proposed with MCU interface
v1.2: `brd_dec_base`, the RTL sprite decoder's output base; v1.1 2026-10-13: `brd_vs_count`, the VS counter; nothing of
v1.0 changed).

## 1. Files

| file | what |
|---|---|
| `board/board.h` | the interface: constants, the board functions, the core functions the board calls |
| `board/clock.h` | `BRD_CLK_HZ` (from the build only), `BRD_CYC_NS` / `BRD_CYC_US`, the clock-following figures (section 6). docs/STAGE1_PLAN.md named it `board/pocket/clock.h`; it sits beside `board.h` because the figures are not the Pocket's (MiSTer uses the same file with its own clock) |
| `board/pocket/board_impl.h` | the Pocket's `static inline` definitions: one load or store to a v1.0 register, or one CSR instruction |
| `board/pocket/include/pocket_map.h` | MCU interface v1.0 as C constants (Appendix A verbatim + sections 2-5); board layer only |
| `board/host/board_impl.h`, `board/host/s1_board.c` | the x86 fake board ("hb"): the same functions over a model |
| `tests/check_board.py` | `pocket_map.h` == docs/MCU_INTERFACE.md (Appendix A and the tables), `board.h` == `pocket_map.h`, the clock values, no removed IO in the s1 sources (the new-core source set, built with FW_S1); `--rtl` adds the RTL (v1.1: slot 16, its reset, the VS synchroniser's SDC line); `--selftest` = 8 planted mistakes, each must fail |
| `tests/s1/board_tests.c` | host unit test of the fake board (58 checks with the v1.1 VS count), built and run by `tools/fwbuild.py s1` |
| `tests/s1/board_compile.c` | RV32IM compile check of every Pocket inline |

## 2. The interface

### 2.1 Constants (board.h; each equals a `pocket_map.h` value, `check_board.py` step 3)

| group | names | v1.0 meaning |
|---|---|---|
| causes | `BRD_CAUSE_B` 0x1, `_A` 0x2, `_S` 0x4, `_V` 0x8 | CAUSE bits: mailbox B (`$1FEA`), mailbox A (`$1FEC`), CPU MATE SEND, console reset (the Pocket's Console Reset menu action, added 2026-10-27; MiSTer's board) (frozen, MCU_INTERFACE.md 4.2) |
| lines | `BRD_LINE_MEI` bit 11, `_MTI` bit 7, `_MSI` bit 3 | the `mie` bits of L1, L2a, L2b (frozen, MCU_INTERFACE.md 2, 6.1) |
| register file | `BRD_FREG_FE4` 0x04 ... `BRD_FREG_FF6` 0x16 | chip offsets; stored: FE4, FE6, FEA, FEC; FE8, FEE, FF2 act on write; FF0, FF4, FF6 have no RTL storage (frozen, MCU_INTERFACE.md 3.4) |
| options | `BRD_OPT_MODEL_MASK` (bits 6, 8-10), `BRD_OPT_MW_MASK` (16-18), `BRD_OPT_MENU` (24), `_JAP` (25), `_PAL` (26) | the option word (frozen, MCU_INTERFACE.md 5) |
| sizes | cart RAM 8 KB (`BRD_CART_RAM_USER_END` = `$1FE0`), ROM 8 MB, workspace 2 MB, save 8 KB, GO 21 bits | (frozen, MCU_INTERFACE.md 3, 3.6 (question Q1 = 8 KB), 4.5) |

### 2.2 Board functions

| function | Pocket (v1.0) | rule |
|---|---|---|
| `brd_now()` | TIMER (slot 10) | cycles at `BRD_CLK_HZ`, wraps at 2^32 (80 s NTSC) |
| `brd_timer_arm(t)`, `brd_timer_disarm()` | TCMP := t, TCTRL := TEN; TCTRL := 0 | MTI level while `(now - t) >= 0` (signed); a past deadline fires at once; the level falls within 2 clocks of either write (frozen, MCU_INTERFACE.md 4.3) |
| `brd_until(t)` | `(int32_t)(t - brd_now())` | same on every board |
| `brd_cycles()` | `mcycle` | TEST per-level counters (no WFI in v1.0, so it never stops) |
| `brd_cause()`, `brd_cause_ack(bits)` | CAUSE read; W1C | ack before read (6.3.2); a set in the same clock wins |
| `brd_stamp_b()` | STAMP_B (slot 13) | TIMER when B was last set (MEI latency, the 84 deadline test) |
| `brd_msi(on)` | MSIP (slot 9) | L1 raises, L2b clears |
| `brd_irq_save()` / `brd_irq_restore(s)` / `brd_irq_enable()` | `csrrci mstatus, 8` / `csrs mstatus` / `csrsi mstatus, 8` | critical sections (rule 6.3.5) |
| `brd_lines_on/off/flush(lines)` | `csrs` / `csrc` / `csrc` + `csrs` on `mie` | flush after every ack (rule 6.3.3: NEORV32 1.4.8.1 re-latches a level) |
| `brd_freg_rd(off)`, `brd_freg_wr(off, v)` | 16-bit at 0x0B00_0000 + off | program order, nothing posted; the new-core accessor with its shadows and the chip-runner comparison's log belongs to the board layer (board/pocket/s1_freg.c, s1_freg.h; docs/STAGE1_PLAN.md item W6) |
| `brd_stream_ptr(off)`, `brd_stream_go(n)`, `brd_stream_state()` | SPTR (slot 2), GO (slot 7) | pointer first, then GO; GO before the status write that clears `$1FE6` bit 14 (fuzz case FZ3) |
| `brd_cart_ram()`, `brd_cart_ram_byte(a)` | RAMDP halfword view 0x0200_0000; byte view 0x0280_0000 | firmware stores stay below `$1FE0`; the byte view is read only |
| `brd_rom()`, `brd_rom_byte(a)` | flash word view 0x0400_0000; byte view 0x0480_0000 | the word view is the patchable image |
| `brd_workspace()`, `brd_save()` | SDRAM 0x0300_0000 (2 MB); battery save 0x0500_0000 (8 KB) | |
| `brd_options()`, `brd_menu_open()` | GPIO input | live; the game reads the options once |
| `brd_vs_count()` (v1.1) | VSCNT (slot 16), `BRD_VS_COUNT_MASK` 16 bits | the VDP's vertical syncs since the reset, wrapping; TEST telemetry only (the debug save extends it to 32 bits), never on a reply path; the host board returns `hb.vs` |
| `brd_dec_base(off)` (v1.2) | DEC_BASE (slot 17), `BRD_DEC_BASE_MASK` (even, 21 bits) | the RTL sprite decoder's output base (docs/MCU_INTERFACE.md section 4.9): written before each `$1FF2 = 0x8000` that has entries queued; the RTL then loads SPTR with it, decodes the queue there (last pushed first) and GOes by itself. Chip-runner log tag `S1_LOG_DECB`. The host board decodes at the START at once (below) |
| `brd_md_hold(h)`, `brd_menu_mute(on)`, `brd_opt_at_reset(on)` | CTRL bits 0, 4, 5 (read-modify-write of byte 0) | board boot only; bit 5 = the dormant latch, left 0 in the new core (question Q4) |
| `brd_full_reset()` | hold, mask, restart from the reset vector | the cart's MCU-only reset: the RTL state stays (docs/ALLOWLIST.md row B17) |
| `brd_milestone(code)` | TEST boot milestone | no effect in RELEASE (the TEST telemetry routes it to the debug save); the fatal halt's code (0x14) also writes the debug save at once, as interrupts stay off from there (docs/STAGE1_PLAN.md question Q1) |
| `board_get_handoff()` | a board constant | docs/BOOT_SPEC.md section 3: all zero in the first new-core firmware |

Why byte reads are functions, not pointers: the byte views swap bytes in RTL; a little-endian host cannot swap behind a
pointer, so `brd_cart_ram_byte(a)` / `brd_rom_byte(a)` keep core code identical on both boards.

### 2.3 Core functions the board calls

`l1_mei()` (L1, interrupts off throughout), `l2a_mti()` (MEI open), `l2b_msi()` (MEI and MTI open), `l3_thread()` (never
returns), `sched_exception(mcause, mepc, mtval)` (returns where to resume). The Pocket's trap entry and crt0 are
`board/pocket/s1_trap.S` and `s1_crt0.S`.

## 3. Rules the core obeys (docs/MCU_INTERFACE.md section 6.3, restated for board.h)

1. Boot: with the 68000 held, `brd_cause_ack(BRD_CAUSE_ALL)`, MSIP 0, timer off, then `brd_lines_on(BRD_LINES_ALL)`,
   then `brd_irq_enable()`; releasing the 68000 is the last step.
2. Ack before release: `brd_cause_ack(BRD_CAUSE_B)` before the finish write `brd_freg_wr(BRD_FREG_FEA, 0)`.
3. Flush after ack: `brd_lines_flush(line)` after acking a level, before re-opening it.
4. An MEI entry with `brd_cause() == 0` returns at once.
5. Timer-wheel edits are made with interrupts off.
6. Nothing on a reply path runs from SRAM, SDRAM or CRAM.
7. No WFI.

## 4. The host fake board

`board/host/s1_board.c` models what v1.0 and docs/CART_FPGA_SPEC.md show the firmware (host model):
- TIMER advances `hb.step` (8) cycles at every board call; `hb_68k_write(off, v)` is the 68000 side (`$1FEA` sets B,
  STAMP_B and, for a DA / DB / F2 command, the busy guard; `$1FEC` sets A); `hb_68k_read(off)` gives the 68000 view
  (`$1FE4` = busy << 2 | model bits, busy = guard | !stream_valid).
- The RTL effects of MCU writes: `$1FEA` clears the guard; `$1FE8` = 1 opens the window, 0 closes it and sets the mini
  view; `$1FEE` = the stop value does the same; `$1FF2` = 0 or bit 15 drops the stream and the guard; GO = N opens N
  words and clears the guard; `hb_stream_consume(n)` is the 68000 reading the window. Every register write is logged.
- v1.2: the RTL sprite decoder on the chip's writes (`$1FF4` latches, `$1FF6` odd clears / even pushes, `$1FF2 = 0x8000`
  with entries loads SPTR with `brd_dec_base`'s value, decodes the entries last pushed first with the chip's 0x80
  algorithm into the workspace, contiguous, and GOes), all at the START: the host has no time (the RV32 board model
  `tests/equiv/rtlmodel.py` times it). The firmware's DEC_BASE and the RTL's GO are logged as board tags (0x42, 0x43).
- Interrupts: at every board call a pending level whose `mie` bit is set is taken when MIE is 1, highest first, with the
  Pocket trap entry's masking and restore. There is no CPU latch and no preemption between two statements; the
  instruction-level behaviour (NEORV32's latch, any-instruction preemption) is the RV32 test rig's.

## 5. What is not in v1.0 of this interface

The register accessor's shadows and the chip-runner comparison's log, the boot sequence (steps P0-P8 of
docs/BOOT_SPEC.md), the FIFO-A target; the storage of the TEST counters; the sound-cache registers and the synth
registers (their own freezes). The decoder queue was the board accessor's until v1.2 moved it into the RTL. Additions
are minor versions.

## 6. The clock (test T23)

One value: `BRD_CLK_HZ`, passed by `tools/fwbuild.py` as `-DBRD_CLK_HZ=<clk_hz>u` from the layout's `"clk_hz"` in
`fwbuild.json` (the RTL's `CLK_HZ`: 53,693,175 Hz NTSC; 53,203,424 Hz in a PAL build). No source file holds a clock
literal. Figures (measured by `tests/check_clock.py`, both clocks):

| figure | time | NTSC cycles | PAL cycles | users |
|---|---|---|---|---|
| `CLK_MS_CYCLES` | 1 ms (truncated `CLK_HZ / 1000`, as the 0.2.6 ms counter) | 53,693 | 53,203 | CPU MATE (buddy) `BUDDY_MS_CYCLES` (s1 source set), board ms |
| `CLK_84_DELAY` | 100 us | 5,369 | 5,320 | 84 |
| `CLK_TIM7` | 102,103.75 us (inferred: 48 MHz timer clock) | 5,482,275 | 5,432,269 | watchdog / heartbeat tick |
| `CLK_FEED` | 133.5 us | 7,168 | 7,103 | CPU MATE (buddy) `BUDDY_FEED_PERIOD` (s1 source set), SFX feeder grid |
| `CLK_URGENT` | 737.5 us (estimated in the firmware's interrupt design) | 39,599 | 39,238 | urgent song-tick promotion (trap-entry plumbing built for the song engine; only the FW_S5 = 0 build's TEST probe arms it, and the FW_S5 firmware uses CLK_URGENT5, 1.8 ms) |

At NTSC every s1 value equals the 0.2.6 literal it replaces (`BUDDY_MS_CYCLES` 53693, `BUDDY_FEED_PERIOD` 7168),
so the clock work changes no NTSC number. CPU work (trap costs, feeder jitter, slice lengths) stays in cycles. The
0.2.6 source set keeps its literals (`buddy.h` changes only under `#if FW_S1`), so the milestone images are unchanged.
