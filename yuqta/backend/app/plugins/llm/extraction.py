"""Shared by the real LLM providers: the prompt, the output schema, and validation of model output."""

from collections.abc import Sequence
import re
from typing import Literal

from pydantic import BaseModel

from app.schemas.analysis import ActionItem, Evidence, MeetingIntelligence, MeetingPoint, Signal, Topic
from app.schemas.transcript import SegmentIn


SYSTEM_PROMPT = """You analyze meeting transcripts for a meeting-intelligence system. The meeting can be about
anything: sales, a project, a product, strategy. Report only what the transcript says; never invent facts.
Transcripts come from speech recognition and may contain mis-heard words: ignore fragments that make no sense.
Speakers may mix languages, e.g. Hindi and English (Hinglish), in Latin or Devanagari script: understand all of
it, and always write every summary, title, task and other text you return in English.
Every item points at the transcript line it comes from (segment_index = the number in square brackets).

1. meeting: what the meeting itself was about.
- summary: 2-4 plain sentences on what was discussed and concluded. If almost nothing substantive was said,
  say so in one sentence.
- meeting_type: sales (customers, deals, revenue), project (tasks, status, deadlines), product (features,
  users), strategy (direction, priorities, money-making ideas) or general.
- topics: the main subjects discussed (at most 8), each with a short title and a one-sentence summary.
- decisions: things the group decided or agreed.
- action_items: concrete tasks someone will do. task is a short imperative phrase. owner is the person
  responsible: a speaker's name exactly as written in the transcript, or another person named in the
  meeting; null if nobody was assigned. due is the stated timeframe in lower case (e.g. "this week",
  "by friday"), or null.
- risks: problems, concerns, blockers or threats raised.
- open_questions: questions raised that were not answered.

2. signals: business statements that can be checked against company data.
- metric_change: a company-level metric said to go up or down. Set metric to exactly one of
  revenue, sales, margin, pipeline (e.g. "enterprise revenue" is revenue) and set direction.
  Leave customers empty.
- order_change: a named customer's orders/volume said to go up or down. Set direction and customers.
- renewal_risk: a named customer has not renewed, is late, or is at risk of not renewing. Set customers.
- action_item: a follow-up concerning named customers. Set customers (resolve references such as
  "both customers" to the names mentioned earlier) and due as above.
Use only customer names from the provided list of known customers, spelled exactly as listed; if the list
is empty or no listed customer is discussed, signals usually only contain metric_change items or nothing.
Write signal summaries as short phrases in the style "<Customer> reduced orders" or
"Contact <Customer> this week", using the real names."""


METRICS = ("revenue", "sales", "margin", "pipeline")
Metric = Literal["revenue", "sales", "margin", "pipeline"]


class ExtractedSignal(BaseModel):
    kind: Literal["metric_change", "order_change", "renewal_risk", "action_item"]
    summary: str
    metric: Metric | str | None  # schema sent to the model allows only the four names (see strict_json_schema)
    direction: Literal["up", "down"] | None
    customers: list[str]
    due: str | None
    segment_index: int


class ExtractedPoint(BaseModel):
    text: str
    segment_index: int


class ExtractedTopic(BaseModel):
    title: str
    summary: str
    segment_index: int


class ExtractedAction(BaseModel):
    task: str
    owner: str | None
    due: str | None
    segment_index: int


class ExtractedMeeting(BaseModel):
    summary: str
    meeting_type: Literal["sales", "project", "product", "strategy", "general"]
    topics: list[ExtractedTopic]
    decisions: list[ExtractedPoint]
    action_items: list[ExtractedAction]
    risks: list[ExtractedPoint]
    open_questions: list[ExtractedPoint]


class Extraction(BaseModel):
    # Required in the schema sent to the model (strict_json_schema); tolerated when a lax provider omits it.
    meeting: ExtractedMeeting | None = None
    signals: list[ExtractedSignal]


def user_prompt(segments: Sequence[SegmentIn], known_customers: Sequence[str]) -> str:
    transcript = "\n".join(f"[{index}] {segment.speaker}: {segment.text}" for index, segment in enumerate(segments))
    return f"Known customers: {', '.join(known_customers) or '(none)'}\n\n<transcript>\n{transcript}\n</transcript>"


def canonical_metric(value: str | None) -> str | None:
    """'Enterprise Revenue' -> 'revenue'. Models sometimes qualify the metric name."""
    if not value:
        return None
    lowered = value.casefold()
    return next((metric for metric in METRICS if metric in lowered), lowered.strip())


def validated_signals(extraction: Extraction, segments: Sequence[SegmentIn], known_customers: Sequence[str]) -> list[Signal]:
    """Model output is untrusted: keep only signals that point at a real line and known customers."""
    known = {name.casefold(): name for name in known_customers}
    signals: list[Signal] = []
    for item in extraction.signals:
        if not 0 <= item.segment_index < len(segments):
            continue
        customers = [known[name.casefold()] for name in item.customers if name.casefold() in known]
        if item.kind in ("order_change", "renewal_risk") and not customers:
            continue
        segment = segments[item.segment_index]
        signals.append(
            Signal(
                kind=item.kind,
                summary=item.summary.strip()[:200],
                metric=canonical_metric(item.metric) if item.kind == "metric_change" else None,
                direction=item.direction if item.kind in ("metric_change", "order_change") else None,
                customers=list(dict.fromkeys(customers)),
                due=item.due.lower() if item.due and item.kind == "action_item" else None,
                # Quote the transcript itself, never the model's paraphrase.
                evidence=Evidence(segment_index=item.segment_index, speaker=segment.speaker, quote=segment.text),
            )
        )
    return signals


_MAX_ITEMS = 20
_LONG_LINE = 280  # characters; longer transcript lines are quoted by their most relevant sentence
# \w misses Devanagari vowel signs (e.g. the ा in करना), so include the whole Devanagari block.
_WORD = re.compile(r"[\wऀ-ॿ']+")
_SENTENCE_END = re.compile(r"(?<=[.!?।॥])\s+")  # ।/॥ end sentences in Hindi


def _quote(text: str, about: str) -> str:
    """The transcript line, or for a long line the sentence that best matches `about` (still verbatim)."""
    if len(text) <= _LONG_LINE:
        return text
    wanted = {word.lower() for word in _WORD.findall(about) if len(word) > 2}
    sentences = [sentence for sentence in _SENTENCE_END.split(text) if sentence.strip()]
    best = max(sentences, key=lambda sentence: len(wanted & {w.lower() for w in _WORD.findall(sentence)}), default=text)
    return best if wanted & {w.lower() for w in _WORD.findall(best)} else text[:_LONG_LINE].rsplit(" ", 1)[0] + "…"


def _clean(text: str, limit: int) -> str:
    return " ".join(str(text).split())[:limit]


def validated_meeting(extracted: ExtractedMeeting | None, segments: Sequence[SegmentIn]) -> MeetingIntelligence:
    """Model output is untrusted: drop items without a real source line; quotes come from the transcript."""
    if extracted is None:
        return MeetingIntelligence()
    speakers = {segment.speaker.casefold(): segment.speaker for segment in segments}

    def evidence(index: int, about: str) -> Evidence | None:
        if not 0 <= index < len(segments):
            return None
        segment = segments[index]
        return Evidence(segment_index=index, speaker=segment.speaker, quote=_quote(segment.text, about))

    def points(items: list[ExtractedPoint]) -> list[MeetingPoint]:
        return [
            MeetingPoint(text=_clean(item.text, 300), evidence=source)
            for item in items[:_MAX_ITEMS]
            if (source := evidence(item.segment_index, item.text)) and item.text.strip()
        ]

    actions = []
    for item in extracted.action_items[:_MAX_ITEMS]:
        source = evidence(item.segment_index, f"{item.task} {item.due or ''}")
        if source is None or not item.task.strip():
            continue
        owner = _clean(item.owner, 100) if item.owner and item.owner.strip() else None
        actions.append(
            ActionItem(
                task=_clean(item.task, 300),
                owner=speakers.get(owner.casefold(), owner) if owner else None,
                due=_clean(item.due, 60).lower() if item.due and item.due.strip() else None,
                evidence=source,
            )
        )
    return MeetingIntelligence(
        summary=_clean(extracted.summary, 1500),
        meeting_type=extracted.meeting_type,
        topics=[
            Topic(title=_clean(item.title, 120), summary=_clean(item.summary, 400), evidence=source)
            for item in extracted.topics[:8]
            if (source := evidence(item.segment_index, f"{item.title} {item.summary}")) and item.title.strip()
        ],
        decisions=points(extracted.decisions),
        action_items=actions,
        risks=points(extracted.risks),
        open_questions=points(extracted.open_questions),
    )


def strict_json_schema() -> dict:
    """The Extraction schema in strict JSON-schema form: every object closed and every field required."""
    schema = Extraction.model_json_schema()
    schema["properties"]["meeting"] = {"$ref": "#/$defs/ExtractedMeeting"}  # always ask for the meeting part
    # The model must pick a known metric name (validation still tolerates free text from lax providers).
    schema["$defs"]["ExtractedSignal"]["properties"]["metric"] = {
        "anyOf": [{"type": "string", "enum": list(METRICS)}, {"type": "null"}],
    }

    def close(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                close(value)
        elif isinstance(node, list):
            for value in node:
                close(value)

    close(schema)
    return schema
