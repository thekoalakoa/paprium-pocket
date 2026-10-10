#!/usr/bin/env bash
# Build the Paprium MCU firmware: krikzz's mega-ppm at its pinned commit + patches/mega-ppm-pocket.patch,
# linked with scripts/firmware/paprium_mcu.ld and split into the four block-RAM init files the RTL reads:
#
#   rtl/PAPRIUM/mcu.txt       IROM rom0, 32 KB          ($readmemh in rtl/PAPRIUM/mcu_core.sv)
#   rtl/PAPRIUM/mcu_ext.txt   IROM extension, 22 KB     ($readmemh in rtl/PAPRIUM/mcu_core.sv)
#   rtl/PAPRIUM/wram_hi.txt   WRAM even bytes           ($readmemh in rtl/PAPRIUM/memory.sv)
#   rtl/PAPRIUM/wram_lo.txt   WRAM odd bytes            ($readmemh in rtl/PAPRIUM/memory.sv)
#
# Usage:
#   ./scripts/build_mcu.sh [--release | --test] [--brain DIR] [--mega-ppm DIR] [--gcc-bin DIR]
#                          [--out DIR] [--no-install] [--any-brain]
#
#   --release       (default) the shipping firmware: debug aids off (-DPPM_RELEASE=1)
#   --test          the test firmware: SAT snapshot, object dump and UART printf on
#   --brain DIR     a folder holding the CPU MATE brain from the release download: brain.bin, cf.bin and
#                   rodata.bin. Without it the firmware is built WITHOUT the brain (BUDDY_NO_BRAIN): it is the
#                   same firmware in every other respect, and the CPU MATE gets no input from the cart.
#   --any-brain     accept brain files whose md5s are not the 0.2.6 ones (the entry table in
#                   zz_buddy_brain.c belongs to that exact brain build, so expect trouble)
#   --mega-ppm DIR  a git clone of https://github.com/krikzz/mega-ppm (default: ../repos/mega-ppm next to
#                   this repository, or $MEGA_PPM). Only the pinned commit is read, with git archive: the
#                   clone's working tree and branch do not matter and are never modified.
#   --gcc-bin DIR   the bin folder of the xPack riscv-none-elf GCC 15.2.0 toolchain (default: $RISCV_GCC_BIN,
#                   then riscv-none-elf-gcc on PATH, then ../tools/xpack-riscv-none-elf-gcc-15.2.0-1/bin)
#   --out DIR       build folder (default: build_output/mcu-<variant>[-nobrain], git-ignored)
#   --no-install    do not copy the four images into rtl/PAPRIUM/
#
# The committed rtl/PAPRIUM images are the RELEASE firmware WITHOUT the brain, so the brain's bytes are never
# in git and a plain Quartus build works from a clean clone. ./scripts/build_mcu.sh with no arguments rebuilds
# exactly those files. To build the bitstream that shipped, run it with --brain first (and do not commit the
# images it installs). See docs/firmware/README.md.
#
# Needs: bash, git, tar, python 3, and the toolchain above. Git Bash on Windows works.
set -euo pipefail
export LC_ALL=C

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FW_DIR="$SCRIPT_DIR/firmware"
PATCH="$PROJECT_DIR/patches/mega-ppm-pocket.patch"

MEGA_PPM_COMMIT=84be6bdd0bff18bf143d9ab3cc7267a5954d5a70
PREFIX=riscv-none-elf
EXT_KB=22

# the CPU MATE brain of the 0.2.6 release download
BRAIN_FILES="brain.bin cf.bin rodata.bin"
BRAIN_MD5_brain=1b64e14d710e8768d3385d1421162bc7
BRAIN_MD5_cf=a5fa37b435f26f9fc2c8fd62d218d7ef
BRAIN_MD5_rodata=5b1d74f454b578196ed1e82548f01b99

# image md5s (mcu.txt mcu_ext.txt wram_hi.txt wram_lo.txt, as written: CRLF lines)
KNOWN_release_brain="1570f36793636d008515faa7608d9c00 d7da4574ba8834e8a9d9319a4081f313 1dfe3f401aaa4b0dab605a480a67c89c 502a6b1bfe800c004cf6605b9b3ec2a6"
KNOWN_test_brain="52801d2884e30932d2b9ae5c92d29207 2c297175fbd4f7f906762c4ca42ce7e5 fb00f0ca4f3b3d5b0f84bc792cbca51e d0fd1a9b1af7bad1f9c9529dcbe60131"
KNOWN_release_nobrain="23e5d47adaea7fdd5c98c1eac5065442 e2883aca6e3273cb43a8c75d3ae5c8d7 fc470b86fa6e559d0def090e9dc3a7c1 36b0468aa6862857d4987fa96818a91a"
KNOWN_test_nobrain="8836a7e5c71156962ab3220ebc51853f 45974a8d6267a5bfddc66cddc5916654 d29ca4ebae044e5764309ddcad103459 2ec453fe6ad48b46dcf344a2ec41268e"

VARIANT=release
BRAIN_DIR=""
ANY_BRAIN=0
MEGA_PPM="${MEGA_PPM:-$PROJECT_DIR/../repos/mega-ppm}"
GCC_BIN="${RISCV_GCC_BIN:-}"
OUT=""
INSTALL=1

usage() { sed -n '2,34p' "$0" | sed 's/^# \{0,1\}//'; }
die() { echo "error: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --release)    VARIANT=release ;;
        --test)       VARIANT=test ;;
        --brain)      [ $# -ge 2 ] || die "--brain needs a folder"; BRAIN_DIR="$2"; shift ;;
        --any-brain)  ANY_BRAIN=1 ;;
        --mega-ppm)   [ $# -ge 2 ] || die "--mega-ppm needs a folder"; MEGA_PPM="$2"; shift ;;
        --gcc-bin)    [ $# -ge 2 ] || die "--gcc-bin needs a folder"; GCC_BIN="$2"; shift ;;
        --out)        [ $# -ge 2 ] || die "--out needs a folder"; OUT="$2"; shift ;;
        --no-install) INSTALL=0 ;;
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
        GCC_BIN="$PROJECT_DIR/../tools/xpack-riscv-none-elf-gcc-15.2.0-1/bin"
    fi
fi
[ -x "$GCC_BIN/$PREFIX-gcc" ] || [ -x "$GCC_BIN/$PREFIX-gcc.exe" ] || \
    die "toolchain not found in $GCC_BIN (get xPack riscv-none-elf-gcc 15.2.0, or pass --gcc-bin)"
export PATH="$GCC_BIN:$PATH"
GCC_VER="$($PREFIX-gcc --version | head -1)"
case "$GCC_VER" in
    *15.2.0*) ;;
    *) echo "warning: $GCC_VER - the shipped images were built with xPack GCC 15.2.0; other versions give other md5s" >&2 ;;
esac

[ -f "$PATCH" ] || die "missing $PATCH"
[ -d "$MEGA_PPM" ] || die "no mega-ppm clone at $MEGA_PPM
  git clone https://github.com/krikzz/mega-ppm.git \"$MEGA_PPM\"   (or pass --mega-ppm DIR)"
git -C "$MEGA_PPM" cat-file -e "$MEGA_PPM_COMMIT^{commit}" 2>/dev/null || \
    die "$MEGA_PPM does not have commit $MEGA_PPM_COMMIT (git -C \"$MEGA_PPM\" fetch origin)"

# ---------------------------------------------------------------- the brain (optional)
if [ -n "$BRAIN_DIR" ]; then
    [ -d "$BRAIN_DIR" ] || die "--brain: no folder $BRAIN_DIR"
    BRAIN_DIR="$(cd "$BRAIN_DIR" && pwd)"
    for f in $BRAIN_FILES; do
        [ -f "$BRAIN_DIR/$f" ] || die "--brain: $BRAIN_DIR has no $f (expected: $BRAIN_FILES)"
        want="BRAIN_MD5_${f%.bin}"
        got="$(md5 "$BRAIN_DIR/$f")"
        if [ "$got" != "${!want}" ]; then
            [ "$ANY_BRAIN" = 1 ] || die "--brain: $f md5 $got, the 0.2.6 brain is ${!want} (--any-brain to build anyway)"
            echo "warning: $f md5 $got is not the 0.2.6 brain (${!want})" >&2
        fi
    done
    KIND=brain
else
    KIND=nobrain
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
SRC="$OUT/src"
OBJ="$OUT/obj"
mkdir -p "$SRC" "$OBJ"

echo "variant:   $VARIANT, $([ "$KIND" = brain ] && echo "with the CPU MATE brain ($BRAIN_DIR)" || echo "WITHOUT the CPU MATE brain")"
echo "toolchain: $GCC_VER"
echo "mega-ppm:  $MEGA_PPM @ ${MEGA_PPM_COMMIT:0:7}"
echo "out:       $OUT"
echo

# ---------------------------------------------------------------- source = pinned mega-ppm + our patch
# git archive of the commit itself (LF, whatever the clone's checkout settings), then the patch with any CRs a
# Windows checkout added taken out again. The source tree is its own (throwaway) repository, so git apply works on
# it and not on a repository around the build folder.
git -C "$MEGA_PPM" -c core.autocrlf=false archive "$MEGA_PPM_COMMIT" mcu | tar -x -C "$SRC"
tr -d '\r' < "$PATCH" > "$OUT/mega-ppm-pocket.patch"
(
    cd "$SRC"
    git init -q .
    git -c core.autocrlf=false -c core.safecrlf=false apply --whitespace=nowarn "$OUT/mega-ppm-pocket.patch"
)
MCU="$SRC/mcu"
LIB="$MCU/lib"

# ---------------------------------------------------------------- compile and link (as mega-ppm's Makefile, plus
# the switches below; Git Bash has no make)
# GCC 15 split CSR and FENCE.I out of the base ISA, so they are named explicitly: krikzz's Makefile says plain rv32im.
CC_OPTS="-march=rv32im_zicsr_zifencei -mabi=ilp32 -O2 -Wall -ffunction-sections -fdata-sections -nostartfiles"
CC_OPTS="$CC_OPTS -Wl,--gc-sections -lm -lc -lgcc -lc"
CC_OPTS="$CC_OPTS -falign-functions=4 -falign-labels=4 -falign-loops=4 -falign-jumps=4"
CC_OPTS="$CC_OPTS -Wno-pointer-sign -DBUDDY_STUB_BRAIN=0"
if [ "$KIND" = brain ]; then
    CC_OPTS="$CC_OPTS -DBUDDY_LINKED_BRAIN=1"
    for f in $BRAIN_FILES; do cp "$BRAIN_DIR/$f" "$OBJ/$f"; done      # zz_buddy_brain.c .incbin's them from here
else
    CC_OPTS="$CC_OPTS -DBUDDY_LINKED_BRAIN=0 -DBUDDY_NO_BRAIN=1"
fi
CC_OPTS="$CC_OPTS -DBUDDY_TRAP_TRAMP=1"
[ "$VARIANT" = release ] && CC_OPTS="$CC_OPTS -DPPM_RELEASE=1"

# link order = the shipped build's: the app in name order, then the NEORV32 runtime, then crt0
SRCS=()
for f in everdrive.c main.c mame.c mdp.c paprium.c sfx.c zz_buddy.c zz_buddy_brain.c zz_buddy_trap.c; do
    SRCS+=("$MCU/$f")
done
for f in "$LIB"/source/*.c; do SRCS+=("$f"); done
if ! (
    cd "$OBJ" || exit 1          # (set -e is off inside an if condition: every step checks itself)
    OBJS=()
    for f in "${SRCS[@]}"; do
        o="$(basename "$f").o"
        $PREFIX-gcc -c $CC_OPTS -I "$LIB/include" -I "$MCU" "$f" -o "$o" || exit 1
        OBJS+=("$o")
    done
    # vu_due / vu_on are static in paprium.c; the CPU MATE glue reads them, so they are made global in the object
    # (no recompile: paprium.c's code is unchanged)
    $PREFIX-objcopy --globalize-symbol=vu_due --globalize-symbol=vu_on paprium.c.o || exit 1
    $PREFIX-gcc -c $CC_OPTS -I "$LIB/include" -I "$MCU" "$LIB/common/crt0.S" -o crt0.S.o || exit 1
    OBJS+=(crt0.S.o)
    $PREFIX-gcc $CC_OPTS -T "$FW_DIR/paprium_mcu.ld" "${OBJS[@]}" -o main.elf -Wl,-Map,main.map || exit 1
) > "$OUT/compile.log" 2>&1; then
    grep -E -i 'error|undefined|overlap|runs into|overflows' "$OUT/compile.log" | head -40 >&2 || true
    die "build failed, see $OUT/compile.log"
fi
echo "compiler warnings: $(grep -c 'warning:' "$OUT/compile.log" || true) (full text in compile.log)"

$PREFIX-size -A "$OBJ/main.elf" | grep -v -E "debug|comment|attributes" > "$OUT/size.txt"
$PREFIX-nm -n -S "$OBJ/main.elf" > "$OUT/main.nm"
"$PY" -I -B "$FW_DIR/mkimage.py" "$OBJ/main.elf" "$OUT/img" --ext-kb "$EXT_KB" --objdump "$PREFIX-objdump" > "$OUT/image.txt"

# ---------------------------------------------------------------- report
IMGS="mcu.txt mcu_ext.txt wram_hi.txt wram_lo.txt"
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
KNOWN_VAR="KNOWN_${VARIANT}_${KIND}"
if [ "$GOT" = "${!KNOWN_VAR}" ]; then
    case "$VARIANT/$KIND" in
        release/brain)   echo "  = the shipped 0.2.6 RELEASE firmware, byte for byte" ;;
        test/brain)      echo "  = the 0.2.6 TEST firmware, byte for byte" ;;
        release/nobrain) echo "  = the committed rtl/PAPRIUM images (0.2.6 RELEASE without the brain), byte for byte" ;;
        test/nobrain)    echo "  = the 0.2.6 TEST firmware without the brain, byte for byte" ;;
    esac
else
    echo "  (not a known 0.2.6 image set: the source, the patch, the brain or the toolchain differ)"
fi

# ---------------------------------------------------------------- install
# Quartus reads rtl/PAPRIUM/*.txt, never build_output/. A build that is not installed changes nothing.
if [ "$INSTALL" = 1 ]; then
    for f in $IMGS; do cp -f "$OUT/img/$f" "$PROJECT_DIR/rtl/PAPRIUM/$f"; done
    echo
    echo "installed -> rtl/PAPRIUM/{mcu,mcu_ext,wram_hi,wram_lo}.txt (what Quartus reads)"
    if [ "$KIND" = brain ]; then
        echo
        echo "  These images CONTAIN THE CPU MATE BRAIN. Build the bitstream, then put the committed ones back"
        echo "  (git checkout -- rtl/PAPRIUM/mcu.txt rtl/PAPRIUM/mcu_ext.txt rtl/PAPRIUM/wram_hi.txt rtl/PAPRIUM/wram_lo.txt,"
        echo "  or run this script again without --brain). Never commit them: the brain is not part of the repository."
    fi
else
    echo
    echo "not installed (--no-install): rtl/PAPRIUM/ is unchanged"
fi
