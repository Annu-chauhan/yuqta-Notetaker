"""Encrypted connector credentials: the Google connection survives a backend restart."""

from base64 import urlsafe_b64encode
import os
from urllib.parse import urlparse

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.connectors.google import GoogleConnector, get_google_connector
from app.connectors.google.mock import MockGoogleWorkspaceClient
from app.core.config import Settings, get_settings
from app.db.credentials import CredentialStore, build_credential_store
from app.db.models import ConnectorCredential
from app.main import app


def _key() -> str:
    return urlsafe_b64encode(os.urandom(32)).decode()


def test_values_are_encrypted_and_round_trip(memory_db) -> None:
    store = CredentialStore(_key(), memory_db)
    store.save("google:live", {"tokens": {"refresh_token": "very-secret"}})
    with memory_db() as db:
        stored = db.scalars(select(ConnectorCredential)).one()
    assert "very-secret" not in stored.ciphertext
    assert store.load("google:live") == {"tokens": {"refresh_token": "very-secret"}}
    store.save("google:live", None)
    assert store.load("google:live") is None


def test_wrong_or_missing_key(memory_db) -> None:
    CredentialStore(_key(), memory_db).save("google:live", {"a": 1})
    assert CredentialStore(_key(), memory_db).load("google:live") is None  # another key cannot decrypt it
    assert build_credential_store("", memory_db) is None
    assert build_credential_store("not-a-key", memory_db) is None


def _connector(store) -> GoogleConnector:
    settings = Settings(_env_file=None, google_redirect_uri="http://backend.test/auth/google/callback",
                        frontend_url="http://frontend.test", sample_transcript_path=get_settings().sample_transcript_path)
    return GoogleConnector(client=MockGoogleWorkspaceClient(settings), mode="mock", frontend_url=settings.frontend_url, store=store)


@pytest.fixture
def restore_overrides():
    yield
    app.dependency_overrides.pop(get_google_connector, None)


def test_connection_survives_restart_and_disconnect_forgets_it(api: TestClient, memory_db, restore_overrides) -> None:
    store = CredentialStore(_key(), memory_db)
    first = _connector(store)
    app.dependency_overrides[get_google_connector] = lambda: first
    url = api.post("/api/google/connect", json={}).json()["authorization_url"]
    api.get(f"/auth/google/callback?{urlparse(url).query}", follow_redirects=False)
    assert first.connected

    restarted = _connector(store)  # a new process: same database and key
    assert restarted.connected and restarted.status()["account"]["email"] == first.status()["account"]["email"]
    assert restarted.events(1, 1)  # the restored tokens work

    restarted.disconnect()
    assert not _connector(store).connected



def test_all_accounts_survive_restart_and_old_format_loads(memory_db) -> None:
    store = CredentialStore(_key(), memory_db)
    tokens = {"access_token": "a", "refresh_token": "r", "expires_at": 9e12, "scope": ""}
    store.save("google:mock", {"accounts": [
        {"tokens": tokens, "account": {"email": "one@example.com"}, "account_id": "1"},
        {"tokens": tokens, "account": {"email": "two@example.com"}, "account_id": "2"},
    ]})
    assert [a["email"] for a in _connector(store).accounts()] == ["one@example.com", "two@example.com"]

    store.save("google:mock", {"tokens": tokens, "account": {"email": "legacy@example.com"}, "account_id": "9"})
    assert [a["email"] for a in _connector(store).accounts()] == ["legacy@example.com"]  # pre-multi-account format
