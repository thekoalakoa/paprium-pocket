#!/usr/bin/env bash
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
# Build the Paprium MCU firmware for 0.3.0 from its stage 1 on (0.3.0 was made in numbered stages: 1 = the new firmware's
# own start-up, scheduler, dispatcher and board layer, 5 = our own song engine and synth): the firmware tree (the firmware/ folder of this repository), built by its own
# tools/fwbuild.py (the stage-1 source set, the pocket72k layout), split into the six block-RAM init files the stage-1 RTL reads:
#
#   rtl/PAPRIUM/mcu.txt       IROM rom0, 32 KB, 8,192 words           ($readmemh in rtl/PAPRIUM/mcu_core.sv)
#   rtl/PAPRIUM/mcu_ext.txt   IROM extension: test build 5 on (--s5) 56 KB, 14,336 words (mcu_core.sv EXT_KB = 56, the
#                             88 KB IROM core_top's PAPRIUM_IROM_KB names); test builds 4-4b 40 KB, 10,240 words (EXT_KB = 40)
#   rtl/PAPRIUM/wram_b0.txt .. wram_b3.txt   WRAM byte lanes 0-3 = MCU bytes 4k .. 4k + 3, 12,288 lines each ($readmemh in rtl/PAPRIUM/memory.sv)
#   (test build 4: the WRAM is tightly coupled to the NEORV32 as four 8-bit lanes; before it, wram_hi.txt / wram_lo.txt
#   held the even / odd bytes. The firmware build writes both forms from one byte array; this script installs the lanes)
#
# Usage:
#   ./scripts/build_mcu.sh [--release | --test] [--s5] [--brain DIR] [--wram-blob] [--fw DIR] [--gcc-bin DIR]
#                          [--out DIR] [--no-install]
#
#   --release       (default) the shipping firmware: debug aids off (-DPPM_RELEASE=1)
#   --test          the test firmware: the TEST counters, the debug save (.sav bytes 0x1000-0x1FFF) and the snapshots on
#   --s5            (firmware trees from test build 5 on) the stage-5 images: the firmware tree's fwbuild variants
#                   s5release / s5test (and their _nobrain twins), linked at its pocket88k layout (IROM 88 KB: rom0 32 KB
#                   + a 56 KB extension), split with --ext-kb 56. Without it: the stage-1 variants release / test at
#                   pocket72k (72 KB). Installing refuses an image whose IROM size is not the RTL's (core_top.sv
#                   PAPRIUM_IROM_KB: 88 from test build 5)
#   --brain DIR     a folder holding the CPU MATE brain from the release download: brain.bin, cf.bin and rodata.bin
#                   (md5s checked: the stage-1 brain, brain.bin b9a76592). Without it the firmware is built WITHOUT
#                   the brain: zeros of the same sizes in its place, every other byte the same; the glue finds no
#                   brain and switches itself off, and the CPU MATE gets no input from the cart.
#   --wram-blob     (firmware trees from test build 4b on) the firmware build's WRAM boot overlay goes into the WRAM lanes where
#                   the firmware build placed it: its ovl.img (the 'POV1' header + the first-boot unpack of the cart's
#                   sound bank) at the tree's fwbuild.json s1.overlay base (0x80006C00, room 16 KB), by mkimage.py
#                   --wram-blob; then it is read back from the lanes as the firmware's IROM stub checks it
#                   (scripts/firmware/ovlcheck.py: magic, length, entry, CRC-32, = ovl.img, the rest of its room zero),
#                   and again from rtl/PAPRIUM/ after the install. Needed when the firmware build made an overlay (lanes
#                   without it boot with no unpack: no sound bank); refused when it made none.
#   --fw DIR        the firmware tree to build (default: $PAPRIUM_FW, then the firmware/ folder of this repository)
#   --gcc-bin DIR   the bin folder of the xPack riscv-none-elf GCC 15.2.0 toolchain (default: $RISCV_GCC_BIN,
#                   then riscv-none-elf-gcc on PATH)
#   --out DIR       build folder (default: build_output/mcu-<variant>[-nobrain], git-ignored)
#   --no-install    do not copy the images into rtl/PAPRIUM/ (the normal use on this tree: see below)
#   --replace-stub  install even though rtl/PAPRIUM/ holds the boot stub (a test bitstream with the firmware built in)
#
# From 0.3.0 the firmware is not built into the Pocket bitstream: the committed rtl/PAPRIUM images are the boot stub
# (the firmware tree's board/pocket/fafrium/fafrium_stub.S, written there by its tools/mkfafrium.py stub), which loads
# the firmware from its own file, little_man_firmware.bin (Little-Man Firmware), at power-on; the firmware tree's
# tools/mkfafrium.py make builds that file from a firmware build. This script still builds a firmware's images and
# checks them both ways (below); run it with --no-install. Installing them would replace the stub, and a bitstream
# built from those images runs the firmware built in and never loads the file, so the script refuses to install over
# the stub unless --replace-stub is given (for a test bitstream; never commit such images). The brain's bytes are
# never in git either way. See docs/firmware/README.md.
#
# A firmware with the MegaWire code (Little-Man Firmware 1.0 has it) links it for the Pocket SRAM (the layout's "sram"
# range, 0x08000000-0x0800FFFF at pocket88k): both splits leave that range out of the block-RAM images and write it
# as sram.bin, which must agree too. sram.bin is not a bitstream image: it travels in the firmware file.
#
# The images are made twice and must agree: by the firmware tree's build (tools/fwbuild.py, tools/mkimage.py) and by
# this repository's scripts/firmware/mkimage.py from the same ELF. The four lanes must also hold exactly the bytes of the
# firmware build's wram_hi / wram_lo. A firmware tree from before the lanes (before test build 4) writes only
# the pair: its lanes then come from this repository's mkimage.py, checked against that pair. With --wram-blob both
# place the same overlay (their image.json wram_blobs agree: address, bytes, md5 = the build's ovl.img).
#
# Needs: bash, python 3, git (for the firmware tree's commit id only), and the toolchain above. Git Bash on Windows works.
set -euo pipefail
export LC_ALL=C

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FW_DIR_TOOLS="$SCRIPT_DIR/firmware"
PREFIX=riscv-none-elf

# the committed images (RELEASE, no brain) and the other three builds, as written by each firmware below:
# md5s of mcu.txt mcu_ext.txt wram_b0.txt wram_b1.txt wram_b2.txt wram_b3.txt (CRLF lines). A test build is a build
# B Jam tested on his own Pocket. Test build 5 (the stage-5 music firmware, test
# build 4b's first-boot unpack with the synth's output curve in the WRAM boot overlay, ovl.img e4f2cb41 in all four),
# built with --s5 --wram-blob (the pocket88k layout, IROM 88 KB).
# Test build S3c (the refit with the Console Reset: the integer stepping of
# command F5 + the Console Reset's warm vector page): the lists below. Test build 5's: RELEASE no brain ae8babb8 4c4de530 6f075d7a 0f4e1970 58ee8b1c aeff1416, TEST no brain
# 13ab4752 a1861acf e41464c0 57f4b8cf 4a25e9d3 cc6ccbba (docs/firmware/README.md keeps all four of its builds).
# Little-Man Firmware 1.0 (the firmware of the conversion to the firmware file, built from the firmware/ folder; the cart's MegaWire
# code in sram.bin, d4ec8522 for RELEASE and f7cce49f for TEST, the same with and without the brain): its four builds.
KNOWNLMF_release_nobrain="78fe35805c430a8c0edef366689eb683 b3c2df8ebffff632ba0f451df5de137e 6f075d7a52ad044a192719d962e1576a b8a2a015f9789eda8b062358e8fa0b14 d483a45ceae03b7d6a2aeea18a8aab67 5d2149aa029f4cadd90f388171bac026"
KNOWNLMF_test_nobrain="e2a3f3b6de9289b75d9261442d14ad26 fdc8a3cb04efe6bea2006f5dc118c5b6 2a14e6c676c1038bf9b8f779405ffb9b a83a09be2d48fa895d38f8f01730c84b 37d3d711675634a254b4ae8ea59a02ae 663120440a2b50a0352ad49be1f00810"
KNOWNLMF_release_brain="a1c7d4a0a063aac80c10f3e2084ca9c0 e136e791f9740f25e3a0e0c188c717a0 f8594eff000552dd384065bad6b0b56a 04b9d15ab0ffef7ddc102d48bcb3436a 5e88be5b61b6c178ae1f0ebc8131bf15 74e0c0f1222ee427ff360a0f5a2016a3"
KNOWNLMF_test_brain="5afa74c31e830eb9b5770e53f4102921 7961943847dc8bc14abc0a8db3897fc9 50725b7516914e53fa5d13fbe5b4209e 32bb52446b66d4fa02245b0b7db96915 8dffbbd7627ab007b9d3ee8172b22af6 9a2ee8beac52ff89a8a8bfe8c3e91d7e"
KNOWN_release_nobrain="fea7467cc2354e9f56e23d9cb494cffb 936aef3b7704e845ad68b5e9b9c5eee6 6f075d7a52ad044a192719d962e1576a fab4302ea503f0381474491cd126d76f ec44ab2509940bdaccde06896d4b2293 50221f93db7fdc97ee264fd158adf296"
KNOWN_test_nobrain="6270931debbb212d4f1d0cfcc02628a4 ece789cc3966c7a54d40cd701b25dacb e41464c056c2dc71e67cc86d5319b2b1 c7a9d95b7098dc6a9a3bb4323b774f6f 9ba5709dfa4afe80c3c10f1f832f7020 86ac7a76ce90937254e206966a90c041"
KNOWN_release_brain="2d7b3dbf986f51a90cace2a4ef652706 6e23bacb74fbd15ec9a456ee72332c02 f8594eff000552dd384065bad6b0b56a 7217e52bf2b12ba0e4a8b5a50d78e17d cf3ce6f2f69d21fda1f130f5c152e61e 2f913f19f1652121b66fcd3428480bc1"
KNOWN_test_brain="1989bd5d2329c8dde99a676131a09108 181df5998640ea7d25cfb8c5dd937ab4 38a418d2bbcf7c3a8a87281b16037844 279701b5c17dc9adacacd245047e97bd 2474df73c163cd7cd78c63d72ed3d0c3 feef6ca2e99083ec854a0af942a7afc5"
# test build 4a's four builds (test build 4's firmware + the TEST image's sound-cache probe for
# MCU interface v1.3; the pocket72k layout, no overlay; its RELEASE images are test build 4's, byte
# for byte), committed here until test build 5; the even / odd pair of its RELEASE no-brain build: 8b99de32 / 17ad00f4.
KNOWN4A_release_nobrain="096fe23b01429976358ffbb99f803dc6 31444366db56ea491bf533483ccebe93 d0242d2592c7ac81b6df3971685edee9 d93120aec3166ff54453b14ff4bfa55f 4b1d709aaa80c740dc93e33195c24d94 d2a1706a997a5ed1f677350814072a3e"
KNOWN4A_test_nobrain="4e5145a154abf5b7e2f337f06b2374b6 3b871768e232ca48c61399ff1ef462c0 22f9bd9fef5b72d2a3625f01a8c61551 4b95f57e93054f0a7bb3508a3ca5f1ea 4e6074b90e206bfd5f53d94fe2d2eb62 83aa94ca65ad8ecc8d263c6fb2bc7a85"
KNOWN4A_release_brain="f5c58628b2ed3b11448059a5109d52da 250091e52f4995a98dc3e5b9bd7100c0 b9925ba12be411ddf3e3f6b6136137fa 5e289070d55c7fedfd63eccbe499d17c de53c0b35db446fc41774788a8a50686 01e4db7aeb5b54eb301c900ddd7c4df1"
KNOWN4A_test_brain="7d302a0651e0b92fe4de2b9fb734c654 5df79079cc5480dae3319d33577791f5 86deb30ff22dbc8702f9f61e81093526 247d2f636f6385c2acfdf9a97d5bf5c7 ddf41c307d0cca6aec160cbac4febc90 023b8c6f675939ac480525325a203cca"
# test build 4b's four builds (the first-boot unpack in the WRAM boot overlay, ovl.img e09e3062
# in all four), built with --wram-blob; not committed here. The same six files' md5s (= the firmware build's lanes).
KNOWN4B_release_nobrain="5b9e10895711710d706d8dce844da412 3d5beae19572242af5b7c44246304ec7 75fe689d7574a650e12ff7ee6027523d f1806226434be93b47c15bede3b7f3e1 bb68b047cb2823afec52864cb034d5fa 36061f9d17d2616432ba062c305688a2"
KNOWN4B_test_nobrain="00a68ec915d7786c273a50d14a71c51f 4aa6b5ea00f7d8d835b19276dc0e88b5 a51ab309e15044e5c7da9848bd7e7440 fe4e9527ef0cde475e2baa5708f09941 906ab0d512fef78b064420be8fced157 b5bc8c396ca24798c43e518b32411147"
KNOWN4B_release_brain="7719938993881357e63d1869bf1334eb 81110d61199bd5a653f296d4a9fc5882 059f517fddb761996b1f5a027ff8bf8a 883cad5506e350a96f425ec2252c7042 192d87d367309907c5d667cc1e4e910c 365103588db8e450405e5f220192a7b9"
KNOWN4B_test_brain="4bf961e35324169bbd50d1d6ce902a88 a60b18e478a272cfd86b3a3c3b32ea18 04a27acb1e1be6d7855b10a86a144a8b aadfc363b5b302c65882ea41d1bedd94 99c4f57e83864afae0d792f80e56753c b45d62d5df4807e5ee54a7ba07a4086a"

VARIANT=release
BRAIN_DIR=""
FW="${PAPRIUM_FW:-$PROJECT_DIR/firmware}"
GCC_BIN="${RISCV_GCC_BIN:-}"
OUT=""
INSTALL=1
WRAM_BLOB=0
S5=0
REPLACE_STUB=0

usage() { sed -n '4,63p' "$0" | sed 's/^# \{0,1\}//'; }
die() { echo "error: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --release)    VARIANT=release ;;
        --test)       VARIANT=test ;;
        --brain)      [ $# -ge 2 ] || die "--brain needs a folder"; BRAIN_DIR="$2"; shift ;;
        --wram-blob)  WRAM_BLOB=1 ;;
        --s5)         S5=1 ;;
        --fw)         [ $# -ge 2 ] || die "--fw needs a folder"; FW="$2"; shift ;;
        --gcc-bin)    [ $# -ge 2 ] || die "--gcc-bin needs a folder"; GCC_BIN="$2"; shift ;;
        --out)        [ $# -ge 2 ] || die "--out needs a folder"; OUT="$2"; shift ;;
        --no-install) INSTALL=0 ;;
        --replace-stub) REPLACE_STUB=1 ;;
        -h|--help)    usage; exit 0 ;;
        *)            usage >&2; die "unknown argument: $1" ;;
    esac
    shift
done

# ---------------------------------------------------------------- tools
PY=""
for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 6))' >/dev/null 2>&1; then
        PY="$c"; break
    fi
done
[ -n "$PY" ] || die "python 3 not found"
md5() { "$PY" -I -B -c 'import hashlib, sys; print(hashlib.md5(open(sys.argv[1], "rb").read()).hexdigest())' "$1"; }

if [ -z "$GCC_BIN" ]; then
    if command -v "$PREFIX-gcc" >/dev/null 2>&1; then
        GCC_BIN="$(dirname "$(command -v "$PREFIX-gcc")")"
    else
        die "no $PREFIX-gcc on PATH: pass --gcc-bin DIR or set RISCV_GCC_BIN (the bin folder of xPack riscv-none-elf-gcc 15.2.0)"
    fi
fi
[ -x "$GCC_BIN/$PREFIX-gcc" ] || [ -x "$GCC_BIN/$PREFIX-gcc.exe" ] || \
    die "toolchain not found in $GCC_BIN (get xPack riscv-none-elf-gcc 15.2.0, or pass --gcc-bin)"
GCC_BIN="$(cd "$GCC_BIN" && pwd)"
GCC_VER="$("$GCC_BIN/$PREFIX-gcc" --version | head -1)"
case "$GCC_VER" in
    *15.2.0*) ;;
    *) echo "warning: $GCC_VER - the committed images were built with xPack GCC 15.2.0; other versions give other md5s" >&2 ;;
esac

[ -f "$FW/tools/fwbuild.py" ] && [ -f "$FW/fwbuild.json" ] || \
    die "no firmware tree at $FW (pass --fw DIR or set PAPRIUM_FW)"
FW="$(cd "$FW" && pwd)"
FW_COMMIT="$(git -C "$FW" rev-parse HEAD 2>/dev/null || echo unknown)"
FW_DIRTY="$(git -C "$FW" status --porcelain --untracked-files=no 2>/dev/null | head -1 || true)"

# ---------------------------------------------------------------- the brain (optional; fwbuild checks the md5s)
# --s5 (test build 5): the stage-5 variants s5release / s5test at the pocket88k layout (IROM 88 KB: a 56 KB extension)
if [ "$S5" = 1 ]; then
    FWBASE="s5$VARIANT"; LAYOUT=pocket88k; EXT_KB=56
else
    FWBASE="$VARIANT"; LAYOUT=pocket72k; EXT_KB=40
fi
if [ -n "$BRAIN_DIR" ]; then
    [ -d "$BRAIN_DIR" ] || die "--brain: no folder $BRAIN_DIR"
    BRAIN_DIR="$(cd "$BRAIN_DIR" && pwd)"
    for f in brain.bin cf.bin rodata.bin; do
        [ -f "$BRAIN_DIR/$f" ] || die "--brain: $BRAIN_DIR has no $f (expected: brain.bin cf.bin rodata.bin)"
    done
    KIND=brain
    FWVAR="$FWBASE"
else
    KIND=nobrain
    FWVAR="${FWBASE}_nobrain"
fi
# the IROM the RTL builds (core_top.sv PAPRIUM_IROM_KB, = FEAT[23:16]): an installed image must be linked for it
RTL_IROM_KB="$(sed -n 's/^[[:space:]]*localparam \[7:0\][[:space:]]*PAPRIUM_IROM_KB[[:space:]]*=[[:space:]]*8.d\([0-9]*\);.*/\1/p' "$PROJECT_DIR/target/pocket/core_top.sv" | head -1)"
if [ "$INSTALL" = 1 ] && [ "$RTL_IROM_KB" != "$((32 + EXT_KB))" ]; then
    die "this RTL builds a ${RTL_IROM_KB:-?} KB IROM (target/pocket/core_top.sv PAPRIUM_IROM_KB) and these images are linked for $((32 + EXT_KB)) KB: $([ "$S5" = 1 ] && echo "drop --s5" || echo "add --s5") (or --no-install)"
fi

# the boot stub's images (from 0.3.0): the IROM extension and the four WRAM lanes are all zero, which no firmware build
# is (its code reaches past the first 32 KB). Installing over them would turn the Pocket bitstream into one that never
# loads little_man_firmware.bin.
if [ "$INSTALL" = 1 ] && [ "$REPLACE_STUB" = 0 ] && "$PY" -I -B - "$PROJECT_DIR/rtl/PAPRIUM" <<'EOF'
import os, sys
d = sys.argv[1]
zero = lambda f: os.path.isfile(os.path.join(d, f)) and all(int(x, 16) == 0 for x in open(os.path.join(d, f)).read().split())
sys.exit(0 if all(zero(f) for f in ('mcu_ext.txt', 'wram_b0.txt', 'wram_b1.txt', 'wram_b2.txt', 'wram_b3.txt')) else 1)
EOF
then
    die "rtl/PAPRIUM/ holds the boot stub that loads little_man_firmware.bin: run with --no-install (the firmware goes in that file, made by the firmware tree's tools/mkfafrium.py make), or with --replace-stub for a test bitstream with the firmware built in"
fi

[ -n "$OUT" ] || OUT="$PROJECT_DIR/build_output/mcu-$VARIANT$([ "$KIND" = nobrain ] && echo -nobrain || true)"
# the build folder is emptied first, but only if it is empty already or one of ours (marker file): a mistyped --out
# must never wipe someone's folder
MARK=.build_mcu-output
if [ -d "$OUT" ] && [ -n "$(ls -A "$OUT")" ] && [ ! -f "$OUT/$MARK" ]; then
    die "--out $OUT is a non-empty folder that build_mcu.sh did not make; give an empty or new folder"
fi
rm -rf "$OUT"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
echo "made by scripts/build_mcu.sh; the whole folder is deleted by the next build into it" > "$OUT/$MARK"

echo "variant:   $VARIANT, $([ "$KIND" = brain ] && echo "with the CPU MATE brain ($BRAIN_DIR)" || echo "WITHOUT the CPU MATE brain"); fwbuild $FWVAR, layout $LAYOUT (IROM $((32 + EXT_KB)) KB)"
echo "toolchain: $GCC_VER"
echo "firmware:  $FW @ ${FW_COMMIT:0:7}$([ -n "$FW_DIRTY" ] && echo " (uncommitted changes)" || true)"
echo "out:       $OUT"
echo

# ---------------------------------------------------------------- the firmware tree's build (fwbuild s1, one image)
if ! (
    export PAPRIUM_RISCV_BIN="$GCC_BIN"
    # the firmware tree reads the stage-1 brain from PAPRIUM_BRAIN_DIR_S1 (fwbuild.json s1.brain, the brain with the cycle-counter fix);
    # older firmware trees read PAPRIUM_BRAIN_DIR
    if [ "$KIND" = brain ]; then export PAPRIUM_BRAIN_DIR="$BRAIN_DIR" PAPRIUM_BRAIN_DIR_S1="$BRAIN_DIR"; fi
    "$PY" -I -B "$FW/tools/fwbuild.py" s1 --images-only --variant "$FWVAR" --out "$OUT/fw"
) > "$OUT/build.log" 2>&1; then
    tail -40 "$OUT/build.log" >&2
    die "the firmware build failed, see $OUT/build.log"
fi
B="$OUT/fw/s1/$LAYOUT/$FWVAR"
[ -f "$B/main.elf" ] || die "no $B/main.elf after the build (see $OUT/build.log)"

# ---------------------------------------------------------------- the WRAM boot overlay (test build 4b on)
# The firmware build's image.json lists every blob it placed in the WRAM image (wram_blobs: address, bytes, md5); the
# tree's fwbuild.json gives the overlay's room (s1.overlay) and the layout's WRAM init ranges, which the firmware
# build passed to its mkimage.py before the overlay's own range.
MKARGS=()
BLOBINFO="$("$PY" -I -B - "$B/img/image.json" "$FW/fwbuild.json" "$B/img/ovl.img" <<'EOF'
import hashlib, json, sys
img, cfg, ovl = sys.argv[1:4]
blobs = json.load(open(img)).get('wram_blobs', [])
if not blobs:
    print('none'); sys.exit(0)
c = json.load(open(cfg))
o = c['s1']['overlay']; base, room = int(o['base'], 0), int(o['room'])
inits = ['%#x:%#x' % (int(lo, 0), int(hi, 0)) for lo, hi in c['layouts'][c['s1']['layout']]['wram_init']]
if len(blobs) != 1 or int(blobs[0]['addr'], 0) != base:
    sys.exit('the firmware build lists the WRAM blobs %s; this script knows one, the boot overlay at %#x' % (blobs, base))
b = open(ovl, 'rb').read()
m = hashlib.md5(b).hexdigest()
if len(b) != blobs[0]['bytes'] or m != blobs[0]['md5'] or len(b) > room:
    sys.exit('img/ovl.img (%d B, md5 %s) is not the blob the firmware build placed, %s (room %d B)' % (len(b), m, blobs[0], room))
print('%#x %d %d %s %s' % (base, room, len(b), m, ','.join(inits + ['%#x:%#x' % (base, base + room)])))
EOF
)" || die "the firmware build's WRAM blob does not check out (above)"
if [ "$BLOBINFO" = none ]; then
    [ "$WRAM_BLOB" = 0 ] || die "--wram-blob: the firmware build made no WRAM blob (a firmware tree from before test build 4b): nothing to place"
else
    read -r BLOB_ADDR BLOB_ROOM BLOB_BYTES BLOB_MD5 BLOB_INITS <<< "$BLOBINFO"
    [ "$WRAM_BLOB" = 1 ] || die "the firmware build placed a WRAM boot overlay (img/ovl.img, $BLOB_BYTES B at $BLOB_ADDR, md5 $BLOB_MD5): run with --wram-blob (lanes without it boot with no unpack)"
    for r in ${BLOB_INITS//,/ }; do MKARGS+=(--wram-init "$r"); done
    # the file by its name in the build's img/ folder (mkimage.py runs there): no path inside the ADDR:FILE argument
    MKARGS+=(--wram-blob "$BLOB_ADDR:ovl.img")
fi

# ---------------------------------------------------------------- the MegaWire SRAM image (a firmware with the MegaWire code)
# The layout's linker JSON names the SRAM range when the firmware links the MegaWire code there (fwbuild.py passes the
# same range to the firmware tree's mkimage.py as --sram); both splits then write it as sram.bin.
SRAM_RANGE="$("$PY" -I -B - "$FW" "$LAYOUT" <<'EOF'
import json, os, sys
fw, lay = sys.argv[1:3]
c = json.load(open(os.path.join(fw, 'fwbuild.json')))
L = c.get('s1', {}).get('layouts', {}).get(lay) or c.get('layouts', {}).get(lay) or {}
s = json.load(open(os.path.join(fw, L['ld_json']))).get('sram') if 'ld_json' in L else None
print('%s:%s' % tuple(s['img']) if s else 'none')
EOF
)" || die "could not read the layout $LAYOUT from the firmware tree's fwbuild.json"
if [ "$SRAM_RANGE" != none ]; then
    MKARGS+=(--sram "$SRAM_RANGE")
    [ -f "$B/img/sram.bin" ] || die "the layout links an SRAM image ($SRAM_RANGE) but the firmware build wrote no img/sram.bin"
fi

# ---------------------------------------------------------------- this repository's split of the same ELF
(cd "$B/img" && "$PY" -I -B "$FW_DIR_TOOLS/mkimage.py" "$B/main.elf" "$OUT/img" --ext-kb "$EXT_KB" ${MKARGS[@]+"${MKARGS[@]}"} \
    --objdump "$GCC_BIN/$PREFIX-objdump") > "$OUT/image.txt"
IMGS="mcu.txt mcu_ext.txt wram_b0.txt wram_b1.txt wram_b2.txt wram_b3.txt"
for f in $IMGS wram_hi.txt wram_lo.txt; do
    if [ ! -f "$B/img/$f" ]; then
        case "$f" in
            wram_b*) echo "  note: $f: the firmware tree predates the lane images; this repository's mkimage.py made it" ;;
            *)       die "$f: missing from the firmware build" ;;
        esac
        continue
    fi
    cmp -s "$B/img/$f" "$OUT/img/$f" || die "$f: scripts/firmware/mkimage.py and the firmware build disagree"
done
if [ "$SRAM_RANGE" != none ]; then
    cmp -s "$B/img/sram.bin" "$OUT/img/sram.bin" || die "sram.bin: scripts/firmware/mkimage.py and the firmware build disagree"
    echo "  sram.bin (the MegaWire code for the Pocket SRAM, $SRAM_RANGE) == the firmware build's, byte for byte"
fi
"$PY" -I -B - "$B/img" "$OUT/img" <<'EOF' || die "the four WRAM lanes do not hold the bytes of the firmware build's wram_hi / wram_lo"
import os, sys
fw, out = sys.argv[1], sys.argv[2]
rd = lambda d, f: [int(x, 16) for x in open(os.path.join(d, f)).read().split()]
hi, lo = rd(fw, 'wram_hi.txt'), rd(fw, 'wram_lo.txt')
w = [0] * (2 * len(hi)); w[0::2] = hi; w[1::2] = lo
lanes = [rd(out, 'wram_b%d.txt' % i) for i in range(4)]
ok = all(lanes[i] == w[i::4] for i in range(4))
print('  WRAM lanes == the firmware build\'s wram_hi / wram_lo, byte for byte: %s' % ('yes' if ok else 'NO'))
sys.exit(0 if ok else 1)
EOF
"$PY" -I -B - "$OUT/img" "$EXT_KB" <<'EOF' || die "the images do not have the RTL's shapes"
import os, sys
d = sys.argv[1]
words = lambda f: len(open(os.path.join(d, f)).read().split())
want = {'mcu.txt': 8192, 'mcu_ext.txt': 256 * int(sys.argv[2]), 'wram_b0.txt': 12288, 'wram_b1.txt': 12288,
        'wram_b2.txt': 12288, 'wram_b3.txt': 12288}
got = {f: words(f) for f in want}
print('  shapes: ' + ', '.join('%s %d' % (f, n) for f, n in got.items()))
sys.exit(0 if got == want else 1)
EOF
if [ "$WRAM_BLOB" = 1 ]; then
    "$PY" -I -B - "$B/img/image.json" "$OUT/img/image.json" <<'EOF' || die "scripts/firmware/mkimage.py and the firmware build placed different WRAM blobs"
import json, sys
a, b = (json.load(open(p)).get('wram_blobs', []) for p in sys.argv[1:3])
print('  WRAM blobs (image.json wram_blobs), the firmware build\'s == this repository\'s: %s' % ('yes' if a == b else 'NO'))
sys.exit(0 if a == b else 1)
EOF
    "$PY" -I -B "$FW_DIR_TOOLS/ovlcheck.py" "$OUT/img" "$B/img/ovl.img" --addr "$BLOB_ADDR" --room "$BLOB_ROOM" || \
        die "the overlay read back from the WRAM lanes is not the firmware build's ovl.img"
fi

# ---------------------------------------------------------------- report
GOT=""
echo
for f in $IMGS; do
    m="$(md5 "$OUT/img/$f")"
    GOT="$GOT${GOT:+ }$m"
    printf '  %-12s %s\n' "$f" "$m"
done
"$PY" -I -B -c 'import json, sys
r = json.load(open(sys.argv[1]))
print("  rom image %d B: rom0 %d of 32768 B, extension %d of %d B; WRAM code window %d B" % (
    r["rom_bytes"], r["rom0_used"], r["ext_used"], r["ext_bytes"], r["wram_code_bytes"]))' "$OUT/img/image.json"
if [ "$WRAM_BLOB" = 1 ]; then
    echo "  WRAM boot overlay: ovl.img $BLOB_BYTES of $BLOB_ROOM B at $BLOB_ADDR, md5 $BLOB_MD5 (read back intact)"
fi
if [ "$SRAM_RANGE" != none ]; then
    echo "  sram.bin    $(md5 "$OUT/img/sram.bin") ($(wc -c < "$OUT/img/sram.bin") B; not a bitstream image: it goes in the firmware file)"
fi
KNOWN_VAR="KNOWN_${VARIANT}_${KIND}"
KNOWNLMF_VAR="KNOWNLMF_${VARIANT}_${KIND}"
KNOWN4A_VAR="KNOWN4A_${VARIANT}_${KIND}"
KNOWN4B_VAR="KNOWN4B_${VARIANT}_${KIND}"
if [ "$S5" = 1 ] && [ "$GOT" = "${!KNOWNLMF_VAR}" ]; then
    echo "  = the $VARIANT build $([ "$KIND" = brain ] && echo with || echo without) the brain of Little-Man Firmware 1.0 (IROM 88 KB, with the WRAM boot overlay), byte for byte"
elif [ "$S5" = 1 ] && [ "$GOT" = "${!KNOWN_VAR}" ]; then
    case "$VARIANT/$KIND" in
        release/nobrain) echo "  = test build S3c's RELEASE build without the brain, the images committed here before the firmware file, byte for byte" ;;
        *)               echo "  = test build S3c's $VARIANT build $([ "$KIND" = brain ] && echo with || echo without) the brain (IROM 88 KB, with the WRAM boot overlay), byte for byte" ;;
    esac
elif [ "$S5" = 0 ] && [ "$GOT" = "${!KNOWN4A_VAR}" ]; then
    echo "  = test build 4a's $VARIANT build $([ "$KIND" = brain ] && echo with || echo without) the brain, byte for byte"
elif [ "$S5" = 0 ] && [ -n "${!KNOWN4B_VAR}" ] && [ "$GOT" = "${!KNOWN4B_VAR}" ]; then
    echo "  = test build 4b's $VARIANT build $([ "$KIND" = brain ] && echo with || echo without) the brain (with the WRAM boot overlay), byte for byte"
else
    echo "  (not the images of Little-Man Firmware 1.0 (--s5), test build S3c (--s5), test build 4a or test build 4b: another firmware version, uncommitted changes or another toolchain)"
fi

# ---------------------------------------------------------------- install
# Quartus reads rtl/PAPRIUM/*.txt, never build_output/. A build that is not installed changes nothing.
if [ "$INSTALL" = 1 ]; then
    for f in $IMGS; do cp -f "$OUT/img/$f" "$PROJECT_DIR/rtl/PAPRIUM/$f"; done
    echo
    echo "installed -> rtl/PAPRIUM/{mcu,mcu_ext,wram_b0,wram_b1,wram_b2,wram_b3}.txt (what Quartus reads)"
    if [ "$WRAM_BLOB" = 1 ]; then
        "$PY" -I -B "$FW_DIR_TOOLS/ovlcheck.py" "$PROJECT_DIR/rtl/PAPRIUM" "$B/img/ovl.img" --addr "$BLOB_ADDR" --room "$BLOB_ROOM" || \
            die "the installed rtl/PAPRIUM WRAM lanes fail the overlay read-back"
    fi
    if [ "$KIND" = brain ]; then
        echo
        echo "  These images CONTAIN THE CPU MATE BRAIN. Build the bitstream, then put the committed ones back"
        echo "  (git checkout -- rtl/PAPRIUM/mcu.txt rtl/PAPRIUM/mcu_ext.txt rtl/PAPRIUM/wram_b0.txt rtl/PAPRIUM/wram_b1.txt"
        echo "   rtl/PAPRIUM/wram_b2.txt rtl/PAPRIUM/wram_b3.txt,"
        echo "  or run this script again without --brain). Never commit them: the brain is not part of the repository."
    fi
else
    echo
    echo "not installed (--no-install): rtl/PAPRIUM/ is unchanged"
fi
