#!/usr/bin/env bash
#
# pocket: no upstream counterpart, wraps Quartus (local install or the pinned container) and loops the
# ntsc, pal, ntsc_svp and pal_svp variants, keeping a per-variant copy of the reports.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Build with QUARTUS_DIR=/opt/intelFPGA/25.1/quartus for low-level debugging,
# where JTAG is needed: it does not work on 21.1 here.
LOCAL_QUARTUS="${QUARTUS_DIR:-/opt/intelFPGA_lite/21.1/quartus}"

# The toolchain pin, used here and by CI (the compile job in
# .github/workflows/build.yml runs this script), so there is one image to bump.
QUARTUS_IMAGE="${QUARTUS_IMAGE:-docker.io/raetro/quartus:21.1}"

# Rootless podman keeps the build output owned by the invoking user, which the
# bind mount below relies on. Set CONTAINER_RUNTIME=docker on a docker-only host
CONTAINER_RUNTIME="${CONTAINER_RUNTIME:-podman}"

# The svp bitstreams carry Virtua Racing's DSP instead of the save hardware; the
# Chip32 loader picks them by cartridge serial. Their filenames stay under APF's
# 15-character limit for core.json entries.
SPECS=(ntsc:md_ntsc pal:md_pal ntsc_svp:mds_ntsc pal_svp:mds_pal)

# One list: the lookup, the default build order and the closing message all come off it
declare -A BITSTREAM
for spec in "${SPECS[@]}"; do BITSTREAM[${spec%:*}]=${spec#*:}; done

(( $# == 0 )) && set -- "${SPECS[@]%:*}"

"$SCRIPT_DIR/build_loader.sh"

for variant; do
  # :? rejects a typo before Quartus starts, not after a build lands under a name
  # no core.json lists
  out="${BITSTREAM[$variant]:?unknown variant, expected one of: ${SPECS[*]%:*}}.rbf_r"

  if [ -x "$LOCAL_QUARTUS/bin/quartus_sh" ]; then
    echo "=== Starting Quartus build, $variant (local: $LOCAL_QUARTUS) ==="
    cd "$PROJECT_DIR"
    PATH="$LOCAL_QUARTUS/bin:$PATH" quartus_sh -t generate.tcl "$variant"
  else
    echo "=== Starting Quartus build, $variant, via container ($CONTAINER_RUNTIME) ==="
    # generate.tcl creates build_output/ and build_output/reports/ as root
    # inside the container, so every path the host writes to afterwards has to
    # exist first or the write is denied: deploy_bitstream.sh puts the .rbf_r in
    # build_output/, and the per-variant report copy below mkdirs inside
    # build_output/reports/
    mkdir -p "$PROJECT_DIR/build_output/reports/$variant"
    "$CONTAINER_RUNTIME" run --rm \
      -v "$PROJECT_DIR":/build:Z \
      -w /build \
      "$QUARTUS_IMAGE" \
      quartus_sh -t generate.tcl "$variant"
  fi

  echo ""
  echo "=== Build complete, reversing bitstream ==="
  "$SCRIPT_DIR/deploy_bitstream.sh" "" "$out"

  echo ""
  "$SCRIPT_DIR/print_timing.sh" \
    "$PROJECT_DIR/projects/output_files/megadrive_pocket.sta.summary" \
    "$PROJECT_DIR/build_output/reports/megadrive_pocket.sta.clock_summary.rpt"

  # The next variant overwrites both report directories, so keep a copy apart
  mkdir -p "$PROJECT_DIR/build_output/reports/$variant"
  cp -f "$PROJECT_DIR"/projects/output_files/megadrive_pocket.*.rpt \
        "$PROJECT_DIR"/projects/output_files/megadrive_pocket.*.summary \
        "$PROJECT_DIR"/build_output/reports/megadrive_pocket.*.rpt \
        "$PROJECT_DIR/build_output/reports/$variant/"
done

echo "Done"
echo "Bitstreams copied to: pkg/pocket/Cores/*/{$(IFS=,; echo "${SPECS[*]#*:}")}.rbf_r"
