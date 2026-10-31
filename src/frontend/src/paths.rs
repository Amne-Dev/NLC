use std::path::PathBuf;

/// Returns the primary user home directory across platforms
pub fn get_user_home() -> PathBuf {
    #[cfg(windows)]
    {
        if let Ok(userprofile) = std::env::var("USERPROFILE") {
            if !userprofile.is_empty() {
                return PathBuf::from(userprofile);
            }
        }
    }
    if let Ok(home) = std::env::var("HOME") {
        if !home.is_empty() {
            return PathBuf::from(home);
        }
    }
    PathBuf::from(".")
}

/// Returns the root data directory for Ny-Luna Core (`.nlc`)
pub fn get_launcher_data_dir() -> PathBuf {
    #[cfg(windows)]
    {
        if let Ok(appdata) = std::env::var("APPDATA") {
            if !appdata.is_empty() {
                return PathBuf::from(appdata).join(".nlc");
            }
        }
    }
    get_user_home().join(".nlc")
}

/// Returns the primary .minecraft directory
pub fn get_minecraft_dir() -> PathBuf {
    #[cfg(windows)]
    {
        if let Ok(appdata) = std::env::var("APPDATA") {
            if !appdata.is_empty() {
                return PathBuf::from(appdata).join(".minecraft");
            }
        }
    }
    get_user_home().join(".minecraft")
}

/// Returns the path to the main launcher config file
pub fn get_config_path() -> PathBuf {
    get_launcher_data_dir().join("launcher_config.json")
}

/// Returns the directory for modpack instances
pub fn get_modpacks_dir() -> PathBuf {
    get_launcher_data_dir().join("modpacks")
}

/// Returns the persistent cache directory
pub fn get_cache_dir() -> PathBuf {
    get_launcher_data_dir().join("cache")
}

/// Returns the cache icons directory
pub fn get_cache_icons_dir() -> PathBuf {
    get_cache_dir().join("icons")
}

/// Returns the addons directory
pub fn get_addons_dir() -> PathBuf {
    get_launcher_data_dir().join("addons")
}

