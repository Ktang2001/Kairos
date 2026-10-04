from fastapi.testclient import TestClient

from tests.server.conftest import auth_headers


def test_get_server_info_is_public_no_auth_needed(client: TestClient) -> None:
    response = client.get("/server/info")

    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Test Server"
    assert "upload_root" not in body


def test_put_server_info_requires_global_admin_role(client: TestClient, make_user) -> None:
    member = make_user("Bob", "bob@example.com", role_name="member")
    admin = make_user("Alice", "alice@example.com", role_name="admin")

    denied = client.put(
        "/server/info", json={"display_name": "Bob's Server"}, headers=auth_headers(member.token)
    )
    assert denied.status_code == 403

    allowed = client.put(
        "/server/info", json={"display_name": "Alice's Server"}, headers=auth_headers(admin.token)
    )
    assert allowed.status_code == 200
    assert allowed.json()["display_name"] == "Alice's Server"

    confirm = client.get("/server/info")
    assert confirm.json()["display_name"] == "Alice's Server"


def test_put_server_info_rejects_unwritable_upload_root(
    client: TestClient, make_user, tmp_path
) -> None:
    admin = make_user("Alice", "alice@example.com", role_name="admin")
    unwritable_file = tmp_path / "not_a_directory"
    unwritable_file.write_text("occupying this path")

    response = client.put(
        "/server/info",
        json={"upload_root": str(unwritable_file / "uploads")},
        headers=auth_headers(admin.token),
    )

    assert response.status_code == 400

    info = client.get("/server/info").json()
    assert info["display_name"] == "Test Server"


def test_put_server_info_accepts_writable_upload_root(
    client: TestClient, make_user, tmp_path
) -> None:
    """Happy path for the branch test_..._rejects_unwritable_upload_root only
    exercises the failure side of: previously nothing confirmed a valid,
    writable upload_root is actually accepted and persisted."""
    admin = make_user("Alice", "alice@example.com", role_name="admin")
    new_root = tmp_path / "new_uploads"

    response = client.put(
        "/server/info", json={"upload_root": str(new_root)}, headers=auth_headers(admin.token)
    )

    assert response.status_code == 200
    assert new_root.is_dir()
    # Not exposed on the public schema (see ServerInfoPublic), but the write-check
    # probe file must not have been left behind.
    assert list(new_root.iterdir()) == []


def test_put_server_info_rejects_empty_display_name(client: TestClient, make_user) -> None:
    admin = make_user("Alice", "alice@example.com", role_name="admin")

    response = client.put(
        "/server/info", json={"display_name": "   "}, headers=auth_headers(admin.token)
    )

    assert response.status_code == 400

    info = client.get("/server/info").json()
    assert info["display_name"] == "Test Server"


def test_put_server_info_accepts_positive_max_upload_size(client: TestClient, make_user) -> None:
    admin = make_user("Alice", "alice@example.com", role_name="admin")

    response = client.put(
        "/server/info",
        json={"max_upload_size_bytes": 5 * 1024 * 1024},
        headers=auth_headers(admin.token),
    )

    assert response.status_code == 200
    assert response.json()["max_upload_size_bytes"] == 5 * 1024 * 1024


def test_put_server_info_rejects_non_positive_max_upload_size(
    client: TestClient, make_user
) -> None:
    admin = make_user("Alice", "alice@example.com", role_name="admin")

    response = client.put(
        "/server/info", json={"max_upload_size_bytes": 0}, headers=auth_headers(admin.token)
    )

    assert response.status_code == 400

    info = client.get("/server/info").json()
    assert info["max_upload_size_bytes"] == 10 * 1024 * 1024
