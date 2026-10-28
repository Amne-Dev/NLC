
import json
import logging
from typing import Any, Dict
from nlc.net.http import get_http_session, DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

class ElyByAuth:
    AUTH_URL = "https://authserver.ely.by/auth/authenticate"

    @staticmethod
    def authenticate(username: str, password: str, timeout=DEFAULT_TIMEOUT) -> Dict[str, Any]:
        if not username or not password:
            return {"error": "Username and password are required"}

        payload = {
            "agent": {
                "name": "Minecraft",
                "version": 1
            },
            "username": username,
            "password": password,
            "requestUser": True
        }

        session = get_http_session()

        try:
            resp = session.post(
                ElyByAuth.AUTH_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=timeout
            )

            if resp.status_code == 200:
                result = resp.json()
                if "accessToken" in result and "selectedProfile" in result:
                    return result
                return {"error": "Invalid authentication response format"}

            try:
                error_data = resp.json()
                msg = error_data.get("errorMessage", error_data.get("error", resp.text))
            except Exception:
                msg = resp.text or f"Status {resp.status_code}"

            return {"error": f"Authentication failed: {msg}"}

        except Exception as e:
            logger.error("Ely.by authentication network error: %s", e)
            return {"error": f"Network error contacting Ely.by: {e}"}
