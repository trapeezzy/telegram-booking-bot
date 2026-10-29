from collections.abc import Sequence
from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db.models import Booking, Service, TimeOff
from bot.keyboards.callbacks import (
    AdminCancelCb,
    AdminCb,
    BroadcastCb,
    DeleteTimeOffCb,
    TimeOffDayCb,
    ToggleServiceCb,
)
from bot.utils.formatting import fmt_day_short, fmt_period


def admin_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📆 Ближайшие записи", callback_data=AdminCb(action="bookings"))
    builder.button(text="🚫 Выходные и перерывы", callback_data=AdminCb(action="time_off"))
    builder.button(text="🛠 Услуги", callback_data=AdminCb(action="services"))
    builder.button(text="📣 Рассылка", callback_data=AdminCb(action="broadcast"))
    builder.button(text="📊 Статистика", callback_data=AdminCb(action="stats"))
    builder.adjust(1, 1, 1, 2)
    return builder.as_markup()


def time_off_kb(items: Sequence[TimeOff]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for t in items:
        builder.button(text=f"🗑 {fmt_period(t.starts_at, t.ends_at)}", callback_data=DeleteTimeOffCb(id=t.id))
    builder.button(text="➕ Закрыть время", callback_data=AdminCb(action="add_time_off"))
    builder.button(text="← Назад", callback_data=AdminCb(action="menu"))
    builder.adjust(1)
    return builder.as_markup()


def time_off_days_kb(days: Sequence[date]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d in days:
        builder.button(text=fmt_day_short(d), callback_data=TimeOffDayCb(value=f"{d:%Y%m%d}"))
    builder.adjust(4)
    builder.row(InlineKeyboardButton(text="← Назад", callback_data=AdminCb(action="time_off").pack()))
    return builder.as_markup()


def whole_day_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🌴 Весь день", callback_data=AdminCb(action="whole_day"))
    builder.button(text="← Назад", callback_data=AdminCb(action="add_time_off"))
    builder.adjust(1)
    return builder.as_markup()


def back_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="← Назад", callback_data=AdminCb(action="menu"))
    return builder.as_markup()


def admin_bookings_kb(bookings: Sequence[Booking]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for b in bookings:
        builder.button(
            text=f"❌ {b.starts_at:%d.%m %H:%M} · {b.user.full_name}",
            callback_data=AdminCancelCb(id=b.id),
        )
    builder.button(text="← Назад", callback_data=AdminCb(action="menu"))
    builder.adjust(1)
    return builder.as_markup()


def admin_services_kb(services: Sequence[Service]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for s in services:
        mark = "✅" if s.is_active else "🚫"
        builder.button(text=f"{mark} {s.title}", callback_data=ToggleServiceCb(id=s.id))
    builder.button(text="➕ Добавить услугу", callback_data=AdminCb(action="add_service"))
    builder.button(text="← Назад", callback_data=AdminCb(action="menu"))
    builder.adjust(1)
    return builder.as_markup()


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📣 Отправить", callback_data=BroadcastCb(action="send"))
    builder.button(text="✖️ Отмена", callback_data=BroadcastCb(action="abort"))
    builder.adjust(2)
    return builder.as_markup()
