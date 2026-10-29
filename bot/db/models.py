from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, ForeignKey, Index, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class BookingStatus(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"


class User(Base):
    __tablename__ = "users"

    # Первичный ключ — Telegram ID, поэтому без автоинкремента
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    full_name: Mapped[str] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str | None] = mapped_column(String(20))
    is_blocked: Mapped[bool] = mapped_column(default=False)  # пользователь заблокировал бота
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(64))
    duration_min: Mapped[int]
    price: Mapped[int]
    is_active: Mapped[bool] = mapped_column(default=True)


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (Index("ix_bookings_status_starts_at", "status", "starts_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    # Время хранится «по часам заведения» (наивное, в таймзоне из настроек)
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    price: Mapped[int]  # цена фиксируется на момент записи — услуга может подорожать
    status: Mapped[BookingStatus] = mapped_column(default=BookingStatus.ACTIVE)
    reminded_day: Mapped[bool] = mapped_column(default=False)
    reminded_hour: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped[User] = relationship(lazy="joined")
    service: Mapped[Service] = relationship(lazy="joined")


class TimeOff(Base):
    """Закрытое для записи время: выходной, отпуск, перерыв."""

    __tablename__ = "time_off"

    id: Mapped[int] = mapped_column(primary_key=True)
    starts_at: Mapped[datetime] = mapped_column(index=True)
    ends_at: Mapped[datetime]
