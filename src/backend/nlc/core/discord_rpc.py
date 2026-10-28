"""
nlc.core.discord_rpc - Discord Rich Presence integration with safe failure handling,
resilient background reconnection, single-thread serialized presence dispatching,
and rich configuration support.
"""

import logging
import threading
import time
from typing import Callable, Optional, Dict, Any

logger = logging.getLogger(__name__)

DISCORD_CLIENT_ID = "1458526248845443167"
IMGUR_CLIENT_ID = "546c25a59c58ad7"


# Catbox removed: blocked by Discord media proxy
def upload_head_to_imgur(head_png_bytes: bytes, timeout: float = 6.0) -> Optional[str]:
    """
    Uploads a small 32x32 head PNG to Imgur anonymously.
    Returns the direct image link (e.g. https://i.imgur.com/...) or None on error.
    """
    import base64
    import json
    import urllib.request

    url = "https://api.imgur.com/3/image"
    b64_data = base64.b64encode(head_png_bytes).decode("ascii")
    payload = json.dumps({"image": b64_data, "type": "base64"}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Client-ID {IMGUR_CLIENT_ID}",
            "Content-Type": "application/json",
            "User-Agent": "NLC-Launcher/3.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            if res_data.get("success"):
                link = res_data.get("data", {}).get("link")
                if link and str(link).startswith("http"):
                    return str(link)
    except Exception as exc:
        logger.debug("Failed to upload avatar to Imgur: %s", exc)
    return None


def upload_head_to_catbox(head_png_bytes: bytes, timeout: float = 6.0) -> Optional[str]:
    """Alias for head avatar uploader (prioritizes Imgur for Discordbot compatibility)."""
    return upload_head_to_imgur(head_png_bytes, timeout=timeout)


def sync_discord_avatar(profile: Dict[str, Any], config_manager=None) -> Optional[str]:
    """
    Ensures that a public Discord avatar URL is available for the given profile.
    Extracts and uploads the player's head image to Imgur (Discord's primary CDN partner)
    so custom skins and Mojang heads render reliably in Discord Rich Presence without proxy errors.
    Falls back to crafthead.net (Discord-compatible CDN) if Imgur upload fails or before upload.
    """
    import hashlib
    import os

    p_type = (profile.get("type") or "microsoft").lower()
    raw_uuid = str(profile.get("uuid") or "").replace("-", "").strip()
    head_path = profile.get("head_path")
    skin_path = profile.get("skin_path")

    # 1. Ensure local head exists
    if not head_path or not os.path.exists(head_path):
        if skin_path and os.path.exists(skin_path):
            try:
                from PIL import Image
                heads_dir = os.path.join(os.path.dirname(os.path.dirname(skin_path)), "heads")
                os.makedirs(heads_dir, exist_ok=True)
                p_name = "".join(c for c in str(profile.get("name", "player")) if c.isalnum() or c in ("-", "_")) or "head"
                p_id = "".join(c for c in str(profile.get("uuid", "")) if c.isalnum() or c in ("-", "_"))
                out_path = os.path.join(heads_dir, f"{p_name}_{p_id}.png" if p_id else f"{p_name}.png")
                with Image.open(skin_path) as img:
                    img = img.convert("RGBA")
                    head = img.crop((8, 8, 16, 16))
                    if img.width >= 48 and img.height >= 16:
                        hat = img.crop((40, 8, 48, 16))
                        head.paste(hat, (0, 0), hat)
                    head_128 = head.resize((128, 128), Image.Resampling.NEAREST if hasattr(Image, "Resampling") else Image.NEAREST)
                    head_128.save(out_path)
                head_path = out_path
                profile["head_path"] = head_path
            except Exception as exc:
                logger.debug("Failed to extract head from skin for profile %s: %s", profile.get("name"), exc)

    head_bytes = None
    head_hash = None
    if head_path and os.path.exists(head_path):
        try:
            with open(head_path, "rb") as f:
                head_bytes = f.read()
            if head_bytes:
                head_hash = hashlib.sha256(head_bytes).hexdigest()
        except Exception as exc:
            logger.debug("Could not read head image at %s: %s", head_path, exc)

    cached_hash = profile.get("discord_avatar_hash")
    cached_url = profile.get("discord_avatar_url")

    # If cached URL is valid and hash matches (and not an old broken catbox/minotar link)
    if cached_url and str(cached_url).startswith("http") and cached_hash == head_hash and "minotar" not in str(cached_url):
        return cached_url

    # Upload new head image to Imgur (whitelisted and proxied by Discord)
    if head_bytes:
        new_url = upload_head_to_imgur(head_bytes)
        if new_url:
            profile["discord_avatar_hash"] = head_hash
            profile["discord_avatar_url"] = new_url
            if config_manager:
                try:
                    cfg = config_manager.load()
                    profiles = cfg.get("profiles", [])
                    p_uuid = profile.get("uuid")
                    p_name = profile.get("name")
                    for p in profiles:
                        if (p_uuid and p.get("uuid") == p_uuid) or (
                            p.get("name") == p_name and p.get("type") == profile.get("type")
                        ):
                            p["discord_avatar_hash"] = head_hash
                            p["discord_avatar_url"] = new_url
                            break
                    config_manager.save(cfg)
                except Exception as e:
                    logger.debug("Failed to save updated discord_avatar_url to config: %s", e)
            return new_url

    # Fallback to crafthead.net (Discord-compatible Minecraft avatar proxy)
    if len(raw_uuid) == 32:
        return f"https://crafthead.net/helm/{raw_uuid}/128.png"
    p_name = profile.get("name") or "Steve"
    return f"https://crafthead.net/helm/{p_name}/128.png"


class DiscordRPCManager:
    """
    Manages Discord Rich Presence client safely in a worker thread.
    Features:
      - Automatic background reconnect loop (every 15s if disconnected and enabled)
      - Serialized presence updates on dedicated supervisor thread to prevent race conditions
      - Streamer Mode awareness (masks server IP and player username)
      - Configurable detail modes, idle display, session timer, and server address display
    """

    def __init__(
        self,
        client_id: str = DISCORD_CLIENT_ID,
        on_status_change: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.client_id = (client_id or "").strip() or DISCORD_CLIENT_ID
        self.rpc = None
        self.connected = False
        self.enabled = True

        # Customization settings
        self.detail_mode = "Show Version"  # "Show Version", "Show Installation", "Playing Modpack", "Hidden"
        self.show_timer = True
        self.show_idle = True
        self.show_server = True
        self.streamer_mode = False

        # Current player identity
        self.player_name = "Steve"
        self.player_uuid: Optional[str] = None
        self.account_type: Optional[str] = None
        self.custom_avatar_url: Optional[str] = None

        # Current internal activity state
        self._activity_mode = "idle"  # "idle", "launching", "playing"
        self._current_screen: str = "Play"
        self._activity_start: Optional[float] = None
        self._current_version: str = ""
        self._current_loader: str = ""
        self._current_installation: str = ""
        self._current_modpack: Optional[str] = None
        self._current_server: Optional[str] = None
        self._in_game_state: str = "menu"  # "menu", "singleplayer", "multiplayer"

        self._last_state: str = "Idle"
        self._last_details: str = "In Launcher"

        self._lock = threading.RLock()
        self._update_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._dirty_event = threading.Event()
        self._supervisor_thread: Optional[threading.Thread] = None
        self._on_status_change = on_status_change

    # -------------------------------------------------------------------------
    # Lifecycle & Supervisor Thread
    # -------------------------------------------------------------------------

    def start(self):
        """Starts the background reconnect supervisor thread."""
        with self._lock:
            if self._supervisor_thread and self._supervisor_thread.is_alive():
                return
            self._stop_event.clear()
            self._dirty_event.set()
            self._supervisor_thread = threading.Thread(
                target=self._supervisor_loop,
                daemon=True,
                name="nlc-discord-rpc-supervisor",
            )
            self._supervisor_thread.start()

    def stop(self):
        """Stops the supervisor loop and cleanly disconnects Discord RPC."""
        self._stop_event.set()
        self._dirty_event.set()
        with self._lock:
            supervisor = self._supervisor_thread
            self._supervisor_thread = None

        if supervisor and supervisor.is_alive() and threading.current_thread() != supervisor:
            supervisor.join(timeout=2.0)
        self.close()

    def _supervisor_loop(self):
        """
        Background loop that handles reconnection and sequential presence updates.
        Ensures presence updates are serialized without concurrent thread collisions.
        """
        last_check = 0.0
        while not self._stop_event.is_set():
            now = time.time()
            with self._lock:
                should_connect = self.enabled and not self.connected
            if should_connect and (now - last_check >= 15.0):
                last_check = now
                self._attempt_connect()

            if self._dirty_event.is_set():
                self._dirty_event.clear()
                self._dispatch_presence_update()

            self._dirty_event.wait(timeout=1.0)

    def _attempt_connect(self):
        """Synchronous connect attempt."""
        with self._lock:
            if not self.enabled or self.connected:
                return
            client_id = self.client_id

        rpc = None
        connected = False
        try:
            from pypresence import Presence  # type: ignore

            temp_rpc = Presence(client_id)
            temp_rpc.connect()
            rpc = temp_rpc
            connected = True
            logger.info("Discord Rich Presence successfully connected (client_id=%s)", client_id)
        except Exception as exc:
            logger.debug("Discord RPC unavailable: %s", exc)

        with self._lock:
            if not self.enabled or self._stop_event.is_set():
                if rpc:
                    try:
                        rpc.close()
                    except Exception:
                        pass
                self.connected = False
                self.rpc = None
            else:
                self.rpc = rpc
                self.connected = connected

        self._notify_status()
        if connected:
            self._dispatch_presence_update()

    def connect(self):
        """Trigger an immediate asynchronous connection attempt."""
        with self._lock:
            if not self.enabled:
                self.enabled = True
        self.start()
        self._dirty_event.set()

    def close(self):
        """Disconnect and clean up."""
        with self._lock:
            was_connected = self.connected
            rpc_to_close = self.rpc
            self.rpc = None
            self.connected = False

        if rpc_to_close:
            try:
                rpc_to_close.close()
            except Exception:
                pass
            if was_connected:
                logger.info("Discord Rich Presence closed.")
                self._notify_status()

    # -------------------------------------------------------------------------
    # Configuration Setters
    # -------------------------------------------------------------------------

    def set_client_id(self, client_id: str):
        """Update Discord Application ID dynamically."""
        with self._lock:
            client_id = (client_id or "").strip() or DISCORD_CLIENT_ID
            if self.client_id == client_id:
                return
            self.client_id = client_id
            if self.connected:
                self.close()
                if self.enabled:
                    self.connect()

    def set_enabled(self, enabled: bool):
        with self._lock:
            if self.enabled == enabled:
                return
            self.enabled = enabled
            if not enabled:
                self.close()
            else:
                self.connect()

    def set_detail_mode(self, mode: str):
        with self._lock:
            self.detail_mode = mode
            self.refresh()

    def set_show_timer(self, show: bool):
        with self._lock:
            self.show_timer = bool(show)
            self.refresh()

    def set_show_idle(self, show: bool):
        with self._lock:
            self.show_idle = bool(show)
            self.refresh()

    def set_show_server(self, show: bool):
        with self._lock:
            self.show_server = bool(show)
            self.refresh()

    def set_streamer_mode(self, enabled: bool):
        with self._lock:
            self.streamer_mode = bool(enabled)
            self.refresh()

    def set_player(
        self,
        name: str,
        uuid: Optional[str] = None,
        account_type: Optional[str] = None,
        custom_avatar_url: Optional[str] = None,
    ):
        with self._lock:
            self.player_name = name or "Steve"
            self.player_uuid = uuid
            self.account_type = account_type
            if custom_avatar_url is not None:
                self.custom_avatar_url = custom_avatar_url
            self.refresh()

    def set_screen(self, screen: str):
        """Sets current active screen / tab and refreshes presence if idle."""
        with self._lock:
            self._current_screen = str(screen or "Play")
            if self._activity_mode == "idle":
                self.refresh()

    # -------------------------------------------------------------------------
    # Activity State Modifiers
    # -------------------------------------------------------------------------

    def set_idle(self, screen: Optional[str] = None):
        """Sets presence state to Idle / In Launcher."""
        with self._lock:
            self._activity_mode = "idle"
            if screen is not None:
                self._current_screen = str(screen)
            self._activity_start = None
            self._current_version = ""
            self._current_loader = ""
            self._current_installation = ""
            self._current_modpack = None
            self._current_server = None
            self._in_game_state = "menu"
            self.refresh()

    def set_launching(self, version: str, loader: str, installation_name: Optional[str] = None):
        """Sets presence state to Launching game."""
        with self._lock:
            self._activity_mode = "launching"
            self._activity_start = time.time()
            self._current_version = version or ""
            self._current_loader = loader or "Vanilla"
            self._current_installation = installation_name or ""
            self.refresh()

    def set_playing(
        self,
        version: str,
        loader: str,
        installation_name: Optional[str] = None,
        modpack_name: Optional[str] = None,
        server_address: Optional[str] = None,
        started_at: Optional[float] = None,
    ):
        """Sets presence state to In-Game Playing."""
        with self._lock:
            self._activity_mode = "playing"
            self._activity_start = started_at or time.time()
            self._current_version = version or ""
            self._current_loader = loader or "Vanilla"
            self._current_installation = installation_name or ""
            self._current_modpack = modpack_name
            self._current_server = server_address
            self._in_game_state = "multiplayer" if server_address else "menu"
            self.refresh()

    def set_game_state(self, game_state: str, server_address: Optional[str] = None):
        """
        Updates the in-game state dynamically while playing.
        game_state can be 'menu', 'singleplayer', or 'multiplayer'.
        """
        with self._lock:
            self._in_game_state = (game_state or "menu").lower()
            if server_address is not None:
                self._current_server = server_address
            elif self._in_game_state != "multiplayer":
                self._current_server = None
            self.refresh()

    # -------------------------------------------------------------------------
    # Presence Calculation & Update
    # -------------------------------------------------------------------------

    def refresh(self):
        """Triggers presence recalculation and dispatch via the supervisor thread."""
        with self._lock:
            if not self.enabled:
                return
        self._dirty_event.set()

    def _build_presence_payload(self) -> Optional[Dict[str, Any]]:
        """Constructs the kwargs dictionary for pypresence.update(), or None to clear."""
        with self._lock:
            if not self.enabled:
                return None

            # Player text and avatar
            user_text = "Steve"
            small_key = "https://crafthead.net/helm/Steve/128.png"
            if self.streamer_mode:
                user_text = "Player"
            elif self.player_name:
                user_text = self.player_name

            if not self.streamer_mode:
                identifier = None
                raw_uuid = str(self.player_uuid or "").replace("-", "").strip()
                is_offline = (self.account_type or "").lower() == "offline"

                # For online accounts, genuine 32-character hex Mojang UUID takes precedence
                if not is_offline and len(raw_uuid) == 32:
                    try:
                        int(raw_uuid, 16)
                        identifier = raw_uuid
                    except ValueError:
                        identifier = None

                if self.custom_avatar_url and str(self.custom_avatar_url).strip().startswith("http"):
                    small_key = str(self.custom_avatar_url).strip()
                elif identifier:
                    # minotar.net helm fallback when no custom avatar upload is available
                    small_key = f"https://crafthead.net/helm/{identifier}/128.png"
                elif self.player_name and self.player_name.strip().lower() not in ("steve", "player", ""):
                    small_key = f"https://crafthead.net/helm/{self.player_name.strip()}/128.png"

            # Calculate primary details and secondary state
            if self._activity_mode == "idle":
                if not self.show_idle:
                    return None
                details = "In Launcher"
                scr = (self._current_screen or "Play").strip().lower()
                if scr in ("play", "main", "home"):
                    state = "Ready to Play"
                elif scr in ("modrinth", "mods"):
                    state = "Browsing Modrinth"
                elif scr in ("modpacks", "modpack"):
                    state = "Browsing Modpacks"
                elif scr in ("installations", "instances"):
                    state = "Managing Installations"
                elif scr in ("locker", "skins", "wardrobe"):
                    state = "Customizing Wardrobe"
                elif scr in ("addons", "addon"):
                    state = "Browsing Addons"
                elif scr in ("screenshots", "screenshot"):
                    state = "Viewing Screenshots"
                elif scr in ("settings", "preferences"):
                    state = "Configuring Settings"
                else:
                    state = "Ready to Play"
                start_time = None
            elif self._activity_mode == "launching":
                details = "Launching Minecraft..."
                state = f"Version: {self._current_version}" if self._current_version else "Starting..."
                start_time = None
            elif self._activity_mode == "playing":
                # Detail line based on mode - Clean version without loader suffix for "Show Version"
                loader_str = f" ({self._current_loader})" if self._current_loader and self._current_loader != "Vanilla" else ""
                if self.detail_mode == "Show Version":
                    details = f"Playing {self._current_version}"
                elif self.detail_mode == "Show Installation":
                    inst = self._current_installation or self._current_version
                    details = f"Playing {inst}"
                elif self.detail_mode == "Playing Modpack":
                    if self._current_modpack:
                        details = f"Playing {self._current_modpack}"
                    else:
                        details = f"Playing {self._current_version}"
                elif self.detail_mode == "Hidden":
                    details = "Playing Minecraft"
                else:
                    details = f"Playing {self._current_version}"

                # State line (Main Menu / Singleplayer / Multiplayer / Server)
                if self._in_game_state == "multiplayer" or self._current_server:
                    if self._current_server and self.show_server and not self.streamer_mode:
                        state = f"Playing on {self._current_server}"
                    else:
                        state = "Multiplayer"
                elif self._in_game_state == "singleplayer":
                    state = "Singleplayer"
                else:
                    state = "Main Menu"

                start_time = self._activity_start if self.show_timer else None
            else:
                details = "In Launcher"
                state = "Idle"
                start_time = None

            self._last_details = details
            self._last_state = state

            kwargs: Dict[str, Any] = {
                "details": details,
                "state": state,
                "large_image": "logo",
                "large_text": "Ny-Luna Core",
                "small_image": small_key,
                "small_text": user_text,
            }
            if start_time:
                kwargs["start"] = int(start_time)

            return kwargs

    def _dispatch_presence_update(self):
        """Sends presence update or clear to pypresence client."""
        with self._lock:
            if not self.connected or not self.rpc:
                return
            rpc = self.rpc

        payload = self._build_presence_payload()
        try:
            with self._update_lock:
                if payload is None:
                    try:
                        rpc.clear()
                    except Exception:
                        pass
                else:
                    rpc.update(**payload)
            if payload:
                logger.info(
                    "Discord Rich Presence updated: details='%s', state='%s', avatar='%s'",
                    payload.get("details"),
                    payload.get("state"),
                    payload.get("small_image"),
                )
        except Exception as exc:
            logger.debug("Failed to update Discord presence (pipe broken?): %s", exc)
            with self._lock:
                self.connected = False
                try:
                    rpc.close()
                except Exception:
                    pass
                self.rpc = None
            self._notify_status()

    # -------------------------------------------------------------------------
    # Status Introspection
    # -------------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Returns current RPC status dictionary for frontend / IPC."""
        with self._lock:
            status_text = "Connected" if self.connected else ("Disabled" if not self.enabled else "Not Connected")
            elapsed = int(time.time() - self._activity_start) if (self._activity_start and self.show_timer) else None
            return {
                "client_id": self.client_id,
                "enabled": self.enabled,
                "connected": self.connected,
                "status_text": status_text,
                "detail_mode": self.detail_mode,
                "show_timer": self.show_timer,
                "show_idle": self.show_idle,
                "show_server": self.show_server,
                "streamer_mode": self.streamer_mode,
                "mode": self._activity_mode,
                "details": self._last_details,
                "state": self._last_state,
                "elapsed_seconds": elapsed,
            }

    def _notify_status(self):
        """Calls optional status change callback."""
        if self._on_status_change:
            try:
                self._on_status_change(self.get_status())
            except Exception as e:
                logger.warning("Error in on_status_change callback: %s", e)
