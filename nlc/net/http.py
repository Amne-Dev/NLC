"""
nlc.net.http - Centralized HTTP session with timeouts and exponential retry backoff
"""

import logging
import requests
from urllib3.util import Retry
from requests.adapters import HTTPAdapter
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT: Tuple[float, float] = (5.0, 30.0)  # (connect_timeout, read_timeout)
USER_AGENT = "NLC-Launcher/3.0.5 (Minecraft; +https://github.com/Amne-Dev/New-launcher)"

_GLOBAL_SESSION: Optional[requests.Session] = None

class TimeoutHTTPAdapter(HTTPAdapter):
    """Custom HTTPAdapter that enforces a default timeout if none is passed."""
    def __init__(self, *args, default_timeout=DEFAULT_TIMEOUT, **kwargs):
        self.default_timeout = default_timeout
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = self.default_timeout
        return super().send(request, **kwargs)

def get_http_session() -> requests.Session:
    """Returns the shared resilient requests.Session."""
    global _GLOBAL_SESSION
    if _GLOBAL_SESSION is None:
        session = requests.Session()
        session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        })

        # Retry strategy for idempotent operations (GET, HEAD, OPTIONS)
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )

        adapter = TimeoutHTTPAdapter(max_retries=retry_strategy, default_timeout=DEFAULT_TIMEOUT)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        _GLOBAL_SESSION = session

    return _GLOBAL_SESSION
