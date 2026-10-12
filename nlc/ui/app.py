"""
nlc.ui.app - Main application window and coordinator (MinecraftLauncher)
Inherits all screen mixins and manages window lifecycle, chrome, navigation,
and launch execution.
"""

import os
import sys
import io
import time
import json
import uuid
import glob
import math
import shutil
import base64
import certifi
import urllib.parse
import zipfile
import tempfile
import socket
import logging
import platform
import threading
import traceback
import subprocess
import webbrowser
import hashlib
try:
    import ctypes
    from ctypes import wintypes
except (ImportError, AttributeError):
    ctypes = None
    wintypes = None
from datetime import datetime
from typing import Any, Optional, cast

logger = logging.getLogger(__name__)

import tkinter as tk
from tkinter import font, ttk, messagebox, filedialog, scrolledtext
from PIL import Image, ImageTk, ImageDraw
import minecraft_launcher_lib
import requests

from nlc.ui.theme import COLORS, METRICS, FONT_FAMILY, THEMES, THEME_MANAGER
from nlc.ui.animation import AnimationManager
from nlc.storage.paths import resource_path, get_minecraft_dir, is_version_installed, RESAMPLE_NEAREST, FLIP_LEFT_RIGHT, AFFINE, open_path_in_system
from nlc.storage.config import (
    CURRENT_VERSION, DEFAULT_RAM, DEFAULT_USERNAME, INSTALL_MARK,
    LOADERS, MOD_COMPATIBLE_LOADERS, ConfigManager, normalize_installations
)
from nlc.core.versions import format_version_display, normalize_version_text
from nlc.core.launch import safe_extract_zip, patch_minecraft_launcher_launch_helpers
from nlc.core.instances import sync_instance_assets
from nlc.core.updater import verify_manifest_signature
from nlc.cdc_engine import download_and_assemble_cdc, verify_cdc_signature
from nlc.core.discord_rpc import DiscordRPCManager
from nlc.net.skin_server import LocalSkinServer
from nlc.net.ms_auth import MicrosoftDeviceAuth, MSA_CLIENT_ID, MSA_REDIRECT_URI
from nlc.net.elyby_auth import ElyByAuth
from nlc.ui.components.dialogs import (
    CustomMessagebox, custom_showinfo, custom_showwarning, custom_showerror, custom_askyesno,
    _build_missing_skin_head
)
from nlc.ui.components.toasts import ToastManager, PopupManager
from nlc.ui.components.notifications import NotificationStore, NotificationCenterDrawer
from nlc.ui.components.modal import InAppModalManager, set_modal_manager, get_modal_manager
from nlc.ui.components.skin_renderer import SkinRenderer3D
from nlc.ui.components.downloads import DownloadManager, DownloadQueueMixin
from nlc.ui.components.buttons import make_button, make_badge, refresh_all_buttons
from nlc.ui.components.cards import create_card
from nlc.ui.components.context_menu import dismiss_active_context_menu
from nlc.ui.dispatcher import EventDispatcher
from nlc.ui.screens.accounts import AccountsScreenMixin
from nlc.ui.screens.settings import SettingsScreenMixin, CATEGORIES
from nlc.ui.screens.addons import AddonsScreenMixin
from nlc.ui.screens.modpacks import ModpacksScreenMixin
from nlc.ui.screens.mods import ModsScreenMixin
from nlc.ui.screens.locker import LockerScreenMixin
from nlc.ui.screens.installations import InstallationsScreenMixin
from nlc.ui.screens.play import PlayScreenMixin
from nlc.ui.screens.screenshots import ScreenshotScreenMixin

try:
    from pypresence import Presence
    RPC_AVAILABLE = True
except ImportError:
    RPC_AVAILABLE = False

try:
    from pystray import MenuItem as TrayItem, Icon as TrayIcon
    TRAY_AVAILABLE = True
except ImportError:
    TrayItem = None
    TrayIcon = None
    TRAY_AVAILABLE = False

# Fallback helper functions for backwards compatibility
_ORIGINAL_PIL_PHOTOIMAGE = getattr(ImageTk, "PhotoImage", None)
_IMAGETK_FALLBACK_WARNED = False

def _safe_pil_photoimage(image, *args, **kwargs):
    global _IMAGETK_FALLBACK_WARNED
    try:
        return _ORIGINAL_PIL_PHOTOIMAGE(image, *args, **kwargs)
    except Exception as exc:
        if not _IMAGETK_FALLBACK_WARNED:
            logging.warning("ImageTk.PhotoImage failed (%s); using tkinter.PhotoImage PNG fallback.", exc)
            _IMAGETK_FALLBACK_WARNED = True
        with io.BytesIO() as png_buffer:
            image.save(png_buffer, format="PNG")
            encoded = base64.b64encode(png_buffer.getvalue()).decode("ascii")
        return tk.PhotoImage(data=encoded, format="png")


ImageTk.PhotoImage = _safe_pil_photoimage


def _center_window_on_parent(win, parent=None, width=None, height=None):
    try:
        if parent is not None and hasattr(parent, "winfo_exists") and parent.winfo_exists():
            try:
                parent.update_idletasks()
            except Exception:
                pass

        try:
            win.update_idletasks()
        except Exception:
            pass

        final_w = width if width is not None else win.winfo_width()
        final_h = height if height is not None else win.winfo_height()

        if not final_w or final_w <= 1:
            final_w = win.winfo_reqwidth()
        if not final_h or final_h <= 1:
            final_h = win.winfo_reqheight()

        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        x = (screen_w - final_w) // 2
        y = (screen_h - final_h) // 2

        if parent is not None and hasattr(parent, "winfo_exists") and parent.winfo_exists():
            try:
                parent_x = parent.winfo_rootx()
                parent_y = parent.winfo_rooty()
                parent_w = parent.winfo_width()
                parent_h = parent.winfo_height()
                if parent_w > 1 and parent_h > 1:
                    x = parent_x + (parent_w - final_w) // 2
                    y = parent_y + (parent_h - final_h) // 2
            except Exception:
                pass

        x = max(0, min(x, max(0, screen_w - final_w)))
        y = max(0, min(y, max(0, screen_h - final_h)))
        win.geometry(f"{int(final_w)}x{int(final_h)}+{int(x)}+{int(y)}")
    except Exception:
        pass


def _get_widget_descendants(widget):
    """Recursively return all descendant widgets of a widget."""
    descendants = []
    try:
        if not widget or not widget.winfo_exists():
            return descendants
        for child in widget.winfo_children():
            descendants.append(child)
            descendants.extend(_get_widget_descendants(child))
    except Exception:
        pass
    return descendants


def _is_pointer_inside(widget):
    """Return True if mouse pointer is inside widget or any of its descendants."""
    try:
        if not widget or not widget.winfo_exists():
            return False
        x, y = widget.winfo_pointerxy()
        under = widget.winfo_containing(x, y)
        if under is None:
            return False
        curr = under
        while curr is not None:
            if curr == widget:
                return True
            curr = getattr(curr, "master", None)
        return False
    except Exception:
        return False


def _resolve_dialog_parent(preferred_parent=None, fallback_widget=None):
    candidates = []
    if preferred_parent is not None:
        candidates.append(preferred_parent)
    if fallback_widget is not None:
        try:
            manager = getattr(fallback_widget, "_nlc_app", None)
            if manager is not None and getattr(manager, "root", None) is not None:
                candidates.append(manager.root)
        except Exception:
            pass
        try:
            top = fallback_widget.winfo_toplevel()
            if top is not None:
                candidates.append(top)
        except Exception:
            pass
    default_root = getattr(tk, "_default_root", None)
    if default_root is not None:
        candidates.append(default_root)

    seen = set()
    for candidate in candidates:
        if candidate is None:
            continue
        ident = id(candidate)
        if ident in seen:
            continue
        seen.add(ident)
        try:
            if candidate.winfo_exists():
                return candidate
        except Exception:
            continue
    return None


def _schedule_window_centering(win, parent=None, width=None, height=None):
    owner = _resolve_dialog_parent(parent, win)
    try:
        win._nlc_center_owner = owner  # type: ignore[attr-defined]
        win._nlc_center_width = width  # type: ignore[attr-defined]
        win._nlc_center_height = height  # type: ignore[attr-defined]
    except Exception:
        pass

    def apply_center(target=win, target_owner=owner, target_width=width, target_height=height):
        try:
            if not target.winfo_exists():
                return
            if os.name == "nt":
                try:
                    if str(target.state()) == "withdrawn":
                        return
                except Exception:
                    pass
            _center_window_on_parent(target, target_owner, width=target_width, height=target_height)
        except Exception:
            pass

    apply_center()

    delays = (0, 30, 120, 240, 420, 760) if os.name == "nt" else (0, 30, 120)
    for delay in delays:
        try:
            win.after(delay, apply_center)
        except Exception:
            pass

    if not getattr(win, "_nlc_center_hooks", False):
        try:
            win.bind(
                "<Map>",
                lambda _event, w=win: _schedule_window_centering(
                    w,
                    getattr(w, "_nlc_center_owner", None),
                    getattr(w, "_nlc_center_width", None),
                    getattr(w, "_nlc_center_height", None),
                ),
                add="+",
            )
        except Exception:
            pass
        try:
            win._nlc_center_hooks = True  # type: ignore[attr-defined]
        except Exception:
            pass


def _resolve_requests_ca_bundle():
    env_vars = ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE")
    for var_name in env_vars:
        path = os.environ.get(var_name)
        if not path:
            continue
        if os.path.exists(path):
            return path
        try:
            os.environ.pop(var_name, None)
        except Exception:
            pass

    if certifi is not None:
        try:
            path = certifi.where()
            if path and os.path.exists(path):
                return path
        except Exception:
            pass

    for bundled in ("certifi/cacert.pem", "cacert.pem"):
        try:
            path = resource_path(bundled)
            if path and os.path.exists(path):
                return path
        except Exception:
            pass

    return None


_REQUESTS_CA_BUNDLE = _resolve_requests_ca_bundle()
_ORIG_REQUESTS_SESSION_REQUEST = requests.sessions.Session.request


def _patched_requests_session_request(session, method, url, **kwargs):
    if kwargs.get("verify", None) is None and _REQUESTS_CA_BUNDLE:
        kwargs["verify"] = _REQUESTS_CA_BUNDLE

    # A missing timeout leaves the UI's worker threads hanging indefinitely on a
    # broken connection.  Individual calls can still request a longer timeout.
    kwargs.setdefault("timeout", (10, 60))

    try:
        return _ORIG_REQUESTS_SESSION_REQUEST(session, method, url, **kwargs)
    except OSError as exc:
        if "Could not find a suitable TLS CA certificate bundle" not in str(exc):
            raise
        for var_name in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
            try:
                os.environ.pop(var_name, None)
            except Exception:
                pass
        # Never silently fall back to an unverified TLS connection.  Requests
        # will use its bundled/default trust store after the invalid override
        # has been cleared.
        retry_kwargs = dict(kwargs)
        retry_kwargs.pop("verify", None)
        logging.warning("Invalid TLS CA bundle path; retrying with the default trust store: %s", url)
        return _ORIG_REQUESTS_SESSION_REQUEST(session, method, url, **retry_kwargs)


requests.sessions.Session.request = _patched_requests_session_request # type: ignore

# --- Helpers ---
# Moved to utils.py

# --- Color Scheme (Official Launcher Look) ---
# Moved to config.py

# --- Helpers ---
# Moved to utils.py

# LOADERS, etc moved to config.py

def format_version_display(version_id):
    return f"{INSTALL_MARK}{version_id}" if is_version_installed(version_id) else version_id

def normalize_version_text(value):
    if not value:
        return ""
    return value.replace(INSTALL_MARK, "").strip()


def _safe_extract_zip(archive, destination):
    """Extract a ZIP without allowing its entries to escape *destination*."""
    destination_path = os.path.realpath(destination)
    with zipfile.ZipFile(archive, "r") as zip_file:
        for member in zip_file.infolist():
            # Unix symlinks encoded in ZIP metadata can redirect a later file
            # outside the target folder even when the filename looks harmless.
            is_symlink = ((member.external_attr >> 16) & 0o170000) == 0o120000
            member_path = os.path.realpath(os.path.join(destination_path, member.filename))
            if is_symlink or os.path.commonpath((destination_path, member_path)) != destination_path:
                raise ValueError(f"Unsafe archive entry rejected: {member.filename}")
        zip_file.extractall(destination_path)


def _atomic_download(url, destination, *, cancel_event=None, chunk_size=64 * 1024, progress=None, headers=None, rate_limit_kib=0, expected_sha1=None):
    """Download to a sibling temporary file, then atomically publish it."""
    destination = os.path.abspath(destination)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    temporary = f"{destination}.{uuid.uuid4().hex}.part"
    try:
        with requests.get(url, stream=True, headers=headers, timeout=(10, 60)) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            started_at = time.monotonic()
            with open(temporary, "wb") as output:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if cancel_event is not None and cancel_event.is_set():
                        raise RuntimeError("Cancelled")
                    if not chunk:
                        continue
                    output.write(chunk)
                    downloaded += len(chunk)
                    if rate_limit_kib:
                        target_elapsed = downloaded / (max(1, rate_limit_kib) * 1024)
                        remaining = target_elapsed - (time.monotonic() - started_at)
                        if remaining > 0:
                            time.sleep(remaining)
                    if progress is not None:
                        progress(downloaded, total)
        if expected_sha1:
            digest = hashlib.sha1()
            with open(temporary, "rb") as downloaded_file:
                for block in iter(lambda: downloaded_file.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest().lower() != str(expected_sha1).lower():
                raise ValueError("Downloaded file failed checksum verification.")
        os.replace(temporary, destination)
        return destination
    finally:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            logging.warning("Could not remove incomplete download: %s", temporary)


def _get_lib_name_without_version(lib):
    return ":".join(str(lib.get("name", "")).split(":")[:-1])


def _safe_inherit_json(original_data, path):
    inherit_version = original_data["inheritsFrom"]

    with open(os.path.join(path, "versions", inherit_version, inherit_version + ".json"), encoding="utf-8") as f:
        new_data = json.load(f)

    original_libs = {}
    for current_lib in original_data.get("libraries", []):
        lib_name = _get_lib_name_without_version(current_lib)
        original_libs[lib_name] = True

    lib_list = original_data.get("libraries", [])
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
                    existing_list = target_dict.get(child_key, [])
                    if not isinstance(existing_list, list):
                        existing_list = []
                    target_dict[child_key] = existing_list + child_value
                else:
                    target_dict[child_key] = child_value
        else:
            new_data[key] = value

    return new_data


def _safe_get_minecraft_arguments(data, version_data, path, options, classpath):
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
            logging.warning(
                "Skipping malformed launch argument without 'value' for version %s: %s",
                version_id,
                entry,
            )
            continue

        argument_value = entry.get("value")
        if isinstance(argument_value, str):
            arglist.append(
                minecraft_launcher_lib.command.replace_arguments(
                    argument_value, version_data, path, options, classpath
                )
            )
            continue

        if isinstance(argument_value, list):
            for value in argument_value:
                arglist.append(
                    minecraft_launcher_lib.command.replace_arguments(
                        value, version_data, path, options, classpath
                    )
                )
            continue

        logging.warning(
            "Skipping malformed launch argument value for version %s: %r",
            version_id,
            argument_value,
        )

    return arglist


def _patch_minecraft_launcher_launch_helpers():
    try:
        minecraft_launcher_lib.command.inherit_json = _safe_inherit_json
        minecraft_launcher_lib.command.get_arguments = _safe_get_minecraft_arguments
    except Exception:
        logging.exception("Failed to patch minecraft-launcher-lib command helpers")


_patch_minecraft_launcher_launch_helpers()


def _get_streamer_hidden_name():
    return "Hidden Account"


def _get_widget_hwnd(widget):
    if os.name != "nt":
        return 0
    try:
        return int(widget.winfo_id())
    except Exception:
        return 0


def _iter_widget_hwnds(widget):
    if os.name != "nt":
        return []
    try:
        user32 = ctypes.windll.user32
        base_hwnd = int(widget.winfo_id())
    except Exception:
        return []

    try:
        root_hwnd = int(user32.GetAncestor(base_hwnd, 2))  # GA_ROOT
    except Exception:
        root_hwnd = 0
    if root_hwnd > 0:
        return [root_hwnd]
    if base_hwnd > 0:
        return [base_hwnd]
    return []


def _ensure_window_icon(window, owner=None):
    try:
        icon_ico = resource_path("logo.ico")
        if os.path.exists(icon_ico):
            window.iconbitmap(icon_ico)
    except Exception:
        pass

    try:
        shared_photo = None
        if owner is not None:
            shared_photo = getattr(owner, "_nlc_icon_photo", None)
        if shared_photo is None:
            shared_photo = getattr(window, "_nlc_icon_photo", None)
        if shared_photo is None:
            icon_png = resource_path("logo.png")
            if os.path.exists(icon_png):
                shared_photo = tk.PhotoImage(file=icon_png)
        if shared_photo is not None:
            window._nlc_icon_photo = shared_photo
            window.iconphoto(True, shared_photo)
    except Exception:
        pass


def _detach_window_owner(window):
    if os.name != "nt":
        return
    try:
        set_window_long = getattr(ctypes.windll.user32, "SetWindowLongPtrW", ctypes.windll.user32.SetWindowLongW)
        GWL_HWNDPARENT = -8
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020

        for hwnd in _iter_widget_hwnds(window):
            try:
                set_window_long(hwnd, GWL_HWNDPARENT, 0)
                ctypes.windll.user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                )
            except Exception:
                continue
    except Exception:
        pass


def _force_taskbar_button(window):
    if os.name != "nt":
        return
    try:
        _detach_window_owner(window)

        get_window_long = getattr(ctypes.windll.user32, "GetWindowLongPtrW", ctypes.windll.user32.GetWindowLongW)
        set_window_long = getattr(ctypes.windll.user32, "SetWindowLongPtrW", ctypes.windll.user32.SetWindowLongW)

        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020
        SWP_SHOWWINDOW = 0x0040

        for hwnd in _iter_widget_hwnds(window):
            try:
                ex_style = int(get_window_long(hwnd, GWL_EXSTYLE))
                new_style = (ex_style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
                if new_style != ex_style:
                    set_window_long(hwnd, GWL_EXSTYLE, new_style)
                # Always commit frame change so Explorer updates taskbar grouping immediately.
                ctypes.windll.user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW
                )
            except Exception:
                continue
    except Exception:
        pass


def _prime_taskbar_window(window):
    if os.name != "nt":
        return

    def enforce():
        try:
            if not window.winfo_exists():
                return
            _force_taskbar_button(window)
        except Exception:
            pass

    try:
        window.wm_attributes("-toolwindow", False)
    except Exception:
        pass

    def schedule_prime(_event=None):
        try:
            if not window.winfo_exists():
                return
        except Exception:
            return
        window.after_idle(enforce)
        window.after(80, enforce)
        window.after(180, enforce)
        window.after(320, lambda: _refresh_taskbar_registration(window))
        window.after(650, lambda: _refresh_taskbar_registration(window))

    if not getattr(window, "_nlc_taskbar_hooks", False):
        try:
            window.bind("<Map>", schedule_prime, add="+")
        except Exception:
            pass
        try:
            window.bind("<FocusIn>", lambda _event=None: window.after(40, enforce), add="+")
        except Exception:
            pass
        try:
            window._nlc_taskbar_hooks = True  # type: ignore[attr-defined]
        except Exception:
            pass

    schedule_prime()


def _refresh_taskbar_registration(window):
    if os.name != "nt":
        return False
    try:
        user32 = ctypes.windll.user32
        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020
        RDW_INVALIDATE = 0x0001
        RDW_UPDATENOW = 0x0100
        RDW_FRAME = 0x0400
        did_refresh = False
        for hwnd in _iter_widget_hwnds(window):
            try:
                user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                )
                user32.RedrawWindow(hwnd, None, None, RDW_INVALIDATE | RDW_UPDATENOW | RDW_FRAME)
                did_refresh = True
            except Exception:
                continue
        return did_refresh
    except Exception:
        return False


class MinecraftLauncher(
    AccountsScreenMixin,
    SettingsScreenMixin,
    AddonsScreenMixin,
    ModpacksScreenMixin,
    ModsScreenMixin,
    LockerScreenMixin,
    InstallationsScreenMixin,
    PlayScreenMixin,
    ScreenshotScreenMixin,
    DownloadQueueMixin,
):
    def __init__(self, root):
        self.root = root
        self.animations_enabled = True
        self.theme_id = "dark_slate"
        self.custom_accent = None
        self.animator = AnimationManager(self.root, lambda: getattr(self, "animations_enabled", True))
        self.dispatcher = EventDispatcher(self.root)
        self.dispatcher.start()
        self.download_manager = DownloadManager(self)
        self.root.title("NLC | New launcher")
        
        # Determine config path early for logging
        app_data = os.getenv('APPDATA')
        if os.path.exists("launcher_config.json"):
             self.config_dir = os.path.abspath(os.path.dirname("launcher_config.json"))
        elif app_data:
             self.config_dir = os.path.join(app_data, ".nlc")
        else:
             self.config_dir = os.path.join(os.path.expanduser("~"), ".nlc")

        # Initialize Logging
        self.setup_logging()

        # Global Exception Hook
        def handle_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            
            logging.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
            traceback.print_exception(exc_type, exc_value, exc_traceback)
            
            # Show error dialog if GUI is up
            if self.root:
                 # Truncate for message box
                 tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
                 start_idx = max(0, len(tb_lines) - 5)
                 err_text = "".join(tb_lines[start_idx:])
                 self.root.after(0, lambda: messagebox.showerror("Critical Error", f"An unexpected error occurred:\n{exc_value}\n\nSee logs for full details."))

        sys.excepthook = handle_exception

        try:
            self.root.iconbitmap(resource_path("logo.ico"))
        except Exception:
            pass
        try:
            self.root._nlc_app = self  # type: ignore[attr-defined]
        except Exception:
            pass
        self.popup_manager = PopupManager(self.root)
        self.notifications = NotificationStore()
        self.toast_manager = ToastManager(self.root, on_toast_click=lambda: self.toggle_notification_center())
        self.notification_drawer = NotificationCenterDrawer(
            self.root,
            self.notifications,
            on_badge_update=lambda count: self._update_notification_badge(count)
        )
        self.modal_manager = InAppModalManager(self.root)
        set_modal_manager(self.modal_manager)
        self.root._nlc_popup_manager = self.popup_manager  # type: ignore[attr-defined]
        _ensure_window_icon(self.root, owner=self.root)
        if os.name != 'nt':
            try:
                self.root.option_add("*Button.highlightThickness", 0)
                self.root.option_add("*Entry.highlightThickness", 0)
                self.root.option_add("*Listbox.highlightThickness", 0)
                self.root.option_add("*Text.highlightThickness", 0)
                self.root.option_add("*Canvas.highlightThickness", 0)
                self.root.option_add("*Checkbutton.highlightThickness", 0)
                self.root.option_add("*Radiobutton.highlightThickness", 0)
                self.root.option_add("*Scale.highlightThickness", 0)
            except Exception:
                pass
            
        # Center Window
        w, h = 1080, 720
        ws = self.root.winfo_screenwidth()
        hs = self.root.winfo_screenheight()
        x = (ws/2) - (w/2)
        y = (hs/2) - (h/2)
        self.root.geometry('%dx%d+%d+%d' % (w, h, x, y))

        # Config Priority: 
        # 1. Local "launcher_config.json" (Portable / Dev mode)
        # 2. AppData/.nlc (Standard Install)
        local_config = "launcher_config.json"
        
        if os.path.exists(local_config):
            self.config_file = os.path.abspath(local_config)
            self.config_dir = os.path.dirname(self.config_file)
            print(f"Using local config: {self.config_file}")
        else:
            app_data = os.getenv('APPDATA')
            if app_data:
                self.config_dir = os.path.join(app_data, ".nlc")
            else:
                self.config_dir = os.path.join(os.path.expanduser("~"), ".nlc")
                
            if not os.path.exists(self.config_dir):
                os.makedirs(self.config_dir, exist_ok=True)
                
            self.config_file = os.path.join(self.config_dir, "launcher_config.json")
            print(f"Using global config: {self.config_file}")
        
        # --- Pre-load Theme, Accent Color & Custom Titlebar ---
        self.theme_id = "dark_slate"
        self.custom_accent = None
        self.accent_color_name = "Green"
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    _d = json.load(f)
                    
                    self.theme_id = _d.get("theme_id", "dark_slate")
                    if self.theme_id not in THEMES:
                        self.theme_id = "dark_slate"
                    self.custom_accent = _d.get("custom_accent", None)
                    self.accent_color_name = _d.get("accent_color", self.custom_accent or THEMES[self.theme_id].get('default_accent', '#2ECC71'))
                    
                    # Pre-load custom titlebar setting BEFORE window creation
                    if "custom_titlebar_enabled" in _d:
                        self.custom_titlebar_enabled = _d["custom_titlebar_enabled"] and os.name == 'nt'
                    
                    self.neo_style_enabled = _d.get("neo_style_enabled", True)
                    self.animations_enabled = _d.get("animations_enabled", True)

                    # Initialize global COLORS design tokens with the user's saved theme before creating widgets
                    THEME_MANAGER.apply(self.theme_id, self.custom_accent, notify=False)
        except Exception as e:
            print(f"Error pre-loading config: {e}")

        self.root.configure(bg=COLORS['main_bg'])
        self.minecraft_dir = get_minecraft_dir()
        self.custom_titlebar_enabled = True # Will be overridden by config, but default to true on windows
        self.neo_style_enabled = True # Will be overridden by config
        if os.name != 'nt':
            self.custom_titlebar_enabled = False
        self._custom_chrome_applied = False
        self._window_is_maximized = False
        self.root.update_idletasks()
        self._windowed_geometry = (
            self.root.winfo_x(),
            self.root.winfo_y(),
            max(1, self.root.winfo_width()),
            max(1, self.root.winfo_height())
        )
        self._last_nonmax_geometry = self._windowed_geometry
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_win_x = 0
        self._drag_win_y = 0
        self._drag_last_x = 0
        self._drag_last_y = 0
        self._drag_active = False
        self._drag_target_x = 0
        self._drag_target_y = 0
        self._drag_apply_after_id = None
        self._drag_preview_enabled = (os.name == 'nt')
        self._drag_preview_win = None
        self._drag_preview_w = 0
        self._drag_preview_h = 0
        self._drag_preview_logo = None
        self._window_animating = False
        self._window_anim_after_id = None
        self._transition_overlay_win = None
        self._pre_minimize_geometry = None
        self._pre_minimize_anchor_geometry = None
        self._pre_minimize_was_maximized = False
        self._taskbar_refresh_done = False
        self._original_win_style = None
        self._use_native_drag = False
        self._onboarding_wizard = None
        self._onboarding_overlay = None
        self._onboarding_focus_bindings = []
        self._dialog_windows = []
        self._dialog_focus_bindings = []
        self._dialog_raise_scheduled = False
        self._dialog_raise_after_id = None
        self._dialog_last_raise_ts = 0.0
        self._dialog_raise_min_interval = 0.12
        self.window_shell = None
        self.window_content = self.root
        self._update_in_progress = False
        self._update_shutdown_started = False
        self._config_save_after_id = None
        self._config_save_delay_ms = 250
        self._config_sync_ui_pending = False
        self._launch_in_progress = False
        
        # Download Queue State
        self.download_tasks = {} # id -> {ui_elements, data}
        self.addons_config: dict[str, Any] = {} # Addons configuration
        self.instances_config = {
            "share_resourcepacks": True,
            "share_shaderpacks": True,
            "share_worlds": False,
            "share_configs": False,
        }
        self.download_queue_visible = False

        self.last_version = ""
        self.profiles = [] # List of {"name": str, "type": "offline", "skin_path": str, "uuid": str} (ACCOUNTS)
        self.installations = [] # List of {"name": str, "version": str, "loader": str, "last_played": str, "created": str} (GAME PROFILES)
        self.current_profile_index = -1
        self.skin_path = ""  # Initialize before load_from_config
        self.auto_download_mod = False
        self.enable_modrinth = True
        self.installed_mods_view_mode = "grid"
        self.mod_available_online = False
        self.ram_allocation = DEFAULT_RAM
        self.java_args = ""
        self.loader_var = tk.StringVar(value="Vanilla")
        self.version_var = tk.StringVar()
        self.rpc_enabled = True # Default True
        self.rpc_show_version = True # Default True
        self.rpc_show_server = True # Default True
        self.rpc = None
        self.rpc_connected = False
        self.auto_update_check = True # Default True
        self.icon_cache = {}
        self.hero_img_raw = None
        self.first_run = True # Default for new installs

        # Addons Config
        self.addons_config = {
            "p3_reload_menu": False,
            "gh_sync_enabled": False,
            "gh_repo": "",
            "gh_token": "",
            "playtime_tracker": {},
            "saved_servers": []
        }
        self.screenshot_thumbnail_cache = {}
        self.quick_join_installation_labels = {}
        self.third_party_addons = []
        self.third_party_addon_input_vars = {}
        
        # Agent / Background Process
        self.agent_process = None
        self.agent_callbacks = {}
        self.agent_lock = threading.Lock()

        self.start_time = None
        self.current_tab = None
        self.log_file_path = None

        self.setup_logging()
        self.setup_tray()
        
        self.modpacks = []
        self.load_modpacks()

        # Smooth scrolling state
        self._scroll_velocities = {}  # canvas_id -> velocity
        self._scroll_anim_ids = {}    # canvas_id -> after_id

        self.setup_styles()
        self.setup_window_chrome()
        self.create_layout()
        self.load_from_config()
        # Refresh UI with loaded data
        self.update_installation_dropdown()
        self.refresh_installations_list()
        self.load_versions()
        
        # Auto Update Check
        if self.auto_update_check:
            self.check_for_updates()
            
        # Start Background Agent
        self.start_agent_process()
            
        # Onboarding / What's New Trigger
        if self.first_run:
            self.last_version = CURRENT_VERSION
            self.root.after(500, self.show_onboarding_wizard)
        elif getattr(self, "last_version", "") and self.last_version != CURRENT_VERSION:
            self.root.after(1000, lambda: self.show_whats_new(CURRENT_VERSION))
            self.last_version = CURRENT_VERSION
            self.save_config()

    def dispatch_ui(self, fn, *args, **kwargs):
        """Thread-safe marshaling of callbacks to the main Tk thread."""
        if hasattr(self, "dispatcher") and self.dispatcher:
            self.dispatcher.post(fn, *args, **kwargs)
        else:
            try:
                self.root.after(0, lambda: fn(*args, **kwargs))
            except Exception:
                pass

    def load_modpacks(self):
        self.modpacks = []
        try:
            mp_file = os.path.join(self.config_dir, "modpacks.json")
            if os.path.exists(mp_file):
                with open(mp_file, "r") as f:
                    loaded = json.load(f)
                    if not isinstance(loaded, list):
                        raise ValueError("Modpacks configuration must be a list.")
                    self.modpacks = [pack for pack in loaded if isinstance(pack, dict)]
        except Exception as e:
            self.log(f"Error loading modpacks: {e}")

    def save_modpacks(self):
        try:
            mp_file = os.path.join(self.config_dir, "modpacks.json")
            with open(mp_file, "w") as f:
                json.dump(self.modpacks, f, indent=4)
        except Exception as e:
            self.log(f"Error saving modpacks: {e}")

    def get_modpack_dir(self, pack_id):
        # IDs are persisted user data; do not let a malformed config traverse
        # out of the launcher's modpack storage before a delete/copy operation.
        safe_id = os.path.basename(str(pack_id or "").strip())
        if not safe_id or safe_id in {".", ".."}:
            raise ValueError("Invalid modpack identifier.")
        root = os.path.abspath(os.path.join(getattr(self, 'config_dir', os.getcwd()), "modpacks"))
        base = os.path.abspath(os.path.join(root, safe_id))
        if os.path.commonpath((root, base)) != root:
            raise ValueError("Modpack path is outside launcher storage.")
        if not os.path.exists(base):
            os.makedirs(base, exist_ok=True)
        return base

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        # Combobox
        style.configure("Launcher.TCombobox",
                       fieldbackground=COLORS['input_bg'],
                       background=COLORS['input_bg'],
                       foreground=COLORS['text_primary'],
                       arrowcolor=COLORS['text_primary'],
                       bordercolor=COLORS['input_border'],
                       lightcolor=COLORS['input_bg'],
                       darkcolor=COLORS['input_bg'],
                       relief="flat")
        style.map('Launcher.TCombobox',
                 fieldbackground=[('readonly', COLORS['input_bg'])],
                 selectbackground=[('readonly', COLORS['input_bg'])],
                 selectforeground=[('readonly', COLORS['text_primary'])])
        
        # Progressbar
        style.configure("Launcher.Horizontal.TProgressbar",
                       troughcolor=COLORS.get('input_bg', '#212121'),
                       background=COLORS.get('play_btn_green', COLORS.get('success_green', '#10B981')),
                       bordercolor=COLORS.get('input_bg', '#212121'),
                       lightcolor=COLORS.get('input_bg', '#212121'),
                       darkcolor=COLORS.get('input_bg', '#212121'),
                       borderwidth=0,
                       thickness=15)
        
        # Scrollbar (Custom Dark)
        style.layout("Launcher.Vertical.TScrollbar", 
                    [('Vertical.Scrollbar.trough',
                      {'children': [('Vertical.Scrollbar.thumb', 
                                    {'expand': '1', 'sticky': 'nswe'})],
                       'sticky': 'ns'})]) # type: ignore
                       
        style.configure("Launcher.Vertical.TScrollbar",
                       background=COLORS.get('input_bg', '#2E333E'),
                       troughcolor=COLORS['main_bg'],
                       bordercolor=COLORS['main_bg'],
                       arrowcolor=COLORS['text_secondary'],
                       lightcolor=COLORS.get('input_bg', '#2E333E'),
                       darkcolor=COLORS.get('input_bg', '#2E333E'),
                       relief="flat",
                       borderwidth=0)
        
        style.map("Launcher.Vertical.TScrollbar",
                 background=[('pressed', COLORS.get('hover_bg', '#3A3F4D')), ('active', COLORS.get('card_hover', '#2C313C'))],
                 arrowcolor=[('pressed', COLORS['text_primary']), ('active', COLORS['text_primary'])])

    def _set_custom_window_chrome(self, enabled):
        if not self.custom_titlebar_enabled:
            return
        try:
            if os.name != 'nt':
                if enabled and not self._custom_chrome_applied:
                    self.root.overrideredirect(True)
                    self._custom_chrome_applied = True
                elif not enabled and self._custom_chrome_applied:
                    self.root.overrideredirect(False)
                    self._custom_chrome_applied = False
                return

            hwnd = self._get_native_hwnd()
            if not hwnd:
                return
            get_window_long = getattr(ctypes.windll.user32, "GetWindowLongPtrW", ctypes.windll.user32.GetWindowLongW)
            set_window_long = getattr(ctypes.windll.user32, "SetWindowLongPtrW", ctypes.windll.user32.SetWindowLongW)

            GWL_STYLE = -16
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            WS_POPUP = 0x80000000
            WS_CAPTION = 0x00C00000
            WS_THICKFRAME = 0x00040000
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            WS_SYSMENU = 0x00080000

            current_style = int(get_window_long(hwnd, GWL_STYLE))
            if self._original_win_style is None:
                self._original_win_style = current_style

            if enabled:
                new_style = (current_style & ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)) | WS_POPUP
                if new_style != current_style:
                    set_window_long(hwnd, GWL_STYLE, new_style)
                    ctypes.windll.user32.SetWindowPos(
                        hwnd, 0, 0, 0, 0, 0,
                        SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                    )
                self._custom_chrome_applied = True
                self.root.after(10, self._ensure_taskbar_visibility)
            elif not enabled and self._custom_chrome_applied:
                restore_style = int(self._original_win_style) if self._original_win_style is not None else current_style
                set_window_long(hwnd, GWL_STYLE, restore_style)
                ctypes.windll.user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                )
                self._custom_chrome_applied = False
        except Exception:
            pass

    def _get_native_hwnd(self):
        if os.name != 'nt':
            return 0
        try:
            base_hwnd = int(self.root.winfo_id())
            GA_ROOT = 2
            user32 = ctypes.windll.user32
            root_hwnd = user32.GetAncestor(base_hwnd, GA_ROOT)
            return int(root_hwnd) if root_hwnd else base_hwnd
        except Exception:
            return 0

    def _ensure_taskbar_visibility(self):
        if not self.custom_titlebar_enabled or os.name != 'nt':
            return
        try:
            hwnd = self._get_native_hwnd()
            if not hwnd:
                return
            get_window_long = getattr(ctypes.windll.user32, "GetWindowLongPtrW", ctypes.windll.user32.GetWindowLongW)
            set_window_long = getattr(ctypes.windll.user32, "SetWindowLongPtrW", ctypes.windll.user32.SetWindowLongW)

            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020

            ex_style = int(get_window_long(hwnd, GWL_EXSTYLE))
            new_style = (ex_style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            if new_style != ex_style:
                set_window_long(hwnd, GWL_EXSTYLE, new_style)
                ctypes.windll.user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                )
            if not self._taskbar_refresh_done:
                self._taskbar_refresh_done = True
                self.root.after(30, self._refresh_taskbar_window)
        except Exception:
            pass

    def _refresh_taskbar_window(self):
        if not self.custom_titlebar_enabled or os.name != 'nt':
            return
        try:
            if str(self.root.state()) == 'withdrawn':
                return
            geom = self.root.geometry()
            self.root.withdraw()
            self.root.after(20, lambda g=geom: self._restore_from_taskbar_refresh(g))
        except Exception:
            pass

    def _restore_from_taskbar_refresh(self, geom):
        try:
            self.root.deiconify()
            self.root.geometry(geom)
            self.root.lift()
            self._set_custom_window_chrome(True)
        except Exception:
            pass

    def _on_root_map_restore_chrome(self, event):
        if not self.custom_titlebar_enabled:
            return
        if event and event.widget != self.root:
            return
        self.root.after(30, lambda: self._set_custom_window_chrome(True))
        self.root.after(60, self._ensure_taskbar_visibility)

    def _start_native_drag(self, window=None):
        if not self._use_native_drag or os.name != 'nt':
            return False
        try:
            target = window if window is not None else self.root
            hwnd = self._get_native_hwnd_for_widget(target)
            if not hwnd:
                return False
            user32 = ctypes.windll.user32
            user32.ReleaseCapture()
            user32.SendMessageW(hwnd, 0x00A1, 0x0002, 0)  # WM_NCLBUTTONDOWN + HTCAPTION
            return True
        except Exception:
            return False

    def _begin_window_drag(self, event):
        if not self.custom_titlebar_enabled:
            return
        if self._window_is_maximized or str(self.root.state()) == "zoomed":
            ratio = (event.x_root - self.root.winfo_x()) / max(1, self.root.winfo_width())
            ratio = min(max(ratio, 0.1), 0.9)
            
            # Instantly unmaximize without animation so dragging isn't interrupted
            self.root.state("normal")
            target = getattr(self, '_windowed_geometry', None) or getattr(self, '_last_nonmax_geometry', None)
            if not target:
                target = self._build_default_windowed_geometry()
            
            w = target[2]
            h = target[3]
            
            self._window_is_maximized = False
            if hasattr(self, 'window_max_btn'):
                self.window_max_btn.config(text="□")
            try:
                self._update_titlebar_controls_offset()
                self._set_custom_window_chrome(True)
                self._ensure_taskbar_visibility()
            except Exception:
                pass
            
            x = int(event.x_root - (w * ratio))
            y = max(0, event.y_root - 12)
            self.root.geometry(f"{max(1, int(w))}x{max(1, int(h))}+{int(x)}+{int(y)}")
            self.root.update_idletasks()

        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root
        self._drag_win_x = self.root.winfo_x()
        self._drag_win_y = self.root.winfo_y()
        self._drag_last_x = event.x_root
        self._drag_last_y = event.y_root
        self._drag_target_x = self._drag_win_x
        self._drag_target_y = self._drag_win_y
        self._drag_active = True
        self._open_drag_preview()

    def _open_drag_preview(self):
        if not self._drag_preview_enabled or self._drag_preview_win is not None:
            return
        try:
            self.root.update_idletasks()
            self._drag_preview_w = max(500, self.root.winfo_width())
            self._drag_preview_h = max(320, self.root.winfo_height())

            preview = tk.Toplevel(self.root)
            preview.overrideredirect(True)
            preview.configure(bg="#0f0f0f")
            try:
                preview.attributes("-topmost", True)
            except Exception:
                pass
            preview.geometry(
                f"{self._drag_preview_w}x{self._drag_preview_h}+{self._drag_target_x}+{self._drag_target_y}"
            )

            shell = tk.Frame(preview, bg="#0f0f0f", highlightthickness=1, highlightbackground="#2f2f2f")
            shell.pack(fill="both", expand=True)
            center = tk.Frame(shell, bg="#0f0f0f")
            center.place(relx=0.5, rely=0.5, anchor="center")

            logo_path = resource_path("logo.png")
            if os.path.exists(logo_path):
                try:
                    img = Image.open(logo_path).convert("RGBA")
                    img = img.resize((92, 92), Image.Resampling.LANCZOS)
                    self._drag_preview_logo = ImageTk.PhotoImage(img)
                    tk.Label(center, image=self._drag_preview_logo, bg="#0f0f0f").pack(pady=(0, 14))
                except Exception:
                    pass

            tk.Label(
                center,
                text="NLC",
                font=("Segoe UI", 22, "bold"),
                fg="white",
                bg="#0f0f0f"
            ).pack()
            tk.Label(
                center,
                text="Drag anywhere you want",
                font=("Segoe UI", 11),
                fg="#A0A0A0",
                bg="#0f0f0f"
            ).pack(pady=(8, 0))

            self._drag_preview_win = preview
            self.root.withdraw()
        except Exception:
            self._drag_preview_win = None

    def _apply_window_drag_target(self):
        self._drag_apply_after_id = None
        if not self._drag_active:
            return
        if self._drag_preview_win and self._drag_preview_win.winfo_exists():
            self._drag_preview_win.geometry(
                f"{self._drag_preview_w}x{self._drag_preview_h}+{self._drag_target_x}+{self._drag_target_y}"
            )
        else:
            self.root.geometry(f"+{self._drag_target_x}+{self._drag_target_y}")

    def _schedule_window_drag_apply(self):
        if self._drag_apply_after_id is not None:
            return
        self._drag_apply_after_id = self.root.after(8, self._apply_window_drag_target)

    def _do_window_drag(self, event):
        if not self.custom_titlebar_enabled or not self._drag_active:
            return
        target_x = self._drag_win_x + (event.x_root - self._drag_start_x)
        target_y = self._drag_win_y + (event.y_root - self._drag_start_y)
        if target_x == self._drag_target_x and target_y == self._drag_target_y:
            return
        self._drag_target_x = target_x
        self._drag_target_y = target_y
        self._schedule_window_drag_apply()

    def _end_window_drag(self, _event=None):
        if self._drag_apply_after_id is not None:
            try:
                self.root.after_cancel(self._drag_apply_after_id)
            except Exception:
                pass
            self._drag_apply_after_id = None
        if self._drag_active:
            if self._drag_preview_win and self._drag_preview_win.winfo_exists():
                try:
                    self.root.deiconify()
                    self.root.geometry(
                        f"{self._drag_preview_w}x{self._drag_preview_h}+{self._drag_target_x}+{self._drag_target_y}"
                    )
                    self._set_custom_window_chrome(True)
                    self.root.lift()
                    self.root.focus_force()
                except Exception:
                    pass
                try:
                    self._drag_preview_win.destroy()
                except Exception:
                    pass
                self._drag_preview_win = None
                self._drag_preview_logo = None
            else:
                self.root.geometry(f"+{self._drag_target_x}+{self._drag_target_y}")
        elif self._drag_preview_win and self._drag_preview_win.winfo_exists():
            try:
                self._drag_preview_win.destroy()
            except Exception:
                pass
            self._drag_preview_win = None
            self._drag_preview_logo = None
            try:
                self.root.deiconify()
                self._set_custom_window_chrome(True)
            except Exception:
                pass
        self._drag_active = False

    def _bind_drag_widget(self, widget):
        widget.bind("<ButtonPress-1>", self._begin_window_drag)
        widget.bind("<B1-Motion>", self._do_window_drag)
        widget.bind("<ButtonRelease-1>", self._end_window_drag)
        widget.bind("<Double-Button-1>", lambda _e: self._toggle_window_maximize())

    def _get_work_area(self):
        if os.name == 'nt':
            try:
                class _RECT(ctypes.Structure):
                    _fields_ = [
                        ("left", ctypes.c_long),
                        ("top", ctypes.c_long),
                        ("right", ctypes.c_long),
                        ("bottom", ctypes.c_long),
                    ]

                class _MONITORINFO(ctypes.Structure):
                    _fields_ = [
                        ("cbSize", wintypes.DWORD),
                        ("rcMonitor", _RECT),
                        ("rcWork", _RECT),
                        ("dwFlags", wintypes.DWORD),
                    ]

                hwnd = self._get_native_hwnd()
                user32 = ctypes.windll.user32
                MONITOR_DEFAULTTONEAREST = 2
                monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
                if monitor:
                    mi = _MONITORINFO()
                    mi.cbSize = ctypes.sizeof(_MONITORINFO)
                    ok = user32.GetMonitorInfoW(monitor, ctypes.byref(mi))
                    if ok:
                        return (
                            int(mi.rcWork.left),
                            int(mi.rcWork.top),
                            int(mi.rcWork.right - mi.rcWork.left),
                            int(mi.rcWork.bottom - mi.rcWork.top),
                        )
            except Exception:
                pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _get_current_geometry_tuple(self):
        return (
            int(self.root.winfo_x()),
            int(self.root.winfo_y()),
            max(1, int(self.root.winfo_width())),
            max(1, int(self.root.winfo_height())),
        )

    def _is_geometry_maximized_like(self, geom, tolerance=14):
        try:
            wx, wy, ww, wh = self._get_work_area()
            x, y, w, h = geom
            right = int(x) + int(w)
            bottom = int(y) + int(h)
            work_right = int(wx) + int(ww)
            work_bottom = int(wy) + int(wh)
            return (
                int(x) <= int(wx) + tolerance
                and int(y) <= int(wy) + tolerance
                and right >= work_right - tolerance
                and bottom >= work_bottom - tolerance
            )
        except Exception:
            return False

    def _build_default_windowed_geometry(self):
        wx, wy, ww, wh = self._get_work_area()
        dw = max(900, min(1100, int(ww * 0.78)))
        dh = max(620, min(760, int(wh * 0.78)))
        dx = wx + max(0, (ww - dw) // 2)
        dy = wy + max(0, (wh - dh) // 2)
        return (dx, dy, dw, dh)

    def _set_geometry_tuple(self, geom):
        x, y, w, h = geom
        self.root.geometry(f"{max(1, int(w))}x{max(1, int(h))}+{int(x)}+{int(y)}")

    def _cancel_window_animation(self):
        if self._window_anim_after_id is not None:
            try:
                self.root.after_cancel(self._window_anim_after_id)
            except Exception:
                pass
            self._window_anim_after_id = None
        self._window_animating = False
        self._destroy_transition_overlay()

    def _animate_window_geometry(self, start_geom, end_geom, duration=150, steps=12, on_done=None, apply_geometry=None, cancel_existing=True):
        if cancel_existing:
            self._cancel_window_animation()
        self._window_animating = True
        step_delay = max(8, int(duration / max(1, steps)))
        apply_cb = apply_geometry if apply_geometry is not None else self._set_geometry_tuple

        sx, sy, sw, sh = start_geom
        ex, ey, ew, eh = end_geom

        def tick(i):
            t = i / max(1, steps)
            # Smoothstep easing
            eased = t * t * (3 - 2 * t)
            nx = round(sx + (ex - sx) * eased)
            ny = round(sy + (ey - sy) * eased)
            nw = round(sw + (ew - sw) * eased)
            nh = round(sh + (eh - sh) * eased)
            apply_cb((nx, ny, nw, nh))

            if i >= steps:
                self._window_animating = False
                self._window_anim_after_id = None
                if on_done:
                    on_done()
                return
            self._window_anim_after_id = self.root.after(step_delay, lambda: tick(i + 1))

        tick(0)

    def _destroy_transition_overlay(self):
        overlay = self._transition_overlay_win
        self._transition_overlay_win = None
        if overlay is not None:
            try:
                if overlay.winfo_exists():
                    overlay.destroy()
            except Exception:
                pass

    def _set_transition_overlay_geometry(self, geom):
        overlay = self._transition_overlay_win
        if overlay is None:
            self._set_geometry_tuple(geom)
            return
        try:
            if overlay.winfo_exists():
                x, y, w, h = geom
                overlay.geometry(f"{max(1, int(w))}x{max(1, int(h))}+{int(x)}+{int(y)}")
                return
        except Exception:
            pass
        self._set_geometry_tuple(geom)

    def _create_transition_overlay(self, geom, subtitle=""):
        if os.name != 'nt' or not self.custom_titlebar_enabled:
            return False
        try:
            self._destroy_transition_overlay()
            x, y, w, h = geom
            overlay = tk.Toplevel(self.root)
            overlay.overrideredirect(True)
            overlay.configure(bg="#0d0d0d")
            try:
                overlay.attributes("-topmost", True)
            except Exception:
                pass
            overlay.geometry(f"{max(1, int(w))}x{max(1, int(h))}+{int(x)}+{int(y)}")

            shell = tk.Frame(overlay, bg="#0d0d0d", highlightthickness=1, highlightbackground="#2f2f2f")
            shell.pack(fill="both", expand=True)

            center = tk.Frame(shell, bg="#0d0d0d")
            center.place(relx=0.5, rely=0.5, anchor="center")
            tk.Label(
                center,
                text="NLC",
                font=("Segoe UI", 22, "bold"),
                fg="white",
                bg="#0d0d0d"
            ).pack()
            if subtitle:
                tk.Label(
                    center,
                    text=subtitle,
                    font=("Segoe UI", 11),
                    fg="#A0A0A0",
                    bg="#0d0d0d"
                ).pack(pady=(8, 0))
            self._transition_overlay_win = overlay
            return True
        except Exception:
            self._destroy_transition_overlay()
            return False

    def _run_transition_with_overlay(self, start_geom, end_geom, duration=150, steps=12, subtitle="", finalize=None, on_done=None):
        self._cancel_window_animation()
        overlay_ready = self._create_transition_overlay(start_geom, subtitle=subtitle)
        apply_cb = self._set_transition_overlay_geometry if overlay_ready else self._set_geometry_tuple

        def finish():
            try:
                if finalize:
                    finalize()
            finally:
                self._destroy_transition_overlay()
                if on_done:
                    on_done()

        if start_geom == end_geom:
            finish()
            return

        self._animate_window_geometry(
            start_geom,
            end_geom,
            duration=duration,
            steps=steps,
            on_done=finish,
            apply_geometry=apply_cb,
            cancel_existing=False
        )

    def _toggle_window_maximize(self):
        if self._drag_active:
            return
        if self._window_animating:
            return
        current_state = str(self.root.state())
        current_geom = self._get_current_geometry_tuple()
        is_geom_max = self._is_geometry_maximized_like(current_geom, tolerance=24)
        currently_maximized = self._window_is_maximized or current_state == "zoomed" or is_geom_max
        if currently_maximized:
            if current_state == "zoomed":
                self.root.state("normal")
                self.root.update_idletasks()
            start = self._get_current_geometry_tuple()
            target = self._windowed_geometry if self._windowed_geometry else self._last_nonmax_geometry
            if not target:
                target = self._build_default_windowed_geometry()
            if self._is_geometry_maximized_like(target, tolerance=20):
                target = self._build_default_windowed_geometry()

            def on_restore_done():
                self._window_is_maximized = False
                self._windowed_geometry = target
                self._last_nonmax_geometry = target
                if hasattr(self, 'window_max_btn'):
                    self.window_max_btn.config(text="□")
                self._update_titlebar_controls_offset()
                self._set_custom_window_chrome(True)
                self._ensure_taskbar_visibility()

            def finalize_restore():
                self.root.state("normal")
                self._set_geometry_tuple(target)

            self._run_transition_with_overlay(
                start,
                target,
                duration=150,
                steps=12,
                subtitle="Restoring window",
                finalize=finalize_restore,
                on_done=on_restore_done
            )
        else:
            if current_state == "zoomed":
                self.root.state("normal")
                self.root.update_idletasks()
            start = self._get_current_geometry_tuple()
            if current_state == "normal" and not self._is_geometry_maximized_like(start, tolerance=20):
                self._windowed_geometry = start
                self._last_nonmax_geometry = start
            x, y, w, h = self._get_work_area()
            target = (x, y, max(1, w), max(1, h))

            def on_max_done():
                self._window_is_maximized = True
                if hasattr(self, 'window_max_btn'):
                    self.window_max_btn.config(text="❐")
                self._update_titlebar_controls_offset()
                self._set_custom_window_chrome(True)
                self._ensure_taskbar_visibility()

            def finalize_max():
                self.root.state("normal")
                self._set_geometry_tuple(target)

            self._run_transition_with_overlay(
                start,
                target,
                duration=150,
                steps=12,
                subtitle="Maximizing window",
                finalize=finalize_max,
                on_done=on_max_done
            )

    def _minimize_window(self):
        if self._drag_active:
            return
        if str(self.root.state()) == "iconic":
            return
        self._cancel_window_animation()
        start = self._get_current_geometry_tuple()
        self._pre_minimize_geometry = start
        self._pre_minimize_was_maximized = bool(self._window_is_maximized or str(self.root.state()) == "zoomed")
        wx, wy, ww, wh = self._get_work_area()
        tw = max(280, int(start[2] * 0.45))
        th = max(180, int(start[3] * 0.45))
        tx = wx + (ww - tw) // 2
        ty = wy + wh - th - 10
        self._pre_minimize_anchor_geometry = (tx, ty, tw, th)

        def finalize_min():
            self.root.state("iconic")

        self._run_transition_with_overlay(
            start,
            self._pre_minimize_anchor_geometry,
            duration=130,
            steps=10,
            subtitle="Minimizing window",
            finalize=finalize_min
        )

    def _sync_window_state(self, event=None):
        if not self.custom_titlebar_enabled:
            return
        if event and event.widget != self.root:
            return
        if self._drag_active or self._window_animating:
            return
        try:
            state = str(self.root.state())
            wx, wy, ww, wh = self._get_work_area()
            rx, ry, rw, rh = self._get_current_geometry_tuple()
            is_geom_max = self._is_geometry_maximized_like((rx, ry, rw, rh), tolerance=14)
            is_max = (state == "zoomed") or (state == "normal" and is_geom_max)
            if is_max != self._window_is_maximized:
                self._window_is_maximized = is_max
                if hasattr(self, 'window_max_btn'):
                    self.window_max_btn.config(text="❐" if is_max else "□")
                self._update_titlebar_controls_offset()
            if not self._window_is_maximized and state == "normal" and not is_geom_max:
                self._windowed_geometry = (rx, ry, rw, rh)
                self._last_nonmax_geometry = self._windowed_geometry
        except Exception:
            pass

    def _update_titlebar_controls_offset(self):
        if not hasattr(self, 'window_controls_frame'):
            return
        try:
            if self._window_is_maximized:
                self.window_controls_frame.pack_configure(padx=(0, 10))
            else:
                self.window_controls_frame.pack_configure(padx=(0, 10))
        except Exception:
            pass

    def setup_window_chrome(self):
        self.window_content = self.root
        if not self.custom_titlebar_enabled:
            return

        shell = tk.Frame(
            self.root,
            bg=COLORS.get('sidebar_bg', '#141414'),
            highlightthickness=0,
            bd=0
        )
        shell.pack(fill="both", expand=True)
        self.window_shell = shell

        titlebar = tk.Frame(shell, bg=COLORS.get('tab_bar_bg', '#252526'), height=36)
        titlebar.pack(fill="x", side="top")
        titlebar.pack_propagate(False)
        self.window_titlebar = titlebar

        left = tk.Frame(titlebar, bg=titlebar.cget("bg"))
        left.pack(side="left", fill="y")
        badge = tk.Label(left, text="NLC", bg=COLORS.get('play_btn_green', '#2D8F36'),
                         fg="white", font=("Segoe UI", 8, "bold"), padx=8, pady=4)
        badge.pack(side="left", padx=(8, 8), pady=6)
        title_lbl = tk.Label(left, text="New Launcher", font=("Segoe UI", 10, "bold"),
                             bg=titlebar.cget("bg"), fg=COLORS.get('text_primary', 'white'))
        title_lbl.pack(side="left")

        self._bind_drag_widget(titlebar)
        self._bind_drag_widget(left)
        self._bind_drag_widget(badge)
        self._bind_drag_widget(title_lbl)

        controls = tk.Frame(titlebar, bg=titlebar.cget("bg"))
        controls.pack(side="right", fill="y")
        self.window_controls_frame = controls

        def style_btn(btn, hover_bg, leave_bg=None):
            normal_bg = leave_bg if leave_bg is not None else titlebar.cget("bg")
            btn.config(bg=normal_bg, activebackground=hover_bg, activeforeground="white")
            btn.bind("<Enter>", lambda _e, b=btn, c=hover_bg: b.config(bg=c))
            btn.bind("<Leave>", lambda _e, b=btn, c=normal_bg: b.config(bg=c))

        btn_font = ("Segoe UI Symbol", 10)

        min_btn = tk.Button(controls, text="—", font=btn_font, fg=COLORS.get('text_primary', 'white'),
                            bd=0, relief="flat", width=4, cursor="hand2", command=self._minimize_window)
        min_btn.pack(side="left", fill="y")
        style_btn(min_btn, "#3A3A3A")

        self.window_max_btn = tk.Button(
            controls,
            text="□",
            font=btn_font,
            fg=COLORS.get('text_primary', 'white'),
            bd=0,
            relief="flat",
            width=4,
            cursor="hand2",
            command=self._toggle_window_maximize
        )
        self.window_max_btn.pack(side="left", fill="y")
        style_btn(self.window_max_btn, "#3A3A3A")

        close_btn = tk.Button(controls, text="✕", font=btn_font, fg="white",
                              bd=0, relief="flat", width=4, cursor="hand2", command=self._on_close)
        close_btn.pack(side="left", fill="y")
        style_btn(close_btn, "#C42B1C")

        self.window_content = tk.Frame(shell, bg=COLORS['main_bg'])
        self.window_content.pack(fill="both", expand=True)

        self.root.bind("<Map>", self._on_root_map_restore_chrome, add="+")
        self.root.bind("<Configure>", self._sync_window_state, add="+")
        self._set_custom_window_chrome(True)
        self.root.after(120, self._ensure_taskbar_visibility)

    def _get_native_hwnd_for_widget(self, widget):
        if os.name != 'nt':
            return 0
        try:
            base_hwnd = int(widget.winfo_id())
            GA_ROOT = 2
            user32 = ctypes.windll.user32
            root_hwnd = user32.GetAncestor(base_hwnd, GA_ROOT)
            return int(root_hwnd) if root_hwnd else base_hwnd
        except Exception:
            return 0

    def _prepare_dialog_window(self, win, owner=None):
        owner_win = owner if owner is not None else self.root
        _ensure_window_icon(win, owner=owner_win)
        self._register_dialog_window(win)
        if os.name == 'nt':
            try:
                win.transient(None)
            except Exception:
                pass
            try:
                win.grab_release()
            except Exception:
                pass
            _prime_taskbar_window(win)
            try:
                win.after(140, lambda w=win: _prime_taskbar_window(w) if w.winfo_exists() else None)
            except Exception:
                pass
            try:
                win.after(20, lambda w=win: (w.lift(), w.focus_force()) if w.winfo_exists() else None)
            except Exception:
                pass

    def _apply_custom_toplevel_chrome(self, win, title_text, close_command=None):
        owner = _resolve_dialog_parent(getattr(win, "master", None), self.root)
        if os.name == 'nt':
            try:
                win.withdraw()
            except Exception:
                pass

        def finalize_windows_dialog():
            if os.name != 'nt':
                return
            try:
                if not win.winfo_exists():
                    return
                win.deiconify()
                _schedule_window_centering(win, owner)
                win.lift()
                win.focus_force()
            except Exception:
                pass

        def schedule_windows_finalize():
            if os.name != 'nt':
                return
            finalize_windows_dialog()
            for delay in (40, 140, 320, 700):
                try:
                    win.after(delay, finalize_windows_dialog)
                except Exception:
                    pass

        if not (self.custom_titlebar_enabled and os.name == 'nt'):
            self._prepare_dialog_window(win)
            _schedule_window_centering(win, owner)
            schedule_windows_finalize()
            return win
        existing_content = getattr(win, "_custom_content_root", None)
        if existing_content and existing_content.winfo_exists():
            title_label = getattr(win, "_custom_title_label", None)
            if title_label and title_label.winfo_exists():
                try:
                    title_label.config(text=title_text)
                except Exception:
                    pass
            self._prepare_dialog_window(win)
            _schedule_window_centering(win, owner)
            schedule_windows_finalize()
            return existing_content

        try:
            win.overrideredirect(True)
        except Exception:
            self._prepare_dialog_window(win)
            _schedule_window_centering(win, owner)
            schedule_windows_finalize()
            return win

        shell = tk.Frame(win, bg=COLORS.get('sidebar_bg', '#141414'), highlightthickness=0, bd=0)
        shell.pack(fill="both", expand=True)

        titlebar = tk.Frame(shell, bg=COLORS.get('tab_bar_bg', '#252526'), height=34)
        titlebar.pack(fill="x", side="top")
        titlebar.pack_propagate(False)

        left = tk.Frame(titlebar, bg=titlebar.cget("bg"))
        left.pack(side="left", fill="y")
        badge = tk.Label(left, text="NLC", bg=COLORS.get('play_btn_green', '#2D8F36'),
                         fg="white", font=("Segoe UI", 8, "bold"), padx=8, pady=3)
        badge.pack(side="left", padx=(8, 8), pady=6)
        title_lbl = tk.Label(left, text=title_text, bg=titlebar.cget("bg"),
                             fg=COLORS.get('text_primary', 'white'), font=("Segoe UI", 9, "bold"))
        title_lbl.pack(side="left")

        drag_state = {"native": False, "sx": 0, "sy": 0, "wx": 0, "wy": 0, "lx": 0, "ly": 0}

        def drag_start(event):
            drag_state["native"] = False
            drag_state["sx"] = event.x_root
            drag_state["sy"] = event.y_root
            drag_state["wx"] = win.winfo_x()
            drag_state["wy"] = win.winfo_y()
            drag_state["lx"] = event.x_root
            drag_state["ly"] = event.y_root

        def drag_move(event):
            if drag_state["native"]:
                return
            dx = event.x_root - drag_state["lx"]
            dy = event.y_root - drag_state["ly"]
            if dx == 0 and dy == 0:
                return
            win.geometry(f"+{win.winfo_x() + dx}+{win.winfo_y() + dy}")
            drag_state["lx"] = event.x_root
            drag_state["ly"] = event.y_root

        for drag_widget in (titlebar, left, badge, title_lbl):
            drag_widget.bind("<ButtonPress-1>", drag_start)
            drag_widget.bind("<B1-Motion>", drag_move)

        close_btn = tk.Button(
            titlebar,
            text="✕",
            font=("Segoe UI Symbol", 10),
            fg="white",
            bg=titlebar.cget("bg"),
            bd=0,
            relief="flat",
            width=4,
            cursor="hand2",
            command=close_command if close_command else win.destroy
        )
        close_btn.pack(side="right", fill="y")
        close_btn.bind("<Enter>", lambda _e: close_btn.config(bg="#C42B1C"))
        close_btn.bind("<Leave>", lambda _e: close_btn.config(bg=titlebar.cget("bg")))

        body = tk.Frame(shell, bg=win.cget("bg"))
        body.pack(fill="both", expand=True)
        try:
            win._custom_content_root = body  # type: ignore[attr-defined]
            win._custom_title_label = title_lbl  # type: ignore[attr-defined]
        except Exception:
            pass
        self._prepare_dialog_window(win)
        _schedule_window_centering(win, owner)
        schedule_windows_finalize()
        return body

    def _get_toplevel_content_root(self, parent):
        content_root = getattr(parent, "_custom_content_root", None)
        if content_root and content_root.winfo_exists():
            return content_root
        return parent

    def _clear_toplevel_content(self, parent):
        content_root = self._get_toplevel_content_root(parent)
        for widget in content_root.winfo_children():
            widget.destroy()
        return content_root

    def _clear_dialog_focus_bindings(self):
        pending_after = getattr(self, "_dialog_raise_after_id", None)
        if pending_after is not None:
            try:
                self.root.after_cancel(pending_after)
            except Exception:
                pass
            self._dialog_raise_after_id = None
        self._dialog_raise_scheduled = False
        for seq, bind_id in getattr(self, "_dialog_focus_bindings", []):
            try:
                self.root.unbind(seq, bind_id)
            except Exception:
                pass
        self._dialog_focus_bindings = []

    def _cleanup_dialog_windows(self):
        cleaned = []
        for win in getattr(self, "_dialog_windows", []):
            try:
                if win is not None and win.winfo_exists():
                    cleaned.append(win)
            except Exception:
                continue
        self._dialog_windows = cleaned

    def _register_dialog_window(self, win):
        if win is None:
            return
        self._cleanup_dialog_windows()
        if win not in self._dialog_windows:
            self._dialog_windows.append(win)
            try:
                win.bind("<Destroy>", lambda _e, w=win: self._unregister_dialog_window(w), add="+")
            except Exception:
                pass
            try:
                win.bind("<FocusIn>", self._schedule_dialog_raise, add="+")
            except Exception:
                pass
        try:
            if not hasattr(win, "_nlc_force_above_launcher"):
                win._nlc_force_above_launcher = True  # type: ignore[attr-defined]
        except Exception:
            pass
        self._bind_dialog_focus_tracking()
        self._schedule_dialog_raise()

    def _unregister_dialog_window(self, win):
        if getattr(self, "_dialog_windows", None):
            self._dialog_windows = [w for w in self._dialog_windows if w is not win]
        if not self._dialog_windows:
            self._clear_dialog_focus_bindings()

    def _is_dialog_above_root(self, win):
        try:
            return bool(int(win.tk.call("wm", "stackorder", str(win), "isabove", str(self.root))))
        except Exception:
            return False

    def _raise_single_dialog_above_launcher(self, win):
        if os.name != "nt":
            try:
                win.transient(self.root)
            except Exception:
                pass
            if self._is_dialog_above_root(win):
                return
            try:
                win.lift(self.root)
            except Exception:
                win.lift()
            return

        try:
            win.lift(self.root)
        except Exception:
            try:
                win.lift()
            except Exception:
                return

        # Windows sometimes ignores plain lift() for custom/override windows.
        # Briefly toggling topmost forces z-order update, then immediately reverts.
        try:
            if not bool(getattr(win, "_nlc_force_above_launcher", False)):
                return
            now = time.time()
            last = float(getattr(win, "_nlc_last_topmost_bump", 0.0))
            if now - last < 0.35:
                return
            win._nlc_last_topmost_bump = now  # type: ignore[attr-defined]
            win.attributes("-topmost", True)
            win.after(
                35,
                lambda w=win: (w.winfo_exists() and w.attributes("-topmost", False))
            )
        except Exception:
            pass

    def _raise_dialogs_above_launcher(self):
        self._dialog_raise_scheduled = False
        self._dialog_raise_after_id = None
        self._dialog_last_raise_ts = time.time()
        try:
            if str(self.root.state()) in ("iconic", "withdrawn"):
                return
        except Exception:
            return

        self._cleanup_dialog_windows()
        if not self._dialog_windows:
            self._clear_dialog_focus_bindings()
            return

        for win in self._dialog_windows:
            try:
                if str(win.state()) in ("iconic", "withdrawn"):
                    continue
                self._raise_single_dialog_above_launcher(win)
            except Exception:
                continue

    def _schedule_dialog_raise(self, _event=None):
        if self._dialog_raise_scheduled:
            return
        now = time.time()
        elapsed = now - float(getattr(self, "_dialog_last_raise_ts", 0.0))
        min_interval = float(getattr(self, "_dialog_raise_min_interval", 0.12))
        wait_s = max(0.0, min_interval - elapsed)
        delay_ms = int(wait_s * 1000)
        self._dialog_raise_scheduled = True
        try:
            if delay_ms <= 0:
                self.root.after_idle(self._raise_dialogs_above_launcher)
            else:
                self._dialog_raise_after_id = self.root.after(delay_ms, self._raise_dialogs_above_launcher)
        except Exception:
            self._dialog_raise_scheduled = False
            self._dialog_raise_after_id = None

    def _bind_dialog_focus_tracking(self):
        self._clear_dialog_focus_bindings()
        bindings = []
        for seq in ("<FocusIn>", "<Map>", "<Activate>"):
            try:
                bind_id = self.root.bind(seq, self._schedule_dialog_raise, add="+")
                if bind_id:
                    bindings.append((seq, bind_id))
            except Exception:
                pass
        self._dialog_focus_bindings = bindings

    def _clear_onboarding_focus_bindings(self):
        for seq, bind_id in getattr(self, "_onboarding_focus_bindings", []):
            try:
                self.root.unbind(seq, bind_id)
            except Exception:
                pass
        self._onboarding_focus_bindings = []

    def _cancel_onboarding_raise_burst(self):
        pass

    def _raise_onboarding_above_launcher(self):
        wizard = getattr(self, "_onboarding_wizard", None)
        if not wizard:
            self._clear_onboarding_focus_bindings()
            self._cancel_onboarding_raise_burst()
            return
        try:
            if not wizard.winfo_exists():
                self._onboarding_wizard = None
                self._clear_onboarding_focus_bindings()
                self._cancel_onboarding_raise_burst()
                return
            if str(self.root.state()) in ("iconic", "withdrawn"):
                return
            if str(wizard.state()) == "withdrawn":
                wizard.deiconify()

            if os.name != "nt":
                wizard.transient(self.root)
                wizard.lift(self.root)
                try:
                    wizard.attributes("-topmost", True)
                except Exception:
                    pass
            else:
                wizard.lift()
                try:
                    wizard.focus_force()
                except Exception:
                    pass
        except Exception:
            pass

    def _schedule_onboarding_raise(self, _event=None):
        try:
            self.root.after_idle(self._raise_onboarding_above_launcher)
        except Exception:
            pass

    def _bind_onboarding_focus_tracking(self):
        self._clear_onboarding_focus_bindings()
        bindings = []
        for seq in ("<FocusIn>", "<Map>"):
            try:
                bind_id = self.root.bind(seq, self._schedule_onboarding_raise, add="+")
                if bind_id:
                    bindings.append((seq, bind_id))
            except Exception:
                pass
        self._onboarding_focus_bindings = bindings

    def _focus_main_window(self):
        try:
            state = str(self.root.state())
            if state in ("iconic", "withdrawn"):
                self.root.deiconify()
            self.root.lift()
            if os.name == 'nt':
                try:
                    self.root.attributes("-topmost", True)
                    self.root.after(
                        40,
                        lambda: self.root.winfo_exists() and self.root.attributes("-topmost", False)
                    )
                except Exception:
                    pass
            try:
                self.root.focus_force()
            except Exception:
                pass
        except Exception:
            pass

    def create_layout(self):
        root_parent = self.window_content if self.window_content is not None else self.root
        # 1. Sidebar (Left) - width 240px for modern unified Neo sidebar
        sb_width = METRICS.get('sidebar_width', 240)
        self.sidebar = tk.Frame(root_parent, bg=COLORS['sidebar_bg'], width=sb_width)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        
        # --- Sidebar Profile Section (Top Left) ---
        self.profile_frame = tk.Frame(self.sidebar, bg=COLORS['sidebar_bg'], cursor="hand2")
        self.profile_frame.pack(fill="x", ipady=8, padx=12, pady=10)
        self.profile_frame.bind("<Button-1>", lambda e: self.toggle_profile_menu())
        
        # Profile Icon (Player Head)
        self.sidebar_head_label = tk.Label(self.profile_frame, bg=COLORS['sidebar_bg'], cursor="hand2")
        self.sidebar_head_label.pack(side="left", padx=(4, 10))
        self.sidebar_head_label.bind("<Button-1>", lambda e: self.toggle_profile_menu())
        
        # Profile Text Container
        self.sidebar_text_frame = tk.Frame(self.profile_frame, bg=COLORS['sidebar_bg'], cursor="hand2")
        self.sidebar_text_frame.pack(side="left", fill="x", expand=True)
        self.sidebar_text_frame.bind("<Button-1>", lambda e: self.toggle_profile_menu())
        
        self.sidebar_username = tk.Label(
            self.sidebar_text_frame,
            text="Steve",
            font=(FONT_FAMILY, 10, "bold"),
            bg=COLORS['sidebar_bg'],
            fg=COLORS['text_primary'],
            anchor="w",
            cursor="hand2"
        )
        self.sidebar_username.pack(fill="x")
        self.sidebar_username.bind("<Button-1>", lambda e: self.toggle_profile_menu())
        
        self.sidebar_acct_type = tk.Label(
            self.sidebar_text_frame,
            text="Offline",
            font=(FONT_FAMILY, 8),
            bg=COLORS['sidebar_bg'],
            fg=COLORS['text_secondary'],
            anchor="w",
            cursor="hand2"
        )
        self.sidebar_acct_type.pack(fill="x")
        self.sidebar_acct_type.bind("<Button-1>", lambda e: self.toggle_profile_menu())

        self.sidebar_chevron = tk.Label(
            self.profile_frame,
            text="▾",
            font=(FONT_FAMILY, 9),
            bg=COLORS['sidebar_bg'],
            fg=COLORS.get('text_muted', '#6B7280'),
            cursor="hand2"
        )
        self.sidebar_chevron.pack(side="right", padx=(4, 4))
        self.sidebar_chevron.bind("<Button-1>", lambda e: self.toggle_profile_menu())

        self._attach_sidebar_hover(self.profile_frame)

        # In-sidebar Collapsible Account Drawer
        self.sidebar_account_drawer = tk.Frame(
            self.sidebar,
            bg=COLORS['card_bg'],
            highlightthickness=1,
            highlightbackground=COLORS.get('border_subtle', '#2D3139')
        )
        self.sidebar_account_drawer_open = False

        self.sidebar_nav_separator = tk.Frame(self.sidebar, bg=COLORS.get('separator', '#454545'), height=1)
        self.sidebar_nav_separator.pack(fill="x", padx=12, pady=(0, 16)) # Separator

        # --- Sidebar Menu Items ---
        self.sidebar_items = []
        self.nav_buttons = {}

        self.sidebar_nav_frame = tk.Frame(self.sidebar, bg=COLORS['sidebar_bg'])
        self.sidebar_nav_frame.pack(fill="both", expand=True)

        def _make_category_header(parent, title):
            lbl = tk.Label(
                parent,
                text=title,
                font=(FONT_FAMILY, 8, "bold"),
                fg=COLORS.get('text_muted', '#6B7280'),
                bg=COLORS['sidebar_bg']
            )
            lbl.pack(anchor="w", padx=16, pady=(12, 4))
            lbl._is_category_header = True  # type: ignore[attr-defined]
            return lbl

        def _neo_nav(parent, text, tab_name, icon_name=None, action=None):
            frame = tk.Frame(parent, bg=COLORS['sidebar_bg'], cursor="hand2", padx=8, pady=6)
            frame.pack(fill="x", padx=6, pady=1)
            self.sidebar_items.append(frame)

            # Left active accent indicator pill (hidden by default)
            accent_col = COLORS.get('accent_color', '#2ECC71')
            bar = tk.Frame(frame, bg=accent_col, width=3)
            frame._active_bar = bar  # type: ignore[attr-defined]

            if icon_name:
                icon_path = f"icons/{icon_name}" if not icon_name.startswith("icons/") else icon_name
                img = getattr(self, "get_icon_image", lambda x, y: None)(icon_path, (20, 20))
                if img:
                    lbl_img = tk.Label(frame, image=img, bg=COLORS['sidebar_bg'], cursor="hand2")
                    lbl_img.image = img # type: ignore
                    lbl_img.pack(side="left", padx=(6, 8))
                    frame._lbl_icon = lbl_img  # type: ignore[attr-defined]
                else:
                    lbl_sym = tk.Label(frame, text="•", font=(FONT_FAMILY, 11), bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'], cursor="hand2")
                    lbl_sym.pack(side="left", padx=(6, 8))
                    frame._lbl_icon = lbl_sym  # type: ignore[attr-defined]
            else:
                frame._lbl_icon = None

            lbl = tk.Label(
                frame,
                text=text,
                font=(FONT_FAMILY, 9, "bold"),
                bg=COLORS['sidebar_bg'],
                fg=COLORS['text_secondary'],
                cursor="hand2"
            )
            if icon_name:
                lbl.pack(side="left")
            else:
                lbl.pack(side="left", padx=(10, 4))
            frame._lbl_text = lbl  # type: ignore[attr-defined]

            def on_click(e):
                if action:
                    action()
                    self.set_active_sidebar(frame)
                    return
                self.set_active_sidebar(frame)
                self.show_tab(tab_name)

            frame.bind("<Button-1>", on_click)
            lbl.bind("<Button-1>", on_click)
            for c in frame.winfo_children():
                c.bind("<Button-1>", on_click)

            self._attach_sidebar_hover(frame)

            if tab_name == "Play":
                self.minecraft_btn_frame = frame  # type: ignore
                frame.is_active = True  # type: ignore
                lbl.config(fg=COLORS['text_primary'])
                anchor_widget = getattr(frame, "_lbl_icon", None) or getattr(frame, "_lbl_text", None)
                bar.pack(side="left", fill="y", padx=(0, 6), before=anchor_widget)

            return frame

        def build_main_sidebar():
            self._in_settings_sidebar = False
            self._in_modrinth_sidebar = False
            for widget in self.sidebar_nav_frame.winfo_children():
                widget.destroy()
            self.sidebar_items = [item for item in getattr(self, 'sidebar_items', []) if item.winfo_exists() and item.master != self.sidebar_nav_frame]
            
            _make_category_header(self.sidebar_nav_frame, "GAMES")
            _neo_nav(self.sidebar_nav_frame, "Minecraft Java", "Play", "grass_block_side.png")
            _neo_nav(self.sidebar_nav_frame, "Installations", "Installations", "crafting_table_front.png")
            _neo_nav(self.sidebar_nav_frame, "Modpacks", "Modpacks", "shulker_box.png")

            _make_category_header(self.sidebar_nav_frame, "DISCOVER")
            _neo_nav(self.sidebar_nav_frame, "Modrinth", "Modrinth", "crafting_table_top.png", action=build_modrinth_sidebar)
            _neo_nav(self.sidebar_nav_frame, "Addons", "Addons", "beacon.png")
            _neo_nav(self.sidebar_nav_frame, "Locker", "Locker", "enchanting_table_side.png")

        def exit_modrinth():
            if hasattr(self, 'close_project_details'):
                self.close_project_details()
            prev = getattr(self, '_prev_tab_modrinth', 'Play')
            if prev in ("Mods", "Settings"):
                prev = "Play"
            if hasattr(self, 'build_main_sidebar'):
                self.build_main_sidebar()
            self.show_tab(prev)

        def build_modrinth_sidebar():
            if getattr(self, 'current_tab', None) and self.current_tab != "Mods":
                self._prev_tab_modrinth = self.current_tab
            self._in_modrinth_sidebar = True
            self._in_settings_sidebar = False
            for widget in self.sidebar_nav_frame.winfo_children():
                widget.destroy()
            self.sidebar_items = [item for item in getattr(self, 'sidebar_items', []) if item.winfo_exists() and item.master != self.sidebar_nav_frame]
            
            _neo_nav(self.sidebar_nav_frame, "← Back", "Back", "observer_back.png", action=exit_modrinth)
            
            _make_category_header(self.sidebar_nav_frame, "MODRINTH NETWORK")
            
            def nav_modrinth(mode):
                def _action():
                    if hasattr(self, 'close_project_details'):
                        self.close_project_details()
                    self.show_tab("Mods")
                    if hasattr(self, 'switch_modrinth_mode'):
                        self.switch_modrinth_mode(mode)
                return _action

            mods_btn = _neo_nav(self.sidebar_nav_frame, "Mods", "Mods", "comparator_on.png", action=nav_modrinth("mod"))
            _neo_nav(self.sidebar_nav_frame, "Resource Packs", "Resource Packs", "painting.png", action=nav_modrinth("resourcepack"))
            _neo_nav(self.sidebar_nav_frame, "Modpacks", "Modpacks", "shulker_box.png", action=nav_modrinth("modpack"))
            _neo_nav(self.sidebar_nav_frame, "Shaders", "Shaders", "glowstone.png", action=nav_modrinth("shader"))

            self.show_tab("Mods")
            self.set_active_sidebar(mods_btn)

        def build_settings_sidebar():
            self._in_settings_sidebar = True
            self._in_modrinth_sidebar = False
            for widget in self.sidebar_nav_frame.winfo_children():
                widget.destroy()
            self.sidebar_items = [item for item in getattr(self, 'sidebar_items', []) if item.winfo_exists() and item.master != self.sidebar_nav_frame]
            self.settings_nav_items = {}

            # Back button to return to regular sidebar and previous screen
            _neo_nav(self.sidebar_nav_frame, "← Back", "Back", "observer_back.png", action=self.exit_settings)

            _make_category_header(self.sidebar_nav_frame, "SETTINGS")

            for cat_name, icon_name, desc in CATEGORIES:
                def make_cat_action(c=cat_name):
                    def _action():
                        self.show_tab("Settings")
                        if hasattr(self, 'switch_settings_category'):
                            self.switch_settings_category(c)
                    return _action

                btn_frame = _neo_nav(
                    self.sidebar_nav_frame,
                    cat_name,
                    cat_name,
                    icon_name=None,
                    action=make_cat_action(cat_name)
                )
                self.settings_nav_items[cat_name] = btn_frame

            cur_cat = getattr(self, 'current_settings_category', 'General')
            if cur_cat in self.settings_nav_items:
                self.set_active_sidebar(self.settings_nav_items[cur_cat])

        self.build_main_sidebar = build_main_sidebar
        self.build_modrinth_sidebar = build_modrinth_sidebar
        self.build_settings_sidebar = build_settings_sidebar
        build_main_sidebar()

        # Settings Link - Packed to bottom first to be at the very bottom
        self._create_sidebar_link("Settings", lambda: self.open_global_settings(), is_action=True, pack_side="bottom", icon="⚙")

        # Notifications Link - Packed to bottom next to be above Settings
        notif_frame = self._create_sidebar_link(
            "Notifications",
            lambda: self.toggle_notification_center(),
            is_action=True,
            pack_side="bottom",
            icon="bell_side.png",
            highlight_on_click=False
        )
        notif_frame._is_notif_toggle = True
        for child in notif_frame.winfo_children():
            child._is_notif_toggle = True

        self.sidebar_notif_badge = tk.Label(
            notif_frame,
            text="",
            bg=COLORS['accent_color'],
            fg="#FFFFFF",
            font=(FONT_FAMILY, 7, "bold"),
            padx=5,
            pady=1,
            cursor="hand2"
        )
        self.sidebar_notif_badge._keep_sidebar_bg = True
        self.sidebar_notif_badge._is_notif_toggle = True
        self.sidebar_notif_badge.bind("<Button-1>", lambda e: self.toggle_notification_center())

        # Screenshots Link - Packed to bottom next to be directly above Notifications
        self._create_sidebar_link(
            "Screenshots",
            lambda: self.show_tab("Screenshots"),
            is_action=True,
            pack_side="bottom",
            icon="painting.png"
        )

        # GitHub Link - Packed to bottom next to be above Screenshots
        self._create_sidebar_link("GitHub", "https://github.com/Amne-Dev/New-launcher", pack_side="bottom", icon="chiseled_bookshelf_occupied.png")

        # Download Queue UI (Initially hidden or empty)
        self.create_download_queue_ui()

        # 2. Main Content Area
        self.content_area = tk.Frame(root_parent, bg=COLORS['main_bg'])
        self.content_area.pack(side="right", fill="both", expand=True)

        # Permanent Neo style: top nav_bar is completely omitted
        self.nav_bar = None

        # 3. Tab Container
        self.tab_container = tk.Frame(self.content_area, bg=COLORS['main_bg'])
        self.tab_container.pack(fill="both", expand=True)
        
        # Initialize Tabs
        self.tabs = {}
        self.create_play_tab()
        self.create_locker_tab()
        self.create_installations_tab()
        self.create_modpacks_tab()
        self.create_settings_tab()
        self.create_addons_tab()
        self.create_screenshots_tab()
        
        # Trigger play selection
        if hasattr(self, 'minecraft_btn_frame'):
            self.set_active_sidebar(self.minecraft_btn_frame)
        self.show_tab("Play")

    def apply_theme(self, theme_key: str, custom_accent: Optional[str] = None, save: bool = True):
        """Apply a curated theme and optional custom accent, refreshing active widgets in real-time."""
        self.theme_id = theme_key if theme_key in THEMES else "dark_slate"
        self.custom_accent = custom_accent
        
        # Apply through ThemeManager
        new_tokens = THEME_MANAGER.apply(self.theme_id, self.custom_accent, notify=True)
        c = new_tokens['play_btn_green']
        self.accent_color_name = custom_accent or THEMES[self.theme_id]['default_accent']

        # Update ttk Styles
        style = ttk.Style()
        style.configure("Launcher.Horizontal.TProgressbar", background=c)

        # Update active window and frame chrome with independent error boundaries
        try:
            if hasattr(self, 'root') and self.root and self.root.winfo_exists():
                self.root.config(bg=new_tokens['main_bg'])
        except Exception as e:
            logger.debug("Failed updating root bg: %s", e)

        try:
            if hasattr(self, 'window_shell') and self.window_shell and self.window_shell.winfo_exists():
                self.window_shell.config(bg=new_tokens.get('sidebar_bg', '#141414'))
        except Exception as e:
            logger.debug("Failed updating window_shell bg: %s", e)

        try:
            if hasattr(self, 'window_titlebar') and self.window_titlebar and self.window_titlebar.winfo_exists():
                self.window_titlebar.config(bg=new_tokens.get('tab_bar_bg', '#252526'))
        except Exception as e:
            logger.debug("Failed updating window_titlebar bg: %s", e)

        try:
            if hasattr(self, 'window_content') and self.window_content and self.window_content.winfo_exists() and self.window_content != getattr(self, 'root', None):
                self.window_content.config(bg=new_tokens['main_bg'])
        except Exception as e:
            logger.debug("Failed updating window_content bg: %s", e)

        try:
            if hasattr(self, 'content_area') and self.content_area and self.content_area.winfo_exists():
                self.content_area.config(bg=new_tokens['main_bg'])
        except Exception as e:
            logger.debug("Failed updating content_area bg: %s", e)

        try:
            if hasattr(self, '_onboarding_view') and self._onboarding_view and self._onboarding_view.winfo_exists():
                self._onboarding_view.config(bg=new_tokens['main_bg'])
        except Exception as e:
            logger.debug("Failed updating _onboarding_view bg: %s", e)

        try:
            if hasattr(self, 'tab_container') and self.tab_container and self.tab_container.winfo_exists():
                self.tab_container.config(bg=new_tokens['main_bg'])
        except Exception as e:
            logger.debug("Failed updating tab_container bg: %s", e)

        for tab_name, tab_frame in getattr(self, 'tabs', {}).items():
            try:
                if tab_frame and tab_frame.winfo_exists():
                    tab_frame.config(bg=new_tokens['main_bg'])
            except Exception as e:
                logger.debug("Failed updating tab_frame %s bg: %s", tab_name, e)

        # Synchronize sidebar navigation & profile chrome
        try:
            self.refresh_sidebar_theme()
        except Exception as e:
            logger.error("Failed refreshing sidebar theme: %s", e)

        # Synchronize all screens
        for screen in ["Play", "Installations", "Modpacks", "Mods", "Locker", "Settings", "Addons"]:
            try:
                self.refresh_screen_theme(screen)
            except Exception as e:
                logger.error("Failed refreshing %s screen theme: %s", screen, e)

        # 1. Play Button chrome fallback
        try:
            if hasattr(self, 'play_container') and self.play_container.winfo_exists():
                self.play_container.config(bg=c)
            if hasattr(self, 'launch_btn') and self.launch_btn.winfo_exists():
                self.launch_btn.config(bg=c, activebackground=new_tokens.get('play_btn_hover', c), fg=new_tokens.get('play_btn_text', 'white'))
            if hasattr(self, 'launch_opts_btn') and self.launch_opts_btn.winfo_exists():
                self.launch_opts_btn.config(bg=c, activebackground=new_tokens.get('play_btn_hover', c), fg=new_tokens.get('play_btn_text', 'white'))
        except Exception as e:
            logger.debug("Failed updating play buttons: %s", e)

        # 2. Installations Tab button fallback
        try:
            if hasattr(self, 'new_inst_btn') and self.new_inst_btn.winfo_exists():
                self.new_inst_btn.config(bg=c)
        except Exception as e:
            logger.debug("Failed updating new_inst_btn: %s", e)

        # 3. Locker Tab
        try:
            if hasattr(self, 'locker_btns'):
                self.refresh_locker_view()
        except Exception as e:
            logger.debug("Failed updating locker view: %s", e)

        # 4. Global live refresh for all buttons across the entire application
        try:
            refresh_all_buttons()
        except Exception as e:
            logger.debug("Failed refreshing all buttons: %s", e)

        # 5. Synchronize TTK widget styles
        try:
            self.setup_styles()
        except Exception as e:
            logger.debug("Failed refreshing TTK styles: %s", e)

        if save:
            try:
                self.save_config(sync_ui=True, immediate=True)
            except Exception as e:
                logger.error("Failed saving config in apply_theme: %s", e)

    def refresh_screen_theme(self, screen_name: str):
        """Ensure the specified screen matches active theme colors."""
        try:
            if screen_name == "Play" and hasattr(self, 'refresh_play_screen_theme'):
                self.refresh_play_screen_theme()
            elif screen_name == "Installations" and hasattr(self, 'refresh_installations_screen_theme'):
                self.refresh_installations_screen_theme()
            elif screen_name == "Modpacks" and hasattr(self, 'refresh_modpacks_screen_theme'):
                self.refresh_modpacks_screen_theme()
            elif screen_name in ("Mods", "Modrinth") and hasattr(self, 'refresh_mods_screen_theme'):
                self.refresh_mods_screen_theme()
            elif screen_name == "Locker":
                if hasattr(self, 'refresh_locker_screen_theme'):
                    self.refresh_locker_screen_theme()
                elif hasattr(self, 'refresh_locker_view'):
                    self.refresh_locker_view()
            elif screen_name == "Settings" and hasattr(self, 'refresh_settings_screen_theme'):
                self.refresh_settings_screen_theme()
            elif screen_name == "Addons" and hasattr(self, 'refresh_addons_screen_theme'):
                self.refresh_addons_screen_theme()
        except Exception as e:
            logger.debug("Error refreshing screen theme for %s: %s", screen_name, e)

    def apply_accent_color(self, name_or_hex: str):
        _named_accents = {
            "Green": "#2D8F36", "Emerald": "#2ECC71", "Blue": "#3498DB", "Sapphire": "#3498DB",
            "Orange": "#E67E22", "Sunset": "#F39C12", "Purple": "#9B59B6", "Violet": "#9B59B6",
            "Red": "#E74C3C", "Crimson": "#E74C3C", "Cyan": "#00E5FF", "Neon Cyan": "#00E5FF",
            "Hot Pink": "#EC4899", "Pink": "#EC4899"
        }
        accent = _named_accents.get(name_or_hex, name_or_hex)
        self.apply_theme(getattr(self, "theme_id", "dark_slate"), custom_accent=accent)

    def perform_auto_update(self, asset_url, version, asset_name="", extra_data=None):
        if self._update_in_progress:
            return
        self._update_in_progress = True

        # 1. Download
        self._set_update_status(f"Downloading update {version}...", COLORS['accent_blue'])
        
        # Show Progress Bar
        self.root.after(0, self.show_update_progress)
        
        candidate = asset_name or os.path.basename(urllib.parse.urlsplit(asset_url).path)
        if candidate.lower().endswith(".cdc.json"):
            threading.Thread(target=self._download_cdc_update_thread, args=(asset_url, version, extra_data or {}), daemon=True).start()
        else:
            threading.Thread(target=self._download_update_thread, args=(asset_url, version, asset_name), daemon=True).start()

    def _download_cdc_update_thread(self, cdc_url, version, extra_data):
        try:
            updates_dir = os.path.join(self.config_dir, "updates")
            if not os.path.exists(updates_dir):
                os.makedirs(updates_dir)

            self.root.after(0, lambda: self.update_progress_label.config(text="Fetching update recipe...") if hasattr(self, "update_progress_label") else None)

            # 1. Download CDC index JSON
            r = requests.get(cdc_url, timeout=(8, 25))
            r.raise_for_status()
            remote_index = r.json()

            # 2. Verify signature
            verify_cdc_signature(remote_index)

            # 3. Locate installed local binary
            local_exe = (
                sys.executable
                if getattr(sys, "frozen", False)
                else os.path.abspath("NewLauncher.exe")
            )
            staged_exe = os.path.join(updates_dir, "NewLauncher.exe.staged")
            exe_url = extra_data.get("exe_url") or cdc_url.rsplit(".", 2)[0]

            self.root.after(0, lambda: self.update_progress_label.config(text="Applying differential slices...") if hasattr(self, "update_progress_label") else None)

            last_ui_tick = [0.0]
            def _progress(done, total):
                now = time.monotonic()
                if (now - last_ui_tick[0]) >= 0.08 or done == total:
                    last_ui_tick[0] = now
                    self.root.after(0, lambda c=done, t=total: self.update_download_progress(c, t))

            # 4. Assemble from local chunks + HTTP Range requests
            download_and_assemble_cdc(
                local_path=local_exe,
                remote_index=remote_index,
                download_url=exe_url,
                output_path=staged_exe,
                progress_callback=_progress,
            )

            # 5. Ensure runner exists
            runner_path = os.path.join(updates_dir, "NLCUpdater.exe")
            runner_url = extra_data.get("runner_url")
            runner_hash = str(remote_index.get("runnerSha256", "")).lower()

            need_download_runner = False
            if not os.path.exists(runner_path):
                need_download_runner = True
            elif runner_hash:
                with open(runner_path, "rb") as rf:
                    if hashlib.sha256(rf.read()).hexdigest().lower() != runner_hash:
                        need_download_runner = True

            if need_download_runner and runner_url:
                self.root.after(0, lambda: self.update_progress_label.config(text="Downloading updater runner...") if hasattr(self, "update_progress_label") else None)
                with requests.get(runner_url, stream=True, timeout=(8, 25)) as r_run:
                    r_run.raise_for_status()
                    runner_part = runner_path + ".part"
                    with open(runner_part, "wb") as f_run:
                        for chunk in r_run.iter_content(64 * 1024):
                            f_run.write(chunk)
                    os.replace(runner_part, runner_path)

            self.root.after(0, self.hide_update_progress)
            self.root.after(0, lambda: self._set_update_status("Update ready.", COLORS['success_green']))
            self.root.after(0, lambda: self._on_cdc_download_complete(staged_exe, runner_path))

        except Exception as e:
            logger.error("CDC update failed: %s", e)
            self.root.after(0, self.hide_update_progress)
            self.root.after(0, self._reset_update_state)
            self.root.after(0, lambda err=str(e): self._set_update_status(f"Update failed: {err}", COLORS['error_red']))

    def _on_cdc_download_complete(self, staged_exe, runner_path):
        btns = [
            ("Yes, Install", True, "primary"),
            ("I'll do it myself", "manual", "secondary"),
            ("No", False, "secondary")
        ]
        mbox = CustomMessagebox("Update Available", "Update downloaded successfully.\nInstall now? (The launcher will restart)",
                                type="yesno", buttons=btns, parent=self.root)
        result = mbox.result

        if result is True:
            self._launch_cdc_updater(staged_exe, runner_path)
        elif result == "manual":
            webbrowser.open("https://github.com/Amne-Dev/New-launcher/releases/latest")
            self._reset_update_state()
        else:
            self._reset_update_state()

    def _launch_cdc_updater(self, staged_exe, runner_path):
        try:
            if os.name != "nt":
                raise RuntimeError("Windows patch updates are only supported on Windows.")
            if not os.path.isfile(staged_exe):
                raise FileNotFoundError(staged_exe)
            if not os.path.isfile(runner_path):
                raise FileNotFoundError(runner_path)

            install_dir = (
                os.path.dirname(os.path.abspath(sys.executable))
                if getattr(sys, "frozen", False)
                else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            )

            self._set_update_status("Launching updater...", COLORS['accent_blue'])
            creationflags = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
            subprocess.Popen(
                [runner_path, "--replace-binary", staged_exe, "--target", install_dir, "--launcher-pid", str(os.getpid())],
                cwd=os.path.dirname(runner_path),
                close_fds=True,
                creationflags=creationflags,
            )
            self._begin_update_shutdown()
        except Exception as e:
            custom_showerror("Error", f"Could not launch updater: {e}")
            self._reset_update_state()

    def _download_update_thread(self, url, version="", asset_name=""):
        try:
            # Save to a persistent directory (avoid Temp/MEI issues)
            updates_dir = os.path.join(self.config_dir, "updates")
            if not os.path.exists(updates_dir):
                os.makedirs(updates_dir)
            
            # Determine filename
            candidate = asset_name or os.path.basename(urllib.parse.urlsplit(url).path)
            if candidate:
                filename = candidate
            elif os.name == "nt":
                filename = f"NLCUpdate-{CURRENT_VERSION}-to-{version}.zip" if version else "NLCUpdate.zip"
            else:
                filename = "NewLauncher_Update.exe"
            path = os.path.join(updates_dir, filename)
            part_path = path + ".part"
            
            self.root.after(0, lambda: self.update_progress_label.config(text="Connecting to update server...") if hasattr(self, "update_progress_label") else None)

            # Download with explicit connect/read timeouts and throttled UI updates.
            with requests.get(url, stream=True, timeout=(8, 25)) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))
                block_size = 1024 * 64
                wrote = 0
                last_ui_tick = 0.0

                with open(part_path, 'wb') as f:
                    for data in r.iter_content(block_size):
                        if not data:
                            continue
                        wrote += len(data)
                        f.write(data)

                        # Throttle to avoid flooding Tk event queue, which can look like a freeze.
                        now = time.monotonic()
                        if (now - last_ui_tick) >= 0.08:
                            last_ui_tick = now
                            if total_size > 0:
                                self.root.after(0, lambda c=wrote, t=total_size: self.update_download_progress(c, t))
                            else:
                                self.root.after(
                                    0,
                                    lambda b=wrote: self._set_update_status(
                                        f"Downloading update... {b // (1024 * 1024)} MB",
                                        COLORS['accent_blue']
                                    )
                                )

                # Final UI update to 100% for known-size downloads.
                if total_size > 0:
                    self.root.after(0, lambda c=wrote, t=total_size: self.update_download_progress(c, t))

            if wrote <= 0:
                raise RuntimeError("Downloaded file is empty.")

            with open(part_path, "rb") as f:
                signature = f.read(4)
            if filename.endswith(".zip"):
                if signature != b"PK\x03\x04":
                    raise RuntimeError("Downloaded patch is not a valid ZIP archive.")
            elif signature[:2] != b"MZ":
                raise RuntimeError("Downloaded update is not a valid Windows executable.")

            os.replace(part_path, path)
            
            # On Finish
            self.root.after(0, self.hide_update_progress)
            self.root.after(0, lambda: self._set_update_status("Update downloaded.", COLORS['success_green']))
            self.root.after(0, lambda: self._on_download_complete(path))
            
        except Exception as e:
            print(f"Update download failed: {e}")
            try:
                if 'part_path' in locals() and os.path.exists(part_path): # type: ignore
                    os.remove(part_path) # type: ignore
            except Exception:
                pass
            self.root.after(0, self.hide_update_progress)
            self.root.after(0, self._reset_update_state)
            self.root.after(0, lambda err=str(e): self._set_update_status(f"Update failed: {err}", COLORS['error_red']))

    def _on_download_complete(self, path):
         # Define custom buttons for the dialog
        btns = [
             ("Yes, Install", True, "primary"), 
             ("I'll do it myself", "manual", "secondary"), 
             ("No", False, "secondary")
        ]
        
        # Use underlying message box class directly for custom buttons since askyesno only supports yes/no
        mbox = CustomMessagebox("Update Available", "Update downloaded successfully.\nInstall now? (The launcher will restart)", 
                                type="yesno", buttons=btns, parent=self.root)
        result = mbox.result

        if result is True:
            if path.lower().endswith(".zip"):
                self._launch_patch_updater(path)
            elif path.lower().endswith(".exe"):
                self._launch_updater_and_exit(path)
            else:
                custom_showinfo("Manual Install", f"Update saved to:\n{path}\nPlease run it manually.")
                self._reset_update_state()
        elif result == "manual":
             webbrowser.open("https://github.com/Amne-Dev/New-launcher/releases/latest")
             self._reset_update_state()
        else:
            self._reset_update_state()

    def _reset_update_state(self):
        self._update_in_progress = False

    def _launch_patch_updater(self, patch_path):
        try:
            if os.name != "nt":
                raise RuntimeError("Windows patch updates are only supported on Windows.")
            if not os.path.isfile(patch_path):
                raise FileNotFoundError(patch_path)

            install_dir = (
                os.path.dirname(os.path.abspath(sys.executable))
                if getattr(sys, "frozen", False)
                else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            )
            updates_dir = os.path.join(self.config_dir, "updates")
            runner_path = os.path.join(updates_dir, "NLCUpdater.exe")
            runner_part_path = runner_path + ".part"

            with zipfile.ZipFile(patch_path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                verify_manifest_signature(manifest)
                if str(manifest.get("baseVersion", "")) != CURRENT_VERSION:
                    raise RuntimeError(
                        f"This patch is for version {manifest.get('baseVersion', 'unknown')}, "
                        f"but this launcher is version {CURRENT_VERSION}."
                    )
                runner_name = str(manifest.get("runner", "NLCUpdater.exe"))
                runner_hash = str(manifest.get("runnerSha256", "")).lower()
                runner_data = archive.read(f"files/{runner_name}")
            if not runner_hash or hashlib.sha256(runner_data).hexdigest() != runner_hash:
                raise RuntimeError("Patch runner checksum verification failed.")
            with open(runner_part_path, "wb") as runner_file:
                runner_file.write(runner_data)
            os.replace(runner_part_path, runner_path)

            self._set_update_status("Launching patch runner...", COLORS['accent_blue'])
            creationflags = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
            subprocess.Popen(
                [runner_path, "--patch", patch_path, "--target", install_dir, "--launcher-pid", str(os.getpid())],
                cwd=updates_dir,
                close_fds=True,
                creationflags=creationflags,
            )
            self._begin_update_shutdown()
        except Exception as e:
            try:
                if 'runner_part_path' in locals() and os.path.exists(runner_part_path):
                    os.remove(runner_part_path)
            except Exception:
                pass
            custom_showerror("Error", f"Could not launch patch installer: {e}")
            self._reset_update_state()

    def _launch_updater_and_exit(self, path):
        try:
            if not os.path.isfile(path):
                raise FileNotFoundError(path)

            self._set_update_status("Launching installer...", COLORS['accent_blue'])
            self.root.after(0, self.hide_update_progress)

            launched = False
            if os.name == 'nt':
                try:
                    creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    subprocess.Popen([path], cwd=os.path.dirname(path), close_fds=True, creationflags=creationflags)
                    launched = True
                except Exception:
                    # Fallback, e.g. if creation flags fail in specific environments.
                    os.startfile(path)
                    launched = True
            else:
                subprocess.Popen([path], cwd=os.path.dirname(path), close_fds=True)
                launched = True

            if launched:
                self._begin_update_shutdown()
            else:
                raise RuntimeError("Failed to start updater.")
        except Exception as e:
            custom_showerror("Error", f"Could not launch update: {e}")
            self._reset_update_state()

    def _begin_update_shutdown(self):
        if self._update_shutdown_started:
            return
        self._update_shutdown_started = True

        def _shutdown():
            try:
                self.stop_agent_process()
            except Exception:
                pass
            try:
                if hasattr(self, 'tray_icon') and self.tray_icon:
                    self.tray_icon.stop()
            except Exception:
                pass
            try:
                self.root.destroy()
            except Exception:
                pass
            os._exit(0)

        # Small delay lets spawned updater initialize before process exit.
        self.root.after(160, _shutdown)

    def show_whats_new(self, version):
        """Fetches the changelog for the current version and displays it on first launch after update."""
        mgr = get_modal_manager(self.root)
        if not mgr:
            return

        def build_content(body_frame, close_modal):
            tk.Label(body_frame, text=f"You are now running version {version}", font=("Segoe UI", 10), 
                     bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w", pady=(0, 10))

            text_area = scrolledtext.ScrolledText(body_frame, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg=COLORS['text_primary'],
                                                  relief="flat", wrap="word", state="normal")
            text_area.pack(fill="both", expand=True)
            text_area.insert("1.0", "Fetching release notes from GitHub...\n\n")
            text_area.config(state="disabled")

            actions = tk.Frame(body_frame, bg=COLORS['card_bg'], pady=10)
            actions.pack(fill="x", side="bottom")
            self._make_btn(actions, "Awesome, Let's Game!", style="primary", font_size=10, 
                           command=close_modal).pack(anchor="center")

            def fetch_changelog():
                try:
                    url = f"https://api.github.com/repos/Amne-Dev/New-launcher/releases/tags/v{version}"
                    r = requests.get(url, timeout=5)
                    if r.status_code == 200:
                        data = r.json()
                        body = data.get("body", "No description provided for this release.")
                        self.root.after(0, lambda b=body: update_text(b))
                    else:
                        self.root.after(0, lambda: update_text(f"Could not load release notes automatically (Status {r.status_code}).\nCheck out the GitHub releases page!"))
                except Exception as e:
                    self.root.after(0, lambda err=str(e): update_text(f"Failed to fetch release notes: {err}"))

            def update_text(msg):
                try:
                    if text_area.winfo_exists():
                        text_area.config(state="normal")
                        text_area.delete("1.0", "end")
                        text_area.insert("1.0", msg)
                        text_area.config(state="disabled")
                except Exception:
                    pass

            threading.Thread(target=fetch_changelog, daemon=True).start()

        mgr.show_modal(f"✨ What's New in v{version} ✨", build_content, width=620, height=480)

    def show_onboarding_wizard(self):
        """Shows the First Run Wizard — modern in-app view without popups, with step indicators and smooth transitions."""
        if getattr(self, "_in_onboarding", False) and hasattr(self, "_onboarding_view") and self._onboarding_view and self._onboarding_view.winfo_exists():
            return

        self._in_onboarding = True

        root_parent = self.window_content if self.window_content is not None else self.root

        # Hide main launcher chrome while onboarding is active
        if hasattr(self, 'sidebar') and self.sidebar and self.sidebar.winfo_exists():
            self.sidebar.pack_forget()
        if hasattr(self, 'content_area') and self.content_area and self.content_area.winfo_exists():
            self.content_area.pack_forget()

        # Remove previous onboarding view if any
        if hasattr(self, '_onboarding_view') and self._onboarding_view and self._onboarding_view.winfo_exists():
            try:
                self._onboarding_view.destroy()
            except Exception:
                pass

        main_bg = COLORS['main_bg']
        card_bg = COLORS['card_bg']
        input_bg = COLORS['input_bg']
        text_primary = COLORS['text_primary']
        text_secondary = COLORS.get('text_secondary', '#A0AAB0')
        border_col = COLORS.get('border_subtle', '#33373E')

        onboarding_view = tk.Frame(root_parent, bg=main_bg)
        self._onboarding_view = onboarding_view
        onboarding_view.pack(fill="both", expand=True)

        # ── Step indicator (top bar) ──
        STEPS = ["Account", "Preferences", "Theme", "Ready"]
        step_bar = tk.Frame(onboarding_view, bg=COLORS.get('sidebar_bg', '#1E1E1E'), height=56)
        step_bar.pack(fill="x")
        step_bar.pack_propagate(False)

        # Logo/title at left
        tk.Label(
            step_bar,
            text="NEW LAUNCHER",
            font=("Segoe UI", 10, "bold"),
            bg=COLORS.get('sidebar_bg', '#1E1E1E'),
            fg=text_secondary,
        ).pack(side="left", padx=24)

        # Exit/Skip Setup link at far right
        exit_btn = tk.Label(
            step_bar,
            text="✕ Exit Setup",
            font=("Segoe UI", 9),
            bg=COLORS.get('sidebar_bg', '#1E1E1E'),
            fg=text_secondary,
            cursor="hand2",
        )
        exit_btn.pack(side="right", padx=24)
        exit_btn.bind("<Button-1>", lambda e: self.close_onboarding_wizard(start_tour=False))
        exit_btn.bind("<Enter>", lambda e: exit_btn.config(fg="white"))
        exit_btn.bind("<Leave>", lambda e: exit_btn.config(fg=text_secondary))

        # Step dots
        dots_frame = tk.Frame(step_bar, bg=COLORS.get('sidebar_bg', '#1E1E1E'))
        dots_frame.pack(side="right", padx=16)
        dot_labels = []
        dot_inactive_bg = COLORS.get('input_bg', '#2E333E')
        dot_inactive_fg = COLORS.get('text_muted', '#6B7280')
        accent_color = COLORS.get('accent_color', '#2ECC71')

        for i, step_name in enumerate(STEPS):
            dot_f = tk.Frame(dots_frame, bg=COLORS.get('sidebar_bg', '#1E1E1E'))
            dot_f.pack(side="left", padx=10)
            dot = tk.Label(dot_f, text=f"{i + 1}", font=("Segoe UI", 8, "bold"),
                           bg=dot_inactive_bg, fg="white", width=2, height=1)
            dot.pack(side="left", padx=(0, 4))
            lbl = tk.Label(dot_f, text=step_name, font=("Segoe UI", 8),
                           bg=COLORS.get('sidebar_bg', '#1E1E1E'), fg=dot_inactive_fg)
            lbl.pack(side="left")
            dot_labels.append((dot, lbl))

        def update_dots(active_idx):
            for i, (dot, lbl) in enumerate(dot_labels):
                if i < active_idx:
                    dot.config(text="✓", bg=COLORS.get('success_green', '#2D8F36'), fg="white")
                    lbl.config(fg=COLORS.get('success_green', '#2D8F36'))
                elif i == active_idx:
                    dot.config(text=f"{i + 1}", bg=accent_color, fg="white")
                    lbl.config(fg="white")
                else:
                    dot.config(text=f"{i + 1}", bg=dot_inactive_bg, fg=dot_inactive_fg)
                    lbl.config(fg=dot_inactive_fg)

        # ── Scrollable or centered content area ──
        content_canvas = tk.Canvas(onboarding_view, bg=main_bg, highlightthickness=0)
        content_canvas.pack(fill="both", expand=True)

        content = tk.Frame(content_canvas, bg=main_bg)
        content_window = content_canvas.create_window((0, 0), window=content, anchor="n")

        def center_content(event):
            content_canvas.coords(content_window, event.width // 2, 20)

        content_canvas.bind("<Configure>", center_content)

        self.wizard_account_data = {}

        def clear_page():
            for w in content.winfo_children():
                w.destroy()

        def make_btn(parent, text, bg_color, command, width=20, font_size=10, bold=True):
            weight = "bold" if bold else ""
            b = tk.Button(parent, text=text, font=("Segoe UI", font_size, weight),
                         bg=bg_color, fg="white", activebackground=bg_color,
                         activeforeground="white", relief="flat", cursor="hand2",
                         command=command, bd=0)
            b.config(padx=16, pady=8)
            return b

        def make_link(parent, text, command):
            l = tk.Label(parent, text=text, font=("Segoe UI", 9),
                        bg=main_bg, fg=text_secondary, cursor="hand2")
            l.bind("<Button-1>", lambda e: command())
            l.bind("<Enter>", lambda e: l.config(fg="white"))
            l.bind("<Leave>", lambda e: l.config(fg=text_secondary))
            return l

        # STEP 0 — Account Type Selection
        def show_step_account_type():
            clear_page()
            update_dots(0)

            tk.Frame(content, bg=main_bg, height=20).pack()

            tk.Label(content, text="Welcome to New Launcher",
                    font=("Segoe UI", 22, "bold"), fg="white",
                    bg=main_bg).pack()
            tk.Label(content, text="Choose how you want to sign in",
                    font=("Segoe UI", 11), fg=text_secondary,
                    bg=main_bg).pack(pady=(6, 26))

            cards = tk.Frame(content, bg=main_bg)
            cards.pack()

            options = [
                ("Microsoft", "#0078D7", "Official Mojang account", show_step_microsoft),
                ("Ely.by", "#3498DB", "Third-party auth server", show_step_elyby),
                ("Offline", "#555555", "Play without authentication", show_step_offline),
            ]

            for name, color, desc, cmd in options:
                card = tk.Frame(cards, bg=card_bg, cursor="hand2",
                               highlightbackground=border_col, highlightthickness=1)
                card.pack(side="left", padx=10, ipadx=0, ipady=0)
                card.config(width=190, height=150)
                card.pack_propagate(False)

                strip = tk.Frame(card, bg=color, height=4)
                strip.pack(fill="x")

                inner_card = tk.Frame(card, bg=card_bg, cursor="hand2")
                inner_card.pack(fill="both", expand=True, padx=16, pady=14)

                tk.Label(inner_card, text=name, font=("Segoe UI", 13, "bold"),
                        fg="white", bg=card_bg, cursor="hand2",
                        anchor="w").pack(anchor="w")
                tk.Label(inner_card, text=desc, font=("Segoe UI", 9),
                        fg=text_secondary, bg=card_bg, cursor="hand2",
                        anchor="w", wraplength=150).pack(anchor="w", pady=(6, 0))

                def on_enter(e, c=card):
                    c.config(highlightbackground="#808080")
                def on_leave(e, c=card):
                    c.config(highlightbackground=border_col)
                def on_click(e, fn=cmd):
                    fn()

                for w in [card, inner_card] + inner_card.winfo_children():
                    w.bind("<Enter>", on_enter)
                    w.bind("<Leave>", on_leave)
                    w.bind("<Button-1>", on_click)

        # STEP 1a — Microsoft Login
        def show_step_microsoft():
            clear_page()
            update_dots(0)

            tk.Frame(content, bg=main_bg, height=20).pack()
            tk.Label(content, text="Microsoft Account",
                    font=("Segoe UI", 18, "bold"), fg="white",
                    bg=main_bg).pack()

            status_lbl = tk.Label(content, text="Connecting to Microsoft...",
                                 font=("Segoe UI", 10), bg=main_bg,
                                 fg=text_secondary, wraplength=450)
            status_lbl.pack(pady=(12, 8))

            code_frame = tk.Frame(content, bg=card_bg,
                                 highlightbackground=border_col, highlightthickness=1)
            code_frame.pack(pady=10, ipadx=30, ipady=12)

            code_lbl = tk.Label(code_frame, text="--------",
                               font=("Consolas", 28, "bold"), bg=card_bg,
                               fg="white")
            code_lbl.pack()

            url_lbl = tk.Label(content, text="", font=("Segoe UI", 10, "underline"),
                              bg=main_bg, fg=COLORS.get('accent_blue', '#3498DB'), cursor="hand2")
            url_lbl.pack(pady=4)

            btn_row = tk.Frame(content, bg=main_bg)
            btn_row.pack(pady=12)

            copy_btn = make_btn(btn_row, "Copy Code", COLORS.get('input_bg', '#404040'),
                               lambda: None, font_size=9, bold=False)
            copy_btn.pack(side="left", padx=6)
            copy_btn.config(state="disabled")

            make_link(btn_row, "← Back to Options", show_step_account_type).pack(side="left", padx=12)

            url_lbl.bind("<Button-1>", lambda e: webbrowser.open(url_lbl.cget("text")) if url_lbl.cget("text") else None)

            inst_lbl = tk.Label(content, text="",
                               font=("Segoe UI", 9), bg=main_bg,
                               fg=text_secondary, justify="center")
            inst_lbl.pack(pady=(8, 0))

            def run_flow():
                try:
                    client_id = MSA_CLIENT_ID
                    scope = "XboxLive.signin offline_access"
                    if not onboarding_view.winfo_exists(): return
                    status_lbl.config(text="Requesting device code...")

                    r = requests.post("https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode",
                                      data={"client_id": client_id, "scope": scope})
                    if r.status_code != 200:
                        if onboarding_view.winfo_exists():
                            status_lbl.config(text=f"Error: {r.text}", fg=COLORS['error_red'])
                        return

                    data = r.json()
                    user_code = data.get("user_code")
                    verification_uri = data.get("verification_uri")
                    device_code = data.get("device_code")
                    interval = data.get("interval", 5)

                    if onboarding_view.winfo_exists():
                        code_lbl.config(text=user_code)
                        url_lbl.config(text=verification_uri)
                        status_lbl.config(text="Sign in using the verification code below")
                        inst_lbl.config(text="1. Click the link  2. Paste the code  3. Sign in with Microsoft")
                        copy_btn.config(state="normal",
                            command=lambda: (self.root.clipboard_clear(),
                                             self.root.clipboard_append(user_code),
                                             copy_btn.config(text="Copied!", fg=COLORS.get('success_green', '#2D8F36')),
                                             self.root.after(1500, lambda: copy_btn.config(text="Copy Code", fg="white") if copy_btn.winfo_exists() else None)))

                    while onboarding_view.winfo_exists():
                        time.sleep(interval)
                        r_poll = requests.post("https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
                            data={"grant_type": "device_code", "client_id": client_id, "device_code": device_code})

                        if r_poll.status_code == 200:
                            token_data = r_poll.json()
                            access_token = token_data["access_token"]
                            refresh_token = token_data["refresh_token"]

                            if onboarding_view.winfo_exists(): status_lbl.config(text="Authenticating with Xbox Live...")
                            xbl = minecraft_launcher_lib.microsoft_account.authenticate_with_xbl(access_token)

                            if onboarding_view.winfo_exists(): status_lbl.config(text="Authenticating with XSTS...")
                            xsts = minecraft_launcher_lib.microsoft_account.authenticate_with_xsts(xbl["Token"])

                            if onboarding_view.winfo_exists(): status_lbl.config(text="Authenticating with Minecraft...")
                            mc_auth = minecraft_launcher_lib.microsoft_account.authenticate_with_minecraft(
                                xbl["DisplayClaims"]["xui"][0]["uhs"], xsts["Token"])

                            if onboarding_view.winfo_exists(): status_lbl.config(text="Fetching profile...")
                            profile = minecraft_launcher_lib.microsoft_account.get_profile(mc_auth["access_token"])

                            self.wizard_account_data = {
                                "name": profile["name"], "uuid": profile["id"],
                                "type": "microsoft", "skin_path": "",
                                "access_token": mc_auth["access_token"],
                                "refresh_token": refresh_token
                            }
                            if onboarding_view.winfo_exists():
                                self.root.after(0, save_account_and_continue)
                            break

                        err = r_poll.json()
                        err_code = err.get("error")
                        if err_code == "authorization_pending": continue
                        elif err_code == "slow_down": interval += 2
                        elif err_code == "expired_token":
                            if onboarding_view.winfo_exists():
                                status_lbl.config(text="Code expired. Please try again.", fg=COLORS['error_red'])
                            break
                        else:
                            if onboarding_view.winfo_exists():
                                status_lbl.config(text=f"Error: {err.get('error_description', 'Unknown')}", fg=COLORS['error_red'])
                            break
                except Exception as e:
                    logger.error("Wizard Login Error: %s", e)
                    if onboarding_view.winfo_exists():
                        status_lbl.config(text=f"Error: {e}", fg=COLORS['error_red'])

            threading.Thread(target=run_flow, daemon=True).start()

        # STEP 1b — Offline
        def show_step_offline():
            clear_page()
            update_dots(0)

            tk.Frame(content, bg=main_bg, height=30).pack()
            tk.Label(content, text="Offline Mode",
                    font=("Segoe UI", 18, "bold"), fg="white",
                    bg=main_bg).pack()
            tk.Label(content, text="Enter a username to play without authentication",
                    font=("Segoe UI", 10), fg=text_secondary,
                    bg=main_bg).pack(pady=(6, 26))

            form = tk.Frame(content, bg=main_bg)
            form.pack(fill="x", padx=100)

            tk.Label(form, text="USERNAME", font=("Segoe UI", 8, "bold"),
                    fg=text_secondary, bg=main_bg).pack(anchor="w")
            name_var = tk.StringVar(value="Player")
            e = tk.Entry(form, textvariable=name_var, font=("Segoe UI", 12),
                        bg=input_bg, fg="white", relief="flat",
                        insertbackground="white", bd=0)
            e.pack(fill="x", ipady=8, pady=(4, 0))
            tk.Frame(form, bg=border_col, height=2).pack(fill="x")
            e.focus_set()

            btn_frame = tk.Frame(form, bg=main_bg)
            btn_frame.pack(fill="x", pady=(24, 0))

            def do_next():
                name = name_var.get().strip() or "Player"
                self.wizard_account_data = {
                    "name": name, "type": "offline",
                    "skin_path": "", "uuid": ""
                }
                save_account_and_continue()

            make_btn(btn_frame, "Continue", COLORS.get('success_green', '#2D8F36'),
                    do_next).pack(fill="x")
            make_link(btn_frame, "← Back to Options", show_step_account_type).pack(anchor="w", pady=(12, 0))

        # STEP 1c — Ely.by
        def show_step_elyby():
            clear_page()
            update_dots(0)

            tk.Frame(content, bg=main_bg, height=24).pack()
            tk.Label(content, text="Ely.by Login",
                    font=("Segoe UI", 18, "bold"), fg="white",
                    bg=main_bg).pack()
            tk.Label(content, text="Sign in with your Ely.by credentials",
                    font=("Segoe UI", 10), fg=text_secondary,
                    bg=main_bg).pack(pady=(6, 20))

            form = tk.Frame(content, bg=main_bg)
            form.pack(fill="x", padx=100)

            tk.Label(form, text="USERNAME / EMAIL", font=("Segoe UI", 8, "bold"),
                    fg=text_secondary, bg=main_bg).pack(anchor="w")
            ue = tk.Entry(form, font=("Segoe UI", 11), bg=input_bg,
                         fg="white", relief="flat", insertbackground="white", bd=0)
            ue.pack(fill="x", ipady=7, pady=(4, 0))
            tk.Frame(form, bg=border_col, height=2).pack(fill="x")

            tk.Frame(form, bg=main_bg, height=14).pack()

            tk.Label(form, text="PASSWORD", font=("Segoe UI", 8, "bold"),
                    fg=text_secondary, bg=main_bg).pack(anchor="w")
            pe = tk.Entry(form, font=("Segoe UI", 11), bg=input_bg,
                         fg="white", relief="flat", show="●",
                         insertbackground="white", bd=0)
            pe.pack(fill="x", ipady=7, pady=(4, 0))
            tk.Frame(form, bg=border_col, height=2).pack(fill="x")

            err_lbl = tk.Label(form, text="", font=("Segoe UI", 9),
                              bg=main_bg, fg=COLORS['error_red'])
            err_lbl.pack(anchor="w", pady=(8, 0))

            ue.focus_set()

            btn_frame = tk.Frame(form, bg=main_bg)
            btn_frame.pack(fill="x", pady=(16, 0))

            def do_auth():
                user_input = ue.get().strip()
                pw = pe.get().strip()
                if not user_input or not pw:
                    err_lbl.config(text="Please fill in both fields")
                    return
                err_lbl.config(text="")
                res = ElyByAuth.authenticate(user_input, pw)
                if "error" in res:
                    err_lbl.config(text=res['error'])
                else:
                    prof = cast(dict, res.get("selectedProfile", {}))
                    name = prof.get("name", user_input)
                    self.wizard_account_data = {
                        "name": name, "type": "ely.by",
                        "uuid": prof.get("id", ""),
                        "skin_path": ""
                    }
                    save_account_and_continue()

            make_btn(btn_frame, "Sign In", "#3498DB", do_auth).pack(fill="x")
            make_link(btn_frame, "← Back to Options", show_step_account_type).pack(anchor="w", pady=(12, 0))

        # Save & transition
        def save_account_and_continue():
            is_default = False
            if len(self.profiles) == 1:
                p = self.profiles[0]
                if p.get("name") == "Steve" and p.get("type") == "offline" and not p.get("uuid"):
                    is_default = True

            if not self.profiles or is_default:
                self.profiles = [self.wizard_account_data]
                self.current_profile_index = 0
            else:
                self.profiles.append(self.wizard_account_data)
                self.current_profile_index = len(self.profiles) - 1

            self.save_config(sync_ui=False)
            self.update_active_profile()
            show_step_preferences()

        # STEP 2 — Preferences
        def show_step_preferences():
            clear_page()
            update_dots(1)

            tk.Frame(content, bg=main_bg, height=24).pack()
            tk.Label(content, text="Game Preferences",
                    font=("Segoe UI", 18, "bold"), fg="white",
                    bg=main_bg).pack()
            tk.Label(content, text="Configure memory and launcher behavior",
                    font=("Segoe UI", 10), fg=text_secondary,
                    bg=main_bg).pack(pady=(6, 20))

            form = tk.Frame(content, bg=main_bg)
            form.pack(fill="x", padx=60)

            # RAM section
            ram_card = tk.Frame(form, bg=card_bg, padx=18, pady=14,
                                highlightbackground=border_col, highlightthickness=1)
            ram_card.pack(fill="x", pady=(0, 16))

            ram_header = tk.Frame(ram_card, bg=card_bg)
            ram_header.pack(fill="x")
            tk.Label(ram_header, text="Memory Allocation",
                    font=("Segoe UI", 11, "bold"), fg="white",
                    bg=card_bg).pack(side="left")
            ram_val_lbl = tk.Label(ram_header, text=f"{self.ram_allocation} MB",
                                  font=("Segoe UI", 10), fg=COLORS.get('success_green', '#2D8F36'),
                                  bg=card_bg)
            ram_val_lbl.pack(side="right")

            ram_v = tk.IntVar(value=self.ram_allocation)

            def on_ram_change(val):
                ram_val_lbl.config(text=f"{int(float(val))} MB")

            ram_scale = tk.Scale(ram_card, from_=1024, to=16384, orient="horizontal",
                                resolution=512, variable=ram_v, showvalue=False,
                                bg=card_bg, fg="white",
                                troughcolor=input_bg, highlightthickness=0,
                                activebackground=COLORS.get('success_green', '#2D8F36'),
                                command=on_ram_change, length=440)
            ram_scale.pack(fill="x", pady=(8, 0))

            # Toggles
            toggle_card = tk.Frame(form, bg=card_bg, padx=18, pady=14,
                                   highlightbackground=border_col, highlightthickness=1)
            toggle_card.pack(fill="x")

            c_launch = tk.BooleanVar(value=getattr(self, 'close_launcher', True))
            c_tray = tk.BooleanVar(value=getattr(self, 'minimize_to_tray', False))

            for txt, var in [("Close launcher when game starts", c_launch),
                             ("Minimize to system tray on close", c_tray)]:
                row = tk.Frame(toggle_card, bg=card_bg)
                row.pack(fill="x", pady=4)
                tk.Checkbutton(row, text=txt, variable=var, font=("Segoe UI", 10),
                              bg=card_bg, fg="white",
                              selectcolor=input_bg,
                              activebackground=card_bg,
                              activeforeground="white").pack(anchor="w")

            btn_frame = tk.Frame(form, bg=main_bg)
            btn_frame.pack(fill="x", pady=(20, 0))

            def do_next():
                self.ram_allocation = ram_v.get()
                self.close_launcher = c_launch.get()
                self.minimize_to_tray = c_tray.get()
                self.save_config(sync_ui=False)
                show_step_theme()

            make_btn(btn_frame, "Continue", COLORS.get('success_green', '#2D8F36'),
                    do_next).pack(fill="x")
            make_link(btn_frame, "← Back to Account", show_step_account_type).pack(anchor="w", pady=(10, 0))

        # STEP 3 — Theme & Appearance
        def show_step_theme():
            clear_page()
            update_dots(2)

            curr_main_bg = COLORS['main_bg']
            curr_card_bg = COLORS['card_bg']
            curr_border_col = COLORS.get('border_subtle', '#33373E')
            curr_text_sec = COLORS.get('text_secondary', '#A0AAB0')
            curr_accent = COLORS.get('accent_color', '#2ECC71')

            tk.Frame(content, bg=curr_main_bg, height=12).pack()
            tk.Label(content, text="Theme & Appearance",
                    font=("Segoe UI", 18, "bold"), fg="white",
                    bg=curr_main_bg).pack()
            tk.Label(content, text="Choose a theme palette and accent color for the launcher",
                    font=("Segoe UI", 10), fg=curr_text_sec,
                    bg=curr_main_bg).pack(pady=(4, 14))

            # Themes Grid Section
            theme_container = tk.Frame(content, bg=curr_main_bg)
            theme_container.pack(fill="x", padx=40)

            tk.Label(theme_container, text="THEME PALETTES", font=("Segoe UI", 8, "bold"),
                     fg=curr_accent, bg=curr_main_bg).pack(anchor="w", pady=(0, 6))

            theme_grid = tk.Frame(theme_container, bg=curr_main_bg)
            theme_grid.pack(fill="x")

            curr_theme_key = getattr(self, "theme_id", "dark_slate")

            def select_theme(t_key):
                self.apply_theme(t_key, save=True)
                show_step_theme()

            theme_keys = list(THEMES.keys())
            for idx, t_key in enumerate(theme_keys):
                t_info = THEMES[t_key]
                col = idx % 3
                row = idx // 3
                is_active = (t_key == curr_theme_key)

                t_frame = tk.Frame(
                    theme_grid,
                    bg=t_info['card_bg'],
                    cursor="hand2",
                    padx=12,
                    pady=9,
                    highlightthickness=2 if is_active else 1,
                    highlightbackground=curr_accent if is_active else curr_border_col
                )
                t_frame.grid(row=row, column=col, padx=5, pady=5, sticky="ew")
                theme_grid.columnconfigure(col, weight=1)

                hdr = tk.Frame(t_frame, bg=t_info['card_bg'])
                hdr.pack(fill="x")

                dot = tk.Label(hdr, text="●", font=("Segoe UI", 9), bg=t_info['card_bg'],
                               fg=t_info.get('default_accent', '#2ECC71'))
                dot.pack(side="left", padx=(0, 5))

                name_lbl = tk.Label(hdr, text=t_info['name'], font=("Segoe UI", 9, "bold"),
                                    bg=t_info['card_bg'], fg="white")
                name_lbl.pack(side="left")

                desc_lbl = tk.Label(t_frame, text=t_info.get('description', ''), font=("Segoe UI", 7),
                                    bg=t_info['card_bg'], fg=curr_text_sec, wraplength=170, justify="left")
                desc_lbl.pack(anchor="w", pady=(2, 0))

                for w in (t_frame, hdr, dot, name_lbl, desc_lbl):
                    w.bind("<Button-1>", lambda e, k=t_key: select_theme(k))

            # Accent Colors Section
            accent_container = tk.Frame(content, bg=curr_main_bg)
            accent_container.pack(fill="x", padx=40, pady=(14, 0))

            tk.Label(accent_container, text="ACCENT COLOR", font=("Segoe UI", 8, "bold"),
                     fg=curr_accent, bg=curr_main_bg).pack(anchor="w", pady=(0, 6))

            colors_list = [
                ("Green",  "#2ECC71"),
                ("Blue",   "#3498DB"),
                ("Cyan",   "#00E5FF"),
                ("Purple", "#9B59B6"),
                ("Orange", "#E67E22"),
                ("Red",    "#E74C3C"),
            ]

            palette = tk.Frame(accent_container, bg=curr_main_bg)
            palette.pack(anchor="w")

            selected_color = [getattr(self, "accent_color_name", "Green")]
            swatch_widgets = []
            finish_btn_ref = [None]

            def select_color(name, color_hex):
                selected_color[0] = name
                self.apply_accent_color(name)
                self.save_config(sync_ui=False)
                for sn, sw, sl in swatch_widgets:
                    if sn == name:
                        sw.config(highlightbackground="white", highlightthickness=2)
                        sl.config(fg="white")
                    else:
                        sw.config(highlightbackground=curr_border_col, highlightthickness=1)
                        sl.config(fg=curr_text_sec)
                if finish_btn_ref[0]:
                    finish_btn_ref[0].config(bg=color_hex, activebackground=color_hex)

            for name, color_hex in colors_list:
                col_box = tk.Frame(palette, bg=curr_main_bg)
                col_box.pack(side="left", padx=(0, 12))

                is_active = (name == selected_color[0] or color_hex.lower() == curr_accent.lower())
                swatch = tk.Frame(
                    col_box, bg=color_hex, width=36, height=36, cursor="hand2",
                    highlightbackground="white" if is_active else curr_border_col,
                    highlightthickness=2 if is_active else 1
                )
                swatch.pack()
                swatch.pack_propagate(False)

                lbl = tk.Label(col_box, text=name, font=("Segoe UI", 8),
                               bg=curr_main_bg,
                               fg="white" if is_active else curr_text_sec)
                lbl.pack(pady=(2, 0))

                swatch_widgets.append((name, swatch, lbl))

                swatch.bind("<Button-1>", lambda e, n=name, c=color_hex: select_color(n, c))
                lbl.bind("<Button-1>", lambda e, n=name, c=color_hex: select_color(n, c))

            btn_box = tk.Frame(content, bg=curr_main_bg)
            btn_box.pack(pady=(20, 0))

            finish_btn = make_btn(btn_box, "Finish Setup", curr_accent, show_step_done)
            finish_btn.pack(ipadx=24)
            finish_btn_ref[0] = finish_btn

            make_link(content, "← Back to Preferences", show_step_preferences).pack(pady=(8, 0))

        # STEP 4 — Done
        def show_step_done():
            clear_page()
            update_dots(3)

            tk.Frame(content, bg=main_bg, height=36).pack()

            tk.Label(content, text="✓", font=("Segoe UI", 40),
                    fg=COLORS.get('success_green', '#2D8F36'),
                    bg=main_bg).pack()
            tk.Label(content, text="You're All Set!",
                    font=("Segoe UI", 22, "bold"), fg="white",
                    bg=main_bg).pack(pady=(8, 6))
            tk.Label(content, text="Create an installation to start playing",
                    font=("Segoe UI", 11), fg=text_secondary,
                    bg=main_bg).pack()

            make_btn(content, "Get Started", COLORS.get('success_green', '#2D8F36'),
                    lambda: self.close_onboarding_wizard(start_tour=True)).pack(pady=(32, 0), ipadx=24)

        show_step_account_type()

    def close_onboarding_wizard(self, start_tour=False):
        """Cleanly tears down the in-app onboarding view and restores main launcher views."""
        self._in_onboarding = False
        self.first_run = False
        self.save_config()

        if hasattr(self, '_onboarding_view') and self._onboarding_view and self._onboarding_view.winfo_exists():
            try:
                self._onboarding_view.destroy()
            except Exception:
                pass
            self._onboarding_view = None

        if hasattr(self, 'sidebar') and self.sidebar and self.sidebar.winfo_exists():
            self.sidebar.pack(side="left", fill="y")
        if hasattr(self, 'content_area') and self.content_area and self.content_area.winfo_exists():
            self.content_area.pack(side="right", fill="both", expand=True)

        self.show_tab("Installations")
        self.root.after(80, self.update_active_profile)
        self.root.after(180, self.refresh_skin)
        if start_tour:
            self.root.after(260, self.start_installations_tour)
        self.root.after(350, self._focus_main_window)

    def start_installations_tour(self):
        """Tour Step 1: Installations"""
        self.show_tab("Installations")
        self.root.update()
        self._focus_main_window()

        target = getattr(self, 'new_inst_btn', None)
        self.show_coach_mark(
            target,
            "Create and manage game installations here.\nUse 'New installation' in the top bar to add versions, mods, and loaders.",
            next_action=self.start_locker_tour,
            step_info="TOUR 1 OF 3 • INSTALLATIONS",
        )

    def start_locker_tour(self):
        """Tour Step 2: Locker (Skins/Wallpapers)"""
        self.show_tab("Locker")
        self.root.update()
        
        target = None
        if hasattr(self, 'locker_btns') and "Skins" in self.locker_btns:
            target = self.locker_btns["Skins"]
        elif "Locker" in self.tabs:
            target = self.tabs["Locker"]

        self.show_coach_mark(
            target,
            "Customize your look in the Locker!\nSwitch between Skins and Wallpapers using the sub-tabs.",
            next_action=self.start_settings_tour,
            step_info="TOUR 2 OF 3 • LOCKER",
        )

    def start_settings_tour(self):
        """Tour Step 3: Settings"""
        self.show_tab("Settings")
        self.root.update()
        
        target = None
        if "Settings" in self.tabs:
            try:
                children = self.tabs["Settings"].winfo_children()
                if children:
                    target = children[0]
            except Exception:
                pass
            if not target:
                target = self.tabs["Settings"]
        
        self.show_coach_mark(
            target,
            "Configure launcher settings, memory allocation,\nand custom appearance here.",
            next_action=self.finish_tour_celebration,
            step_info="TOUR 3 OF 3 • SETTINGS",
        )

    def finish_tour_celebration(self):
        """In-app celebration badge at the end of the tour without modal popups."""
        self._dismiss_coach_mark()
        if not hasattr(self, 'content_area') or not self.content_area.winfo_exists():
            return

        card_bg = COLORS['card_bg']
        accent_col = COLORS.get('accent_color', '#2ECC71')
        text_pri = COLORS['text_primary']

        card = tk.Frame(
            self.content_area,
            bg=card_bg,
            highlightthickness=1,
            highlightbackground=accent_col,
            padx=20,
            pady=16,
        )
        card.place(relx=0.5, rely=0.88, anchor="s")

        header = tk.Frame(card, bg=card_bg)
        header.pack(fill="x")
        tk.Label(
            header,
            text="🎉 ALL SET!",
            font=("Segoe UI", 10, "bold"),
            bg=card_bg,
            fg=accent_col,
        ).pack(side="left")

        tk.Label(
            card,
            text="You're ready to play! Have fun with New Launcher.",
            font=("Segoe UI", 11, "bold"),
            bg=card_bg,
            fg=text_pri,
        ).pack(anchor="w", pady=(6, 12))

        def dismiss():
            if card.winfo_exists():
                card.destroy()

        btn = tk.Label(
            card,
            text="Let's Go",
            font=("Segoe UI", 10, "bold"),
            bg=accent_col,
            fg=COLORS.get('play_btn_text', 'white'),
            padx=16,
            pady=6,
            cursor="hand2",
        )
        btn.pack(anchor="e")
        btn.bind("<Button-1>", lambda e: dismiss())

        # Auto-dismiss after 6 seconds
        self.root.after(6000, dismiss)

    def _dismiss_coach_mark(self):
        if hasattr(self, 'tour_card') and self.tour_card and self.tour_card.winfo_exists():
            try:
                self.tour_card.destroy()
            except Exception:
                pass
        self.tour_card = None

    def show_coach_mark(self, widget, text, next_action=None, step_info=None):
        """Displays a sleek in-app floating tour guide card at bottom of content area."""
        self._dismiss_coach_mark()
        if not hasattr(self, 'content_area') or not self.content_area.winfo_exists():
            if next_action:
                self.root.after(100, next_action)
            return

        card_bg = COLORS['card_bg']
        accent_col = COLORS.get('accent_color', '#2ECC71')
        text_pri = COLORS['text_primary']
        text_muted = COLORS.get('text_muted', '#6B7280')

        card = tk.Frame(
            self.content_area,
            bg=card_bg,
            highlightthickness=1,
            highlightbackground=accent_col,
            padx=18,
            pady=14,
        )
        self.tour_card = card
        card.place(relx=0.5, rely=0.92, anchor="s")

        header = tk.Frame(card, bg=card_bg)
        header.pack(fill="x", pady=(0, 4))

        if step_info:
            tk.Label(
                header,
                text=step_info,
                font=("Segoe UI", 8, "bold"),
                bg=card_bg,
                fg=accent_col,
            ).pack(side="left")

        close_lbl = tk.Label(
            header,
            text="✕",
            font=("Segoe UI", 9, "bold"),
            bg=card_bg,
            fg=text_muted,
            cursor="hand2",
        )
        close_lbl.pack(side="right")
        close_lbl.bind("<Button-1>", lambda e: self._dismiss_coach_mark())

        body_lbl = tk.Label(
            card,
            text=text,
            font=("Segoe UI", 10),
            bg=card_bg,
            fg=text_pri,
            justify="left",
        )
        body_lbl.pack(anchor="w", pady=(2, 10))

        controls = tk.Frame(card, bg=card_bg)
        controls.pack(fill="x")

        skip_lbl = tk.Label(
            controls,
            text="Skip Tour",
            font=("Segoe UI", 8, "underline"),
            bg=card_bg,
            fg=text_muted,
            cursor="hand2",
        )
        skip_lbl.pack(side="left")
        skip_lbl.bind("<Button-1>", lambda e: self._dismiss_coach_mark())

        btn_text = "Continue ➔" if next_action else "Finish"
        def on_advance(e=None):
            self._dismiss_coach_mark()
            if next_action:
                self.root.after(150, next_action)

        btn = tk.Label(
            controls,
            text=btn_text,
            font=("Segoe UI", 9, "bold"),
            bg=accent_col,
            fg=COLORS.get('play_btn_text', 'white'),
            padx=14,
            pady=5,
            cursor="hand2",
        )
        btn.pack(side="right")
        btn.bind("<Button-1>", on_advance)

    def open_global_settings(self):
        cur = getattr(self, 'current_tab', 'Play')
        if cur != "Settings":
            self._prev_tab = cur
        self.show_tab("Settings")
        if hasattr(self, 'build_settings_sidebar'):
            self.build_settings_sidebar()

    def exit_settings(self):
        prev = getattr(self, '_prev_tab', 'Play')
        if prev == "Settings":
            prev = "Play"
        if hasattr(self, 'build_main_sidebar'):
            self.build_main_sidebar()
        self.show_tab(prev)
        
    def show_modrinth_enable_dialog(self):
        mgr = get_modal_manager(self.root)
        if not mgr:
            return

        def build_content(body_frame, close_modal):
            tk.Label(
                body_frame,
                text="Enable Mod Support?",
                font=("Segoe UI", 13, "bold"),
                bg=COLORS['card_bg'],
                fg=COLORS['text_primary'],
            ).pack(anchor="w", pady=(0, 6))

            tk.Label(
                body_frame,
                text="Would you like to enable mod support in the launcher?",
                font=("Segoe UI", 10),
                bg=COLORS['card_bg'],
                fg=COLORS['text_secondary'],
                wraplength=400,
                justify="left",
            ).pack(anchor="w", pady=(0, 10))

            warn_frame = tk.Frame(body_frame, bg=COLORS['card_bg'])
            warn_frame.pack(anchor="w", pady=(0, 10))

            tk.Label(
                warn_frame,
                text="⚠️ Uses additional background resources",
                font=("Segoe UI", 9, "italic"),
                bg=COLORS['card_bg'],
                fg="#F1C40F",
            ).pack(side="left")

            tk.Label(
                body_frame,
                text="Note: You can change this later in Settings > Downloads.",
                font=("Segoe UI", 8),
                bg=COLORS['card_bg'],
                fg=COLORS['text_secondary'],
            ).pack(anchor="w", pady=(0, 16))

            def enable():
                self.enable_modrinth = True
                self.save_config()
                close_modal()

                def do_restart():
                    cmd = [sys.executable]
                    cwd = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.getcwd()
                    if not getattr(sys, 'frozen', False):
                        script = sys.argv[0]
                        if not os.path.isabs(script):
                            script = os.path.abspath(script)
                            cwd = os.path.dirname(script)
                        cmd = [sys.executable, script] + sys.argv[1:]

                    if os.name == 'nt':
                        subprocess.Popen(cmd, cwd=cwd, close_fds=True, creationflags=0x00000008)
                    else:
                        subprocess.Popen(cmd, cwd=cwd, close_fds=True)
                    self.root.quit()

                if messagebox.askyesno("Restart Required", "The launcher needs to restart to apply changes.\nRestart now?"):
                    do_restart()

            btn_frame = tk.Frame(body_frame, bg=COLORS['card_bg'])
            btn_frame.pack(fill="x", side="bottom")

            self._make_btn(
                btn_frame,
                "No, Keep Disabled",
                style="secondary",
                font_size=10,
                command=close_modal,
            ).pack(side="left")

            self._make_btn(
                btn_frame,
                "Yes, Enable",
                style="primary",
                font_size=10,
                command=enable,
            ).pack(side="right")

        mgr.show_modal("Enable Mod Support", build_content, width=460, height=260)

    def set_active_sidebar(self, active_frame):
        hover_col = COLORS.get('hover_bg', '#3A3F4D')
        sidebar_col = COLORS['sidebar_bg']
        accent_col = COLORS.get('accent_color', '#2ECC71')

        for frame in getattr(self, 'sidebar_items', []):
            if not getattr(frame, 'winfo_exists', lambda: False)():
                continue
            is_target = (frame == active_frame)
            frame.is_active = is_target

            # Manage active accent indicator bar
            bar = getattr(frame, "_active_bar", None)
            if bar and bar.winfo_exists():
                bar.config(bg=accent_col)
                if is_target:
                    anchor_widget = getattr(frame, "_lbl_icon", None) or getattr(frame, "_lbl_text", None)
                    bar.pack(side="left", fill="y", padx=(0, 6), before=anchor_widget)
                else:
                    bar.pack_forget()

            target_bg = hover_col if is_target else sidebar_col
            fg_col = COLORS['text_primary'] if is_target else COLORS['text_secondary']

            def _update_descendants_active(c, target_frame=frame, target_bar=bar):
                for child in _get_widget_descendants(target_frame):
                    if getattr(child, '_is_category_header', False) or getattr(child, "_keep_sidebar_bg", False):
                        continue
                    try:
                        if isinstance(child, tk.Frame) and child != target_bar:
                            child.config(bg=c)
                        elif isinstance(child, tk.Label):
                            child.config(bg=c, fg=fg_col)
                    except Exception:
                        pass

            if getattr(self, 'animator', None) and self.animator.is_enabled:
                self.animator.animate_color(
                    frame, "bg", frame.cget("bg"), target_bg,
                    duration_ms=90,
                    on_step=_update_descendants_active
                )
            else:
                frame.config(bg=target_bg)
                _update_descendants_active(target_bg)

    def _attach_sidebar_hover(self, frame):
        hover_state = {"is_hovered": False}

        def _update_descendants_hover(bg_col, is_hover):
            is_active = getattr(frame, "is_active", False)
            bar = getattr(frame, "_active_bar", None)
            is_profile = (frame == getattr(self, "profile_frame", None))

            for child in _get_widget_descendants(frame):
                if getattr(child, "_keep_sidebar_bg", False) or getattr(child, "_is_category_header", False):
                    continue
                try:
                    if isinstance(child, tk.Frame) and child != bar:
                        child.config(bg=bg_col)
                    elif isinstance(child, tk.Label):
                        if is_profile:
                            if child == getattr(self, 'sidebar_username', None):
                                child.config(bg=bg_col, fg=COLORS['text_primary'])
                            elif child in (getattr(self, 'sidebar_acct_type', None), getattr(self, 'sidebar_chevron', None)):
                                child.config(bg=bg_col, fg=COLORS['text_primary'] if is_hover else COLORS.get('text_muted', '#6B7280'))
                            else:
                                child.config(bg=bg_col)
                        else:
                            fg_col = COLORS['text_primary'] if (is_hover or is_active) else COLORS['text_secondary']
                            child.config(bg=bg_col, fg=fg_col)
                except Exception:
                    pass

        def on_enter(e=None):
            if hover_state["is_hovered"]:
                return
            hover_state["is_hovered"] = True
            hover_col = COLORS.get('hover_bg', '#3A3F4D')
            if getattr(self, 'animator', None) and self.animator.is_enabled:
                self.animator.animate_color(
                    frame, "bg", frame.cget("bg"), hover_col,
                    duration_ms=80,
                    on_step=lambda c: _update_descendants_hover(c, is_hover=True)
                )
            else:
                frame.config(bg=hover_col)
                _update_descendants_hover(hover_col, is_hover=True)

        def on_leave(e=None):
            if _is_pointer_inside(frame):
                return
            hover_state["is_hovered"] = False
            is_active = getattr(frame, "is_active", False)
            hover_col = COLORS.get('hover_bg', '#3A3F4D')
            sidebar_col = COLORS.get('sidebar_bg', '#181A1E')
            target_bg = hover_col if is_active else sidebar_col

            if getattr(self, 'animator', None) and self.animator.is_enabled:
                self.animator.animate_color(
                    frame, "bg", frame.cget("bg"), target_bg,
                    duration_ms=80,
                    on_step=lambda c: _update_descendants_hover(c, is_hover=False)
                )
            else:
                frame.config(bg=target_bg)
                _update_descendants_hover(target_bg, is_hover=False)

        frame._on_enter = on_enter  # type: ignore[attr-defined]
        frame._on_leave = on_leave  # type: ignore[attr-defined]
        frame.bind("<Enter>", on_enter)
        frame.bind("<Leave>", on_leave)

        def _bind_all_descendants():
            for child in _get_widget_descendants(frame):
                if getattr(child, "_keep_sidebar_bg", False):
                    continue
                child.bind("<Enter>", on_enter, add="+")
                child.bind("<Leave>", on_leave, add="+")

        frame.after_idle(_bind_all_descendants)

    def refresh_sidebar_theme(self):
        """Synchronize all sidebar components, active bars, and section headers with active theme tokens."""
        sidebar_bg = COLORS['sidebar_bg']
        hover_bg = COLORS.get('hover_bg', '#3A3F4D')
        accent_col = COLORS.get('accent_color', '#2ECC71')
        muted_col = COLORS.get('text_muted', '#6B7280')
        sep_col = COLORS.get('separator', '#282C36')

        if hasattr(self, 'sidebar') and self.sidebar.winfo_exists():
            self.sidebar.config(bg=sidebar_bg)
            for child in self.sidebar.winfo_children():
                if isinstance(child, tk.Frame) and child.cget("height") == 1:
                    child.config(bg=sep_col)

        # Synchronize nav frame and all category headers inside it
        if hasattr(self, 'sidebar_nav_frame') and self.sidebar_nav_frame.winfo_exists():
            self.sidebar_nav_frame.config(bg=sidebar_bg)
            for child in self.sidebar_nav_frame.winfo_children():
                if getattr(child, '_is_category_header', False):
                    child.config(bg=sidebar_bg, fg=muted_col)

        # Synchronize account / profile button and all nested labels/frames
        if hasattr(self, 'profile_frame') and self.profile_frame.winfo_exists():
            self.profile_frame.config(bg=sidebar_bg)
            for child in _get_widget_descendants(self.profile_frame):
                if isinstance(child, (tk.Frame, tk.Label)):
                    child.config(bg=sidebar_bg)
            if hasattr(self, 'sidebar_username') and self.sidebar_username.winfo_exists():
                self.sidebar_username.config(bg=sidebar_bg, fg=COLORS['text_primary'])
            if hasattr(self, 'sidebar_acct_type') and self.sidebar_acct_type.winfo_exists():
                self.sidebar_acct_type.config(bg=sidebar_bg, fg=muted_col)
            if hasattr(self, 'sidebar_chevron') and self.sidebar_chevron.winfo_exists():
                self.sidebar_chevron.config(bg=sidebar_bg, fg=muted_col)

        # Synchronize account drawer and separator
        if hasattr(self, 'sidebar_nav_separator') and self.sidebar_nav_separator.winfo_exists():
            self.sidebar_nav_separator.config(bg=COLORS.get('separator', '#454545'))
        if hasattr(self, 'sidebar_account_drawer') and self.sidebar_account_drawer.winfo_exists():
            self.sidebar_account_drawer.config(
                bg=COLORS['card_bg'],
                highlightbackground=COLORS.get('border_subtle', '#2D3139')
            )
            if getattr(self, 'sidebar_account_drawer_open', False) and hasattr(self, 'render_sidebar_account_drawer'):
                self.render_sidebar_account_drawer()

        # Synchronize all sidebar items and dock links
        for frame in getattr(self, 'sidebar_items', []):
            if not getattr(frame, 'winfo_exists', lambda: False)():
                continue
            is_active = getattr(frame, 'is_active', False)
            target_bg = hover_bg if is_active else sidebar_bg
            frame.config(bg=target_bg)

            bar = getattr(frame, '_active_bar', None)
            if bar and bar.winfo_exists():
                bar.config(bg=accent_col)

            for child in _get_widget_descendants(frame):
                if getattr(child, '_is_category_header', False):
                    child.config(bg=sidebar_bg, fg=muted_col)
                elif isinstance(child, tk.Label):
                    if not getattr(child, '_keep_sidebar_bg', False):
                        child.config(bg=target_bg, fg=COLORS['text_primary'] if is_active else COLORS['text_secondary'])
                elif isinstance(child, tk.Frame) and child != bar:
                    child.config(bg=target_bg)

    def _create_sidebar_link(self, text, url_or_command, indicator_text=None, indicator_color=None, is_action=False, pack_side="top", icon=None, highlight_on_click=True):
        frame = tk.Frame(self.sidebar, bg=COLORS['sidebar_bg'], cursor="hand2", padx=15, pady=8)
        frame.pack(fill="x", side=cast(Any, pack_side))
        
        # Register for active state tracking
        if not hasattr(self, 'sidebar_items'): self.sidebar_items = []
        if highlight_on_click:
            self.sidebar_items.append(frame)
        
        # Indicator (like "Java" or "Mods")
        if indicator_text:
             if indicator_color:
                 bg_color = indicator_color
             else:
                 bg_color = "#E74C3C" if indicator_text == "Mods" else "#2D8F36"
             
             indicator_label = tk.Label(frame, text=indicator_text, bg=bg_color, fg="white", 
                     font=(FONT_FAMILY, 8, "bold"), width=4, cursor="hand2")
             indicator_label._keep_sidebar_bg = True  # type: ignore[attr-defined]
             indicator_label.pack(side="left", padx=(0,10))
        
        # Icon
        if icon:
            if icon.endswith(".png"):
                icon_path = f"icons/{icon}" if not icon.startswith("icons/") else icon
                img = getattr(self, "get_icon_image", lambda x, y: None)(icon_path, (18, 18))
                if img:
                    lbl_img = tk.Label(frame, image=img, bg=COLORS['sidebar_bg'], cursor="hand2")
                    lbl_img.image = img  # type: ignore[attr-defined]
                    lbl_img.pack(side="left", padx=(0, 10))
                    frame._lbl_icon = lbl_img  # type: ignore[attr-defined]
                else:
                    lbl_sym = tk.Label(frame, text="•", font=(FONT_FAMILY, 10), bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'], cursor="hand2")
                    lbl_sym.pack(side="left", padx=(0, 10))
                    frame._lbl_icon = lbl_sym  # type: ignore[attr-defined]
            else:
                lbl_ico = tk.Label(frame, text=icon, font=(FONT_FAMILY, 11), bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'], 
                         cursor="hand2")
                lbl_ico.pack(side="left", padx=(0, 10))
                frame._lbl_icon = lbl_ico  # type: ignore[attr-defined]

        lbl = tk.Label(frame, text=text, font=(FONT_FAMILY, 9), bg=COLORS['sidebar_bg'], fg=COLORS['text_secondary'], cursor="hand2")
        lbl.pack(side="left")
        
        def handle_click(e):
            if is_action:
                if highlight_on_click:
                    self.set_active_sidebar(frame)
                url_or_command()
            else:
                webbrowser.open(url_or_command)
            
        frame.bind("<Button-1>", handle_click)
        lbl.bind("<Button-1>", handle_click)
        # bind children
        for child in frame.winfo_children():
            child.bind("<Button-1>", handle_click)
        
        # Hover effect
        self._attach_sidebar_hover(frame)
        return frame

    def toggle_notification_center(self):
        """Toggle slide-over Notification Center drawer."""
        if hasattr(self, 'notification_drawer') and self.notification_drawer:
            self.notification_drawer.toggle()

    def _update_notification_badge(self, unread_count: int):
        """Update the unread pill badge on the sidebar Notifications link."""
        if not hasattr(self, 'sidebar_notif_badge') or not self.sidebar_notif_badge:
            return
        if unread_count > 0:
            badge_text = str(unread_count) if unread_count < 100 else "99+"
            self.sidebar_notif_badge.config(text=badge_text)
            self.sidebar_notif_badge.pack(side="right", padx=(4, 0))
        else:
            self.sidebar_notif_badge.pack_forget()

    def _notify_game_session_ended(self, inst_id, session_seconds, server_address=None):
        """Notify user of session playtime and cumulative playtime after exiting game."""
        if not inst_id:
            return
        inst_name = str(inst_id)
        for inst in getattr(self, "installations", []):
            if inst.get("id") == inst_id:
                inst_name = inst.get("name", str(inst_id))
                break

        tracker = getattr(self, "addons_config", {}).get("playtime_tracker", {}) if hasattr(self, "addons_config") else {}
        stats = tracker.get(inst_id, {})
        total_seconds = int(stats.get("seconds", session_seconds))

        if hasattr(self, "notifications") and self.notifications:
            self.notifications.add_session(
                inst_name=inst_name,
                session_seconds=session_seconds,
                total_seconds=total_seconds,
                server=server_address
            )
        if hasattr(self, "toast_manager") and self.toast_manager:
            self.toast_manager.show_session_toast(
                inst_name=inst_name,
                session_seconds=session_seconds,
                total_seconds=total_seconds,
                server=server_address
            )

    # --- Smooth Scroll Utilities ---
    def _get_scroll_impulse(self, event):
        """Normalise wheel and precision-touchpad input to pixel impulses."""
        try:
            delta = getattr(event, "delta", 0)
            if delta:
                # Windows wheel mice normally report ±120; precision touchpads
                # often report much smaller values.  The old conversion ignored
                # those small deltas because the animation stopped below 0.5.
                direction = -1 if delta > 0 else 1
                return direction * max(18, min(72, abs(float(delta)) / 3))
        except Exception:
            pass

        try:
            button_num = getattr(event, "num", None)
            if button_num == 4:
                return -40
            if button_num == 5:
                return 40
        except Exception:
            pass

        return 0

    def _bind_wheel_events(self, widget, handler, bind_tag):
        if not widget or not widget.winfo_exists():
            return
        # If widget is a Canvas that is already bound for scrolling, do not attach
        # multiple competing handlers that double the scroll velocity.
        if isinstance(widget, tk.Canvas) and getattr(widget, "_nlc_canvas_wheel_bound", False):
            return

        attr_name = f"_nlc_wheel_bind_{bind_tag}"
        if getattr(widget, attr_name, False):
            return
        # Add, rather than replace, widget-native bindings (notably Combobox
        # and Text).  This fixes wheel support without breaking controls.
        widget.bind("<MouseWheel>", handler, add="+")
        widget.bind("<Button-4>", handler, add="+")
        widget.bind("<Button-5>", handler, add="+")
        setattr(widget, attr_name, True)
        if isinstance(widget, tk.Canvas):
            widget._nlc_canvas_wheel_bound = True  # type: ignore[attr-defined]

    def _smooth_scroll(self, canvas, event):
        """Smooth mousewheel scrolling with inertia for any canvas widget."""
        try:
            if not getattr(canvas, "_nlc_scroll_enabled", True):
                return
        except Exception:
            pass
        cid = id(canvas)
        # Cancel any existing animation for this canvas
        if cid in self._scroll_anim_ids:
            try: self.root.after_cancel(self._scroll_anim_ids[cid])
            except: pass
            self._scroll_anim_ids.pop(cid, None)
        
        # Add velocity from scroll event (accumulate for fast flicks)
        impulse = self._get_scroll_impulse(event)
        if not impulse:
            return
        current = self._scroll_velocities.get(cid, 0.0)
        # A hard cap prevents a burst of wheel events from coasting across an
        # entire page and makes scrolling predictable at all window sizes.
        self._scroll_velocities[cid] = max(-360.0, min(360.0, current + impulse))
        
        # Pre-cache container height metrics once on impulse to avoid querying
        # canvas.bbox("all") on every single 16ms animation frame (which causes GDI tearing).
        try:
            bbox = canvas.bbox("all")
            if bbox:
                total_height = bbox[3] - bbox[1]
                canvas_height = canvas.winfo_height()
                canvas._nlc_scroll_metrics = (total_height, canvas_height)
        except Exception:
            pass

        self._animate_scroll(canvas, cid)
    
    def _animate_scroll(self, canvas, cid):
        """Animate scroll with deceleration (inertia)."""
        try:
            if not canvas.winfo_exists():
                self._scroll_velocities.pop(cid, None)
                self._scroll_anim_ids.pop(cid, None)
                setattr(canvas, "_nlc_scroll_metrics", None)
                return
        except:
            self._scroll_velocities.pop(cid, None)
            self._scroll_anim_ids.pop(cid, None)
            return
        
        velocity = self._scroll_velocities.get(cid, 0)
        
        # Stop if velocity is negligible
        if abs(velocity) < 0.5:
            self._scroll_velocities.pop(cid, None)
            self._scroll_anim_ids.pop(cid, None)
            setattr(canvas, "_nlc_scroll_metrics", None)
            return
        
        # Clamp at boundaries
        top, bottom = canvas.yview()
        if (velocity < 0 and top <= 0) or (velocity > 0 and bottom >= 1.0):
            self._scroll_velocities.pop(cid, None)
            self._scroll_anim_ids.pop(cid, None)
            setattr(canvas, "_nlc_scroll_metrics", None)
            return
        
        # Use cached metrics or query if not yet cached
        metrics = getattr(canvas, "_nlc_scroll_metrics", None)
        if metrics:
            total_height, canvas_height = metrics
        else:
            bbox = canvas.bbox("all")
            if not bbox:
                self._scroll_velocities.pop(cid, None)
                self._scroll_anim_ids.pop(cid, None)
                return
            total_height = bbox[3] - bbox[1]
            canvas_height = canvas.winfo_height()
            canvas._nlc_scroll_metrics = (total_height, canvas_height)
        
        if total_height <= canvas_height:
            self._scroll_velocities.pop(cid, None)
            self._scroll_anim_ids.pop(cid, None)
            setattr(canvas, "_nlc_scroll_metrics", None)
            return
        
        # Quantize to integer pixels to prevent Windows GDI sub-pixel font and border tearing
        current_pixel_top = top * total_height
        target_pixel_top = current_pixel_top + velocity
        max_pixel_top = max(0.0, float(total_height - canvas_height))
        clamped_pixel_top = round(max(0.0, min(max_pixel_top, target_pixel_top)))
        quantized_fraction = clamped_pixel_top / total_height

        canvas.yview_moveto(quantized_fraction)
        callback = getattr(canvas, "_nlc_after_scroll", None)
        if callable(callback):
            callback()
        
        # Apply friction
        self._scroll_velocities[cid] = velocity * 0.78
        
        # Schedule next frame (~16ms for 60fps)
        self._scroll_anim_ids[cid] = self.root.after(16, self._animate_scroll, canvas, cid)

    def _bind_smooth_scroll(self, canvas, widget):
        """Bind smooth scrolling to a widget and all its children for a specific canvas."""
        if not widget or not widget.winfo_exists():
            return
        # Many panels previously bound the wheel only after entering a child
        # frame, so the blank area around content appeared unscrollable.  Give
        # every canvas a handler unless that panel already installed a custom
        # one (such as Modrinth pagination).
        if not getattr(canvas, "_nlc_canvas_wheel_bound", False):
            self._bind_wheel_events(
                canvas,
                lambda event, target=canvas: self._smooth_scroll(target, event),
                f"canvas_{id(canvas)}",
            )
        canvas_id = id(canvas)
        already_bound = getattr(widget, "_nlc_scroll_canvas_id", None)
        if already_bound != canvas_id:
            handler = lambda e, c=canvas: self._smooth_scroll(c, e)
            self._bind_wheel_events(widget, handler, f"smooth_{canvas_id}")
            setattr(widget, "_nlc_scroll_canvas_id", canvas_id)
        for child in widget.winfo_children():
            self._bind_smooth_scroll(canvas, child)

    def _make_btn(self, parent, text, style="secondary", command=None, font_size=9,
                  bold=False, icon=False, width=None, pack_opts=None):
        """Create a consistently styled button adhering to design tokens and micro-animations."""
        btn_style = "icon" if icon else style
        btn = make_button(
            parent,
            text,
            style=btn_style,
            command=command,
            font_size=font_size,
            bold=bold,
            width=width,
            animator=getattr(self, 'animator', None)
        )
        if pack_opts:
            btn.pack(**pack_opts)
        return btn

    def _animate_menu_open(self, menu, target_h, direction="down", pos_x=None, pos_y=None, pos_w=None):
        """Slide-open animation for dropdown menus.
        
        Args:
            pos_x, pos_y, pos_w: Explicit position/size to avoid re-parsing geometry.
                                 pos_y is the FINAL top-left y of the menu.
        """
        try:
            if pos_x is not None and pos_y is not None and pos_w is not None:
                w, x, base_y = pos_w, pos_x, pos_y
            else:
                geo = menu.geometry()
                parts = geo.split('+')
                size = parts[0].split('x')
                w = int(size[0])
                x = int(parts[1])
                base_y = int(parts[2])
        except:
            return
        
        steps = 6
        current_step = [0]
        
        if direction == "up":
            bottom_edge = base_y + target_h
        
        def step():
            if current_step[0] >= steps:
                menu.geometry(f"{w}x{target_h}+{x}+{base_y}")
                return
            try:
                if not menu.winfo_exists(): return
            except: return
            
            t = (current_step[0] + 1) / steps
            t_ease = 1 - (1 - t) ** 3
            h = max(1, int(t_ease * target_h))
            
            if direction == "up":
                y = bottom_edge - h # type: ignore
                menu.geometry(f"{w}x{h}+{x}+{y}")
            else:
                menu.geometry(f"{w}x{h}+{x}+{base_y}")
            
            current_step[0] += 1
            self.root.after(12, step)
        
        if direction == "up":
            menu.geometry(f"{w}x1+{x}+{bottom_edge - 1}") # type: ignore
        else:
            menu.geometry(f"{w}x1+{x}+{base_y}")
        step()

    def _close_all_menus(self):
        """Close all open dropdown menus when switching tabs or performing other actions"""
        try:
            dismiss_active_context_menu()
        except Exception:
            pass

        # Close installation selector menu
        if hasattr(self, '_selector_menu') and self._selector_menu:
            try:
                if self._selector_menu.winfo_exists():
                    self._selector_menu.destroy()
            except:
                pass
            self._selector_menu = None
        
        # Close profile menu / drawer
        if hasattr(self, 'close_profile_drawer'):
            self.close_profile_drawer()
        elif getattr(self, 'sidebar_account_drawer_open', False):
            if hasattr(self, 'sidebar_account_drawer') and self.sidebar_account_drawer.winfo_exists():
                self.sidebar_account_drawer.pack_forget()
            self.sidebar_account_drawer_open = False
            if hasattr(self, 'sidebar_chevron') and self.sidebar_chevron.winfo_exists():
                self.sidebar_chevron.config(text="▾")
        if hasattr(self, 'profile_menu') and self.profile_menu:
            if isinstance(self.profile_menu, tk.Toplevel):
                try:
                    if self.profile_menu.winfo_exists():
                        self.profile_menu.destroy()
                except:
                    pass
            self.profile_menu = None
        
        # Close launch options menu
        if hasattr(self, '_launch_opts_menu') and self._launch_opts_menu:
            try:
                if self._launch_opts_menu.winfo_exists():
                    self._launch_opts_menu.destroy()
            except:
                pass
            self._launch_opts_menu = None
        
        # Close installation context menu
        if hasattr(self, 'installation_menu') and self.installation_menu:
            try:
                if self.installation_menu.winfo_exists():
                    self.installation_menu.destroy()
            except:
                pass
            self.installation_menu = None

    def create_nav_btn(self, text, command):
        """Deprecated legacy top nav button constructor; retained as a safe proxy."""
        if hasattr(self, 'nav_bar') and self.nav_bar and self.nav_bar.winfo_exists():
            def wrapped_command():
                if hasattr(self, 'minecraft_btn_frame'):
                    self.set_active_sidebar(self.minecraft_btn_frame)
                command()
            btn = tk.Button(self.nav_bar, text=text.upper(), font=(FONT_FAMILY, 11, "bold"),
                           bg=COLORS['tab_bar_bg'], fg=COLORS['text_secondary'],
                           activebackground=COLORS['tab_bar_bg'], activeforeground=COLORS['text_primary'],
                           relief="flat", bd=0, cursor="hand2", command=wrapped_command)
            btn.pack(side="left", padx=30, pady=15)
            self.nav_buttons[text] = btn
            return btn
        return None

    def show_tab(self, tab_name):
        # Close any open dropdown menus
        self._close_all_menus()
        
        # Lazy Init Mods Tab
        if tab_name == "Mods" and "Mods" not in self.tabs:
             self.create_mods_tab()

        # Hide all tabs
        for t in self.tabs.values():
            t.pack_forget()
        
        # Update Nav Buttons
        for name, btn in self.nav_buttons.items():
            if name.upper() == tab_name.upper():
                btn.config(fg=COLORS['text_primary'])
            else:
                btn.config(fg=COLORS['text_secondary'])
        
        # Show selected tab
        if tab_name in self.tabs:
            self.tabs[tab_name].pack(fill="both", expand=True)
            self.current_tab = tab_name
            
            # Synchronize screen theme on display to ensure no stale backgrounds
            self.refresh_screen_theme(tab_name)
            
            # Lazy Load triggers
            if tab_name == "Mods":
                if hasattr(self, 'mods_tab_initialized') and not self.mods_tab_initialized:
                    self.mods_tab_initialized = True
                    self.search_mods_thread(reset=True)
            elif tab_name == "Screenshots":
                if hasattr(self, 'render_screenshots_gallery'):
                    self.render_screenshots_gallery()
            elif tab_name == "Settings":
                if hasattr(self, 'build_settings_sidebar') and not getattr(self, '_in_settings_sidebar', False):
                    self.build_settings_sidebar()
            else:
                # If returning to standard tabs, ensure main sidebar is shown
                if getattr(self, '_in_settings_sidebar', False):
                    if hasattr(self, 'build_main_sidebar'):
                        self.build_main_sidebar()

            # Animation lifecycle for 3D Locker Preview
            if tab_name == "Locker":
                if hasattr(self, 'update_locker_subtabs'):
                    self.update_locker_subtabs()
                if hasattr(self, 'start_preview_animation'):
                    self.start_preview_animation()
            else:
                if hasattr(self, 'stop_preview_animation'):
                    self.stop_preview_animation()

    # --- PLAY TAB ---
    def change_minecraft_dir(self):
        path = filedialog.askdirectory(initialdir=self.minecraft_dir)
        if path:
            self.minecraft_dir = path
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, path)
            self.load_versions()
            self.render_screenshot_browser()

    def _set_update_status(self, text: str, fg: str):
        self._update_status_text = text
        self._update_status_color = fg
        try:
            if hasattr(self, 'update_status_lbl') and self.update_status_lbl and self.update_status_lbl.winfo_exists():
                self.update_status_lbl.config(text=text, fg=fg)
        except Exception:
            pass

    def check_for_updates(self):
        self._set_update_status("Checking for updates...", COLORS['text_secondary'])
        threading.Thread(target=self._update_check_thread, daemon=True).start()

    def _update_check_thread(self):
        try:
            url = "https://api.github.com/repos/Amne-Dev/New-launcher/releases/latest"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                latest_tag = data.get("tag_name", "").lstrip("v")
                
                # Check for updates (Simple Semantic Versioning)
                update_available = False
                try:
                    current_parts = [int(x) for x in CURRENT_VERSION.split(".")]
                    latest_parts = [int(x) for x in latest_tag.split(".")]
                    
                    for i in range(max(len(current_parts), len(latest_parts))):
                        cur = current_parts[i] if i < len(current_parts) else 0
                        lat = latest_parts[i] if i < len(latest_parts) else 0
                        if lat > cur:
                            update_available = True
                            break
                        elif lat < cur:
                            break 
                except ValueError:
                    if latest_tag and latest_tag != CURRENT_VERSION:
                        update_available = True
                            
                if update_available:
                    assets = data.get("assets", [])
                    preferred_asset = None
                    extra_data = {}

                    # 1. Check for Content-Defined Chunking (CDC) index on Windows
                    if os.name == "nt":
                        cdc_asset = next((a for a in assets if str(a.get("name", "")).lower() == "newlauncher.exe.cdc.json"), None)
                        exe_asset = next((a for a in assets if str(a.get("name", "")).lower() == "newlauncher.exe"), None)
                        runner_asset = next((a for a in assets if str(a.get("name", "")).lower() == "nlcupdater.exe"), None)
                        if cdc_asset and exe_asset:
                            preferred_asset = cdc_asset
                            extra_data["exe_url"] = exe_asset.get("browser_download_url")
                            if runner_asset:
                                extra_data["runner_url"] = runner_asset.get("browser_download_url")

                    # 2. Select a patch built specifically for the installed version.
                    if preferred_asset is None:
                        expected_patch_name = (
                            f"nlcupdate-{CURRENT_VERSION.lower()}-to-{latest_tag.lower()}.zip"
                        )
                        for asset in assets:
                            name = str(asset.get("name", "")).lower()
                            if (
                                os.name == "nt"
                                and name == expected_patch_name
                            ):
                                preferred_asset = asset
                                break

                    # 3. Fallback to full installer
                    if preferred_asset is None:
                        for asset in assets:
                            name = str(asset.get("name", "")).lower()
                            if name.endswith(".exe") and ("setup" in name or "installer" in name):
                                preferred_asset = asset
                                break

                    asset_url = preferred_asset.get("browser_download_url") if preferred_asset else None
                    asset_name = preferred_asset.get("name") if preferred_asset else ""
                    self.root.after(
                        0,
                        lambda: self._on_update_found(
                            latest_tag,
                            data.get("html_url"),
                            asset_url,
                            asset_name,
                            extra_data,
                        ),
                    )
                else:
                     self.root.after(0, lambda: self._set_update_status("You are on the latest version.", COLORS['success_green']))
            else:
                 self.root.after(0, lambda: self._set_update_status(f"Failed to check: {response.status_code}", COLORS['error_red']))
        except Exception as e:
            self.root.after(0, lambda: self._set_update_status("Error checking updates", COLORS['error_red']))
            print(f"Update check error: {e}")

    def _on_update_found(self, version, html_url, asset_url, asset_name="", extra_data=None):
        self._set_update_status(f"New version available: {version}", COLORS['accent_blue'])
        
        def do_update():
            normalized_asset_name = str(asset_name).lower()
            is_supported_asset = (
                normalized_asset_name.endswith(".cdc.json")
                or (
                    normalized_asset_name.endswith(".zip")
                    and "update" in normalized_asset_name
                ) or (
                    normalized_asset_name.endswith(".exe")
                    and ("setup" in normalized_asset_name or "installer" in normalized_asset_name)
                )
            )
            if asset_url and is_supported_asset:
                try:
                    self.root.grab_release()
                except Exception:
                    pass
                self.root.after(0, lambda u=asset_url, v=version, n=asset_name, ed=extra_data: self.perform_auto_update(u, v, n, ed))
            else:
                if html_url:
                    webbrowser.open(html_url)

        if hasattr(self, "notifications") and self.notifications:
            self.notifications.add_update(
                version=version,
                asset_url=asset_url,
                html_url=html_url,
                on_update=do_update
            )
        if hasattr(self, "toast_manager") and self.toast_manager:
            self.toast_manager.show_update_toast(
                version=version,
                on_update=do_update
            )

    def open_minecraft_dir(self):
        try:
            open_path_in_system(self.minecraft_dir)
        except Exception as e:
            self.log(f"Error opening folder: {e}")

    def setup_tray(self):
        if not TRAY_AVAILABLE or TrayItem is None: return
        
        def quit_app(icon, item):
            icon.stop()
            self.root.destroy()
            sys.exit()

        def show_app(icon, item):
            self.restore_window()
        try:
            image = Image.open(resource_path("logo.ico"))
        except:
            # Fallback
            image = Image.new('RGB', (64, 64), color = (73, 109, 137))
            
        menu = (TrayItem('Open', show_app, default=True), TrayItem('Quit', quit_app))
        if TRAY_AVAILABLE and TrayIcon:
            try:
                self.tray_icon = TrayIcon("New Launcher", image, "New Launcher", menu)
                def _run_tray():
                    try:
                        self.tray_icon.run()
                    except (Exception, AssertionError) as exc:
                        logger.debug("Systray unavailable: %s", exc)
                        self.tray_icon = None
                threading.Thread(target=_run_tray, daemon=True, name="nlc-systray").start()
            except Exception as exc:
                logger.debug("Failed to init systray: %s", exc)
                self.tray_icon = None
        
        # Override minimize
        self.root.bind("<Unmap>", self._on_window_minimize)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_window_minimize(self, event):
        # Filter out random Unmap events (e.g. from widgets)
        if event and event.widget != self.root:
            return

        if self.root.state() == 'iconic':
            # Only withdraw if "Minimize to tray" is enabled
            should_tray = False
            if hasattr(self, 'minimize_to_tray_var'):
                should_tray = self.minimize_to_tray_var.get()
            else:
                should_tray = getattr(self, 'minimize_to_tray', False)

            if should_tray:
                self.root.withdraw()

    def restore_window(self):
        self._cancel_window_animation()
        wx, wy, ww, wh = self._get_work_area()

        if self._pre_minimize_was_maximized:
            target = (wx, wy, max(1, ww), max(1, wh))
        elif self._pre_minimize_geometry:
            target = self._pre_minimize_geometry
        else:
            fallback = self._windowed_geometry if self._windowed_geometry else (wx + 80, wy + 80, 1080, 720)
            target = (
                int(fallback[0]),
                int(fallback[1]),
                max(1, int(fallback[2])),
                max(1, int(fallback[3]))
            )

        if self._pre_minimize_anchor_geometry:
            start = self._pre_minimize_anchor_geometry
        else:
            tw = max(280, int(target[2] * 0.45))
            th = max(180, int(target[3] * 0.45))
            tx = wx + (ww - tw) // 2
            ty = wy + wh - th - 10
            start = (tx, ty, tw, th)

        def on_restore_done():
            self._window_is_maximized = bool(self._pre_minimize_was_maximized)
            if hasattr(self, 'window_max_btn'):
                self.window_max_btn.config(text="❐" if self._window_is_maximized else "□")
            self._update_titlebar_controls_offset()
            self.root.lift()
            try:
                self.root.focus_force()
            except Exception:
                pass
            self._pre_minimize_geometry = None
            self._pre_minimize_anchor_geometry = None
            self._pre_minimize_was_maximized = False

        def finalize_restore():
            self.root.deiconify()
            self.root.state('normal')
            self._set_geometry_tuple(target)
            self._set_custom_window_chrome(True)
            self._ensure_taskbar_visibility()

        self._run_transition_with_overlay(
            start,
            target,
            duration=140,
            steps=12,
            subtitle="Restoring window",
            finalize=finalize_restore,
            on_done=on_restore_done
        )
        
    def _on_close(self):
        try:
            self.save_config(sync_ui=True, immediate=True)
        except Exception:
            pass

        should_tray = False
        if hasattr(self, 'minimize_to_tray_var'):
            should_tray = self.minimize_to_tray_var.get()
        else:
            should_tray = getattr(self, 'minimize_to_tray', False)

        if should_tray and hasattr(self, 'tray_icon') and self.tray_icon:
            self.root.withdraw()
        else:
            if hasattr(self, 'tray_icon') and self.tray_icon:
                self.tray_icon.stop()
            self.root.destroy()
            os._exit(0)

    # --- LOGIC ---
    def setup_logging(self):
        try:
            # Determine log directory based on config location
            # If config_dir is set (which points to either local dir or .nlc), use that.
            if hasattr(self, 'config_dir'):
                log_dir = os.path.join(self.config_dir, "logs")
            else:
                # Fallback if config_dir is not yet set
                if getattr(sys, 'frozen', False):
                    base_dir = os.path.dirname(sys.executable)
                else:
                    base_dir = os.path.dirname(os.path.abspath(__file__))
                log_dir = os.path.join(base_dir, "logs")
            
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)

            self.cleanup_old_logs(log_dir)
            
            fname = f"launcher_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
            self.log_file_path = os.path.join(log_dir, fname)
            
            # Remove existing handlers
            for handler in logging.root.handlers[:]:
                logging.root.removeHandler(handler)
                
            logging.basicConfig(
                level=logging.NOTSET, # Capture everything, handlers will filter
                format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
                handlers=[
                    logging.FileHandler(self.log_file_path, encoding='utf-8'),
                    logging.StreamHandler(sys.stdout)
                ]
            )
            
            logging.info(f"Launcher initialized. Log file: {self.log_file_path}")
            logging.info(f"System: {platform.system()} {platform.release()} {platform.version()}")
            
        except Exception as e:
            print(f"Logging setup failed: {e}")
            self.log_file_path = None

    def cleanup_old_logs(self, log_dir):
        try:
            files = glob.glob(os.path.join(log_dir, "launcher_*.log"))
            files.sort(key=os.path.getmtime)
            while len(files) >= 5:
                try: os.remove(files.pop(0))
                except: pass
        except: pass

    def _on_ram_slider_change(self, value):
        try:
            val = int(float(value))
            self.ram_entry_var.set(str(val))
            self.ram_allocation = val
            self.save_config()
        except: pass

    def _on_ram_entry_change(self, *args):
        try:
            val = int(self.ram_entry_var.get())
            self.ram_allocation = val
            self.ram_var.set(val)
            self.save_config()
        except ValueError:
            pass

    def _on_rpc_toggle(self):
        self.rpc_enabled = self.rpc_var.get()
        if self.rpc_enabled:
            self.connect_rpc()
        else:
            self.close_rpc()
        self.save_config()

    def connect_rpc(self):
        if not RPC_AVAILABLE or not self.rpc_enabled or self.rpc_connected: return
        try:
            self.rpc = Presence("1458526248845443167") # pyright: ignore[reportPossiblyUnboundVariable] 
            self.rpc.connect()
            self.rpc_connected = True
            self.update_rpc("Idle", "In Launcher")
        except Exception as e:
            self.log(f"RPC Error: {e}")
            self.rpc_connected = False

    def close_rpc(self):
        if self.rpc:
            try: self.rpc.close()
            except: pass
        self.rpc_connected = False
        self.rpc = None

    def update_rpc(self, state, details=None, start=None):
        if not self.rpc_connected or not self.rpc: return
        try:
            self._last_rpc_state = state
            self._last_rpc_details = details
            self._last_rpc_start = start
            # User Info for formatted Rich Presence
            user_text = "Steve"
            small_key = "steve" # Fallback asset key
            
            if self.profiles and hasattr(self, 'current_profile_index') and 0 <= self.current_profile_index < len(self.profiles):
                p = self.profiles[self.current_profile_index]
                user_text = p.get("name", "Steve")
                # Use MC-Heads for dynamic avatar if UUID exists (Microsoft/Ely.by)
                if p.get("uuid"):
                    small_key = f"https://mc-heads.net/avatar/{p.get('uuid')}"
            user_text = self._get_streamer_safe_name(user_text)
            
            kwargs = {
                "state": state,
                "details": details,
                "large_image": "logo", 
                "large_text": "New Launcher",
                "small_image": small_key,
                "small_text": user_text
            }
            if start: kwargs["start"] = start
            self.rpc.update(**kwargs)
        except Exception as e: 
            self.log(f"RPC Update Failed: {e}")
            self.rpc_connected = False

    def _set_auto_download(self, enabled):
        self.auto_download_mod = bool(enabled)
        self.save_config()

    def log(self, message):
        # Update UI
        try:
            if hasattr(self, 'log_area') and self.log_area.winfo_exists():
                timestamp = datetime.now().strftime("%H:%M:%S")
                # Strip [GAME] prefix for UI if needed, but keeping it is good for context
                line = f"[{timestamp}] {self._mask_streamer_text(message)}"
                self.log_area.insert(tk.END, line + "\n")
                self.log_area.see(tk.END)
        except:
            pass
        
        # Write to log file via logging module
        logging.info(message)

    def set_status(self, text, color=None):
        self.status_label.config(text=text, fg=color if color else COLORS['text_secondary'])

    def get_head_from_skin(self, skin_path, size=40):
        if not hasattr(self, '_skin_head_cache'):
            self._skin_head_cache = {}
        try:
            if skin_path and os.path.exists(skin_path):
                st = os.stat(skin_path)
                cache_key = (skin_path, st.st_mtime, st.st_size, size)
                if cache_key in self._skin_head_cache:
                    return self._skin_head_cache[cache_key]

                img = Image.open(skin_path).convert("RGBA")
                # Base head is 8x8 at (8, 8, 16, 16)
                head = img.crop((8, 8, 16, 16))
                # Outer hat/helm overlay is at (40, 8, 48, 16)
                try:
                    hat = img.crop((40, 8, 48, 16))
                    if hat.getbbox():
                        head.alpha_composite(hat)
                except Exception:
                    pass
                photo = ImageTk.PhotoImage(head.resize((size, size), RESAMPLE_NEAREST))
                self._skin_head_cache[cache_key] = photo
                return photo
        except Exception:
            pass

        return _build_missing_skin_head(size)

    def export_current_skin(self):
        """Export currently equipped player skin PNG to user-chosen destination."""
        if not self.skin_path or not os.path.exists(self.skin_path):
            custom_showwarning("No Skin", "No skin is currently equipped to export.", parent=self.root)
            return
        default_name = os.path.basename(self.skin_path)
        out_file = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export Skin PNG",
            defaultextension=".png",
            initialfile=default_name,
            filetypes=[("PNG Image", "*.png")]
        )
        if out_file:
            try:
                shutil.copy2(self.skin_path, out_file)
                if hasattr(self, 'toast_manager'):
                    self.toast_manager.show(f"Skin exported: {os.path.basename(out_file)}", level="success")
                else:
                    custom_showinfo("Exported", f"Skin saved to:\n{out_file}", parent=self.root)
            except Exception as e:
                custom_showerror("Export Error", f"Failed to save skin: {e}", parent=self.root)

    def update_active_profile(self):
        if not self.profiles:
            self.skin_path = ""
            if hasattr(self, 'user_entry'):
                self.user_entry.delete(0, tk.END)
            self.update_profile_btn()
            return

        p = self.profiles[self.current_profile_index]
        if not isinstance(p.get("name"), str) or not p["name"].strip():
            p["name"] = str(getattr(self, "username", "") or DEFAULT_USERNAME)
        old_skin_path = self.skin_path
        self.skin_path = p.get("skin_path", "")
        self.username = p.get("name", DEFAULT_USERNAME)
        
        # Enforce settings based on account type
        p_type = p.get("type", "offline")
        if p_type == "microsoft":
            self.auto_download_mod = False
            if hasattr(self, 'auto_download_var'):
                 self.auto_download_var.set(False)
        
        if hasattr(self, 'user_entry'):
            try:
                if self.user_entry.winfo_exists():
                    self.user_entry.delete(0, tk.END)
                    self.user_entry.insert(0, p.get("name", "Steve"))
                    self.user_entry.config(show="*" if self._is_streamer_mode_enabled() else "")
            except Exception:
                pass
        if hasattr(self, 'username_var'):
            try:
                self.username_var.set(p.get("name", "Steve"))
            except Exception:
                pass
        
        # Update Model Radio var BEFORE rendering
        if hasattr(self, 'skin_model_var'):
            self.skin_model_var.set(p.get("skin_model", "classic"))
        
        # Only render if skin path changed or is set
        if self.skin_path and (self.skin_path != old_skin_path or not old_skin_path):
            self.render_preview()
        elif not self.skin_path and hasattr(self, 'preview_canvas'):
            self.preview_canvas.delete("all")  # Clear preview if no skin

        self.update_skin_indicator()
        self.update_profile_btn()
        if hasattr(self, 'update_bottom_gamertag'): self.update_bottom_gamertag()
        
        # Load account capes in background and update locker UI
        if hasattr(self, 'load_account_capes_async'):
            self.load_account_capes_async()
        if hasattr(self, 'update_locker_subtabs'):
            self.update_locker_subtabs()

        # Refresh skin history if on Locker tab
        if self.current_tab == "Locker" and hasattr(self, 'locker_view') and self.locker_view.get() == "Skins":
            if hasattr(self, 'render_skin_history'):
                self.render_skin_history()

        # Refresh sidebar account drawer if open
        if hasattr(self, 'render_sidebar_account_drawer') and getattr(self, 'sidebar_account_drawer_open', False):
            self.render_sidebar_account_drawer()
        
    def update_profile_btn(self):
        # Update text labels
        if not self.profiles: return
        p = self.profiles[self.current_profile_index]
        
        if hasattr(self, 'sidebar_username'):
            self.sidebar_username.config(text=self._get_streamer_safe_name(p.get("name", "Steve")))
        
        if hasattr(self, 'sidebar_acct_type'):
            t = p.get("type", "offline")
            if t == "microsoft":
                label_text = "Microsoft Account"
            elif t == "ely.by":
                label_text = "Ely.by Account"
            else:
                label_text = "Offline Account"
            self.sidebar_acct_type.config(text=label_text)

        # Update Head Image
        if hasattr(self, 'sidebar_head_label'):
            img = self.get_head_from_skin(self.skin_path, size=35)
            if img:
                self.sidebar_head_img = img 
                self.sidebar_head_label.config(image=img)

    def load_from_config(self):
        print(f"Loading config from: {self.config_file}")
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = ConfigManager(self.config_file).load()
                    if not isinstance(data, dict):
                        raise ValueError("Configuration root must be a JSON object.")

                    # Old, partially-written, or hand-edited configuration
                    # should not crash the launcher.  Keep valid records and
                    # let the regular atomic save migrate the rest.
                    raw_profiles = data.get("profiles", [])
                    data["profiles"] = [item for item in raw_profiles if isinstance(item, dict)] if isinstance(raw_profiles, list) else []
                    raw_installations = data.get("installations", [])
                    data["installations"], installations_changed = normalize_installations(raw_installations)
                    if not isinstance(data.get("addons", {}), dict):
                        data["addons"] = {}

                    # First Run Check (Must be done before any save_config triggers)
                    self.first_run = not data.get("first_run_completed", False)
                    self.addons_config = data.get("addons", {})
                    
                    # Profiles (Accounts)
                    self.profiles = data.get("profiles", [])
                    if not self.profiles:
                        old_user = data.get("username", DEFAULT_USERNAME)
                        old_skin = data.get("skin_path", "")
                        self.profiles = [{"name": old_user, "type": "offline", "skin_path": old_skin, "uuid": ""}]
                    
                    # Installations (Game Configs)
                    self.installations = data.get("installations", [])
                    print(f"Loaded {len(self.installations)} installations")
                    
                    idx = data.get("current_profile_index", 0)
                    self.current_profile_index = idx if 0 <= idx < len(self.profiles) else 0
                    
                    active_id = data.get("active_installation_id")
                    inst_idx = next(
                        (i for i, installation in enumerate(self.installations)
                         if installation.get("id") == active_id),
                        data.get("current_installation_index", 0),
                    )
                    self.current_installation_index = inst_idx if 0 <= inst_idx < len(self.installations) else 0
                    data["active_installation_id"] = self.installations[self.current_installation_index]["id"]
                    if installations_changed or data.get("version") != CURRENT_VERSION:
                        self._write_config_payload(data)

                    self.update_active_profile()

                    loader_choice = data.get("loader", LOADERS[0])
                    self.loader_var.set(loader_choice if loader_choice in LOADERS else LOADERS[0])
                    self.last_version = data.get("last_version", "")
                    self.auto_download_mod = data.get("auto_download_mod", False)
                    self.auto_download_var.set(self.auto_download_mod)
                    try:
                        self.ram_allocation = max(512, int(data.get("ram_allocation", DEFAULT_RAM)))
                    except (TypeError, ValueError):
                        self.ram_allocation = DEFAULT_RAM
                    self.ram_var.set(self.ram_allocation)
                    self.ram_entry_var.set(str(self.ram_allocation))

                    # Downloads & Features
                    try:
                        self.max_concurrent_packs = max(1, min(3, int(data.get("max_concurrent_packs", 1))))
                    except (TypeError, ValueError):
                        self.max_concurrent_packs = 1
                    try:
                        self.max_concurrent_mods = max(1, min(8, int(data.get("max_concurrent_mods", 3))))
                    except (TypeError, ValueError):
                        self.max_concurrent_mods = 3
                    self.limit_download_speed_enabled = data.get("limit_download_speed_enabled", False)
                    self.max_download_speed = data.get("max_download_speed", 2048) # KB/s
                    self.enable_modrinth = True
                    loaded_mods_view = str(data.get("installed_mods_view_mode", "grid")).lower()
                    self.installed_mods_view_mode = loaded_mods_view if loaded_mods_view in ("grid", "list") else "grid"
                    
                    # Addons
                    if "addons" in data:
                        self.addons_config.update(data["addons"])
                    self._ensure_addons_config_defaults()

                    # Instances & Asset Sharing
                    instances_cfg = data.get("instances", {})
                    if not isinstance(instances_cfg, dict):
                        instances_cfg = {}
                    self.instances_config = {
                        "share_resourcepacks": bool(instances_cfg.get("share_resourcepacks", True)),
                        "share_shaderpacks": bool(instances_cfg.get("share_shaderpacks", True)),
                        "share_worlds": bool(instances_cfg.get("share_worlds", False)),
                        "share_configs": bool(instances_cfg.get("share_configs", False)),
                    }

                    # Load RPC
                    self.rpc_enabled = data.get("rpc_enabled", True)
                    self.rpc_var.set(self.rpc_enabled)
                    
                    # New Detail Mode with Backward Compat
                    saved_mode = data.get("rpc_detail_mode", None)
                    if saved_mode:
                        self.rpc_detail_mode_var.set(saved_mode)
                    else:
                        # Infer from old bools
                        show_ver = data.get("rpc_show_version", True)
                        show_serv = data.get("rpc_show_server", True)
                        if show_ver: val = "Show Version"
                        elif show_serv: val = "Show Server IP"
                        else: val = "Hidden"
                        self.rpc_detail_mode_var.set(val)
                    
                    self.rpc_show_version = (self.rpc_detail_mode_var.get() == "Show Version")
                    self.rpc_show_server = (self.rpc_detail_mode_var.get() == "Show Server IP")
                    self.auto_update_check = data.get("auto_update_check", True)
                    self.custom_titlebar_enabled = data.get("custom_titlebar_enabled", True)
                    self.neo_style_enabled = data.get("neo_style_enabled", True)
                    self.close_launcher = data.get("close_launcher", True)
                    self.minimize_to_tray = data.get("minimize_to_tray", False)
                    self.show_console = data.get("show_console", False)
                    self.theme_id = data.get("theme_id", getattr(self, "theme_id", "dark_slate"))
                    if self.theme_id not in THEMES:
                        self.theme_id = "dark_slate"
                    self.custom_accent = data.get("custom_accent", getattr(self, "custom_accent", None))
                    self.animations_enabled = data.get("animations_enabled", True)
                    self.apply_theme(self.theme_id, self.custom_accent, save=False)
                    
                    if self.rpc_enabled:
                        self.root.after(1000, self.connect_rpc)

                    # Load Java Args
                    self.java_args = data.get("java_args", "")
                    if hasattr(self, 'java_args_entry'):
                        self.java_args_entry.delete(0, tk.END)
                        self.java_args_entry.insert(0, self.java_args)

                    self.refresh_addons_tab_state()

                    # Load Custom Directory
                    custom_dir = data.get("minecraft_dir", "")
                    if custom_dir and os.path.isdir(custom_dir):
                        self.minecraft_dir = custom_dir
                    
                    if hasattr(self, 'dir_entry'):
                        self.dir_entry.delete(0, tk.END)
                        self.dir_entry.insert(0, self.minecraft_dir)
                    
                    # Load Wallpaper
                    wp = data.get("current_wallpaper")
                    if wp and os.path.exists(wp):
                         self.current_wallpaper = wp
                         try:
                             self.hero_img_raw = Image.open(wp)
                             if hasattr(self, 'hero_canvas'):
                                  w = self.hero_canvas.winfo_width()
                                  h = self.hero_canvas.winfo_height()
                                  # If window is already visible/sized
                                  if w > 1 and h > 1:
                                      self._update_hero_layout(type('obj', (object,), {'width':w, 'height':h}))
                         except Exception as e:
                             print(f"Failed to load saved wallpaper: {e}")
                    else:
                         self.current_wallpaper = None
                         
            except Exception as e: 
                print(f"Error loading config: {e}")
                self.create_default_profile()
                self.first_run = True # Error implies we should probable re-onboard or fallback
        else: 
            print("Config file not found, creating default")
            self.create_default_profile()
            self.first_run = True # Explicitly true for no config

        # --- Default Wallpaper Fallback ---
        if not self.hero_img_raw:
             try:
                 # Check for 'xse1m641dw9f1.png' or other wallpapers in wallpapers dir
                 possible_defaults = ["xse1m641dw9f1.png", "q66ll6p2dw9f1.png", "Island.png", "background.png"]
                 for name in possible_defaults:
                     path = resource_path(os.path.join("wallpapers", name))
                     if os.path.exists(path):
                         self.current_wallpaper = path
                         self.hero_img_raw = Image.open(path)
                         print(f"Loaded default wallpaper: {name}")
                         break
             except Exception as e:
                 print(f"Failed to load default wallpaper: {e}")
            
        # Trigger background check for MS skin model to ensure radio button matches server
        if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
            try:
                p = self.profiles[self.current_profile_index]
                if p.get("type") == "microsoft":
                     threading.Thread(target=self._startup_ms_skin_check, daemon=True).start()
            except: pass

    def _build_config_payload(self, sync_ui=True):
        if sync_ui and self.profiles and 0 <= self.current_profile_index < len(self.profiles):
            self.profiles[self.current_profile_index]["skin_path"] = self.skin_path
            if hasattr(self, 'user_entry'):
                name = self.user_entry.get().strip()
                if name:
                    self.profiles[self.current_profile_index]["name"] = name

        if sync_ui and hasattr(self, 'java_args_entry'):
            self.java_args = self.java_args_entry.get().strip()

        rpc_mode = "Show Version"
        if hasattr(self, 'rpc_detail_mode_var'):
            rpc_mode = self.rpc_detail_mode_var.get()
        if hasattr(self, 'auto_update_var'):
            self.auto_update_check = self.auto_update_var.get()

        self.rpc_show_version = (rpc_mode == "Show Version")
        self.rpc_show_server = (rpc_mode == "Show Server IP")

        close_launcher_val = getattr(self, 'close_launcher', True)
        if hasattr(self, 'close_launcher_var'):
            close_launcher_val = self.close_launcher_var.get()

        minimize_to_tray_val = getattr(self, 'minimize_to_tray', False)
        if hasattr(self, 'minimize_to_tray_var'):
            minimize_to_tray_val = self.minimize_to_tray_var.get()

        show_console_val = getattr(self, 'show_console', False)
        if hasattr(self, 'show_console_var'):
            show_console_val = self.show_console_var.get()

        return {
            "last_version": getattr(self, "last_version", ""),
            "first_run_completed": not self.first_run,
            "accent_color": getattr(self, "accent_color_name", "Green"),
            "profiles": self.profiles,
            "installations": self.installations,
            "current_profile_index": self.current_profile_index,
            "current_installation_index": getattr(self, 'current_installation_index', 0),
            "active_installation_id": (
                self.installations[getattr(self, 'current_installation_index', 0)].get("id")
                if self.installations and 0 <= getattr(self, 'current_installation_index', 0) < len(self.installations)
                else None
            ),
            "version": CURRENT_VERSION,
            "loader": self.loader_var.get() if hasattr(self, 'loader_var') else "Vanilla",
            "auto_download_mod": self.auto_download_mod,
            "ram_allocation": self.ram_allocation,
            "java_args": self.java_args,
            "minecraft_dir": self.minecraft_dir,
            "rpc_enabled": self.rpc_enabled,
            "rpc_detail_mode": rpc_mode,
            "rpc_show_version": self.rpc_show_version,
            "rpc_show_server": self.rpc_show_server,
            "auto_update_check": self.auto_update_check,
            "custom_titlebar_enabled": getattr(self, 'custom_titlebar_enabled', True),
            "neo_style_enabled": getattr(self, 'neo_style_enabled', True),
            "theme_id": getattr(self, "theme_id", "dark_slate"),
            "custom_accent": getattr(self, "custom_accent", None),
            "animations_enabled": getattr(self, "animations_enabled", True),
            "max_concurrent_packs": getattr(self, 'max_concurrent_packs', 1),
            "max_concurrent_mods": getattr(self, 'max_concurrent_mods', 3),
            "limit_download_speed_enabled": getattr(self, 'limit_download_speed_enabled', False),
            "max_download_speed": getattr(self, 'max_download_speed', 2048),
            "enable_modrinth": True,
            "installed_mods_view_mode": getattr(self, 'installed_mods_view_mode', 'grid'),
            "close_launcher": close_launcher_val,
            "minimize_to_tray": minimize_to_tray_val,
            "show_console": show_console_val,
            "current_wallpaper": getattr(self, 'current_wallpaper', None),
            "addons": getattr(self, "addons_config", {}),
            "instances": getattr(self, "instances_config", {
                "share_resourcepacks": True,
                "share_shaderpacks": True,
                "share_worlds": False,
                "share_configs": False,
            })
        }

    def _write_config_payload(self, config):
        tmp_path = f"{self.config_file}.tmp"
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.config_file)
        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            print(f"Failed to save config: {e}")

    def _flush_pending_config_save(self):
        self._config_save_after_id = None
        sync_ui = bool(getattr(self, "_config_sync_ui_pending", False))
        self._config_sync_ui_pending = False
        self._write_config_payload(self._build_config_payload(sync_ui=sync_ui))

    def save_config(self, *args, sync_ui=True, immediate=False):
        self._config_sync_ui_pending = bool(getattr(self, "_config_sync_ui_pending", False) or bool(sync_ui))

        if immediate:
            if getattr(self, "_config_save_after_id", None) is not None:
                try:
                    self.root.after_cancel(self._config_save_after_id)
                except Exception:
                    pass
                self._config_save_after_id = None
            self._flush_pending_config_save()
            return

        delay = max(50, int(getattr(self, "_config_save_delay_ms", 250)))
        if self._config_save_after_id is not None:
            try:
                self.root.after_cancel(self._config_save_after_id)
            except Exception:
                pass
        try:
            self._config_save_after_id = self.root.after(delay, self._flush_pending_config_save)
        except Exception:
            self._config_save_after_id = None
            self._flush_pending_config_save()

    def create_default_profile(self):
        self.profiles = [{"name": DEFAULT_USERNAME, "type": "offline", "skin_path": "", "uuid": ""}]
        self.installations = [{
            "id": str(uuid.uuid4()),
            "name": "Latest Release",
            "version": "latest-release",
            "loader": "Vanilla",
            "icon": "icons/grass_block_side.png",
            "java_executable": "",
            "resolution_width": None,
            "resolution_height": None,
            "last_played": "Never",
            "created": "2024-01-01"
        }]
        self.current_profile_index = 0
        self.current_installation_index = 0
        self.update_active_profile()

    def load_versions(self):
        """Warm the metadata cache without blocking launcher startup.

        The installation editor owns the actual selector; this cache keeps it
        responsive when users open it for the first time.
        """
        if getattr(self, "_version_load_started", False):
            return
        self._version_load_started = True

        def fetch():
            try:
                versions = minecraft_launcher_lib.utils.get_version_list()
                cleaned = [
                    {"id": str(item.get("id")), "type": str(item.get("type", "release"))}
                    for item in versions if isinstance(item, dict) and item.get("id")
                ]
                self.cached_vanilla_versions = cleaned
                self.log(f"Loaded {len(cleaned)} Minecraft versions.")
            except Exception as exc:
                self.cached_vanilla_versions = []
                self.log(f"Could not load Minecraft version metadata: {exc}")
            finally:
                self._version_load_started = False

        threading.Thread(target=fetch, daemon=True, name="version-metadata").start()

    def _apply_version_list(self, loader, display_list):
        """Compatibility hook for older UI surfaces that expose a combobox."""
        for widget_name in ("version_combo", "version_dropdown"):
            widget = getattr(self, widget_name, None)
            if widget is None:
                continue
            try:
                widget["values"] = display_list
                if display_list and not self.version_var.get():
                    self.version_var.set(display_list[0])
            except (tk.TclError, TypeError):
                pass

    def on_loader_change(self, event):
        self.load_versions()
        self.save_config()

    def on_version_change(self, event):
        self.save_config()

    def launch_installation(self, idx, server_address=None, server_port=None):
        if 0 <= idx < len(self.installations):
            self.current_installation_index = idx
            self.show_tab("Play")
            self.update_installation_dropdown()
            self.start_launch(server_address=server_address, server_port=server_port)

    def update_skin_indicator(self):
        if not hasattr(self, 'skin_indicator') or not self.skin_indicator.winfo_exists(): return
        
        # Determine current account type
        current_profile = self.profiles[self.current_profile_index] if (self.profiles and 0 <= self.current_profile_index < len(self.profiles)) else {}
        acct_type = current_profile.get("type", "offline")

        if acct_type == "ely.by":
            self.skin_indicator.config(text="Skin via Ely.by", fg=COLORS['success_green'])
            return

        # Offline
        if getattr(self, 'auto_download_mod', False):
             if getattr(self, 'skin_path', None):
                 self.skin_indicator.config(text="Ready: Local Skin Injection", fg=COLORS['success_green'])
             else:
                 self.skin_indicator.config(text="Injection enabled (No Skin)", fg=COLORS['accent_blue'])
        else:
            self.skin_indicator.config(text="Skin Injection Disabled", fg=COLORS['text_secondary'])

    def custom_skin_model_popup(self, parent=None):
        # Returns "classic" or "slim" or None if cancelled
        result = {"model": None}
        current_model = "classic"
        if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
            current_model = self.profiles[self.current_profile_index].get("skin_model", "classic")

        mgr = get_modal_manager(self.root)
        if not mgr:
            return current_model

        wait_var = tk.BooleanVar(self.root, value=False)

        def on_close():
            if not wait_var.get():
                wait_var.set(True)

        def build_content(body_frame, close_modal):
            tk.Label(
                body_frame,
                text="Does your skin have 3px (Slim) or 4px (Classic) arms?",
                font=("Segoe UI", 9),
                bg=COLORS['card_bg'],
                fg=COLORS['text_secondary'],
            ).pack(anchor="w", pady=(0, 16))

            btn_frame = tk.Frame(body_frame, bg=COLORS['card_bg'])
            btn_frame.pack(fill="x", pady=5)

            def set_classic():
                result["model"] = "classic"
                close_modal()

            def set_slim():
                result["model"] = "slim"
                close_modal()

            b1 = self._make_btn(
                btn_frame,
                "Classic (Steve)\n4px Arms",
                style="primary" if current_model == "classic" else "secondary",
                font_size=10,
                command=set_classic,
            )
            b1.pack(side="left", fill="both", expand=True, padx=(0, 6))

            b2 = self._make_btn(
                btn_frame,
                "Slim (Alex)\n3px Arms",
                style="primary" if current_model == "slim" else "secondary",
                font_size=10,
                command=set_slim,
            )
            b2.pack(side="right", fill="both", expand=True, padx=(6, 0))

        mgr.show_modal("Select Skin Model", build_content, width=420, height=220, on_close=on_close)
        self.root.wait_variable(wait_var)
        return result["model"]

    def upload_ms_skin(self, path, variant, token):
        self.log(f"DEBUG: Uploading skin to Minecraft... Path: {path}, Variant: {variant}")
        try:
             url = "https://api.minecraftservices.com/minecraft/profile/skins"
             # Mask token in logs for security, only show first few chars
             masked_token = token[:8] + "..." if len(token) > 8 else "***"
             self.log(f"DEBUG: Request URL: {url}")
             self.log(f"DEBUG: Auth Token: {masked_token}")
             
             headers = {"Authorization": f"Bearer {token}"}
             files = {
                 "variant": (None, variant),
                 "file": ("skin.png", open(path, "rb"), "image/png")
             }
             
             r = requests.post(url, headers=headers, files=files)
             
             self.log(f"DEBUG: Response Status: {r.status_code}")
             self.log(f"DEBUG: Response Headers: {r.headers}")
             self.log(f"DEBUG: Response Body: {r.text}")
             
             if r.status_code == 200:
                 self.log(f"Skin uploaded successfully ({variant})")
                 return True
             else:
                 self.log(f"Skin upload failed: {r.status_code} {r.text}")
                 return False
        except Exception as e:
            self.log(f"Upload exception: {e}")
            import traceback
            self.log(traceback.format_exc())
            return False

    def check_mod_online(self, mc_version, loader):
        pass # Deprecated

    def render_preview(self):
        if hasattr(self, 'render_3d_stage_frame'):
            self.render_3d_stage_frame()
            return
        try:
            # Check if preview canvas exists and is visible
            if not hasattr(self, 'preview_canvas') or not self.preview_canvas.winfo_exists():
                return
                
            if not self.skin_path or not os.path.exists(self.skin_path): 
                self.preview_canvas.delete("all")
                return
            
            # Determine model
            model = "classic"
            if self.profiles:
                 model = self.profiles[self.current_profile_index].get("skin_model", "classic")

            # Use 3D Renderer
            w = self.preview_canvas.winfo_width()
            h = self.preview_canvas.winfo_height()
            # Defaults if not mapped yet
            if w < 50: w = 300
            if h < 50: h = 360
            
            # Cache key for rendered skin
            cache_key = (self.skin_path, model, h)
            
            self.preview_canvas.delete("all")

            # Draw 3D Showcase Pedestal
            pedestal_y = int(h * 0.86)
            pw, ph = int(min(w * 0.75, 240)), 32
            self.preview_canvas.create_oval(
                (w - pw) // 2, pedestal_y - ph // 2,
                (w + pw) // 2, pedestal_y + ph // 2,
                fill=COLORS.get('input_bg', '#151821'),
                outline=COLORS.get('card_border', '#2F3647'),
                width=2
            )
            inner_pw, inner_ph = int(pw * 0.76), 22
            self.preview_canvas.create_oval(
                (w - inner_pw) // 2, pedestal_y - inner_ph // 2,
                (w + inner_pw) // 2, pedestal_y + inner_ph // 2,
                fill=COLORS.get('card_bg', '#1A1E29'),
                outline=COLORS.get('accent_color', '#2ECC71'),
                width=1
            )

            # Check if we already have this rendered in cache
            if hasattr(self, '_preview_cache') and cache_key in self._preview_cache:
                self.preview_photo = self._preview_cache[cache_key]
                self.preview_canvas.create_image(w // 2, pedestal_y - int(h * 0.44), image=self.preview_photo, anchor="center")
                return

            rendered = SkinRenderer3D.render(self.skin_path, model, height=int(h * 0.82))
            if rendered:
                self.preview_photo = ImageTk.PhotoImage(rendered)

                if not hasattr(self, '_preview_cache'):
                    self._preview_cache = {}
                self._preview_cache[cache_key] = self.preview_photo

                if len(self._preview_cache) > 10:
                    self._preview_cache.pop(next(iter(self._preview_cache)))

                self.preview_canvas.create_image(w // 2, pedestal_y - int(h * 0.44), image=self.preview_photo, anchor="center")
        except Exception as e:
            print(f"Preview Error: {e}")

    def refresh_skin(self):
        p = self.profiles[self.current_profile_index] if self.profiles else {}
        p_type = p.get("type", "offline")
        name = p.get("name", "")
        uuid_ = p.get("uuid", "")
        
        if p_type == "ely.by":
            self.skin_indicator.config(text="Refreshing...", fg=COLORS['text_primary'])
            self.root.update()
            
            def _refresh():
                path = self.fetch_elyby_skin(name, uuid_)
                
                def _update_ui():
                    if path:
                        self.profiles[self.current_profile_index]["skin_path"] = path
                        self.update_active_profile()
                        self.add_skin_to_history(path, "classic")
                        custom_showinfo("Skin Refreshed", "Skin updated from Ely.by successfully.")
                    else:
                        self.skin_indicator.config(text="Refresh Failed", fg="red")
                        custom_showwarning("Refresh Failed", "Could not fetch skin from Ely.by.")
                
                self.root.after(0, _update_ui)
            
            threading.Thread(target=_refresh, daemon=True).start()
        
        elif p_type == "microsoft":
            self.skin_indicator.config(text="Refreshing...", fg=COLORS['text_primary'])
            self.root.update()
            
            def _refresh_ms():
                token = p.get("access_token")
                path = self.fetch_microsoft_skin(name, uuid_, token)
                
                def _update_ui():
                    if path:
                        self.profiles[self.current_profile_index]["skin_path"] = path
                        # Model is updated in profile by fetch_microsoft_skin side-effect
                        model = self.profiles[self.current_profile_index].get("skin_model", "classic")
                        self.update_active_profile()
                        self.add_skin_to_history(path, model)
                        # Don't show success box if auto-called (check if called by user?) or just show small toast?
                        # For now, let's keep it but maybe it's annoying if auto-called.
                        # Actually, better to just log it if successful, only warn on fail.
                        pass # self.log("Skin updated")
                    else:
                        self.skin_indicator.config(text="Refresh Failed", fg="red")
                        # messagebox.showwarning("Refresh Failed", "Could not fetch skin. Session might be expired.")
                
                self.root.after(0, _update_ui)
                
            threading.Thread(target=_refresh_ms, daemon=True).start()
            
        else:
             self.update_active_profile()

    def _startup_ms_skin_check(self):
        try:
            if not self.profiles: return
            p = self.profiles[self.current_profile_index]
            token = p.get("access_token")
            if not token: return

            headers = {"Authorization": f"Bearer {token}"}
            # Silent check
            r = requests.get("https://api.minecraftservices.com/minecraft/profile", headers=headers, timeout=5)
            if r.status_code == 200:
                data = r.json()
                skins = data.get("skins", [])
                active_skin = next((s for s in skins if s["state"] == "ACTIVE"), None)
                if active_skin:
                    variant = active_skin.get("variant", "CLASSIC").lower()
                    # Check against local
                    local_model = p.get("skin_model", "classic")
                    
                    if variant != local_model:
                         self.log(f"Syncing skin model to match server ({variant})")
                         p["skin_model"] = variant
                         if hasattr(self, 'skin_model_var'):
                             self.root.after(0, lambda: self.skin_model_var.set(variant))
                         self.save_config(sync_ui=False)
        except: pass

    def fetch_microsoft_skin(self, username, uuid_, token):
        try:
            headers = {"Authorization": f"Bearer {token}"}
            # Fetch Profile
            r = requests.get("https://api.minecraftservices.com/minecraft/profile", headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                skins = data.get("skins", [])
                active_skin = next((s for s in skins if s["state"] == "ACTIVE"), None)
                
                if active_skin:
                    skin_url = active_skin["url"]
                    variant = active_skin.get("variant", "CLASSIC").lower()
                    
                    # Store model
                    if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
                         self.profiles[self.current_profile_index]["skin_model"] = "classic" if variant == "classic" else "slim"
                    
                    # Download
                    target_path = os.path.join(self.config_dir, "skins", f"{username}_ms.png")
                    if not os.path.exists(os.path.dirname(target_path)):
                        os.makedirs(os.path.dirname(target_path))
                        
                    print(f"Downloading MS skin from {skin_url}")
                    r_img = requests.get(skin_url, timeout=10)
                    if r_img.status_code == 200:
                        with open(target_path, "wb") as f:
                            f.write(r_img.content)
                        return target_path
            else:
                 print(f"MS Profile fetch failed: {r.status_code}")
                 
        except Exception as e:
            print(f"Error fetching MS skin: {e}")
            
        return ""

    def fetch_elyby_skin(self, username, uuid_, properties=None):
        skin_url = f"http://skinsystem.ely.by/skins/{username}.png"
        props = properties if properties else []

        try:
            # If properties are missing, fetch them from the Session Server
            if not props and uuid_:
                print(f"[DEBUG] Properties missing, fetching from Session Server for {uuid_}")
                try:
                    # Ely.by Session Server endpoint
                    session_url = f"https://authserver.ely.by/api/authlib-injector/sessionserver/session/minecraft/profile/{uuid_}?unsigned=false"
                    r_sess = requests.get(session_url, timeout=5)
                    if r_sess.status_code == 200:
                        session_profile = r_sess.json()
                        props = session_profile.get("properties", [])
                        print(f"[DEBUG] Session Server returned {len(props)} properties")
                except Exception as ex:
                    print(f"[ERROR] Session Server fetch failed: {ex}")

            # If still no properties/textures, try the /textures/ endpoint on skinsystem
            if not props:
                 print(f"[DEBUG] Session server produced no props, trying skinsystem/textures/{username}")
                 try:
                     r_tex = requests.get(f"http://skinsystem.ely.by/textures/{username}", timeout=5)
                     if r_tex.status_code == 200:
                         tex_data_direct = r_tex.json()
                         if "SKIN" in tex_data_direct and "url" in tex_data_direct["SKIN"]:
                             skin_url = tex_data_direct["SKIN"]["url"]
                             print(f"[DEBUG] Resolved skin URL from skinsystem/textures: {skin_url}")
                             props = [] 
                 except Exception as e_tex:
                     print(f"[DEBUG] Skinsystem texture fetch failed: {e_tex}")

            for prop in props:
                if prop.get("name") == "textures":
                    val = prop.get("value")
                    # value is base64 encoded json
                    decoded = base64.b64decode(val).decode('utf-8')
                    tex_data = json.loads(decoded)
                    if "textures" in tex_data and "SKIN" in tex_data["textures"]:
                        extracted_url = tex_data["textures"]["SKIN"].get("url")
                        if extracted_url:
                            skin_url = extracted_url
                            print(f"[DEBUG] Resolved skin URL: {skin_url}")
        except Exception as e:
            print(f"[ERROR] Failed to extract skin data: {e}")

        # Download
        target_path = os.path.join(self.config_dir, "skins", f"{username}.png")
        if not os.path.exists(os.path.dirname(target_path)):
             os.makedirs(os.path.dirname(target_path))
             
        try:
            print(f"[DEBUG] Fetching skin from {skin_url}")
            r_skin = requests.get(skin_url, timeout=5)
            if r_skin.status_code == 200:
                with open(target_path, "wb") as f:
                    f.write(r_skin.content)
                print(f"[DEBUG] Saved skin to {target_path}")
                return target_path
            else:
                 print(f"Ely.by skin not found (Status {r_skin.status_code})")
        except Exception as e:
            print(f"Skin fetch exception: {e}")
            if os.path.exists(target_path):
                return target_path 
        
        return ""

    def select_skin(self):
        # Check profile type
        p = self.profiles[self.current_profile_index] if self.profiles else {}
        if p and not str(p.get("name", "")).strip():
            p["name"] = str(getattr(self, "username", "") or DEFAULT_USERNAME)
        p_type = p.get("type", "offline")
        
        if p_type == "ely.by":
            if custom_askyesno("Ely.by Skin", "Ely.by requires skins to be managed via their website.\n\nOpen Ely.by skin catalog for your user?"):
                name = p.get("name", "")
                webbrowser.open(f"https://ely.by/skins?uploader={name}")
            return
            
        elif p_type == "microsoft":
             # Upload Logic directly
             path = filedialog.askopenfilename(filetypes=[("Image files", "*.png")])
             if not path: return
             
             # Verify size
             try:
                 im = Image.open(path)
                 w, h = im.size
                 if w != 64 or (h != 64 and h != 32):
                     if not custom_askyesno("Warning", f"Skin dimensions {w}x{h} might not work perfectly. Standard is 64x64. Continue?"):
                         return
                 
                 token = p.get("access_token")
                 
                 # Ask model
                 variant = self.custom_skin_model_popup()
                 if not variant: return # Cancelled
                     
                 # Upload
                 if self.upload_ms_skin(path, variant, token):
                     custom_showinfo("Success", "Skin uploaded successfully!")
                     self.profiles[self.current_profile_index]["skin_path"] = path
                     self.profiles[self.current_profile_index]["skin_model"] = variant
                     
                     # Update UI
                     self.skin_path = path
                     if hasattr(self, 'skin_model_var'):
                         self.skin_model_var.set(variant)
                     self.render_preview()
                     self.update_skin_indicator()
                     
                     # Add to history and save once
                     self.add_skin_to_history(path, variant)
                 else:
                     custom_showerror("Error", f"Failed to upload skin.")
                     
             except Exception as e:
                 custom_showerror("Error", f"Upload failed: {e}")
             return

        # Offline / Standard
        if not self.auto_download_mod:
            if custom_askyesno("Skin Injection", "Enable Skin Injection to use this skin in-game?"):
                self.auto_download_mod = True
                self.auto_download_var.set(True)
        path = filedialog.askopenfilename(filetypes=[("Image files", "*.png")])
        if path:
            # Ask model for offline usage too (for correct injections/rendering)
            variant = self.custom_skin_model_popup() or "classic"
            
            self.skin_path = path
            if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
                profile = self.profiles[self.current_profile_index]
                profile["name"] = str(profile.get("name", "") or getattr(self, "username", "") or DEFAULT_USERNAME)
                profile["skin_path"] = path
                profile["skin_model"] = variant
            
            # Update UI
            if hasattr(self, 'skin_model_var'):
                self.skin_model_var.set(variant)
            self.render_preview()
            self.update_skin_indicator()
            
            # Add to history (will save config)
            self.add_skin_to_history(path, variant)

    def ensure_authlib_injector(self):
        """ Ensures authlib-injector is present. Code adapted to fetch latest release from GitHub. """
        jar_path = os.path.join(self.minecraft_dir, "authlib-injector.jar")
        if os.path.exists(jar_path) and os.path.getsize(jar_path) > 0:
             return jar_path
             
        repo = "yushijinhun/authlib-injector"
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        try:
            self.log("Checking for authlib-injector...")
            r = requests.get(api_url, timeout=10)
            if r.status_code == 200:
                release = r.json()
                for asset in release.get("assets", []):
                    if asset["name"].endswith(".jar"):
                        self.log(f"Downloading authlib-injector: {asset['name']}...")
                        r_file = requests.get(asset["browser_download_url"], stream=True)
                        with open(jar_path, "wb") as f:
                            for chunk in r_file.iter_content(8192): f.write(chunk)
                        return jar_path
        except Exception as e:
            self.log(f"Error downloading authlib-injector: {e}")
            
        return None

    def get_installations(self):
        # Return dict {id: inst}
        d = {}
        for inst in self.installations:
            if "id" in inst:
                d[inst["id"]] = inst
        return d

    def _normalize_java_executable_input(self, value):
        raw_value = os.path.expandvars(os.path.expanduser(str(value or "").strip()))
        if not raw_value or raw_value == "<Use Bundled Java Runtime>":
            return ""

        if os.path.isdir(raw_value):
            candidates = [
                os.path.join(raw_value, "bin", "java.exe"),
                os.path.join(raw_value, "bin", "javaw.exe"),
                os.path.join(raw_value, "bin", "java"),
            ]
            for candidate in candidates:
                if os.path.isfile(candidate):
                    return candidate
            raise ValueError(f"No Java executable was found inside '{raw_value}'.")

        if os.path.isfile(raw_value):
            return raw_value

        if shutil.which(raw_value):
            return raw_value

        raise ValueError(f"Java executable not found: {raw_value}")

    def _normalize_installation_resolution_value(self, value, label):
        raw_value = str(value or "").strip()
        if not raw_value or raw_value.lower() == "auto":
            return ""
        if not raw_value.isdigit():
            raise ValueError(f"Resolution {label} must be a number or 'Auto'.")

        numeric_value = int(raw_value)
        if numeric_value <= 0:
            raise ValueError(f"Resolution {label} must be greater than 0.")
        return str(numeric_value)

    def start_launch(self, force_update=False, server_address=None, server_port=None):
        # Close any open menus
        self._close_all_menus()
        if self._launch_in_progress:
            self.toast_manager.show("Minecraft is already being prepared.", kind="info")
            return
        
        if not self.installations: return
        
        idx = getattr(self, 'current_installation_index', 0)
        if not (0 <= idx < len(self.installations)): return
        
        inst = self.installations[idx]
        version_id = inst.get("version")
        loader = inst.get("loader", "Vanilla")
        java_executable = inst.get("java_executable", "")
        resolution_width = inst.get("resolution_width")
        resolution_height = inst.get("resolution_height")
        
        if not version_id:
            version_id = "latest-release"

        # Get username from current profile or entry
        username = DEFAULT_USERNAME
        if hasattr(self, 'user_entry'):
            username = self.user_entry.get().strip() or DEFAULT_USERNAME
        
        if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
             # Sync back to profile
             self.profiles[self.current_profile_index]["name"] = username
             username = self.profiles[self.current_profile_index]["name"]

        self.save_config()
        
        # Generate Background Resource Pack if wallpaper exists
        if self.current_wallpaper:
            self.create_background_resource_pack()

        # Show Progress Overlay
        self.show_progress_overlay("Launching Minecraft...")
        
        self.update_rpc("Launching...", f"Version: {version_id} ({loader})")

        self._launch_in_progress = True
        self.launch_btn.config(state="disabled", text="PREPARING...")
        self.launch_opts_btn.config(state="disabled")
        # self.set_status("Launching Minecraft...") # Redundant with overlay
        inst_id = inst.get("id")
        threading.Thread(
            target=self.launch_logic,
            args=(version_id, username, loader, force_update, inst_id, java_executable, resolution_width, resolution_height, server_address, server_port),
            daemon=True,
        ).start()

    def _version_metadata_is_valid(self, version_id):
        """Return whether an installed version has readable launch metadata."""
        version_dir = os.path.join(self.minecraft_dir, "versions", str(version_id))
        metadata_path = os.path.join(version_dir, f"{version_id}.json")
        if not os.path.isfile(metadata_path):
            return False
        try:
            with open(metadata_path, "r", encoding="utf-8") as metadata_file:
                metadata = json.load(metadata_file)
            return isinstance(metadata, dict) and metadata.get("id") == version_id
        except (OSError, ValueError, TypeError):
            return False

    def launch_logic(self, version, username, loader, force_update=False, inst_id=None, custom_java_executable="", resolution_width=None, resolution_height=None, server_address=None, server_port=None):
        # Callback wrapper to update overlay
        def update_status(t):
            self.log(f"Status: {t}")
            status_text = str(t)
            def apply_status():
                if hasattr(self, 'update_progress_label'):
                    self.update_progress_label.config(text=status_text)
                if hasattr(self, 'launch_btn') and self._launch_in_progress:
                    compact = status_text.upper().replace("DOWNLOADING", "DOWNLOADING")
                    self.launch_btn.config(text=(compact[:20] + "…") if len(compact) > 21 else compact)
            self.root.after(0, apply_status)

        def update_progress(v):
            if hasattr(self, 'update_progress_bar'):
                self.update_progress_bar.config(value=v)
                # Update counter label (Current / Max)
                try:
                    m = self.update_progress_bar['maximum']
                    if hasattr(self, 'update_counter_label') and m > 0:
                        self.update_counter_label.config(text=f"{int(v)} / {int(m)}")
                except: pass

        def set_max(m):
             if hasattr(self, 'update_progress_bar'):
                self.update_progress_bar.config(maximum=m)
                # Force update counter immediately if max changes
                try:
                    v = self.update_progress_bar['value']
                    if hasattr(self, 'update_counter_label') and m > 0:
                         self.update_counter_label.config(text=f"{int(v)} / {int(m)}")
                except: pass

        callback = cast(Any, {
            "setStatus": update_status,
            "setProgress": lambda v: self.root.after(0, lambda: update_progress(v)),
            "setMax": lambda m: self.root.after(0, lambda: set_max(m))
        })
        local_skin_server = None
        try:
            if version in ("latest-release", "latest-snapshot"):
                update_status("Resolving Minecraft version…")
                latest = minecraft_launcher_lib.utils.get_latest_version()
                version = latest["snapshot" if version == "latest-snapshot" else "release"]
            launch_id = version
            normalized_java_executable = self._normalize_java_executable_input(custom_java_executable)
            
            # --- Check for existing installations to avoid re-downloading ---
            installed_versions = [v['id'] for v in minecraft_launcher_lib.utils.get_installed_versions(self.minecraft_dir)]

            # Resolve Java for Installers (Fabric/Forge need Java to run their installer)
            java_install_path = normalized_java_executable or "java"
            if normalized_java_executable:
                self.log(f"Using custom Java executable: {normalized_java_executable}")
            else:
                try:
                    # 1. Try Library Utility (No args)
                    rt = minecraft_launcher_lib.utils.get_java_executable()
                    
                    if rt and os.path.exists(rt):
                        java_install_path = rt
                    elif shutil.which("java"):
                        java_install_path = shutil.which("java")
                    else:
                        # 2. Check Local Runtime Folder Manually
                        runtime_dir = os.path.join(self.minecraft_dir, "runtime")
                        local_java = None
                        if os.path.exists(runtime_dir):
                            for root, dirs, files in os.walk(runtime_dir):
                                if "java.exe" in files:
                                    local_java = os.path.join(root, "java.exe")
                                    break
                                elif "java" in files and sys.platform != "win32":
                                    local_java = os.path.join(root, "java")
                                    break
                        
                        if local_java:
                            java_install_path = local_java
                        else:
                            # 3. No Java found - Install Vanilla first to fetch Runtime
                            self.log("Java not found. Installing Vanilla version to fetch Runtime...")
                            try:
                                minecraft_launcher_lib.install.install_minecraft_version(version, self.minecraft_dir, callback=callback)
                                # Scan again
                                if os.path.exists(runtime_dir):
                                    for root, dirs, files in os.walk(runtime_dir):
                                        if "java.exe" in files:
                                            java_install_path = os.path.join(root, "java.exe")
                                            break
                                        elif "java" in files and sys.platform != "win32":
                                            java_install_path = os.path.join(root, "java")
                                            break
                            except Exception as e:
                                self.log(f"Failed to install vanilla runtime: {e}")
                                if "launchermeta.mojang.com" in str(e) or "getaddrinfo failed" in str(e):
                                    self.log("Network Error: Could not connect to Mojang. Check your internet.")

                            if java_install_path == "java" and not shutil.which("java"):
                                 self.log("Warning: Could not resolve setup Java. Fabric/Forge installation might fail.")
                except Exception as e:
                    self.log(f"Java resolution error: {e}")
            
            if force_update:
                self.log("Force Update enabled: Verifying and re-installing versions...")
            
            if loader == "Fabric":
                found_fabric = None
                if not force_update:
                    for vid in installed_versions:
                        if "fabric" in vid and version in vid.split('-') and self._version_metadata_is_valid(vid):
                             found_fabric = vid
                             break
                
                if found_fabric:
                    self.log(f"Using existing Fabric installation: {found_fabric}")
                    launch_id = found_fabric
                else:
                    self.log(f"Installing Fabric for {version}...")
                    result = minecraft_launcher_lib.fabric.install_fabric(version, self.minecraft_dir, callback=callback, java=java_install_path)
                    if result: launch_id = result
                    else:
                        loader_v = minecraft_launcher_lib.fabric.get_latest_loader_version()
                        launch_id = f"fabric-loader-{loader_v}-{version}"

            elif loader == "Forge":
                found_forge = None
                if not force_update:
                    for vid in installed_versions:
                        if "forge" in vid and version in vid.split('-') and self._version_metadata_is_valid(vid):
                            found_forge = vid
                            break
                        
                if found_forge:
                    self.log(f"Using existing Forge installation: {found_forge}")
                    launch_id = found_forge
                else:
                    self.log(f"Installing Forge for {version}...")
                    forge_v = minecraft_launcher_lib.forge.find_forge_version(version)
                    if forge_v:
                        minecraft_launcher_lib.forge.install_forge_version(forge_v, self.minecraft_dir, callback=callback, java=java_install_path)
                        launch_id = forge_v
            
            else:
                version_is_incomplete = (
                    version in installed_versions
                    and not self._version_metadata_is_valid(version)
                )
                if force_update or (
                    (version not in installed_versions and launch_id not in installed_versions)
                    or version_is_incomplete
                ):
                     self.log(f"Installing/Updating Vanilla version {version}...")
                     minecraft_launcher_lib.install.install_minecraft_version(version, self.minecraft_dir, callback=callback)

            # Determine Account & Injection Settings
            current_profile = self.profiles[self.current_profile_index] if (self.profiles and 0 <= self.current_profile_index < len(self.profiles)) else {"type": "offline", "skin_path": "", "uuid": ""}
            acct_type = current_profile.get("type", "offline")
            
            launch_uuid = ""
            launch_token = ""
            
            injector_path = None
            # Only use authlib-injector if requested (Ely.by or Offline+Injection)
            use_injection = False
            skin_server_url = ""

            if acct_type == "ely.by":
                # Ely.by Logic
                use_injection = True
                injector_path = self.ensure_authlib_injector()
                # Use the explicit API URL to avoid redirects/ambiguity
                skin_server_url = "https://authserver.ely.by/api/authlib-injector"
                launch_uuid = current_profile.get("uuid", "")
                launch_token = current_profile.get("token", "")
                self.log("Launching with Ely.by account...")

            elif acct_type == "microsoft":
                self.log("Validating Microsoft Session...")
                refresh_token = current_profile.get("refresh_token")
                if refresh_token:
                    try:
                         # Refresh
                         new_data = minecraft_launcher_lib.microsoft_account.complete_refresh(MSA_CLIENT_ID, None, MSA_REDIRECT_URI, refresh_token)
                         if "error" not in new_data:
                             # Update profile
                             current_profile["access_token"] = new_data["access_token"]
                             current_profile["refresh_token"] = new_data["refresh_token"]
                             current_profile["name"] = new_data["name"]
                             current_profile["uuid"] = new_data["id"]
                             self.save_config()
                             
                             username = new_data["name"]
                             launch_uuid = new_data["id"]
                             launch_token = new_data["access_token"]
                             self.log(f"Session refreshed for {username}")
                         else:
                             raise Exception(f"Session Expired: {new_data.get('error')}")
                    except Exception as e:
                         self.log(f"Token refresh error: {e}")
                         raise Exception("Failed to refresh Microsoft session. Please re-login.")
                else:
                    raise Exception("No refresh token found. Please re-login.")

            elif acct_type == "offline":
                # Offline Logic
                launch_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{username}"))
                self.log(f"Offline UUID: {launch_uuid}")
                
                if self.auto_download_mod: # This toggle now means "Enable Skin Injection"
                     skin_path = current_profile.get("skin_path") or self.skin_path
                     if skin_path and os.path.exists(skin_path):
                         use_injection = True
                         injector_path = self.ensure_authlib_injector()
                         
                         # Start Local Skin Server only when a real local skin exists.
                         try:
                             local_skin_server = LocalSkinServer(port=0)
                             skin_model = current_profile.get("skin_model", "classic")
                             skin_server_url = local_skin_server.start(skin_path, username, launch_uuid, skin_model)
                             self.log(f"Local Skin Server active at {skin_server_url}")
                         except Exception as e:
                             self.log(f"Failed to start local skin server: {e}")
                             use_injection = False
                     else:
                         self.log("Skin injection is enabled, but no local skin is selected. Launching without authlib-injector.")

            # Build Options
            jvm_args = [f"-Xmx{self.ram_allocation}M"]
            if self.java_args:
                jvm_args.extend(self.java_args.split())
            
            if use_injection and injector_path and skin_server_url:
                self.log(f"Applying authlib-injector: {injector_path}={skin_server_url}")
                jvm_args.append(f"-javaagent:{injector_path}={skin_server_url}")
                # Ensure we pass the prefab UUID/Token so authlib trusts it if we can
                # For offline local server, token can be anything usually, but validation might fail if not careful.
                # Authlib Injector usually disables signature checks.

            # --- INSTANCE & MODPACK ISOLATION ---
            target_game_dir = self.minecraft_dir
            if inst_id:
                pack = next((p for p in getattr(self, 'modpacks', []) if p.get('linked_installation_id') == inst_id), None)
                if pack:
                    pack_name = str(pack.get('name') or 'modpack')
                    update_status(f"Preparing {pack_name}…")
                    self.log(f"Preparing isolated instance for linked modpack: {pack_name}")
                    pack_dir = os.path.abspath(self.get_modpack_dir(pack['id']))
                    os.makedirs(pack_dir, exist_ok=True)
                    sync_instance_assets(pack_dir, self.minecraft_dir, getattr(self, 'instances_config', {}))
                    target_game_dir = pack_dir
                else:
                    inst_obj = next((i for i in self.installations if i.get('id') == inst_id), None)
                    if inst_obj and inst_obj.get('game_directory'):
                        custom_dir = os.path.abspath(os.path.expanduser(inst_obj['game_directory']))
                        os.makedirs(custom_dir, exist_ok=True)
                        sync_instance_assets(custom_dir, self.minecraft_dir, getattr(self, 'instances_config', {}))
                        target_game_dir = custom_dir

            options = {
                "username": username, 
                "uuid": launch_uuid, 
                "token": launch_token,
                "jvmArguments": jvm_args,
                "launcherName": "MinecraftLauncher",
                "gameDirectory": target_game_dir
            }

            if normalized_java_executable:
                options["executablePath"] = normalized_java_executable

            if resolution_width and resolution_height:
                options["customResolution"] = True
                options["resolutionWidth"] = str(resolution_width)
                options["resolutionHeight"] = str(resolution_height)

            if server_address:
                options["server"] = str(server_address)
                if server_port:
                    options["port"] = str(server_port)
            
            self.log(f"Generating command for: {launch_id} (gameDirectory: {target_game_dir})")
            command = minecraft_launcher_lib.command.get_minecraft_command(launch_id, self.minecraft_dir, options) # type: ignore
            
            self.root.after(0, self.root.withdraw)
            
            # RPC Logic
            rpc_details = "Playing Minecraft"
            if getattr(self, 'rpc_show_version', True):
                 rpc_details = f"Playing {version} ({loader})"
            if server_address:
                 rpc_details = f"Connecting to {server_address}"
            
            self.root.after(0, lambda: self.update_rpc("In Game", rpc_details, start=time.time()))
            
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NO_WINDOW

            process = subprocess.Popen(
                command, 
                cwd=target_game_dir,
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                encoding='utf-8',
                errors='replace',
                creationflags=creationflags
            )
            self.root.after(0, lambda: self.launch_btn.config(text="RUNNING") if hasattr(self, 'launch_btn') else None)
            session_started_at = time.time()
            
            if process.stdout:
                for line in process.stdout:
                    line_stripped = line.strip()
                    self.root.after(0, lambda l=line_stripped: self.log(f"[GAME] {l}"))
                    
                    if "Connecting to" in line_stripped and "," in line_stripped:
                         if getattr(self, 'rpc_show_server', True):
                            try:
                                parts = line_stripped.split("Connecting to")[-1].strip()
                                server_addr = parts.split(",")[0].strip()
                                if server_addr:
                                    self.root.after(0, lambda s=server_addr: self.update_rpc("In Game", f"Playing on {s}", start=time.time()))
                            except: pass

            process.wait()
            if inst_id:
                session_seconds = max(0, int(time.time() - session_started_at))
                self.root.after(0, lambda iid=inst_id, secs=session_seconds, srv=server_address, prt=server_port: self._record_play_session(iid, secs, srv, prt))
                self.root.after(0, lambda iid=inst_id, secs=session_seconds, srv=server_address: self._notify_game_session_ended(iid, secs, srv))
            self.root.after(0, self.root.deiconify)
            self.root.after(0, lambda: self.update_rpc("Idle", "In Launcher"))
        except Exception as e:
            self.log(f"Error: {e}")
            logging.exception("Launch failed")
            
            err_msg = str(e)
            if isinstance(e, KeyError) and e.args == ("value",):
                err_msg = "The selected version has malformed launch metadata.\nThe launcher skipped a broken launch entry, but this install may still need Force Update & Play."
            if "launchermeta.mojang.com" in err_msg or "getaddrinfo failed" in err_msg:
                 err_msg = "Network Error: Could not connect to Mojang servers.\nPlease check your internet connection."
            elif "SSL" in err_msg or "DECRYPTION_FAILED" in err_msg:
                 err_msg = "Network connection interrupted (SSL error).\nThis is usually a temporary hiccup or antivirus block.\n\nPlease try clicking PLAY again."
            
            self.root.after(0, lambda: custom_showerror("Launch Error", err_msg))
            self.root.after(0, lambda: self.update_rpc("Idle", "In Launcher"))
        finally:
            if local_skin_server:
                self.log("Stopping local skin server...")
                try: local_skin_server.stop()
                except: pass
                
            def reset_ui():
                self._launch_in_progress = False
                self.launch_btn.config(state="normal", text="PLAY")
                self.launch_opts_btn.config(state="normal")
                self.update_skin_indicator()
                self.hide_progress_overlay()
                
            self.root.after(0, reset_ui)

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()

    splash = tk.Toplevel(root)
