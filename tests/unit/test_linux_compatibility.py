import os
import sys
import json
import zipfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from nlc.storage.paths import get_launcher_data_dir, get_minecraft_dir, open_path_in_system
from nlc.update_engine import load_patch_manifest
from nlc.core.system_info import get_total_ram_mb
from nlc.core import vault


def test_update_manifest_accepts_linux_platform(tmp_path):
    manifest_data = {
        "formatVersion": 1,
        "platform": "linux",
        "baseVersion": "4.0.0",
        "targetVersion": "4.0.3",
        "files": [],
        "delete": [],
    }
    zip_path = tmp_path / "patch.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest_data))

    loaded = load_patch_manifest(zip_path)
    assert loaded["platform"] == "linux"
    assert loaded["targetVersion"] == "4.0.3"


def test_posix_paths_resolution(monkeypatch, tmp_path):
    fake_home = tmp_path / "home_user"
    fake_home.mkdir()
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr("nlc.storage.paths._CACHED_MC_DIR", None)

    data_dir = get_launcher_data_dir()
    assert data_dir == fake_home / ".nlc"

    mc_dir = get_minecraft_dir()
    assert mc_dir == str((fake_home / ".minecraft").resolve())


def test_open_path_in_system_linux(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello")

    with patch("sys.platform", "linux"), patch("subprocess.Popen") as mock_popen:
        res = open_path_in_system(test_file)
        assert res is True
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert args[0] == "xdg-open"
        assert str(test_file) in args[1]


def test_vault_linux_fallback_aesgcm(monkeypatch, tmp_path):
    # Test non-windows DPAPI fallback to local AES-256-GCM
    monkeypatch.setattr(sys, "platform", "linux")
    salt_file = tmp_path / ".vault_salt"

    vm = vault.VaultManager(salt_path=salt_file)
    assert vm.is_dpapi_available() is False

    secret = "mypassword123-super-secret"
    encrypted = vm.encrypt(secret)
    assert encrypted.startswith(vault.VAULT_PREFIX_LOCAL)
    assert vm.is_vault_string(encrypted) is True

    decrypted = vm.decrypt(encrypted)
    assert decrypted == secret


def test_system_info_linux_meminfo(tmp_path):
    meminfo_content = "MemTotal:       16324220 kB\nMemFree:         4123456 kB\n"
    fake_meminfo = tmp_path / "meminfo"
    fake_meminfo.write_text(meminfo_content, encoding="utf-8")

    with patch("os.sysconf", create=True, side_effect=AttributeError), patch("nlc.core.system_info.Path") as mock_path, patch("os.name", "posix"):
        mock_path.return_value = fake_meminfo
        ram = get_total_ram_mb()
        assert ram == 16324220 // 1024


def test_system_info_linux_sysconf():
    with patch("os.sysconf", create=True) as mock_sysconf:
        mock_sysconf.side_effect = lambda name: 4096 if name == "SC_PAGE_SIZE" else (4194304 if name == "SC_PHYS_PAGES" else None)
        ram = get_total_ram_mb()
        assert ram == (4194304 * 4096) // (1024 * 1024)


def test_agent_clipboard_linux():
    from agent import handle_system_copy_clipboard
    with patch("sys.platform", "linux"), patch("shutil.which") as mock_which, patch("subprocess.run") as mock_run:
        mock_which.side_effect = lambda t: "/usr/bin/" + t if t == "wl-copy" else None
        res = handle_system_copy_clipboard({"text": "copied_content"})
        assert res == {"status": "success"}
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ["wl-copy"]
        assert mock_run.call_args[1]["input"] == "copied_content".encode("utf-8")


def test_main_candidates_include_linux():
    import main
    assert hasattr(main, "main")
    # Verify candidates list in main.py contains linux binaries without .exe
    content = Path("main.py").read_text(encoding="utf-8")
    assert 'REPO_ROOT / "dist" / "NyLuna"' in content
    assert 'REPO_ROOT / "src" / "frontend" / "target" / "release" / "nlc-ui"' in content


def test_installer_app_import_without_winreg(monkeypatch):
    """Ensure packaging/windows/installer_app.py does not crash when winreg is absent on Linux."""
    orig_installer = sys.modules.pop("installer_app", None)
    pkg_win = str(Path(__file__).resolve().parent.parent.parent / "packaging" / "windows")
    if pkg_win not in sys.path:
        sys.path.insert(0, pkg_win)

    # Simulate non-Windows environment where winreg is missing
    monkeypatch.setitem(sys.modules, "winreg", None)

    try:
        import installer_app
        assert installer_app.winreg is None
        # Verify functions degrade gracefully
        assert installer_app._read_reg_str(None, "path", "val") == ""
        installer_app.remove_uninstall_entry()
        installer_app.register_uninstall_entry("C:/dummy")
        existing = installer_app.discover_existing_install_dir()
        assert isinstance(existing, str)
    finally:
        if orig_installer:
            sys.modules["installer_app"] = orig_installer

