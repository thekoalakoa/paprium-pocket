# Paprium on Analogue Pocket — port plan

Working repo forked from `drizzt/openFPGA-MegaDrive` v0.3.0 (Pocket port of
Nuked-MD-FPGA via MegaDrive_MiSTer). Source of the Paprium delta:
`MisterPezz82/Paprium_MegaDrive_MiSTer` (same upstream lineage).

## Phase 1 findings

### The delta is small and clean

Diffing `paprium-mister/rtl` against `MiSTer-devel/MegaDrive_MiSTer` HEAD, the
entire Paprium change is:

| Item | Size |
|---|---|
| `rtl/PAPRIUM/` (new) | 12 SV files, 2,213 lines + NEORV32 (29 VHDL, 12,219 lines) + `mcu.txt` firmware (36 KB) |
| `rtl/cartridge.sv` | 266 diff lines |
| `rtl/sdram.sv` | 29 diff lines |
| `rtl/mdp_audio.sv` | 9 diff lines |
| `rtl/pad_io.sv` | 7 diff lines |
| `MegaDrive.sv` (MiSTer top) | ~30 hook points |
| `hps_ext.sv` | **unchanged** |

No MiSTer framework file was modified. That is the best possible shape for a port.

### Same silicon family — RTL carries over

Correcting an earlier assumption: the Pocket's core FPGA is a **Cyclone V
`5CEBA4F23C8`** (`platform/pocket/pocket.tcl:25`), not a Xilinx part. MiSTer is
`5CSEBA6U23I7`. Same vendor, same family. Altera PLL instantiations,
`altsyncram` inference, and Quartus synthesis attributes all carry across.
The port is APF-framework glue plus memory architecture — **not** an RTL rewrite.

### The real constraint: fit

Approximate device capacities (confirm against a fitter report):

| | MiSTer 5CSEBA6 | Pocket 5CEBA4 | Pocket / MiSTer |
|---|---|---|---|
| ALM | ~41,910 | ~18,480 | 44% |
| M10K blocks | ~553 | ~308 | 56% |

Against that:

- The **base** Pocket MegaDrive core is already at **~82% ALM**
  (`projects/megadrive_pocket.qsf:29`).
- To fit at all, the Pocket core has **already dropped**: `md_plus.sv`,
  `mdp_audio.sv`, `md_io.sv`, `cheatcodes.sv`, `VM2413/`, `mboot.mif`,
  `EEPROM_STM95.sv`, and the pad/lightgun/multitap/keyboard muxes (`rtl/core.qip`).
- The **SVP ships as a separate bitstream** because it cannot coexist with the
  save hardware (`rtl/cartridge.sv:23-31`).
- MiSTer's Paprium build sits at **~92% M10K** on a device with ~1.8x the M10K.

And Paprium wants to *add*: a NEORV32 RISC-V MCU, `paprium_cart`, the 68000<->MCU
mailbox, an 8-channel PCM SFX engine — **plus `md_plus.sv` and `mdp_audio.sv`,
the two files the Pocket core deleted for space**, because CDDA runs through them.

**Conclusion: this does not fit as a mode of the general MegaDrive core.**

### Strategy: a Paprium-dedicated bitstream

Build Paprium as its own core, not an option in the MegaDrive core. That lets us
delete everything Paprium provably does not use and spend the reclaimed area on
the MCU and the audio path:

Removable (Paprium-only build): SVP entirely (Virtua Racing only — and Paprium
takes over SDRAM port 2, which is the SVP's), SSF2/Realtec/SF-00x mappers
(Paprium suppresses SSF2 banking anyway), `EEPROM_24CXX`, `cofi`, `scanline_filler`,
SMS mode, unlicensed-cart protection reads.

### Unused off-chip memory is our headroom

The Pocket core currently ties off two whole memories (`target/pocket/core_top.sv:267-290`):

| Resource | Size | Status |
|---|---|---|
| SDRAM | 512 Mbit x16 = **64 MB** | used for cart ROM |
| CRAM0 + CRAM1 (cellular PSRAM) | 64 Mbit x2 dual-die x2 chips = **32 MB** | **unused** |
| SRAM (async) | 1 Mbit x16 = **128 KB** | **unused** |

Paprium needs 8 MB writable ROM + 2 MB decompression workspace. On MiSTer both
share one SDRAM, which forced the V.04 "SDRAM anti-starvation" fix. On the Pocket
we can put the MCU workspace in CRAM and **remove that contention entirely** —
a structural improvement over the MiSTer port, not just a translation.

CRAM/SRAM are also where on-chip buffers can go to buy back M10K: the CDDA ring
buffer (DDR3 on MiSTer), MCU work RAM, and possibly the SFX FIFOs.

### CDDA has no HPS — but APF can do it

Paprium's music is MD+ CDDA. On MiSTer, Main_MiSTer's Linux side reads WAV tracks
from a `.cue` and feeds the DDR3 ring buffer. The Pocket has no equivalent.

The replacement mechanism exists: APF exposes asynchronous SD file reads via
`target_dataslot_read` / `target_dataslot_slotoffset` / `target_dataslot_bridgeaddr`
/ `target_dataslot_length` with ack/done/err handshake
(`target/pocket/core_bridge_cmd.v:80-92`). A streamer built on it can pull 48 kHz
PCM from SD into a CRAM ring buffer. This is real work with no upstream reference
in this tree — it is the single largest new-code item in the project.

## Phase order

1. **Measure before building.** Install Quartus, fit the unmodified baseline,
   record exact ALM/M10K. Every decision below depends on those numbers.
2. **Strip build.** Produce the Paprium-only variant (SVP and mappers removed),
   fit it, measure the reclaimed area. This is the budget we have to spend.
3. **MCU bring-up.** Vendor `rtl/PAPRIUM/`, trim NEORV32 generics (TRNG, TWI,
   SPI, PWM, WDT, CFU0/1 are almost certainly dead weight for `mega-ppm`), wire
   the mailbox, fit again. Gate: does the MCU fit at all?
4. **Memory architecture.** MCU flash/workspace onto CRAM instead of SDRAM port 2.
5. **CDDA streamer.** New APF dataslot-based PCM streamer replacing the HPS path.
6. **SFX engine + top-level mix.**
7. **Hardware loop** on your Pocket.

Gate 3 is the go/no-go. If NEORV32 plus the cart logic will not fit after the
strip, the fallback is replacing the RISC-V core with a hand-written state machine
implementing only the `mega-ppm` behaviour Paprium actually invokes — much more
work, but far smaller.

## Open items

- Confirm device capacities from a real fitter report, not datasheet recall.
- Confirm which Quartus version the Pocket project needs (qsf says
  `LAST_QUARTUS_VERSION "21.1.1 Lite Edition"`; the MiSTer Paprium core says 25.1
  Standard).
- Paprium's `mcu.txt` is krikzz `mega-ppm` firmware — check its licence before
  redistributing anything.

## Progress

### Done

- **`rtl/PAPRIUM/` vendored** (12 SV + NEORV32 28 VHDL + `mcu.txt`), listed in
  `rtl/paprium.qip`, wired into the project.
- **Firmware path fixed.** `mcu_core.sv` loaded `mcu.txt` with a path relative to
  the MiSTer tree root. Quartus resolves `$readmemh` against the *project*
  directory, which here is `projects/`. Now a bare filename plus
  `SEARCH_PATH "../rtl/PAPRIUM"`, the same way `68k.v` loads its 68000 microcode.
- **`sdram.sv` port-2 anti-starvation** copied to `rtl/sdram.sv` (the repo keeps
  `rtl/upstream/` pristine) and swapped in `rtl/core.qip`.
- **Save RAM adapted.** MiSTer's cartridge save interface is 16-bit; APF's is
  byte-wide. `paprium_backup.sv` port B is now an 8-bit port on the same
  2048x16 array via `dpram_dif`'s mixed-width support, so the `.sav` is a flat
  4096-byte file with no adapter logic. Byte order within the word is a
  `localparam` (`SAVE_BIG_ENDIAN`) because altsyncram's mixed-width ordering is
  little-endian and MD saves are big-endian — **unverified on hardware**; if a
  MiSTer save loads byte-swapped, clearing that constant is the whole fix.
- **`rtl/cartridge.sv` integrated** behind a new `PAPRIUM` parameter, mutually
  exclusive with `SVP` (both want SDRAM port 2). All hooks carry `// paprium:`
  markers matching the file's existing `// pocket:` convention:
  SDRAM port 2 mux, mailbox excluded from `rom_data_req`, stream-window address
  mux, stream-pointer ack toggle, mailbox in the `cart_data` mux, save mux,
  SSF2 banking suppressed, and the `paprium_cart` instantiation.
- **`paprium_quirk` is hard-wired to `PAPRIUM`**, mirroring how the SVP
  bitstream trusts the loader's serial check rather than re-detecting. This also
  drops the entire quirk table, `cart_id` and `crc` from the Paprium build.

### Next

1. **`core_top.sv` wiring** — thread the `PAPRIUM` parameter, mix
   `paprium_sfx_l/r` into the audio path, hold the 68000 on `paprium_md_reset`,
   and force NTSC (the PAL PLL is 53.203 MHz, but the MCU's `CLOCK_FREQUENCY`
   generic and `CLK_FREQ` are 53.693 MHz; PAL would put the firmware's
   clock-derived timing out by 0.9%).
2. **`generate.tcl`** — add a `paprium` variant alongside `ntsc`/`pal`/`*_svp`.
3. **CDDA streamer** — the `mdp_*` command channel currently leaves `cartridge`
   with nothing consuming it. Needs a new APF `target_dataslot_read` streamer
   feeding a CRAM ring buffer at 48 kHz.
4. **Chip32 loader rule** so the Pocket picks this bitstream for Paprium.

### Deferred

The V.05/V.06 extras — Arcade Mode IPS substitution, stage select, coin chute,
and the virtual 6-button combo injection — are all in the MiSTer `cartridge.sv`
diff and are *not* ported yet. They are self-contained ROM-read substitutions
and pad hooks; they cost area we have not measured yet, so they wait until the
core fits and boots.

## Findings from the actual ROM dump

Header of the local dump (8,231,927 bytes), offsets from the file start:

```
0x100  SEGA MEGA DRIVE (C) WM  2020.JUN  PAPRIUM
0x180  GM MK-12056-00
0x1B0  (no "RA" marker)
```

Two things follow, both already fixed in the tree:

1. **The serial does not match what the MiSTer core looks for.** MiSTer's quirk
   table activates Paprium on `cart_id[87:0] == "GM T-574120"`; this dump reads
   `GM MK-12056-00`. Serial-based detection would silently fail on it. This is
   the concrete reason `paprium_quirk` is hard-wired to the `PAPRIUM` parameter
   rather than sniffed from the header — different Paprium dumps carry different
   serials, and a dedicated bitstream does not need to guess.

2. **The header declares no battery RAM.** There is no `"RA"` at `0x1B0`, so the
   stock detection leaves `sram_present` low, APF never allocates a save slot,
   and the MCU's backup RAM never persists. The Paprium build now announces the
   save unconditionally, and `SAVE_SIZE` is 4 KB there instead of 64 KB —
   `paprium_backup` decodes only 12 address bits, so a 64 KB slot would wrap
   sixteen times over the array and corrupt the save on every load.

### Asset gap for CDDA

`docs/paprium.cue` in the MiSTer repo lists **62 tracks** drawn from WAV files
numbered up to at least 42. The local OST folder holds **26 MP3s** numbered
01-26. Whatever form the Pocket CDDA streamer takes, the track set on hand does
not cover the cue — several referenced files (e.g. `42 1988 Commercial`) are
simply absent. Sourcing the full 52-file WAV set is a prerequisite for music,
independent of any RTL work.

## Measured: it fits

Quartus Prime Lite 21.1.1 Build 850, device `5CEBA4F23C8`.

| | ALMs | of 18,480 | Memory bits | of 3,153,920 | Fitter |
|---|---|---|---|---|---|
| First attempt, nothing stripped | 18,733 | **101%** | 2,258,194 | 72% | **Failed** |
| After the three dead-hardware cuts | 18,314 | **99%** | 1,733,903 | 55% | **Successful** |

The cuts bought 419 ALMs and 524,291 memory bits. Final: 230/308 RAM blocks (75%),
33/66 DSP (50%), 2/4 PLLs, and an `.rbf` is produced.

**The block-RAM worry in the Phase 1 plan above was wrong.** Memory is at 55%,
never close to the wall. ALMs are the binding constraint, at 99% with 166 spare.
That inverts the CDDA buffer decision: `2 x 8 KB` of block RAM is affordable, and
reaching for `cram0`/`cram1` would trade plentiful memory for scarce logic. Build
the ring in BRAM.

The 166 spare ALMs are not much to build a CDDA streamer in. Levers not yet
pulled, cheapest first: NEORV32 `FAST_SHIFT_EN` off (barrel shifter to serial -
costs shift performance, nothing else), then its unused peripherals (UART, GPIO,
WDT are all tied off at the `paprium_cart` instantiation, but `mega-ppm` may poll
them, so that carries firmware risk).

## Measured: timing does not close

```
Slow 1100mV 85C Model Setup 'ic|mp1|...general[1]...divclk'
Slack : -2.277    TNS : -1590.865
```

`general[1]` is `clk_md_107_39`. It is constrained at 107.39 MHz and achieves
**86.29 MHz**. Every other clock passes, `clk_sys_53_69` among them at +0.520.

All 80 of the worst setup paths are inside `md_board` - `ym7101` (the VDP) into
its line buffer and sprite output, and `mclk_clk3_l` into the Z80. **Not one
Paprium path appears.** That points at a pre-existing property of the gate-level
Nuked-MD core rather than anything this port added, but that has to be confirmed
by fitting the untouched baseline and comparing, not assumed - see below.

Two things worth keeping in view. The failing model is the worst-case corner
(1100 mV, 85 C); a Pocket does not run at 85 C. And the base core ships as a
declared beta. Neither makes a violation acceptable, but both bear on whether
this is a regression or the status quo.

## Baseline comparison: the timing violation is inherited

Fitting the untouched `ntsc` variant on the same toolchain and device:

| | ALMs | Memory bits | DSP | general[1] slack | TNS |
|---|---|---|---|---|---|
| Baseline `ntsc` (no Paprium) | 16,249 (88%) | 1,731,855 (55%) | 26 | **-2.612** | -717.7 |
| `paprium` | 18,314 (99%) | 1,733,903 (55%) | 33 | **-2.277** | -1590.9 |

**The baseline fails the same clock, on the same paths, with a worse worst-case
slack than the Paprium build.** Its failing nodes are the same base-core logic:
`ym7101:vdp|mclk_clk3_l`, `ym7101:vdp|ym7101_dff:prescaler_dff11`,
`z80cpu:z80|z80_dlatch`. Nothing this port added appears in either list.

So `clk_md_107_39` not closing at the slow 85 C corner is a property of the
gate-level Nuked-MD core as shipped, not a regression introduced here. The
released v0.3.0 core carries it too, and people run that core on real hardware.

The one honest caveat: our **TNS is worse** (-1590.9 against -717.7). The single
worst path improved, but the *number* of failing paths roughly doubled. That is
what 99% ALM utilisation does - the fitter has almost no placement freedom left,
so many paths land marginally worse even though the logic on them is unchanged.
Reclaiming ALMs would pull TNS back down; it will not fix the worst path, because
that path is the base core's.

Paprium's net cost, after the dead-hardware cuts: **+2,065 ALMs, +7 DSP, and
essentially no memory** (+2,048 bits - the MCU work RAM, firmware ROM and backup
RAM almost exactly replace the 64 KB cart SRAM that was removed).

### What this means for the plan

Hardware testing is reasonable now. The core is no further outside timing than
the base core that already works on real Pockets, so a bring-up attempt will tell
us something real rather than just re-measuring a known violation.

## Correction: there are two dumps, and the earlier analysis used the wrong one

The "Findings from the actual ROM dump" section above analysed
`Paprium (JUE) v1.0.zip`. That is not the cartridge dump. The correct one ships
inside the ROM+Core+OST archive as `src/paprium/paprium.bin`:

| | `Paprium (JUE) v1.0.bin` | `src/paprium/paprium.bin` |
|---|---|---|
| Size | 8,231,927 | **8,388,608 (exactly 8 MiB)** |
| 0x110 | `(C) WM  2020.JUN` | `(c)T574 2018.DEC` |
| 0x180 serial | `GM MK-12056-00` | **`GM T-574120-00`** |
| 0x1B0 | no marker | **`RA`** |

So both earlier claims were wrong **about the right file**:

- The serial **does** match what MiSTer's quirk table looks for
  (`cart_id[87:0] == "GM T-574120"`). Serial detection would work fine.
- The header **does** declare battery RAM, so `sram_present` would be set
  normally.

The two code changes those findings motivated are still correct, but for weaker
reasons than stated. Hard-wiring `paprium_quirk` to the `PAPRIUM` parameter is
still right for a dedicated bitstream - it drops the whole quirk table, `cart_id`
and `crc`, which is area we need - and forcing `sram_present` is harmless when
the header sets it anyway. Neither is load-bearing on the bad analysis.

The size difference is the substantive part: the MCU expects a full 8 MiB
writable ROM image in SDRAM, with the decompression workspace starting at byte
0x800000 immediately above it (`paprium_cart.sv`: `stream_addr = 24'h400000 +
...`, a word address). The 8,231,927-byte file is not that image. **Use
`src/paprium/paprium.bin`.**

## Hardware test log

### Test 1 - first bitstream (OE bug present)

Boots, boot minigame playable, reset into the real game works. Heavy tile
glitching; sprites present and positioned correctly, gameplay and collision
working, but their pixel data was garbage. English text clean, Japanese text
blurry. Identical on two different dumps.

Everything broken was data that reaches VRAM through the decompression stream
window; everything clean was data that does not. The control path - object
lists, SAT writes, positions - was correct throughout, which ruled out the
sprite-attribute priority bug in the MiSTer KNOWN_ISSUES (that misorders
sprites, it does not garble pixels).

### Diagnosis

`md_board` exposes two output-enable strobes: the real cartridge OE (`~CAS0`)
and `vdp_dma_oe_early`, issued a cycle earlier to hide SDRAM latency. The Pocket
shell wired the early one to `cart_oe` and left the real one dangling - correct
for ordinary ROM reads. Paprium's `$C000-$FFFF` window is not an ordinary read:
every accepted one advances the cart's private stream pointer, so a speculative
DMA phase that never delivers a word still consumes one. MiSTer handles this at
`MegaDrive.sv:466`; the hook was missed when the top-level wiring was ported.

### Test 2 - `paprium_nosfx` (OE fixed)

**Clean backgrounds and sprites.** The fix is confirmed.

This build dropped `audio_sfx` to fit, which also showed the TNS regression was
density rather than logic:

| | worst slack | TNS |
|---|---|---|
| Baseline `ntsc` | -2.612 | -717.7 |
| `paprium` (SFX, pre-fix) | -2.277 | -1590.9 |
| `paprium_nosfx` | **-2.135** | **-562.8** |

With placement room the Paprium build is better than the untouched base core on
both figures.

## The fit was a settings problem, not an RTL problem

With sound effects in and the Fmax-tuned settings inherited from the base core,
the Paprium variant failed at 18,560 ALMs / 1868 LABs against 1848 available.
Switching the Paprium variants alone to area-oriented fitter settings:

| | ALMs | LABs | worst slack | TNS |
|---|---|---|---|---|
| Fmax settings, SFX | 18,560 (100%) | 1868 - **failed** | - | - |
| Area settings, SFX | **17,737 (96%)** | fits | -2.318 | -1061.9 |

**823 ALMs recovered from six `set_global_assignment` lines** - more than the
whole `audio_sfx` engine costs, and with no RTL sacrificed. The time-multiplexed
`sfx_bank` rewrite, the NEORV32 trims and the audio-conditioning cut are all
still available and all still untouched.

Memory is unchanged at 1,733,903 bits (55%), 230/308 RAM blocks, 33 DSP.

The lesson is in the base core's own qsf comment: it moved *off* area settings
because its first fit landed at 82% ALM and it had room to spend on Fmax. That
trade is correct at 82% and backwards at 100%. MisterPezz82's qsf points the same
way from the other side - he sets `ALM_REGISTER_PACKING_EFFORT LOW` on a device
2.3x this size.

Cost: timing is worse than the `nosfx` build (-2.318 / -1061.9 against
-2.135 / -562.8), which is the expected area-for-speed trade. Worst-case slack is
still better than the untouched baseline's -2.612; TNS is worse than its -717.7.

**743 ALMs of headroom now exist for the CDDA streamer**, which is the number
that decides whether music and sound effects can coexist.

## CDDA fits: full core measured

| | ALMs | Memory | RAM blocks | DSP | worst slack | TNS |
|---|---|---|---|---|---|---|
| SFX only | 17,737 (96%) | 1,733,903 (55%) | 230 | 33 | -2.318 | -1061.9 |
| + CDDA, param struct inferred | 18,794 (**102%** - failed) | 1,865,053 | - | 39 | - | - |
| + CDDA, param struct instantiated | **18,100 (98%)** | 1,869,149 (59%) | 249 (81%) | 39 | -3.040 | -1347.5 |

The streamer's true cost is **363 ALMs**, not the 1,057 the first attempt showed.
The difference was a 66-word parameter struct that failed to infer as block RAM
because its write sits inside the sequencer's always block; 66 words of flops
plus a 66-way 32-bit read mux cost 694 ALMs. Instantiating `dpram_dif` explicitly
fixed it, and the memory figure is what exposed the problem: the first fit's
+131,150 bits was exactly the ring and nothing else.

**Lesson for this device: infer nothing, instantiate everything.**

Timing degraded to -3.040 / -1347.5, worse than the untouched baseline's -2.612 /
-717.7 for the first time. The worst eight paths are still `ym7101:vdp` and the
prescaler - no CDDA path appears - so this is congestion at 98% making the same
inherited paths route worse, not a new critical path. Reclaiming ALMs would pull
it back; the reserve levers are all still unspent:

| Lever | ~ALUTs | Risk |
|---|---|---|
| Time-multiplex `sfx_bank` | 260 | moderate, no audible effect |
| NEORV32 `MTIME` | 185 | firmware may use the timer |
| NEORV32 `FAST_SHIFT_EN` | 150 | slows the decompressors |
| Hardwire `audio_cond` LPF | 300-400 | audibly changes MD sound character |

## CDDA bring-up log

Music took four fixes, three of which were real bugs that were not the blocker.
Recorded because the order matters more than the fixes.

1. **Param struct not byte-swapped.** `core_top` ties `bridge_endian_little` to
   0, so the bridge is big-endian and every other read path in the shell swaps
   for it (`data_unloader.sv:200`). The struct returned raw words, reversing each
   group of four path bytes. Real bug; did not change the symptom.

2. **Stale `target_dataslot_done`.** `core_bridge_cmd` clears `done` only on
   reaching `TARG_ST_DATASLOTOP`, several cycles after a request, so it still
   holds the previous command's value. Waiting on `done` alone fired instantly on
   a stale 1, and every read after the first "completed" with nothing written.
   Commands now wait for `ack` first. Also: `err` 1 is *created and opened*, a
   success code, and was being treated as failure. Real bugs; symptom unchanged.

3. **Zero slot size read as end-of-track.** A `deferload` slot that is not loaded
   reports size 0 through `dataslot_update`. With `track_bytes = 0` and
   `track_bytes_valid = 1`, the first `S_ADVANCE` evaluated `0 + CHUNK >= 0` as
   end-of-track: one 21 ms chunk, `playing` dropped, silence - **whatever
   happened upstream**. This was the blocker, and it masked fixes 1 and 2.

4. **`version_required` too low.** With audio flowing, every track played as
   track 01, which is the fallback path: `openfile` was having no effect.
   `core.json` declared `"1.1"`; `Mazamars312/openfpga-pcengine-cd`, the one core
   known to use `openfile`, declares **`"2.3"`**. APF offers a core only the
   features matching its declared framework version, so the core was asking for a
   2.x command while claiming to be a 1.1 core. Reads are long-standing and
   worked throughout; `openfile` silently did not.

The lesson: silence is a terrible diagnostic, because every failure in a streamer
looks identical. What broke the deadlock was making failures *audible* - falling
back to streaming the slot untouched rather than going quiet turned "no music"
into "wrong track", which named the remaining fault immediately.

## To do, in order

### 1. Music selects the right track (in progress)

The seek-by-offset redesign is built and waiting on hardware. `openfile` is out of
the picture; a track request reads its 8-byte header entry from `paprium.pcm` and
streams from that offset.

**Numbering is confirmed from two independent sources.** GPGX's
`paprium_load_mp3` (`src/Full Source/core/cart_hw/paprium.h`) is the authoritative
game-index -> song table, and it agrees with the cue: `idx 0x35 -> "12 Stage
Clear"`, and 0x35 is 53 decimal, the cue's TRACK 53. So blob entry N = game
index N.

### 2. The punk-TV cue - a missing asset, not a bug

GPGX's mapping covers 52 indices and references **all 52** OST files, none spare.
The ten indices it does NOT map are exactly the `Blank.wav` slots:
**8, 9, 10, 13, 26, 31, 41, 44, 45, 48**.

So that audio was never released. Genesis Plus GX is silent in those scenes too,
for want of a file. Upstream's "track number TBD" is unresolved because there is
nothing to resolve it against.

> **Superseded - this whole section is the wrong subsystem.** The punk-TV audio
> is **SFX `0x4A`**, raw PCM sitting in the cart ROM, confirmed by ear from
> `scripts/dump_sfx.py`. It is not a music track and was never missing. The cart's
> music pointer table is additionally **null at all ten of these indices**, so
> music is correctly silent in those scenes. Every option listed below - decoding
> the wave ROM, rendering with the synth, recording from a real cartridge - is
> aimed at a track that does not exist. See "The SFX bank is readable" below.

What would actually fix it:

- **Decode the cartridge's own wave ROM.** The DATENMEISTER chipset holds the
  real music compressed; nobody has decoded that format, which is why every
  implementation substitutes an external OST. A reverse-engineering project in
  its own right.
- **Record the scene from a real cartridge**, trim and convert to `trackNN.pcm`.
  Crude but sufficient - the blob makes dropping it in trivial.
- **Identify which index the TV requests** - cheap and worth doing regardless.
  Built: `DIAG_MODE` plays the requested number back as two counted bursts, no
  save-file round trip needed. See "The TV track-number diagnostic" below.

### 3. Boss fight: player sprite drops behind the background

**Symptom (hardware, this port):** during one phase of a boss fight the player
falls behind the background plane, stays controllable, and pops back when the
phase ends.

**Cause, per upstream:** `mega-ppm` composes each sprite's attribute word by
XORing it whole (`ppm_obj_render`, `mame.c:544`), where GPGX composes field-wise
with tile precedence - `priority = tileP ? tileP : objP`. The two agree only
while the object's priority bits are 0. When both the tile and the object set
priority, XOR cancels them to 0 and the sprite drops behind the BG.

**Not ours.** Confirmed by upstream as *"also broken on EverDrive Pro -> firmware,
not core/VDP"*. It happens on real cartridge hardware running the same
replacement firmware.

**Difficulty is real.** The obvious fix - field-wise composition - was built and
hardware-tested in V.04 and logged as *"superseded: had NO observable effect on
HW"* for the elevator case. It was kept because it did no harm, but it is not the
fix. Upstream's remaining leads are the muted `0xB0` `paprium_sprite_init` and
`0x88` setup commands, or a different decode path.

**What attempting it needs:** the firmware is `mcu.txt`, a compiled image. Changing
it means building krikzz's `mega-ppm` source with a RISC-V toolchain and
regenerating the image, then hardware-testing for regressions across normal scenes
(the all-XOR path works everywhere else, so anything that relies on it would
break). Our boss fight may be a different instance of the same class from the
elevator, which would make it a fresh data point upstream does not have.

## Music works (hardware confirmed)

Correct track per scene, and the one-shots - Continue, Game Over, High Score,
Stage Clear - play once and stop instead of looping. **MiSTer cannot do that**:
Main_MiSTer's player ignores the play command's loop flag and takes looping from
cue directives, which is why that project ships `REM NOLOOP` entries. Reading
`$11xx` vs `$12xx` directly, with a definite length from the blob header, is a
capability the reference implementation does not have.

Working on hardware: MCU boot, decompression, graphics streaming, saves,
cartridge PCM sound effects, and CD-quality music with correct selection, looping
and one-shot behaviour.

### Remaining issues, and who owns them

| Issue | Owner | Status |
|---|---|---|
| Punk-TV cue silent | **CLOSED - works in both regions** | SFX `0x4A` plays loud and clear. Not a bug in the port, and not region-dependent |
| SFX inaudible while music plays | **CLOSED - settings, not headroom** | Refuted: at the same 294 gain the effects are clear once the game's own audio options are right |
| Elevator corruption + priority | upstream firmware | Open, issue C |
| Boss fight: sprite drops behind BG | upstream firmware | Open, sprite-attribute XOR |
| "Saxophone guy" never appears | probably upstream | Candidate: issues A/B |
| Some SFX differ from real hardware | expected, partly | See below |

**Elevator** is upstream issue C verbatim: *"Lots of graphical corruption in the
elevator, and background priority problems."* Narrowed there to a
**decompression/decode** fault, not sprites. They implemented full GPGX page
semantics for the `0xC000` window to try to fix it; the elevator was unchanged
and it **regressed boss animations**, so it was rolled back.

**"Saxophone guy" never appearing** looks like upstream issues A/B - the MCU
falling behind on SDRAM port 2 and missing a spawn trigger, which they describe
as *"enemies stop appearing"* and suspect shares a root cause with the subway
stall. Worth checking whether it is reproducible or occasional: theirs is
occasional, which is what makes it a race.

**Sound effects differing from a real cartridge is expected in part.** Neither
this port nor MiSTer reproduces the DATENMEISTER chipset - upstream's own README
opens by saying so. `audio_sfx` is a port of the mega-ppm PCM engine, an
EverDrive-Pro-style workaround, not the cartridge's real sound hardware.

The useful distinction is *what* it differs from:

- **Differs from a real cart, matches MiSTer** - inherent to the approach, not
  fixable without decoding the cartridge's own audio path.
- **Differs from MiSTer too** - then it is ours, and the first suspect is the
  `aclk_bank` rewrite. That replaced five free-running fractional dividers with
  counters off the 48 kHz tick: rates are identical except 5333 -> 5333.33 Hz
  (0.006%, inaudible), but the channels are now phase-locked to a common tick
  rather than drifting independently. Reverting it is one file and costs ~290
  ALUTs, which the area budget can absorb at 98%.

## Rendering the cart's own music: how far it got

The cartridge does not play CD audio. It **synthesises** music from sequence data
and samples in ROM, through a 26-voice engine. The OST substitution used by this
port and by MiSTer is the workaround, not the original. Genesis Plus GX contains
that synth, so rendering the ten tracks with no OST file - punk-TV among them -
looked tractable.

### What was built (`tools/gpgx-render/`)

- MSYS2 + gcc 16.2 + make installed; the GPGX core builds.
- Three source gates flipped in `paprium.h`: `if(0)` -> `if(1)` on the WavPack
  sample-bank loader, and the two `#if 1` guards that make `paprium_music_synth`
  return MP3 audio and `paprium_music` load MP3s at all.
- `paprium_render_wav()` added: walks the same per-sample path `paprium_audio()`
  does - synth, SFX voice, echo, master volume, clip - and writes a 48 kHz stereo
  WAV. Driven by `PAPRIUM_RENDER="track:seconds:outfile"`.
- Hooked at the end of `paprium_init()`, which works because the *fast loadstate*
  block there reads `music_ptr`, `wave_ptr` and the rest **straight from fixed ROM
  offsets** - so no booting and no navigating to a scene.
- `render_host.c`: a minimal libretro host, enough to make the core load a ROM.

### What works

The harness runs end to end and writes a correctly-formed WAV of exactly the
right length. State dumped from inside the renderer confirms the data path:

| | |
|---|---|
| `music_ptr` | `0x001400B0`, read from ROM `0x10054` |
| `music_ram` | decompresses to a valid module - magic `4D 57 4D 4D` (`"MWMM"`) |
| `wave_ram` | instrument table present: program 0 at `0x10`, size `0x8B0B` |
| sequencer | advances correctly - `music_section` reached 75 in 5 s, exactly 60fps/4 |

### What does not

**Every render is digital silence**, and `0/26` voices ever receive a note.

Two targeted fixes were tried and neither changed it: setting the master volume
(`paprium_init` memsets it to 0, and the final mix scales by it), and setting
`paprium_s.music_track`, which `paprium_music()` never sets itself - it relied on
`paprium_load_mp3()` doing it as a side effect.

So everything up to and including the sequencer stepping works; **note emission
does not**.

### Assessment

Probably incomplete upstream rather than misconfigured. Three separate
disablements point the same way: `paprium_wave_unpack()` (the in-ROM unpacker)
was never written at all, the external sample-bank loader is `if(0)`, and the
synth is bypassed by an early `return`. That reads as abandoned mid-development,
not superseded once MP3s worked.

Finishing it means reverse-engineering the `MWMM` module format against the ROM
and completing someone else's half-written parser. That is a project in its own
right, not a debugging session.

**And it would not fix punk-TV.** The cart's music pointer table is null at all
ten unmapped indices, so there is no module there to render however good the
synth gets. Finishing this work would be for its own sake - rendering the 52
tracks that *do* exist without the OST - not for the missing ten.

### Cheaper thing to do first

**Confirm which index the TV actually requests.** It has never been measured. If
it turns out to be one of the 52 *mapped* indices, this is a mapping or ordering
bug with a trivial fix and none of the above matters. Only if it is one of the
ten blanks does the audio genuinely not exist. The audible-readout trick already
used for the openfile error code applies directly: play the requested track
number as N seconds and count.

## Resume here

### State

Working on hardware: MCU boot, decompression, graphics streaming, saves,
cartridge PCM sound effects, and music with correct per-scene track selection and
one-shot behaviour. Standalone core packaged as `Koala_Koa.Paprium`, platform
`paprium`, category Others. Fits at 98% ALM.

Everything needed to rebuild is committed. `docs/PORT_PLAN.md` (this file) is the
whole history and reasoning.

### The TV track-number diagnostic

`DIAG_MODE` reports the REQUESTED track number as two audible bursts - tens
seconds, a pause, then units - so the punk-TV scene names its own index. Track 41
plays 4 s, pauses ~1.8 s, plays 1 s. If the index turns out to be one of the 52
mapped ones, punk-TV is a mapping bug with a trivial fix; only if it is one of
the ten unmapped slots (8 9 10 13 26 31 41 44 45 48) is the audio genuinely
absent.

Reading it: an index below 10 has a tens digit of 0, so the first burst is a
single chunk - a ~21 ms tick rather than a silent gap. That is deliberate: a tick
confirms the readout ran and the tens digit is zero, where nothing at all would
leave "0 tens" and "the scene never asked" looking identical. So tick-pause-8 s
reads as index 8, and 4 s-pause-1 s reads as 41.

**RTL is complete and synthesises clean** (`paprium_cdda_fetch.sv`,
`target/pocket/core_top.sv`). `S_DIAG_GAP` added; `S_ADVANCE` counts
`diag_chunks` against `diag_target` and hands off to the gap after the tens
burst, `S_DONE` after the units; `diag_phase`/`diag_chunks`/`diag_gap` reset on
`track_request`; `DIAG_MODE` never loops.

Two things had to be handled that the original step list did not anticipate.
Both are gated on `DIAG_MODE`, so shipping behaviour is untouched.

**The bursts stream from a fixed source track, not the requested one**
(`DIAG_SRC = 5`). Measuring the blob header settled why - see below. The reported
number is still the requested one; only the bytes fed to the ring are borrowed.

**A stop arriving mid-readout is deferred.** `$13xx` with `fade_sectors == 0`
latches `paused` in `paprium_cdda_play` and hard-mutes it until the next track.
A scene-change stop would therefore cut a burst short and read as a *smaller
number* - a believable wrong answer, the one failure mode this diagnostic cannot
afford. `mdp_stop_gated` in `core_top.sv` drops the stop for both the fetcher and
the player while `mdp_playing` is high, and `DIAG_MODE` raises `playing` at the
request rather than after the header lands so the mask spans the whole readout.
The readout ends itself after ~17 s at worst, and a new `track_request` always
restarts it.

Remaining: build `paprium_cddadbg`, verify size and timestamp differ from the
shipping build, install, reach the TV scene and count the two bursts.

### The cartridge has no music for those ten indices either

Tested directly against the ROM. This settles a question the plan had only been
reasoning about circumstantially.

`paprium_music()` locates a track's module through a **pointer table in the cart
ROM** (`paprium.h:1774`): base `paprium_music_ptr` = `0x001400B0`, read from ROM
`0x10054`; one big-endian u32 per track at `base + track*4`. The word at entry 0
is `0x0000003E` - 62, the track count.

Dumping that table:

- **52 live entries, 52 distinct offsets, exactly 10 nulls.**
- The ten nulls are indices **8, 9, 10, 13, 26, 31, 41, 44, 45, 48** - the same
  ten, reached independently of GPGX's file mapping and of the cue.
- The 52 live offsets sort into a clean ascending run, no overlaps, sensible
  module sizes (~0x300-0x1E00 bytes), and all 52 share the 8-byte prologue
  `81 0E 57 4D 4D 4D 00 01`. The parse is sound.
- Identical in two independent dumps: `hw-test/Paprium.md` and
  `src/paprium/paprium.bin`.

**So the cartridge itself has no music for those ten indices.** Not "the OST
omitted them" - the game's own data has nothing there, and the 26-voice synth
has nothing to render for them either.

That rules out the idea that a blank slot is the game yielding to its internal
synth. (No implementation has such a fallback in any case: GPGX's
`paprium_music_synth` hits an unconditional `return` placed *outside* the
`if(music_track)`, so the 26-voice loop below it is dead code in every build, for
every track.)

What survives of that reading is narrower but still open: a null may be a
deliberate "go quiet" marker the DATENMEISTER firmware special-cases. It cannot
be a *used* pointer - `paprium_decoder_type(paprium_music_ptr + 0, ...)` would
decode the pointer table itself as a module, which is garbage, not silence. So
either the firmware null-checks, or the game never requests these ten at all.

#### What this changes

**The expensive option is off the table.** "Decode the cartridge's own wave ROM"
and "finish `tools/gpgx-render/` to render the missing ten" cannot produce
punk-TV audio *even if they completely succeed* - there is no module for index 8,
9, 10, 13, 26, 31, 41, 44, 45 or 48 to render. The same goes for "record the
scene from a real cartridge": a real cartridge has no music module there either.

**The diagnostic's answer is now cleanly binary:**

| Diagnostic reports | Meaning | Action |
|---|---|---|
| one of the 52 live indices | mapping or ordering bug; the music exists | trivial fix |
| one of the 10 null indices | the game has no music there, hardware included | close it - silence is correct |

The first is now the likelier outcome, because shipping a request for a
null-pointer track would have real hardware decode its own pointer table as a
module. That is a real prediction the diagnostic will confirm or refute.

### The SFX bank is readable, and is where a non-music cue would live

If the punk-TV audio exists on original hardware - and it is reported to - then
given the null music pointers it cannot be a music module. The only other audio
in the cartridge is the SFX bank, and unlike the music that bank is **raw PCM in
ROM**, so it can be read offline without the DATENMEISTER decoder.

`scripts/dump_sfx.py` does that. Layout, from GPGX's `sfx_play` /
`paprium_sfx_voice`:

    sfx_ptr = be32(rom + be32(rom + 0xAF77C) + 0x778)   = 0x0025ECA4
    entry N = 8 bytes at sfx_ptr + N*8
        +0 u32 sample offset (relative to sfx_ptr)
        +4 u8  type      +5 u8 size hi      +6 u16 size lo
    type >> 4 -> rate index into {1,2,4,5,8,9} = 48000/N Hz
    type &  3 -> depth: 1 = 8-bit unsigned, 2 = 4-bit packed, high nibble first
    size counts SAMPLES, not bytes

What it contains: **127 usable entries, 552,746 bytes at ROM 0x25ECA4-0x2E5BCE**,
5333-48000 Hz, durations 0.03 s to **4.99 s**. 48 entries are 8-bit, 79 are 4-bit.
Nothing in the bank is music-length, but a few-second diegetic TV cue fits it
comfortably - the longest entries are `0x4A` (4.99 s), `0x4B` (4.55 s), `0x2F`
(3.51 s), `0x4C` (3.29 s), `0x3D` (3.07 s), `0x2E` (2.99 s).

**Byte order is the trap here, and it is a silent one.** GPGX keeps `cart.rom`
byte-swapped against the file, so a `*(uint16*)` read gives the big-endian value
directly while a plain byte read lands on the neighbour. The table's u8 fields are
read *without* `^1` in GPGX and so need one here; the sample read already carries
an explicit `^1` (`cart.rom + sfx_ptr + (voice->ptr^1)`) and so must NOT be
swapped again. Getting either backwards still yields plausible output - the first
pass here decoded sane-looking waveforms while reading the wrong byte throughout.

Three checks catch it, and `--verify` re-runs them:

1. **Contiguity** - entries must pack end to end. 114 exact joins, 12 padded to a
   word boundary, 0 unexplained. This also confirms `size` is in samples and that
   the depth field is read correctly.
2. **Range** - the whole bank must land inside the 8 MB ROM. It does.
3. **Nibble order** - GPGX specifies high-nibble-first; an independent smoothness
   metric must agree. With the byte access wrong it voted low-first 64/79; with it
   right it votes high-first 63/79. That flip is what exposed the bug.

#### Confirmed: the punk-TV audio is SFX 0x4A

Identified by ear from the dump. **`sfx_074` / index `0x4A`** - the longest entry
in the bank: 29,920 samples, 6000 Hz, 4-bit packed, 4.99 s, 14,960 bytes at ROM
`0x2B6...` (`sfx_ptr + 0x0584CA`).

That closes the question this section opened, and it **reclassifies the issue
entirely**:

- The punk-TV cue is **not a music track**, so "the audio was never released" was
  the wrong diagnosis. Nothing is missing - the audio has been in the ROM all
  along, 900 KB from the music the project has been substituting.
- Music being silent in that scene is **correct behaviour**, consistent with the
  null pointer at whichever index the scene requests.
- Neither the OST pack, the cue, the blob, nor `paprium_cdda_fetch` was ever
  involved. Three of the four "what would actually fix it" options listed earlier
  - decode the wave ROM, render with the synth, record from a real cart - were
  aimed at the wrong subsystem.

#### Why it is silent here, and what is not the cause

Our SFX engine is **not** the suspect. `sfx_chan` (`audio_sfx.sv`) is a pure
streaming FIFO: the MCU firmware reads the ROM, unpacks the 4-bit nibbles and
pushes 16-bit samples; the RTL only paces them at `srate` and mixes. There is no
`ptr` or `size` in the RTL, so nothing there caps sample length, and a 4.99 s clip
is just a longer stream. 6000 Hz is 3 KB/s against a 256-entry FIFO holding 42 ms
- not a bandwidth problem either.

So if it is genuinely silent on hardware, the cause is upstream of the RTL: the
firmware not receiving or not acting on the trigger. That puts it in the same
family as issues A/B (the MCU falling behind on SDRAM port 2 and missing events),
not in a family of its own.

One mechanism worth noting because it is inherent rather than a bug: `sfx_play`
allocates a free channel, and failing that **evicts the channel with the largest
`time`** - the longest-running one. At 4.99 s, `0x4A` is by a wide margin the
longest sample in the bank, so any later effect sharing its channel mask will
steal it. That happens on real hardware too, so it is a design property, but it
does mean the cue can be cut short legitimately.

**The first thing to establish is whether it is actually silent at all.** The
original "punk-TV cue silent" report was about music, and music is *supposed* to
be silent there. It is entirely possible the SFX already plays and there is no bug
left to fix.

#### A cheap fix that needs no firmware work

If the SFX path does turn out not to deliver it, this port can serve the cue
through the music path instead, because we now hold the sample:

`sfx-dump/sfx_074_punktv_48k_stereo.pcm` - the same audio resampled 6000 -> 48000
Hz with linear interpolation and duplicated to stereo, 957,440 bytes, already in
the blob's track format. Drop it in at whichever index the track-number diagnostic
reports and the scene plays its own sound, with no `mcu.txt` rebuild and no
reverse engineering.

That is the payoff from the two findings meeting: the diagnostic names the index,
and the SFX dump supplies the audio to put there. **Do not do both** - if the SFX
path already plays `0x4A`, adding it to the blob doubles it.

### Note: the 1.000 s "silences" in the blob are our own tooling

Recorded so it is not mistaken for evidence. `scripts/build_cdda.sh` runs
`dd if=/dev/zero bs=192000 count=1` for any cue entry pointing at `Blank.wav`, so
`cdda/track08.pcm` and its nine siblings are exactly one second of zeros because
*our script made them that way*. The length says nothing about the game, and the
real `Blank.wav` has never been read by anything here.

The cue does **name** `Blank.wav` for those ten rather than omitting them - an
authored decision, and consistent with the null pointers above.

This is also why `DIAG_MODE` streams from a fixed `DIAG_SRC` rather than the
requested track: the `hdr_len == 0` silence path never fires for these entries,
so the fetcher would stream one second of digital silence and the readout would
be **silent for exactly the ten cases it exists to name** - indistinguishable
from "the scene never asked for a track at all".

### Build commands

    quartus_sh -t scripts/syn_check.tcl paprium        # fast, synthesis only
    quartus_sh -t generate.tcl paprium                 # full, shipping build
    quartus_sh -t generate.tcl paprium_cddadbg         # diagnostic build
    python scripts/reverse_bitstream.py <in.rbf> <out.rbf_r>

Always check the fit summary timestamp AND the .rbf size against the previous
build before flashing. Several builds have failed silently and left stale
artifacts, which produce believable wrong answers on hardware.


---

## Hardware result: punk-TV closed, and a new lead

Tested on the diagnostic build. **The punk-TV sound effect plays** - and so do
all the other effects that had been written off as missing or wrong.

That closes the punk-TV issue outright. It was never a bug: the audio is SFX
`0x4A`, it has always been in the ROM, and the music being silent in that scene
is the correct response to a null pointer. No fix is needed and none should be
applied. In particular **do not** add `sfx_074_punktv_48k_stereo.pcm` to the
blob - the SFX path already delivers it and the blob copy would double it.

### But "all the lost effects came back" is a finding of its own

The effects were never lost. They were inaudible, and they became audible under a
build whose only behavioural difference is that **music stops after ~17 seconds**.

`CDDA_DIAG` changes the fetcher's source track, its looping, its stop handling and
its burst counting, and gates `mdp_stop_request`. None of that is anywhere near
the SFX path - `audio_sfx.sv` is fed by the MCU and shares no resource with the
CDDA fetcher, which streams from the APF bridge into block RAM and never touches
the MCU's SDRAM port. The one audio-path consequence of the diagnostic build is
that the music term is absent for most of a level.

So the correlation points at the mix, and the mix has a real headroom problem:

    mix = base_audio (16-bit FS) + paprium_sfx (16-bit FS) + cdda * 294/256

The CDDA term alone reaches ~1.15x full scale. All three together reach about
**3.15x** what the 16-bit output can carry, and the clip is hard. Under a hard
clip the loudest term is what survives; a quiet effect over loud music does not
attenuate, it *disappears*. That also fits the earlier report that "the boss
getting hit isn't the same sound" - clipping distortion, not a wrong sample.

**This is not a Pocket regression.** MiSTer's `MegaDrive.sv:999-1012` is the same
expression with the same `294` and the same clip, carried over deliberately. If
the diagnosis holds, it is an upstream property that this port inherited, and it
would be audible on MiSTer too.

### Measuring it instead of guessing

The fix depends on a number that only real hardware can supply, and guessing it
costs a 40-minute build per guess. So the gain is now **menu-selectable**:
Music Volume, id 9 at `0x0000002C`, eight steps from the shipping value down to
Off. Default is index 0 = 294, so shipping behaviour is unchanged for anyone who
never opens the menu.

The measurement is then a single build and a few minutes with the menu:

| Setting | If the effects are audible | If they are still missing |
|---|---|---|
| Default (294) | nothing to fix; it was masking, not clipping | - |
| Off (0) | confirms the music term is responsible | the cause is not the mix at all |
| somewhere between | that step is the answer | - |

The useful outcome is the **highest** setting at which the effects stay audible -
that is the real headroom figure, and it is worth reporting upstream either way.

If the answer turns out to be "the mix needs restructuring rather than turning
down", the next step is a proper limiter or a duck on the CDDA term keyed off SFX
activity, rather than a fixed attenuation. Do not build that until the number
above says it is needed.

### Fixed in passing: MD+ CDDA gain in the non-Paprium builds

`cdda_mult` was hard-coded `294` for every variant. MiSTer selects on
`paprium_active` and gives ordinary MD+ content `93/256`; only Paprium gets the
boost. So the MegaDrive core in this repo was playing MD+ CDDA about **10 dB
hot**. Now `PAPRIUM ? 294 : 93`, which folds away at elaboration since `PAPRIUM`
is a localparam. Unrelated to the Paprium work, found while reading the mix.


### Build: menu-selectable music level

| | ALMs | RAM blocks | DSP | worst slack | TNS |
|---|---|---|---|---|---|
| shipping, as tested on hardware | 18,133 (98%) | 247 (80%) | 41 | (not recorded) | (not recorded) |
| earlier "+ CDDA" reference row | 18,100 (98%) | 249 (81%) | 39 | -3.040 | -1347.5 |
| **+ Music Volume menu** | **18,158 (98%)** | 247 (80%) | 39 | **-3.030** | **-2991.1** |

Fit succeeded with 322 ALMs spare. Making the multiplier variable cost **25 ALMs**
and no DSP - the concern that it would tip the fit did not materialise, so the
power-of-two fallback was not needed.

**Worst-case slack is unchanged** (-3.030 against the -3.040 reference), and the
failing paths are the same inherited `m68kcpu` ones this core has always had - no
audio path appears. **TNS more than doubled** though, -2991 against -1347, which
is more failing paths rather than a worse one, consistent with congestion at 98%.

Two caveats on that comparison, stated because they limit what it proves: the
-1347.5 figure is from an earlier tree than the bitstream actually tested on
hardware, and no TNS was recorded for the tested build itself. So this is a
doubling against an approximate baseline, not against the known-good one. Record
TNS for every build from here.

The practical read: worst-case slack predicts failure better than TNS, and it did
not move. Flash it, and if new glitching appears that the previous build did not
show, suspect this rather than the audio change. `build_output/paprium_SHIPPING.rbf_r`
is the rollback.

### What removing menu options would actually buy

Asked during this session; answered with fitter data rather than estimates.

Deleting entries from `interact.json` frees **zero** ALMs - it is metadata, the
config register keeps its default and the logic behind it is still synthesised.
Saving area means hard-wiring the setting to a `localparam` so Quartus can
constant-fold the unselected paths, and only then removing the menu entry so the
UI does not offer a control that does nothing.

Per-entity ALMs from `megadrive_pocket.fit.rpt`:

| Option | Logic behind it | Realistic saving |
|---|---|---|
| Audio Filter | `audio_cond` **378** (FM LPF 70, Genesis LPF 50, PSG IIR 136, CE gen 28) | ~150-250 pinned to one mode |
| FM Chip | `fc1004` **7,862** - but both modes are the same core with a ladder-DAC switch | tens; not a lever |
| Composite Blend | small video-path filter | ~50-150 |
| CRAM Dots / 6-Button / Region / Aspect | a few muxes each | negligible |

`audio_mixer` (497) is APF's output stage, not a setting.

Ceiling is roughly **200-400 ALMs**, nearly all of it Audio Filter, at the cost of
a real feature. Not worth spending on a diagnostic: once the music level is
measured the shipping build gets a constant and the multiplier folds away by
itself.


---

## Hardware: the punk-TV cue works

Reported working **loud and clear**, with this exact configuration:

| Where | Setting |
|---|---|
| Core menu | Music Volume = **Default** (i.e. 294, the shipping gain) |
| Core menu | Audio Filter = **No Filter** |
| Core menu | Region = **Export** (changed from Auto) |
| Game menu | Background FX slider = **max** |
| Game menu | Music slider = **max** |
| Game menu | +6 dB gain = **checked** |
| Game menu | VM DAC = **unchecked** (using the DT128VALT DAC) |

The cue was never missing, never mis-decoded, and never lost to the mixer. `0x4A`
is the working-TV sound, it is in the ROM, the firmware triggers it and the RTL
plays it.

### Four theories this refutes

Recording these because each was argued from real evidence and each was wrong.
The pattern is the same every time: a plausible mechanism, reasoned confidently,
overturned the moment hardware was asked.

1. **"The audio was never released."** Wrong subsystem entirely - it is an SFX,
   not a music track.
2. **"`0x4A` is TV static, so silence is correct."** Broadband noise with an
   envelope is equally what crowd noise or a broadcast bed looks like. The
   spectrum measurement did not support the specific conclusion drawn from it.
3. **"The mix clips and swallows the effects."** The clip arithmetic is real -
   294/256 plus two full-scale terms overflows a 16-bit output about threefold -
   but it is **not the operative cause**. At the *same* 294 gain the effects are
   clear once the game's own options are right. A correct mechanism can still be
   the wrong explanation.
4. **"It is a gap in the substitute `mega-ppm` firmware, so it is unfixable."**
   The firmware framing is accurate - the NEORV32 image really is a ~16 KB
   reimplementation and the STM32/MAX 10 really are undumped - but it was applied
   to a cue that works. Reaching for the unfixable explanation is the most
   expensive mistake available, because it stops the search.

A default change to `cdda_mult = 93` had been written and had passed synthesis on
the strength of theory 3. Hardware refuted it before the build shipped. **It was
reverted; the default stays 294.** Had that gone out it would have made things
worse while appearing to be a fix.

### Still worth knowing: which setting was load-bearing?

Seven things changed at once, so the cause is not isolated. Cheap to narrow, no
build required - revert one at a time and see if the cue disappears:

- **Audio Filter** back to Model 1. The strongest candidate: the cue is a 6 kHz
  sample and the Genesis low-pass models attenuate exactly that region. If this
  is it, our LPF may be more aggressive than hardware and worth comparing.
- **Region** back to Auto. If Auto is detecting Japan for a `T-574120-00` cart
  the detection is wrong (`detected_jap`, written by the loader at bridge address
  `0x18`, consumed at `core_top.sv:599`), and that is a real bug affecting more
  than audio.
- **+6 dB gain** unchecked, and the sliders down from max.

If Region turns out to matter, chase `detected_jap` first - a mis-detected region
would explain far more than one sound effect.

### Note: the in-game audio options exist and are wired through

Easy to forget the game has its own mixer. The background-music slider reaches us
as the MD+ volume command and **is** honoured - `paprium_cdda_play.sv:126`:

    wire [15:0] vol_product = {8'd0, volume} * {8'd0, fade_vol};
    wire  [7:0] eff_volume  = vol_product[15:8];

So any RTL gain calibration must be done with that slider at a known position, or
the two attenuations compound. The "VM DAC" checkbox picks between the YM2612 DAC
(FM path, via `audio_cond`) and the DT128VALT DAC (our `audio_sfx`), which are two
entirely different paths through this core - a useful bisection tool for any
future "which chip is this sound coming from" question.


---

## Testing protocol: Reset Core is NOT a clean start

The single most important process finding of this project, and it invalidates an
unknown amount of earlier testing.

**Reset Core does not clear SDRAM.** `sys_reset` restarts the 68000 and the MCU
(`cartridge.sv:543` takes `.reset(reset)`), but nothing wipes memory - the
`reset_sdram` signal only initialises the controller. After a reset, SDRAM still
holds the ROM *plus everything the MCU decompressed and wrote there during the
previous session*.

Only quitting the core and relaunching gives a clean slate: the FPGA is
reconfigured, every register returns to its initial value, and the ROM is
re-downloaded from the card.

This matters more than usual here because the documented way to reach the game is
"play the mini-game, **reset the core**, play the real game." Every test done that
way ran on carried-over state.

### What it already explained

The punk-TV cue appeared to be region-dependent - working on Export, silent on
Auto and Japan. It is not. **It works in both regions.** The apparent link was
carried-over state from the previous session, because region changes were tested
with a reset rather than a full reload.

That also resolves a discrepancy worth recording: the RTL says Auto and Export
must be *identical* for this core. The Paprium package's `core.json` lists one
entry and no loader, so nothing ever writes bridge address `0x18`, `detected_jap`
stays 0, and `cfg_jap` is 0 for both. The header is `JUE` and the loader's
priority is US > EU > JP, so even with a loader it would resolve to Export. The
code reading was right; the observation was confounded.

### Protocol from here

1. **Quit the core and relaunch between every test.** Never use Reset Core to set
   up a measurement.
2. Region, and anything else latched at boot, only takes effect on a full reload.
3. When a result looks like it depends on a setting, re-confirm it with a clean
   reload before believing it.

### Worth retesting under this protocol

Results obtained with resets are now suspect and cheap to re-check:

- **Elevator corruption** (issue 2 on the list). Currently attributed to upstream
  firmware. If it turns out to need a stale-SDRAM session to reproduce, that
  attribution is wrong and the bug is ours.
- **The intermittent single-pixel flicker** during the intro.
- **Boss-fight sprite priority.**

### Should the reset be made to clear SDRAM?

Not obviously. A console reset does not wipe the real cartridge's memory either,
so the current behaviour is arguably faithful - the difference is that our MCU is
a ~16 KB reimplementation and may not re-initialise as thoroughly as the real
STM32 does. Worth knowing before treating this as a defect to fix. The protocol
above costs nothing and removes the variable either way.


---

## Menu reduction: trading options for ALMs

The core carried the base MegaDrive core's full option set. Most of it is not wanted
for a single-game core, and at 98% ALM the logic behind it was worth more than the
choices. Removing a menu entry frees nothing on its own - the saving comes from
hard-wiring the setting to a `localparam` so Quartus can constant-fold the
unselected paths, which is what was done in each case.

### Removed, and why

| Option | Now | Rationale |
|---|---|---|
| Audio Filter | `localparam CFG_LPF = 2'd3` (No Filter) | **Measured on hardware: any other mode stops the punk-TV cue being audible.** Also the cheapest arm - see below |
| FM Chip | `CFG_FM = 1'b0` (YM2612) | The YM3438 option was never wanted here |
| CRAM Dots | `CFG_CRAMDOT = 1'b0` | Mega Drive artefact, not wanted |
| Composite Blend | `CFG_BLEND = 1'b0` | Lets the fitter drop `cofi` entirely |
| Music Volume | gain is a constant again | Served its purpose; it is how the masking was measured |
| Region: Auto | removed from the menu | It never worked - see below |

Region is now an explicit **Japan (default) / Export**, labelled
"Region (hard restart req'd)" because it is latched at boot. Reset Core is renamed
**Soft Reset (mini game)**. A menu hard-reset that clears SDRAM was considered and
dropped: the Pocket already provides exactly that by exiting the core, and building
it would have meant re-reading an 8 MiB data slot mid-session, which is untested
and would have *added* logic to a change meant to remove it.

### Auto never did anything

Worth recording because the RTL said so before hardware did. This core's
`core.json` lists a single bitstream and no loader, so nothing ever wrote bridge
address `0x18`, `detected_jap` stayed 0, and Auto resolved to Export every time.
Even with a loader the header is `JUE` and the loader's priority is US > EU > JP,
so Auto would still have meant Export. The register is gone.

### The audio filter arithmetic, which came out backwards

Hard-wiring to *No Filter* saves considerably more than hard-wiring to Model 1 -
the opposite of the intuition that "no filter" simply removes a filter.

    al <= ((lpf_mode == 1) ? md_fm_lpf_l : md_fm_l) + sms_fm
                                         + ((lpf_mode == 3) ? psg_amp : psg);

`psg_amp` is `PSG + PSG[15:1]`, one adder. Every mode *except* 3 routes the PSG
through `psg_iir`, which costs **146 ALMs** on its own. So mode 3 drops `psg_iir`
(146), `genesis_lpf` (50, bypassed at mode 3) and `genesis_fm_lpf` (66, mode 1
only) - about **262 ALMs** plus the muxes. Model 1 would have kept the first two.

The user's preference and the cheapest option coincided, which is luck rather than
design. The cost is real though: No Filter is **less authentic** than the low-pass
a real Mega Drive has. A deliberate trade for one game.

One loose end: `paprium_sfx_l/r` is summed in `core_top` *after* `audio_cond`, so
the LPF should not touch the cart's SFX at all. Hardware says it does. Either the
cue has a PSG component or the filter attenuates enough to mask it. The action is
the same either way, so this was noted rather than chased.

### Display modes: free, and capped by firmware

`video.json` `display_modes` are Analogue's own - the schema is just `{"id": ...}`
with **no core-side customisation**, so scanline/mask/curvature parameters are not
available to us. There is exactly **one** CRT mode (`0x10`, CRT Trinitron) and
**no BVM mode at all**; more CRT variants would need Analogue to ship them.

The core declared only `0x10` and `0x40`. It now declares all 22 valid IDs, which
costs nothing and needs no rebuild - it is metadata. Source:
<https://www.analogue.co/developer/docs/core-definition-files/video-json>


---

## The MCU firmware is open source - and ours is not the published build

`krikzz/mega-ppm` is cloned to `repos/mega-ppm`. `mcu/` holds real C source -
`main.c`, `paprium.c/h`, `mame.c/h`, `mdp.c/h`, **`sfx.c/h`**, `everdrive.c/h`,
`cfg.h` and a `Makefile` that produces the `mcu.txt` we load with `$readmemh`.

**This corrects an earlier claim in this document.** The elevator corruption, boss
sprite priority and the SFX faults were repeatedly filed as "upstream firmware,
needs the undumped STM32/MAX 10". The chips are indeed undumped and that remains
irrelevant: the firmware this core actually runs has published source.

### But our image is not krikzz's

    repos/mega-ppm/mcu/mcu.txt         35,615 bytes   245 lines   ec08f761...
    paprium-pocket/.../mcu.txt         35,906 bytes   248 lines   0f1a2b90...

Byte-identical to MiSTer's, and **different from krikzz's from line 1** - line 2
alone changes the stack-pointer setup (`130101FC` vs `130101F8`), so it is a
different compile rather than a patch. `mcu.txt` has a single "init" commit
upstream, so there is no older revision that matches.

MisterPezz82's `docs/KNOWN_ISSUES.md` says "our firmware" throughout and cites
line numbers (`mame.c:544`), so our image is **their modified build**. Their repo
publishes no `.c` files, so we hold krikzz's source and MisterPezz82's binary,
and not the source that produced what we run.

**Consequence: rebuilding from krikzz's source does not reproduce our firmware.**
It would produce upstream's, silently dropping whatever MisterPezz82 changed.
Before any firmware work:

1. Build krikzz's source unmodified and check it reproduces *their* `mcu.txt`.
   That validates the toolchain against a known target before anything is changed.
2. Ask MisterPezz82 for their source, or reconstruct their changes from
   `KNOWN_ISSUES.md`, which documents several of them.
3. Only then patch, and keep the diff minimal.

Also worth weighing: our `mcu.txt` currently matches MiSTer's exactly, so any bug
we hit is reproducible against a second implementation. Diverging gives that up.

### What their engineering record already tells us

`repos/paprium-mister/docs/KNOWN_ISSUES.md`, 258 lines. Highlights that change
what is worth trying here:

- **The sprite-attribute fix was already built and tested on hardware, and did NOT
  fix the elevator** (2026-06-25). The hypothesis - that elevator sprites set both
  tile and object priority bits, so `mame.c:544`'s whole-word XOR cancels them -
  was wrong. It was kept in V.04 as harmless but is explicitly not an elevator
  fix. **Do not spend a build re-deriving this.**
- **Elevator root cause is recorded as shared-SDRAM port starvation**, with the
  MCU clock ruled out (NEORV32 runs at 50 MHz).
- **Confirmed broken on EverDrive Pro too**, so it is firmware, not the core or VDP.
- **Decompression is ruled out** - the `0x80`/`0x81` decoders match GPGX exactly.

### The lead worth taking: command 0x88 is muted in our firmware

`KNOWN_ISSUES.md` lists `0xB0 paprium_sprite_init` and **`0x88
paprium_audio_setting`** as "muted in our firmware but real in GPGX".

`0x88` is small, fully specified by GPGX (`paprium.h:2006`), and is exactly the
command behind the in-game **VM DAC** checkbox:

    paprium_s.audio_flags = flags;
    paprium_s.ram[0x1801] = flags & 0x01;                    /* dac  */
    paprium_s.ram[0x1800]  = (flags & 0x01) ? 0x80 : 0x00;   /* dac  */
    paprium_s.ram[0x1800] += (flags & 0x02) ? 0x40 : 0x00;   /* ntsc */

If our firmware ignores it, the game's audio configuration is never stored and it
reads back stale values from `0x1800`/`0x1801`. That is a plausible contributor to
SFX behaving differently from hardware - including the boss/large-enemy death
playing an ordinary enemy's sound - and it is a handful of lines to implement.

Sequence: confirm the toolchain first, then `0x88`, then re-test. One change at a
time, since we have just spent a session learning how easily a plausible
explanation survives an untested build.


## Build: menu reduction measured

| | ALMs | Registers | RAM blocks | DSP | worst slack | TNS |
|---|---|---|---|---|---|---|
| before (full menu) | 18,158 (98%) | 30,399 | 247 (80%) | 39 | -3.030 | -2991.1 |
| **after (menu stripped)** | **16,753 (91%)** | 30,071 | 246 (80%) | **21** | **-2.856** | **-2034.8** |
| delta | **-1,405** | -328 | -1 | **-18** | +0.174 | +956 |

**The estimate was 250-470 ALMs. The actual figure is 1,405 - low by about 3x.**

The error was method, not arithmetic. The estimate summed the named leaf entities
in the fit report and assumed everything else was fixed cost. What it missed is
that constant-folding **cascades**: tying an option off removes not just its
filter chain but the control logic feeding it, its CDC path through `synch_3`, the
muxes selecting between arms, and - the big one - the **DSP multipliers** those
filters inferred. DSP usage fell 39 -> 21, which no ALM-only reckoning would catch.

Confirmed gone from the fit report: `psg_iir`, `genesis_lpf`, `genesis_fm_lpf`,
`cofi`. `audio_cond` survives at **67.7 ALMs**, down from 383.

The timing prediction, by contrast, was about right: "-2.7 to -2.9, maybe 0.1-0.3
ns, with TNS improving more than worst-case slack." Actual: **-2.856** (+0.174)
with **TNS down 32%**. Still the same inherited `m68kcpu` critical paths, and
timing still does not close - this buys margin, not correctness.

Lesson for future estimates on this device: **entity-level ALM figures are a
lower bound**, because they attribute nothing to the glue that disappears with
them, and nothing at all to DSP.

1,727 ALMs are now free. That is real headroom for firmware-adjacent RTL work -
a mailbox snooper, deeper SFX FIFOs - none of which was affordable at 98%.


## Hardware confirmation: slim build, Japan region, No Filter

Tested and working. New four-item menu present, and **the punk-TV cue works as
intended**. This is the first time that combination has been verified together -
the cue had only ever been confirmed on Export, on the pre-slim bitstream.

So the shipping configuration is now confirmed end to end:

| | |
|---|---|
| Bitstream | 16,753 ALMs (91%), md5 `6116d16c` |
| Region | Japan (default), JP extras present |
| Audio filter | hard-wired No Filter |
| Menu | Soft Reset / Region / 6 Button Pad / Aspect Ratio |
| Display modes | 22 |

### Process note: a duplicate package cost a round trip

An old copy of the core package sat at `hw-test/pocket-install/`, frozen at
2026-08-26. It was installed by mistake - reasonably, given the directory name -
which silently reverted the card to the 8/26 bitstream and menu. The symptom
(removed menu entries still listed) looked like a failed build.

Two consequences worth recording:

1. **The earlier music-volume measurements were taken on a bitstream with no
   music-volume menu.** The masking/clipping theory built on them was resting on
   nothing. Hardware refuted that theory independently and the default was
   reverted before shipping, so no bad code went out, but the reasoning was
   unsupported at the time it was written down.
2. `hw-test/pocket-install/` now contains only a README pointing at `pkg/`. The
   package is built in exactly one place, and `scripts/deploy_to_sd.sh` force-
   copies the whole directory and prints the resulting menu so a stale file is
   visible before ejecting.

**Verify the card, not the report.** Cheap, and it would have caught this
immediately.


---

## Boss / large-enemy death plays the wrong sound

**The correct sample is identified: `0x1C`** (`sfx_028_0x1C_9600Hz_4bit_2.15s.wav`),
9600 Hz, 4-bit, 2.15 s, autocorrelation 0.895 - one of the most tonal in the bank.
Identified by ear from the dump; it is the death sound for large "fat" enemies and
most bosses. What plays instead is an ordinary enemy's death sound.

### How the request reaches us

`paprium_w16` (`paprium.h:2658`): a **16-bit write to cart RAM offset `0x1FEA`**
dispatches every Paprium command.

    if( address == 0x1FEA ) { paprium_cmd(data); }
    /* cmd = data >> 8;   parameter = data & 0xFF */

So `sfx_play` of sample `0x1C` is a single write of **`0xD11C`**, with the channel
mask at `0x1E10`, volume `0x1E12`, pan `0x1E14` and flags `0x1E16` written just
before. All of it is visible to our RTL.

Note this is **not** the MD+ protocol our `paprium_mdp_adapter.sv` decodes
(`$11xx`/`$12xx`). That adapter is the CDDA overlay this port added. Paprium's own
commands go to the MCU, which polls cart RAM.

### Eviction is ruled out by argument, not by test

`sfx.c`'s allocator evicts the **oldest** channel when no masked channel is free -
and then plays the **new** sound in it. Eviction can silence an older effect; it
can never silence the incoming one. So "a different sound plays instead of `0x1C`"
cannot be eviction, and the earlier eviction hypothesis is dead.

That also disposes of the layered-sound theory: if the game asked for `0x1C` it
would be heard, whatever else was competing.

### What is left, and the test that separates it

| Log at the kill | Meaning |
|---|---|
| `0xD11C` present | requested correctly - our firmware or RTL plays the wrong sample. **Ours, fixable** |
| a different `0xD1nn` | the game asked for the ordinary sound; divergence is earlier, in game state |
| no `0xD1` nearby | the cue arrives by a path our firmware mutes - `0xD3 sfx_loop`, or `0x88` |

**Diagnostic design.** Snoop 16-bit writes to cart RAM `0x1FEA`, keep a ring of the
last N commands with their `0x1E10` channel mask, and expose it through APF. Write
it to a **separate nonvolatile data slot, not the save slot** - the 4 KB save is
the player's actual progress and a diagnostic must not overwrite it.

Affordable now: the menu reduction freed 1,727 ALMs, where at 98% this was not
buildable at all.


### Command-log build measured

| | ALMs | RAM blocks | block mem | worst slack |
|---|---|---|---|---|
| shipping | 16,753 (91%) | 246 (80%) | 1,865,044 (59%) | -2.856 |
| **+ command log** | **17,970 (97%)** | 262 (85%) | 1,996,116 (63%) | **-3.141** |

The ring itself is cheap and went where intended: block memory grew by exactly
131,072 bits = 4096 x 32, and RAM blocks by 16, so the buffer inferred correctly.
The **1,217 ALMs** are almost all the second `data_unloader` - the dcfifos and
state machine to serve a slot over the bridge cost far more than the buffer does.
Worth knowing before adding a third slot to anything.

Timing is 0.285 ns worse than shipping, which is what 97% looks like, and no worse
than builds already proven on hardware (the first shipping build ran at -3.040).
Acceptable for a diagnostic; it is not a build to ship.

**The first attempt at this build crashed** - `quartus_fit` took an Access
Violation at "Fitter placement preparation", 2:42 in, because the previous build
had been killed mid-fit and left corrupt incremental state. Clearing
`projects/db` and `projects/incremental_db` fixed it. **If a build is killed, wipe
those before rebuilding.**

It also nearly went unnoticed: the command was written
`quartus_sh ...; echo "EXIT=$?"; grep ...`, so the reported exit status came from
the trailing `grep` and read 0 on a failed build. Only the fit-summary timestamp
caught it. Had it passed unremarked, the "diagnostic" package would have carried
the shipping bitstream, with no logger in it, and a full playthrough would have
produced an empty log. **Check the timestamp and size; never trust the exit code
of a compound command.**


---

## Proposal: IMA ADPCM for the music blob

Not urgent, and not a constraint anyone is currently hitting - a 2.25 GB blob sits
happily on a card with 953 GB free. Logged because it is a real improvement and
the analysis behind it should not have to be redone.

### The blob today

    cdda-blob/paprium.pcm   2,245,919,744 bytes   195 minutes
    48 kHz, 16-bit, stereo, headerless PCM at 192 KB/s

53 unique tracks. Deduplication is not worth doing: the only repeats are the ten
`Blank.wav` silences, all one second of zeros, wasting **1.7 MB**. The format is
uncompressed deliberately, so the fetcher can seek by byte offset without decoding.

### Why IMA ADPCM

4 bits per sample, **4:1**, keeping 48 kHz and stereo: **2.25 GB -> ~562 MB**.

The property that matters is that it is block-based. Each block carries its own
predictor and step index, so decoding can start at any block boundary - which is
exactly what `paprium_cdda_fetch` already does when it seeks to a chunk boundary.
The seek mechanism does not change; each chunk simply covers 4x more audio.

Decoder cost is an 89-entry step table, a 16-entry index table, and some adds and
shifts. Small against the 1,727 ALMs the menu reduction freed.

**The better reason is bandwidth.** Reading a quarter as many bytes cuts the CDDA
path's bridge traffic 4x, on the subsystem that has caused the most trouble in this
project - underruns, stale-chunk races, the stale-`done` bug twice. That headroom is
worth more than the disk saving.

### Work involved

- ADPCM decoder module between `data_loader` and `paprium_cdda_buf`
- Bytes-per-sample arithmetic in `paprium_cdda_fetch` and the blob header's length
  fields; chunk size must land on block boundaries
- `build_cdda_blob.sh` needs an encoder (ffmpeg `adpcm_ima_wav`, or ~30 lines of
  Python)
- **Format change** - every existing blob must be rebuilt, and the core should
  reject or detect an old one rather than play noise
- Its own hardware test pass. Music took four attempts to get right; it earns one

### Why not a real codec

Asked and answered, so it does not get re-asked. Two routes, both dead on this
device.

**In RTL.** MP3 needs Huffman decode over ~30 tables, requantisation, stereo
processing, alias reduction, a 36-point IMDCT, and the synthesis polyphase
filterbank - 32 subbands against a 512-tap window. Published FPGA implementations
run **5,000-15,000 LEs plus DSPs and coefficient ROM**. We have 1,727 ALMs. Vorbis
is worse (variable MDCT to 8192, codebooks in the tens of KB); Opus is a CELT/SILK
hybrid essentially nobody implements in pure RTL.

**On a soft CPU.** The realistic route generally, and it dies on two numbers here.
`libmad` needs ~40 KB of code plus working RAM, against **62 free M10K = 77 KB
total** before the CPU's own needs - and a small RISC-V with a multiplier is itself
1,500-2,500 ALMs, already more than we have. Throughput is worse: stereo 48 kHz MP3
is ~20-30 MIPS on an integer core with no DSP, and NEORV32 at 50 MHz gives perhaps
15-25, which must never miss a deadline. The existing MCU cannot help - 16 KB of
ROM, fully occupied servicing the 68000.

Seeking would also stop being free: byte offsets no longer address frames, so the
blob would need a frame index built at packing time.

| Codec | Ratio | Cost |
|---|---|---|
| IMA ADPCM | 4:1 | ~100-200 ALMs |
| FLAC | ~1.8:1 | feasible, poor payoff |
| MP3 | ~11:1 | 5-15k LEs, or a CPU that does not fit |
| Vorbis / Opus | ~12:1 | soft CPU + tens of KB, not viable |

The complexity curve between ADPCM and MP3 is brutal; the size curve is not
(562 MB against ~200 MB). A hundred times the logic for a further 2.8x.

On a larger FPGA the answer differs. On a 5CEBA4 already at 91% with a gate-level
68000 and VDP in it, it does not.


---

## The command logger works, and boot already answered two questions

### Getting the file written: a datatable entry, not just data.json

The first capture came back with no file at all. **APF creates a nonvolatile file
from the DATATABLE, not from `data.json`** - `core_top.sv` writes the save slot's
size there and the comment says so outright:

    // APF creates a .sav for every game unless the slot size reads back 0
    wire [9:0]  datatable_addr = 10'd3;      // the save slot's index
    wire [31:0] datatable_data = ... SAVE_SIZE;

Slot 11 was declared in `data.json` and given no datatable entry, so APF never
created `Paprium.log`. A full playthrough was spent on a logger with nowhere to
write - my bug, and the smoke test that caught it cost two minutes against the
two levels it saved.

**Workaround, and it works:** pre-create the file on the card and APF loads it and
writes it back on exit.

    D:\Saves\paprium\common\Paprium.log   16384 zero bytes

Note the path convention is `/Saves/<platform>/common/<romname>.<ext>` - **not**
`/Saves/<platform>/<Author.Core>/`, which is what Analogue's docs suggest and what
was tried first. Confirmed against the other cores on the card.

A proper fix would add a datatable entry for slot 11. The index is
`(slot_position * 2) + 1` by inference from the save slot at position 1 -> address
3, so the log at position 3 -> address 7. **Unverified**, and writing the wrong
index could corrupt the ROM slot's size, so it was not guessed at while a free
workaround existed.

### Confirmed from a 30-second boot

    96   D1  SFX_PLAY 4E  mask 003F  flags 4000  ECHO
    98   D1  SFX_PLAY 56  mask 003F  flags 4000  ECHO
    58   D1  SFX_PLAY 01  mask 003F  flags 2100  pitchHalf, AMPLIFY

**The game really does request echo and amplify**, and this port implements
neither. That is no longer inference from GPGX source - it is measured, on real
hardware, during the boot sequence alone. Every effect that asks for them is drier
and quieter than the cartridge.

**`0x88 audio_setting` fires five times during boot**, parameters `02` and `0A` -
the NTSC and DAC configuration bits - and our firmware ignores all of it, exactly
as MisterPezz82's KNOWN_ISSUES.md records.

### Caveat when reading a capture

`flags` and `vol` are the **last values latched** from `0x1E16`/`0x1E12`, not
values carried by the command itself. A command that does not write them shows
whatever the previous one left - the first few boot entries show `AC4C`/`9000`,
which is uninitialised. This is faithful rather than a bug: `sfx_play` reads the
same latched RAM. Only trust flags on an `SFX_PLAY` whose parameters were written
alongside it.


---

## Plan: rebuilding the MCU firmware ourselves

MisterPezz82 will not be sharing their firmware source, so any firmware change has
to start from krikzz's tree. This is the plan, and it is more tractable than it
first looked.

### What we know

Our `mcu.txt` is byte-identical to MiSTer's (`0f1a2b90`, 248 lines) and differs
from krikzz's published build (`ec08f761`, 245 lines) from line 1 - a different
compile, ~48 words larger. **No `.c` or `.h` file has ever been committed to the
MiSTer repo**, confirmed across all history, so only the binary was ever published.

But their commit messages describe the firmware changes at source level, which
means the delta is small and documented. Across the entire history, `mcu.txt`
changed in four commits, and only two firmware changes are described:

| Change | Origin | Description as given |
|---|---|---|
| First-level door fix | krikzz | object 107, sprite 4, `attr &= ~0x2000` |
| Sprite attribute composition | MisterPezz82 | field-wise per GPGX with the `0x7ff` tile-index mask, replacing the whole-word XOR at `mame.c:544` |

~48 words is consistent with two small changes, not a rewrite.

### The tree builds standalone

`repos/mega-ppm/mcu/` is self-contained. The Makefile's `NEORV32_HOME = ../neorv32`
is misleading - the paths actually resolve to a bundled `lib/`:

    lib/include/neorv32.h      the framework headers
    lib/common/crt0.S          startup
    lib/common/neorv32.ld      linker script
    lib/source/*.c             the runtime

Build settings are pinned by the Makefile: `-O2`, `-march=rv32im`, `-mabi=ilp32`,
`riscv64-unknown-elf`. **The only missing piece is the compiler.**

### Steps, in order

1. **Install a RISC-V toolchain.** xPack `riscv-none-elf-gcc` is the easiest on
   Windows; override `RISCV_TOOLCHAIN` since xPack uses a different prefix.
2. **Reproduce krikzz's `mcu.txt` byte-for-byte.** This is the gating test. If
   `make` reproduces `ec08f761`, the toolchain is pinned and everything downstream
   is trustworthy. If it does not, no diff against our binary means anything,
   because compiler drift will differ on every function.
3. **Disassemble both images and diff.** ~4,000 instructions is tractable. With the
   toolchain pinned, the differences ARE MisterPezz82's changes, which both
   confirms the two documented ones and reveals anything undocumented.
4. **Re-apply the two changes** to krikzz's source and rebuild.
5. **Validate on hardware** against the behaviours their notes name - the
   first-level door, and no regression in scenes that relied on the whole-word XOR.
6. Only then add our own: `0x88 paprium_audio_setting`, currently muted.

### Keep the fallback

`rtl/PAPRIUM/mcu.txt` as it stands is known-good and hardware-validated. Any
rebuild ships as a **variant**, never as a replacement, until it has been A/B'd on
real hardware. Losing a working firmware to chase a fix would be a poor trade.

### None of this blocks the audio work

Echo and amplify are RTL - `audio_sfx.sv` and the mixer, entirely ours. The
firmware question gates only `0x88` and any channel-allocation change. Do the RTL
first: it is specified exactly, it fits, and it improves every effect in the game.
