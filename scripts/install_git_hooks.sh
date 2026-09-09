#!/usr/bin/env bash
#
# Install the repository's git hooks into .git/hooks.
#
# Hooks are not carried by a clone, so this has to be run once per working copy.
# Re-run it after cloning, or after deleting .git/hooks.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

SRC="$PROJECT_DIR/hooks"
DST="$PROJECT_DIR/.git/hooks"

[ -d "$SRC" ] || { echo "error: no hooks/ directory at $SRC" >&2; exit 1; }
[ -d "$DST" ] || { echo "error: no .git/hooks - is this a git working copy?" >&2; exit 1; }

for hook in "$SRC"/*; do
    name="$(basename "$hook")"
    target="$DST/$name"

    if [ -e "$target" ] && ! cmp -s "$hook" "$target"; then
        cp -f "$target" "$target.replaced"
        echo "  kept your existing $name as $name.replaced"
    fi

    cp -f "$hook" "$target"
    chmod +x "$target"
    echo "installed $name"
done

echo
echo "Active hooks:"
for hook in "$SRC"/*; do
    name="$(basename "$hook")"
    [ -x "$DST/$name" ] && echo "  $name  (executable)" || echo "  $name  NOT EXECUTABLE"
done
