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
# Git for Windows has no `python3`; the Windows launcher stub that answers to
# that name prints a Microsoft Store advert and exits 9009. Because the stub
# "succeeds" as far as a bare call is concerned, the reverse step was skipped
# silently and build_output/ kept the PREVIOUS bitstream - a fit that appears
# to have landed while the card still holds the old one. Pick an interpreter
# that actually runs, and fail loudly if none does.
PY=""
for cand in python3 python py; do
  if "$cand" -c "import sys" >/dev/null 2>&1; then PY="$cand"; break; fi
done
[ -n "$PY" ] || { echo "no working python found (tried python3, python, py)" >&2; exit 1; }
"$PY" "$SCRIPT_DIR/reverse_bitstream.py" "$RBF" "$RBF_R"
"$SCRIPT_DIR/install_binaries.sh" "$NAME"
