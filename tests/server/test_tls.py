from server.tls import ensure_server_cert, fingerprint_sha256


def test_ensure_server_cert_creates_files_with_safe_permissions(tmp_path) -> None:
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"

    ensure_server_cert(cert_path, key_path)

    assert cert_path.exists()
    assert key_path.exists()
    assert oct(key_path.stat().st_mode)[-3:] == "600"


def test_ensure_server_cert_is_idempotent(tmp_path) -> None:
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"

    ensure_server_cert(cert_path, key_path)
    original_cert_bytes = cert_path.read_bytes()
    original_key_bytes = key_path.read_bytes()

    ensure_server_cert(cert_path, key_path)

    assert cert_path.read_bytes() == original_cert_bytes
    assert key_path.read_bytes() == original_key_bytes


def test_fingerprint_sha256_is_stable_and_formatted(tmp_path) -> None:
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    ensure_server_cert(cert_path, key_path)

    first = fingerprint_sha256(cert_path)
    second = fingerprint_sha256(cert_path)

    assert first == second
    parts = first.split(":")
    assert len(parts) == 32  # SHA-256 digest
    assert all(len(p) == 2 for p in parts)


def test_different_certs_have_different_fingerprints(tmp_path) -> None:
    cert_a, key_a = tmp_path / "a_cert.pem", tmp_path / "a_key.pem"
    cert_b, key_b = tmp_path / "b_cert.pem", tmp_path / "b_key.pem"
    ensure_server_cert(cert_a, key_a)
    ensure_server_cert(cert_b, key_b)

    assert fingerprint_sha256(cert_a) != fingerprint_sha256(cert_b)
