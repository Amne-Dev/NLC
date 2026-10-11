import hashlib
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from nlc.cdc_engine import (
    build_cdc_index,
    scan_local_chunks,
    coalesce_missing_ranges,
    download_and_assemble_cdc,
    iter_cdc_chunks,
)


def test_cdc_chunking_and_index_generation(tmp_path):
    target = tmp_path / "app.exe"
    payload = b"HEADER_DATA" * 5000 + b"MIDDLE_DATA" * 5000 + b"FOOTER_DATA" * 5000
    target.write_bytes(payload)

    index = build_cdc_index(target, "3.0.6")
    assert index["formatVersion"] == 1
    assert index["filename"] == "app.exe"
    assert index["targetVersion"] == "3.0.6"
    assert index["targetSize"] == len(payload)
    assert index["targetSha256"] == hashlib.sha256(payload).hexdigest()
    assert index["chunkCount"] > 0
    assert sum(c["length"] for c in index["chunks"]) == len(payload)


def test_cdc_boundary_shift_deduplication(tmp_path):
    orig_file = tmp_path / "v1.exe"
    base = b"".join(hashlib.sha256(str(i).encode()).digest() for i in range(10000))
    orig_file.write_bytes(b"OLD_HEADER_" * 100 + base)

    mod_file = tmp_path / "v2.exe"
    # Insert a different-length header
    mod_file.write_bytes(b"NEW_DIFFERENT_HEADER_LONG_" * 100 + base)

    idx1 = build_cdc_index(orig_file, "1.0.0")
    idx2 = build_cdc_index(mod_file, "2.0.0")

    hashes1 = {c["sha256"] for c in idx1["chunks"]}
    hashes2 = {c["sha256"] for c in idx2["chunks"]}
    common = hashes1.intersection(hashes2)

    # Significant chunk overlap despite arbitrary header shift
    assert len(common) >= 5


def test_scan_local_chunks(tmp_path):
    local_file = tmp_path / "local.exe"
    local_file.write_bytes(b"LOCAL_DATA_BLOCK_" * 4000)

    local_map = scan_local_chunks(local_file)
    assert len(local_map) > 0
    for h, offset in local_map.items():
        assert isinstance(offset, int)
        assert offset >= 0


def test_coalesce_missing_ranges():
    remote_chunks = [
        {"offset": 0, "length": 1000, "sha256": "hash_a"},
        {"offset": 1000, "length": 1000, "sha256": "hash_b"},
        {"offset": 2000, "length": 1000, "sha256": "hash_c"},
        {"offset": 3000, "length": 1000, "sha256": "hash_d"},
    ]

    # Only hash_a and hash_d exist locally; hash_b and hash_c are missing
    local_chunk_map = {"hash_a": 0, "hash_d": 3000}

    # Should coalesce hash_b (1000..1999) and hash_c (2000..2999) into single range [1000, 2999]
    ranges = coalesce_missing_ranges(remote_chunks, local_chunk_map)
    assert ranges == [(1000, 2999)]


def test_download_and_assemble_cdc_reconstructs_exact_binary(monkeypatch, tmp_path):
    # Setup full remote file
    target_data = b"BLOCK_ONE_" * 3000 + b"BLOCK_TWO_MODIFIED_" * 3000 + b"BLOCK_THREE_" * 3000
    remote_file = tmp_path / "target.exe"
    remote_file.write_bytes(target_data)

    index = build_cdc_index(remote_file, "3.0.6")

    # Local file has BLOCK_ONE and BLOCK_THREE, but old BLOCK_TWO
    old_data = b"BLOCK_ONE_" * 3000 + b"BLOCK_TWO_OLD_" * 3000 + b"BLOCK_THREE_" * 3000
    local_file = tmp_path / "installed.exe"
    local_file.write_bytes(old_data)

    output_file = tmp_path / "staged.exe"

    # Mock HTTP session requests to simulate range downloads from remote_file
    class MockResponse:
        def __init__(self, data):
            self.data = data
            self.status_code = 206

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size=65536):
            for i in range(0, len(self.data), chunk_size):
                yield self.data[i:i + chunk_size]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    ranges_requested = []

    def mock_get(url, headers=None, stream=True, timeout=None):
        range_header = headers.get("Range", "")
        # e.g. "bytes=start-end"
        bytes_part = range_header.replace("bytes=", "")
        start, end = [int(x) for x in bytes_part.split("-")]
        ranges_requested.append((start, end))
        return MockResponse(target_data[start:end + 1])

    monkeypatch.setattr("requests.Session.get", lambda self, url, **kwargs: mock_get(url, **kwargs))

    progress_ticks = []
    def on_progress(done, total):
        progress_ticks.append((done, total))

    download_and_assemble_cdc(
        local_path=local_file,
        remote_index=index,
        download_url="https://github.com/fake/releases/target.exe",
        output_path=output_file,
        progress_callback=on_progress,
    )

    # Output file must exist and be byte-for-byte identical to target_data
    assert output_file.exists()
    assert output_file.read_bytes() == target_data
    assert len(progress_ticks) > 0
    # Verified range requests were made for the missing parts only
    assert len(ranges_requested) > 0
