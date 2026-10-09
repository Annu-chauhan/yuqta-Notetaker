"""Checks the demo numbers in data/seed.sql without needing a database."""

from decimal import Decimal
from pathlib import Path
import re

from app.core.config import get_settings
from app.db.base import Base
from app.db import models  # noqa: F401


SEED = Path(get_settings().seed_sql_path).read_text(encoding="utf-8")
PREVIOUS, CURRENT = "2026-08-01", "2026-09-01"


def _revenue_rows() -> dict[tuple[str, str | None], Decimal]:
    block = SEED.split("INSERT INTO revenue")[1].split(";")[0]
    rows = re.findall(r"\('(\d{4}-\d{2}-\d{2})',\s*(?:'(C\d+)'|NULL),\s*([\d.]+)\)", block)
    return {(period, customer or None): Decimal(amount) for period, customer, amount in rows}


def _order_units(customer: str, month: str) -> int:
    block = SEED.split("INSERT INTO orders")[1].split(";")[0]
    rows = re.findall(r"\('(C\d+)',\s*'(\d{4}-\d{2})-\d{2}',\s*(\d+),", block)
    return sum(int(units) for cid, period, units in rows if cid == customer and period == month)


def test_all_tables_are_defined() -> None:
    assert set(Base.metadata.tables) == {
        "customers",
        "orders",
        "revenue",
        "renewals",
        "meetings",
        "transcript_segments",
        "meeting_bots",
        "minutes_emails",
        "connector_credentials",
        "action_items",
        "reminder_log",
        "meeting_insights",
        "dashboard_specs",
    }


def test_customers_match_spec() -> None:
    assert "('C001', 'Acme',  'Retail',        'Rahul', 'At Risk')" in SEED
    assert "('C002', 'Beta',  'Technology',    'Priya', 'At Risk')" in SEED
    assert "('C003', 'Gamma', 'Manufacturing', 'Amit',  'Healthy')" in SEED


def test_revenue_totals_and_decline() -> None:
    rows = _revenue_rows()
    previous = sum(amount for (period, _), amount in rows.items() if period == PREVIOUS)
    current = sum(amount for (period, _), amount in rows.items() if period == CURRENT)
    assert previous == Decimal("2390000")
    assert current == Decimal("1950000")
    assert current - previous == Decimal("-440000")
    assert round((current - previous) / previous * 100, 1) == Decimal("-18.4")


def test_decline_contribution_per_customer() -> None:
    rows = _revenue_rows()
    contribution = {customer: rows[(CURRENT, customer)] - rows[(PREVIOUS, customer)] for _, customer in rows}
    assert contribution == {
        "C001": Decimal("-190000"),
        "C002": Decimal("-120000"),
        "C003": Decimal("-80000"),
        None: Decimal("-50000"),
    }


def test_acme_order_volume_down_31_percent() -> None:
    previous, current = _order_units("C001", "2026-08"), _order_units("C001", "2026-09")
    assert (previous, current) == (1000, 690)
    assert round((current - previous) / previous * 100) == -31


def test_beta_renewal_overdue() -> None:
    assert re.search(r"\('C002',[^)]*'overdue'", SEED)
