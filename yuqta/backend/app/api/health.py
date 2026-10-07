from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.db.session import check_database
from app.schemas.health import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    # The API is alive even if Postgres is down; the database field reports that separately.
    return HealthResponse(
        status="ok",
        app_env=settings.app_env,
        database="ok" if check_database() else "unavailable",
    )
