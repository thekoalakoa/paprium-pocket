#!/usr/bin/env bash
#
# Apply the rulesets in .github/rulesets/ to the GitHub repository.
#
#   ./scripts/apply_github_rulesets.sh           # apply
#   ./scripts/apply_github_rulesets.sh --list    # show what is currently applied
#
# Requires the `gh` CLI, authenticated as an account with admin on the repo:
#
#   winget install GitHub.cli
#   gh auth login                 # you must run this yourself
#
# NOTE ON PLAN: rulesets are free on PUBLIC repositories. On a PRIVATE repository
# they require GitHub Pro / Team / Enterprise, and applying them to a private repo
# on the free plan fails. If that happens, this script says so rather than leaving
# you thinking the repo is protected. See docs/REPO_PROTECTION.md.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
RULESET_DIR="$PROJECT_DIR/.github/rulesets"

command -v gh >/dev/null 2>&1 || {
    echo "error: gh not found. winget install GitHub.cli, then 'gh auth login'." >&2
    exit 1
}
gh auth status >/dev/null 2>&1 || {
    echo "error: gh is not authenticated. Run 'gh auth login' yourself." >&2
    exit 1
}

REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
VIS="$(gh repo view --json visibility -q .visibility)"
echo "repo: $REPO ($VIS)"

if [ "${1:-}" = "--list" ]; then
    echo
    echo "Rulesets currently on the repository:"
    gh api "repos/$REPO/rulesets" \
        --jq '.[] | "  \(.id)  \(.name)  target=\(.target)  \(.enforcement)"' \
        || echo "  (none, or the plan does not expose rulesets)"
    exit 0
fi

if [ "$VIS" != "PUBLIC" ]; then
    echo
    echo "WARNING: this repository is $VIS. Rulesets on a private repository need a"
    echo "paid plan; on the free plan the calls below will fail with 403. That is a"
    echo "plan limit, not a mistake in these files."
    echo
fi

rc=0
for f in "$RULESET_DIR"/*.json; do
    name="$(python -c "import json,sys;print(json.load(open(sys.argv[1]))['name'])" "$f")"
    echo
    echo "--- $name  ($(basename "$f"))"

    existing="$(gh api "repos/$REPO/rulesets" --jq \
        ".[] | select(.name==\"$name\") | .id" 2>/dev/null || true)"

    if [ -n "$existing" ]; then
        echo "    updating existing ruleset $existing"
        gh api -X PUT "repos/$REPO/rulesets/$existing" --input "$f" >/dev/null && \
            echo "    ok" || { echo "    FAILED"; rc=1; }
    else
        echo "    creating"
        gh api -X POST "repos/$REPO/rulesets" --input "$f" >/dev/null && \
            echo "    ok" || { echo "    FAILED"; rc=1; }
    fi
done

echo
if [ "$rc" -eq 0 ]; then
    echo "Applied. Verify with: $0 --list"
else
    echo "One or more failed - see the messages above. Nothing is partially enforced:"
    echo "a ruleset either exists on the repo or it does not."
fi
exit "$rc"
