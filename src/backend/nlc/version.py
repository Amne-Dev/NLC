
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

FALLBACK_VERSION = "4.0.3"


def find_repo_root() -> Path:
    curr = Path(__file__).resolve().parent
    for p in [curr, curr.parent, curr.parent.parent]:
        if (p / "VERSION").is_file() or (p / ".git").is_dir() or (p / "src" / "frontend").is_dir():
            return p
    cwd = Path.cwd().resolve()
    for p in [cwd, *cwd.parents]:
        if (p / "VERSION").is_file() or (p / ".git").is_dir():
            return p
    return cwd


def get_version(repo_root: Optional[Path] = None) -> str:
    root = repo_root or find_repo_root()
    v_file = root / "VERSION"
    if v_file.is_file():
        try:
            v_text = v_file.read_text(encoding="utf-8").strip()
            if v_text:
                return v_text
        except Exception:
            pass
    return FALLBACK_VERSION


def parse_semver(v: str) -> Tuple[int, int, int, str]:
    clean_v = v.strip().lstrip("v")
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$", clean_v)
    if not m:
        raise ValueError(f"Invalid SemVer version string: '{v}'. Expected format 'X.Y.Z' or 'X.Y.Z-prerelease'.")
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    prerelease = m.group(4) or ""
    return major, minor, patch, prerelease


def bump_semver(current: str, part: str = "patch") -> str:
    major, minor, patch, _ = parse_semver(current)
    part_clean = part.lower().strip()
    if part_clean == "patch":
        patch += 1
    elif part_clean == "minor":
        minor += 1
        patch = 0
    elif part_clean == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        raise ValueError(f"Unknown bump target: '{part}'. Choose from 'patch', 'minor', or 'major'.")
    return f"{major}.{minor}.{patch}"


# Managed Target Files Configuration

def get_managed_file_rules(v: str) -> List[Dict[str, Any]]:
    return [
        {
            "path": "src/frontend/Cargo.toml",
            "patterns": [
                (r'(?m)(^\[package\][\s\S]*?^version\s*=\s*)"[^"]+"', rf'\g<1>"{v}"'),
            ],
        },
        {
            "path": "packaging/windows/installer_app.py",
            "patterns": [
                (r'APP_VERSION\s*=\s*"[^"]+"', f'APP_VERSION = "{v}"'),
            ],
        },
        {
            "path": "packaging/windows/config_healer.py",
            "patterns": [
                (r'CURRENT_VERSION\s*=\s*"[^"]+"', f'CURRENT_VERSION = "{v}"'),
            ],
        },
        {
            "path": "packaging/linux/build_appimage.sh",
            "patterns": [
                (r'APP_VERSION="\$\(cat VERSION 2>/dev/null \|\| echo "[^"]+"\)"', f'APP_VERSION="$(cat VERSION 2>/dev/null || echo "{v}")"'),
            ],
        },
        {
            "path": "packaging/linux/.SRCINFO",
            "patterns": [
                (r'(\tpkgver\s*=\s*)[\d\w\.\-]+', rf'\g<1>{v}'),
                (r'(source\s*=\s*https://github\.com/Amne-Dev/NLC/archive/refs/tags/v)[\d\w\.\-]+(\.tar\.gz)', rf'\g<1>{v}\g<2>'),
            ],
        },
        {
            "path": "src/frontend/ui/splash.slint",
            "patterns": [
                (r'text:\s*"NLC v[^"•]+ • @Amne-Dev";', f'text: "NLC v{v} • @Amne-Dev";'),
            ],
        },
        {
            "path": "src/frontend/ui/screens/settings.slint",
            "patterns": [
                (r'title:\s*"Launcher Version:\s*[^"]+";', f'title: "Launcher Version: {v}";'),
                (r'text:\s*"Version:\s*[^"•]+ • Python/Tkinter Native & Rust Frontend', f'text: "Version: {v} • Python/Tkinter Native & Rust Frontend'),
            ],
        },
    ]


# Synchronization & Integrity Check Operations

def sync_all(
    target_version: Optional[str] = None,
    repo_root: Optional[Path] = None,
    update_cargo_lock: bool = True
) -> List[Dict[str, Any]]:
    root = repo_root or find_repo_root()
    v = (target_version or get_version(root)).strip().lstrip("v")
    parse_semver(v)

    results: List[Dict[str, Any]] = []

    # 1. Update canonical root VERSION file
    v_file = root / "VERSION"
    v_orig = v_file.read_text(encoding="utf-8").strip() if v_file.is_file() else ""
    v_changed = (v_orig != v)
    if v_changed or not v_file.is_file():
        v_file.parent.mkdir(parents=True, exist_ok=True)
        v_file.write_text(f"{v}\n", encoding="utf-8")
    results.append({"file": "VERSION", "changed": v_changed, "matches": 1})

    # 2. Update all managed static target files
    rules = get_managed_file_rules(v)
    cargo_updated = False

    for rule in rules:
        rel_p = rule["path"]
        f_path = root / rel_p
        if not f_path.is_file():
            continue

        try:
            content = f_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = f_path.read_text(encoding="utf-8-sig")

        original = content
        matches_total = 0

        for pattern, replacement in rule["patterns"]:
            new_content, count = re.subn(pattern, replacement, content)
            matches_total += count
            content = new_content

        changed = (content != original)
        if changed:
            f_path.write_text(content, encoding="utf-8")
            if "Cargo.toml" in rel_p:
                cargo_updated = True

        results.append({
            "file": rel_p,
            "changed": changed,
            "matches": matches_total,
        })

    # 3. Update Cargo.lock if Cargo.toml changed and cargo CLI is installed
    if cargo_updated and update_cargo_lock:
        try:
            cargo_bin = shutil.which("cargo")
            cargo_toml = root / "src" / "frontend" / "Cargo.toml"
            if cargo_bin and cargo_toml.is_file():
                subprocess.run(
                    [cargo_bin, "check", "--manifest-path", str(cargo_toml)],
                    cwd=str(root),
                    check=False,
                    capture_output=True,
                    timeout=60,
                )
        except Exception:
            pass

    return results


def check_all(repo_root: Optional[Path] = None) -> Tuple[bool, List[str]]:
    root = repo_root or find_repo_root()
    v = get_version(root).strip().lstrip("v")
    mismatches: List[str] = []

    # 1. Check VERSION file
    v_file = root / "VERSION"
    if not v_file.is_file():
        mismatches.append("Missing file: VERSION")
    elif v_file.read_text(encoding="utf-8").strip() != v:
        mismatches.append(f"Out of sync: VERSION (has '{v_file.read_text(encoding='utf-8').strip()}', expected '{v}')")

    # 2. Check static managed files
    rules = get_managed_file_rules(v)
    for rule in rules:
        rel_p = rule["path"]
        f_path = root / rel_p
        if not f_path.is_file():
            continue

        try:
            content = f_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = f_path.read_text(encoding="utf-8-sig")

        for pattern, replacement in rule["patterns"]:
            new_content, count = re.subn(pattern, replacement, content)
            if new_content != content:
                mismatches.append(f"Out of sync: {rel_p}")
                break

    return (len(mismatches) == 0, mismatches)
