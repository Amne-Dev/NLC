"""
Unit tests for NLC Centralized Version Management & Single Source of Truth Engine.
Verifies:
- Root VERSION loading and fallback
- SemVer parsing and bumping logic
- Repository synchronization and drift check
- CLI entry points
"""

import sys
import subprocess
import pytest
from pathlib import Path

from nlc.version import (
    get_version,
    parse_semver,
    bump_semver,
    sync_all,
    check_all,
    find_repo_root,
)


def test_get_version_matches_root_file():
    root = find_repo_root()
    v_file = root / "VERSION"
    assert v_file.is_file(), "VERSION file must exist at repo root"
    expected = v_file.read_text(encoding="utf-8").strip()
    assert get_version(root) == expected


def test_parse_semver_valid():
    assert parse_semver("3.0.6") == (3, 0, 6, "")
    assert parse_semver("v3.0.6") == (3, 0, 6, "")
    assert parse_semver("1.2.3-alpha.1") == (1, 2, 3, "alpha.1")


def test_parse_semver_invalid():
    with pytest.raises(ValueError):
        parse_semver("invalid-version")
    with pytest.raises(ValueError):
        parse_semver("3.0")


def test_bump_semver():
    assert bump_semver("3.0.6", "patch") == "3.0.7"
    assert bump_semver("3.0.6", "minor") == "3.1.0"
    assert bump_semver("3.0.6", "major") == "4.0.0"

    with pytest.raises(ValueError):
        bump_semver("3.0.6", "invalid_part")


def test_repository_files_are_in_sync():
    """Verifies that all project files currently match the canonical VERSION file."""
    in_sync, mismatches = check_all()
    assert in_sync, f"Version drift detected in repository: {mismatches}"


def test_sync_all_in_mock_workspace(tmp_path):
    # Setup mock workspace files
    v_file = tmp_path / "VERSION"
    v_file.write_text("3.0.6\n", encoding="utf-8")

    cargo_file = tmp_path / "src" / "frontend" / "Cargo.toml"
    cargo_file.parent.mkdir(parents=True, exist_ok=True)
    cargo_file.write_text('[package]\nname = "nlc-ui"\nversion = "3.0.6"\n', encoding="utf-8")

    installer_file = tmp_path / "packaging" / "windows" / "installer_app.py"
    installer_file.parent.mkdir(parents=True, exist_ok=True)
    installer_file.write_text('APP_VERSION = "3.0.6"\n', encoding="utf-8")

    splash_file = tmp_path / "src" / "frontend" / "ui" / "splash.slint"
    splash_file.parent.mkdir(parents=True, exist_ok=True)
    splash_file.write_text('Text { text: "NLC v3.0.6 • @Amne-Dev"; }\n', encoding="utf-8")

    # Run sync to 3.0.7
    results = sync_all(target_version="3.0.7", repo_root=tmp_path, update_cargo_lock=False)
    assert any(r["file"] == "VERSION" and r["changed"] for r in results)
    assert any(r["file"] == "src/frontend/Cargo.toml" and r["changed"] for r in results)
    assert any(r["file"] == "packaging/windows/installer_app.py" and r["changed"] for r in results)
    assert any(r["file"] == "src/frontend/ui/splash.slint" and r["changed"] for r in results)

    # Verify content
    assert v_file.read_text(encoding="utf-8").strip() == "3.0.7"
    assert 'version = "3.0.7"' in cargo_file.read_text(encoding="utf-8")
    assert 'APP_VERSION = "3.0.7"' in installer_file.read_text(encoding="utf-8")
    assert 'text: "NLC v3.0.7 • @Amne-Dev";' in splash_file.read_text(encoding="utf-8")

    # Verify check_all on mock workspace
    in_sync, mismatches = check_all(tmp_path)
    assert in_sync, f"Expected mock workspace to be in sync, got mismatches: {mismatches}"


def test_cli_get_and_check():
    repo_root = find_repo_root()
    cli_path = repo_root / "scripts" / "version.py"

    # Test 'get'
    res_get = subprocess.run([sys.executable, str(cli_path), "get"], capture_output=True, text=True)
    assert res_get.returncode == 0
    assert res_get.stdout.strip() == get_version(repo_root)

    # Test 'check'
    res_check = subprocess.run([sys.executable, str(cli_path), "check"], capture_output=True, text=True)
    assert res_check.returncode == 0
    assert "[+] All files are in sync" in res_check.stdout

