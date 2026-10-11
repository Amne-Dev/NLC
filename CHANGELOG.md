# Changelog

All notable changes to this project will be documented in this file.

## [3.0.6] - 2026-10-11

### Added

- **Dedicated Screenshots Gallery**: Extracted screenshot browsing out of the Addons tab into a dedicated primary screen (`Screenshots`) positioned in the sidebar right above Notifications. Features non-blocking asynchronous thumbnail generation, persistent two-tier disk + memory LRU caching, high-resolution modal lightbox viewer, and real-time search filtering.

### Changed

- **Installed Mods List Scrolling Performance**: Optimized modpack installed mods view by decoupling geometry and scrollregion re-calculations, preventing layout thrashing and event-loop queue starvation during rapid mouse-wheel scrolling while retaining 100% of badges, icons, mod toggles, and remove actions.

### Fixed

- **Offline Skin Injection & Stale Cache Invalidation**: Fixed singleplayer and custom-skin-plugin servers showing outdated skins by adding dynamic modification hash query tags (`/textures/skin.png?v=<hash>`) to skin URLs and injecting `no-cache` headers into Yggdrasil session profile endpoints, forcing client cache invalidation on skin changes.

### Added

- **FastCDC Differential Updates**: Introduced content-defined chunking (FastCDC with Gear rolling hashing) for Windows executable updates over GitHub Releases. The launcher downloads only missing byte ranges via HTTP `Range` requests (~5–15 MB) instead of full binaries (~95 MB), regardless of internal offset shifts.
- **Standalone Binary Replacement**: Enhanced `NLCUpdater.exe` with `--replace-binary` for atomic staging swaps, backup preservation, and automated application relaunch.
- **Ed25519 Index Verification**: Cryptographic signing and verification for CDC chunk index manifests (`NewLauncher.exe.cdc.json`).

### Fixed

- **Notification Center Update Persistence**: Fixed update cards auto-dismissing after 10 seconds; update notifications now remain pinned in the notification drawer until explicitly acted upon or dismissed.
- **Toast Manager Parameter Compatibility**: Fixed unhandled `TypeError` exceptions across UI modules by allowing `level` as an alias for `kind` in `ToastManager.show()`.

## [3.0.4] - 2026-10-11

### Fixed

- **Offline Profile Names**: Preserved named offline profiles when changing or equipping skins, while repairing legacy profiles that are missing a name.

## [3.0.3] - 2026-10-11

### Added

- **Incremental Windows Updates**: Added verified patch packages that update the launcher executable, background agent, and bundled resources without replacing launcher configuration or Minecraft data.

### Fixed

- **Installation Recovery**: Normalized legacy installation entries, restored stable installation IDs, and repaired active-installation selection after configuration migrations.

## [3.0.2] - 2026-10-10

### Fixed

- **Offline Account Names**: Fixed offline account names reverting unexpectedly during skin-related updates.
- **Update Notifications**: Fixed the notification-center update action and improved update notification timing.

## [3.0.1] - 2026-10-09

### Fixed

- **Windows Startup Error**: Fixed addon timestamp formatting using the `datetime` module correctly, preventing startup failures when rendering screenshots.
- **Windows Alt-Tab Input Lockup**: Restored valid modal focus and cleared orphaned input grabs when the launcher regains focus.

## [3.0] - 2026-10-09

### Added

- **Neo UI & Dark Slate Theme**: Full client redesign with Dark Slate color scheme (`#1E2025`, `#181A1E`, `#2ECC71`), Minecraft pixel typography, and modern responsive cards.
- **Action Toasts & Fluid Feedback**: Interactive floating toasts for modpack downloads, instance creation, and system operations.
- **Two-Tier Asset Caching**: Disk and memory caching for wallpapers, skins, and modpack thumbnails for lag-free scrolling and navigation.
- **Locker & 3D Character Studio**: 3D skin preview stage, dynamic Steve (4px) vs Alex (3px) geometry toggle, saved wardrobe presets, and offline skin injection.
- **Modrinth Modpack Discovery & Mod Inspector**: 1-click modpack installs, auto installation linking, and granular mod ON/OFF toggle switches.

## [2.8] - 2026-08-21

### Added

- **CurseForge Modpack Import**: Import local CurseForge exports directly from the Modpacks page. Overrides are imported safely, and an optional CurseForge API key can download the mod files listed in the manifest.
- **Loading Skeletons**: Added lightweight placeholder loading states throughout long-running launcher views, so content feels responsive while it is being fetched or prepared.

### Changed

- **Installed Mods Browser**: Reworked the **Show Mods** popup to render large mod lists in small batches. Grid/List switching, searching, resizing, and scrolling stay responsive even with very large modpacks.
- **Modpack Launch Preparation**: Linked modpacks are now synchronized automatically immediately before launch. The Play button shows the update step, then starts Minecraft with the pack's current mods.
- **Scrolling**: Improved smooth mouse-wheel behavior and scroll-region updates across launcher pages, including the Addons and installed-mods views.
- **Modrinth UI**: Removed the redundant result-count and status-feedback elements from the Modrinth browsing page for a cleaner results view.

### Fixed

- **Stale Modpack Mods at Launch**: Removing all mods from a linked pack no longer causes the launcher to fall back to global mods. The temporary launch-time mods folder is cleaned up and the original folder is restored after the game closes.
- **Large Modpack Freezes**: Opening the installed-mods popup no longer blocks the launcher while every mod card is created.
- **Scroll Binding Regression**: Dynamic Addons content retains working mouse-wheel scrolling after it refreshes.

## [2.7] - 2026-04-04

### Added

- **Drop-In Third-Party Addons**: Added support for user-made addon folders that can be dropped into the launcher addons directory and rendered directly inside the native Addons tab.
- **Streamer Mode Addon**: Added a dedicated Streamer Mode addon for masking account names on launcher-controlled surfaces without changing the real account used for launch.

### Fixed

- **Addons Page Scrolling**: Rebound dynamic Addons content after rebuilds so mouse-wheel scrolling stays responsive after addon sections refresh or re-render.

## [2.6] - 2026-04-04

### Added

- **Addons Expansion**: Added 3 new built-in addons in the Addons tab:
  - **Playtime Tracker** for per-installation session time and launch counts.
  - **Server Quick Join** for saving favorite servers and launching directly into them.
  - **Screenshot Browser** for browsing, opening, and deleting recent screenshots from the Minecraft directory.
- **Modpack Version Picker**: Modrinth modpack installs now let users choose which `.mrpack` release to install instead of always taking the first available version.
- **Installation Advanced Options**: The installation create/edit dialog now supports a working custom **Java Executable** field and **Resolution** override, both saved per installation and applied at launch.
- **Windows Build Automation**: Added a GitHub Actions Windows build workflow that builds the launcher and installer automatically and can attach the installer plus SHA256 checksums to tagged releases.

### Changed

- **Addons Layout**: The Addons tab was reorganized so Playtime Tracker stays always visible, while the other addon sections are collapsible.
- **Addon UI Polish**: Collapsible addon cards now use top-right dropdown icons instead of inline text chevrons.
- **Skin Injection Branding**: The local authlib-injector metadata now identifies itself as **NLC Skin Handler** instead of **Local Skin Server**.
- **Versioning**: Updated launcher and installer version references to **2.6**.

### Fixed

- **Linux Scrolling**: Added Linux mouse wheel support (`Button-4` / `Button-5`) to the shared smooth-scrolling system so scrollable launcher views work properly on Linux.
- **Offline Skin Launches**: Fixed a launch failure where enabling local skin injection without an actual selected skin could prevent the game from starting.
- **No-Skin Placeholder**: Replaced the old fake fallback face with a white `?` placeholder when no skin is set.
- **Installed Mods Dialog**: Reworked the installed-mods browser to reduce jitter, stabilize scrolling/rendering, and support persistent Grid/List view selection.
- **Modpacks Page Rendering**: Fixed Linux cases where modpack action buttons did not visibly render until hover.
- **Sidebar Highlighting**: Fixed highlight behavior for the Modrinth `Mods` entry so the active state covers the full label area correctly.

## [1.8.2] - 2026-02-05

### Fixed

- **Encoding Error**: Fixed a `UnicodeDecodeError` (charmap codec) when the game logs special characters (e.g., from chat commands). The launcher now strictly uses UTF-8 buffering for game output.

## [1.8] - 2026-02-04

### Added
- **Background Agent**: Introduced a separate `agent.exe` process to handle heavy tasks (Modrinth searches, skin syncing) without freezing the main UI.
- **GitHub Skin Sync**: New feature in the "Addons" tab allowing users to link a GitHub repository to upload their skin and automatically download skins from friends/others in the repo.
- **Installer Improvements**: The installer now intelligently detects if it's a fresh install or an update, hiding the "Create Desktop Shortcut" checkbox for updates.
- **Data Persistence**: Ensured all local data (like cached skins) is saved to the `%AppData%\.nlc` directory, even when installed in restricted folders.

### Fixed
- **Scroll Glitch**: Fixed an issue where the Mods and Addons tabs would scroll infinitely upwards when using the mouse wheel.
- **Updater Launch**: Fixed a bug where the launcher wouldn't restart automatically after an update; switched to `os.startfile` for better UAC handling.
- **Installer Permissions**: The "Launch New Launcher" checkbox in the installer now starts the app with standard user privileges instead of inheriting Admin rights, preventing permission issues with configuration files.

## [1.7] - 2026-02-03

### Added
- **Addons System**: New "Addons" tab in the main sidebar for experimental features.
- **Persona 3 Reload Menu**: A new "Addons" option to replace the standard main menu with a stylized, animated interface inspired by Persona 3 Reload.
- **Download Manager**: A centralized system to handle all downloads with configurable concurrency limits (defaults to 1 Modpack, 3 Mods at a time) and speed throttling options in Settings.
- **Modrinth Toggle**: Mod support is now optional and disabled by default to improve startup performance. Users are prompted to enable it via the sidebar, with warnings about resource usage.
- **Downloads Settings**: A new section in the Settings tab to control download speeds and parallel limits.
- **Global Crash Handler**: A robust exception catcher that logs full tracebacks to file and displays a user-friendly error dialog instead of silently closing.
- **Lazy Loading**: The Modrinth/Mods tab is now initialized only upon first access, reducing initial memory footprint and load time.

### Changed
- **Logging System**: Completely rewrote logging to use Python's standard `logging` module. Logs are now saved to the configuration directory (`.nlc/logs` or local `logs/`) for better accessibility and diagnostics.
- **Modpack UX**: The "Create Modpack" button's "+" action now intelligently falls back to a local file picker if Modrinth integration is disabled.
- **Sidebar Navigation**: Reordered buttons for better flow; disabled features trigger helpful dialogs instead of being hidden.

### Fixed
- **Dialog Crashes**: Fixed a `TclError` caused by an invalid cursor property in the Modrinth enabling dialog.
- **Modpack Installation**: Refactored the "Create Matching Installation" logic to use the internal profile list directly, preventing sync issues with `launcher_config.json`.

## [1.6.4] - 2026-02-03

### Added
- **Wallpaper Injection**: Creating a seamless experience, the launcher now automatically injects your active wallpaper into the Minecraft Main Menu as a static background (replacing the spinning panorama).
- **Discord RPC Upgrade**: Rich Presence now displays the actual player's head (fetched via UUID) instead of the default "Steve" icon, falling back gracefully if offline.
- **Resource Pack Generation**: Implemented a dynamic `LauncherTheme.zip` generator that creates a valid resource pack for modern Minecraft versions (1.21+), handling icon resizing and format compatibility automatically.

### Fixed
- **Profile Persistence**: Fixed a critical bug where restarting the launcher would reset the active profile to "Steve". Valid Microsoft/Ely.by sessions now persist correctly.
- **Resource Reload Errors**: Solved "Resource Reload Failed" errors in Minecraft 1.21 by enforcing strict image dimensions (1024x1024) for panorama injection and removing invalid metadata ranges.
- **Config Race Condition**: Fixed a logic error where UI updates during profile switching would accidentally overwrite the saved configuration with default values.

## [1.6.2] - 2026-02-02

### Added
- **Progress Overlay**: A unified, persistent progress bar overlay now covers the bottom action bar during long tasks (Game Launch, Auto-Updates). This replaces inconsistent floating popups.
- **Custom Update Options**: The startup "Update Available" prompt now features 3 custom buttons: "Yes, Update", "I'll do it myself" (opens GitHub), and "No".

### Changed
- **Update Logic**: Updates are now downloaded to a persistent `config/updates` folder instead of the system Temp folder, resolving "Failed to load Python DLL" errors during self-updates.
- **Restart Mechanism**: Hardened the restart process for updates and factory resets to fully detach from the parent process, preventing file locking issues and `[WinError 32]`.

## [1.6.1] - 2026-02-02

### Fixed
- **Reset Crash**: Fixed a critical `[Errno 2]` crash when using "Reset to Defaults". The restart mechanism now uses absolute paths and detached processes to guarantee a clean reboot.
- **Wallpaper Duplication**: Fixed a visual bug where default wallpapers (like "Island") would appear twice in the list if selected.
- **Factory Reset**: "Reset to Defaults" now correctly wipes the `config/wallpapers` directory, removing all custom user assets.

## [1.6] - 2026-02-02

### Added
- **Onboarding**: Integrated full Microsoft Device Code Flow login into the initial setup wizard (replacing the "Coming Soon" placeholder).

### Fixed
- **Onboarding Loop**: Fixed a bug where the Onboarding Wizard would reappear on every launch due to configuration saving race conditions.
- **Auto-Update**: Fixed a `[WinError 32]` (Failed to remove temporary directory) warning during auto-updates by properly detaching the new process on Windows.

## [1.5] - 2026-02-02

### Added
- **Skin Model Sync**: Implemented automatic synchronization of the skin model (Classic/Slim) with Minecraft servers on startup to ensure local state matches the server API.
- **Background Checks**: Added `_startup_ms_skin_check` to validate and update the skin configuration silently in the background.
- **Verbose Logging**: Enhanced debug logging for the `upload_ms_skin` function to print full request/response headers and bodies for easier troubleshooting.

### Changed
- **UI Overhaul**: Replaced all native Windows message boxes (`messagebox`) with a unified **Custom Message Box** (`CustomMessagebox`) system.
    - Dialogs now use the launcher's dark theme/color palette (`#3A3B3C`).
    - Standardized error, warning, and confirmation popups.
- **Error Handling**: 
    - Improved "Sync Error" feedback with specific guidance for users (e.g., prompt to re-upload if skin path is missing).
    - Fixed issues where the UI would desync from the actual server state.

### Fixed
- **Startup Crash**: Resolved `NameError: name 'root' is not defined` and `AttributeError` for `_default_root` in the new custom popup class.
- **Indentation**: Fixed logic formatting in the main `MinecraftLauncher` initialization.

## [1.4] - 2026-02-02

### Added
- **Java Auto-Discovery**: Implemented a robust Java runtime resolution system.
    - If no system Java is found, the launcher searches the `runtime/` folder.
    - **Fallback Mechanism**: If no Java is found locally, the launcher will automatically download and install a Vanilla version to acquire the bundled Java Runtime, fixing `[WinError 2]` for Modloader installs.
- **Network Resilience**: Added graceful error handling for connection failures (e.g., DNS resolution errors, `getaddrinfo failed`). Users now see a friendly "Network Error" message instead of a raw traceback.
- **Build Configuration**:
    - Updated `alt.spec` to correctly bundle `wallpapers/` and `icons/` directories.
    - Added hidden imports for `pypresence` and `pystray`.

### Changed
- **Code Refactoring**: Major codebase restructuring. The monolithic `alt.py` has been split into modules:
    - `auth.py`: Authentication logic (Ely.by, etc.)
    - `handlers.py`: HTTP handlers for skins and Microsoft login.
    - `utils.py`: Shared utilities and file management.
    - `config.py`: Global constants and configuration.
- **Assets**: Moved default background images to the `wallpapers/` directory.
- **Installer**: Updated Inno Setup script (`installer.iss`) to version 1.4.

### Fixed
- Fixed a startup crash caused by an indentation error in `setup_tray`.
- Fixed `RPC` variable initialization errors.
- Fixed a crash during Fabric/Forge installation where the installer could not find a valid Java executable.
