import os
import shutil
import subprocess
import sys
import threading
import argparse
import ctypes
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import winreg
from nlc.core.updater import apply_patch


APP_NAME = "NLC"
APP_VERSION = "3.0.3"
APP_PUBLISHER = "@amne-dev on github"
APP_EXE = "NewLauncher.exe"
AGENT_EXE = "agent.exe"
SHORTCUT_NAME = "NLC"
SETUP_EXE_NAME = "NLCSetup.exe"
PAYLOAD_DIR_NAME = "payload"
CHUNK_SIZE = 1024 * 1024
UNINSTALL_ROOT = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
CUSTOM_UNINSTALL_KEY = "NewLauncher"
LEGACY_INNO_KEY = "{A3543210-9876-5432-1000-ABCDEF123456}_is1"
APP_USER_MODEL_ID = "AmneDev.NewLauncher.Setup"


def resource_path(rel_path: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, rel_path)


def resolve_payload_file(name: str) -> str:
    candidates = [
        os.path.join(resource_path(PAYLOAD_DIR_NAME), name),
        resource_path(name),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def default_install_dir() -> str:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        local_appdata = os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(local_appdata, "NewLauncher")


def _ps_quote(value: str) -> str:
    return value.replace("'", "''")


def create_shortcut(link_path: str, target_path: str, working_dir: str, icon_path: str) -> None:
    script = (
        "$w = New-Object -ComObject WScript.Shell;"
        "$s = $w.CreateShortcut('{0}');"
        "$s.TargetPath = '{1}';"
        "$s.WorkingDirectory = '{2}';"
        "$s.IconLocation = '{3},0';"
        "$s.Save();"
    ).format(
        _ps_quote(link_path),
        _ps_quote(target_path),
        _ps_quote(working_dir),
        _ps_quote(icon_path),
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
    )


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path.rstrip("\\/")))


def _path_within(path: str, parent: str) -> bool:
    try:
        p = _norm(path)
        root = _norm(parent)
    except Exception:
        return False
    return p == root or p.startswith(root + os.sep)


def is_user_admin() -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(argv: list[str]) -> bool:
    if os.name != "nt":
        return False
    if is_user_admin():
        return True

    try:
        if getattr(sys, "frozen", False):
            executable = os.path.abspath(sys.executable)
            params = subprocess.list2cmdline(argv)
            workdir = os.path.dirname(executable)
        else:
            script_path = os.path.abspath(__file__)
            executable = sys.executable
            params = subprocess.list2cmdline([script_path, *argv])
            workdir = os.path.dirname(script_path)

        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            params,
            workdir,
            1,
        )
        return int(result) > 32
    except Exception:
        return False


def path_needs_admin(path: str) -> bool:
    if os.name != "nt":
        return False
    roots = [
        os.environ.get("ProgramFiles", ""),
        os.environ.get("ProgramFiles(x86)", ""),
        os.environ.get("ProgramW6432", ""),
        os.environ.get("WINDIR", ""),
    ]
    return any(root and _path_within(path, root) for root in roots)


def _find_existing_parent(path: str) -> str:
    probe = os.path.abspath(path)
    while not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    if os.path.isdir(probe):
        return probe
    return os.path.dirname(os.path.abspath(path))


def check_write_access(target_dir: str) -> tuple[bool, str]:
    probe_dir = target_dir if os.path.isdir(target_dir) else _find_existing_parent(target_dir)
    try:
        os.makedirs(target_dir, exist_ok=True)
    except PermissionError:
        return False, f"No permission to create directory: {target_dir}"
    except OSError:
        pass

    if not os.path.isdir(probe_dir):
        return False, f"Target path is not writable: {probe_dir}"
    try:
        with tempfile.NamedTemporaryFile(prefix="nlc_write_test_", dir=probe_dir, delete=True) as temp:
            temp.write(b"ok")
            temp.flush()
        return True, ""
    except PermissionError:
        return False, f"No write permission in: {probe_dir}"
    except OSError as exc:
        return False, f"Cannot write in {probe_dir}: {exc}"


def _read_reg_str(root, key_path: str, value_name: str) -> str:
    try:
        with winreg.OpenKey(root, key_path, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            return str(value)
    except Exception:
        return ""


def _extract_install_dir_from_uninstall_key(root, sub_key_name: str) -> str:
    key_path = UNINSTALL_ROOT + "\\" + sub_key_name
    install_loc = _read_reg_str(root, key_path, "InstallLocation").strip()
    if install_loc:
        return install_loc

    display_icon = _read_reg_str(root, key_path, "DisplayIcon").strip()
    if "," in display_icon:
        display_icon = display_icon.split(",", 1)[0].strip()
    display_icon = display_icon.strip('"')
    if display_icon:
        if display_icon.lower().endswith(".exe"):
            return os.path.dirname(display_icon)
        return display_icon
    return ""


def _looks_like_install_dir(path: str) -> bool:
    if not path:
        return False
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        return False
    markers = (APP_EXE, AGENT_EXE, "unins000.exe", SETUP_EXE_NAME)
    return any(os.path.exists(os.path.join(path, marker)) for marker in markers)


def discover_existing_install_dir() -> str:
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    keys = (CUSTOM_UNINSTALL_KEY, LEGACY_INNO_KEY)
    for root in roots:
        for key in keys:
            path = _extract_install_dir_from_uninstall_key(root, key)
            if not path:
                continue
            if _looks_like_install_dir(path):
                return path
            if os.path.isdir(path):
                return path

    candidates = [
        default_install_dir(),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), APP_NAME),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), APP_NAME),
    ]
    for path in candidates:
        if _looks_like_install_dir(path):
            return path
    return ""


def remove_shortcut_if_exists(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def remove_uninstall_entry() -> None:
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            winreg.DeleteKey(root, UNINSTALL_ROOT + "\\" + CUSTOM_UNINSTALL_KEY)
        except Exception:
            pass


def register_uninstall_entry(install_dir: str, setup_exe_path: str = "") -> None:
    if setup_exe_path and os.path.isfile(setup_exe_path) and setup_exe_path.lower().endswith(".exe"):
        command_prefix = f'"{setup_exe_path}"'
    else:
        script_path = os.path.abspath(__file__)
        command_prefix = f'"{sys.executable}" "{script_path}"'

    uninstall_cmd = f'{command_prefix} --uninstall --target "{install_dir}"'
    key_path = UNINSTALL_ROOT + "\\" + CUSTOM_UNINSTALL_KEY

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, APP_PUBLISHER)
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, install_dir)
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, os.path.join(install_dir, APP_EXE))
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, uninstall_cmd)
        winreg.SetValueEx(key, "QuietUninstallString", 0, winreg.REG_SZ, uninstall_cmd + " --quiet")
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def run_uninstall(target_dir: str, quiet: bool = False) -> int:
    if not target_dir:
        target_dir = discover_existing_install_dir() or default_install_dir()

    target_dir = os.path.abspath(target_dir)
    if not os.path.isdir(target_dir):
        if not quiet:
            messagebox.showerror("Uninstall Error", "Install directory was not found.")
        remove_uninstall_entry()
        return 1

    if not quiet:
        ok = messagebox.askyesno(
            "Uninstall New Launcher",
            f"Remove {APP_NAME} from:\n{target_dir}\n\nThis removes launcher binaries and shortcuts.",
        )
        if not ok:
            return 2

    files_to_remove = [
        APP_EXE,
        AGENT_EXE,
        "logo.ico",
        "logo.png",
        SETUP_EXE_NAME,
        "unins000.exe",
        "unins000.dat",
        "unins000.msg",
    ]
    for name in files_to_remove:
        try:
            path = os.path.join(target_dir, name)
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass

    start_menu_link = os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        SHORTCUT_NAME,
        SHORTCUT_NAME + ".lnk",
    )
    desktop_link = os.path.join(os.path.expanduser("~"), "Desktop", SHORTCUT_NAME + ".lnk")
    remove_shortcut_if_exists(start_menu_link)
    remove_shortcut_if_exists(desktop_link)
    try:
        start_menu_dir = os.path.dirname(start_menu_link)
        if os.path.isdir(start_menu_dir) and not os.listdir(start_menu_dir):
            os.rmdir(start_menu_dir)
    except Exception:
        pass

    try:
        if os.path.isdir(target_dir) and not os.listdir(target_dir):
            os.rmdir(target_dir)
    except Exception:
        pass

    remove_uninstall_entry()
    if not quiet:
        messagebox.showinfo("Uninstall Complete", f"{APP_NAME} has been removed.")
    return 0


def run_silent_install(target_dir: str = "") -> int:
    """Install the bundled launcher without creating a graphical installer window."""
    target_dir = os.path.abspath(target_dir.strip() or default_install_dir())
    can_write, write_reason = check_write_access(target_dir)
    if not can_write:
        raise PermissionError(write_reason)

    payload_files = [APP_EXE, AGENT_EXE, "logo.ico", "logo.png"]
    payload_sources = {name: resolve_payload_file(name) for name in payload_files}
    missing = [name for name, source in payload_sources.items() if not source]
    if missing:
        raise RuntimeError("Installer payload is incomplete. Missing: " + ", ".join(missing))

    for process_name in (APP_EXE, AGENT_EXE):
        try:
            subprocess.run(
                ["taskkill", "/IM", process_name, "/F"],
                capture_output=True,
                check=False,
                timeout=8,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    os.makedirs(target_dir, exist_ok=True)
    for name, source in payload_sources.items():
        shutil.copy2(source, os.path.join(target_dir, name))

    setup_source = os.path.abspath(sys.executable if getattr(sys, "frozen", False) else sys.argv[0])
    setup_target = ""
    if os.path.isfile(setup_source) and setup_source.lower().endswith(".exe"):
        setup_target = os.path.join(target_dir, SETUP_EXE_NAME)
        if _norm(setup_source) != _norm(setup_target):
            shutil.copy2(setup_source, setup_target)

    _create_start_menu_shortcut(target_dir)
    register_uninstall_entry(target_dir, setup_target)
    return 0


def run_patch(package_path: str, target_dir: str = "") -> int:
    """Apply an incremental launcher patch without touching user data."""
    target_dir = os.path.abspath(target_dir.strip() or default_install_dir())
    can_write, reason = check_write_access(target_dir)
    if not can_write:
        raise PermissionError(reason)
    for process_name in (APP_EXE, AGENT_EXE):
        try:
            subprocess.run(
                ["taskkill", "/IM", process_name, "/F"],
                capture_output=True,
                check=False,
                timeout=8,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    apply_patch(package_path, target_dir)
    register_uninstall_entry(target_dir, os.path.join(target_dir, SETUP_EXE_NAME))
    return 0


def _create_start_menu_shortcut(install_dir: str) -> None:
    app_path = os.path.join(install_dir, APP_EXE)
    icon_path = os.path.join(install_dir, "logo.ico")
    start_menu_dir = os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        SHORTCUT_NAME,
    )
    if not start_menu_dir:
        return
    os.makedirs(start_menu_dir, exist_ok=True)
    create_shortcut(
        os.path.join(start_menu_dir, SHORTCUT_NAME + ".lnk"),
        app_path,
        install_dir,
        icon_path,
    )


class InstallerApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("NLC Setup")
        self.root.geometry("1080x560")
        self.root.minsize(980, 520)
        self.root.configure(bg="#1e1e1e")
        self._set_windows_app_id()
        self._custom_chrome_applied = False
        self._original_win_style = None
        self._taskbar_refresh_done = False
        if os.name != "nt":
            self.root.overrideredirect(True)
        self.root.bind("<Map>", self._on_window_map)

        try:
            icon = resource_path("logo.ico")
            if os.path.exists(icon):
                self.root.iconbitmap(icon)
        except Exception:
            pass
        try:
            logo_png = resource_path("logo.png")
            if os.path.exists(logo_png):
                self._icon_photo = tk.PhotoImage(file=logo_png)
                self.root.iconphoto(True, self._icon_photo)
        except Exception:
            pass

        detected = discover_existing_install_dir()
        self.detected_existing_dir = _norm(detected) if detected else ""
        self.install_path_var = tk.StringVar(value=detected or default_install_dir())
        self.desktop_shortcut_var = tk.BooleanVar(value=True)
        self.launch_after_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Ready to install")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.is_update_mode = False
        self._drag_start_x = 0
        self._drag_start_y = 0
        self._drag_win_x = 0
        self._drag_win_y = 0
        self._drag_target_x = 0
        self._drag_target_y = 0
        self._drag_active = False
        self._drag_apply_after_id = None
        self._drag_preview_enabled = (os.name == "nt")
        self._drag_preview_win = None
        self._drag_preview_w = 0
        self._drag_preview_h = 0
        self._drag_preview_logo = None
        self._minimize_pending = False

        self._build_ui()
        self._center_window()
        self.root.after(40, self._apply_initial_window_styles)
        self._refresh_install_mode()

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "NLC.Horizontal.TProgressbar",
            troughcolor="#2a2a2a",
            background="#2D8F36",
            bordercolor="#2a2a2a",
            lightcolor="#2D8F36",
            darkcolor="#2D8F36",
        )

        chrome = tk.Frame(
            self.root,
            bg="#1e1e1e",
            highlightthickness=1,
            highlightbackground="#363636",
            highlightcolor="#363636",
        )
        chrome.pack(fill="both", expand=True)

        self.titlebar = tk.Frame(chrome, bg="#141414", height=36)
        self.titlebar.pack(fill="x")
        self.titlebar.pack_propagate(False)

        self.titlebar_icon = tk.Label(
            self.titlebar,
            text="NLC",
            font=("Segoe UI", 9, "bold"),
            fg="#8fe39b",
            bg="#141414",
        )
        self.titlebar_icon.pack(side="left", padx=(12, 8))

        self.titlebar_title = tk.Label(
            self.titlebar,
            text="New Launcher Setup",
            font=("Segoe UI", 10, "bold"),
            fg="#d5d5d5",
            bg="#141414",
        )
        self.titlebar_title.pack(side="left")

        title_controls = tk.Frame(self.titlebar, bg="#141414")
        title_controls.pack(side="right", fill="y")

        self.min_btn = tk.Button(
            title_controls,
            text="\u2013",
            command=self._minimize_window,
            font=("Segoe UI", 13, "bold"),
            fg="#d2d2d2",
            bg="#141414",
            activeforeground="white",
            activebackground="#2a2a2a",
            relief="flat",
            bd=0,
            padx=14,
            pady=0,
            cursor="hand2",
        )
        self.min_btn.pack(side="left", fill="y")
        self.min_btn.bind("<Enter>", lambda _e: self.min_btn.config(bg="#2a2a2a", fg="white"))
        self.min_btn.bind("<Leave>", lambda _e: self.min_btn.config(bg="#141414", fg="#d2d2d2"))

        self.close_btn = tk.Button(
            title_controls,
            text="X",
            command=self._close_window,
            font=("Segoe UI", 10, "bold"),
            fg="#d2d2d2",
            bg="#141414",
            activeforeground="white",
            activebackground="#b83333",
            relief="flat",
            bd=0,
            padx=14,
            pady=0,
            cursor="hand2",
        )
        self.close_btn.pack(side="left", fill="y")
        self.close_btn.bind("<Enter>", lambda _e: self.close_btn.config(bg="#c23b3b", fg="white"))
        self.close_btn.bind("<Leave>", lambda _e: self.close_btn.config(bg="#141414", fg="#d2d2d2"))

        for widget in (self.titlebar, self.titlebar_icon, self.titlebar_title):
            widget.bind("<ButtonPress-1>", self._start_window_drag)
            widget.bind("<B1-Motion>", self._on_window_drag)
            widget.bind("<ButtonRelease-1>", self._end_window_drag)

        tk.Frame(chrome, bg="#2D8F36", height=1).pack(fill="x")

        content = tk.Frame(chrome, bg="#1e1e1e")
        content.pack(fill="both", expand=True)

        outer = tk.Frame(content, bg="#1e1e1e")
        outer.pack(fill="both", expand=True, padx=18, pady=18)

        left = tk.Frame(outer, bg="#252526", width=280)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        right = tk.Frame(outer, bg="#1e1e1e")
        right.pack(side="right", fill="both", expand=True, padx=(18, 0))

        logo_path = resource_path("logo.png")
        if os.path.exists(logo_path):
            try:
                from PIL import Image, ImageTk  # local import to avoid hard dependency in launcher runtime

                image = Image.open(logo_path).convert("RGBA").resize((110, 110), Image.Resampling.LANCZOS)
                self.logo_photo = ImageTk.PhotoImage(image)
                tk.Label(left, image=self.logo_photo, bg="#252526").pack(pady=(36, 14))
            except Exception:
                pass

        tk.Label(
            left,
            text="NEW LAUNCHER",
            font=("Segoe UI", 16, "bold"),
            fg="white",
            bg="#252526",
        ).pack()
        tk.Label(
            left,
            text="Custom Setup",
            font=("Segoe UI", 10),
            fg="#a0a0a0",
            bg="#252526",
        ).pack(pady=(4, 24))

        self.mode_badge = tk.Label(
            left,
            text="Mode: Install",
            font=("Segoe UI", 10, "bold"),
            fg="#c8c8c8",
            bg="#252526",
        )
        self.mode_badge.pack()

        tk.Label(
            right,
            text="Setup Destination",
            font=("Segoe UI", 19, "bold"),
            fg="white",
            bg="#1e1e1e",
        ).pack(anchor="w")

        tk.Label(
            right,
            text="Choose where New Launcher should be installed.",
            font=("Segoe UI", 10),
            fg="#9a9a9a",
            bg="#1e1e1e",
        ).pack(anchor="w", pady=(4, 14))

        path_row = tk.Frame(right, bg="#1e1e1e")
        path_row.pack(fill="x")
        self.path_entry = tk.Entry(
            path_row,
            textvariable=self.install_path_var,
            font=("Segoe UI", 10),
            bg="#2d2d2d",
            fg="white",
            relief="flat",
            insertbackground="white",
        )
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=7)
        tk.Button(
            path_row,
            text="Browse",
            command=self._browse_install_dir,
            font=("Segoe UI", 9, "bold"),
            bg="#3a3a3a",
            fg="white",
            relief="flat",
            padx=12,
            pady=8,
            cursor="hand2",
        ).pack(side="left", padx=(8, 0))

        options = tk.Frame(right, bg="#1e1e1e")
        options.pack(fill="x", pady=(18, 10))

        self.desktop_cb = tk.Checkbutton(
            options,
            text="Create Desktop Shortcut",
            variable=self.desktop_shortcut_var,
            bg="#1e1e1e",
            fg="white",
            selectcolor="#2d2d2d",
            activebackground="#1e1e1e",
            activeforeground="white",
            font=("Segoe UI", 10),
        )
        self.desktop_cb.pack(anchor="w")

        tk.Checkbutton(
            options,
            text="Launch New Launcher after setup",
            variable=self.launch_after_var,
            bg="#1e1e1e",
            fg="white",
            selectcolor="#2d2d2d",
            activebackground="#1e1e1e",
            activeforeground="white",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(6, 0))

        bar_frame = tk.Frame(right, bg="#1e1e1e")
        bar_frame.pack(fill="x", pady=(16, 0))
        self.progress = ttk.Progressbar(
            bar_frame,
            style="NLC.Horizontal.TProgressbar",
            maximum=100.0,
            variable=self.progress_var,
        )
        self.progress.pack(fill="x")

        tk.Label(
            right,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            fg="#a0a0a0",
            bg="#1e1e1e",
        ).pack(anchor="w", pady=(8, 0))

        self.log_box = tk.Text(
            right,
            height=10,
            bg="#191919",
            fg="#c8c8c8",
            relief="flat",
            font=("Consolas", 9),
            state="disabled",
        )
        self.log_box.pack(fill="both", expand=True, pady=(14, 12))

        controls = tk.Frame(right, bg="#1e1e1e")
        controls.pack(fill="x")
        self.install_btn = tk.Button(
            controls,
            text="Install",
            command=self._start_install,
            font=("Segoe UI", 11, "bold"),
            bg="#2D8F36",
            fg="white",
            activebackground="#38a144",
            activeforeground="white",
            relief="flat",
            padx=18,
            pady=9,
            cursor="hand2",
        )
        self.install_btn.pack(side="right")

        self.install_path_var.trace_add("write", lambda *_: self._refresh_install_mode())

    def _browse_install_dir(self) -> None:
        initial = self.install_path_var.get().strip() or default_install_dir()
        chosen = filedialog.askdirectory(initialdir=initial)
        if chosen:
            self.install_path_var.set(chosen)

    def _center_window(self) -> None:
        self.root.update_idletasks()
        width = self.root.winfo_width() or 1080
        height = self.root.winfo_height() or 560
        x = max(0, (self.root.winfo_screenwidth() - width) // 2)
        y = max(0, (self.root.winfo_screenheight() - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _set_windows_app_id(self) -> None:
        if os.name != "nt":
            return
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass

    def _get_native_hwnd(self) -> int:
        if os.name != "nt":
            return 0
        try:
            base_hwnd = int(self.root.winfo_id())
            GA_ROOT = 2
            root_hwnd = ctypes.windll.user32.GetAncestor(base_hwnd, GA_ROOT)
            return int(root_hwnd) if root_hwnd else base_hwnd
        except Exception:
            return 0

    def _set_custom_window_chrome(self, enabled: bool) -> None:
        if os.name != "nt":
            self.root.overrideredirect(bool(enabled))
            self._custom_chrome_applied = bool(enabled)
            return
        try:
            hwnd = self._get_native_hwnd()
            if not hwnd:
                return
            get_window_long = getattr(ctypes.windll.user32, "GetWindowLongPtrW", ctypes.windll.user32.GetWindowLongW)
            set_window_long = getattr(ctypes.windll.user32, "SetWindowLongPtrW", ctypes.windll.user32.SetWindowLongW)

            GWL_STYLE = -16
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            WS_POPUP = 0x80000000
            WS_CAPTION = 0x00C00000
            WS_THICKFRAME = 0x00040000
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            WS_SYSMENU = 0x00080000

            current_style = int(get_window_long(hwnd, GWL_STYLE))
            if self._original_win_style is None:
                self._original_win_style = current_style

            if enabled:
                new_style = (current_style & ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)) | WS_POPUP
                if new_style != current_style:
                    set_window_long(hwnd, GWL_STYLE, new_style)
                    ctypes.windll.user32.SetWindowPos(
                        hwnd, 0, 0, 0, 0, 0,
                        SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                    )
                self._custom_chrome_applied = True
            elif self._custom_chrome_applied:
                restore_style = int(self._original_win_style) if self._original_win_style is not None else current_style
                set_window_long(hwnd, GWL_STYLE, restore_style)
                ctypes.windll.user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                )
                self._custom_chrome_applied = False
        except Exception:
            pass

    def _apply_initial_window_styles(self) -> None:
        self._set_custom_window_chrome(True)
        self._ensure_taskbar_entry()

    def _ensure_taskbar_entry(self) -> None:
        if os.name != "nt":
            return
        try:
            hwnd = self._get_native_hwnd()
            if not hwnd:
                return
            get_window_long = getattr(ctypes.windll.user32, "GetWindowLongPtrW", ctypes.windll.user32.GetWindowLongW)
            set_window_long = getattr(ctypes.windll.user32, "SetWindowLongPtrW", ctypes.windll.user32.SetWindowLongW)
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020

            exstyle = int(get_window_long(hwnd, GWL_EXSTYLE))
            new_style = (exstyle & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            if new_style != exstyle:
                set_window_long(hwnd, GWL_EXSTYLE, new_style)
                ctypes.windll.user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                )
            if not self._taskbar_refresh_done:
                self._taskbar_refresh_done = True
                self.root.after(30, self._refresh_taskbar_window)
        except Exception:
            pass

    def _refresh_taskbar_window(self) -> None:
        if os.name != "nt":
            return
        try:
            if self._drag_active or str(self.root.state()) == "withdrawn":
                return
            geom = self.root.geometry()
            self.root.withdraw()
            self.root.after(20, lambda g=geom: self._restore_from_taskbar_refresh(g))
        except Exception:
            pass

    def _restore_from_taskbar_refresh(self, geom: str) -> None:
        try:
            self.root.deiconify()
            self.root.geometry(geom)
            self.root.lift()
            self._set_custom_window_chrome(True)
        except Exception:
            pass

    def _start_window_drag(self, event) -> None:
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root
        self._drag_win_x = self.root.winfo_x()
        self._drag_win_y = self.root.winfo_y()
        self._drag_target_x = self._drag_win_x
        self._drag_target_y = self._drag_win_y
        self._drag_active = True
        self._open_drag_preview()

    def _on_window_drag(self, event) -> None:
        if not self._drag_active:
            return
        target_x = self._drag_win_x + (event.x_root - self._drag_start_x)
        target_y = self._drag_win_y + (event.y_root - self._drag_start_y)
        if target_x == self._drag_target_x and target_y == self._drag_target_y:
            return
        self._drag_target_x = target_x
        self._drag_target_y = target_y
        self._schedule_window_drag_apply()

    def _open_drag_preview(self) -> None:
        if not self._drag_preview_enabled or self._drag_preview_win is not None:
            return
        try:
            self.root.update_idletasks()
            self._drag_preview_w = max(560, self.root.winfo_width())
            self._drag_preview_h = max(360, self.root.winfo_height())

            preview = tk.Toplevel(self.root)
            preview.overrideredirect(True)
            preview.configure(bg="#0f0f0f")
            try:
                preview.attributes("-topmost", True)
            except Exception:
                pass
            preview.geometry(
                f"{self._drag_preview_w}x{self._drag_preview_h}+{self._drag_target_x}+{self._drag_target_y}"
            )

            shell = tk.Frame(preview, bg="#0f0f0f", highlightthickness=1, highlightbackground="#2f2f2f")
            shell.pack(fill="both", expand=True)
            center = tk.Frame(shell, bg="#0f0f0f")
            center.place(relx=0.5, rely=0.5, anchor="center")

            logo_path = resource_path("logo.png")
            if os.path.exists(logo_path):
                try:
                    from PIL import Image, ImageTk

                    img = Image.open(logo_path).convert("RGBA").resize((88, 88), Image.Resampling.LANCZOS)
                    self._drag_preview_logo = ImageTk.PhotoImage(img)
                    tk.Label(center, image=self._drag_preview_logo, bg="#0f0f0f").pack(pady=(0, 14))
                except Exception:
                    pass

            tk.Label(
                center,
                text="NLC",
                font=("Segoe UI", 22, "bold"),
                fg="white",
                bg="#0f0f0f",
            ).pack()
            tk.Label(
                center,
                text="Drag anywhere you want",
                font=("Segoe UI", 11),
                fg="#A0A0A0",
                bg="#0f0f0f",
            ).pack(pady=(8, 0))

            self._drag_preview_win = preview
            self.root.withdraw()
        except Exception:
            self._drag_preview_win = None

    def _apply_window_drag_target(self) -> None:
        self._drag_apply_after_id = None
        if not self._drag_active:
            return
        if self._drag_preview_win and self._drag_preview_win.winfo_exists():
            self._drag_preview_win.geometry(
                f"{self._drag_preview_w}x{self._drag_preview_h}+{self._drag_target_x}+{self._drag_target_y}"
            )
        else:
            self.root.geometry(f"+{self._drag_target_x}+{self._drag_target_y}")

    def _schedule_window_drag_apply(self) -> None:
        if self._drag_apply_after_id is not None:
            return
        self._drag_apply_after_id = self.root.after(8, self._apply_window_drag_target)

    def _end_window_drag(self, _event=None) -> None:
        if self._drag_apply_after_id is not None:
            try:
                self.root.after_cancel(self._drag_apply_after_id)
            except Exception:
                pass
            self._drag_apply_after_id = None

        if self._drag_active and self._drag_preview_win and self._drag_preview_win.winfo_exists():
            try:
                self.root.deiconify()
                self.root.geometry(
                    f"{self._drag_preview_w}x{self._drag_preview_h}+{self._drag_target_x}+{self._drag_target_y}"
                )
                self._set_custom_window_chrome(True)
                self.root.lift()
            except Exception:
                pass
            try:
                self._drag_preview_win.destroy()
            except Exception:
                pass
            self._drag_preview_win = None
            self._drag_preview_logo = None
            self._ensure_taskbar_entry()
        elif self._drag_active:
            self.root.geometry(f"+{self._drag_target_x}+{self._drag_target_y}")
        elif self._drag_preview_win and self._drag_preview_win.winfo_exists():
            try:
                self._drag_preview_win.destroy()
            except Exception:
                pass
            self._drag_preview_win = None
            self._drag_preview_logo = None
            try:
                self.root.deiconify()
                self._set_custom_window_chrome(True)
                self._ensure_taskbar_entry()
            except Exception:
                pass

        self._drag_active = False

    def _minimize_window(self) -> None:
        self._end_window_drag()
        self._minimize_pending = True
        if os.name != "nt":
            self.root.overrideredirect(False)
        self.root.iconify()

    def _on_window_map(self, _event=None) -> None:
        if self.root.state() != "normal":
            return
        if self._drag_active:
            return
        if self._minimize_pending:
            self.root.after(15, self._restore_custom_chrome)
        else:
            self.root.after(15, self._apply_initial_window_styles)

    def _restore_custom_chrome(self) -> None:
        self._set_custom_window_chrome(True)
        self._ensure_taskbar_entry()
        self._minimize_pending = False

    def _close_window(self) -> None:
        self._end_window_drag()
        self.root.destroy()

    def _append_log(self, text: str) -> None:
        self.log_box.config(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def _set_progress(self, value: float) -> None:
        self.progress_var.set(max(0.0, min(100.0, value)))

    def _refresh_install_mode(self) -> None:
        target = self.install_path_var.get().strip()
        norm_target = _norm(target) if target else ""
        matches_detected = bool(target and self.detected_existing_dir and norm_target == self.detected_existing_dir)
        is_update = _looks_like_install_dir(target) or matches_detected
        if is_update:
            self.mode_badge.config(text="Mode: Update", fg="#8fd0ff")
            self.install_btn.config(text="Update")
            if not self.is_update_mode:
                self.desktop_shortcut_var.set(False)
            self.desktop_cb.config(state="disabled")
        else:
            self.mode_badge.config(text="Mode: Install", fg="#8fe39b")
            self.install_btn.config(text="Install")
            self.desktop_cb.config(state="normal")
            if self.is_update_mode:
                self.desktop_shortcut_var.set(True)
        self.is_update_mode = is_update

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.install_btn.config(state=state)
        self.path_entry.config(state=state)
        if not busy:
            self._refresh_install_mode()

    def _start_install(self) -> None:
        target_dir = self.install_path_var.get().strip()
        if not target_dir:
            messagebox.showerror("Install Error", "Please choose an install directory.")
            return

        can_write, write_reason = check_write_access(target_dir)
        if not can_write:
            needs_admin = path_needs_admin(target_dir) and not is_user_admin()
            msg = "Permission check failed before install.\n" + write_reason
            if needs_admin:
                msg += (
                    "\n\nThis location is protected by Windows. "
                    "Run NLCSetup.exe as Administrator or install to a user folder "
                    "(for example AppData\\Local\\NewLauncher)."
                )
            messagebox.showerror("Install Error", msg)
            return

        required = [APP_EXE, AGENT_EXE, "logo.ico", "logo.png"]
        missing = [name for name in required if not resolve_payload_file(name)]
        if missing:
            messagebox.showerror(
                "Install Error",
                "Installer payload is incomplete.\nMissing: "
                + ", ".join(missing)
                + "\n\nRebuild NLCSetup.exe using build.bat so all bundled resources are embedded.",
            )
            return

        self._set_busy(True)
        self._set_progress(0)
        self.status_var.set("Preparing installation...")
        self._append_log("Starting setup...")

        thread = threading.Thread(target=self._install_worker, daemon=True)
        thread.start()

    def _install_worker(self) -> None:
        target_dir = self.install_path_var.get().strip()
        payload_files = [APP_EXE, AGENT_EXE, "logo.ico", "logo.png"]
        payload_sources = {name: resolve_payload_file(name) for name in payload_files}

        try:
            self.root.after(0, lambda: self._append_log("Stopping running launcher processes..."))
            self._stop_running_instances()
            os.makedirs(target_dir, exist_ok=True)
            self.root.after(0, lambda: self.status_var.set("Copying files..."))

            missing_now = [name for name, src in payload_sources.items() if not src]
            if missing_now:
                raise RuntimeError("Missing bundled files: " + ", ".join(missing_now))

            total_bytes = 0
            for name in payload_files:
                total_bytes += os.path.getsize(payload_sources[name])
            copied = 0

            def on_chunk(chunk_size: int) -> None:
                nonlocal copied
                copied += chunk_size
                pct = 8.0 + ((copied / max(1, total_bytes)) * 82.0)
                self.root.after(0, lambda p=pct: self._set_progress(p))

            for name in payload_files:
                src = payload_sources[name]
                dst = os.path.join(target_dir, name)
                self.root.after(0, lambda n=name: self._append_log("Installing " + n + "..."))
                try:
                    self._copy_with_progress(src, dst, on_chunk)
                except PermissionError as exc:
                    raise PermissionError(f"Access denied while writing: {dst}") from exc

            setup_target = ""
            setup_source = os.path.abspath(sys.executable if getattr(sys, "frozen", False) else sys.argv[0])
            if os.path.isfile(setup_source) and setup_source.lower().endswith(".exe"):
                setup_target = os.path.join(target_dir, SETUP_EXE_NAME)
                if _norm(setup_source) != _norm(setup_target):
                    shutil.copy2(setup_source, setup_target)
                    self.root.after(0, lambda: self._append_log("Installed setup uninstaller entry point."))
                else:
                    self.root.after(0, lambda: self._append_log("Setup executable already in target directory."))
            else:
                self.root.after(0, lambda: self._append_log("Setup executable copy skipped (dev mode)."))

            self.root.after(0, lambda: self.status_var.set("Creating shortcuts..."))
            self._create_shortcuts(target_dir)

            try:
                register_uninstall_entry(target_dir, setup_target)
                self.root.after(0, lambda: self._append_log("Registered Windows uninstall entry."))
            except Exception as reg_exc:
                self.root.after(0, lambda e=reg_exc: self._append_log("Uninstall registration failed: " + str(e)))

            self.root.after(0, lambda: self._set_progress(100.0))
            self.root.after(0, lambda: self.status_var.set("Setup complete"))
            self.root.after(0, lambda: self._append_log("Installation finished."))

            if self.launch_after_var.get():
                app_path = os.path.join(target_dir, APP_EXE)
                if os.path.exists(app_path):
                    self.root.after(0, lambda: self._append_log("Launching New Launcher..."))
                    subprocess.Popen([app_path], cwd=target_dir)

            self.root.after(220, self.root.destroy)
        except PermissionError:
            still_running = self._is_process_running(APP_EXE) or self._is_process_running(AGENT_EXE)
            reason = (
                "Permission denied while writing files.\n"
                "Check if the target folder requires Administrator rights "
                "(for example Program Files) or a launcher process is still running."
            )
            if still_running:
                reason += (
                    "\n\nA launcher process is still running. "
                    "Close it from Task Manager and try update again."
                )
            if path_needs_admin(target_dir) and not is_user_admin():
                reason += (
                    "\n\nThis target is protected by Windows. "
                    "Run NLCSetup.exe as Administrator or change install location."
                )
            self.root.after(
                0,
                lambda: messagebox.showerror(
                    "Install Error",
                    reason,
                ),
            )
            self.root.after(0, lambda: self.status_var.set("Install failed"))
            self.root.after(0, lambda: self._append_log("Install failed: permission denied."))
            self.root.after(0, lambda: self._set_busy(False))
        except Exception as exc:
            self.root.after(0, lambda: messagebox.showerror("Install Error", str(exc)))
            self.root.after(0, lambda: self.status_var.set("Install failed"))
            self.root.after(0, lambda: self._append_log("Install failed: " + str(exc)))
            self.root.after(0, lambda: self._set_busy(False))

    @staticmethod
    def _copy_with_progress(src: str, dst: str, on_chunk) -> None:
        with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
            while True:
                chunk = fsrc.read(CHUNK_SIZE)
                if not chunk:
                    break
                fdst.write(chunk)
                on_chunk(len(chunk))
        shutil.copystat(src, dst)

    def _stop_running_instances(self) -> None:
        if os.name != "nt":
            return
        for proc_name in (APP_EXE, AGENT_EXE):
            try:
                result = subprocess.run(
                    ["taskkill", "/IM", proc_name, "/F"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=8,
                )
                if result.returncode == 0:
                    self.root.after(0, lambda p=proc_name: self._append_log(f"Stopped {p}."))
            except subprocess.TimeoutExpired:
                self.root.after(0, lambda p=proc_name: self._append_log(f"Stop timeout for {p}; continuing."))
            except Exception:
                pass

    @staticmethod
    def _is_process_running(proc_name: str) -> bool:
        if os.name != "nt":
            return False
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {proc_name}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            output = (result.stdout or "").lower()
            return proc_name.lower() in output
        except Exception:
            return False

    def _create_shortcuts(self, install_dir: str) -> None:
        app_path = os.path.join(install_dir, APP_EXE)
        icon_path = os.path.join(install_dir, "logo.ico")
        start_menu_root = os.path.join(
            os.environ.get("APPDATA", ""),
            "Microsoft",
            "Windows",
            "Start Menu",
            "Programs",
            SHORTCUT_NAME,
        )
        if start_menu_root:
            os.makedirs(start_menu_root, exist_ok=True)
            start_link = os.path.join(start_menu_root, SHORTCUT_NAME + ".lnk")
            try:
                create_shortcut(start_link, app_path, install_dir, icon_path)
                self.root.after(0, lambda: self._append_log("Created Start Menu shortcut."))
            except Exception as exc:
                self.root.after(0, lambda: self._append_log("Start Menu shortcut failed: " + str(exc)))

        if self.desktop_shortcut_var.get():
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            desktop_link = os.path.join(desktop, SHORTCUT_NAME + ".lnk")
            try:
                create_shortcut(desktop_link, app_path, install_dir, icon_path)
                self.root.after(0, lambda: self._append_log("Created Desktop shortcut."))
            except Exception as exc:
                self.root.after(0, lambda: self._append_log("Desktop shortcut failed: " + str(exc)))

    def run(self) -> None:
        self.root.mainloop()


def _parse_args(argv: list[str]):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--target", default="")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--elevated", action="store_true")
    parser.add_argument("--patch", default="")
    args, _ = parser.parse_known_args(argv)
    return args


if __name__ == "__main__":
    cli = _parse_args(sys.argv[1:])
    if os.name == "nt" and not is_user_admin():
        if not cli.elevated:
            launch_args = list(sys.argv[1:])
            launch_args.append("--elevated")
            if relaunch_as_admin(launch_args):
                raise SystemExit(0)
        messagebox.showerror(
            "Administrator Required",
            "NLC Setup requires administrator privileges.\n"
            "Please approve the UAC prompt and try again.",
        )
        raise SystemExit(1)
    if cli.uninstall:
        raise SystemExit(run_uninstall(cli.target.strip(), quiet=cli.quiet))
    if cli.patch:
        try:
            raise SystemExit(run_patch(cli.patch, cli.target))
        except Exception as exc:
            print(f"Patch update failed: {exc}", file=sys.stderr)
            raise SystemExit(1)
    if cli.quiet:
        try:
            raise SystemExit(run_silent_install(cli.target))
        except Exception as exc:
            print(f"Silent installation failed: {exc}", file=sys.stderr)
            raise SystemExit(1)
    InstallerApp().run()
