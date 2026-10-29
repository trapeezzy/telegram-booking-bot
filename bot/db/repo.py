"""Все запросы к БД собраны здесь, чтобы хендлеры не знали про SQL."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from bot.db.models import Booking, BookingStatus, Service, TimeOff, User

DEFAULT_SERVICES = [
    ("Мужская стрижка", 60, 1500),
    ("Стрижка бороды", 30, 900),
    ("Стрижка + борода", 90, 2200),
    ("Детская стрижка", 45, 1000),
]


# ---------- Пользователи ----------

async def upsert_user(session: AsyncSession, user_id: int, full_name: str, username: str | None) -> User:
    user = await session.get(User, user_id)
    if user is None:
        user = User(id=user_id, full_name=full_name, username=username)
        session.add(user)
    else:
        user.full_name = full_name
        user.username = username
        user.is_blocked = False
    await session.commit()
    return user


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def set_phone(session: AsyncSession, user_id: int, phone: str) -> None:
    user = await session.get(User, user_id)
    if user is not None:
        user.phone = phone
        await session.commit()


async def broadcast_recipients(session: AsyncSession) -> list[int]:
    return list(await session.scalars(select(User.id).where(User.is_blocked.is_(False))))


async def mark_blocked(session: AsyncSession, user_id: int) -> None:
    user = await session.get(User, user_id)
    if user is not None:
        user.is_blocked = True
        await session.commit()


# ---------- Услуги ----------

async def seed_services(session: AsyncSession) -> None:
    if await session.scalar(select(func.count()).select_from(Service)):
        return
    session.add_all(Service(title=t, duration_min=d, price=p) for t, d, p in DEFAULT_SERVICES)
    await session.commit()


async def list_services(session: AsyncSession, *, only_active: bool = True) -> Sequence[Service]:
    stmt = select(Service).order_by(Service.id)
    if only_active:
        stmt = stmt.where(Service.is_active.is_(True))
    return (await session.scalars(stmt)).all()


async def get_service(session: AsyncSession, service_id: int) -> Service | None:
    return await session.get(Service, service_id)


async def add_service(session: AsyncSession, title: str, duration_min: int, price: int) -> Service:
    service = Service(title=title, duration_min=duration_min, price=price)
    session.add(service)
    await session.commit()
    return service


async def toggle_service(session: AsyncSession, service_id: int) -> None:
    service = await session.get(Service, service_id)
    if service is not None:
        service.is_active = not service.is_active
        await session.commit()


# ---------- Записи ----------

async def busy_intervals(session: AsyncSession, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Занятые интервалы, пересекающиеся с [start, end): активные записи и закрытое время."""
    bookings = select(Booking.starts_at, Booking.ends_at).where(
        Booking.status == BookingStatus.ACTIVE, Booking.starts_at < end, Booking.ends_at > start
    )
    time_off = select(TimeOff.starts_at, TimeOff.ends_at).where(TimeOff.starts_at < end, TimeOff.ends_at > start)
    rows = await session.execute(bookings.union_all(time_off))
    return [(s, e) for s, e in rows]


async def count_user_upcoming(session: AsyncSession, user_id: int, now: datetime) -> int:
    return await session.scalar(
        select(func.count()).where(
            Booking.user_id == user_id, Booking.status == BookingStatus.ACTIVE, Booking.starts_at > now
        )
    ) or 0


async def create_booking(
    session: AsyncSession, user_id: int, service: Service, starts_at: datetime, now: datetime
) -> Booking | None:
    """Создаёт запись, если время ещё свободно. Возвращает None, если слот успели занять."""
    ends_at = starts_at + timedelta(minutes=service.duration_min)
    if await busy_intervals(session, starts_at, ends_at):
        return None

    lead = starts_at - now
    booking = Booking(
        user_id=user_id,
        service=service,
        starts_at=starts_at,
        ends_at=ends_at,
        price=service.price,
        # Если до визита меньше суток/часа — соответствующее напоминание уже не нужно
        reminded_day=lead <= timedelta(hours=24),
        reminded_hour=lead <= timedelta(hours=1),
    )
    session.add(booking)
    await session.commit()
    return booking


async def get_booking(session: AsyncSession, booking_id: int) -> Booking | None:
    return await session.get(Booking, booking_id)


async def cancel_booking(session: AsyncSession, booking: Booking) -> None:
    booking.status = BookingStatus.CANCELLED
    await session.commit()


async def user_upcoming(session: AsyncSession, user_id: int, now: datetime) -> Sequence[Booking]:
    stmt = (
        select(Booking)
        .where(Booking.user_id == user_id, Booking.status == BookingStatus.ACTIVE, Booking.starts_at > now)
        .order_by(Booking.starts_at)
    )
    return (await session.scalars(stmt)).all()


async def upcoming_bookings(session: AsyncSession, start: datetime, end: datetime, limit: int = 30) -> Sequence[Booking]:
    stmt = (
        select(Booking)
        .where(Booking.status == BookingStatus.ACTIVE, Booking.starts_at > start, Booking.starts_at < end)
        .order_by(Booking.starts_at)
        .limit(limit)
    )
    return (await session.scalars(stmt)).all()


async def bookings_to_remind(
    session: AsyncSession, now: datetime, within: timedelta, flag: InstrumentedAttribute[bool]
) -> Sequence[Booking]:
    stmt = select(Booking).where(
        Booking.status == BookingStatus.ACTIVE,
        Booking.starts_at > now,
        Booking.starts_at <= now + within,
        flag.is_(False),
    )
    return (await session.scalars(stmt)).all()


# ---------- Закрытое время ----------

async def add_time_off(session: AsyncSession, starts_at: datetime, ends_at: datetime) -> TimeOff:
    time_off = TimeOff(starts_at=starts_at, ends_at=ends_at)
    session.add(time_off)
    await session.commit()
    return time_off


async def upcoming_time_off(session: AsyncSession, now: datetime) -> Sequence[TimeOff]:
    return (await session.scalars(select(TimeOff).where(TimeOff.ends_at > now).order_by(TimeOff.starts_at))).all()


async def delete_time_off(session: AsyncSession, time_off_id: int) -> None:
    if (time_off := await session.get(TimeOff, time_off_id)) is not None:
        await session.delete(time_off)
        await session.commit()


async def bookings_overlapping(session: AsyncSession, start: datetime, end: datetime) -> Sequence[Booking]:
    stmt = select(Booking).where(
        Booking.status == BookingStatus.ACTIVE, Booking.starts_at < end, Booking.ends_at > start
    ).order_by(Booking.starts_at)
    return (await session.scalars(stmt)).all()


# ---------- Статистика ----------

@dataclass(frozen=True)
class Stats:
    users: int
    upcoming: int
    completed_30d: int
    revenue_30d: int
    cancelled_30d: int
    top_service: str | None


async def get_stats(session: AsyncSession, now: datetime) -> Stats:
    month_ago = now - timedelta(days=30)
    active = Booking.status == BookingStatus.ACTIVE
    last_month = (Booking.starts_at >= month_ago) & (Booking.starts_at <= now)

    completed, revenue = (
        await session.execute(select(func.count(), func.coalesce(func.sum(Booking.price), 0)).where(active, last_month))
    ).one()
    top_service = await session.scalar(
        select(Service.title)
        .join(Booking, Booking.service_id == Service.id)
        .where(active, Booking.starts_at >= month_ago)
        .group_by(Service.id)
        .order_by(func.count().desc())
        .limit(1)
    )
    return Stats(
        users=await session.scalar(select(func.count()).select_from(User)) or 0,
        upcoming=await session.scalar(select(func.count()).where(active, Booking.starts_at > now)) or 0,
        completed_30d=completed,
        revenue_30d=revenue,
        cancelled_30d=await session.scalar(
            select(func.count()).where(Booking.status == BookingStatus.CANCELLED, Booking.starts_at >= month_ago)
        )
        or 0,
        top_service=top_service,
    )
