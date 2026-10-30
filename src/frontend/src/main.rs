#![windows_subsystem = "windows"]

slint::include_modules!();

mod ipc;
mod animations;
mod paths;
mod dialogs;

use ipc::AgentClient;
use slint::{ComponentHandle, Model};
use std::path::PathBuf;
use std::sync::Arc;

pub fn load_image_safely(path: &std::path::Path) -> Option<slint::Image> {
    if !path.exists() {
        return None;
    }
    let bytes = std::fs::read(path).ok()?;
    let dyn_img = image::load_from_memory(&bytes).ok()?;
    let rgba = dyn_img.to_rgba8();
    let (width, height) = rgba.dimensions();
    if width == 0 || height == 0 {
        return None;
    }
    let mut buffer = slint::SharedPixelBuffer::<slint::Rgba8Pixel>::new(width, height);
    buffer.make_mut_bytes().copy_from_slice(rgba.as_raw());
    Some(slint::Image::from_rgba8(buffer))
}

fn resolve_icon_path(icon_name: &str, project_root: &std::path::Path) -> std::path::PathBuf {
    if icon_name.is_empty() {
        return project_root.join("icons").join("2x").join("grass_block_side.png");
    }
    let p = std::path::Path::new(icon_name);
    if p.is_absolute() && p.exists() {
        return p.to_path_buf();
    }
    let direct = project_root.join(icon_name);
    if direct.exists() {
        return direct;
    }
    let in_icons = project_root.join("icons").join(icon_name);
    if in_icons.exists() {
        return in_icons;
    }
    let in_2x = project_root.join("icons").join("2x").join(icon_name);
    if in_2x.exists() {
        return in_2x;
    }
    let with_png = project_root.join("icons").join(format!("{}.png", icon_name));
    if with_png.exists() {
        return with_png;
    }
    let with_png_2x = project_root.join("icons").join("2x").join(format!("{}.png", icon_name));
    if with_png_2x.exists() {
        return with_png_2x;
    }

    let nlc_base = paths::get_launcher_data_dir();
    let mp_path = nlc_base.join("modpacks").join(icon_name);
    if mp_path.exists() {
        return mp_path;
    }
    let mp_icon = nlc_base.join("modpacks").join(icon_name).join("icon.png");
    if mp_icon.exists() {
        return mp_icon;
    }
    let cache_icon = nlc_base.join("cache").join("icons").join(icon_name);
    if cache_icon.exists() {
        return cache_icon;
    }
    let cache_icon_png = nlc_base.join("cache").join("icons").join(format!("{}.png", icon_name));
    if cache_icon_png.exists() {
        return cache_icon_png;
    }

    project_root.join("icons").join("2x").join("grass_block_side.png")
}

fn prompt_open_file(filter: &str) -> Option<String> {
    dialogs::prompt_open_file(filter)
}

fn prompt_save_file(default_name: &str, filter: &str) -> Option<String> {
    dialogs::prompt_save_file(default_name, filter)
}

fn prompt_open_folder() -> Option<String> {
    dialogs::prompt_open_folder()
}

fn map_installation(item: &ipc::InstallationItem, root_dir: &std::path::Path) -> InstallationData {
    let mut resolved_path: Option<std::path::PathBuf> = None;
    if let Some(ref icon_raw) = item.icon {
        if !icon_raw.is_empty() && !icon_raw.contains("grass_block") {
            let p = resolve_icon_path(icon_raw, root_dir);
            if p.exists() {
                resolved_path = Some(p);
            }
        }
    }
    if resolved_path.is_none() {
        if let Some(ref gd) = item.game_directory {
            if !gd.is_empty() {
                let p = std::path::Path::new(gd).join("icon.png");
                if p.exists() {
                    resolved_path = Some(p);
                }
            }
        }
    }
    if resolved_path.is_none() && item.id.starts_with("inst-") {
        let pack_id = item.id.trim_start_matches("inst-");
        let p = paths::get_modpacks_dir().join(pack_id).join("icon.png");
        if p.exists() {
            resolved_path = Some(p);
        }
    }
    let icon_raw = item.icon.as_deref().unwrap_or("grass_block_side.png");
    let icon_path = resolved_path.clone().unwrap_or_else(|| resolve_icon_path(icon_raw, root_dir));
    let img = load_image_safely(&icon_path).unwrap_or_default();
    let is_snap = item.r#type.as_deref() == Some("snapshot")
        || item.version.to_lowercase().contains("snapshot")
        || item.version.contains("w");
    let is_mod = item.r#type.as_deref() == Some("modded")
        || item.loader.as_deref().map(|l| l.to_lowercase()).map_or(false, |l| l != "vanilla")
        || item.version.to_lowercase().contains("fabric")
        || item.version.to_lowercase().contains("forge");
    InstallationData {
        id: item.id.clone().into(),
        name: item.name.clone().into(),
        version: item.version.clone().into(),
        loader: item.loader.clone().unwrap_or_else(|| "Vanilla".to_string()).into(),
        icon: img,
        icon_name: resolved_path.map(|p| p.to_string_lossy().to_string()).unwrap_or_else(|| icon_raw.to_string()).into(),
        last_played: item.last_played.clone().unwrap_or_else(|| "Never".to_string()).into(),
        created: item.created.clone().unwrap_or_else(|| "2026-10-12".to_string()).into(),
        is_snapshot: is_snap,
        is_modded: is_mod,
        java_path: item.java_executable.clone().unwrap_or_default().into(),
        jvm_args: item.jvm_arguments.clone().unwrap_or_default().into(),
        resolution_w: item.resolution_width.unwrap_or(854),
        resolution_h: item.resolution_height.unwrap_or(480),
        game_dir: item.game_directory.clone().unwrap_or_default().into(),
        ram_mb: item.max_ram_mb.map(|r| r as i32).unwrap_or(0),
    }
}

fn map_installation_choice(item: &ipc::InstallationItem) -> InstallationChoice {
    let loader = item.loader.clone().unwrap_or_else(|| "Vanilla".to_string());
    let is_compat = loader.to_lowercase() != "vanilla" || item.version.contains("26.2") || item.version.contains("1.21");
    InstallationChoice {
        id: item.id.clone().into(),
        name: item.name.clone().into(),
        version: item.version.clone().into(),
        loader: loader.into(),
        is_compatible: is_compat,
    }
}

fn format_account_type(raw: &str) -> &'static str {
    let lower = raw.to_lowercase();
    if lower == "microsoft" {
        "Microsoft Account"
    } else if lower == "ely.by" || lower == "elyby" {
        "Ely.by Account"
    } else {
        "Offline"
    }
}

struct LocalCapeItem {
    id: String,
    alias: String,
    local_path: String,
    thumb_path: String,
    is_equipped: bool,
}

async fn refresh_locker_capes(agent: &ipc::AgentClient, win_weak: slint::Weak<MainWindow>) {
    let capes_data: Vec<serde_json::Value> = agent
        .call("capes_list", serde_json::json!({}))
        .await
        .unwrap_or_default();

    let items: Vec<LocalCapeItem> = capes_data
        .iter()
        .map(|c| {
            let id = c.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
            let alias = c.get("alias").and_then(|v| v.as_str()).unwrap_or("Cape").to_string();
            let local_p = c.get("local_path").and_then(|v| v.as_str()).unwrap_or("").to_string();
            let thumb_p = c.get("thumb_path").and_then(|v| v.as_str()).unwrap_or("").to_string();
            let is_eq = c.get("state").and_then(|v| v.as_str()).map(|s| s == "ACTIVE").unwrap_or(false);

            LocalCapeItem {
                id,
                alias,
                local_path: local_p,
                thumb_path: thumb_p,
                is_equipped: is_eq,
            }
        })
        .collect();
    let any_equipped = items.iter().any(|c| c.is_equipped);

    let _ = slint::invoke_from_event_loop(move || {
        if let Some(w) = win_weak.upgrade() {
            w.set_locker_has_active_cape(any_equipped);
            let slint_capes: Vec<CapeData> = items
                .into_iter()
                .map(|it| {
                    let preview_path = if !it.thumb_path.is_empty() && std::path::Path::new(&it.thumb_path).exists() {
                        &it.thumb_path
                    } else {
                        &it.local_path
                    };

                    let (has_prev, img) = if !preview_path.is_empty() && std::path::Path::new(preview_path).exists() {
                        (true, load_image_safely(std::path::Path::new(preview_path)).unwrap_or_default())
                    } else {
                        (false, slint::Image::default())
                    };

                    CapeData {
                        id: it.id.into(),
                        alias: it.alias.into(),
                        local_path: it.local_path.into(),
                        thumb_path: it.thumb_path.into(),
                        has_preview: has_prev,
                        preview: img,
                        is_equipped: it.is_equipped,
                    }
                })
                .collect();
            w.set_locker_capes(std::rc::Rc::new(slint::VecModel::from(slint_capes)).into());
        }
    });
}

struct LocalPresetItem {
    id: String,
    name: String,
    path: String,
    model: String,
    thumb_path: String,
    is_equipped: bool,
}

struct LocalWallpaperItem {
    id: String,
    name: String,
    path: String,
    thumb_path: String,
    is_equipped: bool,
    is_downloaded: bool,
    size_text: String,
}

async fn refresh_locker_presets(agent: &ipc::AgentClient, win_weak: slint::Weak<MainWindow>) {
    let res: Result<serde_json::Value, _> = agent.call("skin_presets_list", serde_json::json!({})).await;
    let mut items: Vec<LocalPresetItem> = Vec::new();
    if let Ok(data) = res {
        if let Some(arr) = data.get("presets").and_then(|v| v.as_array()) {
            for item in arr {
                let id = item.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let name = item.get("name").and_then(|v| v.as_str()).unwrap_or("Skin").to_string();
                let path = item.get("path").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let model = item.get("model").and_then(|v| v.as_str()).unwrap_or("classic").to_string();
                let thumb_path = item.get("thumb_path").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let is_equipped = item.get("is_equipped").and_then(|v| v.as_bool()).unwrap_or(false);
                items.push(LocalPresetItem {
                    id,
                    name,
                    path,
                    model,
                    thumb_path,
                    is_equipped,
                });
            }
        }
    }

    let _ = slint::invoke_from_event_loop(move || {
        if let Some(w) = win_weak.upgrade() {
            let presets: Vec<SkinPresetData> = items.into_iter().map(|it| {
                let (has_thumb, thumb_img) = if !it.thumb_path.is_empty() && std::path::Path::new(&it.thumb_path).exists() {
                    (true, load_image_safely(std::path::Path::new(&it.thumb_path)).unwrap_or_default())
                } else {
                    (false, slint::Image::default())
                };
                SkinPresetData {
                    id: it.id.into(),
                    name: it.name.into(),
                    model: it.model.into(),
                    path: it.path.into(),
                    has_thumbnail: has_thumb,
                    thumbnail: thumb_img,
                    is_equipped: it.is_equipped,
                }
            }).collect();
            w.set_locker_presets(std::rc::Rc::new(slint::VecModel::from(presets)).into());
        }
    });
}

async fn refresh_wallpapers_roster(agent: &ipc::AgentClient, win_weak: slint::Weak<MainWindow>) {
    let res: Result<serde_json::Value, _> = agent.call("wallpapers_list", serde_json::json!({})).await;
    let mut items: Vec<LocalWallpaperItem> = Vec::new();
    let mut equipped_path: Option<String> = None;
    if let Ok(data) = res {
        if let Some(arr) = data.get("wallpapers").and_then(|v| v.as_array()) {
            for item in arr {
                let id = item.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let name = item.get("name").and_then(|v| v.as_str()).unwrap_or("Wallpaper").to_string();
                let path = item.get("path").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let thumb_path = item.get("thumb_path").and_then(|v| v.as_str()).unwrap_or("").to_string();
                let is_eq = item.get("is_equipped").and_then(|v| v.as_bool()).unwrap_or(false);
                let is_dl = item.get("is_downloaded").and_then(|v| v.as_bool()).unwrap_or(!path.is_empty());
                let size_text = item.get("size_text").and_then(|v| v.as_str()).unwrap_or("2.5 MB").to_string();
                if is_eq && !path.is_empty() {
                    equipped_path = Some(path.clone());
                }
                items.push(LocalWallpaperItem {
                    id,
                    name,
                    path,
                    thumb_path,
                    is_equipped: is_eq,
                    is_downloaded: is_dl,
                    size_text,
                });
            }
        }
    }

    let win_for_eq = win_weak.clone();
    let _ = slint::invoke_from_event_loop(move || {
        if let Some(w) = win_weak.upgrade() {
            let slint_wallpapers: Vec<WallpaperData> = items.into_iter().map(|it| {
                let preview_file = if !it.thumb_path.is_empty() && std::path::Path::new(&it.thumb_path).exists() {
                    &it.thumb_path
                } else {
                    &it.path
                };
                let (has_prev, img) = if !preview_file.is_empty() && std::path::Path::new(preview_file).exists() {
                    (true, load_image_safely(std::path::Path::new(preview_file)).unwrap_or_default())
                } else {
                    (false, slint::Image::default())
                };
                WallpaperData {
                    id: it.id.into(),
                    name: it.name.into(),
                    path: it.path.into(),
                    has_preview: has_prev,
                    preview: img,
                    is_equipped: it.is_equipped,
                    is_downloaded: it.is_downloaded,
                    is_downloading: false,
                    size_text: it.size_text.into(),
                }
            }).collect();
            w.set_locker_wallpapers(std::rc::Rc::new(slint::VecModel::from(slint_wallpapers)).into());
        }
    });

    if let Some(eq_p) = equipped_path {
        let _ = slint::invoke_from_event_loop(move || {
            if let Some(w) = win_for_eq.upgrade() {
                let p = std::path::Path::new(&eq_p);
                if p.exists() {
                    if let Some(full_img) = load_image_safely(p) {
                        w.set_current_wallpaper_image(full_img);
                        w.set_has_current_wallpaper(true);
                    }
                }
            }
        });
    }
}

struct LocalScreenshotItem {
    id: String,
    name: String,
    date: String,
    path: String,
}

async fn refresh_screenshots_gallery(agent: Option<&ipc::AgentClient>, root_dir: &std::path::Path, win_weak: slint::Weak<MainWindow>) {
    let mut items: Vec<LocalScreenshotItem> = Vec::new();

    if let Some(ag) = agent {
        if let Ok(resp) = ag.list_screenshots(None).await {
            for sc in resp.items {
                items.push(LocalScreenshotItem {
                    id: sc.path.clone(),
                    name: sc.name,
                    date: if sc.date.is_empty() { "Recent".to_string() } else { sc.date },
                    path: sc.path,
                });
            }
        }
    }

    if items.is_empty() {
        let mut paths_to_scan = Vec::new();
        let mc_sc = paths::get_minecraft_dir().join("screenshots");
        if mc_sc.exists() {
            paths_to_scan.push(mc_sc);
        }
        let nlc_packs = paths::get_modpacks_dir();
        if let Ok(entries) = std::fs::read_dir(&nlc_packs) {
            for e in entries.flatten() {
                let sc = e.path().join("screenshots");
                if sc.exists() {
                    paths_to_scan.push(sc);
                }
            }
        }
        let cfg_path = paths::get_config_path();
        if let Ok(content) = std::fs::read_to_string(&cfg_path) {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&content) {
                if let Some(insts) = val.get("installations").and_then(|i| i.as_array()) {
                    for inst in insts {
                        if let Some(g_dir) = inst.get("game_directory").and_then(|g| g.as_str()) {
                            let sc = std::path::PathBuf::from(g_dir).join("screenshots");
                            if sc.exists() {
                                paths_to_scan.push(sc);
                            }
                        }
                    }
                }
            }
        }
        let local_sc = root_dir.join("screenshots");
        if local_sc.exists() {
            paths_to_scan.push(local_sc);
        }

        let mut seen = std::collections::HashSet::new();
        for dir in paths_to_scan {
            if let Ok(entries) = std::fs::read_dir(dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.extension().and_then(|e| e.to_str()).map(|e| e.eq_ignore_ascii_case("png") || e.eq_ignore_ascii_case("jpg")).unwrap_or(false) {
                        let path_str = path.to_string_lossy().to_string();
                        if seen.insert(path_str.to_lowercase()) {
                            let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("screenshot.png").to_string();
                            let date = entry.metadata().and_then(|m| m.modified()).map(|t| {
                                let dur = t.duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_secs();
                                format!("{}s ago", (std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_secs().saturating_sub(dur)))
                            }).unwrap_or_else(|_| "Recent".to_string());
                            items.push(LocalScreenshotItem {
                                id: path_str.clone(),
                                name,
                                date,
                                path: path_str,
                            });
                            if items.len() >= 50 {
                                break;
                            }
                        }
                    }
                }
            }
        }
    }

    let _ = slint::invoke_from_event_loop(move || {
        if let Some(w) = win_weak.upgrade() {
            let cards: Vec<ScreenshotCardData> = items.into_iter().map(|it| {
                let preview = load_image_safely(std::path::Path::new(&it.path)).unwrap_or_default();
                ScreenshotCardData {
                    id: it.id.into(),
                    name: it.name.into(),
                    date: it.date.into(),
                    path: it.path.into(),
                    preview,
                }
            }).collect();
            w.set_screenshots(std::rc::Rc::new(slint::VecModel::from(cards)).into());
        }
    });
}

fn sync_modrinth_destinations(w: &MainWindow, modpacks: &[ModpackData]) {
    let mut dests: Vec<slint::SharedString> = vec!["Global (.minecraft)".into()];
    if !modpacks.is_empty() {
        for mp in modpacks {
            if !mp.name.is_empty() && !dests.iter().any(|d| d.as_str() == mp.name.as_str()) {
                dests.push(mp.name.clone());
            }
        }
    } else {
        let packs = w.get_modpacks();
        for i in 0..packs.row_count() {
            if let Some(mp) = packs.row_data(i) {
                if !mp.name.is_empty() && !dests.iter().any(|d| d.as_str() == mp.name.as_str()) {
                    dests.push(mp.name.clone());
                }
            }
        }
    }

    let installs = w.get_installations();
    for i in 0..installs.row_count() {
        if let Some(inst) = installs.row_data(i) {
            let loader_lower = inst.loader.to_lowercase();
            let is_modded = inst.is_modded
                || (!inst.loader.is_empty() && loader_lower != "vanilla");
            if is_modded && !inst.name.is_empty() && !dests.iter().any(|d| d.as_str() == inst.name.as_str()) {
                dests.push(inst.name.clone());
            }
        }
    }
    w.set_modrinth_destinations(std::rc::Rc::new(slint::VecModel::from(dests)).into());
}

struct ThemePalette {
    main_bg: &'static str,
    card_bg: &'static str,
    card_hover: &'static str,
    sidebar_bg: &'static str,
    bottom_bar_bg: &'static str,
    titlebar_bg: &'static str,
    input_bg: &'static str,
    border: &'static str,
    default_accent: &'static str,
}

pub fn hex_to_rgb(hex: &str) -> Option<(u8, u8, u8)> {
    let s = hex.trim().trim_start_matches('#').trim_start_matches("0x").trim_start_matches("0X");
    if !s.is_ascii() {
        return None;
    }
    if s.len() == 6 || s.len() == 8 {
        let r = u8::from_str_radix(&s[0..2], 16).ok()?;
        let g = u8::from_str_radix(&s[2..4], 16).ok()?;
        let b = u8::from_str_radix(&s[4..6], 16).ok()?;
        Some((r, g, b))
    } else if s.len() == 3 {
        let r = u8::from_str_radix(&s[0..1], 16).ok()? * 17;
        let g = u8::from_str_radix(&s[1..2], 16).ok()? * 17;
        let b = u8::from_str_radix(&s[2..3], 16).ok()? * 17;
        Some((r, g, b))
    } else {
        None
    }
}

fn parse_hex_color(hex: &str) -> Option<slint::Color> {
    hex_to_rgb(hex).map(|(r, g, b)| slint::Color::from_argb_u8(255, r, g, b))
}

pub(crate) fn validate_minecraft_username(username: &str) -> Result<(), &'static str> {
    let trimmed = username.trim();
    if trimmed.is_empty() {
        return Err("Username cannot be empty");
    }
    if trimmed.len() < 3 {
        return Err("Username must be at least 3 characters");
    }
    if trimmed.len() > 16 {
        return Err("Username cannot exceed 16 characters");
    }
    if !trimmed.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
        return Err("Username can only contain letters, numbers, and underscores (_)");
    }
    Ok(())
}

fn lerp_rgb(c1: (u8, u8, u8), c2: (u8, u8, u8), t: f32) -> (u8, u8, u8) {
    let r = (c1.0 as f32 * (1.0 - t) + c2.0 as f32 * t).round().clamp(0.0, 255.0) as u8;
    let g = (c1.1 as f32 * (1.0 - t) + c2.1 as f32 * t).round().clamp(0.0, 255.0) as u8;
    let b = (c1.2 as f32 * (1.0 - t) + c2.2 as f32 * t).round().clamp(0.0, 255.0) as u8;
    (r, g, b)
}

fn relative_luminance(rgb: (u8, u8, u8)) -> f32 {
    let srgb_to_lin = |c_int: u8| -> f32 {
        let c = c_int as f32 / 255.0;
        if c <= 0.04045 {
            c / 12.92
        } else {
            ((c + 0.055) / 1.055).powf(2.4)
        }
    };
    0.2126 * srgb_to_lin(rgb.0) + 0.7152 * srgb_to_lin(rgb.1) + 0.0722 * srgb_to_lin(rgb.2)
}

fn derive_hover_color(rgb: (u8, u8, u8)) -> (u8, u8, u8) {
    let lum = relative_luminance(rgb);
    let target = if lum > 0.5 { (0, 0, 0) } else { (255, 255, 255) };
    lerp_rgb(rgb, target, 0.16)
}

fn derive_contrast_text(rgb: (u8, u8, u8)) -> slint::Color {
    let lum = relative_luminance(rgb);
    if lum > 0.42 {
        slint::Color::from_argb_u8(255, 0x12, 0x13, 0x16)
    } else {
        slint::Color::from_argb_u8(255, 255, 255, 255)
    }
}

fn get_theme_palette(name: &str) -> ThemePalette {
    let normalized = name.to_lowercase().replace([' ', '-'], "_");
    if normalized.contains("obsidian") || normalized.contains("oled") {
        ThemePalette {
            main_bg: "#0A0A0A",
            card_bg: "#141414",
            card_hover: "#1F1F1F",
            sidebar_bg: "#000000",
            bottom_bar_bg: "#050505",
            titlebar_bg: "#000000",
            input_bg: "#181818",
            border: "#222222",
            default_accent: "#00E5FF",
        }
    } else if normalized.contains("catppuccin") || normalized.contains("mocha") {
        ThemePalette {
            main_bg: "#1E1E2E",
            card_bg: "#28283D",
            card_hover: "#313244",
            sidebar_bg: "#181825",
            bottom_bar_bg: "#181825",
            titlebar_bg: "#11111B",
            input_bg: "#313244",
            border: "#36374D",
            default_accent: "#CBA6F7",
        }
    } else if normalized.contains("nord") || normalized.contains("frost") {
        ThemePalette {
            main_bg: "#2E3440",
            card_bg: "#384152",
            card_hover: "#434C5E",
            sidebar_bg: "#242933",
            bottom_bar_bg: "#242933",
            titlebar_bg: "#1E222A",
            input_bg: "#3B4252",
            border: "#3B4252",
            default_accent: "#88C0D0",
        }
    } else if normalized.contains("dracula") || normalized.contains("midnight") {
        ThemePalette {
            main_bg: "#282A36",
            card_bg: "#343746",
            card_hover: "#44475A",
            sidebar_bg: "#1E1F29",
            bottom_bar_bg: "#1E1F29",
            titlebar_bg: "#14151C",
            input_bg: "#44475A",
            border: "#3A3D4E",
            default_accent: "#BD93F9",
        }
    } else if normalized.contains("emerald") || normalized.contains("pine") {
        ThemePalette {
            main_bg: "#162119",
            card_bg: "#1F2E23",
            card_hover: "#2A3C2F",
            sidebar_bg: "#101712",
            bottom_bar_bg: "#101712",
            titlebar_bg: "#0B100C",
            input_bg: "#223326",
            border: "#253629",
            default_accent: "#27AE60",
        }
    } else {
        // Default: Dark Slate
        ThemePalette {
            main_bg: "#1E2025",
            card_bg: "#242830",
            card_hover: "#2C313C",
            sidebar_bg: "#181A1E",
            bottom_bar_bg: "#181A1E",
            titlebar_bg: "#121316",
            input_bg: "#2E333E",
            border: "#2B303A",
            default_accent: "#2ECC71",
        }
    }
}


pub fn generate_dynamic_chevron_icon(accent_rgb: (u8, u8, u8), size: u32) -> Option<slint::Image> {
    if size == 0 {
        return None;
    }
    let mut buffer = slint::SharedPixelBuffer::<slint::Rgba8Pixel>::new(size, size);
    let bytes = buffer.make_mut_bytes();

    let upper_outer: [(f32, f32); 4] = [(420.0, 220.0), (580.0, 220.0), (720.0, 512.0), (610.0, 512.0)];
    let lower_outer: [(f32, f32); 4] = [(610.0, 540.0), (720.0, 540.0), (580.0, 804.0), (420.0, 804.0)];
    let upper_inner: [(f32, f32); 4] = [(340.0, 380.0), (450.0, 380.0), (520.0, 512.0), (430.0, 512.0)];
    let lower_inner: [(f32, f32); 4] = [(430.0, 528.0), (520.0, 528.0), (450.0, 644.0), (340.0, 644.0)];

    let point_in_quad = |p: (f32, f32), quad: &[(f32, f32); 4]| -> bool {
        let mut sign = 0;
        for i in 0..4 {
            let p1 = quad[i];
            let p2 = quad[(i + 1) % 4];
            let cross = (p2.0 - p1.0) * (p.1 - p1.1) - (p2.1 - p1.1) * (p.0 - p1.0);
            if cross.abs() > 1e-4 {
                let s = if cross > 0.0 { 1 } else { -1 };
                if sign == 0 {
                    sign = s;
                } else if sign != s {
                    return false;
                }
            }
        }
        true
    };

    let sz_f = size as f32;
    for y in 0..size {
        for x in 0..size {
            let mut white_hits = 0;
            let mut accent_hits = 0;
            let sub_offsets = [(0.25f32, 0.25f32), (0.75f32, 0.25f32), (0.25f32, 0.75f32), (0.75f32, 0.75f32)];
            for (ox, oy) in sub_offsets {
                let px = ((x as f32 + ox) / sz_f) * 1024.0;
                let py = ((y as f32 + oy) / sz_f) * 1024.0;
                if point_in_quad((px, py), &upper_outer) || point_in_quad((px, py), &lower_outer) {
                    white_hits += 1;
                } else if point_in_quad((px, py), &upper_inner) || point_in_quad((px, py), &lower_inner) {
                    accent_hits += 1;
                }
            }

            let idx = ((y * size + x) * 4) as usize;
            if white_hits > 0 {
                let alpha = ((white_hits as f32 / 4.0) * 255.0) as u8;
                bytes[idx] = 255;
                bytes[idx + 1] = 255;
                bytes[idx + 2] = 255;
                bytes[idx + 3] = alpha;
            } else if accent_hits > 0 {
                let alpha = ((accent_hits as f32 / 4.0) * 255.0) as u8;
                bytes[idx] = accent_rgb.0;
                bytes[idx + 1] = accent_rgb.1;
                bytes[idx + 2] = accent_rgb.2;
                bytes[idx + 3] = alpha;
            } else {
                bytes[idx] = 0;
                bytes[idx + 1] = 0;
                bytes[idx + 2] = 0;
                bytes[idx + 3] = 0;
            }
        }
    }
    Some(slint::Image::from_rgba8(buffer))
}

pub fn apply_theme_palette(win: &MainWindow, theme_name: &str, custom_accent_hex: Option<&str>) {
    let palette = get_theme_palette(theme_name);
    let theme = win.global::<Theme>();

    let accent_rgb = custom_accent_hex
        .and_then(|h| hex_to_rgb(h))
        .or_else(|| hex_to_rgb(palette.default_accent))
        .unwrap_or((0x2E, 0xCC, 0x71));

    if let Some(dyn_icon) = generate_dynamic_chevron_icon(accent_rgb, 64) {
        win.set_window_icon(dyn_icon);
    }
    if let Some(dyn_logo) = generate_dynamic_chevron_icon(accent_rgb, 256) {
        win.set_launcher_logo(dyn_logo);
    }

    let accent_color = slint::Color::from_argb_u8(255, accent_rgb.0, accent_rgb.1, accent_rgb.2);

    let hover_rgb = derive_hover_color(accent_rgb);
    let accent_hover_color = slint::Color::from_argb_u8(255, hover_rgb.0, hover_rgb.1, hover_rgb.2);

    let pressed_rgb = lerp_rgb(accent_rgb, (0, 0, 0), 0.2);
    let accent_pressed_color = slint::Color::from_argb_u8(255, pressed_rgb.0, pressed_rgb.1, pressed_rgb.2);

    let card_rgb = hex_to_rgb(palette.card_bg).unwrap_or((0x24, 0x28, 0x30));
    let subtle_rgb = lerp_rgb(card_rgb, accent_rgb, 0.18);
    let accent_subtle_color = slint::Color::from_argb_u8(255, subtle_rgb.0, subtle_rgb.1, subtle_rgb.2);

    let accent_text_color = derive_contrast_text(accent_rgb);

    if let Some(c) = parse_hex_color(palette.main_bg) {
        theme.set_main_bg(c);
    }
    if let Some(c) = parse_hex_color(palette.card_bg) {
        theme.set_card_bg(c);
    }
    if let Some(c) = parse_hex_color(palette.card_hover) {
        theme.set_card_hover(c);
    }
    if let Some(c) = parse_hex_color(palette.sidebar_bg) {
        theme.set_sidebar_bg(c);
    }
    if let Some(c) = parse_hex_color(palette.bottom_bar_bg) {
        theme.set_bottom_bar_bg(c);
    }
    if let Some(c) = parse_hex_color(palette.titlebar_bg) {
        theme.set_titlebar_bg(c);
    }
    if let Some(c) = parse_hex_color(palette.input_bg) {
        theme.set_input_bg(c);
    }
    if let Some(c) = parse_hex_color(palette.border) {
        theme.set_border(c);
        theme.set_border_subtle(c);
    }

    let sidebar_rgb = hex_to_rgb(palette.sidebar_bg).unwrap_or((0x14, 0x16, 0x19));
    let sidebar_hover_rgb = lerp_rgb(sidebar_rgb, card_rgb, 0.45);
    let sidebar_hover_color = slint::Color::from_argb_u8(255, sidebar_hover_rgb.0, sidebar_hover_rgb.1, sidebar_hover_rgb.2);
    let sidebar_active_rgb = card_rgb;
    let sidebar_active_color = slint::Color::from_argb_u8(255, sidebar_active_rgb.0, sidebar_active_rgb.1, sidebar_active_rgb.2);

    let border_rgb = hex_to_rgb(palette.border).unwrap_or((0x28, 0x2D, 0x37));
    let border_hover_rgb = lerp_rgb(border_rgb, accent_rgb, 0.45);
    let border_hover_color = slint::Color::from_argb_u8(255, border_hover_rgb.0, border_hover_rgb.1, border_hover_rgb.2);

    let button_dark_color = parse_hex_color(palette.card_bg).unwrap_or(accent_subtle_color);
    let button_dark_hover_color = parse_hex_color(palette.card_hover).unwrap_or(accent_color);

    theme.set_sidebar_hover(sidebar_hover_color);
    theme.set_sidebar_active(sidebar_active_color);
    theme.set_border_hover(border_hover_color);
    theme.set_button_dark(button_dark_color);
    theme.set_button_dark_hover(button_dark_hover_color);

    theme.set_border_focus(accent_color);
    theme.set_accent(accent_color);
    theme.set_accent_hover(accent_hover_color);
    theme.set_accent_pressed(accent_pressed_color);
    theme.set_accent_subtle(accent_subtle_color);
    theme.set_accent_text(accent_text_color);

    println!(
        "[NLC-Rust] Applied theme palette '{}' with accent #{:02X}{:02X}{:02X}",
        theme_name, accent_rgb.0, accent_rgb.1, accent_rgb.2
    );
}


#[cfg(windows)]
#[repr(C)]
struct MemoryStatusEx {
    dw_length: u32,
    dw_memory_load: u32,
    ull_total_phys: u64,
    ull_avail_phys: u64,
    ull_total_page_file: u64,
    ull_avail_page_file: u64,
    ull_total_virtual: u64,
    ull_avail_virtual: u64,
    ull_avail_extended_virtual: u64,
}

#[cfg(windows)]
#[link(name = "kernel32")]
extern "system" {
    fn GlobalMemoryStatusEx(lpBuffer: *mut MemoryStatusEx) -> i32;
}

pub fn detect_system_ram() -> (i32, String) {
    #[cfg(windows)]
    unsafe {
        let mut status: MemoryStatusEx = std::mem::zeroed();
        status.dw_length = std::mem::size_of::<MemoryStatusEx>() as u32;
        if GlobalMemoryStatusEx(&mut status) != 0 {
            let total_mb = (status.ull_total_phys / (1024 * 1024)) as i32;
            let total_gb = (status.ull_total_phys as f64) / (1024.0 * 1024.0 * 1024.0);
            return (
                total_mb,
                format!("Total Physical System Memory: {:.1} GB ({} MB)", total_gb, total_mb),
            );
        }
    }

    #[cfg(target_os = "linux")]
    {
        if let Ok(meminfo) = std::fs::read_to_string("/proc/meminfo") {
            for line in meminfo.lines() {
                if line.starts_with("MemTotal:") {
                    let parts: Vec<&str> = line.split_whitespace().collect();
                    if parts.len() >= 2 {
                        if let Ok(kb) = parts[1].parse::<u64>() {
                            let total_mb = (kb / 1024) as i32;
                            let total_gb = (kb as f64) / (1024.0 * 1024.0);
                            return (
                                total_mb,
                                format!("Total Physical System Memory: {:.1} GB ({} MB)", total_gb, total_mb),
                            );
                        }
                    }
                }
            }
        }
    }

    (8192, "Total Physical System Memory: 8.0 GB (8192 MB)".to_string())
}

fn sync_settings_to_ui(cfg: &ipc::LauncherConfig, win: &MainWindow) {
    if let Some(ref ver) = cfg.version {
        win.set_selected_version(ver.clone().into());
    }
    let theme_name = if let Some(ref theme) = cfg.theme_id {
        win.set_selected_theme(theme.clone().into());
        theme.clone()
    } else if let Some(theme) = cfg.extra.get("theme").and_then(|v| v.as_str()) {
        win.set_selected_theme(theme.into());
        theme.to_string()
    } else {
        "Dark Slate".to_string()
    };

    let custom_hex = if let Some(ref hex) = cfg.custom_accent {
        win.set_custom_hex(hex.clone().into());
        Some(hex.clone())
    } else if let Some(hex) = cfg.extra.get("custom_hex").or_else(|| cfg.extra.get("accent_color")).and_then(|v| v.as_str()) {
        win.set_custom_hex(hex.into());
        Some(hex.to_string())
    } else {
        None
    };

    apply_theme_palette(win, &theme_name, custom_hex.as_deref());

    if let Some(anim) = cfg.animations_enabled {
        win.set_smooth_animations(anim);
        win.global::<Theme>().set_smooth_animations(anim);
    } else if let Some(anim) = cfg.extra.get("smooth_animations").and_then(|v| v.as_bool()) {
        win.set_smooth_animations(anim);
        win.global::<Theme>().set_smooth_animations(anim);
    }

    if let Some(walk) = cfg.enable_walking_mobs {
        win.set_enable_walking_mobs(walk);
    } else if let Some(walk) = cfg.extra.get("enable_walking_mobs").and_then(|v| v.as_bool()) {
        win.set_enable_walking_mobs(walk);
    }

    if let Some(streamer) = cfg.streamer_mode {
        win.set_streamer_privacy(streamer);
    } else if let Some(streamer) = cfg.extra.get("streamer_privacy").or_else(|| cfg.extra.get("streamer_mode")).and_then(|v| v.as_bool()) {
        win.set_streamer_privacy(streamer);
    }

    if let Some(rpc) = cfg.rpc_enabled {
        win.set_discord_rpc(rpc);
    } else if let Some(rpc) = cfg.extra.get("discord_rpc").and_then(|v| v.as_bool()) {
        win.set_discord_rpc(rpc);
    }

    if let Some(ref detail) = cfg.rpc_detail_mode {
        win.set_discord_detail(detail.clone().into());
    } else if let Some(detail) = cfg.extra.get("discord_detail").or_else(|| cfg.extra.get("rpc_detail_mode")).and_then(|v| v.as_str()) {
        win.set_discord_detail(detail.into());
    }

    if let Some(timer) = cfg.rpc_show_timer {
        win.set_discord_show_timer(timer);
    } else if let Some(timer) = cfg.extra.get("discord_show_timer").or_else(|| cfg.extra.get("rpc_show_timer")).and_then(|v| v.as_bool()) {
        win.set_discord_show_timer(timer);
    }

    if let Some(idle) = cfg.rpc_show_idle {
        win.set_discord_show_idle(idle);
    } else if let Some(idle) = cfg.extra.get("discord_show_idle").or_else(|| cfg.extra.get("rpc_show_idle")).and_then(|v| v.as_bool()) {
        win.set_discord_show_idle(idle);
    }

    if let Some(server) = cfg.rpc_show_server {
        win.set_discord_show_server(server);
    } else if let Some(server) = cfg.extra.get("discord_show_server").or_else(|| cfg.extra.get("rpc_show_server")).and_then(|v| v.as_bool()) {
        win.set_discord_show_server(server);
    }

    let (detected_ram_mb, detected_ram_str) = detect_system_ram();
    win.set_total_system_ram_mb(detected_ram_mb);
    win.set_total_system_ram_str(detected_ram_str.into());

    if let Some(ram) = cfg.ram {
        win.set_ram_allocation_mb(ram as i32);
    } else if let Some(ram) = cfg.extra.get("ram_allocation_mb").or_else(|| cfg.extra.get("ram_mb")).and_then(|v| v.as_i64()) {
        win.set_ram_allocation_mb(ram as i32);
    }

    if let Some(ref action) = cfg.post_launch_action {
        win.set_post_launch_action(action.clone().into());
    } else if let Some(action) = cfg.extra.get("post_launch_action").and_then(|v| v.as_str()) {
        win.set_post_launch_action(action.into());
    }
    if let Some(close) = cfg.extra.get("close_on_launch").and_then(|v| v.as_bool()) {
        win.set_close_on_launch(close);
    }
    if let Some(tray) = cfg.extra.get("minimize_to_tray").and_then(|v| v.as_bool()) {
        win.set_minimize_to_tray(tray);
    }
    if let Some(console) = cfg.extra.get("keep_console_open").and_then(|v| v.as_bool()) {
        win.set_keep_console_open(console);
    }
    if let Some(show_logs) = cfg.extra.get("show_launch_logs").and_then(|v| v.as_bool()) {
        win.set_show_launch_logs(show_logs);
    }
    if let Some(res) = cfg.extra.get("share_resource_packs").and_then(|v| v.as_bool()) {
        win.set_share_resource_packs(res);
    }
    if let Some(shd) = cfg.extra.get("share_shader_packs").and_then(|v| v.as_bool()) {
        win.set_share_shader_packs(shd);
    }
    if let Some(wrld) = cfg.extra.get("share_worlds").and_then(|v| v.as_bool()) {
        win.set_share_worlds(wrld);
    }
    if let Some(cfg_share) = cfg.extra.get("share_mod_configs").and_then(|v| v.as_bool()) {
        win.set_share_mod_configs(cfg_share);
    }
    if let Some(java) = cfg.extra.get("java_executable").or_else(|| cfg.extra.get("java_path")).and_then(|v| v.as_str()) {
        win.set_java_executable(java.into());
    }
    if let Some(jvm) = cfg.extra.get("jvm_arguments").or_else(|| cfg.extra.get("jvm_args")).and_then(|v| v.as_str()) {
        win.set_jvm_arguments(jvm.into());
    }
    if let Some(mc_dir) = cfg.extra.get("minecraft_directory").or_else(|| cfg.extra.get("game_directory")).and_then(|v| v.as_str()) {
        win.set_minecraft_directory(mc_dir.into());
    }
    let offline_skin_inj = cfg.extra.get("offline_skin_injection")
        .or_else(|| cfg.extra.get("skin_injection"))
        .or_else(|| cfg.extra.get("auto_download_mod"))
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    win.set_offline_skin_injection(offline_skin_inj);
    if let Some(dl_mp) = cfg.extra.get("max_modpack_downloads").and_then(|v| v.as_i64()) {
        win.set_max_modpack_downloads(dl_mp as i32);
    }
    if let Some(dl_mod) = cfg.extra.get("max_mod_downloads").and_then(|v| v.as_i64()) {
        win.set_max_mod_downloads(dl_mod as i32);
    }
    if let Some(thr) = cfg.extra.get("throttle_downloads").and_then(|v| v.as_bool()) {
        win.set_throttle_downloads(thr);
    }
    if let Some(spd) = cfg.extra.get("max_download_speed_kb").and_then(|v| v.as_i64()) {
        win.set_max_download_speed_kb(spd as i32);
    }
    if let Some(chk) = cfg.extra.get("check_updates_startup").and_then(|v| v.as_bool()) {
        win.set_check_updates_startup(chk);
    }
    if let Some(dtl) = cfg.extra.get("discord_detail").and_then(|v| v.as_str()) {
        win.set_discord_detail(dtl.into());
    }
    if let Some(off) = cfg.extra.get("default_offline_name").and_then(|v| v.as_str()) {
        win.set_default_offline_name(off.into());
    }
}


async fn refresh_accounts_roster(agent: &ipc::AgentClient, win_weak: slint::Weak<MainWindow>) {
    match agent.list_accounts().await {
        Ok(accts) => {
            let accounts = accts.accounts().to_vec();
            let is_empty = accounts.is_empty();

            let win_weak_inner = win_weak.clone();
            let accounts_items = accounts.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(w) = win_weak_inner.upgrade() {
                    if is_empty {
                        w.set_username("No Account".into());
                        w.set_account_type("Click to Sign In".into());
                        w.set_has_active_head(false);
                        w.set_accounts(std::rc::Rc::new(slint::VecModel::from(Vec::<AccountData>::new())).into());
                        w.set_add_account_modal_mode("select".into());
                        w.set_add_account_modal_open(true);
                    } else {
                        let active_idx = accounts_items.iter().position(|a| a.active.unwrap_or(false)).unwrap_or(0);
                        let active = accounts_items.get(active_idx);
                        let active_name = active.map(|a| a.name().to_string()).unwrap_or_else(|| "".to_string());
                        let active_type = active.map(|a| format_account_type(a.account_type())).unwrap_or("Offline");

                        let mut active_head_img: Option<slint::Image> = None;
                        let accounts_data: Vec<AccountData> = accounts_items.iter().enumerate().map(|(idx, a)| {
                            let is_active = idx == active_idx;
                            let acc_id = a.id.clone().or_else(|| a.uuid.clone()).unwrap_or_else(|| format!("acc_{}", idx));
                            let mut head_image = slint::Image::default();
                            let mut has_head = false;
                            if let Some(ref hp) = a.head_path {
                                if !hp.is_empty() && std::path::Path::new(hp).exists() {
                                    if let Some(img) = load_image_safely(std::path::Path::new(hp)) {
                                        if is_active {
                                            active_head_img = Some(img.clone());
                                        }
                                        head_image = img;
                                        has_head = true;
                                    }
                                }
                            }
                            AccountData {
                                id: acc_id.into(),
                                index: idx as i32,
                                name: a.name().into(),
                                account_type: format_account_type(a.account_type()).into(),
                                is_active,
                                has_head,
                                head_image,
                            }
                        }).collect();

                        w.set_username(active_name.into());
                        w.set_account_type(active_type.into());
                        w.set_accounts(std::rc::Rc::new(slint::VecModel::from(accounts_data)).into());
                        if let Some(img) = active_head_img {
                            w.set_has_active_head(true);
                            w.set_active_head_image(img);
                        } else {
                            w.set_has_active_head(false);
                        }
                    }
                }
            });

            if !is_empty {
                refresh_locker_capes(agent, win_weak.clone()).await;
                refresh_locker_presets(agent, win_weak.clone()).await;
                refresh_wallpapers_roster(agent, win_weak).await;
            }
        }
        Err(err) => {
            eprintln!("[NLC-Rust] Failed to list accounts: {:?}", err);
        }
    }
}

fn map_modpack(pack: &ipc::ModpackItem) -> ModpackData {
    let initial = pack.name.chars().next().map(|c| c.to_uppercase().to_string()).unwrap_or_else(|| "M".to_string());
    let is_linked = pack.linked_installation_id.is_some() && !pack.linked_installation_id.as_deref().unwrap_or("").is_empty();
    let ver = pack.version.clone().or_else(|| pack.mc_version.clone()).unwrap_or_else(|| "1.21.1".to_string());
    let release = pack.pack_release.clone().or_else(|| pack.version_name.clone()).unwrap_or_else(|| "1.0.0".to_string());

    let root_dir = std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."));
    let mut resolved_path: Option<std::path::PathBuf> = None;

    if let Some(ref ip) = pack.icon_path {
        let p = resolve_icon_path(ip, &root_dir);
        if p.exists() {
            resolved_path = Some(p);
        }
    }

    if resolved_path.is_none() {
        let direct = paths::get_modpacks_dir().join(&pack.id).join("icon.png");
        if direct.exists() {
            resolved_path = Some(direct);
        }
    }

    let (has_icon, icon_img) = if let Some(p) = resolved_path {
        if let Some(img) = load_image_safely(&p) {
            (true, img)
        } else {
            (false, slint::Image::default())
        }
    } else {
        (false, slint::Image::default())
    };

    ModpackData {
        id: pack.id.clone().into(),
        name: pack.name.clone().into(),
        loader: pack.loader.clone().unwrap_or_else(|| "Fabric".to_string()).into(),
        version: ver.into(),
        pack_release: release.into(),
        has_release: true,
        linked_inst_id: pack.linked_installation_id.clone().unwrap_or_default().into(),
        linked_inst_name: pack.linked_inst_name.clone().unwrap_or_default().into(),
        is_linked,
        mod_count: pack.mod_count.unwrap_or(0),
        thumbnail: pack.thumbnail.clone().unwrap_or_default().into(),
        icon_letter: initial.into(),
        has_icon,
        icon: icon_img,
    }
}

fn map_mod_card(item: &ipc::ModItem, idx: usize) -> ModCardData {
    let fn_str = if !item.filename.is_empty() {
        item.filename.clone()
    } else {
        item.name.clone()
    };
    let id_str = if !fn_str.is_empty() {
        fn_str.clone()
    } else {
        item.id.clone().unwrap_or_else(|| format!("{}", idx + 1))
    };
    let sz = item.size_text.clone().or_else(|| item.size.clone()).unwrap_or_else(|| "1.0 MB".to_string());
    let is_act = item.enabled.or(item.is_active).or(item.active).unwrap_or(true);
    let ver_str = item.version.clone().unwrap_or_default();

    let (has_icon, icon_img) = if let Some(ref path_str) = item.icon_path {
        if !path_str.is_empty() && std::path::Path::new(path_str).exists() {
            if let Some(img) = load_image_safely(std::path::Path::new(path_str)) {
                (true, img)
            } else {
                (false, slint::Image::default())
            }
        } else {
            (false, slint::Image::default())
        }
    } else {
        (false, slint::Image::default())
    };

    ModCardData {
        id: id_str.into(),
        name: item.name.clone().into(),
        filename: fn_str.into(),
        size: sz.into(),
        version: ver_str.into(),
        active: is_act,
        has_icon,
        icon: icon_img,
    }
}

fn format_count(count: u64) -> String {
    if count >= 1_000_000 {
        format!("{:.1}M", count as f64 / 1_000_000.0)
    } else if count >= 1_000 {
        format!("{:.1}K", count as f64 / 1_000.0)
    } else {
        count.to_string()
    }
}

fn resolve_project_id_icon_path(proj_id: &str, root: &std::path::Path) -> Option<std::path::PathBuf> {
    let local = root.join("cache").join("icons").join(format!("{}.png", proj_id));
    if local.exists() {
        return Some(local);
    }
    let cache_p = paths::get_cache_icons_dir().join(format!("{}.png", proj_id));
    if cache_p.exists() {
        return Some(cache_p);
    }
    None
}

fn resolve_modrinth_icon_path(hit: &ipc::ModrinthHit, root: &std::path::Path) -> Option<std::path::PathBuf> {
    if let Some(ref path_str) = hit.icon_path {
        let p = std::path::Path::new(path_str);
        if p.exists() {
            return Some(p.to_path_buf());
        }
    }
    if let Some(p) = resolve_project_id_icon_path(&hit.project_id, root) {
        return Some(p);
    }
    if let Some(ref slug) = hit.slug {
        if let Some(p) = resolve_project_id_icon_path(slug, root) {
            return Some(p);
        }
    }
    None
}

fn resolve_gallery_item_image_path(proj_id: &str, idx: usize, root: &std::path::Path) -> Option<std::path::PathBuf> {
    let local = root.join("cache").join("gallery").join(format!("{}_{}.png", proj_id, idx));
    if local.exists() {
        return Some(local);
    }
    let cache_p = paths::get_cache_dir().join("gallery").join(format!("{}_{}.png", proj_id, idx));
    if cache_p.exists() {
        return Some(cache_p);
    }
    None
}

fn map_modrinth_hit(hit: &ipc::ModrinthHit, default_type: &str, root: &std::path::Path) -> ModrinthProjectData {
    let p_type = hit.project_type.as_deref().unwrap_or(default_type);
    let dls = hit.downloads.map(format_count).unwrap_or_else(|| "0".to_string());
    let flws = hit.follows.map(format_count).unwrap_or_else(|| "0".to_string());
    const KNOWN_LOADERS: &[&str] = &["fabric", "forge", "neoforge", "quilt"];
    let loader_labels: Vec<String> = hit.categories
        .iter()
        .filter(|c| KNOWN_LOADERS.contains(&c.to_lowercase().as_str()))
        .map(|c| c.to_uppercase())
        .collect();
    let loaders = if !loader_labels.is_empty() {
        loader_labels.join(", ")
    } else {
        "".to_string()
    };
    let vers = if hit.versions.is_empty() {
        "".to_string()
    } else {
        hit.versions.iter().take(2).cloned().collect::<Vec<_>>().join(", ")
    };
    let (has_icon, icon) = if let Some(p) = resolve_modrinth_icon_path(hit, root) {
        if let Some(img) = load_image_safely(&p) {
            (true, img)
        } else {
            (false, slint::Image::default())
        }
    } else {
        (false, slint::Image::default())
    };
    ModrinthProjectData {
        id: hit.project_id.clone().into(),
        slug: hit.slug.clone().unwrap_or_default().into(),
        title: hit.title.clone().into(),
        description: hit.description.clone().unwrap_or_default().into(),
        author: hit.author.clone().unwrap_or_default().into(),
        downloads: dls.into(),
        follows: flws.into(),
        project_type: p_type.to_string().into(),
        loaders: loaders.into(),
        versions: vers.into(),
        icon_url: hit.icon_url.clone().unwrap_or_default().into(),
        install_status: "idle".into(),
        has_icon,
        icon,
    }
}

// -----------------------------------------------------------------------------
// Addons View State and Helper Functions
// -----------------------------------------------------------------------------

#[derive(Clone, Debug)]
struct RawAddonItem {
    id: String,
    name: String,
    version: String,
    author: String,
    description: String,
    source: String,
    installed: bool,
    icon_path: Option<std::path::PathBuf>,
    downloads: String,
    folder_path: String,
    action_id: String,
    action_label: String,
    badge_text: String,
    badge_color: slint::Color,
    details_text: String,
}

fn map_local_addon(addon: &ipc::ThirdPartyAddonItem) -> RawAddonItem {
    let icon_path = std::path::Path::new(&addon.addon_dir).join("icon.png");
    let icon_opt = if icon_path.exists() {
        Some(icon_path)
    } else {
        None
    };

    let first_action = addon.actions.first();
    let action_id = first_action.map(|a| a.id.as_str()).unwrap_or("").to_string();
    let action_label = first_action
        .map(|a| {
            if !a.name.is_empty() {
                a.name.as_str()
            } else {
                "Run"
            }
        })
        .unwrap_or("Run")
        .to_string();

    RawAddonItem {
        id: addon.id.clone(),
        name: addon.name.clone(),
        version: addon.version.clone(),
        author: addon.author.clone(),
        description: addon.description.clone(),
        source: "local".to_string(),
        installed: true,
        icon_path: icon_opt,
        downloads: "Installed Local".to_string(),
        folder_path: addon.addon_dir.clone(),
        action_id,
        action_label,
        badge_text: "".to_string(),
        badge_color: slint::Color::from_argb_u8(255, 92, 209, 255),
        details_text: "".to_string(),
    }
}

#[allow(dead_code)]
fn map_modrinth_addon(hit: &ipc::ModrinthHit, root: &std::path::Path) -> RawAddonItem {
    let dls = hit.downloads.map(format_count).unwrap_or_else(|| "0".to_string());
    let icon_opt = resolve_modrinth_icon_path(hit, root);
    let first_ver = hit.versions.first().cloned().unwrap_or_else(|| "Latest".to_string());

    RawAddonItem {
        id: hit.project_id.clone(),
        name: hit.title.clone(),
        version: first_ver,
        author: hit.author.clone().unwrap_or_else(|| "Unknown".to_string()),
        description: hit.description.clone().unwrap_or_default(),
        source: "modrinth".to_string(),
        installed: false,
        icon_path: icon_opt,
        downloads: format!("{} dls", dls),
        folder_path: "".to_string(),
        action_id: "install".to_string(),
        action_label: "Install".to_string(),
        badge_text: "".to_string(),
        badge_color: slint::Color::from_argb_u8(255, 46, 204, 113),
        details_text: "".to_string(),
    }
}

fn format_playtime_duration(seconds: u64) -> String {
    let hours = seconds / 3600;
    let minutes = (seconds % 3600) / 60;
    if hours > 0 {
        format!("{}h {}m", hours, minutes)
    } else {
        format!("{}m", minutes)
    }
}

async fn update_playtime_stats_in_ui(
    agent: &ipc::AgentClient,
    win_weak: slint::Weak<MainWindow>,
    project_root: &std::path::Path,
) {
    let stats = agent.get_playtime_stats().await.ok();
    let insts_res = agent.list_instances().await.ok();
    let root_path = project_root.to_path_buf();
    let win_weak_inner = win_weak.clone();

    let _ = slint::invoke_from_event_loop(move || {
        if let Some(w) = win_weak_inner.upgrade() {
            let total_sec = stats.as_ref().map(|s| s.total_seconds).unwrap_or(0);
            let total_min = stats.as_ref().map(|s| s.total_minutes).unwrap_or(0);
            let total_launches = stats.as_ref().map(|s| s.total_launches).unwrap_or(0);
            let total_fmt = format_playtime_duration(total_sec);

            w.set_addons_minutes(total_min as i32);
            w.set_addons_launches(total_launches as i32);
            w.set_addons_total_playtime(total_fmt.into());

            // Build list of installations with their playtime
            let mut inst_list: Vec<(String, u64, slint::Image)> = Vec::new();
            let tracker = stats.as_ref().map(|s| &s.tracker);

            let installations = w.get_installations();
            if installations.row_count() > 0 {
                for idx in 0..installations.row_count() {
                    if let Some(inst) = installations.row_data(idx) {
                        let inst_id = inst.id.to_string();
                        let mut seconds = 0u64;
                        if let Some(tr) = tracker {
                            if let Some(val) = tr.get(&inst_id) {
                                if let Some(obj) = val.as_object() {
                                    seconds = obj.get("seconds").and_then(|v| v.as_u64()).unwrap_or(0);
                                }
                            }
                        }
                        inst_list.push((inst.name.to_string(), seconds, inst.icon));
                    }
                }
            } else if let Some(inst_items) = insts_res {
                for i in inst_items {
                    let inst_id = i.id.clone();
                    let mut seconds = 0u64;
                    if let Some(tr) = tracker {
                        if let Some(val) = tr.get(&inst_id) {
                            if let Some(obj) = val.as_object() {
                                seconds = obj.get("seconds").and_then(|v| v.as_u64()).unwrap_or(0);
                            }
                        }
                    }
                    let icon_img = load_image_safely(&resolve_icon_path(i.icon.as_deref().unwrap_or(""), &root_path)).unwrap_or_default();
                    inst_list.push((i.name.clone(), seconds, icon_img));
                }
            }

            inst_list.sort_by(|a, b| b.1.cmp(&a.1));

            // Top 1 installation
            if let Some((name, sec, icon)) = inst_list.get(0) {
                if *sec > 0 {
                    w.set_has_top_inst_1(true);
                    w.set_top_inst_1_name(name.clone().into());
                    w.set_top_inst_1_time(format_playtime_duration(*sec).into());
                    w.set_top_inst_1_icon(icon.clone());
                } else {
                    w.set_has_top_inst_1(false);
                }
            } else {
                w.set_has_top_inst_1(false);
            }

            // Top 2 installation
            if let Some((name, sec, icon)) = inst_list.get(1) {
                if *sec > 0 {
                    w.set_has_top_inst_2(true);
                    w.set_top_inst_2_name(name.clone().into());
                    w.set_top_inst_2_time(format_playtime_duration(*sec).into());
                    w.set_top_inst_2_icon(icon.clone());
                } else {
                    w.set_has_top_inst_2(false);
                }
            } else {
                w.set_has_top_inst_2(false);
            }
        }
    });
}

fn get_addons_config_state() -> (bool, usize, String) {
    let cfg_path = paths::get_config_path();
    if let Ok(content) = std::fs::read_to_string(&cfg_path) {
        if let Ok(val) = serde_json::from_str::<serde_json::Value>(&content) {
            let streamer = val.get("streamer_mode")
                .or_else(|| val.get("streamer_privacy"))
                .and_then(|v| v.as_bool())
                .unwrap_or(false);
            let saved_count = val.get("addons")
                .and_then(|a| a.get("saved_servers"))
                .and_then(|s| s.as_array())
                .map(|arr| arr.len())
                .unwrap_or(0);
            let gh_repo = val.get("gh_sync_repo")
                .and_then(|r| r.as_str())
                .unwrap_or("")
                .to_string();
            return (streamer, saved_count, gh_repo);
        }
    }
    (false, 0, String::new())
}

fn get_builtin_addons(streamer_mode: bool, saved_servers_count: usize, gh_repo: &str) -> Vec<RawAddonItem> {
    vec![
        RawAddonItem {
            id: "gh_skin_sync".to_string(),
            name: "GitHub Skin Sync".to_string(),
            version: "1.2.0".to_string(),
            author: "Amne-Dev".to_string(),
            description: "Automatically synchronizes character skins with a remote GitHub repository.".to_string(),
            source: "builtin".to_string(),
            installed: true,
            icon_path: None,
            downloads: "Built-in Tool".to_string(),
            folder_path: "".to_string(),
            action_id: "sync".to_string(),
            action_label: "Sync Now".to_string(),
            badge_text: if gh_repo.is_empty() { "SETUP NEEDED".to_string() } else { "READY".to_string() },
            badge_color: if gh_repo.is_empty() { slint::Color::from_argb_u8(255, 243, 156, 18) } else { slint::Color::from_argb_u8(255, 92, 209, 255) },
            details_text: if gh_repo.is_empty() { "Configure GitHub token in Settings to sync.".to_string() } else { format!("Repository: {}", gh_repo) },
        },
        RawAddonItem {
            id: "streamer_mode".to_string(),
            name: "Streamer Mode".to_string(),
            version: "1.0.0".to_string(),
            author: "Amne-Dev".to_string(),
            description: "Hides account emails, session tokens, and IP addresses during broadcasting.".to_string(),
            source: "builtin".to_string(),
            installed: true,
            icon_path: None,
            downloads: "Built-in Tool".to_string(),
            folder_path: "".to_string(),
            action_id: "toggle".to_string(),
            action_label: if streamer_mode { "Disable".to_string() } else { "Enable".to_string() },
            badge_text: if streamer_mode { "SHIELD ACTIVE".to_string() } else { "INACTIVE".to_string() },
            badge_color: if streamer_mode { slint::Color::from_argb_u8(255, 46, 204, 113) } else { slint::Color::from_argb_u8(255, 122, 130, 148) },
            details_text: if streamer_mode { "Shield active: Masking accounts, tokens, and IP addresses.".to_string() } else { "Protect sensitive details from broadcast and screenshots.".to_string() },
        },
        RawAddonItem {
            id: "server_quick_join".to_string(),
            name: "Server Quick Join".to_string(),
            version: "1.0.0".to_string(),
            author: "Amne-Dev".to_string(),
            description: "Directly join favorite multiplayer servers with latency monitoring.".to_string(),
            source: "builtin".to_string(),
            installed: true,
            icon_path: None,
            downloads: "Built-in Tool".to_string(),
            folder_path: "".to_string(),
            action_id: "manage".to_string(),
            action_label: "Manage".to_string(),
            badge_text: if saved_servers_count == 0 { "0 SERVERS".to_string() } else { format!("{} SERVERS", saved_servers_count) },
            badge_color: slint::Color::from_argb_u8(255, 224, 86, 253),
            details_text: if saved_servers_count == 0 { "Click Manage to add favorite servers and monitor latency.".to_string() } else { format!("{} multiplayer servers saved with direct join.", saved_servers_count) },
        },
    ]
}

#[allow(dead_code)]
#[derive(serde::Deserialize, Clone, Debug)]
struct CommunityAddonManifestItem {
    id: String,
    name: String,
    version: String,
    author: String,
    description: String,
    #[serde(default = "default_community_source")]
    source: String,
    #[serde(default)]
    installed: bool,
    #[serde(default)]
    downloads: String,
    #[serde(default)]
    folder_path: String,
    #[serde(default = "default_addon_action_id")]
    action_id: String,
    #[serde(default = "default_addon_action_label")]
    action_label: String,
}

fn default_community_source() -> String {
    "community".to_string()
}
fn default_addon_action_id() -> String {
    "install".to_string()
}
fn default_addon_action_label() -> String {
    "Install".to_string()
}

async fn fetch_community_addons_from_repo(agent: Option<&ipc::AgentClient>) -> Vec<RawAddonItem> {
    if let Some(agent) = agent {
        if let Ok(raw_list) = agent.get_community_addons_catalog().await {
            let mut items = Vec::new();
            for item in raw_list {
                if let Ok(m) = serde_json::from_value::<CommunityAddonManifestItem>(item) {
                    items.push(RawAddonItem {
                        id: m.id,
                        name: m.name,
                        version: m.version,
                        author: m.author,
                        description: m.description,
                        source: "community".to_string(),
                        installed: false,
                        icon_path: None,
                        downloads: "".to_string(),
                        folder_path: "".to_string(),
                        action_id: "install".to_string(),
                        action_label: "Install".to_string(),
                        badge_text: "".to_string(),
                        badge_color: slint::Color::from_argb_u8(255, 46, 204, 113),
                        details_text: "".to_string(),
                    });
                }
            }
            return items;
        }
    }
    Vec::new()
}

#[derive(Default, Clone, Debug)]
struct AddonsViewState {
    current_source: String,
    search_filter: String,
    addons_dir: String,
    local_addons: Vec<ipc::ThirdPartyAddonItem>,
    community_addons: Vec<RawAddonItem>,
    #[allow(dead_code)]
    modrinth_addons: Vec<ipc::ModrinthHit>,
    is_loading: bool,
}

async fn sync_addons_model_to_ui(
    win_weak: slint::Weak<MainWindow>,
    state: Arc<tokio::sync::Mutex<AddonsViewState>>,
    _root_dir: &std::path::Path,
) {
    let st = state.lock().await;
    let mut raw_items: Vec<RawAddonItem> = Vec::new();
    let query = st.search_filter.to_lowercase();
    let source = if st.current_source.is_empty() {
        "all".to_string()
    } else {
        st.current_source.to_lowercase()
    };

    // Built-in tools
    if source == "all" || source == "builtin" {
        let (streamer, saved_count, gh_repo) = get_addons_config_state();
        for b in get_builtin_addons(streamer, saved_count, &gh_repo) {
            if query.is_empty()
                || b.name.to_lowercase().contains(&query)
                || b.description.to_lowercase().contains(&query)
            {
                raw_items.push(b);
            }
        }
    }

    // Local addons
    if source == "all" || source == "local" || source == "installed" {
        for a in &st.local_addons {
            if query.is_empty()
                || a.name.to_lowercase().contains(&query)
                || a.description.to_lowercase().contains(&query)
                || a.author.to_lowercase().contains(&query)
            {
                raw_items.push(map_local_addon(a));
            }
        }
    }

    // Community discover addons (Amne-Dev/Community-addons-nlc)
    if source == "all" || source == "community" || source == "discover" || source == "modrinth" {
        for c in &st.community_addons {
            if query.is_empty()
                || c.name.to_lowercase().contains(&query)
                || c.description.to_lowercase().contains(&query)
                || c.author.to_lowercase().contains(&query)
            {
                raw_items.push(c.clone());
            }
        }
    }

    let is_loading = st.is_loading;
    drop(st);

    let _ = slint::invoke_from_event_loop(move || {
        if let Some(w) = win_weak.upgrade() {
            sync_raw_addons_to_ui(&w, raw_items, is_loading);
        }
    });
}

fn sync_raw_addons_to_ui(w: &MainWindow, raw_items: Vec<RawAddonItem>, is_loading: bool) {
    let count = raw_items.len();
    let items: Vec<AddonItemData> = raw_items
        .into_iter()
        .map(|it| {
            let (has_icon, icon) = if let Some(ref p) = it.icon_path {
                if let Some(img) = load_image_safely(p) {
                    (true, img)
                } else {
                    (false, slint::Image::default())
                }
            } else {
                (false, slint::Image::default())
            };

            AddonItemData {
                id: it.id.into(),
                name: it.name.into(),
                version: it.version.into(),
                author: it.author.into(),
                description: it.description.into(),
                source: it.source.into(),
                installed: it.installed,
                has_icon,
                icon,
                downloads: it.downloads.into(),
                folder_path: it.folder_path.into(),
                action_id: it.action_id.into(),
                action_label: it.action_label.into(),
                badge_text: it.badge_text.into(),
                badge_color: it.badge_color,
                details_text: it.details_text.into(),
            }
        })
        .collect();

    w.set_addons(std::rc::Rc::new(slint::VecModel::from(items)).into());
    w.set_addons_is_loading(is_loading);
    w.set_addons_status_message(if is_loading {
        "Loading addons...".into()
    } else {
        format!("{} addons available", count).into()
    });
}

async fn refresh_and_ping_saved_servers(
    agent: Option<&ipc::AgentClient>,
    win_weak: slint::Weak<MainWindow>,
) {
    if let Some(agent) = agent {
        if let Ok(servers) = agent.get_saved_servers().await {
            let initial_items: Vec<SavedServerData> = servers.iter().map(|s| {
                SavedServerData {
                    id: s.id.clone().into(),
                    name: s.name.clone().into(),
                    address: s.address.clone().into(),
                    port: s.port as i32,
                    online: false,
                    latency_ms: 0,
                    players_online: 0,
                    players_max: 0,
                    version: "".into(),
                    pinging: true,
                }
            }).collect();

            let _ = slint::invoke_from_event_loop({
                let win_weak = win_weak.clone();
                let initial_items = initial_items.clone();
                move || {
                    if let Some(w) = win_weak.upgrade() {
                        w.set_saved_servers(std::rc::Rc::new(slint::VecModel::from(initial_items)).into());
                        w.set_is_pinging_servers(true);
                    }
                }
            });

            let mut tasks = Vec::new();
            for s in servers {
                let a = agent.clone();
                tasks.push(tokio::spawn(async move {
                    let ping_res = a.ping_server(&s.address, s.port).await;
                    (s, ping_res)
                }));
            }

            let mut updated_items = Vec::new();
            for t in tasks {
                if let Ok((s, res)) = t.await {
                    match res {
                        Ok(p) => {
                            updated_items.push(SavedServerData {
                                id: s.id.into(),
                                name: s.name.into(),
                                address: s.address.into(),
                                port: s.port as i32,
                                online: p.online,
                                latency_ms: p.latency_ms as i32,
                                players_online: p.players_online.unwrap_or(0) as i32,
                                players_max: p.players_max.unwrap_or(0) as i32,
                                version: p.version.unwrap_or_default().into(),
                                pinging: false,
                            });
                        }
                        Err(_) => {
                            updated_items.push(SavedServerData {
                                id: s.id.into(),
                                name: s.name.into(),
                                address: s.address.into(),
                                port: s.port as i32,
                                online: false,
                                latency_ms: 0,
                                players_online: 0,
                                players_max: 0,
                                version: "".into(),
                                pinging: false,
                            });
                        }
                    }
                }
            }

            let _ = slint::invoke_from_event_loop({
                let win_weak = win_weak.clone();
                move || {
                    if let Some(w) = win_weak.upgrade() {
                        w.set_saved_servers(std::rc::Rc::new(slint::VecModel::from(updated_items)).into());
                        w.set_is_pinging_servers(false);
                    }
                }
            });
        }
    }
}

async fn refresh_addons_roster(
    agent: Option<&ipc::AgentClient>,
    win_weak: slint::Weak<MainWindow>,
    state: Arc<tokio::sync::Mutex<AddonsViewState>>,
    root_dir: &std::path::Path,
) {
    if let Some(agent) = agent {
        let _ = slint::invoke_from_event_loop({
            let win_weak = win_weak.clone();
            move || {
                if let Some(w) = win_weak.upgrade() {
                    w.set_addons_is_loading(true);
                }
            }
        });

        match agent.list_third_party_addons().await {
            Ok(resp) => {
                let mut st = state.lock().await;
                if let Some(data) = resp.data {
                    st.addons_dir = data.addons_dir;
                    st.local_addons = data.addons;
                }
                st.is_loading = false;
            }
            Err(e) => {
                eprintln!("[NLC-Rust] Failed to list third party addons: {}", e);
                let mut st = state.lock().await;
                st.is_loading = false;
            }
        }
    }

    let community = fetch_community_addons_from_repo(agent).await;
    {
        let mut st = state.lock().await;
        st.community_addons = community;
    }

    sync_addons_model_to_ui(win_weak, state, root_dir).await;
}

#[derive(Default, Clone, Debug)]
struct ModrinthSearchState {
    query: String,
    mode: String,
    loader: String,
    version: String,
    sort: String,
    offset: u32,
    has_more: bool,
    is_loading: bool,
}

fn push_or_update_notification(
    win: &MainWindow,
    id: &str,
    category: &str,
    title: &str,
    description: &str,
    timestamp: &str,
    is_read: bool,
) {
    let current_model = win.get_notifications();
    let mut items: Vec<NotificationItemData> = Vec::new();
    let mut found = false;
    for i in 0..current_model.row_count() {
        if let Some(item) = current_model.row_data(i) {
            if item.id == id {
                items.push(NotificationItemData {
                    id: id.into(),
                    category: category.into(),
                    title: title.into(),
                    description: description.into(),
                    timestamp: timestamp.into(),
                    is_read,
                });
                found = true;
            } else {
                items.push(item);
            }
        }
    }
    if !found {
        items.insert(0, NotificationItemData {
            id: id.into(),
            category: category.into(),
            title: title.into(),
            description: description.into(),
            timestamp: timestamp.into(),
            is_read,
        });
    }

    let mut dl_count = 0;
    let mut sess_count = 0;
    let mut unread = 0;
    for item in &items {
        if item.category == "Downloads" {
            dl_count += 1;
        } else if item.category == "Sessions" {
            sess_count += 1;
        }
        if !item.is_read {
            unread += 1;
        }
    }

    win.set_notifications(std::rc::Rc::new(slint::VecModel::from(items)).into());
    win.set_active_downloads_count(dl_count);
    win.set_active_sessions_count(sess_count);
    win.set_unread_notifications(unread);
}

#[derive(Clone, Debug)]
struct ActiveSessionItem {
    id: String,
    name: String,
    version: String,
    loader: String,
    started_at: std::time::Instant,
    icon_path: std::path::PathBuf,
}

fn format_session_duration(d: std::time::Duration) -> String {
    let secs = d.as_secs();
    if secs < 60 {
        format!("{}s", secs)
    } else if secs < 3600 {
        let mins = secs / 60;
        let rem_s = secs % 60;
        if rem_s == 0 {
            format!("{}m", mins)
        } else {
            format!("{}m {}s", mins, rem_s)
        }
    } else {
        let hrs = secs / 3600;
        let rem_m = (secs % 3600) / 60;
        if rem_m == 0 {
            format!("{}h", hrs)
        } else {
            format!("{}h {}m", hrs, rem_m)
        }
    }
}

thread_local! {
    static ACTIVE_SESSIONS_MODEL: std::cell::RefCell<Option<std::rc::Rc<slint::VecModel<ActiveSessionData>>>> = const { std::cell::RefCell::new(None) };
}

fn sync_active_sessions_to_ui(
    win: &MainWindow,
    tracker: &std::sync::Mutex<Vec<ActiveSessionItem>>,
) {
    if let Ok(list) = tracker.lock() {
        ACTIVE_SESSIONS_MODEL.with(|cell| {
            let mut opt = cell.borrow_mut();
            let model = opt.get_or_insert_with(|| {
                let m = std::rc::Rc::new(slint::VecModel::<ActiveSessionData>::default());
                win.set_active_sessions(m.clone().into());
                m
            }).clone();

            // 1. Remove rows no longer present in list
            let mut i = 0;
            while i < model.row_count() {
                if let Some(row) = model.row_data(i) {
                    if !list.iter().any(|item| item.id == row.id.as_str()) {
                        model.remove(i);
                        continue;
                    }
                }
                i += 1;
            }

            // 2. Synchronize active items in order
            for (target_idx, item) in list.iter().enumerate() {
                let elapsed = item.started_at.elapsed();
                let elapsed_sec = elapsed.as_secs() as i32;
                let elapsed_str = format_session_duration(elapsed);

                if let Some(mut existing) = model.row_data(target_idx) {
                    if existing.id == item.id.as_str() {
                        let mut changed = false;
                        if existing.elapsed_seconds != elapsed_sec {
                            existing.elapsed_seconds = elapsed_sec;
                            existing.elapsed_text = elapsed_str.clone().into();
                            changed = true;
                        }
                        if existing.name != item.name.as_str() {
                            existing.name = item.name.clone().into();
                            changed = true;
                        }
                        if existing.version != item.version.as_str() {
                            existing.version = item.version.clone().into();
                            changed = true;
                        }
                        if existing.loader != item.loader.as_str() {
                            existing.loader = item.loader.clone().into();
                            changed = true;
                        }
                        if changed {
                            model.set_row_data(target_idx, existing);
                        }
                        continue;
                    }
                }

                // Check if item exists later in the model
                let mut found_at = None;
                for k in target_idx..model.row_count() {
                    if let Some(row) = model.row_data(k) {
                        if row.id == item.id.as_str() {
                            found_at = Some(k);
                            break;
                        }
                    }
                }

                if let Some(k) = found_at {
                    let existing = model.remove(k);
                    model.insert(target_idx, existing);
                } else {
                    let img = load_image_safely(&item.icon_path).unwrap_or_default();
                    let row = ActiveSessionData {
                        id: item.id.clone().into(),
                        name: item.name.clone().into(),
                        version: item.version.clone().into(),
                        loader: item.loader.clone().into(),
                        elapsed_seconds: elapsed_sec,
                        elapsed_text: elapsed_str.into(),
                        status: "Running".into(),
                        icon: img,
                    };
                    model.insert(target_idx, row);
                }
            }
        });

        win.set_active_sessions_count(list.len() as i32);
    }
}

#[derive(Clone, Debug)]
struct ToastItem {
    id: String,
    title: String,
    detail: String,
    progress: f32,
    status: String,
    timeout_fraction: f32,
    remaining_ms: u32,
    total_ms: u32,
    is_sticky: bool,
    is_paused: bool,
    can_copy: bool,
    error_payload: String,
}

static GLOBAL_TOAST_TRACKER: std::sync::OnceLock<Arc<std::sync::Mutex<Vec<ToastItem>>>> = std::sync::OnceLock::new();

fn get_toast_tracker() -> Arc<std::sync::Mutex<Vec<ToastItem>>> {
    GLOBAL_TOAST_TRACKER.get_or_init(|| Arc::new(std::sync::Mutex::new(Vec::new()))).clone()
}

fn sync_toasts_to_ui(win: &MainWindow, list: &[ToastItem]) {
    let slint_items: Vec<ToastItemData> = list
        .iter()
        .map(|t| ToastItemData {
            id: t.id.clone().into(),
            title: t.title.clone().into(),
            detail: t.detail.clone().into(),
            progress: t.progress,
            status: t.status.clone().into(),
            timeout_fraction: t.timeout_fraction,
            is_sticky: t.is_sticky,
            can_copy: t.can_copy,
            error_payload: t.error_payload.clone().into(),
        })
        .collect();
    win.set_active_toasts(std::rc::Rc::new(slint::VecModel::from(slint_items)).into());
}

fn show_toast_notification(
    win: &MainWindow,
    tracker: &std::sync::Mutex<Vec<ToastItem>>,
    id: &str,
    title: &str,
    detail: &str,
    status: &str,
    progress: f32,
    is_sticky: bool,
    error_payload: &str,
) {
    if let Ok(mut list) = tracker.lock() {
        let total_ms = match status {
            "error" => 7000,
            "warning" => 5000,
            "completed" => 3500,
            _ => 4000,
        };
        let can_copy = status == "error";
        let err_str = if can_copy && error_payload.is_empty() {
            detail.to_string()
        } else {
            error_payload.to_string()
        };

        if let Some(existing) = list.iter_mut().find(|t| t.id == id) {
            existing.title = title.to_string();
            existing.detail = detail.to_string();
            existing.status = status.to_string();
            existing.progress = progress;
            existing.is_sticky = is_sticky;
            existing.can_copy = can_copy;
            existing.error_payload = err_str;
            if !is_sticky {
                existing.total_ms = total_ms;
                existing.remaining_ms = total_ms;
                existing.timeout_fraction = 1.0;
            }
        } else {
            while list.len() >= 4 {
                list.remove(0);
            }
            list.push(ToastItem {
                id: id.to_string(),
                title: title.to_string(),
                detail: detail.to_string(),
                progress,
                status: status.to_string(),
                timeout_fraction: 1.0,
                remaining_ms: total_ms,
                total_ms,
                is_sticky,
                is_paused: false,
                can_copy,
                error_payload: err_str,
            });
        }
        sync_toasts_to_ui(win, &list);
    }
}

fn push_toast(
    win: &MainWindow,
    id: &str,
    title: &str,
    detail: &str,
    status: &str,
) {
    show_toast_notification(win, &get_toast_tracker(), id, title, detail, status, 100.0, false, "");
}

fn push_toast_with_progress(
    win: &MainWindow,
    id: &str,
    title: &str,
    detail: &str,
    status: &str,
    progress: f32,
    is_sticky: bool,
    error_payload: &str,
) {
    show_toast_notification(win, &get_toast_tracker(), id, title, detail, status, progress, is_sticky, error_payload);
}

fn map_modrinth_version(v: &serde_json::Value) -> ModrinthVersionData {
    let id = v.get("id").and_then(|x| x.as_str()).unwrap_or("").to_string();
    let name = v.get("name").and_then(|x| x.as_str()).unwrap_or("").to_string();
    let ver_num = v.get("version_number").and_then(|x| x.as_str()).unwrap_or("").to_string();
    let g_vers = v.get("game_versions").and_then(|x| x.as_array())
        .map(|arr| arr.iter().filter_map(|s| s.as_str()).take(2).collect::<Vec<_>>().join(", "))
        .unwrap_or_default();
    let ldrs = v.get("loaders").and_then(|x| x.as_array())
        .map(|arr| arr.iter().filter_map(|s| s.as_str()).collect::<Vec<_>>().join(", "))
        .unwrap_or_default();

    let file = v.get("files").and_then(|x| x.as_array()).and_then(|arr| arr.first());
    let filename = file.and_then(|f| f.get("filename")).and_then(|s| s.as_str()).unwrap_or("").to_string();
    let size_bytes = file.and_then(|f| f.get("size")).and_then(|s| s.as_u64()).unwrap_or(0);
    let size_str = if size_bytes >= 1_048_576 {
        format!("{:.1} MB", size_bytes as f64 / 1_048_576.0)
    } else {
        format!("{:.0} KB", size_bytes as f64 / 1024.0)
    };
    let dl_url = file.and_then(|f| f.get("url")).and_then(|s| s.as_str()).unwrap_or("").to_string();
    let sha1 = file.and_then(|f| f.get("hashes")).and_then(|h| h.get("sha1")).and_then(|s| s.as_str()).unwrap_or("").to_string();

    ModrinthVersionData {
        id: id.into(),
        name: name.into(),
        version_number: ver_num.into(),
        game_versions: g_vers.into(),
        loaders: ldrs.into(),
        filename: filename.into(),
        file_size: size_str.into(),
        download_url: dl_url.into(),
        sha1: sha1.into(),
        install_status: "idle".into(),
    }
}

use base64::Engine;

#[derive(Debug)]
struct SkinViewState {
    yaw: f32,
    pitch: f32,
    walk_phase: f32,
    is_walking: bool,
    model: String,
    skin_path: Option<String>,
    cape_path: Option<String>,
    is_fetching: bool,
}

fn decode_b64_to_rgba(b64_str: &str) -> Option<(u32, u32, Vec<u8>)> {
    let png_bytes = base64::engine::general_purpose::STANDARD.decode(b64_str.trim()).ok()?;
    let dyn_img = image::load_from_memory(&png_bytes).ok()?;
    let rgba = dyn_img.to_rgba8();
    let (width, height) = rgba.dimensions();
    Some((width, height, rgba.into_raw()))
}

async fn trigger_skin_render(
    agent: Arc<AgentClient>,
    win_weak: slint::Weak<MainWindow>,
    skin_state: Arc<tokio::sync::Mutex<SkinViewState>>,
) {
    let (req, should_fetch) = {
        let mut state = skin_state.lock().await;
        if state.is_fetching {
            (ipc::SkinRenderFrameRequest::default(), false)
        } else {
            state.is_fetching = true;
            let r = ipc::SkinRenderFrameRequest {
                skin_path: state.skin_path.clone(),
                cape_path: state.cape_path.clone(),
                yaw_deg: state.yaw,
                pitch_deg: state.pitch,
                walk_phase: if state.is_walking { state.walk_phase } else { 0.0 },
                width: 320,
                height: 380,
                model: state.model.clone(),
            };
            (r, true)
        }
    };

    if !should_fetch {
        return;
    }

    let res = agent.render_skin_frame(req).await;
    {
        let mut state = skin_state.lock().await;
        state.is_fetching = false;
    }

    if let Ok(frame_data) = res {
        if let Some((w, h, raw_bytes)) = decode_b64_to_rgba(&frame_data.image_base64) {
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(win) = win_weak.upgrade() {
                    let mut buffer = slint::SharedPixelBuffer::<slint::Rgba8Pixel>::new(w, h);
                    buffer.make_mut_bytes().copy_from_slice(&raw_bytes);
                    win.set_skin_preview_image(slint::Image::from_rgba8(buffer));
                }
            });
        }
    }
}

#[cfg(target_os = "windows")]
mod win32 {
    #[link(name = "user32")]
    extern "system" {
        pub fn FindWindowW(lpClassName: *const u16, lpWindowName: *const u16) -> isize;
        pub fn GetForegroundWindow() -> isize;
        pub fn GetWindowThreadProcessId(hWnd: isize, lpdwProcessId: *mut u32) -> u32;
        pub fn AttachThreadInput(idAttach: u32, idAttachTo: u32, fAttach: i32) -> i32;
        pub fn BringWindowToTop(hWnd: isize) -> i32;
        pub fn SetForegroundWindow(hWnd: isize) -> i32;
        pub fn SetWindowPos(hWnd: isize, hWndInsertAfter: isize, X: i32, Y: i32, cx: i32, cy: i32, uFlags: u32) -> i32;
        pub fn ShowWindow(hWnd: isize, nCmdShow: i32) -> i32;
        pub fn EnumWindows(lpEnumFunc: unsafe extern "system" fn(isize, isize) -> i32, lParam: isize) -> i32;
        pub fn GetWindowTextLengthW(hWnd: isize) -> i32;
    }
    #[link(name = "kernel32")]
    extern "system" {
        pub fn GetCurrentProcessId() -> u32;
        pub fn GetCurrentThreadId() -> u32;
    }

    #[derive(Default)]
    struct EnumState {
        hwnd_with_title: isize,
        hwnd_any: isize,
    }

    unsafe extern "system" fn enum_window_callback(hwnd: isize, lparam: isize) -> i32 {
        let mut pid = 0u32;
        GetWindowThreadProcessId(hwnd, &mut pid);
        if pid == GetCurrentProcessId() {
            let state = &mut *(lparam as *mut EnumState);
            if state.hwnd_any == 0 {
                state.hwnd_any = hwnd;
            }
            if GetWindowTextLengthW(hwnd) > 0 {
                state.hwnd_with_title = hwnd;
                return 0; // Found main window with non-empty title; stop enum
            }
        }
        1
    }

    pub fn find_launcher_hwnd(fallback_title: &str) -> isize {
        let mut state = EnumState::default();
        unsafe {
            EnumWindows(enum_window_callback, &mut state as *mut EnumState as isize);
        }
        if state.hwnd_with_title != 0 {
            return state.hwnd_with_title;
        }
        if state.hwnd_any != 0 {
            return state.hwnd_any;
        }
        use std::os::windows::ffi::OsStrExt;
        let wide: Vec<u16> = std::ffi::OsStr::new(fallback_title).encode_wide().chain(std::iter::once(0)).collect();
        unsafe { FindWindowW(std::ptr::null(), wide.as_ptr()) }
    }

    pub fn refocus_window(title: &str) {
        let hwnd = find_launcher_hwnd(title);
        if hwnd != 0 {
            unsafe {
                ShowWindow(hwnd, 9); // SW_RESTORE
                const HWND_TOP: isize = 0;
                const SWP_NOMOVE: u32 = 0x0002;
                const SWP_NOSIZE: u32 = 0x0001;
                const SWP_SHOWWINDOW: u32 = 0x0040;
                SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);

                let fore_hwnd = GetForegroundWindow();
                let fore_thread = GetWindowThreadProcessId(fore_hwnd, std::ptr::null_mut());
                let cur_thread = GetCurrentThreadId();
                if fore_thread != 0 && fore_thread != cur_thread {
                    AttachThreadInput(cur_thread, fore_thread, 1);
                    BringWindowToTop(hwnd);
                    SetForegroundWindow(hwnd);
                    AttachThreadInput(cur_thread, fore_thread, 0);
                } else {
                    BringWindowToTop(hwnd);
                    SetForegroundWindow(hwnd);
                }
            }
        }
    }
}

#[cfg(not(target_os = "windows"))]
mod win32 {
    pub fn refocus_window(_title: &str) {}
}

pub fn normalize_launch_progress(raw: f32) -> f32 {
    if raw.is_nan() || raw.is_infinite() {
        return 0.0;
    }
    let p = if raw > 1.0 { raw / 100.0 } else { raw };
    p.clamp(0.0, 1.0)
}

fn restore_and_refocus_window(win: &MainWindow) {
    let _ = win.show();
    win.window().set_minimized(false);
    win32::refocus_window("Ny-Luna");
    win32::refocus_window("New Launcher");
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // 1. Locate repository / app root dynamically
    let project_root = {
        let mut r = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        if let Ok(exe) = std::env::current_exe() {
            if let Some(parent) = exe.parent() {
                if parent.join("agent.exe").exists() || parent.join("assets").exists() {
                    r = parent.to_path_buf();
                }
            }
        }
        if !r.join("agent.exe").exists() && !r.join("agent.py").exists() && !r.join("src").join("backend").join("agent.py").exists() {
            if let Some(p) = r.parent() {
                if p.join("agent.py").exists() || p.join("src").join("backend").join("agent.py").exists() {
                    r = p.to_path_buf();
                }
            }
        }
        if !r.join("agent.exe").exists() && !r.join("agent.py").exists() && !r.join("src").join("backend").join("agent.py").exists() {
            if let Ok(exe) = std::env::current_exe() {
                for anc in exe.ancestors() {
                    if anc.join("agent.exe").exists() || anc.join("agent.py").exists() || anc.join("src").join("backend").join("agent.py").exists() {
                        r = anc.to_path_buf();
                        break;
                    }
                }
            }
        }
        r
    };
    println!("[NLC-Rust] Resolved project root: {:?}", project_root);

    let rt = tokio::runtime::Handle::current();

    // 2. Initialize Slint Window
    let main_window = MainWindow::new()?;
    #[cfg(target_os = "linux")]
    {
        if let Err(e) = slint::set_xdg_app_id("nlc") {
            eprintln!("[NLC-Rust] Failed to set XDG app id: {:?}", e);
        }
        std::env::remove_var("DESKTOP_STARTUP_ID");
        std::env::remove_var("XDG_ACTIVATION_TOKEN");
    }
    let (init_ram_mb, init_ram_str) = detect_system_ram();
    main_window.set_total_system_ram_mb(init_ram_mb);
    main_window.set_total_system_ram_str(init_ram_str.into());

    // Support snapshot mode for automated verification
    let args: Vec<String> = std::env::args().collect();
    if args.len() >= 4 && args[1] == "--snapshot-tab" {
        let _anim_state = animations::init_animations_state(&project_root);
        let _anim_controller = _anim_state.as_ref().map(|s| animations::start_animation_controllers(&main_window, s.clone()));
        let tab_name = args[2].clone();
        let out_path = args[3].clone();
        let is_maximized = args.iter().any(|a| a == "--maximized" || a == "-m");
        let mut wait_ms = if is_maximized { 800 } else { 500 };
        if tab_name == "Splash" || tab_name == "Startup" || tab_name == "Loading" {
            main_window.set_startup_splash_active(true);
            main_window.set_startup_splash_ready(false);
            main_window.set_startup_splash_progress(0.65);
            main_window.set_startup_splash_status("Loading accounts and wardrobe...".into());
            wait_ms = 1000;
        } else {
            main_window.set_startup_splash_ready(true);
            main_window.set_startup_splash_active(false);
            if tab_name == "Notifications" {
                main_window.set_notifications_open(true);
            } else if tab_name == "Toast" {
                main_window.set_current_tab("Play".into());
                main_window.set_toast_visible(true);
                main_window.set_toast_title("Sodium 0.6.0-fabric".into());
                main_window.set_toast_detail("downloading 68% (4.2 MB/s)".into());
                main_window.set_toast_progress(68.0);
            main_window.set_toast_status("normal".into());
        } else if tab_name == "Play-Launching" {
            main_window.set_current_tab("Play".into());
            main_window.set_is_launching(true);
            main_window.set_launch_progress(27.0);
            main_window.set_launch_log_text("Downloading assets (27/100)...".into());
        } else if tab_name == "AccountModal" || tab_name == "AddAccount" {
            main_window.set_current_tab("Play".into());
            main_window.set_add_account_modal_open(true);
            main_window.set_add_account_modal_mode("select".into());
        } else if tab_name == "AccountModal-Microsoft" {
            main_window.set_current_tab("Play".into());
            main_window.set_add_account_modal_open(true);
            main_window.set_add_account_modal_mode("microsoft".into());
            main_window.set_ms_user_code("FD8R-34LM".into());
            main_window.set_ms_verification_uri("https://microsoft.com/link".into());
            main_window.set_ms_status("1. Open verification link\n2. Enter code shown\n3. Sign in with Microsoft".into());
        } else if tab_name == "AccountModal-ElyBy" {
            main_window.set_current_tab("Play".into());
            main_window.set_add_account_modal_open(true);
            main_window.set_add_account_modal_mode("elyby".into());
            main_window.set_elyby_username("notch".into());
        } else if tab_name == "AccountModal-Offline" {
            main_window.set_current_tab("Play".into());
            main_window.set_add_account_modal_open(true);
            main_window.set_add_account_modal_mode("offline".into());
            main_window.set_offline_username("Alex".into());
        } else if tab_name == "Modrinth" || tab_name == "Mods" {
            main_window.set_current_tab("Modrinth".into());
            main_window.set_sidebar_mode("modrinth".into());
            wait_ms = 4000;
            main_window.set_current_modrinth_mode("mod".into());
            main_window.set_modrinth_selected_loader("All".into());
            main_window.set_modrinth_selected_version("All".into());
            main_window.set_modrinth_selected_sort("Relevance".into());
            let dummy_projects = vec![
                ModrinthProjectData {
                    id: "sodium".into(),
                    slug: "sodium".into(),
                    title: "Sodium".into(),
                    description: "A modern rendering engine for Minecraft that greatly improves frame rates and reduces micro-stutter.".into(),
                    author: "jellysquid3".into(),
                    downloads: "42.1M".into(),
                    follows: "156K".into(),
                    project_type: "mod".into(),
                    loaders: "fabric, quilt".into(),
                    versions: "1.21.4, 1.21.3".into(),
                    icon_url: "".into(),
                    install_status: "idle".into(),
                    has_icon: false,
                    icon: slint::Image::default(),
                },
                ModrinthProjectData {
                    id: "iris".into(),
                    slug: "iris".into(),
                    title: "Iris Shaders".into(),
                    description: "A modern shaders mod for Minecraft compatible with existing OptiFine shader packs.".into(),
                    author: "coderbot".into(),
                    downloads: "31.4M".into(),
                    follows: "98K".into(),
                    project_type: "mod".into(),
                    loaders: "fabric, quilt".into(),
                    versions: "1.21.4, 1.21.3".into(),
                    icon_url: "".into(),
                    install_status: "installed".into(),
                    has_icon: false,
                    icon: slint::Image::default(),
                },
            ];
            main_window.set_modrinth_projects(std::rc::Rc::new(slint::VecModel::from(dummy_projects)).into());
        } else if tab_name == "Modrinth-Loading" {
            main_window.set_current_tab("Modrinth".into());
            main_window.set_sidebar_mode("modrinth".into());
            main_window.set_current_modrinth_mode("modpack".into());
            main_window.set_modrinth_is_loading(true);
            main_window.set_modrinth_projects(std::rc::Rc::new(slint::VecModel::default()).into());
            wait_ms = 1500;
        } else if tab_name == "Modrinth-Modpacks" {
            main_window.set_current_tab("Modrinth".into());
            main_window.set_sidebar_mode("modrinth".into());
            main_window.set_current_modrinth_mode("modpack".into());
            main_window.set_modrinth_selected_loader("All".into());
            wait_ms = 4500;
        } else if tab_name == "StealModal" || tab_name == "StealSkin" {
            main_window.set_current_tab("Locker".into());
            main_window.set_steal_modal_open(true);
            main_window.set_steal_username_input("Technoblade".into());
            main_window.set_steal_preview_username("Technoblade".into());
            main_window.set_steal_preview_model("classic".into());
            main_window.set_steal_has_preview(true);
            wait_ms = 4000;
            let win_init = main_window.as_weak();
            let root_init = project_root.clone();
            tokio::spawn(async move {
                if let Ok(agent) = AgentClient::spawn(root_init).await {
                    let req = ipc::SkinRenderFrameRequest {
                        skin_path: None,
                        cape_path: None,
                        yaw_deg: 25.0,
                        pitch_deg: 5.0,
                        walk_phase: 0.0,
                        width: 240,
                        height: 280,
                        model: "classic".into(),
                    };
                    if let Ok(res) = agent.render_skin_frame(req).await {
                        if let Some((w, h, raw)) = decode_b64_to_rgba(&res.image_base64) {
                            let _ = slint::invoke_from_event_loop(move || {
                                if let Some(w_win) = win_init.upgrade() {
                                    let mut buffer = slint::SharedPixelBuffer::<slint::Rgba8Pixel>::new(w, h);
                                    buffer.make_mut_bytes().copy_from_slice(&raw);
                                    w_win.set_steal_preview_image(slint::Image::from_rgba8(buffer));
                                }
                            });
                        }
                    }
                }
            });
        } else if tab_name == "Locker" || tab_name == "Locker-Wallpapers" || tab_name == "Wallpapers" {
            main_window.set_current_tab("Locker".into());
            if tab_name == "Locker-Wallpapers" || tab_name == "Wallpapers" {
                main_window.set_locker_active_subtab("Wallpapers".into());
            }
            wait_ms = 8500;
            let win_init = main_window.as_weak();
            let root_init = project_root.clone();
            tokio::spawn(async move {
                match AgentClient::spawn(root_init).await {
                    Ok(agent) => {
                        let skin_info = agent.get_skin(ipc::GetSkinRequest::default()).await.ok();
                        let skin_model = skin_info.as_ref().and_then(|s| s.skin_model.clone()).unwrap_or_else(|| "classic".to_string());
                        let skin_path = skin_info.as_ref().and_then(|s| s.skin_path.clone());
                        let cape_path = skin_info.as_ref().and_then(|s| s.cape_path.clone());
                        let win_arm = win_init.clone();
                        let m_copy = skin_model.clone();
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_arm.upgrade() {
                                w.set_locker_model(m_copy.into());
                            }
                        });
                        let req = ipc::SkinRenderFrameRequest {
                            skin_path,
                            cape_path,
                            yaw_deg: 30.0,
                            pitch_deg: 10.0,
                            walk_phase: 0.0,
                            width: 320,
                            height: 380,
                            model: skin_model,
                        };
                        match agent.render_skin_frame(req).await {
                            Ok(res) => {
                                if let Some((w, h, raw_bytes)) = decode_b64_to_rgba(&res.image_base64) {
                                    let win_inner = win_init.clone();
                                    let _ = slint::invoke_from_event_loop(move || {
                                        if let Some(win) = win_inner.upgrade() {
                                            let mut buffer = slint::SharedPixelBuffer::<slint::Rgba8Pixel>::new(w, h);
                                            buffer.make_mut_bytes().copy_from_slice(&raw_bytes);
                                            win.set_skin_preview_image(slint::Image::from_rgba8(buffer));
                                            println!("[NLC-Rust] 3D Skin preview frame rendered successfully onto viewport ({}x{}).", w, h);
                                        }
                                    });
                                }
                            }
                            Err(e) => eprintln!("[NLC-Rust] render_skin_frame failed: {}", e),
                        }
                        refresh_locker_capes(&agent, win_init.clone()).await;
                        refresh_locker_presets(&agent, win_init.clone()).await;
                        refresh_wallpapers_roster(&agent, win_init.clone()).await;
                    }
                    Err(e) => eprintln!("[NLC-Rust] AgentClient::spawn failed: {}", e),
                }
            });
        } else if tab_name == "Installations" {
            main_window.set_current_tab("Installations".into());
            wait_ms = 4500;
            let win_init = main_window.as_weak();
            let root_init = project_root.clone();
            tokio::spawn(async move {
                if let Ok(agent) = AgentClient::spawn(root_init.clone()).await {
                    if let Ok(items) = agent.list_instances().await {
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_init.upgrade() {
                                let slint_items: Vec<InstallationData> = items.iter().map(|i| map_installation(i, &root_init)).collect();
                                let choice_items: Vec<InstallationChoice> = items.iter().map(map_installation_choice).collect();
                                w.set_installations(std::rc::Rc::new(slint::VecModel::from(slint_items.clone())).into());
                                w.set_compatible_installations(std::rc::Rc::new(slint::VecModel::from(choice_items)).into());
                                if let Some(first) = slint_items.first() {
                                    w.set_selected_instance(first.name.clone());
                                    w.set_selected_installation_id(first.id.clone());
                                }
                            }
                        });
                    }
                }
            });
        } else if tab_name == "Modpacks" || tab_name == "Modpacks-Mods-Grid" || tab_name == "Modpacks-Mods-List" {
            main_window.set_current_tab("Modpacks".into());
            let is_mods_grid = tab_name == "Modpacks-Mods-Grid";
            let is_mods_list = tab_name == "Modpacks-Mods-List";
            let is_mods = is_mods_grid || is_mods_list;
            if is_mods {
                main_window.set_modpack_view_mode("mods".into());
                main_window.set_modpack_mods_layout(if is_mods_list { "list".into() } else { "grid".into() });
                main_window.set_modpack_title("Fabulously Optimized".into());
                main_window.set_modpack_loader("Fabric".into());
                main_window.set_modpack_version("1.21.1".into());
            }
            wait_ms = 4500;
            let win_init = main_window.as_weak();
            let root_init = project_root.clone();
            tokio::spawn(async move {
                if let Ok(agent) = AgentClient::spawn(root_init).await {
                    if is_mods {
                        if let Ok(mods) = agent.list_pack_mods("fabulously-optimized").await {
                            let _ = slint::invoke_from_event_loop(move || {
                                if let Some(w) = win_init.upgrade() {
                                    let slint_mods = apply_mod_filter(&mods, "", "all");
                                    w.set_modpack_mods(std::rc::Rc::new(slint::VecModel::from(slint_mods)).into());
                                }
                            });
                        }
                    } else {
                        if let Ok(packs) = agent.list_modpacks().await {
                            let _ = slint::invoke_from_event_loop(move || {
                                if let Some(w) = win_init.upgrade() {
                                    let slint_packs: Vec<ModpackData> = packs.iter().map(map_modpack).collect();
                                    sync_modrinth_destinations(&w, &slint_packs);
                                    w.set_modpacks(std::rc::Rc::new(slint::VecModel::from(slint_packs)).into());
                                }
                            });
                        }
                    }
                }
            });
        } else if tab_name == "Addons" || tab_name == "Addons-MostPlayed" {
            main_window.set_current_tab("Addons".into());
            let (streamer_mode, saved_servers_count, gh_repo) = get_addons_config_state();
            let all_addons = get_builtin_addons(streamer_mode, saved_servers_count, &gh_repo);
            sync_raw_addons_to_ui(&main_window, all_addons, false);
            if tab_name == "Addons-MostPlayed" {
                main_window.set_has_top_inst_1(true);
                main_window.set_top_inst_1_name("Fabulously Optimized".into());
                main_window.set_top_inst_1_time("2h 0m".into());
                if let Some(img) = load_image_safely(&resolve_icon_path("grass_block_side", &project_root)) {
                    main_window.set_top_inst_1_icon(img);
                }
            }
            wait_ms = 2500;
        } else if tab_name == "Addons-ServerManager" {
            main_window.set_current_tab("Addons".into());
            let (streamer_mode, saved_servers_count, gh_repo) = get_addons_config_state();
            let all_addons = get_builtin_addons(streamer_mode, saved_servers_count, &gh_repo);
            sync_raw_addons_to_ui(&main_window, all_addons, false);
            main_window.set_server_manager_open(true);
            let win_init = main_window.as_weak();
            let root_init = project_root.clone();
            tokio::spawn(async move {
                if let Ok(agent) = AgentClient::spawn(root_init).await {
                    refresh_and_ping_saved_servers(Some(&agent), win_init).await;
                }
            });
            wait_ms = 4000;
        } else if tab_name == "Settings" || tab_name == "Settings-Memory" || tab_name == "Settings-Close" || tab_name == "Settings-Integrations" || tab_name == "Settings-Discord-Server" || tab_name == "Settings-Discord-Launcher" {
            main_window.set_current_tab("Settings".into());
            if tab_name == "Settings-Memory" {
                main_window.set_current_settings_cat("Java & Memory".into());
            } else if tab_name == "Settings-Close" {
                main_window.set_post_launch_action("Close".into());
            } else if tab_name == "Settings-Integrations" {
                main_window.set_current_settings_cat("Integrations".into());
                main_window.set_discord_connected(true);
                main_window.set_discord_status("CONNECTED".into());
                main_window.set_discord_preview_mode("game".into());
            } else if tab_name == "Settings-Discord-Server" {
                main_window.set_current_settings_cat("Integrations".into());
                main_window.set_discord_connected(true);
                main_window.set_discord_status("CONNECTED".into());
                main_window.set_discord_preview_mode("server".into());
            } else if tab_name == "Settings-Discord-Launcher" {
                main_window.set_current_settings_cat("Integrations".into());
                main_window.set_discord_connected(false);
                main_window.set_discord_status("DISCORD NOT DETECTED".into());
                main_window.set_discord_preview_mode("launcher".into());
            }
            wait_ms = 1500;
        } else {
            main_window.set_current_tab(tab_name.into());
        }
        }
        if is_maximized {
            main_window.window().set_size(slint::PhysicalSize::new(1920, 1080));
            main_window.window().set_maximized(true);
        } else if let Some(pos) = args.iter().position(|a| a == "--width") {
            if let Some(w_str) = args.get(pos + 1) {
                if let Ok(w) = w_str.parse::<u32>() {
                    let h = args.get(pos + 3).and_then(|s| s.parse::<u32>().ok()).unwrap_or(720);
                    main_window.window().set_size(slint::PhysicalSize::new(w, h));
                }
            }
        }
        main_window.show()?;
        if is_maximized {
            main_window.window().set_size(slint::PhysicalSize::new(1920, 1080));
            main_window.window().set_maximized(true);
        }

        let win_weak = main_window.as_weak();
        slint::Timer::single_shot(std::time::Duration::from_millis(wait_ms), move || {
            if let Some(win) = win_weak.upgrade() {
                match win.window().take_snapshot() {
                    Ok(pix) => {
                        let w = pix.width();
                        let h = pix.height();
                        let raw_bytes: Vec<u8> = pix.as_slice().iter().flat_map(|p| [p.r, p.g, p.b, p.a]).collect();
                        if let Some(img) = image::RgbaImage::from_raw(w, h, raw_bytes) {
                            let _ = img.save(&out_path);
                            println!("[NLC-Rust] Saved snapshot to: {}", out_path);
                        }
                    }
                    Err(e) => {
                        eprintln!("[NLC-Rust] take_snapshot failed: {:?}", e);
                    }
                }
                let _ = slint::quit_event_loop();
            }
        });

        main_window.run()?;
        return Ok(());
    }


    let agent_close_holder: Arc<std::sync::Mutex<Option<Arc<AgentClient>>>> = Arc::new(std::sync::Mutex::new(None));
    let agent_close_cb = agent_close_holder.clone();
    let agent_quit_cb = agent_close_holder.clone();

    // Native Slint System Tray Integration
    let tray = match AppTray::new() {
        Ok(t) => {
            let win_weak_tray = main_window.as_weak();
            let win_weak_quit = main_window.as_weak();
            t.on_show_window(move || {
                if let Some(win) = win_weak_tray.upgrade() {
                    let _ = win.show();
                    win.window().set_minimized(false);
                }
            });
            t.on_quit_app(move || {
                if let Some(win) = win_weak_quit.upgrade() {
                    let _ = win.hide();
                }
                let maybe_ag = agent_quit_cb.lock().unwrap().clone();
                if let Some(agent) = maybe_ag {
                    tokio::spawn(async move {
                        agent.shutdown().await;
                        std::process::exit(0);
                    });
                } else {
                    std::process::exit(0);
                }
            });
            Some(t)
        }
        Err(e) => {
            eprintln!("[NLC-Rust] Warning: Could not initialize system tray icon (headless or unsupported environment): {:?}", e);
            None
        }
    };

    // Window controls
    let win_weak_min = main_window.as_weak();
    main_window.on_minimize_window(move || {
        if let Some(win) = win_weak_min.upgrade() {
            win.window().set_minimized(true);
        }
    });

    let win_weak_max = main_window.as_weak();
    main_window.on_maximize_window(move || {
        if let Some(win) = win_weak_max.upgrade() {
            let is_max = win.window().is_maximized();
            win.window().set_maximized(!is_max);
        }
    });

    let win_weak_move = main_window.as_weak();
    main_window.on_move_window(move |dx, dy| {
        if let Some(win) = win_weak_move.upgrade() {
            let pos = win.window().position();
            let new_pos = slint::PhysicalPosition::new(pos.x + dx as i32, pos.y + dy as i32);
            win.window().set_position(new_pos);
        }
    });

    let win_weak_close = main_window.as_weak();
    main_window.on_close_window(move || {
        if let Some(win) = win_weak_close.upgrade() {
            if win.get_minimize_to_tray() {
                #[cfg(target_os = "linux")]
                {
                    if std::env::var_os("WAYLAND_DISPLAY").is_some() {
                        win.window().set_minimized(true);
                    } else {
                        let _ = win.hide();
                    }
                }
                #[cfg(not(target_os = "linux"))]
                {
                    let _ = win.hide();
                }
            } else {
                let _ = win.hide();
                let maybe_ag = agent_close_cb.lock().unwrap().clone();
                if let Some(agent) = maybe_ag {
                    tokio::spawn(async move {
                        let _ = tokio::time::timeout(
                            tokio::time::Duration::from_millis(1500),
                            agent.call::<serde_json::Value>("skin_flush_mojang", serde_json::json!({}))
                        ).await;
                        agent.shutdown().await;
                        std::process::exit(0);
                    });
                } else {
                    std::process::exit(0);
                }
            }
        }
    });

    // 3. Spawn background agent IPC client with immediate visual presentation
    main_window.set_startup_splash_active(true);
    main_window.set_startup_splash_progress(0.20);
    main_window.set_startup_splash_status("Starting Ny-Luna...".into());
    let _ = main_window.show();
    main_window.window().set_maximized(true);

    let agent_result = AgentClient::spawn(project_root.clone()).await;

    let agent_client = match agent_result {
        Ok(client) => {
            println!("[NLC-Rust] Connected to headless Python backend.");
            main_window.set_startup_splash_progress(0.40);
            main_window.set_startup_splash_status("Loading configuration and profiles...".into());
            Some(Arc::new(client))
        }
        Err(err) => {
            eprintln!("[NLC-Rust] Warning: Could not connect to Python agent: {}", err);
            main_window.set_startup_splash_progress(0.40);
            main_window.set_startup_splash_status("Starting offline mode...".into());
            None
        }
    };
    *agent_close_holder.lock().unwrap() = agent_client.clone();

    // 4. Wire Background Push Event Listener
    let active_sessions_tracker = Arc::new(std::sync::Mutex::new(Vec::<ActiveSessionItem>::new()));

    if let Some(ref agent) = agent_client {
        let mut event_rx = agent.subscribe_events();
        let win_weak_events = main_window.as_weak();
        let root_dir_events = project_root.clone();
        let agent_events = agent.clone();
        let active_sessions_tracker_events = active_sessions_tracker.clone();
        tokio::spawn(async move {
            loop {
                match event_rx.recv().await {
                    Ok(event) => {
                        let win_weak_inner = win_weak_events.clone();
                        let root_dir_inner = root_dir_events.clone();
                        let agent_inner = agent_events.clone();
                        match event.event.as_str() {
                            "ms_auth_completed" => {
                                let status = event.payload.get("status").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                if status == "success" {
                                    let win_weak = win_weak_inner.clone();
                                    let _ = slint::invoke_from_event_loop(move || {
                                        if let Some(win) = win_weak.upgrade() {
                                            win.set_ms_status("Login Successful!".into());
                                        }
                                    });
                                    tokio::time::sleep(tokio::time::Duration::from_millis(600)).await;
                                    refresh_accounts_roster(&agent_inner, win_weak_inner.clone()).await;
                                    let win_weak = win_weak_inner.clone();
                                    let _ = slint::invoke_from_event_loop(move || {
                                        if let Some(w) = win_weak.upgrade() {
                                            w.set_add_account_modal_open(false);
                                            w.set_ms_user_code("".into());
                                        }
                                    });
                                } else {
                                    let err = event.payload.get("message").and_then(|v| v.as_str()).unwrap_or("Microsoft login failed").to_string();
                                    let win_weak = win_weak_inner.clone();
                                    let _ = slint::invoke_from_event_loop(move || {
                                        if let Some(win) = win_weak.upgrade() {
                                            win.set_ms_status(format!("Error: {}", err).into());
                                            win.set_add_account_error(err.into());
                                        }
                                    });
                                }
                            }
                            "discord_status_changed" => {
                                let connected = event.payload.get("connected").and_then(|v| v.as_bool()).unwrap_or(false);
                                let status_text = event.payload.get("status_text").and_then(|v| v.as_str()).unwrap_or("Not Connected").to_string();
                                let win_weak = win_weak_inner.clone();
                                let _ = slint::invoke_from_event_loop(move || {
                                    if let Some(win) = win_weak.upgrade() {
                                        win.set_discord_connected(connected);
                                        win.set_discord_status(status_text.into());
                                    }
                                });
                            }
                            "launch_state_changed" | "launch_state" => {
                                let state = event
                                    .payload
                                    .get("state")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("")
                                    .to_string();
                                let msg = event
                                    .payload
                                    .get("message")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("")
                                    .to_string();
                                let progress = event
                                    .payload
                                    .get("progress")
                                    .and_then(|v| v.as_f64())
                                    .unwrap_or(0.0) as f32;
                                let launch_id = event
                                    .payload
                                    .get("launch_id")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("")
                                    .to_string();
                                let instance_id = event
                                    .payload
                                    .get("instance_id")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("")
                                    .to_string();
                                let instance_name = event
                                    .payload
                                    .get("instance_name")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("")
                                    .to_string();
                                let version = event
                                    .payload
                                    .get("version")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("")
                                    .to_string();
                                let loader = event
                                    .payload
                                    .get("loader")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("Vanilla")
                                    .to_string();
                                let effective_id = if !launch_id.is_empty() {
                                    launch_id.clone()
                                } else if !instance_id.is_empty() {
                                    instance_id.clone()
                                } else {
                                    format!("session-{}", version)
                                };

                                if state == "running" {
                                    if let Ok(mut list) = active_sessions_tracker_events.lock() {
                                        if let Some(existing) = list.iter_mut().find(|s| {
                                            s.id == effective_id
                                                || (!launch_id.is_empty() && s.id == launch_id)
                                                || (!instance_id.is_empty() && s.id == instance_id)
                                        }) {
                                            if !instance_name.is_empty() {
                                                existing.name = instance_name.clone();
                                            }
                                            if !version.is_empty() {
                                                existing.version = version.clone();
                                            }
                                            if !loader.is_empty() {
                                                existing.loader = loader.clone();
                                            }
                                        } else {
                                            let display_name = if !instance_name.is_empty() {
                                                instance_name.clone()
                                            } else if !version.is_empty() {
                                                format!("Minecraft {}", version)
                                            } else {
                                                "Minecraft Session".to_string()
                                            };
                                            let icon_path = resolve_icon_path(
                                                if !instance_id.is_empty() { &instance_id } else { &version },
                                                &root_dir_inner,
                                            );
                                            list.push(ActiveSessionItem {
                                                id: effective_id.clone(),
                                                name: display_name,
                                                version: version.clone(),
                                                loader: if loader.is_empty() { "Vanilla".to_string() } else { loader.clone() },
                                                started_at: std::time::Instant::now(),
                                                icon_path,
                                            });
                                        }
                                    }
                                } else if state == "stopped" || state == "exited" || state == "error" {
                                    if let Ok(mut list) = active_sessions_tracker_events.lock() {
                                        list.retain(|s| {
                                            let match_launch = !launch_id.is_empty() && s.id == launch_id;
                                            let match_instance = !instance_id.is_empty() && s.id == instance_id;
                                            let match_eff = !effective_id.is_empty() && s.id == effective_id;
                                            !(match_launch || match_instance || match_eff)
                                        });
                                    }
                                }

                                let is_active = !matches!(state.as_str(), "running" | "exited" | "stopped" | "error");
                                let win_weak = win_weak_inner.clone();
                                let tracker_ui = active_sessions_tracker_events.clone();
                                let _ = slint::invoke_from_event_loop(move || {
                                    if let Some(win) = win_weak.upgrade() {
                                        sync_active_sessions_to_ui(&win, &tracker_ui);
                                        win.set_is_launching(is_active);
                                        win.set_launch_progress(normalize_launch_progress(progress));
                                        if !msg.is_empty() {
                                            win.set_launch_log_text(msg.clone().into());
                                        }
                                        if is_active {
                                            // Launch progress is tracked via bottom bar 2px progress line
                                        } else if state == "running" {
                                            win.set_launch_progress(0.0);
                                            let action = win.get_post_launch_action();
                                            let action_str = action.as_str().trim();
                                            println!("[NLC-Rust] Executing post-launch behavior: '{}'", action_str);
                                            match action_str {
                                                "Minimise to taskbar" | "minimize_taskbar" => {
                                                    win.window().set_minimized(true);
                                                }
                                                "Minimise to tray" | "minimize_tray" => {
                                                    #[cfg(target_os = "linux")]
                                                    {
                                                        if std::env::var_os("WAYLAND_DISPLAY").is_some() {
                                                            win.window().set_minimized(true);
                                                        } else {
                                                            let _ = win.hide();
                                                        }
                                                    }
                                                    #[cfg(not(target_os = "linux"))]
                                                    {
                                                        let _ = win.hide();
                                                    }
                                                }
                                                "Close" | "close" => {
                                                    let _ = win.hide();
                                                    std::process::exit(0);
                                                }
                                                _ => {
                                                    // "Do nothing" | "do_nothing" | other: keep launcher open
                                                }
                                            }
                                        } else if state == "error" {
                                            win.set_launch_progress(0.0);
                                            win.set_toast_visible(true);
                                            let lower_msg = msg.to_lowercase();
                                            let (err_title, err_detail, err_status) = if lower_msg.contains("cancelled") || lower_msg.contains("canceled") {
                                                ("Launch Cancelled", "Game launch was aborted.", "warning")
                                            } else {
                                                ("Launch Failed", if msg.is_empty() { "Failed to launch Minecraft instance." } else { &msg }, "error")
                                            };
                                            win.set_toast_title(err_title.into());
                                            win.set_toast_detail(err_detail.into());
                                            win.set_toast_status(err_status.into());
                                            show_toast_notification(&win, &get_toast_tracker(), "launch-progress", err_title, err_detail, err_status, 0.0, false, &msg);
                                        } else if state == "stopped" || state == "exited" {
                                            win.set_launch_progress(0.0);
                                            win.set_launch_log_text("".into());
                                            win.set_toast_visible(false);
                                            if let Ok(mut list) = get_toast_tracker().lock() {
                                                list.retain(|t| t.id != "launch-progress");
                                                sync_toasts_to_ui(&win, &list);
                                            }
                                            let action = win.get_post_launch_action();
                                            let action_str = action.as_str().trim();
                                            if action_str == "Minimise to taskbar"
                                                || action_str == "minimize_taskbar"
                                                || action_str == "Minimise to tray"
                                                || action_str == "minimize_tray"
                                                || win.get_minimize_to_tray()
                                            {
                                                restore_and_refocus_window(&win);
                                            }
                                        }
                                    }
                                });
                            }
                            "game_log" => {
                                if let Some(line) = event.payload.get("line").and_then(|v| v.as_str()) {
                                    let line_str = line.to_string();
                                    let win_weak = win_weak_inner.clone();
                                    let _ = slint::invoke_from_event_loop(move || {
                                        if let Some(win) = win_weak.upgrade() {
                                            if win.get_is_launching() {
                                                win.set_launch_log_text(line_str.into());
                                            }
                                        }
                                    });
                                }
                            }
                            "game_session_ended" => {
                                let launch_id = event
                                    .payload
                                    .get("launch_id")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("")
                                    .to_string();
                                let instance_id = event
                                    .payload
                                    .get("instance_id")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("")
                                    .to_string();
                                if let Ok(mut list) = active_sessions_tracker_events.lock() {
                                    list.retain(|s| {
                                        let match_launch = !launch_id.is_empty() && s.id == launch_id;
                                        let match_instance = !instance_id.is_empty() && s.id == instance_id;
                                        !(match_launch || match_instance)
                                    });
                                }
                                let tracker_ui = active_sessions_tracker_events.clone();
                                let win_weak = win_weak_inner.clone();
                                let _ = slint::invoke_from_event_loop(move || {
                                    if let Some(win) = win_weak.upgrade() {
                                        sync_active_sessions_to_ui(&win, &tracker_ui);
                                        let action = win.get_post_launch_action();
                                        let action_str = action.as_str().trim();
                                        if action_str == "Minimise to taskbar"
                                            || action_str == "minimize_taskbar"
                                            || action_str == "Minimise to tray"
                                            || action_str == "minimize_tray"
                                            || win.get_minimize_to_tray()
                                        {
                                            restore_and_refocus_window(&win);
                                        }
                                    }
                                });
                                update_playtime_stats_in_ui(&agent_inner, win_weak_inner.clone(), &root_dir_inner).await;
                            }
                            "config_changed" => {
                                if let Some(key) = event.payload.get("key").and_then(|k| k.as_str()) {
                                    if key == "active_profile" {
                                        if let Some(name) = event
                                            .payload
                                            .get("value")
                                            .and_then(|v| v.get("name"))
                                            .and_then(|n| n.as_str())
                                            .map(|s| s.to_string())
                                        {
                                            let win_weak = win_weak_inner.clone();
                                            let _ = slint::invoke_from_event_loop(move || {
                                                if let Some(win) = win_weak.upgrade() {
                                                    win.set_username(name.into());
                                                }
                                            });
                                        }
                                    } else if key == "profiles" || key == "active_profile_index" || key == "active_account" {
                                        refresh_accounts_roster(&agent_inner, win_weak_inner.clone()).await;
                                    } else if key == "installations" {
                                        if let Some(val) = event.payload.get("value") {
                                            if let Ok(items) = serde_json::from_value::<Vec<ipc::InstallationItem>>(val.clone()) {
                                                let win_weak = win_weak_inner.clone();
                                                let root_dir = root_dir_inner.clone();
                                                let _ = slint::invoke_from_event_loop(move || {
                                                    if let Some(win) = win_weak.upgrade() {
                                                        let slint_items: Vec<InstallationData> = items.iter().map(|i| map_installation(i, &root_dir)).collect();
                                                        let choice_items: Vec<InstallationChoice> = items.iter().map(map_installation_choice).collect();
                                                        win.set_installations(std::rc::Rc::new(slint::VecModel::from(slint_items)).into());
                                                        win.set_compatible_installations(std::rc::Rc::new(slint::VecModel::from(choice_items)).into());
                                                        sync_modrinth_destinations(&win, &[]);
                                                    }
                                                });
                                            }
                                        }
                                    }
                                }
                            }
                            "modpacks_changed" => {
                                if let Some(val) = event.payload.get("modpacks") {
                                    if let Ok(packs) = serde_json::from_value::<Vec<ipc::ModpackItem>>(val.clone()) {
                                        let win_weak = win_weak_inner.clone();
                                        let _ = slint::invoke_from_event_loop(move || {
                                            if let Some(win) = win_weak.upgrade() {
                                                let slint_packs: Vec<ModpackData> = packs.iter().map(map_modpack).collect();
                                                sync_modrinth_destinations(&win, &slint_packs);
                                                win.set_modpacks(std::rc::Rc::new(slint::VecModel::from(slint_packs)).into());
                                            }
                                        });
                                    }
                                }
                            }
                            "download_progress" => {
                                let status = event.payload.get("status").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                let filename = event.payload.get("filename").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                let pct = event.payload.get("percentage").or(event.payload.get("progress")).and_then(|v| v.as_f64()).unwrap_or(0.0);
                                let speed = event.payload.get("speed").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                let err_msg = event.payload.get("message").and_then(|v| v.as_str()).unwrap_or("Download failed").to_string();
                                let task_id = event.payload.get("task_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                let project_id = event.payload.get("project_id").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                let current_file = event.payload.get("current_file").and_then(|v| v.as_i64()).unwrap_or(0);
                                let total_files = event.payload.get("total_files").and_then(|v| v.as_i64()).unwrap_or(0);
                                let detail = event.payload.get("detail").and_then(|v| v.as_str()).unwrap_or("").to_string();

                                let notif_id = if !task_id.is_empty() {
                                    format!("dl-task-{}", task_id)
                                } else if !project_id.is_empty() {
                                    format!("dl-proj-{}", project_id)
                                } else {
                                    format!("dl-file-{}", filename)
                                };

                                let payload_title = event.payload.get("title").and_then(|v| v.as_str()).unwrap_or("");
                                let display_title = if !payload_title.is_empty() {
                                    payload_title.to_string()
                                } else if !project_id.is_empty() {
                                    project_id.clone()
                                } else if !filename.is_empty() {
                                    filename.clone()
                                } else {
                                    "Download".to_string()
                                };

                                let win_weak = win_weak_inner.clone();
                                let _ = slint::invoke_from_event_loop(move || {
                                    if let Some(win) = win_weak.upgrade() {
                                        let is_sticky = status != "completed" && status != "error" && status != "failed";
                                        let toast_status = if status == "completed" {
                                            "completed"
                                        } else if status == "error" || status == "failed" {
                                            "error"
                                        } else {
                                            "normal"
                                        };

                                        let (toast_detail, notif_desc) = if status == "completed" {
                                            let d = if total_files > 1 {
                                                format!("Installed {} mods successfully ✓", total_files)
                                            } else {
                                                "Completed ✓".to_string()
                                            };
                                            (d.clone(), d)
                                        } else if status == "error" || status == "failed" {
                                            (err_msg.clone(), err_msg.clone())
                                        } else {
                                            let d = if total_files > 1 {
                                                if !detail.is_empty() {
                                                    detail.clone()
                                                } else {
                                                    format!("Downloading {}/{} mods ({:.0}%)", current_file, total_files, pct)
                                                }
                                            } else if !detail.is_empty() {
                                                detail.clone()
                                            } else if !speed.is_empty() {
                                                format!("{:.0}% ({})", pct, speed)
                                            } else {
                                                format!("{:.0}%", pct)
                                            };
                                            (d.clone(), d)
                                        };

                                        push_toast_with_progress(
                                            &win,
                                            &notif_id,
                                            &display_title,
                                            &toast_detail,
                                            toast_status,
                                            pct as f32,
                                            is_sticky,
                                            &err_msg,
                                        );

                                        // Keep legacy toast properties populated for fallback
                                        win.set_toast_visible(true);
                                        win.set_toast_title(display_title.clone().into());
                                        win.set_toast_detail(toast_detail.clone().into());
                                        win.set_toast_progress(pct as f32);
                                        win.set_toast_status(toast_status.into());

                                        // Update Notification Center (aggregated: single card updated in-place)
                                        if status == "completed" || status == "error" || status == "failed" || total_files > 1 {
                                            push_or_update_notification(
                                                &win,
                                                &notif_id,
                                                "Downloads",
                                                &display_title,
                                                &notif_desc,
                                                "Just now",
                                                false,
                                            );
                                        }
                                        if status == "completed" {
                                            win.set_modrinth_status_text(format!("Downloaded {} ✓", display_title).into());
                                            win.set_modrinth_details_install_status("installed".into());
                                        } else if status != "error" && status != "failed" {
                                            win.set_modrinth_status_text(toast_detail.into());
                                        }
                                    }
                                });
                            }
                            "agent_disconnected" => {
                                let win_weak = win_weak_inner.clone();
                                let _ = slint::invoke_from_event_loop(move || {
                                    if let Some(win) = win_weak.upgrade() {
                                        win.set_is_launching(false);
                                    }
                                });
                            }
                            _ => {}
                        }
                    }
                    Err(tokio::sync::broadcast::error::RecvError::Lagged(missed)) => {
                        eprintln!("[NLC-Rust] Warning: Event subscriber lagged, missed {} events", missed);
                    }
                    Err(tokio::sync::broadcast::error::RecvError::Closed) => {
                        println!("[NLC-Rust] Agent event broadcast channel closed");
                        break;
                    }
                }
            }
        });
    }

    // Shared search state for Modrinth lazy loading / pagination
    let search_state = Arc::new(tokio::sync::Mutex::new(ModrinthSearchState {
        mode: "mod".to_string(),
        sort: "downloads".to_string(),
        offset: 20,
        has_more: true,
        ..Default::default()
    }));

    // Shared state for Addons screen
    let state_addons = Arc::new(tokio::sync::Mutex::new(AddonsViewState::default()));
    let modpack_tutorial_tracker = Arc::new(std::sync::atomic::AtomicBool::new(false));

    // 5. Initial state synchronization with Python agent
    if let Some(ref agent) = agent_client {
        let agent_init = agent.clone();
        let win_weak_init = main_window.as_weak();
        let root_dir_init = project_root.clone();
        let state_addons_init = state_addons.clone();
        let modpack_tut_init = modpack_tutorial_tracker.clone();
        tokio::spawn(async move {
            let win_splash_st1 = win_weak_init.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(w) = win_splash_st1.upgrade() {
                    w.set_startup_splash_progress(0.60);
                    w.set_startup_splash_status("Loading configuration and profiles...".into());
                }
            });

            // 1. Concurrently fetch essential startup data in parallel
            let (cfg_res, _, inst_res, loaders_res, vers_res, packs_res, _, _) = tokio::join!(
                agent_init.get_config(),
                refresh_accounts_roster(&agent_init, win_weak_init.clone()),
                agent_init.list_instances(),
                agent_init.list_loaders(),
                agent_init.list_versions("Vanilla", false),
                agent_init.list_modpacks(),
                update_playtime_stats_in_ui(&agent_init, win_weak_init.clone(), &root_dir_init),
                refresh_addons_roster(Some(&agent_init), win_weak_init.clone(), state_addons_init.clone(), &root_dir_init),
            );

            // Request initial Discord status
            let agent_discord_init = agent_init.clone();
            let win_weak_discord = win_weak_init.clone();
            tokio::spawn(async move {
                if let Ok(res) = agent_discord_init.get_discord_status().await {
                    let connected = res.get("connected").and_then(|v| v.as_bool()).unwrap_or(false);
                    let status_text = res.get("status_text").and_then(|v| v.as_str()).unwrap_or("Not Connected").to_string();
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak_discord.upgrade() {
                            w.set_discord_connected(connected);
                            w.set_discord_status(status_text.into());
                        }
                    });
                }
            });

            // 2. Apply config
            let mut active_inst_id_from_cfg: Option<String> = None;
            if let Ok(ref cfg) = cfg_res {
                let first_run_completed = cfg.first_run_completed.unwrap_or(false);
                let tut_done = cfg.modpack_tutorial_completed.unwrap_or(false);
                modpack_tut_init.store(tut_done, std::sync::atomic::Ordering::Relaxed);
                let cfg_clone = cfg.clone();
                active_inst_id_from_cfg = cfg.extra.get("active_installation_id")
                    .or_else(|| cfg.extra.get("active_instance"))
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string());
                let win_weak_inner = win_weak_init.clone();
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_weak_inner.upgrade() {
                        sync_settings_to_ui(&cfg_clone, &w);
                        if !first_run_completed {
                            w.set_onboarding_wizard_step(1);
                            w.set_onboarding_wizard_open(true);
                        }
                    }
                });
            }

            // 3. Apply installations
            if let Ok(ref items) = inst_res {
                let win_weak_inner = win_weak_init.clone();
                let root_dir = root_dir_init.clone();
                let chosen_cfg_id = active_inst_id_from_cfg.clone();
                let items_clone = items.clone();
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_weak_inner.upgrade() {
                        let slint_items: Vec<InstallationData> = items_clone.iter().map(|i| map_installation(i, &root_dir)).collect();
                        let choice_items: Vec<InstallationChoice> = items_clone.iter().map(map_installation_choice).collect();
                        w.set_installations(std::rc::Rc::new(slint::VecModel::from(slint_items.clone())).into());
                        w.set_compatible_installations(std::rc::Rc::new(slint::VecModel::from(choice_items)).into());
                        sync_modrinth_destinations(&w, &[]);

                        let target_inst = if let Some(ref tid) = chosen_cfg_id {
                            slint_items.iter().find(|i| i.id == tid.as_str() || i.name == tid.as_str()).or_else(|| slint_items.first())
                        } else {
                            slint_items.first()
                        };

                        if let Some(chosen) = target_inst {
                            w.set_selected_instance(chosen.name.clone());
                            w.set_selected_version(chosen.version.clone());
                            w.set_selected_installation_id(chosen.id.clone());
                            w.set_selected_loader(chosen.loader.clone());
                            w.set_selected_instance_icon(chosen.icon.clone());
                            let v_disp = if chosen.loader != "" && chosen.loader != "Vanilla" {
                                format!("{} {}", chosen.loader, chosen.version)
                            } else if chosen.version == "latest-release" {
                                "Vanilla 1.21.4 (Latest Release)".to_string()
                            } else {
                                format!("Vanilla {}", chosen.version)
                            };
                            w.set_selected_version_display(v_disp.into());
                        }
                    }
                });
            }

            // 4. Apply loaders
            if let Ok(ref loaders_resp) = loaders_res {
                let loaders: Vec<slint::SharedString> = loaders_resp.loaders.iter().map(|s| s.as_str().into()).collect();
                let mp_loaders: Vec<slint::SharedString> = loaders_resp.modpack_loaders.iter().map(|s| s.as_str().into()).collect();
                let win_weak_inner = win_weak_init.clone();
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_weak_inner.upgrade() {
                        if !loaders.is_empty() {
                            w.set_available_loaders(std::rc::Rc::new(slint::VecModel::from(loaders)).into());
                        }
                        if !mp_loaders.is_empty() {
                            w.set_modpack_loaders(std::rc::Rc::new(slint::VecModel::from(mp_loaders)).into());
                        }
                    }
                });
            }

            // 5. Apply versions
            if let Ok(ref versions_resp) = vers_res {
                let versions: Vec<slint::SharedString> = versions_resp.releases.iter().map(|s| s.as_str().into()).collect();
                let count = versions.len();
                let latest = versions_resp.latest_release.clone().or_else(|| versions_resp.releases.first().cloned()).unwrap_or_else(|| "1.21.4".to_string());
                let win_weak_inner = win_weak_init.clone();
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_weak_inner.upgrade() {
                        if !versions.is_empty() {
                            w.set_available_versions(std::rc::Rc::new(slint::VecModel::from(versions)).into());
                            w.set_version_fetch_status(format!("Found {} Vanilla versions", count).into());
                        }
                        if w.get_selected_version() == "latest-release" {
                            w.set_selected_version_display(format!("Vanilla {} (Latest Release)", latest).into());
                        }
                    }
                });
            }

            // 6. Apply modpacks
            if let Ok(ref packs) = packs_res {
                let win_weak_inner = win_weak_init.clone();
                let packs_clone = packs.clone();
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_weak_inner.upgrade() {
                        let slint_packs: Vec<ModpackData> = packs_clone.iter().map(map_modpack).collect();
                        sync_modrinth_destinations(&w, &slint_packs);
                        w.set_modpacks(std::rc::Rc::new(slint::VecModel::from(slint_packs)).into());
                    }
                });
            }

            // 7. Ready! Signal splash to finish current cycle and smoothly fade into content
            let win_splash_fin = win_weak_init.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(w) = win_splash_fin.upgrade() {
                    w.set_startup_splash_progress(1.0);
                    w.set_startup_splash_status("Ready!".into());
                    w.set_startup_splash_ready(true);
                }
            });

            // Watchdog fallback to ensure splash is never permanently stuck
            let win_splash_dismiss = win_weak_init.clone();
            tokio::spawn(async move {
                tokio::time::sleep(tokio::time::Duration::from_secs(6)).await;
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_splash_dismiss.upgrade() {
                        if w.get_startup_splash_active() {
                            w.set_startup_splash_active(false);
                        }
                    }
                });
            });

            // 8. Non-blocking background warmup for wardrobe and mods
            let agent_bg = agent_init.clone();
            let win_weak_bg = win_weak_init.clone();
            tokio::spawn(async move {
                refresh_locker_capes(&agent_bg, win_weak_bg.clone()).await;
                refresh_locker_presets(&agent_bg, win_weak_bg.clone()).await;
                refresh_wallpapers_roster(&agent_bg, win_weak_bg.clone()).await;
                if let Ok(mods) = agent_bg.list_pack_mods("fabulously-optimized").await {
                    let win_inner = win_weak_bg.clone();
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_inner.upgrade() {
                            let slint_mods: Vec<ModCardData> = mods.iter().enumerate().map(|(idx, m)| map_mod_card(m, idx)).collect();
                            w.set_modpack_mods(std::rc::Rc::new(slint::VecModel::from(slint_mods)).into());
                        }
                    });
                }
            });
        });
    }

    if agent_client.is_none() {
        let win_weak_fallback = main_window.as_weak();
        let state_addons_fallback = state_addons.clone();
        let root_dir_fallback = project_root.clone();
        tokio::spawn(async move {
            refresh_addons_roster(None, win_weak_fallback.clone(), state_addons_fallback, &root_dir_fallback).await;
            tokio::time::sleep(tokio::time::Duration::from_millis(1200)).await;
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(w) = win_weak_fallback.upgrade() {
                    w.set_startup_splash_progress(1.0);
                    w.set_startup_splash_status("Ready!".into());
                    w.set_startup_splash_ready(true);
                }
            });
        });
    }

    // Initialize 3D Skin Viewport State
    let skin_state = Arc::new(tokio::sync::Mutex::new(SkinViewState {
        yaw: 30.0,
        pitch: 10.0,
        walk_phase: 0.0,
        is_walking: false,
        model: "classic".to_string(),
        skin_path: None,
        cape_path: None,
        is_fetching: false,
    }));

    if let Some(ref agent) = agent_client {
        let ag_skin = agent.clone();
        let win_skin = main_window.as_weak();
        let state_skin = skin_state.clone();
        tokio::spawn(async move {
            tokio::time::sleep(tokio::time::Duration::from_millis(50)).await;
            if let Ok(info) = ag_skin.get_skin(ipc::GetSkinRequest::default()).await {
                let model = info.skin_model.unwrap_or_else(|| "classic".to_string());
                {
                    let mut s = state_skin.lock().await;
                    s.skin_path = info.skin_path;
                    s.cape_path = info.cape_path;
                    s.model = model.clone();
                }
                let win_inner = win_skin.clone();
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_inner.upgrade() {
                        w.set_locker_model(model.into());
                    }
                });
            }
            trigger_skin_render(ag_skin, win_skin, state_skin).await;
        });
    }

    // 5b. Wire 3D Skin Preview Callbacks
    let win_weak_drag = main_window.as_weak();
    let agent_client_drag = agent_client.clone();
    let skin_state_drag = skin_state.clone();
    let rt_skin_drag = rt.clone();
    main_window.on_skin_drag(move |dx, dy| {
        if let Some(ref agent) = agent_client_drag {
            let ag = agent.clone();
            let win = win_weak_drag.clone();
            let state = skin_state_drag.clone();
            rt_skin_drag.spawn(async move {
                {
                    let mut s = state.lock().await;
                    s.yaw = (s.yaw - dx * 0.8) % 360.0;
                    if s.yaw < 0.0 { s.yaw += 360.0; }
                    s.pitch = (s.pitch + dy * 0.5).clamp(-60.0, 60.0);
                }
                trigger_skin_render(ag, win, state).await;
            });
        }
    });

    let win_weak_reset = main_window.as_weak();
    let agent_client_reset = agent_client.clone();
    let skin_state_reset = skin_state.clone();
    let rt_skin_reset = rt.clone();
    main_window.on_skin_reset_view(move |mode| {
        if let Some(ref agent) = agent_client_reset {
            let ag = agent.clone();
            let win = win_weak_reset.clone();
            let state = skin_state_reset.clone();
            let mode_str = mode.as_str().to_lowercase();
            rt_skin_reset.spawn(async move {
                {
                    let mut s = state.lock().await;
                    match mode_str.as_str() {
                        "front" => { s.yaw = 0.0; s.pitch = 0.0; }
                        "back" => { s.yaw = 180.0; s.pitch = 0.0; }
                        _ => { s.yaw = 30.0; s.pitch = 10.0; }
                    }
                }
                trigger_skin_render(ag, win, state).await;
            });
        }
    });

    let win_weak_walk = main_window.as_weak();
    let agent_client_walk = agent_client.clone();
    let skin_state_walk = skin_state.clone();
    let rt_skin_walk = rt.clone();
    main_window.on_skin_toggle_walk(move || {
        if let Some(ref agent) = agent_client_walk {
            let ag = agent.clone();
            let win = win_weak_walk.clone();
            let state = skin_state_walk.clone();
            rt_skin_walk.spawn(async move {
                let is_now_walking = {
                    let mut s = state.lock().await;
                    s.is_walking = !s.is_walking;
                    if !s.is_walking {
                        s.walk_phase = 0.0;
                    }
                    s.is_walking
                };
                let win_inner = win.clone();
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_inner.upgrade() {
                        w.set_is_walking(is_now_walking);
                    }
                });
                trigger_skin_render(ag, win, state).await;
            });
        }
    });

    // Continuous walking animation driven by native Slint LockerScreen Timer
    let win_weak_tick = main_window.as_weak();
    let agent_client_tick = agent_client.clone();
    let skin_state_tick = skin_state.clone();
    let rt_tick = rt.clone();
    main_window.on_skin_walk_tick(move || {
        if let Some(ref agent) = agent_client_tick {
            let ag = agent.clone();
            let win = win_weak_tick.clone();
            let state = skin_state_tick.clone();
            rt_tick.spawn(async move {
                {
                    let mut s = state.lock().await;
                    s.walk_phase += 0.28;
                    if s.walk_phase > 2.0 * std::f32::consts::PI {
                        s.walk_phase -= 2.0 * std::f32::consts::PI;
                    }
                }
                trigger_skin_render(ag, win, state).await;
            });
        }
    });

    let win_weak_model = main_window.as_weak();
    let agent_client_model = agent_client.clone();
    let skin_state_model = skin_state.clone();
    let rt_model = rt.clone();
    main_window.on_skin_model_changed(move |model| {
        let model_str = model.to_string();
        println!("[NLC-Rust] Skin model changed to: {}", model_str);
        let win = win_weak_model.clone();
        let agent = agent_client_model.clone();
        let state = skin_state_model.clone();
        rt_model.spawn(async move {
            {
                let mut s = state.lock().await;
                s.model = model_str.clone();
            }
            if let Some(ref ag) = agent {
                let _ = ag.call::<serde_json::Value>("skin_model_set", serde_json::json!({
                    "model": model_str
                })).await;
                trigger_skin_render(ag.clone(), win.clone(), state.clone()).await;
            }
        });
    });

    // Defer Mojang skin upload until leaving Locker tab & auto-fetch Modrinth content when first opened
    let prev_tab_tracker = Arc::new(std::sync::Mutex::new(main_window.get_current_tab().to_string()));
    let prev_tab_cb = prev_tab_tracker.clone();
    let agent_client_tab = agent_client.clone();
    let win_weak_tab_change = main_window.as_weak();
    let modpack_tut_tab = modpack_tutorial_tracker.clone();
    main_window.on_tab_changed(move |new_tab| {
        let new_tab_str = new_tab.to_string();
        let was_locker = {
            let mut guard = prev_tab_cb.lock().unwrap();
            let was = *guard == "Locker";
            *guard = new_tab_str.clone();
            was
        };
        if was_locker && new_tab_str != "Locker" {
            println!("[NLC-Rust] Left Locker tab -> flushing pending Mojang skin upload");
            if let Some(ref agent) = agent_client_tab {
                let ag = agent.clone();
                tokio::spawn(async move {
                    let _ = ag.call::<serde_json::Value>("skin_flush_mojang", serde_json::json!({})).await;
                });
            }
        }

        // Sync Discord RPC idle state with active tab
        if let Some(ref agent) = agent_client_tab {
            let ag = agent.clone();
            let tab_for_rpc = new_tab_str.clone();
            tokio::spawn(async move {
                let _ = ag.call::<serde_json::Value>("discord_set_screen", serde_json::json!({ "screen": tab_for_rpc })).await;
            });
        }
        if new_tab_str == "Mods" || new_tab_str == "Modrinth" {
            let win_weak = win_weak_tab_change.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(w) = win_weak.upgrade() {
                    if w.get_modrinth_projects().row_count() == 0 && !w.get_modrinth_is_loading() {
                        let mode = w.get_current_modrinth_mode();
                        let mode_str = if mode.is_empty() { "mod".into() } else { mode };
                        let query = w.get_modrinth_search_query();
                        let loader = w.get_modrinth_selected_loader();
                        let version = w.get_modrinth_selected_version();
                        let sort = w.get_modrinth_selected_sort();
                        w.set_modrinth_is_loading(true);
                        w.invoke_modrinth_search(query, mode_str, loader, version, sort);
                    }
                }
            });
        }
        if new_tab_str == "Modpacks" && !modpack_tut_tab.load(std::sync::atomic::Ordering::Relaxed) {
            modpack_tut_tab.store(true, std::sync::atomic::Ordering::Relaxed);
            let win_weak = win_weak_tab_change.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(w) = win_weak.upgrade() {
                    w.set_modpack_tutorial_open(true);
                }
            });
            if let Some(ref agent) = agent_client_tab {
                let ag = agent.clone();
                tokio::spawn(async move {
                    let _ = ag.set_config(serde_json::json!({ "modpack_tutorial_completed": true })).await;
                });
            }
        }
    });

    let win_weak_toggle_inj = main_window.as_weak();
    let agent_client_toggle_inj = agent_client.clone();
    let rt_toggle_inj = rt.clone();
    main_window.on_toggle_offline_injection(move |enabled| {
        println!("[NLC-Rust] Offline skin injection toggled: {}", enabled);
        let win = win_weak_toggle_inj.clone();
        let _ = slint::invoke_from_event_loop(move || {
            if let Some(w) = win.upgrade() {
                w.set_offline_skin_injection(enabled);
                let msg = if enabled {
                    "Offline skin injection enabled"
                } else {
                    "Offline skin injection disabled"
                };
                push_toast(&w, "skin-inj", "Skin System", msg, "completed");
            }
        });
        let agent = agent_client_toggle_inj.clone();
        rt_toggle_inj.spawn(async move {
            if let Some(ref ag) = agent {
                let _ = ag.call::<serde_json::Value>("config_set", serde_json::json!({
                    "updates": {
                        "offline_skin_injection": enabled
                    }
                })).await;
            }
        });
    });

    let win_weak_cape = main_window.as_weak();
    let agent_client_cape = agent_client.clone();
    let skin_state_cape = skin_state.clone();
    let rt_cape = rt.clone();
    main_window.on_equip_cape(move |cape_id| {
        let id_str = cape_id.to_string();
        let win = win_weak_cape.clone();
        let acc_type = if let Some(w) = win.upgrade() {
            w.get_account_type().to_string()
        } else {
            String::new()
        };
        if !acc_type.to_lowercase().contains("microsoft") {
            println!("[NLC-Rust] Rejected cape selection: not a Microsoft account ({})", acc_type);
            let win_warn = win.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(w) = win_warn.upgrade() {
                    w.set_toast_visible(true);
                    w.set_toast_title("Capes Locked".into());
                    w.set_toast_detail("Capes are exclusively available for Microsoft accounts.".into());
                    w.set_toast_status("warning".into());
                    push_toast(&w, "cape-locked", "Capes Locked", "Capes are exclusively available for Microsoft accounts.", "warning");
                }
            });
            return;
        }
        println!("[NLC-Rust] Equipping cape: {}", id_str);
        let win_opt = win_weak_cape.clone();
        let _ = slint::invoke_from_event_loop(move || {
            if let Some(w) = win_opt.upgrade() {
                w.set_locker_has_active_cape(true);
            }
        });
        let agent = agent_client_cape.clone();
        let state = skin_state_cape.clone();
        rt_cape.spawn(async move {
            if let Some(ref ag) = agent {
                let _ = ag.call::<serde_json::Value>("capes_select", serde_json::json!({ "cape_id": id_str })).await;
                refresh_locker_capes(ag, win.clone()).await;
                if let Ok(skin_res) = ag.get_skin(ipc::GetSkinRequest::default()).await {
                    {
                        let mut s = state.lock().await;
                        s.cape_path = skin_res.cape_path;
                    }
                    trigger_skin_render(ag.clone(), win.clone(), state.clone()).await;
                }
            }
        });
    });

    let win_weak_uncape = main_window.as_weak();
    let agent_client_uncape = agent_client.clone();
    let skin_state_uncape = skin_state.clone();
    let rt_uncape = rt.clone();
    main_window.on_unequip_cape(move || {
        println!("[NLC-Rust] Unequipping active cape");
        let win = win_weak_uncape.clone();
        let win_opt = win_weak_uncape.clone();
        let _ = slint::invoke_from_event_loop(move || {
            if let Some(w) = win_opt.upgrade() {
                w.set_locker_has_active_cape(false);
            }
        });
        let agent = agent_client_uncape.clone();
        let state = skin_state_uncape.clone();
        rt_uncape.spawn(async move {
            if let Some(ref ag) = agent {
                let _ = ag.call::<serde_json::Value>("capes_select", serde_json::json!({ "cape_id": "" })).await;
                refresh_locker_capes(ag, win.clone()).await;
                {
                    let mut s = state.lock().await;
                    s.cape_path = None;
                }
                trigger_skin_render(ag.clone(), win.clone(), state.clone()).await;
            }
        });
    });

    let win_weak_preset = main_window.as_weak();
    let agent_client_preset = agent_client.clone();
    let skin_state_preset = skin_state.clone();
    let rt_preset = rt.clone();
    main_window.on_equip_skin_preset(move |preset_id| {
        let p_str = preset_id.to_string();
        let win = win_weak_preset.clone();
        let agent = agent_client_preset.clone();
        let state = skin_state_preset.clone();
        rt_preset.spawn(async move {
            if let Some(ref ag) = agent {
                let _ = ag.call::<serde_json::Value>("skin_set_custom", serde_json::json!({ "skin_path": p_str.clone() })).await;
                refresh_locker_presets(ag, win.clone()).await;
                refresh_accounts_roster(ag, win.clone()).await;
                if let Ok(skin_res) = ag.get_skin(ipc::GetSkinRequest::default()).await {
                    let m = skin_res.skin_model.unwrap_or_else(|| "classic".to_string());
                    {
                        let mut s = state.lock().await;
                        s.skin_path = Some(p_str);
                        s.model = m.clone();
                    }
                    let win_inner = win.clone();
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_inner.upgrade() {
                            w.set_locker_model(m.into());
                        }
                    });
                }
                trigger_skin_render(ag.clone(), win.clone(), state.clone()).await;
            }
        });
    });

    let win_weak_del_sk = main_window.as_weak();
    let agent_client_del_sk = agent_client.clone();
    let skin_state_del_sk = skin_state.clone();
    let rt_del_sk = rt.clone();
    main_window.on_delete_skin_preset(move |preset_id| {
        let p_str = preset_id.to_string();
        println!("[NLC-Rust] Deleting skin preset: {}", p_str);
        let win = win_weak_del_sk.clone();
        let agent = agent_client_del_sk.clone();
        let state = skin_state_del_sk.clone();
        rt_del_sk.spawn(async move {
            if let Some(ref ag) = agent {
                if std::path::Path::new(&p_str).exists() {
                    let _ = std::fs::remove_file(&p_str);
                }
                refresh_locker_presets(ag, win.clone()).await;
                trigger_skin_render(ag.clone(), win.clone(), state.clone()).await;
            }
        });
    });

    let win_weak_up = main_window.as_weak();
    let agent_client_up = agent_client.clone();
    let skin_state_up = skin_state.clone();
    let rt_up = rt.clone();
    main_window.on_upload_skin(move || {
        println!("[NLC-Rust] Upload skin requested");
        let win = win_weak_up.clone();
        let agent = agent_client_up.clone();
        let state = skin_state_up.clone();
        rt_up.spawn(async move {
            if let Some(path) = prompt_open_file("Minecraft Skin (*.png)|*.png") {
                    if !path.is_empty() && std::path::Path::new(&path).exists() {
                        if let Some(ref ag) = agent {
                            let curr_model = {
                                let s = state.lock().await;
                                s.model.clone()
                            };
                            let _ = ag.call::<serde_json::Value>("skin_set_custom", serde_json::json!({ "skin_path": path.clone(), "model": curr_model })).await;
                            refresh_locker_presets(ag, win.clone()).await;
                            refresh_accounts_roster(ag, win.clone()).await;
                            if let Ok(skin_res) = ag.get_skin(ipc::GetSkinRequest::default()).await {
                                let m = skin_res.skin_model.unwrap_or(curr_model);
                                {
                                    let mut s = state.lock().await;
                                    s.skin_path = skin_res.skin_path;
                                    s.model = m.clone();
                                }
                                let win_inner = win.clone();
                                let _ = slint::invoke_from_event_loop(move || {
                                    if let Some(w) = win_inner.upgrade() {
                                        w.set_locker_model(m.into());
                                    }
                                });
                            }
                            trigger_skin_render(ag.clone(), win.clone(), state.clone()).await;
                            let _ = slint::invoke_from_event_loop(move || {
                                if let Some(w) = win.upgrade() {
                                    w.set_toast_visible(true);
                                    w.set_toast_title("Skin Uploaded".into());
                                    w.set_toast_detail("Custom skin applied to preview stage ✓".into());
                                    w.set_toast_status("completed".into());
                                    push_toast(&w, "skin-upload", "Skin Uploaded", "Custom skin applied to preview stage ✓", "completed");
                                }
                            });
                        }
                    }
                }
        });
    });

    let win_weak_steal = main_window.as_weak();
    main_window.on_steal_skin(move || {
        println!("[NLC-Rust] Steal skin modal opened");
        if let Some(w) = win_weak_steal.upgrade() {
            w.set_steal_modal_open(true);
            w.set_steal_username_input("".into());
            w.set_steal_has_preview(false);
            w.set_steal_is_loading(false);
            w.set_steal_status_message("".into());
            w.set_steal_preview_username("".into());
        }
    });

    let win_weak_st_close = main_window.as_weak();
    main_window.on_steal_close_modal(move || {
        if let Some(w) = win_weak_st_close.upgrade() {
            w.set_steal_modal_open(false);
            w.set_steal_has_preview(false);
            w.set_steal_is_loading(false);
            w.set_steal_status_message("".into());
        }
    });

    let win_weak_st_fetch = main_window.as_weak();
    let agent_client_st_fetch = agent_client.clone();
    let rt_st_fetch = rt.clone();
    main_window.on_steal_preview_fetch(move |uname_val| {
        let u_str = uname_val.trim().to_string();
        if u_str.is_empty() { return; }
        let win = win_weak_st_fetch.clone();
        let agent = agent_client_st_fetch.clone();
        let _ = slint::invoke_from_event_loop({
            let win = win.clone();
            move || {
                if let Some(w) = win.upgrade() {
                    w.set_steal_is_loading(true);
                    w.set_steal_status_message("".into());
                }
            }
        });
        rt_st_fetch.spawn(async move {
            if let Some(ref ag) = agent {
                let res = ag.call::<serde_json::Value>("skin_steal_preview", serde_json::json!({ "username": u_str })).await;
                match res {
                    Ok(data) => {
                        let b64 = data.get("preview_base64").and_then(|v| v.as_str()).unwrap_or("");
                        let model = data.get("model").and_then(|v| v.as_str()).unwrap_or("classic").to_string();
                        let decoded = decode_b64_to_rgba(b64);
                        let win_ui = win.clone();
                        let u_copy = u_str.clone();
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_ui.upgrade() {
                                w.set_steal_is_loading(false);
                                if let Some((width, height, raw)) = decoded {
                                    let mut buffer = slint::SharedPixelBuffer::<slint::Rgba8Pixel>::new(width, height);
                                    buffer.make_mut_bytes().copy_from_slice(&raw);
                                    w.set_steal_preview_image(slint::Image::from_rgba8(buffer));
                                    w.set_steal_has_preview(true);
                                    w.set_steal_preview_model(model.into());
                                    w.set_steal_preview_username(u_copy.into());
                                } else {
                                    w.set_steal_has_preview(false);
                                    w.set_steal_status_message("Failed to decode preview image.".into());
                                }
                            }
                        });
                    }
                    Err(_e) => {
                        let err_msg = format!("Player '{}' not found or skin unavailable.", u_str);
                        let win_ui = win.clone();
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_ui.upgrade() {
                                w.set_steal_is_loading(false);
                                w.set_steal_has_preview(false);
                                w.set_steal_status_message(err_msg.into());
                            }
                        });
                    }
                }
            }
        });
    });

    let win_weak_st_confirm = main_window.as_weak();
    let agent_client_st_confirm = agent_client.clone();
    let skin_state_st_confirm = skin_state.clone();
    let rt_st_confirm = rt.clone();
    main_window.on_steal_confirm_download(move || {
        let win = win_weak_st_confirm.clone();
        let agent = agent_client_st_confirm.clone();
        let state = skin_state_st_confirm.clone();
        let (u_str, m_str) = {
            if let Some(w) = win.upgrade() {
                (w.get_steal_preview_username().to_string(), w.get_steal_preview_model().to_string())
            } else {
                (String::new(), String::new())
            }
        };
        if u_str.is_empty() { return; }
        rt_st_confirm.spawn(async move {
            if let Some(ref ag) = agent {
                let res = ag.call::<serde_json::Value>("skin_steal", serde_json::json!({
                    "username": u_str,
                    "model": m_str
                })).await;
                match res {
                    Ok(data) => {
                        let s_path = data.get("skin_path").and_then(|v| v.as_str()).unwrap_or("").to_string();
                        let s_model = data.get("model").and_then(|v| v.as_str()).unwrap_or("classic").to_string();
                        refresh_locker_presets(ag, win.clone()).await;
                        refresh_accounts_roster(ag, win.clone()).await;
                        {
                            let mut s = state.lock().await;
                            if !s_path.is_empty() {
                                s.skin_path = Some(s_path);
                            }
                            s.model = s_model.clone();
                        }
                        let win_inner = win.clone();
                        let u_display = u_str.clone();
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_inner.upgrade() {
                                w.set_steal_modal_open(false);
                                w.set_locker_model(s_model.into());
                                w.set_toast_visible(true);
                                w.set_toast_title("Skin Acquired".into());
                                w.set_toast_detail(format!("Successfully applied skin for {} ✓", u_display).into());
                                w.set_toast_status("completed".into());
                                push_toast(&w, "skin-steal", "Skin Acquired", &format!("Successfully applied skin for {} ✓", u_display), "completed");
                            }
                        });
                        trigger_skin_render(ag.clone(), win.clone(), state.clone()).await;
                    }
                    Err(e) => {
                        let win_inner = win.clone();
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_inner.upgrade() {
                                w.set_steal_status_message(format!("Failed to save skin: {:?}", e).into());
                            }
                        });
                    }
                }
            }
        });
    });

    let agent_client_exp_sk = agent_client.clone();
    let skin_state_exp_sk = skin_state.clone();
    let rt_exp_sk = rt.clone();
    main_window.on_export_skin(move || {
        println!("[NLC-Rust] Export skin requested");
        let _agent = agent_client_exp_sk.clone();
        let state = skin_state_exp_sk.clone();
        rt_exp_sk.spawn(async move {
            let src = {
                let s = state.lock().await;
                s.skin_path.clone()
            };
            if let Some(src_path) = src {
                if let Some(dest_path) = prompt_save_file("skin_export.png", "Minecraft Skin (*.png)|*.png") {
                    if let Err(e) = std::fs::copy(&src_path, &dest_path) {
                        eprintln!("[NLC-Rust] Failed to export skin to {}: {}", dest_path, e);
                    } else {
                        println!("[NLC-Rust] Successfully exported skin to: {}", dest_path);
                    }
                }
            }
        });
    });

    let win_weak_ref_sk = main_window.as_weak();
    let agent_client_ref_sk = agent_client.clone();
    let skin_state_ref_sk = skin_state.clone();
    let rt_ref_sk = rt.clone();
    main_window.on_refresh_skin(move || {
        println!("[NLC-Rust] Refreshing 3D skin stage");
        let win = win_weak_ref_sk.clone();
        let agent = agent_client_ref_sk.clone();
        let state = skin_state_ref_sk.clone();
        rt_ref_sk.spawn(async move {
            if let Some(ref ag) = agent {
                {
                    let mut s = state.lock().await;
                    s.yaw = 30.0;
                    s.pitch = 0.0;
                }
                trigger_skin_render(ag.clone(), win.clone(), state.clone()).await;
            }
        });
    });

    main_window.on_open_skins_folder(move || {
        let path = paths::get_launcher_data_dir().join("skins");
        let _ = std::fs::create_dir_all(&path);
        #[cfg(windows)]
        let _ = std::process::Command::new("explorer").arg(&path).spawn();
        #[cfg(not(windows))]
        let _ = std::process::Command::new("xdg-open").arg(&path).spawn();
    });

    // 5b. Wire Wallpapers Studio Handlers
    let win_weak_eq_wp = main_window.as_weak();
    let agent_client_eq_wp = agent_client.clone();
    let rt_eq_wp = rt.clone();
    main_window.on_equip_wallpaper(move |wp_path| {
        let p_str = wp_path.to_string();
        println!("[NLC-Rust] Equipping wallpaper: {}", p_str);
        let agent = agent_client_eq_wp.clone();
        let win = win_weak_eq_wp.clone();
        rt_eq_wp.spawn(async move {
            if let Some(ref ag) = agent {
                let _ = ag.call::<serde_json::Value>("wallpapers_set", serde_json::json!({
                    "path": p_str
                })).await;
                refresh_wallpapers_roster(ag, win).await;
            }
        });
    });

    let win_weak_dl_wp = main_window.as_weak();
    let agent_client_dl_wp = agent_client.clone();
    let rt_dl_wp = rt.clone();
    main_window.on_download_wallpaper(move |wp_id| {
        let id_str = wp_id.to_string();
        println!("[NLC-Rust] Downloading wallpaper on-demand: {}", id_str);
        let agent = agent_client_dl_wp.clone();
        let win = win_weak_dl_wp.clone();

        // Optimistically set downloading state on card
        let id_for_opt = id_str.clone();
        let _ = slint::invoke_from_event_loop(move || {
            if let Some(w) = win.upgrade() {
                let model = w.get_locker_wallpapers();
                for i in 0..model.row_count() {
                    if let Some(mut wp) = model.row_data(i) {
                        if wp.id.as_str() == id_for_opt.as_str() {
                            wp.is_downloading = true;
                            model.set_row_data(i, wp);
                            break;
                        }
                    }
                }
            }
        });

        let win_inner = win_weak_dl_wp.clone();
        rt_dl_wp.spawn(async move {
            if let Some(ref ag) = agent {
                let res: Result<serde_json::Value, _> = ag.call("wallpapers_download", serde_json::json!({
                    "filename": id_str
                })).await;
                println!("[NLC-Rust] Wallpaper download result: {:?}", res);
                refresh_wallpapers_roster(ag, win_inner.clone()).await;
            }
        });
    });

    let win_weak_up_wp = main_window.as_weak();
    let agent_client_up_wp = agent_client.clone();
    let rt_up_wp = rt.clone();
    main_window.on_upload_wallpaper(move || {
        let agent = agent_client_up_wp.clone();
        let win = win_weak_up_wp.clone();
        rt_up_wp.spawn(async move {
            if let Some(path) = prompt_open_file("Image Files (*.png;*.jpg;*.jpeg)|*.png;*.jpg;*.jpeg") {
                    if !path.is_empty() && std::path::Path::new(&path).exists() {
                        if let Some(ref ag) = agent {
                            let _ = ag.call::<serde_json::Value>("wallpapers_upload", serde_json::json!({
                                "path": path
                            })).await;
                            refresh_wallpapers_roster(ag, win).await;
                        }
                    }
                }
        });
    });

    let win_weak_del_wp = main_window.as_weak();
    let agent_client_del_wp = agent_client.clone();
    let rt_del_wp = rt.clone();
    main_window.on_delete_wallpaper(move |wp_path| {
        let p_str = wp_path.to_string();
        println!("[NLC-Rust] Deleting wallpaper: {}", p_str);
        let agent = agent_client_del_wp.clone();
        let win = win_weak_del_wp.clone();
        rt_del_wp.spawn(async move {
            if let Some(ref ag) = agent {
                let _ = ag.call::<serde_json::Value>("wallpapers_delete", serde_json::json!({
                    "path": p_str
                })).await;
                refresh_wallpapers_roster(ag, win).await;
            }
        });
    });

    let agent_client_fld_wp = agent_client.clone();
    let rt_fld_wp = rt.clone();
    main_window.on_open_wallpapers_folder(move || {
        let agent = agent_client_fld_wp.clone();
        rt_fld_wp.spawn(async move {
            if let Some(ref ag) = agent {
                let _ = ag.call::<serde_json::Value>("wallpapers_open_folder", serde_json::json!({})).await;
            }
        });
    });

    // 6. Wire Game Launch & Cancel Callbacks
    let win_weak_launch = main_window.as_weak();
    let agent_client_launch = agent_client.clone();
    let rt_launch = rt.clone();
    main_window.on_launch_game(move |inst_id, version, loader| {
        let inst_id_str = inst_id.to_string();
        let version_str = version.to_string();
        let loader_str = loader.to_string();
        println!("[NLC-Rust] Requesting game launch: inst_id={}, ver={}, loader={}", inst_id_str, version_str, loader_str);
        if let Some(win) = win_weak_launch.upgrade() {
            if win.get_accounts().row_count() == 0 {
                push_toast(
                    &win,
                    "no-account-warning",
                    "Account Required",
                    "Please add an account before launching Minecraft.",
                    "failed",
                );
                win.set_add_account_modal_mode("select".into());
                win.set_add_account_modal_open(true);
                return;
            }
            win.set_is_launching(true);
            win.set_launch_progress(0.0);
            win.set_launch_log_text(format!("Resolving {} ({})...", version_str, if loader_str.is_empty() { "Vanilla" } else { &loader_str }).into());
            let notif_id = format!("sess-{}", if !inst_id_str.is_empty() { &inst_id_str } else { &version_str });
            push_or_update_notification(
                &win,
                &notif_id,
                "Sessions",
                &format!("Launch: {} ({})", version_str, if loader_str.is_empty() { "Vanilla" } else { &loader_str }),
                "Game launch initiated",
                "Just now",
                false,
            );
        }

        let agent = agent_client_launch.clone();
        let win_weak_inner = win_weak_launch.clone();
        rt_launch.spawn(async move {
            if let Some(ref agent) = agent {
                let req = ipc::LaunchGameRequest {
                    version: version_str.clone(),
                    installation_id: if !inst_id_str.is_empty() { Some(inst_id_str.clone()) } else { None },
                    instance_id: if !inst_id_str.is_empty() { Some(inst_id_str) } else { None },
                    loader: if !loader_str.is_empty() { Some(loader_str) } else { None },
                    ..Default::default()
                };
                match agent.launch_game(req).await {
                    Ok(resp) => {
                        println!("[NLC-Rust] Launch initiated: status={}, id={:?}", resp.status, resp.launch_id);
                    }
                    Err(err) => {
                        eprintln!("[NLC-Rust] Launch failed: {}", err);
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_weak_inner.upgrade() {
                                w.set_is_launching(false);
                            }
                        });
                    }
                }
            } else {
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_weak_inner.upgrade() {
                        w.set_is_launching(false);
                    }
                });
            }
        });
    });

    let win_weak_force_launch = main_window.as_weak();
    let agent_client_force_launch = agent_client.clone();
    let rt_force_launch = rt.clone();
    main_window.on_force_update_and_play_game(move |inst_id, version, loader| {
        let inst_id_str = inst_id.to_string();
        let version_str = version.to_string();
        let loader_str = loader.to_string();
        println!("[NLC-Rust] Requesting force update & play: inst_id={}, ver={}, loader={}", inst_id_str, version_str, loader_str);
        if let Some(win) = win_weak_force_launch.upgrade() {
            win.set_is_launching(true);
            win.set_launch_progress(0.0);
            win.set_launch_log_text(format!("Force updating {} ({})...", version_str, if loader_str.is_empty() { "Vanilla" } else { &loader_str }).into());
            let notif_id = format!("sess-{}", if !inst_id_str.is_empty() { &inst_id_str } else { &version_str });
            push_or_update_notification(
                &win,
                &notif_id,
                "Sessions",
                &format!("Force Update & Launch: {} ({})", version_str, if loader_str.is_empty() { "Vanilla" } else { &loader_str }),
                "Clean reinstall and launch initiated",
                "Just now",
                false,
            );
        }

        let agent = agent_client_force_launch.clone();
        let win_weak_inner = win_weak_force_launch.clone();
        rt_force_launch.spawn(async move {
            if let Some(ref agent) = agent {
                let req = ipc::LaunchGameRequest {
                    version: version_str.clone(),
                    installation_id: if !inst_id_str.is_empty() { Some(inst_id_str.clone()) } else { None },
                    instance_id: if !inst_id_str.is_empty() { Some(inst_id_str) } else { None },
                    loader: if !loader_str.is_empty() { Some(loader_str) } else { None },
                    force_update: Some(true),
                    ..Default::default()
                };
                match agent.launch_game(req).await {
                    Ok(resp) => {
                        println!("[NLC-Rust] Force launch initiated: status={}, id={:?}", resp.status, resp.launch_id);
                    }
                    Err(err) => {
                        eprintln!("[NLC-Rust] Force launch failed: {}", err);
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_weak_inner.upgrade() {
                                w.set_is_launching(false);
                            }
                        });
                    }
                }
            } else {
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_weak_inner.upgrade() {
                        w.set_is_launching(false);
                    }
                });
            }
        });
    });

    let win_weak_cancel = main_window.as_weak();
    let agent_client_cancel = agent_client.clone();
    let rt_cancel = rt.clone();
    main_window.on_cancel_launch(move || {
        println!("[NLC-Rust] User requested cancel launch");
        if let Some(win) = win_weak_cancel.upgrade() {
            win.set_is_launching(false);
            win.set_launch_progress(0.0);
            win.set_launch_log_text("Launch aborted by user".into());
            win.set_toast_visible(false);
        }
        let agent = agent_client_cancel.clone();
        rt_cancel.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.call::<serde_json::Value>("cancel_launch", serde_json::json!({})).await;
            }
        });
    });

    // 7. Wire Account Switcher & Manager Callbacks
    let win_weak_sel = main_window.as_weak();
    let agent_client_sel = agent_client.clone();
    let skin_state_sel = skin_state.clone();
    let rt_sel = rt.clone();
    main_window.on_select_account(move |target_idx, account_name, account_id| {
        let name_str = account_name.to_string();
        let id_str = account_id.to_string();
        let idx_val = target_idx as usize;
        println!("[NLC-Rust] Selecting account #{} '{}' (id: '{}')", idx_val, name_str, id_str);
        let agent = agent_client_sel.clone();
        let win_weak_inner = win_weak_sel.clone();
        let state = skin_state_sel.clone();
        rt_sel.spawn(async move {
            if let Some(ref agent) = agent {
                let req = ipc::SelectAccountRequest {
                    id: if id_str.is_empty() { None } else { Some(id_str.clone()) },
                    index: Some(idx_val),
                    username: Some(name_str.clone()),
                };
                if let Ok(res) = agent.select_account(req).await {
                    println!("[NLC-Rust] Account selected: {:?}", res);
                    let _ = agent.set_config(serde_json::json!({ "username": name_str.clone(), "default_offline_name": name_str.clone() })).await;
                    refresh_accounts_roster(agent, win_weak_inner.clone()).await;

                    // Automatically update 3D skin preview for newly selected account!
                    if let Ok(skin_res) = agent.get_skin(ipc::GetSkinRequest::default()).await {
                        let new_model = skin_res.skin_model.clone().unwrap_or_else(|| "classic".to_string());
                        {
                            let mut s = state.lock().await;
                            s.skin_path = skin_res.skin_path;
                            s.model = new_model.clone();
                            s.cape_path = skin_res.cape_path;
                        }
                        let win_arm = win_weak_inner.clone();
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_arm.upgrade() {
                                w.set_locker_model(new_model.into());
                            }
                        });
                        trigger_skin_render(agent.clone(), win_weak_inner.clone(), state).await;
                    }
                    refresh_locker_presets(agent, win_weak_inner.clone()).await;
                }
            }
        });
    });

    let agent_client_acct_rm = agent_client.clone();
    let win_weak_acct_rm = main_window.as_weak();
    let rt_acct_rm = rt.clone();
    main_window.on_remove_account(move |target_idx, account_name, account_id| {
        let name_str = account_name.to_string();
        let id_str = account_id.to_string();
        let idx_val = target_idx as usize;
        println!("[NLC-Rust] Account removal requested for #{}: '{}' (id: '{}')", idx_val, name_str, id_str);
        let agent = agent_client_acct_rm.clone();
        let win_weak = win_weak_acct_rm.clone();
        rt_acct_rm.spawn(async move {
            if let Some(ref agent) = agent {
                let res = agent.remove_account_by_target(Some(idx_val), Some(&name_str), Some(&id_str)).await;
                println!("[NLC-Rust] Account removed: {:?}", res);
                refresh_accounts_roster(agent, win_weak).await;
            }
        });
    });

    let win_weak_chk = main_window.as_weak();
    main_window.on_check_username(move |name| {
        if let Some(w) = win_weak_chk.upgrade() {
            let trimmed = name.trim();
            if trimmed.is_empty() {
                w.set_username_validation_error("".into());
            } else {
                match validate_minecraft_username(trimmed) {
                    Ok(()) => w.set_username_validation_error("".into()),
                    Err(err) => w.set_username_validation_error(err.into()),
                }
            }
        }
    });

    let agent_client_acct_add = agent_client.clone();
    let win_weak_acct_add = main_window.as_weak();
    let skin_state_acct_add = skin_state.clone();
    let rt_acct_add = rt.clone();
    main_window.on_create_account(move |account_name| {
        let name_str = account_name.to_string();
        let win_val = win_weak_acct_add.clone();
        if let Err(err_msg) = validate_minecraft_username(&name_str) {
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(w) = win_val.upgrade() {
                    w.set_add_account_error(err_msg.into());
                    push_toast(&w, "account-invalid", "Invalid Username", err_msg, "warning");
                }
            });
            return;
        }

        println!("[NLC-Rust] Creating offline account: {}", name_str);
        let agent = agent_client_acct_add.clone();
        let win_weak = win_weak_acct_add.clone();
        let state = skin_state_acct_add.clone();
        rt_acct_add.spawn(async move {
            if let Some(ref agent) = agent {
                let add_res = agent.add_offline_account(&name_str).await;
                let (target_idx, target_uuid) = match add_res {
                    Ok(ref val) => (
                        val.get("index").and_then(|i| i.as_u64()).map(|i| i as usize),
                        val.get("uuid").and_then(|u| u.as_str()).map(|s| s.to_string()),
                    ),
                    Err(e) => {
                        let err_str = e.to_string();
                        let win_err = win_weak.clone();
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_err.upgrade() {
                                w.set_add_account_error(err_str.clone().into());
                                push_toast(&w, "account-error", "Account Error", &err_str, "warning");
                            }
                        });
                        return;
                    }
                };
                let _ = agent.select_account(ipc::SelectAccountRequest {
                    index: target_idx,
                    id: target_uuid,
                    username: Some(name_str.clone()),
                }).await;
                refresh_accounts_roster(agent, win_weak.clone()).await;

                if let Ok(skin_res) = agent.get_skin(ipc::GetSkinRequest::default()).await {
                    let new_model = skin_res.skin_model.clone().unwrap_or_else(|| "classic".to_string());
                    {
                        let mut s = state.lock().await;
                        s.skin_path = skin_res.skin_path;
                        s.model = new_model.clone();
                        s.cape_path = skin_res.cape_path;
                    }
                    let win_arm = win_weak.clone();
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_arm.upgrade() {
                            w.set_locker_model(new_model.into());
                        }
                    });
                    trigger_skin_render(agent.clone(), win_weak.clone(), state).await;
                }

                let name_done = name_str.clone();
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_weak.upgrade() {
                        w.set_add_account_modal_open(false);
                        w.set_offline_username("".into());
                        if w.get_onboarding_wizard_open() {
                            w.set_username(name_done.into());
                            w.set_account_type("Offline".into());
                        }
                    }
                });
            }
        });
    });

    let win_weak_add_modal = main_window.as_weak();
    main_window.on_add_account(move || {
        println!("[NLC-Rust] Add account dialog requested");
        if let Some(w) = win_weak_add_modal.upgrade() {
            w.set_add_account_modal_mode("select".into());
            w.set_add_account_error("".into());
            w.set_add_account_is_busy(false);
            w.set_ms_user_code("".into());
            w.set_ms_status("Contacting Microsoft...".into());
            w.set_elyby_username("".into());
            w.set_elyby_password("".into());
            w.set_offline_username("".into());
            w.set_add_account_modal_open(true);
        }
    });

    let win_weak_ms = main_window.as_weak();
    let agent_client_ms = agent_client.clone();
    let rt_ms = rt.clone();
    main_window.on_start_microsoft_auth(move || {
        println!("[NLC-Rust] Initiating Microsoft Device Code Flow");
        let win_weak = win_weak_ms.clone();
        let agent = agent_client_ms.clone();
        rt_ms.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = slint::invoke_from_event_loop({
                    let w_clone = win_weak.clone();
                    move || {
                        if let Some(w) = w_clone.upgrade() {
                            w.set_ms_status("Contacting Microsoft...".into());
                            w.set_ms_user_code("".into());
                        }
                    }
                });
                match agent.start_microsoft_auth().await {
                    Ok(resp) => {
                        let user_code = resp.user_code;
                        let verif_uri = resp.verification_uri;
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_weak.upgrade() {
                                w.set_ms_user_code(user_code.into());
                                w.set_ms_verification_uri(verif_uri.into());
                                w.set_ms_status("1. Open verification link\n2. Enter code shown\n3. Sign in with Microsoft".into());
                            }
                        });
                    }
                    Err(e) => {
                        let err_msg = format!("Failed to initiate login: {}", e);
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_weak.upgrade() {
                                w.set_ms_status(err_msg.into());
                            }
                        });
                    }
                }
            }
        });
    });

    let win_weak_ely = main_window.as_weak();
    let agent_client_ely = agent_client.clone();
    let rt_ely = rt.clone();
    main_window.on_login_elyby(move |username, password| {
        let u_str = username.to_string();
        let p_str = password.to_string();
        println!("[NLC-Rust] Authenticating with Ely.by as: {}", u_str);
        let win_weak = win_weak_ely.clone();
        let agent = agent_client_ely.clone();
        rt_ely.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = slint::invoke_from_event_loop({
                    let w_clone = win_weak.clone();
                    move || {
                        if let Some(w) = w_clone.upgrade() {
                            w.set_add_account_is_busy(true);
                            w.set_add_account_error("".into());
                        }
                    }
                });
                match agent.auth_elyby(&u_str, &p_str).await {
                    Ok(res) => {
                        if let Some(err) = res.get("message").or_else(|| res.get("error")).and_then(|v| v.as_str()) {
                            let err_str = err.to_string();
                            let _ = slint::invoke_from_event_loop(move || {
                                if let Some(w) = win_weak.upgrade() {
                                    w.set_add_account_is_busy(false);
                                    w.set_add_account_error(err_str.into());
                                }
                            });
                        } else {
                            let req = ipc::SelectAccountRequest {
                                username: Some(u_str.clone()),
                                ..Default::default()
                            };
                            let _ = agent.select_account(req).await;
                            refresh_accounts_roster(agent, win_weak.clone()).await;
                            let u_done = u_str.clone();
                            let _ = slint::invoke_from_event_loop(move || {
                                if let Some(w) = win_weak.upgrade() {
                                    w.set_add_account_is_busy(false);
                                    w.set_add_account_modal_open(false);
                                    w.set_elyby_username("".into());
                                    w.set_elyby_password("".into());
                                    if w.get_onboarding_wizard_open() && w.get_onboarding_wizard_step() == 1 {
                                        w.set_onboarding_wizard_step(2);
                                        w.set_username(u_done.into());
                                        w.set_account_type("ely.by".into());
                                    }
                                }
                            });
                        }
                    }
                    Err(e) => {
                        let err_msg = format!("Login request error: {}", e);
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_weak.upgrade() {
                                w.set_add_account_is_busy(false);
                                w.set_add_account_error(err_msg.into());
                            }
                        });
                    }
                }
            }
        });
    });

    let agent_client_copy = agent_client.clone();
    let rt_copy = rt.clone();
    main_window.on_copy_clipboard(move |text| {
        let text_str = text.to_string();
        let agent = agent_client_copy.clone();
        rt_copy.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.copy_clipboard(&text_str).await;
            }
        });
    });

    let agent_client_url = agent_client.clone();
    let rt_url = rt.clone();
    main_window.on_open_url(move |url| {
        let url_str = url.to_string();
        let agent = agent_client_url.clone();
        rt_url.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.open_url(&url_str).await;
            }
        });
    });

    // 8. Wire Bottom Dock Actions (GitHub, Screenshots, Notifications)
    let agent_client_dock = agent_client.clone();
    let rt_dock = rt.clone();
    let proj_root_dock = project_root.clone();
    let win_weak_dock = main_window.as_weak();
    main_window.on_open_dock(move |item| {
        println!("[NLC-Rust] Dock item clicked: {}", item);
        match item.as_str() {
            "github" => {
                #[cfg(windows)]
                let _ = std::process::Command::new("cmd")
                    .args(["/c", "start", "https://github.com/Amne-Dev/NLC"])
                    .spawn();
            }
            "screenshots" => {
                let agent = agent_client_dock.clone();
                let win_weak = win_weak_dock.clone();
                let root_dir = proj_root_dock.clone();
                rt_dock.spawn(async move {
                    refresh_screenshots_gallery(agent.as_deref(), &root_dir, win_weak).await;
                });
            }
            "notifications" => {
                println!("[NLC-Rust] Notification panel toggled");
            }
            _ => {}
        }
    });

    // 9. Wire Folder Navigation Actions
    let agent_client_folder = agent_client.clone();
    let rt_folder = rt.clone();
    main_window.on_open_folder(move |target| {
        let target_str = target.to_string();
        println!("[NLC-Rust] Opening directory for: {}", target_str);
        let agent = agent_client_folder.clone();
        rt_folder.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.open_folder(&target_str).await;
            } else {
                let folder_path = match target_str.as_str() {
                    "mods" => paths::get_modpacks_dir(),
                    "screenshots" => paths::get_minecraft_dir().join("screenshots"),
                    "latest-release" => paths::get_minecraft_dir(),
                    target_id => paths::get_modpacks_dir().join(target_id),
                };
                let _ = std::fs::create_dir_all(&folder_path);
                #[cfg(windows)]
                let _ = std::process::Command::new("explorer").arg(&folder_path).spawn();
                #[cfg(not(windows))]
                {
                    let mut cmd = std::process::Command::new("xdg-open");
                    cmd.arg(&folder_path);
                    cmd.env_remove("LD_LIBRARY_PATH");
                    cmd.env_remove("PYTHONPATH");
                    cmd.env_remove("PYTHONHOME");
                    cmd.env_remove("LD_PRELOAD");
                    if let Ok(orig_ld) = std::env::var("LD_LIBRARY_PATH_ORIG") {
                        cmd.env("LD_LIBRARY_PATH", orig_ld);
                    }
                    let _ = cmd.spawn();
                }
            }
        });
    });

    main_window.on_new_installation(move || {
        println!("[NLC-Rust] New installation requested");
    });

    let agent_client_save = agent_client.clone();
    let win_weak_save = main_window.as_weak();
    let proj_root_save = project_root.clone();
    let rt_save = rt.clone();
    main_window.on_save_installation(move |data| {
        let id_str = data.id.to_string();
        println!("[NLC-Rust] Saving installation: id={}, name={}", id_str, data.name);
        let agent = agent_client_save.clone();
        let win_weak_inner = win_weak_save.clone();
        let root_dir = proj_root_save.clone();
        let payload = serde_json::json!({
            "id": id_str,
            "name": data.name.to_string(),
            "version": data.version.to_string(),
            "loader": data.loader.to_string(),
            "icon": data.icon_name.to_string(),
            "is_snapshot": data.is_snapshot,
            "is_modded": data.is_modded,
            "java_path": data.java_path.to_string(),
            "java_executable": data.java_path.to_string(),
            "jvm_args": data.jvm_args.to_string(),
            "jvm_arguments": data.jvm_args.to_string(),
            "resolution_w": data.resolution_w,
            "resolution_width": data.resolution_w,
            "resolution_h": data.resolution_h,
            "resolution_height": data.resolution_h,
            "game_dir": data.game_dir.to_string(),
            "game_directory": data.game_dir.to_string(),
            "ram_mb": data.ram_mb,
            "max_ram_mb": if data.ram_mb > 0 { serde_json::Value::Number(serde_json::Number::from(data.ram_mb)) } else { serde_json::Value::Null },
        });
        rt_save.spawn(async move {
            if let Some(ref agent) = agent {
                let existing = agent.list_instances().await.unwrap_or_default();
                let exists = !id_str.is_empty() && existing.iter().any(|i| i.id == id_str);
                let save_res = if exists {
                    agent.update_instance(payload).await
                } else {
                    agent.create_instance(payload).await
                };
                if let Err(ref e) = save_res {
                    eprintln!("[NLC-Rust] Failed to save installation: {:?}", e);
                }
                if let Ok(items) = agent.list_instances().await {
                    let is_success = save_res.is_ok();
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak_inner.upgrade() {
                            let slint_items: Vec<InstallationData> = items.iter().map(|i| map_installation(i, &root_dir)).collect();
                            let choice_items: Vec<InstallationChoice> = items.iter().map(map_installation_choice).collect();
                            w.set_installations(std::rc::Rc::new(slint::VecModel::from(slint_items)).into());
                            w.set_compatible_installations(std::rc::Rc::new(slint::VecModel::from(choice_items)).into());
                            if is_success {
                                show_toast_notification(&w, &get_toast_tracker(), "inst-saved", "Installation Saved", "Your installation configuration has been saved.", "completed", 100.0, false, "");
                            }
                        }
                    });
                }
            }
        });
    });

    let agent_client_del_inst = agent_client.clone();
    let win_weak_del_inst = main_window.as_weak();
    let proj_root_del_inst = project_root.clone();
    let rt_del_inst = rt.clone();
    main_window.on_delete_installation(move |id| {
        let id_str = id.to_string();
        println!("[NLC-Rust] Deleting installation: {}", id_str);
        let agent = agent_client_del_inst.clone();
        let win_weak_inner = win_weak_del_inst.clone();
        let root_dir = proj_root_del_inst.clone();
        rt_del_inst.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.delete_instance(&id_str).await;
                if let Ok(items) = agent.list_instances().await {
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak_inner.upgrade() {
                            let slint_items: Vec<InstallationData> = items.iter().map(|i| map_installation(i, &root_dir)).collect();
                            let choice_items: Vec<InstallationChoice> = items.iter().map(map_installation_choice).collect();
                            w.set_installations(std::rc::Rc::new(slint::VecModel::from(slint_items)).into());
                            w.set_compatible_installations(std::rc::Rc::new(slint::VecModel::from(choice_items)).into());
                        }
                    });
                }
            }
        });
    });

    let agent_client_dup = agent_client.clone();
    let win_weak_dup = main_window.as_weak();
    let proj_root_dup = project_root.clone();
    let rt_dup = rt.clone();
    main_window.on_duplicate_installation(move |id| {
        let id_str = id.to_string();
        println!("[NLC-Rust] Duplicating installation: {}", id_str);
        let agent = agent_client_dup.clone();
        let win_weak_inner = win_weak_dup.clone();
        let root_dir = proj_root_dup.clone();
        rt_dup.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.duplicate_instance(&id_str).await;
                if let Ok(items) = agent.list_instances().await {
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak_inner.upgrade() {
                            let slint_items: Vec<InstallationData> = items.iter().map(|i| map_installation(i, &root_dir)).collect();
                            let choice_items: Vec<InstallationChoice> = items.iter().map(map_installation_choice).collect();
                            w.set_installations(std::rc::Rc::new(slint::VecModel::from(slint_items)).into());
                            w.set_compatible_installations(std::rc::Rc::new(slint::VecModel::from(choice_items)).into());
                        }
                    });
                }
            }
        });
    });

    let agent_client_sel_inst = agent_client.clone();
    let rt_sel_inst = rt.clone();
    main_window.on_installation_selected(move |name, id| {
        let n_str = name.to_string();
        let id_str = id.to_string();
        println!("[NLC-Rust] Installation selected on play screen: name='{}', id='{}'", n_str, id_str);
        let agent = agent_client_sel_inst.clone();
        rt_sel_inst.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.set_config(serde_json::json!({
                    "active_installation_id": id_str,
                    "active_instance": id_str
                })).await;
            }
        });
    });

    let agent_client_create_mp = agent_client.clone();
    let win_weak_create_mp = main_window.as_weak();
    let rt_create_mp = rt.clone();
    main_window.on_create_modpack(move |name, loader, ver| {
        let name_str = name.to_string();
        let loader_str = loader.to_string();
        let ver_str = ver.to_string();
        println!("[NLC-Rust] Creating modpack: name={}, loader={}, ver={}", name_str, loader_str, ver_str);
        let agent = agent_client_create_mp.clone();
        let win_weak_inner = win_weak_create_mp.clone();
        rt_create_mp.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.create_modpack(&name_str, &loader_str, &ver_str).await;
                if let Ok(packs) = agent.list_modpacks().await {
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak_inner.upgrade() {
                            let slint_packs: Vec<ModpackData> = packs.iter().map(map_modpack).collect();
                            sync_modrinth_destinations(&w, &slint_packs);
                            w.set_modpacks(std::rc::Rc::new(slint::VecModel::from(slint_packs)).into());
                        }
                    });
                }
            }
        });
    });

    let agent_client_link = agent_client.clone();
    let win_weak_link = main_window.as_weak();
    let rt_link = rt.clone();
    main_window.on_link_modpack(move |pack_id, inst_id| {
        let pack_str = pack_id.to_string();
        let inst_str = inst_id.to_string();
        println!("[NLC-Rust] Linking modpack {} to installation {}", pack_str, inst_str);
        let agent = agent_client_link.clone();
        let win_weak_inner = win_weak_link.clone();
        rt_link.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.link_modpack(&pack_str, &inst_str).await;
                if let Ok(packs) = agent.list_modpacks().await {
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak_inner.upgrade() {
                            let slint_packs: Vec<ModpackData> = packs.iter().map(map_modpack).collect();
                            sync_modrinth_destinations(&w, &slint_packs);
                            w.set_modpacks(std::rc::Rc::new(slint::VecModel::from(slint_packs)).into());
                        }
                    });
                }
            }
        });
    });

    let agent_client_del_mp = agent_client.clone();
    let win_weak_del_mp = main_window.as_weak();
    let rt_del_mp = rt.clone();
    main_window.on_delete_modpack(move |pack_id| {
        let pack_str = pack_id.to_string();
        println!("[NLC-Rust] Deleting modpack: {}", pack_str);
        let agent = agent_client_del_mp.clone();
        let win_weak_inner = win_weak_del_mp.clone();
        rt_del_mp.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.delete_modpack(&pack_str).await;
                if let Ok(packs) = agent.list_modpacks().await {
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak_inner.upgrade() {
                            let slint_packs: Vec<ModpackData> = packs.iter().map(map_modpack).collect();
                            sync_modrinth_destinations(&w, &slint_packs);
                            w.set_modpacks(std::rc::Rc::new(slint::VecModel::from(slint_packs)).into());
                        }
                    });
                }
            }
        });
    });

    let agent_client_export_fmt = agent_client.clone();
    let rt_export_fmt = rt.clone();
    main_window.on_export_modpack_format(move |pack_id, fmt| {
        let pack_str = pack_id.to_string();
        let fmt_str = fmt.to_string();
        println!("[NLC-Rust] Exporting modpack {} as {}", pack_str, fmt_str);
        let agent = agent_client_export_fmt.clone();
        rt_export_fmt.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.export_modpack(&pack_str, &fmt_str).await;
            }
        });
    });

    let win_weak_browse_zip = main_window.as_weak();
    let rt_browse_zip = rt.clone();
    main_window.on_browse_curseforge_zip(move || {
        println!("[NLC-Rust] Browse curseforge/modpack zip dialog requested");
        let win_weak = win_weak_browse_zip.clone();
        rt_browse_zip.spawn(async move {
            if let Some(path) = prompt_open_file("Modpacks (*.zip, *.mrpack)|*.zip;*.mrpack|All files (*.*)|*.*") {
                    if !path.is_empty() {
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_weak.upgrade() {
                                w.set_modpack_import_zip_path(path.into());
                            }
                        });
                    }
                }
        });
    });

    let agent_client_import_mp = agent_client.clone();
    let win_weak_import_mp = main_window.as_weak();
    let rt_import_mp = rt.clone();
    main_window.on_import_curseforge_modpack(move |zip_path, api_key| {
        let zip_str = zip_path.to_string();
        let key_str = api_key.to_string();
        println!("[NLC-Rust] Importing modpack archive: {}", zip_str);
        let agent = agent_client_import_mp.clone();
        let win_weak_inner = win_weak_import_mp.clone();
        rt_import_mp.spawn(async move {
            if let Some(ref agent) = agent {
                let payload = serde_json::json!({
                    "archive_path": zip_str,
                    "api_key": if key_str.is_empty() { None } else { Some(key_str.as_str()) },
                });
                let res = agent.call::<serde_json::Value>("modpack_import", payload).await;
                println!("[NLC-Rust] Modpack import result: {:?}", res);
                if let Ok(packs) = agent.list_modpacks().await {
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak_inner.upgrade() {
                            let slint_packs: Vec<ModpackData> = packs.iter().map(map_modpack).collect();
                            sync_modrinth_destinations(&w, &slint_packs);
                            w.set_modpacks(std::rc::Rc::new(slint::VecModel::from(slint_packs)).into());
                            w.set_modpack_import_zip_path("".into());
                        }
                    });
                }
            }
        });
    });

    let agent_client_match_inst = agent_client.clone();
    let win_weak_match_inst = main_window.as_weak();
    let proj_root_match_inst = project_root.clone();
    let rt_match_inst = rt.clone();
    main_window.on_create_matching_installation(move |pack_id| {
        let pack_str = pack_id.to_string();
        println!("[NLC-Rust] Creating matching installation for modpack: {}", pack_str);
        let agent = agent_client_match_inst.clone();
        let win_weak_inner = win_weak_match_inst.clone();
        let root_dir = proj_root_match_inst.clone();
        rt_match_inst.spawn(async move {
            if let Some(ref agent) = agent {
                let packs = agent.list_modpacks().await.unwrap_or_default();
                if let Some(pack) = packs.iter().find(|p| p.id == pack_str) {
                    let new_inst_id = format!("inst-{}", pack.id);
                    let new_inst_name = pack.name.clone();
                    let ver = pack.version.clone().or_else(|| pack.mc_version.clone()).unwrap_or_else(|| "1.21.1".to_string());
                    let ldr = pack.loader.clone().unwrap_or_else(|| "Fabric".to_string());

                    let pack_dir_path = paths::get_modpacks_dir().join(&pack.id);
                    let pack_dir = pack_dir_path.to_string_lossy().to_string();
                    let pack_icon = pack_dir_path.join("icon.png");

                    let mut payload = serde_json::json!({
                        "id": new_inst_id,
                        "name": new_inst_name,
                        "version": ver,
                        "loader": ldr,
                        "is_modded": true,
                    });
                    if !pack_dir.is_empty() {
                        payload["game_directory"] = serde_json::Value::String(pack_dir);
                    }
                    if pack_icon.exists() {
                        payload["icon"] = serde_json::Value::String(pack_icon.to_string_lossy().to_string());
                    }
                    let _ = agent.create_instance(payload).await;
                    let _ = agent.link_modpack(&pack.id, &new_inst_id).await;

                    let (inst_res, mp_res) = tokio::join!(agent.list_instances(), agent.list_modpacks());
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak_inner.upgrade() {
                            if let Ok(items) = inst_res {
                                let slint_items: Vec<InstallationData> = items.iter().map(|i| map_installation(i, &root_dir)).collect();
                                let choice_items: Vec<InstallationChoice> = items.iter().map(map_installation_choice).collect();
                                w.set_installations(std::rc::Rc::new(slint::VecModel::from(slint_items)).into());
                                w.set_compatible_installations(std::rc::Rc::new(slint::VecModel::from(choice_items)).into());
                            }
                            if let Ok(packs) = mp_res {
                                let slint_packs: Vec<ModpackData> = packs.iter().map(map_modpack).collect();
                                sync_modrinth_destinations(&w, &slint_packs);
                                w.set_modpacks(std::rc::Rc::new(slint::VecModel::from(slint_packs)).into());
                            }
                        }
                    });
                }
            }
        });
    });

fn apply_mod_filter(
    mods: &[ipc::ModItem],
    query: &str,
    status: &str,
) -> Vec<ModCardData> {
    let q = query.trim().to_lowercase();
    mods.iter()
        .filter(|m| {
            let is_act = m.enabled.or(m.is_active).or(m.active).unwrap_or(true);
            if status == "active" && !is_act {
                return false;
            }
            if status == "disabled" && is_act {
                return false;
            }
            if !q.is_empty() {
                let name_match = m.name.to_lowercase().contains(&q);
                let fn_match = m.filename.to_lowercase().contains(&q);
                if !name_match && !fn_match {
                    return false;
                }
            }
            true
        })
        .enumerate()
        .map(|(idx, m)| map_mod_card(m, idx))
        .collect()
}

    // 10. Wire Mod Management Actions
    let cached_mods_state: std::sync::Arc<std::sync::Mutex<Vec<ipc::ModItem>>> = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));

    let agent_client_show_mods = agent_client.clone();
    let win_weak_show_mods = main_window.as_weak();
    let rt_show_mods = rt.clone();
    let cached_mods_show = cached_mods_state.clone();
    main_window.on_show_mods(move |pack_id| {
        let pack_str = pack_id.to_string();
        println!("[NLC-Rust] Showing mods for modpack: {}", pack_str);
        let agent = agent_client_show_mods.clone();
        let win_weak_inner = win_weak_show_mods.clone();
        let cached_mods_inner = cached_mods_show.clone();
        rt_show_mods.spawn(async move {
            if let Some(ref agent) = agent {
                if let Ok(mods) = agent.list_pack_mods(&pack_str).await {
                    println!("[NLC-Rust] Loaded {} mods for {}", mods.len(), pack_str);
                    {
                        let mut lock = cached_mods_inner.lock().unwrap();
                        *lock = mods.clone();
                    }
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak_inner.upgrade() {
                            let q = w.get_mod_search_query().to_string();
                            let s = w.get_mod_filter_status().to_string();
                            let slint_mods = apply_mod_filter(&mods, &q, &s);
                            w.set_active_modpack_id(pack_str.into());
                            w.set_modpack_view_mode("mods".into());
                            w.set_modpack_mods(std::rc::Rc::new(slint::VecModel::from(slint_mods)).into());
                        }
                    });
                }
            }
        });
    });

    let agent_client_mods = agent_client.clone();
    let win_weak_mods_ref = main_window.as_weak();
    let rt_mods_ref = rt.clone();
    let cached_mods_ref = cached_mods_state.clone();
    main_window.on_refresh_mods(move || {
        println!("[NLC-Rust] Refreshing mods list from backend...");
        let agent = agent_client_mods.clone();
        let win_weak_inner = win_weak_mods_ref.clone();
        let cached_mods_inner = cached_mods_ref.clone();
        rt_mods_ref.spawn(async move {
            let active_pack = if let Some(w) = win_weak_inner.upgrade() {
                let p = w.get_active_modpack_id().to_string();
                if p.is_empty() { "fabulously-optimized".to_string() } else { p }
            } else {
                "fabulously-optimized".to_string()
            };
            if let Some(ref agent) = agent {
                if let Ok(mods) = agent.list_pack_mods(&active_pack).await {
                    println!("[NLC-Rust] Loaded {} mods from instance {}", mods.len(), active_pack);
                    {
                        let mut lock = cached_mods_inner.lock().unwrap();
                        *lock = mods.clone();
                    }
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak_inner.upgrade() {
                            let q = w.get_mod_search_query().to_string();
                            let s = w.get_mod_filter_status().to_string();
                            let slint_mods = apply_mod_filter(&mods, &q, &s);
                            w.set_modpack_mods(std::rc::Rc::new(slint::VecModel::from(slint_mods)).into());
                        }
                    });
                }
            }
        });
    });

    let win_weak_search_mods = main_window.as_weak();
    let cached_mods_search = cached_mods_state.clone();
    main_window.on_search_mods(move |query| {
        let q_str = query.to_string();
        if let Some(w) = win_weak_search_mods.upgrade() {
            let s = w.get_mod_filter_status().to_string();
            let mods = {
                let lock = cached_mods_search.lock().unwrap();
                lock.clone()
            };
            let slint_mods = apply_mod_filter(&mods, &q_str, &s);
            w.set_modpack_mods(std::rc::Rc::new(slint::VecModel::from(slint_mods)).into());
        }
    });

    let win_weak_filter_status = main_window.as_weak();
    let cached_mods_filter = cached_mods_state.clone();
    main_window.on_filter_status_changed(move |status| {
        let s_str = status.to_string();
        if let Some(w) = win_weak_filter_status.upgrade() {
            let q = w.get_mod_search_query().to_string();
            let mods = {
                let lock = cached_mods_filter.lock().unwrap();
                lock.clone()
            };
            let slint_mods = apply_mod_filter(&mods, &q, &s_str);
            w.set_modpack_mods(std::rc::Rc::new(slint::VecModel::from(slint_mods)).into());
        }
    });

    let agent_client_add_mod = agent_client.clone();
    let win_weak_add_mod = main_window.as_weak();
    let rt_add_mod = rt.clone();
    let cached_mods_add = cached_mods_state.clone();
    main_window.on_add_mod(move |pack_id| {
        let pack_str = pack_id.to_string();
        println!("[NLC-Rust] Add mod requested for pack: {}", pack_str);
        let agent = agent_client_add_mod.clone();
        let win_weak_inner = win_weak_add_mod.clone();
        let cached_mods_inner = cached_mods_add.clone();
        rt_add_mod.spawn(async move {
            if let Some(path) = prompt_open_file("Minecraft Mods (*.jar)|*.jar|All files (*.*)|*.*") {
                    if !path.is_empty() {
                        if let Some(ref agent) = agent {
                            let _ = agent.install_pack_mod(&pack_str, &path).await;
                            if let Ok(mods) = agent.list_pack_mods(&pack_str).await {
                                {
                                    let mut lock = cached_mods_inner.lock().unwrap();
                                    *lock = mods.clone();
                                }
                                let _ = slint::invoke_from_event_loop(move || {
                                    if let Some(w) = win_weak_inner.upgrade() {
                                        let q = w.get_mod_search_query().to_string();
                                        let s = w.get_mod_filter_status().to_string();
                                        let slint_mods = apply_mod_filter(&mods, &q, &s);
                                        w.set_modpack_mods(std::rc::Rc::new(slint::VecModel::from(slint_mods)).into());
                                    }
                                });
                            }
                        }
                    }
                }
        });
    });

    let agent_client_export = agent_client.clone();
    let win_weak_exp = main_window.as_weak();
    let rt_exp = rt.clone();
    main_window.on_export_modpack(move || {
        println!("[NLC-Rust] Modpack export requested");
        let agent = agent_client_export.clone();
        let win_weak_inner = win_weak_exp.clone();
        rt_exp.spawn(async move {
            let active_pack = if let Some(w) = win_weak_inner.upgrade() {
                let p = w.get_active_modpack_id().to_string();
                if p.is_empty() { "fabulously-optimized".to_string() } else { p }
            } else {
                "fabulously-optimized".to_string()
            };
            if let Some(ref agent) = agent {
                let _ = agent.export_modpack(&active_pack, "mrpack").await;
            }
        });
    });

    let agent_client_toggle = agent_client.clone();
    let win_weak_toggle = main_window.as_weak();
    let rt_toggle = rt.clone();
    let cached_mods_toggle = cached_mods_state.clone();
    main_window.on_toggle_mod(move |mod_id, enabled| {
        let mod_str = mod_id.to_string();
        println!("[NLC-Rust] Toggling mod {} -> {}", mod_str, enabled);
        let agent = agent_client_toggle.clone();
        let win_weak_inner = win_weak_toggle.clone();
        let cached_mods_inner = cached_mods_toggle.clone();
        rt_toggle.spawn(async move {
            let active_pack = if let Some(w) = win_weak_inner.upgrade() {
                let p = w.get_active_modpack_id().to_string();
                if p.is_empty() { "fabulously-optimized".to_string() } else { p }
            } else {
                "fabulously-optimized".to_string()
            };
            if let Some(ref agent) = agent {
                let _ = agent.toggle_pack_mod(&active_pack, &mod_str, enabled).await;
                if let Ok(mods) = agent.list_pack_mods(&active_pack).await {
                    {
                        let mut lock = cached_mods_inner.lock().unwrap();
                        *lock = mods.clone();
                    }
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak_inner.upgrade() {
                            let q = w.get_mod_search_query().to_string();
                            let s = w.get_mod_filter_status().to_string();
                            let slint_mods = apply_mod_filter(&mods, &q, &s);
                            w.set_modpack_mods(std::rc::Rc::new(slint::VecModel::from(slint_mods)).into());
                        }
                    });
                }
            }
        });
    });

    let agent_client_rm = agent_client.clone();
    let win_weak_rm = main_window.as_weak();
    let rt_rm = rt.clone();
    let cached_mods_rm = cached_mods_state.clone();
    main_window.on_remove_mod(move |mod_id| {
        let mod_str = mod_id.to_string();
        println!("[NLC-Rust] Mod removal requested: {}", mod_str);
        let agent = agent_client_rm.clone();
        let win_weak_inner = win_weak_rm.clone();
        let cached_mods_inner = cached_mods_rm.clone();
        rt_rm.spawn(async move {
            let active_pack = if let Some(w) = win_weak_inner.upgrade() {
                let p = w.get_active_modpack_id().to_string();
                if p.is_empty() { "fabulously-optimized".to_string() } else { p }
            } else {
                "fabulously-optimized".to_string()
            };
            if let Some(ref agent) = agent {
                let _ = agent.remove_pack_mod(&active_pack, &mod_str).await;
                if let Ok(mods) = agent.list_pack_mods(&active_pack).await {
                    {
                        let mut lock = cached_mods_inner.lock().unwrap();
                        *lock = mods.clone();
                    }
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak_inner.upgrade() {
                            let q = w.get_mod_search_query().to_string();
                            let s = w.get_mod_filter_status().to_string();
                            let slint_mods = apply_mod_filter(&mods, &q, &s);
                            w.set_modpack_mods(std::rc::Rc::new(slint::VecModel::from(slint_mods)).into());
                        }
                    });
                }
            }
        });
    });

    // 11. Wire Settings Toggles to Backend Configuration
    let agent_client_cfg = agent_client.clone();
    let win_weak_cfg = main_window.as_weak();
    let rt_cfg = rt.clone();
    main_window.on_setting_changed(move |key, val| {
        let k = key.to_string();
        println!("[NLC-Rust] Setting changed: {} = {}", k, val);
        let win = win_weak_cfg.clone();
        let _ = slint::invoke_from_event_loop({
            let k_ui = k.clone();
            move || {
                if let Some(w) = win.upgrade() {
                    match k_ui.as_str() {
                        "smooth_animations" | "animations_enabled" => {
                            w.set_smooth_animations(val);
                            w.global::<Theme>().set_smooth_animations(val);
                        }
                        "enable_walking_mobs" => {
                            w.set_enable_walking_mobs(val);
                            if !val {
                                w.set_walking_mob_visible(false);
                            }
                        }
                        "close_on_launch" => w.set_close_on_launch(val),
                        "minimize_to_tray" => w.set_minimize_to_tray(val),
                        "keep_console_open" => w.set_keep_console_open(val),
                        "show_launch_logs" => w.set_show_launch_logs(val),
                        "streamer_privacy" | "streamer_mode" => w.set_streamer_privacy(val),
                        "discord_rpc" | "rpc_enabled" => w.set_discord_rpc(val),
                        "discord_show_timer" | "rpc_show_timer" => w.set_discord_show_timer(val),
                        "discord_show_idle" | "rpc_show_idle" => w.set_discord_show_idle(val),
                        "discord_show_server" | "rpc_show_server" => w.set_discord_show_server(val),
                        "share_resource_packs" => w.set_share_resource_packs(val),
                        "share_shader_packs" => w.set_share_shader_packs(val),
                        "share_worlds" => w.set_share_worlds(val),
                        "share_mod_configs" => w.set_share_mod_configs(val),
                        "check_updates_startup" => w.set_check_updates_startup(val),
                        "throttle_downloads" => w.set_throttle_downloads(val),
                        _ => {}
                    }
                }
            }
        });
        let agent = agent_client_cfg.clone();
        rt_cfg.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.set_config(serde_json::json!({ k: val })).await;
            }
        });
    });

    let agent_client_cfg_int = agent_client.clone();
    let win_weak_cfg_int = main_window.as_weak();
    let rt_cfg_int = rt.clone();
    main_window.on_setting_int_changed(move |key, val| {
        let k = key.to_string();
        println!("[NLC-Rust] Int setting changed: {} = {}", k, val);
        let win = win_weak_cfg_int.clone();
        let _ = slint::invoke_from_event_loop({
            let k_ui = k.clone();
            move || {
                if let Some(w) = win.upgrade() {
                    match k_ui.as_str() {
                        "ram" | "ram_allocation_mb" | "ram_mb" => w.set_ram_allocation_mb(val),
                        "max_modpack_downloads" => w.set_max_modpack_downloads(val),
                        "max_mod_downloads" => w.set_max_mod_downloads(val),
                        "max_download_speed_kb" => w.set_max_download_speed_kb(val),
                        _ => {}
                    }
                }
            }
        });
        let agent = agent_client_cfg_int.clone();
        rt_cfg_int.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.set_config(serde_json::json!({ k: val })).await;
            }
        });
    });

    let agent_client_cfg_str = agent_client.clone();
    let win_weak_cfg_str = main_window.as_weak();
    let rt_cfg_str = rt.clone();
    main_window.on_setting_string_changed(move |key, val| {
        let k = key.to_string();
        let v = val.to_string();
        println!("[NLC-Rust] String setting changed: {} = {}", k, v);
        let agent = agent_client_cfg_str.clone();
        let win_weak = win_weak_cfg_str.clone();
        rt_cfg_str.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.set_config(serde_json::json!({ &k: &v })).await;
            }
            if k == "post_launch_action" {
                let v_ui = v.clone();
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_weak.upgrade() {
                        w.set_post_launch_action(v_ui.into());
                    }
                });
            } else if k == "discord_detail" || k == "rpc_detail_mode" {
                let v_ui = v.clone();
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_weak.upgrade() {
                        w.set_discord_detail(v_ui.into());
                    }
                });
            } else if k == "default_offline_name" {
                if let Err(err_msg) = validate_minecraft_username(&v) {
                    let win_val = win_weak.clone();
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_val.upgrade() {
                            push_toast(&w, "offline-name-invalid", "Invalid Username", err_msg, "warning");
                        }
                    });
                    return;
                }
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_weak.upgrade() {
                        w.set_toast_visible(true);
                        w.set_toast_title("Offline Name Saved".into());
                        w.set_toast_detail(format!("Fallback username set to {}", v).into());
                        w.set_toast_status("completed".into());
                        push_toast(&w, "offline-name", "Offline Name Saved", &format!("Fallback username set to {}", v), "completed");
                    }
                });
            }
        });
    });

    let win_weak_b_java = main_window.as_weak();
    let agent_client_b_java = agent_client.clone();
    let rt_b_java = rt.clone();
    main_window.on_browse_java_path(move || {
        println!("[NLC-Rust] Browse Java executable requested");
        let win_weak = win_weak_b_java.clone();
        let agent = agent_client_b_java.clone();
        rt_b_java.spawn(async move {
            let filter = if cfg!(windows) {
                "Java Executable (javaw.exe;java.exe)|javaw.exe;java.exe|All Executables (*.exe)|*.exe"
            } else {
                "Java Executable (java)|java|All files (*)|*"
            };
            if let Some(path) = prompt_open_file(filter) {
                if !path.is_empty() && std::path::Path::new(&path).exists() {
                    if let Some(ref ag) = agent {
                        let _ = ag.set_config(serde_json::json!({ "java_executable": &path, "java_path": &path })).await;
                    }
                    let p_clone = path.clone();
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak.upgrade() {
                            w.set_java_executable(p_clone.into());
                            w.set_toast_visible(true);
                            w.set_toast_title("Java Executable Updated".into());
                            w.set_toast_detail("New Java runtime configured ✓".into());
                            w.set_toast_status("completed".into());
                            push_toast(&w, "java-update", "Java Executable Updated", "New Java runtime configured ✓", "completed");
                        }
                    });
                }
            }
        });
    });

    let win_weak_dt_java = main_window.as_weak();
    let agent_client_dt_java = agent_client.clone();
    let rt_dt_java = rt.clone();
    main_window.on_auto_detect_java(move || {
        println!("[NLC-Rust] Auto-detect Java requested");
        let win_weak = win_weak_dt_java.clone();
        let agent = agent_client_dt_java.clone();
        rt_dt_java.spawn(async move {
            fn find_java_in_dir(dir: &std::path::Path, depth: u8) -> Option<String> {
                if depth > 4 { return None; }
                if let Ok(entries) = std::fs::read_dir(dir) {
                    for entry in entries.flatten() {
                        let path = entry.path();
                        if path.is_file() {
                            let name = path.file_name().unwrap_or_default().to_string_lossy().to_lowercase();
                            if name == "javaw.exe" || name == "java.exe" || name == "java" {
                                return Some(path.to_string_lossy().to_string());
                            }
                        } else if path.is_dir() {
                            if let Some(found) = find_java_in_dir(&path, depth + 1) {
                                return Some(found);
                            }
                        }
                    }
                }
                None
            }

            let mut candidates: Vec<std::path::PathBuf> = Vec::new();
            candidates.push(paths::get_minecraft_dir().join("runtime"));
            candidates.push(paths::get_launcher_data_dir().join("runtime"));
            #[cfg(windows)]
            {
                candidates.push(std::path::PathBuf::from("C:\\Program Files\\Eclipse Adoptium"));
                candidates.push(std::path::PathBuf::from("C:\\Program Files\\Java"));
                candidates.push(std::path::PathBuf::from("C:\\Program Files\\Microsoft"));
                candidates.push(std::path::PathBuf::from("C:\\Program Files\\BellSoft"));
                candidates.push(std::path::PathBuf::from("C:\\Program Files (x86)\\Java"));
            }
            #[cfg(not(windows))]
            {
                candidates.push(std::path::PathBuf::from("/usr/lib/jvm"));
                candidates.push(std::path::PathBuf::from("/usr/lib64/jvm"));
                candidates.push(std::path::PathBuf::from("/usr/local/jvm"));
                candidates.push(paths::get_user_home().join(".sdkman").join("candidates").join("java"));
                candidates.push(paths::get_user_home().join(".jdks"));
            }

            let mut detected: Option<String> = None;
            for base in &candidates {
                if base.exists() {
                    if let Some(found) = find_java_in_dir(base, 0) {
                        detected = Some(found);
                        break;
                    }
                }
            }
            if detected.is_none() {
                if let Ok(out) = std::process::Command::new("where").arg("javaw").output() {
                    let s = String::from_utf8_lossy(&out.stdout).lines().next().unwrap_or("").trim().to_string();
                    if !s.is_empty() && std::path::Path::new(&s).exists() {
                        detected = Some(s);
                    }
                }
            }
            if detected.is_none() {
                if let Ok(out) = std::process::Command::new("where").arg("java").output() {
                    let s = String::from_utf8_lossy(&out.stdout).lines().next().unwrap_or("").trim().to_string();
                    if !s.is_empty() && std::path::Path::new(&s).exists() {
                        detected = Some(s);
                    }
                }
            }
            if let Some(java_path) = detected {
                if let Some(ref ag) = agent {
                    let _ = ag.set_config(serde_json::json!({ "java_executable": &java_path, "java_path": &java_path })).await;
                }
                let jp_clone = java_path.clone();
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_weak.upgrade() {
                        w.set_java_executable(jp_clone.into());
                        w.set_toast_visible(true);
                        w.set_toast_title("Java Auto-Detected".into());
                        w.set_toast_detail(format!("Found Java runtime: {}", java_path).into());
                        w.set_toast_status("completed".into());
                        push_toast(&w, "java-detect", "Java Auto-Detected", &format!("Found Java runtime: {}", java_path), "completed");
                    }
                });
            } else {
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_weak.upgrade() {
                        w.set_toast_visible(true);
                        w.set_toast_title("Java Detection Failed".into());
                        w.set_toast_detail("No Java installations found. Please browse manually.".into());
                        w.set_toast_status("error".into());
                        show_toast_notification(&w, &get_toast_tracker(), "java-detect-fail", "Java Detection Failed", "No Java installations found. Please browse manually.", "error", 0.0, false, "No Java installations found. Please browse manually.");
                    }
                });
            }
        });
    });

    let win_weak_ch_mc = main_window.as_weak();
    let agent_client_ch_mc = agent_client.clone();
    let rt_ch_mc = rt.clone();
    main_window.on_change_minecraft_dir(move || {
        println!("[NLC-Rust] Change Minecraft directory requested");
        let win_weak = win_weak_ch_mc.clone();
        let agent = agent_client_ch_mc.clone();
        rt_ch_mc.spawn(async move {
            if let Some(path) = prompt_open_folder() {
                if !path.is_empty() && std::path::Path::new(&path).exists() {
                    if let Some(ref ag) = agent {
                        let _ = ag.set_config(serde_json::json!({ "minecraft_directory": &path, "game_dir": &path })).await;
                    }
                    let p_clone = path.clone();
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak.upgrade() {
                            w.set_minecraft_directory(p_clone.into());
                            w.set_toast_visible(true);
                            w.set_toast_title("Minecraft Directory Updated".into());
                            w.set_toast_detail("Game data directory saved ✓".into());
                            w.set_toast_status("completed".into());
                            push_toast(&w, "mc-dir", "Minecraft Directory Updated", "Game data directory saved ✓", "completed");
                        }
                    });
                }
            }
        });
    });

    // 12. Wire Addons & Diagnostics Actions
    let win_weak_addons = main_window.as_weak();
    let agent_client_addons = agent_client.clone();
    let rt_addons = rt.clone();
    let state_addons_callbacks = state_addons.clone();
    let root_dir_addons = project_root.clone();

    // Reset playtime stats
    main_window.on_reset_addons_stats({
        let win_weak = win_weak_addons.clone();
        let agent = agent_client_addons.clone();
        let rt = rt_addons.clone();
        let root_dir = project_root.clone();
        move || {
            println!("[NLC-Rust] Resetting playtime and launch stats");
            let win_weak = win_weak.clone();
            let agent = agent.clone();
            let root_dir = root_dir.clone();
            rt.spawn(async move {
                if let Some(ref agent) = agent {
                    let _ = agent.reset_playtime_stats().await;
                    update_playtime_stats_in_ui(agent, win_weak.clone(), &root_dir).await;
                } else {
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak.upgrade() {
                            w.set_addons_minutes(0);
                            w.set_addons_launches(0);
                            w.set_addons_total_playtime("0m".into());
                            w.set_has_top_inst_1(false);
                            w.set_has_top_inst_2(false);
                        }
                    });
                }
            });
        }
    });

    // Open Addons Directory in File Explorer
    main_window.on_open_addons_folder({
        let state = state_addons_callbacks.clone();
        let agent = agent_client_addons.clone();
        let rt = rt_addons.clone();
        move || {
            println!("[NLC-Rust] Opening addons directory in file explorer");
            let state = state.clone();
            let agent = agent.clone();
            rt.spawn(async move {
                let target = {
                    let st = state.lock().await;
                    if !st.addons_dir.is_empty() {
                        st.addons_dir.clone()
                    } else {
                        paths::get_addons_dir().to_string_lossy().to_string()
                    }
                };

                let target_path = std::path::PathBuf::from(&target);
                if !target_path.exists() {
                    let _ = std::fs::create_dir_all(&target_path);
                }

                #[cfg(windows)]
                {
                    let _ = std::process::Command::new("explorer").arg(&target).spawn();
                }
                #[cfg(not(windows))]
                {
                    let _ = std::process::Command::new("xdg-open").arg(&target).spawn();
                }
                if let Some(ref a) = agent {
                    let _ = a.open_folder(&target).await;
                }
            });
        }
    });

    // Refresh Addons
    main_window.on_refresh_addons({
        let state = state_addons_callbacks.clone();
        let agent = agent_client_addons.clone();
        let win = win_weak_addons.clone();
        let root = root_dir_addons.clone();
        let rt = rt_addons.clone();
        move || {
            println!("[NLC-Rust] Refreshing addons roster");
            let state = state.clone();
            let agent = agent.clone();
            let win = win.clone();
            let root = root.clone();
            rt.spawn(async move {
                refresh_addons_roster(agent.as_deref(), win, state, &root).await;
            });
        }
    });

    // Select Addons Source Category
    main_window.on_select_addons_source({
        let state = state_addons_callbacks.clone();
        let agent = agent_client_addons.clone();
        let win = win_weak_addons.clone();
        let root = root_dir_addons.clone();
        let rt = rt_addons.clone();
        move |src_val| {
            let src = src_val.to_string();
            let state = state.clone();
            let agent = agent.clone();
            let win = win.clone();
            let root = root.clone();

            rt.spawn(async move {
                {
                    let mut st = state.lock().await;
                    st.current_source = src.clone();
                    if (src == "community" || src == "discover" || src == "modrinth") && st.community_addons.is_empty() {
                        st.community_addons = fetch_community_addons_from_repo(agent.as_deref()).await;
                    }
                }

                sync_addons_model_to_ui(win, state, &root).await;
            });
        }
    });

    // Search Addons
    main_window.on_search_addons({
        let state = state_addons_callbacks.clone();
        let win = win_weak_addons.clone();
        let root = root_dir_addons.clone();
        let rt = rt_addons.clone();
        move |query_val| {
            let q = query_val.to_string();
            let state = state.clone();
            let win = win.clone();
            let root = root.clone();

            rt.spawn(async move {
                {
                    let mut st = state.lock().await;
                    st.search_filter = q;
                }

                sync_addons_model_to_ui(win, state, &root).await;
            });
        }
    });

    // Submit Addon via GitHub PR
    main_window.on_submit_addon_pr({
        move || {
            println!("[NLC-Rust] Submit Addon PR requested - opening browser");
            let pr_url = "https://github.com/Amne-Dev/Community-addons-nlc/pulls";
            #[cfg(windows)]
            {
                let _ = std::process::Command::new("cmd")
                    .args(["/c", "start", "", pr_url])
                    .spawn();
            }
            #[cfg(not(windows))]
            {
                let _ = std::process::Command::new("xdg-open")
                    .arg(pr_url)
                    .spawn();
            }
        }
    });

    // Open Installation Playtime Details Modal
    main_window.on_open_playtime_details({
        let win_weak = main_window.as_weak();
        let agent = agent_client_addons.clone();
        let rt = rt_addons.clone();
        move || {
            let win_weak = win_weak.clone();
            let agent = agent.clone();
            rt.spawn(async move {
                let stats = if let Some(ref a) = agent {
                    a.get_playtime_stats().await.ok()
                } else {
                    None
                };

                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_weak.upgrade() {
                        let mut items: Vec<InstallationPlaytimeData> = Vec::new();
                        let tracker = stats.as_ref().map(|s| &s.tracker);

                        let installations = w.get_installations();
                        for idx in 0..installations.row_count() {
                            if let Some(inst) = installations.row_data(idx) {
                                let inst_id = inst.id.to_string();
                                let mut seconds = 0u64;
                                let mut launches = 0u64;
                                let mut last_played = String::new();

                                if let Some(tracker) = tracker {
                                    if let Some(val) = tracker.get(&inst_id) {
                                        if let Some(obj) = val.as_object() {
                                            seconds = obj.get("seconds").and_then(|v| v.as_u64()).unwrap_or(0);
                                            launches = obj.get("launches").and_then(|v| v.as_u64()).unwrap_or(0);
                                            if let Some(lp) = obj.get("last_played_at").and_then(|v| v.as_str()) {
                                                last_played = lp.chars().take(16).collect::<String>().replace('T', " ");
                                            }
                                        }
                                    }
                                }

                                items.push(InstallationPlaytimeData {
                                    id: inst.id.clone(),
                                    name: inst.name.clone(),
                                    version: inst.version.clone(),
                                    loader: inst.loader.clone(),
                                    icon: inst.icon.clone(),
                                    playtime_formatted: format_playtime_duration(seconds).into(),
                                    playtime_minutes: (seconds / 60) as i32,
                                    launches: launches as i32,
                                    last_played: if last_played.is_empty() { "Never".into() } else { last_played.into() },
                                });
                            }
                        }

                        items.sort_by(|a, b| b.playtime_minutes.cmp(&a.playtime_minutes));

                        let total_sec = stats.as_ref().map(|s| s.total_seconds).unwrap_or(0);
                        let total_fmt = format_playtime_duration(total_sec);

                        w.set_addons_total_playtime(total_fmt.into());
                        w.set_installation_playtimes(std::rc::Rc::new(slint::VecModel::from(items)).into());
                        w.set_playtime_details_open(true);
                    }
                });
            });
        }
    });

    // Run Addon Action
    main_window.on_run_addon_action({
        let state = state_addons_callbacks.clone();
        let agent = agent_client_addons.clone();
        let win = win_weak_addons.clone();
        let root = root_dir_addons.clone();
        let rt = rt_addons.clone();
        move |addon_id_val, action_id_val| {
            let addon_id = addon_id_val.to_string();
            let action_id = action_id_val.to_string();
            let agent = agent.clone();
            let win = win.clone();
            let state = state.clone();
            let root = root.clone();

            rt.spawn(async move {
                if addon_id == "playtime_tracker" {
                    if let Some(ref a) = agent {
                        let _ = a.reset_playtime_stats().await;
                        update_playtime_stats_in_ui(a, win.clone(), &root).await;
                    }
                    let _ = slint::invoke_from_event_loop({
                        let win = win.clone();
                        move || {
                            if let Some(w) = win.upgrade() {
                                w.set_addons_minutes(0);
                                w.set_addons_launches(0);
                                w.set_addons_total_playtime("0m".into());
                                w.set_has_top_inst_1(false);
                                w.set_has_top_inst_2(false);
                                push_toast(&w, "addon-playtime", "Playtime Tracker", "Playtime statistics reset ✓", "completed");
                            }
                        }
                    });
                    return;
                } else if addon_id == "streamer_mode" {
                    let mut new_state = true;
                    if let Some(ref a) = agent {
                        if let Ok(cfg) = a.get_config().await {
                            let curr = cfg.streamer_mode.unwrap_or(false);
                            new_state = !curr;
                            let _ = a.set_streamer_mode(new_state).await;
                        } else {
                            let _ = a.set_streamer_mode(true).await;
                        }
                    }
                    let _ = slint::invoke_from_event_loop({
                        let win = win.clone();
                        move || {
                            if let Some(w) = win.upgrade() {
                                let msg = if new_state {
                                    "Streamer mode enabled: credentials and addresses hidden ✓"
                                } else {
                                    "Streamer mode disabled ✓"
                                };
                                push_toast(&w, "addon-streamer", "Streamer Mode", msg, "completed");
                            }
                        }
                    });
                    refresh_addons_roster(agent.as_deref(), win.clone(), state.clone(), &root).await;
                    return;
                } else if addon_id == "gh_skin_sync" {
                    let win_c = win.clone();
                    let mut sync_success = false;
                    let mut sync_msg = String::new();
                    if let Some(ref a) = agent {
                        match a.call::<serde_json::Value>("skin_sync", serde_json::json!({})).await {
                            Ok(res) => {
                                if res.get("status").and_then(|v| v.as_str()) == Some("error") {
                                    sync_msg = res.get("msg").and_then(|v| v.as_str()).unwrap_or("Sync failed").to_string();
                                } else {
                                    sync_success = true;
                                    sync_msg = "Skins synchronized with GitHub repository ✓".to_string();
                                    refresh_accounts_roster(a, win_c.clone()).await;
                                }
                            }
                            Err(e) => {
                                sync_msg = format!("GitHub sync: {}", e);
                            }
                        }
                    }
                    let _ = slint::invoke_from_event_loop({
                        let win = win.clone();
                        move || {
                            if let Some(w) = win.upgrade() {
                                if sync_success {
                                    push_toast(&w, "addon-skin-sync", "GitHub Skin Sync", &sync_msg, "completed");
                                } else {
                                    push_toast(&w, "addon-skin-sync", "GitHub Skin Sync", "Configure GitHub repository and token in Settings to sync.", "warning");
                                }
                            }
                        }
                    });
                    return;
                } else if addon_id == "server_quick_join" {
                    let _ = slint::invoke_from_event_loop({
                        let win = win.clone();
                        move || {
                            if let Some(w) = win.upgrade() {
                                w.set_server_manager_open(true);
                            }
                        }
                    });
                    refresh_and_ping_saved_servers(agent.as_deref(), win.clone()).await;
                    return;
                }

                // 3rd-party addon action
                if let Some(ref a) = agent {
                    match a.run_third_party_addon_action(addon_id.clone(), action_id.clone(), serde_json::json!({})).await {
                        Ok(res) => {
                            let msg = res.msg.unwrap_or_else(|| format!("Action '{}' finished successfully.", action_id));
                            let _ = slint::invoke_from_event_loop({
                                let win = win.clone();
                                let a_id = addon_id.clone();
                                move || {
                                    if let Some(w) = win.upgrade() {
                                        push_toast(&w, &format!("addon-act-{}", a_id), "Addon Action Completed", &msg, "completed");
                                    }
                                }
                            });
                            refresh_addons_roster(Some(a), win, state, &root).await;
                        }
                        Err(e) => {
                            let err_msg = e.to_string();
                            let _ = slint::invoke_from_event_loop({
                                let win = win.clone();
                                let a_id = addon_id.clone();
                                move || {
                                    if let Some(w) = win.upgrade() {
                                        push_toast(&w, &format!("addon-err-{}", a_id), "Addon Action Failed", &err_msg, "error");
                                    }
                                }
                            });
                        }
                    }
                }
            });
        }
    });

    // Install Addon (from Modrinth)
    main_window.on_install_addon({
        let win = win_weak_addons.clone();
        move |addon_id_val| {
            let id = addon_id_val.to_string();
            let _ = slint::invoke_from_event_loop({
                let win = win.clone();
                move || {
                    if let Some(w) = win.upgrade() {
                        push_toast(&w, &format!("install-addon-{}", id), "Addon Install", "Installation queued", "info");
                    }
                }
            });
        }
    });

    // Add Saved Server
    main_window.on_add_saved_server({
        let win_weak = win_weak_addons.clone();
        let agent = agent_client_addons.clone();
        let state = state_addons_callbacks.clone();
        let root_dir = root_dir_addons.clone();
        let rt = rt_addons.clone();
        move |name_val, addr_val, port_val| {
            let name = name_val.to_string();
            let mut addr = addr_val.to_string();
            let port_str = port_val.to_string();
            let win = win_weak.clone();
            let agent = agent.clone();
            let state = state.clone();
            let root = root_dir.clone();
            rt.spawn(async move {
                let mut port = 25565u16;
                if let Ok(p) = port_str.trim().parse::<u16>() {
                    port = p;
                }
                if addr.contains(':') && addr.matches(':').count() == 1 {
                    let parts: Vec<&str> = addr.split(':').collect();
                    if let Ok(p) = parts[1].parse::<u16>() {
                        addr = parts[0].to_string();
                        port = p;
                    }
                }
                if let Some(ref a) = agent {
                    match a.add_saved_server(&name, &addr, port).await {
                        Ok(_) => {
                            let _ = slint::invoke_from_event_loop({
                                let win = win.clone();
                                let s_name = if name.is_empty() { addr.clone() } else { name.clone() };
                                move || {
                                    if let Some(w) = win.upgrade() {
                                        push_toast(&w, "server-added", "Server Saved", &format!("Added {} to quick join ✓", s_name), "completed");
                                    }
                                }
                            });
                            refresh_and_ping_saved_servers(Some(a), win.clone()).await;
                            refresh_addons_roster(Some(a), win.clone(), state.clone(), &root).await;
                        }
                        Err(e) => {
                            let _ = slint::invoke_from_event_loop({
                                let win = win.clone();
                                let err_str = e.to_string();
                                move || {
                                    if let Some(w) = win.upgrade() {
                                        push_toast(&w, "server-err", "Server Save Failed", &err_str, "error");
                                    }
                                }
                            });
                        }
                    }
                }
            });
        }
    });

    // Delete Saved Server
    main_window.on_delete_saved_server({
        let win_weak = win_weak_addons.clone();
        let agent = agent_client_addons.clone();
        let state = state_addons_callbacks.clone();
        let root_dir = root_dir_addons.clone();
        let rt = rt_addons.clone();
        move |server_id_val| {
            let server_id = server_id_val.to_string();
            let win = win_weak.clone();
            let agent = agent.clone();
            let state = state.clone();
            let root = root_dir.clone();
            rt.spawn(async move {
                if let Some(ref a) = agent {
                    if a.remove_saved_server(&server_id).await.is_ok() {
                        let _ = slint::invoke_from_event_loop({
                            let win = win.clone();
                            move || {
                                if let Some(w) = win.upgrade() {
                                    push_toast(&w, "server-deleted", "Server Removed", "Server removed from quick join list ✓", "completed");
                                }
                            }
                        });
                        refresh_and_ping_saved_servers(Some(a), win.clone()).await;
                        refresh_addons_roster(Some(a), win.clone(), state.clone(), &root).await;
                    }
                }
            });
        }
    });

    // Ping All Saved Servers
    main_window.on_ping_all_servers({
        let win_weak = win_weak_addons.clone();
        let agent = agent_client_addons.clone();
        let rt = rt_addons.clone();
        move || {
            let win = win_weak.clone();
            let agent = agent.clone();
            rt.spawn(async move {
                refresh_and_ping_saved_servers(agent.as_deref(), win.clone()).await;
            });
        }
    });

    // Quick Join Server (Launch Game directly into server)
    main_window.on_quick_join_server({
        let win_weak = win_weak_addons.clone();
        let agent = agent_client_addons.clone();
        let rt = rt_addons.clone();
        move |address_val, port_val| {
            let address = address_val.to_string();
            let port = port_val as u16;
            let win = win_weak.clone();
            let agent = agent.clone();
            rt.spawn(async move {
                let mut active_inst_id = String::new();
                let mut active_ver = "latest-release".to_string();
                let mut active_loader = "Vanilla".to_string();
                let cfg_path = paths::get_config_path();
                if let Ok(content) = std::fs::read_to_string(&cfg_path) {
                    if let Ok(val) = serde_json::from_str::<serde_json::Value>(&content) {
                        if let Some(id) = val.get("active_installation_id").and_then(|i| i.as_str()) {
                            active_inst_id = id.to_string();
                        }
                        if let Some(insts) = val.get("installations").and_then(|i| i.as_array()) {
                            for inst in insts {
                                if inst.get("id").and_then(|i| i.as_str()) == Some(&active_inst_id) {
                                    if let Some(v) = inst.get("version").and_then(|v| v.as_str()) {
                                        active_ver = v.to_string();
                                    }
                                    if let Some(l) = inst.get("loader").and_then(|l| l.as_str()) {
                                        active_loader = l.to_string();
                                    }
                                    break;
                                }
                            }
                        }
                    }
                }

                let _ = slint::invoke_from_event_loop({
                    let win = win.clone();
                    let addr = address.clone();
                    move || {
                        if let Some(w) = win.upgrade() {
                            w.set_server_manager_open(false);
                            w.set_is_launching(true);
                            w.set_launch_progress(0.0);
                            w.set_launch_log_text(format!("Connecting to {}:{}...", addr, port).into());
                            push_toast(&w, "launch-progress", "Connecting to Server", &format!("Launching Minecraft to join {}:{}", addr, port), "normal");
                        }
                    }
                });

                if let Some(ref a) = agent {
                    let req = ipc::LaunchGameRequest {
                        version: active_ver,
                        installation_id: if !active_inst_id.is_empty() { Some(active_inst_id.clone()) } else { None },
                        instance_id: if !active_inst_id.is_empty() { Some(active_inst_id) } else { None },
                        loader: if !active_loader.is_empty() { Some(active_loader) } else { None },
                        server: Some(address.clone()),
                        port: Some(port),
                        ..Default::default()
                    };
                    if let Err(err) = a.launch_game(req).await {
                        eprintln!("[NLC-Rust] Quick join launch failed: {}", err);
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win.upgrade() {
                                w.set_is_launching(false);
                                push_toast(&w, "launch-err", "Launch Failed", &err.to_string(), "error");
                            }
                        });
                    }
                }
            });
        }
    });

    let win_weak_wizard = main_window.as_weak();
    main_window.on_replay_wizard(move || {
        println!("[NLC-Rust] Replaying onboarding setup wizard");
        if let Some(w) = win_weak_wizard.upgrade() {
            w.set_onboarding_wizard_step(1);
            w.set_onboarding_wizard_open(true);
        }
    });

    let agent_client_ob = agent_client.clone();
    let win_weak_ob = main_window.as_weak();
    let rt_ob = rt.clone();
    main_window.on_complete_onboarding(move |username, ram_mb, theme_id| {
        let u_str = username.to_string();
        let t_str = theme_id.to_string();
        let ram = ram_mb as u32;
        println!("[NLC-Rust] Onboarding completed: user={}, ram={}MB, theme={}", u_str, ram, t_str);
        let agent = agent_client_ob.clone();
        let win_weak = win_weak_ob.clone();
        rt_ob.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.set_config(serde_json::json!({
                    "first_run_completed": true,
                    "ram": ram,
                    "theme_id": t_str,
                    "theme": t_str,
                })).await;
                if !u_str.is_empty() && u_str != "Player" {
                    let existing_accounts = agent.list_accounts().await.map(|a| a.accounts().to_vec()).unwrap_or_default();
                    let already_has_user = existing_accounts.iter().any(|a| a.name().eq_ignore_ascii_case(&u_str));
                    if !already_has_user {
                        let _ = agent.add_offline_account(&u_str).await;
                    }
                    let _ = refresh_accounts_roster(agent, win_weak.clone()).await;
                }
            }
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(w) = win_weak.upgrade() {
                    show_toast_notification(&w, &get_toast_tracker(), "onboarding-done", "Setup Completed", "Your preferences have been saved. Welcome to Ny-Luna Core!", "completed", 100.0, false, "");
                }
            });
        });
    });

    let agent_client_ob_full = agent_client.clone();
    let win_weak_ob_full = main_window.as_weak();
    let rt_ob_full = rt.clone();
    let proj_root_ob_full = project_root.clone();
    main_window.on_complete_onboarding_full(move |username, s_ldr, s_ver, ram_mb, post_launch, tray_on_close, theme_name, accent_hex, rpc_on, streamer_on| {
        let u_str = username.to_string();
        let ldr_str = s_ldr.to_string();
        let ver_str = s_ver.to_string();
        let ram = ram_mb as u32;
        let post_str = post_launch.to_string();
        let theme_str = theme_name.to_string();
        let hex_str = accent_hex.to_string();
        println!("[NLC-Rust] Full Onboarding completed: user={}, loader={}, ver={}, ram={}MB, post={}, tray_close={}, theme={}, hex={}, rpc={}, streamer={}",
            u_str, ldr_str, ver_str, ram, post_str, tray_on_close, theme_str, hex_str, rpc_on, streamer_on);

        let agent = agent_client_ob_full.clone();
        let win_weak = win_weak_ob_full.clone();
        let root_dir = proj_root_ob_full.clone();

        // 1. Immediately apply theme & settings to UI
        let win_weak_ui = win_weak.clone();
        let theme_copy = theme_str.clone();
        let hex_copy = hex_str.clone();
        let post_copy = post_str.clone();
        let _ = slint::invoke_from_event_loop(move || {
            if let Some(w) = win_weak_ui.upgrade() {
                w.set_selected_theme(theme_copy.clone().into());
                w.set_custom_hex(hex_copy.clone().into());
                w.set_post_launch_action(post_copy.into());
                w.set_minimize_to_tray(tray_on_close);
                w.set_discord_rpc(rpc_on);
                w.set_streamer_privacy(streamer_on);
                apply_theme_palette(&w, &theme_copy, Some(&hex_copy));
            }
        });

        // 2. Persist configuration & create offline account / instance if needed
        rt_ob_full.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.set_config(serde_json::json!({
                    "first_run_completed": true,
                    "ram": ram,
                    "post_launch_action": post_str,
                    "minimize_to_tray": tray_on_close,
                    "theme_id": theme_str,
                    "theme": theme_str,
                    "custom_accent": hex_str,
                    "rpc_enabled": rpc_on,
                    "streamer_mode": streamer_on,
                    "username": u_str,
                    "default_offline_name": u_str,
                })).await;

                if !u_str.is_empty() && u_str != "Player" {
                    let existing_accounts = agent.list_accounts().await.map(|a| a.accounts().to_vec()).unwrap_or_default();
                    let already_has_user = existing_accounts.iter().any(|a| a.name().eq_ignore_ascii_case(&u_str));
                    if !already_has_user {
                        let _ = agent.add_offline_account(&u_str).await;
                    }
                    let _ = refresh_accounts_roster(agent, win_weak.clone()).await;
                }

                // Check or create starter instance
                let inst_list = agent.list_instances().await.unwrap_or_default();
                let target_name = format!("{} {}", ldr_str, ver_str);
                let already_exists = inst_list.iter().any(|i| i.name.eq_ignore_ascii_case(&target_name) || (i.version == ver_str && i.loader.as_deref().unwrap_or("").eq_ignore_ascii_case(&ldr_str)));
                if !already_exists && !ver_str.is_empty() {
                    let new_id = format!("{}-{}", ldr_str.to_lowercase(), ver_str.replace('.', "-"));
                    let payload = serde_json::json!({
                        "id": new_id,
                        "name": target_name,
                        "version": ver_str,
                        "loader": ldr_str.to_lowercase(),
                    });
                    let _ = agent.create_instance(payload).await;
                }

                if let Ok(items) = agent.list_instances().await {
                    let win_weak_inner = win_weak.clone();
                    let root_dir_clone = root_dir.clone();
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak_inner.upgrade() {
                            let slint_items: Vec<InstallationData> = items.iter().map(|i| map_installation(i, &root_dir_clone)).collect();
                            let choice_items: Vec<InstallationChoice> = items.iter().map(map_installation_choice).collect();
                            w.set_installations(std::rc::Rc::new(slint::VecModel::from(slint_items)).into());
                            w.set_compatible_installations(std::rc::Rc::new(slint::VecModel::from(choice_items)).into());
                        }
                    });
                }
            }

            let _ = slint::invoke_from_event_loop(move || {
                if let Some(w) = win_weak.upgrade() {
                    show_toast_notification(&w, &get_toast_tracker(), "onboarding-done", "Setup Completed", "Your preferences have been saved. Welcome to Ny-Luna Core!", "completed", 100.0, false, "");
                }
            });
        });
    });

    let agent_client_ref_sc = agent_client.clone();
    let win_weak_ref_sc = main_window.as_weak();
    let proj_root_ref_sc = project_root.clone();
    let rt_ref_sc = rt.clone();
    main_window.on_refresh_screenshots(move || {
        println!("[NLC-Rust] Screenshots gallery refresh requested");
        let agent = agent_client_ref_sc.clone();
        let win_weak = win_weak_ref_sc.clone();
        let root_dir = proj_root_ref_sc.clone();
        rt_ref_sc.spawn(async move {
            refresh_screenshots_gallery(agent.as_deref(), &root_dir, win_weak).await;
        });
    });

    let agent_client_del_sc = agent_client.clone();
    let win_weak_del_sc = main_window.as_weak();
    let proj_root_del_sc = project_root.clone();
    let rt_del_sc = rt.clone();
    main_window.on_delete_screenshot(move |sc_id| {
        let id_str = sc_id.to_string();
        println!("[NLC-Rust] Deleting screenshot: {}", id_str);
        let agent = agent_client_del_sc.clone();
        let win_weak = win_weak_del_sc.clone();
        let root_dir = proj_root_del_sc.clone();
        rt_del_sc.spawn(async move {
            let p = std::path::Path::new(&id_str);
            if p.exists() {
                let _ = std::fs::remove_file(p);
            }
            if let Some(ref agent) = agent {
                let _ = agent.delete_screenshot(&id_str, None).await;
            }
            refresh_screenshots_gallery(agent.as_deref(), &root_dir, win_weak).await;
        });
    });

    // 12b. Wire Settings Themes, Custom Hex, Memory & Diagnostics Actions
    let agent_client_theme = agent_client.clone();
    let rt_theme = rt.clone();
    let win_weak_theme = main_window.as_weak();
    main_window.on_select_theme(move |theme| {
        let t_str = theme.to_string();
        let def_accent = get_theme_palette(&t_str).default_accent;
        println!("[NLC-Rust] Selected theme: {}, syncing signature accent: {}", t_str, def_accent);
        if let Some(win) = win_weak_theme.upgrade() {
            win.set_selected_theme(t_str.clone().into());
            win.set_custom_hex(def_accent.into());
            apply_theme_palette(&win, &t_str, Some(def_accent));
        }
        let agent = agent_client_theme.clone();
        rt_theme.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.set_config(serde_json::json!({
                    "theme_id": t_str,
                    "theme": t_str,
                    "custom_accent": def_accent,
                    "custom_hex": def_accent
                })).await;
            }
        });
    });

    let agent_client_hex = agent_client.clone();
    let rt_hex = rt.clone();
    let win_weak_hex = main_window.as_weak();
    main_window.on_apply_custom_hex(move |hex| {
        let h_str = hex.to_string();
        println!("[NLC-Rust] Custom hex: {}", h_str);
        if let Some(win) = win_weak_hex.upgrade() {
            let cur_theme = win.get_selected_theme();
            apply_theme_palette(&win, cur_theme.as_str(), Some(&h_str));
            win.set_custom_hex(h_str.clone().into());
        }
        let agent = agent_client_hex.clone();
        rt_hex.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.set_config(serde_json::json!({ "custom_accent": h_str, "custom_hex": h_str })).await;
            }
        });
    });

    let agent_client_ram = agent_client.clone();
    let rt_ram = rt.clone();
    main_window.on_ram_preset_clicked(move |ram_mb| {
        println!("[NLC-Rust] RAM preset clicked: {} MB", ram_mb);
        let agent = agent_client_ram.clone();
        rt_ram.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.set_config(serde_json::json!({ "ram": ram_mb, "ram_allocation_mb": ram_mb })).await;
            }
        });
    });

    let agent_client_reset_cfg = agent_client.clone();
    let win_weak_reset_cfg = main_window.as_weak();
    let rt_reset_cfg = rt.clone();
    main_window.on_reset_defaults(move || {
        println!("[NLC-Rust] Resetting configuration to defaults");
        let agent = agent_client_reset_cfg.clone();
        let win_weak = win_weak_reset_cfg.clone();
        rt_reset_cfg.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.reset_config_defaults().await;
                if let Ok(cfg) = agent.get_config().await {
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak.upgrade() {
                            sync_settings_to_ui(&cfg, &w);
                        }
                    });
                }
            }
        });
    });

    let agent_client_refresh_logs = agent_client.clone();
    let win_weak_refresh_logs = main_window.as_weak();
    let rt_refresh_logs = rt.clone();
    main_window.on_refresh_logs(move || {
        println!("[NLC-Rust] Refreshing launcher diagnostics logs");
        let win_weak = win_weak_refresh_logs.clone();
        let agent = agent_client_refresh_logs.clone();
        rt_refresh_logs.spawn(async move {
            if let Some(ref agent) = agent {
                if let Ok(logs_res) = agent.get_diagnostics_logs().await {
                    let text = if !logs_res.text.is_empty() {
                        logs_res.text
                    } else {
                        logs_res.lines.join("\n")
                    };
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak.upgrade() {
                            w.set_logs_text(text.into());
                        }
                    });
                }
            }
        });
    });

    let agent_client_copy_logs = agent_client.clone();
    let win_weak_copy_logs = main_window.as_weak();
    let rt_copy_logs = rt.clone();
    main_window.on_copy_logs(move || {
        println!("[NLC-Rust] Copying diagnostics logs to clipboard");
        let win_weak = win_weak_copy_logs.clone();
        let agent = agent_client_copy_logs.clone();
        rt_copy_logs.spawn(async move {
            let logs = if let Some(w) = win_weak.upgrade() {
                w.get_logs_text().to_string()
            } else {
                "".to_string()
            };
            if let Some(ref agent) = agent {
                let _ = agent.copy_clipboard(&logs).await;
            }
        });
    });

    let agent_client_clear_cache = agent_client.clone();
    let rt_clear_cache = rt.clone();
    main_window.on_clear_cache(move || {
        println!("[NLC-Rust] Clearing launcher cache");
        let agent = agent_client_clear_cache.clone();
        rt_clear_cache.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = agent.call::<serde_json::Value>("system_clear_cache", serde_json::json!({})).await;
            }
        });
    });

    let agent_client_diag = agent_client.clone();
    let win_weak_diag = main_window.as_weak();
    let rt_diag = rt.clone();
    main_window.on_export_diagnostics(move || {
        println!("[NLC-Rust] Exporting system diagnostics");
        let agent = agent_client_diag.clone();
        let win_weak = win_weak_diag.clone();
        rt_diag.spawn(async move {
            if let Some(ref agent) = agent {
                if let Ok(sys_info) = agent.get_diagnostics_system_info().await {
                    let dump = serde_json::to_string_pretty(&sys_info).unwrap_or_default();
                    let _ = agent.copy_clipboard(&dump).await;
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak.upgrade() {
                            w.set_toast_visible(true);
                            w.set_toast_title("Diagnostics Copied".into());
                            w.set_toast_detail("System diagnostic data copied to clipboard ✓".into());
                            w.set_toast_status("completed".into());
                            push_toast(&w, "diag-copy", "Diagnostics Copied", "System diagnostic data copied to clipboard ✓", "completed");
                        }
                    });
                }
            }
        });
    });

    let agent_client_chk_up = agent_client.clone();
    let win_weak_chk_up = main_window.as_weak();
    let rt_chk_up = rt.clone();
    main_window.on_check_updates(move || {
        println!("[NLC-Rust] Checking for updates...");
        let win_weak = win_weak_chk_up.clone();
        let agent = agent_client_chk_up.clone();
        rt_chk_up.spawn(async move {
            let mut is_update = false;
            let mut latest_ver = String::from(env!("CARGO_PKG_VERSION"));
            if let Some(ref a) = agent {
                if let Ok(res) = a.call::<serde_json::Value>("system_check_updates", serde_json::json!({})).await {
                    if let Some(up) = res.get("update_available").and_then(|v| v.as_bool()) {
                        is_update = up;
                    }
                    if let Some(ver) = res.get("latest_version").and_then(|v| v.as_str()) {
                        latest_ver = ver.to_string();
                    }
                }
            }
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(w) = win_weak.upgrade() {
                    w.set_toast_visible(true);
                    if is_update {
                        w.set_toast_title("Update Available!".into());
                        w.set_toast_detail(format!("New version v{} is available.", latest_ver).into());
                        w.set_toast_status("info".into());
                        push_toast(&w, "updater", "Update Available!", &format!("New version v{} is available.", latest_ver), "info");
                    } else {
                        w.set_toast_title("Launcher is Up to Date".into());
                        w.set_toast_detail(format!("Running latest version (v{}).", latest_ver).into());
                        w.set_toast_status("completed".into());
                        push_toast(&w, "updater", "Launcher is Up to Date", &format!("Running latest version (v{}).", latest_ver), "completed");
                    }
                }
            });
        });
    });

    // 13. Wire Loader and Version Selection
    let agent_client_loader = agent_client.clone();
    let win_weak_loader = main_window.as_weak();
    let rt_loader = rt.clone();
    main_window.on_loader_changed(move |loader| {
        let loader_str = loader.to_string();
        println!("[NLC-Rust] Loader selection changed to: {}", loader_str);
        let agent = agent_client_loader.clone();
        let win_weak_inner = win_weak_loader.clone();
        rt_loader.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = slint::invoke_from_event_loop({
                    let win_weak_status = win_weak_inner.clone();
                    let loader_name = loader_str.clone();
                    move || {
                        if let Some(w) = win_weak_status.upgrade() {
                            w.set_version_fetch_status(format!("Fetching {} versions...", loader_name).into());
                        }
                    }
                });
                if let Ok(resp) = agent.list_versions(&loader_str, false).await {
                    let versions: Vec<slint::SharedString> = resp.releases.iter().map(|s| s.as_str().into()).collect();
                    let count = versions.len();
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak_inner.upgrade() {
                            if !versions.is_empty() {
                                w.set_available_versions(std::rc::Rc::new(slint::VecModel::from(versions)).into());
                            }
                            w.set_version_fetch_status(format!("Found {} {} versions", count, loader_str).into());
                        }
                    });
                }
            }
        });
    });

    let agent_client_snaps = agent_client.clone();
    let win_weak_snaps = main_window.as_weak();
    let rt_snaps = rt.clone();
    main_window.on_toggle_snapshots(move |show_snapshots| {
        println!("[NLC-Rust] Toggle snapshots: {}", show_snapshots);
        let agent = agent_client_snaps.clone();
        let win_weak_inner = win_weak_snaps.clone();
        rt_snaps.spawn(async move {
            if let Some(ref agent) = agent {
                if let Ok(resp) = agent.list_versions("Vanilla", show_snapshots).await {
                    let versions_list = if show_snapshots {
                        let mut all = resp.releases.clone();
                        all.extend(resp.snapshots.clone());
                        all
                    } else {
                        resp.releases
                    };
                    let versions: Vec<slint::SharedString> = versions_list.iter().map(|s| s.as_str().into()).collect();
                    let count = versions.len();
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak_inner.upgrade() {
                            if !versions.is_empty() {
                                w.set_available_versions(std::rc::Rc::new(slint::VecModel::from(versions)).into());
                            }
                            w.set_version_fetch_status(format!("Found {} versions", count).into());
                        }
                    });
                }
            }
        });
    });

    // 14. Wire Modrinth Search, Details, Installation and Lazy Loading
    let agent_client_mr_search = agent_client.clone();
    let win_weak_mr_search = main_window.as_weak();
    let search_state_search = search_state.clone();
    let rt_mr_search = rt.clone();
    let root_dir_mr_search = project_root.clone();
    main_window.on_modrinth_search(move |query, mode, loader, version, sort| {
        let q = query.to_string();
        let m = mode.to_string();
        let l = loader.to_string();
        let v = version.to_string();
        let s = sort.to_string();
        println!("[NLC-Rust] Modrinth search: query='{}', mode='{}', loader='{}', version='{}', sort='{}'", q, m, l, v, s);

        let agent = agent_client_mr_search.clone();
        let win_weak = win_weak_mr_search.clone();
        let s_state = search_state_search.clone();
        let root_dir = root_dir_mr_search.clone();
        rt_mr_search.spawn(async move {
            if let Some(ref agent) = agent {
                {
                    let mut st = s_state.lock().await;
                    st.query = q.clone();
                    st.mode = m.clone();
                    st.loader = l.clone();
                    st.version = v.clone();
                    st.sort = s.clone();
                    st.offset = 0;
                    st.has_more = true;
                    st.is_loading = true;
                }

                let _ = slint::invoke_from_event_loop({
                    let win = win_weak.clone();
                    move || {
                        if let Some(w) = win.upgrade() {
                            w.set_modrinth_is_loading(true);
                            w.set_modrinth_status_text("".into());
                            w.set_modrinth_projects(std::rc::Rc::new(slint::VecModel::default()).into());
                        }
                    }
                });

                let l_opt = if l == "All" || l.is_empty() { None } else { Some(l.to_lowercase()) };
                let v_opt = if v == "All" || v.is_empty() { None } else { Some(v) };
                let s_opt = if s.is_empty() { None } else { Some(s.to_lowercase()) };

                let req = ipc::ModrinthSearchRequest {
                    query: q,
                    project_type: Some(m.clone()),
                    loader: l_opt,
                    version: v_opt,
                    sort: s_opt,
                    limit: Some(20),
                    offset: Some(0),
                };

                match agent.search_modrinth(req).await {
                    Ok(resp) => {
                        let hits: Vec<ipc::ModrinthHit> = resp.hits().to_vec();
                        let default_type = m.clone();
                        let count = hits.len();
                        {
                            let mut st = s_state.lock().await;
                            st.offset = count as u32;
                            st.has_more = count >= 20;
                            st.is_loading = false;
                        }
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_weak.upgrade() {
                                let cards: Vec<ModrinthProjectData> = hits.iter().map(|h| map_modrinth_hit(h, &default_type, &root_dir)).collect();
                                w.set_modrinth_projects(std::rc::Rc::new(slint::VecModel::from(cards)).into());
                                w.set_modrinth_is_loading(false);
                                w.set_modrinth_has_more(count >= 20);
                                w.set_modrinth_status_text("".into());
                            }
                        });
                    }
                    Err(e) => {
                        let err_str = e.to_string();
                        {
                            let mut st = s_state.lock().await;
                            st.is_loading = false;
                        }
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_weak.upgrade() {
                                w.set_modrinth_is_loading(false);
                                w.set_modrinth_status_text(format!("Error: {}", err_str).into());
                            }
                        });
                    }
                }
            }
        });
    });

    let agent_client_mr_more = agent_client.clone();
    let win_weak_mr_more = main_window.as_weak();
    let search_state_more = search_state.clone();
    let rt_mr_more = rt.clone();
    let root_dir_mr_more = project_root.clone();
    main_window.on_modrinth_load_more(move || {
        let agent = agent_client_mr_more.clone();
        let win_weak = win_weak_mr_more.clone();
        let s_state = search_state_more.clone();
        let root_dir = root_dir_mr_more.clone();

        rt_mr_more.spawn(async move {
            let (query, mode, loader, version, sort, offset) = {
                let mut st = s_state.lock().await;
                if st.is_loading || !st.has_more {
                    return;
                }
                st.is_loading = true;
                (st.query.clone(), st.mode.clone(), st.loader.clone(), st.version.clone(), st.sort.clone(), st.offset)
            };

            println!("[NLC-Rust] Loading more Modrinth items: offset={}", offset);

            let _ = slint::invoke_from_event_loop({
                let win = win_weak.clone();
                move || {
                    if let Some(w) = win.upgrade() {
                        w.set_modrinth_is_loading(true);
                        w.set_modrinth_status_text("Loading more projects...".into());
                    }
                }
            });

            if let Some(ref agent) = agent {
                let l_opt = if loader == "All" || loader.is_empty() { None } else { Some(loader.to_lowercase()) };
                let v_opt = if version == "All" || version.is_empty() { None } else { Some(version) };
                let s_opt = if sort.is_empty() { None } else { Some(sort.to_lowercase()) };

                let req = ipc::ModrinthSearchRequest {
                    query,
                    project_type: Some(mode.clone()),
                    loader: l_opt,
                    version: v_opt,
                    sort: s_opt,
                    limit: Some(20),
                    offset: Some(offset),
                };

                match agent.search_modrinth(req).await {
                    Ok(resp) => {
                        let hits: Vec<ipc::ModrinthHit> = resp.hits().to_vec();
                        let count = hits.len();
                        {
                            let mut st = s_state.lock().await;
                            st.offset += count as u32;
                            st.has_more = count >= 20;
                            st.is_loading = false;
                        }
                        let default_type = mode.clone();
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_weak.upgrade() {
                                let current_model = w.get_modrinth_projects();
                                let mut all_cards: Vec<ModrinthProjectData> = Vec::new();
                                for i in 0..current_model.row_count() {
                                    if let Some(card) = current_model.row_data(i) {
                                        all_cards.push(card);
                                    }
                                }
                                for h in &hits {
                                    all_cards.push(map_modrinth_hit(h, &default_type, &root_dir));
                                }
                                let total = all_cards.len();
                                w.set_modrinth_projects(std::rc::Rc::new(slint::VecModel::from(all_cards)).into());
                                w.set_modrinth_is_loading(false);
                                w.set_modrinth_has_more(count >= 20);
                                w.set_modrinth_status_text(format!("{} projects loaded", total).into());
                            }
                        });
                    }
                    Err(e) => {
                        let err_str = e.to_string();
                        {
                            let mut st = s_state.lock().await;
                            st.is_loading = false;
                        }
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_weak.upgrade() {
                                w.set_modrinth_is_loading(false);
                                w.set_modrinth_status_text(format!("Load more error: {}", err_str).into());
                            }
                        });
                    }
                }
            } else {
                let mut st = s_state.lock().await;
                st.is_loading = false;
                let _ = slint::invoke_from_event_loop(move || {
                    if let Some(w) = win_weak.upgrade() {
                        w.set_modrinth_is_loading(false);
                    }
                });
            }
        });
    });

    let agent_client_mr_det = agent_client.clone();
    let win_weak_mr_det = main_window.as_weak();
    let rt_mr_det = rt.clone();
    let root_dir_mr_det = project_root.clone();
    main_window.on_modrinth_open_details(move |project_id| {
        let p_id = project_id.to_string();
        println!("[NLC-Rust] Modrinth fetch project details: {}", p_id);
        let agent = agent_client_mr_det.clone();
        let win_weak = win_weak_mr_det.clone();
        let root_dir = root_dir_mr_det.clone();
        rt_mr_det.spawn(async move {
            if let Some(ref agent) = agent {
                let _ = slint::invoke_from_event_loop({
                    let win = win_weak.clone();
                    let pid = p_id.clone();
                    move || {
                        if let Some(w) = win.upgrade() {
                            w.set_modrinth_details_id(pid.into());
                            w.set_modrinth_view_mode("details".into());
                            w.set_modrinth_details_install_status("idle".into());
                        }
                    }
                });

                if let Ok(details) = agent.get_modrinth_project(&p_id).await {
                    let title = details.get("title").and_then(|v| v.as_str()).unwrap_or("").to_string();
                    let desc = details.get("description").and_then(|v| v.as_str()).unwrap_or("").to_string();
                    let body = details.get("body").and_then(|v| v.as_str()).unwrap_or("").to_string();
                    let dls = details.get("downloads").and_then(|v| v.as_u64()).map(format_count).unwrap_or_else(|| "0".to_string());
                    let flws = details.get("followers").or(details.get("follows")).and_then(|v| v.as_u64()).map(format_count).unwrap_or_else(|| "0".to_string());
                    let p_type = details.get("project_type").and_then(|v| v.as_str()).unwrap_or("mod").to_string();
                    let loaders = details.get("loaders").and_then(|v| v.as_array())
                        .map(|arr| arr.iter().filter_map(|s| s.as_str()).collect::<Vec<_>>().join(", "))
                        .unwrap_or_default();

                    let raw_gallery_items: Vec<(String, String, String, Option<std::path::PathBuf>)> = details.get("gallery").and_then(|v| v.as_array())
                        .map(|arr| {
                            arr.iter().enumerate().map(|(idx, item)| {
                                let u = item.get("url").and_then(|s| s.as_str()).unwrap_or("").to_string();
                                let t = item.get("title").and_then(|s| s.as_str()).unwrap_or("").to_string();
                                let d = item.get("description").and_then(|s| s.as_str()).unwrap_or("").to_string();
                                let p = resolve_gallery_item_image_path(&p_id, idx, &root_dir);
                                (u, t, d, p)
                            }).collect()
                        }).unwrap_or_default();

                    let icon_path = resolve_project_id_icon_path(&p_id, &root_dir);

                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak.upgrade() {
                            w.set_modrinth_details_title(title.into());
                            w.set_modrinth_details_desc(desc.into());
                            w.set_modrinth_details_body(body.into());
                            w.set_modrinth_details_downloads(dls.into());
                            w.set_modrinth_details_follows(flws.into());
                            w.set_modrinth_details_type(p_type.into());
                            w.set_modrinth_details_loaders(loaders.into());
                            // Versions are NOT loaded by default until requested by user
                            w.set_modrinth_details_versions(std::rc::Rc::new(slint::VecModel::default()).into());
                            let gallery_items: Vec<ModrinthGalleryItem> = raw_gallery_items.into_iter().map(|(u, t, d, local_p)| {
                                let mut has_img = false;
                                let mut img = slint::Image::default();
                                if let Some(ref p) = local_p {
                                    if let Some(loaded) = load_image_safely(p) {
                                        has_img = true;
                                        img = loaded;
                                    }
                                }
                                ModrinthGalleryItem {
                                    url: u.into(),
                                    title: t.into(),
                                    description: d.into(),
                                    has_image: has_img,
                                    image: img,
                                }
                            }).collect();
                            w.set_modrinth_details_gallery(std::rc::Rc::new(slint::VecModel::from(gallery_items)).into());
                            if let Some(ref ip) = icon_path {
                                if let Some(img) = load_image_safely(ip) {
                                    w.set_modrinth_details_has_icon(true);
                                    w.set_modrinth_details_icon(img);
                                } else {
                                    w.set_modrinth_details_has_icon(false);
                                }
                            } else {
                                w.set_modrinth_details_has_icon(false);
                            }
                        }
                    });
                }
            }
        });
    });

    let agent_client_mr_ver = agent_client.clone();
    let win_weak_mr_ver = main_window.as_weak();
    let rt_mr_ver = rt.clone();
    main_window.on_modrinth_load_versions(move |project_id| {
        let p_id = project_id.to_string();
        println!("[NLC-Rust] Modrinth load versions requested on-demand for: {}", p_id);
        let agent = agent_client_mr_ver.clone();
        let win_weak = win_weak_mr_ver.clone();
        rt_mr_ver.spawn(async move {
            if let Some(ref agent) = agent {
                if let Ok(details) = agent.get_modrinth_project(&p_id).await {
                    let versions: Vec<ModrinthVersionData> = details.get("versions").and_then(|v| v.as_array())
                        .map(|arr| arr.iter().take(40).map(map_modrinth_version).collect::<Vec<_>>())
                        .unwrap_or_default();
                    let _ = slint::invoke_from_event_loop(move || {
                        if let Some(w) = win_weak.upgrade() {
                            w.set_modrinth_details_versions(std::rc::Rc::new(slint::VecModel::from(versions)).into());
                        }
                    });
                }
            }
        });
    });

    let agent_client_mr_inst = agent_client.clone();
    let win_weak_mr_inst = main_window.as_weak();
    let rt_mr_inst = rt.clone();
    main_window.on_modrinth_install(move |project_id, project_type, target_dest, version_id| {
        let p_id = project_id.to_string();
        let p_type = project_type.to_string();
        let target = target_dest.to_string();

        let is_real_dest = if let Some(w) = win_weak_mr_inst.upgrade() {
            let packs = w.get_modpacks();
            let mut found = false;
            for i in 0..packs.row_count() {
                if let Some(mp) = packs.row_data(i) {
                    if mp.name == target.as_str() || mp.id == target.as_str() {
                        found = true;
                        break;
                    }
                }
            }
            if !found {
                let installs = w.get_installations();
                for i in 0..installs.row_count() {
                    if let Some(inst) = installs.row_data(i) {
                        if inst.name == target.as_str() || inst.id == target.as_str() {
                            found = true;
                            break;
                        }
                    }
                }
            }
            found
        } else {
            false
        };

        let share_rp = if let Some(w) = win_weak_mr_inst.upgrade() { w.get_share_resource_packs() } else { true };
        let share_sp = if let Some(w) = win_weak_mr_inst.upgrade() { w.get_share_shader_packs() } else { true };
        let requires_dest = p_type == "mod"
            || (p_type == "resourcepack" && !share_rp)
            || (p_type == "shader" && !share_sp);

        if requires_dest && !is_real_dest {
            let win = win_weak_mr_inst.clone();
            let p_type_cloned = p_type.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(w) = win.upgrade() {
                    let type_label = if p_type_cloned == "shader" { "shader pack" } else if p_type_cloned == "resourcepack" { "resource pack" } else { "mod" };
                    w.set_toast_visible(true);
                    w.set_toast_title("Destination Required".into());
                    w.set_toast_detail(format!("Please select a target installation to install this {}.", type_label).into());
                    w.set_toast_status("warning".into());
                    push_toast(&w, "dest-required", "Destination Required", &format!("Please select a target installation to install this {}.", type_label), "warning");
                }
            });
            return;
        }

        let final_target = if is_real_dest { target } else { "".to_string() };
        let v_id = if version_id.is_empty() { None } else { Some(version_id.to_string()) };
        println!("[NLC-Rust] Modrinth install: id='{}', type='{}', target='{}', ver='{:?}'", p_id, p_type, final_target, v_id);

        let agent = agent_client_mr_inst.clone();
        let win_weak = win_weak_mr_inst.clone();
        rt_mr_inst.spawn(async move {
            if let Some(ref agent) = agent {
                let title_opt = if let Some(w) = win_weak.upgrade() {
                    let t = w.get_modrinth_details_title().to_string();
                    if !t.is_empty() { Some(t) } else { None }
                } else {
                    None
                };
                let display_title = title_opt.clone().unwrap_or_else(|| p_id.clone());

                let _ = slint::invoke_from_event_loop({
                    let win = win_weak.clone();
                    let pid = p_id.clone();
                    let title = display_title.clone();
                    move || {
                        if let Some(w) = win.upgrade() {
                            w.set_modrinth_status_text(format!("Installing {}...", title).into());
                            w.set_modrinth_details_install_status("installing".into());
                            if !w.get_notifications_open() {
                                w.set_toast_visible(true);
                            }
                            w.set_toast_title(title.clone().into());
                            w.set_toast_detail("Starting download...".into());
                            w.set_toast_progress(0.0);
                            w.set_toast_status("normal".into());
                            push_toast_with_progress(&w, &format!("dl-proj-{}", pid), &title, "Starting download...", "normal", 0.0, true, "");
                        }
                    }
                });
                let res = agent.install_modrinth_artifact(&p_id, &p_type, &final_target, v_id.as_deref(), None, None, title_opt.as_deref()).await;
                match res {
                    Ok(_) => {
                        println!("[NLC-Rust] Successfully installed {}", p_id);
                        if let Ok(packs) = agent.list_modpacks().await {
                            let win_weak_packs = win_weak.clone();
                            let _ = slint::invoke_from_event_loop(move || {
                                if let Some(w) = win_weak_packs.upgrade() {
                                    let slint_packs: Vec<ModpackData> = packs.iter().map(map_modpack).collect();
                                    sync_modrinth_destinations(&w, &slint_packs);
                                    w.set_modpacks(std::rc::Rc::new(slint::VecModel::from(slint_packs)).into());
                                }
                            });
                        }
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_weak.upgrade() {
                                w.set_modrinth_status_text(format!("Installed {} successfully! ✓", display_title).into());
                                w.set_modrinth_details_install_status("installed".into());
                            }
                        });
                    }
                    Err(e) => {
                        let err_msg = e.to_string();
                        eprintln!("[NLC-Rust] Failed to install {}: {}", p_id, err_msg);
                        let _ = slint::invoke_from_event_loop(move || {
                            if let Some(w) = win_weak.upgrade() {
                                w.set_modrinth_status_text(format!("Install error: {}", err_msg).into());
                                w.set_modrinth_details_install_status("idle".into());
                                w.set_toast_status("error".into());
                                w.set_toast_detail(err_msg.into());
                            }
                        });
                    }
                }
            }
        });
    });

    // 15. Wire Notification Center Callbacks
    let win_weak_notif_clear = main_window.as_weak();
    main_window.on_clear_notifications(move || {
        if let Some(w) = win_weak_notif_clear.upgrade() {
            w.set_notifications(std::rc::Rc::new(slint::VecModel::default()).into());
            w.set_active_downloads_count(0);
            w.set_active_sessions_count(0);
            w.set_unread_notifications(0);
        }
    });

    let win_weak_notif_dismiss = main_window.as_weak();
    main_window.on_dismiss_notification(move |target_id| {
        if let Some(w) = win_weak_notif_dismiss.upgrade() {
            let current = w.get_notifications();
            let mut items: Vec<NotificationItemData> = Vec::new();
            for i in 0..current.row_count() {
                if let Some(item) = current.row_data(i) {
                    if item.id != target_id {
                        items.push(item);
                    }
                }
            }
            let mut dl_count = 0;
            let mut sess_count = 0;
            let mut unread = 0;
            for item in &items {
                if item.category == "Downloads" {
                    dl_count += 1;
                } else if item.category == "Sessions" {
                    sess_count += 1;
                }
                if !item.is_read {
                    unread += 1;
                }
            }
            w.set_notifications(std::rc::Rc::new(slint::VecModel::from(items)).into());
            w.set_active_downloads_count(dl_count);
            w.set_active_sessions_count(sess_count);
            w.set_unread_notifications(unread);
        }
    });

    // 15b. Active Game Sessions Timer & Terminate Callback
    let sessions_timer = slint::Timer::default();
    let win_weak_timer = main_window.as_weak();
    let tracker_timer = active_sessions_tracker.clone();
    sessions_timer.start(
        slint::TimerMode::Repeated,
        std::time::Duration::from_millis(1000),
        move || {
            if let Some(win) = win_weak_timer.upgrade() {
                sync_active_sessions_to_ui(&win, &tracker_timer);
            }
        },
    );

    let win_weak_terminate = main_window.as_weak();
    let tracker_terminate = active_sessions_tracker.clone();
    let agent_client_term = agent_client.clone();
    main_window.on_terminate_game_session(move |launch_id| {
        let id_str = launch_id.to_string();
        println!("[NLC-Rust] Terminating game session: {}", id_str);
        if let Ok(mut list) = tracker_terminate.lock() {
            list.retain(|s| s.id != id_str);
        }
        if let Some(win) = win_weak_terminate.upgrade() {
            sync_active_sessions_to_ui(&win, &tracker_terminate);
        }
        if let Some(ref agent) = agent_client_term {
            let agent = agent.clone();
            let kill_id = id_str.clone();
            tokio::spawn(async move {
                let req = ipc::KillGameRequest {
                    launch_id: if kill_id.is_empty() { None } else { Some(kill_id) },
                };
                if let Err(err) = agent.kill_game(req).await {
                    eprintln!("[NLC-Rust] Error terminating game session: {}", err);
                }
            });
        }
    });

    // 15c. Stacked Notification Toasts Timer & Callbacks
    let toast_timer = slint::Timer::default();
    let win_weak_toast_timer = main_window.as_weak();
    toast_timer.start(
        slint::TimerMode::Repeated,
        std::time::Duration::from_millis(100),
        move || {
            if let Some(win) = win_weak_toast_timer.upgrade() {
                if let Ok(mut list) = get_toast_tracker().lock() {
                    if list.is_empty() {
                        return;
                    }
                    let mut changed = false;
                    list.retain_mut(|t| {
                        if !t.is_sticky && !t.is_paused {
                            if t.remaining_ms <= 100 {
                                changed = true;
                                return false;
                            } else {
                                t.remaining_ms -= 100;
                                t.timeout_fraction = t.remaining_ms as f32 / t.total_ms as f32;
                                changed = true;
                            }
                        }
                        true
                    });
                    if changed {
                        sync_toasts_to_ui(&win, &list);
                    }
                }
            }
        },
    );

    let win_weak_dismiss_toast = main_window.as_weak();
    main_window.on_dismiss_toast(move |id| {
        let id_str = id.to_string();
        if let Ok(mut list) = get_toast_tracker().lock() {
            list.retain(|t| t.id != id_str);
            if let Some(win) = win_weak_dismiss_toast.upgrade() {
                sync_toasts_to_ui(&win, &list);
            }
        }
    });

    let win_weak_copy_toast = main_window.as_weak();
    let agent_client_copy_toast = agent_client.clone();
    let rt_copy_toast = rt.clone();
    main_window.on_copy_toast_error(move |err| {
        let err_str = err.to_string();
        let agent = agent_client_copy_toast.clone();
        rt_copy_toast.spawn(async move {
            if let Some(ref a) = agent {
                let _ = a.copy_clipboard(&err_str).await;
            }
        });
        if let Some(win) = win_weak_copy_toast.upgrade() {
            push_toast(
                &win,
                "copy-feedback",
                "Error Copied",
                "Error details copied to clipboard ✓",
                "completed",
            );
        }
    });

    main_window.on_pause_toast(move |id| {
        let id_str = id.to_string();
        if let Ok(mut list) = get_toast_tracker().lock() {
            if let Some(t) = list.iter_mut().find(|t| t.id == id_str) {
                t.is_paused = true;
            }
        }
    });

    main_window.on_resume_toast(move |id| {
        let id_str = id.to_string();
        if let Ok(mut list) = get_toast_tracker().lock() {
            if let Some(t) = list.iter_mut().find(|t| t.id == id_str) {
                t.is_paused = false;
            }
        }
    });

    // 15d. Loading Spinner & Walking Mob Animation Controllers
    let _animations = if let Some(anim_state) = animations::init_animations_state(&project_root) {
        Some(animations::start_animation_controllers(&main_window, anim_state))
    } else {
        None
    };

    // 16. Run Native GPU Window Event Loop (60/144Hz VSync atomic presentation)
    println!("[NLC-Rust] Launching native 1:1 GPU window with zero-tear VSync...");
    let _keep_tray = tray;
    let _keep_animations = _animations;
    main_window.run()?;

    if let Some(ref agent) = agent_client {
        agent.shutdown().await;
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_hex_to_rgb_valid_and_adversarial() {
        // Valid 6-digit hex
        assert_eq!(hex_to_rgb("#00E5FF"), Some((0x00, 0xE5, 0xFF)));
        assert_eq!(hex_to_rgb("00e5ff"), Some((0x00, 0xE5, 0xFF)));
        assert_eq!(hex_to_rgb("0x2ECC71"), Some((0x2E, 0xCC, 0x71)));

        // Valid 3-digit shorthand hex
        assert_eq!(hex_to_rgb("#fff"), Some((255, 255, 255)));
        assert_eq!(hex_to_rgb("000"), Some((0, 0, 0)));

        // Valid 8-digit RGBA hex
        assert_eq!(hex_to_rgb("#BD93F9FF"), Some((0xBD, 0x93, 0xF9)));

        // Adversarial inputs that should return None gracefully without panicking
        assert_eq!(hex_to_rgb("#zzz"), None);
        assert_eq!(hex_to_rgb(""), None);
        assert_eq!(hex_to_rgb("   "), None);
        assert_eq!(hex_to_rgb("#12345"), None); // Invalid length 5
        assert_eq!(hex_to_rgb("#1234567"), None); // Invalid length 7
        assert_eq!(hex_to_rgb("€"), None); // Non-ASCII byte length 3
        assert_eq!(hex_to_rgb("€€"), None); // Non-ASCII byte length 6
        assert_eq!(hex_to_rgb("🦀"), None); // Emoji
        assert_eq!(hex_to_rgb("#!@#$%"), None);
    }

    #[test]
    fn test_all_six_themes_palette_mapping() {
        let themes = [
            ("Dark Slate", "#1E2025", "#2ECC71"),
            ("OLED Obsidian", "#0A0A0A", "#00E5FF"),
            ("Catppuccin Mocha", "#1E1E2E", "#CBA6F7"),
            ("Nord Frost", "#2E3440", "#88C0D0"),
            ("Dracula Midnight", "#282A36", "#BD93F9"),
            ("Emerald Pine", "#162119", "#27AE60"),
        ];

        for (name, expected_bg, expected_accent) in themes {
            let p = get_theme_palette(name);
            assert_eq!(p.main_bg, expected_bg, "Theme {} main_bg mismatch", name);
            assert_eq!(p.default_accent, expected_accent, "Theme {} default_accent mismatch", name);
        }

        // Fallback for unknown theme
        let fallback = get_theme_palette("UnknownCustomTheme");
        assert_eq!(fallback.main_bg, "#1E2025");
        assert_eq!(fallback.default_accent, "#2ECC71");
    }

    #[test]
    fn test_post_launch_action_config_and_behavior_mapping() {
        let json_str = r#"{
            "version": "1.21.4",
            "post_launch_action": "Minimise to tray"
        }"#;
        let config: ipc::LauncherConfig = serde_json::from_str(json_str).expect("Valid config JSON");
        assert_eq!(config.post_launch_action.as_deref(), Some("Minimise to tray"));

        let json_extra = r#"{
            "version": "1.21.4"
        }"#;
        let config_extra: ipc::LauncherConfig = serde_json::from_str(json_extra).expect("Valid config JSON");
        assert_eq!(config_extra.post_launch_action, None);

        // Verify the 4 post-launch action strings and slugs
        let categorize = |action: &str| -> &'static str {
            match action.trim() {
                "Minimise to taskbar" | "minimize_taskbar" => "taskbar",
                "Minimise to tray" | "minimize_tray" => "tray",
                "Close" | "close" => "close",
                _ => "do_nothing",
            }
        };

        assert_eq!(categorize("Minimise to taskbar"), "taskbar");
        assert_eq!(categorize("minimize_taskbar"), "taskbar");
        assert_eq!(categorize("Minimise to tray"), "tray");
        assert_eq!(categorize("minimize_tray"), "tray");
        assert_eq!(categorize("Close"), "close");
        assert_eq!(categorize("close"), "close");
        assert_eq!(categorize("Do nothing"), "do_nothing");
        assert_eq!(categorize("do_nothing"), "do_nothing");
        assert_eq!(categorize("anything_else"), "do_nothing");
    }

    #[test]
    fn test_normalize_launch_progress_both_scales() {
        // 0.0 - 1.0 unit scale
        assert_eq!(normalize_launch_progress(0.0), 0.0);
        assert!((normalize_launch_progress(0.45) - 0.45).abs() < 1e-6);
        assert_eq!(normalize_launch_progress(1.0), 1.0);

        // 0 - 100 percentage scale
        assert!((normalize_launch_progress(10.0) - 0.10).abs() < 1e-6);
        assert!((normalize_launch_progress(50.0) - 0.50).abs() < 1e-6);
        assert!((normalize_launch_progress(85.0) - 0.85).abs() < 1e-6);
        assert_eq!(normalize_launch_progress(100.0), 1.0);

        // Out of bounds clamping
        assert_eq!(normalize_launch_progress(-10.0), 0.0);
        assert_eq!(normalize_launch_progress(150.0), 1.0);

        // Adversarial non-finite inputs
        assert_eq!(normalize_launch_progress(f32::NAN), 0.0);
        assert_eq!(normalize_launch_progress(f32::INFINITY), 0.0);
        assert_eq!(normalize_launch_progress(f32::NEG_INFINITY), 0.0);
    }

    #[test]
    fn test_validate_minecraft_username_identity() {
        // Valid usernames
        assert!(validate_minecraft_username("Steve").is_ok());
        assert!(validate_minecraft_username("Alex_123").is_ok());
        assert!(validate_minecraft_username("pro_gamer_2026").is_ok());
        assert!(validate_minecraft_username("abc").is_ok()); // Minimum 3 chars
        assert!(validate_minecraft_username("1234567890123456").is_ok()); // Exactly 16 chars

        // Invalid: empty or whitespace
        assert!(validate_minecraft_username("").is_err());
        assert!(validate_minecraft_username("   ").is_err());

        // Invalid: length out of bounds
        assert!(validate_minecraft_username("ab").is_err()); // Too short (< 3)
        assert!(validate_minecraft_username("12345678901234567").is_err()); // Too long (> 16)

        // Invalid: special characters & spaces
        assert!(validate_minecraft_username("Steve 123").is_err()); // Spaces not allowed
        assert!(validate_minecraft_username("Steve!").is_err()); // Punctuation
        assert!(validate_minecraft_username("Steve@work").is_err());
        assert!(validate_minecraft_username("User-Name").is_err()); // Hyphen not allowed in vanilla MC handles
        assert!(validate_minecraft_username("🎮player").is_err()); // Unicode/Emoji
    }
}

