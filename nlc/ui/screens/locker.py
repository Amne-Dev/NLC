"""
nlc.ui.screens.locker - Modernized Locker screen (2.5D skin showcase, wardrobe presets & wallpapers studio).
"""

import os
import sys
import math
import shutil
import logging
import threading
import hashlib
import time
import base64
import json
import urllib.request
import tkinter as tk
from tkinter import ttk, filedialog
from PIL import Image, ImageTk

from typing import cast, Optional, List, Dict, Any, Tuple
from nlc.storage.paths import resource_path, open_path_in_system, get_launcher_data_dir, RESAMPLE_NEAREST
from nlc.ui.theme import COLORS, FONT_FAMILY
from nlc.ui.components.dialogs import custom_showinfo, custom_showerror, custom_showwarning, custom_askyesno
from nlc.ui.components.context_menu import NeoContextMenu, attach_context_menu
from nlc.ui.components.modal import get_modal_manager
from nlc.ui.components.skin_renderer import SkinRenderer3D, Model3DRenderer
from nlc.net.capes import fetch_account_capes, download_and_cache_cape, set_active_mojang_cape, clear_active_mojang_cape

logger = logging.getLogger(__name__)


class LockerScreenMixin:
    """Mixin providing redesigned Locker screen with 3D skin showcase, wardrobe presets, capes studio & wallpapers."""

    def create_locker_tab(self):
        frame = tk.Frame(self.tab_container, bg=COLORS['main_bg'])
        self.tabs["Locker"] = frame

        # Sub-tabs Header Area
        header = tk.Frame(frame, bg=COLORS['main_bg'], padx=24, pady=14)
        header.pack(fill="x")
        self.locker_header = header

        # Segmented Pill Nav (Packed right first so it is never clipped on narrower windows)
        self.locker_view = tk.StringVar(value="Skins")
        self.locker_nav_frame = tk.Frame(
            header,
            bg=COLORS.get('input_bg', '#1E222B'),
            padx=3,
            pady=3,
            highlightthickness=1,
            highlightbackground=COLORS.get('card_border', '#2A303F')
        )
        self.locker_nav_frame.pack(side="right")
        self.locker_btn_frame = self.locker_nav_frame  # Backwards compatibility

        title_box = tk.Frame(header, bg=COLORS['main_bg'])
        title_box.pack(side="left", fill="x", expand=True)

        self.locker_title_lbl = tk.Label(
            title_box,
            text="LOCKER & CUSTOMIZATION",
            font=(FONT_FAMILY, 12, "bold"),
            bg=COLORS['main_bg'],
            fg=COLORS['text_primary']
        )
        self.locker_title_lbl.pack(anchor="w")

        self.locker_subtitle_lbl = tk.Label(
            title_box,
            text="3D Skin showcase, wardrobe presets, capes & wallpaper studio",
            font=(FONT_FAMILY, 8),
            bg=COLORS['main_bg'],
            fg=COLORS['text_secondary']
        )
        self.locker_subtitle_lbl.pack(anchor="w", pady=(1, 0))

        # 3D Animation & Drag State
        self.preview_yaw = 30.0
        self.preview_pitch = 10.0
        self.preview_walk_phase = 0.0
        self.is_walking = True
        self._anim_running = False
        self._anim_job = None
        self._is_dragging = False
        self.account_capes: List[Dict[str, Any]] = []
        self.current_cape_path: Optional[str] = None

        self.locker_btns = {}
        self.update_locker_subtabs()

        # Main Content Frame
        self.locker_content = tk.Frame(frame, bg=COLORS['main_bg'])
        self.locker_content.pack(fill="both", expand=True)

        # Search variable for wardrobe filtering
        self.wardrobe_search_var = tk.StringVar(value="")
        self.wallpaper_filter_var = tk.StringVar(value="all")

        # Start loading account capes asynchronously if Microsoft account
        self.load_account_capes_async()

        self.refresh_locker_view()

    def has_owned_capes(self) -> bool:
        """Return True only if active account is a Microsoft account with >= 1 capes."""
        if not getattr(self, 'profiles', None) or not (0 <= getattr(self, 'current_profile_index', 0) < len(self.profiles)):
            return False
        p = self.profiles[self.current_profile_index]
        if p.get("type") != "microsoft":
            return False
        return len(getattr(self, 'account_capes', [])) > 0

    def update_locker_subtabs(self):
        """Update navigation pill buttons depending on whether capes are owned."""
        if not hasattr(self, 'locker_nav_frame') or not self.locker_nav_frame.winfo_exists():
            return

        for w in self.locker_nav_frame.winfo_children():
            w.destroy()

        views = [("Skins", "Skins")]
        if self.has_owned_capes():
            views.append(("Capes", "Capes"))
        views.append(("Wallpapers", "Wallpapers"))

        self.locker_btns = {}
        for view_name, label_text in views:
            btn = tk.Button(
                self.locker_nav_frame,
                text=label_text,
                font=(FONT_FAMILY, 9, "bold"),
                relief="flat",
                bd=0,
                padx=12,
                pady=4,
                cursor="hand2",
                command=lambda v=view_name: self.switch_locker_view(v)
            )
            btn.pack(side="left", padx=1)
            self.locker_btns[view_name] = btn

        if self.locker_view.get() == "Capes" and not self.has_owned_capes():
            self.locker_view.set("Skins")

    def switch_locker_view(self, view_name: str):
        self.locker_view.set(view_name)
        if view_name == "Capes":
            self.preview_yaw = 200.0  # Orient towards back so cape is immediately visible
        elif view_name == "Skins":
            self.preview_yaw = 30.0   # Orient towards front
        self.refresh_locker_view()

    def refresh_locker_screen_theme(self):
        """Update Locker screen chrome, sub-nav buttons, and content with active theme."""
        main_bg = COLORS['main_bg']
        input_bg = COLORS.get('input_bg', '#1E222B')
        border_col = COLORS.get('card_border', '#2A303F')

        if hasattr(self, 'tabs') and "Locker" in self.tabs and self.tabs["Locker"].winfo_exists():
            self.tabs["Locker"].config(bg=main_bg)
        if hasattr(self, 'locker_header') and self.locker_header.winfo_exists():
            self.locker_header.config(bg=main_bg)
            for child in self.locker_header.winfo_children():
                if isinstance(child, tk.Frame) and child != getattr(self, 'locker_nav_frame', None):
                    child.config(bg=main_bg)
                    for lbl in child.winfo_children():
                        if lbl == getattr(self, 'locker_title_lbl', None):
                            lbl.config(bg=main_bg, fg=COLORS['text_primary'])
                        elif lbl == getattr(self, 'locker_subtitle_lbl', None):
                            lbl.config(bg=main_bg, fg=COLORS['text_secondary'])
        if hasattr(self, 'locker_nav_frame') and self.locker_nav_frame.winfo_exists():
            self.locker_nav_frame.config(bg=input_bg, highlightbackground=border_col)
        if hasattr(self, 'locker_content') and self.locker_content.winfo_exists():
            self.locker_content.config(bg=main_bg)

        self.refresh_locker_view()

    def refresh_locker_view(self):
        current_view = self.locker_view.get()
        accent = COLORS.get('accent_color', COLORS.get('play_btn_green', '#2ECC71'))
        accent_text = COLORS.get('accent_text', '#FFFFFF')
        input_bg = COLORS.get('input_bg', '#1E222B')
        text_primary = COLORS.get('text_primary', '#FFFFFF')

        for name, btn in getattr(self, 'locker_btns', {}).items():
            if not btn.winfo_exists():
                continue
            if name == current_view:
                btn.config(bg=accent, fg=accent_text, activebackground=accent, activeforeground=accent_text)
            else:
                btn.config(bg=input_bg, fg=text_primary, activebackground=input_bg, activeforeground=text_primary)

        if not hasattr(self, 'locker_content') or not self.locker_content.winfo_exists():
            return

        for child in self.locker_content.winfo_children():
            child.destroy()

        if current_view == "Skins":
            self.render_skins_view(self.locker_content)
        elif current_view == "Capes" and self.has_owned_capes():
            self.render_capes_view(self.locker_content)
        else:
            self.render_wallpapers_view(self.locker_content)

    # -------------------------------------------------------------------------
    # 3D INTERACTIVE STAGE & ANIMATION ENGINE
    # -------------------------------------------------------------------------
    def build_3d_stage(self, container: tk.Widget, default_yaw: float = 30.0) -> tk.Frame:
        """Construct the interactive 3D model pedestal stage with drag-to-rotate and walk controls."""
        stage_frame = tk.Frame(container, bg=COLORS['main_bg'])
        stage_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 16), pady=0)

        card_bg = COLORS.get('card_bg', '#222630')
        border_col = COLORS.get('card_border', '#2A303F')
        accent = COLORS.get('accent_color', '#2ECC71')

        self.preview_card = tk.Frame(
            stage_frame,
            bg=card_bg,
            highlightbackground=border_col,
            highlightthickness=1,
            padx=14,
            pady=12
        )
        self.preview_card.pack(fill="both", expand=True)

        # Top Bar of Stage
        top_bar = tk.Frame(self.preview_card, bg=card_bg)
        top_bar.pack(fill="x", pady=(0, 8))

        p = self.profiles[self.current_profile_index] if (self.profiles and 0 <= self.current_profile_index < len(self.profiles)) else {}
        p_name = p.get("name", "Player")
        p_type = p.get("type", "offline").upper()

        badge_frame = tk.Frame(top_bar, bg=COLORS.get('input_bg', '#1E222B'), padx=6, pady=3)
        badge_frame.pack(side="left")
        tk.Label(
            badge_frame,
            text=f"● {p_name} ({p_type})",
            font=(FONT_FAMILY, 8, "bold"),
            bg=COLORS.get('input_bg', '#1E222B'),
            fg=accent
        ).pack(side="left")

        # Current Model Pill
        model_val = p.get("skin_model", "classic")
        self.stage_model_badge = tk.Label(
            top_bar,
            text=f"ARMS: {model_val.upper()}",
            font=(FONT_FAMILY, 8, "bold"),
            bg=COLORS.get('input_bg', '#1E222B'),
            fg=COLORS['text_secondary'],
            padx=6,
            pady=3
        )
        self.stage_model_badge.pack(side="right")

        # Active Cape Pill if equipped
        if getattr(self, 'current_cape_path', None):
            cape_name = "CAPE"
            for c in getattr(self, 'account_capes', []):
                if c.get("local_path") == self.current_cape_path:
                    cape_name = c.get('alias', 'CAPE').upper()
                    break
            self.stage_cape_badge = tk.Label(
                top_bar,
                text=cape_name,
                font=(FONT_FAMILY, 8, "bold"),
                bg=COLORS.get('input_bg', '#1E222B'),
                fg=accent,
                padx=6,
                pady=3
            )
            self.stage_cape_badge.pack(side="right", padx=(0, 6))

        # Canvas for the 3D Skin Preview + Pedestal
        self.preview_canvas = tk.Canvas(
            self.preview_card,
            bg=card_bg,
            width=360,
            height=400,
            highlightthickness=0,
            cursor="hand2"
        )
        self.preview_canvas.pack(fill="both", expand=True, pady=4)
        self._pedestal_drawn = False
        self._bind_canvas_drag(self.preview_canvas)

        # 3D Animation Controls Pill Bar under canvas
        anim_bar = tk.Frame(
            self.preview_card,
            bg=COLORS.get('input_bg', '#1E222B'),
            padx=4,
            pady=3,
            highlightthickness=1,
            highlightbackground=border_col
        )
        anim_bar.pack(pady=(4, 2))

        self.btn_walk_toggle = tk.Button(
            anim_bar,
            text="⏸ Stand" if getattr(self, 'is_walking', True) else "🚶 Walk",
            font=(FONT_FAMILY, 8, "bold"),
            relief="flat",
            bd=0,
            padx=10,
            pady=3,
            cursor="hand2",
            bg=COLORS.get('card_bg', '#222630'),
            fg=COLORS['text_primary'],
            command=self.toggle_walking_animation
        )
        self.btn_walk_toggle.pack(side="left", padx=2)

        b_front = tk.Button(
            anim_bar,
            text="⟲ Front",
            font=(FONT_FAMILY, 8, "bold"),
            relief="flat",
            bd=0,
            padx=8,
            pady=3,
            cursor="hand2",
            bg=COLORS.get('card_bg', '#222630'),
            fg=COLORS['text_secondary'],
            command=lambda: self.reset_preview_rotation(30.0)
        )
        b_front.pack(side="left", padx=2)

        b_rear = tk.Button(
            anim_bar,
            text="↻ Back",
            font=(FONT_FAMILY, 8, "bold"),
            relief="flat",
            bd=0,
            padx=8,
            pady=3,
            cursor="hand2",
            bg=COLORS.get('card_bg', '#222630'),
            fg=COLORS['text_secondary'],
            command=lambda: self.reset_preview_rotation(200.0)
        )
        b_rear.pack(side="left", padx=2)

        # Status indicator / hints
        self.skin_indicator = tk.Label(
            self.preview_card,
            text="Drag to rotate 360°",
            font=(FONT_FAMILY, 8),
            bg=card_bg,
            fg=COLORS['text_muted']
        )
        self.skin_indicator.pack(pady=(1, 8))

        # Action Toolbar at Bottom of Stage (Single spacious row as conceptualized)
        toolbar = tk.Frame(self.preview_card, bg=card_bg)
        toolbar.pack(fill="x", side="bottom")

        b_upload = self._make_btn(
            toolbar,
            "📂 Upload",
            style="primary",
            font_size=9,
            command=self.select_skin
        )
        b_upload.pack(side="left", fill="x", expand=True, padx=(0, 4))

        b_fetch = self._make_btn(
            toolbar,
            "🔍 Steal Skin",
            style="secondary",
            font_size=9,
            command=self.open_player_skin_fetcher
        )
        b_fetch.pack(side="left", fill="x", expand=True, padx=4)

        b_export = self._make_btn(
            toolbar,
            "💾 Export",
            style="secondary",
            font_size=9,
            command=self.export_current_skin
        )
        b_export.pack(side="left", fill="x", expand=True, padx=4)

        b_refresh = self._make_btn(
            toolbar,
            "🔄",
            style="secondary",
            font_size=9,
            command=self.refresh_skin
        )
        b_refresh.pack(side="left", padx=(4, 0))

        self.preview_yaw = default_yaw
        self.start_preview_animation()
        return stage_frame

    def _bind_canvas_drag(self, canvas: tk.Canvas):
        """Bind horizontal mouse dragging for fluid 360-degree rotation."""
        def on_down(e):
            self._drag_start_x = e.x
            self._is_dragging = True
            canvas.config(cursor="sb_h_double_arrow")

        def on_move(e):
            if not getattr(self, '_is_dragging', False):
                return
            dx = e.x - getattr(self, '_drag_start_x', e.x)
            self._drag_start_x = e.x
            self.preview_yaw = (getattr(self, 'preview_yaw', 30.0) + dx * 0.75) % 360.0
            self.render_3d_stage_frame()

        def on_up(e):
            self._is_dragging = False
            canvas.config(cursor="hand2")

        canvas.bind("<Button-1>", on_down)
        canvas.bind("<B1-Motion>", on_move)
        canvas.bind("<ButtonRelease-1>", on_up)

    def render_3d_stage_frame(self):
        """Render a single frame of the 3D model and update canvas without flicker."""
        if not hasattr(self, 'preview_canvas') or not self.preview_canvas.winfo_exists():
            return
        skin_p = getattr(self, 'skin_path', None)
        if not skin_p or not os.path.exists(skin_p):
            self.preview_canvas.delete("all")
            return

        w = self.preview_canvas.winfo_width()
        h = self.preview_canvas.winfo_height()
        if w < 50: w = 360
        if h < 50: h = 400

        model = "classic"
        if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
            model = self.profiles[self.current_profile_index].get("skin_model", "classic")

        cape_path = getattr(self, 'current_cape_path', None)
        yaw = getattr(self, 'preview_yaw', 30.0)
        pitch = getattr(self, 'preview_pitch', 10.0)
        walk_phase = getattr(self, 'preview_walk_phase', 0.0) if getattr(self, 'is_walking', True) else 0.0

        rendered = SkinRenderer3D.render_frame(
            skin_path=skin_p,
            cape_path=cape_path,
            yaw_deg=yaw,
            pitch_deg=pitch,
            walk_phase=walk_phase,
            width=w,
            height=h,
            model=model
        )

        if not rendered:
            return

        self.preview_photo = ImageTk.PhotoImage(rendered)

        # Draw Pedestal once, then reuse image id
        pedestal_y = int(h * 0.86)
        pw, ph = int(min(w * 0.78, 270)), 34

        if not getattr(self, '_pedestal_drawn', False) or getattr(self, '_last_canvas_size', None) != (w, h):
            self.preview_canvas.delete("all")
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
            self._pedestal_drawn = True
            self._last_canvas_size = (w, h)
            self.preview_canvas_img_id = self.preview_canvas.create_image(
                0, 0, image=self.preview_photo, anchor="nw"
            )
        else:
            if hasattr(self, 'preview_canvas_img_id') and self.preview_canvas_img_id:
                self.preview_canvas.itemconfig(self.preview_canvas_img_id, image=self.preview_photo)
            else:
                self.preview_canvas_img_id = self.preview_canvas.create_image(
                    0, 0, image=self.preview_photo, anchor="nw"
                )

    def start_preview_animation(self):
        """Start the lightweight 30 FPS walk cycle loop."""
        if getattr(self, '_anim_running', False):
            return
        self._anim_running = True
        self._tick_preview_animation()

    def stop_preview_animation(self):
        """Stop the animation loop to ensure 0% CPU consumption in background."""
        self._anim_running = False
        if hasattr(self, '_anim_job') and self._anim_job:
            try:
                self.root.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None

    def _tick_preview_animation(self):
        if not getattr(self, '_anim_running', False):
            return
        if getattr(self, 'current_tab', '') != "Locker":
            self.stop_preview_animation()
            return

        if getattr(self, 'is_walking', True):
            self.preview_walk_phase = (getattr(self, 'preview_walk_phase', 0.0) + 0.12) % (math.pi * 2)
            self.render_3d_stage_frame()

        self._anim_job = self.root.after(33, self._tick_preview_animation)

    def toggle_walking_animation(self):
        self.is_walking = not getattr(self, 'is_walking', True)
        if hasattr(self, 'btn_walk_toggle'):
            self.btn_walk_toggle.config(text="⏸ Stand" if self.is_walking else "🚶 Walk")
        if not self.is_walking:
            self.preview_walk_phase = 0.0
        self.render_3d_stage_frame()

    def reset_preview_rotation(self, target_yaw: float = 30.0):
        self.preview_yaw = target_yaw
        self.render_3d_stage_frame()

    # -------------------------------------------------------------------------
    # WARDROBE & SKINS VIEW
    # -------------------------------------------------------------------------
    def render_skins_view(self, parent: tk.Widget):
        container = tk.Frame(parent, bg=COLORS['main_bg'])
        container.pack(expand=True, fill="both", padx=20, pady=(0, 16))

        # Two Column Layout: Left (Showcase Stage), Right (Geometry + Wardrobe Grid)
        container.columnconfigure(0, weight=0, minsize=420)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(0, weight=1)

        # LEFT: 3D SHOWCASE STAGE ("The Pedestal")
        self.build_3d_stage(container, default_yaw=30.0)

        # RIGHT: CONTROLS & WARDROBE PRESETS GRID
        controls_area = tk.Frame(container, bg=COLORS['main_bg'])
        controls_area.grid(row=0, column=1, sticky="nsew")

        card_bg = COLORS.get('card_bg', '#222630')
        border_col = COLORS.get('card_border', '#2A303F')
        accent = COLORS.get('accent_color', '#2ECC71')

        # 1. Top Configuration Card (Geometry + Offline Injection in 2 horizontal columns)
        config_card = tk.Frame(
            controls_area,
            bg=card_bg,
            highlightbackground=border_col,
            highlightthickness=1,
            padx=18,
            pady=14
        )
        config_card.pack(fill="x", pady=(0, 14))
        config_card.columnconfigure(0, weight=1)
        config_card.columnconfigure(1, weight=1)

        # Left Column: Arm Geometry
        geom_box = tk.Frame(config_card, bg=card_bg)
        geom_box.grid(row=0, column=0, sticky="w")

        tk.Label(
            geom_box,
            text="ARM GEOMETRY (MODEL)",
            font=(FONT_FAMILY, 9, "bold"),
            bg=card_bg,
            fg=COLORS['text_secondary']
        ).pack(anchor="w", pady=(0, 6))

        if self.profiles:
            p_prof = self.profiles[self.current_profile_index]
            cur_model = p_prof.get("skin_model", "classic")
            self.skin_model_var = tk.StringVar(value=cur_model)
        else:
            self.skin_model_var = tk.StringVar(value="classic")

        model_chips = tk.Frame(geom_box, bg=card_bg)
        model_chips.pack(anchor="w")

        self.chip_classic = tk.Button(
            model_chips,
            text="Steve (Classic 4px)",
            font=(FONT_FAMILY, 8, "bold"),
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2",
            command=lambda: self._select_skin_model("classic")
        )
        self.chip_classic.pack(side="left", padx=(0, 6))

        self.chip_slim = tk.Button(
            model_chips,
            text="Alex (Slim 3px)",
            font=(FONT_FAMILY, 8, "bold"),
            relief="flat",
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2",
            command=lambda: self._select_skin_model("slim")
        )
        self.chip_slim.pack(side="left")
        self._update_model_chips()

        # Right Column: Multiplayer Skin Injection Toggle
        inj_box = tk.Frame(config_card, bg=card_bg)
        inj_box.grid(row=0, column=1, sticky="e")

        tk.Label(
            inj_box,
            text="OFFLINE SKIN INJECTION",
            font=(FONT_FAMILY, 8, "bold"),
            bg=card_bg,
            fg=COLORS['text_secondary']
        ).pack(anchor="w", pady=(0, 6))

        self.auto_download_var = tk.BooleanVar(value=self.auto_download_mod)
        inj_toggle_row = tk.Frame(inj_box, bg=card_bg)
        inj_toggle_row.pack(anchor="w")

        self.inj_toggle_btn = tk.Button(
            inj_toggle_row,
            text="ON" if self.auto_download_mod else "OFF",
            font=(FONT_FAMILY, 8, "bold"),
            relief="flat",
            bd=0,
            padx=10,
            pady=3,
            cursor="hand2",
            bg=accent if self.auto_download_mod else COLORS.get('input_bg', '#1E222B'),
            fg="#FFFFFF" if self.auto_download_mod else COLORS['text_secondary'],
            command=self._toggle_skin_injection
        )
        self.inj_toggle_btn.pack(side="left", padx=(0, 8))

        tk.Label(
            inj_toggle_row,
            text="Inject in offline sessions",
            font=(FONT_FAMILY, 8),
            bg=card_bg,
            fg=COLORS['text_primary']
        ).pack(side="left")

        # 2. Wardrobe Presets Card (Grid & Collection)
        wardrobe_card = tk.Frame(
            controls_area,
            bg=card_bg,
            highlightbackground=border_col,
            highlightthickness=1,
            padx=16,
            pady=14
        )
        wardrobe_card.pack(fill="both", expand=True)

        # Wardrobe Card Header & Filter Toolbar
        w_header = tk.Frame(wardrobe_card, bg=card_bg)
        w_header.pack(fill="x", pady=(0, 10))

        tk.Label(
            w_header,
            text="SAVED WARDROBE PRESETS",
            font=(FONT_FAMILY, 9, "bold"),
            bg=card_bg,
            fg=COLORS['text_primary']
        ).pack(side="left")

        self.wardrobe_count_lbl = tk.Label(
            w_header,
            text="0 Skins",
            font=(FONT_FAMILY, 8, "bold"),
            bg=COLORS.get('input_bg', '#1E222B'),
            fg=COLORS['text_secondary'],
            padx=6,
            pady=2
        )
        self.wardrobe_count_lbl.pack(side="left", padx=(6, 0))

        b_open_dir = tk.Button(
            w_header,
            text="📁 Open Folder",
            font=(FONT_FAMILY, 8, "bold"),
            relief="flat",
            bd=0,
            bg=COLORS.get('input_bg', '#1E222B'),
            fg=COLORS['text_primary'],
            padx=10,
            pady=3,
            cursor="hand2",
            command=lambda: open_path_in_system(self._get_skins_storage_dir())
        )
        b_open_dir.pack(side="right", padx=(6, 0))

        b_import = self._make_btn(
            w_header,
            "+ Add Skin",
            style="primary",
            font_size=8,
            command=self.select_skin
        )
        b_import.pack(side="right")

        # Search Bar
        search_frame = tk.Frame(
            wardrobe_card,
            bg=COLORS.get('input_bg', '#1E222B'),
            padx=6,
            pady=3,
            highlightthickness=1,
            highlightbackground=border_col
        )
        search_frame.pack(fill="x", pady=(0, 10))

        tk.Label(
            search_frame,
            text="🔍",
            font=(FONT_FAMILY, 8),
            bg=COLORS.get('input_bg', '#1E222B'),
            fg=COLORS['text_secondary']
        ).pack(side="left", padx=(0, 4))

        search_entry = tk.Entry(
            search_frame,
            textvariable=self.wardrobe_search_var,
            font=(FONT_FAMILY, 8),
            bg=COLORS.get('input_bg', '#1E222B'),
            fg=COLORS['text_primary'],
            insertbackground=COLORS['text_primary'],
            relief="flat",
            bd=0
        )
        search_entry.pack(side="left", fill="x", expand=True)
        self.wardrobe_search_var.trace_add("write", lambda *_: self.render_skin_history())

        b_open_dir = tk.Button(
            search_frame,
            text="📁",
            font=(FONT_FAMILY, 9),
            relief="flat",
            bd=0,
            bg=COLORS.get('card_bg', '#222630'),
            fg=COLORS['text_secondary'],
            padx=5,
            pady=1,
            cursor="hand2",
            command=lambda: open_path_in_system(self._get_skins_storage_dir())
        )
        b_open_dir.pack(side="right", padx=(4, 0))

        # Scrollable Wardrobe Grid Area
        grid_container = tk.Frame(wardrobe_card, bg=card_bg)
        grid_container.pack(fill="both", expand=True)

        self.history_canvas = tk.Canvas(grid_container, bg=card_bg, highlightthickness=0)
        self.history_scroll = ttk.Scrollbar(grid_container, orient="vertical", command=self.history_canvas.yview)
        self.history_frame = tk.Frame(self.history_canvas, bg=card_bg)

        self.history_canvas_win = self.history_canvas.create_window((0, 0), window=self.history_frame, anchor="nw")
        self.history_canvas.configure(yscrollcommand=self.history_scroll.set)

        self.history_frame.bind(
            "<Configure>",
            lambda e: self.history_canvas.configure(scrollregion=self.history_canvas.bbox("all"))
        )
        self.history_canvas.bind(
            "<Configure>",
            lambda e: self.history_canvas.itemconfig(self.history_canvas_win, width=e.width)
        )

        self._bind_wheel_events(
            self.history_canvas,
            lambda e, c=self.history_canvas: self._smooth_scroll(c, e),
            f"direct_{id(self.history_canvas)}"
        )
        self._bind_smooth_scroll(self.history_canvas, self.history_frame)

        self.history_canvas.pack(side="left", fill="both", expand=True)
        self.history_scroll.pack(side="right", fill="y")

        # Initial render of skins and preview
        self.render_skin_history()
        self.render_preview()
        self.update_skin_indicator()
        if self.profiles:
            self.update_active_profile()

    def _select_skin_model(self, model_name: str):
        self.skin_model_var.set(model_name)
        self._update_model_chips()
        self.update_skin_model()

    def _update_model_chips(self):
        val = getattr(self, 'skin_model_var', None)
        cur = val.get() if val else "classic"
        accent = COLORS.get('accent_color', '#2ECC71')
        input_bg = COLORS.get('input_bg', '#1E222B')

        if hasattr(self, 'chip_classic') and self.chip_classic.winfo_exists():
            if cur == "classic":
                self.chip_classic.config(bg=accent, fg="#FFFFFF")
            else:
                self.chip_classic.config(bg=input_bg, fg=COLORS['text_secondary'])

        if hasattr(self, 'chip_slim') and self.chip_slim.winfo_exists():
            if cur == "slim":
                self.chip_slim.config(bg=accent, fg="#FFFFFF")
            else:
                self.chip_slim.config(bg=input_bg, fg=COLORS['text_secondary'])

        if hasattr(self, 'stage_model_badge') and self.stage_model_badge.winfo_exists():
            self.stage_model_badge.config(text=f"ARMS: {cur.upper()}")

    def _toggle_skin_injection(self):
        new_val = not self.auto_download_var.get()
        self.auto_download_var.set(new_val)
        self._set_auto_download(new_val)
        accent = COLORS.get('accent_color', '#2ECC71')
        input_bg = COLORS.get('input_bg', '#1E222B')

        if hasattr(self, 'inj_toggle_btn') and self.inj_toggle_btn.winfo_exists():
            self.inj_toggle_btn.config(
                text="ON" if new_val else "OFF",
                bg=accent if new_val else input_bg,
                fg="#FFFFFF" if new_val else COLORS['text_secondary']
            )
        self.update_skin_indicator()

    def _get_skins_storage_dir(self) -> str:
        skins_dir = os.path.join(str(get_launcher_data_dir()), "skins")
        os.makedirs(skins_dir, exist_ok=True)
        return skins_dir

    def render_skin_history(self):
        if not hasattr(self, 'history_frame') or not self.history_frame.winfo_exists():
            return

        for w in self.history_frame.winfo_children():
            w.destroy()

        if not self.profiles or not (0 <= self.current_profile_index < len(self.profiles)):
            return

        p = self.profiles[self.current_profile_index]
        history = cast(list, p.get("skin_history", []))
        query = self.wardrobe_search_var.get().strip().lower()

        filtered_items = []
        for idx, item in enumerate(history):
            if isinstance(item, str):
                path = item
                model = "classic"
                name = os.path.splitext(os.path.basename(path))[0]
            else:
                path = item.get("path", "")
                model = item.get("model", "classic")
                name = item.get("name") or os.path.splitext(os.path.basename(path))[0]

            if not path or not os.path.exists(path):
                continue

            if query and query not in name.lower() and query not in model.lower():
                continue

            filtered_items.append((idx, path, model, name))

        if hasattr(self, 'wardrobe_count_lbl') and self.wardrobe_count_lbl.winfo_exists():
            self.wardrobe_count_lbl.config(text=f"{len(filtered_items)} Skins")

        if not filtered_items:
            empty_box = tk.Frame(self.history_frame, bg=COLORS.get('card_bg', '#222630'), pady=30)
            empty_box.pack(fill="both", expand=True)
            tk.Label(
                empty_box,
                text="No skins found in wardrobe.",
                font=(FONT_FAMILY, 10),
                bg=COLORS.get('card_bg', '#222630'),
                fg=COLORS['text_secondary']
            ).pack()
            return

        # Render 2-Column Grid of Wardrobe Cards
        self.history_frame.columnconfigure(0, weight=1)
        self.history_frame.columnconfigure(1, weight=1)

        card_bg = COLORS.get('input_bg', '#1E222B')
        border_col = COLORS.get('card_border', '#2A303F')
        accent = COLORS.get('accent_color', '#2ECC71')
        cur_skin_path = os.path.abspath(self.skin_path) if self.skin_path else ""

        for card_idx, (orig_idx, path, model, name) in enumerate(filtered_items):
            is_equipped = cur_skin_path and os.path.abspath(path) == cur_skin_path

            card = tk.Frame(
                self.history_frame,
                bg=card_bg,
                highlightthickness=1,
                highlightbackground=accent if is_equipped else border_col,
                padx=10,
                pady=10,
                cursor="hand2"
            )
            col = card_idx % 2
            row = card_idx // 2
            card.grid(row=row, column=col, sticky="nsew", padx=4, pady=4)

            # Left: Head Avatar Icon
            head = self.get_head_from_skin(path, size=44)
            if head:
                icon_lbl = tk.Label(card, image=head, bg=card_bg)
                icon_lbl.image = head  # type: ignore
                icon_lbl.pack(side="left", padx=(0, 10))

            # Center: Title & Model Tag
            info = tk.Frame(card, bg=card_bg)
            info.pack(side="left", fill="both", expand=True)

            disp_name = name if len(name) <= 16 else f"{name[:13]}..."
            name_lbl = tk.Label(
                info,
                text=disp_name,
                font=(FONT_FAMILY, 9, "bold"),
                bg=card_bg,
                fg=COLORS['text_primary'],
                anchor="w"
            )
            name_lbl.pack(fill="x")

            model_badge = tk.Label(
                info,
                text=f"{model.upper()}",
                font=(FONT_FAMILY, 7, "bold"),
                bg=COLORS.get('card_bg', '#222630'),
                fg=COLORS['text_secondary'],
                padx=4,
                pady=1,
                anchor="w"
            )
            model_badge.pack(anchor="w", pady=(3, 0))

            # Right: Equip Status or Button
            right_box = tk.Frame(card, bg=card_bg)
            right_box.pack(side="right")

            if is_equipped:
                status_lbl = tk.Label(
                    right_box,
                    text="✓ EQUIPPED",
                    font=(FONT_FAMILY, 8, "bold"),
                    bg=accent,
                    fg="#FFFFFF",
                    padx=6,
                    pady=3
                )
                status_lbl.pack()
            else:
                eq_btn = tk.Button(
                    right_box,
                    text="Equip",
                    font=(FONT_FAMILY, 8, "bold"),
                    relief="flat",
                    bd=0,
                    bg=COLORS.get('card_bg', '#222630'),
                    fg=COLORS['text_primary'],
                    padx=8,
                    pady=3,
                    cursor="hand2",
                    command=lambda p=path, m=model: self.apply_history_skin(p, m)
                )
                eq_btn.pack()

            # Click on card equips skin
            def _bind_equip(widget, p=path, m=model):
                widget.bind("<Button-1>", lambda _e: self.apply_history_skin(p, m))

            _bind_equip(card)
            _bind_equip(info)
            _bind_equip(name_lbl)

            # Context Menu for Card
            def make_menu_handler(p=path, m=model, i=orig_idx, n=name):
                def show_menu(event):
                    menu = NeoContextMenu(self.root)
                    menu.add_item("👕 Equip Skin", lambda: self.apply_history_skin(p, m))
                    menu.add_item("✏️ Rename Preset", lambda: self.rename_wardrobe_preset(i, n))
                    menu.add_item("💾 Export PNG", lambda: self._export_specific_skin(p))
                    menu.add_item("📁 Open in File Manager", lambda: open_path_in_system(os.path.dirname(p)))
                    menu.add_separator()
                    menu.add_item("🗑 Remove from Wardrobe", lambda: self.remove_skin_from_history(i), is_danger=True)
                    menu.show_at(event.x_root, event.y_root)
                return show_menu

            attach_context_menu(card, make_menu_handler())

    def rename_wardrobe_preset(self, index: int, old_name: str):
        mgr = get_modal_manager(self.root)
        if not mgr:
            return

        def build_content(body, close):
            tk.Label(
                body,
                text="Rename Wardrobe Preset",
                font=(FONT_FAMILY, 12, "bold"),
                bg=COLORS['card_bg'],
                fg=COLORS['text_primary']
            ).pack(anchor="w", pady=(0, 6))

            name_var = tk.StringVar(value=old_name)
            entry = tk.Entry(
                body,
                textvariable=name_var,
                font=(FONT_FAMILY, 10),
                bg=COLORS.get('input_bg', '#1E222B'),
                fg=COLORS['text_primary'],
                insertbackground=COLORS['text_primary'],
                relief="flat",
                bd=0
            )
            entry.pack(fill="x", pady=(0, 16), ipady=4)
            entry.focus_set()

            def on_save():
                new_n = name_var.get().strip()
                if new_n and self.profiles:
                    p = self.profiles[self.current_profile_index]
                    hist = p.get("skin_history", [])
                    if 0 <= index < len(hist):
                        item = hist[index]
                        if isinstance(item, str):
                            hist[index] = {"path": item, "model": "classic", "name": new_n}
                        else:
                            item["name"] = new_n
                        self.save_profiles()
                        self.render_skin_history()
                close()

            btn_row = tk.Frame(body, bg=COLORS['card_bg'])
            btn_row.pack(fill="x", side="bottom")

            self._make_btn(btn_row, "Cancel", style="secondary", font_size=9, command=close).pack(side="left")
            self._make_btn(btn_row, "Save", style="primary", font_size=9, command=on_save).pack(side="right")

        mgr.show_modal("Rename Preset", build_content, width=380, height=180)

    def _export_specific_skin(self, path: str):
        if not os.path.exists(path):
            return
        out_file = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export Skin PNG",
            defaultextension=".png",
            initialfile=os.path.basename(path),
            filetypes=[("PNG Image", "*.png")]
        )
        if out_file:
            try:
                shutil.copy2(path, out_file)
                if hasattr(self, 'toast_manager'):
                    self.toast_manager.show(f"Skin exported: {os.path.basename(out_file)}", level="success")
                elif hasattr(self.root, 'toast_manager'):
                    self.root.toast_manager.show(f"Skin exported: {os.path.basename(out_file)}", level="success")
                else:
                    custom_showinfo("Exported", f"Skin saved to:\n{out_file}", parent=self.root)
            except Exception as e:
                custom_showerror("Error", f"Failed to export: {e}", parent=self.root)

    def remove_skin_from_history(self, index: int):
        if not self.profiles:
            return
        p_prof = self.profiles[self.current_profile_index]
        hist = p_prof.get("skin_history", [])
        if 0 <= index < len(hist):
            hist.pop(index)
            p_prof["skin_history"] = hist
            self.save_profiles()
            self.render_skin_history()

    # -------------------------------------------------------------------------
    # ONLINE PLAYER SKIN STEALER / FETCHER MODAL
    # -------------------------------------------------------------------------
    def open_player_skin_fetcher(self):
        mgr = get_modal_manager(self.root)
        if not mgr:
            return

        def build_content(body, close):
            tk.Label(
                body,
                text="Fetch & Import Player Skin",
                font=(FONT_FAMILY, 12, "bold"),
                bg=COLORS['card_bg'],
                fg=COLORS['text_primary']
            ).pack(anchor="w", pady=(0, 4))

            tk.Label(
                body,
                text="Enter any Minecraft username to preview and equip their skin.",
                font=(FONT_FAMILY, 9),
                bg=COLORS['card_bg'],
                fg=COLORS['text_secondary']
            ).pack(anchor="w", pady=(0, 12))

            # Input Row
            in_row = tk.Frame(body, bg=COLORS.get('input_bg', '#1E222B'), padx=8, pady=4)
            in_row.pack(fill="x", pady=(0, 14))

            user_var = tk.StringVar(value="")
            entry = tk.Entry(
                in_row,
                textvariable=user_var,
                font=(FONT_FAMILY, 10),
                bg=COLORS.get('input_bg', '#1E222B'),
                fg=COLORS['text_primary'],
                insertbackground=COLORS['text_primary'],
                relief="flat",
                bd=0
            )
            entry.pack(side="left", fill="x", expand=True)
            entry.focus_set()

            # Preview Section
            preview_container = tk.Frame(body, bg=COLORS['card_bg'])
            preview_container.pack(fill="both", expand=True)

            preview_canvas = tk.Canvas(preview_container, bg=COLORS.get('input_bg', '#1E222B'), width=180, height=220, highlightthickness=0)
            preview_canvas.pack(side="left", fill="both", expand=True, padx=(0, 12))

            info_box = tk.Frame(preview_container, bg=COLORS['card_bg'])
            info_box.pack(side="right", fill="both", expand=True)

            status_lbl = tk.Label(info_box, text="Enter a username and click Fetch", font=(FONT_FAMILY, 9), bg=COLORS['card_bg'], fg=COLORS['text_secondary'], wraplength=220, justify="left")
            status_lbl.pack(anchor="w", pady=(10, 8))

            action_row = tk.Frame(info_box, bg=COLORS['card_bg'])
            action_row.pack(side="bottom", fill="x", pady=6)

            fetched_data = {"path": None, "model": "classic", "photo": None}

            def do_fetch():
                u = user_var.get().strip()
                if not u:
                    return
                status_lbl.config(text=f"Fetching profile for '{u}'...", fg=COLORS['text_primary'])

                def worker():
                    try:
                        # 1. Mojang UUID lookup
                        mojang_url = f"https://api.mojang.com/users/profiles/minecraft/{u}"
                        req = urllib.request.Request(mojang_url, headers={"User-Agent": "NLC-Launcher"})
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            data = json.loads(resp.read().decode())
                            uuid_str = data.get("id")

                        # 2. Session server textures
                        session_url = f"https://sessionserver.mojang.com/session/minecraft/profile/{uuid_str}"
                        req_s = urllib.request.Request(session_url, headers={"User-Agent": "NLC-Launcher"})
                        with urllib.request.urlopen(req_s, timeout=5) as resp_s:
                            data_s = json.loads(resp_s.read().decode())
                            props = data_s.get("properties", [])
                            skin_url = None
                            model = "classic"
                            for prop in props:
                                if prop.get("name") == "textures":
                                    val_b64 = prop.get("value")
                                    tex_data = json.loads(base64.b64decode(val_b64).decode())
                                    skin_info = tex_data.get("textures", {}).get("SKIN", {})
                                    skin_url = skin_info.get("url")
                                    if skin_info.get("metadata", {}).get("model") == "slim":
                                        model = "slim"
                                    break

                        if not skin_url:
                            self.root.after(0, lambda: status_lbl.config(text="Player has no custom skin.", fg=COLORS['text_secondary']))
                            return

                        # Download Skin PNG
                        skins_dir = self._get_skins_storage_dir()
                        dest_path = os.path.join(skins_dir, f"{u}_{int(time.time())}.png")
                        urllib.request.urlretrieve(skin_url, dest_path)

                        fetched_data["path"] = dest_path
                        fetched_data["model"] = model

                        # Render 2.5D preview
                        rendered = SkinRenderer3D.render(dest_path, model=model, height=190)
                        if rendered:
                            photo = ImageTk.PhotoImage(rendered)
                            fetched_data["photo"] = photo

                        def on_success():
                            preview_canvas.delete("all")
                            if fetched_data.get("photo"):
                                cw = preview_canvas.winfo_width() or 180
                                ch = preview_canvas.winfo_height() or 220
                                preview_canvas.create_image(cw // 2, ch // 2, image=fetched_data["photo"], anchor="center")
                            status_lbl.config(text=f"Found: {u}\nModel: {model.title()}\nUUID: {uuid_str[:12]}...", fg=COLORS.get('accent_color', '#2ECC71'))
                            b_equip.config(state="normal")
                            b_save.config(state="normal")

                        self.root.after(0, on_success)

                    except Exception as exc:
                        logger.debug("Mojang fetch failed: %s, trying Minotar fallback", exc)
                        # Fallback to Minotar skin URL
                        try:
                            fallback_url = f"https://minotar.net/skin/{u}"
                            skins_dir = self._get_skins_storage_dir()
                            dest_path = os.path.join(skins_dir, f"{u}_{int(time.time())}.png")
                            urllib.request.urlretrieve(fallback_url, dest_path)

                            fetched_data["path"] = dest_path
                            fetched_data["model"] = "classic"
                            rendered = SkinRenderer3D.render(dest_path, model="classic", height=190)
                            photo = ImageTk.PhotoImage(rendered) if rendered else None
                            fetched_data["photo"] = photo

                            def on_fallback():
                                preview_canvas.delete("all")
                                if fetched_data.get("photo"):
                                    cw = preview_canvas.winfo_width() or 180
                                    ch = preview_canvas.winfo_height() or 220
                                    preview_canvas.create_image(cw // 2, ch // 2, image=fetched_data["photo"], anchor="center")
                                status_lbl.config(text=f"Found: {u} (Fallback)\nModel: Classic", fg=COLORS.get('accent_color', '#2ECC71'))
                                b_equip.config(state="normal")
                                b_save.config(state="normal")

                            self.root.after(0, on_fallback)
                        except Exception as e2:
                            self.root.after(0, lambda: status_lbl.config(text=f"Could not load skin: {e2}", fg=COLORS.get('error_red', '#EF4444')))

                threading.Thread(target=worker, daemon=True).start()

            fetch_btn = self._make_btn(in_row, "Fetch ⚡", style="primary", font_size=9, command=do_fetch)
            fetch_btn.pack(side="right")
            entry.bind("<Return>", lambda _e: do_fetch())

            def on_equip():
                p_path = fetched_data.get("path")
                p_mod = fetched_data.get("model", "classic")
                if p_path and os.path.exists(p_path):
                    self.apply_history_skin(p_path, p_mod)
                    close()

            def on_save_to_wardrobe():
                p_path = fetched_data.get("path")
                p_mod = fetched_data.get("model", "classic")
                if p_path and os.path.exists(p_path):
                    self.add_skin_to_history(p_path, p_mod)
                    self.render_skin_history()
                    if hasattr(self, 'toast_manager'):
                        self.toast_manager.show("Skin saved to wardrobe presets!", level="success")
                    elif hasattr(self.root, 'toast_manager'):
                        self.root.toast_manager.show("Skin saved to wardrobe presets!", level="success")
                    else:
                        custom_showinfo("Saved", "Skin saved to wardrobe presets!", parent=self.root)

            b_equip = self._make_btn(action_row, "Equip Now", style="primary", font_size=9, command=on_equip)
            b_equip.pack(side="left", padx=(0, 6))
            b_equip.config(state="disabled")

            b_save = self._make_btn(action_row, "Save", style="secondary", font_size=9, command=on_save_to_wardrobe)
            b_save.pack(side="left")
            b_save.config(state="disabled")

        mgr.show_modal("Fetch Player Skin", build_content, width=540, height=420)

    # -------------------------------------------------------------------------
    # OFFICIAL ACCOUNT CAPES INTEGRATION & CAPE STUDIO
    # -------------------------------------------------------------------------
    def load_account_capes_async(self):
        """Asynchronously retrieve official capes from Minecraft Services API if Microsoft account."""
        if not getattr(self, 'profiles', None) or not (0 <= getattr(self, 'current_profile_index', 0) < len(self.profiles)):
            self.account_capes = []
            self.current_cape_path = None
            self.update_locker_subtabs()
            return

        p = self.profiles[self.current_profile_index]
        if p.get("type") != "microsoft":
            self.account_capes = []
            self.current_cape_path = None
            self.update_locker_subtabs()
            return

        token = p.get("access_token")

        # Synchronously check cached capes first for instantaneous zero-latency UI display
        cached_capes = p.get("owned_capes", [])
        if not cached_capes:
            capes_dir = os.path.join(get_launcher_data_dir(), "capes")
            if os.path.exists(capes_dir):
                detected = []
                for fname in sorted(os.listdir(capes_dir)):
                    if fname.endswith(".png"):
                        alias = fname[:-4].capitalize()
                        c_path = os.path.join(capes_dir, fname)
                        state = "ACTIVE" if c_path == p.get("cape_path") else "INACTIVE"
                        detected.append({
                            "id": f"cached-{fname[:-4]}",
                            "state": state,
                            "alias": alias,
                            "local_path": c_path
                        })
                if detected:
                    cached_capes = detected
                    p["owned_capes"] = detected

        if cached_capes:
            self.account_capes = cached_capes
            if p.get("cape_path") and os.path.exists(p.get("cape_path")):
                self.current_cape_path = p.get("cape_path")
            self.update_locker_subtabs()

        if not token:
            return

        def _fetch_worker():
            capes = fetch_account_capes(token)
            active_path = None
            if capes:
                for c in capes:
                    alias = c.get("alias", "cape")
                    c_path = download_and_cache_cape(c.get("url", ""), alias)
                    c["local_path"] = c_path
                    if c.get("state") == "ACTIVE":
                        active_path = c_path

            def _on_done():
                if capes:
                    self.account_capes = capes
                    p["owned_capes"] = capes
                    if active_path:
                        self.current_cape_path = active_path
                        p["cape_path"] = active_path
                    elif p.get("cape_path") and os.path.exists(p.get("cape_path")):
                        self.current_cape_path = p.get("cape_path")
                    if hasattr(self, 'save_config'):
                        self.save_config()
                self.update_locker_subtabs()
                self.render_3d_stage_frame()
                if getattr(self, 'locker_view', None) and self.locker_view.get() == "Capes":
                    self.refresh_locker_view()

            try:
                if hasattr(self, 'root') and self.root.winfo_exists():
                    self.root.after(0, _on_done)
            except Exception:
                pass

        threading.Thread(target=_fetch_worker, daemon=True).start()

    def get_cape_thumbnail(self, cape_dict: Dict[str, Any], height: int = 36) -> Optional[ImageTk.PhotoImage]:
        """Generate a 2D thumbnail swatch of the cape back face (1:1.6 aspect ratio)."""
        if not hasattr(self, '_cape_thumb_cache'):
            self._cape_thumb_cache = {}

        local_path = cape_dict.get("local_path")
        if not local_path or not os.path.exists(local_path):
            url = cape_dict.get("url", "")
            alias = cape_dict.get("alias", "cape")
            local_path = download_and_cache_cape(url, alias)
            cape_dict["local_path"] = local_path

        if not local_path or not os.path.exists(local_path):
            return None

        cache_key = (local_path, height)
        if cache_key in self._cape_thumb_cache:
            return self._cape_thumb_cache[cache_key]

        try:
            img = Image.open(local_path).convert("RGBA")
            back_face = img.crop((1, 1, 11, 17))
            w = int(height * (10.0 / 16.0))
            thumb = back_face.resize((max(1, w), height), RESAMPLE_NEAREST)
            photo = ImageTk.PhotoImage(thumb)
            self._cape_thumb_cache[cache_key] = photo
            return photo
        except Exception as e:
            logger.error("Failed to generate cape thumbnail: %s", e)
            return None

    def render_capes_view(self, parent: tk.Widget):
        """Render the Cape Studio showcasing owned official Minecraft capes."""
        container = tk.Frame(parent, bg=COLORS['main_bg'])
        container.pack(expand=True, fill="both", padx=20, pady=(0, 16))

        container.columnconfigure(0, weight=0, minsize=420)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(0, weight=1)

        # LEFT: 3D Stage pre-turned to 150 degrees (rear view to highlight the cape)
        self.build_3d_stage(container, default_yaw=150.0)

        # RIGHT: Cape Selection Studio Card
        controls_area = tk.Frame(container, bg=COLORS['main_bg'])
        controls_area.grid(row=0, column=1, sticky="nsew")

        card_bg = COLORS.get('card_bg', '#222630')
        border_col = COLORS.get('card_border', '#2A303F')
        accent = COLORS.get('accent_color', '#2ECC71')

        capes_card = tk.Frame(
            controls_area,
            bg=card_bg,
            highlightbackground=border_col,
            highlightthickness=1,
            padx=16,
            pady=14
        )
        capes_card.pack(fill="both", expand=True)

        # Header
        c_header = tk.Frame(capes_card, bg=card_bg)
        c_header.pack(fill="x", pady=(0, 10))

        tk.Label(
            c_header,
            text="MINECRAFT CAPES",
            font=(FONT_FAMILY, 9, "bold"),
            bg=card_bg,
            fg=COLORS['text_primary']
        ).pack(side="left")

        num_capes = len(getattr(self, 'account_capes', []))
        tk.Label(
            c_header,
            text=f"{num_capes} Capes",
            font=(FONT_FAMILY, 8, "bold"),
            bg=COLORS.get('input_bg', '#1E222B'),
            fg=COLORS['text_secondary'],
            padx=6,
            pady=2
        ).pack(side="left", padx=(6, 0))

        # Unequip action on right
        b_unequip = tk.Button(
            c_header,
            text="Unequip Cape",
            font=(FONT_FAMILY, 8, "bold"),
            relief="flat",
            bd=0,
            bg=COLORS.get('input_bg', '#1E222B'),
            fg=COLORS['text_primary'],
            padx=8,
            pady=3,
            cursor="hand2",
            command=self.unequip_active_cape
        )
        b_unequip.pack(side="right")

        b_sync = tk.Button(
            c_header,
            text="🔄 Sync",
            font=(FONT_FAMILY, 8, "bold"),
            relief="flat",
            bd=0,
            bg=COLORS.get('input_bg', '#1E222B'),
            fg=COLORS['text_secondary'],
            padx=8,
            pady=3,
            cursor="hand2",
            command=self.load_account_capes_async
        )
        b_sync.pack(side="right", padx=(0, 6))

        tk.Label(
            capes_card,
            text="Official Minecraft capes retrieved from your account. Select a cape to equip it.",
            font=(FONT_FAMILY, 8),
            bg=card_bg,
            fg=COLORS['text_secondary'],
            anchor="w"
        ).pack(fill="x", pady=(0, 10))

        # Scrollable Cape List Frame
        scroll_box = tk.Frame(capes_card, bg=card_bg)
        scroll_box.pack(fill="both", expand=True)

        canvas = tk.Canvas(scroll_box, bg=card_bg, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_box, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=card_bg)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        cw = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        if not getattr(self, 'account_capes', []):
            empty_box = tk.Frame(scrollable_frame, bg=card_bg, pady=30)
            empty_box.pack(fill="both", expand=True)
            tk.Label(
                empty_box,
                text="No capes found on this account.",
                font=(FONT_FAMILY, 9),
                bg=card_bg,
                fg=COLORS['text_secondary']
            ).pack()
            return

        for cape in self.account_capes:
            self._render_cape_card(scrollable_frame, cape)

    def _render_cape_card(self, parent: tk.Widget, cape: Dict[str, Any]):
        c_id = cape.get("id")
        alias = cape.get("alias", "Minecraft Cape")
        local_path = cape.get("local_path")
        state = cape.get("state", "INACTIVE")
        is_equipped = (state == "ACTIVE") or (local_path and local_path == getattr(self, 'current_cape_path', None))

        card_bg = COLORS.get('input_bg', '#1E222B')
        border_col = COLORS.get('card_border', '#2A303F')
        accent = COLORS.get('accent_color', '#2ECC71')

        card = tk.Frame(
            parent,
            bg=card_bg,
            highlightthickness=1,
            highlightbackground=accent if is_equipped else border_col,
            padx=12,
            pady=10,
            cursor="hand2"
        )
        card.pack(fill="x", pady=4, padx=2)

        # Right: Status / Button
        right_box = tk.Frame(card, bg=card_bg)
        right_box.pack(side="right", padx=(6, 0))

        if is_equipped:
            tk.Label(
                right_box,
                text="✓ EQUIPPED",
                font=(FONT_FAMILY, 7, "bold"),
                bg=accent,
                fg="#FFFFFF",
                padx=6,
                pady=2
            ).pack()
        else:
            tk.Button(
                right_box,
                text="Equip",
                font=(FONT_FAMILY, 8, "bold"),
                relief="flat",
                bd=0,
                bg=COLORS.get('card_bg', '#222630'),
                fg=COLORS['text_primary'],
                padx=10,
                pady=3,
                cursor="hand2",
                command=lambda c=cape: self.equip_account_cape(c)
            ).pack()

        # Left: Cape Swatch Thumbnail (back texture)
        thumb = self.get_cape_thumbnail(cape, height=36)
        if thumb:
            lbl_thumb = tk.Label(card, image=thumb, bg=card_bg)
            lbl_thumb.image = thumb  # retain reference
            lbl_thumb.pack(side="left", padx=(0, 12))

        # Center: Name & Tag
        info = tk.Frame(card, bg=card_bg)
        info.pack(side="left", fill="x", expand=True)

        tk.Label(
            info,
            text=alias,
            font=(FONT_FAMILY, 9, "bold"),
            bg=card_bg,
            fg=COLORS['text_primary'],
            anchor="w"
        ).pack(fill="x")

        tk.Label(
            info,
            text="OFFICIAL MOJANG CAPE",
            font=(FONT_FAMILY, 7, "bold"),
            bg=COLORS.get('card_bg', '#222630'),
            fg=COLORS['text_secondary'],
            padx=4,
            pady=1,
            anchor="w"
        ).pack(anchor="w", pady=(2, 0))

        def _on_click(_e):
            self.equip_account_cape(cape)

        card.bind("<Button-1>", _on_click)
        info.bind("<Button-1>", _on_click)

    def equip_account_cape(self, cape: Dict[str, Any]):
        """Equip chosen cape on 3D model and sync with Mojang servers."""
        p = self.profiles[self.current_profile_index] if self.profiles else {}
        token = p.get("access_token")
        c_id = cape.get("id")
        local_path = cape.get("local_path")

        self.current_cape_path = local_path
        p["cape_path"] = local_path or ""
        p["active_cape_id"] = c_id or ""

        for c in getattr(self, 'account_capes', []):
            if c.get("id") == c_id:
                c["state"] = "ACTIVE"
            else:
                c["state"] = "INACTIVE"

        self.render_3d_stage_frame()
        self.refresh_locker_view()

        if token and c_id:
            def _sync():
                set_active_mojang_cape(token, c_id)
            threading.Thread(target=_sync, daemon=True).start()

    def unequip_active_cape(self):
        """Unequip active cape from 3D model and Mojang account."""
        p = self.profiles[self.current_profile_index] if self.profiles else {}
        token = p.get("access_token")

        self.current_cape_path = None
        if "cape_path" in p:
            p["cape_path"] = ""
        if "active_cape_id" in p:
            p["active_cape_id"] = ""

        for c in getattr(self, 'account_capes', []):
            c["state"] = "INACTIVE"

        self.render_3d_stage_frame()
        self.refresh_locker_view()

        if token:
            def _sync():
                clear_active_mojang_cape(token)
            threading.Thread(target=_sync, daemon=True).start()

    def get_wallpaper_thumbnail(self, path: str, size: Tuple[int, int] = (220, 124)) -> Optional[ImageTk.PhotoImage]:
        """Load or create a lightweight, disk-persisted and memory-cached thumbnail for a wallpaper."""
        if not path or not os.path.exists(path):
            return None

        if not hasattr(self, '_wallpaper_thumb_cache'):
            self._wallpaper_thumb_cache = {}

        try:
            stat = os.stat(path)
            cache_key = (path, stat.st_mtime, stat.st_size, size)
            if cache_key in self._wallpaper_thumb_cache:
                return self._wallpaper_thumb_cache[cache_key]

            cache_dir = os.path.join(self.config_dir, "cache", "wallpaper_thumbs")
            os.makedirs(cache_dir, exist_ok=True)
            disk_key = hashlib.md5(f"{path}_{stat.st_mtime}_{stat.st_size}_{size[0]}x{size[1]}".encode('utf-8')).hexdigest()
            disk_path = os.path.join(cache_dir, f"{disk_key}.jpg")

            if os.path.isfile(disk_path):
                try:
                    with Image.open(disk_path) as cached_im:
                        photo = ImageTk.PhotoImage(cached_im.copy())
                        self._wallpaper_thumb_cache[cache_key] = photo
                        return photo
                except Exception:
                    pass

            # Generate compressed thumbnail
            with Image.open(path) as raw_im:
                im = raw_im.convert("RGB")
                im.thumbnail(size, Image.Resampling.BILINEAR)
                try:
                    im.save(disk_path, "JPEG", quality=82, optimize=True)
                except Exception:
                    pass
                photo = ImageTk.PhotoImage(im)
                self._wallpaper_thumb_cache[cache_key] = photo
                return photo
        except Exception as e:
            logger.debug("Failed creating wallpaper thumbnail for %s: %s", path, e)
            return None

    # -------------------------------------------------------------------------
    # WALLPAPERS STUDIO VIEW
    # -------------------------------------------------------------------------
    def render_wallpapers_view(self, parent: tk.Widget):
        container = tk.Frame(parent, bg=COLORS['main_bg'])
        container.pack(fill="both", expand=True, padx=40, pady=(0, 20))

        card_bg = COLORS.get('card_bg', '#222630')
        border_col = COLORS.get('card_border', '#2A303F')
        accent = COLORS.get('accent_color', '#2ECC71')

        # 1. Hero Banner: Current Active Wallpaper
        hero_card = tk.Frame(
            container,
            bg=card_bg,
            highlightbackground=border_col,
            highlightthickness=1,
            padx=20,
            pady=16
        )
        hero_card.pack(fill="x", pady=(0, 16))

        cur_wp = getattr(self, 'current_wallpaper', None)
        cur_wp_name = os.path.basename(cur_wp) if cur_wp else "None"

        # Hero Thumbnail on Left
        thumb_frame = tk.Frame(hero_card, bg=card_bg, width=220, height=120)
        thumb_frame.pack(side="left", padx=(0, 20))
        thumb_frame.pack_propagate(False)

        if cur_wp and os.path.exists(cur_wp):
            tk_thumb = self.get_wallpaper_thumbnail(cur_wp, size=(220, 120))
            if tk_thumb:
                lbl_thumb = tk.Label(thumb_frame, image=tk_thumb, bg=card_bg)
                lbl_thumb.image = tk_thumb  # type: ignore
                lbl_thumb.pack(fill="both", expand=True)
            else:
                tk.Label(thumb_frame, text="No Preview", font=(FONT_FAMILY, 10), bg=card_bg, fg=COLORS['text_secondary']).pack(expand=True)
        else:
            tk.Label(thumb_frame, text="No Wallpaper", font=(FONT_FAMILY, 10), bg=card_bg, fg=COLORS['text_secondary']).pack(expand=True)

        # Hero Info & Actions
        hero_info = tk.Frame(hero_card, bg=card_bg)
        hero_info.pack(side="left", fill="both", expand=True)

        badge_row = tk.Frame(hero_info, bg=card_bg)
        badge_row.pack(anchor="w")

        tk.Label(
            badge_row,
            text="● CURRENT ACTIVE WALLPAPER",
            font=(FONT_FAMILY, 8, "bold"),
            bg=COLORS.get('input_bg', '#1E222B'),
            fg=accent,
            padx=8,
            pady=3
        ).pack(side="left")

        tk.Label(
            hero_info,
            text=cur_wp_name,
            font=(FONT_FAMILY, 12, "bold"),
            bg=card_bg,
            fg=COLORS['text_primary']
        ).pack(anchor="w", pady=(6, 2))

        tk.Label(
            hero_info,
            text="High-resolution launcher background • Synced with your active profile settings",
            font=(FONT_FAMILY, 9),
            bg=card_bg,
            fg=COLORS['text_secondary']
        ).pack(anchor="w", pady=(0, 10))

        hero_acts = tk.Frame(hero_info, bg=card_bg)
        hero_acts.pack(anchor="w")

        if cur_wp and os.path.exists(cur_wp):
            self._make_btn(
                hero_acts,
                "Show in Files",
                style="secondary",
                font_size=9,
                command=lambda p=cur_wp: open_path_in_system(os.path.dirname(p))
            ).pack(side="left", padx=(0, 6))

            self._make_btn(
                hero_acts,
                "Preview Fullscreen",
                style="secondary",
                font_size=9,
                command=lambda p=cur_wp: self.preview_wallpaper_fullscreen(p)
            ).pack(side="left")

        # 2. Studio Filter Toolbar
        toolbar = tk.Frame(container, bg=COLORS['main_bg'])
        toolbar.pack(fill="x", pady=(0, 14))

        # Filter Chips: All, Default, Custom
        self.wp_chip_btns = {}
        chip_frame = tk.Frame(toolbar, bg=COLORS['main_bg'])
        chip_frame.pack(side="left")

        for key, text_label in [("all", "All Wallpapers"), ("default", "Default Presets"), ("custom", "Custom Wallpapers")]:
            btn = tk.Button(
                chip_frame,
                text=text_label,
                font=(FONT_FAMILY, 9, "bold"),
                relief="flat",
                bd=0,
                padx=12,
                pady=5,
                cursor="hand2",
                command=lambda k=key: self._set_wallpaper_filter(k)
            )
            btn.pack(side="left", padx=(0, 6))
            self.wp_chip_btns[key] = btn

        self._update_wallpaper_chips()

        # Action Buttons on Right
        b_add_wp = self._make_btn(
            toolbar,
            "+ Add Wallpaper",
            style="primary",
            font_size=9,
            command=self.add_custom_wallpaper
        )
        b_add_wp.pack(side="right")

        b_wp_dir = tk.Button(
            toolbar,
            text="Open Folder",
            font=(FONT_FAMILY, 9, "bold"),
            relief="flat",
            bd=0,
            bg=COLORS.get('input_bg', '#1E222B'),
            fg=COLORS['text_primary'],
            padx=12,
            pady=5,
            cursor="hand2",
            command=lambda: open_path_in_system(os.path.join(self.config_dir, "wallpapers"))
        )
        b_wp_dir.pack(side="right", padx=(0, 8))

        # 3. Responsive Wallpapers Grid
        grid_area = tk.Frame(container, bg=COLORS['main_bg'])
        grid_area.pack(fill="both", expand=True)

        canvas = tk.Canvas(grid_area, bg=COLORS['main_bg'], highlightthickness=0)
        scrollbar = tk.Scrollbar(grid_area, orient="vertical", command=canvas.yview)

        self.wp_grid_frame = tk.Frame(canvas, bg=COLORS['main_bg'])
        canvas_window = canvas.create_window((0, 0), window=self.wp_grid_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Discover all wallpapers
        all_images = self._discover_all_wallpapers()
        filter_mode = self.wallpaper_filter_var.get()

        filtered_wps = []
        for name, path, is_default, img_hash in all_images:
            if filter_mode == "default" and not is_default:
                continue
            if filter_mode == "custom" and is_default:
                continue
            filtered_wps.append((name, path, is_default, img_hash))

        self.wp_widgets = []
        cur_wp_path = os.path.abspath(cur_wp) if cur_wp else ""

        for name, path, is_default, img_hash in filtered_wps:
            is_active = cur_wp_path and os.path.abspath(path) == cur_wp_path

            card = tk.Frame(
                self.wp_grid_frame,
                bg=card_bg,
                highlightthickness=1,
                highlightbackground=accent if is_active else border_col,
                padx=8,
                pady=8,
                cursor="hand2"
            )

            # Thumbnail
            try:
                tk_im = self.get_wallpaper_thumbnail(path, size=(220, 124))
                if not tk_im:
                    im = Image.open(path)
                    im.thumbnail((220, 124))
                    tk_im = ImageTk.PhotoImage(im)
                btn = tk.Button(
                    card,
                    image=tk_im,
                    bg=card_bg,
                    relief="flat",
                    bd=0,
                    command=lambda p=path: self.set_wallpaper(p)
                )
                btn.image = tk_im  # type: ignore
                btn.pack()
            except Exception:
                card.destroy()
                continue

            # Bottom row of card
            bot = tk.Frame(card, bg=card_bg)
            bot.pack(fill="x", pady=(6, 0))

            t_name = name if len(name) <= 18 else f"{name[:15]}..."
            tk.Label(
                bot,
                text=t_name,
                font=(FONT_FAMILY, 9, "bold"),
                bg=card_bg,
                fg=COLORS['text_primary'],
                anchor="w"
            ).pack(side="left")

            if is_active:
                tk.Label(
                    bot,
                    text="ACTIVE",
                    font=(FONT_FAMILY, 8, "bold"),
                    bg=accent,
                    fg="#FFFFFF",
                    padx=6,
                    pady=2
                ).pack(side="right")
            else:
                eq_btn = tk.Button(
                    bot,
                    text="Equip",
                    font=(FONT_FAMILY, 8, "bold"),
                    relief="flat",
                    bd=0,
                    bg=COLORS.get('input_bg', '#1E222B'),
                    fg=COLORS['text_secondary'],
                    padx=6,
                    pady=2,
                    cursor="hand2",
                    command=lambda p=path: self.set_wallpaper(p)
                )
                eq_btn.pack(side="right")

            # Context Menu for Wallpaper Card
            def make_wp_menu(p=path, is_def=is_default):
                def show_menu(event):
                    menu = NeoContextMenu(self.root)
                    menu.add_item("Set as Wallpaper", lambda: self.set_wallpaper(p))
                    menu.add_item("Fullscreen Preview", lambda: self.preview_wallpaper_fullscreen(p))
                    menu.add_item("Open Folder", lambda: open_path_in_system(os.path.dirname(p)))
                    if not is_def:
                        def delete_wp():
                            if custom_askyesno("Delete Wallpaper", "Are you sure you want to delete this custom wallpaper?", parent=self.root):
                                try:
                                    if os.path.exists(p):
                                        os.remove(p)
                                    self.refresh_locker_view()
                                except Exception as exc:
                                    custom_showerror("Error", f"Failed to delete wallpaper: {exc}", parent=self.root)
                        menu.add_separator()
                        menu.add_item("Delete Wallpaper", delete_wp, is_danger=True)
                    menu.show_at(event.x_root, event.y_root)
                return show_menu

            attach_context_menu(card, make_wp_menu())
            self.wp_widgets.append(card)

        # Responsive Reflow
        def reflow(event=None):
            w = canvas.winfo_width()
            item_width = 246
            cols = max(1, w // item_width)
            for i, widget in enumerate(self.wp_widgets):
                r = i // cols
                c = i % cols
                widget.grid(row=r, column=c, padx=8, pady=8)
            self.wp_grid_frame.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))

        canvas.bind(
            "<Configure>",
            lambda e: (canvas.itemconfig(canvas_window, width=e.width), reflow(e))
        )
        self._bind_wheel_events(canvas, lambda e, c=canvas: self._smooth_scroll(c, e), f"direct_{id(canvas)}")
        self._bind_smooth_scroll(canvas, self.wp_grid_frame)

    def _set_wallpaper_filter(self, key: str):
        self.wallpaper_filter_var.set(key)
        self._update_wallpaper_chips()
        self.refresh_locker_view()

    def _update_wallpaper_chips(self):
        val = self.wallpaper_filter_var.get()
        accent = COLORS.get('accent_color', '#2ECC71')
        input_bg = COLORS.get('input_bg', '#1E222B')

        for k, btn in getattr(self, 'wp_chip_btns', {}).items():
            if not btn.winfo_exists():
                continue
            if k == val:
                btn.config(bg=accent, fg="#FFFFFF")
            else:
                btn.config(bg=input_bg, fg=COLORS['text_secondary'])

    def _discover_all_wallpapers(self) -> List[Tuple[str, str, bool, str]]:
        if not hasattr(self, '_wallpaper_hash_cache'):
            self._wallpaper_hash_cache = {}

        def get_img_hash(p):
            try:
                st = os.stat(p)
                ckey = (p, st.st_mtime, st.st_size)
                if ckey in self._wallpaper_hash_cache:
                    return self._wallpaper_hash_cache[ckey]
                h = hashlib.sha1()
                with open(p, 'rb') as f:
                    while True:
                        b = f.read(65536)
                        if not b:
                            break
                        h.update(b)
                digest = h.hexdigest()
                self._wallpaper_hash_cache[ckey] = digest
                return digest
            except Exception:
                return ""

        discovered_defaults = []
        wp_res_dir = resource_path("wallpapers")
        if os.path.exists(wp_res_dir) and os.path.isdir(wp_res_dir):
            for f in sorted(os.listdir(wp_res_dir)):
                if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                    discovered_defaults.append(f)
        if "xse1m641dw9f1.png" in discovered_defaults:
            discovered_defaults.remove("xse1m641dw9f1.png")
            discovered_defaults.insert(0, "xse1m641dw9f1.png")

        defaults = discovered_defaults if discovered_defaults else [
            "xse1m641dw9f1.png", "q66ll6p2dw9f1.png", "background.png", "image1.png", "Island.png", "River.png"
        ]

        all_images = []
        default_hashes = set()

        for fname in defaults:
            path = resource_path(fname)
            final_path = path if os.path.exists(path) else resource_path(os.path.join("wallpapers", fname))
            if os.path.exists(final_path):
                h = get_img_hash(final_path)
                if h:
                    default_hashes.add(h)
                all_images.append((fname, final_path, True, h))

        # Custom user wallpapers
        try:
            custom_dir = os.path.join(self.config_dir, "wallpapers")
            if os.path.exists(custom_dir):
                for f in sorted(os.listdir(custom_dir)):
                    if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                        full_path = os.path.join(custom_dir, f)
                        h = get_img_hash(full_path)
                        if h and h in default_hashes:
                            continue
                        all_images.append((f, full_path, False, h))
        except Exception as e:
            logger.debug("Error listing custom wallpapers: %s", e)

        return all_images

    def preview_wallpaper_fullscreen(self, path: str):
        """Displays full-window lightbox overlay preview for a wallpaper image."""
        if not path or not os.path.exists(path):
            return

        card = tk.Frame(self.root, bg="#12141A", highlightbackground=COLORS.get('accent_color', '#2ECC71'), highlightthickness=2)
        card.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.90, relheight=0.90)
        card.lift()

        # Canvas with backdrop click to dismiss
        c = tk.Canvas(card, bg="#12141A", highlightthickness=0)
        c.pack(fill="both", expand=True)

        close_lbl = tk.Label(
            card,
            text="✕ Close",
            font=(FONT_FAMILY, 11, "bold"),
            bg="#222630",
            fg="#FFFFFF",
            padx=14,
            pady=6,
            cursor="hand2"
        )
        close_lbl.place(relx=1.0, rely=0.0, x=-24, y=24, anchor="ne")

        def close_preview():
            try:
                card.grab_release()
            except Exception:
                pass
            try:
                card.destroy()
            except Exception:
                pass

        close_lbl.bind("<Button-1>", lambda _e: close_preview())
        c.bind("<Button-1>", lambda _e: close_preview())

        try:
            rw = max(600, int(self.root.winfo_width() * 0.90))
            rh = max(400, int(self.root.winfo_height() * 0.90))
            im = Image.open(path)
            im.thumbnail((rw - 60, rh - 60))
            tk_photo = ImageTk.PhotoImage(im)
            c.create_image(rw // 2, rh // 2, image=tk_photo, anchor="center")
            card._photo = tk_photo  # type: ignore
        except Exception as e:
            logger.debug("Lightbox preview error: %s", e)

        def on_outside_click(event):
            if not card.winfo_exists():
                return
            try:
                cx = card.winfo_rootx()
                cy = card.winfo_rooty()
                cw = card.winfo_width()
                ch = card.winfo_height()
                if not (cx <= event.x_root <= cx + cw and cy <= event.y_root <= cy + ch):
                    close_preview()
            except Exception:
                pass

        card.bind_all("<Button-1>", on_outside_click, add="+")
        card.bind("<Escape>", lambda _e: close_preview())
        try:
            card.grab_set()
        except Exception:
            pass
        card.focus_set()

    # -------------------------------------------------------------------------
    # LEGACY / APP CONTRACT METHODS
    # -------------------------------------------------------------------------
    def update_skin_model(self):
        val = self.skin_model_var.get()
        if self.profiles and 0 <= self.current_profile_index < len(self.profiles):
            p = self.profiles[self.current_profile_index]
            old_val = p.get("skin_model", "classic")
            if old_val == val:
                return

            p["skin_model"] = val

            if p.get("type", "offline") == "microsoft":
                path = p.get("skin_path")
                if path and os.path.exists(path):
                    token = p.get("access_token")

                    def _sync_model():
                        if not self.upload_ms_skin(path, val, token):
                            custom_showwarning("Sync Error", "Failed to update skin model on Minecraft servers.")

                    threading.Thread(target=_sync_model, daemon=True).start()

        self.render_preview()
        self.save_config(sync_ui=False)

    def apply_history_skin(self, path: str, model: str = "classic"):
        if not os.path.exists(path):
            return

        p = self.profiles[self.current_profile_index]
        p_type = p.get("type", "offline")
        p["name"] = str(p.get("name", "") or getattr(self, "username", "") or "Steve")

        if p_type == "microsoft":
            token = p.get("access_token")
            if not self.upload_ms_skin(path, model, token):
                custom_showerror("Error", "Failed to upload skin to Minecraft servers.")

        self.skin_path = path
        p["skin_path"] = path
        p["skin_model"] = model

        if hasattr(self, 'skin_model_var'):
            self.skin_model_var.set(model)
            self._update_model_chips()

        self.render_preview()
        self.update_skin_indicator()
        self.add_skin_to_history(path, model)

    def add_skin_to_history(self, path: str, model: str = "classic"):
        if not self.profiles or not path:
            return
        p = self.profiles[self.current_profile_index]
        history = cast(list, p.get("skin_history", []))

        entry = {"path": path, "model": model, "name": os.path.splitext(os.path.basename(path))[0]}

        to_remove = None
        for item in history:
            existing_path = item if isinstance(item, str) else item.get("path")
            if existing_path == path:
                to_remove = item
                break

        if to_remove:
            history.remove(to_remove)

        history.insert(0, entry)
        if len(history) > 30:
            history = history[:30]

        p["skin_history"] = history  # type: ignore
        self.save_config(sync_ui=False)

        if hasattr(self, 'history_frame') and self.history_frame.winfo_exists():
            self.render_skin_history()

    def add_custom_wallpaper(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png;*.jpg;*.jpeg")])
        if path:
            self.set_wallpaper(path)

    def set_wallpaper(self, path: str):
        if not path or not os.path.exists(path):
            return

        try:
            wp_dir = os.path.join(self.config_dir, "wallpapers")
            os.makedirs(wp_dir, exist_ok=True)

            abs_path = os.path.abspath(path)
            abs_wp_dir = os.path.abspath(wp_dir)

            if not abs_path.startswith(abs_wp_dir):
                BUF_SIZE = 65536
                sha1 = hashlib.sha1()
                with open(path, 'rb') as f:
                    while True:
                        data = f.read(BUF_SIZE)
                        if not data:
                            break
                        sha1.update(data)
                src_hash = sha1.hexdigest()

                existing_file = None
                for wp in os.listdir(wp_dir):
                    wp_path = os.path.join(wp_dir, wp)
                    if not os.path.isfile(wp_path):
                        continue
                    try:
                        sha1_e = hashlib.sha1()
                        with open(wp_path, 'rb') as f:
                            while True:
                                data = f.read(BUF_SIZE)
                                if not data:
                                    break
                                sha1_e.update(data)
                        if sha1_e.hexdigest() == src_hash:
                            existing_file = wp_path
                            break
                    except Exception:
                        pass

                if existing_file:
                    path = existing_file
                else:
                    filename = os.path.basename(path)
                    name, ext = os.path.splitext(filename)
                    new_filename = f"{name}_{int(time.time())}{ext}"
                    new_path = os.path.join(wp_dir, new_filename)
                    shutil.copy2(path, new_path)
                    path = new_path

        except Exception as e:
            logger.debug("Failed saving wallpaper locally: %s", e)

        self.current_wallpaper = path
        try:
            self.hero_img_raw = Image.open(path)
            w = self.hero_canvas.winfo_width()
            h = self.hero_canvas.winfo_height()
            self._update_hero_layout(type('obj', (object,), {'width': w, 'height': h}))
            self.save_config(sync_ui=False)

            if hasattr(self, 'locker_view') and self.locker_view.get() == "Wallpapers":
                self.root.after(100, self.refresh_locker_view)
        except Exception as e:
            logger.debug("Wallpaper apply error: %s", e)
