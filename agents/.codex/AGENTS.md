# Global agent instructions

Shared by Claude Code (`~/.claude/CLAUDE.md`) and Codex (`~/.codex/AGENTS.md`). They apply in every repo, personal or work. A repo's own `CLAUDE.md` or `AGENTS.md` adds to these; it does not replace them. Keep this file short: a rule earns its place only if it changes what the agent does next.

## Done means verified

- Report done only for work you can point to evidence for: a test run, a command's output, a diff. If you did not run it, say so.
- Every background task, subagent, or delegate you started is joined before the final answer. Read its result back in the turn; a completion notification is a wake signal, not proof.
- Keep the turn open with bounded waits until the outcome is verified. Do not end the turn and hope a notification brings you back.
- When the acceptance criterion is a metric, eval, or benchmark, make it independently checkable. A delegate can satisfy a measure by gaming it.

## Delegation

Claude Code is the orchestrator. Codex (`codex exec`) is the delegate. If codex is not installed or not permitted in the current environment, use a Claude Code subagent for the same job with the same contracts below.

The point of delegating is twofold: bulk tokens (file dumps, test output, exploration transcripts) stay out of the orchestrator's context, and independent work runs in parallel. Delegates return conclusions, not transcripts. Delegate proactively per these rules; do not ask first.

**Delegate** when the task can be spec'd in a few sentences and verified mechanically: tests, linters, a command with expected output. **Keep inline** when it is ambiguous, architectural, cross-cutting, or user-facing (UI, copy, API shapes). Route by risk, not just cost: reviewing bad work on an ambiguous task costs more than doing it once. Do not delegate work finishable in a handful of tool calls, and do not spawn anything to double-check your own work. A fresh-context review is the one exception, because its value is cold context.

Delegation is per phase, not per task. The ambiguity that keeps design work inline ends when the design settles; the implementation that follows is routed on its own merits. "Already mid-session" is not a reason to stay inline.

### What goes where

- Trivial lookups (one grep or glob answers it): inline. Spawning anything costs more than the search.
- Exploration and investigation (how does X work, where does Y happen, trace this flow): `codex exec -s read-only`. Fan out independent questions as parallel background calls. Ask for conclusions with file and line references, not file contents.
- Implementation from a settled spec (roughly three or more files of work that is mechanical once specced): `codex exec -s workspace-write`. Stay inline only when the edits are entangled with live iterative state (a tight test-and-tweak loop, debugging a remote box) or the code is user-facing.
- Second-opinion review: after every substantial change is complete, run `codex exec -s read-only` (or `codex review`) with a review prompt and surface its findings. Put simplification first: what can be deleted, collapsed, or replaced by one validated path, not just what is broken. The orchestrator still reviews the final diff itself.
- Long operations (deploys, builds, pulls, anything that mostly waits): launch in the background, then keep the current turn active with bounded foreground waits until the outcome is verified.

### Effort

Set reasoning effort explicitly on every codex call with `-c model_reasoning_effort=<level>`; an unpinned run applies no effort at all.

- `low` or `medium`: mechanical work with a clear spec, fixture and data edits, migrations, ops sequences.
- `high`: the default for ordinary implementation and investigation.
- `xhigh`: review, architecture decisions, anything ambiguous.

### Handoff contract

Every delegation prompt is self-contained; the delegate cannot see the orchestrator's conversation and cannot ask follow-ups. It must include: file paths, constraints and invariants, acceptance criteria, and the exact verify command(s). Size the task as a coherent slice with its tests, not micro-tasks. State scope discipline ("deliver what was asked, at the scope intended") and evidence-based completion ("report done only for work you can point to tool-result evidence for").

### Report-back contract

The delegate returns: files changed, what was run, pass/fail with the key output lines, and open questions. Take that report at face value and review the diff, not the process. Re-run its verification only when the report is suspect: internally inconsistent, missing the output it claims, or contradicted by the diff.

### Escalation

One retry with concrete failure feedback, then bring the work inline; the orchestrator's context is what the delegate lacked. Never a third round with the same delegate on the same task. A success report that later turns out wrong counts as the failed attempt.

### Mechanics

One `codex exec` invocation is one delegation. Run it as a background shell command when it may take more than a couple of minutes, then join it from the open turn.

```bash
codex exec --skip-git-repo-check -C <dir> -s <read-only|workspace-write> \
  -c model_reasoning_effort=<level> -o <out>.md --json "<prompt>" < /dev/null > <out>.events.jsonl
```

Read `<out>.md` (the delegate's final message) and nothing else by default; the JSONL event log is for diagnosing a run. The `< /dev/null` is required: codex reads stdin even with a prompt argument and waits forever on an idle pipe. Follow-ups continue the same thread rather than starting a fresh prompt: take the thread id from the first `--json` event (or use `codex exec resume --last`) and run `codex exec resume <thread-id> "<prompt>" < /dev/null`, repeating the effort flag. Independent delegations are separate processes; fan them out in parallel.

## Long-running commands

- Bound any command that can hang on external state (network, a container daemon, a remote host): `timeout <seconds> <cmd>` on Linux, `gtimeout` from coreutils on macOS. A retry loop around an unbounded probe is still unbounded; bound each probe, not just the loop.
- Scripts launched in the background must terminate on every outcome: success, known failure signatures, and a hard iteration cap. Silence is not success.

## Git and GitHub

- Commit messages are for someone reading the log a year from now. The subject line says what changed in plain words, in the imperative, under about 70 characters. The body says why, and anything a reader could not get from the diff. No vague subjects ("fix stuff", "updates", "wip"), and no labels coined mid-session.
- One commit is one coherent change. Do not bundle unrelated edits, and do not commit files you did not mean to touch.
- Use `gh` for everything on GitHub: creating, viewing, and merging PRs, reading review comments, inspecting CI runs and their logs (`gh pr view`, `gh pr checks`, `gh run view --log-failed`, `gh api`). Do not guess at state you can query.
- Never force push on your own, including `--force-with-lease`. If a force push looks unavoidable (a rebase or amend of commits already pushed, a rewritten history), stop before doing it. Tell the user what happened, why a normal push no longer works, and what the options are, then wait for their decision.
- Prefer fixing forward with a new commit over rewriting commits that are already pushed; that is what keeps force pushes avoidable.

### Pull request descriptions

Write in simple language for a reader who has not seen the work. Cover, in this order:

- **What**: the change, in a sentence or two.
- **Why**: the problem or need behind it.
- **How**: the approach, and anything in the diff that would surprise a reviewer.
- **Testing and verification**: everything actually run or checked, with the outcome. Name what was not tested.
- **Tradeoffs**: alternatives considered, what was given up, known limitations, and follow-ups left out of scope.

The title follows the commit subject rules. Keep the description current when later commits change the PR's scope.

## Final summary

Terse shorthand between tool calls is fine; that is thinking out loud. The final message is different: it is for a reader who saw none of it, and after a long unattended stretch it is their first look at the work. Write it as a re-grounding, not a continuation of the working thread.

- Open with the outcome: one sentence answering "what happened" or "what did you find." Supporting detail after.
- Drop the working vocabulary. No arrow chains, no hyphen-stacked compounds, no labels coined mid-session. Give files, commits, flags, and run ids their own plain-language clause.
- Readable beats concise. Shorten by cutting details that would not change what the reader does next, not by compressing prose into fragments.
- Report faithfully: failing tests with their output, skipped steps named as skipped.
