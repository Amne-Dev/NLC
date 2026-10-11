import hashlib
import json
import zipfile

import pytest

from nlc.core.updater import apply_patch


def make_patch(path, files, *, manifest_files=None):
    entries = []
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(f"files/{name}", content)
            entries.append({
                "path": name,
                "sha256": hashlib.sha256(content).hexdigest(),
            })
        if manifest_files is not None:
            entries = manifest_files
        archive.writestr("manifest.json", json.dumps({
            "formatVersion": 1,
            "platform": "windows",
            "files": entries,
        }))


def test_apply_patch_replaces_only_manifest_files(tmp_path):
    target = tmp_path / "install"
    target.mkdir()
    (target / "NewLauncher.exe").write_bytes(b"old")
    (target / "launcher_config.json").write_text("keep", encoding="utf-8")
    package = tmp_path / "patch.zip"
    make_patch(package, {"NewLauncher.exe": b"new"})

    apply_patch(package, target)

    assert (target / "NewLauncher.exe").read_bytes() == b"new"
    assert (target / "launcher_config.json").read_text(encoding="utf-8") == "keep"


def test_apply_patch_rejects_traversal(tmp_path):
    package = tmp_path / "patch.zip"
    (tmp_path / "install").mkdir()
    make_patch(package, {}, manifest_files=[{
        "path": "../launcher_config.json",
        "sha256": "0" * 64,
    }])

    with pytest.raises(ValueError):
        apply_patch(package, tmp_path / "install")


def test_apply_patch_rejects_checksum_mismatch(tmp_path):
    target = tmp_path / "install"
    target.mkdir()
    (target / "NewLauncher.exe").write_bytes(b"old")
    package = tmp_path / "patch.zip"
    make_patch(package, {"NewLauncher.exe": b"new"}, manifest_files=[{
        "path": "NewLauncher.exe",
        "sha256": hashlib.sha256(b"wrong").hexdigest(),
    }])

    with pytest.raises(ValueError):
        apply_patch(package, target)
    assert (target / "NewLauncher.exe").read_bytes() == b"old"
