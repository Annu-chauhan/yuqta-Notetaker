from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


SignalKind = Literal["metric_change", "order_change", "renewal_risk", "action_item"]


class Evidence(BaseModel):
    segment_index: int
    speaker: str
    quote: str


class Signal(BaseModel):
    """A business statement understood from the transcript (produced by the LLM plugin)."""

    kind: SignalKind
    summary: str
    metric: str | None = None
    direction: Literal["up", "down"] | None = None
    customers: list[str] = Field(default_factory=list)  # customer names as known to the business data
    due: str | None = None
    evidence: Evidence


MeetingType = Literal["sales", "project", "product", "strategy", "general"]


class MeetingPoint(BaseModel):
    """A decision, risk or open question raised in the meeting."""

    text: str
    evidence: Evidence


class Topic(BaseModel):
    title: str
    summary: str
    evidence: Evidence


class ActionItem(BaseModel):
    task: str
    owner: str | None = None  # a speaker, or a person named in the meeting
    due: str | None = None  # as said, lower case: "this week", "friday"
    evidence: Evidence


class Participation(BaseModel):
    """How much one speaker talked. Computed from the transcript, not by the LLM."""

    speaker: str
    turns: int
    words: int
    share_pct: float


class MeetingIntelligence(BaseModel):
    """What the meeting itself was about, independent of any business data."""

    summary: str = ""
    meeting_type: MeetingType = "general"
    topics: list[Topic] = Field(default_factory=list)
    decisions: list[MeetingPoint] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    risks: list[MeetingPoint] = Field(default_factory=list)
    open_questions: list[MeetingPoint] = Field(default_factory=list)
    participation: list[Participation] = Field(default_factory=list)


class SignalExtraction(BaseModel):
    provider: str
    signals: list[Signal]
    meeting: MeetingIntelligence = Field(default_factory=MeetingIntelligence)


class DataCheck(BaseModel):
    status: Literal["confirmed", "contradicted", "no_data"]
    detail: str
    facts: dict[str, Any] = Field(default_factory=dict)


class CorrelatedSignal(Signal):
    data_check: DataCheck


class KPI(BaseModel):
    key: str
    label: str
    unit: Literal["usd", "units", "status", "count"]
    value: float | str
    previous: float | None = None
    current: float | None = None
    change: float | None = None
    change_pct: float | None = None
    customer: str | None = None


class RootCause(BaseModel):
    rank: int
    segment: str  # customer name, or "Other" for long-tail accounts
    customer_id: str | None
    previous: float
    current: float
    contribution: float
    share_of_decline_pct: float
    drivers: list[str]
    mentioned_in_meeting: bool
    evidence: list[Evidence] = Field(default_factory=list)


class Recommendation(BaseModel):
    """A concrete next step, derived by fixed rules from the analysis."""

    key: str
    title: str
    priority: Literal["high", "medium", "low"]
    customer: str | None = None
    owner: str | None = None
    due: str | None = None
    rationale: list[str]
    evidence: list[Evidence] = Field(default_factory=list)


class Periods(BaseModel):
    previous: date
    current: date


class AnalysisSummary(BaseModel):
    headline: str
    # The revenue fields are set only when the meeting was checked against business data.
    revenue_change: float | None = None
    revenue_change_pct: float | None = None
    explained_by_discussed_pct: float | None = None
    not_discussed: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    meeting_id: UUID
    status: str
    llm_provider: str
    # True when the meeting discussed customers or revenue AND business data exists to check it against.
    # False: the analysis is about the meeting alone (no KPIs, root causes or "not discussed" accounts).
    business_context: bool = True
    periods: Periods | None = None
    summary: AnalysisSummary
    meeting: MeetingIntelligence = Field(default_factory=MeetingIntelligence)
    signals: list[CorrelatedSignal]
    kpis: list[KPI]
    root_causes: list[RootCause]
    recommendations: list[Recommendation] = Field(default_factory=list)
