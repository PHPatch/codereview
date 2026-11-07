#!/bin/sh
# CodeReview — one-line installer for macOS and Linux.
#
#   curl -fsSL https://phpatch.com/codereview/install.sh | sh
#
# What it does, in plain words:
#   1. checks you have Python 3.11 or newer (CodeReview needs it);
#   2. installs the `codereview-ai` package from PyPI in its own
#      isolated environment (pipx if you have it, otherwise a
#      private virtual environment under ~/.local/share) — your
#      system Python and other tools are never touched;
#   3. puts a `codereview` command where your terminal can find
#      it and tells you the two commands to run next.
#
# Nothing is installed system-wide and no administrator password
# is ever asked for. To remove CodeReview later, delete the
# environment it created (the paths are printed at the end).
#
# Pre-launch note: this script installs the published package
# `codereview-ai` from PyPI. Until the package is published,
# testers can point the installer at another source:
#   CODEREVIEW_INSTALL_SOURCE=/path/to/codereview  sh install.sh
#   CODEREVIEW_INSTALL_SOURCE=codereview-ai==0.13.0 sh install.sh
# The value is passed verbatim to pip/pipx as the install target.

set -eu

PACKAGE="${CODEREVIEW_INSTALL_SOURCE:-codereview-ai}"
VENV_DIR="${CODEREVIEW_VENV:-$HOME/.local/share/codereview-venv}"
BIN_DIR="$HOME/.local/bin"

say() { printf '%s\n' "$*"; }
die() { printf 'install: %s\n' "$*" >&2; exit 1; }

# --- 1. find a Python new enough --------------------------------
PYTHON=""
for cand in python3.13 python3.12 python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
            PYTHON="$cand"
            break
        fi
    fi
done
if [ -z "$PYTHON" ]; then
    die "Python 3.11 or newer was not found on this machine.
CodeReview needs it. On macOS: install it from https://www.python.org/downloads/
(or 'brew install python'). On Debian/Ubuntu: 'sudo apt install python3'.
Then run this installer again."
fi
say "Found $("$PYTHON" --version 2>&1)."

# --- 2. install, isolated ---------------------------------------
mkdir -p "$BIN_DIR"
if command -v pipx >/dev/null 2>&1; then
    say "Installing CodeReview with pipx (isolated environment)…"
    pipx install --force "$PACKAGE" >/dev/null
    # pipx installs into its own bin dir; make sure our BIN_DIR
    # carries the command too when pipx used a different one.
    PIPX_BIN="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || echo "$BIN_DIR")"
    if [ "$PIPX_BIN" != "$BIN_DIR" ] && [ -x "$PIPX_BIN/codereview" ]; then
        ln -sf "$PIPX_BIN/codereview" "$BIN_DIR/codereview"
    fi
else
    say "Installing CodeReview into its own environment at $VENV_DIR …"
    "$PYTHON" -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip
    "$VENV_DIR/bin/python" -m pip install --quiet "$PACKAGE"
    ln -sf "$VENV_DIR/bin/codereview" "$BIN_DIR/codereview"
fi

[ -x "$BIN_DIR/codereview" ] || die "the install finished but the codereview command was not created — please report this (see SUPPORT in the package docs)."

# --- 3. say what happened ---------------------------------------
say ""
say "CodeReview is installed: $("$BIN_DIR/codereview" --version 2>/dev/null || echo 'codereview')"
case ":$PATH:" in
    *":$BIN_DIR:"*)
        say "Next steps:"
        ;;
    *)
        say "One more step: $BIN_DIR is not on your PATH yet. Add it with:"
        say "  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.profile   # then open a new terminal"
        say "Next steps (in a new terminal):"
        ;;
esac
say "  1. codereview setup          — pick your AI providers (you bring your own keys)"
say "  2. codereview doctor --plain — check every seat answers, in plain words"
say "  3. in a git repo: codereview — your first review"
