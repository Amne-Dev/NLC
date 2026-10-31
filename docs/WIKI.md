# Ny-Luna Core (NLC) — Technical & Architectural Wiki

Welcome to the **Ny-Luna Core** technical wiki. This document serves as the canonical reference for players, modpack creators, addon authors, and core developers on the architecture, subsystems, security model, and operations of Ny-Luna Core (NLC).

---

## Table of Contents
1. [Overview, Architecture & Quick Start](#1-overview-architecture--quick-start)
   - [Architectural Goals](#architectural-goals)
   - [Player Quick Start: Zero to In-Game](#player-quick-start-zero-to-in-game)
   - [System Topology](#system-topology)
2. [Process Model, IPC Protocol & Lifecycle](#2-process-model-ipc-protocol--lifecycle)
   - [IPC Protocol Specification](#ipc-protocol-specification-gui---daemon-agent)
   - [IPC Action Catalog](#ipc-action-catalog)
   - [Supervision & Watchdog Lifecycle](#process-supervision--watchdog-lifecycle)
3. [Authentication Engines & Credential Vault](#3-authentication-engines--credential-vault)
   - [Microsoft / Mojang (OAuth 2.0)](#1-microsoft--mojang-authentication-oauth-20)
   - [Ely.by Account Service](#2-elyby-account-service)
   - [Offline (Local) Profiles & Multiplayer Realities](#3-offline-local-profiles--multiplayer-realities)
   - [Credential Vault](#4-credential-vault)
4. [Installations, Modloaders & JVM Architecture](#4-installations-modloaders--jvm-architecture)
   - [Supported Modloaders](#supported-loaders)
   - [Instance Isolation & Shared Reparse Points](#instance-isolation--directory-junctions)
   - [Java Runtime Matrix & RAM Sizing](#java-version-matrix-jvm-flags--ram-sizing)
5. [Skin System, Wardrobe & 3D Engine](#5-skin-system-wardrobe--3d-engine)
   - [How to Change Your Skin in the Locker](#how-to-set-your-skin-in-the-launcher)
   - [JVM Injection Model](#1-jvm-injection-model)
   - [Ephemeral Local Yggdrasil Proxy](#2-ephemeral-local-yggdrasil-proxy-localskinserver)
   - [Under the Hood: Software 3D Preview Engine](#3-software-3d-skin-preview-engine-engine-details)
6. [Modpacks, Mods & Content Delivery](#6-modpacks-mods--content-delivery)
   - [Modrinth & CurseForge Support](#modrinth-integration)
   - [Non-Destructive Mod Toggling](#non-destructive-mod-toggling)
7. [Addons Framework & Ecosystem](#7-addons-framework--ecosystem)
   - [Addon Manifest Format](#addonjson-manifest-format)
   - [Built-in Addons](#built-in-addons)
8. [FastCDC Differential Binary Updater](#8-fastcdc-differential-binary-updater)
   - [Lightning-Fast Delta Updates](#1-fastcdc-algorithm--gear-rolling-hash)
   - [Cryptographic Signature Verification](#2-ed25519-manifest-verification)
9. [Storage Layout, File Locations & Atomic I/O](#9-storage-layout-file-locations--atomic-io)
   - [Filesystem Directory Matrix](#standard-filesystem-paths)
   - [Atomic Persistence Protocol](#atomic-persistence-protocol)
10. [Command-Line Interface (CLI Reference)](#10-command-line-interface-cli-reference)
    - [Player & Automation Shortcuts](#player--automation-commands)
    - [Developer, Daemon & CI Testing Tools](#developer-daemon--ci-testing-tools)
11. [Diagnostics, Exit Codes & Troubleshooting](#11-diagnostics-exit-codes--troubleshooting)
    - [Minecraft Crash Exit Codes](#common-minecraft-exit-codes)
    - [Linux FUSE Requirements](#linux-fuse-library-requirements-appimage)
    - [Wayland & KDE Plasma Graphics](#wayland--kde-plasma-diagnostics)
    - [Uninstallation on Linux](#linux-uninstallation)
12. [Development, Build & Licensing](#12-development-build--licensing)
    - [Building from Source](#building-from-source)
    - [Packaging Releases](#packaging-for-release)
    - [License (BSD-3-Clause)](#license)

---

## 1. Overview, Architecture & Quick Start

**Ny-Luna Core (NLC)** is an open-source Minecraft Java Edition launcher for Windows and Linux. Starting with release v4.0.0, Ny-Luna transitioned from a monolithic architecture to an asynchronous, decoupled multi-process topology.

> [!TIP]
> **What this means for players:**
> The launcher interface is compiled in native Rust using Slint UI, while downloads, modpacks, and game processes run in a separate background engine. Even when you are downloading a 5 GB modpack or compiling shaders, the launcher window will never freeze, stutter, or lag. There is zero Electron, Chromium, or web-engine bloat, saving memory and battery life.

### Architectural Goals
* **Sub-Millisecond UI Responsiveness:** Presentation is completely decoupled from network operations, Java process launches, and disk hashing.
* **GPU-Accelerated Window Chrome:** Rendered natively via hardware OpenGL/Vulkan/software backends without memory overhead.
* **Deterministic Local-First Isolation:** Complete user privacy with no telemetry or remote aggregation. All profiles, modpacks, and credentials remain strictly on your local disk.
* **Zero Jar-Modding Skin Injection:** Transparent skin and cape support for offline and third-party profiles through non-invasive JVM agent injection.

### Player Quick Start: Zero to In-Game
Getting into the game takes just 4 steps:
1. **Launch Ny-Luna:** Run the AppImage (Linux) or executable (Windows).
2. **Set Up an Account:** Click your avatar in the upper-right corner or go to the **Accounts** screen:
   - **Microsoft Account:** Follow the one-click device code prompt in your web browser.
   - **Offline Account:** Pick any username (e.g. `Alex`) and start playing immediately.
3. **Select or Create an Installation:** On the **Play** screen, choose an existing version or click **Installations** &rarr; **New Installation** to pick any Minecraft release, snapshot, or loader (Fabric, Forge, NeoForge, Quilt).
4. **Hit Play:** The launcher will automatically fetch required game libraries, Java assets, and mods, and launch your game.

### System Topology
```
+-------------------------------------------------------------+
|                      User Display / Desktop                 |
+-------------------------------------------------------------+
                               |
                               v
            +------------------------------------+
            |      Frontend GUI (Rust / Slint)   |
            |     - GPU-Accelerated Chrome       |
            |     - Reactive Slint Models        |
            |     - Sub-millisecond Event Loop   |
            +------------------------------------+
                               |
                    Line-Buffered JSON IPC
                    (stdin/stdout anonymous pipe)
                               |
                               v
            +------------------------------------+
            |   Daemon Agent (Python 3.12+)      |
            |     - Minecraft Launch Process     |
            |     - Local Yggdrasil Skin Server  |
            |     - Microsoft OAuth2 & Ely.by    |
            |     - Modrinth / CurseForge APIs   |
            |     - FastCDC Delta Assembly       |
            |     - Discord Rich Presence        |
            +------------------------------------+
                               |
                               +-----------------------------+
                               |                             |
                               v                             v
                +----------------------------+  +----------------------------+
                | Minecraft Game Client JVM  |  | Elevated Patch Supervisor  |
                | - Authlib-Injector Agent   |  | (NLCUpdater.exe)           |
                | - Fabric / Forge / Vanilla |  | - Process Termination      |
                | - Isolated Game Directory  |  | - Atomic Binary Promotion  |
                +----------------------------+  +----------------------------+
```

---

## 2. Process Model, IPC Protocol & Lifecycle

The launcher coordinates three distinct process domains:

| Process Domain | Binary / Target | Technology | Privileges | Lifetime |
|---|---|---|---|---|
| **Frontend GUI** | `nlc-ui` / `NyLuna.exe` | Rust, Slint UI | Standard User | Active during user session |
| **Daemon Agent** | `agent.py` / `agent` / `agent.exe` | Python 3.12+ (Daemon) | Standard User | Spawns with GUI, terminates when GUI exits |
| **Patch Supervisor** | `NLCUpdater.exe` / `patch_runner.py` | C / Python Runner | Elevated (UAC `runas`) | Spawns detached only during updates |

### IPC Protocol Specification (GUI <-> Daemon Agent)
The frontend and backend communicate via anonymous pipes over standard input and standard output (`stdin`/`stdout`).

* **Encoding:** UTF-8, line-delimited JSON (`\n`).
* **Request Correlation:** The client issues a unique UUID for each request (`id`). The server responds with the matching `id`.
* **Asynchronous Events:** The backend emits unsolicited events (download progress, Discord status updates, game termination) using the `event` key.
* **Resilient Line Reader:** The frontend reader runs an infinite asynchronous event loop that logs warnings on malformed lines and continues reading without dropping the connection.

#### Request Format
```json
{
  "id": "c8f2a170-16bb-493e-a89c-5509cb7b7a21",
  "action": "search_mods",
  "payload": {
    "query": "iris",
    "loader": "fabric",
    "version": "1.21.1"
  }
}
```

#### Response Format
```json
{
  "id": "c8f2a170-16bb-493e-a89c-5509cb7b7a21",
  "result": {
    "status": "success",
    "data": [
      {
        "id": "YL57xq9U",
        "title": "Iris Shaders",
        "author": "Iris-Shaders",
        "downloads": 18500000
      }
    ]
  },
  "error": null
}
```

#### Event Streaming Envelope
```json
{
  "event": "download_progress",
  "payload": {
    "file": "client.jar",
    "current": 14200000,
    "total": 28400000,
    "percent": 50.0
  }
}
```

### IPC Action Catalog
| Action | Description | Key Payload Parameters |
|---|---|---|
| `launch_game` | Boots Minecraft with selected modloader and JVM flags | `instance_id`, `account`, `offline_name` |
| `accounts_list` | Lists all stored Microsoft, Ely.by, and offline accounts | `{}` |
| `accounts_select` | Sets active profile index or UUID | `id`, `index`, `username` |
| `accounts_auth_offline` | Creates or updates an offline profile | `username`, `skin_model` |
| `accounts_remove` | Deletes a stored account and purges tokens | `uuid`, `username`, `index` |
| `accounts_ms_start` | Requests Microsoft OAuth2 Device Code grant | `{}` |
| `accounts_ms_poll` | Polls Microsoft Identity token endpoint for completion | `device_code` |
| `config_get` | Fetches active launcher settings | `{}` |
| `config_set` | Updates launcher configuration attributes | `{ key: value, ... }` |
| `mods_list_installed` | Enumerates mods in an instance directory | `instance_id` |
| `mods_toggle_enabled` | Toggles mod `.jar` vs `.jar.disabled` state | `instance_id`, `filename`, `enabled` |
| `modrinth_search` | Queries Modrinth API for mods, packs, and shaders | `query`, `project_type`, `loader`, `version` |
| `skin_get_current` | Reads active player skin and cape file paths | `{}` |
| `skin_set_custom` | Assigns custom skin PNG file to profile | `path`, `skin_model` |
| `capes_list` | Fetches owned official and third-party capes | `{}` |
| `capes_select` | Equips or unequips a cape | `cape_id`, `active` |
| `get_discord_status` | Returns Discord Rich Presence connection state | `{}` |
| `ping` | Heartbeat check returning `pong` | `{}` |
| `agent_shutdown` | Gracefully closes connections and shuts down workers | `{}` |

### Process Supervision & Watchdog Lifecycle
> [!NOTE]
> **Crash Safety Guarantee:** If the launcher window ever closes unexpectedly, all background tasks and helper processes clean up automatically without leaving zombie processes draining your CPU or RAM.

1. **Stdin EOF Monitoring:** The primary lifecycle mechanism relies on stdin EOF. When the frontend process closes or terminates, the operating system closes the anonymous pipe. The agent's `sys.stdin.readline()` returns an empty string (`""`), breaking the main dispatch loop and triggering immediate clean shutdown.
2. **Orphan PID Check (Linux):** On Linux, a background watchdog thread checks `os.getppid() == 1`. If the parent process crashes abruptly without closing pipes, the watchdog detects reparenting to `init` (PID 1) and calls `os._exit(0)`.
3. **Avoidance of Thread-Bound Signals:** `PR_SET_PDEATHSIG` is deliberately avoided on Linux because Tokio worker threads are recycled and terminated dynamically; binding `PDEATHSIG` to worker threads would trigger premature child termination.
4. **Job Objects (Windows):** On Windows, the frontend assigns the agent process to a Windows Job Object configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.

---

## 3. Authentication Engines & Credential Vault

> [!IMPORTANT]
> **Player Security Guarantee:**
> Ny-Luna Core never asks for, handles, or stores your Microsoft password. Microsoft authentication occurs strictly in your official system web browser via OAuth 2.0 Device Flow. All tokens and session keys are encrypted locally on your computer with operating-system hardware encryption.

### 1. Microsoft / Mojang Authentication (OAuth 2.0)
1. **Device Code Request:** The launcher requests a device authorization grant from Microsoft Identity (`https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode`) with client ID `00000000402b5328`. The user enters the code in their browser.
2. **Xbox Live Authentication:** Exchanges the Microsoft OAuth token at `https://user.auth.xboxlive.com/user/authenticate` for an Xbox Live token.
3. **XSTS Authorization:** Contacts `https://xsts.auth.xboxlive.com/xsts/authorize` with RelyingParty `rp://api.minecraftservices.com/` to produce the XSTS token and user hash (`uhs`).
4. **Minecraft Services Login:** Sends the XSTS proof to `https://api.minecraftservices.com/authentication/login_with_xbox` to acquire the final Bearer token.
5. **Entitlement & Profile Fetch:** Verifies game ownership via `/entitlements/mcstore` and fetches player UUID, skin textures, and capes from `/minecraft/profile`.

### 2. Ely.by Account Service
[Ely.by](https://ely.by) is a popular independent authentication and skin service:
* Authenticates directly with Ely.by via `https://authserver.ely.by/auth/authenticate`.
* Uses `accessToken` and `selectedProfile.id`.
* Transparently adds Ely.by's authlib server to JVM launch flags:
  `-javaagent:authlib-injector.jar=https://authserver.ely.by/api/authlib-injector`.

### 3. Offline (Local) Profiles & Multiplayer Realities
Offline profiles allow anyone to play Minecraft without logging into Microsoft:
* **Deterministic UUID:** Calculates a consistent UUID in compliance with standard Minecraft server offline algorithms:
  ```python
  uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{player_name}")
  ```
* **Single-Player:** 100% functional offline with full save support.
* **LAN Multiplayer:** Works with friends on your local home Wi-Fi network without internet access.
* **Online Servers:** You can connect to private and community servers that have `online-mode=false` (cracked/offline servers). You cannot join official Mojang-authenticated servers like Hypixel.
* **Skin Visibility:** Custom offline skins stream via the internal Yggdrasil proxy. On LAN or offline servers, players using authlib-injector compatible launchers can see your skin.

> [!WARNING]
> **UUID & Player Inventory Notice:**
> Single-player world inventories, advancements, and tamed pets are tied to your player UUID. If you start a world with an Offline account and later switch to a Microsoft account with a different UUID, your old inventory will not transfer automatically unless you copy your player `.dat` file inside the world's `playerdata/` folder.

### 4. Credential Vault
All sensitive tokens (`access_token`, `refresh_token`, `xsts`) are stored in `launcher_config.json` inside encrypted blocks:
* **Windows:** Uses the Windows Data Protection API (DPAPI via `CryptProtectData`), binding encryption keys to the user's Windows login credentials.
* **Linux:** Uses AES-256-GCM authenticated encryption. The cryptographic key is derived via PBKDF2 from machine identity (`/etc/machine-id` or `/var/lib/dbus/machine-id`) combined with the current POSIX user ID and a dedicated salt.

---

## 4. Installations, Modloaders & JVM Architecture

Ny-Luna allows granular management of game installations with automated modloader bootstrap:

### Supported Loaders
* **Vanilla:** Automated fetch from Mojang's version manifest (`launchermeta.mojang.com`).
* **Fabric:** Automated library resolver via the Fabric Meta API (`meta.fabricmc.net`).
* **Forge:** Full Forge installer processor pipeline supporting both legacy (`1.7.10` / `1.12.2`) and modern (`1.20+`) packaging.
* **NeoForge:** Modern NeoForged maven resolver and installer.
* **Quilt:** Quilt Meta integration for Fabric-compatible modding.
* **BatMod / LabyMod / Lunar Client:** Dedicated client hooks and environment preparation.

### Instance Isolation & Directory Junctions
To prevent mod collisions, installations can be isolated in separate directories (`instances/<id>/`). To avoid duplicating heavy game assets across multiple instances, Ny-Luna creates filesystem reparse points:
* **Windows:** NTFS Directory Junctions via `_winapi.CreateJunction(target, link)`. This avoids requiring Administrator rights or Developer Mode.
* **Linux:** Standard POSIX symbolic links (`os.symlink`).
* **Shared Assets:** `resourcepacks`, `shaderpacks`, `saves`, and `assets` can be linked to a central storage root, saving dozens of gigabytes of disk space.

### Java Version Matrix, JVM Flags & RAM Sizing
| Minecraft Version | Required Java Runtime | Recommended GC |
|---|---|---|
| **1.7.10 - 1.16.5** | Java 8 (OpenJDK / Temurin) | ParallelGC or G1GC |
| **1.17 - 1.20.4** | Java 17 | Aiken Tuned G1GC |
| **1.20.5 - 1.21.x+** | Java 21+ | Aiken Tuned G1GC / ZGC |

> [!TIP]
> **Zero Manual Setup Required:**
> Ny-Luna automatically detects installed Java runtimes and applies pre-tuned Aiken G1GC arguments behind the scenes to eliminate Java stutter and garbage collection freeze spikes. You do not need to configure complex command-line arguments manually!

#### Recommended RAM Allocation Guide (Settings &rarr; Java & Memory)
* **Vanilla / Light Fabric (1.20+):** 3 GB – 4 GB RAM.
* **Standard Modpacks (50–150 mods):** 4 GB – 6 GB RAM.
* **Heavy Forge / Modpack (200+ mods, shaders):** 6 GB – 8 GB RAM.
* *Rule of Thumb:* Never allocate more than 50%–70% of your system's total physical RAM to Java to prevent operating system freezes.

---

## 5. Skin System, Wardrobe & 3D Engine

Ny-Luna Core provides a non-invasive skin injection system for offline and third-party players, eliminating the need to modify game JAR files.

### How to Set Your Skin in the Launcher
1. Open Ny-Luna and navigate to the **Locker / Wardrobe** tab on the left sidebar.
2. Select your character model type:
   - **Classic (Steve):** Standard 4-pixel arm width.
   - **Slim (Alex):** 3-pixel arm width.
3. Click **Upload Custom Skin** and select any standard `64x64` or legacy `64x32` PNG skin file.
4. Use your mouse to click and drag the 3D preview viewport to inspect your character in real-time with walk and cape flutter animations!

### 1. JVM Injection Model
During launch, the launcher injects `authlib-injector`:
```text
-javaagent:{minecraft_dir}/authlib-injector.jar=http://127.0.0.1:{port}
```

### 2. Ephemeral Local Yggdrasil Proxy (`LocalSkinServer`)
When an offline profile has a custom skin configured:
1. `LocalSkinServer` binds to `127.0.0.1` on an ephemeral free port (`port 0`).
2. **Handshake Verification:** `GET /` responds with HTTP `200` and the required header:
   ```text
   X-Authlib-Injector-API-Location: /
   ```
3. **Profile Lookup:** Intercepts `/api/profiles/minecraft` and `/sessionserver/session/minecraft/profile/{uuid}`.
4. **Texture Delivery:** Returns a signed-format JSON payload pointing to `http://127.0.0.1:{port}/textures/skin.png`. The game client requests the texture, and `LocalSkinServer` streams the PNG from disk.

### 3. Software 3D Skin Preview Engine (Engine Details)
The software 3D skin rasterizer is written in Pillow and NumPy without requiring heavy external 3D libraries:
* **Format Normalization:** Automatically converts legacy 64x32 skins to 64x64 format with second-layer alpha support.
* **Camera Transformations:** Applies 3D Euler rotation matrices: $R_{\text{cam}} = R_{\text{pitch}} \times R_{\text{yaw}}$.
* **Real-Time Animation:** Simulates limb pendulum swings ($\theta_{\text{leg}} = 26^\circ \sin(\omega)$) and cape flutter ($6^\circ + 6^\circ |\sin(\omega)|$).
* **Shading & Rasterization:** Normal vectors are evaluated for backface culling ($\vec{N}_{\text{cam}}[2] \ge 0$), shaded by an ambient sun vector ($\vec{L} = [0.3, 0.8, -0.5]$), and rasterized via affine polygon transformation (`Image.Transform.AFFINE`).

---

## 6. Modpacks, Mods & Content Delivery

Ny-Luna integrates directly with the **Modrinth API** and provides importer capabilities for **CurseForge** modpacks.

### Modrinth Integration
* **In-Launcher Browser:** Discover, filter, and install mods, resource packs, modpacks, and shaderpacks directly from the **Modrinth** tab without leaving the launcher.
* **Native `.mrpack` Support:** Extracts `modrinth.index.json`, downloads all dependencies with concurrent streams, and validates SHA-1 and SHA-512 hashes.
* **Overrides Extraction:** Extracts `overrides/` and `client-overrides/` safely, blocking path traversal vulnerabilities (Zip Slip).

### CurseForge Importer
* Unpacks CurseForge modpack ZIP archives.
* Parses `manifest.json`, resolving `projectID` and `fileID` records.
* Supports user-supplied CurseForge API keys for restricted assets.

### Non-Destructive Mod Toggling
Disabling a mod appends a `.disabled` extension (e.g. `sodium.jar.disabled`). This prevents loaders from mounting the JAR while preserving configuration files and download caches.

---

## 7. Addons Framework & Ecosystem

Ny-Luna supports standalone Python addons running inside the daemon worker:

### Directory & Manifest Structure
Addons reside in `<data_dir>/addons/<addon_id>/`:
```text
my_addon/
├── addon.json       # Metadata, actions, and UI hooks
└── main.py          # Action handler implementation
```

#### `addon.json` Manifest Format
```json
{
  "id": "server_backup",
  "name": "World Backup Helper",
  "version": "1.0.0",
  "author": "Community",
  "entrypoint": "main.py",
  "actions": [
    {
      "id": "backup_active_world",
      "name": "Backup Active World",
      "inputs": [{"name": "world_name", "type": "string"}]
    }
  ]
}
```

### Built-in Addons
* **Streamer Mode:** Masks usernames, tokens, UUIDs, and paths on-screen.
* **Server Monitor:** Performs live TCP pings against server IPs, displaying ping latency, MOTD, and player count.
* **Playtime Tracker:** Persists gameplay duration per installation.
* **Community Addons Registry:** Managed via `packaging/community_addons_repo/` with automated packaging scripts.

---

## 8. FastCDC Differential Binary Updater

Ny-Luna features differential binary updating powered by **FastCDC** (Content-Defined Chunking) and **Ed25519** cryptographic signatures:

> [!TIP]
> **Lightning-Fast Delta Updates:**
> When a new version of Ny-Luna Core is released, you don't need to re-download the entire 100+ MB launcher. FastCDC identifies the exact chunks that changed, typically downloading only 2–5 MB of delta patches. Every update is cryptographically signed to prevent tampering.

### 1. FastCDC Algorithm & Gear Rolling Hash
Instead of fixed-size chunks (which break upon single-byte insertions), FastCDC calculates dynamic chunk boundaries using a 256-entry 32-bit Gear lookup table (`GEAR_TABLE`):
* **Min Chunk Size:** 16 KB (prevents microscopic fragments).
* **Average Chunk Size:** 64 KB (optimal network throughput).
* **Max Chunk Size:** 256 KB (upper bound).
* **Boundary Condition:** `(fp & 0x0000FFFF) == 0`.

### 2. Ed25519 Manifest Verification
Before downloading any update, Ny-Luna retrieves the index (`newlauncher.exe.cdc.json`) and verifies its Ed25519 signature against the embedded public key using canonical zero-whitespace JSON serialization.

### 3. Range Coalescing & Assembly
1. **Local Scan:** Chunks present in the local executable are copied directly into `.part` at their target offsets (0 bytes transferred).
2. **Coalesced Requests:** Missing chunk gaps smaller than 32 KB are merged into contiguous HTTP `Range: bytes={start}-{end}` requests.
3. **Atomic Promotion:** The final file's SHA-256 hash is verified against the signed manifest before renaming over the live binary.

---

## 9. Storage Layout, File Locations & Atomic I/O

### Standard Filesystem Paths
| Content | Windows Path | Linux Path |
|---|---|---|
| **Launcher Data Root** | `%APPDATA%\.nlc` | `~/.nlc` |
| **Config File** | `%APPDATA%\.nlc\launcher_config.json` | `~/.nlc/launcher_config.json` |
| **Single-Instance Lock** | `%APPDATA%\.nlc\launcher.lock` | `@nlc-single-instance-lock` (Abstract Socket) |
| **Crash & Agent Logs** | `%APPDATA%\.nlc\logs\` | `~/.nlc/logs/` |
| **Default Game Dir** | `%APPDATA%\.minecraft` | `~/.minecraft` |
| **System Installation** | `%LOCALAPPDATA%\Programs\Ny-Luna` | `/opt/new-launcher` |
| **System Symlinks** | None | `/usr/local/bin/nlc`, `/usr/local/bin/newlauncher` |
| **Desktop Integrations** | Desktop Shortcut, Start Menu | `/usr/share/applications/nlc.desktop`, `hicolor` icons |

### Atomic Persistence Protocol
To prevent file corruption during sudden power failures or system crashes:
1. `ConfigManager` creates a temporary file `nlc_cfg_*.tmp` inside the target directory.
2. Writes formatted JSON and calls `os.fsync(f.fileno())` to guarantee physical disk write.
3. Creates a backup copy `launcher_config.json.bak`.
4. Atomically promotes the temporary file to `launcher_config.json` via `os.replace()`.

---

## 10. Command-Line Interface (CLI Reference)

Ny-Luna Core provides a flexible command-line interface for desktop shortcuts, automation, and administration.

### Player & Automation Commands
These commands are intended for players, scripting, or desktop launcher shortcuts:

```bash
# Launch the default graphical interface
nlc

# Print current version
nlc --version

# Print command-line help
nlc --help

# Launch directly into an installation (bypasses main menu)
nlc --instance "Fabric 1.21" --account "MyUsername"

# Launch in offline mode immediately
nlc --offline-user "Alex"

# Store/load game data from a secondary drive or custom directory
nlc --dir "/mnt/games/minecraft"

# Launch with verbose debug logging in terminal
nlc --debug

# Interactive uninstaller on Linux (asks confirmation)
nlc --uninstall
```

### Developer, Daemon & CI Testing Tools
These flags are specialized for developers, headless servers, and automated pipelines:

| Flag | Category | Description |
|---|---|---|
| `--snapshot-tab <tab> <path>` | CI Testing | Renders a headless visual snapshot of a UI tab to a PNG file without opening a window (used for automated visual regression tests). |
| `--agent`, `--backend` | Daemon / Dev | Boots the headless Python JSON-RPC daemon on stdio without opening a window (used by wrapper scripts and debug harnesses). |

### Complete CLI Argument Matrix
| Flag | Short | Scope | Description |
|---|---|---|---|
| `--help` | `-h` | Player | Prints complete syntax guide and exits immediately. |
| `--version` | `-v` | Player | Displays current launcher release version and exits. |
| `--uninstall` | None | Admin | Launches interactive Linux uninstaller with confirmation prompt. |
| `--instance` | None | Player | Boots directly into the specified Minecraft instance. |
| `--account` | None | Player | Specifies account to use for game launch. |
| `--offline-user` | None | Player | Launches an offline game session directly. |
| `--dir` | None | Player | Overrides the root `.minecraft` storage directory. |
| `--debug` | None | Player | Enables verbose debug logging in console and logs directory. |
| `--snapshot-tab` | None | Dev / CI | Renders a headless visual snapshot of a specific tab without opening a window. |
| `--agent`, `--backend` | None | Dev | Boots headless Python daemon agent without starting the GUI. |

---

## 11. Diagnostics, Exit Codes & Troubleshooting

### Common Minecraft Exit Codes
| Exit Code | Classification | Cause & Resolution |
|---|---|---|
| `0` | Normal | Clean shutdown or user quit. |
| `1` | Exception | Mod conflict, missing dependency, or invalid Java argument. Check `logs/latest.log`. |
| `-1073740791`<br>`(0xC0000409)` | GPU Crash | Stack buffer overrun in graphics driver or overlay software (Discord, RivaTuner). Update GPU drivers and disable third-party in-game overlays. |
| `137` | OOM | Process terminated by Linux Out-of-Memory (OOM) killer. Increase RAM in Settings &rarr; Java & Memory. |

### Linux FUSE Library Requirements (AppImage)
If the AppImage produces `dlopen(): error loading libfuse.so.2`:
* **Ubuntu 22.04 LTS & Debian 12:** `sudo apt install -y libfuse2`
* **Ubuntu 24.04 LTS & Newer:** `sudo apt install -y libfuse2t64`
* **Arch Linux / Manjaro:** `sudo pacman -S fuse2`
* **Fedora:** `sudo dnf install fuse`

### Wayland & KDE Plasma Diagnostics
* **Wayland Native vs XWayland:** Slint uses `winit` with automatic Wayland detection. If your compositor has window title or scaling glitches, force XWayland via:
  ```bash
  WINIT_UNIX_BACKEND=x11 nlc
  ```
* **Single Instance Socket:** If a second instance fails to focus the first, ensure `@nlc-single-instance-lock` is accessible and `kdialog` or `zenity` is installed for desktop activation.

### Linux Uninstallation
To uninstall Ny-Luna Core on Linux:
```bash
# Interactive uninstaller from CLI
nlc --uninstall

# Or run the standalone script directly
./packaging/linux/uninstall.sh
```
The uninstaller requires explicit confirmation (`[y/N]`), prompts whether to keep or purge personal instances and configs (`~/.nlc`), removes all wrappers and desktop files, and refreshes desktop icon databases.

---

## 12. Development, Build & Licensing

### Local Build Requirements
* **Python 3.12+** with `pip` and `virtualenv`
* **Rust & Cargo** (Stable toolchain 1.80+)
* **Linux Prerequisites:** `libfuse2` (or `libfuse2t64`), `gcc`, `make`, `pkg-config`, `libfontconfig-dev`

### Building from Source
```bash
# 1. Clone repository
git clone https://github.com/Amne-Dev/NLC.git
cd NLC

# 2. Set up Python backend environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Build & Run native Slint UI
cargo run --manifest-path src/frontend/Cargo.toml
```

### Packaging for Release
* **Linux AppImage:** `./packaging/linux/build_appimage.sh`
* **Arch Linux PKGBUILD:** `cd packaging/linux && makepkg -si`
* **Windows Setup:** Build using PyInstaller and InnoSetup scripts in `packaging/windows/`.

### License
Ny-Luna Core is released under the **BSD-3-Clause License**.
See the [LICENSE](https://github.com/Amne-Dev/NLC#BSD-3-Clause-1-ov-file) file for complete details.
