# Ny-Luna Core (NLC)

**A fast, focused Minecraft Java launcher for Windows and Linux.**

Ny-Luna keeps the familiar parts of Minecraft launcher setup while making it easier to manage installations, modpacks, mods, skins, and profiles in one place.

<p align="center">
    <img src="assets/branding/nyluna_banner.gif" alt="Ny-Luna Core" width="560">
</p>

<p align="center">
    <a href="https://github.com/Amne-Dev/NLC/releases/latest"><img src="https://img.shields.io/github/v/release/Amne-Dev/NLC?label=Latest%20release&style=flat-square" alt="Latest release"></a>
    <a href="https://github.com/Amne-Dev/NLC/releases"><img src="https://img.shields.io/github/downloads/Amne-Dev/NLC/total?label=Downloads&style=flat-square" alt="Total downloads"></a>
    <a href="LICENSE"><img src="https://img.shields.io/github/license/Amne-Dev/NLC?style=flat-square" alt="License"></a>
    <a href="https://github.com/Amne-Dev/NLC/issues"><img src="https://img.shields.io/github/issues/Amne-Dev/NLC?style=flat-square" alt="Open issues"></a>
</p>

<p align="center">
    <a href="https://github.com/Amne-Dev/NLC/releases/latest">Download Ny-Luna</a>
    &nbsp;&middot;&nbsp;
    <a href="docs/WIKI.md">Read the user guide</a>
    &nbsp;&middot;&nbsp;
    <a href="https://github.com/Amne-Dev/NLC/issues">Get help</a>
</p>

## See It In Action

<p align="center">
    <img src="preview.png" alt="Ny-Luna play screen" width="820">
</p>

<p align="center">
    <img src="web/img/locker.png" alt="Ny-Luna skin locker" width="400">
    <img src="web/img/modpacks.png" alt="Ny-Luna modpacks screen" width="400">
</p>

<p align="center">
    <img src="web/img/mods.png" alt="Ny-Luna mods screen" width="820">
</p>

## Why Ny-Luna?

- **Start playing quickly.** Install and launch Minecraft Java Edition from a simple, familiar interface.
- **Keep installations organized.** Create separate profiles for different Minecraft versions and loaders.
- **Choose your mod setup.** Use Vanilla, Fabric, Forge, BatMod, LabyMod, or Lunar Client installations where supported.
- **Find and manage content.** Browse Modrinth, install modpacks, inspect mods, and turn individual mods on or off.
- **Make it yours.** Customize installation icons with Minecraft block textures and manage skins in the built-in locker.
- **Use the account setup that fits.** Sign in with Microsoft, connect supported skin services, or create an offline profile for local use.
- **Stay connected.** Optional Discord Rich Presence can show what you are playing.

## Install

### Windows

1. Open the [latest release](https://github.com/Amne-Dev/NLC/releases/latest).
2. Download `NLCSetup.exe`.
3. Run the installer and open **Ny-Luna** from the Start Menu.

### Linux

#### Option 1: Quick Install (Debian, Ubuntu, Arch, Manjaro, Pop!_OS)
Run this single command in your terminal to automatically install prerequisites (FUSE runtime, desktop icons), download the latest AppImage to `/opt/new-launcher`, configure application menu shortcuts, and enable the `nlc` (or `newlauncher`) terminal command:

```bash
curl -fsSL https://raw.githubusercontent.com/Amne-Dev/NLC/main/packaging/linux/install.sh | bash
```

#### Option 2: Arch Linux (AUR / PKGBUILD)
To build and install the native Slint UI package directly on Arch Linux:

```bash
cd packaging/linux
makepkg -si
```

#### Option 3: Manual AppImage Download
1. Open the [latest release](https://github.com/Amne-Dev/NLC/releases/latest).
2. Download the `NewLauncher-*-x86_64.AppImage`.
3. Make it executable and run it:

```bash
chmod +x NewLauncher-*.AppImage
./NewLauncher-*.AppImage
```

> [!NOTE]
> On Ubuntu 22.04+ or Debian 12+, ensure FUSE 2 is installed if your system does not already provide it:
> `sudo apt install libfuse2` (or `libfuse2t64` on Ubuntu 24.04+). On Arch: `sudo pacman -S fuse2`.


## Your First Installation

1. Open **Profiles** and sign in with Microsoft, or create an offline profile for local use.
2. Open **Installations** and select **New Installation**.
3. Choose a Minecraft version and loader, then select an icon if you want to personalize it.
4. Return to **Play**, select the installation, and click **Play**.

Ny-Luna can download the files it needs when you create an installation. A Java runtime may also be downloaded automatically when a loader requires it.

On Windows, launcher updates use a verified incremental patch when the release
provides one. The patch updates the launcher executable, agent, and bundled resources without replacing launcher configuration or Minecraft data. If a
patch is unavailable, the regular setup executable remains available as a
fallback.

### Windows Patch Releases

Windows patch assets are version-specific (`NLCUpdate-<base>-to-<target>.zip`).
The release workflow includes only launcher files changed since the previous
release, plus the standalone patch runner. The workflow requires the
`NLC_UPDATE_SIGNING_PRIVATE_KEY_B64` and `NLC_UPDATE_PUBLIC_KEY_B64` GitHub
secrets; releases are rejected when either signing value is missing.

Clients on unsupported versions fall back to `NLCSetup.exe`. Do not rename or
reuse a patch ZIP for another source version.

## Modpacks, Mods, and Skins

The **Modrinth** area lets you discover modpacks and mods without leaving the launcher. Installed modpacks stay linked to their Minecraft installation, and individual mods can be enabled or disabled from the management view.

The **Locker** keeps your saved skins in one place. You can also use local skin files and supported online skin services.

## Settings

Open **Settings** to adjust Java memory, launcher behavior, and optional integrations. For a large modpack, increase the Java memory allocation gradually and leave enough memory available for your operating system.

## Documentation and Support

- [User guide and troubleshooting](docs/WIKI.md)
- [Changelog](docs/CHANGELOG.md)
- [Credits & Third-Party Notices](docs/CREDITS.md)
- [Frequently asked questions](web/faq.html)
- [Report a bug or request a feature](https://github.com/Amne-Dev/NLC/issues)
- [Security policy](web/security.html)

## Build From Source

Ny-Luna Core v4.0.0 features a modern high-performance decoupled architecture:
- **Frontend (`src/frontend`)**: Pure native Rust UI powered by Slint (60+ FPS, zero GDI tearing, instant reactive rendering).
- **Backend Daemon (`src/backend`)**: Python background agent handling authentication, game process isolation, downloads, and skin serving.

### Prerequisites

- **Python 3.12+** with pip
- **Rust 1.80+** (stable toolchain with Cargo)

### Running Locally

1. Install Python backend dependencies:

```bash
python -m pip install -r requirements.txt
```

2. Run the launcher (compiles and starts the Rust Slint frontend, which automatically spawns the background agent):

```bash
cargo run --manifest-path src/frontend/Cargo.toml
```

### Packaging Windows Installers

To compile all release binaries, build FastCDC chunk recipes, and generate both Web and Offline installers:

```bash
python packaging/windows/build_installers.py --all
```

### Packaging Linux AppImage

To build the self-contained Linux AppImage (bundles native Rust Slint frontend and frozen Python agent):

```bash
chmod +x packaging/linux/build_appimage.sh
./packaging/linux/build_appimage.sh
```


Outputs are generated in `dist/` and `dist/installers/`:
- `dist/NyLuna.exe` — Native Rust frontend binary
- `dist/agent.exe` — Python background agent daemon
- `dist/installers/NLCSetup.exe` — Web installer & FastCDC network chunk streamer
- `dist/installers/NLCSetup-Offline.exe` — Standalone offline installer
- `dist/NyLuna.exe.cdc.json` — FastCDC differential recipe manifest

## License

Ny-Luna Core is open source. See [LICENSE](LICENSE) for the full license text.

Ny-Luna Core is not affiliated with Mojang Studios or Microsoft. Minecraft is a trademark of Microsoft Corporation.
