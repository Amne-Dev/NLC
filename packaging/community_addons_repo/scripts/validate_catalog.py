#!/usr/bin/env python3
"""
Catalog Validator script for Amne-Dev/Community-addons-nlc.
Used in GitHub Actions CI and local pre-commit checks.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

# Add tools directory to path
repo_root = Path(__file__).resolve().parent.parent
tools_dir = repo_root / "tools"
if str(tools_dir) not in sys.path:
    sys.path.insert(0, str(tools_dir))

import security_scanner as sec  # type: ignore


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate addons.json catalog integrity and security")
    parser.add_argument(
        "--file",
        default=str(repo_root / "addons.json"),
        help="Path to addons.json catalog"
    )
    parser.add_argument(
        "--deep-scan",
        action="store_true",
        help="Download and inspect all addon archives for malware, zip-slip, and executables"
    )
    args = parser.parse_args()

    manifest_path = Path(args.file)
    if not manifest_path.is_file():
        print(f"[-] Catalog file not found: {manifest_path}", file=sys.stderr)
        return 1

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)
    except Exception as exc:
        print(f"[-] Invalid JSON in {manifest_path}: {exc}", file=sys.stderr)
        return 1

    if not isinstance(catalog, list):
        print("[-] addons.json root must be a JSON array", file=sys.stderr)
        return 1

    print(f"[*] Validating {len(catalog)} addon(s) in {manifest_path.name}...")

    seen_ids: Set[str] = set()
    errors: List[str] = []

    for index, item in enumerate(catalog):
        if not isinstance(item, dict):
            errors.append(f"Item #{index} is not a JSON object")
            continue

        addon_id = str(item.get("id", "")).strip()
        name = str(item.get("name", "")).strip()

        # Required fields check
        for required_field in ("id", "name", "version", "author", "description", "download_url"):
            if not item.get(required_field):
                errors.append(f"Addon #{index} ('{name or addon_id}') missing required field '{required_field}'")

        # Uniqueness
        if addon_id:
            if addon_id in seen_ids:
                errors.append(f"Duplicate addon ID found: '{addon_id}'")
            seen_ids.add(addon_id)

        # Content Safety (profanity, scam terms, HTML injection)
        content_errs = sec.verify_content_safety(item)
        for ce in content_errs:
            errors.append(f"[{addon_id or index}] Content error: {ce}")

        # URL Safety
        download_url = item.get("download_url", "")
        url_errs = sec.verify_download_url(download_url)
        for ue in url_errs:
            errors.append(f"[{addon_id or index}] URL error: {ue}")

        # Optional Deep Scan
        if args.deep_scan and download_url and not url_errs:
            print(f"[*] Deep scanning '{addon_id}' ({download_url})...")
            try:
                raw_bytes, sha256_hash = sec.download_addon_archive(download_url)
                is_safe, archive_errs, _ = sec.verify_archive_safety(raw_bytes, expected_id=addon_id)
                if not is_safe:
                    for ae in archive_errs:
                        errors.append(f"[{addon_id}] Security scan failure: {ae}")
                else:
                    print(f"[+] '{addon_id}' archive clean (SHA-256: {sha256_hash})")
            except Exception as exc:
                errors.append(f"[{addon_id}] Deep scan download error: {exc}")

    if errors:
        print(f"\n[-] FAILED with {len(errors)} error(s):", file=sys.stderr)
        for err in errors:
            print(f"    - {err}", file=sys.stderr)
        return 1

    print(f"\n[+] SUCCESS: Catalog validated successfully! All {len(catalog)} addon(s) comply with security policies.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

