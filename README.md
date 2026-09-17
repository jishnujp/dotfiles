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
  - `agents` → `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md` (one shared file of global agent instructions)
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
│   └── .claude/CLAUDE.md      # symlink to ../.codex/AGENTS.md, stowed to ~/.claude/CLAUDE.md
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

The scripts in `scripts/bin/` and `scripts/cron/` are Linux-oriented (they assume `wmctrl`, GNOME `gsettings`, `sha1sum`, and `/home/<user>` paths) and have not been made macOS-portable. Cron helpers live in `scripts/cron/`, are not installed automatically — review/edit paths before adding them to your crontab.

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
