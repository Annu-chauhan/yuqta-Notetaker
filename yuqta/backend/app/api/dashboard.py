from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.dashboard import DashboardSpec
from app.workflows.analyze_meeting import load_dashboard


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/latest", response_model=DashboardSpec)
def latest_dashboard(db: Session = Depends(get_db)) -> DashboardSpec:
    """The dashboard updated by the most recent meeting analysis."""
    spec = load_dashboard(db)
    if spec is None:
        raise HTTPException(status_code=404, detail="No dashboard yet. Analyze a meeting first.")
    return spec
