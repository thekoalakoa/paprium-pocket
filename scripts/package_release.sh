#!/usr/bin/env bash
# Usage: package_release.sh <version> [infix]
#   infix lands before the version: openfpga-<shortname>_<infix>_<version>.zip
#
# One zip per platform core, each holding only that platform's Cores/<pkg>/,
# Platforms/<id>.json and Assets/<id>/. Pupdate maps each core to the single
# zip it was found in, so a combined zip would drop every Cores/ folder on the
# SD card when one platform is installed. Prints the zip names on stdout.
#
# pocket: no upstream counterpart, one zip per platform core, because Pupdate maps each core to
# the single zip it was found in.
set -euo pipefail

VERSION="${1:?usage: package_release.sh <version> [infix]}"
INFIX="${2:-}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

for core_json in "$PROJECT_DIR"/pkg/pocket/Cores/*/core.json; do
  pkgdir="$(basename "$(dirname "$core_json")")"               # author.SHORT
  shortname="$(jq -r '.core.metadata.shortname' "$core_json")" # SHORT
  pid="$(jq -r '.core.metadata.platform_ids[0]' "$core_json")" # platform id

  # zip exits 0 (warning only) when an argument doesn't match, so a drifted or
  # missing shortname/platform mapping would silently ship an incomplete zip.
  # Validate the coupling up front and fail loud instead.
  for field in shortname pid; do
    case "${!field}" in
      '' | null) echo "$pkgdir: core.json .core.metadata.$field is missing" >&2; exit 1 ;;
    esac
  done
  [ -f "$PROJECT_DIR/pkg/pocket/Platforms/${pid}.json" ] || {
    echo "$pkgdir: missing pkg/pocket/Platforms/${pid}.json for platform '$pid'" >&2; exit 1; }
  # No Platforms/_images/<id>.bin check: this core ships no platform artwork on
  # purpose, see "Installation" in the README.
  [ -d "$PROJECT_DIR/pkg/pocket/Assets/${pid}" ] || {
    echo "$pkgdir: missing pkg/pocket/Assets/${pid}/ for platform '$pid'" >&2; exit 1; }
  # The svp bitstreams build last, so an interrupted build leaves fresh md_* next
  # to absent mds_*; the zip would ship anyway and the Pocket only fails when the
  # loader picks the missing variant. Require every core.json bitstream up front.
  for rbf in $(jq -r '.core.cores[].filename' "$core_json"); do
    [ -f "$PROJECT_DIR/pkg/pocket/Cores/${pkgdir}/${rbf}" ] || {
      echo "$pkgdir: core.json references missing bitstream '$rbf'" >&2; exit 1; }
  done

  # ${INFIX:+_$INFIX} adds the _<infix> segment only when INFIX is non-empty.
  zip_name="openfpga-${shortname}${INFIX:+_$INFIX}_${VERSION}.zip"
  zip_path="$PROJECT_DIR/$zip_name"

  rm -f "$zip_path"
  # Run from pkg/pocket/ so the archive's paths are SD-card-root relative.
  # -x '*/.gitkeep' drops the empty-dir marker but keeps Assets/<id>/common/.
  # The Pocket shows Platforms/_images/<id>.bin next to the platform name. It was
  # missing from the archive until 0.1.0, so a release install had no artwork.
  PLAT_IMG=""
  [ -f "$PROJECT_DIR/pkg/pocket/Platforms/_images/${pid}.bin" ] &&     PLAT_IMG="Platforms/_images/${pid}.bin"

  # Git for Windows ships no `zip`, so fall back to a Python zipper that writes
  # the same layout. A release should not depend on which shell is installed.
  if command -v zip >/dev/null 2>&1; then
    ( cd "$PROJECT_DIR/pkg/pocket" &&       zip -r "$zip_path"         "Cores/${pkgdir}" "Platforms/${pid}.json" ${PLAT_IMG:+"$PLAT_IMG"} "Assets/${pid}"         -x '*/.gitkeep' ) >&2
  else
    ( cd "$PROJECT_DIR/pkg/pocket" &&       python "$SCRIPT_DIR/_zip_fallback.py" "$zip_path"         "Cores/${pkgdir}" "Platforms/${pid}.json" ${PLAT_IMG:+"$PLAT_IMG"} "Assets/${pid}" ) >&2
  fi

  echo "$zip_name"
done
