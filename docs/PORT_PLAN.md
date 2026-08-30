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
| Punk-TV cue silent | **FIXED in firmware** | `sfx_loop` now re-arms a channel that already ended. Both TVs play, level 1 and level 2 |
| SFX inaudible while music plays | **CLOSED - settings, not headroom** | Refuted: at the same 294 gain the effects are clear once the game's own audio options are right |
| Elevator corruption + priority | upstream firmware | Open, issue C |
| Boss fight: sprite drops behind BG | upstream firmware | Open, sprite-attribute XOR |
| "Saxophone guy" never appears | **not yet tested** | Spawns on **Very Hard and above**, on specific stages. Every run so far has been Arcade/Easy, so the conditions have never been met |
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



### CORRECTION: quitting the core does not clear the workspace either

Found when a mini-game test failed: the core was exited and relaunched as the
protocol above instructs, and the mini-game **still did not appear**.

The protocol's claim that quitting gives "a clean slate" is wrong above 8 MiB.

    data.json   "Paprium ROM"  address 0x10000000  size_maximum 0x800000

The ROM slot is exactly 8 MiB, so a relaunch rewrites SDRAM `0x000000-0x7FFFFF`
and nothing else. The MCU's decompression workspace starts at **`0x800000`,
immediately above the ROM** (`paprium_cart.sv`, and the size note above), inside
the same 64 MB chip. Reconfiguring the FPGA does not power-cycle that chip, and
the ROM download does not reach it, so **everything the MCU decompressed in the
previous session survives a core exit**.

The MCU side is identical either way and cannot be the difference: `ppm_reset()`
is unconditional - it re-copies 8 KB from flash and re-applies the boot-check and
post-splash patches on every 68000 reset, cold or soft. So the mini-game is
gated purely on whether the workspace already holds decompressed data.

**Only a full power-off of the Pocket clears it.** A short press of the power
button sleeps the unit and keeps SDRAM powered; the unit must be actually powered
down, then started again.

    to reach the mini-game:  power the Pocket OFF (not sleep), wait a few
                             seconds, power on, launch the core

**RETRACTED - this did not affect any real test.** The above was written
asserting that the elevator, intro-flicker and boss-priority retests had been
run with "quit and relaunch" and were therefore tainted. They were not: the
hardware testing for this project has used a **full power cycle before every
run** throughout. Those results were obtained on genuinely clean state and the
attributions stand as measured.

The workspace finding itself remains true and worth keeping - a core relaunch
really does leave `0x800000` upward intact - but it describes a trap that was
never actually fallen into. It matters only for anyone who tests with a
relaunch instead of a power cycle.


### Power-cycling does not trigger it either - so SDRAM is not the gate

Tested: the Pocket was fully powered off and restarted, and the mini-game **still
did not appear**. That rules out the workspace explanation above as the cause,
though the workspace finding itself stands - a core relaunch genuinely does not
clear `0x800000` upward, and the protocol correction remains valid.

What it establishes is a constraint rather than an answer. A power cycle clears
all of SDRAM, so whatever gates the mini-game either lives **on the SD card** or
is not state at all. The only writable state on the card is the save:

    data.json  "Save"  id 10  nonvolatile  0x20000000  size_maximum 0x1000
    on card    /Saves/paprium/common/<romname>.sav

backed by BRAM at `ADDR_BRM 0x5000000`, which the firmware reads and writes
through `cmd_DF_eep_rd` / `cmd_E0_eep_wr` in banks of 0x200. Paprium's cartridge
carries a real M24C64 EEPROM (`paprium-dump/ChipDocs/m24c64wp.pdf`), so a
"first boot done" flag there would produce exactly the observed behaviour: the
mini-game was seen during Test 1 on a fresh save and has not been seen since.

This is reinforced by the testing practice: every hardware run on this project
is preceded by a full power cycle, so SDRAM state has **never** been carried
between sessions. The mini-game has nonetheless been absent across many builds.
Whatever gates it has therefore survived every power cycle it has ever been
given, which leaves the save as the only candidate that is actually state.

**Next check: rename the .sav (it is the player's progress - rename, never
delete) and cold boot.**

If that also fails, the mini-game is not state-gated and something in this
build changed it. The suspects are the two commands recently un-muted, `0x88
audio_cfg` and `0xB0 sprite_init`, both of which now execute during boot where
they previously did nothing. An older `.rbf` plus a cold boot separates those.


### CONFIRMED: the save gates the mini-game, and its music is not MWMM

Renaming `/Saves/paprium/common/<romname>.sav` and cold booting brought the
mini-game back, after a **language-selection screen** that also only appears on a
fresh save. So first-boot state lives in the EEPROM-backed save, not in SDRAM -
which is why no amount of power cycling reached it.

Practical consequence, worth telling users: **to see the mini-game again, remove
the save.** Rename it rather than deleting it; it is the player's progress.

**The music question is now closed, negatively.** Chiptune music was audible in
the mini-game with `paprium.pcm` renamed away. That proves it is not CDDA. But it
equally proves it is not the cartridge synth, by elimination:

    this core implements no MWMM synth at all - the firmware substitutes CDDA
    for music. Therefore anything audible from it is BY CONSTRUCTION not MWMM.

With CDDA absent and MWMM not implemented, what remains is the 68000 driving the
YM2612/PSG directly - ordinary Mega Drive music held in the ROM. That also
explains why the square-wave renders "sounded like the mini-game": both are plain
chiptune, and the resemblance carried no information about the decode.

So the mini-game is **not** a reference for the MWMM format. The door is closed,
which was the likely outcome recorded before the test and is worth having settled
rather than left open.

**The only remaining reference is a capture of real cartridge audio**, run blind
through `scripts/identify_track.py` against all 52 modules.

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


---

## Echo and amplify implemented in RTL

Measured on hardware first: the boot capture showed `flags 4000` on `SFX_PLAY`
`0x4E` and `0x56`, and `0x2100` on `0x01`, and the gameplay capture showed echo on
nearly every command in the fade loop. The game asks for these constantly and this
port dropped all of it, as MiSTer still does.

Both flags were already reaching the RTL. Our 8-bit `flags` is the HIGH byte of the
16-bit word the game writes to `0x1E16`, so **echo is `flags[6]`** (`0x4000`) and
**amplify is `flags[0]`** (`0x0100`) - no new MCU decode, just two bits that were
being ignored.

**Amplify** scales the RUNNING mix, not the voice - GPGX does `l = (l * 125) / 100`
on the accumulator inside the voice loop, so it is applied at the accumulate step
as `acc + acc/4`.

**Echo** is a single-tap 8000-entry ring - 166.7 ms at 48 kHz - at 33%, no
feedback. GPGX clears each slot, lets voices accumulate into it, advances the
pointer and adds the slot it lands on; overwriting each slot rather than
accumulating gives the clear for free. 33/100 is taken as 84/256 (0.328 against
0.330, inside the noise of 4-bit source material). 8000 x 32 = 256 Kbit, ~26 M10K
against 62 free.

### One deliberate deviation

GPGX assigns each echo-flagged voice to ONE side, alternating as voices are
allocated (`voice->echo = echo_pan++ & 1`). That counter lives in the firmware and
is not visible to the RTL, so the side is taken from the **channel index** instead.
Deterministic, and it spreads echo across both sides the same way, but it is not
bit-identical to GPGX. Recorded because it is the only place this feature departs
from the reference.

### Status

Written, **not yet synthesised** - the command-log build had the Quartus project
locked. Needs `syn_check`, a fit, and a hardware A/B against the current build
before it goes anywhere near shipping.

### Firmware rebuild: batch it with the audio format change

Rebuilding `mcu.txt` from krikzz's tree and moving the blob to IMA ADPCM should
land in the SAME validation pass. Both change audio behaviour, both need a careful
hardware A/B, and doing them separately means two full test cycles for one set of
listening. Neither is urgent; the RTL work above is not blocked by either.


---

## SOLVED: the punk-TV cue never loops, and why

Root cause, from the channel-7 capture. This is measured, not inferred.

    232   SFX_PLAY 4A   mask=0080  vol=0000      cue starts at volume ZERO
    234   ch7: vol=000  fifo=fed    pcm=1
    286   ch7: vol=000  fifo=EMPTY  pcm=29920    whole sample pushed, FIFO dry
    298   ch7: vol=019  fifo=EMPTY  pcm=29920    ramp begins...
    352   ch7: vol=0C0  fifo=EMPTY  pcm=29920    ...fully ramped, nothing playing

**29,920 is exactly the length of sample `0x4A`** - 4.99 s at 6 kHz, matching the
SFX table dump. The MCU pushed the entire sample, it ended, and the PCM count never
moved again. The second TV repeats it: 29921 -> 59840, exactly two plays all
session, neither looping.

### The bug, in krikzz's `sfx_player_update`

    for (int ch = 0; ch < SFX_CHAN_NUM; ch++) {
        if (sfx_chan[ch].size == 0) {
            continue;                     // channel abandoned once it empties
        }
        ...
        if (sfx_chan[ch].size == 0 && sfx_chan[ch].looped) {
            ptr = ptr_base; size = size_base;   // only reachable from inside
        }
    }

The restart fires only on the iteration where `size` reaches zero, and only if
`looped` is ALREADY set. `sfx_play` sets `looped = 0`; the game's `sfx_loop`
arrives about five seconds later. By then the channel is skipped at the top
forever, and the volume ramp lands on a dead channel.

The game is blameless: it starts the cue at volume 0, enables looping, ramps to
`0xC0` and sweeps the pan `0xED -> 0x2A` as the player walks past. Textbook
positional audio, all of it correct.

### The fix - two lines, in `sfx_loop`

    sfx_chan[i].looped = 1;
    if (sfx_chan[i].size == 0) {          /* re-arm a channel that already ended */
        sfx_chan[i].ptr  = sfx_chan[i].ptr_base;
        sfx_chan[i].size = sfx_chan[i].size_base;
    }

**Firmware, not RTL.** So the toolchain work is now the critical path rather than
optional - but precisely specified rather than exploratory.

### Confirmed working: the RTL audio fixes

Reported by ear on the build carrying them: enemies dropping, weapon drops and
explosions are "noticeably louder or piercing through the music in a good way".
That is exactly what the pan fix predicts - one side of every non-centred effect
was phase-inverted and cancelling on the mono speaker, and impacts are the widest-
panned, most transient sounds, so they had the most to lose. Echo and amplify
contribute too. Three fixes shipped and audibly working.

### Firmware headroom is tight

    krikzz mcu.txt  3930 words = 15,720 bytes
    ours            3962 words = 15,848 bytes
    IMEM                          16,384 bytes

**536 bytes spare, 3.3%.** A newer GCC producing slightly larger code overflows.
`EFFORT ?= -O2` in the Makefile is overridable, so `-Os` is the fallback. Toolchain
being installed is xPack `riscv-none-elf-gcc` 15.2.0, far newer than krikzz's, so
a byte-identical rebuild is unlikely - which means the disassembly-diff route to
recovering MisterPezz82's changes probably will not work, and the two documented
changes have to be re-applied by hand instead.

### Diagnostic bug to fix when the logger is next built

`paprium_cmd_log` resets `armed`/`frozen`/`wr_idx` on `reset` but not the RAM, so
exiting the core zeroes the header while leaving the data. This capture was
salvaged by reading in address order and ignoring the header. Capture state should
survive resets - it is a diagnostic.


---

## The firmware builds. Toolchain working.

xPack `riscv-none-elf-gcc` 15.2.0 in `tools/`, driven by `scripts/build_mcu.sh` -
a shell replica of krikzz's Makefile, because Git Bash has no `make`. Same flags,
same linker script, same `bin_to_verilog.exe`. Output goes to `build_output/mcu/`
so krikzz's tree is never touched: his `mcu.txt` is our only clean baseline.

Two things needed fixing to build at all:

- **`-march=rv32im` is no longer enough.** GCC 15 split CSR and FENCE.I out of the
  base ISA, so it must be `rv32im_zicsr_zifencei`. Same instructions; the CPU has
  always had them. krikzz's Makefile says plain `rv32im` because his GCC folded
  them in.
- Paths needed quoting throughout - the project directory has a space in it.

### Sizes, and why -O2 does not fit

| build | bytes | spare of 16,384 |
|---|---|---|
| krikzz's published `mcu.txt` | 15,720 | 664 |
| ours (MisterPezz82's) | 15,848 | 536 |
| **rebuilt, `-O2`** | **16,344** | **40** |
| **rebuilt, `-Os`** | **15,504** | **880** |

GCC 15 at `-O2` is **624 bytes larger** than krikzz's compiler produced, leaving 40
bytes - the two-line `sfx_loop` fix would overflow it. `-Os` comes in smaller than
krikzz's own build with 880 bytes spare.

**Byte-identical reproduction is off the table**, as expected. So the
disassembly-diff route to recovering MisterPezz82's undocumented changes is dead,
and their two documented ones have to be re-applied by hand.

### -Os is a risk, and growing the IMEM is the better answer

`-Os` is not free: the MCU services the 68000 in real time, and upstream already
attributes the elevator corruption to **MCU SDRAM starvation**. Making its code
slower to save space is exactly the wrong trade on a part already suspected of
missing deadlines.

The IMEM limit is **ours, not the toolchain's**. `neorv32.ld` already allows 256 KB;
the ceiling is `rtl/PAPRIUM/mcu_core.sv`:

    module mcu_irom(input [13:0]addr, ...);
    reg[31:0]rom[16384/4];
    di <= rom[addr[13:2]];

Growing to 32 KB is a three-line change costing about **13 more M10K** against 62
free in the shipping build. That buys `-O2` back plus room for the fix, Pezz's two
changes, and anything later.

**Plan: grow the IMEM, build at -O2.** Use `-Os` only as a fallback if the memory
does not fit.


---

## FIXED: punk-TV cue, in firmware, verified on hardware

**Both punk TVs play** - level 1 and level 2. The level-2 one has never worked in
this port.

The log shows the mechanism exactly:

    256  vol=000  EMPTY  pcm=29920    sample ended, as it always did
    276  vol=019  EMPTY  pcm=29920    the ramp arrives
    278  vol=019  fed    pcm=29921    RE-ARMED - PCM resumes
    334  vol=0C0  fed    pcm=42772    still streaming as volume peaks
    654  vol=000  fed    pcm=62532    2.1 plays of a 29,920-word sample

Before the fix that count froze at 29,920 forever and the volume ramp climbed onto
a dead channel. Two lines in `sfx_loop`, in krikzz's `mega-ppm` source.

This is the first bug fixed by **changing the firmware** rather than working around
it. Two days ago that was filed as impossible - needing chips nobody has dumped.
It needed a compiler, a 40-line build script, and reading `sfx.c`.

### The three predicted regressions, all confirmed

Reported on hardware, and all expected because this firmware is krikzz's source
plus our fix, without MisterPezz82's changes:

| Symptom | Cause |
|---|---|
| Block 888 door renders wrong | their door fix absent (`attr &= ~0x2000`, object 107 sprite 4) |
| No end-of-stage music | their `cmd_8C` one-shot change absent |
| Subway (untested this run) | stock `0x81` LZ decoder is MAME's broken heuristic |

Nothing unexpected broke, which is the other thing this test established: our
rebuild does not diverge from theirs in undocumented ways.

### Still open, and separate

The **boss / large-enemy death sound** is unchanged, and the mailbox capture
already showed why: `0x1C` is never requested across a window spanning boot to the
first TV. The game asks for a different sample, so it is not a playback fault and
not related to the loop bug.

### Next: three ports back onto our firmware

1. **`0x81` LZO decoder** - GPGX's `paprium_decoder_lzo` (`paprium.h:827-1010`,
   183 lines) replacing mame.c's `case 0x81` heuristic, the one with an
   `// unconfirmed end code` comment on its loop terminator. Verify against the
   subway.
2. **Door fix** - one line, `attr &= ~0x2000` on object 107 sprite 4. Verify
   against Block 888.
3. **`cmd_8C` one-shot music cues** - bit-7-clear cues routed to `mdp_play_once`
   instead of stopping. Verify against stage clear.

Room exists: IMEM is 32 KB and the firmware is 16,368 bytes.

### Warning: block RAM is now completely full

    ALMs        18,149 / 18,480  (98%)
    RAM blocks     308 / 308     (100%)

In the DIAGNOSTIC configuration - shipping has no 16 KB command log and no second
data_unloader. Nothing further can be added to a cmdlog build without taking
something out.


---

## "Saxophone guy": we have never tested the conditions

He only appears in **Original mode, at Hard difficulty or above**.

Every hardware run in this project has been **Arcade / Easy** - chosen early
because it is the fastest route to the punk TVs and the big enemy, and then kept
for comparability across runs. So the conditions for him to spawn have never once
been met, and "never appears" is not evidence of anything.

That retires the standing theory that it was upstream issues A/B (the MCU falling
behind and missing events). It might still be, but nothing observed so far
supports it.

**To test:** Original mode, Hard or above, and play to wherever he appears. Worth
folding into the next run that is not a controlled A/B, since changing mode and
difficulty invalidates comparison with the Arcade/Easy captures.

Worth noting the same trap may apply elsewhere: the mode/difficulty axis was only
discovered at all because the punk-TV cue behaved differently across it. Any
"never happens" observation from this project should be checked against whether
the conditions were ever actually present.


---

## Reference: wafflenet.com/paprium.html

A community walkthrough with trigger conditions for secrets. Two things in it
change how we test.

### The Boom Box is a sound test, and we should be using it

> The Boom Box is in the Options menu, labelled '?'.
> Unlock: complete Original Mode with more than 160000 points, **or press
> Up-Up-Down-Down-Left-Right-Left-Right-B-B on the main menu** (a sound effect
> will play to confirm code entry).

**A cheat code gives us a sound test.** Every audio capture in this project has
cost a full arcade-style playthrough, because the game has no saves and the cues
we needed were minutes apart. A sound test reaches music directly.

Also in there:

> press X to change the music to the "crisis state" out-of-tune version, and Z to
> add the Sexy Sax Man solos to the songs where he appears. These can also be
> combined! ... once enabled you cannot press the buttons a second time to remove
> the effect - the song must be restarted.

So the sax solos are a **music-layer variant**, not only a character that spawns
in-game - reachable from the Boom Box without playing at Very Hard at all.

Note the caveat for our purposes: the Boom Box plays MUSIC, and this port
substitutes the OST for music, so it exercises the CDDA path rather than the
cartridge's own synth. Useful for track selection, mapping and one-shot behaviour;
it does **not** test the SFX bank, which is where the punk-TV and boss-death cues
live.

> Nobody has yet unlocked more than 52/63 music tracks in the Boom Box.

52 is exactly the number of live entries in the cartridge's music pointer table,
against 62 slots - matching the ten null pointers found in the ROM. Independent
confirmation of that finding from an entirely different direction.

### Sax man: Very Hard, not Hard, and stage-specific

> Appears on Very Hard difficulty and higher:
> INTERCOM (Mid-Levels path only), BION MART, CENTRAL PARK, ICE FACTORY,
> GREEN CROSS, BLUE BAR (during Romulus & Remus boss fight), SKY SPA

**INTERCOM is the elevator stage** - the one with the corruption bug. So a Very
Hard run through INTERCOM's mid-levels path tests the sax man and the elevator at
once.

### Block 888 is the opening stage

Confirms the door fix is reachable in seconds, which makes it a cheap regression
check rather than something to play toward.

> After leaving the first room, if you go left and push against the edge of the
> screen you can skip the whole level and go straight to the boss area - only
> works in Original Mode, and only after your first playthrough on a given save
> file.


---

# RESUME HERE (2026-08-29)

Everything is committed and pushed to
<https://github.com/thekoalakoa/paprium-pocket>. Working tree clean.

## State

The **shipping build is on the SD card and verified** in Arcade and Original modes:
`pkg/pocket/Cores/Koala_Koa.Paprium/paprium.rbf_r`, md5 `8124362d`, 16,900 ALMs
(91%), worst slack **-2.539**, TNS **-1201** - the best timing this project has
produced.

Six fixes shipped, none of which exist in any other Paprium build on this
hardware: punk-TV cues and area ambience, the `0x81` LZO decoder, the Block 888
door, one-shot music cues, echo and amplify, and the pan phase inversion.

Firmware is rebuilt from krikzz's source and reproducible via
`patches/mega-ppm-pocket.patch`. Toolchain in `tools/`, driven by
`scripts/build_mcu.sh`.

## The one open item with a clear next step

**Big enemies play a normal enemy's death sound.** The game requests correctly, so
the loss is downstream of the mailbox. `0x1C` is never requested in any capture.

Do **not** try to infer which sound is the death cue from a full log - that was
attempted three times and was wrong three times (`0x1C`, then `0x3D`, then the
`0x0D/0x13/0x3A/0x20` cluster, which the user identified as a regular enemy dying
to a weapon).

**Take a minimal capture instead:**

1. Install the diagnostic: `./scripts/make_cmdlog_pkg.sh`, copy
   `build_output/cmdlog-pkg/Cores/Koala_Koa.Paprium/*` to the card, and re-zero
   `D:\Saves\paprium\common\Paprium.log` with 16,384 zero bytes.
2. Launch, go straight to the big enemy (the fourth), **kill it, exit immediately**.
3. The last entries in the log are unambiguously that death. No correlation
   guesswork.

Then extend `paprium_cmd_log` to snapshot **all eight channels** rather than just
channel 7, to see whether the cue is allocated and then evicted.

## Other open items

- Elevator corruption (INTERCOM) and the rooftop boss sprite priority - both
  characterised using soft resets, which carry stale SDRAM. Retest under a clean
  core exit before trusting the upstream attribution.
- Sax man: **Very Hard or above**, and INTERCOM is on his list, so one Very Hard
  run tests him and the elevator together.
- Intro single-pixel flicker - cosmetic.
- IMA ADPCM for the music blob (2.25 GB -> ~562 MB, 4x less bridge traffic).
  Batch with a firmware validation pass.
- `paprium_cmd_log` resets `armed`/`frozen`/`wr_idx` but not its RAM, so exiting
  the core zeroes the header. Captures are salvageable by reading in address order.
- `build_output/paprium_SHIPPING.rbf_r` is misnamed - it is the old 2026-08-26
  build, not what ships.

## Habits that earned their keep

- **Verify the card, not the report.** A stale copy of the package once reverted a
  card silently and cost a playthrough.
- **Check the fit-summary timestamp and `.rbf` size before flashing.** Quartus
  failed silently more than once; a compound shell command reported the trailing
  `grep`'s exit status as success.
- **Quit and relaunch the core between tests.** Reset Core does not clear SDRAM.
- **Measure before theorising.** Four confident diagnoses of the punk-TV cue were
  wrong; the log settled it in one capture.


---

# The music instrument bank is in the ROM, and it is WavPack

**2026-08-29.** This overturns the premise the whole project has run on.

Every version of this document, the README and the install guide has said Paprium's
music "is generated by hardware that has never been dumped, so it cannot be
reproduced". **That is wrong.** The instrument samples are in the cartridge ROM,
in an open format, and `ffmpeg` decodes them.

## Where

The same pointer table that gives the SFX bank gives the wave bank, four bytes
earlier (`paprium.h:2837`):

    base = be32(rom + be32(rom + 0xAF77C) + 0x774)

    wave   +0x774 -> 0x1A0010
    sfx    +0x778 -> 0x25ECA4
    sprite +0x77C -> 0x2E5BD0

## What

`0x1A0010` begins `77 76 70 6B` - **"wvpk"**, the WavPack magic. The header parses
cleanly:

    version       0x0407
    total_samples 1,379,262
    block_samples 44,100        one second per block
    32 blocks, ending at exactly 0x25ECA4 - the sfx pointer, no slop

Extracting those 32 blocks (781,460 bytes) and decoding gives **1,379,262 samples**,
matching the header exactly. The low byte of every 16-bit sample is **zero**: the
data is 8-bit unsigned in 16-bit containers, which is precisely how GPGX's synth
reads it - `(sample * 65536 / 256) - 32768`. 1.38 MB, matching its
`wave_ram[0x180000]` allocation.

`scripts/dump_wave.py` does the extraction. Decode with ffmpeg; the result is
derived from the user's own ROM and stays local, like the SFX dump.

## It is a sampler, not a tone generator

Confirmed from GPGX's dead synth code and from listening:

    const int _rates[] = {2,4,5,8,9,10};   /* 24000, 12000, 9600, 6000, 5333, 4800 */
    int rate = _rates[voice->type] << 16;  /* 16.16 */
    voice->tick += 0x10000;                /* phase accumulator */

One recorded instrument covers a range of notes by varying playback rate, 26 voices
at once - the same principle as the SNES SPC700 or a tracker. Nothing at 44.1 kHz;
that is only the container rate. Played at 12 kHz the bank runs 115 seconds, at
6 kHz 230 - which is why it sounds like recognisable fragments laid end to end
rather than music.

## What is still unknown

Being precise, because the temptation is to over-read this.

- **The program table has not been found.** GPGX reads 16-byte records from
  `wave_ram + program*16`, but the decoded bank starts with audio, not records.
  The four pointers immediately before the wave entry (`0x19F5C4`, `0x19F868`,
  `0x19FBA8`, `0x19FE34`) were checked and none parses as a table - the last looks
  like compressed data.
- **GPGX's synth is unvalidated.** It sits behind an unconditional `return` and has
  never executed, so its table layout is an assumption nobody has tested. Do not
  treat it as documentation.
- **The MWMM sequence format** is partially reverse-engineered. Modules carry
  `81 0E 57 4D 4D 4D`, and that leading `0x81` means they are LZO-compressed -
  which this port can now decode.
- **Where a 26-voice renderer would live.** Not the MCU, which already services the
  68000 in real time. It would be RTL, a larger `audio_sfx`, with the bank in SDRAM.

## Honest status

Solved: the samples exist, are reachable, and decode. That removes the blocker
everyone assumed was permanent.

Not solved: the program table, the sequence format, and the renderer. This is a
real reverse-engineering project, not a weekend - but it is no longer gated on
hardware nobody has dumped.


## All 52 music modules decompress

`scripts/dump_music.py` extracts and decompresses every one. The pointer table base
is read from ROM `0x10054`; entry 0 is the track count (62) and entries 1..62 are
offsets **relative to that base** - not absolute, which is what made track 1 appear
to point at the ROM header on the first attempt.

Each module begins `81 0E 57 4D 4D 4D 00 01`. The `0x81` is the decoder type byte,
so the LZO stream starts one byte later and its first instruction emits the literal
`WMMM` header. **All 52 decompress cleanly**, 2,712 to 12,984 bytes - which
independently validates the LZO decoder ported into the firmware, beyond the subway
test on hardware.

Byte order is **plain file bytes, no `^1`** - the same as the `0x80` blocks and the
opposite of the SFX table. Established empirically, not assumed.

### Header, as far as it is understood

    +0x00  "WMMM"
    +0x04  00 01           version - constant across all 52
    +0x06  BE xx           BE constant; second byte varies (03/04/05)
    +0x08  xx xx           varies per track
    +0x0A  xx 10 04 00 00 00
    +0x10  26 bytes        per-voice array, 0x10 in EVERY module
    +0x34  sequence data begins

**26 is the voice count** in GPGX's synth loop, so that array is per-voice - most
likely an initial volume, given every module ships the same value.

### Why this matters

The remaining unknown for music synthesis was the sequence format and the program
table. We now hold all 52 sequences in decompressed form, which is the corpus
needed to work out both: the program numbers a track references have to appear in
this data, and comparing 52 modules gives far more signal than staring at one.

## TO DO: the boot-time console check

**Not investigated.** The game runs a check sequence at boot - separate from the
mini-game - that identifies what it is running on: console model, attached hardware
(Sega CD, 32X), and the state of the cartridge's own MAX 10 / STM32. It is
understood to be anti-piracy, and it is believed to **enable or disable features**
depending on what it finds.

Why this is worth chasing rather than filing away:

- It could explain the **big-enemy death sound**, the one open audio bug. The game
  requests correctly and the sound is lost downstream - but if the game believes it
  is on unexpected hardware it may take a different branch entirely.
- It fits things already observed. `0x88 audio_setting` writes console
  configuration bits to `ram[0x1800]`/`[0x1801]` (DAC select, NTSC) and **our
  firmware ignores that command entirely**. The Boom Box is documented as showing
  icons that vary "based on what console you are using, how many controllers are
  attached, and whether or not you have a MegaWire connected" - so the game
  certainly does detect its environment and surface it.
- It may explain mode- and difficulty-linked oddities that looked like separate
  bugs.

Where to start: log the boot command sequence with `paprium_cmdlog` (it already
captures `0x88` and `0xB0`), and read GPGX's handling of the `0xC6 paprium_boot`
command and the `ram[0x1800]` region.


## TO DO: fake an expansion, and see what the game gates on hardware

Deferred deliberately, to be run after the `0x88` result is in.

**Faking a Sega CD is one line.** `rtl/upstream/nuked-md/md_board.v`:

    assign DISK = 1'h1;   // expansion detect: high = nothing attached

`DISK` feeds `ym6046`, the I/O chip owning the version register at `0xA10001`,
whose bit 5 is the expansion detect. Setting it to `1'h0` reports an expansion.

**Expect it to break rather than unlock.** A real Sega CD also provides hardware at
`0x400000-0x7FFFFF` - program RAM, sub-CPU communication registers, CD audio. Claim
one is present and the game may talk to something that is not there; a hang or a
wait loop at boot is the likelier outcome than new content. There is also no
evidence Paprium gains anything: GPGX's Paprium code contains no Mega CD or 32X
references at all, and the Boom Box is documented as merely *displaying* console
icons for what is attached. It would not help audio either - Paprium's enhanced
sound is its own cartridge hardware, not a CD.

Cheap enough to settle empirically though: one line, one build, and the failure mode
shows within seconds of boot.

**The broader question is the interesting one:** what does the game actually gate on
detected hardware? The `0x88` fix is the first probe - it stores the DAC and NTSC
selection where the game reads it back, so the in-game **VM DAC** checkbox becomes
the observable. If toggling it now audibly changes which chip plays the effects, the
game does act on configuration state, and hardware-gated behaviour becomes worth
mapping properly. If it stays inert, the detection is likely cosmetic and this whole
line of enquiry can be closed.

Other things to try once that is known:

- Region reported as Japan vs Export against **Original mode at Very Hard**, where
  the sax man and the JP-exclusive features live.
- Whether `0xB0 paprium_sprite_init`, the other muted command, gates anything -
  MisterPezz82 suspected it in the elevator corruption and never followed up.


## Eight commands are muted, not two

The firmware stubs more than the two upstream mentioned. From
`repos/mega-ppm/mcu/paprium.c`, with krikzz's own comments:

| cmd | comment | GPGX |
|---|---|---|
| `0x83` | unk startup thing | logged no-op |
| `0x95` | (bgm related) | logged no-op |
| `0x96` | (bgm related) | logged no-op |
| `0xA4` | **megawire settings** | logged no-op |
| `0xB0` | *(none)* | `paprium_sprite_init` - **implemented** |
| `0xB6` | likely restores boot code to allow HW reset | logged no-op |
| `0xD0` | *(none)* | logged no-op |
| `0xD6` | ??? | `paprium_music_special` - **implemented** |
| `0x88` | set audio config | `paprium_audio_setting` - **now implemented here too** |

Most are no-ops in GPGX as well, so muting them costs nothing. **Three are not:**
`0x88` (fixed), `0xB0` and `0xD6`.

`0xD6` matters most on current evidence: it fires **hundreds of times** in a single
playthrough capture, interleaved with the audio traffic, and we discard every one.
GPGX implements it as `paprium_music_special`. `0xB0` is `paprium_sprite_init`, and
MisterPezz82 suspected it in the elevator corruption without following up.

## Observed: enemy names do not vary

**Reported on hardware comparison:** in this port every enemy of a given type shares
one name; on original hardware each enemy has its own.

That is a behavioural difference, a different class from the audio bugs, and it is
what a lookup returning a constant looks like. No mechanism identified yet - and
guessing at one is the mistake this project keeps making - but the muted command
list above is a far better suspect set than nothing.

**Diagnostic:** the command logger currently filters to audio commands, deliberately,
so a capture survives a playthrough. A short capture with the filter OFF, taken while
a few enemies spawn, would show what actually fires at a spawn. That is a small
change to `paprium_cmd_log.sv`'s `keep` expression.


## 0x88 confirmed on hardware: the game DOES act on configuration

Tested with the shipping build carrying the `0x88` fix (md5 `bb0cb54c`).

**The VM DAC checkbox now does something.** Before the fix it was inert - the game
wrote its audio configuration and read back stale memory. Now toggling it produces
an audible change. That settles the question behind the whole boot-check theory:
**the game reads its hardware/audio configuration back and branches on it.**

Two consequences.

### The YM2612 DAC path is broken - newly reachable, not newly broken

Checking the box produces **static, with music still audible underneath**. The
option selects the YM2612's DAC over the cartridge's own, and that path evidently
does not work in this port. It has presumably never worked; the toggle simply could
not reach it before.

**Not a shipping concern.** The default is unchecked (DT128VALT, the cartridge DAC)
and is unaffected. The box now does what it says on the tin and exposes a real
downstream fault, which is an improvement over silently doing nothing.

Worth investigating separately: whether the game routes PCM to YM2612 register 0x2A
and our timing for those writes is wrong, or whether the cartridge SFX engine keeps
running with stale data alongside it - "music still audible underneath" suggests
both paths may be live at once.

### 0x88 is NOT the big-enemy death sound

The sound is unchanged. That theory is closed. The remaining candidates are the two
other commands GPGX implements and we mute - `0xB0 paprium_sprite_init` and
`0xD6 paprium_music_special` - and whatever drives the grunt-name variation, which
fails in the same "varying path does not vary" way.

### Everything else confirmed

All five firmware fixes and three RTL audio fixes verified on hardware: both punk
TVs, the subway, the Block 888 door, stage-clear music, echo, amplify and the pan
de-inversion.


## TO DO: the full-health stage clear, bundled with the YM2612 work

Reported from hardware: clearing stage 1 at 100% health plays the ordinary
stage-clear cue instead of the perfect-health one. The tester's ear says the
perfect version sounds like **an additional layer over the standard finish**, not
a different piece.

That matches the shape of a PCM cue plus an **FM fanfare driven by the 68000
through the console's own YM2612** - which would be entirely independent of the
unsolved MWMM payload, and therefore fixable.

Supporting circumstantial evidence:

- The released soundtrack has exactly one Stage Clear track (cue index 52), so a
  variant was never a separate recording.
- The cartridge's own music pointer table is **null at ten indices** (8, 9, 10, 13,
  26, 31, 41, 44, 45, 48). If the perfect clear requests one of those, the cart has
  no PCM to stream and the jingle must come from elsewhere.
- The YM2612 DAC path is independently known to be broken here (below), so we
  already have reason to believe FM content can go missing.

### The zero-cost test, which needs no build

With `paprium.pcm` renamed away this core has no music path at all, so anything
still audible is the 68000 driving the YM2612 directly. That isolates the layer:

    1. rename /Assets/paprium/common/paprium.pcm -> paprium.pcm.off
    2. EXIT the core (not Reset Core), relaunch
    3. clear stage 1 at ordinary health - listen
    4. clear stage 1 at full health - listen

    fanfare audible at full health only -> the FM layer exists and we drop it
    nothing either time                 -> no FM layer; it is a synth render
    same sound both times               -> the variation is not in the FM part

Rename, do not delete - the blob is 2.25 GB to rebuild.

### The instrumented version, if the ear test is ambiguous

Sticky counters for YM2612 activity - total register writes, key-ons (reg 0x28),
DAC writes (reg 0x2A) - using the same reset-immune scheme as the VRAM budget
counters, plus the existing 0x8C/0x8D/0xD6 music logging so the requested track
index is visible. One capture: clear stage 1 at full health, exit.

    different index  -> we map it wrong, or to Blank; fixable
    null index + FM key-ons -> the YM2612 IS the variant; fixable
    standard index, no FM   -> a synth render of the same module; out of reach

### Note on scope

If the layer turns out not to exist, the correct outcome is to leave the standard
cue playing. Writing a perfect-health fanfare of our own would mean shipping music
the game never contained - fabrication in a preservation project, and worse than an
honest wrong cue.

## TO DO: the YM2612 DAC path produces static

Exposed by the `0x88` fix - the in-game **VM DAC** option selects the YM2612's DAC
over the cartridge's own, and choosing it gives **static with music still audible
underneath**.

Not a regression and not a shipping concern: the default is the cartridge DAC and is
unaffected. The path has presumably never worked in this port; the toggle simply
could not reach it before, because the game read its configuration back from memory
we never wrote.

Starting points:

- "Music still audible underneath" suggests **both paths may be live at once** -
  the cartridge SFX engine still running while the game also feeds the YM2612.
- The game would write PCM to YM2612 register `0x2A` at some rate. Check whether
  those writes arrive and whether our timing for them is right.
- Compare against GPGX with the same option set, which is cheap and needs no build.


## LOG_ALL capture: what the full command stream shows

First capture with the audio filter off - boot through the first room, ring filled
once (2047 entries) and stopped.

    AD sprite          1392
    AF sprite_stop      263
    AE sprite_start     263
    D1 SFX_PLAY          22
    F5 unpack_scal       21
    B1 sprite_pause      14
    D2 sfx_off           11
    DA decoder            8
    88 audio_setting      8
    B6                    6   muted
    DB decoder_copy       5
    C9 music_volume       5
    EC                    4
    DF sram_read          4
    A4 megawire           3   muted
    CA sfx_volume         3
    83                    2   muted
    8D music_setting      2
    F4 unpack             2
    8C music              2
    96                    2   muted
    95                    2   muted
    B0 sprite_init        1   muted

### Two things worth knowing

**`0xD6` does not appear at all.** It fired hundreds of times in the audio-filtered
captures, so it starts later in gameplay rather than at boot. Chasing it needs a
capture taken mid-level, not from boot.

**`0xB0 sprite_init` fires once, at init, and we muted it.** GPGX implements it as a
single clear:

    memset(paprium_s.ram + 0x1F20, 0, 14*8);

112 bytes of the DMA/sprite table. Without it, stale entries survive initialisation.
Now implemented here. MisterPezz82 suspected this command in the elevator corruption
and never followed it up, so it is worth retesting the elevator against this build.

### The grunt-name question is NOT answered

Stated plainly because the temptation is to force a conclusion. The capture shows
sprites being rendered but not *what* they render - names are almost certainly drawn
from object data in cart RAM, which the command stream does not carry.

Finding the mechanism needs a different diagnostic: snapshot the object table
(`obj_data[64]` in the ramdp struct) around a spawn and compare entries between two
grunts of the same type. That is a different capture shape from a command ring.


## Why the commands were muted at all

`cmd_unknown()` prints `"unknown cmd: %x"` over UART; `cmd_unknown_muted()` is the
same function with that call commented out. **"Muted" means "known to occur, not
implemented, stop spamming the debug log"** - a to-do list, not a design decision.
That is why implementing them has been productive: they were never deliberately
disabled.

## 0xD6 is a feature waiting on the synth, not a bug

GPGX's `paprium_music_special` is also effectively a no-op, but its comment gives
the command away:

    else if( flag == 2 ) {
        //*(uint16 *)(ram + 0x1E10)  /* 4 = crisis, 0 = normal ? */

**`0xD6` switches the music between normal and "crisis" state** - the out-of-tune
variant the wafflenet guide describes, toggled with X in the Boom Box. That is why
it fires hundreds of times during gameplay: it tracks the player's state.

Neither GPGX nor this port can act on it, for the same reason: **both substitute
pre-rendered audio, and an OST rip cannot be made to go out of tune.** Implementing
the command would only store a flag nothing could use.

It is worth recording because it argues for the synth. The game is actively
requesting musical behaviour that no substitution can provide, several times a
second, throughout play.

### Scope of a synth, for when it is considered

Have: the instrument bank (WavPack, decoded) and all 52 sequence modules
(LZO, decompressed).

Missing:

1. **The program table.** Not found. GPGX reads 16-byte records from
   `wave_ram + program*16`, but that code has never executed and the decoded bank
   starts with audio, so its layout is an untested assumption.
2. **The MWMM sequence encoding.** Header partly understood; the body is not.
3. **A 26-voice renderer.** Would be RTL - a larger `audio_sfx` - with the bank in
   SDRAM. Not the MCU, which already services the 68000 in real time.

That is a project on its own branch, not something to ride along with a `memset`.


# Synth work: the MWMM module format is opening up

## Layout established

From variance analysis across all 52 modules - bytes constant across every module
are structure, bytes that vary are data.

    +0x00  "WMMM"
    +0x04  00 01 BE   constant
    +0x07  ..0x0C     per-track parameters (tempo? length?)
    +0x10  26 bytes   per-voice array A - volume, 0x10 everywhere
    +0x2A  26 bytes   per-voice array B - varies per track
    +0x44  26 bytes   per-voice array C - zero everywhere
    +0x5E  26 bytes   per-voice array D - pan, 0x80 (centre) everywhere
    +0x78  32 bytes   TITLE,    XOR 0xA5
    +0x98  32 bytes   COMPOSER, XOR 0xA5
    +0xB8  sequence data

26 is the voice count in GPGX's synth loop, which is what identifies the arrays.

## TEXT IS XOR 0xA5

`0x85 ^ 0xA5 = 0x20` (space), `0xA5 ^ 0xA5 = 0x00` (padding). Every module decodes
cleanly, so this is not a coincidence.

**This applies to game text generally, not just modules** - and it explains why an
ASCII search for the enemy-name table found nothing earlier. A repeat of that search
under XOR 0xA5 finds mostly these same titles (surviving as LZO literals in the
module region), so the name table is presumably inside a compressed asset. The
encoding is no longer the obstacle.

Two incidental findings: **tracks 3 and 51 are placeholders** shipped in the retail
ROM - `"I am a new music module !"` - and **tracks 34 and 35 are both titled
"Hardcore Boss Part 3"**, a typo in WaterMelon's own data where 34 should be Part 2.

## A third text field, and the real start of the sequence data

`0xB8` is **not** sequence data. It is a third 32-byte XOR-`0xA5` field: a
**comment**, present in all 52 modules and drawn from a fixed set of about a dozen
joke strings the authoring tool offered - `"Make music not war !"`,
`"It hurts to be SNES"`, `"I am king of the YM chip !"`,
`"Even GEMS sounds better than thi[s]"`. Track 1's is truncated mid-word at exactly
32 bytes (`"Good... Bad... I got the MIDI ke"`), which is what fixes the field width.

So the header is three 32-byte text fields, and sequence data starts at **0xD8**.

## Structure, measured from 0xD8

    +0xD8   order list   u16 big-endian, ABSOLUTE file offsets
    ...     ends exactly where its own lowest entry points
    min(w)  pattern data, contiguous to end of file

**The order list is self-delimiting**: `0xD8 + 2n == min(entries)`. Solving for n
resolves all **52/52** modules with every entry in range - no heuristics, no
thresholds. Lengths run 26 to 468 entries.

**Patterns partition the remainder contiguously.** Sizes are always a multiple of 8
(136 to 352 bytes in track 1), so a pattern is a whole number of **8-byte rows**.
That is the 8-byte stride showing up, and it lives *inside* patterns rather than
across the file.

**An all-zero pattern exists and is heavily reused** - in track 1 it is `0x14C0`,
136 bytes of zeros, referenced 93 of 312 times. That is the rest/empty pattern, and
it is what makes the body 67.7% zeros. Others are sparse sustains: `0x07C0` is 144
bytes with one event at the top and one at the bottom, reused 16 times.

## Corrections to the previous entry

Both earlier "ruled out" claims were **wrong**, and both for the same reason - they
were measured over the header rather than the data.

- **"Not offset-indexed"** - false. The order list is exactly the pointer table that
  search was looking for. It was missed because the search covered the first 512
  bytes *of the file*, which is header and text, and because the entries are
  absolute file offsets rather than relative to the body.
- **"Not a fixed-stride row format"** - false. The stride is 8, and every one of the
  52 modules agrees once measured from 0xD8.

The sparsity figure survives unchanged: 67.7% zeros from 0xD8, against 67% measured
from 0x78. It was right by luck, not by method.

## Open: the column count

Order-list lengths are divisible by **13 and 26 in all 52 modules** (by 8 in only
16), so the grid is positions x 13 or positions x 26. The header's 26-byte arrays
fit either reading - 26 u8, or 13 u16.

Not yet resolved, and two obvious tests failed to separate them:

- No column is constant under either width, because the exporter emitted patterns in
  first-use order, which makes the table ascend regardless of how it is folded.
- Patterns are **shared across columns** under both widths (mean 2.65 columns per
  pattern at 13, 2.76 at 26), so patterns are voice-agnostic phrases rather than
  belonging to a voice. That kills the separation test but is itself a useful fact.

## The 8-byte row

    row    8 bytes = 2 events of 4
    event  note, octave, effect, param

**Rows are real**: 2509 of 2525 patterns across all 52 modules are an exact
multiple of 8 bytes. Patterns end `00 00` (98%) and begin with `01` (72%).

**note/octave is well evidenced.** From 1172 near-duplicate pattern pairs - the
same phrase appearing twice with small variations - the byte deltas are musical:
+-1 and +-2 dominate, then +5 and -7, which are the same interval an octave
apart. Plain +-12 never occurs. The joint test explains why:

    note +5  with octave -1  (75%)   net -7
    note -7  with octave  0  (75%)   net -7      same interval
    note -8  with octave +1  (76%)   net +4
    note +4  with octave  0  (82%)   net +4      same interval
    note -5  with octave +1  (65%)   net +7
    note +7  with octave  0  (54%)   net +7      same interval

Every wrap resolves to the same net semitone interval, which is what an octave
field does and hard to produce any other way. 84.7% of note bytes are 1..12, and
the adjacent byte concentrates on 1..9.

**Evidence against, recorded honestly:** the note-byte histogram decays
monotonically (1:12%, 2:16%, 3:12% ... 12:3%) rather than showing seven hot
values. Real music in a key does not look like that. Either the note slots are
not yet cleanly separated from command slots, or the field is not a semitone.

A pitch-class test was run and then discarded as worthless: `(oct*12+note-1) mod
12` reduces to `note-1`, so it only re-showed the note histogram.

## Hypotheses tested and refuted

- **Indices assigned in first-use order** (as the order list does). Only 3-5% of
  patterns satisfy it under any framing - no better than chance.
- **A fixed 128-byte pattern prologue.** Suggested by track 1, where every
  pattern changes character at row 16. False across the corpus: the smallest
  pattern is 56 bytes.
- **Voice separation by column.** Patterns are *shared* across columns under both
  13 and 26 (mean 2.65 / 2.76 columns per pattern), so patterns are
  voice-agnostic phrases. This also means the 13-vs-26 question is still open.

## Timing is not yet understood

Patterns sharing an order-list row have different lengths (track 1 position 0
mixes 304, 176, 192 and 296-byte patterns), so a row of the order list cannot be
a set of simultaneous voices of equal duration. Either the order list is not
positions x voices, or rows carry a duration this model has not identified.

## Game state modulates playback

Reported from hardware: tones and music change as player health drops, and the
sax man's theme changes as he is hit. So the synth takes **live modulation from
game state** - it is not module playback alone. That is almost certainly what
`0x8D music_setting` and `0xD6 music_special` carry, and it means any renderer
needs a transpose/parameter input rather than being a pure function of the
module. Worth capturing 0x8D/0xD6 during a boss fight.

## Validated against the released recordings - and the pitch model FAILED

`cdda/trackNN.pcm` and `music-modules/trackNN.mwmm` are **the same piece**: the
cue's TRACK numbers line up with the module numbers (TRACK 01 = "90's Acid Dub
Character Select" = track01.mwmm "90's Acid Dubstep"). That gives objective
ground truth, so the decode does not have to be judged by ear.

`scripts/validate_pitch.py` measures the chroma of the real audio with Goertzel
filters and correlates it against the decoded pitch classes at all 12 rotations.
Across 8 modules, as a full matrix with every other track as a control:

    own audio ranked best for 1 of 8 modules - exactly chance

Module 01 correlates **better with track 05's audio (+0.755) than with its own
(+0.568)**. So the decoded pitch classes carry no song-specific information, and
**note/octave as ABSOLUTE pitch is refuted.**

## What survives

The interval evidence is not thereby wrong - it is evidence about *deltas*, and
deltas stay musical if the values are pitch relative to some per-pattern base.
That was tested without needing to know the base: fit each pattern's own notes to
their best 7-note scale, against a null with the same counts drawn from the
global value distribution.

    real 80.1%   null 72.2%   gap +7.9 points

Real tonal music sits 15-25 points above such a null. So there **is** tonal
structure, at roughly half the strength it should have. The natural reading is
that the note slots are real but **diluted by command slots being counted as
notes** - which also explains the note histogram's monotonic decay, since small
command opcodes and small note values are being pooled.

## Status, honestly

| Claim | Standing |
|---|---|
| Order list, u16 absolute offsets, self-delimiting | Solid - 52/52 |
| Patterns contiguous, rows of 8 bytes | Solid - 2509/2525 |
| Row = 2 events of 4 bytes | Good - lane statistics are symmetric |
| A note and an octave field exist | Good - interval and wrap evidence |
| Those fields give absolute pitch | **Refuted** - chance against real audio |
| Which slots are notes vs commands | **Unknown - this is the blocker** |
| Timing / tempo | Unknown |
| 13 or 26 voices | Unknown |

## Slot classification tried, and the sweep that followed

Eight classifiers were tested - dropping octave 0, restricting the octave to
1-10 / 1-8 / 2-6, primary slots only, secondary slots only, and note/octave
swapped. **None reached significance.** Best mean own-rank 6.75 against a chance
value of 8.5, with own-best stuck at 1/16 throughout.

A wider sweep then tried all 8 byte lanes under three readings each - absolute,
delta-unsigned and delta-signed, the last being what "pitch relative to an
unknown base" would actually look like. Best of all 24: mean rank 6.62,
own-best 1/16. Nothing works.

**No simple per-byte interpretation of the pattern data reproduces the song's
pitch content.**

## The harness is sound - this was checked

Before trusting a negative result, the feature was validated. Chroma of a
*different 40-second segment* of the same recording, scored against all 16
cached recordings:

    own-best 8/8, mean rank 1.00, correlations +0.937 to +0.998

and different recordings are genuinely distinct (mean pairwise +0.375, min
-0.697). So the test identifies a song from pitch content perfectly when the
pitch content is real. The decoded notes rank at chance. The instrument is not
blunt; the signal is absent.

## The one caveat on the ground truth

The comparison assumes the released album preserves the cartridge's key. The
names differ in a way that leaves room for doubt - module "90's Acid Dubstep" vs
OST "02 90's Acid Dub Character Select", module "Bladerunner FM" vs OST "43 Blade
FM". Same pieces, but plausibly a separately produced album rather than a render
of the cart data. If any track was transposed for production, chroma comparison
fails for that track - though not for all 16 at once, which is what was observed.

## What this rules in

The order list and pattern framing are unaffected - they were established by
self-consistency across 52/52 modules, not by this test. What is now doubtful is
that **the pattern bytes contain playable pitch at all**. Two readings survive:

1. Notes need stateful decoding - through the instrument definitions in header
   array B, or a per-voice table - so no fixed byte position carries pitch.
2. The patterns are automation and structure, and pitch lives elsewhere. Worth
   noting the wave bank is a **sampler** with a rate table `{2,4,5,8,9,10}`
   giving 24000/12000/9600/6000/5333/4800 Hz. If pitch is chosen by sample rate
   rather than by semitone, there may be no semitone field anywhere.

## The OST is NOT ground truth - and that reverses the refutation

Tempo was checked next, since tempo survives editing where duration does not: a
stage theme loops forever and the album track is an edit of it, so its LENGTH is
an arranging decision and says nothing about the module. (Duration was correlated
first and gave +0.47, which measured nothing - recorded so the mistake is not
repeated.)

`scripts/validate_tempo.py` measures BPM from the audio alone - energy envelope
at 43 fps, positive first difference as onset strength, autocorrelation over
60-200 BPM. The estimator was controlled first: two different segments of the
same track agree **11/12**, so the numbers are sound.

Every header byte, u16, and pattern-command parameter was then tested for
`BPM = field * 2^k` - robust to the octave errors the control exposed - against
a 40-shuffle null:

    best real field 0.496    mean null 0.501    best null 0.830

The best real candidate scores **below the mean of the null**. No tempo field
corresponds to the album's tempo.

So the album fails on key AND on tempo, has different track names, and has
lengths that are editorial. The reasonable conclusion is that **the released
soundtrack is an independent studio production, not a render of the cartridge
data** - which is what the differing names suggested all along
("Bladerunner FM" vs "43 Blade FM").

**Therefore the earlier "absolute pitch refuted" verdict does not stand.** It
rested on the album being the same performance. A re-produced album in its own
key would produce exactly the chance-level chroma result that was observed, with
a perfectly correct decode.

## Internal evidence, which needs no reference recording

With the external reference discredited, the model was tested against itself.
Real melodies move in small steps; shuffling a melody destroys that and nothing
else. Over 30,608 successive note pairs in the same slot lane:

    within +-2 semitones   real 45.0%   shuffled 27.0%   gap +18.0
    within +-4 semitones   real 58.4%   shuffled 38.1%   gap +20.2
    within +-7 semitones   real 70.4%   shuffled 53.8%   gap +16.7

That is melodic motion. Together with the octave-wrap evidence (a note delta
that wraps carries the matching octave step 65-84% of the time, every pair
resolving to the same net interval), the note/octave reading is **well supported
by internal evidence** and should be carried forward.

The weak per-pattern scale fit (+7.9 where real music gives +15-25) remains the
one internal result that is softer than expected, and is still best explained by
command slots being pooled in with note slots.

## Revised status

| Claim | Standing |
|---|---|
| Order list, u16 absolute offsets, self-delimiting | Solid - 52/52 |
| Patterns contiguous, rows of 8 bytes | Solid - 2509/2525 |
| Row = 2 events of 4 bytes | Good |
| note + octave fields, semitone pitch | **Good** - wrap evidence + melodic continuity |
| The OST can validate the decode | **No** - independent production |
| Which slots are notes vs commands | Open - eight classifiers all failed |
| Timing / tempo | Open - no field found, and no valid reference to fit against |
| 13 or 26 voices | Open |

## How to get a valid reference - the test plan

**The mini-game.** It appears only on a cold start. `Reset Core` does NOT clear
SDRAM (see "Reset Core does not clear SDRAM" above) - that is precisely why the
documented workflow is "play the mini-game, reset the core, play the real game".
To see it again the core must be **fully exited and relaunched**.

    1. rename /Assets/paprium/common/paprium.pcm -> paprium.pcm.off
       (rename, not delete - it is 2.25 GB to rebuild)
    2. EXIT the core from the Pocket menu, not Reset Core
    3. relaunch, load the ROM, listen to the mini-game

Expectations, so the result is interpretable either way. This core has **no MWMM
synth at all** - the firmware substitutes CDDA for music. So music in the
mini-game with the blob absent is the 68000 driving the YM2612 directly, i.e.
ordinary Mega Drive music, **not** the cartridge synth. That would make the
mini-game useless as an MWMM reference - and would also explain why the
square-wave renders sounded like it, both being plain chiptune. Cheap to run,
but it will probably close a door rather than open one.

**The real cartridge is the reference that matters.** Same synth, same key, same
tempo, none of the album's re-production problems. A 60-second capture of any
stage theme off real hardware is enough.

`scripts/identify_track.py` takes such a recording and ranks all 52 modules by
decoded pitch content, **blind** - the track does not have to be identified in
advance, which is what makes it a test rather than a demonstration.

    right module #1 by a clear margin  ->  note/octave decode confirmed
    right module mid-pack              ->  decode wrong, revisit the framing

This is the experiment that should decide whether to continue. Everything else
is blocked behind it.

## Properly powered search: pitch is NOT in the module data

With the album restored as a valid reference, chroma was cached for **50
labelled tracks**, so a hypothesis is scored by the mean rank of the correct
module across 50 trials rather than one 1-in-52 shot. Chance is 25.5, standard
error 2.0, so significance needs a mean rank below about 21.

Seventeen interpretations, all at chance:

    mean 22.2  top-1  0/50   a pentatonic degree      <- best, 1.6 SE, not significant
    mean 22.9  top-1  1/50   b major degree
    mean 23.4  top-1  0/50   a major degree
    mean 24.3  top-1  0/50   u16 as log-frequency
    mean 24.3  top-1  2/50   a + octave b (old model)
    mean 25.5  top-1  1/50   voice index x2 mod 12
    mean 26.1  top-1  1/50   voice index mod 12
    mean 26.7  top-1  1/50   a absolute semitone

covering both bytes, absolute and delta, major / minor / pentatonic degrees, the
16-bit slot as a log-frequency, and the hypothesis that pitch is carried by the
**voice** with patterns as pure rhythm. Top-1 counts run 0-2 of 50 where chance
is 1.

**Conclusion: the melodic pitch content is not recoverable from the pattern
bytes, nor from the voice index, by any direct mapping.** This is no longer a
weak or single-trial result - it is a 50-trial test with a validated reference
and a known chance level.

## What that implies

The container is fully understood and the payload does not contain pitch in any
form that a per-value mapping reaches. The remaining possibilities are all
indirect:

1. **Events reference something we have not found.** The small values (`01..0E`)
   behave like indices, and there is no frequency register anywhere in the
   hardware we hold to point them at (see the SFX-engine correction above). The
   referenced structure would have to live outside the module - in the ROM, or in
   the STM32 firmware that has never been dumped.
2. **Pitch is stateful in a way a histogram cannot see** - relative to a running
   value updated by commands that are themselves not yet identified. A chroma
   test cannot detect that, and nothing weaker than a full interpreter would.

Both are consistent with everything measured. Neither is testable with the files
we have.

## Honest bottom line

    container  order list, 26 voices, patterns, rows, slots     SOLVED
    text       XOR 0xA5                                          SOLVED
    reference  album validated against hardware, 50 tracks       SOLVED
    payload    event semantics, pitch                            NOT SOLVED

The tooling built here is durable and correct: `identify_track.py`,
`validate_pitch.py`, `validate_tempo.py`, and a cached 50-track reference make
any future hypothesis decisively testable in seconds against a known chance
level. That is what was missing for the whole first half of this work.

What would actually unlock the payload is **the STM32F446 firmware**, which is
the only place the synth has ever existed. `repos/paprium-dump` documents glitch
attacks against exactly that chip (`ChipWhisperer/Paprium_STM32_Glitch_CW.py`,
CVE-2020-0574 for the MAX 10). Until such a dump exists, further guessing at
event semantics is not a good use of effort - the search space is unbounded and
the tests can only ever say no.

## RETRACTION: the album IS a valid reference, and a correct refutation was explained away

Two direct captures (Nickology, from hardware) settled this.

**Intercom capture = album track04 "Asian Chill"**, on two independent measures:

    chroma +0.936      tempo 123.0 BPM capture vs 123.0 BPM album

Same key and same tempo. The album version and the cartridge version are the
same piece, so **the released soundtrack is a faithful reference after all**.

### What that costs

The earlier entry "The OST is NOT ground truth - and that reverses the
refutation" is **wrong and is withdrawn**. Its reasoning was that decoded modules
matched their own album audio at chance (1 of 16) and that no field matched album
tempo, therefore the album must be a different production. The parsimonious
explanation was always the other one: **the album is fine and the decode is
wrong.**

This is the error pattern to name: a negative result was explained away by
impugning the reference rather than the hypothesis. The reference then got
"replaced" with internal tests that were weaker (melodic continuity, which any
smooth parameter passes), and the wrong conclusion survived two more rounds.

So the original album-based chroma test stands as **valid evidence**, and it
refuted the decode correctly the first time.

### Why the earlier cart capture disagreed

The Bone Crusher capture ranked its own album track 9th of 16 audio-to-audio.
That was a 34-second phone recording of gameplay, with sound effects over the
music. The Intercom direct capture is 208 seconds and clean. Recording quality,
not a different production.

## Two hardware tests, both failed

| Test | Reference | Correct module | Rank |
|---|---|---|---|
| Bone Crusher | phone, 34 s, gameplay SFX | track07 | **52 / 52** |
| Intercom | direct capture, 208 s, clean | track04 | **15 / 52** |

Chance is 26. Neither passes, and the second is on a good reference, so the
refutation of the note/octave decode is now supported by better evidence than
when it was first made rather than worse.

### Block 888 is not yet identified

Chroma put it closest to album track07 (+0.929) but tempo refutes that outright:
71.8 BPM against 161.5, a ratio of 2.25. Chroma alone is not sufficient to
identify a track - worth remembering, since it nearly produced a false label.
Tempo-compatible candidates are track12/20/23/27/33/34/35/57/59 (73.8 BPM) and
track25/36 (143.6). Needs a `0x8C` capture from the cmdlog build to label
properly.

## Consequence for method

The album is usable, which restores 50 potential reference tracks instead of the
handful of hardware captures. Any hypothesis can now be scored across many
labelled trials, which is what defeats the multiple-comparison problem.

**Label recordings by tempo AND chroma together, never chroma alone.**

## Event layer restarted from nothing - and the container is now fully mapped

Working from structure alone, assuming no field means anything.

**Mutual information between the eight byte lanes** shows 2-byte grouping, not
4: L2-L3 couple most strongly (0.71 bits), and there is clear same-parity
coupling across slots (L4-L6 0.51, L5-L7 0.47, L2-L4 0.46, L3-L5 0.45).

**A row is four optional 2-byte slots**, all drawing on the same vocabulary
(`0200`, `0300`, `0400` lead in every slot). Occupancy falls 85.7 / 45.9 / 39.5 /
31.0%. Left-packing was tested and **refuted** - 27% violations - so the slots are
independently occupied, commonly slot 0 alone (38.6%) or all four (19.5%).

The commonest rows are a single 2-byte event with everything else zero:

    02 00 00 00 00 00 00 00    2.66%
    01 04 00 00 00 00 00 00    1.65%
    03 04 00 00 00 00 00 00    1.53%

First byte spans `01..0E`. **14 = 2 x 7** suggested scale degrees rather than
semitones, which is a different hypothesis from any tried before.

### Thirteen interpretations tested against hardware, all fail

Each scored by where `track07` lands against the Bone Crusher recording:

    rank  6/52   a delta major degree      <- best, and not significant
    rank 12/52   b minor scale degree
    rank 18/52   a major scale degree
    rank 26/52   a minor scale degree      <- chance
    rank 50/52   a absolute semitone
    rank 52/52   a + octave b              <- the previously assumed model

Chance is 26/52 and rank 1-2 was pre-registered as the bar. With 13 hypotheses,
a rank of 6 is exactly what chance produces - `P(rank<=6)` is 11.5% each, so
about 1.5 of 13 should reach it. **Nothing passes.** Absolute semitone and scale
degree, on either byte, plain or delta, are all dead.

Searching further in this direction would be multiple-comparison mining, so it
stopped here.

## CORRECTION: the SFX engine cannot be the music synth

Stated earlier in this document that a 26-voice synth could be reached by
extending `audio_sfx.sv`, since it already does per-channel rate, volume, pan and
echo. **That is wrong.** The engine has no chromatic pitch:

    reg [2:0]srate;   // 8 sample rates, sub-multiples of the 48 kHz tick
    reg [4:0]pitch;   // "skip 1 of 2..32 cycles"
    pitch <= flags[7] ? 5'd31 : flags[5] ? 5'd1 : 5'd0;   // three values in use

Eight rates and a cycle-skip cannot play a melody. Whatever renders MWMM is a
**separate mechanism that has never been seen** - not in RTL, not in firmware
(krikzz substitutes CDDA and never implemented it), and not in any dump. That
also explains why the module's values look like indices rather than frequencies:
there is no frequency register anywhere in the hardware we have.

Building the synth therefore means *designing* one, not extending what exists.

## Where the work actually stands

| Layer | State |
|---|---|
| Container - order list, voices, patterns, rows, slots | **Fully mapped**, all internally verified |
| Text encoding (XOR 0xA5) | Solved |
| Event semantics | **Open**, with every simple reading refuted against hardware |
| Reference material | One 34 s cartridge recording; the album is unusable |

The honest position: the container is understood and the payload is not. Cracking
event semantics with no reference implementation, from 52 files and a single
recording, is a research problem rather than an engineering one.

## What would actually change that

**More hardware recordings.** One recording tests one track, so any hypothesis
gets a single 1-in-52 shot and cannot be distinguished from luck. Ten recordings
of ten known tracks would let a hypothesis be scored across ten independent
trials - a real statistical test rather than a coin flip, and enough to survive
the multiple-comparison problem that just stopped this round.

That is cheap to collect and would make every future hypothesis decisively
testable. It is the highest-value thing available.

## RESOLVED: 26 voices, and the order list is voice-major

Settled with internal evidence, no audio involved.

**The order list is not a positions x voices grid.** Autocorrelation across all
52 modules decays smoothly with lag and shows no peak at either candidate:

    lag 13  20.7%   neighbours 20.9%   excess -0.2 points
    lag 26  15.4%   neighbours 15.3%   excess +0.1 points

A real period is a peak above its neighbours, not a high value - short lags
repeat more by chance. There is no period, so the entries are not interleaved
columns.

**It is voice-major**: each voice's positions are contiguous. An unused voice is
then a whole block of the empty pattern, which is exactly what appears, against
a shuffle null:

    width 13   54.6% pure blocks   null  5.7%   excess +48.8
    width 26   70.2% pure blocks   null 15.7%   excess +54.5
    width  2    6.7%               null  1.9%   excess  +4.8

("pure" = a block that is either >90% empty or <2% empty - a voice that is
unused, or always playing. A shuffle cannot manufacture that.)

**26 voices**, and the two readings converge on it regardless of block count:
13 blocks each carrying 2 voices per pattern, or 26 blocks each carrying 1. Both
give 26. The header's four per-voice arrays are **26 bytes** - one byte per voice
(volume `0x10`, pan `0x80`) - not 13 u16, which corroborates it independently.

**The block count is 26, so a pattern carries ONE voice.** The deciding evidence
is an asymmetry that cannot arise by chance. Taking bytes 0-3 and 4-7 of each row
as two candidate voices, across 2525 patterns:

    both halves active 2129    only the first 342    only the second 0

Two independent voices would split roughly symmetrically. A hard zero on one side
means the second half is populated only when the first is - it is dependent, not
independent. The halves belong to the same voice.

### Correction to the row model

Earlier entries describe the 8-byte row as "2 events of 4 bytes" and speculated
it "interleaves two voices". The framing is right and the speculation is wrong:
both events belong to **one** voice, so they are two consecutive time steps, or
an event plus a secondary slot. That also disposes of the lane-symmetry argument
used to suggest two voices - the halves are symmetric because they are the same
kind of thing, not because they are different voices.

### Settled layout

    +0xD8       order list, u16 big-endian absolute file offsets
                VOICE-MAJOR: 26 contiguous blocks, one per voice
                each block is len/26 position entries
    min(order)  patterns, contiguous, rows of 8 bytes
    row         2 events of 4 bytes, BOTH the same voice

Still open: what the 4-byte event contains. The note/octave reading was refuted
against hardware (see below), so this restarts with no field assumed to be pitch.

## Array B as a per-voice transpose: dead, and so is the whole family

**Array B is entirely zero for track07** - Bone Crusher, the only track we have a
hardware recording of. So are arrays A, C and D, in the sense that matters: A is
a constant `0x10`, C all zero, D a constant `0x80`.

    track07 header arrays:  A const 10   B ALL ZERO   C ALL ZERO   D const 80

Applying B as a transpose there is a **no-op**. It cannot change the 52/52 result
and cannot rescue anything. (Across the corpus 15 of 52 modules have any nonzero
B at all; 37 are entirely zero.)

That alone removes the excuse: Bone Crusher carries no per-voice base of any
kind, so if the note/octave reading were correct, plain absolute pitch should
have matched. It ranked last.

### The general case, closed too

Rather than stop at array B, the entire per-voice-transpose family was tested by
granting each module a **free 0-11 transpose per voice, fitted by coordinate
ascent to maximise agreement with the recording** - best case, every module
given the same advantage.

    rank  1  track11  +0.999
    rank  2  track21  +0.998
    ...
    rank 34  track07  +0.972   <- the correct answer, below chance (26)

Bone Crusher fits **worse than 33 other modules even after being optimally
fitted to the recording it actually is**. If the note reading carried real pitch,
track07's notes should fit its own recording better than other songs' notes do,
fitting or no fitting. They do not.

Note the fitted correlations are all +0.97 to +0.999: with 26 free parameters
every module can be bent to match, so the model is nearly vacuous. That makes
the test weak at *confirming* anything - but the ordering is still informative,
and it puts the right answer in the bottom half.

**Conclusion: no per-voice pitch base rescues the decode.** The refutation stands
without qualification, and the remaining explanation is that the 4-byte event
simply does not contain a semitone note where it was thought to.

## HARDWARE VERDICT: the note/octave decode is wrong

A 34-second capture of **Bone Crusher from original hardware** was run blind
through `scripts/identify_track.py` against all 52 modules. The correct module is
`track07.mwmm`.

    Bone Crusher (track07)  rank 52 of 52   corr +0.300   (winner +0.809)

Dead last. Repeated on two independent 17-second halves: **52/52 both times**.
Worse than chance, not merely unsupported.

Confounds checked, none of them explains it:

- **track07 is not a degenerate module.** 568 decoded notes, 23rd of 52 by count,
  peak/trough 22.2 - entirely typical.
- **The ranking is not just counting notes.** Correlation between match score and
  note count is only +0.253; `track53` decodes 114 notes and ranks 4th while
  `track37` decodes 1181 and ranks near the bottom.
- **The reference is valid.** Real cartridge, real synth, correct track named
  only afterwards, and the chroma feature is separately validated at 8/8
  own-best on segment-vs-segment.

This was pre-registered before the answer was known - "mid-pack or lower means
the decode is wrong" - so it stands as written.

## What that costs, and what survives

**Withdrawn:** note + octave as semitone pitch.

**The melodic-continuity result was weaker evidence than it was presented as.**
+18 and +20 points over a shuffle shows the values move in small steps. So does
*any* smoothly varying parameter - a volume envelope, a filter sweep, a pan
automation. It never distinguished pitch from those, and it was treated as
though it did.

**Still standing**, because none of it depends on the pitch reading:

| Claim | Basis |
|---|---|
| Order list, u16 absolute offsets, self-delimiting | 52/52 self-consistent |
| Patterns contiguous, sizes a multiple of 8 | 2509/2525 |
| Row = 2 events of 4 bytes | symmetric lane statistics |
| Text is XOR 0xA5 | all 52 titles, composers, comments decode |
| The album cannot serve as reference | key and tempo both fail |

The octave-wrap observation remains a real, specific pattern (delta pairs summing
to 12, resolving to identical net intervals 65-84% of the time). It means
*something* - but whatever it means, it does not produce the pitches the
cartridge plays.

## Next step

Stop extending the current model; it is falsified at the top. The structural
layer is solid and the event layer is not, so work restarts at the 4-byte event
with no assumption that any field is a note.

The asset from this round is the **method**: a blind, pre-registered test against
real hardware that a wrong answer cannot pass. `identify_track.py` plus one
cartridge recording now falsifies any hypothesis in seconds. Every earlier round
of this work failed for want of exactly that.

One hypothesis worth testing before abandoning pitch entirely: the values may be
pitch **relative to a per-voice base**, in which case pooled chroma is wrong by
construction. Header array B (`+0x2A`, sparse, the only per-track-varying array)
is the obvious candidate for that base. Testing it needs the voice mapping, so
resolve 13-vs-26 first.

## 0xB0 does not fix the elevator - but the trigger is now known

Tested on hardware with the sixth firmware fix in place. **The elevator still
glitches**: the player sprite drops to the background, and square sprite blocks
scroll across the screen.

New and useful: it happens **when a background elevator is scrolling past**.

That is sustained tile streaming, which is exactly when port 0/1 traffic is heaviest
and the MCU on port 2 waits longest - and it matches MisterPezz82's recorded root
cause, shared-SDRAM port starvation. So `0xB0` being a dead end here is consistent
rather than surprising; it fires once at init and has nothing to do with sustained
bandwidth.

### The next lever is a tunable we already have

`rtl/sdram.sv`:

    localparam [7:0] STARVE2_LIMIT = 8'd24;
    wire boost2 = port2_pending && (starve2 >= STARVE2_LIMIT);

The arbiter is strict fixed priority (refresh > port0 > port1 > port2), so under load
the MCU is served only **once every 24+ arbitration rounds**. That is a hard cap on
its bandwidth precisely when the game needs it most.

MisterPezz82 chose 24 and recorded that it "reduces (does not fully resolve) the
animation skipping" - so by their own account the MCU is still starved at this value.

**Experiment:** lower it. 8 would triple the MCU's worst-case service rate while
still leaving the console 7 of every 8 rounds. The trade-off is real and needs
watching: port 0/1 are the 68000 and VDP, which have real-time deadlines, so taking
cycles from them can create its own artefacts. Test for new glitches elsewhere, not
just the elevator.

If lowering the limit changes the elevator at all - better or worse - that confirms
starvation as the mechanism, which is worth knowing even if the value needs tuning
afterwards.


## STARVE2_LIMIT=8 changes nothing - evidence against starvation

Built at 8 (from upstream's 24) and tested on hardware. **The elevator glitches
identically.**

Under contention that is a real 3x increase in the MCU's service rate - one access
per 8 arbitration rounds instead of one per 24. Tripling its bandwidth produced no
observable change, which is difficult to reconcile with "the MCU is starved and
falls behind on per-frame composition".

Cost of the build, for the record: **18,045 ALMs (98%) against 16,900 (91%)** and
worst slack **-3.413 against -2.539**. Changing one constant should not cost 1,145
ALMs; that is the fitter landing badly at high utilisation rather than the
comparator growing. Worth knowing that fits at this density are unstable.

### Next: the opposite experiment

Now building at **96** - starving the MCU roughly 12x harder than upstream's 24. If
the elevator is unchanged at both 8 and 96, MCU bandwidth is **not** the mechanism,
and the root cause MisterPezz82 recorded is wrong. That is the single most useful
thing left to learn about this bug, because it has steered the investigation since
before this port existed.

If 96 makes it clearly worse, starvation is real after all and 8 simply was not
enough of a change - in which case the useful direction is removing the arbitration
cap for port 2 entirely rather than tuning a threshold.

**Revert to 24 afterwards** unless a result argues otherwise: 8 costs ALMs and
timing for no benefit.


## SETTLED: MCU starvation is not the elevator's cause

Both directions tested on hardware.

| STARVE2_LIMIT | MCU bandwidth | Elevator | Everything else |
|---|---|---|---|
| 8 | 3x more | **unchanged** | no reported difference |
| 24 (upstream) | baseline | glitches | fine |
| 96 | 12x less | **unchanged** | **visible slowdown, dropped frames** |

The frame drops at 96 are what make this conclusive. **The knob demonstrably
works** - starve the MCU and frame pacing suffers, which is precisely the animation
skipping MisterPezz82 logged as issue #10 and added `STARVE2_LIMIT` to address. The
game is genuinely sensitive to port-2 arbitration.

**And the elevator is indifferent to it in both directions.** Three times the
bandwidth does not help; a twelfth of it does not hurt. Whatever corrupts the
elevator is not MCU bandwidth.

So upstream's recorded root cause - "ROOT CAUSE = shared-SDRAM port starvation" -
conflated two separate problems. Starvation explains the animation skipping. It does
not explain the elevator.

**Restored to 24.** 8 costs 1,145 ALMs and 0.87 ns for no benefit; 96 makes the game
worse. 24 is the value the animation fix was tuned to and neither direction improved
on it.

### Where the elevator investigation goes now

Everything tried and eliminated: the sprite-attribute composition (upstream built and
HW-tested it, no effect), `0xB0 sprite_init` (implemented here, no effect), MCU
bandwidth in both directions (no effect), and decompression (upstream verified the
decoders match GPGX, and this port has since replaced the `0x81` decoder with the
real LZO one and the subway renders correctly).

What is known: it happens **when a background elevator is scrolling past**, and it
manifests as the player sprite dropping to background priority plus square sprite
blocks scrolling across.

That combination - a scrolling background object, sprite priority, and block-shaped
artefacts - points at the VDP side rather than the MCU: plane priority, scroll
tables, or VRAM allocation for the scrolling layer. The next diagnostic should look
at what the game writes to the VDP during that scene, not at what the MCU is doing.


## Strong elevator lead: the VRAM block budget is silently clamped

The MCU firmware does the graphics assist WaterMelon's chipset was meant to -
decompression, sprite composition, and **VRAM block allocation**. That last one has
an acknowledged hack in it.

`mame.c`, `ppm_vram_set_budget`:

    // temp failsafe
    if (blocks > 0x35) {
        printf("Allocation error (0x%x blocks)
", blocks);
        blocks = 0x35;
    }

**krikzz's own "temp failsafe" clamps the VRAM budget at 53 blocks.** Ask for more
and you get 53. `ppm_vram_load_block` then starts returning 0, `blocks_available`
goes false, and the object falls back to its previous animation frame with whatever
tiles happen to be resident.

That predicts exactly the reported symptoms: **block-shaped artefacts** (wrong tiles
resident) **and sprites behaving wrongly** (stale frames), during a scene with heavy
tile demand - a scrolling background elevator.

There are two further failure paths in the same function, invisible from the command
stream: the DMA budget check (`dma_remaining < 0x110`) and "no free slot", both of
which also return 0.

### What the captures already show

`0xEC` sets the budget from `cmd_args[1]` (cart RAM `0x1E12`). Across both LOG_ALL
captures of the first room:

    29 blocks, 1 block, 29 blocks, 49 blocks

All under the clamp - **but 49 is close to 53**, and neither capture reaches the
elevator.

### The diagnostic

Filter the logger to `0xEC` alone. It fires a handful of times per level, so the ring
will comfortably survive to the elevator, and the requested budget is read directly
from the capture. If the elevator scene asks for more than 53, the clamp is firing
and this is the bug.

That is a one-line change to `keep` in `paprium_cmd_log.sv`.

If the budget stays under 53 there, the clamp is innocent and the next suspects are
the DMA-budget and no-free-slot paths, which need firmware instrumentation rather
than command logging.

**This is a far better lead than anything MCU-bandwidth related**, because it
predicts both halves of the symptom rather than just "things go wrong under load".

## The VRAM budget clamp: 53 is mega-ppm's limit, not the console's

`ppm_vram_set_budget` in `mame.c` clamps the requested block count at `0x35`
under a comment reading "temp failsafe". Working out where 53 comes from:

Every block is a fixed **16 tiles** - `ppm_vram_load_block` hardcodes the DMA
length at 0x100 words (512 bytes) and advances the unpack pointer by 0x200.
The allocator is fixed-size LRU: `age` selects the victim, `usage` pins blocks
still needed this frame.

Slot index translates to a VRAM tile address as
`((x + (x <= 0x30 ? 1 : 0x4b)) << 4)`:

| slots  | block index | tiles     |
|--------|-------------|-----------|
| 0-48   | 1-49        | 16-799    |
| 49-52  | 124-127     | 1984-2047 |

Slot 53 maps to tile 2048 - one past the end of the Mega Drive's 2048-tile
VRAM. **So the clamp is not an arbitrary margin, and the constant cannot just
be raised**: 54 would DMA off the end of VRAM.

### But it does not mean VRAM is full

53 blocks is 848 tiles. Plus the 16 reserved low tiles, that is 864 of 2048.
**Tiles 800-1983 - 1,184 tiles, 37 KB - are never allocated at all.**

Plane maps, the sprite attribute table, hscroll and window live somewhere in
that gap, but on a typical setup those come to roughly 450 tiles' worth. The
remainder appears to be unused. The two-range mapping with a large hole in the
middle has the shape of a partial reverse-engineering (mame.c is derived from
MAME's `rom.cpp`), not of a deliberate layout.

### Where the cartridge chips come in

The MAX 10 and STM32 **cannot** touch VRAM - it is inside the VDP on a private
bus, reachable only by 68000 DMA. The 2048-tile ceiling is absolute and no cart
silicon raises it. But deciding *how to pack those tiles* is precisely the job
those chips did. If the real chipset packed the middle region, or used
variable-size blocks rather than fixed 16-tile ones, it would have had far more
than 53 blocks available.

So the ceiling to chase is 2048 tiles, of which we use 848.

### Next step, in order

1. **Does the elevator exceed 53?** The BUDGET_ONLY logger build captures only
   `0xEC`, so one run survives to the elevator. If the peak is <= 53 the clamp
   is innocent and this whole line is dead.
2. **If it exceeds:** find what actually occupies tiles 800-1983 by logging the
   VDP's plane/sprite/hscroll base registers (2, 3, 4, 5, 13) from our own RTL -
   we have the VDP, so this is directly measurable rather than guesswork.
3. Only then consider extending the slot mapping into whatever is genuinely free.

Do not raise `0x35` blindly. Slots past 52 alias off the end of VRAM, and slots
grown into the middle gap would land on the plane maps and sprite table - which
would look like corruption everywhere, not just the elevator.

## Two new hardware reports (2026-08-29)

### Block 888 door: red floor where hardware shows green

Reported leaving the first room. The floor of the doorway renders red; on original
hardware it is green and matches the cell behind it.

**This is very likely ours, and specifically the door fix itself.** The line is:

```c
if ((intf_obj->objID & 0xff) == 107 && x == 4) satEntry->attrs &= ~0x2000;
```

`0x2000` is bit 13 of the Mega Drive sprite attribute word - **palette bit 0**. So
the fix forces sprite 4 of object 107 onto a different palette line (1->0, or 3->2).
A wrong floor colour is exactly what a wrong palette line looks like.

Hypothesis: **`x == 4` is the floor sprite in our build, not the door panel.** The
fix came from MisterPezz82 against their build; if sprite ordering differs at all we
are recolouring the wrong piece - repairing the panel they saw and breaking the
floor we see.

Test is cheap for the tester: the door is ~30 seconds in, so an A/B needs no
playthrough. Build with the line disabled and compare:

- floor green AND panel still correct -> drop the fix entirely
- floor green BUT panel wrong again -> `x == 4` is the floor; find the panel's index
- no change -> the fix is innocent and the palette comes from elsewhere (CRAM)

Note `satEntry->attrs` is computed with an XOR chain including
`ppm_vram_find_block(...)`, so a block that failed to load returns 0 and changes the
resulting attribute word. A door whose block is missing could mis-colour for reasons
that have nothing to do with this line - worth keeping in mind if the A/B comes back
clean.

### Stage clear at full health plays the standard cue

At 100% health the game should play a different stage-clear tune; ours plays the
ordinary one.

**Probably not fixable under the OST-substitution approach.** The released
soundtrack contains exactly one Stage Clear track (cue index 52). There is no
separate perfect-clear recording on the album, so if the cartridge plays a variant
it is a modified render of the same module by the synth - not a track we can
substitute.

Worth one cheap capture anyway, because two outcomes differ materially:

- the game requests a DIFFERENT track index -> we map it wrong (or to Blank), and
  that is fixable
- the game requests the standard index and signals the variation another way, most
  likely `0xD6 music_special` which this firmware mutes -> confirms it is a synth
  render, and closes the question

The audio-filter logger mode already captures `0x8C`, `0x8D` and `0xD6`. Clear
stage 1 at full health, then exit.

### Note on where sat_data lives

`ppmio.ramdp->sat_data[144]` sits at cart RAM byte offset 0xb00, items of 8 bytes
(posY, sizeNext, attrs, posX), so `sat_data[i].attrs` is at byte `0xb00 + i*8 + 4`.
That is inside the shared RAM - but it is written by the MCU, not the 68000, and the
command logger snoops 68000 writes only. Reading actual sprite attributes would need
a snoop on the MCU write port, not the existing one.

## RESULT: the VRAM clamp is innocent, and the door fix is not the door bug

One run, two experiments, both conclusive.

### The clamp never fires

    mailbox commands seen  23899      <- the control: the snoop was alive
    0xEC seen                 26
    peak budget requested     53 (0x35)
    last                      53

The logger records the value the 68000 writes to `0x1E12`, i.e. the **request**,
before the firmware clamps it. The peak request across a full run to the elevator
is **exactly 53** and never above. Budgets seen: 1, 2, 29, 40, 49, 53.

**So `ppm_vram_set_budget`'s "temp failsafe" never truncates anything, and the
clamp cannot be the elevator's cause.** That line is closed.

This is the answer the previous capture could not give: `any_cmd_cnt` at 23899
proves the snoop was working, so "0xEC never exceeded 53" is a fact about the
game rather than a fact about our filter.

### The door fix is refuted as the door's cause

With `PPM_DOOR_FIX` compiled out: **floor still red, panel still correct.**

That refutes the hypothesis directly. If `x == 4` were the floor sprite, removing
the palette-bit clear would have changed the floor's colour. It did not, so
`x == 4` is not the floor - and since the panel is correct without the fix too,
the fix is a visual no-op at this door.

Restored to enabled for shipping parity: there is no evidence it helps here, but
none that it harms either, and it came from upstream for a case we may not have
reproduced.

### What both results point at instead

Not the budget, but **block residency**. `ppm_vram_find_block` returns **0** when a
block is not resident (mame.c, confirmed), and that 0 feeds the sprite attribute
XOR:

```c
satEntry->attrs = ((spr_data->attrs & 0xf8) << 8) ^ intf_obj->attrs
                ^ (ppm_vram_find_block(spr_data->blockNum) + spr_data->offset);
```

In an XOR chain 0 is not "no change" - it silently alters **the tile index and the
palette bits together**. A missing block therefore renders as *wrong graphics in
wrong colours*, which is precisely both reported symptoms: the elevator's block
artefacts with sprite priority loss, and the doorway's red floor.

`ppm_vram_load_block` has three paths that leave a block absent:

1. `dma_remaining < 0x110`  - the per-frame DMA budget is spent
2. `block_index == 0xffff`  - no free slot (every slot has `usage` set)
3. `!num`                   - block 0

And the capture makes 2 plausible for the first time: **the game asks for the full
53 slots**, the exact ceiling the layout supports. It is running at the limit, so
exhaustion is no longer hypothetical.

### Next, and why in this order

Do **not** grow the slot pool blindly. Slots past 52 run off the end of VRAM, and
growing into the 800-1983 tile gap would land on the plane maps and sprite table.

1. **Read the VDP's own layout.** Snoop register writes 2 (plane A), 3 (window),
   4 (plane B), 5 (sprite table) and 13 (hscroll) from our RTL - we have the VDP,
   so what occupies tiles 800-1983 is directly measurable rather than guessed. That
   decides whether there is room to grow at all.
2. **Find out which failure path fires.** Firmware counters on the DMA-budget and
   no-free-slot returns. Needs a readout: `sat_data` and friends are MCU-written,
   so this needs a snoop on the MCU write port, not the existing 68000-side one.
3. Only then consider extending the slot map into whatever is genuinely free.

The doorway is now the cheapest known reproduction: 30 seconds in, versus a full
level to reach the elevator.

## Big-enemy death: probably not a missing cue, but a missing PITCH

Observed on **original hardware**: the big-enemy death sound is the standard
enemy death sound played **lower / deeper**, not a different sample.

If that is right it dissolves the puzzle that has blocked this all along -
**`0x1C` never appears in any capture**, and we kept looking for a cue that may
not exist. The game would instead be requesting the ordinary death sfx with a
pitch flag set.

Paprium has exactly such a flag:

    0x8000  pitch 31/32   slightly slower
    0x2000  HALF PITCH    half rate = one octave down = "deeper"
    0x4000  echo
    0x0100  amplify

### Our implementation of it is correct

`rtl/PAPRIUM/audio_sfx.sv`:

```systemverilog
pitch <= flags[7] ? 5'd31 : flags[5] ? 5'd1 : 5'd0;
if(!fifo_empty & next_sample & (pitch_ctr != 1)) addr_rd <= addr_rd + 1'd1;
if(next_sample) pitch_ctr <= pitch_ctr >= pitch ? 5'd0 : pitch_ctr + 1'd1;
```

Traced by hand:

- `pitch=0`  - ctr stays 0, never equals 1, a sample every tick. Full speed.
- `pitch=1`  - ctr alternates 0,1,0,1; consumed only when 0. **Half speed.**
- `pitch=31` - ctr runs 0..31, skips at 1. 31/32 speed.

So the RTL does what the flag asks. The open question is whether the flag arrives.

### The diagnostic

An audio-filter capture during a big-enemy kill, reading the **flags column** on
the `0x1A` request rather than hunting for `0x1C`:

    0x1A with flags 0x2000, but it sounds normal  -> our flag path drops it; RTL/ours
    0x1A with flags 0x0000                        -> the game never asks; firmware or
                                                     game state, and 0x1C stays a
                                                     red herring
    a different id entirely                       -> the table lookup is wrong

Third possibility worth keeping in view: the depth may come from the SFX table's
own rate field (`srate <= typev[6:4]`) rather than the flag, in which case a wrong
byte order on the table read would give the wrong rate. The SFX table needs the
`^1` byte swap, so that path is worth checking if the flags come back empty.

Cheap to run: kill one big enemy early, exit immediately, so the ring is short and
readable.

## RESULT: field-wise attrs fixes the door; the slot cap improves the elevator

Hardware, both probes in one run.

**Door: FIXED.** The doorway floor renders correctly. So the all-XOR attribute
composition was scrambling the palette, exactly as MisterPezz82's analysis said it
would, and **we had regressed against their V.04 by not carrying the field-wise
change.** Their fix was real - it was simply never described as a door fix, because
for them it was a failed elevator attempt that incidentally repaired this.

**Elevator: better, not fixed.** The player no longer stays stuck behind the
background as long, and the game reportedly runs smoother with better collision
response. So slots 49-52 *were* colliding with the top of VRAM - partial
confirmation - but they are not the whole cause. The smoother play is consistent
with capping the budget: fewer block DMAs means less bus contention.

Both changes are shipping candidates. No missing graphics were reported despite
the four-block reduction.

## The NX terminal is a readable diagnostic - and it says a sub-CPU is missing

The boot terminal on **original hardware** reports:

    ROM        : OK
    SRAM       : OK
    MODEM      : MW4.0
    SUB-CPU    : M68000

Ours - and reportedly every other replacement-firmware build - reports
`SUB-CPU : NONE`.

### The terminal text is XOR 0xFF at 0x12C6EC

A new and generally useful capability: the game's diagnostic strings decode with a
simple `^ 0xFF`, and the full table is readable. It enumerates exactly two options
per line, so the terminal is a **direct readout of what the game detected**:

    MODEM      : NONE / MW4.0
    SUB-CPU    : NONE / M68000
    SRAM       : OK / EMPTY
    ROM        : OK

`MODEM` is already spoofed by our firmware - `reg_status_2.bits.mwire_status = 7`
with the comment "let's pretend MW is plugged & connected" - so there is precedent
for these lines being satisfied by the cart rather than measured.

### SUB-CPU is probed on the console, not asked of the cart

There is no sub-CPU field anywhere in the cart's shared structures, so the game
tests the machine. An address table at 0xAF810 confirms it knows the relevant
hardware:

    0AF814  $420000   Sega CD PRG RAM
    0AF830  $A12000   Sega CD gate array
    0AF874  $A10001   version register (the /DISK expansion bit)

`btst #5,$A10001` does not appear literally, so the test is assembled differently
or computed - but the game plainly probes for a Sega CD.

### Open question that decides whether this is a bug at all

**Was the original-hardware playthrough on a machine with a Mega CD attached?**

- **Yes** - then `M68000` is simply correct there, `NONE` is correct for us, and
  there may be nothing to fix. What would still be worth knowing is whether the
  game takes a different code path when it sees one, since the elevator corruption
  is recorded as Original-mode-only.
- **No** - then a plain Mega Drive reports a sub-CPU we cannot account for, and
  the detection is something other than the expansion bit. That would be a real
  divergence worth chasing.

The existing to-do "fake an expansion (`DISK = 1'h0` in md_board.v)" now has a
**visible success criterion** for the first time: the terminal line itself. Worth
running either way, but the risk is real - a game that believes a Sega CD is
present may try to hand work to a sub-CPU that will never answer.

## RESOLVED: what the add-ons actually gate, and why the reference stands

The original-hardware reference playthrough was made with a **Sega CD attached**, so
`SUB-CPU : M68000` is correct there and `NONE` is correct for us. **Not a bug**, and
the open question above is closed.

I raised a worry that add-on-gated content might confound the reference
observations. **That worry was wrong and is withdrawn.** What the add-ons gate:

| Add-on | What it changes |
|---|---|
| Sega CD | Unlocks **CPU Mate** only - the CD's sub-CPU drives a second player as an AI co-op partner |
| 32X | Cosmetic item swaps: a 32X box appears, and Chavez throws 32Xs instead of bombs on ROOF-TOP |

Neither touches audio, graphics streaming, or sprite composition. So every
hardware observation recorded here - the doorway floor, the elevator, the
big-enemy death sound, the full-health stage clear - is a **valid comparison**
against our build, and no re-test without the CD is needed.

### The audio architecture, and why it matters for the stage clear

Paprium's sound is the cartridge's DATENMEISTER PCM channels **mixed with the
console's own YM2612 and Z80**, with the cart's extra analog audio fed in through
the cartridge slot pins.

That is not PCM *instead of* FM - it is PCM *plus* FM. Which makes the
"perfect-health finish is an additional layer" report structurally plausible rather
than a stretch: **the game's audio design has an FM layer to add.** It strengthens
the YM2612 hypothesis and leaves the zero-build rename test (see the stage-clear
to-do) as the right next step.

It also confirms the Sega CD would not have helped audio, independent of our own
earlier finding that GPGX's Paprium code carries no Mega CD or 32X references.

### Consequence for the Sega CD idea

Implementing a Mega CD inside this core is not feasible - we are at 91% ALM
(16,900/18,480) and 95% M10K (294/308), and a Mega CD needs a second 68000, gate
array, CD controller, RF5C164, plus 512K PRG RAM, 256K word RAM, 64K PCM RAM and a
BIOS. Pocket Mega CD cores exist, but each spends the whole FPGA on that; ours
already spends the whole FPGA on the Mega Drive plus Paprium's cartridge hardware.

And the only prize is CPU Mate - an AI co-op partner. Worth knowing, but it is a
feature, not a fix, and it buys nothing for any open bug here.

(Add-on effects per the tester, citing Wikipedia; consistent with our own evidence.)
