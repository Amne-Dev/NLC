#!/usr/bin/env bash
#
# Launches the New-Launcher development environment on Linux.
# Verifies Python environment (.venv or system python3), compiles/checks
# the Slint Rust frontend, cleans up conflicting processes, and runs the launcher.
#
# Usage:
#   ./scripts/run_dev.sh [--release] [--no-build] [--clean] [--check-only]
#

set -e

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

RELEASE=false
NO_BUILD=false
CLEAN=false
CHECK_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --release|-release|-Release)
            RELEASE=true
            ;;
        --no-build|-no-build|-NoBuild)
            NO_BUILD=true
            ;;
        --clean|-clean|-Clean)
            CLEAN=true
            ;;
        --check-only|-check-only|-CheckOnly)
            CHECK_ONLY=true
            ;;
        --help|-h)
            echo "Usage: $0 [--release] [--no-build] [--clean] [--check-only]"
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg"
            exit 1
            ;;
    esac
done

echo "============================================================"
echo "         NEW LAUNCHER - LINUX DEVELOPMENT RUNNER            "
echo "============================================================"
echo "Project Root : $PROJECT_ROOT"

# 0. Clean conflicting or stale processes
if [ "$CLEAN" = true ]; then
    echo "[Clean] Terminating any existing launcher or agent processes..."
    pkill -f "nlc-ui" 2>/dev/null || true
    pkill -f "src/backend/agent.py" 2>/dev/null || true
fi

# 1. Check Python Environment
echo "[1/3] Checking Python environment..."
if [ -f "$PROJECT_ROOT/.venv/bin/python" ]; then
    PYTHON_CMD="$PROJECT_ROOT/.venv/bin/python"
    echo "      Using virtual environment python: $PYTHON_CMD"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
    echo "      System Python detected: $($PYTHON_CMD --version)"
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
    echo "      Python detected: $($PYTHON_CMD --version)"
else
    echo "Error: Python 3 is required but not found in PATH or .venv."
    exit 1
fi

# 2. Rust Frontend Verification
echo "[2/3] Checking Rust & Slint toolchain..."
if ! command -v cargo >/dev/null 2>&1; then
    echo "Error: cargo is required. Install from https://rustup.rs"
    exit 1
fi

if [ "$CHECK_ONLY" = true ]; then
    echo "      Running cargo check..."
    cargo check --manifest-path "$PROJECT_ROOT/src/frontend/Cargo.toml"
    echo "Cargo check passed."
    exit 0
fi

# 3. Build or Run
if [ "$NO_BUILD" = true ]; then
    echo "[3/3] Skipping build step (--no-build specified)..."
    TARGET_BIN="$PROJECT_ROOT/src/frontend/target/debug/nlc-ui"
    if [ "$RELEASE" = true ]; then
        TARGET_BIN="$PROJECT_ROOT/src/frontend/target/release/nlc-ui"
    fi
    if [ ! -f "$TARGET_BIN" ]; then
        echo "Error: Binary not found at $TARGET_BIN. Run without --no-build."
        exit 1
    fi
    exec "$TARGET_BIN"
fi

echo "[3/3] Launching New-Launcher..."
if [ "$RELEASE" = true ]; then
    echo "      Building release binary..."
    cargo build --release --manifest-path "$PROJECT_ROOT/src/frontend/Cargo.toml"
    exec "$PROJECT_ROOT/src/frontend/target/release/nlc-ui"
else
    echo "      Running via cargo run (dev mode)..."
    exec cargo run --manifest-path "$PROJECT_ROOT/src/frontend/Cargo.toml"
fi

