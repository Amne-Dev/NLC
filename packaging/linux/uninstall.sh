#!/usr/bin/env bash
# ==============================================================================
# Ny-Luna Core (New Launcher) - Linux Uninstaller Script
# ==============================================================================
set -euo pipefail

APP_NAME="Ny-Luna"
BIN_NAME="nlc"
LEGACY_BIN_NAME="newlauncher"
INSTALL_DIR="/opt/new-launcher"
BIN_LINK="/usr/local/bin/${BIN_NAME}"
LEGACY_BIN_LINK="/usr/local/bin/${LEGACY_BIN_NAME}"
DESKTOP_FILE="/usr/share/applications/nlc.desktop"
LEGACY_DESKTOP_FILE="/usr/share/applications/NewLauncher.desktop"

log() {
  echo -e "\033[1;34m[nyluna-uninstall]\033[0m $*"
}

warn() {
  echo -e "\033[1;33m[nyluna-uninstall] WARNING:\033[0m $*" >&2
}

die() {
  echo -e "\033[1;31m[nyluna-uninstall] ERROR:\033[0m $*" >&2
  exit 1
}

echo "============================================================"
echo "          Ny-Luna Core (NLC) - Linux Uninstaller            "
echo "============================================================"
echo ""
echo "This will uninstall Ny-Luna Core from your system:"
echo "  • Desktop entries & application menu shortcuts"
echo "  • Application icons and pixmaps"
echo "  • Wrapper scripts (${BIN_LINK}, ${LEGACY_BIN_LINK})"
echo "  • Installed application files (${INSTALL_DIR})"
echo ""

read -rp "Are you sure you want to proceed with uninstallation? [y/N]: " confirm
case "${confirm}" in
  [yY]|[yY][eE][sS]) ;;
  *)
    echo "Uninstallation cancelled."
    exit 0
    ;;
esac

echo ""
read -rp "Do you also want to remove personal data, instances, and configurations (~/.nlc)? [y/N]: " purge_confirm
PURGE_DATA=0
case "${purge_confirm}" in
  [yY]|[yY][eE][sS]) PURGE_DATA=1 ;;
  *) PURGE_DATA=0 ;;
esac

# Determine privilege elevation tool
if [ "${EUID}" -eq 0 ]; then
  SUDO=""
elif command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
else
  die "This uninstaller requires administrative privileges. Please install sudo or run as root."
fi

log "Removing system launchers and desktop entries..."
${SUDO} rm -f "${BIN_LINK}" "${LEGACY_BIN_LINK}" "${DESKTOP_FILE}" "${LEGACY_DESKTOP_FILE}"

log "Removing system icons and pixmaps..."
for sz in 16x16 22x22 24x24 32x32 48x48 64x64 128x128 256x256 scalable; do
  ${SUDO} rm -f "/usr/share/icons/hicolor/${sz}/apps/nlc.png" \
                "/usr/share/icons/hicolor/${sz}/apps/newlauncher.png" \
                "/usr/share/icons/hicolor/${sz}/apps/NewLauncher.png"
done

${SUDO} rm -f /usr/share/pixmaps/nlc.png /usr/share/pixmaps/newlauncher.png /usr/share/pixmaps/NewLauncher.png

log "Removing installed application directory ${INSTALL_DIR}..."
${SUDO} rm -rf "${INSTALL_DIR}"

# Remove user-level desktop files if present
USER_HOME="${HOME:-$(getent passwd "${USER:-root}" | cut -d: -f6)}"
if [ -d "${USER_HOME}" ]; then
  rm -f "${USER_HOME}/.local/share/applications/nlc.desktop" \
        "${USER_HOME}/.local/share/applications/NewLauncher.desktop"

  for sz in 16x16 22x22 24x24 32x32 48x48 64x64 128x128 256x256 scalable; do
    rm -f "${USER_HOME}/.local/share/icons/hicolor/${sz}/apps/nlc.png" \
          "${USER_HOME}/.local/share/icons/hicolor/${sz}/apps/newlauncher.png" \
          "${USER_HOME}/.local/share/icons/hicolor/${sz}/apps/NewLauncher.png"
  done

  if [ "${PURGE_DATA}" -eq 1 ] && [ -d "${USER_HOME}/.nlc" ]; then
    log "Purging user data directory ${USER_HOME}/.nlc..."
    rm -rf "${USER_HOME}/.nlc"
  fi
fi

# Refresh desktop & icon databases
if command -v update-desktop-database >/dev/null 2>&1; then
  ${SUDO} update-desktop-database /usr/share/applications || true
  if [ -d "${USER_HOME}/.local/share/applications" ]; then
    update-desktop-database "${USER_HOME}/.local/share/applications" 2>/dev/null || true
  fi
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  ${SUDO} gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi

if command -v kbuildsycoca6 >/dev/null 2>&1; then
  kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
elif command -v kbuildsycoca5 >/dev/null 2>&1; then
  kbuildsycoca5 --noincremental >/dev/null 2>&1 || true
fi

echo ""
echo "============================================================"
echo " ✓ Ny-Luna Core has been successfully uninstalled.          "
echo "============================================================"

