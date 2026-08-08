from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS_KO = {
    "월": 0,
    "월요일": 0,
    "화": 1,
    "화요일": 1,
    "수": 2,
    "수요일": 2,
    "목": 3,
    "목요일": 3,
    "금": 4,
    "금요일": 4,
    "토": 5,
    "토요일": 5,
    "일": 6,
    "일요일": 6,
}
WEEKDAYS_EN = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


@dataclass(slots=True)
class TemporalResult:
    at: datetime | None = None
    date_value: date | None = None
    time_value: time | None = None
    has_date: bool = False
    has_time: bool = False
    is_all_day: bool = False
    is_deadline: bool = False
    vague: bool = False
    matched_text: list[str] | None = None


def _next_weekday(base: date, target: int, include_today: bool = False) -> date:
    delta = (target - base.weekday()) % 7
    if delta == 0 and not include_today:
        delta = 7
    return base + timedelta(days=delta)


def _week_start(base: date) -> date:
    return base - timedelta(days=base.weekday())


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _parse_date(text: str, ref: datetime) -> tuple[date | None, list[str]]:
    matched: list[str] = []
    lowered = text.lower()

    iso = re.search(r"\b(20\d{2})[-./](\d{1,2})[-./](\d{1,2})\b", text)
    if iso:
        parsed = _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        if parsed:
            matched.append(iso.group(0))
            return parsed, matched

    md = re.search(r"(?:(20\d{2})년\s*)?(\d{1,2})월\s*(\d{1,2})일", text)
    if md:
        year = int(md.group(1)) if md.group(1) else ref.year
        parsed = _safe_date(year, int(md.group(2)), int(md.group(3)))
        if parsed and not md.group(1) and parsed < ref.date() - timedelta(days=1):
            parsed = _safe_date(year + 1, int(md.group(2)), int(md.group(3)))
        if parsed:
            matched.append(md.group(0))
            return parsed, matched

    slash = re.search(r"(?<!\d)(\d{1,2})[./](\d{1,2})(?!\d)", text)
    if slash:
        parsed = _safe_date(ref.year, int(slash.group(1)), int(slash.group(2)))
        if parsed and parsed < ref.date() - timedelta(days=1):
            parsed = _safe_date(ref.year + 1, int(slash.group(1)), int(slash.group(2)))
        if parsed:
            matched.append(slash.group(0))
            return parsed, matched

    relative = [
        (r"\bday after tomorrow\b|모레", 2),
        (r"\btomorrow\b|내일", 1),
        (r"\btoday\b|오늘", 0),
    ]
    for pattern, offset in relative:
        m = re.search(pattern, lowered, flags=re.IGNORECASE)
        if m:
            matched.append(m.group(0))
            return ref.date() + timedelta(days=offset), matched

    week_match = re.search(r"(이번\s*주|다음\s*주|금주|차주)\s*(월요일|화요일|수요일|목요일|금요일|토요일|일요일|월|화|수|목|금|토|일)(?:요일)?", text)
    if week_match:
        week_word = re.sub(r"\s+", "", week_match.group(1))
        target = WEEKDAYS_KO[week_match.group(2)]
        start = _week_start(ref.date())
        if week_word in {"다음주", "차주"}:
            start += timedelta(days=7)
        parsed = start + timedelta(days=target)
        matched.append(week_match.group(0))
        return parsed, matched

    ko_weekday = re.search(r"(?<!이번\s)(?<!다음\s)(월요일|화요일|수요일|목요일|금요일|토요일|일요일)", text)
    if ko_weekday:
        parsed = _next_weekday(ref.date(), WEEKDAYS_KO[ko_weekday.group(1)], include_today=True)
        matched.append(ko_weekday.group(0))
        return parsed, matched

    for name, index in WEEKDAYS_EN.items():
        m = re.search(rf"\b{name}\b", lowered)
        if m:
            matched.append(m.group(0))
            return _next_weekday(ref.date(), index, include_today=True), matched

    return None, matched


def _parse_time(text: str) -> tuple[time | None, list[str], bool]:
    matched: list[str] = []
    vague = False

    if "정오" in text:
        return time(12, 0), ["정오"], False
    if "자정" in text:
        return time(0, 0), ["자정"], False

    korean = re.search(
        r"(?:(오전|오후)\s*)?(\d{1,2})시(?!간)(?:\s*(\d{1,2})분)?(?:\s*(?:경|쯤))?",
        text,
    )
    if korean:
        meridiem = korean.group(1)
        hour = int(korean.group(2))
        minute = int(korean.group(3) or 0)
        if meridiem == "오후" and hour < 12:
            hour += 12
        elif meridiem == "오전" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            matched.append(korean.group(0))
            return time(hour, minute), matched, False

    clock = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", text)
    if clock:
        matched.append(clock.group(0))
        return time(int(clock.group(1)), int(clock.group(2))), matched, False

    if re.search(r"\b(am|pm)\b", text, flags=re.IGNORECASE):
        english = re.search(r"(?<!\d)(\d{1,2})(?::([0-5]\d))?\s*(am|pm)\b", text, flags=re.IGNORECASE)
        if english:
            hour = int(english.group(1)) % 12
            if english.group(3).lower() == "pm":
                hour += 12
            matched.append(english.group(0))
            return time(hour, int(english.group(2) or 0)), matched, False

    if re.search(r"(?:오전|오후|아침|점심|저녁|밤)(?!\s*\d)", text):
        vague = True
    return None, matched, vague


def parse_temporal(text: str, reference: datetime, timezone_name: str) -> TemporalResult:
    tz = ZoneInfo(timezone_name)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=tz)
    else:
        reference = reference.astimezone(tz)

    date_value, date_matches = _parse_date(text, reference)
    time_value, time_matches, vague_time = _parse_time(text)
    deadline = bool(re.search(r"까지|마감|due\b|deadline", text, flags=re.IGNORECASE))
    vague = vague_time or bool(re.search(r"나중에|조만간|언젠가|시간\s*될\s*때|이번\s*주\s*중|다음\s*주\s*중", text))

    at: datetime | None = None
    all_day = False
    if date_value and time_value:
        at = datetime.combine(date_value, time_value, tzinfo=tz)
    elif date_value:
        all_day = True
        at = datetime.combine(date_value, time(23, 59), tzinfo=tz)
    elif time_value:
        candidate = datetime.combine(reference.date(), time_value, tzinfo=tz)
        if candidate < reference - timedelta(minutes=5):
            candidate += timedelta(days=1)
        at = candidate

    return TemporalResult(
        at=at,
        date_value=date_value,
        time_value=time_value,
        has_date=date_value is not None,
        has_time=time_value is not None,
        is_all_day=all_day,
        is_deadline=deadline,
        vague=vague,
        matched_text=[*date_matches, *time_matches],
    )


def month_last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]
