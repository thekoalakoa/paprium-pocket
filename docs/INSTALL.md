# Paprium for Analogue Pocket — Installation

A standalone openFPGA core for **Paprium** (WaterMelon, 2020).

This is a single-game core, not a Mega Drive emulator — the general cartridge
hardware is stripped out to make room for Paprium's own. Don't load other ROMs
into it; use a Mega Drive core for those.

**You must supply your own cartridge dump.** None is included, and none will be
linked. WaterMelon have ceased trading and the game is no longer sold, but that
does not put it in the public domain - it is still their work.

---

## What you need

- An Analogue Pocket with **openFPGA** support (firmware 1.1 or later)
- A microSD card, formatted as the Pocket expects
- Your own dump of the Paprium cartridge — 8 MiB, serial `GM T-574120-00`
- Optionally, the music blob (see [Music](#music))

---

## Get the core

Download **`openfpga-Paprium_<version>.zip`** from the
[latest release](https://github.com/thekoalakoa/paprium-pocket/releases/latest)
and unzip it onto the root of your SD card, merging with the folders already
there.

**The core is not in the git repository.** `paprium.rbf_r` is the compiled
bitstream — a build artefact, deliberately not committed. If you cloned the repo
and copied `pkg/pocket/` across, you have the metadata without the core and the
Pocket will not run it. Use the release zip, or build the bitstream yourself
(see the Building section of the README).

---

## Install

The easiest way, which force-copies everything and then prints the menu the card
will actually show:

```bash
./scripts/deploy_to_sd.sh /d          # your card's drive letter
```

Doing it by hand instead, copy these onto the root of the SD card, merging with
the folders already there:

```
/Cores/Koala_Koa.Paprium/     the core itself
/Platforms/paprium.json       the platform entry
/Assets/paprium/common/       where your ROM and music go
```

Then put your cartridge dump in:

```
/Assets/paprium/common/Paprium.md
```

**The name matters now.** The core boots straight into the game instead of opening
a file browser, so it loads exactly `Paprium.md` from that directory. A dump under
any other name will not be found, and the core will sit waiting for a file it
cannot see.

Your save lives at `/Saves/paprium/common/Paprium.sav` and is also a fixed name.
If you are moving a save over from a build that used the file browser, that is
where it goes.

There is no region option in the menu either — this is a single-game core and the
game is Japanese, so the region is fixed to Japan.

Eject the card, put it in the Pocket, and the core appears under
**Openfpga → Others → Paprium**.

> Platform artwork ships with the core and installs to `/Platforms/_images/`.
> Purely cosmetic - the core runs identically without it.

> **Copy the whole `Cores/Koala_Koa.Paprium/` directory, not just the bitstream.**
> The menu lives in `interact.json` and the display modes in `video.json`. Copying
> only `paprium.rbf_r` leaves a stale menu that looks exactly like the update
> failed to take - removed options still listed, new ones missing.

---

## First boot

Paprium starts on a **mini-game**, not the main game. This is the cartridge's own
behaviour, not a fault in the core.

To reach the game: play or skip through the mini-game, then use
**Soft Reset (mini game)** from the core's settings menu. The game boots properly
on the second start.

### Getting the mini-game back

You only see it once. The cartridge records first-boot state in its save, so
after that you go straight to the game - and no amount of resetting or power
cycling brings it back, because the save is on the SD card.

To see it again (and the language-selection screen), move your save aside:

```
/Saves/paprium/common/<your-rom-name>.sav
```

**Rename it, don't delete it** - that file is your game progress. Rename it back
afterwards to carry on where you left off.

---

## Core settings

Reached through the Pocket's own menu while the core is running.

| Setting | Notes |
|---|---|
| **Soft Reset (mini game)** | Restarts the console. This is how you get past the mini-game on first boot |
| **Region (hard restart req'd)** | **Japan** (default) or **Export**. See below |
| **Aspect Ratio** | Original or corrected |

### Region needs a full restart

The game reads the console region **once, at boot**, and a soft reset is not
enough to change it — the core keeps data in memory across a reset. To change
region, **exit the core completely** and relaunch it.

If you change region and nothing seems different, this is why.

**Japan** gives you the Japanese cartridge's extras — song titles at the start of
each level, and other easter eggs. **Export** doesn't. Both play the game fine.

### There is no 6-button option

Removed deliberately. Paprium's own controller read is a 3-button read, so X, Y, Z
and Mode never did anything regardless of the setting - the option only looked like
it worked. Tying it off also frees logic on a core that fits tightly.

The game plays fully with three buttons; that is how it reads the pad.

### The in-game "VM DAC" option

Paprium's own options menu has a **VM DAC** checkbox - "use VM2612 DAC instead of
DT128VALT DAC". It used to produce loud static in this core. **It no longer
does.**

What it does here: nothing audible. The music and effects sound the same either
way.

What it does on a real cartridge: routes Paprium's audio through the Mega Drive's
own 8-bit converter instead of the cartridge's better one, so the game sounds
thinner and more like stock Genesis hardware. Reproducing that needs hardware
this core does not have room for, so the option is inert rather than wrong. The
design is written up in `docs/PORT_PLAN.md` for anyone porting to a larger FPGA.

### There is no audio filter setting

Deliberately. It's fixed at **No Filter**, because every other mode makes some of
the cartridge's own sound effects inaudible. It also freed a useful amount of
logic on a core that was fitting at 98%.

The trade-off: a real Mega Drive has a low-pass filter, so this is a little
brighter than original hardware.

---

## Display modes

The core declares every display mode the Pocket offers — CRT Trinitron plus the
various LCD panel emulations — selectable under the Pocket's **Display** menu.

Note there is exactly **one** CRT mode and no BVM mode. Those come from Analogue's
firmware, not from the core, so no amount of core work adds more.

---

## Music

Paprium's music is generated by a chipset on the cartridge that has never been
dumped, so it cannot be reproduced. Like the EverDrive Pro, this core substitutes
the released soundtrack, streamed from the SD card.

**The core runs fine without it** — you just get no music.

To enable it, place the music blob at:

```
/Assets/paprium/common/paprium.pcm
```

> **The blob format changed.** It is now IMA ADPCM (`PPAD`), about a quarter the
> size of the old raw-PCM blob - 543 MB instead of 2.09 GB. The core checks for
> the `PPAD` marker and **plays nothing at all** if it is missing, rather than
> streaming an old blob as noise. So if music went silent after an update, your
> `paprium.pcm` is the old format. The game itself is unaffected either way.
>
> **Already have the old blob? You do not need your soundtrack again.** It is
> already 48 kHz stereo with a track table, so convert it in place:
>
> ```bash
> python scripts/convert_cdda_to_adpcm.py old_paprium.pcm paprium.pcm
> ```
>
> About 17 minutes for a full blob. Keep the old file until you have heard the
> new one - it cannot be reconstructed from the converted one.

Building it from your own copy of the soundtrack:

Needs [ffmpeg](https://ffmpeg.org/) on `PATH` and your own copy of the released
soundtrack, in any format ffmpeg reads:

```bash
./scripts/build_cdda.sh  ~/Music/Paprium  docs/paprium.cue  cdda/
```

```bash
python scripts/build_cdda_adpcm.py  cdda/  paprium.pcm
```

`docs/paprium.cue` ships with the core. Source files are matched by their leading
two-digit number rather than by title, so a rip with slightly different titles
still works.

Buffering is 0.337 s, four times the old raw path, because a compressed ring
holds four times as much audio in the same block RAM. If music used to drop out
occasionally, that is why it no longer does.

Ten of the game's music slots have no audio at all — the cartridge itself has a
null pointer for each of them, so those scenes are correctly silent. That's not a
missing file.

---

## Known issues

Honest list. All of these predate this port and are present on other Paprium
setups running the same replacement firmware.

| Issue | Status |
|---|---|
| Elevator level: residual glitching | Characterised, not fixable here - see below |
| Boss fight: player sprite drops behind the background | Under investigation |
| Occasional single-pixel flicker in the intro | Cosmetic, self-corrects |

Fixed since the first release: sprite attribute and palette corruption at the
doorway and in the cell room, the DMA overrun that was writing over the sprite
and hscroll tables, and the wrong sound effect on large enemy deaths.

The elevator is **fill-bound, not a bug in this port**: the cartridge firmware
budgets 10-16 blocks per frame from a constant in the game's own ROM, and when a
block misses its deadline the renderer falls back to re-showing the previous
animation frame. Uncapping it corrupts video instead. It is better than it was
and it is not going to be perfect.

Timing does not fully close on this device — a known property inherited from the
base core, which runs correctly on hardware regardless.

---

## What this is not

Not a faithful reproduction of the cartridge. Paprium's DATENMEISTER chipset —
the part that decompresses graphics and generates the music — has never been
dumped. This takes the same approach as the EverDrive Pro: it runs krikzz's
`mega-ppm` replacement MCU firmware and substitutes the soundtrack.

Expect it to play well, not to be cycle-accurate.

---

## Credits

| | |
|---|---|
| Nuked-MD-FPGA | nukeykt |
| MegaDrive_MiSTer | MiSTer-devel |
| openFPGA-MegaDrive (Pocket port) | drizzt |
| Paprium_MegaDrive_MiSTer | MisterPezz82 |
| mega-ppm firmware | krikzz |
| Pocket port | Koala_Koa |

Licensed under GPLv3.
