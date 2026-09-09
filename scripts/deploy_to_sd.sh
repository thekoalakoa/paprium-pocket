#!/usr/bin/env bash
# Copy the whole Paprium core package to a Pocket SD card.
#
#   ./scripts/deploy_to_sd.sh /d            (Windows drive D:, via Git Bash)
#   ./scripts/deploy_to_sd.sh /Volumes/POCKET
#
# Copies the ENTIRE core directory rather than named files. The menu lives in
# interact.json, the display modes in video.json and the logic in paprium.rbf_r,
# so copying only the bitstream leaves a stale menu that looks like the build
# failed to take - which has happened, twice. Copying the directory removes the
# chance of forgetting one.
#
# Assets are NOT touched: your ROM and paprium.pcm stay where they are.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

CORE_SRC="$PROJECT_DIR/pkg/pocket/Cores/Koala_Koa.Paprium"
PLAT_SRC="$PROJECT_DIR/pkg/pocket/Platforms/paprium.json"
IMG_SRC="$PROJECT_DIR/pkg/pocket/Platforms/_images/paprium.bin"

if [ $# -ne 1 ]; then
    sed -n '2,9p' "$0" | sed 's/^# \?//'
    exit 2
fi

SD=${1%/}

[ -d "$SD" ]        || { echo "error: no such path: $SD" >&2; exit 1; }
[ -d "$SD/Cores" ]  || { echo "error: $SD has no Cores/ - is that the card root?" >&2; exit 1; }
[ -d "$CORE_SRC" ]  || { echo "error: core package not found: $CORE_SRC" >&2; exit 1; }

if [ ! -f "$CORE_SRC/paprium.rbf_r" ]; then
    echo "error: no paprium.rbf_r in the package - build first, then" >&2
    echo "       cp build_output/paprium.rbf_r $CORE_SRC/" >&2
    exit 1
fi

mkdir -p "$SD/Cores/Koala_Koa.Paprium" "$SD/Platforms/_images" "$SD/Assets/paprium/common"

cp -f "$CORE_SRC"/* "$SD/Cores/Koala_Koa.Paprium/"
cp -f "$PLAT_SRC"   "$SD/Platforms/"
[ -f "$IMG_SRC" ] && cp -f "$IMG_SRC" "$SD/Platforms/_images/"

echo "Installed to $SD:"
ls -la "$SD/Cores/Koala_Koa.Paprium/" | tail -n +2

echo
echo "Menu the core will show:"
python - "$SD/Cores/Koala_Koa.Paprium/interact.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for v in d['interact']['variables']:
    opts = ', '.join(o['name'] for o in v.get('options', []))
    print('  %-30s %s' % (v['name'], opts))
PY

echo
echo "Assets left untouched. Expected in $SD/Assets/paprium/common/ :"
ls -la "$SD/Assets/paprium/common/" 2>/dev/null | tail -n +2 || echo "  (empty - the ROM goes here)"

echo
echo "Region is latched at boot: fully EXIT the core and relaunch, do not soft reset."
