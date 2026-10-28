import sys
from pathlib import Path

# Add packaging/windows to sys.path if not present
cur = Path(__file__).resolve().parent
while cur.parent != cur:
    cand = cur / "packaging" / "windows"
    if cand.is_dir():
        if str(cand) not in sys.path:
            sys.path.insert(0, str(cand))
        break
    cur = cur.parent

from config_healer import (  # type: ignore
    ConfigHealer,
    get_default_v3_config,
    get_default_config_dir,
    discover_candidate_config_paths,
    recover_corrupted_json,
    migrate_legacy_schema,
)

__all__ = [
    "ConfigHealer",
    "get_default_v3_config",
    "get_default_config_dir",
    "discover_candidate_config_paths",
    "recover_corrupted_json",
    "migrate_legacy_schema",
]
