import pytest
from fastapi.testclient import TestClient

from app.core import config


@pytest.fixture
def secured(seeded_api: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(config.get_settings(), "api_auth_token", "s3cret-token")
    return seeded_api


def test_api_open_when_no_token_configured(seeded_api: TestClient) -> None:
    assert seeded_api.get("/api/customers").status_code == 200


def test_api_requires_bearer_token(secured: TestClient) -> None:
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic s3cret-token"}, {"Authorization": "s3cret-token"}):
        response = secured.get("/api/customers", headers=headers)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
    assert secured.post("/api/meetings/sample").status_code == 401
    assert secured.get("/api/customers", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200


def test_public_paths_stay_open(secured: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import health as health_module

    monkeypatch.setattr(health_module, "check_database", lambda: True)
    assert secured.get("/health").status_code == 200
    # The OAuth callback is public but rejects anything without a valid state.
    callback = secured.get("/auth/google/callback?code=x&state=forged", follow_redirects=False)
    assert callback.status_code == 302 and "google_error=invalid_state" in callback.headers["location"]


def test_system_info_never_exposes_keys(seeded_api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.get_settings(), "llm_api_key", "sk-very-secret")
    monkeypatch.setattr(config.get_settings(), "deepgram_api_key", "dg-very-secret")
    info = seeded_api.get("/api/system").json()
    assert info["stt_provider"] == "mock" and info["llm_provider"] == "mock" and info["google_mode"] == "mock"
    assert "secret" not in str(info)
