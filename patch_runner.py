import argparse
import ctypes
import os
import shutil
import subprocess
import sys
import time

from nlc.update_engine import apply_patch


APP_EXE = "NewLauncher.exe"
AGENT_EXE = "agent.exe"


def _is_admin():
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_as_admin(argv):
    if os.name != "nt" or _is_admin():
        return _is_admin()
    try:
        executable = os.path.abspath(sys.executable)
        elevated_argv = list(argv)
        if "--elevated" not in elevated_argv:
            elevated_argv.append("--elevated")
        params = subprocess.list2cmdline(elevated_argv)
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            params,
            os.path.dirname(executable),
            1,
        )
        return int(result) > 32
    except Exception:
        return False


def _launcher_is_running(pid):
    if not pid:
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def _stop_agent():
    try:
        subprocess.run(
            ["taskkill", "/IM", AGENT_EXE, "/F"],
            capture_output=True,
            check=False,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _parse_args(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch", default="")
    parser.add_argument("--replace-binary", default="")
    parser.add_argument("--target", required=True)
    parser.add_argument("--launcher-pid", type=int, default=0)
    parser.add_argument("--elevated", action="store_true")
    return parser.parse_args(argv)


def _validate_args(args):
    if not args.patch and not args.replace_binary:
        raise ValueError("Either --patch or --replace-binary must be specified")
    if args.patch and not os.path.isfile(args.patch):
        raise FileNotFoundError(args.patch)
    if args.replace_binary and not os.path.isfile(args.replace_binary):
        raise FileNotFoundError(args.replace_binary)
    if not os.path.isdir(args.target):
        raise FileNotFoundError(args.target)
    if args.launcher_pid < 0:
        raise ValueError("--launcher-pid must be non-negative")


def _apply_binary_replacement(source_path: str, target_dir: str):
    source = os.path.abspath(source_path)
    target = os.path.join(os.path.abspath(target_dir), APP_EXE)
    backup = target + ".backup"

    if os.path.exists(target):
        shutil.copy2(target, backup)

    try:
        os.replace(source, target)
    except Exception:
        if os.path.exists(backup):
            try:
                shutil.copy2(backup, target)
            except Exception:
                pass
        raise
    finally:
        if os.path.exists(backup):
            try:
                os.remove(backup)
            except Exception:
                pass


def _launch_app(target):
    launcher_path = os.path.join(target, APP_EXE)
    if os.path.isfile(launcher_path):
        try:
            creationflags = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
            subprocess.Popen([launcher_path], cwd=target, close_fds=True, creationflags=creationflags)
        except Exception as e:
            print(f"Failed to restart launcher: {e}", file=sys.stderr)


def main(argv=None):
    args = _parse_args(argv or sys.argv[1:])
    _validate_args(args)
    if os.name != "nt":
        raise RuntimeError("The Windows patch runner can only run on Windows.")

    if not _is_admin():
        if _relaunch_as_admin(sys.argv[1:] + ["--elevated"]):
            return 0
        raise PermissionError("Administrator permission was not granted.")

    deadline = time.monotonic() + 20
    while args.launcher_pid and _launcher_is_running(args.launcher_pid) and time.monotonic() < deadline:
        time.sleep(0.1)

    if args.launcher_pid and _launcher_is_running(args.launcher_pid):
        subprocess.run(
            ["taskkill", "/PID", str(args.launcher_pid), "/F"],
            capture_output=True,
            check=False,
            timeout=8,
        )
        time.sleep(0.5)

    _stop_agent()
    if args.patch:
        apply_patch(args.patch, args.target)
    elif args.replace_binary:
        _apply_binary_replacement(args.replace_binary, args.target)
    _launch_app(args.target)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Patch update failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
