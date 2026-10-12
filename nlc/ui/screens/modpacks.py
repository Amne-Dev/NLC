"""
nlc.ui.screens.modpacks - Modpacks management screen and dialogs
"""

import os
import sys
import json
import uuid
import shutil
import zipfile
import logging
import threading
import tempfile
import urllib.parse
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import requests
import minecraft_launcher_lib

from nlc.storage.paths import resource_path, open_path_in_system
from nlc.ui.theme import COLORS, FONT_FAMILY
from nlc.ui.components.dialogs import custom_showinfo, custom_showerror, custom_askyesno, _schedule_window_centering
from nlc.ui.components.modal import get_modal_manager
from nlc.ui.components.context_menu import NeoContextMenu, attach_context_menu
from nlc.net.http import get_http_session
from nlc.net.downloader import _atomic_download
from nlc.core.launch import safe_extract_zip as _safe_extract_zip
from nlc.core.instances import export_modpack_to_mrpack, export_modpack_to_zip
from nlc.net.mod_icons import get_mod_icon_manager

logger = logging.getLogger(__name__)

class ModpacksScreenMixin:
    """Mixin providing Modpacks tab, CurseForge import, and modpack linking dialogs."""
    def create_modpacks_tab(self):
        container = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Modpacks"] = container

        browse_view = tk.Frame(container, bg=COLORS['main_bg'])
        browse_view.pack(fill="both", expand=True)
        self.modpacks_browse_view = browse_view
        
        # Top Bar
        top_bar = tk.Frame(browse_view, bg=COLORS['main_bg'], pady=15, padx=20)
        top_bar.pack(fill="x")
        self.mp_top_bar = top_bar
        
        self.mp_title_lbl = tk.Label(top_bar, text="My Modpacks", font=("Segoe UI", 16, "bold"), 
                 bg=COLORS['main_bg'], fg=COLORS['text_primary'])
        self.mp_title_lbl.pack(side="left")
                 
        create_mp_btn = self._make_btn(top_bar, "+ Create New Modpack", style="primary",
                                         font_size=10, bold=True, command=self.show_create_modpack_page)
        create_mp_btn.pack(side="right")
        self._make_btn(
            top_bar,
            "Import CurseForge Pack",
            style="secondary",
            font_size=10,
            command=self.show_import_curseforge_dialog,
        ).pack(side="right", padx=(0, 8))

        # Config Warning
        self.mp_empty_lbl = None
        if not self.modpacks:
            self.mp_empty_lbl = tk.Label(browse_view, text="Create a modpack to get started!", 
                    font=("Segoe UI", 12), fg=COLORS['text_secondary'], bg=COLORS['main_bg'])
            self.mp_empty_lbl.pack(pady=40)
        
        # Scrollable Area
        self.mp_canvas = tk.Canvas(browse_view, bg=COLORS['main_bg'], highlightthickness=0)
        self.mp_scrollbar = ttk.Scrollbar(browse_view, orient="vertical", command=self.mp_canvas.yview, style="Launcher.Vertical.TScrollbar")
        self.mp_scrollable_frame = tk.Frame(self.mp_canvas, bg=COLORS['main_bg'])
        
        self.mp_scrollable_frame.bind(
            "<Configure>",
            lambda e: self.mp_canvas.configure(scrollregion=self.mp_canvas.bbox("all"))
        )
        
        self.mp_canvas_window = self.mp_canvas.create_window((0, 0), window=self.mp_scrollable_frame, anchor="nw")
        
        def on_canvas_configure(event):
            self.mp_canvas.itemconfig(self.mp_canvas_window, width=event.width)
            
        self.mp_canvas.bind("<Configure>", on_canvas_configure)
        self.mp_canvas.configure(yscrollcommand=self.mp_scrollbar.set)
        
        self.mp_canvas.pack(side="left", fill="both", expand=True)
        # Scrollbar visibility managed in refresh
        
        # Smooth mousewheel
        self._bind_wheel_events(self.mp_canvas, lambda e, c=self.mp_canvas: self._smooth_scroll(c, e), f"direct_{id(self.mp_canvas)}")
        container.bind("<Enter>", lambda e: self._bind_smooth_scroll(self.mp_canvas, self.mp_scrollable_frame))
        self.mp_canvas.bind("<Enter>", lambda e: self._bind_smooth_scroll(self.mp_canvas, self.mp_scrollable_frame))
        self.mp_scrollable_frame.bind("<Enter>", lambda e: self._bind_smooth_scroll(self.mp_canvas, self.mp_scrollable_frame))
        
        self.refresh_modpacks_list()

    def refresh_modpacks_screen_theme(self):
        """Update Modpacks tab chrome, scroll frames, and items with current theme."""
        main_bg = COLORS['main_bg']
        text_primary = COLORS['text_primary']
        text_secondary = COLORS.get('text_secondary', '#A0AAB0')
        card_bg = COLORS.get('card_bg', '#2A2D32')

        if hasattr(self, 'tabs') and "Modpacks" in self.tabs:
            tab = self.tabs["Modpacks"]
            if tab and tab.winfo_exists():
                tab.config(bg=main_bg)

        if hasattr(self, 'modpacks_browse_view') and self.modpacks_browse_view.winfo_exists():
            self.modpacks_browse_view.config(bg=main_bg)

        if hasattr(self, 'mp_top_bar') and self.mp_top_bar.winfo_exists():
            self.mp_top_bar.config(bg=main_bg)

        if hasattr(self, 'mp_title_lbl') and self.mp_title_lbl.winfo_exists():
            self.mp_title_lbl.config(bg=main_bg, fg=text_primary)

        if hasattr(self, 'mp_empty_lbl') and self.mp_empty_lbl and self.mp_empty_lbl.winfo_exists():
            self.mp_empty_lbl.config(bg=main_bg, fg=text_secondary)

        if hasattr(self, 'mp_canvas') and self.mp_canvas.winfo_exists():
            self.mp_canvas.config(bg=main_bg)

        if hasattr(self, 'mp_scrollable_frame') and self.mp_scrollable_frame.winfo_exists():
            self.mp_scrollable_frame.config(bg=main_bg)

        # Update in-place create view if open
        if getattr(self, '_in_modpack_create_view', False):
            if hasattr(self, 'modpack_create_view') and self.modpack_create_view.winfo_exists():
                self.modpack_create_view.config(bg=main_bg)
            if hasattr(self, 'mp_create_header') and self.mp_create_header.winfo_exists():
                self.mp_create_header.config(bg=main_bg)
            if hasattr(self, 'mp_create_title_lbl') and self.mp_create_title_lbl.winfo_exists():
                self.mp_create_title_lbl.config(bg=main_bg, fg=text_primary)
            if hasattr(self, 'mp_create_card') and self.mp_create_card.winfo_exists():
                self.mp_create_card.config(bg=card_bg)

        # Update in-place details view if open
        if getattr(self, '_in_modpack_details_view', False):
            if hasattr(self, 'modpack_details_view') and self.modpack_details_view.winfo_exists():
                self.modpack_details_view.config(bg=main_bg)

        if hasattr(self, 'refresh_modpacks_list'):
            self.refresh_modpacks_list()

    def refresh_modpacks_list(self):
        for w in self.mp_scrollable_frame.winfo_children(): w.destroy()
        
        # Show/Hide Scrollbar based on content
        # Note: We need to let it pack first to know height, but for now we can just check count
        # A simpler way is to always check bbox after update
        
        if not self.modpacks:
            self.mp_scrollbar.pack_forget()
            return

        for i, pack in enumerate(self.modpacks):
            self._create_modpack_item(pack, i)
            
        self.mp_scrollable_frame.update_idletasks()
        self._bind_smooth_scroll(self.mp_canvas, self.mp_scrollable_frame)
        try:
            bbox = self.mp_canvas.bbox("all")
            if bbox and (bbox[3] - bbox[1]) > self.mp_canvas.winfo_height():
                self.mp_scrollbar.pack(side="right", fill="y")
            else:
                self.mp_scrollbar.pack_forget()
        except: pass

    def _create_modpack_item(self, pack, index):
        card = tk.Frame(self.mp_scrollable_frame, bg=COLORS['card_bg'], pady=15, padx=15)
        card.pack(fill="x", padx=20, pady=5)
        
        # Icon / Initial
        initial = pack['name'][0].upper() if pack['name'] else "?"
        icon = tk.Label(card, text=initial, font=("Segoe UI", 18, "bold"), 
                       bg=COLORS.get('input_bg', '#333333'), fg="white", width=4, height=2)
        icon.pack(side="left", padx=(0, 15))
        
        # Details
        info = tk.Frame(card, bg=COLORS['card_bg'])
        info.pack(side="left", fill="both", expand=True)
        
        tk.Label(info, text=pack['name'], font=("Segoe UI", 14, "bold"), fg="white", bg=COLORS['card_bg'], anchor="w").pack(fill="x")
        
        meta = f"Loader: {pack.get('loader', 'Unknown').capitalize()}  •  Version: {pack.get('mc_version', 'Unknown')}"
        tk.Label(info, text=meta, font=("Segoe UI", 10), fg=COLORS['text_secondary'], bg=COLORS['card_bg'], anchor="w").pack(fill="x", pady=2)

        selected_pack_version = pack.get("version_name")
        if selected_pack_version:
            tk.Label(
                info,
                text=f"Pack Release: {selected_pack_version}",
                font=("Segoe UI", 9),
                fg=COLORS['text_secondary'],
                bg=COLORS['card_bg'],
                anchor="w",
            ).pack(fill="x")

        # Linked Status
        linked_inst_id = pack.get("linked_installation_id")
        link_status = "Not linked"
        link_color = COLORS['text_secondary']
        
        if linked_inst_id:
            # Check if inst exists
             curr_insts = self.get_installations()
             # Finding name is hard without helper, let's just say "Linked"
             link_status = "Linked to Installation"
             link_color = COLORS['play_btn_green']

        tk.Label(info, text=link_status, font=("Segoe UI", 9, "italic"), fg=link_color, bg=COLORS['card_bg'], anchor="w").pack(fill="x")

        # Buttons
        btns = tk.Frame(card, bg=COLORS['card_bg'])
        btns.pack(side="right")

        # Link
        self._make_btn(btns, "Link", style="secondary", font_size=10,
                      command=lambda: self.show_link_modpack_dialog(pack)).pack(side="left", padx=2)

        # Show Mods
        sm_btn = self._make_btn(btns, "Show Mods", style="primary", font_size=10,
                                command=lambda: self.show_modpack_contents_dialog(pack))
        sm_btn.pack(side="left", padx=2)

        # Browse (+)
        def browse_action():
            self.select_modpack_and_browse(pack)

        self._make_btn(btns, "+", style="primary", font_size=10, icon=True, width=3,
                      command=browse_action).pack(side="left", padx=2)

        # Menu (⋮) - Now on Right
        menu_btn = self._make_btn(btns, "⋮", style="icon", font_size=10, width=3)
        menu_btn.pack(side="left", padx=2)

        def show_pack_menu(event=None):
            m = NeoContextMenu(self.root)
            m.add_item("📦 View Details / Mods", lambda: self.show_modpack_contents_dialog(pack))
            m.add_item("🔗 Link Installation", lambda: self.show_link_modpack_dialog(pack))
            m.add_item("📁 Open Folder", lambda: open_path_in_system(self.get_modpack_dir(pack['id'])))
            m.add_separator()
            m.add_item("📤 Export as .mrpack", lambda: self.export_modpack(pack, format="mrpack"))
            m.add_item("🗜 Export as .zip", lambda: self.export_modpack(pack, format="zip"))
            m.add_separator()
            m.add_item("🗑 Delete Modpack", lambda: self.delete_modpack(pack), is_danger=True)
            if event:
                m.show_at(event.x_root, event.y_root)
            else:
                m.show_below(menu_btn)

        menu_btn.config(command=lambda: show_pack_menu())
        attach_context_menu(card, lambda e: show_pack_menu(e))
        self._bind_smooth_scroll(self.mp_canvas, card)

    def install_local_mods(self, pack):
        paths = filedialog.askopenfilenames(filetypes=[("Jar Files", "*.jar")])
        if not paths: return
        
        mods_dir = os.path.join(self.get_modpack_dir(pack['id']), "mods")
        if not os.path.exists(mods_dir): os.makedirs(mods_dir)
        
        count = 0
        for p in paths:
             try:
                 shutil.copy(p, mods_dir)
                 count += 1
             except: pass
             
        if count > 0:
            if hasattr(self, 'toast_manager') and self.toast_manager:
                self.toast_manager.show(f"Installed {count} mods locally.", kind="success")
            elif hasattr(self, 'notifications') and self.notifications:
                self.notifications.add("download", "Mods Installed", f"Installed {count} mods locally.")

    def delete_modpack(self, pack):
        if not messagebox.askyesno("Delete Modpack", f"Are you sure you want to delete '{pack['name']}'?"):
            return
        
        try:
            d = self.get_modpack_dir(pack['id'])
            if os.path.exists(d):
                shutil.rmtree(d)
        except Exception as e:
            print(f"Error deleting dir: {e}")
        
        self.modpacks = [p for p in self.modpacks if p['id'] != pack['id']]
        self.save_modpacks()
        
        # Refresh both list and dropdown
        self.refresh_modpacks_list()
        self.update_active_modpack_dropdown()
        
        # Reset active pack selection if deleted pack was active
        if hasattr(self, 'active_modpack_var') and self.active_modpack_var.get() == pack['name']:
            self.active_modpack_var.set("None")

    def export_modpack(self, pack: dict, format: str = "mrpack") -> None:
        """Export modpack to .mrpack or .zip."""
        pack_dir = self.get_modpack_dir(pack['id'])
        if not os.path.exists(pack_dir):
            custom_showerror("Export Error", f"Modpack directory not found for '{pack.get('name', 'Pack')}'.", parent=self.root)
            return

        name_slug = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in pack.get("name", "modpack"))
        default_ext = ".mrpack" if format == "mrpack" else ".zip"
        filetypes = [("Modrinth Modpack", "*.mrpack")] if format == "mrpack" else [("Zip Archive", "*.zip")]

        target_file = filedialog.asksaveasfilename(
            parent=self.root,
            title=f"Export Modpack as {default_ext.upper()}",
            initialfile=f"{name_slug}{default_ext}",
            defaultextension=default_ext,
            filetypes=filetypes
        )
        if not target_file:
            return

        self.show_progress_overlay(f"Exporting '{pack.get('name')}'…")

        def run_export():
            try:
                if format == "mrpack":
                    export_modpack_to_mrpack(
                        modpack_dir=pack_dir,
                        output_path=target_file,
                        modpack_name=pack.get("name", "Custom Pack"),
                        version_id=pack.get("version_name", "1.0.0"),
                        game_version=pack.get("mc_version", "1.20.1"),
                        loader=pack.get("loader", "Fabric")
                    )
                else:
                    export_modpack_to_zip(
                        modpack_dir=pack_dir,
                        output_path=target_file
                    )
                def on_export_done():
                    self.hide_progress_overlay()
                    succ_msg = f"Exported '{pack.get('name')}' to {os.path.basename(target_file)}"
                    if hasattr(self, 'toast_manager'):
                        self.toast_manager.show(succ_msg, level="success")
                    elif hasattr(self.root, 'toast_manager'):
                        self.root.toast_manager.show(succ_msg, level="success")
                    else:
                        custom_showinfo("Export Complete", succ_msg, parent=self.root)
                    if hasattr(self, 'notifications'):
                        self.notifications.add(
                            title="Modpack Exported",
                            message=f"Successfully exported '{pack.get('name')}' to:\n{target_file}",
                            level="success",
                            action=lambda p=target_file: open_path_in_system(os.path.dirname(p))
                        )
                self.root.after(0, on_export_done)
            except Exception as e:
                logger.exception("Export failed: %s", e)
                self.root.after(0, lambda err=str(e): [
                    self.hide_progress_overlay(),
                    custom_showerror("Export Failed", f"Failed to export modpack:\n{err}", parent=self.root)
                ])

        threading.Thread(target=run_export, daemon=True).start()

    def show_modpack_contents_dialog(self, pack):
        self._in_modpack_details_view = True
        if hasattr(self, 'modpacks_browse_view') and self.modpacks_browse_view.winfo_exists():
            self.modpacks_browse_view.pack_forget()

        if hasattr(self, 'modpack_details_view') and self.modpack_details_view.winfo_exists():
            try:
                self.modpack_details_view.destroy()
            except Exception:
                pass

        page = tk.Frame(self.tabs["Modpacks"], bg=COLORS['main_bg'])
        self.modpack_details_view = page
        dialog_root = page
        
        mods_dir = os.path.join(self.get_modpack_dir(pack['id']), "mods")
        if not os.path.exists(mods_dir): os.makedirs(mods_dir)
        
        # Header
        header = tk.Frame(dialog_root, bg=COLORS['sidebar_bg'], pady=15, padx=20)
        header.pack(fill="x")
        
        title_frame = tk.Frame(header, bg=COLORS['sidebar_bg'])
        title_frame.pack(fill="x")
        
        back_btn = self._make_btn(
            title_frame,
            "← Back to Modpacks",
            style="secondary",
            font_size=9,
            command=self.close_modpack_details_page,
        )
        back_btn.pack(side="left", padx=(0, 15))

        tk.Label(title_frame, text=pack['name'], font=("Segoe UI", 16, "bold"),
                 bg=COLORS['sidebar_bg'], fg=COLORS['text_primary']).pack(side="left")
        
        # Action buttons in header
        actions = tk.Frame(title_frame, bg=COLORS['sidebar_bg'])
        actions.pack(side="right")
        
        def open_folder():
            self._open_path(mods_dir)
        
        def refresh_list():
            render_mods()
        
        self._make_btn(actions, "Open Folder", style="secondary", font_size=9,
                      command=open_folder).pack(side="left", padx=5)

        self._make_btn(actions, "Refresh", style="secondary", font_size=9,
                      command=refresh_list).pack(side="left")

        def show_export_menu():
            m = NeoContextMenu(self.root)
            m.add_item("Export as .mrpack", lambda: self.export_modpack(pack, format="mrpack"))
            m.add_item("Export as .zip", lambda: self.export_modpack(pack, format="zip"))
            m.show_below(export_btn)

        export_btn = self._make_btn(actions, "Export", style="secondary", font_size=9,
                                    command=show_export_menu)
        export_btn.pack(side="left", padx=5)

        view_mode_var = tk.StringVar(value=getattr(self, "installed_mods_view_mode", "grid"))
        grid_btn = self._make_btn(actions, "Grid", style="secondary", font_size=9)
        grid_btn.pack(side="left", padx=(12, 5))
        list_btn = self._make_btn(actions, "List", style="secondary", font_size=9)
        list_btn.pack(side="left")
        
        # Search bar
        search_frame = tk.Frame(header, bg=COLORS['input_bg'], padx=10, pady=8)
        search_frame.pack(fill="x", pady=(10, 0))
        
        tk.Label(search_frame, text="Search:", font=(FONT_FAMILY, 9, "bold"), bg=COLORS['input_bg'], 
                fg=COLORS['text_secondary']).pack(side="left", padx=(0, 6))
        
        search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=search_var, 
                               font=("Segoe UI", 10), bg=COLORS['input_bg'],
                               fg=COLORS['text_primary'], relief="flat", 
                               insertbackground="white")
        search_entry.pack(side="left", fill="x", expand=True, padx=5)
        
        # Scrollable content area
        content_frame = tk.Frame(dialog_root, bg=COLORS['main_bg'])
        content_frame.pack(fill="both", expand=True)

        canvas = tk.Canvas(content_frame, bg=COLORS['main_bg'], highlightthickness=0, yscrollincrement=16)

        def on_scrollbar_scroll(*args):
            canvas.yview(*args)
            if hasattr(self, '_flush_canvas_paint'):
                self._flush_canvas_paint(canvas)
            else:
                try:
                    canvas.update()
                except Exception:
                    canvas.update_idletasks()

        scrollbar = ttk.Scrollbar(content_frame, orient="vertical",
                                 command=on_scrollbar_scroll, style="Launcher.Vertical.TScrollbar")
        scroll_frame = tk.Frame(canvas, bg=COLORS['main_bg'])
        canvas._nlc_scroll_enabled = True # type: ignore[attr-defined]
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Rendering every card in a single event-loop turn makes a large pack
        # look like the launcher has hung.  Keep enough state to cancel a
        # stale render (search, refresh, resize, or view change) and resume in
        # short batches instead.
        layout_state = {
            "cols": None,
            "page": 0,
            "per_page": 24,
            "render_after_id": None,
            "batch_after_id": None,
            "render_generation": 0,
            "file_metadata": {},
        }

        def compute_grid_columns():
            try:
                canvas.update_idletasks()
                available_w = max(360, canvas.winfo_width() - 36)
                return max(1, min(4, available_w // 235))
            except Exception:
                return 3

        def update_view_buttons():
            current = view_mode_var.get()
            btn_active_bg = COLORS.get('accent_color', COLORS.get('play_btn_green', '#2D8F36'))
            btn_inactive_bg = COLORS.get('input_bg', '#2E333E')
            btn_inactive_fg = COLORS.get('text_secondary', '#A0AAB0')
            btn_hover_bg = COLORS.get('hover_bg', '#3A3F4D')
            if current == "grid":
                grid_btn.config(bg=btn_active_bg, fg="white",
                                activebackground=btn_active_bg)
                list_btn.config(bg=btn_inactive_bg, fg=btn_inactive_fg, activebackground=btn_hover_bg)
            else:
                list_btn.config(bg=btn_active_bg, fg="white",
                                activebackground=btn_active_bg)
                grid_btn.config(bg=btn_inactive_bg, fg=btn_inactive_fg, activebackground=btn_hover_bg)

        def set_view_mode(mode):
            if mode not in ("grid", "list"):
                return
            if getattr(self, "installed_mods_view_mode", "grid") == mode and view_mode_var.get() == mode:
                update_view_buttons()
                return
            self.installed_mods_view_mode = mode
            view_mode_var.set(mode)
            update_view_buttons()
            self.save_config(sync_ui=False)
            render_mods(reset_scroll=False)

        grid_btn.config(command=lambda: set_view_mode("grid"))
        list_btn.config(command=lambda: set_view_mode("list"))
        update_view_buttons()

        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
            if view_mode_var.get() != "grid":
                return
            new_cols = compute_grid_columns()
            if layout_state["cols"] == new_cols:
                return
            layout_state["cols"] = new_cols
            after_id = layout_state.get("render_after_id")
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except Exception:
                    pass
            layout_state["render_after_id"] = self.root.after(70, lambda: render_mods(reset_scroll=False))

        canvas.bind("<Configure>", on_canvas_configure)
        self._bind_smooth_scroll(canvas, scroll_frame)

        mod_icon_mgr = get_mod_icon_manager()

        def get_mod_display_data(filename):
            is_enabled = not filename.lower().endswith(".disabled")
            clean_name = filename
            if clean_name.lower().endswith(".jar.disabled"):
                clean_name = clean_name[:-13]
            elif clean_name.lower().endswith(".jar"):
                clean_name = clean_name[:-4]

            size_bytes = layout_state["file_metadata"].get(filename, 0)
            size_str = ""
            if size_bytes < 1024:
                size_str = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                size_str = f"{size_bytes / 1024:.1f} KB"
            else:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
            return clean_name, is_enabled, size_str

        def delete_mod(filename, display_name):
            if custom_askyesno("Delete Mod",
                              f"Are you sure you want to delete '{display_name}'?",
                              parent=dialog_root):
                try:
                    os.remove(os.path.join(mods_dir, filename))
                    rem_meta = next((m for m in pack.get('mods', []) if m.get('filename') == filename), None)
                    if rem_meta:
                        pack['mods'].remove(rem_meta)
                        self.save_modpacks()
                    render_mods(reset_scroll=False)
                except Exception as e:
                    custom_showerror("Error", f"Failed to delete mod: {e}", parent=dialog_root)

        def toggle_mod(filename, is_enabled, on_toggle_done=None):
            old_path = os.path.join(mods_dir, filename)
            if is_enabled:
                new_filename = filename + ".disabled"
            else:
                new_filename = filename[:-9] if filename.endswith(".disabled") else filename
            new_path = os.path.join(mods_dir, new_filename)
            try:
                os.rename(old_path, new_path)
                if filename in layout_state["file_metadata"]:
                    layout_state["file_metadata"][new_filename] = layout_state["file_metadata"].pop(filename)
                if on_toggle_done:
                    on_toggle_done(new_filename, not is_enabled)
                else:
                    render_mods(reset_scroll=False)
            except Exception as e:
                custom_showerror("Toggle Mod", f"Could not toggle mod: {e}", parent=dialog_root)

        def bind_hover_surfaces(card, surfaces, info_widgets, del_btn, toggle_btn=None):
            card_hover_bg = COLORS.get('card_hover', COLORS.get('hover_bg', '#3A3F4D'))
            def on_enter_card(_event):
                for surface in surfaces:
                    surface.config(bg=card_hover_bg)
                for widget in info_widgets:
                    widget.config(bg=card_hover_bg)

            def on_leave_card(event):
                for btn in (del_btn, toggle_btn):
                    if btn and btn.winfo_containing(event.x_root, event.y_root) == btn:
                        return
                for surface in surfaces:
                    surface.config(bg=COLORS['card_bg'])
                for widget in info_widgets:
                    widget.config(bg=COLORS['card_bg'])

            for surface in surfaces:
                surface.bind("<Enter>", on_enter_card)
                surface.bind("<Leave>", on_leave_card)

        def create_remove_button(parent, command):
            danger_subtle = COLORS.get('input_bg', '#2E333E')
            danger_red = COLORS.get('error_red', '#EF4444')
            del_btn = tk.Button(parent, text="Remove", font=(FONT_FAMILY, 8, "bold"),
                               bg=danger_subtle, fg=danger_red, relief="flat", bd=0,
                               cursor="hand2", padx=8, pady=3, command=command)
            del_btn.bind("<Enter>", lambda _e: del_btn.config(bg=danger_red, fg="white"))
            del_btn.bind("<Leave>", lambda _e: del_btn.config(bg=danger_subtle, fg=danger_red))
            return del_btn

        def create_toggle_switch(parent, is_enabled, command):
            active_col = COLORS.get('play_btn_green', COLORS.get('accent_color', '#2ECC71'))
            off_bg = COLORS.get('input_bg', '#2E333E')
            btn = tk.Button(
                parent,
                text="ON" if is_enabled else "OFF",
                font=(FONT_FAMILY, 8, "bold"),
                bg=active_col if is_enabled else off_bg,
                fg="#FFFFFF" if is_enabled else COLORS.get('text_secondary', '#A6ACB8'),
                relief="flat",
                bd=0,
                padx=8,
                pady=2,
                cursor="hand2",
                command=command
            )
            return btn

        def create_mod_grid_card(parent, filename, row, col):
            clean_name, is_enabled, size_str = get_mod_display_data(filename)
            card_state = {"filename": filename, "is_enabled": is_enabled}

            card_border = COLORS.get('play_btn_green', COLORS.get('accent_color', '#2ECC71')) if is_enabled else COLORS.get('card_border', '#2A303F')
            card = tk.Frame(parent, bg=COLORS['card_bg'], padx=12, pady=10, width=240, height=148,
                            highlightthickness=1, highlightbackground=card_border)
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            card.grid_propagate(False)
            card.pack_propagate(False)

            top_row = tk.Frame(card, bg=COLORS['card_bg'])
            top_row.pack(fill="x")

            # Icon on top-left (40x40)
            placeholder_photo = mod_icon_mgr.get_placeholder_photo((40, 40))
            icon_lbl = tk.Label(top_row, bg=COLORS['card_bg'], image=placeholder_photo, bd=0)
            icon_lbl.image = placeholder_photo
            icon_lbl.pack(side="left")

            jar_path = os.path.join(mods_dir, filename)
            real_photo = mod_icon_mgr.get_icon_async(
                jar_path,
                icon_lbl,
                lambda p, lbl=icon_lbl: (lbl.config(image=p), setattr(lbl, 'image', p)) if (lbl.winfo_exists() and p) else None,
                size=(40, 40)
            )
            if real_photo:
                icon_lbl.config(image=real_photo)
                icon_lbl.image = real_photo

            # Badge & Toggle on top-right
            status_box = tk.Frame(top_row, bg=COLORS['card_bg'])
            status_box.pack(side="right", anchor="ne")

            status_lbl = tk.Label(
                status_box,
                text="Active" if is_enabled else "Disabled",
                font=(FONT_FAMILY, 8, "bold"),
                bg=COLORS['card_bg'],
                fg=COLORS.get('play_btn_green', '#2ECC71') if is_enabled else COLORS.get('text_secondary', '#A6ACB8')
            )
            status_lbl.pack(side="top", anchor="e", pady=(0, 2))

            def on_toggle_click():
                curr_f = card_state["filename"]
                curr_en = card_state["is_enabled"]
                def on_done(new_f, new_en):
                    card_state["filename"] = new_f
                    card_state["is_enabled"] = new_en
                    active_c = COLORS.get('play_btn_green', COLORS.get('accent_color', '#2ECC71'))
                    off_b = COLORS.get('input_bg', '#2E333E')
                    t_btn.config(
                        text="ON" if new_en else "OFF",
                        bg=active_c if new_en else off_b,
                        fg="#FFFFFF" if new_en else COLORS.get('text_secondary', '#A6ACB8')
                    )
                    status_lbl.config(
                        text="Active" if new_en else "Disabled",
                        fg=active_c if new_en else COLORS.get('text_secondary', '#A6ACB8')
                    )
                    card.config(highlightbackground=active_c if new_en else COLORS.get('card_border', '#2A303F'))
                    name_lbl.config(fg=COLORS['text_primary'] if new_en else COLORS.get('text_secondary', '#A6ACB8'))
                toggle_mod(curr_f, curr_en, on_done)

            t_btn = create_toggle_switch(status_box, is_enabled, on_toggle_click)
            t_btn.pack(side="bottom", anchor="e")

            # Bottom actions row (docked at the bottom before middle info to avoid clipping)
            actions_row = tk.Frame(card, bg=COLORS['card_bg'])
            actions_row.pack(side="bottom", fill="x")

            del_btn = create_remove_button(actions_row, lambda: delete_mod(card_state["filename"], clean_name))
            del_btn.pack(side="right")

            # Title and metadata in middle
            info = tk.Frame(card, bg=COLORS['card_bg'])
            info.pack(side="top", fill="both", expand=True, pady=(6, 0))

            name_lbl = tk.Label(
                info,
                text=clean_name,
                font=(FONT_FAMILY, 10, "bold"),
                bg=COLORS['card_bg'],
                fg=COLORS['text_primary'] if is_enabled else COLORS.get('text_secondary', '#A6ACB8'),
                anchor="w",
                wraplength=210,
                justify="left"
            )
            name_lbl.pack(fill="x")

            meta_lbl = tk.Label(
                info,
                text=f"Size: {size_str}" if size_str else "",
                font=(FONT_FAMILY, 8),
                bg=COLORS['card_bg'],
                fg=COLORS.get('text_secondary', '#A6ACB8'),
                anchor="w"
            )
            meta_lbl.pack(fill="x", pady=(2, 0))

            bind_hover_surfaces(card, [card, top_row, status_box, info, actions_row], [status_lbl, name_lbl, meta_lbl], del_btn, t_btn)

            def show_mod_card_menu(event):
                m = NeoContextMenu(self.root)
                m.add_item("Toggle (ON/OFF)", on_toggle_click)
                m.add_item("Open Mods Folder", lambda: open_path_in_system(mods_dir))
                m.add_separator()
                m.add_item("Remove Mod", lambda: delete_mod(card_state["filename"], clean_name), is_danger=True)
                m.show_at(event.x_root, event.y_root)

            attach_context_menu(card, show_mod_card_menu)
            self._bind_smooth_scroll(canvas, card)

        def create_mod_list_row(parent, filename):
            clean_name, is_enabled, size_str = get_mod_display_data(filename)
            card_state = {"filename": filename, "is_enabled": is_enabled}

            card_border = COLORS.get('play_btn_green', COLORS.get('accent_color', '#2ECC71')) if is_enabled else COLORS.get('card_border', '#2A303F')
            row = tk.Frame(parent, bg=COLORS['card_bg'], padx=14, pady=10,
                           highlightthickness=1, highlightbackground=card_border)
            row.pack(fill="x", padx=12, pady=5)

            left = tk.Frame(row, bg=COLORS['card_bg'])
            left.pack(side="left", fill="both", expand=True)

            # Icon (36x36)
            placeholder_photo = mod_icon_mgr.get_placeholder_photo((36, 36))
            icon_lbl = tk.Label(left, bg=COLORS['card_bg'], image=placeholder_photo, bd=0)
            icon_lbl.image = placeholder_photo
            icon_lbl.pack(side="left", padx=(0, 12))

            jar_path = os.path.join(mods_dir, filename)
            real_photo = mod_icon_mgr.get_icon_async(
                jar_path,
                icon_lbl,
                lambda p, lbl=icon_lbl: (lbl.config(image=p), setattr(lbl, 'image', p)) if (lbl.winfo_exists() and p) else None,
                size=(36, 36)
            )
            if real_photo:
                icon_lbl.config(image=real_photo)
                icon_lbl.image = real_photo

            info = tk.Frame(left, bg=COLORS['card_bg'])
            info.pack(side="left", fill="both", expand=True)

            name_lbl = tk.Label(
                info,
                text=clean_name,
                font=(FONT_FAMILY, 10, "bold"),
                bg=COLORS['card_bg'],
                fg=COLORS['text_primary'] if is_enabled else COLORS.get('text_secondary', '#A6ACB8'),
                anchor="w"
            )
            name_lbl.pack(fill="x")

            meta_text = filename if not size_str else f"{filename}  •  {size_str}"
            meta_lbl = tk.Label(
                info,
                text=meta_text,
                font=(FONT_FAMILY, 8),
                bg=COLORS['card_bg'],
                fg=COLORS.get('text_secondary', '#A6ACB8'),
                anchor="w"
            )
            meta_lbl.pack(fill="x", pady=(2, 0))

            actions_row = tk.Frame(row, bg=COLORS['card_bg'])
            actions_row.pack(side="right", padx=(10, 0))

            status_lbl = tk.Label(
                actions_row,
                text="Active" if is_enabled else "Disabled",
                font=(FONT_FAMILY, 8, "bold"),
                bg=COLORS['card_bg'],
                fg=COLORS.get('play_btn_green', '#2ECC71') if is_enabled else COLORS.get('text_secondary', '#A6ACB8')
            )
            status_lbl.pack(side="left", padx=(0, 10))

            def on_toggle_click():
                curr_f = card_state["filename"]
                curr_en = card_state["is_enabled"]
                def on_done(new_f, new_en):
                    card_state["filename"] = new_f
                    card_state["is_enabled"] = new_en
                    active_c = COLORS.get('play_btn_green', COLORS.get('accent_color', '#2ECC71'))
                    off_b = COLORS.get('input_bg', '#2E333E')
                    t_btn.config(
                        text="ON" if new_en else "OFF",
                        bg=active_c if new_en else off_b,
                        fg="#FFFFFF" if new_en else COLORS.get('text_secondary', '#A6ACB8')
                    )
                    status_lbl.config(
                        text="Active" if new_en else "Disabled",
                        fg=active_c if new_en else COLORS.get('text_secondary', '#A6ACB8')
                    )
                    row.config(highlightbackground=active_c if new_en else COLORS.get('card_border', '#2A303F'))
                    name_lbl.config(fg=COLORS['text_primary'] if new_en else COLORS.get('text_secondary', '#A6ACB8'))
                toggle_mod(curr_f, curr_en, on_done)

            t_btn = create_toggle_switch(actions_row, is_enabled, on_toggle_click)
            t_btn.pack(side="left", padx=(0, 10))

            del_btn = create_remove_button(actions_row, lambda: delete_mod(card_state["filename"], clean_name))
            del_btn.pack(side="left")

            bind_hover_surfaces(row, [row, left, info, actions_row], [status_lbl, name_lbl, meta_lbl], del_btn, t_btn)

            def show_mod_row_menu(event):
                m = NeoContextMenu(self.root)
                m.add_item("Toggle (ON/OFF)", on_toggle_click)
                m.add_item("Open Mods Folder", lambda: open_path_in_system(mods_dir))
                m.add_separator()
                m.add_item("Remove Mod", lambda: delete_mod(card_state["filename"], clean_name), is_danger=True)
                m.show_at(event.x_root, event.y_root)

            attach_context_menu(row, show_mod_row_menu)
            self._bind_smooth_scroll(canvas, row)

        def render_mods(reset_scroll=True):
            after_id = layout_state.get("render_after_id")
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except Exception:
                    pass
            layout_state["render_after_id"] = None

            batch_after_id = layout_state.get("batch_after_id")
            if batch_after_id is not None:
                try:
                    self.root.after_cancel(batch_after_id)
                except Exception:
                    pass
            layout_state["batch_after_id"] = None
            layout_state["render_generation"] += 1
            render_generation = layout_state["render_generation"]

            current_top = canvas.yview()[0] if not reset_scroll else 0.0

            for widget in scroll_frame.winfo_children():
                widget.destroy()

            # Scan both .jar (enabled) and .jar.disabled (disabled) files
            file_metadata = {}
            with os.scandir(mods_dir) as entries:
                files = []
                for entry in entries:
                    if not entry.is_file():
                        continue
                    lower = entry.name.lower()
                    if not (lower.endswith(".jar") or lower.endswith(".jar.disabled")):
                        continue
                    try:
                        file_metadata[entry.name] = entry.stat().st_size
                    except OSError:
                        file_metadata[entry.name] = 0
                    files.append(entry.name)
            layout_state["file_metadata"] = file_metadata
            files.sort(key=str.lower)
            search_term = search_var.get().strip().lower()
            if search_term:
                files = [f for f in files if search_term in f.lower()]

            MODS_PER_PAGE = layout_state.get("per_page", 24)
            total_pages = max(1, (len(files) + MODS_PER_PAGE - 1) // MODS_PER_PAGE)
            current_page = max(0, min(layout_state.get("page", 0), total_pages - 1))
            layout_state["page"] = current_page

            start_idx = current_page * MODS_PER_PAGE
            end_idx = min(start_idx + MODS_PER_PAGE, len(files))
            page_files = files[start_idx:end_idx]

            # Top count and pager bar
            top_bar = tk.Frame(scroll_frame, bg=COLORS['main_bg'])
            top_bar.pack(fill="x", padx=20, pady=(15, 10))

            count_text = f"{len(files)} mod{'s' if len(files) != 1 else ''} installed"
            if total_pages > 1 and len(files) > 0:
                count_text += f"  •  Showing {start_idx + 1}–{end_idx}"
            count_label = tk.Label(
                top_bar,
                text=count_text,
                font=(FONT_FAMILY, 10, "bold"),
                bg=COLORS['main_bg'],
                fg=COLORS['text_secondary'],
            )
            count_label.pack(side="left")

            def create_pager(parent_container):
                if total_pages <= 1:
                    return
                pager = tk.Frame(parent_container, bg=COLORS['main_bg'])
                pager.pack(side="right")

                def go_prev():
                    if layout_state["page"] > 0:
                        layout_state["page"] -= 1
                        render_mods(reset_scroll=True)

                def go_next():
                    if layout_state["page"] < total_pages - 1:
                        layout_state["page"] += 1
                        render_mods(reset_scroll=True)

                prev_btn = self._make_btn(
                    pager, "◀ Prev",
                    style="secondary" if current_page > 0 else "text",
                    font_size=8,
                    command=go_prev if current_page > 0 else None,
                    pack_opts={"side": "left", "padx": (0, 6)}
                )
                if current_page == 0:
                    prev_btn.config(state="disabled", fg=COLORS.get('text_muted', '#6B7280'))

                page_lbl = tk.Label(
                    pager,
                    text=f"Page {current_page + 1} of {total_pages}",
                    font=(FONT_FAMILY, 9, "bold"),
                    bg=COLORS['main_bg'],
                    fg=COLORS['text_primary'],
                )
                page_lbl.pack(side="left", padx=8)

                next_btn = self._make_btn(
                    pager, "Next ▶",
                    style="secondary" if current_page < total_pages - 1 else "text",
                    font_size=8,
                    command=go_next if current_page < total_pages - 1 else None,
                    pack_opts={"side": "left", "padx": (6, 0)}
                )
                if current_page >= total_pages - 1:
                    next_btn.config(state="disabled", fg=COLORS.get('text_muted', '#6B7280'))

            create_pager(top_bar)

            if not files:
                empty_frame = tk.Frame(scroll_frame, bg=COLORS['main_bg'])
                empty_frame.pack(fill="both", expand=True, pady=50)

                msg = "No mods found in this modpack." if not search_term else "No mods match your search."
                tk.Label(empty_frame, text=msg, font=(FONT_FAMILY, 12, "bold"),
                        bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack(pady=10)

                if not search_term:
                    tk.Label(empty_frame, text="Use 'Install Local Mods' or browse mods to add mods.",
                            font=(FONT_FAMILY, 10), bg=COLORS['main_bg'],
                            fg=COLORS.get('text_muted', '#6B7280')).pack()
            elif view_mode_var.get() == "list":
                layout_state["cols"] = None
                list_wrap = tk.Frame(scroll_frame, bg=COLORS['main_bg'])
                list_wrap.pack(fill="x", padx=8, pady=(0, 12))
                for filename in page_files:
                    create_mod_list_row(list_wrap, filename)
            else:
                cols = compute_grid_columns()
                layout_state["cols"] = cols
                grid_wrap = tk.Frame(scroll_frame, bg=COLORS['main_bg'])
                grid_wrap.pack(fill="x", padx=16, pady=(0, 12))
                for c in range(cols):
                    grid_wrap.grid_columnconfigure(c, weight=1, uniform="modgrid")
                for index, filename in enumerate(page_files):
                    create_mod_grid_card(grid_wrap, filename, index // cols, index % cols)

            if total_pages > 1 and page_files:
                bottom_bar = tk.Frame(scroll_frame, bg=COLORS['main_bg'])
                bottom_bar.pack(fill="x", padx=20, pady=(15, 25))
                create_pager(bottom_bar)

            scroll_frame.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.yview_moveto(0.0 if reset_scroll else current_top)
            if hasattr(self, '_flush_canvas_paint'):
                self._flush_canvas_paint(canvas)

        # Let the view paint immediately, then scan/render its installed
        # files. This avoids the blank flash on large modpack directories.
        self._show_skeleton_list(scroll_frame, rows=3, card_height=112, padx=12, pady=6)
        self._bind_smooth_scroll(canvas, scroll_frame)
        self.root.after(50, render_mods)
        
        # Bind search to debounced re-render
        search_state = {"after_id": None}

        def run_search_render():
            search_state["after_id"] = None
            layout_state["page"] = 0
            render_mods(reset_scroll=True)

        def schedule_search_render(*_args):
            after_id = search_state.get("after_id")
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except Exception:
                    pass
            try:
                search_state["after_id"] = self.root.after(180, run_search_render) # type: ignore
            except Exception:
                search_state["after_id"] = None
                render_mods()

        search_var.trace_add("write", schedule_search_render)
        page.bind("<Escape>", lambda _e: self.close_modpack_details_page())
        page.pack(fill="both", expand=True)

    def close_modpack_details_page(self):
        self._in_modpack_details_view = False
        if hasattr(self, 'modpack_details_view') and self.modpack_details_view.winfo_exists():
            self.modpack_details_view.pack_forget()
            try:
                self.modpack_details_view.destroy()
            except Exception:
                pass
        if hasattr(self, 'modpacks_browse_view') and self.modpacks_browse_view.winfo_exists():
            self.modpacks_browse_view.pack(fill="both", expand=True)
            self.refresh_modpacks_list()

    def show_import_curseforge_dialog(self):
        """Import a local CurseForge export, including its overrides folder.

        CurseForge manifests deliberately omit direct mod-file URLs.  Supplying
        an optional API key enables exact-file downloads through the official
        CurseForge API; without one, the launcher still imports all included
        overrides and retains the manifest's unresolved file list.
        """
        mgr = get_modal_manager(self.root)
        if not mgr:
            return

        def build_content(content, close_modal):
            tk.Label(
                content,
                text="Choose a CurseForge export (.zip). Overrides are imported securely. An API key is optional but required to download the manifest's mod files.",
                font=("Segoe UI", 9), bg=COLORS['card_bg'], fg=COLORS['text_secondary'],
                justify="left", wraplength=520,
            ).pack(anchor="w", pady=(0, 16))

            archive_var = tk.StringVar()
            archive_row = tk.Frame(content, bg=COLORS['card_bg'])
            archive_row.pack(fill="x")
            archive_entry = tk.Entry(archive_row, textvariable=archive_var, bg=COLORS['input_bg'],
                                     fg=COLORS['text_primary'], relief="flat", insertbackground="white")
            archive_entry.pack(side="left", fill="x", expand=True, ipady=6)

            def choose_archive():
                selected = filedialog.askopenfilename(
                    parent=self.root,
                    title="Choose CurseForge Modpack",
                    filetypes=[("CurseForge Modpack", "*.zip"), ("All Files", "*")],
                )
                if selected:
                    archive_var.set(selected)

            self._make_btn(archive_row, "Browse…", style="secondary", font_size=9, command=choose_archive).pack(side="left", padx=(8, 0))

            tk.Label(content, text="CurseForge API key (optional)", font=("Segoe UI", 9, "bold"),
                     bg=COLORS['card_bg'], fg=COLORS['text_secondary']).pack(anchor="w", pady=(16, 5))
            api_key_var = tk.StringVar(value=str(self.addons_config.get("curseforge_api_key", "")))
            tk.Entry(content, textvariable=api_key_var, show="•", bg=COLORS['input_bg'], fg=COLORS['text_primary'],
                     relief="flat", insertbackground="white").pack(fill="x", ipady=6)

            status = tk.Label(content, text="", font=("Segoe UI", 9), bg=COLORS['card_bg'], fg=COLORS.get('error_red', '#EF4444'))
            status.pack(anchor="w", pady=(8, 0))
            actions = tk.Frame(content, bg=COLORS['card_bg'])
            actions.pack(side="bottom", fill="x")

            def begin_import():
                archive_path = archive_var.get().strip()
                if not archive_path or not os.path.isfile(archive_path):
                    status.config(text="Choose a valid CurseForge .zip export first.")
                    return
                api_key = api_key_var.get().strip()
                if api_key:
                    self.addons_config["curseforge_api_key"] = api_key
                    self.save_config(sync_ui=False)
                task_id = self.add_download_task(os.path.basename(archive_path), "modpack")
                close_modal()
                self.download_manager.queue_modpack(
                    lambda: self._import_curseforge_modpack_thread(archive_path, api_key, task_id),
                    task_id,
                )

            self._make_btn(actions, "Cancel", style="secondary", font_size=9, command=close_modal).pack(side="right")
            self._make_btn(actions, "Import", style="primary", font_size=9, bold=True, command=begin_import).pack(side="right", padx=(0, 8))

        mgr.show_modal("Import CurseForge Modpack", build_content, width=580, height=360)

    def _curseforge_loader_from_manifest(self, manifest):
        minecraft = manifest.get("minecraft", {}) if isinstance(manifest, dict) else {}
        loader_records = minecraft.get("modLoaders", []) if isinstance(minecraft, dict) else []
        loader_ids = [str(item.get("id", "")).lower() for item in loader_records if isinstance(item, dict)]
        if any("fabric" in loader_id for loader_id in loader_ids):
            return "Fabric"
        if any("forge" in loader_id and "neoforge" not in loader_id for loader_id in loader_ids):
            return "Forge"
        return "Vanilla"

    def _import_curseforge_modpack_thread(self, archive_path, api_key, task_id):
        staging_dir = None
        try:
            self.root.after(0, lambda: self.update_download_task(task_id, 2, detail="Reading CurseForge manifest…"))
            with zipfile.ZipFile(archive_path, "r") as archive:
                try:
                    manifest = json.loads(archive.read("manifest.json").decode("utf-8-sig"))
                except KeyError as exc:
                    raise ValueError("This archive is not a CurseForge export (manifest.json is missing).") from exc
            if not isinstance(manifest, dict) or not isinstance(manifest.get("minecraft"), dict):
                raise ValueError("The CurseForge manifest is malformed.")

            minecraft = manifest["minecraft"]
            minecraft_version = str(minecraft.get("version") or "").strip()
            if not minecraft_version:
                raise ValueError("The CurseForge manifest does not specify a Minecraft version.")
            pack_name = str(manifest.get("name") or os.path.splitext(os.path.basename(archive_path))[0]).strip() or "Imported CurseForge Pack"
            pack_id = str(uuid.uuid4())
            modpack_root = os.path.abspath(os.path.join(self.config_dir, "modpacks"))
            os.makedirs(modpack_root, exist_ok=True)
            staging_dir = os.path.join(modpack_root, f".import-{pack_id}")
            final_dir = os.path.join(modpack_root, pack_id)
            os.makedirs(staging_dir)

            self.root.after(0, lambda: self.update_download_task(task_id, 8, detail="Importing overrides…"))
            with tempfile.TemporaryDirectory() as extract_dir:
                _safe_extract_zip(archive_path, extract_dir)
                overrides_name = str(manifest.get("overrides") or "overrides").replace("\\", "/").strip("/")
                overrides_dir = os.path.realpath(os.path.join(extract_dir, overrides_name))
                extract_root = os.path.realpath(extract_dir)
                if os.path.commonpath((extract_root, overrides_dir)) != extract_root:
                    raise ValueError("The CurseForge overrides path is unsafe.")
                if os.path.isdir(overrides_dir):
                    shutil.copytree(overrides_dir, staging_dir, dirs_exist_ok=True)

            raw_files = manifest.get("files", [])
            required_files = [record for record in raw_files if isinstance(record, dict) and record.get("required", True)] if isinstance(raw_files, list) else []
            installed_files = []
            if api_key and required_files:
                mods_dir = os.path.join(staging_dir, "mods")
                os.makedirs(mods_dir, exist_ok=True)
                for index, record in enumerate(required_files, start=1):
                    if self.download_tasks.get(task_id, {}).get("cancel_event") and self.download_tasks[task_id]["cancel_event"].is_set():
                        raise RuntimeError("Cancelled")
                    project_id = record.get("projectID")
                    file_id = record.get("fileID")
                    if not project_id or not file_id:
                        raise ValueError("A CurseForge file entry is missing its project or file ID.")
                    self.root.after(0, lambda i=index, total=len(required_files): self.update_download_task(task_id, 10 + (i - 1) / max(1, total) * 85, detail=f"Downloading mod {i} of {total}…"))
                    response = requests.get(
                        f"https://api.curseforge.com/v1/mods/{project_id}/files/{file_id}/download-url",
                        headers={"x-api-key": api_key}, timeout=(10, 45),
                    )
                    if response.status_code in (401, 403):
                        raise PermissionError("CurseForge rejected the API key. Check that it is valid and has access to file downloads.")
                    response.raise_for_status()
                    download_url = response.json().get("data")
                    if not isinstance(download_url, str) or not download_url.startswith("https://"):
                        raise ValueError(f"CurseForge did not return a valid download URL for file {file_id}.")
                    filename = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(download_url).path)) or f"curseforge-{project_id}-{file_id}.jar"
                    target = os.path.join(mods_dir, filename)
                    _atomic_download(download_url, target, cancel_event=self.download_tasks.get(task_id, {}).get("cancel_event"))
                    installed_files.append({"project_id": project_id, "file_id": file_id, "filename": filename})

            os.replace(staging_dir, final_dir)
            staging_dir = None
            pack = {
                "id": pack_id,
                "name": pack_name,
                "loader": self._curseforge_loader_from_manifest(manifest),
                "mc_version": minecraft_version,
                "version_name": str(manifest.get("version") or ""),
                "source": "curseforge",
                "mods": installed_files,
                "curseforge_files": required_files,
                "linked_installation_id": None,
            }

            def complete_import():
                self.modpacks.append(pack)
                self.save_modpacks()
                self.refresh_modpacks_list()
                self.update_active_modpack_dropdown()
                self.complete_download_task(task_id)
                if required_files and not api_key:
                    self.toast_manager.show("Imported overrides; add a CurseForge API key to download listed mods.", kind="warning", duration=6000)
                else:
                    self.toast_manager.show(f"Imported {pack_name}", kind="success")

            self.root.after(0, complete_import)
        except Exception as exc:
            logging.exception("CurseForge import failed")
            if staging_dir and os.path.isdir(staging_dir):
                try:
                    shutil.rmtree(staging_dir)
                except OSError:
                    pass
            message = str(exc)
            self.root.after(0, lambda: [
                self.fail_download_task(task_id, "Import failed"),
                custom_showerror("CurseForge Import Failed", message, parent=self.root),
            ])

    def show_create_modpack_page(self):
        self._in_modpack_create_view = True
        if hasattr(self, 'modpacks_browse_view') and self.modpacks_browse_view.winfo_exists():
            self.modpacks_browse_view.pack_forget()

        if hasattr(self, 'modpack_create_view') and self.modpack_create_view.winfo_exists():
            try:
                self.modpack_create_view.destroy()
            except Exception:
                pass

        main_bg = COLORS['main_bg']
        card_bg = COLORS.get('card_bg', '#2A2D32')
        input_bg = COLORS['input_bg']
        text_primary = COLORS['text_primary']
        text_secondary = COLORS.get('text_secondary', '#A0AAB0')
        border_col = COLORS.get('border_subtle', '#33373E')

        page = tk.Frame(self.tabs["Modpacks"], bg=main_bg)
        self.modpack_create_view = page

        # Header with back button
        header = tk.Frame(page, bg=main_bg, pady=16, padx=40)
        header.pack(fill="x")
        self.mp_create_header = header

        back_btn = self._make_btn(
            header,
            "← Back to Modpacks",
            style="secondary",
            font_size=9,
            command=self.close_create_modpack_page,
        )
        back_btn.pack(side="left")

        title_lbl = tk.Label(
            header,
            text="New Modpack",
            font=("Segoe UI", 16, "bold"),
            bg=main_bg,
            fg=text_primary,
        )
        title_lbl.pack(side="left", padx=20)
        self.mp_create_title_lbl = title_lbl

        # Centered form card
        card = tk.Frame(page, bg=card_bg, padx=30, pady=24, highlightthickness=1, highlightbackground=border_col)
        card.pack(fill="x", padx=40, pady=20)
        self.mp_create_card = card

        def create_label(text):
            return tk.Label(card, text=text, font=("Segoe UI", 9, "bold"),
                            bg=card_bg, fg=text_secondary, anchor="w")

        # Name
        create_label("MODPACK NAME").pack(fill="x", pady=(0, 5))
        name_var = tk.StringVar()
        name_entry = tk.Entry(card, textvariable=name_var, bg=input_bg, fg=text_primary,
                              insertbackground="white", relief="flat", font=("Segoe UI", 10))
        name_entry.pack(fill="x", ipady=8, pady=(0, 16))
        name_entry.focus_set()

        # Loader
        create_label("MOD LOADER").pack(fill="x", pady=(0, 5))
        loader_var = tk.StringVar(value="fabric")
        loader_cb = ttk.Combobox(card, textvariable=loader_var, values=["fabric", "forge"],
                                 state="readonly", font=("Segoe UI", 10))
        loader_cb.pack(fill="x", ipady=5, pady=(0, 16))

        # Version
        create_label("MINECRAFT VERSION").pack(fill="x", pady=(0, 5))
        ver_var = tk.StringVar(value="Fetching...")
        ver_cb = ttk.Combobox(card, textvariable=ver_var, values=[], state="disabled", font=("Segoe UI", 10))
        ver_cb.pack(fill="x", ipady=5, pady=(0, 20))

        def fetch_vers():
            try:
                vlist = minecraft_launcher_lib.utils.get_version_list()
                releases = [v['id'] for v in vlist if v.get('type') == 'release']

                def update():
                    if not page.winfo_exists():
                        return
                    ver_cb['values'] = releases
                    if releases:
                        ver_cb.current(0)
                        ver_cb.config(state="readonly")
                    else:
                        ver_var.set("Error fetching")

                self.root.after(0, update)
            except Exception as e:
                logger.error("Version fetch error: %s", e)
                if page.winfo_exists():
                    self.root.after(0, lambda: ver_var.set("Network Error"))

        threading.Thread(target=fetch_vers, daemon=True).start()

        def create():
            name = name_var.get().strip()
            if not name:
                custom_showerror("Invalid Name", "Please enter a modpack name.", parent=self.root)
                return

            new_pack = {
                "id": str(uuid.uuid4()),
                "name": name,
                "loader": loader_var.get(),
                "mc_version": ver_var.get(),
                "mods": [],
                "linked_installation_id": None
            }
            self.modpacks.append(new_pack)
            self.save_modpacks()
            self.get_modpack_dir(new_pack['id'])

            self.close_create_modpack_page()
            self.refresh_modpacks_list()
            self.update_active_modpack_dropdown()

        btn_row = tk.Frame(card, bg=card_bg, pady=10)
        btn_row.pack(fill="x")

        save_btn = self._make_btn(
            btn_row,
            "Create Modpack",
            style="primary",
            font_size=10,
            bold=True,
            command=create,
        )
        save_btn.pack(side="right", padx=(10, 0))

        self._make_btn(
            btn_row,
            "Cancel",
            style="secondary",
            font_size=10,
            command=self.close_create_modpack_page,
        ).pack(side="right")

        page.pack(fill="both", expand=True)

    def close_create_modpack_page(self):
        self._in_modpack_create_view = False
        if hasattr(self, 'modpack_create_view') and self.modpack_create_view.winfo_exists():
            self.modpack_create_view.pack_forget()
        if hasattr(self, 'modpacks_browse_view') and self.modpacks_browse_view.winfo_exists():
            self.modpacks_browse_view.pack(fill="both", expand=True)
            self.refresh_modpacks_list()

    def show_create_modpack_dialog(self):
        """Backward-compatible alias delegating to in-page create modpack view."""
        return self.show_create_modpack_page()

    def show_link_modpack_dialog(self, pack):
        mgr = get_modal_manager(self.root)
        if not mgr:
            return

        def build_content(body_frame, close_modal):
            tk.Label(body_frame, text=f"Requires: {pack['mc_version']} ({pack['loader']})", 
                     bg=COLORS['card_bg'], fg=COLORS['text_secondary'], font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 10))

            insts = self.get_installations().items()

            list_frame = tk.Frame(body_frame, bg=COLORS['card_bg'])
            list_frame.pack(fill="both", expand=True)

            scroll = ttk.Scrollbar(list_frame)
            scroll.pack(side="right", fill="y")
            lb = tk.Listbox(list_frame, bg=COLORS['input_bg'], fg="white", yscrollcommand=scroll.set,
                            selectbackground=COLORS.get('accent_color', '#2ECC71'), selectforeground="white",
                            relief="flat", highlightthickness=0, font=("Segoe UI", 10))
            lb.pack(fill="both", expand=True)
            scroll.config(command=lb.yview)

            map_insts = {}  # index -> inst_id
            idx = 0
            for inst_id, inst in insts:
                v_id = inst.get('version', '').lower()
                l_id = inst.get('loader', '').lower()
                is_compat = False
                if pack['loader'].lower() == "fabric":
                    if "fabric" in l_id and pack['mc_version'] in v_id: is_compat = True
                elif pack['loader'].lower() == "forge":
                    if "forge" in l_id and pack['mc_version'] in v_id: is_compat = True
                if pack['mc_version'] in v_id:
                    is_compat = True

                if is_compat:
                    lb.insert("end", f"  {inst.get('name', 'Unnamed')} ({v_id} - {l_id})")
                    map_insts[idx] = inst_id
                    idx += 1

            if idx == 0:
                lb.insert("end", "  (No compatible installations found)")
                lb.config(state="disabled")

            def link():
                sel = lb.curselection()
                if not sel or sel[0] not in map_insts: return
                inst_id = map_insts[sel[0]]

                pack['linked_installation_id'] = inst_id
                self.save_modpacks()
                close_modal()
                self.root.after(50, self.refresh_modpacks_list)

            def create_match():
                threading.Thread(target=self._create_matching_installation_thread, args=(pack, close_modal), daemon=True).start()

            actions = tk.Frame(body_frame, bg=COLORS['card_bg'], pady=10)
            actions.pack(fill="x", side="bottom")

            create_match_btn = self._make_btn(actions, "Create Matching Installation", style="secondary",
                                               font_size=9, bold=True, command=create_match)
            create_match_btn.pack(side="left")

            link_btn = self._make_btn(actions, "Link Selected", style="primary",
                                      font_size=9, bold=True, command=link)
            link_btn.pack(side="right")

            cancel_btn = self._make_btn(actions, "Cancel", style="secondary",
                                        font_size=9, command=close_modal)
            cancel_btn.pack(side="right", padx=(0, 8))

        mgr.show_modal(f"Link '{pack['name']}'", build_content, width=520, height=440)

    def _create_matching_installation_thread(self, pack, dialog):
        try:
            # 1. Prepare Profile Data
            mc_ver = pack['mc_version']
            loader = pack['loader'] # "Fabric" or "Forge"
            
            # Ensure title case for loader to match launch logic expectations
            loader = loader.capitalize() if loader else "Vanilla"
            
            new_id = str(uuid.uuid4()).replace("-", "")
            new_name = f"{pack['name']} ({loader})"
            
            # 2. Create Profile in self.installations (Launcher's own list)
            new_profile = {
                 "id": new_id,
                 "name": new_name,
                 "version": mc_ver,
                 "loader": loader,
                 "icon": "icons/crafting_table_front.png",
                 "java_executable": "",
                 "resolution_width": None,
                 "resolution_height": None,
                 "last_played": "Never",
                 "created": datetime.now().isoformat()
            }
            
            # Try to use pack icon if available
            if 'icon' in pack and pack['icon']:
                 # Ensure it's a valid path we can use
                 new_profile['icon'] = pack['icon']

            self.installations.append(new_profile)
            
            # 3. Link and Refresh
            pack['linked_installation_id'] = new_id
            self.save_config() # Saves installations
            self.save_modpacks() # Saves modpack link
            
            def update_ui():
                self.refresh_installations_list()
                self.update_installation_dropdown()
                self.refresh_modpacks_list()
                if callable(dialog):
                    dialog()
                elif hasattr(dialog, "destroy") and dialog.winfo_exists():
                    dialog.destroy()
                created_msg = f"Created matching installation '{new_name}'"
                if hasattr(self, 'toast_manager'):
                    self.toast_manager.show(created_msg, level="success")
                elif hasattr(self.root, 'toast_manager'):
                    self.root.toast_manager.show(created_msg, level="success")
                else:
                    custom_showinfo("Success", f"Created installation '{new_name}' and linked it.", parent=self.root)
                if hasattr(self, 'notifications'):
                    self.notifications.add(
                        title="Installation Created",
                        message=f"Created matching installation '{new_name}' and linked it to '{pack.get('name')}'.",
                        level="success"
                    )
            
            self.root.after(0, update_ui)
            
        except Exception as e:
            print(e)
            err_msg = str(e)
            self.root.after(0, lambda m=err_msg: custom_showerror("Error", m, parent=self.root))

    def update_active_modpack_dropdown(self):
        if hasattr(self, 'mods_active_pack_combobox'):
            pack_names = ["None"] + [p['name'] for p in self.modpacks]
            self.mods_active_pack_combobox['values'] = pack_names

    def select_modpack_and_browse(self, pack):
        # Set active modpack and switch tab
        self.show_tab("Mods")
        # Update dropdown var
        if hasattr(self, 'active_modpack_var'):
            self.active_modpack_var.set(pack['name'])
            
            # Manually trigger filter update since .set() doesn't fire event
            if hasattr(self, 'mod_loader_filter'):
                self.mod_loader_filter.set(pack['loader'])
            
            # Trigger search with new constraints
            self.search_mods_thread(reset=True)


