"""Content-Defined Chunking (CDC) engine for differential HTTP Range updates."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from nlc import update_keys

logger = logging.getLogger(__name__)

# Precomputed 256-entry Gear rolling-hash table
GEAR_TABLE: List[int] = [
    0x8c743842, 0x4879d20c, 0xb800a7b4, 0x5a1f6a1e, 0x5b38e07a, 0x762bcf9e,
    0x9597f7fa, 0xad72a39a, 0x3d0b284e, 0x6e788bc2, 0xc1ff3b56, 0x3f545166,
    0x7e83216c, 0x7596c568, 0x8b3c4f74, 0x3d395898, 0x70d8a57e, 0x05b822d8,
    0x98188174, 0x9f5c40bc, 0x794b150c, 0x899a8b16, 0xb0e3cf08, 0x6e88d22c,
    0x82f2f754, 0x6198f46e, 0xecfa3a06, 0x367f0f62, 0xb8be3f3c, 0x2280d968,
    0x7856d2e6, 0xb8be9684, 0x18efd924, 0x1fbe526c, 0x24a49688, 0x5c8e2358,
    0x55bc2358, 0x35bc8754, 0x78de3452, 0x145896a2, 0x56be8724, 0x12ac58e6,
    0x9852f4a2, 0x45be9624, 0x2589ad42, 0x87ec42a6, 0x56a421b8, 0x78ac42b4,
] * 6
GEAR_TABLE = GEAR_TABLE[:256]

DEFAULT_MIN_CHUNK = 16 * 1024       # 16 KB
DEFAULT_AVG_CHUNK = 64 * 1024       # 64 KB
DEFAULT_MAX_CHUNK = 256 * 1024      # 256 KB
MASK_64K = 0x0000FFFF


def iter_cdc_chunks(
    stream: Any,
    min_size: int = DEFAULT_MIN_CHUNK,
    max_size: int = DEFAULT_MAX_CHUNK,
    mask: int = MASK_64K,
) -> Iterator[Tuple[int, int, bytes, str]]:
    """Yield (offset, length, chunk_data, sha256_hex) using FastCDC over a readable binary stream."""
    buffer = bytearray()
    file_offset = 0

    read_chunk_size = 2 * 1024 * 1024  # 2MB stream buffer
    eof = False

    while True:
        if not eof and len(buffer) < max_size:
            chunk_data = stream.read(read_chunk_size)
            if not chunk_data:
                eof = True
            else:
                buffer.extend(chunk_data)

        buf_len = len(buffer)
        if buf_len == 0:
            break

        if buf_len <= min_size:
            if eof:
                data = bytes(buffer)
                yield file_offset, len(data), data, hashlib.sha256(data).hexdigest()
                file_offset += len(data)
                buffer.clear()
                break
            else:
                # Need more data
                chunk_data = stream.read(read_chunk_size)
                if not chunk_data:
                    eof = True
                else:
                    buffer.extend(chunk_data)
                continue

        curr_min = min_size
        curr_max = min(buf_len, max_size)

        fp = 0
        i = curr_min
        cut_point = -1

        while i < curr_max:
            fp = ((fp << 1) + GEAR_TABLE[buffer[i]]) & 0xFFFFFFFF
            if (fp & mask) == 0:
                cut_point = i
                break
            i += 1

        if cut_point == -1:
            if curr_max == max_size or eof:
                cut_point = curr_max
            else:
                # Read more to reach max_size
                chunk_data = stream.read(read_chunk_size)
                if not chunk_data:
                    eof = True
                else:
                    buffer.extend(chunk_data)
                continue

        chunk_bytes = bytes(buffer[:cut_point])
        chunk_len = len(chunk_bytes)
        yield file_offset, chunk_len, chunk_bytes, hashlib.sha256(chunk_bytes).hexdigest()

        file_offset += chunk_len
        del buffer[:cut_point]


def build_cdc_index(file_path: Path | str, target_version: str, filename: Optional[str] = None) -> Dict[str, Any]:
    """Scan a target binary and generate a Content-Defined Chunking recipe index."""
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Source file not found: {path}")

    total_hasher = hashlib.sha256()
    chunks = []
    total_size = 0

    with path.open("rb") as f:
        for offset, length, chunk_bytes, chunk_hash in iter_cdc_chunks(f):
            total_hasher.update(chunk_bytes)
            total_size += length
            chunks.append({
                "offset": offset,
                "length": length,
                "sha256": chunk_hash,
            })

    return {
        "formatVersion": 1,
        "filename": filename or path.name,
        "targetVersion": target_version,
        "targetSize": total_size,
        "targetSha256": total_hasher.hexdigest(),
        "chunkCount": len(chunks),
        "chunks": chunks,
    }


def canonical_cdc_bytes(index: Dict[str, Any]) -> bytes:
    """Return deterministic JSON bytes for Ed25519 signing (excluding signature field)."""
    unsigned = dict(index)
    unsigned.pop("signature", None)
    return json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def sign_cdc_index(index: Dict[str, Any], private_key_b64: str) -> None:
    """Sign the CDC index in-place using Ed25519 private key."""
    if not private_key_b64:
        raise ValueError("Private key is required to sign CDC index.")
    private_key = Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(private_key_b64, validate=True)
    )
    sig_bytes = private_key.sign(canonical_cdc_bytes(index))
    index["signature"] = base64.b64encode(sig_bytes).decode("ascii")


def verify_cdc_signature(index: Dict[str, Any], public_key_b64: Optional[str] = None) -> None:
    """Verify Ed25519 signature on CDC index."""
    sig_text = index.get("signature")
    pub_key_text = public_key_b64 or update_keys.PATCH_PUBLIC_KEY_B64
    if not isinstance(sig_text, str) or not sig_text:
        raise ValueError("CDC index is missing its signature.")
    if not pub_key_text:
        raise ValueError("Patch signing public key is not configured.")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(pub_key_text, validate=True)
        )
        signature = base64.b64decode(sig_text, validate=True)
        public_key.verify(signature, canonical_cdc_bytes(index))
    except (ValueError, InvalidSignature) as exc:
        raise ValueError("CDC index signature verification failed.") from exc


def scan_local_chunks(local_path: Path | str) -> Dict[str, int]:
    """Slice an installed binary and return a mapping of {chunk_sha256: offset_in_file}."""
    path = Path(local_path).resolve()
    if not path.is_file():
        return {}

    local_map: Dict[str, int] = {}
    with path.open("rb") as f:
        for offset, _length, _data, chunk_hash in iter_cdc_chunks(f):
            # Prefer first occurrence
            if chunk_hash not in local_map:
                local_map[chunk_hash] = offset
    return local_map


def coalesce_missing_ranges(
    remote_chunks: List[Dict[str, Any]],
    local_chunk_map: Dict[str, int],
    max_gap: int = 32 * 1024,
) -> List[Tuple[int, int]]:
    """
    Identify missing chunks and coalesce contiguous or nearby slices into merged (start, end_inclusive) ranges.
    """
    missing_slices: List[Tuple[int, int]] = []
    for c in remote_chunks:
        if c["sha256"] not in local_chunk_map:
            start = c["offset"]
            end = start + c["length"] - 1
            missing_slices.append((start, end))

    if not missing_slices:
        return []

    coalesced: List[Tuple[int, int]] = []
    curr_start, curr_end = missing_slices[0]

    for s_start, s_end in missing_slices[1:]:
        if s_start <= curr_end + 1 + max_gap:
            # Merge slices
            curr_end = max(curr_end, s_end)
        else:
            coalesced.append((curr_start, curr_end))
            curr_start, curr_end = s_start, s_end

    coalesced.append((curr_start, curr_end))
    return coalesced


def download_and_assemble_cdc(
    local_path: Optional[Path | str],
    remote_index: Dict[str, Any],
    download_url: str,
    output_path: Path | str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> None:
    """
    Assemble the target executable using locally cached chunks + HTTP Range requests for missing spans.
    """
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    target_size = int(remote_index.get("targetSize", 0))
    expected_sha256 = str(remote_index.get("targetSha256", "")).lower()

    if target_size <= 0:
        raise ValueError("Invalid targetSize in CDC index.")

    local_map: Dict[str, int] = {}
    local_file: Optional[Path] = None
    if local_path:
        lp = Path(local_path).resolve()
        if lp.is_file():
            local_file = lp
            local_map = scan_local_chunks(local_file)

    remote_chunks: List[Dict[str, Any]] = remote_index.get("chunks", [])
    ranges_to_fetch = coalesce_missing_ranges(remote_chunks, local_map)

    # 1. Pre-allocate target file
    part_out = out.with_suffix(out.suffix + ".part")
    with part_out.open("wb") as f:
        f.truncate(target_size)

    bytes_written = 0
    total_bytes = target_size

    # 2. Copy matching chunks from local binary
    if local_file and local_map:
        with local_file.open("rb") as src, part_out.open("r+b") as dst:
            for c in remote_chunks:
                c_hash = c["sha256"]
                if c_hash in local_map:
                    src.seek(local_map[c_hash])
                    data = src.read(c["length"])
                    dst.seek(c["offset"])
                    dst.write(data)
                    bytes_written += len(data)
                    if progress_callback:
                        progress_callback(bytes_written, total_bytes)

    # 3. Fetch missing ranges over HTTP Range requests
    session = requests.Session()
    try:
        with part_out.open("r+b") as dst:
            for start, end in ranges_to_fetch:
                headers = {"Range": f"bytes={start}-{end}"}
                with session.get(download_url, headers=headers, stream=True, timeout=(10, 30)) as resp:
                    resp.raise_for_status()
                    dst.seek(start)
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        dst.write(chunk)
                        bytes_written += len(chunk)
                        if progress_callback:
                            progress_callback(bytes_written, total_bytes)
    finally:
        session.close()

    # 4. Verify target checksum
    hasher = hashlib.sha256()
    with part_out.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            hasher.update(chunk)

    actual_hash = hasher.hexdigest().lower()
    if actual_hash != expected_sha256:
        part_out.unlink(missing_ok=True)
        raise ValueError(
            f"CDC target verification failed! Expected {expected_sha256}, got {actual_hash}"
        )

    # Atomic move into final path
    os.replace(part_out, out)


def main():
    parser = argparse.ArgumentParser(description="Content-Defined Chunking index generator")
    parser.add_argument("binary", help="Path to binary file")
    parser.add_argument("--version", default="0.0.0", help="Target release version")
    parser.add_argument("--output", default="", help="Output path for index JSON")
    args = parser.parse_args()

    binary_path = Path(args.binary)
    out_path = Path(args.output) if args.output else binary_path.with_suffix(binary_path.suffix + ".cdc.json")

    idx = build_cdc_index(binary_path, args.version)
    out_path.write_text(json.dumps(idx, indent=2), encoding="utf-8")
    print(f"Generated CDC index: {out_path} ({idx['chunkCount']} chunks, target size: {idx['targetSize']} bytes)")


if __name__ == "__main__":
    main()
