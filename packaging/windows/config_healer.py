"""
Config Healer & Legacy Migration Engine for New-launcher (NLC).
Handles:
1. Multi-location config discovery (v3 %APPDATA%/.nlc, legacy .new-launcher, portable).
2. Corrupt / truncated JSON recovery without user data loss.
3. Legacy Tkinter GUI schema migration to v3.
4. Installation UUID normalization and atomic file persistence.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger(__name__)

CURRENT_VERSION = "4.0.4"
DEFAULT_RAM = 4096
DEFAULT_USERNAME = "Steve"

DEFAULT_INSTALLATION = {
    "id": "default-vanilla",
    "name": "Latest Release",
    "version": "latest-release",
    "loader": "Vanilla",
    "icon": "icons/grass_block_side.png",
    "java_executable": "",
    "resolution_width": None,
    "resolution_height": None,
    "game_directory": "",
    "last_played": "Never",
    "created": "2024-01-01",
}


def get_default_v3_config() -> Dict[str, Any]:
    """Returns the canonical default v3 configuration dictionary."""
    return {
        "version": CURRENT_VERSION,
        "first_run_completed": False,
        "ram": DEFAULT_RAM,
        "custom_titlebar": True if os.name == "nt" else False,
        "neo_style": True,
        "theme_id": "dark_slate",
        "custom_accent": None,
        "animations_enabled": True,
        "enable_walking_mobs": True,
        "offline_skin_injection": True,
        "minimize_to_tray": False,
        "rpc_enabled": True,
        "streamer_mode": False,
        "instances": {
            "share_resourcepacks": True,
            "share_shaderpacks": True,
            "share_worlds": False,
            "share_configs": False,
        },
        "profiles": [],
        "active_profile_index": 0,
        "installations": [
            dict(DEFAULT_INSTALLATION, id=str(uuid.uuid4()))
        ],
        "active_installation_id": None,
        "addons": {
            "gh_sync": False,
            "playtime": {},
            "servers": [],
        },
    }


def get_default_config_dir() -> Path:
    """Returns the default configuration directory (%APPDATA%/.nlc on Windows, ~/.nlc on Linux/macOS)."""
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home()
        return base / ".nlc"
    return Path.home() / ".nlc"


def discover_candidate_config_paths(target_dir: Optional[Union[Path, str]] = None) -> List[Path]:
    """Finds all potential existing config files across v3, legacy Tkinter, target_dir, and portable paths."""
    candidates: List[Path] = []
    
    # 1. Target install directory if provided
    if target_dir:
        td = Path(target_dir)
        candidates.append(td / "launcher_config.json")
        candidates.append(td / "config.json")
        candidates.append(td / "nlc" / "launcher_config.json")

    # 2. Primary v3 path
    primary_dir = get_default_config_dir()
    candidates.append(primary_dir / "launcher_config.json")
    
    # 3. Legacy Tkinter directories
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            ap = Path(appdata)
            candidates.append(ap / ".new-launcher" / "launcher_config.json")
            candidates.append(ap / "NewLauncher" / "launcher_config.json")
            candidates.append(ap / "NewLauncher" / "config.json")
            candidates.append(ap / ".nlc" / "config.json")
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            lap = Path(local_appdata)
            candidates.append(lap / "NewLauncher" / "launcher_config.json")
            candidates.append(lap / "NewLauncher" / "config.json")
    
    # 4. Portable paths (current working directory)
    candidates.append(Path.cwd() / "launcher_config.json")
    
    # De-duplicate maintaining order
    unique: List[Path] = []
    seen = set()
    for c in candidates:
        try:
            res_str = str(c.resolve()).lower()
            if res_str not in seen:
                seen.add(res_str)
                unique.append(c)
        except Exception:
            unique.append(c)

    return unique


def has_custom_profiles(cfg: Dict[str, Any]) -> bool:
    """Returns True if configuration has user accounts beyond default Steve."""
    profiles = cfg.get("profiles")
    if not isinstance(profiles, list) or len(profiles) == 0:
        return False
    if len(profiles) > 1:
        return True
    p = profiles[0]
    if isinstance(p, dict):
        name = str(p.get("name", "")).strip()
        if name and name.lower() not in ("steve", "default"):
            return True
        if p.get("type") == "microsoft" or p.get("access_token") or p.get("skin_path"):
            return True
    return False


def extract_profiles_from_candidate(cand_data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    """Extracts normalized profile list and optional active index from candidate config dictionary."""
    profiles: List[Dict[str, Any]] = []
    active_idx: Optional[int] = None

    if isinstance(cand_data.get("profiles"), list) and cand_data["profiles"]:
        for p in cand_data["profiles"]:
            if isinstance(p, dict) and p.get("name"):
                p_copy = dict(p)
                p_copy.setdefault("type", "offline")
                p_copy.setdefault("skin_model", "classic")
                p_copy.setdefault("skin_path", "")
                if not p_copy.get("uuid"):
                    p_copy["uuid"] = str(uuid.uuid4())
                profiles.append(p_copy)
        if "active_profile_index" in cand_data:
            try:
                active_idx = int(cand_data["active_profile_index"])
            except (ValueError, TypeError):
                pass
    elif isinstance(cand_data.get("accounts"), list) and cand_data["accounts"]:
        for acc in cand_data["accounts"]:
            if isinstance(acc, dict):
                name = acc.get("name") or acc.get("username") or acc.get("player_name")
                if name:
                    profiles.append({
                        "name": str(name).strip(),
                        "type": acc.get("type", "offline"),
                        "skin_path": acc.get("skin_path", ""),
                        "skin_model": acc.get("skin_model", "classic"),
                        "uuid": acc.get("uuid") or str(uuid.uuid4()),
                        "access_token": acc.get("access_token"),
                        "refresh_token": acc.get("refresh_token"),
                    })
        if "active_account_index" in cand_data:
            try:
                active_idx = int(cand_data["active_account_index"])
            except (ValueError, TypeError):
                pass
    elif cand_data.get("username") or cand_data.get("player_name"):
        u = str(cand_data.get("username") or cand_data.get("player_name")).strip()
        if u and u.lower() not in ("steve", "default"):
            profiles.append({
                "name": u,
                "type": "offline",
                "skin_path": "",
                "skin_model": "classic",
                "uuid": str(uuid.uuid4()),
            })

    return profiles, active_idx


# ==============================================================================
# Heuristic Recovery for Corrupted / Truncated JSON
# ==============================================================================

def recover_corrupted_json(raw_text: str) -> Tuple[Dict[str, Any], List[str]]:
    """
    Attempts heuristic extraction of key configuration values from corrupted or truncated JSON.
    Recovers username/profiles, RAM, theme, Java path, and installation definitions.
    Returns (recovered_dict, list_of_recovered_keys).
    """
    recovered: Dict[str, Any] = {}
    recovered_keys: List[str] = []

    # 1. Recover RAM
    ram_match = re.search(r'["\'](?:ram|ram_mb|memory)["\']\s*:\s*(\d+)', raw_text, re.IGNORECASE)
    if ram_match:
        try:
            val = int(ram_match.group(1))
            if 1024 <= val <= 65536:
                recovered["ram"] = val
                recovered_keys.append("ram")
        except ValueError:
            pass

    # 2. Recover Theme
    theme_match = re.search(r'["\'](?:theme|theme_id)["\']\s*:\s*["\']([^"\']+)["\']', raw_text, re.IGNORECASE)
    if theme_match:
        theme_val = theme_match.group(1).strip()
        recovered["theme_id"] = theme_val
        recovered_keys.append("theme_id")

    # 3. Recover Profiles / Usernames
    profiles: List[Dict[str, Any]] = []
    user_match = re.search(r'["\'](?:username|player_name|user)["\']\s*:\s*["\']([^"\']+)["\']', raw_text, re.IGNORECASE)
    if user_match:
        u_name = user_match.group(1).strip()
        if u_name:
            profiles.append({
                "name": u_name,
                "type": "offline",
                "skin_path": "",
                "skin_model": "classic",
                "uuid": str(uuid.uuid4()),
            })
            recovered_keys.append("profiles (from legacy username)")

    profile_matches = re.findall(r'\{[^{}]*["\']name["\']\s*:\s*["\']([^"\']+)["\'][^{}]*\}', raw_text)
    for p_name in profile_matches:
        clean_name = p_name.strip()
        if clean_name and clean_name != DEFAULT_USERNAME and not any(p["name"] == clean_name for p in profiles):
            profiles.append({
                "name": clean_name,
                "type": "offline",
                "skin_path": "",
                "skin_model": "classic",
                "uuid": str(uuid.uuid4()),
            })
            if "profiles" not in recovered_keys:
                recovered_keys.append("profiles")

    if profiles:
        recovered["profiles"] = profiles

    # 4. Recover Java Executable
    java_match = re.search(r'["\'](?:java_executable|java_path)["\']\s*:\s*["\']([^"\']+)["\']', raw_text, re.IGNORECASE)
    if java_match:
        j_path = java_match.group(1).strip()
        if j_path:
            recovered["java_executable"] = j_path
            recovered_keys.append("java_executable")

    # 5. Recover Installations
    inst_section_match = re.search(r'["\']installations["\']\s*:\s*\[(.*)', raw_text, re.DOTALL)
    search_target = inst_section_match.group(1) if inst_section_match else raw_text

    inst_matches = re.findall(
        r'["\']name["\']\s*:\s*["\']([^"\']+)["\'][^{}\]]*?["\']version["\']\s*:\s*["\']([^"\']+)["\']',
        search_target
    )
    if not inst_matches:
        inst_matches = [(n, v) for v, n in re.findall(
            r'["\']version["\']\s*:\s*["\']([^"\']+)["\'][^{}\]]*?["\']name["\']\s*:\s*["\']([^"\']+)["\']',
            search_target
        )]

    if inst_matches:
        installations: List[Dict[str, Any]] = []
        for inst_name, inst_ver in inst_matches:
            installations.append({
                "id": str(uuid.uuid4()),
                "name": inst_name.strip(),
                "version": inst_ver.strip(),
                "loader": "Vanilla",
                "icon": "icons/grass_block_side.png",
                "java_executable": recovered.get("java_executable", ""),
                "resolution_width": None,
                "resolution_height": None,
                "game_directory": "",
                "last_played": "Never",
                "created": "2024-01-01",
            })
        if installations:
            recovered["installations"] = installations
            recovered_keys.append(f"installations ({len(installations)} items)")

    return recovered, recovered_keys


# ==============================================================================
# Legacy Schema Migration (Tkinter -> Slint v3)
# ==============================================================================

THEME_MAPPINGS = {
    "dark": "dark_slate",
    "slate": "dark_slate",
    "dark_slate": "dark_slate",
    "light": "light",
    "nord": "nord",
    "dracula": "dracula",
    "catppuccin": "catppuccin",
    "tokyo_night": "tokyo_night",
}


def migrate_legacy_schema(data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """
    Migrates legacy Tkinter GUI config properties into canonical v3 schema.
    Returns (migrated_dict, changed_bool).
    """
    defaults = get_default_v3_config()
    changed = False

    # 1. Theme normalization
    raw_theme = str(data.get("theme_id") or data.get("theme") or "").strip().lower()
    norm_theme = THEME_MAPPINGS.get(raw_theme, "dark_slate")
    if data.get("theme_id") != norm_theme:
        data["theme_id"] = norm_theme
        changed = True

    # 2. RAM normalization
    if "ram_mb" in data and "ram" not in data:
        try:
            data["ram"] = int(data.pop("ram_mb"))
            changed = True
        except (ValueError, TypeError):
            pass
    if not isinstance(data.get("ram"), (int, float)) or data.get("ram") < 512:
        data["ram"] = DEFAULT_RAM
        changed = True

    # 3. Profiles normalization
    profiles = data.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        legacy_user = str(data.get("username") or data.get("player_name") or "").strip()
        if legacy_user and legacy_user.lower() not in ("steve", "default"):
            data["profiles"] = [
                {
                    "name": legacy_user,
                    "type": "offline",
                    "skin_path": "",
                    "skin_model": "classic",
                    "uuid": str(uuid.uuid4()),
                }
            ]
            data["active_profile_index"] = 0
            changed = True
        else:
            data["profiles"] = []
            data["active_profile_index"] = 0
    else:
        valid_profiles = []
        for p in profiles:
            if isinstance(p, dict) and p.get("name"):
                profile_obj = dict(p)
                if not profile_obj.get("uuid"):
                    profile_obj["uuid"] = str(uuid.uuid4())
                    changed = True
                profile_obj.setdefault("type", "offline")
                profile_obj.setdefault("skin_model", "classic")
                profile_obj.setdefault("skin_path", "")
                valid_profiles.append(profile_obj)
        data["profiles"] = valid_profiles

    # 4. Installations normalization
    raw_inst = data.get("installations")
    if not isinstance(raw_inst, list) or not raw_inst:
        data["installations"] = [dict(DEFAULT_INSTALLATION, id=str(uuid.uuid4()))]
        data["active_installation_id"] = data["installations"][0]["id"]
        changed = True
    else:
        norm_inst: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()
        for item in raw_inst:
            if not isinstance(item, dict):
                changed = True
                continue
            inst = dict(item)
            inst_id = str(inst.get("id", "")).strip()
            if not inst_id or inst_id in seen_ids:
                inst_id = str(uuid.uuid4())
                changed = True
            seen_ids.add(inst_id)
            inst["id"] = inst_id

            for k, def_val in DEFAULT_INSTALLATION.items():
                if k not in inst:
                    inst[k] = def_val
                    changed = True
            norm_inst.append(inst)

        if not norm_inst:
            norm_inst = [dict(DEFAULT_INSTALLATION, id=str(uuid.uuid4()))]
            changed = True
        data["installations"] = norm_inst

    # 5. Ensure active installation exists
    active_inst = data.get("active_installation_id")
    available_ids = {i["id"] for i in data["installations"]}
    if active_inst not in available_ids:
        data["active_installation_id"] = data["installations"][0]["id"]
        changed = True

    # 6. Addons structure
    if not isinstance(data.get("addons"), dict):
        data["addons"] = defaults["addons"]
        changed = True
    else:
        data["addons"].setdefault("gh_sync", False)
        data["addons"].setdefault("playtime", {})
        data["addons"].setdefault("servers", [])

    # 7. Version stamp
    if data.get("version") != CURRENT_VERSION:
        data["version"] = CURRENT_VERSION
        changed = True

    return data, changed


# ==============================================================================
# Config Healer Engine
# ==============================================================================

class ConfigHealer:
    """Detects, repairs, migrates, and atomically persists launcher configurations."""

    @classmethod
    def heal_and_migrate(
        cls,
        target_config_path: Optional[Path] = None,
        force_save: bool = False,
        target_dir: Optional[Union[Path, str]] = None,
    ) -> Dict[str, Any]:
        """
        Executes full configuration healing and migration:
        1. Checks target_config_path or discovers existing configs.
        2. Transfers user accounts from candidate/legacy paths if primary config is fresh/default.
        3. Recovers corrupted JSON if necessary (backing up original).
        4. Migrates legacy Tkinter fields to v3.
        5. Writes atomically with .bak synchronization.
        Returns status summary dict.
        """
        config_file = Path(target_config_path) if target_config_path else (get_default_config_dir() / "launcher_config.json")
        backup_file = config_file.with_suffix(".json.bak")
        config_dir = config_file.parent
        config_dir.mkdir(parents=True, exist_ok=True)

        summary: Dict[str, Any] = {
            "path": str(config_file),
            "status": "clean",
            "recovered_corrupted": False,
            "migrated_legacy": False,
            "actions": [],
        }

        raw_data: Optional[Dict[str, Any]] = None
        loaded_from: Optional[Path] = None

        # 1. Attempt to read primary file
        if config_file.is_file():
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    content = f.read()
                raw_data = json.loads(content)
                loaded_from = config_file
            except Exception as read_err:
                summary["actions"].append(f"Corrupt JSON in {config_file}: {read_err}")
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                corrupt_backup = config_dir / f"launcher_config.json.corrupt.{timestamp}"
                try:
                    shutil.copy2(config_file, corrupt_backup)
                    summary["actions"].append(f"Preserved corrupt config copy at {corrupt_backup}")
                except Exception:
                    pass

                if backup_file.is_file():
                    try:
                        with open(backup_file, "r", encoding="utf-8") as bf:
                            raw_data = json.load(bf)
                        loaded_from = backup_file
                        summary["actions"].append("Successfully restored valid config from .bak backup")
                    except Exception:
                        summary["actions"].append("Backup .bak was also unreadable")

                if raw_data is None:
                    recovered_dict, rec_keys = recover_corrupted_json(content)
                    if recovered_dict:
                        raw_data = recovered_dict
                        summary["recovered_corrupted"] = True
                        summary["actions"].append(f"Heuristically recovered fields from corrupt file: {', '.join(rec_keys)}")

        # Check if primary config exists but lacks custom user accounts
        needs_account_migration = (raw_data is not None) and (not has_custom_profiles(raw_data))

        # 2. If no config found at primary path OR primary lacks custom accounts, search candidate/legacy paths
        if raw_data is None or needs_account_migration:
            candidates = discover_candidate_config_paths(target_dir=target_dir)
            for cand in candidates:
                if cand.resolve() == config_file.resolve():
                    continue
                if cand.is_file():
                    try:
                        with open(cand, "r", encoding="utf-8") as cf:
                            c_content = cf.read()
                        parsed = json.loads(c_content)
                        if isinstance(parsed, dict):
                            cand_profiles, cand_active_idx = extract_profiles_from_candidate(parsed)
                            if cand_profiles:
                                if raw_data is None:
                                    raw_data = parsed
                                    loaded_from = cand
                                    summary["actions"].append(f"Imported configuration from legacy path: {cand}")
                                else:
                                    raw_data["profiles"] = cand_profiles
                                    if cand_active_idx is not None and 0 <= cand_active_idx < len(cand_profiles):
                                        raw_data["active_profile_index"] = cand_active_idx
                                    if isinstance(parsed.get("installations"), list) and len(parsed["installations"]) > 1:
                                        raw_data["installations"] = parsed["installations"]
                                    summary["actions"].append(f"Transferred {len(cand_profiles)} user account(s) from legacy config: {cand}")
                                    summary["migrated_legacy"] = True
                                break
                            elif raw_data is None:
                                raw_data = parsed
                                loaded_from = cand
                                summary["actions"].append(f"Imported configuration from legacy path: {cand}")
                                break
                    except Exception:
                        pass

        # 3. If completely fresh / unrecoverable, initialize defaults
        if raw_data is None:
            raw_data = get_default_v3_config()
            summary["actions"].append("Initialized fresh configuration with v3 defaults")
            summary["status"] = "created_default"
            cls._atomic_save(config_file, raw_data)
            return summary

        # 4. Migrate and normalize
        migrated_data, changed = migrate_legacy_schema(raw_data)
        if changed:
            summary["migrated_legacy"] = True
            summary["actions"].append("Normalized schema and migrated legacy fields to v3")

        # 5. Persist if modified or loaded from another source
        should_save = force_save or changed or summary["recovered_corrupted"] or (loaded_from and loaded_from.resolve() != config_file.resolve())
        if should_save:
            cls._atomic_save(config_file, migrated_data)
            summary["actions"].append(f"Atomically saved healed configuration to {config_file}")
            summary["status"] = "healed"

        return summary

    @staticmethod
    def _atomic_save(target_path: Path, data: Dict[str, Any]) -> None:
        """Atomically saves data to target_path and creates a synchronized .bak file."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_file = target_path.with_suffix(".json.tmp")
        backup_file = target_path.with_suffix(".json.bak")

        json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")

        with open(temp_file, "wb") as f:
            f.write(json_bytes)
            f.flush()
            os.fsync(f.fileno())

        if target_path.is_file():
            try:
                shutil.copy2(target_path, backup_file)
            except Exception:
                pass

        os.replace(temp_file, target_path)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="New-launcher Config Integrity & Healing Tool")
    parser.add_argument("--check", action="store_true", help="Inspect and heal config in default location")
    parser.add_argument("--path", help="Explicit config file path to heal")
    args = parser.parse_args()

    cfg_path = Path(args.path) if args.path else None
    result = ConfigHealer.heal_and_migrate(cfg_path)
    print(f"[*] Config Healing Status: {result['status']}")
    print(f"[*] Target Path: {result['path']}")
    for action in result["actions"]:
        print(f"  + {action}")


if __name__ == "__main__":
    main()
