"""The client's connection to the server. ``ApiClient`` (in client.py) makes every HTTP request;
screens never call httpx themselves.
"""

from client.api_client.client import (
    ApiClient,
    ApiError,
    is_connection_error,
    normalise_base_url,
)

__all__ = ["ApiClient", "ApiError", "is_connection_error", "normalise_base_url"]
