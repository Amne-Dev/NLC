#!/usr/bin/env bash
# ==============================================================================
# Ny-Luna Core (New Launcher) - Universal Linux Installer
# Supports: Arch Linux, Manjaro, EndeavourOS, Debian, Ubuntu, Linux Mint, Pop!_OS
# ==============================================================================
set -euo pipefail

APP_NAME="Ny-Luna"
BIN_NAME="nlc"
LEGACY_BIN_NAME="newlauncher"
INSTALL_DIR="/opt/new-launcher"
APPIMAGE_DEST="${INSTALL_DIR}/NewLauncher.AppImage"
BIN_LINK="/usr/local/bin/${BIN_NAME}"
LEGACY_BIN_LINK="/usr/local/bin/${LEGACY_BIN_NAME}"
DESKTOP_FILE="/usr/share/applications/nlc.desktop"
ICON_DEST="/usr/share/icons/hicolor/256x256/apps/newlauncher.png"
PIXMAP_DEST="/usr/share/pixmaps/newlauncher.png"
GITHUB_REPO="Amne-Dev/NLC"

log() {
  echo -e "\033[1;34m[nyluna-install]\033[0m $*"
}

warn() {
  echo -e "\033[1;33m[nyluna-install] WARNING:\033[0m $*" >&2
}

die() {
  echo -e "\033[1;31m[nyluna-install] ERROR:\033[0m $*" >&2
  exit 1
}

# Determine privilege elevation tool
if [ "${EUID}" -eq 0 ]; then
  SUDO=""
elif command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  die "This installer requires administrative privileges. Please install sudo or run as root."
fi

# 1. Detect Package Manager & Distro Family
DISTRO_FAMILY="unknown"
if command -v pacman >/dev/null 2>&1; then
  DISTRO_FAMILY="arch"
elif command -v apt-get >/dev/null 2>&1; then
  DISTRO_FAMILY="debian"
fi

log "Detected system family: ${DISTRO_FAMILY}"

# 2. Install Distro Prerequisites (FUSE2 for AppImage execution & xdg-utils)
case "${DISTRO_FAMILY}" in
  arch)
    log "Ensuring system dependencies (fuse2, xdg-utils, curl) via pacman..."
    ${SUDO} pacman -Sy --needed --noconfirm fuse2 xdg-utils curl || warn "Could not install all pacman packages automatically. Continuing..."
    ;;
  debian)
    log "Ensuring system dependencies via apt..."
    ${SUDO} apt-get update -qq || true
    # Ubuntu 24.04+ renamed libfuse2 to libfuse2t64, handle both
    if ${SUDO} apt-get install -y -qq libfuse2t64 >/dev/null 2>&1; then
      log "Installed libfuse2t64."
    elif ${SUDO} apt-get install -y -qq libfuse2 >/dev/null 2>&1; then
      log "Installed libfuse2."
    else
      warn "FUSE2 library (libfuse2/libfuse2t64) could not be automatically installed. AppImages might require it to run."
    fi
    ${SUDO} apt-get install -y -qq xdg-utils curl >/dev/null 2>&1 || true
    ;;
  *)
    warn "Unrecognized package manager. Ensure libfuse2 (FUSE 2 runtime) and xdg-utils are installed."
    ;;
esac

# 3. Locate or Download AppImage
APPIMAGE_SRC="${1:-}"
TEMP_DIR=""

cleanup() {
  if [ -n "${TEMP_DIR}" ] && [ -d "${TEMP_DIR}" ]; then
    rm -rf "${TEMP_DIR}"
  fi
}
trap cleanup EXIT

REPO_ROOT=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  CANDIDATE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." 2>/dev/null && pwd || true)"
  if [ -f "${CANDIDATE}/VERSION" ] && [ -d "${CANDIDATE}/src/frontend" ]; then
    REPO_ROOT="${CANDIDATE}"
  fi
fi

find_local_appimage() {
  if [ -n "${REPO_ROOT}" ] && [ -d "${REPO_ROOT}" ]; then
    local match
    match="$(find "${REPO_ROOT}" -maxdepth 4 -type f -name 'NewLauncher-*-x86_64.AppImage' ! -name 'appimagetool-*.AppImage' 2>/dev/null | sort -rV | head -n1 || true)"
    if [ -n "${match}" ] && [ -f "${match}" ]; then
      echo "${match}"
      return 0
    fi
  fi
  return 1
}

if [ -z "${APPIMAGE_SRC}" ]; then
  APPIMAGE_SRC="$(find_local_appimage || true)"
fi

if [ -z "${APPIMAGE_SRC}" ]; then
  log "No local AppImage specified. Downloading latest release from GitHub (${GITHUB_REPO})..."
  TEMP_DIR="$(mktemp -d)"
  DOWNLOAD_FILE="${TEMP_DIR}/NewLauncher.AppImage"

  # Query releases (including pre-releases) to find the newest release with a Linux AppImage asset
  RELEASES_JSON="$(curl -fsSL "https://api.github.com/repos/${GITHUB_REPO}/releases" 2>/dev/null || true)"
  DOWNLOAD_URL="$(echo "${RELEASES_JSON}" | grep -o 'https://[^"]*NewLauncher-[^"]*-x86_64\.AppImage' | head -n1 || true)"

  if [ -z "${DOWNLOAD_URL}" ]; then
    LATEST_TAG="$(echo "${RELEASES_JSON}" | grep -o '"tag_name": *"[^"]*"' | head -n1 | cut -d'"' -f4 || echo "v4.0.1")"
    DOWNLOAD_URL="https://github.com/${GITHUB_REPO}/releases/download/${LATEST_TAG}/NewLauncher-${LATEST_TAG#v}-x86_64.AppImage"
  fi

  log "Downloading from: ${DOWNLOAD_URL}..."
  if ! curl -fSL --progress-bar "${DOWNLOAD_URL}" -o "${DOWNLOAD_FILE}"; then
    die "Failed to download AppImage from ${DOWNLOAD_URL}. Check your internet connection, release assets on GitHub, or supply a local file path: install.sh <path-to-appimage>"
  fi
  APPIMAGE_SRC="${DOWNLOAD_FILE}"
fi

if [ ! -f "${APPIMAGE_SRC}" ]; then
  die "AppImage binary not found: ${APPIMAGE_SRC}"
fi

# 4. Prepare Destination & Copy Files
log "Creating install directories under ${INSTALL_DIR}..."
${SUDO} mkdir -p "${INSTALL_DIR}"
${SUDO} mkdir -p "$(dirname "${ICON_DEST}")"
${SUDO} mkdir -p "$(dirname "${PIXMAP_DEST}")"
${SUDO} mkdir -p "$(dirname "${BIN_LINK}")"
${SUDO} mkdir -p "$(dirname "${DESKTOP_FILE}")"

log "Installing AppImage to ${APPIMAGE_DEST}..."
${SUDO} cp -f "${APPIMAGE_SRC}" "${APPIMAGE_DEST}"
${SUDO} chmod 755 "${APPIMAGE_DEST}"

# 5. Icon Installation
ICON_SRC=""
if [ -n "${REPO_ROOT}" ] && [ -f "${REPO_ROOT}/logo.png" ]; then
  ICON_SRC="${REPO_ROOT}/logo.png"
else
  # Extract logo from AppImage or fetch from raw repo
  log "Retrieving application icon..."
  ICON_TEMP="${TEMP_DIR:-/tmp}/newlauncher_logo.png"
  if curl -fsSL "https://raw.githubusercontent.com/${GITHUB_REPO}/main/logo.png" -o "${ICON_TEMP}" 2>/dev/null; then
    ICON_SRC="${ICON_TEMP}"
  fi
fi

if [ -n "${ICON_SRC}" ] && [ -f "${ICON_SRC}" ]; then
  for sz in 16x16 22x22 24x24 32x32 48x48 64x64 128x128 256x256 scalable; do
    ${SUDO} mkdir -p "/usr/share/icons/hicolor/${sz}/apps"
    ${SUDO} cp -f "${ICON_SRC}" "/usr/share/icons/hicolor/${sz}/apps/nlc.png"
    ${SUDO} cp -f "${ICON_SRC}" "/usr/share/icons/hicolor/${sz}/apps/newlauncher.png"
    ${SUDO} cp -f "${ICON_SRC}" "/usr/share/icons/hicolor/${sz}/apps/NewLauncher.png"
    ${SUDO} chmod 644 "/usr/share/icons/hicolor/${sz}/apps/nlc.png" "/usr/share/icons/hicolor/${sz}/apps/newlauncher.png" "/usr/share/icons/hicolor/${sz}/apps/NewLauncher.png"
  done

  ${SUDO} mkdir -p /usr/share/pixmaps
  ${SUDO} cp -f "${ICON_SRC}" /usr/share/pixmaps/nlc.png
  ${SUDO} cp -f "${ICON_SRC}" /usr/share/pixmaps/newlauncher.png
  ${SUDO} cp -f "${ICON_SRC}" /usr/share/pixmaps/NewLauncher.png
  ${SUDO} chmod 644 /usr/share/pixmaps/nlc.png /usr/share/pixmaps/newlauncher.png /usr/share/pixmaps/NewLauncher.png
fi

# 6. Create Binary Launchers
log "Creating executable wrapper ${BIN_LINK} (and ${LEGACY_BIN_LINK} for compatibility)..."
${SUDO} tee "${BIN_LINK}" >/dev/null <<EOF
#!/bin/sh
export APPIMAGELAUNCHER_DISABLE=1
exec "${APPIMAGE_DEST}" "\$@"
EOF
${SUDO} chmod 755 "${BIN_LINK}"
${SUDO} ln -sf "${BIN_NAME}" "${LEGACY_BIN_LINK}"

# 7. Write Desktop Entry
log "Installing desktop launcher entry..."
${SUDO} tee "${DESKTOP_FILE}" >/dev/null <<EOF
[Desktop Entry]
Type=Application
Name=Ny-Luna
GenericName=Minecraft Launcher
Comment=High-performance Minecraft Java launcher with Slint UI and modular core
Exec=${BIN_LINK} %U
Icon=nlc
Terminal=false
Categories=Game;ActionGame;
Keywords=minecraft;game;launcher;mc;craft;nlc;nyluna;ny-luna;
StartupNotify=false
StartupWMClass=nlc
EOF
${SUDO} chmod 644 "${DESKTOP_FILE}"
${SUDO} cp -f "${DESKTOP_FILE}" "/usr/share/applications/NewLauncher.desktop"

# 8. Update Desktop & Icon Databases
if command -v update-desktop-database >/dev/null 2>&1; then
  ${SUDO} update-desktop-database /usr/share/applications || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  ${SUDO} gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true
fi

if command -v kbuildsycoca6 >/dev/null 2>&1; then
  kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
elif command -v kbuildsycoca5 >/dev/null 2>&1; then
  kbuildsycoca5 --noincremental >/dev/null 2>&1 || true
fi

log "================================================================="
log "Installation Successful! ✓"
log "Launch from terminal:   ${BIN_NAME} (or ${LEGACY_BIN_NAME})"
log "Launch from menu:       Application Menu -> Games -> Ny-Luna"
log ""
log "To uninstall, run:"
log "  ${SUDO} rm -f '${BIN_LINK}' '${LEGACY_BIN_LINK}' '${DESKTOP_FILE}' '/usr/share/applications/NewLauncher.desktop' /usr/share/icons/hicolor/256x256/apps/{nlc,newlauncher,NewLauncher}.png /usr/share/pixmaps/{nlc,newlauncher,NewLauncher}.png && ${SUDO} rm -rf '${INSTALL_DIR}'"
log "================================================================="

