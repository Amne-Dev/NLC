
import json
import logging
import os
import re
import shutil
import stat
import zipfile
from typing import Any, Dict, List, Optional
import minecraft_launcher_lib

logger = logging.getLogger(__name__)

def safe_extract_zip(archive_path: str, destination_dir: str):
    dest_path = os.path.realpath(destination_dir)
    with zipfile.ZipFile(archive_path, "r") as zf:
        for member in zf.infolist():
            is_symlink = ((member.external_attr >> 16) & 0o170000) == 0o120000
            target_path = os.path.realpath(os.path.join(dest_path, member.filename))
            if is_symlink or os.path.commonpath((dest_path, target_path)) != dest_path:
                raise ValueError(f"Unsafe zip archive entry rejected: {member.filename}")
        zf.extractall(dest_path)

def _get_lib_name_without_version(lib: Dict[str, Any]) -> str:
    return ":".join(str(lib.get("name", "")).split(":")[:-1])

def safe_inherit_json(original_data: Dict[str, Any], path: str) -> Dict[str, Any]:
    inherit_version = original_data.get("inheritsFrom")
    if not inherit_version:
        return original_data

    parent_json_path = os.path.join(path, "versions", inherit_version, f"{inherit_version}.json")
    with open(parent_json_path, encoding="utf-8") as f:
        new_data = json.load(f)

    original_libs = {}
    for current_lib in original_data.get("libraries", []):
        lib_name = _get_lib_name_without_version(current_lib)
        original_libs[lib_name] = True

    lib_list = list(original_data.get("libraries", []))
    for current_lib in new_data.get("libraries", []):
        lib_name = _get_lib_name_without_version(current_lib)
        if lib_name not in original_libs:
            lib_list.append(current_lib)

    new_data["libraries"] = lib_list

    for key, value in original_data.items():
        if key == "libraries":
            continue
        if isinstance(value, list) and isinstance(new_data.get(key), list):
            new_data[key] = value + new_data[key]
        elif isinstance(value, dict) and isinstance(new_data.get(key), dict):
            target_dict = new_data[key]
            for child_key, child_value in value.items():
                if isinstance(child_value, list):
                    existing = target_dict.get(child_key, [])
                    if not isinstance(existing, list):
                        existing = []
                    target_dict[child_key] = existing + child_value
                else:
                    target_dict[child_key] = child_value
        else:
            new_data[key] = value

    return new_data

def safe_get_minecraft_arguments(data, version_data, path, options, classpath) -> List[str]:
    arglist = []
    version_id = version_data.get("id", "<unknown>")

    for entry in data:
        if isinstance(entry, str):
            arglist.append(
                minecraft_launcher_lib.command.replace_arguments(
                    entry, version_data, path, options, classpath
                )
            )
            continue

        if "compatibilityRules" in entry and not minecraft_launcher_lib.command.parse_rule_list(entry["compatibilityRules"], options):
            continue

        if "rules" in entry and not minecraft_launcher_lib.command.parse_rule_list(entry["rules"], options):
            continue

        if "value" not in entry:
            logger.warning("Skipping argument without 'value' for %s: %s", version_id, entry)
            continue

        arg_val = entry.get("value")
        if isinstance(arg_val, str):
            arglist.append(
                minecraft_launcher_lib.command.replace_arguments(
                    arg_val, version_data, path, options, classpath
                )
            )
            continue

        if isinstance(arg_val, list):
            for v in arg_val:
                arglist.append(
                    minecraft_launcher_lib.command.replace_arguments(
                        v, version_data, path, options, classpath
                    )
                )
            continue

        logger.warning("Skipping malformed argument value for %s: %r", version_id, arg_val)

    return arglist

def apply_launcher_lib_patches():
    try:
        minecraft_launcher_lib.command.inherit_json = safe_inherit_json
        minecraft_launcher_lib.command.get_arguments = safe_get_minecraft_arguments
        logger.debug("Patched minecraft_launcher_lib command helpers successfully.")
    except Exception as e:
        logger.exception("Failed to apply launcher lib patches: %s", e)

patch_minecraft_launcher_launch_helpers = apply_launcher_lib_patches


def _handle_remove_readonly(func, path, _exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def purge_version_directory(mc_dir: str, actual_version: str, loader: str = "Vanilla") -> List[str]:
    purged: List[str] = []
    if not actual_version or not str(actual_version).strip() or str(actual_version).strip() in (".", ".."):
        logger.warning("Refusing to purge version directory with empty or invalid version: %r", actual_version)
        return purged

    clean_version = str(actual_version).strip()

    versions_base = os.path.join(mc_dir, "versions")
    if not os.path.isdir(versions_base):
        return purged

    base_norm = os.path.normpath(versions_base)
    loader_clean = str(loader or "Vanilla").strip()
    loader_lower = loader_clean.lower()

    if loader_lower == "vanilla":
        v_dir = os.path.join(versions_base, clean_version)
        target_norm = os.path.normpath(v_dir)
        if target_norm == base_norm or not target_norm.startswith(base_norm + os.sep):
            logger.warning("Directory traversal or base directory purge blocked: %s", v_dir)
            return purged

        if os.path.isdir(v_dir):
            logger.info("Force update: Purging stale vanilla version dir %s", v_dir)
            shutil.rmtree(v_dir, onerror=_handle_remove_readonly)
            if not os.path.exists(v_dir):
                purged.append(v_dir)
    else:
        ver_pattern = re.compile(rf"(?:^|[-_]){re.escape(clean_version)}(?:$|[-_])", re.IGNORECASE)
        for entry in os.listdir(versions_base):
            entry_lower = entry.lower()
            if loader_lower == "forge" and "neoforge" in entry_lower:
                continue
            if loader_lower in entry_lower and ver_pattern.search(entry):
                sub_dir = os.path.join(versions_base, entry)
                sub_norm = os.path.normpath(sub_dir)
                if sub_norm == base_norm or not sub_norm.startswith(base_norm + os.sep):
                    logger.warning("Directory traversal in modloader purge blocked: %s", sub_dir)
                    continue
                if os.path.isdir(sub_dir):
                    logger.info("Force update: Purging stale %s version dir %s", loader_clean, sub_dir)
                    shutil.rmtree(sub_dir, onerror=_handle_remove_readonly)
                    if not os.path.exists(sub_dir):
                        purged.append(sub_dir)

    return purged


def clean_modpack_temp_files(modpack_dir: str) -> List[str]:
    cleaned: List[str] = []
    if not os.path.isdir(modpack_dir):
        return cleaned
    for root_d, _, files in os.walk(modpack_dir):
        for f in files:
            if f.lower().endswith((".part", ".tmp")):
                file_path = os.path.join(root_d, f)
                try:
                    try:
                        os.remove(file_path)
                    except PermissionError:
                        os.chmod(file_path, stat.S_IWRITE)
                        os.remove(file_path)
                    cleaned.append(file_path)
                except Exception as ex:
                    logger.debug("Could not remove temp file %s: %s", file_path, ex)
    return cleaned

