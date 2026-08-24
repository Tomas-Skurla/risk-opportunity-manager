#!/usr/bin/env bash
set -euo pipefail

MODE="${1:---desktop}"

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/setup_os_prereqs.sh [--server-only|--desktop|--headless-gui|--all]

Modes:
  --server-only   Python/build/sqlite/curl/git basics only.
  --desktop       Server basics plus PySide6/Qt GUI runtime libraries.
  --headless-gui  Desktop runtime plus Xvfb/dbus for headless GUI smoke tests.
  --all           Headless GUI plus LibreOffice Calc for CSV manual testing.

Supported package managers:
  apt, dnf, yum, pacman, zypper, apk, brew

Notes:
  - Package names differ by distro; this script is best-effort.
  - If a package name is unavailable, the script skips it where possible.
  - Python dependencies are still installed separately by setup_python_env.sh.
USAGE
}

case "$MODE" in
  --server-only|--desktop|--headless-gui|--all)
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    echo "Unknown mode: $MODE"
    usage
    exit 2
    ;;
esac

have() {
  command -v "$1" >/dev/null 2>&1
}

run_sudo() {
  if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

try_apt_install_one_of() {
  local installed=0
  for pkg in "$@"; do
    if run_sudo apt-get install -y "$pkg"; then
      installed=1
      break
    fi
  done

  if [[ "$installed" -ne 1 ]]; then
    echo "WARNING: none of these apt packages installed successfully: $*"
  fi
}

install_apt() {
  export DEBIAN_FRONTEND=noninteractive

  run_sudo apt-get update

  run_sudo apt-get install -y \
    ca-certificates \
    curl \
    unzip \
    git \
    sqlite3 \
    build-essential \
    python3 \
    python3-venv \
    python3-pip \
    python3-dev

  # Debian/Ubuntu family split/renamed GLib runtime packages across releases.
  try_apt_install_one_of libglib2.0-0 libglib2.0-0t64

  if [[ "$MODE" != "--server-only" ]]; then
    run_sudo apt-get install -y \
      libegl1 \
      libgl1 \
      libfontconfig1 \
      libxkbcommon-x11-0 \
      libxcb1 \
      libxcb-cursor0 \
      libxcb-icccm4 \
      libxcb-image0 \
      libxcb-keysyms1 \
      libxcb-randr0 \
      libxcb-render-util0 \
      libxcb-shape0 \
      libxcb-xfixes0 \
      libxcb-xinerama0 \
      libxcb-render0 \
      libxcb-shm0 \
      libxcb-sync1 \
      libxcb-xkb1 \
      libx11-xcb1
  fi

  if [[ "$MODE" == "--headless-gui" || "$MODE" == "--all" ]]; then
    run_sudo apt-get install -y xvfb dbus-x11
  fi

  if [[ "$MODE" == "--all" ]]; then
    run_sudo apt-get install -y libreoffice-calc || true
  fi
}

install_dnf_like() {
  local pm="$1"

  run_sudo "$pm" install -y \
    ca-certificates \
    curl \
    unzip \
    git \
    sqlite \
    gcc \
    gcc-c++ \
    make \
    python3 \
    python3-pip \
    python3-devel

  if [[ "$MODE" != "--server-only" ]]; then
    run_sudo "$pm" install -y \
      glib2 \
      mesa-libGL \
      mesa-libEGL \
      fontconfig \
      libxkbcommon-x11 \
      libxcb \
      xcb-util \
      xcb-util-cursor \
      xcb-util-image \
      xcb-util-keysyms \
      xcb-util-renderutil \
      libX11-xcb \
      dbus-libs || true
  fi

  if [[ "$MODE" == "--headless-gui" || "$MODE" == "--all" ]]; then
    run_sudo "$pm" install -y xorg-x11-server-Xvfb dbus-x11 || true
  fi

  if [[ "$MODE" == "--all" ]]; then
    run_sudo "$pm" install -y libreoffice-calc || true
  fi
}

install_pacman() {
  run_sudo pacman -Sy --needed --noconfirm \
    ca-certificates \
    curl \
    unzip \
    git \
    sqlite \
    base-devel \
    python \
    python-pip

  if [[ "$MODE" != "--server-only" ]]; then
    run_sudo pacman -S --needed --noconfirm \
      glib2 \
      libglvnd \
      fontconfig \
      libxkbcommon-x11 \
      libxcb \
      xcb-util \
      xcb-util-cursor \
      xcb-util-image \
      xcb-util-keysyms \
      xcb-util-renderutil \
      libx11
  fi

  if [[ "$MODE" == "--headless-gui" || "$MODE" == "--all" ]]; then
    run_sudo pacman -S --needed --noconfirm xorg-server-xvfb dbus
  fi

  if [[ "$MODE" == "--all" ]]; then
    run_sudo pacman -S --needed --noconfirm libreoffice-fresh || true
  fi
}

install_zypper() {
  run_sudo zypper --non-interactive refresh

  run_sudo zypper --non-interactive install \
    ca-certificates \
    curl \
    unzip \
    git \
    sqlite3 \
    gcc \
    gcc-c++ \
    make \
    python3 \
    python3-pip \
    python3-devel

  if [[ "$MODE" != "--server-only" ]]; then
    run_sudo zypper --non-interactive install \
      glib2 \
      Mesa-libGL1 \
      Mesa-libEGL1 \
      fontconfig \
      libxkbcommon-x11-0 \
      libxcb1 \
      libxcb-cursor0 \
      libxcb-icccm4 \
      libxcb-image0 \
      libxcb-keysyms1 \
      libxcb-randr0 \
      libxcb-render-util0 \
      libxcb-shape0 \
      libxcb-xfixes0 \
      libxcb-xinerama0 \
      libX11-xcb1 || true
  fi

  if [[ "$MODE" == "--headless-gui" || "$MODE" == "--all" ]]; then
    run_sudo zypper --non-interactive install xorg-x11-server-extra dbus-1-x11 || true
  fi

  if [[ "$MODE" == "--all" ]]; then
    run_sudo zypper --non-interactive install libreoffice-calc || true
  fi
}

install_apk() {
  run_sudo apk update

  run_sudo apk add \
    ca-certificates \
    curl \
    unzip \
    git \
    sqlite \
    build-base \
    python3 \
    py3-pip \
    python3-dev

  if [[ "$MODE" != "--server-only" ]]; then
    run_sudo apk add \
      glib \
      mesa-gl \
      mesa-egl \
      fontconfig \
      libxkbcommon \
      libxkbcommon-x11 \
      libxcb \
      xcb-util \
      xcb-util-cursor \
      xcb-util-image \
      xcb-util-keysyms \
      xcb-util-renderutil \
      libx11 || true
  fi

  if [[ "$MODE" == "--headless-gui" || "$MODE" == "--all" ]]; then
    run_sudo apk add xvfb dbus-x11 || true
  fi

  if [[ "$MODE" == "--all" ]]; then
    run_sudo apk add libreoffice || true
  fi
}

install_brew() {
  brew update

  brew install \
    python \
    curl \
    unzip \
    git \
    sqlite

  if [[ "$MODE" == "--all" ]]; then
    brew install --cask libreoffice || true
  fi

  echo "macOS note: PySide6 GUI dependencies are normally handled by the wheel/Homebrew frameworks."
}

echo "Detected mode: $MODE"

if have apt-get; then
  echo "Using apt-get."
  install_apt
elif have dnf; then
  echo "Using dnf."
  install_dnf_like dnf
elif have yum; then
  echo "Using yum."
  install_dnf_like yum
elif have pacman; then
  echo "Using pacman."
  install_pacman
elif have zypper; then
  echo "Using zypper."
  install_zypper
elif have apk; then
  echo "Using apk."
  install_apk
elif have brew; then
  echo "Using Homebrew."
  install_brew
else
  echo "ERROR: No supported package manager found."
  echo "Install OS prerequisites manually, then run scripts/setup_python_env.sh."
  exit 1
fi

echo
echo "OS prerequisite setup complete."
echo "Python:"
python3 --version || true

echo
echo "Next:"
echo "  bash scripts/setup_python_env.sh"