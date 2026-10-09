"""Turns a spoken deadline ("by Friday", "next week", "15 November") into a calendar date.

Deterministic on purpose: the same words and meeting day always give the same date, and anything not
understood returns None (the spoken text is kept and shown instead; nothing is invented).

Conventions, relative to the meeting day:
- "this week" / "end of the week" -> that week's Friday; "next week" -> the following week's Friday.
- "<weekday>" / "by <weekday>" / "this <weekday>" -> the next such day (the meeting day itself counts).
- "next <weekday>" -> that weekday in the following week (Monday-based weeks).
- "end of month" / "this month" -> the month's last day; "next month" -> the last day of next month.
- Dates without a year that already passed this year are taken as next year.
"""

from calendar import monthrange
from datetime import date, timedelta
import re


_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WEEKDAY_ALIASES = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6}
_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
_FILLER = re.compile(r"^(?:(?:by|before|on|until|till|latest by|no later than|at the latest)\s+)+|\s+(?:at the latest|latest)$")
_ORDINAL = r"(\d{1,2})(?:st|nd|rd|th)?"


def _weekday(word: str) -> int | None:
    word = word.strip(".,")
    if word in _WEEKDAYS:
        return _WEEKDAYS.index(word)
    return _WEEKDAY_ALIASES.get(word)


def _month(word: str) -> int | None:
    word = word.strip(".,")
    for index, name in enumerate(_MONTHS, start=1):
        if word == name or (len(word) >= 3 and name.startswith(word)):
            return index
    return None


def _end_of_month(day: date, months_ahead: int = 0) -> date:
    year, month = day.year, day.month + months_ahead
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1
    return date(year, month, monthrange(year, month)[1])


def _friday(day: date, weeks_ahead: int = 0) -> date:
    monday = day - timedelta(days=day.weekday()) + timedelta(weeks=weeks_ahead)
    friday = monday + timedelta(days=4)
    return friday if friday >= day else day  # said on the weekend: "this week" means now


def _dated(day_of_month: int, month: int, reference: date, year: int | None = None) -> date | None:
    try:
        result = date(year or reference.year, month, day_of_month)
    except ValueError:
        return None
    if year is None and result < reference:
        result = date(result.year + 1, month, day_of_month)
    return result


def parse_due(text: str | None, reference: date) -> date | None:
    """The date meant by `text` when said on `reference`, or None if it is not understood."""
    if not text:
        return None
    phrase = " ".join(text.lower().replace("’", "'").split()).strip(" .,!")
    phrase = _FILLER.sub("", phrase).strip()
    phrase = re.sub(r"^the\s+", "", phrase)
    if not phrase:
        return None

    if phrase in ("today", "tonight", "eod", "end of day", "end of the day", "asap", "immediately", "right away", "now"):
        return reference
    if phrase in ("tomorrow", "tomorrow morning", "tomorrow evening", "tmrw", "tmr"):
        return reference + timedelta(days=1)
    if phrase == "day after tomorrow":
        return reference + timedelta(days=2)
    if phrase in ("this week", "end of week", "end of the week", "end of this week", "this weekend", "eow"):
        return _friday(reference)
    if phrase in ("next week", "end of next week"):
        return _friday(reference, weeks_ahead=1)
    if phrase in ("this month", "end of month", "end of the month", "end of this month", "month end", "eom"):
        return _end_of_month(reference)
    if phrase in ("next month", "end of next month"):
        return _end_of_month(reference, months_ahead=1)

    match = re.fullmatch(r"in (\d{1,3}|a|one|two|three|four|five|six|seven) (day|days|week|weeks)", phrase)
    if match:
        words = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
        count = int(match.group(1)) if match.group(1).isdigit() else words[match.group(1)]
        return reference + (timedelta(weeks=count) if match.group(2).startswith("week") else timedelta(days=count))

    match = re.fullmatch(r"(this |coming |next )?([a-z]+)", phrase)
    if match and (weekday := _weekday(match.group(2))) is not None:
        if (match.group(1) or "").strip() == "next":
            next_monday = reference - timedelta(days=reference.weekday()) + timedelta(weeks=1)
            return next_monday + timedelta(days=weekday)
        return reference + timedelta(days=(weekday - reference.weekday()) % 7)

    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", phrase)  # 2026-11-15
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    match = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?", phrase)  # 15/11, 15/11/2026 (day first)
    if match:
        year = int(match.group(3)) if match.group(3) else None
        if year is not None and year < 100:
            year += 2000
        return _dated(int(match.group(1)), int(match.group(2)), reference, year)
    match = re.fullmatch(rf"{_ORDINAL}(?: of)? ([a-z.]+)(?:,? (\d{{4}}))?", phrase)  # 15 november, 15th of nov
    if match and (month := _month(match.group(2))):
        return _dated(int(match.group(1)), month, reference, int(match.group(3)) if match.group(3) else None)
    match = re.fullmatch(rf"([a-z.]+) {_ORDINAL}(?:,? (\d{{4}}))?", phrase)  # november 15, nov 15th 2026
    if match and (month := _month(match.group(1))):
        return _dated(int(match.group(2)), month, reference, int(match.group(3)) if match.group(3) else None)
    return None
