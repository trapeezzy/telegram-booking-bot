from collections.abc import Sequence
from datetime import date, datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.models import Booking, Service
from bot.keyboards.callbacks import BookNavCb, CancelBookingCb, DayCb, ServiceCb, SlotCb
from bot.utils.formatting import fmt_day_short


def services_kb(services: Sequence[Service]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for s in services:
        builder.button(text=f"{s.title} · {s.price} ₽", callback_data=ServiceCb(id=s.id))
    builder.adjust(1)
    return builder.as_markup()


def days_kb(days: Sequence[date]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d in days:
        builder.button(text=fmt_day_short(d), callback_data=DayCb(value=f"{d:%Y%m%d}"))
    builder.adjust(3)
    builder.row(_nav_button("← К услугам", "services"))
    return builder.as_markup()


def slots_kb(slots: Sequence[datetime]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for s in slots:
        builder.button(text=f"{s:%H:%M}", callback_data=SlotCb(value=f"{s:%Y%m%d%H%M}"))
    builder.adjust(4)
    builder.row(_nav_button("← К датам", "days"))
    return builder.as_markup()


def _nav_button(text: str, action: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=BookNavCb(action=action).pack())


def back_to_services_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="← К услугам", callback_data=BookNavCb(action="services"))
    return builder.as_markup()


def confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=BookNavCb(action="confirm"))
    builder.button(text="✖️ Отмена", callback_data=BookNavCb(action="abort"))
    builder.adjust(2)
    return builder.as_markup()


def my_bookings_kb(bookings: Sequence[Booking]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for b in bookings:
        builder.button(text=f"❌ Отменить {b.starts_at:%d.%m %H:%M}", callback_data=CancelBookingCb(id=b.id))
    builder.adjust(1)
    return builder.as_markup()
