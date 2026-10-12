"""
nlc.ui.screens.mods - Modrinth browser, search, modpack installation
"""

import io
import os
import sys
import json
import uuid
import time
import shutil
import logging
import threading
import hashlib
from concurrent.futures import ThreadPoolExecutor
import webbrowser
import tempfile
import urllib.parse
import zipfile
import re
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import requests
import minecraft_launcher_lib

from nlc.storage.paths import resource_path, open_path_in_system
from nlc.ui.theme import COLORS, FONT_FAMILY
from nlc.ui.components.dialogs import custom_showinfo, custom_showerror, custom_askyesno
from nlc.ui.components.modal import get_modal_manager
from nlc.ui.components.context_menu import NeoContextMenu, attach_context_menu, attach_entry_context_menu
from nlc.net.http import get_http_session
from nlc.net.downloader import _atomic_download
from nlc.core.launch import safe_extract_zip as _safe_extract_zip

logger = logging.getLogger(__name__)

# Bounded worker pool to prevent CPU pinning & RAM spikes during mod browsing
_MOD_ICON_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ModIconPool")

class ModsScreenMixin:
    """Mixin providing Modrinth mod/modpack browser, search, and installation."""
    def create_mods_tab(self):
        frame = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Mods"] = frame

        # Dual in-place views: Browse list vs Details view
        self.mods_browse_view = tk.Frame(frame, bg=COLORS['main_bg'])
        self.mods_browse_view.pack(fill="both", expand=True)

        self.mods_detail_view = tk.Frame(frame, bg=COLORS['main_bg'])
        self._in_mod_details = False
        self.cached_gallery_images = {}
        
        # Top Bar (Search & Filters) inside browse view
        top_bar = tk.Frame(self.mods_browse_view, bg=COLORS['main_bg'], pady=10, padx=20)
        top_bar.pack(fill="x")
        self.mods_top_bar = top_bar

        # Modpack Selection
        mp_frame = tk.Frame(top_bar, bg=COLORS['main_bg'])
        mp_frame.pack(side="top", fill="x", pady=(0, 10))
        self.mods_mp_frame = mp_frame
        
        self.mods_mp_label = tk.Label(mp_frame, text="Active Modpack:", bg=COLORS['main_bg'], fg=COLORS['text_secondary'])
        self.mods_mp_label.pack(side="left")
        
        pack_names = ["None"] + [p['name'] for p in self.modpacks]
        self.active_modpack_var = tk.StringVar(value="None")
        
        self.mods_active_pack_combobox = ttk.Combobox(mp_frame, textvariable=self.active_modpack_var, 
                            values=pack_names, 
                            style="Launcher.TCombobox", width=25, state="readonly")
        self.mods_active_pack_combobox.pack(side="left", padx=10)
        
        # When modpack changes, force filter update
        def on_pack_change(e):
             p_name = self.active_modpack_var.get()
             if p_name != "None":
                 # Find pack
                 pack = next((p for p in self.modpacks if p['name'] == p_name), None)
                 if pack:
                     self.mod_loader_filter.set(pack['loader'])
                     # We might want to lock it or show it's locked
             self.search_mods_thread(reset=True)

        self.mods_active_pack_combobox.bind("<<ComboboxSelected>>", on_pack_change)

        # View Mode (Mods vs Modpacks vs Resource Packs vs Shaders)
        self.browse_mode_var = tk.StringVar(value="mod")

        def switch_mode(m):
            if getattr(self, '_in_mod_details', False):
                self.close_project_details()
            self.browse_mode_var.set(m)
            self.search_mods_thread(reset=True)
            
            # Hide or show the modpack selection
            if m in ["modpack", "shader", "resourcepack"]:
                mp_frame.pack_forget()
            else:
                mp_frame.pack(side="top", fill="x", pady=(0, 10), before=search_line)

        # Expose the method globally for Neo sidebar drill-down
        self.switch_modrinth_mode = switch_mode
        
        # Search Entry
        search_line = tk.Frame(top_bar, bg=COLORS['main_bg'])
        search_line.pack(fill="x")
        self.mods_search_line = search_line
        
        self.mod_search_var = tk.StringVar()
        self.mod_search_var.trace_add("write", lambda *args: self.schedule_mod_search())
        
        search_frame = tk.Frame(search_line, bg=COLORS['input_bg'], padx=10, pady=5)
        search_frame.pack(side="left", fill="x", expand=True)
        self.mods_search_frame = search_frame
        
        self.mods_search_icon = tk.Label(search_frame, text="🔍", bg=COLORS['input_bg'], fg=COLORS['text_secondary'])
        self.mods_search_icon.pack(side="left")
        
        entry = tk.Entry(search_frame, textvariable=self.mod_search_var, font=("Segoe UI", 11),
                        bg=COLORS['input_bg'], fg=COLORS['text_primary'], relief="flat", insertbackground="white")
        entry.pack(side="left", fill="x", expand=True)
        self.mods_search_entry = entry
        attach_entry_context_menu(entry)

        # Filters
        self.mod_loader_filter = tk.StringVar(value="fabric") # Default
        loader_cb = ttk.Combobox(search_line, textvariable=self.mod_loader_filter, 
                                values=["fabric", "forge"], 
                                style="Launcher.TCombobox", width=10, state="readonly")
        loader_cb.pack(side="left", padx=10)
        loader_cb.bind("<<ComboboxSelected>>", lambda e: self.search_mods_thread(reset=True))
        
        self.mods_loader_combobox = loader_cb # Store ref for updates

        # Game Version Filter
        self.mod_version_filter = tk.StringVar(value="All")
        version_cb = ttk.Combobox(search_line, textvariable=self.mod_version_filter, 
                                values=["All"], 
                                style="Launcher.TCombobox", width=10, state="readonly")
        version_cb.pack(side="left", padx=5)
        version_cb.bind("<<ComboboxSelected>>", lambda e: self.search_mods_thread(reset=True))
        
        self.mods_version_combobox = version_cb

        # Load Versions Async
        def load_versions():
            try:
                vlist = minecraft_launcher_lib.utils.get_version_list()
                releases = ["All"] + [v['id'] for v in vlist if v['type'] == 'release']
                self.root.after(0, lambda: version_cb.config(values=releases))
            except: pass
        threading.Thread(target=load_versions, daemon=True).start()

        # Update controls when pack changes
        def update_filter_state(e=None):
             p_name = self.active_modpack_var.get()
             if p_name != "None":
                 # Find pack
                 pack = next((p for p in self.modpacks if p['name'] == p_name), None)
                 if pack:
                     # Set and Disable
                     self.mod_loader_filter.set(pack['loader'])
                     self.mod_version_filter.set(pack['mc_version'])
                     
                     loader_cb.config(state="disabled")
                     version_cb.config(state="disabled")
             else:
                 # Enable
                 loader_cb.config(state="readonly")
                 version_cb.config(state="readonly")
                 
             self.search_mods_thread(reset=True)

        # Rebind
        self.mods_active_pack_combobox.bind("<<ComboboxSelected>>", update_filter_state)

        # Content Area (Scrollable) inside mods_browse_view
        self.mods_canvas = tk.Canvas(self.mods_browse_view, bg=COLORS['main_bg'], highlightthickness=0)
        self.mods_scrollbar = ttk.Scrollbar(self.mods_browse_view, orient="vertical", command=self.mods_canvas.yview, style="Launcher.Vertical.TScrollbar")
        self.mods_scrollable_frame = tk.Frame(self.mods_canvas, bg=COLORS['main_bg'])
        
        self.mods_scrollable_frame.bind(
            "<Configure>",
            lambda e: self.mods_canvas.configure(scrollregion=self.mods_canvas.bbox("all"))
        )
        
        self.mods_canvas_window = self.mods_canvas.create_window((0, 0), window=self.mods_scrollable_frame, anchor="nw")
        
        def on_canvas_configure(event):
            self.mods_canvas.itemconfig(self.mods_canvas_window, width=event.width)
        
        self.mods_canvas.bind("<Configure>", on_canvas_configure)
        self.mods_canvas.configure(yscrollcommand=self._on_scrollbar_update)
        
        self.mods_canvas.pack(side="left", fill="both", expand=True)
        self.mods_scrollbar.pack(side="right", fill="y")
        
        # Smooth mousewheel for Mods Tab with infinite scroll check
        self.last_scroll_check = 0.0

        self._bind_smooth_scroll(self.mods_canvas, self.mods_scrollable_frame)
        self.mods_canvas._nlc_after_scroll = self._check_scroll_position  # type: ignore[attr-defined]

        self.mod_search_timer = None
        self._mod_load_more_after_id = None
        self._mod_search_generation = 0
        self._mod_page_size = 20
        self.cached_mod_images = {}
        self.mod_image_loading = set()
        self.mod_image_waiters = {}
        
        # Pagination State
        self.mod_offset = 0
        self.mod_loading = False
        self.mod_end_reached = False
        self.mods_tab_initialized = False # Flag for lazy load
        
        # We DO NOT auto-load here to prevent startup freeze.
        # It is triggered by show_tab("Mods")
        tk.Label(self.mods_scrollable_frame, text="Loading Mods...", 
                font=("Segoe UI", 12), fg=COLORS['text_secondary'], bg=COLORS['main_bg']).pack(pady=40)

    def refresh_mods_screen_theme(self):
        """Update Modrinth Mods tab chrome, search input, canvas, and cards."""
        main_bg = COLORS['main_bg']
        input_bg = COLORS.get('input_bg', '#1E222B')
        card_bg = COLORS['card_bg']
        text_primary = COLORS['text_primary']
        text_secondary = COLORS.get('text_secondary', '#A0AAB0')

        if hasattr(self, 'tabs') and "Mods" in self.tabs:
            tab = self.tabs["Mods"]
            if tab and tab.winfo_exists():
                tab.config(bg=main_bg)

        if hasattr(self, 'mods_browse_view') and self.mods_browse_view.winfo_exists():
            self.mods_browse_view.config(bg=main_bg)

        if hasattr(self, 'mods_detail_view') and self.mods_detail_view.winfo_exists():
            self.mods_detail_view.config(bg=main_bg)
            if hasattr(self, 'detail_top_bar') and self.detail_top_bar.winfo_exists():
                self.detail_top_bar.config(bg=main_bg)
            if hasattr(self, 'detail_canvas') and self.detail_canvas.winfo_exists():
                self.detail_canvas.config(bg=main_bg)
            if hasattr(self, 'detail_scrollable_frame') and self.detail_scrollable_frame.winfo_exists():
                self.detail_scrollable_frame.config(bg=main_bg)
            if hasattr(self, 'detail_hero_card') and self.detail_hero_card.winfo_exists():
                self.detail_hero_card.config(bg=card_bg)
                for c in self.detail_hero_card.winfo_children():
                    if isinstance(c, tk.Frame) and c.winfo_exists():
                        c.config(bg=card_bg)
                        for sub in c.winfo_children():
                            if isinstance(sub, tk.Label) and sub.winfo_exists():
                                sub.config(bg=card_bg)
            if hasattr(self, 'detail_gallery_section') and self.detail_gallery_section.winfo_exists():
                self.detail_gallery_section.config(bg=card_bg)
            if hasattr(self, 'detail_mods_section') and self.detail_mods_section.winfo_exists():
                self.detail_mods_section.config(bg=card_bg)
            if hasattr(self, 'detail_desc_section') and self.detail_desc_section.winfo_exists():
                self.detail_desc_section.config(bg=card_bg)
            if hasattr(self, 'detail_text_widget') and self.detail_text_widget.winfo_exists():
                self.detail_text_widget.config(bg=card_bg, fg=text_primary)

        for attr in ['mods_top_bar', 'mods_mp_frame', 'mods_search_line']:
            w = getattr(self, attr, None)
            if w and w.winfo_exists():
                w.config(bg=main_bg)

        if hasattr(self, 'mods_mp_label') and self.mods_mp_label.winfo_exists():
            self.mods_mp_label.config(bg=main_bg, fg=text_secondary)

        if hasattr(self, 'mods_search_frame') and self.mods_search_frame.winfo_exists():
            self.mods_search_frame.config(bg=input_bg)
        if hasattr(self, 'mods_search_icon') and self.mods_search_icon.winfo_exists():
            self.mods_search_icon.config(bg=input_bg, fg=text_secondary)
        if hasattr(self, 'mods_search_entry') and self.mods_search_entry.winfo_exists():
            self.mods_search_entry.config(bg=input_bg, fg=text_primary)

        if hasattr(self, 'mods_canvas') and self.mods_canvas.winfo_exists():
            self.mods_canvas.config(bg=main_bg)
        if hasattr(self, 'mods_scrollable_frame') and self.mods_scrollable_frame.winfo_exists():
            self.mods_scrollable_frame.config(bg=main_bg)
            for card in self.mods_scrollable_frame.winfo_children():
                if isinstance(card, tk.Frame) and card.winfo_exists():
                    card.config(bg=card_bg)
                    for child in card.winfo_children():
                        if isinstance(child, tk.Frame) and child.winfo_exists():
                            child.config(bg=card_bg)
                            for sub in child.winfo_children():
                                if isinstance(sub, tk.Label) and sub.winfo_exists():
                                    sub.config(bg=card_bg)
                        elif isinstance(child, tk.Label) and child.winfo_exists():
                            child.config(bg=input_bg if child.cget("text") == "?" else card_bg)
                elif isinstance(card, tk.Label) and card.winfo_exists():
                    card.config(bg=main_bg, fg=text_secondary)

    def _on_scrollbar_update(self, first, last):
        self.mods_scrollbar.set(first, last)
        self._check_scroll_position()

    def _check_scroll_position(self):
        if self.mod_loading or self.mod_end_reached or getattr(self, "_mod_load_more_after_id", None):
            return
        # If user is flicking or scrolling rapidly, wait until velocity settles
        # before triggering pagination requests and DOM additions.
        cid = id(self.mods_canvas)
        velocity = getattr(self, "_scroll_velocities", {}).get(cid, 0.0)
        if abs(velocity) > 40.0:
            return
        try:
            # Keep enough content below the viewport that pagination feels
            # seamless, without immediately chaining page requests.
            if self.mods_canvas.yview()[1] >= 0.90:
                self._mod_load_more_after_id = self.root.after(90, self._run_scheduled_mod_page)
        except tk.TclError:
            return

    def _run_scheduled_mod_page(self):
        self._mod_load_more_after_id = None
        self.load_more_mods()

    def schedule_mod_search(self, *args):
        if self.mod_search_timer:
            try:
                self.root.after_cancel(self.mod_search_timer)
            except tk.TclError:
                pass
        self.mod_search_timer = self.root.after(800, self._run_debounced_mod_search)

    def _run_debounced_mod_search(self):
        self.mod_search_timer = None
        self.search_mods_thread(reset=True)

    def load_more_mods(self):
        if self.mod_loading or self.mod_end_reached: return
        self.search_mods_thread(reset=False)

    def search_mods_thread(self, reset=False):
        if self.mod_loading and not reset:
            return
        if reset:
            self._mod_search_generation += 1
            if self._mod_load_more_after_id:
                try:
                    self.root.after_cancel(self._mod_load_more_after_id)
                except tk.TclError:
                    pass
                self._mod_load_more_after_id = None
        generation = self._mod_search_generation
        self.mod_loading = True
        
        query = self.mod_search_var.get().strip()
        loader = self.mod_loader_filter.get().lower()
        if loader == "all": loader = "" # Though we default to fabric now
        
        # Check active modpack for version constraint
        version_facet = ""
        p_name = self.active_modpack_var.get()
        if p_name != "None":
             pack = next((p for p in self.modpacks if p['name'] == p_name), None)
             if pack:
                 loader = pack['loader'] # Force loader
                 version_facet = pack['mc_version']
        else:
             # Use filters
             if hasattr(self, 'mod_version_filter'):
                 vf = self.mod_version_filter.get()
                 if vf != "All": version_facet = vf

        if reset:
            self.mod_offset = 0
            self.mod_end_reached = False
            # Scroll to top
            self.mods_canvas.yview_moveto(0)
            
            for w in self.mods_scrollable_frame.winfo_children(): w.destroy()
            tk.Label(self.mods_scrollable_frame, text="Searching...", 
                     font=("Segoe UI", 12), fg=COLORS['accent_blue'], bg=COLORS['main_bg']).pack(pady=20)

        payload = {
            "query": query,
            "limit": self._mod_page_size,
            "offset": self.mod_offset,
            "facets": []
        }
        
        # Project Type
        p_type = "mod"
        if hasattr(self, 'browse_mode_var'):
             p_type = self.browse_mode_var.get()
        payload["facets"].append(f'project_type:{p_type}')

        if loader and p_type not in ["resourcepack", "shader"]:
            payload["facets"].append(f'categories:{loader}')
        if version_facet:
            payload["facets"].append(f'versions:{version_facet}')

        def handle_response(res):
            if res and res.get("status") == "success":
                self._on_mod_search_result(res, reset, generation)
            else:
                # If agent is unavailable or returns an error, fallback to direct search
                threading.Thread(
                    target=self._direct_search_mods_worker,
                    args=(payload, reset, generation),
                    daemon=True
                ).start()

        # Try agent if running, otherwise use direct worker
        if getattr(self, "agent_process", None) and self.agent_process.poll() is None:
            self.send_agent_request("search_mods", payload, handle_response)
        else:
            threading.Thread(
                target=self._direct_search_mods_worker,
                args=(payload, reset, generation),
                daemon=True
            ).start()

    def _direct_search_mods_worker(self, payload, reset, generation):
        if generation != self._mod_search_generation:
            return
        try:
            query = payload.get("query", "")
            limit = payload.get("limit", 20)
            offset = payload.get("offset", 0)
            facets = payload.get("facets", [])
            
            params = f"limit={limit}&offset={offset}"
            if query:
                params += f"&query={urllib.parse.quote(query)}"
            else:
                params += "&index=downloads"

            if facets:
                facet_str = ",".join(f'["{f}"]' for f in facets)
                enc = urllib.parse.quote(f'[{facet_str}]')
                params += f'&facets={enc}'

            url = f"https://api.modrinth.com/v2/search?{params}"
            session = get_http_session()
            response = session.get(url, headers={"User-Agent": "AmneDev/NewLauncher"}, timeout=15)
            if response.status_code == 200:
                result = {"status": "success", "data": response.json()}
            else:
                result = {"status": "error", "code": response.status_code, "msg": response.text}
        except Exception as e:
            result = {"status": "error", "msg": str(e)}

        self.root.after(0, lambda: self._on_mod_search_result(result, reset, generation))

    def _on_mod_search_result(self, result, reset, generation=None):
        if generation is not None and generation != self._mod_search_generation:
            return
        if not result or result.get("status") != "success":
            self.mod_loading = False
            msg = result.get("msg", "Unknown error") if result else "No response"
            self._display_mod_error(msg)
            return
            
        data = result.get("data", {})
        hits = data.get("hits", [])
        
        if hits:
            self.mod_offset += len(hits)
        else:
            self.mod_end_reached = True

        self._display_mod_results(hits, reset, generation)

    def _display_mod_error(self, msg):
        tk.Label(self.mods_scrollable_frame, text=f"Error: {msg}", 
                 fg=COLORS['error_red'], bg=COLORS['main_bg']).pack(pady=20)

    def _display_mod_results(self, hits, reset, generation=None):
        if generation is not None and generation != self._mod_search_generation:
            return
        if reset:
            for w in self.mods_scrollable_frame.winfo_children():
                w.destroy()
            if not hits:
                tk.Label(self.mods_scrollable_frame, text="No results found", 
                         fg=COLORS['text_secondary'], bg=COLORS['main_bg']).pack(pady=20)
                self.mod_loading = False
                return

        # Render cards progressively in lightweight batches of 5 to eliminate GUI freeze
        chunk_size = 5
        total_hits = len(hits)

        def render_batch(start_idx):
            if generation is not None and generation != self._mod_search_generation:
                self.mod_loading = False
                return
            if not hasattr(self, 'mods_scrollable_frame') or not self.mods_scrollable_frame.winfo_exists():
                self.mod_loading = False
                return

            end_idx = min(start_idx + chunk_size, total_hits)
            for i in range(start_idx, end_idx):
                self._create_mod_card(hits[i])

            try:
                self.mods_canvas.configure(scrollregion=self.mods_canvas.bbox("all"))
                self._bind_smooth_scroll(self.mods_canvas, self.mods_scrollable_frame)
            except (tk.TclError, AttributeError):
                pass

            if end_idx < total_hits:
                self.root.after(15, lambda: render_batch(end_idx))
            else:
                self.mod_loading = False

        render_batch(0)

    def _create_mod_card(self, mod):
        card = tk.Frame(self.mods_scrollable_frame, bg=COLORS['card_bg'], pady=10, padx=10)
        card.pack(fill="x", padx=20, pady=5)
        
        # Icon
        icon_lbl = tk.Label(card, text="?", bg=COLORS.get('input_bg', '#212121'), fg="white", width=8, height=4)
        icon_lbl.pack(side="left", padx=(0, 15))
        
        icon_url = mod.get("icon_url")
        if icon_url:
            self._load_mod_icon_async(icon_url, icon_lbl)

        # Info
        info_frame = tk.Frame(card, bg=COLORS['card_bg'])
        info_frame.pack(side="left", fill="both", expand=True)
        
        tk.Label(info_frame, text=mod.get("title", "Unknown"), font=("Segoe UI", 12, "bold"), 
                 fg="white", bg=COLORS['card_bg'], anchor="w", justify="left", wraplength=460).pack(fill="x")
        
        # Desc
        desc = mod.get("description", "")
        if len(desc) > 80: desc = desc[:77] + "..."
        tk.Label(info_frame, text=desc, font=("Segoe UI", 9), 
                 fg=COLORS['text_secondary'], bg=COLORS['card_bg'], anchor="w").pack(fill="x")
        
        # Meta
        tk.Label(info_frame, text=f"By {mod.get('author', 'Unknown')}", font=("Segoe UI", 8), 
                 fg=COLORS.get('text_muted', '#6B7280'), bg=COLORS['card_bg'], anchor="w").pack(fill="x", pady=(2, 0))

        # Buttons
        btn_frame = tk.Frame(card, bg=COLORS['card_bg'])
        btn_frame.pack(side="right")

        project_type = mod.get('project_type', 'mod')
        action_btn = None

        # INSTALL BUTTON (If pack selected or Modpack Browse)
        if project_type == 'modpack':
             btn = self._make_btn(btn_frame, "Download", style="primary", font_size=9, bold=True)
             btn.pack(side="right", padx=5)
             btn.config(command=lambda m=mod, b=btn: self._install_mr_modpack(m, b))
             action_btn = btn
             
        elif project_type in ['resourcepack', 'shader']:
             btn = self._make_btn(btn_frame, "Install", style="primary", font_size=9, bold=True)
             btn.pack(side="right", padx=5)
             btn.config(command=lambda m=mod, b=btn: self._install_global_resource(m, b))
             action_btn = btn

        else:
            active_pack_name = self.active_modpack_var.get()
            if active_pack_name != "None":
                # Check if installed
                pack = next((p for p in self.modpacks if p['name'] == active_pack_name), None)
                is_installed = False
                if pack:
                    # Check meta
                    mod_slug = mod.get('slug')
                    if any(m.get('slug') == mod_slug for m in pack['mods']):
                        is_installed = True
                
                if is_installed:
                    tk.Label(btn_frame, text="✔ Installed", font=("Segoe UI", 9, "bold"), 
                            fg=COLORS['success_green'], bg=COLORS['card_bg']).pack(side="right", padx=10)
                else:
                    btn = self._make_btn(btn_frame, "Install", style="primary", font_size=9, bold=True)
                    btn.pack(side="right", padx=5)
                    btn.config(command=lambda b=btn, m=mod, p=active_pack_name: self._install_mod_to_pack(m, p, b))
                    action_btn = btn

        self._make_btn(btn_frame, "Web", style="secondary", font_size=9,
                      command=lambda u=f"https://modrinth.com/{mod.get('project_type', 'mod')}/{mod['slug']}": webbrowser.open(u)).pack(side="right", padx=5)

        # Open in-place Project Details on clicking card (outside action buttons)
        def open_details(e=None):
            self.show_project_details(mod)

        for w in (card, icon_lbl, info_frame):
            w.config(cursor="hand2")
            w.bind("<Button-1>", open_details)
        for child in info_frame.winfo_children():
            child.config(cursor="hand2")
            child.bind("<Button-1>", open_details)

        card_default_bg = COLORS['card_bg']
        card_hover_bg = COLORS.get('input_bg', '#1E222B')

        def on_card_enter(e):
            if card.winfo_exists():
                card.config(bg=card_hover_bg)
                if info_frame.winfo_exists(): info_frame.config(bg=card_hover_bg)
                if btn_frame.winfo_exists(): btn_frame.config(bg=card_hover_bg)
                for c in info_frame.winfo_children():
                    if c.winfo_exists(): c.config(bg=card_hover_bg)

        def on_card_leave(e):
            if card.winfo_exists():
                card.config(bg=card_default_bg)
                if info_frame.winfo_exists(): info_frame.config(bg=card_default_bg)
                if btn_frame.winfo_exists(): btn_frame.config(bg=card_default_bg)
                for c in info_frame.winfo_children():
                    if c.winfo_exists(): c.config(bg=card_default_bg)

        card.bind("<Enter>", on_card_enter)
        card.bind("<Leave>", on_card_leave)

        def show_mod_card_menu(event):
            m = NeoContextMenu(self.root)
            m.add_item("ℹ View Details", lambda: self.show_project_details(mod))
            m.add_item("🌐 Open on Modrinth", lambda: webbrowser.open(f"https://modrinth.com/{mod.get('project_type', 'mod')}/{mod.get('slug', '')}"))
            
            p_type = mod.get('project_type', 'mod')
            active_p_name = self.active_modpack_var.get()
            if p_type == 'modpack' and action_btn:
                m.add_separator()
                m.add_item("📥 Download Modpack", lambda: self._install_mr_modpack(mod, action_btn))
            elif p_type in ['resourcepack', 'shader'] and action_btn:
                m.add_separator()
                m.add_item("📥 Install Resource", lambda: self._install_global_resource(mod, action_btn))
            elif active_p_name != "None":
                pack = next((p for p in self.modpacks if p['name'] == active_p_name), None)
                if pack:
                    m.add_separator()
                    m.add_item(f"📁 Open Mods Folder", lambda: open_path_in_system(os.path.join(self.get_modpack_dir(pack['id']), "mods")))
                    if action_btn:
                        m.add_item(f"📥 Install to {pack['name']}", lambda: self._install_mod_to_pack(mod, active_p_name, action_btn))
            m.show_at(event.x_root, event.y_root)

        attach_context_menu(card, show_mod_card_menu)

    def _install_mod_to_pack(self, mod_data, pack_name, btn_widget):
        pack = next((p for p in self.modpacks if p['name'] == pack_name), None)
        if not pack: return
        
        # Update button state
        btn_widget.config(state="disabled", text="Queued...", bg=COLORS['text_secondary'])
        
        # Add to Queue
        task_id = self.add_download_task(mod_data.get('title', 'Mod'), "mod")
        
        def run_install():
            self.root.after(0, lambda: btn_widget.config(text="Installing..."))
            success = False
            try:
                mod_id = mod_data['slug'] # or project_id or slug from search hit
                
                self.root.after(0, lambda: self.update_download_task(task_id, 0, detail="Fetching versions..."))
                
                # version request
                if mod_data.get('project_type') == 'resourcepack':
                    v_url = f"https://api.modrinth.com/v2/project/{mod_id}/version?game_versions=[%22{pack['mc_version']}%22]"
                else:
                    v_url = f"https://api.modrinth.com/v2/project/{mod_id}/version?loaders=[%22{pack['loader']}%22]&game_versions=[%22{pack['mc_version']}%22]"
                
                r = requests.get(v_url, timeout=10)
                if r.status_code != 200:
                    raise Exception(f"Failed to fetch versions: {r.status_code}")
                
                versions = r.json()
                if not versions:
                    raise Exception("No compatible version found for this modpack.")
                
                # Pick first (newest)
                best_ver = versions[0]
                files = best_ver.get('files', [])
                if not files:
                    raise Exception("No files in version.")
                    
                primary_file = next((f for f in files if f.get('primary', False)), files[0])
                download_url = primary_file['url']
                filename = primary_file['filename']
                size = primary_file.get('size', 0)
                
                # Download
                if mod_data.get('project_type') == 'resourcepack':
                    target_dir = os.path.join(self.minecraft_dir, "resourcepacks")
                else:
                    target_dir = os.path.join(self.get_modpack_dir(pack['id']), "mods")
                
                if not os.path.exists(target_dir): os.makedirs(target_dir)
                
                target_path = os.path.join(target_dir, filename)
                
                self.root.after(0, lambda: self.update_download_task(task_id, 0, detail=f"Downloading {filename}..."))
                cancel_event = self.download_tasks.get(task_id, {}).get('cancel_event')
                rate_limit = getattr(self, 'max_download_speed', 2048) if getattr(self, 'limit_download_speed_enabled', False) else 0
                _atomic_download(
                    download_url,
                    target_path,
                    cancel_event=cancel_event,
                    rate_limit_kib=rate_limit,
                    expected_sha1=(primary_file.get("hashes") or {}).get("sha1"),
                    progress=lambda current, total: self.root.after(
                        0, lambda: self.update_download_task(task_id, (current / total) * 100)
                    ) if total else None,
                )
                            
                success = True
                
                # Update Pack Meta
                # Store full info to detect duplicates
                meta = {
                    "slug": mod_id,
                    "filename": filename,
                    "version_id": best_ver['id']
                }
                
                # Remove old entry if same slug exists (updating?)
                # For now just append, user can manage files manually if needed
                pack['mods'].append(meta) 
                
                self.save_modpacks()
                
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda m=err_msg: messagebox.showerror("Error", m))
            
            # Post-Op UI Update
            def finish():
                if success:
                    self.complete_download_task(task_id)
                    btn_widget.destroy() # Remove install button (or replace with checkmark)
                else:
                    self.fail_download_task(task_id, "Download failed — retry available")
                    btn_widget.config(state="normal", text="Install", bg=COLORS['play_btn_green'])
            
            self.root.after(0, finish)
        
        self.download_manager.queue_mod(run_install, task_id)

    def _install_global_resource(self, mod_data, btn_widget):
        btn_widget.config(state="disabled", text="Queued...", bg=COLORS['text_secondary'])
        item_type = mod_data.get('project_type', 'shader')
        task_id = self.add_download_task(mod_data.get('title', 'Resource'), item_type)

        def run_install():
            self.root.after(0, lambda: btn_widget.config(text="Installing..."))
            try:
                mod_id = mod_data['slug']
                self.root.after(0, lambda: self.update_download_task(task_id, 0, detail="Fetching versions..."))
                
                v_url = f"https://api.modrinth.com/v2/project/{mod_id}/version"
                r = requests.get(v_url, timeout=10)
                if r.status_code != 200:
                    raise Exception(f"Failed to fetch versions: {r.status_code}")
                    
                versions = r.json()
                if not versions:
                    raise Exception("No versions found.")
                    
                best_ver = versions[0]
                files = best_ver.get('files', [])
                if not files:
                    raise Exception("No files in version.")
                
                primary_file = next((f for f in files if f.get('primary', False)), files[0])
                download_url = primary_file['url']
                filename = primary_file['filename']
                
                target_dir = os.path.join(self.minecraft_dir, "shaderpacks" if item_type == "shader" else "resourcepacks")
                if not os.path.exists(target_dir): os.makedirs(target_dir)
                target_path = os.path.join(target_dir, filename)
                
                self.root.after(0, lambda: self.update_download_task(task_id, 0, detail=f"Downloading {filename}..."))
                _atomic_download(
                    download_url,
                    target_path,
                    cancel_event=self.download_tasks.get(task_id, {}).get("cancel_event"),
                    expected_sha1=(primary_file.get("hashes") or {}).get("sha1"),
                )
                
                self.root.after(0, lambda: self.complete_download_task(task_id))
                self.root.after(0, lambda: btn_widget.config(text="✔ Installed", bg=COLORS['success_green'], fg="white"))
                
            except Exception as e:
                msg = str(e)
                if msg != "Cancelled":
                    self.root.after(0, lambda: self.update_download_task(task_id, status="Error", detail=msg))
                self.root.after(0, lambda: btn_widget.config(state="normal", text="Retry", bg=COLORS['error_red']))
        
        self.download_manager.queue_mod(run_install, task_id)

    def _get_modpack_version_file(self, version_data):
        try:
            files = version_data.get('files', [])
            return next(
                (f for f in files if str(f.get('filename', '')).endswith('.mrpack') and f.get('url')),
                None
            )
        except Exception:
            return None

    def _format_modpack_version_option(self, version_data):
        version_name = version_data.get('version_number') or version_data.get('name') or version_data.get('id', 'Unknown')
        game_versions = [str(v) for v in version_data.get('game_versions', []) if v]
        loaders = [str(v) for v in version_data.get('loaders', []) if v]
        published = str(version_data.get('date_published', '')).replace('T', ' ')[:16]

        meta_parts = []
        if game_versions:
            meta_parts.append(", ".join(game_versions[:2]))
        if loaders:
            meta_parts.append("/".join(loaders[:2]))
        if published:
            meta_parts.append(published)

        return version_name if not meta_parts else f"{version_name}  •  " + "  •  ".join(meta_parts)

    def _prompt_modpack_version(self, mod_data, versions):
        result = {"version": None}
        mgr = get_modal_manager(self.root)
        if not mgr:
            return None

        wait_var = tk.BooleanVar(self.root, value=False)

        def build_content(container, close_modal):
            tk.Label(
                container,
                text="Choose which version of this modpack to install.",
                font=("Segoe UI", 10),
                bg=COLORS['card_bg'],
                fg=COLORS['text_secondary'],
            ).pack(anchor="w", pady=(0, 16))

            options = [self._format_modpack_version_option(version) for version in versions]
            selected_index = {"value": 0}
            version_var = tk.StringVar(value=options[0] if options else "")

            combo = ttk.Combobox(
                container,
                textvariable=version_var,
                values=options,
                state="readonly",
                style="Launcher.TCombobox",
            )
            combo.pack(fill="x", ipady=6)
            if options:
                combo.current(0)

            detail_lbl = tk.Label(
                container,
                text="",
                font=("Segoe UI", 9),
                bg=COLORS['card_bg'],
                fg=COLORS['text_secondary'],
                justify="left",
                anchor="w",
            )
            detail_lbl.pack(fill="x", pady=(14, 0))

            def update_version_details(*_args):
                try:
                    idx = combo.current()
                except Exception:
                    idx = selected_index["value"]
                if idx is None or idx < 0 or idx >= len(versions):
                    idx = 0
                selected_index["value"] = idx
                version = versions[idx]
                mrpack_file = self._get_modpack_version_file(version)
                game_versions = ", ".join(str(v) for v in version.get('game_versions', [])[:3]) or "Unknown"
                loaders = ", ".join(str(v) for v in version.get('loaders', [])[:3]) or "Unknown"
                file_name = mrpack_file.get('filename', 'Unknown') if mrpack_file else "Missing .mrpack"
                detail_lbl.config(
                    text=f"Minecraft: {game_versions}\nLoader: {loaders}\nFile: {file_name}"
                )

            combo.bind("<<ComboboxSelected>>", update_version_details)
            update_version_details()

            btn_row = tk.Frame(container, bg=COLORS['card_bg'])
            btn_row.pack(side="bottom", fill="x", pady=(20, 0))

            def confirm_install():
                idx = selected_index["value"]
                if 0 <= idx < len(versions):
                    result["version"] = versions[idx]
                close_modal()

            self._make_btn(
                btn_row, "Cancel", style="secondary", font_size=10, command=close_modal
            ).pack(side="right")
            self._make_btn(
                btn_row, "Install", style="primary", font_size=10, bold=True, command=confirm_install
            ).pack(side="right", padx=(0, 8))

        def on_close():
            wait_var.set(True)

        mgr.show_modal(
            f"Install {mod_data.get('title', 'Modpack')}",
            build_content,
            width=560,
            height=300,
            on_close=on_close
        )
        self.root.wait_variable(wait_var)
        return result["version"]

    def _install_mr_modpack(self, mod_data, btn_widget):
        original_text = btn_widget.cget("text")
        btn_widget.config(state="disabled", text="Loading...")

        try:
            mod_id = mod_data['slug']
            v_url = f"https://api.modrinth.com/v2/project/{mod_id}/version"
            r = requests.get(v_url, headers={"User-Agent": "AmneDev/NewLauncher"}, timeout=10)
            if r.status_code != 200:
                raise Exception(f"Failed to fetch versions: {r.status_code}")

            versions = [v for v in r.json() if self._get_modpack_version_file(v)]
            if not versions:
                raise Exception("No installable .mrpack versions were found for this modpack.")

            selected_version = self._prompt_modpack_version(mod_data, versions)
            if not selected_version:
                btn_widget.config(state="normal", text=original_text, bg=COLORS['play_btn_green'])
                return
        except Exception as e:
            btn_widget.config(state="normal", text=original_text, bg=COLORS['play_btn_green'])
            custom_showerror("Error", str(e), parent=self.root)
            return

        btn_widget.config(state="disabled", text="Queued...", bg=COLORS['text_secondary'])
        task_id = self.add_download_task(mod_data['title'], "modpack")
        
        def run():
             self.root.after(0, lambda: btn_widget.config(text="Installing..."))
             self._install_mr_modpack_thread(mod_data, selected_version, btn_widget, task_id)
             
        self.download_manager.queue_modpack(run, task_id)

    def _install_mr_modpack_thread(self, mod_data, version_data, btn_widget, task_id):
        try:
             self.root.after(0, lambda: self.update_download_task(task_id, 0, detail="Fetching info..."))
             best = version_data
             
             mrpack_file = self._get_modpack_version_file(best)
             
             if not mrpack_file:
                 raise Exception("No .mrpack file found in selected version")
                 
             # Create Pack Entry
             pack_name = mod_data['title']
             mc_ver = next((str(v) for v in best.get('game_versions', []) if v), "unknown")
             loader = next((str(v) for v in best.get('loaders', []) if v), "vanilla")
             version_name = best.get('version_number') or best.get('name') or best.get('id', 'unknown')
             
             new_id = str(uuid.uuid4())
             new_pack = {
                 "id": new_id,
                 "name": pack_name,
                 "loader": loader,
                 "mc_version": mc_ver,
                 "version_id": best.get('id', ''),
                 "version_name": version_name,
                 "mods": [],
                 "linked_installation_id": None
             }
             
             # Download .mrpack to temp
             self.root.after(0, lambda: self.update_download_task(task_id, 5, detail=f"Downloading {version_name}..."))
             with tempfile.TemporaryDirectory() as temp_dir:
                 mr_path = os.path.join(temp_dir, "pack.mrpack")
                 cancel_event = self.download_tasks.get(task_id, {}).get('cancel_event')
                 _atomic_download(mrpack_file['url'], mr_path, cancel_event=cancel_event)
                         
                 # Extract
                 if task_id in self.download_tasks and self.download_tasks[task_id]['cancel_event'].is_set(): raise Exception("Cancelled")

                 self.root.after(0, lambda: self.update_download_task(task_id, 10, detail="Extracting..."))
                 _safe_extract_zip(mr_path, temp_dir)
                     
                 # Read index.json
                 index_path = os.path.join(temp_dir, "modrinth.index.json")
                 if not os.path.exists(index_path):
                     raise Exception("Invalid mrpack: No index.json")
                     
                 with open(index_path, 'r') as f:
                     idx = json.load(f)
                     
                 # Initialize isolated pack directory
                 pack_dir = os.path.abspath(self.get_modpack_dir(new_id))
                 os.makedirs(pack_dir, exist_ok=True)
                 os.makedirs(os.path.join(pack_dir, "mods"), exist_ok=True)
                 
                 files_list = idx.get('files', [])
                 total_files = len(files_list)
                 completed_files = 0
                 
                 for file_def in files_list:
                     if task_id in self.download_tasks and self.download_tasks[task_id]['cancel_event'].is_set():
                         raise Exception("Cancelled")

                     downloads = file_def.get('downloads') or []
                     d_url = downloads[0] if downloads else ""
                     f_path = str(file_def.get('path') or "").replace(chr(92), "/").lstrip("/")
                     if not f_path or not d_url:
                         completed_files += 1
                         continue

                     f_name = os.path.basename(f_path)
                     dest = os.path.abspath(os.path.join(pack_dir, f_path))
                     if os.path.commonpath((pack_dir, dest)) != pack_dir:
                         raise ValueError(f"Unsafe modpack file path: {f_path}")
                     
                     # Ensure parent dir exists
                     os.makedirs(os.path.dirname(dest), exist_ok=True)
                     
                     self.root.after(0, lambda n=f_name: self.update_download_task(task_id, detail=f"Downloading {n}"))
                     _atomic_download(
                         d_url,
                         dest,
                         cancel_event=cancel_event,
                         expected_sha1=(file_def.get("hashes") or {}).get("sha1"),
                     )
                                 
                     completed_files += 1
                     if total_files > 0:
                         prog = 10 + (completed_files / total_files * 75)
                         self.root.after(0, lambda p=prog: self.update_download_task(task_id, p))
                                 
                 # Copy overrides (config/, shaderpacks/, resourcepacks/, etc.)
                 self.root.after(0, lambda: self.update_download_task(task_id, 88, detail="Applying modpack overrides…"))
                 for override_folder in ("overrides", "client-overrides"):
                     override_dir = os.path.join(temp_dir, override_folder)
                     if os.path.isdir(override_dir):
                         for root_d, dirs, files in os.walk(override_dir):
                             rel = os.path.relpath(root_d, override_dir)
                             target_sub = os.path.abspath(os.path.join(pack_dir, rel)) if rel != "." else pack_dir
                             if os.path.commonpath((pack_dir, target_sub)) != pack_dir:
                                 continue
                             os.makedirs(target_sub, exist_ok=True)
                             for f in files:
                                 src_f = os.path.join(root_d, f)
                                 dst_f = os.path.join(target_sub, f)
                                 shutil.copy2(src_f, dst_f)
                 
                 # Add to modpacks list
                 self.root.after(0, lambda: self.complete_download_task(task_id))
                 
                 self.modpacks.append(new_pack)
                 self.save_modpacks()
                 
             self.root.after(0, lambda: [
                 self.refresh_modpacks_list(),
                 self.update_active_modpack_dropdown(),
                 btn_widget.destroy()
             ])
             
        except Exception as e:
            print(f"Modpack install error: {e}")
            err_msg = f"Failed to install pack: {e}"
            self.root.after(0, lambda m=err_msg: [
                self.update_download_task(task_id, detail="Error"),
                messagebox.showerror("Error", m),
                btn_widget.config(state="normal", text="Download")
            ])

    def _get_mod_icon_cache_dir(self):
        base_dir = getattr(self, 'config_dir', None) or os.path.join(os.path.expanduser("~"), ".nlc")
        cache_dir = os.path.join(base_dir, "cache", "mod_icons")
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

    def _fetch_and_cache_mod_icon(self, url):
        image = None
        try:
            url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
            cache_dir = self._get_mod_icon_cache_dir()
            cache_file = os.path.join(cache_dir, f"{url_hash}.png")

            # 1. Fast disk cache check (64x64 PNG reads in <1ms with near-zero RAM)
            if os.path.isfile(cache_file):
                try:
                    with Image.open(cache_file) as cached_img:
                        image = cached_img.copy()
                except Exception:
                    image = None

            # 2. Download and downscale with BILINEAR (much lighter on RAM/CPU than LANCZOS)
            if image is None:
                session = get_http_session()
                resp = session.get(url, timeout=5, headers={"User-Agent": "AmneDev/NewLauncher"})
                if resp.status_code == 200:
                    with Image.open(io.BytesIO(resp.content)) as source:
                        image = source.convert("RGBA").resize((64, 64), Image.Resampling.BILINEAR)
                    try:
                        temp_fd, temp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
                        os.close(temp_fd)
                        image.save(temp_path, format="PNG")
                        os.replace(temp_path, cache_file)
                    except Exception as exc:
                        logger.debug("Failed saving mod icon to disk cache: %s", exc)

            if image is not None:
                def update_ui():
                    self.mod_image_loading.discard(url)
                    try:
                        photo = ImageTk.PhotoImage(image)
                        # Cap in-memory image cache to 120 items to prevent unbounded memory growth
                        if len(self.cached_mod_images) >= 120:
                            oldest_key = next(iter(self.cached_mod_images))
                            del self.cached_mod_images[oldest_key]
                        self.cached_mod_images[url] = photo
                        for waiting_label in self.mod_image_waiters.pop(url, []):
                            if waiting_label.winfo_exists():
                                waiting_label.config(image=photo, text="", width=64, height=64)
                    except (tk.TclError, AttributeError):
                        pass

                self.root.after(0, update_ui)
                return
        except (requests.RequestException, OSError, ValueError) as exc:
            logger.debug("Could not load Modrinth icon %s: %s", url, exc)
        finally:
            if url in self.mod_image_loading:
                try:
                    self.root.after(0, lambda: (self.mod_image_loading.discard(url), self.mod_image_waiters.pop(url, None)))
                except (tk.TclError, AttributeError):
                    pass

    def _load_mod_icon_async(self, url, label):
        if url in self.cached_mod_images:
            label.config(image=self.cached_mod_images[url], text="", width=64, height=64)
            return
        if url in self.mod_image_loading:
            self.mod_image_waiters.setdefault(url, []).append(label)
            return
        self.mod_image_loading.add(url)
        self.mod_image_waiters[url] = [label]

        _MOD_ICON_POOL.submit(self._fetch_and_cache_mod_icon, url)

    def close_project_details(self):
        """Return from project details view back to browse search results."""
        self._in_mod_details = False
        if hasattr(self, 'mods_detail_view') and self.mods_detail_view.winfo_exists():
            self.mods_detail_view.pack_forget()
        if hasattr(self, 'mods_browse_view') and self.mods_browse_view.winfo_exists():
            self.mods_browse_view.pack(fill="both", expand=True)

    def show_project_details(self, mod):
        """Open the in-place details view for a mod/modpack/resource pack/shader."""
        self._in_mod_details = True
        if hasattr(self, 'mods_browse_view') and self.mods_browse_view.winfo_exists():
            self.mods_browse_view.pack_forget()

        if not hasattr(self, 'mods_detail_view') or not self.mods_detail_view.winfo_exists():
            self.mods_detail_view = tk.Frame(self.tabs["Mods"], bg=COLORS['main_bg'])
        self.mods_detail_view.pack(fill="both", expand=True)

        for w in self.mods_detail_view.winfo_children():
            w.destroy()

        main_bg = COLORS['main_bg']
        card_bg = COLORS['card_bg']
        input_bg = COLORS.get('input_bg', '#1E222B')
        text_primary = COLORS['text_primary']
        text_secondary = COLORS.get('text_secondary', '#A0AAB0')

        # Top Bar
        top_bar = tk.Frame(self.mods_detail_view, bg=main_bg, pady=10, padx=20)
        top_bar.pack(fill="x")
        self.detail_top_bar = top_bar

        back_btn = self._make_btn(top_bar, "← Back to Results", style="secondary", font_size=10, bold=True,
                                   command=self.close_project_details)
        back_btn.pack(side="left")

        project_type = mod.get('project_type', 'mod')
        slug = mod.get('slug', '')
        web_url = f"https://modrinth.com/{project_type}/{slug}" if slug else "https://modrinth.com"

        self._make_btn(top_bar, "View on Modrinth ↗", style="secondary", font_size=9,
                       command=lambda u=web_url: webbrowser.open(u)).pack(side="right")

        type_lbl = tk.Label(top_bar, text=project_type.upper(), font=(FONT_FAMILY, 9, "bold"),
                            bg=input_bg, fg=text_secondary, padx=8, pady=3)
        type_lbl.pack(side="right", padx=10)

        # Scrollable area
        canvas = tk.Canvas(self.mods_detail_view, bg=main_bg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.mods_detail_view, orient="vertical", command=canvas.yview, style="Launcher.Vertical.TScrollbar")
        content_frame = tk.Frame(canvas, bg=main_bg)

        content_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=content_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.detail_canvas = canvas
        self.detail_scrollbar = scrollbar
        self.detail_scrollable_frame = content_frame

        self._bind_wheel_events(canvas, lambda e, c=canvas: self._smooth_scroll(c, e), f"detail_{id(canvas)}")
        self._bind_smooth_scroll(canvas, content_frame)

        # Hero Card
        hero_card = tk.Frame(content_frame, bg=card_bg, padx=20, pady=20)
        hero_card.pack(fill="x", padx=20, pady=(10, 15))
        self.detail_hero_card = hero_card

        # Icon
        icon_lbl = tk.Label(hero_card, text="?", bg=input_bg, fg="white", width=8, height=4)
        icon_lbl.pack(side="left", padx=(0, 20), anchor="n")
        icon_url = mod.get("icon_url")
        if icon_url:
            self._load_mod_icon_async(icon_url, icon_lbl)

        # Meta & Info
        info_frame = tk.Frame(hero_card, bg=card_bg)
        info_frame.pack(side="left", fill="both", expand=True)

        tk.Label(info_frame, text=mod.get("title", "Unknown"), font=(FONT_FAMILY, 16, "bold"),
                 fg="white", bg=card_bg, anchor="w", justify="left").pack(fill="x")

        author = mod.get("author", "Unknown")
        tk.Label(info_frame, text=f"By {author}", font=(FONT_FAMILY, 9),
                 fg=text_secondary, bg=card_bg, anchor="w").pack(fill="x", pady=(2, 6))

        summary = mod.get("description", "")
        tk.Label(info_frame, text=summary, font=(FONT_FAMILY, 10),
                 fg=text_primary, bg=card_bg, anchor="w", justify="left", wraplength=560).pack(fill="x", pady=(0, 10))

        # Stats chips
        stats_frame = tk.Frame(info_frame, bg=card_bg)
        stats_frame.pack(fill="x", anchor="w")

        downloads = mod.get("downloads", 0)
        dl_str = f"📥 {downloads:,} downloads" if isinstance(downloads, int) else f"📥 {downloads} downloads"
        tk.Label(stats_frame, text=dl_str, font=(FONT_FAMILY, 9), bg=input_bg, fg=text_secondary, padx=8, pady=3).pack(side="left", padx=(0, 8))

        follows = mod.get("follows", 0)
        if follows:
            tk.Label(stats_frame, text=f"⭐ {follows:,} followers", font=(FONT_FAMILY, 9), bg=input_bg, fg=text_secondary, padx=8, pady=3).pack(side="left", padx=(0, 8))

        # Hero Actions Frame
        hero_btn_frame = tk.Frame(hero_card, bg=card_bg)
        hero_btn_frame.pack(side="right", padx=(15, 0), anchor="center")

        if project_type == 'modpack':
            btn = self._make_btn(hero_btn_frame, "Download Modpack", style="primary", font_size=10, bold=True)
            btn.pack(side="top", pady=4)
            btn.config(command=lambda m=mod, b=btn: self._install_mr_modpack(m, b))
        elif project_type in ['resourcepack', 'shader']:
            name_action = "Install Resource Pack" if project_type == 'resourcepack' else "Install Shader"
            btn = self._make_btn(hero_btn_frame, name_action, style="primary", font_size=10, bold=True)
            btn.pack(side="top", pady=4)
            btn.config(command=lambda m=mod, b=btn: self._install_global_resource(m, b))
        else:
            active_pack_name = self.active_modpack_var.get()
            if active_pack_name != "None":
                pack = next((p for p in self.modpacks if p['name'] == active_pack_name), None)
                is_installed = False
                if pack:
                    mod_slug = mod.get('slug')
                    if any(m.get('slug') == mod_slug for m in pack['mods']):
                        is_installed = True
                if is_installed:
                    tk.Label(hero_btn_frame, text="✔ Installed in Pack", font=(FONT_FAMILY, 10, "bold"),
                             fg=COLORS['success_green'], bg=card_bg).pack(side="top", pady=4)
                else:
                    btn = self._make_btn(hero_btn_frame, f"Install to {active_pack_name}", style="primary", font_size=10, bold=True)
                    btn.pack(side="top", pady=4)
                    btn.config(command=lambda b=btn, m=mod, p=active_pack_name: self._install_mod_to_pack(m, p, b))
            else:
                tk.Label(hero_btn_frame, text="(Select a modpack in the browse view to install)", font=(FONT_FAMILY, 9),
                         fg=text_secondary, bg=card_bg).pack(side="top", pady=4)

        # Loading placeholder
        loading_lbl = tk.Label(content_frame, text="Loading screenshots, description, and details...",
                               font=(FONT_FAMILY, 11), fg=text_secondary, bg=main_bg)
        loading_lbl.pack(pady=30)
        self.detail_loading_lbl = loading_lbl

        # Async Worker
        project_id_or_slug = mod.get("slug") or mod.get("project_id") or mod.get("id")
        _MOD_ICON_POOL.submit(self._fetch_project_details_worker, project_id_or_slug, project_type, mod, loading_lbl)

    def _fetch_project_details_worker(self, project_id_or_slug, project_type, mod_summary, loading_lbl):
        base_dir = getattr(self, 'config_dir', None) or os.path.join(os.path.expanduser("~"), ".nlc")
        cache_dir = os.path.join(base_dir, "cache", "projects")
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"{project_id_or_slug}.json")

        project_data = None
        if os.path.isfile(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                if time.time() - mtime < 900:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        project_data = json.load(f)
            except Exception:
                project_data = None

        if not project_data:
            try:
                session = get_http_session()
                url = f"https://api.modrinth.com/v2/project/{project_id_or_slug}"
                resp = session.get(url, headers={"User-Agent": "AmneDev/NewLauncher"}, timeout=12)
                if resp.status_code == 200:
                    project_data = resp.json()
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(project_data, f)
            except Exception as e:
                logger.debug("Failed fetching project details for %s: %s", project_id_or_slug, e)

        included_mods = []
        if project_type == "modpack":
            included_mods = self._extract_modpack_mods(project_id_or_slug)

        self.root.after(0, lambda: self._populate_project_details(project_data, included_mods, mod_summary, loading_lbl))

    def _extract_modpack_mods(self, project_id_or_slug):
        base_dir = getattr(self, 'config_dir', None) or os.path.join(os.path.expanduser("~"), ".nlc")
        cache_dir = os.path.join(base_dir, "cache", "modpack_mods")
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"{project_id_or_slug}.json")

        if os.path.isfile(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        mods = []
        try:
            session = get_http_session()
            v_url = f"https://api.modrinth.com/v2/project/{project_id_or_slug}/version"
            v_resp = session.get(v_url, headers={"User-Agent": "AmneDev/NewLauncher"}, timeout=12)
            if v_resp.status_code == 200:
                versions = v_resp.json()
                if versions:
                    best_ver = versions[0]
                    mr_file = next((f for f in best_ver.get('files', []) if f.get('filename', '').endswith('.mrpack')), None)
                    if mr_file:
                        mr_resp = session.get(mr_file['url'], headers={"User-Agent": "AmneDev/NewLauncher"}, timeout=20)
                        if mr_resp.status_code == 200:
                            with zipfile.ZipFile(io.BytesIO(mr_resp.content)) as z:
                                if "modrinth.index.json" in z.namelist():
                                    idx_data = json.loads(z.read("modrinth.index.json"))
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
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(mods, f)
        except Exception as exc:
            logger.debug("Failed extracting modpack mods for %s: %s", project_id_or_slug, exc)
        return mods

    def _populate_project_details(self, project_data, included_mods, mod_summary, loading_lbl):
        if not getattr(self, '_in_mod_details', False):
            return
        if not hasattr(self, 'detail_scrollable_frame') or not self.detail_scrollable_frame.winfo_exists():
            return

        if loading_lbl and loading_lbl.winfo_exists():
            loading_lbl.destroy()

        data = project_data or mod_summary
        content_frame = self.detail_scrollable_frame
        card_bg = COLORS['card_bg']
        main_bg = COLORS['main_bg']
        input_bg = COLORS.get('input_bg', '#1E222B')
        text_primary = COLORS['text_primary']
        text_secondary = COLORS.get('text_secondary', '#A0AAB0')

        # 1. GALLERY SECTION (Preceding description as requested)
        gallery = data.get("gallery", [])
        if gallery:
            gal_sec = tk.Frame(content_frame, bg=card_bg, padx=20, pady=15)
            gal_sec.pack(fill="x", padx=20, pady=(0, 15))
            self.detail_gallery_section = gal_sec

            tk.Label(gal_sec, text=f"📸 Screenshots & Gallery ({len(gallery)})", font=(FONT_FAMILY, 13, "bold"),
                     fg=text_primary, bg=card_bg, anchor="w").pack(fill="x", pady=(0, 10))

            cards_frame = tk.Frame(gal_sec, bg=card_bg)
            cards_frame.pack(fill="x", anchor="w")

            for idx, item in enumerate(gallery[:10]):
                item_card = tk.Frame(cards_frame, bg=input_bg, padx=5, pady=5, cursor="hand2")
                item_card.pack(side="left", padx=6, pady=4)

                img_lbl = tk.Label(item_card, text="Loading image...", bg=input_bg, fg=text_secondary,
                                   width=24, height=6, cursor="hand2")
                img_lbl.pack()

                title_text = item.get("title") or f"Image {idx+1}"
                if len(title_text) > 24: title_text = title_text[:21] + "..."
                tk.Label(item_card, text=title_text, font=(FONT_FAMILY, 8), bg=input_bg,
                         fg=text_primary, cursor="hand2").pack(pady=(4, 0))

                def make_click(i=idx):
                    return lambda e: self._open_gallery_lightbox(gallery, i)

                item_card.bind("<Button-1>", make_click(idx))
                img_lbl.bind("<Button-1>", make_click(idx))

                img_url = item.get("url") or item.get("raw_url")
                if img_url:
                    self._load_gallery_thumbnail_async(img_url, img_lbl)

        # 2. INCLUDED MODS SECTION (Modpacks only)
        if data.get("project_type") == "modpack" and included_mods:
            mods_sec = tk.Frame(content_frame, bg=card_bg, padx=20, pady=15)
            mods_sec.pack(fill="x", padx=20, pady=(0, 15))
            self.detail_mods_section = mods_sec

            header_frame = tk.Frame(mods_sec, bg=card_bg)
            header_frame.pack(fill="x", pady=(0, 10))

            tk.Label(header_frame, text=f"📦 Included Mods ({len(included_mods)} mods)",
                     font=(FONT_FAMILY, 13, "bold"), fg=text_primary, bg=card_bg).pack(side="left")

            filter_var = tk.StringVar()
            filter_entry = tk.Entry(header_frame, textvariable=filter_var, font=(FONT_FAMILY, 9),
                                    bg=input_bg, fg=text_primary, insertbackground="white", width=20)
            filter_entry.pack(side="right")
            tk.Label(header_frame, text="Filter: ", font=(FONT_FAMILY, 9), fg=text_secondary, bg=card_bg).pack(side="right")

            list_container = tk.Frame(mods_sec, bg=input_bg, padx=10, pady=10)
            list_container.pack(fill="x")

            row_widgets = []
            for m in included_mods:
                row = tk.Frame(list_container, bg=input_bg)
                row.pack(fill="x", pady=2)
                row._mod_name = m["name"].lower()
                lbl_name = tk.Label(row, text=f"• {m['name']}", font=(FONT_FAMILY, 9), fg=text_primary, bg=input_bg, anchor="w")
                lbl_name.pack(side="left")
                if m.get("size"):
                    lbl_size = tk.Label(row, text=m["size"], font=(FONT_FAMILY, 8), fg=text_secondary, bg=input_bg)
                    lbl_size.pack(side="right")
                row_widgets.append(row)

            def on_filter_change(*args):
                q = filter_var.get().strip().lower()
                for r in row_widgets:
                    if not q or q in r._mod_name:
                        r.pack(fill="x", pady=2)
                    else:
                        r.pack_forget()

            filter_var.trace_add("write", on_filter_change)

        # 3. DESCRIPTION SECTION
        desc_sec = tk.Frame(content_frame, bg=card_bg, padx=20, pady=20)
        desc_sec.pack(fill="x", padx=20, pady=(0, 20))
        self.detail_desc_section = desc_sec

        tk.Label(desc_sec, text="📝 Description", font=(FONT_FAMILY, 13, "bold"),
                 fg=text_primary, bg=card_bg, anchor="w").pack(fill="x", pady=(0, 10))

        body_text = data.get("body") or data.get("description", "No description provided.")
        text_widget = tk.Text(desc_sec, wrap="word", bg=card_bg, fg=text_primary, relief="flat",
                              highlightthickness=0, font=(FONT_FAMILY, 10))
        text_widget.pack(fill="both", expand=True)
        self.detail_text_widget = text_widget

        self._render_markdown_to_text(text_widget, body_text)

        content_lines = max(8, min(len(body_text.splitlines()) + 8, 35))
        text_widget.config(height=content_lines)

        content_frame.update_idletasks()
        self.detail_canvas.configure(scrollregion=self.detail_canvas.bbox("all"))

    def _get_gallery_cache_dir(self):
        base_dir = getattr(self, 'config_dir', None) or os.path.join(os.path.expanduser("~"), ".nlc")
        cache_dir = os.path.join(base_dir, "cache", "gallery")
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

    def _load_gallery_thumbnail_async(self, url, label):
        if hasattr(self, 'cached_gallery_images') and url in self.cached_gallery_images:
            if label.winfo_exists():
                label.config(image=self.cached_gallery_images[url], text="", width=240, height=135)
            return

        cache_dir = self._get_gallery_cache_dir()
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        cache_file = os.path.join(cache_dir, f"{url_hash}.png")

        def fetch():
            image = None
            if os.path.isfile(cache_file):
                try:
                    with Image.open(cache_file) as cached_img:
                        image = cached_img.copy()
                except Exception:
                    image = None
            if image is None:
                try:
                    session = get_http_session()
                    resp = session.get(url, timeout=8, headers={"User-Agent": "AmneDev/NewLauncher"})
                    if resp.status_code == 200:
                        with Image.open(io.BytesIO(resp.content)) as src:
                            thumb = src.convert("RGBA")
                            thumb.thumbnail((240, 135), Image.Resampling.BILINEAR)
                            image = thumb
                        temp_fd, temp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
                        os.close(temp_fd)
                        image.save(temp_path, format="PNG")
                        os.replace(temp_path, cache_file)
                except Exception as exc:
                    logger.debug("Failed loading gallery image %s: %s", url, exc)

            if image is not None:
                def update_ui():
                    try:
                        photo = ImageTk.PhotoImage(image)
                        if not hasattr(self, 'cached_gallery_images'):
                            self.cached_gallery_images = {}
                        if len(self.cached_gallery_images) >= 60:
                            oldest = next(iter(self.cached_gallery_images))
                            del self.cached_gallery_images[oldest]
                        self.cached_gallery_images[url] = photo
                        if label.winfo_exists():
                            label.config(image=photo, text="", width=240, height=135)
                    except (tk.TclError, AttributeError):
                        pass
                self.root.after(0, update_ui)

        _MOD_ICON_POOL.submit(fetch)

    def _open_gallery_lightbox(self, gallery, initial_index=0):
        if not gallery: return
        dialog_bg = COLORS.get('sidebar_bg', '#12141A')
        card_bg = COLORS.get('main_bg', '#181A20')
        dialog_text_sec = COLORS.get('text_secondary', '#A0AAB0')
        dialog_text_pri = COLORS['text_primary']

        # Centered Card Frame directly on self.root (no full-screen opaque blackout)
        card = tk.Frame(self.root, bg=dialog_bg, highlightbackground=COLORS.get('accent_color', '#2ECC71'), highlightthickness=2)
        card.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.88, relheight=0.88)
        card.lift()

        # Top Bar with Title and Close (✕)
        top_bar = tk.Frame(card, bg=dialog_bg, padx=16, pady=10)
        top_bar.pack(side="top", fill="x")

        title_lbl = tk.Label(top_bar, text="", font=(FONT_FAMILY, 11, "bold"), fg=dialog_text_pri, bg=dialog_bg)
        title_lbl.pack(side="left")

        def close_lightbox():
            try:
                card.grab_release()
            except Exception:
                pass
            if card.winfo_exists():
                card.place_forget()
                card.destroy()

        close_btn = tk.Label(top_bar, text="✕", font=(FONT_FAMILY, 11, "bold"), bg=dialog_bg, fg=dialog_text_sec, cursor="hand2", padx=8)
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda _e: close_lightbox())
        close_btn.bind("<Enter>", lambda _e: close_btn.config(fg="white"))
        close_btn.bind("<Leave>", lambda _e: close_btn.config(fg=dialog_text_sec))

        # Main image preview area
        content_box = tk.Frame(card, bg=card_bg)
        content_box.pack(expand=True, fill="both", padx=16, pady=(0, 10))

        img_lbl = tk.Label(content_box, text="Loading full image...", bg=card_bg, fg=dialog_text_sec)
        img_lbl.pack(expand=True, fill="both", padx=10, pady=10)

        # Bottom Bar with Counter, Previous, Next
        bottom_bar = tk.Frame(card, bg=dialog_bg, pady=10, padx=16)
        bottom_bar.pack(side="bottom", fill="x")

        counter_lbl = tk.Label(bottom_bar, text="", font=(FONT_FAMILY, 9), fg=dialog_text_sec, bg=dialog_bg)
        counter_lbl.pack(side="left")

        btn_box = tk.Frame(bottom_bar, bg=dialog_bg)
        btn_box.pack(side="right")

        current_idx = [initial_index]

        def show_current():
            idx = current_idx[0]
            item = gallery[idx]
            title_lbl.config(text=item.get("title") or f"Screenshot {idx+1}")
            counter_lbl.config(text=f"Image {idx + 1} of {len(gallery)}")
            img_lbl.config(image="", text="Loading...")

            img_url = item.get("raw_url") or item.get("url")
            def load_full():
                try:
                    session = get_http_session()
                    resp = session.get(img_url, timeout=10, headers={"User-Agent": "AmneDev/NewLauncher"})
                    if resp.status_code == 200:
                        with Image.open(io.BytesIO(resp.content)) as src:
                            full = src.convert("RGBA")
                            cw = max(400, content_box.winfo_width() - 40)
                            ch = max(300, content_box.winfo_height() - 40)
                            full.thumbnail((cw, ch), Image.Resampling.BILINEAR)
                        def set_full():
                            if card.winfo_exists() and img_lbl.winfo_exists():
                                photo = ImageTk.PhotoImage(full)
                                img_lbl.config(image=photo, text="")
                                img_lbl.image = photo  # type: ignore[attr-defined]
                        self.root.after(0, set_full)
                except Exception as exc:
                    logger.debug("Failed loading lightbox image %s: %s", img_url, exc)
            _MOD_ICON_POOL.submit(load_full)

        def prev_img():
            if current_idx[0] > 0:
                current_idx[0] -= 1
                show_current()

        def next_img():
            if current_idx[0] < len(gallery) - 1:
                current_idx[0] += 1
                show_current()

        self._make_btn(btn_box, "◀ Previous", style="secondary", font_size=9, command=prev_img).pack(side="left", padx=4)
        self._make_btn(btn_box, "Next ▶", style="secondary", font_size=9, command=next_img).pack(side="left", padx=4)
        self._make_btn(btn_box, "Close", style="primary", font_size=9, command=close_lightbox).pack(side="left", padx=(8, 0))

        def on_outside_click(event):
            if not card.winfo_exists():
                return
            try:
                cx = card.winfo_rootx()
                cy = card.winfo_rooty()
                cw = card.winfo_width()
                ch = card.winfo_height()
                if not (cx <= event.x_root <= cx + cw and cy <= event.y_root <= cy + ch):
                    close_lightbox()
            except Exception:
                pass

        card.bind_all("<Button-1>", on_outside_click, add="+")
        card.bind("<Escape>", lambda _e: close_lightbox())
        card.bind("<Left>", lambda _e: prev_img())
        card.bind("<Right>", lambda _e: next_img())
        try:
            card.grab_set()
        except Exception:
            pass
        card.focus_set()

        show_current()

    def _render_markdown_to_text(self, text_widget, markdown_text):
        text_widget.config(state="normal")
        text_widget.delete("1.0", tk.END)

        main_bg = COLORS['main_bg']
        card_bg = COLORS['card_bg']
        input_bg = COLORS.get('input_bg', '#1E222B')
        text_primary = COLORS['text_primary']
        accent_blue = COLORS.get('accent_blue', '#3498DB')
        accent_color = COLORS.get('accent_color', COLORS.get('play_btn_green', '#2D8F36'))

        text_widget.tag_configure("h1", font=(FONT_FAMILY, 14, "bold"), foreground=text_primary, spacing1=12, spacing3=4)
        text_widget.tag_configure("h2", font=(FONT_FAMILY, 12, "bold"), foreground=accent_color, spacing1=10, spacing3=3)
        text_widget.tag_configure("h3", font=(FONT_FAMILY, 11, "bold"), foreground=text_primary, spacing1=8, spacing3=2)
        text_widget.tag_configure("bullet", font=(FONT_FAMILY, 10), lmargin1=15, lmargin2=25, foreground=text_primary)
        text_widget.tag_configure("bold", font=(FONT_FAMILY, 10, "bold"), foreground=text_primary)
        text_widget.tag_configure("italic", font=(FONT_FAMILY, 10, "italic"), foreground=text_primary)
        text_widget.tag_configure("code", font=("Consolas", 9), background=input_bg, foreground=COLORS.get('warning_orange', '#F59E0B'))
        text_widget.tag_configure("normal", font=(FONT_FAMILY, 10), foreground=text_primary)

        link_counter = 0
        inline_pattern = re.compile(r"(\[.*?\]\(.*?\)|\*\*.*?\*\*|`.*?`|\*.*?\*)")

        for line in markdown_text.splitlines():
            s = line.strip()
            if not s:
                text_widget.insert(tk.END, "\n")
                continue

            if s.startswith("# "):
                text_widget.insert(tk.END, s[2:] + "\n", "h1")
            elif s.startswith("## "):
                text_widget.insert(tk.END, s[3:] + "\n", "h2")
            elif s.startswith("### "):
                text_widget.insert(tk.END, s[4:] + "\n", "h3")
            elif s.startswith(("- ", "* ")):
                text_widget.insert(tk.END, "• ", "bullet")
                content = s[2:]
                parts = inline_pattern.split(content)
                for p in parts:
                    if not p: continue
                    if p.startswith("[") and "](" in p and p.endswith(")"):
                        m = re.match(r"\[(.*?)\]\((.*?)\)", p)
                        if m:
                            lt, lu = m.group(1), m.group(2)
                            tag = f"link_{link_counter}"
                            link_counter += 1
                            text_widget.tag_configure(tag, font=(FONT_FAMILY, 10, "underline"), foreground=accent_blue)
                            text_widget.tag_bind(tag, "<Button-1>", lambda e, u=lu: webbrowser.open(u))
                            text_widget.tag_bind(tag, "<Enter>", lambda e: text_widget.config(cursor="hand2"))
                            text_widget.tag_bind(tag, "<Leave>", lambda e: text_widget.config(cursor="arrow"))
                            text_widget.insert(tk.END, lt, (tag, "bullet"))
                        else:
                            text_widget.insert(tk.END, p, "bullet")
                    elif p.startswith("**") and p.endswith("**") and len(p) >= 4:
                        text_widget.insert(tk.END, p[2:-2], ("bold", "bullet"))
                    elif p.startswith("`") and p.endswith("`") and len(p) >= 2:
                        text_widget.insert(tk.END, p[1:-1], ("code", "bullet"))
                    elif p.startswith("*") and p.endswith("*") and len(p) >= 2:
                        text_widget.insert(tk.END, p[1:-1], ("italic", "bullet"))
                    else:
                        text_widget.insert(tk.END, p, "bullet")
                text_widget.insert(tk.END, "\n")
            else:
                parts = inline_pattern.split(line)
                for p in parts:
                    if not p: continue
                    if p.startswith("[") and "](" in p and p.endswith(")"):
                        m = re.match(r"\[(.*?)\]\((.*?)\)", p)
                        if m:
                            lt, lu = m.group(1), m.group(2)
                            tag = f"link_{link_counter}"
                            link_counter += 1
                            text_widget.tag_configure(tag, font=(FONT_FAMILY, 10, "underline"), foreground=accent_blue)
                            text_widget.tag_bind(tag, "<Button-1>", lambda e, u=lu: webbrowser.open(u))
                            text_widget.tag_bind(tag, "<Enter>", lambda e: text_widget.config(cursor="hand2"))
                            text_widget.tag_bind(tag, "<Leave>", lambda e: text_widget.config(cursor="arrow"))
                            text_widget.insert(tk.END, lt, tag)
                        else:
                            text_widget.insert(tk.END, p, "normal")
                    elif p.startswith("**") and p.endswith("**") and len(p) >= 4:
                        text_widget.insert(tk.END, p[2:-2], "bold")
                    elif p.startswith("`") and p.endswith("`") and len(p) >= 2:
                        text_widget.insert(tk.END, p[1:-1], "code")
                    elif p.startswith("*") and p.endswith("*") and len(p) >= 2:
                        text_widget.insert(tk.END, p[1:-1], "italic")
                    else:
                        text_widget.insert(tk.END, p, "normal")
                text_widget.insert(tk.END, "\n")

        text_widget.config(state="disabled")


