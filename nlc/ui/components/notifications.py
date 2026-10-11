"""
nlc.ui.components.notifications - Notification store, event tracking, and slide-over Notification Center drawer.
"""

import time
import uuid
import logging
import tkinter as tk
from tkinter import ttk
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field

from nlc.ui.theme import COLORS, FONT_FAMILY
from nlc.ui.components.radial_progress import RadialProgress

logger = logging.getLogger(__name__)


def _bind_mousewheel(canvas: tk.Canvas, widget: tk.Widget):
    """Recursively bind mouse wheel scrolling across platforms."""
    def _on_wheel(event):
        try:
            if event.num == 4:
                canvas.yview_scroll(-2, "units")
            elif event.num == 5:
                canvas.yview_scroll(2, "units")
            elif getattr(event, "delta", 0):
                canvas.yview_scroll(int(-1 * (event.delta / 60)), "units")
        except Exception:
            pass

    widget.bind("<MouseWheel>", _on_wheel, add=True)
    widget.bind("<Button-4>", _on_wheel, add=True)
    widget.bind("<Button-5>", _on_wheel, add=True)
    for child in widget.winfo_children():
        _bind_mousewheel(canvas, child)


@dataclass
class NotificationItem:
    id: str
    category: str  # "download", "session", "update", "system"
    title: str
    message: str
    timestamp: float = field(default_factory=time.time)
    progress: Optional[float] = None  # 0.0 to 100.0 if applicable
    status: str = "active"  # "active", "completed", "failed"
    read: bool = False
    data: Dict[str, Any] = field(default_factory=dict)
    action_label: Optional[str] = None
    action_callback: Optional[Callable] = None
    dismiss_after: Optional[float] = None
    expires_at: Optional[float] = None


class NotificationStore:
    """Central notification and background task registry."""
    def __init__(self):
        self._items: List[NotificationItem] = []
        self._listeners: List[Callable] = []

    def add(
        self,
        category: str,
        title: str,
        message: str,
        progress: Optional[float] = None,
        status: str = "active",
        item_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        action_label: Optional[str] = None,
        action_callback: Optional[Callable] = None,
        dismiss_after: Optional[float] = None
    ) -> NotificationItem:
        nid = item_id or str(uuid.uuid4())
        # Check if item with ID already exists
        existing = self.get(nid)
        if existing:
            existing.title = title
            existing.message = message
            existing.progress = progress
            existing.status = status
            if action_label is not None:
                existing.action_label = action_label
            if action_callback is not None:
                existing.action_callback = action_callback
            if dismiss_after is not None:
                existing.dismiss_after = dismiss_after
                existing.expires_at = time.time() + dismiss_after
            self._notify()
            return existing

        item = NotificationItem(
            id=nid,
            category=category,
            title=title,
            message=message,
            timestamp=time.time(),
            progress=progress,
            status=status,
            read=False,
            data=data or {},
            action_label=action_label,
            action_callback=action_callback,
            dismiss_after=dismiss_after,
            expires_at=(time.time() + dismiss_after) if dismiss_after is not None else None
        )
        self._items.insert(0, item)
        # Cap store at 50 historical items
        if len(self._items) > 50:
            self._items.pop()
        self._notify()
        return item

    def add_session(
        self,
        inst_name: str,
        session_seconds: int,
        total_seconds: int,
        server: Optional[str] = None
    ) -> NotificationItem:
        secs_str = self._format_duration(session_seconds)
        tot_str = self._format_duration(total_seconds)
        detail = f"Session: {secs_str} • Total: {tot_str}"
        if server:
            detail += f" • {server}"
        return self.add(
            category="session",
            title=f"Played {inst_name}",
            message=detail,
            status="completed",
            data={
                "inst_name": inst_name,
                "session_seconds": session_seconds,
                "total_seconds": total_seconds,
                "server": server
            }
        )

    def add_update(
        self,
        version: str,
        asset_url: Optional[str] = None,
        html_url: Optional[str] = None,
        on_update: Optional[Callable] = None,
        dismiss_after: float = 10.0
    ) -> NotificationItem:
        return self.add(
            category="update",
            title=f"Update Available: {version}",
            message="A new launcher update is ready to install.",
            status="active",
            data={"version": version, "asset_url": asset_url, "html_url": html_url},
            action_label="Update Now",
            action_callback=on_update,
            dismiss_after=dismiss_after
        )

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

    def get(self, item_id: str) -> Optional[NotificationItem]:
        for it in self._items:
            if it.id == item_id:
                return it
        return None

    def update(
        self,
        item_id: str,
        title: Optional[str] = None,
        message: Optional[str] = None,
        progress: Optional[float] = None,
        status: Optional[str] = None
    ):
        it = self.get(item_id)
        if not it:
            return
        if title is not None:
            it.title = title
        if message is not None:
            it.message = message
        if progress is not None:
            it.progress = progress
        if status is not None:
            it.status = status
        self._notify()

    def remove(self, item_id: str):
        self._items = [it for it in self._items if it.id != item_id]
        self._notify()

    def clear_all(self, category: Optional[str] = None):
        if category and category != "all":
            self._items = [it for it in self._items if it.category != category]
        else:
            self._items = []
        self._notify()

    def mark_all_read(self):
        for it in self._items:
            it.read = True
        self._notify()

    def get_items(self, category: Optional[str] = None) -> List[NotificationItem]:
        if not category or category == "all":
            return list(self._items)
        return [it for it in self._items if it.category == category]

    def unread_count(self) -> int:
        return sum(1 for it in self._items if not it.read)

    def add_listener(self, cb: Callable):
        self._listeners.append(cb)

    def remove_listener(self, cb: Callable):
        if cb in self._listeners:
            self._listeners.remove(cb)

    def _notify(self):
        for cb in list(self._listeners):
            try:
                cb()
            except Exception as e:
                logger.debug("Notification listener error: %s", e)


class NotificationCenterDrawer:
    """Slide-over notification center drawer on the right edge of the launcher window."""
    def __init__(self, parent: tk.Widget, store: NotificationStore, on_badge_update: Optional[Callable] = None):
        self.parent = parent.winfo_toplevel()
        self.store = store
        self.on_badge_update = on_badge_update
        self.is_open = False
        self.current_category = "all"

        self._backdrop = None
        self._drawer_frame = None
        self._anim_job = None
        self._target_width = 360
        self._card_widgets = {}

        self.store.add_listener(self._on_store_updated)

    def toggle(self):
        if self.is_open:
            self.close()
        else:
            self.open()

    def open(self):
        if self.is_open:
            return
        self.is_open = True
        self.store.mark_all_read()
        self._ensure_ui()
        self.render_feed()
        self._slide_in()

    def close(self):
        if not self.is_open:
            return
        self.is_open = False
        self._slide_out()

    def _slide_in(self):
        if not self._drawer_frame:
            return
        self._drawer_frame.place(
            relx=1.0,
            rely=0.0,
            x=0,
            width=self._target_width,
            relheight=1.0,
            anchor="ne"
        )
        self._drawer_frame.lift()
        self._bind_outside_click()

    def _slide_out(self):
        self._unbind_outside_click()
        if self._drawer_frame and self._drawer_frame.winfo_exists():
            self._drawer_frame.place_forget()
        if self._backdrop and self._backdrop.winfo_exists():
            self._backdrop.place_forget()

    def _bind_outside_click(self):
        self._unbind_outside_click()
        try:
            self._click_bind_id = self.parent.bind("<Button-1>", self._on_parent_click, add="+")
        except Exception:
            self._click_bind_id = None
        try:
            self._esc_bind_id = self.parent.bind("<Escape>", self._on_escape, add="+")
        except Exception:
            self._esc_bind_id = None

    def _unbind_outside_click(self):
        if getattr(self, "_click_bind_id", None):
            try:
                self.parent.unbind("<Button-1>", self._click_bind_id)
            except Exception:
                pass
            self._click_bind_id = None
        if getattr(self, "_esc_bind_id", None):
            try:
                self.parent.unbind("<Escape>", self._esc_bind_id)
            except Exception:
                pass
            self._esc_bind_id = None

    def _on_escape(self, event=None):
        if self.is_open:
            self.close()

    def _on_parent_click(self, event):
        if not self.is_open or not self._drawer_frame or not self._drawer_frame.winfo_exists():
            return
        widget = getattr(event, "widget", None)
        try:
            w = widget
            while w is not None:
                if w == self._drawer_frame or getattr(w, "_is_notif_toggle", False):
                    return
                w = getattr(w, "master", None)
        except Exception:
            pass

        try:
            dx = self._drawer_frame.winfo_rootx()
            dy = self._drawer_frame.winfo_rooty()
            dw = self._drawer_frame.winfo_width()
            dh = self._drawer_frame.winfo_height()
            if dx <= event.x_root <= dx + dw and dy <= event.y_root <= dy + dh:
                return
        except Exception:
            pass

        self.close()

    def _ensure_ui(self):
        if self._drawer_frame and self._drawer_frame.winfo_exists():
            return

        card_bg = COLORS.get('card_bg', '#242830')
        border_col = COLORS.get('card_border', '#2F3542')
        accent = COLORS.get('accent_color', '#2ECC71')

        # Main slide-over drawer (no full-screen opaque blackout)
        self._drawer_frame = tk.Frame(
            self.parent,
            bg=card_bg,
            highlightthickness=1,
            highlightbackground=border_col,
            cursor="arrow"
        )
        self._drawer_frame.bind("<Button-1>", lambda e: "break")

        # 1. Header Bar
        header = tk.Frame(self._drawer_frame, bg=card_bg, padx=16, pady=14)
        header.pack(fill="x")

        # Title + Count Badge
        title_box = tk.Frame(header, bg=card_bg)
        title_box.pack(side="left")

        tk.Label(
            title_box,
            text="Notifications",
            font=(FONT_FAMILY, 11, "bold"),
            bg=card_bg,
            fg=COLORS.get('text_primary', '#FFFFFF')
        ).pack(side="left")

        self.header_badge_lbl = tk.Label(
            title_box,
            text="0",
            font=(FONT_FAMILY, 8, "bold"),
            bg=accent,
            fg="#FFFFFF",
            padx=6,
            pady=1
        )
        self.header_badge_lbl.pack(side="left", padx=(8, 0))

        # Close button (✕)
        b_close = tk.Button(
            header,
            text="✕",
            font=(FONT_FAMILY, 9),
            bg=card_bg,
            fg=COLORS.get('text_muted', '#6B7280'),
            bd=0,
            relief="flat",
            cursor="hand2",
            command=self.close
        )
        b_close.pack(side="right")

        # Clear All button
        b_clear = tk.Button(
            header,
            text="Clear All",
            font=(FONT_FAMILY, 8),
            bg=card_bg,
            fg=COLORS.get('text_muted', '#6B7280'),
            bd=0,
            relief="flat",
            cursor="hand2",
            command=lambda: self.store.clear_all(self.current_category)
        )
        b_clear.pack(side="right", padx=(0, 12))

        # 2. Filter Tabs (All, Downloads, Sessions)
        tabs_bar = tk.Frame(self._drawer_frame, bg=card_bg, padx=16)
        tabs_bar.pack(fill="x", pady=(0, 10))

        self._tab_btns = {}
        for cat_id, cat_lbl in [("all", "All"), ("download", "Downloads"), ("session", "Sessions")]:
            btn = tk.Button(
                tabs_bar,
                text=cat_lbl,
                font=(FONT_FAMILY, 8, "bold"),
                relief="flat",
                bd=0,
                padx=10,
                pady=3,
                cursor="hand2",
                command=lambda c=cat_id: self._select_category(c)
            )
            btn.pack(side="left", padx=(0, 6))
            self._tab_btns[cat_id] = btn

        self._update_tab_buttons()

        # Separator Line
        tk.Frame(self._drawer_frame, bg=border_col, height=1).pack(fill="x", padx=16, pady=(0, 8))

        # 3. Scrollable Notifications Feed
        feed_container = tk.Frame(self._drawer_frame, bg=card_bg)
        feed_container.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(feed_container, bg=card_bg, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(feed_container, orient="vertical", command=self.canvas.yview)
        self.feed_frame = tk.Frame(self.canvas, bg=card_bg)

        self.canvas_win = self.canvas.create_window((0, 0), window=self.feed_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.feed_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfig(self.canvas_win, width=e.width)
        )

        _bind_mousewheel(self.canvas, self.feed_frame)

        self.canvas.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.scrollbar.pack(side="right", fill="y")

    def _select_category(self, cat: str):
        self.current_category = cat
        self._update_tab_buttons()
        self.render_feed()

    def _invoke_action(self, item: NotificationItem):
        """Run a notification action and close the drawer after dispatching it."""
        try:
            if item.action_callback:
                item.action_callback()
        except Exception:
            logger.exception("Notification action failed")
            return
        self.close()

    def _dismiss_item(self, item_id: str):
        self.store.remove(item_id)

    def _update_tab_buttons(self):
        accent = COLORS.get('accent_color', '#2ECC71')
        input_bg = COLORS.get('input_bg', '#151821')
        text_sec = COLORS.get('text_secondary', '#A6ACB8')

        for cid, btn in self._tab_btns.items():
            if cid == self.current_category:
                btn.config(bg=accent, fg="#FFFFFF")
            else:
                btn.config(bg=input_bg, fg=text_sec)

    def _on_store_updated(self):
        unread = self.store.unread_count()
        if self.on_badge_update:
            self.on_badge_update(unread)
        if self.is_open:
            self.render_feed()

    def render_feed(self):
        if (
            not self._drawer_frame
            or not self._drawer_frame.winfo_exists()
            or not getattr(self, "feed_frame", None)
            or not self.feed_frame.winfo_exists()
        ):
            return

        items = self.store.get_items(self.current_category)

        # Update count badge
        if hasattr(self, 'header_badge_lbl') and self.header_badge_lbl.winfo_exists():
            self.header_badge_lbl.config(text=f"{len(items)}")

        # Clear old items
        for w in self.feed_frame.winfo_children():
            w.destroy()
        self._card_widgets.clear()

        if not items:
            empty_box = tk.Frame(self.feed_frame, bg=COLORS.get('card_bg', '#1E222B'), pady=40)
            empty_box.pack(fill="both", expand=True)
            tk.Label(
                empty_box,
                text="No notifications",
                font=(FONT_FAMILY, 10, "bold"),
                bg=COLORS.get('card_bg', '#1E222B'),
                fg=COLORS.get('text_secondary', '#A6ACB8')
            ).pack(pady=(0, 4))
            tk.Label(
                empty_box,
                text="Downloads, updates, and play sessions\nwill appear here.",
                font=(FONT_FAMILY, 8),
                bg=COLORS.get('card_bg', '#1E222B'),
                fg=COLORS.get('text_muted', '#6B7280'),
                justify="center"
            ).pack()
            return

        card_bg = COLORS.get('input_bg', '#151821')
        border_col = COLORS.get('card_border', '#2A303F')
        accent = COLORS.get('accent_color', '#2ECC71')

        for item in items:
            self._render_notification_card(item, card_bg, border_col, accent)

    def _render_notification_card(self, item: NotificationItem, card_bg: str, border_col: str, accent: str):
        card = tk.Frame(
            self.feed_frame,
            bg=card_bg,
            highlightthickness=1,
            highlightbackground=border_col,
            padx=12,
            pady=10
        )
        card.pack(fill="x", pady=4, padx=(0, 8))

        countdown = None
        if item.expires_at is not None:
            countdown = tk.Frame(card, bg=COLORS.get('warning_orange', '#F39C12'), height=2)
            countdown.place(relx=0, rely=0, relwidth=1.0, height=2, anchor="nw")

            def update_countdown():
                if not countdown.winfo_exists():
                    return
                remaining = (item.expires_at or 0) - time.time()
                if remaining <= 0:
                    self.parent.after_idle(lambda: self.store.remove(item.id))
                    return
                fraction = min(1.0, remaining / max(item.dismiss_after or 1.0, 0.001))
                try:
                    countdown.place(
                        relx=0,
                        rely=0,
                        relwidth=fraction,
                        height=2,
                        anchor="nw"
                    )
                except tk.TclError:
                    return
                countdown.after(100, update_countdown)

            update_countdown()

        # Left Graphic Icon or Radial Progress
        left_box = tk.Frame(card, bg=card_bg, width=44, height=44)
        left_box.pack(side="left", padx=(0, 10))
        left_box.pack_propagate(False)

        if item.category == "download" and item.status == "active":
            rp = RadialProgress(left_box, size=40, line_width=3, bg=card_bg)
            rp.pack(expand=True)
            if item.progress is not None:
                rp.set_progress(item.progress)
            else:
                rp.set_indeterminate(True)
            self._card_widgets[item.id] = {"radial": rp, "card": card}
        elif item.category == "download" and item.status == "completed":
            rp = RadialProgress(left_box, size=40, line_width=3, bg=card_bg)
            rp.pack(expand=True)
            rp.set_success()
        elif item.category == "download" and item.status == "failed":
            rp = RadialProgress(left_box, size=40, line_width=3, bg=card_bg)
            rp.pack(expand=True)
            rp.set_error()
        elif item.category == "session":
            # Session timer clock graphic
            icon_canvas = tk.Canvas(left_box, width=38, height=38, bg=card_bg, highlightthickness=0)
            icon_canvas.pack(expand=True)
            icon_canvas.create_oval(3, 3, 35, 35, outline=accent, width=2)
            icon_canvas.create_line(19, 19, 19, 10, fill=accent, width=2)
            icon_canvas.create_line(19, 19, 26, 19, fill=accent, width=2)
        elif item.category == "update":
            # Update rocket / arrow graphic
            icon_canvas = tk.Canvas(left_box, width=38, height=38, bg=card_bg, highlightthickness=0)
            icon_canvas.pack(expand=True)
            upd_col = COLORS.get('warning_orange', '#F39C12')
            icon_canvas.create_oval(3, 3, 35, 35, outline=upd_col, width=2)
            icon_canvas.create_polygon(19, 11, 26, 20, 12, 20, fill=upd_col)
            icon_canvas.create_rectangle(16, 20, 22, 27, fill=upd_col)
        else:
            # Default info dot
            icon_canvas = tk.Canvas(left_box, width=38, height=38, bg=card_bg, highlightthickness=0)
            icon_canvas.pack(expand=True)
            icon_canvas.create_oval(14, 14, 24, 24, fill=accent, outline="")

        # Content Area
        info = tk.Frame(card, bg=card_bg)
        info.pack(side="left", fill="both", expand=True)

        top_row = tk.Frame(info, bg=card_bg)
        top_row.pack(fill="x")

        tk.Label(
            top_row,
            text=item.title,
            font=(FONT_FAMILY, 9, "bold"),
            bg=card_bg,
            fg=COLORS.get('text_primary', '#FFFFFF'),
            anchor="w"
        ).pack(side="left", fill="x", expand=True)

        # Time ago string
        mins_ago = int((time.time() - item.timestamp) / 60.0)
        time_str = "Just now" if mins_ago < 1 else f"{mins_ago}m ago"
        tk.Label(
            top_row,
            text=time_str,
            font=(FONT_FAMILY, 7),
            bg=card_bg,
            fg=COLORS.get('text_muted', '#6B7280')
        ).pack(side="right")

        msg_lbl = tk.Label(
            info,
            text=item.message,
            font=(FONT_FAMILY, 8),
            bg=card_bg,
            fg=COLORS.get('text_secondary', '#A6ACB8'),
            anchor="w",
            wraplength=220,
            justify="left"
        )
        msg_lbl.pack(fill="x", pady=(2, 0))

        # Inline action and dismiss buttons
        action_row = None
        if item.action_label and item.action_callback:
            action_row = tk.Frame(info, bg=card_bg)
            action_row.pack(anchor="w", pady=(6, 0))
            act_btn = tk.Button(
                action_row,
                text=item.action_label,
                font=(FONT_FAMILY, 8, "bold"),
                bg=accent,
                fg="#FFFFFF",
                bd=0,
                relief="flat",
                padx=8,
                pady=2,
                cursor="hand2",
                command=lambda notification=item: self._invoke_action(notification)
            )
            act_btn.pack(side="left")

        dismiss_btn = tk.Button(
            action_row or info,
            text="Dismiss",
            font=(FONT_FAMILY, 8),
            bg=card_bg,
            fg=COLORS.get('text_muted', '#6B7280'),
            bd=0,
            relief="flat",
            padx=8,
            pady=2,
            cursor="hand2",
            command=lambda notification_id=item.id: self._dismiss_item(notification_id)
        )
        dismiss_btn.pack(
            side="left" if action_row else "top",
            anchor="w",
            pady=(6, 0) if not action_row else (0, 0),
            padx=(8, 0) if action_row else (0, 0)
        )

        _bind_mousewheel(self.canvas, card)
