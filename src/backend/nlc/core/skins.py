
import os
import sys
import time
import shutil
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from nlc.storage.paths import get_launcher_data_dir

logger = logging.getLogger(__name__)

# Cache for file hash lookups: (resolved_path_str, mtime, size) -> hash_hex
_SKIN_HASH_CACHE: Dict[Tuple[str, float, int], str] = {}


def is_subpath(child: Union[str, Path], parent: Union[str, Path]) -> bool:
    try:
        c = Path(child).resolve()
        p = Path(parent).resolve()
        return c == p or p in c.parents
    except Exception:
        return False


def compute_skin_hash(image_path: Union[str, Path], use_pixel_data: bool = True) -> str:
    p = Path(image_path).resolve()
    if not p.is_file():
        return ""

    try:
        st = p.stat()
        cache_key = (str(p), st.st_mtime, st.st_size)
        if cache_key in _SKIN_HASH_CACHE:
            return _SKIN_HASH_CACHE[cache_key]
    except Exception:
        cache_key = None

    digest = ""
    if use_pixel_data:
        try:
            from PIL import Image
            with Image.open(p) as img:
                rgba = img.convert("RGBA")
                header = f"{rgba.width}x{rgba.height}:".encode("ascii")
                digest = hashlib.sha256(header + rgba.tobytes()).hexdigest()
        except Exception:
            digest = ""

    if not digest:
        try:
            h = hashlib.sha256()
            with open(p, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
            digest = h.hexdigest()
        except Exception as exc:
            logger.debug("Failed computing file hash for %s: %s", p, exc)
            return ""

    if cache_key and digest:
        _SKIN_HASH_CACHE[cache_key] = digest

    return digest


def get_skins_directory(base_dir: Optional[Union[str, Path]] = None) -> Path:
    if base_dir:
        skins_dir = Path(base_dir) / "skins"
    else:
        skins_dir = Path(get_launcher_data_dir()) / "skins"
    skins_dir.mkdir(parents=True, exist_ok=True)
    return skins_dir.resolve()


def find_duplicate_skin(image_path: Union[str, Path], skins_dir: Union[str, Path]) -> Optional[Path]:
    target_p = Path(image_path).resolve()
    if not target_p.is_file():
        return None

    target_hash = compute_skin_hash(target_p)
    if not target_hash:
        return None

    dir_p = Path(skins_dir).resolve()
    if not dir_p.is_dir():
        return None

    # Scan skins_dir for matching hash
    for item in sorted(dir_p.glob("*.png"), key=lambda f: f.stat().st_mtime):
        item_res = item.resolve()
        if item_res == target_p:
            continue
        if compute_skin_hash(item_res) == target_hash:
            return item_res

    # Also check jpg/jpeg if any exist in skins_dir
    for ext in ("*.jpg", "*.jpeg"):
        for item in sorted(dir_p.glob(ext), key=lambda f: f.stat().st_mtime):
            item_res = item.resolve()
            if item_res == target_p:
                continue
            if compute_skin_hash(item_res) == target_hash:
                return item_res

    return None


def deduplicate_and_reroute_skin(
    path: Union[str, Path],
    skins_dir: Union[str, Path],
    copy_if_new: bool = True
) -> Tuple[str, bool]:
    target_p = Path(path).resolve()
    if not target_p.exists() or not target_p.is_file():
        return str(path), False

    dir_p = Path(skins_dir).resolve()
    dir_p.mkdir(parents=True, exist_ok=True)

    original_match = find_duplicate_skin(target_p, dir_p)
    if original_match:
        # Duplicate detected!
        # If target_p is inside skins_dir and is a distinct file from original_match, remove it.
        if is_subpath(target_p, dir_p) and target_p != original_match:
            try:
                target_p.unlink(missing_ok=True)
                logger.info("Removed duplicate skin file %s -> rerouted to %s", target_p, original_match)
            except Exception as exc:
                logger.warning("Failed removing duplicate skin file %s: %s", target_p, exc)

        return str(original_match), True

    # No duplicate found in skins_dir.
    if copy_if_new and not is_subpath(target_p, dir_p):
        try:
            filename = target_p.name
            stem = target_p.stem
            suffix = target_p.suffix or ".png"
            dest = dir_p / filename
            if dest.exists() and dest != target_p:
                dest = dir_p / f"{stem}_{int(time.time())}{suffix}"
            shutil.copy2(target_p, dest)
            return str(dest), False
        except Exception as exc:
            logger.warning("Could not copy skin to skins directory: %s", exc)

    return str(target_p), False


def _choose_canonical_skin(candidates: List[Path]) -> Path:
    def score(p: Path) -> Tuple[int, float]:
        name = p.stem.lower()
        penalty = 0
        if "_stolen" in name:
            penalty += 10
        if "_copy" in name:
            penalty += 10
        # Check for trailing timestamp e.g. _1729240000
        parts = name.split("_")
        if len(parts) > 1 and parts[-1].isdigit() and len(parts[-1]) >= 9:
            penalty += 5
        try:
            mtime = p.stat().st_mtime
        except Exception:
            mtime = 0.0
        return penalty, mtime

    return min(candidates, key=score)


def cleanup_duplicate_skins(
    skins_dir: Union[str, Path],
    config_data: Optional[Dict[str, Any]] = None
) -> Tuple[Dict[str, str], int]:
    dir_p = Path(skins_dir).resolve()
    if not dir_p.is_dir():
        return {}, 0

    hash_groups: Dict[str, List[Path]] = {}
    for item in dir_p.glob("*.png"):
        if not item.is_file():
            continue
        h = compute_skin_hash(item)
        if h:
            hash_groups.setdefault(h, []).append(item.resolve())

    reroutes: Dict[str, str] = {}
    removed_count = 0

    for h, files in hash_groups.items():
        if len(files) <= 1:
            continue

        canonical = _choose_canonical_skin(files)
        canonical_str = str(canonical)

        for dup in files:
            if dup == canonical:
                continue
            dup_str = str(dup)
            reroutes[dup_str] = canonical_str
            reroutes[dup.name] = canonical_str

            try:
                dup.unlink(missing_ok=True)
                removed_count += 1
                logger.info("Removed duplicate skin %s -> rerouted to original %s", dup_str, canonical_str)
            except Exception as exc:
                logger.warning("Failed removing duplicate skin %s: %s", dup_str, exc)

    # Reroute config references if provided
    if config_data and isinstance(config_data, dict):
        profiles = config_data.get("profiles", [])
        for p in profiles:
            if not isinstance(p, dict):
                continue

            # 1. Active skin_path
            cur_skin = p.get("skin_path", "")
            if cur_skin:
                norm_cur = str(Path(cur_skin).resolve()) if os.path.exists(cur_skin) else cur_skin
                if norm_cur in reroutes:
                    p["skin_path"] = reroutes[norm_cur]
                elif cur_skin in reroutes:
                    p["skin_path"] = reroutes[cur_skin]
                elif os.path.exists(cur_skin):
                    # Check if hash matches canonical in skins_dir
                    chash = compute_skin_hash(cur_skin)
                    if chash in hash_groups and hash_groups[chash]:
                        can_p = str(hash_groups[chash][0])
                        if norm_cur != can_p and not is_subpath(cur_skin, dir_p):
                            p["skin_path"] = can_p

            # 2. skin_history / wardrobe presets
            history = p.get("skin_history", [])
            if isinstance(history, list) and history:
                new_history: List[Any] = []
                seen_hashes: Set[str] = set()

                for item in history:
                    if isinstance(item, str):
                        item_path = item
                        item_model = "classic"
                        item_name = Path(item).stem
                    elif isinstance(item, dict):
                        item_path = item.get("path", "")
                        item_model = item.get("model", "classic")
                        item_name = item.get("name") or Path(item_path).stem
                    else:
                        continue

                    if not item_path:
                        continue

                    # Reroute path if needed
                    norm_path = str(Path(item_path).resolve()) if os.path.exists(item_path) else item_path
                    if norm_path in reroutes:
                        item_path = reroutes[norm_path]
                    elif item_path in reroutes:
                        item_path = reroutes[item_path]

                    # Deduplicate history entries by image hash if file exists
                    if os.path.exists(item_path):
                        ihash = compute_skin_hash(item_path)
                        if ihash:
                            if ihash in seen_hashes:
                                # Duplicate entry in history, skip
                                continue
                            seen_hashes.add(ihash)

                    entry = {
                        "path": item_path,
                        "model": item_model,
                        "name": item_name
                    }
                    new_history.append(entry)

                p["skin_history"] = new_history

        # 3. skin_arm_models mapping
        arm_models = config_data.get("skin_arm_models", {})
        if isinstance(arm_models, dict) and reroutes:
            for old_k, old_v in list(arm_models.items()):
                if old_k in reroutes:
                    new_k = reroutes[old_k]
                    arm_models.setdefault(new_k, old_v)
                    arm_models.setdefault(Path(new_k).name, old_v)

    return reroutes, removed_count
