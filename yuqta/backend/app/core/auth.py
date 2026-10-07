"""Service-token protection for the API.

When API_AUTH_TOKEN is set, every /api/* request must send `Authorization: Bearer <token>`.
Only the Next.js server holds the token; browsers never call /api/* directly. /health and
the Google OAuth callback stay public (Google redirects the browser to the callback, and it
only accepts a state issued through the protected API).
"""

import secrets

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings


def _authorized(request: Request, token: str) -> bool:
    scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
    return scheme.lower() == "bearer" and secrets.compare_digest(supplied.encode(), token.encode())


async def require_service_token(request: Request, call_next):
    token = get_settings().api_auth_token
    if token and request.url.path.startswith("/api/") and not _authorized(request, token):
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or invalid API token."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)
