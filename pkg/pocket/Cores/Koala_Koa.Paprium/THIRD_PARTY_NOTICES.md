# Third-party notices

This core is GPLv3-or-later; see [LICENSE](LICENSE). Some of what it's built from, and some of what's in the release, is
under other licences that ask for their copyright notice and licence text to go along with every binary
redistribution. So here they are. This file lives in the repository and in the release zip.

Copyright (C) 2026 Marsupial Solutions LLC, for the changes made in this core's repository and for the cartridge
firmware; each component below keeps its own copyright.

Starting with 0.3.0, the cart's chip runs our own firmware, Little-Man Firmware. Our team wrote it from our own study of
how the cart behaves. Its source is in this repository's `firmware/` folder, published with the 0.3.0 release, and it's
GPL-3.0-or-later. Its own `firmware/THIRD_PARTY_NOTICES.md` lists what it carries from other people. The firmware rows
below repeat that list, because the firmware ships with this core as its own file, `little_man_firmware.bin`, which also
holds our MegaWire code. The file isn't signed and isn't encrypted.

## Where each one ships

| Component | Licence | Shipped in |
|---|---|---|
| NEORV32 processor (Stephan Nolting), the RTL in `rtl/PAPRIUM/risc-v/` | BSD-3-Clause | the bitstream `paprium.rbf_r` (synthesised as the cart's chip); the sources in the repository |
| NEORV32 linker script, as carried in mega-ppm's `mcu/lib/` | BSD-3-Clause, with the Free Software Foundation notice the script carries | the firmware's memory layout is linked with scripts based on it (in `firmware/board/pocket/link/`); `scripts/firmware/paprium_mcu.ld`, the 0.2.x script, is based on it too. Up to 0.2.6 the firmware also linked NEORV32's runtime (`crt0.S` and the `neorv32_*` library); 0.3.0 doesn't |
| mega-ppm (krikzz) at commit `84be6bd`: the FPGA sources that `rtl/PAPRIUM/fpgio.sv`, `mcu_core.sv`, `memory.sv`, `ramdp_io.sv`, `structs.sv`, `audio_sfx.sv` and `audio_clock.sv` are based on, and the replacement cartridge MCU firmware | BSD-3-Clause for krikzz's code (our changes to it: GPLv3-or-later, see below) | the cartridge logic synthesised into the bitstream `paprium.rbf_r` (`fpgio.sv`, `mcu_core.sv`, `memory.sv`, `ramdp_io.sv`, `structs.sv`; `audio_sfx.sv` and `audio_clock.sv` are in the repository but aren't built into 0.3.0's bitstream); the firmware of 0.1 to 0.2.6, built from mega-ppm with `patches/mega-ppm-pocket.patch`, which stays in the repository. The 0.3.0 firmware file still carries code moved over from the 0.2.6 firmware (`firmware/interim/s1/bodies_s1.c`), and `firmware/` keeps the 0.2.6 build's other source files based on mega-ppm; `firmware/THIRD_PARTY_NOTICES.md` lists them. |
| WavPack "tiny decoder" (WavPack 4.0, Conifer Software), as the Rockbox project carries it, kept in `firmware/core/wavpack/` | BSD (Conifer Software's licence) | the firmware file `little_man_firmware.bin`: the work-RAM boot code that unpacks the game's sound bank on the first start |
| newlib, the C library of the xPack riscv-none-elf GCC 15.2.0-1 toolchain (newlib 4.5.0): `memcpy` and `memset` only | FreeBSD License (BSD-2-Clause) | the firmware file `little_man_firmware.bin` |
| agg23's openFPGA modules (Adam Gastineau): `target/pocket/data_loader.sv`, `data_unloader.sv`, `sound_i2s.sv`, `sync_fifo.sv` | MIT | the bitstream `paprium.rbf_r`; the sources in the repository |
| agg23's scanline filler (Adam Gastineau), from openfpga-SNES: `rtl/scanline_filler.sv` | no licence line in the file (see below); our changes GPL-3.0-or-later | the bitstream `paprium.rbf_r`; the source in the repository |
| OpenGateware's audio modules (Marcus Andrade), as agg23's openFPGA cores carry them: `target/pocket/audio/audio_mixer.sv`, `filters/filter_loader.sv`, `filters/filters_rom.sv` | MIT | the bitstream `paprium.rbf_r`; the sources in the repository |
| Gregory Hogan (Soltan_G42)'s audio filters, as MegaDrive_MiSTer carries them: `rtl/upstream/genesis_lpf.v`, `audio_iir_filter.v` | MIT | the bitstream `paprium.rbf_r`; the sources in the repository |
| The Analogue Pocket Framework (Analogue): `platform/pocket/apf_top.v`, `common.v`, `io_bridge_peripheral.v`, `io_pad_controller.v`; and `target/pocket/core_bridge_cmd.v`, from Analogue's core template | the APF Software License Agreement, kept in the four platform files' headers; `core_bridge_cmd.v` names Analogue and carries no licence text | the bitstream `paprium.rbf_r`; the sources in the repository |

agg23's scanline filler, `rtl/scanline_filler.sv`, names agg23's openfpga-SNES as where it came from and doesn't have a
licence line of its own, so there's no notice text to copy here for it. It's credited to agg23 here and in the README's
Lineage, and our changes to it are GPL-3.0-or-later.

The agreement in Analogue's platform files says that where the MIT License or the GNU General Public License applies and
its terms differ, those licences prevail. The Quartus-generated IP files (`platform/pocket/mf_*.v`, the PLLs in
`target/pocket/`) carry Intel's terms in their headers.

The GPL-licensed parts (Nuked-MD-FPGA, FX68K, MegaDrive_MiSTer, the openFPGA port and the Paprium cartridge RTL, except
the mega-ppm code inside it) are covered by [LICENSE](LICENSE) and the licence files kept with their sources
(`rtl/upstream/nuked-md/LICENSE`, `rtl/fx68k/LICENSE`). That includes `rtl/sdram.sv`, Sorgelig's SDRAM controller from
MegaDrive_MiSTer (GPL-3.0-or-later, in its header), with MisterPezz82's port-2 counter from their Paprium MiSTer core
(V.04), which lets the cart's chip win a memory turn when it's waited too long. It also includes OpenGateware's
GPL-3.0-or-later audio filters (`target/pocket/audio/filters/audio_filters.sv`, `audio_mix.sv`, `dc_blocker.sv`,
`iir_filter.sv`, `iir_filter_tap.sv`), the cartridge firmware in `firmware/`, and the firmware file in the release (the
firmware plus our MegaWire code), which is built from that same source.

Our own changes to mega-ppm (the code we added in `patches/mega-ppm-pocket.patch` and our changes to the cartridge files
above) are GPLv3-or-later, like the rest of this core. So the bitstream carries both: krikzz's BSD-3-Clause code in the
cartridge logic, with its notice below, and our GPLv3 code. The firmware file carries both too, wherever it links code
based on mega-ppm (see the mega-ppm row above).

The CPU MATE brain, which rides inside the firmware file, is a reverse-engineered emulation of the game's CPU partner.
It isn't a third-party open-source component, and none of these notices covers it.

## Credited for their history of use

Most of these aren't in the 0.3.0 core anymore, though their files may still be in the repository.

- **mega-ppm's firmware** (krikzz) ran the cart MCU from 0.1 through 0.2.6. From 0.3.0 the cart's chip runs our own
  firmware; whatever it still carries from mega-ppm is in the mega-ppm row above. krikzz's first-level door fix went
  away with the 0.2.x sprite rules.
- **Genesis Plus GX** (<https://github.com/ekeeke/Genesis-Plus-GX>, Eke-Eke and contributors; its Paprium support,
  `cart_hw/paprium.h`, is headed Project Little Man): the 0.2.x firmware's LZO decoder was ported from its Paprium
  support (`paprium.h`), and `firmware/legacy/026/mame.c` keeps that port as source for the 0.2.6 build. Genesis Plus GX
  is also an emulator our tests use, and `tools/da-twin/da_twin.c` carries its decompressors for a test comparison.
- **TheHpman's MAME Paprium work**: mega-ppm's `mame.c` says it's based on TheHpman's `rom.cpp`, so the firmware in 0.1
  through 0.2.6 was built on it.
- **MisterPezz82's SFX engine and MD+ adapter** (`rtl/PAPRIUM/audio_sfx.sv` with krikzz's `audio_clock.sv`,
  `paprium_mdp_adapter.sv`) and the CD-audio player ported from his `mdp_audio.sv` (`paprium_cdda_play.sv`): that was the
  0.2.x sound path. In 0.3.0 the sound works the way the original cart's does.
- **adroxe's arcade unlock and Mode-button credit** (Paprium-Arcade): that was 0.2.6's Arcade Mode. In 0.3.0 Arcade Mode
  is a virtual Grand Stick III, and its ARCADE switch turns on the game's own arcade mode.
- **MisterPezz82's pad hook**, which injected X, Y, Z and Mode in 0.2.6.
- **The MiSTer Paprium team's detection stubs** for 32X and Mega CD: `rtl/PAPRIUM/paprium_addons.sv` grew out of them,
  and it's still in the core.

---

## mega-ppm

<https://github.com/krikzz/mega-ppm>

```
BSD 3-Clause License

Copyright (c) 2025, krikzz

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## NEORV32

<https://github.com/stnolting/neorv32> (processor version 1.4.8.1, as carried in the Paprium cartridge RTL. The same
notice heads every file in `rtl/PAPRIUM/risc-v/` except the two generated memory images,
`neorv32_application_image.vhd` and `neorv32_bootloader_image.vhd`, which name NEORV32 and Stephan Nolting in one line.
It also heads the runtime files `firmware/board/pocket/neorv32/` keeps for the 0.2.6 build.)

```
BSD 3-Clause License

Copyright (c) 2020, Stephan Nolting. All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are
permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this list of
   conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice, this list of
   conditions and the following disclaimer in the documentation and/or other materials
   provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors may be used to
   endorse or promote products derived from this software without specific prior written
   permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS
OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED
OF THE POSSIBILITY OF SUCH DAMAGE.
```

NEORV32's own linker script, kept as `firmware/board/pocket/neorv32/common/neorv32.ld` for the 0.2.6 build, the copy of
it adapted as `scripts/firmware/paprium_mcu.ld`, and the three linker scripts in `firmware/board/pocket/link/` made from
it (`pocket88k.ld`, `pocket72k.ld`, `legacy54k.ld`) also carry this notice, kept in each file:

```
Copyright (C) 2014-2020 Free Software Foundation, Inc.
Copying and distribution of this script, with or without modification,
are permitted in any medium without royalty provided the copyright
notice and this notice are preserved.
```

## WavPack

<https://github.com/dbry/WavPack> (the "tiny decoder" of WavPack 4.0, 2004, as the Rockbox project carries it. Its files
name the BSD license, and this is the license text Conifer Software shipped with that decoder, the same text as
`firmware/core/wavpack/LICENSE.txt`.)

```
               Copyright (c) 1998 - 2004 Conifer Software
                          All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

    * Redistributions of source code must retain the above copyright notice,
      this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright notice,
      this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of Conifer Software nor the names of its contributors
      may be used to endorse or promote products derived from this software
      without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE REGENTS OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## newlib (memcpy, memset)

The firmware takes two routines, `memcpy` and `memset`, from the C library of the xPack riscv-none-elf GCC 15.2.0-1
toolchain (newlib 4.5.0). newlib's licence file lists this notice for its RISC-V code:

```
Copyright (c) 2017  SiFive Inc. All rights reserved.

This copyrighted material is made available to anyone wishing to use,
modify, copy, or redistribute it subject to the terms and conditions
of the FreeBSD License.   This program is distributed in the hope that
it will be useful, but WITHOUT ANY WARRANTY expressed or implied,
including the implied warranties of MERCHANTABILITY or FITNESS FOR
A PARTICULAR PURPOSE.  A copy of this license is available at
http://www.opensource.org/licenses.
```

The FreeBSD License is the BSD 2-Clause License:

```
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

The full newlib licence file comes with the toolchain
(`distro-info/licenses/newlib-4.5.0.20241231/COPYING.NEWLIB` in the xPack archive).


## agg23's openFPGA modules

<https://github.com/agg23> (vendored from openfpga-NES; the same notice heads each file)

```
MIT License

Copyright (c) 2022 Adam Gastineau

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## OpenGateware's audio modules

OpenGateware (`SPDX-FileCopyrightText: (c) 2023, OpenGateware authors and contributors`; the same notice heads each of
the three MIT files)

```
Copyright (c) 2023, Marcus Andrade <marcus@opengateware.org>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Gregory Hogan's audio filters

(`genesis_lpf.v` and `audio_iir_filter.v`, as MegaDrive_MiSTer carries them; the same notice heads both files)

```
MIT License

Copyright (c) 2019 Gregory Hogan (Soltan_G42)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

Paprium is a trademark of its owners. This project is not affiliated with WaterMelon. It is a free, non-commercial
project: it is not sold, and the game is not included. Little-Man Firmware (trademark pending) is Marsupial Solutions
LLC's name for the cartridge firmware.
