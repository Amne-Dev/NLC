"""
Unit tests for packaging and Authenticode code signing:
- Web installer spec asset bundle staging (icons, wallpapers, skins, assets)
- Signtool detection and fallback (SIGNTOOL_PATH -> PATH -> Windows Kits)
- Code signing configuration and command generation (PFX & SHA-1 store modes)
- Graceful degradation and strict mode error handling
- Mock signtool execution flow
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PKG_WIN = REPO_ROOT / "packaging" / "windows"
if str(PKG_WIN) not in sys.path:
    sys.path.insert(0, str(PKG_WIN))

from build_installers import (
    build_signtool_command,
    find_signtool,
    get_signing_config,
    sign_binary,
)


def _extract_spec_datas_and_imports(spec_path: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """Evaluates or extracts datas and hiddenimports from a PyInstaller spec file."""
    content = spec_path.read_text(encoding="utf-8")
    
    # We can execute the spec file in a sandbox namespace with PyInstaller mock classes
    class MockAnalysis:
        def __init__(self, scripts=None, pathex=None, binaries=None, datas=None, hiddenimports=None, **kwargs):
            self.scripts = scripts or []
            self.binaries = binaries or []
            self.datas = datas or []
            self.hiddenimports = hiddenimports or []
            self.pure = []

    class MockPYZ:
        def __init__(self, pure, **kwargs):
            pass

    class MockEXE:
        def __init__(self, *args, **kwargs):
            pass

    sandbox = {
        "__file__": str(spec_path),
        "SPECPATH": str(spec_path.parent),
        "Analysis": MockAnalysis,
        "PYZ": MockPYZ,
        "EXE": MockEXE,
        "Path": Path,
        "os": os,
    }
    exec(content, sandbox)
    analysis_inst = sandbox["a"]
    return analysis_inst.datas, analysis_inst.hiddenimports


# ---------------------------------------------------------------------------
# Test 1: installer_web.spec is minimal and installer_offline.spec bundles offline payload
# ---------------------------------------------------------------------------
def test_web_installer_spec_asset_staging():
    specs = [
        p for p in [PKG_WIN / "installer_web.spec", REPO_ROOT / "installer_web.spec"] if p.is_file()
    ]

    for spec_path in specs:
        assert spec_path.is_file(), f"Spec file missing: {spec_path}"
        datas, hiddenimports = _extract_spec_datas_and_imports(spec_path)

        dest_targets = [dest for _, dest in datas]

        # Web installer must be minimal: heavy asset payloads are downloaded from repo, not bundled
        assert "payload/wallpapers" not in dest_targets, f"payload/wallpapers should NOT be bundled in minimal web installer {spec_path.name}"
        assert "payload/skins" not in dest_targets, f"payload/skins should NOT be bundled in minimal web installer {spec_path.name}"
        assert "payload/icons" not in dest_targets, f"payload/icons should NOT be bundled in minimal web installer {spec_path.name}"
        assert "payload/assets" not in dest_targets, f"payload/assets should NOT be bundled in minimal web installer {spec_path.name}"

        # Verify minimal required files at root ('.') for installer UI runtime
        root_sources = {Path(src).name: dest for src, dest in datas if dest == "."}

        for required_file in ["logo.ico", "logo.png", "config_healer.py", "VERSION"]:
            assert required_file in root_sources, f"{required_file} missing at root in {spec_path.name}"

        # Verify hidden imports
        required_imports = [
            "PIL",
            "PIL.Image",
            "PIL.ImageTk",
            "requests",
            "cryptography",
            "nlc.version",
            "nlc.cdc_engine",
        ]
        for imp in required_imports:
            assert imp in hiddenimports, f"Hidden import {imp} missing in {spec_path.name}"

    # Verify offline installer spec DOES bundle full offline payloads
    offline_spec = PKG_WIN / "installer_offline.spec"
    assert offline_spec.is_file(), f"Spec file missing: {offline_spec}"
    offline_datas, _ = _extract_spec_datas_and_imports(offline_spec)
    offline_dests = [dest for _, dest in offline_datas]
    for d in ["payload/icons", "payload/wallpapers", "payload/skins", "payload/assets"]:
        assert d in offline_dests, f"{d} missing in offline installer spec"


# ---------------------------------------------------------------------------
# Test 2: find_signtool discovery and graceful fallback
# ---------------------------------------------------------------------------
def test_find_signtool_from_env_var(monkeypatch, tmp_path):
    mock_tool = tmp_path / "custom_signtool.exe"
    mock_tool.write_bytes(b"mock_signtool")
    monkeypatch.setenv("SIGNTOOL_PATH", str(mock_tool))

    found = find_signtool()
    assert found is not None
    assert found.resolve() == mock_tool.resolve()


def test_find_signtool_graceful_fallback_when_absent(monkeypatch):
    monkeypatch.delenv("SIGNTOOL_PATH", raising=False)
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    monkeypatch.setattr(Path, "is_dir", lambda self: False)

    found = find_signtool()
    assert found is None


def test_find_signtool_from_windows_kits(monkeypatch, tmp_path):
    monkeypatch.delenv("SIGNTOOL_PATH", raising=False)
    monkeypatch.setattr(shutil, "which", lambda cmd: None)

    # Setup fake Windows Kits directory hierarchy
    kits_bin = tmp_path / "Windows Kits" / "10" / "bin"
    v1_tool = kits_bin / "10.0.19041.0" / "x64" / "signtool.exe"
    v2_tool = kits_bin / "10.0.22621.0" / "x64" / "signtool.exe"
    v2_tool.parent.mkdir(parents=True, exist_ok=True)
    v1_tool.parent.mkdir(parents=True, exist_ok=True)
    v1_tool.write_bytes(b"v1")
    v2_tool.write_bytes(b"v2")

    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path))

    found = find_signtool()
    assert found is not None
    # Must sort descending and pick the newest version (22621 > 19041)
    assert "10.0.22621.0" in str(found)


# ---------------------------------------------------------------------------
# Test 3: sign_binary graceful skip when unconfigured
# ---------------------------------------------------------------------------
def test_sign_binary_graceful_skip_when_unconfigured(monkeypatch, tmp_path, capsys):
    for k in ["SIGNTOOL_PATH", "SIGN_CERT_FILE", "SIGN_CERT_PATH", "SIGN_CERT_SHA1", "SIGN_CERT_THUMBPRINT", "SIGN_STRICT"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(shutil, "which", lambda cmd: None)

    test_file = tmp_path / "test_app.exe"
    test_file.write_bytes(b"MZfakebinary")

    # Should not raise, logs warning, returns False
    result = sign_binary(test_file, strict=False)
    assert result is False

    captured = capsys.readouterr()
    assert "[!] Code signing skipped" in captured.out
    assert "Continuing build..." in captured.out


# ---------------------------------------------------------------------------
# Test 4: sign_binary in strict mode raises RuntimeError when unconfigured
# ---------------------------------------------------------------------------
def test_sign_binary_strict_mode_raises_when_unconfigured(monkeypatch, tmp_path):
    for k in ["SIGNTOOL_PATH", "SIGN_CERT_FILE", "SIGN_CERT_PATH", "SIGN_CERT_SHA1", "SIGN_CERT_THUMBPRINT"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(shutil, "which", lambda cmd: None)

    test_file = tmp_path / "test_app.exe"
    test_file.write_bytes(b"MZfakebinary")

    with pytest.raises(RuntimeError, match="Code signing failed: signtool or certificate missing in strict mode"):
        sign_binary(test_file, strict=True)

    # Test via SIGN_STRICT environment variable
    monkeypatch.setenv("SIGN_STRICT", "1")
    with pytest.raises(RuntimeError, match="Code signing failed: signtool or certificate missing in strict mode"):
        sign_binary(test_file, strict=False)


# ---------------------------------------------------------------------------
# Test 5: Command line building for PFX file mode
# ---------------------------------------------------------------------------
def test_build_signtool_command_pfx_mode():
    signtool = Path("C:/WindowsKits/signtool.exe")
    target = Path("C:/build/dist/NyLuna.exe")
    config = {
        "cert_file": "C:/certs/release.pfx",
        "cert_password": "super_secret_pass",
        "timestamp_url": "http://timestamp.digicert.com",
        "app_name": "Ny-Luna Core",
    }

    cmd = build_signtool_command(signtool, target, config, description="Ny-Luna Core")

    assert cmd[0] == str(signtool)
    assert cmd[1] == "sign"
    assert "/fd" in cmd and cmd[cmd.index("/fd") + 1] == "SHA256"
    assert "/f" in cmd and cmd[cmd.index("/f") + 1] == "C:/certs/release.pfx"
    assert "/p" in cmd and cmd[cmd.index("/p") + 1] == "super_secret_pass"
    assert "/tr" in cmd and cmd[cmd.index("/tr") + 1] == "http://timestamp.digicert.com"
    assert "/td" in cmd and cmd[cmd.index("/td") + 1] == "SHA256"
    assert "/d" in cmd and cmd[cmd.index("/d") + 1] == "Ny-Luna Core"
    assert cmd[-1] == str(target)


# ---------------------------------------------------------------------------
# Test 6: Command line building for SHA1 certificate store mode
# ---------------------------------------------------------------------------
def test_build_signtool_command_sha1_store_mode():
    signtool = Path("C:/WindowsKits/signtool.exe")
    target = Path("C:/build/dist/agent.exe")
    config = {
        "cert_sha1": "A1B2C3D4E5F60123456789ABCDEF0123456789AB",
        "cert_store": "My",
        "store_location": "Machine",
        "timestamp_url": "http://timestamp.digicert.com",
        "app_name": "Ny-Luna Core Agent",
    }

    cmd = build_signtool_command(signtool, target, config, description="Ny-Luna Core Agent")

    assert cmd[0] == str(signtool)
    assert cmd[1] == "sign"
    assert "/fd" in cmd and cmd[cmd.index("/fd") + 1] == "SHA256"
    assert "/sha1" in cmd and cmd[cmd.index("/sha1") + 1] == "A1B2C3D4E5F60123456789ABCDEF0123456789AB"
    assert "/s" in cmd and cmd[cmd.index("/s") + 1] == "My"
    assert "/sm" in cmd
    assert "/tr" in cmd and cmd[cmd.index("/tr") + 1] == "http://timestamp.digicert.com"
    assert "/td" in cmd and cmd[cmd.index("/td") + 1] == "SHA256"
    assert "/d" in cmd and cmd[cmd.index("/d") + 1] == "Ny-Luna Core Agent"
    assert cmd[-1] == str(target)


# ---------------------------------------------------------------------------
# Test 7: Mock signtool execution flow (success and failure)
# ---------------------------------------------------------------------------
def test_sign_binary_mock_execution_success(monkeypatch, tmp_path):
    mock_tool = tmp_path / "signtool.exe"
    mock_tool.write_bytes(b"mock_signtool")
    target = tmp_path / "NyLuna.exe"
    target.write_bytes(b"MZbinary")

    monkeypatch.setenv("SIGNTOOL_PATH", str(mock_tool))
    monkeypatch.setenv("SIGN_CERT_FILE", "C:/certs/test.pfx")
    monkeypatch.setenv("SIGN_CERT_PASSWORD", "secret")

    executed_cmd = []

    def mock_run(cmd, *args, **kwargs):
        executed_cmd.extend(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr(subprocess, "run", mock_run)

    result = sign_binary(target, description="Ny-Luna Core", strict=True)
    assert result is True
    assert str(mock_tool) in executed_cmd
    assert "sign" in executed_cmd
    assert "/fd" in executed_cmd and executed_cmd[executed_cmd.index("/fd") + 1] == "SHA256"
    assert "/f" in executed_cmd and executed_cmd[executed_cmd.index("/f") + 1] == "C:/certs/test.pfx"
    assert str(target.resolve()) in executed_cmd


def test_sign_binary_mock_execution_failure_handling(monkeypatch, tmp_path):
    mock_tool = tmp_path / "signtool.exe"
    mock_tool.write_bytes(b"mock_signtool")
    target = tmp_path / "NyLuna.exe"
    target.write_bytes(b"MZbinary")

    monkeypatch.setenv("SIGNTOOL_PATH", str(mock_tool))
    monkeypatch.setenv("SIGN_CERT_FILE", "C:/certs/test.pfx")

    # Mock signtool returning exit code 1
    def mock_run_fail(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=1)

    monkeypatch.setattr(subprocess, "run", mock_run_fail)

    # In non-strict mode: logs warning and returns False
    res_non_strict = sign_binary(target, strict=False)
    assert res_non_strict is False

    # In strict mode: raises RuntimeError
    with pytest.raises(RuntimeError, match="Code signing failed: signtool exited with code 1"):
        sign_binary(target, strict=True)


# ---------------------------------------------------------------------------
# Test 8: Non-existent target file handling (unconditionally raises FileNotFoundError)
# ---------------------------------------------------------------------------
def test_sign_binary_missing_target_file(monkeypatch, tmp_path):
    missing_file = tmp_path / "non_existent.exe"

    # Non-strict mode
    with pytest.raises(FileNotFoundError, match="Target file for signing does not exist"):
        sign_binary(missing_file, strict=False)

    # Strict mode
    with pytest.raises(FileNotFoundError, match="Target file for signing does not exist"):
        sign_binary(missing_file, strict=True)


# ---------------------------------------------------------------------------
# Test 8b: Invalid SIGNTOOL_PATH falls back gracefully without crashing
# ---------------------------------------------------------------------------
def test_find_signtool_invalid_env_path_falls_back(monkeypatch, tmp_path):
    invalid_tool = tmp_path / "nonexistent" / "signtool.exe"
    monkeypatch.setenv("SIGNTOOL_PATH", str(invalid_tool))
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    monkeypatch.setattr(Path, "is_dir", lambda self: False)

    # find_signtool should ignore invalid SIGNTOOL_PATH and fall through to return None
    found = find_signtool()
    assert found is None

    # In non-strict mode, sign_binary with invalid SIGNTOOL_PATH skips gracefully
    target = tmp_path / "app.exe"
    target.write_bytes(b"MZfakebinary")
    monkeypatch.setenv("SIGN_CERT_FILE", "dummy.pfx")
    res = sign_binary(target, strict=False)
    assert res is False


# ---------------------------------------------------------------------------
# Test 9: Dry run mode logs command and returns True without executing signtool
# ---------------------------------------------------------------------------
def test_sign_binary_dry_run_mode(monkeypatch, tmp_path, capsys):
    mock_tool = tmp_path / "signtool.exe"
    mock_tool.write_bytes(b"mock_signtool")
    target = tmp_path / "NyLuna.exe"
    target.write_bytes(b"MZbinary")

    monkeypatch.setenv("SIGNTOOL_PATH", str(mock_tool))
    monkeypatch.setenv("SIGN_CERT_FILE", "C:/certs/test.pfx")
    monkeypatch.setenv("SIGN_CERT_PASSWORD", "secret_pass")

    # subprocess.run should NOT be called in dry run mode
    def fail_if_run(*args, **kwargs):
        raise AssertionError("subprocess.run should not be called in dry-run mode!")

    monkeypatch.setattr(subprocess, "run", fail_if_run)

    result = sign_binary(target, dry_run=True)
    assert result is True

    captured = capsys.readouterr()
    assert "[DRY RUN]" in captured.out
    assert "sign" in captured.out
    assert "/fd SHA256" in captured.out
    assert "/f C:/certs/test.pfx" in captured.out
    assert "/p secret_pass" in captured.out


# ---------------------------------------------------------------------------
# Test 10: Bundled wallpaper directory resolution in dev mode and installed mode
# ---------------------------------------------------------------------------
def test_bundled_wallpapers_dir_resolution(monkeypatch, tmp_path):
    backend_dir = REPO_ROOT / "src" / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    import agent

    # 1. Dev mode resolution: locates REPO_ROOT / wallpapers
    dev_wp_dir = agent.get_bundled_wallpapers_dir()
    assert dev_wp_dir.is_dir()
    assert (dev_wp_dir / "Island.png").is_file()

    # 2. Installed mode simulation: launcher_dir / wallpapers exists
    installed_dir = tmp_path / "installed_launcher"
    installed_wp_dir = installed_dir / "wallpapers"
    installed_wp_dir.mkdir(parents=True)
    (installed_wp_dir / "Island.png").write_bytes(b"mock_png")

    monkeypatch.setattr(agent, "get_launcher_dir", lambda: str(installed_dir))

    resolved_installed = agent.get_bundled_wallpapers_dir()
    assert resolved_installed.resolve() == installed_wp_dir.resolve()


