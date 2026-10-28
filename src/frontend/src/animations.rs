use image::codecs::gif::GifDecoder;
use image::AnimationDecoder;
use image::{imageops, RgbaImage};
use std::fs::File;
use std::io::BufReader;
use std::path::Path;
use std::time::{Duration, Instant};
use crate::MainWindow;
use slint::ComponentHandle;

#[derive(Clone)]
pub struct AnimationFrames {
    #[allow(dead_code)]
    pub name: &'static str,
    pub frames_facing_left: Vec<slint::Image>,
    pub frames_facing_right: Vec<slint::Image>,
    pub frame_delay: Duration,
    pub width: u32,
    pub height: u32,
    pub is_flying: bool,
}

#[derive(Clone)]
pub struct AnimationsState {
    pub copper_golem_frames: Vec<slint::Image>,
    pub copper_golem_delay: Duration,
    pub mobs: Vec<AnimationFrames>,
}

fn rgba_to_slint_image(rgba: &RgbaImage) -> slint::Image {
    let (w, h) = rgba.dimensions();
    let mut buffer = slint::SharedPixelBuffer::<slint::Rgba8Pixel>::new(w, h);
    buffer.make_mut_bytes().copy_from_slice(rgba.as_raw());
    slint::Image::from_rgba8(buffer)
}

/// Decodes all frames from a GIF file, crops transparent margins, and scales to target height.
pub fn load_cropped_gif(
    path: &Path,
    target_height: u32,
    is_flying: bool,
    name: &'static str,
) -> Option<AnimationFrames> {
    if !path.exists() {
        return None;
    }

    let file = File::open(path).ok()?;
    let reader = BufReader::new(file);
    let decoder = GifDecoder::new(reader).ok()?;
    let raw_frames = decoder.into_frames().collect_frames().ok()?;
    if raw_frames.is_empty() {
        return None;
    }

    // Default frame delay fallback: 50ms
    let (num, denom) = raw_frames[0].delay().numer_denom_ms();
    let delay_ms = if denom == 0 || num == 0 { 50 } else { num / denom };
    let frame_delay = Duration::from_millis(delay_ms.max(20) as u64);

    // Compute union bounding box of non-transparent pixels across all frames
    let mut min_x = u32::MAX;
    let mut min_y = u32::MAX;
    let mut max_x = 0u32;
    let mut max_y = 0u32;
    let mut has_content = false;

    let rgba_frames: Vec<RgbaImage> = raw_frames.into_iter().map(|f| f.into_buffer()).collect();

    for frame in &rgba_frames {
        let (w, h) = frame.dimensions();
        for y in 0..h {
            for x in 0..w {
                if frame.get_pixel(x, y)[3] > 10 {
                    has_content = true;
                    if x < min_x { min_x = x; }
                    if x > max_x { max_x = x; }
                    if y < min_y { min_y = y; }
                    if y > max_y { max_y = y; }
                }
            }
        }
    }

    let (first_w, first_h) = rgba_frames[0].dimensions();
    let (crop_x, crop_y, crop_w, crop_h) = if has_content && max_x >= min_x && max_y >= min_y {
        (min_x, min_y, (max_x - min_x + 1).max(1), (max_y - min_y + 1).max(1))
    } else {
        (0, 0, first_w, first_h)
    };

    let aspect = crop_w as f32 / crop_h as f32;
    let scaled_w = (target_height as f32 * aspect).round().max(1.0) as u32;

    let mut frames_left = Vec::with_capacity(rgba_frames.len());
    let mut frames_right = Vec::with_capacity(rgba_frames.len());

    // All 4 mob GIFs naturally face LEFT.
    // Unflipped `scaled` faces LEFT; horizontal `flipped` faces RIGHT.
    for frame in rgba_frames {
        let cropped = imageops::crop_imm(&frame, crop_x, crop_y, crop_w, crop_h).to_image();
        let scaled = imageops::resize(&cropped, scaled_w, target_height, imageops::FilterType::Nearest);
        let flipped = imageops::flip_horizontal(&scaled);

        frames_left.push(rgba_to_slint_image(&scaled));
        frames_right.push(rgba_to_slint_image(&flipped));
    }

    Some(AnimationFrames {
        name,
        frames_facing_left: frames_left,
        frames_facing_right: frames_right,
        frame_delay,
        width: scaled_w,
        height: target_height,
        is_flying,
    })
}

pub fn init_animations_state(project_root: &Path) -> Option<AnimationsState> {
    let mut loading_dir = project_root.join("assets").join("loading");
    let mut walking_dir = project_root.join("assets").join("walking");

    if !loading_dir.exists() {
        if let Ok(exe) = std::env::current_exe() {
            if let Some(parent) = exe.parent() {
                if parent.join("assets").join("loading").exists() {
                    loading_dir = parent.join("assets").join("loading");
                    walking_dir = parent.join("assets").join("walking");
                }
            }
        }
    }
    if !loading_dir.exists() {
        if Path::new("assets").join("loading").exists() {
            loading_dir = Path::new("assets").join("loading").to_path_buf();
            walking_dir = Path::new("assets").join("walking").to_path_buf();
        } else if Path::new("../../assets").join("loading").exists() {
            loading_dir = Path::new("../../assets").join("loading").to_path_buf();
            walking_dir = Path::new("../../assets").join("walking").to_path_buf();
        }
    }

    let golem_path = loading_dir.join("Copper_golem_take_item_fail_JE1_BE1.gif");
    let golem_anim = load_cropped_gif(&golem_path, 72, false, "copper_golem");

    let (copper_golem_frames, copper_golem_delay) = match golem_anim {
        Some(a) => (a.frames_facing_left, a.frame_delay),
        None => (Vec::new(), Duration::from_millis(50)),
    };

    let mut mobs = Vec::new();

    // 1. Allay (Flying)
    let allay_path = walking_dir.join("Allay_Fly.gif");
    if let Some(m) = load_cropped_gif(&allay_path, 36, true, "allay") {
        mobs.push(m);
    }

    // 2. Baby White Rabbit (Walking)
    let rabbit_w_path = walking_dir.join("Baby_white_rabbit_move.gif");
    if let Some(m) = load_cropped_gif(&rabbit_w_path, 34, false, "white_rabbit") {
        mobs.push(m);
    }

    // 3. Bee (Flying)
    let bee_path = walking_dir.join("Bee_JE1.gif");
    if let Some(m) = load_cropped_gif(&bee_path, 34, true, "bee") {
        mobs.push(m);
    }

    // 4. Baby White Splotched Rabbit (Walking)
    let rabbit_s_path = walking_dir.join("Baby_white_splotched_rabbit_move.gif");
    if let Some(m) = load_cropped_gif(&rabbit_s_path, 34, false, "splotched_rabbit") {
        mobs.push(m);
    }

    println!(
        "[NLC-Rust] Loaded animations: Copper Golem ({} frames), Mobs: {} loaded",
        copper_golem_frames.len(),
        mobs.len()
    );

    Some(AnimationsState {
        copper_golem_frames,
        copper_golem_delay,
        mobs,
    })
}

pub fn compute_mob_boundaries(window_width: f32, scale_factor: f32, mob_width: f32) -> (f32, f32) {
    let win_w = (window_width / scale_factor.max(0.1)).max(800.0);
    let right_pane_w = (win_w - 240.0).max(400.0);
    let behind_sidebar_x = -mob_width - 6.0;
    let right_edge_x = (right_pane_w - 90.0).max(250.0);
    (behind_sidebar_x, right_edge_x)
}

pub fn compute_walking_mob_step(current_x: f32, target_x: f32, dt: f32, remaining_secs: f32) -> f32 {
    if remaining_secs <= dt || remaining_secs <= 0.0 {
        target_x
    } else {
        let step = (dt / remaining_secs).clamp(0.0, 1.0);
        let next_x = current_x + (target_x - current_x) * step;
        if current_x <= target_x {
            next_x.min(target_x)
        } else {
            next_x.max(target_x)
        }
    }
}

enum MobWalkStatus {
    Idle {
        next_walk_at: Instant,
    },
    Walking {
        mob_idx: usize,
        moving_right: bool,
        started_at: Instant,
        last_tick_at: Instant,
        current_x: f32,
        duration: Duration,
    },
}

pub struct AnimationControllers {
    pub _spinner_timer: slint::Timer,
    pub _walking_mob_timer: slint::Timer,
}

pub fn start_animation_controllers(
    main_window: &MainWindow,
    state: AnimationsState,
) -> AnimationControllers {
    let state = std::rc::Rc::new(state);

    // Set initial loading spinner frame immediately so any loading element has a ready frame
    if !state.copper_golem_frames.is_empty() {
        main_window.set_loading_spinner_frame(state.copper_golem_frames[0].clone());
    }

    // --- 1. Loading Spinner Controller ---
    let spinner_timer = slint::Timer::default();
    let win_weak_spinner = main_window.as_weak();
    let state_spinner = state.clone();
    let mut spinner_frame_idx = 0usize;

    spinner_timer.start(
        slint::TimerMode::Repeated,
        state_spinner.copper_golem_delay,
        move || {
            if let Some(win) = win_weak_spinner.upgrade() {
                let is_loading = win.get_addons_is_loading()
                    || win.get_modrinth_is_loading()
                    || win.get_steal_is_loading()
                    || win.get_startup_splash_active();

                if is_loading && !state_spinner.copper_golem_frames.is_empty() {
                    spinner_frame_idx = (spinner_frame_idx + 1) % state_spinner.copper_golem_frames.len();
                    win.set_loading_spinner_frame(state_spinner.copper_golem_frames[spinner_frame_idx].clone());
                }
            }
        },
    );

    // --- 2. Walking Mob Controller on Bottom Bar ---
    let walking_mob_timer = slint::Timer::default();
    let win_weak_mob = main_window.as_weak();
    let state_mob = state.clone();

    let mut walk_status = MobWalkStatus::Idle {
        next_walk_at: Instant::now() + Duration::from_millis(500),
    };
    let mut walk_counter = 0usize;

    walking_mob_timer.start(
        slint::TimerMode::Repeated,
        Duration::from_millis(50),
        move || {
            if let Some(win) = win_weak_mob.upgrade() {
                let is_launching = win.get_is_launching();
                let enable_walking = win.get_enable_walking_mobs();

                if state_mob.mobs.is_empty() {
                    return;
                }

                if is_launching && enable_walking {
                    match &mut walk_status {
                        MobWalkStatus::Idle { next_walk_at } => {
                            if Instant::now() >= *next_walk_at {
                                let mob_idx = walk_counter % state_mob.mobs.len();
                                // Alternate direction cleanly on every walk: 0 = right, 1 = left, 2 = right...
                                let moving_right = (walk_counter % 2) == 0;
                                walk_counter += 1;

                                let mob = &state_mob.mobs[mob_idx];
                                let duration = Duration::from_millis(7000);

                                // The walking mob layer lives inside the Right Content Area (clip: true).
                                // x: 0 is the right edge of the 240px sidebar.
                                // Negative x places the mob behind the sidebar (clipped).
                                let (behind_sidebar_x, right_edge_x) = compute_mob_boundaries(
                                    win.window().size().width as f32,
                                    win.window().scale_factor(),
                                    mob.width as f32,
                                );

                                let start_x = if moving_right { behind_sidebar_x } else { right_edge_x };

                                // Moving right: mob must face RIGHT (coming from the left)
                                // Moving left: mob must face LEFT (walking towards the sidebar)
                                let frames = if moving_right {
                                    &mob.frames_facing_right
                                } else {
                                    &mob.frames_facing_left
                                };

                                // Set initial position and properties
                                win.set_walking_mob_width(mob.width as f32);
                                win.set_walking_mob_height(mob.height as f32);
                                win.set_walking_mob_is_flying(mob.is_flying);
                                win.set_walking_mob_x(start_x);
                                if !frames.is_empty() {
                                    win.set_walking_mob_frame(frames[0].clone());
                                }
                                win.set_walking_mob_visible(true);

                                let now = Instant::now();
                                walk_status = MobWalkStatus::Walking {
                                    mob_idx,
                                    moving_right,
                                    started_at: now,
                                    last_tick_at: now,
                                    current_x: start_x,
                                    duration,
                                };
                            }
                        }
                        MobWalkStatus::Walking {
                            mob_idx,
                            moving_right,
                            started_at,
                            last_tick_at,
                            current_x,
                            duration,
                        } => {
                            let now = Instant::now();
                            let dt = now.duration_since(*last_tick_at).as_secs_f32().max(0.001);
                            *last_tick_at = now;
                            let elapsed = started_at.elapsed();

                            if elapsed >= *duration {
                                // Walk complete; hide and pause for 3.5 seconds
                                win.set_walking_mob_visible(false);
                                walk_status = MobWalkStatus::Idle {
                                    next_walk_at: Instant::now() + Duration::from_millis(3500),
                                };
                            } else {
                                let mob = &state_mob.mobs[*mob_idx];

                                // Dynamically recalculate right_edge_x and boundaries every single tick
                                // to smoothly compensate for real-time window resizing.
                                let (behind_sidebar_x, right_edge_x) = compute_mob_boundaries(
                                    win.window().size().width as f32,
                                    win.window().scale_factor(),
                                    mob.width as f32,
                                );

                                let target_x = if *moving_right { right_edge_x } else { behind_sidebar_x };
                                let rem_secs = (duration.as_secs_f32() - elapsed.as_secs_f32()).max(0.0);

                                if (*moving_right && *current_x >= target_x) || (!*moving_right && *current_x <= target_x) {
                                    *current_x = target_x;
                                } else {
                                    *current_x = compute_walking_mob_step(*current_x, target_x, dt, (rem_secs + dt).max(0.001));
                                }
                                win.set_walking_mob_x(*current_x);

                                // Update walking animation frame
                                let frames = if *moving_right {
                                    &mob.frames_facing_right
                                } else {
                                    &mob.frames_facing_left
                                };

                                if !frames.is_empty() {
                                    let frame_idx = (elapsed.as_millis() / mob.frame_delay.as_millis().max(1)) as usize % frames.len();
                                    win.set_walking_mob_frame(frames[frame_idx].clone());
                                }
                            }
                        }
                    }
                } else {
                    // Not launching or walking mobs disabled; ensure walking mob is hidden immediately
                    if win.get_walking_mob_visible() {
                        win.set_walking_mob_visible(false);
                    }
                    walk_status = MobWalkStatus::Idle {
                        next_walk_at: Instant::now() + Duration::from_millis(800),
                    };
                }
            }
        },
    );

    AnimationControllers {
        _spinner_timer: spinner_timer,
        _walking_mob_timer: walking_mob_timer,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compute_mob_boundaries_scaling() {
        let (behind, right_edge) = compute_mob_boundaries(1040.0, 1.0, 34.0);
        assert_eq!(behind, -40.0);
        // right_pane_w = 1040 - 240 = 800. right_edge_x = 800 - 90 = 710.
        assert_eq!(right_edge, 710.0);

        // Window resize wider to 1440.0
        let (_, right_edge_wide) = compute_mob_boundaries(1440.0, 1.0, 34.0);
        assert_eq!(right_edge_wide, 1110.0);

        // Clamped minimum width 800.0
        let (_, right_edge_min) = compute_mob_boundaries(600.0, 1.0, 34.0);
        assert_eq!(right_edge_min, 470.0);
    }

    #[test]
    fn test_compute_walking_mob_step_smooth_resize_compensation() {
        // 1. Moving right: start at -40, target 710, dt = 0.05, rem = 7.0
        let x0 = -40.0;
        let x1 = compute_walking_mob_step(x0, 710.0, 0.05, 7.0);
        assert!(x1 > x0, "Mob must advance right");

        // 2. Window resizes mid-walk at halfway (rem = 3.5s) from 710 to 1110
        let current_pos = 335.0; // halfway
        let step_wide = compute_walking_mob_step(current_pos, 1110.0, 0.05, 3.5);
        // In 50ms over 3.5s, step should be ~1/70th of (1110 - 335 = 775) -> ~11.07px
        assert!(step_wide > current_pos);
        assert!((step_wide - current_pos) < 20.0, "Must smoothly step without leap/teleport");

        // 3. Moving left: start at 710, target -40 (behind sidebar)
        // If window resizes mid-walk, target behind_sidebar_x does NOT change
        let current_pos_left = 300.0;
        let step_left = compute_walking_mob_step(current_pos_left, -40.0, 0.05, 3.5);
        assert!(step_left < current_pos_left, "Mob must advance left towards behind_sidebar");
        assert!((current_pos_left - step_left) < 10.0, "Must not jump when moving left");

        // 4. Clean completion at boundary
        let final_step = compute_walking_mob_step(705.0, 710.0, 0.05, 0.04);
        assert_eq!(final_step, 710.0, "Must land exactly on target endpoint");
    }

    #[test]
    fn test_compute_walking_mob_step_uniform_trajectory_and_exact_arrival() {
        let total_duration = 7.0f32;
        let dt = 0.05f32;
        let total_ticks = (total_duration / dt).round() as usize; // 140 ticks
        let target_x = 700.0f32;
        let mut current_x = 0.0f32;

        for tick in 1..=total_ticks {
            let elapsed = tick as f32 * dt;
            let rem_secs = (total_duration - elapsed).max(0.0);
            current_x = compute_walking_mob_step(current_x, target_x, dt, rem_secs + dt);

            // At halfway (tick 70 / 3.5s), current_x should be exactly 350.0 +/- 0.01
            if tick == 70 {
                assert!(
                    (current_x - 350.0).abs() < 0.05,
                    "Must be halfway at halfway time, got {}",
                    current_x
                );
            }
        }

        assert_eq!(
            current_x, 700.0,
            "Must land exactly on target endpoint at final tick"
        );
    }

    #[test]
    fn test_compute_walking_mob_step_shrink_window_compensation() {
        // Window was wide (e.g. 1440, right_edge_x = 1110), mob walked right to 800.0.
        // User abruptly shrinks window down to 800 (right_edge_x = 470).
        // Target is now 470.0, which is behind the mob's current position 800.0.
        let current_pos = 800.0;
        let shrunk_target = 470.0;
        let next = compute_walking_mob_step(current_pos, shrunk_target, 0.05, 3.5);
        // Step advances towards 470.0 without overshooting past 470.0
        assert!(next < current_pos);
        assert!(next >= shrunk_target);

        // Near completion step
        let final_step = compute_walking_mob_step(current_pos, shrunk_target, 0.05, 0.04);
        assert_eq!(final_step, shrunk_target);
    }

    #[test]
    fn test_load_copper_golem_gif() {
        let p = Path::new("../../assets/loading/Copper_golem_take_item_fail_JE1_BE1.gif");
        let fallback_p = Path::new("assets/loading/Copper_golem_take_item_fail_JE1_BE1.gif");
        let actual_p = if p.exists() { p } else { fallback_p };

        if actual_p.exists() {
            let anim = load_cropped_gif(actual_p, 72, false, "copper_golem");
            assert!(anim.is_some(), "Copper golem GIF should decode successfully");
            let anim = anim.unwrap();
            assert_eq!(anim.height, 72);
            assert!(anim.width > 0);
            assert_eq!(anim.frames_facing_left.len(), 60, "Copper golem should have 60 frames");
            assert_eq!(anim.frames_facing_right.len(), 60);
        }
    }

    #[test]
    fn test_load_walking_mob_bee() {
        let p = Path::new("../../assets/walking/Bee_JE1.gif");
        let fallback_p = Path::new("assets/walking/Bee_JE1.gif");
        let actual_p = if p.exists() { p } else { fallback_p };

        if actual_p.exists() {
            let anim = load_cropped_gif(actual_p, 34, true, "bee");
            assert!(anim.is_some(), "Bee GIF should decode successfully");
            let anim = anim.unwrap();
            assert_eq!(anim.height, 34);
            assert!(anim.is_flying);
            assert_eq!(anim.frames_facing_left.len(), 84);
            assert_eq!(anim.frames_facing_right.len(), 84);
        }
    }

    #[test]
    fn test_load_all_walking_mobs() {
        let walking_dir = if Path::new("../../assets/walking").exists() {
            Path::new("../../assets/walking")
        } else {
            Path::new("assets/walking")
        };

        if !walking_dir.exists() {
            return;
        }

        let test_cases = [
            ("Allay_Fly.gif", 36, true, "allay"),
            ("Baby_white_rabbit_move.gif", 34, false, "white_rabbit"),
            ("Bee_JE1.gif", 34, true, "bee"),
            ("Baby_white_splotched_rabbit_move.gif", 34, false, "splotched_rabbit"),
        ];

        for (filename, target_h, is_flying, name) in test_cases {
            let p = walking_dir.join(filename);
            let anim = load_cropped_gif(&p, target_h, is_flying, name);
            assert!(anim.is_some(), "Mob {} should load successfully", name);
            let a = anim.unwrap();
            assert_eq!(a.height, target_h);
            assert!(a.width > 0);
            assert!(!a.frames_facing_left.is_empty());
            assert_eq!(a.frames_facing_left.len(), a.frames_facing_right.len());
        }
    }
}
