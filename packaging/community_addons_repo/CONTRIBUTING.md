# Contributing to Community Addons Registry

Thank you for contributing to the New-launcher ecosystem! Follow these steps to submit or update an addon.

---

## 1. Unique Addon ID Policy

Every community addon requires a globally unique identifier formatted as lowercase alphanumeric characters and underscores (`^[a-z0-9_]{3,40}$`).

### How to Get a Unique ID:
You have complete freedom over your addon's display name (e.g. `⚡ Epic Crosshair 2026`). To make sure your ID doesn't collide with existing addons, use our developer CLI:

- **Automatic Registration (Recommended)**:
  ```bash
  python tools/community_tool.py register
  ```
  This interactive wizard automatically suggests a clean, collision-free ID based on your addon name and author (e.g. `epic_crosshair` or `author_epic_crosshair`), performs immediate security checks, and formats your entry into `addons.json`.

- **Check ID Availability Manually**:
  ```bash
  python tools/community_tool.py check-id <candidate_id>
  ```
  If taken, the tool will output who owns it and suggest available alternatives.

- **Suggest Unique ID**:
  ```bash
  python tools/community_tool.py suggest-id --name "My Addon" --author "Steve"
  ```

---

## 2. Security & Content Moderation Policies

Every submission is automatically scanned by our CI security suite:

1. **Content Moderation**:
   - Addon names and descriptions must be appropriate, accurate, and respectful.
   - Profanity, slurs, scam terms (e.g. `free nitro`, `free accounts`), and deceptive keywords will cause automated PR failure.
   - HTML or JavaScript injection tags (`<script>`, `<iframe>`, `javascript:`) are strictly forbidden.

2. **Download URL Constraints**:
   - Must use secure HTTPS (`https://`).
   - Bare IP addresses, localhost, and URL shorteners (`bit.ly`, `tinyurl.com`, etc.) are blocked.
   - Recommended hosts: GitHub Releases (`https://github.com/<user>/<repo>/releases/...`), Modrinth, CurseForge, or reputable HTTPS hosts.

3. **Archive Security & Malware Screening**:
   - **Strict Executable Ban**: Addons are modular extensions (JSON, Slint, Python, assets). Release archives **MUST NOT** contain compiled native executables or batch scripts (`.exe`, `.bat`, `.cmd`, `.ps1`, `.vbs`, `.dll`, `.so`, `.dylib`, `.scr`). Submissions containing binaries will be rejected.
   - **Anti-Zip-Slip**: Archive paths cannot contain `..` or absolute paths.
   - **Manifest Required**: Must include a valid `addon.json` (or `manifest.json`) at root or top-level directory.
   - **Static Script Analysis**: Python scripts are scanned for obfuscation (`base64.b64decode`, `eval`), Discord webhook grabbers, and credential theft.

---

## 3. Pull Request Checklist

Before opening your PR:
- [ ] Registered via `python tools/community_tool.py register` or verified ID with `check-id`.
- [ ] Validated catalog locally: `python scripts/validate_catalog.py`.
- [ ] Download archive contains `addon.json` and zero native executables.
- [ ] Description accurately conveys addon functionality.
