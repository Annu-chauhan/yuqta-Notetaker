"""Deterministic, rule-based stand-in for an LLM. Same input always gives the same signals."""

from collections.abc import Sequence
import re

from app.schemas.analysis import ActionItem, Evidence, MeetingIntelligence, MeetingPoint, Signal, SignalExtraction
from app.schemas.transcript import SegmentIn


_DOWN = r"\b(down|declin\w*|drop\w*|fell|fall\w*|decreas\w*|lower|reduc\w*|cut)\b"
_UP = r"\b(up|grew|grow\w*|increas\w*|rose|higher)\b"
_METRICS = ("revenue", "sales", "margin", "pipeline")
_ORDER = r"\b(order\w*|purchas\w*|volume)\b"
_NOT_RENEWED = r"\b(hasn't|has not|haven't|have not|not yet|yet to|delay\w*|overdue|late)\b.*\brenew\w*|\brenew\w*.*\b(yet|delay\w*|overdue|late)\b"
_ACTION = r"\b(should|will|need to|must|let's|have to)\b.*\b(contact|call|reach out|follow up|email|meet|visit)\b"
_WEEKDAY = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
_DUE = rf"\b(today|tomorrow|this week|next week|this month|(?:by )?next {_WEEKDAY}|by (?:{_WEEKDAY}|end of \w+))\b"
_TASK = r"\b(I'll|I will|we'll|we will|should|need to|needs to|must|let's|have to|going to)\b"
_DECISION = r"\b(we (?:have )?(?:agreed|decided)|agreed to|decided to|let's go with|we'll go with|approved)\b"
_RISK = r"\b(risk\w*|concern\w*|worr\w*|problem\w*|issue\w*|blocker\w*|blocked|delay\w*)\b"
_SELF = r"\b(I'll|I will)\b"
_GROUP_REFERENCE = r"\b(both|all|these|those|them|the) (customers|accounts|clients)\b|\bboth of them\b"


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text, re.IGNORECASE) is not None


def _join(names: Sequence[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


class MockLLMProvider:
    name = "mock"

    def extract_signals(self, segments: Sequence[SegmentIn], known_customers: Sequence[str]) -> SignalExtraction:
        signals: list[Signal] = []
        mentioned: list[str] = []  # customers in order of first mention, for "both customers"

        for index, segment in enumerate(segments):
            text = segment.text
            evidence = Evidence(segment_index=index, speaker=segment.speaker, quote=text)
            customers = [name for name in known_customers if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE)]
            mentioned.extend(name for name in customers if name not in mentioned)

            for metric in _METRICS:
                if re.search(rf"\b{metric}\b", text, re.IGNORECASE) and not customers:
                    direction = "down" if _has(_DOWN, text) else "up" if _has(_UP, text) else None
                    if direction:
                        scope = "Enterprise revenue" if _has(r"\benterprise\b", text) and metric == "revenue" else metric.capitalize()
                        signals.append(Signal(kind="metric_change", summary=f"{scope} reported {direction}", metric=metric, direction=direction, evidence=evidence))

            for name in customers:
                if _has(_ORDER, text) and _has(_DOWN, text):
                    signals.append(Signal(kind="order_change", summary=f"{name} reduced orders", direction="down", customers=[name], evidence=evidence))
                elif _has(_ORDER, text) and _has(_UP, text):
                    signals.append(Signal(kind="order_change", summary=f"{name} increased orders", direction="up", customers=[name], evidence=evidence))
                if _has(_NOT_RENEWED, text):
                    signals.append(Signal(kind="renewal_risk", summary=f"{name} has not renewed", customers=[name], evidence=evidence))

            if _has(_ACTION, text):
                targets = customers or (list(mentioned) if _has(_GROUP_REFERENCE, text) else [])
                due_match = re.search(_DUE, text, re.IGNORECASE)
                due = due_match.group(1).lower() if due_match else None
                verb = "Contact" if _has(r"\b(contact|call|reach out|email)\b", text) else "Follow up with"
                summary = f"{verb} {_join(targets)}" if targets else "Follow-up action agreed"
                signals.append(Signal(kind="action_item", summary=f"{summary}{' ' + due if due else ''}", customers=targets, due=due, evidence=evidence))

        return SignalExtraction(provider=self.name, signals=signals, meeting=_meeting(segments))


def _meeting(segments: Sequence[SegmentIn]) -> MeetingIntelligence:
    """Keyword rules for decisions, tasks, risks and questions; good enough for offline demos and tests."""
    decisions, actions, risks, questions = [], [], [], []
    for index, segment in enumerate(segments):
        text = segment.text.strip()
        evidence = Evidence(segment_index=index, speaker=segment.speaker, quote=segment.text)
        if text.endswith("?"):
            questions.append(MeetingPoint(text=text, evidence=evidence))
            continue
        if _has(_DECISION, text):
            decisions.append(MeetingPoint(text=text, evidence=evidence))
        elif _has(_TASK, text):
            due = re.search(_DUE, text, re.IGNORECASE)
            owner = segment.speaker if _has(_SELF, text) else None
            actions.append(ActionItem(task=text.rstrip("."), owner=owner, due=due.group(1).lower() if due else None, evidence=evidence))
        if _has(_RISK, text):
            risks.append(MeetingPoint(text=text, evidence=evidence))

    names = list(dict.fromkeys(segment.speaker for segment in segments))
    found = [f"{len(items)} {label}" for items, label in ((decisions, "decisions"), (actions, "action items"), (risks, "risks"), (questions, "open questions")) if items]
    summary = f"Meeting between {_join(names)} ({len(segments)} turns)" if names else "Empty meeting"
    summary += f": {', '.join(found)}." if found else "; no decisions or action items were found."
    return MeetingIntelligence(summary=summary, decisions=decisions, action_items=actions, risks=risks, open_questions=questions)
