from datetime import datetime, time, timedelta

from bot.db import repo
from bot.db.models import Booking
from bot.services.slots import slots_by_day

NOW = datetime(2026, 11, 2, 9, 0)


async def _client(session, user_id=1):
    return await repo.upsert_user(session, user_id, "Иван Петров", "ivan")


async def test_cannot_book_overlapping_time(session):
    await _client(session)
    haircut, beard = (await repo.list_services(session))[:2]  # 60 и 30 минут
    start = NOW + timedelta(days=1)

    assert await repo.create_booking(session, 1, haircut, start, NOW) is not None
    assert await repo.create_booking(session, 1, beard, start + timedelta(minutes=30), NOW) is None
    assert await repo.create_booking(session, 1, beard, start + timedelta(minutes=60), NOW) is not None


async def test_cancelled_booking_frees_the_slot(session):
    await _client(session)
    service = (await repo.list_services(session))[0]
    start = NOW + timedelta(days=1)

    booking = await repo.create_booking(session, 1, service, start, NOW)
    await repo.cancel_booking(session, booking)
    assert await repo.create_booking(session, 1, service, start, NOW) is not None


async def test_reminder_flags_depend_on_lead_time(session):
    await _client(session)
    service = (await repo.list_services(session))[0]

    far = await repo.create_booking(session, 1, service, NOW + timedelta(days=3), NOW)
    soon = await repo.create_booking(session, 1, service, NOW + timedelta(hours=5), NOW)
    assert (far.reminded_day, far.reminded_hour) == (False, False)
    assert (soon.reminded_day, soon.reminded_hour) == (True, False)  # «за сутки» уже не нужно

    later = NOW + timedelta(days=2, hours=1)  # за сутки до первой записи
    due = await repo.bookings_to_remind(session, later, timedelta(hours=24), Booking.reminded_day)
    assert [b.id for b in due] == [far.id]


async def test_stats(session):
    await _client(session)
    service = (await repo.list_services(session))[0]
    await repo.create_booking(session, 1, service, NOW - timedelta(days=2), NOW - timedelta(days=5))
    await repo.create_booking(session, 1, service, NOW + timedelta(days=2), NOW)

    stats = await repo.get_stats(session, NOW)
    assert stats.users == 1
    assert stats.upcoming == 1
    assert stats.completed_30d == 1
    assert stats.revenue_30d == service.price
    assert stats.top_service == service.title


async def test_time_off_and_daily_break_block_slots(session, settings):
    tomorrow = (NOW + timedelta(days=1)).date()
    await repo.add_time_off(session, datetime.combine(tomorrow, time(10)), datetime.combine(tomorrow, time(12)))
    lunch = settings.model_copy(update={"lunch_break": "14:00-15:00"})

    slots = (await slots_by_day(session, lunch, 60, NOW, days=[tomorrow]))[tomorrow]
    hours = {s.time() for s in slots}
    assert time(10) not in hours and time(11, 30) not in hours  # закрыто админом
    assert time(13, 30) not in hours and time(14) not in hours  # пересекается с обедом
    assert time(12) in hours and time(15) in hours

    # Закрытое время учитывается и при финальной проверке в create_booking
    await _client(session)
    service = (await repo.list_services(session))[0]
    assert await repo.create_booking(session, 1, service, datetime.combine(tomorrow, time(10)), NOW) is None
