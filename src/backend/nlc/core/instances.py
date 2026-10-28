
import json
import logging
import os
import shutil
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

SHARED_ASSET_FOLDERS = {
    "share_resourcepacks": "resourcepacks",
    "share_shaderpacks": "shaderpacks",
    "share_worlds": "saves",
    "share_configs": "config",
}


def is_directory_link(path: Union[Path, str]) -> bool:
    p = Path(path)
    if not p.exists() and not p.is_symlink():
        return False
    if p.is_symlink():
        return True
    if os.name == "nt":
        try:
            import stat
            return bool(p.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        except Exception:
            return False
    return False


def remove_directory_link(link_path: Union[Path, str]) -> bool:
    p = Path(link_path)
    if not is_directory_link(p):
        return False
    try:
        if os.name == "nt" and not p.is_symlink():
            # Windows junction directory removal requires os.rmdir without recursion
            os.rmdir(p)
        else:
            p.unlink()
        return True
    except Exception as e:
        logger.warning("Failed to unlink directory %s: %s", p, e)
        return False


def create_directory_link(target: Union[Path, str], link: Union[Path, str]) -> bool:
    target_path = Path(target)
    link_path = Path(link)

    # Check if arguments are in (link, target) order instead of (target, link)
    if not target_path.exists() and not target_path.is_symlink() and link_path.exists():
        target_path, link_path = link_path, target_path

    target_path = target_path.resolve()
    try:
        if os.name == "nt":
            try:
                # Try directory junction first (doesn't require Windows Developer Mode / Admin privileges)
                import _winapi
                _winapi.CreateJunction(str(target_path), str(link_path))
                return True
            except Exception:
                os.symlink(str(target_path), str(link_path), target_is_directory=True)
                return True
        else:
            os.symlink(str(target_path), str(link_path), target_is_directory=True)
            return True
    except Exception as e:
        logger.warning("Could not create link %s -> %s: %s", link_path, target_path, e)
        return False


def link_shared_folder(instance_dir: Union[Path, str], shared_root: Union[Path, str], folder_name: str, enabled: bool) -> bool:
    inst_root = Path(instance_dir).resolve()
    shared_base = Path(shared_root).resolve()
    target_dir = shared_base / folder_name
    link_dir = inst_root / folder_name

    inst_root.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    if enabled:
        if is_directory_link(link_dir):
            try:
                # Check if it already points to target_dir
                resolved = link_dir.resolve()
                if resolved == target_dir.resolve():
                    return True
            except Exception:
                pass
            remove_directory_link(link_dir)

        if link_dir.exists():
            if link_dir.is_dir():
                # Merge any existing non-duplicate files from instance folder into shared folder
                try:
                    for item in link_dir.iterdir():
                        dest = target_dir / item.name
                        if not dest.exists():
                            if item.is_dir():
                                shutil.copytree(item, dest)
                            else:
                                shutil.copy2(item, dest)
                    shutil.rmtree(link_dir)
                except Exception as e:
                    logger.warning("Error merging instance folder %s before linking: %s", link_dir, e)
                    return False
            else:
                try:
                    link_dir.unlink()
                except Exception:
                    return False

        return create_directory_link(target_dir, link_dir)
    else:
        # Asset sharing disabled: unlink if linked and create independent physical folder
        if is_directory_link(link_dir):
            remove_directory_link(link_dir)
        link_dir.mkdir(parents=True, exist_ok=True)
        return True


def sync_instance_assets(instance_dir: Union[Path, str], shared_root: Union[Path, str], settings: Optional[Dict[str, Any]] = None) -> None:
    if settings is None:
        settings = {
            "share_resourcepacks": True,
            "share_shaderpacks": True,
            "share_worlds": False,
            "share_configs": False,
        }

    for setting_key, folder_name in SHARED_ASSET_FOLDERS.items():
        enabled = bool(settings.get(setting_key, False))
        link_shared_folder(instance_dir, shared_root, folder_name, enabled=enabled)


def export_modpack_to_zip(
    pack_dir: Optional[Union[Path, str]] = None,
    output_path: Optional[Union[Path, str]] = None,
    pack_meta: Optional[Dict[str, Any]] = None,
    *,
    modpack_dir: Optional[Union[Path, str]] = None,
    target_zip_path: Optional[Union[Path, str]] = None,
) -> str:
    src = pack_dir or modpack_dir
    dst = output_path or target_zip_path
    if not src or not dst:
        raise ValueError("Both source modpack directory and output zip path are required.")

    pack_path = Path(src).resolve()
    target_path = Path(dst).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    meta = pack_meta or {}
    with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Write metadata
        clean_meta = {
            "name": meta.get("name", "Custom Modpack"),
            "loader": meta.get("loader", "Vanilla"),
            "mc_version": meta.get("mc_version", "1.21.1"),
            "version_name": meta.get("version_name", "1.0.0"),
            "source": meta.get("source", "nlc_export"),
        }
        zf.writestr("modpack.json", json.dumps(clean_meta, indent=2))

        # Bundle files
        for root, dirs, files in os.walk(pack_path, followlinks=False):
            # Exclude symlinks/junctions
            dirs[:] = [d for d in dirs if not is_directory_link(Path(root) / d)]
            for file in files:
                file_path = Path(root) / file
                if not file_path.is_symlink():
                    arcname = file_path.relative_to(pack_path)
                    zf.write(file_path, arcname=str(arcname))

    return str(target_path)


def export_modpack_to_mrpack(
    pack_dir: Optional[Union[Path, str]] = None,
    output_path: Optional[Union[Path, str]] = None,
    pack_meta: Optional[Dict[str, Any]] = None,
    *,
    modpack_dir: Optional[Union[Path, str]] = None,
    target_mrpack_path: Optional[Union[Path, str]] = None,
    modpack_name: Optional[str] = None,
    version_id: Optional[str] = None,
    game_version: Optional[str] = None,
    loader: Optional[str] = None,
) -> str:
    src = pack_dir or modpack_dir
    dst = output_path or target_mrpack_path
    if not src or not dst:
        raise ValueError("Both source modpack directory and output mrpack path are required.")

    pack_path = Path(src).resolve()
    target_path = Path(dst).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    meta = pack_meta or {}
    name = str(modpack_name or meta.get("name") or "Custom Modpack")
    mc_version = str(game_version or meta.get("mc_version") or "1.21.1")
    mod_loader = str(loader or meta.get("loader") or "fabric").lower()
    # Normalize loader name for modrinth dependencies (e.g. fabric-loader, forge, neoforge, quilt-loader)
    loader_dep = f"{mod_loader}-loader" if mod_loader in ("fabric", "quilt") else mod_loader
    v_id = str(version_id or meta.get("version_id") or meta.get("version_name") or uuid.uuid4().hex[:8])

    index_data = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": v_id,
        "name": name,
        "summary": "Modpack exported from Ny-Luna (NLC)",
        "files": [],
        "dependencies": {
            "minecraft": mc_version,
            loader_dep: "latest"
        }
    }

    with zipfile.ZipFile(target_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Write modrinth.index.json
        zf.writestr("modrinth.index.json", json.dumps(index_data, indent=2))

        # Pack contents into overrides/
        for root, dirs, files in os.walk(pack_path, followlinks=False):
            dirs[:] = [d for d in dirs if not is_directory_link(Path(root) / d)]
            for file in files:
                file_path = Path(root) / file
                if not file_path.is_symlink():
                    rel = file_path.relative_to(pack_path)
                    arcname = f"overrides/{rel.as_posix()}"
                    zf.write(file_path, arcname=arcname)

    return str(target_path)
