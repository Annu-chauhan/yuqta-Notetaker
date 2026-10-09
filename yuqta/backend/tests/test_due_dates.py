"""Spoken deadlines -> calendar dates, relative to the meeting day."""

from datetime import date

import pytest

from app.analytics.due_dates import parse_due


MONDAY = date(2026, 10, 5)  # Monday 5 October 2026
SATURDAY = date(2026, 10, 10)


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("today", date(2026, 10, 5)),
        ("by end of day", date(2026, 10, 5)),
        ("tomorrow", date(2026, 10, 6)),
        ("by tomorrow", date(2026, 10, 6)),
        ("day after tomorrow", date(2026, 10, 7)),
        ("this week", date(2026, 10, 9)),
        ("by the end of this week", date(2026, 10, 9)),
        ("next week", date(2026, 10, 16)),
        ("friday", date(2026, 10, 9)),
        ("by Friday", date(2026, 10, 9)),
        ("this wed", date(2026, 10, 7)),
        ("monday", date(2026, 10, 5)),  # said on Monday: today
        ("next wednesday", date(2026, 10, 14)),
        ("by next Monday", date(2026, 10, 12)),
        ("end of month", date(2026, 10, 31)),
        ("next month", date(2026, 11, 30)),
        ("in 3 days", date(2026, 10, 8)),
        ("in two weeks", date(2026, 10, 19)),
        ("15 November", date(2026, 11, 15)),
        ("by the 15th of november", date(2026, 11, 15)),
        ("1st December", date(2026, 12, 1)),
        ("nov 3rd", date(2026, 11, 3)),
        ("November 15, 2027", date(2027, 11, 15)),
        ("15/11", date(2026, 11, 15)),
        ("2026-12-24", date(2026, 12, 24)),
        ("5 march", date(2027, 3, 5)),  # already passed this year: next year
    ],
)
def test_understood(said: str, expected: date) -> None:
    assert parse_due(said, MONDAY) == expected


@pytest.mark.parametrize("said", [None, "", "soon", "when possible", "after the launch", "31 february", "someday"])
def test_not_understood_returns_none(said) -> None:
    assert parse_due(said, MONDAY) is None


def test_weekend_meetings() -> None:
    assert parse_due("this week", SATURDAY) == SATURDAY  # Friday already passed
    assert parse_due("next week", SATURDAY) == date(2026, 10, 16)
    assert parse_due("friday", SATURDAY) == date(2026, 10, 16)
