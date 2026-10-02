---
name: feedback-log
description: Log feedback on the agent's own work to a shared review log at ~/.claude/feedback-log/. Use without being asked whenever the user asks for a redo, asks for it to be done differently, corrects a wrong assumption, points out a missed instruction or a failing tool call, says they are unhappy with a result, or says they are pleased or impressed with something. Also use to list or review logged feedback and turn it into instruction or tool fixes.
---

# Feedback log

One shared, append-only log of what went wrong and what went well in agent sessions, across every project, so the patterns can be reviewed later and turned into instructions, tools, or kept practices. Each entry records the session itself: time, project, git branch, Claude session id and transcript path, the T3 thread, and an excerpt of the last few messages. Transcripts are pruned after about 30 days, so the excerpt is what survives.

```bash
L=~/.claude/skills/feedback-log/feedback_log.py
```

## When to log

Log in the same turn, before or alongside the fix, without asking. Add one line to the reply ("Logged this to the feedback log.") and carry on with the actual work.

| The user… | kind |
|---|---|
| asks for the same work again, because the result was wrong or incomplete | `redo` |
| wants it done another way (different tool, design, scope, format) | `approach` |
| corrects a fact about the repo, environment, or task that the agent assumed | `assumption` |
| points to an instruction or earlier request that was not followed | `ignored-instruction` |
| points out a failing tool call, command, or broken environment | `tool-failure` |
| is unhappy with the quality, tone, or length of a response | `quality` |
| says something worked well, or that they are pleased or impressed | `win` |

The trigger is the user's feedback on work the agent already did, or specific praise for it. Do not log ordinary follow-up requests, refinements, new information the agent could not have known, or a change of mind about requirements. One entry per incident; do not log the same correction twice.

## Add an entry

```bash
$L add --kind redo \
  --summary "PR still contained experiment scripts after the first cleanup" \
  --user-said "the experiments still have some left overs in the PR" \
  --what-happened "Removed result files but kept experiments/ scripts as a fourth commit" \
  --why "Treated pre-PR validation code as part of the contribution" \
  --lesson "Read the full PR diff; experiment code stays off product branches" \
  --cost "1 extra round, ~16 min"
```

For a `win`, `--why` says why it worked and `--lesson` says what to keep doing. Quote the user's words in `--user-said`, and keep every field to a sentence or two. Never put secrets in a field; the script redacts common token patterns, but don't rely on it.

## Review

When the user asks to review the log:

```bash
$L list                      # open problems and new wins from the last 30 days
$L list --kind problems --days 90 --project horus
$L show <id>                 # full entry with the transcript excerpt
$L resolve <id> --note "Rule added to ~/recommendly/CLAUDE.md"
```

Group the entries by root cause, not by project. For each group that recurs, propose a fix: a rule in the global `~/.claude/CLAUDE.md` (dotfiles `agents/.codex/AGENTS.md`), a line in the machine file `~/CLAUDE.md`, a project `CLAUDE.md`, or a script or tool when an instruction won't hold. Wins that recur become rules too ("keep doing X"). After making a change, `resolve` each entry it covers, with a note saying where the change went.
