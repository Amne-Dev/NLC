"""
Ny-Luna Core (NLC) - Modular Entry Point
Provides backwards-compatible entry point for tests and packaging.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = REPO_ROOT / "src" / "backend"
for p in (str(REPO_ROOT), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from main import main
from nlc.net.downloader import download_file as _atomic_download

__all__ = ["main", "_atomic_download"]

if __name__ == "__main__":
    sys.exit(main())
