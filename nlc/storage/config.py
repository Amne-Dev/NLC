"""
nlc.storage.config - Safe configuration persistence with atomic writes and .bak recovery
"""

import json
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from nlc.storage.paths import get_config_path

logger = logging.getLogger(__name__)

DEFAULT_RAM = 4096
DEFAULT_USERNAME = "Steve"
CURRENT_VERSION = "3.0.4"
INSTALL_MARK = "✅ "

LOADERS = ["Vanilla", "Forge", "Fabric", "BatMod", "LabyMod", "Lunar Client"]
MOD_COMPATIBLE_LOADERS = {"Forge", "Fabric"}

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
    "created": "2024-01-01"
}

def normalize_installations(value: Any) -> tuple[List[Dict[str, Any]], bool]:
    """Return usable installation records and whether migration changed them."""
    defaults = get_default_config()["installations"][0]
    changed = not isinstance(value, list)
    installations: List[Dict[str, Any]] = []
    seen_ids = set()

    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            changed = True
            continue
        installation = dict(item)
        installation_id = installation.get("id")
        if not isinstance(installation_id, str) or not installation_id.strip() or installation_id in seen_ids:
            installation_id = str(uuid.uuid4())
            changed = True
        seen_ids.add(installation_id)
        installation["id"] = installation_id
        for key, default in defaults.items():
            if key not in installation:
                installation[key] = default
                changed = True
        installations.append(installation)

    if not installations:
        installations = [dict(defaults, id=str(uuid.uuid4()))]
        changed = True
    return installations, changed

def get_default_config() -> Dict[str, Any]:
    """Return default launcher configuration dictionary."""
    return {
        "version": CURRENT_VERSION,
        "first_run_completed": False,
        "ram": DEFAULT_RAM,
        "custom_titlebar": True if os.name == "nt" else False,
        "neo_style": True,
        "theme_id": "dark_slate",
        "custom_accent": None,
        "animations_enabled": True,
        "minimize_to_tray": False,
        "rpc_enabled": True,
        "streamer_mode": False,
        "instances": {
            "share_resourcepacks": True,
            "share_shaderpacks": True,
            "share_worlds": False,
            "share_configs": False
        },
        "profiles": [
            {
                "name": DEFAULT_USERNAME,
                "type": "offline",
                "skin_path": "",
                "skin_model": "classic",
                "uuid": ""
            }
        ],
        "active_profile_index": 0,
        "installations": [
            dict(DEFAULT_INSTALLATION, id=str(uuid.uuid4()))
        ],
        "active_installation_id": None,
        "addons": {
            "gh_sync": False,
            "playtime": {},
            "servers": []
        }
    }

class ConfigManager:
    """Manages reading and writing launcher_config.json with atomic writes and backups."""
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = Path(config_path) if config_path else get_config_path()
        self.backup_path = self.config_path.with_suffix(".json.bak")
        self.corrupt_path = self.config_path.with_suffix(".json.corrupt")

    def load(self) -> Dict[str, Any]:
        """
        Loads configuration from disk.
        Attempts to read main config; on failure or corruption, falls back to .bak;
        if neither is valid, safely preserves the corrupt file and returns defaults.
        """
        data = None

        if self.config_path.exists():
            data = self._read_file(self.config_path)
            if data is None and self.backup_path.exists():
                logger.warning("Config corrupted, attempting recovery from backup: %s", self.backup_path)
                data = self._read_file(self.backup_path)
                if data is not None:
                    try:
                        shutil.copy2(self.backup_path, self.config_path)
                    except OSError as exc:
                        logger.warning("Could not restore config backup: %s", exc)

        if data is None:
            logger.info("Initializing new configuration with defaults.")
            data = get_default_config()
            self.save(data)
            return data

        # Sanitize and migrate fields
        return self._normalize_config(data)

    def _read_file(self, path: Path) -> Optional[Dict[str, Any]]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = json.load(f)
                if isinstance(content, dict):
                    return content
                logger.error("Config at %s is not a JSON object.", path)
        except Exception as e:
            logger.error("Failed to read JSON config at %s: %s", path, e)
            if path == self.config_path:
                try:
                    shutil.copy2(self.config_path, self.corrupt_path)
                    logger.warning("Preserved corrupt config at %s", self.corrupt_path)
                except Exception:
                    pass
        return None

    def _normalize_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure all required root keys exist with valid types."""
        defaults = get_default_config()
        changed = False

        profiles = data.get("profiles")
        if isinstance(profiles, list):
            valid_profiles = [profile for profile in profiles if isinstance(profile, dict)]
        else:
            valid_profiles = []
        if not valid_profiles:
            data["profiles"] = defaults["profiles"]
            changed = True
        elif len(valid_profiles) != len(profiles):
            data["profiles"] = valid_profiles
            changed = True
        for profile in data["profiles"]:
            if not isinstance(profile.get("name"), str) or not profile["name"].strip():
                profile["name"] = DEFAULT_USERNAME
                changed = True

        installations, installations_changed = normalize_installations(data.get("installations"))
        data["installations"] = installations
        changed = changed or installations_changed

        if not isinstance(data.get("addons"), dict):
            data["addons"] = defaults["addons"]
            changed = True

        # Ensure active installation is selected
        active_id = data.get("active_installation_id")
        installation_ids = {item["id"] for item in installations}
        if active_id not in installation_ids:
            data["active_installation_id"] = installations[0]["id"]
            changed = True

        if data.get("version") != CURRENT_VERSION:
            data["version"] = CURRENT_VERSION
            changed = True

        if changed:
            self.save(data)

        return data

    def save(self, data: Dict[str, Any]) -> bool:
        """
        Atomically saves configuration to disk.
        Rotates current good file to .bak before replacing.
        """
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            prefix="nlc_cfg_",
            suffix=".tmp",
            dir=str(self.config_path.parent)
        )
        tmp_path = Path(tmp_path_str)

        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())

            # Make a backup of the current valid config before replacing
            if self.config_path.exists() and self.config_path.stat().st_size > 0:
                try:
                    shutil.copy2(self.config_path, self.backup_path)
                except Exception as e:
                    logger.warning("Could not create config backup: %s", e)

            # Atomic rename into place
            os.replace(tmp_path, self.config_path)
            return True
        except Exception as e:
            logger.error("Failed to atomically save config: %s", e)
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            return False
