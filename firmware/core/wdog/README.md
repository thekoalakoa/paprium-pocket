# core/wdog - the cart chip's TIM7 tick: watchdog and heartbeat

The cart chip's TIM7 housekeeping (the cart chip is the STM32 microcontroller on the real cartridge), with the same
steps, written by our team from our own study of how the cart behaves: the interrupt 0x08015400 runs the watchdog
0x08020E50, then the heartbeat 0x08020DE8 (then the MegaWire task, core/mw). Ours is the timer-wheel slot `WH_WDOG`,
every `CLK_TIM7` (102.1 ms, a time: the same at both build clocks; the 48 MHz timer clock behind it is inferred). The
board boot starts it (`wdog_start`) after the acknowledges of `docs/MCU_INTERFACE.md` rule 6.3.1. G is the cart chip's
global block (`disp_g` in core/dispatch/disp.h); row numbers such as B7 are rows of `docs/ALLOWLIST.md`.

| count | written by | the tick | trips |
|---|---|---|---|
| G+0x190 (`wd_arm`) | app start 0, app init 1, 81 1, 84 / A858 0, 9494 2 if not 0 | +1 when above 1 | past 40: $1FEE := 0xAF5B, $1FE4 := 0x4200, event 0x400000FA (fatal); with 81 bit 4: $1FE4 := 0, 300 ms, MCU reset |
| G+0x192 (`wd_count`) | app start 0, app init 1, 9494 / 84 / A858 0 | +1 when above 1 | past 100 (as above); nothing raises it above 1: no effect |
| G+0x194 (`g194`, heartbeat) | app start 1 | +1 when above 1 | $1FE4 bit 11 set: fatal 0x400000FB; past 2,400: $1FE4 bit 13 cleared, count 0; no effect at 1 |

- **When it trips:** on the 39th tick after the last 9494 (the count goes 2 -> 41), 3.88-3.98 s. The game posts 81 at
  frame 169 and the first 9494 at frame 190; app init already leaves the count at 1, so the first 9494 starts it
  even without an 81 (as on the cart chip). 84 (the blank-save mini-game) and A858 switch it off for good.
- **Ours only:** while the Pocket menu is open the watchdog does not count (row B7: the 68000 is paused there);
  the heartbeat is not gated. TIM7 has one update flag: periods missed while L2a (the timer interrupt level) is held
  up merge into one tick.
- The fatal halt and the MCU reset are `core/trace`.

## Proofs (measured 2026-10-11)

- `tests/s1/wdog_tests.c` (run by every `tools/fwbuild.py s1`, and at the PAL clock by `tests/check_clock.py --images`):
  the watchdog checks (property FZ10 among them) on the fake board through the real dispatcher: no trip with 81 alone
  or app init's 1; 30 s of 9494s; the trip on the 39th tick (3.897 s after the last 9494 at NTSC) with the cart chip's
  register writes; the menu gate (10 s and 20 s open, the count goes on after it closes); 84 and A858 (30 s, and later
  9494s do not restart it); 81 bit 4 (the reset 300.06 ms after $1FE4 := 0); the heartbeat (no effect at 1; armed:
  bit 13 after 2,400 ticks; bit 11 fatal); 85; the TIM7 grid and the merge.
- **Lockstep with the cart chip** (a bench outside this tree): the cart chip's own 0x08020E50 and 0x08020DE8 run in an
  emulator against ours, event by event (9494, 81 with random flags, 84, A858, ticks with the menu open and closed,
  heartbeat arming, $1FE4 bit 11): 2 x 262,434 events at 53,693,175 and 53,203,424 Hz, 1,234 fatal halts and 138 MCU
  resets, 0 differences in the counts, the $1FE4 word and shadow, the register writes or the end. Three planted bugs
  (trip one tick early, heartbeat one tick early, menu gate removed) each caught.
