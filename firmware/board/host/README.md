# board/host - the x86 host board (the "ours" side of our comparison harness)

`ours_host.exe` = a unity build of `ours_host.c` + `legacy/026/mame.c` + `legacy/026/paprium.c` (the same files the
Pocket images are built from), driven over a pipe. Build: `python -I -B tools/fwbuild.py host` ->
`build/host/{test,release}/ours_host.exe`. Use: `harness.OursSide(exe=<path>)` from our comparison harness, which runs
the cart chip's program and this firmware side by side (the harness is not in this repository).

| file | what |
|---|---|
| `ours_host.c` | the harness's pipe protocol (L R W w P p M D S A G B Q) + `O` (set the option word read by the next R); stubs for sfx_*/mdp_* (logged), buddy_event, printf capture |
| `memmap.c` | maps host memory at the firmware's own ADDR_* (0x1000000-0x7900000), a byte copy of the harness's own file |
| `appmain.h` | stands in for board/pocket/appmain.h (board/host is first on the include path) |
| `host_neorv32.h` | GPIO_INPUT as a variable, CSR reads = 0, RTE no-ops |
| `host_rv_asm.h` | GNU as macros (`srli`, `andi`, `mv`) so the shared sources' RISC-V inline-asm templates assemble as the same x86 operations; needs `-fno-toplevel-reorder` |

Variants follow the Pocket ones: `test` (printf captured) and `release` (`-DPPM_RELEASE=1`, printf compiled out).
`tests/host_smoke.py` checks boot, the option word and TEST == RELEASE on the 68000-visible view.

The new-core source set (fwbuild.json "s1", built with `FW_S1=1`): `board_impl.h` + `s1_board.c` are the x86 fake
board of the board interface v1.0 (`docs/BOARD_IFACE.md` section 4), used by the host tests of that source set
(`tools/fwbuild.py s1`). They are not part of `ours_host.exe`.
