#!/usr/bin/env bash
# Install WFS Studio on Linux and add an alias to bash or zsh.
#
# The script asks three things, then follows those answers:
#   the working directory, the alias name, and bash or zsh.
# Bash writes ~/.bashrc. Zsh writes ~/.zshrc.
#
# A checkout can set these instead of prompting:
#   WFS_INSTALL_DIR, WFS_INSTALL_ALIAS, WFS_INSTALL_SHELL
# WFS_INSTALL_SKIP_PIP=1 writes the alias and skips the virtualenv.
# WFS_INSTALL_ALLOW_NON_LINUX=1 is only for tests on another system.
set -euo pipefail

REPO_URL="https://github.com/p4h88hnz4w-byte/wfs-studio.git"
BEGIN="# >>> wfs-studio >>>"
END="# <<< wfs-studio <<<"

if [[ "$(uname -s)" != "Linux" && "${WFS_INSTALL_ALLOW_NON_LINUX:-}" != "1" ]]; then
  echo "This installer is for Linux." >&2
  exit 1
fi

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run this installer as your own user, not as root." >&2
  exit 1
fi

if [[ -z "${HOME:-}" ]]; then
  echo "HOME is not set." >&2
  exit 1
fi

answer=""

ask() {
  local label="$1"
  local default="$2"
  local preset="${3:-}"
  local reply=""
  if [[ -n "$preset" ]]; then
    answer="$preset"
    return
  fi
  if [[ ! -t 0 ]]; then
    echo "No answer for: $label" >&2
    exit 1
  fi
  read -r -p "$label [$default]: " reply
  answer="${reply:-$default}"
}

script_dir="$(cd "$(dirname "$0")" && pwd)"
default_dir="$script_dir"
if [[ ! -f "$script_dir/pyproject.toml" ]]; then
  default_dir="$HOME/wfs-studio"
fi

detected="bash"
case "${SHELL:-}" in
  */zsh) detected="zsh" ;;
  */bash) detected="bash" ;;
esac

ask "Working directory" "$default_dir" "${WFS_INSTALL_DIR:-}"
case "$answer" in
  "~") answer="$HOME" ;;
  "~/"*) answer="$HOME/${answer#"~/"}" ;;
esac
mkdir -p "$answer"
work="$(cd "$answer" && pwd)"

ask "Alias" "wfs-studio" "${WFS_INSTALL_ALIAS:-}"
alias_name="$answer"
if [[ ! "$alias_name" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]]; then
  echo "The alias must be a shell name, such as wfs-studio." >&2
  exit 1
fi

ask "Shell (bash or zsh)" "$detected" "${WFS_INSTALL_SHELL:-}"
shell_name="$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]')"
case "$shell_name" in
  bash) rc_file="$HOME/.bashrc" ;;
  zsh) rc_file="$HOME/.zshrc" ;;
  *)
    echo "Choose bash or zsh." >&2
    exit 1
    ;;
esac

echo "Working directory: $work"
echo "Alias: $alias_name"
echo "Shell file: $rc_file"

if [[ ! -f "$work/pyproject.toml" ]]; then
  if [[ -n "$(ls -A "$work")" ]]; then
    echo "That folder is not empty, and it is not a WFS Studio checkout." >&2
    exit 1
  fi
  if [[ "${WFS_INSTALL_SKIP_PIP:-}" == "1" ]]; then
    echo "That folder has no checkout to install." >&2
    exit 1
  fi
  git clone --depth 1 "$REPO_URL" "$work"
  git -C "$work" submodule update --init --depth 1 third_party/wfs-tools
fi

python_bin="$work/.venv/bin/python"
if [[ "${WFS_INSTALL_SKIP_PIP:-}" != "1" ]]; then
  if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Python 3.10 or newer is required. python3 is older than that." >&2
    exit 1
  fi
  python3 -m venv "$work/.venv"
  "$work/.venv/bin/pip" install -r "$work/requirements.txt"
  "$work/.venv/bin/pip" install -e "$work"
fi

quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

launch="cd $(quote "$work") && exec $(quote "$python_bin") -m wfs_studio"
block="alias ${alias_name}=$(quote "$launch")"

tmp="$(mktemp)"
if [[ -f "$rc_file" ]]; then
  awk -v begin="$BEGIN" -v end="$END" '
    $0 == begin { skip = 1; next }
    $0 == end { skip = 0; next }
    skip != 1 { print }
  ' "$rc_file" > "$tmp"
else
  : > "$tmp"
fi
{
  cat "$tmp"
  printf '\n%s\n%s\n%s\n' "$BEGIN" "$block" "$END"
} > "$rc_file"
rm -f "$tmp"

echo "Added ${alias_name} to ${rc_file}."
echo "Open a new terminal, or run: source $(quote "$rc_file")"
echo "Then run: ${alias_name}"
