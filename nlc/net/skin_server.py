"""
nlc.net.skin_server - Local Yggdrasil-compatible Skin Server for Offline Mode with authlib-injector
"""

import base64
import http.server
import json
import logging
import os
import socketserver
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

class LocalSkinHandler(http.server.BaseHTTPRequestHandler):
    """Serves the locally selected skin to the game via authlib-injector."""
    _skin_cache: Dict[str, bytes] = {}
    _cache_lock = threading.Lock()

    def log_message(self, format, *args):
        pass  # Suppress HTTP server noise

    def _get_cached_skin_data(self, filepath: Optional[str]) -> Optional[bytes]:
        if not filepath or not os.path.exists(filepath):
            return None
        try:
            mtime = os.path.getmtime(filepath)
            key = f"{filepath}:{mtime}"
            with self._cache_lock:
                if key in self._skin_cache:
                    return self._skin_cache[key]
                data = Path(filepath).read_bytes()
                if len(self._skin_cache) > 20:
                    self._skin_cache.pop(next(iter(self._skin_cache)), None)
                self._skin_cache[key] = data
                return data
        except Exception:
            return None

    def do_POST(self):
        config = getattr(self.server, "skin_config", {})
        player_name = config.get("player_name", "Player")
        player_uuid = config.get("player_uuid", "")

        if self.path.startswith("/authserver/") or self.path == "/authenticate":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")
            return

        elif self.path == "/api/profiles/minecraft":
            p_id = player_uuid.replace("-", "") if player_uuid else uuid.uuid4().hex
            resp = [{"id": p_id, "name": player_name}]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return

        self.send_error(404)

    def do_GET(self):
        config = getattr(self.server, "skin_config", {})
        skin_path = config.get("skin_path")
        player_name = config.get("player_name", "Player")
        player_uuid = config.get("player_uuid", "")
        skin_model = config.get("skin_model", "classic")

        # Strip query parameters for routing
        path_without_query = self.path.split("?")[0]

        if path_without_query == "/":
            self.send_response(200)
            self.send_header("X-Authlib-Injector-API-Location", "/")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "meta": {
                    "serverName": "NLC Skin Handler",
                    "implementationName": "NLC Skin Handler",
                    "implementationVersion": "2.0.0"
                },
                "skinDomains": ["localhost", "127.0.0.1"],
                "signaturePublicKeys": []
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))
            return

        if path_without_query.startswith("/sessionserver/session/minecraft/profile/"):
            requested_uuid = path_without_query.split("/")[-1]
            if not skin_path or not os.path.exists(skin_path):
                p_id = requested_uuid or (player_uuid.replace("-", "") if player_uuid else "")
                resp = {"id": p_id, "name": player_name, "properties": []}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(json.dumps(resp).encode("utf-8"))
                return

            host = self.headers.get("Host", "127.0.0.1")

            # Version tag based on skin modification timestamp or file hash
            # This prevents Minecraft from reusing stale client/world skin caches
            version_tag = "1"
            try:
                mtime = int(os.path.getmtime(skin_path))
                version_tag = f"{mtime:x}"
            except Exception:
                pass

            texture_url = f"http://{host}/textures/skin.png?v={version_tag}"
            texture_info: Dict[str, Any] = {"url": texture_url}
            if skin_model == "slim":
                texture_info["metadata"] = {"model": "slim"}

            textures = {
                "timestamp": int(time.time() * 1000),
                "profileId": requested_uuid,
                "profileName": player_name,
                "textures": {"SKIN": texture_info}
            }

            b64_textures = base64.b64encode(json.dumps(textures).encode("utf-8")).decode("utf-8")
            response_payload = {
                "id": requested_uuid,
                "name": player_name,
                "properties": [{"name": "textures", "value": b64_textures}]
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(json.dumps(response_payload).encode("utf-8"))
            return

        if path_without_query == "/textures/skin.png":
            skin_data = self._get_cached_skin_data(skin_path)
            if not skin_data:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(skin_data)))
            # Long cache for specific versioned URL
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.end_headers()
            self.wfile.write(skin_data)
            return

        self.send_error(404)

class LocalSkinServer:
    """Manages local HTTP server for serving offline skins via authlib-injector."""
    def __init__(self, port: int = 0):
        self.port = port
        self.httpd: Optional[socketserver.ThreadingTCPServer] = None
        self.thread: Optional[threading.Thread] = None
        self._running = False

    def start(self, skin_path: str, player_name: str, player_uuid: str, skin_model: str = "classic") -> Optional[str]:
        try:
            self.httpd = socketserver.ThreadingTCPServer(("127.0.0.1", self.port), LocalSkinHandler)
            self.port = self.httpd.server_address[1]
            self.httpd.skin_config = {  # type: ignore
                "skin_path": skin_path,
                "player_name": player_name,
                "player_uuid": player_uuid,
                "skin_model": skin_model
            }
            self._running = True
            self.thread = threading.Thread(target=self._serve, daemon=True, name="nlc-skin-server")
            self.thread.start()
            logger.info("Local Skin Server active at http://127.0.0.1:%d", self.port)
            return f"http://127.0.0.1:{self.port}"
        except Exception as e:
            logger.error("Failed to start Local Skin Server: %s", e)
            return None

    def _serve(self):
        if self.httpd:
            try:
                self.httpd.serve_forever()
            except Exception as e:
                logger.debug("Skin server terminated: %s", e)
            finally:
                self._running = False

    def stop(self):
        if self.httpd and self._running:
            self._running = False
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
                if self.thread and self.thread.is_alive():
                    self.thread.join(timeout=2.0)
            except Exception as e:
                logger.error("Error stopping skin server: %s", e)
            finally:
                self.httpd = None
                self.thread = None

    def is_running(self) -> bool:
        return self._running and self.thread is not None and self.thread.is_alive()

    def __del__(self):
        self.stop()
