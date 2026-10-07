"""Checks each understood signal against the business data."""

from sqlalchemy.orm import Session

from app.analytics import business_data as data
from app.analytics.formatting import day, pct, pct_change, usd
from app.schemas.analysis import CorrelatedSignal, DataCheck, Signal


def _direction_check(direction: str | None, previous: float, current: float) -> str:
    actual = "down" if current < previous else "up" if current > previous else "flat"
    return "confirmed" if direction == actual else "contradicted"


def correlate(db: Session, signals: list[Signal], revenue: data.RevenueComparison) -> list[CorrelatedSignal]:
    customers = data.customers_by_name(db)
    return [CorrelatedSignal(**signal.model_dump(), data_check=_check(db, signal, revenue, customers)) for signal in signals]


def _check(db: Session, signal: Signal, revenue: data.RevenueComparison, customers: dict) -> DataCheck:
    previous_period, current_period = revenue.previous_period, revenue.current_period

    if signal.kind == "metric_change" and signal.metric in ("revenue", "sales"):
        previous, current = float(revenue.previous_total), float(revenue.current_total)
        change = pct_change(previous, current)
        return DataCheck(
            status=_direction_check(signal.direction, previous, current),
            detail=f"Revenue {usd(previous)} → {usd(current)} ({usd(current - previous, signed=True)}, {pct(change)})",
            facts={"previous": previous, "current": current, "change": current - previous, "change_pct": change},
        )

    if signal.kind == "order_change" and signal.customers:
        customer = customers.get(signal.customers[0])
        units = data.order_units(db, customer.id, previous_period, current_period) if customer else None
        if units is None:
            return DataCheck(status="no_data", detail=f"No orders on record for {signal.customers[0]}.")
        previous, current = units
        change = pct_change(previous, current)
        return DataCheck(
            status=_direction_check(signal.direction, previous, current),
            detail=f"{customer.name} order units {previous:,} → {current:,} ({pct(change)})",
            facts={"previous_units": previous, "current_units": current, "change_pct": change},
        )

    if signal.kind == "renewal_risk" and signal.customers:
        customer = customers.get(signal.customers[0])
        renewal = data.latest_renewal(db, customer.id) if customer else None
        if renewal is None:
            return DataCheck(status="no_data", detail=f"No renewal on record for {signal.customers[0]}.")
        facts = {"status": renewal.status, "due_date": renewal.due_date.isoformat(), "contract_value": float(renewal.contract_value)}
        if renewal.status in ("overdue", "upcoming"):
            label = "overdue since" if renewal.status == "overdue" else "due"
            return DataCheck(
                status="confirmed",
                detail=f"{customer.name} renewal {label} {day(renewal.due_date)} ({usd(renewal.contract_value)} contract)",
                facts=facts,
            )
        return DataCheck(status="contradicted", detail=f"{customer.name} renewal is {renewal.status}.", facts=facts)

    if signal.kind == "action_item" and signal.customers:
        known = [customers[name] for name in signal.customers if name in customers]
        if not known:
            return DataCheck(status="no_data", detail="Referenced customers are not in the business data.")
        statuses = {customer.name: customer.status for customer in known}
        owners = {customer.name: customer.account_owner for customer in known}
        detail = "; ".join(f"{name}: {status}, owner {owners[name]}" for name, status in statuses.items())
        return DataCheck(status="confirmed", detail=detail, facts={"status": statuses, "account_owner": owners})

    return DataCheck(status="no_data", detail="No business data linked to this signal.")
