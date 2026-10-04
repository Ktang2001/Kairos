"""Trust-on-first-use (TOFU) certificate pinning for self-signed server certs.

See server/tls.py for the server side. The client fetches a server's certificate
once (deliberately unverified - there's no CA to check against) and pins it on
that saved server entry (see KnownServer.cert_pem in
client/viewmodels/server_list_viewmodel.py); every later connection verifies
against exactly that pinned certificate, so the TLS handshake itself fails closed
if the server ever presents a different one.
"""

import ssl


def fetch_server_cert_pem(host: str, port: int, timeout: float = 5.0) -> str:
    """One-time, deliberately unverified connection just to retrieve the server's
    certificate for pinning. Can raise OSError/ssl.SSLError if unreachable."""
    return ssl.get_server_certificate((host, port), timeout=timeout)


def build_pinned_ssl_context(cert_pem: str) -> ssl.SSLContext:
    """Trust ONLY this exact certificate - any other cert (even a real CA-signed
    one) fails the handshake. Hostname checking is off because this pins the
    literal leaf certificate rather than validating a name against a CA chain -
    the LAN IP a saved server resolves to can change without the pinned identity
    changing."""
    context = ssl.create_default_context(cadata=cert_pem)
    context.check_hostname = False
    return context
