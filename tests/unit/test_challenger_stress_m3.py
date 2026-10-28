"""
Empirical Adversarial Stress Test Suite for M3:
- Packaging spec datas existence and dual SPECPATH evaluation
- Nonexistent binary paths passed to sign_binary
- Signtool failure handling in strict and non-strict modes
- Cert path edge cases, empty passwords, special descriptions, timestamp overrides
- CLI flags verification
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

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


def _eval_spec(spec_file: Path, specpath: Path):
    class MockAnalysis:
        def __init__(self, scripts=None, pathex=None, binaries=None, datas=None, hiddenimports=None, **kwargs):
            self.scripts = scripts or []
            self.pathex = pathex or []
            self.binaries = binaries or []
            self.datas = datas or []
            self.hiddenimports = hiddenimports or []
            self.pure = []

    class MockPYZ:
        def __init__(self, *args, **kwargs):
            pass

    class MockEXE:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs
            self.args = args

    sandbox = {
        "__file__": str(spec_file),
        "SPECPATH": str(specpath),
        "Analysis": MockAnalysis,
        "PYZ": MockPYZ,
        "EXE": MockEXE,
        "Path": Path,
        "os": os,
    }
    content = spec_file.read_text(encoding="utf-8")
    exec(content, sandbox)
    return sandbox["a"], sandbox["exe"]


# ---------------------------------------------------------------------------
# 1. Spec Robustness & Datas Verification
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("spec_rel", [
    "packaging/windows/installer_web.spec",
    "installer_web.spec",
])
@pytest.mark.parametrize("sim_specpath", [
    REPO_ROOT,
    REPO_ROOT / "packaging" / "windows",
])
def test_spec_datas_and_paths_robustness(spec_rel, sim_specpath):
    spec_path = REPO_ROOT / spec_rel
    if not spec_path.is_file():
        pytest.skip(f"Optional spec path not present: {spec_rel}")

    analysis, exe = _eval_spec(spec_path, sim_specpath)

    # 1. Check entry script
    for script in analysis.scripts:
        assert Path(script).is_file(), f"Script entry not found: {script}"

    # 2. Check icon
    for icon in exe.kwargs.get("icon", []):
        assert Path(icon).is_file(), f"Icon not found: {icon}"

    # 3. Check every single entry in datas
    for src, dest in analysis.datas:
        src_p = Path(src)
        assert src_p.exists(), f"Datas source does not exist: {src} -> {dest}"
        if dest in [".", "payload"]:
            assert src_p.is_file(), f"Expected file for {dest}: {src}"
        elif dest.startswith("payload/"):
            assert src_p.is_dir() or src_p.is_file(), f"Expected dir/file for {dest}: {src}"


# ---------------------------------------------------------------------------
# 2. Nonexistent Binary Paths Passed to sign_binary (Challenger Defect 1 - Resolved)
# ---------------------------------------------------------------------------
def test_sign_binary_missing_target_file_should_raise_filenotfounderror(tmp_path):
    missing_binary = tmp_path / "phantom_app.exe"
    assert not missing_binary.exists()

    # The challenge specification requires:
    # Test nonexistent binary paths passed to sign_binary -> raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        sign_binary(missing_binary, strict=False)


# ---------------------------------------------------------------------------
# 3. Invalid SIGNTOOL_PATH in find_signtool (Challenger Defect 2 - Resolved)
# ---------------------------------------------------------------------------
def test_find_signtool_invalid_env_path_should_fallback(monkeypatch):
    monkeypatch.setenv("SIGNTOOL_PATH", r"C:\path\does\not\exist\signtool.exe")
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    monkeypatch.setattr(Path, "is_dir", lambda self: False)

    tool = find_signtool()
    assert tool is None or tool.is_file()


# ---------------------------------------------------------------------------
# 4. Signtool Execution Failures (Strict vs Non-Strict)
# ---------------------------------------------------------------------------
def test_sign_binary_signtool_nonzero_exit_code(monkeypatch, tmp_path):
    dummy_bin = tmp_path / "valid.exe"
    dummy_bin.write_bytes(b"MZfake")

    mock_tool = tmp_path / "signtool.exe"
    mock_tool.write_bytes(b"tool")

    monkeypatch.setenv("SIGNTOOL_PATH", str(mock_tool))
    monkeypatch.setenv("SIGN_CERT_FILE", "C:/certs/test.pfx")

    def mock_fail(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=2)

    monkeypatch.setattr(subprocess, "run", mock_fail)

    res = sign_binary(dummy_bin, strict=False)
    assert res is False

    with pytest.raises(RuntimeError, match="signtool exited with code 2"):
        sign_binary(dummy_bin, strict=True)


# ---------------------------------------------------------------------------
# 5. Weird Cert Paths, Empty Passwords, Special Chars, Timestamp URL Overrides
# ---------------------------------------------------------------------------
def test_signing_config_and_command_edge_cases(tmp_path):
    signtool = tmp_path / "signtool.exe"
    target = tmp_path / "app.exe"

    weird_paths = [
        r"C:\Program Files\Certs\my cert (prod).pfx",
        r"\\nas\builds\certs\code_signing.pfx",
        r"C:\certs\unicode_ñ_🚀.pfx",
        "relative/path/cert.p12",
    ]
    for p in weird_paths:
        cfg = get_signing_config(cert_file=p)
        assert cfg is not None
        cmd = build_signtool_command(signtool, target, cfg)
        assert "/f" in cmd
        assert cmd[cmd.index("/f") + 1] == p

    cfg_empty = get_signing_config(cert_file="test.pfx", cert_pass="")
    cmd_empty = build_signtool_command(signtool, target, cfg_empty)
    assert "/p" not in cmd_empty

    cfg_with_pass = get_signing_config(cert_file="test.pfx", cert_pass="pass123")
    cmd_with_pass = build_signtool_command(signtool, target, cfg_with_pass)
    assert "/p" in cmd_with_pass
    assert cmd_with_pass[cmd_with_pass.index("/p") + 1] == "pass123"

    special_descriptions = [
        "Ny-Luna Core & Co.",
        'Ny-Luna "Quotes" Test',
        "Ny-Luna | Pipe > Redirect < Test",
        "Ny-Luna %PATH% Test",
        "🚀 Ny-Luna v4.0",
    ]
    for desc in special_descriptions:
        cmd = build_signtool_command(signtool, target, cfg_with_pass, description=desc)
        assert "/d" in cmd
        assert cmd[cmd.index("/d") + 1] == desc

    os.environ["SIGN_TIMESTAMP_URL"] = "http://timestamp.sectigo.com"
    try:
        cfg_custom_ts = get_signing_config(cert_file="test.pfx")
        assert cfg_custom_ts["timestamp_url"] == "http://timestamp.sectigo.com"
        cmd_ts = build_signtool_command(signtool, target, cfg_custom_ts)
        assert "/tr" in cmd_ts
        assert cmd_ts[cmd_ts.index("/tr") + 1] == "http://timestamp.sectigo.com"
    finally:
        os.environ.pop("SIGN_TIMESTAMP_URL", None)

    os.environ["SIGN_TIMESTAMP_URL"] = ""
    try:
        cfg_no_ts = get_signing_config(cert_file="test.pfx")
        cmd_no_ts = build_signtool_command(signtool, target, cfg_no_ts)
        assert "/tr" not in cmd_no_ts
    finally:
        os.environ.pop("SIGN_TIMESTAMP_URL", None)
