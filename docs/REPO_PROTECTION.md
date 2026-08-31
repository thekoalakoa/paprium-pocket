# Repository protection

Goal: nobody force-pushes or deletes this work, deliberately or by accident.

There are two layers, and they cover different things. Neither is a substitute for
the other.

## What each layer actually covers

    GitHub ruleset   server side, applies to every clone and every person
                     .github/rulesets/*.json, applied with
                     scripts/apply_github_rulesets.sh

    pre-push hook    this machine only, and skippable with --no-verify
                     hooks/pre-push, installed with scripts/install_git_hooks.sh

## The plan gate, which decides the order of work

**Rulesets are free on public repositories. On a private repository they require
GitHub Pro, Team or Enterprise.** This repository is currently private, so
applying the rulesets may fail with a 403 until it is made public (or the account
is on a paid plan).

That is the reason the ruleset definitions are committed as files rather than
applied and forgotten: they are ready to fire the moment the repository goes
public, and applying them is one command.

    ./scripts/apply_github_rulesets.sh --list     # what is applied now
    ./scripts/apply_github_rulesets.sh            # apply

`gh` must be installed and authenticated first, and **you have to run
`gh auth login` yourself** - it is a credential step.

## What a ruleset cannot do

**It cannot stop the repository being deleted.** Rulesets protect *branches* and
*tags*, not the repository. On a personal account the owner can always delete the
repository; GitHub's only guard is the typed-name confirmation. Nothing here
changes that, so do not read "protected" as "undeletable".

Repository deletion can only be restricted by an *organisation* policy. Moving the
repository into an organisation you own is the way to get that, and it is
orthogonal to everything else in this file.

## The rulesets

`master-protection.json` - on the default branch:

    deletion          the branch cannot be deleted
    non_fast_forward  no force-push; history cannot be rewritten

`tag-protection.json` - on `refs/tags/v*`, so a published release tag cannot be
deleted or moved to a different commit. This matters more once releases exist:
a moved tag means someone's "v1.0" is not the v1.0 you built.

### On bypass actors

Both ship with `"bypass_actors": []` - **nobody bypasses, including the owner.**

That is deliberate, and it is stricter than "let admins through". The realistic
risk on a solo repository is not a hostile collaborator, it is a mistaken
force-push by the one person with access. An admin bypass would let exactly that
through, which defeats the point.

The rule is not a cage: to do something the ruleset forbids, set its enforcement
to `disabled` in the repository settings, do the thing, and turn it back on. That
is deliberate and visible, which is what you want for an irreversible operation.

To allow admins through anyway, in both files:

    "bypass_actors": [
      { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always" }
    ]

## The local hook

`hooks/pre-push` refuses, for `master` and `main` only:

- deleting the remote branch
- any non-fast-forward push, reporting how many commits would become unreachable

It allows normal pushes, and allows force-pushing topic branches, because
rebasing a topic branch loses nothing.

Hooks are not carried by a clone, so run this once per working copy:

    ./scripts/install_git_hooks.sh

It is skippable with `git push --no-verify`, by design - a guard against a slip,
not against intent.

## Before making the repository public

Checked 2026-08-31, all clean:

- **no game data in history.** The largest blobs ever committed are revisions of
  `docs/PORT_PLAN.md`. No ROM, no `.pcm`, no saves, no wave bank
- **no ROM links.** No `archive.org` reference in any commit, which is the
  standing rule - the ROM must not be linked from core metadata or docs
- **no credential-shaped strings** in the tree

Re-run those checks if history is ever rewritten:

    git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | awk '$1=="blob" {print $3, $4}' | sort -rn | head

One item was a judgement call rather than a check, and it has been decided:
`pkg/pocket/Platforms/_images/paprium.bin` is the core's platform artwork, derived
from WaterMelon key art. The full-resolution source was deliberately removed from
the repository on the same principle that keeps the ROM out; the downscaled
platform image is **kept** - decided 2026-08-31 - because the core needs it to
display and it is the artwork in its functional form rather than a redistributable
copy of the original.
