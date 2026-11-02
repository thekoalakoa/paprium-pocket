# Stage 1 plan: new core, same game (the work order)

Paprium 0.3.0, stage 1: the step after stage 0 (the 0.2.6 firmware moved into this tree): the new scheduler,
dispatcher, boot and watchdog (the s1 source set of `tools/fwbuild.py`, built with `FW_S1`) and every MCU and RTL
hardware change 0.3.0 needs. Written 2026-10-11 by our
planning pass `workorder` from five design studies (`iface`, `cartrtl`, `platform`, `fwcore`, `checks`), checked
against each other, against the specs and the 0.3.0 plan (which is not in this tree), and against the RTL, the ROM and
our study of the chip where a claim carries weight. **Design only: nothing here is built.** Companions: `docs/MCU_INTERFACE.md` (v1.0, the
frozen MCU interface), `docs/CART_FPGA_SPEC.md`, `docs/BOOT_SPEC.md`, `tests/equiv/allowlist.json`.

**What stage 1 is** (the 0.3.0 plan's stage table): one fit that swaps mega-ppm's firmware for ours with 0.2.6
behaviour, and makes every MCU and RTL hardware change 0.3.0 needs, once. Stages 2, 3 and 4b are firmware-only after
it. Every fit round is 6 FPGA fits with different placement seeds, then B Jam's ~60 min warm play+pause soak on
hardware (the timing gate alone is not trusted since the VRAM trial fit with seed 4 froze). The MCU is the cart's
NEORV32 soft CPU in the core; RTL is the core's hardware description; RAMDP is the cart RAM both the 68000 and the cart
chip see; ALM and M10K are the FPGA's logic and block-RAM units; a co-sim is a simulation of the core's RTL running the firmware.

**How numbers are known.** Measured = read from a fit, a run, a report or a file; estimated = arithmetic on measured
parts; not known = nobody knows. "(verified)" = verified in code or a run, "(read only, not run)" = code read only,
"(inferred)" = inferred. Work-days are estimates of the work, not calendar days.

**Item ids.** Z = freeze and docs, M = MCU platform RTL, C = cart FPGA RTL, S = Soft Reset and reset domains, V =
console-side robustness, F = features, W = firmware (paprium-fw), X = proof benches and tests, G = fit, H = hardware, Q = decisions
for B Jam. Test ids are the specs': R1-R12 (docs/CART_FPGA_SPEC.md section 15.2), T-B1..T-B15 (docs/BOOT_SPEC.md section 9), T1-T29 (the test
matrix of our 0.3.0 study, not in this tree), FZ1-FZ11 (the firmware fuzz invariants, section 4.7).

---

## 0. Findings first

1. **It fits, but only with the vram_alt swap.** The stage-1 fit is about **16,450-17,200 ALM** (estimated on the
   measured vram_alt trial base of 16,493-16,545) and **289-290 of 308 M10K**. Without the swap the same list lands at
   ~18,100-18,760 ALM, above the 18,215 pass zone. So vram_alt (V1) is load-bearing, and its soak is the top risk.
2. **The firmware fits the locked layout.** IROM firmware ~27.7 KB TEST / ~23.8 KB RELEASE of 41,076 B; the stack
   bound ~2.8 KB of 5,120 B (estimated). Hot WRAM data is tight: ~470 B free in TEST.
3. **The five designs disagreed on 18 points.** All are resolved here from the specs and the 0.3.0 plan (section 2), or listed
   as decisions. The biggest: one FPGAIO slot map (the firmware design had assumed another), only four cart registers
   stored, one owner for the Soft Reset hold, and the watchdog and the menu mute both in stage 1.
4. **Nine load-bearing claims were re-checked in the code** (section 3). Seven hold as stated. One is struck: the SDRAM
   port-2 mismatch after a reset cannot lose a write on this core (it is one stray read, finished inside the reset).
   One is refined: the open-bus byte the game reads with Mega CD = None is not `'B'` whichever word the bus holds.
5. **0.2.x has been setting the game's copy-protection flag** at the first food pickup of every session (measured in
   GPGX by `checks`; the test code and 0.2.6's per-lane RAMDP writes re-read here (verified)). A real cart cannot honour
   68000 byte lanes in RAMDP. Stage 1 fixes it (C7). What to do about 0.2.6, which awaits its push, is B Jam's call
   (Q8). **Resolved (2026-10-12):** 0.2.6 shipped with the fix (byte writes ignored, 2026-10-11, the release fit of the same day);
   0.3.0 writes the whole word (Q2, docs/ALLOWLIST.md, row B32).
6. **F-D3 is the cart's behaviour again** in paprium-fw: an uncommitted working-copy edit had turned it back to "keep
   0.2.6". B Jam's word while this plan was written (2026-10-11), "Keep it like the cart", and the allow-list review of 2026-10-11 both say
   the cart. This commit
   restores it (and fixes two rows that still said "keep").
7. **The effort is ~67-94 work-days, not the 0.3.0 plan's 7-12.** The calendar is about **4-6 weeks** from B Jam's
   answers to a soaked stage-1 test card (a hardware test build; estimated; best case ~3 weeks).
8. **Seven decisions are needed before any RTL is written** (Q1-Q7, section 11): battery RAM size, RAMDP byte writes
   (ignore or whole word), the EA 4-Way Play scope, the dormant options-at-reset latch, TeraDrive with a Mega CD unit,
   player 3's X/Y/Z, and the Scum! coin sound. Each has a recommendation.

---

## 1. What stage 1 builds

| area | what | items |
|---|---|---|
| MCU platform | NEORV32 without MTIME / UART / WDT; FPGAIO v1.0 (interrupt causes with acks, software interrupt, timer + compare, post stamp, WRAM lock, board-control bits); IROM 72 KB (fixed select); WRAM 48 KB (write-select off the half-cycle path); option word bits 24-26; one clock value | M1-M8 |
| cart FPGA | register file `$1FE0-$1FFF` with both views; `$1FE4` composer; busy generator; `$C000` window and the 84 view switch; FM bank XOR in game view; F-D3 (no answer at `$400000-$7FFFFF` with Mega CD = None); MCU byte views; RAMDP byte lanes (cart-correct) | C1-C8 |
| Soft Reset | 68000 held from every reset's first clock; reset-domain handshakes resynchronised; simulations of hypotheses 2 and 2b (the 0.3.0 plan's hypotheses about the Soft Reset black screen) and a dormant options-at-reset latch (Q4) | S1-S3 |
| console robustness | vram_alt with F1-F3 (and F4 only if needed); video crossing fix; SDRAM refresh yield; the inherited negative clk_md classes (Z80 enables first); the 0.3.0 plan's small levers | V1-V5 |
| features | Pocket-menu music mute; Hall of Fame bar fix (+ Scum! flip guard and coin-path fix); TeraDrive detection stub; Arcade Mode Off / On / Multiplayer with an emulated EA 4-Way Play | F1-F4b |
| firmware | four interrupt levels, the chip's dispatcher, status layer, job queue, C6, 81/82/84/85, watchdog; the board layer (boot, register accessor, stream, options); 0.2.6 bodies re-hosted; CPU MATE glue on the software interrupt; TEST counters and freeze telemetry | W1-W15 |
| proof | cart and MCU benches, interrupt fuzz, chip lockstep, system co-sim, 3-slot CPU MATE corpora, the two new L1 captures | X1-X7, W12-W14 |
| fit and hardware | 6 seeds per round, gate + class envelope + census, two soak candidates; B Jam's ~45 min list and the warm soak | G1-G3, H1-H2 |

What stage 1 does **not** change: the sprite engine (stage 2), the unpackers, saves, zoom and MegaWire (stage 3), the
bank cache (stage 4), the music (stage 5). Their 0.2.6 code moves in unchanged; the album, SFX feeder and VU stay.

---

## 2. Conflicts between the designs, and how they were resolved

| # | conflict | designs | resolution | basis |
|---|---|---|---|---|
| 1 | FPGAIO slot map: the firmware design assumed CAUSE in slot 6, MSI 8, counter 9-11 | fwcore vs iface | **iface's map**: CAUSE 8, MSIP 9, TIMER/TCMP/TCTRL 10-12, STAMP_B 13, WLOCK 15; slot 6 stays the legacy ack | the interface owner; firmware uses `pocket_map.h` names only |
| 2 | register storage: iface stored all ten registers; cartrtl and fwcore store four | iface vs cartrtl, fwcore | **only `$1FE4/6/A/C` stored**; `+8/+E/+12` act on write; `+10/+14/+16` dropped; the firmware accessor shadows and logs them | the chip reads only those (verified: docs/CART_FPGA_SPEC.md section 3.2); ~48 fewer flops |
| 3 | GO length width | spec 16 (proposed), cartrtl 20, iface 21 | **21 bits** | DA/AF lengths not measured; 21 holds the whole 2 MB workspace in words; +1 flop over 20 |
| 4 | TEST timing aid: post timestamp + stream status at `0x0B000020/24` | cartrtl (CR-11) vs iface (STAMP_A/B) | **STAMP_B (slot 13) + GO read-back**; CR-11 dropped; STAMP_A reserved (slot 14) for stage 5 | same numbers, counted once; STAMP_A has no stage-1 user and stage 5 is a fit |
| 5 | board-control enables MENU_MUTE_EN, OPT_AT_RESET_EN had no address | platform | **CTRL bits 4 and 5** (reset 0 on every reset) | free R/W bits (verified: `fpgio.sv`); no new decode |
| 6 | the 68000 hold on Soft Reset had three owners | iface P10, cartrtl CR-6, platform W5a | **one item, S1**: `ctrl` = 0x09 on every reset, `shell_reset` ORed into the hold, HOLD through a `synch_3` | all three are compatible; together they hold from the first clock and remove the marginal crossing |
| 7 | port-2 handshake after reset | iface (assertion only) vs cartrtl, platform (resync) | **resync `mem_req <= mem_ack`** plus the assertion; cartrtl's "lost write or wrong read" claim struck (section 3, #4). **As built (S2, 2026-10-11; the review of track S agreed):** a reset leaves the port-2 request alone, so an access already requested finishes inside the reset and the reset launches nothing; the benched `mem_req <= mem_ack` form could still launch one stray read (docs/MCU_INTERFACE.md section 8, erratum 2026-10-13) | the 0.3.0 plan's rule from hypothesis 4: resynchronise every handshake the boot depends on |
| 8 | watchdog stage | platform, `tools/budget.json` (stage 3) vs fwcore, BOOT-16, T10 (stage 1) | **stage 1**, in IROM | BOOT-16, docs/CART_FPGA_SPEC.md section 15.3 (mini-game 10 s with the watchdog as the chip has it), test T10 |
| 9 | menu music mute | docs/ALLOWLIST.md, row B7 (music at stage 5) vs the 0.3.0 plan's decision 5, docs/CART_FPGA_SPEC.md section 15.3 | **RTL hook built (F1) and enabled by the stage-1 firmware**; B7's stage column changes at the allow-list review (Z5; done 2026-10-13: B7 says stage 1); CTRL.MENU_MUTE_EN can turn it off without a refit | B Jam's decision of 2026-10-09: music stops in the menu in 0.3.0; the hook must be in the only fit before stage 5 |
| 10 | the ms counter (slot 1) | iface, platform retire; fwcore "either" | **retired**; `mdp.c` gets an `FW_S1` guard so its timeout still fires | -25..-30 ALM; TIMER replaces it |
| 11 | Arcade Mode and EA 4-Way Play twice | platform W9 vs checks CHK-3/CHK-4 | **one item, F4**; CHK-4's wider scope (the tap with Arcade Mode Off) becomes Q3 | same files and proofs |
| 12 | HOF cave move and the coin-path fix | platform W7 vs checks CHK-2 | **one item, F2** | same cave source and table |
| 13 | RAMDP byte lanes | cartrtl CR-12 (whole word, if the run says so) vs checks (run done: both forms pass) | **C7 builds the form B Jam picks (Q2)**; per-lane is out | Measured: per-lane fails the game's own test |
| 14 | album divider "NTSC /1119" | platform vs iface (compare 1118) | **compare `CLK_HZ/48000`**: 1118 at NTSC, the same logic | the counter runs 0..1118, a 1,119-clock period (verified) |
| 15 | ALM of the register file, busy, composer, byte views | the platform study counted 0 | **counted: track C +53..+171 ALM** | the platform study's count predates moving them into RTL |
| 16 | IROM "2:1 select" (the 0.3.0 plan, `pocket72k.json`) | the plan vs iface | **2048-deep slices, 5:1 + 2:1, fixed select and index** | the 0.2.6 module at EXT_KB = 40 misreads 10,240 words (verified) |
| 17 | effort and calendar | the 0.3.0 plan's 7-12 work-days, 2-3 weeks vs the designs | **~67-94 work-days, ~4-6 weeks** (section 9) | the designs' de-duplicated sums |
| 18 | F-D3 text in paprium-fw | uncommitted working copy vs the allow-list review of 2026-10-11 | **the cart's behaviour**, restored in this commit; the old diff kept in our working notes | B Jam: "Keep it like the cart" (while this plan was written) |

---

## 3. Load-bearing claims, re-checked by `workorder`

| # | claim (from) | re-check | result |
|---|---|---|---|
| 1 | The 0.2.6 `mcu_irom` misreads 10,240 of 18,432 words at EXT_KB = 40 (iface, measured Icarus) | `mcu_core.sv` 312-331: `XW = $clog2(10240) = 14`, so the index `addr[XW+1:2]` includes `addr[15]`, the select bit | **holds** (verified) |
| 2 | The WRAM write fires in the first cycle with the region decode and the lock on a half-cycle path (iface) | `mcu_core.sv` 186-189 (`we` from `ram_ce` while `idle` = 0), `memory.sv` 145-151 (negative-edge RAM, `LOCK_MAP[addr[13:9]]`) | **holds** (verified) |
| 3 | NEORV32 1.4.8.1 re-latches a level after the trap ack (iface) | `neorv32_cpu_control.vhd` 1389-1391 | **holds** (verified); the flush rule (docs/MCU_INTERFACE.md section 6.3) is required |
| 4 | After a reset, port 2 "can complete the MCU's request with a stale word (a lost write or a wrong read)" (cartrtl) | `paprium_mcu_mem.sv` resets `mem_req` and the write enables to 0; `sdram.sv` serves `ack2 != req2` as a **read** and sets `ack2 <= req2`; the reset envelope `shell_reset` lasts 3 steps of 2^15 clk_md (~0.6-0.9 ms) (verified: `core_top.sv` 796-820) | **struck as stated**: one stray read, done long before the MCU leaves reset. The resync (S2) stays, as the 0.3.0 plan's rule |
| 5 | The game's byte-lane self-test sets `$FF9986` on per-lane RAM, and 0.2.6 is per-lane (checks) | ROM `$2B83E-$2B874`: base pointer = 0 (RAMDP), word `$F2F0` to `$1F0E`, byte 0 to `$1F0F`, flag if the word reads `$F200` or the first write did not stick; `ramdp_io.sv` lanes from `cart_lwr` / `cart_uwr` | **holds** (verified). That it runs at every food pickup is measured by `checks` (GPGX marks), not re-run |
| 6 | The F-D3 tie-off cannot hang the 68000 (cartrtl) | `md_board.v` 788: DTACK = arbiter pull OR `ext_dtack` (verified); the path to the `$400124` reads (`$BCA1C-$BCA6A`) has no branch around them (verified: listing); the vramsim harness ties `ext_dtack` to 0 (verified: `tb_top.sv`) and that run reached gameplay | **holds** (inferred, strongly); R12(b) logs it directly |
| 7 | With Mega CD = None the game reads `$01` at `$400124`, so "no CD" (cartrtl) | `cmpi.b #$42,$400124.l` then `bne`: the last word on the bus is the address word (`$01xx`) or the next opcode (`$66xx`), depending on prefetch order; neither high byte is `$42` | **refined**: "no CD" either way (verified: listing; bus estimated); R12(c) runs it |
| 8 | `CLK_FREQ/48000` keeps the NTSC album divider identical (iface) | `paprium_cdda_play.sv` 131-139: compare `>= 1118`, period 1,119 | **holds** (verified) |
| 9 | The FM XOR adds at most one input on six bits (cartrtl) | `0xA8A2` = bits 15, 13, 11, 7, 5, 1 | **holds** (verified: arithmetic); timing still not known until STA |

The brain-neutrality finding (the brain touches only RAMDP, the flash word view, SRAM and WRAM) has two independent
measurements already (`iface` static scan, `fwcore` objdump) and was not re-run.

---

## 4. The work order

### 4.0 Order at a glance

```
Z0 docs (this commit)
 -> Z1 B Jam answers Q1-Q7
 -> Z2 interface freeze (pocket_map.h v1.0, board.h)   Z3 stage-1 RTL branch   Z4 bench conventions
 -> Phase 2, in parallel:
      M  MCU platform     C  cart FPGA      S  Soft Reset      V  console robustness
      F  features         W  firmware       X  benches and rigs
 -> Phase 3: integration and co-simulation (X6, W13, W14, X3)
 -> Phase 4: fit (G1 tooling, G2 rounds of 6 seeds, G3 two candidate images)
 -> Phase 5: hardware (H1 ~45 min list, H2 ~60 min warm soak)  -> exit
```

Can start at Z3 without the freeze: M4, M6, C5, V1-V3, V5, G1, X5. Everything that reads or writes an MCU-visible
register waits for Z2. **Critical path:** Z1 -> Z2 -> C1 -> C2/C3 -> W4/W6 -> W14 (system co-sim) -> G2 -> H2.

### 4.1 Phase 0 and 1: docs and freeze

| id | what changes | files | ALM / M10K | proof | depends | days |
|---|---|---|---|---|---|---|
| Z0 | This page and MCU_INTERFACE v1.0; F-D3 cart wording restored; the two "keep" rows fixed | paprium-fw `docs/`, `tests/equiv/allowlist.json` | 0 | run_all green | - | done |
| Z1 | B Jam answers Q1-Q7 (section 11) | - | - | - | - | his time |
| Z2 | Freeze: `pocket_map.h` v1.0 (MCU_INTERFACE Appendix A) = M8; `board/board.h` + `docs/BOARD_IFACE.md` (W1); `tests/check_board.py` compares the header with MCU_INTERFACE and the RTL defines | paprium-fw `board/`, `docs/`, `tests/` | 0 | check_board 0 differences; check_tree (core/ includes `board.h` only) | Z1 | 1 |
| Z3 | Stage-1 RTL working tree: a local branch from the 0.2.6 release commit. The release branch is never written. If Q8 changes 0.2.6, branch from the new release commit | paprium-pocket (new branch) | 0 | - | Q8 | 0.25 |
| Z4 | Bench conventions: tool paths (Verilator 5.050, Icarus, GHDL with our RV32 firmware bench, Unicorn, GPGX); `PAPRIUM_SFX = 0` in cart benches until V5; sized unsigned constants; `verilator -Wall` lint gate on new files; every run < 10 min (checkpoint segments) | scratch bench folders | 0 | - | - | 0.25 |
| Z5 | Spec and allow-list updates, for B Jam's review before H1: F-D4 row (after Q2); the 84 deadline timed against the first window-range fetch (`$D0A2`, ~1.12 ms in GPGX; limits unchanged) in docs/CART_FPGA_SPEC.md section 6 / R9 and docs/BOOT_SPEC.md section 4 / T-B11; docs/CART_FPGA_SPEC.md section 4 queue wording (firmware); allow-list: B7 (music mute from stage 1), B10 split (`$1FE6` bit 3 and the set half of bit 13 stay 0.2.6 until stage 5), B13 wording (TeraDrive, Arcade Mode), B17 wording (firmware restart keeps the RTL state), new rows (84 as the chip does it, watchdog halt possible, default refusal bit 9, DA07 as board work, SFX feeder on the timer grid). **Done 2026-10-13:** all of these, plus the later decisions as rows (B31-B33) and the completeness check's unlisted differences (B34-B36); `docs/ALLOWLIST.md` is the list in plain words for the review and `tests/check_tree.py` rule 6 keeps it in step with the JSON; rows marked PROPOSED wait for B Jam's yes | paprium-fw `docs/`, `tests/equiv/allowlist.json` | 0 | B Jam reviews | W15 | 1 |

### 4.2 Track M: MCU platform RTL (MCU_INTERFACE v1.0)

| id | what changes | files | ALM / M10K | timing risk | proof | depends | days |
|---|---|---|---|---|---|---|---|
| M1 | NEORV32: `CLOCK_FREQUENCY` from `CLK_HZ`; `USER_CODE` 0x50490100; MTIME, UART, WDT off; `mext/mtime/msw_irq_i` from FPGAIO; GPIO kept (F-D1) | `rtl/PAPRIUM/mcu_core.sv` | -140..-161 (estimated from measured entity rows 106.4 / 29.3 / 25.6) / 0 | low (removes logic) | GHDL boot: SYSINFO clock and USER_CODE read by crt0; rvboard faults on `0xFFFFFF90-A4`; the fit's entity table has no mtime / uart / wdt | M2; W3 (no UART, no MTIME in firmware) | 0.5 |
| M2 | FPGAIO v1.0: `addr[6:2]` decode; registered read + ack; CTRL = 0x09 on every reset, bits 4/5; slot 1 retired; slot 6 legacy ack; GO `[20:0]` + read-back; CAUSE {V,S,A,B} W1C, set wins -> `mext`; MSIP -> `msw`; TIMER/TCMP/TCTRL, registered signed compare -> `mtime`; STAMP_B; WLOCK; mailbox-A latch copying `$1FEA`'s filtered write (`addr[12:1] == 0xFF6`); S from XLINK `posts_s[0]` | `fpgio.sv`, `structs.sv`, `mcu_core.sv`, `paprium_cart.sv`, `paprium_xlink.sv` (one output), `core_top.sv` (wire) | +67..+141 (estimated: timer +40..+60, ms counter -25..-30, CAUSE + MSIP +6..+17, read mux +15..+30, read-backs +5..+10, STAMP_B +18..+23, WLOCK +10..+18, mailbox A +3..+8) / 0 | low (every source registered) | per-slot bench: reset values, W1C, set wins, signed compare across the 2^32 wrap, stamp capture, WLOCK sticky; R4; census replay: CAUSE.A once a frame from frame 190, S once per buddy post; GHDL interrupt fuzz: no lost event, no double entry with the flush rule, MEI > MTI > MSI | Z2; C1 (post pulses) | 3 |
| M3 | WRAM 48 KB: 24,576 words, `addr[15:1]`; write-select registered in cycle 0, half 0 written in cycle 1, half 1 + ack in cycle 3; lock = CONST (KB 11-26, 48-63) or WLOCK (KB 27-47); 24,576-line images | `memory.sv` (`paprium_wram`), `mcu_core.sv` (`mcu_wram`), `paprium_cart.sv` | +10..+25 (estimated) / **+16** (measured geometry) | **medium**: the seed-6 path; the design removes the decode and lock from it | our GHDL cycle bench: store 12, load 10 unchanged; lock bench; our RV32 lockstep run (not in this tree) of the pocket72k images on the stage-1 RTL; STA: WRAM write path >= +0.5 ns in every seed | M2 | 2 |
| M4 | IROM 72 KB: EXT_KB = 40 in 2048-deep slices (5 x 8 M10K); `sel_x <= addr[16] \| addr[15]`; index `{addr[16], addr[14:2]}`; image files unchanged; `mkmif` mapping | `mcu_core.sv` (`mcu_irom`); bitstream-update tools | -43..-58 (estimated vs 92.7 measured) / **+18** (measured geometry) | low (mux shrinks) | Icarus 18,432-word bench (draft: 0 wrong; 0.2.6 module: 10,240 wrong); brain bytes at 0x5360-0xD2EB = `brain.bin`; `update_mif` identity guard on the first fit | - | 1 |
| M5 | Option word: bit 24 MENU (`inmenu_sys_s`), 25 JAP (`opt_jap`; `opt_mcu_sync` 5 -> 6), 26 PAL (parameter) | `core_top.sv`, `cartridge.sv:147`, `paprium_cart.sv:77, :211` | +1..+3 / 0 | none | T2 / T-B9 (watchdog gated); T-B4 / T-B14 (the ROM header's region letters for both regions; JP features follow the version register as in 0.2.6); bit 25 per Console value in sim | - | 0.5 |
| M6 | Clock-following RTL: `CLK_HZ` / `CLK_MD_HZ` parameters in `core_top`; NEORV32 generic; album compare `CLK_HZ/48000`; album mute `CLK_HZ/20`; `mcd_link` `DIV = CLK_MD_HZ/50`; `dac_clocker`; SDRAM refresh compare (with V3); `clkcheck.py` lint | `core_top.sv`, `paprium_defs.sv`, `mcu_core.sv`, `paprium_cart.sv`, `paprium_cdda_play.sv`, `paprium_mcd_link.sv`, `sdram.sv`, `scripts/clkcheck.py` | 0 / 0 | none | T23: benches at PAL = 0 and 1 (48 kHz tick, album rate, 12.5 MHz tick, refresh interval equal in us within 50 ppm); NTSC bit-identical except the mute count (2,684,658 vs 2,685,000 clocks, 6 us) and the decided refresh 836; `clkcheck` fails on a planted literal | V3 | 1-2 |
| M7 | SRAM image route, no RTL change: APF data slot -> bridge 0x40000000; header (magic, interface major, length, CRC-32); XCFG bit 16 lock after the check | package `data.json`; board layer | 0 (loader kept, already in the base) | none | APF load and header check on hardware (content: stage 3); lock test | stage 3 for content | 0.5 |
| M8 | `pocket_map.h` v1.0 and `tests/check_board.py` (= Z2) | paprium-fw | 0 | - | check_board | Z1 | (in Z2) |

### 4.3 Track C: cart FPGA RTL (CART_FPGA_SPEC)

| id | what changes | files | ALM / M10K | timing risk | proof | depends | days |
|---|---|---|---|---|---|---|---|
| C1 | Register file and both views: `$1FE4/6/A/C` stored (MCU lanes; 68000 lanes on `+A`/`+C`; a 68000 write wins a same-clock MCU write); registered MCU read (`+4` = stored word, others 0); registered 68000 view (`$1FE4` = `busy<<2 \| model` bits 6, 8-10; stored `$1FE6/A/C`; others 0); region 0x0B decode; `post_a` / `post_b`; `ramdp_io`: no RAMDP write on the page, `cpu_dati` = page ? register : RAM, `debug_cpu_write` ungated for the cmdlog variant | new `rtl/PAPRIUM/paprium_regfile.sv`; `structs.sv`; `mcu_core.sv`; `paprium_cart.sv`; `ramdp_io.sv` | +70..+110 (estimated) / 0 | **medium** on `mcu_dati -> rv_di` (~+0.7 ns headroom): registered data, one shared registered block for regions 0x01 and 0x0B | R1, R3, R4, R5; T-B1, T-B6, T-B8; chip-runner oracle 15.1 with the rig's model at 0x0B000000 | Z2 | 2-3 |
| C2 | Busy generator: `busy = guard \| ~stream_valid`; guard set by a 68000 `$1FEA` write with high byte DA / DB / F2 (set wins), cleared by an MCU `+A` write, a clearing `+12` write or GO; `stream_valid` set by GO, cleared by `+12` (0 or bit 15), `remaining` = 0, `window_en` falling, reset; 21-bit `remaining`, one per delivered word, saturating; GO wins a same-clock decrement | `paprium_regfile.sv`; `fpgio.sv` (slot-7 strobe); `paprium_cart.sv` (`word_delivered`) | +20..+36 / 0 | low | R8 (census posts with up to 0.32 ms injected MCU latency: 0 bit-2 timeouts, 0 stale-ready polls); R10; R1; R2; oracle rule T4 (GO follows each stream start) | C1, M2 | 1-1.5 |
| C3 | `$C000` window and the 84 view: `$1FE8` bit 0 = 1 -> window on; `$1FE8` = 0 or `$1FEE` = 0xAF5B -> window off and `mini_view` = 1; off at every reset; `stream_cs` uses `window_en & ~mini_view` (`sdram_en` retired); `mini_view` synchronised into clk_md | `paprium_regfile.sv`; `paprium_cart.sv:117`; `fpgio.sv`; `cartridge.sv` | +3..+8 / 0 | low | R6; R9 / T-B11 (8400 write -> window and XOR off >= 0.1 ms, <= 0.5 ms, fail above 1.0 ms; the mini-game's first window-range fetch is ~1.12 ms, measured GPGX); T-B3; rig: every GO follows a `$1FE8 = 1` since the reset | C1; W4 (84 as the chip does it) | 0.5 |
| C4 | FM XOR + checksum quirk out: `rom_xor` decided at the read launch (`$2000-$7FFF`, not the stream, not `mini_view`); capture `rom_data ^ (rom_xor ? 16'hA8A2 : 0)`; any future ROM patch inside `$2000-$7FFF` stored pre-XORed; the checksum-quirk logic gated with `!PAPRIUM` | `rtl/cartridge.sv` (:315, :323-331, :994-1020, :1149-1156) | -57..-25 (XOR +3..+10, quirk -35..-60) / 0 | low-medium on `sdram dout -> cart_data` (9.31 ns): only six bits gain an input; compare each seed with 0.2.6 seed 2 | R7 (every word `$0000-$FFFF` in both states); the Z80 byte path in the full-system harness in < 10 min segments; B24; stage 5 FM by ear | C3 | 0.75-1.25 |
| C5 | F-D3: `cart_cs_ext` gated with `!(PAPRIUM && paprium_cd_none)`; `paprium_cd_none = (opt_cd_unit_s == 0)` from `core_top` (clk_md); the unit stubs untouched | `rtl/cartridge.sv:897` + one port; `core_top.sv` | +1..+3 / 0 | low | R12: (a) slice sim, None: no `data_en`, no SDRAM read, no `dtack_ext` at `$400000-$7FFFFF`; units: answers identical to 0.2.6; (b) md_board: each such read ends on the arbiter's DTACK; `/CE0` never at or above `$400000`; (c) `$BC944` with open-bus answers on all 8 consoles: no CD; (d) T18 probes unchanged. Allow-list B25 | - | 0.5 |
| C6 | MCU byte views: RAMDP `addr[23]` arm returns the bytes swapped inside each halfword; flash: `addr[23]` latched in state 0, swap at the `mem_dout` captures, writes gated; both read-only | `paprium_cart.sv:155-163`, `ramdp_io.sv`, `paprium_mcu_mem.sv` | +16..+36 / 0 | medium (RAMDP arm on `rv_di`; fallback: swap in the firmware accessor); low (flash, at a register input; the X0 port-2 SDC exception must still match) | R11; benches: all 8 KB through both views, every flash byte through a behavioural SDRAM; rig: no store to a byte view | C1 | 1 |
| C7 | RAMDP 68000 byte writes per Q2: ignore (`cpu_we` only when both lanes) or whole word (both lanes on either) | `ramdp_io.sv` (`cpu_we`) | 0..+3 / 0 | none | co-sim of the `$2B83E` sequence never reads `$F200` (ignore: `$F2F0`; whole word: `$0000`, which also proves FX68K puts the byte on both halves); T19; L1 corpora 0 differences (0 game byte writes in 203,526 frames, measured) | Q2 | 0.5 |
| C8 | SDC: C2c (68000 write data into register flops, hold-only false path), MV (`mini_view` first stage), the HOLD synchroniser (S1); each guarded with `xf_col` | `target/pocket/core_constraints.sdc` | 0 | removes false hold failures only | per seed: each collection matches its intended registers (no empty-match warning); `sta_xcheck` clean | C1, C3, S1 | 0.5 |

### 4.4 Track S: Soft Reset and reset domains

| id | what changes | files | ALM / M10K | timing risk | proof | depends | days |
|---|---|---|---|---|---|---|---|
| S1 | 68000 held from every reset's first clock: CTRL = 0x09 on `md_srst`; `md_reset_effective = md_reset \| (paprium_active & (sync3(paprium_md_reset) \| shell_reset))` | `fpgio.sv:47-50`, `core_top.sv:1075` (+ `synch_3`), SDC (C8) | +2..+7 / 0 | positive: removes the marginal `ctrl[0]` crossing (seed 5 failed hold there); the release moves ~28 ns once per boot | T-B7 (B Jam's decision of 2026-10-13: with the Pocket menu open 0 68000 bus cycles between the reset request and the release; with it closed at most ONE cycle may start after the request, within 0.25 us, never a write; ym6045 sweep, 24 phases; cold boot unchanged. Measured on the RTL of 2026-10-12: open 0 in 24; closed one cycle in 8 of 24 at 9-148 ns, no write landed; BOOT_SPEC T-B7 says how "never a write" is read); full-system checkpoints (title, stage with album, CPU MATE fight), Soft Reset at 24 phases x 3: non-memory state at release = power-on; T-B12; R1 | M2 | 1-2 |
| S2 | Reset-domain audit and resync (the 0.3.0 plan's hypothesis 4): `mem_req <= mem_ack` (as built: the reset leaves the port-2 request alone, section 2 row 7); stream pointer / ack toggles reset or resynchronised; CRAM port B drained before the release; CDDA buffer / fetch credit resynchronised; the album init after the release (firmware); bounded waits and TEST milestones (W6, W10) | `paprium_mcu_mem.sv:41-46`, `paprium_cart.sv`, `cartridge.sv`, `paprium_cram.sv`, `paprium_cdda_buf*.sv`, `paprium_cdda_fetch.sv`, `core_top.sv` (optional drain hold) | +2..+10 / 0 | low-moderate (a mux on `mem_req`; the P2r hold exception stands) | firmware sim of the stage-1 boot with the real cart RTL and a CDDA / APF model, Soft Reset at random phases (album fetch, target commands, MCU SDRAM and CRAM bursts): the 68000 released within the bound every time (T-B10, T27); one micro-bench per handshake pair; reset-sim assertion that port-2 `req`/`ack` agree before the MCU leaves reset | S1, W6 | 3-5 |
| S3 | Hypotheses 2 / 2b proved or refuted in simulation; the "options apply at reset" latch built dormant if Q4 = yes (CTRL bit 5; 0 = 0.2.6's live options) | `core_top.sv`; `paprium_addons.sv` (optional stub reset on a unit change) | +10..+15 if built / 0 | low | Hypothesis 2: static census of 68000 loops on the Mega CD registers + GPGX fake-CD drop at 100 random frames; hypothesis 2b: Unicorn boot runs over every Console x unit transition; latch: a slice simulation of the 0.2.6 RTL and power-on sweep (0 mixed views), enable 0 = today | Q4; M2 | 2-3 |

### 4.5 Track V: console-side robustness

| id | what changes | files | ALM / M10K | timing risk | proof | depends | days |
|---|---|---|---|---|---|---|---|
| V1 | vram_alt (design B, no G1) with F1-F3 as vram1, default on; the original behind `VRAM_ORIG` | `rtl/upstream/nuked-md/vram_alt.v` (from the trial file + F1-F3, md5 c1836fab), `vram_alt_ram_syn.v` (08b22f1b), `md_board.v`, `nuked-md.qip` | in the base: 16,493-16,545 (measured trial, seeds 4/3) = -1,515..-1,722 vs 0.2.6 incl. seed noise (estimated in-core -1,254..-1,272); F1-F3 0..-5 / **+2** (measured) | low-moderate: measured better on every path that changes VRAM; the seed-4 freeze mechanism not known | T26 on the exact file: 1.64 G clocks of Paprium 0 mismatches; md_board recordings; vdp suites 100 M each; 18 corner files; vendor-model bench in 9 pieces; mutants caught; F1-F3 lockstep vs the trial file 0 mismatching clocks; G1 census; H2 soak | G1 | 2-3 |
| V1b | F4 shadow pins, **only if** round 1 shows vram1 class C or D below 0 in 2 or more of 6 seeds | `ym_lib.v`, `ym7101.v`, `fc1004.v`, `md_board.v`, `vram_alt.v` | +3..+15 / 0 | touches Nuked latch modules (exact by construction) | assertion `pin_q == pins` on every clock (replay, recordings, 145-reset campaign); V1 suite again | G2 round 1 | 1.5-2.5 |
| V2 | Video crossing: scanline-filler inputs registered once on the dot clock; SDC lines 47-58 -> `-start -setup 0` general[1] -> general[2]/[4] + false path into `h32_sync`; the rule comment; APF slot word cleared in blanking | `rtl/scanline_filler.sv`, `core_constraints.sdc`, `core_top.sv` | +7..+14 / 0 | low; the 28 capture flops must sit next to `cofi` | T24 `vidsta.tcl` every seed (exactly 28 reg->reg pairs per dot clock, 0 levels, 4 corners); RTL boot-phase sweep (line count, DE, first pixel, slot latch identical) | G1 | 1-1.5 |
| V3 | SDRAM refresh yields to a waiting port 1; top-refresh compare from `CLK_MD_HZ` (836 NTSC) | `rtl/sdram.sv`, `rtl/cartridge.sv` | +2..+6 / 0 | low | T25: Icarus `tb_p1` 20-row sweep on the exact file (0 late port-1 reads, max D 13); 4 system runs 0 chain-late reads; assertion: interval <= 845 ticks, 8,192 refreshes in 64 ms. Known gap: `boost2` composition path; zero margin at D = 13 | M6 | 0.5-1 |
| V4 | Inherited negative clk_md classes: the Z80 latch enable as an exact look-ahead register `zclk_q` (with `max_fanout`); `max_fanout` on `sl_m5` / `sl_disp`; Scum! `rom_addr -> data` multicycle by protocol (or a 2-stage lookup); FX68K `Abd -> pswCcr` only if proven enable-gated | `md_board.v`, `fc1004.v`, `ym7101.v`; qsf / SDC; `paprium_scum.sv` (option) | +5..+40 / 0 | moderate (Nuked's Z80 clock enable; exact by construction) | assertion `zclk_q == ZCLK` every clock (replay, recordings, 145-reset campaign); Scum! bench (data stable >= 2 clocks before served); G1 census: Z80 enable class >= 0, every other class no worse than shipped seed 2 | G1; F2, F4 (the Scum! table) | 3-5 |
| V5 | The 0.3.0 plan's small levers: SDRAM output registers in I/O cells + SDRAM I/O constraints; IIR multicycle scoped to `audio_cond`; SFX mixer literals made explicitly signed (Quartus already builds them signed; the simulators then match) | `sdram.sv` / qsf, `core_constraints.sdc`, `audio_sfx.sv` | -12..0 (estimated) / 0 | improves the SDRAM output paths | STA on the SDRAM I/O paths; `audio_sfx` in Verilator = a signed reference model; `sta_xcheck` | - | 1-2 |

### 4.6 Track F: features

| id | what changes | files | ALM / M10K | timing risk | proof | depends | days |
|---|---|---|---|---|---|---|---|
| F1 | Pocket-menu music mute: album `osd_pause(inmenu_sys_s & MENU_MUTE_EN)` (pauses in place, resumes), cart SFX pair forced to 0 under the same term; FM/PSG mute unchanged; firmware sets the bit at boot | `core_top.sv`; `fpgio.sv` (CTRL bit 4 out) | +2..+10 / 0 | low (bit already on clk_sys) | T2: RTL bench (menu open: ring consumption stops, output 0; close: resumes at the same ring address); RV32 runner with the bit | M2, M5 | 0.5-1 |
| F2 | Hall of Fame bar fix: Scum! pad cave -> 0x0BF040, REGS -> 0x0BF0C0, hook `0x0B2394/6`, `A_P1/P2_PRESS = 24'h05F864/5`; `check()` forbids any Scum! word in 0x11C560-0x11C75F; **flip guard** (enables change only on a served read outside every patch group); **coin path**: load a1/a2/a3 (saved) before `jsr $0B5960`, coin sound per Q7 | `scripts/scum_pad_cave.s`, `scripts/scum_table.py`, `rtl/PAPRIUM/paprium_scum.sv`, `docs/SCUM.md` | -2..+22 / 0 | moderate (the Scum! decode is seed-sensitive; V4) | T22: `equiv.py` 1,568 cases 0 differences; `sentinel.py` region-unread extended to Original, Arena and 2P name entry; GPGX pixel compare of the 1,278 HOF frames; flip-guard bench; coin capture: 0 RAMDP byte writes (today 2 per coin), +1 credit per press | V4; Q7 | 2-3 |
| F3 | TeraDrive detection stub: Console list "TeraDrive" = 8 (bridge 0x54 -> 4 bits); `paprium_opts` case 8 = {JP, version 0, model 0000, expansion per Q5}; `td_en`; `vram_td_stub` (bank 2 random port on WE1/OE1/RAS1/CAS1 + RD, a store of <= 64 B, never drives SD, inert when off); the RD mux | `interact.json`, `core_top.sv`, `paprium_addons.sv`, new `rtl/upstream/nuked-md/vram_td_stub.v`, `md_board.v` | +40..+120 / 0..1 | moderate (the VDP's 128 KB outputs are no longer pruned) | T21: TD-0 bench finds the store index; `$BC81C` passes with the stub on, fails off; `$FF98DA` = code B with bit 15 set for TeraDrive, 0.2.6's word for every other Console; stub off = replay and recordings bit-identical | V1; Q5 | 3-5 |
| F4 | Arcade Mode Off / On / Multiplayer (list id 38 at 0x5C); stage lists only pick the stage; Multiplayer adds `G_ARC3P` (word 0x0B5B1A -> nop; the Grand Stick III DIP bit 0) and the emulated EA 4-Way Play on Dock pads 1-3 (P3 only for controller types 2/3; pad D constant), tap scope per Q3 | `interact.json`, `core_top.sv`, `paprium_scum.sv`, `scum_table.py`, `docs/SCUM.md`, README | +55..+80 / 0 | low-moderate | T28: pad-mux bench vs upstream `fourway.sv` (identical to today with the tap off); Unicorn `$B1DBC` / `$B1E3C` / `$B22C2`; GPGX rows measured by `checks` (Off: stock menu; On: `$FF98D4` = 0; Multiplayer: `$FF98D4` = 2, `$FF9903` = 4, P1-P3 join; Stage Select Arena -> stage `$1E` under arcade rules; CPU MATE + P3 HUD) re-run on the RTL's served words; APF load (12 of 16 variables with 3-Player Mode, Q3; measured in `interact.json`) | F2, F3; Q3 | 3-4 |
| F4b | (Q6) Player 3 X/Y/Z/Mode through the Scum! cave in Multiplayer (as built: through the game's own read of six-button pads behind the 4-Way Play with 6-Button on; the hook injects nothing there, which is also the double-credit fix; all 12 buttons land in records 1-3, measured) | `scum_pad_cave.s`, `scum_table.py`, `paprium_scum.sv`, `core_top.sv` | +20..+40 / 0 | low (grows the Scum! decode) | `equiv.py` P3 cases; sentinel; GPGX 6-button 4-way device | F2, F4; Q6 | 1-2 |

### 4.7 Track W: firmware (paprium-fw; 0 ALM, 0 M10K)

Sizes are estimated bytes (IROM unless marked). Source rule: `legacy/026` and `interim/album` gain only `#if FW_S1`
guards, so the milestone images stay byte-identical; the 0.2.6 command bodies move to `interim/s1/`.

| id | what changes | files | size | proof | depends | days |
|---|---|---|---|---|---|---|
| W1 | Board interface v1 (= Z2): `board/board.h` is the only header `core/` sees; `docs/BOARD_IFACE.md`; host fake board | `board/board.h`, `board/host/s1_board.c`, `docs/BOARD_IFACE.md` | 0 | check_tree; header = MCU_INTERFACE | Z1 | 1 |
| W2 | One build-time clock (`BRD_CLK_HZ`) and the clock-following figures (84 delay 100 us, watchdog tick, feeder grid, `BUDDY_MS_CYCLES`) | `fwbuild.json`, `tools/fwbuild.py`, `board/pocket/clock.h`, `buddy/buddy.h`, `tests/check_clock.py` | ~0 | T23 at 53.693175 / 53.203424 MHz (us equal +-1 cycle; frame figures unchanged); no NTSC literal; SYSINFO check | W1 | 0.5 |
| W3 | crt0 (no IO sweep; no reuse of the s0/s1-swapping 0.2.6 dummy handler; `wram_upper` `.bss` cleared); one trap entry; four levels `l1_mei`, `l2a_mti`, `l2b_msi`, `l3_thread`; timer wheel; MSI; hold / urgent plumbing | `board/pocket/crt0.S`, `trap.S`, `core/sched/*`, `pocket72k.json`, `tools/mkld.py` | 1,200 (872-1,672) + ~150 WRAM | fwstack scheme 030 as the gate (<= 5,120; PROXY 2,768 / 2,640); FZ5, FZ7-FZ9, FZ11; GHDL nesting | W1 | 2 |
| W4 | The chip's dispatcher (both mailboxes, 55-entry tables, gates, default refusal), status helper as the only `$1FE4`/`$1FE6` writer, 16-slot job queue and loop, C6 one-shot, 81/82/84/85, the 9494 head (inline in L1 in stage 1) | `core/dispatch/*` | 3,236 (2,472-3,878) + ~520 WRAM | L1 lockstep (view68 = the earlier 0.2.6 test build, except the B10 words = chip); oracle 15.1; FZ1, FZ2, FZ4, FZ6 | W1, W3 | 3-4 |
| W5 | 0.2.6 bodies re-hosted under the chip command map; DA07 as board work (no bit 14) with the chip's register order; DB06 / F2 / AE-B1 register sequences; F5 (float, 0.2.6) as an L3 job with a static 4 KB buffer | `interim/s1/*.c`, `fwbuild.json` | ~+500; +4,096 `wram_upper` | milestone images unchanged; host vs the shipped 0.2.6 build, strict outside the allow-list; FZ3 (GO before the bit-14 clear); R8 / R10 in the model | W4, W6 | 2 |
| W6 | Board layer: boot P0-P8 (hold, 8,160 B page copy, D45 patches, `$1E4 = $FF00`, region letters, app init, MegaWire status, enables, acks before enable, bounded release); register accessor with shadows and the oracle log; stream API (SPTR then GO); hand-off block (pages 0 in stage 1); options / region / menu; full reset; `mdp.c` `FW_S1` guard (timeout on TIMER) | `board/pocket/*.c`, `core/boot/appinit.c`, `interim/album` (guards) | ~1,000 + 692 | T-B1..T-B15; R1, R3, R6, R9, R11; T-B10 with an injected album stall; rvboard faults on MCU access to RAMDP `$1FE0-$1FFF` | W1, W2 | 2 |
| W7 | Watchdog + heartbeat (D35) with the menu gate, and the fatal-halt subset ("WE SUX" poll, MCU reset = hold + firmware restart) | `core/wdog/wdog.c`, `core/trace/fatal.c`, `tools/budget.json` (stage 3 -> 1) | 619 + ~200 | FZ10 at both clocks; T10; mini-game 30 s no trip; menu 10 s no trip | W2-W4 | 1 |
| W8 | CPU MATE glue on the MSI entry (SEND cause -> brain pending -> L2b `run_call`); housekeeping in L3 idle; MTIME -> TIMER; the trap leaves the code window | `buddy/*` | wcode <= 9,148 glue; +~400 | L9 CART-TIMED bit-exact (889,593 calls); brain md5 unchanged | W3 | 2 |
| W9 | Interim audio: the rate-aware SFX feeder and the VU row on the L2a wheel at all times; empty tick hooks; MENU_MUTE_EN = 1 at boot; ordered audio-call log | `interim/s1/audio_s1.c`, `buddy/zz_buddy.c` | ~300 | A4 as one ordered stream with job-tail attribution; SFX FIFO model: 0 underruns | W3, W8 | 1 |
| W10 | TEST counters per level, boot milestones (MCU up, 68000 released, first post, C6 posted / done, first 9494, bus-fault PC), **freeze telemetry** (MCU heartbeat, 9494 count, VS count if G1 builds it), 84 window-off time from STAMP_B; `tools/dbgsave.py`; printf without a UART (no-op or RAM ring) | `core/sched/stats.c`, `board/pocket/dbgsave.c`, `tools/dbgsave.py` | <= 2,800 TEST, 0 RELEASE; ~256 `wram_upper` | counters = the model's counts in rvboard; an rvboard-made `.sav` decodes | W3 | 1 |
| W11 | Build and static checks for the stage-1 source set: `s1` set in `fwbuild.json`; stack scheme 030 gates it; `budget.json` rows (board layer, interim s1, F5 copy, watchdog in stage 1, TEST counters); `check_tree` (no `reg_cmd` / `reg_status_*` / `0x02001FE` in stage-1 sources; no NTSC literal); move cold input sections to `irom_hi_text` (`.text` outgrows `irom_lo`); scheduler state where it fits (`wram_sched` has 12 B free) | `fwbuild.json`, `tools/stack.json`, `tools/budget.json`, `tests/check_tree.py`, `tests/check_tools.py`, `docs/LAYOUT.md`, `docs/BUDGET.md` | 0 | run_all green; negative tests fail when they must | W3-W10 | 1 |
| W12 | rvboard stage-1 board mode (register file, busy / guard / window rules, CAUSE, MSI, TIMER, menu bit, SFX FIFO) and the interrupt-race fuzz | `tests/equiv/rvboard.py`, `rtlmodel.py`, `fuzz_s1.py`, `run_all.py` | 0 | FZ1-FZ11 hold; six planted bugs each exit 1 | W3, W4 | 3 |
| W13 | Chip lockstep on every command (new stage-1 host side; scope file per command and field) | `board/host/s1_host.c`, `tests/equiv/chiplock_s1.py`, `s1_scope.json`, `synth.py` | 0 | solo, duo, attract, stage 04, the synthetic list, the first-boot capture, the three-player arcade capture: 0 differences outside the allow-list; visible `$1FE4 = 0004 \| model` for every Console | W4-W6 | 3 |
| W14 | System co-simulation with the stage-1 RTL (our Verilator model of the whole core, not in this tree, with the new cause / timer / MSI) | outside the tree; `tests/equiv/sys_s1` drivers | 0 | 0 late buddy words on the calls of our CPU MATE deadline study; "F5 not finished before the next VBlank" = 0 (else the synchronous-F5 switch); held posts 0; L1 max latency; 84 window-off 0.1-0.5 ms | M2, C1-C3, W8 | 2 |
| W15 | `docs/STAGE1_FW.md` (levels, command map, invariants) and the allow-list proposals for Z5 (done 2026-10-13) | paprium-fw `docs/`, `allowlist.json` | 0 | B Jam reviews | all | 0.5-1 |

**Fuzz invariants (FZ, from the firmware design):** FZ1 one finish per post; FZ2 status bits stored before `$1FEA := 0`;
FZ3 GO / pointer before the bit-14 clear, no stale "ready"; FZ4 bit 14 = queue not empty, never stuck; FZ5 no lost post,
ack before read; FZ6 one 9494 service, then `$1FEC := 0`; FZ7 shadow = register after every critical section; FZ8 held
posts after the tick end, in order; FZ9 urgent promotion meets its deadline; FZ10 watchdog trips only after > 40 ticks
with no 9494, never with the menu bit; FZ11 stack never reaches its floor; FZ12 (since 2026-10-13) no post body in L1 over
the 0.32 ms budget at the hardware CPI (the 0.2.6 AD compose listed apart until stage 2) and no block decode in L1;
FZ13 (since 2026-10-15; the version of 2026-10-14 was the reverse) no job waits for a CPU MATE brain call (none pending wherever the call's
code runs with interrupts open); FZ14 (since 2026-10-15; the version of 2026-10-14 was the reverse) the SFX feeder and the rest of the wheel
never wait for a brain call (the call runs with MTI open); DEC (with MCU interface v1.2, the RTL decoder in the
board model) the decoder's posts finish at once and the game never reads a block before it is decoded.

### 4.8 Track X: benches and rigs

| id | what | where | proves | depends | days |
|---|---|---|---|---|---|
| X1 | Cart benches: `tb_cartregs` (Verilator + Icarus; 68000 bus BFM, MCU wishbone BFM, the real `ramdp_io` / `fpgio` / `paprium_regfile`, a cartridge read-path slice with an SDRAM model filled from the ROM in place); a C++ reference model of the interface shared with the full-system harness | scratch bench folder | R1-R8, R11, R12(a), C7's sequence; model = RTL on random and recorded traffic | C1-C8 | 4-6 |
| X2 | MCU benches (FPGAIO, WRAM, IROM, both byte views, register port) and the rvboard v1.0 MMIO model (faults on removed IO) | scratch + `tests/equiv/rvboard.py` | MCU_INTERFACE I1-I4 | M1-M5, C6 | 2 |
| X3 | CPU MATE with three player slots: record 3-slot corpora (Multiplayer + CPU MATE + P3 on stage 1 and `$1E`; Arena mode + P3 if Q3 allows it); a call-by-call comparison with the reference brain build ("Build R") | our CPU MATE comparison bench (not in this tree) | 0 differences per call; 0 late words in the closed loop | F4 | 1-2 |
| X4 | 84 timing bench asserts against the first window-range fetch (`$D0A2`), fetches included | X1 bench | window and view off before any 68000 access at `>= $C000` after the 8400 write, within 0.5 ms | C3 | 0.5 |
| X5 | Add the first-boot capture (1,084 posts, 84) and the three-player arcade capture (89,895 posts, EC `$34`) to the L1 corpus: expected digests and the chip-side replay (84 handler, AE aging at slot count `$34`, 81 0F) | `tests/equiv/expected/host_final026.json`, `tests/equiv/README.md`; captures stay outside the tree | equivA PASS (measured by `checks`); chip replay 0 differences outside the allow-list | - | 0.5 |
| X6 | Integration sims: full-system (md_board + FX68K + stage-1 cart rules) for T-B3 (frame 22), R7's Z80 path and R12(b); a reset simulation of the 0.2.6 RTL for T-B7, S1, S2; Unicorn `run_bc944.py` for R2, R12(c), F3 | scratch | the RTL rows of docs/BOOT_SPEC.md section 9 and docs/CART_FPGA_SPEC.md section 15.2 | Phase 2 | 3-5 |
| X7 | Optional, last: the gameplay-stage full-system replay (12.6-13.4 h in <= 10 min segments); display equivalence only | scratch | vram_alt display equivalence in play | V1 | (machine time) |

### 4.9 Track G: the fit

| id | what | ALM / M10K | proof | depends | days |
|---|---|---|---|---|---|
| G1 | Gate tooling: `v1census.tcl` (vram1 classes A-D), `vidsta.tcl` + `diemodel.py` (28 pairs per dot clock), a clk_md class census against `base_census.txt` (shipped 0.2.6 seed 2), `sta_xcheck`, the STA query list (section 6); the class envelope; optional VS counter into clk_sys for the freeze telemetry | VS counter +10..+20 (estimated) / 0 | each script exits non-zero when its rule fails, on a planted bad database | - | 1.5-2.5 |
| G2 | Fit rounds: 6 seeds, one at a time (~3 h a round) | - | section 6 | Phase 3 green | 1 per round |
| G3 | Candidate images: RELEASE and TEST of the best two seeds with `update_mif` (the first fit proves `mkmif` = the Quartus mifs byte for byte); deploy candidate 1 to the SD per the standing order, with ALM / setup / hold | - | md5 of every image recorded | G2 | 0.5 |

### 4.10 Track H: hardware

H1 = B Jam's ~45 min list and H2 = the warm soak (section 7).

---

## 5. Budget

### 5.1 ALM (Cyclone V 5CEBA4: 18,480 ALM; fits passed up to 18,215)

| part | ALM | label |
|---|---|---|
| final 0.2.6 | 18,060-18,215 (seed spread; 18,097 on the release seed) | Measured |
| 0.2.6 + vram_alt (V1 base) | 16,493-16,545 (trial seeds 4 / 3) | Measured |
| track M (M1-M5) | -141..-14 | Estimated |
| track C (C1-C8, incl. the checksum-quirk lever) | +53..+171 | Estimated |
| track S (S1-S3; Q4 = yes: S3 latch +10..+15, dormant) | +14..+32 | Estimated |
| track V (V1's F1-F3, V2-V5; V1b not counted) | -3..+60 | Estimated |
| track F (F1-F4b; F4b only if Q6 = yes: +20..+40) | +115..+272 | Estimated |
| G1 VS counter | +10..+20 | Estimated |
| **stage-1 fit** | **~16,540-17,090, read as ~16,450-17,200** (seed spread +-100) | Estimated |
| margin to the 18,215 pass point | >= ~1,000 | Estimated |
| conditional V1b | +3..+15 | Estimated |

**Without vram_alt** the same list is ~18,100-18,760 (estimated): over the pass zone. If V1 fails its soak twice, stage
1 must drop F3 (-40..-120), F4b, S3 and the VS counter, and take the 0.3.0 plan's FIFO-in-block-RAM lever (-260..-330 ALM,
+6 M10K): ~17,600-18,400, still marginal at the top. So V1 is the plan, and its soak is the first thing H2 proves.

The 0.3.0 plan's final forecast with the swap (15,778 / 16,308 / 16,821) did not count track C (+53..+171) or the
stage-1 fixes and features; with them it is roughly 16,000 / 16,650 / 17,350 (estimated), still >= ~850 under the pass
zone.

### 5.2 Block RAM (308 M10K) and DSP (66)

| part | M10K | label |
|---|---|---|
| final 0.2.6 | 253 | Measured |
| vram_alt | +2 | Measured (trial) |
| IROM 54 -> 72 KB (M4) | +18 | Measured geometry |
| WRAM 32 -> 48 KB (M3) | +16 | Measured geometry |
| TeraDrive stub store (F3) | 0..+1 | Estimated |
| **stage-1 fit** | **289-290** | Estimated |
| Q1 = 8 KB battery RAM | +4 -> 293-294 | Estimated |
| fallback FIFO lever (only without vram_alt) | +6 | Estimated |

Stage 1 leaves 18-19 M10K. Stage 5 (the next fit) removes the album path and adds the synth; the 0.3.0 plan's final 0.3.0 with
the swap is 279-291, so stage 5 has to land under the same 308. DSP: 22 today, unchanged in stage 1 (estimated).

### 5.3 Firmware memory (pocket72k, locked; 0 ALM, 0 M10K)

| region | room (B) | stage 1, TEST / RELEASE (estimated from the measured pocket72k build) | note |
|---|---|---|---|
| IROM firmware | 41,076 | ~27,700 / ~23,800 (+-2 KB) | 13.3 / 17.3 KB free; `.text` outgrows `irom_lo` (21,344), so cold sections move to `irom_hi_text` (W11) |
| WRAM code window (`wcode`) | 16,384 | <= 15,876 (~15,500 with the trap moved out) | the glue must not grow |
| `wram_data` | 6,176 | ~5,700 / ~5,500 | **tight**: ~470 B free in TEST |
| `wram_sched` | 320 | 308 today | the wheel / scheduler state goes where it fits (W11) |
| `wram_upper` | 16,384 | ~4,500 (F5's 4 KB buffer, TEST counters) | |
| stack | 5,120 | bound ~2,800 (scheme 030, PROXY 2,768 / 2,640) | F5's buffer must stay off the stack |

CPU: stage 1 has no song engine; per-level load is measured on hardware from the TEST counters (W10). The L1 worst case
on RV32 is measured (risk 5): after the change of 2026-10-13 the 0.2.6 AD compose, ~1.4-1.6 ms at the hardware CPI; the 84 never waits
behind it (mailbox B, after the previous post's finish).

---

## 6. Fit plan

- **Entry:** Phases 2 and 3 green (X1, X2, X6, W12-W14, V1's T26 suite on the exact files), paprium-fw run_all green,
  estimated ALM <= 17,200.
- **Round:** 6 seeds, one at a time (~30 min each, ~3 h). Per seed:
  - the gate: setup >= -2.60 ns, hold > 0, `sta_xcheck` clean;
  - G1's census and the **class envelope**: reject a seed (even if it passes the gate) when a freeze-capable class
    (FX68K CCR / VD bus, VDP `io_data` / `io_address`, VA/rAS -> VD, Z80 internal) is more than 0.25 ns worse than
    shipped 0.2.6 seed 2, or the Z80 enable class is below 0 after V4;
  - `vidsta`: exactly 28 reg->reg pairs per dot clock, 0 levels, 4 corners pass;
  - STA queries: WRAM write path (target >= +0.5 ns) and read path; `mcu_dati -> rv_di` (register file and RAMDP
    byte-view arms); `sdram dout -> cart_data` against 0.2.6 seed 2; the HOLD synchroniser; C2c / MV / HOLD false
    paths match their registers; ALM and M10K against section 5.
- **Pick:** rank the passing seeds by their worst freeze-capable class margin; take the best two.
- **Images (G3):** RELEASE and TEST of both via `update_mif`, no refit. Deploy candidate 1 to the SD (standing order)
  and report ALM, setup and hold.
- **Hardware:** H1 and H2 on candidate 1's TEST image (it carries the freeze telemetry); then a 10 min RELEASE smoke
  on the same bitstream. A freeze on candidate 1: soak candidate 2 without a new fit. A freeze on both: the RTL is
  suspect; read the telemetry, then V1b / V4 changes and a new round.
- **A second round is triggered by:** no seed passing; vram1 class C or D below 0 in 2 or more seeds (V1b); both
  candidates freezing; any H1 item failing on hardware.

---

## 7. B Jam's stage-1 hardware test (~45 min), then the soak

On the Pocket only. Never a blank save on the real cart. Use candidate 1's TEST image; send the `.sav` afterwards.
Quitting the core is fine (debug save version 5, from 2026-10-17): the Pocket's quit restarts the core about 0.3 s before it
writes the `.sav`, so the record itself is that short boot, but it carries the session just played (`prev`, and `prev2`:
the sprite decoder's late words, flags and margin, the CPU MATE, feeder, exception, dispatcher and stack counters), and
the worst of them over every session since, so a quick relaunch and quit afterwards keeps its worst values. From
debug save version 6 (from 2026-10-19) it also carries the music's state at the quit (which track the album holds, whether it
plays, how long a requested track has waited, the CDDA underruns) and counts the CPU MATE answers armed late one by
one (version 5's count was every publish while a sticky flag stayed up: not a fault sign).

| # | test | pass | min |
|---|---|---|---|
| 1 | Power-on twice; the second time hold B | boots to the title; the hold-B line ends in a **space** (not 'S') | 3 |
| 2 | Each Console value, a Soft Reset after each change, incl. **TeraDrive** | the Boom Box picture as 0.2.6; TeraDrive shows its own picture and nothing else changes | 6 |
| 3 | Mega CD None, then a unit (CPU MATE); MegaWire Off, then On | as 0.2.6 | 3 |
| 4 | The 10-item list of the earlier 0.2.6 test build: select flicker, mode switching, Solarium float, no moonwalk, credits, elevator, weapon drop, attract demo, CPU buddy, busy fights | as 0.2.6; 8C / F4 / F5 replies come first (no visible change expected); the DA freeze is the same unless the DA job got faster | 15 |
| 5 | Save, load an old 0.2.6 save, a zoom scene | as 0.2.6 | 4 |
| 6 | **Blank save, first boot**: the mini-game, 10 s, then Soft Reset (twice) | the mini-game draws and runs; each Soft Reset boots the game; the mini-game never returns; no halt | 3 |
| 7 | **Pocket menu open 10 s** in play, then close | music and SFX silent while open; music resumes where it was; replies carry on; no watchdog halt | 1 |
| 8 | **Soft Reset black-screen check**: 10 Soft Resets, at least 5 straight after a Console or Mega CD change | every one boots; on any black screen, close it through the menu and send the `.sav` (boot milestones) | 5 |
| 9 | **Hall of Fame** with Arcade Mode On and 6-Button on; Mode coin; X/Y/Z | the highlight bar clean; +1 credit per coin and the game's coin sound (Q7); X/Y/Z work | 2 |
| 10 | **Arcade Mode** with Dock pads 1-3: Off, On, Multiplayer; Multiplayer with Arcade Stage Select "Arena"; Multiplayer with CPU MATE (Mega CD on) and P3; then **3-Player Mode** On with Arcade Mode Off (Soft Reset after each change) | Off with 3-Player Mode Off = the stock menu and 0.2.6's controller ports (no adapter: Q3 was revised 2026-10-11, the adapter is no longer there at every boot); On = arcade, 1-2 players; Multiplayer: P1-P3 join; "Arena" plays the Arena stage under arcade rules; CPU MATE fights beside P1 and P3; 3-Player Mode On: Arena mode takes three players | 6 |
| | | **total** | **~48** |

**Known cart behaviour, not a fault (docs/BOOT_SPEC.md section 13):** with no input, the intro's tech-logo sequence shows a
"MegaWire 4.0" logo even with MegaWire Off and "MODEM : NONE" on the terminal. It is the game's own credit screen,
and B Jam's original cart shows it with no MegaWire attached (2026-10-13).

**Soak (H2, ~80 min, the stage-1 exit):** about 60 min of warm play (the Pocket warm, ~50 C), through the elevator and
the Solarium, with CPU MATE off and on; a long pause (>= 10 min) in Block 888; then 20 min of attract idle. Pass: no
freeze. On a freeze: note where, Soft Reset, send the `.sav` (MCU heartbeat, 9494 count = 68000 alive, VS count = VDP
alive). After the soak, quitting the core and sending the `.sav` is fine: `tools/dbgsave.py` prints the soak's decoder
late words (must be 0), flags and smallest margin from `prev2`, with the worst over the chained sessions.

---

## 8. Risks

| # | risk | impact | mitigation | fallback |
|---|---|---|---|---|
| 1 | vram_alt freezes again on some layouts (seed-4 mechanism not known) | high: without it stage 1 does not fit comfortably | F1-F3; the class envelope; two candidates per round; freeze telemetry; V4 (Z80 enables) | V1b; `VRAM_ORIG` with features dropped and the FIFO lever (5.1) |
| 2 | `mcu_dati -> rv_di` on clk_sys (~+0.7 ns headroom) gains the register-file and byte-view arms | a seed sweep with few passes | registered sources, one shared registered block for 0x01 / 0x0B | RAMDP byte swap in firmware (C6 fallback) |
| 3 | The WRAM write path (seed 6 failed there at -0.105) | fewer passing seeds | M3 takes the decode and lock off the half-cycle path by design | a pre-decoded bank bit plus a multicycle backed by a bench |
| 4 | The FM XOR on `sdram dout -> cart_data` (9.31 ns) | fewer passing seeds | six bits only; C4's checksum-quirk lever frees the same mux | XOR at ROM load (Q11, needs B Jam's OK) |
| 5 | L1's worst case on RV32: measured 8.3-8.5 ms in the W14 co-sim, all of it AD bodies: 0.2.6 decoded the sprite blocks inside the post (the co-sim's "D1 3.5 ms" and "B6 3.0 ms" were AD00 bodies served in the same L1 entry right after a D1 / B6 finish, measured from its log; D1 alone 213 us). From 2026-10-13: the decode runs in the board's stand-in (WH_DEC, L2a, below the SFX feeder), and so does TEST's SAT snapshot (from 2026-10-14: L2c, below the CPU MATE brain call, risk 15); AD is now the 0.2.6 compose alone, 1.16 ms RELEASE / 1.30 ms TEST at most in the RV32 model (~1.4-1.6 ms at the hardware CPI), and it stays in L1 (the chip composes there; the game writes the object's record right after the post); every other body <= 0.24 ms at the hardware CPI (FZ12). The 84 deadline needs < ~0.95 ms | the mini-game could start on the window | the game posts 84 on mailbox B through `$B43A0`, which waits for the previous post's finish (verified: ROM `$B468C`): 84 -> window off 0.115-0.128 ms after the worst AD / D1 / B6 in the RV32 model (0.118-0.127 ms before). NOT met for a synthetic 84 on mailbox A in the middle of the worst AD: 0.96 ms RELEASE / 1.04 ms TEST model time (3.4-3.9 ms before), because the chip's EXTI order serves the next B post first; the game never posts 84 there. In the W14 co-sim (before 2026-10-13) the recorded 84 came 8 frames after the last post and R9 passed (0.135 ms). R9 / T-B11 on hardware via STAMP_B | stage 2's chip sprite engine; meanwhile an O(1) block-to-slot map (the chip's own, 0x20008164) for the compose's slot searches |
| 6 | F5 as an L3 job waits behind a brain call (up to ~2.9 ms) | stale zoom stamps for a frame | W14's count must be 0 | 0.2.6's synchronous F5 until stage 3 |
| 7 | NEORV32 `irq_buf` re-entry and ack ordering | lost or doubled posts | docs/MCU_INTERFACE.md section 6.3 rules; FZ1-FZ11; GHDL fuzz | - |
| 8 | Soft Reset black screen: the cause is still not known | the hardware test can still show it | S1, S2 by rule; the hypothesis 2/2b simulations (S3); TEST milestones | the dormant latch (Q4), switched on by firmware without a refit |
| 9 | TeraDrive stub un-prunes the VDP's 128 KB logic | ALM and new clk_md paths | the census watches it | leave F3 out of the fit |
| 10 | CPU MATE with three player slots not known. **X3 (2026-10-13, measured):** 12 three-slot corpora, compared call by call with the reference brain build, 0 mismatched of 38,984 calls; the s1 brain's words and variables equal the original's, but its cycle counter was +116 sub cycles on Arcade-3P census calls and +2 in the Arena (released late, never early). Fixed in the brain's counter weights (the cycle-counter fix: nine immediates, brain.bin b9a76592, fwbuild.json s1.brain): c_hat exact on 45,474 calls, closed loop 0 calls off on 38,851 | buddy misbehaves in Multiplayer | X3 corpora before H1 (done); CPU MATE lateness on the real stage-1 firmware is the co-sim's | document; fix in the glue (firmware-only) |
| 11 | `wram_data` ~470 B free in TEST | a link failure in stage 2 or 3 | W11 watches it; cold data to `wram_upper` | move TEST-only data out |
| 12 | Effort larger than the 0.3.0 plan said (67-94 work-days) | the calendar slips | parallel tracks; the critical path is short (C1 -> W14 -> G2) | - |
| 13 | The arbiter's DTACK with Mega CD = None was (inferred, strongly), not logged. **Closed (measured, R12(b), with its regression run and review):** with None, 13 of 13 cycles at `$400000-$7FFFFF` end on the arbiter's DTACK, no /CE0 | a boot hang with None | R12(b) logs it in md_board before the fit | revert C5 (0.2.6's answer), with B Jam's OK |
| 14 | M10K at 289-290 of 308 leaves stage 5 ~18 blocks | the stage-5 fit gets tight | Q1 = 4 KB; no other new block RAM in stage 1 | stage-5 levers (the 0.3.0 plan) |
| 15 | CPU MATE answers late against the original's release instants. **Measured (W14 co-sim, TEST + brain, 752 calls in play):** the brain call waited in L2a behind the decoder stand-in of 2026-10-13 and TEST's SAT snapshot: 422 words armed late (up to 8 ms); from frame 3236 a running call was held by the decoder for up to 109 ms and the game read a stale word or busy bit in 9 calls | the CPU MATE acts on an older answer, or the game refuses a send (busy) | **2026-10-14 (firmware-only):** the stand-in and TEST's debug save run as L2c, below the brain call, one request at a time with MSI open (the call preempts a request) and MTI masked (the wheel runs between two, as on the wheel); FZ13. The RV32 bench (a model of the board, the brain's real code, TEST, model time): word ARMs late 390 -> 261 (solo, `sw_05_fight`), 694 -> 449 / 737 -> 520 (Arcade 3P, `mp3_01` / `arena3`), the latest 5.7 / 16.8 / 16.4 -> 1.0 / 2.0 / 3.8 ms, stale game reads 0 / 76 / 121 -> 0 / 2 / 9; AF replies later by +1-17% on average. The rest was the interim SFX feeder's ticks (L2a) preempting the call. **Also 2026-10-14:** the call holds the feeder's wheel slot from the brain post to its end (the sub-CPU runs a call with every interrupt off; FZ14); the bench: late words 9 / 2 / 22 (floor) / 13 / 10 / 6 of ~2,450 in its six runs, the latest 0.13-0.92 ms, stale game reads 0 in all, SFX underruns 0, AF replies between L2c's and the 534 us option's. Proof on NEORV32: the W14 co-simulation re-run. **2026-10-15 (B Jam's decision, after test build 2 slowed in busy fights): reversed** - the game's own work comes first, the call is the thread's and takes the time left; CPU MATE lateness and stale reads come back (interim/README.md; the RV32 bench, priced clock: calls with a stale game read 0 -> 2-96 a run (1-100 with test build 1's firmware in the same bench); the latest word 27-68 ms at stage loads, 9 ms otherwise; 2-8 sends found busy) and are accepted by his rule | the 534 us feeder grid (the option of 2026-10-14) is not the chip's period (TIM6: 2,085 us, 160-sample blocks) and is not taken; the feeder goes in stage 5 |

---

## 9. Calendar (estimated)

| phase | what | time |
|---|---|---|
| Z1 | B Jam's answers Q1-Q7 | his time |
| Z2-Z4 | freeze, branch, conventions | ~1 day |
| Phase 2 | tracks M, C, S, V, F, W, X in parallel: ~67-94 work-days in all (M ~10-11, C ~10-15 with benches, S 6-10, V 8-13, F 8.5-13, W 20-27, X/G ~6-9) | ~2-3 weeks (stage 0 landed 4-7 estimated work-days in ~1.5 days; stage 1 has a longer chain: freeze -> RTL -> co-sim) |
| Phase 3 | integration and co-sim | ~3-5 days |
| Phase 4 | fit round 1 (~3 h of fitting + census + images); plan for a second round | 1-2 days a round |
| Phase 5 | H1 + H2 on candidate 1 (~2 h of B Jam's time); candidate 2 or a fix round if needed | 1-7 days |
| **total** | from B Jam's answers to a soaked stage-1 card | **~4-6 weeks; best case ~3 weeks** |

The 0.3.0 plan's stage-1 row ("7-12 work-days, 2-3 weeks") was never re-estimated for the added RTL and is superseded by this
table. The plan itself is not edited here.

---

## 10. Exit and fallback

- **Exit:** B Jam passes H1 and the warm soak; the system co-sim shows 0 late buddy words; per-level maxima measured on
  hardware; the RTL frozen (sizes, lock map, MCU_INTERFACE v1.0) for the firmware-only stages 2, 3 and 4b.
- **Fallback:** the final 0.2.6 bitstream.

---

## 11. Decisions for B Jam

**Needed before any RTL is written (Q1-Q7):**

| # | question | options | recommendation | why |
|---|---|---|---|---|
| Q1 | Battery save RAM size | 4 KB (as 0.2.x) or 8 KB (like the cart's EEPROM) | **4 KB** | the chip's save layout ends at 0xAE0; the game cannot see the size; the `.sav` stays 0.2.x's size; 8 KB costs 4 block RAM. TEST debug then uses 0xB00-0xFFF (1,280 B) from stage 3 |
| Q2 | 68000 byte writes into cart RAM | ignore them, or write the whole word (the byte on both halves) | **ignore** | both pass the game's own self-test, per-lane (0.2.x) fails it, and nothing else in the game can tell the two apart (0 game byte writes in 203,526 frames); ignoring also makes any stray byte write harmless. Which one the real cart does is not known (only a bus capture of a food pickup would show it) |
| Q3 | EA 4-Way Play scope | only in Arcade Mode Multiplayer (as decided 2026-10-10), or present at every boot (P3 counts only with a Dock pad of type 2/3) | **present at every boot** | the arcade flag hides Arena mode (measured), so with the tap only in Multiplayer the game's own 3-player Arena mode can never be played. With the tap always there, Off gives native 3P Arena (and 3P Arcade with the map code), as a 4-Way Play does on a real console; On stays 1-2 players (P3 cannot join without the DIP bit, measured); Multiplayer adds the DIP bit. Needs one GPGX check that 1-2 player play and the menus are unchanged with the tap present (T28) |
| Q4 | "Options apply at reset" latch, built dormant | build (off by default = 0.2.6's live options; firmware can switch it on later without a refit) or not | **build it dormant** | +10..+15 ALM; stage 1 is the last fit before stage 5, so this keeps the Soft Reset fix available if hypothesis 2 is proven |
| Q5 | TeraDrive with a separate Mega CD unit | allowed (like a Model 1) or forced to None | **allowed** until shown otherwise | the real TeraDrive's expansion support is not known |
| Q6 | Player 3 X/Y/Z/Mode in Multiplayer (through the Scum! cave) | yes or no | **yes**, when 6-Button is on | +20..+40 ALM; otherwise P3 has 3 buttons only |
| Q7 | The Scum! Mode coin once its stale-register bug is fixed | the game's own coin sound (what a real Grand Stick III gives) or silent (0.2.6, by accident) | **the game's coin sound** | cart-accurate; the silence came from a stale pointer |

**Not blocking the RTL:**

| # | question | recommendation |
|---|---|---|
| Q8 | 0.2.6 (awaiting its push) sets the copy-protection flag `$FF9986` at the first food pickup of every session, and its Scum! coin writes stray bytes into cart RAM. Effects never isolated on hardware (2 in 16 spawns of one kind can drop an object from the update order; an unlock withheld half the time). Ship 0.2.6 as built and soaked, or fix it first (a new fit and soak) | ship as built, fix in 0.3.0; whether to list it as a 0.2.6 known issue is your call. **Overtaken:** 0.2.6 was fixed first and shipped 2026-10-12 (byte writes ignored, seed 3) |
| Q9 | Stage-1 allow-list review (Z5): B7 music mute from stage 1; B10 split; B13 and B17 wording; new rows (84 as the chip does it, watchdog halt possible, default refusal, DA07 as board work, feeder grid) | approve before H1 |
| Q10 | The soak protocol: two candidates per round; ~60 min warm play + a long Block 888 pause + 20 min attract idle on the TEST image | yes |
| Q11 | FM XOR fallback: XOR the bank once at ROM load, only if STA shows the read-path XOR costs slack ("off after 84" is then not reproduced; nothing reads the bank after 84) | pre-approve as a fallback only |
| Q12 | Arcade Mode is a new menu variable: upgraders who had a stage chosen boot with Arcade Mode Off | accept, one release-note line |

**B Jam's answers (2026-10-11):**
- **Q1: 8 KB, replicate the cart** ("we don't know for certain 8 KB isn't needed for some reason"). +4 M10K (293-294 of 308). The `.sav` becomes 8 KB (data.json nonvolatile slot), and the one-time import accepts 0.2.x's 4 KB saves. The chip's layout uses 0x000-0xAE0; the rest is reserved, and the TEST debug region moves above it.
- **Q2: whole word** (B Jam's decision of 2026-10-11): a 68000 byte write to cart RAM writes the byte on both halves of the word. Per-lane (0.2.x) trips the game's self-test; whole word and ignore both pass, and the real cart's choice is not known. His reasoning: if anything breaks, we learn we are not cart-accurate somewhere. Item C7 builds whole word.
- **Q3 (revised by B Jam on 2026-10-11): the EA 4-Way Play is its own Pocket menu switch, "3-Player Mode", default Off.** Batch 1 found that with the adapter always present the first-boot mini-game hears only pad 3 and the attract demos drift, as on a real console with the adapter attached. The tap is present when 3-Player Mode = On (normal play: 3-player Arena, map-code Arcade) or when Arcade Mode = Multiplayer (which needs it); otherwise the ports behave exactly as 0.2.6. Read by the game at boot, so a change takes effect at the next Soft Reset. Was: present at every boot.
- **Q4: build it dormant for diagnosis** (+10..+15 ALM, no block RAM). If it is never switched on, remove it in the stage-6 release fit, which happens anyway.
- **Q5 allowed. Q6 yes. Q7 fix: the game's own coin sound.**
- **Q8: waiting on the $FF9986 effect check**. **Overtaken 2026-10-12:** 0.2.6 shipped with the byte-write fix (ignore; 2026-10-11, release fit seed 3).
- **Q9, Q10, Q11, Q12: approved.**
- **New item F5 (2026-10-11): TMSS per combined unit.** B Jam's real CDX shows the TMSS licence screen, but 0.2.6 forces the version nibble to 0 (no TMSS) for every combined unit (`ver1 <= ~combined & c_ver1`, paprium_addons.sv). Stage 1 sets the version nibble (and the TMSS stand-in) per unit from B Jam's check of each all-in-one unit; CDX = TMSS now. A few ALM. Test: the $BC944/$BC6BC paths over every Console x unit combination, then the Boom Box picture per unit on hardware.

**B Jam's answers (2026-10-13):**
- **VS counter (G1 option): BUILD it into this fit** (RTL, a new FPGAIO slot = MCU_INTERFACE v1.1, and the W10 freeze
  telemetry reads it), so a freeze log tells a dead VDP from a dead 68000 (both stop the frame post).
- **T-B7 wording widened:** with the Pocket menu closed, at most ONE 68000 bus cycle may start after the Soft Reset
  request, within 0.25 us, and never a write (was 0.15 us; measured worst 148 ns). BOOT_SPEC T-B7 and row S1 carry it.
- **The "MegaWire 4.0" logo in the no-input intro also shows on his original cart with no MegaWire attached:** the
  game's own credit screen, not a fault (docs/BOOT_SPEC.md section 13; section 7 above).

Resolved here without B Jam (section 2): the slot map, register storage, GO width, the stamps, the board-control bits,
the reset hold, the port-2 resync, the watchdog stage, the ms counter, the WRAM lock, the IROM build, the Scum! flip
guard (an invisible crash guard), F4 shadow pins only if needed, the Z80 enable fix as an exact look-ahead register,
and the HOLD synchroniser's 28 ns (reset only).

---

## 12. Not established

- The seed-4 freeze mechanism.
- Whether the real cart ignores 68000 byte writes into its RAM or writes the whole word.
- ~~The arbiter's DTACK for `$400000-$7FFFFF` with no cart answer~~ (measured by R12(b): every such cycle ends on the
  arbiter's DTACK).
- L1's worst case on the hardware itself (co-sim and RV32 model: section 8 risk 5); the real MCU load per level on
  hardware (TEST counters). (The F5 job's time is measured in the W14 co-sim: F5 fixed on 2026-10-12, 0 late.)
- `rv_di`, WRAM, `cart_data` slack with the stage-1 changes: only a fit says.
- TIM7's real rate (the ~4 s watchdog rests on an inferred 48 MHz timer clock).
- CPU MATE's behaviour with three player slots on hardware (X3's corpora and the counter fix: risk 10), and other
  counter ties of the same kind in states no corpus or forced test reached.
- Whether a non-Soft-Reset APF reset reloads the data slots (the SRAM image).
- The bank-2 row / column of VRAM `$0000` and `$10000` in 128 KB mode (TD-0 settles it).
- The Soft Reset black screen's cause (hypotheses 2, 2b and 4 are tested, not proven).
- ~~Native 6-button for P3 through the 4-Way Play on this core~~ (built as F4b; measured in the md bench: all 12
  buttons in records 1-3); its effect on play on hardware is not known until H1 item 9.

---

## 13. Sources

Design notes: the five design studies' notes and this planning pass's own (not in this tree). Specs: `docs/CART_FPGA_SPEC.md`, `docs/BOOT_SPEC.md`, `docs/BUDGET.md`, `docs/LAYOUT.md`,
`docs/CENSUS.md`, `tests/equiv/allowlist.json`; the 0.3.0 plan and its stage and test tables (not in this tree). RTL re-read
in the 0.2.6 release worktree (read only): `mcu_core.sv`, `memory.sv`, `fpgio.sv`, `ramdp_io.sv`, `paprium_mcu_mem.sv`,
`sdram.sv`, `cartridge.sv`, `core_top.sv`, `md_board.v`, `neorv32_cpu_control.vhd`, `paprium_cdda_play.sv`. ROM read in
place: `$2B83E-$2B874`, `$BCA1C-$BCAA6`.
