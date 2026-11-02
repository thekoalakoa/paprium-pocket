# Stage-1 firmware: levels, command map, invariants

What the stage-1 firmware is, in one place: the four interrupt levels and what runs on each, where every command the
game can post goes, and the rules the code keeps (with the test that checks each). Work item W15 of
`docs/STAGE1_PLAN.md`; written 2026-10-13 from the code of that day and the results of the first full-system
simulation and its review. Stage 1 is the new-core stage of the 0.3.0 work, after stage 0's skeleton (the s1 source set
of `tools/fwbuild.py`, built with `FW_S1`); stage 2 is the sprite engine, stage 3 the unpackers, zoom, saves and
MegaWire, stage 5 the song engine. Companions:
`docs/MCU_INTERFACE.md` (the hardware it runs on), `docs/BOOT_SPEC.md` (power-on and reset), `docs/CART_FPGA_SPEC.md`
(the cart registers), `docs/ALLOWLIST.md` (what may differ from the chip), the READMEs in `core/*/`, `interim/`,
`buddy/` and `board/pocket/` (each module's own proofs).

**How numbers are known.** Measured = read from a build, a run or a capture; estimated = worked out from measured
numbers; not known = nobody knows. "(verified)" = checked in code or a run, "(read only, not run)" = code read only,
"(inferred)" = inferred. A co-sim is a simulation of the core's RTL running the firmware; the RV32 rig is our RV32
model of the board that runs the firmware images on recorded play (tests/equiv/rvboard.py and rtlmodel.py; its timed
form on the priced clock, `tr_rig.py`, is not in this tree). The MCU is the cart's NEORV32
soft CPU in the core; RAMDP is the cart RAM both the 68000 and the cart chip see; L1, L2a, L2b, L2c and L3 are the
firmware's interrupt levels (section 1). Dates name the changes made on those days; the hardware test cards are the
test builds B Jam ran on the Pocket, numbered in order. D numbers (D02, D23, ...) name the differences between the
0.2.6 firmware and the cart's chip that our study of the cart listed.

---

## 0. Findings first

1. **Stage 1 is the cart chip's dispatcher with 0.2.6's effects behind it.** The mailbox entry, both 55-entry command
   tables, every gate and refusal, the status layer, the 16-slot job queue, C6, 81 / 82 / 84 / 85, the watchdog,
   the heartbeat and the fatal halt do what the chip program does (verified: the chip comparison on 81 of 81 posts, the
   watchdog lockstep over 2 x 262,434 events, 0 differences). What each accepted command *does* (sprites, unpacking, saves, album, sound
   effects) is still 0.2.6's code, re-hosted per command (`interim/s1/`). Later stages swap those bodies for the
   chip's, one subsystem at a time, without touching the dispatcher.
2. **It boots and plays in the full-system simulation** (the first full-system simulation and its review, measured): power-on to the
   title, the main menu, a new game and gameplay on the stage-1 RTL with these images; 7,555 posts, 1,492 streams,
   0 MCU exceptions, 0 streams cut short, window-range reads against the ROM 0 mismatches, every Soft Reset type
   released with the right state.
3. **L1 ran much longer than the plan assumed** (measured, system co-sim, images of 2026-10-13): up to
   8.3-8.5 ms for an AD post (0.2.6 decoded the sprite blocks inside the post), against the 0.32 ms the specs planned
   (docs/CART_FPGA_SPEC.md section 6, docs/MCU_INTERFACE.md section 6.2). The co-sim's "3.5 ms for D1" and "3.1 ms for B6" were AD bodies served in the
   same L1 entry (it credits an entry to its first post; D1 alone 213 us). Nothing failed from it on the paths run: the
   busy bit is RTL, F5 finished in time (0 late of 45), the first-boot 84 came 8 frames after the last post. **The 2026-10-13 change:** the sprite-block decodes and TEST's SAT snapshot run in the board's stand-in (WH_DEC, L2a); AD is the
   0.2.6 compose alone, at most 1.16 / 1.30 ms RELEASE / TEST in the RV32 model (~1.4-1.6 ms at the hardware CPI), and
   stays in L1 (the game writes the object's record right after the post); every other body <= 0.24 ms (FZ12).
   **The first 2026-10-14 change:** the stand-in moved again, below the CPU MATE brain call (L2c, section 1): on the wheel it ran above
   the call, and the W14 co-sim showed calls waiting up to 8 ms for it and the game reading a stale CPU MATE word or
   busy bit in 9 calls of 752 (finding 6).
4. **One fault was found and fixed in this stage by the simulation:** F5 (the zoom rescale) ran 0.2.6's soft-float
   body and missed the next VBlank 4 times in 25 (fixed 2026-10-12: fixed point, word-wise, same bytes; then 0 of 45).
5. **The 68000 sees only what the chip's code writes,** through the register file the RTL keeps (`$1FE4/6/A/C`
   stored; `$1FE8`, `$1FEE`, `$1FF2` act on write). The firmware never writes the RAMDP words under `$1FE0-$1FFF`
   (`tests/check_tree.py` rule 5).
6. **CPU MATE answers (W14 co-sim, measured; fixed in the first 2026-10-14 change).** The co-sim (TEST + brain, 752 calls in play,
   frames 2600-3370) found the brain call waiting in L2a behind the decoder stand-in and TEST's SAT snapshot (the
   SEND comes 389-460 us after AF, while the frame's decode runs): 422 words armed after the original's release
   instant (the link's LATE), up to 8 ms; from frame 3236 a running call was also held by the decoder each time an AD
   queued blocks (109 ms once) and the game read before the ARM in 8 calls, seeing a stale word or busy bit in 9. The
   original's CPU MATE never waits: it runs on the Mega CD's sub-CPU (interrupts off, a call within one 98-cycle
   pass of its spin loop) and the cart's FPGA decodes the blocks. The first 2026-10-14 change runs the stand-in (and TEST's debug save)
   as L2c, below the brain call (section 1; interim/README "The decoder below the brain call" has the RV32 rig's
   before / after numbers): no brain call waits for a decode. **The second 2026-10-14 change:** what was left (the interim SFX feeder's
   133.5 us ticks preempting the call) goes too: the call holds the feeder's wheel slot from the brain post to its
   end, as the sub-CPU runs a call with every interrupt off, and the feeder catches up from its 256-sample FIFOs
   (10.7 ms at 24 kHz, the bank's fastest rate). The chip's own SFX mixer period was checked first (2,085 us, 160-sample
   blocks into a 20 ms DMA half) - not the first 2026-10-14 change's 534 us option,
   which is not taken. RV32 rig (estimated board, the brain's real code): word ARMs late 9-22 of ~2,450 per run (L2c
   alone 93-520), the latest 0.13-0.92 ms, 0 stale game reads in all six runs, SFX underruns 0 (interim/README "The
   brain call holds the SFX feeder"). **Turned round in the 2026-10-15 change (finding 7).**
7. **The 2026-10-15 change: the game's own work first (B Jam's decision of 2026-10-15).** On test build 2 (the second
   2026-10-14 change) the game slowed, sound effects with it, in busy fights with CPU MATE: the game's late-frame check
   (ROM `$33256`, the VDP line right after AF's reply, line 176 or later = skip the frame's phase work) fired far more
   often than the cart's at-once reply allows, because AF's reply waits for the frame's block decode and a brain call
   sat in front of it (a pose study and a co-sim of 2026-10-15).
   B Jam's rule: the CPU buddy, which the game does not use all the time, must not slow the rest down; cart accuracy
   over being right. So the brain call is the thread's now, below L1, the wheel, the decoder stand-in and the jobs
   (section 1), and TEST's diagnostics sit below the call. AF keeps its finish after its decode: after the reply the
   game reads nothing of the cart's before its VBlank DMA reads the window but `$1FEA` bit 15 at `$33428`, which no post
   holds (measured: ROM; 0 posts after AF in 2,932 co-sim frames), so the chip's at-once reply could only be made safe
   with a firmware decoder by a time argument; what remained of the late frames was the decode itself, so the decoder
   stand-in got faster (the same bytes) and keeps the blocks it decoded (the block memo, which that side branch proposed
   as allow-list row B37, a row docs/ALLOWLIST.md does not have: a block the game asks for again is a copy). Numbers,
   method and costs: interim/README "The CPU MATE brain call takes the time that is left". RV32 rig on the priced clock
   (estimated), test build 2 -> this commit, the cart model 1 in each: late passes 15 -> 2 / 10 -> 1 (solo TEST /
   RELEASE), 5 -> 2 (stage 04), 123 -> 37 (Arcade 3P), 135 -> 41 (Arena), 78 -> 28 (Arcade 3P RELEASE), 215 -> 101 (duo,
   cart 12); 0 DMA reads of an unfinished decode, 0 SFX underruns.
   What is left is decode (and the SFX feeder between the requests) at AF's reply in the Arcade 3P / Arena stage start
   and duo: the cart's count needs the decode off the reply (B Jam's hardware test, or the decoder in logic). (Those
   numbers are the side branch of 2026-10-15's, with its faster firmware decoder and block memo; the decoder-in-logic
   change took its levels, not its decoder.)
8. **The decoder-in-logic change: the decoder in logic, AF replies at once (B Jam's decision of 2026-10-15: "preservation": the chip's at-once reply,
   sprites already done, never wait).** The cart's chip never waits for its FPGA's decoder (no read of `$1FF0-$1FF6`, no
   decode-done interrupt: the first finding of our decoder spec, not in this tree). MCU interface v1.2 (PROPOSED) puts
   that decoder and its queue in our RTL (`paprium_hwdec`), and the firmware does what the chip does, step for step: the
   flush pushes the frame's load list
   last to first (`flush_regs`), F2 its block twice, DA06 / DA07 their 0x80 stream, one board write of the decoder's
   output base before each START, and AF / B1 / F2 / DA06 / DA07 finish at once. The firmware decoder stand-in, its
   board work, the deferred finish and the firmware queue are gone; `ppm_unpack` stays for the chip's own decodes (DA02
   and the 0x81 / 0x82 DA07 jobs, C6, F4). The pushes equal the chip's write for write (chiplock_s1 W13: the T-S2
   transform is gone). docs/ALLOWLIST.md, row B38 (proposed) replaces row B1. AF's frame end leaves out 0.2.6's slot-age pass, which
   nothing reads with the chip's cache lists (AF reply 134 -> 72 us mean). Results in interim/README "The decoder
   in logic" (RV32 rig, priced clock, estimated; test build 2 -> the side branch of 2026-10-15 -> this, the cart model
   in brackets): late passes 15 -> 2 -> 1 (1) / 10 -> 1 -> 1 (1) (solo with CPU MATE, TEST / RELEASE), 5 -> 2 -> 1 (1)
   (stage 04), 123 -> 37 -> 2 (1) (Arcade 3P), 135 -> 41 -> 2 (1) (Arena), 78 -> 28 -> 2 (1) (Arcade 3P RELEASE), 215 ->
   101 -> 30 (12) (duo), 300 -> 226 -> 62 (21) (attract); 0 window words read early, 0 decoder aborts, 0 SFX underruns.
   Every late pass left over the cart model is the 68000's wait on the posts before AF (the AD composes of 0.2.6's
   sprite engine), not AF's reply and not the decode: the cart's count there needs stage 2's sprite engine.
9. **The sprite-values update: the sprite values the game reads as data are the chip's** (B Jam's decision of 2026-10-15/16, pulled forward
   from stage 2; our spec of the sprite values, not in this tree). The game decides on three sprite-engine words: `$1F18`
   (the SAT count: 80+ entries arm its effect gate `$FF99A6`, ROM `$33088`, whose readers skip effect spawns and two
   random-number draws), `$1F1C` (the multiplex flag, `$33AEE`: the mid-screen stash copy and one gate decrement less)
   and `$1F1A` (the ready flag, already the chip's since 0.2.6 final, D18). Stage 1 now does the chip's clip rule D24
   (`legacy/026/mame.c` `ppm_obj_render`, `PPM_CHIP_CLIP`: X only, `$61..$1BF`, Y never tested, X / Y stored unmasked,
   so pieces above or below the screen count as on the cart) and the chip's whole AF frame end `0x080190B8` (D10 and the
   rest of D42, `PPM_CHIP_AF_END`: modes 0-2, the second 14-entry DMA, the `$1F20` stash, `$1F1C`; 80+ tables multiplex
   and rotate their overflow in on alternate frames: the cart's flicker), its open-frame gate D38 (`core/dispatch`
   `f_af`: an AF no AE opened only finishes) and the multiplex parity H+$403 (`disp_g.af_parity`, +1 at AE, accepted B0
   / F0 and the first C6's sprite init). AF03 above 80 entries is not done the chip's way (the chip writes through a register that
   path never set; the game posts AF02 / AF01 only). docs/ALLOWLIST.md, row B14, shrinks to D19, D23, D39, D47-D49. Proof (measured):
   `sprval.py` (the spec's replay, the cart program against the stage-1 RELEASE host build, open loop) on solo, duo,
   attract, Arcade 3P, stage 04 and first boot: 0 differences in `$1F18` / `$1F1A` / `$1F1C` after 918,241 ADs and
   200,948 AFs, the 80+ decision equal on every AF (solo 11, duo 131), the 122 multiplexed frames (`$1F1C` = 1: solo 8,
   duo 114) equal, the effect-gate model equal on every pass; the full AF write (SAT entries 0-129 Y / link / X, the
   stash, the descriptors, `$1F10`, `$1F16`) equal but for SAT entry 0 with an empty table (the boot page, and 25 AFs
   where 0.2.6's B1 clear of entry 0 shows: D47, B14). The chip lockstep holds the words to the chip on every corpus
   (tests/equiv/README "The sprite-values update": 1,148,167 ADs and 240,063 AFs, PASS) plus an AF unit check of every count
   0-140 x mode x parity on synthetic tables (1,008 cases, 0 differences); four planted bugs (0.2.6's clip, `$1F1C`
   never written, B0 not counted in the parity, the stash from entries 0-13) each fail it. Cost (measured): +696 / +736
   B of IROM (RELEASE / TEST; free IROM 10,484 -> 9,788 / 3,380 -> 2,644 B), +2 B of WRAM, the stack bound unchanged.
   MCU time: the chip's close does more RAMDP work than 0.2.6's (two descriptors and the 28-word stash at 9 clocks an
   access, in AF's L1 before the reply), so the update gives time back in the same engine: the compose writes each SAT
   entry as two word stores and reads `$1F18` and the record's attribute word once (about 45 clocks less an entry); the
   close's descriptors, overflow move and stash are word-wide; and, as the decoder-in-logic change did for AF's age pass, AE's 64-slot
   usage clear and the per-hit usage / age marks are left out (nothing reads them with the chip's cache lists). All of
   it writes the same bytes in the same places. Time (RV32 rig on the priced clock, estimated; the 13 usable corpora of
   the decoder-in-logic change against the base build (the decoder-in-logic merge of 2026-10-17, before these
   updates), the plain Arena capture faulting at its frame 282 on both as before): late passes equal on
   12 corpora (sw05 TEST / RELEASE 1 / 1, ex17 1, mp3_01r7 2, arena3r7 2, mp3_1Ew 2, stage 04 1, Arcade 3P 2, solo TEST
   / RELEASE 13 / 12, duo TEST / RELEASE 30 / 28; the cart model's 1-12 as before), and one more on attract (TEST,
   frames 7,000-9,000: 62 -> 63): frame 8380, which the base build finished 9.1 us before the 13.03 ms check, now ends 0.1 us
   after it. That frame's waits before AF are not sprite work (they barely move, -2 us), and its AF reply is 11.4 us
   longer (65.7 -> 77.1 us; the stash and DMA 2 alone are some 60 RAMDP accesses, about 10 us), so it has nothing to
   give back: OPEN, the update's one timing regression (a faster AF register path or test build 4's fast path removes
   it). On average the 68000 reaches AF 18-27 us earlier, AF's reply is 18-20 us longer and it ends 0.5-9 us earlier
   than on the base build (per-frame scatter about 40 us); SFX underruns 0; decoder words read early 0; AF's L1 body at
   most 115-224 us (inside the 0.32 ms budget; FZ12 passes); the longest L1 and interrupts-off section 14 us shorter; L1
   bodies over 0.32 ms fewer on every corpus (duo TEST 2,328 -> 1,690); lag VBlanks equal but for Arcade 3P stage loads
   (mp3_01r7 4 -> 5, arena3r7 5 -> 4, arc3p 57 -> 58). Controls: the rig is deterministic (a rerun of the base build
   gives its numbers from the decoder-in-logic change's runs on all 13), and the same base build with 2 us added to AF's
   close and nothing else changed already moves two: duo TEST 30 -> 31 and attract 62 -> 64 (8380 one of the two), the
   other 11 equal. A further build (a leaf close path, about 2 us less a reply) kept 8380 late and tipped two more (duo
   3570 in the character select, Arcade 3P 2197); it was not kept.
   Hardware check (spec T6, B Jam ~20 min side by side with the cart): the 2-player character select (sprites flicker
   the cart's way, no garbage in the lower half), a busy 2-player fight, solo play unchanged.
10. **The AF-reply update: AF's reply gives back about half of what the chip's frame end costs** (0.3.0-s1t4, 2026-10-17;
   on top of finding 9). Where AF's reply goes (measured in the RV32 board model on the priced clock, every instruction
   of the 1,828 AF replies of the attract window priced and summed per function; the profiled run reproduces the plain
   one exactly): the sprite-values update's mean reply is 97.3 us against the base build's 79.6; the extra 17.7 us is the chip's frame end
   (`ppm_close_sprite_table` + its descriptors 23.7 us against 0.2.6's close 7.3: the 28-word stash, the second
   descriptor, `$1F1C`, entry 79; the D38 gate and the mode / parity hand-over 1.4 us). The rest is the same on both:
   the cart-register writes (`s1_freg_wr`, about 8 a reply: the entry clear, the flush's four, the finish, and two for
   every listed load; 19.3 us in TEST with the oracle log), the status helper (3 calls, 8.0 us), the dispatcher entry
   and the trap (19.5 us), the flush (6.9 us) and TEST's counters (5.2 us). Frame 8380 (AF01, 56 entries, no load): its
   reply is 11.4 us longer, the close +16.4 us of it (the rest moved with interrupt timing). What this update changes,
   all pure speed-ups (the same stores to the RAMDP, the cart registers and FPGAIO in the same order, with the same
   values; only store widths differ, as before):
   - the close (`legacy/026/mame.c`): the descriptors are built inline with their constant words held in registers
     (`chip_af_desc` always inlined), the end mark's Y and link clear are one read and one word store of the entry's
     first word (Y at +0, then the link at +2), the stash is 28 word copies fully unrolled in one tail-called helper
     (`chip_af_stash`), and the 80+ tables are out of line and compiled for size (`chip_af_over80`: one move helper, the
     relink four entries a pass), so the common close is a leaf with no stack frame;
   - the frame end does its WRAM bookkeeping first and reaches the close by a tail call, and no longer reads `$1F18` for
     a variable nothing uses;
   - the flush (`core/dispatch` `flush_regs`) writes each entry's two queue registers in line (no `push_entry` call).
   Proof: a bench (our `closebench.py` and `afbench.py`, not in this tree: the close and the whole AF fragment called alone on
   the board model, on 3,000 / 600 synthetic cases: every count 0-140 x mode x parity, 0-15 loads) gives the same
   halfword write sequence, cart-register writes and FPGAIO writes in order and the same RAMDP afterwards as the sprite-values update;
   the chip lockstep (`chiplock_s1`, full corpora and the AF unit) and `sprval.py` (six corpora) as finding 9.
   MCU time (estimated): the common close 23.7 -> 17.6 us, the 80+ tables 97-126 -> 74-94 us (AF02), AF01 above 80 on an
   even parity 62 -> 48 us; the whole fragment -6.5 us with no load and -1.35 us a load (TEST and RELEASE alike).
   Cost: IROM +132 / +108 B (TEST / RELEASE) in the 0.2.6 sprite engine (4,192 / 3,992 B) and +20 / +20 B in the
   dispatcher (7,132 / 7,116 B); free IROM 2,644 -> 2,492 / 9,788 -> 9,660 B; WRAM, the stack bound and the 0.2.6 source
   set unchanged.
   Time (RV32 rig on the priced clock, estimated; P0 = the rig's default seed; against the base build / the sprite-values update): late passes
   attract TEST (7,000-9,000) 62 (62 / 63, the same late frames as the base build), duo TEST 30 (30 / 30), solo TEST 13 (13 /
   13), Arcade 3P TEST 2 (2 / 2); at >= 12,973 / >= 13,075 us 65 / 61, 31 / 28, 13 / 13, 2 / 2 (the base build 65 / 60, 33 /
   30, 13 / 13, 3 / 2). Frame 8380 ends at 13,023.0 us (the base build 13,020.9, the sprite-values update 13,030.1): its reply is 70.4 us
   (77.1). AF's reply on average 89.2 / 87.7 / 84.5 / 88.8 us (attract / duo / solo / Arcade 3P; the sprite-values update 97.3 / 95.6 /
   91.7 / 96.6, the base build 79.6 / 75.9 / 73.8 / 78.4); AF ends 8.8 / 7.8 / 7.3 / 9.0 us earlier than the sprite-values update's (17.9 /
   11.4 / 10.7 / 15.1 us earlier than the base build's), while the AF write itself moves by sd ~25 us a frame between any two
   builds (the closed loop). Lag VBlanks 28 / 65 / 64 / 58 (the base build 28 / 65 / 64 / 57, the sprite-values update the same as this
   update); SFX underruns, decoder late words, aborts and rig faults 0; AF's L1 body at most 147-194 us. The rig is also
   layout-sensitive: an intermediate build that differed only in the code of the 80+ tables (never run on attract)
   scored 63 there (8380 at 13,089.7 us after a reply that met the thread's TEST work), its timeline parting from this
   one's at frame 3074, in a stage load with no AF in between, where only `mame.c`'s later functions had moved (48 B;
   the AF fragment itself prices the same on both: afbench 0.00 us); why a move changes the priced time there is not
   known (the model reads the jump and branch extras per translation block (inferred)). A single P0 run is one draw
   (in a noise study, the base build itself scores 62 / 63 / 62 / 63 on four seeds).
   On four seeds (that noise study's ensemble, attract TEST: P0-P3 = `tr_rig.py --seed 1-4`) the late passes are 62 / 63
   / 62 / 63 (mean 62.50; the base build 62.50, the sprite-values update 62.75), lag 28 / 27 / 27 / 28 (the base build 28 on all four); per frame
   (1,828 frames x 4 seeds) AF ends 17.7 us earlier than on the base build (the sprite-values update 9.4), its reply 9.7 us longer (the sprite-values update
   18.1): the update gives back 8.3 us of the chip close's 18.1. Frame 8380 stays inside T_LATE's band: late on 3 of 4
   seeds (the base build 1 of 4, the sprite-values update 3 of 4), mean finish 13,042.2 us (the base build 13,029.6, the sprite-values update 13,041.4); its AF is
   not written earlier on either update (the compose savings land elsewhere) and its reply is still 11.5 us over
   the base build's: the stash and the second descriptor (about 10 us of RAMDP accesses) are the floor the chip's close leaves
   on this MCU. OPEN as before (test build 4's MCU fast path or a faster register path).
11. **The misc update (2026-10-17, B Jam's decisions of 2026-10-16 from his Group 1 captures; firmware only, test build
    3's fit).**
   - **The C6 hold (docs/ALLOWLIST.md, row B34, done as the chip does it).** The game counts its polls of the C6 busy and keeps the low byte as the start of its
     random table; the cart's is 94 (measured: three CDX power-ons, all 256 attract demos matched; 95 once). The C6
     job (L2c) now holds `$1FE6` bit 14, the chip's own "queue not empty", until the game has polled 80 times: at the
     C600 post and at VBlank starts 1-79, counted on VSCNT (v1.1), released 120 lines after the 79th VS start (a VS
     start comes 10.99 lines after the VBlank start, measured on Nuked-MD; when the game's first read, 96 68000
     cycles after its C600 write, falls between a VBlank start and its VS start, the hold counts one VS start more). The job step's own bit-14 store follows it, so every register write of the C6
     event is the chip's. Proof: `tests/equiv/c6count.py` (the game's loop against the image on the RV32 board model:
     count byte 94 at the corpus's C600 phase and 7 more, TEST and RELEASE, and 60 phases on TEST; planted bugs
     caught).
   - **The SFX laws (D31 and the three faults of B Jam's follow-up captures).** D1 / D3 levels (from the
     chip's level table, built at boot), the D1 loop flag (bit 15) as the only loop and kept out of the RTL's pitch
     bits, D3's target / step on the lowest channel of its mask, D2's free or fade-then-free, the per-channel fade on
     the synth tick (the 9494 head with the mixer, NTSC skips every 6th frame). Equal to the cart program frame by
     frame in six scripted cases (punk TV, the corpus's loop + D2 6 fade, D3 step 1, levels 0-0x1FF, D2 cases); the
     pushed samples equal the chip mixer's order (6 ids, two looped passes). Proof: tests/s1/audio_tests.c A7-A10 and
     our frame-by-frame SFX comparison (not in this tree).
   - **The hold-B line:** the ROM's own digits and letters on every Console (BOOT-07 dropped).
12. **The merge of 2026-10-18 (0.3.0-s1t4b, 2026-10-18): the TEST debug-save fixes on the 0.3.0-s1t4 firmware (TEST
    only; the RELEASE images
   are the 0.3.0-s1t4 firmware's, byte for byte, brain-bearing and brain-less).**
   - **Debug save version 5 (the 2026-10-17 debug-save update):** the previous session's decoder, CPU MATE, feeder, exception, dispatcher and
     stack counters (`prev2`) and their worst over the chained sessions, carried across the Pocket's quit restart.
   - **TEST's SAT snapshot, layout 2 (the 2026-10-17 snapshot update):** the session's most crowded frame with its true count, the latest
     frame, the session's most and its frame ends over 80, a torn copy flagged (`interim/README.md`).
   - **The review's finding F1, fixed:** the thread read the frame-start count (`ae0`) only inside `ppm_snapshot_sat`, after
     its interrupts-off take of the request, so a frame start in between gave a torn copy with no flag. `l3_test_work`
     now reads it in the same interrupts-off section and hands it over (+4 B of IROM). Section H of tests/equiv/q1_save.py, the take race, plants
     that frame start at the take path's first instruction and at `ppm_snapshot_sat`'s entry, with the next frame's
     table written under the copy: flagged on this tree, unflagged on the same tree without the fix (measured, RV32
     model).
   - **the 0.3.0-s1t4 firmware's AF close is the chip's, so the stored crowded table is the chip's multiplex:** a frame
     over 80 posted AF02 (the game's usual close) is relinked in the cart RAM before the thread copies it (entries 14-79
     link to k - 13; the console's slots 14-79 hold entries 28-93, its slots 0-13 entries 0-13 above line 48 and 14-27
     below). `tools/dbgsave.py` names it in plain words, gives no line totals for it (entries 80-93 are not in the
     save), and reads "more than 80" from it in a layout-1 save as well (the old reading, entry 79 linking to entry 80,
     holds only for the base build's close). Section H of tests/equiv/q1_save.py checks it (the replay posts AF02).
13. **the fix of 2026-10-18 (0.3.0-s1t4c, 2026-10-18): the lost wake-up fixed (TEST and RELEASE), and TEST's snapshot bookkeeping
   after AF's reply (TEST only).**
   - **The lost wake-up (finding R1 of our audit of the scheduler; the freezes of a timing run on the RV32 rig).** From
     the decoder-in-logic change (jobs in L2c) to the merge of 2026-10-18, test build 3's firmware included: an L2c
     pass's l3_job reads the queue's indices, finds nothing and returns 0; a job an L1 post queues after that read,
     before the pass stores `l2c_active = 0`, raises MSIP; the nested L2b (MSI open in L2c) clears MSIP, finds the pass
     running and leaves; the pass returned 0 and left too, so the job stayed queued with MSIP clear and the 68000 spun
     on `$1FE6` bit 14 for good (a DA02 / C6 / DF / E0 post; a DA07 0x81 / 0x82 waits on busy). The window is 9
     instruction boundaries in TEST, 6 in RELEASE, stretched by any L2a or L1 taken inside it (that timing run's attract
     freeze: an MTI there stretched it to ~9,600 cycles and the game's next DA02, ~30 us after bit 14 cleared, came
     inside it). Fix (`core/sched/sched.c`, core/sched README): the nested L2b sets `l2c_missed`; the pass clears it
     before it opens MSI and, after it has masked MSI again, loops on `ran || l2c_missed`. Proof (estimated): the
     audit's exhaustive interleaving model on the built images (our `model.py`, not in this tree: 2 or 3 jobs, a timer
     deadline, a plain post, two SENDs, stage 5's tick with the urgent deadline: no lost wake-up, no drain failure, TEST
     and RELEASE; the images with the fix left out lose the job at all 9 / 6 boundaries); `tests/equiv/race_s1.py` on
     the RV32 model (the job planted at every window boundary and the control: it runs at each, TEST and RELEASE;
     without the fix it is lost at every boundary); `tests/s1/sched_tests.c` 7d. Cost (measured): l2b_msi +8 B TEST /
     +20 B RELEASE, sched_init +4 B, 4 B wram; per L2b entry about 10 instructions more and one less per pass that ran a
     job (estimated from main.dis: about 1 us a job post at the hardware CPI, never in a reply).
   - **Not a race:** the audit's "R2" (one `tick_mbx` for both mailboxes, stage 5) assumed a tick post that arrives
     during a tick is dispatched at once; `disp_holdable` holds it (index 0x14), so each tick end finishes one tick post
     and the held one starts the next tick (the model with the hold: no finish lost, estimated). Its "BRAIN-REPEAT" (a
     SEND between l3_brain's LSTAT clear and the call's read is answered by this call and once more) is 0.2.6's order
     for the CPU MATE: kept (the buddy copies 0.2.6, quirks included).
   - **TEST's SAT snapshot: AF's bookkeeping after the reply, its count read before it.** in that timing run on the RV32
     rig: the count latch, the two compares and the request (14-18 instructions) cost AF's reply +1.53 to +1.66 us
     against the 0.3.0-s1t4 firmware, which put duo 0.25 over the noise band. TEST's `f_af` now makes the finish itself
     and then calls `body_af_replied` (still in AF's L1), off the reply. CORRECTION (from a review): as first committed
     (2026-10-18) the bookkeeping read `$1F18` after the reply as well, and this finding said "the same records (the game
     writes `$1F18` only after the next VBlank in every capture)". The captures say that of the game's timing; it is not
     a property of the firmware: the reply frees the 68000, and in the RV32 model's replay with the 68000 unpaced (duo
     frames 0-19,000) it wrote `$1F18` first in 2,022 of 18,425 closes, so those latched the next frame's 14 or 0 and
     the frame ends over 80 came to 106, not 114. Fix: `body_af` reads `$1F18` before the reply, beside the chip close's
     own read, into a 2-byte holding place (5 instructions, one RAMDP read), and `s1_sat_snapshot_later` latches it
     after the reply; the AF count, the two compares and the request stay after it. Measured on the same unpaced replay
     (the review's tool with the close's own read added, run on until the last AF's L1 has ended): on all 18,426 closes
     the latched count equals the count the chip's close read,
     and the latched counts, the session's most (93), the frame ends over 80 (114, = sprval's) and the AF / AE counts
     equal the merge of 2026-10-18's. The final save is not a function of the latch: which frames the thread copies (and so which
     crowded table and copy-time counters the save keeps) follows when the 68000's next frame start comes. In the
     unpaced replay it differs from the merge of 2026-10-18's (460 B), as the merge of 2026-10-18's own does when only its reply timing moves (5 nops in
     its `body_af`: 463 B, every latch equal); with every frame paced like the game (the 68000 waiting 30,000 model
     cycles after each frame record) the final save is the merge of 2026-10-18's byte for byte, and the first commit of the fix's too (measured, RV32
     model). TEST's AF reply 3.6 us shorter on average than the merge of 2026-10-18's and 0.6 us longer than the first commit of the fix's (duo, frames
     0-1,500, the timed rig, estimated); RELEASE unchanged (the images byte for byte). Section H of tests/equiv/q1_save.py now gives each
     copy to the frame whose request the thread took (the AF count at the take, not at the copy's entry): with the
     new timing a copy taken for an earlier frame began after the planted frame had closed, took its number and let
     the 68000 go on before the planted frame's own take (a harness fault; `tests/equiv/README.md`).
   - **The C6 hold's edge band (not new; the gate phase moved).** The case check (B34, `c6_hold_target`) samples VSCNT
     once a loop pass (~42 model cycles), so a C600 whose first read falls within one pass after a VBlank start can
     give 93 instead of 94, depending on where the job's loop starts (the misc update: "a boundary, not a test"). Measured
     on the RV32 model (82 phases): the merge of 2026-10-18 TEST 93 at first reads 2-12 MCLK past the edge, the fix of 2026-10-18 TEST 2-42 (the L2b
     entry is ~6 instructions longer), RELEASE 2 on both; 94 everywhere else. run_all's phase 895300 (22 MCLK past)
     lay in the band and is now 895350 (72 MCLK past, outside any one-pass band). The game's own C600 lands ~138,000
     MCLK after a VBlank start in every capture. Narrowing the band (straight-line VSCNT / TIMER pairs at the deadline)
     is a separate change.
   - Sizes (measured, TEST / RELEASE): the scheduler 2,868 / 2,400 B irom, 152 wram; the dispatcher 7,568 / 7,480 B;
     the re-hosted bodies 4,062 / 3,550 B, 92 / 66 B wram (the count's holding place +2, the linker's fill 2 B less);
     the 0.2.6 sprite engine 4,172 / 3,992 B; IROM below the brain 21,132 /
     17,548 B, above it 19,564 / 15,088 B (free 212 + 168 = 380 / 3,796 + 4,644 = 8,440 B; the merge of 2026-10-18 428 / 8,464); the
     stack bound 3,108 / 2,324 of 5,120 B (3,092 / 2,292: l2b_msi's frame 16 -> 32 B, twice in the L2b-on-L2c chain;
     TEST's AF path in L1 16 B less).
14. **the SFX fix of 2026-10-19 (2026-10-19): the cart chip's SFX channels (B Jam's report on the 0.3.0-s1t4 firmware: in the Block 888 cell, as Tug, the alarm
   kept playing after the cell).**
   - **The fault (measured):** the alarm is D123 [0040 00FF 0080 8100] (mask 0x40 = channel 6, looped),
     posted when the cell door breaks; the play start's D122 (looped, channel 6) is still fading out to a free (D240 1)
     if the door breaks in the first ~3.8 s of play (a fast Tug). The chip's channel pick then takes channel 6
     (the old cue ends) and the exit's D240 0 frees it. 0.2.6's channel choice put the loop on channel 0, outside the
     mask, where nothing the game sends reaches it: with the real loop of s1t4 (D31) it played on (87 s in the run).
   - **The fix does the rest of the chip's SFX channels as the chip does** (`interim/s1/sfx_s1.c`, which the stage-1 builds link
     instead of `interim/album/sfx.c`; the entry names and the audit log are 0.2.6's): the channel choice (never
     outside the mask); the SFX start's voices (the rate step and size trim; in the cart-DAC mode, which the game uses,
     an echo voice and a two-voice spread; retriggers; a start delay); the mixer's bookkeeping (a sound's position and
     end from a 300 Hz block count);
     no RTL flag bit (the RTL's half rate, echo line and pitch bits were 0.2.6 / GPGX readings of 0x2000 / 0x4000 /
     0x8000); D5 touches no channel (0.2.6 stopped 6 / 7, which ended the Solarium wind loop 456 frames early). The
     block count is ours (a grid on the board timer, estimated against the chip's TIM6-polled mixer) and so are the
     random numbers. A start that waits (a delay, the two voices of a spread, or a FIFO still holding samples: muted
     and drained at 48 kHz, at most 5.3 ms) is pending and the feeder's grid starts it. Allow-list B12 shrinks to the filters, the pan law, D5's
     echo itself, the RTL's lowest rate and the block phase (the lowest rate is the chip's 4,800 Hz since test build 4's RTL of
     2026-10-19).
   - **Proof (measured: the cart program in our cart-engine runner, not in this tree, against sfx_s1.c + audio_s1.c
     as built, on the real ROM, with the chip's own block count and random numbers replayed):** every frame, every
     channel: active, level, pan, targets, step, free flag, loop byte, sound id, position, length, delay left and
     retrigger count equal, 0 differences, on solo (72,422 frames), duo (59,553), attract (60,000, with the game's
     0x0400-0x0C00 retriggers), stage 04 (9,551), Arcade 3P (8,139), w14 (the co-sim capture, 3,601), first boot
     (2,000), the seven Block 888 runs (the fast Tug door break included; the alarm on channel 6 from
     frame 183, freed at 691) and the misc update's six scenarios (also on its own harness: 0 differences); the feeder
     pushes nothing on a channel the chip has freed and feeds every loop the chip plays (the same runs). Host:
     `tests/s1/audio_tests.c` A11-A18 (the cell, the channel order, echo, spread, retrigger, 0x0100, D5, the block
     count; negative controls 6-8 caught).
   - **Cost (estimated, the RV32 model on the TEST image, solo's first 380 D1 posts):** a D1 body runs 677 instructions
     at the median (the fix of 2026-10-18's 366: both include the first batch) and 6 divides (when every channel of the mask is busy:
     one per channel's score, as the chip); the 9494 head 213 (the fix of 2026-10-18 119): the block count and each channel's end. A
     spread's two voices start from the grid, not in the D1's L1 (with both first batches there a D101 took 14,766
     model cycles in fuzz_s1, over FZ12's 14,318). In the
     code window, so the IROM is unchanged but for the feeder's pending check and the grid's clock figure (+112 B;
     the window carries no clock figure: check_clock --images) and the 88 call (+28 B).
   - Sizes (measured, TEST / RELEASE): the stage-1 SFX 4,552 / 4,440 B in the code window, 975 B wram (the records in
     wram_upper); interim irom 1,856 / 1,684 B (the album); the bodies 4,090 / 3,578 B; the feeder 1,948 / 1,476 B;
     `f5_s1.c` moved to irom_lo: free irom_lo 916 / 4,328 B, irom_hi 936 / 5,412 B, wcode 2,420 / 3,112 B; the stack
     bound 3,108 / 2,340 of 5,120 B.

15. **Test build 4 firmware (0.3.0-s1c4, 2026-10-18): the MCU fast path's firmware side, the chip's attribute word
    (D23),
   and the card's controller and coin decisions on record.**
   - **The fast path (the fast-path branch of 2026-10-16) merged onto the fix of 2026-10-18.** Its firmware side is the image tools only: the WRAM
     image also as four byte lanes `wram_b0..b3.txt` (`tools/mkimage.py`, fwbuild's md5 list, `check_images` checks the
     lanes hold the pair's bytes), `check_board`'s RTL items for test build 4 and their three planted mistakes,
     MCU_INTERFACE section 20 (the cycle table; section 19 stays test build 3's v1.2 record), LAYOUT, README. No C code:
     the merged tree builds the fix of 2026-10-18's images byte for byte (measured: TEST a88919b7, RELEASE 43fe78b2,
     every file), its lanes equal its pair. One timing fact carried into section 20 (measured in replay): on test build
     4 a pending interrupt that a `mie` / `mstatus` write unmasks, or one pending at an `mret`, can be taken one
     instruction later than on round 4 (same interrupt, same handler), which can reorder an MCU register access around a
     handler.
   - **The scheduler after the merge: no lost wake-up (estimated).** The merged scheduler is the fix of 2026-10-18's (the R1 fix,
     finding 13), and with D23 its code and addresses are unchanged (D23 is in the low IROM). The audit's exhaustive
     interleaving model (a copy of the audit's model: the tick post held) and the review's own model, both on the images' real
     instructions and both taking every pending interrupt either at once or one instruction later (which covers card
     4's late take): model.py TEST J=2 / J=3 / J=2+T / J=2+P / J=1+2 SENDs / stage 5's tick with the urgent deadline
     (3 shapes), RELEASE J=2 / J=3 / J=2+T / stage 5 (3); rmodel.py J=2, J=2+T, J=2+P, J=3, J=2+K, J=1+T+K, J=2+P+T on
     both images: no lost job, no drain failure (only the known BRAIN-REPEAT, 0.2.6's CPU MATE order); every state count
     equals the fix of 2026-10-18's. The images with the fix left out lose the job at the same 9 / 6 boundaries (both models).
     `tests/equiv/race_s1.py` (run_all) plants R1's window on these images: the job runs at every boundary, TEST and
     RELEASE; without the fix it is lost. Nothing new to plant.
   - **D23: the attribute word as the chip composes it** (B Jam's decision of 2026-10-18: "if cart is different color change to cart").
     The chip (0x0802F02C composer) adds three 16-bit words: the piece word (the halfword at piece +6: attr byte << 8 |
     tile offset), the object's attribute word and the block's VRAM id x 16 (0x0802F186-0x0802F192); with the object's
     H-flip bit it takes the object word less $800 once a pose (0x0802F41E-0x0802F428) and XORs $800 into each piece word
     (0x0802F47A-0x0802F48E); a pose whose frame word has bit 29 clears the object's palette bits 13-14 first
     (0x0802F104-0x0802F112; a held pose tests the frame drawn again, 0x0802F404-0x0802F41C). 0.2.6 composed field-wise
     (the piece's priority and palette win, flip and tile XOR, the piece's attr bits 0-2 dropped), ignored bit 29 and
     cleared palette bit 13 on object 107's piece 4 (the door fix). `PPM_CHIP_ATTR` (legacy/026 mame.h, stage 1 only)
     follows the chip's rule; neither the field-wise rule nor the door fix is compiled with it. Measured: the chip
     lockstep now holds every word of SAT entries 0-129 and the stash to the chip after every AF (`chip_sat_words`); all
     24 corpus runs PASS (the sprite words compared after 1,148,167 ADs and 240,063 AFs: 0 differences, the attribute
     word included). the fix of 2026-10-18 fails solo 0-3,700 on 77 AFs (from frame 1,040, an AF02 table the chip draws on palette line 2
     and 0.2.6 on line 1). Planted (chiplock_slice n9-n11): 0.2.6's rule back, bit 29 ignored, the H-flip path composed
     as the plain one: each caught (the last only where a flipped object has a piece attr bit 3: solo frames
     11,995-11,996, attract from 8,116, measured from the captures' poses). Sizes: the sprite engine 4,052 TEST / 3,868
     RELEASE B irom (-120 / -124); IROM free TEST 332 + 168 = 500 B, RELEASE 3,920 + 4,644 B; stack bound unchanged.
   - **Controllers and the first coin are RTL (test build 4, its RTL).** The firmware reads no controller: the empty
     port, the real six-button pad on the direct ports (and the Scum! cave no longer adding X / Y / Z / Mode there),
     each 4-Way Play slot's own pad type and the coin stub's jump to the game's first-coin gate ($0B5950) are in the RTL
     tree. The firmware tree records them in allow-list rows B13 / B31 and the release draft.
   - **A false positive in the stack check:** in the `release_bug_r1` image (run_all's planted R1 image) the shorter
     compose moves libgcc's `__fixsfsi` to 0x4000, which is `$1FE6` bit 14 in four functions' code; it is called
     directly only, so `tools/stack_s1.json` lists it under `address_taken_ok` (as `ppm_chip_rebuild` in finding 13).
   - **The fast path in the timed rig (estimated: the RV32 board model with the fast path's prices, each round-4
     class price times the measured fast-path / round-4 ratio; TEST images, seed 1, the gate's corpora).** Late passes,
     test build 3 with the fix of 2026-10-18 (round-4 prices, the s1t4 gate's runs) -> test build 4 with this firmware:
     solo 13 -> 9, duo 30 -> 19, attract (frames 7,000-9,000) 63 -> 41, arc3p 2 -> 1; what is left includes every frame
     the cart model itself makes late (5 / 12 / 21 / 1: the game's own AF write already that late in the GPGX capture).
     Lag frames 91 -> 87, 92 -> 87, 28 -> 18, 85 -> 83. AF's reply 82.5-86.9 -> 47.8-49.4 us mean (paired -34.7 to -37.5
     us), the 68000's wait before AF about halved (491 / 547 / 950 / 593 -> 259 / 299 / 524 / 331 us a frame). No
     underrun, no decoder word read before it is decoded, no rig fault; the RTL decoder is not faster, so with the
     game's frames earlier its smallest margin falls on solo (2,404 -> 584 us) and duo (1,385 -> 728 us). The figures
     mix the fast path and D23's shorter compose (fewer instructions a piece); the fast path dominates.

16. **The 2026-10-19 lateness update (2026-10-19, on a branch of its own, TEST only: the RELEASE images are the 2026-10-19 merge's
    byte for byte, brain-bearing
   and brain-less, NTSC and PAL): the TEST debug save version 6.**
   - **The CPU MATE late counter:** B Jam's save from a long play test of the 0.3.0-s1t4d firmware read "answers published late 31,629
     (must be 0)" of 36,904 calls, with no partner in play. The brain ran because the game posts it every gameplay pass
     with a Mega CD unit selected and the Options CPU MATE row on, partner or not (the cart's own behaviour); the count
     was the counter's: it went up at every publish that found the stub's sticky LATE flag up (`paprium_mcd_link.sv`
     flags[3], cleared only by LCLR: at the boot and in rare housekeeping). In TEST, `publish` now clears the flag just
     before each ARM and counts the flag in the LSTAT read that shows the ARM taken (the RTL sets it in the ARM's clock
     and gives that event priority over a same-clock clear; the clear and the ARM cross on the same synchroniser in
     write order); the housekeeping still clears it and no longer counts. Beside the count: the largest lateness (TICK
     at the busy release, or at the read a few sub cycles after the ARM, minus D_WORD) and the calls with D_WORD under
     1,000 sub cycles (the brain's short word-0000 path: no partner active). The old `late_seen` stays in the layout at
     0. A late answer is expected since the 2026-10-15 change and is no lateness sign any more; the reader says so.
   - **The album recorder:** B Jam heard no Blue Bar street music on the 0.3.0-s1t4d firmware although the game
     posts 8C8B and the firmware writes MD+ 0x120B there. Every debug-save write now polls the MD+ result word
     ({current_track, 7'b0, playing}, `paprium_mdp_adapter.sv`) and the command word the adapter last took, XLINK 0x14
     (CDDA underruns, snoop overflows) and 0x18 (CRAM ring writes and loader words lost); every album call notes its
     command word (and whether it was written: the album off marks it); a play request also its VSCNT, and the wait runs
     until a write sees playing (then it is how long the start took), a stop ("stopped without playing") or the next
     request. `prev2` carries the state at the last write across the quit, and the longest wait over the chain.
   - **Cost (measured, TEST):** the glue +20 B in the code window, the album recorder +424 B interim irom (irom_lo;
     `album_call` and `s1_album_poll` out of line, -Os), the debug save +4 B (the carried words' table rows and the
     poll's call, less the stack block's copy), wram +92 B (wram_upper; `s1_audio_stats` moves there in TEST). Free:
     irom_lo 512 B, irom_hi 912 B, wcode 2,400 B, wram_data 480 B; the debug-aids plan row 3,164 of 3,164 (the irom
     placement's slack 12 -> 8 B). Record 1,024 of 1,024 words. One more XLINK store before each TEST ARM.
   - **Proof:** `tests/equiv/tdiag_s1.py` on the TEST image in the RV32 board model with a Mega CD link stub written
     from `paprium_mcd_link.sv` (the sub-cycle tick, the ARM's lateness test, the sticky flag, the release at D_BUSY,
     TICK frozen there): the firmware's count equals the stub's own late ARMs, its largest lateness the largest TICK
     read after a late ARM minus D_WORD, its short-path count the ARMs under 1,000 sub cycles; the album words, the
     reader's lines and the quit's `prev2` for a play request left silent, played, stopped, a play-once left silent and
     stopped, and a request across the quit; its negative control (test_bug_late: no clear before the ARM) counts more.
     On the four recorded co-sims the version-6 count is the RTL's own late count by construction (w14 616, w14m2 34,
     w14p3 402, w14p4 480 of ~1,050; estimated from their cpumate.csv).
   - **The fix of 2026-10-19 (the review's "counts each answer once", TEST only):** the review measured two races on the RV32
     rig that the default seed 3 hid (`tdiag_s1.py --seed 11` failed): (a) publish preempted past the busy release and
     the game's next post reads LSTAT with the new post in it and takes the discard path, so a late ARM was never
     counted (seeds 5 / 11: 530 / 516 of the stub's 532 / 518); (b) a post between late_note's LSTAT read and its TICK
     read restarts TICK, so late_max took the newer post's tick minus D_WORD (16,776,751 = 2^24 - 465; seeds 5, 7,
     11). Now the discard path counts the flag too (only an ARM sets it, and publish cleared it just before: it is this
     ARM's), and late_note keeps a TICK reading for late_max only when LSTAT's post count read after it is still the
     call's (`posts0`, not the publish read's own count). The answer of (b) still counts; its lateness is unknown to the
     firmware (TICK restarted), so late_max is the largest *readable* lateness. Measured: after the replay on seed 11 the
     true largest (224,778 sub cycles) was such an answer (late_max 127,214, the largest readable); at the quit late_max
     was the true largest on all four seeds. In the hardware the game posts once a gameplay pass, so (a) and (b) need
     the thread preempted for a pass (estimated: not seen; the rig's sub posts as soon as one model step after a
     release, a stress). Cost: the glue +40 B TEST wcode (2,424 B; free wcode 2,360 B); RELEASE unchanged (images
     byte-identical to the 2026-10-19 merge's, brain-bearing and brain-less, NTSC and PAL).
     **Proof:** `tdiag_s1.py` now runs seeds 3, 5, 7 and 11, each through J, the album scenario and W (the whole run to
     the quit, ~1,700-1,900 calls a seed: the count == the stub's with each late ARM counted once, late_max == the
     largest readable == the true largest unless that answer was unreadable, every ARM's fate), then section F on seed
     3: three overtaken publish reads and three stale TICK reads placed on purpose (posts just before the firmware's
     reads), so that each net runs on every run whatever the seed. Planted: test_bug_disc (GLUE_BUG 2, no count on the
     discard path) and test_bug_tick (GLUE_BUG 3, no post-count check) each fail F (F1 / F2) on the first board, every
     other check passing; without F the sweep's own races catch them too, seed by seed (test_bug_disc on seeds 3 and 5,
     test_bug_tick on 5 and 11; on seed 3 its one stale read poisoned nothing: the newer post's tick was already past
     D_WORD, a lateness below late_max; measured, and why F places them with the read at 0); test_bug_late as before. The sweep's own races on the fixed image: 3 overtaken
     publish reads, 7 stale TICK reads over the four seeds (measured).
   - **Merged into test build 4 (test build 4's firmware, 2026-10-20; the doc lines on the RTL's rate 5
     corrected in the same merge: 48,000 / 10 = the chip's 4,800 Hz since test build 4's RTL of 2026-10-19):** RELEASE
     images = the 2026-10-19 merge's byte for byte, brain-bearing and brain-less (test build 4's fit keeps its RELEASE bitstream);
     TEST (measured): free irom_lo 632 B, irom_hi 912 B, wram_data 480 B, wcode 2,360 B, wram_upper 7,740 B; the stack
     bound 3,124 / 2,340 of 5,120 B. In the merged tree the planted test_bug_l2c and test_bug_hold images put
     `interim/album/everdrive.c`'s `ed_cmd_cd_mount` at 0x4000 by layout, the same `$1FE6` bit-14 coincidence as
     `__fixsfsi` in test build 4's item; it is called directly only (one jal, from `mdp_init`), so `tools/stack_s1.json`
     lists it under `address_taken_ok`.

---

## 1. The levels

Design B on the MCU interface v1.0 (NEORV32, three level interrupts plus the thread). One trap entry
(`board/pocket/s1_trap.S`) serves all three.

| level | entry | interrupts while it runs | what runs there | Measured (system co-sim, TEST images unless marked) |
|---|---|---|---|---|
| **L1** | `l1_mei` (MEI: CAUSE B, A, S) | none (MIE off) | read and acknowledge each post, the chip's dispatcher (gates, refusals, status writes, job pushes, register sequences: since the decoder-in-logic change the decoder queue's pushes too, and the DEC_BASE board write before each START), the L1 bodies (audio, sprites, streams), the 9494 head (watchdog feed, bit 13 clear); a SEND from the buddy link marks the brain call pending (the 2026-10-15 change: no interrupt raised, the thread makes the call); a queued job raises MSI | post answer (post to acknowledge): RELEASE 92.9 us max, 10.3 us mean over 2,031 posts to the main menu; TEST 32.6 us max to frame 825, 101 us in play (a post waiting behind the previous body). Length (co-sim, the images of 2026-10-13): AD 8,269 / 8,538 us (RELEASE / TEST), "D1" 3,460 / 3,566 us and "B6" 2,943 / 3,055 us (AD bodies in the same entry; D1 alone 213 us), mean 128 us. The 2026-10-13 change (RV32 model): AD <= 1,161 / 1,303 us, every other body <= 0.24 ms at the hardware CPI |
| **L2a** | `l2a_mti` (MTI: TIMER >= TCMP) | MEI | the timer wheel: each due slot, lowest first (urgent song tick, watchdog / heartbeat, SFX feeder, VU row); the compare always holds the earliest deadline. TEST's debug save slot is only marked due here (since the 2026-10-15 change the thread runs it, below the brain call; after the first 2026-10-14 change it was L2c). No slot is held for a brain call (since the 2026-10-15 change; the second 2026-10-14 change held the SFX feeder's) | 3.4 ms of CPU per frame on average, 6.2 ms during the title zoom (before the F5 fix); longest run 9.49 ms inclusive |
| **L2b** | `l2b_msi` (MSI) | MEI, MTI | from stage 5 the song tick in slices; then one L2c pass. From 2026-10-13 to the 2026-10-15 change, the firmware ran a stand-in for the cart FPGA's sprite-block decoder here or below (the decoder-in-logic change: the RTL decodes, finding 8); the two 2026-10-14 changes ran the CPU MATE brain call here, first, holding the SFX feeder's slot for it | the RV32 rig after the first 2026-10-14 change (TEST, model time): the decoder's share of the brain calls' waits 60% -> 1% while the decoder was L2c below the call; the 2026-10-15 change turns it round (finding 7) |
| **L2c** | inside `l2b_msi` (the 2026-10-15 change) | MEI, MTI, MSI (a tick start nests L2b on top) | the work the chip's main loop does, one pass at a time: one job from the queue (after the first 2026-10-14 change L2c was the decoder, below the brain call; after the 2026-10-15 change also the DA06 / DA07 board work, gone with the decoder-in-logic change) | C6 job 878.8 ms (TEST; 47.2 M cycles); F5 job 4.6 ms mean, 10.4 ms max inclusive (in the thread then) |
| **L3** | `l3_thread` | all | the 2026-10-15 change: the CPU MATE brain call (buddy glue) when one is pending, with every interrupt open (L1, the wheel and the jobs preempt it), else TEST's diagnostics (the debug save, the SAT snapshot), else idle housekeeping (the buddy link's restart / release / AI-off, one interrupts-off section a pass) | brain answers equal the reference on the RV32 rig (1,959 calls, W8; every call of every rig run since). W14 co-sim (the images of 2026-10-13 + that day's change): 422 of 752 words armed late, 9 calls with a stale read the game could see (finding 6) |
| boot | `_start` -> `brd_boot` | none until the end | BOOT_SPEC P1-P6: crt0 checks, boot page, app init, the release | release 7.83 ms after the reset (RELEASE), 11.08 ms (TEST); bounded at 61 ms with the EverDrive stub never answering (T-B10) |

Nesting: MEI > MTI > MSI > thread. L1 is not re-entrant: a post that arrives while an L1 body runs waits for it. GHDL
on the real NEORV32 VHDL showed all three nestings with no empty MEI entry (W3). MSI over MSI: an L2c pass (inside
L2b) opens MSI, so a second L2b may nest on it (after the first 2026-10-14 change: on a decoder request; after the 2026-10-15 change: on a job; with the decoder in logic: a tick
start on a job, stage 5's only case; fwstack level
`msi_l2c`, counted as a whole second `l2b_msi`; the bound is TEST 3,140 / RELEASE 2,388 of 5,120 B with the 2026-10-15 change,
TEST 3,252 / RELEASE 2,292 with the second 2026-10-14 change).

### The timer wheel (`core/sched/wheel.c`)

| slot | owner | period | does |
|---|---|---|---|
| `WH_URGENT` | scheduler | 737.5 us after a 9494 (stage 5) | finishes the song tick and the Z80 packet if L2b has not; empty in stage 1 (TEST probe only) |
| `WH_WDOG` | `core/wdog` (W7) | 102.1 ms (`CLK_TIM7`) | the chip's TIM7 work: watchdog, heartbeat (MegaWire's task joins it in stage 3) |
| `WH_FEED` | `interim/s1/audio_s1.c` (W9) | 133.5 us while an SFX channel plays | pushes SFX samples into the RTL FIFOs; preempts a CPU MATE brain call like every other slot (since the 2026-10-15 change; the second 2026-10-14 change held it for the call). The 2026-10-15 change: the same pushes in the same ticks for about 40% fewer cycles a tick (TEST ~5,000 -> ~3,000, RELEASE ~4,200 -> ~2,300, estimated at the hardware CPI; interim/README "The feeder's cost") |
| `WH_VU` | `interim/s1/vu_s1.c` (W9) | at each row's due instant | the Boom Box VU row (0.2.6's, on the board timer) |
| `WH_TEST` | `board/pocket/dbgsave.c` (W10) | 102.1 ms | TEST only: writes the debug record into the save; in `WH_LOW_SLOTS`, so its callback runs in the thread, below the brain call (since the 2026-10-15 change; after the first 2026-10-14 change: L2c; not in the scheduler probe, which uses the slot to time the wheel) |

Every period is a time, converted with the one build clock (`board/clock.h`, `BRD_CLK_HZ` from `fwbuild.json`), so it
is the same at the NTSC and PAL clocks (T23, `tests/check_clock.py`).

---

## 2. The command map

The game posts a 16-bit word: to `$1FEA` (mailbox B, every command) or `$1FEC` (mailbox A, the 9494 frame tick).
The chip's dispatcher takes the table index from bits 8-13 and the "arguments" flag from bit 14 (mailbox B only), so
a command and its bit-14 twin (95 / D5, 89 / C9, F0 / B0...) reach the same fragment. Indexes above 0x36, or with no
handler, are refused with code 2 (docs/ALLOWLIST.md, row B28). Every path ends with the finish: `$1FEA := 0` (or `$1FEC := 0`),
then `$1FE6` bit 15 through the status helper.

Where it runs: **L1** = inside the mailbox interrupt; **job** = queued (sets `$1FE6` bit 14; the job end clears it);
**RTL** = the chip's queue writes in L1, the post finished at once, the RTL decoder (MCU interface v1.2) decodes behind
the reply; **refused (n)** = `$1FE6` bit 9 (B) or 10 (A), trace code n
(5 queue full, 6 not ready, 7 bad arguments, 2 unknown).

| word | what (chip) | mailbox B, stage 1 | mailbox A | body in stage 1 | chip body arrives |
|---|---|---|---|---|---|
| 81 | options: debug counters, Boom Box feed, MegaWire task, watchdog reset; arms the watchdog | L1 | L1 | flags only | stage 3 / 5 use the flags |
| 82 | `$1FF2 :=` bit 0 | L1 | L1 | (register write only) | - |
| 83 | frame-period measurement | L1, accepted, nothing done (0.2.6) | same | none | stage 3 (B12) |
| 84 | blank-save first boot: 0.1 ms, window and FM view off, reset vector to the mini-game, watchdog off | L1 | L1 | as the chip does it, whole (docs/ALLOWLIST.md, row B26) | now |
| 85 | stop serving: `$1FEE`, `$1FE4 := 0x4000`, fatal trace; never returns | L1 | L1 | as the chip does it, whole | now |
| C6 | cart set-up (one-shot): mixer, sequencer, SFX, MegaWire init | job 11, held for the game's 80 VBlank polls (count 94, docs/ALLOWLIST.md, row B34, done as the chip does it: the misc update) | refused (7) | 0.2.6's set-up after the chip's writes | stages 2-5 |
| 88 | audio config (`$1800-$19FF`) | L1 (needs C6) | L1 | 0.2.6 `cmd_88`; the SFX takes bit 0 (the YM-DAC mode: no echo / spread voice; the SFX fix of 2026-10-19) | stage 5 |
| C9 / CA | music / SFX volume | L1 | L1 | 0.2.6 | stage 5 |
| 8C | play a music module | job 2 (no failure report) | job 2 | the album (0.2.6) | stage 5 |
| 8D | music stop / fade | L1 | L1 | the album | stage 5 |
| 8E | queue a track | L1, gates only | L1 | none (0.2.6 had none) | stage 5 |
| D0 | direct synth note | L1, gates only | L1 | none (0.2.6 muted it) | stage 5 |
| D1 / D2 / D3 | SFX start / stop or fade / level and pan | L1 | L1 (D3 refused 7) | the chip's SFX channels (D1 / D2 / D3 laws and the per-channel fade on the 9494, the misc update of 2026-10-17; the channel choice, voices, retrigger and mixer bookkeeping, the SFX fix of 2026-10-19) on the 0.2.6 feeder | stage 5 |
| 94 / D4, 9494 | the frame tick | L1 (the same path) | **L1: the 9494 head** | watchdog feed, bit 13 clear; song tick empty but the SFX channel fade (the misc update of 2026-10-17) | stage 5 (song tick) |
| D5 | echo off / on | L1 | L1 | no channel touched (the chip's; the SFX fix of 2026-10-19), the echo itself not yet (B12) | stage 5 |
| D6 | song controls (reset, echo, crisis, tempo, transpose, voice mute, sax flags, boost) | L1, gates only | L1 | none (0.2.6 muted it) | stage 5 |
| DA | load to VRAM: mode 2 or 7 via a job; DA06 / DA07 from a 0x80 source run in place | job 3, or RTL (B29, B38) | refused (5 / 7) | 0.2.6's unpack (jobs); the RTL decoder (0x80 in place) | stage 3 (unpackers) |
| DB | stream from SDRAM (DB06), or RAMDP to SDRAM (DB03) | L1 (SPTR then GO) | refused (7) | 0.2.6's stream | - (our stream path, B4) |
| DF | save read | job 5 | refused (5 / 7) | 0.2.6's save | stage 3 |
| E0 | save write (`$BEEF` key) | job 7 | refused (5 / 7) | 0.2.6's save | stage 3 |
| A4 / A6 / A9 / E7 / A8 / AA | MegaWire | L1, argument gates only; A8 (A858) disarms the watchdog | L1 (E7 refused 7) | 0.2.6 (E7: "data in") | stage 3 |
| EC | sprite slot count | L1 (needs the engine) | refused (6 / 7) | 0.2.6 `mame.c` | stage 2 |
| AD / AE / AF / B0 / B1 | sprites: compose, frame start, frame end, reset, load list | L1; AF / B1 push the load list (RTL); AF without an open frame: the finish only (D38) | L1 | 0.2.6 `mame.c` (its load list pushed by the chip's flush; the RTL decodes and points the window) with the chip's clip D24 and the chip's AF frame end (D10, the rest of D42; the parity H+$403 counted at AE / B0 / C6): the sprite-values update; the chip's attribute word D23 (the ADD, pose bit 29, no door fix): test build 4 | stage 2 (D19, D39, D47-D49) |
| F2 | stream one sprite block | L1 (the block pushed twice; RTL) | refused (6 / 7) | the RTL decoder | stage 2 |
| F4 | zoom source unpack + save | jobs 4 and 8 | refused (7) | 0.2.6 | stage 3 |
| F5 | zoom rescale | job 9 | refused (7) | 0.2.6's, fixed point (2026-10-12) | stage 3 |
| B6 | zoom restore | job 10 | job 10 | 0.2.6 | stage 3 |

Job types (`core/dispatch/disp.h`): 1-4 unpack (2 = 8C, 3 = DA, 4 = F4), 5 save read, 6 MegaWire EEPROM read (stage
3), 7 save write, 8 zoom save, 9 rescale, 10 restore, 11 set-up (C6), 12 set-up with the MegaWire screen
(unreachable on ours, B18). One job per thread pass; a failure sets `$1FE6` bit 8 when the slot asks for it.

Gates left for their stage (each fragment names its stage): the AD index (stage 2; the AF frame-open check D38 is
the chip's since the sprite-values update); the MegaWire byte and send gates, 83's windows (stage 3); the song and SFX ranges and
null slots (stage 5).

**0.2.6 behaviour per byte.** 0.2.6 dispatched on the whole high byte, so it served only one form of each pair. The
stage-1 bodies check the posted word and do nothing for the other form until their replacement that does what the chip does lands, so the game sees
no new effect (`tests/equiv/s1_slice.py`: 0 differences from final 0.2.6 outside the allow categories, solo frames
0-3,000, every post; since the sprite-values update the sprite words are one of those categories, a counted change of
reference held to the chip by the lockstep: finding 9).

---

## 3. Invariants

Each is a rule the code keeps, with where it is checked. FZ = the interrupt-race fuzz invariants (docs/STAGE1_PLAN.md section 4.7);
6.3.x = the handler rules of docs/MCU_INTERFACE.md section 6.3.

| # | rule | checked by |
|---|---|---|
| FZ1 | one finish per post | `tests/s1/disp_tests.c` fuzz; `tests/equiv/fuzz_s1.py` on the RV32 images |
| FZ2 | the status bits are stored before `$1FEA := 0` (the 68000 must never see the finish with older status) | same; planted bug DISP_BUG 1 caught |
| FZ3 | a job's GO (SPTR, length) is stored before its bit-14 clear, so a stale "ready" stays hidden behind bit 14 | same; planted go1 / go2 caught |
| FZ4 | `$1FE6` bit 14 = "the queue is not empty", never stuck | same; DISP_BUG 3 |
| FZ5 | no post is lost: acknowledge before read (6.3.2) | `fuzz_sched.py`, `fuzz_s1.py`; SCHED_BUG 1 |
| FZ6 | one 9494 service, then `$1FEC := 0` | disp fuzz; DISP_BUG 2 |
| FZ7 | the status shadow equals the register after every critical section | disp fuzz; DISP_BUG 4; host tests |
| FZ8 | posts held during a song tick are served after its end, in order (stage 5 path; vacuous on the stage-1 images) | `fuzz_sched.py` probe; SCHED_BUG 3 |
| FZ9 | the song tick meets its deadline: the urgent promotion, and since the 2026-10-15 change the brain call below L2b (stage 5 path; vacuous on the stage-1 images) | `fuzz_sched.py` probe; SCHED_BUG 4 (since the 2026-10-15 change: a call that masks MSI and MTI; the old plant, no urgent promotion, cannot fail it any more) |
| FZ10 | the watchdog trips only after more than 40 ticks with no 9494, never while the menu bit is set | `wdog_tests.c` at both clocks; `fuzz_s1.py` TEST scenario; chip lockstep |
| FZ11 | the stack never reaches its floor | `fwstack.py` bound in every build (5,120 B region); fuzz stack watch |
| FZ13 | (the 2026-10-15 change; B Jam's rule) no job waits for a CPU MATE brain call: wherever the CPU runs the call's code with interrupts open, none is pending (the first 2026-10-14 change's FZ13 was the reverse: the call never waits for a decode; with the decoder in logic: no firmware decoder left to check) | `fuzz_s1.py` on the RV32 images (every checkpoint inside the call); planted bug `test_bug_l2c` (the call masks MSI); host `sched_tests.c` 7b |
| DEC | (the decoder-in-logic change, MCU interface v1.2) the chip's queue writes in its order (the flush's pushes last to first, F2's twice, DA direct's one), DEC_BASE before every START with an entry, AF / B1 / F2 / DA06 / DA07 finished in their own L1; the 68000 never reads a decoded word before its block is decoded (the board model's RTL decoder at 140 ns an access, the game's VBlank DMA no earlier than the reply + 106 us and 175 us a block: our decoder spec, section 4) and no run is cut | host `disp_tests.c` (the write order and the decoded bytes); `chiplock_s1.py` (the pushes against the chip, write for write); `fuzz_s1.py` DEC (late window words, aborts, flags, deferred finishes; the control: a 40x slower decoder must fail); the timed rig outside the tree |
| FZ14 | (the 2026-10-15 change) the SFX feeder and the rest of the wheel never wait for a brain call: the call runs with MTI open (the second 2026-10-14 change's FZ14 was the reverse: the call held the feeder) | `fuzz_s1.py` on the RV32 images (every checkpoint inside the call); planted bug `test_bug_hold` (the call masks MTI); host `sched_tests.c` 7c, planted bug `sched_tests_bug7` |
| 6.3.1 | boot: acknowledge every cause with the 68000 held, then enable, then release as the very last step | `fuzz_sched.py --boot-checks`; co-sim: 0 bus cycles before the release |
| 6.3.3 | flush a level's `mie` bit after acknowledging it (NEORV32 re-latches the level) | GHDL nesting: 0 empty MEI entries |
| 6.3.4 | an MEI entry with CAUSE = 0 returns at once | `sched_tests.c` |
| 6.3.5 | wheel edits and every shared state change sit inside an interrupts-off section or in L1 | review; fuzz |
| 6.3.6 | nothing on a reply path runs from SRAM, SDRAM or CRAM | link map (`pocket72k.json`); `check_images.py s1` |
| 6.3.7 | no WFI | review |
| S1 | the status helper is the only writer of `$1FE4` / `$1FE6` (85 and the fatal paths store `$1FE4` raw, as the chip) | code review; oracle |
| S2 | no stage-1 source touches the 0.2.6 register page (`$1FE0-$1FFF` in RAMDP) or types a clock | `check_tree.py` rule 5 (5 planted mistakes caught) |
| S3 | every wait before the 68000's release is bounded | `tests/s1/boot_tests.c`; co-sim T-B10 (released at 61 ms) |
| S4 | the brain's bytes and addresses never move (IROM 0x5360-0xD2EB, the code window) | `check_images.py s1` |
| S5 | the debug save writes only inside 0x1000-0x1FFF, and nothing when the save RAM is 4 KB; version 5: a planted version-4 record and three reboots carry `prev2` and its chain as `dbgsave.h` says (section G of tests/equiv/q1_save.py; version 6: its layout, the 2026-10-19 lateness update); version 6: the CPU MATE late count equals a Mega CD link stub model's own late ARMs, each counted once, and late_max the largest readable lateness (the fix of 2026-10-19: seeds 3 / 5 / 7 / 11 to the quit and the placed races of section F), and the album's state reaches the save and `prev2` (`tdiag_s1.py`, its negative control and that fix's two planted faults); TEST's SAT snapshot layout 2 keeps the planted tables and flags every copy a frame start came after the take of (section H of tests/equiv/q1_save.py, its race and take race) | `fuzz_s1.py --q1` |

---

## 4. TEST and RELEASE

| | TEST | RELEASE |
|---|---|---|
| per-level counters, boot milestones, L1 latency per post (from STAMP_B), 84 window-off time | yes | compiled out |
| freeze telemetry: MCU heartbeat (the watchdog tick count), 9494 count and the last one's time, the last post; the VDP frame count (the VS counter, B Jam's decision of 2026-10-13: FPGAIO slot 16 VSCNT, the vertical syncs since reset, MCU interface v1.1, the RTL of 2026-10-13; the firmware reading lands with the v1.1 firmware change) so a freeze log tells a dead VDP from a dead 68000 | yes | compiled out |
| the debug save (upper half of the 8 KB `.sav`, decoded by `tools/dbgsave.py`; the previous session's record kept across a Soft Reset; written by a fatal halt too; version 5, the 2026-10-17 debug-save update: the previous session's decoder, CPU MATE, feeder, exception, dispatcher and stack counters and their worst over the chained sessions, `DBG_B_PREV2`, because the Pocket's quit restarts the core before it reads the save; version 6, the 2026-10-19 lateness update: the CPU MATE answers armed late counted one by one, with the largest lateness and the short-path calls, and the album's state: the MD+ result word, XLINK's CDDA underruns and ring writes lost, the last album call and play request, the wait for a requested track to play) | yes | nothing written |
| the register-write oracle log and the ordered audio-call log | yes | no |
| the RTL sprite decoder's read-backs (MCU interface v1.2, FPGAIO slots 18-22: state, words, START -> GO time, the smallest GO -> first window read margin, the count of window words served ahead of the decode) in the debug save (version 4, `DBG_B_DEC`) | yes | no |
| `printf` | dropped (no UART on the Pocket) | dropped |

H1 and H2 run the TEST image (it carries the telemetry); a 10-minute RELEASE smoke follows on the same bitstream.

---

## 5. Open

- **L1 body length** (finding 3): AD, D1 and B6 bodies run 3-8.5 ms with interrupts off. Firmware-only fix; the
  W5 / W9 decision. Watch item for the first-boot 84 (it must not land behind such a body; on the recorded path it
  cannot (inferred)).
- **CPU MATE answer lateness** (finding 6). Measured in the W14 co-sim before the first 2026-10-14 change; the first 2026-10-14 change (L2c) is proven on
  the RV32 model only (estimated board, the brain's real code): a co-sim of the CPU MATE branch's images and the hardware's TEST
  telemetry (the glue's `late_seen`; the 2026-10-19 lateness update: it counted every publish while the stub's sticky flag was up, so version 6 of the debug save counts each late answer instead) are still to come. Left after L2c: the interim SFX feeder's ticks (L2a, every
  133.5 us while a channel plays, ~74 us of fixed cost a tick in the model) preempt the call; with SFX playing they
  are ~90% of the remaining lateness (word ARMs late 10-22% of calls in TEST, model time; game-visible stale reads 0
  on the solo route, 2-9 calls in 2,412 on the Arcade 3P route). The RV brain alone is slower than the original on a
  few calls (`ex_17_bigfoe_fight`: 22 of 2,704 with nothing else running, TEST): no schedule reaches those.
  **The 2026-10-15 change accepts lateness back** (finding 7, B Jam's rule: the game first): the call waits for the decoder, the
  jobs and the feeder again (RV32 rig, priced clock: calls with a stale game read 0 -> 2-96 a run, as many as on test
  build 1 1-100; the latest word 27-68 ms, the longest at stage loads behind a DA decode, 9 ms otherwise; 2-8 sends
  found the buddy busy). The cart's way to have both is the CPU MATE on its own CPU; the
  firmware lever was the decode time; the decoder-in-logic change takes the decode out of the firmware altogether (the RTL decoder, decision 4 of the 0.3.0 plan
  brought forward by B Jam's decision of 2026-10-15), and the call gets that time back.
- **R10 over-reads:** the game's VDP DMA reads 128 words past two DA07 streams (title load and a stage load). Stage 1
  serves the next SDRAM words, as 0.2.6; the cart's value needs a hardware capture (CART_FPGA_SPEC F-D5). Copying it
  is firmware-only.
- **W13** (the chip lockstep on every command) is in progress in its own worktree.
- **Sizes** (measured, the stage-1 build of this commit, `build/s1/pocket72k/*/layout.txt`, TEST / RELEASE): IROM
  below the brain 19,204 / 15,944 of 21,344 B; above it 18,492 / 14,648 of 19,732 B (the decoder-in-logic change: the firmware decoder
  gone, 2,140 / 1,240 B free in TEST); `wram_data` 5,664 / 5,360 of 6,176 B; the WRAM code window 9,412 / 8,832 of
  16,384 B; `wram_upper` 7,704 / 4,200 of 16,384 B; stack bound (fwstack) 3,092 / 2,292 of 5,120 B. The dispatcher
  (7,024 B TEST / 7,004 B RELEASE) and the scheduler are larger than the plan rows (`docs/BUDGET.md`).
  The sprite-values update (finding 9): IROM below the brain 19,860 / 16,604 B, above it 18,572 / 14,684 B (TEST / RELEASE; free
  2,644 / 9,788 B in all), `wram_data` use unchanged (.bss +4, .noinit -4), the stack bound unchanged; the dispatcher
  7,112 / 7,096 B, the 0.2.6 sprite engine 4,060 / 3,884 B (`tools/budget.json`).
  The AF-reply update (finding 10): IROM below the brain 19,992 / 16,712 B, above it 18,592 / 14,704 B (free 2,492 /
  9,660 B in all), the dispatcher 7,132 / 7,116 B, the 0.2.6 sprite engine 4,192 / 3,992 B; WRAM and the stack bound
  unchanged.
  The 0.3.0-s1t4 firmware (findings 9-11: the AF-reply update and the misc update of 2026-10-17 together): IROM below
  the brain 20,888 / 17,524 B, above it 19,028 / 15,088 B (free 1,160 / 8,464 B in all), `wram_data` 5,744 / 5,456 B,
  `wram_upper` 7,960 / 4,456 B; the dispatcher 7,548 / 7,480 B (the base build + the AF-reply update's +108 / +112 + the
  misc update of 2026-10-17's +416 / +364: the two add exactly), the 0.2.6 sprite engine 4,192 / 3,992 B, the interim
  album 3,468 / 3,124 B, the re-hosted bodies 3,954 / 3,550 B; the WRAM code window and the stack bound (3,092 / 2,292
  B) unchanged.
  The merge of 2026-10-18 (finding 12, TEST only): IROM below the brain 21,140 / 17,524 B, above it 19,508 / 15,088 B (free 428 /
  8,464 B in all), `wram_data` 5,776 / 5,456 B, `wram_upper` 8,180 / 4,456 B; the TEST counters and debug save 3,160 B
  (cap 3,160) and 668 B wram, the legacy debug aids 2,059 B and 237 B wram, the re-hosted bodies 4,026 / 3,550 B, the
  linker's fill 42 B of TEST wram (cap 40 -> 42); RELEASE and the stack bound (3,092 / 2,292 B) unchanged.
  the fix of 2026-10-18 (finding 13): IROM below the brain 21,132 / 17,548 B, above it 19,564 / 15,088 B (free 380 / 8,440 B in all);
  the scheduler 2,868 / 2,400 B and 152 B wram, the dispatcher 7,568 / 7,480 B, the re-hosted bodies 4,062 / 3,550 B
  and 92 / 66 B wram, the 0.2.6 sprite engine 4,172 / 3,992 B, the linker's fill 36 / 23 B of wram; the stack bound
  3,108 / 2,324 B.
  the SFX fix of 2026-10-19 (finding 14): IROM below the brain 20,428 / 17,016 B, above it 18,796 / 14,320 B (free 1,852 / 9,740 B in
  all: the stage-1 SFX moved to the code window, 13,964 / 13,272 of 16,384 B); `wram_upper` 8,532 / 4,808 B; the
  bodies 4,090 / 3,578 B, the feeder 1,948 / 1,476 B; the stack bound 3,108 / 2,340 B.
- **The SFX after the SFX fix of 2026-10-19 (finding 14):** still ours (B12): the chip's low-pass on the 0x1000, echo and spread voices,
  its pan law, D5's SFX echo (no RTL echo bus), a looped pass's short last block, and the block count's phase against
  the chip's TIM6-polled mixer (estimated). Done in test build 4: the RTL's lowest rate is the chip's 4,800 Hz (48,000 /
  10, the RTL of test build 4 (2026-10-19); it was 48,000 / 9 Hz, and rate-5 sounds played 11 % fast and short). B Jam's
  hardware check: the fast door break as Tug in the Block 888 cell (walk right, punch at once), then out of the cell:
  the alarm stops.
