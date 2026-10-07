"""Read-only access to the business data used for correlation, KPIs and RCA.

Grouping is done in Python: the data set is small and this keeps queries portable.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Customer, Order, Renewal, Revenue


OTHER = "Other"


@dataclass(frozen=True)
class RevenueComparison:
    previous_period: date
    current_period: date
    by_segment: dict[str, tuple[Decimal, Decimal]]  # segment name -> (previous, current)
    customer_ids: dict[str, str]  # customer name -> id

    @property
    def previous_total(self) -> Decimal:
        return sum((previous for previous, _ in self.by_segment.values()), Decimal(0))

    @property
    def current_total(self) -> Decimal:
        return sum((current for _, current in self.by_segment.values()), Decimal(0))


class NoRevenueData(Exception):
    pass


def customers_by_name(db: Session) -> dict[str, Customer]:
    return {customer.name: customer for customer in db.scalars(select(Customer).order_by(Customer.id))}


def revenue_comparison(db: Session) -> RevenueComparison:
    """Compares the two most recent revenue periods."""
    periods = sorted(set(db.scalars(select(Revenue.period_start))), reverse=True)
    if len(periods) < 2:
        raise NoRevenueData("At least two revenue periods are needed to compare.")
    current, previous = periods[0], periods[1]

    names = {customer.id: customer.name for customer in db.scalars(select(Customer))}
    amounts: dict[str, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for row in db.scalars(select(Revenue).where(Revenue.period_start.in_([previous, current]))):
        segment = names.get(row.customer_id, OTHER) if row.customer_id else OTHER
        amounts[segment][0 if row.period_start == previous else 1] += Decimal(row.amount)

    return RevenueComparison(
        previous_period=previous,
        current_period=current,
        by_segment={segment: (values[0], values[1]) for segment, values in amounts.items()},
        customer_ids={name: customer_id for customer_id, name in names.items()},
    )


def order_units(db: Session, customer_id: str, previous: date, current: date) -> tuple[int, int] | None:
    """Units ordered in the months starting at `previous` and `current`; None if no orders at all."""
    totals = {previous: 0, current: 0}
    found = False
    for order in db.scalars(select(Order).where(Order.customer_id == customer_id)):
        month = order.order_date.replace(day=1)
        if month in totals:
            totals[month] += order.units
            found = True
    return (totals[previous], totals[current]) if found else None


def latest_renewal(db: Session, customer_id: str) -> Renewal | None:
    return db.scalars(
        select(Renewal).where(Renewal.customer_id == customer_id).order_by(Renewal.due_date.desc())
    ).first()
