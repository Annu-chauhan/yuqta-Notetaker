"""Deterministic analysis: understand -> correlate -> KPI -> RCA -> recommendations -> dashboard -> store.

Meeting-first: the meeting's own intelligence (summary, topics, decisions, tasks, risks, questions,
participation) is always produced. The business layer (KPIs, revenue root causes, "not discussed"
accounts) is added only when business data exists AND the meeting discussed customers or revenue.

Re-running replaces the meeting's previous insights and dashboard, so analysis is idempotent.
"""

import logging
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analytics import business_data as data
from app.analytics.correlation import correlate
from app.analytics.kpi import compute_kpis
from app.analytics.meeting import discusses_business, meeting_headline, meeting_recommendations, participation
from app.analytics.rca import revenue_root_causes, summarize
from app.analytics.recommendations import recommend
from app.dashboard.spec import build_dashboard_spec
from app.db import meetings as repo
from app.db.models import DashboardSpec as DashboardSpecRow
from app.db.models import Meeting, MeetingInsight
from app.plugins.llm.base import LLMError, LLMProvider
from app.schemas.analysis import KPI, AnalysisResult, AnalysisSummary, CorrelatedSignal, DataCheck, Periods, Recommendation, RootCause
from app.schemas.dashboard import DashboardSpec
from app.schemas.transcript import SegmentIn


logger = logging.getLogger(__name__)


class AnalysisError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def analyze_meeting(db: Session, llm: LLMProvider, meeting_id: UUID) -> AnalysisResult:
    meeting = repo.get_meeting(db, meeting_id)
    if meeting is None:
        raise AnalysisError("Meeting not found", 404)
    if not meeting.segments:
        raise AnalysisError("Meeting has no transcript to analyze.", 409)

    segments = [
        SegmentIn(speaker=s.speaker, text=s.text, start_seconds=s.start_seconds, end_seconds=s.end_seconds)
        for s in meeting.segments
    ]
    customers = data.customers_by_name(db)
    try:
        extraction = llm.extract_signals(segments, list(customers))
    except LLMError as error:
        raise AnalysisError(f"Signal extraction failed: {error}", 502) from error
    try:
        revenue = data.revenue_comparison(db)
    except data.NoRevenueData:
        revenue = None  # no business data loaded: analyze the meeting on its own

    meeting_info = extraction.meeting.model_copy(update={"participation": participation(segments)})
    business = revenue is not None and discusses_business(extraction.signals)
    if business:
        signals = correlate(db, extraction.signals, revenue)
        kpis = compute_kpis(revenue, signals)
        root_causes = revenue_root_causes(db, revenue, signals)
        recommendations = recommend(db, signals, root_causes)
        summary = summarize(revenue, root_causes)
        periods = Periods(previous=revenue.previous_period, current=revenue.current_period)
    else:
        unchecked = DataCheck(status="no_data", detail="Not checked: no business data is linked to this meeting.")
        signals = [CorrelatedSignal(**signal.model_dump(), data_check=unchecked) for signal in extraction.signals]
        kpis, root_causes, recommendations, periods = [], [], [], None
        summary = AnalysisSummary(headline=meeting_headline(meeting_info))
    # Customer follow-ups exist only in business mode; otherwise every agreed task comes from the meeting itself.
    recommendations = _by_priority(recommendations + meeting_recommendations(meeting_info, signals if business else []))

    result = AnalysisResult(
        meeting_id=meeting.id,
        status="analyzed",
        llm_provider=extraction.provider,
        business_context=business,
        periods=periods,
        summary=summary,
        meeting=meeting_info,
        signals=signals,
        kpis=kpis,
        root_causes=root_causes,
        recommendations=recommendations,
    )
    spec = build_dashboard_spec(meeting.title, result, revenue)
    header = result.model_dump(mode="json", include={"llm_provider", "business_context", "periods", "summary", "meeting"})

    # Lock the meeting row: a concurrent analysis of the same meeting waits here, then replaces our results.
    db.execute(select(Meeting.id).where(Meeting.id == meeting.id).with_for_update())
    db.execute(delete(MeetingInsight).where(MeetingInsight.meeting_id == meeting.id))
    db.add_all(
        [MeetingInsight(meeting_id=meeting.id, insight_type="summary", payload=header)]
        + [MeetingInsight(meeting_id=meeting.id, insight_type="signal", payload=s.model_dump(mode="json")) for s in signals]
        + [MeetingInsight(meeting_id=meeting.id, insight_type="kpi", payload=k.model_dump(mode="json")) for k in kpis]
        + [MeetingInsight(meeting_id=meeting.id, insight_type="root_cause", payload=r.model_dump(mode="json")) for r in root_causes]
        + [MeetingInsight(meeting_id=meeting.id, insight_type="recommendation", payload=r.model_dump(mode="json")) for r in recommendations]
    )
    db.execute(delete(DashboardSpecRow).where(DashboardSpecRow.meeting_id == meeting.id))
    db.add(DashboardSpecRow(meeting_id=meeting.id, title=spec.title, spec=spec.model_dump(mode="json")))
    meeting.status = "analyzed"
    db.commit()
    logger.info(
        "Meeting %s analyzed (%s): %d signals, %d KPIs, %d root causes, %d recommendations",
        meeting.id, extraction.provider, len(signals), len(kpis), len(root_causes), len(recommendations),
    )
    return result


def _by_priority(recommendations: list[Recommendation]) -> list[Recommendation]:
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(recommendations, key=lambda rec: order[rec.priority])  # stable within a priority


def load_analysis(db: Session, meeting_id: UUID) -> AnalysisResult | None:
    """Rebuilds the stored analysis exactly as computed; None if the meeting was never analyzed."""
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise AnalysisError("Meeting not found", 404)
    rows = list(db.scalars(select(MeetingInsight).where(MeetingInsight.meeting_id == meeting_id).order_by(MeetingInsight.id)))
    header = next((row.payload for row in rows if row.insight_type == "summary"), None)
    if meeting.status != "analyzed" or header is None:
        return None

    def of_type(kind: str, model):
        return [model.model_validate(row.payload) for row in rows if row.insight_type == kind]

    return AnalysisResult.model_validate(
        {
            **header,
            "meeting_id": meeting.id,
            "status": meeting.status,
            "signals": of_type("signal", CorrelatedSignal),
            "kpis": of_type("kpi", KPI),
            "root_causes": of_type("root_cause", RootCause),
            "recommendations": of_type("recommendation", Recommendation),
        }
    )


def load_dashboard(db: Session, meeting_id: UUID | None = None) -> DashboardSpec | None:
    """The dashboard for one meeting, or the most recently generated one when meeting_id is None."""
    query = select(DashboardSpecRow)
    if meeting_id is not None:
        query = query.where(DashboardSpecRow.meeting_id == meeting_id)
    row = db.scalars(query.order_by(DashboardSpecRow.created_at.desc(), DashboardSpecRow.id.desc()).limit(1)).first()
    return DashboardSpec.model_validate(row.spec) if row else None
