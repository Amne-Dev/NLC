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


def test_patch_runner_launch_app(monkeypatch, tmp_path):
    from patch_runner import _launch_app, APP_EXE
    launcher = tmp_path / APP_EXE
    launcher.write_bytes(b"exe")

    launched = []
    def fake_popen(cmd, cwd=None, close_fds=True, creationflags=0):
        launched.append((cmd, cwd))

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    _launch_app(str(tmp_path))

    assert len(launched) == 1
    assert launched[0][0] == [str(launcher)]
    assert launched[0][1] == str(tmp_path)


def test_patch_runner_launch_app_skips_when_missing(monkeypatch, tmp_path):
    from patch_runner import _launch_app

    launched = []
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: launched.append(a))
    _launch_app(str(tmp_path))
    assert len(launched) == 0
