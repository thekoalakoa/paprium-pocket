#!/usr/bin/env bash
# Build the Paprium CDDA track set for the Pocket core.
#
# The core streams headerless 48 kHz 16-bit stereo little-endian PCM, named by
# CUE TRACK NUMBER (see docs/CDDA_DESIGN.md for why). This script resolves the
# cue's track-to-file mapping and emits track01.pcm .. trackNN.pcm.
#
#   ./scripts/build_cdda.sh <source-dir> <paprium.cue> <output-dir>
#
# <source-dir> holds the OST as MP3, WAV, FLAC, whatever ffmpeg reads. Files are
# matched to cue entries by their LEADING TWO-DIGIT NUMBER, not by title, so a
# rip whose titles differ slightly still works and .mp3 substitutes for the
# .wav the cue names.
#
# Requires ffmpeg on PATH.

set -euo pipefail

if [ $# -ne 3 ]; then
    sed -n '2,17p' "$0" | sed 's/^# \?//'
    exit 2
fi

SRC=$1
CUE=$2
OUT=$3

command -v ffmpeg >/dev/null 2>&1 || {
    echo "error: ffmpeg not found on PATH." >&2
    echo "       Install it (winget install Gyan.FFmpeg) and re-run." >&2
    exit 1
}
[ -d "$SRC" ] || { echo "error: source dir not found: $SRC" >&2; exit 1; }
[ -f "$CUE" ] || { echo "error: cue not found: $CUE" >&2; exit 1; }

mkdir -p "$OUT"

# Walk the cue. Entries pair up as:
#   FILE "01 Theme of Paprium.wav" WAVE
#     TRACK 01 AUDIO
# so remember the most recent FILE and bind it to the next TRACK number.
pending_file=""
converted=0
silent=0
missing=0
missing_list=""

while IFS= read -r line; do
    case "$line" in
        FILE\ *)
            # strip to the quoted filename, then to its leading digits
            name=${line#FILE \"}
            pending_file=${name%%\"*}
            ;;
        *TRACK\ *)
            [ -n "$pending_file" ] || continue
            track=$(printf '%s\n' "$line" | sed -n 's/.*TRACK *\([0-9][0-9]*\).*/\1/p')
            [ -n "$track" ] || continue

            out_file=$(printf '%s/track%02d.pcm' "$OUT" "$((10#$track))")
            prefix=$(printf '%s\n' "$pending_file" | sed -n 's/^\([0-9][0-9]*\).*/\1/p')

            # Ten cue entries point at "Blank.wav" rather than a numbered track -
            # these are deliberate silent placeholders (tracks 08 09 10 13 26 31
            # 41 44 45 48). They still have to exist, or the core would report a
            # missing track where the game expects a real, silent one. Zero-filled
            # PCM is silence, so no decoder is involved.
            if [ -z "$prefix" ]; then
                dd if=/dev/zero of="$out_file" bs=192000 count=1 status=none
                silent=$((silent + 1))
                printf 'track %02d  <- silence  (cue: %s)\n' \
                    "$((10#$track))" "$pending_file"
                pending_file=""
                continue
            fi

            # find any source file starting with the same number
            src_file=""
            for cand in "$SRC/$prefix"*; do
                [ -f "$cand" ] || continue
                src_file=$cand
                break
            done

            if [ -z "$src_file" ]; then
                missing=$((missing + 1))
                missing_list="$missing_list $prefix"
                printf 'track %02d  MISSING source %s* (cue: %s)\n' \
                    "$((10#$track))" "$prefix" "$pending_file"
            else
                ffmpeg -loglevel error -y -i "$src_file" \
                    -f s16le -acodec pcm_s16le -ar 48000 -ac 2 \
                    "$out_file"
                converted=$((converted + 1))
                printf 'track %02d  <- %s  (%s bytes)\n' \
                    "$((10#$track))" "$(basename "$src_file")" \
                    "$(wc -c < "$out_file")"
            fi
            pending_file=""
            ;;
    esac
done < "$CUE"

echo
echo "converted: $converted"
echo "silent:    $silent  (Blank.wav placeholders the cue asks for)"
if [ "$missing" -gt 0 ]; then
    echo "missing:   $missing tracks, source numbers:$(printf '%s' "$missing_list" | tr ' ' '\n' | sort -un | tr '\n' ' ')"
    echo
    echo "The core treats a missing track as silence rather than hanging, so an"
    echo "incomplete set still boots - those cues just play nothing."
    exit 3
fi
echo "complete set written to $OUT"
