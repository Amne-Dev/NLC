"""
nlc.ui.screens.addons - Addons tab (playtime tracker, servers, screenshots, third-party addons, agent integration)
"""

import os
import sys
import time
import json
import uuid
import logging
import datetime
import subprocess
import threading
import hashlib
import webbrowser
import tkinter as tk
from tkinter import ttk, filedialog
from PIL import Image, ImageTk

from nlc.storage.paths import resource_path, open_path_in_system
from nlc.ui.theme import COLORS, FONT_FAMILY, derive_hover_color
from nlc.ui.components.dialogs import custom_showinfo, custom_showerror, custom_askyesno
from nlc.ui.components.context_menu import NeoContextMenu, attach_context_menu

def _get_streamer_hidden_name():
    return "Hidden Account"

try:
    from agent import (
        addon_add_saved_server,
        addon_delete_screenshot,
        addon_list_screenshot_files,
        addon_normalize_config,
        addon_record_play_session,
        addon_remove_saved_server,
        addon_reset_playtime_tracker,
        addon_set_streamer_mode,
    )
except ImportError:
    def addon_normalize_config(cfg): return cfg or {}
    def addon_add_saved_server(cfg, s): pass
    def addon_delete_screenshot(p): pass
    def addon_list_screenshot_files(p): return []
    def addon_record_play_session(*args): pass
    def addon_remove_saved_server(cfg, s): pass
    def addon_reset_playtime_tracker(cfg): pass
    def addon_set_streamer_mode(cfg, m): pass

logger = logging.getLogger(__name__)

class AddonsScreenMixin:
    """Mixin providing Addons and Agent integration screen."""
    def create_addons_tab(self):
        frame = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Addons"] = frame
        
        # Header
        header = tk.Frame(frame, bg=COLORS['main_bg'], pady=20, padx=30)
        header.pack(fill="x")
        self.addons_header_frame = header
        
        self.addons_title_lbl = tk.Label(header, text="Addons & Agent", font=("Segoe UI", 24, "bold"), bg=COLORS['main_bg'], fg=COLORS['text_primary'])
        self.addons_title_lbl.pack(side="left")

        # Scrollable Content
        canvas = tk.Canvas(frame, bg=COLORS['main_bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview, style="Launcher.Vertical.TScrollbar")
        scroll_frame = tk.Frame(canvas, bg=COLORS['main_bg'])
        
        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        
        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
            
        canvas.bind("<Configure>", on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Auto-hide scrollbar when not needed
        def update_scrollbar_visibility(*args):
            try:
                scroll_frame.update_idletasks()
                canvas.update_idletasks()
                content_height = scroll_frame.winfo_reqheight()
                canvas_height = canvas.winfo_height()
                
                if content_height > canvas_height:
                    scrollbar.pack(side="right", fill="y")
                else:
                    scrollbar.pack_forget()
            except:
                pass
        
        # Preserve the scrollregion updater when tracking scrollbar visibility;
        # replacing this binding made Addons appear to stop scrolling whenever
        # a collapsible card changed height.
        canvas.bind("<Configure>", lambda e: [on_canvas_configure(e), update_scrollbar_visibility()])
        scroll_frame.bind("<Configure>", lambda e: update_scrollbar_visibility(), add="+")

        self.addons_canvas = canvas
        self.addons_scroll_frame = scroll_frame
        self._addons_update_scrollbar_visibility = update_scrollbar_visibility

        # Smooth mousewheel
        self._bind_wheel_events(canvas, lambda e, c=canvas: self._smooth_scroll(c, e), f"direct_{id(canvas)}")

        # Keep wheel scrolling active anywhere over the Addons page content.
        for bind_target in (frame, canvas, scroll_frame):
            bind_target.bind("<Enter>", lambda e, c=canvas, sf=scroll_frame: self._bind_smooth_scroll(c, sf))
        
        # --- content ---
        content = tk.Frame(scroll_frame, bg=COLORS['main_bg'], padx=30, pady=10)
        content.pack(fill="x")
        content.bind("<Enter>", lambda e, c=canvas, ct=content: self._bind_smooth_scroll(c, ct))
        self.addons_content_frame = content

        if not hasattr(self, '_addons_collapsible_state'):
            self._addons_collapsible_state = {}

        def create_collapsible_card(parent, title, subtitle, state_key, default_open=True, title_badge_text=None, title_badge_fg=None):
            card = tk.Frame(parent, bg=COLORS['card_bg'], padx=20, pady=20)
            card.pack(fill="x", pady=(0, 20))

            is_open = bool(self._addons_collapsible_state.get(state_key, default_open))
            body = tk.Frame(card, bg=COLORS['card_bg'])
            icon_font = ("Segoe UI Symbol", 13, "bold")
            icon_open = "⌄"
            icon_closed = "›"

            header = tk.Frame(card, bg=COLORS['card_bg'], cursor="hand2")
            header.pack(fill="x")

            text_wrap = tk.Frame(header, bg=COLORS['card_bg'])
            text_wrap.pack(side="left", fill="x", expand=True)

            icon_wrap = tk.Frame(header, bg=COLORS['card_bg'])
            icon_wrap.pack(side="right", anchor="ne")
            chevron = tk.Label(
                icon_wrap,
                text=icon_open if is_open else icon_closed,
                font=icon_font,
                bg=COLORS['card_bg'],
                fg=COLORS['text_primary'],
                cursor="hand2",
                anchor="ne",
            )
            chevron.pack(anchor="ne")

            title_row = tk.Frame(text_wrap, bg=COLORS['card_bg'])
            title_row.pack(anchor="w", fill="x")
            title_lbl = tk.Label(title_row, text=title, font=("Segoe UI", 16, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_primary'], anchor="w", cursor="hand2")
            title_lbl.pack(side="left", anchor="w")
            badge_lbl = None
            if title_badge_text:
                badge_lbl = tk.Label(
                    title_row,
                    text=title_badge_text,
                    font=("Segoe UI", 15, "bold"),
                    bg=COLORS['card_bg'],
                    fg=title_badge_fg or COLORS['accent_blue'],
                    anchor="w",
                    cursor="hand2",
                )
                badge_lbl.pack(side="left", padx=(8, 0), anchor="w")
            subtitle_lbl = tk.Label(text_wrap, text=subtitle, font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary'], anchor="w", cursor="hand2")
            subtitle_lbl.pack(anchor="w", pady=(4, 0))

            def toggle_section(_event=None):
                is_now_open = not bool(self._addons_collapsible_state.get(state_key, default_open))
                self._addons_collapsible_state[state_key] = is_now_open
                chevron.config(text=icon_open if is_now_open else icon_closed)
                if is_now_open:
                    body.pack(fill="x", pady=(15, 0))
                else:
                    body.pack_forget()

            bind_widgets = [header, text_wrap, title_row, icon_wrap, title_lbl, subtitle_lbl, chevron]
            if badge_lbl is not None:
                bind_widgets.append(badge_lbl)
            for widget in bind_widgets:
                widget.bind("<Button-1>", toggle_section)

            if is_open:
                body.pack(fill="x", pady=(15, 0))

            return card, body

        self._addons_create_collapsible_card = create_collapsible_card

        # Playtime Tracker
        playtime_frame = tk.Frame(content, bg=COLORS['card_bg'], padx=20, pady=20)
        playtime_frame.pack(fill="x", pady=(0, 20))
        tk.Label(playtime_frame, text="Playtime Tracker", font=("Segoe UI", 16, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_primary']).pack(anchor="w", pady=(0, 5))
        tk.Label(playtime_frame, text="Tracks session time and launch counts for each installation.", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")

        playtime_summary = tk.Frame(playtime_frame, bg=COLORS['card_bg'])
        playtime_summary.pack(fill="x", pady=(15, 12))
        self.playtime_total_lbl = tk.Label(playtime_summary, text="Total Time: 0m", font=("Segoe UI", 11, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_primary'])
        self.playtime_total_lbl.pack(side="left")
        self.playtime_launches_lbl = tk.Label(playtime_summary, text="Launches: 0", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary'])
        self.playtime_launches_lbl.pack(side="left", padx=(18, 0))
        self._make_btn(playtime_summary, "Reset Stats", style="secondary", font_size=9, command=self.reset_playtime_tracker).pack(side="right")

        self.playtime_list_frame = tk.Frame(playtime_frame, bg=COLORS['card_bg'])
        self.playtime_list_frame.pack(fill="x")

        # GitHub Skin Sync
        _sync_card, sync_frame = create_collapsible_card(
            content,
            "GitHub Skin Sync",
            "Link a GitHub repository to sync skins with your friends.",
            "github_skin_sync",
            default_open=False,
        )

        # Enable Toggle
        self.gh_sync_enabled = tk.BooleanVar(value=self.addons_config.get("gh_sync_enabled", False))
        tk.Checkbutton(sync_frame, text="Enable Skin Sync", variable=self.gh_sync_enabled,
                      bg=COLORS['card_bg'], fg=COLORS['text_primary'],
                      selectcolor=COLORS['card_bg'], activebackground=COLORS['card_bg'],
                      command=self._save_addons_config).pack(anchor="w", pady=(0, 15))

        # Inputs Grid
        grid_frame = tk.Frame(sync_frame, bg=COLORS['card_bg'])
        grid_frame.pack(fill="x")
        grid_frame.columnconfigure(1, weight=1)

        # Repo
        tk.Label(grid_frame, text="Repository (user/repo):", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).grid(row=0, column=0, sticky="w", pady=5)
        self.gh_repo_entry = tk.Entry(grid_frame, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg="white", relief="flat")
        self.gh_repo_entry.grid(row=0, column=1, sticky="ew", padx=10, ipady=5)

        # Token
        tk.Label(grid_frame, text="Access Token (PAT):", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).grid(row=1, column=0, sticky="w", pady=5)
        self.gh_token_entry = tk.Entry(grid_frame, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg="white", relief="flat", show="*")
        self.gh_token_entry.grid(row=1, column=1, sticky="ew", padx=10, ipady=5)
        
        # Save Button
        save_sync_btn = self._make_btn(sync_frame, "Save & Sync", style="secondary", font_size=10,
                                       command=self._save_gh_sync_settings)
        accent_blue = COLORS.get('accent_blue', '#3498DB')
        hover_blue = derive_hover_color(accent_blue)
        save_sync_btn.config(bg=accent_blue, activebackground=hover_blue)
        save_sync_btn.bind("<Enter>", lambda e: save_sync_btn.config(bg=hover_blue))
        save_sync_btn.bind("<Leave>", lambda e: save_sync_btn.config(bg=accent_blue))
        save_sync_btn.pack(anchor="w", pady=(20, 0))

        # Streamer Mode
        _streamer_card, streamer_frame = create_collapsible_card(
            content,
            "Streamer Mode",
            "Hide your account name across launcher-controlled surfaces while keeping the real server username.",
            "streamer_mode",
            default_open=False,
        )

        self.streamer_mode_var = tk.BooleanVar(value=bool(self.addons_config.get("streamer_mode_enabled", False)))
        tk.Checkbutton(
            streamer_frame,
            text="Hide my username locally in the launcher and game-adjacent overlays",
            variable=self.streamer_mode_var,
            bg=COLORS['card_bg'],
            fg=COLORS['text_primary'],
            selectcolor=COLORS['card_bg'],
            activebackground=COLORS['card_bg'],
            command=self._save_streamer_mode_settings,
        ).pack(anchor="w")
        tk.Label(
            streamer_frame,
            text="This masks launcher UI, local logs, and Discord/status surfaces we control. Your real username is still used for launches and servers.",
            font=("Segoe UI", 9),
            bg=COLORS['card_bg'],
            fg=COLORS['text_secondary'],
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        # Server Quick Join
        _server_card, server_frame = create_collapsible_card(
            content,
            "Server Quick Join",
            "Save favorite servers and launch directly into them.",
            "server_quick_join",
            default_open=True,
        )

        install_row = tk.Frame(server_frame, bg=COLORS['card_bg'])
        install_row.pack(fill="x", pady=(0, 12))
        tk.Label(install_row, text="Installation", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(side="left")
        self.quick_join_install_var = tk.StringVar()
        self.quick_join_install_combo = ttk.Combobox(install_row, textvariable=self.quick_join_install_var, state="readonly", style="Launcher.TCombobox", width=36)
        self.quick_join_install_combo.pack(side="left", padx=(10, 0), fill="x", expand=True)

        server_form = tk.Frame(server_frame, bg=COLORS['card_bg'])
        server_form.pack(fill="x")
        server_form.columnconfigure(1, weight=1)

        self.quick_join_name_var = tk.StringVar()
        self.quick_join_address_var = tk.StringVar()
        self.quick_join_port_var = tk.StringVar(value="25565")

        tk.Label(server_form, text="Name", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).grid(row=0, column=0, sticky="w", pady=5)
        tk.Entry(server_form, textvariable=self.quick_join_name_var, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg="white", relief="flat").grid(row=0, column=1, sticky="ew", ipady=5)
        tk.Label(server_form, text="Address", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).grid(row=1, column=0, sticky="w", pady=5)
        tk.Entry(server_form, textvariable=self.quick_join_address_var, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg="white", relief="flat").grid(row=1, column=1, sticky="ew", ipady=5)
        tk.Label(server_form, text="Port", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).grid(row=2, column=0, sticky="w", pady=5)
        tk.Entry(server_form, textvariable=self.quick_join_port_var, font=("Segoe UI", 10), bg=COLORS['input_bg'], fg="white", relief="flat", width=12).grid(row=2, column=1, sticky="w", ipady=5)

        self._make_btn(server_frame, "Save Server", style="primary", font_size=10, bold=True, command=self.add_quick_join_server).pack(anchor="w", pady=(14, 0))
        self.saved_servers_list_frame = tk.Frame(server_frame, bg=COLORS['card_bg'])
        self.saved_servers_list_frame.pack(fill="x", pady=(14, 0))

        # Screenshot Browser (Shortcut to dedicated gallery tab)
        _screenshot_card, screenshot_frame = create_collapsible_card(
            content,
            "Screenshot Browser",
            "Browse and manage recent screenshots from your Minecraft directory in full gallery mode.",
            "screenshot_browser",
            default_open=False,
        )

        screenshot_actions = tk.Frame(screenshot_frame, bg=COLORS['card_bg'])
        screenshot_actions.pack(fill="x", pady=(0, 6))
        self.screenshot_status_lbl = tk.Label(
            screenshot_actions,
            text="Screenshots have moved to the sidebar for full-screen gallery browsing.",
            font=("Segoe UI", 9),
            bg=COLORS['card_bg'],
            fg=COLORS['text_secondary'],
        )
        self.screenshot_status_lbl.pack(side="left")
        self._make_btn(
            screenshot_actions,
            "Open Gallery",
            style="primary",
            font_size=9,
            command=lambda: self.show_tab("Screenshots") if hasattr(self, 'show_tab') else None,
        ).pack(side="right")
        self._make_btn(
            screenshot_actions,
            "Open Folder",
            style="secondary",
            font_size=9,
            command=lambda: self._open_path(self.get_screenshots_dir()),
        ).pack(side="right", padx=(0, 8))

        self.screenshot_grid_frame = tk.Frame(screenshot_frame, bg=COLORS['card_bg'])
        self.screenshot_grid_frame.pack(fill="x")

        third_party_top = tk.Frame(content, bg=COLORS['main_bg'])
        third_party_top.pack(fill="x", pady=(0, 8))
        self.third_party_addons_status_lbl = tk.Label(
            third_party_top,
            text="",
            font=("Segoe UI", 9),
            bg=COLORS['main_bg'],
            fg=COLORS['text_secondary'],
        )
        self.third_party_addons_status_lbl.pack(side="left")
        self._make_btn(
            third_party_top,
            "Refresh",
            style="secondary",
            font_size=9,
            command=self.refresh_third_party_addons,
        ).pack(side="right")
        self._make_btn(
            third_party_top,
            "Open Folder",
            style="secondary",
            font_size=9,
            command=self.open_third_party_addons_folder,
        ).pack(side="right", padx=(0, 8))

        self.third_party_addons_path_lbl = tk.Label(
            content,
            text="",
            font=("Consolas", 8),
            bg=COLORS['main_bg'],
            fg=COLORS['text_secondary'],
            anchor="w",
            justify="left",
            wraplength=760,
        )
        self.third_party_addons_path_lbl.pack(fill="x", pady=(0, 12))

        self.third_party_addons_cards_frame = tk.Frame(content, bg=COLORS['main_bg'])
        self.third_party_addons_cards_frame.pack(fill="x")

        # Instructions
        info_frame = tk.Frame(content, bg=COLORS['main_bg'], pady=10)
        info_frame.pack(fill="x")
        
        info_text = """
How to use:
1. Create a public or private GitHub repository.
2. Generate a Personal Access Token (PAT) with 'repo' scope.
3. Enter the repository name (e.g., 'MyName/Skins') and token in the GitHub Skin Sync card.
4. Enable the feature. The launcher will upload your current skin to the repo and download friends' skins automatically.
        """
        tk.Label(info_frame, text=info_text, font=("Segoe UI", 9), justify="left", bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(anchor="w")

        self._bind_smooth_scroll(canvas, scroll_frame)
        self._bind_smooth_scroll(canvas, content)
        update_scrollbar_visibility()
        self.refresh_addons_tab_state()

        if getattr(self, "current_tab", None) == "Addons":
            frame.pack(fill="both", expand=True)

    def _ensure_addons_config_defaults(self):
        self.addons_config = addon_normalize_config(getattr(self, "addons_config", {}))

    def _refresh_addons_scroll_bindings(self):
        canvas = getattr(self, "addons_canvas", None)
        scroll_frame = getattr(self, "addons_scroll_frame", None)
        content = getattr(self, "addons_content_frame", None)
        if not canvas or not scroll_frame or not content:
            return

        try:
            self._bind_wheel_events(canvas, lambda e, c=canvas: self._smooth_scroll(c, e), f"direct_{id(canvas)}")
            self._bind_smooth_scroll(canvas, scroll_frame)
            self._bind_smooth_scroll(canvas, content)
            update_scrollbar_visibility = getattr(self, "_addons_update_scrollbar_visibility", None)
            if callable(update_scrollbar_visibility):
                update_scrollbar_visibility()
        except Exception:
            pass

    def _get_installation_display_label(self, inst):
        return f"{inst.get('name', 'Unnamed')} • {inst.get('loader', 'Vanilla')} {inst.get('version', 'latest-release')}"

    def _is_streamer_mode_enabled(self):
        return bool(getattr(self, "addons_config", {}).get("streamer_mode_enabled", False))

    def _get_streamer_safe_name(self, name=None):
        if not self._is_streamer_mode_enabled():
            return str(name or "Steve")
        return _get_streamer_hidden_name()

    def _mask_streamer_text(self, text):
        if not self._is_streamer_mode_enabled():
            return text
        masked_text = str(text)
        for profile in getattr(self, "profiles", []):
            name = str(profile.get("name", "")).strip()
            if name:
                masked_text = masked_text.replace(name, _get_streamer_hidden_name())
        return masked_text

    def _apply_streamer_mode_ui(self):
        try:
            if hasattr(self, 'user_entry') and self.user_entry.winfo_exists():
                self.user_entry.config(show="*" if self._is_streamer_mode_enabled() else "")
        except Exception:
            pass

        try:
            self.update_profile_btn()
        except Exception:
            pass

        try:
            if hasattr(self, 'update_bottom_gamertag'):
                self.update_bottom_gamertag()
        except Exception:
            pass

        try:
            if hasattr(self, 'profile_menu') and self.profile_menu and self.profile_menu.winfo_exists():
                self.profile_menu.destroy()
                self.profile_menu = None
        except Exception:
            pass

        try:
            if getattr(self, "rpc_connected", False) and getattr(self, "rpc", None):
                self.update_rpc(
                    getattr(self, "_last_rpc_state", "Idle"),
                    getattr(self, "_last_rpc_details", "In Launcher"),
                    getattr(self, "_last_rpc_start", None),
                )
        except Exception:
            pass

    def _save_streamer_mode_settings(self):
        self._ensure_addons_config_defaults()
        enabled = bool(self.streamer_mode_var.get()) if hasattr(self, 'streamer_mode_var') else False
        self.addons_config = addon_set_streamer_mode(self.addons_config, enabled)
        self._apply_streamer_mode_ui()
        self.save_config(sync_ui=False)

    def _refresh_quick_join_installation_values(self):
        if not hasattr(self, 'quick_join_install_combo'):
            return
        labels = {}
        values = []
        for idx, inst in enumerate(self.installations):
            label = self._get_installation_display_label(inst)
            values.append(label)
            labels[label] = idx
        self.quick_join_installation_labels = labels
        self.quick_join_install_combo.config(values=values, state="readonly" if values else "disabled")

        selected = self.quick_join_install_var.get() if hasattr(self, 'quick_join_install_var') else ""
        if selected in labels:
            return

        fallback = ""
        current_idx = getattr(self, 'current_installation_index', 0)
        if 0 <= current_idx < len(values):
            fallback = values[current_idx]
        elif values:
            fallback = values[0]
        self.quick_join_install_var.set(fallback)

    def _format_duration(self, total_seconds):
        total_seconds = max(0, int(total_seconds))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _seconds = divmod(remainder, 60)
        if hours and minutes:
            return f"{hours}h {minutes}m"
        if hours:
            return f"{hours}h"
        return f"{minutes}m"

    def _format_timestamp_short(self, iso_value):
        if not iso_value:
            return "Never"
        try:
            return datetime.datetime.fromisoformat(str(iso_value)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(iso_value)

    def render_playtime_tracker(self):
        if not hasattr(self, 'playtime_list_frame'):
            return

        self._ensure_addons_config_defaults()
        for widget in self.playtime_list_frame.winfo_children():
            widget.destroy()

        tracker = self.addons_config.get("playtime_tracker", {})
        total_seconds = 0
        total_launches = 0
        entries = []
        installations_by_id = {
            inst.get("id"): inst for inst in self.installations if inst.get("id")
        }

        for inst_id, stats in tracker.items():
            if not isinstance(stats, dict):
                continue
            seconds = int(stats.get("seconds", 0) or 0)
            launches = int(stats.get("launches", 0) or 0)
            total_seconds += seconds
            total_launches += launches
            inst = installations_by_id.get(inst_id, {"name": "Unknown Installation", "loader": "-", "version": "-"})
            entries.append((inst_id, inst, stats, seconds, launches))

        self.playtime_total_lbl.config(text=f"Total Time: {self._format_duration(total_seconds)}")
        self.playtime_launches_lbl.config(text=f"Launches: {total_launches}")

        if not entries:
            tk.Label(self.playtime_list_frame, text="No tracked play sessions yet. Launch a game to start collecting stats.", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
            self._refresh_addons_scroll_bindings()
            return

        entries.sort(key=lambda item: item[3], reverse=True)
        for _inst_id, inst, stats, seconds, launches in entries:
            row = tk.Frame(self.playtime_list_frame, bg=COLORS['card_bg'], pady=8)
            row.pack(fill="x")
            left = tk.Frame(row, bg=COLORS['card_bg'])
            left.pack(side="left", fill="x", expand=True)
            tk.Label(left, text=inst.get("name", "Unknown Installation"), font=("Segoe UI", 10, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_primary']).pack(anchor="w")
            tk.Label(left, text=f"{inst.get('loader', 'Vanilla')} {inst.get('version', 'latest-release')}  •  Last Played: {self._format_timestamp_short(stats.get('last_played_at'))}", font=("Segoe UI", 9), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")

            right = tk.Frame(row, bg=COLORS['card_bg'])
            right.pack(side="right")
            tk.Label(right, text=self._format_duration(seconds), font=("Segoe UI", 10, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_primary']).pack(anchor="e")
            tk.Label(right, text=f"{launches} launches", font=("Segoe UI", 9), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="e")

        self._refresh_addons_scroll_bindings()

    def reset_playtime_tracker(self):
        if not custom_askyesno("Reset Playtime", "Clear all tracked playtime and launch counts?", parent=self.root):
            return
        self._ensure_addons_config_defaults()
        self.addons_config = addon_reset_playtime_tracker(self.addons_config)
        self.save_config(sync_ui=False)
        self.render_playtime_tracker()

    def _record_play_session(self, inst_id, session_seconds, server_address=None, server_port=None):
        if not inst_id:
            return
        self._ensure_addons_config_defaults()
        self.addons_config = addon_record_play_session(
            self.addons_config,
            inst_id,
            session_seconds,
            server_address=server_address,
            server_port=server_port,
        )

        for inst in self.installations:
            if inst.get("id") == inst_id:
                inst["last_played"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                break

        self.save_config(sync_ui=False)
        self.render_playtime_tracker()

    def add_quick_join_server(self):
        self._ensure_addons_config_defaults()
        name = self.quick_join_name_var.get().strip() if hasattr(self, 'quick_join_name_var') else ""
        address = self.quick_join_address_var.get().strip() if hasattr(self, 'quick_join_address_var') else ""
        port = self.quick_join_port_var.get().strip() if hasattr(self, 'quick_join_port_var') else "25565"

        try:
            self.addons_config = addon_add_saved_server(self.addons_config, name, address, port)
        except ValueError as e:
            title = "Missing Address" if "address" in str(e).lower() else "Invalid Port"
            custom_showerror(title, str(e), parent=self.root)
            return

        self.quick_join_name_var.set("")
        self.quick_join_address_var.set("")
        self.quick_join_port_var.set("25565")
        self.save_config(sync_ui=False)
        self.render_quick_join_servers()

    def remove_quick_join_server(self, server_id):
        self._ensure_addons_config_defaults()
        self.addons_config = addon_remove_saved_server(self.addons_config, server_id)
        self.save_config(sync_ui=False)
        self.render_quick_join_servers()

    def launch_saved_server(self, server_data):
        if not self.installations:
            custom_showerror("No Installation", "Create an installation before using Quick Join.", parent=self.root)
            return

        self._refresh_quick_join_installation_values()
        selected_label = self.quick_join_install_var.get() if hasattr(self, 'quick_join_install_var') else ""
        install_idx = self.quick_join_installation_labels.get(selected_label, getattr(self, 'current_installation_index', 0))
        if install_idx is None or not (0 <= install_idx < len(self.installations)):
            custom_showerror("Invalid Installation", "Select a valid installation for Quick Join.", parent=self.root)
            return

        self.launch_installation(
            install_idx,
            server_address=str(server_data.get("address", "")).strip(),
            server_port=server_data.get("port"),
        )

    def render_quick_join_servers(self):
        if not hasattr(self, 'saved_servers_list_frame'):
            return

        self._ensure_addons_config_defaults()
        for widget in self.saved_servers_list_frame.winfo_children():
            widget.destroy()

        saved_servers = self.addons_config.get("saved_servers", [])
        if not saved_servers:
            tk.Label(self.saved_servers_list_frame, text="No saved servers yet.", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
            self._refresh_addons_scroll_bindings()
            return

        for server in saved_servers:
            row = tk.Frame(self.saved_servers_list_frame, bg=COLORS['card_bg'], pady=8)
            row.pack(fill="x")
            info = tk.Frame(row, bg=COLORS['card_bg'])
            info.pack(side="left", fill="x", expand=True)
            port = server.get("port", 25565)
            tk.Label(info, text=server.get("name", "Unnamed Server"), font=("Segoe UI", 10, "bold"), bg=COLORS['card_bg'], fg=COLORS['text_primary']).pack(anchor="w")
            tk.Label(info, text=f"{server.get('address', '')}:{port}", font=("Segoe UI", 9), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")

            btns = tk.Frame(row, bg=COLORS['card_bg'])
            btns.pack(side="right")
            self._make_btn(btns, "Join", style="primary", font_size=9, bold=True, command=lambda s=server: self.launch_saved_server(s)).pack(side="left", padx=(0, 6))
            self._make_btn(btns, "Delete", style="secondary", font_size=9, command=lambda sid=server.get("id"): self.remove_quick_join_server(sid)).pack(side="left")

        self._refresh_addons_scroll_bindings()

    def get_screenshots_dir(self):
        return os.path.join(self.minecraft_dir, "screenshots")

    def get_third_party_addons_dir(self):
        addons_dir = os.path.join(self.config_dir, "addons")
        try:
            os.makedirs(addons_dir, exist_ok=True)
        except Exception:
            pass
        return addons_dir

    def open_third_party_addons_folder(self):
        self._open_path(self.get_third_party_addons_dir())

    def refresh_third_party_addons(self):
        if not hasattr(self, 'third_party_addons_cards_frame'):
            return

        addons_dir = self.get_third_party_addons_dir()
        if hasattr(self, 'third_party_addons_path_lbl'):
            self.third_party_addons_path_lbl.config(text=f"Folder: {addons_dir}")
        if hasattr(self, 'third_party_addons_status_lbl'):
            self.third_party_addons_status_lbl.config(text="Scanning third-party addons...")
        self._show_skeleton_list(self.third_party_addons_cards_frame, rows=2, card_height=82, padx=0, pady=6)
        self._refresh_addons_scroll_bindings()

        payload = {
            "minecraft_dir": self.minecraft_dir,
        }
        self.send_agent_request("list_third_party_addons", payload, self._on_third_party_addons_loaded)

    def _on_third_party_addons_loaded(self, result):
        if not isinstance(result, dict):
            if hasattr(self, 'third_party_addons_status_lbl'):
                self.third_party_addons_status_lbl.config(text="Failed to load third-party addons.")
            return

        if result.get("status") != "success":
            if hasattr(self, 'third_party_addons_status_lbl'):
                self.third_party_addons_status_lbl.config(text=str(result.get("msg", "Failed to load third-party addons.")))
            self.third_party_addons = []
            self.render_third_party_addons()
            return

        data = result.get("data", {})
        if isinstance(data, dict):
            self.third_party_addons = data.get("addons", []) if isinstance(data.get("addons"), list) else []
            if hasattr(self, 'third_party_addons_path_lbl'):
                self.third_party_addons_path_lbl.config(text=f"Folder: {data.get('addons_dir', self.get_third_party_addons_dir())}")
        else:
            self.third_party_addons = []

        addon_count = len(self.third_party_addons)
        if hasattr(self, 'third_party_addons_status_lbl'):
            self.third_party_addons_status_lbl.config(text=f"{addon_count} addon{'s' if addon_count != 1 else ''} detected.")
        self.render_third_party_addons()

    def _coerce_third_party_addon_input(self, input_type, var):
        if input_type == "checkbox":
            return bool(var.get())
        if input_type == "number":
            raw = str(var.get()).strip()
            if not raw:
                return ""
            try:
                if "." in raw:
                    return float(raw)
                return int(raw)
            except Exception:
                return raw
        return str(var.get())

    def run_third_party_addon_action(self, addon_data, action_data):
        addon_id = str(addon_data.get("id", "")).strip()
        action_id = str(action_data.get("id", "")).strip()
        if not addon_id or not action_id:
            return

        inputs = {}
        input_map = self.third_party_addon_input_vars.get((addon_id, action_id), {})
        for input_id, data in input_map.items():
            inputs[input_id] = self._coerce_third_party_addon_input(data.get("type"), data.get("var"))

        if hasattr(self, 'third_party_addons_status_lbl'):
            self.third_party_addons_status_lbl.config(text=f"Running {addon_data.get('name', addon_id)}...")

        payload = {
            "addon_id": addon_id,
            "action_id": action_id,
            "inputs": inputs,
            "minecraft_dir": self.minecraft_dir,
        }
        self.send_agent_request(
            "run_third_party_addon_action",
            payload,
            lambda result, addon=addon_data, action=action_data: self._on_third_party_addon_action_result(addon, action, result),
        )

    def _on_third_party_addon_action_result(self, addon_data, action_data, result):
        addon_name = str(addon_data.get("name", addon_data.get("id", "Addon")))
        action_label = str(action_data.get("label", action_data.get("id", "Action")))

        if not isinstance(result, dict):
            custom_showerror("Addon Error", f"{addon_name} returned an invalid response.")
            return

        status = result.get("status")
        message = str(result.get("msg", "") or "")
        extra_data = result.get("data", {})

        if hasattr(self, 'third_party_addons_status_lbl'):
            if status == "success":
                self.third_party_addons_status_lbl.config(text=f"{addon_name}: {message or 'Completed successfully.'}")
            else:
                self.third_party_addons_status_lbl.config(text=f"{addon_name}: {message or 'Action failed.'}")

        if isinstance(extra_data, dict):
            open_path = extra_data.get("open_path")
            open_url = extra_data.get("open_url")
            if open_path:
                self._open_path(str(open_path))
            if open_url:
                webbrowser.open(str(open_url))
            if extra_data.get("refresh_addons"):
                self.refresh_third_party_addons()

        if status == "success":
            if message:
                custom_showinfo(f"{addon_name} - {action_label}", message, parent=self.root)
        else:
            custom_showerror(f"{addon_name} - {action_label}", message or "Action failed.", parent=self.root)

    def render_third_party_addons(self):
        if not hasattr(self, 'third_party_addons_cards_frame'):
            return

        for widget in self.third_party_addons_cards_frame.winfo_children():
            widget.destroy()
        self.third_party_addon_input_vars = {}

        addons = self.third_party_addons if isinstance(self.third_party_addons, list) else []
        if not addons:
            tk.Label(
                self.third_party_addons_cards_frame,
                text="No third-party addons found yet. Drop addon folders here and click Refresh.",
                font=("Segoe UI", 10),
                bg=COLORS['main_bg'],
                fg=COLORS['text_secondary'],
                justify="left",
                wraplength=760,
            ).pack(anchor="w")
            self._refresh_addons_scroll_bindings()
            return

        create_card = getattr(self, "_addons_create_collapsible_card", None)
        if not callable(create_card):
            return

        for addon in addons:
            addon_name = str(addon.get("name", addon.get("id", "Addon")))
            addon_version = str(addon.get("version", "0.0.0"))
            addon_id = str(addon.get("id", addon_name)).strip() or addon_name
            card, body = create_card(
                self.third_party_addons_cards_frame,
                addon_name,
                str(addon.get("description", "Third-party addon")),
                f"third_party_addon::{addon_id}",
                default_open=False,
                title_badge_text="+",
                title_badge_fg=COLORS['accent_blue'],
            )

            meta_text = f"By {addon.get('author', 'Unknown')}"
            tk.Label(
                body,
                text=f"{meta_text}  •  v{addon_version}",
                font=("Segoe UI", 9),
                bg=COLORS['card_bg'],
                fg=COLORS['text_secondary'],
                anchor="w",
            ).pack(fill="x")

            if addon.get("load_error"):
                tk.Label(
                    body,
                    text=f"Load Error:\n{addon.get('load_error')}",
                    font=("Consolas", 8),
                    bg=COLORS['card_bg'],
                    fg=COLORS['error_red'],
                    justify="left",
                    wraplength=740,
                    anchor="w",
                ).pack(fill="x", pady=(10, 0))
                continue

            actions = addon.get("actions", [])
            if not isinstance(actions, list) or not actions:
                tk.Label(
                    body,
                    text="This addon does not expose any launcher actions.",
                    font=("Segoe UI", 9),
                    bg=COLORS['card_bg'],
                    fg=COLORS['text_secondary'],
                    anchor="w",
                ).pack(fill="x", pady=(10, 0))
                continue

            for action in actions:
                action_frame = tk.Frame(body, bg=COLORS['card_bg'])
                action_frame.pack(fill="x", pady=(10, 0))

                tk.Label(
                    action_frame,
                    text=str(action.get("label", action.get("id", "Action"))),
                    font=("Segoe UI", 9, "bold"),
                    bg=COLORS['card_bg'],
                    fg=COLORS['text_primary'],
                    anchor="w",
                ).pack(fill="x")

                if action.get("description"):
                    tk.Label(
                        action_frame,
                        text=str(action.get("description", "")),
                        font=("Segoe UI", 8),
                        bg=COLORS['card_bg'],
                        fg=COLORS['text_secondary'],
                        justify="left",
                        wraplength=720,
                        anchor="w",
                    ).pack(fill="x", pady=(2, 6))

                action_inputs = {}
                for input_spec in action.get("inputs", []) or []:
                    input_id = str(input_spec.get("id", "")).strip()
                    input_type = str(input_spec.get("type", "text")).strip().lower()
                    label = str(input_spec.get("label", input_id))

                    if input_type == "checkbox":
                        var = tk.BooleanVar(value=bool(input_spec.get("default", False)))
                        tk.Checkbutton(
                            action_frame,
                            text=label,
                            variable=var,
                            bg=COLORS['card_bg'],
                            fg=COLORS['text_primary'],
                            selectcolor=COLORS['card_bg'],
                            activebackground=COLORS['card_bg'],
                        ).pack(anchor="w", pady=(2, 4))
                    else:
                        tk.Label(
                            action_frame,
                            text=label,
                            font=("Segoe UI", 8),
                            bg=COLORS['card_bg'],
                            fg=COLORS['text_secondary'],
                            anchor="w",
                        ).pack(fill="x")
                        var = tk.StringVar(value=str(input_spec.get("default", "")))
                        entry = tk.Entry(
                            action_frame,
                            textvariable=var,
                            font=("Segoe UI", 9),
                            bg=COLORS['input_bg'],
                            fg="white",
                            relief="flat",
                            insertbackground="white",
                            show="*" if input_type == "password" else "",
                        )
                        entry.pack(fill="x", ipady=5, pady=(2, 6))

                    action_inputs[input_id] = {"type": input_type, "var": var}

                self.third_party_addon_input_vars[(str(addon.get("id", "")), str(action.get("id", "")))] = action_inputs
                self._make_btn(
                    action_frame,
                    str(action.get("label", "Run")),
                    style=str(action.get("style", "secondary")),
                    font_size=9,
                    bold=True,
                    command=lambda addon_data=addon, action_data=action: self.run_third_party_addon_action(addon_data, action_data),
                ).pack(anchor="w", pady=(2, 0))

        self._refresh_addons_scroll_bindings()

    def _open_path(self, path):
        try:
            open_path_in_system(path)
        except Exception as e:
            custom_showerror("Open Failed", f"Could not open:\n{path}\n\n{e}", parent=self.root)

    def _list_screenshot_files(self):
        return addon_list_screenshot_files(self.minecraft_dir).get("items", [])

    def _get_screenshot_thumbnail(self, path, size=(170, 96)):
        try:
            if not hasattr(self, 'screenshot_thumbnail_cache'):
                self.screenshot_thumbnail_cache = {}
            mtime = os.path.getmtime(path)
            cache_key = (path, mtime, size)
            if cache_key in self.screenshot_thumbnail_cache:
                return self.screenshot_thumbnail_cache[cache_key]

            # Persistent disk cache check
            cache_dir = os.path.join(getattr(self, 'config_dir', None) or os.path.expanduser('~/.nlc'), 'cache', 'screenshot_thumbs')
            os.makedirs(cache_dir, exist_ok=True)
            disk_key = hashlib.md5(f"{path}_{mtime}_{size[0]}x{size[1]}".encode('utf-8')).hexdigest()
            disk_path = os.path.join(cache_dir, f"{disk_key}.jpg")

            if os.path.isfile(disk_path):
                try:
                    with Image.open(disk_path) as cached_im:
                        photo = ImageTk.PhotoImage(cached_im.copy())
                        self.screenshot_thumbnail_cache[cache_key] = photo
                        return photo
                except Exception:
                    pass

            img = Image.open(path).convert("RGB")
            img.thumbnail(size, Image.Resampling.LANCZOS)
            background = Image.new("RGB", size, COLORS.get('input_bg', '#1A1A1A'))
            offset_x = max(0, (size[0] - img.width) // 2)
            offset_y = max(0, (size[1] - img.height) // 2)
            background.paste(img, (offset_x, offset_y))

            # Save to disk cache
            try:
                background.save(disk_path, "JPEG", quality=85)
            except Exception:
                pass

            photo = ImageTk.PhotoImage(background)
            self.screenshot_thumbnail_cache[cache_key] = photo
            return photo
        except Exception:
            return None

    def delete_screenshot(self, path):
        if not custom_askyesno("Delete Screenshot", f"Delete '{os.path.basename(path)}'?", parent=self.root):
            return
        try:
            addon_delete_screenshot(path, self.minecraft_dir)
            self.save_config(sync_ui=False)
            self.render_screenshot_browser()
        except Exception as e:
            custom_showerror("Delete Failed", f"Could not delete screenshot:\n{e}", parent=self.root)

    def render_screenshot_browser(self):
        if not hasattr(self, 'screenshot_grid_frame'):
            return

        for widget in self.screenshot_grid_frame.winfo_children():
            widget.destroy()

        screenshots = self._list_screenshot_files()
        screenshots_dir = self.get_screenshots_dir()
        if hasattr(self, 'screenshot_status_lbl'):
            count = len(screenshots)
            self.screenshot_status_lbl.config(text=f"{count} screenshot{'s' if count != 1 else ''} in {screenshots_dir}")

        if not screenshots:
            tk.Label(self.screenshot_grid_frame, text="No screenshots found yet.", font=("Segoe UI", 10), bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w")
            self._refresh_addons_scroll_bindings()
            return

        columns = 3
        for column in range(columns):
            self.screenshot_grid_frame.grid_columnconfigure(column, weight=1)

        for index, path in enumerate(screenshots[:18]):
            card = tk.Frame(self.screenshot_grid_frame, bg=COLORS.get('input_bg', '#1A1A1A'), padx=10, pady=10)
            card.grid(row=index // columns, column=index % columns, sticky="nsew", padx=6, pady=6)

            thumbnail = self._get_screenshot_thumbnail(path)
            if thumbnail:
                preview = tk.Label(card, image=thumbnail, bg=COLORS.get('input_bg', '#1A1A1A'))
                preview.image = thumbnail  # type: ignore[attr-defined]
            else:
                preview = tk.Label(card, text="No Preview", width=20, height=6, bg=COLORS.get('input_bg', '#1A1A1A'), fg=COLORS['text_secondary'])
            preview.pack(fill="x")

            tk.Label(card, text=os.path.basename(path), font=("Segoe UI", 9, "bold"), bg=COLORS.get('input_bg', '#1A1A1A'), fg=COLORS['text_primary'], anchor="w").pack(fill="x", pady=(8, 2))
            tk.Label(card, text=datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M"), font=("Segoe UI", 8), bg=COLORS.get('input_bg', '#1A1A1A'), fg=COLORS['text_secondary'], anchor="w").pack(fill="x")

            btns = tk.Frame(card, bg=COLORS.get('input_bg', '#1A1A1A'))
            btns.pack(fill="x", pady=(8, 0))
            self._make_btn(btns, "Open", style="secondary", font_size=8, command=lambda p=path: self._open_path(p)).pack(side="left")
            self._make_btn(btns, "Delete", style="secondary", font_size=8, command=lambda p=path: self.delete_screenshot(p)).pack(side="right")

            def show_screenshot_menu(event, p=path):
                m = NeoContextMenu(self.root)
                m.add_item("🖼 Open Screenshot", lambda: self._open_path(p))
                m.add_item("📁 Open Screenshots Folder", lambda: open_path_in_system(screenshots_dir))
                m.add_separator()
                m.add_item("🗑 Delete Screenshot", lambda: self.delete_screenshot(p), is_danger=True)
                m.show_at(event.x_root, event.y_root)

            attach_context_menu(card, show_screenshot_menu)

        self._refresh_addons_scroll_bindings()

    def refresh_addons_tab_state(self):
        self._ensure_addons_config_defaults()

        if hasattr(self, 'streamer_mode_var'):
            self.streamer_mode_var.set(bool(self.addons_config.get("streamer_mode_enabled", False)))
        if hasattr(self, 'gh_sync_enabled'):
            self.gh_sync_enabled.set(bool(self.addons_config.get("gh_sync_enabled", False)))
        if hasattr(self, 'gh_repo_entry'):
            self.gh_repo_entry.delete(0, tk.END)
            self.gh_repo_entry.insert(0, str(self.addons_config.get("gh_repo", "")))
        if hasattr(self, 'gh_token_entry'):
            self.gh_token_entry.delete(0, tk.END)
            self.gh_token_entry.insert(0, str(self.addons_config.get("gh_token", "")))

        self._refresh_quick_join_installation_values()
        self.render_playtime_tracker()
        self.render_quick_join_servers()
        self.render_screenshot_browser()
        self.refresh_third_party_addons()
        self._apply_streamer_mode_ui()
        self._refresh_addons_scroll_bindings()

    def _save_addons_config(self):
        self._ensure_addons_config_defaults()
        self.addons_config["gh_sync_enabled"] = self.gh_sync_enabled.get()
        self.save_config()

    def _save_gh_sync_settings(self):
        self._ensure_addons_config_defaults()
        repo = self.gh_repo_entry.get().strip()
        token = self.gh_token_entry.get().strip()
        
        self.addons_config.update({
            "gh_sync_enabled": self.gh_sync_enabled.get(),
            "gh_repo": repo,
            "gh_token": token
        })
        self.save_config()
        
        if self.gh_sync_enabled.get():
             self.perform_gh_skin_sync()
        else:
             if hasattr(self, 'toast_manager'):
                 self.toast_manager.show("Settings saved.", level="info")
             else:
                 custom_showinfo("Saved", "Settings saved.")

    def perform_gh_skin_sync(self):
        # Trigger Agent to Sync
        if not self.profiles: return
        
        current_p = self.profiles[self.current_profile_index]
        username = current_p.get("name", "Unknown")
        skin_path = current_p.get("skin_path")
        
        payload = {
            "repo": self.addons_config.get("gh_repo"),
            "token": self.addons_config.get("gh_token"),
            "username": username,
            "skin_path": skin_path,
            "upload": True,
            "download": True
        }
        
        self.show_progress_overlay("Syncing Skins...")
        
        def on_complete(res):
            self.hide_progress_overlay()
            if res.get("status") == "success":
                msg = f"Skin sync complete! {res.get('msg', '')}".strip()
                if hasattr(self, 'toast_manager'):
                    self.toast_manager.show(msg, level="success")
                else:
                    custom_showinfo("Success", msg)
            else:
                custom_showerror("Sync Error", res.get("msg", "Unknown error"))
                
        self.send_agent_request("gh_skin_sync", payload, lambda r: self.root.after(0, lambda: on_complete(r)))

    def start_agent_process(self):

        if hasattr(self, 'agent_process') and self.agent_process and self.agent_process.poll() is None:
            return # Already running
            
        try:
            # Determine command based on environment (Frozen vs Source)
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
                agent_candidates = [
                    os.path.join(base_dir, "agent.exe"),
                    os.path.join(base_dir, "agent"),
                ]
                agent_exe = next((path for path in agent_candidates if os.path.exists(path)), agent_candidates[0])
                cmd = [agent_exe, self.config_dir]
                cwd = base_dir
            else:
                script = resource_path("agent.py")
                cmd = [sys.executable, script, self.config_dir]
                cwd = os.path.dirname(script)
            
            # Start detached process with pipes
            startupinfo = None
            creationflags = 0
            
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                creationflags = subprocess.CREATE_NO_WINDOW
                
            self.agent_process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, 
                text=True,
                startupinfo=startupinfo,
                creationflags=creationflags
            )
            
            # Start Listener
            threading.Thread(target=self._agent_listener_thread, daemon=True).start()
            
            self.log(f"Agent started with PID {self.agent_process.pid}")
            
        except Exception as e:
            custom_showerror("Agent Error", f"Failed to start agent: {e}")

    def _agent_listener_thread(self):
        if not self.agent_process: return
        
        try:
            while self.agent_process and self.agent_process.poll() is None:
                # Use readline to get line-buffered output
                if not self.agent_process.stdout: break
                line = self.agent_process.stdout.readline()
                if not line: break
                
                try:
                    data = json.loads(line)
                    req_id = data.get("id")
                    
                    if req_id in self.agent_callbacks:
                        callback = self.agent_callbacks.pop(req_id)
                        # Run callback safely on main thread
                        res_val = data.get("result")
                        if hasattr(self, "dispatch_ui"):
                            self.dispatch_ui(callback, res_val)
                        else:
                            try:
                                self.root.after(0, lambda c=callback, d=res_val: c(d))
                            except Exception:
                                pass
                        
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            print(f"Agent listener error: {e}")
            
        # Cleanup if process died
        if hasattr(self, "dispatch_ui"):
            self.dispatch_ui(self._on_agent_exit)
        else:
            try:
                self.root.after(0, self._on_agent_exit)
            except Exception:
                pass

    def _on_agent_exit(self):
        self.agent_process = None
        # Drain and notify any pending callbacks so callers do not hang indefinitely
        with getattr(self, "agent_lock", threading.Lock()):
            callbacks = list(self.agent_callbacks.values())
            self.agent_callbacks.clear()
        for cb in callbacks:
            err_dict = {"status": "error", "msg": "Agent disconnected"}
            if hasattr(self, "dispatch_ui"):
                self.dispatch_ui(cb, err_dict)
            else:
                try:
                    self.root.after(0, lambda c=cb: c(err_dict))
                except Exception:
                    pass

    def send_agent_request(self, action, payload, callback=None):
        if not self.agent_process or self.agent_process.poll() is not None:
            # Try to auto-start
            self.start_agent_process()
            # If still failed, abort
            if not self.agent_process or self.agent_process.poll() is not None:
                if callback:
                    self.root.after(0, lambda: callback({"status": "error", "msg": "Agent not running"}))
                return

        req_id = str(uuid.uuid4())
        request = {"id": req_id, "action": action, "payload": payload}
        
        if callback:
            self.agent_callbacks[req_id] = callback
            
        try:
            with self.agent_lock:
                if self.agent_process.stdin:
                    self.agent_process.stdin.write(json.dumps(request) + "\n")
                    self.agent_process.stdin.flush()
        except Exception as e:
            if req_id in self.agent_callbacks:
                 del self.agent_callbacks[req_id]
            if callback:
                 callback({"status": "error", "msg": str(e)})

    def stop_agent_process(self):
        if hasattr(self, 'agent_process') and self.agent_process:
            self.agent_process.terminate()
            self.agent_process = None
            
            self.log("Agent stopped.")

    def refresh_addons_screen_theme(self):
        """Update existing Addons tab widgets in-place with active theme tokens."""
        main_bg = COLORS.get('main_bg', '#12141A')
        card_bg = COLORS.get('card_bg', '#1E222B')
        text_primary = COLORS.get('text_primary', '#FFFFFF')

        tab = getattr(self, "tabs", {}).get("Addons")
        if tab and tab.winfo_exists():
            try:
                tab.config(bg=main_bg)
            except Exception:
                pass

        if hasattr(self, 'addons_header_frame') and self.addons_header_frame and self.addons_header_frame.winfo_exists():
            try:
                self.addons_header_frame.config(bg=main_bg)
            except Exception:
                pass

        if hasattr(self, 'addons_title_lbl') and self.addons_title_lbl and self.addons_title_lbl.winfo_exists():
            try:
                self.addons_title_lbl.config(bg=main_bg, fg=text_primary)
            except Exception:
                pass

        if hasattr(self, 'addons_canvas') and self.addons_canvas and self.addons_canvas.winfo_exists():
            try:
                self.addons_canvas.config(bg=main_bg)
            except Exception:
                pass

        if hasattr(self, 'addons_scroll_frame') and self.addons_scroll_frame and self.addons_scroll_frame.winfo_exists():
            try:
                self.addons_scroll_frame.config(bg=main_bg)
            except Exception:
                pass

        if hasattr(self, 'addons_content_frame') and self.addons_content_frame and self.addons_content_frame.winfo_exists():
            try:
                self.addons_content_frame.config(bg=main_bg)
            except Exception:
                pass

        try:
            self.refresh_addons_tab_state()
        except Exception:
            pass



