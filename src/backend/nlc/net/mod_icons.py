
import os
import io
import json
import hashlib
import zipfile
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, Optional, Tuple

from PIL import Image


logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = os.path.expanduser("~/.nlc/cache/mod_icons")
_ICON_EXTRACT_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ModIconExtract")


def extract_icon_from_jar(
    jar_path: str,
    target_size: Tuple[int, int] = (44, 44),
    cache_dir: Optional[str] = None
) -> Optional[Image.Image]:
    if not os.path.isfile(jar_path):
        return None

    if cache_dir is None:
        cache_dir = _DEFAULT_CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)

    try:
        stat = os.stat(jar_path)
        cache_key = hashlib.sha256(
            f"{os.path.basename(jar_path)}_{stat.st_size}_{stat.st_mtime}".encode("utf-8")
        ).hexdigest()[:24]
        cache_path = os.path.join(cache_dir, f"{cache_key}_{target_size[0]}x{target_size[1]}.png")

        # 1. Fast disk cache check
        if os.path.isfile(cache_path):
            try:
                with Image.open(cache_path) as cached:
                    return cached.copy()
            except Exception:
                pass

        # 2. Inspect jar archive
        icon_bytes = None
        with zipfile.ZipFile(jar_path, "r") as z:
            names = set(z.namelist())

            # Fabric mod check
            if "fabric.mod.json" in names:
                try:
                    data = json.loads(z.read("fabric.mod.json").decode("utf-8", errors="ignore"))
                    icon_entry = data.get("icon")
                    if isinstance(icon_entry, dict):
                        icon_entry = (
                            icon_entry.get("64")
                            or icon_entry.get("128")
                            or icon_entry.get("32")
                            or next(iter(icon_entry.values()), None)
                        )
                    if icon_entry:
                        icon_clean = icon_entry.lstrip("/")
                        candidates = [icon_clean, f"assets/{icon_clean}"]
                        for c in candidates:
                            if c in names:
                                icon_bytes = z.read(c)
                                break
                except Exception as ex:
                    logger.debug("Error reading fabric.mod.json in %s: %s", jar_path, ex)

            # Quilt mod check
            if not icon_bytes and "quilt.mod.json" in names:
                try:
                    data = json.loads(z.read("quilt.mod.json").decode("utf-8", errors="ignore"))
                    icon_entry = (data.get("quilt_loader") or {}).get("icon") or data.get("icon")
                    if isinstance(icon_entry, dict):
                        icon_entry = (
                            icon_entry.get("64")
                            or icon_entry.get("128")
                            or next(iter(icon_entry.values()), None)
                        )
                    if icon_entry:
                        icon_clean = icon_entry.lstrip("/")
                        for c in [icon_clean, f"assets/{icon_clean}"]:
                            if c in names:
                                icon_bytes = z.read(c)
                                break
                except Exception as ex:
                    logger.debug("Error reading quilt.mod.json in %s: %s", jar_path, ex)

            # Forge / NeoForge mods.toml check
            if not icon_bytes and "META-INF/mods.toml" in names:
                try:
                    toml_str = z.read("META-INF/mods.toml").decode("utf-8", errors="ignore")
                    for line in toml_str.splitlines():
                        line = line.strip()
                        if line.startswith("logoFile"):
                            parts = line.split("=", 1)
                            if len(parts) == 2:
                                logo_file = parts[1].strip().strip('"').strip("'").lstrip("/")
                                for candidate in [logo_file, f"META-INF/{logo_file}", f"assets/{logo_file}"]:
                                    if candidate in names:
                                        icon_bytes = z.read(candidate)
                                        break
                                if icon_bytes:
                                    break
                except Exception as ex:
                    logger.debug("Error reading mods.toml in %s: %s", jar_path, ex)

            # Universal fallback pattern search
            if not icon_bytes:
                for name in names:
                    if name.startswith("META-INF/"):
                        continue
                    lower = name.lower()
                    if lower.endswith("/icon.png") or lower.endswith("/logo.png") or lower in ("icon.png", "logo.png"):
                        try:
                            icon_bytes = z.read(name)
                            break
                        except Exception:
                            continue

        if not icon_bytes:
            return None

        # 3. Process and downscale to target size with BILINEAR
        with Image.open(io.BytesIO(icon_bytes)) as src:
            img = src.convert("RGBA").resize(target_size, Image.Resampling.BILINEAR)

        # 4. Save to disk cache atomically
        try:
            temp_path = cache_path + f".tmp_{os.getpid()}"
            img.save(temp_path, format="PNG")
            os.replace(temp_path, cache_path)
        except Exception as ex:
            logger.debug("Failed saving mod icon cache: %s", ex)

        return img

    except Exception as ex:
        logger.debug("Failed extracting icon for %s: %s", jar_path, ex)
        return None


def get_mod_icon_path(
    jar_path: str,
    target_size: Tuple[int, int] = (48, 48),
    cache_dir: Optional[str] = None
) -> Optional[str]:
    if not os.path.isfile(jar_path):
        return None
    if cache_dir is None:
        cache_dir = _DEFAULT_CACHE_DIR
    try:
        stat = os.stat(jar_path)
        cache_key = hashlib.sha256(
            f"{os.path.basename(jar_path)}_{stat.st_size}_{stat.st_mtime}".encode("utf-8")
        ).hexdigest()[:24]
        cache_path = os.path.join(cache_dir, f"{cache_key}_{target_size[0]}x{target_size[1]}.png")
        if os.path.isfile(cache_path):
            return os.path.abspath(cache_path)
        img = extract_icon_from_jar(jar_path, target_size=target_size, cache_dir=cache_dir)
        if img and os.path.isfile(cache_path):
            return os.path.abspath(cache_path)
    except Exception as ex:
        logger.debug("Failed getting icon path for %s: %s", jar_path, ex)
    return None


def get_mod_info(
    jar_path: str,
    target_size: Tuple[int, int] = (48, 48)
) -> Dict[str, str]:
    info = {"name": "", "version": "", "icon_path": ""}
    if not os.path.isfile(jar_path):
        return info
    icon_path = get_mod_icon_path(jar_path, target_size=target_size)
    if icon_path:
        info["icon_path"] = icon_path

    try:
        with zipfile.ZipFile(jar_path, "r") as z:
            names = set(z.namelist())
            if "fabric.mod.json" in names:
                data = json.loads(z.read("fabric.mod.json").decode("utf-8", errors="ignore"))
                info["name"] = data.get("name", "")
                info["version"] = str(data.get("version", ""))
            elif "quilt.mod.json" in names:
                data = json.loads(z.read("quilt.mod.json").decode("utf-8", errors="ignore"))
                meta = data.get("quilt_loader", {}).get("metadata", {})
                info["name"] = meta.get("name", "")
                info["version"] = str(data.get("quilt_loader", {}).get("version", ""))
            elif "META-INF/mods.toml" in names:
                toml_str = z.read("META-INF/mods.toml").decode("utf-8", errors="ignore")
                for line in toml_str.splitlines():
                    line = line.strip()
                    if line.startswith("displayName"):
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            info["name"] = parts[1].strip().strip('"').strip("'")
                    elif line.startswith("version") and not info["version"]:
                        parts = line.split("=", 1)
                        if len(parts) == 2:
                            v = parts[1].strip().strip('"').strip("'")
                            if not v.startswith("${"):
                                info["version"] = v
    except Exception as ex:
        logger.debug("Error extracting metadata for %s: %s", jar_path, ex)

    return info
