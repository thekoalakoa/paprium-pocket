# Mega Drive for Analogue Pocket

[![Latest Release](https://img.shields.io/github/v/tag/drizzt/openFPGA-MegaDrive?label=latest)](https://github.com/drizzt/openFPGA-MegaDrive/releases/latest) [![Downloads](https://img.shields.io/github/downloads/drizzt/openFPGA-MegaDrive/total)](https://github.com/drizzt/openFPGA-MegaDrive/releases) [![Platform](https://img.shields.io/badge/platform-Analogue%20Pocket-blue)](https://openfpga-library.github.io/analogue-pocket/)

LLM assisted port of [Nuked-MD-FPGA](https://github.com/nukeykt/Nuked-MD-FPGA),
via [MegaDrive_MiSTer](https://github.com/MiSTer-devel/MegaDrive_MiSTer). The
console is a gate-level model of the real silicon, not a behavioural rewrite.

Please report any issues to this repo, not to the MiSTer or Nuked-MD ones. Most
likely a problem is a result of this port rather than the original core.

> [!WARNING]
>
> Beta core
>
> Games boot and play, but some may still glitch or behave oddly. Please report
> anything you run into.

## Installation

### Easy mode

Use one of the openFPGA updater tools, such as
[Pupdate](https://github.com/mattpannella/pupdate). They download and install
cores onto the Pocket for you. Go donate to them if you can.

### Manual mode

Download the [latest release](https://github.com/drizzt/openFPGA-MegaDrive/releases/latest)
zip and copy the `Assets`, `Cores` and `Platforms` folders to the root of your SD
card. Note that Finder on macOS *replaces* folders rather than merging them like
Windows does, so on a Mac merge the contents by hand.

Platform artwork is not bundled. If your SD card does not already have images for
this platform, grab them from
[dyreschlock/pocket-platform-images](https://github.com/dyreschlock/pocket-platform-images).

## Usage

ROMs go in `/Assets/genesis/common`. `.md`, `.bin` and `.gen` files up to 32 MB
are supported.

## Features

### Cartridges

Plain ROMs, SSF2 bank switching (Super Street Fighter 2 and most pirate carts),
the Realtec and SF-001/002/004 mappers, the SVP chip (Virtua Racing), and the
fixed-value protection reads a handful of unlicensed carts expect.

### Saves

Cartridges with battery-backed SRAM or a 24CXX serial EEPROM save to a `.sav`
file. Anything whose header claims save memory gets one, so a few homebrew and
test ROMs end up with a `.sav` they never use.

> [!WARNING]
>
> Back up `/Saves/genesis` before switching between Genesis cores
>
> Every Genesis core on the Pocket writes the same save file for a given ROM, and
> the Pocket gives a core no way to keep its saves to itself. The cores do not
> agree on the format, so a save made in one is not readable by another, and
> playing a game here can overwrite a save made elsewhere, or the other way
> round. Copy `/Saves/genesis` off your card before you switch cores, and keep
> one core per game.

### Region

NTSC or PAL, chosen automatically from the cartridge header. The Region setting
picks Japanese or export machine behaviour; set it to Auto unless a game needs
otherwise. A cart with a blank or mis-stamped header field runs as NTSC.

### Audio

FM and PSG straight out of the gate-level sound chips. **Audio Filter** picks
between the Model 1 and Model 2 low-pass characteristics, a minimal filter, or
none. **FM Chip** switches between the YM2612's ladder-effect DAC and the
cleaner YM3438.

### Video

**CRAM Dots** enables the coloured dot the real VDP puts in the left column when
a game writes palette memory mid-line. Some games rely on it, most look better
without it.

**Composite Blend** blends adjacent pixels horizontally, like a composite video
cable. Effects drawn as thin stripes, such as Sonic's waterfalls, become
translucent instead of striped.

**Aspect Ratio** picks how wide the picture is drawn. **Original** matches a
period television. **Corrected** stretches the wider of the two Mega Drive
screen modes so its pixels come out square, which suits games that were drawn
on a computer monitor. Games in the narrower mode look the same either way.

### Controls

| Pocket | Mega Drive |
|---|---|
| D-pad | D-pad |
| B | B |
| A | C |
| Y | A |
| X | Y |
| L | X |
| R | Z |
| Start | Start |
| Select | Mode |

**6 Button Pad** can be turned off for the handful of games that misread a
6-button controller. A Mega Drive pad has no reset button, so use **Reset Core**
in the Core Settings menu.

### Pause

The game pauses while the Pocket menu is open.

## Not included

- Savestates and sleep, so leaving the core loses your progress
- Master System backward compatibility
- MD+ and CDDA, which need hardware the Pocket does not have
- Pier Solar and Sega Channel carts
- J-Cart, so the Codemasters carts save but only take two controllers
- Cheats, multitaps, lightguns, keyboard and mouse

## License

GPLv3, see [LICENSE](LICENSE). Individual files keep the licenses noted in their
own headers: Nuked-MD-FPGA and most of the MegaDrive_MiSTer RTL are
GPLv2-or-later, the audio filter chain is a mix of MIT and GPLv3-or-later,
agg23's modules are MIT, and Analogue's APF shell is under the APF Software
License Agreement, whose terms defer to the GPL or MIT wherever the two conflict.

Thanks to **nukeykt** and the Nuked-MD-FPGA contributors for the console model,
**Alexey Melnikov (Sorgelig)** and the MegaDrive_MiSTer contributors for the
MiSTer core, and **[agg23](https://github.com/agg23)** for the openFPGA
integration work every Pocket port of a MiSTer core builds on.
