import json
import pytest
from pathlib import Path
from nlc.storage.config import ConfigManager, CURRENT_VERSION, get_default_config

def test_config_manager_creates_default_on_missing_file(tmp_path):
    cfg_file = tmp_path / "launcher_config.json"
    mgr = ConfigManager(cfg_file)
    data = mgr.load()

    assert cfg_file.exists()
    assert "profiles" in data
    assert "installations" in data
    assert len(data["profiles"]) > 0

def test_config_manager_atomic_save_and_backup(tmp_path):
    cfg_file = tmp_path / "launcher_config.json"
    mgr = ConfigManager(cfg_file)
    data = mgr.load()

    data["ram"] = 8192
    success = mgr.save(data)
    assert success is True

    # Reload and verify
    reloaded = mgr.load()
    assert reloaded["ram"] == 8192

    # Save again to verify .bak creation
    data["ram"] = 12288
    mgr.save(data)
    bak_file = tmp_path / "launcher_config.json.bak"
    assert bak_file.exists()

    with open(bak_file, "r") as f:
        bak_data = json.load(f)
    assert bak_data["ram"] == 8192

def test_config_manager_recovers_from_corrupt_file_using_backup(tmp_path):
    cfg_file = tmp_path / "launcher_config.json"
    mgr = ConfigManager(cfg_file)
    data = mgr.load()

    # Modify and save twice to establish backup
    data["profiles"][0]["name"] = "SavedProfile"
    mgr.save(data)
    data["ram"] = 6144
    mgr.save(data)

    # Now corrupt main config file
    cfg_file.write_text("{corrupt: json truncated...", encoding="utf-8")

    # Load should fallback to .bak
    recovered = mgr.load()
    assert recovered is not None
    assert recovered["profiles"][0]["name"] == "SavedProfile"
    assert (tmp_path / "launcher_config.json.corrupt").exists()

def test_config_manager_migrates_installations_and_preserves_active_id(tmp_path):
    cfg_file = tmp_path / "launcher_config.json"
    cfg_file.write_text(json.dumps({
        "version": "2.0.0",
        "profiles": [{"name": "Player", "type": "offline"}],
        "installations": [
            {"id": "kept", "name": "Primary", "version": "1.21.1"},
            {"id": "kept", "name": "Duplicate", "version": "1.20.1"},
            "invalid-record",
        ],
        "active_installation_id": "kept",
        "addons": {},
    }), encoding="utf-8")

    data = ConfigManager(cfg_file).load()

    assert data["version"] == CURRENT_VERSION
    assert len(data["installations"]) == 2
    assert data["installations"][0]["id"] == "kept"
    assert data["installations"][1]["id"] != "kept"
    assert data["active_installation_id"] == "kept"
    assert data["installations"][0]["game_directory"] == ""

    persisted = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert persisted["active_installation_id"] == "kept"
    assert persisted["installations"][1]["id"] == data["installations"][1]["id"]

def test_config_manager_repairs_profiles_without_overwriting_names(tmp_path):
    cfg_file = tmp_path / "launcher_config.json"
    cfg_file.write_text(json.dumps({
        "profiles": [
            {"name": "CustomPlayer", "type": "offline"},
            {"name": " ", "type": "offline"},
            {"type": "offline"},
        ],
        "installations": [],
        "addons": {},
    }), encoding="utf-8")

    data = ConfigManager(cfg_file).load()

    assert [profile["name"] for profile in data["profiles"]] == [
        "CustomPlayer",
        "Steve",
        "Steve",
    ]
