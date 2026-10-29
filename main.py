# Ny-Luna Core (NLC) - Main Entry Point
import sys
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def main() -> int:
    if "--agent" in sys.argv or "--backend" in sys.argv:
        # Launch headless Python agent directly
        backend_dir = REPO_ROOT / "src" / "backend"
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))
        from agent import main as agent_main
        return agent_main()

    # Search for compiled release or debug Slint binary (cross-platform)
    candidates = [
        REPO_ROOT / "dist" / "NyLuna.exe",
        REPO_ROOT / "dist" / "NyLuna",
        REPO_ROOT / "dist" / "nlc-ui.exe",
        REPO_ROOT / "dist" / "nlc-ui",
        REPO_ROOT / "src" / "frontend" / "target" / "release" / "nlc-ui",
        REPO_ROOT / "src" / "frontend" / "target" / "debug" / "nlc-ui",
        REPO_ROOT / "src" / "frontend" / "target" / "x86_64-pc-windows-gnullvm" / "release" / "nlc-ui.exe",
        REPO_ROOT / "src" / "frontend" / "target" / "release" / "nlc-ui.exe",
        REPO_ROOT / "src" / "frontend" / "target" / "debug" / "nlc-ui.exe",
    ]
    for exe in candidates:
        if exe.is_file():
            return subprocess.call([str(exe)] + sys.argv[1:])

    # Fallback to cargo run in src/frontend
    print("[Ny-Luna] Binary not found. Running via cargo...")
    cargo_cmd = ["cargo", "run", "--manifest-path", str(REPO_ROOT / "src" / "frontend" / "Cargo.toml")]
    return subprocess.call(cargo_cmd + ["--"] + sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
