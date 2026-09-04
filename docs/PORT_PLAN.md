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
`0xD6 paprium_music_special`, which
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

### What the GPGX source rules out (2026-08-31, no build required)

- **The DAC bit changes nothing in the cartridge audio path.** `audio_flags` is
  read in exactly one place in GPGX - the `0x08` gain bit. The `0x01` DAC bit is
  only written back to cart RAM `0x1800`/`0x1801` so the 68000 can read its own
  setting. Our `paprium.c` writes the same two bytes the same way.
- The static is something **added** on top rather than replacing, which matches
  core_top's mixer: `base_audio + paprium_sfx + cdda_att`, summed into 19 bits
  and clamped. The YM2612 lands in `base_audio`.
- **GPGX never feeds the YM2612 DAC itself.** There is no cartridge-side write to
  register `0x2A` anywhere in `paprium.h`.

### CORRECTION - what the option actually does (hardware report, 2026-08-31)

The menu text is *"use VM2612 DAC instead of DT128VALT DAC"*, and on original
hardware selecting it makes the game **sound like a stock Genesis - fewer
channels, less full**. That is not a broken path, it is a working lo-fi option,
and it corrects two things assumed above.

**"Fewer channels" is literal.** Enabling the YM2612's DAC costs FM channel 6 -
that is how the chip works. So the option really does trade a channel away.

**"Less full" is the DAC swap.** The cartridge's DT128VALT is the good converter;
the YM2612's is the stock 8-bit one.

Which means the cartridge's PCM is **routed through the YM2612's DAC** when the
bit is set. And the cartridge cannot write YM2612 registers - it sits on the
cartridge bus, while the YM2612 is in the console - so **the 68000 must be
reading PCM from the cartridge and stuffing `0x2A` with it**.

So an earlier note here was wrong and is retracted: *"music still audible
underneath is correct behaviour"* was too strong. On hardware you hear the same
music through a worse converter, not the good path plus a second noise source.
Hearing full-quality music with hash on top means the routing is not happening
and something else is reaching `0x2A`.

That makes the first experiment a **discriminator rather than a fix attempt**:

**Do the ntsc bitstream's DAC samples work?** Nearly every Mega Drive game uses
YM2612 DAC PCM for drums and voices. Run any of them on the `ntsc` variant built
from this same tree:

- static there too -> the bug is in the base core's YM2612 DAC or our audio
  mixing, it is not Paprium-specific, and it is reproducible without the
  cartridge at all - a far easier thing to chase
- clean there -> the DAC is fine and something Paprium-specific is feeding it
  garbage. Then the question becomes what the game reads to source those samples

Do this before building any probe. It costs one bitstream that already exists and
it splits the problem in half.

### RESULT: the DAC is fine, the feed is wrong (2026-08-31)

**Sonic 2 drums play correctly on this tree's `md_ntsc`** (md5 `e99bb253`, 82%
ALM, setup -1.946). Not crunchy, not hashy - correct.

Three things settled:

- our base core's YM2612 DAC works
- **`CFG_LPF = 2'd3` does not damage DAC audio.** The mode-3 bypass is a colour
  choice, not a destroyer. Do NOT "fix" VM DAC by turning the filter on
- therefore the VM DAC hash is a **feed** problem: something is putting junk into
  YM2612 register `0x2A`

**A wrong turn worth recording.** Between the prediction and the test I talked
myself into a filter theory: mode 3 bypasses `genesis_lpf`, real hardware always
filters, an unfiltered 8-bit DAC could sound like hash. It was wrong, and it was
wrong in an avoidable way - the same note also contained the objection that kills
it, that no LPF should sound *harsh*, not like radio static. The objection was
right and I let the tidiness of the story outweigh it.

Two process points fell out of it:

- earlier "drums are fine" listens were on `ericlewis.Genesis` and on an Aug 26
  file that turned out **not** to be this tree's `md_ntsc` (2,019,008 bytes vs
  1,911,596, different hash, archived at
  `build_output/card-backup/md_ntsc.CARD-Aug26.rbf_r`). Neither could implicate
  mode 3. Only a known bitstream can answer a question about a specific config
- the original prediction was correct and the revision was not. Predictions
  recorded in advance earn their keep precisely when they disagree with a later,
  more elegant story

### CONFIRMED: it is a PCM stream buffer (2026-08-31)

Filling `0x1802-0x19FF` with `0x80` **killed the hash on hardware**. VM DAC no
longer produces static.

So the 68000 does read that window and push it to YM2612 register `0x2A`, and the
static was it streaming uninitialised `ramdp`. GPGX's `/* DAC list ?? */` guess
was right and the region is now identified: **an unsigned 8-bit PCM stream buffer
the cartridge is expected to keep filled.**

The probe fit was byte-identical to shipping in ALM, M10K, setup and hold
(18,194 / 294 / -2.596 / +0.004), so this costs no logic.

### The "DAC list" region - the reasoning that got there

GPGX suppresses debug logging for reads in cart RAM `0x1800-0x19FF` with the
comment `/* DAC list ?? */` - its author saw reads there and never identified
them. We write `0x1800` and `0x1801` (the settings bytes); the other 510 are
whatever `ramdp` happens to hold.

The size fits a stream buffer uncomfortably well:

    0x1800-0x19FF = 512 bytes
    512 samples refilled once per NTSC frame = 30,679 Hz
    512 samples refilled once per PAL  frame = 25,446 Hz
    two 256-byte halves, NTSC                = 15,340 Hz

All three land inside the 8-32 kHz band Genesis PCM streaming normally uses, and
30.7 kHz in particular is a common choice. An 8-bit sample buffer the cartridge
is expected to keep filled, read by the 68000 and pushed to `0x2A`, would explain
the symptom exactly: we never fill it, so the 68000 streams uninitialised RAM,
which is hash - while our own SFX engine carries on feeding `paprium_sfx` at full
quality underneath.

**Still a hypothesis, and the arithmetic is suggestive rather than probative.**
Against it: the settings bytes sit at `0x1800`/`0x1801`, i.e. inside the same
window, so either the buffer starts at `0x1802` or the first bytes are a header.
Nobody has confirmed the game reads that range at all.

### SHIPPED: the fill (2026-08-31)

Keeping the `0x80` fill turns VM DAC from "adds static" into an **inert menu
item**: the DAC path sits at DC and the cartridge audio plays exactly as it does
with the option off. Firmware-only, identical fit, and it closes a real defect.

It does NOT reproduce what hardware does. On a real cartridge the option also
**thins** the mix. Here it changes nothing audible except spending FM channel 6.
That is documented in INSTALL.md rather than left for someone to discover.

### DEFERRED: the hardware-accurate implementation

Not built, and deliberately so - it is new RTL on a core fitting at 98% ALM with
4 ps of hold margin, for a checkbox whose purpose is to sound worse. Recorded in
full because **it becomes cheap on a larger FPGA**, and whoever ports this should
not have to rediscover any of it.

**What hardware does.** The cartridge's PCM is routed through the YM2612's own
8-bit DAC instead of the DT128VALT. Same cues, worse converter, and FM channel 6
is spent because that is the channel the DAC replaces. The result is thinner and
more Genesis-like. The 68000 does the moving: it reads cart RAM `0x1802-0x19FF`
and writes bytes to YM2612 register `0x2A`.

**Two pieces are needed.**

*(1) Fill the window with real audio.* Unsigned 8-bit, mid-scale `0x80`, at about
30 kHz - `512 samples x 59.92 fps = 30,679 Hz`, and the buffer is refilled per
frame. Source is the sum the mixer already has:

    paprium_sfx_l/r + cdda_l/r        (16-bit signed, clk_sys)
      -> mono, or the left channel; the YM2612 DAC is mono
      -> decimate 48000 -> ~30,679 Hz
      -> (sample >>> 8) + 0x80        signed 16-bit to unsigned 8-bit
      -> write into ramdp at 0x1802-0x19FF, wrapping

*This is the hard part, and the reason it was deferred.* The MCU firmware cannot
do it: `paprium_sfx` and `cdda` are generated in the FPGA in the clk_sys domain
and the firmware never sees those samples. It needs a **new hardware writer into
`ramdp` from the audio domain** - a third master on a dual-port RAM that already
has the MCU on one port and the 68000 on the other. Expect arbitration work, not
just a counter.

Watch the write pointer: the 68000 reads this window continuously, so a writer
that laps the reader tears the stream. Hardware presumably double-buffers, which
is a plausible reading of why the region is `0x200` bytes rather than `0x100` -
two 256-byte halves, filling one while the game drains the other. **Unverified.**

*(2) Duck the cartridge path.* A mux in core_top's mixer, and genuinely easy:

    mix = base_audio + (vm_dac ? 0 : paprium_sfx) + (vm_dac ? 0 : cdda_att)

"Less full" means *instead of*, not *as well as*. Ducking without (1) just gives
silence, so the two must land together.

**Where the `vm_dac` bit lives:** the firmware already has it - `cmd_88_audio_cfg`
receives it as bit 0 and writes `ram[0x1801]`. Getting it to core_top means one
more signal out of the cartridge, which is cheap.

**Cost estimate on this device:** the ramdp writer plus decimator is the bulk of
it; the mixer mux is a handful of ALMs. On a device with headroom this is a small
afternoon. Here it competes with 4 ps of hold margin, which is why it is written
down instead of built.

### How it was found: a fill test, not a logger

The obvious next step is a bus log of 68000 reads in `0x1800-0x19FF`. There is a
cheaper experiment that answers the same question audibly, and this project's own
record says a controlled trigger beats analysis:

**Fill `0x1802-0x19FF` with `0x80` and listen.** `0x80` is mid-scale for an
unsigned 8-bit DAC, so a constant fill is a DC level - silence.

    hash becomes SILENCE  -> the 68000 IS streaming that window   <-- THIS ONE
    hash unchanged        -> it is not, build the bus logger instead

One firmware change and one listen settled what a bus logger would have taken the
same build to capture and then required reading. The project's own note holds: a
controlled trigger beats analysis.

`0x1800`/`0x1801` must be left alone - they carry the DAC and NTSC settings the
game reads back, and overwriting them would break the `0x88` fix and confuse the
result.

One bitstream, one listen, and an unambiguous answer either way. A logger costs
the same build and needs interpretation afterwards.

### If the hypothesis holds, the fix shape

Fill the window each frame with the same PCM the SFX engine is producing,
downconverted to 8 bits, and let the 68000 push it to `0x2A`. The cartridge DAC
path should then be attenuated or muted so the audio is not heard twice at two
different qualities - "less full" means instead of, not as well as.

Not a Pocket fit until the discriminator says so.

### What would NOT be worth doing

Comparing against GPGX by ear needs a host that runs frames and takes input;
`tools/gpgx-render` exits during `retro_load_game` because its hook fires there.
That is a real piece of work, and the ntsc test answers the same question for
free. Note also that GPGX does not implement this routing either, so it is not a
reference for what VM DAC should sound like - only hardware is.


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

## RESULT: no FM layer - the stage clear is entirely PCM

Blob renamed away, so no music path exists and anything audible would be the 68000
driving the YM2612 directly.

    perfect health   no sound
    damaged          no sound

**Silence both times.** So the stage-clear cue - both versions - comes wholly from
the cartridge PCM path. There is no FM fanfare being dropped, and the "additional
layer" is not a YM2612 voice.

The one caveat stated before the test still stands: a PCM sample routed through the
YM2612's *DAC* would also be silent here, and that DAC path is independently broken
(see the static to-do). So this is strong evidence rather than proof. It does
however remove the FM-voice hypothesis, which was the version worth building for.

### The cue sheet is not the explanation either

Checked offline, no hardware needed: no cue index maps to the same file twice.
`12 Stage Clear.wav` is reached only by index 52, and the ten `Blank.wav` entries
are the ten indices where the cartridge's own pointer table is null.

So we are not accidentally pointing two different requests at one recording. If the
game asked for a different track at full health, we would have played a different
file or silence - and the tester heard the ordinary cue. The game therefore asks
for **track 52 both times**.

### Where that leaves it

The variation has to be produced *within* the render of track 52 - a synth
difference, not a track difference. Substituting a fixed recording for that track
loses it by construction. **This returns to the original position: not reproducible
under OST substitution.** The softer reading offered mid-investigation was wrong,
and the evidence now supports the first answer.

One thing still worth a cheap capture, because it identifies the mechanism even
though it probably cannot be fixed: whether a `0x8D music_setting` or `0xD6
music_special` accompanies the full-health clear and not the ordinary one. `0xD6`
is muted in our firmware. Knowing it is the modifier would close the question
properly rather than by elimination.

## Elevator: the corruption is REAL SPRITE GRAPHICS in the wrong place

Best description of this bug recorded so far, from hardware:

> The tiles all look like they are the sprites of the game scrambled in the wrong
> place, but it is not interactable. The actual battle stage can move around and
> still fight the bosses.

Three things follow, and together they discriminate between the surviving theories:

1. **The garbage is real decompressed graphics, not noise.** So the decompressor
   works - consistent with MisterPezz82 verifying `0x80`/`0x81` against GPGX.
2. **Game logic is untouched** - movement and combat are normal. Nothing is
   corrupting game state; this is purely VRAM/display.
3. **Sprite graphics appear where background block tiles belong.**

### Why that points at 0xF2 rather than a bad destination

`cmd_F2_unpack` does not change where a DMA lands - it changes where the data comes
from:

```c
void cmd_F2_unpack() {
    // used in sprites test menu      <- krikzz's own comment
    ppm_unpack(ppm_block_addr(ppmio.ramdp->cmd_args[0]), 0x9000);
    ppm_unpack(ppm_block_addr(ppmio.ramdp->cmd_args[0]), 0x9200);
    FPGAIO->sdram_ptr = 0x9000;       // repoints the streaming window
}
```

Correct destination, wrong source, so a block slot is filled from the wrong place in
the workspace: **intact sprite graphics rendered as background blocks**, in a
structurally valid location, leaving the scene underneath to render and play
normally. A wrong *destination* would scatter data across VRAM and break more than
one thing at once.

It also explains why the slot cap helped but did not fix it - that was a genuine
but separate destination collision.

krikzz's comment marks `0xF2` as a **sprites test menu** feature, and GPGX disables
it as a debug viewer. We implement it. If the game issues it during normal play,
the streaming window is silently redirected.

### The probe

One line, and MisterPezz82 recommended it but never ran it:

    cmp_ptr[0xF2] = cmd_unknown_muted;

If the elevator's garbage disappears, `0xF2` is the cause. If a genuine sprite test
menu stops working, that is the expected cost and tells us the mute is effective.

Run after the sfx capture - this one needs a run to the elevator, the sfx capture
needs a short run, and they cannot share a ring.

## TO DO: 6-button pad support (X/Y/Z/Mode) - not implemented here

Confirmed absent: no `vpad`, no code cave, no ROM-read substitution anywhere in
this tree. 3-button play works; X, Y, Z and Mode do nothing.

### Why our pad being correct does not help

MisterPezz82 verified the core side is already right - `pad_io.sv` returns the exact
6-button protocol frames (JCNT=2/TH=0 -> `{Start,A,0000}`, JCNT=3/TH=1 ->
`{C,B,Mode,X,Y,Z}`), with the TH-edge counter and the ~1.5 ms inactivity reset. The
failure is in **the game's read**: Paprium's pad routine at ROM `0xaae0` is a plain
3-button read that bails after one TH toggle, and its real 6-button routine is not
visible in the static ROM (likely MCU-decompressed or dynamically addressed).

Their leading explanation is that the read is stalled past the ~1.5 ms window - on
real hardware it halts the Z80 to avoid bus contention, and on a cycle-accurate core
the MCU or interrupt timing may stretch it - so the pad's counter resets before
reaching step 3.

**So this cannot be fixed by making our pad more correct. It already is.**

### What upstream actually shipped, in order

| Version | Approach |
|---|---|
| V.04 | Combo injection in `pad_io.sv` - X/Y/Z as simultaneous 3-button combos (`Y=Down+B`, `X=B+C`, `Z=A+B`), gated on `~MODE` |
| V.05 | Superseded - needed OSD 6-button mode OFF, and motion inputs were out of scope |
| current | **Cave v3** - ROM-read substitution injecting X/Y/Z directly into the game's pad struct |

Cave v3, in their `cartridge.sv`: hook the pad-read routine's `unlk/rts` at
`0xB2392` to jump to a code cave at `0x11C560`, which ORs FPGA register values into
the pad struct (P1 held `$FF7028`, just-pressed `$FF702A`; stride 0x10 per port),
mirroring the routine's own merges of ports 3/4 into 1/2. Served as ROM-read
substitution keyed on the latched `rom_addr`, gated on `paprium_quirk`. The same
cave also serves the **arcade coin chute**.

### Porting cost, honestly

This is a feature port, not a one-line fix:

- ROM-read substitution in our (Pocket-adapted, structurally different) cartridge.sv
- FPGA registers for virtual pad state plus a just-pressed edge latch
- A menu option for `vpad_en`, on a core whose menu was cut to save logic
- **ALM budget is the real risk** - the shipping build sits at 91% (16,900/18,480)

In its favour: the design is fully specified, the addresses are known, and it is
hardware-verified upstream. The arcade coin chute comes with it.

Prefer cave v3 over the V.04 combo injection. The combo version only reaches
simultaneous inputs - motion inputs such as forward-forward-B dashes stay
unreachable - and it needs the 6-button menu option turned OFF, which is a
confusing thing to ship.

## SOLVED (diagnosis): the big-enemy death is 0x1A + flag 0x0100

The capture settles it. `0x1A` was requested four times:

    word 214   SFX_PLAY 1A   flags 0000
    word 228   SFX_PLAY 1A   flags 0000
    word 258   SFX_PLAY 1A   flags 0000
    word 292   SFX_PLAY 1A   flags 0100     <- the big enemy, killed last

The flags value changed immediately before word 292, so it is genuine rather than a
stale latch. **The entire difference between an ordinary and a big enemy death is
the single flag `0x0100`.**

Three things die with this:

- **`0x1C` is not the big-enemy cue.** Absent from this capture too, as from every
  other. There is no separate cue and never was - the search for one is closed.
- **It is not half pitch.** `0x2000` appears just twice in 236 sfx commands, on ids
  `0x01` and `0x06`. Never on `0x1A`.
- **It is not a table or id problem.** The game asks for the same id both times.

### Why ours sounds like an ordinary death

We render `0x0100` as amplify - x1.25 on the running mix, following GPGX
(`l = (l * 125) / 100` inside the voice loop). So our big-enemy death is the
ordinary death very slightly louder, which is indistinguishable in play. That is
exactly the original report: "when killing bosses or large enemies the sound effect
is that of a normal enemy".

Hardware says it should sound **deeper**. Gain alone cannot do that, so **our
reading of `0x0100` is wrong or incomplete** - and GPGX is a plausible place for it
to be wrong, since its Paprium support is reverse-engineered. We already had to
replace MAME's guessed `0x81` decoder for the same reason.

### Blast radius, if the reading is wrong

`0x0100` appears on 15 of 83 sfx requests, across ids `01, 08, 1A, 23, 40, 7D`,
with `7D` alone accounting for 9. So this is not an obscure corner - if the flag is
mis-rendered, a number of sounds are subtly wrong in the same way, and fixing it
should be broadly audible.

### Next step: MEASURE it, do not guess

The tester has original hardware. A short recording of **an ordinary enemy death and
a big enemy death**, from the cartridge, settles what `0x0100` does without a single
build:

    same pitch, ~25% louder        -> GPGX is right and something else is wrong
    exactly half frequency, 2x long -> it is a rate change; render it like 0x2000
    some other ratio                -> read the ratio off the recording directly

ffmpeg plus the existing analysis tooling can measure the ratio directly. Guessing
in RTL would cost a build per attempt and change 15 sounds each time; one recording
answers it outright.

Also fixed here: `decode_cmdlog.py` still labelled ECHO and AMPLIFY
"(unimplemented)" long after both were implemented in RTL, which is actively
misleading when reading a capture.

## DECIDED: no 6-button support; the option is removed

Superseding the porting to-do above - **not doing it, and the menu option is gone.**

The option never worked. Paprium's pad read is a 3-button read that bails after one
TH toggle, so X/Y/Z/Mode did nothing whatever the setting said. Presenting a control
that does nothing is worse than not presenting it.

Tying `cfg_6btn` low also lets the fitter drop real logic in `pad_io`, on both
ports: the `JCNT` state machine, the ~1.5 ms `JTMR` counter (`11600*7`, 17 bits) and
the extra protocol frames. On a core at 91% ALM with the elevator work still to
land, that matters more than an inert checkbox.

**This does not foreclose the proper fix.** Upstream's cave v3 injects X/Y/Z
straight into the game's pad struct by ROM-read substitution, bypassing the pad
protocol entirely - so it never needed `pad_io`'s 6-button support and would not
need it restored. If it is ever ported, the option comes back with it.

The game plays fully with three buttons, which is how it reads the pad.


## Platform artwork: the Pocket's .bin format, decoded

Worked out by decoding Analogue's own files, since the format is not documented
anywhere we could find:

    521 x 165 pixels, 16bpp RGB565 LITTLE-ENDIAN   ->  exactly 171,930 bytes
    stored COLUMN-MAJOR, as a 165-wide x 521-tall buffer

**The column-major part is the trap.** The byte count matches 521x165x2 exactly, so
it is tempting to write it row-major - and that produces horizontal streaks rather
than an obviously wrong image, which is the kind of failure that gets shipped. Read
as 165x521 and rotated -90, Analogue's files resolve into clean console art.
Writing is the inverse: rotate the finished 521x165 artwork +90, then emit
row-major.

Verified by round-tripping our own output back through the decoder used on
Analogue's files, rather than by inspection alone.

Also worth knowing: **every stock platform image is monochrome blue on black.** A
colour or greyscale image is legible but visibly different from the rest of the
list. `scripts/make_platform_image.py --blue` renders in that house style; the
default conversion is faithful to the source.

### Producing ours

    python scripts/make_platform_logo.py <keyart.jpg>         pkg/pocket/Platforms/_images/paprium.bin

**The logo alone, colour-keyed off its background.** In the key art the logo is a
single flat magenta, `#FF006A`, which keys out exactly - so the glyphs and the
cross lift with nothing attached: no sky, no cityscape, no character, and no crop
rectangle showing against the canvas.

Two things a crop cannot do:

- **Search the logo's own region first.** The character sprites contain the same
  magenta, so keying the whole image drags them in - the naive bounding box comes
  out 1188x656 instead of the logo's real 941x264.
- **Produce a mask**, so the background is true black by construction rather than
  by thresholding something that was merely nearly black. Every earlier attempt
  showed a faint rectangle where its crop met the canvas.

Rendered bright on black, which is the house style and holds against the menu's
white background - the light version washed out there.

### Superseded approaches, kept for the reasoning

A composite of character plus logo (`make_platform_composite.py`) and single-source
crops (`make_platform_image.py`, with `--fit` to letterbox) both work and are still
in the tree. They were superseded because a 768x768 character cannot fill a 3.16:1
frame - scaling him to fill keeps ~32% of his height, a band through his chest -
and any crop drags its own background along with it. The colour key sidesteps both.

Channel choice still matters if either is used again:

- **A white-ground source needs `--invert`**, or the background becomes the
  brightest thing on screen - backwards from every stock image.
- **A saturated logo needs `--value`, not luminance.** Magenta has high HSV
  brightness but low luminance, so plain greyscale renders it dim.

`scripts/make_platform_image.py` remains for single-source images and gained
`--fit` (letterbox instead of centre-crop) for sources whose aspect is nowhere
near the frame's.

Shipped from the pixel-art key art (logo plus the three characters). **The source
image is deliberately NOT in the repo** - it is WaterMelon's artwork, and this
project does not carry game-derived material. The generated 171,930-byte
`paprium.bin` is committed because the core needs it; the crop parameters above
make it reproducible from any copy of the same 1280x720 art.

Three lessons, all learned by looking at the result rather than reasoning about it:

1. **Crop to the logo.** Analogue's images are a logo or a console render on black.
   A full-bleed painted banner scaled to 521x165 stays busy and reads as mush at
   that size, whatever the colour treatment.
2. **Invert when the source is dark-on-light.** Paprium's logo is black text on a
   pale sky, so a straight luminance-to-blue map puts the artwork dark on a bright
   ground - backwards from every stock image, and the logo reads as a hole.
3. **Match the aspect in the crop, not the resize.** The frame is 3.158:1; the crop
   above is 3.155:1, so nothing of the tagline is lost to centre-cropping.

### Why the full banner is not inverted, though the logo crop was

The source pulls both ways: the logo is dark text on a pale sky, while the
characters are light-toned against darkness. Whichever way luminance maps to blue,
one of the two reads bright and the other reads dark.

- **Not inverted** - characters render correctly (dark linework, proper faces) and
  the logo stays legible as dark text on a bright ground. Background is bright,
  which is backwards from the house style, but it looks like the artwork.
- **Inverted** - the logo is bright and correct, but the characters come out as
  photo negatives: light hair, inverted faces. Obviously wrong.

**Settled on hardware: inverted.** Judged in previews the un-inverted version looks
more faithful, but the Analogue menu draws platform art on a WHITE background, and
there the un-inverted image is too light and washes out against it. The inverted
version has enough dark area to hold its own.

A preview on a dark editor background is therefore misleading for this decision -
the only test that counts is the menu itself. The negative-look characters are the
accepted cost.

### Why the pixel-art source beats the painted banner

The painted banner fought the format; this one fits it:

- **Already bright-on-dark**, which IS the house style, so no `--invert` is needed -
  and it keeps enough dark area to hold against the Analogue menu's WHITE
  background, the exact failure of the un-inverted banner.
- **`--value`, not luminance.** The magenta logo has high HSV *brightness* but low
  *luminance*, so a normal greyscale conversion left it dimmer than the near-white
  pixel art beside it. Mapping V keeps saturated artwork as prominent as it looks.
- **Aspect forces a choice.** 1280x720 is 1.78:1 against a 3.158:1 frame, so about
  half the height goes. Framing high keeps the whole logo and the characters' upper
  bodies; framing lower cuts the logo in half. No crop holds both in full.

## 0xF2 mute: no effect. The lead is the STREAM POSITION, not the decoder

Hardware: elevator unchanged with `cmd_F2_unpack` muted. So `0xF2` is not the cause,
and MisterPezz82's recommended probe is answered - negatively, but answered.

In hindsight the null result is consistent with krikzz's own comment calling `0xF2`
the **sprites test menu** unpack: if it never fires during normal play, muting it
could not change anything.

### What the block DMA actually depends on

Reading `ppm_vram_load_block` closely:

```c
ppm_block_unpack_addr = 0x9000;                       // reset once
...
ppm_unpack(ppm_block_addr(num), ppm_block_unpack_addr);
ppm_block_unpack_addr += 0x200;                       // each block to the NEXT slot
dma_entry->srcH = 0x9700; srcM = 0x9660; srcL = 0x9500;   // every DMA reads 0xC000
```

Every block is unpacked to a **different** address, yet every DMA reads the **same**
address. That only works because the `0xC000` window streams **linearly** - reading it
advances the position. MisterPezz82 established this is what the game expects: they
implemented GPGX's paged model instead, the elevator was unchanged and boss
animations regressed, and they rolled it back.

**So the block DMAs depend on the window position not being disturbed between the
unpack and the DMA.** The DMAs are queued for the 68000 to execute later, so what
matters is the position at execution time, not at queue time.

### And 0xDA disturbs it

```c
void cmd_DA_unpack() {
    u32 src = (cmd_args[1] << 16) + cmd_args[2];
    u32 dst = cmd_args[0];
    ppm_unpack(src, dst);
    FPGAIO->sdram_ptr = ppmio.ramdp->cmd_args[0];   // optional ?
}
```

**krikzz marked that line `// optional ?` himself** - he was not sure it belonged.

If the game issues `0xDA` between queued block DMAs, the stream position jumps and
the pending DMAs fetch whatever now sits at the new offset: **real decompressed
graphics delivered into the wrong block slots.** That is precisely the reported
symptom - recognisable game sprites scrambled into the wrong place, with the scene
underneath rendering and playing normally, because game state is untouched.

A second argument: **`0xDB` exists solely to set that pointer**
(`cmd_DB_set_dma_ptr`). A dedicated command for the job makes `0xDA` doing it as
well redundant - and a redundant pointer write is exactly what desynchronises a
linear stream.

### The probe

Drop one line - the one its author already doubted:

    // FPGAIO->sdram_ptr = ppmio.ramdp->cmd_args[0];   // optional ?

Risk, stated plainly: if the game does rely on `0xDA` leaving the pointer at the
decoded data, reads afterwards will come from the wrong place and something else
breaks. `0xDB`'s existence argues against that, but it is a real risk and the test
is what settles it.

Worth pairing with a capture that logs `0xDA`/`0xDB` against `0xAE`/`0xAF` frame
boundaries, to see whether `0xDA` really does land mid-frame while blocks are
queued. That would confirm the mechanism rather than just its removal.

## PROBE A RESULT: 0xDA's pointer write is LOAD-BEARING. Reverted.

Hardware, with `FPGAIO->sdram_ptr = cmd_args[0]` dropped from `cmd_DA_unpack`:

    cell room   background GLITCHED  (it was clean before)
    intercom    glitched
    elevator    unchanged, scrolling sprite squares still present

So the freeze **regressed** the game and did not help the elevator. Reverted.

### What that establishes

Despite krikzz marking the line `// optional ?`, and despite `0xDB` existing
solely to set that pointer, **the game genuinely relies on `0xDA` leaving the
stream pointer at the decoded data.** `0xDA` is a real consumer of the window, not
a stray write. That is a fact worth having: it was a reasonable hypothesis, it was
cheap to test, and it is now closed.

It also matches the reviewer's middle row - "0xDA is a real consumer; freeze
desyncs later DMA -> do not ship the freeze, go to dest capture / decoder_ram."

### What it does NOT establish

The elevator was unchanged, so this scene is not pointer disturbance **by 0xDA**.
It says nothing about `0xDB`, which also writes the pointer and was never touched.
An unchanged elevator does not clear the window.

Note the two commands do not even share an argument convention:

```c
0xDB:  sdram_ptr = swapshorts(cmd_args_long[0]);   // full 32-bit, byte-swapped
0xDA:  sdram_ptr = cmd_args[0];                    // bare 16-bit, zero-extended
```

`sdram_ptr` is `vu32`, so `0xDA` can only ever place it in 0x0000-0xFFFF, while its
own `src` is assembled as a full 32-bit value. A capture must therefore decode each
command's arguments its own way - decoding both alike would put every `0xDB`
destination in the wrong half of the map.

### Next: Probe B, the destination capture

Filter the logger to `0xDA` and `0xDB` only, record raw words, and bucket each
destination:

    0xC000-0xFFFF   stream window     -> collision with live VDP DMA plausible
    0x9000-0xBFFF   block staging     -> collision with prior tiles plausible
    mailbox / low   control, ignore
    0xF800+ / tile 1984+   leftover table smash even at budget 49

One destination in the window during the INTERCOM scroll keeps the disturbance
theory alive. Destinations only ever in the workspace kill it and leave
`decoder_ram` / buffer reuse as the live lead.

## Probe B design, and a correction to the address-space assumption

A reviewer flagged that `0xDA` and `0xDB` must not be bucketed against one map,
since they use different argument conventions. Correct on the decoding. But
checking `ppm_unpack` shows **both destinations live in the SAME space, and it is
neither a 68000 address nor 0x800000**:

```c
uint32_t ppm_unpack(uint32_t source_addr, uint32_t dest_addr)
    unpacked_data = (uint8_t *) ppmio.sdram;     // dest_addr INDEXES this
...
cmd_F2:  ppm_unpack(..., 0x9000);  FPGAIO->sdram_ptr = 0x9000;   // same value both
blocks:  ppm_unpack(..., ppm_block_unpack_addr);                  // 0x9000 + n*0x200
```

`dst` and `sdram_ptr` are both **offsets into the SDRAM workspace**, and `cmd_F2`
passes the identical value as both - so they index one space. `0xDB` is 32-bit and
half-swapped, `0xDA` is a bare 16-bit, but they address the same thing.

### That makes the test more sensitive, not less

There is no fixed "window region" in SDRAM - the window is wherever `sdram_ptr`
points. So bucketing against `0xC000-0xFFFF` would test the wrong thing. What
matters is the **block staging range**, which a decode landing in would corrupt
directly:

    0x9000 + 49 blocks * 0x200  =  0x9000 - 0xF1FF    (at the shipped cap of 49)
    0x9000 + 53 blocks * 0x200  =  0x9000 - 0xF9FF    (uncapped)

**CORRECTION: being in the staging range is not itself a collision.**
`0x9000 + n*0x200` is exactly where blocks are supposed to land, `cmd_F2` parks the
pointer at `0x9000` deliberately, and Probe A proved the game wants the pointer left
on the decoded bytes. Flagging the whole range would have called the happy path a
bug.

A hit matters only if it is the **wrong kind** of write:

| Dest | Meaning |
|---|---|
| `0x9000 + n*0x200`, n < 49, aligned | Normal block unpack. Ignore |
| Inside staging, **not** 0x200-aligned | **Overlap** - can smear two blocks |
| Inside staging, aligned, but n is a live slot not being rebuilt | **True collision** - the tile-corrupt case |
| Below `0x9000` | Private / decoder scratch. Interesting only if `sdram_ptr` is left there while the VDP still consumes |
| >= `0xF200` | Outside the 49-block arena; pointer moved off staging |

So each in-range destination is reported as `cmd, raw, dest, n, aligned?`, where
`n = (dest - 0x9000) / 0x200`. Slot liveness is not visible from the 68000 side, so
the third row is detected by correlation - a slot rebuilt repeatedly while still
on-screen - rather than directly.

`0xDB`'s two reconstructions are both printed and the data picks the endianness -
one should cluster in plausible workspace, the other look like noise.

## If Probe B is clean: REMAP, do not raise the cap

The residual "scrolling sprite squares" after cap-at-49 is exactly what a 16-tile
block cache looks like when it is too small: a still-visible block is evicted, the
stale pattern stays mapped, and the shaft scroll carries the square with it. Probe
B does not measure that - a clean dest capture only proves the decode is not
landing on staged tiles.

The fix is to give the four blocks back **somewhere safe**, not to restore the
collision:

    current  slots 0-48   -> block indices 1-49    -> tiles 16-799   -> 0x0200-0x63FF
    REMAP    slots 49-52  -> block indices 50-53   -> tiles 800-863  -> 0x6400-0x6BFF

which is simply dropping mega-ppm's two-range special case and using `x + 1`
throughout. Still far below the usual nametable floor, and it never touches
`0xF800-0xFFFF`.

If the squares shrink or vanish, the residual was LRU pressure. If they stay and a
nametable or window tears instead, that hole is not empty on Paprium and the next
slice further up gets tried - still below `0xC000`. **Do not** jump to tiles
1920-1983; that is against the same high-VRAM tables we just stopped hitting.

Note the headroom this opens if it works: a linear `x + 1` mapping stays below
`0xC000` all the way to block index 95, i.e. **95 slots against today's 53** - but
only as much of that hole as testing proves is actually free.

## SETTLED: tying cfg_6btn off COST 1,151 ALMs

Controlled experiment, three builds:

| Build | ALMs | Worst slack | TNS |
|---|---|---|---|
| 6-button tied off | 18,051 (98%) | -2.666 | -1,559 |
| same, clean db/incremental_db wipe | 18,051 (98%) | -2.666 | -1,559 |
| **6-button RTL restored** | **16,900 (91%)** | **-2.539** | **-1,201** |

Exact recovery of ALMs, timing and TNS. So the tie-off genuinely cost 1,151 ALMs
**while verifiably removing the logic** - `JCNT` and `JTMR` appear zero times in the
tied-off build's fit report. Counterintuitive, reproduced twice, and not fitter
noise: the clean-wipe rebuild was identical to the digit.

`mcu.txt` was eliminated as a cause for free along the way - the 0xDA probe changed
the firmware and produced an identical 18,051.

**The menu entry stays removed.** The option never did anything, since Paprium's pad
read is a 3-button read, so the register simply sits at its default. Menu presence
and RTL cost are independent.

Lesson worth keeping: **tying a signal off is not automatically an area win.** Verify
by measurement, not by reasoning about what the fitter should do.

## Core icon: the logo's actual cross

`pkg/pocket/Cores/Koala_Koa.Paprium/icon.bin` was a solid plus with a **spike out
to the right** - the signature of a hand crop that caught part of the adjacent
letter. Paprium's cross is not a plus at all: it is a Latin cross with a **hollow
centre** and a long lower stem.

Rebuilt by the same colour key as the wordmark (`scripts/make_core_icon.py`): the
logo is a flat `#FF006A`, so the glyphs isolate exactly, and the cross is cut at
the last run of empty columns - the gap between the M and the cross - rather than
by eye.

**The icon format is NOT the platform-image format**, which cost a moment to
establish:

    icon.bin      36x36, RGB565 LE, ROW-MAJOR
    platform .bin 521x165, RGB565 LE, COLUMN-MAJOR

Verified by decoding the shipped icon both ways - only row-major renders upright.
Colour matched to the shipped icon exactly: `0x00FF`, rgb(0,28,255) on black.

The previous icon is kept at `build_output/icon_old_backup.bin`.

## PROBE B RESULT: decode is clean. Remap, do not add a private buffer

Capture: 1,223 `0xDA`/`0xDB` commands, 27,807 mailbox commands as the control.

    unaligned_da = 0        every real unpack destination is 0x200-aligned
    0xF2         NEVER FIRED in any of the 20 scene fences
    0xEC peak    53         the REQUEST - cap-at-49 was clamping INTERCOM

**Destination collision is dead.** The decode path lands exactly where blocks
belong, so a private unpack buffer (`decoder_ram`) would fix nothing.

### A false positive of ours, corrected

The decoder first reported **168 unaligned destinations**, all of them `0xDB`. That
was a classifier bug, not a finding: `0xDB` is `cmd_DB_set_dma_ptr`, which **sets a
read pointer and unpacks nothing**. Block-grid alignment is meaningless for it -
the game may point the window wherever it likes. Applying the unpack test to a
pointer-set command produced a confident result pointing straight at `decoder_ram`,
which is exactly the wrong direction.

`0xDB` rows now read `algn=n/a`. Its volume also scales with the budget-53 scenes
(F10 464, F18 187, F20 376, against 4 in a budget-29 scene) with `+0x40` walks and
`-0x80` rewinds - which is what a long stream looks like, not corruption. Do not
freeze it; `0xDA` already proved these pointer writes are load-bearing.

### The remap

Cap-at-49 helped only because slots 49-52 took the `+0x4b` jump onto tiles
1984-2047 (`0xF800-0xFFFF`) - the sprite attribute and hscroll tables. But capping
cost four blocks of cache while INTERCOM asks for all 53, so the residual squares
are small-cache pressure: a still-visible 16-tile square is evicted and scrolls
with the shaft.

Give the four slots back in the hole the two-range map skipped, rather than
restoring the collision. Linear `(x + 1)` throughout, cap back to `0x35`:

| Slots | Block idx | Tiles | VRAM |
|---|---|---|---|
| 0-48 | 1-49 | 16-799 | `0x0200-0x63FF` (unchanged) |
| 49-52 | 50-53 | 800-863 | `0x6400-0x6BFF` (was `0xF800-0xFFFF`) |

Top of the new range is `0x6BFF`, still far below the usual `0xC000` nametable
floor.

**Read the result as:** squares shrink or vanish -> LRU confirmed. A nametable or
the window tears -> `0x6400-0x6BFF` is not empty on this game, and the next slice
to try is tiles 864-927, still below `0xC000`. **Do not send them back to
`0xF800`.**

Built on a shipping-timing bitstream, not the 99% logger. Smoke boot -> cell room
-> doorway before trusting INTERCOM.

### If INTERCOM is unchanged after a clean smoke

Do not try another tile slice yet. The next suspect is `ppm_vram_load_block`
returning 0 on `dma_remaining < 0x110`, which evicts the same way LRU does and
would survive a perfect remap.

The remap makes that path **more** likely, not less: 53 blocks demand more DMA per
frame than 49.

```c
void ppm_obj_frame_end() {
    ppm_block_unpack_addr = 0x9000;                       // staging restarts each frame
    ppmio.ramdp->dma_remaining = ppmio.ramdp->dma_budget - ppmio.ramdp->dma_total;
```

`dma_budget` is **never written by the firmware** - the game sets it, and mame.h
calls it "per frame budget (depends on system)". So the per-frame FILL RATE is
capped at `(budget - total) / 0x110` blocks, independently of how many SLOTS exist.

Two separate constraints:

- **slots** - how many blocks stay resident, i.e. how often eviction happens
- **DMA budget** - how many can be loaded per frame

The remap raises the first and does nothing to the second. If INTERCOM is DMA-bound
rather than slot-bound, it will look identical afterwards, because a block that
fails to load returns 0 from `ppm_vram_find_block` exactly as an evicted one does.

**But it does NOT need a new instrument.** Checked before costing one: two of the
three DMA fields are written by the GAME, in the same 68k-visible RAM the logger
already snoops.

    dma_total      0x1F10   never written by firmware -> game-written  (wr_word 0xF88)
    dma_budget     0x1F12   never written by firmware -> game-written  (wr_word 0xF89)
    dma_remaining  0x1F14   firmware-written          -> MCU-private, invisible

The addresses come from the struct naming itself: `unk_1f1a` fixes 0x1F1A, and
`cmd_args[128]` starting at the confirmed 0x1E10 runs to 0x1F0F, so the two meet
exactly at `dma_total` = 0x1F10.

`dma_remaining` is only ever `budget - total`, recomputed each frame in
`ppm_obj_frame_end`, so it can be reconstructed rather than snooped. That gives the
decisive number:

    blocks fillable per frame = (dma_budget - dma_total) / 0x110

If that is below what INTERCOM needs, the scene is DMA-bound and the four extra
slots cannot help.

So this is a **filter change** - the same kind as adding `0xEC` - not a 98% feature.
Likely dedup'd to on-change, since the budget probably moves only per scene, which
pairs it naturally with the `0xEC` fences already in the ring. A `ramdp_io` counter
is only needed if that reconstruction turns out to disagree with the symptom.

### Units, reconciled before the measurement

`0x110` per block reconciles cleanly, which matters because it fixes the units of
any snooped budget:

    dma_entry->lenH = 0x9401; lenL = 0x9300;   // VDP length 0x0100 WORDS
                                               // = 512 bytes = 16 tiles
    dma_remaining -= 0x110;                    // 0x100 payload + 0x10 overhead

The `0x10` is the entry's own register writes (autoinc, lenH/L, srcH/M/L, cmdH/L),
rounded up. `dma_total` is documented as "total size in words", and the payload is
0x100 words - the two agree.

**Pre-registered expectation, so the result is not fitted afterwards.** A real NTSC
vblank moves roughly 7.5 KB to VRAM, about 3,800 words, i.e. **13-14 blocks per
frame** - not 53. A full 53-slot refill would take about four frames.

| snooped `budget - total` | reading |
|---|---|
| ~3,000-4,000 words | plausible; fill rate ~13-14 blocks/frame and the likely leftover |
| much above 14,416 (53 x 0x110) | **units are wrong**, not the budget generous - reconcile first |
| well under 3,000 | tighter than hardware allows; the game is being conservative |

This also means the shaft symptom is explicable with **no collision at all**: if the
scroll demands more than ~14 new blocks in a frame, the rest fail on
`dma_remaining < 0x110`, return 0, and render as stale squares - and more slots
would not change that.

### PRE-REGISTERED: the remap makes two separate claims

Written before the hardware result, so a partial outcome is not read as a failure.

**Claim 1 - correctness. Already proven, independent of the shaft.** Slots 49-52
must not sit on `0xF800-0xFFFF`, the sprite attribute and hscroll tables.
Cap-at-49 established that by removing the collision and visibly improving the
elevator. The remap keeps those four blocks *without* the collision, so it is
strictly better than the cap whatever the shaft does.

**Claim 2 - the visible shaft. Conditional.** The leftover squares vanish only if
INTERCOM is **slot-bound**. If it is **fill-bound**, more residents do nothing and
the squares stay.

Both were written on the belief that hardware had shown cap-at-49 improving the
elevator (collision removed) while leaving scrolling squares (churn remaining).
**That premise was withdrawn on 2026-08-31** - see "cap-at-49 has lost its
justification" below. The tester's report is that capping made it feel the same or
similar, not noticeably better.

    clean doorway + shaft improved   -> slot-bound. LRU confirmed, done
    clean doorway + shaft UNCHANGED  -> A RESULT, NOT A FAILED REMAP. Claim 1 stands;
                                        claim 2 is refuted, and INTERCOM is fill-bound
    doorway wrong                    -> 0x6400-0x6BFF is NOT free on this game

**On an unchanged shaft, do NOT slide the window to tiles 864-927.** Measure
`budget - total` against ~3,800 words first. Sliding would be treating a refuted
residency hypothesis as a mapping problem.

Treat "13-14 blocks/frame" as a **band, not a spec**: display-on fetches, 68000 bus
traffic and the SAT DMA all draw on the same budget. The prediction that survives
regardless is that a 53-block refill cannot happen in one vblank.

## REMAP REFUTED: tiles 800-863 are NOT free - the game owns them

Hardware, cap restored to 53 with a linear `(x + 1)` map putting slots 49-52 at
tiles 800-863 (`0x6400-0x6BFF`): **the cell-room floor glitched immediately.** The
residency canary fired a room earlier than the doorway. Reverted; `61d1ddd3`
(cap-at-49, two-range map) is back on the card.

### The arithmetic says what it is

A 32x32 nametable at `0x6400` is `0x800` bytes = **tiles 800-863 exactly** - the
range the remap wrote patterns into. A floor built from that plane would break in
the cell room and nowhere else first, which is what happened.

**So mega-ppm's `+0x4b` jump is deliberate, not an artefact of a partial
reverse-engineering.** The gap it skips is not spare VRAM; the game already owns it.
An earlier entry here read that gap as "1,184 unallocated tiles" and treated it as
headroom. That was wrong, and the correction is the useful part: *the map skips
those tiles because they are in use.*

### What is isolated by this

    cap-at-49, two-range map   cell room CLEAN
    53 slots at 0xF800         cell room CLEAN  (elevator corrupt)
    53 slots at 0x6400         cell room BROKEN

Only the placement changed between the last two, so the failure is **the address,
not the extra four blocks**.

### What is NOT established

**INTERCOM is not an untested LRU case.** The remap never became a valid slot-bound
experiment - it broke before the shaft was reached. Slot-bound vs fill-bound remains
open.

### If the four blocks are still wanted

Do **not** retry tiles 864-927. If the map is 64x32 it spans `0x6400-0x73FF` =
tiles 800-927, and that slice is still inside it.

- **Cheap discriminator:** a ONE-SLOT write at tile 864 (`0x6C00`). Floor dies ->
  64x32. Floor lives -> 32x32, and 864-927 is usable.
- **Otherwise** tiles 928-991 (`0x7400-0x7BFF`), which clears both a 32x32 and a
  64x32 map based at `0x6400`.

But the cheaper question first: an unchanged shaft still means logging
`0xF88`/`0xF89` and comparing `budget - total` against ~3,800 words. If INTERCOM is
fill-bound, the four blocks were never going to matter and none of this placement
work is needed.

## ANSWERED STATICALLY: INTERCOM is fill-bound. dma_budget is in the ROM

The DMA ceiling did not need a logger at all. `dma_budget` is written by the game
from two immediate constants, findable in the ROM:

    0310A2:  2079 000A F83C     movea.l $000AF83C,a0        ; a0 = cart-RAM base
    0310A8:  317C 0B00 1F12     move.w  #$0B00,($1F12,a0)   ; dma_budget = 2816
    0310AE:  0C39 0032 00FF99B5 cmpi.b  #$32,$00FF99B5
    0310B6:  660E               bne.s   $310C6
    0310C0:  317C 1200 1F12     move.w  #$1200,($1F12,a0)   ; dma_budget = 4608

`317C` is `move.w #imm,(d16,A0)`, and the base long at `0xAF83C` is **0x00000000** -
a value from the address table already dumped at `0xAF810`. So `ramdp` is at 68000
address 0 and `0x1F12` is `dma_budget`, exactly as the struct predicted.

| | words | blocks/frame at 0x110 |
|---|---|---|
| default | 2,816 | **10** |
| conditional | 4,608 | **16** |

Minus `dma_total`, so real headroom is lower. **Against 53 slots the ceiling is
10-16.** This brackets the pre-registered ~3,800-word vblank band, so the units are
confirmed as words.

`$FF99B5` is **not identified**. `$32` is 50, so 50 Hz is plausible but unproven -
the byte is `clr.b`'d at `0x0810EC` and read at `0x08CD50` with no direct
`move.b #$32` store, so it is set indirectly. Do not label the branch. It does not
affect the verdict: both constants are far below 53.

### Verdict

**INTERCOM is fill-bound under mega-ppm's allocator.** 53 resident slots cannot be
refreshed in one vblank at any slot count we can give it. Cap-at-49 remains
shipping.

The leftover squares are fully compatible with: shaft churn exceeds ~10-16 new
blocks per frame -> `dma_remaining < 0x110` -> `ppm_vram_load_block` returns 0 ->
`ppm_vram_find_block` returns 0 -> a stale 16-tile square that scrolls with the
shaft.

**Qualification, so this is not read as cleaner than it is:** slots and fill rate
are not independent. More residents mean less churn and so less DMA demand, so the
four blocks could have reduced pressure - they simply cannot raise a 10-16 block
ceiling to 53.

The original MAX 10 may look cleaner on the same scene because it can pack or DMA
at finer grain than a fixed 16-tile, `0x110`-word charge.

**That is a POLICY difference, not a hardware one, and it is not a route.** The
Pocket is a Cyclone V - wrong family for a MAX 10 bitstream - and the Datenmeister
bitstream has never been dumped; it is still inside an epoxied 10M02. There is no
file to instantiate and no reverse-engineered command set to reimplement. What is
missing is the packing and DMA policy, not a chip. GPGX looks cleaner for a
different reason again: emulated VRAM writes are free. EverDrive Pro, MiSTer and
Pocket all push the real VDP pipe.

So the leftover is an **allocator** problem.

### Stop conditions

- **No more dmalog builds for this question.** Four failed the timing gate; the
  answer was in the ROM the whole time and should have been looked for first.
- **No tile-864 or 928-991 slide to "fix INTERCOM".** Placement probes stay queued
  and need a different justification than "maybe four more slots help".
- The `dmalog3` hold failure (-0.004, a single 4 ps path) is congestion plus a
  rounding miss. Leave it; the bitstream is not needed.

### Cheap follow-up, later

Identify `$FF99B5` and which branch this core takes. An Export/NTSC default may
lock us to `0x0B00` = 10 blocks/frame, which refines the band. It does **not**
reopen remapping.


## What could still change the squares - and what cannot

**Cannot:**

- Emulating the MAX 10 as a core-in-a-core. No bitstream, no RE of its command set,
  wrong FPGA family.
- Raising the slot cap into nametable space. `0x6400-0x6BFF` is live; the rest of
  800-1983 is **unknown, not free**. Guessing that range is what broke the
  cell-room floor.
- More cmdlog builds to re-measure `0x0B00` / `0x1200`. That is settled in the ROM.

**Could, in rough order of promise:**

1. **Stop rendering a miss as garbage - with a reserved MISS_BLOCK, NOT by
   blanking tiles 0-15.**

   On a miss `ppm_vram_find_block` returns 0, so `tileIdx = 0 + spr_data->offset`.
   That does **not** land on tile 0 - it lands anywhere in tiles 0-15 depending on
   the offset. On a real Genesis tile 0 is often the blank cell but 1-15 commonly
   hold font, HUD or the first pattern row, so **a miss may already be drawing the
   game's own tiles, and that may be the garbage we see.**

   Blanking 0-15 because "the allocator never uses them" is the 800-1983 mistake
   again: the allocator not using a region does not mean the game does not.

   The safe version does not need that question answered at all:

   - reserve one slot inside the allocator's own range as `MISS_BLOCK`
   - fill it blank once at init
   - a miss returns **that block's base**, not 0

   Cost is 48 residents instead of 49; the fill ceiling is unchanged. Every miss
   then becomes a hole in our own patterns rather than a stab at the game's tile 0.

   If someone still wants to know whether 0-15 are live, the checks are: do the
   cell-room and INTERCOM plane maps contain tile indices 0-15, does the SAT use
   them, and does a VRAM peek of patterns `0x0000-0x01FF` come back zeroed
   (interesting) or font-shaped (a veto). But `MISS_BLOCK` makes that optional.

2. **Charge by dirty tiles, not a fixed block.** A block costs `0x110` = `0x100`
   payload + `0x10` setup regardless of how many of its 16 tiles actually changed.
   Sizing honestly: merging consecutive blocks into one DMA saves `0x10` per block
   after the first - roughly one extra block out of ten, ~10%. Charging by dirty
   tiles could save far more, but only if the workload really is partial-block, and
   that is unmeasured.

3. **Take the 4,608-word branch** if `$FF99B5` turns out to be a mode flag we can
   satisfy: 16 blocks/frame instead of 10. Will not reach 53, may cut the worst
   frames.

4. **Pack into genuinely free VRAM** - but only once the nametable map is *known*,
   not guessed.

Note 1 and 2 are different in kind: 1 makes the failure **look like absence**, 2
makes it **rarer**. Neither needs a chip we do not have.

**Sequencing:** before spending effort on 2, measure whether INTERCOM's misses are
whole 16-tile blocks. If they are, merging consecutive DMAs saves only the `0x10`
setup per extra block and will not change the scene.

**Expectation for 1, stated plainly:** it is cosmetic. The misses still happen at
the same rate - the shaft would show empty cells instead of stale shaft. That may
look better or worse, and it is worth deciding whether that is wanted before
building it.

### A SECOND stale path, found while implementing MISS_BLOCK

A failed **load** never reaches `find_block` at all:

```c
if (!ppm_vram_load_block(spr_data->blockNum)) blocks_available = false;
...
if (!blocks_available) { if (previous_offset) { /* restore offset/counter */ } }
```

The object re-renders its **previous animation frame** instead. So there are two
independent sources of a stale appearance:

1. `find_block` returning 0 on a lookup miss -> draws tiles 0-15 + offset
2. `load_block` failing -> the object repeats its previous frame

`MISS_BLOCK` only addresses (1). If the shaft looks identical afterwards, (2) is
the mechanism - which fits a scrolling scene better anyway, since a repeated
animation frame carried along by the scroll is exactly "a stale 16-tile square
that scrolls with the shaft".

### The two paths, and what MISS_BLOCK discriminates

| Path | What you see | Under MISS_BLOCK |
|---|---|---|
| `find_block` returns 0 | tile 0 + offset - font, HUD or junk | **holes**, if the blank fill landed |
| `load_block` fails -> `previous_offset` | the last good animation frame, scrolling with the object | **no change** |

The second is the better match for a moving shaft: the cell stays a shaft tile,
just the wrong one, and it rides the scroll. **So an identical INTERCOM is a
POSITIVE IDENTIFICATION, not a dead experiment** - it isolates path 2 by
elimination.

**One variable.** The fallback is deliberately NOT changed in this bitstream.

If it turns out to be path 2 and holes are still wanted, that is a separate patch:
on `load_block` failure render `MISS_BASE + offset` instead of restoring
`previous_offset`. Only after this look shows the squares survived - and note it is
a bigger behavioural change, since the fallback exists to keep objects coherent
when their blocks cannot load, not merely to hide a miss.

## MISS_BLOCK RESULT: path 2 confirmed. Reverted.

Hardware: **the elevator behaves exactly as before.** Per the pre-registered
discriminator that is a positive identification, not a dud.

`MISS_BLOCK` never ran on those squares. `ppm_vram_load_block` failed,
`blocks_available` went false, and the object redrew with `previous_offset` - its
last good animation frame - which then rides the scroll. That path never reaches
`ppm_vram_find_block`, so blanking the miss target could not change it.

    residual elevator = fill-bound (10-16 blocks/frame) + previous-frame fallback
    NOT find_block == 0

**Reverted**, and removed rather than left behind an `#if 0`: it cost a resident
slot (48 instead of 49) and did no work. Firmware back to 4,191 words, matching
`61d1ddd3`. The full implementation is in git - "EXPERIMENT: reserved MISS_BLOCK
for cache misses" (163076b) - which is the right archive for it.

**The `0xF800` fix (cap-at-49) remains the real shipping change.**

### The pin itself was harmless - which de-risks the follow-up

Confirmed on hardware: boot, cell room, doorway and on-screen text were all clean
on this bitstream, with no new glitching. (The single missing pixel on the logo
screen is the pre-existing intro flicker, present on every build.)

So slot 48 really was spare, the blank DMA landed at the right address, and
queueing it first in the frame did **not** desync the linear stream - which was the
stated risk. That matters beyond this experiment: the pinning mechanism is proven,
so if the `previous_offset` follow-up is ever attempted it does not also have to
prove that a reserved blank block can be created safely.

### The only follow-up that would change the picture

Replace the `previous_offset` restore with the dummy block on load failure, so
wrong-but-plausible shaft tiles become holes.

That is a **behaviour change, not a presentation tweak**: the fallback exists to
keep an object coherent when its blocks cannot load. Trading a plausible frame for
a visible absence may look better or worse, and it would affect every scene that
ever misses, not just the shaft. A separate, explicit look - not folded into a
revert.

## RETRACTION: the fat-death row was inferred, not measured

The entry above reads the capture as "the game requests `0x1A` with flag `0x0100`
for a big enemy". **That identification was an inference and is withdrawn.**

Word 292 was the last `0x1A`, it carried a flag the other three did not, and the
tester killed a big enemy near the end of the run - so it was *treated* as the fat
death. Nothing in the capture marks which row belonged to which enemy. The run
contained several ordinary kills as well.

A second, independent reading of the mailbox says `0xD1 1C` never appears and the
68000 asks for a **small-enemy id**. Both claims cannot be the mechanism, and
neither is established without a single-kill capture.

### Three playback paths - do not merge them

| Path | Where | How pitch happens | Pocket |
|---|---|---|---|
| SFX table | ROM 0x25ECA4, 127 clips | `sfx[5]` rate + flags[5]/[7] skip | implemented |
| Wavbank sampler | ROM 0x1A0010 WavPack, 26 voices | STM32 clocks a slice at 48000/n | **not implemented** - the OST replaces it |
| CDDA | paprium.pcm | none | implemented |

Cart extras that "sound like the wavbank" are almost certainly path 2. A fat-enemy
death could be path 1 with `0x0100`, or path 2, or a 68000 fallback to a grunt.
**Those are different bugs with different fixes.**

### Against the bit-0-is-a-rate-bit guess

Boot sfx `0x01` was captured with flags `0x2100` - **bit 0 and bit 5 set
together**. If bit 0 were the same halver as bit 5, setting both would be
redundant. So they are probably not the same thing, and "bit 0 halves the rate"
is weaker than it looked.

### The decisive capture

One kill of a fat enemy, and the last `0xD1` before it:

    D1 1A (or 1C) + flags 0100  -> path 1; then a listen-only flags[0] probe
    D1 <small-grunt id>         -> the 68000 took a no-synth / small-enemy branch;
                                   stop touching the PCM RTL, look at object /
                                   hardware-detect fallback
    no 0xD1 near the kill       -> wavbank or a muted command; not the 8-voice engine

**Until that row exists: do not change RTL, and do not implement `0xD6`.**

### 0xD6 is not the death cue

GPGX's `paprium_music_special` is a crisis/detune poke for the 26-voice wavbank
synth. Its only "body" is a **commented-out write to `0x1E10`** - and that cell is
also the SFX channel mask, so implementing the comment can smash the next `0xD1`.
GPGX itself does nothing there. mega-ppm mutes it. This port has no MWMM engine for
it to drive. Copying GPGX would be copying a comment.

Crisis detune on cart is wavbank rate/step, not SFX `flags[0]`.

### What the wavbank means for missing extras

One recording becomes many pitches because the F446 walks `wave_ram` at
48000/{2,4,5,8,9,10}. That is how one slap becomes several notes, and how "missing"
effects exist without a new 4-bit id.

The current 8-channel engine cannot do that - it has `srate` plus three pitch
values - and CDDA will never bend those slices. **Extras that live only in the
wavbank stay missing until someone implements sampler voices, which is a new
engine, not a flag fix.**

## SOLVED: flag 0x0100 steps the SAMPLE RATE, it is not amplify

Established from hardware, and it closes the big-enemy death sound.

**The large grunt's death is the ordinary grunt's sample played slower.** The
tester identified 0.625x by ear, against pitched copies restricted to the ratios
the engine can actually produce, and then auditioned the **entire 127-entry SFX
bank** and found no separate fat-death sample. So it cannot be a different id.

    rate table:  0=48000  1=24000  2=12000  3=9600  4=6000  5=5333
    sfx 0x1A table entry -> index 3 = 9600 Hz
    index 3 + 1          -> index 4 = 6000 Hz  =  0.625x

**Flag `0x0100` steps the rate index down by one.** GPGX names that bit "amplify"
and this port implemented it as x1.25 gain, following GPGX. That was wrong.

### Why the earlier objections dissolve

- **`0x2100` on boot sfx `0x01`** - bit 0 and bit 5 together - looked like proof
  that bit 0 was not a rate bit, since two halvers would be redundant. They are not
  the same mechanism: **bit 5 is a sample-skip halver, bit 0 is a rate-index
  step.** Composing them is meaningful.
- **Gain was never it.** The fat death measures **0.90x** the grunt's amplitude -
  slightly quieter - where x1.25 would be louder.
- **The retracted capture row was right after all.** `0x1A` with flags `0x0100` at
  word 292 *was* the fat death. Retracting it was still correct at the time: the
  capture could not show which row belonged to which enemy, and the identification
  rested on position alone.

### Where the earlier analysis went wrong

Two of my own measurements pointed away from this and both were faulty:

- A log-frequency correlation reported "no shift", which would have refuted a rate
  change. **Its control failed** - it could not detect a known octave shift - so it
  could not rule one out either.
- An envelope-shape comparison said "different sample". Its control passed for
  recording-vs-recording, but ranking ROM samples against a recording failed its
  sanity check: `0x1A` did not surface for the grunt death that it demonstrably is.
  Console output stage, room and mp3 coding defeat it.

The ear test with engine-constrained ratios was the measurement that worked, and it
was cheap. Try it before building analysis tooling next time.

### The change - note this moved after it was first written

The first version did it in `rtl/PAPRIUM/audio_sfx.sv`, stepping `srate` in place
of setting `amp`. **That was reverted.** The same `+1` put an adder in front of the
aclk mux and cost 0.4 ns of setup; three fitter seeds landed between -2.72 and
-2.98, and -2.715 is measured NOT to boot.

**Shipping does it in firmware,** `mcu/sfx.c`, for zero logic. The rate index is
stepped there, and bit 0 is cleared on the way out:

    ppmio.sfx[chan_idx].flags = (flags >> 8) & ~0x01;

So the RTL is unchanged and still carries the full amplify path - `sfx.amp <=
flags[0]` and the x1.25 on the running mix are both still there. It simply never
fires, because the only bit that would assert it is cleared before the RTL sees
it. **Amplify is implemented and starved, not removed.** If the rate-step reading
is ever overturned, dropping the `& ~0x01` restores the old behaviour exactly.

An earlier version of this passage said `amp` was "tied off" in RTL. It is not -
nothing in `audio_sfx.sv` changed - and the distinction matters, because a reader
checking the RTL would find the amp path live and reasonably conclude `0x0100`
gets both a rate step and a x1.25 gain. It does not.

Affects 15 of 83 sfx requests in the capture, across ids `01, 08, 1A, 23, 40, 7D` -
so it should be audible in several places, not just the fat death. Anything that
sounds *too slow* afterwards is the signal this is wrong.

## The Boom Box sound test - a controlled trigger, and what 0x9A means

The game has an in-game sound test (Boom Box) that lists effects by id, and it
labels the large grunt's death **`0x9A`**. On this core every entry, including that
one, plays correctly.

**`0x9A` is not a second sample.** Two checks:

- The SFX table has 127 live rows, `0x00-0x7E`. Entries 128+ are invalid, and row
  `0x9A` reads `00 00 00 00 00 00 00 00` - size 0, which plays **silence**.
- `sfx_play()` applies **no mask**: `&ppmio.flash[ppm_sfx_base_addr + arg * 8]`
  uses the id directly, so a literal `D1 9A` would read that empty row.

Since it plays correctly, the Boom Box is not sending `9A` as an id. The decode is
`0x9A = 0x80 | 0x1A` - a **label** meaning "row 0x1A, deep variant" - and what it
actually sends is `D1 1A` with `flags 0x0100`.

That makes the sound test a **controlled, repeatable trigger** for the exact flag
under investigation, far better than fighting to a large grunt and hoping the ring
catches the right rows.

### The control that decides whether the fix is real

Play Boom Box `0x9A` on **stock `61d1ddd3`**, with no rate step anywhere:

| stock `9A` | meaning |
|---|---|
| normal grunt pitch | the flag is the deep switch; the firmware step is correct |
| already deep | something else retunes it in that menu, the 68000 simply never uses it in play, and the `+1` is treating the wrong layer |

**Boom Box "everything plays" does not finish the listen.** That menu likely fires
table rate only; `0x0100` appears in combat. `0x7D` is the veto - nine of the
fifteen flagged requests, and it fires constantly during a fight.

## RESOLVED ON HARDWARE: 0x0100 steps the rate index

Controlled A/B through the Boom Box sound test - same trigger, same sound, only the
build differs:

    stock 61d1ddd3        Boom Box 9A  ->  normal pitch, identical to 0x1A
    seed 4 (+rate step)   Boom Box 9A  ->  deep, matches the in-game fat death

So nothing else retunes that sound in that menu: **the deep variant is `0x0100`
stepping the sample-rate index by one**, 9600 -> 6000 Hz, the 0.625x ratio
identified by ear.

Combat on seed 4 was clean - `0x7D` and the other flagged ids unchanged - so the
step is not over-applying.

### Shipping form: firmware, not RTL

    type[6:4] += 1  when flags & 0x0100, saturating at index 5 (5333 Hz)
    hardware bit 0 cleared so the RTL amp path cannot stack
    fit IDENTICAL to 61d1ddd3 - 16,900 ALM / 294 M10K / -2.539 / -1201.155

The RTL form works but must not ship. It put an adder in front of the `aclk` mux
and cost ~0.4 ns; four fitter seeds landed at -2.70, -2.72, -2.96 and -2.98, and
**-2.715 was measured not to boot while -2.701 boots** - a 0.014 ns difference with
opposite outcomes, so that version depends on a lucky place-and-route rather than
on anything reproducible.

### What actually solved it

**The tester found the game's own sound test.** That converted an intermittent
combat event into a repeatable trigger, which made the A/B and the control
possible. Two of my analyses pointed the other way and both failed their own
controls - a log-frequency correlation that could not detect a known octave shift,
and an envelope ranking that did not surface `0x1A` for the grunt death it
demonstrably is.

The cheap listening test, with ratios restricted to what the engine can actually
produce, is what worked. It should have come before the tooling.

## The Boom Box has 256 slots, but the PCM table has 128 rows

The sound test indexes `0x00-0xFF`. The SFX table is 127 live rows, `0x00-0x7E`,
and `sfx_play` does `flash[sfx_base + arg * 8]` with **no mask** - so a literal
`D1 9A` reads row 154, which is all zeros, and plays silence.

So the menu is not indexing rows 128-255. The layout that fits every observation:

| Menu slot | What it fires |
|---|---|
| `00-7F` | table id N, no flag |
| `80-FF` | table id `N & 0x7F`, **with `0x0100`** |

That is exactly why `9A` sounded like `1A` on stock and like deep-`1A` on the
patched build - it is `0x80 | 0x1A`, i.e. "row 0x1A with the rate step".

### CONFIRMED on hardware, 2026-08-31 - sweep run, item closed

**The extra 128 entries are variants, not new samples.** Run on shipping
`397b28eb`, which carries the rate step; on stock `61d1ddd3` every pair sounds
identical and the test is meaningless.

The pairs PORT_PLAN originally suggested were not good enough to be decisive.
Shipping `sfx.c` does `sr = (type>>4)&7; if (sr < 5) sr++;` - it **saturates** -
so six rows are already at the slowest rate and their `N+0x80` *must* be
identical. Without knowing which rows those are, an identical pair reads like a
refutation when it is the fix working correctly. `00 / 80` was also a poor
choice: row `0x00` is 127 bytes, about 2.6 ms, far too short to judge pitch.

Predictions were computed from the table before playing, so the sweep had a
falsifier rather than a listen-and-see:

    positive controls    52 / D2   24000 -> 12000 Hz   0.95 s -> 1.90 s   VERIFIED
                         20 / A0   24000 -> 12000 Hz   1.42 s -> 2.83 s   VERIFIED
    long-sample confirm  1C / 9C    9600 ->  6000 Hz   4.31 s -> 6.89 s   VERIFIED
    negative control     22 / A2    5333 -> 5333 Hz    identical          VERIFIED

The negative control is what makes this a result and not an impression: `22` is
already at rate index 5, so it cannot step, and it came back identical while the
positive controls dropped a full octave and roughly doubled in length. That
distinguishes "the flag works and saturated" from "the flag did nothing".

Rate index distribution across the 127 live rows, for anyone re-deriving this:

    index 0 = 48000 Hz :  1     index 3 = 9600 Hz : 23
    index 1 = 24000 Hz :  4     index 4 = 6000 Hz : 34
    index 2 = 12000 Hz : 59     index 5 = 5333 Hz :  6   <- cannot step

The six saturated rows are `22, 2C, 2F, 48, 4C, 71`.

Predictor: `scripts/predict_boombox_pairs.py <rom>` - reads the table at ROM
`0x25ECA4` and prints the pair predictions above. Script only; the ROM stays local.

### What would have refuted it

If any `N + 0x80` had been a *different instrument* rather than a slowed `N`, it
is not this table, and the candidates become wavbank slices or the menu walking
past the table's end into raw PCM. Nothing in the sweep behaved that way.

**Do not grow the mixer toward 256 voices on the strength of the menu's range.**
`80-FF` is a flag UI. There are 127 samples, not 255.

---

# (superseded) 2026-08-30, IMA ADPCM in progress

## Shipping state

`build_output/paprium.rbf_r` + the firmware rate-step is what is on the card and
pushed. Verified on hardware:

- **cap-at-49** - believed to stop slots 49-52 DMAing over the sprite attribute
  and hscroll tables at `0xF800`. **Both halves of that have since failed**: the
  SAT is at `0xF000`, and the tester reports no noticeable improvement. Still on
  the card, now unjustified rather than validated
- **field-wise sprite attributes** - fixes the doorway floor and palette generally
- **`0x0100` = rate-index step**, done in `sfx.c`, fit identical to `61d1ddd3`.
  Large-enemy death is the grunt sample one rate step down

Elevator is **closed as characterised**: fill-bound at 10-16 blocks/frame from
`dma_budget` (a ROM constant), plus the `previous_offset` fallback re-rendering the
last animation frame. Not a collision. Do not reopen without new evidence.

## IMA ADPCM - SHIPPING, verified on hardware 2026-08-31

**Done and committed:**

- `scripts/build_cdda_adpcm.py` - PPAD packer. 3.95x, SNR 37.9 dB, quality approved
- `rtl/PAPRIUM/paprium_ima_decode.sv` - 512-byte frames -> 505 stereo samples,
  fully registered, declared in `rtl/paprium.qip`
- `rtl/PAPRIUM/paprium_cdda_buf.sv` - ring holds compressed frames, decoder inside,
  chunk accounting in bytes (`6b75e90`)
- `rtl/PAPRIUM/paprium_cdda_fetch.sv` - PPAD vetted **before the table is walked**,
  16-byte entries at `0x18 + N*16`, mute on a bad or missing blob (`9e49d1b`)
- `scripts/verify_ima_decode.py` - cycle model, matches the reference decoder
  byte-for-byte over 1,010 samples across a frame boundary
- `scripts/verify_ppad_header.py` / `verify_ppad_audio.py` - model the fetch's
  address arithmetic and check pad behaviour against a real packer-written blob

**Two packer bugs the header check caught, both of which play as noise:**

- a **short final block** (looped to `take`, not `block_samples`) slides every
  following frame, because the decoder frames by counting bytes
- track padding went into a local, so the table held padded lengths while the file
  held unpadded bytes - every offset past track 1 drifted

**Known gap, stated rather than implied:** playback stops on the byte count, not on
`pcm_samples`. The ring's flow control is at 4096-byte granularity, so sample-exact
stopping belongs in `cdda_buf`. Residual is up to ~84 ms of digital silence at a
loop seam - quiet, not wrong. `pcm_samples` is already parsed and range-checked.

**Hardware results (`ima1` seed 5, setup -2.596, hold +0.004, M10K 294):**

- boots and runs - which also moved the known-good slack edge to -2.596
- **stale raw-PCM blob stays silent**, confirmed across all tracks via the Boom
  Box. The PPAD gate refuses it rather than streaming it as noise
- music plays correctly off the converted blob, and the user reports it sounding
  *cleaner* than the raw path

That last point is worth being precise about, because the obvious reading is
wrong: IMA is lossy at ~38 dB SNR, so the samples are strictly worse than the raw
blob's. What improved is **underruns** - the ring went from 0.085 s to 0.337 s of
buffering and SD fetch bandwidth dropped 4x, so dropouts that were present before
are gone. Fewer gaps, not better samples. If anyone later "optimises" the ring
back down, that is the regression to expect.

**Remaining:**

1. The sample-exact loop seam in `cdda_buf`, if the ~84 ms seam turns out to be
   audible. Not reported as noticed yet - ask before spending a fit on it

**Constraints:** player stays 16-bit 48 kHz. Do NOT fold in the ratestep RTL, the
cmdlog logger, or any region/menu cut. Shipping tree plus this decoder only.

**Gate:** hold > 0, setup not ~-3.0. Then hardware decides - see BUILD_REFERENCE.

**Users must rebuild `paprium.pcm`** - the format changed and the core now refuses
an unrecognised blob outright. INSTALL.md says so where the build commands are.

## Standing rules that cost something to learn

- **Archive before anything overwrites it** - `archive_fit.sh <label>` keeps the
  report AND the bitstream, in `build_output/gate-archive/` marked NOT-FOR-INSTALL
- **Never two Quartus builds at once** - they share `output_files` and both results
  become meaningless
- **The slack gate warns, hardware decides** - `-2.701` boots, `-2.715` does not
- **Combinational logic in a hot path is expensive here** - the `srate+1` adder in
  front of the `aclk` mux cost 0.4 ns and four seeds; registered logic is nearly free
- **Check the ROM before building instrumentation** - `dma_budget` was a ROM
  constant after four failed logger builds
- **A controlled trigger beats analysis** - the in-game Boom Box settled the death
  sound after two of my own analyses failed their own controls

## Elevator: the VRAM map question, and one approach already refuted

Raising `PPM_VRAM_SAFE_SLOTS` above 0x31 needs a 64-tile range that is not a
nametable, SAT or hscroll table **in both the cell room and INTERCOM**, because
layouts can change per scene. Until those five addresses are written down for
both, the cap stays at 49. Guessing 0x6400 is how the floor broke.

The five registers and their address maths:

    reg  2  plane A nametable   (v & 0x38) << 10      32x32 map = 0x800
    reg  3  window  nametable   (v & 0x3E) << 10      64x32 map = 0x1000
    reg  4  plane B nametable   (v & 0x07) << 13
    reg  5  sprite attributes   (v & 0x7F) << 9       SAT     = 0x280
    reg 13  hscroll table       (v & 0x3F) << 10      hscroll = 0x400

**REFUTED: static search of the ROM for VDP register tables (2026-08-31).**
Scanning for runs of `0x8rvv` words with ascending register numbers finds only
false positives - an 8 MiB ROM is full of ascending byte runs in the 0x80-0x9F
range, and the "tables" it returns decode to values that are themselves 0x8r
patterns (`reg 3 = 0x84`, `reg 16 = 0x91`), which is the signature of reading one
byte off. Scanning both alignments and requiring the run to start at register 0
or 1 did not fix it: the top hits are plainly data (`8182 8384 8587 8889 ...`
and `8001 8101 8201 8301 ...`).

That is probably inherent rather than a weak heuristic. Paprium's scene data goes
through the DATENMEISTER decompressor, so register setup need not exist as
plaintext anywhere in ROM. **Do not spend more time on a static scan.** Same
failure shape as the 0xDB decoder false positive: a heuristic that matches
structure which ordinary data also has.

What is left, cheapest first:

1. **Emulator VDP viewer.** Read regs 2/3/4/5/13/16 in the cell room and in
   INTERCOM; write down the five addresses and their sizes. Five minutes.
2. **A logging GPGX.** `tools/gpgx-render` already has a libretro host and the
   core source is in `gpgx-build/`, so patching the VDP register write path to
   log every distinct layout with a frame number is a small change - and it
   catches per-scene changes that reading a viewer by eye can miss. It still
   needs someone to play to those scenes.
3. **One-slot hardware probe, only after 1 or 2.** Pin slot 49 to a candidate
   outside every listed map; boot -> cell room -> doorway -> HUD. Anything
   breaking means the range is live.

Do NOT slide 800 -> 864 -> 928 blind. A 64x32 map at 0x6400 covers 0x6400-0x73FF,
which is tiles 800-927, so 864 is still inside it.


## VRAM starvation is ONE defect, and it is wider than the elevator

**Reported (hardware, 2026-08-31):** characters sometimes animate as if standing
still - walking, but the frame never advances. Present since the first build. A
community thread put it down to VRAM starvation. That reading is correct, and it
is the mechanism already recorded here for the elevator.

`ppm_obj_render` in `mcu/mame.c`:

    if (!ppm_vram_load_block(spr_data->blockNum)) {
        blocks_available = false;
    }
    ...
    if (!blocks_available) {
        if (previous_offset) {
            handle->anim_offset = previous_offset;   // rewind to the last frame
            handle->counter     = previous_counter;
        } else {
            return;                                  // draw nothing at all
        }
    }

When a block will not load, the object **rewinds to its previous animation
frame**. Across consecutive frames that is a character walking on the spot. With
no previous frame it is not drawn at all, so severe starvation makes objects
vanish rather than freeze - the same path, worse severity.

**Consequences for how the open items relate:**

- **The elevator is not a separate bug.** It is this fallback in the scene that
  demands the most blocks. PORT_PLAN already described the elevator's stale
  squares in exactly these terms; what was missed is that the same code fires in
  ordinary gameplay, so it was mis-scoped as an elevator problem
- **Cap-at-49 is a second-order factor, not the cause.** `PPM_VRAM_SAFE_SLOTS`
  and `dma_budget` are different limits and must not be conflated:

      PPM_VRAM_SAFE_SLOTS 0x31   how many blocks may be RESIDENT   (49)
      dma_budget                 how many may be LOADED PER FRAME  (10-16)

  Starvation is `load_block` failing, and **four more slots does not raise the
  fill rate**. More slots only helps by retaining blocks the LRU would otherwise
  evict and reload, which avoids some loads rather than allowing more of them.
  Worth having, not the lever.

- **So frozen walks are NOT blocked on the emulator session.** An earlier version
  of this note claimed buying back four blocks would reduce animation freezing
  across the whole game, and parked the symptom behind the VDP map. That was
  wrong - it treated slot count and fill rate as the same quantity. The binding
  constraint is 10-16 blocks/frame from a constant in the game's own ROM, and
  nothing in the map changes it.

**Separately: do not raise the cap blind.** The reason 49 exists is the confirmed
`0xF800` SAT/hscroll collision, and the reason a remap was reverted is that the
cell-room floor broke. The route to 53 is still the five addresses - but that is
about the elevator's tile corruption, not about this.


## Sprite priority: NOT SAT priority - probe result (2026-08-31)

`PPM_FORCE_SPRITE_PRI` OR'd `0x8000` onto every SAT entry after field-wise
composition. Fit was identical to shipping (18,194 / 294 / -2.596 / +0.004) with
a different bitstream hash, so it was firmware-only and it did land.

**Result: other sprites came forward - the player and the bombs did not.**

So the probe worked and the answer is negative. **It is not SAT priority**, which
rules out the "high-priority plane tiles vs low-priority SAT" reading entirely.

### A misread to correct

That reading came from me describing the elevator walkway screenshot as
"tile-shaped occlusion following the parapet silhouette", and picking the
per-tile row of the decision table on that basis. **The rooftop capture shows a
clean horizontal line across the full screen width** - the big enemy fully drawn
above it, the player cut exactly at it. A window plane's edge lands on a tile-row
boundary and therefore produces exactly that straight line, so the elevator
parapet most likely coincided with it. The silhouette reading was seeing what the
theory wanted.

### What a negative result here actually implies

**A high-priority sprite is topmost on a Mega Drive.** The order is sprite-pri-1,
plane A pri-1, plane B pri-1, sprite-pri-0, plane A pri-0, plane B pri-0. A
forced-priority sprite beats every plane including the window. So "priority
forced and still behind" is not a weaker version of the same problem - it means
something else is happening.

Two candidates, and the emulator session distinguishes them:

1. **The player and bombs are not cartridge-rendered.** `ppm_obj_render` composes
   SAT entries for objects the cartridge draws; if the player is a 68000-managed
   sprite, our OR never touches it and **no change in that function can ever
   affect it**. This fits which things moved - the cartridge-rendered enemy and
   explosions came forward, the player and bombs did not. It would also mean the
   whole "mega-ppm composes attributes wrong" line of investigation cannot
   explain this symptom
2. **Something region-based is masking rather than layering** - a window plane,
   or sprite masking (a sprite at X=0 hides lower-priority sprites on its
   scanlines regardless of priority)

### What the emulator session must now capture

**Two items need it, not four.** The frozen-walk symptom is already explained by
`load_block` -> `previous_offset` and is fill-rate bound; the intro flicker is
unrelated and lowest value. Only these are actually gated:

    cap-53 / remap              five addresses + map sizes, cell room + INTERCOM
    player/bombs behind scenery SAT dump + regs 3/17/18

The same playthrough is convenient for both, not required.

Beyond the five VDP addresses already needed for the cap:

- **window position and size** in the rooftop and elevator scenes (reg 17/18 as
  well as reg 3), because a horizontal window edge is the leading suspect
- **whether the player's SAT entry has priority set**, and whether the player
  appears in the SAT at all - which settles candidate 1 directly
- a **sprite-per-scanline** check in the bombing scene, since that stage is busy

Until that exists, do not spend another fit on sprite attributes. The blanket-OR
probe was the cheap decisive test for the firmware side and it came back negative.


## Still open

- ~~YM2612 DAC static (VM DAC option)~~ **FIXED 2026-08-31** - the 68000 streams
  cart RAM 0x1802-0x19FF to YM2612 0x2A and we never initialised it. Filling it
  with 0x80 (unsigned 8-bit mid-scale) makes the path DC instead of noise.
  Firmware-only, identical fit. Hardware-accurate routing deferred - see above
- Rooftop boss sprite priority - never investigated
- Intro pixel flicker - cosmetic
- ~~Boom Box `N` vs `N+0x80` sweep~~ **CONFIRMED 2026-08-31** - the high 128 slots
  are rate variants, not unheard samples. Positive controls, a long-sample
  confirmation and a saturated negative control all verified. See above


## Auto-boot: a data slot needs its own filename, and so does the save

Confirmed on hardware 2026-08-31. JSON only - no RTL change, no fit.

The core now launches straight into the game with no file browser, and there is
no region option. Both were cheaper than they looked:

- **Region.** `core_top.sv` already resets `cfg_region` to `2'd1`, which is Japan.
  The menu variable was only ever writing back the value the core already had, so
  deleting it from `interact.json` means nothing writes bridge `0x0C` and the
  reset value stands. No RTL edit was needed at all
- **Auto-boot.** Giving the ROM slot `"filename": "Paprium.md"` in `data.json`
  makes APF load it directly instead of opening the browser

### The part that is worth remembering

**Auto-loading the ROM silently broke saves.** The core booted, played correctly,
and started the boot mini game every time - while a perfectly good 4 KB
`Paprium.sav` sat unread at `/Saves/paprium/common/`.

The save slot's file is associated with the **instance** the file browser creates.
Auto-loading by filename produces no instance, so the nonvolatile slot was never
loaded and never written back. The fix is to give the save slot its own filename
too:

    "id": 10, "nonvolatile": true, "filename": "Paprium.sav"

With that, both work: boots straight in, save intact. **A nonvolatile slot's
filename resolves under `/Saves/<platform>/common/`, not `/Assets/`** - the
existing save was picked up in place, which settles where the path is rooted.

The general rule, for any future slot: **if the browser is skipped, every slot
that relied on the browser's instance needs an explicit filename.**

### Two notes on the test itself

- The save was backed up on and off the card before anything ran. It would have
  been easy to conclude "saves are broken" and start debugging over the top of the
  only copy
- The save was deliberately **not** also copied into `/Assets`. Leaving one copy
  at the canonical path is what made the result readable - it loaded, so it
  resolved under `/Saves`. Had both existed, the run would have proved nothing

### Still open

`Load Paprium ROM` remains in the core settings menu, because the ROM slot keeps
its user-reloadable bit. Harmless - the save now has a fixed name either way, so
loading through it cannot split saves across two files - and it is a useful escape
hatch. Remove the bit from `parameters` if the menu should be tidier.

# GPGX sprite-path read - 2026-08-31

Source only, no playthrough, no build. Two results: one closes the rooftop
firmware line of attack, one hands over a VDP address that was thought to need an
emulator.

## 1. The player does NOT go through mega-ppm. Stop fitting SAT attribute changes

The SAT is staged in **cart RAM at 0xB00** and DMAed to VRAM by the cartridge. Both
implementations agree on the protocol:

    GPGX      paprium.h:1296   ram + 0xB00 + spriteCount*8
    mega-ppm  mame.h:48        ppm_sat_item sat_data[144];  //0xb00

and both take the running count from the same place - GPGX reads and writes
`ram + 0x1F18`, mega-ppm calls it `sat_count`, and the struct puts it at 0x1F18.

**Nothing on the cartridge side ever zeroes that count.** GPGX writes it back at
the end of `paprium_sprite` and reads it in start/stop/pause; it is never reset.
So the 68000 owns it, which means the 68000 decides where the cart's entries begin
and is free to write its own entries into the same shared buffer.

That closes the loop with the hardware probe. Forcing `0x8000` moved other sprites
and did not move the player or the bombs, which is exactly what a shared buffer
predicts: **we only ever touch the entries we append.** Three independent sources
agree, so this is settled without a dump:

    GPGX source        SAT staged at 0xB00, count 68k-owned
    mega-ppm header    same buffer, same counter
    hardware probe     forced priority moved other sprites, not the player

**No change in `ppm_obj_render` can fix the rooftop or elevator clipping.** Do not
spend another Pocket fit on sprite attribute composition. The remaining question -
whether the player's entry is in the SAT at all, and with what priority - is a
runtime one and still needs the emulator.

Worth noting the attribute composition itself is confirmed correct. GPGX at
`paprium.h:1287-1289` is field-wise with tile precedence, which is what the door
fix changed ours to. That fix matches the reference exactly.

## 2. SAT base is 0xF000, from source - and the 0xF800 note is wrong

`paprium_sprite_start` (paprium.h:1420) builds a fixed VDP DMA list:

    8F02  reg15 auto-inc 2
    9340  reg19     9401  reg20  > length 0x140 words = 640 bytes = 80 entries
    9580  reg21     9605  reg22  > source (0x05<<9)|(0x80<<1) = 0xB00, the staging buffer
    9700  reg23 /
    7000  } control: CD=100001 VRAM write + DMA
    0083  } address = (0b11 << 14) | 0x3000 = 0xF000

**So the SAT lives at VRAM 0xF000 and spans 0xF000-0xF27F**, and it is hardcoded -
the cart writes there every frame regardless of scene, so `reg 5` must be 0x78
throughout. That is one of the five addresses, and it did not need an emulator.

**This contradicts what is written above.** The cap-at-49 analysis says slots 49-52
were landing on "the sprite attribute and hscroll tables at `0xF800`". Tiles
1984-2047 are `0xF800-0xFFFF`, and the SAT is nowhere near that - it ends at
`0xF27F`, in tiles 1920-1939.

To be careful about what changed and what did not:

- **The fix is still right.** Cap-at-49 was verified on hardware and the elevator
  improved. That is unaffected
- **The explanation was wrong.** Whatever slots 49-52 were smashing at
  `0xF800-0xFFFF`, it was not the sprite attribute table. The hscroll table
  (`reg 13`) is the obvious remaining candidate, and it is still unmeasured
- The standing instruction not to send those slots back to `0xF800` was empirical
  and stands on its own

## 3. What the source cannot give, and why

The cart writes exactly two kinds of VDP list: tile DMAs to `draw_dst`, and the
one SAT DMA above. **It never touches plane A, plane B, window or hscroll** - the
68000 owns those registers, and they are set from decompressed scene data.

So regs 2, 3, 4, 13, 17 and 18 still need the emulator, and the plaintext ROM scan
for them is still refuted. The emulator session is now smaller than it was: SAT
base is known, one of the two questions about the player is answered, and what is
left is the plane/window/hscroll set plus a SAT dump to see whether the player is
in the table.

# QUEUED: fix the ownership map, then build on it - after masking and the elevator

`snap_owner` in `mcu/mame.c` records, per SAT entry, the object index that wrote
it. It is currently **wrong and should not be trusted** - in the one capture that
used it, it credited the 68000's own masks to "obj 0" (entries we never write) and
split a single figure across obj 38, 44 and 1. It is still compiled in and writes
80 bytes into every capture that nothing reads.

## Why it is worth fixing rather than deleting

Not as a labelling convenience - it earns its place as a way to model **how the
game drives the cartridge**. Across captures it would give:

- which object each sprite belongs to, so groups need no human identification
- the same object tracked across the phases of a scene, which matters because the
  rooftop is a sequence and entry indices differ every frame
- where the 68000's own entries sit relative to ours, which is exactly the axis the
  masking bug turned out to live on
- a picture of the object model itself: how many objects a scene uses, how many
  sprites each costs, which are cartridge-rendered and which are not

The masking root cause was found by comparing chain POSITION between two runs. A
working ownership map makes that kind of comparison routine instead of a one-off.

## What fixing it needs

Not yet diagnosed, so this is a starting point rather than a plan:

- **the array is never cleared between frames**, so an entry we do not write keeps
  a stale owner. That alone would explain masks credited to obj 0. Clearing to
  0xFF each frame would make "not ours" explicit and self-evident in the capture
- confirm `obj_slot` is the identifier it appears to be, and that indexing by
  `sat_count` before the increment lines up with `satEntry` in every path,
  including the ones that `continue`
- consider recording the DRAW ORDER as well as the object, since order is what the
  masking bug turned on

Sequenced after the masking fix and the elevator check - it is an investigative
tool, not a fix, and the fix in flight should not wait behind it.

# QUEUED NEXT: DMA overbudget probe - after the masking work closes

Written and committed, **default OFF** (`PPM_DMA_OVERBUDGET` in `mcu/mame.c`).
Not to be enabled in the same build as any mask probe - two variables in one
build and neither result means anything.

## The hypothesis, and why it inverts what this file assumed

From the tester, on original hardware: **Paprium visibly tears when the screen is
busy, and does NOT lose animation.** Our port is the other way round - no tearing,
dropped frames.

This file previously argued that `dma_budget` is a real hardware limit the game
respects, and therefore that the frozen animations were "characterised, not
fixable at this scope". If the real cartridge routinely overruns its vblank and
accepts tearing as the price, then **respecting the budget exactly is OUR
deviation** and the frozen walks are self-inflicted. That is a materially
different claim and it deserves a measurement rather than an argument.

## What the probe does

`dma_budget` at ramdp `0x1F12` is written by the 68000 and only read by us. The
probe does NOT overwrite it - the game still reads back its own value. It inflates
only the figure the cartridge budgets ITSELF against, so more blocks are queued
per frame. Ratio is a num/den pair; 3/2 is the first try.

    tearing appears AND animation smooths   -> trading an artefact hardware also
                                               has for frames it also has. Arguably
                                               MORE faithful, not less
    tiles corrupt, animation unchanged      -> bad trade, stays off
    nothing changes at all                  -> the 68000 is not honouring
                                               dma_remaining the way we assume,
                                               which is worth knowing on its own

Keep sprite flicker out of the judgement: that is the VDP's per-scanline sprite
limit and will behave identically either way. Only tearing and torn tiles are in
scope.

## Related correction already made

`cmd_EC_vram_budget` sets the SLOT count - residency, what `PPM_VRAM_SAFE_SLOTS`
clamps - not `dma_budget`. Those are different numbers and were conflated earlier
in this file.

# THE RULE THAT GENERALISED: absolute SAT index, not a count - 2026-09-01 late

## Result

    emulator rooftop, no symptom     masks at chain 25, 27, 29
    our port, absolute-index 32      masks at chain 23, 24, 25
    our port, before any fix         masks at chain  8, 10, 12

Tester: "it fixed a lot of both" - elevator and rooftop.

**This is the first value that transferred between scenes without being refitted.**
Both earlier constants were derived from elevator frames and broke elsewhere; the
index was derived from the mechanism and landed within two chain positions of
where correct hardware puts the masks, in a scene it had never seen.

## Why counts failed and the index did not

`MOVE_AFTER` counted OUR composed sprites, so the correct value moved with how
many of ours happened to precede the boundary - 8 in one elevator frame, 13 in
another - and each spliced through whichever group sat at that ordinal: the player
at 8, the NPC at 13.

The 68000 writes its masks at whatever `sat_count` holds at that instant. On
hardware ~32 sprites are already composed; on our port ~14. **Index 32 is where
the game means them to be**, and our lateness is the entire bug. Expressed in
absolute indices the target is fixed; expressed as a count of our own sprites it
is not.

## Remaining difference from hardware

Hardware interleaves: 32, **33**, 34, **35**, 36 - each X=0 mask followed by its
X=1 partner. We move only the X=0 sprites, so ours land contiguously at 23, 24, 25
while the partners stay at their original early positions.

Masking still functions - the partner only has to precede the mask on the same
scanline, which it does - but the layout is not an exact reproduction. If anything
subtle remains, moving each pair together is the next refinement, and it is a
small change to the same pass: collect the X=1 node adjacent to each X=0 node and
splice both.

## Still not fixed by any of this

The elevator's scrolling squares. They are plane tiles, not sprites - a frame
captured with them filling the screen held 14 sprites and none of them were
squares, and frames full of squares report zero masks. No mask work can touch
them.

# MASK RELINK: what it fixes, what it cannot - 2026-09-01 evening

## Confirmed fixable by moving the masks

Hardware, elevator, `MOVE_AFTER = 8` (`c7f6c5a5`):

    the scrolling enemy no longer cuts through the elevator it rides   FIXED
    the elevator structure no longer draws over the player             FIXED (earlier build)
    the player's back half is hidden                                   COST of 8 - predicted

The player clipping was **predicted before the run** from the capture: in that
frame our 8th composed sprite is entry 27, inside the player group 25-29, so the
masks splice through him. It happened exactly as predicted, which is the first
time this model forecast hardware behaviour rather than explaining it afterwards.
That is what makes the derivation trustworthy.

`MOVE_AFTER = 13` - after the NPC, before the enemy - is the value the same
capture supports, and should keep the enemy fix without the player cost.

## NOT fixable by moving the masks: the scrolling squares

The tester captured a frame **with the squares filling the screen**, exiting while
they were visible. The sprite table for that frame holds **14 sprites**: the HUD,
the player, an NPC, and one other. Nothing that could be a square.

**So the squares are plane tiles, not sprites.** A sprite mask hides only sprites,
so no amount of relinking can touch them. The fill-rate / stale-tile explanation
stands.

This was a hypothesis worth testing - the squares look exactly like a grid of
sprite blocks, and an earlier capture did contain an 8-sprite 32x32 grid that was
taken for them. It was refuted by a capture designed to confirm it, which is the
strongest form of negative result available here.

### A loose end with a duller explanation

"Some squares now draw behind the player" was observed under the 8 build. If they
are plane tiles that cannot be masking. It does not need to be: plane cells carry
their own priority bit, so squares in pri-1 cells draw in front of a pri-0 sprite
and squares in pri-0 cells draw behind. A mix produces exactly that, and would
have done so before the build changed.

## The open question about MOVE_AFTER

Two elevator frames produced two different correct values - 8 and 13 - because
different objects were alive. Whether one constant can serve the whole game
depends on whether the render ORDER is stable even when the COUNT is not. The
tester's position is that it should be, and that fixing one scene fixes the
others. `MOVE_AFTER = 13` tested in both elevator and rooftop is the experiment
that decides it.

An earlier version of this note called the approach a dead end on the strength of
those two numbers. That was premature: the 8 came from a frame identified from
memory, the 13 from one identified against a photograph. One well-measured frame
is worth more than two half-measured ones.

## Method note

Five captures were named from memory or from photos taken afterwards, and the
group identifications drifted between them - the same block called the squares in
one capture and the background elevator in another. That is a fault in the
experimental design, not in the tester's recall: naming sprites from memory across
a moving, multi-phase scene is not a reasonable thing to ask.

`scripts/draw_sat_layout.py` plus a photograph taken during the run fixed it, and
the moment that was the method, the numbers became derivable and the first correct
prediction followed. Do it that way from the first capture, not the fifth.

# ROOFTOP ROOT CAUSE: the masks are in the WRONG PLACE IN THE CHAIN - 2026-09-01

Comparing the hardware capture against the emulator rooftop state - where the
symptom does NOT occur - the masks are identical and their position is not:

                            X=0 masks, chain position   entries      Y
    emulator rooftop s10          25, 27, 29            32, 34, 36   136/168/200
    our hardware capture           8, 10, 12            15, 17, 19   136/168/200

Same three masks. Same Y ladder. Seventeen chain positions apart.

Sprite masking hides sprites that come **later in the chain**, so:

    emulator   masks at 25-29 -> only sprites after them are hidden. The player,
               earlier in the list, is untouched. No symptom
    our port   masks at 8-12  -> nearly everything the cartridge composes lands
               behind them, the player included

## Why this is not an attribute bug at all

The 68000 writes those masks at whatever `sat_count` holds **at the moment it
writes them**. On the emulator, 32 sprites have already been composed by the
cartridge by then. On ours, 14 have. So our sprite composition runs **later
relative to the 68000's mask write** than it should.

That is an ordering/timing relationship between the MCU's rendering and the
68000's frame - not priority, not attribute composition, not the tile data. Two
days were spent in `ppm_obj_render`'s attribute path, and nothing there could ever
have fixed it.

## How the mechanism was finally cornered

Each step ruled out the previous favourite, and every decisive one came from
hardware or from a rendered picture rather than from reading code:

    forced priority + snapshot   priority forced to max, player still behind, and
                                 the capture proved the OR had landed
    mask kill                    player fixed, boss and door broken - so the masks
                                 are live and load-bearing
    tester identification        the rendered SAT layout named the player, boss,
                                 bombs and HUD, which no instrumentation had managed
    emulator comparison          same masks, different chain position. Free, and
                                 it should have been the first thing checked

## What the fix has to do

Get the cartridge's sprites into the chain **before** the 68000 writes its masks,
which means understanding what makes the emulator's cart reach 32 composed sprites
where ours reaches 14 at the same point in the frame. Candidates:

- the MCU is slower to compose, so the 68000's write arrives earlier in our
  sequence. This would tie the bug to the same fill-rate story as the frozen
  animations
- the mailbox command order differs, so we start composing later in the frame
- our `ppm_obj_frame_end` runs at a different point relative to the 68000's frame
  than the real cartridge's equivalent

**Do not ship the mask-kill probe.** It fixes the player by breaking the boss and
the helicopter door, which is trading one visible bug for another.

## A note on the ownership instrumentation

The SAT-entry-to-object map added for this run was **wrong** - it attributed the
68000's own masks to "obj 0" and split a single figure across three owners. It was
not used for any conclusion here. The tester's identification from the rendered
layout has now been more reliable than the instrumentation twice running.

# ROOFTOP SOLVED: SPRITE MASKING, not priority - 2026-09-01

Probe and snapshot run together on hardware. This closes the question.

## The experiment

`PPM_FORCE_SPRITE_PRI` ORs `0x8000` onto every entry this firmware composes, and
`PPM_SAT_SNAPSHOT` captured the list it produced, so the probe's effect could be
read rather than judged by eye.

    capture: every entry we compose reads priority 1   - the OR landed
    tester : the extra life behind the bed came forward, the escalator stopped
             occluding the player                       - the probe visibly worked
    tester : THE PLAYER STILL DREW BEHIND ON THE ROOFTOP

Priority was forced to maximum on the player and it changed nothing. **Sprite
priority is not the mechanism.** That is now a measured result, not an inference.

## What is doing it

The capture shows entries in the link chain that this firmware did not write - the
probe would have set priority on anything we wrote, and these read 0:

    chain pos  entry    X     Y   tile  pri
        7        14   -127  136  0x000   0
        8        15      0  136  0x000   0   <- MASK
        9        16   -127  168  0x000   0
       10        17      0  168  0x000   0   <- MASK
       11        18   -127  200  0x000   0
       12        19      0  200  0x000   0   <- MASK

**X = 0 is the Mega Drive sprite-mask position.** A sprite there hides sprites that
come LATER in the link chain on its scanlines, and it does so regardless of their
priority bit. These three cover Y 136-231 - the lower half of the screen, where the
player stands - and they sit at chain positions 8-12, ahead of nearly everything we
append.

Each is paired with a companion at X = 1. That is the standard construction for
making a mask take effect, so this is deliberate, well-formed masking rather than
stray data. The 68000 wrote it; we did not.

## Why every previous theory failed

    forced priority   masking ignores the priority bit entirely
    window plane      refuted separately: reg 17/18 are zero in every scene
    68000-drawn player  wrong; the player is entries 38-43 of OUR list
    high-pri BG tiles   real, but not what hides the player

And it explains the August result precisely: sprites earlier in the chain, or
outside Y 136-231, came forward when priority was forced; the player, later in the
chain and inside that band, did not.

## A correction to yesterday's note

Yesterday this file said the forced-priority result and the capture "cannot both be
right as stated". They were both right. The tester's observation was accurate on
both occasions and the missing piece was a mechanism that was not on the list -
one I had also called "refuted" the day before, on the strength of a single capture
where the X=0 entries happened not to be chain-reachable. One frame is not a scene.

## Where the fix has to live

We do not write the masks and we do not choose our position in the chain: the
68000 owns `sat_count`, so it reserves the low indices for itself and our sprites
are necessarily appended after. On real hardware the same ordering must hold, and
the real cartridge does not hide the player - so either

1. the mask entries are STALE on our port - written for an earlier frame or scene
   and never cleared, so the VDP walks into them, or
2. they are current, and on hardware something we are not reproducing stops them
   applying to the player

Both are testable, and (1) is testable cheaply: a firmware build that moves any
chain-reachable X=0 entry we did not write to an off-screen Y before the frame is
handed over. If the player then draws correctly, masking is confirmed AND the fix
is in hand. If the game loses a masking effect it wanted, that shows as something
else appearing that should be hidden - which is exactly the signal to look for.

**Do not ship a blanket mask-killer without that check.** Masking is a legitimate
technique and this game clearly uses it on purpose somewhere.

# ROOFTOP ANSWERED: the player is in OUR sprite list, at priority 0 - 2026-09-01

Captured on real hardware with the `PPM_SAT_SNAPSHOT` firmware, scene identified
by the tester from a rendered layout of the sprite table
(`scripts/draw_sat_layout.py`, image in `docs/rooftop-sat-layout.png`).

    SAT entries 38-43   THE PLAYER          priority 0   palette 1
    SAT entries 14-20   boss in helicopter  priority 1
    SAT entries 27,28,32,33  bombs          priority 1
    SAT entries 35-37   player UI / health  priority 1

**The player is the ONLY priority-0 sprite on the screen.** Everything else - boss,
bombs, HUD - is priority 1.

That single fact explains the shape of the symptom. On a Mega Drive the order is

    sprite pri1 > plane A pri1 > plane B pri1 > sprite pri0 > plane A pri0 > plane B pri0

so a priority-0 sprite is the only kind of sprite a high-priority background tile
can cover. Every other object in the scene is immune by construction, which is
exactly what "only the player drops behind the scenery" looks like.

## What is settled

- **The player IS cartridge-rendered, by this firmware.** It is in the list we
  compose at `0xB00`, not drawn by the 68000. An earlier note in this file
  concluded the opposite from the forced-priority probe; that conclusion is
  withdrawn
- The 68000 asks for it at priority 0: object table entry for the player carries
  `attrs 0x2000` - palette 1, priority bit clear. **All 42 objects** in the capture
  have the priority bit clear, so sprite priority in this game comes entirely from
  the per-tile attribute byte, never from the object
- Sprite masking is refuted: the X=0 entries in the buffer are not reachable
  through the link chain, and the VDP only draws what the chain reaches

## The tension that must be resolved before any fix

The forced-`0x8000` probe OR'd priority onto every entry this firmware composes.
If the player is entries 38-43, that probe should have made the player priority 1
and brought it in front of everything. **The tester reported it did not move.**

Both observations cannot be right as stated. Either the probe did not do what its
code says, or what was seen not moving was not the player. Do not ship a
priority-related fix until that is resolved - the obvious "just force the player to
priority 1" would be built on a contradiction.

**The decisive experiment is now cheap**, because the snapshot exists: build the
forced-priority probe AND the snapshot together, capture the rooftop, and read the
player's entry.

    player entry shows pri 1 and still renders behind  -> priority is NOT the
        mechanism, and the cause is what the background draws over it
    player entry shows pri 0 with the probe active     -> the probe never reached
        those entries, and the earlier refutation was invalid

## Also worth checking, spotted while reading the attribute path

`ppm_spr_data.offset` is a `uint8_t`. GPGX splits the same word as 7 bits of
attribute and **9 bits** of offset (`& 0x1FF`), and our `attrs & 0xf8` discards the
low three bits of the attribute byte - one of which may be the ninth offset bit.
If so, any sprite whose offset exceeds 255 gets the wrong tile index. Speculative,
not yet evidence, but it is in the same few lines as the priority extraction.

# What actually lives in each tile range - 2026-08-31, rendered

`scripts/render_vram_tiles.py` renders the tile patterns and the plane maps out of
the savestates, and tints the cells whose tile index falls in a chosen range. So
this is a picture, not a reference count.

## The answer

    tiles  800-863   VRAM 0x6400-0x6BFF   BACKGROUND. Planes index it, sprites never do
    tiles 1984-2047  VRAM 0xF800-0xFFFF   SPRITES. The SAT indexes it, planes never do

Measured across cell room, elevator/INTERCOM and rooftop:

    scene                planes -> 800-863      sprites -> 1984-2047
    cell room            48 tiles / 169 cells   42 SAT entries
    elevator/INTERCOM    39-41 tiles / ~138     9 SAT entries
    rooftop              -                      12 SAT entries

and the converse is zero in every scene: **no sprite references 800-863, and no
nametable cell references 1984-2047.**

Visually confirmed too. `planeB-marked.png` for the cell room lights up the floor
band and the doorway pillars; in the elevator scene the same range is the ground
and platform edges in plane A instead. Different plane, same role.

## Why this matters

**It gives cap-53 a mechanism.** Cap-49 was not starving the background - it was
starving **sprite** pattern space, because slots 49-52 land at tiles 1984-2047 via
the `+0x4b` jump and that is where sprite artwork goes. Sprites are the animation.
"Walks and animations much better" is exactly what restoring those four blocks
predicts, and the elevator shaft not moving is equally expected: the shaft is plane
artwork and never used that range.

**And it explains the 0x6400 remap failure precisely.** That range is floor and
ground art the planes are actively indexing. Writing streamed blocks over it
destroys the floor - which is what hardware showed.

## Two corrections to the section below this one

Both were mine, both from the same bug, and both were stated confidently:

1. **"Plane A and B index tiles 1984-2047, 10-37 entries"** - wrong. Corrected: the
   planes reference that range **zero** times. The support for cap-53 is the
   sprite column, not the nametable column
2. **"GPGX does not render these scenes, so its sprite output is not evidence"** -
   wrong, and the more serious one. The sprite tables looked like garbage because
   of the same bug

**The bug:** GPGX stores VRAM as native 16-bit words (`uint16 *p = (uint16
*)&vram[index]` in `vdp_ctrl.c`), so on a little-endian host every word is
byte-swapped against Genesis order. Reading it big-endian scrambles tile patterns,
nametable cells and SAT entries alike. `scripts/parse_gpgx_state.py` now has
`unswap()` and both scripts use it.

**What should have caught it sooner:** the first tile atlas came out as noise, and
the response was to look for reasons the data might be bad rather than to test the
decoder against something known. Rendering a whole plane was the available control
and it takes one command - the cell room now renders as a recognisable room, door,
sign and all, which is proof the decode is right in a way no amount of arguing was.

## Confidence, honestly

This is **strongly supported, not proven**:

- the range-to-consumer split is consistent across every scene captured, in both
  directions, and matches two independent hardware results (the 0x6400 remap
  breaking the floor, cap-53 improving animation)
- it is derived from an emulator, and the tester reports its backgrounds look
  wrong. The *structure* comes from the game's own allocator and the `+0x4b` map,
  which are shared with hardware, but the pixels may not be
- only four scenes were checked. Another scene could use the ranges differently -
  the same tile index holds different pixels in different scenes, by design
- "800-863 is the floor" is scene-specific. It is floor in the cell room and
  ground/platform in the elevator. The general claim is "background artwork", and
  that is what the evidence supports

# VDP capture RESULT - 2026-08-31, 11 savestates

Captured in RetroArch with the Paprium-capable GPGX core: cell room, elevator,
INTERCOM walkway, rooftop. Parsed with `scripts/parse_gpgx_state.py`.

## The register map is STATIC across the whole game

All eleven captures, every scene, byte-identical:

    reg  2 = 0x30   plane A   0xC000 - 0xCFFF
    reg  4 = 0x07   plane B   0xE000 - 0xEFFF     (reg 16 = 0x01, 64x32)
    reg  5 = 0x78   SAT       0xF000 - 0xF27F
    reg 13 = 0x3D   hscroll   0xF400 - 0xF7FF
    reg  3 = 0x3C   window    base 0xF000, but reg 17 = reg 18 = 0

**There is no per-scene VDP remapping.** The five addresses that were treated as
unknown for weeks are one set of numbers, the same everywhere.

### cap-53, and a correction to the first version of this note

`0xF800-0xFFFF` holds no VDP **structure** in any scene - hscroll ends at `0xF7FF`
and no register points above it. That much the registers prove.

**The first version of this note then said the region was "free". That is wrong,
and the registers never supported it.** A register only says where the VDP is
aimed; it says nothing about which tile indices the nametables reference. Checked
directly, from the same captures:

    capture   nametable refs to tiles 800-863   refs to tiles 1984-2047   max idx
    state0                 203                           21                1989
    state7                  64                           37                2027
    state9                 121                           24                2003

**Plane A and B actively index tiles 1984-2047**, which is `0xF800-0xFFFF`. The
region is live artwork, not spare space.

This makes cap-53 more clearly right rather than less. Slots 49-52 map to tiles
1984-2047 through the game's own `+0x4b` jump, and the planes reference exactly
those tiles - so that is **where the game intends the artwork to go**. Capping at
49 leaves the nametables pointing at patterns that were never loaded, which is a
mechanism for the animation problems, not merely an absence of harm.

It also confirms why the `0x6400` remap broke the cell-room floor: 34-224
nametable entries reference tiles 800-863. Not a nametable base, but indexed as
artwork. **"Not a table" never meant "not used"** - which is the same error the
first version of this section made about `0xF800`.

Three independent confirmations agree that the SAT/hscroll collision story is
dead: the GPGX source (SAT DMAed to `0xF000`), the hardware A/B (cap 49 vs 53,
elevator unchanged and animation much better), and these measured registers from
the elevator and INTERCOM - the very scenes that use those slots.

### And it refutes the window hypothesis for the rooftop

**reg 17 and reg 18 are zero in every capture, including the rooftop.** The window
plane is never enabled anywhere in this game. It was the leading suspect for the
player-behind-scenery clip and it is now dead.

## What this capture could NOT answer, and why

The SAT question - is the player in the sprite table, with what priority - is
**not answered**, and the captures cannot answer it.

Both copies of the sprite list were checked:

    VRAM at 0xF000              2-3 sprites in the link chain, none on screen
    cart RAM at 0xB00           identical to VRAM, every entry parked at X=0/1

`sat_count` at `0x1F18` reads 56, so the game thinks it has written 56 sprites,
but every entry is off-screen. Mid-fight, that is not a plausible sprite list.

The tester's own observation explains it: in the emulator **the background looked
different and almost broken, the elevator glitching did not occur, and the player
never went behind the stage**. GPGX's Paprium cartridge emulation is not rendering
these scenes correctly, so its sprite output is not evidence about ours.

### Why the register result survives that and the SAT result does not

The VDP registers are written by the **68000**, which GPGX emulates faithfully -
that path does not depend on the cartridge implementation at all. The sprite list
is built by the **cartridge**, which is exactly the part that is visibly wrong.
So the same capture is trustworthy for one and worthless for the other.

Do not read "the symptom did not reproduce in the emulator" as evidence that our
firmware causes it. An emulator that does not draw the scene correctly cannot be
cited for what it fails to show.

## Where the rooftop item stands now

    window plane            REFUTED - never enabled, in any scene
    SAT priority            already refuted on hardware by the forced-0x8000 probe
    is the player in the SAT  STILL OPEN, and not answerable from GPGX

The remaining candidates are unchanged: the player is drawn by the 68000 rather
than by the cartridge, or something region-based masks it. Note there ARE sprites
parked at raw X=0 in the captures, and X=0 is the Mega Drive sprite-masking
position - worth keeping in mind, though these captures are too broken to build on.

Getting further needs the sprite list as OUR firmware builds it, on hardware.
That is a cart-RAM read at `0xB00`, not a VDP tap - and it is still gated behind
the standing rule that no new bitstream is built for this without a decision.

# The VDP capture needs no compiler - use a savestate

Genesis Plus GX savestates already contain everything the capture was going to be
built for. From the source in `gpgx-build/core`:

    state.c      16-byte version "GENPLUS-GX 1.7.6", then work_ram[0x10000],
                 zram[0x2000], zstate, zbank, io_reg[0x10], then the VDP block
    vdp_ctrl.c   sat[0x400], vram[0x10000], cram[0x80], vsram[0x80], reg[0x20]

`reg[0x20]` is the full register file - 2, 3, 4, 5, 13, 16, 17, 18 - and `vram` has
the live SAT in it. So a savestate per scene gives the addresses **and** the sprite
list, including whether the player is in the table and with what priority bit.

**No debugger build, no BlastEm, no compiler.** This machine has no toolchain, so
this is also the only route that does not start with installing one.

    python scripts/parse_gpgx_state.py cellroom.state
    python scripts/parse_gpgx_state.py rooftop.state --sat-all

The parser anchors on the version string rather than computed offsets, so a
RetroArch container or zlib compression in front of the payload does not matter. It
was verified against a synthetic state with known register values before being
committed - every field decodes, including the SAT entry.

## What to capture

One savestate in each of the three rooms that matter:

    cellroom.state    the room a bad VRAM remap breaks first
    intercom.state    the INTERCOM walkway, the 53-slot scene
    rooftop.state     the bombing phase, mid-fight, player visibly behind scenery

The rooftop one is the important one, and it must be saved **while the symptom is
on screen** - the question is what the SAT says at the moment the player is clipped.

## What each answer decides

    reg 5 = 0x78          confirms the GPGX source read; SAT really is at 0xF000
    reg 13 (hscroll)      if it lands in 0xF800-0xFFFF, that is finally what the
                          old cap-49 was colliding with, and 53 slots would be
                          writing over it - which the hardware A/B says is not
                          visible, but it would explain the original suspicion
    reg 2/3/4 + reg 16    the real VRAM map, hence whether any hole exists for a
                          linear 53 - and 0x6400 is already known NOT to be free
    reg 17/18             window position. A horizontal window edge is the leading
                          suspect for the rooftop clip
    the SAT itself        is the player in the table at all? With pri set? If the
                          player is absent, it is 68k-drawn and outside everything
                          this port controls, which matches the probe result

## Running it

There is no RetroArch on this machine, but `src/genesis_plus_gx_libretro_x64/`
holds a Paprium-capable GPGX core already. Any RetroArch install can load that core
plus the ROM. Turn savestate compression off if the parser cannot find the payload,
though it handles zlib.

# RESULT: cap removed, 53 slots shipping - 2026-08-31

A/B run on hardware, cap 49 vs 53 on the **same** two-range map, firmware-only,
`8c82d458` against shipping `397b28eb`. Tester report:

    elevator shaft    THE SAME
    walks / anims     MUCH BETTER
    cell room, door   unaffected

**53 is now shipping.** `PPM_VRAM_SAFE_SLOTS` is `0x35`, the full request, and the
`+0x4b` jump is untouched so slots 49-52 still go to `0xF800`.

## What each half means

**The shaft did not move**, so nothing visible lives at `0xF800-0xFFFF`, or writing
tiles there does no visible harm. The cap did not buy the thing it was introduced
to buy. Combined with the SAT being at `0xF000`, the whole `0xF800` collision story
is now unsupported from both ends - wrong address, no observable effect.

**The walks got much better, and that is the real finding.** It also corrects this
file. The note added on 2026-08-30 said frozen walks were fill-rate bound and
therefore *not* helped by more slots. The mechanism it gave was right - more slots
help by retaining blocks the LRU would otherwise evict and reload - but it
dismissed that as "worth having, not the lever". On hardware it is a lot more than
worth having.

So the honest characterisation is **both limits are real and they bind different
things**:

    dma_budget, 10-16 blocks/frame   caps how fast a scrolling shaft refills
                                     -> the elevator, unchanged by slot count
    residency, 49 vs 53 blocks       caps how much survives between uses
                                     -> animation frames, much improved

A fast-scrolling shaft needs *new* blocks faster than the budget allows, and no
amount of residency helps. A walk cycle needs the *same* blocks repeatedly, so
residency is exactly what it wants.

## What this cost while it was in

Four blocks of residency game-wide, for about a day, on the strength of an
explanation that was wrong about the address and a result nobody had reported.
The animation quality it was costing is visible enough that the tester called it
"much better" the moment it was removed.

## Standing corrections

- **Do not re-cap without a hardware observation.** The route back is an
  observation, not an argument
- The remap to `0x6400` is still forbidden - the cell-room floor breaks, and that
  was a real hardware result
- `0xF800-0xFFFF` is still unidentified. It is not the SAT. It may be hscroll or
  unused. Nothing now depends on knowing

# cap-at-49 has lost its justification - 2026-08-31

Two independent things landed on the same day and between them there is nothing
left holding this change up.

**The target was misidentified.** The rationale was that slots 49-52 land on tiles
1984-2047 (`0xF800-0xFFFF`), "the sprite attribute and hscroll tables". The GPGX
read shows the SAT is DMAed to `0xF000` and ends at `0xF27F`. Whatever is at
`0xF800`, it is not the sprite attribute table.

**The benefit was not observed.** The record says "Elevator improved". Asked
directly, the tester's report is that capping made it feel **the same or similar,
not noticeably better**. That claim came from me, not from a hardware report, and
it has been propagating through this file and the README ever since.

So the current position on cap-at-49 is:

    claimed collision target   wrong - SAT is at 0xF000
    claimed benefit            not reproduced by the tester
    known cost                 four blocks of residency, game-wide, permanently

A change that costs four blocks everywhere and cannot show what it buys should not
be carried on the strength of the story that motivated it.

## What is NOT being claimed

Not that the cap is harmful, and not that there is no collision. `0xF800-0xFFFF`
may well hold the hscroll table (`reg 13`) or a nametable, and writing tiles over
it may well cause something - just not the thing that was written down, and not an
effect anyone has seen. The empirical instruction "do not send those slots back to
`0xF800`" was never based on the SAT reasoning and still stands on its own.

## The cheap test, when there is appetite for it

`PPM_VRAM_SAFE_SLOTS` is firmware, so this is a firmware-only build: fit metrics
identical to shipping, bitstream md5 different, no RTL touched.

    build 53 (uncapped) and A/B it against shipping in the elevator

    no visible difference        -> the cap buys nothing. Revert it and take four
                                    blocks of residency back game-wide, which is
                                    the one thing that helps the fill-bound
                                    symptoms even slightly
    uncapped is visibly worse    -> there IS a collision at 0xF800. The cap stays,
                                    and now it is justified by an observation
                                    instead of by a misread address

Either outcome is worth more than the current state, which is a change carried on
a withdrawn premise. **Standing instruction is that cap-49 stays and no new VRAM
bitstream is built without a dump - this does not override that.** It is here so
the decision is made on what is actually known.

## Process note

This is the second correction in a day where a tidy explanation outran the
evidence, and the same shape as the VM DAC filter theory: a mechanism that sounded
right, a fix that followed from it, and a claimed confirmation that nobody had
actually made. The tester's "it felt the same" is the measurement; my "improved"
was an inference wearing its clothes.

# Release gate for v0.2.0

**Decision, 2026-08-31: do not cut a release until the list below is closed or
explicitly verified.** Nothing downstream depends on shipping early, and a release
is the one step here that is hard to take back - people install it, and it becomes
the version bugs get reported against.

**`core.json` stays at 0.1.0 until publication.** It was briefly bumped to 0.2.0
on the reasoning that the version marks the build on the card; that was reverted,
because an unreleased core has no business advertising a version that was never
published. The number moves as part of cutting a release, not before it.

## The trap to avoid

Two open items are blocked on a VDP/SAT capture that does not exist yet. "Close
everything first" would therefore block a release indefinitely on work that is not
scheduled. So the gate is not "no open items" - it is **no open item that is
unverified, undocumented, or worse than the last release**.

Each item must reach one of three states - agreed 2026-08-31 - and be written
down as such:

    FIXED        verified on hardware
    CHARACTERISED  root cause known, documented, not fixable at this scope
    ACCEPTED     known, cosmetic or rare, listed in the README's Known issues

## Status against that gate

    IMA ADPCM music                FIXED, hardware-verified
    VM DAC static                  FIXED, hardware-verified
    Boom Box N vs N+0x80           VERIFIED - the menu is a flag UI, nothing unheard
    Auto-boot + save               FIXED, hardware-verified, save loads and writes
    Elevator scrolling squares     CHARACTERISED - fill-rate bound at 10-16
                                   blocks/frame from a ROM constant
    Frozen walk animations         CHARACTERISED - same cause, load_block failure
                                   falls back to previous_offset
    Intro pixel flicker            ACCEPTED - cosmetic, self-corrects
    Rooftop player/bombs behind BG  **NOT YET** - open, and the probe only ruled a
                                   cause out. Needs a SAT dump to reach
                                   CHARACTERISED
    cap-53 / VRAM remap            **NOT YET** - needs five VDP addresses

So **two items are short of the gate**, and both need the same emulator session.
Neither needs a fix to pass - reaching CHARACTERISED is enough, because both are
upstream-firmware symptoms present on other Paprium setups. What is not acceptable
is releasing with "we don't know" against a symptom a player will hit in normal
play, which is what the rooftop one is.

## Before any release is cut, re-verify on hardware

The build on the card has accumulated changes that were each tested in isolation.
Verify them together, from a cold boot, on a card prepared the way the README
tells a stranger to prepare one:

    boots straight in, no browser
    save loads, and a new save persists across a full core exit
    music plays, correct track per scene, one-shots stop rather than loop
    VM DAC toggle produces silence, not static
    Block 888 doorway palette correct
    stage clear / continue / game over cues audible
    punk-TV cue loops

Then confirm the packaged zip installs from scratch on a card that has never had
this core - the fixed filenames make a clean-card install a genuinely different
path from an upgrade, and it is the path a new user takes.

## Also outstanding, not blocking

- `README` and `INSTALL` describe auto-boot and fixed filenames. Both were written
  today and have not been read by anyone following them from scratch
- no git tag exists yet; `scripts/package_release.sh` has its `jq` dependency
  satisfied as of today

# RESUME HERE - 2026-08-31

## Shipping

    bitstream   397b28eb   build_output/paprium.rbf_r, on the card
    firmware    6efba936   rtl/PAPRIUM/mcu.txt, committed, patch reproduces it
    blob        PPAD, 543 MB. Old raw blob kept as paprium_raw.pcm.bak

    cap-at-49 | firmware 0x0100 -> srate+1 | IMA fetch/decode + PPAD
    field-wise door attrs | VM DAC stream-buffer fill

Fit: ALM 18,194 / M10K 294 / setup -2.596 / hold +0.004, seed 5. **M10K 294 is the
shipping fingerprint** (cmdlog is 308).

## Closed today, both hardware-verified

- **IMA ADPCM music.** 2.09 GB -> 543 MB, 3.94x. A stale raw blob now stays
  SILENT rather than playing as noise - the PPAD magic and every field the decoder
  hardcodes are checked before the table is walked. Buffering went 0.085 s ->
  0.337 s, which is why it sounds cleaner; the codec is lossy at ~38 dB and the
  samples are strictly worse. Do not shrink the ring to reclaim M10K
- **VM DAC static.** Cart RAM 0x1802-0x19FF is an unsigned 8-bit PCM stream
  buffer the 68000 pushes to YM2612 0x2A; we never initialised it. Filling with
  0x80 makes the path DC. The option is now inert rather than wrong - hardware
  also thins the mix and we do not reproduce that. Hardware-accurate design is
  written up above for a larger FPGA

## Open, and what each is actually blocked on

    cap-53 / remap            five VDP addresses + map sizes, cell room + INTERCOM
    player/bombs behind BG    SAT dump (is the player in the table?) + regs 3/17/18
    frozen walks / squares    NOTHING - fill-rate bound, 10-16 blocks/frame
    intro pixel flicker       unrelated, lowest value

Closed 2026-08-31: **Boom Box N vs N+0x80**. Swept with predicted pairs and a
saturated negative control - the top half is the same 127 rows with the rate-step
flag. Nothing unheard in the bank, and the mixer does not grow.

**No new Pocket bitstream for sprites or VRAM until a SAT/register dump exists.**

## Gates learned the hard way (all in BUILD_REFERENCE)

- **Firmware-only change: TWO conditions.** Fit metrics identical to the
  reference AND bitstream md5 different. Identical metrics with an identical hash
  is a void build, and the timing report cannot tell you - it cost a fit
- **Seed spread is 1.19 ns**, not the 0.25-0.55 assumed. One bad fit is not
  evidence a change broke timing. Re-seed before concluding; three or four seeds
  is data, ten is a lottery
- **Hold lives in the fast 0C corner.** Two seeds passed hold in the slow model
  and failed it fast. Read the multicorner summary
- **-2.596 boots**, so the untested band is now -2.596..-2.715

## Refuted today - do not retry

- **Static ROM scan for VDP register tables.** Only false positives; an 8 MiB ROM
  is full of ascending 0x8rvv-shaped data. Scene setup goes through DATENMEISTER
  and need not exist as plaintext
- **The LPF/mode-3 theory for VM DAC static.** This tree's md_ntsc plays Sonic 2
  drums correctly with CFG_LPF = 2'd3. Do not "fix" anything by enabling the filter
- **Blanket SAT priority.** Forced 0x8000 on every entry: other sprites came
  forward, player and bombs did not. Not SAT priority, which also rules out
  mega-ppm's whole-word XOR as the cause of that symptom

## Corrections worth keeping

Both were tidy stories that outran the evidence, and both were caught by hardware
or by a hash rather than by reasoning:

- claimed "identity fit confirms firmware-only" when the firmware had never
  reached the build - `build_mcu.sh` did not install, and now does
- claimed four slots of cap headroom would reduce frozen walks game-wide. Slot
  count is residency, `dma_budget` is fill rate; they are different limits

## 2026-09-02 - the subway capture: the relink pass was deleting sprites

`12415202` (the mask-pair build) was run on a rooftop attempt and passed through
the subway on the way. Sprites there were wrong, a capture was taken, and it says
something worse than mask ordering.

**The chain had lost a character.** Entries 14-19 are a 48x96 figure at screen
X 68-132, Y 69-165 - written to the table, on screen, and not reachable through
the link chain, so the VDP never drew it. The old decoder never mentioned it,
because every view it printed walked the chain and the chain is exactly what had
lost them. Both `decode_sat_snapshot.py` and `draw_sat_layout.py` now report
orphans; that is the change worth keeping out of the whole day.

**The links name the culprit:**

    6  -> 8      while  7  -> 8
    11 -> 20     while  19 -> 20

Predecessors rewired past a run of nodes, and the skipped nodes still pointing
exactly where they always did. That shape is only possible if **the 68000 writes
the link topology ONCE per scene and thereafter updates position and attributes
alone.** Nothing repairs entry 6. So every link the relink pass writes is a
permanent edit to the game's list, and a node dropped from the rebuild is gone
for the rest of the scene - which is why one bad frame showed as a missing
character for the whole subway.

**What dropped them.** `12415202` widened the mask test from `X == 0` to
`X & 0x1ff <= 1` to carry the partner sprite along. A character standing fully
off-screen left is parked at raw X 0 or 1, so six sprites of one figure were read
as six masks, `masks[8]` overflowed, and the overflow branch was

    if (nmask < 8) { masks[nmask++] = node; }   // else the node simply vanishes

`1ec0f2c3` (`== 0`) could not reach this. The header confirms the frame captured
had **0 masks moved** - the damage was done earlier and had simply persisted.

Two further unguarded drops in the same block, neither reached yet: the chain was
truncated at 80 when `sat_data` holds 144, and `visited[10]` was indexed by a link
byte that can legally name entry 143.

### The rebuilt pass

Two rules, both testable:

1. **The rebuild is a permutation.** Every flattened node appears in the output
   exactly once; no branch can drop one, and `m == n` is checked before a single
   link is written.
2. **Anything it cannot represent leaves the chain alone.** Cycle, link past the
   table, chain longer than the table, or a mask group larger than
   `PPM_MASK_GROUP_MAX` (5, which is hardware's rooftop group 32-36 counting
   partners) - all stand down without writing. A frame of lost mask ordering
   costs one frame; a wrong write costs the sprite for the scene.

X == 1 is now only adopted as a partner when it is chain-adjacent to a real X == 0
mask, never on its own. The capture header reports the pass: a plain number is
entries moved, `0xFFnn` means it stood down with `nn` the chain length it saw.

Run on the host against the subway frame and five synthetic cases before spending
a fit - a no-mask frame comes out identity, a parked-left figure stands the pass
down, a genuine three-mask group moves to index 32 and is idempotent on a second
pass, and cycle / out-of-range links stand down untouched.

**Open:** whether the rooftop and elevator gains from `12415202` survive a pass
that is this much more conservative. If the gain came from moving pairs and the
pair test now rarely fires, the gain goes with it - that is a real possible
outcome and not a reason to loosen the rules back.

### 2026-09-02, later - the cap was the wrong test, and a correction

`7d2ce1c0` on hardware: **subway fixed** - the tester confirms sprites are no
longer deleted - and **the rooftop regressed**. The capture explains it in one
line: `relink stood down, chain of 36 left untouched`. The pass wrote nothing.

The rooftop group is three masks **and their three partners** - six - against a
`PPM_MASK_GROUP_MAX` of five. That five came from reading the emulator's rooftop
group `32,33,34,35,36` as a maximum when it was a single observation. The pass
stood down on the exact scene it exists for.

**Counting was the wrong test.** Every mask in the rooftop capture is `1x4` with
tile `0x000`; the character the subway lost was tiles `0x7E0, 0x300, 0x7E8,
0x270, 0x0F0, 0x1B0` at `2x4/4x4/3x4`. A mask is a sprite parked off the left
edge to occupy scanlines with nothing to draw - **blankness is what it is**, and
unlike a count it needs no tuning. `PPM_MASK_TILE 0x000` is now the identity test
for both the mask and its partner; the cap survives at 8 as a sanity bound only.

Host-tested on the **two real captures** rather than invented cases, which is the
other lesson: the synthetic "parked character" had six sprites, which is exactly
what made a cap of five look safe, and the real rooftop group is also six.

    subway   hdr 0x0000   chain 17 in / 17 out, unchanged
    rooftop  hdr 0x0006   14-19 moved to after entry 32, all 36 preserved
    rooftop  run twice    identical - idempotent

Probe `648fdcd8`. ALM 18,194 / M10K 294 / setup -2.596 / hold +0.004.

#### Correction: "predecessor rewired past a run" never proved authorship

The subway diagnosis leaned on this shape as evidence the relink pass had done
the damage:

    6 -> 8    while  7 -> 8

The rooftop capture has `4 -> 8` past entries 5,6,7 and `8 -> 11` past 9,10 -
**with the pass standing down and writing nothing at all.** The game produces
that shape itself, typically on HUD it is hiding. The `masks[8]` overflow was
real and removing it removed the subway symptom, but the signature argument was
stronger than the evidence supported, and `reachable < composed` is no longer
reported as a failure by `decode_sat_snapshot.py` - it reports, and leaves the
judgement to what the orphans actually are.

### 2026-09-02, third build - stand-down means no write, and two corrections

`648fdcd8` in the subway: the figure is gone again. The capture (`sat_count 27`,
17 on the chain, header `moved 0`) was replayed through the algorithm on the host
and **the pass is a no-op on that frame** - it writes back the links already
there. It did not orphan entries 16-19, which carry real art (`0x7E0, 0x290,
0x7E8, 0x7C0`, 48x64 at X 168-216) and are on screen.

    on-screen, real tiles, off the chain   16,17,18,19 (the figure), 14, 15, 30
    HUD the game hides itself              9, 10
    parked junk at 360,-128 tile 0         7, 12, 13

**Correction: the `masks[8]` overflow was never supported by a capture.** Both
subway captures report `moved 0`, so that branch never executed in either. It was
a real latent bug and the permutation rewrite is worth keeping, but the causal
story was an inference from reading the diff, presented as though the capture had
shown it. Together with the "predecessor rewired past a run" correction above,
that is twice in one day that a tidy mechanism outran the measurement.

**And the comparison that would settle this no longer exists.** The card save was
wiped before the `7d2ce1c0` subway test, so there is no capture of the scene from
the build the tester reported good. Two readings remain open - the game leaves
16-19 unlinked in this pose, or an earlier frame this boot published a topology
the 68000 never repaired - and only that A/B separates them. **Keep every .sav.**

`6596070d` changes exactly two things, neither of them tuned:

- **`ngrp == 0` returns before any link store.** An identity rewrite is still a
  rewrite, and it is only identity if the walk was right. With nothing to gain
  there is no reason to accept the risk of a wrong head or a miscounted length
  publishing a topology the game will never repair.
- **Sticky run counters** in the capture - frames written, frames stood down,
  largest group seen. `moved 0` describes one frame; two captures in a row could
  not say whether the pass wrote anything earlier in the boot.

Cap stays 8, `PPM_MASK_TILE` stays `0x000`, `PPM_MASK_AFTER_INDEX` stays 32.

### 2026-09-02, control run - the relink WRITE is what blanks the subway

Symptom restated by the tester: **nearly every sprite disappears including the
player.** That cannot come from orphans - the captures show ~10 unlinked entries
out of 30, which is a figure or two. It is masking. A `1x4` sprite at X=0 covers
32 scanlines and hides every sprite LATER in the chain on those lines; three of
them on a Y ladder cover 136-231, most of the screen. Pull that block toward the
front and the room goes dark.

Measured on the rooftop capture, moving the group to the anchor:

    as the game built it :  9 hidden   22,23,24,25,26,27,28, 36,41
    after the move to 32 :  2 hidden   36,41
    freed 22-28, the whole player group; nothing newly hidden

Which is exactly why the same rule wrecks the station. `PPM_MASK_AFTER_INDEX` was
being applied in BOTH directions, and dragging masks forward is never the fix.

**Control `76d278e2`** - `PPM_RELINK_APPLY 0`, classify and count exactly as
normal, store nothing:

    frames the pass WOULD have written : 99
    links actually stored              : none
    tester: sprites present, nearly to the end of the subway

Against `6596070d`, same scene, writes applied, mass disappearance. The
classification fired 99 times, so the pass was fully engaged and only the store
was removed. **The write is the cause.**

The control also closes the gap that had kept this circular - the station's mask
group is real and is the same shape as the rooftop's:

    largest mask group seen : 6
    first mask              : 1x4 tile 0x000

(The `LINKS stored: 0` line in that capture is NOT evidence - the control
firmware predates the counter, so those header bytes are zeroed RAM.)

#### The rule, and the write set

    if the group's new position is not LATER than its current one -> do not write
    else                                                          -> splice, block intact

Compared as positions in the rebuilt list, not against `PPM_MASK_AFTER_INDEX`,
which is an absolute SAT index - comparing a chain position against it would only
work by coincidence. And the flatten stays as ANALYSIS while the store is now
minimal: only links that actually differ are written. On the rooftop capture that
is **3 stores**, the three a block move needs, instead of 36. Storing a whole
topology to make a three-link change is how one bad walk republishes a list the
68000 will never repair.

One-sided also makes the pass self-limiting: once the group has been moved it
stands down rather than rewriting, so a scene gets at most one write.

### Cross-checked against MisterPezz82/Paprium_MegaDrive_MiSTer

The MiSTer port of the same mega-ppm firmware has the same rooms open:

    #8  graphic errors in the Intercom elevator - corruption AND background
        priority problems                                          OPEN
    #10 animations skipped, "the more enemies on screen, the more problems"
                                                                   OPEN
    #5  v03 stuck at subway                                        OPEN
    #6  subway graphics corruption near the train                  closed

So the elevator and the density-dependent animation loss are not ours alone and
are unsolved there too. Their June fix - *"fix 0x81 decompression (subway etc.),
replacing MAME's broken heuristic"* - is the GPGX/FinalBurn LZO decoder we had
already ported into `case 0x81`, so nothing to take. Worth noting anyway: **the
subway has a history of corruption from a DECODE fault**, so if masking ever
fails to explain a station symptom, the decoder is the better next suspect than
the link chain.

Two of their changes to compare against ours later, neither in this fit:

- V.05 *"field-wise sprite attribute composition with the GPGX 0x7ff tile-index
  mask"* - close to the queued item that `ppm_spr_data.offset` is `uint8_t`
  where GPGX reads 9 bits
- V.04 *"MCU shares the console SDRAM (port 2, lowest priority) and was starved
  under dense scenes"* - independent support for the starvation theory behind
  the elevator

**Queued:** `'lz' may be used uninitialized` in the LZO decoder. Traced - it is
the `state == 0` literal path where `len = 0`, so `copy_addr` is computed and
never used. Undefined behaviour, harmless in practice, but it has been printed on
every build for weeks and a warning nobody reads is a warning that hides the next
one.

## 2026-09-02 - the root cause: we composed sprites in the wrong place in the frame

The whole mask investigation was chasing a symptom. The cause is one line.

    GPGX      case 0xAD: paprium_sprite(data);      composes immediately
    mega-ppm  ppm_obj_add -> queue; 0xAF renders the whole list

The game's real sequence is `0xAD` x17, write masks, more `0xAD`. GPGX interleaves
exactly that. krikzz's firmware defers every sprite to frame end, so everything
the 68000 writes mid-frame - masks included - is already in the table before the
cartridge appends anything:

    emulator  0-13 HUD/dummies  14-30 composed  31-36 MASKS  37+ composed
    before    0-13 HUD/dummies  14-19 MASKS     20-42 composed
    after     0-13 HUD/dummies  14-33 composed  34-39 MASKS  40+ composed

Entries 0-13 match the emulator tile for tile, so the 68000 was never behaving
differently - the ordering was ours. Masks now land at 34-39 against the
emulator's 31-36, **with nothing editing the list**. Mask coverage went from 9
hidden - including 22-28, the entire player group - to 3.

Tester: *"boss bombs and character in correct place... first time we have seen
subway and rooftop play clean."* Also fewer skipped frames and less floaty
enemies, which is the second consequence: `ppm_obj_render` samples `obj_data`
when it runs, so batching sampled every object at frame end and a slot reused
within a frame lost its first pose. That is the shape of the animation bug open
in both ports (MisterPezz82 #10).

**It was never SDRAM starvation.** `STARVE2_LIMIT` had already been A/B'd at 8 and
96 on hardware with the elevator indifferent in both directions.

**The relink is deleted, not disabled.** With the ordering fixed it wanted to make
things worse - the same capture shows it would have stored 1698 links across 574
frames, pushing the group out of the correct place. Gone with it: `ONE_WAY`,
`AFTER_INDEX`, `MASK_TILE`, `GROUP_MAX`, `RELINK_APPLY`, `MOVE_AFTER`, and
`PPM_MASK_PROBE` (it also wrote the SAT, moving mask `posY`). Firmware -950 bytes.
Nothing in the build writes the sprite table.

### The regression inline composition introduced, and how it was found

Destructibles stopped showing their destroyed art. The tester's wording is what
made it findable: **"still look undamaged"**, not "missing". An intact pillar is a
plane tile, so the sprite was not vanishing - its graphics never arrived.

    void ppm_obj_frame_end() {
        dma_remaining = dma_budget - dma_total;    // refresh
        while (...) ppm_obj_render(...);           // then render

The frame's DMA budget was refreshed in `frame_end`, immediately before the batch
- correct while the batch WAS composition. Moving composition to `0xAD` left every
inline render testing the PREVIOUS frame's leftover budget, already spent. It
gates one path:

    if (dma_remaining < 0x110) return 0;      // block never loads

Resident art hits the slot cache and returns before that check, which is why
everything else looked right and only a NEWLY needed block starved - a pillar
smashed for the first time being exactly that. `ppm_dma_refresh()` now runs in
`frame_start`, before any `0xAD` can arrive.

**Open caveat, from the reviewer:** if the 68000 writes `dma_total`/`dma_budget`
AFTER `0xAE`, the refresh is now too early and starves the same way. The
falsifier is in the build - if pillars stay whole while "refused, out of DMA
budget" is still high, log both words at `0xAE` and at the first `0xAD` rather
than moving the call again on a hunch.

### Instruments that replaced the guesses

    anim-over drops                      0 - REFUTED the early-out suspect outright
    block loads refused, DMA budget      the starvation path
    block loads refused, slot full       PPM_VRAM_SAFE_SLOTS pressure, a different bug

### Corrections from this day, all worth keeping

- the `masks[8]` overflow story was never supported by a capture. Both subway
  captures read `moved 0`, so that branch never executed in either
- "predecessor rewired past a run" never proved authorship; the game does it
- a mask group of six `1x4 tile 0x000` entries was read as proof the station had
  real masks. It was a figure parked off-screen left with blank tiles
- the mask-group cap of 5 came from reading one emulator observation as a maximum
- and the card save was wiped before the one A/B that would have settled the
  station, which is why it stayed open for four builds. **Keep every .sav.**

#### Correction: the DMA mechanism is NOT settled

The `139e931f` change was described above as "refresh the budget at frame start so
inline renders see a fresh budget". The `26370eff` capture undermines the second
half of that:

    block loads refused, out of DMA budget : 2983
    block loads that SUCCEEDED             : 86935
    refusal rate                           : 3.3%
    in-game frames                         : 0        <-- counted in frame_start

Those header bytes are written unconditionally, so 0 means the counter was 0, not
that the write was lost - checked against the raw tail of older captures to rule
out the end of the save being reserved. But `frame_start` is also the only place
slot usage is cleared for ACTIVE slots (`ppm_vram_reset_blocks` only touches slots
above the budget), and slot-full is 0, so slots are plainly being freed.

So one of two things is true and we do not yet know which:

1. `frame_start` runs and the counter is broken in a way not yet visible, or
2. **`frame_start` does not run per frame**, something else frees slots
   (`ppm_obj_reset` -> `ppm_vram_reset_blocks(0)` is a candidate), and therefore
   `ppm_dma_refresh()` there never executes at all

If (2), the pillar fix came from the OTHER half of that change: `frame_end`
STOPPED refreshing `dma_remaining` under inline. That would mean our frame-end
write had been clobbering a value the 68000 maintains itself and starving the
next frame's inline composition - a different mechanism from the one recorded
above, reaching the same fix by accident.

The visual results are unaffected: pillars smash, masks ~34, station and rooftop
clean, refusal rate healthy. **The fix stands; the explanation does not.** Do not
cite the frame-start reasoning until the dispatch counts exist.

**Offset check, done before any theorising (2026-09-02):** firmware writes
`frames` to bram `0xFF5..0xFF8` (`t[13..16]`, `t = b[1752]`, `SNAP_BASE 0x910`)
and the decoder reads file `0xFF5..0xFF8`. They match, `loads_ok` sits
immediately before at `0xFF1..0xFF4` and reads correctly, the preceding memcpys
end at `0xFE7`, and the last byte is inside the 4096-byte save. So it is NOT a
header-packing or length miss - the zero is real. That eliminates one
explanation; it does not establish that `0xAE` is dead, and the note above stands
as written until the dispatch counters exist.

### 2026-09-02, elevator on the inline build

Tester: **the background enemy now scrolls correctly and the player no longer
drops into the background.** Squares unchanged. So the elevator's depth problems
were the same sprite-ordering bug as the rooftop and the subway - one cause, three
scenes.

**Not** "half of MisterPezz82 #8". #8 IS the tile corruption - the floor band that
climbs with the plane until INTERCOM COMPLETE - and it is untouched and still open.
What was fixed here is a DIFFERENT bug that lives in the same level: sprite mask
ordering. Same hallway, not the same fault. Keep the labels apart:

    SAT masks landing too early (0xAD batched at 0xAF)   FIXED in 0.1.0 -
                                                        subway, rooftop, elevator depth
    Pezz #8 shaft / INTERCOM COMPLETE garbage            OPEN, pre-existing,
                                                        stream window next
    leftover walk skips                                  OPEN, fill / density

The elevator-only capture also gives the first direct measurement of the shaft's
DMA behaviour, and it does not say what the README's derivation implied:

    elevator only          829 refused of 25413 attempts   3.3%
    subway -> rooftop     2983 refused of 89918 attempts   3.3%

Identical. The shaft does **not** starve the block loader relative to anywhere
else. **But that counter lives in `ppm_block_load`, which handles SPRITE blocks,
and the squares are plane tiles** - background streaming may take the stream-window
path, which this never sees. So it rules the loader out and settles nothing about
the squares. The README now says exactly that rather than either claim.

Worth doing when the squares are next picked up: a counter on the background
streaming path, so the ceiling is measured rather than derived from the
2,816-4,608 words-per-frame arithmetic.

## 2026-09-03 - full playthrough captured, and TWO SEPARATE things

52 minutes of OBS capture at 1080p60, sampled at one frame per minute across the
whole run. **These are two different problems and must not be merged.**

### 1. Elevator shaft garbage - PRE-DATES 0.1.0, this is MisterPezz82 #8

A band of wrong tiles appears at the floor of the shaft, **climbs upward with the
background and accumulates until the end of the level**, and the INTERCOM COMPLETE
screen after it is corrupted too. Tester confirms he has seen this before 0.1.0
and that it matches #8. **The sprite-ordering fix did not cause it and does not
address it.**

    9:10   clean
    9:21   one band of garbage at floor level, second enemy just spawned
    9:24   grown to fill the lower half, third character present
    ~10-11 INTERCOM COMPLETE screen corrupted

Everything else in the run is clean - streets, arcade, alleys, hangar, boss.
**Confinement to one section is itself evidence**: any runaway pointer or growing
per-frame drift would degrade every busy scene downstream, and nothing downstream
degrades.

The garbage is *recognisable artwork from elsewhere*, not flat stale fill, and it
moves with the plane rather than flickering in place. That points at the **stream
window** - the 68000 DMAs graphics from cart `0xC000-0xFFFF`, which the RTL
redirects into SDRAM at `0x400000 + stream_ptr/2`, advancing two bytes per
delivered word (`paprium_cart.sv`). That file already carries a fix for this
pointer desyncing once.

**`ppm_block_load` is the wrong meter for this.** It measured 3.3% refusals in
this exact scene, identical to the rest of the game, because it serves SPRITE
blocks. The background path is unmeasured. The next instrument belongs there -
`stream_ptr` read back versus what the MCU set - and `fpgio_sptr` is currently
**write-only**, so that needs a read path in RTL. NOT another SAT rewrite.

### 2. Cursor split - a real hygiene bug that inline compose introduced

Two cursors must start each frame together and advance in lockstep:

    ppm_block_unpack_addr = 0x9000    MCU WRITE cursor  (where blocks unpack to)
    FPGAIO->sdram_ptr     = 0x9000    68000 READ cursor (where the DMA reads from)

Both used to be reset in `ppm_obj_frame_end`, two lines apart. `PPM_INLINE_COMPOSE`
moved the write cursor to `frame_start` (`0xAE`) and left the read cursor in
`frame_end` (`0xAF`). **They are now reset by different commands.** If `0xAE` is
ever flaky the write cursor climbs while the read cursor resets, and the 68000
reads the previous frame's data.

Fix: put the unpack reset next to `sdram_ptr` in `0xAF` **and** keep it on `0xAE`.
Harmless if both fire, required if either does not.

**This does not explain problem 1** and must not be sold as its fix: a growing
AE/AF gap would smear every busy scene, and 48 minutes of streets are clean.

### The instrument contradiction, still open

`frames = 0` (counted inside `ppm_obj_frame_start`) against `noslot = 0` (which
requires that same function to run, since it is the only place active slots are
freed - `ppm_obj_reset` runs only from `cmd_81_init`, and `ppm_vram_reset_blocks`
only touches slots above the budget). The offset check passed. `deb45ef5` counts
`0xAE` at the dispatch site in `paprium.c`, one call earlier than the tick.

    0xAE >> 0            the frame tick is a header bug; cursor patch is latent
    0xAE ~ 0, 0xAF >> 0  ship 0.1.1 with both resets, retest depth AND shaft
    refuse still ~3%     keep looking at the stream window, not ppm_block_load

**0.1.0 is not held for #8.** The depth and mask fix stands on its own.

### 2026-09-03, dispatch capture - the anomaly was my instrument

    0xAE frame start : 30585
    0xAF frame end   : 30584          one fewer, a frame in flight
    0xAD sprite draw : 231046
    ppm_dma_refresh  : 0
    frames (tick inside frame_start) : 0
    block loads refused / succeeded  : 851 / 25899   = 3.2%, elevator only

`0xAE` is dispatched reliably. The two counters reading zero sit **above** the
`#define PPM_SAT_SNAPSHOT` in the file:

    650  ppm_dma_refresh()      snap_cnt_refresh++    line 652
    691  ppm_obj_frame_start()  snap_frames++         line 694
    744  #define PPM_SAT_SNAPSHOT
    1284                        snap_loads_ok++       compiled in, works

**A guard placed above its own `#define` is silently false.** Those increments
were never compiled into the firmware. They read zero because the code does not
exist, not because the functions do not run. The define now lives at the top with
every other switch.

**What it settles:**

- `ppm_obj_frame_start` runs every frame, so `ppm_block_unpack_addr` **is** reset
  every frame. The twin-cursor split is **latent only** and has never bitten
- `ppm_dma_refresh` runs at frame start, so the mechanism recorded for the
  destructible fix in 0.1.0 is **correct** - the earlier "unproven" caveat above
  is now resolved in its favour
- refusal rate **3.2% inside the corrupting scene**, the same as everywhere.
  `ppm_block_load` is confirmed as the wrong meter for the shaft. Next instrument
  is `stream_ptr` read-back versus what the MCU set, which needs a read path on
  `fpgio_sptr` in RTL

**The reasoning failure worth keeping.** The write offset was checked, the zero was
declared real, and two theories were built on it - one briefly implicating the
shipped release. The counter was never checked for being *compiled in*. Same class
as reading a stale fit summary: one gate verified and treated as proof. And
`noslot = 0` contradicted the whole line from the start; it was noted and then
argued around instead of believed.

Queued for 0.1.1, not shipped hot: the twin cursors are now reset together in
`0xAF` as well as `0xAE`. Firmware moves 3815042f -> 245749f8, so master no longer
rebuilds the release byte-for-byte - the `0.1.0` tag is the reproducible point.

## Queued experiments

Not started. Recorded so they are not re-derived, and with what is already known
about each so nobody spends a fit finding it out again.

### The timing wall is VDP -> Z80, not the 68000

Measured 2026-09-03 with `quartus_sta` on the shipping-timing build, after five
fits had been spent reasoning about area and mux levels without once reading the
failing path. **Read the path report first next time.**

    -2.549  ym7101:vdp|prescaler_dff11  ->  z80cpu:z80|z80_dlatch:dw293
    -2.398  ym7101:vdp|mclk_clk3_l      ->  z80cpu:z80|z80_dlatch:dw293
    -2.361  ym7101:vdp|prescaler_dff11  ->  z80cpu:z80|z80_dlatch:dw293
    -2.339  m68kcpu:m68k|w68            ->  m68kcpu:m68k|w980[4]
    -2.290  m68kcpu:m68k|w67            ->  m68kcpu:m68k|w980[4]

The three worst are VDP clock-prescaler flops into **Z80 transparent latches**.
The first 68000-internal path is fourth, 0.2 ns better than the worst.

### Experiment: reverse-engineer the MWMM synth

**On its own branch, after #8.** This is the cartridge's music hardware - the part
that has never been dumped and the reason the port substitutes the released
soundtrack. Reproducing it would remove that substitution entirely.

Targets named so far: the **sax layer**, the **crisis cue `0xD6`**, and **hit
pitch**.

    have    the wave bank, 52 decompressed modules, and the header
    need    the sequence body, the program table, and 26-voice RTL

**Start offline; nothing here is gated on silicon.** The sequence body, the program
table and a host renderer (`tools/gpgx-render` path) need **zero ALMs**. That work
is useful whether or not headroom ever lands, and it is the part that has to exist
before any RTL question is even well-posed.

FX68K is a prerequisite only for **26 voices running on the Pocket** - the last
step, not the first. Cost the RTL before scheduling a ship, not before starting.

**Serialisation against #8 applies to firmware instruments and card captures, not
to offline work.** No second MCU probe until the CRC card closes, because two
instruments in one capture make both ambiguous - that is how the elevator depth
bug and Pezz #8 stayed conflated for weeks. Script-side module work shares nothing
with the card and can run in parallel.

### Experiment: swap nuked-md's 68000 for FX68K

**Status: queued, and the measurement above says it will NOT fix timing.** Even a
zero-delay 68000 leaves the critical path at -2.549, because the worst paths never
touch the CPU. It would free area - `nuked-md/68k.v` is 6,299 lines of gate-level
Verilog against FX68K's far more compact microcoded design - but **area was
measured not to buy timing on this design** (see BUILD_REFERENCE.md: 1,600 ALMs
and 40 M10K freed, setup did not improve).

**The reason to do it is ALM HEADROOM, stated by the tester: room to fit future
instruments, not to fix a bug.** That is the right justification and it should not
get resold as anything else later. Several probes this project needed could not be
built because the fitter had no slack - not because the 68000 was on the critical
path.

Keep all three caveats attached:

- worst STA paths are VDP -> Z80 latches, not the 68000, so extra ALMs will not
  move -2.549 on their own. `nosfx` already freed 1,600 ALMs and setup got *worse*
- headroom is still genuinely useful: instruments, IMA work, a second decoder
  buffer - the things that failed for want of slack
- the risk is bus timing on the mailbox, the DMA cadence and the stream window,
  so the gate is a **full playthrough** (boot -> cell -> subway -> elevator ->
  rooftop), not a synth check

**When:** after #8 has a firmware-only next step, or when a probe is needed that
demonstrably will not fit on `nuked-md`. **Not** in the middle of a capture series.

**Identity rule if it happens:** new seed table, hold > 0, setup not Probe-B-v1
class, then hardware smoke. A compatibility failure means revert - do not start
tuning Paprium around FX68K in the same week, or neither change can be attributed.

**The risk that has to be weighed:** this core uses `nuked-md` because it is
transistor-accurate, and Paprium's cartridge protocol is bus-timing sensitive -
the MCU mailbox, the DMA cadence, the stream window. FX68K is an excellent
microcoded 68000 but it is a different model of the same chip. That is a
compatibility gamble on the one game the core exists to run.

### Open question: what is the Z80 doing?

Unresolved, and **not answerable by reading the source** - it is a runtime
property. It matters because it sits on the wrong end of the three worst paths.

What is known:

- it is the stock MD Z80, `nuked-md/z80.v`, 4,091 lines, instantiated inside
  `md_board.v` - the CONSOLE model, not our cartridge
- `md_board.v` has **no PAPRIUM parameter**; it is shared verbatim by the ntsc,
  pal and paprium variants. Removing the Z80 for Paprium alone means
  parameterising upstream console code every variant depends on
- the failing endpoints are `z80_dlatch` transparent latches, which timing tools
  analyse conservatively - so -2.549 may not be the physical margin it looks like
- Paprium does its own 8-channel PCM on the cartridge, and the 68000 writes the
  YM2612 directly for the VM DAC path, so the Z80 may be idle or held in reset.
  Most MD games do run a Z80 sound driver. Both readings are live

Settling it needs a runtime measurement, and every cheap one is RTL - which is the
wall itself. Do not guess at it in either direction.

## 2026-09-03, end of day - the POINTER CHOREOGRAPHY is coherent. That is all.

Six mechanisms examined inside mega-ppm, all cleared. The picture that emerged is
coherent and, as far as every measurement goes, correct behaviour.

    0xDA with dst = 0     unpacks a payload at SDRAM offset 0. ppm_unpack writes
                          as far as the stream expands - tens of KB
    0xDB x947             reads 0x80..0x7F80, inside that payload
    six loads, ~158       reads each: load a chunk, stream it out, load the next
    sprite pad            starts at 0x9000 and NEVER overlaps 0x0000..0x7F80

**The collision is dead arithmetically, not just statistically.** The background
payload and the sprite scratch pad do not share a byte. The scattered stale hits
(61 then 42, only 2 on any one address) were telling the truth both times.

### What was ruled out, and how

    SAT ordering                fixed in 0.1.0 - a different bug in the same level
    sprite-slot eviction        peak 8/frame, steady 0.78, and slots never own
                                tiles 800-863 where background art lives
    0xAF clobbering a live 0xDA 0 clobbers; 0xDB 1109 vs 0xDA 49; 43-44 of the
                                0xDAs already targeted 0x9000
    same-frame pad collision    INVALID CHECK - ppm_block_unpack_addr resets every
                                frame, so it could only see same-frame overwrites.
                                Result discarded, not counted
    cross-frame pad collision   42-61 of ~1100, scattered. Ordinary sprite traffic
    the below-0x9000 region     legitimately written by 0xDA to dst 0

### Two mistakes worth keeping

**`dst = 0` was treated as an idle marker.** It was assumed for `0xDB` early on and
carried into `0xDA` untested. Zero was the actual destination, and the assumption
hid the answer for two captures.

**The decoder suppressed an all-zero list** with `if any(six)`, when zero was the
measurement. A suppressed zero is a hidden result; it now always prints.

### What is actually proven, and what is not

**Proven:** the pointer choreography is coherent - load at 0, stream it out over
~158 reads, repeat. Destinations, ordering and the SDRAM layout all check out, and
the sprite pad cannot collide with the payload.

**NOT proven, and the earlier heading claimed it:** that the BYTES are right, or
that they land in the right place in VRAM. "The path is clean" overshot by exactly
that much. Two things remain firmly inside firmware scope:

- **a wrong `src` in a `0xDA`** would produce a perfectly well-formed payload of
  the WRONG DATA, streamed through a pointer sequence that measures as flawless.
  Every counter built today would read healthy. This is still a stream/firmware
  bug and it is not ruled out
- the VDP DMA destination, and the plane's name table, are downstream

The cheap next step for the first is firmware-only and mirrors what was just done
for `dst`: **record the `src` argument of each `0xDA`**, and whether it repeats or
advances. A `src` that does not move between chunks, or repeats across scenes,
would show up immediately.

### Downstream candidates

- what the 68000 does with the streamed bytes - the VDP DMA destination
- the decompression itself: wrong `src` in a `0xDA`, giving a correct-looking
  payload of the wrong data
- the plane's name table, which the cartridge never touches

The first two are still firmware-observable. The third is not, and would need the
kind of tap that does not fit - see `docs/attempts/`.

### Closed 2026-09-03: the full-health stage clear does not exist

Removed from the known-issues list in both README.md and docs/INSTALL.md. The
tester has verified there is no different stage-clear cue at full health **in the
original game** - the behaviour being chased was never real, so there was nothing
for this port to be failing to reproduce.

It had been carried as "not reproducible - the variation is inside the cartridge
synth's own render of one track", which was a plausible-sounding explanation for
a phenomenon that does not occur. The earlier investigation notes above are left
in place because the YM2612 work they sit alongside is still valid; only the
claim that a full-health variant exists is withdrawn.

Worth noting the shape of the error: an unverified report was written into the
user-facing issue list, then given a mechanism that made it sound understood.
Nobody checked the premise against the original hardware until now.

### 2026-09-03: the 0xDA sources are sane

    51 recorded, 46 distinct, 1 consecutive repeat
    expanded range 192 .. 32768 bytes
    sources seen repeatedly: 0x0069A0F8, 0x0069A686 - the game revisiting tilesets

One consecutive repeat in fifty-one is noise, not a source that stopped advancing.
The decoder's verdict branch fired on `rep > 0` and had to be raised to `rep * 10 >
n`: a diagnostic that over-reports is worse than none, and this one would have sent
us chasing an artefact of its own threshold.

**A consistency check that lands:** the largest expanded payload is 32,768 bytes,
exactly `0x8000`, and the `0xDB` feeder reads `0x80..0x7F80`. A full-size chunk
decompresses into `0x0000..0x7FFF` and every read sits inside it. Two independently
measured numbers agreeing that precisely is good evidence the load-and-stream
picture is what it appears to be.

So the remaining firmware-observable candidate is not the pointers, not the
destinations, and not the sources - it is whether the BYTES those sources produce
are correct. That is the CRC-vs-GPGX card: decompress the same source in both and
compare. Not VDP or the name table until that is done.

## 2026-09-04 - the unpack is byte-correct. #8 leaves the stream path.

The CRC card (`4b80ff01`) ran an elevator descent to the first band. It
recorded 48 `0xDA` unpacks - source, expanded length, and a CRC32 of the
expanded bytes. Every one of them matches the reference decoder.

### How the comparison was made, and why it needed no gameplay

The plan of record was a live GPGX twin: play the same scene in the emulator,
hash `decoder_ram` the same way, compare. That was more work than the problem
needs. The unpack is a **pure function of the compressed bytes at `src`** - it
does not depend on scene, frame, or anything else about the run. So the twin
does not have to reproduce anything.

`tools/da-twin/da_twin.c` lifts `paprium_decoder_lz_rle` and
`paprium_decoder_lzo` verbatim out of GPGX `cart_hw/paprium.h`, makes them
return the produced size, and hashes the result with the same CRC32 as
`snap_crc32()` in `mcu/mame.c`. Feed it the source addresses the hardware
recorded and the answers must agree byte for byte.

Validity condition, worth stating because it is the thing that could have made
this comparison meaningless: both implementations apply a `^1` endian swizzle
to source **and** destination, but GPGX swizzles relative to
`decoder_ram + offset` while the firmware swizzles the absolute SDRAM address.
Those agree only while the destination is even. Every destination ever recorded
(`0x0000` and `0x9000`) is even. If that stops being true the comparison is
invalid.

ROM byte order was not assumed either. The twin runs both ways and the result
picks itself: **0 of 45 sources decoded as-is, 45 of 45 byteswapped.** A wrong
convention does not produce subtly wrong output - it walks off the end of the
image or hits an unknown type byte, and the harness bounds-checks for exactly
that.

### The result

```
  match 48   mismatch 0   no-decode 0   of 48
```

Both the length and the CRC agree on every record. Forty-eight independent
32-bit hashes do not coincide by accident.

**The MCU unpack is byte-correct.** #8 is not a decompression fault. Combined
with the pointer choreography already shown coherent on 2026-09-03, the whole
firmware stream path is now measured correct end to end: the right bytes are
produced, at the right length, and the pointer lands where the MCU finished
every frame. What remains is **where those bytes go afterwards** - 68000->VDP
DMA and the name table.

### A lead that closed on the way

The decoder had been narrating that `0xDB` re-points below `0x9000` aimed at a
region "the firmware never unpacks anything" into, and offering an unknown
writer as the explanation. That is false, and this capture proves it: six
payloads landed at `dst 0` at 16384-32768 bytes each, and a 32768-byte payload
covers `0x0000..0x8000`, which contains **every** read base observed
(`0x80..0x7F80`). Those are ordinary reads of bytes the firmware wrote. The
narration is corrected in the script.

### Two instrument faults found in the same pass

- The "0xDA destinations that were not 0x9000" section shared an offset with
  the new CRC arena and was printing record 0's `src`/`len`/`crc` as if they
  were destinations - which is where the nonsense value `0x6261E9B8` in that
  list came from. It is record 0's CRC. Section removed; the `dst` column of
  the CRC table carries the same information per record and is measured.
  This is the **third** time a reused offset has manufactured a finding.

- The fence agrees with record #42 exactly - and that is trivial, not
  corroboration. The fence refreshes immediately after any `0xDA` that expands
  inside the region, #42 is the last such payload, and it is full-size, so the
  two hash the same bytes. One measurement reported twice. The caveat was
  already written down in `CRC_SNAPSHOT.md` before the run; the script now
  prints it rather than relying on someone remembering.

To make the fence say something it would have to be taken a known number of
frames **after** the last full-region unpack. It is not currently stamped, so
its 40-frame age cannot be separated from the refresh. That is cheap to fix if
the fence ever becomes the interesting instrument.

### Hardware observation the same day, not yet measured

Before the squares appear, a few background tiles look **misplaced** - roughly
half a second of wrong position, then the band fills in. Two phases, and the
order matters: wrong *placement* first, wrong *pattern* second.

That is consistent with what the CRC result says. If the bytes are correct but
tiles appear in the wrong place, the fault is in **where art lands or which
tile the name table points at**, not in what was decompressed. The two
independent lines agree, which is the first time anything about #8 has had
that. It is still one observer's recollection of two runs and has not been
captured - it is a lead, not a measurement.

### The onset-ring card, and its read criteria fixed IN ADVANCE

Written before the capture exists, deliberately. Every wrong turn in this
investigation has been a number read after the fact and fitted to the theory
that was already in hand - the `masks[8]` overflow, the mask-group cap of 5,
the "predecessor rewired past a run". The criteria below are the reviewer's,
agreed while the fit was still running, and they are not to be renegotiated
once the numbers are on the table.

**Budget dips - or a refusal spike - in the last ~0.5-2 s against the sticky
baseline** -> starvation owns the band. `ppm_vram_load_block` returns 0, the
block never loads, the plane renders stale tiles.

**Flat through the half-second of misplaced tiles** -> not `dma_budget`. The
block cache was behaving normally while the band formed, no further slot or
budget knob will move it, and the next suspect is land/index: 68000->VDP
destination and the name table.

Between those two - the decoder prints 1.5x to 3x as inconclusive and says so
rather than picking a side. If that is the result, the question is whether the
elevated frames are **contiguous** (an onset) or **scattered** (ordinary
scrolling load pressure), and the timeline answers it directly.

#### Why byte 1 is the signal and the refusal nibble is not

`dma_remaining / 0x110` is the refusal test's own input. The refusal count is
downstream of it and depends on a load having been **attempted** - a frame can
be fully starved and record zero refusals simply because nothing asked that
frame. Where the two disagree, byte 1 is right. This is the same class of
mistake as the same-frame collision check that returned zero by construction.

#### What this card cannot decide

The ring counts pressure. It cannot tell **wrong place** from **wrong picture
in the right place**, and those are different bugs pointing at different
suspects - name table or scroll for the first, an overwritten VRAM slot for
the second. That separation needs the phone-cam of the half-second before the
squares, and no firmware counter substitutes for it.


### Onset ring, run 1: FLAT. Starvation is not the mechanism.

Read against the criteria fixed above before the capture existed.

    ring          480 frames, 26830 committed (1:1 with frame_start - not stalled)
    dma_budget    2816 -> 10 blocks/frame from full
    whole run     683 refusals / 26830 frames = 0.0255 per frame, worst frame 22
    last 480      0 refusals, 32 loads, 0 frames ending with zero blocks payable

    frame  -126 -120 -114 -108   -72  -66      (relative to quit)
    loads     5    6    6    5     5    5
    left      3    2    1    2     3    2      blocks of budget after

Six load bursts of 5-6 blocks each, in two pairs six frames apart - the two
enemy drops - and every one paid for with budget to spare. Then 66 frames of
nothing. The block cache handled every request in the window. Byte 1 - the
refusal test's own input - never hit zero. Not `dma_budget`, not slots, and
no further knob on the block cache will move the band.

Run-to-run the sticky counters are reproducible to a few percent against the
CRC card's run (683 vs 737 refusals, 0.81 vs 0.79 loads/frame, 50 `0xDA`,
1173 `0xDB`), so the window is not a fluke of one playthrough.

#### Correction: the stream-pointer audit has never measured anything

`decode_sat_snapshot.py` printed **"frames where it did not land where
expected: 0 -> the pointer landed exactly where the MCU finished, every
frame"** on the CRC capture and again on this one. Nothing in `mcu/mame.c`
writes `t[17..22]`. The reader was added by `385115d` (2026-09-03), the
commit that *parked* the RTL read-back after five failed fits - the writer
lived in that read-back and was never fitted, never committed. The bytes are
zeroed on every capture. The line is retired in the decoder and marked NOT
MEASURED; it is not cited anywhere in docs/, only in chat, where it was used
to rule out pointer desync. **Pointer desync is not ruled out. It has never
been observed either way, because the firmware cannot read the pointer.**

#### Where that leaves #8: the pointer, and a real asymmetry with GPGX

With the block cache cleared and the payload bytes verified (CRC card, 48/48),
the stream path has one remaining moving part the firmware cannot see: the
RTL's read cursor.

**Two different models of the window.** GPGX (`paprium.h:2579`) serves
`0xC000-0xFFFF` as a *page*: on a read at exactly `0xC000` with data pending
it copies the next `0x4000` bytes (mode 2; `0x800` in mode 7) into the
mirror, bumps `decoder_ptr` by the page size, and the 68000 then reads inside
the page with no per-read advance. The Pocket RTL (`paprium_cart.sv:98`) is a
*tape*: every delivered word advances two bytes, whatever address was read.
The real cartridge is a tape too (`mega-ppm/fpga/sdram_io.sv:50` advances on
each `cpu_oe` falling edge), so the tape is the original and GPGX the
approximation - the game must read sequentially or GPGX would break. The
models agree only while the count of delivered words is exact.

**How the count can be wrong on the Pocket, from the RTL's own comments.**
`cartridge.sv:225` has `sdram_rd = cart_oe`, and the SDRAM request issues on
a rising edge of `cart_oe & cart_cs` (`cartridge.sv:248`). The comment at
`cartridge.sv:530` states that the cycle-accurate VDP *glitches* `cart_cs` /
`cart_oe` within a single DMA word, and that counting the combinational
`stream_cs` edge double-counted those glitches - with the symptom recorded as
"per-pixel tile noise on backgrounds while resident font/UI stayed clean".
The fix moved the count to the SDRAM ack. But the ack is produced by the same
rising-edge detector: a mid-word glitch that re-arms it issues a *second*
SDRAM read for the same 68000 word, which completes, acks, and advances the
pointer twice. The fix removed the bus-strobe double count, not the
request-issue double count. Whether the residual rate is zero is exactly
what nobody has measured.

Clock domains: `cartridge.clk` = 53.69 MHz (`clk_sys_53_69`), `clk_ram` =
107.39 MHz (`clk_md_107_39`), 2:1; the 68000 bus originates in the 107.39
domain (`md_board.v`, everything on `MCLK2`). The ack crosses 107.39 -> 53.69
as a toggle, which loses a flip if two acks land in one 53.69 period - but an
SDRAM read spans many 107.39 cycles, so that path is unlikely. The
double-issue path is the credible one.

**Why this fits the symptom.** A drift of one word shifts every subsequent
tile fetched through the window by two bytes until the next `0xDB` re-points
the cursor - a small displacement first (the "misplaced tiles" the tester sees
seconds before the squares), growing with each further miscount until the
plane is fetching garbage (the squares), then reset by the next re-point.
Two-phase, timed, and `0xDB` fires ~23x per `0xDA`. It also predicts the
phone-cam answer: **right picture in the wrong place, shifted** - not a wrong
picture in the right slot. That prediction is on the record before the
footage.

**The next card is a 68000-side counter, not another MCU instrument.** Count
delivered stream words (`paprium_stream_read_ack`) since the last MCU write
to `fpgio_sptr`, latch it into a register the MCU can read through the
existing FPGAIO path, and have the firmware record on each `0xDB` how many
words the RTL delivered against how many the game should have consumed. A
counter and a latch, not a second `data_unloader` (that is what cost the
cmdlog build 1,217 ALMs and -3.141). This is the read-back that was refuted
five times - but the refuted version read the *pointer* back live; a
per-epoch word count latched on the MCU's own write is a smaller thing and
has not been fitted. Gate stays: setup >= -2.60, boots, full playthrough.


### The epoch-counter card, and its read criteria fixed IN ADVANCE

The tester's answer to the one question only they could settle: the tiles in
the seconds before the squares **looked shifted** - right art, wrong place.
That is the tape prediction, made on the record before the answer. It does
not prove the tape; it rules out the overwritten-slot reading of the same
footage and makes the cursor the thing to measure.

**What the card measures.** An *epoch* is the interval between two MCU writes
of `sdram_ptr`. On each write the RTL (`paprium_cart.sv`, next to
`stream_ptr`) latches two counts for the epoch that just ended:

    ack   completed SDRAM reads - the events that advanced the pointer
    oe    68000 read strobes inside the window, counted the way the real
          cartridge counts them (mega-ppm sdram_io.sv: cpu_oe high for two
          samples then low), so a glitch shorter than a sample is not a read

The MCU reads the latched pair at FPGAIO+0x14 (`fpgio_wcnt`, map slot 5,
read-only) immediately after each of its five pointer writes (`0xDA`, `0xDB`,
`0xAF` rewind, `0xF2`, init) and records `{ack, oe, frame, ptr}` for epochs
that carried any traffic. 99 epochs, 10 bytes each, in the arena; the onset
ring and the CRC table are compiled out (`#error` if two claim the arena).

**Why two counters and no "expected" from firmware.** The reviewer's
criterion is "count vs expected words-per-epoch". The firmware cannot know
what the game consumed - it only knows where it pointed. So the expected
count is taken from the 68000 side of the same bus, in the same clock domain
as the pointer, with no assumption about the game's read pattern at all.
`ack - oe` per epoch *is* the drift.

**Criteria, agreed while the fit was running and not renegotiable after:**

- `ack > oe` in epochs clustered at the onset -> **desync owns the band.**
  The fix is in `cartridge.sv`'s request-issue path (the rising edge of
  `cart_oe & cart_cs` re-arming on a mid-word glitch), not in firmware.
- `ack == oe` in every epoch through the band -> **look past the cursor.**
  The tape kept step; the shift is happening after the bytes leave the
  window - 68000->VDP destination or the name table.
- `ack < oe` -> the toggle crossing dropped a flip (107.39 -> 53.69 MHz).
  A different bug with the same consequence for the tiles; report it as what
  it is, do not fold it into the double-issue story.

The strong result is the **zero**. A run with the band on screen and every
epoch at `+0` retires the whole tape theory in one capture.

**What this card cannot decide.** An event landing on the exact cycle of the
MCU's re-point write is dropped from both counters rather than counted - at
most one per epoch, symmetric, so it cannot manufacture a difference, but it
can hide a real `+1` in one epoch out of many. A single isolated `+1` is
therefore weaker evidence than a cluster; the criteria above ask for a
cluster. And the card counts *words*; it says nothing about which VRAM
address the 68000 sent them to.

**Deploy note.** The fit is the risk, not the logic: two 16-bit counters,
two latches and a 3-bit shifter next to the stream pointer, in the module
that already sits on the worst STA paths. Gate unchanged: setup >= -2.60,
boots, full playthrough. The refuted read-back read the live pointer; this
reads a latch on the MCU's own write, and has not been fitted before.


### Onset ring, run 2 (unplanned replicate): FLAT again

The epoch build was still in the fitter when the tester ran the elevator a
second time on `dec2f09f`. Free replicate, read against the same criteria:

    whole run     742 refusals / 29911 frames = 0.0248 per frame, worst frame 15
    last 480      0 refusals, 64 loads, 0 frames ending with zero blocks payable
    bursts        sixteen load-frames, 1-6 loads each, never below 1 block left

Three playthroughs now agree to a few percent on every sticky counter:

    run            frames   refusals   /frame    loads/frame   0xDA   0xDB
    CRC card        27809       737    0.0265        0.79        50   1173
    onset ring 1    26830       683    0.0255        0.81        50   1173
    onset ring 2    29911       742    0.0248        0.77        64   1246

Starvation is closed as firmly as a firmware counter can close it.

### Epoch-counter build: fitted, gated, on the card

    bitstream   53076197   (ring dec2f09f, shipping 63891f17)
    ALMs        18,074 / 18,480  (98%)   - 120 fewer than the ring build
    M10K          294 / 308      (95%)
    setup       -2.404 ns   slow 85C     gate >= -2.60   PASS
    hold        +0.021 ns                                PASS
    seed 5, firmware mcu.txt 5235f357

Setup is the best of the three diagnostic fits, which says only that the
fitter is not deterministic in the tail - not that the counters helped.
Deployed with the snapshot region zeroed and game progress intact.

**Run:** elevator, slide, squares, quit promptly after the squares. The ring
keeps the last 99 epochs with traffic, not a number of seconds; the sticky
first-mismatch frame survives regardless.


### Correction: the footage does not settle wrong-place vs wrong-picture

Above, the tester's "they looked shifted" was written up as settling it for
the tape. That was too strong. The reviewer watched the 2026-09-03 capture
(clip clock ~9:19-9:21) and reports the SQUARES phase, from ~00:44: wrong
square tiles on the elevator floor - sign fragments, solid colours, UI bits
replacing the green hex floor - accumulating on the floor 00:46-01:40 and
scrolling with the plane; horizontal garbage bands in the distant BG from
~01:47 scrolling with the parallax; sprites and HUD clean throughout. That
reads as **wrong art in the right cells**, not the floor slid over.

The two observations are of two phases. The tester described the precursor
(seconds before the squares); the reviewer described the squares. The tape
theory predicts that progression - one word of drift shifts a tile's rows
within itself, several words fetch a *neighbouring tile's pattern* from the
same stream into the same VRAM slot, which is wrong art in the right cell -
but the squares phase on its own is equally consistent with pattern VRAM
being overwritten by something other than the window. **On footage it is a
draw.** The epoch counter decides, and its criteria are unchanged because it
measures the cursor, not the look of the tiles.

What the footage does constrain, for any theory:

- **Sprites and HUD clean.** Under drift the miscount must live in the long
  background-payload epochs and be reset before sprite fetches - plausible,
  `0xAF` rewinds every frame and sprite fetches are short, and it is the
  RTL's own recorded symptom ("tile noise on backgrounds while resident
  font/UI stayed clean"). Under an overwrite theory, the writer targets
  background tiles only.
- **The wrong art is sign/UI fragments, not enemy frames.** Sprite blocks
  carry sprite art; a sprite-slot overwrite painting the floor would be
  expected to show enemy or player fragments. Same-stream neighbours lean
  toward a misfetch from the background payload. A weak lean, recorded as
  one.

Refinement for the FLAT outcome only: if `ack == oe` through the band, the
reviewer's read then points at pattern VRAM being written by something other
than the window. The next step is offline and costs no ALMs - log in GPGX
which VRAM tile addresses the game DMAs into during the shaft, and check
whether anything else in the shipping layout can land on tiles 800-863.


### Epoch build 53076197 hangs at boot. A withdrawn theory, and the bisect

The epoch-counter build does not leave WaterMelon's disclaimer splash. The
Pocket and VDP are alive (`sync ok`, ~60 Hz); the 68000 is parked on the
mailbox. The boot marker in the save reads `PBOT` boot #3 with no `PSAT`, so
the MCU firmware ran far enough to stamp the marker on every boot - the hang
is consistent across three cold boots, and it is after the MCU is alive.

#### Withdrawn: the stack-overflow theory

Written down so nobody re-derives it. `ppm_stamp_rescale` (`cmd_F5`) has a
**4,128-byte** frame (`uint8_t scaled_stamp[128][32]`; the prologue is
`addi sp,sp,-32` then two `-2048`s). The internal DMEM is 8 KB and bss ends
at `0x80001938`, leaving 1,736 bytes - 56 fewer than the ring build. For an
hour that looked like a pre-existing overflow that 56 bytes of new statics
had pushed onto `ppmio`, the struct holding the mailbox base pointers. It
explained the symptom perfectly. It is wrong.

`neorv32_dmem.vhd` decodes with `hi_abb_c = 31`, `lo_abb_c = 13`: the DMEM
answers only `0x80000000-0x80001FFF`. The linker (`neorv32.ld`, `ram LENGTH
= 256K`) starts the stack at `0x8003FFFC`, which the DMEM does not claim; it
falls through to Wishbone, where `mcu.map.wram` (`addr[31:24] == 0x80`,
`mcu_core.sv`) serves it from the **32 KB WRAM** (`paprium_wram`,
`wram_addr[14:1]`). Stack and bss are different physical memories that alias
at the same base address. The 4,128-byte frame has always had 32 KB of room,
and no quantity of bss can reach the stack. There is no path from the stack
to `ppmio`, in any build.

Lesson, same as the last three: a number that fits the symptom is not a
measurement. The numbers that refuted it (`hi_abb_c`, the linker origin, the
map decode) were three greps away and were checked *before* the theory went
to the reviewer - which is the only reason this section is a withdrawal
rather than a correction.

#### What the epoch card actually changed

RTL: two counters, two latches, a 3-bit shifter, one extra term at the head
of the `mcu_dati` mux (`fpgio_wcnt`, map slot 5), and the `McuMap` field.
Firmware: `snap_epoch_note()` after each of five pointer writes - reads
FPGAIO+0x14, no loops, no waits - plus 990 bytes of statics. Neither side
shows a hang mechanism on reading. The fit passed every gate (-2.404).

#### The bisect, and why the control is the ring firmware

Reviewer's order: firmware side first. The cleanest firmware-side control is
not a stub - it is the **ring firmware unchanged** (`PPM_ONSET_RING 1`,
`PPM_EPOCH_RING 0`, mcu.txt `14844a95`, the same switches as the firmware
inside `dec2f09f`, which booted and ran two elevators today). It never reads
slot 5 and never calls the note. Fitted under the epoch RTL at seed 5:

    boots  -> the firmware side is guilty: the note path or its statics
    hangs  -> the RTL additions or the fit itself, regardless of firmware

A seed-6 refit of the full epoch build was started and killed: it tested
placement only, and a placement result cannot be read until the logic is
cleared. Its partial state was deleted before the control fit.

Card is on `dec2f09f` for the boot A/B against card and game state.

**A/B result:** `dec2f09f` boots past the disclaimer on the same card and
save. Card and game state cleared; the hang belongs to bitstream `53076197`
- its RTL additions, its firmware, or its fit. The control (epoch RTL, ring
firmware) is the cut between the first two.

#### Control fitted: 80e68bc9 - same placement as the hanging build

    bitstream   80e68bc9   epoch RTL + ring firmware 14844a95, seed 5
    ALMs        18,074 / 18,480   M10K 294 / 308
    setup       -2.404   hold +0.021        PASS

Every metric is identical to 53076197. Expected: the firmware only changes
the IMEM's ROM initialisation, and the same RTL at the same seed produces the
same placement and the same timing. So the control differs from the hanging
build in **nothing but the ROM contents** - placement is held constant.
Boots -> firmware, with no placement caveat. Hangs -> the RTL logic, or a
glitch both placements share. Deployed, region zeroed, progress intact.


#### Control result: HANGS. RTL side, placement held constant

`80e68bc9` (epoch RTL, ring firmware) does not boot. Cold boot: a **red
screen with `00F0` in the upper-left** - a harder failure than the splash
freeze, recorded as observed and not explained. Soft reset: wedges on the
disclaimer like `53076197`. The ring firmware never reads slot 5 and never
calls the note, and the control's placement is identical to the hanging
build's, so `snap_epoch_note` and the firmware statics are cleared. The fault
is in the RTL additions, or in a glitch both placements share.

#### Cut 2: mux term out, counters pinned

Reviewer's call: drop the `mcu_dati` slot-5 term, keep the counters. One
correction to make that a real cut: with the term gone nothing reads
`cnt_ack_l`/`cnt_oe_l`, and the fitter sweeps the counters, latches and
`oe_st` as dead logic - "keep the counters" silently becomes the ring build,
and a boot would say only that *something* in the additions is at fault. So
the five registers carry `(* noprune *)`. Pinned and unread, what survives
of them is exactly their **fanout** on `cart_oe`, `cart_cs`, `cpu.addr`, the
ack toggle and the `fpgio_sptr` write - the placement-pressure hypothesis -
against the mux term's functional one. `fpgio_wcnt` decode and the `McuMap`
field stay. Ring firmware `14844a95`, seed 5.

    boots  -> the mux term was functional. A read term the firmware never
              selects broke boot; the fix is to move the slot-5 read inside
              fpgio.sv's own mux and leave paprium_cart's untouched.
    hangs  -> the counters' fanout, or a glitch both placements share.
              Cut 3 is then a SEED, not a removal: cut-2 RTL at seed 6.
              Boots -> placement; hangs -> the counters' presence itself.

Why the mux term is suspect at all: it is the only edit to pre-existing
logic. The design fails timing by 2.4 ns on paths STA does not tie to
function; a term at the head of the MCU's data-in mux reshapes that mux for
every MCU read, not only slot 5.


#### Cut 2 fitted: counters survived, and it FAILS GATE at -3.343

    bitstream   14314402   cut-2 RTL (mux term out, five regs noprune), ring fw, seed 5
    ALMs        18,242 / 18,480   M10K 294 / 308
    setup       -3.343   hold +0.006        FAIL  (gate >= -2.60; -2.715 glitches at boot)
    pinned registers present in the fit report: yes (16 references)

Not installed. Archived as `cut2-mux-out-noprune.FAILED-GATE-3.343`. Flashing
it would test nothing: a hang at -3.343 is indistinguishable from a timing
glitch. The card went back to `dec2f09f` so nothing hanging is left in play.

#### The confound this exposes

Every RTL change re-rolls the placement. The control was informative *only*
because same RTL at the same seed gave the identical placement to the
hanging build - that held the fitter still while the firmware changed. Cut 2
changed the netlist (one term removed, five attributes added) and the fitter
landed a full nanosecond worse. So the "which addition" question cannot be
read from any cut that does not ALSO pass gate, and passing gate is seed
luck with a ~1.2 ns spread. This was always true of every diagnostic fit;
it has just not bitten until a cut and a bad seed coincided.

Sweep in progress: cut-2 RTL at seeds 6, 7, 8, 9 in sequence, stopping at
the first placement with setup >= -2.60. Every seed's metrics and md5 are
recorded whether or not it passes. This is also what the "hangs" branch's
cut 3 was going to be (a seed), so nothing is spent twice.

Reading, once a seed passes and is booted:

    boots  -> the mux term. The slot-5 read moves inside fpgio.sv's own mux.
    hangs  -> the counters' presence. Then the honest question is whether an
              RTL counter can be added to this design at all under the
              current gate, or whether the epoch measurement has to come from
              somewhere that adds no logic to the MCU or 68000 paths.

    cut-2 seed 6   ALM 18,162   setup -2.989   hold +0.087   md5 2635f4cb   FAIL
    cut-2 seed 7   ALM 18,199   setup -2.812   hold +0.044   md5 7d160710   FAIL
    (seed 8, 9 in progress)
    cut-2 seed 8   ALM 18,026   setup -4.609   hold +0.039   md5 6bbcb0bd   FAIL

**Locked with the reviewer (13:09):** cut 2 is not extended past seed 9 -
five unread `noprune` registers on the bus is an odd shape for the fitter,
and four placements spanning -4.609..-2.812 read as a worse netlist, not bad
luck. If seed 9 misses, the fallback is the ORIGINAL epoch RTL (`bace7b0`) at
seeds 6-9, ring firmware, first placement >= -2.60 wins. Read, fixed now:

    boots  -> seed-5's placement was the glitch
    hangs  -> functional -> the slot-5 read moves inside fpgio.sv's own mux

Card stays on `dec2f09f` throughout.
    cut-2 seed 9   ALM 18,114   setup -3.241   hold +0.095   md5 7f7d1bff   FAIL

**Cut 2 closed.** Five placements (-3.343, -2.989, -2.812, -4.609, -3.241),
none within the gate. Not extended, per the lock. Fallback sweep started
13:3x: original epoch RTL (`bace7b0`) at seeds 6-9, ring firmware 14844a95.
    epoch-rtl seed 6   ALM 18,105   setup -2.835   hold +0.061   md5 074cfd28   FAIL
