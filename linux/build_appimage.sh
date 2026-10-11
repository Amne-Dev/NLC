#!/bin/bash
set -e

# AppImage Builder Script for New Launcher
# Run this script on a Linux system (Ubuntu 20.04+ recommended) inside the repository root.

APP_NAME="NewLauncher"
BUILD_DIR="build_linux"
DIST_DIR="dist_linux"
APP_DIR="AppDir"
APPIMAGE_OUT="${APP_NAME}-3.0.5-x86_64.AppImage"
APPIMAGE_OUT_ABS="$(pwd)/${APPIMAGE_OUT}"

echo "=== Starting AppImage Build ==="

# 1. Verification
if [ ! -f "alt.py" ]; then
    echo "Error: alt.py not found. Please run this script from the repository root."
    exit 1
fi

# 2. Cleanup
echo "[*] Cleaning previous builds..."
rm -rf "$BUILD_DIR" "$DIST_DIR" "$APP_DIR"
rm -f "$APP_NAME"-*-x86_64.AppImage

# 3. Dependencies
echo "[*] Setting up Virtual Environment..."

if [ ! -d "venv_build" ]; then
    echo "Creating new virtual environment..."
    if ! python3 -m venv venv_build; then
        echo "Error: Failed to create virtual environment."
        echo "Please install the venv package:"
        echo "  Debian/Ubuntu: sudo apt install python3-venv"
        echo "  Fedora: dnf install python3"
        exit 1
    fi
    source venv_build/bin/activate
else
    echo "Using existing virtual environment."
    source venv_build/bin/activate
fi

if ! python -m pip --version >/dev/null 2>&1; then
    echo "[!] pip is missing in venv_build. Attempting to bootstrap with ensurepip..."
    if ! python -m ensurepip --upgrade >/dev/null 2>&1; then
        echo "[!] ensurepip failed. Recreating virtual environment..."
        deactivate >/dev/null 2>&1 || true
        rm -rf venv_build
        python3 -m venv venv_build
        source venv_build/bin/activate
        python -m ensurepip --upgrade >/dev/null 2>&1 || true
    fi
fi

echo "[*] Installing/Verifying Python dependencies..."
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt pyinstaller --quiet

# 4. Build Binary (PyInstaller)
echo "[*] Running PyInstaller..."
# We use the existing alt.spec. 
# PyInstaller on Linux will generate a Linux binary from it.
pyinstaller alt.spec --distpath "$DIST_DIR" --workpath "$BUILD_DIR" --noconfirm --clean

echo "[*] Running PyInstaller for agent..."
pyinstaller agent.spec --distpath "$DIST_DIR" --workpath "$BUILD_DIR" --noconfirm --clean

# Deactivate venv
deactivate

# 5. Prepare AppDir
echo "[*] Creating AppDir..."
mkdir -p "$APP_DIR/usr/bin"
mkdir -p "$APP_DIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$APP_DIR/usr/share/applications"

# 6. Install Files
# Copy binary
echo "[*] Installing binary..."
# Note: Since alt.spec defines a One-File EXE, we take the single file
cp "$DIST_DIR/$APP_NAME" "$APP_DIR/usr/bin/$APP_NAME"
chmod +x "$APP_DIR/usr/bin/$APP_NAME"

# Copy background agent binary
echo "[*] Installing background agent..."
cp "$DIST_DIR/agent" "$APP_DIR/usr/bin/agent"
chmod +x "$APP_DIR/usr/bin/agent"

if [ ! -x "$APP_DIR/usr/bin/agent" ]; then
    echo "Error: agent binary is missing from AppDir (expected $APP_DIR/usr/bin/agent)."
    exit 1
fi

# Copy Icon
echo "[*] Installing icon..."
cp logo.png "$APP_DIR/logo.png"
cp logo.png "$APP_DIR/usr/share/icons/hicolor/256x256/apps/logo.png"

# Copy Desktop File
echo "[*] Installing desktop file..."
cp linux/NewLauncher.desktop "$APP_DIR/NewLauncher.desktop"
# Fix potential Windows CRLF line endings
sed -i 's/\r$//' "$APP_DIR/NewLauncher.desktop"
cp "$APP_DIR/NewLauncher.desktop" "$APP_DIR/usr/share/applications/NewLauncher.desktop"

# 7. Create AppRun
# Since it's a single binary, we can just point AppRun to it, 
# but a script ensures environment variables (like PATH) are sane if needed.
echo "[*] Creating AppRun..."
cat > "$APP_DIR/AppRun" <<EOF
#!/bin/bash
HERE="\$(dirname "\$(readlink -f "\${0}")")"
export PATH="\${HERE}/usr/bin:\${PATH}"
exec "\${HERE}/usr/bin/$APP_NAME" "\$@"
EOF
chmod +x "$APP_DIR/AppRun"

# 8. Build AppImage
echo "[*] Downloading AppImageTool..."
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
if [ ! -s "appimagetool-x86_64.AppImage" ]; then
    echo "[*] Fetching AppImageTool..."
    rm -f appimagetool-x86_64.AppImage
    if command -v wget >/dev/null 2>&1; then
        wget -q -O appimagetool-x86_64.AppImage "$APPIMAGETOOL_URL"
    elif command -v curl >/dev/null 2>&1; then
        curl -L "$APPIMAGETOOL_URL" -o appimagetool-x86_64.AppImage --silent --show-error
    else
        echo "Error: Neither wget nor curl is available to download appimagetool."
        exit 1
    fi
fi

if [ ! -s "appimagetool-x86_64.AppImage" ]; then
    echo "Error: appimagetool-x86_64.AppImage is missing or empty after download."
    echo "Please verify network access, then rerun the build."
    exit 1
fi
chmod +x appimagetool-x86_64.AppImage

echo "[*] Packaging AppImage..."
# ARCH=x86_64 covers most desktop linux users
export ARCH=x86_64

if command -v fusermount >/dev/null 2>&1 || command -v fusermount3 >/dev/null 2>&1; then
    ./appimagetool-x86_64.AppImage "$APP_DIR" "$APPIMAGE_OUT_ABS"
else
    echo "[!] FUSE not detected. Using extracted appimagetool fallback..."
    ./appimagetool-x86_64.AppImage --appimage-extract >/dev/null
    if [ -x "./squashfs-root/AppRun" ]; then
        ./squashfs-root/AppRun "$APP_DIR" "$APPIMAGE_OUT_ABS"
    elif [ -x "./squashfs-root/usr/bin/appimagetool" ]; then
        ./squashfs-root/usr/bin/appimagetool "$APP_DIR" "$APPIMAGE_OUT_ABS"
    else
        echo "Error: Could not locate extracted appimagetool binary."
        exit 1
    fi
    rm -rf squashfs-root
fi

FOUND_APPIMAGE="$(find . -maxdepth 3 -type f -name "$APP_NAME*.AppImage" ! -name "appimagetool-*.AppImage" -print | head -n1 || true)"

if [ -f "$APPIMAGE_OUT_ABS" ]; then
    FOUND_APPIMAGE="$APPIMAGE_OUT_ABS"
fi

if [ -z "$FOUND_APPIMAGE" ] || [ ! -f "$FOUND_APPIMAGE" ]; then
    echo "Error: AppImage packaging reported success, but no launcher AppImage was found."
    echo "Searched in: $(pwd)"
    echo "Expected output: $APPIMAGE_OUT_ABS"
    echo "Available AppImage files:"
    find . -maxdepth 3 -type f -name "*.AppImage" -print || true
    exit 1
fi

echo "=== Build Complete ==="
echo "Generated: $FOUND_APPIMAGE"
