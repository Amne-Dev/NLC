import os
import shutil
import tempfile
from pathlib import Path
import pytest
from unittest.mock import patch

from agent import (
    _resolve_instance_mods_dir,
    handle_modpack_mods_list,
    handle_modpack_mods_toggle,
    handle_modpack_mods_remove,
    handle_mods_toggle_enabled,
)


@pytest.fixture
def mock_launcher_env(tmp_path, monkeypatch):
    """Sets up a temporary environment for NLC modpack and minecraft storage."""
    config_dir = tmp_path / ".nlc"
    mc_dir = tmp_path / ".minecraft"
    config_dir.mkdir(parents=True, exist_ok=True)
    mc_dir.mkdir(parents=True, exist_ok=True)

    # Global .minecraft/mods containing some unrelated mods
    global_mods = mc_dir / "mods"
    global_mods.mkdir(parents=True, exist_ok=True)
    (global_mods / "global_mod_do_not_leak.jar").write_bytes(b"PK3global")

    monkeypatch.setattr("agent.get_config_dir", lambda: str(config_dir))
    monkeypatch.setattr("agent.get_minecraft_dir", lambda: str(mc_dir))

    # Also patch load_launcher_config to avoid reading real user config
    monkeypatch.setattr("agent.load_launcher_config", lambda: {"installations": []})

    return {"config_dir": config_dir, "mc_dir": mc_dir}


def test_last_mod_deletion_returns_empty_and_no_leak(mock_launcher_env):
    """
    Verifies that when the last mod of a modpack is deleted,
    it returns an empty mod list [] and does NOT leak global .minecraft/mods
    or another modpack's mods.
    """
    config_dir = mock_launcher_env["config_dir"]
    pack_id = "test-pack-uuid-1234"
    pack_dir = config_dir / "modpacks" / pack_id / "mods"
    pack_dir.mkdir(parents=True, exist_ok=True)

    mod_file = pack_dir / "sole_mod.jar"
    mod_file.write_bytes(b"PK3mod")

    # Modpack exists and has 1 mod initially
    res_initial = handle_modpack_mods_list({"pack_id": pack_id})
    assert len(res_initial["mods"]) == 1
    assert res_initial["mods"][0]["filename"] == "sole_mod.jar"

    # Delete the sole mod
    del_res = handle_modpack_mods_remove({"pack_id": pack_id, "filename": "sole_mod.jar"})
    assert del_res["success"] is True
    assert not mod_file.exists()

    # Now verify the mods list is completely empty [] and did not leak global mods
    res_after = handle_modpack_mods_list({"pack_id": pack_id})
    assert res_after["success"] is True
    assert res_after["mods"] == []
    assert res_after["data"] == []


def test_mod_toggle_rename_on_disk_and_persistence(mock_launcher_env):
    """
    Verifies that disabling a mod renames the file to .jar.disabled on disk,
    and enabling it renames it back to .jar on disk.
    """
    config_dir = mock_launcher_env["config_dir"]
    pack_id = "test-pack-uuid-5678"
    pack_dir = config_dir / "modpacks" / pack_id / "mods"
    pack_dir.mkdir(parents=True, exist_ok=True)

    jar_path = pack_dir / "physicsmod.jar"
    disabled_path = pack_dir / "physicsmod.jar.disabled"
    jar_path.write_bytes(b"PK3physics")

    # 1. Toggle disabled (enabled=False)
    res_dis = handle_modpack_mods_toggle({
        "pack_id": pack_id,
        "filename": "physicsmod.jar",
        "enabled": False
    })
    assert res_dis["success"] is True
    assert not jar_path.exists()
    assert disabled_path.exists()

    # Listing mods should reflect disabled status
    list_dis = handle_modpack_mods_list({"pack_id": pack_id})
    assert len(list_dis["mods"]) == 1
    assert list_dis["mods"][0]["is_active"] is False
    assert list_dis["mods"][0]["filename"] == "physicsmod.jar.disabled"

    # 2. Toggle enabled (enabled=True)
    res_en = handle_modpack_mods_toggle({
        "pack_id": pack_id,
        "filename": "physicsmod.jar.disabled",
        "enabled": True
    })
    assert res_en["success"] is True
    assert jar_path.exists()
    assert not disabled_path.exists()

    # Listing mods should reflect enabled status
    list_en = handle_modpack_mods_list({"pack_id": pack_id})
    assert len(list_en["mods"]) == 1
    assert list_en["mods"][0]["is_active"] is True
    assert list_en["mods"][0]["filename"] == "physicsmod.jar"


def test_resolve_instance_mods_dir_no_empty_id_match(mock_launcher_env):
    """
    Verifies that empty string or whitespace instance_id does not falsely
    match an unlinked modpack in modpacks.json.
    """
    config_dir = mock_launcher_env["config_dir"]
    mp_json = config_dir / "modpacks.json"
    mp_json.write_text('[{"id": "dummy-pack-id", "name": "Dummy", "linked_installation_id": ""}]', encoding="utf-8")

    # Calling with empty string should fall back to default, not dummy-pack-id
    resolved = _resolve_instance_mods_dir("")
    assert "dummy-pack-id" not in resolved
    assert resolved == str(mock_launcher_env["mc_dir"] / "mods")


def test_remove_disabled_mod(mock_launcher_env):
    """
    Verifies that handle_modpack_mods_remove works when the mod is already disabled.
    """
    config_dir = mock_launcher_env["config_dir"]
    pack_id = "test-pack-uuid-9999"
    pack_dir = config_dir / "modpacks" / pack_id / "mods"
    pack_dir.mkdir(parents=True, exist_ok=True)

    disabled_file = pack_dir / "optifine.jar.disabled"
    disabled_file.write_bytes(b"PK3optifine")

    # Removal by clean name or full disabled name
    del_res = handle_modpack_mods_remove({"pack_id": pack_id, "filename": "optifine.jar"})
    assert del_res["success"] is True
    assert not disabled_file.exists()

