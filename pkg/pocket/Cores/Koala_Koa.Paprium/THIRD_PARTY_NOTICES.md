# Third-party notices

This core is GPLv3-or-later; see [LICENSE](LICENSE). Some of what it is built from, and
what its release contains, is under permissive licences whose terms ask that their
copyright notice and licence text go with every binary redistribution. Those notices are
reproduced here. This file is in the repository and in the release package.

## Where each one ships

| Component | Licence | Shipped in |
|---|---|---|
| NEORV32 processor (Stephan Nolting), the RTL in `rtl/PAPRIUM/risc-v/` | BSD-3-Clause | the bitstream `paprium.rbf_r` (synthesised as the cartridge MCU); the sources in the repository |
| NEORV32 software runtime: `crt0.S`, the `neorv32_*` library and the linker script, as carried in mega-ppm's `mcu/lib/` | BSD-3-Clause | linked into the MCU firmware, which is inside the bitstream's memory images; `scripts/firmware/paprium_mcu.ld` is derived from the linker script |
| mega-ppm (krikzz), the replacement cartridge MCU firmware at commit `84be6bd` | BSD-3-Clause | the MCU firmware inside the bitstream, built from mega-ppm with `patches/mega-ppm-pocket.patch`; the firmware images `rtl/PAPRIUM/mcu.txt`, `mcu_ext.txt`, `wram_hi.txt` and `wram_lo.txt` in the repository |
| newlib, the toolchain's C library (xPack GCC 15.2.0, newlib 4.5.0): `memcpy` and `memset` only | see below | linked into the MCU firmware |
| libgcc (GCC 15.2.0): soft-float and count-leading-zeros helpers | GPLv3 with the GCC Runtime Library Exception | linked into the MCU firmware; the exception places no condition on the result |

The GPL-licensed parts (Nuked-MD-FPGA, FX68K, MegaDrive_MiSTer, the openFPGA port and the
Paprium cartridge RTL) are covered by [LICENSE](LICENSE) and the licence files kept with
their sources (`rtl/upstream/nuked-md/LICENSE`, `rtl/fx68k/LICENSE`).

The CPU MATE brain, a separate download next to each release, is made from the game's own
code. It is not a third-party open-source component and none of these notices covers it.

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

<https://github.com/stnolting/neorv32> (processor version 1.4.8.1, as carried in the Paprium
cartridge RTL; the same notice heads every file in `rtl/PAPRIUM/risc-v/` and the runtime)

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

The linker script NEORV32 adapted, and `scripts/firmware/paprium_mcu.ld` after it, also
carry this notice, kept in the file:

```
Copyright (C) 2014-2020 Free Software Foundation, Inc.
Copying and distribution of this script, with or without modification,
are permitted in any medium without royalty provided the copyright
notice and this notice are preserved.
```

## newlib (memcpy, memset)

The firmware takes two routines, `memcpy` and `memset`, from the C library of the xPack
riscv-none-elf GCC 15.2.0 toolchain (newlib 4.5.0). newlib's licence file lists this notice
for its RISC-V code:

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

The full newlib licence file is distributed with the toolchain
(`distro-info/licenses/newlib-4.5.0.20241231/COPYING.NEWLIB` in the xPack archive).
