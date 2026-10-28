# Project: New-launcher Slint UI Port

## Architecture
- **Process Hierarchy**: Multi-process model. Slint Rust UI frontend (`src/frontend/`) runs as the primary desktop application; headless Python backend worker (`src/backend/agent.py` backed by `src/backend/nlc/` core subsystems) runs as a subprocess.
- **IPC Protocol**: Bidirectional asynchronous line-delimited UTF-8 JSON-RPC over `stdin`/`stdout`. Rust `AgentClient` routes request/response pairs by `id` and broadcasts unsolicited push events (`launch_state_changed`, `config_changed`, `download_progress`) via Tokio broadcast channels to Slint's thread-safe event loop.
- **Design System & Styling**: Strict pixel aesthetic matching authentic Tkinter captures:
  - `border-radius: 0px` globally on all cards, buttons, checkboxes, switches, and inputs.
  - OFL `Minecraft.otf` & `Minecraft-Bold.otf` typography.
  - Pixel asset binding from `icons/*.png` (no emoji Unicode or missing glyph boxes).
  - Fixed docking metrics: 240px Sidebar, 36px custom Titlebar.
  - 80px `BottomBar` docked strictly and exclusively to the `Play` view; all other 19 views expand to full window height.
- **Snapshot Testing**: Native Slint `window.take_snapshot()` automated CLI (`--snapshot-tab <tab> <path>` and `--snapshot-all <out_dir>`) for headless deterministic visual verification.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | IPC Stdio Transport & Event Router | Bidirectional line-delimited JSON-RPC client with Tokio broadcast channel for unsolicited async events | M1 | ORIGINAL_REQUEST §R3, Survey 3 |
| 2 | IPC Game Launch Lifecycle | `launch_game` action, version resolution, Java discovery, authlib-injector, and `launch_state_changed` push events | M1 | ORIGINAL_REQUEST §R3, Survey 3 |
| 3 | IPC Configuration Persistence | `config_get` and `config_set` RPC syncing bidirectionally with `ConfigManager` / `launcher_config.json` | M1 | ORIGINAL_REQUEST §R3, Survey 3 |
| 4 | IPC Account Auth & Management | `accounts_list`, `accounts_select`, Microsoft OAuth device code flow, and offline session creation | M1 | ORIGINAL_REQUEST §R3, Survey 3 |
| 5 | IPC Mod & Modrinth Queries | `mods_list_installed`, `mods_toggle_enabled`, `modrinth_search` routed to backend worker | M1 | ORIGINAL_REQUEST §R3, Survey 3 |
| 6 | IPC Skin & Cape Management | `skin_get_current`, `skin_set_custom`, `capes_list`, and `capes_select` hooks | M1 | ORIGINAL_REQUEST §R3, Survey 3 |
| 7 | Play Hero View | 1:1 parity with `01_play.png`, banner wallpaper, 80px Play-exclusive bottom bar, instance selector, Play button | M2 | ORIGINAL_REQUEST §R1, Survey 1 |
| 8 | Account Quick-Drawer Overlay | 1:1 parity with `01b_play_account_drawer.png`, popover drawer from user avatar, account switcher, add account button | M2 | ORIGINAL_REQUEST §R1, Survey 1 |
| 9 | Installations View & Management | 1:1 parity with `02_installations.png`, search, filter checkboxes (Releases, Snapshots, Modded), "New installation" button, cards with Play, folder, options | M2 | ORIGINAL_REQUEST §R1, Survey 1 |
| 10 | Pixel Icon & Typography Hardening | Purge all Unicode emojis and missing glyph boxes (`▯`); bind pixel PNGs from `icons/*.png` or pure Slint pixel shapes; strict 0px border-radius | M2 | ORIGINAL_REQUEST §R2, Survey 1 |
| 11 | Modpacks Overview View | 1:1 parity with `03_modpacks_overview.png`, modpack card, banner, description, and "Show Mods" button | M3 | ORIGINAL_REQUEST §R1, Survey 1 |
| 12 | Modpacks Installed Mod Grid | 1:1 parity with `media_1791798458082_bfce3214.png`, 9-mod grid, enable/disable toggle, mod count badge, back navigation | M3 | ORIGINAL_REQUEST §R1, Survey 1 |
| 13 | Addons & Agent View | 1:1 parity with `04_addons.png`, Playtime Tracker, GitHub Skin Sync, Streamer Mode, Server Quick Join cards with sharp toggles | M3 | ORIGINAL_REQUEST §R1, Survey 1 |
| 14 | Locker: Skins View | 1:1 parity with `05a_locker_skins.png`, wardrobe split layout, 2D/3D skin preview, custom upload, recent skins list | M3 | ORIGINAL_REQUEST §R1, Survey 1 |
| 15 | Locker: Capes View | 1:1 parity with `05b_locker_capes.png`, official Mojang & Ely.by capes grid, equip action, preview viewport | M3 | ORIGINAL_REQUEST §R1, Survey 1 |
| 16 | Locker: Wallpapers View | 1:1 parity with `05c_locker_wallpapers.png`, background wallpaper gallery, thumbnail picker, active selection | M3 | ORIGINAL_REQUEST §R1, Survey 1 |
| 17 | Modrinth: Mods View | 1:1 parity with `06a_modrinth_mods.png`, live search input, loader filter dropdown, version pills, install cards | M4 | ORIGINAL_REQUEST §R1, Survey 1 |
| 18 | Modrinth: Resource Packs View | 1:1 parity with `06b_modrinth_resourcepacks.png`, category tabs, resolution filter, install cards | M4 | ORIGINAL_REQUEST §R1, Survey 1 |
| 19 | Modrinth: Modpacks View | 1:1 parity with `06c_modrinth_modpacks.png`, modpack search, categories, install cards | M4 | ORIGINAL_REQUEST §R1, Survey 1 |
| 20 | Modrinth: Shaders View | 1:1 parity with `06d_modrinth_shaders.png`, shaderpack browser, install cards | M4 | ORIGINAL_REQUEST §R1, Survey 1 |
| 21 | Settings: General | 1:1 parity with `07_1_general.png`, Launcher Lifecycle, Setup & Wizard, telemetry | M4 | ORIGINAL_REQUEST §R1, Survey 1 |
| 22 | Settings: Appearance | 1:1 parity with `07_2_appearance.png`, color themes, font scale, UI glow, animation toggles | M4 | ORIGINAL_REQUEST §R1, Survey 1 |
| 23 | Settings: Modpacks & Instances | 1:1 parity with `07_3_modpacks_instances.png`, default modpack loader, update checks, memory isolation | M4 | ORIGINAL_REQUEST §R1, Survey 1 |
| 24 | Settings: Java & Memory | 1:1 parity with `07_4_java_memory.png`, Java runtime selector, min/max RAM sliders, JVM flags | M4 | ORIGINAL_REQUEST §R1, Survey 1 |
| 25 | Settings: Downloads | 1:1 parity with `07_5_downloads.png`, concurrent threads slider, mirror CDN selector, hash validation | M4 | ORIGINAL_REQUEST §R1, Survey 1 |
| 26 | Settings: Integrations | 1:1 parity with `07_6_integrations.png`, Discord Rich Presence, CurseForge API key, GitHub token | M4 | ORIGINAL_REQUEST §R1, Survey 1 |
| 27 | Settings: Logs & Diagnostics | 1:1 parity with `07_7_logs_diagnostics.png`, console log viewer, export crash report, copy debug info | M4 | ORIGINAL_REQUEST §R1, Survey 1 |
| 28 | Settings: About & Reset | 1:1 parity with `07_8_about_reset.png`, version 3.0.6 badge, license, factory reset, check updates | M4 | ORIGINAL_REQUEST §R1, Survey 1 |
| 29 | E2E Test Suite Execution & 100% Pass | Phase 1 of Final Milestone: run and pass all tests in E2E Test Suite (Tiers 1-4) | M5 | ORIGINAL_REQUEST §Functional Verification |
| 30 | Slint Automated 20-View Snapshot Suite | Batch snapshot testing (`--snapshot-all`) verifying pixel alignment across all 20 views | M5 | ORIGINAL_REQUEST §Visual Parity, Survey 2 |
| 31 | Adversarial Coverage Hardening | Phase 2 of Final Milestone: Tier 5 white-box challenger test generation and hardening | M5 | Project Pattern Phase 2 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Backend IPC Protocol & Event Infrastructure | Features 1-6: `agent.py` RPC action routing, Rust `ipc.rs` broadcast channel, async event streaming, config sync | none | PLANNED |
| M2 | Main Navigation, Play Hero & Account Management | Features 7-10: `PlayScreen`, Account Drawer, `InstallationsScreen`, pixel icon hardening, 0px radius | M1 | PLANNED |
| M3 | Modpacks, Mod Grid & Discover Section | Features 11-16: Modpacks overview & 9-mod grid, `AddonsScreen`, Locker Skins/Capes/Wallpapers | M1 | PLANNED |
| M4 | Modrinth Network & 8-Category Settings Drill-Down | Features 17-28: `ModrinthScreen` (Mods, Resource Packs, Modpacks, Shaders) and `SettingsScreen` (all 8 categories) | M1 | PLANNED |
| M5 | Final Milestone: E2E Test Pass & Adversarial Hardening | Features 29-31: Pass 100% E2E tests, 20-view snapshot suite, Tier 5 adversarial hardening, zero compiler warnings | M2, M3, M4, TEST_READY | PLANNED |

## Interface Contracts
### Rust UI ↔ Python Backend IPC (`agent.py`)
- Transport: UTF-8 line-delimited JSON over `stdin` (requests) and `stdout` (responses / events).
- Request Format: `{"id": "<uuid-or-number>", "action": "<method_name>", "payload": { ... }}`
- Response Format: `{"id": "<uuid-or-number>", "result": { ... }, "error": null}`
- Push Event Format: `{"event": "<event_name>", "payload": { ... }}`
- Actions:
  - `launch_game`: payload `{"profile": str, "instance_id": str}` -> result `{"status": "launching", "pid": int}`
  - `accounts_list`: payload `{}` -> result `[{"id": str, "username": str, "account_type": "microsoft"|"offline", "active": bool}]`
  - `accounts_select`: payload `{"id": str}` -> result `{"active": str}`
  - `config_get`: payload `{}` -> result `{ ... complete launcher config ... }`
  - `config_set`: payload `{"updates": { ... }}` -> result `{"success": true}`
  - `mods_list_installed`: payload `{"instance_id": str}` -> result `[{"name": str, "file": str, "enabled": bool, "version": str}]`
  - `modrinth_search`: payload `{"query": str, "project_type": str, "loader": str, "version": str}` -> result `[ ... ]`
  - `skin_get_current`: payload `{}` -> result `{"skin_path": str, "cape_path": str}`
- Events:
  - `launch_state_changed`: payload `{"state": "verifying"|"downloading"|"injecting"|"running"|"stopped", "progress": float, "message": str}`
  - `config_changed`: payload `{"key": str, "value": any}`

## Code Layout
- `src/frontend/`: Rust Slint application root.
  - `Cargo.toml`: Package dependencies (`slint`, `tokio`, `serde`, `image`).
  - `src/main.rs`: Entry point, window initialization, snapshot CLI flags (`--snapshot-tab`, `--snapshot-all`), Slint callback wiring.
  - `src/ipc.rs`: Async JSON-RPC client, child process management, response future resolution, push event broadcast channel.
  - `ui/main.slint`: Root window layout, sidebar navigation, Play-exclusive 80px bottom bar docking, screen routing.
  - `ui/theme.slint`: Global tokens (`COLORS`, metrics, 0px border-radii).
  - `ui/components.slint`: Reusable pixel-art widgets (Button, Card, Checkbox, Toggle, SearchInput, Icon, TabPill).
  - `ui/screens/play.slint`: Hero play screen and account drawer overlay.
  - `ui/screens/installations.slint`: Installations list, search, filter checkboxes, flat cards.
  - `ui/screens/modpacks.slint`: Modpack overview and installed mod grid.
  - `ui/screens/addons.slint`: Addons & agent cards with pixel switches.
  - `ui/screens/locker.slint`: Skins, Capes, and Wallpapers wardrobe tabs.
  - `ui/screens/modrinth.slint`: Modrinth network drill-down (Mods, Resource Packs, Modpacks, Shaders).
  - `ui/screens/settings.slint`: All 8 category views and navigation list.
- `src/backend/`: Authentic launcher backend core modules and IPC worker.
  - `agent.py`: Headless Python backend worker handling JSON-RPC requests via stdio and delegating to `nlc/`.
  - `agent.spec`: PyInstaller build specification for background agent daemon.
  - `nlc/`: Authentic launcher backend core modules (launch, config, auth, skins, modpacks, cdc).
- `tests/`: Categorized test suites (unit, ui, integration, e2e).
