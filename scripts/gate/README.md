<!-- Copyright (C) 2026 Marsupial Solutions LLC -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# The fit gate

The fit gate was built for the 0.3.0 new core (the first step of the 0.3.0 work, which built the new cart register
file and MCU interface v1.0); the firmware's `docs/STAGE1_PLAN.md`, items G1 (the gate tooling) and G2 (the fit
rounds) and its section 6, describe it. Every seed of a fit round goes through this gate before it can be a
candidate; a seed that fails any part is rejected, even when it passes the old `setup >= -2.60 ns` line. The gate
predicts, hardware decides (docs/BUILD_REFERENCE.md): the two best seeds still need B Jam's hardware test list and
the warm soak.

## Run it on a seed

1. Fit the seed as usual (`quartus_sh -t generate.tcl paprium <seed>`), then `scripts/archive_fit.sh <label>`.
2. Copy the fitted tree to a scratch folder: `platform/`, `target/`, `projects/{db,incremental_db,output_files}` and
   `projects/megadrive_pocket.{qpf,qsf}`. quartus_sta writes into the project it opens, so never point the gate at the
   build tree itself. (A TEST-image fit carries the CPU MATE brain in its db: delete the copy afterwards.)
3. With no other Quartus process on the machine (the script waits until there is none, and kills nothing):

       scripts/gate/run_gate.sh <copy>/projects <out dir>

   About 3-4 minutes (3 min 17 s on the shipped 0.2.6 seed-2 copy): five `quartus_sta` sessions, one at a time, then six
   judges. `<out dir>/G1.txt` (named after item G1) has one line per judge; each judge's full report is
   `<name>.verdict.txt`. The exit status is 0 only when all six pass.
4. Rank the seeds that pass by their worst freeze-capable class margin (`census.json`, the "margin" column of
   `census.verdict.txt`) and take the best two (the firmware's docs/STAGE1_PLAN.md section 6, item G3).

After an RTL or SDC change, before any fit: `quartus_sh -t scripts/syn_check.tcl paprium` (Analysis & Synthesis) in a
copy of the tree, then `run_gate.sh <copy>/projects <out> --post-map`. That checks every SDC collection, the dot-clock
crossing's structure and the synchronisers' false paths on the mapped netlist (slacks there are estimates and are not
gated).

## What it checks

| judge | data (STA script) | rule (reject the seed when it fails) |
|---|---|---|
| `gate.py` | the fit's `sta.summary`; `xcheck.tcl` | worst setup >= -2.60 ns over every clock and corner (less negative is better); worst hold > 0 in every corner; every clk_sys <-> clk_md crossing setup >= 0 and hold > 0, setup into clk_sys >= 0, no failing hold path; every SDC collection matched (the new core's: C2c, MV, HOLD, VS, Scum!, P2, P2r, P0, RM, SP, C2a, C2b, the FX68K and audio multicycles, option D, h32_sync, the SDRAM pins; the synth step's, from test build 4a (the first 0.3.0 hardware test build of the sound cache): the first-boot bar's bar_sync / bar_w_sync); no SDC guard warning (`pocket: ... matched nothing`) in the fit / STA reports or the gate's own STA logs |
| `census_gate.py` | `census.tcl` (v1census + class queries) | the class envelope against the shipped 0.2.6 seed 2 (`ref/base_census_026s2.txt`): FX68K CCR, the VD bus, VA / rAS -> VD, VDP io_data, VDP io_address and Z80 internal each no more than 0.25 ns worse than the base in every corner; the Z80 enable class (`zclk_q`, the look-ahead register of the Z80 latch enable in ym7101, and the prescaler / test-register terms of its next value that the third fit round's instruction-register look-ahead reads) >= 0. Printed: the vram1 classes A-D below 0 ("V1B": class C or D, the round-level trigger for vram_alt.v's shadow pins, its F4) and the negative clk_md census |
| `vidsta_gate.py` | `vidsta.tcl` | per dot clock (H40, H32) and corner: exactly 28 reg->reg pairs from clk_md, into scanline_filler's 28 capture registers, 0 logic levels, the same-edge window (core_constraints.sdc's `-start -setup 0`), setup and hold >= 0; no timed pair from another clock |
| `queries_gate.py` | `queries.tcl` | the MCU memory rows follow the design queries.tcl finds (its `design` line). Wishbone (before the MCU fast path): WRAM write path >= +0.5 ns, WRAM read path >= 0, the IROM arm >= 0. Test build 4 on (the 0.3.0 hardware test build of the MCU fast path: the IROM / WRAM tightly coupled, the firmware's docs/MCU_INTERFACE.md section 20; found by `mcu_tcm_wram`): into and out of `mcu_tcm_wram` and `mcu_tcm_irom` >= 0 (full-cycle paths now), RAMDP's registered ack >= 0. The synth (test build 5 on, the synth build: the synth in the netlist, queries.tcl's `stage5 synth` line): the synth's CRAM read (`syn_cram_rd`: port C's read data into the synth), its DSP path (`syn_dsp`: through the synth's DSP blocks' result pins; `syn_dsp_in`: through their data inputs, which also sees a path that ends in a register the Fitter packed into a DSP block, such as B6's `f_rate -> mp` (B6 = paprium_synth_sfx); a project decision), the dac_buf port (`syn_dacbuf_w` / `syn_dacbuf_r`: CRAM port E both ways) and the 7-slice IROM (`irom_x`: the 88 KB extension's block RAM into the NEORV32) >= 0, and their collections matched. Both: the `mcu_dati -> rv_di` arms (register file / FPGAIO, RAMDP, SDRAM) >= 0; `sdram dout -> cart_data` no more than 0.25 ns worse than 0.2.6 seed 2 (`ref/queries_026s2.txt`); no timed path into the HOLD or VS synchroniser's first stage; their later stages and the VS counter setup >= 0, hold > 0 |
| `sdpins_gate.py` | the fit's `fit.rpt` | no warning 176279 on a `dram_*` pin; every `dram_*` register in its IOE (the new core's SDRAM I/O change) |
| `sdram_gate.py` | `sdram_sta.tcl` | every `dram_*` output and `dram_dq` input has a timed path with setup and hold >= 0 in all four corners (the SDRAM pad budgets in core_constraints.sdc); B1 (a metric from our comparison of the 0.2.6 byte-fix builds): the worst register -> pad delay at slow 85C <= 9.74 ns, and under the session-only `dram_clk` constraint (run with the pad-budget block left out) the worst fast-85C setup >= -0.10 ns with at most one bit below 0 |

Every judge exits 0 = pass, 1 = its rule failed, 2 = an input missing or unreadable. The STA scripts are read only
on the database and take an optional `post_map`. `--profile 026` runs the same tools on a 0.2.x fit (0.2.6's
collection list, no Z80 enable / VS / register-file items): used to prove the tools on real 0.2.6 databases; the new
core's own rules (vidsta, the SDRAM pads) then fail by design.

## Reference files (`ref/`)

- `base_census_026s2.txt`: `census.tcl` on a copy of the shipped 0.2.6 seed-2 fit (the final 0.2.6 tree `tree_s2`,
  release 44c9fa69). Its D lines equal the `base_census.txt` of our earlier VRAM timing trial (v1census, 058e867e) line
  for line; the K lines are new.
- `queries_026s2.txt`: `queries.tcl` on the same copy (the `sdram dout -> cart_data` reference).

## How the tools were proven (2026-10-13)

No fit of the new core exists yet, so each rule was proven on real databases where one fits the rule, and on planted
ones:

- **Real fits, read only through copies.** The shipped 0.2.6 seed 2 (the final 0.2.6 tree `tree_s2`, 44c9fa69), profile
  026: gate PASS, class envelope PASS (against itself), queries PASS; vidsta FAIL (144 pairs, the old `-setup 2` form:
  it predates the new core's video crossing), sdpins FAIL (12 pins in the fabric: it predates the SDRAM I/O change),
  SDRAM pads FAIL (no budgets), B1 PASS (9.737 /
  -0.056 at fast 85C, one bit). The tools reproduce the earlier audits on that copy: census A-E equal the VRAM trial's
  `base_census.txt`, xcheck equals the fit's own `xcheck.txt`, the sdpin / P2 lines equal the earlier comparison's
  `boot_ship.txt` (436 lines), vidsta gives the 144 pairs and the 122.751 ns of our earlier vidsta study.
- **The byte-fix pair (dbs deleted: their report files were used).** f0ec00cc (seed 2, black screen on every boot)
  PASSES the old gate (-0.874) and FAILS B1 (12.836 ns, -1.880 at fast 85C, 8 bits) and sdpins (12 unpacked);
  de85f7d5 (seed 3, boots) PASSES B1 (8.908, +0.237, 0 bits) and fails sdpins like every 0.2.x fit.
- **Planted databases** (the shipped seed-2 copy with one SDC line planted; the new core's post-map netlist with one SDC
  line planted): a 4 ns clk_sys -> clk_md hold requirement (gate FAIL, 500 failing hold paths), a C2b pattern that
  matches nothing (gate FAIL on the guard message and on the crossing it no longer covers), the FX68K CCR class given
  6 ns (envelope FAIL, 3.3 ns worse), the WRAM write side and cart_data given less time (queries FAIL), the SDRAM pad
  budgets on the 0.2.6 netlist (exactly its 12 fabric pins FAIL), the H40 same-edge window removed (vidsta FAIL), the VS
  and the HOLD false paths removed (queries FAIL: a timed path into the first stage), the VS pattern misspelled (gate
  FAIL on the guard). Every one exits 1.
- **Report-level plants** (35 cases): every judge passes its real input and fails a one-number plant on each side of
  its line (setup -2.610 / -2.590, CCR 0.251 / 0.241 worse, WRAM write +0.490 / +0.500, B1 9.750), an emptied class or
  collection, a missing pair, a logic level, an untimed pad, a missing input (exit 2).
- **The new core's netlist** (post-map, the branch head of the day): every collection of the new core's SDC matches (C2c
  33, MV 1, HOLD 1, VS 1, Scum! 23 / 17, P2 41, P2r 1, ...), vidsta has 28 pairs per dot clock with 0 levels in the
  same-edge window, the VS and HOLD first stages have no timed path, the classes all match: post-map gate PASS.
