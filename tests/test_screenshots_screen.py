import os
import sys
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nlc.ui.screens.screenshots import ScreenshotScreenMixin
from agent import addon_list_screenshot_files, addon_delete_screenshot


def test_addon_list_and_delete_screenshots(tmp_path):
    mc_dir = tmp_path / ".minecraft"
    ss_dir = mc_dir / "screenshots"
    ss_dir.mkdir(parents=True)

    img_1 = ss_dir / "2026-10-10_12.00.00.png"
    img_2 = ss_dir / "2026-10-10_13.00.00.png"
    img_1.write_bytes(b"\x89PNG\r\n\x1a\nfakeimage1")
    img_2.write_bytes(b"\x89PNG\r\n\x1a\nfakeimage2")

    res = addon_list_screenshot_files(str(mc_dir))
    assert len(res["items"]) == 2
    assert str(img_1) in res["items"] or str(img_2) in res["items"]

    # Delete img_1
    del_res = addon_delete_screenshot(str(img_1), str(mc_dir))
    assert not img_1.exists()

    res2 = addon_list_screenshot_files(str(mc_dir))
    assert len(res2["items"]) == 1
    assert str(img_2) in res2["items"]


def test_screenshot_screen_mixin_attributes():
    class DummyApp(ScreenshotScreenMixin):
        def __init__(self):
            self.minecraft_dir = "C:/mock/.minecraft"

    app = DummyApp()
    assert app.get_screenshots_dir() == os.path.join("C:/mock/.minecraft", "screenshots")

