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
been dumped, and the company that made it has wound up; a core that runs the game
from your own dump is a way of keeping it playable.

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

The core boots straight into the game — no file browser, and no region option.
The cost is that the dump and the save are both fixed names; see
[docs/INSTALL.md](docs/INSTALL.md).

Region is fixed to Japan, which was already the menu default. The cartridge header
is `JUE` and the game is confirmed on hardware to run in **both** regions, so this
is one less menu item on a single-game core rather than a requirement. Restoring
the choice is a JSON edit, not an RTL change.

There is no 6-button option either: Paprium's own controller read is a 3-button
read, so X, Y, Z and Mode never did anything. The setting was removed rather than
left looking functional.

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
| Elevator level: scrolling tile squares | **Characterised, not fixed.** It is a DMA limit, not a bug: the game grants 2,816–4,608 words per frame, so at 272 words per 16-tile block only 10–16 blocks can load per frame. A shaft that scrolls faster than that leaves stale squares, and no allocator change lifts that ceiling — confirmed on hardware, where giving the allocator four more blocks changed the shaft not at all while visibly improving animation everywhere else |
| Characters animating on the spot — walking without the walk cycle advancing | **Much improved.** When a block cannot be loaded in time the firmware rewinds to the previous animation frame rather than dropping the sprite, which reads as a freeze. Raising the VRAM residency limit from 49 blocks to the 53 the game actually asks for makes those failures far rarer — verified on hardware. Not eliminated: the per-frame DMA ceiling below still applies |
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
| Large enemies playing a normal enemy's death sound | Flag `0x0100` steps the sample rate down one index (9600 → 6000 Hz), so a large grunt's death is the ordinary death played slower. GPGX names that bit "amplify" and this port rendered it as a ×1.25 gain, which is why both sounded identical. Confirmed by A/B through the game's own sound test. The gain path is still in the mixer but is starved: the firmware clears bit 0 before the RTL sees it, so `0x0100` gets a rate step and **not** a gain — and one `& ~0x01` puts the old behaviour back if the reading is ever overturned |
| The "VM DAC" option producing static | The 68000 streams cart RAM `0x1802–0x19FF` to the YM2612's DAC port, and that buffer was never initialised — so the option played uninitialised memory. Filling it with `0x80`, unsigned 8-bit mid-scale, makes the path silent instead. The option is now inert rather than wrong; real hardware also thins the mix, which this does not reproduce |
| The Block 888 doorway, and sprite colours generally | Wrong palette. The sprite attribute was composed by XORing tile and object words together, which scrambles the palette whenever both set those bits; now composed field-wise with tile precedence, as GPGX does |
| Stage Clear, Continue, Game Over, High Score, Ending | Silent. `cmd_8C` stopped one-shot cues instead of playing them |
| Echo on sound effects | Never implemented, though the game requests it constantly. `0x4000` now runs a real delay line — a 1/6th-second ring, each flagged voice sending 33% of itself into it, following GPGX |
| Stereo imaging on every off-centre effect | One side was phase-inverted, cancelling on the Pocket's mono speaker |

The firmware changes are in [patches/](patches/) and rebuild from a clean
[krikzz/mega-ppm](https://github.com/krikzz/mega-ppm) clone.

Timing does not fully close on this device — inherited from the base core, which
runs correctly on hardware regardless.

### How these were found

Most of them came from four cheap techniques rather than from reading code until
something looked wrong. Worth writing down, because they transfer to the parts
still open:

- **A mailbox command logger.** A build variant records every command the game
  sends the cartridge MCU, with a ring in spare M10K. That capture is what showed
  the game constantly requesting echo and amplify that nothing implemented, that
  `cmd_8C` was being handed one-shot cues it was stopping instead of playing, and
  that flag `0x0100` accompanied large-enemy deaths. Three fixes out of one
  diagnostic
- **Channel-state capture in the SFX engine.** Logging what each of the eight
  channels was doing showed the punk-TV channel had already been released by the
  time the game's `sfx_loop` arrived — `sfx_player_update` abandons a channel the
  moment it empties, so the loop enable landed on a dead one. The bug is in the
  order of two events, which is invisible in a static read of the source
- **Reading GPGX as a second implementation.** Where `mega-ppm` guessed, GPGX
  often had the real thing. The `0x81` decoder in stock firmware is MAME's
  reverse-engineered approximation, carrying an `unconfirmed end code` comment on
  its own loop terminator; GPGX has an actual LZO decoder, and porting it fixed
  the subway. The same comparison fixed sprite palettes: the attribute word was
  being composed by XORing the tile and object words together, which scrambles
  the palette bits whenever both are set, where GPGX composes field by field with
  tile precedence
- **Control experiments on unmodified hardware.** The "VM DAC" static was blamed
  on our audio filtering, and a plausible story was built for it. Running a stock
  Mega Drive core on the same Pocket and hearing Sonic 2's drums — the same
  YM2612 DAC path, same filter setting — killed that theory in one test and moved
  the search to the data being fed in, which turned out to be an uninitialised
  buffer. **The wrong explanation was internally consistent and produced a fix
  that would have made things worse**

The pan bug is the exception: one side of every off-centre effect was
phase-inverted, which cancels when the Pocket sums to its mono speaker. Impacts
are the widest-panned sounds in the game, so they had the most to lose, and the
fix was immediately audible.

### The in-game sound test is a usable instrument

Paprium has a sound test — the Boom Box, in the Options menu, labelled `?`. It is
the fastest way to check the large-enemy death fix above, or any other sound
question, because it fires one sample on demand instead of making you reproduce a
fight.

It indexes `00-FF`, but the sample table has only 127 live rows (`00-7E`). Swept
on hardware, the top half is **not** 128 more samples: slot `N + 0x80` fires row
`N` with the rate-step flag set. So there are 127 samples, not 255, and nothing in
the bank is unheard. Anyone else working on this cartridge should not size a mixer
for 256 voices on the strength of the menu's range.

That also makes the menu a controlled A/B for the rate-step fix. `52` then `D2`
drops 24000 Hz to 12000 Hz — an octave down and roughly double the length. Compare
with `22` then `A2`, which **must** sound identical, because row `0x22` is already
at the slowest rate and the firmware saturates rather than wrapping. Six rows
behave that way (`22, 2C, 2F, 48, 4C, 71`); on those, identical is the fix working,
not the fix failing. Without a saturated pair as a control, an unchanged sound is
ambiguous.

`scripts/predict_boombox_pairs.py <rom>` reads the table and prints the predicted
rate and duration for any pair, so a sweep can be checked against numbers rather
than judged by ear alone.

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

About 40% of `rtl/PAPRIUM` is new here — 1,519 of 3,596 lines are in files that
did not exist upstream — plus changes throughout the rest:

- **The whole CDDA music path** — `paprium_cdda_fetch/buf/play.sv`. Streams the
  soundtrack from an SD-card blob by seeking within a single APF data slot,
  because a core is capped at 32 data slots and Paprium has 62 tracks.
- **An IMA ADPCM decoder in fabric** — `paprium_ima_decode.sv`. The ring holds
  compressed frames and decodes on the way out, which cut the blob to a quarter
  and, as a side effect, bought about 4× the buffering (0.085 s → 0.337 s).
- **Audio fixes in the SFX mixer** — echo (`0x4000`), which the game requests
  constantly and neither this port nor MiSTer implemented; and a pan sign bug that
  phase-inverted one side of every non-centred effect. The mixer also carries an
  amplify path for `0x0100`, written when that bit was believed to be a gain. It
  is deliberately never asserted — see below.
- **Firmware fixes**, built from krikzz's source — see [patches/](patches/). The
  punk-TV cue never looped because `sfx_player_update` abandons a channel once it
  empties, so the game's later `sfx_loop` landed on a dead one.
- **Diagnostics** — a mailbox command logger, SFX channel-state capture, and
  savestate tooling that reads the VDP registers, sprite table and tile patterns
  straight out of a Genesis Plus GX state (`scripts/parse_gpgx_state.py`,
  `scripts/render_vram_tiles.py`). That is how the VRAM map was settled: the
  planes and the sprites use strictly separate tile ranges —

      tiles  800-863   VRAM 0x6400-0x6BFF   background art, planes only
      tiles 1984-2047  VRAM 0xF800-0xFFFF   sprite art, SAT only

  which is why the VRAM budget matters to animation and not to background
  scrolling, and why an earlier attempt to relocate streaming blocks into
  `0x6400` destroyed the cell-room floor.
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
