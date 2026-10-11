import argparse
import ctypes
import os
import subprocess
import sys
import time

from nlc.core.updater import apply_patch


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
        params = subprocess.list2cmdline(argv)
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
    parser.add_argument("--patch", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--launcher-pid", type=int, default=0)
    parser.add_argument("--elevated", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv or sys.argv[1:])
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
    apply_patch(args.patch, args.target)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Patch update failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
