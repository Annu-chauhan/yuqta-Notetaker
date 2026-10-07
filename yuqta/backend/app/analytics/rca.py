"""Root-cause analysis: decompose the revenue change by customer and attach data-backed drivers."""

from sqlalchemy.orm import Session

from app.analytics import business_data as data
from app.analytics.formatting import day, pct, pct_change, usd
from app.schemas.analysis import AnalysisSummary, CorrelatedSignal, Evidence, RootCause


def _drivers(db: Session, name: str, customer_id: str | None, revenue: data.RevenueComparison) -> list[str]:
    if customer_id is None:
        return ["Long-tail accounts (no customer-level data)"]
    drivers: list[str] = []
    units = data.order_units(db, customer_id, revenue.previous_period, revenue.current_period)
    if units and units[0] != units[1]:
        drivers.append(f"Order volume {pct(pct_change(*units))} ({units[0]:,} → {units[1]:,} units)")
    renewal = data.latest_renewal(db, customer_id)
    if renewal and renewal.status == "overdue":
        drivers.append(f"Renewal overdue since {day(renewal.due_date)} ({usd(renewal.contract_value)} contract)")
    return drivers or ["No order or renewal change on record"]


def revenue_root_causes(db: Session, revenue: data.RevenueComparison, signals: list[CorrelatedSignal]) -> list[RootCause]:
    total_change = revenue.current_total - revenue.previous_total
    if total_change >= 0:
        return []  # nothing to explain: revenue did not decline

    evidence: dict[str, list[Evidence]] = {}
    for signal in signals:
        if signal.kind != "action_item":
            for name in signal.customers:
                evidence.setdefault(name, []).append(signal.evidence)

    rows = []
    for segment, (previous, current) in revenue.by_segment.items():
        contribution = current - previous
        if contribution >= 0:
            continue
        customer_id = revenue.customer_ids.get(segment) if segment != data.OTHER else None
        rows.append(
            dict(
                segment=segment,
                customer_id=customer_id,
                previous=float(previous),
                current=float(current),
                contribution=float(contribution),
                share_of_decline_pct=round(float(contribution / total_change * 100), 1),
                drivers=_drivers(db, segment, customer_id, revenue),
                mentioned_in_meeting=segment in evidence,
                evidence=evidence.get(segment, []),
            )
        )
    rows.sort(key=lambda row: row["contribution"])  # largest decline first
    return [RootCause(rank=rank, **row) for rank, row in enumerate(rows, start=1)]


def summarize(revenue: data.RevenueComparison, root_causes: list[RootCause]) -> AnalysisSummary:
    previous, current = float(revenue.previous_total), float(revenue.current_total)
    change, change_pct = current - previous, pct_change(previous, current)
    if not root_causes:
        return AnalysisSummary(
            headline=f"Revenue {usd(change, signed=True)} ({pct(change_pct)}); no decline to explain.",
            revenue_change=change,
            revenue_change_pct=change_pct,
            explained_by_discussed_pct=None,
            not_discussed=[],
        )

    discussed = [cause for cause in root_causes if cause.mentioned_in_meeting]
    not_discussed = [cause for cause in root_causes if not cause.mentioned_in_meeting and cause.customer_id]
    explained = round(sum(cause.share_of_decline_pct for cause in discussed), 1)

    headline = f"Revenue down {usd(-change)} ({pct(change_pct)})."
    if discussed:
        names = " and ".join(f"{cause.segment} ({usd(cause.contribution)})" for cause in discussed)
        verb = "explains" if len(discussed) == 1 else "explain"
        headline += f" {names}, discussed in the meeting, {verb} {explained:.1f}% of the decline."
    if not_discussed:
        names = ", ".join(f"{cause.segment} ({usd(cause.contribution)})" for cause in not_discussed)
        headline += f" Not discussed: {names}."
    return AnalysisSummary(
        headline=headline,
        revenue_change=change,
        revenue_change_pct=change_pct,
        explained_by_discussed_pct=explained,
        not_discussed=[cause.segment for cause in not_discussed],
    )
