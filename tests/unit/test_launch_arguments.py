import json
import os
import platform
import tempfile
import pytest

import minecraft_launcher_lib
from nlc.core.launch import (
    safe_get_minecraft_arguments,
    safe_inherit_json,
    apply_launcher_lib_patches,
)


@pytest.fixture(autouse=True)
def patch_launcher_lib():
    apply_launcher_lib_patches()


def test_safe_get_minecraft_arguments_strings():
    data = ["--username", "TestPlayer", "--version", "1.20"]
    version_data = {"id": "1.20", "type": "release"}
    options = {"nativesDirectory": "natives"}
    classpath = "dummy.jar"
    result = safe_get_minecraft_arguments(data, version_data, "", options, classpath)
    assert result == ["--username", "TestPlayer", "--version", "1.20"]


def test_safe_get_minecraft_arguments_value_singular_string():
    data = [
        {"rules": [], "value": "-Xmx2G"},
        {"rules": [], "value": "-Dfile.encoding=UTF-8"},
    ]
    version_data = {"id": "1.20", "type": "release"}
    options = {"nativesDirectory": "natives"}
    result = safe_get_minecraft_arguments(data, version_data, "", options, "dummy.jar")
    assert result == ["-Xmx2G", "-Dfile.encoding=UTF-8"]


def test_safe_get_minecraft_arguments_value_singular_list():
    data = [
        {"rules": [], "value": ["-cp", "${classpath}"]},
    ]
    version_data = {"id": "1.20", "type": "release"}
    options = {"nativesDirectory": "natives"}
    result = safe_get_minecraft_arguments(data, version_data, "", options, "libs.jar")
    assert result == ["-cp", "libs.jar"]


def test_safe_get_minecraft_arguments_values_plural_fabric_format():
    """Validates the exact format produced in Fabric 26.2 manifests where all arguments use 'values'."""
    data = [
        {
            "rules": [{"action": "allow", "os": {"name": "windows"}}],
            "values": ["-XX:HeapDumpPath=MojangTricksIntelDriversForPerformance_javaw.exe_minecraft.exe.heapdump"],
        },
        {"rules": [], "values": ["-cp"]},
        {"rules": [], "values": ["${classpath}"]},
        {"rules": [], "values": ["-DFabricMcEmu= net.minecraft.client.main.Main "]},
        {"rules": [], "values": ["--username"]},
        {"rules": [], "values": ["${auth_player_name}"]},
        {"rules": [], "values": ["--gameDir"]},
        {"rules": [], "values": ["${game_directory}"]},
    ]
    version_data = {"id": "Fabric 26.2", "type": "release"}
    options = {
        "username": "yufui",
        "gameDirectory": "C:/mc",
        "nativesDirectory": "C:/mc/natives",
    }
    classpath = "C:/mc/libraries/all.jar"

    result = safe_get_minecraft_arguments(data, version_data, "C:/mc", options, classpath)

    assert "-cp" in result
    assert "C:/mc/libraries/all.jar" in result
    assert "-DFabricMcEmu= net.minecraft.client.main.Main " in result
    assert "--username" in result
    assert "yufui" in result
    assert "--gameDir" in result
    assert "C:/mc" in result

    if platform.system() == "Windows":
        assert any("MojangTricksIntelDrivers" in arg for arg in result)


def test_safe_get_minecraft_arguments_rules_filtering():
    data = [
        {
            "rules": [{"action": "allow", "os": {"name": "osx"}}],
            "values": ["-XstartOnFirstThread"],
        },
        {
            "rules": [{"action": "allow", "os": {"name": "windows"}}],
            "values": ["-Dwindows.specific=true"],
        },
    ]
    version_data = {"id": "test_rules", "type": "release"}
    options = {"nativesDirectory": "natives"}
    result = safe_get_minecraft_arguments(data, version_data, "", options, "")

    if platform.system() == "Windows":
        assert "-Dwindows.specific=true" in result
        assert "-XstartOnFirstThread" not in result
    elif platform.system() == "Darwin":
        assert "-XstartOnFirstThread" in result
        assert "-Dwindows.specific=true" not in result


def test_safe_get_minecraft_arguments_simulated_linux(monkeypatch):
    """Ensures Linux compatibility by verifying argument parsing under a simulated Linux environment."""
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    data = [
        {
            "rules": [{"action": "allow", "os": {"name": "windows"}}],
            "values": ["-Dwindows.flag=true"],
        },
        {
            "rules": [{"action": "allow", "os": {"name": "linux"}}],
            "values": ["-Dlinux.flag=true", "-Dawt.useSystemAAFontSettings=on"],
        },
        {
            "rules": [{"action": "allow", "os": {"name": "osx"}}],
            "values": ["-XstartOnFirstThread"],
        },
        {"rules": [], "values": ["-cp"]},
        {"rules": [], "values": ["${classpath}"]},
    ]
    version_data = {"id": "linux_test", "type": "release"}
    options = {
        "nativesDirectory": "/home/user/.minecraft/natives",
    }
    classpath = "/home/user/.minecraft/libraries/test.jar"

    result = safe_get_minecraft_arguments(data, version_data, "/home/user/.minecraft", options, classpath)

    assert "-Dlinux.flag=true" in result
    assert "-Dawt.useSystemAAFontSettings=on" in result
    assert "-cp" in result
    assert "/home/user/.minecraft/libraries/test.jar" in result
    assert "-Dwindows.flag=true" not in result
    assert "-XstartOnFirstThread" not in result


def test_safe_get_minecraft_arguments_malformed_handling():
    data = [
        "valid_str",
        12345,  # non-dict, non-str
        None,
        {"rules": []},  # missing both value and values
        {"values": [123, None, "valid_in_list"]},  # mixed types in values list
        {"value": 9999},  # non-str non-list value
    ]
    version_data = {"id": "malformed_test", "type": "release"}
    options = {"nativesDirectory": "natives"}
    result = safe_get_minecraft_arguments(data, version_data, "", options, "")
    assert result == ["valid_str", "valid_in_list"]


def test_safe_inherit_json_recursive(tmp_path):
    # Grandparent version
    base_dir = tmp_path / "versions"
    grandparent_dir = base_dir / "base"
    grandparent_dir.mkdir(parents=True)
    grandparent_json = {
        "id": "base",
        "libraries": [{"name": "org.base:core:1.0"}],
        "arguments": {
            "jvm": ["-Dbase=true"],
            "game": ["--baseFlag"]
        }
    }
    (grandparent_dir / "base.json").write_text(json.dumps(grandparent_json), encoding="utf-8")

    # Parent version
    parent_dir = base_dir / "parent"
    parent_dir.mkdir(parents=True)
    parent_json = {
        "id": "parent",
        "inheritsFrom": "base",
        "libraries": [{"name": "org.parent:mod:1.0"}],
        "arguments": {
            "jvm": ["-Dparent=true"],
            "game": ["--parentFlag"]
        }
    }
    (parent_dir / "parent.json").write_text(json.dumps(parent_json), encoding="utf-8")

    # Child version
    child_json = {
        "id": "child",
        "inheritsFrom": "parent",
        "libraries": [{"name": "org.child:addon:1.0"}],
        "arguments": {
            "jvm": ["-Dchild=true"],
            "game": ["--childFlag"]
        }
    }

    merged = safe_inherit_json(child_json, str(tmp_path))
    assert merged["id"] == "child"  # preserves the child version id
    lib_names = [lib["name"] for lib in merged["libraries"]]
    assert "org.child:addon:1.0" in lib_names
    assert "org.parent:mod:1.0" in lib_names
    assert "org.base:core:1.0" in lib_names

    jvm_args = merged["arguments"]["jvm"]
    assert "-Dchild=true" in jvm_args
    assert "-Dparent=true" in jvm_args
    assert "-Dbase=true" in jvm_args


def test_end_to_end_command_generation_with_values_format(tmp_path):
    mc_dir = str(tmp_path)
    ver_dir = tmp_path / "versions" / "fabric-26.2"
    ver_dir.mkdir(parents=True)

    ver_json = {
        "id": "fabric-26.2",
        "type": "release",
        "mainClass": "net.fabricmc.loader.impl.launch.knot.KnotClient",
        "arguments": {
            "jvm": [
                {"rules": [], "values": ["-Dminecraft.launcher.brand=NewLauncher"]},
                {"rules": [], "values": ["-cp"]},
                {"rules": [], "values": ["${classpath}"]},
            ],
            "game": [
                {"rules": [], "values": ["--username"]},
                {"rules": [], "values": ["${auth_player_name}"]},
                {"rules": [], "values": ["--version"]},
                {"rules": [], "values": ["${version_name}"]},
                {"rules": [], "values": ["--gameDir"]},
                {"rules": [], "values": ["${game_directory}"]},
            ],
        },
        "libraries": [
            {
                "name": "net.fabricmc:fabric-loader:0.20.1",
                "downloads": {
                    "artifact": {
                        "path": "net/fabricmc/fabric-loader/0.20.1/fabric-loader-0.20.1.jar"
                    }
                }
            }
        ]
    }
    (ver_dir / "fabric-26.2.json").write_text(json.dumps(ver_json), encoding="utf-8")

    options = {
        "username": "yufui",
        "uuid": "3a23327c-f1e8-487b-b664-92f160ca05f8",
        "token": "0",
        "gameDirectory": str(tmp_path / "instances" / "puh"),
        "executablePath": "javaw.exe",
    }

    cmd = minecraft_launcher_lib.command.get_minecraft_command("fabric-26.2", mc_dir, options)

    assert "javaw.exe" in cmd
    assert "-cp" in cmd
    assert "-Dminecraft.launcher.brand=NewLauncher" in cmd
    assert "net.fabricmc.loader.impl.launch.knot.KnotClient" in cmd
    assert "--username" in cmd
    assert "yufui" in cmd
    assert "--version" in cmd
    assert "fabric-26.2" in cmd
    assert "--gameDir" in cmd
    assert str(tmp_path / "instances" / "puh") in cmd
