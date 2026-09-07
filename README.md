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

## Download

**[Get the latest release](https://github.com/thekoalakoa/paprium-pocket/releases/latest)** — `openfpga-Paprium_<version>.zip`, and unzip it onto your SD card.

> [!NOTE]
> **The core is not in this repository — it is in the release.** `paprium.rbf_r` is
> the compiled bitstream, a build artefact, so it is deliberately not committed
> (`.gitignore`). Cloning the repo and copying `pkg/pocket/` to your card gives you
> the JSON metadata **without the core**, and the Pocket will not run it. Download
> the release zip, or build the bitstream yourself — see [Building](#building).

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

Two, both on the audio side. Everything else that was listed here has moved to
[Fixed here](#fixed-here).

| Issue | Status |
|---|---|
| The music is the released soundtrack, not the cartridge's synthesiser | **Open.** The real cartridge synthesises the music live on a 26-voice sampler and bends it with play: the crisis variant the game switches to, the sax man's cues, the pitch of hits. This port plays the album instead, so none of that reacts. The instrument bank and all 52 sequence modules are decoded; the event semantics are not, and a 26-voice renderer needs FPGA area the 68000 swap is expected to free. Tracked in `docs/PORT_PLAN.md` |
| The "VM DAC" option does nothing when enabled | **Open.** On a real cartridge, enabling it routes the cartridge's PCM through the YM2612's DAC and thins the mix. Here the stream buffer the 68000 reads for it (cart RAM `0x1802–0x19FF`) is held at mid-scale, so the option is silent rather than static and the audio is unchanged. Making it work means the firmware keeping that buffer filled with the mixed PCM the game expects |

### Fixed here

Bugs present in every other Paprium build on this hardware, including the MiSTer
core this forks. All verified on real hardware, in both Arcade and Original modes.

| Fix | Was |
|---|---|
| Attacks not showing their frames; a walk that slid in the standing pose when entering a new screen | **Character animation** (0.2.1). Two separate firmware faults. (1) When a block for a *new* animation could not be loaded in time, the firmware rewound the object to its previous frame and, in doing so, overwrote the game's one-shot "restart animation" request — so the object carried on in its old cycle until the game asked for a different animation. A change of action is exactly when new art is needed, which is why attacks lost their frames. The request is now kept pending and retried on the next draw (`PPM_STICKY_SWITCH`), and the tiles of the frame shown meanwhile are protected from eviction within the same frame (`PPM_PIN_FALLBACK`). (2) At a screen transition the game queues "idle" as the walk's follow-up and then scripts the character across without touching it again. Stock firmware — and the reference emulator — took a queued follow-up as soon as the current cycle ended, so the character went idle and slid; the real cartridge keeps walking. A looping animation now keeps looping and a queued follow-up applies only when an animation actually ends (`PPM_CHAIN_ONLY_AT_END`). The earlier improvements stand: residency raised from 49 to the 53 blocks the game asks for, and sprites composed on the draw command rather than in a batch at frame end. A small floor on the loader's share of the frame's DMA budget (`PPM_DMA_FLOOR_BLOCKS`) is also in, measured harmless |
| Occasional single-pixel flicker in the intro | **Single-pixel flicker in the intro** (0.2.1). Not seen since the animation fixes. The likely cause was a rewound object's tiles being handed to a later load in the same frame — a one-frame flash of foreign tiles — which `PPM_PIN_FALLBACK` now prevents |
| Elevator level: bands of wrong tiles scrolling up the shaft, and the corrupted Intercom Complete screen after it (open as #8 on the MiSTer port) | The game parks a decompressed level payload in cartridge RAM at `0x9000` and reads rows of it back through the cartridge window for thousands of frames while the shaft scrolls. The firmware unpacks every newly loaded sprite block into its scratch area at the same address, so those rows came back as whatever sprite art had been unpacked since — 16-tile bands under correct name tables, accumulating with the scroll. The scratch now lives at `0x1E0000` (`PPM_SCRATCH_HIGH`), above anything the game addresses. Stock `mega-ppm` has the same scratch at `0x9000`, so every setup running it shares the fault. An earlier note here blamed a DMA ceiling; that reading was wrong. A second, smaller fault in the same shaft showed once the bands were gone: the game asks for one row per frame and tests the cartridge's busy flag once, right after asking, and the firmware could answer late, so the row was read before the pointer had moved — a blank or shifted row now and then. Busy is now held set at rest and dropped only once the pointer is in place, and released through the response so the one reader that polls after the response no longer runs its 0.56 s timeout |
| Rooftop boss, elevator and subway: the player, bombs and whole characters drawn behind the scenery, or vanishing | Sprites were composed in the wrong place in the frame. The reference implementation composes each sprite **as its draw command arrives**; the stock firmware queued every one and rendered the batch at frame end. The game interleaves — draw seventeen sprites, write its sprite **masks**, draw more — and a mask at X=0 hides every sprite later in the link chain on its scanlines. Batching put every cartridge sprite *after* the masks, so on the rooftop they sat at sprite-table entries 14–19 instead of the emulator's 31–36 and hid nine sprites including the entire player. Composing inline puts them at 34–39 and the count drops to three. Verified against a Genesis Plus GX savestate of the same scene, entry by entry |
| Destructible pillars and crates keeping their intact artwork after being smashed | A regression from the fix above, found and fixed in the same session. The frame's DMA budget was refreshed at frame *end*, immediately before the old batch — correct while the batch was where everything was composed. Once composition moved earlier, each sprite tested a budget already spent by the previous frame, so a **newly needed** block was refused and the sprite drew with whatever tiles were already resident. Artwork already in VRAM was unaffected, which is why only first-time smashes showed it |
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

Most of them came from a handful of cheap techniques rather than from reading code
until something looked wrong. Worth writing down, because they transfer to the parts
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
- **Comparing the sprite table against the emulator, entry by entry.** A firmware
  build that copies the cartridge's sprite list into the battery-backed save, plus
  a script that reads the same table out of a Genesis Plus GX savestate, turns "the
  player is behind the scenery" into two columns of numbers. The masks sat at
  entries 14–19 here and 31–36 there, while entries 0–13 matched tile for tile —
  which said the game was behaving identically and the *ordering* was ours. Every
  earlier attempt to fix that symptom by editing the sprite list afterwards failed,
  and one of them silently unlinked a character for a whole level; the comparison
  is what showed the position was not a number to tune but an ordering that had
  been removed
- **Reading GPGX as a second implementation.** Where `mega-ppm` guessed, GPGX
  often had the real thing. The `0x81` decoder in stock firmware is MAME's
  reverse-engineered approximation, carrying an `unconfirmed end code` comment on
  its own loop terminator; GPGX has an actual LZO decoder, and porting it fixed
  the subway. The same comparison fixed sprite palettes: the attribute word was
  being composed by XORing the tile and object words together, which scrambles
  the palette bits whenever both are set, where GPGX composes field by field with
  tile precedence. It also settled the sprite ordering: GPGX composes a sprite on
  the draw command, `mega-ppm` queues it for frame end, and that one difference
  was the rooftop bug
- **Control experiments on unmodified hardware.** The "VM DAC" static was blamed
  on our audio filtering, and a plausible story was built for it. Running a stock
  Mega Drive core on the same Pocket and hearing Sonic 2's drums — the same
  YM2612 DAC path, same filter setting — killed that theory in one test and moved
  the search to the data being fed in, which turned out to be an uninitialised
  buffer. **The wrong explanation was internally consistent and produced a fix
  that would have made things worse**

- **Instrumenting the emulator's cartridge window.** Genesis Plus GX, patched to
  log every 68000 read through the cartridge window, every mailbox command and
  every status poll with the address of the code doing it
  (`scripts/apply_gpgx_winlog.py`, `scripts/gpgx_winlog_build.sh`). That log is
  what showed the game parks a decompressed level payload at cartridge RAM
  `0x9000` and reads rows of it back thousands of frames later — the moment the
  shaft corruption stopped being "tiles never streamed" and became "tiles
  overwritten in cartridge RAM by the firmware's own scratch". The emulator has
  no MCU scratch, which is exactly why it does not have the bug and why the
  comparison worked
- **Bisecting by card, one variable at a time, on a placement that does not
  move.** Fits on this device sit at 98% of the logic; a firmware-only change on
  unchanged RTL lands on the identical placement every time, so consecutive test
  builds differ by exactly one firmware switch and a hardware read means one
  thing. Five cards settled the two elevator faults and refuted four candidates
  on the way — MCU SDRAM traffic starving the 68000, pausing SFX reads during
  DMA, the crash recorder as the cost of the boot pause, and the streaming
  loader — each with one build and one ride in the shaft
- **Reading the ROM at the poll sites.** The boot log listed every reader of the
  cartridge's busy flag and the command posted before it; disassembling those
  five addresses turned up one that waits for the command response first and
  *then* polls busy-clear, with a 65,534-iteration timeout. The first busy fix
  raised the flag again before the response, so that reader ran its full timeout
  — 0.56 s — after every scene load. That was the boot pause, and it was a dozen
  lines of 68000 code (`scripts/busy_polls.py`, `scripts/backtoback_posts.py`)
- **A crash recorder in battery RAM.** A build variant has the firmware write a
  40-byte record of what it is doing — phase, command, stack pointer, trap cause
  — into the save every frame, and the save survives a hang if the core is
  exited from the Pocket's menu (`scripts/decode_heartbeat.py`). It showed the
  MCU never trapped and the 68000 never faulted during a hang that looked like a
  crash, which took a whole chain of "corrupted payload → CPU fault"
  explanations off the table without a single fix attempt

- **Reading the game's own protocol instead of either port's guess.** Word `+0xA`
  of the animation record is a frame counter that `mega-ppm` increments every
  draw and restarts on any mismatch; in GPGX it is a one-shot reset the cart
  clears. Six bytes of 68000 at ROM `0x031024` say which: the game compares the
  requested animation with the current one, does nothing if equal, and otherwise
  writes `1` once. With that, "a refused block load rewinds the object" became
  "a refused block load overwrites the game's one request", and the attack
  frames followed from a two-line change. Neither implementation was the
  reference; the ROM was
- **Counting in the save, before and after.** Two counters added to the save
  block (`scripts/decode_sat_snapshot.py`) measured the fault on the card that
  shipped: 230 lost animations in ten minutes on the old rule, and 92% of them
  completing within a draw or two on the fix. The same file then refuted the
  next idea: a floor on the loader's budget fired in 44 of 7,808 frames while the
  walk-in slid on unchanged, so the budget was not the mechanism. A counter with
  a denominator turns "feels better" into a number, and a negative result into
  a closed door
- **A committee that tries to knock each hypothesis down.** Six readers over the
  firmware, the reference, the plan's history and the game side; four
  diagnosticians with different lenses; three adversarial refuters per surviving
  hypothesis; one synthesis. It ranked the lost switch first and refuted six
  alternatives, and its read of the ROM's DMA accounting — the game rewrites the
  remaining-budget word itself between frame start and the first draw — caught
  a build that would have done nothing before it reached the card
- **Logging what the game writes, not what the cart does with it.** The reference
  had the walk-in bug too, so comparing against it could not find it. The window
  logger gained one record per draw command holding the object record as the
  game left it (`scripts/analyze_objrec.py`). Two minutes of play showed the
  game queueing idle behind the walk and then scripting the character across
  for 295 frames without touching the record; both carts took the queued
  follow-up at the next cycle end. The tester's note that the real cartridge
  keeps walking was the arbiter, and the fix was one condition: a queued
  follow-up applies only when an animation actually ends
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

Paprium's music is generated by a chip inside the cartridge that has never been
dumped, so it cannot be reproduced. Like the EverDrive Pro, this core plays the
**released soundtrack** from the SD card instead.

**The core works fine without it.** You just get no music. If you want music, you
supply your own copy of the soundtrack — it is not distributed here — and turn it
into one file the core can stream.

### What you need

- **The Paprium soundtrack**, in any format ffmpeg can read: MP3, WAV or FLAC.
- **[ffmpeg](https://ffmpeg.org/)**, on your `PATH`. On Windows:
  `winget install Gyan.FFmpeg`, then **open a new terminal** — an already-open one
  will not see it.
- **Python 3**, for the second step.

You will run two commands. The first converts your music; the second packs it into
a single file. Together they take a few minutes and produce a **~543 MB** file
called `paprium.pcm`.

### Step 1 — put your soundtrack in one folder

All the audio files in a single folder, nothing else. **What matters is that each
filename starts with its two-digit track number.** The rest of the name is
ignored, so the titles in your rip do not have to match anything:

    ~/Music/Paprium/
      01 Theme of Paprium.mp3
      02 90's Acid Dub Character Select.mp3
      05 Asian Chill.mp3
      31 Bad Dudes vs Paprium.mp3
      ...

`02 Acid Dub.mp3` and `02 90's Acid Dub Character Select.wav` are both fine — only
the leading `02` is read. A file whose name does **not** start with a number will
not be found, and that track will be silent in game.

### Step 2 — convert the tracks

```bash
./scripts/build_cdda.sh ~/Music/Paprium docs/paprium.cue cdda/
```

Point the first argument at *your* folder from step 1. This reads
`docs/paprium.cue`, which maps the game's track numbers onto soundtrack files, and
writes `track01.pcm … track62.pcm` into `cdda/`. It prints what it converted and
what it could not find, so read that summary — missing files are reported here, not
later.

**Ten tracks are silent on purpose.** Cue entries 8, 9, 10, 13, 26, 31, 41, 44, 45
and 48 point at `Blank.wav`, because the cartridge's own music table is empty at
exactly those positions — the game has no music there either. Verified against two
independent ROM dumps. Nothing is missing if you see those reported as blank.

### Step 3 — pack it into one file

```bash
python scripts/build_cdda_adpcm.py cdda/ paprium.pcm
```

This compresses the tracks about 4:1 and writes a single `paprium.pcm` of roughly
**543 MB**. (The uncompressed equivalent was 2.09 GB, which is why this step
exists.)

### Step 4 — copy it to the SD card

Put `paprium.pcm` in:

    /Assets/paprium/common/paprium.pcm

That is the same folder as your `Paprium.md` cartridge dump. Start the core and
the music plays.

### If something is wrong

| Symptom | Cause |
|---|---|
| **No music at all**, everything else works | The blob is the old format or truncated. The core checks the file's header before playing anything, so a bad blob is silent rather than noisy — this is deliberate. Rebuild it, or convert an old one with the command below |
| **One track silent**, the rest fine | That file's name does not start with the right two-digit number — or it is one of the ten that are silent by design |
| `ffmpeg: command not found` | Not installed, or installed into a terminal that was already open. Open a new one |

**Already built the old 2.09 GB blob?** You do not need your soundtrack files
again — it is already the right sample rate and has a track table, so convert it in
place:

```bash
python scripts/convert_cdda_to_adpcm.py old_paprium.pcm paprium.pcm
```

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

## Reporting a bug

[Open an issue](https://github.com/thekoalakoa/paprium-pocket/issues/new/choose).
The template asks for the core version, the scene, and what you actually saw.

That last one matters more than it sounds. **Describe what was on the screen, not
what you think caused it.** Every bug in this project that took several attempts
to find was reported as an interpretation; every one that fell quickly was
reported as an observation. "The pillar still looks undamaged" located a fault in
one run, because *undamaged* rather than *missing* meant the sprite was being
drawn with stale artwork rather than not drawn at all — two different subsystems.
"Sprites are missing" took four runs and three wrong theories.

Photos or video of the moment it goes wrong are worth more than any description.

Please check [Known issues](#known-issues) first, and note that **we cannot help
you obtain the ROM or the soundtrack** — see [What this is not](#what-this-is-not).

## Versioning

Releases are published as full GitHub releases from 0.2.1 on (0.1.0 and 0.2.0
were pre-releases while the elevator corruption was open). What is still open is
listed under [Known issues](#known-issues); it does not hold a release back.

**Any released update that changes the game takes a patch bump** — `0.1.1`,
`0.1.2` and so on. If what a player sees or hears is different, the version moves,
whether that is a fix, a regression repair, or a behaviour change.

Two things that do *not* bump it: diagnostic bitstreams, which are never released
and are marked `NOT-FOR-INSTALL` in the build archive; and documentation.

A change is only released once it has been **tested on real hardware**, not merely
built. Several changes in this project's history looked right, passed every fit
gate, and were wrong on the device. The minor version moves when the known-issues
list actually shrinks.

## Lineage

Built on five projects. GPLv3 throughout, so all of it stays credited.

| | |
|---|---|
| [Nuked-MD-FPGA](https://github.com/nukeykt/Nuked-MD-FPGA) | nukeykt — gate-level model of the real silicon; the console itself |
| [MegaDrive_MiSTer](https://github.com/MiSTer-devel/MegaDrive_MiSTer) | MiSTer-devel — the core built around it |
| [openFPGA-MegaDrive](https://github.com/drizzt/openFPGA-MegaDrive) | drizzt — the Pocket port this forks |
| [Paprium_MegaDrive_MiSTer](https://github.com/MisterPezz82/Paprium_MegaDrive_MiSTer) | MisterPezz82 — the Paprium cartridge RTL: MCU integration, mailbox, memory map, SFX engine, MD+ adapter |
| [mega-ppm](https://github.com/krikzz/mega-ppm) | krikzz — the replacement MCU firmware, and the source this core's firmware is built from |

### Artwork

The platform image — the banner on the Pocket's system list — was made for
this core by **LemonGrwab**. The artwork is theirs; only the conversion into
Analogue's format is this repo's, via `scripts/make_platform_image.py`.

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
  empties, so the game's later `sfx_loop` landed on a dead one. The elevator
  corruption (0.2.0) is two firmware changes on unchanged RTL: the MCU's scratch
  area — block unpacking and staging — moved from `0x9000`, where the game parks
  and re-reads level payloads, to `0x1E0000` (`PPM_SCRATCH_HIGH`); and the busy
  handshake redesigned so busy is held set at rest, dropped once the read
  pointer has moved, released through the command response and raised again on
  the game's next post (`PPM_BUSY_REST`, `PPM_BUSY_CLEAR_THROUGH_RESP`). Stock
  `mega-ppm` has neither, so the fault is on every setup running it. The
  animation faults (0.2.1) are three more firmware changes on the same RTL: a
  refused block load no longer destroys the game's one-shot animation request
  (`PPM_STICKY_SWITCH`), the frame shown meanwhile keeps its tiles
  (`PPM_PIN_FALLBACK`), and a queued follow-up animation applies only when an
  animation actually ends rather than at its next cycle end
  (`PPM_CHAIN_ONLY_AT_END`) — a rule the reference emulator gets wrong too. A
  small floor on the loader's share of the frame's DMA budget
  (`PPM_DMA_FLOOR_BLOCKS`) ships alongside, measured harmless. The MCU's
  instruction memory is also 32 KB here, grown from 16 KB, to hold the
  diagnostic builds.
- **Diagnostics** — a mailbox command logger, SFX channel-state capture, a
  Genesis Plus GX cartridge-window logger with its analysers
  (`scripts/apply_gpgx_winlog.py`, `scripts/analyze_stream.py`,
  `scripts/busy_polls.py`) which since 0.2.1 also records the object record as
  the game writes it on every draw command (`scripts/analyze_objrec.py`), a
  battery-RAM crash recorder and its decoder (`scripts/decode_heartbeat.py`),
  a block of counters in the save — block loads refused, animation switches
  refused and completed, evictions, frames carried by the DMA floor — read by
  `scripts/decode_sat_snapshot.py`, and savestate tooling that reads the VDP
  registers, sprite table and tile patterns straight out of a GPGX state
  (`scripts/parse_gpgx_state.py`, `scripts/render_vram_tiles.py`). The
  loggers and the crash recorder sit behind switches and are off in the
  release; the save-block counters are compiled in, cost nothing, and are how
  the 0.2.1 numbers were read from the shipping card. The shipped firmware is
  0.1.0's configuration plus the two elevator fixes (0.2.0) and the three
  animation fixes with the floor (0.2.1). The savestate tooling is how the
  VRAM map was settled: the planes and the sprites use strictly separate tile
  ranges —

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
