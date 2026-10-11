import pytest

from patch_runner import _parse_args, _validate_args


def test_patch_runner_rejects_negative_pid(tmp_path):
    patch = tmp_path / "patch.zip"
    patch.write_bytes(b"zip")
    args = _parse_args([
        "--patch", str(patch),
        "--target", str(tmp_path),
        "--launcher-pid", "-1",
    ])

    with pytest.raises(ValueError, match="non-negative"):
        _validate_args(args)


def test_patch_runner_validates_paths(tmp_path):
    patch = tmp_path / "patch.zip"
    patch.write_bytes(b"zip")
    args = _parse_args([
        "--patch", str(patch),
        "--target", str(tmp_path),
    ])

    _validate_args(args)


def test_patch_runner_rejects_missing_patch(tmp_path):
    args = _parse_args([
        "--patch", str(tmp_path / "missing.zip"),
        "--target", str(tmp_path),
    ])

    with pytest.raises(FileNotFoundError):
        _validate_args(args)
