#!/usr/bin/env bash
# dotfiles installer

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STOW_PACKAGES=(nvim tmux bash zsh shell agents)
BACKUP_ROOT="$HOME/.dotfiles-backup"

print_status() { echo -e "${GREEN}[✓]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[!]${NC} $1"; }
print_error() { echo -e "${RED}[✗]${NC} $1"; }

confirm() {
    local prompt="$1"
    local answer
    read -r -p "$prompt [y/N] " answer
    case "$answer" in
        y|Y|yes|YES) return 0 ;;
        *) return 1 ;;
    esac
}

ensure_stow() {
    if command -v stow >/dev/null 2>&1; then
        print_status "stow installed"
        return 0
    fi

    print_warning "GNU Stow is not installed."
    if ! confirm "Install stow now if a supported package manager is available?"; then
        print_error "stow is required to install dotfile packages."
        exit 1
    fi

    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y stow
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y stow
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --needed stow
    elif command -v brew >/dev/null 2>&1; then
        brew install stow
    else
        print_error "No supported package manager found. Install GNU Stow manually and rerun."
        exit 1
    fi

    print_status "stow installed"
}

backup_target() {
    local target="$1"
    local timestamp backup_path backup_parent

    timestamp="$(date +%Y%m%d_%H%M%S)"
    backup_path="$BACKUP_ROOT/$timestamp${target#$HOME}"
    backup_parent="$(dirname "$backup_path")"

    mkdir -p "$backup_parent"
    mv "$target" "$backup_path"
    print_status "Backed up $target to $backup_path"
}

source_matches_target() {
    local source="$1"
    local target="$2"

    [ -L "$target" ] || return 1
    [ "$(readlink -f "$target")" = "$(readlink -f "$source")" ]
}

find_package_conflicts() {
    local package="$1"
    local source target rel

    [ -d "$REPO_DIR/$package" ] || return 0

    while IFS= read -r -d '' source; do
        rel="${source#"$REPO_DIR/$package/"}"
        target="$HOME/$rel"

        if [ -e "$target" ] || [ -L "$target" ]; then
            if ! source_matches_target "$source" "$target"; then
                printf '%s\t%s\n' "$source" "$target"
            fi
        fi
    done < <(find "$REPO_DIR/$package" \( -type f -o -type l \) -print0)
}

resolve_package_conflicts() {
    local package="$1"
    local conflicts=()
    local line source target choice

    while IFS= read -r line; do
        [ -n "$line" ] && conflicts+=("$line")
    done < <(find_package_conflicts "$package")

    [ "${#conflicts[@]}" -eq 0 ] && return 0

    print_warning "Conflicts found for package '$package':"
    for line in "${conflicts[@]}"; do
        source="${line%%$'\t'*}"
        target="${line#*$'\t'}"
        echo "  target exists: $target"
        echo "    repo file:   $source"
    done

    while true; do
        echo
        echo "Choose conflict handling for package '$package':"
        echo "  [b] Back up existing targets and continue"
        echo "  [s] Skip this package"
        echo "  [a] Abort install"
        read -r -p "Choice [b/s/a]: " choice
        case "$choice" in
            b|B)
                for line in "${conflicts[@]}"; do
                    target="${line#*$'\t'}"
                    backup_target "$target"
                done
                return 0
                ;;
            s|S)
                print_warning "Skipping package '$package'"
                return 1
                ;;
            a|A)
                print_error "Install aborted."
                exit 1
                ;;
            *)
                print_warning "Please choose b, s, or a."
                ;;
        esac
    done
}

stow_package() {
    local package="$1"

    if [ ! -d "$REPO_DIR/$package" ]; then
        print_warning "Package '$package' not found; skipping"
        return 0
    fi

    if resolve_package_conflicts "$package"; then
        stow -d "$REPO_DIR" -t "$HOME" -R "$package"
        print_status "Stowed package: $package"
    fi
}

create_local_shell_example() {
    if [ -f "$HOME/.bashrc.local.example" ] && [ ! -f "$HOME/.bashrc.local" ]; then
        print_warning "For host-specific shell settings, copy ~/.bashrc.local.example to ~/.bashrc.local and edit it."
    fi
}

print_secret_hygiene_reminder() {
    echo
    print_warning "Secret hygiene reminder"
    echo "Before committing, review local/secret files:"
    echo "  git status --short --ignored"
    echo "  git ls-files | grep -Ei '(^|/)(\\.env|.*\\.local|settings\\.local\\.json|credentials|token.*\\.json)$' || true"
    echo "If a secret is already tracked, remove it with git rm --cached <file> before committing."
}

main() {
    echo -e "${GREEN}=== dotfiles installation ===${NC}"
    echo "Repo: $REPO_DIR"
    echo

    ensure_stow

    for package in "${STOW_PACKAGES[@]}"; do
        stow_package "$package"
    done

    create_local_shell_example

    echo
    print_status "Install complete"
    echo
    echo "Installed Stow packages: ${STOW_PACKAGES[*]}"
    echo "Not stowed by default: scripts, ai, assets, docs"
    echo "Git config is intentionally not managed here (identity/auth is per-machine)."
    echo "Reload shell with: source ~/.bashrc   (or ~/.zshrc on macOS)"
    echo "User commands will be available from: $REPO_DIR/scripts/bin"

    print_secret_hygiene_reminder
}

main "$@"
