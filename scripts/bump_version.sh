#!/usr/bin/env bash
# Usage: bump_version.sh <patch|minor|major>
#
# Bumps every core.json and gateware.json in lockstep, since sibling packages
# share one bitstream and release together, and prints the new version.
#
# pocket: no upstream counterpart, bumps core.json and gateware.json in lockstep, since they
# release together.
set -euo pipefail

BUMP="${1:?usage: bump_version.sh <patch|minor|major>}"
case "$BUMP" in
  patch | minor | major) ;;
  *) echo "bump_version.sh: unknown bump type '$BUMP' (want patch|minor|major)" >&2; exit 1 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

set -- "$PROJECT_DIR"/pkg/pocket/Cores/*/core.json
CURRENT="$(jq -r '.core.metadata.version' "$1")"
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"

case "$BUMP" in
  major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
  minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  patch) PATCH=$((PATCH + 1)) ;;
esac

NEW="${MAJOR}.${MINOR}.${PATCH}"
DATE="$(date -u +%Y-%m-%d)"

for f in "$PROJECT_DIR"/pkg/pocket/Cores/*/core.json; do
  jq --arg v "$NEW" --arg d "$DATE" \
    '.core.metadata.version = $v | .core.metadata.date_release = $d' \
    "$f" > "$f.tmp" && mv "$f.tmp" "$f"
done

GATEWARE="$PROJECT_DIR/gateware.json"
if [ -f "$GATEWARE" ]; then
  jq --arg v "$NEW" '.version = $v' "$GATEWARE" > "$GATEWARE.tmp" && mv "$GATEWARE.tmp" "$GATEWARE"
fi

echo "Bumped $CURRENT -> $NEW" >&2
echo "$NEW"
