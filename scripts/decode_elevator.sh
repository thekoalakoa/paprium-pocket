#!/usr/bin/env bash
# One-shot decode of a RetroArch session on the DMA-instrumented core:
# archive the log and the auto-saved end state under a timestamp, then run
# the read-pattern verdict, the DMA table, and the over-read -> tiles ->
# on-screen-cells scan. Never overwrites an earlier session's artefacts.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
V="$HERE/../vdp-capture"
TAG="${1:-$(date +%Y%m%d-%H%M)}"
LOG="$V/winlog-$TAG.bin"; ST="$V/states/Genesis Plus GX/$TAG.state.auto"
[ -f "$V/paprium_winlog.bin" ] || { echo "no paprium_winlog.bin in vdp-capture"; exit 1; }
cp "$V/paprium_winlog.bin" "$LOG"
[ -f "$V/states/Genesis Plus GX/Paprium.state.auto" ] && cp "$V/states/Genesis Plus GX/Paprium.state.auto" "$ST"
echo "archived: $LOG ($(stat -c %s "$LOG") bytes)$( [ -f "$ST" ] && echo ", $ST")"
echo; echo "################ READ PATTERN ################"
python "$HERE/scripts/analyze_winlog.py" "$LOG" | tee "$V/decode-$TAG-pattern.txt" | sed -n '1,2p;/not tape-shaped/p;/^VERDICT/,$p'
if [ -f "$ST" ]; then
  echo; echo "################ OVER-READ -> TILES -> CELLS ################"
  python "$HERE/scripts/overread_tiles.py" "$LOG" "$ST" | tee "$V/decode-$TAG-tiles.txt"
fi
