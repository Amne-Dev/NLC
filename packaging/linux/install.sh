#!/usr/bin/env bash
# ==============================================================================
# Ny-Luna Core (New Launcher) - Universal Linux Installer
# Supports: Arch Linux, Manjaro, EndeavourOS, Debian, Ubuntu, Linux Mint, Pop!_OS
# ==============================================================================
set -euo pipefail

APP_NAME="New Launcher"
BIN_NAME="newlauncher"
INSTALL_DIR="/opt/new-launcher"
APPIMAGE_DEST="${INSTALL_DIR}/NewLauncher.AppImage"
BIN_LINK="/usr/local/bin/${BIN_NAME}"
DESKTOP_FILE="/usr/share/applications/newlauncher.desktop"
ICON_DEST="/usr/share/icons/hicolor/256x256/apps/newlauncher.png"
PIXMAP_DEST="/usr/share/pixmaps/newlauncher.png"
GITHUB_REPO="Amne-Dev/NLC"

log() {
  echo -e "\033[1;34m[newlauncher-install]\033[0m $*"
}

warn() {
  echo -e "\033[1;33m[newlauncher-install] WARNING:\033[0m $*" >&2
}

die() {
  echo -e "\033[1;31m[newlauncher-install] ERROR:\033[0m $*" >&2
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

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." 2>/dev/null && pwd || true)"

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

  LATEST_JSON="$(curl -fsSL "https://api.github.com/repos/${GITHUB_REPO}/releases/latest" 2>/dev/null || true)"
  DOWNLOAD_URL="$(echo "${LATEST_JSON}" | grep -o 'https://[^"]*NewLauncher-[^"]*-x86_64\.AppImage' | head -n1 || true)"

  if [ -z "${DOWNLOAD_URL}" ]; then
    # Fallback to direct redirect URL
    DOWNLOAD_URL="https://github.com/${GITHUB_REPO}/releases/latest/download/NewLauncher-4.0.1-x86_64.AppImage"
  fi

  log "Downloading from: ${DOWNLOAD_URL}..."
  if ! curl -fSL --progress-bar "${DOWNLOAD_URL}" -o "${DOWNLOAD_FILE}"; then
    die "Failed to download AppImage from ${DOWNLOAD_URL}. Check your internet connection or supply a local file path."
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
if [ -n "${REPO_ROOT}" ] && [ -f "${REPO_ROOT}/logo.png" ]; then
  ${SUDO} cp -f "${REPO_ROOT}/logo.png" "${ICON_DEST}"
  ${SUDO} cp -f "${REPO_ROOT}/logo.png" "${PIXMAP_DEST}"
  ${SUDO} chmod 644 "${ICON_DEST}" "${PIXMAP_DEST}"
else
  # Extract logo from AppImage or fetch from raw repo
  log "Retrieving application icon..."
  ICON_TEMP="${TEMP_DIR:-/tmp}/newlauncher_logo.png"
  if curl -fsSL "https://raw.githubusercontent.com/${GITHUB_REPO}/main/logo.png" -o "${ICON_TEMP}" 2>/dev/null; then
    ${SUDO} cp -f "${ICON_TEMP}" "${ICON_DEST}"
    ${SUDO} cp -f "${ICON_TEMP}" "${PIXMAP_DEST}"
    ${SUDO} chmod 644 "${ICON_DEST}" "${PIXMAP_DEST}"
    rm -f "${ICON_TEMP}"
  fi
fi

# 6. Create Binary Symlink
log "Creating executable symlink ${BIN_LINK}..."
${SUDO} ln -sf "${APPIMAGE_DEST}" "${BIN_LINK}"

# 7. Write Desktop Entry
log "Installing desktop launcher entry..."
${SUDO} tee "${DESKTOP_FILE}" >/dev/null <<EOF
[Desktop Entry]
Type=Application
Name=New Launcher
GenericName=Minecraft Launcher
Comment=High-performance Minecraft Java launcher with Slint UI and modular core
Exec=${BIN_LINK} %U
Icon=newlauncher
Terminal=false
Categories=Game;ActionGame;
Keywords=minecraft;game;launcher;mc;craft;
StartupNotify=true
StartupWMClass=nlc-ui
EOF
${SUDO} chmod 644 "${DESKTOP_FILE}"

# 8. Update Desktop & Icon Databases
if command -v update-desktop-database >/dev/null 2>&1; then
  ${SUDO} update-desktop-database /usr/share/applications || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  ${SUDO} gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true
fi

log "================================================================="
log "Installation Successful! ✓"
log "Launch from terminal:   ${BIN_NAME}"
log "Launch from menu:       Application Menu -> Games -> New Launcher"
log ""
log "To uninstall, run:"
log "  ${SUDO} rm -f '${BIN_LINK}' '${DESKTOP_FILE}' '${ICON_DEST}' '${PIXMAP_DEST}' && ${SUDO} rm -rf '${INSTALL_DIR}'"
log "================================================================="

