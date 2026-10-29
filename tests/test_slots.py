from datetime import date, datetime, time, timedelta

from bot.services.slots import free_slots, working_days
from bot.utils.formatting import fmt_weekdays, normalize_phone, parse_time_range

DAY = date(2026, 11, 2)  # понедельник
WORK = {"work_start": time(10), "work_end": time(14), "step": timedelta(minutes=30)}
EARLY = datetime(2026, 11, 1, 9, 0)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(DAY, time(hour, minute))


def test_empty_day_has_all_slots_that_fit():
    slots = free_slots(DAY, timedelta(minutes=60), [], now=EARLY, **WORK)
    # последний слот 13:00 — часовая услуга должна закончиться к 14:00
    assert slots[0] == at(10) and slots[-1] == at(13)
    assert len(slots) == 7


def test_busy_interval_blocks_overlapping_slots():
    busy = [(at(11), at(12))]
    slots = free_slots(DAY, timedelta(minutes=60), busy, now=EARLY, **WORK)
    assert at(10, 30) not in slots  # 10:30–11:30 пересекается с 11:00
    assert at(11, 30) not in slots
    assert at(10) in slots and at(12) in slots  # впритык до и после — можно


def test_past_slots_are_hidden():
    slots = free_slots(DAY, timedelta(minutes=30), [], now=at(12, 10), **WORK)
    assert slots[0] == at(12, 30)


def test_long_service_does_not_fit_short_gap():
    busy = [(at(10), at(11)), (at(12), at(14))]
    assert free_slots(DAY, timedelta(minutes=90), busy, now=EARLY, **WORK) == []


def test_working_days_skips_days_off():
    days = working_days(DAY, 7, weekdays={0, 1, 2, 3, 4})
    assert [d.weekday() for d in days] == [0, 1, 2, 3, 4]


def test_normalize_phone():
    assert normalize_phone("8 (900) 123-45-67") == "+79001234567"
    assert normalize_phone("+7 900 123 45 67") == "+79001234567"
    assert normalize_phone("79001234567") == "+79001234567"
    assert normalize_phone("123") is None
    assert normalize_phone("позвоните мне") is None


def test_fmt_weekdays():
    assert fmt_weekdays({0, 1, 2, 3, 4, 5}) == "Пн–Сб"
    assert fmt_weekdays({0, 2, 4}) == "Пн, Ср, Пт"


def test_parse_time_range():
    assert parse_time_range("13:00-15:00") == (time(13), time(15))
    assert parse_time_range("9.30 – 10:00") == (time(9, 30), time(10))
    assert parse_time_range("15:00-13:00") is None
    assert parse_time_range("25:00-26:00") is None
    assert parse_time_range("обед") is None
