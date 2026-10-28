# Ny-Luna Core (NLC) - Headless Agent Forwarding Shim
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
backend_dir = REPO_ROOT / "src" / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from agent import (
    main,
    handle_modpack_import,
    _safe_resolve_archive_path,
    get_bundled_wallpapers_dir,
    handle_wallpapers_list,
    handle_wallpapers_download,
    handle_wallpapers_delete,
)

if __name__ == "__main__":
    sys.exit(main())
