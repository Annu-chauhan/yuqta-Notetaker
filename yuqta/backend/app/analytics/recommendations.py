"""Turns analysis results into prioritised next steps using fixed rules."""

from sqlalchemy.orm import Session

from app.analytics import business_data as data
from app.analytics.formatting import usd
from app.schemas.analysis import CorrelatedSignal, Evidence, Recommendation, RootCause


_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_MIN_SHARE_TO_REVIEW = 10.0  # undiscussed declines below this share are left out


def _impact(cause: RootCause | None) -> list[str]:
    if cause is None:
        return []
    return [f"Revenue {usd(cause.contribution)} ({cause.share_of_decline_pct:.1f}% of the decline)"]


def recommend(db: Session, signals: list[CorrelatedSignal], root_causes: list[RootCause]) -> list[Recommendation]:
    customers = data.customers_by_name(db)
    causes = {cause.segment: cause for cause in root_causes}

    # Actions agreed in the meeting attach their due date and quote to the matching recommendation.
    agreed: dict[str, CorrelatedSignal] = {}
    for signal in signals:
        if signal.kind == "action_item":
            for name in signal.customers:
                agreed.setdefault(name, signal)

    recommendations: list[Recommendation] = []
    covered: set[str] = set()

    def add(signal: CorrelatedSignal | None, customer: str | None, **fields) -> None:
        action = agreed.get(customer) if customer else None
        evidence: list[Evidence] = [signal.evidence] if signal else []
        if action:
            evidence.append(action.evidence)
        recommendations.append(
            Recommendation(
                customer=customer,
                owner=customers[customer].account_owner if customer in customers else None,
                due=action.due if action else None,
                evidence=evidence,
                **fields,
            )
        )
        if customer:
            covered.add(customer)

    for signal in signals:
        if signal.data_check.status == "contradicted":
            recommendations.append(
                Recommendation(
                    key=f"correct:{signal.evidence.segment_index}",
                    title=f"Correct the record: {signal.summary.rstrip('.')}",
                    priority="high",
                    customer=signal.customers[0] if signal.customers else None,
                    owner=customers[signal.customers[0]].account_owner if signal.customers and signal.customers[0] in customers else None,
                    rationale=[f"Said in the meeting: \u201c{signal.evidence.quote}\u201d", f"The data shows: {signal.data_check.detail}"],
                    evidence=[signal.evidence],
                )
            )
            continue
        if signal.data_check.status != "confirmed" or not signal.customers:
            continue
        customer = signal.customers[0]
        if signal.kind == "order_change" and signal.direction == "down":
            add(
                signal,
                customer,
                key=f"contact:{customer}",
                title=f"Contact {customer} about reduced orders",
                priority="high",
                rationale=[signal.data_check.detail, *_impact(causes.get(customer))],
            )
        elif signal.kind == "renewal_risk" and signal.data_check.facts.get("status") == "overdue":
            add(
                signal,
                customer,
                key=f"renewal:{customer}",
                title=f"Escalate {customer}'s overdue renewal",
                priority="high",
                rationale=[signal.data_check.detail, *_impact(causes.get(customer))],
            )

    for cause in root_causes:
        if cause.mentioned_in_meeting or cause.share_of_decline_pct < _MIN_SHARE_TO_REVIEW:
            continue
        if cause.customer_id:
            add(
                None,
                cause.segment,
                key=f"review:{cause.segment}",
                title=f"Review {cause.segment}'s revenue decline",
                priority="medium",
                rationale=[*_impact(cause), "Not discussed in the meeting", *cause.drivers],
            )
        else:
            add(
                None,
                None,
                key="review:other",
                title="Review long-tail accounts",
                priority="low",
                rationale=[*_impact(cause), *cause.drivers],
            )

    # Agreed actions not already covered above are kept as their own follow-ups.
    for signal in signals:
        if signal.kind == "action_item" and not (set(signal.customers) & covered):
            first = signal.customers[0] if signal.customers else None
            recommendations.append(
                Recommendation(
                    key=f"action:{signal.evidence.segment_index}",
                    title=signal.summary,
                    priority="low",
                    customer=first,
                    owner=customers[first].account_owner if first in customers else None,
                    due=signal.due,
                    rationale=["Agreed in the meeting"],
                    evidence=[signal.evidence],
                )
            )

    return sorted(recommendations, key=lambda rec: _PRIORITY_ORDER[rec.priority])  # stable within a priority
