# Release Automation Script: Generates FastCDC recipes (.cdc.json) and release manifest

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict

# Ensure nlc package is importable
repo_root = Path(__file__).resolve().parent.parent
backend_dir = repo_root / "src" / "backend"
for p in (str(repo_root), str(backend_dir)):
    if p not in sys.path:
        sys.path.insert(0, p)

from nlc.version import get_version
from nlc.cdc_engine import build_cdc_index, sign_cdc_index


# Default wallpapers included for offline installation (Option A)
DEFAULT_WALLPAPERS = {
    "13uv5py3dw9f1.png",
    "8w0iispqcw9f1.png",
    "gqv4762zcw9f1.png",
    "Island.png",
    "background.png",
}


def package_assets_archive(repo_root_dir: Path, dist_dir: Path, base_url: str) -> Dict[str, Any]:
    print("[*] Packaging web installer assets bundle (Option A: core UI + thumbnails + default wallpapers)...")
    dist_dir.mkdir(parents=True, exist_ok=True)
    out_zip = dist_dir / "assets.zip"

    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # 1. assets/
        assets_dir = repo_root_dir / "assets"
        if assets_dir.is_dir():
            for p in sorted(assets_dir.rglob("*")):
                if p.is_file() and not p.name.startswith(".") and p.name.lower() not in ("thumbs.db", "desktop.ini"):
                    arcname = p.relative_to(repo_root_dir).as_posix()
                    zf.write(p, arcname)

        # 2. icons/
        icons_dir = repo_root_dir / "icons"
        if icons_dir.is_dir():
            for p in sorted(icons_dir.rglob("*")):
                if p.is_file() and not p.name.startswith(".") and p.name.lower() not in ("thumbs.db", "desktop.ini"):
                    arcname = p.relative_to(repo_root_dir).as_posix()
                    zf.write(p, arcname)

        # 3. skins/
        skins_dir = repo_root_dir / "skins"
        if skins_dir.is_dir():
            for p in sorted(skins_dir.rglob("*")):
                if p.is_file() and not p.name.startswith(".") and p.name.lower() not in ("thumbs.db", "desktop.ini"):
                    arcname = p.relative_to(repo_root_dir).as_posix()
                    zf.write(p, arcname)

        # 4. wallpapers/thumbnails/
        thumbs_dir = repo_root_dir / "wallpapers" / "thumbnails"
        if thumbs_dir.is_dir():
            for p in sorted(thumbs_dir.rglob("*")):
                if p.is_file() and not p.name.startswith(".") and p.name.lower() not in ("thumbs.db", "desktop.ini"):
                    arcname = p.relative_to(repo_root_dir).as_posix()
                    zf.write(p, arcname)

        # 5. wallpapers/ default images
        wp_dir = repo_root_dir / "wallpapers"
        if wp_dir.is_dir():
            for wp_name in sorted(DEFAULT_WALLPAPERS):
                wp_file = wp_dir / wp_name
                if wp_file.is_file():
                    arcname = wp_file.relative_to(repo_root_dir).as_posix()
                    zf.write(wp_file, arcname)

    size = out_zip.stat().st_size
    sha256 = hashlib.sha256(out_zip.read_bytes()).hexdigest()
    mb = size / (1024 * 1024)
    print(f"    [+] Created: {out_zip.name} ({mb:.2f} MB, sha256: {sha256[:16]}...)")

    return {
        "name": "assets.zip",
        "size": size,
        "sha256": sha256,
        "download_url": f"{base_url}/assets.zip",
    }


def generate_cdc_for_file(file_path: Path, version: str, private_key_b64: str = "") -> Dict[str, Any]:
    print(f"[*] Slicing {file_path.name} with FastCDC...")
    idx = build_cdc_index(file_path, version)
    
    runner_path = file_path.parent / "NLCUpdater.exe"
    if runner_path.is_file():
        idx["runner"] = "NLCUpdater.exe"
        idx["runnerSha256"] = hashlib.sha256(runner_path.read_bytes()).hexdigest()

    if private_key_b64:
        try:
            sign_cdc_index(idx, private_key_b64)
            print(f"    [+] Signed: {file_path.name}.cdc.json with Ed25519")
        except Exception as exc:
            print(f"    [!] Warning signing {file_path.name}.cdc.json: {exc}", file=sys.stderr)

    out_path = file_path.with_suffix(file_path.suffix + ".cdc.json")
    out_path.write_text(json.dumps(idx, indent=2), encoding="utf-8")
    print(f"    [+] Created: {out_path.name} ({idx['chunkCount']} chunks, target size: {idx['targetSize']} bytes)")
    return idx


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate FastCDC release recipes and manifest")
    parser.add_argument("--dir", default="dist", help="Directory containing release binaries")
    parser.add_argument("--version", default=get_version(), help="Release version tag (e.g. 4.0.0)")
    parser.add_argument("--repo", default="Amne-Dev/NLC", help="GitHub repo (owner/name)")
    parser.add_argument("--key", default="", help="Base64 Ed25519 private key for signing")
    args = parser.parse_args()

    dist_dir = Path(args.dir).resolve()
    if not dist_dir.is_dir():
        print(f"[-] Release directory not found: {dist_dir}", file=sys.stderr)
        return 1

    private_key_text = (
        args.key or os.environ.get("NLC_UPDATE_SIGNING_PRIVATE_KEY_B64", "")
    ).strip()

    binaries = ["NyLuna.exe", "agent.exe"]
    if (dist_dir / "libunwind.dll").is_file():
        binaries.append("libunwind.dll")
    release_manifest: Dict[str, Any] = {
        "version": args.version,
        "repo": args.repo,
        "files": {},
    }

    base_url = f"https://github.com/{args.repo}/releases/download/v{args.version}"

    found = 0
    for b_name in binaries:
        p = dist_dir / b_name
        if p.is_file():
            found += 1
            idx = generate_cdc_for_file(p, args.version, private_key_b64=private_key_text)
            release_manifest["files"][b_name] = {
                "size": idx["targetSize"],
                "sha256": idx["targetSha256"],
                "download_url": f"{base_url}/{b_name}",
                "cdc_url": f"{base_url}/{b_name}.cdc.json",
                "chunk_count": idx["chunkCount"],
            }
        else:
            print(f"[!] Warning: {b_name} not found in {dist_dir}")

    if found == 0:
        print("[-] No target binaries found to slice.", file=sys.stderr)
        return 1

    try:
        assets_entry = package_assets_archive(repo_root, dist_dir, base_url)
        release_manifest["assets"] = assets_entry
    except Exception as exc:
        print(f"[!] Warning packaging assets archive: {exc}", file=sys.stderr)

    manifest_path = dist_dir / "release_manifest.json"
    manifest_path.write_text(json.dumps(release_manifest, indent=2), encoding="utf-8")
    print(f"\n[+] SUCCESS: Generated release manifest at {manifest_path}!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
