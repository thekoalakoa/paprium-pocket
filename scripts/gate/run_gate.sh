#!/usr/bin/env bash
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
# run_gate.sh - the fit gate of the 0.3.0 new core on one seed (see scripts/gate/README.md for how to use it).
#
#   scripts/gate/run_gate.sh <projects dir of a COPY of the fitted tree> <out dir> [--profile s1|026] [--post-map]
#
# Read only on the database, but quartus_sta writes into the project it opens, so always point it at a COPY
# (platform/, target/, projects/{db,incremental_db,output_files,*.qpf,*.qsf}); the copy's qpf / qsf are restored
# after every run. One quartus_sta at a time: each run waits until no quartus process is left on the machine.
# Steps: the five STA scripts (xcheck, census, vidsta, queries, sdram_sta; ~1 min each), then the judges (gate.py,
# census_gate.py, vidsta_gate.py, queries_gate.py, sdpins_gate.py, sdram_gate.py). Exit 0 only when every judge passes.
# --post-map: a mapped (not fitted) database: collections and structure only (no sdram_sta, no sdpins, no slacks).
# --profile 026: the 0.2.6 collection list (to run the tools on a 0.2.x fit; the new core's rules then fail by design).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
[ $# -ge 2 ] || { sed -n '2,15p' "$0" | sed 's/^# \?//'; exit 2; }
P="$(cd "$1" && pwd)"; OUT="$2"; shift 2
PROFILE=s1; POSTMAP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --post-map) POSTMAP=1; shift ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
done
mkdir -p "$OUT"; OUT="$(cd "$OUT" && pwd)"
Q="${QUARTUS_BIN:-/c/intelFPGA_lite/21.1/quartus/bin64}"
PY="${PYTHON:-python} -I -B"
w() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else echo "$1"; fi; }
[ -f "$P/megadrive_pocket.qpf" ] || { echo "no megadrive_pocket.qpf in $P"; exit 2; }

quartus_count() {
  if command -v powershell >/dev/null 2>&1; then
    powershell -NoProfile -Command '@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match "^quartus" }).Count' | tr -dc '0-9'
  else
    pgrep -c '^quartus' || true
  fi
}
slot() {   # wait until no quartus process runs, checked twice; kills nothing
  while true; do
    n=$(quartus_count); [ "${n:-0}" = 0 ] && { sleep 4; n=$(quartus_count); [ "${n:-0}" = 0 ] && return; }
    sleep 15
  done
}
mkdir -p "$OUT/snap"
cp "$P/megadrive_pocket.qpf" "$P/megadrive_pocket.qsf" "$OUT/snap/"
sta() {    # sta <name> <script> <args...>
  local name=$1 tcl=$2; shift 2
  slot
  echo "$(date '+%F %T') quartus_sta $name"
  ( cd "$P" && "$Q/quartus_sta.exe" -t "$(w "$HERE/$tcl")" "$@" > "$OUT/$name.log" 2>&1 )
  local rc=$?
  cp "$OUT/snap/megadrive_pocket.qpf" "$OUT/snap/megadrive_pocket.qsf" "$P/"
  [ $rc = 0 ] || echo "  quartus_sta $name exited $rc (see $name.log)"
}

OF="$P/output_files"
for f in sta.summary fit.summary fit.rpt sta.rpt map.summary; do
  [ -f "$OF/megadrive_pocket.$f" ] && cp "$OF/megadrive_pocket.$f" "$OUT/$f"
done
PM=""; [ $POSTMAP = 1 ] && PM=post_map
sta xcheck  xcheck.tcl  "$(w "$OUT/xcheck.txt")" $PROFILE $PM
sta census  census.tcl  "$(w "$OUT/census.txt")" 0.3 $PM
sta vidsta  vidsta.tcl  "$(w "$OUT/vidsta.tsv")" $PM
sta queries queries.tcl "$(w "$OUT/queries.txt")" $PM
if [ $POSTMAP = 0 ]; then
  # Part 2's session constraint needs the core SDC without the SDRAM pad-budget block (it would override it)
  SDC="$P/../target/pocket/core_constraints.sdc"
  awk 'BEGIN{skip=0} /^# pocket \(0\.3\.0\): SDRAM pad budgets/{skip=1} { if (!skip) print } skip && /^# pocket-end/{skip=0}' \
      "$SDC" > "$OUT/core_constraints_nov5.sdc"
  sta sdram_sta sdram_sta.tcl "$(w "$OUT/sdram_sta.txt")" "$(w "$OUT/core_constraints_nov5.sdc")"
fi

declare -a NAMES RCS
judge() {  # judge <name> <command...>
  local name=$1; shift
  "$@" > "$OUT/$name.verdict.txt" 2>&1
  local rc=$?
  NAMES+=("$name"); RCS+=($rc)
}
LOGS=("$(w "$OUT/xcheck.log")" "$(w "$OUT/census.log")" "$(w "$OUT/vidsta.log")" "$(w "$OUT/queries.log")")
if [ $POSTMAP = 1 ]; then
  judge gate        $PY "$(w "$HERE/gate.py")" --xcheck "$(w "$OUT/xcheck.txt")" --profile $PROFILE --collections-only --log "${LOGS[@]}"
  judge census      $PY "$(w "$HERE/census_gate.py")" "$(w "$OUT/census.txt")" --profile $PROFILE --structure-only
  judge vidsta      $PY "$(w "$HERE/vidsta_gate.py")" "$(w "$OUT/vidsta.tsv")" --structure-only
  judge queries     $PY "$(w "$HERE/queries_gate.py")" "$(w "$OUT/queries.txt")" --collections-only --profile $PROFILE
else
  [ -f "$OUT/sta.rpt" ] && LOGS+=("$(w "$OUT/sta.rpt")")
  [ -f "$OUT/fit.rpt" ] && LOGS+=("$(w "$OUT/fit.rpt")")
  judge gate        $PY "$(w "$HERE/gate.py")" --summary "$(w "$OUT/sta.summary")" --xcheck "$(w "$OUT/xcheck.txt")" \
                        --profile $PROFILE --log "${LOGS[@]}" "$(w "$OUT/sdram_sta.log")"
  judge census      $PY "$(w "$HERE/census_gate.py")" "$(w "$OUT/census.txt")" --json "$(w "$OUT/census.json")" --profile $PROFILE
  judge vidsta      $PY "$(w "$HERE/vidsta_gate.py")" "$(w "$OUT/vidsta.tsv")"
  judge queries     $PY "$(w "$HERE/queries_gate.py")" "$(w "$OUT/queries.txt")" --profile $PROFILE
  judge sdpins      $PY "$(w "$HERE/sdpins_gate.py")" "$(w "$OUT/fit.rpt")"
  judge sdram       $PY "$(w "$HERE/sdram_gate.py")" "$(w "$OUT/sdram_sta.txt")"
fi
fail=0
echo "G1 gate, $(date '+%F %T'), $P (profile $PROFILE$([ $POSTMAP = 1 ] && echo ', post-map'))" > "$OUT/G1.txt"
for i in "${!NAMES[@]}"; do
  v=PASS; [ "${RCS[$i]}" = 0 ] || { v="FAIL (exit ${RCS[$i]})"; fail=1; }
  printf '  %-8s %s   %s\n' "${NAMES[$i]}" "$v" "$(tail -1 "$OUT/${NAMES[$i]}.verdict.txt")" >> "$OUT/G1.txt"
done
echo "G1: $([ $fail = 0 ] && echo PASS || echo FAIL)" >> "$OUT/G1.txt"
cat "$OUT/G1.txt"
exit $fail
