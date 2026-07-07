#!/usr/bin/env bash
set -euo pipefail

# ────────────────────────────────────────────────────────────────────
# rume — one prompt to get any system running
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/zhixiangxue/rume/main/install.sh | bash
# ────────────────────────────────────────────────────────────────────

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
CYAN="\033[36m"
RESET="\033[0m"

log()  { echo -e "${BOLD}${GREEN}→${RESET} $*"; }
warn() { echo -e "${BOLD}${YELLOW}⚠${RESET} $*"; }

echo ""
echo -e "${BOLD}${CYAN}  ╔══════════════════════════════════╗${RESET}"
echo -e "${BOLD}${CYAN}  ║       rume installer v0.2       ║${RESET}"
echo -e "${BOLD}${CYAN}  ╚══════════════════════════════════╝${RESET}"
echo ""

# ── 1. Ensure uv is available ──────────────────────────────────────
if command -v uv &>/dev/null; then
    log "uv $(uv --version | awk '{print $2}') already installed"
else
    warn "uv not found — installing now..."
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Source cargo/env if it exists (uv installs via cargo/standalone)
    for rc in "$HOME/.local/bin/env" "$HOME/.cargo/env"; do
        [ -f "$rc" ] && source "$rc" 2>/dev/null || true
    done

    # Ensure ~/.local/bin is on PATH
    case ":$PATH:" in
        *:"$HOME/.local/bin":*) ;;
        *) export PATH="$HOME/.local/bin:$PATH" ;;
    esac

    if command -v uv &>/dev/null; then
        log "uv installed successfully ($(uv --version))"
    else
        echo ""
        echo "❌ Failed to install uv. Please install it manually:"
        echo "   https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
fi

# ── 2. Install rume ────────────────────────────────────────────────
log "Installing rume from GitHub..."

uv tool install "git+https://github.com/zhixiangxue/rume.git" \
    --force \
    2>&1 | sed 's/^/  /'

# ── 3. Verify ───────────────────────────────────────────────────────
echo ""
if command -v rume &>/dev/null; then
    log "rume installed at $(command -v rume)"
    echo ""
    echo -e "  ${BOLD}Try it out:${RESET}"
    echo -e "    ${CYAN}rume \"Start https://github.com/user/repo dev server\"${RESET}"
    echo ""
else
    warn "rume binary not found on PATH."
    echo ""
    echo "  uv installs tools to ~/.local/bin — make sure it's in your PATH:"
    echo '    export PATH="$HOME/.local/bin:$PATH"'
    echo ""
    echo "  Then try:  rume --help"
    echo ""
fi
