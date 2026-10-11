"""
tests/test_notifications.py - Tests for NotificationStore, NotificationCenterDrawer, and ToastManager.
"""

import pytest
import tkinter as tk
from nlc.ui.components.notifications import (
    NotificationStore,
    NotificationItem,
    NotificationCenterDrawer,
)
from nlc.ui.components.toasts import ToastManager


def test_notification_store_crud():
    store = NotificationStore()
    assert len(store.get_items()) == 0
    assert store.unread_count() == 0

    # Add item
    item = store.add(
        category="download",
        title="Test Download",
        message="Downloading file...",
        progress=25.0,
        item_id="task-1"
    )
    assert item.id == "task-1"
    assert len(store.get_items()) == 1
    assert store.unread_count() == 1

    # Update item
    store.update("task-1", progress=75.0, message="Almost done...")
    updated = store.get("task-1")
    assert updated is not None
    assert updated.progress == 75.0
    assert updated.message == "Almost done..."

    # Category filter
    store.add_session("Fabric 1.21.1", 3600, 7200, server="hypixel.net")
    assert len(store.get_items("all")) == 2
    assert len(store.get_items("download")) == 1
    assert len(store.get_items("session")) == 1

    # Mark all read
    store.mark_all_read()
    assert store.unread_count() == 0

    # Clear category
    store.clear_all("download")
    assert len(store.get_items("download")) == 0
    assert len(store.get_items("session")) == 1

    # Clear all
    store.clear_all()
    assert len(store.get_items()) == 0


def test_notification_store_listener():
    store = NotificationStore()
    notified = []

    def on_change():
        notified.append(True)

    store.add_listener(on_change)
    store.add(category="system", title="Hello", message="World")
    assert len(notified) == 1

    store.clear_all()
    assert len(notified) == 2


def test_update_notification_action_and_expiration():
    store = NotificationStore()
    called = []

    item = store.add_update(
        "3.0.5",
        asset_url="https://example.test/NLCUpdate.zip",
        on_update=lambda: called.append(True),
        dismiss_after=10.0,
    )

    assert item.action_callback is not None
    assert item.dismiss_after == 10.0
    assert item.expires_at is not None
    item.action_callback()
    assert called == [True]


def test_notification_drawer_lifecycle(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    store = NotificationStore()
    store.add_session("Survival 1.20", 120, 300)

    badge_updates = []
    drawer = NotificationCenterDrawer(
        tk_root,
        store,
        on_badge_update=lambda count: badge_updates.append(count)
    )

    assert not drawer.is_open

    drawer.open()
    assert drawer.is_open
    assert drawer._drawer_frame is not None
    assert drawer._drawer_frame.winfo_exists()

    drawer.close()
    assert not drawer.is_open


def test_toast_manager_downloads_and_sessions(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    tm = ToastManager(tk_root)

    # Show download toast
    tm.show_download_toast("dl-1", "Sodium 0.5", "Downloading...", 10.0)
    assert "dl-1" in tm._download_toasts

    # Update download toast
    tm.update_download_toast("dl-1", progress=60.0, detail="60% complete")

    # Complete download toast
    tm.complete_download_toast("dl-1", message="Done ✓")

    # Session toast
    tm.show_session_toast("Modded", 1800, 3600, server="mc.example.com")
    assert len(tm._toasts) > 0

    # Update toast
    called = []
    tm.show_update_toast("v2.5.0", on_update=lambda: called.append(True))
    assert len(tm._toasts) > 0


def test_toast_manager_level_alias(tk_root):
    if not tk_root:
        pytest.skip("Tkinter not available")

    tm = ToastManager(tk_root)
    # Both level="success" and level="info" should work without TypeError
    tm.show("Success message", level="success")
    tm.show("Info message", level="info")
    assert len(tm._toasts) >= 2


def test_update_notification_default_persistence():
    store = NotificationStore()
    item = store.add_update("3.0.6", asset_url="https://example.test/patch.zip")
    assert item.dismiss_after is None
    assert item.expires_at is None
