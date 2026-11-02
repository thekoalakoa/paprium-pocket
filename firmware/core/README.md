# core/ - the firmware core: the parts that behave exactly as the cart chip does (board-independent)

The cart chip is the STM32 microcontroller on the real Paprium cartridge. This folder was empty at stage 0 (the
skeleton); modules come into it as they are written to do what the cart chip does: the dispatcher and its gate tables,
the status layer, the job queue, sprites, scaling, saves and the song engine. They are written by our team from our own
study of how the cart behaves.

`core/wavpack/` (added 2026-10-22, test build 4b): the WavPack library the cart chip uses (the BSD-licensed WavPack 4.0
"tiny decoder"; its licence is `LICENSE.txt` in that folder), and the cart chip's sound-bank unpack (`wvbank.c`). It
was edited from a version that we proved decodes bit-exact on rv32im: the encoder, stereo, float and sample-rate parts
are dropped (they have no effect on the cart's bank), its four tables are generated, and it is compiled with
-fsigned-char (the decoder's own rule), into the WRAM boot overlay only. `wvbank.c` is written by our team: we reverse
engineered the STM32F4's commands as close as possible, with hardware verification.

Rules (enforced by `tests/check_tree.py`):
- **No board addresses.** In code (comments may cite anything): no MCU region literals (the 0x01-0x07, 0x09 and 0x0A
  regions, WRAM 0x8000xxxx, NEORV32 IO 0xFFFFFFxx; 0x08xxxxxx is left to the identifier check because it is also the
  STM32 flash, and cart chip addresses are allowed here), no `ADDR_*`,
  `FPGAIO`, `POCKET_*`, `BUD_*`, `GPIO_INPUT`, `MTIME*`, and **`board.h` is the only board header** (every
  `#include` in core/ names `board.h`, a core header or a standard C header). The core reaches RAMDP (the cart RAM
  that both the 68000 and the MCU see), the ROM view, SDRAM, timers and interrupts through the board interface v1.0
  (`board/board.h`, `docs/BOARD_IFACE.md`), frozen with MCU interface v1.0 (`tests/check_board.py`). The MCU is the
  processor our firmware runs on: the NEORV32, a RISC-V soft CPU inside the FPGA.
- **Behave exactly as the cart chip does.** Every part names, in a comment, the cart chip address of the routine
  whose behaviour it has, except the audio parts (core/song, core/tables): of those we say only that we reverse
  engineered the STM32F4's commands as close as possible, with hardware verification.
  Every part whose effect the game or a player could see behaves as the cart chip's does; only the STM32 plumbing
  (drivers, C library, EEPROM driver, boot-time table builders) is replaced by our own.
- **Size and stack are budgeted** (`tools/budget.json` "plan", `tools/stack.json`): a new module adds a
  `modules` rule that claims its sections and a `measured_by` link to its plan entry, and stays within its allocation.
- **Constant tables are generated**: the tables were worked out from our own study of how the cart behaves and
  checked on hardware; they never hold bytes taken over from the cart chip.
- Every file builds for both boards: RV32IM (the Pocket) and x86 (the host build, the "ours" side of the test harness
  that compares the cart chip with our firmware).
