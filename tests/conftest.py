import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
backend_dir = REPO_ROOT / "src" / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def mock_agent_process_for_ui(request, monkeypatch):
    """Prevent launcher UI tests from spawning lingering background agent.py processes."""
    if request.node.name == "test_agent_script_exists_and_runs" or "tests/e2e" in str(request.node.fspath).replace("\\", "/"):
        return
    import subprocess
    real_popen = subprocess.Popen
    def safe_popen(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        if isinstance(cmd, (list, tuple)) and any("agent.py" in str(arg) for arg in cmd):
            from unittest.mock import MagicMock
            proc = MagicMock()
            proc.poll.return_value = 0
            proc.terminate.return_value = None
            proc.kill.return_value = None
            return proc
        return real_popen(*args, **kwargs)
    monkeypatch.setattr(subprocess, "Popen", safe_popen)
