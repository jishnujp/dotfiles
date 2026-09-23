# dotfiles

Personal workflow and preference files for a new server/laptop: bash + zsh, Neovim, tmux, scripts, cron helpers, global AI agent instructions, and a small Pi-only AI scaffold. Works on Linux (bash) and macOS (zsh); both shells share one aliases file.

The core dotfiles are installed with GNU Stow. Scripts and AI files are kept in the repo but are not stowed into `$HOME` by default. Git config is intentionally **not** managed here — identity and auth (credential helpers, signing keys) vary per machine, so set those up per host.

## Quick installation

```bash
git clone https://github.com/jishnujp/dotfiles.git ~/dotfiles
cd ~/dotfiles
./install.sh
```

One-liner:

```bash
git clone https://github.com/jishnujp/dotfiles.git ~/dotfiles && cd ~/dotfiles && ./install.sh
```

## What `install.sh` does

- Ensures GNU Stow is installed, or prompts to install it.
- Stows only these packages by default:
  - `bash` → `~/.bashrc`, `~/.profile`, `~/.inputrc`, `~/.bashrc.local.example`
  - `zsh` → `~/.zshrc`, `~/.zshrc.local.example` (macOS default shell)
  - `shell` → `~/.shell_common.sh` (shared aliases/env sourced by bash **and** zsh)
  - `nvim` → `~/.config/nvim`
  - `tmux` → `~/.tmux.conf`
  - `agents` → `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md` (one shared file of global agent instructions), `~/.claude/skills/create-pr`
- Does **not** stow `scripts/`, `ai/`, `assets/`, or `docs/`.
- Does **not** manage git config; set `~/.gitconfig` up per machine.
- The managed `~/.bashrc` / `~/.zshrc` add `~/dotfiles/scripts/bin` to `PATH` and source `~/.bashrc.local` / `~/.zshrc.local` when present.
- Prompts interactively when existing target files conflict:
  - back up existing targets and continue
  - skip that package
  - abort
- Prints a secret-hygiene reminder before you commit anything.

## Repository structure

```text
dotfiles/
├── install.sh
├── README.md
├── nvim/
│   └── .config/nvim/          # Stow package for ~/.config/nvim
├── tmux/
│   └── .tmux.conf             # Stow package for ~/.tmux.conf (per-OS clipboard)
├── agents/
│   ├── .codex/AGENTS.md       # global agent instructions, stowed to ~/.codex/AGENTS.md
│   ├── .claude/CLAUDE.md      # symlink to ../.codex/AGENTS.md, stowed to ~/.claude/CLAUDE.md
│   └── .claude/skills/        # Claude Code skills, stowed to ~/.claude/skills/<name>
├── shell/
│   └── .shell_common.sh       # shared aliases/env, sourced by bash and zsh
├── bash/
│   ├── .bashrc                # managed bash baseline (Linux default shell)
│   ├── .profile
│   ├── .inputrc
│   └── .bashrc.local.example  # template for ignored machine-local shell config
├── zsh/
│   ├── .zshrc                 # managed zsh baseline (macOS default shell)
│   └── .zshrc.local.example   # template for ignored machine-local shell config
├── scripts/
│   ├── bin/                   # user-invoked commands, added to PATH by bash/.bashrc
│   └── cron/                  # cron/scheduled-job scripts and templates
├── ai/
│   └── pi/                    # Pi-only scaffold, not installed by default
├── assets/                    # reserved for future assets
└── docs/                      # planning/decision/task docs
```

## Scripts

After installation and reloading your shell, commands in `scripts/bin/` are available on `PATH`.

Current commands include:

- `backup <folder>` — create timestamped tar.gz backups in `~/backup/`
- `practice <project-name>` — create a Python practice environment
- `closeall` — close open windows, requires `wmctrl` (Linux/X11)
- `simple-server` — start a tiny local HTTP response on port `1500`
- `pi-workflow-init` — helper for Pi workflow setup
- `delegate-codex` — run bounded, detached Codex jobs from Fable or a shell (Python 3.9+, POSIX)
- `delegation-ledger` — build a per-run ledger (model, effort, task type, time, token split, cost) from the Codex and Claude Code logs already on disk, then query or report it (Python 3.9+)

The scripts in `scripts/bin/` and `scripts/cron/` are Linux-oriented (they assume `wmctrl`, GNOME `gsettings`, `sha1sum`, and `/home/<user>` paths) and have not been made macOS-portable. Cron helpers live in `scripts/cron/`, are not installed automatically — review/edit paths before adding them to your crontab.

### Fable-to-Codex delegation

`delegate-codex` uses only the Python standard library and an installed, authenticated
`codex` CLI. Launch reads the complete prompt from stdin and returns a job ID once
it has passed the prompt to a detached worker. Provide a self-contained task with
paths, constraints, acceptance criteria, and exact verification commands. The global
agent instructions (`agents/.codex/AGENTS.md`, "Long delegations") tell the
orchestrator when and how to use it.

Agent tool shells are often non-interactive and never read the `PATH` addition in
`~/.bashrc` / `~/.zshrc`, so link the command somewhere already on `PATH`:

```bash
ln -s ~/dotfiles/scripts/bin/delegate-codex ~/.local/bin/delegate-codex
```

```bash
export DELEGATE_JOB_ROOT="$HOME/.local/state/delegate-codex" # optional; this is the default
job=$(delegate-codex launch --cwd "$PWD" --label fable-tests <<'PROMPT'
Run the repository's tests. Report the commands, key results, and any failures.
Do not modify files.
PROMPT
)
delegate-codex inspect "$job"           # JSON state, plus last event time and last agent message
delegate-codex join "$job" --timeout 30 # bounded wait; repeat while exit status is 75
delegate-codex result "$job"            # final response, once the job is terminal
delegate-codex list                     # JSON array of jobs under DELEGATE_JOB_ROOT
delegate-codex cancel "$job"            # request cancellation; bounded wait
delegate-codex launch --resume "$job" <<< "Follow-up feedback" # new job, same Codex thread
```

`join` also accepts several job IDs and applies one shared timeout to the group.
Launch defaults to `--sandbox workspace-write`, `--reasoning high`,
`--max-runtime 14400` seconds, and `--idle-timeout 1800` seconds. The idle timeout
stops a run that has emitted no Codex event for that long (a hung network call, a
wedged command); pass `--idle-timeout 0` to disable it when a single step, such as
a long build, is expected to stay silent for longer. Use `--sandbox read-only` for
investigation. The model defaults to `gpt-6-sol`, which is enough for work with
a clear spec; pass `--model gpt-6-luna` for mechanical bulk work and `--model
gpt-6-astra` for the occasional second opinion or architecture review, or set
`DELEGATE_CODEX_MODEL` to change the default on a host.
Left to itself `codex exec` would pick Astra, its most expensive model, every time.
`--codex /absolute/path/to/codex` selects another executable. Cwd, sandbox, reasoning,
JSON events, and the final-response path are explicit in every `codex exec` call.
Approvals are disabled for unattended execution; sandbox restrictions still apply.
The private `_worker` entry point is internal.

`launch --resume JOB_ID` starts a new job that continues a finished job's Codex
thread (`codex exec resume`), so a retry with feedback keeps the delegate's context.
It inherits the earlier job's cwd, sandbox, model, and `--pass-env` names unless they
are given again,
and refuses live jobs and jobs launched with `--ephemeral`.

Each job directory contains atomically replaced `state.json`, `events.jsonl`,
`stderr.log`, and, when Codex produces one, `result.md`. States are `queued`,
`running`, `succeeded`, `failed`, `timed_out` (with `timeout_reason` of
`max_runtime` or `idle`), `cancelled`, and `lost`. `succeeded` means only that
Codex exited 0 and wrote a final message; a delegate that was blocked still
succeeds, so read the result. Job directories are
private (0700), files are 0600, and labels/IDs accept only 1–64 ASCII letters,
digits, underscores, and hyphens, beginning with a letter or digit. Labels are
metadata; unique generated IDs name directories.

`join` and `cancel` wait at most `--timeout` seconds (default 10). They return 75
while live, otherwise the job's exit code: 0 for success, 87 for runtime or idle
expiry, 125 for runner failure or a lost worker, 130 for cancellation, or Codex's
nonzero exit code.
`result` uses the same codes and prints any available final response only after
completion. Invalid syntax returns 2; unknown jobs return 125. Timeout and
cancellation send TERM to the Codex process group, then KILL after a two-second
grace period; cleanup also covers children left behind when Codex exits.

Prompts travel through anonymous pipes, never wrapper metadata, files, or command
arguments. Workers and Codex receive only the account's HOME, the caller's PATH
(so the delegate finds the same toolchain: node, uv, gh, and so on), the caller's
LANG (`C.UTF-8` when unset), and any variable named with a repeatable `--pass-env NAME`. Forwarded values live only in
the worker's process environment; `state.json` records the names, never the values.
Authentication therefore uses the account's normal on-disk Codex login; caller API
keys, custom CODEX_HOME, and proxies are not forwarded unless named. Codex keeps
its normal session file under `~/.codex/sessions` so the thread can be resumed;
that file contains the prompt. Pass `--ephemeral` to keep no session file, at the
cost of `--resume`. Events, stderr, and results are retained verbatim and may
contain content Codex chooses to echo; they are not secret-redacted. Delete
completed job directories when no longer needed.

If a worker is killed outright (SIGKILL) or the host reboots, the next `join`,
`inspect`, `list`, or `cancel` notices the missing worker and marks the job `lost`
(exit 125) instead of reporting it live forever. Liveness is a file lock
(`worker.lock`) that the worker holds for its whole life, so a reused process ID
cannot make a dead job look alive. A lost job that got as far as starting its
Codex thread can still be continued with `--resume`. The wrapper does not kill the
Codex process such a worker leaves behind; check `codex_pid` from the job state.

On Ubuntu 24.04 and later, AppArmor's restriction on unprivileged user namespaces
blocks the `bwrap` binary that Codex bundles for its sandbox. Every command the
delegate runs then fails with `bwrap: loopback: Failed RTM_NEWADDR: Operation not
permitted`, in every sandbox mode except `danger-full-access`, while the job still
exits 0. This affects bare `codex exec` equally. The fix is an AppArmor profile
that grants `userns` to that binary only. It is a host setting, not installed by
these dotfiles; save this as `/etc/apparmor.d/codex-bwrap` (adjust the path if
Codex is installed elsewhere) and load it with
`sudo apparmor_parser -r /etc/apparmor.d/codex-bwrap`:

```text
abi <abi/5.0>,
include <tunables/global>

profile codex-bwrap /home/*/.local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-*/vendor/*/codex-resources/bwrap flags=(unconfined) {
  userns,
  @{exec_path} mr,

  include if exists <local/codex-bwrap>
}
```

Verify without API calls:

```bash
python3 -m unittest discover -s tests -p 'test_delegate_codex.py' -v
python3 -m py_compile scripts/bin/delegate-codex tests/test_delegate_codex.py
scripts/bin/delegate-codex --help
```

### Delegation ledger

`delegation-ledger` answers "which model did what, for how long, at what token cost"
without any new instrumentation. It reads the delegate-codex job directories, every
Codex session rollout under `~/.codex/sessions`, and every Claude Code transcript
under `~/.claude/projects` (subagent transcripts included), and writes one JSON row
per run: source, model, effort, sandbox, a heuristic task type (review, exploration,
implementation, other), active minutes, tokens split into uncached input, cache
reads, cache writes, output and reasoning, an estimated API cost, and for Codex the
share of the weekly subscription window the run consumed.

```bash
ln -s ~/dotfiles/scripts/bin/delegation-ledger ~/.local/bin/delegation-ledger

delegation-ledger build -o ~/ledgers/before.jsonl --snapshot before   # freeze a baseline
delegation-ledger build -o ~/ledgers/after.jsonl --since 2026-09-24    # after a model switch
delegation-ledger report ~/ledgers/before.jsonl ~/ledgers/after.jsonl -o compare.md

# slices for a person or an LLM to analyse
delegation-ledger query before.jsonl --task-type implementation --group-by model,effort
delegation-ledger query before.jsonl --model gpt-6-sol,gpt-5.6-sol --since 2026-09-20 --format csv
delegation-ledger query before.jsonl --min-tokens 1000000 --source delegate-codex --format markdown
delegation-ledger query before.jsonl --group-by day,model
```

The report opens with a "how to read" section, then summaries by task type, by
snapshot and model, and by day, then the rows newest first with the prompt head, so
it can be pasted into a chat as-is. Task type is a keyword heuristic over the prompt,
label and sandbox; re-classify from `prompt_head` where it is wrong. Cost uses list
API prices, which both vendors also use, near enough, to meter subscription windows.
Claude Code prunes transcripts after 30 days by default, so build a snapshot before
they age out. Codex splits one session across several rollout files; the ledger
merges them so a delegation's tokens are counted once.

Verify without API calls:

```bash
python3 -m unittest discover -s tests -p 'test_delegation_ledger.py' -v
python3 -m py_compile scripts/bin/delegation-ledger tests/test_delegation_ledger.py
```

## Shell local config

Machine-specific shell settings belong in a host-local file that is sourced by the managed shell config and must not be committed:

```bash
cp ~/.bashrc.local.example ~/.bashrc.local   # bash / Linux
cp ~/.zshrc.local.example  ~/.zshrc.local    # zsh / macOS
```

Aliases and env that should apply on **both** shells go in `shell/.shell_common.sh` (stowed to `~/.shell_common.sh`), which `~/.bashrc` and `~/.zshrc` both source.

## Manual Stow usage

```bash
cd ~/dotfiles
stow bash       # or: stow zsh   (macOS)
stow shell
stow nvim
stow tmux
stow agents
stow -D nvim   # unstow
stow -R nvim   # restow
```

Do not run `stow */`; that would try to stow non-dotfile directories such as `scripts/`, `ai/`, `assets/`, and `docs/`.

## Agent instructions

`agents/.codex/AGENTS.md` holds the global instructions for AI coding agents: when Claude Code delegates to Codex, the handoff and report-back contracts, how to bound long-running commands, and how to write the final summary. It is one file linked into both `~/.codex/AGENTS.md` and `~/.claude/CLAUDE.md`, so edit it once and both tools pick it up. It is meant to be generic across personal and work repos; repo-specific rules go in that repo's own `AGENTS.md` or `CLAUDE.md`.

Rules that must always hold (commit messages, no force pushes) stay in that file because it is loaded into every session. Procedures that are only needed now and then live as Claude Code skills under `agents/.claude/skills/`, which cost nothing until used. Currently: `create-pr`, which branches, commits, runs the project's checks, pushes, writes the what/why/how/testing/tradeoffs description, and opens the pull request with `gh`. Invoke it with `/create-pr` or by asking for a pull request.

## Dependencies

Required:

- git
- bash (Linux) or zsh (macOS)
- GNU Stow

Optional, depending on what you use:

- neovim
- jq, curl
- wmctrl (Linux/X11, for `closeall`)
- gsettings/GNOME tools (Linux, for cron wallpaper helpers)
- a clipboard tool for tmux: `xclip` (X11), `wl-clipboard` (Wayland), or `pbcopy` (built into macOS)

Ubuntu example:

```bash
sudo apt update
sudo apt install git stow neovim jq curl wmctrl xclip
```

macOS example:

```bash
brew install stow neovim jq   # zsh is the default shell; pbcopy is built in
```

## Secret hygiene

Do not commit credentials, OAuth tokens, PATs, local shell settings, `.env` files, or machine-local agent settings.

Before committing, run:

```bash
git status --short --ignored
git ls-files | grep -Ei '(^|/)(\.env|.*\.local|settings\.local\.json|credentials|token.*\.json)$' || true
```

Important: adding a pattern to `.gitignore` does **not** untrack a file that is already tracked. If a secret-like file is tracked, remove it from git without deleting your local copy:

```bash
git rm --cached <file>
```

## Updating

```bash
cd ~/dotfiles
git pull
./install.sh
```
