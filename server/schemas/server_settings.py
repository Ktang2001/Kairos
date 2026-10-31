from pydantic import BaseModel


class ServerInfoPublic(BaseModel):
    """Public, unauthenticated view of the server's identity.

    Deliberately excludes `upload_root` - a local filesystem path on the host
    machine isn't something to expose to arbitrary LAN clients.
    """

    display_name: str
    max_upload_size_bytes: int
    #: Where meetings are held. Public on purpose: the client's Profile page
    #: opens it so people can sign in to Jitsi before their first meeting.
    jitsi_base_url: str

    model_config = {"from_attributes": True}


class ServerSettingsUpdate(BaseModel):
    """Partial update - any field left as None is left unchanged."""

    display_name: str | None = None
    upload_root: str | None = None
    max_upload_size_bytes: int | None = None
    jitsi_base_url: str | None = None
