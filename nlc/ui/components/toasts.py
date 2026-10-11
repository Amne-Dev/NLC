"""
nlc.ui.components.toasts - In-app toast notifications and deduplicated popup manager.
Renders directly within the main window frame to eliminate Wayland (0,0) floating window bugs.
"""

import logging
import time
import tkinter as tk
from typing import Optional, Callable, Dict, Any
from nlc.ui.theme import COLORS, FONT_FAMILY
from nlc.ui.components.radial_progress import RadialProgress

logger = logging.getLogger(__name__)


def _truncate_toast_text(text: str, max_chars: int = 34) -> str:
    """Safely truncate long strings with ellipsis to avoid UI stretch and eye fatigue."""
    if not text or len(text) <= max_chars:
        return text
    return text[:max_chars - 3].rstrip() + "..."


class PopupManager:
    """Manages application dialogs with duplicate suppression."""
    def __init__(self, root: tk.Tk):
        self.root = root.winfo_toplevel()
        self._active = set()

    def show(self, title: str, message: str, *, type="info", buttons=None, parent=None):
        signature = (type, str(title), str(message))
        if signature in self._active:
            logger.info("Suppressed duplicate popup: %s", title)
            return None
        self._active.add(signature)
        try:
            from nlc.ui.components.dialogs import custom_showinfo, custom_showerror, custom_askyesno
            target_parent = parent or self.root
            if type == "error":
                return custom_showerror(title, message, parent=target_parent)
            elif type == "yesno":
                return custom_askyesno(title, message, parent=target_parent)
            else:
                return custom_showinfo(title, message, parent=target_parent)
        finally:
            self._active.discard(signature)


class ToastManager:
    """Non-blocking, deduplicated in-app toast notifications contained within the launcher window."""
    def __init__(self, root: tk.Widget, on_toast_click: Optional[Callable] = None):
        self.root = root.winfo_toplevel()
        self.on_toast_click = on_toast_click
        self._toasts = []
        self._signatures = set()
        self._container = None
        self._download_toasts: Dict[str, Dict[str, Any]] = {}

    def _ensure_container(self):
        if self._container is None or not self._container.winfo_exists():
            self._container = tk.Frame(self.root, bg=COLORS.get('main_bg', '#13151A'))
            # Position at bottom-right inside the window, above status bar
            self._container.place(relx=1.0, rely=1.0, x=-24, y=-90, anchor="se")
            self._container.lift()
        return self._container

    def show(self, message: str, *, kind="success", duration=3600):
        signature = (kind, str(message))
        if signature in self._signatures:
            return
        self._signatures.add(signature)

        container = self._ensure_container()
        container.lift()

        colors = {
            "success": COLORS.get("success_green", "#2ECC71"),
            "warning": COLORS.get("warning_orange", "#F39C12"),
            "error": COLORS.get("error_red", "#EF4444"),
            "info": COLORS.get("accent_blue", "#3498DB"),
        }
        kind_col = colors.get(kind, colors["info"])
        card_bg = COLORS.get("card_bg", "#222630")

        toast_card = tk.Frame(
            container,
            bg=card_bg,
            highlightthickness=1,
            highlightbackground=kind_col,
            padx=14,
            pady=10
        )
        toast_card.pack(side="top", pady=4, fill="x", anchor="e")

        dot = tk.Label(
            toast_card,
            text="●",
            fg=kind_col,
            bg=card_bg,
            font=(FONT_FAMILY, 10, "bold")
        )
        dot.pack(side="left", padx=(0, 8))

        lbl = tk.Label(
            toast_card,
            text=str(message),
            fg=COLORS.get("text_primary", "#FFFFFF"),
            bg=card_bg,
            font=(FONT_FAMILY, 9),
            wraplength=340,
            justify="left"
        )
        lbl.pack(side="left")

        def dismiss():
            if toast_card in self._toasts:
                self._toasts.remove(toast_card)
            self._signatures.discard(signature)
            try:
                if toast_card.winfo_exists():
                    toast_card.destroy()
            except Exception:
                pass
            if not self._toasts and self._container and self._container.winfo_exists():
                try:
                    self._container.place_forget()
                except Exception:
                    pass

        def handle_click():
            dismiss()
            if self.on_toast_click:
                self.on_toast_click()

        for w in (toast_card, dot, lbl):
            w.bind("<Button-1>", lambda _e: handle_click())

        self._toasts.append(toast_card)
        toast_card.after(duration, dismiss)

    # -------------------------------------------------------------------------
    # DOWNLOAD TOAST WITH RADIAL PROGRESS BAR
    # -------------------------------------------------------------------------
    def show_download_toast(
        self,
        task_id: str,
        title: str,
        detail: str = "Downloading...",
        initial_progress: float = 0.0,
        on_cancel: Optional[Callable] = None
    ):
        """Display an active download toast with circular radial progress bar."""
        if task_id in self._download_toasts:
            self.update_download_toast(task_id, progress=initial_progress, detail=detail)
            return

        container = self._ensure_container()
        container.lift()

        card_bg = COLORS.get("card_bg", "#222630")
        border_col = COLORS.get("card_border", "#2A303F")

        toast_card = tk.Frame(
            container,
            bg=card_bg,
            highlightthickness=1,
            highlightbackground=border_col,
            padx=12,
            pady=10,
            width=352,
            height=68
        )
        toast_card.pack_propagate(False)
        toast_card.pack(side="top", pady=4, anchor="e")

        # Radial Progress widget on the left
        radial = RadialProgress(toast_card, size=42, line_width=3, bg=card_bg)
        radial.pack(side="left", padx=(0, 10))
        if initial_progress > 0:
            radial.set_progress(initial_progress)
        else:
            radial.set_indeterminate(True)

        info = tk.Frame(toast_card, bg=card_bg)
        info.pack(side="left", fill="both", expand=True)

        lbl_title = tk.Label(
            info,
            text=_truncate_toast_text(title, 32),
            font=(FONT_FAMILY, 9, "bold"),
            bg=card_bg,
            fg=COLORS.get("text_primary", "#FFFFFF"),
            anchor="w"
        )
        lbl_title.pack(fill="x")

        lbl_detail = tk.Label(
            info,
            text=_truncate_toast_text(detail, 36),
            font=(FONT_FAMILY, 8),
            bg=card_bg,
            fg=COLORS.get("text_secondary", "#A6ACB8"),
            anchor="w"
        )
        lbl_detail.pack(fill="x", pady=(2, 0))

        # Close / Cancel button
        def cancel_clicked():
            if on_cancel:
                on_cancel()
            dismiss()

        def dismiss():
            if task_id in self._download_toasts:
                del self._download_toasts[task_id]
            if toast_card in self._toasts:
                self._toasts.remove(toast_card)
            try:
                if toast_card.winfo_exists():
                    toast_card.destroy()
            except Exception:
                pass
            if not self._toasts and self._container and self._container.winfo_exists():
                try:
                    self._container.place_forget()
                except Exception:
                    pass

        b_cancel = tk.Button(
            toast_card,
            text="✕",
            font=(FONT_FAMILY, 8),
            bg=card_bg,
            fg=COLORS.get("text_muted", "#6B7280"),
            bd=0,
            relief="flat",
            cursor="hand2",
            command=cancel_clicked
        )
        b_cancel.pack(side="right", anchor="ne", padx=(8, 0))

        # Clicking the toast body triggers drawer if click handler exists
        def on_card_click(e):
            if self.on_toast_click:
                self.on_toast_click()

        for w in (toast_card, info, lbl_title, lbl_detail):
            w.bind("<Button-1>", on_card_click)

        self._download_toasts[task_id] = {
            "card": toast_card,
            "radial": radial,
            "title_lbl": lbl_title,
            "detail_lbl": lbl_detail,
            "dismiss_fn": dismiss
        }
        self._toasts.append(toast_card)

    def update_download_toast(
        self,
        task_id: str,
        progress: Optional[float] = None,
        detail: Optional[str] = None,
        title: Optional[str] = None
    ):
        """Update the radial progress percentage or status message of an active download toast."""
        entry = self._download_toasts.get(task_id)
        if not entry:
            return
        radial: RadialProgress = entry["radial"]
        if progress is not None:
            radial.set_progress(progress)
        if title and entry.get("title_lbl") and entry["title_lbl"].winfo_exists():
            entry["title_lbl"].config(text=_truncate_toast_text(title, 32))
        if detail and entry["detail_lbl"].winfo_exists():
            entry["detail_lbl"].config(text=_truncate_toast_text(detail, 36))

    def complete_download_toast(self, task_id: str, message: str = "Completed ✓"):
        """Display 100% completion with green checkmark and auto-dismiss after 2.5 seconds."""
        entry = self._download_toasts.get(task_id)
        if not entry:
            return
        radial: RadialProgress = entry["radial"]
        radial.set_success()
        if entry["detail_lbl"].winfo_exists():
            entry["detail_lbl"].config(
                text=_truncate_toast_text(message, 36),
                fg=COLORS.get("accent_color", "#2ECC71")
            )
        card = entry["card"]
        card.config(highlightbackground=COLORS.get("accent_color", "#2ECC71"))

        def dismiss():
            if task_id in self._download_toasts:
                del self._download_toasts[task_id]
            if card in self._toasts:
                self._toasts.remove(card)
            try:
                if card.winfo_exists():
                    card.destroy()
            except Exception:
                pass
            if not self._toasts and self._container and self._container.winfo_exists():
                try:
                    self._container.place_forget()
                except Exception:
                    pass

        card.after(2500, dismiss)

    def fail_download_toast(self, task_id: str, message: str = "Download failed"):
        """Display error state on radial toast."""
        entry = self._download_toasts.get(task_id)
        if not entry:
            return
        radial: RadialProgress = entry["radial"]
        radial.set_error()
        if entry["detail_lbl"].winfo_exists():
            entry["detail_lbl"].config(
                text=message,
                fg=COLORS.get("error_red", "#EF4444")
            )
        card = entry["card"]
        card.config(highlightbackground=COLORS.get("error_red", "#EF4444"))

        def dismiss():
            if task_id in self._download_toasts:
                del self._download_toasts[task_id]
            if card in self._toasts:
                self._toasts.remove(card)
            try:
                if card.winfo_exists():
                    card.destroy()
            except Exception:
                pass
            if not self._toasts and self._container and self._container.winfo_exists():
                try:
                    self._container.place_forget()
                except Exception:
                    pass

        card.after(3500, dismiss)

    # -------------------------------------------------------------------------
    # GAME SESSION PLAYTIME TOAST
    # -------------------------------------------------------------------------
    def show_session_toast(
        self,
        inst_name: str,
        session_seconds: int,
        total_seconds: int,
        server: Optional[str] = None
    ):
        """Display session playtime celebration toast when exiting game."""
        container = self._ensure_container()
        container.lift()

        card_bg = COLORS.get("card_bg", "#222630")
        accent = COLORS.get("accent_color", "#2ECC71")

        toast_card = tk.Frame(
            container,
            bg=card_bg,
            highlightthickness=1,
            highlightbackground=accent,
            padx=14,
            pady=10,
            width=352,
            height=68
        )
        toast_card.pack_propagate(False)
        toast_card.pack(side="top", pady=4, anchor="e")

        # Clock / Timer graphic on left
        clock_canvas = tk.Canvas(toast_card, width=44, height=44, bg=card_bg, highlightthickness=0)
        clock_canvas.pack(side="left", padx=(0, 12))
        clock_canvas.create_oval(3, 3, 41, 41, outline=accent, width=2)
        clock_canvas.create_line(22, 22, 22, 11, fill=accent, width=2)
        clock_canvas.create_line(22, 22, 31, 22, fill=accent, width=2)

        info = tk.Frame(toast_card, bg=card_bg)
        info.pack(side="left", fill="both", expand=True)

        tk.Label(
            info,
            text="Game Session Ended",
            font=(FONT_FAMILY, 9, "bold"),
            bg=card_bg,
            fg=COLORS.get("text_primary", "#FFFFFF"),
            anchor="w"
        ).pack(fill="x")

        session_str = self._format_duration(session_seconds)
        total_str = self._format_duration(total_seconds)

        msg = f"You played {inst_name} for {session_str}"
        tk.Label(
            info,
            text=msg,
            font=(FONT_FAMILY, 9, "bold"),
            bg=card_bg,
            fg=accent,
            anchor="w"
        ).pack(fill="x", pady=(2, 0))

        detail_text = f"Total playtime: {total_str}"
        if server:
            detail_text += f" • {server}"
        tk.Label(
            info,
            text=detail_text,
            font=(FONT_FAMILY, 8),
            bg=card_bg,
            fg=COLORS.get("text_secondary", "#A6ACB8"),
            anchor="w"
        ).pack(fill="x", pady=(2, 0))

        # Close button
        def dismiss():
            if toast_card in self._toasts:
                self._toasts.remove(toast_card)
            try:
                if toast_card.winfo_exists():
                    toast_card.destroy()
            except Exception:
                pass
            if not self._toasts and self._container and self._container.winfo_exists():
                try:
                    self._container.place_forget()
                except Exception:
                    pass

        b_close = tk.Button(
            toast_card,
            text="✕",
            font=(FONT_FAMILY, 8),
            bg=card_bg,
            fg=COLORS.get("text_muted", "#6B7280"),
            bd=0,
            relief="flat",
            cursor="hand2",
            command=dismiss
        )
        b_close.pack(side="right", anchor="ne")

        self._toasts.append(toast_card)
        toast_card.after(6000, dismiss)

    # -------------------------------------------------------------------------
    # LAUNCHER UPDATE TOAST
    # -------------------------------------------------------------------------
    def show_update_toast(
        self,
        version: str,
        on_update: Callable,
        on_later: Optional[Callable] = None
    ):
        """Display non-blocking update notification toast with actionable update button."""
        container = self._ensure_container()
        container.lift()

        card_bg = COLORS.get("card_bg", "#222630")
        upd_col = COLORS.get("warning_orange", "#F39C12")
        accent = COLORS.get("accent_color", "#2ECC71")

        toast_card = tk.Frame(
            container,
            bg=card_bg,
            highlightthickness=1,
            highlightbackground=upd_col,
            padx=14,
            pady=10,
            width=352,
            height=104
        )
        toast_card.pack_propagate(False)
        toast_card.pack(side="top", pady=4, anchor="e")

        # Arrow up graphic
        arrow_canvas = tk.Canvas(toast_card, width=40, height=40, bg=card_bg, highlightthickness=0)
        arrow_canvas.pack(side="left", padx=(0, 10))
        arrow_canvas.create_oval(2, 2, 38, 38, outline=upd_col, width=2)
        arrow_canvas.create_polygon(20, 10, 28, 20, 12, 20, fill=upd_col)
        arrow_canvas.create_rectangle(17, 20, 23, 28, fill=upd_col)

        info = tk.Frame(toast_card, bg=card_bg)
        info.pack(side="left", fill="both", expand=True)

        tk.Label(
            info,
            text=f"Update Available: {version}",
            font=(FONT_FAMILY, 9, "bold"),
            bg=card_bg,
            fg=COLORS.get("text_primary", "#FFFFFF"),
            anchor="w"
        ).pack(fill="x")

        tk.Label(
            info,
            text="A new launcher update is ready to install.",
            font=(FONT_FAMILY, 8),
            bg=card_bg,
            fg=COLORS.get("text_secondary", "#A6ACB8"),
            anchor="w"
        ).pack(fill="x", pady=(2, 6))

        btn_row = tk.Frame(info, bg=card_bg)
        btn_row.pack(anchor="w")

        def dismiss():
            if toast_card in self._toasts:
                self._toasts.remove(toast_card)
            try:
                if toast_card.winfo_exists():
                    toast_card.destroy()
            except Exception:
                pass
            if not self._toasts and self._container and self._container.winfo_exists():
                try:
                    self._container.place_forget()
                except Exception:
                    pass

        def do_update():
            dismiss()
            on_update()

        b_upd = tk.Button(
            btn_row,
            text="Update Now",
            font=(FONT_FAMILY, 8, "bold"),
            bg=accent,
            fg="#FFFFFF",
            bd=0,
            relief="flat",
            padx=10,
            pady=3,
            cursor="hand2",
            command=do_update
        )
        b_upd.pack(side="left", padx=(0, 6))

        b_later = tk.Button(
            btn_row,
            text="Later",
            font=(FONT_FAMILY, 8),
            bg=COLORS.get("input_bg", "#1E222B"),
            fg=COLORS.get("text_secondary", "#A6ACB8"),
            bd=0,
            relief="flat",
            padx=8,
            pady=3,
            cursor="hand2",
            command=dismiss
        )
        b_later.pack(side="left")

        dismiss_line = tk.Frame(toast_card, bg=upd_col, height=2)
        dismiss_line.place(relx=0, rely=1.0, relwidth=1.0, height=2, anchor="sw")
        dismiss_started = time.monotonic()
        dismiss_duration = 60.0

        def update_dismiss_line():
            if not dismiss_line.winfo_exists():
                return
            remaining = max(0.0, dismiss_duration - (time.monotonic() - dismiss_started))
            dismiss_line.place(
                relx=0,
                rely=1.0,
                relwidth=remaining / dismiss_duration,
                height=2,
                anchor="sw"
            )
            if remaining > 0:
                dismiss_line.after(100, update_dismiss_line)

        update_dismiss_line()
        self._toasts.append(toast_card)
        toast_card.after(60000, dismiss)

    @staticmethod
    def _format_duration(seconds: int) -> str:
        secs = max(0, int(seconds))
        if secs < 60:
            return f"{secs}s"
        mins = secs // 60
        hours = mins // 60
        mins = mins % 60
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{mins}m"
