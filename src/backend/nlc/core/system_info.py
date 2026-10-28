
import os
import sys
import shutil
import platform
import subprocess
import glob
from pathlib import Path
from typing import List, Dict, Optional, Any

def get_total_ram_mb() -> int:
    # 1. Linux / Android
    if hasattr(os, "sysconf"):
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            if pages and page_size and pages > 0 and page_size > 0:
                return int((pages * page_size) // (1024 * 1024))
        except (ValueError, OSError, AttributeError):
            pass

    # 2. Linux /proc/meminfo fallback
    meminfo_path = Path("/proc/meminfo")
    if meminfo_path.exists():
        try:
            with open(meminfo_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            kb = int(parts[1])
                            return int(kb // 1024)
        except Exception:
            pass

    # 3. Windows ctypes
    if os.name == "nt":
        try:
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return int(stat.ullTotalPhys // (1024 * 1024))
        except Exception:
            pass

    # 4. macOS sysctl fallback
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=1).decode().strip()
            if out.isdigit():
                return int(int(out) // (1024 * 1024))
        except Exception:
            pass

    # Safe fallback if undetermined: 8192 MB (8 GB)
    return 8192

def _get_java_version(binary_path: str) -> Optional[str]:
    try:
        out = subprocess.check_output(
            [binary_path, "-version"],
            stderr=subprocess.STDOUT,
            timeout=2,
            text=True
        )
        for line in out.splitlines():
            line_clean = line.strip()
            if "version" in line_clean.lower():
                return line_clean
        return "Java Runtime"
    except Exception:
        return None

def detect_installed_javas() -> List[Dict[str, str]]:
    found: Dict[str, str] = {}  # path -> display_label
    candidates: List[str] = []

    # 1. System PATH
    which_java = shutil.which("java")
    if which_java:
        try:
            candidates.append(os.path.realpath(which_java))
        except Exception:
            candidates.append(which_java)

    # 2. JAVA_HOME environment variable
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        jh_bin = os.path.join(java_home, "bin", "java.exe" if os.name == "nt" else "java")
        if os.path.exists(jh_bin):
            candidates.append(jh_bin)

    # 3. Linux JVM standard directories
    if os.name != "nt":
        search_dirs = [
            "/usr/lib/jvm/*",
            "/usr/lib64/jvm/*",
            "/usr/local/jvm/*",
            os.path.expanduser("~/.sdkman/candidates/java/*"),
            os.path.expanduser("~/.jdks/*"),
        ]
        for pattern in search_dirs:
            for d in glob.glob(pattern):
                bin_path = os.path.join(d, "bin", "java")
                if os.path.isfile(bin_path) and os.access(bin_path, os.X_OK):
                    candidates.append(bin_path)
    else:
        # 4. Windows Standard directories
        win_dirs = [
            r"C:\Program Files\Java\*",
            r"C:\Program Files (x86)\Java\*",
            r"C:\Program Files\Eclipse Adoptium\*",
            r"C:\Program Files\Microsoft\jdk*",
            r"C:\Program Files\BellSoft\*",
            r"C:\Program Files\Zulu\*",
            os.path.expanduser(r"~\.jdks\*"),
        ]
        for pattern in win_dirs:
            for d in glob.glob(pattern):
                bin_path = os.path.join(d, "bin", "java.exe")
                if os.path.isfile(bin_path):
                    candidates.append(bin_path)

    # Process and deduplicate candidates
    for cand in candidates:
        try:
            real_p = os.path.realpath(cand)
        except Exception:
            real_p = cand

        if real_p not in found:
            ver_info = _get_java_version(real_p)
            if ver_info:
                # Format friendly label
                # e.g. "openjdk version 21.0.2" -> "Java 21 (21.0.2)"
                label = ver_info
                if '"' in ver_info:
                    raw_ver = ver_info.split('"')[1]
                    major = raw_ver.split(".")[0]
                    if major == "1" and len(raw_ver.split(".")) > 1:
                        major = raw_ver.split(".")[1]
                    label = f"Java {major} ({raw_ver})"
                found[real_p] = label

    return [{"path": p, "label": lbl} for p, lbl in found.items()]

def get_system_specs() -> Dict[str, str]:
    total_ram_gb = round(get_total_ram_mb() / 1024.0, 1)
    return {
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python": f"Python {platform.python_version()}",
        "ram": f"{total_ram_gb} GB Total Physical RAM",
        "processor": platform.processor() or platform.machine(),
    }
