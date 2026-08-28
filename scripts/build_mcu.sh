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
echo "IMEM    : 16384 bytes (rtl/PAPRIUM/mcu_core.sv)"
if [ "$BYTES" -gt 16384 ]; then
    echo "*** OVERFLOWS the current IMEM by $((BYTES - 16384)) bytes."
    echo "    Retry with -Os, or grow rom[]/addr[] in mcu_core.sv (32 KB = ~13 more M10K)."
else
    echo "fits, $((16384 - BYTES)) bytes spare"
fi

echo
echo "reference builds for comparison:"
for f in "$MCU_SRC/mcu.txt" "$PROJECT_DIR/rtl/PAPRIUM/mcu.txt"; do
    [ -f "$f" ] && printf "  %-52s %s words\n" "$f" "$(wc -w < "$f")"
done
[ -f "$OUT/mcu.txt" ] && printf "  %-52s %s words\n" "$OUT/mcu.txt" "$(wc -w < "$OUT/mcu.txt")"
