# New Launcher — Project Wiki

Welcome to the project wiki. This file provides a centralized, human-readable overview of the project and links to canonical documentation and website pages.

## Overview
New Launcher is an open-source Minecraft Java launcher for Windows and Linux. It keeps installation and launch workflows simple while adding profiles, modpacks, mods, skins, wallpapers, addons, and optional integrations.

## Quick links (hosted)
- Website: https://amne-dev.github.io/NLC/
- Changelog: https://amne-dev.github.io/NLC/changelog.html
- Privacy Policy: https://amne-dev.github.io/NLC/privacy.html
- Terms: https://amne-dev.github.io/NLC/terms.html
- FAQ: https://amne-dev.github.io/NLC/faq.html
- Getting Started: https://amne-dev.github.io/NLC/getting-started.html
- Download & Verification: https://amne-dev.github.io/NLC/download.html
- Support: https://amne-dev.github.io/NLC/support.html
- Contributing: https://amne-dev.github.io/NLC/contributing.html
- Security: https://amne-dev.github.io/NLC/security.html
- Credits: https://amne-dev.github.io/NLC/credits.html
- Roadmap: https://amne-dev.github.io/NLC/roadmap.html
- Gallery: https://amne-dev.github.io/NLC/gallery.html
- Wiki (site): https://amne-dev.github.io/NLC/wiki.html

## Getting Started
1. Download the latest release from GitHub: https://github.com/Amne-Dev/NLC/releases/latest
2. On Windows, run `NLCSetup.exe` and launch New Launcher from the Start Menu.
3. On Linux, download the AppImage, make it executable, and launch it:
    ```bash
    chmod +x NewLauncher-*.AppImage
    ./NewLauncher-*.AppImage
    ```
4. Create a profile, choose an installation, and launch Minecraft.

The hosted [Getting Started](https://amne-dev.github.io/NLC/getting-started.html) page includes the short version of this guide. The [Download & Verification](https://amne-dev.github.io/NLC/download.html) page contains release download information.

## User Guide

### 1. Managing Profiles
The launcher supports Microsoft, Ely.by, and offline profiles.

* **Microsoft**: Use the Microsoft sign-in flow to authenticate through your browser. The profile's username, UUID, and skin information are used when Minecraft launches.
* **Ely.by**: Sign in with an Ely.by account when you use that service's skin and account system.
* **Offline**: Enter a local username without signing in. A local PNG skin can be selected for offline skin injection.

Keep account credentials in the launcher and services they belong to. Only install addons and third-party integrations that you trust.

### 2. Creating Installations
Navigate to the **Installations** tab to manage your game versions.
*   **Create New**: Click **New Installation**.
    *   **Name**: Give your installation a name (e.g., "Survival 1.20").
    *   **Version**: Select the Minecraft version.
    *   **Loader**: Choose **Vanilla**, **Forge**, **Fabric**, **BatMod**, **LabyMod**, or **Lunar Client** where supported. The launcher handles loader installation automatically.
    *   **Icon**: Select a Minecraft block icon or a custom `.png` image.

The installation editor also supports a custom Java executable and display resolution override. These values are saved per installation.

### 3. Settings & Customization
Click the **Gear Icon** to access settings.
*   **RAM Allocation**: Use the slider to increase memory for modded instances. The default allocation is 4 GB.
*   **Wallpapers**: Customize the launcher background. You can select pre-loaded images or import your own from the `wallpapers/` folder.
*   **Rich Presence**: Toggle Discord RPC integration to show your game status ("Playing Minecraft 1.21").
*   **Java Arguments**: Advanced users can supply custom JVM arguments.
*   **Downloads**: Configure download speed and parallel download limits where available.

### 4. Modpacks and Mods
The **Modrinth** area supports mod and modpack discovery. You can choose a modpack version, install it, link it to an installation, and manage its installed mods. Individual mods can be enabled or disabled before launch.

Local CurseForge modpack exports can also be imported. Some CurseForge downloads require a user-provided API key.

### 5. Custom Skins (Offline/Ely.by)
*   **Ely.by**: Skins are managed on the Ely.by website.
*   **Offline**: Go to your profile settings, click **"Select Skin"**, and choose a valid skin `.png` file. The launcher will start a local server to inject this skin into your game session transparently.

## Developer Documentation
The current application is organized around `main.py` and the `nlc/` package:

* **`main.py`**: Application entry point.
* **`nlc/ui/`**: Screens, widgets, dialogs, and application flow.
* **`nlc/net/`**: Network-facing helpers and HTTP operations.
* **`nlc/storage/`**: Configuration and persistent launcher data.
* **`nlc/`**: Shared launcher logic, authentication, handlers, and utilities.
* **`config.py`**: Version, account defaults, supported loaders, and global settings.

The current release version is defined as `CURRENT_VERSION` in `config.py`.

### Building from Source (Windows)
Install the Python dependencies first, then run the application directly:

```bash
python -m pip install -r requirements.txt
python main.py
```

Windows release builds are automated by `.github/workflows/windows-build.yml`. The provided PyInstaller specs can also be used for local builds:

```bash
pyinstaller alt.spec
```

### Building for Linux (AppImage)
Since the project relies on system-level libraries (like Tkinter) that vary by distro, we recommend packaging as an **AppImage**.

**Prerequisites**:
*   Linux Environment (e.g., Ubuntu 20.04 LTS) or **WSL**.
*   Python 3.8+.
*   **Debian/Ubuntu**: `sudo apt install python3-tk python3-venv`
*   **Fedora**: `sudo dnf install python3-tkinter`

**Steps**:
1.  Open a terminal in the repository root.
2.  Make the build script executable:
    ```bash
    chmod +x linux/build_appimage.sh
    ```
3.  Run the script:
    ```bash
    ./linux/build_appimage.sh
    ```
4.  This will:
    *   Install pip requirements.
    *   Run PyInstaller to create a portable binary.
    *   Download `appimagetool`.
    *   Package everything into a versioned `NewLauncher-*-x86_64.AppImage`.

### Skin System Architecture

The launcher implements three distinct methods for handling player skins, depending on the account type.

#### 1. Microsoft/Mojang (Official)
*   **Mechanism**: Reference client behavior. The launcher authenticates with Microsoft OAuth2.
*   **Game Launch**: The access token and UUID are passed to the game.
*   **Skin Resolution**: The game client contacts official Mojang Session Servers (`sessionserver.mojang.com`) using the provided token to retrieve the skin assigned to that UUID in the official database.

#### 2. Ely.by (Third-Party Service)
*   **Mechanism**: Authlib Injection via Remote Server.
*   **Authorization**: The launcher authenticates the user against Ely.by's API to get a valid token.
*   **Game Launch**: The launcher adds `-javaagent:authlib-injector.jar=https://authserver.ely.by/api/authlib-injector` to the JVM arguments.
*   **Skin Resolution**: `authlib-injector` redirects all internal game requests for profile data to Ely.by's servers instead of Mojang's. Ely.by returns the skin texture associated with the user's account on their platform.

#### 3. Offline Mode (Local Injection)
This is a custom implementation allowing offline users to see their own skins without modifying the game JAR.

**The Workflow:**
1.  **Server Startup**: When launching an offline profile with a custom skin selected, `handlers.py` starts a `ThreadingTCPServer` on a random free port (e.g., `127.0.0.1:54321`).
2.  **Authlib Configuration**: The launcher calls `authlib-injector` pointing to this local address: `-javaagent:authlib-injector.jar=http://127.0.0.1:54321`.
3.  **Request Highjacking**: When the game client attempts to load the player's profile:
    *   It requests the Profile Data from the configured auth server (our local one).
    *   **Endpoint**: `/sessionserver/session/minecraft/profile/<UUID>`
    *   **Response**: The local server constructs a valid Yggdrasil-compatible JSON response. This response mimics a signed profile but contains a texture property pointing to `http://127.0.0.1:54321/textures/skin.png`.
4.  **Texture Delivery**:
    *   The game client reads the JSON response and sees the texture URL.
    *   It makes a GET request to `/textures/skin.png`.
    *   The local server reads the `.png` file specified in the Launcher Profile from the disk and renders it to the game.

**Why this matters**: This allows "Offline" skins to work seamlessly and be visible to the player (and potentially others on LAN if they shared the spoofing setup, though currently designed for local-only).

## Privacy
The launcher does not collect, transmit, or aggregate user data. See `web/privacy.html` for details.

## Troubleshooting / FAQ
See the hosted [FAQ](https://amne-dev.github.io/NLC/faq.html) and [Support](https://amne-dev.github.io/NLC/support.html) pages for common issues. Include your operating system, launcher version, reproduction steps, and relevant logs when opening an issue on GitHub: https://github.com/Amne-Dev/NLC/issues

## Contributing
Please read the hosted [Contributing](https://amne-dev.github.io/NLC/contributing.html) page for build and pull request guidance. Basic steps:
1. Fork the repo
2. Create a feature branch
3. Open a pull request with a clear description

## Security
Do not disclose security-sensitive details in a public issue. Follow the [Security Policy](https://amne-dev.github.io/NLC/security.html) for reporting guidance.

## Credits
See `CREDITS.md` for contributors and third-party libraries.

---
This wiki is intentionally concise. Expand any section by adding site pages under `web/` and linking them here.