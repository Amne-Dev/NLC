from __future__ import annotations

import sys
import os

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
if sys.stdin is None:
    sys.stdin = open(os.devnull, "r", encoding="utf-8")

import re
import time
import json
import os
import shutil
import base64
import importlib.util
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
import subprocess
from pathlib import Path
import requests
import urllib.parse
import hashlib
import uuid
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union
class _LazyImageModule:
    def __getattr__(self, name):
        from PIL import Image as _RealImage
        globals()["Image"] = _RealImage
        return getattr(_RealImage, name)

Image = _LazyImageModule()
import zipfile
import io
import tempfile
import socket
import struct

# Import backend NLC subsystems
from nlc.storage.paths import get_launcher_data_dir, get_config_path, get_minecraft_dir
from nlc.storage.config import ConfigManager, get_default_config
from nlc.core.vault import get_vault_manager, encrypt as vault_encrypt, decrypt as vault_decrypt, is_vault_string
from nlc.core.launch import patch_minecraft_launcher_launch_helpers
from nlc.net.ms_auth import MicrosoftDeviceAuth, MSA_CLIENT_ID, MSA_REDIRECT_URI
from nlc.net.elyby_auth import ElyByAuth
from nlc.net.skin_server import LocalSkinServer
from nlc.net.capes import (
    fetch_account_capes,
    download_and_cache_cape,
    set_active_mojang_cape,
    clear_active_mojang_cape,
    upload_mojang_skin,
)
from nlc.core.instances import sync_instance_assets
from nlc.core.skins import deduplicate_and_reroute_skin, cleanup_duplicate_skins, compute_skin_hash, is_subpath
from nlc.core.discord_rpc import DiscordRPCManager, sync_discord_avatar
class _LazyMinecraftLauncherLib:
    def __getattr__(self, name):
        import minecraft_launcher_lib
        globals()["minecraft_launcher_lib"] = minecraft_launcher_lib
        return getattr(minecraft_launcher_lib, name)

minecraft_launcher_lib = _LazyMinecraftLauncherLib()
import webbrowser

logger = logging.getLogger("agent")

# Ensure UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Global session for connection pooling
_session = None
ADDON_MANIFEST = "addon.json"

# Thread-safe transport locks
_stdout_lock = threading.Lock()
_process_lock = threading.Lock()
_config_lock = threading.RLock()
_pending_mojang_skin_upload: Optional[Dict[str, Any]] = None
_pending_mojang_skin_lock = threading.Lock()
_running_processes: Dict[str, Dict[str, Any]] = {}
_deferred_events: List[tuple] = []
_in_request_handling = False


def emit_event(event_name: str, payload: Any = None) -> None:
    if payload is None:
        payload = {}
    if threading.current_thread() is threading.main_thread() and _in_request_handling and event_name != "download_progress":
        _deferred_events.append((event_name, payload))
        return
    frame = json.dumps({"event": event_name, "payload": payload}, ensure_ascii=False)
    with _stdout_lock:
        try:
            sys.stdout.buffer.write(frame.encode("utf-8") + b"\n")
            sys.stdout.buffer.flush()
        except Exception:
            sys.stdout.write(frame + "\n")
            sys.stdout.flush()
def _on_discord_status_change(status: Dict[str, Any]) -> None:
    emit_event("discord_status_changed", status)

_discord_rpc_manager = DiscordRPCManager(on_status_change=_on_discord_status_change)


def _async_sync_discord_avatar(profile: Optional[Dict[str, Any]]) -> None:
    if not profile or not isinstance(profile, dict):
        return

    def _worker():
        try:
            cm = get_config_manager()
            url = sync_discord_avatar(profile, cm)
            if url:
                _discord_rpc_manager.set_player(
                    profile.get("name", "Steve"),
                    profile.get("uuid"),
                    profile.get("type", "microsoft"),
                    url,
                )
        except Exception as e:
            logger.debug("Background avatar sync exception: %s", e)

    threading.Thread(target=_worker, daemon=True, name="nlc-discord-avatar-sync").start()

def init_discord_rpc():
    try:
        cm = get_config_manager()
        cfg = cm.load()
        enabled = bool(cfg.get("rpc_enabled", cfg.get("discord_rpc", True)))
        detail_mode = str(cfg.get("rpc_detail_mode", cfg.get("discord_detail", "Show Version")))
        show_timer = bool(cfg.get("rpc_show_timer", cfg.get("discord_show_timer", True)))
        show_idle = bool(cfg.get("rpc_show_idle", cfg.get("discord_show_idle", True)))
        show_server = bool(cfg.get("rpc_show_server", cfg.get("discord_show_server", True)))
        streamer_mode = bool(cfg.get("streamer_mode", cfg.get("streamer_privacy", False)))
        client_id = cfg.get("discord_client_id")

        raw_active_idx = cfg.get("active_profile_index", cfg.get("current_profile_index", 0))
        try:
            active_idx = int(raw_active_idx)
        except Exception:
            active_idx = 0
        profiles = cfg.get("profiles", [])
        p_name = "Steve"
        p_uuid = None
        p_type = "microsoft"
        p_avatar = None
        if profiles and 0 <= active_idx < len(profiles):
            p = profiles[active_idx]
            p_name = p.get("name", "Steve")
            p_uuid = p.get("uuid")
            p_type = p.get("type", "microsoft")
            p_avatar = p.get("discord_avatar_url")

        if client_id:
            _discord_rpc_manager.set_client_id(str(client_id))
        _discord_rpc_manager.set_enabled(enabled)
        _discord_rpc_manager.set_detail_mode(detail_mode)
        _discord_rpc_manager.set_show_timer(show_timer)
        _discord_rpc_manager.set_show_idle(show_idle)
        _discord_rpc_manager.set_show_server(show_server)
        _discord_rpc_manager.set_streamer_mode(streamer_mode)
        _discord_rpc_manager.set_player(p_name, p_uuid, p_type, p_avatar)
        _discord_rpc_manager.start()
        if enabled:
            _discord_rpc_manager.set_idle("Play")
            if profiles and 0 <= active_idx < len(profiles):
                _async_sync_discord_avatar(profiles[active_idx])
    except Exception as e:
        logger.warning("Error initializing Discord RPC: %s", e)


def handle_discord_set_screen(payload: Dict[str, Any]) -> Dict[str, Any]:
    screen = str(payload.get("screen", "Play"))
    _discord_rpc_manager.set_screen(screen)
    return {"status": "success", "screen": screen}


def handle_agent_shutdown(payload: Dict[str, Any]) -> Dict[str, Any]:
    def _exit_soon():
        time.sleep(0.05)
        try:
            _WORKER_POOL.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        try:
            if _discord_rpc_manager:
                _discord_rpc_manager.stop()
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=_exit_soon, daemon=True, name="agent-shutdown").start()
    return {"status": "shutting_down"}


def _start_parent_watchdog():
    if sys.platform == "win32":
        try:
            import ctypes
            ppid = os.getppid()
            if ppid <= 0:
                return
            SYNCHRONIZE = 0x00100000
            h_proc = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, ppid)
            if not h_proc:
                return

            def _watch():
                ctypes.windll.kernel32.WaitForSingleObject(h_proc, 0xFFFFFFFF)
                ctypes.windll.kernel32.CloseHandle(h_proc)
                try:
                    _WORKER_POOL.shutdown(wait=False, cancel_futures=True)
                except Exception:
                    pass
                try:
                    if _discord_rpc_manager:
                        _discord_rpc_manager.stop()
                except Exception:
                    pass
                os._exit(0)

            t = threading.Thread(target=_watch, daemon=True, name="parent-watchdog")
            t.start()
        except Exception as e:
            logger.debug("Could not start Windows parent watchdog: %s", e)
    elif sys.platform.startswith("linux"):
        # On Linux, primary lifecycle is driven by stdin EOF in main loop.
        # Fallback watchdog thread detects if process becomes orphaned (ppid == 1).
        # Note: PR_SET_PDEATHSIG is intentionally avoided because in multithreaded
        # parents (such as Rust Tokio), PDEATHSIG is delivered when the spawning worker
        # thread terminates, not when the overall process terminates.
        try:
            orig_ppid = os.getppid()
            if orig_ppid > 1:
                def _linux_watch():
                    import time
                    orphan_count = 0
                    while True:
                        time.sleep(1.5)
                        current_ppid = os.getppid()
                        if current_ppid == 1:
                            orphan_count += 1
                            if orphan_count >= 2:
                                try:
                                    _WORKER_POOL.shutdown(wait=False, cancel_futures=True)
                                except Exception:
                                    pass
                                try:
                                    if _discord_rpc_manager:
                                        _discord_rpc_manager.stop()
                                except Exception:
                                    pass
                                os._exit(0)
                        else:
                            orphan_count = 0

                threading.Thread(target=_linux_watch, daemon=True, name="parent-watchdog-linux").start()
        except Exception as e:
            logger.debug("Could not start Linux parent watchdog thread: %s", e)



def send_response(req_id: Any = None, result: Any = None, error: Any = None) -> None:
    frame = json.dumps({"id": req_id, "result": result, "error": error}, ensure_ascii=False)
    with _stdout_lock:
        try:
            sys.stdout.buffer.write(frame.encode("utf-8") + b"\n")
            sys.stdout.buffer.flush()
        except Exception:
            sys.stdout.write(frame + "\n")
            sys.stdout.flush()


def flush_deferred_events() -> None:
    while _deferred_events:
        evt, payload = _deferred_events.pop(0)
        frame = json.dumps({"event": evt, "payload": payload}, ensure_ascii=False)
        with _stdout_lock:
            try:
                sys.stdout.buffer.write(frame.encode("utf-8") + b"\n")
                sys.stdout.buffer.flush()
            except Exception:
                sys.stdout.write(frame + "\n")
                sys.stdout.flush()


def get_launcher_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_config_dir() -> str:
    if len(sys.argv) > 1 and sys.argv[1]:
        val = sys.argv[1]
        if not val.startswith('-') and not val.endswith('.py') and not any(p in sys.argv[0].lower() for p in ('pytest', 'unittest')):
            return os.path.abspath(val)
    return str(get_launcher_data_dir())


def init_agent_logging():
    try:
        from logging.handlers import RotatingFileHandler
        import platform
        log_dir = Path(get_config_dir()) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "agent.log"
        handler = RotatingFileHandler(
            str(log_file),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8"
        )
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        handler.setFormatter(formatter)
        
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
            root_logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("==========================================")
        logger.info("NLC Agent Logger initialized. Log file: %s", log_file)
        logger.info("Platform: %s %s | Python: %s", platform.system(), platform.release(), sys.version.split()[0])
        logger.info("Data Directory: %s", get_config_dir())
        logger.info("==========================================")
    except Exception as e:
        sys.stderr.write(f"Failed to init agent logging: {e}\n")


def repair_modpack_icons():
    try:
        from PIL import Image
        packs_dir = Path(get_config_dir()) / "modpacks"
        if not packs_dir.exists():
            return
        for pack_folder in packs_dir.iterdir():
            if not pack_folder.is_dir():
                continue
            icon_file = pack_folder / "icon.png"
            if icon_file.exists() and icon_file.stat().st_size > 0:
                try:
                    with open(icon_file, "rb") as f:
                        header = f.read(8)
                    # PNG magic bytes: \x89PNG\r\n\x1a\n
                    if header != b"\x89PNG\r\n\x1a\n":
                        im = Image.open(icon_file)
                        im.save(icon_file, format="PNG")
                        logger.info("Repaired modpack icon for %s (converted %s to PNG format)", pack_folder.name, getattr(im, "format", "Unknown"))
                except Exception as err:
                    logger.warning("Failed to verify/repair icon for modpack %s: %s", pack_folder.name, err)
    except Exception as e:
        logger.warning("Error running repair_modpack_icons: %s", e)


def get_config_manager() -> ConfigManager:
    cfg_file = Path(get_config_dir()) / "launcher_config.json"
    return ConfigManager(config_path=cfg_file)


def load_launcher_config() -> Dict[str, Any]:
    return get_config_manager().load()


def get_third_party_addons_dir() -> str:
    addons_dir = os.path.join(get_config_dir(), "addons")
    os.makedirs(addons_dir, exist_ok=True)
    return addons_dir


def get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": "NewLauncher-Agent"})
    return _session


def get_file_sha(filepath: str) -> Optional[str]:
    if not os.path.exists(filepath):
        return None
    try:
        sha1 = hashlib.sha1()
        with open(filepath, "rb") as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                sha1.update(data)
        return sha1.hexdigest()
    except Exception:
        return None


# Configuration Handlers
def handle_config_get(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cm = get_config_manager()
    cfg = cm.load()
    if "offline_skin_injection" not in cfg:
        cfg["offline_skin_injection"] = cfg.get("skin_injection", cfg.get("auto_download_mod", True))
    res = dict(cfg)
    res["status"] = "success"
    res["data"] = cfg
    return res


def handle_config_set(payload: Dict[str, Any]) -> Dict[str, Any]:
    cm = get_config_manager()
    if isinstance(payload.get("updates"), dict):
        raw_updates = payload["updates"]
    elif isinstance(payload.get("patch"), dict):
        raw_updates = payload["patch"]
    else:
        raw_updates = {k: v for k, v in payload.items() if k not in ("id", "action")}

    if not isinstance(raw_updates, dict):
        raise ValueError("Config updates must be an object")

    # Slint UI <-> config.json alias map
    ALIAS_MAP = {
        "close_on_launch": "close_launcher",
        "keep_console_open": "show_console",
        "smooth_animations": "animations_enabled",
        "enable_walking_mobs": "enable_walking_mobs",
        "selected_theme": "theme_id",
        "custom_hex": "custom_accent",
        "ram_allocation_mb": "ram",
        "ram_allocation": "ram",
        "java_executable": "java_path",
        "jvm_arguments": "java_args",
        "minecraft_directory": "minecraft_dir",
        "max_modpack_downloads": "max_concurrent_packs",
        "max_mod_downloads": "max_concurrent_mods",
        "throttle_downloads": "limit_download_speed_enabled",
        "max_download_speed_kb": "max_download_speed",
        "check_updates_startup": "auto_update_check",
        "discord_rpc": "rpc_enabled",
        "discord_detail": "rpc_detail_mode",
        "discord_show_timer": "rpc_show_timer",
        "discord_show_idle": "rpc_show_idle",
        "discord_show_server": "rpc_show_server",
        "streamer_privacy": "streamer_mode",
        "default_offline_name": "username",
        "post_launch_behavior": "post_launch_action",
        "offline_skin_injection": "offline_skin_injection",
        "skin_injection": "offline_skin_injection",
        "auto_download_mod": "offline_skin_injection",
    }

    for k in ("default_offline_name", "username"):
        if k in raw_updates and raw_updates[k]:
            validate_minecraft_username(str(raw_updates[k]))

    with _config_lock:
        cfg = cm.load()
        cfg_instances = cfg.setdefault("instances", {})
        cfg_addons = cfg.setdefault("addons", {})

        for k, v in raw_updates.items():
            cfg[k] = v
            # Alias translation
            if k in ALIAS_MAP:
                cfg[ALIAS_MAP[k]] = v
            # Instances sub-settings
            if k in ("share_resource_packs", "share_resourcepacks"):
                cfg_instances["share_resourcepacks"] = bool(v)
            elif k in ("share_shader_packs", "share_shaderpacks"):
                cfg_instances["share_shaderpacks"] = bool(v)
            elif k in ("share_worlds",):
                cfg_instances["share_worlds"] = bool(v)
            elif k in ("share_mod_configs", "share_configs"):
                cfg_instances["share_configs"] = bool(v)
            elif k in ("streamer_privacy", "streamer_mode"):
                cfg_addons["streamer_mode_enabled"] = bool(v)

        # Propagate Discord RPC config updates immediately
        if "discord_rpc" in raw_updates or "rpc_enabled" in raw_updates:
            v = raw_updates.get("discord_rpc", raw_updates.get("rpc_enabled"))
            _discord_rpc_manager.set_enabled(bool(v))
        if "discord_detail" in raw_updates or "rpc_detail_mode" in raw_updates:
            v = raw_updates.get("discord_detail", raw_updates.get("rpc_detail_mode"))
            _discord_rpc_manager.set_detail_mode(str(v))
        if "discord_show_timer" in raw_updates or "rpc_show_timer" in raw_updates:
            v = raw_updates.get("discord_show_timer", raw_updates.get("rpc_show_timer"))
            _discord_rpc_manager.set_show_timer(bool(v))
        if "discord_show_idle" in raw_updates or "rpc_show_idle" in raw_updates:
            v = raw_updates.get("discord_show_idle", raw_updates.get("rpc_show_idle"))
            _discord_rpc_manager.set_show_idle(bool(v))
        if "discord_show_server" in raw_updates or "rpc_show_server" in raw_updates:
            v = raw_updates.get("discord_show_server", raw_updates.get("rpc_show_server"))
            _discord_rpc_manager.set_show_server(bool(v))
        if "streamer_privacy" in raw_updates or "streamer_mode" in raw_updates:
            v = raw_updates.get("streamer_privacy", raw_updates.get("streamer_mode"))
            _discord_rpc_manager.set_streamer_mode(bool(v))
        if "discord_client_id" in raw_updates:
            v = raw_updates.get("discord_client_id")
            _discord_rpc_manager.set_client_id(str(v))

        saved = cm.save(cfg)
        if not saved:
            return {
                "status": "error",
                "success": False,
                "message": "Failed to persist configuration to disk"
            }

    for k, v in raw_updates.items():
        emit_event("config_changed", {"key": k, "value": cfg.get(k)})

    return {
        "status": "success",
        "success": True,
        "updated_keys": list(raw_updates.keys()),
        "config": cfg,
    }


def handle_config_reset_defaults(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cm = get_config_manager()
    default_cfg = get_default_config()
    with _config_lock:
        cm.save(default_cfg)
    emit_event("config_changed", {"key": "all", "value": default_cfg})
    return {"status": "success", "success": True, "config": default_cfg}


# Account Management Handlers
def handle_accounts_list(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cm = get_config_manager()
    cfg = cm.load()
    profiles = cfg.get("profiles", [])
    cfg_accounts = cfg.get("accounts", [])

    if not isinstance(profiles, list):
        profiles = []

    if isinstance(cfg_accounts, list):
        existing_names = {p.get("name") or p.get("username") for p in profiles if isinstance(p, dict)}
        for acc in cfg_accounts:
            if isinstance(acc, dict):
                uname = acc.get("username") or acc.get("name")
                if uname and uname not in existing_names:
                    profiles.append({
                        "name": uname,
                        "username": uname,
                        "type": acc.get("account_type") or acc.get("type", "offline"),
                        "uuid": acc.get("uuid", str(uuid.uuid4())),
                        "skin_path": acc.get("skin_path", ""),
                        "skin_model": acc.get("skin_model", "classic"),
                    })
                    existing_names.add(uname)

    if not profiles:
        return {
            "status": "success",
            "accounts": [],
            "active_index": -1,
            "profiles": []
        }

    active_acc = cfg.get("active_account")
    active_idx = None
    if active_acc:
        for idx, p in enumerate(profiles):
            if p.get("name") == active_acc or p.get("username") == active_acc:
                active_idx = idx
                break
        if active_idx is None:
            profiles.append({
                "name": active_acc,
                "username": active_acc,
                "type": "offline",
                "uuid": str(uuid.uuid4()),
                "skin_path": "",
                "skin_model": "classic",
            })
            active_idx = len(profiles) - 1

    if active_idx is None:
        active_idx = cfg.get("active_profile_index", cfg.get("current_profile_index", 0))
    if not (0 <= active_idx < len(profiles)):
        active_idx = 0

    target_profile = profiles[active_idx]
    active_account_name = target_profile.get("name") or target_profile.get("username", "Steve")
    cfg["active_account"] = active_account_name
    cfg["active_profile_index"] = active_idx
    cfg["current_profile_index"] = active_idx

    # Ensure Discord RPC is synchronized with the active profile
    if _discord_rpc_manager and _discord_rpc_manager.player_name != active_account_name:
        try:
            _discord_rpc_manager.set_player(
                active_account_name,
                target_profile.get("uuid"),
                target_profile.get("type", "microsoft"),
                target_profile.get("discord_avatar_url")
            )
            _async_sync_discord_avatar(target_profile)
        except Exception:
            pass

    accounts_list = []
    cfg_models = cfg.get("skin_arm_models", {})
    for idx, p in enumerate(profiles):
        p_name = p.get("name") or p.get("username", "Steve")
        p_type = p.get("type") or p.get("account_type", "offline")
        p_id = p.get("uuid") or p.get("id") or str(idx)
        is_active = (idx == active_idx)
        s_path = p.get("skin_path", "")
        skin_key = Path(s_path).name if s_path else "default"
        preferred_model = cfg_models.get(skin_key) or p.get("skin_model", "classic")
        accounts_list.append({
            "name": p_name,
            "username": p_name,
            "type": p_type,
            "account_type": p_type,
            "id": p_id,
            "index": idx,
            "active": is_active,
            "skin_path": s_path,
            "skin_model": preferred_model,
            "uuid": p.get("uuid", p_id),
            "head_path": extract_player_head(s_path, p_name, p_id)
        })

    # Merge any extra accounts from cfg.get("accounts")
    if isinstance(cfg_accounts, list):
        existing_names = {a["name"] for a in accounts_list}
        for extra in cfg_accounts:
            if isinstance(extra, dict):
                uname = extra.get("name") or extra.get("username")
                extra_id = extra.get("uuid") or extra.get("id") or str(len(accounts_list))
                if uname and uname not in existing_names:
                    is_act = (uname == active_account_name)
                    e_path = extra.get("skin_path", "")
                    accounts_list.append({
                        "name": uname,
                        "username": uname,
                        "type": extra.get("type") or extra.get("account_type", "offline"),
                        "account_type": extra.get("type") or extra.get("account_type", "offline"),
                        "id": extra_id,
                        "index": len(accounts_list),
                        "active": is_act,
                        "skin_path": e_path,
                        "skin_model": extra.get("skin_model", "classic"),
                        "uuid": extra.get("uuid", extra_id),
                        "head_path": extract_player_head(e_path, uname, extra_id)
                    })

    return {
        "status": "success",
        "data": {
            "accounts": accounts_list,
            "active_account": active_account_name,
            "active_profile_index": active_idx,
        },
        "accounts": accounts_list,
        "active_account": active_account_name,
        "active_profile_index": active_idx,
    }


def handle_accounts_select(payload: Dict[str, Any]) -> Dict[str, Any]:
    cm = get_config_manager()
    cfg = cm.load()
    profiles = cfg.get("profiles", [])
    target_id = payload.get("id")
    target_idx = payload.get("index")
    target_username = payload.get("username") or payload.get("name")

    selected_idx = None
    # 1. First priority: match exact UUID / unique ID to prevent wrong account selection when usernames collide
    if target_id is not None:
        target_str = str(target_id)
        for idx, p in enumerate(profiles):
            if p.get("uuid") == target_str or p.get("id") == target_str or str(idx) == target_str:
                selected_idx = idx
                break
    # 2. Second priority: valid index
    if selected_idx is None and target_idx is not None and 0 <= target_idx < len(profiles):
        selected_idx = target_idx
    # 3. Last fallback: match by username
    elif selected_idx is None and target_username:
        for idx, p in enumerate(profiles):
            if p.get("name") == target_username:
                selected_idx = idx
                break

    if selected_idx is None:
        # Check accounts array as fallback
        cfg_accounts = cfg.get("accounts", [])
        if isinstance(cfg_accounts, list) and target_id:
            for a in cfg_accounts:
                if isinstance(a, dict) and (a.get("id") == target_id or a.get("username") == target_id):
                    cfg["active_account"] = a.get("username")
                    cm.save(cfg)
                    return {"status": "success", "active": target_id, "username": a.get("username")}
        if profiles:
            selected_idx = 0
        else:
            return {"status": "error", "msg": f"Profile not found: {target_id or target_idx}"}

    cfg["active_profile_index"] = selected_idx
    cfg["current_profile_index"] = selected_idx
    p = profiles[selected_idx]
    cfg["active_account"] = p.get("name", "Steve")
    cm.save(cfg)

    emit_event("config_changed", {"key": "active_profile_index", "value": selected_idx})
    emit_event("config_changed", {"key": "active_profile", "value": p})
    try:
        _discord_rpc_manager.set_player(p.get("name", "Steve"), p.get("uuid"), p.get("type", "microsoft"), p.get("discord_avatar_url"))
        _async_sync_discord_avatar(p)
    except Exception:
        pass
    return {
        "status": "success",
        "active": p.get("uuid", str(selected_idx)),
        "index": selected_idx,
        "username": p.get("name", "Steve")
    }


def validate_minecraft_username(username: str) -> None:
    if not username:
        raise ValueError("Username cannot be empty")
    if len(username) < 3:
        raise ValueError("Username must be at least 3 characters")
    if len(username) > 16:
        raise ValueError("Username cannot exceed 16 characters")
    if not re.fullmatch(r"^[a-zA-Z0-9_]+$", username):
        raise ValueError("Username can only contain letters, numbers, and underscores (_)")


def _fetch_mojang_skin_silent(username: str) -> Tuple[Optional[str], str]:
    try:
        import urllib.request
        import base64

        skins_dir = Path(get_config_dir()) / "skins"
        skins_dir.mkdir(parents=True, exist_ok=True)
        out_p = skins_dir / f"{username}.png"

        # Check if already cached
        if out_p.exists() and out_p.stat().st_size > 0:
            return str(out_p), "classic"

        mojang_url = f"https://api.mojang.com/users/profiles/minecraft/{username}"
        req = urllib.request.Request(mojang_url, headers={"User-Agent": "NLC-Launcher"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            uuid_str = data.get("id")

        if not uuid_str:
            return None, "classic"

        session_url = f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid_str}"
        req_s = urllib.request.Request(session_url, headers={"User-Agent": "NLC-Launcher"})
        model = "classic"
        skin_url = None
        with urllib.request.urlopen(req_s, timeout=3) as resp_s:
            data_s = json.loads(resp_s.read().decode())
            for prop in data_s.get("properties", []):
                if prop.get("name") == "textures":
                    tex_json = json.loads(base64.b64decode(prop.get("value", "")).decode())
                    skin_info = (tex_json.get("textures") or {}).get("SKIN") or {}
                    skin_url = skin_info.get("url")
                    meta = skin_info.get("metadata") or {}
                    if meta.get("model") == "slim":
                        model = "slim"
                    break

        if skin_url:
            req_dl = urllib.request.Request(skin_url, headers={"User-Agent": "NLC-Launcher"})
            with urllib.request.urlopen(req_dl, timeout=3) as resp_dl:
                with open(out_p, "wb") as f_out:
                    f_out.write(resp_dl.read())
            return str(out_p), model

    except Exception as exc:
        logger.debug("Silent skin fetch for %s skipped/failed: %s", username, exc)

    return None, "classic"


def handle_accounts_auth_offline(payload: Dict[str, Any]) -> Dict[str, Any]:
    cm = get_config_manager()
    cfg = cm.load()
    username = str(payload.get("username") or payload.get("name") or "").strip()
    if not username:
        raise ValueError("Username cannot be empty")
    if len(username) < 3:
        raise ValueError("Username must be at least 3 characters")
    if any(c in username for c in " -./@#!$%^&*()+=[]{}|\\:;\"'<>,?"):
        raise ValueError("Username can only contain letters, numbers, and underscores (_)")
    if len(username) > 16 and username.isascii():
        raise ValueError("Username cannot exceed 16 characters")

    profiles = cfg.setdefault("profiles", [])

    # Prevent creating duplicate offline account if an online account (microsoft or ely.by) already exists
    existing_online = next(
        (p for p in profiles if (p.get("name") or "").lower() == username.lower() and p.get("type") in ("microsoft", "elyby", "ely.by")),
        None
    )
    if existing_online:
        logger.info("Account %s already exists as online account (%s); skipping offline duplicate creation", username, existing_online.get("type"))
        return {
            "status": "success",
            "profile": existing_online,
            "index": profiles.index(existing_online),
            "skipped_duplicate": True
        }

    fetched_skin, fetched_model = _fetch_mojang_skin_silent(username)
    if fetched_skin:
        skin_path = fetched_skin
        skin_model = fetched_model
    else:
        skin_path = ""
        skin_model = payload.get("skin_model", "classic")

    offline_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{username}"))

    new_profile = {
        "name": username,
        "type": "offline",
        "skin_path": skin_path,
        "skin_model": skin_model,
        "uuid": offline_uuid
    }

    existing_idx = next((i for i, p in enumerate(profiles) if p.get("name") == username and p.get("type") == "offline"), None)
    if existing_idx is not None:
        profiles[existing_idx] = new_profile
        new_idx = existing_idx
    else:
        profiles.append(new_profile)
        new_idx = len(profiles) - 1

    cfg["active_profile_index"] = new_idx
    cfg["current_profile_index"] = new_idx
    cfg["active_account"] = username

    if "accounts" in cfg and isinstance(cfg["accounts"], list):
        cfg["accounts"] = [
            a for a in cfg["accounts"]
            if isinstance(a, dict) and not (a.get("id") == offline_uuid or a.get("username") == username)
        ]
        cfg["accounts"].append({
            "id": offline_uuid,
            "username": username,
            "account_type": "offline",
            "active": True
        })

    cm.save(cfg)

    try:
        _discord_rpc_manager.set_player(
            username,
            offline_uuid,
            "offline",
            new_profile.get("discord_avatar_url")
        )
        _async_sync_discord_avatar(new_profile)
    except Exception as rpc_err:
        logger.warning("Failed to update Discord RPC on offline login: %s", rpc_err)

    emit_event("config_changed", {"key": "profiles", "value": profiles})
    emit_event("config_changed", {"key": "active_profile_index", "value": new_idx})
    return {"status": "success", "profile": new_profile, "index": new_idx}


def handle_accounts_remove(payload: Dict[str, Any]) -> Dict[str, Any]:
    cm = get_config_manager()
    cfg = cm.load()
    target_username = str(payload.get("username") or payload.get("name") or "").strip()
    target_id = str(payload.get("id") or payload.get("uuid") or "").strip()
    target_index = payload.get("index")
    if target_index is not None:
        try:
            target_index = int(target_index)
        except (ValueError, TypeError):
            target_index = None

    profiles = cfg.get("profiles", [])
    def is_target(idx: int, p: Dict[str, Any]) -> bool:
        if target_index is not None:
            return idx == target_index
        if target_id and (str(p.get("uuid") or p.get("id") or "").strip() == target_id):
            return True
        if target_username and (str(p.get("name") or p.get("username") or "").strip() == target_username):
            return True
        return False

    new_profiles = [p for idx, p in enumerate(profiles) if not is_target(idx, p)]
    if not new_profiles:
        cfg["profiles"] = []
        cfg["active_account"] = ""
        cfg["active_profile_index"] = -1
        cfg["current_profile_index"] = -1
    else:
        cfg["profiles"] = new_profiles

    if "accounts" in cfg and isinstance(cfg["accounts"], list):
        cfg["accounts"] = [a for idx, a in enumerate(cfg["accounts"]) if not is_target(idx, a)]

    active_name = cfg.get("active_account", "")
    active_idx = cfg.get("active_profile_index", 0)

    if not new_profiles:
        cfg["active_account"] = ""
        cfg["active_profile_index"] = -1
        cfg["current_profile_index"] = -1
    elif (target_index is not None and target_index == active_idx) or active_name == target_username or active_idx >= len(new_profiles):
        cfg["active_account"] = new_profiles[0].get("name", "")
        cfg["active_profile_index"] = 0
        cfg["current_profile_index"] = 0
    elif target_index is not None and target_index < active_idx:
        new_idx = max(0, active_idx - 1)
        cfg["active_profile_index"] = new_idx
        cfg["current_profile_index"] = new_idx
        if new_idx < len(new_profiles):
            cfg["active_account"] = new_profiles[new_idx].get("name", "")
    else:
        found_idx = next((i for i, p in enumerate(new_profiles) if p.get("name") == active_name), 0)
        cfg["active_profile_index"] = found_idx
        cfg["current_profile_index"] = found_idx

    cm.save(cfg)
    emit_event("config_changed", {"key": "profiles", "value": new_profiles})
    emit_event("config_changed", {"key": "active_profile_index", "value": cfg["active_profile_index"]})
    active_prof = new_profiles[cfg["active_profile_index"]] if (new_profiles and 0 <= cfg["active_profile_index"] < len(new_profiles)) else None
    emit_event("config_changed", {"key": "active_profile", "value": active_prof})
    return {"status": "success", "remaining": len(new_profiles), "profiles": new_profiles}


def handle_accounts_auth_microsoft_start(payload: Dict[str, Any]) -> Dict[str, Any]:
    auth = MicrosoftDeviceAuth()
    device_data = auth.request_device_code()

    device_code = device_data["device_code"]
    interval = device_data.get("interval", 5)
    expires_in = device_data.get("expires_in", 900)

    def _poll_worker():
        try:
            token_data = auth.poll_token(device_code, interval, expires_in)
            if "error" in token_data:
                emit_event("ms_auth_completed", {"status": "error", "message": token_data.get("message", "Login failed")})
                return

            access_token = token_data["access_token"]
            refresh_token = token_data.get("refresh_token", "")

            xbl = minecraft_launcher_lib.microsoft_account.authenticate_with_xbl(access_token)
            xsts = minecraft_launcher_lib.microsoft_account.authenticate_with_xsts(xbl["Token"])
            mc_auth = minecraft_launcher_lib.microsoft_account.authenticate_with_minecraft(xbl["DisplayClaims"]["xui"][0]["uhs"], xsts["Token"])
            mc_profile = minecraft_launcher_lib.microsoft_account.get_profile(mc_auth["access_token"])

            # 1. Download active skin immediately
            skin_path = ""
            skin_model = "classic"
            skins = mc_profile.get("skins", [])
            active_skin = next((s for s in skins if s.get("state") == "ACTIVE"), skins[0] if skins else None)
            skins_dir = Path(get_config_dir()) / "skins"
            skins_dir.mkdir(parents=True, exist_ok=True)
            out_p = skins_dir / f"{mc_profile['name']}.png"

            if active_skin and active_skin.get("url"):
                try:
                    import urllib.request
                    req_dl = urllib.request.Request(active_skin["url"], headers={"User-Agent": "NLC-Launcher"})
                    with urllib.request.urlopen(req_dl, timeout=5) as resp_dl:
                        with open(out_p, "wb") as f_out:
                            f_out.write(resp_dl.read())
                    skin_path = str(out_p)
                    if str(active_skin.get("variant", "")).upper() == "SLIM":
                        skin_model = "slim"
                except Exception as s_err:
                    logger.warning("Failed to download MS skin from profile URL: %s", s_err)

            if not skin_path:
                fetched_p, fetched_m = _fetch_mojang_skin_silent(mc_profile["name"])
                if fetched_p:
                    skin_path = fetched_p
                    skin_model = fetched_m

            # 2. Extract player head thumbnail immediately
            head_path = ""
            if skin_path:
                try:
                    head_path = extract_player_head(skin_path, mc_profile["name"], mc_profile["id"], force=True)
                except Exception as h_err:
                    logger.warning("Failed to extract head thumbnail for %s: %s", mc_profile["name"], h_err)

            new_profile = {
                "name": mc_profile["name"],
                "uuid": mc_profile["id"],
                "type": "microsoft",
                "skin_path": skin_path,
                "skin_model": skin_model,
                "head_path": head_path,
                "access_token": vault_encrypt(mc_auth["access_token"]),
                "refresh_token": vault_encrypt(refresh_token) if refresh_token else "",
                "created": datetime.now().strftime("%Y-%m-%d")
            }

            cm = get_config_manager()
            cfg = cm.load()
            profiles = cfg.setdefault("profiles", [])

            # Update existing profile if UUID matches or same username
            existing_idx = next(
                (i for i, p in enumerate(profiles) if p.get("uuid") == mc_profile["id"] or (p.get("name") == mc_profile["name"] and p.get("type") == "microsoft")),
                None
            )
            if existing_idx is not None:
                profiles[existing_idx] = new_profile
                new_idx = existing_idx
            else:
                # Remove any offline account with the same name to prevent duplicates
                profiles = [p for p in profiles if not (p.get("name") == mc_profile["name"] and p.get("type") == "offline")]
                profiles.append(new_profile)
                cfg["profiles"] = profiles
                new_idx = len(profiles) - 1

            cfg["active_profile_index"] = new_idx
            cfg["current_profile_index"] = new_idx
            cfg["active_account"] = mc_profile["name"]

            if "accounts" in cfg and isinstance(cfg["accounts"], list):
                cfg["accounts"] = [
                    a for a in cfg["accounts"]
                    if isinstance(a, dict) and not (a.get("id") == mc_profile["id"] or a.get("username") == mc_profile["name"])
                ]
                cfg["accounts"].append({
                    "id": mc_profile["id"],
                    "username": mc_profile["name"],
                    "account_type": "microsoft",
                    "skin_path": skin_path,
                    "skin_model": skin_model,
                    "head_path": head_path,
                    "active": True
                })

            cm.save(cfg)

            # 3. IMMEDIATELY update Discord RPC with the player's real name and info
            try:
                _discord_rpc_manager.set_player(
                    mc_profile["name"],
                    mc_profile["id"],
                    "microsoft",
                    new_profile.get("discord_avatar_url")
                )
                _async_sync_discord_avatar(new_profile)
            except Exception as rpc_err:
                logger.warning("Failed to update Discord RPC on Microsoft login: %s", rpc_err)

            emit_event("ms_auth_completed", {"status": "success", "profile": new_profile})
            emit_event("config_changed", {"key": "profiles", "value": cfg["profiles"]})
            emit_event("config_changed", {"key": "active_profile_index", "value": new_idx})
        except Exception as exc:
            logger.exception("MS auth polling failed: %s", exc)
            emit_event("ms_auth_completed", {"status": "error", "message": str(exc)})

    threading.Thread(target=_poll_worker, daemon=True, name="ms-auth-poll").start()

    return {
        "status": "success",
        "user_code": device_data.get("user_code", ""),
        "verification_uri": device_data.get("verification_uri", ""),
        "expires_in": expires_in,
        "interval": interval
    }


def _fetch_elyby_skin(username: str, uuid_str: str, properties: Optional[List[Dict[str, Any]]] = None) -> str:
    skin_url = f"http://skinsystem.ely.by/skins/{username}.png"
    props = properties if properties else []

    try:
        if not props and uuid_str:
            try:
                session_url = f"https://authserver.ely.by/api/authlib-injector/sessionserver/session/minecraft/profile/{uuid_str}?unsigned=false"
                r_sess = requests.get(session_url, timeout=5)
                if r_sess.status_code == 200:
                    session_profile = r_sess.json()
                    props = session_profile.get("properties", [])
            except Exception as ex:
                logger.warning("Session Server fetch failed: %s", ex)

        if not props:
            try:
                r_tex = requests.get(f"http://skinsystem.ely.by/textures/{username}", timeout=5)
                if r_tex.status_code == 200:
                    tex_data_direct = r_tex.json()
                    if "SKIN" in tex_data_direct and "url" in tex_data_direct["SKIN"]:
                        skin_url = tex_data_direct["SKIN"]["url"]
                        props = []
            except Exception as e_tex:
                logger.warning("Skinsystem texture fetch failed: %s", e_tex)

        for prop in props:
            if prop.get("name") == "textures":
                val = prop.get("value", "")
                decoded = base64.b64decode(val).decode("utf-8")
                tex_data = json.loads(decoded)
                if "textures" in tex_data and "SKIN" in tex_data["textures"]:
                    extracted_url = tex_data["textures"]["SKIN"].get("url")
                    if extracted_url:
                        skin_url = extracted_url
    except Exception as e:
        logger.error("Failed to extract Ely.by skin data: %s", e)

    config_dir = get_launcher_data_dir()
    target_path = os.path.join(config_dir, "skins", f"{username}.png")
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    try:
        r_skin = requests.get(skin_url, timeout=5)
        if r_skin.status_code == 200:
            with open(target_path, "wb") as f:
                f.write(r_skin.content)
            return target_path
    except Exception as e:
        logger.warning("Skin fetch exception: %s", e)
        if os.path.exists(target_path):
            return target_path
    return ""


def compute_offline_uuid(username: str) -> str:
    m = hashlib.md5(f"OfflinePlayer:{username}".encode("utf-8")).digest()
    b = bytearray(m)
    b[6] = (b[6] & 0x0f) | 0x30  # UUID v3
    b[8] = (b[8] & 0x3f) | 0x80  # IETF variant
    return str(uuid.UUID(bytes=bytes(b)))


def _ensure_authlib_injector(mc_dir: str) -> str:
    jar_path = os.path.join(mc_dir, "authlib-injector.jar")
    if os.path.exists(jar_path) and os.path.getsize(jar_path) > 1000:
        return jar_path

    global_jar = os.path.join(get_launcher_data_dir(), "authlib-injector.jar")
    if os.path.exists(global_jar) and os.path.getsize(global_jar) > 1000:
        try:
            shutil.copy2(global_jar, jar_path)
            return jar_path
        except Exception:
            return global_jar

    headers = {"User-Agent": "NewLauncher/3.0"}
    # Try downloading from GitHub releases
    repo = "yushijinhun/authlib-injector"
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                if name.endswith(".jar") and not name.endswith("-javadoc.jar") and not name.endswith("-sources.jar"):
                    download_url = asset["browser_download_url"]
                    r_dl = requests.get(download_url, headers=headers, timeout=15)
                    if r_dl.status_code == 200 and len(r_dl.content) > 1000:
                        os.makedirs(mc_dir, exist_ok=True)
                        with open(jar_path, "wb") as f:
                            f.write(r_dl.content)
                        return jar_path
    except Exception as e:
        logger.warning("Could not download authlib-injector from GitHub API: %s", e)

    # Fallback to direct stable release asset if API rate-limited
    fallback_url = "https://github.com/yushijinhun/authlib-injector/releases/download/v1.2.5/authlib-injector-1.2.5.jar"
    try:
        r_fb = requests.get(fallback_url, headers=headers, timeout=15)
        if r_fb.status_code == 200 and len(r_fb.content) > 1000:
            os.makedirs(mc_dir, exist_ok=True)
            with open(jar_path, "wb") as f:
                f.write(r_fb.content)
            return jar_path
    except Exception as e_fb:
        logger.warning("Could not download authlib-injector fallback: %s", e_fb)

    return jar_path if os.path.exists(jar_path) else ""


def handle_accounts_auth_elyby(payload: Dict[str, Any]) -> Dict[str, Any]:
    username = str(payload.get("username") or payload.get("name") or "").strip()
    password = str(payload.get("password") or "").strip()
    if not username or not password:
        return {"status": "error", "message": "Username and password are required"}

    res = ElyByAuth.authenticate(username, password)
    if "error" in res:
        return {"status": "error", "message": res["error"]}

    profile_data = res.get("selectedProfile", {})
    uuid_str = profile_data.get("id", "")
    name_str = profile_data.get("name", username)
    token = res.get("accessToken", "")
    properties = profile_data.get("properties", [])

    skin_path = _fetch_elyby_skin(name_str, uuid_str, properties)

    new_profile = {
        "name": name_str,
        "type": "ely.by",
        "skin_path": skin_path,
        "uuid": uuid_str,
        "token": vault_encrypt(token) if token else ""
    }

    cm = get_config_manager()
    cfg = cm.load()
    profiles = cfg.setdefault("profiles", [])
    existing_idx = next((i for i, p in enumerate(profiles) if p.get("name") == name_str and p.get("type") == "ely.by"), None)
    if existing_idx is not None:
        profiles[existing_idx] = new_profile
        new_idx = existing_idx
    else:
        profiles.append(new_profile)
        new_idx = len(profiles) - 1

    cfg["active_profile_index"] = new_idx
    cfg["current_profile_index"] = new_idx
    cfg["active_account"] = name_str

    if "accounts" in cfg and isinstance(cfg["accounts"], list):
        cfg["accounts"] = [
            a for a in cfg["accounts"]
            if isinstance(a, dict) and not (a.get("id") == uuid_str or a.get("username") == name_str)
        ]
        cfg["accounts"].append({
            "id": uuid_str,
            "username": name_str,
            "account_type": "ely.by",
            "skin_path": skin_path,
            "skin_model": "classic",
            "active": True
        })

    cm.save(cfg)

    try:
        _discord_rpc_manager.set_player(
            name_str,
            uuid_str,
            "ely.by",
            new_profile.get("discord_avatar_url")
        )
        _async_sync_discord_avatar(new_profile)
    except Exception as rpc_err:
        logger.warning("Failed to update Discord RPC on Ely.by login: %s", rpc_err)

    emit_event("config_changed", {"key": "profiles", "value": profiles})
    emit_event("config_changed", {"key": "active_profile_index", "value": new_idx})
    return {"status": "success", "profile": new_profile, "index": new_idx}


def handle_system_open_url(payload: Dict[str, Any]) -> Dict[str, Any]:
    url = payload.get("url", "")
    if url:
        if sys.platform.startswith("linux"):
            clean_env = dict(os.environ)
            clean_env.pop("LD_LIBRARY_PATH", None)
            clean_env.pop("PYTHONPATH", None)
            clean_env.pop("PYTHONHOME", None)
            clean_env.pop("LD_PRELOAD", None)
            if "LD_LIBRARY_PATH_ORIG" in os.environ:
                clean_env["LD_LIBRARY_PATH"] = os.environ["LD_LIBRARY_PATH_ORIG"]
            try:
                subprocess.Popen(["xdg-open", url], env=clean_env)
            except Exception:
                webbrowser.open(url)
        else:
            webbrowser.open(url)
    return {"status": "success"}


def handle_system_copy_clipboard(payload: Dict[str, Any]) -> Dict[str, Any]:
    text = payload.get("text", "")
    if text:
        if sys.platform == "win32":
            try:
                subprocess.run("clip", input=text.encode("utf-16le"), check=True, creationflags=0x08000000)
            except Exception as e:
                logger.warning("Clip subprocess failed: %s", e)
        elif sys.platform.startswith("linux"):
            copied = False
            for tool, args in [("wl-copy", []), ("xclip", ["-selection", "clipboard"]), ("xsel", ["-b", "-i"])]:
                if shutil.which(tool):
                    try:
                        subprocess.run([tool] + args, input=text.encode("utf-8"), check=True, timeout=2)
                        copied = True
                        break
                    except Exception as e:
                        logger.debug("Clipboard helper %s failed: %s", tool, e)
            if not copied:
                logger.debug("No Linux clipboard helper (wl-copy, xclip, xsel) succeeded.")
    return {"status": "success"}


def handle_system_open_folder(payload: Dict[str, Any]) -> Dict[str, Any]:
    target = payload.get("target") or payload.get("path") or payload.get("instance_id") or ""
    target_str = str(target).strip()

    mc_dir = get_minecraft_dir()
    cfg_dir = get_config_dir()

    folder_path = None
    if target_str == "mods":
        folder_path = os.path.join(cfg_dir, "modpacks")
    elif target_str == "screenshots":
        folder_path = os.path.join(mc_dir, "screenshots")
    elif target_str == "logs":
        folder_path = os.path.join(cfg_dir, "logs")
    elif target_str in ("modpacks", "packs"):
        folder_path = os.path.join(cfg_dir, "modpacks")
    elif target_str in ("minecraft", "minecraft-dir", ".minecraft", "latest-release", ""):
        folder_path = mc_dir
    elif target_str == "cache":
        folder_path = os.path.join(cfg_dir, "cache")
    elif target_str in ("java", "java-detect"):
        folder_path = r"C:\Program Files\Java" if os.path.exists(r"C:\Program Files\Java") else mc_dir
    elif os.path.isabs(target_str) and (os.path.exists(target_str) or os.path.isdir(os.path.dirname(target_str))):
        folder_path = target_str
    else:
        pack_dir = os.path.join(cfg_dir, "modpacks", target_str)
        if os.path.exists(pack_dir):
            folder_path = pack_dir
        else:
            cfg = load_launcher_config()
            for inst in cfg.get("installations", []):
                if inst.get("id") == target_str:
                    gdir = inst.get("game_directory")
                    if gdir and os.path.exists(gdir):
                        folder_path = gdir
                    break
        if not folder_path:
            folder_path = mc_dir

    try:
        os.makedirs(folder_path, exist_ok=True)
        if sys.platform == "win32":
            subprocess.Popen(["explorer", os.path.abspath(folder_path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", os.path.abspath(folder_path)])
        else:
            clean_env = dict(os.environ)
            clean_env.pop("LD_LIBRARY_PATH", None)
            clean_env.pop("PYTHONPATH", None)
            clean_env.pop("PYTHONHOME", None)
            clean_env.pop("LD_PRELOAD", None)
            if "LD_LIBRARY_PATH_ORIG" in os.environ:
                clean_env["LD_LIBRARY_PATH"] = os.environ["LD_LIBRARY_PATH_ORIG"]
            subprocess.Popen(["xdg-open", os.path.abspath(folder_path)], env=clean_env)
    except Exception as e:
        logger.warning("Failed to open directory %s: %s", folder_path, e)
        return {"status": "error", "message": str(e), "path": folder_path}

    return {"status": "success", "success": True, "path": folder_path}


# Mod Management Handlers
def _resolve_instance_mods_dir(instance_id: str) -> str:
    cm = get_config_manager()
    cfg = cm.load()

    clean_id = instance_id.replace("inst-", "") if (instance_id and instance_id.startswith("inst-")) else instance_id

    # 1. Modpacks directory direct search (checking both raw and stripped id)
    for tid in filter(None, (instance_id, clean_id)):
        direct_pack_dir = Path(get_config_dir()) / "modpacks" / tid
        if direct_pack_dir.exists() and direct_pack_dir.is_dir():
            direct_mods = direct_pack_dir / "mods"
            direct_mods.mkdir(parents=True, exist_ok=True)
            return str(direct_mods)

    # 2. Modpacks metadata search (modpacks.json)
    mp_file = Path(get_config_dir()) / "modpacks.json"
    if mp_file.exists():
        try:
            with open(mp_file, "r", encoding="utf-8") as f:
                modpacks = json.load(f)
            if isinstance(modpacks, list):
                for mp in modpacks:
                    mp_id = mp.get("id", "")
                    mp_name = mp.get("name", "").lower().replace(" ", "-")
                    query = instance_id.lower().replace(" ", "-") if instance_id else ""
                    clean_query = clean_id.lower().replace(" ", "-") if clean_id else ""
                    if (
                        mp_id in (instance_id, clean_id)
                        or mp.get("linked_installation_id") in (instance_id, clean_id)
                        or (query and mp_name == query)
                        or (clean_query and mp_name == clean_query)
                        or (query and query in mp_id.lower())
                        or (clean_query and clean_query in mp_id.lower())
                    ):
                        pack_dir = Path(get_config_dir()) / "modpacks" / mp["id"] / "mods"
                        pack_dir.mkdir(parents=True, exist_ok=True)
                        return str(pack_dir)
        except Exception:
            pass

    # 3. Installations search
    for inst in cfg.get("installations", []):
        if (
            inst.get("id") in (instance_id, clean_id)
            or inst.get("name") in (instance_id, clean_id)
            or str(inst.get("name", "")).lower() in (str(instance_id).lower(), str(clean_id).lower())
        ):
            game_dir = inst.get("game_directory")
            if game_dir and os.path.exists(game_dir):
                mods_path = Path(game_dir) / "mods"
                mods_path.mkdir(parents=True, exist_ok=True)
                return str(mods_path)

    # 4. Default fallback
    default_mods = Path(get_minecraft_dir()) / "mods"
    default_mods.mkdir(parents=True, exist_ok=True)
    return str(default_mods)


def handle_mods_list_installed(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    instance_id = payload.get("instance_id") or payload.get("installation_id") or ""
    mods_dir = _resolve_instance_mods_dir(instance_id)

    from nlc.net.mod_icons import get_mod_info

    mods = []
    if os.path.isdir(mods_dir):
        for entry in os.scandir(mods_dir):
            if not entry.is_file():
                continue
            lower = entry.name.lower()
            if not (lower.endswith(".jar") or lower.endswith(".jar.disabled")):
                continue
            is_enabled = not lower.endswith(".disabled")
            clean_name = entry.name
            if lower.endswith(".jar.disabled"):
                clean_name = entry.name[:-13]
            elif lower.endswith(".jar"):
                clean_name = entry.name[:-4]

            mod_meta = get_mod_info(entry.path)
            display_name = mod_meta.get("name") or clean_name
            version_str = mod_meta.get("version", "")
            icon_path = mod_meta.get("icon_path", "")

            mods.append({
                "name": display_name,
                "file": entry.name,
                "filename": entry.name,
                "enabled": is_enabled,
                "version": version_str,
                "icon_path": icon_path,
                "size_bytes": entry.stat().st_size
            })
    mods.sort(key=lambda m: m["name"].lower())
    return mods


def handle_mods_toggle_enabled(payload: Dict[str, Any]) -> Dict[str, Any]:
    instance_id = payload.get("instance_id") or payload.get("installation_id") or ""
    filename = payload.get("filename") or payload.get("file") or ""
    enable_flag = payload.get("enabled", payload.get("enable"))

    mods_dir = _resolve_instance_mods_dir(instance_id)
    old_path = os.path.join(mods_dir, filename)
    if not os.path.exists(old_path):
        if os.path.exists(old_path + ".disabled"):
            old_path = old_path + ".disabled"
            filename = filename + ".disabled"
        elif filename.lower().endswith(".disabled") and os.path.exists(old_path[:-9]):
            old_path = old_path[:-9]
            filename = filename[:-9]
        else:
            raise FileNotFoundError(f"Mod file not found: {filename}")

    is_currently_enabled = not filename.lower().endswith(".disabled")
    target_enabled = not is_currently_enabled if enable_flag is None else bool(enable_flag)

    if target_enabled and not is_currently_enabled:
        new_filename = filename[:-9] if filename.lower().endswith(".disabled") else filename
    elif not target_enabled and is_currently_enabled:
        new_filename = filename + ".disabled"
    else:
        new_filename = filename

    new_path = os.path.join(mods_dir, new_filename)
    if old_path != new_path:
        os.replace(old_path, new_path)

    return {
        "status": "success",
        "success": True,
        "old_file": filename,
        "new_file": new_filename,
        "enabled": target_enabled
    }


# Modrinth Discovery & Installation Pipeline Handlers
def _format_speed(speed_bps: float) -> str:
    if speed_bps >= 1024 * 1024:
        return f"{speed_bps / (1024 * 1024):.1f} MB/s"
    elif speed_bps >= 1024:
        return f"{speed_bps / 1024:.0f} KB/s"
    return f"{int(speed_bps)} B/s"


def _safe_extract_zip(archive_path: str, destination_dir: str) -> None:
    dest_path = os.path.realpath(destination_dir)
    with zipfile.ZipFile(archive_path, "r") as zf:
        for member in zf.infolist():
            is_symlink = ((member.external_attr >> 16) & 0o170000) == 0o120000
            target_path = os.path.realpath(os.path.join(dest_path, member.filename))
            if is_symlink or os.path.commonpath((dest_path, target_path)) != dest_path:
                raise ValueError(f"Unsafe zip archive entry rejected: {member.filename}")
        zf.extractall(dest_path)


def _download_file_atomic(
    url: str,
    destination: Any,
    *,
    expected_sha1: Optional[str] = None,
    task_id: str = "",
    project_id: str = "",
    filename: Optional[str] = None,
    project_type: str = "mod",
    progress_offset: float = 0.0,
    progress_scale: float = 100.0,
    session: Optional[requests.Session] = None,
    timeout: int = 30,
) -> Path:
    from nlc.net.downloader import download_file

    dest_path = Path(destination).resolve()
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    file_name = filename or dest_path.name
    started_at = time.monotonic()
    last_emit = [0.0]

    def _progress_cb(downloaded: int, total_size: int):
        now = time.monotonic()
        if now - last_emit[0] >= 0.1 or (total_size and downloaded >= total_size):
            last_emit[0] = now
            elapsed = now - started_at
            speed_bps = int(downloaded / elapsed) if elapsed > 0.05 else 0
            pct = (downloaded / total_size * 100.0) if total_size else 0.0
            scaled_pct = round(progress_offset + (pct * progress_scale / 100.0), 1)
            emit_event("download_progress", {
                "task_id": task_id,
                "project_id": project_id,
                "filename": file_name,
                "project_type": project_type,
                "status": "downloading",
                "percentage": scaled_pct,
                "progress": scaled_pct,
                "speed_bps": speed_bps,
                "speed": _format_speed(speed_bps),
                "downloaded": downloaded,
                "downloaded_bytes": downloaded,
                "total": total_size,
                "total_bytes": total_size,
                "detail": f"Downloading {file_name} ({scaled_pct:.0f}%)",
            })

    headers = {"User-Agent": "AmneDev/NewLauncher/1.8.2"}
    return download_file(
        url,
        dest_path,
        chunk_size=64 * 1024,
        progress=_progress_cb,
        headers=headers,
        expected_sha1=expected_sha1,
        timeout=timeout,
        session=get_session(),
    )


def _extract_modpack_mods_internal(project_id_or_slug: str, versions: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    cache_dir = Path(get_config_dir()) / "cache" / "modpack_mods"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{project_id_or_slug}.json"

    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    mods = []
    try:
        session = get_session()
        headers = {"User-Agent": "AmneDev/NewLauncher/1.8.2"}
        if not versions:
            v_url = f"https://api.modrinth.com/v2/project/{urllib.parse.quote(project_id_or_slug)}/version"
            v_resp = session.get(v_url, headers=headers, timeout=12)
            if v_resp.status_code == 200:
                versions = v_resp.json()
        if versions:
            best_ver = versions[0]
            mr_file = next((f for f in best_ver.get("files", []) if f.get("filename", "").endswith(".mrpack")), None)
            if mr_file and mr_file.get("url"):
                mr_resp = session.get(mr_file["url"], headers=headers, timeout=20)
                if mr_resp.status_code == 200:
                    with zipfile.ZipFile(io.BytesIO(mr_resp.content)) as z:
                        if "modrinth.index.json" in z.namelist():
                            idx_data = json.loads(z.read("modrinth.index.json").decode("utf-8"))
                            for f in idx_data.get("files", []):
                                p = f.get("path", "")
                                if p.startswith("mods/"):
                                    clean_name = p.replace("mods/", "").replace(".jar", "")
                                    size_b = f.get("fileSize", 0)
                                    if size_b > 1048576:
                                        size_str = f"{size_b / 1048576:.1f} MB"
                                    elif size_b > 1024:
                                        size_str = f"{size_b / 1024:.0f} KB"
                                    else:
                                        size_str = f"{size_b} B" if size_b else ""
                                    mods.append({"name": clean_name, "size": size_str, "path": p})
        if mods:
            tmp_cache = cache_file.with_suffix(".tmp")
            with open(tmp_cache, "w", encoding="utf-8") as f:
                json.dump(mods, f, indent=2, ensure_ascii=False)
            os.replace(tmp_cache, cache_file)
    except Exception as exc:
        logger.debug("Failed extracting modpack mods for %s: %s", project_id_or_slug, exc)
    return mods


def _cache_modrinth_icons(hits: List[Dict[str, Any]]) -> None:
    icons_dir = Path(get_config_dir()) / "cache" / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)
    session = get_session()
    headers = {"User-Agent": "AmneDev/NewLauncher/1.8.2"}

    def _fetch_one(hit):
        icon_url = hit.get("icon_url")
        project_id = hit.get("project_id") or hit.get("id")
        if not icon_url or not project_id:
            return
        dest = icons_dir / f"{project_id}.png"
        if dest.exists() and dest.stat().st_size > 0:
            hit["icon_path"] = str(dest)
            return
        try:
            r = session.get(icon_url, headers=headers, timeout=5)
            if r.status_code == 200 and r.content:
                try:
                    from PIL import Image
                    im = Image.open(io.BytesIO(r.content))
                    tmp = dest.with_suffix(".tmp")
                    im.save(tmp, format="PNG")
                    os.replace(tmp, dest)
                except Exception:
                    tmp = dest.with_suffix(".tmp")
                    with open(tmp, "wb") as f:
                        f.write(r.content)
                    os.replace(tmp, dest)
                hit["icon_path"] = str(dest)
        except Exception:
            pass

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(_fetch_one, hits))


def handle_modrinth_search(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    query = payload.get("query", "")
    project_type = payload.get("project_type", "mod")
    loader = payload.get("loader")
    version = payload.get("version")
    sort = payload.get("sort") or payload.get("index")
    limit = payload.get("limit", 20)
    offset = payload.get("offset", 0)

    facets = list(payload.get("facets", []))
    if not facets:
        if project_type and project_type.lower() != "all":
            facets.append(f"project_type:{project_type.lower()}")
        if loader and loader.lower() not in ("vanilla", "all") and (not project_type or project_type.lower() not in ("resourcepack", "shader")):
            facets.append(f"categories:{loader.lower()}")
        if version and version.lower() != "all":
            facets.append(f"versions:{version}")

    adapted_payload = {
        "query": query,
        "limit": limit,
        "offset": offset,
        "facets": facets,
        "sort": sort,
        "project_type": project_type,
        "loader": loader,
        "version": version,
    }
    raw_res = handle_search_mods(adapted_payload)
    if raw_res.get("status") == "success" and "data" in raw_res:
        hits = raw_res["data"].get("hits", [])
        _cache_modrinth_icons(hits)
        return hits
    return []


def handle_modrinth_project_details(payload: Dict[str, Any]) -> Dict[str, Any]:
    project_id = str(payload.get("project_id") or payload.get("id") or payload.get("slug") or "").strip()
    if not project_id:
        return {"status": "error", "msg": "Missing project_id or slug"}

    cache_dir = Path(get_config_dir()) / "cache" / "projects"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{project_id}.json"

    if cache_file.exists():
        try:
            mtime = cache_file.stat().st_mtime
            if time.time() - mtime < 900:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if isinstance(cached, dict) and (cached.get("title") or cached.get("id")) and "versions" in cached:
                    return cached
        except Exception:
            pass

    session = get_session()
    headers = {"User-Agent": "AmneDev/NewLauncher/1.8.2"}

    try:
        url = f"https://api.modrinth.com/v2/project/{urllib.parse.quote(project_id)}"
        resp = session.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
            return {"status": "error", "code": resp.status_code, "msg": f"Failed to fetch project details: {resp.text}"}

        proj = resp.json()
        real_id = proj.get("id", project_id)

        v_url = f"https://api.modrinth.com/v2/project/{urllib.parse.quote(real_id)}/version"
        v_resp = session.get(v_url, headers=headers, timeout=15)
        versions = v_resp.json() if v_resp.status_code == 200 else []

        project_type = proj.get("project_type", "mod")
        included_mods = []
        if project_type == "modpack":
            included_mods = _extract_modpack_mods_internal(project_id, versions)

        result = {
            "status": "success",
            "id": real_id,
            "slug": proj.get("slug", project_id),
            "title": proj.get("title", ""),
            "description": proj.get("description", ""),
            "body": proj.get("body", ""),
            "icon_url": proj.get("icon_url"),
            "gallery": proj.get("gallery", []),
            "project_type": project_type,
            "downloads": proj.get("downloads", 0),
            "followers": proj.get("followers", proj.get("follows", 0)),
            "loaders": proj.get("loaders", []),
            "game_versions": proj.get("game_versions", []),
            "license": proj.get("license", {}),
            "versions": versions,
            "included_mods": included_mods,
            "project": proj,
        }

        try:
            tmp_cache = cache_file.with_suffix(".tmp")
            with open(tmp_cache, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            os.replace(tmp_cache, cache_file)
        except Exception as e:
            logger.debug("Failed saving project cache for %s: %s", project_id, e)

        return result

    except Exception as exc:
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"status": "error", "msg": f"Network error: {str(exc)}"}


def _is_real_modpack_or_instance(target_id: str) -> bool:
    if not target_id or target_id in ("Global", "Global (.minecraft)", "__global__"):
        return False
    # Check modpacks
    for mp in _load_modpacks_json():
        if mp.get("id") == target_id or mp.get("name") == target_id or mp.get("linked_installation_id") == target_id:
            return True
    # Check installations
    cfg = load_launcher_config()
    for inst in cfg.get("installations", []):
        if inst.get("id") == target_id or inst.get("name") == target_id:
            return True
    return False


def _is_version_like_string(s: Optional[str]) -> bool:
    if not s:
        return True
    s_clean = s.strip()
    if re.match(r"^v?\d+(\.\d+)+", s_clean, re.IGNORECASE):
        return True
    if re.match(r"^(release|snapshot|server|beta|alpha|v\d+)", s_clean, re.IGNORECASE):
        return True
    return False


def detect_loader_from_modpack(
    dependencies: Optional[Dict[str, Any]] = None,
    version_loaders: Optional[List[str]] = None,
    project_loaders: Optional[List[str]] = None,
    files: Optional[List[Dict[str, Any]]] = None,
) -> str:
    deps = {str(k).lower(): str(v).lower() for k, v in (dependencies or {}).items()}
    v_loaders = [str(l).lower() for l in (version_loaders or [])]
    p_loaders = [str(l).lower() for l in (project_loaders or [])]

    # 1. Quilt detection (highest priority over fabric compatibility)
    if "quilt-loader" in deps or "quilt" in deps or "quilt" in v_loaders:
        return "quilt"
    if any(k.startswith("quilt") for k in deps):
        return "quilt"
    if files:
        for f in files:
            p = str(f.get("path") or "").lower()
            if "quilted-fabric-api" in p or "qsl" in p or "quilt-loading-screen" in p:
                return "quilt"

    # 2. NeoForge detection (highest priority over legacy forge)
    if "neoforge" in deps or "neoforge-loader" in deps or "neoforge" in v_loaders:
        return "neoforge"
    if any(k.startswith("neoforge") for k in deps):
        return "neoforge"
    if files:
        for f in files:
            p = str(f.get("path") or "").lower()
            if "neoforge" in p:
                return "neoforge"

    # 3. Forge detection (exact loader check, not generic substrings)
    if "forge" in deps or ("forge" in v_loaders and "neoforge" not in v_loaders):
        return "forge"
    if any(k == "forge" or (k.startswith("forge-") and "config" not in k and "port" not in k) for k in deps):
        return "forge"

    # 4. Fabric detection
    if "fabric-loader" in deps or "fabric" in deps or "fabric" in v_loaders:
        return "fabric"
    if any(k.startswith("fabric-loader") for k in deps):
        return "fabric"

    # 5. Project-level fallback
    if "quilt" in p_loaders:
        return "quilt"
    if "neoforge" in p_loaders:
        return "neoforge"
    if "forge" in p_loaders and "neoforge" not in p_loaders:
        return "forge"
    if "fabric" in p_loaders:
        return "fabric"

    return "vanilla"


def handle_modrinth_install_artifact(payload: Dict[str, Any]) -> Dict[str, Any]:
    project_id = str(payload.get("project_id") or payload.get("id") or payload.get("slug") or "").strip()
    project_type = str(payload.get("project_type") or "mod").strip().lower()
    target_id = str(payload.get("target_id") or payload.get("instance_id") or payload.get("pack_id") or payload.get("installation_id") or "").strip()
    version_id = payload.get("version_id")
    url = payload.get("url") or payload.get("download_url")
    filename = payload.get("filename")
    expected_sha1 = payload.get("sha1") or (payload.get("hashes") or {}).get("sha1")
    task_id = str(payload.get("task_id") or f"dl-{uuid.uuid4().hex[:8]}")
    title = str(payload.get("title") or payload.get("name") or payload.get("pack_name") or project_id or "artifact")

    if not project_id and not url:
        return {"status": "error", "success": False, "task_id": task_id, "msg": "Missing project_id or url"}

    session = get_session()
    headers = {"User-Agent": "AmneDev/NewLauncher/1.8.2"}

    try:
        # Mock mode for testing
        if payload.get("mock", False):
            emit_event("download_progress", {
                "task_id": task_id,
                "project_id": project_id,
                "filename": filename or f"{project_id}.jar",
                "project_type": project_type,
                "status": "downloading",
                "percentage": 50.0,
                "progress": 50.0,
                "speed_bps": 1048576,
                "speed": "1.0 MB/s",
                "downloaded": 524288,
                "downloaded_bytes": 524288,
                "total": 1048576,
                "total_bytes": 1048576,
                "detail": f"Mock downloading {project_id}...",
            })
            emit_event("download_progress", {
                "task_id": task_id,
                "project_id": project_id,
                "filename": filename or f"{project_id}.jar",
                "project_type": project_type,
                "status": "completed",
                "percentage": 100.0,
                "progress": 100.0,
                "speed_bps": 0,
                "speed": "0 B/s",
                "downloaded": 1048576,
                "downloaded_bytes": 1048576,
                "total": 1048576,
                "total_bytes": 1048576,
                "detail": f"Completed mock install for {project_id}",
            })
            return {
                "status": "success",
                "success": True,
                "task_id": task_id,
                "project_id": project_id,
                "project_type": project_type,
                "filename": filename or f"{project_id}.jar",
                "mock": True,
            }

        if project_type == "modpack":
            proj_meta = {}
            try:
                p_resp = session.get(f"https://api.modrinth.com/v2/project/{urllib.parse.quote(project_id)}", headers=headers, timeout=12)
                if p_resp.status_code == 200:
                    proj_meta = p_resp.json()
            except Exception as e_p:
                logger.debug("Failed fetching project metadata for %s: %s", project_id, e_p)

            project_display_title = (
                payload.get("title")
                or proj_meta.get("title")
                or (title if title and title != project_id and not title.endswith(".mrpack") else None)
                or proj_meta.get("slug")
                or project_id
            )

            emit_event("download_progress", {
                "task_id": task_id,
                "project_id": project_id,
                "filename": filename or f"{project_id}.mrpack",
                "project_type": "modpack",
                "status": "queued",
                "percentage": 0.0,
                "progress": 0.0,
                "speed_bps": 0,
                "speed": "0 B/s",
                "downloaded": 0,
                "downloaded_bytes": 0,
                "total": 0,
                "total_bytes": 0,
                "detail": f"Fetching metadata for modpack {project_display_title}...",
            })

            version_data = {}
            if not url:
                v_url = f"https://api.modrinth.com/v2/project/{urllib.parse.quote(project_id)}/version"
                r = session.get(v_url, headers=headers, timeout=15)
                if r.status_code != 200:
                    raise Exception(f"Failed to fetch modpack versions: HTTP {r.status_code}")
                versions = r.json()
                mr_versions = [v for v in versions if any(f.get("filename", "").endswith(".mrpack") for f in v.get("files", []))]
                if not mr_versions:
                    raise Exception(f"No installable .mrpack versions found for modpack '{project_id}'")
                best_ver = mr_versions[0]
                if version_id:
                    for v in mr_versions:
                        if v.get("id") == version_id:
                            best_ver = v
                            break
                version_data = best_ver
                mr_file = next(f for f in best_ver.get("files", []) if f.get("filename", "").endswith(".mrpack"))
                url = mr_file["url"]
                filename = mr_file.get("filename") or f"{project_id}.mrpack"
                expected_sha1 = (mr_file.get("hashes") or {}).get("sha1")
            else:
                if not filename:
                    filename = os.path.basename(urllib.parse.urlsplit(url).path) or f"{project_id}.mrpack"

            with tempfile.TemporaryDirectory() as temp_dir:
                mr_path = os.path.join(temp_dir, "pack.mrpack")
                _download_file_atomic(
                    url,
                    mr_path,
                    expected_sha1=expected_sha1,
                    task_id=task_id,
                    project_id=project_id,
                    filename=filename,
                    project_type="modpack",
                    progress_offset=0.0,
                    progress_scale=10.0,
                )

                emit_event("download_progress", {
                    "task_id": task_id,
                    "project_id": project_id,
                "title": title,
                    "filename": filename,
                    "project_type": "modpack",
                    "status": "extracting",
                    "percentage": 10.0,
                    "progress": 10.0,
                    "speed_bps": 0,
                    "speed": "0 B/s",
                    "downloaded": 0,
                    "downloaded_bytes": 0,
                    "total": 0,
                    "total_bytes": 0,
                    "detail": "Extracting modpack archive...",
                })
                _safe_extract_zip(mr_path, temp_dir)

                index_path = os.path.join(temp_dir, "modrinth.index.json")
                if not os.path.exists(index_path):
                    raise ValueError("Invalid modpack: missing modrinth.index.json")
                with open(index_path, "r", encoding="utf-8") as f:
                    idx = json.load(f)

                new_id = target_id if target_id else str(uuid.uuid4())
                pack_dir = _get_modpack_dir(new_id)
                (pack_dir / "mods").mkdir(parents=True, exist_ok=True)

                files_list = idx.get("files", [])
                total_files = len(files_list)
                completed_files = 0

                for file_def in files_list:
                    d_urls = file_def.get("downloads", [])
                    d_url = d_urls[0] if d_urls else ""
                    f_path = str(file_def.get("path") or "").replace("\\", "/").lstrip("/")
                    if not f_path or not d_url:
                        completed_files += 1
                        continue

                    dest = os.path.abspath(os.path.join(str(pack_dir), f_path))
                    if os.path.commonpath((str(pack_dir), dest)) != str(pack_dir):
                        raise ValueError(f"Unsafe modpack file path: {f_path}")

                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    f_sha1 = (file_def.get("hashes") or {}).get("sha1")
                    cur_offset = 10.0 + (completed_files / max(total_files, 1)) * 75.0
                    cur_scale = 75.0 / max(total_files, 1)

                    _download_file_atomic(
                        d_url,
                        dest,
                        expected_sha1=f_sha1,
                        task_id=task_id,
                        project_id=project_id,
                        filename=os.path.basename(f_path),
                        project_type="modpack",
                        progress_offset=cur_offset,
                        progress_scale=cur_scale,
                    )
                    completed_files += 1

                emit_event("download_progress", {
                    "task_id": task_id,
                    "project_id": project_id,
                "title": title,
                    "filename": filename,
                    "project_type": "modpack",
                    "status": "installing",
                    "percentage": 88.0,
                    "progress": 88.0,
                    "speed_bps": 0,
                    "speed": "0 B/s",
                    "downloaded": 0,
                    "downloaded_bytes": 0,
                    "total": 0,
                    "total_bytes": 0,
                    "detail": "Applying modpack overrides…",
                })

                for override_folder in ("overrides", "client-overrides"):
                    override_dir = os.path.join(temp_dir, override_folder)
                    if os.path.isdir(override_dir):
                        for root_d, dirs, files in os.walk(override_dir):
                            rel = os.path.relpath(root_d, override_dir)
                            target_sub = os.path.abspath(os.path.join(str(pack_dir), rel)) if rel != "." else str(pack_dir)
                            if os.path.commonpath((str(pack_dir), target_sub)) != str(pack_dir):
                                continue
                            os.makedirs(target_sub, exist_ok=True)
                            for f in files:
                                src_f = os.path.join(root_d, f)
                                dst_f = os.path.join(target_sub, f)
                                shutil.copy2(src_f, dst_f)

                deps = idx.get("dependencies", {})
                mc_ver = str(deps.get("minecraft") or (version_data.get("game_versions", ["1.21.1"])[0] if version_data.get("game_versions") else "1.21.1"))
                loader = detect_loader_from_modpack(
                    dependencies=deps,
                    version_loaders=version_data.get("loaders"),
                    project_loaders=proj_meta.get("loaders"),
                    files=files_list,
                )

                ver_name = (
                    version_data.get("name")
                    or version_data.get("version_number")
                    or idx.get("name")
                    or idx.get("versionId")
                    or "1.0.0"
                )

                # Use canonical project title as the modpack name
                pack_name = (
                    payload.get("title")
                    or proj_meta.get("title")
                    or (idx.get("name") if idx.get("name") and not _is_version_like_string(idx.get("name")) else None)
                    or project_display_title
                    or "Modpack"
                )

                # Download modpack project icon if available
                icon_path_str = None
                p_icon_url = proj_meta.get("icon_url")
                if p_icon_url:
                    try:
                        icon_dest = pack_dir / "icon.png"
                        ic_r = session.get(p_icon_url, headers=headers, timeout=10)
                        if ic_r.status_code == 200 and ic_r.content:
                            try:
                                from PIL import Image
                                im = Image.open(io.BytesIO(ic_r.content))
                                im.save(icon_dest, format="PNG")
                            except Exception:
                                with open(icon_dest, "wb") as f_ic:
                                    f_ic.write(ic_r.content)
                            icon_path_str = str(icon_dest)
                    except Exception as e_ic:
                        logger.warning("Could not download modpack icon for %s: %s", project_id, e_ic)

                new_pack = {
                    "id": new_id,
                    "name": pack_name,
                    "loader": loader,
                    "mc_version": mc_ver,
                    "version": mc_ver,
                    "version_id": idx.get("versionId", ""),
                    "version_name": ver_name,
                    "pack_release": ver_name,
                    "icon": icon_path_str,
                    "icon_path": icon_path_str,
                    "mods": [],
                    "linked_installation_id": None,
                    "created": datetime.now().strftime("%Y-%m-%d"),
                }

                for f_def in files_list:
                    p = str(f_def.get("path") or "").replace("\\", "/").lstrip("/")
                    if p.startswith("mods/"):
                        fn = os.path.basename(p)
                        new_pack["mods"].append({
                            "slug": fn.replace(".jar", ""),
                            "filename": fn,
                            "version_id": "",
                        })

                with _config_lock:
                    packs = _load_modpacks_json()
                    packs = [p for p in packs if p.get("id") != new_id]
                    packs.append(new_pack)
                    _save_modpacks_json(packs)

                emit_event("modpacks_changed", {"action": "modpack_created", "pack": new_pack, "modpacks": packs})
                emit_event("download_progress", {
                    "task_id": task_id,
                    "project_id": project_id,
                    "filename": filename,
                    "project_type": "modpack",
                    "status": "completed",
                    "percentage": 100.0,
                    "progress": 100.0,
                    "speed_bps": 0,
                    "speed": "0 B/s",
                    "downloaded": 0,
                    "downloaded_bytes": 0,
                    "total": 0,
                    "total_bytes": 0,
                    "detail": f"Installed modpack {pack_name} ✓",
                })
                return {
                    "status": "success",
                    "success": True,
                    "task_id": task_id,
                    "pack_id": new_id,
                    "pack": new_pack,
                    "target_path": str(pack_dir),
                }

        elif project_type == "mod":
            mods_dir = _resolve_instance_mods_dir(target_id)
            os.makedirs(mods_dir, exist_ok=True)

            if not url:
                loader = None
                mc_version = None
                packs = _load_modpacks_json()
                for p in packs:
                    if p.get("id") == target_id or p.get("name") == target_id or p.get("linked_installation_id") == target_id:
                        loader = p.get("loader")
                        mc_version = p.get("mc_version")
                        break
                if not loader:
                    cfg = load_launcher_config()
                    for inst in cfg.get("installations", []):
                        if inst.get("id") == target_id or inst.get("name") == target_id:
                            loader = inst.get("loader")
                            mc_version = inst.get("version")
                            break

                v_url = f"https://api.modrinth.com/v2/project/{urllib.parse.quote(project_id)}/version"
                params = []
                if loader and loader.lower() not in ("vanilla", "all"):
                    params.append(f'loaders=[%22{loader.lower()}%22]')
                if mc_version and mc_version.lower() != "all":
                    params.append(f'game_versions=[%22{mc_version}%22]')
                if params:
                    v_url += "?" + "&".join(params)

                r = session.get(v_url, headers=headers, timeout=15)
                if r.status_code != 200:
                    raise Exception(f"Failed to fetch mod versions: HTTP {r.status_code}")
                versions = r.json()
                if not versions:
                    raise Exception(f"No compatible version found for mod '{project_id}'")
                best_ver = versions[0]
                if version_id:
                    for v in versions:
                        if v.get("id") == version_id:
                            best_ver = v
                            break
                files = best_ver.get("files", [])
                if not files:
                    raise Exception("No downloadable files found in version")
                primary_file = next((f for f in files if f.get("primary", False)), files[0])
                url = primary_file["url"]
                filename = primary_file.get("filename") or f"{project_id}.jar"
                expected_sha1 = (primary_file.get("hashes") or {}).get("sha1")
                version_id = best_ver.get("id")
            else:
                if not filename:
                    filename = os.path.basename(urllib.parse.urlsplit(url).path) or f"{project_id}.jar"

            dest_path = os.path.join(mods_dir, filename)
            _download_file_atomic(
                url,
                dest_path,
                expected_sha1=expected_sha1,
                task_id=task_id,
                project_id=project_id,
                filename=filename,
                project_type="mod",
            )

            with _config_lock:
                packs = _load_modpacks_json()
                for p in packs:
                    if p.get("id") == target_id or p.get("name") == target_id or p.get("linked_installation_id") == target_id:
                        if not any(m.get("filename") == filename or m.get("slug") == project_id for m in p.get("mods", [])):
                            if "mods" not in p:
                                p["mods"] = []
                            p["mods"].append({
                                "slug": project_id,
                                "filename": filename,
                                "version_id": version_id or "",
                            })
                            _save_modpacks_json(packs)
                            emit_event("modpacks_changed", {"action": "mod_installed", "pack_id": p["id"]})
                        break

            emit_event("download_progress", {
                "task_id": task_id,
                "project_id": project_id,
                "filename": filename,
                "project_type": "mod",
                "status": "completed",
                "percentage": 100.0,
                "progress": 100.0,
                "speed_bps": 0,
                "speed": "0 B/s",
                "downloaded": 0,
                "downloaded_bytes": 0,
                "total": 0,
                "total_bytes": 0,
                "detail": f"Installed {filename} ✓",
            })
            return {
                "status": "success",
                "success": True,
                "task_id": task_id,
                "project_id": project_id,
                "project_type": "mod",
                "filename": filename,
                "target_path": dest_path,
            }

        elif project_type in ("resourcepack", "shader"):
            folder_name = "shaderpacks" if project_type == "shader" else "resourcepacks"
            cfg = load_launcher_config()

            target_dir = None
            if target_id and _is_real_modpack_or_instance(target_id):
                for inst in cfg.get("installations", []):
                    if inst.get("id") == target_id or inst.get("name") == target_id or str(inst.get("name", "")).lower() == target_id.lower():
                        g_dir = inst.get("game_directory")
                        if g_dir and os.path.exists(g_dir):
                            target_dir = os.path.join(g_dir, folder_name)
                        break
                if not target_dir:
                    mp_base = os.path.join(get_config_dir(), "modpacks")
                    for mp in _load_modpacks_json():
                        if mp.get("id") == target_id or mp.get("name") == target_id or str(mp.get("name", "")).lower() == target_id.lower():
                            p_dir = os.path.join(mp_base, mp["id"])
                            if os.path.isdir(p_dir):
                                target_dir = os.path.join(p_dir, folder_name)
                            break
            if not target_dir:
                target_dir = os.path.join(get_minecraft_dir(), folder_name)
            os.makedirs(target_dir, exist_ok=True)

            if not url:
                v_url = f"https://api.modrinth.com/v2/project/{urllib.parse.quote(project_id)}/version"
                r = session.get(v_url, headers=headers, timeout=15)
                if r.status_code != 200:
                    raise Exception(f"Failed to fetch versions: HTTP {r.status_code}")
                versions = r.json()
                if not versions:
                    raise Exception(f"No versions found for {project_type} '{project_id}'")
                best_ver = versions[0]
                if version_id:
                    for v in versions:
                        if v.get("id") == version_id:
                            best_ver = v
                            break
                files = best_ver.get("files", [])
                if not files:
                    raise Exception("No files in version")
                primary_file = next((f for f in files if f.get("primary", False)), files[0])
                url = primary_file["url"]
                filename = primary_file.get("filename") or f"{project_id}.zip"
                expected_sha1 = (primary_file.get("hashes") or {}).get("sha1")
            else:
                if not filename:
                    filename = os.path.basename(urllib.parse.urlsplit(url).path) or f"{project_id}.zip"

            dest_path = os.path.join(target_dir, filename)
            _download_file_atomic(
                url,
                dest_path,
                expected_sha1=expected_sha1,
                task_id=task_id,
                project_id=project_id,
                filename=filename,
                project_type=project_type,
            )

            emit_event("download_progress", {
                "task_id": task_id,
                "project_id": project_id,
                "filename": filename,
                "project_type": project_type,
                "status": "completed",
                "percentage": 100.0,
                "progress": 100.0,
                "speed_bps": 0,
                "speed": "0 B/s",
                "downloaded": 0,
                "downloaded_bytes": 0,
                "total": 0,
                "total_bytes": 0,
                "detail": f"Installed {filename} ✓",
            })
            return {
                "status": "success",
                "success": True,
                "task_id": task_id,
                "project_id": project_id,
                "project_type": project_type,
                "filename": filename,
                "target_path": dest_path,
            }

        else:
            raise ValueError(f"Unknown project_type: '{project_type}'")

    except Exception as exc:
        logger.exception("Error installing artifact %s: %s", project_id, exc)
        emit_event("download_progress", {
            "task_id": task_id,
            "project_id": project_id,
                "title": title,
            "filename": filename or "",
            "project_type": project_type,
            "status": "error",
            "percentage": 0.0,
            "progress": 0.0,
            "speed_bps": 0,
            "speed": "0 B/s",
            "downloaded": 0,
            "downloaded_bytes": 0,
            "total": 0,
            "total_bytes": 0,
            "detail": str(exc),
            "error": str(exc),
        })
        return {
            "status": "error",
            "success": False,
            "task_id": task_id,
            "msg": str(exc),
        }


# Skin & Cape Management Handlers

def ensure_valid_microsoft_token(profile: Dict[str, Any], force_refresh: bool = False) -> Optional[str]:
    # Validates Microsoft/Mojang token, decrypts refresh_token, refreshes if needed, and encrypts on save
    if not profile or profile.get("type") != "microsoft":
        raw_tok = profile.get("access_token") if profile else None
        return vault_decrypt(raw_tok) if raw_tok else None

    raw_access_token = profile.get("access_token", "")
    access_token = vault_decrypt(raw_access_token) if raw_access_token else ""
    raw_refresh_token = profile.get("refresh_token", "")
    refresh_token = vault_decrypt(raw_refresh_token) if raw_refresh_token else ""

    # Fast-path local validation if not force_refresh: decode JWT exp claim
    if access_token and not force_refresh:
        try:
            parts = access_token.split(".")
            if len(parts) >= 2:
                payload_b64 = parts[1]
                payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
                data = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8"))
                exp = data.get("exp")
                if exp and isinstance(exp, (int, float)) and exp - time.time() > 300:
                    return access_token
        except Exception:
            pass

        try:
            headers = {"Authorization": f"Bearer {access_token}", "User-Agent": "NLC-Minecraft-Launcher/1.0"}
            r = requests.get("https://api.minecraftservices.com/minecraft/profile", headers=headers, timeout=5)
            if r.status_code == 200:
                return access_token
        except Exception as e:
            logger.debug("Failed validating access_token against Mojang profile: %s", e)

    # Need refresh
    if not refresh_token:
        logger.warning("Microsoft account %s has no refresh_token to refresh session", profile.get("name", "unknown"))
        return access_token or None

    try:
        logger.info("Refreshing Microsoft session for %s...", profile.get("name", "unknown"))
        new_data = minecraft_launcher_lib.microsoft_account.complete_refresh(
            MSA_CLIENT_ID, None, MSA_REDIRECT_URI, refresh_token
        )
        if "error" not in new_data and "access_token" in new_data:
            fresh_token = new_data["access_token"]
            new_refresh = new_data.get("refresh_token")
            enc_access = vault_encrypt(fresh_token)
            enc_refresh = vault_encrypt(new_refresh) if new_refresh else ""

            profile["access_token"] = enc_access
            if new_refresh:
                profile["refresh_token"] = enc_refresh
            if new_data.get("id"):
                profile["uuid"] = new_data["id"]
            if new_data.get("name"):
                profile["name"] = new_data["name"]

            # Persist in config.json
            cm = get_config_manager()
            cfg = cm.load()
            profiles = cfg.get("profiles", [])
            p_uuid = profile.get("uuid")
            p_name = profile.get("name")
            for p in profiles:
                if (p_uuid and p.get("uuid") == p_uuid) or (p_name and p.get("name") == p_name):
                    p["access_token"] = enc_access
                    if new_refresh:
                        p["refresh_token"] = enc_refresh
                    break
            cm.save(cfg)
            emit_event("config_changed", {"key": "profiles", "value": profiles})
            logger.info("Successfully refreshed Microsoft session for %s", profile.get("name", "unknown"))
            return fresh_token
        else:
            logger.warning("Microsoft token refresh returned error: %s", new_data.get("error"))
    except Exception as e:
        logger.error("Exception refreshing Microsoft token for %s: %s", profile.get("name", "unknown"), e)

    return access_token or None


def handle_skin_get_current(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cm = get_config_manager()
    cfg = cm.load()
    profiles = cfg.get("profiles", [])
    active_idx = cfg.get("active_profile_index", cfg.get("current_profile_index", 0))
    p = profiles[active_idx] if 0 <= active_idx < len(profiles) else {}

    cape_p = p.get("cape_path", "")
    if not cape_p or not os.path.exists(cape_p):
        active_cape_id = p.get("active_cape_id", "")
        if active_cape_id:
            for c in p.get("owned_capes", []):
                if c.get("id") == active_cape_id:
                    cand = c.get("local_path", "")
                    if cand and os.path.exists(cand):
                        cape_p = cand
                        p["cape_path"] = cand
                        cm.save(cfg)
                        break

    return {
        "status": "success",
        "skin_path": p.get("skin_path", ""),
        "skin_model": p.get("skin_model", "classic"),
        "cape_path": cape_p,
        "active_cape_id": p.get("active_cape_id", "")
    }


def handle_skin_set_custom(payload: Dict[str, Any]) -> Dict[str, Any]:
    global _pending_mojang_skin_upload
    skin_src = payload.get("skin_path") or ""
    model = payload.get("model", "classic")
    account_id = payload.get("account_id") or payload.get("uuid")

    if not os.path.exists(skin_src):
        raise FileNotFoundError(f"Skin file not found: {skin_src}")

    try:
        with Image.open(skin_src) as img:
            w, h = img.size
            if (w, h) not in [(64, 64), (64, 32)]:
                raise ValueError(f"Invalid skin dimensions: {w}x{h}. Must be 64x64 or 64x32.")
    except Exception as exc:
        raise ValueError(f"Corrupt skin image: {exc}")

    skins_dir = Path(get_config_dir()) / "skins"
    skins_dir.mkdir(parents=True, exist_ok=True)

    src_path = Path(skin_src).resolve()
    if is_subpath(src_path, skins_dir):
        target_path = str(src_path)
    else:
        target_path, _ = deduplicate_and_reroute_skin(skin_src, skins_dir, copy_if_new=True)
    filename = Path(target_path).name

    cm = get_config_manager()
    cfg = cm.load()
    profiles = cfg.get("profiles", [])

    # Remember arm model for this skin
    cfg_models = cfg.setdefault("skin_arm_models", {})
    if payload.get("model"):
        cfg_models[filename] = model
        cfg_models[Path(skin_src).name] = model
    elif Path(skin_src).name in cfg_models:
        model = cfg_models[Path(skin_src).name]
        cfg_models[filename] = model

    active_idx = None
    if account_id:
        target_str = str(account_id)
        for idx, p in enumerate(profiles):
            if p.get("uuid") == target_str or p.get("id") == target_str:
                active_idx = idx
                break
    if active_idx is None:
        active_idx = cfg.get("active_profile_index", cfg.get("current_profile_index", 0))

    if 0 <= active_idx < len(profiles):
        p = profiles[active_idx]
        p["skin_path"] = target_path
        p["skin_model"] = model
        p_name = p.get("name", "player")
        p_uuid = p.get("uuid", str(active_idx))
        head_path = extract_player_head(target_path, p_name, p_uuid, force=True)
        p["head_path"] = head_path
        _async_sync_discord_avatar(p)
        cm.save(cfg)
        emit_event("config_changed", {"key": "profiles", "value": profiles})

        # If Microsoft account, stage skin upload to Mojang session servers
        # (deferred until user leaves Locker tab to avoid rate limiting)
        if p.get("type") == "microsoft":
            with _pending_mojang_skin_lock:
                _pending_mojang_skin_upload = {
                    "account_uuid": p.get("uuid"),
                    "account_name": p.get("name"),
                    "skin_path": target_path,
                    "model": model,
                }

    return {
        "status": "success",
        "skin_path": target_path,
        "model": model
    }


def handle_capes_list(payload: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    from nlc.net.capes import get_capes_cache_dir
    from nlc.core.skin_renderer import SkinRenderer3D

    cm = get_config_manager()
    cfg = cm.load()
    profiles = cfg.get("profiles", [])
    active_idx = cfg.get("active_profile_index", cfg.get("current_profile_index", 0))
    p = profiles[active_idx] if 0 <= active_idx < len(profiles) else {}

    # Capes are strictly exclusive to Microsoft accounts
    if p.get("type") != "microsoft":
        return []

    token = ensure_valid_microsoft_token(p) or vault_decrypt(p.get("access_token", ""))
    capes: List[Dict[str, Any]] = []

    if token and p.get("type") == "microsoft":
        try:
            fetched = fetch_account_capes(token)
            for c in fetched:
                alias = c.get("alias", "cape")
                c_path = download_and_cache_cape(c.get("url", ""), alias)
                c["local_path"] = c_path or ""
            p["owned_capes"] = fetched
            cm.save(cfg)
            capes = fetched
        except Exception as e:
            logger.warning("Error fetching capes: %s", e)

    if not capes:
        capes = p.get("owned_capes", [])

    # If no capes recorded in profile, discover from local cache directory
    if not capes:
        cache_dir = get_capes_cache_dir()
        if cache_dir.exists():
            for f in sorted(cache_dir.glob("*.png")):
                if f.name.endswith("_thumb.png"):
                    continue
                safe_name = f.stem
                capes.append({
                    "id": safe_name,
                    "alias": safe_name.replace("_", " ").title(),
                    "url": "",
                    "state": "INACTIVE",
                    "local_path": str(f.resolve())
                })
            if capes:
                p["owned_capes"] = capes
                cm.save(cfg)

    active_cape_id = p.get("active_cape_id", "")
    for c in capes:
        c_id = c.get("id", "")
        if active_cape_id and c_id == active_cape_id:
            c["state"] = "ACTIVE"
        local_p = c.get("local_path", "")
        if local_p and os.path.exists(local_p):
            thumb_path = Path(local_p).parent / f"{Path(local_p).stem}_thumb.png"
            if not thumb_path.exists() or thumb_path.stat().st_size == 0:
                try:
                    thumb_img = SkinRenderer3D.render_cape_thumbnail(local_p, width=128, height=160)
                    if thumb_img:
                        thumb_img.save(thumb_path)
                except Exception as ex:
                    logger.warning("Failed generating cape thumb for %s: %s", local_p, ex)
            if thumb_path.exists():
                c["thumb_path"] = str(thumb_path.resolve())
            else:
                c["thumb_path"] = local_p

    return capes


def handle_capes_select(payload: Dict[str, Any]) -> Dict[str, Any]:
    cape_id = payload.get("cape_id") if "cape_id" in payload else payload.get("id")
    cm = get_config_manager()
    cfg = cm.load()
    profiles = cfg.get("profiles", [])
    active_idx = cfg.get("active_profile_index", cfg.get("current_profile_index", 0))
    p = profiles[active_idx] if 0 <= active_idx < len(profiles) else {}

    if p.get("type") != "microsoft" and cape_id != "mojang-migrator":
        return {"status": "error", "msg": "Capes are exclusively available for Microsoft accounts."}

    token = vault_decrypt(p.get("access_token", ""))
    selected_path = ""

    if cape_id:
        capes = p.get("owned_capes", [])
        for c in capes:
            if c.get("id") == cape_id:
                c["state"] = "ACTIVE"
                selected_path = c.get("local_path", "")
            else:
                c["state"] = "INACTIVE"
        p["active_cape_id"] = cape_id
        p["cape_path"] = selected_path
        if p.get("type") == "microsoft":
            def _async_cape_equip(prof_dict, c_id):
                tok = ensure_valid_microsoft_token(prof_dict)
                if tok:
                    ok = set_active_mojang_cape(tok, c_id)
                    if not ok:
                        refreshed = ensure_valid_microsoft_token(prof_dict, force_refresh=True)
                        if refreshed:
                            set_active_mojang_cape(refreshed, c_id)

            threading.Thread(target=_async_cape_equip, args=(p, cape_id), daemon=True).start()
    else:
        p["active_cape_id"] = ""
        p["cape_path"] = ""
        if p.get("type") == "microsoft":
            def _async_cape_clear(prof_dict):
                tok = ensure_valid_microsoft_token(prof_dict)
                if tok:
                    ok = clear_active_mojang_cape(tok)
                    if not ok:
                        refreshed = ensure_valid_microsoft_token(prof_dict, force_refresh=True)
                        if refreshed:
                            clear_active_mojang_cape(refreshed)

            threading.Thread(target=_async_cape_clear, args=(p,), daemon=True).start()

    cm.save(cfg)
    emit_event("config_changed", {"key": "profiles", "value": profiles})

    return {
        "status": "success",
        "active_cape_id": p.get("active_cape_id", ""),
        "cape_path": selected_path
    }


def _ensure_default_steve_skin() -> str:
    skins_dir = Path(get_config_dir()) / "skins"
    skins_dir.mkdir(parents=True, exist_ok=True)
    steve_path = skins_dir / "default_steve.png"

    # Check for authentic bundled default_steve.png in repository assets
    repo_asset = Path(__file__).resolve().parent / "assets" / "default_steve.png"
    if repo_asset.exists():
        try:
            if not steve_path.exists() or os.path.getsize(steve_path) != os.path.getsize(repo_asset):
                shutil.copy2(repo_asset, steve_path)
            return str(steve_path)
        except Exception as e:
            logger.warning("Could not copy authentic default_steve asset: %s", e)

    if steve_path.exists():
        return str(steve_path)

    # Fallback standard 64x64 Steve skin
    from PIL import ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([8, 8, 15, 15], fill=(200, 153, 122, 255))
    draw.rectangle([8, 8, 15, 9], fill=(73, 51, 28, 255))
    draw.rectangle([8, 0, 15, 7], fill=(73, 51, 28, 255))
    draw.rectangle([24, 8, 31, 15], fill=(73, 51, 28, 255))
    draw.rectangle([0, 8, 7, 15], fill=(73, 51, 28, 255))
    draw.rectangle([16, 8, 23, 15], fill=(73, 51, 28, 255))
    draw.point((9, 12), fill=(255, 255, 255, 255))
    draw.point((10, 12), fill=(59, 75, 157, 255))
    draw.point((13, 12), fill=(59, 75, 157, 255))
    draw.point((14, 12), fill=(255, 255, 255, 255))
    draw.rectangle([11, 13, 12, 14], fill=(115, 66, 51, 255))
    draw.rectangle([20, 20, 27, 31], fill=(0, 145, 140, 255))
    draw.rectangle([32, 20, 39, 31], fill=(0, 145, 140, 255))
    draw.rectangle([16, 20, 19, 31], fill=(0, 145, 140, 255))
    draw.rectangle([28, 20, 31, 31], fill=(0, 145, 140, 255))
    draw.rectangle([44, 20, 47, 23], fill=(0, 145, 140, 255))
    draw.rectangle([44, 24, 47, 31], fill=(200, 153, 122, 255))
    draw.rectangle([36, 52, 39, 55], fill=(0, 145, 140, 255))
    draw.rectangle([36, 56, 39, 63], fill=(200, 153, 122, 255))
    draw.rectangle([4, 20, 7, 29], fill=(41, 51, 117, 255))
    draw.rectangle([4, 30, 7, 31], fill=(77, 77, 77, 255))
    draw.rectangle([20, 52, 23, 61], fill=(41, 51, 117, 255))
    draw.rectangle([20, 62, 23, 63], fill=(77, 77, 77, 255))
    img.save(steve_path)
    return str(steve_path)


def extract_player_head(skin_path: Optional[str] = None, username: str = "player", account_id: Optional[str] = None, force: bool = False) -> str:
    try:
        if not skin_path or not os.path.exists(skin_path):
            skin_path = _ensure_default_steve_skin()

        heads_dir = Path(get_config_dir()) / "heads"
        heads_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c for c in username if c.isalnum() or c in ("-", "_")) or "head"
        if account_id:
            safe_id = "".join(c for c in str(account_id) if c.isalnum() or c in ("-", "_"))
            out_path = heads_dir / f"{safe_name}_{safe_id}.png"
        else:
            out_path = heads_dir / f"{safe_name}.png"

        # Check if head is already up to date
        if not force and out_path.exists() and os.path.exists(skin_path) and os.path.getmtime(out_path) >= os.path.getmtime(skin_path):
            return str(out_path)

        with Image.open(skin_path) as img:
            img = img.convert("RGBA")
            # 1. Base head face (8, 8, 16, 16)
            head = img.crop((8, 8, 16, 16))

            # 2. Hat / helmet overlay (40, 8, 48, 16)
            if img.width >= 48 and img.height >= 16:
                hat = img.crop((40, 8, 48, 16))
                head.paste(hat, (0, 0), hat)

            # 3. Upscale to 32x32 using Nearest Neighbor for crisp pixel art
            head_32 = head.resize((32, 32), Image.NEAREST)
            head_32.save(out_path)
            return str(out_path)
    except Exception as e:
        logger.warning("Failed to extract player head for %s: %s", username, e)
        return ""


def handle_skin_model_set(payload: Dict[str, Any]) -> Dict[str, Any]:
    global _pending_mojang_skin_upload
    model = payload.get("model", "classic")
    cm = get_config_manager()
    cfg = cm.load()
    profiles = cfg.get("profiles", [])
    active_idx = cfg.get("active_profile_index", cfg.get("current_profile_index", 0))
    if 0 <= active_idx < len(profiles):
        profiles[active_idx]["skin_model"] = model
        skin_path = profiles[active_idx].get("skin_path", "")
        if skin_path:
            cfg_models = cfg.setdefault("skin_arm_models", {})
            cfg_models[Path(skin_path).name] = model
            cfg_models[skin_path] = model
        cm.save(cfg)
        emit_event("config_changed", {"key": "skin_model", "value": model})

        if profiles[active_idx].get("type") == "microsoft" and skin_path:
            with _pending_mojang_skin_lock:
                _pending_mojang_skin_upload = {
                    "account_uuid": profiles[active_idx].get("uuid"),
                    "account_name": profiles[active_idx].get("name"),
                    "skin_path": skin_path,
                    "model": model,
                }
    return {"status": "success", "model": model}


def handle_skin_flush_mojang(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    global _pending_mojang_skin_upload
    with _pending_mojang_skin_lock:
        pending = _pending_mojang_skin_upload
        _pending_mojang_skin_upload = None

    if not pending:
        return {"status": "noop", "msg": "No pending skin upload"}

    def _async_flush(target_pending):
        try:
            cm = get_config_manager()
            cfg = cm.load()
            profiles = cfg.get("profiles", [])
            target_uuid = target_pending.get("account_uuid")
            p = next((prof for prof in profiles if prof.get("uuid") == target_uuid), None)
            if not p:
                active_idx = cfg.get("active_profile_index", cfg.get("current_profile_index", 0))
                if 0 <= active_idx < len(profiles):
                    p = profiles[active_idx]

            if not p or p.get("type") != "microsoft":
                return

            s_path = target_pending.get("skin_path")
            s_model = target_pending.get("model", "classic")
            if not s_path or not os.path.exists(s_path):
                return

            tok = ensure_valid_microsoft_token(p)
            if tok:
                ok = upload_mojang_skin(tok, s_path, s_model)
                if not ok:
                    refreshed = ensure_valid_microsoft_token(p, force_refresh=True)
                    if refreshed:
                        upload_mojang_skin(refreshed, s_path, s_model)
        except Exception as exc:
            logger.error("Failed flushing skin to Mojang server: %s", exc)

    threading.Thread(target=_async_flush, args=(pending,), daemon=True).start()
    return {"status": "flushing", "skin_path": pending.get("skin_path")}


def handle_skin_thumbnail_get(payload: Dict[str, Any]) -> Dict[str, Any]:
    from nlc.core.skin_renderer import SkinRenderer3D
    skin_path = payload.get("skin_path") or ""
    model = payload.get("model", "classic")
    if not skin_path or not os.path.exists(skin_path):
        skin_path = _ensure_default_steve_skin()

    thumbs_dir = Path(get_config_dir()) / "thumbnails"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    skin_stem = Path(skin_path).stem
    thumb_path = thumbs_dir / f"thumb_{skin_stem}_{model}.png"

    if not thumb_path.exists() or os.path.getmtime(thumb_path) < os.path.getmtime(skin_path):
        frame = SkinRenderer3D.render_frame(
            skin_path=skin_path,
            yaw_deg=30.0,
            pitch_deg=10.0,
            walk_phase=0.8,
            width=128,
            height=160,
            model=model,
        )
        if frame:
            frame.save(thumb_path, format="PNG")

    return {
        "status": "success",
        "thumbnail_path": str(thumb_path) if thumb_path.exists() else ""
    }


def handle_skin_presets_list(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    skins_dir = Path(get_config_dir()) / "skins"
    skins_dir.mkdir(parents=True, exist_ok=True)

    # Seed default skins from bundled app skins if user folder has <= 1 png
    existing_pngs = list(skins_dir.glob("*.png"))
    if len(existing_pngs) <= 1:
        for cand_dir in [
            Path(sys.executable).parent / "skins",
            Path(__file__).resolve().parent.parent.parent / "skins",
            Path.cwd() / "skins",
        ]:
            if cand_dir.is_dir():
                for s_f in cand_dir.glob("*.png"):
                    dst_s = skins_dir / s_f.name
                    if not dst_s.exists():
                        try:
                            shutil.copy2(s_f, dst_s)
                        except Exception:
                            pass
                break

    cm = get_config_manager()
    cfg = cm.load()
    reroutes, removed = cleanup_duplicate_skins(skins_dir, cfg)
    if removed > 0 or reroutes:
        cm.save(cfg)

    profiles = cfg.get("profiles", [])
    active_idx = cfg.get("active_profile_index", cfg.get("current_profile_index", 0))
    active_skin = profiles[active_idx].get("skin_path") if 0 <= active_idx < len(profiles) else None
    arm_models = cfg.get("skin_arm_models", {})

    presets = []
    for f in sorted(skins_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True):
        fn = f.name
        stem = f.stem
        f_str = str(f)
        model = arm_models.get(fn) or arm_models.get(f_str) or "classic"
        model = "slim" if str(model).lower() == "slim" else "classic"

        thumb_res = handle_skin_thumbnail_get({"skin_path": f_str, "model": model})
        thumb_path = thumb_res.get("thumbnail_path", "")

        is_eq = False
        if active_skin:
            try:
                is_eq = os.path.samefile(f_str, active_skin)
            except Exception:
                is_eq = (f_str == active_skin)

        presets.append({
            "id": f_str,
            "name": stem,
            "path": f_str,
            "model": model,
            "thumb_path": thumb_path,
            "is_equipped": is_eq
        })

    return {"status": "success", "presets": presets}


def handle_skin_steal_preview(payload: Dict[str, Any]) -> Dict[str, Any]:
    username = (payload.get("username") or "").strip()
    if not username:
        raise ValueError("Username cannot be empty")

    import urllib.request
    import base64
    import json
    import io
    from nlc.core.skin_renderer import SkinRenderer3D

    preview_dir = Path(get_config_dir()) / "cache" / "steal_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    temp_skin_path = preview_dir / f"{username}_preview.png"

    model = "classic"
    skin_bytes = None

    try:
        mojang_url = f"https://api.mojang.com/users/profiles/minecraft/{username}"
        req = urllib.request.Request(mojang_url, headers={"User-Agent": "NLC-Launcher"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            uuid_str = data.get("id")

        if uuid_str:
            session_url = f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid_str}"
            req_s = urllib.request.Request(session_url, headers={"User-Agent": "NLC-Launcher"})
            with urllib.request.urlopen(req_s, timeout=5) as resp_s:
                data_s = json.loads(resp_s.read().decode())
                for prop in data_s.get("properties", []):
                    if prop.get("name") == "textures":
                        tex_json = json.loads(base64.b64decode(prop.get("value", "")).decode())
                        skin_info = (tex_json.get("textures") or {}).get("SKIN") or {}
                        skin_url = skin_info.get("url")
                        meta = skin_info.get("metadata") or {}
                        if meta.get("model") == "slim":
                            model = "slim"
                        if skin_url:
                            req_dl = urllib.request.Request(skin_url, headers={"User-Agent": "NLC-Launcher"})
                            with urllib.request.urlopen(req_dl, timeout=5) as resp_dl:
                                skin_bytes = resp_dl.read()
                        break
    except Exception as exc:
        logger.warning("Mojang API lookup failed for %s: %s, falling back to minotar", username, exc)

    if not skin_bytes:
        try:
            minotar_url = f"https://minotar.net/skin/{username}"
            req_m = urllib.request.Request(minotar_url, headers={"User-Agent": "NLC-Launcher"})
            with urllib.request.urlopen(req_m, timeout=5) as resp_m:
                skin_bytes = resp_m.read()
        except Exception as exc2:
            logger.error("Minotar fallback failed for %s: %s", username, exc2)
            raise RuntimeError(f"Could not find skin for player '{username}'")

    if not skin_bytes:
        raise RuntimeError(f"Could not find skin for player '{username}'")

    with open(temp_skin_path, "wb") as f_out:
        f_out.write(skin_bytes)

    # Render 3D preview frame
    frame = SkinRenderer3D.render_frame(
        skin_path=str(temp_skin_path),
        yaw_deg=25.0,
        pitch_deg=5.0,
        walk_phase=0.0,
        width=240,
        height=280,
        model=model,
    )
    if frame is None:
        raise RuntimeError("Failed to render preview frame for skin")

    buf = io.BytesIO()
    frame.save(buf, format="PNG")
    preview_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    return {
        "status": "success",
        "username": username,
        "model": model,
        "preview_base64": preview_b64,
        "temp_skin_path": str(temp_skin_path),
    }


def handle_skin_steal(payload: Dict[str, Any]) -> Dict[str, Any]:
    username = (payload.get("username") or "").strip()
    if not username:
        raise ValueError("Username cannot be empty")

    import urllib.request
    import base64
    import json
    import shutil

    skins_dir = Path(get_config_dir()) / "skins"
    skins_dir.mkdir(parents=True, exist_ok=True)

    out_p = skins_dir / f"{username}.png"
    temp_skin_path = payload.get("temp_skin_path")
    model = payload.get("model") or "classic"

    if temp_skin_path and os.path.exists(temp_skin_path):
        shutil.copy2(temp_skin_path, out_p)
        target_skin_path = str(out_p)
    else:
        target_skin_path = None
        try:
            mojang_url = f"https://api.mojang.com/users/profiles/minecraft/{username}"
            req = urllib.request.Request(mojang_url, headers={"User-Agent": "NLC-Launcher"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                uuid_str = data.get("id")

            if uuid_str:
                session_url = f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid_str}"
                req_s = urllib.request.Request(session_url, headers={"User-Agent": "NLC-Launcher"})
                with urllib.request.urlopen(req_s, timeout=5) as resp_s:
                    data_s = json.loads(resp_s.read().decode())
                    for prop in data_s.get("properties", []):
                        if prop.get("name") == "textures":
                            tex_json = json.loads(base64.b64decode(prop.get("value", "")).decode())
                            skin_info = (tex_json.get("textures") or {}).get("SKIN") or {}
                            skin_url = skin_info.get("url")
                            meta = skin_info.get("metadata") or {}
                            if meta.get("model") == "slim":
                                model = "slim"
                            if skin_url:
                                req_dl = urllib.request.Request(skin_url, headers={"User-Agent": "NLC-Launcher"})
                                with urllib.request.urlopen(req_dl, timeout=5) as resp_dl:
                                    with open(out_p, "wb") as f_out:
                                        f_out.write(resp_dl.read())
                                target_skin_path = str(out_p)
                            break
        except Exception as exc:
            logger.warning("Mojang API lookup failed for %s: %s, falling back to minotar", username, exc)

        if not target_skin_path:
            try:
                minotar_url = f"https://minotar.net/skin/{username}"
                req_m = urllib.request.Request(minotar_url, headers={"User-Agent": "NLC-Launcher"})
                with urllib.request.urlopen(req_m, timeout=5) as resp_m:
                    with open(out_p, "wb") as f_out:
                        f_out.write(resp_m.read())
                target_skin_path = str(out_p)
            except Exception as exc2:
                logger.error("Minotar fallback failed for %s: %s", username, exc2)
                raise RuntimeError(f"Could not fetch skin for '{username}': {exc2}")

    target_skin_path, _ = deduplicate_and_reroute_skin(target_skin_path, skins_dir, copy_if_new=False)

    handle_skin_set_custom({
        "skin_path": target_skin_path,
        "model": model,
    })

    return {
        "status": "success",
        "username": username,
        "skin_path": target_skin_path,
        "model": model,
    }


OFFICIAL_WALLPAPERS = [
    {"filename": "13uv5py3dw9f1.png", "name": "Alpine Sunrise", "size_mb": 2.4},
    {"filename": "8w0iispqcw9f1.png", "name": "Deep Forest Mist", "size_mb": 2.8},
    {"filename": "gqv4762zcw9f1.png", "name": "Lush Valley Sunset", "size_mb": 3.3},
    {"filename": "Island.png", "name": "Floating Island", "size_mb": 1.8},
    {"filename": "background.png", "name": "Classic Slate Vista", "size_mb": 1.7},
    {"filename": "River.png", "name": "Canyon River", "size_mb": 2.4},
    {"filename": "80uo8d4vcw9f1.png", "name": "Emerald Canopy", "size_mb": 4.0},
    {"filename": "9as74p5rcw9f1.png", "name": "Mountain Peak", "size_mb": 3.3},
    {"filename": "image1.png", "name": "Highlands Panorama", "size_mb": 6.4},
    {"filename": "p5hsf52zcw9f1.png", "name": "Autumn Highlands", "size_mb": 3.0},
    {"filename": "pddw573scw9f1.png", "name": "Twilight Horizon", "size_mb": 4.2},
    {"filename": "q66ll6p2dw9f1.png", "name": "Misty Lake", "size_mb": 2.4},
    {"filename": "xrkgdnt4dw9f1.png", "name": "Nordic Fjord", "size_mb": 3.5},
    {"filename": "xse1m641dw9f1.png", "name": "Verdant Hills", "size_mb": 3.2},
    {"filename": "y9dkt48qcw9f1.png", "name": "Sunlit Clearing", "size_mb": 2.4},
]

DEFAULT_LOCAL_WALLPAPERS = {
    "13uv5py3dw9f1.png",
    "8w0iispqcw9f1.png",
    "gqv4762zcw9f1.png",
    "Island.png",
}


def get_bundled_wallpapers_dir() -> Path:
    candidates = [
        Path(get_launcher_dir()) / "wallpapers",
        Path(__file__).resolve().parent.parent.parent / "wallpapers",
        Path(__file__).resolve().parent / "wallpapers",
    ]
    for cand in candidates:
        if cand.is_dir():
            return cand
    return Path(get_launcher_dir()) / "wallpapers"


_get_bundled_wallpapers_dir = get_bundled_wallpapers_dir


def handle_wallpapers_list(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from PIL import Image

    cm = get_config_manager()
    cfg = cm.load()
    current_wp = cfg.get("current_wallpaper") or ""

    # Resolved via get_bundled_wallpapers_dir() checking Path(get_launcher_dir()) / "wallpapers"
    repo_wp_dir = get_bundled_wallpapers_dir()
    user_wp_dir = Path(get_config_dir()) / "wallpapers"
    user_wp_dir.mkdir(parents=True, exist_ok=True)

    thumbs_dir = Path(get_config_dir()) / "wallpapers_thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    repo_thumbs_dir = repo_wp_dir / "thumbnails"

    items = []
    seen = set()

    # 1. Process Official Wallpapers Catalog
    for entry in OFFICIAL_WALLPAPERS:
        fname = entry["filename"]
        stem = Path(fname).stem
        seen.add(fname.lower())

        repo_full = repo_wp_dir / fname
        user_full = user_wp_dir / fname

        is_dl = False
        resolved_full = ""
        if fname in DEFAULT_LOCAL_WALLPAPERS:
            if repo_full.exists():
                is_dl = True
                resolved_full = str(repo_full)
            elif user_full.exists():
                is_dl = True
                resolved_full = str(user_full)
        else:
            if user_full.exists():
                is_dl = True
                resolved_full = str(user_full)

        is_eq = bool(resolved_full and ((resolved_full == current_wp) or (current_wp and Path(current_wp).name.lower() == fname.lower())))

        thumb_file = repo_thumbs_dir / f"thumb_{stem}.png"
        if not thumb_file.exists():
            thumb_file = thumbs_dir / f"thumb_{stem}.png"
            if not thumb_file.exists() and resolved_full:
                try:
                    with Image.open(resolved_full) as img:
                        img_thumb = img.convert("RGB")
                        img_thumb.thumbnail((240, 135))
                        img_thumb.save(thumb_file, format="PNG")
                except Exception as e:
                    logger.warning("Could not generate wallpaper thumb: %s", e)

        items.append({
            "id": fname,
            "filename": fname,
            "name": entry["name"],
            "path": resolved_full,
            "thumb_path": str(thumb_file) if thumb_file.exists() else resolved_full,
            "is_equipped": is_eq,
            "is_downloaded": is_dl,
            "size_text": f"{entry['size_mb']:.1f} MB",
        })

    # 2. Process Custom Uploaded Wallpapers from user_wp_dir
    if user_wp_dir.exists():
        for f in sorted(user_wp_dir.glob("*.png")):
            if f.name.lower() not in seen:
                seen.add(f.name.lower())
                p_str = str(f)
                is_eq = (p_str == current_wp) or (current_wp and Path(current_wp).name.lower() == f.name.lower())
                thumb_file = thumbs_dir / f"thumb_{f.stem}.png"
                if not thumb_file.exists() or (os.path.getmtime(f) > os.path.getmtime(thumb_file)):
                    try:
                        with Image.open(f) as img:
                            img_thumb = img.convert("RGB")
                            img_thumb.thumbnail((240, 135))
                            img_thumb.save(thumb_file, format="PNG")
                    except Exception as e:
                        logger.warning("Could not generate wallpaper thumb for %s: %s", f, e)

                items.append({
                    "id": f.name,
                    "filename": f.name,
                    "name": f.stem.replace("_", " ").title(),
                    "path": p_str,
                    "thumb_path": str(thumb_file) if thumb_file.exists() else p_str,
                    "is_equipped": is_eq,
                    "is_downloaded": True,
                    "size_text": f"{f.stat().st_size / (1024 * 1024):.1f} MB",
                })

    return {
        "status": "success",
        "current_wallpaper": current_wp,
        "wallpapers": items
    }


def handle_wallpapers_download(payload: Dict[str, Any]) -> Dict[str, Any]:
    filename = str(payload.get("filename") or payload.get("id") or "").strip()
    if not filename:
        raise ValueError("Missing wallpaper filename")

    filename = Path(filename).name
    user_wp_dir = Path(get_config_dir()) / "wallpapers"
    user_wp_dir.mkdir(parents=True, exist_ok=True)
    dst_path = user_wp_dir / filename

    if dst_path.exists() and dst_path.stat().st_size > 1000:
        return {
            "status": "success",
            "filename": filename,
            "path": str(dst_path),
            "is_downloaded": True
        }

    urls = [
        f"https://raw.githubusercontent.com/Amne-Dev/NLC/main/wallpapers/{filename}",
        f"https://raw.githubusercontent.com/Amne-Dev/NLC/c444a9df42ec658fa7a8125e02d1b16446c0b585/wallpapers/{filename}",
    ]

    downloaded = False
    repo_wp_dir = get_bundled_wallpapers_dir()
    repo_full = repo_wp_dir / filename
    if repo_full.exists() and not dst_path.exists():
        try:
            import shutil
            shutil.copy2(repo_full, dst_path)
            downloaded = True
        except Exception as e:
            logger.debug("Local wallpaper copy failed, attempting network: %s", e)

    if not downloaded:
        session = get_session()
        headers = {"User-Agent": "AmneDev/NewLauncher/1.8.2"}

    for url in urls:
        try:
            r = session.get(url, headers=headers, timeout=30)
            if r.status_code == 200 and len(r.content) > 1000:
                tmp_path = dst_path.with_suffix(".tmp")
                with open(tmp_path, "wb") as f:
                    f.write(r.content)
                os.replace(tmp_path, dst_path)
                downloaded = True
                break
        except Exception as e:
            logger.warning("Error downloading wallpaper from %s: %s", url, e)

    if not downloaded:
        return {"status": "error", "error": f"Failed to download wallpaper {filename} from repository"}

    thumbs_dir = Path(get_config_dir()) / "wallpapers_thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    thumb_file = thumbs_dir / f"thumb_{dst_path.stem}.png"
    if not thumb_file.exists():
        try:
            from PIL import Image
            with Image.open(dst_path) as img:
                img_thumb = img.convert("RGB")
                img_thumb.thumbnail((240, 135))
                img_thumb.save(thumb_file, format="PNG")
        except Exception as e:
            logger.warning("Could not create thumb for downloaded wallpaper: %s", e)

    emit_event("wallpaper_downloaded", {"filename": filename, "path": str(dst_path)})
    return {
        "status": "success",
        "filename": filename,
        "path": str(dst_path),
        "thumb_path": str(thumb_file) if thumb_file.exists() else str(dst_path),
        "is_downloaded": True
    }


def handle_wallpapers_set(payload: Dict[str, Any]) -> Dict[str, Any]:
    wp_path = payload.get("path") or ""
    cm = get_config_manager()
    cfg = cm.load()
    cfg["current_wallpaper"] = wp_path
    cm.save(cfg)
    emit_event("config_changed", {"key": "current_wallpaper", "value": wp_path})
    return {"status": "success", "current_wallpaper": wp_path}


def handle_wallpapers_upload(payload: Dict[str, Any]) -> Dict[str, Any]:
    src_path = payload.get("path") or ""
    if not os.path.exists(src_path):
        raise FileNotFoundError(f"Wallpaper not found: {src_path}")
    user_wp_dir = Path(get_config_dir()) / "wallpapers"
    user_wp_dir.mkdir(parents=True, exist_ok=True)
    dst_name = f"wp_{int(time.time())}_{Path(src_path).name}"
    dst_path = str(user_wp_dir / dst_name)
    shutil.copy2(src_path, dst_path)

    cm = get_config_manager()
    cfg = cm.load()
    cfg["current_wallpaper"] = dst_path
    cm.save(cfg)
    emit_event("config_changed", {"key": "current_wallpaper", "value": dst_path})
    return {"status": "success", "path": dst_path}


def handle_wallpapers_delete(payload: Dict[str, Any]) -> Dict[str, Any]:
    wp_path = payload.get("path") or ""
    repo_wp_dir = get_bundled_wallpapers_dir()
    if wp_path and os.path.exists(wp_path):
        try:
            # Protect bundled repository wallpapers from deletion
            if Path(wp_path).resolve().is_relative_to(repo_wp_dir.resolve()):
                logger.info("Ignoring delete request for built-in wallpaper: %s", wp_path)
                return {"status": "error", "error": "Cannot delete built-in wallpaper"}
            os.remove(wp_path)
            fname = Path(wp_path).name
            thumb = Path(get_config_dir()) / "wallpapers_thumbs" / f"thumb_{fname}"
            if thumb.exists():
                thumb.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Error deleting wallpaper %s: %s", wp_path, e)
    cm = get_config_manager()
    cfg = cm.load()
    if cfg.get("current_wallpaper") == wp_path:
        cfg["current_wallpaper"] = ""
        cm.save(cfg)
        emit_event("config_changed", {"key": "current_wallpaper", "value": ""})
    return {"status": "success", "deleted": wp_path}


def handle_wallpapers_open_folder(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user_wp_dir = Path(get_config_dir()) / "wallpapers"
    user_wp_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(user_wp_dir))
    return {"status": "success", "path": str(user_wp_dir)}


def handle_skin_render_frame(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from nlc.core.skin_renderer import SkinRenderer3D

    payload = payload or {}
    skin_path = payload.get("skin_path")
    cape_path = payload.get("cape_path")
    model = payload.get("model") or payload.get("skin_model")

    cm = get_config_manager()
    cfg = cm.load()
    profiles = cfg.get("profiles", [])
    active_idx = cfg.get("active_profile_index", cfg.get("current_profile_index", 0))
    p = profiles[active_idx] if 0 <= active_idx < len(profiles) else {}

    if not skin_path:
        skin_path = p.get("skin_path")

    if not cape_path:
        cape_path = p.get("cape_path")
        if not cape_path or not os.path.exists(cape_path):
            active_cape_id = p.get("active_cape_id", "")
            if active_cape_id:
                for c in p.get("owned_capes", []):
                    if c.get("id") == active_cape_id:
                        cand = c.get("local_path", "")
                        if cand and os.path.exists(cand):
                            cape_path = cand
                            break

    if not model:
        if skin_path:
            cfg_models = cfg.get("skin_arm_models", {})
            model = cfg_models.get(Path(skin_path).name) or cfg_models.get(skin_path)
        if not model:
            model = p.get("skin_model", "classic")

    model = "slim" if str(model).lower() == "slim" else "classic"

    if not skin_path or not os.path.exists(skin_path):
        skin_path = _ensure_default_steve_skin()

    yaw_deg = float(payload.get("yaw_deg", payload.get("yaw", 30.0)))
    pitch_deg = float(payload.get("pitch_deg", payload.get("pitch", 10.0)))
    walk_phase = float(payload.get("walk_phase", 0.0))
    width = int(payload.get("width", 320))
    height = int(payload.get("height", 380))
    scale = payload.get("scale")
    if scale is not None:
        scale = float(scale)

    frame = SkinRenderer3D.render_frame(
        skin_path=skin_path,
        cape_path=cape_path if cape_path and os.path.exists(cape_path) else None,
        yaw_deg=yaw_deg,
        pitch_deg=pitch_deg,
        walk_phase=walk_phase,
        width=width,
        height=height,
        model=model,
        scale=scale,
    )
    if frame is None:
        return {"status": "error", "msg": "Failed to render skin frame"}

    buf = io.BytesIO()
    frame.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    return {
        "status": "success",
        "image_base64": b64,
        "width": width,
        "height": height,
        "yaw_deg": yaw_deg,
        "pitch_deg": pitch_deg,
        "model": model,
    }


def _extract_base_mc_version(version: str) -> str:
    matches = re.findall(r"(\d+\.\d+(?:\.\d+)?)", version)
    for m in reversed(matches):
        if m.startswith("1.") or m.startswith("2."):
            return m
    return matches[-1] if matches else version


def are_version_libraries_complete(version_id: str, mc_dir: str) -> bool:
    try:
        ver_dir = os.path.join(mc_dir, "versions", version_id)
        ver_json = os.path.join(ver_dir, f"{version_id}.json")
        if not os.path.isfile(ver_json):
            return False
        with open(ver_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        jar_name = data.get("jar", version_id)
        client_jar = os.path.join(mc_dir, "versions", jar_name, f"{jar_name}.jar")
        if not os.path.isfile(client_jar):
            return False
        libstr = minecraft_launcher_lib.command.get_libraries(data, mc_dir)
        sep = os.pathsep
        for lib in libstr.split(sep):
            lib = lib.strip()
            if lib and not os.path.isfile(lib) and not lib.endswith("jinput-platform-2.0.5.jar"):
                logger.info("Missing library detected for %s: %s", version_id, lib)
                return False
        return True
    except Exception as e:
        logger.debug("are_version_libraries_complete check failed for %s: %s", version_id, e)
        return False


def _deduce_jvm_runtime_name(version: str) -> str:
    mc_ver = _extract_base_mc_version(version)

    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", mc_ver)
    if not m:
        return "java-runtime-gamma"
    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3) or 0)
    if (major, minor) >= (1, 21) or (major, minor, patch) >= (1, 20, 5):
        return "java-runtime-delta"  # Java 21+
    elif (major, minor) >= (1, 18):
        return "java-runtime-gamma"  # Java 17+
    elif (major, minor) >= (1, 17):
        return "java-runtime-alpha"  # Java 16
    else:
        return "jre-legacy"          # Java 8


def ensure_java_runtime(version: str, mc_dir: str, launch_callbacks: Optional[Dict[str, Any]] = None) -> str:
    import minecraft_launcher_lib.runtime as jvm_rt

    matches = re.findall(r"(\d+\.\d+(?:\.\d+)?)", version)
    base_version = ""
    for m in reversed(matches):
        if m.startswith("1.") or m.startswith("2."):
            base_version = m
            break
    if not base_version:
        base_version = matches[-1] if matches else version

    runtime_name = None
    try:
        info = jvm_rt.get_version_runtime_information(base_version, mc_dir)
        if isinstance(info, dict) and "name" in info:
            runtime_name = info["name"]
    except Exception as e:
        logger.debug("get_version_runtime_information failed for %s: %s", base_version, e)

    if not runtime_name:
        runtime_name = _deduce_jvm_runtime_name(base_version)

    # 1. Check if already installed in .minecraft/runtime
    try:
        exec_path = jvm_rt.get_executable_path(runtime_name, mc_dir)
        if exec_path and os.path.isfile(exec_path):
            return exec_path
    except Exception as e:
        logger.debug("get_executable_path check failed: %s", e)

    # 2. Automatically install missing runtime via Mojang
    try:
        logger.info("Java runtime '%s' is missing. Initiating automatic download into %s...", runtime_name, mc_dir)
        if launch_callbacks and "setStatus" in launch_callbacks:
            try:
                launch_callbacks["setStatus"](f"Downloading required Java runtime ({runtime_name})...")
            except Exception:
                pass
        jvm_rt.install_jvm_runtime(runtime_name, mc_dir, callback=launch_callbacks)
        exec_path = jvm_rt.get_executable_path(runtime_name, mc_dir)
        if exec_path and os.path.isfile(exec_path):
            logger.info("Java runtime '%s' installed successfully at %s", runtime_name, exec_path)
            return exec_path
    except Exception as e:
        logger.warning("Failed to automatically install JVM runtime '%s': %s", runtime_name, e)

    # 3. Fallback: Search .minecraft/runtime for ANY working java executable
    mc_rt_dir = Path(mc_dir) / "runtime"
    if mc_rt_dir.exists():
        for cand in mc_rt_dir.glob("**/java.exe" if sys.platform == "win32" else "**/java"):
            if cand.is_file():
                return str(cand)

    # 4. Fallback: System PATH
    which_java = shutil.which("java")
    if which_java:
        return which_java

    # 5. Fallback: Standard installation directories (Windows & Linux)
    if sys.platform == "win32":
        standard_dirs = [
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Eclipse Adoptium",
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Java",
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Microsoft",
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "BellSoft",
            Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")) / "Java",
        ]
        for base in standard_dirs:
            if base.exists():
                for cand in base.glob("**/bin/javaw.exe"):
                    if cand.is_file():
                        return str(cand)
                for cand in base.glob("**/bin/java.exe"):
                    if cand.is_file():
                        return str(cand)
    else:
        linux_dirs = [
            Path("/usr/lib/jvm"),
            Path("/usr/lib64/jvm"),
            Path("/usr/local/jvm"),
            Path(os.path.expanduser("~/.sdkman/candidates/java")),
            Path(os.path.expanduser("~/.jdks")),
        ]
        for base in linux_dirs:
            if base.exists():
                for cand in base.glob("**/bin/java"):
                    if cand.is_file() and os.access(cand, os.X_OK):
                        return str(cand)

    return "java"


# Launch Engine Handlers
def handle_launch_game(payload: Dict[str, Any]) -> Dict[str, Any]:
    patch_minecraft_launcher_launch_helpers()

    try:
        handle_skin_flush_mojang({})
    except Exception as e:
        logger.warning("Error auto-flushing skin before launch: %s", e)

    cm = get_config_manager()
    cfg = cm.load()
    inst_id = payload.get("installation_id") or payload.get("instance_id") or payload.get("profile") or cfg.get("active_installation_id")
    clean_id = inst_id.replace("inst-", "") if (inst_id and inst_id.startswith("inst-")) else inst_id

    inst = next((i for i in cfg.get("installations", []) if i.get("id") in (inst_id, clean_id, f"inst-{inst_id}")), None)
    if not inst:
        mp_file = Path(get_config_dir()) / "modpacks.json"
        if mp_file.exists():
            try:
                with open(mp_file, "r", encoding="utf-8") as f:
                    modpacks = json.load(f)
                if isinstance(modpacks, list):
                    for mp in modpacks:
                        if mp.get("id") in (inst_id, clean_id) or mp.get("linked_installation_id") in (inst_id, clean_id):
                            inst = {
                                "id": mp.get("linked_installation_id") or f"inst-{mp['id']}",
                                "name": mp.get("name", "Modpack"),
                                "version": mp.get("mc_version") or mp.get("version") or "1.21.1",
                                "loader": mp.get("loader") or "Fabric",
                                "game_directory": str(Path(get_config_dir()) / "modpacks" / mp["id"])
                            }
                            break
            except Exception:
                pass
    if not inst:
        insts = cfg.get("installations", [])
        inst = insts[0] if insts else {"id": "default", "version": "latest-release", "loader": "Vanilla"}

    version = payload.get("version") or inst.get("version", "latest-release")
    loader = payload.get("loader") or inst.get("loader", "Vanilla")
    fu_val = payload.get("force_update", False)
    force_update = (fu_val in (True, 1)) if not isinstance(fu_val, str) else fu_val.strip().lower() in ("true", "1", "yes")
    is_mock = bool(payload.get("mock", False) or version == "mock" or payload.get("is_mock", False))

    active_idx = cfg.get("active_profile_index", cfg.get("current_profile_index", 0))
    profiles = cfg.get("profiles", [])
    if not profiles:
        raise ValueError("No profile or account configured. Please create an account before launching.")
    profile = profiles[active_idx] if 0 <= active_idx < len(profiles) else profiles[0]

    launch_id = str(uuid.uuid4())

    try:
        p_name = profile.get("name", "Steve")
        p_uuid = profile.get("uuid")
        p_type = profile.get("type", "microsoft")
        p_avatar = profile.get("discord_avatar_url")
        logger.info("[Discord RPC] Setting launching: ver=%s, loader=%s, player=%s (uuid=%s)", version, loader, p_name, p_uuid)
        _discord_rpc_manager.set_player(p_name, p_uuid, p_type, p_avatar)
        _async_sync_discord_avatar(profile)
        _discord_rpc_manager.set_launching(version=version, loader=loader, installation_name=inst.get("name"))
    except Exception as e:
        logger.warning("Error setting Discord launching state: %s", e)

    cancel_event = threading.Event()
    with _process_lock:
        _running_processes[launch_id] = {
            "proc": None,
            "cancel_event": cancel_event,
            "skin_server": None,
            "installation_id": inst_id,
            "start_time": time.time(),
        }

    def _execute_launch_sequence():
        # Brief pause to guarantee correlated response frame is flushed to stdout before push events
        time.sleep(0.02)
        local_skin_server = None
        try:
            if cancel_event.is_set():
                raise RuntimeError("Launch cancelled by user")

            emit_event("launch_state_changed", {
                "state": "verifying",
                "launch_id": launch_id,
                "progress": 0.0,
                "message": f"Resolving Minecraft {version} ({loader})..."
            })

            if force_update:
                logger.info("Force update enabled: Clean reinstalling version %s and dependencies", version)
                from nlc.core.versions import _VERSION_CACHE, _CACHE_LOCK
                with _CACHE_LOCK:
                    _VERSION_CACHE.clear()

                modpack_cache_dir = Path(get_config_dir()) / "cache" / "modpack_mods"
                if modpack_cache_dir.is_dir():
                    shutil.rmtree(modpack_cache_dir, ignore_errors=True)

            if is_mock:
                time.sleep(0.05)
                if cancel_event.is_set():
                    raise RuntimeError("Launch cancelled by user")
                emit_event("launch_state_changed", {
                    "state": "downloading",
                    "launch_id": launch_id,
                    "progress": 50.0,
                    "message": "Downloading assets..."
                })
                time.sleep(0.05)
                if cancel_event.is_set():
                    raise RuntimeError("Launch cancelled by user")
                emit_event("launch_state_changed", {
                    "state": "running",
                    "launch_id": launch_id,
                    "pid": 99999,
                    "instance_id": inst_id,
                    "instance_name": inst.get("name") or version,
                    "version": version,
                    "loader": loader,
                    "message": "Game process running (mock)"
                })
                emit_event("game_log", {"launch_id": launch_id, "line": "[Mock] Minecraft started."})
                time.sleep(0.1)
                emit_event("launch_state_changed", {
                    "state": "stopped",
                    "launch_id": launch_id,
                    "exit_code": 0,
                    "session_seconds": 1,
                    "message": "Game session ended"
                })
                emit_event("game_session_ended", {
                    "launch_id": launch_id,
                    "installation_id": inst_id,
                    "session_seconds": 1,
                    "exit_code": 0
                })
                return

            mc_dir = get_minecraft_dir()

            curr_prog = [0]
            max_prog = [100]

            def _set_status(msg: str):
                if cancel_event.is_set():
                    raise RuntimeError("Launch cancelled by user")
                pct = float(curr_prog[0]) / float(max_prog[0]) * 100.0 if max_prog[0] > 0 else 0.0
                emit_event("launch_state_changed", {
                    "state": "downloading",
                    "launch_id": launch_id,
                    "progress": pct,
                    "message": msg or "Downloading assets..."
                })

            def _set_progress(val: int):
                if cancel_event.is_set():
                    raise RuntimeError("Launch cancelled by user")
                curr_prog[0] = val
                pct = float(curr_prog[0]) / float(max_prog[0]) * 100.0 if max_prog[0] > 0 else 0.0
                emit_event("launch_state_changed", {
                    "state": "downloading",
                    "launch_id": launch_id,
                    "progress": pct,
                    "message": f"Downloading assets ({curr_prog[0]}/{max_prog[0]})..."
                })

            def _set_max(val: int):
                max_prog[0] = max(1, val)

            launch_callbacks = {
                "setStatus": _set_status,
                "setProgress": _set_progress,
                "setMax": _set_max,
            }

            actual_version = version
            if version == "latest-release":
                try:
                    actual_version = minecraft_launcher_lib.utils.get_latest_version()["release"]
                except Exception:
                    actual_version = "1.20.4"

            # 1. Resolve and verify Java runtime (auto-downloading official Mojang runtime if missing)
            custom_java = inst.get("java_executable") or payload.get("custom_java")
            if custom_java and os.path.isfile(custom_java):
                java_exec = custom_java
            else:
                try:
                    emit_event("launch_state_changed", {
                        "state": "downloading",
                        "launch_id": launch_id,
                        "progress": 5.0,
                        "message": f"Resolving Java runtime for {actual_version}..."
                    })
                    java_exec = ensure_java_runtime(actual_version, mc_dir, launch_callbacks)
                except Exception as e:
                    logger.warning("ensure_java_runtime failed: %s", e)
                    java_exec = cfg.get("java_path") or shutil.which("java") or "java"

            loader_clean = str(loader or "Vanilla").strip()
            loader_lower = loader_clean.lower()

            if force_update:
                logger.info("Force update enabled: Clean reinstalling version %s and dependencies", actual_version)
                from nlc.core.launch import purge_version_directory
                purge_version_directory(mc_dir, actual_version, loader_clean)

            installed_versions = [v["id"] for v in minecraft_launcher_lib.utils.get_installed_versions(mc_dir)]

            # Verify that base Minecraft version libraries exist
            base_mc_ver = _extract_base_mc_version(actual_version)
            if base_mc_ver and (not are_version_libraries_complete(base_mc_ver, mc_dir) or force_update):
                logger.info("Base Minecraft %s is missing libraries or files. Installing...", base_mc_ver)
                emit_event("launch_state_changed", {
                    "state": "downloading",
                    "launch_id": launch_id,
                    "progress": 8.0,
                    "message": f"Verifying Minecraft {base_mc_ver} assets and libraries..."
                })
                minecraft_launcher_lib.install.install_minecraft_version(base_mc_ver, mc_dir, callback=launch_callbacks)
                installed_versions = [v["id"] for v in minecraft_launcher_lib.utils.get_installed_versions(mc_dir)]

            if loader_lower == "fabric":
                fabric_found = next((v for v in installed_versions if "fabric" in v.lower() and actual_version in v), None)
                if not fabric_found or force_update:
                    emit_event("launch_state_changed", {"state": "downloading", "launch_id": launch_id, "progress": 10.0, "message": f"Installing Fabric for {actual_version}..."})
                    minecraft_launcher_lib.fabric.install_fabric(actual_version, mc_dir, callback=launch_callbacks, java=java_exec)
                    installed_versions_new = [v["id"] for v in minecraft_launcher_lib.utils.get_installed_versions(mc_dir)]
                    fabric_found = next((v for v in installed_versions_new if "fabric" in v.lower() and actual_version in v), None)
                    if fabric_found:
                        actual_version = fabric_found
                else:
                    actual_version = fabric_found
            elif loader_lower == "forge":
                forge_found = next((v for v in installed_versions if "forge" in v.lower() and actual_version in v), None)
                if not forge_found or force_update:
                    emit_event("launch_state_changed", {"state": "downloading", "launch_id": launch_id, "progress": 10.0, "message": f"Installing Forge for {actual_version}..."})
                    try:
                        forge_ver = minecraft_launcher_lib.forge.find_forge_version(actual_version)
                        if forge_ver:
                            minecraft_launcher_lib.forge.install_forge_version(forge_ver, mc_dir, callback=launch_callbacks, java=java_exec)
                            installed_versions_new = [v["id"] for v in minecraft_launcher_lib.utils.get_installed_versions(mc_dir)]
                            forge_found = next((v for v in installed_versions_new if "forge" in v.lower() and actual_version in v), None)
                            if forge_found:
                                actual_version = forge_found
                    except Exception as e:
                        logger.warning(f"Could not automatically install Forge: {e}")
                else:
                    actual_version = forge_found
            elif loader_lower == "quilt":
                quilt_found = next((v for v in installed_versions if "quilt" in v.lower() and actual_version in v), None)
                if not quilt_found or force_update:
                    emit_event("launch_state_changed", {"state": "downloading", "launch_id": launch_id, "progress": 10.0, "message": f"Installing Quilt for {actual_version}..."})
                    try:
                        minecraft_launcher_lib.quilt.install_quilt(actual_version, mc_dir, callback=launch_callbacks, java=java_exec)
                        installed_versions_new = [v["id"] for v in minecraft_launcher_lib.utils.get_installed_versions(mc_dir)]
                        quilt_found = next((v for v in installed_versions_new if "quilt" in v.lower() and actual_version in v), None)
                        if quilt_found:
                            actual_version = quilt_found
                    except Exception as e:
                        logger.warning(f"Could not automatically install Quilt: {e}")
                else:
                    actual_version = quilt_found
            elif loader_lower == "neoforge":
                neoforge_found = next((v for v in installed_versions if "neoforge" in v.lower() and (actual_version in v or v in actual_version)), None)
                if not neoforge_found or force_update:
                    emit_event("launch_state_changed", {
                        "state": "downloading",
                        "launch_id": launch_id,
                        "progress": 10.0,
                        "message": f"Installing NeoForge for {actual_version}..."
                    })
                    try:
                        import minecraft_launcher_lib.mod_loader as ml
                        neo = ml.Neoforge()
                        requested_loader_ver = payload.get("loader_version") or inst.get("loader_version")
                        loader_versions = neo.get_loader_versions(actual_version, stable_only=False)
                        if requested_loader_ver and requested_loader_ver in loader_versions:
                            loader_ver = requested_loader_ver
                        elif loader_versions:
                            loader_ver = loader_versions[0]
                        else:
                            loader_ver = None

                        if loader_ver:
                            logger.info("Installing NeoForge %s for Minecraft %s using java=%s", loader_ver, actual_version, java_exec)
                            neo.install(actual_version, mc_dir, callback=launch_callbacks, java=java_exec, loader_version=loader_ver)
                            actual_version = neo.get_installed_version(actual_version, loader_ver)
                            logger.info("NeoForge installed successfully as %s", actual_version)
                        else:
                            logger.warning("No NeoForge loader versions found for %s", actual_version)
                    except Exception as e:
                        logger.warning(f"Could not automatically install NeoForge: {e}")
                else:
                    actual_version = neoforge_found
            elif loader_lower == "vanilla":
                if actual_version not in installed_versions or not are_version_libraries_complete(actual_version, mc_dir) or force_update:
                    emit_event("launch_state_changed", {"state": "downloading", "launch_id": launch_id, "progress": 10.0, "message": f"Installing Vanilla {actual_version}..."})
                    minecraft_launcher_lib.install.install_minecraft_version(actual_version, mc_dir, callback=launch_callbacks)

            username = profile.get("name", "Steve")
            acct_type = profile.get("type", "offline")
            launch_uuid = ""
            launch_token = ""
            ram_val = payload.get("ram_mb") or inst.get("max_ram_mb") or inst.get("ram_max") or inst.get("max_ram") or cfg.get("ram", cfg.get("ram_allocation", 4096))
            min_ram_val = payload.get("min_ram_mb") or inst.get("min_ram_mb") or inst.get("ram_min") or inst.get("min_ram") or cfg.get("min_ram")
            jvm_args = [f"-Xmx{ram_val}M"]
            if min_ram_val:
                jvm_args.append(f"-Xms{min_ram_val}M")

            inst_jvm = inst.get("jvm_arguments") or inst.get("jvm_args") or ""
            if inst_jvm:
                jvm_args.extend(inst_jvm.split())
            cfg_jvm = cfg.get("jvm_arguments") or cfg.get("java_args") or ""
            if cfg_jvm and cfg_jvm != inst_jvm:
                jvm_args.extend(cfg_jvm.split())

            # Optimized G1GC flags for fast launch and low GC pause latency
            current_jvm_str = " ".join(jvm_args)
            default_gc_args = [
                "-XX:+UseG1GC",
                "-XX:+ParallelRefProcEnabled",
                "-XX:MaxGCPauseMillis=200",
                "-XX:+UnlockExperimentalVMOptions",
                "-XX:+DisableExplicitGC",
                "-XX:+AlwaysPreTouch",
                "-XX:+PerfDisableSharedMem",
            ]
            for flag in default_gc_args:
                flag_key = flag.split("=")[0]
                if flag_key not in current_jvm_str:
                    jvm_args.append(flag)

            if acct_type == "microsoft":
                fresh_tok = ensure_valid_microsoft_token(profile)
                launch_uuid = profile.get("uuid", "")
                launch_token = vault_decrypt(fresh_tok or profile.get("access_token", ""))
            elif acct_type == "ely.by":
                launch_uuid = profile.get("uuid", "")
                launch_token = vault_decrypt(profile.get("token", ""))
                jar_path = _ensure_authlib_injector(mc_dir)
                if jar_path and os.path.exists(jar_path):
                    jvm_args.append(f"-javaagent:{jar_path}=https://authserver.ely.by/api/authlib-injector")
            else:
                launch_uuid = compute_offline_uuid(username)
                enable_skin_inj = cfg.get("offline_skin_injection", cfg.get("skin_injection", cfg.get("auto_download_mod", True)))
                skin_path = profile.get("skin_path")
                if enable_skin_inj and skin_path and os.path.exists(skin_path):
                    emit_event("launch_state_changed", {"state": "injecting", "launch_id": launch_id, "progress": 85.0, "message": "Starting local skin proxy..."})
                    local_skin_server = LocalSkinServer(port=0)
                    skin_url = local_skin_server.start(skin_path, username, launch_uuid, profile.get("skin_model", "classic"))
                    jar_path = _ensure_authlib_injector(mc_dir)
                    if jar_path and os.path.exists(jar_path) and skin_url:
                        jvm_args.append(f"-javaagent:{jar_path}={skin_url}")
                        logger.info("Injected offline skin via authlib-injector: %s (model=%s)", skin_path, profile.get("skin_model", "classic"))
                elif not enable_skin_inj:
                    logger.info("Offline skin injection is disabled in settings. Launching without authlib-injector.")
                else:
                    logger.info("Offline skin injection is enabled, but no local skin selected for %s. Launching without authlib-injector.", username)

            target_dir = mc_dir
            mp_mods_dir = _resolve_instance_mods_dir(inst_id)
            if mp_mods_dir and mp_mods_dir != str(Path(mc_dir) / "mods"):
                target_dir = os.path.dirname(mp_mods_dir)
                sync_instance_assets(target_dir, mc_dir, cfg.get("instances", {}))
            elif inst.get("game_directory"):
                gdir = os.path.abspath(os.path.expanduser(inst["game_directory"]))
                os.makedirs(gdir, exist_ok=True)
                sync_instance_assets(gdir, mc_dir, cfg.get("instances", {}))
                target_dir = gdir

            if force_update:
                from nlc.core.launch import clean_modpack_temp_files
                clean_modpack_temp_files(target_dir)

                linked_mp = None
                mp_file = Path(get_config_dir()) / "modpacks.json"
                if mp_file.exists():
                    try:
                        with open(mp_file, "r", encoding="utf-8") as f:
                            modpacks_list = json.load(f)
                        if isinstance(modpacks_list, list):
                            for m in modpacks_list:
                                if m.get("id") in (inst_id, clean_id) or m.get("linked_installation_id") in (inst_id, clean_id):
                                    linked_mp = m
                                    break
                    except Exception:
                        pass

                if linked_mp:
                    logger.info("Force update: Re-verifying modpack '%s' files in %s", linked_mp.get("name", inst_id), target_dir)
                    mods_folder = Path(target_dir) / "mods"
                    mods_folder.mkdir(parents=True, exist_ok=True)
                    for m in linked_mp.get("mods", []):
                        fn = m.get("filename")
                        if fn:
                            mod_file = mods_folder / fn
                            if not mod_file.exists() or mod_file.stat().st_size == 0:
                                slug = m.get("slug")
                                ver_id = m.get("version_id")
                                if slug:
                                    try:
                                        logger.info("Force update: Re-downloading missing modpack mod %s (%s)", fn, slug)
                                        handle_modrinth_install_artifact({
                                            "project_id": slug,
                                            "version_id": ver_id,
                                            "target_id": linked_mp.get("id"),
                                            "project_type": "mod",
                                        })
                                    except Exception as e_mod:
                                        logger.warning("Could not re-download modpack mod %s: %s", fn, e_mod)
                    sync_instance_assets(target_dir, mc_dir, cfg.get("instances", {}))

            options = {
                "username": username,
                "uuid": launch_uuid,
                "token": launch_token,
                "jvmArguments": jvm_args,
                "launcherName": "NewLauncher",
                "gameDirectory": target_dir,
                "executablePath": java_exec,
            }

            res_w = inst.get("resolution_width") or payload.get("resolution_width") or payload.get("resolution_w")
            res_h = inst.get("resolution_height") or payload.get("resolution_height") or payload.get("resolution_h")
            if res_w and res_h:
                options["customResolution"] = True
                options["resolutionWidth"] = str(res_w)
                options["resolutionHeight"] = str(res_h)

            server_target = payload.get("server") or payload.get("server_address")
            port_target = payload.get("port") or payload.get("server_port")
            if server_target:
                options["server"] = str(server_target).strip()
                if port_target:
                    options["port"] = str(port_target).strip()

            command = minecraft_launcher_lib.command.get_minecraft_command(actual_version, mc_dir, options)

            creationflags = 0
            if sys.platform == "win32":
                creationflags = 0x08000000  # CREATE_NO_WINDOW

            proc = subprocess.Popen(
                command,
                cwd=target_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                creationflags=creationflags
            )

            started_at = time.time()
            with _process_lock:
                if cancel_event.is_set():
                    proc.kill()
                    raise RuntimeError("Launch cancelled by user")
                if launch_id in _running_processes:
                    _running_processes[launch_id]["proc"] = proc
                    _running_processes[launch_id]["skin_server"] = local_skin_server
                    _running_processes[launch_id]["started_at"] = started_at
                else:
                    _running_processes[launch_id] = {
                        "proc": proc,
                        "cancel_event": cancel_event,
                        "skin_server": local_skin_server,
                        "started_at": started_at,
                        "instance_id": inst_id
                    }

            emit_event("launch_state_changed", {
                "state": "running",
                "launch_id": launch_id,
                "pid": proc.pid,
                "instance_id": inst_id,
                "instance_name": inst.get("name") or actual_version,
                "version": actual_version,
                "loader": loader,
                "message": "Game process running"
            })

            try:
                modpack_name = inst.get("name") if (inst.get("is_modpack") or "modpack" in str(inst.get("id", "")).lower()) else None
                logger.info("[Discord RPC] Setting playing: ver=%s, loader=%s, inst=%s, pack=%s", actual_version, loader, inst.get("name"), modpack_name)
                _discord_rpc_manager.set_playing(
                    version=actual_version,
                    loader=loader,
                    installation_name=inst.get("name"),
                    modpack_name=modpack_name,
                    server_address=server_target,
                    started_at=started_at,
                )
            except Exception as e:
                logger.warning("Error setting Discord playing state: %s", e)
            if proc.stdout:
                for line in proc.stdout:
                    l = line.strip()
                    if l:
                        logger.info("[Minecraft] %s", l)
                        emit_event("game_log", {"launch_id": launch_id, "line": l})

                        # Dynamic Discord RPC In-Game State Detection
                        try:
                            lower_l = l.lower()
                            if "connecting to " in lower_l and "," in l:
                                # e.g. "[Render thread/INFO]: Connecting to mc.hypixel.net, 25565"
                                s_host = l.split("Connecting to ", 1)[-1].split(",")[0].strip()
                                _discord_rpc_manager.set_game_state("multiplayer", s_host)
                            elif any(s in l for s in ("Starting integrated minecraft server", "Loaded 0 advancements", "loaded 0 advancement", "Saving and pausing game")):
                                _discord_rpc_manager.set_game_state("singleplayer")
                            elif any(s in l for s in ("Stopping singleplayer server", "Saving chunks for level", "Stopping server")):
                                _discord_rpc_manager.set_game_state("menu")
                            elif any(s in lower_l for s in ("disconnected from server", "lost connection", "disconnecting from", "left the game")):
                                _discord_rpc_manager.set_game_state("menu")
                        except Exception:
                            pass

            proc.wait()
            elapsed = int(time.time() - started_at)

            # Auto-record play session in config
            try:
                with _config_lock:
                    cfg_curr = cm.load()
                    cfg_curr["addons"] = addon_record_play_session(cfg_curr.get("addons", {}), inst_id, elapsed)
                    cm.save(cfg_curr)
            except Exception as e:
                logger.warning("Auto recording play session failed: %s", e)

            emit_event("launch_state_changed", {
                "state": "stopped",
                "launch_id": launch_id,
                "exit_code": proc.returncode,
                "session_seconds": elapsed,
                "message": "Game session ended"
            })
            emit_event("game_session_ended", {
                "launch_id": launch_id,
                "installation_id": inst_id,
                "session_seconds": elapsed,
                "exit_code": proc.returncode
            })
        except Exception as exc:
            logger.exception("Launch failed: %s", exc)
            emit_event("launch_state_changed", {
                "state": "error",
                "launch_id": launch_id,
                "message": str(exc)
            })
        finally:
            if local_skin_server:
                local_skin_server.stop()
            with _process_lock:
                _running_processes.pop(launch_id, None)
            try:
                _discord_rpc_manager.set_idle()
            except Exception:
                pass

    threading.Thread(target=_execute_launch_sequence, daemon=True, name=f"launch-{launch_id[:8]}").start()
    return {"status": "launching", "launch_id": launch_id}


def handle_kill_game(payload: Dict[str, Any]) -> Dict[str, Any]:
    launch_id = payload.get("launch_id") or ""
    with _process_lock:
        targets = []
        if launch_id and launch_id in _running_processes:
            targets.append((launch_id, _running_processes[launch_id]))
        else:
            targets = list(_running_processes.items())

        for _lid, record in targets:
            if record.get("cancel_event"):
                record["cancel_event"].set()
            proc = record.get("proc")
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=1.5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            if record.get("skin_server"):
                try:
                    record["skin_server"].stop()
                except Exception:
                    pass
            record["killed"] = True

        if targets:
            emit_event("launch_state_changed", {
                "state": "stopped",
                "launch_id": launch_id,
                "message": "Launch cancelled by user"
            })
            return {"status": "success", "killed": True}
    return {"status": "error", "message": f"No active launch found"}


# Addon Helpers & Authentic Handlers
def addon_normalize_config(addons_config):
    normalized = dict(addons_config) if isinstance(addons_config, dict) else {}
    normalized.setdefault("p3_reload_menu", False)
    normalized["streamer_mode_enabled"] = bool(normalized.get("streamer_mode_enabled", False))
    normalized["gh_sync_enabled"] = bool(normalized.get("gh_sync_enabled", False))
    normalized["gh_repo"] = str(normalized.get("gh_repo", "") or "")
    normalized["gh_token"] = str(normalized.get("gh_token", "") or "")
    normalized["curseforge_api_key"] = str(normalized.get("curseforge_api_key", "") or "")

    if not isinstance(normalized.get("playtime_tracker"), dict):
        normalized["playtime_tracker"] = {}

    saved_servers = normalized.get("saved_servers", [])
    if not isinstance(saved_servers, list):
        saved_servers = []

    normalized_servers = []
    for server in saved_servers:
        if not isinstance(server, dict):
            continue
        address = str(server.get("address", "")).strip()
        if not address:
            continue
        port = server.get("port", 25565)
        try:
            port = int(port)
        except Exception:
            port = 25565
        normalized_servers.append({
            "id": str(server.get("id") or uuid.uuid4()),
            "name": str(server.get("name") or address),
            "address": address,
            "port": port,
        })
    normalized["saved_servers"] = normalized_servers
    return normalized


def addon_set_streamer_mode(addons_config, enabled):
    normalized = addon_normalize_config(addons_config)
    normalized["streamer_mode_enabled"] = bool(enabled)
    return normalized


def addon_reset_playtime_tracker(addons_config):
    normalized = addon_normalize_config(addons_config)
    normalized["playtime_tracker"] = {}
    return normalized


def addon_record_play_session(addons_config, inst_id, session_seconds, server_address=None, server_port=None):
    normalized = addon_normalize_config(addons_config)
    inst_id = str(inst_id or "").strip()
    if not inst_id:
        return normalized

    tracker = normalized.setdefault("playtime_tracker", {})
    stats = tracker.setdefault(inst_id, {})
    stats["seconds"] = int(stats.get("seconds", 0) or 0) + max(0, int(session_seconds))
    stats["launches"] = int(stats.get("launches", 0) or 0) + 1
    stats["last_session_seconds"] = max(0, int(session_seconds))
    stats["last_played_at"] = datetime.now().isoformat()

    if server_address:
        last_server = str(server_address)
        if server_port:
            last_server = f"{last_server}:{server_port}"
        stats["last_server"] = last_server

    return normalized


def addon_add_saved_server(addons_config, name, address, port):
    normalized = addon_normalize_config(addons_config)
    address = str(address or "").strip()
    port = str(port or "25565").strip()
    name = str(name or "").strip()

    if not address:
        raise ValueError("Enter a server address first.")

    if ":" in address and address.count(":") == 1:
        host_part, maybe_port = address.rsplit(":", 1)
        if maybe_port.isdigit():
            address = host_part
            if not port or port == "25565":
                port = maybe_port

    if not port:
        port = "25565"
    if not port.isdigit():
        raise ValueError("Server port must be a number.")

    normalized.setdefault("saved_servers", []).append({
        "id": str(uuid.uuid4()),
        "name": name or address,
        "address": address,
        "port": int(port),
    })
    return normalized


def addon_remove_saved_server(addons_config, server_id):
    normalized = addon_normalize_config(addons_config)
    normalized["saved_servers"] = [
        server for server in normalized.get("saved_servers", [])
        if str(server.get("id")) != str(server_id)
    ]
    return normalized


def addon_delete_screenshot(path, _minecraft_dir=None):
    target_path = os.path.abspath(str(path))
    if not os.path.exists(target_path):
        raise FileNotFoundError(target_path)
    if os.path.splitext(target_path)[1].lower() not in {".png", ".jpg", ".jpeg"}:
        raise ValueError("Only screenshot image files can be deleted.")
    os.remove(target_path)
    return {"deleted": target_path}


def _sanitize_identifier(value):
    cleaned = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in str(value or "").strip())
    return cleaned.strip("_") or "addon"


def _normalize_addon_input(input_data, index):
    if not isinstance(input_data, dict):
        return None

    input_id = str(input_data.get("id") or f"input_{index + 1}").strip()
    if not input_id:
        return None

    input_type = str(input_data.get("type") or "text").strip().lower()
    if input_type not in {"text", "number", "checkbox", "password"}:
        input_type = "text"

    return {
        "id": input_id,
        "label": str(input_data.get("label") or input_id.replace("_", " ").title()),
        "type": input_type,
        "default": input_data.get("default", False if input_type == "checkbox" else ""),
        "placeholder": str(input_data.get("placeholder") or ""),
    }


def _normalize_addon_action(action_data, index):
    if not isinstance(action_data, dict):
        return None

    action_id = str(action_data.get("id") or f"action_{index + 1}").strip()
    if not action_id:
        return None

    style = str(action_data.get("style") or "secondary").strip().lower()
    if style not in {"primary", "secondary", "danger", "text"}:
        style = "secondary"

    inputs = []
    for input_index, input_data in enumerate(action_data.get("inputs", []) or []):
        normalized_input = _normalize_addon_input(input_data, input_index)
        if normalized_input:
            inputs.append(normalized_input)

    return {
        "id": action_id,
        "label": str(action_data.get("label") or action_id.replace("_", " ").title()),
        "description": str(action_data.get("description") or ""),
        "style": style,
        "inputs": inputs,
    }


def _normalize_addon_manifest(raw_manifest, addon_dir, folder_name):
    manifest = raw_manifest if isinstance(raw_manifest, dict) else {}
    addon_id = str(manifest.get("id") or folder_name).strip() or folder_name
    entrypoint = str(manifest.get("entrypoint") or "main.py").strip() or "main.py"

    actions = []
    for index, action_data in enumerate(manifest.get("actions", []) or []):
        normalized_action = _normalize_addon_action(action_data, index)
        if normalized_action:
            actions.append(normalized_action)

    return {
        "id": addon_id,
        "name": str(manifest.get("name") or folder_name.replace("_", " ").title()),
        "version": str(manifest.get("version") or "1.0.0"),
        "author": str(manifest.get("author") or "Unknown"),
        "description": str(manifest.get("description") or "No description provided."),
        "entrypoint": entrypoint,
        "actions": actions,
        "folder_name": folder_name,
        "addon_dir": addon_dir,
        "entrypoint_path": os.path.join(addon_dir, entrypoint),
    }


def _build_addon_context(addon_record, payload=None):
    addon_dir = addon_record["addon_dir"]
    data_dir = os.path.join(addon_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    return {
        "addon_id": addon_record["id"],
        "addon_name": addon_record["name"],
        "addon_dir": addon_dir,
        "data_dir": data_dir,
        "addons_dir": get_third_party_addons_dir(),
        "config_dir": get_config_dir(),
        "launcher_dir": get_launcher_dir(),
        "minecraft_dir": None if payload is None else payload.get("minecraft_dir"),
    }


def _load_addon_module(addon_record):
    entrypoint_path = addon_record.get("entrypoint_path")
    if not entrypoint_path or not os.path.isfile(entrypoint_path):
        return None, f"Missing addon entrypoint: {addon_record.get('entrypoint', 'main.py')}"

    module_name = f"nlc_addon_{_sanitize_identifier(addon_record.get('id'))}_{int(time.time() * 1000)}"
    spec = importlib.util.spec_from_file_location(module_name, entrypoint_path)
    if spec is None or spec.loader is None:
        return None, f"Could not load addon module for {addon_record.get('id')}"

    module = importlib.util.module_from_spec(spec)
    old_sys_path = list(sys.path)
    try:
        sys.path.insert(0, addon_record["addon_dir"])
        spec.loader.exec_module(module)
        return module, None
    except Exception as exc:
        return None, f"{exc}\n{traceback.format_exc()}"
    finally:
        sys.path[:] = old_sys_path


def _merge_addon_registration(addon_record, registration):
    if not isinstance(registration, dict):
        return addon_record

    merged = dict(addon_record)
    for key in ("name", "version", "author", "description"):
        if key in registration:
            merged[key] = str(registration.get(key) or merged[key])

    if "actions" in registration:
        actions = []
        for index, action_data in enumerate(registration.get("actions", []) or []):
            normalized_action = _normalize_addon_action(action_data, index)
            if normalized_action:
                actions.append(normalized_action)
        merged["actions"] = actions

    return merged


def discover_third_party_addons(payload=None):
    addons = []
    addons_dir = get_third_party_addons_dir()

    try:
        folder_names = sorted(os.listdir(addons_dir))
    except Exception:
        folder_names = []

    for folder_name in folder_names:
        addon_dir = os.path.join(addons_dir, folder_name)
        if not os.path.isdir(addon_dir):
            continue

        manifest_path = os.path.join(addon_dir, ADDON_MANIFEST)
        if not os.path.isfile(manifest_path):
            continue

        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                raw_manifest = json.load(handle)
            addon_record = _normalize_addon_manifest(raw_manifest, addon_dir, folder_name)

            module, load_error = _load_addon_module(addon_record)
            addon_record["load_error"] = None
            if load_error:
                addon_record["load_error"] = load_error
            elif hasattr(module, "register"):
                try:
                    registration = module.register(_build_addon_context(addon_record, payload))
                    addon_record = _merge_addon_registration(addon_record, registration)
                except Exception as exc:
                    addon_record["load_error"] = f"{exc}\n{traceback.format_exc()}"

            addons.append(addon_record)
        except Exception as exc:
            addons.append({
                "id": folder_name,
                "name": folder_name.replace("_", " ").title(),
                "version": "0.0.0",
                "author": "Unknown",
                "description": "Failed to load addon manifest.",
                "entrypoint": "main.py",
                "actions": [],
                "folder_name": folder_name,
                "addon_dir": addon_dir,
                "entrypoint_path": os.path.join(addon_dir, "main.py"),
                "load_error": f"{exc}\n{traceback.format_exc()}",
            })

    return {"addons_dir": addons_dir, "addons": addons}


def _find_addon_record(addon_id, payload=None):
    listing = discover_third_party_addons(payload)
    for addon_record in listing.get("addons", []):
        if str(addon_record.get("id")) == str(addon_id):
            return addon_record, listing
    return None, listing


def run_third_party_addon_action(addon_id, action_id, payload=None):
    addon_record, listing = _find_addon_record(addon_id, payload)
    if addon_record is None:
        return {
            "status": "error",
            "msg": f"Addon '{addon_id}' was not found in {listing.get('addons_dir')}",
        }

    if addon_record.get("load_error"):
        return {
            "status": "error",
            "msg": f"Addon '{addon_record.get('name')}' failed to load.\n{addon_record.get('load_error')}",
        }

    module, load_error = _load_addon_module(addon_record)
    if load_error:
        return {
            "status": "error",
            "msg": f"Failed to load addon '{addon_record.get('name')}'.\n{load_error}",
        }

    context = _build_addon_context(addon_record, payload)
    inputs = {}
    if isinstance(payload, dict):
        raw_inputs = payload.get("inputs", {})
        if isinstance(raw_inputs, dict):
            inputs = raw_inputs

    try:
        result = None
        if hasattr(module, "handle_action"):
            result = module.handle_action(action_id, inputs, context)
        else:
            action_func_name = f"action_{_sanitize_identifier(action_id)}"
            if hasattr(module, action_func_name):
                result = getattr(module, action_func_name)(inputs, context)
            else:
                return {
                    "status": "error",
                    "msg": f"Addon '{addon_record.get('name')}' does not expose action '{action_id}'.",
                }

        if result is None:
            return {"status": "success", "msg": f"{addon_record.get('name')} finished successfully."}
        if isinstance(result, dict):
            result.setdefault("status", "success")
            return result
        return {"status": "success", "msg": str(result)}
    except Exception as exc:
        return {
            "status": "error",
            "msg": f"{exc}\n{traceback.format_exc()}",
        }


def handle_gh_skin_sync(payload):
    repo = payload.get("repo") or payload.get("gh_repo")
    token = payload.get("token") or payload.get("gh_token")
    if token:
        token = vault_decrypt(token)
    username = payload.get("username")
    skin_path = payload.get("skin_path")
    do_upload = payload.get("upload", False)
    do_download = payload.get("download", True)

    if not repo or not token or not username:
        return {"status": "error", "msg": "Missing configuration"}

    session = get_session()
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    skins_cache_dir = os.path.join(get_config_dir(), "skins_cache")
    if not os.path.exists(skins_cache_dir):
        os.makedirs(skins_cache_dir, exist_ok=True)

    file_name = f"skins/{username}.png"
    api_url = f"https://api.github.com/repos/{repo}/contents/{file_name}"
    base_url = f"https://api.github.com/repos/{repo}/contents/skins"

    try:
        # 1. Upload Current Skin if requested
        if do_upload and skin_path and os.path.exists(skin_path):
            file_size = os.path.getsize(skin_path)
            if file_size > 1048576:
                return {"status": "error", "msg": "Skin file too large (max 1MB)"}

            with open(skin_path, "rb") as f:
                content = base64.b64encode(f.read()).decode("utf-8")

            sha = None
            try:
                r_check = session.get(api_url, headers=headers, timeout=10)
                if r_check.status_code == 200:
                    sha = r_check.json().get("sha")
            except requests.RequestException:
                pass

            data = {
                "message": f"Update skin for {username}",
                "content": content,
                "branch": "main"
            }
            if sha:
                data["sha"] = sha

            r_put = session.put(api_url, headers=headers, json=data, timeout=30)
            if r_put.status_code not in [200, 201]:
                return {"status": "error", "msg": f"Upload failed: {r_put.status_code} {r_put.text}"}

        # 2. Download Friends' Skins
        synced_count = 0
        skipped_count = 0
        if do_download:
            try:
                r_list = session.get(base_url, headers=headers, timeout=15)
                if r_list.status_code == 200:
                    items = r_list.json()
                    if isinstance(items, list):
                        for item in items:
                            name = item.get("name")
                            download_url = item.get("download_url")
                            remote_sha = item.get("sha")

                            if name and download_url and name.endswith(".png"):
                                local_file = os.path.join(skins_cache_dir, name)
                                if os.path.exists(local_file) and remote_sha:
                                    local_sha = get_file_sha(local_file)
                                    if local_sha and local_sha == remote_sha:
                                        skipped_count += 1
                                        continue

                                try:
                                    r_img = session.get(download_url, timeout=15)
                                    if r_img.status_code == 200:
                                        if r_img.content[:8] == b'\x89PNG\r\n\x1a\n':
                                            with open(local_file, "wb") as f:
                                                f.write(r_img.content)
                                            synced_count += 1
                                except requests.RequestException:
                                    continue
            except requests.RequestException as e:
                return {"status": "error", "msg": f"Download failed: {str(e)}"}

        return {"status": "success", "msg": f"Skin sync complete. Uploaded: {do_upload}, Downloaded: {synced_count}, Skipped: {skipped_count}"}

    except Exception as e:
        return {"status": "error", "msg": str(e)}


def handle_search_mods(payload):
    try:
        query = payload.get("query")
        limit = payload.get("limit", 20)
        offset = payload.get("offset", 0)
        facets = list(payload.get("facets", []))
        sort = payload.get("sort") or payload.get("index")

        if not facets:
            pt = payload.get("project_type")
            if pt and str(pt).lower() != "all":
                facets.append(f"project_type:{str(pt).lower()}")
            ldr = payload.get("loader")
            if ldr and str(ldr).lower() not in ("vanilla", "all") and (not pt or str(pt).lower() not in ("resourcepack", "shader")):
                facets.append(f"categories:{str(ldr).lower()}")
            ver = payload.get("version")
            if ver and str(ver).lower() != "all":
                facets.append(f"versions:{ver}")

        params = f"limit={limit}&offset={offset}"
        if query:
            params += f"&query={urllib.parse.quote(str(query))}"

        if sort and str(sort).lower() in ("relevance", "downloads", "follows", "newest", "updated"):
            params += f"&index={str(sort).lower()}"
        elif not query:
            params += "&index=downloads"

        if facets:
            facet_str = "".join(f',["{f}"]' for f in facets).lstrip(",")
            enc = urllib.parse.quote(f"[{facet_str}]")
            params += f"&facets={enc}"

        url = f"https://api.modrinth.com/v2/search?{params}"
        headers = {"User-Agent": "AmneDev/NewLauncher/1.8.2"}

        cache_dir = Path(get_config_dir()) / "cache" / "search"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        cache_file = cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            try:
                if time.time() - cache_file.stat().st_mtime < 900:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        return {"status": "success", "data": json.load(f), "cached": True}
            except Exception:
                pass

        session = get_session()
        response = session.get(url, headers=headers, timeout=3.0)
        if response.status_code == 200:
            data = response.json()
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(data, f)
            except Exception:
                pass
            return {"status": "success", "data": data}
        else:
            return {"status": "error", "code": response.status_code, "msg": response.text}

    except requests.Timeout:
        if 'cache_file' in locals() and cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return {"status": "success", "data": json.load(f), "cached": True}
            except Exception:
                pass
        return {"status": "error", "msg": "Request timed out"}
    except requests.RequestException as e:
        if 'cache_file' in locals() and cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return {"status": "success", "data": json.load(f), "cached": True}
            except Exception:
                pass
        return {"status": "error", "msg": f"Network error: {str(e)}"}
    except Exception as e:
        return {"status": "error", "msg": str(e)}


def handle_addons_normalize(payload):
    return {"status": "success", "data": addon_normalize_config(payload.get("addons", {}))}


def handle_addons_set_streamer_mode(payload: Dict[str, Any]) -> Dict[str, Any]:
    enabled = bool(payload.get("enabled", payload.get("streamer_mode", payload.get("streamer_privacy", False))))
    cm = get_config_manager()
    with _config_lock:
        cfg = cm.load()
        cfg["streamer_mode"] = enabled
        cfg["streamer_privacy"] = enabled
        raw_addons = payload.get("addons") if payload.get("addons") is not None else cfg.get("addons", {})
        addons = addon_set_streamer_mode(raw_addons, enabled)
        cfg["addons"] = addons
        cm.save(cfg)
    emit_event("config_changed", {"key": "streamer_mode", "value": enabled})
    return {
        "status": "success",
        "data": addons,
        "streamer_mode": enabled,
        "enabled": enabled,
        "streamer_mode_enabled": enabled
    }


def handle_addons_get_playtime(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = load_launcher_config()
    addons = cfg.get("addons", {})
    tracker = addons.get("playtime_tracker", {}) or addons.get("playtime", {})
    total_seconds = 0
    total_launches = 0
    for inst_id, stats in tracker.items():
        if isinstance(stats, dict):
            total_seconds += int(stats.get("seconds", 0) or 0)
            total_launches += int(stats.get("launches", 0) or 0)
    total_minutes = total_seconds // 60
    return {
        "status": "success",
        "data": {
            "total_seconds": total_seconds,
            "total_minutes": total_minutes,
            "total_launches": total_launches,
            "tracker": tracker,
        },
        "total_seconds": total_seconds,
        "total_minutes": total_minutes,
        "total_launches": total_launches,
        "tracker": tracker,
    }


def handle_addons_reset_playtime(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cm = get_config_manager()
    with _config_lock:
        cfg = cm.load()
        raw_addons = payload.get("addons") if (payload and payload.get("addons") is not None) else cfg.get("addons", {})
        addons = addon_reset_playtime_tracker(raw_addons)
        cfg["addons"] = addons
        cm.save(cfg)
    emit_event("config_changed", {"key": "addons", "value": addons})
    return {
        "status": "success",
        "data": addons,
        "playtime_tracker": {},
        "total_minutes": 0,
        "total_launches": 0
    }


def handle_addons_record_play_session(payload: Dict[str, Any]) -> Dict[str, Any]:
    inst_id = payload.get("inst_id") or payload.get("installation_id")
    sec = payload.get("session_seconds", 0)
    cm = get_config_manager()
    with _config_lock:
        cfg = cm.load()
        raw_addons = payload.get("addons") if payload.get("addons") is not None else cfg.get("addons", {})
        updated = addon_record_play_session(
            raw_addons,
            inst_id,
            sec,
            server_address=payload.get("server_address"),
            server_port=payload.get("server_port"),
        )
        cfg["addons"] = updated
        cm.save(cfg)
    return {"status": "success", "data": updated}


def handle_addons_get_saved_servers(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        cfg = load_launcher_config()
        addons = cfg.get("addons", {})
        normalized = addon_normalize_config(addons)
        return {"status": "success", "servers": normalized.get("saved_servers", []), "data": normalized}
    except Exception as e:
        return {"status": "error", "msg": str(e), "servers": []}


def handle_addons_add_saved_server(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        cm = get_config_manager()
        with _config_lock:
            cfg = cm.load()
            raw_addons = payload.get("addons") if payload.get("addons") is not None else cfg.get("addons", {})
            updated = addon_add_saved_server(
                raw_addons,
                payload.get("name"),
                payload.get("address"),
                payload.get("port"),
            )
            cfg["addons"] = updated
            cm.save(cfg)
        return {"status": "success", "data": updated, "servers": updated.get("saved_servers", [])}
    except Exception as e:
        return {"status": "error", "msg": str(e)}


def handle_addons_remove_saved_server(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        cm = get_config_manager()
        with _config_lock:
            cfg = cm.load()
            addons = cfg.get("addons", {})
            updated = addon_remove_saved_server(addons, payload.get("server_id"))
            cfg["addons"] = updated
            cm.save(cfg)
        return {"status": "success", "data": updated, "servers": updated.get("saved_servers", [])}
    except Exception as e:
        return {"status": "error", "msg": str(e)}


def handle_addons_list_screenshots(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if payload is None:
        payload = {}
    mc_dir = payload.get("minecraft_dir") or get_minecraft_dir()
    primary_dir = os.path.join(str(mc_dir), "screenshots")
    dirs_to_scan = [primary_dir]

    try:
        cfg = load_launcher_config()
        for inst in cfg.get("installations", []):
            g_dir = inst.get("game_directory")
            if g_dir and os.path.exists(g_dir):
                inst_sc = os.path.join(g_dir, "screenshots")
                if inst_sc not in dirs_to_scan and os.path.isdir(inst_sc):
                    dirs_to_scan.append(inst_sc)
    except Exception:
        pass

    try:
        mp_base = os.path.join(get_config_dir(), "modpacks")
        if os.path.isdir(mp_base):
            for d in os.listdir(mp_base):
                sc = os.path.join(mp_base, d, "screenshots")
                if os.path.isdir(sc) and sc not in dirs_to_scan:
                    dirs_to_scan.append(sc)
    except Exception:
        pass

    items = []
    seen = set()
    for s_dir in dirs_to_scan:
        if os.path.isdir(s_dir):
            for entry in os.listdir(s_dir):
                path = os.path.join(s_dir, entry)
                real_p = os.path.realpath(path).lower()
                if real_p in seen:
                    continue
                seen.add(real_p)
                if os.path.isfile(path) and os.path.splitext(entry)[1].lower() in {".png", ".jpg", ".jpeg"}:
                    mtime = os.path.getmtime(path)
                    size = os.path.getsize(path)
                    items.append({
                        "path": path,
                        "name": entry,
                        "size": size,
                        "modified": mtime,
                        "date": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
                    })
    items.sort(key=lambda item: item["modified"], reverse=True)
    return {
        "status": "success",
        "data": {
            "dir": primary_dir,
            "items": items,
        },
        "dir": primary_dir,
        "items": items,
    }


def handle_addons_delete_screenshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        path = payload.get("path") or payload.get("file_path") or ""
        mc_dir = payload.get("minecraft_dir") or get_minecraft_dir()
        res = addon_delete_screenshot(path, mc_dir)
        return {"status": "success", "data": res, "deleted": path}
    except Exception as e:
        return {"status": "error", "msg": str(e)}


def handle_server_ping(payload: Dict[str, Any]) -> Dict[str, Any]:
    host = payload.get("host") or payload.get("address") or "localhost"
    port = int(payload.get("port") or 25565)
    timeout_sec = float(payload.get("timeout") or 3.0)

    start_time = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout_sec)
        sock.connect((host, port))
        latency_ms = int((time.time() - start_time) * 1000)

        def pack_varint(val):
            out = bytearray()
            while True:
                part = val & 0x7F
                val >>= 7
                out.append(part | (0x80 if val != 0 else 0))
                if val == 0:
                    break
            return bytes(out)

        host_bytes = host.encode("utf-8")
        handshake_payload = (
            b"\x00"
            + pack_varint(765)
            + pack_varint(len(host_bytes))
            + host_bytes
            + struct.pack(">H", port)
            + pack_varint(1)
        )
        handshake_packet = pack_varint(len(handshake_payload)) + handshake_payload
        sock.sendall(handshake_packet)
        sock.sendall(b"\x01\x00")

        def read_varint(s):
            val = 0
            shift = 0
            for _ in range(5):
                b = s.recv(1)
                if not b:
                    raise EOFError("Socket closed")
                byte = b[0]
                val |= (byte & 0x7F) << shift
                shift += 7
                if not (byte & 0x80):
                    return val
            raise ValueError("Varint too long")

        _resp_len = read_varint(sock)
        _packet_id = read_varint(sock)
        json_len = read_varint(sock)

        raw_data = bytearray()
        while len(raw_data) < json_len:
            chunk = sock.recv(min(4096, json_len - len(raw_data)))
            if not chunk:
                break
            raw_data.extend(chunk)

        sock.close()
        server_info = json.loads(raw_data.decode("utf-8", errors="replace"))

        motd = ""
        desc = server_info.get("description", "")
        if isinstance(desc, dict):
            motd = desc.get("text", "")
            if "extra" in desc and isinstance(desc["extra"], list):
                motd += "".join(e.get("text", "") for e in desc["extra"] if isinstance(e, dict))
        elif isinstance(desc, str):
            motd = desc

        players = server_info.get("players", {})
        version_data = server_info.get("version", {})

        return {
            "status": "success",
            "online": True,
            "latency_ms": latency_ms,
            "version": version_data.get("name", ""),
            "motd": motd,
            "players_online": players.get("online", 0),
            "players_max": players.get("max", 0),
            "favicon": server_info.get("favicon", ""),
        }
    except Exception as exc:
        latency_ms = int((time.time() - start_time) * 1000) if start_time else -1
        is_online = False
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            s.connect((host, port))
            s.close()
            is_online = True
        except Exception:
            pass

        return {
            "status": "success" if is_online else "offline",
            "online": is_online,
            "latency_ms": latency_ms if is_online else -1,
            "version": "Unknown" if is_online else "",
            "motd": "Online" if is_online else str(exc),
            "players_online": 0,
            "players_max": 0,
            "favicon": "",
        }


def handle_system_check_updates(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from nlc.version import get_version
    current_version = get_version()
    repo = "Amne-Dev/NLC"
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": "NewLauncher/3.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tag = str(data.get("tag_name", "")).lstrip("v").strip()
            body = str(data.get("body", "")).strip()
            assets = data.get("assets", [])

            def parse_ver(v_str):
                return [int(x) for x in re.findall(r"\d+", v_str)]

            is_newer = False
            if tag:
                try:
                    is_newer = parse_ver(tag) > parse_ver(current_version)
                except Exception:
                    is_newer = tag != current_version

            installer_url = ""
            cdc_url = ""
            for a in assets:
                name = a.get("name", "").lower()
                if name in ("nlcsetup.exe", "nlcsetup-web.exe", "setup.exe"):
                    installer_url = a.get("browser_download_url", "")
                elif name.endswith(".cdc.json"):
                    cdc_url = a.get("browser_download_url", "")

            return {
                "status": "success",
                "update_available": is_newer,
                "current_version": current_version,
                "latest_version": tag or current_version,
                "release_notes": body,
                "download_url": installer_url or f"https://github.com/{repo}/releases/latest",
                "cdc_url": cdc_url,
            }
    except Exception as e:
        logger.info("System check updates: %s", e)
        return {
            "status": "success",
            "update_available": False,
            "current_version": current_version,
            "latest_version": current_version,
            "release_notes": "Up to date",
            "download_url": "",
            "cdc_url": "",
        }


def handle_system_apply_update(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        launcher_dir = get_launcher_dir()
        candidates = [
            os.path.join(launcher_dir, "NLCSetup.exe"),
            os.path.join(launcher_dir, "NLCUpdater.exe"),
            os.path.join(launcher_dir, "NLCUpdater"),
            os.path.join(launcher_dir, "updater.sh"),
        ]
        setup_exe = next((c for c in candidates if os.path.isfile(c)), None)
        if setup_exe:
            cmd = [setup_exe, "--update", "--target", launcher_dir]
            popen_kwargs = {"cwd": launcher_dir, "close_fds": True}
            if sys.platform == "win32":
                popen_kwargs["creationflags"] = (
                    getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                )
            else:
                popen_kwargs["start_new_session"] = True
            subprocess.Popen(cmd, **popen_kwargs)
            return {"status": "success", "message": "Updater launched"}
        else:
            return {"status": "error", "error": "Updater executable not found in install directory"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

def handle_diagnostics_get_system_info(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from nlc.core.system_info import get_system_specs, detect_installed_javas, get_total_ram_mb
    specs = get_system_specs()
    javas = detect_installed_javas()
    total_ram = get_total_ram_mb()
    return {
        "status": "success",
        "data": {
            "os": specs.get("os", sys.platform),
            "python": specs.get("python", sys.version),
            "ram": specs.get("ram", f"{total_ram} MB"),
            "ram_mb": total_ram,
            "processor": specs.get("processor", ""),
            "javas": javas,
        },
        "os": specs.get("os", sys.platform),
        "python": specs.get("python", sys.version),
        "ram": specs.get("ram", f"{total_ram} MB"),
        "processor": specs.get("processor", ""),
        "javas": javas,
    }


def handle_diagnostics_get_logs(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    import platform
    log_dir = Path(get_config_dir()) / "logs"
    lines = []
    if log_dir.exists():
        log_files = []
        agent_log = log_dir / "agent.log"
        if agent_log.exists():
            log_files.append(agent_log)
        
        for f in sorted(log_dir.glob("launcher_*.log"), key=lambda p: p.stat().st_mtime):
            log_files.append(f)
            
        if not log_files:
            log_files = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime)

        if log_files:
            recent_lines = []
            for lf in log_files[-3:]:
                try:
                    with open(lf, "r", encoding="utf-8", errors="replace") as f:
                        recent_lines.extend(f.readlines())
                except Exception as e:
                    recent_lines.append(f"Error reading {lf.name}: {e}\n")
            lines = recent_lines[-350:] if len(recent_lines) > 350 else recent_lines
            
    if not lines:
        lines = [
            f"[INFO] Launcher backend active. Logs directory: {log_dir}\n",
            f"[INFO] Platform: {platform.system()} {platform.release()}, Python: {sys.version.split()[0]}\n",
            "[INFO] Waiting for launcher events...\n"
        ]

    # Read Minecraft game logs (latest.log)
    game_log_candidates = [Path(get_minecraft_dir()) / "logs" / "latest.log"]
    inst_id = (payload or {}).get("instance_id") or (payload or {}).get("installation_id")
    if inst_id:
        try:
            mp_mods = _resolve_instance_mods_dir(inst_id)
            if mp_mods:
                game_log_candidates.append(Path(mp_mods).parent / "logs" / "latest.log")
        except Exception:
            pass

    modpacks_dir = Path(get_config_dir()) / "modpacks"
    if modpacks_dir.exists():
        for mp_dir in modpacks_dir.iterdir():
            if mp_dir.is_dir():
                cand = mp_dir / "logs" / "latest.log"
                if cand.exists():
                    game_log_candidates.append(cand)

    found_game_log = None
    latest_mtime = 0
    for cand in game_log_candidates:
        if cand.exists() and cand.is_file():
            try:
                mtime = cand.stat().st_mtime
                if mtime > latest_mtime:
                    latest_mtime = mtime
                    found_game_log = cand
            except Exception:
                pass

    game_lines = []
    if found_game_log:
        try:
            with open(found_game_log, "r", encoding="utf-8", errors="replace") as f:
                glines = f.readlines()
                game_lines = glines[-250:] if len(glines) > 250 else glines
        except Exception as e:
            game_lines = [f"Error reading game log ({found_game_log}): {e}\n"]

    combined_lines = []
    combined_lines.append("=== LAUNCHER LOGS ===\n")
    combined_lines.extend(lines)
    if game_lines:
        combined_lines.append(f"\n=== GAME LOGS ({found_game_log.name}) ===\n")
        combined_lines.extend(game_lines)
    else:
        combined_lines.append("\n=== GAME LOGS ===\nNo game logs found (launch Minecraft to generate logs).\n")

    return {
        "status": "success",
        "lines": combined_lines,
        "text": "".join(combined_lines),
    }


def handle_diagnostics_toggle_logging(payload: Dict[str, Any]) -> Dict[str, Any]:
    enabled = bool(payload.get("enabled", payload.get("debug_logging", payload.get("show_console", False))))
    cm = get_config_manager()
    with _config_lock:
        cfg = cm.load()
        cfg["show_console"] = enabled
        cfg["debug_logging"] = enabled
        cm.save(cfg)
    emit_event("config_changed", {"key": "show_console", "value": enabled})
    return {"status": "success", "show_console": enabled, "debug_logging": enabled}


def handle_list_third_party_addons(payload):
    return {"status": "success", "data": discover_third_party_addons(payload)}


def handle_run_third_party_addon_action(payload):
    addon_id = payload.get("addon_id")
    action_id = payload.get("action_id")
    return run_third_party_addon_action(addon_id, action_id, payload)

def handle_addons_get_community_catalog(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = "https://raw.githubusercontent.com/Amne-Dev/Community-addons-nlc/main/addons.json"
    req = urllib.request.Request(url, headers={"User-Agent": "NewLauncher/3.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                return {"status": "success", "data": data}
    except Exception as e:
        logger.info("Community addons catalog fetch error: %s", e)
    return {"status": "success", "data": []}

def handle_addons_install_community(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not payload:
        return {"status": "error", "error": "Missing payload"}

    addon_id = str(payload.get("addon_id") or "").strip()
    download_url = str(payload.get("download_url") or "").strip()
    expected_sha256 = str(payload.get("sha256") or "").strip().lower()

    if not addon_id or not re.match(r"^[a-z0-9_]{3,40}$", addon_id):
        return {"status": "error", "error": f"Invalid addon ID: {addon_id}"}

    if not download_url.startswith("https://"):
        return {"status": "error", "error": "download_url must use secure HTTPS"}

    try:
        req = urllib.request.Request(download_url, headers={"User-Agent": "NewLauncher/3.0"})
        max_bytes = 50 * 1024 * 1024
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_bytes = bytearray()
            hasher = hashlib.sha256()
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                raw_bytes.extend(chunk)
                hasher.update(chunk)
                if len(raw_bytes) > max_bytes:
                    return {"status": "error", "error": "Addon archive exceeds 50MB size limit"}

        actual_sha256 = hasher.hexdigest()
        if expected_sha256 and expected_sha256 != actual_sha256:
            return {
                "status": "error",
                "error": f"SHA-256 integrity check failed. Expected {expected_sha256}, got {actual_sha256}"
            }

        if not raw_bytes.startswith(b"PK\x03\x04"):
            return {"status": "error", "error": "Downloaded file is not a valid ZIP archive"}

        zf = zipfile.ZipFile(io.BytesIO(raw_bytes))
        forbidden_exts = {
            ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".scr", ".pif", ".com",
            ".dll", ".so", ".dylib", ".jar", ".msi", ".reg", ".hta", ".cpl", ".lnk"
        }

        for member in zf.infolist():
            norm_name = member.filename.replace("\\", "/")
            if norm_name.startswith("/") or ".." in norm_name.split("/") or re.match(r"^[a-zA-Z]:", norm_name):
                return {"status": "error", "error": f"Zip-Slip path traversal detected in archive: {member.filename}"}
            if not member.is_dir():
                _, ext = os.path.splitext(norm_name.lower())
                if ext in forbidden_exts:
                    return {
                        "status": "error",
                        "error": f"Archive contains forbidden binary or executable file: {member.filename}"
                    }

        target_dir = os.path.join(get_third_party_addons_dir(), addon_id)
        os.makedirs(target_dir, exist_ok=True)
        zf.extractall(target_dir)

        return {
            "status": "success",
            "addon_id": addon_id,
            "target_dir": target_dir,
            "sha256": actual_sha256
        }
    except Exception as exc:
        logger.error("Failed to install community addon %s: %s", addon_id, exc)
        return {"status": "error", "error": str(exc)}


def _get_modpacks_file() -> Path:
    return Path(get_config_dir()) / "modpacks.json"


def _load_modpacks_json() -> List[Dict[str, Any]]:
    mp_file = _get_modpacks_file()
    if not mp_file.exists():
        return []
    try:
        with open(mp_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        return []
    except Exception as e:
        logger.warning("Error reading modpacks.json: %s", e)
        return []


def _save_modpacks_json(packs: List[Dict[str, Any]]) -> None:
    mp_file = _get_modpacks_file()
    mp_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = mp_file.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(packs, f, indent=4, ensure_ascii=False)
    os.replace(temp_file, mp_file)


def _get_modpack_dir(pack_id: str) -> Path:
    safe_id = os.path.basename(str(pack_id or "").strip())
    if not safe_id or safe_id in {".", ".."}:
        raise ValueError("Invalid modpack identifier.")
    p = Path(get_config_dir()) / "modpacks" / safe_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _unlink_modpack_installation(inst_id: str) -> None:
    try:
        packs = _load_modpacks_json()
        changed = False
        for p in packs:
            if p.get("linked_installation_id") == inst_id:
                p["linked_installation_id"] = None
                changed = True
        if changed:
            _save_modpacks_json(packs)
    except Exception as exc:
        logger.warning("Error unlinking modpack for deleted installation %s: %s", inst_id, exc)


def handle_instances_list(payload):
    config = load_launcher_config()
    installations = config.get("installations", [])
    packs = _load_modpacks_json()

    # Link modpack icons to installations if they are associated with a modpack
    inst_results = []
    for inst in installations:
        inst_copy = dict(inst)
        inst_id = inst.get("id", "")
        # Find if this installation is linked to a modpack (prioritize exact link/id before name matching)
        linked_pack = (
            next((p for p in packs if p.get("linked_installation_id") == inst_id), None)
            or next((p for p in packs if inst.get("modpack_id") and p.get("id") == inst.get("modpack_id")), None)
            or next((p for p in packs if inst_id == f"inst-{p.get('id')}" or (inst.get("game_directory") and str(p.get("id")) in str(inst.get("game_directory")))), None)
            or next((p for p in packs if p.get("linked_installation_id") is None and inst.get("name") and p.get("name", "").strip().lower() == inst.get("name", "").strip().lower()), None)
        )
        if linked_pack:
            # Check if linked pack has an icon
            pack_icon = Path(get_config_dir()) / "modpacks" / linked_pack.get("id", "") / "icon.png"
            if pack_icon.exists():
                curr_icon = inst_copy.get("icon") or ""
                # If installation icon is default grass_block or not set, inherit modpack icon
                if not curr_icon or "grass_block" in curr_icon:
                    inst_copy["icon"] = str(pack_icon)
            elif linked_pack.get("icon_path") and os.path.exists(linked_pack.get("icon_path")):
                curr_icon = inst_copy.get("icon") or ""
                if not curr_icon or "grass_block" in curr_icon:
                    inst_copy["icon"] = str(linked_pack.get("icon_path"))

        # Fallback: check game_directory/icon.png directly if still default icon
        curr_icon = inst_copy.get("icon") or ""
        if (not curr_icon or "grass_block" in curr_icon) and inst.get("game_directory"):
            direct_icon = Path(inst["game_directory"]) / "icon.png"
            if direct_icon.exists():
                inst_copy["icon"] = str(direct_icon)
        inst_results.append(inst_copy)

    return {
        "status": "success",
        "success": True,
        "data": {"instances": inst_results, "installations": inst_results},
        "instances": inst_results,
        "installations": inst_results,
    }


def handle_instance_create(payload: Dict[str, Any]) -> Dict[str, Any]:
    cm = get_config_manager()
    inst_id = payload.get("id") or str(uuid.uuid4())
    name = payload.get("name") or "New Installation"
    version = payload.get("version") or "26.3"
    loader = payload.get("loader") or "Vanilla"
    icon = payload.get("icon") or "icons/grass_block_side.png"

    inst_type = payload.get("type")
    if not inst_type:
        lower_v = str(version).lower()
        lower_l = str(loader).lower()
        if lower_l in ("fabric", "forge", "neoforge", "quilt") or "fabric" in lower_v or "forge" in lower_v:
            inst_type = "modded"
        elif "snapshot" in lower_v or "w" in lower_v:
            inst_type = "snapshot"
        else:
            inst_type = "release"

    min_ram = payload.get("min_ram_mb") or payload.get("ram_min") or payload.get("min_ram")
    max_ram = payload.get("max_ram_mb") or payload.get("ram_max") or payload.get("max_ram") or payload.get("ram_mb")

    new_inst = {
        "id": inst_id,
        "name": name,
        "version": version,
        "loader": loader,
        "type": inst_type,
        "icon": icon,
        "java_executable": payload.get("java_executable") or payload.get("java_path") or "",
        "jvm_arguments": payload.get("jvm_arguments") or payload.get("jvm_args") or "",
        "min_ram_mb": int(min_ram) if min_ram is not None else None,
        "max_ram_mb": int(max_ram) if max_ram is not None else None,
        "resolution_width": payload.get("resolution_width") or payload.get("resolution_w") or 854,
        "resolution_height": payload.get("resolution_height") or payload.get("resolution_h") or 480,
        "game_directory": payload.get("game_directory") or payload.get("game_dir") or "",
        "last_played": payload.get("last_played") or "Never",
        "created": payload.get("created") or datetime.now().strftime("%Y-%m-%d"),
    }

    with _config_lock:
        cfg = cm.load()
        inst_list = cfg.get("installations", [])
        inst_list.append(new_inst)
        cfg["installations"] = inst_list
        cm.save(cfg)

    emit_event("config_changed", {"key": "installations", "value": inst_list})
    return {
        "status": "success",
        "success": True,
        "data": new_inst,
        "instance": new_inst,
    }


def handle_instance_update(payload: Dict[str, Any]) -> Dict[str, Any]:
    cm = get_config_manager()
    inst_id = payload.get("id") or payload.get("instance_id")
    if not inst_id:
        raise ValueError("Missing installation id")
    updates = payload.get("updates") if isinstance(payload.get("updates"), dict) else payload

    updated_inst = None
    with _config_lock:
        cfg = cm.load()
        inst_list = cfg.get("installations", [])
        for inst in inst_list:
            if inst.get("id") == inst_id:
                for k, v in updates.items():
                    if k not in ("id", "instance_id", "updates"):
                        inst[k] = v
                if "java_path" in updates:
                    inst["java_executable"] = updates["java_path"]
                if "jvm_args" in updates:
                    inst["jvm_arguments"] = updates["jvm_args"]
                if "min_ram_mb" in updates or "ram_min" in updates:
                    inst["min_ram_mb"] = updates.get("min_ram_mb") or updates.get("ram_min")
                if "max_ram_mb" in updates or "ram_max" in updates or "ram_mb" in updates:
                    inst["max_ram_mb"] = updates.get("max_ram_mb") or updates.get("ram_max") or updates.get("ram_mb")
                if "resolution_w" in updates:
                    inst["resolution_width"] = updates["resolution_w"]
                if "resolution_h" in updates:
                    inst["resolution_height"] = updates["resolution_h"]
                if "game_dir" in updates:
                    inst["game_directory"] = updates["game_dir"]
                updated_inst = dict(inst)
                break
        if updated_inst is None:
            raise ValueError(f"Installation {inst_id} not found")
        cm.save(cfg)

    # If icon was updated, propagate to any linked modpack
    new_icon = updates.get("icon")
    if new_icon:
        try:
            with _config_lock:
                packs = _load_modpacks_json()
                pack_updated = False
                for p in packs:
                    if p.get("linked_installation_id") == inst_id or (updated_inst.get("modpack_id") and p.get("id") == updated_inst.get("modpack_id")):
                        p["icon"] = str(new_icon)
                        p["icon_path"] = str(new_icon)
                        pack_updated = True
                if pack_updated:
                    _save_modpacks_json(packs)
                    emit_event("modpacks_changed", {"modpacks": packs})
        except Exception as exc:
            logger.warning("Failed to propagate installation icon to linked modpack: %s", exc)

    emit_event("config_changed", {"key": "installations", "value": inst_list})
    return {
        "status": "success",
        "success": True,
        "data": updated_inst,
        "instance": updated_inst,
    }


def handle_instance_delete(payload: Dict[str, Any]) -> Dict[str, Any]:
    cm = get_config_manager()
    inst_id = payload.get("id") or payload.get("instance_id")
    if not inst_id:
        raise ValueError("Missing installation id")

    with _config_lock:
        cfg = cm.load()
        inst_list = cfg.get("installations", [])
        cfg["installations"] = [inst for inst in inst_list if inst.get("id") != inst_id]
        cm.save(cfg)

    _unlink_modpack_installation(inst_id)
    emit_event("config_changed", {"key": "installations", "value": cfg["installations"]})
    return {"status": "success", "success": True, "deleted_id": inst_id}


def handle_instance_duplicate(payload: Dict[str, Any]) -> Dict[str, Any]:
    cm = get_config_manager()
    inst_id = payload.get("id") or payload.get("instance_id")
    if not inst_id:
        raise ValueError("Missing installation id")

    new_inst = None
    with _config_lock:
        cfg = cm.load()
        inst_list = cfg.get("installations", [])
        for inst in inst_list:
            if inst.get("id") == inst_id:
                new_id = str(uuid.uuid4())
                new_inst = dict(inst)
                new_inst["id"] = new_id
                new_inst["name"] = f"{inst.get('name', 'Installation')} (Copy)"
                new_inst["created"] = datetime.now().strftime("%Y-%m-%d")
                inst_list.append(new_inst)
                break
        if new_inst is None:
            raise ValueError(f"Installation with id {inst_id} not found")
        cm.save(cfg)

    emit_event("config_changed", {"key": "installations", "value": inst_list})
    return {
        "status": "success",
        "success": True,
        "new_id": new_inst["id"],
        "data": new_inst,
        "instance": new_inst,
    }


def handle_versions_list(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from nlc.core.versions import get_versions_for_loader
    payload = payload or {}
    loader = payload.get("loader") or "Vanilla"
    include_snapshots = bool(payload.get("include_snapshots", False))
    data = get_versions_for_loader(loader=loader, include_snapshots=include_snapshots)
    return {
        "status": "success",
        "loader": data["loader"],
        "releases": data["releases"],
        "snapshots": data["snapshots"],
        "latest_release": data.get("latest_release", ""),
        "latest_snapshot": data.get("latest_snapshot", ""),
        "versions": data["all"] if include_snapshots else data["releases"],
        "data": data,
    }


def handle_loaders_list(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from nlc.core.versions import get_available_loaders, get_modpack_loaders
    return {
        "status": "success",
        "loaders": get_available_loaders(),
        "modpack_loaders": get_modpack_loaders(),
        "data": {
            "loaders": get_available_loaders(),
            "modpack_loaders": get_modpack_loaders(),
        },
    }


def handle_modpack_update(payload: Dict[str, Any]) -> Dict[str, Any]:
    pack_id = payload.get("pack_id") or payload.get("id")
    if not pack_id:
        raise ValueError("Missing pack_id")

    with _config_lock:
        packs = _load_modpacks_json()
        target = next((p for p in packs if p.get("id") == pack_id), None)
        if not target:
            raise ValueError(f"Modpack not found: {pack_id}")

        if "name" in payload and payload["name"]:
            target["name"] = str(payload["name"]).strip()
        if "loader" in payload and payload["loader"]:
            target["loader"] = str(payload["loader"]).strip().lower()
        if "version" in payload and payload["version"]:
            target["mc_version"] = str(payload["version"]).strip()
            target["version"] = str(payload["version"]).strip()
        if "pack_release" in payload:
            target["pack_release"] = str(payload["pack_release"]).strip()

        _save_modpacks_json(packs)

    return {"status": "success", "success": True, "pack": target}


def handle_modpacks_list(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    packs = _load_modpacks_json()

    # Auto-repair pass for previously misnamed or misclassified modpacks
    modified = False
    for p in packs:
        pack_id = p.get("id", "")
        p_name = p.get("name", "")
        # Fix known release tags as names
        if p_name == "2.4.7 SERVER":
            p["name"] = "Sodium Plus"
            p["pack_release"] = "2.4.7 SERVER"
            modified = True
        elif p_name == "fp" and p.get("mc_version") == "26.3":
            p["name"] = "Fabulously Polished"
            p["pack_release"] = "4.4.0"
            modified = True

        mods_dir = Path(get_config_dir()) / "modpacks" / pack_id / "mods"
        if mods_dir.is_dir():
            jar_names = [e.name.lower() for e in os.scandir(mods_dir) if e.is_file() and e.name.lower().endswith(".jar")]
            # Check for Quilt indicators
            if p.get("loader") == "fabric":
                if any("quilt" in j or "qsl" in j for j in jar_names):
                    p["loader"] = "quilt"
                    modified = True
            # Check for NeoForge indicators
            elif p.get("loader") in ("forge", "vanilla"):
                if any("neoforge" in j for j in jar_names):
                    p["loader"] = "neoforge"
                    modified = True

    if modified:
        try:
            with _config_lock:
                _save_modpacks_json(packs)
        except Exception as e:
            logger.debug("Failed saving auto-repaired modpacks.json: %s", e)
    cfg = load_launcher_config()
    installations = {i.get("id"): i.get("name", "Unnamed") for i in cfg.get("installations", [])}

    enriched_packs = []
    for p in packs:
        p_copy = dict(p)
        pack_id = p.get("id", "")
        mods_dir = Path(get_config_dir()) / "modpacks" / pack_id / "mods"
        mod_count = 0
        if mods_dir.is_dir():
            mod_count = len([e for e in os.scandir(mods_dir) if e.is_file() and (e.name.lower().endswith(".jar") or e.name.lower().endswith(".jar.disabled"))])
        else:
            mod_count = len(p.get("mods", []))

        linked_id = p.get("linked_installation_id")
        linked_name = installations.get(linked_id, "") if linked_id else ""
        p_copy["mod_count"] = mod_count
        p_copy["is_linked"] = bool(linked_id)
        p_copy["linked_inst_id"] = linked_id or ""
        p_copy["linked_installation_id"] = linked_id or ""
        p_copy["linked_inst_name"] = linked_name
        p_copy["version"] = p.get("version") or p.get("mc_version") or "1.21.1"
        p_copy["pack_release"] = p.get("pack_release") or p.get("version_name") or "1.0.0"
        p_copy["thumbnail"] = p.get("thumbnail") or ""
        p_copy["icon_letter"] = (p.get("name", "M")[:1]).upper()

        # Resolve real modpack icon artwork
        icon_path = ""
        possible_icon = Path(get_config_dir()) / "modpacks" / pack_id / "icon.png"
        if possible_icon.exists():
            icon_path = str(possible_icon)
        elif p.get("icon") and os.path.exists(p.get("icon")):
            icon_path = str(p.get("icon"))
        elif p.get("icon_path") and os.path.exists(p.get("icon_path")):
            icon_path = str(p.get("icon_path"))
        elif p.get("thumbnail") and os.path.exists(p.get("thumbnail")):
            icon_path = str(p.get("thumbnail"))

        p_copy["icon_path"] = icon_path
        p_copy["has_icon"] = bool(icon_path)
        enriched_packs.append(p_copy)

    return {
        "status": "success",
        "success": True,
        "data": enriched_packs,
        "modpacks": enriched_packs,
    }


def handle_modpack_create(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("Modpack name cannot be empty")
    loader = payload.get("loader") or "fabric"
    mc_version = payload.get("mc_version") or payload.get("version") or "26.3"
    pack_id = payload.get("id") or str(uuid.uuid4())

    pack_dir = _get_modpack_dir(pack_id)
    (pack_dir / "mods").mkdir(parents=True, exist_ok=True)

    new_pack = {
        "id": pack_id,
        "name": name,
        "loader": loader,
        "mc_version": mc_version,
        "version": mc_version,
        "description": payload.get("description", ""),
        "source": payload.get("source", "Custom"),
        "total_mods": 0,
        "active_mods": 0,
        "is_linked": False,
        "linked_installation_id": "",
        "version_name": payload.get("version_name", "1.0.0"),
        "pack_release": payload.get("pack_release", "1.0.0"),
        "mods": [],
        "created": datetime.now().strftime("%Y-%m-%d"),
    }

    with _config_lock:
        packs = _load_modpacks_json()
        packs.append(new_pack)
        _save_modpacks_json(packs)

    emit_event("modpacks_changed", {"modpacks": packs})
    return {
        "status": "success",
        "success": True,
        "data": new_pack,
        "pack": new_pack,
    }


def handle_modpack_link(payload: Dict[str, Any]) -> Dict[str, Any]:
    pack_id = payload.get("pack_id") or payload.get("modpack_id")
    inst_id = payload.get("installation_id") or payload.get("inst_id")
    if not pack_id:
        raise ValueError("Missing pack_id")

    with _config_lock:
        packs = _load_modpacks_json()
        found = False
        target_pack = None
        for p in packs:
            if p.get("id") == pack_id:
                p["linked_installation_id"] = inst_id if inst_id else None
                found = True
                target_pack = {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "loader": p.get("loader", "Fabric"),
                    "version": p.get("version", p.get("mc_version", "1.21.1")),
                    "description": p.get("description", ""),
                    "source": p.get("source", "Modrinth"),
                    "total_mods": len(p.get("mods", [])),
                    "active_mods": len([m for m in p.get("mods", []) if m.get("enabled", True)]),
                    "is_linked": bool(p.get("linked_installation_id")),
                    "linked_installation_id": p.get("linked_installation_id") or "",
                }
                break
        if not found:
            raise ValueError(f"Modpack {pack_id} not found")
        _save_modpacks_json(packs)

    emit_event("modpacks_changed", {"modpacks": packs})
    return {"status": "success", "success": True, "data": target_pack, "pack": target_pack}


def handle_modpack_delete(payload: Dict[str, Any]) -> Dict[str, Any]:
    pack_id = payload.get("pack_id") or payload.get("modpack_id")
    if not pack_id:
        raise ValueError("Missing pack_id")

    with _config_lock:
        packs = _load_modpacks_json()
        packs = [p for p in packs if p.get("id") != pack_id]
        _save_modpacks_json(packs)

    try:
        pack_dir = Path(get_config_dir()) / "modpacks" / os.path.basename(str(pack_id))
        if pack_dir.exists() and pack_dir.is_dir():
            shutil.rmtree(pack_dir, ignore_errors=True)
    except Exception as exc:
        logger.warning("Error deleting modpack directory: %s", exc)

    emit_event("modpacks_changed", {"modpacks": packs})
    return {"status": "success", "success": True, "deleted_id": pack_id}


def handle_modpack_export(payload: Dict[str, Any]) -> Dict[str, Any]:
    from nlc.core.instances import export_modpack_to_mrpack, export_modpack_to_zip

    pack_id = payload.get("pack_id") or payload.get("modpack_id")
    export_fmt = (payload.get("format") or "mrpack").lower()
    if not pack_id:
        raise ValueError("Missing pack_id for export")

    packs = _load_modpacks_json()
    pack_meta = next((p for p in packs if p.get("id") == pack_id), None)
    if not pack_meta:
        pack_meta = {"name": pack_id, "id": pack_id, "loader": "fabric", "mc_version": "1.21.1"}

    pack_dir = Path(get_config_dir()) / "modpacks" / os.path.basename(str(pack_id))
    pack_dir.mkdir(parents=True, exist_ok=True)

    out_path = payload.get("output_path")
    if not out_path:
        exports_dir = Path(get_config_dir()) / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(c for c in pack_meta.get("name", pack_id) if c.isalnum() or c in ("-", "_")).strip() or pack_id
        ext = "mrpack" if export_fmt == "mrpack" else "zip"
        out_path = str(exports_dir / f"{safe_name}.{ext}")

    if export_fmt == "mrpack":
        res_path = export_modpack_to_mrpack(
            pack_dir=pack_dir,
            output_path=out_path,
            pack_meta=pack_meta,
            modpack_name=pack_meta.get("name"),
            game_version=pack_meta.get("mc_version") or pack_meta.get("version"),
            loader=pack_meta.get("loader"),
        )
    else:
        res_path = export_modpack_to_zip(
            pack_dir=pack_dir,
            output_path=out_path,
            pack_meta=pack_meta,
        )

    return {
        "status": "success",
        "success": True,
        "path": res_path,
        "export_path": res_path,
        "data": {"path": res_path, "export_path": res_path},
    }


def handle_modpack_mods_list(payload: Dict[str, Any]) -> Dict[str, Any]:
    pack_id = payload.get("pack_id") or payload.get("instance_id") or payload.get("installation_id") or ""
    mods = handle_mods_list_installed({"instance_id": pack_id})
    formatted = []
    for idx, m in enumerate(mods):
        fname = m.get("filename") or m.get("file") or ""
        is_active = not fname.lower().endswith(".disabled")
        size_bytes = m.get("size_bytes", 0)
        size_text = f"{size_bytes / 1024:.1f} KB" if size_bytes < 1024 * 1024 else f"{size_bytes / (1024 * 1024):.1f} MB"
        formatted.append({
            "id": str(idx + 1),
            "name": m.get("name", fname),
            "filename": fname,
            "size_text": size_text,
            "size": size_text,
            "is_active": is_active,
            "active": is_active,
            "version": m.get("version", ""),
            "icon_path": m.get("icon_path", ""),
        })
    return {
        "status": "success",
        "success": True,
        "data": formatted,
        "mods": formatted,
    }


def handle_modpack_mods_toggle(payload: Dict[str, Any]) -> Dict[str, Any]:
    pack_id = payload.get("pack_id") or payload.get("instance_id") or ""
    filename = payload.get("filename") or payload.get("file") or ""
    enabled = payload.get("enabled", payload.get("is_active"))
    res = handle_mods_toggle_enabled({"instance_id": pack_id, "filename": filename, "enabled": enabled})
    return {
        "status": "success",
        "success": True,
        "data": res,
    }


def handle_modpack_mods_remove(payload: Dict[str, Any]) -> Dict[str, Any]:
    pack_id = payload.get("pack_id") or payload.get("instance_id") or ""
    filename = payload.get("filename") or payload.get("file") or payload.get("mod_id") or ""
    if not filename:
        raise ValueError("Missing filename to remove")

    mods_dir = _resolve_instance_mods_dir(pack_id)
    target = os.path.join(mods_dir, filename)
    if os.path.exists(target):
        os.remove(target)
    elif os.path.exists(target + ".disabled"):
        os.remove(target + ".disabled")
    elif filename.lower().endswith(".disabled") and os.path.exists(target[:-9]):
        os.remove(target[:-9])

    return {
        "status": "success",
        "success": True,
        "removed": filename,
    }


def _safe_resolve_archive_path(
    dest_dir: Union[str, Path],
    subpath: Union[str, Path, zipfile.ZipInfo],
    entry_name: Optional[str] = None,
) -> Path:
    if isinstance(subpath, zipfile.ZipInfo):
        is_symlink = ((subpath.external_attr >> 16) & 0o170000) == 0o120000
        if is_symlink:
            raise ValueError(f"Zip-Slip path traversal detected: {subpath.filename}")
        raw_path = subpath.filename
        name_for_err = entry_name or subpath.filename
    else:
        raw_path = str(subpath)
        name_for_err = entry_name or raw_path

    dest_canonical = os.path.realpath(os.path.abspath(str(dest_dir)))
    norm = raw_path.replace("\\", "/").strip()
    if not norm or norm == "." or norm.startswith("/"):
        raise ValueError(f"Zip-Slip path traversal detected: {name_for_err}")
    if re.match(r"^[a-zA-Z]:", norm):
        raise ValueError(f"Zip-Slip path traversal detected: {name_for_err}")

    candidate = os.path.realpath(os.path.abspath(os.path.join(dest_canonical, norm)))
    try:
        common = os.path.commonpath([dest_canonical, candidate])
    except ValueError as err:
        raise ValueError(f"Zip-Slip path traversal detected: {name_for_err}") from err

    if common != dest_canonical or candidate == dest_canonical:
        raise ValueError(f"Zip-Slip path traversal detected: {name_for_err}")

    return Path(candidate)


def handle_modpack_import(payload: Dict[str, Any]) -> Dict[str, Any]:
    archive_path = payload.get("archive_path") or payload.get("file_path") or payload.get("path")
    if not archive_path or not os.path.exists(archive_path):
        raise FileNotFoundError(f"Archive file not found: {archive_path}")

    custom_name = payload.get("name")
    api_key = payload.get("api_key")
    if api_key:
        api_key = vault_decrypt(api_key)
    else:
        try:
            cm = get_config_manager()
            cfg = cm.load()
            cf_key = cfg.get("addons", {}).get("curseforge_api_key")
            if cf_key:
                api_key = vault_decrypt(cf_key)
        except Exception:
            pass

    pack_id = str(uuid.uuid4())
    modpack_root = Path(get_config_dir()) / "modpacks"
    modpack_root.mkdir(parents=True, exist_ok=True)
    pack_dir = modpack_root / pack_id
    pack_dir.mkdir(parents=True, exist_ok=True)

    try:
        mods_dir = pack_dir / "mods"
        mods_dir.mkdir(parents=True, exist_ok=True)

        loader = "fabric"
        mc_version = "1.21.1"
        pack_name = custom_name or os.path.splitext(os.path.basename(archive_path))[0]
        installed_files = []

        with zipfile.ZipFile(archive_path, "r") as zf:
            namelist = zf.namelist()

            for member in zf.infolist():
                is_symlink = ((member.external_attr >> 16) & 0o170000) == 0o120000
                if is_symlink:
                    raise ValueError(f"Zip-Slip path traversal detected: {member.filename}")
                norm_m = member.filename.replace("\\", "/").strip()
                clean_m = norm_m.rstrip("/")
                if not clean_m:
                    if member.is_dir() or norm_m.endswith("/"):
                        continue
                    raise ValueError(f"Zip-Slip path traversal detected: {member.filename}")
                if clean_m == ".":
                    if member.is_dir() or norm_m.endswith("/"):
                        continue
                    raise ValueError(f"Zip-Slip path traversal detected: {member.filename}")
                if clean_m.startswith("/") or re.match(r"^[a-zA-Z]:", clean_m):
                    raise ValueError(f"Zip-Slip path traversal detected: {member.filename}")
                if ".." in clean_m.split("/"):
                    try:
                        cand = os.path.realpath(os.path.abspath(os.path.join(os.path.realpath(str(pack_dir)), clean_m)))
                        if os.path.commonpath([os.path.realpath(str(pack_dir)), cand]) != os.path.realpath(str(pack_dir)):
                            raise ValueError(f"Zip-Slip path traversal detected: {member.filename}")
                    except ValueError as exc:
                        raise ValueError(f"Zip-Slip path traversal detected: {member.filename}") from exc

            if "modrinth.index.json" in namelist:
                manifest = json.loads(zf.read("modrinth.index.json").decode("utf-8-sig"))
                m_name = manifest.get("name")
                if custom_name:
                    pack_name = custom_name
                elif m_name and not _is_version_like_string(m_name):
                    pack_name = m_name
                else:
                    pack_name = os.path.splitext(os.path.basename(archive_path))[0]

                deps = manifest.get("dependencies", {})
                mc_version = deps.get("minecraft", "1.21.1")
                loader = detect_loader_from_modpack(dependencies=deps, files=manifest.get("files", []))

                for member in zf.infolist():
                    norm_filename = member.filename.replace("\\", "/")
                    if member.is_dir() or norm_filename.endswith("/"):
                        continue
                    if norm_filename.startswith("overrides/"):
                        rel_path = norm_filename[len("overrides/"):]
                        target_file = _safe_resolve_archive_path(pack_dir, rel_path, entry_name=member.filename)
                        target_file.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as src, open(target_file, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                    elif norm_filename.startswith("client-overrides/"):
                        rel_path = norm_filename[len("client-overrides/"):]
                        target_file = _safe_resolve_archive_path(pack_dir, rel_path, entry_name=member.filename)
                        target_file.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as src, open(target_file, "wb") as dst:
                            shutil.copyfileobj(src, dst)

                session = get_session()
                for f in manifest.get("files", []):
                    env = f.get("env", {})
                    if env.get("client") == "unsupported":
                        continue
                    file_path = f.get("path")
                    if not file_path:
                        continue
                    target = _safe_resolve_archive_path(pack_dir, file_path, entry_name=file_path)
                    downloads = f.get("downloads", [])
                    if downloads:
                        dl_url = downloads[0]
                        target.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            r = session.get(dl_url, timeout=30)
                            if r.status_code == 200:
                                with open(target, "wb") as out_f:
                                    out_f.write(r.content)
                                installed_files.append({"filename": os.path.basename(file_path), "path": file_path})
                        except Exception as exc:
                            logger.warning("Failed downloading modpack file %s: %s", dl_url, exc)

            elif "manifest.json" in namelist:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8-sig"))
                m_name = manifest.get("name")
                if custom_name:
                    pack_name = custom_name
                elif m_name and not _is_version_like_string(m_name):
                    pack_name = m_name
                else:
                    pack_name = os.path.splitext(os.path.basename(archive_path))[0]

                mc_info = manifest.get("minecraft", {})
                mc_version = mc_info.get("version", "1.21.1")
                mod_loaders = mc_info.get("modLoaders", [])
                for ml in mod_loaders:
                    ml_id = str(ml.get("id", "")).lower()
                    if "quilt" in ml_id:
                        loader = "quilt"
                        break
                    elif "neoforge" in ml_id:
                        loader = "neoforge"
                        break
                    elif "forge" in ml_id:
                        loader = "forge"
                        break
                    elif "fabric" in ml_id:
                        loader = "fabric"
                        break

                overrides_dir_name = manifest.get("overrides", "overrides")
                norm_overrides = str(overrides_dir_name).replace("\\", "/").strip().strip("/")
                if ".." in norm_overrides.split("/") or norm_overrides.startswith("/") or re.match(r"^[a-zA-Z]:", norm_overrides):
                    raise ValueError(f"Zip-Slip path traversal detected: {overrides_dir_name}")
                prefix = f"{norm_overrides}/"
                for member in zf.infolist():
                    norm_filename = member.filename.replace("\\", "/")
                    if member.is_dir() or norm_filename.endswith("/"):
                        continue
                    if norm_filename.startswith(prefix):
                        rel_path = norm_filename[len(prefix):]
                        target_file = _safe_resolve_archive_path(pack_dir, rel_path, entry_name=member.filename)
                        target_file.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as src, open(target_file, "wb") as dst:
                            shutil.copyfileobj(src, dst)

                if api_key:
                    session = get_session()
                    headers = {"x-api-key": api_key}
                    for rec in manifest.get("files", []):
                        pid = rec.get("projectID")
                        fid = rec.get("fileID")
                        if pid and fid:
                            try:
                                dl_resp = session.get(f"https://api.curseforge.com/v1/mods/{pid}/files/{fid}/download-url", headers=headers, timeout=15)
                                if dl_resp.status_code == 200:
                                    dl_url = dl_resp.json().get("data")
                                    if dl_url:
                                        fname = os.path.basename(urllib.parse.urlparse(dl_url).path) or f"cf_{pid}_{fid}.jar"
                                        target_cf = _safe_resolve_archive_path(mods_dir, fname, entry_name=fname)
                                        r_file = session.get(dl_url, timeout=30)
                                        if r_file.status_code == 200:
                                            with open(target_cf, "wb") as out_f:
                                                out_f.write(r_file.content)
                                            installed_files.append({"filename": fname, "project_id": pid, "file_id": fid})
                            except Exception as exc:
                                logger.warning("Error fetching CurseForge mod %s/%s: %s", pid, fid, exc)
            else:
                for member in zf.infolist():
                    norm_filename = member.filename.replace("\\", "/")
                    if member.is_dir() or norm_filename.endswith("/"):
                        continue
                    fname_lower = norm_filename.lower()
                    if fname_lower.endswith(".jar") or fname_lower.endswith(".jar.disabled"):
                        base_name = os.path.basename(norm_filename)
                        target_file = _safe_resolve_archive_path(mods_dir, base_name, entry_name=member.filename)
                        with zf.open(member) as src, open(target_file, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        installed_files.append({"filename": base_name})
                    else:
                        target_file = _safe_resolve_archive_path(pack_dir, member.filename, entry_name=member.filename)
                        target_file.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as src, open(target_file, "wb") as dst:
                            shutil.copyfileobj(src, dst)

        new_pack = {
            "id": pack_id,
            "name": pack_name,
            "loader": loader,
            "mc_version": mc_version,
            "version": mc_version,
            "description": f"Imported from {os.path.basename(archive_path)}",
            "source": "import",
            "total_mods": len(installed_files),
            "active_mods": len(installed_files),
            "is_linked": False,
            "linked_installation_id": "",
            "version_name": "1.0.0",
            "pack_release": "1.0.0",
            "mods": installed_files,
            "created": datetime.now().strftime("%Y-%m-%d"),
        }

        with _config_lock:
            packs = _load_modpacks_json()
            packs.append(new_pack)
            _save_modpacks_json(packs)

        emit_event("modpacks_changed", {"modpacks": packs})
        return {
            "status": "success",
            "success": True,
            "data": new_pack,
            "pack": new_pack,
        }
    except Exception:
        if pack_dir.exists():
            shutil.rmtree(pack_dir, ignore_errors=True)
        raise


def handle_modpack_install_mod(payload: Dict[str, Any]) -> Dict[str, Any]:
    pack_id = payload.get("pack_id") or payload.get("instance_id") or ""
    if not pack_id:
        raise ValueError("Missing pack_id")

    mods_dir = Path(_resolve_instance_mods_dir(pack_id))
    mods_dir.mkdir(parents=True, exist_ok=True)

    file_path = payload.get("file_path")
    url = payload.get("url")
    filename = payload.get("filename")
    project_id = payload.get("project_id")

    if file_path and os.path.exists(file_path):
        fname = filename or os.path.basename(file_path)
        shutil.copy2(file_path, str(mods_dir / fname))
        return {"status": "success", "filename": fname, "path": str(mods_dir / fname)}
    elif url:
        fname = filename or os.path.basename(urllib.parse.urlparse(url).path) or f"mod_{int(time.time())}.jar"
        session = get_session()
        r = session.get(url, timeout=30)
        r.raise_for_status()
        with open(mods_dir / fname, "wb") as f:
            f.write(r.content)
        return {"status": "success", "filename": fname, "path": str(mods_dir / fname)}
    elif project_id:
        res = handle_modrinth_install_artifact({
            "project_id": project_id,
            "version_id": payload.get("version_id"),
            "target_dest": pack_id,
        })
        return res
    else:
        raise ValueError("Must provide file_path, url, or project_id to install mod")


ACTION_HANDLERS = {
    # Launch Lifecycle
    "launch_game": handle_launch_game,
    "launch_game_mock": lambda p: handle_launch_game({**p, "mock": True}),
    "kill_game": handle_kill_game,
    "cancel_launch": handle_kill_game,

    # Accounts
    "accounts_list": handle_accounts_list,
    "accounts_select": handle_accounts_select,
    "account_select": handle_accounts_select,
    "accounts_auth_microsoft_start": handle_accounts_auth_microsoft_start,
    "start_microsoft_auth": handle_accounts_auth_microsoft_start,
    "accounts_auth_elyby": handle_accounts_auth_elyby,
    "login_elyby": handle_accounts_auth_elyby,
    "accounts_auth_offline": handle_accounts_auth_offline,
    "accounts_remove": handle_accounts_remove,
    "remove_account": handle_accounts_remove,
    "gh_skin_sync": handle_gh_skin_sync,
    "skin_sync": handle_gh_skin_sync,

    # Discord RPC Status & Screen
    "get_discord_status": lambda p: _discord_rpc_manager.get_status(),
    "discord_status": lambda p: _discord_rpc_manager.get_status(),
    "discord_set_screen": handle_discord_set_screen,
    "discord_set_tab": handle_discord_set_screen,
    "agent_shutdown": handle_agent_shutdown,

    # System Utilities
    "system_open_url": handle_system_open_url,
    "open_url": handle_system_open_url,
    "system_copy_clipboard": handle_system_copy_clipboard,
    "copy_clipboard": handle_system_copy_clipboard,
    "system_open_folder": handle_system_open_folder,
    "open_folder": handle_system_open_folder,

    # Config Persistence
    "config_get": handle_config_get,
    "config_set": handle_config_set,
    "config_update": handle_config_set,
    "config_reset_defaults": handle_config_reset_defaults,

    # Mods Management
    "mods_list_installed": handle_mods_list_installed,
    "mods_toggle_enabled": handle_mods_toggle_enabled,
    "mods_toggle": handle_mods_toggle_enabled,

    # Modrinth Discovery & Installation
    "modrinth_search": handle_modrinth_search,
    "modrinth_project_details": handle_modrinth_project_details,
    "modrinth_install_artifact": handle_modrinth_install_artifact,
    "search_mods": handle_search_mods,

    # Locker: Skins, Capes & Wallpapers
    "skin_get_current": handle_skin_get_current,
    "skin_set_custom": handle_skin_set_custom,
    "skin_flush_mojang": handle_skin_flush_mojang,
    "skin_render_frame": handle_skin_render_frame,
    "skin_set_model": handle_skin_model_set,
    "skin_model_set": handle_skin_model_set,
    "skin_thumbnail_get": handle_skin_thumbnail_get,
    "skin_steal": handle_skin_steal,
    "skin_steal_preview": handle_skin_steal_preview,
    "skin_presets_list": handle_skin_presets_list,
    "capes_list": handle_capes_list,
    "capes_select": handle_capes_select,
    "wallpapers_list": handle_wallpapers_list,
    "wallpapers_set": handle_wallpapers_set,
    "wallpapers_upload": handle_wallpapers_upload,
    "wallpapers_delete": handle_wallpapers_delete,
    "wallpapers_open_folder": handle_wallpapers_open_folder,
    "wallpapers_download": handle_wallpapers_download,

    # Addons & Tools
    "addons_normalize": handle_addons_normalize,
    "addons_set_streamer_mode": handle_addons_set_streamer_mode,
    "addons_get_playtime": handle_addons_get_playtime,
    "addons_reset_playtime": handle_addons_reset_playtime,
    "addons_record_play_session": handle_addons_record_play_session,
    "addons_get_saved_servers": handle_addons_get_saved_servers,
    "addons_add_saved_server": handle_addons_add_saved_server,
    "addons_remove_saved_server": handle_addons_remove_saved_server,
    "addons_list_screenshots": handle_addons_list_screenshots,
    "addons_delete_screenshot": handle_addons_delete_screenshot,
    "server_ping": handle_server_ping,
    "ping_server": handle_server_ping,
    "system_check_updates": handle_system_check_updates,
    "system_apply_update": handle_system_apply_update,
    "diagnostics_get_system_info": handle_diagnostics_get_system_info,
    "diagnostics_get_logs": handle_diagnostics_get_logs,
    "diagnostics_toggle_logging": handle_diagnostics_toggle_logging,
    "list_third_party_addons": handle_list_third_party_addons,
    "run_third_party_addon_action": handle_run_third_party_addon_action,
    "addons_get_community_catalog": handle_addons_get_community_catalog,
    "addons_install_community": handle_addons_install_community,
    "instances_list": handle_instances_list,

    # Instance Management
    "instance_create": handle_instance_create,
    "instance_update": handle_instance_update,
    "instance_delete": handle_instance_delete,
    "instance_duplicate": handle_instance_duplicate,
    "instance_open_folder": handle_system_open_folder,

    # Modpack Management
    "modpacks_list": handle_modpacks_list,
    "modpack_create": handle_modpack_create,
    "modpack_update": handle_modpack_update,
    "modpack_import": handle_modpack_import,
    "modpack_install_mod": handle_modpack_install_mod,
    "modpack_link": handle_modpack_link,
    "modpack_delete": handle_modpack_delete,
    "modpack_export": handle_modpack_export,
    "modpack_mods_list": handle_modpack_mods_list,
    "modpack_mods_toggle": handle_modpack_mods_toggle,
    "modpack_mods_remove": handle_modpack_mods_remove,

    # Minecraft Versions & Loaders
    "versions_list": handle_versions_list,
    "loaders_list": handle_loaders_list,

    # Heartbeat
    "ping": lambda payload: {"status": "success", "data": "pong"},
}


_ASYNC_ACTIONS = {
    "modrinth_install_artifact",
    "modpack_import",
    "modpack_install_mod",
    "system_apply_update",
}
_WORKER_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="AgentWorker")


def _execute_async_action(handler, req_id, payload, action):
    try:
        result = handler(payload)
        send_response(req_id, result=result, error=None)
    except Exception as exc:
        logger.exception("Error executing async action %s: %s", action, exc)
        send_response(
            req_id,
            result={"status": "error", "msg": str(exc)},
            error={"code": "ERR_HANDLER", "message": str(exc)}
        )


def main():
    global _in_request_handling
    init_agent_logging()
    repair_modpack_icons()
    init_discord_rpc()
    with _stdout_lock:
        sys.stdout.write("Agent process started.\n")
        sys.stdout.flush()

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break  # EOF on pipe: Slint frontend terminated

            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                continue

            req_id = request.get("id")
            action = request.get("action")
            payload = request.get("payload", {})
            if payload is None:
                payload = {}

            handler = ACTION_HANDLERS.get(action)
            if handler:
                if action in _ASYNC_ACTIONS:
                    _WORKER_POOL.submit(_execute_async_action, handler, req_id, payload, action)
                else:
                    try:
                        _in_request_handling = True
                        result = handler(payload)
                        send_response(req_id, result=result, error=None)
                        flush_deferred_events()
                    except Exception as exc:
                        _deferred_events.clear()
                        logger.exception("Error executing action %s: %s", action, exc)
                        send_response(
                            req_id,
                            result={"status": "error", "msg": str(exc)},
                            error={"code": "ERR_HANDLER", "message": str(exc)}
                        )
                    finally:
                        _in_request_handling = False
            else:
                send_response(
                    req_id,
                    result={"status": "error", "msg": f"Unknown action: {action}"},
                    error={"code": "ERR_UNKNOWN_ACTION", "message": f"Unknown action: {action}"}
                )

        except KeyboardInterrupt:
            break
        except Exception as exc:
            logger.exception("Unexpected error in agent loop: %s", exc)
            time.sleep(0.1)

    try:
        _WORKER_POOL.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass
    try:
        if _discord_rpc_manager:
            _discord_rpc_manager.stop()
    except Exception:
        pass
    os._exit(0)


if __name__ == "__main__":
    _start_parent_watchdog()
    main()
