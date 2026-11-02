# Static checks: stack bound, size budget, leak guard

The tools of stage 0 (2026-10-10; the size basis, the fill accounting, the leak guard and the song-engine draft came
the same day, the sprite-engine draft on 2026-10-11). Stage 0 is this tree's first step; stage 1 the new scheduler and
dispatcher (the s1 source set, built with FW_S1); stage 2 the sprite engine; stage 3 the unpackers, the zoom, the
saves and MegaWire; stage 5 the song engine (the s5 variants, FW_S5); stage 6 the public release. How numbers are
known: measured (from a build, a compile or a run), PROXY (measured on stand-in code: today's functions, or code written
by our team from our own study of how the cart behaves, one function for each routine of the cart program, standing in
for 0.3.0 code that is not written yet), estimated
(calculated), not known. The test builds are the builds B Jam ran on the Pocket (test build 4: 2026-10-18,
4a: 2026-10-21, 4b: 2026-10-22, 5: 2026-10-23; test builds S3a, S3b and S3c in stage 3, 2026-10-27 to 2026-10-30). The
room plan is our plan for the IROM room of stages 2 and 3 (not in this tree). D numbers name the differences between the
0.2.6 firmware and the cart's chip that our study of the cart listed. The MCU is the cart's NEORV32 soft CPU in the
core; IROM is its code memory and WRAM its working RAM.

| tool | config | what it proves | runs |
|---|---|---|---|
| `tools/fwstack.py` | `tools/stack.json` | static stack bound per interrupt level and per nesting chain; fails the build when the gated scheme is over the stack region or something reachable cannot be bounded | every Pocket build (`stack.txt`) |
| `tools/fwbudget.py` | `tools/budget.json` | every linked byte belongs to a module (alignment fill included; each output section adds up to its size in the map), each module within its cap; the 0.3.0 allocations fit their rooms; the resident-code verdict | every Pocket build (`budget.txt`) |
| `tools/leakguard.py` | `tools/leakguard.json`, allow-list `tools/leak_allow.json` | no run of chip / ROM / sub-CPU / brain values is typed into the tree as numbers (u8/u16/u32, both byte orders, hex or decimal), in the sources or in the built sections; the allow-list holds exactly the two hand-typed chip tables | run_all (~4 s) |
| `tests/check_leakguard.py` | - | the guard catches planted chip values (8 rodata values as u16, and 6 more forms) and its allow-list rule is exact | run_all |
| `tests/check_stack_su.py` | - | fwstack's frame of every C function == GCC's own `-fstack-usage`, and that flag changes no object byte | run_all |
| `tests/check_tools.py` | - | the checks fail when they must (10 negative tests: 5 on the 0.2.6 image, 5 on the stage-1 image; and on the 0.2.6, stage-1 and stage-5 images: a real function pointer, one the code builds and one a table holds (the 0.2.6 image has no such table), left uncovered fails, and the relocation records missing or from another link fail) | run_all |
| `tests/check_fwstack_exact.py` | - | on one small program built with the firmware's compiler at the IROM, SRAM and WRAM-window bases: three real function pointers are taken and caught when left uncovered; a function whose start is used only as integers (an argument, a store, a data word) is not taken; a switch jump that objdump's note names 0x04800000 is read from its table; 30 checks | run_all |
| `tests/check_tree.py` rule 5 | `fwbuild.json` "s1" | the stage-1 source set reaches no 0.2.6 cart register (`reg_cmd`, `reg_status_*`, the page 0x02001FE0-0x02001FFF) and types no clock, raw and preprocessed exactly as built (test and release); `--selftest`: 5 planted mistakes caught, 2 controls pass | run_all (~6 s + ~5 s) |

## 1. Stack bound (tools/fwstack.py)

**How.** From the linked image (`main.elf` + `main.dis`), so crt0, the trap stub, libgcc and the glue are all in it:
each function is walked as a control-flow graph tracking the stack-pointer offset, whether `mstatus.MIE` may be 1, and
register constants (far calls, switch tables, `csrs mstatus,a5` resolve). MIE windows are found from the code, not
listed by hand. Indirect calls must be resolved in the config (the `cmd_*` table, the brain), or the check fails;
function addresses that are stored, written to a CSR or passed as arguments must be covered by an indirect-call set
(so a new handler table cannot slip past). A value counts as a function's address only where the code builds it as an
address: the linker's relocation records say which instructions and data words those are (`main.rel.elf`, the same
link with `--emit-relocs`, which `tools/fwbuild.py` writes beside `main.elf`; its loaded bytes must equal `main.elf`'s,
and every call site's record must name the call's own target). A plain integer that equals a function's start (a
length, a count) is listed apart and is not an address. An indirect jump or call is read from the walk's own register
values, never from objdump's `# <address>` note (that note follows objdump's last load of the register in address order
and can name an address the code never forms there). A level = trap-stub frame + handler; a chain = thread -> ... -> the top
level, each able to preempt the one below; worst = P(thread) + P(...) + D(top).

**Validated (measured):** the frames of all 101 C functions in the TEST link (91 RELEASE) equal GCC's `-fstack-usage`,
and compiling with that flag gives byte-identical objects (21/21); the 0.2.6 chains equal final026's
`stack_merge.py` (A 4,432 / B 4,800 / C 4,960); the recorded lockstep's deepest stack (4,208 B, solo 0-34,000) is under
the bound.

| scheme | what | TEST | RELEASE | of 5,120 |
|---|---|---|---|---|
| **026 (gate)** | the code as it is: thread; MTI tick and MEI post only inside a brain call (buddy_trap, 80 B) | **4,960** = thread P 416 (brain call) + MTI P 160 (feed_push MIE window) + MEI D 4,384 (F5's 4,128 B frame) | 4,960 | margin 160 |
| 030 | the 0.3.0 design: L1 MEI > L2a MTI > L2b MSI > L3 thread, every level open above it, F5/F4 buffers static (design 4.1) | 2,768 | 2,640 | margin 2,352 / 2,480 |
| 030-f5-on-stack | the same with F5's 4 KB local buffer left on the stack | 5,808 | 5,744 | **over by 688 / 624** |
| **s1 (gate of the stage-1 image)** | scheme 030 in real code (`tools/stack_s1.json`): section 7 | 2,580 | 1,668 | margin 2,540 / 3,452 |

0.3.0 levels (PROXY: today's functions with the job commands moved to L3 and the brain call to MSI, plus the cart
program's own call chains, written by our team from our own study of how the cart behaves, compiled for RV32IM -O2 with
`-fstack-usage` along their call graph):
thread 1,232 / 1,168 (job chains: MegaWire 560, saves 384, unpackers 304, chip F5 208; today's deepest thread path is
the interim `mdp_init` with a 1,040 B frame), MSI 576 (glue 96 + song tick 400; brain call 288), MTI 512 (song tick
400 + wheel 32 estimated), MEI 448 / 384 (dispatcher + 64 estimated status layer). The song-engine draft (section 4)
checks the 400: its deepest chain, mailbox entry -> 9494 -> song tick -> sequencer -> voice effects -> note on -> PSG
note on -> PSG tone message, is 336 B at -Os / 304 B at -O2 (frames measured with `-fstack-usage`, the chain sum
estimated). The sprite-engine draft checks the MEI level: its deepest chain, mailbox entry -> AD -> composer -> miss ->
claim, is 272 B at -Os / 256 B at -O2 of frames, 336 / 320 B with the 64 B status layer (same method), under 448 / 384.

**Consequence:** 0.3.0 must keep F5's working buffer out of the stack (the 0.3.0 design already places the scaling buffers in
`wram_upper`); with it on the stack the four-level nesting does not fit 5,120 B.

## 2. Sizes today (tools/fwbudget.py, measured, pocket72k)

Every byte of the link is attributed (0 unattributed), the linker's alignment fill between input sections included (its
own row, so the totals equal `layout.txt`: IROM 22,024 / 17,604 used); fwbudget also checks that the attributed bytes of
every output section add up to its size in the map. The caps are these sizes (max of TEST and RELEASE), because the
0.2.6 modules are frozen by milestone 1.

| module | TEST irom | RELEASE irom | wram | wcode | goes |
|---|---|---|---|---|---|
| brain (fixed) | - | - | - | - (39,380 brain bytes) | kept |
| buddy glue: brain call | 8 | 8 | 412 | 5,844 | rebuilt for MSI (stage 1) |
| buddy glue: SFX feeder + VU | - | - | - | 3,304 | stage 5 |
| legacy: sprite engine | 3,628 | 3,416 | 2,346 | - | replaced by code that does what the chip does (stage 2) |
| legacy: sprite block load (D43) | 1,456 | 1,244 | - | - | kept (stage 2) |
| legacy: unpack + DA/DB/F2/F4 | 1,836 | 1,656 | 16 | - | chip unpackers (stage 3) |
| legacy: F5 rescale + soft float | 4,480 | 4,480 | 2,052 | - | chip integer F5 (stage 3) |
| legacy: C6 setup | 1,048 | 708 | - | - | stage 1 / 3 |
| legacy: dispatcher, main loop, reset | 1,440 | 1,380 | 1,050 | - | stage 1 |
| legacy: saves (plain) | 280 | 280 | - | - | stage 3 |
| debug aids | 3,308 | 0 | 217 / 8 | - | TEST only |
| interim: album, SFX, VU, music cmds | 3,442 | 3,354 | 363 | - | stage 5 |
| board: crt0, main, UART setup | 572 | 560 | - | - | stage 1 |
| lib: memcpy, memset | 516 | 516 | - | - | kept |
| linker: alignment fill | 10 | 2 | 28 / 13 | - | follows the modules |
| **total** | **22,024** | **17,604** | 6,484 / 6,260 | 9,148 | |

Other code that exists today (measured, RV32IM): `core/tables` = 2,592 B of start-up tables (pan A/B, level T, wave and
SFX expansion) + 4,928 B curve knee, all rodata, 0 B code; they feed the synth logic in the 0.3.0 design (0 IROM; +1,536 if the
gain chain falls back to firmware). `board/pocket/boot/boot_cache.c` stub = 372 B (design guessed 150-300). Test build
4b (2026-10-22, measured): the real stub 348 B (IROM, both images); the WRAM boot overlay 15,124 of 16,384 B (15,032
before a later repair of the boot cache: the SFX copy before CACHE, the bar only in the unpack) (-Os; -O2 does not fit:
17.8 KB whole, 16.5 KB with only the decoder's two hot files at -O2), linked apart (`ovl/ovl.txt`). The TEST debug save
+12 B (3,176: the VS poll and the album poll at one instant, interrupts off), its allocation taken from the stub row
(372 -> 360).

## 3. Inputs of the 0.3.0 forecast

**Size basis: the cart program is Thumb-1 code** (corrected 2026-10-10, stage 0 (2026-10-10)). The STM32 core is a Cortex-M4, but
the program in it was compiled for Thumb-1: over all 737 chip-map function spans, 39,007 16-bit instructions, 1,855 BL,
**0 IT instructions**, and 69 other 32-bit decodes that are literal-pool data or ARMv6-M barriers (measured, and
measured again). A Thumb-2 compile is full of IT, `ldr.w` and `mov.w`; the image also uses
`__gnu_thumb1_case_uqi`, which GCC emits only for Thumb-1 targets (verified in the notes of an earlier FPGA-fit study). So every ratio is taken against Cortex-M0 (Thumb-1).
The first version of this page used Cortex-M4 ratios (1.508 / 1.708 / 1.952), which overstated every central forecast
by 7.3 %.

| ratio | value | label | source |
|---|---|---|---|
| R_OS: same C, RV32IM -Os / Cortex-M0 -Os | **1.406** | Measured | our 0.2.6 app sources (mame, paprium, sfx, mdp), the objects of an earlier FPGA-fit study, .text + .rodata: 14,555-14,559 / 10,350 B |
| R_O2: same C, RV32IM -O2 / Cortex-M0 -Os | **1.593** | Measured | same: 16,485-16,489 / 10,350 B |
| (not used) the same against Cortex-M4 -Os | 1.508 / 1.708 | Measured | same objects; Thumb-2 is not the chip's encoding |
| -Os vs -O2 on our code | -11.7 % | Measured | same |
| RV32C | -21 % | Measured | an earlier FPGA-fit study (its ALM cost not measured) |
| R_DEC: the chip's own code style, RV32IM -O2 / Cortex-M0 -Os | 1.939 overall; song engine 2.039, sprites 2.111, scaling 1.921, saves 1.982, MegaWire 1.928, WavPack 1.852 | **PROXY** | code written by our team from our own study of how the cart behaves, one function for each routine of the cart program, 620 of 737 functions (74,546 of 85,978 Thumb bytes), compiled per function for both cores (nothing of it is in this tree). That compiled code stands in for a straight port; it is not one. |
| C inflation (Cortex-M0 -Os of that C / the chip's real bytes) | 1.132 overall | PROXY | same |
| R_PORT: our code that does what the chip does, RV32 bytes per chip Thumb byte | ~1.12 | **PROXY, inferred** | the 0.2.6 sprite engine against the chip rows it covers; which rows it covers is inferred |
| check on a real port: the song-engine draft, RV32IM / the chip's Thumb | **1.341 (-Os) / 1.603 (-O2)** | Measured | the song-engine draft (section 4): a struct-based C port of the whole song engine, 12,362 Thumb bytes. R_OS and R_O2 held (the port is 4.6 % under R_OS, 0.6 % over R_O2); R_PORT is refuted for this module; R_DEC overstated it (the compiled C of the chip's routines is 1.29x / 1.20x the draft on the engine proper) |
| check on a real port: the sprite-engine draft, RV32IM / the chip's Thumb | **1.43 (-Os) / 1.67 (-O2)** on the six routines the chip does not duplicate; **1.03-1.06 / 1.13-1.17** on the whole resident engine against the chip with its aging chains counted as a loop | Measured | the sprite-engine draft (section 4): all 141 SPR rows of our map of the chip's routines ported. R_OS and R_O2 held within 2-5 % on the routines the chip writes once. The whole module comes in far under every forecast because the chip repeats code a port writes once (4,020 B of unrolled aging, three copies of search + claim, one refusal copy per mailbox), which a Thumb x ratio basis cannot see; R_DEC SPR (2.111) overstated it most (the compiled C of the chip's routines is 1.10x / 1.03x the draft on the six routines) |

That C compiles to the same size for both cores (M0/M4 1.006 overall, song engine 0.996, measured), so the hi
forecast barely moves with the basis; the central forecast moves by the full 7.3 %.

Forecast per module: lo = Thumb x R_PORT (or the measured size of code that exists), cen = Thumb x R_OS (cold) or
x R_O2 (hot L1/L2: dispatcher, sprites, F5, unpack), hi = Thumb x R_DEC (a straight port as global-heavy as the chip's
code). Thumb bases are the measured spans of our map of the chip's routines. Six modules are no longer forecasts but measured sizes of drafts
(section 4): from stage 0 (2026-10-10) the song engine (16,584 B -Os, its allocation; 19,816 B -O2), the 88 audio config (384 B)
and the synth state (6,400 B of data); from stage 0 (2026-10-11) the sprite engine (5,704 B -O2, its allocation; 5,164 B -Os;
7,456 B in the chip's code shape), the sparse block->id index (248 B) and the sprite state (2,100 B of data).
Per-module numbers and bases: `tools/budget.json` "plan" (its "ratio_labels" and "ratio_checks" carry the labels
above), the report: `build/pocket/pocket72k/<v>/budget.txt`.

## 4. The 0.3.0 plan and the verdict (estimated from the above, Thumb-1 basis; the song and sprite engines measured as drafts)

(The numbers in this section are stage 0 (2026-10-11)'s. Stage 1 has since moved the watchdog into the IROM at its measured size
(W7) and resized D43 (W4-W6): `budget.txt` now prints IROM allocations 40,648 B (428 B free) and a central resident
case of 2,962 B (TEST) / 5,762 B (RELEASE) free. What the stage-1 code says about the plan rows: section 7.)

| placement | room | allocated | free | forecast lo / cen / hi |
|---|---|---|---|---|
| IROM firmware (72 KB around the brain) | 41,076 | 39,488 (incl. TEST debug 2,800, and the constant tables 2,098, moved here from WRAM-ROM) | 1,588 | 32,774 / 39,488 / 49,376 |
| WRAM code window (16 KB - brain's 6,728) | 9,656 | 8,555 (glue 4,000, F4/F5/B6 3,836, watchdog 619, mute/counters 100) | 1,101 | 6,740 / 8,555 / 11,462 |
| wram_upper (synth state, scaling buffers, .bss, WRAM-ROM) | 16,384 | 15,626 (synth state 6,400 measured; WRAM-ROM: app init, save reply, trace/83 = 2,582) | 758 | 11,620 / 15,626 / 17,286 |
| wram_data (sprite state 2,346 allocated, 2,100 measured in the draft) | 6,176 | 4,350 | 1,826 | |
| SRAM cold pack | 32,768 | 3,847 | 28,921 | |
| SRAM MegaWire (code 25,750 + RAM 13,920) | 65,536 | 39,670 | 25,866 | 34,666 / 39,670 / 48,804 |
| boot overlay | 22,560 | 17,508 | 5,052 | 12,710 / 17,508 / 21,942 |

**Resident code (IROM + window + WRAM-ROM) against its room, 54,072 B** (55,972 B before the song-engine draft: the
synth state's measured 6,400 B in wram_upper take 1,900 B more than the 4,500 B estimated, and that comes off the same
room; the sprite state is in wram_data, outside this room):

| | lo | cen | hi |
|---|---|---|---|
| RELEASE | 39,094: free 14,978 (IROM alone holds) | 47,825: free **6,247**; needs 6,749 B spilled out of the IROM | 60,360: **over by 6,288** |
| TEST | 40,594: free 13,478 | 50,625: free **3,447**; needs 9,549 B spilled | 64,780: **over by 10,708** |

**Does 72 KB still hold? Yes on the central forecast, now with both big engines measured: about 3.4 KB (TEST) / 6.2 KB
(RELEASE) to spare. No on the worst case: 6.3-10.7 KB over.** The central case needs (a) the song engine built -Os and
the sprite engine -O2 (the plan's convention for hot L1 code), each changed only where a CPU measurement asks for it,
and (b) about 6.7 KB (RELEASE) / 9.5 KB (TEST) of resident code in the code window and WRAM-ROM, as the 0.3.0 design planned.
The sprite draft gave back 1,003 B on the central case (the engine 951 B under its forecast, the sparse index 52 B
under) and 5,142 B on the worst case (measured sizes against the estimated forecast). The margin moves with these
choices (estimated from the numbers above):

| choice | TEST free | RELEASE free | decided by |
|---|---|---|---|
| as allocated: the chip's RAM layout, the song engine -Os, the sprite engine -O2 | 3,447 | 6,247 | |
| the sprite engine and its index built -Os too (-548) | 3,995 | 6,795 | a stage-1/2 CPU measurement (sprite replies are the longest L1 work) |
| SFX record table sized to the game's 127 SFX (2 KB -> 1 KB) | 4,471 | 7,271 | B Jam, with stage 5 |
| SFX record table and BGM pointer table read in place (0 B of WRAM) | 5,751 | 8,551 | B Jam, with stage 5 |
| the song tick path (A1 + A3) built -O2 (about +2.0 KB) | about 1,450 | about 4,250 | a stage-5 CPU measurement |
| the whole song engine built -O2 (+3,232) | 215 | 3,015 | |

**The worst case** is now driven by the song engine at -O2 and by modules nobody has drafted. Hi minus cen, TEST
(14,155 B in all): song engine at -O2 +3.2 KB, buddy glue +1.8 KB, sprite engine in the chip's code shape +1.8 KB,
TEST debug aids +1.6 KB, all other resident modules +5.7 KB together (scaling +790, trace/83 +789, constant tables
+788, unpackers +723, dispatcher +642, the rest under 0.5 KB each). Most of the remaining hi forecasts are the C of the chip's
routines compiled (R_DEC, PROXY), and on both drafted engines that proxy came out too big. Even if every remaining
R_DEC forecast were as pessimistic as the song engine's (estimated: their R_DEC parts / 1.20, -2.8 KB: dispatcher,
unpackers, scaling, watchdog, app init, saves, trace), the hi case stays about 7.9 KB (TEST) / 3.5 KB (RELEASE) over.
The sprite hi is the draft in the chip's code shape (7,456 B, a measured variant), kept as the upper bound because the
draft was not run; with the song engine's hi convention instead (the draft as written, -O2: 5,704 B) the hi case is
8,956 / 4,536 B over (estimated). (History: before the sprite draft the central case had 2.4 / 5.2 KB free and the hi
case was 15.9 / 11.4 KB over; before the song draft, on the Thumb-1 basis, 4.1 / 6.9 KB free and 18.7 / 14.3 KB over;
the first version of this page, on Cortex-M4 ratios, had the central case at 1.6 / 4.4 KB free.)

### Song-engine draft (measured, stage 0, 2026-10-10)

**What it is.** The song-engine draft (2026-10-10) is our team's first version of the song engine, written from our own
study of how the cart behaves: one function for each routine of the audio subsystem (54 routines) and for each of the
92 dispatcher fragments of the 13 audio commands, state as structs in the chip's layouts, and the chip's two known
bugs kept. Every chip data table is a
zero-filled placeholder of its real size, so no chip value is in it. It is compiled and linked RV32IM with this tree's
GCC 15.2 and Pocket flags (`-Os` swapped in for the -Os build), gates as code. It lives in a scratch clone
outside this tree (2026-10-10); its review rebuilt it from there and
got the same sizes (measured). It was not run: its behaviour is not known (stage 5 proves it against the cart
runner).

| part | chip Thumb | RV32IM -Os | RV32IM -O2 |
|---|---|---|---|
| A1 sequencer, module commands, effects, note functions | 3,824 | 5,968 | 7,532 |
| A2 voice back-ends, PSG envelope, pitch and gain helpers | 1,312 | 1,800 | 2,252 |
| A3 Z80 messages, packet + YM-DAC stream copy, flush timer | 1,876 | 2,848 | 3,256 |
| A4 masters and fades | 684 | 1,140 | 1,192 |
| A5 SFX control | 1,168 | 1,688 | 2,168 |
| A6 Boom Box feed | 212 | 328 | 400 |
| A7 audio posts 9494, 88, C9, CA, 8C, 8D, 8E, D0-D3, D5, D6 (gates + bodies) | 3,288 | 2,812 | 3,016 |
| **song engine = plan module "song engine hot path"** | **12,364** | **16,584** (x1.341) | **19,816** (x1.603) |
| variant: gates in a table (the dispatcher then carries the gate table) | | 16,252 | 19,416 |
| variant: every refusal inlined at its site, as the chip does | | 18,852 | 22,568 |
| outside it: 88 audio config (its own plan module) | 272 | 384 | 388 |
| outside it: wave envelope 300 Hz (logic in the 0.3.0 design; firmware fallback) | 452 | 580 | 696 |
| outside it: dispatcher entry + one 55-entry handler table (dispatcher module) | | 568 | 600 |
| outside it: chip data tables, placeholders (constant tables module) | | 326 | |
| its RAM (.bss) | | 6,400 | |

- **Into the plan:** the song engine's cen and allocation = 16,584 (-Os); lo = the same (R_PORT 1.12 is refuted here:
  a struct-based port measures 1.341); hi = 19,816 (the whole engine -O2). The glue the draft does not cover gets its
  own estimated line, 350 / 625 / 900: the wave-voice hand-off to the synth logic (0-0.4 KB), the 0.3.0 design's sliced song
  tick, urgent rule and held posts (0.2-0.5 KB, partly in the scheduler module, so it may double count a little), and
  the board's flush timer and packet copy (~0.1 KB). The 88 audio config is measured 384 / 384 / 388.
- **RAM (measured):** S + 26 voices 3,000, SFX record table 2,048, SFX state 448, packet staging 448, BGM pointer table
  256, Z80 queue 132, G 64, 4 = 6,400 B. The SFX record table and the BGM pointer table had no allocation. To keep
  wram_upper's allocations inside its room, the firmware constant tables (2,098 B) moved from WRAM-ROM to the IROM.
  That is bookkeeping: resident code counts the same in either place, and the IROM reads at the same cost
  (`docs/LAYOUT.md`). Which RAM option to take is open (table above).
- **Gate tables (measured on the audio commands):** one 55-entry handler table serves both mailboxes (mailbox A posts
  never carry arguments; inferred for the entries not studied). A gate table costs +532 / +612 B in the dispatcher and
  saves 332 / 400 B in the audio handlers (19 gates). Over all commands it saves about 0.45-0.57 KB (estimated from the
  audio rate), not the ~3 KB the 0.3.0 design assumed. The dispatcher module keeps its forecast until the dispatcher is
  drafted (the forecast counts the chip's 662 B of dispatch tables; the draft needs 220 B).
- **Stack:** the deepest song chain is 336 B (-Os) / 304 B (-O2), under the 400 B the 0.3.0 levels assume (section 1).
- **CPU (not known):** nobody has measured whether the song tick fits its slice at -Os.
- **RV32IMC (information only):** 13,800 / 16,656 B (-16.8 % / -15.9 %); the ALM cost of compressed instructions was
  never measured.

`tools/budget.json` plan module "song engine hot path ..." keeps the whole record under `draft` (status measured, the
per-part, variant and outside sizes, the RAM), and `tools/fwbudget.py` prints it in every `budget.txt`.

### Sprite-engine draft (measured, stage 0, 2026-10-11)

**What it is.** The sprite-engine draft (2026-10-11) is a C port of the chip's whole sprite subsystem: one function per
chip routine, all 141 SPR rows of our map of the chip's routines (9,596 B), with the chip's cases and branches, state as one struct with the chip's
field sizes, and the 0.3.0 design's sparse block->id index in place of the chip's 16 KB table. Every chip data table is a
zero-filled placeholder of its real size. It is compiled and linked RV32IM with this tree's GCC 15.2 and Pocket flags
(`-Os` swapped in for the -Os build), gates as code, 0 warnings. It lives in a scratch clone
outside this tree (2026-10-11); its review rebuilt it from the same sources and
got byte-identical sizes (measured). The leak guard passes on its sources and its 10 ELFs. It was not run: its
behaviour is not known (stage 2 proves it: 351,839 draws equal the chip).

| part | chip Thumb | RV32IM -Os | RV32IM -O2 |
|---|---|---|---|
| S1 composer (4 chip fragments -> one function + 3 helpers) | 2,112 | 2,016 | 2,092 |
| S2 AE aging (entry + 4,020 B of unrolled chains -> one loop) | 4,064 | 164 | 188 |
| S3 AE open, B1 flush, B0 | 428 | 624 | 648 |
| S4 AF + multiplex | 852 | 1,208 | 1,544 |
| S5 AD wrapper (3 entries) | 294 | 500 | 548 |
| S6 EC worker | 252 | 280 | 316 |
| S7 posts EC, AD, AE, AF, B0, B1 (gates + refusals) | 750 (dispatcher walk) | 372 | 368 |
| **sprite engine = plan module "sprite engine, complete chip copy"** | **8,752** (4,890-5,040 with the aging as a loop) | **5,164** | **5,704** |
| variant: the chip's code shape (search + claim and every refusal inlined at each site) | | 6,612 | 7,456 |
| variant: gates in a table (the gate table lives in the dispatcher) | | 4,976 | 5,524 |
| variant: the chip's direct 16 KB block->id table (+15,616 B of RAM: cannot be placed) | | 5,048 | 5,676 |
| outside it: sparse block->id index (its own plan module) | | 240 | 248 |
| outside it: F2 block viewer, body + post (the plan keeps our D46 path; unpack/stream module) | 326 | 292 | 304 |
| outside it: C6 job 11 sprite part, init + anim setup (cold pack, "C6 job 11 body") | 538 | 728 | 740 |
| outside it: chip tables as placeholders, slot->id + DMA words (constant tables module) | | 568 | 568 |
| its RAM (.bss): sprite state + index | | 2,100 + 768 | |

- **Into the plan:** the sprite engine's cen and allocation = 5,704 (-O2, the plan's central convention for hot L1
  code; sprite replies run in L1); lo = 5,164 (-Os, if a CPU measurement allows it); hi = 7,456 (the chip-shape variant
  at -O2, the largest measured form, kept as the upper bound for an unrun draft). Was (forecast): 5,756 / 6,655 /
  12,446. The sparse index is measured 240 / 248 / 248 (was 200 / 300 / 400).
- **Why it is under every forecast:** the chip repeats code a port writes once, and a Thumb x ratio basis counts every
  copy. On the six routines the chip writes once (AE open, flush, AF, B0, AD, EC: 1,826 Thumb) the port is 1.43x / 1.67x
  the Thumb, so R_OS and R_O2 held (section 3). The forecast's hi basis (5,896 Thumb) also counted F2 and the C6 sprite
  part, which belong to other modules; the whole SPR as drafted, every part, plain -O2, is 6,748 B.
- **RAM (measured):** sprite state 2,100 B (handles 1,024, engine block 260, block directory 10, load list 32,
  countdowns 128, id->block 256, lists A/B/C 390); its allocation stays at 0.2.6's 2,346 B (246 B of headroom). The
  index's 768 B (256 bucket heads + 128 nodes) is exactly the 0.3.0 design's. Both are in wram_data, outside the resident room.
- **Stack:** section 1 (272 / 256 B of frames, under the MEI level).
- **Not settled by the draft:** CPU per frame at -Os against -O2 (not measured); the C6 job 11 body's forecast
  (708 / 914 / 1,260, cold pack) holds the sprite part's 728-740 B with little room for the rest of C6 (cold pack, 28 KB
  free, not resident); F2's chip body (292-304 B) against our F2 share of the 480 B "DA/DB/F2 handlers" (split not
  measured); the D43 loader call shape (per block or the whole list) is a stage-2 choice; the 0.2.6 object-107 door fix
  is ours, not the chip's, so it is not in the draft (D23: recheck in stage 2).

`tools/budget.json` plan module "sprite engine, complete chip copy" keeps the whole record under `draft`, and
`tools/fwbudget.py` prints it in every `budget.txt`.

## 6. Numeric-literal leak guard (tools/leakguard.py)

`tests/check_tree.py` looks for 64-byte runs of the brain files; a chip table typed in as C numbers passes it. The
guard closes that gap.

**How.** Every tracked or new `.c .h .S .s .ld .py .json` file is split into code and comment/string text. In each, runs
of numeric literals are found (hex, decimal, binary, C octal, C suffixes, Python underscores, negatives as two's
complement), with only commas, spaces, brackets and assembler data directives between them (comments between them are
skipped, so a table with `/* row */` notes is still one run). Every 8 consecutive values are encoded as u16 LE, u16 BE,
u32 LE and u32 BE, and every 12 as u8, and looked up in the references: the ROM (plain and 16-bit swapped), the cart
program, the sub-CPU program (plain and swapped), `brain.bin`, `cf.bin`, `rodata.bin` (read in place, md5-checked).
Windows that match any counter table are skipped: fewer than 5 different values, steps of at most 2 sizes (ramps,
staircases, a hex-digit string after a NUL pad), mostly zero bytes. The built sections of all four Pocket builds are
scanned too: data sections in 12-byte windows against every reference, code sections in 16-byte windows against the
non-RV32 references (the brain is RV32 code, so GCC idioms match it by construction). The brain's own bytes are
excluded after an exact compare.

**Why u8 needs 12 values (measured):** with 8, our own generated `chip_sfx8_expand` (a smooth curve) matched 9 bytes of
8-bit PCM in the ROM by coincidence. Smooth 8-byte stretches are common in 8 MB of samples.

**Allow-list (`tools/leak_allow.json`).** Exactly the two tables B Jam decided to type in: `chip_note_pitch` 110 x u16
and `chip_fm_fnum` 13 x u16, each pinned by the SHA-256 of its values and a place (`core/*`). A hit is allowed only
inside one C array definition with that name, that count and those exact values (or the linked object of that name,
size and bytes); a same-named array that differs in a value, its count or its place fails the guard. In a built
section a window that overlaps such an object is allowed too when every byte of it is inside an allowed object or
zero: the linker's fill or a zero byte beside the table, which equals the cart program because the chip has zero bytes
beside the same two tables (measured 2026-10-30 on the stage-5 images; B Jam's decision of 2026-10-30 approved it); a window with any
other byte outside them still fails. Today both
entries match nothing; stage 5 adds the tables. (measured: the chip's note table is 108 values; the plan's
110 included the next two words, which the note lookup can read past the table; tools/leak_allow.json holds the entry as
typed.)

**Proof (measured, `tests/check_leakguard.py`, run_all):** clean pass on the tree and its builds (0 hits; 92 files,
114,034 section windows; ~4 s); positive controls in a temporary directory outside the tree, all caught: 8 cart-program
rodata values as u16 hex in a C array, the same in decimal in Python, 12 rodata bytes as `.byte` lines, 8 ROM
big-endian words in decimal, the 8 values inside a comment, 8 rodata u32 words, 12 rodata bytes inside a raw section;
the allow rule: the exact 110-value table is allowed (as source and as a linked RV32 ELF), one changed value, 12 of 13
values, or the right values in the wrong place each fail.

## 7. Stage 1 against the plan (work item W11 of docs/STAGE1_PLAN.md, measured 2026-10-11)

The stage-1 image (`tools/fwbuild.py s1`, `build/s1/pocket72k/<variant>`) is built with the same two checks as every
Pocket build: `fwstack.py` with `tools/stack_s1.json` (its scheme `s1` is the gate) and `fwbudget.py` with this budget
file (every stage-1 object has a module row with a cap; 0 bytes unattributed). `tests/check_tools.py` shows that both
fail on the stage-1 image when they must: the stack region 1 B under the s1 worst chain, the fatal-halt switch left
unresolved, the stage-1 dispatcher's cap 1 B under its size, the stage-1 scheduler's bytes unattributed, and the
stage-1 watchdog 1 B over its 0.3.0 allocation.

**Stack (measured).** Scheme `s1` is scheme 030 built from real code: L1 `l1_mei` > L2a `l2a_mti` > L2b `l2b_msi` > L3,
one trap entry, 80 B a level, every level open above it. Worst chain 2,580 B TEST / 1,668 B RELEASE of 5,120 (margin
2,540 / 3,452), against scheme 030's PROXY 2,768 / 2,640. One stand-in is left: the stage-5 song tick behind
`audio_tick_slice` (`@chip_song_tick`, 400 B PROXY). The thread level's deepest path today is the interim album's
`mdp_init` (a 1,056 B frame), which leaves with stage 5.

**Sizes against the plan rows.** Plan rows whose job stage-1 code already does are linked in one of two ways:
- `measured_by` (gated: the build fails if the stage-1 code is over the allocation): watchdog / heartbeat 1,104 B TEST /
  920 B RELEASE of 1,104; debug aids + per-level counters 2,580 B TEST of 2,800 (3,160 B of 3,160 from the 2026-10-17 debug-save update,
  2026-10-17: the debug save version 5's carried block; the allocation was raised out of the IROM placement's slack,
  372 -> 12 B, TEST only; 3,164 B of 3,164 from the 2026-10-19 lateness update, 2026-10-19: version 6 carries the CPU MATE late counter's and
  the album recorder's words across the quit, the allocation raised again out of that slack, 12 -> 8 B, TEST only; the
  counter itself is in the glue's code window (+20 B TEST; the fix of 2026-10-19: +40 B more, each late answer counted once
  and late_max from readable TICK reads only, 2,424 B TEST) and the recorder in the interim album, +424 B TEST irom, a
  module that leaves with stage 5 and is no plan row); buddy glue 2,332 B TEST / 1,752 B
  RELEASE of 4,000 (code window).
- `stage1_by` (printed in every stage-1 `budget.txt`, NOT gated):

| plan row | allocation (estimated) | stage 1 TEST | stage 1 RELEASE | why it is not gated |
|---|---|---|---|---|
| crt0, trap entry, L1/L2/L3 scheduler, timer wheel | 1,200 | 3,272 | 2,748 | the 1,200 was 0.2.6's crt0 + main (372 + 72) and a estimated scheduler; the stage-1 code adds the trap entry (372), the board boot (~290) and the scheduler's held posts, urgent promotion and brain poll (scheduler + wheel 1,672 RELEASE; TEST adds 388 B of counters, which the plan holds in its debug-aids row) |
| dispatcher, gates, status layer, job queue, C6 reply | 3,236 | 6,964 | 6,944 | the stage-1 dispatcher writes every gate and refusal out per mailbox fragment, as the chip does (`disp.c` 5,920 RELEASE). The song-engine draft's A7 (the audio posts' gates and bodies, 2,812 B -Os) and the sprite draft's S7 (372 B) count some of the same gates again. How much is not known |
| app init values + warm reset | 692 | 652 | 656 | under; in stage 1 it sits in the IROM (the plan puts it in WRAM-ROM) |

**What it does to the verdict (estimated from these numbers).** If the two rows that are over took their stage-1 sizes,
the IROM allocations would go from 40,648 to 45,904 B (RELEASE sizes): 4,828 B over the 41,076 B room. The central
resident case would go from 2,962 B free (TEST) / 5,762 B free (RELEASE) to **2,798 B over (TEST) / 542 B free
(RELEASE)** (TEST up to 388 B better: the scheduler's counters, which the debug-aids row already holds). If all 3,184 B
of the drafts' gate parts turn out to be the same code as the stage-1 dispatcher's (the most the overlap can be), the
central case is 386 B free (TEST) / 3,726 B free (RELEASE). So on the central forecast the TEST image no longer clearly
fits: the answer rests on the overlap (not known) and on the planned spill (section 4). This is B Jam's call: no
allocation is changed here and nothing is gated on these two rows.

## 8. Stage 5, step F1: the engine linked, against the plan and the 88 KB IROM (measured 2026-10-22)

The song engine came in four steps, F1 to F4 below. The first images that link the song engine: `tools/fwbuild.py s1` variants `s5test` / `s5release` (`-DFW_S5=1`, layout
pocket88k: rom0 32 KB + 56 KB, the IROM firmware room 57,460 B = 90,112 - the brain's 32,652), core/song at -Os (the
section 4 convention; `s5test_o2` / `s5release_o2`, on demand, build it -O2). The interim audio (audio_s1, sfx_s1,
vu_s1), the album (mdp, everdrive) and TEST's debug save are left out of them (the debug save's record carries the
interim audio block: F4 gives it its stage-5 record). `fwbudget` is not run on them (`budget: null`): no plan row is
gated; this section is the size report a new module needs (the bytes first, then trim or rebudget). Bytes = IROM (code + rodata + the .data image), from each
build's `objects.txt` / `layout.txt`.

**The IROM after F1:**

| image | IROM firmware used | free of 57,460 | of which irom_lo / irom_hi | stack worst of 5,120 |
|---|---|---|---|---|
| stage 1 TEST (pocket72k, room 41,076) | 39,532 | 1,544 (of 41,076) | 632 / 912 | 3,124 |
| stage 1 RELEASE (pocket72k) | 31,212 | 9,864 (of 41,076) | 4,452 / 5,412 | 2,340 |
| **s5test** (song -Os) | **50,488** | **6,972** | 2,872 / 4,100 | 2,436 |
| **s5release** (song -Os) | **45,788** | **11,672** | 5,956 / 5,716 | 2,372 |
| s5test_o2 (song -O2) | 54,400 | 3,060 | 2,872 / 188 | 2,260 |
| s5release_o2 (song -O2) | 49,700 | 7,760 | 5,956 / 1,804 | 2,196 |

(F1 repair, 2026-10-22, measured: L1 serves the two mailboxes in arrival order (`l1_serve_a` / `l1_serve_b`, SEQLAT
compared when both are pending): +128 / +164 / +136 / +172 B against the first F1 build's 50,360 / 45,624 / 54,264 /
49,528, sched.c in irom_lo 1,592 TEST / 1,312 RELEASE; song_oeq.c 2,208 B -Os / 2,624 -O2 (+8 / +16: the held posts
taken by arrival number); wram_upper 12 B less (the held posts' service-order byte gone).)
(The first commit of step F2, measured: `SONG_Q_N` 16 -> 8 leaves every IROM figure above unchanged and
takes 236 B off wram_upper: 13,320 / 10,936 B used, TEST / RELEASE.)
(Step F2, measured: the tick's board side, counter 11's fold and the module store's directory read add 436 B of
IROM to both images (irom_hi +432, irom_lo +4): s5test 6,536 B free, s5release 11,236; .bss +20 B (the DIAG
fold's base and totals), wram_upper -4 B (dbg_underrun gone). Against section 4's plan these 436 B are glue the
draft did not cover (the board side of the tick), like F1's queue glue.)
(A repair of step F2, measured against a build of 2026-10-22: DIAG's clear only when STATUS is quiet (board_trace_fold
0xD8 -> 0xC4 B plus diag_fold 0x94 / 0x98 B) adds 132 B of irom_hi to s5release (11,104 B free) and 8 B of .bss
(the put-off and forced counts) to both; s5test comes out 24 B smaller (6,560 B free): the new .bss words move its
data so that 30 other functions (dispatcher, boot, scheduler, watchdog) link 4-8 B shorter, 148 B in all; every
other size unchanged.)
(Step F3, measured against the F2 repair's figures: C6 (the chip's audio set-up and bank load, its two stream
decoders, ours' module pre-decode: core/song/song_c6.c 2,100 B -Os, of which the 0x81 (LZO) decoder 724 B, the 0x80
decoder 204, the bank load's gates 372, the store loop 288), the SQ_CALL items (`song_call` 188 B), the store
writer, CONFIG and C6's views in s5_glue.c (736 B now), the 8C job's busy time and C6's job in jobs.c and
C6's gate in disp.c add 3,380 B of IROM to s5test (3,180 B free: irom_lo 776, irom_hi 2,404) and 3,420 B to
s5release (7,684 B free: 3,852 / 3,832); wram_upper +32 B (the queue items' fn pointers, 8 x 4 B: 13,348 / 10,964 B used). Against the F1
forecast below ("the C6 audio init and the module store glue, about 0.5-1.5 KB estimated") F3 is 1.9-2.9 KB over:
the two decoders (928 B) and the pre-decode were not in that row. F4 adds the SFX laws, the main-loop pass's wiring
and TEST's debug save (the interim audio code is out of the s5 images since F1); the reserve below (cold song code into the code window: 6,912 B free there) is the first lever if TEST runs
short.)

The free bytes sit in two regions (below and above the brain); the song objects are placed in irom_hi
(`board/pocket/link/pocket88k.json`), so irom_lo's free bytes take other code only. WRAM: wram_upper 13,556 / 11,172
used of 16,384 (the song state, `upper_bss_objects`), wram_data 896 / 1,168 free, and the code window has 6,912 /
7,552 B free (TEST / RELEASE) now that the interim SFX feeder's 4,552 B of window code are gone.

**Where the bytes went (TEST, stage 1 -> s5test: +10,828 B; RELEASE +14,412 B):** core/song +18,376; core/tables
+1,536 (the level table T and pan A / B: the engine computes the per-voice levels in the firmware as the chip does,
section 2's "+1,536 if the gain chain falls back to firmware"); core/dispatch -412 / -576 (the interim audio fragments
replaced by `f_song` and the glue); core/sched +20 / +104 (the tick slot, held posts and deferred finish out; the
queue's L1 / L2b / urgent paths and `s5_glue.c` 164 in); interim/s1 -3,830 / -3,362; interim/album -2,240 / -1,644;
board/pocket -2,620 / -8 (TEST's debug save, 2,560, out); the rest +/-16.

**Against the plan rows (section 4's song-engine draft):**

| plan row | plan lo / cen / hi | Measured -Os | Measured -O2 | |
|---|---|---|---|---|
| song engine A1-A7 (song_seq, song_voice, song_z80, song_sfx, song_posts) | 16,584 / 16,584 / 19,816 | 15,658 | 19,146 | under by 926 / 670 |
| 88 audio config (song_cfg) | 384 / 384 / 388 | 264 | 272 | under by 120 |
| the glue the draft did not cover (estimated 350 / 625 / 900) | 350 / 625 / 900 | song_oeq.c 2,208; s5_glue.c 164; net of the stage-1 code it replaces: 1,936 TEST / 1,892 RELEASE (F1 repair; 1,808 / 1,728 before) | song_oeq.c 2,624 | **over: +1,311 / +1,267 on cen, +1,036 / +992 on hi** |
| song tables (placeholders in the draft) | 326 | 254 (song_tables) + 1,536 (core/tables) | same | +1,464 (the gain chain in the firmware) |
| wave envelope 300 Hz | 580 (firmware fallback) | 0 (synth logic, the 0.3.0 design) | 0 | as planned |

The overrun is the queue: the 0.3.0 design's held posts and urgent rule were estimated at 0.2-0.5 KB; the ordered queue with
DONE computed from the pending arrivals (`done_value` 232 B), the held posts (`arrive` 316; taken oldest arrival
first since the F1 repair), the urgent deadline (`song_tick_due` 264), the 8C module items (`song_job_done` /
`song_job_waiting` 280) and the item run with synth_begin / synth_end and the meters (`song_run_one` 504,
`song_meters` 116) measure 2,200 B at -Os (2,208 after the F1 repair; L1's arrival-order serve adds 120-164 B in
sched.c).

**Against our design notes for stage 5, the song engine and synth (not in this tree; estimated):** "TEST +9.8..11.4 KB
free after stage 5" at 88 KB. After F1 the
TEST image has 6,972 B free (7,100 before the F1 repair): 2.8-4.4 KB under that band, with F2-F4 still to add the C6
audio init and the module store glue (not known, about 0.5-1.5 KB estimated), the SFX laws in the core (not
known) and TEST's debug
save again (2,560 B at its stage-1 size, less the interim audio block it drops). Estimated from these: TEST about
2-4 KB free at the end of stage 5, RELEASE about 9-11 KB. Stages 2 and 3 then replace legacy/026 (9,231 B TEST) and
the F5 rescale's soft float (3,812 B) with the chip's code (section 4 plans the sprite engine at 5,704-7,456 B).

**Trim or rebudget:** rebudget, no trim in F1. The numbers:
- keep core/song at -Os (section 4's convention): -O2 costs +3,904 B TEST (measured, s5test_o2); -O2 on the tick
  path only (song_seq + song_voice + song_z80) +2,708 B (estimated from the per-object -Os / -O2 sizes), TEST then
  about 4.4 KB free after F1;
- the glue row becomes 1,936 B TEST / 1,892 B RELEASE net after the F1 repair (measured; 1,808 / 1,728 before it),
  +1.3 KB on the plan's centre; the song engine
  row and the 88 row give back 1,046 B of it (measured), so the engine as a whole is +137 B TEST over the plan's
  centre (+1,601 with the tables row);
- the reserve, if TEST runs short in F2-F4 (estimated, none taken): the code window's 6,912 free bytes (cold song code:
  the 88 and 8C bodies, song_cfg, about 1.5-3 KB); song_oeq.c's walks (`song_tick_due` and `done_value` kept as
  running values instead of loops over the queue, about -0.35 KB); balancing irom_lo / irom_hi (placement only).

**Step F4 (2026-10-23; measured, fwbuild s1, pocket88k, function sizes
from main.dis, against F3's head of 2026-10-23 built the same way): the synth's fields and the main-loop pass.**
- `core/sched/s5_mirror.c` (the engine's fields to and from region 0x06: s5_mirror_out 2,276, put 612, s5_mirror_in
  524, s5_mirror_pass_in 184, s5_mirror_prime 12): 3,608 B TEST (3,676 RELEASE) at -O2, placed in the WRAM code window
  (pocket88k.json wcode_text: a TCM, a tightly coupled memory, like the IROM on test build 4, no fetch penalty), whose
  free bytes go 6,912 -> 3,304 TEST and 7,552 -> 3,872 RELEASE; its shadow of what the synth holds, ~1 KB, in wram_upper
  (free 3,036 -> 2,016 TEST, 5,420 -> 4,412 RELEASE); wram_data -48 / -32 B.
- IROM, TEST (RELEASE): -1,460 B (-1,328), free 3,180 -> 1,720 (irom_lo 384 + irom_hi 1,336; RELEASE 7,684 -> 6,356:
  3,412 + 2,944): the pass's wiring 728 (528: board_pass_bracket 372 (236) with its second STATUS read and
  re-read, board_item_pass 164, ctrl_bit 68 for CTRL.BLKIE, sched_pass_post 32, disp_s5_jobs, disp_s5_pass,
  song_q_depth 28 each, board_synth_put 8), L1 / L2b / sched_init +388 (+440), board_blkcnt +16 (the pass's
  snapshot), the chip's pass code now linked 564 (song_main_pass 204, the Boom Box feed 360: written in an earlier song-engine step, unreferenced
  until now, so the linker had dropped them), +20 elsewhere (board_synth_begin, l3_job, sfx_table_init,
  song_run_one); out: the 0.2.6 8C unpack in job_unpack -108 (-88), the interim boot writes -56 and their hooks
  (ppm_bgm_addr, s1_board_vol, s1_board_sfx) -80, brd_full_reset -12, brd_boot -4, +4 of alignment (TEST).
- Against the plan (the bytes, then trim or rebudget): the field mirror is no plan row (section 4's draft
  wrote the synth's fields nowhere), so its 3,608 B of code and ~1 KB of state are over
  the plan by all of it; the pass's wiring and its L1 / L2b part (1,132 B TEST) go on the glue row (estimated 350 / 625
  / 900), which is then 3,068 B TEST net, +2.4 KB on its centre; the 564 B of the chip's pass code are the engine
  row's (its 15,658 B were measured on the linked image, without them). Rebudget, no trim: the mirror sits in the
  code window (the reserve named above), so the IROM pays 1,460 B, and TEST keeps 1,720 B of IROM after F1-F4. The
  next levers, in order, if test build 5's TEST image runs short: cold song code to the code window (the 88 and 8C
  bodies, song_cfg, song_c6.c's 2,100 B: 3,304 B free there), the mirror at -Os (about -1.5 KB, estimated; the rig at
  test build 4's prices prices it at -O2), song_oeq.c's walks as running values (about -0.35 KB).

**Test build 5 (2026-10-23; measured, fwbuild s1, pocket88k): the boot cache, the curve, DTOUT and TEST's
debug save version 9 in the stage-5 images.** Against the F4 images above (TEST / RELEASE):
- the boot-cache stub (boot/boot_cache.c, -Os) after the brain (irom_hi), crt0's FEAT check of test build 5, DTOUT at
  boot, `brd_bank_ok`, the TEST counts in core/sched/s5_glue.c and core/song/song_oeq.c (TEST only), and the debug
  save's version 9 (dbgsave.c, -Os) with test build 4b's record writer (s1_cache4b.c) in the WRAM code window: s5test
  IROM free 1,720 -> 500 B (irom_lo 208, irom_hi 292), code window 3,304 -> 132 B, wram_upper 2,016 -> 1,320 B;
  s5release IROM 6,356 -> 5,736 B (irom_lo 3,332, irom_hi 2,404), code window 3,872 -> 3,864 B. C6 (song_c6.c) stays in
  irom_lo where the F4 timing run measured it. The first try (song_c6.c to the code window, the debug save after the
  brain) overflowed irom_hi by 2,304 B: song_c6.c was irom_lo's.
- the boot overlay with the synth's curve (c5_curve.h's 488 B of steps): 15,840 of 16,384 B (544 free; test build 4b's
  15,124).
- TEST is now the tight image (500 B of IROM, 132 B of window; its stack bound 3,572 of 5,120 B, F4 2,516).
- test build 5's repair: SONG_FRAME_PAD16 (brain hygiene: 16 B of frame in l2b_msi (RELEASE),
  song_c6_ready, the module start, s5_mirror_out and prev_take (TEST)) changes no size; TEST's A1X bit and the debug
  save's counter-11 fold take 20 B of window: s5test code window 132 -> 112 B (IROM 500 B as above), stack bound
  3,572 B unchanged; s5release stack bound 2,404 -> 2,436 B (the pads on its deepest path), every size unchanged.
- test build 5's second repair: A1 = WBUSY > DONE_WBUSY + JOB_WBUSY again and the A1X
  bit gone: s5test code window 112 -> 120 B (IROM 500 B, wram_upper 1,320 B, stack bound 3,572 B unchanged); s5release
  byte-identical.
- test build 5's third repair: A1's excused count is labelled "module starts + C6
  items" (comments, the reader, a host test, planted bug SONG_BUG 39): s5test, s5release and both twins byte-identical
  to repair 2's, every size unchanged.
  The levers left, in order: the field mirror
  (s5_mirror.c, 3,608 B of window at -O2) at -Os (about -1.5 KB of window, estimated; the rig at test build 4's prices
  would price it again), song_oeq.c's walks as running values (about -0.35 KB), cold song code (song_cfg, the 88 and 8C
  bodies) to the window once the mirror shrinks.
- stage 2, step 1 (2026-10-27, the room plan): F5's past-row-127 window steps its rows in integers that are
  the IEEE single sums exactly (interim/s1/f5_s1.c f5_round24, bgBC tC), so libgcc's soft float (3,812 B) leaves
  both images: f5_s1.c +100 B irom (the stage-1 row's cap 912 -> 1,012, rebudgeted); s5test IROM free 500 ->
  4,208 B, s5release 5,736 -> 9,444 B; window, WRAM and stack bound unchanged. Its 4 B float constant leaves the
  small data too, so gp moves and a few lui / addi pairs relax differently (s5 images: the SFX start +4 B; the stage-1
  TEST image: ppm_obj_render +12 B, the sprite row's cap 4,052 -> 4,064).
- stage 2, steps 2b-2d (2026-10-27, the room plan's path B): the new sprite engine (core/sprite, which does what the cart's chip does) replaces
  0.2.6's in every stage-1 and stage-5 image. Two new rows (the caps are the measured stage-1 TEST
  figures): "stage 2: sprite engine (chip copy)" 5,480 TEST / 5,300 RELEASE irom, 2,944 / 2,932 wram (on the stage-1
  interim images its state and the 768 B index sit in wram_upper: their wram_data holds the interim audio), and
  "stage 2: sparse block->id index" 244 irom; the dispatcher +20 B (D48), the interim bodies' wram +3 B (the rate word
  of the 50 Hz skip); the two 0.2.6 sprite rows measure 0 there. The card images (pocket88k, no budget): s5test IROM
  free 4,208 -> 4,268 B (the 0.2.6 TEST engine it replaces was the larger), s5release 9,444 -> 9,180 B; wram_data free
  TEST 672 -> 256 B, RELEASE 1,040 -> 576 B; wram_upper TEST 1,320 -> 552 B (the index); wram_sched gains the flush
  list (64 B) where 0.2.6's lists were; the window and the stack bound unchanged.
- test build S3c (2026-10-27, merged 2026-10-28): the Console Reset's warm vector page (core/boot/bootpage.c
  boot_warm_page, 64 B) and its call in l1_mei (+4 B), 68 B of IROM in all, stage-5 images only: s5test IROM free
  4,268 -> 4,200 B, s5release 9,180 -> 9,112 B (measured); the window, WRAM and the stack bound unchanged; the stage-1
  images byte-identical.
- test build S3a, step 0 (the room plan's decision 3): the stage-5 TEST images drop 0.2.6's SAT snapshot diagnostic
  (interim/s1/appmain.h: PPM_SAT_SNAPSHOT 0 with FW_S5; the stage-1 TEST image keeps it for its rigs): s5test IROM free
  4,200 -> 6,480 B (irom_lo 3,168 -> 5,224, irom_hi 1,032 -> 1,256), wram_data 256 -> 400 B, wram_sched 224 -> 256 B,
  code window 136 -> 132 B, the stack bound unchanged (measured): mame.c -2,075 B, the bodies -364 B, +164 B elsewhere
  where the small data moved under gp (disp.c +116, jobs.c +24, wdog.c / event.c +8, appinit.c +4; the debug save's
  window +4). The room plan's +2,724 B was measured on test build 5's tree, before stage 2 took out the snapshot's half
  in the 0.2.6 sprite engine. s5release and the stage-1 images are byte-identical.
- test build S3a, step 3a (the room plan's zoom row): the cart chip's zoom (core/zoom: job 8's save of RAMDP $0200-$09FF
  and the stamps' set-up, F5's integer rescale with both 32-byte column copies written out (decision 4's default) and
  its copy-out, B6's restore; the buffers in the chip's order) replaces interim/s1/f5_s1.c in every stage-1 and stage-5
  image (measured): zoom.c 2,148 B irom (the rescale 1,632), f5_s1.c -1,012, the bodies -12..-20, the job step +4
  (+12 in the stage-1 RELEASE image: relaxation); s5test IROM free 6,480 -> 5,360 B (irom_lo 4,088, irom_hi 1,272),
  s5release 9,112 -> 7,992 B; stage-1 test 4,796 -> 3,668 B, release 12,860 -> 11,728 B; WRAM unchanged (the 2 KB
  stamps where mame.c's 2 KB F4 buffer was, the 4 KB source + save where f5_s1.c's 4 KB work buffer was), the window
  and the stack bound unchanged. The room plan's estimate of -476 B for this row was based on the loop count of an
  F5 that kept the soft float; the chip's shape costs +1,120 B here.
- test build S3a, step 3b (the room plan's unpack row): on the stage-5 images the DA / F4 jobs and C6's three containers
  decode through the cart chip's own decoders (core/song's song_unpack80 / 81, already in those images for the song
  engine), so mame.c's ppm_unpack_scal (0.2.6's 0x80 decoder and the LZO port) leaves them (measured): mame.c -1,240 B,
  the bodies +156 TEST / +116 RELEASE (s5_unpack, the swap, the set-up adapter), zoom.c -80 (zoom_f4_order unlinked):
  s5test IROM free 5,360 -> 6,524 B, s5release 7,992 -> 9,196 B; the stage-1 images unchanged (they keep 0.2.6's
  decoder). The room plan's -972..-992 B was estimated on a second copy of the decoders.
- test build S3a, step 3b's word-wide SDRAM lever (the room plan's S3-16): the DA job's and C6's halfword swap (the
  chip's type-3 tail, bodies_s1.c s5_rev16) swaps two halfwords per 32-bit SDRAM word, the same bytes; s5_rev16 and
  s5_unpack stay out of line (measured): the bodies +108 B TEST / +92 B RELEASE; s5test IROM free 6,484 -> 6,376 B
  (irom_hi 1,116 -> 1,008), s5release 9,156 -> 9,064 B; WRAM, the window and the stack bound unchanged; the stage-1
  images byte-identical. The room plan allowed 0 / +150 / +300 B for S3-16.
- test build S3a, the TEST trim (the debug save cut to the lateness signs, the freeze telemetry and the CPU MATE
  counters, version 10; core/trace/tdiag.h TDIAG_LEAN): s5test and its twins only; s5release and the stage-1 images
  byte-identical (measured): s5test IROM free 6,376 -> 8,644 B (irom_lo 5,368 -> 5,896, irom_hi 1,008 -> 2,748), the
  code window 132 -> 1,864 B, wram_data 400 -> 512 B, wram_upper 552 -> 3,316 B, the stack bound 3,572 -> 2,468 B.
  IROM: stats.c -604 (the level counters, milestones, latency; the frame ticks and the last post stay as two inline
  stores), s5_glue.c -596 (the synth's TEST assertions and the pass counts), spr_compose.c -180, s1_board.c -164
  (the milestones), bodies_s1.c -156, fatal.c -116 (the poll count; the halt's record stays), s1_freg.c -108 (the
  register-write oracle), jobs.c -100 (C6's hold record), song_oeq.c -68, wdog.c -68, wheel.c -64, disp.c -32,
  status.c -24, event.c -12, sched.c +24 (L1's post path now inlined as in RELEASE, plus l2b_msi's 16 B frame pad,
  RELEASE's brain hygiene); window: dbgsave.c 2,688 -> 1,890, the CPU MATE glue 2,424 -> 1,904, the boot cache's
  record writer 484 -> 0, s5_mirror.c +68 (RELEASE's size).
- test build S3a, step 3c (the room plan's 83 row): 83's frame-period check as the cart chip does it
  (core/dispatch/disp.c disp_83_check, the stage-5 images only): disp.c +200 B in both images (measured): s5test IROM
  free 8,644 -> 8,444 B (irom_hi 2,748 -> 2,548), s5release 9,064 -> 8,864 B; WRAM, the window and the stack bound
  unchanged; the stage-1 images byte-identical. The room plan's row was +272 B.
- test build S3a, step 3d (the room plan's C6 sprite row): C6's sprite part as the cart chip's (the sprite init
  0x08019734 with its anim set-up 0x080195E0: only the anim container decoded, its whole 512 KB swapped, the counts; the
  stage-5 images only): 0.2.6's ppm_setup_data leaves them with its two other decodes (the song engine's audio init
  decodes its own) and its 512 B count table (measured): s5test IROM free 8,444 -> 8,720 B (irom_lo 5,896 -> 6,220),
  s5release 8,864 -> 9,140 B; wram_data 496 -> 1,056 B (TEST), 560 -> 1,120 B (RELEASE); the window and the stack
  bound unchanged; the stage-1 images byte-identical. The room plan's row was +248-252 B (estimated).
- test build S3a, step 3e (the room plan's saves row): the saves in the cart's own format (the chip's read and write
  jobs and their validator, the slot table read from the player's ROM at the boot, the one-time 0.2.x import;
  interim/s1/ bodies_s1.c, the stage-5 images only), measured: s5test IROM free 8,720 -> 6,508 B (irom_hi 2,500 -> 288),
  s5release 9,140 -> 6,928 B (2,212 B each); wram_data 1,056 -> 864 B (TEST), 1,120 -> 928 B (RELEASE): the table's
  192 B; the scratch is the zoom stamps, as on the chip; the window and the stack bound unchanged; the stage-1 images
  byte-identical. The room plan's row was +1,956 B (D30 at -O2) + 396 B (the import) = 2,352 B. Time (the rig's
  test build 4's pricing, estimated): the boot's table load ~136 ms (the cart program's 196,608 B unpacked into the
  workspace, the 68000 still held); DF 0.1-1.6 ms, E0 0.3-1.9 ms a job.
- stage 3, test build S3b (2026-10-27 / 28, step 4 of the room plan: the cart's MegaWire code with no module, from the
  SRAM image). The s5 images have no module budget (`budget: null`, above), so this is a report of the bytes, not a
  gate; the linker regions, the stack bound and the code window stay the hard limits. Measured (objects.txt and
  layout.txt, the no-brain images; IROM = code + rodata + the .data image), test build 5 (2026-10-27) -> the port:

  | object | what | TEST IROM | RELEASE IROM |
  |---|---|---|---|
  | core/mw/mw_res.c | the init's interrupts-off block and the E7 / A9 / A6 bodies, resident (from SRAM the block held interrupts off ~3k cycles: test build 5's packet margin -58 us in the rig) | +492 | +492 |
  | board/pocket/s3_sram.c | the SRAM image check: header, link id, the hot part's CRC-32, the cold part's, the XCFG lock | +396 | +396 |
  | board/pocket/boot/boot_cache.c | the image's CRC-32 in whole words with a 16-entry table (64 B), the same result as bytewise | +152 | +152 |
  | core/mw/mw_boot.c | the thread's first work after the 68000's release: the check, then the port runs only when the image passed; the MegaWire RAM, the screen's, the text's and the task's step state cleared; the resident task step, multiplex count and screen flags | +172 | +172 |
  | core/dispatch/disp.c | the MegaWire gates of A4 / A6 / A8 / A9 / AA / E7 beside test build 5's own paths (kept for a missing or refused image); an accepted A858 sets the resident screen flag | +284 | +284 |
  | core/dispatch/jobs.c | the EEPROM job step of the MegaWire record (slot 9: MW+0xC := 1 on a good read) | +88 | +96 |
  | core/sched/sched.c | the image check as the thread's first step; the task in the thread, once per counted TIM7 tick, one of the chip's steps a thread step, none starting while the game's sprite frame is open (for up to 33.4 ms) or a post waits (the check again with the interrupts off, the step entered with them off); the A858 screen's steps once due; the idle path reads only resident state | +488 | +484 |
  | core/wdog/wdog.c | L2a counts the TIM7 ticks | +16 | +16 |
  | interim/s1/bodies_s1.c | the C6 body's MegaWire init | +36 | +36 |
  | core/song/song_tables.c | song_note_tail: our server name, 17 B (B51); not in the merged tree below | +5 | +5 |
  | core/boot/bootpage.c | boot_mw_status() no longer called with the port | -32 | -32 |
  | board/pocket/s1_board.c | brd_md_hold out of line for the A858 screen's call (it was only inlined at boot before); the boot no longer calls the image check | +44 | +44 |
  | total (objects) | | +2,141 | +2,145 |

  With the A858 screen, the cart program's text unpacked from the player's ROM, page A, task states 4 and 6, the
  image's hot / cold split and the word CRC, the image check after the 68000's release, and the task run one of the
  chip's steps at a time with the sprite wait; the new code is in the SRAM image (the screen in its cold part). IROM
  free (layout.txt, irom_lo + irom_hi): TEST 4,208 -> 2,064 B, RELEASE 9,444 -> 7,296 B. The room plan estimated +540-820 B
  for its steps 4.2 and 4.4 (the slot check +120-300, the resident gates and bodies +420-520): the check came out at
  720 B (s3_sram.c, boot_cache.c's word CRC, mw_boot.c) and the resident part at 1,421-1,425 B (the thread's sprite
  wait and step calls among them), because test build 5's paths stay beside the cart's (a refused image must run test
  build 5's MegaWire) and the init block and the three bodies are resident (the rig measured what they cost from SRAM).
  The SRAM image (not IROM): TEST 64 + 10,424 B (hot part to 0x1444: the task, the driver step, the information block,
  core/mw/mw_task.c, mw_drv.c; cold part: core/mw/mw_screen.c, mw_text.c, mw_page_a.c), RELEASE 64 + 9,928 B (hot to
  0x1250). Its RAM .sram_bss 19,608 B at SRAM 0x18C00-0x1D897 (the task's step state and the information block's
  buffer 112 B, TEST counters 12 B, the MegaWire blocks 14,532 B, the two packed pages, the screen's and the text's
  state). The cart program's text: 196,608 B in CRAM MWTEXT (0x1B0000), rebuilt from the ROM on the Pocket, never in an
  image. Against test build 5: wram_data free TEST 672 -> 656 B, RELEASE 1,040 -> 1,024 B (the screen's and the sprite
  wait's state); the code window, wram_sched and wram_upper unchanged; the stack
  bound TEST 3,572 B (=), RELEASE 2,436 -> 2,468 B (of 5,120).
- The MegaWire port merged onto the cart-chip zoom, unpack, C6, save and level-table work (2026-10-31; the merge keeps
  both sides: the C6 job's MegaWire init sits after the chip's own C6 sprite part, the note table's 12-byte tail stays the
  chip's own bytes read from the player's ROM, so the 17-byte server-name copy above is not in this tree, and the
  MegaWire init's slot-9 read lands in the MegaWire record). Measured (layout.txt, the no-brain images; IROM = irom_lo +
  irom_hi free), before -> after the merge:

  | image | IROM free | irom_lo | irom_hi | code window | wram_data | wram_sched | wram_upper | stack bound (of 5,120) |
  |---|---|---|---|---|---|---|---|---|
  | s5test | 5,864 -> 3,648 B | 4,784 -> 2,816 | 1,080 -> 832 | 1,864 = | 864 -> 848 | 256 = | 2,280 = | 2,468 -> 2,500 |
  | s5release | 6,284 -> 4,068 B | 5,084 -> 3,156 | 1,200 -> 912 | 3,864 = | 928 -> 896 | 256 = | 2,608 = | 2,436 -> 2,468 |

  The merge costs 2,216 B of IROM in each image and no region overflows, so no code was moved between irom_lo and
  irom_hi. The SRAM image: TEST 10,500 B, RELEASE 9,992 B (64 B header + .sram_text); its RAM (.sram_bss) 19,608 B at SRAM
  0x18C00. The stage-1 images are byte-identical to before the merge.
- Our own 0x81 decoder, the MegaWire code using it, and the firmware file (2026-10-31). `core/song/unpack81.c`
  replaces the 0x81 decoder that sat in `core/song/song_c6.c` (the "0x81 (LZO) decoder 724 B" in the note above on
  C6's code is that old one), and the MegaWire text unpack in `core/mw/mw_text.c` now calls the same decoder instead
  of carrying its own. Measured (main.nm of the no-brain s5release image): the old song_unpack81 724 B +
  song_unpack81_to 808 B = 1,532 B; the new song_unpack81 608 B + song_unpack81_to 112 B + their shared limited body
  760 B = 1,480 B, no read-only data; the checked entry unpack81_checked (36 B) links in once the MegaWire code calls
  it; mw_text_run 1,080 -> 176 B. With the firmware
  in its own file, the SRAM image comes inside that file and the image check no longer reads the APF loader's counts
  (board/pocket/s3_sram.c): 36 B less code. IROM free (layout.txt, irom_lo + irom_hi; the brain and no-brain images
  alike) and the SRAM image:

  | image | IROM free: before -> the decoder -> the MegaWire code on it -> the image check | irom_lo | irom_hi | SRAM image (64 B header + .sram_text) |
  |---|---|---|---|---|
  | s5test | 3,648 -> 3,700 -> 3,664 -> 3,700 B | 2,816 -> 2,868 -> 2,832 -> 2,868 | 832 = | 10,500 -> 9,568 B |
  | s5release | 4,068 -> 4,120 -> 4,084 -> 4,120 B | 3,156 -> 3,208 -> 3,172 -> 3,208 | 912 = | 9,992 -> 9,060 B |

  The code window, wram_data, wram_sched, wram_upper, .sram_bss (19,608 B) and the stack bound (2,500 / 2,468 B of
  5,120) do not change, and the 72 KB-layout images (pocket72k) stay byte-identical.
