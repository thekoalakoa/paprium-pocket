# paprium-fw

Our own cart firmware for Paprium on the Analogue Pocket (0.3.0).

The tree's first state (2026-10-10, stage 0 of the 0.3.0 work): the skeleton. The final 0.2.6 firmware is moved in
unchanged and builds byte-identical images; the same modules also link into the locked 0.3.0 memory layout. No 0.3.0
module is ported yet.

Terms used across the tree's notes: the 0.3.0 work went in stages. Stage 0 is this skeleton; stage 1 the new
scheduler, dispatcher, boot and watchdog, the s1 source set (`tools/fwbuild.py s1`, every file compiled with
`-DFW_S1=1`); stage 2 the sprite engine (`core/sprite`); stage 3 the unpackers, the zoom (F4 / F5), the saves and
MegaWire; stage 5 the song engine (`core/song`, the s5 variants, built with `-DFW_S5=1`). The cart MCU is the NEORV32
soft CPU in the core that runs this firmware; IROM is its code memory and WRAM its working RAM; RTL is the core's
hardware description.

## Rules for this tree

- **No game data.** The ROM and the cart program image are read in place, outside the tree. Constant tables are
  generated from formulas, never copied bytes. The CPU MATE brain (a reverse-engineered emulation of the game's CPU
  partner) is linked from an external directory (below). `tests/check_tree.py` scans for copied bytes and
  `tools/leakguard.py` for chip, ROM, sub-CPU or brain values typed in as numbers; its allow-list
  (`tools/leak_allow.json`) holds exactly the two hand-typed chip tables B Jam decided to type in (note pitches and FM
  fnum, for the song engine), nothing else. In a built image a zero byte beside them counts with them (B Jam's
  decision of 2026-10-30).
- **Chip offsets are allowed here.**
- **How numbers are known.** Notes and comments say in words whether a number was measured (read from a build, a run
  or a capture), estimated (calculated) or is not known (nobody has a number). Some tool reports print the labels
  MEASURED and MODELLED for the first two.
- **Commits:** plain messages, no attribution lines.

## Tree

| path | what |
|---|---|
| `core/` | board-independent, chip-exact modules. No board addresses; `board/board.h` is the only board header (`tests/check_tree.py`). `core/sched/` = the new scheduler (four levels, timer wheel, held posts, urgent tick; README there). |
| `legacy/026/` | the 0.2.6 command handlers and sprite engine, as-is (`mame.c/h`, `paprium.c/h`). Retired module by module. |
| `interim/album/` | the interim album / MD+ / SFX-feeder shim (`mdp`, `everdrive`, `sfx`). Goes with stage 5. |
| `buddy/` | the CPU MATE glue (`zz_buddy*.c`, `buddy.h`). The brain itself is external. |
| `board/board.h`, `board/clock.h` | the board interface v1.0 (`docs/BOARD_IFACE.md`): the only header `core/` includes; the one build-time clock value and the clock-following figures. |
| `board/pocket/` | the Pocket board layer: `main.c`, `appmain.h`, `cfg.h` (the 0.2.6 MMIO constants), `neorv32/` (HAL, crt0), `include/pocket_map.h` (MCU interface v1.0: Appendix A + the map, slot, bit and layout constants), `board_impl.h` (the interface's inline definitions), `s1_crt0.S` / `s1_trap.S` / `s1_board.c` / `s1_boot.h` (the s1 start-up, the one trap entry, the board boot), `link/` (layouts and linker scripts), `boot/` (boot/cache stubs). |
| `board/host/` | the x86 host board: the "ours" side of the audit harness (`ours_host.c`, shims; the audit harness is our comparison test harness, kept outside this tree) and the s1 fake board (`s1_board.c`, `board_impl.h`). |
| `tools/` | `fwbuild.py` (the build), `mkld.py` (linker script generator), `mkimage.py` (block-RAM images), `fwsize.py` (sizes and free space per region), `fwobjs.py` (bytes per object and tree area); the static checks `fwstack.py` + `stack.json` (stack bound per interrupt level and nesting chain), `fwbudget.py` + `budget.json` (size per module, 0.3.0 allocations and verdict), `fwelf.py` (ELF reader); `leakguard.py` + `leakguard.json` + `leak_allow.json` (the numeric-literal leak guard and its allow-list); `mkfafrium.py` (the firmware file, Little-Man Firmware, and the boot stub the bitstream carries for it: `docs/FAFRIUM.md`). |
| `tests/` | `run_all.py` and the checks it runs; `check_board.py` (the board interface == MCU interface v1.0; `--selftest` = its negative controls); `check_clock.py` (T23: no clock literal, every figure follows `BRD_CLK_HZ`); `s1/` (the s1 host tests, RV32 compile checks, the scheduler probe); `equiv/fuzz_sched.py` (the s1 scheduler on its RV32 image under random interrupts: the invariants FZ5/7/8/9/11 of `docs/STAGE1_PLAN.md` section 4.7, 5 planted-bug controls, crt0's interface checks); `expected/final026.json` (the shipped 0.2.6 md5s), `expected/pocket72k_026.json` (the milestone 2 pin); `check_stack_su.py` (fwstack == GCC `-fstack-usage`), `check_tools.py` (the checks fail when they must), `check_leakguard.py` (the leak guard catches planted chip values; its allow-list is exact; in a build only zero bytes may sit beside the two tables, B Jam's decision of 2026-10-30); `equiv/` (the replay tests, the allow-list of differences and the reference digests; `equiv/slice.py` = the short replay slice run_all checks on). |
| `docs/LAYOUT.md` | the memory layout, old and new, with measured sizes. |
| `docs/BUDGET.md` | the stack bound, today's sizes per module, the measured ratios, the 0.3.0 allocation and whether 72 KB holds. |
| `fwbuild.json` | the build manifest: sources in link order, flags, variants, layouts. |

## Build

Needs Python 3.12, the xPack RISC-V GCC 15.2.0-1 (the 0.2.6 toolchain; another GCC gives other bytes) and MSYS2
mingw64 gcc for the host build. Tell the build where they are, and where the brain is, in `paths.local.json` (not
tracked) or the environment:

```json
{
 "riscv_bin": "<the bin dir of xpack-riscv-none-elf-gcc-15.2.0-1>",
 "host_bin": "<the bin dir of MSYS2 mingw64, holding gcc>",
 "brain_dir": "<dir with the 0.2.6 brain.bin, cf.bin, rodata.bin>",
 "brain_dir_s1": "<dir with the brain the s1 images link, with the cycle-counter fix: fwbuild.json s1.brain>",
 "harness_dir": "<the audit harness dir, for tests/host_smoke.py>"
}
```

(`PAPRIUM_RISCV_BIN`, `PAPRIUM_HOST_BIN`, `PAPRIUM_BRAIN_DIR`, `PAPRIUM_BRAIN_DIR_S1`, `PAPRIUM_HARNESS_DIR` override it.) Two more blocks turn on
run_all steps that read game data in place: `"refs"` (`rom`, `cart_program`, `sub_program`: the leak guard)
and `"equiv"` (`capture_solo`, `rom`, optional `ref_host` {`test`, `release`}: the replay slice). Without them those
steps print SKIP. The brain files are
md5-checked before every build: the 0.2.6 source sets link the 0.2.6 brain (fwbuild.json "brain"), the s1 set its
own (fwbuild.json "s1"."brain": the 0.2.6 brain with a cycle-counter fix, brain.bin b9a76592).

```
python -I -B tools/fwbuild.py all                       # everything below
python -I -B tools/fwbuild.py pocket --layout legacy54k --variant test     # one Pocket image set
python -I -B tools/fwbuild.py host                      # build/host/{test,release}/ours_host.exe
python -I -B tools/fwbuild.py s1                        # the s1 set: build/s1/pocket72k/{test,release,probe,probe_bug1-5}, host tests
python -I -B tests/equiv/fuzz_sched.py [--negative|--boot-checks]   # the s1 scheduler fuzz on RV32 (~10 s)
python -I -B tests/check_board.py [--rtl <RTL tree>]    # board interface v1.0 == docs/MCU_INTERFACE.md (+ the RTL)
python -I -B tests/check_clock.py                       # T23: the one clock (fwbuild.json clk_hz) and its figures, both clocks
python -I -B tests/run_all.py                           # build + every check (~3 min: incl. leak guard + replay slice)
python -I -B tools/leakguard.py                         # the numeric-literal leak guard alone (~4 s)
python -I -B tests/equiv/slice.py                       # the replay slice alone (~1 min; exit 1 on any difference)
```

Outputs go to `build/` (not tracked): `build/pocket/<layout>/<variant>/img/{mcu.txt, mcu_ext.txt, wram_hi.txt,
wram_lo.txt, and the same WRAM bytes as the four lanes wram_b0..b3.txt that the newer RTL reads}` plus the ELF, map, nm, the objdump listing (`main.dis`), `layout.txt` (sizes per section, free space per region),
`objects.txt` (bytes per object and per tree area), `stack.txt` (the stack bound), `budget.txt` (sizes per module
and the 0.3.0 plan) and `md5.txt`. **A Pocket build fails when the stack bound or a size budget is over**
(`docs/BUDGET.md`).

- **The firmware file (0.3.0):** the Pocket core no longer has the firmware built into its bitstream. One Pocket
  build's images (`build/s1/pocket88k/<variant>/img`) become one file, **Little-Man Firmware**
  (`little_man_firmware.bin`, version 1.0; in this tree's code and docs it is called Fafrium):
  `python -I -B tools/mkfafrium.py make --img <variant>/img --sram <variant>/img/sram.bin --kind release` (add
  `--brain` for a build with the CPU MATE brain, `--kind test` for a TEST build), then `mkfafrium.py check` against
  the same images. The player copies it to `Assets/paprium/Koala_Koa.Paprium/` on the SD card. `docs/FAFRIUM.md`
  describes the file, the checks the core makes and the tools.
- **Variants:** `test` (debug aids on: B Jam's rule for every test build) and `release` (`-DPPM_RELEASE=1`).
- **Layouts:** `legacy54k` (the 0.2.6 layout: IROM 54 KB, WRAM 32 KB; runs on the 0.2.6 RTL) and `pocket72k` (the
  locked 0.3.0 layout: IROM 72 KB, WRAM 48 KB; **needs the RTL of stage 1 or later**, see `docs/LAYOUT.md`).
- **Host:** `ours_host.exe` speaks the audit harness pipe protocol (plus `O`, the option word). Use it with
  `harness.OursSide(exe=...)`.

## Milestones (stage 0, skeleton)

1. **0.2.6 moved in unchanged, byte-identical: PASS** (measured). `legacy54k` TEST = `52801d28 / 2c297175 / fb00f0ca
   / d0fd1a9b`, RELEASE = `1570f367 / d7da4574 / 1dfe3f40 / 502a6b1b` (`mcu / mcu_ext / wram_hi / wram_lo`), and the
   ELFs too (`ef138460`, `3a861f71`). `tests/check_images.py m1`.
2. **The same modules in the 72 KB layout: PASS** (measured). Brain bytes unchanged at 0x5360-0xD2EB, code window
   unchanged, data symbols at the same addresses, images pinned in `tests/expected/pocket72k_026.json`; run in
   lockstep against an earlier 0.2.6 test build (solo, frames 0-34,000, TEST and RELEASE): 0 differences. Sizes and
   free space: `docs/LAYOUT.md`.
