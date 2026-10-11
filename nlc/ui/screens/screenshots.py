"""
nlc.ui.screens.screenshots - Dedicated Screenshots Gallery View
"""

import os
import sys
import time
import logging
import datetime
import hashlib
import threading
import queue
import tkinter as tk
from tkinter import ttk
from typing import Optional, List, Dict, Tuple
from PIL import Image, ImageTk

from nlc.storage.paths import open_path_in_system
from nlc.ui.theme import COLORS, FONT_FAMILY
from nlc.ui.components.buttons import make_button
from nlc.ui.components.dialogs import custom_showinfo, custom_showerror, custom_askyesno
from nlc.ui.components.context_menu import NeoContextMenu, attach_context_menu

logger = logging.getLogger(__name__)

try:
    from agent import addon_list_screenshot_files, addon_delete_screenshot
except ImportError:
    def addon_list_screenshot_files(p): return {"dir": os.path.join(str(p), "screenshots"), "items": []}
    def addon_delete_screenshot(p, m=None): pass


class ScreenshotScreenMixin:
    """Mixin providing the dedicated Screenshots screen with async caching and zoom modal."""

    def create_screenshots_tab(self):
        """Construct the dedicated Screenshots tab with modern Neo styling."""
        page = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Screenshots"] = page

        # Persistent memory cache for thumbnails (up to 150 items)
        if not hasattr(self, '_screenshot_thumb_cache'):
            self._screenshot_thumb_cache: Dict[Tuple[str, float, Tuple[int, int]], ImageTk.PhotoImage] = {}
        if not hasattr(self, '_screenshot_work_queue'):
            self._screenshot_work_queue: queue.Queue = queue.Queue()
        if not hasattr(self, '_screenshot_results_queue'):
            self._screenshot_results_queue: queue.Queue = queue.Queue()
            self._start_screenshot_worker_threads()

        # --- Top Header ---
        header = tk.Frame(page, bg=COLORS['sidebar_bg'], height=60, padx=24, pady=14)
        header.pack(fill="x")

        title_box = tk.Frame(header, bg=COLORS['sidebar_bg'])
        title_box.pack(side="left")

        tk.Label(
            title_box,
            text="SCREENSHOTS",
            font=(FONT_FAMILY, 8, "bold"),
            bg=COLORS['sidebar_bg'],
            fg=COLORS['accent_color'],
        ).pack(anchor="w")

        self.screenshots_title_lbl = tk.Label(
            title_box,
            text="Gallery",
            font=("Segoe UI", 16, "bold"),
            bg=COLORS['sidebar_bg'],
            fg=COLORS['text_primary'],
        )
        self.screenshots_title_lbl.pack(anchor="w")

        # Action Buttons on Header Right
        hdr_actions = tk.Frame(header, bg=COLORS['sidebar_bg'])
        hdr_actions.pack(side="right")

        self.screenshots_status_lbl = tk.Label(
            hdr_actions,
            text="",
            font=("Segoe UI", 9),
            bg=COLORS['sidebar_bg'],
            fg=COLORS['text_secondary'],
        )
        self.screenshots_status_lbl.pack(side="left", padx=(0, 16))

        make_button(
            hdr_actions,
            "Open Folder",
            style="secondary",
            font_size=9,
            command=lambda: open_path_in_system(self.get_screenshots_dir()),
        ).pack(side="left", padx=(0, 8))

        make_button(
            hdr_actions,
            "Refresh",
            style="secondary",
            font_size=9,
            command=self.render_screenshots_gallery,
        ).pack(side="left")

        # --- Search / Filter Bar ---
        search_bar = tk.Frame(page, bg=COLORS['card_bg'], padx=20, pady=10)
        search_bar.pack(fill="x", padx=24, pady=(16, 8))

        tk.Label(
            search_bar,
            text="Search:",
            font=(FONT_FAMILY, 9, "bold"),
            bg=COLORS['card_bg'],
            fg=COLORS['text_secondary'],
        ).pack(side="left", padx=(0, 8))

        self.screenshot_search_var = tk.StringVar()
        s_entry = tk.Entry(
            search_bar,
            textvariable=self.screenshot_search_var,
            font=("Segoe UI", 10),
            bg=COLORS['input_bg'],
            fg=COLORS['text_primary'],
            relief="flat",
            insertbackground="white",
        )
        s_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.screenshot_search_var.trace_add("write", lambda *_: self._debounce_screenshot_search())

        # --- Main Scrollable Canvas ---
        canvas_wrap = tk.Frame(page, bg=COLORS['main_bg'])
        canvas_wrap.pack(fill="both", expand=True, padx=24, pady=(0, 16))

        self.screenshots_canvas = tk.Canvas(canvas_wrap, bg=COLORS['main_bg'], highlightthickness=0)
        sb = ttk.Scrollbar(canvas_wrap, orient="vertical", command=self.screenshots_canvas.yview, style="Launcher.Vertical.TScrollbar")
        self.screenshots_grid_frame = tk.Frame(self.screenshots_canvas, bg=COLORS['main_bg'])

        self.screenshots_canvas._nlc_scroll_enabled = True
        self.screenshots_grid_frame.bind(
            "<Configure>",
            lambda e: self.screenshots_canvas.configure(scrollregion=self.screenshots_canvas.bbox("all")),
        )
        self._screenshots_win = self.screenshots_canvas.create_window((0, 0), window=self.screenshots_grid_frame, anchor="nw")

        self.screenshots_canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.screenshots_canvas.configure(yscrollcommand=sb.set)

        self.screenshots_canvas.bind(
            "<Configure>",
            lambda e: self.screenshots_canvas.itemconfig(self._screenshots_win, width=e.width),
        )
        if hasattr(self, '_bind_smooth_scroll'):
            self._bind_smooth_scroll(self.screenshots_canvas, self.screenshots_grid_frame)

        self._poll_screenshot_thumbnails()

    def get_screenshots_dir(self) -> str:
        """Return the active Minecraft screenshots directory."""
        return os.path.join(self.minecraft_dir, "screenshots")

    def _debounce_screenshot_search(self):
        if hasattr(self, '_ss_search_after') and self._ss_search_after:
            try:
                self.root.after_cancel(self._ss_search_after)
            except Exception:
                pass
        self._ss_search_after = self.root.after(150, self.render_screenshots_gallery)

    def _start_screenshot_worker_threads(self):
        """Start daemon worker thread for background disk-cached thumbnail processing."""
        def worker():
            cache_dir = os.path.join(getattr(self, 'config_dir', None) or os.path.expanduser('~/.nlc'), 'cache', 'screenshot_thumbs')
            os.makedirs(cache_dir, exist_ok=True)

            while True:
                try:
                    task = self._screenshot_work_queue.get()
                    if task is None:
                        break
                    path, mtime, size, label_id = task

                    disk_key = hashlib.md5(f"{path}_{mtime}_{size[0]}x{size[1]}".encode('utf-8')).hexdigest()
                    disk_path = os.path.join(cache_dir, f"{disk_key}.jpg")

                    img_pil = None
                    if os.path.isfile(disk_path):
                        try:
                            with Image.open(disk_path) as cached_im:
                                img_pil = cached_im.copy()
                        except Exception:
                            pass

                    if img_pil is None and os.path.exists(path):
                        try:
                            with Image.open(path) as raw_im:
                                im = raw_im.convert("RGB")
                                im.thumbnail(size, Image.Resampling.LANCZOS)
                                bg = Image.new("RGB", size, (26, 28, 34))
                                off_x = max(0, (size[0] - im.width) // 2)
                                off_y = max(0, (size[1] - im.height) // 2)
                                bg.paste(im, (off_x, off_y))
                                img_pil = bg
                                try:
                                    bg.save(disk_path, "JPEG", quality=85)
                                except Exception:
                                    pass
                        except Exception as e:
                            logger.debug("Failed rendering screenshot thumb: %s", e)

                    if img_pil:
                        self._screenshot_results_queue.put((path, mtime, size, label_id, img_pil))
                    self._screenshot_work_queue.task_done()
                except Exception as ex:
                    logger.debug("Error in screenshot worker: %s", ex)

        t = threading.Thread(target=worker, daemon=True, name="nlc-screenshot-worker")
        t.start()

    def _poll_screenshot_thumbnails(self):
        """Main-thread polling to populate PhotoImages from worker queue."""
        count = 0
        while not self._screenshot_results_queue.empty() and count < 15:
            count += 1
            try:
                path, mtime, size, label_id, pil_img = self._screenshot_results_queue.get_nowait()
                cache_key = (path, mtime, size)
                photo = ImageTk.PhotoImage(pil_img)
                self._screenshot_thumb_cache[cache_key] = photo

                # If label widget still exists and matches
                lbl = getattr(self, f"_ss_lbl_{label_id}", None)
                if lbl and lbl.winfo_exists():
                    lbl.config(image=photo, text="")
                    lbl.image = photo
            except Exception:
                pass

        if hasattr(self, 'root') and self.root.winfo_exists():
            self.root.after(30, self._poll_screenshot_thumbnails)

    def render_screenshots_gallery(self):
        """Render grid cards for all screenshots."""
        if not hasattr(self, 'screenshots_grid_frame'):
            return

        for w in self.screenshots_grid_frame.winfo_children():
            w.destroy()

        # Clear pending tasks
        while not self._screenshot_work_queue.empty():
            try:
                self._screenshot_work_queue.get_nowait()
                self._screenshot_work_queue.task_done()
            except Exception:
                break

        res = addon_list_screenshot_files(self.minecraft_dir)
        all_items: List[str] = res.get("items", [])
        q = getattr(self, 'screenshot_search_var', None)
        query = q.get().strip().lower() if q else ""
        if query:
            all_items = [p for p in all_items if query in os.path.basename(p).lower()]

        count = len(all_items)
        if hasattr(self, 'screenshots_status_lbl'):
            self.screenshots_status_lbl.config(
                text=f"{count} screenshot{'s' if count != 1 else ''}"
            )

        if not all_items:
            empty = tk.Frame(self.screenshots_grid_frame, bg=COLORS['main_bg'], pady=40)
            empty.pack(fill="x")
            msg = "No screenshots match your search." if query else "No screenshots found in your Minecraft directory yet."
            tk.Label(empty, text=msg, font=(FONT_FAMILY, 11), bg=COLORS['main_bg'], fg=COLORS['text_secondary']).pack()
            return

        cols = 3
        for c in range(cols):
            self.screenshots_grid_frame.grid_columnconfigure(c, weight=1, uniform="ss_col")

        thumb_size = (260, 146)
        for idx, path in enumerate(all_items):
            r = idx // cols
            c = idx % cols
            self._create_screenshot_card(self.screenshots_grid_frame, path, r, c, thumb_size, idx)

        self.screenshots_grid_frame.update_idletasks()
        self.screenshots_canvas.configure(scrollregion=self.screenshots_canvas.bbox("all"))

    def _create_screenshot_card(self, parent, path: str, row: int, col: int, thumb_size: Tuple[int, int], card_id: int):
        card = tk.Frame(
            parent,
            bg=COLORS['card_bg'],
            padx=10,
            pady=10,
            highlightthickness=1,
            highlightbackground=COLORS.get('card_border', '#2A303F'),
        )
        card.grid(row=row, column=col, sticky="nsew", padx=8, pady=8)

        # Thumbnail area
        mtime = os.path.getmtime(path) if os.path.exists(path) else 0.0
        cache_key = (path, mtime, thumb_size)

        preview = tk.Label(
            card,
            bg=COLORS.get('input_bg', '#181A20'),
            width=36,
            height=9,
            cursor="hand2",
        )
        preview.pack(fill="x")
        setattr(self, f"_ss_lbl_{card_id}", preview)

        if cache_key in self._screenshot_thumb_cache:
            photo = self._screenshot_thumb_cache[cache_key]
            preview.config(image=photo, width=thumb_size[0], height=thumb_size[1])
            preview.image = photo
        else:
            preview.config(text="Loading…", fg=COLORS['text_secondary'], font=(FONT_FAMILY, 8))
            self._screenshot_work_queue.put((path, mtime, thumb_size, card_id))

        # Click opens lightbox viewer
        preview.bind("<Button-1>", lambda _e, p=path: self.open_screenshot_lightbox(p))

        # Metadata Row
        meta_box = tk.Frame(card, bg=COLORS['card_bg'])
        meta_box.pack(fill="x", pady=(8, 4))

        filename = os.path.basename(path)
        tk.Label(
            meta_box,
            text=filename,
            font=(FONT_FAMILY, 9, "bold"),
            bg=COLORS['card_bg'],
            fg=COLORS['text_primary'],
            anchor="w",
        ).pack(fill="x")

        dt_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime else ""
        tk.Label(
            meta_box,
            text=dt_str,
            font=(FONT_FAMILY, 8),
            bg=COLORS['card_bg'],
            fg=COLORS['text_secondary'],
            anchor="w",
        ).pack(fill="x")

        # Bottom Action Bar
        act_box = tk.Frame(card, bg=COLORS['card_bg'])
        act_box.pack(fill="x", pady=(6, 0))

        make_button(
            act_box,
            "View",
            style="secondary",
            font_size=8,
            command=lambda p=path: self.open_screenshot_lightbox(p),
        ).pack(side="left")

        make_button(
            act_box,
            "Delete",
            style="secondary",
            font_size=8,
            command=lambda p=path: self.delete_screenshot(p),
        ).pack(side="right")

        # Context Menu
        def show_ctx_menu(event, p=path):
            m = NeoContextMenu(self.root)
            m.add_item("🖼 Open Lightbox View", lambda: self.open_screenshot_lightbox(p))
            m.add_item("📁 Open in System Viewer", lambda: open_path_in_system(p))
            m.add_item("📂 Open Screenshots Folder", lambda: open_path_in_system(self.get_screenshots_dir()))
            m.add_separator()
            m.add_item("🗑 Delete Screenshot", lambda: self.delete_screenshot(p), is_danger=True)
            m.show_at(event.x_root, event.y_root)

        attach_context_menu(card, show_ctx_menu)
        attach_context_menu(preview, show_ctx_menu)
        if hasattr(self, '_bind_smooth_scroll'):
            self._bind_smooth_scroll(self.screenshots_canvas, card)

    def open_screenshot_lightbox(self, path: str):
        """Open high-resolution lightbox preview modal for a screenshot."""
        if not os.path.exists(path):
            return

        def build_content(container, modal_mgr):
            top_bar = tk.Frame(container, bg=COLORS['sidebar_bg'], padx=12, pady=8)
            top_bar.pack(fill="x")

            tk.Label(
                top_bar,
                text=os.path.basename(path),
                font=("Segoe UI", 10, "bold"),
                bg=COLORS['sidebar_bg'],
                fg=COLORS['text_primary'],
            ).pack(side="left")

            make_button(
                top_bar,
                "Open in Explorer",
                style="secondary",
                font_size=8,
                command=lambda: open_path_in_system(path),
            ).pack(side="right", padx=6)

            # High-res image display
            img_container = tk.Frame(container, bg="#0D0E12")
            img_container.pack(fill="both", expand=True, padx=12, pady=12)

            try:
                with Image.open(path) as raw:
                    im = raw.convert("RGB")
                    # Fit within 800x520
                    im.thumbnail((800, 520), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(im)
                    lbl = tk.Label(img_container, image=photo, bg="#0D0E12")
                    lbl.image = photo
                    lbl.pack(expand=True)
            except Exception as e:
                tk.Label(img_container, text=f"Could not load image:\n{e}", fg=COLORS['error_red'], bg="#0D0E12").pack(expand=True)

        mgr = getattr(self, 'modal_manager', None)
        if mgr:
            mgr.show_modal(
                title="Screenshot Preview",
                content_callback=build_content,
                width=860,
                height=620,
            )
        else:
            open_path_in_system(path)

    def delete_screenshot(self, path: str):
        """Delete screenshot with confirmation."""
        if not custom_askyesno("Delete Screenshot", f"Delete '{os.path.basename(path)}'?", parent=self.root):
            return
        try:
            addon_delete_screenshot(path, self.minecraft_dir)
            if hasattr(self, 'save_config'):
                self.save_config(sync_ui=False)
            self.render_screenshots_gallery()
        except Exception as e:
            custom_showerror("Delete Failed", f"Could not delete screenshot:\n{e}", parent=self.root)

