"""Encrypted storage for connector credentials (e.g. the Google OAuth tokens), so connections survive restarts.

Values are JSON, encrypted with Fernet (AES-128-CBC + HMAC-SHA256) using TOKEN_ENCRYPTION_KEY. The key lives
only in the environment, so a copy of the database alone does not reveal the tokens. Without a key nothing is
stored and connections are kept in memory only, as before.
"""

from collections.abc import Callable
import json
import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.db.models import ConnectorCredential


logger = logging.getLogger(__name__)


class CredentialStore:
    def __init__(self, key: str, session_factory: Callable[[], Session]):
        self._fernet = Fernet(key.encode())  # ValueError for a malformed key
        self._sessions = session_factory

    def load(self, name: str) -> dict | None:
        try:
            with self._sessions() as db:
                row = db.get(ConnectorCredential, name)
                if row is None:
                    return None
                return json.loads(self._fernet.decrypt(row.ciphertext.encode()))
        except InvalidToken:
            logger.warning("Stored credentials %r cannot be decrypted (TOKEN_ENCRYPTION_KEY changed?); ignoring them", name)
        except Exception:  # noqa: BLE001 - a broken store must never stop the app; the user can reconnect
            logger.exception("Could not load stored credentials %r", name)
        return None

    def save(self, name: str, value: dict | None) -> None:
        """Stores (or with None, deletes) the credentials."""
        try:
            with self._sessions() as db:
                row = db.get(ConnectorCredential, name)
                if value is None:
                    if row is not None:
                        db.delete(row)
                else:
                    ciphertext = self._fernet.encrypt(json.dumps(value).encode()).decode()
                    if row is None:
                        db.add(ConnectorCredential(name=name, ciphertext=ciphertext))
                    else:
                        row.ciphertext = ciphertext
                db.commit()
        except Exception:  # noqa: BLE001 - the connection still works in memory
            logger.exception("Could not store credentials %r", name)


def build_credential_store(key: str, session_factory: Callable[[], Session]) -> CredentialStore | None:
    if not key:
        return None
    try:
        return CredentialStore(key, session_factory)
    except ValueError:
        logger.warning("TOKEN_ENCRYPTION_KEY is not a valid key; connections are kept in memory only")
        return None
