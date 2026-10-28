
import logging
from typing import Any, Dict, List, Optional
from nlc.storage.paths import is_version_installed
from nlc.net.http import get_http_session

logger = logging.getLogger(__name__)

INSTALL_MARK = "✅ "
VERSION_MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"

def format_version_display(version_id: str) -> str:
    return f"{INSTALL_MARK}{version_id}" if is_version_installed(version_id) else version_id

def normalize_version_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return value.replace(INSTALL_MARK, "").strip()

def fetch_version_manifest() -> List[Dict[str, Any]]:
    session = get_http_session()
    try:
        resp = session.get(VERSION_MANIFEST_URL, timeout=(5.0, 15.0))
        resp.raise_for_status()
        data = resp.json()
        return data.get("versions", [])
    except Exception as e:
        logger.error("Failed to fetch Minecraft version manifest: %s", e)
        return []

import re
import threading

LOADERS = ["Vanilla", "Fabric", "Forge", "NeoForge", "Quilt"]
MODPACK_LOADERS = ["fabric", "forge", "neoforge", "quilt"]

_VERSION_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()

def clear_version_cache() -> None:
    with _CACHE_LOCK:
        _VERSION_CACHE.clear()

def version_sort_key(v: str):
    """
    Sort key supporting SemVer (1.x.y) and 2026+ CalVer (26.x.y).
    CalVer (26.x) sorts higher than legacy SemVer (1.x).
    """
    clean_v = normalize_version_text(v)
    clean_v = re.sub(r"^(?:vanilla|fabric|neoforge|forge|quilt)\s+", "", clean_v, flags=re.I).strip()
    clean_v = re.sub(r"\s*\([^)]*\)", "", clean_v).strip()
    match = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)$", clean_v)
    if match:
        major = int(match.group(1))
        minor = int(match.group(2)) if match.group(2) is not None else 0
        patch = int(match.group(3)) if match.group(3) is not None else 0
        extra = match.group(4) or ""
        is_release = 1 if extra == "" else 0
        return (major, minor, patch, is_release, extra)
    snap_match = re.match(r"^(\d{2})w(\d{2})([a-z])$", clean_v)
    if snap_match:
        year = int(snap_match.group(1))
        week = int(snap_match.group(2))
        rev = snap_match.group(3)
        return (year, week, 0, 0, rev)
    return (0, 0, 0, 0, clean_v)

def sort_versions(versions: List[str], reverse: bool = True) -> List[str]:
    return sorted(versions, key=version_sort_key, reverse=reverse)

CALVER_2026_RELEASES = ["26.3", "26.2", "26.1"]

FALLBACK_RELEASES = [
    "26.3", "26.2", "26.1",
    "1.21.4", "1.21.3", "1.21.1", "1.21.0",
    "1.20.4", "1.20.2", "1.20.1",
    "1.19.4", "1.19.2", "1.18.2", "1.16.5", "1.12.2", "1.8.9"
]
FALLBACK_SNAPSHOTS = ["25w03a", "24w46a"]

def get_available_loaders() -> List[str]:
    return list(LOADERS)

def get_modpack_loaders() -> List[str]:
    return list(MODPACK_LOADERS)

def get_versions_for_loader(loader: str = "Vanilla", include_snapshots: bool = False) -> Dict[str, Any]:
    normalized_loader = (loader or "Vanilla").strip()
    cache_key = normalized_loader.lower()

    with _CACHE_LOCK:
        if cache_key in _VERSION_CACHE:
            cached = _VERSION_CACHE[cache_key]
            return {
                "loader": normalized_loader,
                "releases": cached["releases"],
                "snapshots": cached["snapshots"] if include_snapshots else [],
                "latest_release": cached.get("latest_release", ""),
                "latest_snapshot": cached.get("latest_snapshot", ""),
                "all": (cached["releases"] + cached["snapshots"]) if include_snapshots else cached["releases"],
            }

    # Fetch fresh
    releases: List[str] = []
    snapshots: List[str] = []
    latest_rel = ""
    latest_snap = ""

    try:
        if cache_key in ("vanilla", "all", ""):
            manifest = fetch_version_manifest()
            for v in manifest:
                vid = v.get("id")
                vtype = v.get("type", "release")
                if not vid:
                    continue
                if vtype == "release":
                    releases.append(vid)
                elif vtype == "snapshot":
                    snapshots.append(vid)
            if releases:
                latest_rel = releases[0]
            if snapshots:
                latest_snap = snapshots[0]

        elif cache_key == "fabric":
            import minecraft_launcher_lib as mll
            fv = mll.fabric.get_all_minecraft_versions()
            for item in fv:
                vid = item.get("version")
                if not vid:
                    continue
                if item.get("stable", True):
                    releases.append(vid)
                else:
                    snapshots.append(vid)
            if releases:
                latest_rel = releases[0]
            if snapshots:
                latest_snap = snapshots[0]

        elif cache_key == "forge":
            import minecraft_launcher_lib as mll
            forge_list = mll.forge.list_forge_versions()
            seen: set = set()
            for fv in forge_list:
                parts = fv.split("-", 1)
                mc = parts[0]
                if mc not in seen:
                    seen.add(mc)
                    releases.append(mc)
            if releases:
                latest_rel = releases[0]

        elif cache_key == "quilt":
            import minecraft_launcher_lib as mll
            qv = mll.quilt.get_all_minecraft_versions()
            for item in qv:
                vid = item.get("version")
                if not vid:
                    continue
                if item.get("stable", True):
                    releases.append(vid)
                else:
                    snapshots.append(vid)
            if releases:
                latest_rel = releases[0]
            if snapshots:
                latest_snap = snapshots[0]

        elif cache_key == "neoforge":
            try:
                import minecraft_launcher_lib.mod_loader as ml
                neo = ml.Neoforge()
                supported = neo.get_minecraft_versions(stable_only=False)
                manifest = fetch_version_manifest()
                released_ids = {v.get("id") for v in manifest if v.get("type") == "release"}
                valid_releases = [v for v in supported if v in released_ids]
                if valid_releases:
                    releases = list(reversed(valid_releases))
                else:
                    releases = list(reversed(supported))
            except Exception as e_neo:
                logger.warning("Error fetching NeoForge versions via mod_loader: %s", e_neo)
                manifest = fetch_version_manifest()
                for v in manifest:
                    vid = v.get("id", "")
                    if v.get("type") == "release" and (vid.startswith("1.2") or vid.startswith("2") or vid.startswith("26.")):
                        releases.append(vid)
            if not releases:
                releases = list(FALLBACK_RELEASES)
            latest_rel = releases[0]

    except Exception as exc:
        logger.warning("Error fetching versions for %s: %s", loader, exc)

    if not releases:
        releases = list(FALLBACK_RELEASES)
    else:
        for calver in CALVER_2026_RELEASES:
            if calver not in releases:
                releases.append(calver)
        releases = sort_versions(releases, reverse=True)

    latest_rel = releases[0] if releases else "26.3"
    if not snapshots:
        snapshots = list(FALLBACK_SNAPSHOTS)
        latest_snap = snapshots[0]

    with _CACHE_LOCK:
        _VERSION_CACHE[cache_key] = {
            "releases": releases,
            "snapshots": snapshots,
            "latest_release": latest_rel,
            "latest_snapshot": latest_snap,
        }

    return {
        "loader": normalized_loader,
        "releases": releases,
        "snapshots": snapshots if include_snapshots else [],
        "latest_release": latest_rel,
        "latest_snapshot": latest_snap,
        "all": (releases + snapshots) if include_snapshots else releases,
    }
