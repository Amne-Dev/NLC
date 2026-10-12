import base64
import hashlib
import json
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import nlc.update_keys as update_keys
from nlc.update_engine import apply_patch, canonical_manifest_bytes


TEST_SIGNING_KEY = Ed25519PrivateKey.generate()
update_keys.PATCH_PUBLIC_KEY_B64 = base64.b64encode(
    TEST_SIGNING_KEY.public_key().public_bytes_raw()
).decode("ascii")


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
        manifest = {
            "formatVersion": 1,
            "platform": "windows",
            "baseVersion": "3.0.5",
            "targetVersion": "3.0.6",
            "files": entries,
        }
        manifest["signature"] = base64.b64encode(
            TEST_SIGNING_KEY.sign(canonical_manifest_bytes(manifest))
        ).decode("ascii")
        archive.writestr("manifest.json", json.dumps(manifest))


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


def test_apply_patch_restores_deleted_file_on_failure(tmp_path):
    target = tmp_path / "install"
    target.mkdir()
    (target / "legacy.dll").write_bytes(b"keep")
    package = tmp_path / "patch.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("files/NewLauncher.exe", b"new")
        manifest = {
            "formatVersion": 1,
            "platform": "windows",
            "baseVersion": "3.0.5",
            "targetVersion": "3.0.6",
            "files": [{
                "path": "NewLauncher.exe",
                "sha256": hashlib.sha256(b"new").hexdigest(),
            }],
            "delete": ["legacy.dll"],
        }
        manifest["signature"] = base64.b64encode(
            TEST_SIGNING_KEY.sign(canonical_manifest_bytes(manifest))
        ).decode("ascii")
        archive.writestr("manifest.json", json.dumps(manifest))

    import nlc.update_engine as updater
    original_replace = updater.os.replace

    def fail_replace(source, destination):
        raise OSError("simulated replacement failure")

    updater.os.replace = fail_replace
    try:
        with pytest.raises(OSError):
            apply_patch(package, target)
    finally:
        updater.os.replace = original_replace

    assert (target / "legacy.dll").read_bytes() == b"keep"


def test_apply_patch_rejects_tampered_signature(tmp_path):
    target = tmp_path / "install"
    target.mkdir()
    package = tmp_path / "patch.zip"
    make_patch(package, {"NewLauncher.exe": b"new"})

    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(tampered, "w") as destination:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename == "manifest.json":
                manifest = json.loads(content)
                manifest["signature"] = base64.b64encode(b"invalid").decode("ascii")
                content = json.dumps(manifest).encode("utf-8")
            destination.writestr(entry, content)

    with pytest.raises(ValueError, match="signature"):
        apply_patch(tampered, target)
