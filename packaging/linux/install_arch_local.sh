#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

INSTALL_DIR="/opt/new-launcher"
APPIMAGE_DEST="${INSTALL_DIR}/NewLauncher.AppImage"
BIN_LINK="/usr/local/bin/newlauncher"
DESKTOP_FILE="/usr/share/applications/newlauncher.desktop"
ICON_DEST="/usr/share/icons/hicolor/256x256/apps/newlauncher.png"

log() {
  echo "[newlauncher-install] $*"
}

die() {
  echo "[newlauncher-install] ERROR: $*" >&2
  exit 1
}

if command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
elif [ "${EUID}" -eq 0 ]; then
  SUDO=""
else
  die "This script needs root privileges. Install sudo or run as root."
fi

find_default_appimage() {
  local latest
  latest="$(find "${REPO_ROOT}" -maxdepth 4 -type f -name 'NewLauncher-*-x86_64.AppImage' ! -name 'appimagetool-*.AppImage' -print | sort -r | head -n1 || true)"
  if [ -n "${latest}" ] && [ -f "${latest}" ]; then
    echo "${latest}"
    return 0
  fi

  if [ -f "${REPO_ROOT}/NewLauncher-1.7-x86_64.AppImage" ]; then
    echo "${REPO_ROOT}/NewLauncher-1.7-x86_64.AppImage"
    return 0
  fi

  return 1
}

APPIMAGE_SRC="${1:-}"
if [ -z "${APPIMAGE_SRC}" ]; then
  APPIMAGE_SRC="$(find_default_appimage || true)"
fi

if [ -z "${APPIMAGE_SRC}" ]; then
  if [ -x "${REPO_ROOT}/linux/build_appimage.sh" ]; then
    log "No AppImage found. Building one now..."
    (cd "${REPO_ROOT}" && bash linux/build_appimage.sh)
    if [ -f "${REPO_ROOT}/NewLauncher-1.7-x86_64.AppImage" ]; then
      APPIMAGE_SRC="${REPO_ROOT}/NewLauncher-1.7-x86_64.AppImage"
    fi
    if [ -z "${APPIMAGE_SRC}" ]; then
      APPIMAGE_SRC="$(find_default_appimage || true)"
    fi
  fi
fi

if [ -z "${APPIMAGE_SRC}" ]; then
  log "No AppImage detected in ${REPO_ROOT}."
  log "Current *.AppImage files:"
  ls -1 "${REPO_ROOT}"/*.AppImage 2>/dev/null || true
  die "No AppImage found or built. Run: bash linux/build_appimage.sh, then retry installer."
fi

if [ ! -f "${APPIMAGE_SRC}" ]; then
  die "AppImage not found: ${APPIMAGE_SRC}"
fi

if [ ! -f "${REPO_ROOT}/logo.png" ]; then
  die "logo.png not found in repo root (${REPO_ROOT})"
fi

if ! command -v pacman >/dev/null 2>&1; then
  die "This installer is for Arch Linux (pacman not found)."
fi

log "Installing runtime dependency (tk)..."
${SUDO} pacman -Sy --needed --noconfirm tk

log "Creating install directories..."
${SUDO} mkdir -p "${INSTALL_DIR}"
${SUDO} mkdir -p "$(dirname "${ICON_DEST}")"
${SUDO} mkdir -p "$(dirname "${BIN_LINK}")"

log "Installing AppImage to ${APPIMAGE_DEST}..."
${SUDO} cp "${APPIMAGE_SRC}" "${APPIMAGE_DEST}"
${SUDO} chmod 755 "${APPIMAGE_DEST}"

log "Installing icon..."
${SUDO} cp "${REPO_ROOT}/logo.png" "${ICON_DEST}"
${SUDO} chmod 644 "${ICON_DEST}"

log "Creating launcher symlink ${BIN_LINK}..."
${SUDO} ln -sf "${APPIMAGE_DEST}" "${BIN_LINK}"

log "Writing desktop entry..."
${SUDO} tee "${DESKTOP_FILE}" >/dev/null <<EOF
[Desktop Entry]
Type=Application
Name=New Launcher
Comment=A lightweight Minecraft Launcher
Exec=${APPIMAGE_DEST}
Icon=newlauncher
Categories=Game;
Terminal=false
StartupNotify=true
EOF
${SUDO} chmod 644 "${DESKTOP_FILE}"

if command -v update-desktop-database >/dev/null 2>&1; then
  log "Refreshing desktop database..."
  ${SUDO} update-desktop-database /usr/share/applications || true
fi

log "Done."
log "Run from terminal: newlauncher"
log "Or launch from your app menu: New Launcher"
log "Uninstall with: ${SUDO} rm -f '${BIN_LINK}' '${DESKTOP_FILE}' '${ICON_DEST}' && ${SUDO} rm -rf '${INSTALL_DIR}'"
