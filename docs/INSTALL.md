# Paprium for Analogue Pocket: installation (0.3.0)

This is a standalone openFPGA core for **Paprium** (WaterMelon, 2020). It plays this one game and isn't a Mega Drive
emulator, so please don't load other ROMs into it. Use a Mega Drive core for those.

**You need your own copy of the game.** I don't include one and I won't link one. WaterMelon have stopped trading and
the game isn't sold anymore, but that doesn't make it public domain. It's still their work.

---

## What you need

- An Analogue Pocket on **firmware 2.3 or later**.
- A microSD card, formatted the way the Pocket wants it.
- Your own copy of the game's ROM (8 MiB), made from your own cartridge.
- Two downloads from the [release page](https://github.com/thekoalakoa/paprium-pocket/releases/latest):
  - the core, **`openfpga-Paprium_0.3.0.zip`**;
  - the cart firmware, **`Little-Man_Firmware_1.0.zip`**, which has `little_man_firmware.bin` inside.
  The core zip already holds the firmware file, so step 3 below is already done by step 2, and the firmware's own
  download is only for firmware-only updates.

You can forget the soundtrack file `paprium.pcm`. 0.3.0 doesn't read it.

**The core itself isn't in the git repo.** `paprium.rbf_r` is the compiled bitstream, which is a build output, so I
don't commit it. If you clone the repo and copy `pkg/pocket/` to your card, you get the core's settings files **but no
core**. Grab the release zip, or build the bitstream yourself (the README's Building section shows how).

---

## Before you install: keep a copy of your save

First, copy your save to your PC:

```
/Saves/paprium/common/Paprium.sav
```

That's your game progress. The first time 0.3.0 starts, it converts a 0.2.x save once into the cart's own format (see
[First start](#first-start)). I haven't tested going back to 0.2.x with a converted save, so hang on to that copy until
you're sure you're staying on 0.3.0.

---

## Install

1. **Copy your save** like above.
2. **Unzip `openfpga-Paprium_0.3.0.zip` onto the root of your SD card** and merge with the folders already there. Copy
   the whole `Cores/Koala_Koa.Paprium/` folder, not just the bitstream. The menu lives in `interact.json` and the data
   slots live in `data.json`. If you only drop in a new `paprium.rbf_r`, you'll be stuck with the old menu and the wrong
   slots.
3. **Put the firmware file in the core's own Assets folder.** Take `little_man_firmware.bin` out of
   `Little-Man_Firmware_1.0.zip` and copy it here:

   ```
   /Assets/paprium/Koala_Koa.Paprium/little_man_firmware.bin
   ```

   If there's no `Koala_Koa.Paprium` folder yet, make one. The name has to be exactly `little_man_firmware.bin`.
4. **Put your copy of the game in place**, named exactly this:

   ```
   /Assets/paprium/common/Paprium.md
   ```

   The core boots straight into the game with no file browser, so it only ever loads `Paprium.md` from that folder.
   Any other name won't be found.
5. **Optional: delete the old soundtrack file**, `/Assets/paprium/common/paprium.pcm`. 0.3.0 never touches it. If you
   think you might go back to 0.2.6, keep it, since 0.2.6 needs it for music.

Once you're done, the card should have:

```
/Cores/Koala_Koa.Paprium/                                  the core
/Platforms/paprium.json                                    the platform entry
/Platforms/_images/paprium.bin                             the platform artwork
/Assets/paprium/common/Paprium.md                          your own copy of the game
/Assets/paprium/Koala_Koa.Paprium/little_man_firmware.bin  the cartridge firmware
/Saves/paprium/common/Paprium.sav                          your save (the Pocket keeps it here)
/Saves/paprium/Koala_Koa.Paprium/paprium_sound_cache.bin   the sound cache (the Pocket writes it after the first start)
```

Pop the card in the Pocket. You'll find the core under **Openfpga → Others → Paprium**.

---

## First start

**Give it about 30 seconds.** After the Pocket's loading bar, the screen stays black for about 20 seconds while a bar
fills along the bottom. That's the core unpacking the game's sounds from your copy of the game into the sound cache.
Don't press anything. Then the game starts.

That same first start also **converts a 0.2.x save**, just once. Every save slot that has a game in it gets rewritten in
the cart's own format, in the same spot. It only happens once: if a save is already in the cart's format, it's left
alone. From 0.3.0 on the save file is 8 KB, the same size as the cart's own save chip (0.2.x saves are 4 KB).

**Then quit the core once.** The Pocket only writes the sound cache to the card when you leave the core, either with
Quit in the Pocket's menu or with the power button:

```
/Saves/paprium/Koala_Koa.Paprium/paprium_sound_cache.bin   (1,384,704 bytes)
```

After that, every start loads the cache and takes about **12 to 14 seconds** from the Pocket's library to the first
picture, including about 2 seconds of black while the core checks the cache.

A few things about the sound cache:
- Your Pocket makes it from your own copy of the game. Keep it on your own card and please don't share it, because it
  holds the game's sounds.
- If it's missing or doesn't check out, the core just builds it again, and that start takes as long as the first one.
- It's safe to delete. All it costs you is one slow start.

**If you have no save at all**, the game starts on its first-boot **mini-game**, the same as a brand-new cart does.
That's the cart's own behaviour, not a bug in the core. With **3-Player Mode** on (or Arcade Mode on Multiplayer) the
mini-game only listens to Dock controller 3, just like on a real console with the adapter plugged in, so leave those off
for the first boot. Play or skip the mini-game, then hit **Soft Reset (mini game)** in the core's menu and the game boots
properly.

You only get the mini-game once. The cart records it in its save, and the save lives on the SD card, so no reset or power
cycle brings it back. If you want to see it again (with the language-selection screen), rename your save file. Don't
delete it, it's your progress. Rename it back afterwards and you'll carry on where you left off.

---

## A plain red screen

If the screen goes **plain red**, with no text and no sound, and the game never starts, the core has turned down the
firmware file. Either the file is damaged or it was made for a different core version.

Here's the fix:
1. Copy `little_man_firmware.bin` from the firmware release that goes with your core (for 0.3.0 that's Little-Man
   Firmware 1.0) into `/Assets/paprium/Koala_Koa.Paprium/`, replacing the one that's there.
2. Quit the core from the Pocket's menu and start it again.

If the file is missing or the wrong size, the Pocket itself tells you before the core starts.

The firmware's red screen has no text at all. Don't mix it up with the game's own red "0012" screen. That one shows up on
purpose when you set Arcade Coins to "Inf. Credits (0012)".

---

## The core and the firmware file belong together

I release the core and the firmware file together, and they have to match:

- **0.3.0 takes Little-Man Firmware 1.0.** Every core release says which firmware version it takes.
- **A firmware-only update is just a file swap.** Replace `little_man_firmware.bin` and start the core. Each firmware
  release says which core versions it runs on.
- **A firmware file made for a different core version gets turned down** with the red screen above. Put the matching
  file back and start the core again.
- The file name on the card never changes. You'll find the version in the download's name, inside the file and in the
  release notes.

---

## Going back to 0.2.6

1. Put the 0.2.6 core back (the whole `Cores/Koala_Koa.Paprium/` folder from the 0.2.6 zip).
2. Put back the copy of `Paprium.sav` you made before you installed 0.3.0.
3. 0.2.6 still needs `paprium.pcm` for its music, same as before.

0.2.6 doesn't use `little_man_firmware.bin` or `paprium_sound_cache.bin`. You can leave them on the card.

---

## Core settings

You get to these from the Pocket's own menu while the core is running. Anything marked "Soft Reset" is read when the game
boots, so change it first and then hit **Soft Reset (mini game)**.

| Setting | Notes |
|---|---|
| **Soft Reset (mini game)** | Restarts the console. This is how you get past the mini-game on the first boot |
| **Console Reset** | Resets the console like its own Reset button. During play the game starts over from its NX TERMINAL screen, the status page at the start of the intro |
| **Aspect Ratio** | Original or corrected |
| **Little-Man** | The cheats: Health, Pills, Lives, or any mix. Off by default, takes effect right away. (This isn't the firmware file) |
| **Arcade Mode** | Off (default), On, Multiplayer or Stick Only. Anything but Off plugs a virtual Grand Stick III into controller port 1. On flips the stick's ARCADE switch, so the game turns on its own arcade mode, and Select drops a coin. Multiplayer is On plus the stick's 3 PLAYERS switch, with the third player on Dock controller 3. Stick Only is the stick with every switch off: the normal game, with Select as the stick's Mode button. Soft Reset |
| **Arcade Coins** | 1 Coin 1 Credit, 2 Coins 1 Credit, or Inf. Credits (0012), which stops on the game's red 0012 screen just like the real stick. Only with Arcade Mode On or Multiplayer. Soft Reset |
| **Attract Only** | The Grand Stick III's Attract Only switch. Only with Arcade Mode On or Multiplayer. Soft Reset |
| **Arcade Stage Select**, **Arcade Stage Select 2** | Which stage Arcade Mode starts on, with Arcade Mode On or Multiplayer. Soft Reset |
| **6-Button** | Controllers 1 and 2 turn into six-button pads, and the game reads X, Y, Z and Mode itself (on L, X, R and Select). With Arcade Mode on, port 1 is the stick, which has all its buttons either way. Takes effect right away |
| **3-Player Mode** | Plugs in an EA 4-Way Play so the game's three-player modes work with three Dock controllers. With Arcade Mode on, Dock controller 3 goes into the stick's EXT socket instead. Off by default. Soft Reset |
| **Console** | Mega Drive (default), Genesis, Mega Drive 2, Genesis Model 2, Genesis 3, Nomad, Mega Jet, TeraDrive or Unknown. Sets the region. Soft Reset |
| **Mega CD** | None (default) or one of eight units. With any unit except Unknown CD, the game's CPU MATE partner works. Soft Reset |
| **32X Mode** | Makes the game think a 32X is attached. Soft Reset |


For what each one does, plus CPU MATE, see [Scum! and the console options](../README.md#scum-and-the-console-options)
in the README, and [docs/SCUM.md](SCUM.md) for the deep version.

### Console and Mega CD: change first, then Soft Reset

The game only reads the console, the Mega CD unit and 32X Mode **once, at boot**. So change the setting first,
then hit **Soft Reset (mini game)**. In 0.2.6 the Boom Box once in a while showed the wrong console afterwards, or the
screen stayed black, and a second Soft Reset fixed it. That's tested and fixed in 0.3.0 with Little-Man Firmware 1.0.

**Japan** (Mega Drive, Mega Drive 2, Mega Jet, TeraDrive, Unknown) gets you the Japanese cart's extras, like the song
titles at the start of each level. **USA** (Genesis, Genesis Model 2, Genesis 3, Nomad) doesn't. Both play the game just
fine. A combined Mega CD unit sets its own region: Wondermega and Aiwa CSD-GM1 are Japan, and the CDX is USA.

### 6-Button

Off by default: the pads are three-button pads, and the game plays fully with three buttons.

From 0.3.0, **6-Button** makes the pads real six-button pads, and X, Y, Z and Mode
arrive by the game's own read: on the two controller ports, and with **3-Player Mode**
on (or Arcade Mode set to Multiplayer) behind the EA 4-Way Play, for all three players.
A port or adapter socket with no Pocket controller behind it reads as nothing plugged in.

### The in-game "VM DAC" option

Paprium's own options menu has a **VM DAC** checkbox, "use VM2612 DAC instead of
DT128VALT DAC". It picks between the game's two sound options, YM and
Datenmeister, and in 0.3.0 both work the way the cart's do. Up to 0.2.6 it made no
audible difference here. What the cart's own output circuit does in Datenmeister
mode isn't reproduced: see
[Known differences](../README.md#known-differences-from-the-original-cartridge).

### There is no audio filter setting

Deliberately. It's fixed at **No Filter**. That was decided in 0.2.x, when every
other mode made some of the cart's sound effects inaudible and the core was
fitting at 98%.

The trade-off: a real Mega Drive has a low-pass filter, so this is a little
brighter than original hardware.

---

## Display modes

The core declares every display mode the Pocket offers — CRT Trinitron plus the
various LCD panel emulations — selectable under the Pocket's **Display** menu.

Note there is exactly **one** CRT mode and no BVM mode. Those come from Analogue's
firmware, not from the core, so no amount of core work adds more.

---

## Known issues

There is one maintained list and this is not it: see
[Known issues](../README.md#known-issues) in the README for what is open today, and
[Fixed here](../README.md#fixed-here) for what has been closed since. Everything below
is the per-release history this guide was written alongside, and is kept for that.

(This section used to carry its own copy of the open list, which fell five releases
behind and ended up advertising fixed bugs as open. One list only.)

### Fixed in 0.2.0

- **Elevator shaft: corrupted background tiles**, and the Intercom Complete screen
  after it (open as #8 on the MiSTer port). Two faults in the replacement firmware's
  handshake with the game. The game parks a level payload in cartridge RAM at
  `0x9000` and reads rows of it back for thousands of frames, and the firmware
  unpacked new sprite blocks into scratch at the same address, so the rows came
  back as bands of sprite art; the scratch moved above anything the game addresses.
  Then, visible once the bands were gone: each frame's row request could be read
  before the cartridge had moved its pointer, giving a blank or shifted row; the
  busy flag is now held until the pointer is in place

### Fixed in 0.1.0

- **Sprites drawn behind the scenery, or vanishing** — the rooftop boss fight, the
  elevator, and the subway station. One cause behind all three: sprites were being
  composed at the wrong point in the frame, so they landed after the game's own
  sprite masks instead of before them
- **Destructibles keeping their intact artwork** after being smashed
- Audio and palette work: echo, stereo imaging, the large-enemy death sound,
  one-shot cues, the looping area ambience, the Block 888 doorway palette, and the
  decompressor that corrupted the subway

The full list, with what each bug actually was, is in the
[README](../README.md#fixed-here).

### On the elevator, specifically

The level had **two unrelated faults**, and both are now fixed. The depth problem —
the background enemy scrolling wrongly and the player dropping behind the scenery —
was the sprite ordering bug, fixed in 0.1.0. The corrupted tiles were the firmware's
scratch area sitting on top of a payload the game reads back while the shaft scrolls,
fixed in 0.2.0, with a second, smaller row-timing fault behind it.

0.1.0's text here offered a per-frame streaming limit as the working explanation.
That was a derivation, not a measurement, and it was wrong: the tiles were streamed
in fine and then overwritten in cartridge RAM.

Timing does not fully close on this device — a known property inherited from the
base core, which runs correctly on hardware regardless.

---

## Credits

The credits, with what each project gave this core, are in the README's
[Lineage](../README.md#lineage) and [History](../README.md#history). Licensed under
GPLv3 or later; the notices for the parts under other licences are in
`THIRD_PARTY_NOTICES.md`, in the repository and in the release package.
