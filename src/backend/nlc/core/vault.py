# Ny-Luna Core Credential Vault Module
# Windows DPAPI encryption with authenticated local AES-256-GCM fallback.

import base64
import ctypes
try:
    from ctypes import wintypes
except (ImportError, ValueError):
    wintypes = None  # type: ignore
import logging
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional, Tuple

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from nlc.storage.paths import get_launcher_data_dir

logger = logging.getLogger(__name__)

VAULT_PREFIX_DPAPI = "vault:dpapi:"
VAULT_PREFIX_LOCAL = "vault:local:"
APP_ENTROPY = b"NyLunaLauncher-Vault-v1"


if wintypes is not None and hasattr(wintypes, "DWORD"):
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]
else:
    class DATA_BLOB(ctypes.Structure):  # type: ignore
        _fields_ = [
            ("cbData", ctypes.c_uint32),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]


def _get_machine_guid() -> str:
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
                guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                if guid and str(guid).strip():
                    return str(guid).strip()
        except Exception as exc:
            logger.debug("Could not read MachineGuid from registry: %s", exc)

    for path_str in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            p = Path(path_str)
            if p.exists():
                content = p.read_text(encoding="utf-8").strip()
                if content:
                    return content
        except Exception:
            pass

    return str(uuid.getnode())


def _get_username() -> str:
    try:
        import getpass
        u = getpass.getuser()
        if u and u.strip():
            return u.strip()
    except Exception:
        pass
    env_u = os.environ.get("USERNAME") or os.environ.get("USER") or "default_user"
    return env_u.strip()


def _dpapi_protect(data: bytes, entropy: Optional[bytes] = APP_ENTROPY) -> bytes:
    if sys.platform != "win32":
        raise OSError("DPAPI is only available on Windows")

    crypt32 = getattr(ctypes.windll, "crypt32", None)
    kernel32 = getattr(ctypes.windll, "kernel32", None)
    if not crypt32 or not kernel32:
        raise OSError("crypt32 or kernel32 DLL not available")

    in_buf = ctypes.create_string_buffer(data, len(data))
    in_blob = DATA_BLOB(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_byte)))
    out_blob = DATA_BLOB()

    if entropy:
        ent_buf = ctypes.create_string_buffer(entropy, len(entropy))
        ent_blob = DATA_BLOB(len(entropy), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_byte)))
        ent_ptr = ctypes.byref(ent_blob)
    else:
        ent_ptr = None

    # CRYPTPROTECT_UI_FORBIDDEN = 0x01
    res = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        ctypes.c_wchar_p("NLC_CREDENTIAL"),
        ent_ptr,
        None,
        None,
        1,
        ctypes.byref(out_blob),
    )
    if not res:
        raise ctypes.WinError()

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(data: bytes, entropy: Optional[bytes] = APP_ENTROPY) -> bytes:
    if sys.platform != "win32":
        raise OSError("DPAPI is only available on Windows")

    crypt32 = getattr(ctypes.windll, "crypt32", None)
    kernel32 = getattr(ctypes.windll, "kernel32", None)
    if not crypt32 or not kernel32:
        raise OSError("crypt32 or kernel32 DLL not available")

    in_buf = ctypes.create_string_buffer(data, len(data))
    in_blob = DATA_BLOB(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_byte)))
    out_blob = DATA_BLOB()

    if entropy:
        ent_buf = ctypes.create_string_buffer(entropy, len(entropy))
        ent_blob = DATA_BLOB(len(entropy), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_byte)))
        ent_ptr = ctypes.byref(ent_blob)
    else:
        ent_ptr = None

    # CRYPTPROTECT_UI_FORBIDDEN = 0x01
    res = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        ent_ptr,
        None,
        None,
        1,
        ctypes.byref(out_blob),
    )

    if not res and ent_ptr is not None:
        # Fallback probe without application entropy
        res = crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            1,
            ctypes.byref(out_blob),
        )

    if not res:
        raise ctypes.WinError()

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


class VaultManager:
    def __init__(self, salt_path: Optional[Path] = None):
        self._lock = threading.Lock()
        self._salt_path = salt_path or (get_launcher_data_dir() / ".vault_salt")
        self._salt: Optional[bytes] = None
        self._aesgcm: Optional[AESGCM] = None

    def is_dpapi_available(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            crypt32 = getattr(ctypes.windll, "crypt32", None)
            if not crypt32 or not hasattr(crypt32, "CryptProtectData"):
                return False
            probe = b"__dpapi_probe__"
            enc = _dpapi_protect(probe)
            dec = _dpapi_unprotect(enc)
            return dec == probe
        except Exception as exc:
            logger.debug("DPAPI probe check failed: %s", exc)
            return False

    def is_vault_string(self, val: Any) -> bool:
        return isinstance(val, str) and val.startswith("vault:")

    def _read_salt_from_disk(self, max_retries: int = 5) -> Tuple[Optional[bytes], Optional[Exception]]:
        last_exc: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                if self._salt_path.exists():
                    with open(self._salt_path, "rb") as f:
                        data = f.read()
                        if len(data) >= 16:
                            return data[:32], None
            except Exception as exc:
                last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(0.02 * (2 ** attempt))
        return None, last_exc

    def _get_or_create_salt(self) -> bytes:
        is_healing_truncated = False
        if self._salt_path.exists():
            salt, last_exc = self._read_salt_from_disk(max_retries=5)
            if salt is not None:
                return salt

            try:
                size = self._salt_path.stat().st_size
            except Exception:
                size = 16

            if size >= 16:
                logger.warning(
                    "Vault salt file %s exists (size=%d) but could not be read after retries: %s",
                    self._salt_path,
                    size,
                    last_exc,
                )
                raise OSError(f"Failed to read existing salt file: {last_exc}")

            is_healing_truncated = True

        new_salt = os.urandom(32)
        try:
            self._salt_path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY

            if is_healing_truncated:
                fd = os.open(str(self._salt_path), flags | os.O_TRUNC, 0o600)
            else:
                try:
                    fd = os.open(str(self._salt_path), flags | os.O_EXCL, 0o600)
                except (FileExistsError, PermissionError) as exc:
                    salt, read_exc = self._read_salt_from_disk(max_retries=8)
                    if salt is not None:
                        return salt
                    raise OSError(f"Failed to read salt file created concurrently: {read_exc or exc}")

            with os.fdopen(fd, "wb") as f:
                f.write(new_salt)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except Exception:
                    pass
            try:
                os.chmod(str(self._salt_path), 0o600)
            except Exception:
                pass
            return new_salt
        except Exception as exc:
            if isinstance(exc, OSError) and "Failed to read" in str(exc):
                raise
            logger.warning("Could not persist vault salt file %s: %s", self._salt_path, exc)
            return new_salt

    def _get_aesgcm(self) -> AESGCM:
        with self._lock:
            if self._aesgcm is not None:
                return self._aesgcm

            if self._salt is None:
                self._salt = self._get_or_create_salt()

            guid = _get_machine_guid()
            user = _get_username()
            key_material = f"nyluna-vault:{guid}:{user}".encode("utf-8")
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=self._salt,
                iterations=100000,
            )
            derived_key = kdf.derive(key_material)
            self._aesgcm = AESGCM(derived_key)
            return self._aesgcm

    def _local_encrypt(self, data: bytes) -> bytes:
        aesgcm = self._get_aesgcm()
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, data, None)
        return nonce + ciphertext

    def _local_decrypt(self, raw: bytes) -> bytes:
        if len(raw) < 28:
            raise ValueError("AES-GCM payload too short to contain nonce and auth tag")
        nonce = raw[:12]
        ciphertext = raw[12:]
        aesgcm = self._get_aesgcm()
        return aesgcm.decrypt(nonce, ciphertext, None)

    def encrypt(self, plaintext: str, prefer_dpapi: bool = True) -> str:
        if plaintext is None:
            return ""
        if not isinstance(plaintext, str):
            plaintext = str(plaintext)
        if not plaintext:
            return ""
        if self.is_vault_string(plaintext):
            return plaintext

        raw_bytes = plaintext.encode("utf-8")

        if prefer_dpapi and self.is_dpapi_available():
            try:
                enc_bytes = _dpapi_protect(raw_bytes)
                b64_str = base64.b64encode(enc_bytes).decode("ascii")
                return f"{VAULT_PREFIX_DPAPI}{b64_str}"
            except Exception as exc:
                logger.warning("DPAPI encryption failed, falling back to local vault: %s", exc)

        # Fallback to local authenticated AES-256-GCM
        enc_bytes = self._local_encrypt(raw_bytes)
        b64_str = base64.b64encode(enc_bytes).decode("ascii")
        return f"{VAULT_PREFIX_LOCAL}{b64_str}"

    def decrypt(self, ciphertext: str) -> str:
        if ciphertext is None:
            return ""
        if not isinstance(ciphertext, str):
            return str(ciphertext)
        if not ciphertext:
            return ""
        if not self.is_vault_string(ciphertext):
            return ciphertext

        if ciphertext.startswith(VAULT_PREFIX_DPAPI):
            payload_str = ciphertext[len(VAULT_PREFIX_DPAPI):]
            try:
                raw_bytes = base64.b64decode(payload_str)
                dec_bytes = _dpapi_unprotect(raw_bytes)
                return dec_bytes.decode("utf-8")
            except Exception as exc:
                logger.warning("DPAPI decryption failed: %s", exc)
                return ""

        if ciphertext.startswith(VAULT_PREFIX_LOCAL):
            payload_str = ciphertext[len(VAULT_PREFIX_LOCAL):]
            try:
                raw_bytes = base64.b64decode(payload_str)
                dec_bytes = self._local_decrypt(raw_bytes)
                return dec_bytes.decode("utf-8")
            except Exception as exc:
                logger.warning("Local AES-GCM decryption failed: %s", exc)
                return ""

        logger.warning("Unknown vault prefix for ciphertext: %s", ciphertext[:20])
        return ""


_DEFAULT_VAULT: Optional[VaultManager] = None
_INIT_LOCK = threading.Lock()


def get_vault_manager() -> VaultManager:
    global _DEFAULT_VAULT
    with _INIT_LOCK:
        if _DEFAULT_VAULT is None:
            _DEFAULT_VAULT = VaultManager()
        return _DEFAULT_VAULT


def encrypt(plaintext: str, prefer_dpapi: bool = True) -> str:
    return get_vault_manager().encrypt(plaintext, prefer_dpapi=prefer_dpapi)


def decrypt(ciphertext: str) -> str:
    return get_vault_manager().decrypt(ciphertext)


def is_vault_string(val: Any) -> bool:
    return get_vault_manager().is_vault_string(val)


def is_dpapi_available() -> bool:
    return get_vault_manager().is_dpapi_available()


# Aliases for backward compatibility and alternate interfaces
protect_secret = encrypt
unprotect_secret = decrypt
is_secret_protected = is_vault_string
