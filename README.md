# Paprium for Analogue Pocket

A standalone openFPGA core for **Paprium** (WaterMelon, 2020), running on the
Analogue Pocket.

This is a single-game core, not a Mega Drive emulator. The general cartridge
hardware is stripped out to make room for Paprium's own — the NEORV32 MCU, the
streaming window, and the cartridge's 8-channel PCM sound engine. Don't load other
ROMs into it.

> [!IMPORTANT]
> **You must supply your own cartridge dump.** None is included, and none will be
> linked. WaterMelon have ceased trading and the game is no longer sold, but that
> does not put it in the public domain — it is still their work, and this project
> treats it that way.
>
> The music is likewise not included — see [Music](#music).

This exists for preservation. The cartridge depends on hardware that has never
been dumped, and the people who built it are gone; a core that runs the game from
your own dump is a way of keeping it playable.

**Installation: [docs/INSTALL.md](docs/INSTALL.md)**

---

## What works

Boot, decompression, graphics streaming, saves, the cartridge's own sound effects,
and music — with correct per-scene track selection and one-shot cues that stop
rather than loop.

Fits a Cyclone V `5CEBA4F23C8` at **98% ALM and 95% M10K**, on a device with less
than half the logic of the MiSTer board this was ported from. There is very little
room left; see [docs/BUILD_REFERENCE.md](docs/BUILD_REFERENCE.md) before adding
anything.

There is no 6-button option: Paprium's own controller read is a 3-button read, so
X, Y, Z and Mode never did anything. The setting was removed rather than left
looking functional.

## What this is not

Not a faithful reproduction of the cartridge, but an attempt with what we have.
Paprium's "DATENMEISTER" chipset — in reality an Intel MAX 10 FPGA, an STM32F446
and a flash die — decompresses the graphics and synthesises the music. **Neither
the MAX 10 bitstream nor the STM32 firmware has ever been dumped... yet.**

So this takes the same approach as the EverDrive Pro: it runs krikzz's
[`mega-ppm`](https://github.com/krikzz/mega-ppm) replacement MCU firmware and
substitutes the released soundtrack for the synthesised music.

Expect it to play well, not to be cycle-accurate.

## Known issues

All predate this port and are present on other Paprium setups running the same
replacement firmware. Several are confirmed on real EverDrive Pro hardware.

| Issue | Status |
|---|---|
| Elevator level: scrolling tile squares | **Improved, and the remainder is explained.** Slots 49–52 were overwriting the sprite and scroll tables at `0xF800`; capping the budget removed that. What is left is a DMA limit, not a bug: the game grants 2,816–4,608 words per frame, so at 272 words per 16-tile block only 10–16 blocks can load per frame. A shaft that scrolls faster than that leaves stale squares |
| Characters animating on the spot — walking without the walk cycle advancing | **Same root cause, characterised.** When a block cannot be loaded in time the firmware rewinds to the previous animation frame rather than dropping the sprite, which reads as a freeze. Bound by the same 10–16 blocks per frame, which comes from a constant in the game's own ROM — so it is not fixable by giving the allocator more slots |
| Rooftop boss: player and bombs drop behind the background during the bombing phase | Open. Forcing the priority bit on every sprite was tried on hardware: other sprites came forward, the player and the bombs did not move. So it is **not** sprite priority, and no attribute change in the replacement firmware can fix it. The live candidates are that the player is drawn by the 68000 rather than by the cartridge, or region-based masking (window plane, or sprite masking). Needs a VDP/SAT capture to settle |
| Full-health stage clear plays the ordinary cue | Not reproducible — the variation is inside the cartridge synth's render of one track, and the soundtrack has a single Stage Clear recording |
| Occasional single-pixel flicker in the intro | Cosmetic, self-corrects |

### Fixed here

Bugs present in every other Paprium build on this hardware, including the MiSTer
core this forks. All verified on real hardware, in both Arcade and Original modes.

| Fix | Was |
|---|---|
| All punk-TV cues, and the looping area ambience | Silent. `sfx_player_update` abandons a channel once it empties, so the game's later `sfx_loop` — which enables looping and ramps the volume — landed on a dead channel |
| Subway and other `0x81` assets | Corrupted. Stock `mega-ppm` ships MAME's reverse-engineered guess at the LZ decoder; replaced with the real LZO decoder |
| Large enemies playing a normal enemy's death sound | Flag `0x0100` steps the sample rate down one index (9600 → 6000 Hz), so a large grunt's death is the ordinary death played slower. GPGX names that bit "amplify" and this port rendered it as a ×1.25 gain, which is why both sounded identical. Confirmed by A/B through the game's own sound test |
| The "VM DAC" option producing static | The 68000 streams cart RAM `0x1802–0x19FF` to the YM2612's DAC port, and that buffer was never initialised — so the option played uninitialised memory. Filling it with `0x80`, unsigned 8-bit mid-scale, makes the path silent instead. The option is now inert rather than wrong; real hardware also thins the mix, which this does not reproduce |
| The Block 888 doorway, and sprite colours generally | Wrong palette. The sprite attribute was composed by XORing tile and object words together, which scrambles the palette whenever both set those bits; now composed field-wise with tile precedence, as GPGX does |
| Stage Clear, Continue, Game Over, High Score, Ending | Silent. `cmd_8C` stopped one-shot cues instead of playing them |
| Echo and amplify on sound effects | Never implemented, though the game requests them constantly |
| Stereo imaging on every off-centre effect | One side was phase-inverted, cancelling on the Pocket's mono speaker |

The firmware changes are in [patches/](patches/) and rebuild from a clean
[krikzz/mega-ppm](https://github.com/krikzz/mega-ppm) clone.

Timing does not fully close on this device — inherited from the base core, which
runs correctly on hardware regardless.

[docs/PORT_PLAN.md](docs/PORT_PLAN.md) is the full engineering record: what was
measured, what was tried, and which explanations turned out to be wrong.

## Music

Paprium's music is generated by hardware that has never been dumped, so it cannot
be reproduced. Like the EverDrive Pro, this core substitutes the released
soundtrack, streamed from the SD card.

**The core runs fine without it** — you simply get no music.

The soundtrack is not distributed here. Everything needed to build the blob from
your own copy *is* here.

**You need:** the released Paprium soundtrack in any format ffmpeg reads (MP3,
WAV, FLAC), and [ffmpeg](https://ffmpeg.org/) on `PATH`
(`winget install Gyan.FFmpeg`).

```bash
./scripts/build_cdda.sh ~/Music/Paprium docs/paprium.cue cdda/
```

```bash
python scripts/build_cdda_adpcm.py cdda/ paprium.pcm
```

Then copy `paprium.pcm` to `/Assets/paprium/common/` on the SD card.

The blob is IMA ADPCM in a `PPAD` container — 543 MB for 62 tracks, about a
quarter of the 2.09 GB the earlier raw-PCM blob needed. The core validates the
`PPAD` header and every field the decoder assumes **before** it walks the track
table, so a blob in the old format, or a truncated one, plays **nothing at all**
rather than streaming as noise. If music went silent after an update, the blob is
the old format.

**Already have the old raw blob?** You do not need your soundtrack files again —
it is already 48 kHz stereo with a track table, so convert it in place:

```bash
python scripts/convert_cdda_to_adpcm.py old_paprium.pcm paprium.pcm
```

`docs/paprium.cue` maps the game's track numbers onto soundtrack filenames.
Source files are matched by their **leading two-digit number**, not by title, so a
rip whose titles differ slightly still works and an `.mp3` substitutes for the
`.wav` the cue names.

Ten cue entries point at `Blank.wav` and become silence. That is correct, not a
missing file: the cartridge's own music pointer table is null at exactly those ten
indices (8, 9, 10, 13, 26, 31, 41, 44, 45, 48), so the game has no music there
either — verified against two independent ROM dumps.

## Building

Quartus Prime Lite 21.1.1.

```bash
quartus_sh -t scripts/syn_check.tcl paprium
```

```bash
quartus_sh -t generate.tcl paprium
```

```bash
python scripts/reverse_bitstream.py projects/output_files/megadrive_pocket.rbf build_output/paprium.rbf_r
```

```bash
./scripts/deploy_to_sd.sh /d
```

`generate.tcl` takes an optional second argument, a fitter seed. Timing on this
device is seed-sensitive by up to about 1.2 ns, so a single failing fit is not by
itself evidence that a change broke timing. The shipping bitstream is seed 5.

Firmware is rebuilt separately with `./scripts/build_mcu.sh`, which installs its
output into `rtl/PAPRIUM/mcu.txt` — the bitstream picks it up from there, so a
firmware change that was not installed will silently rebuild the previous one.

Variants: `paprium`, `paprium_nosfx`, `paprium_cddadbg`, `paprium_cmdlog`. Tell
them apart by **M10K**, not ALM: shipping is 294, `cmdlog` is 308.

> Always check the fit summary **timestamp** and the `.rbf` **size** before
> flashing. Quartus can fail and leave stale artifacts, which produce believable
> wrong answers on hardware.

[docs/BUILD_REFERENCE.md](docs/BUILD_REFERENCE.md) has the fit and timing gates,
and the measurements behind them.

## Lineage

Built on five projects. GPLv3 throughout, so all of it stays credited.

| | |
|---|---|
| [Nuked-MD-FPGA](https://github.com/nukeykt/Nuked-MD-FPGA) | nukeykt — gate-level model of the real silicon; the console itself |
| [MegaDrive_MiSTer](https://github.com/MiSTer-devel/MegaDrive_MiSTer) | MiSTer-devel — the core built around it |
| [openFPGA-MegaDrive](https://github.com/drizzt/openFPGA-MegaDrive) | drizzt — the Pocket port this forks |
| [Paprium_MegaDrive_MiSTer](https://github.com/MisterPezz82/Paprium_MegaDrive_MiSTer) | MisterPezz82 — the Paprium cartridge RTL: MCU integration, mailbox, memory map, SFX engine, MD+ adapter |
| [mega-ppm](https://github.com/krikzz/mega-ppm) | krikzz — the replacement MCU firmware, and the source this core's firmware is built from |

### What this port adds

Roughly a third of `rtl/PAPRIUM` is new here, plus changes throughout the rest:

- **The whole CDDA music path** — `paprium_cdda_fetch/buf/play.sv`. Streams the
  soundtrack from an SD-card blob by seeking within a single APF data slot,
  because a core is capped at 32 data slots and Paprium has 62 tracks.
- **An IMA ADPCM decoder in fabric** — `paprium_ima_decode.sv`. The ring holds
  compressed frames and decodes on the way out, which cut the blob to a quarter
  and, as a side effect, bought about 4× the buffering (0.085 s → 0.337 s).
- **Audio fixes in the SFX mixer** — echo (`0x4000`) and amplify (`0x0100`), which
  the game requests constantly and neither this port nor MiSTer implemented; and a
  pan sign bug that phase-inverted one side of every non-centred effect.
- **Firmware fixes**, built from krikzz's source — see [patches/](patches/). The
  punk-TV cue never looped because `sfx_player_update` abandons a channel once it
  empties, so the game's later `sfx_loop` landed on a dead one.
- **Diagnostics** — a mailbox command logger and SFX channel-state capture, which
  is how the above was found rather than guessed at.
- **Everything Pocket-specific** — APF integration, data slots, and the fit work
  that made room for all of it on a device this small.

The cartridge RTL underneath it is MisterPezz82's, and their
[KNOWN_ISSUES.md](https://github.com/MisterPezz82/Paprium_MegaDrive_MiSTer/blob/master/docs/KNOWN_ISSUES.md)
is a genuinely useful engineering record — it saved this project at least one
wasted build by documenting an elevator fix that had already been tried and did
not work.

Please report issues with **this** core here, not to those projects. A problem is
most likely a result of this port.

## Licence

GPLv3, inherited from the upstream projects. See [LICENSE](LICENSE).
