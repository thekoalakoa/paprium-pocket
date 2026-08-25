#!/usr/bin/env bash
# Reverse the Quartus .rbf for the Pocket and copy it into every core package
# under pkg/pocket/Cores (one bitstream serves all of them).
# Usage: deploy_bitstream.sh [path/to/megadrive_pocket.rbf] [output_name.rbf_r]
# core.json caps a bitstream filename at 15 characters, so the names stay short.
#
# pocket: no upstream counterpart, reverses the .rbf for the Pocket and copies it into every
# core package.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

RBF="${1:-$PROJECT_DIR/projects/output_files/megadrive_pocket.rbf}"
NAME="${2:-md_ntsc.rbf_r}"
RBF_R="$PROJECT_DIR/build_output/$NAME"

mkdir -p "$PROJECT_DIR/build_output"
python3 "$SCRIPT_DIR/reverse_bitstream.py" "$RBF" "$RBF_R"
"$SCRIPT_DIR/install_binaries.sh" "$NAME"
