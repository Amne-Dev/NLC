
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from nlc import update_keys


def _safe_relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not value or ".." in path.parts or path == Path("."):
        raise ValueError(f"Unsafe patch path: {value}")
    return path


def canonical_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    unsigned = dict(manifest)
    unsigned.pop("signature", None)
    return json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def verify_manifest_signature(manifest: dict[str, Any]) -> None:
    signature_text = manifest.get("signature")
    public_key_text = update_keys.PATCH_PUBLIC_KEY_B64
    if not isinstance(signature_text, str) or not signature_text:
        raise ValueError("Patch manifest is missing its signature.")
    if not public_key_text:
        raise ValueError("Patch signing public key is not configured.")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_text, validate=True))
        signature = base64.b64decode(signature_text, validate=True)
        public_key.verify(signature, canonical_manifest_bytes(manifest))
    except (ValueError, InvalidSignature) as exc:
        raise ValueError("Patch manifest signature verification failed.") from exc


def load_patch_manifest(package_path: str | Path) -> dict[str, Any]:
    with zipfile.ZipFile(package_path) as archive:
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (KeyError, json.JSONDecodeError) as exc:
            raise ValueError("Patch package has no valid manifest.") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("formatVersion") != 1
        or manifest.get("platform") not in ("windows", "linux", "darwin")
        or not isinstance(manifest.get("baseVersion"), str)
        or not manifest.get("baseVersion")
        or not isinstance(manifest.get("targetVersion"), str)
        or not manifest.get("targetVersion")
        or not isinstance(manifest.get("files"), list)
    ):
        raise ValueError("Patch manifest has an invalid file list.")
    return manifest


def apply_patch(package_path: str | Path, target_dir: str | Path) -> None:
    target = Path(target_dir).resolve()
    if not target.is_dir():
        raise FileNotFoundError(f"Install directory not found: {target}")

    manifest = load_patch_manifest(package_path)
    verify_manifest_signature(manifest)
    files = manifest["files"]
    deletes = manifest.get("delete", [])
    if not isinstance(deletes, list):
        raise ValueError("Patch manifest has an invalid delete list.")

    entries = []
    seen_paths = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("Patch manifest contains an invalid file entry.")
        relative = _safe_relative_path(str(entry.get("path", "")))
        if relative in seen_paths:
            raise ValueError(f"Patch manifest contains a duplicate file: {relative}")
        seen_paths.add(relative)
        checksum = entry.get("sha256")
        if not isinstance(checksum, str) or len(checksum) != 64:
            raise ValueError(f"Invalid checksum for {relative}")
        entries.append((relative, checksum.lower()))

    delete_paths = []
    for item in deletes:
        relative = _safe_relative_path(str(item))
        if relative in seen_paths:
            raise ValueError(f"Patch manifest updates and deletes the same file: {relative}")
        if relative in delete_paths:
            raise ValueError(f"Patch manifest contains a duplicate delete: {relative}")
        delete_paths.append(relative)

    staging = Path(tempfile.mkdtemp(prefix="nlc_patch_", dir=target.parent))
    backups = []
    replaced = []
    try:
        with zipfile.ZipFile(package_path) as archive:
            for relative, expected_hash in entries:
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with archive.open(f"files/{relative.as_posix()}") as source, destination.open("wb") as output:
                        shutil.copyfileobj(source, output)
                except KeyError as exc:
                    raise ValueError(f"Patch file is missing: {relative}") from exc
                digest = hashlib.sha256(destination.read_bytes()).hexdigest()
                if digest != expected_hash:
                    raise ValueError(f"Checksum mismatch for {relative}")

        backup_root = staging / ".backup"
        for relative, _ in entries:
            destination = target / relative
            if destination.exists():
                backup = backup_root / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup)
                backups.append((backup, destination))
        for relative in delete_paths:
            destination = target / relative
            if destination.is_file() or destination.is_symlink():
                backup = backup_root / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup, follow_symlinks=False)
                backups.append((backup, destination))

        for relative, _ in entries:
            source = staging / relative
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
            replaced.append(destination)
        for relative in delete_paths:
            destination = target / relative
            if destination.is_file() or destination.is_symlink():
                destination.unlink()
    except Exception:
        for destination in replaced:
            try:
                destination.unlink()
            except OSError:
                pass
        for backup, destination in backups:
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(backup, destination, follow_symlinks=False)
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
