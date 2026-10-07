from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.api.bots import router as bots_router
from app.api.customers import router as customers_router
from app.api.dashboard import router as dashboard_router
from app.api.google import router as google_router
from app.api.health import router as health_router
from app.api.meetings import router as meetings_router
from app.api.system import router as system_router
from app.connectors.meeting_bot import BotError
from app.core.auth import require_service_token
from app.core.config import get_settings
from app.core.logging import configure_logging


settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("yuqta")


def _start_auto_import():
    """Background polling for finished Meet meetings (not in tests; they call run_once directly)."""
    from app.connectors.google import get_google_connector
    from app.db.session import new_session
    from app.plugins.llm.factory import build_llm_provider
    from app.workflows.auto_import import AutoImportWorker, auto_importer

    connector = get_google_connector()
    if settings.app_env == "test" or not connector.client.settings.auto_import_configured:
        return None
    worker = AutoImportWorker(
        auto_importer,
        connector.client.settings.auto_import_poll_seconds,
        lambda: auto_importer.run_once(connector, new_session, lambda: build_llm_provider(get_settings())),
    )
    worker.start()
    return worker


def _start_meeting_bots():
    """Background polling of notetaker bots in live calls (not in tests; they call run_once directly)."""
    from app.connectors.meeting_bot import BotError, get_meeting_bot_client
    from app.db.session import new_session
    from app.plugins.llm.factory import build_llm_provider
    from app.workflows.auto_import import AutoImportWorker
    from app.workflows.meeting_bot import meeting_bot_poller

    if settings.app_env == "test":
        return None
    try:
        client = get_meeting_bot_client()
    except BotError as error:
        logger.warning("Meeting bots disabled: %s", error)
        return None
    worker = AutoImportWorker(
        None,
        settings.bot_poll_seconds,
        lambda: meeting_bot_poller.run_once(client, new_session, lambda: build_llm_provider(get_settings())),
        name="meeting-bots",
    )
    worker.start()
    return worker


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "Yuqta API starting (env=%s, stt=%s, llm=%s, google=%s, bot=%s, api_auth=%s)",
        settings.app_env,
        settings.stt_provider,
        settings.llm_provider,
        settings.google_mode,
        settings.meeting_bot_provider,
        "on" if settings.api_auth_token else "OFF",
    )
    if not settings.api_auth_token and settings.app_env == "production":
        logger.warning("API_AUTH_TOKEN is not set: the API is unauthenticated")
    workers = [w for w in (_start_auto_import(), _start_meeting_bots()) if w]
    yield
    for worker in workers:
        worker.stop()
    logger.info("Yuqta API stopped")


app = FastAPI(title="Yuqta API", version="0.1.0", lifespan=lifespan)
app.middleware("http")(require_service_token)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(customers_router)
app.include_router(bots_router)
app.include_router(meetings_router)
app.include_router(dashboard_router)
app.include_router(google_router)
app.include_router(system_router)


@app.exception_handler(OperationalError)
async def database_unavailable(request: Request, error: OperationalError) -> JSONResponse:
    logger.error("Database unavailable on %s %s: %s", request.method, request.url.path, error.orig)
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


@app.exception_handler(BotError)
async def meeting_bot_error(request: Request, error: BotError) -> JSONResponse:
    # e.g. MEETING_BOT_PROVIDER=recall without RECALL_API_KEY, raised while building the client.
    return JSONResponse(status_code=error.status_code, content={"detail": str(error)})


@app.exception_handler(Exception)
async def unhandled_error(request: Request, error: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
