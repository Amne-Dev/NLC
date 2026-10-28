"""
Unit tests for Web Installer asset packaging and download/extraction (Option A).
Tests:
- package_assets_archive packages core UI, icons, skins, thumbnails, and default wallpapers.
- package_assets_archive excludes heavy non-default 4K wallpapers.
- download_web_payload downloads, verifies checksum, and extracts assets into target_dir.
- download_web_payload gracefully cleans up temp files and reports progress.
- install_payload_directories seeds wardrobe skins from target_dir/skins when bundled payload is absent.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
PKG_WIN = REPO_ROOT / "packaging" / "windows"
for p in (str(REPO_ROOT), str(SCRIPTS_DIR), str(PKG_WIN)):
    if p not in sys.path:
        sys.path.insert(0, p)

from generate_release_cdc import (
    DEFAULT_WALLPAPERS,
    package_assets_archive,
)
from installer_app import (
    download_web_payload,
    install_payload_directories,
)


@pytest.fixture
def temp_workspace(tmp_path: Path):
    """Creates a mock repository layout with assets, icons, skins, and wallpapers."""
    mock_root = tmp_path / "repo"
    mock_dist = tmp_path / "dist"
    mock_root.mkdir()
    mock_dist.mkdir()

    # Create dummy core assets
    assets_dir = mock_root / "assets"
    assets_dir.mkdir()
    (assets_dir / "logo.png").write_bytes(b"PNG_LOGO_DATA")
    (assets_dir / "spinner.gif").write_bytes(b"GIF_SPINNER_DATA")

    # Create dummy icons
    icons_dir = mock_root / "icons"
    icons_dir.mkdir()
    (icons_dir / "dirt.png").write_bytes(b"ICON_DIRT")
    (icons_dir / "stone.png").write_bytes(b"ICON_STONE")

    # Create dummy skins
    skins_dir = mock_root / "skins"
    skins_dir.mkdir()
    (skins_dir / "steve.png").write_bytes(b"SKIN_STEVE")
    (skins_dir / "alex.png").write_bytes(b"SKIN_ALEX")

    # Create dummy wallpapers & thumbnails
    wp_dir = mock_root / "wallpapers"
    thumbs_dir = wp_dir / "thumbnails"
    thumbs_dir.mkdir(parents=True)
    (thumbs_dir / "thumb_default.png").write_bytes(b"THUMB_DEFAULT")
    (thumbs_dir / "thumb_heavy.png").write_bytes(b"THUMB_HEAVY")

    # Default wallpaper (should be included in Option A)
    (wp_dir / "Island.png").write_bytes(b"WALLPAPER_ISLAND_DEFAULT")
    # Heavy non-default wallpaper (should NOT be included in Option A)
    (wp_dir / "image1.png").write_bytes(b"WALLPAPER_IMAGE1_HEAVY_NON_DEFAULT")

    return {
        "root": mock_root,
        "dist": mock_dist,
    }


def test_package_assets_archive_option_a(temp_workspace):
    """Verifies Option A bundling: core assets, icons, skins, thumbnails, default wallpapers included; non-default excluded."""
    mock_root = temp_workspace["root"]
    mock_dist = temp_workspace["dist"]

    base_url = "https://example.com/releases/v4.0.0"
    entry = package_assets_archive(mock_root, mock_dist, base_url)

    zip_path = mock_dist / "assets.zip"
    assert zip_path.is_file(), "assets.zip must be created in dist_dir"
    assert entry["name"] == "assets.zip"
    assert entry["size"] == zip_path.stat().st_size
    assert entry["sha256"] == hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert entry["download_url"] == f"{base_url}/assets.zip"

    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        # Verify core folders
        assert "assets/logo.png" in namelist
        assert "assets/spinner.gif" in namelist
        assert "icons/dirt.png" in namelist
        assert "skins/steve.png" in namelist
        assert "wallpapers/thumbnails/thumb_default.png" in namelist
        assert "wallpapers/thumbnails/thumb_heavy.png" in namelist

        # Verify Option A wallpaper filtering: Island.png included, image1.png excluded
        assert "wallpapers/Island.png" in namelist
        assert "wallpapers/image1.png" not in namelist


def test_download_web_payload_extracts_assets(tmp_path: Path):
    """Verifies that download_web_payload parses the manifest, downloads assets.zip, and unpacks it into target_dir."""
    target_install_dir = tmp_path / "installed_app"
    target_install_dir.mkdir()

    source_dir = tmp_path / "server_files"
    source_dir.mkdir()

    # Create dummy assets.zip
    zip_path = source_dir / "assets.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("assets/test_asset.txt", "hello asset")
        zf.writestr("icons/test_icon.png", "icon bytes")
        zf.writestr("skins/steve.png", "skin bytes")

    zip_bytes = zip_path.read_bytes()
    zip_sha = hashlib.sha256(zip_bytes).hexdigest()

    manifest = {
        "version": "4.0.0",
        "files": {},
        "assets": {
            "name": "assets.zip",
            "size": len(zip_bytes),
            "sha256": zip_sha,
            "download_url": str(zip_path),
        },
    }
    manifest_file = source_dir / "release_manifest.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

    progress_log: list[float] = []
    log_messages: list[str] = []

    download_web_payload(
        target_dir=str(target_install_dir),
        mirror_url=str(manifest_file),
        log_fn=lambda m: log_messages.append(m),
        progress_fn=lambda p: progress_log.append(p),
    )

    # Verify extracted contents
    assert (target_install_dir / "assets" / "test_asset.txt").read_text() == "hello asset"
    assert (target_install_dir / "icons" / "test_icon.png").read_text() == "icon bytes"
    assert (target_install_dir / "skins" / "steve.png").read_text() == "skin bytes"

    # Verify temp files cleaned up
    assert not (target_install_dir / "_assets_download.tmp").exists()

    # Verify progress reached >= 85%
    assert any(p >= 85.0 for p in progress_log)


def test_download_web_payload_corrupted_checksum(tmp_path: Path):
    """Verifies that download_web_payload detects checksum mismatch and logs a warning without crashing."""
    target_install_dir = tmp_path / "installed_app"
    target_install_dir.mkdir()

    source_dir = tmp_path / "server_files"
    source_dir.mkdir()

    zip_path = source_dir / "assets.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("assets/test.txt", "hello")

    manifest = {
        "version": "4.0.0",
        "files": {},
        "assets": {
            "name": "assets.zip",
            "size": 100,
            "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
            "download_url": str(zip_path),
        },
    }
    manifest_file = source_dir / "release_manifest.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

    log_messages: list[str] = []
    download_web_payload(
        target_dir=str(target_install_dir),
        mirror_url=str(manifest_file),
        log_fn=lambda m: log_messages.append(m),
    )

    # Warning should be logged
    assert any("checksum mismatch" in msg.lower() for msg in log_messages)
    # Target file should not have extracted
    assert not (target_install_dir / "assets" / "test.txt").exists()


def test_install_payload_directories_seeds_skins_from_target_dir(tmp_path: Path, monkeypatch):
    """Verifies that wardrobe skin seeding succeeds from target_dir/skins even when resolve_payload_file returns None."""
    target_dir = tmp_path / "target"
    target_skins = target_dir / "skins"
    target_skins.mkdir(parents=True)
    (target_skins / "steve.png").write_bytes(b"STEVE_SKIN_BYTES")
    (target_skins / "alex.png").write_bytes(b"ALEX_SKIN_BYTES")

    mock_appdata = tmp_path / "AppData" / "Roaming"
    monkeypatch.setenv("APPDATA", str(mock_appdata))

    # Mock resolve_payload_file to return None (simulating Web Installer without bundled payload)
    with patch("installer_app.resolve_payload_file", return_value=None):
        logs: list[str] = []
        install_payload_directories(str(target_dir), log_fn=lambda m: logs.append(m))

    user_skins_dir = mock_appdata / ".nlc" / "skins"
    assert user_skins_dir.is_dir()
    assert (user_skins_dir / "steve.png").read_bytes() == b"STEVE_SKIN_BYTES"
    assert (user_skins_dir / "alex.png").read_bytes() == b"ALEX_SKIN_BYTES"
    assert any("Seeded default wardrobe skins" in msg for msg in logs)

