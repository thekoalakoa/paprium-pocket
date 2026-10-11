<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/platform-banner.png">
    <img src="docs/images/platform-banner-light.png" alt="Paprium" />
  </picture>
</p>

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

Fits a Cyclone V `5CEBA4F23C8` at **98% ALM and 82% M10K** (0.2.6: 18,184 ALM, 253
M10K), on a device with less than half the logic of the MiSTer board this was ported
from. From 0.2.2 the 68000 is [FX68K](https://github.com/ijor/fx68k) rather than the
gate-level netlist, which freed about ten points of ALM; 0.2.6 spends most of them on
the CPU MATE link and the new menu options. There is little room left; see
[docs/BUILD_REFERENCE.md](docs/BUILD_REFERENCE.md) before adding anything.

The core boots straight into the game — no file browser. The cost is that the dump
and the save are both fixed names; see [docs/INSTALL.md](docs/INSTALL.md).

From 0.2.6 the menu also has the [Scum!](#scum-and-the-console-options) switches
(cheats, the hidden Arcade Mode with a stage select, and a 6-Button switch), a choice
of console and Mega CD unit, which brings in the game's **CPU MATE** partner, and 32X
and MegaWire options. All of it is off by default; the one visible difference from
0.2.5 at the defaults is that no MegaWire shows as connected, as on a real cartridge
with nothing plugged in.

## Scum! and the console options

The core's settings menu, in the order the Pocket shows it:

| Entry | Choices | Takes effect |
|---|---|---|
| Soft Reset (mini game) | action: restarts the console (see [docs/INSTALL.md](docs/INSTALL.md) for the mini-game) | — |
| Aspect Ratio | Original (default), Corrected | at once |
| Little-Man | Off (default), Health, Pills, Lives, Health + Pills, Health + Lives, Pills + Lives, All Three | at once |
| Arcade Stage Select | Off (default), Block 888, Intercom, MTS, Bion Mart, Roof-Top, Police HQ, Ice Factory, Reformatory, Sanophix PU, Central Park, Green Cross, The Docks, Golden Of Seas, Deep Storage, Aquaworld | Soft Reset |
| Arcade Stage Select 2 | Off (default), Blue Bar, Powder-Zone, Bohpal B-2, Juvanium, Sky Spa, Digniti KTV, The Vault, Sanophix Labs, The Solarium, Arena | Soft Reset |
| 6-Button | off (default) / on | at once |
| Console | Mega Drive (default), Genesis, Mega Drive 2, Genesis Model 2, Genesis 3, Nomad, Mega Jet, Unknown | Soft Reset |
| Mega CD | None (default), Mega-CD / Sega CD, Mega-CD 2 / Sega CD 2, Wondermega, Wondermega M2 / X'Eye, LaserActive, Aiwa CSD-GM1, CDX, Unknown CD | Soft Reset |
| 32X Mode | off (default) / on | Soft Reset |
| MegaWire | off (default) / on | Soft Reset |

**Scum!** is this project's name for the first four game switches:

- **Little-Man** (the cheats). Health: players take no damage and specials cost no
  health; enemies are unaffected. Pills: using a Blu pill (Down + A) does not spend
  one. Lives: dying does not spend a life.
- **Arcade Stage Select** and **Arcade Stage Select 2**: choosing a stage switches on
  the game's hidden ARCADE PAPRIUM mode (credits and friendly fire) and starts it on
  that stage. **Select inserts a coin.** If both pages hold a stage, page 2's applies.
- **6-Button**: X, Y, Z and Mode reach the game, on L, the Pocket's X, R and Select.
  Paprium's pad code does read a 6-button pad, but on this core, as on MiSTer and
  EverDrive, those buttons never arrive; the switch hands them to the game directly.

Nothing touches the ROM file. While a switch is on, the cartridge hands the console a
few replacement words in place of the game's own, the same kind of patch a Game Genie
makes, done in the FPGA; switching it off gives back the original bytes.

The other four change the machine the game believes it is running on. **Console**
sets the region (Mega Drive, Mega Drive 2, Mega Jet and Unknown are Japan; the others
USA) and the console picture in the Boom Box; the TMSS consoles boot without a licence
screen. **Mega CD** picks the unit the game finds, with its splash and region. **32X
Mode** makes the game believe a 32X is attached (some throwables become 32X boxes).
**MegaWire** off is what a real cartridge reports with nothing plugged in (MODEM :
NONE, no icon); on is what every earlier release reported. The game reads all four at
boot: change the setting, then Soft Reset.

**CPU MATE.** Choose a Mega CD unit (any except Unknown CD) and Soft Reset, and the
game offers CPU MATE in its Options: a computer-controlled partner. Switch it on, and
at character select bring the partner in. Played handheld, turn **6-Button** on in the
core menu: **hold Select** to add the partner, and while still holding it move the
partner's cursor with the D-pad and press **Start** to pick its character; release
Select to pick your own. No second controller needed: it is the game's own six-button
control with a Mega CD ([Paprium FAQ](https://www.wafflenet.com/paprium.html#questions)). With a second controller on the
Dock, press **Start on controller 2** (again to pick its character).
The partner's brain is the game's own Mega CD AI, translated to run on the cartridge
MCU. The release bitstream has it built in. Because it is made from the game's code it
is not in this repository: anyone building the core gets it as a separate download next
to each release, and a core built without it has no brain, so the partner stands
still. See [docs/firmware/README.md](docs/firmware/README.md).

How all of it works, the patch sites, what was measured, and what did not work:
[docs/SCUM.md](docs/SCUM.md).

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

Four: two on the audio side, and two that came with the 0.2.6 menu options.
Everything else that was listed here has moved to [Fixed here](#fixed-here).

| Issue | Status |
|---|---|
| Hall of Fame: garbage on the name-entry bar while **Arcade Stage Select** or **6-Button** is on | **Open (0.2.6).** The blinking highlight bar on the name-entry row shows garbage in the first 24 pixels of every 64-pixel group, worst at the left edge where the initials go. The code those two switches add is served from ROM space that looked like padding and is really the bar's tile data, which the game copies to VRAM with a DMA; the substitution covers DMA reads too. Little-Man alone does not do it, and with both switches off the bar is clean. Moving the code needs a new fit. Details in [docs/SCUM.md](docs/SCUM.md) |
| Changing **Console** or **Mega CD** around a Soft Reset can need a second Soft Reset | **Open (0.2.6).** The firmware reads the console model and the MegaWire setting once, about 2 ms into a reset. A setting changed after that read gives that one boot a mixed machine, such as the wrong console picture; the next reset is clean. Change the setting first, then Soft Reset. Separately, a Soft Reset rarely ends on a black screen with a few pixels at the bottom edge, most often around such a change; another Soft Reset recovers. The cause of the black screen is not established |
| The music is the released soundtrack, not the cartridge's synthesiser | **Open.** The real cartridge synthesises the music live on a 26-voice sampler and bends it with play: the crisis variant the game switches to, the sax man's cues, the pitch of hits. This port plays the album instead, so none of that reacts. The instrument bank and all 52 sequence modules are decoded; the event semantics are not, and a 26-voice renderer needs FPGA area the 68000 swap is expected to free. Tracked in `docs/PORT_PLAN.md` |
| The "VM DAC" option does nothing when enabled | **Open.** On a real cartridge, enabling it routes the cartridge's PCM through the YM2612's DAC and thins the mix. Here the stream buffer the 68000 reads for it (cart RAM `0x1802–0x19FF`) is held at mid-scale, so the option is silent rather than static and the audio is unchanged. Making it work means the firmware keeping that buffer filled with the mixed PCM the game expects |

### Fixed here

Bugs present in every other Paprium build on this hardware, including the MiSTer
core this forks. All verified on real hardware: up to 0.2.5 in both Arcade and
Original modes; the 0.2.6 rows on an arcade run to the credits plus the regression
list in the [changelog](#changelog).

| Fix | Was |
|---|---|
| The end credits: sparkles drawn as squares of background art, and damaged tiles in the credits pictures | **Sprite cache** (0.2.6). The firmware's cache claimed its VRAM slots in its own order, so the sparkle sprite's block was loaded into slots that lie inside the credits background (slots 15–27, up to 15 damaged cells on the first page). The cache now follows the original cartridge's rules: every slot has a countdown that each use or load resets and every frame ages; aged slots fall into free, idle and recently-used lists; a missing block takes a free slot, then an idle one, then the slot of a related block, then a recently-used one, lowest slot first; a piece that still cannot be loaded is dropped alone, and at most 15 blocks load a frame. On five separate captures the sparkle block now lands in the first slot every time, clear of the background. The 0.2.0 elevator fix had no effect here: a different mechanism |
| At the end of the game, characters frozen in mid-walk and floating across The Solarium's camera pan | **Sprite-table close** (0.2.6). While the HUD is hidden the game links the first sprite-table entry straight to entry 14. The firmware closed the table by clearing the link of its own last entry and uploading only that many entries, so the previous frame's entries from 14 on stayed linked in VRAM and kept drawing. The table is now closed the cartridge's way: an end mark at the entry count, entry 79's link cleared, one entry more uploaded (`PPM_FLOAT_ENDMARK`, [the MiSTer Paprium team](https://github.com/thekoalakoa/Paprium_MiSTer)'s patch). The end mark is in place on all 870 frames of the pan on a recorded solo run, and all 860 on a two-player run |
| Busy fights: characters freezing in a pose for up to half a second | **Loads refused** (0.2.6). The old cache could never take a slot used in the previous frame, so in a busy fight a new pose's blocks were refused and the whole object was rewound to its previous frame; if that pose's block had meanwhile been evicted, the piece was drawn from VRAM tile 0, as garbage. In one 36-frame fight window of a recorded run: 32 loads, 1,038 refusals and 69 refused animation switches before; 130 loads and 0 refusals with the cache above. The DMA budget is also charged and gated as on the cartridge now, and a pose that does not fit is held whole or pre-loaded over several frames rather than drawn in part |
| The game showing a MegaWire modem as connected (the icon, MODEM : MW4.0, an extra Options row) | **MegaWire status** (0.2.6). The firmware always reported a MegaWire plugged in and connected; a real cartridge with nothing plugged in reports none. The status now comes from the new **MegaWire** menu option, off by default |
| The Boom Box's bars running about 20% fast | **Boom Box row clock** (0.2.6). The 0.2.3 level meter used an emulator's frames-per-row reading. The bars now run on the clock measured against hardware captures; see `patches/README.md` |
| A dropped weapon kept spinning instead of settling on the ground | Knives `0xDC`, chains `0xDD`, neon sticks `0xDE` and pipes `0xE0` spun where they should have settled. The game hands a dropped item over and walks away: it arms the ground animation as a queued follow-up and never writes the animation itself again, for hundreds of frames. The rule that refused the switch is the one that stops a character sliding in its standing pose at a screen transition (`PPM_CHAIN_ONLY_AT_END`, 0.2.1), and measured across 12 minutes of play it fired on **0 of 821** queue requests — in practice "never chain". Three readings of *when* the game arms the queue were tried against that, and each one that settled the weapons also put a walking character back into its standing pose, because the game uses the same idiom for a player's looping idle as for a dropped knife. What separates them is not the timing but the object: the firmware's own per-object animation count splits props (2 to 29 animations, every weapon is 10) from actors (39 to 220, the characters are 157) with no overlap. A prop now takes its queued follow-up at any animation end — the rule hardware confirmed settles every weapon — while an actor keeps the 0.2.4 rule unchanged. The frame-word flag bits, `obj_data+0x06`, object movement, a frame clock, and copying the reference emulator were each measured and refuted first; see `patches/README.md`. **0.2.6** replaces this rule, and the 0.2.1 rules in the next row, with the original cartridge's own animation queue; see [0.2.6: what worked, and what did not](#026-what-worked-and-what-did-not) |
| The Boom Box’s bar graph lit up permanently instead of following the music | **Boom Box level meter** (0.2.3). Cartridge RAM `0x1B98– 0x1BFF` is a per-voice level feed — 26 voices of left/right, ending exactly on `0x1C00` — that the cartridge’s music engine rewrites every row, and the Boom Box draws its 26 bars straight from it. This port substitutes the album for the synthesiser and never sequences the modules, so nothing wrote that window at all and the game drew its bars out of uninitialised memory. The firmware already decompresses the sequence module on every music command and then discards it, so the bars are now driven from that — the real per-voice arrangement, at the module’s own tempo, for no extra work. The tempo comes from the module header, verified against hardware: Stage Clear is 105 rows at 20 rows a second, 5.25 seconds, matching a capture of the Boom Box exactly |
| Attacks not showing their frames; a walk that slid in the standing pose when entering a new screen | **Character animation** (0.2.1). Two separate firmware faults. (1) When a block for a *new* animation could not be loaded in time, the firmware rewound the object to its previous frame and, in doing so, overwrote the game's one-shot "restart animation" request — so the object carried on in its old cycle until the game asked for a different animation. A change of action is exactly when new art is needed, which is why attacks lost their frames. The request is now kept pending and retried on the next draw (`PPM_STICKY_SWITCH`), and the tiles of the frame shown meanwhile are protected from eviction within the same frame (`PPM_PIN_FALLBACK`). (2) At a screen transition the game queues "idle" as the walk's follow-up and then scripts the character across without touching it again. Stock firmware — and the reference emulator — took a queued follow-up as soon as the current cycle ended, so the character went idle and slid; the real cartridge keeps walking. A looping animation now keeps looping and a queued follow-up applies only when an animation actually ends (`PPM_CHAIN_ONLY_AT_END`). The earlier improvements stand: residency raised from 49 to the 53 blocks the game asks for, and sprites composed on the draw command rather than in a batch at frame end. A small floor on the loader's share of the frame's DMA budget (`PPM_DMA_FLOOR_BLOCKS`) is also in, measured harmless. **0.2.6** compiles out the sticky switch, the pin, the chain rule and the floor in favour of the original cartridge's cache, budget and animation-queue rules, which keep both fixes |
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
  move.** Fits on this device sat at 98% of the logic before the 0.2.2 CPU swap, 88%
  after; a firmware-only change on
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

### 0.2.6: what worked, and what did not

**What worked.**

- **The cartridge's rules instead of another guess.** 0.2.1 to 0.2.5 each fixed an
  animation symptom with a rule of our own (the sticky switch, "chain only at an end",
  the fresh-queue window, "a prop is not an actor"), and each one traded a symptom for
  another on hardware: walk-ins that moonwalk against weapons that spin. The missing
  step was one write. When the cartridge takes a queued animation it writes it back into
  the game's object record, and the game's own `setAnim` compares against that record:
  re-arming the same queue then cancels it, and a single queue switches at the end of
  the current cycle. 0.2.6 does the same, a terminal animation end clears the animation
  as on the cartridge, and all four heuristics are compiled out. The sprite cache, the
  DMA budget, the held and pre-loaded poses, the "on screen" flag the stage scripts wait
  on, and the three cache commands (reset, resize, and the one that only sets flags)
  follow the cartridge's rules the same way. Each sits behind its own switch in
  `mame.h`, so any of them can be switched off to compare; `patches/README.md` lists them.
- **One step per hardware build.** Test 1 (cache and float): credits and float fixed,
  but two new faults, a flicker on the character-select screen and a glitch with lost
  background colours going from Original mode to Arcade. Test 2 added the budget and
  the pose hold: both gone. Test 3 added the cache commands and the animation queue:
  every item on the regression list passed. The release build passed the same list
  again.
- **The select flicker had a number before it had a fix.** With the cache alone, a pose
  whose blocks did not fit the frame's DMA budget was drawn with pieces missing: Dice
  lost 74–84% of his pixels for single frames, every six frames, when the budget ran
  short. With the budget and the hold, 0 incomplete draws in 774 select-screen
  character draws (one player) and 1,332 (two players).
- **Recorded runs as the test bench.** A solo arcade run through The Solarium and the
  credits, a two-player run and a 60,000-frame attract demo were replayed through each
  firmware step, counting per frame what was loaded, held, refused and drawn. In the
  attract demo all 29 weapon lives (9 drops) settle and none spins.
- **A crossing fixed at its root.** The MCU's stream pointer was captured on a clock edge
  that the other clock also moves, a real same-edge race that showed as hold misses of
  9 and 30 ps in earlier fits. On shared edges the address now takes a held copy: the
  same value, no added latency. Constraint exceptions now cover the real
  `clk_sys`/`clk_md` crossings, each raising a critical warning if it ever matches
  nothing.
- **FX68K's own multicycle constraint.** The worst setup path in every fit was FX68K's
  `Ir → nanoAddr`, which is not a real single-cycle path: those registers load at most
  once every four clocks. The multicycle constraint FX68K's author gives for it is in
  `core_constraints.sdc` now.
- **The Pocket's spare memories.** The sound-effect echo line moved from block RAM into
  the Pocket's cellular RAM (32 M10K freed, clock-for-clock identical in simulation),
  and the album's stream buffer moved there too, with a guard so a late write cannot land
  in a flushed buffer. The Pocket's 256 KB SRAM became a window for the MCU, which holds
  the CPU MATE's view of the stage.
- **A one-clock stale reply on file commands.** The APF bridge left the host's previous
  `ok` in the upper half of the target-command word for one clock after a new command
  started; the four command starts now write the whole word.

**What did not work.**

- **Our own float fix**: an off-screen dummy entry whenever no sprite had been added.
  It cut the frozen frames of the pan from 889 to 19 in a model, but it is not the
  cartridge's rule, and the end mark replaced it.
- **Clearing the cache when the credits start.** The credits came out clean in a model,
  but the cartridge does not do it. Rejected; the claim order fixed the credits.
- **The cache lists without the per-piece drop.** An interim build removed the select
  flicker but brought back frozen poses and, without the old fallback pin, rare
  whole-sprite garbage frames in two-player fights.
- **The two-load DMA floor** from 0.2.1. The cartridge has no floor; with the budget and
  the pose hold, a pose that cannot load is held whole. Removed.
- **The first pose-hold code** kept two registers live across the piece loop and cost
  600 MCU cycles a draw in spills. Moving one store ahead of the loop and the
  pre-load out of line fixed that.
- **Room for the animation queue.** It needs a 256-byte array, and the MCU's work RAM,
  shared with the CPU MATE, had none: a straightforward build overflowed by exactly 256
  bytes, and moving the stack instead made its worst case negative. The queue is packed
  into object bytes that only the retired heuristics used, proven identical in lockstep.
- **A stock debug line.** mega-ppm prints a line on its serial port when an animation
  index runs past the object's count, about 3.8% of a frame per hit. It is off in 0.2.6,
  and the release compiles all debug output out.
- **Fitter seeds.** Six seeds were fitted. Seed 5, the old shipping seed, failed by
  0.003 ns of hold on the MCU's 68000 reset line; 4 and 6 failed the crossing re-check
  (SDRAM to MCU data, MCU bus to work RAM); 3 failed setup at −3.84 ns. Seeds 2 and 1
  passed; the release is seed 2.
- **"Free padding" that was not.** The Scum! pad code went into a 512-byte block of `0xFF`
  in the ROM. It is the Hall of Fame bar's tile data, which the game copies with a DMA:
  the first known issue above.
- **A one-time read.** The firmware copies the console model into the game's view once
  per reset; changing it around a Soft Reset gives one mixed boot, the second known issue.
  A latch that holds the options during reset was considered and not taken.

The CPU MATE partner went through five versions before this one; that story, and the
Scum! patch sites, are in [docs/SCUM.md](docs/SCUM.md).

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

That script works one sample at a time on one core and takes ten minutes or more.
`build_cdda_adpcm_fast.py` takes the same arguments and writes the same file byte
for byte, but encodes the tracks in parallel on every core — about half a minute
on an 8-core machine, and still faster than the original on a single core:

```bash
python scripts/build_cdda_adpcm_fast.py cdda/ paprium.pcm
```

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
device is seed-sensitive by several nanoseconds (0.2.6's six seeds ranged from
−0.74 to −3.84 ns of setup), so a single failing fit is not by itself evidence that a
change broke timing. The shipping bitstream is seed 2, which is also what
`projects/megadrive_pocket.qsf` says. The 0.2.6 gate was setup ≥ −2.60 ns, hold > 0,
and a re-check of the clock crossings; seeds 2 and 1 passed it.

Firmware is rebuilt separately with `./scripts/build_mcu.sh`, which installs four
images into `rtl/PAPRIUM/` (`mcu.txt`, `mcu_ext.txt`, `wram_hi.txt`, `wram_lo.txt`) —
the bitstream picks them up from there, so a firmware change that was not installed
will silently rebuild the previous one. The committed images are the release firmware
**without the CPU MATE brain**, which is not in this repository; with the brain
download, `./scripts/build_mcu.sh --brain <folder>` builds the shipped firmware byte for
byte. The released bitstream was fitted with the test firmware and then given the
release firmware by a memory-initialisation update, so a fresh fit is not guaranteed
to reproduce it bit for bit: the release download is the reference. Details:
[docs/firmware/README.md](docs/firmware/README.md).

Variants: `paprium`, `paprium_nosfx`, `paprium_cddadbg`, `paprium_cmdlog`. Tell
them apart by **M10K**, not ALM: shipping drifts per release (279 at 0.2.5, 253 at
0.2.6), and `cmdlog` was 308 before 0.2.6 (not re-measured since).

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

## Changelog

**0.2.6** — the CPU MATE partner, the menu options, and the cartridge's own sprite
rules. Bitstream seed 2: 18,184 ALM, 253 M10K, worst setup −0.739 ns, worst hold
+0.071 ns.

- **CPU MATE.** With a Mega CD unit chosen in the menu, the game offers its
  computer-controlled partner. The partner's brain, the game's own Mega CD AI, runs on
  the cartridge MCU behind a Mega CD link that answers at the moment the real sub-CPU
  would; the game's code is not patched. The brain is built into the release bitstream
  and is a separate download for anyone building the core
  ([docs/SCUM.md](docs/SCUM.md#cpu-mate), [docs/firmware/README.md](docs/firmware/README.md)).
- **Scum!**: **Little-Man** (infinite health, Blu pills and lives, in any combination),
  **Arcade Stage Select** (two pages: the hidden Arcade Mode, started on any of 25
  stages, with Select as the coin) and **6-Button** (X, Y, Z and Mode reach the game).
- **Console** (8 models; sets the region and the Boom Box picture, and the TMSS models
  boot without a licence screen), **Mega CD** (8 units, with their splashes and
  regions), **32X Mode** and **MegaWire** (off by default, as a real cartridge with
  nothing plugged in).
- **The end-credits corruption and The Solarium float are fixed**, and busy fights no
  longer freeze poses: the sprite cache, the DMA budget, the held and pre-loaded poses
  and the animation queue now follow the original cartridge's rules, which also replace
  the animation heuristics of 0.2.1–0.2.5.
- The Boom Box bars run at the measured tempo instead of about 20% fast.
- Under the hood: a clock-crossing race on the MCU's stream pointer fixed at its root,
  FX68K's own multicycle constraint, the sound-effect echo line and the album buffer
  moved into the Pocket's cellular RAM (freeing block RAM), the Pocket's SRAM opened to
  the MCU, a stale one-clock reply on APF file commands fixed, and debug output compiled
  out of the release firmware.
- Two known issues come with the new options: the Hall of Fame name-entry bar with
  Arcade Stage Select or 6-Button on, and a Console or Mega CD change around a Soft
  Reset ([Known issues](#known-issues)).

Hardware-tested on a real Pocket before release: default boot, all 8 consoles and every
Mega CD unit (picture, splash, region), the TMSS consoles, MegaWire off, 32X Mode, and
the regression list: the select screen, switching between Original and Arcade modes, The
Solarium, the credits, the elevator, dropped weapons, the attract demo, CPU MATE, busy
fights, sound effects and echo. Every Scum! switch and stage name was checked on the
0.2.6 test builds.

**0.2.2** — the 68000 changes. The core now runs [FX68K](https://github.com/ijor/fx68k)
(Jorge Cwik, GPL-3, vendored in `rtl/fx68k/`) in place of the gate-level netlist. For a
player nothing should look or sound different; the point is area. The fit drops from 98%
to 88% ALM, and that headroom is what the live synthesiser under
[Known issues](#known-issues) needs.

Getting there needed one fix in the CPU wrapper worth recording, because it is the kind of
fault that hides for a long time. The wrapper released the 68000's function-code pins as
soon as the address strobe went inactive, but the board registers that strobe a cycle
later — so for one cycle the arbiter saw the pin pattern that means *interrupt
acknowledge* while the strobe still read active, and the video chip discarded whichever
raster interrupt it was holding. Roughly eleven thousand false acknowledgements a frame.
Because the game's raster-interrupt chain reloads itself from each handler, one lost
interrupt threw every later split on that frame onto the wrong line — a whole plane in the
wrong place. Holding the function code one cycle longer fixes it.

**0.2.1** — character animation fixed; first full release.

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

## Sponsor

If this is useful to you, you can sponsor the work at
[github.com/sponsors/thekoalakoa](https://github.com/sponsors/thekoalakoa).

It changes nothing about the core: it is GPLv3, the source is all here, and none of
it is or will be behind a sponsorship. It also cannot buy you the ROM or the
soundtrack — see [What this is not](#what-this-is-not).

## Lineage

Built on seven projects. GPLv3 throughout, apart from the two BSD-licensed parts of the
cartridge MCU (NEORV32 and mega-ppm), so all of it stays credited.

| | |
|---|---|
| [Nuked-MD-FPGA](https://github.com/nukeykt/Nuked-MD-FPGA) | nukeykt — gate-level model of the real silicon; the console itself. Everything but the 68000: the VDP, the arbiter, the I/O chip, the FM, the Z80 and the board |
| [FX68K](https://github.com/ijor/fx68k) | Jorge Cwik (ijor) — the 68000, from 0.2.2. Replaces Nuked's gate-level CPU and frees the ALM the synthesiser needs; Nuked's netlist is still in the tree behind `USE_FX68K` |
| [MegaDrive_MiSTer](https://github.com/MiSTer-devel/MegaDrive_MiSTer) | MiSTer-devel — the core built around it |
| [openFPGA-MegaDrive](https://github.com/drizzt/openFPGA-MegaDrive) | drizzt — the Pocket port this forks |
| [Paprium_MegaDrive_MiSTer](https://github.com/MisterPezz82/Paprium_MegaDrive_MiSTer) | MisterPezz82 — the Paprium cartridge RTL: MCU integration, mailbox, memory map, SFX engine, MD+ adapter |
| [mega-ppm](https://github.com/krikzz/mega-ppm) | krikzz — the replacement MCU firmware, and the source this core's firmware is built from (BSD-3-Clause) |
| [NEORV32](https://github.com/stnolting/neorv32) | Stephan Nolting — the RISC-V processor the cartridge MCU runs on, carried in MisterPezz82's cartridge RTL, and the runtime and linker script the firmware is built with (BSD-3-Clause) |

### The 0.2.6 menu switches and fixes

The arcade unlock and the Mode-button credit are adroxe's
([Paprium-Arcade](https://github.com/adroxe/Paprium-Arcade)); the arcade start-stage
word was found by krikzz; serving patches as ROM reads, the pad hook that injects X,
Y, Z and Mode, and the stage list come from MisterPezz82's Paprium MiSTer core (V.05
and V.06). The sprite-table end mark that fixes The Solarium float is the MiSTer Paprium
team's patch, their 32X and Mega CD detection stubs are where `paprium_addons.sv`
started, and the CPU MATE link's restart rule was worked out with them. The health,
pill and life patches, the console options and the CPU MATE link are new here.

### Artwork

The platform image — the banner on the Pocket's system list — was made for
this core by **LemonGrwab**, who supplies it in Analogue's format. The artwork
is theirs. `scripts/make_platform_image.py` converts a PNG into that format for
anyone who wants to start from one.

### What this port adds

About 60% of `rtl/PAPRIUM` is new here — 3,540 of 5,862 lines are in files that
did not exist upstream (at 0.2.5 it was 1,519 of 3,596) — plus changes throughout the
rest:

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
  (`PPM_DMA_FLOOR_BLOCKS`) ships alongside, measured harmless. 0.2.6 replaces
  those animation rules, the floor and the eviction with the original
  cartridge's sprite cache, DMA budget and animation queue, each behind its own
  switch (`PPM_CHIP_*`), and closes the sprite table with the cartridge's end
  mark (`PPM_FLOAT_ENDMARK`). The MCU's instruction memory grew from 16 KB to
  32 KB to hold the diagnostic builds, and in 0.2.6 to 54 KB (a 22 KB
  extension) for the CPU MATE brain, with a write-locked 16 KB code window in
  the cartridge work RAM.
- **Scum! and the console options** — `paprium_scum.sv` serves the switches'
  replacement words on ROM reads (generated by `scripts/scum_table.py`);
  `paprium_addons.sv` answers the 32X, Mega CD and TMSS checks and turns the
  Console and Mega CD lists into the region, version register and unit ID the
  game reads.
- **The CPU MATE link** — `paprium_mcd_link.sv` and `paprium_xlink.sv` play the
  Mega CD's side of the game's partner protocol at the real sub-CPU's timing,
  and `paprium_snoop.sv` mirrors what the game writes for the sub-CPU into the
  Pocket's SRAM, which `paprium_xram.sv` opens to the MCU. See
  [docs/SCUM.md](docs/SCUM.md#cpu-mate).
- **The Pocket's cellular RAM** — from 0.2.6, `paprium_cram.sv` and
  `paprium_cdda_buf_cram.sv` hold the album's stream buffer and the sound-effect
  echo line, which both used to take block RAM.
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
  0.1.0's configuration plus the two elevator fixes (0.2.0), the three
  animation fixes with the floor (0.2.1), the Boom Box level feed and the
  restart-flag fix (0.2.3), and the dropped-weapon chain rule (0.2.4, rewritten
  in 0.2.5); 0.2.6 then swaps the sprite and animation rules for the cartridge's
  own, adds the float end mark, the Boom Box row clock, the console and MegaWire
  bits and the CPU MATE glue, and compiles the debug aids out of the release
  build. The savestate tooling is how the
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

GPLv3 or later. Nuked-MD-FPGA is GPLv2-or-later and FX68K is GPLv3-or-later;
exercising Nuked's *or later* option is what lets the two combine, so the work as a
whole is GPLv3-or-later. See [LICENSE](LICENSE), and the vendored
`rtl/upstream/nuked-md/LICENSE` (GPLv2) and `rtl/fx68k/LICENSE` (GPLv3), both of
which stay as they are.

The cartridge MCU's parts are BSD-3-Clause: the NEORV32 processor (in the bitstream)
and its runtime, and krikzz's mega-ppm firmware, which this core's firmware is built
from (in the bitstream's MCU memories). Their copyright notices and licence texts are
in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), which also ships in the release
package.

The CPU MATE brain download is made from the game's own code, so it is not part of this
repository and is not offered under its licence. It is useful only together with your
own copy of the game.
