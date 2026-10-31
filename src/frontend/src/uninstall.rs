#[cfg(target_os = "linux")]
use std::io::{self, Write};
#[cfg(target_os = "linux")]
use std::path::PathBuf;
use std::process::Command;

pub fn handle_uninstall_cli() {
    #[cfg(target_os = "linux")]
    {
        run_linux_uninstall();
    }
    #[cfg(target_os = "windows")]
    {
        run_windows_uninstall();
    }
    #[cfg(not(any(target_os = "linux", target_os = "windows")))]
    {
        println!("The --uninstall command is only supported on Linux and Windows.");
        std::process::exit(1);
    }
}

#[cfg(target_os = "windows")]
fn run_windows_uninstall() {
    println!("============================================================");
    println!("          Ny-Luna Core (NLC) - Windows Uninstaller          ");
    println!("============================================================");
    println!();

    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()));

    if let Some(dir) = exe_dir {
        let uninst_exe = dir.join("uninstall.exe");
        if uninst_exe.exists() {
            println!("Launching dedicated Windows uninstaller: {:?}", uninst_exe);
            let status = Command::new(&uninst_exe)
                .arg("--uninstall")
                .arg("--target")
                .arg(&dir)
                .status();
            match status {
                Ok(s) => std::process::exit(s.code().unwrap_or(0)),
                Err(e) => {
                    eprintln!("Failed to launch uninstaller: {}", e);
                }
            }
        }
    }

    println!("To uninstall Ny-Luna on Windows:");
    println!("  • Open Windows Settings -> Installed apps -> Search 'Ny-Luna' -> Uninstall");
    println!("  • Or run 'uninstall.exe' in your installation folder.");
    println!();
    std::process::exit(0);
}

#[cfg(target_os = "linux")]
fn run_linux_uninstall() {
    println!("============================================================");
    println!("           Ny-Luna Core (NLC) - Linux Uninstaller           ");
    println!("============================================================");
    println!();
    println!("This will uninstall Ny-Luna Core from your system:");
    println!("  • Desktop entries & application menu shortcuts");
    println!("  • Application icons and pixmaps");
    println!("  • Wrapper scripts (/usr/local/bin/nlc, /usr/local/bin/newlauncher)");
    println!("  • Installed application files (/opt/new-launcher)");
    println!();

    print!("Are you sure you want to proceed with uninstallation? [y/N]: ");
    let _ = io::stdout().flush();

    let mut response = String::new();
    if io::stdin().read_line(&mut response).is_err() {
        println!("\nFailed to read input. Uninstallation cancelled.");
        std::process::exit(1);
    }

    let trimmed = response.trim().to_lowercase();
    if trimmed != "y" && trimmed != "yes" {
        println!("Uninstallation cancelled.");
        std::process::exit(0);
    }

    println!();
    print!("Do you also want to remove personal data, instances, and configurations (~/.nlc)? [y/N]: ");
    let _ = io::stdout().flush();

    let mut purge_response = String::new();
    let purge_data = if io::stdin().read_line(&mut purge_response).is_ok() {
        let p = purge_response.trim().to_lowercase();
        p == "y" || p == "yes"
    } else {
        false
    };

    extern "C" {
        fn geteuid() -> u32;
    }
    let is_root = unsafe { geteuid() == 0 };

    let run_cmd = |cmd: &str, args: &[&str]| -> bool {
        let mut process = if !is_root {
            let mut c = Command::new("sudo");
            c.arg(cmd);
            c.args(args);
            c
        } else {
            let mut c = Command::new(cmd);
            c.args(args);
            c
        };
        process.status().map(|s| s.success()).unwrap_or(false)
    };

    println!("\n[*] Removing system files and shortcuts...");

    // Remove binary wrapper links
    run_cmd("rm", &["-f", "/usr/local/bin/nlc", "/usr/local/bin/newlauncher"]);

    // Remove system desktop entries
    run_cmd(
        "rm",
        &[
            "-f",
            "/usr/share/applications/nlc.desktop",
            "/usr/share/applications/NewLauncher.desktop",
        ],
    );

    // Remove pixmaps
    run_cmd(
        "rm",
        &[
            "-f",
            "/usr/share/pixmaps/nlc.png",
            "/usr/share/pixmaps/newlauncher.png",
            "/usr/share/pixmaps/NewLauncher.png",
        ],
    );

    // Remove system icons
    let sizes = [
        "16x16", "22x22", "24x24", "32x32", "48x48", "64x64", "128x128", "256x256", "scalable",
    ];
    for sz in sizes {
        let p1 = format!("/usr/share/icons/hicolor/{}/apps/nlc.png", sz);
        let p2 = format!("/usr/share/icons/hicolor/{}/apps/newlauncher.png", sz);
        let p3 = format!("/usr/share/icons/hicolor/{}/apps/NewLauncher.png", sz);
        run_cmd("rm", &["-f", &p1, &p2, &p3]);
    }

    // Remove /opt/new-launcher directory
    run_cmd("rm", &["-rf", "/opt/new-launcher"]);

    // Remove user-level desktop shortcuts & icons
    let home = crate::paths::get_user_home();
    let user_apps = home.join(".local/share/applications");
    let _ = std::fs::remove_file(user_apps.join("nlc.desktop"));
    let _ = std::fs::remove_file(user_apps.join("NewLauncher.desktop"));

    for sz in sizes {
        let user_icons = home.join(format!(".local/share/icons/hicolor/{}/apps", sz));
        let _ = std::fs::remove_file(user_icons.join("nlc.png"));
        let _ = std::fs::remove_file(user_icons.join("newlauncher.png"));
        let _ = std::fs::remove_file(user_icons.join("NewLauncher.png"));
    }

    // Optional user data purge
    if purge_data {
        let nlc_dir = crate::paths::get_launcher_data_dir();
        if nlc_dir.exists() {
            println!("[*] Removing user data directory: {:?}", nlc_dir);
            let _ = std::fs::remove_dir_all(&nlc_dir);
        }
    }

    // Check for standalone AppImage
    if let Ok(appimage_path) = std::env::var("APPIMAGE") {
        let p = PathBuf::from(&appimage_path);
        if p.exists() && !p.starts_with("/opt/new-launcher") {
            println!("\nCurrent AppImage file detected at: {}", appimage_path);
            print!("Do you want to delete this standalone AppImage file as well? [y/N]: ");
            let _ = io::stdout().flush();
            let mut app_resp = String::new();
            if io::stdin().read_line(&mut app_resp).is_ok() {
                let trimmed = app_resp.trim().to_lowercase();
                if trimmed == "y" || trimmed == "yes" {
                    if let Err(e) = std::fs::remove_file(&p) {
                        eprintln!("Warning: Could not remove {}: {}", appimage_path, e);
                    } else {
                        println!("Deleted: {}", appimage_path);
                    }
                }
            }
        }
    }

    // Refresh system and user caches
    println!("[*] Updating desktop and icon caches...");
    let _ = run_cmd("update-desktop-database", &["/usr/share/applications"]);
    let _ = run_cmd("gtk-update-icon-cache", &["-f", "-t", "/usr/share/icons/hicolor"]);
    let _ = Command::new("kbuildsycoca6").arg("--noincremental").output();
    let _ = Command::new("kbuildsycoca5").arg("--noincremental").output();

    if user_apps.exists() {
        let _ = Command::new("update-desktop-database").arg(&user_apps).output();
    }

    println!();
    println!("============================================================");
    println!(" ✓ Ny-Luna Core has been successfully uninstalled.          ");
    println!("============================================================");
    std::process::exit(0);
}

