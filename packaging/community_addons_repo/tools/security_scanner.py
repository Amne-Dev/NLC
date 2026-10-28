#!/usr/bin/env python3
"""
Security and Malware Verification Engine for Community Addons (Amne-Dev/Community-addons-nlc).

Provides:
1. Unique Addon ID derivation and slugification.
2. Content moderation for addon metadata (profanity, scam/phishing terms, HTML/script injections).
3. Download URL safety constraints (HTTPS only, blocked shorteners/IPs, size limits).
4. Deep archive security inspection:
   - Anti-Zip-Slip directory traversal prevention
   - Strict ban on native executables (.exe, .dll, .bat, .cmd, .ps1, .vbs, .so, etc.)
   - Addon structure & manifest validation (addon.json / manifest.json)
   - Static analysis on Python scripts for token grabbers, obfuscated code, and backdoors
   - Cryptographic SHA-256 calculation
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import urllib.parse
import urllib.request
import zipfile
from typing import Any, Dict, List, Optional, Set, Tuple

# ==============================================================================
# 1. ID Generation & Slugification
# ==============================================================================

ID_REGEX = re.compile(r"^[a-z0-9_]{3,40}$")

def slugify_id(text: str) -> str:
    """Convert arbitrary text (e.g. display name or author) into a valid addon ID slug."""
    text = text.strip().lower()
    # Replace whitespace and dashes with underscores
    text = re.sub(r"[\s\-]+", "_", text)
    # Remove any character not alphanumeric or underscore
    text = re.sub(r"[^a-z0-9_]", "", text)
    # Collapse multiple underscores
    text = re.sub(r"_+", "_", text).strip("_")
    # Truncate to max 40 chars
    return text[:40]


def generate_unique_id(
    name: str,
    author: str,
    existing_ids: Set[str],
    preferred_id: Optional[str] = None
) -> str:
    """
    Derives an available, unique ID for an addon given existing catalog IDs.
    Tries preferred_id (if valid), then name slug, then author_name slug, then numbered suffix.
    """
    if preferred_id:
        clean_pref = slugify_id(preferred_id)
        if clean_pref and len(clean_pref) >= 3 and clean_pref not in existing_ids:
            return clean_pref

    name_slug = slugify_id(name)
    author_slug = slugify_id(author)

    if not name_slug:
        name_slug = "addon"

    # Candidate 1: clean name slug (e.g. "custom_crosshair")
    if len(name_slug) >= 3 and name_slug not in existing_ids:
        return name_slug

    # Candidate 2: author + name (e.g. "amne_custom_crosshair")
    if author_slug:
        combined = f"{author_slug}_{name_slug}"[:40]
        if len(combined) >= 3 and combined not in existing_ids:
            return combined

    # Candidate 3: numbered suffix
    counter = 2
    base = name_slug[:35]
    while True:
        candidate = f"{base}_{counter}"
        if candidate not in existing_ids:
            return candidate
        counter += 1


# ==============================================================================
# 2. Content Moderation (Name, Description, Author)
# ==============================================================================

# Blacklist of prohibited words / slurs / offensive content
PROFANITY_PATTERNS = [
    r"\b(nigger|nigga|faggot|kike|chink|cunt|retard)\b",
    r"\b(porn|nsfw|hentai|sex|rape|hitler|nazi)\b",
]

# Scam, phishing, and malware lure patterns
SCAM_PATTERNS = [
    r"\bfree\s+(nitro|vbucks|minecoins|robux|gift\s*card)\b",
    r"\b(discord\s*token|token\s*grabber|session\s*stealer|stealer)\b",
    r"\b(hack\s*client|cheat\s*bypass|hacked\s*client|force\s*op)\b",
    r"\b(rat\s+installer|remote\s*access\s*trojan|ransomware)\b",
    r"\b(crack\s*minecraft|free\s*minecraft\s*account)\b",
]

# Prohibited script / HTML tags
MALICIOUS_TAGS = [
    r"<\s*script\b",
    r"<\s*iframe\b",
    r"<\s*embed\b",
    r"<\s*object\b",
    r"javascript\s*:",
    r"data\s*:\s*text/html",
    r"onload\s*=",
    r"onerror\s*=",
]


class SecurityValidationError(Exception):
    """Raised when an addon fails safety or structural verification."""
    pass


def verify_content_safety(item: Dict[str, Any]) -> List[str]:
    """
    Validates name, description, author, and tags for malicious or inappropriate content.
    Returns a list of error messages (empty if completely clean).
    """
    errors: List[str] = []

    name = str(item.get("name", "")).strip()
    author = str(item.get("author", "")).strip()
    description = str(item.get("description", "")).strip()
    addon_id = str(item.get("id", "")).strip()

    # ID format check
    if not ID_REGEX.match(addon_id):
        errors.append(f"Invalid ID format '{addon_id}': Must match ^[a-z0-9_]{{3,40}}$")

    # Name constraints
    if len(name) < 3 or len(name) > 60:
        errors.append(f"Name must be between 3 and 60 characters (got {len(name)})")

    # Author constraints
    if len(author) < 2 or len(author) > 40:
        errors.append(f"Author must be between 2 and 40 characters (got {len(author)})")

    # Description constraints
    if len(description) < 10 or len(description) > 500:
        errors.append(f"Description must be between 10 and 500 characters (got {len(description)})")

    # Impersonation check
    lower_name = name.lower()
    if lower_name.startswith("official new launcher") or lower_name.startswith("mojang admin"):
        errors.append("Addon name cannot impersonate official launcher or Mojang components")

    combined_text = f"{name} {author} {description} {' '.join(item.get('tags', []))}".lower()

    # HTML / Script injection check
    for pattern in MALICIOUS_TAGS:
        if re.search(pattern, combined_text, re.IGNORECASE):
            errors.append(f"Malicious HTML/Script injection pattern detected: '{pattern}'")

    # Profanity check
    for pattern in PROFANITY_PATTERNS:
        if re.search(pattern, combined_text, re.IGNORECASE):
            errors.append("Inappropriate or offensive language detected in metadata")

    # Scam / Phishing check
    for pattern in SCAM_PATTERNS:
        match = re.search(pattern, combined_text, re.IGNORECASE)
        if match:
            errors.append(f"Suspicious or deceptive term detected: '{match.group(0)}'")

    return errors


# ==============================================================================
# 3. URL Verification & Safe Download
# ==============================================================================

MAX_ADDON_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB limit

BLOCKED_SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "buff.ly", "ow.ly",
    "adf.ly", "bc.vc", "shorte.st", "cutt.ly", "rb.gy", "shorturl.at"
}


def verify_download_url(url: str) -> List[str]:
    """Validates that the download URL adheres to security policies."""
    errors: List[str] = []
    if not url:
        return ["Missing required field: download_url"]

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        return [f"Malformed download_url: {exc}"]

    # 1. Strictly HTTPS
    if parsed.scheme.lower() != "https":
        errors.append(f"download_url must use secure HTTPS protocol (got '{parsed.scheme}')")

    host = (parsed.hostname or "").lower()
    if not host:
        errors.append("download_url missing valid host name")

    # 2. Block direct IP addresses (e.g. 192.168.1.1 or 127.0.0.1)
    if re.match(r"^(\d{1,3}\.){3}\d{1,3}$", host) or host in ("localhost", "0.0.0.0"):
        errors.append(f"download_url cannot point to direct IP or localhost ('{host}')")

    # 3. Block URL shorteners
    if host in BLOCKED_SHORTENERS:
        errors.append(f"download_url cannot use URL shortener domain '{host}'")

    return errors


def download_addon_archive(url: str, timeout: int = 15, max_bytes: int = MAX_ADDON_SIZE_BYTES) -> Tuple[bytes, str]:
    """
    Safely streams and downloads an addon archive into memory with a size cap.
    Returns (raw_bytes, sha256_hex).
    Raises SecurityValidationError on download failure or size violation.
    """
    url_errors = verify_download_url(url)
    if url_errors:
        raise SecurityValidationError("; ".join(url_errors))

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "NLC-SecurityScanner/3.0"}
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise SecurityValidationError(
                    f"Remote file size ({content_length} bytes) exceeds limit ({max_bytes} bytes)"
                )

            buffer = bytearray()
            hasher = hashlib.sha256()

            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                buffer.extend(chunk)
                hasher.update(chunk)
                if len(buffer) > max_bytes:
                    raise SecurityValidationError(
                        f"Download exceeded maximum allowed addon size of {max_bytes // (1024 * 1024)} MB"
                    )

            data = bytes(buffer)
            return data, hasher.hexdigest()
    except Exception as exc:
        if isinstance(exc, SecurityValidationError):
            raise
        raise SecurityValidationError(f"Failed to fetch addon archive from {url}: {exc}")


# ==============================================================================
# 4. Deep Archive Security Inspection
# ==============================================================================

# Executable / native binary extensions strictly prohibited in addons
FORBIDDEN_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".scr", ".pif", ".com",
    ".dll", ".so", ".dylib", ".jar", ".msi", ".reg", ".hta", ".cpl", ".lnk",
    ".sys", ".drv", ".bin", ".elf", ".sh", ".bash"
}

# Suspicious code signatures inside Python scripts
SUSPICIOUS_SCRIPT_PATTERNS = [
    (r"\b(base64\.b64decode|eval|exec|compile|marshal\.loads)\s*\(", "Obfuscated / dynamic code execution"),
    (r"(discord\.com/api/v\d+/webhooks|discordapp\.com/api/webhooks)", "Hardcoded Discord Webhook (potential data exfiltration)"),
    (r"(\.leveldb|Local\s*Storage|Roaming/Discord|discord_tokens)", "Credential / Token scraping pattern"),
    (r"(socket\.socket|reverse_shell|nc\s+-e|/bin/sh)", "Reverse shell / socket backdoor pattern"),
    (r"(os\.system\s*\(\s*['\"]rm\s+-rf|os\.system\s*\(\s*['\"]del\s+/f)", "Destructive command execution pattern"),
]


def verify_archive_safety(
    archive_bytes: bytes,
    expected_id: Optional[str] = None
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """
    Performs deep inspection of the ZIP archive:
    1. Validates ZIP magic bytes.
    2. Enforces Anti-Zip-Slip (no path traversal).
    3. Rejects dangerous executable extensions.
    4. Ensures presence of addon.json / manifest.json.
    5. Performs static analysis on scripts.
    Returns (is_valid, error_list, manifest_data).
    """
    errors: List[str] = []
    manifest_data: Dict[str, Any] = {}

    # Check ZIP magic bytes (PK\x03\x04)
    if not archive_bytes.startswith(b"PK\x03\x04"):
        return False, ["Invalid archive format: File does not have valid ZIP magic bytes"], {}

    try:
        zf = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except Exception as exc:
        return False, [f"Corrupted or invalid ZIP archive: {exc}"], {}

    infolist = zf.infolist()
    if not infolist:
        return False, ["ZIP archive is empty"], {}

    found_manifest = False
    manifest_names = {"addon.json", "manifest.json"}

    for member in infolist:
        raw_name = member.filename
        norm_name = raw_name.replace("\\", "/")

        # 1. Anti-Zip-Slip Check: Reject directory traversal
        if norm_name.startswith("/") or ".." in norm_name.split("/"):
            errors.append(f"Zip-Slip Directory Traversal exploit detected: '{raw_name}'")

        # Reject absolute Windows paths (e.g. C:/...)
        if re.match(r"^[a-zA-Z]:", norm_name):
            errors.append(f"Absolute Windows path detected in archive: '{raw_name}'")

        # Skip directory members
        if member.is_dir():
            continue

        # 2. Executable / Dangerous File Ban
        _, ext = os.path.splitext(norm_name.lower())
        if ext in FORBIDDEN_EXTENSIONS:
            errors.append(
                f"Forbidden executable file extension '{ext}' in member '{norm_name}'. Addons cannot contain native binaries."
            )

        # 3. Check for manifest
        basename = os.path.basename(norm_name)
        if basename in manifest_names:
            found_manifest = True
            try:
                content = zf.read(member).decode("utf-8")
                parsed_manifest = json.loads(content)
                if isinstance(parsed_manifest, dict):
                    manifest_data = parsed_manifest
            except Exception as exc:
                errors.append(f"Failed to parse manifest '{norm_name}': {exc}")

        # 4. Static script analysis for Python files
        if norm_name.endswith(".py"):
            try:
                code_text = zf.read(member).decode("utf-8", errors="ignore")
                for pattern, desc in SUSPICIOUS_SCRIPT_PATTERNS:
                    if re.search(pattern, code_text, re.IGNORECASE):
                        errors.append(f"Security Alert in '{norm_name}': {desc}")
            except Exception as exc:
                errors.append(f"Could not read script member '{norm_name}': {exc}")

    # 5. Manifest requirement
    if not found_manifest:
        errors.append("Archive missing required 'addon.json' (or 'manifest.json') manifest entry")
    elif expected_id and manifest_data:
        m_id = str(manifest_data.get("id", "")).strip()
        if m_id and m_id != expected_id:
            errors.append(
                f"Manifest ID '{m_id}' in addon.json does not match catalog ID '{expected_id}'"
            )

    return len(errors) == 0, errors, manifest_data

