import os
import json
import shutil
import tempfile
from pathlib import Path
import pytest
from unittest.mock import patch

from nlc.storage.paths import get_launcher_data_dir
from nlc.storage.config import ConfigManager


@pytest.fixture
def temp_environment(tmp_path, monkeypatch):
    """Isolate config dir and launcher data dir for tests."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    data_dir = tmp_path / ".nlc"
    data_dir.mkdir(parents=True, exist_ok=True)
    skins_dir = data_dir / "skins"
    skins_dir.mkdir(parents=True, exist_ok=True)
    modpacks_dir = data_dir / "modpacks"
    modpacks_dir.mkdir(parents=True, exist_ok=True)

    # Mock get_config_dir and paths
    monkeypatch.setattr("agent.get_config_dir", lambda: str(data_dir))
    monkeypatch.setattr("agent.get_launcher_data_dir", lambda: str(data_dir))
    monkeypatch.setattr("nlc.storage.paths.get_launcher_data_dir", lambda: str(data_dir))

    # Initialize basic config.json
    cfg = {
        "profiles": [
            {
                "id": "test-uuid-1",
                "uuid": "test-uuid-1",
                "name": "AlexTester",
                "type": "offline",
                "skin_path": "",
                "skin_model": "classic",
                "head_path": "",
            }
        ],
        "active_profile_index": 0,
        "installations": [],
        "skin_arm_models": {},
    }
    cfg_file = data_dir / "config.json"
    with open(cfg_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    return {
        "root": tmp_path,
        "data_dir": data_dir,
        "skins_dir": skins_dir,
        "modpacks_dir": modpacks_dir,
        "cfg_file": cfg_file,
    }


def create_dummy_png(path: Path):
    """Create a minimal valid 64x64 PNG image."""
    from PIL import Image
    img = Image.new("RGBA", (64, 64), color=(255, 0, 0, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")


def test_skin_presets_seeding_marker_allows_deleting_to_zero(temp_environment):
    """Test that default skins do not aggressively respawn once seeded, allowing empty wardrobe."""
    from agent import handle_skin_presets_list, handle_skin_preset_delete

    skins_dir = temp_environment["skins_dir"]

    # Create dummy skins in bundled dir or skins_dir directly
    skin1 = skins_dir / "skin1.png"
    create_dummy_png(skin1)
    (skins_dir / ".seeded").touch()

    res = handle_skin_presets_list({})
    assert len(res["presets"]) == 1

    # Delete skin1
    del_res = handle_skin_preset_delete({"skin_path": str(skin1)})
    assert del_res["success"] is True
    assert del_res["remaining_count"] == 0

    # Next list call should return 0 presets and NOT respawn bundled skins
    res2 = handle_skin_presets_list({})
    assert len(res2["presets"]) == 0


def test_delete_inactive_skin_preset(temp_environment):
    """Deleting a preset that is NOT active should not affect the active profile."""
    from agent import handle_skin_presets_list, handle_skin_preset_delete, get_config_manager

    skins_dir = temp_environment["skins_dir"]
    active_skin = skins_dir / "active_skin.png"
    other_skin = skins_dir / "other_skin.png"
    create_dummy_png(active_skin)
    create_dummy_png(other_skin)
    (skins_dir / ".seeded").touch()

    cm = get_config_manager()
    cfg = cm.load()
    cfg["profiles"][0]["skin_path"] = str(active_skin)
    cm.save(cfg)

    # Delete other_skin
    del_res = handle_skin_preset_delete({"skin_path": str(other_skin)})
    assert del_res["success"] is True
    assert del_res["was_active"] is False

    cfg_after = cm.load()
    assert cfg_after["profiles"][0]["skin_path"] == str(active_skin)


def test_delete_active_skin_preset_falls_back_to_remaining(temp_environment):
    """Deleting the currently active preset should automatically fallback to the next preset."""
    from agent import handle_skin_presets_list, handle_skin_preset_delete, get_config_manager

    skins_dir = temp_environment["skins_dir"]
    skin_a = skins_dir / "skin_a.png"
    skin_b = skins_dir / "skin_b.png"
    create_dummy_png(skin_a)
    create_dummy_png(skin_b)
    (skins_dir / ".seeded").touch()

    cm = get_config_manager()
    cfg = cm.load()
    cfg["profiles"][0]["skin_path"] = str(skin_a)
    cfg["profiles"][0]["skin_model"] = "slim"
    cfg.setdefault("skin_arm_models", {})["skin_b.png"] = "classic"
    cm.save(cfg)

    # Delete skin_a (which is active)
    del_res = handle_skin_preset_delete({"skin_path": str(skin_a)})
    assert del_res["success"] is True
    assert del_res["was_active"] is True
    assert del_res["remaining_count"] == 1
    assert Path(del_res["active_skin_path"]).resolve() == skin_b.resolve()

    cfg_after = cm.load()
    assert Path(cfg_after["profiles"][0]["skin_path"]).resolve() == skin_b.resolve()


def test_delete_last_active_skin_preset_falls_back_to_steve(temp_environment):
    """Deleting the last active preset should fallback to default Steve and not break config."""
    from agent import handle_skin_presets_list, handle_skin_preset_delete, get_config_manager

    skins_dir = temp_environment["skins_dir"]
    skin_only = skins_dir / "lone_skin.png"
    create_dummy_png(skin_only)
    (skins_dir / ".seeded").touch()

    cm = get_config_manager()
    cfg = cm.load()
    cfg["profiles"][0]["skin_path"] = str(skin_only)
    cm.save(cfg)

    del_res = handle_skin_preset_delete({"skin_path": str(skin_only)})
    assert del_res["success"] is True
    assert del_res["was_active"] is True
    assert del_res["remaining_count"] == 0

    cfg_after = cm.load()
    assert cfg_after["profiles"][0]["skin_path"] != str(skin_only)
    assert os.path.exists(cfg_after["profiles"][0]["skin_path"])


def test_modpack_mods_toggle_and_remove_sync(temp_environment):
    """Test that toggling and removing mods updates files on disk, modpacks.json, and linked installation."""
    from agent import handle_modpack_mods_toggle, handle_modpack_mods_remove, handle_modpack_mods_list, _save_modpacks_json

    pack_id = "test-pack-123"
    pack_dir = temp_environment["data_dir"] / "modpacks" / pack_id
    mods_dir = pack_dir / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy mod
    mod_jar = mods_dir / "test-mod-1.0.jar"
    mod_jar.write_bytes(b"PK\x05\x06" + b"\x00" * 18)

    # Create modpack entry in modpacks.json
    packs = [{
        "id": pack_id,
        "name": "Test Pack",
        "loader": "fabric",
        "version": "1.21.1",
        "mods": [
            {
                "slug": "test-mod",
                "filename": "test-mod-1.0.jar",
                "enabled": True,
            }
        ]
    }]
    _save_modpacks_json(packs)

    # 1. Test Toggle: Disable
    toggle_res = handle_modpack_mods_toggle({"pack_id": pack_id, "filename": "test-mod-1.0.jar", "enabled": False})
    assert toggle_res["success"] is True
    assert (mods_dir / "test-mod-1.0.jar.disabled").exists()
    assert not (mods_dir / "test-mod-1.0.jar").exists()

    # Verify list reflects disabled
    list_res = handle_modpack_mods_list({"pack_id": pack_id})
    assert len(list_res["mods"]) == 1
    assert list_res["mods"][0]["is_active"] is False

    # 2. Test Toggle: Re-enable
    toggle_res2 = handle_modpack_mods_toggle({"pack_id": pack_id, "filename": "test-mod-1.0.jar.disabled", "enabled": True})
    assert toggle_res2["success"] is True
    assert (mods_dir / "test-mod-1.0.jar").exists()
    assert not (mods_dir / "test-mod-1.0.jar.disabled").exists()

    # 3. Test Remove
    rm_res = handle_modpack_mods_remove({"pack_id": pack_id, "filename": "test-mod-1.0.jar"})
    assert rm_res["success"] is True
    assert not (mods_dir / "test-mod-1.0.jar").exists()

    # Verify list is empty
    list_res2 = handle_modpack_mods_list({"pack_id": pack_id})
    assert len(list_res2["mods"]) == 0
