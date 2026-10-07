"""Deterministic KPI calculations for the signals discussed in a meeting."""

from app.analytics.business_data import RevenueComparison
from app.analytics.formatting import pct_change
from app.schemas.analysis import KPI, CorrelatedSignal


def compute_kpis(revenue: RevenueComparison, signals: list[CorrelatedSignal]) -> list[KPI]:
    previous, current = float(revenue.previous_total), float(revenue.current_total)
    kpis = [
        KPI(
            key="revenue",
            label="Revenue",
            unit="usd",
            value=current,
            previous=previous,
            current=current,
            change=current - previous,
            change_pct=pct_change(previous, current),
        )
    ]

    seen: set[tuple[str, str]] = set()
    for signal in signals:
        if not signal.customers or signal.data_check.status == "no_data":
            continue
        customer, facts = signal.customers[0], signal.data_check.facts
        if (signal.kind, customer) in seen:
            continue

        if signal.kind == "order_change":
            seen.add((signal.kind, customer))
            before, after = facts["previous_units"], facts["current_units"]
            kpis.append(
                KPI(
                    key=f"order_volume:{customer}",
                    label=f"{customer} order volume",
                    unit="units",
                    value=after,
                    previous=before,
                    current=after,
                    change=after - before,
                    change_pct=facts["change_pct"],
                    customer=customer,
                )
            )
        elif signal.kind == "renewal_risk":
            seen.add((signal.kind, customer))
            kpis.append(
                KPI(
                    key=f"renewal:{customer}",
                    label=f"{customer} renewal",
                    unit="status",
                    value=facts["status"],
                    current=facts["contract_value"],
                    customer=customer,
                )
            )
    return kpis
