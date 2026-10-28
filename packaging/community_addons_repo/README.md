# New Launcher Community Addons Registry

Welcome to the official community extensions repository for **New-launcher** (NLC)!
This repository acts as the decentralized community catalog fetched by the launcher.

- **Repository**: [Amne-Dev/Community-addons-nlc](https://github.com/Amne-Dev/Community-addons-nlc)
- **Catalog Endpoint**: `https://raw.githubusercontent.com/Amne-Dev/Community-addons-nlc/main/addons.json`

---

## 🚀 How It Works

1. Developers build an extension or utility for New-launcher.
2. Developers register their addon using `python tools/community_tool.py register` (which auto-assigns a collision-free ID and pre-screens for safety).
3. Open a Pull Request adding the verified entry to `addons.json`.
4. Automated CI runs `scripts/validate_catalog.py` to audit metadata safety, URL accessibility, and file integrity.
5. Once merged, the addon instantly appears in New-launcher under the **Community Addons** tab!

---

## 📦 Addon Manifest Specification (`addons.json`)

Each entry in `addons.json` must follow this schema:

```json
{
  "id": "custom_crosshair",
  "name": "Custom Crosshair",
  "version": "1.0.0",
  "author": "Amne-Dev",
  "description": "Dynamic customizable HUD crosshairs with multiple shapes and RGB color presets.",
  "icon_url": "https://raw.githubusercontent.com/Amne-Dev/Community-addons-nlc/main/addons/custom_crosshair/icon.png",
  "download_url": "https://github.com/Amne-Dev/Community-addons-nlc/raw/main/addons/custom_crosshair/addon.zip",
  "sha256": "Optional SHA-256 integrity checksum",
  "action_label": "Install",
  "tags": ["HUD", "Visual"]
}
```

### Fields:
- `id` (string, required): Unique identifier matching `^[a-z0-9_]{3,40}$`.
- `name` (string, required): Clean display title shown in the launcher card.
- `version` (string, required): Semantic version (e.g. `1.0.0`).
- `author` (string, required): Creator or team name.
- `description` (string, required): Brief summary (10-400 characters).
- `download_url` (string, required): Direct HTTPS URL to release `.zip` archive.
- `sha256` (string, optional): SHA-256 hash of the release archive for cryptographic integrity.
- `icon_url` (string, optional): Direct link to a 1:1 square icon PNG.
- `action_label` (string, optional): Button label in launcher (defaults to `"Install"`).
- `tags` (array of strings, optional): Category keywords.

---

## 🛡️ Security & Malware Policies

To protect launcher users, all submissions must comply with the following:
1. **Zero Native Executables**: Addons are modular UI/data/Python scripts. Release archives **cannot contain `.exe`, `.bat`, `.cmd`, `.dll`, `.ps1`, `.vbs`, `.so`, or `.scr` files**.
2. **Anti-Zip-Slip**: Archive file paths must not contain directory traversal (`..`) or absolute paths.
3. **Manifest Entry**: Release archives must contain a valid `addon.json` matching the catalog ID.
4. **Content Moderation**: Name and description are screened for profanity, slurs, phishing, and scam lures (`free nitro`, `token stealer`, etc.).
5. **HTTPS Only**: Download URLs must strictly use HTTPS without URL shorteners.

---

## 🛠️ Developer CLI Tool

This repository includes a developer CLI helper:

```bash
# Check if an ID is available
python tools/community_tool.py check-id <candidate_id>

# Auto-suggest an available ID from name and author
python tools/community_tool.py suggest-id --name "My Mod" --author "Steve"

# Run interactive registration wizard with security scan
python tools/community_tool.py register

# Validate all catalog entries
python scripts/validate_catalog.py
```
