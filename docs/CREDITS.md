# Credits

## Development & Leadership
- **Project Lead & Architecture**: Amne-Dev ([@Amne-Dev](https://github.com/Amne-Dev))

## Core Architecture & Technologies
Ny-Luna Core (NLC) v4.0.0 is built on modern native technologies:

- **[Rust](https://www.rust-lang.org/)**: High-performance systems programming language powering the native desktop client.
- **[Slint UI](https://slint.dev/)**: Hardware-accelerated, declarative cross-platform GUI framework powering the 60 FPS brutalist interface.
- **FastCDC Rolling Hash Engine**: Custom Content-Defined Chunking differential updater with HTTP Range request assembly for minimal download sizes.
- **Python Daemon Agent**: Isolated background process handling game lifecycle supervision, instance isolation, and modpack resolution.

## Open Source Libraries

### Rust Frontend Ecosystem
- **[Slint](https://crates.io/crates/slint)**: Declarative UI toolkit and reactive property system.
- **[serde](https://crates.io/crates/serde)** & **[serde_json](https://crates.io/crates/serde_json)**: High-speed JSON serialization and IPC communication with the backend daemon.
- **[tokio](https://crates.io/crates/tokio)**: Asynchronous runtime for concurrent background tasks and thread synchronization.

### Python Backend Ecosystem
- **[minecraft-launcher-lib](https://gitlab.com/JakobDev/minecraft-launcher-lib)**: Minecraft metadata handling, installation management, and launch argument generation.
- **[requests](https://requests.readthedocs.io/)**: Robust HTTP networking for Modrinth queries, asset streaming, and differential chunk downloads.
- **[Pillow](https://python-pillow.org/)**: Image manipulation for skin compositing, texture caching, and dynamic chevron badges.
- **[pypresence](https://github.com/qwertyquerty/pypresence)**: Real-time Discord Rich Presence integration.
- **[cryptography](https://cryptography.io/)**: Security verification for update manifests, patch signing, and addon catalogs.
- **[skinpy](https://pypi.org/project/skinpy/)**: Skin model parsing and 64x64 / 64x32 geometry adaptation.
- **[pystray](https://github.com/moses-palmer/pystray)**: Windows system tray minimization and background daemon control.

## Game Ecosystem & External Services
- **[authlib-injector](https://github.com/yushijinhun/authlib-injector)**: Local skin injection and offline skin servers without jar tampering.
- **[Modrinth](https://modrinth.com/)**: Mod, modpack, and community project discovery and automatic installation linking.
- **[Ely.by](https://ely.by/)**: Community authentication service and skin repository integration.
- **[Microsoft / Xbox](https://www.microsoft.com/)**: Official Microsoft OAuth authentication and game entitlement verification.
- **Mod Loaders**: [Fabric](https://fabricmc.net/), [Forge](https://files.minecraftforge.net/), [NeoForge](https://neoforged.net/), and [Quilt](https://quiltmc.org/) for supporting the broader modding ecosystem.
- **[GitHub Actions](https://github.com/features/actions)**: Automated cross-compilation, test orchestration, and release distribution.

## Special Thanks
- **Mojang Studios**: For creating Minecraft and inspiring generations of players and developers.
- **The Minecraft Modding Community**: For the passionate tooling, libraries, APIs, and creators that make this project meaningful.
- **Open Source Maintainers**: For developing and maintaining the open-source libraries that Ny-Luna Core depends upon.
