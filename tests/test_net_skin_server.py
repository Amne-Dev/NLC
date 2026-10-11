import os
import sys
import time
import urllib.request
import json
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from handlers import LocalSkinServer, LocalSkinHandler

def test_local_skin_server_lifecycle_and_endpoints(tmp_path):
    # Create dummy skin file
    skin_file = tmp_path / "steve.png"
    skin_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtestskin")

    server = LocalSkinServer(port=0)
    base_url = server.start(
        skin_path=str(skin_file),
        player_name="TestPlayer",
        player_uuid="12345678-1234-1234-1234-123456789abc",
        skin_model="classic"
    )
    assert base_url is not None
    assert base_url.startswith("http://127.0.0.1:")
    assert server.is_running()

    try:
        # 1. Test root metadata endpoint
        with urllib.request.urlopen(f"{base_url}/", timeout=3) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["meta"]["serverName"] == "NLC Skin Handler"

        # 2. Test texture endpoint
        with urllib.request.urlopen(f"{base_url}/textures/skin.png", timeout=3) as resp:
            assert resp.status == 200
            content = resp.read()
            assert content.startswith(b"\x89PNG")

        # 3. Test profile endpoint and versioned texture URL
        profile_url = f"{base_url}/sessionserver/session/minecraft/profile/12345678-1234-1234-1234-123456789abc"
        with urllib.request.urlopen(profile_url, timeout=3) as resp:
            assert resp.status == 200
            assert "no-cache" in resp.headers.get("Cache-Control", "")
            profile_data = json.loads(resp.read().decode("utf-8"))
            assert profile_data["name"] == "TestPlayer"
            assert "properties" in profile_data

            # Verify versioned texture URL
            b64_textures = profile_data["properties"][0]["value"]
            import base64
            tex_json = json.loads(base64.b64decode(b64_textures).decode("utf-8"))
            skin_url = tex_json["textures"]["SKIN"]["url"]
            assert "?v=" in skin_url

        # 4. Test versioned texture request
        with urllib.request.urlopen(skin_url, timeout=3) as resp:
            assert resp.status == 200
            assert resp.read().startswith(b"\x89PNG")
    finally:
        server.stop()
        assert not server.is_running()
