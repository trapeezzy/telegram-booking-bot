"""Расчёт свободного времени. Чистые функции отделены от БД — их легко тестировать."""

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db import repo

Interval = tuple[datetime, datetime]


def working_days(today: date, days_ahead: int, weekdays: set[int]) -> list[date]:
    days = (today + timedelta(days=i) for i in range(days_ahead))
    return [d for d in days if d.weekday() in weekdays]


def free_slots(
    day: date,
    duration: timedelta,
    busy: Iterable[Interval],
    *,
    work_start: time,
    work_end: time,
    step: timedelta,
    now: datetime,
) -> list[datetime]:
    """Начала слотов, в которые услуга длительностью duration помещается целиком
    до конца рабочего дня и не пересекается ни с одной занятой записью."""
    busy = list(busy)
    end_of_day = datetime.combine(day, work_end)
    slot = datetime.combine(day, work_start)
    result = []
    while slot + duration <= end_of_day:
        slot_end = slot + duration
        if slot > now and not any(b_start < slot_end and b_end > slot for b_start, b_end in busy):
            result.append(slot)
        slot += step
    return result


async def slots_by_day(
    session: AsyncSession, settings: Settings, duration_min: int, now: datetime, days: list[date] | None = None
) -> dict[date, list[datetime]]:
    """Свободные слоты по дням (дни без слотов не попадают в результат).
    Все занятые интервалы берутся одним запросом на весь период."""
    days = days if days is not None else working_days(now.date(), settings.booking_days_ahead, settings.weekdays)
    if not days:
        return {}

    busy = await repo.busy_intervals(
        session, datetime.combine(days[0], time.min), datetime.combine(days[-1], time.max)
    )
    result = {}
    for day in days:
        day_busy = busy
        if settings.daily_break:
            day_busy = [*busy, tuple(datetime.combine(day, t) for t in settings.daily_break)]
        slots = free_slots(
            day,
            timedelta(minutes=duration_min),
            day_busy,
            work_start=settings.work_start,
            work_end=settings.work_end,
            step=timedelta(minutes=settings.slot_step_minutes),
            now=now,
        )
        if slots:
            result[day] = slots
    return result
