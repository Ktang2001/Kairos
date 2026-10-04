import io
from pathlib import Path

from fastapi.testclient import TestClient

from server.models.server_settings import ServerSettings
from tests.server.conftest import auth_headers


def _start_direct_conversation(client: TestClient, alice, bob) -> dict:
    return client.post(
        "/conversations/direct", json={"other_user_id": bob.id}, headers=auth_headers(alice.id)
    ).json()


def test_upload_and_download_roundtrip(client: TestClient, make_user) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    conversation = _start_direct_conversation(client, alice, bob)

    upload = client.post(
        f"/conversations/{conversation['id']}/attachments",
        files={"file": ("notes.txt", io.BytesIO(b"hello world"), "text/plain")},
        headers=auth_headers(alice.id),
    )
    assert upload.status_code == 200
    body = upload.json()
    assert len(body["attachments"]) == 1
    attachment = body["attachments"][0]
    assert attachment["original_filename"] == "notes.txt"
    assert "stored_filename" not in attachment

    download = client.get(f"/attachments/{attachment['id']}/download", headers=auth_headers(bob.id))
    assert download.status_code == 200
    assert download.content == b"hello world"
    assert "notes.txt" in download.headers["content-disposition"]


def test_upload_rejects_path_traversal_filename(client: TestClient, make_user, db_session) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    conversation = _start_direct_conversation(client, alice, bob)

    upload = client.post(
        f"/conversations/{conversation['id']}/attachments",
        files={"file": ("../../evil.sh", io.BytesIO(b"#!/bin/sh\necho pwned"), "text/plain")},
        headers=auth_headers(alice.id),
    )

    assert upload.status_code == 200

    settings = db_session.get(ServerSettings, 1)
    upload_root = Path(settings.upload_root).expanduser().resolve()
    attachment = upload.json()["attachments"][0]
    assert attachment["original_filename"] == "../../evil.sh"

    stored_files = list(upload_root.iterdir())
    assert len(stored_files) == 1
    assert stored_files[0].parent == upload_root
    assert not (upload_root.parent / "evil.sh").exists()
    assert not (upload_root.parent.parent / "evil.sh").exists()


def test_upload_rejects_oversized_file(client: TestClient, make_user, db_session) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    conversation = _start_direct_conversation(client, alice, bob)

    settings = db_session.get(ServerSettings, 1)
    settings.max_upload_size_bytes = 10
    db_session.commit()

    upload = client.post(
        f"/conversations/{conversation['id']}/attachments",
        files={"file": ("big.bin", io.BytesIO(b"x" * 1000), "application/octet-stream")},
        headers=auth_headers(alice.id),
    )

    assert upload.status_code == 413

    upload_root = Path(settings.upload_root).expanduser().resolve()
    assert list(upload_root.iterdir()) == []

    messages = client.get(
        f"/conversations/{conversation['id']}/messages", headers=auth_headers(alice.id)
    ).json()
    assert messages == []


def test_download_denied_for_non_participant(client: TestClient, make_user) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    mallory = make_user("Mallory", "mallory@example.com")
    conversation = _start_direct_conversation(client, alice, bob)

    upload = client.post(
        f"/conversations/{conversation['id']}/attachments",
        files={"file": ("notes.txt", io.BytesIO(b"secret"), "text/plain")},
        headers=auth_headers(alice.id),
    ).json()
    attachment_id = upload["attachments"][0]["id"]

    response = client.get(
        f"/attachments/{attachment_id}/download", headers=auth_headers(mallory.id)
    )
    assert response.status_code == 403
