#!/usr/bin/env bash
# Assemble support/loader.asm into pkg/pocket/Cores/*/loader.bin. No loader.asm, no work.
#
# pocket: no upstream counterpart, assembles support/loader.asm into every core package.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

ASM="$PROJECT_DIR/support/loader.asm"
if [ ! -f "$ASM" ]; then
    echo "no loader program ($ASM), skipping"
    exit 0
fi

ARCH_DIR="$PROJECT_DIR/build_output/bass-chip32"
BASS_SRC="$PROJECT_DIR/build_output/bass-src"
BASS_BIN="$ARCH_DIR/bass"

if [ ! -x "$BASS_BIN" ]; then
    mkdir -p "$PROJECT_DIR/build_output"
    [ -d "$ARCH_DIR" ] || git clone --depth 1 https://github.com/open-fpga/bass-chip32.git "$ARCH_DIR"
    [ -d "$BASS_SRC" ] || git clone --depth 1 -b devel https://github.com/ARM9/bass.git "$BASS_SRC"
    # nall misses <stdexcept> with newer GCC
    grep -q '#include <stdexcept>' "$BASS_SRC/nall/arithmetic/natural.hpp" || \
        sed -i '1a #include <stdexcept>' "$BASS_SRC/nall/arithmetic/natural.hpp"
    make -C "$BASS_SRC/bass" -j"$(nproc)"
    # bass looks for "architectures" next to the executable, so it has to live
    # in the bass-chip32 checkout rather than in its own build tree
    cp "$BASS_SRC/bass/out/bass" "$BASS_BIN"
fi

cd "$(dirname "$ASM")"
"$BASS_BIN" "$(basename "$ASM")"
# Lands next to the bitstreams rather than straight into the packages, so CI can
# carry every build product between jobs as one artifact. build_output exists by
# now either way: bass itself lives in it.
mv -f loader.bin "$PROJECT_DIR/build_output/loader.bin"
# the per-platform core packages share one loader
"$SCRIPT_DIR/install_binaries.sh" loader.bin
