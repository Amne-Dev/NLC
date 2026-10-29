# Ny-Luna Core (NLC) — Technical & Architectural Wiki

Welcome to the **Ny-Luna Core** technical wiki. This document serves as the canonical reference for users, modpack creators, addon authors, and core developers on the architecture, subsystems, security model, and operations of Ny-Luna Core (NLC).

---

## Table of Contents
1. [Overview & Decoupled Topology](#1-overview--decoupled-topology)
2. [Process Model & IPC Protocol](#2-process-model--ipc-protocol)
3. [Authentication Engines & Credential Vault](#3-authentication-engines--credential-vault)
4. [Installations, Modloaders & JVM Architecture](#4-installations-modloaders--jvm-architecture)
5. [Skin System, Authlib Injection & 3D Software Engine](#5-skin-system-authlib-injection--3d-software-engine)
6. [Modpacks, Mods & Content Delivery](#6-modpacks-mods--content-delivery)
7. [Addons Framework & Decoupled Extensions](#7-addons-framework--decoupled-extensions)
8. [FastCDC Differential Updater & Security](#8-fastcdc-differential-updater--security)
9. [Storage Layout, File Locations & Atomic IO](#9-storage-layout-file-locations--atomic-io)
10. [Command-Line Interface (CLI Reference)](#10-command-line-interface-cli-reference)
11. [Diagnostics, Exit Codes & Troubleshooting](#11-diagnostics-exit-codes--troubleshooting)
12. [Contributing & Development Setup](#12-contributing--development-setup)

---

## 1. Overview & Decoupled Topology

**Ny-Luna Core (NLC)** is an open-source Minecraft Java Edition launcher for Windows and Linux. Starting with release v4.0.0, Ny-Luna transitioned from a monolithic architecture to an asynchronous, decoupled multi-process topology.

### Architectural Goals
* **Sub-Millisecond UI Responsiveness:** The user interface is decoupled from heavy network operations, Java process launches, and disk hashing.
* **GPU-Accelerated Window Chrome:** Rendered natively via Rust and Slint UI without the memory overhead of Chromium or Electron.
* **Deterministic Local-First Isolation:** Complete user privacy with no telemetry or aggregation. All profiles, modpacks, and credentials stay on your local disk.
* **Zero Jar-Modding Skin Injection:** Transparent skin support for offline and third-party profiles through non-invasive JVM agent injection.

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
                   (stdin/stdout pipe)
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

## 2. Process Model & IPC Protocol

The launcher coordinates three distinct process domains:

| Process Domain | Binary / Target | Technology | Privileges | Lifetime |
|---|---|---|---|---|
| **Frontend GUI** | `nlc-ui` / `NyLuna.exe` | Rust, Slint UI | Standard User | Active during user session |
| **Daemon Agent** | `agent.py` / `agent.exe` | Python 3.12+ (Daemon) | Standard User | Spawns with GUI, terminates on GUI exit |
| **Patch Supervisor** | `NLCUpdater.exe` / `patch_runner.py` | C / Python Runner | Elevated (UAC `runas`) | Spawns detached only during updates |

### IPC Protocol Specification (GUI <-> Daemon Agent)
The frontend and backend communicate via anonymous pipes over standard input and standard output (`stdin`/`stdout`).

* **Encoding:** UTF-8, line-delimited JSON (`\n`).
* **Request Correlation:** The client issues a unique UUID for each request (`id`). The server responds with the identical `id`.
* **Asynchronous Events:** The backend emits unsolicited events (download progress, Discord status updates, game termination) using the `event` key.

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
  }
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

---

## 3. Authentication Engines & Credential Vault

Ny-Luna Core handles multiple account types without telemetry or remote logging:

### 1. Microsoft / Mojang Authentication (OAuth 2.0)
1. **Device Code Request:** The launcher requests a device authorization grant from Microsoft Identity (`https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode`) with client ID `00000000402b5328`.
2. **Xbox Live Authentication:** Exchanges the Microsoft OAuth token at `https://user.auth.xboxlive.com/user/authenticate` for an Xbox Live token.
3. **XSTS Authorization:** Contacts `https://xsts.auth.xboxlive.com/xsts/authorize` with RelyingParty `rp://api.minecraftservices.com/` to produce the XSTS token and user hash (`uhs`).
4. **Minecraft Services Login:** Sends the XSTS proof to `https://api.minecraftservices.com/authentication/login_with_xbox` to acquire the final Bearer token.
5. **Entitlement & Profile Fetch:** Verifies game ownership via `/entitlements/mcstore` and fetches player UUID, skin textures, and capes from `/minecraft/profile`.

### 2. Ely.by Account Service
* Authenticates directly with Ely.by via `https://authserver.ely.by/auth/authenticate`.
* Uses `accessToken` and `selectedProfile.id`.
* Transparently adds Ely.by's authlib server to JVM launch flags:
  `-javaagent:authlib-injector.jar=https://authserver.ely.by/api/authlib-injector`.

### 3. Offline (Local) Profiles
* Calculates a deterministic UUID in compliance with standard Minecraft server offline algorithms:
  ```python
  uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{player_name}")
  ```
* Supports local custom PNG skins and capes via the internal Yggdrasil proxy.

### 4. Credential Vault
All sensitive tokens (`access_token`, `refresh_token`, `xsts`) are stored in `launcher_config.json` inside encrypted blocks using AES-GCM and DPAPI system-protected keys. Plaintext credentials are never written to disk or sent over external networks.

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
* **Shared Assets:** `resourcepacks`, `shaderpacks`, `saves`, and `assets` can be linked to a central storage root.

### Java Version Matrix & GC Tuning
| Minecraft Version | Required Java Runtime | Recommended GC |
|---|---|---|
| **1.7.10 - 1.16.5** | Java 8 (OpenJDK / Temurin) | ParallelGC or G1GC |
| **1.17 - 1.20.4** | Java 17 | Aiken Tuned G1GC |
| **1.20.5 - 1.21.x+** | Java 21+ | Aiken Tuned G1GC / ZGC |

Pre-tuned Aiken G1GC arguments included with the launcher:
```text
-XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 -XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC -XX:+AlwaysPreTouch -XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 -XX:G1ReservePercent=20 -XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 -XX:InitiatingHeapOccupancyPercent=15 -XX:G1MixedGCLiveThresholdPercent=90 -XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 -XX:+PerfDisableSharedMem -XX:MaxTenuringThreshold=1
```

---

## 5. Skin System, Authlib Injection & 3D Software Engine

Ny-Luna Core provides a non-invasive skin injection system for offline players, eliminating the need to modify game JAR files.

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

### 3. Software 3D Skin Preview Engine
The **Locker** tab features a software 3D skin rasterizer written in Pillow and NumPy:
* **Format Normalization:** Automatically converts legacy 64x32 skins to 64x64 format with second-layer alpha support.
* **Camera Transformations:** Applies 3D rotation matrices:
  $$R_{\text{cam}} = R_{\text{pitch}} \times R_{\text{yaw}}$$
* **Real-Time Animation:** Simulates limb pendulum swings ($\theta_{\text{leg}} = 26^\circ \sin(\omega)$) and cape flutter ($6^\circ + 6^\circ |\sin(\omega)|$).
* **Shading & Rasterization:** Normal vectors are evaluated for backface culling ($\vec{N}_{\text{cam}}[2] \ge 0$), shaded by an ambient sun vector ($\vec{L} = [0.3, 0.8, -0.5]$), and rasterized via affine polygon transformation (`Image.Transform.AFFINE`).

---

## 6. Modpacks, Mods & Content Delivery

Ny-Luna integrates directly with the **Modrinth API** and provides importer capabilities for **CurseForge** modpacks.

### Modrinth Integration
* **Search & Filter:** Query mods, modpacks, resource packs, and shaders filtered by version and modloader.
* **Native `.mrpack` Support:** Extracts `modrinth.index.json`, downloads all dependencies with concurrent streams, and validates SHA-1 and SHA-512 hashes.
* **Overrides Extraction:** Extracts `overrides/` and `client-overrides/` safely, blocking path traversal vulnerabilities (Zip Slip).

### CurseForge Importer
* Unpacks CurseForge modpack ZIP archives.
* Parses `manifest.json`, resolving `projectID` and `fileID` records.
* Supports user-supplied CurseForge API keys for restricted assets.

### Non-Destructive Mod Toggling
Disabling a mod appends a `.disabled` extension (e.g. `sodium.jar.disabled`). This prevents loaders from mounting the JAR while preserving configuration files and download caches.

---

## 7. Addons Framework & Decoupled Extensions

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
* **Screenshot Gallery:** Browse, copy, and organize in-game screenshots from the launcher.

---

## 8. FastCDC Differential Updater & Security

Ny-Luna features differential binary updating powered by **FastCDC** (Content-Defined Chunking) and **Ed25519** cryptographic signatures:

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

## 9. Storage Layout, File Locations & Atomic IO

### Standard Filesystem Paths
| Content | Windows Path | Linux Path |
|---|---|---|
| **Launcher Data Root** | `%APPDATA%\.nlc` | `~/.nlc` |
| **Config File** | `%APPDATA%\.nlc\launcher_config.json` | `~/.nlc/launcher_config.json` |
| **Single-Instance Lock** | `%APPDATA%\.nlc\launcher.lock` | `~/.nlc/launcher.lock` |
| **Crash & Agent Logs** | `%APPDATA%\.nlc\logs\` | `~/.nlc/logs/` |
| **Default Game Dir** | `%APPDATA%\.minecraft` | `~/.minecraft` |
| **Installation Binary** | `%LOCALAPPDATA%\Programs\Ny-Luna` | `/opt/new-launcher` |

### Atomic Persistence Protocol
To prevent file corruption during sudden power failures or system crashes:
1. `ConfigManager` creates a temporary file `nlc_cfg_*.tmp` inside the target directory.
2. Writes formatted JSON and calls `os.fsync(f.fileno())` to guarantee physical disk write.
3. Creates a backup copy `launcher_config.json.bak`.
4. Atomically promotes the temporary file to `launcher_config.json` via `os.replace()`.

---

## 10. Command-Line Interface (CLI Reference)

Launch commands are accessed via `nlc` (or the legacy alias `newlauncher`):

```bash
# Launch default GUI
nlc

# Launch headless daemon agent directly
nlc --agent

# Launch directly into an installation
nlc --instance "Fabric 1.21" --account "MyUsername"

# Launch in offline mode
nlc --offline-user "Alex"

# Launch with verbose debug output
nlc --debug
```

### CLI Flag Reference
| Flag | Arguments | Description |
|---|---|---|
| `--help`, `-h` | None | Prints complete syntax guide and exits. |
| `--version`, `-v` | None | Displays current launcher release version. |
| `--agent`, `--backend` | None | Boots headless Python agent without starting the GUI. |
| `--instance` | `<name_or_id>` | Launches the specified Minecraft instance. |
| `--account` | `<username>` | Specifies account to use for game launch. |
| `--offline-user` | `<name>` | Launches an offline game session directly. |
| `--dir` | `<path>` | Overrides the root `.minecraft` storage directory. |
| `--debug` | None | Enables verbose logging in console and logs directory. |

---

## 11. Diagnostics, Exit Codes & Troubleshooting

### Common Minecraft Exit Codes
| Exit Code | Classification | Cause & Resolution |
|---|---|---|
| `0` | Normal | Clean shutdown or user quit. |
| `1` | Exception | Mod conflict or missing dependency. Review `logs/latest.log`. |
| `-1073740791`<br>`(0xC0000409)` | GPU Crash | Stack buffer overrun in graphics driver or overlay software (Discord, RivaTuner). Update GPU drivers and disable third-party overlays. |
| `137` | OOM | Process terminated by Linux Out-of-Memory (OOM) killer. Increase RAM in Settings. |

### Missing Linux FUSE Library (AppImage)
If the AppImage produces `dlopen(): error loading libfuse.so.2`:
* **Ubuntu 22.04 LTS & Debian 12:** `sudo apt install -y libfuse2`
* **Ubuntu 24.04 LTS & Newer:** `sudo apt install -y libfuse2t64`
* **Arch Linux:** `sudo pacman -S fuse2`
* **Fedora:** `sudo dnf install fuse`

---

## 12. Contributing & Development Setup

### Local Build Requirements
* **Python 3.12+** with `pip` and `virtualenv`
* **Rust & Cargo** (Stable toolchain)
* **Linux Prerequisites:** `libfuse2` (or `libfuse2t64`), `gcc`, `make`

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
