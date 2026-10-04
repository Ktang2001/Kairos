"""Tests for the security protections that apply to every route.

6  request size limit (uploads have their own)   12 API docs only from the host computer
9  oversized ids                                 14 no --password on the seed command line
10 invisible characters stripped from team names

Sign-in protections (password rules, the login cooldown, two-factor codes) are
the Kaleb branch's and are tested in test_auth.py and test_verification_service.py.
"""

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from server import seed
from server.api.protection import MAX_BODY_BYTES, UNLIMITED_PATHS
from server.main import app
from shared.text_rules import clean_display_text

# ================================================= 6. request size limit


def test_a_body_over_the_limit_is_refused_by_its_declared_length(client: TestClient) -> None:
    big = b'{"email":"a@b.co","password":"' + b"x" * MAX_BODY_BYTES + b'"}'
    response = client.post("/auth/login", content=big, headers={"content-type": "application/json"})
    assert response.status_code == 413


def test_a_streamed_body_without_a_length_is_cut_off(client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        yield b'{"email":"a@b.co","password":"'
        for _ in range(3 * MAX_BODY_BYTES // 65536):
            yield b"x" * 65536
        yield b'"}'

    response = client.post(
        "/auth/login", content=chunks(), headers={"content-type": "application/json"}
    )
    assert response.status_code == 413


def test_a_body_just_under_the_limit_is_still_processed(client: TestClient) -> None:
    body = b'{"email":"a@b.co","password":"' + b"x" * (MAX_BODY_BYTES - 100) + b'"}'
    response = client.post(
        "/auth/login", content=body, headers={"content-type": "application/json"}
    )
    # Read and processed in full (an unknown account), not refused as too large.
    assert response.status_code == 401


def test_a_bogus_content_length_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        content=b"{}",
        headers={"content-type": "application/json", "content-length": "lots"},
    )
    assert response.status_code == 400


def test_only_the_attachment_upload_route_skips_the_size_limit() -> None:
    # It enforces the server's own, admin-configurable upload limit instead.
    assert UNLIMITED_PATHS.fullmatch("/conversations/12/attachments")
    assert not UNLIMITED_PATHS.fullmatch("/conversations/12/attachments/extra")
    assert not UNLIMITED_PATHS.fullmatch("/teams")
    assert not UNLIMITED_PATHS.fullmatch("/messages")


# ================================================== 9. oversized ids


@pytest.mark.parametrize("big", ["9223372036854775808", "99999999999999999999"])
def test_ids_beyond_64_bits_are_rejected_not_crashed(
    client: TestClient, user_headers: Callable[..., dict[str, str]], big: str
) -> None:
    headers = user_headers()
    for method, url in (("GET", f"/teams/{big}"), ("DELETE", f"/teams/{big}/members/1")):
        response = client.request(method, url, headers=headers)
        assert response.status_code == 422, url
        assert response.json()["detail"] == "A number in the request is too large"


def test_the_largest_64_bit_id_is_just_not_found(
    client: TestClient, user_headers: Callable[..., dict[str, str]]
) -> None:
    assert client.get("/teams/9223372036854775807", headers=user_headers()).status_code == 404


# ================================ 10. invisible characters in team names


def test_team_names_are_cleaned(client: TestClient, lead) -> None:
    team = client.post("/teams", json={"name": "Alp\u200bha"}, headers=lead.headers).json()
    assert team["name"] == "Alpha"
    assert (
        client.post("/teams", json={"name": "\u202eAlpha"}, headers=lead.headers).status_code == 409
    )
    renamed = client.patch(
        f"/teams/{team['id']}", json={"name": "\u202eOmega"}, headers=lead.headers
    ).json()
    assert renamed["name"] == "Omega"


@pytest.mark.parametrize("value", [None, 5, ["x"], {"a": 1}])
def test_cleaning_leaves_non_text_alone_for_validation_to_reject(value: object) -> None:
    # Iterating a number would raise TypeError, i.e. a 500 instead of a 422.
    assert clean_display_text(value) == value


def test_a_non_text_team_name_is_a_422_not_a_crash(client: TestClient, lead) -> None:
    response = client.post("/teams", json={"name": 123}, headers=lead.headers)
    assert response.status_code == 422


# ============================================ 12. docs only from the host


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_are_hidden_from_other_computers(client: TestClient, path: str) -> None:
    # TestClient's default address is "testclient": not this computer.
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
def test_docs_work_on_the_host_itself(address: str) -> None:
    # No ``with``: that would run start-up against the development database.
    # The docs routes need no database, so start-up is not required here.
    local = TestClient(app, client=(address, 50000))
    assert local.get("/openapi.json").status_code == 200
    assert local.get("/docs").status_code == 200


def test_hiding_docs_does_not_affect_the_api(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


# ================================================ 14. seed command line


def test_the_seed_script_has_no_password_option() -> None:
    with pytest.raises(SystemExit):
        seed.main(["--password", "tangerine-ladder-77"])


def test_the_seed_script_rejects_a_weak_password_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KAIROS_ADMIN_PASSWORD", "password123")
    with pytest.raises(SystemExit):
        seed.main(["--email", "admin@example.com"])
