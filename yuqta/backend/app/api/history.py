from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.analytics.history import History, build_history
from app.db.session import get_db


router = APIRouter(prefix="/api", tags=["history"])


@router.get("/history", response_model=History)
def meeting_history(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> History:
    """All recent meetings with their action items, decisions, risks and open questions in one place."""
    return build_history(db, limit)
