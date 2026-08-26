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
