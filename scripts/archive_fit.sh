#!/usr/bin/env bash
# Snapshot a build's fit/timing numbers so later builds can be compared against it.
#
#   ./scripts/archive_fit.sh <label>        e.g. probeb2, shipping, cmdlog-sfx
#
# WHY: a diagnostic build must be judged against the last one that BOOTED, not
# against the shipping build - cmdlog starts at ~98% before any instrumentation is
# added, so shipping's free ALMs are not diagnostic budget. That comparison is only
# possible if the numbers survive, and Quartus overwrites its reports every build.
# This has already cost one wasted round: Probe B was judged against shipping,
# installed, and broke at boot.
set -euo pipefail
D="$(cd "$(dirname "$0")/.." && pwd)"
[ $# -eq 1 ] || { sed -n '2,12p' "$0" | sed 's/^# \?//'; exit 2; }
OUT="$D/build_output/fits"; mkdir -p "$OUT"
F="$D/projects/output_files/megadrive_pocket.fit.rpt"
S="$D/projects/output_files/megadrive_pocket.sta.rpt"
{
  echo "== $1 =="
  awk '/^; Fitter Summary/,/^\+=+\+$/' "$F" | grep -E "Fitter Status|Logic utilization \(in ALMs\)|Total RAM Blocks|Total registers"
  grep -E "Worst-case Slack|Design-wide TNS" "$S" | head -2
} | tee "$OUT/$1.txt"
