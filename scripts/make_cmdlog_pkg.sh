#!/usr/bin/env bash
# Assemble the command-log DIAGNOSTIC core package into build_output/.
#
#   ./scripts/make_cmdlog_pkg.sh
#
# The diagnostic build needs one thing the shipping package does not: a second
# nonvolatile data slot for the log. That slot is deliberately NOT in the shipping
# data.json - in a shipping build the unloader does not exist, so the slot would
# only ever produce 4 KB of zeros and confuse people.
#
# The package is GENERATED rather than kept in the tree. A second copy of the core
# package living on disk is exactly what caused an old bitstream to be installed
# by mistake once already; build_output/ is disposable and nobody mistakes it for
# the source.
#
# The log slot is id 11 at bridge address 0x30000000, which is where core_top's
# cmdlog data_unloader answers. The save stays at 0x20000000 and is untouched.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

SRC="$PROJECT_DIR/pkg/pocket/Cores/Koala_Koa.Paprium"
OUT="$PROJECT_DIR/build_output/cmdlog-pkg/Cores/Koala_Koa.Paprium"
RBF="$PROJECT_DIR/build_output/paprium_cmdlog.rbf_r"

[ -f "$RBF" ] || {
    echo "error: $RBF not found." >&2
    echo "       quartus_sh -t generate.tcl paprium_cmdlog" >&2
    echo "       python scripts/reverse_bitstream.py \\" >&2
    echo "           projects/output_files/megadrive_pocket.rbf $RBF" >&2
    exit 1
}

rm -rf "$PROJECT_DIR/build_output/cmdlog-pkg"
mkdir -p "$OUT" "$PROJECT_DIR/build_output/cmdlog-pkg/Platforms"

cp -f "$SRC"/*.json "$SRC"/icon.bin "$SRC"/info.txt "$OUT/"
cp -f "$PROJECT_DIR/pkg/pocket/Platforms/paprium.json" \
      "$PROJECT_DIR/build_output/cmdlog-pkg/Platforms/"

# The diagnostic bitstream takes the name core.json already expects
cp -f "$RBF" "$OUT/paprium.rbf_r"

python - "$OUT/data.json" <<'PY'
import collections, io, json, sys

p = sys.argv[1]
d = json.load(io.open(p, encoding='utf-8'), object_pairs_hook=collections.OrderedDict)
slots = d['data']['data_slots']

assert not any(s['id'] == 11 for s in slots), "slot 11 already present"

slots.append(collections.OrderedDict([
    ("name", "Command Log"),
    ("id", 11),
    ("required", False),
    ("parameters", "0x84"),          # same shape as the save slot
    ("nonvolatile", True),
    ("extensions", ["log"]),
    ("address", "0x30000000"),
    ("size_maximum", "0x1000"),
]))

io.open(p, 'w', encoding='utf-8', newline='\n').write(json.dumps(d, indent=2) + "\n")
print("data.json: added slot 11 (Command Log) at 0x30000000, 4 KB")
PY

echo
echo "Diagnostic package: $PROJECT_DIR/build_output/cmdlog-pkg"
echo
echo "Install it over the shipping core:"
echo "  cp -rf build_output/cmdlog-pkg/Cores/Koala_Koa.Paprium/* /d/Cores/Koala_Koa.Paprium/"
echo
echo "The log lands next to the save, as a .log file. Play to a boss, kill it,"
echo "EXIT the core so the slot is flushed, then hand the .log file back."
echo
echo "Restore the shipping core afterwards with:"
echo "  ./scripts/deploy_to_sd.sh /d"
