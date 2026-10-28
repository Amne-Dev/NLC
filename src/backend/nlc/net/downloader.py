
import hashlib
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional
from nlc.net.http import get_http_session, DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

def download_file(
    url: str,
    destination: Path,
    *,
    cancel_event=None,
    chunk_size: int = 64 * 1024,
    progress: Optional[Callable[[int, int], None]] = None,
    headers: Optional[dict] = None,
    rate_limit_kib: int = 0,
    expected_sha1: Optional[str] = None,
    timeout=DEFAULT_TIMEOUT,
    session: Optional[Any] = None,
) -> Path:
    dest_path = Path(destination).resolve()
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_name(f"{dest_path.name}.{uuid.uuid4().hex}.part")

    http_session = session or get_http_session()

    try:
        with http_session.get(url, stream=True, headers=headers, timeout=timeout) as response:
            response.raise_for_status()
            total_size = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            started_at = time.monotonic()

            with open(temp_path, "wb") as out_f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if cancel_event is not None and cancel_event.is_set():
                        raise RuntimeError("Download cancelled by user.")
                    if not chunk:
                        continue
                    out_f.write(chunk)
                    downloaded += len(chunk)

                    if rate_limit_kib > 0:
                        target_elapsed = downloaded / (rate_limit_kib * 1024)
                        remaining = target_elapsed - (time.monotonic() - started_at)
                        if remaining > 0:
                            time.sleep(remaining)

                    if progress is not None:
                        progress(downloaded, total_size)

        # Checksum validation
        if expected_sha1:
            hasher = hashlib.sha1()
            with open(temp_path, "rb") as check_f:
                while chunk := check_f.read(1024 * 1024):
                    hasher.update(chunk)
            if hasher.hexdigest().lower() != expected_sha1.lower():
                raise ValueError(
                    f"Download checksum verification failed: expected {expected_sha1}, got {hasher.hexdigest()}"
                )

        # Atomic replacement
        os.replace(temp_path, dest_path)
        logger.info("Successfully downloaded %s -> %s", url, dest_path)
        return dest_path

    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise

def atomic_download(url, destination, *, cancel_event=None, chunk_size=64 * 1024, progress=None, headers=None, rate_limit_kib=0, expected_sha1=None):
    return download_file(
        url,
        Path(destination),
        cancel_event=cancel_event,
        chunk_size=chunk_size,
        progress=progress,
        headers=headers,
        rate_limit_kib=rate_limit_kib,
        expected_sha1=expected_sha1,
    )

_atomic_download = atomic_download
