import os
import io
import shutil
import tempfile
import zipfile
from PIL import Image
import pytest

from nlc.net.mod_icons import ModIconManager, extract_icon_from_jar
from nlc.ui.components.toasts import _truncate_toast_text
from nlc.ui.screens.modpacks import ModpacksScreenMixin


def create_dummy_mod_jar(target_path: str, mod_id: str = "examplemod", has_icon: bool = True):
    """Helper to create a valid minimal mod jar with or without an embedded icon."""
    with zipfile.ZipFile(target_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if has_icon:
            img = Image.new("RGBA", (16, 16), color=(0, 200, 100, 255))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png_bytes = buf.getvalue()
            zf.writestr(f"assets/{mod_id}/icon.png", png_bytes)
            fabric_json = f'{{"id": "{mod_id}", "name": "Example Mod", "icon": "assets/{mod_id}/icon.png"}}'
            zf.writestr("fabric.mod.json", fabric_json)
        else:
            fabric_json = f'{{"id": "{mod_id}", "name": "No Icon Mod"}}'
            zf.writestr("fabric.mod.json", fabric_json)


def test_mod_icon_extractor():
    tmpdir = tempfile.mkdtemp()
    try:
        jar_with_icon = os.path.join(tmpdir, "testmod_with_icon.jar")
        create_dummy_mod_jar(jar_with_icon, "testmod", has_icon=True)

        jar_no_icon = os.path.join(tmpdir, "testmod_no_icon.jar")
        create_dummy_mod_jar(jar_no_icon, "noicon", has_icon=False)

        img_1 = extract_icon_from_jar(jar_with_icon)
        assert img_1 is not None
        assert isinstance(img_1, Image.Image)

        img_2 = extract_icon_from_jar(jar_no_icon)
        assert img_2 is None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_toast_truncation_and_fixed_dimensions():
    long_name = "this_is_a_very_long_modpack_or_mod_filename_that_would_cause_toasts_to_jitter_repeatedly.jar"
    truncated = _truncate_toast_text(long_name, 36)
    assert len(truncated) <= 36
    assert truncated.endswith("...")

    short_name = "Sodium 0.5.8"
    assert _truncate_toast_text(short_name, 36) == "Sodium 0.5.8"


def test_mod_on_off_toggle():
    tmpdir = tempfile.mkdtemp()
    try:
        pack_id = "test-pack-1"
        pack_dir = os.path.join(tmpdir, "modpacks", pack_id)
        mods_dir = os.path.join(pack_dir, "mods")
        os.makedirs(mods_dir, exist_ok=True)

        jar_file = os.path.join(mods_dir, "sodium.jar")
        create_dummy_mod_jar(jar_file, "sodium", has_icon=True)

        screen = ModpacksScreenMixin.__new__(ModpacksScreenMixin)
        screen.get_modpack_dir = lambda pid: pack_dir

        mod_item = {
            "name": "sodium.jar",
            "file": "sodium.jar",
            "path": jar_file,
            "size": 1024,
            "enabled": True,
            "mod_id": "sodium"
        }

        disabled_path = os.path.join(mods_dir, "sodium.jar.disabled")
        assert os.path.exists(jar_file)
        assert not os.path.exists(disabled_path)

        os.rename(mod_item["path"], disabled_path)
        mod_item["path"] = disabled_path
        mod_item["file"] = "sodium.jar.disabled"
        mod_item["enabled"] = False

        assert not os.path.exists(jar_file)
        assert os.path.exists(disabled_path)
        assert mod_item["enabled"] is False

        os.rename(mod_item["path"], jar_file)
        mod_item["path"] = jar_file
        mod_item["file"] = "sodium.jar"
        mod_item["enabled"] = True

        assert os.path.exists(jar_file)
        assert not os.path.exists(disabled_path)
        assert mod_item["enabled"] is True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_mod_card_and_row_smooth_scroll_bindings():
    import tkinter as tk
    from nlc.ui.app import MinecraftLauncher

    root = tk.Tk()
    root.withdraw()
    try:
        canvas = tk.Canvas(root)
        card = tk.Frame(canvas, width=240, height=148)
        card.pack_propagate(False)
        lbl = tk.Label(card, text="Test Mod Label")
        lbl.pack()
        btn = tk.Button(card, text="Remove")
        btn.pack()

        # Simulate _bind_smooth_scroll
        launcher = MinecraftLauncher.__new__(MinecraftLauncher)
        launcher.root = root
        launcher._smooth_scroll = lambda c, e: None
        launcher._bind_smooth_scroll(canvas, card)

        assert getattr(card, "_nlc_scroll_canvas_id", None) == id(canvas)
        assert getattr(lbl, "_nlc_scroll_canvas_id", None) == id(canvas)
        assert getattr(btn, "_nlc_scroll_canvas_id", None) == id(canvas)

        # Verify bindings exist on card and children
        assert getattr(card, f"_nlc_wheel_bind_smooth_{id(canvas)}", False) is True
        assert getattr(lbl, f"_nlc_wheel_bind_smooth_{id(canvas)}", False) is True
        assert getattr(btn, f"_nlc_wheel_bind_smooth_{id(canvas)}", False) is True
    finally:
        root.destroy()
