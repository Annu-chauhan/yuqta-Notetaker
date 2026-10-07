"""Dashboard spec: a JSON description the frontend renders as-is.

The backend decides what the dashboard shows; the frontend only knows how to draw
each widget type. Data is embedded so a spec is a self-contained snapshot.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.analysis import KPI, MeetingPoint, Periods, Recommendation, Topic


class SummaryWidget(BaseModel):
    type: Literal["summary"] = "summary"
    headline: str
    detail: str | None = None  # the meeting summary, when the headline is about business data


class KpiWidget(BaseModel):
    type: Literal["kpis"] = "kpis"
    title: str
    previous_label: str
    kpis: list[KPI]


class ChartSeries(BaseModel):
    key: str
    label: str
    role: Literal["previous", "current", "decline", "share"]


class BarChartWidget(BaseModel):
    type: Literal["bar_chart"] = "bar_chart"
    id: str
    title: str
    subtitle: str
    orientation: Literal["vertical", "horizontal"]
    category_key: str
    unit: Literal["usd", "units", "percent"]
    series: list[ChartSeries]
    data: list[dict[str, float | str]]


class RecommendationsWidget(BaseModel):
    type: Literal["recommendations"] = "recommendations"
    title: str
    items: list[Recommendation]


class TopicsWidget(BaseModel):
    type: Literal["topics"] = "topics"
    title: str
    items: list[Topic]


class PointsWidget(BaseModel):
    """Decisions, risks or open questions from the meeting, each with its source quote."""

    type: Literal["points"] = "points"
    id: str
    title: str
    tone: Literal["decision", "risk", "question"]
    items: list[MeetingPoint]


Widget = Annotated[
    SummaryWidget | KpiWidget | BarChartWidget | RecommendationsWidget | TopicsWidget | PointsWidget,
    Field(discriminator="type"),
]


class DashboardSpec(BaseModel):
    version: Literal[1] = 1
    title: str
    meeting_id: UUID
    meeting_title: str
    periods: Periods | None = None  # None when the meeting was analyzed without business data
    widgets: list[Widget]
