# buddy/ - the CPU MATE glue

The glue that runs the CPU MATE brain on the cart MCU (the NEORV32, the RISC-V soft CPU in our core that runs this
firmware). B Jam's decision of 2026-10-10: this buddy (the version called E5) is kept for good.

Taken from the shipped 0.2.6 firmware: `zz_buddy.c`, `zz_buddy_trap.c` and `buddy.h` (md5s of the 0.2.6 files: 297a7da9,
03fc8c0a and c25ae5e2). This tree has since added copyright lines and the FW_S1 lines in `buddy.h` and
`zz_buddy_trap.c`, and reworded their comments. `zz_buddy_brain.c` differs from 0.2.6 only in its three `.incbin` paths:
they name `brain.bin`, `cf.bin` and `rodata.bin` without a directory, and the build points the assembler at the brain
directory (`-Wa,-I<dir>`, from `PAPRIUM_BRAIN_DIR` / `paths.local.json`). The object code is the same (the milestone-1
images, the 0.2.6 source set built in this tree, are byte-identical to the shipped ones).

The brain (a reverse-engineered emulation of the game's CPU partner) is not in this tree. Its three files are checked
by md5 in every build (`fwbuild.json` "brain"); every shipped 0.2.6 image set holds the same bytes. The brain has a
fixed place: its code in IROM (the MCU's code memory inside the FPGA) at 0x5360-0xD2EB, `cf.bin` at WRAM (the MCU's
working RAM) 0x80002C00, the image tables at 0x80004110-0x80004647 and the brain's data at 0x80001820-0x80002ABF.
Moving any of them changes the brain's bytes, and the CART-TIMED test suite (the brain's call sequences with the
cart's timing) would have to pass again.

For 0.3.0 the glue is rebuilt for the new firmware's scheduler (first entered from the machine software interrupt,
MSI, instead of the main loop's `buddy_event`; no SFX feeder, no VU rows).

## `s1_glue.c`: the glue on the new firmware's four levels

The images of the new firmware (built with `FW_S1`, `tools/fwbuild.py s1`: its own start-up, scheduler and board layer)
link `s1_glue.c` instead of `zz_buddy.c`, and only the call wrapper of `zz_buddy_trap.c` (`buddy_call_brain` /
`buddy_abort_land`, unchanged: its 43 instructions equal 0.2.6's except the two address pairs of `buddy_jmp_sp`;
`buddy_trap` is left out when `FW_S1` is set). The brain, `cf.bin` and the image tables keep their bytes and addresses
(`tests/check_images.py s1`); `zz_buddy_brain.c` gains two labels around `cf.bin` (`FW_S1` only).

The scheduler's levels (core/sched/sched.h): L1 takes the 68000's mailbox posts (the machine external interrupt, MEI),
L2a runs the timer wheel (the machine timer interrupt, MTI), L2b and L2c run the song tick and the jobs (MSI), and the
thread (L3) runs in the time left. XLINK is the core's register block that holds the registers of the Mega CD link stub
(LSTAT, LCLR, ARM, ...); CAUSE.S is the "send" bit of the core's interrupt cause register. SFX = sound effects; the VU rows are the Boom
Box level meters; ISR = interrupt service routine; MTIME = the RISC-V machine timer.

| what | 0.2.6 (`zz_buddy.c`) | the new firmware (`s1_glue.c`) |
|---|---|---|
| a send | the main loop's slow path `buddy_event` | XLINK's post count -> CAUSE.S -> L1 -> brain pending -> the thread's `l3_brain` (earlier versions of the new firmware: MSI -> L2b) |
| during the call | `buddy_trap`: mailbox ISR, MTIME feeder / VU | the one trap entry: L1 (every post), L2a (the wheel, the SFX feeder included) and L2b / L2c (the jobs) preempt it. B Jam's decision of 2026-10-15: the call runs in the time the game's work leaves. An earlier version also had the firmware's sprite decoder stand-in preempt it; it is gone, as the RTL decodes now. |
| abort (restart / AI off) | checked in both ISRs; the trap exit jumps to `buddy_abort_land` | `brain_poll` from L1 / L2a; the trap exit of L1, L2a or L2b (`s1_trap.S`) sends the level that interrupted the call itself (its pc in the brain, its helpers or the wrapper) to `buddy_abort_land` |
| exception in the brain | `buddy_exc_brain` | `l2b_brain_fault` from `sched_exception` |
| restart / release / restore, AI off, option D | the slow path, a slice a pass | `l3_idle`, a slice a pass, one interrupts-off section |
| state | `.noinit`, cleared at the first event (MTIME_HI bit 31) | `.bss_upper`, cleared by the new firmware's crt0 |
| SFX feeder, VU rows | the glue (MTIME grid) | `interim/s1/audio_s1.c` on the wheel |

How it was checked (measured on 2026-10-11, with a test bench outside this tree): the new firmware's TEST image (the
build with the debug output; its real boot, dispatcher and glue) ran on an RV32 (32-bit RISC-V) model with an XLINK /
SRAM / flash model, fed the CART-TIMED closed-loop call sequences (five scenes, 1,959 accepted calls) while the 68000
posted at random: every answer (word, D_WORD, D_BUSY) and the brain's 2 KB RAM equal the reference brain build called
directly (except RAM $6AC-$6AF, which holds a value of the entry registers: three reference runs with different random
registers differ there and nowhere else); 1,294 L1 and 5 L2a entries were taken inside brain code. With sub-CPU
restarts cut into calls: 9 aborts, 9 landings, the calls after each release still equal. Planted bugs caught: the
landing removed, the abort poll removed, the restart flag not raised. Found by the bench and fixed: the idle
housekeeping cleared an AI-off flag set while a call ran (a stale LSTAT read), so it now runs as one interrupts-off
section.
