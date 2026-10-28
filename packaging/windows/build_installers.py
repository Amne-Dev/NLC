#!/usr/bin/env python3
"""
Build Orchestrator for New-launcher Windows Installers:
1. Builds Rust frontend (nlc-ui.exe -> dist/NyLuna.exe)
2. Builds Python backend daemon (agent.spec -> dist/agent.exe)
3. Generates FastCDC recipes (.cdc.json) for minimal updates
4. Builds NLCSetup.exe (Web Installer & FastCDC Update Gateway)
5. Builds NLCSetup-Offline.exe (Standalone Offline Installer)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = REPO_ROOT / "src" / "backend"
for p in (str(REPO_ROOT), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from nlc.version import get_version


def run_cmd(cmd: list[str], cwd: Path, desc: str) -> None:
    print(f"\n[*] {desc}...")
    print(f"    Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(cwd))
    if result.returncode != 0:
        print(f"[-] FAILED: {desc} exited with code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)
    print(f"[+] Completed: {desc}")


def find_signtool() -> Path | None:
    """Detects signtool.exe via SIGNTOOL_PATH, system PATH, or Windows Kits SDK directories."""
    custom_path = os.environ.get("SIGNTOOL_PATH")
    if custom_path:
        p = Path(custom_path)
        if p.is_file():
            return p.resolve()
        if (p / "signtool.exe").is_file():
            return (p / "signtool.exe").resolve()
        print(f"[!] Warning: SIGNTOOL_PATH '{custom_path}' does not point to a valid signtool binary. Falling back to search...", file=sys.stderr)
        # Fall through to search system PATH and Windows Kits SDK directories

    which_path = shutil.which("signtool.exe") or shutil.which("signtool")
    if which_path:
        return Path(which_path)

    for prog_env in ["ProgramFiles(x86)", "ProgramFiles"]:
        base = os.environ.get(prog_env)
        if not base:
            continue
        kits_dir = Path(base) / "Windows Kits" / "10" / "bin"
        if kits_dir.is_dir():
            for match in sorted(kits_dir.glob("*/x64/signtool.exe"), reverse=True):
                if match.is_file():
                    return match

    for static_dir in [r"C:\Program Files (x86)\Windows Kits\10\bin", r"C:\Program Files\Windows Kits\10\bin"]:
        kits_dir = Path(static_dir)
        if kits_dir.is_dir():
            for match in sorted(kits_dir.glob("*/x64/signtool.exe"), reverse=True):
                if match.is_file():
                    return match

    return None


def get_signing_config(
    cert_file: str | None = None,
    cert_pass: str | None = None,
    cert_sha1: str | None = None,
) -> dict[str, str] | None:
    """Evaluates certificate configuration from CLI args or environment variables."""
    file = cert_file or os.environ.get("SIGN_CERT_FILE") or os.environ.get("SIGN_CERT_PATH") or ""
    sha1 = cert_sha1 or os.environ.get("SIGN_CERT_SHA1") or os.environ.get("SIGN_CERT_THUMBPRINT") or ""
    if not file and not sha1:
        return None

    password = cert_pass or os.environ.get("SIGN_CERT_PASSWORD") or os.environ.get("SIGN_CERT_PASS") or ""
    store = os.environ.get("SIGN_CERT_STORE", "My")
    store_loc = os.environ.get("SIGN_CERT_STORE_LOCATION", "User")
    ts_url = os.environ.get("SIGN_TIMESTAMP_URL", "http://timestamp.digicert.com")
    app_name = os.environ.get("SIGN_APP_NAME", "Ny-Luna Core")

    return {
        "cert_file": file,
        "cert_password": password,
        "cert_sha1": sha1,
        "cert_store": store,
        "store_location": store_loc,
        "timestamp_url": ts_url,
        "app_name": app_name,
    }


def build_signtool_command(
    signtool: Path,
    target_path: Path,
    config: dict[str, str],
    description: str = "Ny-Luna Core",
) -> list[str]:
    """Builds signtool sign command-line arguments list."""
    cmd = [
        str(signtool),
        "sign",
        "/fd",
        "SHA256",
    ]

    if config.get("cert_file"):
        cmd.extend(["/f", config["cert_file"]])
        if config.get("cert_password"):
            cmd.extend(["/p", config["cert_password"]])
    elif config.get("cert_sha1"):
        cmd.extend(["/sha1", config["cert_sha1"], "/s", config.get("cert_store", "My")])
        if config.get("store_location", "").lower() == "machine":
            cmd.append("/sm")

    if config.get("timestamp_url"):
        cmd.extend(["/tr", config["timestamp_url"], "/td", "SHA256"])

    desc = description or config.get("app_name", "")
    if desc:
        cmd.extend(["/d", desc])

    cmd.append(str(target_path))
    return cmd


def sign_binary(
    file_path: Path,
    description: str = "Ny-Luna Core",
    strict: bool = False,
    dry_run: bool = False,
    cert_file: str | None = None,
    cert_pass: str | None = None,
    cert_sha1: str | None = None,
) -> bool:
    """Signs a Windows PE binary using signtool.exe with graceful fallback."""
    target_path = Path(file_path).resolve()
    is_strict = strict or os.environ.get("SIGN_STRICT") == "1"

    if not target_path.is_file():
        raise FileNotFoundError(f"Target file for signing does not exist: {target_path}")

    signtool = find_signtool()
    cfg = get_signing_config(cert_file=cert_file, cert_pass=cert_pass, cert_sha1=cert_sha1)

    if not signtool or not cfg:
        if is_strict:
            raise RuntimeError("Code signing failed: signtool or certificate missing in strict mode")

        print(
            f"[!] Code signing skipped: signtool.exe or certificate not configured. "
            f"Set SIGN_CERT_FILE or SIGN_CERT_SHA1. Continuing build..."
        )
        return False

    cmd = build_signtool_command(signtool, target_path, cfg, description=description)

    print(f"\n[*] Authenticode signing: {target_path.name}...")
    if dry_run or os.environ.get("SIGN_DRY_RUN") == "1":
        print(f"    [DRY RUN] Would run: {' '.join(cmd)}")
        return True

    res = subprocess.run(cmd)
    if res.returncode != 0:
        if is_strict:
            raise RuntimeError(f"Code signing failed: signtool exited with code {res.returncode}")
        print(f"[!] Code signing failed for {target_path.name} with exit code {res.returncode}. Continuing unsigned...")
        return False

    print(f"[+] Successfully signed: {target_path.name}")
    return True


def find_libunwind() -> Path | None:
    """Finds libunwind.dll from PATH or toolchain directories."""
    for p in os.environ.get("PATH", "").split(os.path.pathsep):
        candidate = Path(p) / "libunwind.dll"
        if candidate.is_file():
            return candidate
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        winget_pkgs = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        for match in winget_pkgs.glob("**/llvm-mingw*/bin/libunwind.dll"):
            if match.is_file():
                return match
    return None


def build_rust_frontend(release: bool = True) -> Path:
    target_mode = ["--release"] if release else []
    cargo_cmd = ["cargo", "build"] + target_mode + ["--manifest-path", "src/frontend/Cargo.toml"]
    run_cmd(cargo_cmd, REPO_ROOT, "Compiling Rust Slint UI Frontend")
    
    subfolder = "release" if release else "debug"
    candidates = [
        REPO_ROOT / "src" / "frontend" / "target" / "x86_64-pc-windows-gnullvm" / subfolder / "nlc-ui.exe",
        REPO_ROOT / "src" / "frontend" / "target" / subfolder / "nlc-ui.exe",
    ]
    src_exe = next((c for c in candidates if c.is_file()), None)
    if not src_exe or not src_exe.is_file():
        raise FileNotFoundError(f"Expected compiled binary not found at {src_exe}")

    dist_dir = REPO_ROOT / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    dst_exe = dist_dir / "NyLuna.exe"
    shutil.copy2(src_exe, dst_exe)

    print(f"[+] Placed frontend binary at: {dst_exe}")

    # Ensure libunwind.dll is bundled alongside NyLuna.exe
    unwind_dll = find_libunwind()
    if unwind_dll:
        dst_unwind = dist_dir / "libunwind.dll"
        shutil.copy2(unwind_dll, dst_unwind)
        print(f"[+] Placed runtime dependency at: {dst_unwind}")

    return dst_exe


def build_python_agent() -> Path:
    spec_path = str(REPO_ROOT / "src" / "backend" / "agent.spec")
    pyinstaller_cmd = ["pyinstaller", "--clean", "-y", spec_path]
    run_cmd(pyinstaller_cmd, REPO_ROOT, "Packaging Python Agent Daemon via PyInstaller")
    
    agent_exe = REPO_ROOT / "dist" / "agent.exe"
    if not agent_exe.is_file():
        raise FileNotFoundError(f"Expected agent binary not found at {agent_exe}")
    return agent_exe


def generate_cdc_indexes(version: str) -> None:
    gen_script = REPO_ROOT / "scripts" / "generate_release_cdc.py"
    if gen_script.is_file():
        cmd = [sys.executable, str(gen_script), "--dir", str(REPO_ROOT / "dist"), "--version", version]
        run_cmd(cmd, REPO_ROOT, "Generating FastCDC Differential Recipe Indexes (.cdc.json)")


def build_web_installer() -> Path:
    spec_path = REPO_ROOT / "packaging" / "windows" / "installer_web.spec"
    cmd = ["pyinstaller", "--clean", "-y", str(spec_path)]
    run_cmd(cmd, REPO_ROOT, "Building NLCSetup.exe (Web Installer & Update Gateway)")

    out_exe = REPO_ROOT / "dist" / "NLCSetup.exe"
    if not out_exe.is_file():
        raise FileNotFoundError(f"Expected installer not found at {out_exe}")
    
    installers_dir = REPO_ROOT / "dist" / "installers"
    installers_dir.mkdir(parents=True, exist_ok=True)
    final_path = installers_dir / "NLCSetup.exe"
    shutil.copy2(out_exe, final_path)
    print(f"[+] Output: {final_path}")
    return final_path


def build_offline_installer() -> Path:
    spec_path = REPO_ROOT / "packaging" / "windows" / "installer_offline.spec"
    cmd = ["pyinstaller", "--clean", "-y", str(spec_path)]
    run_cmd(cmd, REPO_ROOT, "Building NLCSetup-Offline.exe (Standalone Offline Installer)")

    out_exe = REPO_ROOT / "dist" / "NLCSetup-Offline.exe"
    if not out_exe.is_file():
        raise FileNotFoundError(f"Expected installer not found at {out_exe}")
    
    installers_dir = REPO_ROOT / "dist" / "installers"
    installers_dir.mkdir(parents=True, exist_ok=True)
    final_path = installers_dir / "NLCSetup-Offline.exe"
    shutil.copy2(out_exe, final_path)
    print(f"[+] Output: {final_path}")
    return final_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Ny-Luna Core Windows Installer Builder")
    parser.add_argument("--web", action="store_true", help="Build NLCSetup.exe (Web)")
    parser.add_argument("--offline", action="store_true", help="Build NLCSetup-Offline.exe (Offline)")
    parser.add_argument("--all", action="store_true", help="Build both Web and Offline installers")
    parser.add_argument("--version", default=get_version(), help="Release version string")
    parser.add_argument("--skip-compile", action="store_true", help="Skip cargo and agent build")
    parser.add_argument("--sign", action="store_true", help="Enable code signing (opt-in explicit or auto-detected)")
    parser.add_argument("--strict-signing", action="store_true", help="Fail build if code signing fails or credentials missing")
    parser.add_argument("--cert-file", default=None, help="Path to .pfx/.p12 certificate file")
    parser.add_argument("--cert-pass", default=None, help="Password for certificate file")
    parser.add_argument("--cert-sha1", default=None, help="SHA-1 thumbprint for Windows Certificate Store")
    parser.add_argument("--skip-signing", action="store_true", help="Explicitly skip all signing stages")
    parser.add_argument("--dry-run-signing", action="store_true", help="Simulate signing commands without running signtool")
    args = parser.parse_args()

    do_web = args.web or args.all or (not args.web and not args.offline)
    do_offline = args.offline or args.all

    should_sign = not args.skip_signing and (
        args.sign
        or args.strict_signing
        or os.environ.get("SIGN_STRICT") == "1"
        or bool(get_signing_config(args.cert_file, args.cert_pass, args.cert_sha1))
        or bool(find_signtool())
    )

    print("==================================================================")
    print(f"       Ny-Luna Core Windows Installer Builder (v{args.version})   ")
    print("==================================================================")

    if not args.skip_compile:
        build_rust_frontend(release=True)
        build_python_agent()
        if should_sign:
            sign_binary(
                REPO_ROOT / "dist" / "NyLuna.exe",
                description="Ny-Luna Core",
                strict=args.strict_signing,
                dry_run=args.dry_run_signing,
                cert_file=args.cert_file,
                cert_pass=args.cert_pass,
                cert_sha1=args.cert_sha1,
            )
            sign_binary(
                REPO_ROOT / "dist" / "agent.exe",
                description="Ny-Luna Core Agent",
                strict=args.strict_signing,
                dry_run=args.dry_run_signing,
                cert_file=args.cert_file,
                cert_pass=args.cert_pass,
                cert_sha1=args.cert_sha1,
            )
            unwind_dll = REPO_ROOT / "dist" / "libunwind.dll"
            if unwind_dll.is_file():
                sign_binary(
                    unwind_dll,
                    description="LLVM libunwind",
                    strict=args.strict_signing,
                    dry_run=args.dry_run_signing,
                    cert_file=args.cert_file,
                    cert_pass=args.cert_pass,
                    cert_sha1=args.cert_sha1,
                )
        generate_cdc_indexes(args.version)

    if do_web:
        web_exe = build_web_installer()
        if should_sign:
            sign_binary(
                web_exe,
                description="Ny-Luna Setup",
                strict=args.strict_signing,
                dry_run=args.dry_run_signing,
                cert_file=args.cert_file,
                cert_pass=args.cert_pass,
                cert_sha1=args.cert_sha1,
            )
            raw_web = REPO_ROOT / "dist" / "NLCSetup.exe"
            if raw_web.is_file() and raw_web.resolve() != web_exe.resolve():
                sign_binary(
                    raw_web,
                    description="Ny-Luna Setup",
                    strict=args.strict_signing,
                    dry_run=args.dry_run_signing,
                    cert_file=args.cert_file,
                    cert_pass=args.cert_pass,
                    cert_sha1=args.cert_sha1,
                )

    if do_offline:
        offline_exe = build_offline_installer()
        if should_sign:
            sign_binary(
                offline_exe,
                description="Ny-Luna Setup (Offline)",
                strict=args.strict_signing,
                dry_run=args.dry_run_signing,
                cert_file=args.cert_file,
                cert_pass=args.cert_pass,
                cert_sha1=args.cert_sha1,
            )
            raw_offline = REPO_ROOT / "dist" / "NLCSetup-Offline.exe"
            if raw_offline.is_file() and raw_offline.resolve() != offline_exe.resolve():
                sign_binary(
                    raw_offline,
                    description="Ny-Luna Setup (Offline)",
                    strict=args.strict_signing,
                    dry_run=args.dry_run_signing,
                    cert_file=args.cert_file,
                    cert_pass=args.cert_pass,
                    cert_sha1=args.cert_sha1,
                )

    print("\n==================================================================")
    print("                       BUILD COMPLETE!                            ")
    print(f" Installers available in: {REPO_ROOT / 'dist' / 'installers'}     ")
    print("==================================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())

