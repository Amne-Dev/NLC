import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import requests

from nlc.storage.paths import get_launcher_data_dir

logger = logging.getLogger(__name__)

MOJANG_PROFILE_URL = "https://api.minecraftservices.com/minecraft/profile"
MOJANG_CAPE_ACTIVE_URL = "https://api.minecraftservices.com/minecraft/profile/capes/active"
MOJANG_SKIN_URL = "https://api.minecraftservices.com/minecraft/profile/skins"


def get_capes_cache_dir() -> Path:
    capes_dir = Path(get_launcher_data_dir()) / "capes"
    capes_dir.mkdir(parents=True, exist_ok=True)
    return capes_dir


def fetch_account_capes(access_token: str) -> List[Dict[str, Any]]:
    if not access_token:
        return []

    try:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "NLC-Minecraft-Launcher/1.0"
        }
        resp = requests.get(MOJANG_PROFILE_URL, headers=headers, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            capes = data.get("capes", [])
            logger.info("Retrieved %d capes for account %s", len(capes), data.get("name", "unknown"))
            return capes
        else:
            logger.warning("Failed to fetch capes: HTTP %d %s", resp.status_code, resp.text)
            return []
    except Exception as e:
        logger.error("Exception fetching account capes: %s", e)
        return []


def download_and_cache_cape(url: str, alias: str, force: bool = False) -> Optional[str]:
    if not url:
        return None

    try:
        cache_dir = get_capes_cache_dir()
        safe_alias = "".join(c for c in alias if c.isalnum() or c in ("-", "_")).lower() or "cape"
        filename = f"{safe_alias}.png"
        target_path = cache_dir / filename

        if target_path.exists() and not force and target_path.stat().st_size > 0:
            return str(target_path)

        headers = {"User-Agent": "NLC-Minecraft-Launcher/1.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200 and resp.content:
            with open(target_path, "wb") as f:
                f.write(resp.content)
            logger.info("Saved cape %s to %s (%d bytes)", alias, target_path, len(resp.content))
            return str(target_path)
        else:
            logger.warning("Failed to download cape %s: HTTP %d", alias, resp.status_code)
            return None
    except Exception as e:
        logger.error("Exception downloading cape %s: %s", alias, e)
        return None


def set_active_mojang_cape(access_token: str, cape_id: str) -> bool:
    if not access_token or not cape_id:
        return False

    try:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": "NLC-Minecraft-Launcher/1.0"
        }
        payload = {"capeId": cape_id}
        resp = requests.put(MOJANG_CAPE_ACTIVE_URL, headers=headers, json=payload, timeout=8)
        if resp.status_code in (200, 204):
            logger.info("Successfully equipped Mojang cape %s", cape_id)
            return True
        else:
            logger.warning("Failed to equip Mojang cape %s: HTTP %d %s", cape_id, resp.status_code, resp.text)
            return False
    except Exception as e:
        logger.error("Exception setting active Mojang cape: %s", e)
        return False


def clear_active_mojang_cape(access_token: str) -> bool:
    if not access_token:
        return False

    try:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "NLC-Minecraft-Launcher/1.0"
        }
        resp = requests.delete(MOJANG_CAPE_ACTIVE_URL, headers=headers, timeout=8)
        if resp.status_code in (200, 204):
            logger.info("Successfully unequipped Mojang cape")
            return True
        else:
            logger.warning("Failed to clear Mojang cape: HTTP %d %s", resp.status_code, resp.text)
            return False
    except Exception as e:
        logger.error("Exception clearing active Mojang cape: %s", e)
        return False


def upload_mojang_skin(access_token: str, skin_path: str, model: str = "classic") -> bool:
    if not access_token or not skin_path or not os.path.isfile(skin_path):
        logger.warning("upload_mojang_skin called with invalid arguments: token=%s, skin_path=%s", bool(access_token), skin_path)
        return False

    variant = "slim" if str(model).lower() in ("slim", "alex") else "classic"
    try:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "NLC-Minecraft-Launcher/1.0"
        }
        with open(skin_path, "rb") as f:
            files = {
                "variant": (None, variant),
                "file": ("skin.png", f, "image/png")
            }
            resp = requests.post(MOJANG_SKIN_URL, headers=headers, files=files, timeout=12)
            if resp.status_code == 200:
                logger.info("Successfully uploaded skin to Mojang servers (%s variant)", variant)
                return True
            else:
                logger.warning("Failed to upload skin to Mojang: HTTP %d %s", resp.status_code, resp.text)
                return False
    except Exception as e:
        logger.error("Exception uploading skin to Mojang: %s", e)
        return False
