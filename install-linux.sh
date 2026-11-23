#!/usr/bin/env bash
# Install WFS Studio on Linux and add an alias to bash or zsh.
#
# Native installs name missing window libraries for apt, dnf, or pacman.
# Ubuntu 22.04+, Debian 12+, Fedora 39+, and Arch on WSL2 use this same
# script. WSL1, other WSL distros, a Windows drive (/mnt), and 32-bit x86
# are refused. Native Windows is not installed by this script.
#
# The script asks three things, then follows those answers:
#   the working directory, the alias name, and bash or zsh.
# Bash writes ~/.bashrc. Zsh writes ~/.zshrc.
#
# A checkout can set these instead of prompting:
#   WFS_INSTALL_DIR, WFS_INSTALL_ALIAS, WFS_INSTALL_SHELL
# WFS_INSTALL_SKIP_PIP=1 writes the alias and skips the virtualenv.
# WFS_INSTALL_ALLOW_NON_LINUX=1 is only for tests on another system.
# WSL tests point WFS_INSTALL_PROC_VERSION, WFS_INSTALL_OS_RELEASE, and
# WFS_INSTALL_WSLG_DIR at stand-in files. WFS_INSTALL_SKIP_PACKAGES=1 skips
# the library check. WFS_INSTALL_LIB_DIR and WFS_INSTALL_MACHINE are test hooks.
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

proc_version_file="${WFS_INSTALL_PROC_VERSION:-/proc/version}"
os_release_file="${WFS_INSTALL_OS_RELEASE:-/etc/os-release}"
wslg_dir="${WFS_INSTALL_WSLG_DIR:-/mnt/wslg}"
wsl_session=0
wsl_family=""
distro_id=""
distro_version=""
distro_like=""
pkg_family=""

wsl_detected() {
  if [[ -n "${WSL_DISTRO_NAME:-}" || -n "${WSL_INTEROP:-}" ]]; then
    return 0
  fi
  if [[ -r "$proc_version_file" ]] && grep -q -i microsoft "$proc_version_file"; then
    return 0
  fi
  return 1
}

os_release_value() {
  local key="$1"
  (
    # shellcheck disable=SC1090
    . "$os_release_file"
    eval "printf '%s' \"\${${key}:-}\""
  )
}

read_distro() {
  distro_id=""
  distro_version=""
  distro_like=""
  pkg_family=""
  if [[ ! -r "$os_release_file" ]]; then
    return
  fi
  distro_id="$(os_release_value ID)"
  distro_version="$(os_release_value VERSION_ID)"
  distro_like="$(os_release_value ID_LIKE)"
  set_pkg_family
}

set_pkg_family() {
  local id like
  id="$(printf '%s' "$distro_id" | tr '[:upper:]' '[:lower:]')"
  like="$(printf '%s' " $distro_like " | tr '[:upper:]' '[:lower:]')"
  case "$id" in
    ubuntu|debian|linuxmint|pop)
      pkg_family="apt"
      ;;
    fedora|rhel|centos|rocky|almalinux|nobara)
      pkg_family="dnf"
      ;;
    arch|manjaro|endeavouros|garuda|cachyos|omarchy|artix)
      pkg_family="pacman"
      ;;
    *)
      case "$like" in
        *" debian "*|*" ubuntu "*) pkg_family="apt" ;;
        *" fedora "*|*" rhel "*) pkg_family="dnf" ;;
        *" arch "*) pkg_family="pacman" ;;
      esac
      ;;
  esac
}

version_at_least() {
  local have="$1"
  local need="$2"
  local have_parts need_parts i h n
  IFS=. read -r -a have_parts <<< "${have}"
  IFS=. read -r -a need_parts <<< "${need}"
  i=0
  while [[ "$i" -lt 3 ]]; do
    h="${have_parts[$i]:-0}"
    n="${need_parts[$i]:-0}"
    h="${h%%[^0-9]*}"
    n="${n%%[^0-9]*}"
    h="${h:-0}"
    n="${n:-0}"
    if (( 10#$h > 10#$n )); then
      return 0
    fi
    if (( 10#$h < 10#$n )); then
      return 1
    fi
    i=$((i + 1))
  done
  return 0
}

have_soname() {
  local soname="$1"
  if [[ -n "${WFS_INSTALL_LIB_DIR:-}" ]]; then
    [[ -e "${WFS_INSTALL_LIB_DIR}/${soname}" ]]
    return
  fi
  if ! command -v ldconfig >/dev/null 2>&1; then
    echo "ldconfig is not available, so the library check cannot run." >&2
    exit 1
  fi
  # grep -q in a pipefail pipeline can die with SIGPIPE before a match counts.
  ldconfig -p 2>/dev/null | awk -v name="$soname" '$1 == name { found = 1 } END { exit found ? 0 : 1 }'
}

require_supported_wsl() {
  local kernel="" os_id="" os_version="" machine=""
  if [[ ! -r "$proc_version_file" ]]; then
    echo "This looks like WSL, but ${proc_version_file} cannot be read." >&2
    exit 1
  fi
  kernel="$(cat "$proc_version_file")"
  if ! grep -q -i microsoft <<< "$kernel"; then
    echo "WSL_DISTRO_NAME is set, but the kernel is not Microsoft's." >&2
    exit 1
  fi
  if ! grep -q -i wsl2 <<< "$kernel"; then
    echo "This is WSL1. The window needs WSL2." >&2
    echo "From Windows, run: wsl --set-version <distro> 2" >&2
    exit 1
  fi
  if [[ -z "$distro_id" ]]; then
    echo "This looks like WSL, but ${os_release_file} cannot be read." >&2
    exit 1
  fi
  os_id="$(printf '%s' "$distro_id" | tr '[:upper:]' '[:lower:]')"
  os_version="$distro_version"
  case "$os_id" in
    ubuntu)
      if ! version_at_least "$os_version" "22.04"; then
        echo "This installer supports Ubuntu 22.04 or newer, Debian 12 or newer, Fedora 39 or newer, and Arch, on WSL2." >&2
        echo "This system is ubuntu ${os_version:-with no version}." >&2
        exit 1
      fi
      wsl_family="Ubuntu"
      ;;
    debian)
      if ! version_at_least "$os_version" "12"; then
        echo "This installer supports Ubuntu 22.04 or newer, Debian 12 or newer, Fedora 39 or newer, and Arch, on WSL2." >&2
        echo "This system is debian ${os_version:-with no version}." >&2
        exit 1
      fi
      wsl_family="Debian"
      ;;
    fedora)
      if ! version_at_least "$os_version" "39"; then
        echo "This installer supports Ubuntu 22.04 or newer, Debian 12 or newer, Fedora 39 or newer, and Arch, on WSL2." >&2
        echo "This system is fedora ${os_version:-with no version}." >&2
        exit 1
      fi
      wsl_family="Fedora"
      ;;
    arch)
      wsl_family="Arch"
      ;;
    omarchy)
      wsl_family="Omarchy"
      ;;
    *)
      echo "This installer supports Ubuntu 22.04 or newer, Debian 12 or newer, Fedora 39 or newer, and Arch, on WSL2." >&2
      echo "This system is ${os_id:-unknown}." >&2
      exit 1
      ;;
  esac
  machine="${WFS_INSTALL_MACHINE:-$(uname -m)}"
  if [[ "$machine" != "x86_64" ]]; then
    echo "WSL needs an x86_64 distro. This one is ${machine}." >&2
    echo "The official wfs-extract build used here is Linux x86_64." >&2
    exit 1
  fi
  if [[ ! -d "$wslg_dir" ]]; then
    echo "WSLg is not running. The window needs Windows 11 with WSLg." >&2
    exit 1
  fi
}

package_for_soname() {
  case "${pkg_family}:$1" in
    apt:libxcb-cursor.so.0) printf '%s\n' libxcb-cursor0 ;;
    apt:libxkbcommon.so.0) printf '%s\n' libxkbcommon0 ;;
    apt:libxkbcommon-x11.so.0) printf '%s\n' libxkbcommon-x11-0 ;;
    apt:libEGL.so.1) printf '%s\n' libegl1 ;;
    apt:libGL.so.1) printf '%s\n' libgl1 ;;
    apt:libfontconfig.so.1) printf '%s\n' libfontconfig1 ;;
    apt:libpulse.so.0) printf '%s\n' libpulse0 ;;
    dnf:libxcb-cursor.so.0) printf '%s\n' xcb-util-cursor ;;
    dnf:libxkbcommon.so.0) printf '%s\n' libxkbcommon ;;
    dnf:libxkbcommon-x11.so.0) printf '%s\n' libxkbcommon-x11 ;;
    dnf:libEGL.so.1) printf '%s\n' libglvnd-egl ;;
    dnf:libGL.so.1) printf '%s\n' libglvnd-glx ;;
    dnf:libfontconfig.so.1) printf '%s\n' fontconfig ;;
    dnf:libpulse.so.0) printf '%s\n' pulseaudio-libs ;;
    pacman:libxcb-cursor.so.0) printf '%s\n' xcb-util-cursor ;;
    pacman:libxkbcommon.so.0) printf '%s\n' libxkbcommon ;;
    pacman:libxkbcommon-x11.so.0) printf '%s\n' libxkbcommon-x11 ;;
    pacman:libEGL.so.1) printf '%s\n' libglvnd ;;
    pacman:libGL.so.1) printf '%s\n' libglvnd ;;
    pacman:libfontconfig.so.1) printf '%s\n' fontconfig ;;
    pacman:libpulse.so.0) printf '%s\n' libpulse ;;
    *) return 1 ;;
  esac
}

require_libraries() {
  local soname package missing="" seen=" "
  # libxcb-cursor.so.0 is linked by Qt's xcb plugin. Wayland does not
  # load it. The check stays so an X11 session is not left unable to open.
  local sonames=(
    libxcb-cursor.so.0
    libxkbcommon.so.0
    libxkbcommon-x11.so.0
    libEGL.so.1
    libGL.so.1
    libfontconfig.so.1
    libpulse.so.0
  )
  for soname in "${sonames[@]}"; do
    if have_soname "$soname"; then
      continue
    fi
    package="$(package_for_soname "$soname")" || continue
    case "$seen" in
      *" ${package} "*) continue ;;
    esac
    missing="${missing} ${package}"
    seen="${seen}${package} "
  done
  if [[ -z "$missing" ]]; then
    return
  fi
  echo "This system is missing libraries the window needs." >&2
  case "$pkg_family" in
    apt) echo "sudo apt install${missing}" >&2 ;;
    dnf) echo "sudo dnf install${missing}" >&2 ;;
    pacman) echo "sudo pacman -S --needed${missing}" >&2 ;;
  esac
  exit 1
}

refuse_32bit() {
  local machine="${WFS_INSTALL_MACHINE:-$(uname -m)}"
  case "$machine" in
    i386|i486|i586|i686)
      echo "32-bit x86 is not supported." >&2
      exit 1
      ;;
  esac
}

python_hint() {
  case "$pkg_family" in
    apt) echo "Often: sudo apt install python3 python3-venv python3-pip" >&2 ;;
    dnf) echo "Often: sudo dnf install python3 python3-pip" >&2 ;;
    pacman) echo "Often: sudo pacman -S python python-pip" >&2 ;;
  esac
}

refuse_windows_drive() {
  local path="$1"
  case "$path" in
    /mnt|/mnt/*)
      echo "Put the working directory in the Linux filesystem, not on a Windows drive (/mnt)." >&2
      exit 1
      ;;
  esac
}

read_distro
if [[ -n "$distro_id" ]]; then
  echo "Distro: ${distro_id}${distro_version:+ ${distro_version}}"
fi

if wsl_detected; then
  wsl_session=1
  require_supported_wsl
else
  refuse_32bit
fi

if [[ "${WFS_INSTALL_SKIP_PACKAGES:-}" != "1" && -n "$pkg_family" ]]; then
  require_libraries
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
if [[ "$wsl_session" -eq 1 ]]; then
  refuse_windows_drive "$answer"
fi
mkdir -p "$answer"
work="$(cd "$answer" && pwd)"
if [[ "$wsl_session" -eq 1 ]]; then
  refuse_windows_drive "$work"
fi

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
  if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3.10 or newer is required, and python3 is not on PATH." >&2
    python_hint
    exit 1
  fi
  if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Python 3.10 or newer is required. python3 is older than that." >&2
    python_hint
    exit 1
  fi
  if ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
    echo "python3 cannot create a virtualenv because ensurepip is missing." >&2
    python_hint
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
if [[ "$wsl_session" -eq 1 ]]; then
  # xcb is the WSLg display path. PulseAudio keeps Qt off the distro PipeWire
  # backend, which can hang this process. Menu music itself is not supported.
  launch="cd $(quote "$work") && exec env QT_QPA_PLATFORM=xcb QT_AUDIO_BACKEND=PulseAudio $(quote "$python_bin") -m wfs_studio"
fi
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
if [[ "$wsl_session" -eq 1 ]]; then
  echo "WSL2 ${wsl_family}: the window opens through WSLg with xcb."
  echo "Menu music is not supported on WSL."
fi
