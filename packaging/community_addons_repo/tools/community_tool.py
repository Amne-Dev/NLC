#!/usr/bin/env python3
"""
Developer & Contributor CLI Tool for New-launcher Community Addons Registry.

Commands:
  check-id <id>          Check if an addon ID is available or taken.
  suggest-id             Auto-generate a collision-free ID from name and author.
  register               Interactive or flag-based registration wizard with security scan.
  verify-all             Validate all entries in addons.json for compliance.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

# Ensure tools package can import security_scanner
tools_dir = Path(__file__).resolve().parent
if str(tools_dir) not in sys.path:
    sys.path.insert(0, str(tools_dir))

import security_scanner as sec  # type: ignore


def get_repo_root() -> Path:
    """Finds the repository root containing addons.json."""
    curr = Path(__file__).resolve().parent
    while curr != curr.parent:
        if (curr / "addons.json").is_file():
            return curr
        curr = curr.parent
    return Path.cwd()


def load_catalog(repo_root: Path) -> Tuple[List[Dict[str, Any]], Set[str]]:
    """Loads addons.json and returns (items, existing_id_set)."""
    manifest_path = repo_root / "addons.json"
    if not manifest_path.is_file():
        return [], set()

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("addons.json root must be a JSON array")

    ids = {str(item.get("id")) for item in data if isinstance(item, dict) and "id" in item}
    return data, ids


def save_catalog(repo_root: Path, items: List[Dict[str, Any]]) -> None:
    """Saves updated catalog to addons.json with standard 2-space indentation."""
    manifest_path = repo_root / "addons.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ==============================================================================
# Subcommand Handlers
# ==============================================================================

def cmd_check_id(args: argparse.Namespace) -> int:
    repo_root = get_repo_root()
    catalog, ids = load_catalog(repo_root)
    candidate = sec.slugify_id(args.id)

    if not candidate:
        print(f"[-] Error: '{args.id}' is not a valid identifier.")
        return 1

    if candidate in ids:
        # Find who owns it
        owner = next((item for item in catalog if item.get("id") == candidate), {})
        print(f"[!] ID '{candidate}' is ALREADY TAKEN by '{owner.get('name', 'Unknown')}' (Author: {owner.get('author', 'Unknown')}).")
        
        # Suggest available alternatives
        author = owner.get("author", "user")
        sug1 = sec.generate_unique_id(candidate, f"my_{author}", ids)
        sug2 = sec.generate_unique_id(f"{candidate}_addon", author, ids)
        print(f"[+] Suggested available IDs:")
        print(f"    - {sug1}")
        print(f"    - {sug2}")
        return 1
    else:
        print(f"[+] SUCCESS: ID '{candidate}' is AVAILABLE!")
        return 0


def cmd_suggest_id(args: argparse.Namespace) -> int:
    repo_root = get_repo_root()
    _, ids = load_catalog(repo_root)

    sug = sec.generate_unique_id(args.name, args.author, ids, preferred_id=args.preferred)
    print(f"[+] Generated unique ID: {sug}")
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    repo_root = get_repo_root()
    catalog, ids = load_catalog(repo_root)

    print("==================================================================")
    print("      New-launcher Community Addon Registration Wizard            ")
    print("==================================================================")

    # 1. Gather Metadata (interactive if not provided via flags)
    name = (args.name or input("1. Addon Display Name (e.g. 'Custom Crosshair'): ")).strip()
    author = (args.author or input("2. Author / Creator (e.g. 'SteveDev'): ")).strip()
    
    # Auto-suggest ID
    suggested_id = sec.generate_unique_id(name, author, ids, preferred_id=args.id)
    if args.id:
        chosen_id = sec.slugify_id(args.id)
        if chosen_id in ids:
            print(f"[!] Preferred ID '{chosen_id}' is taken. Falling back to '{suggested_id}'.")
            chosen_id = suggested_id
    elif args.non_interactive:
        chosen_id = suggested_id
    else:
        prompt_id = input(f"3. Addon ID (Press Enter for suggested '{suggested_id}'): ").strip()
        chosen_id = sec.slugify_id(prompt_id) if prompt_id else suggested_id

    version = (args.version or input("4. Version (e.g. '1.0.0'): ")).strip() or "1.0.0"
    desc = (args.description or input("5. Description (10-400 chars): ")).strip()
    url = (args.download_url or input("6. Download URL (Direct HTTPS link to .zip): ")).strip()
    icon = (args.icon_url or input("7. Icon URL (Optional square PNG, press Enter to skip): ")).strip()
    tags_input = (args.tags or input("8. Tags (comma-separated, e.g. 'HUD, Visual'): ")).strip()
    tags = [t.strip() for t in tags_input.split(",") if t.strip()]

    item: Dict[str, Any] = {
        "id": chosen_id,
        "name": name,
        "version": version,
        "author": author,
        "description": desc,
        "download_url": url,
        "action_label": "Install",
        "tags": tags,
    }
    if icon:
        item["icon_url"] = icon

    # 2. Content Moderation
    print("\n[*] Performing content moderation scan...")
    content_errors = sec.verify_content_safety(item)
    if content_errors:
        print("[-] Content safety verification FAILED:")
        for err in content_errors:
            print(f"    - {err}")
        return 1
    print("[+] Metadata content is clean and safe.")

    # 3. URL & Archive Verification
    print("[*] Verifying download URL and archive security...")
    url_errors = sec.verify_download_url(url)
    if url_errors:
        print("[-] Download URL verification FAILED:")
        for err in url_errors:
            print(f"    - {err}")
        return 1

    if not args.skip_download_scan:
        try:
            print(f"[*] Downloading release archive from {url}...")
            archive_bytes, sha256_hash = sec.download_addon_archive(url)
            print(f"[+] Downloaded {len(archive_bytes)} bytes. SHA-256: {sha256_hash}")
            item["sha256"] = sha256_hash

            print("[*] Inspecting archive contents for malware, zip-slip, and executables...")
            is_safe, archive_errors, manifest_data = sec.verify_archive_safety(archive_bytes, expected_id=chosen_id)
            if not is_safe:
                print("[-] Archive security verification FAILED:")
                for err in archive_errors:
                    print(f"    - {err}")
                return 1
            print("[+] Archive inspection PASSED! Zero malicious patterns or forbidden binaries.")
        except Exception as exc:
            print(f"[-] Could not complete security scan on download: {exc}")
            if not args.force:
                print("    (Use --force to register anyway if repository is offline/local)")
                return 1

    # 4. Save to addons.json
    catalog.append(item)
    save_catalog(repo_root, catalog)
    print(f"\n[+] SUCCESS! Addon '{name}' (ID: {chosen_id}) registered in addons.json!")
    print("\nNext Steps:")
    print("  1. git checkout -b add-" + chosen_id)
    print("  2. git commit -am \"Add community addon: " + name + "\"")
    print("  3. git push origin add-" + chosen_id)
    print("  4. Open a Pull Request on https://github.com/Amne-Dev/Community-addons-nlc/pulls")
    return 0


def cmd_verify_all(args: argparse.Namespace) -> int:
    repo_root = get_repo_root()
    catalog, ids = load_catalog(repo_root)

    print(f"[*] Auditing {len(catalog)} addon(s) in {repo_root / 'addons.json'}...")
    seen_ids: Set[str] = set()
    total_errors = 0

    for idx, item in enumerate(catalog):
        addon_id = item.get("id", f"<index {idx}>")
        print(f" -> Checking [{idx+1}/{len(catalog)}] {addon_id} ('{item.get('name', 'Unnamed')}')")

        # Uniqueness
        if addon_id in seen_ids:
            print(f"    [-] Duplicate ID: {addon_id}")
            total_errors += 1
        seen_ids.add(addon_id)

        # Content Safety
        errors = sec.verify_content_safety(item)
        url_errors = sec.verify_download_url(item.get("download_url", ""))
        errors.extend(url_errors)

        if errors:
            total_errors += len(errors)
            for err in errors:
                print(f"    [-] {err}")
        else:
            print("    [+] OK")

    if total_errors == 0:
        print(f"\n[+] SUCCESS: All {len(catalog)} addons passed validation!")
        return 0
    else:
        print(f"\n[-] FAILED: Found {total_errors} validation issue(s).")
        return 1


# ==============================================================================
# CLI Entrypoint
# ==============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Community Addons Registry Developer CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Subcommand: check-id
    p_check = subparsers.add_parser("check-id", help="Check if an addon ID is available")
    p_check.add_argument("id", help="Candidate addon ID to check (e.g. 'custom_crosshair')")
    p_check.set_defaults(func=cmd_check_id)

    # Subcommand: suggest-id
    p_sug = subparsers.add_parser("suggest-id", help="Suggest an available unique ID from name and author")
    p_sug.add_argument("--name", required=True, help="Display name of the addon")
    p_sug.add_argument("--author", default="", help="Author name")
    p_sug.add_argument("--preferred", default="", help="Preferred candidate ID")
    p_sug.set_defaults(func=cmd_suggest_id)

    # Subcommand: register
    p_reg = subparsers.add_parser("register", help="Register a new addon in addons.json with security verification")
    p_reg.add_argument("--name", help="Display name")
    p_reg.add_argument("--author", help="Author")
    p_reg.add_argument("--id", help="Preferred ID")
    p_reg.add_argument("--version", help="Version string")
    p_reg.add_argument("--description", help="Description")
    p_reg.add_argument("--download-url", help="Direct HTTPS release .zip URL")
    p_reg.add_argument("--icon-url", help="Square PNG icon URL")
    p_reg.add_argument("--tags", help="Comma-separated tags")
    p_reg.add_argument("--skip-download-scan", action="store_true", help="Skip remote download security scan")
    p_reg.add_argument("--force", action="store_true", help="Force registration even if remote download fails")
    p_reg.add_argument("--non-interactive", action="store_true", help="Do not prompt interactively")
    p_reg.set_defaults(func=cmd_register)

    # Subcommand: verify-all
    p_ver = subparsers.add_parser("verify-all", help="Verify all catalog entries")
    p_ver.set_defaults(func=cmd_verify_all)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

