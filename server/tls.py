"""Self-signed TLS for the LAN server - no paid CA needed.

Trust model is trust-on-first-use (TOFU), the same one SSH host keys use: the
client pins this exact certificate the first time it connects (see
client/views/connect_window.py's cert-pinning flow) and every later request fails
closed if a different certificate is ever presented. The one gap TOFU can't close
is the very first connection to a brand-new server - that's a known, accepted
limitation of this trust model, not a bug.
"""

import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CERT_VALIDITY = datetime.timedelta(days=3650)


def ensure_server_cert(cert_path: Path, key_path: Path) -> None:
    """Generate a self-signed cert+key at these paths if they don't already exist.

    Idempotent - calling this on every server start only pays the generation cost
    once per machine. The cert's hostname/IP fields don't matter (the client pins
    the exact cert rather than checking hostnames - see ApiClient's SSL context),
    so one fixed subject name is fine even though the LAN IP can change.
    """
    if cert_path.exists() and key_path.exists():
        return

    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Kairos Server")])
    now = datetime.datetime.now(datetime.UTC)

    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + CERT_VALIDITY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256())
    )

    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))


def fingerprint_sha256(cert_path: Path) -> str:
    """A human-comparable fingerprint (e.g. for out-of-band verification between
    teammates), stronger-than-TOFU assurance if they choose to compare it."""
    certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
    digest = certificate.fingerprint(hashes.SHA256())
    return ":".join(f"{b:02X}" for b in digest)
