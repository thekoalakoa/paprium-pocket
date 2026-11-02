<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/platform-banner.png">
    <img src="docs/images/platform-banner-light.png" alt="Paprium" />
  </picture>
</p>

# Paprium for Analogue Pocket

A standalone openFPGA core for **Paprium** (WaterMelon, 2020), running on the
Analogue Pocket.

This core plays one game. It isn't a Mega Drive emulator. I stripped out the general cartridge hardware to make room for
Paprium's own: the NEORV32 processor that stands in for the cart's chip and runs our firmware, Little-Man Firmware; the
streaming window; and a sprite decoder and synthesiser we rebuilt to work the way the cart's do. Please don't load other
ROMs into it.

> [!IMPORTANT]
> **You need your own copy of the game.** I don't include one and I won't link one. WaterMelon have stopped trading and
> the game isn't sold anymore, but that doesn't make it public domain. It's still their work, and this project treats it
> that way.
>
> You don't need a soundtrack file anymore. From 0.3.0 on, the core makes the game's music from your own copy of the
> game, the same way the cart does. See [What 0.3.0 is](#what-030-is).

I made this for preservation. The cart depends on hardware of its own, and the company behind it has wound up. A core
that runs the game from your own copy is one way to keep it playable.

## Download

**[Grab the latest release](https://github.com/thekoalakoa/paprium-pocket/releases/latest)**. There are two downloads:
the core, `openfpga-Paprium_<core version>.zip`, which you unzip onto your SD card, and the cart firmware,
`Little-Man_Firmware_<firmware version>.zip`, which has `little_man_firmware.bin` inside. For 0.3.0 that's
`openfpga-Paprium_0.3.0.zip` and `Little-Man_Firmware_1.0.zip`.
The core zip already holds the firmware file; the firmware's own download is for firmware-only updates.

> [!NOTE]
> **The core isn't in this repo. It's in the release.** `paprium.rbf_r` is the compiled bitstream, which is a build
> output, so I leave it out on purpose (`.gitignore`). The firmware file `little_man_firmware.bin` isn't committed
> either. If you clone the repo and copy `pkg/pocket/` to your card, you get the JSON metadata **but no core**, and the
> Pocket won't run it. Download the release, or build the bitstream and the firmware file yourself (see
> [Building](#building)).

**Installation: [docs/INSTALL.md](docs/INSTALL.md)**

---

## What 0.3.0 is

With 0.3.0 the core acts like the original cart. Two things changed the most.

- **The game's own music, made the way the cart makes it.** We rebuilt the cart's sound chip in the core's logic, and
  our music player runs in the firmware, working like the cart's does. The music and sound effects are made from your
  own copy of the game the same way the cart makes them, so the music reacts to what's happening in the game just like
  on a real cart. Both of the game's sound options work, YM and Datenmeister. No more soundtrack file.
- **Our own firmware for the cart's chip.** The cart has its own processor. It unpacks the game's graphics, drives the
  sprites, keeps the saves and plays the sound. In this core that processor runs **Little-Man Firmware**, which our team
  wrote from our own study of how the cart behaves. It's its own file, `little_man_firmware.bin`, version 1.0. It's free
  software under the GPL (version 3 or later), and the source is in this repo's [`firmware/`](firmware/) folder.

Anything a player might notice that's different from the original cart is listed below under
[Known differences from the original cartridge](#known-differences-from-the-original-cartridge). Every one of them is
there on purpose.

## What you need

- An Analogue Pocket on firmware 2.3 or later.
- A microSD card set up for the Pocket.
- Your own copy of the game's ROM (8 MiB), made from your own cartridge. I don't include one and I won't link one.
- Two files from the release page: the core, `openfpga-Paprium_0.3.0.zip`, and the cart firmware,
  `Little-Man_Firmware_1.0.zip`.
  The core zip already holds the firmware file; the firmware's own download is for firmware-only updates.

You can forget the soundtrack file (`paprium.pcm`). 0.3.0 doesn't read it.

The core boots straight into the game with no file browser, so the game, the firmware file and the save each have a
fixed name and spot. Install steps are in [docs/INSTALL.md](docs/INSTALL.md).

## What changed since 0.2.6

**Sound**
- The music comes from our music player in the firmware plus our rebuild of the cart's sound chip, which work the way
  the cart's do, in both of the game's sound options (YM and Datenmeister). It follows the game like the cart does:
  the low-health music, the sax man's cues, the Boom Box's X, Y and Z effects and the fades.
- Sound effects play on our rebuild of the cart's synthesiser, filter and echo included.
- The audio option in the game's own options menu works like it does on the cart.
- The first start takes about 30 seconds. After the Pocket's loading bar you get a black screen with a bar along the
  bottom while the core unpacks the game's sounds from your copy of the game into a sound cache file. Starts after that
  take about 12 to 14 seconds.
- While the Pocket's menu is open, the music pauses right where it is and the cart's sound effects go quiet. When you
  close the menu, the music picks up from the same spot.

**How the cart behaves**
- The sprites, the zooms (the intro's SEGA CD logo, the arcade title and the stage zooms), unpacking the game's data,
  the saves, the start-up and the cart's watchdog all work the way the cart does them.
- Sprites get the cart's colours. Dice's afterimage outline is green like on the cart (0.2.x drew it blue), and the first
  level's doorway gets its colours from the cart's own rule.
- Saves use the cart's own format, 8 KB, the size of the cart's save chip. A 0.2.x save gets converted once, the first
  time 0.3.0 starts. Make a copy of your save before you install (see [docs/INSTALL.md](docs/INSTALL.md)).
- The cart's watchdog is back. With the Pocket's menu closed, if the game stops sending its once-a-frame signal for
  about 4 seconds, the cart's chip halts, just like a real cart.

**The menu**
- **Console Reset** is new. It resets the console like the console's own Reset button. During play, the game starts
  over from its NX TERMINAL screen (the status page at the start of the intro), same as on the cart.
- **Arcade Mode** has its own entry now: Off, On, Multiplayer and Stick Only. Anything but Off plugs a virtual Grand
  Stick III into controller port 1. On flips the stick's ARCADE switch, so the game turns on its own arcade mode without
  any change to the ROM. Multiplayer adds the stick's 3 PLAYERS switch, with the third player on Dock controller 3.
  Stick Only is the stick with every switch off, which plays the normal game. With On or Multiplayer, Select drops a
  coin, and the first coin after power-on or a reset gives no credit, just like a cart with a Grand Stick III. With Stick
  Only, Select is the stick's Mode button.
- New alongside it: **Arcade Coins** (1 Coin 1 Credit, 2 Coins 1 Credit, Inf. Credits (0012)) and **Attract Only**, the
  stick's other switches. They only count with Arcade Mode On or Multiplayer, like Arcade Stage Select.
- **3-Player Mode** is new (Off by default). It plugs in an EA 4-Way Play so the game's three-player modes work with
  three Dock controllers. With Arcade Mode on there's no 4-Way Play: Dock controller 3 goes into the stick's EXT socket.
- **6-Button** now hands the game real six-button pads on controllers 1 and 2, and the game reads X, Y, Z and Mode
  itself. An empty controller port reads as empty. With Arcade Mode on, port 1 is the stick, which has all its buttons
  no matter what 6-Button says.
- **TeraDrive** joins the Console list (it's a Japanese console, so the region is Japan).
- **MegaWire** is out of the menu: its On / Off row did nothing in 0.3.0. Our MegaWire code always runs and acts like the
  cart's does. See [MegaWire](#megawire).

**Fixed**
- Hall of Fame name entry: the highlight bar is clean with Arcade Stage Select or 6-Button on. Details are in
  [docs/SCUM.md](docs/SCUM.md#fixed-in-030-the-hall-of-fame-name-entry-bar).
- The Arcade coin plays the game's coin sound on every press.
- Soft Reset holds the 68000 from the very first clock of the reset, so a warm reset doesn't repeat the bus cycle it cut
  off anymore.
- TMSS, the licence check the later consoles run at power-on, works on every all-in-one Mega CD unit (Wondermega,
  Wondermega M2 / X'Eye, LaserActive, Aiwa CSD-GM1, CDX), same as on the real ones.
- The two Soft Reset issues of 0.2.6 are tested and fixed in 0.3.0 with Little-Man Firmware 1.0: a second Soft Reset
  needed after a **Console** or **Mega CD** change, and the rare black screen after a Soft Reset.

## Scum! and the console options

Here's the core's settings menu, in the order the Pocket shows it:

| Entry | Choices | Takes effect |
|---|---|---|
| Soft Reset (mini game) | action: restarts the console and the cart's chip (see [docs/INSTALL.md](docs/INSTALL.md) for the mini-game) | — |
| Console Reset | action: resets the console like its own Reset button | — |
| Aspect Ratio | Original (default), Corrected | right away |
| Little-Man | Off (default), Health, Pills, Lives, Health + Pills, Health + Lives, Pills + Lives, All Three | right away |
| Arcade Mode | Off (default), On, Multiplayer, Stick Only | Soft Reset |
| Arcade Coins | 1 Coin 1 Credit (default), 2 Coins 1 Credit, Inf. Credits (0012) | Soft Reset |
| Attract Only | off (default) / on | Soft Reset |
| Arcade Stage Select | Off (default), Block 888, Intercom, MTS, Bion Mart, Roof-Top, Police HQ, Ice Factory, Reformatory, Sanophix PU, Central Park, Green Cross, The Docks, Golden Of Seas, Deep Storage, Aquaworld | Soft Reset |
| Arcade Stage Select 2 | Off (default), Blue Bar, Powder-Zone, Bohpal B-2, Juvanium, Sky Spa, Digniti KTV, The Vault, Sanophix Labs, The Solarium, Arena | Soft Reset |
| 6-Button | off (default) / on | right away |
| 3-Player Mode | off (default) / on | Soft Reset |
| Console | Mega Drive (default), Genesis, Mega Drive 2, Genesis Model 2, Genesis 3, Nomad, Mega Jet, TeraDrive, Unknown | Soft Reset |
| Mega CD | None (default), Mega-CD / Sega CD, Mega-CD 2 / Sega CD 2, Wondermega, Wondermega M2 / X'Eye, LaserActive, Aiwa CSD-GM1, CDX, Unknown CD | Soft Reset |
| 32X Mode | off (default) / on | Soft Reset |


**Soft Reset (mini game)** restarts the console and the cart's chip together. **Console Reset** resets just the 68000,
like the console's own Reset button. During play, the game starts over from its NX TERMINAL screen.

**Scum!** is what I call the game switches:

- **Little-Man** (the cheats). Health: you take no damage. With it on, enemies you throw don't take any damage either,
  because one of its patches sits in the game's throw-damage routine. Every other hit on an enemy does full damage.
  Pills: using a Blu pill (Down + A) doesn't use one up. Lives: dying doesn't cost a life.
- **Arcade Mode**: anything but Off plugs a virtual Grand Stick III, Paprium's arcade stick, into controller port 1,
  and the game reads the stick's switches itself, with nothing patched. **On** flips the stick's ARCADE switch, which
  turns on the game's hidden ARCADE PAPRIUM mode (credits and friendly fire), and **Select drops a coin**.
  **Multiplayer** adds the stick's 3 PLAYERS switch, with the third player on Dock controller 3 in the stick's EXT
  socket. **Stick Only** is the stick with every switch off: the normal game, with Select as the stick's Mode button. The
  game gives no credit for the first coin after power-on or a reset, just like a cart with a Grand Stick III.
- **Arcade Coins** and **Attract Only** are the stick's other switches. They only count with Arcade Mode On or
  Multiplayer. Inf. Credits (0012) makes the game stop on its red 0012 screen at boot, which is exactly what the game
  does with that switch on a real stick.
- **Arcade Stage Select** and **Arcade Stage Select 2**: which stage Arcade Mode starts on, only with Arcade Mode On or
  Multiplayer. If both pages have a stage picked, page 2 wins. A stage you picked in 0.2.6 waits until you set Arcade
  Mode, since that entry is new and starts Off.
- **6-Button**: the pads turn into real six-button pads, and the game reads X, Y, Z and Mode itself, on L, the Pocket's
  X, R and Select (off: three-button pads). With Arcade Mode on, port 1 is the stick, which has all its buttons no
  matter what 6-Button says, and 6-Button then sets the pads on port 2 and in the stick's EXT socket. A controller port
  with no Pocket controller behind it reads as empty, so a handheld Pocket doesn't get a phantom player 2.
- **3-Player Mode** (off by default) plugs in an EA 4-Way Play (more below).

**Three players.** With **3-Player Mode** on and Arcade Mode Off, the core shows the game an EA 4-Way Play, as if it was
plugged in before power-on, and the game supports it: with three Dock controllers, Arena takes three players. With
Arcade Mode on there's no 4-Way Play. Multiplayer puts Dock controller 3 in the stick's EXT socket as the third player,
and so does 3-Player Mode with On or Stick Only. Controller 3 only counts as a docked pad. The game looks for the adapter
and the stick at boot, so Soft Reset after you change it. With the 4-Way Play, the first-boot mini-game only listens to
controller 3, same as a real console.

None of this touches the ROM file. Little-Man and the Arcade stage pick work like a Game Genie: while one is on, the cart
hands the console a few replacement words instead of the game's own (done in the FPGA), and switching it off gives back
the original words. Arcade Mode, 6-Button and 3-Player Mode don't change a single word of the game. They change what the
game finds on its controller ports.

The other three change what machine the game thinks it's running on. **Console** sets the region (Mega Drive, Mega Drive
2, Mega Jet, TeraDrive and Unknown are Japan; the rest are USA) and the console picture in the Boom Box. The TMSS
consoles boot without a licence screen. TeraDrive is detection only: the core answers the game's video RAM test, so the
Boom Box shows the TeraDrive. **Mega CD** picks the unit the game finds, with its splash and region. The all-in-one
units (Wondermega, Wondermega M2 / X'Eye, LaserActive, Aiwa CSD-GM1, CDX) report TMSS like the real ones do and also boot
without a licence screen. **32X Mode** makes the game think a 32X is attached (some throwables turn into 32X boxes).
There's no MegaWire setting any more. Our MegaWire code always runs and acts like the cart's does, and with no module
plugged in (the Pocket never has one) the game looks like a real cart with nothing plugged in (see
[MegaWire](#megawire)). The game reads all three at boot, so change the setting and then Soft Reset.

**CPU MATE.** Pick a Mega CD unit (anything except None and Unknown CD) and Soft Reset, and the game offers CPU MATE in
its Options: a computer-controlled partner. Turn it on, then bring the partner in at character select. Playing handheld?
Turn **6-Button** on in the core menu, then **hold Select** to add the partner. While you're still holding it, move the
partner's cursor with the D-pad and press **Start** to pick its character; let go of Select to pick your own. You don't
need a second controller: it's the game's own six-button control with a Mega CD
([Paprium FAQ](https://www.wafflenet.com/paprium.html#questions)). With a second controller on the Dock, press **Start
on controller 2** (and again to pick its character). The partner's brain ships inside the firmware file,
`little_man_firmware.bin` (see [Little-Man Firmware](#little-man-firmware)). It's a reverse-engineered emulation of the
game's CPU partner. Its files aren't part of this repo's source. A firmware file built without it still runs the game,
but the partner just stands there.

How all of it works, the patch spots, what we measured and what didn't work: [docs/SCUM.md](docs/SCUM.md).

## Known differences from the original cartridge

0.3.0 tries to act like the original cart. These are the differences a player can notice. We know about each one, and
each one is there on purpose:

- **Starting takes longer than on the cart.** Before the game starts, the core checks the firmware file, and it holds
  the game until the cart's chip is ready. It also reads the cart's save table from your copy of the game while the game
  waits. In simulation that read adds about a tenth of a second at power-on and at each Soft Reset, and the firmware
  file check adds about 0.15 seconds of black screen after the Pocket's loading bar. The very first start also builds the
  sound cache (about 30 seconds total), and every start after that checks it (about 2 seconds of black). After that, the
  game waits for the cart's chip to set up its sound and sprites for the same number of frames as on a real cart.
- **A Console Reset early in the boot.** If you press it during the game's fake licence screen at power-on, this core
  stays black for about 2 seconds before the NX TERMINAL screen. A real cart, pressed a bit later in that screen, stayed
  black for about 6.5 seconds. We haven't compared a press at exactly the same moment. Where a Reset locks up and where
  it restarts follows the game's own checks, same as on the cart. A Reset during the intro's SEGA CD zoom freezes the
  picture, just like on the cart, where only switching it off gets you out. Here, **Soft Reset (mini game)** gets the
  game going again.
- **One frame of the intro logo zoom.** One frame of the SEGA CD logo zoom can land one step off. That's a timing race
  inside the game itself, between its main loop and its screen interrupt. We don't know which picture a real cart shows
  there.
- **The Pocket's menu.** The cart doesn't have a menu. While the Pocket's menu is open, the music pauses, the cart's
  sound effects go quiet and the cart's watchdog stops counting.
- **Datenmeister's output.** In Datenmeister mode the sound leaves the cart's chip the same way it does on the cart.
  What the cart's own output circuit does to it after that (its level next to the YM music, a low cut, its polarity)
  isn't copied. Instead there's a simple stand-in: one volume, and a filter that only takes out a steady offset (below
  4 Hz).
- **Corners the game never reaches.** A few edge cases the game never hits, like asking for more than 53 sprite slots,
  an object number of 268 or higher, or a zoom or unpack that runs past the chip's own memory, are handled safely here.
  On the cart, the chip would read or write unrelated memory of its own.

The full list, with how each difference was measured, is in [firmware/docs/ALLOWLIST.md](firmware/docs/ALLOWLIST.md).

## MegaWire

- **No menu setting.** 0.2.6 had a MegaWire On / Off row. In 0.3.0 it changed nothing, so it's gone.
- Our MegaWire code always runs, and acts like a real cart's does with no MegaWire module plugged in. The Pocket never
  has a module, so the boot terminal says MODEM : NONE, and there's no MegaWire icon and no MEGAWIRE row in Options,
  like a real cart with nothing plugged in. 0.2.6's "connected" look is gone.
- Two details only a plugged-in module would ever see: the server name stored for the module is `www.koalakoa.com`,
  where the cart names its own server, and the restart command in the game's own MegaWire menu doesn't save a MegaWire
  record.
- The intro's "MegaWire 4.0" logo is part of the game's own credits screen. A real cart shows it with no MegaWire
  attached. It doesn't mean a MegaWire is plugged in.

## Little-Man Firmware

Little-Man Firmware (trademark pending) is the firmware the cart's chip runs in this core. It's one file,
`little_man_firmware.bin`, version 1.0, and it holds three things: the firmware itself, our MegaWire code, and the brain
of the game's CPU MATE partner.

- It goes in `/Assets/paprium/Koala_Koa.Paprium/` on the SD card. See [docs/INSTALL.md](docs/INSTALL.md).
- The core checks the file at every power-on, before the firmware starts. It isn't signed and it isn't encrypted. The
  check looks at its length, its version, its fixed layout and two checksums, and that's all.
- If the file is damaged or was made for a different core version, the core turns it down: the screen goes plain red,
  with no text and no sound, and the game doesn't start. Copy over the firmware file that goes with your core, then quit
  the core and start it again.
  If the file is missing or the wrong size, the Pocket itself tells you before the core starts.
- The core and the firmware file go together. 0.3.0 takes Little-Man Firmware 1.0. Any later firmware release will say
  which core versions it runs on.
- The source is in [`firmware/`](firmware/), under GPL-3.0-or-later, with its own design docs and
  [THIRD_PARTY_NOTICES.md](firmware/THIRD_PARTY_NOTICES.md).
- The **Little-Man** entry in the core's menu is the cheats. It has nothing to do with the firmware file.

## Known issues

None listed for 0.3.0.

The two known issues of 0.2.6, a Soft Reset after changing **Console** or **Mega CD** that needed a second Soft Reset
and a Soft Reset that rarely ended on a black screen, were tested and are fixed in 0.3.0 with Little-Man Firmware 1.0.

Things that were listed here up to 0.2.6 and have since been fixed are under [Fixed here](#fixed-here) (0.1.0 to 0.2.6)
and [What changed since 0.2.6](#what-changed-since-026) (0.3.0). The differences from the original cart that are there on
purpose are under [Known differences from the original cartridge](#known-differences-from-the-original-cartridge).

### Fixed here

This table is the record for 0.1.0 through 0.2.6, with each fix written up the way it was made back then. Those releases
ran a cart firmware built from krikzz's mega-ppm and played the released soundtrack. 0.3.0 replaces both (see
[What changed since 0.2.6](#what-changed-since-026)). So when a row says "now", it means from that release up to 0.2.6.
Two rows read differently in 0.3.0: a single byte the console writes into cart memory (the first row) gets stored on both
halves of the word, and the game's "VM DAC" option, its YM sound path, actually plays.

Bugs present in every other Paprium build on this hardware, including the MiSTer
core this forks. All verified on real hardware: up to 0.2.5 in both Arcade and
Original modes; the 0.2.6 rows on an arcade run to the credits plus the regression
list in the [changelog](#changelog). The exception is the first row: what it fixes
shows only by chance, and late in a run, so it was checked in a simulation of the
core's cartridge memory and in an emulator running the same rule. On hardware, enemies
dropping in on MTS and Roof-Top after a food pickup, the moment the game runs its
check, played normally on the release build.

| Fix | Was |
|---|---|
| When enemies dropped in from above, an enemy could turn invisible and unkillable and stop the screen scrolling, so the section could not be finished. In Original mode, beating Pang at Golden Of Seas did not always give you his KTV Member Card, so a later run ended at Digniti KTV ("THE END?") instead of going on to The Vault, Sanophix Labs, The Solarium and the ending | **Cartridge memory** (0.2.6). The core's cartridge memory stored the console's single-byte writes, which a real cartridge does not. The game's own check of the cartridge, which runs in ordinary play, saw that and concluded it was not running on a genuine cartridge. From then until the game was reset or switched off, it quietly did two things: when enemies dropped in, it could freeze an enemy out of the game, invisible and unkillable, holding up the section (pausing does not clear it); and in Original mode, when Golden Of Seas was cleared, it left Pang's KTV Member Card out of the save nearly half the time, though he still hands it over on screen. The bouncer at Digniti KTV lets you through to The Vault only with that card; without it the run ends there with "THE END?" and nothing saved, which is also what a real cartridge does for a player who never beat Pang. A card left out stays out after a reset, because it is the save that lacks it. Nothing on screen says why, and nothing else changes. Every earlier release of this core stored those bytes, and so does the emulator this project compares against, so comparing against it could not find this. The cartridge memory now ignores the console's single-byte writes (`ramdp_io.sv`), and the check passes as it does on a real cartridge. Every clear of Golden Of Seas in Original mode now keeps the card. A save that lost it under an earlier release does not get it back by itself: clear Golden Of Seas once more in Original mode. Word writes, and the cartridge MCU's own writes, are unchanged. Whether a real cartridge ignores such a byte or writes it over the whole word is not known; the game cannot tell the two apart, and [0.2.6: what worked, and what did not](#026-what-worked-and-what-did-not) says why this core ignores it |
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

Up to 0.2.6, the firmware changes were patches on top of krikzz's [mega-ppm](https://github.com/krikzz/mega-ppm). They're
in [patches/](patches/) and rebuild that firmware from a clean mega-ppm clone. From 0.3.0 on, the cart's chip runs our own
firmware: see [Little-Man Firmware](#little-man-firmware).

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
- **Watching the poll sites.** The boot log listed everything that reads the cart's busy flag, plus the command posted
  just before. Watching how the game behaved at those five addresses turned up one reader that waits for the command
  response first and *then* polls for busy-clear, with a 65,534-iteration timeout. The first busy fix raised the flag
  again before the response, so that reader sat through its whole timeout (0.56 s) after every scene load. That was the
  boot pause, and the fix was a dozen lines of 68000 code (`scripts/busy_polls.py`, `scripts/backtoback_posts.py`)
- **A crash recorder in battery RAM.** A build variant has the firmware write a
  40-byte record of what it is doing — phase, command, stack pointer, trap cause
  — into the save every frame, and the save survives a hang if the core is
  exited from the Pocket's menu (`scripts/decode_heartbeat.py`). It showed the
  MCU never trapped and the 68000 never faulted during a hang that looked like a
  crash, which took a whole chain of "corrupted payload → CPU fault"
  explanations off the table without a single fix attempt

- **Going by the game's own protocol instead of either port's guess.** Word `+0xA` of the animation record is a frame
  counter that `mega-ppm` bumps every draw and restarts on any mismatch. In GPGX it's a one-shot reset the cart clears.
  The game's own behaviour settles it: it compares the requested animation with the current one, does nothing if they
  match, and otherwise writes `1` once. Once we knew that, "a refused block load rewinds the object" turned into "a
  refused block load overwrites the game's one request", and the attack frames came out of a two-line change. Neither
  implementation was the reference. The cart was
- **Counting in the save, before and after.** Two counters added to the save
  block (`scripts/decode_sat_snapshot.py`) measured the fault on the card that
  shipped: 230 lost animations in ten minutes on the old rule, and 92% of them
  completing within a draw or two on the fix. The same file then refuted the
  next idea: a floor on the loader's budget fired in 44 of 7,808 frames while the
  walk-in slid on unchanged, so the budget was not the mechanism. A counter with
  a denominator turns "feels better" into a number, and a negative result into
  a closed door
- **Trying to knock down every idea before a build.** We checked each candidate against the firmware, the reference and
  the game's behaviour. That put the lost switch at the top, ruled out six other explanations, and showed that the game
  rewrites the remaining-budget word itself between frame start and the first draw. That caught a build that would have
  done nothing, before it ever got to the Pocket
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
  every item on the regression list passed. The first release build passed the same list
  again; the final one, with the cartridge-memory fix, was checked once more (the
  [changelog](#changelog) lists what).
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
- **A census of the game's single-byte writes.** Listing every single-byte write the game
  makes into the cartridge memory turned up one that is not data but the game's own check
  of the cartridge. A real cartridge does not keep that byte; every release of this core
  did, so the game took it for a copy (the first row of [Fixed here](#fixed-here)). Two
  copies of the emulator in lockstep, one keeping such bytes and one ignoring them: when
  the check ran, it failed in the first and passed in the second; recorded solo and
  two-player runs to the credits drew the same screen and sent the cartridge the same
  commands on every frame (about 950,000 of them); and the Arcade Stage Select coin still
  credits. A simulation of the cartridge memory, old and new side by side, reads back
  what a real cartridge gives with the fix, and matches the old design on every output
  at every clock while the game writes whole words.

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
  passed, and seed 2 became the first release build. After the cartridge-memory fix the
  core was fitted again: seed 2 passed the gate but did not boot (the next entry); of
  six seeds of the fixed design, 1, 2, 3 and 6 passed the gate, and the release is
  seed 3.
- **The first build of the cartridge-memory fix.** It passed the timing check, then did
  not boot on the Pocket: a black screen at once, every time. The fix only changes what
  happens when the console writes a single byte, and none is written while the core
  boots, so the build was suspected rather than the fix. Twelve of the pins that carry
  addresses and byte masks to the Pocket's memory chip are not covered by the timing
  check, and their timing changes from build to build. We measured them on this build
  and on four earlier ones tried on hardware: this build was by far the slowest, and the
  one of the four that had gone wrong on hardware (it froze in play) was the next
  slowest. Six seeds of the fixed design were fitted, and the release is the one with
  the best margin on those pins, better than every build measured before; it boots and
  plays. That these pins caused the black screen is the leading explanation, consistent
  with every hardware result so far, not a proof.
- **Storing a single-byte write as the whole word.** Writing the byte over both halves of the word passes the game's
  check too, and it might be what a real cart does. But the Arcade Stage Select coin writes a few stray bytes, some into
  cart memory, and stored as whole words they overwrite bits of the game's sprite records. In the emulator, sprites went
  missing from the first coin on. Ignoring those bytes changes nothing the game uses, so 0.2.6 ignores them. 0.3.0 stores
  such a byte on both halves of the word.
- **"Free padding" that wasn't.** The Scum! pad code went into a 512-byte stretch of ROM space that looked like padding.
  It's actually the Hall of Fame bar's tile data, which the game copies with a DMA. That was 0.2.6's first known issue,
  and it's fixed in 0.3.0 (see [What changed since 0.2.6](#what-changed-since-026)).
- **A one-time read.** The 0.2.6 firmware copies the console model into the game's view once per reset, so changing it
  around a Soft Reset gives you one mixed boot. That was 0.2.6's second known issue, and it's tested and fixed in 0.3.0
  with Little-Man Firmware 1.0. We thought about a latch that holds the options during reset and decided against it.

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

In 0.2.x that also turned the menu into a controlled A/B for the rate-step fix. `52` then `D2` dropped 24000 Hz to
12000 Hz: an octave down and about twice as long. Compare that with `22` then `A2`, which **had to** sound the same,
because row `0x22` is already at the slowest rate and the 0.2.x firmware's rate step stopped there instead of
wrapping around. Six rows work that way (`22, 2C, 2F, 48, 4C, 71`). On those, sounding the same meant the fix was
working, not failing. Without a pair that's already maxed out as a control, an unchanged sound could mean either
thing.

In 0.3.0 the music is fixed. The sound effects
and the music now come from our rebuild of the cart's synthesiser and our own firmware, not from the 0.2.x firmware.

`scripts/predict_boombox_pairs.py <rom>` reads the table and prints the predicted
rate and duration for any pair, so a sweep can be checked against numbers rather
than judged by ear alone.

[docs/PORT_PLAN.md](docs/PORT_PLAN.md) is the full engineering record: what was
measured, what was tried, and which explanations turned out to be wrong.

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

`deploy_to_sd.sh` copies the core's package to the SD card and leaves the Assets folders alone, so it won't copy the
firmware file for you.

The release fits a Cyclone V `5CEBA4F23C8` at 18,233 ALMs (99 %), 298 M10K blocks (97 %) and 24 DSP blocks (36 %). There's not much room left, so read [docs/BUILD_REFERENCE.md](docs/BUILD_REFERENCE.md) before you add
anything.

`generate.tcl` takes an optional second argument, a fitter seed. Timing on this device swings by several nanoseconds
from seed to seed, so one failing fit doesn't prove a change broke timing. The release bitstream is seed
16, which is also what `projects/megadrive_pocket.qsf` says, so
`quartus_sh -t generate.tcl paprium` and `quartus_sh -t generate.tcl paprium 16` fit the same.
The 0.3.0 gate was setup ≥ −2.60 ns, hold > 0, a re-check of the clock crossings, the memory chip's pins and the
video timing, and a census of the paths behind the freezes we'd already fixed. Of the twelve seeds tried on the
release design (7 to 18), only seed 16 passed it, and three didn't fit at all. Seed 16 (−0.643 ns setup, +0.084 ns
hold) is the release, and it passed an hour's warm soak on a Pocket.

**The firmware builds on its own.** From 0.3.0 on, the bitstream only holds a small boot stub for the cart's chip. Its
images in `rtl/PAPRIUM/` (`mcu.txt` holds the stub; `mcu_ext.txt` and the four lanes of the chip's work RAM,
`wram_b0.txt` .. `wram_b3.txt`, are zeros) only change when the stub does. The firmware itself shows up at power-on as
`little_man_firmware.bin` (see [Little-Man Firmware](#little-man-firmware)), so changing the firmware doesn't need a new
fit. Its source is in [`firmware/`](firmware/): `firmware/README.md` explains how to build it, and
`firmware/docs/FAFRIUM.md` explains how a build turns into the file (Fafrium is the file's working name inside the
source). It's built with the xPack RISC-V GCC 15.2.0-1 toolchain. A different GCC version builds working firmware, just
with different bytes.

The CPU MATE brain inside the release file isn't in this repo's source. A firmware file built without it runs the game,
and the CPU MATE partner just stands there.

A fresh fit isn't guaranteed to match the released bitstream bit for bit, so treat the release download as the
reference.

Variants: `paprium` is the release. `generate.tcl` still offers `paprium_nosfx`, `paprium_cddadbg` and `paprium_cmdlog`,
the 0.2.x debug builds; they weren't part of 0.3.0's testing.

> Always check the fit summary **timestamp** and the `.rbf` **size** before you
> flash. Quartus can fail and leave old files behind, and those give you believable
> wrong answers on hardware.

[docs/BUILD_REFERENCE.md](docs/BUILD_REFERENCE.md) has the fit and timing gates,
plus the measurements behind them.

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

Please check [Known issues](#known-issues) and
[Known differences from the original cartridge](#known-differences-from-the-original-cartridge) first. And just so you
know, **we can't help you get the game**: players supply their own legally obtained copy (see
[What you need](#what-you-need)), and there's no music file any more. Tell us which firmware file is on your card too
(for 0.3.0: Little-Man Firmware 1.0).

## Changelog

**0.3.0** — the cart's own behaviour: our own firmware for the cart's chip, Little-Man Firmware 1.0, as its own file,
and the game's music made the way the cart makes it, in both sound options.
Bitstream seed 16: 18,233 ALM, 298 M10K, 24 DSP, worst setup −0.643 ns, worst hold +0.084 ns.

**New**
- **The music, made the way the cartridge makes it.** We rebuilt the cartridge's sound chip in the core's logic, and our
  music player runs in the firmware the way the cartridge's does. So the music follows the game like it does on a cart:
  the low-health music, the sax man's cues, the Boom Box's X, Y and Z effects and the fades.
- **Sound effects on our rebuild of the cartridge's synthesiser**, filter and echo included.
- **Little-Man Firmware**, our own firmware for the cartridge's chip, now its own file. It holds the firmware, our
  MegaWire code and the CPU MATE partner's brain. It's GPL-3.0-or-later, and the source is in the repo's `firmware/`
  folder. If the file is damaged or was made for a different core version, the screen goes plain red and the game won't
  start (see INSTALL).
  If the file is missing or the wrong size, the Pocket itself tells you before the core starts.
- **A sound cache.** On the first start we unpack the game's sounds from your copy of the game, with a bar along the
  bottom of the black screen. The Pocket keeps them in `paprium_sound_cache.bin` for next time. It's made on your Pocket,
  so keep it on your own card.
- **Console Reset** in the core's menu. It resets the console just like the console's own Reset button.
- **Arcade Mode is now a virtual Grand Stick III**, with Off, On, Multiplayer and Stick Only. On and Multiplayer flip the
  stick's ARCADE switch, so the game turns on its own arcade mode with no change to the ROM. Select drops a coin, and like
  a real stick, the first coin after power-on or a reset doesn't give a credit. Stick Only is the stick with every switch
  off: the normal game, with Select as the stick's Mode button. Also new: **Arcade Coins** and **Attract Only**, the
  stick's other switches, for On and Multiplayer.
- **3-Player Mode** (Off by default): an EA 4-Way Play, for the game's three-player modes with three Dock controllers.
- **TeraDrive** in the Console list.

**Changed**
- **Saves** now use the cartridge's own format: 8 KB, the size of the cart's save chip. We convert a 0.2.x save once, on
  the first start. We haven't tested going back to 0.2.x with a converted save, so keep a copy of your 0.2.x save.
- **No more soundtrack file.** 0.3.0 doesn't read `paprium.pcm`, so you can delete it (0.2.6 still needs it).
- **6-Button** gives the game real six-button pads on controllers 1 and 2, and the game reads X, Y, Z and Mode itself.
  An empty controller port reads as empty, so no more phantom player 2.
- **Opening the Pocket's menu pauses the music** right where it is and mutes the cartridge's sound effects. Close the
  menu and the music picks up from the same spot.
- **The cartridge's watchdog is back.** With the menu closed, if the game stops sending its once-a-frame signal for
  about 4 seconds, the cartridge's chip halts, same as a real cart.
- **Sprites, zooms, unpacking the game's data, saves and start-up** now work the way the cartridge does them.
- **Sprites use the cartridge's colours.** Dice's afterimage outline is green like on the cart (0.2.x drew it blue), and
  the first level's doorway takes its colours from the cartridge's own rule.
- **A single byte the console writes into cartridge memory** now lands on both halves of the word.
- **MegaWire** is gone from the menu. Its On / Off row did nothing in 0.3.0: our MegaWire code always runs and behaves
  like the cartridge's, and with no module plugged in (the Pocket never has one) the game looks like a cart with
  nothing plugged in.

**Fixed**
- **Hall of Fame name entry**: the highlight bar is clean with Arcade Stage Select or 6-Button on (a 0.2.6 known issue).
- **The Arcade coin** plays the game's coin sound on every press.
- **Soft Reset** holds the 68000 from the reset's very first clock, so a warm reset no longer repeats the bus cycle it cut.
- **TMSS**, the licence check later consoles run at power-on, works on every all-in-one Mega CD unit (Wondermega,
  Wondermega M2 / X'Eye, LaserActive, Aiwa CSD-GM1, CDX).
- **Soft Reset after a Console or Mega CD change**: the two other 0.2.6 known issues, a second Soft Reset needed now
  and then and the rare black screen after a Soft Reset, are tested and fixed in 0.3.0 with Little-Man Firmware 1.0.

Tested on a real Pocket before release, on the release bitstream with the TEST firmware file and then the RELEASE
one swapped in: the first start, the saves and a new save, five cold starts, the firmware file renamed away and
swapped for the wrong file, Console Reset in play, at the NX terminal and early in the boot, the intro and stage
zooms, MegaWire's boot terminal, the attract mode and the game's hidden MegaWire screen, the music in YM and
Datenmeister, sound effects, CPU MATE, the Scum! menu, the Block 888 doorway and Dice's afterimage, busy scenes, an
hour's warm soak, and the menu without its MegaWire row. The earlier 0.3.0 test builds were checked against a cart
item by item: the music and its effects (the low-health music, the sax man, the Boom Box's X, Y and Z, the Blue Bar,
the fades, the pause dip), the Grand Stick III options, the sprites side by side, the zooms, the saves and their
one-time conversion, and every kind of Console Reset.

**0.2.6** — the CPU MATE partner, the menu options, and the cartridge's own sprite
rules. Bitstream seed 3: 18,079 ALM, 253 M10K, worst setup −1.026 ns, worst hold
+0.085 ns.

- **CPU MATE.** With a Mega CD unit picked in the menu, the game offers its computer-controlled partner. The partner's
  brain, a reverse-engineered emulation of the game's CPU partner, runs on the cart MCU behind a Mega CD link that
  answers at the moment the real sub-CPU would. The game's code isn't patched. In 0.2.6 the brain was built into the
  release bitstream, and anyone building the core got it as a separate download
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
- **Invisible, unkillable enemies, and Pang's KTV Member Card going missing, are
  fixed.** The core's cartridge memory stored single-byte writes, which a real cartridge
  does not, so the game's own check of the cartridge concluded it was not genuine. In
  Original mode it then left Pang's KTV Member Card out of the save nearly half the
  time, so a later run ended at Digniti KTV. The cartridge memory now ignores
  single-byte writes, and the check passes ([Fixed here](#fixed-here)); a save that
  already lost the card needs Golden Of Seas cleared once more. Every earlier release
  had this.
- The Boom Box bars run at the measured tempo instead of about 20% fast.
- Under the hood: a clock-crossing race on the MCU's stream pointer fixed at its root,
  FX68K's own multicycle constraint, the sound-effect echo line and the album buffer
  moved into the Pocket's cellular RAM (freeing block RAM), the Pocket's SRAM opened to
  the MCU, a stale one-clock reply on APF file commands fixed, and debug output compiled
  out of the release firmware.
- Two known issues come with the new options: the Hall of Fame name-entry bar with
  Arcade Stage Select or 6-Button on, and, rarely, a second Soft Reset needed after a
  Console or Mega CD change ([Known issues](#known-issues)).

Hardware-tested on a real Pocket before release: default boot, all 8 consoles and every
Mega CD unit (picture, splash, region), the TMSS consoles, MegaWire off, 32X Mode, and
the regression list: the select screen, switching between Original and Arcade modes, The
Solarium, the credits, the elevator, dropped weapons, the attract demo, CPU MATE, busy
fights, sound effects and echo. Every Scum! switch and stage name was checked on the
0.2.6 test builds. The final build, with the cartridge-memory fix, was checked again:
five cold boots; Soft Resets across switches between Arcade and Original modes, Console,
Mega CD and MegaWire; enemies dropping in on MTS and Roof-Top after a food pickup; the
Arcade coin, which credits and plays the coin sound; CPU MATE joining and playing well;
and a long play including the elevator and The Solarium.

**0.2.2** — the 68000 changes. The core now runs [FX68K](https://github.com/ijor/fx68k)
(Jorge Cwik, GPL-3, vendored in `rtl/fx68k/`) instead of the gate-level netlist. As a
player you shouldn't see or hear any difference; the point is space. The fit drops from
98% to 88% ALM, and that headroom is what the live synthesiser needed. It arrived in 0.3.0.

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

**Little-Man Firmware has its own version number**, starting at 1.0 with 0.3.0. The file name on the SD card stays
`little_man_firmware.bin`. The version is in the download's name, inside the file and in the release notes. Every core
release says which firmware version it takes, and every firmware release says which core versions it runs on.

## Sponsor

If this is useful to you, you can sponsor the work at
[github.com/sponsors/thekoalakoa](https://github.com/sponsors/thekoalakoa).

Sponsoring doesn't change anything about the core or its firmware. Both are GPLv3, and all their source is right here
(the firmware's is in [`firmware/`](firmware/)) except the CPU MATE brain (see [Licence](#licence)). None of it is or
ever will be behind a sponsorship. It also can't get you the game (see [What you need](#what-you-need)).

## Lineage

This core stands on the projects below. It's GPLv3 all the way through, except for the parts under permissive licences:
the BSD-licensed parts of the cartridge (NEORV32, krikzz's mega-ppm code, the WavPack decoder and two routines from the
toolchain's C library), the MIT-licensed Pocket and audio modules (from agg23, OpenGateware and Gregory Hogan) and
Analogue's framework files. One file from agg23, the scanline filler, doesn't name a licence of its own (see its row
below). Every one of them stays credited. Our own changes to those parts are GPLv3 like everything else; see
[Licence](#licence). The work that got this core going but isn't in it anymore is credited under [History](#history).

| | |
|---|---|
| [Nuked-MD-FPGA](https://github.com/nukeykt/Nuked-MD-FPGA) | nukeykt — a gate-level model of the real silicon, which is to say the console itself. Everything except the 68000: the VDP, the arbiter, the I/O chip, the FM, the Z80 and the board |
| [FX68K](https://github.com/ijor/fx68k) | Jorge Cwik (ijor) — the 68000, since 0.2.2. It takes over from Nuked's gate-level CPU and frees up the logic the cart's synthesiser needs. Nuked's netlist is still in the tree behind `USE_FX68K` |
| [MegaDrive_MiSTer](https://github.com/MiSTer-devel/MegaDrive_MiSTer) | MiSTer-devel — the core built around it |
| [openFPGA-MegaDrive](https://github.com/drizzt/openFPGA-MegaDrive) | drizzt — the Pocket port this one forks from |
| [Paprium_MegaDrive_MiSTer](https://github.com/MisterPezz82/Paprium_MegaDrive_MiSTer) | MisterPezz82 — the Paprium cartridge RTL our cartridge is built on: the MCU integration, mailbox and memory map (`paprium_cart`, `mcu_core`, `fpgio`, `ramdp_io`, `memory`, `paprium_mcu_mem`, `paprium_backup`, `structs`, `paprium_defs`, all heavily changed since); serving patches as ROM reads, which the Scum! switches still use; and the SDRAM port-2 counter from their V.04 (in `rtl/sdram.sv`, Sorgelig's SDRAM controller from MegaDrive_MiSTer, GPL-3.0-or-later), which lets the cart's chip win a memory turn when it's waited too long |
| [mega-ppm](https://github.com/krikzz/mega-ppm) | krikzz — the FPGA sources the cartridge files `fpgio.sv`, `mcu_core.sv`, `memory.sv`, `ramdp_io.sv` and `structs.sv` come from, and `audio_sfx.sv` and `audio_clock.sv`, which are still in the repository but aren't built into the bitstream (BSD-3-Clause). The firmware every release up to 0.2.6 was built from is credited under [History](#history). |
| 0.2.6 firmware code still carried | Code from the 0.2.6 firmware that this release still has in it: krikzz's mega-ppm code (BSD-3-Clause) in the 0.2.6 command bodies `firmware/interim/s1/bodies_s1.c` (moved over from mega-ppm's `paprium.c`), which the 0.3.0 firmware still links, and in the 0.2.6 build's source files kept in `firmware/legacy/026/`, `firmware/interim/` and `firmware/board/`; the 0.2.6 LZO decoder in `firmware/legacy/026/mame.c`, ported from Genesis Plus GX's Paprium support (source for the 0.2.6 build only); and the parts of `mame.c` that mega-ppm based on TheHpman's MAME Paprium work. Each one keeps its credit, and krikzz's code keeps its notice. |
| [NEORV32](https://github.com/stnolting/neorv32) | Stephan Nolting — the RISC-V processor the cart's chip runs on (it comes in with MisterPezz82's cartridge RTL), plus the linker script our firmware's linker scripts are based on (BSD-3-Clause). Its runtime, which the firmware linked up to 0.2.6, is credited under [History](#history) |
| [WavPack](https://github.com/dbry/WavPack) | Conifer Software — the WavPack 4.0 "tiny decoder" in the firmware, as the Rockbox project carries it. It unpacks the game's sound bank from your own copy of the game on the first start (BSD) |
| newlib | the C library from the xPack RISC-V GCC toolchain: its `memcpy` and `memset` are linked into the firmware (SiFive, FreeBSD licence) |
| openFPGA and audio modules | agg23 (Adam Gastineau) — the Pocket's data loader and unloader, the I2S audio output and FIFO, and the scanline filler that pads each frame to the height the Pocket's scaler wants (`rtl/scanline_filler.sv`, from agg23's openfpga-SNES; it has no licence line of its own); OpenGateware (Marcus Andrade) — the Pocket's audio mixer and filter loader, and the audio filters written with Alexey Melnikov, as agg23's openFPGA cores carry them; Gregory Hogan (Soltan_G42) — the console's audio filters, as MegaDrive_MiSTer carries them (MIT, except the scanline filler; the OpenGateware filter modules themselves are GPL-3.0-or-later) |
| Analogue Pocket Framework | Analogue — the Pocket's platform files, under Analogue's licence agreement in their headers |


**The cart's firmware is our own: Little-Man Firmware.** Our team wrote it from our own study of how the cart behaves.
It's GPL-3.0-or-later. It ships as its own file, `little_man_firmware.bin` (Little-Man Firmware 1.0 goes with this
release). The source is in [`firmware/`](firmware/), published with this release, along with the design docs that explain
how it all works.

### Menu switches, controllers and the CPU MATE link

Serving patches as ROM reads is MisterPezz82's idea, and the Arcade Stage Select list comes from their Paprium MiSTer core
(V.05 and V.06). krikzz found the arcade start-stage word. The cheat spots were found on Genesis Plus GX with a 68000
write watch. The MiSTer Paprium team's 32X and Mega CD detection stubs are where `paprium_addons.sv` began, and we worked
out the CPU MATE link's restart rule together with them. New in this core: the health, pill and life patches, the console
options, the CPU MATE link, the virtual Grand Stick III and the 3-Player Mode adapter.

### Research credits

Big thanks to Project Little Man, TheHpman (MAME Paprium research), MAVProxyUser (Genesis Plus GX Paprium work) and the
whole Paprium preservation community.

### Artwork

The platform image (the banner on the Pocket's system list) is artwork produced by good friends for this core, handed
over in Analogue's format. The artwork is theirs. If you'd rather start from a PNG, `scripts/make_platform_image.py`
converts one into that format.

### What this port adds

- **The cart's synthesiser, rebuilt in logic** (`rtl/PAPRIUM/paprium_synth*.sv`): the wave voices, the sound effects, the
  filter and the echo, and the Datenmeister output, driven by our music player and sound-effect engine in the firmware.
  It takes over from 0.2.x's sound path and the album.
- **A sprite decoder that works the way the cart's does** (`paprium_hwdec.sv`), plus the cart's register file at
  `$1FE0-$1FFF` (`paprium_regfile.sv`).
- **Controllers the way the cart sees them** (`paprium_pads.sv`): real six-button pads, empty ports, an emulated EA
  4-Way Play, and a **virtual Grand Stick III** (`paprium_gs3.sv`).
- **The sound cache**: a data slot the Pocket keeps between starts (`target/pocket/paprium_cache_slot.sv`), the
  first-start unpack with its bar (`paprium_bar.sv`, `paprium_holdvid.sv`), and the console's frame counter the firmware
  uses to time its work (`paprium_vs_tap.sv`).
- **The firmware file loader**: the bitstream only keeps a small boot stub. It checks `little_man_firmware.bin` and
  starts it, or holds the cart on a plain red screen (`rtl/cartridge.sv`, `paprium_xlink.sv`, and the firmware's
  `board/pocket/fafrium/`; Fafrium is the firmware file's working name inside the source).
- **Console Reset**: Console Reset in the Pocket menu resets just the 68000, like the console's own Reset button.
- **The MegaWire code** in the Pocket's SRAM, and a fix to NEORV32's Wishbone gateway so the cart's chip can run code
  from there (`rtl/PAPRIUM/risc-v/`, with a "Changes:" line under NEORV32's notice).
- Carried over from 0.2.x: Scum!, the add-on answers, the CPU MATE link, the Pocket's cellular RAM and SRAM.
- And then the firmware's own parts, all written to act like the cart's chip: command handling and status bits, the job
  queue and the watchdog, the sprite engine, the zooms, the unpackers, saves in the cart's format, the start-up, the
  music player and the sound effects, and our MegaWire code.
- The handful of places where we differ from the cart on purpose are written down and were signed off one at a time:
  see [Known differences from the original cartridge](#known-differences-from-the-original-cartridge).


The cartridge RTL underneath all this is MisterPezz82's, and their
[KNOWN_ISSUES.md](https://github.com/MisterPezz82/Paprium_MegaDrive_MiSTer/blob/master/docs/KNOWN_ISSUES.md) is a really
useful engineering record. It saved us at least one wasted build, because it already wrote down an elevator fix that had
been tried and didn't work.

If something's wrong with **this** core, please report it here and not to those projects. Odds are it's something this
port did.

## History

Releases 0.1.0 through 0.2.6 stood on work that 0.3.0 doesn't run the same way anymore. That work got this core going, so
it stays credited here. Whatever of it this release still carries is listed in [Lineage](#lineage) too.

| | |
|---|---|
| [mega-ppm](https://github.com/krikzz/mega-ppm) — krikzz | The replacement cartridge MCU firmware (BSD-3-Clause). Every release from 0.1.0 to 0.2.6 ran it, built with this project's changes in `patches/mega-ppm-pocket.patch`: the elevator, animation and Boom Box fixes, and 0.2.6's cartridge rules. 0.3.0 runs our own firmware. krikzz's image converter has been replaced by our own; the image files keep its layout |
| krikzz's first-level door fix | The palette fix for the first level's door (object 107, sprite 4) that 0.1.0 to 0.2.6 carried, reported by MisterPezz82 and shipped in their V.05. From 0.3.0 the cart's own palette rule gives the door its colours |
| MisterPezz82's SFX engine and MD+ adapter | `audio_sfx.sv`, the 8-channel sound-effect engine adapted from mega-ppm's, and `paprium_mdp_adapter.sv`, the MD+ link the album played through: the 0.2.x sound path. From 0.3.0 our rebuild of the cart's synthesiser plays the sound effects and the music |
| [Genesis Plus GX](https://github.com/ekeeke/Genesis-Plus-GX) — Eke-Eke and contributors; its Paprium support headed Project Little Man | The 0.2.x firmware's LZO decoder (asset type `0x81`), ported from its Paprium support (`paprium.h`), because stock mega-ppm's decoder broke the subway, among other spots. Genesis Plus GX is also an emulator our tests use, with logging patches of our own (the cartridge-window logger among them), and `tools/da-twin/da_twin.c` carries its decompressors for a test comparison |
| TheHpman's MAME Paprium work | `rom.cpp`, which mega-ppm's `mame.c` says it's based on: the firmware in 0.1.0 to 0.2.6 was built on it |
| NEORV32's runtime | Stephan Nolting — the start-up code (`crt0.S`) and the `neorv32_*` library the firmware linked up to 0.2.6 (BSD-3-Clause). 0.3.0's firmware has its own start-up code; the NEORV32 processor and the linker script are still in (see [Lineage](#lineage)) |
| The album path | Up to 0.2.6 the music was the released soundtrack, which you turned into a `paprium.pcm` file: `paprium_cdda_fetch/buf/play.sv` streamed it from one data slot, and `paprium_ima_decode.sv` decoded IMA ADPCM in logic. From 0.3.0 our rebuild of the cart's synthesiser plays the music, and the soundtrack file isn't used. André Coelho's `scripts/build_cdda_adpcm_fast.py` (#10) packed that file on every core at once, byte for byte the same as our packer |

### The 0.2.6 menu switches and fixes (as credited in 0.2.6)

The arcade unlock and the Mode-button credit are adroxe's
([Paprium-Arcade](https://github.com/adroxe/Paprium-Arcade)). krikzz found the arcade start-stage word. Serving patches
as ROM reads, the pad hook that injects X, Y, Z and Mode, and the stage list come from MisterPezz82's Paprium MiSTer core
(V.05 and V.06). The sprite-table end mark that fixes The Solarium float is the MiSTer Paprium team's patch, their 32X
and Mega CD detection stubs are where `paprium_addons.sv` began, and we worked out the CPU MATE link's restart rule with
them. The health, pill and life patches, the console options and the CPU MATE link were new in this core.

What 0.3.0 changed there:
- **adroxe's Arcade Mode unlock and the Mode-button credit** are gone. Arcade Mode is a virtual Grand Stick III now: the
  game reads its switches and its coin, and the stick's ARCADE switch turns on the game's own arcade mode, on the
  unpatched ROM.
- **MisterPezz82's pad hook** is gone. The controllers are real six-button pads and the game reads X, Y, Z and Mode
  itself.
- **The float end mark**: 0.3.0's firmware closes the sprite table using the cart's own rule.
- krikzz's start-stage word, MisterPezz82's ROM-read approach and stage list, and the MiSTer team's add-on stubs and
  restart rule are all still in (see [Lineage](#lineage)).

## Licence

Copyright (C) 2026 Marsupial Solutions LLC, for the changes made in this repository and for the cartridge firmware. The
projects it's built on keep their own copyright; see [Lineage](#lineage), [History](#history) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

GPLv3 or later. Nuked-MD-FPGA is GPLv2-or-later and FX68K is GPLv3-or-later. Using Nuked's *or later* option is what
lets the two go together, so the work as a whole is GPLv3-or-later. See [LICENSE](LICENSE), plus the vendored
`rtl/upstream/nuked-md/LICENSE` (GPLv2) and `rtl/fx68k/LICENSE` (GPLv3), which both stay as they are.

**The firmware is our own.** Our team wrote the cart firmware, Little-Man Firmware, from our own study of how the cart
behaves. It's GPL-3.0-or-later like the rest of the core. It ships next to the bitstream in the release as its own file,
`little_man_firmware.bin`. It isn't signed and it isn't encrypted. The file also carries the MegaWire code, built from the
same source under the same licence, and the CPU MATE brain (see below). Its source is in [`firmware/`](firmware/) in
this repository, published with every release from 0.3.0 on, along with its design docs and its own
[THIRD_PARTY_NOTICES.md](firmware/THIRD_PARTY_NOTICES.md). Our new files carry
`Copyright (C) 2026 Marsupial Solutions LLC` and `SPDX-License-Identifier: GPL-3.0-or-later`. Files that came from
someone else keep their own notice.

**Little-Man Firmware** (trademark pending) is Marsupial Solutions LLC's name for this firmware.

**We keep the BSD notices for everything still carried**: the NEORV32 processor (in the bitstream) and the NEORV32 linker
script our firmware's linker scripts are based on (in the firmware source, with the Free Software Foundation notice the
script carries); krikzz's mega-ppm code in the cartridge files `rtl/PAPRIUM/fpgio.sv`, `mcu_core.sv`, `memory.sv`,
`ramdp_io.sv` and `structs.sv` (and in `audio_sfx.sv` and `audio_clock.sv`, which stay in the repository but aren't built),
and in the firmware files based on mega-ppm that this release still carries (`firmware/THIRD_PARTY_NOTICES.md` lists
them); the WavPack decoder (in the firmware); and the toolchain C library's `memcpy` and `memset` (in the firmware). Their
original code stays under its BSD licence. Their copyright notices and licence texts are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), which ships in the release too.


Our own changes to that code aren't BSD. They're GPLv3-or-later, like the rest of this core. The firmware file and the
bitstream are distributed under the GPL, with the BSD notices kept.

**We keep the MIT and Analogue notices too.** agg23's modules (`target/pocket/data_loader.sv`, `data_unloader.sv`,
`sound_i2s.sv`, `sync_fifo.sv`), OpenGateware's audio mixer and filter loader (`target/pocket/audio/audio_mixer.sv`,
`filters/filter_loader.sv`, `filters/filters_rom.sv`) and Gregory Hogan (Soltan_G42)'s audio filters
(`rtl/upstream/genesis_lpf.v`, `audio_iir_filter.v`) are MIT-licensed and built into the bitstream. agg23's scanline
filler, `rtl/scanline_filler.sv`, is built into the bitstream too. It names agg23's openfpga-SNES as its source and has
no licence line, so it's credited in [Lineage](#lineage), and our changes to it are GPL-3.0-or-later.
The Analogue Pocket Framework files in `platform/pocket/` (`apf_top.v`, `common.v`, `io_bridge_peripheral.v`,
`io_pad_controller.v`) keep Analogue's licence agreement in their headers; where it differs from the MIT License or the
GPL, it says those licences win. `target/pocket/core_bridge_cmd.v`, from Analogue's core template, names Analogue and
has no licence text. The Quartus-generated IP files keep Intel's terms in their headers. All of these notices are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) as well.

**CPU MATE.** The partner's brain ships inside the firmware file. It's a reverse-engineered emulation of the game's CPU
partner. Its files aren't part of this repository's source. It's only useful together with your own copy of the game.

**The game.** You bring your own copy of the game. The ROM, and anything taken from it, never ships: not in this
repository, not in a release, not in any download. The sound cache the core writes on the first start is made on your
Pocket, from your own copy.

Paprium is a trademark of its owners. This project is not affiliated with WaterMelon. It is a free, non-commercial
project: it is not sold, and the game is not included.

Paprium game content (WaterMelon IP)
This project's GPLv3 license covers only our code. It does not include, and grants no rights to, Paprium's game ROM, code, music, graphics or other assets, which are owned by WaterMelon.

Do not distribute ports, forks or modified builds of this project bundled with Paprium's ROM, decompiled game code or assets. Doing so infringes WaterMelon's copyright and is not covered by our license.
Players must supply their own legally owned copy of the game.
Any port or modification of our code that ships with WaterMelon content without WaterMelon's written permission is unauthorized, and we will report it.
