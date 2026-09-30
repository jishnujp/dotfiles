---
name: weekend-cleanup
description: Weekly housekeeping for the devbox and agent context. Removes T3 worktrees whose PR is merged or whose T3 thread is settled, and prunes Claude memory down to what is still relevant. Use when the user asks for the weekend or weekly cleanup, to clean up worktrees or workspaces, or to clean memory and free context space.
---

# Weekend cleanup

Two jobs: remove finished worktrees, then prune memory. The script `cleanup.py` next to this file does the mechanical survey and the removal. Memory pruning is judgement, so it stays with you.

Nothing here deletes a branch, a report folder, or a running service. Uncommitted work is stashed before its worktree goes. Stop and ask before anything outside those rules.

## 1. Worktrees

```bash
S=~/.claude/skills/weekend-cleanup/cleanup.py
$S worktrees            # read-only report
```

It covers every git worktree of every T3 project. It fetches each repo and checks the branch's PR with `gh`, the T3 thread state (read-only from `~/.t3/userdata/state.sqlite`), running compose stacks and processes. Each worktree gets one verdict:

- **REMOVE**: the PR is merged, or every T3 thread on it is settled or archived, or it is a detached copy whose HEAD is on another branch. Dirty files get stashed, and processes older than 24 hours get stopped.
- **BLOCKED**: it would be REMOVE, but a docker compose project runs from it or a process younger than 24 hours uses it. Report these rows. Take a stack down only if the user says so (`docker compose down` in that directory), then re-run.
- **REVIEW**: a merged PR with local commits after it, or a worktree with no thread and no PR. Look at it and ask the user.
- **KEEP**: there is an open PR or an active thread, or the worktree is outside `~/.t3/worktrees`.
- **ORPHAN**: a folder in `~/.t3/worktrees` that git does not know about. Check what is in it before removing it by hand.

Read the report. Once the REMOVE rows look right, run:

```bash
$S worktrees --apply
```

This acts on REMOVE rows only. The branches stay, so nothing committed is lost. Every stash is labelled `worktree-cleanup <date>: uncommitted work from <dir> (<branch>)`. Note each stash in the project's `open-loose-ends` memory so it is not forgotten.

## 2. Memory

```bash
$S memory               # every ~/.claude/projects/*/memory with a MEMORY.md
```

It lists index problems (missing files, unindexed files, dangling `[[links]]`) and each entry's age, type and size. Then, for each memory directory with more than a handful of entries (the horus one above all), read the entries and sort them:

- **Keep as they are**: `feedback` and `user` entries, credentials the owner asked to keep, and facts about live systems (prod topology, boxes that are running, AWS layout).
- **Fold into `past-work-index`**: finished studies, merged PRs and closed arcs. Each becomes one line with its date, its report folder under `~/recommendly` and its headline result. Then delete the entry. Merged work whose code is in git needs no more than one line in the index.
- **Fold into `open-loose-ends`**: any pending item buried in an entry you are deleting ("not yet", "still open", "pending", "remove when done"). Drop loose ends that are now done. Check before deciding: `gh pr view`, `git log origin/main`, whether a container is still running.
- **Delete outright**: recipes for machines, stacks or tunnels that no longer exist, and status snapshots superseded by a newer entry.

Before you rely on a fact to keep or drop something, check it (a file, a port, a PR state). Update an entry that has drifted instead of keeping it stale.

Afterwards:
- Repoint `[[links]]` to deleted entries at `[[past-work-index]]`.
- Rewrite `MEMORY.md`: grouped by topic, one line per entry, no content.
- Re-run `$S memory` and confirm it prints no PROBLEM lines.

Keep `MEMORY.md` well under 5 KB. It is loaded into every session.

## 3. Leave alone

- Report and data folders in `~/recommendly` and elsewhere. They cost disk, not context, and the `:8091` report pages are served from them. You may list large or old ones for the user.
- Remote boxes (gpu*, horus-test-box, prod), docker volumes and images, and git branches. Offer, never do.

## 4. Report

Start with the outcome, for example "Removed N worktrees; memory went from A to B entries." Then list:

- worktrees removed, with the reason for each (PR number or settled thread)
- every stash created
- BLOCKED and REVIEW rows with what the user needs to decide
- memory entries deleted, folded or updated
- disk before and after (`df -h ~`)
