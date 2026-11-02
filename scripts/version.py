# scripts/version.py - Centralized Version CLI for New-launcher (NLC)

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure nlc package is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
backend_nlc = REPO_ROOT / "src" / "backend"
if str(backend_nlc) not in sys.path:
    sys.path.insert(0, str(backend_nlc))

from nlc.version import (
    get_version,
    bump_semver,
    parse_semver,
    sync_all,
    check_all,
    find_repo_root,
)


def print_status_table(results: list[dict], current_v: str, new_v: str) -> None:
    print(f"\n[+] Version Synchronization Complete: v{current_v} -> v{new_v}\n")
    print(f"{'Target File':<45} | {'Status':<10} | {'Matches'}")
    print("-" * 68)
    for r in results:
        status = "UPDATED" if r["changed"] else "OK (in sync)"
        matches = r.get("matches", 0)
        print(f"{r['file']:<45} | {status:<10} | {matches}")
    print("-" * 68)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="NLC Unified Version Manager & Synchronizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Usage: python scripts/version.py [get|set|bump|check|sync]",
    )
    parser.add_argument(
        "action_or_version",
        nargs="?",
        default="sync",
        help="Target version string (e.g. '3.0.7'), or action: 'sync', 'bump', 'get', 'check', 'set'",
    )
    parser.add_argument(
        "target_arg",
        nargs="?",
        default=None,
        help="Optional argument for action (e.g. 'patch' for bump, or version string for set)",
    )
    parser.add_argument(
        "--no-cargo",
        action="store_true",
        help="Skip running cargo check on Cargo.lock",
    )

    args = parser.parse_args()
    root = find_repo_root()
    current_v = get_version(root)
    action = args.action_or_version.strip()

    # 1. Action: get
    if action == "get":
        print(current_v)
        return 0

    # 2. Action: check
    if action == "check":
        in_sync, mismatches = check_all(root)
        if in_sync:
            print(f"[+] All files are in sync with VERSION (v{current_v}).")
            return 0
        else:
            print(f"[-] Version drift detected! Expected v{current_v}:", file=sys.stderr)
            for m in mismatches:
                print(f"    - {m}", file=sys.stderr)
            print("\nRun 'python scripts/version.py' to automatically synchronize all files.", file=sys.stderr)
            return 1

    # 3. Action: bump [patch|minor|major]
    if action == "bump":
        part = (args.target_arg or "patch").lower().strip()
        try:
            new_v = bump_semver(current_v, part)
        except ValueError as err:
            print(f"[-] Error: {err}", file=sys.stderr)
            return 1

        print(f"[*] Bumping {part}: v{current_v} -> v{new_v}...")
        results = sync_all(new_v, root, update_cargo_lock=not args.no_cargo)
        print_status_table(results, current_v, new_v)
        return 0

    # 4. Action: set <version>
    if action == "set":
        new_v = (args.target_arg or "").strip().lstrip("v")
        if not new_v:
            print("[-] Error: 'set' requires a version argument, e.g.: python scripts/version.py set 3.0.7", file=sys.stderr)
            return 1
        try:
            parse_semver(new_v)
        except ValueError as err:
            print(f"[-] Error: {err}", file=sys.stderr)
            return 1

        print(f"[*] Setting project version: v{current_v} -> v{new_v}...")
        results = sync_all(new_v, root, update_cargo_lock=not args.no_cargo)
        print_status_table(results, current_v, new_v)
        return 0

    # 5. Action: sync (no arguments or explicit 'sync')
    if action == "sync":
        print(f"[*] Synchronizing all project files to match VERSION (v{current_v})...")
        results = sync_all(current_v, root, update_cargo_lock=not args.no_cargo)
        print_status_table(results, current_v, current_v)
        return 0

    # 6. Direct version string (e.g. 'python scripts/version.py 3.0.7')
    try:
        parse_semver(action)
        new_v = action.lstrip("v")
        print(f"[*] Setting project version: v{current_v} -> v{new_v}...")
        results = sync_all(new_v, root, update_cargo_lock=not args.no_cargo)
        print_status_table(results, current_v, new_v)
        return 0
    except ValueError:
        print(f"[-] Unrecognized command or invalid version: '{action}'", file=sys.stderr)
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())

