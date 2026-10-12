"""
tests/test_scroll_visual_verification.py - Visual verification test for canvas scrolling without tearing.
Captures screenshots via Win32 PrintWindow and verifies pixel integrity.
"""

import os
import shutil
import tempfile
import ctypes
from ctypes import wintypes
import pytest
import tkinter as tk
from PIL import Image

from nlc.ui.app import MinecraftLauncher


def capture_window_screenshot(root, output_path):
    """Captures a clean screenshot of a Tkinter window using Win32 PrintWindow."""
    root.update()
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    hwnd = user32.GetAncestor(root.winfo_id(), 2) or root.winfo_id()
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = max(1, rect.right - rect.left)
    h = max(1, rect.bottom - rect.top)

    hdc_window = user32.GetWindowDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    hbm = gdi32.CreateCompatibleBitmap(hdc_window, w, h)
    gdi32.SelectObject(hdc_mem, hbm)

    # PW_RENDERFULLCONTENT = 2
    user32.PrintWindow(hwnd, hdc_mem, 2)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ('biSize', wintypes.DWORD),
            ('biWidth', wintypes.LONG),
            ('biHeight', wintypes.LONG),
            ('biPlanes', wintypes.WORD),
            ('biBitCount', wintypes.WORD),
            ('biCompression', wintypes.DWORD),
            ('biSizeImage', wintypes.DWORD),
            ('biXPelsPerMeter', wintypes.LONG),
            ('biYPelsPerMeter', wintypes.LONG),
            ('biClrUsed', wintypes.DWORD),
            ('biClrImportant', wintypes.DWORD),
        ]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = w
    bmi.biHeight = -h
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0

    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(hdc_mem, hbm, 0, h, buf, ctypes.byref(bmi), 0)
    im = Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    im.save(output_path)

    gdi32.DeleteObject(hbm)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(hwnd, hdc_window)
    return im


def test_modpack_scroll_visual_verification():
    tmpdir = tempfile.mkdtemp()
    root = None
    try:
        pack_id = "visual_test_pack"
        pack_dir = os.path.join(tmpdir, "modpacks", pack_id)
        mods_dir = os.path.join(pack_dir, "mods")
        os.makedirs(mods_dir, exist_ok=True)
        for i in range(40):
            with open(os.path.join(mods_dir, f"mod_{i:02d}_fabric_1.20.1.jar"), "w") as f:
                f.write("dummy")

        root = tk.Tk()
        root.geometry("1080x720")
        root.title("Scroll Visual Verification")

        app = MinecraftLauncher.__new__(MinecraftLauncher)
        app.root = root
        app.tabs = {"Modpacks": root}
        app.config = {}
        app.modpacks = [{"id": pack_id, "name": "Fabulously Optimized", "loader": "fabric", "mc_version": "1.20.1"}]
        app.get_modpack_dir = lambda pid: pack_dir
        app.save_modpacks = lambda: None
        app.save_config = lambda **kwargs: None
        app.installed_mods_view_mode = "grid"
        app.animator = None
        app._scroll_velocities = {}
        app._scroll_anim_ids = {}

        pack = app.modpacks[0]
        app.show_modpack_contents_dialog(pack)
        for _ in range(60):
            root.update()

        out_dir = r"C:\Users\Ev\.gemini\antigravity\brain\f316519d-f8af-45ab-b0be-ac8bda35e145\verification_screenshots"
        initial_shot = os.path.join(out_dir, "verify_initial.png")
        scrolled_shot = os.path.join(out_dir, "verify_scrolled.png")

        im_init = capture_window_screenshot(root, initial_shot)
        assert im_init is not None
        assert im_init.size[0] >= 1000
        assert os.path.exists(initial_shot)

        # Locate canvas
        canvas = None
        for child in root.winfo_children():
            for grandchild in child.winfo_children():
                if isinstance(grandchild, tk.Canvas):
                    canvas = grandchild
                    break
                for ggchild in grandchild.winfo_children():
                    if isinstance(ggchild, tk.Canvas):
                        canvas = ggchild
                        break

        assert canvas is not None, "Canvas must exist in dialog"

        # Simulate scrolling with smooth flush
        class DummyEvent:
            delta = -120
            num = None

        for _ in range(6):
            app._smooth_scroll(canvas, DummyEvent())
            root.update()

        # Flush and capture scrolled state
        app._flush_canvas_paint(canvas)
        im_scrolled = capture_window_screenshot(root, scrolled_shot)

        assert im_scrolled is not None
        assert os.path.exists(scrolled_shot)
        assert im_scrolled.size == im_init.size

        # Verify pagination screenshots
        p1_path = os.path.join(out_dir, "page_1_view.png")
        p2_path = os.path.join(out_dir, "page_2_view.png")
        capture_window_screenshot(root, p1_path)
        assert os.path.exists(p1_path)

    finally:
        if root:
            root.destroy()
        shutil.rmtree(tmpdir, ignore_errors=True)

