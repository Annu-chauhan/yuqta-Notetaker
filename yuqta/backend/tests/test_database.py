"""Checks against a real, migrated Postgres. Enable with RUN_DB_TESTS=1."""

from datetime import date
from decimal import Decimal
from uuid import UUID
import os

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.db import seed
from app.db.models import Customer, Order, Renewal, Revenue
from app.db.session import check_database, get_db, get_engine
from app.main import app


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_TESTS") != "1",
    reason="set RUN_DB_TESTS=1 with a reachable, migrated DATABASE_URL to run database tests",
)

PREVIOUS, CURRENT = date(2026, 8, 1), date(2026, 9, 1)


@pytest.fixture(scope="module", autouse=True)
def seeded() -> None:
    seed.run(if_empty=True)


@pytest.fixture
def session():
    db = next(get_db())
    try:
        yield db
    finally:
        db.rollback()
        db.close()


def test_database_is_reachable() -> None:
    assert check_database() is True


def test_schema_is_at_latest_migration(session) -> None:
    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    assert session.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == head


def test_seeded_customers(session) -> None:
    customers = {c.id: (c.name, c.industry, c.account_owner, c.status) for c in session.scalars(select(Customer))}
    assert customers == {
        "C001": ("Acme", "Retail", "Rahul", "At Risk"),
        "C002": ("Beta", "Technology", "Priya", "At Risk"),
        "C003": ("Gamma", "Manufacturing", "Amit", "Healthy"),
    }


def test_revenue_decline_in_database(session) -> None:
    totals = dict(session.execute(select(Revenue.period_start, func.sum(Revenue.amount)).group_by(Revenue.period_start)).all())
    previous, current = totals[PREVIOUS], totals[CURRENT]
    assert (previous, current) == (Decimal("2390000.00"), Decimal("1950000.00"))
    assert round((current - previous) / previous * 100, 1) == Decimal("-18.4")


def test_decline_contribution_in_database(session) -> None:
    rows = session.execute(text(
        """
        SELECT COALESCE(c.name, 'Other') AS name,
               SUM(CASE WHEN r.period_start = :cur THEN r.amount ELSE -r.amount END) AS change
        FROM revenue r LEFT JOIN customers c ON c.id = r.customer_id
        GROUP BY 1
        """
    ), {"cur": CURRENT}).all()
    assert dict(rows) == {
        "Acme": Decimal("-190000.00"),
        "Beta": Decimal("-120000.00"),
        "Gamma": Decimal("-80000.00"),
        "Other": Decimal("-50000.00"),
    }


def test_acme_order_volume(session) -> None:
    month = func.date_trunc("month", Order.order_date)
    units = dict(session.execute(
        select(func.to_char(month, "YYYY-MM"), func.sum(Order.units)).where(Order.customer_id == "C001").group_by(month)
    ).all())
    assert units == {"2026-08": 1000, "2026-09": 690}


def test_beta_renewal_overdue(session) -> None:
    assert session.scalars(select(Renewal.status).where(Renewal.customer_id == "C002")).one() == "overdue"


def test_only_one_other_revenue_row_per_period(session) -> None:
    session.add(Revenue(period_start=CURRENT, customer_id=None, amount=1))
    with pytest.raises(IntegrityError):
        session.flush()


def test_seed_reload_is_idempotent() -> None:
    seed.run(if_empty=False)
    seed.run(if_empty=False)
    with get_engine().connect() as connection:
        counts = [connection.execute(select(func.count()).select_from(model)).scalar_one() for model in (Customer, Order, Revenue, Renewal)]
    assert counts == [3, 15, 8, 3]
    assert seed.run(if_empty=True) is False


def test_customers_endpoint() -> None:
    response = TestClient(app).get("/api/customers")
    assert response.status_code == 200
    customers = response.json()
    assert [c["name"] for c in customers] == ["Acme", "Beta", "Gamma"]
    assert customers[1]["renewals"][0]["status"] == "overdue"


def test_sample_meeting_round_trip_in_postgres(session) -> None:
    from app.db.models import Meeting, TranscriptSegment

    client = TestClient(app)
    created = client.post("/api/meetings/sample")
    assert created.status_code == 201
    meeting_id = created.json()["id"]
    try:
        fetched = client.get(f"/api/meetings/{meeting_id}").json()
        assert fetched["status"] == "transcribed"
        assert [s["speaker"] for s in fetched["segments"]] == [
            "Sales Manager", "Finance Manager", "Product Manager", "Sales Manager"
        ]
        assert session.execute(
            text("SELECT jsonb_typeof(participants) FROM meetings WHERE id = :id"), {"id": meeting_id}
        ).scalar_one() == "array"
    finally:
        session.execute(Meeting.__table__.delete().where(Meeting.id == UUID(meeting_id)))
        session.commit()
    # ON DELETE CASCADE removed the segments too.
    remaining = session.execute(
        select(func.count()).select_from(TranscriptSegment).where(TranscriptSegment.meeting_id == UUID(meeting_id))
    ).scalar_one()
    assert remaining == 0


def test_analysis_round_trip_in_postgres(session) -> None:
    from app.db.models import DashboardSpec, Meeting, MeetingInsight

    dashboards_before = session.execute(select(func.count()).select_from(DashboardSpec)).scalar_one()
    client = TestClient(app)
    meeting_id = client.post("/api/meetings/sample").json()["id"]
    try:
        analyzed = client.post(f"/api/meetings/{meeting_id}/analyze")
        assert analyzed.status_code == 200
        result = analyzed.json()
        assert result["summary"]["revenue_change"] == -440000
        assert [c["segment"] for c in result["root_causes"]] == ["Acme", "Beta", "Gamma", "Other"]
        assert client.get(f"/api/meetings/{meeting_id}/analysis").json() == result
        types = session.execute(
            select(MeetingInsight.insight_type, func.count()).where(MeetingInsight.meeting_id == UUID(meeting_id)).group_by(MeetingInsight.insight_type)
        ).all()
        assert dict(types) == {"summary": 1, "signal": 4, "kpi": 3, "root_cause": 4, "recommendation": 4}
        assert client.get(f"/api/meetings/{meeting_id}/dashboard").status_code == 200
    finally:
        session.execute(Meeting.__table__.delete().where(Meeting.id == UUID(meeting_id)))
        session.commit()
    # Deleting the meeting removes its dashboard too (no orphaned "latest" dashboard).
    assert session.execute(select(func.count()).select_from(DashboardSpec)).scalar_one() == dashboards_before
