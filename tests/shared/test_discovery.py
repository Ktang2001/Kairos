import json

from shared.discovery import DISCOVERY_PROTOCOL_VERSION, decode_announcement, encode_announcement


def test_round_trip() -> None:
    packet = encode_announcement("abc123", "Kairos Server", 8000)

    decoded = decode_announcement(packet)

    assert decoded is not None
    assert decoded.instance_id == "abc123"
    assert decoded.name == "Kairos Server"
    assert decoded.port == 8000


def test_decode_rejects_garbage_bytes() -> None:
    assert decode_announcement(b"not json at all") is None


def test_decode_rejects_non_utf8_bytes() -> None:
    assert decode_announcement(b"\xff\xfe\x00\x01") is None


def test_decode_rejects_wrong_protocol_version() -> None:
    payload = json.dumps(
        {"proto": DISCOVERY_PROTOCOL_VERSION + 1, "id": "x", "name": "y", "port": 1}
    ).encode()

    assert decode_announcement(payload) is None


def test_decode_rejects_missing_fields() -> None:
    payload = json.dumps({"proto": DISCOVERY_PROTOCOL_VERSION, "id": "x"}).encode()

    assert decode_announcement(payload) is None


def test_decode_rejects_wrong_field_types() -> None:
    payload = json.dumps(
        {"proto": DISCOVERY_PROTOCOL_VERSION, "id": "x", "name": "y", "port": "not-an-int"}
    ).encode()

    assert decode_announcement(payload) is None


def test_decode_rejects_foreign_json_shape() -> None:
    payload = json.dumps({"hello": "world"}).encode()

    assert decode_announcement(payload) is None
