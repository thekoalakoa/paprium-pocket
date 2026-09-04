#!/usr/bin/env bash
# Build the instrumented GPGX libretro core for the window-read logger.
#
#   ./scripts/gpgx_winlog_build.sh            window reads + page turns + cmds
#   ./scripts/gpgx_winlog_build.sh --dma      ... plus 68k-bus VDP DMA destinations
#
# Encodes the recipe that took four detours to find (docs/PORT_PLAN.md):
#   - gpgx-build/paprium.h.orig is the pristine fork (== src/Full Source); the
#     working copy may be the MWMM render instrumentation, which exit(1)s on
#     a missing render input and looks like a crash. ALWAYS start from .orig.
#   - msys2 gcc 16 compiles fine under msys make, but gcc's driver cannot find
#     a temp dir for the LINK when spawned through msys make ("Cannot create
#     temporary file in C:\WINDOWS"). Run the link line directly (link.cmd).
#   - -pipe is harmless and kept; the as-shipped -O3 is fine (the "crash" was
#     never optimisation).
#   - The core is written next to the Makefile; RetroArch loads it with -L and
#     writes paprium_winlog.bin in its working directory (launch-winlog.cmd
#     pins that to vdp-capture\).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
T0=$(date +%s)
G="$HERE/../gpgx-build"
export PATH="/c/msys64/mingw64/bin:/c/msys64/usr/bin:$PATH"
cd "$G"

[ -f core/cart_hw/paprium.h.orig ] || { echo "no paprium.h.orig - refusing to guess a base"; exit 1; }
cp core/cart_hw/paprium.h core/cart_hw/paprium.h.before-winlog 2>/dev/null || true
cp core/cart_hw/paprium.h.orig core/cart_hw/paprium.h
if [ -f "$HERE/../src/Full Source/core/cart_hw/paprium.h" ]; then
  diff -q core/cart_hw/paprium.h "$HERE/../src/Full Source/core/cart_hw/paprium.h" >/dev/null \
    || { echo "paprium.h.orig != Full Source - refusing"; exit 1; }
fi
[ -f core/vdp_ctrl.c.orig ] || cp core/vdp_ctrl.c core/vdp_ctrl.c.orig
cp core/vdp_ctrl.c.orig core/vdp_ctrl.c
[ -f Makefile.libretro.orig ] && cp Makefile.libretro.orig Makefile.libretro

python "$HERE/scripts/apply_gpgx_winlog.py" core/cart_hw/paprium.h
# the header must now carry every hook the applier's current version emits
for tok in "PAPRIUM_WINLOG 1" "winlog(2," "winlog(0," ; do
  grep -q "$tok" core/cart_hw/paprium.h || { echo "hook '$tok' missing from the applied header - applier is broken"; exit 1; }
done
for tok in "rec\[0\] = 11" "m68k\.pc" "winlog(9,"; do
  if grep -q "$tok" "$HERE/scripts/apply_gpgx_winlog.py"; then
    grep -q "$tok" core/cart_hw/paprium.h || { echo "applier has '$tok' but the applied header does not - apply failed"; exit 1; }
  fi
done
OLDMD5=$(md5sum genesis_plus_gx_libretro.dll 2>/dev/null | cut -c1-8 || echo none)
EXTRA=""
if [ "${1:-}" = "--dma" ]; then
  python "$HERE/scripts/apply_gpgx_dmalog.py" core/vdp_ctrl.c
  EXTRA="-DPAPRIUM_WINLOG_EXTERN"
fi

find . -name "*.o" -delete
/c/msys64/usr/bin/make -f Makefile.libretro platform=win CC="gcc -pipe $EXTRA" CXX="g++ -pipe $EXTRA" -j4 > build-winlog.log 2>&1 || true
n=$(grep -c " error:" build-winlog.log || true)
[ "$n" = "0" ] || { echo "compile errors:"; grep -m5 " error:" build-winlog.log; exit 1; }

# the link line, exactly as make would run it, executed here instead
if [ ! -f link.cmd ]; then
  /c/msys64/usr/bin/make -n -f Makefile.libretro platform=win CC="gcc -pipe" 2>/dev/null \
    | grep -m1 "genesis_plus_gx_libretro.dll" > link.cmd
fi
eval "$(cat link.cmd)" > link-winlog.log 2>&1 || { echo "link failed:"; tail -3 link-winlog.log; exit 1; }
NEWMD5=$(md5sum genesis_plus_gx_libretro.dll | cut -c1-8)
MT=$(stat -c %Y genesis_plus_gx_libretro.dll)
[ "$MT" -ge "$T0" ] || { echo "DLL is OLDER than this run (stale build) - refusing to call it built"; exit 1; }
[ "$NEWMD5" != "$OLDMD5" ] || echo "WARNING: md5 unchanged from the previous core ($OLDMD5) - identical source?"
echo "core: $G/genesis_plus_gx_libretro.dll  md5 $OLDMD5 -> $NEWMD5  built $(date -d @$MT +%H:%M)  dma=${1:-off}"
