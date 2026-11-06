# Security Policy

The Ny-Luna Core (NLC) project takes the security and privacy of its users, accounts, and execution environments seriously. This document outlines our supported versions, security architecture, vulnerability disclosure guidelines, and reporting procedures.

---

## Supported Versions

Security updates, vulnerability patches, and integrity fixes are actively maintained for the following versions:

| Version | Supported          | Status                                 |
| :------ | :----------------: | :------------------------------------- |
| 4.0.x   | :white_check_mark: | Current active release line            |
| < 4.0.0 | :x:                | End of Life (Legacy Tkinter architecture) |

We strongly recommend all users stay updated to the latest stable release to ensure critical security patches and protocol updates are applied.

---

## Security Architecture & Safeguards

Ny-Luna Core is engineered with defensive security layers designed to protect player credentials, prevent arbitrary code execution during modpack installations, and ensure the integrity of the launcher runtime:

1. **Credential Vault & Hardware/OS Encryption**:
   - Authentication tokens (Microsoft OAuth, Ely.by session tokens, offline profiles) are never stored in cleartext.
   - Secrets are secured using hardware-backed platform cryptographic stores: **Windows DPAPI** (`CryptProtectData`) on Windows and **Keyring / SecretService** on Linux, reinforced with **AES-256-GCM** encryption and per-machine salt derivation.
   - Diagnostic and log outputs automatically redact authorization headers, bearer tokens, ciphertext slices, and passwords.

2. **IPC Process Isolation**:
   - The launcher operates on a decoupled architecture separating the native UI frontend (Rust / Slint) from the backend daemon (Python).
   - Communication is constrained strictly to the local loopback boundary (`127.0.0.1`), with message validation and sanitization on all inter-process remote procedure calls.

3. **Archive Extraction & Zip-Slip Defense**:
   - Modpack, world, and resource pack installers enforce strict canonical path traversal validation to prevent Zip-Slip vulnerabilities.
   - Files with absolute path components or directory traversal prefixes (`../`) outside the target instance sandbox are rejected immediately.

4. **Update Verification & Cryptographic Signatures**:
   - FastCDC update packages and differential recipes (`.cdc.json`) are cryptographically verified using **Ed25519 digital signatures** prior to patching launcher binaries.
   - Official release binaries are hashed with SHA-256 and matched against verified release manifests.

---

## Reporting a Vulnerability

If you discover a security vulnerability or potential exploit within Ny-Luna Core, please report it privately. **Do not create public GitHub issues or discuss undisclosed vulnerabilities in public Discord channels.**

### Preferred Method: GitHub Private Vulnerability Reporting
You can privately disclose vulnerabilities directly through GitHub:
1. Navigate to the [Ny-Luna Core Security Advisories](https://github.com/Amne-Dev/NLC/security/advisories) tab.
2. Click **"Report a vulnerability"** to open a confidential advisory draft.
3. Include detailed information to assist us in understanding and reproducing the issue.

### Alternative Method: Direct Maintainer Contact
If you cannot use GitHub Advisories, you may reach out directly to the core maintainers via:
- **Discord**: Direct message a project maintainer on our official [Discord Community](https://discord.gg/2CSGqYz9ms).
- Clearly mention that you are reaching out regarding a private security disclosure.

---

## What to Include in Your Report

To help us investigate and remediate the issue quickly, please provide:
- **Vulnerability Type**: (e.g., Credential leakage, Path traversal, Insecure deserialization, Privilege escalation).
- **Affected Component**: (e.g., Frontend Slint UI, Backend IPC Agent, Installer, FastCDC updater, Modpack importer).
- **Affected Version**: (e.g., v4.0.6, or specific commit hash).
- **Reproduction Steps**: Step-by-step instructions or minimal proof-of-concept (PoC).
- **Impact Assessment**: The potential consequences of exploiting the vulnerability (e.g., local token access, arbitrary file overwrite).
- **Suggested Remediation**: (Optional) Recommended code changes or mitigation steps if you have already analyzed them.

---

## Vulnerability Handling & Response Process

1. **Initial Acknowledgment**:
   - Maintainers will acknowledge receipt of your report within **48 to 72 hours**.
2. **Assessment & Triage**:
   - The team will investigate, verify reproduction, assign a severity rating (CVSS), and communicate findings with you.
3. **Patch Development & Testing**:
   - A fix will be developed in a private security fork or branch, accompanied by adversarial unit tests.
4. **Coordinated Disclosure**:
   - A patched release will be published.
   - Maintainers will publish a GitHub Security Advisory detailing the issue and remediation, with proper credit and attribution given to the reporter (unless anonymity is requested).

