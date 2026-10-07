from functools import lru_cache

from app.connectors.google.client import GoogleWorkspaceClient
from app.connectors.google.service import ConnectorError, GoogleConnector
from app.core.config import get_settings


@lru_cache
def _connector() -> GoogleConnector:
    settings = get_settings()
    if settings.google_mode == "mock":
        from app.connectors.google.mock import MockGoogleWorkspaceClient

        client: GoogleWorkspaceClient = MockGoogleWorkspaceClient(settings)
    else:
        client = GoogleWorkspaceClient(settings)
    return GoogleConnector(client=client, mode=settings.google_mode, frontend_url=settings.frontend_url)


def get_google_connector() -> GoogleConnector:
    """FastAPI dependency (one connection per process). Override in tests."""
    return _connector()


__all__ = ["ConnectorError", "GoogleConnector", "get_google_connector"]
