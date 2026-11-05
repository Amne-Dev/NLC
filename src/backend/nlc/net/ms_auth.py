
import logging
import time
from typing import Any, Callable, Dict, Optional
from nlc.net.http import get_http_session, DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

import os

# Default Microsoft Azure Application Client ID (User-configured with Prism fallback)
DEFAULT_MSA_CLIENT_ID = "9d6a0dfb-42b0-46a4-a904-1d4557409da7"
PRISM_FALLBACK_CLIENT_ID = "c36a9fb6-4f2a-41ff-90bd-ae7cc92031eb"
MSA_CLIENT_ID = DEFAULT_MSA_CLIENT_ID
MSA_REDIRECT_URI = "https://login.microsoftonline.com/common/oauth2/nativeclient"
DEVICE_CODE_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
TOKEN_URL = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"


def get_msa_client_id() -> str:
    """
    Resolves the active Microsoft Azure Client ID:
    1. Environment variable override (NLC_MSA_CLIENT_ID)
    2. Config provider setting (msa_auth_provider: 'Default(NLC)', 'Prism', 'Custom')
    3. Config file setting (msa_client_id)
    4. Default application Client ID (DEFAULT_MSA_CLIENT_ID)
    """
    env_id = os.environ.get("NLC_MSA_CLIENT_ID", "").strip()
    if env_id:
        return env_id
    try:
        from nlc.storage.config import get_config_manager
        cfg = get_config_manager().load()
        provider = (cfg.get("msa_auth_provider") or "").strip().lower()
        if provider in ("default(nlc)", "default (nlc)", "default", "nlc"):
            return DEFAULT_MSA_CLIENT_ID
        elif provider == "prism":
            return PRISM_FALLBACK_CLIENT_ID
        elif provider == "custom":
            cfg_id = (cfg.get("msa_client_id") or "").strip()
            if cfg_id:
                return cfg_id
            return DEFAULT_MSA_CLIENT_ID

        cfg_id = (cfg.get("msa_client_id") or cfg.get("microsoft_client_id") or "").strip()
        if cfg_id:
            if cfg_id.lower() == "prism" or cfg_id == PRISM_FALLBACK_CLIENT_ID:
                return PRISM_FALLBACK_CLIENT_ID
            return cfg_id
    except Exception:
        pass
    return DEFAULT_MSA_CLIENT_ID


def get_msa_redirect_uri() -> str:
    """
    Resolves the active Microsoft OAuth redirect URI:
    1. Environment variable override (NLC_MSA_REDIRECT_URI)
    2. Config file setting (msa_redirect_uri)
    3. Default native client URI
    """
    env_uri = os.environ.get("NLC_MSA_REDIRECT_URI", "").strip()
    if env_uri:
        return env_uri
    try:
        from nlc.storage.config import get_config_manager
        cfg = get_config_manager().load()
        cfg_uri = (cfg.get("msa_redirect_uri") or cfg.get("microsoft_redirect_uri") or "").strip()
        if cfg_uri:
            return cfg_uri
    except Exception:
        pass
    return MSA_REDIRECT_URI

import http.server
import urllib.parse

class MicrosoftLoginHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if '?' in self.path:
            query = self.path.split('?', 1)[1]
            params = urllib.parse.parse_qs(query)
            if 'code' in params:
                self.server.auth_code = params['code'][0]  # type: ignore
                self.server.auth_state = params.get('state', [None])[0]  # type: ignore
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                html = (
                    "<html>\n"
                    "<head><title>Login Successful</title></head>\n"
                    "<body style=\"font-family: 'Segoe UI', sans-serif; text-align: center; padding-top: 50px; background-color: #212121; color: white;\">\n"
                    "    <h1>Login Successful!</h1>\n"
                    "    <p>You can verify the login in the launcher.</p>\n"
                    "    <p>This window will close automatically.</p>\n"
                    "    <script>setTimeout(function(){window.close()}, 2000);</script>\n"
                    "</body>\n"
                    "</html>\n"
                )
                self.wfile.write(html.encode("utf-8"))
                return
            if 'error' in params:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Login failed or cancelled.")
                return
        self.send_error(404)

class MicrosoftDeviceAuth:
    def __init__(self, client_id: Optional[str] = None):
        self.client_id = client_id or get_msa_client_id()

    def request_device_code(self, timeout=DEFAULT_TIMEOUT) -> Dict[str, Any]:
        session = get_http_session()
        payload = {
            "client_id": self.client_id,
            "scope": "XboxLive.signin offline_access"
        }
        resp = session.post(DEVICE_CODE_URL, data=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def poll_token(
        self,
        device_code: str,
        interval: int = 5,
        expires_in: int = 900,
        cancel_event=None,
        _on_status: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        session = get_http_session()
        payload = {
            "grant_type": "device_code",
            "client_id": self.client_id,
            "device_code": device_code
        }

        deadline = time.monotonic() + expires_in

        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                return {"error": "cancelled", "message": "Login was cancelled."}

            time.sleep(interval)

            if cancel_event is not None and cancel_event.is_set():
                return {"error": "cancelled", "message": "Login was cancelled."}

            try:
                resp = session.post(TOKEN_URL, data=payload, timeout=(5.0, 15.0))
                if resp.status_code == 200:
                    return resp.json()

                err_json = resp.json()
                err_code = err_json.get("error")

                if err_code == "authorization_pending":
                    continue
                elif err_code == "slow_down":
                    interval += 2
                elif err_code == "expired_token":
                    return {"error": "expired", "message": "The login code expired. Please try again."}
                else:
                    return {"error": err_code, "message": err_json.get("error_description", "Unknown error")}
            except Exception as e:
                logger.warning("Transient error during token polling: %s", type(e).__name__)

        return {"error": "timeout", "message": "Login timed out."}
