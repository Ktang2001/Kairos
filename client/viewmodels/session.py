"""Who is signed in, as the Teams and Users pages need it."""

from dataclasses import dataclass

from client.api_client import ApiClient


@dataclass
class Session:
    """A signed-in user: the client holding their token, and who they are."""

    client: ApiClient
    #: ``{"id", "name", "email", "role"}`` as the server reports it (/people/me).
    user: dict
