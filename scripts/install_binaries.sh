#!/usr/bin/env bash
# Copy build products out of build_output into every core package under
# pkg/pocket/Cores (one set of binaries serves all of them).
# Usage: install_binaries.sh [name ...]
# Default: every bitstream core.json names, plus loader.bin
#
# pocket: no upstream counterpart. Split out of deploy_bitstream.sh because CI compiles one
# variant per job and the packaging job rebuilds the tree from downloaded artifacts, where
# there is no .rbf left to reverse and the bitstreams arrive one at a time.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR/build_output"

if (( $# == 0 )); then
  # The list check_packages.sh and package_release.sh already work off, rather
  # than whatever happens to be lying in build_output: a variant that was never
  # compiled then fails the cp below instead of going quietly missing from the zip.
  mapfile -t bins < <(jq -r '.core.cores[].filename' "$PROJECT_DIR"/pkg/pocket/Cores/*/core.json | sort -u)
  set -- "${bins[@]}"
  # A literal rather than a name out of core.json, so it needs its own test: the
  # core builds without a loader if support/loader.asm is gone, which
  # check_packages.sh tolerates too.
  if [ -f loader.bin ]; then
    set -- "$@" loader.bin
  fi
fi

if (( $# == 0 )); then
  echo "install_binaries.sh: no core.json names a bitstream to install" >&2
  exit 1
fi

for name; do
  for d in "$PROJECT_DIR"/pkg/pocket/Cores/*/; do
    cp -f "$name" "$d/$name"
    echo "$name -> ${d#"$PROJECT_DIR/"}$name"
  done
done
