import os

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"


class ApiClient:
    """Thin wrapper around the Kairos REST backend.

    Host address is configurable via the KAIROS_SERVER_URL env var (or
    the constructor arg) rather than hardcoded, since either teammate's
    machine may be hosting the backend for a given session.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or os.environ.get("KAIROS_SERVER_URL", DEFAULT_BASE_URL)

    def health(self) -> dict:
        response = httpx.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()
