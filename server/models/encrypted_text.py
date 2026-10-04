from sqlalchemy.types import LargeBinary, TypeDecorator

from server import crypto


class EncryptedText(TypeDecorator):
    """Transparently Fernet-encrypts a text column at rest (see server/crypto.py).

    Stored as LargeBinary (a Fernet token is bytes, not valid text) - every
    existing call site keeps reading/writing a plain Python str, unaware this
    column is encrypted on disk. `cache_ok = True` since this type has no
    per-instance state that would make SQLAlchemy's statement cache unsafe.
    """

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> bytes | None:
        if value is None:
            return None
        return crypto.encrypt_text(crypto.get_default_key(), value)

    def process_result_value(self, value: bytes | None, dialect) -> str | None:
        if value is None:
            return None
        return crypto.decrypt_text(crypto.get_default_key(), value)
