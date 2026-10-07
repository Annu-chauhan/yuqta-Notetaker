"""Builds the dashboard spec for an analyzed meeting. Pure function of its inputs.

The meeting's own intelligence is always shown. Revenue charts and business KPIs are added only when
the analysis was checked against business data (analysis.business_context).
"""

from app.analytics.business_data import RevenueComparison
from app.schemas.analysis import KPI, AnalysisResult
from app.schemas.dashboard import (
    BarChartWidget,
    ChartSeries,
    DashboardSpec,
    KpiWidget,
    PointsWidget,
    RecommendationsWidget,
    SummaryWidget,
    TopicsWidget,
)


def _month(revenue: RevenueComparison, which: str) -> str:
    period = revenue.previous_period if which == "previous" else revenue.current_period
    return f"{period:%b %Y}"


def _count(key: str, label: str, value: int) -> KPI:
    return KPI(key=key, label=label, unit="count", value=value)


def _business_widgets(analysis: AnalysisResult, revenue: RevenueComparison) -> list:
    previous, current = _month(revenue, "previous"), _month(revenue, "current")
    # Accounts ordered by previous-period revenue, "Other" always last.
    segments = sorted(revenue.by_segment.items(), key=lambda item: (item[0] == "Other", -item[1][0]))
    widgets: list = [
        KpiWidget(title="Key metrics", previous_label=previous, kpis=analysis.kpis),
        BarChartWidget(
            id="revenue_by_account",
            title="Revenue by account",
            subtitle=f"{previous} vs {current}",
            orientation="vertical",
            category_key="account",
            unit="usd",
            series=[
                ChartSeries(key="previous", label=previous, role="previous"),
                ChartSeries(key="current", label=current, role="current"),
            ],
            data=[{"account": name, "previous": float(before), "current": float(after)} for name, (before, after) in segments],
        ),
    ]
    if analysis.root_causes:
        widgets.append(
            BarChartWidget(
                id="decline_by_account",
                title="Where the decline came from",
                subtitle=f"Revenue change by account, {previous} → {current}",
                orientation="horizontal",
                category_key="account",
                unit="usd",
                series=[ChartSeries(key="change", label="Revenue change", role="decline")],
                data=[
                    {"account": cause.segment, "change": cause.contribution, "share_pct": cause.share_of_decline_pct}
                    for cause in analysis.root_causes
                ],
            )
        )
    return widgets


def _meeting_widgets(analysis: AnalysisResult) -> list:
    meeting = analysis.meeting
    widgets: list = []
    if not analysis.business_context:
        widgets.append(
            KpiWidget(
                title="At a glance",
                previous_label="",
                kpis=[
                    _count("participants", "Participants", len(meeting.participation)),
                    _count("action_items", "Action items", len(meeting.action_items)),
                    _count("decisions", "Decisions", len(meeting.decisions)),
                    _count("risks", "Risks raised", len(meeting.risks)),
                    _count("open_questions", "Open questions", len(meeting.open_questions)),
                ],
            )
        )
    if meeting.participation:
        widgets.append(
            BarChartWidget(
                id="participation",
                title="Who spoke",
                subtitle="Share of the conversation, by words spoken",
                orientation="horizontal",
                category_key="speaker",
                unit="percent",
                series=[ChartSeries(key="share", label="Share of words", role="share")],
                data=[{"speaker": row.speaker, "share": row.share_pct} for row in meeting.participation],
            )
        )
    if meeting.topics:
        widgets.append(TopicsWidget(title="Topics discussed", items=meeting.topics))
    for widget_id, title, tone, items in (
        ("decisions", "Decisions", "decision", meeting.decisions),
        ("risks", "Risks and concerns", "risk", meeting.risks),
        ("open_questions", "Open questions", "question", meeting.open_questions),
    ):
        if items:
            widgets.append(PointsWidget(id=widget_id, title=title, tone=tone, items=items))
    return widgets


def build_dashboard_spec(meeting_title: str, analysis: AnalysisResult, revenue: RevenueComparison | None) -> DashboardSpec:
    business = analysis.business_context and revenue is not None
    widgets: list = [
        SummaryWidget(
            headline=analysis.summary.headline,
            detail=(analysis.meeting.summary or None) if business else None,
        )
    ]
    if business:
        widgets += _business_widgets(analysis, revenue)
    widgets += _meeting_widgets(analysis)
    widgets.append(RecommendationsWidget(title="Recommended actions" if business else "Next steps", items=analysis.recommendations))

    return DashboardSpec(
        title=f"{meeting_title} · dashboard",
        meeting_id=analysis.meeting_id,
        meeting_title=meeting_title,
        periods=analysis.periods if business else None,
        widgets=widgets,
    )
