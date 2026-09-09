#!/usr/bin/env bash
# Pack the per-track PCM files into the single blob the core streams.
#
#   ./scripts/build_cdda_blob.sh <pcm-dir> <output.pcm>
#
# <pcm-dir> holds track01.pcm .. track62.pcm as produced by build_cdda.sh.
#
# Why one file: APF caps a core at 32 data slots and Paprium has 62 tracks, so
# slot-per-track is impossible, and repointing one slot with the openfile target
# command never worked - it answers "malformed path" and the protocol is not
# documented well enough to debug blind. Seeking within ONE slot is the mechanism
# hardware has confirmed end to end, so the track index moves out of the
# filesystem and into the file.
#
# Layout, all integers little-endian:
#
#   0x000  64 entries x 8 bytes = 512-byte header
#          entry N: u32 start offset, u32 length   (entry 0 unused, tracks are 1-based)
#   0x200  track data, concatenated in track order
#
# A track with no audio gets offset 0 / length 0, which the core reads as silence.

set -euo pipefail

if [ $# -ne 2 ]; then
    sed -n '2,4p' "$0" | sed 's/^# \?//'
    exit 2
fi

SRC=$1
OUT=$2
HEADER_BYTES=512
MAX_TRACK=62

[ -d "$SRC" ] || { echo "error: pcm dir not found: $SRC" >&2; exit 1; }

tmp_data=$(mktemp)
tmp_hdr=$(mktemp)
trap 'rm -f "$tmp_data" "$tmp_hdr"' EXIT

# Little-endian u32 -> 4 raw bytes
emit_u32() {
    local v=$1
    printf "$(printf '\\x%02x\\x%02x\\x%02x\\x%02x' \
        $((v & 255)) $((v >> 8 & 255)) $((v >> 16 & 255)) $((v >> 24 & 255)))"
}

# Entry 0 is unused - tracks are numbered from 1
emit_u32 0 >> "$tmp_hdr"
emit_u32 0 >> "$tmp_hdr"

cursor=$HEADER_BYTES
present=0
missing=0

for n in $(seq 1 $MAX_TRACK); do
    f=$(printf '%s/track%02d.pcm' "$SRC" "$n")
    if [ -f "$f" ]; then
        len=$(wc -c < "$f")
        emit_u32 "$cursor" >> "$tmp_hdr"
        emit_u32 "$len"    >> "$tmp_hdr"
        cat "$f" >> "$tmp_data"
        printf 'track %02d  offset %10d  length %10d\n' "$n" "$cursor" "$len"
        cursor=$((cursor + len))
        present=$((present + 1))
    else
        emit_u32 0 >> "$tmp_hdr"
        emit_u32 0 >> "$tmp_hdr"
        printf 'track %02d  MISSING - will play as silence\n' "$n"
        missing=$((missing + 1))
    fi
done

# Pad the header out to its full 512 bytes so track data starts where the
# offsets say it does
while [ "$(wc -c < "$tmp_hdr")" -lt "$HEADER_BYTES" ]; do
    emit_u32 0 >> "$tmp_hdr"
done

cat "$tmp_hdr" "$tmp_data" > "$OUT"

echo
echo "tracks packed: $present   missing: $missing"
echo "wrote $OUT ($(wc -c < "$OUT") bytes)"
echo
echo "Copy it to /Assets/genesis/common/Paprium/paprium.pcm on the SD card."
