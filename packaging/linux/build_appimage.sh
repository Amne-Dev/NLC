#!/bin/bash
set -e

# AppImage Builder Script for New Launcher (Ny-Luna Core)
# Run this script on a Linux system (Ubuntu 20.04+ or modern Linux) inside the repository root.

APP_NAME="NewLauncher"
BUILD_DIR="build_linux"
DIST_DIR="dist_linux"
APP_DIR="AppDir"

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

APP_VERSION="$(cat VERSION 2>/dev/null || echo "4.0.2")"
APP_VERSION="${APP_VERSION//[[:space:]]/}"
APPIMAGE_OUT="${APP_NAME}-${APP_VERSION}-x86_64.AppImage"
APPIMAGE_OUT_ABS="$(pwd)/${APPIMAGE_OUT}"

# 1. Cleanup
echo "[*] Cleaning previous builds..."
rm -rf "$BUILD_DIR" "$DIST_DIR" "$APP_DIR"
rm -f "$APP_NAME"-*-x86_64.AppImage

# 2. Build Rust Slint UI Frontend
echo "[*] Checking Rust/Cargo toolchain..."
if ! command -v cargo >/dev/null 2>&1; then
    echo "Error: cargo is required to build the frontend. Please install rustup / cargo."
    exit 1
fi

echo "[*] Compiling Slint UI frontend (Release)..."
cargo build --release --manifest-path src/frontend/Cargo.toml
UI_BIN="src/frontend/target/release/nlc-ui"
if [ ! -f "$UI_BIN" ]; then
    echo "Error: Compiled frontend binary not found at $UI_BIN"
    exit 1
fi

# 3. Setup Python Virtual Environment for Agent Packaging
echo "[*] Setting up Python environment..."
if [ ! -d "venv_build" ]; then
    echo "Creating virtual environment..."
    if ! python3 -m venv venv_build; then
        echo "Error: Failed to create virtual environment."
        echo "Please install the venv package:"
        echo "  Debian/Ubuntu: sudo apt install python3-venv python3-pip"
        echo "  Fedora: dnf install python3"
        echo "  Arch: pacman -S python"
        exit 1
    fi
fi

source venv_build/bin/activate

echo "[*] Installing build requirements..."
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt pyinstaller --quiet

# 4. Build Agent with PyInstaller
echo "[*] Packaging Python agent backend..."
pyinstaller src/backend/agent.spec --distpath "$DIST_DIR" --workpath "$BUILD_DIR" --noconfirm --clean

deactivate

# 5. Prepare AppDir
echo "[*] Assembling AppDir structure..."
mkdir -p "$APP_DIR/usr/bin"
mkdir -p "$APP_DIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$APP_DIR/usr/share/applications"

# Copy binaries
echo "[*] Copying binaries..."
cp "$UI_BIN" "$APP_DIR/usr/bin/$APP_NAME"
chmod +x "$APP_DIR/usr/bin/$APP_NAME"
cp "$UI_BIN" "$APP_DIR/usr/bin/nlc"
chmod +x "$APP_DIR/usr/bin/nlc"
cp "$UI_BIN" "$APP_DIR/usr/bin/newlauncher"
chmod +x "$APP_DIR/usr/bin/newlauncher"
cp "$UI_BIN" "$APP_DIR/usr/bin/nlc-ui"
chmod +x "$APP_DIR/usr/bin/nlc-ui"

cp "$DIST_DIR/agent" "$APP_DIR/usr/bin/agent"
chmod +x "$APP_DIR/usr/bin/agent"
cp "$DIST_DIR/agent" "$APP_DIR/agent"
chmod +x "$APP_DIR/agent"

# Copy VERSION metadata
if [ -f "VERSION" ]; then
    cp VERSION "$APP_DIR/VERSION"
    cp VERSION "$APP_DIR/usr/bin/VERSION"
fi

# Copy icons
echo "[*] Installing icons..."
cp logo.png "$APP_DIR/logo.png"
cp logo.png "$APP_DIR/nlc.png"
cp logo.png "$APP_DIR/newlauncher.png"
cp logo.png "$APP_DIR/NewLauncher.png"
cp logo.png "$APP_DIR/.DirIcon"
for sz in 16x16 22x22 24x24 32x32 48x48 64x64 128x128 256x256 scalable; do
    mkdir -p "$APP_DIR/usr/share/icons/hicolor/${sz}/apps"
    cp logo.png "$APP_DIR/usr/share/icons/hicolor/${sz}/apps/nlc.png"
    cp logo.png "$APP_DIR/usr/share/icons/hicolor/${sz}/apps/newlauncher.png"
    cp logo.png "$APP_DIR/usr/share/icons/hicolor/${sz}/apps/NewLauncher.png"
done

# Copy launcher assets, icons, and wallpapers into AppDir
echo "[*] Bundling launcher assets, icons, and wallpapers..."
if [ -d "icons" ]; then
    cp -r "icons" "$APP_DIR/icons"
    cp -r "icons" "$APP_DIR/usr/bin/icons"
fi
if [ -d "wallpapers" ]; then
    cp -r "wallpapers" "$APP_DIR/wallpapers"
    cp -r "wallpapers" "$APP_DIR/usr/bin/wallpapers"
fi
if [ -d "assets" ]; then
    cp -r "assets" "$APP_DIR/assets"
    cp -r "assets" "$APP_DIR/usr/bin/assets"
fi

# Copy Desktop File
echo "[*] Installing desktop entry..."
cp packaging/linux/NewLauncher.desktop "$APP_DIR/NewLauncher.desktop"
sed -i 's/\r$//' "$APP_DIR/NewLauncher.desktop"
cp "$APP_DIR/NewLauncher.desktop" "$APP_DIR/nlc.desktop"
cp "$APP_DIR/NewLauncher.desktop" "$APP_DIR/usr/share/applications/NewLauncher.desktop"
cp "$APP_DIR/NewLauncher.desktop" "$APP_DIR/usr/share/applications/nlc.desktop"

# 6. Create AppRun launcher script
echo "[*] Writing AppRun..."
cat > "$APP_DIR/AppRun" <<EOF
#!/bin/bash
export APPIMAGELAUNCHER_DISABLE=1
HERE="\$(dirname "\$(readlink -f "\${0}")")"
export APPDIR="\${HERE}"
export PATH="\${HERE}/usr/bin:\${PATH}"
export LD_LIBRARY_PATH="\${HERE}/usr/lib:\${LD_LIBRARY_PATH}"
exec "\${HERE}/usr/bin/nlc" "\$@"
EOF
chmod +x "$APP_DIR/AppRun"

# 7. Package AppImage with appimagetool
echo "[*] Checking AppImageTool..."
APPIMAGETOOL="packaging/linux/appimagetool-x86_64.AppImage"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
if [ ! -s "$APPIMAGETOOL" ]; then
    echo "[*] Fetching AppImageTool..."
    rm -f "$APPIMAGETOOL"
    if command -v wget >/dev/null 2>&1; then
        wget -q -O "$APPIMAGETOOL" "$APPIMAGETOOL_URL"
    elif command -v curl >/dev/null 2>&1; then
        curl -L "$APPIMAGETOOL_URL" -o "$APPIMAGETOOL" --silent --show-error
    else
        echo "Error: Neither wget nor curl is available to download appimagetool."
        exit 1
    fi
fi

chmod +x "$APPIMAGETOOL"

echo "[*] Packaging AppImage..."
export ARCH=x86_64

if command -v fusermount >/dev/null 2>&1 || command -v fusermount3 >/dev/null 2>&1; then
    ./"$APPIMAGETOOL" "$APP_DIR" "$APPIMAGE_OUT_ABS"
else
    echo "[!] FUSE not detected. Using extracted appimagetool fallback..."
    ./"$APPIMAGETOOL" --appimage-extract >/dev/null
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

if [ ! -f "$APPIMAGE_OUT_ABS" ]; then
    echo "Error: AppImage file was not generated at $APPIMAGE_OUT_ABS"
    exit 1
fi

echo "=== Build Complete ==="
echo "Generated: $APPIMAGE_OUT_ABS"
