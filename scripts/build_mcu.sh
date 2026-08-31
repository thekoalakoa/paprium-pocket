#!/usr/bin/env bash
# Build the Paprium MCU firmware from krikzz's mega-ppm source.
#
#   ./scripts/build_mcu.sh [-Os]
#
# Replicates repos/mega-ppm/mcu/Makefile, because Git Bash has no make. Same
# flags, same linker script, same image generator - only the driver differs.
#
# Output goes to build_output/mcu/ so krikzz's tree is never modified: the
# reference mcu.txt in that repo is our only known-good baseline for comparison.
#
# WHY: the punk-TV cue dies because sfx_player_update abandons a channel once
# size hits 0, so the game's later sfx_loop (which enables looping and ramps the
# volume) lands on a dead channel. The fix is two lines in sfx_loop. It is
# firmware, so it cannot be done in RTL.
#
# NOTE ON SIZE: our shipping mcu.txt is 15,848 bytes against a 16 KB IMEM - 536
# bytes spare. That limit is imposed by rtl/PAPRIUM/mcu_core.sv (`rom[16384/4]`
# and `addr[13:2]`), NOT by the linker, whose script already allows 256 KB. If a
# rebuild overflows, growing the IMEM is cheap: 32 KB costs ~13 more M10K against
# 62 free. Try -Os first; grow the RAM if that is not enough.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MCU_SRC="$(cd "$PROJECT_DIR/../repos/mega-ppm/mcu" && pwd)"
TOOLS="$(cd "$PROJECT_DIR/../tools" && pwd)"            # xPack toolchain lives here
MPTOOLS="$(cd "$PROJECT_DIR/../repos/mega-ppm/tools" && pwd)"  # krikzz's image generator
OUT="$PROJECT_DIR/build_output/mcu"

EFFORT="${1:--O2}"
PREFIX=riscv-none-elf
GCC_BIN="$TOOLS/xpack-riscv-none-elf-gcc-15.2.0-1/bin"

[ -x "$GCC_BIN/$PREFIX-gcc.exe" ] || {
    echo "error: toolchain not found at $GCC_BIN" >&2
    exit 1
}
export PATH="$GCC_BIN:$PATH"

LIB="$MCU_SRC/lib"
# GCC 15 split CSR and FENCE.I out of the base ISA, so they must be named
# explicitly - krikzz's Makefile says plain rv32im because his GCC still folded
# them in. Same instructions either way; the CPU has always had them.
CC_OPTS="-march=rv32im_zicsr_zifencei -mabi=ilp32 $EFFORT -Wall -ffunction-sections -fdata-sections -nostartfiles"
CC_OPTS="$CC_OPTS -Wl,--gc-sections -lm -lc -lgcc -lc"
CC_OPTS="$CC_OPTS -falign-functions=4 -falign-labels=4 -falign-loops=4 -falign-jumps=4"
CC_OPTS="$CC_OPTS -Wno-pointer-sign"

rm -rf "$OUT"; mkdir -p "$OUT"

echo "toolchain: $($PREFIX-gcc --version | head -1)"
echo "effort:    $EFFORT"
echo

# Sources: the app, the NEORV32 runtime, and crt0. Arrays throughout - the
# project path contains a space and word-splitting mangles it otherwise.
SRCS=("$MCU_SRC"/*.c "$LIB"/source/*.c)
OBJS=()
for f in "${SRCS[@]}"; do
    [ -f "$f" ] || continue
    o="$OUT/$(basename "$f").o"
    $PREFIX-gcc -c $CC_OPTS -I "$LIB/include" -I "$MCU_SRC" "$f" -o "$o"
    OBJS+=("$o")
done
$PREFIX-gcc -c $CC_OPTS -I "$LIB/include" -I "$MCU_SRC" "$LIB/common/crt0.S" -o "$OUT/crt0.S.o"
OBJS+=("$OUT/crt0.S.o")

$PREFIX-gcc $CC_OPTS -T "$LIB/common/neorv32.ld" "${OBJS[@]}" -o "$OUT/main.elf"

echo "Memory utilization:"
$PREFIX-size "$OUT/main.elf"
echo

for sec in text rodata data; do
    $PREFIX-objcopy -I elf32-little "$OUT/main.elf" -j ".$sec" -O binary "$OUT/$sec.bin"
done
cat "$OUT/text.bin" "$OUT/rodata.bin" "$OUT/data.bin" > "$OUT/mcu.bin"
rm -f "$OUT/text.bin" "$OUT/rodata.bin" "$OUT/data.bin"

# bin_to_verilog writes mcu.txt beside its input
( cd "$OUT" && "$MPTOOLS/bin_to_verilog.exe" wsize=4 make=mcu.bin )

BYTES=$(wc -c < "$OUT/mcu.bin")
echo
echo "mcu.bin : $BYTES bytes"
echo "IMEM    : 32768 bytes (rtl/PAPRIUM/mcu_core.sv, grown from 16 KB)"
if [ "$BYTES" -gt 32768 ]; then
    echo "*** OVERFLOWS the current IMEM by $((BYTES - 16384)) bytes."
    echo "    Retry with -Os, or grow rom[]/addr[] in mcu_core.sv (32 KB = ~13 more M10K)."
else
    echo "fits, $((32768 - BYTES)) bytes spare"
fi

# INSTALL it. This script used to build into build_output/ and merely PRINT the
# rtl copy as a "reference build for comparison", which reads like confirmation
# and is not: Quartus reads rtl/PAPRIUM/mcu.txt ($readmemh in mcu_core.sv), so a
# build run after this script alone silently used the OLD firmware.
#
# That cost a full 25-minute fit, and the timing gate cannot catch it - ALM,
# M10K, setup and hold all come back identical to shipping, which is exactly what
# "firmware-only, no RTL touched" is supposed to look like. It is also what
# "nothing changed at all" looks like. See docs/BUILD_REFERENCE.md.
if [ -f "$OUT/mcu.txt" ]; then
    PREV=""
    [ -f "$PROJECT_DIR/rtl/PAPRIUM/mcu.txt" ] && \
        PREV=$(md5sum < "$PROJECT_DIR/rtl/PAPRIUM/mcu.txt" | cut -d" " -f1)
    cp -f "$OUT/mcu.txt" "$PROJECT_DIR/rtl/PAPRIUM/mcu.txt"
    NOW=$(md5sum < "$PROJECT_DIR/rtl/PAPRIUM/mcu.txt" | cut -d" " -f1)

    echo
    echo "installed -> rtl/PAPRIUM/mcu.txt   (this is what Quartus reads)"
    if [ "$PREV" = "$NOW" ]; then
        echo "  UNCHANGED from the previous firmware ($NOW)."
        echo "  A rebuild will produce an IDENTICAL bitstream. If you expected a"
        echo "  change, the source edit did not take."
    else
        echo "  changed: ${PREV:-none} -> $NOW"
        echo "  The next Paprium fit must differ in bitstream md5 from the last"
        echo "  shipping one. Identical metrics AND an identical hash = void build."
    fi
fi

echo
echo "other copies, for reference only:"
[ -f "$MCU_SRC/mcu.txt" ] && printf "  %-52s %s words\n" "$MCU_SRC/mcu.txt" "$(wc -w < "$MCU_SRC/mcu.txt")"
