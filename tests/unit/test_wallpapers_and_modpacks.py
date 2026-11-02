import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
from PIL import Image

import agent
from nlc.core.versions import get_versions_for_loader, clear_version_cache


@pytest.fixture
def temp_workspace(monkeypatch):
    tmp_dir = Path(tempfile.mkdtemp(prefix="nlc_test_wp_"))
    config_dir = tmp_dir / "config"
    config_dir.mkdir(parents=True)
    launcher_dir = tmp_dir / "launcher"
    launcher_dir.mkdir(parents=True)
    icons_dir = launcher_dir / "icons" / "2x"
    icons_dir.mkdir(parents=True)
    (icons_dir / "crafting_table_front.png").write_bytes(b"mock_png_icon")
    (icons_dir / "furnace_front.png").write_bytes(b"mock_furnace_icon")

    monkeypatch.setattr(agent, "get_config_dir", lambda: str(config_dir))
    monkeypatch.setattr(agent, "get_launcher_dir", lambda: str(launcher_dir))
    monkeypatch.setattr("nlc.storage.paths.get_launcher_data_dir", lambda: str(tmp_dir / "data"))

    # Initial minimal config.json
    cm = agent.get_config_manager()
    cm.save({
        "current_wallpaper": "",
        "hidden_wallpapers": [],
        "profiles": [{"name": "Steve", "skin_path": "", "skin_model": "classic"}],
        "active_profile_index": 0,
    })

    yield {
        "root": tmp_dir,
        "config_dir": config_dir,
        "launcher_dir": launcher_dir,
    }

    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_custom_wallpaper_upload_and_list_non_png(temp_workspace):
    config_dir = temp_workspace["config_dir"]
    user_wp_dir = config_dir / "wallpapers"
    user_wp_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy jpg image
    dummy_jpg = temp_workspace["root"] / "sample.jpg"
    img = Image.new("RGB", (800, 600), color="blue")
    img.save(dummy_jpg, format="JPEG")

    res_up = agent.handle_wallpapers_upload({"path": str(dummy_jpg)})
    assert res_up["status"] == "success"
    uploaded_path = res_up["path"]
    assert Path(uploaded_path).exists()
    assert Path(uploaded_path).name.startswith("wp_")

    # List wallpapers
    res_list = agent.handle_wallpapers_list()
    assert res_list["status"] == "success"
    uploaded_items = [w for w in res_list["wallpapers"] if w["path"] == uploaded_path]
    assert len(uploaded_items) == 1
    item = uploaded_items[0]
    assert item["is_equipped"] is True
    assert item["is_downloaded"] is True
    assert Path(item["thumb_path"]).exists()


def test_delete_downloadable_wallpaper_persists_in_hidden(temp_workspace):
    # Before deletion, official wallpapers should appear
    res_list1 = agent.handle_wallpapers_list()
    assert len(res_list1["wallpapers"]) > 0
    first_official = res_list1["wallpapers"][0]
    first_fname = first_official["filename"]

    # Delete the wallpaper before downloading it
    res_del = agent.handle_wallpapers_delete({"filename": first_fname})
    assert res_del["status"] == "success"

    # Verify hidden_wallpapers in config
    cfg = agent.get_config_manager().load()
    assert any(first_fname.lower() in h.lower() for h in cfg.get("hidden_wallpapers", []))

    # After deletion, card is completely removed from list
    res_list2 = agent.handle_wallpapers_list()
    remaining_names = [w["filename"].lower() for w in res_list2["wallpapers"]]
    assert first_fname.lower() not in remaining_names


def test_delete_equipped_wallpaper_clears_background(temp_workspace):
    config_dir = temp_workspace["config_dir"]
    user_wp_dir = config_dir / "wallpapers"
    user_wp_dir.mkdir(parents=True, exist_ok=True)

    dummy_png = temp_workspace["root"] / "active.png"
    img = Image.new("RGB", (400, 300), color="green")
    img.save(dummy_png, format="PNG")

    res_up = agent.handle_wallpapers_upload({"path": str(dummy_png)})
    wp_path = res_up["path"]

    cfg = agent.get_config_manager().load()
    assert cfg.get("current_wallpaper") == wp_path

    # Delete equipped wallpaper
    res_del = agent.handle_wallpapers_delete({"path": wp_path})
    assert res_del["status"] == "success"

    # Config current_wallpaper should be cleared to ""
    cfg_after = agent.get_config_manager().load()
    assert cfg_after.get("current_wallpaper") == ""


def test_modpack_create_with_icon(temp_workspace):
    res = agent.handle_modpack_create({
        "name": "Fantasy Pack",
        "loader": "fabric",
        "mc_version": "26.3",
        "icon": "furnace_front.png",
    })
    assert res["status"] == "success"
    pack = res["data"]
    assert pack["name"] == "Fantasy Pack"
    assert pack["icon"] == "furnace_front.png"
    assert pack["icon_path"] == "furnace_front.png"

    # Verify icon was copied into pack directory
    pack_dir = Path(agent.get_config_dir()) / "modpacks" / pack["id"]
    assert (pack_dir / "icon.png").exists()

    # Verify handle_modpacks_list returns icon_path
    list_res = agent.handle_modpacks_list()
    packs = [p for p in list_res["modpacks"] if p["id"] == pack["id"]]
    assert len(packs) == 1
    assert packs[0]["has_icon"] is True


def test_dynamic_versions_loader_isolation():
    clear_version_cache()

    # NeoForge only supports 1.20.2+ and 26.x
    neoforge_data = get_versions_for_loader("NeoForge")
    neoforge_rels = neoforge_data["releases"]
    assert len(neoforge_rels) > 0
    assert "1.20.1" not in neoforge_rels
    assert "1.19.4" not in neoforge_rels
    assert "1.16.5" not in neoforge_rels
    assert "1.12.2" not in neoforge_rels
    assert "1.8.9" not in neoforge_rels
    assert "1.20.2" in neoforge_rels
    assert "26.3" in neoforge_rels

    # Fabric supports 1.14+
    fabric_data = get_versions_for_loader("Fabric")
    fabric_rels = fabric_data["releases"]
    assert "1.12.2" not in fabric_rels
    assert "1.8.9" not in fabric_rels
    assert "1.14" in fabric_rels

    # Forge supports legacy and 26.x
    forge_data = get_versions_for_loader("Forge")
    forge_rels = forge_data["releases"]
    assert "1.12.2" in forge_rels
    assert "26.3" in forge_rels

