---
name: create-pr
description: Open a GitHub pull request for the current work, or refresh the description of one that already exists. Use when the user asks to create, open, or raise a PR, to "commit, push and PR", or to update a PR description after its scope changed. Covers branching off the default branch, committing, verifying, pushing, writing the description, and `gh pr create`.
---

# Create a pull request

Asking for a pull request authorizes committing the work and pushing its branch. It does not authorize force pushing, merging, or pushing to the default branch. The commit and force-push rules in the global instructions apply throughout.

## 1. Survey

Run these before changing anything:

```bash
git status --short
git branch --show-current
base=$(timeout 30 gh repo view --json defaultBranchRef -q .defaultBranchRef.name)
timeout 30 git fetch origin "$base"
git log --oneline "origin/$base..HEAD"
timeout 30 gh pr view --json url,state,isDraft 2>/dev/null   # is there already a PR for this branch?
```

If an open PR already exists for the branch, do not create another: push the new commits and go to step 6 to refresh its description.

## 2. Branch

If the current branch is the default branch, create a branch named for the change in plain words (`fix-idle-timeout-clock`, not `patch-1` or a label coined mid-session) and move the work there. Commits already made locally on the default branch come along with `git switch -c <branch>`; leave the local default branch for the user to reset, and say so in the final message.

## 3. Commit

Commit the uncommitted changes that belong to this work, one coherent change per commit. Leave unrelated modified files alone and name them in the final message. If it is unclear whether a file belongs, ask.

## 4. Verify

Find and run the project's own checks (tests, linter, type check, build), each bounded with `timeout`. Record the exact commands and outcomes; they go into the description. If something fails, stop and report it with the output, unless the user asked for a draft PR with known failures. If the project has no checks, say that in the description rather than implying it was tested.

## 5. Push

```bash
timeout 120 git push -u origin "$(git branch --show-current)"
```

A plain push only. If it is rejected, stop and explain why and what the options are; never force push on your own.

## 6. Write the description

Read the whole change against the base, not just the last commit:

```bash
git log "origin/$base..HEAD"
git diff "origin/$base...HEAD" --stat
git diff "origin/$base...HEAD"
```

For a large diff, delegate the read and ask for a summary per area with file references.

The title follows the commit subject rules: what changed, plain words, imperative, under about 70 characters.

The body is in simple language for a reader who has not seen the work, with these sections in this order:

- **What**: the change, in a sentence or two.
- **Why**: the problem or need behind it. Link the issue if there is one.
- **How**: the approach, and anything in the diff that would surprise a reviewer.
- **Testing and verification**: everything actually run or checked in step 4, with the outcome. Name what was not tested.
- **Tradeoffs**: alternatives considered, what was given up, known limitations, and follow-ups left out of scope.

Leave out working vocabulary, a file-by-file changelog the diff already shows, and claims about testing you cannot point to output for. End the body with the attribution line if the session specifies one.

## 7. Create or update

Write the body to a file so quoting cannot mangle it:

```bash
body=$(mktemp)            # fill it with the description
timeout 60 gh pr create --base "$base" --title "<title>" --body-file "$body"    # add --draft when asked, or when checks are known to fail
timeout 60 gh pr edit --title "<title>" --body-file "$body"                     # instead, for an existing PR
```

## 8. Confirm

```bash
timeout 30 gh pr view --json url,state,isDraft,title
timeout 60 gh pr checks        # may be empty right after creation; one later look is enough
```

If the session has a tool for registering pull requests with the thread, call it with the PR URL. Report the URL, what was verified, any failing or pending checks, and anything left uncommitted or skipped. Do not merge.

When later commits change what the PR does, repeat steps 6 and 7 so the description stays true.
