import http.server
import socketserver
import threading
import json
import uuid
import base64
import time
import os
import urllib.parse
from typing import Any, Optional

class MicrosoftLoginHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Suppress logs

    def do_GET(self):
        # Handle the callback: /?code=...&state=...
        if '?' in self.path:
            query = self.path.split('?', 1)[1]
            params = urllib.parse.parse_qs(query)
            
            if 'code' in params:
                self.server.auth_code = params['code'][0] # type: ignore
                self.server.auth_state = params.get('state', [None])[0] # type: ignore
                
                # Success Page
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                html = """
                <html>
                <head><title>Login Successful</title></head>
                <body style="font-family: 'Segoe UI', sans-serif; text-align: center; padding-top: 50px; background-color: #212121; color: white;">
                    <h1>Login Successful!</h1>
                    <p>You can verify the login in the launcher.</p>
                    <p>This window will close automatically.</p>
                    <script>setTimeout(function(){window.close()}, 2000);</script>
                </body>
                </html>
                """
                self.wfile.write(html.encode("utf-8"))
                return
            
            if 'error' in params:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Login failed or cancelled.")
                return

        self.send_error(404)

class LocalSkinHandler(http.server.BaseHTTPRequestHandler):
    """
    Minimal Yggdrasil-compatible Skin Server for Offline Mode.
    Serves the locally selected skin to the game via authlib-injector.
    """
    # Class-level cache for skin data (shared across instances)
    _skin_cache = {}
    _cache_lock = threading.Lock()
    
    def __init__(self, *args, **kwargs):
        # Instance variables (thread-safe)
        self.skin_path: Optional[str] = None
        self.skin_model = "classic"
        self.player_name = "Player"
        self.player_uuid: Optional[str] = None
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        pass # Suppress server logs
    
    def _get_cached_skin_data(self, filepath) -> Optional[bytes]:
        """Get skin data from cache or read from file."""
        if not filepath or not os.path.exists(filepath):
            return None
        
        try:
            # Check cache with file modification time
            mtime = os.path.getmtime(filepath)
            cache_key = (filepath, mtime)
            
            with self._cache_lock:
                if cache_key in self._skin_cache:
                    return self._skin_cache[cache_key]
                
                # Read file and cache it
                with open(filepath, 'rb') as f:
                    data = f.read()
                
                # Limit cache size to prevent memory bloat
                if len(self._skin_cache) > 20:
                    # Remove oldest entry
                    self._skin_cache.pop(next(iter(self._skin_cache)), None)
                
                self._skin_cache[cache_key] = data
                return data
        except Exception:
            return None

    def do_POST(self):
        # Get instance variables from server
        if hasattr(self.server, 'skin_config'):
            config = self.server.skin_config  # type: ignore
            self.skin_path = config.get('skin_path')
            self.player_name = config.get('player_name', 'Player')
            self.player_uuid = config.get('player_uuid')
            self.skin_model = config.get('skin_model', 'classic')
        
        # Handle Auth/Validation requests blindly to satisfy injector
        if self.path.startswith("/authserver/") or self.path == "/authenticate":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{}')
            return
            
        elif self.path == "/api/profiles/minecraft":
            # Bulk profile lookup
            p_id = self.player_uuid.replace("-", "") if self.player_uuid else uuid.uuid4().hex
            resp = [{
                "id": p_id,
                "name": self.player_name
            }]
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode('utf-8'))
            return

        self.send_error(404)

    def do_GET(self):
        # Get instance variables from server
        if hasattr(self.server, 'skin_config'):
            config = self.server.skin_config  # type: ignore
            self.skin_path = config.get('skin_path')
            self.player_name = config.get('player_name', 'Player')
            self.player_uuid = config.get('player_uuid')
            self.skin_model = config.get('skin_model', 'classic')
        
        # Root check
        if self.path == '/':
            self.send_response(200)
            self.send_header('X-Authlib-Injector-API-Location', '/')
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            resp = {
                "meta": {
                    "serverName": "NLC Skin Handler",
                    "implementationName": "NLC Skin Handler",
                    "implementationVersion": "1.0.0"
                },
                "skinDomains": ["localhost", "127.0.0.1"],
                "signaturePublicKeys": [] 
            }
            self.wfile.write(json.dumps(resp).encode('utf-8'))
            return

        # Profile request: /sessionserver/session/minecraft/profile/<uuid>
        if self.path.startswith("/sessionserver/session/minecraft/profile/"):
            requested_uuid = self.path.split("/")[-1].split("?")[0]
            
            # Check if skin exists
            if not self.skin_path or not os.path.exists(self.skin_path):
                # Fallback to empty profile to prevent crash
                p_id = requested_uuid or (self.player_uuid.replace("-", "") if self.player_uuid else "")
                resp = {
                    "id": p_id,
                    "name": self.player_name,
                    "properties": []
                }
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(resp).encode('utf-8'))
                return

            # Construct Texture Payload
            texture_model = "default" 
            if hasattr(self, 'skin_model') and self.skin_model == 'slim':
                texture_model = "slim"
            
            host = self.headers.get('Host')

            version_tag = "1"
            try:
                mtime = int(os.path.getmtime(self.skin_path))
                version_tag = f"{mtime:x}"
            except Exception:
                pass

            texture_url = f"http://{host}/textures/skin.png?v={version_tag}"

            texture_info: dict[str, Any] = {
                "url": texture_url
            }
            if texture_model == "slim":
                texture_info["metadata"] = {"model": "slim"}

            textures = {
                "timestamp": int(time.time() * 1000),
                "profileId": requested_uuid,
                "profileName": self.player_name,
                "textures": {
                    "SKIN": texture_info
                }
            }
            
            json_textures = json.dumps(textures)
            base64_textures = base64.b64encode(json_textures.encode('utf-8')).decode('utf-8')
            
            response = {
                "id": requested_uuid,
                "name": self.player_name,
                "properties": [
                    {
                        "name": "textures",
                        "value": base64_textures
                    }
                ]
            }
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode('utf-8'))
            return

        # Texture Request
        path_without_query = self.path.split('?')[0]
        if path_without_query == "/textures/skin.png":
            # Use cached skin data
            skin_data = self._get_cached_skin_data(self.skin_path)
            if not skin_data:
                self.send_error(404)
                return
            
            try:
                self.send_response(200)
                self.send_header('Content-type', 'image/png')
                self.send_header('Content-Length', str(len(skin_data)))
                self.send_header('Cache-Control', 'public, max-age=31536000, immutable')
                self.end_headers()
                self.wfile.write(skin_data)
            except Exception:
                self.send_error(500)
            return

        self.send_error(404)

class LocalSkinServer:
    """Manages a local HTTP server for serving skins with proper cleanup."""
    def __init__(self, port=0):
        self.handler = LocalSkinHandler
        self.httpd: Optional[socketserver.ThreadingTCPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.port = port
        self._running = False

    def start(self, skin_path, player_name, player_uuid, skin_model="classic"):
        """Start the skin server with given configuration."""
        try:
            # Create server instance
            self.httpd = socketserver.ThreadingTCPServer(("127.0.0.1", self.port), self.handler)
            self.port = self.httpd.server_address[1]
            
            # Store configuration in server instance (thread-safe)
            self.httpd.skin_config = {  # type: ignore
                'skin_path': skin_path,
                'player_name': player_name,
                'player_uuid': player_uuid,
                'skin_model': skin_model
            }
            
            # Start server thread
            self.thread = threading.Thread(target=self._serve_forever, daemon=True)
            self._running = True
            self.thread.start()
            
            print(f"Local Skin Server started on port {self.port}")
            return f"http://127.0.0.1:{self.port}"
        except Exception as e:
            print(f"Failed to start Local Skin Server: {e}")
            return None
    
    def _serve_forever(self):
        """Server loop with error recovery."""
        if self.httpd:
            try:
                self.httpd.serve_forever()
            except Exception as e:
                print(f"Skin server error: {e}")
            finally:
                self._running = False

    def stop(self):
        """Properly stop the server and clean up resources."""
        if self.httpd and self._running:
            try:
                self._running = False
                self.httpd.shutdown()
                self.httpd.server_close()
                
                # Wait for thread to finish (with timeout)
                if self.thread and self.thread.is_alive():
                    self.thread.join(timeout=2.0)
                
                print("Local Skin Server stopped")
            except Exception as e:
                print(f"Error stopping skin server: {e}")
            finally:
                self.httpd = None
                self.thread = None
    
    def is_running(self):
        """Check if server is currently running."""
        return self._running and self.thread and self.thread.is_alive()
    
    def __del__(self):
        """Cleanup on object destruction."""
        self.stop()
