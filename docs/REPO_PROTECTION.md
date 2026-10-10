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
GitHub Pro, Team or Enterprise.** This repository is public, so both rulesets are
applied and active.

The ruleset definitions are committed as files rather than applied and forgotten:
the files are the record of what is enforced, and re-applying them after an edit
is one command.

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

`tag-protection.json` - on every tag (`refs/tags/*`; the release tags are `0.x.y`,
with no `v`), so a published release tag cannot be deleted or moved to a different
commit:

    deletion          the tag cannot be deleted
    update            the tag cannot be re-pointed, forward or backward
    non_fast_forward  no force-push of the tag

Creating a new tag is not restricted, so a new release still tags as usual. A moved
tag means someone's "0.2.5" is not the 0.2.5 you built.

### On bypass actors

`master-protection.json` ships with `"bypass_actors": []` - **nobody bypasses,
including the owner.** `tag-protection.json` lets the repository admin role
through (`actor_id` 5), so the owner can still repair a tag without switching the
ruleset off.

The branch rule is deliberate, and it is stricter than "let admins through". The realistic
risk on a solo repository is not a hostile collaborator, it is a mistaken
force-push by the one person with access. An admin bypass would let exactly that
through, which defeats the point.

The rule is not a cage: to do something the ruleset forbids, set its enforcement
to `disabled` in the repository settings, do the thing, and turn it back on. That
is deliberate and visible, which is what you want for an irreversible operation.

To allow admins through on the branch too, in `master-protection.json`:

    "bypass_actors": [
      { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always" }
    ]

## The local hook

`hooks/pre-push` refuses, for `master` and `main` only:

- deleting the remote branch
- any non-fast-forward push, reporting how many commits would become unreachable

and, on every branch and tag pushed, any added line (binary files included) that
names a local home directory - see "no local home paths" below.

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

Added 2026-10: **no local home paths.** Build logs and two scripts had carried the
author's Windows home directory in absolute paths. The history was rewritten to
replace that prefix with `<HOME>` (the rest of each path is kept), so the commit
IDs from the first affected commit onward changed, and commit IDs quoted in old
commits refer to the old history. Check every commit with (the revisions go
through xargs because a long history overflows the Windows command line):

    git rev-list --all | xargs git grep -n -I -i -E '([a-z]:[\\/]+|(^|[^a-z0-9_.~-])/(mnt/)?([a-z]/)?)users[\\/]+[^\\/[:space:]"<>]|[a-z]--users-[a-z0-9]' | head

and the release zips before uploading them (`-a`: binaries too):

    unzip -o -q <release>.zip -d /tmp/relcheck && grep -r -a -i -l -E 'users[\\/]+[^\\/<[:space:]]|[a-z]--users-' /tmp/relcheck

One item was a judgement call rather than a check, and it has since been overtaken
by a better answer. `pkg/pocket/Platforms/_images/paprium.bin` was originally
generated from WaterMelon key art: the full-resolution source was deliberately kept
out of the repository on the same principle that keeps the ROM out, and the
downscaled platform image was **kept** - decided 2026-08-31 - as the artwork in its
functional form rather than a redistributable copy.

**That no longer describes the shipped file.** Since `dc8daec` the platform image
has been original artwork drawn for this core by LemonGrwab, replaced again at
0.2.5 (`fdc1c5a`) with their updated banner. So the repository carries no
game-derived artwork at all, and the judgement above now applies only to the
history. `scripts/make_platform_logo.py`, which produced the key-art version,
remains in the tree and its output is not shipped.
