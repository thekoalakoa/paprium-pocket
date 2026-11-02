# core/trace - event_post's fatal half and the MCU self-reset

`event_post` 0x08020B24 (its counting half is `core/dispatch/event.c`, `chip_trace`) is fatal when its third argument
is not 0: 85, the watchdog and the heartbeat (`core/wdog`) and the cart chip's other fatal paths. The cart chip is the
STM32 microcontroller on the real cartridge; the hex numbers are its addresses. The MCU is the processor this
firmware runs on.

- `fatal.c` - `fatal_halt`, 0x08020B56-0x08020C7C, with interrupts off for good: the LED code (pin low, 10 ms; for
  each of the code's bits 0-15 a clear bit waits 1 ms; 10 ms) and then the "WE SUX" poll: every 10 us (`CLK_FATAL_POLL`)
  the low byte of $1FEA as the 68000 last wrote it, one state per poll through the bytes 'W', 'E', ' ', 'S', 'U',
  'X' (any other byte goes back to state 0), and a 0 in the last state resets the MCU. The Pocket has no LED: its writes
  are left out, its waits kept, so the poll starts when the cart chip's does.
- `mcureset.c` - `mcu_reset` 0x0801FCC8 ($1FE4 := 0, then the reset; ours: `brd_full_reset`, the cart's MCU-only
  reset, docs/ALLOWLIST.md, row B17) and `chip_wait`, the cart chip's delay() on our board timer. Apart from `fatal.c`
  so the host replay (`tests/s1/s1_ours.c`, which ends a post where the cart chip halts) can link the watchdog.
- TEST: `fatal_rec` (code, arguments, time, polls) for the debug save (the TEST telemetry).

No game code sends the backdoor (docs/BOOT_SPEC.md, row AL-03); while the MCU is halted the 68000 runs on what it
has, as on the cart.

## Proofs (measured 2026-10-11)

- `tests/s1/wdog_tests.c`: the halt's timing (30 ms of LED waits for 0x400000FA, then 10 us per poll), the backdoor
  one byte per poll resets the MCU at the 7th poll, a broken sequence does not.
- **Lockstep with the cart chip** (a bench outside this tree): the cart chip's own event_post 0x08020B24 run in an
  emulator against ours (an 85 through the real dispatcher), one $1FEA byte per poll: 1,000 random sequences at each
  build clock (the exact backdoor, a byte held two polls or dropped, prefixes, noise, two in a row): 423 resets, 577
  none, 0 differences in whether and at which poll the reset comes.
