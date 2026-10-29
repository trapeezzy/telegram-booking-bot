from datetime import date, datetime, time, timedelta

from aiogram import Bot, F, Router, html
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db import repo
from bot.db.models import BookingStatus
from bot.filters import IsAdmin
from bot.keyboards.admin import (
    admin_bookings_kb,
    admin_menu_kb,
    admin_services_kb,
    back_kb,
    broadcast_confirm_kb,
    time_off_days_kb,
    time_off_kb,
    whole_day_kb,
)
from bot.keyboards.callbacks import AdminCancelCb, AdminCb, BroadcastCb, DeleteTimeOffCb, TimeOffDayCb, ToggleServiceCb
from bot.keyboards.menu import Btn, not_menu_button
from bot.services.notify import broadcast
from bot.states import AddService, Broadcast, TimeOffForm
from bot.utils.formatting import fmt_day, fmt_dt, fmt_money, fmt_period, now_local, parse_time_range, user_link
from bot.utils.telegram import edit_or_answer

router = Router(name="admin")
# Фильтр на весь роутер: для не-админов эти хендлеры просто не существуют
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

MENU_TEXT = "⚙️ <b>Панель администратора</b>"


@router.message(F.text == Btn.ADMIN)
@router.message(Command("admin"))
async def admin_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(MENU_TEXT, reply_markup=admin_menu_kb())


@router.callback_query(AdminCb.filter(F.action == "menu"))
async def back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_or_answer(callback, MENU_TEXT, admin_menu_kb())
    await callback.answer()


# ---------- Записи ----------

@router.callback_query(AdminCb.filter(F.action == "bookings"))
async def show_bookings(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    await edit_or_answer(callback, *await _render_bookings(session, settings))
    await callback.answer()


@router.callback_query(AdminCancelCb.filter())
async def cancel_booking(
    callback: CallbackQuery, callback_data: AdminCancelCb, session: AsyncSession, settings: Settings, bot: Bot
) -> None:
    booking = await repo.get_booking(session, callback_data.id)
    if booking is None or booking.status != BookingStatus.ACTIVE or booking.starts_at <= now_local(settings.tz):
        await callback.answer("Запись уже неактуальна", show_alert=True)
    else:
        await repo.cancel_booking(session, booking)
        try:
            await bot.send_message(
                booking.user_id,
                "😔 К сожалению, ваша запись отменена администратором:\n\n"
                f"✂️ {html.quote(booking.service.title)}\n🕒 {fmt_dt(booking.starts_at)}\n\n"
                f"Приносим извинения! Выберите, пожалуйста, другое время через «{Btn.BOOK}».",
            )
        except TelegramAPIError:
            pass
        await callback.answer("Запись отменена, клиент уведомлён")
    await edit_or_answer(callback, *await _render_bookings(session, settings))


async def _render_bookings(session: AsyncSession, settings: Settings) -> tuple[str, InlineKeyboardMarkup]:
    now = now_local(settings.tz)
    bookings = await repo.upcoming_bookings(session, now, now + timedelta(days=7))
    if not bookings:
        return "📆 На ближайшие 7 дней записей нет.", back_kb()

    lines = ["📆 <b>Записи на 7 дней</b>"]
    current_day = None
    for b in bookings:
        if b.starts_at.date() != current_day:
            current_day = b.starts_at.date()
            lines.append(f"\n<b>{fmt_day(current_day)}</b>")
        lines.append(
            f"{b.starts_at:%H:%M}–{b.ends_at:%H:%M} · {html.quote(b.service.title)} · "
            f"{user_link(b.user_id, b.user.full_name)}, {b.user.phone or '—'}"
        )
    lines.append("\nНажмите на запись ниже, чтобы отменить её.")
    return "\n".join(lines), admin_bookings_kb(bookings)


# ---------- Услуги ----------

@router.callback_query(AdminCb.filter(F.action == "services"))
async def show_services(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await edit_or_answer(callback, *await _render_services(session))
    await callback.answer()


@router.callback_query(ToggleServiceCb.filter())
async def toggle_service(callback: CallbackQuery, callback_data: ToggleServiceCb, session: AsyncSession) -> None:
    await repo.toggle_service(session, callback_data.id)
    await edit_or_answer(callback, *await _render_services(session))
    await callback.answer("Готово")


@router.callback_query(AdminCb.filter(F.action == "add_service"))
async def add_service_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddService.title)
    await callback.message.answer("Введите название новой услуги:\n\n/cancel — отмена")
    await callback.answer()


@router.message(AddService.title, F.text, not_menu_button)
async def add_service_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip()
    if not 2 <= len(title) <= 64:
        await message.answer("Название должно быть от 2 до 64 символов.")
        return
    await state.update_data(title=title)
    await state.set_state(AddService.duration)
    await message.answer("Длительность в минутах (например, 60):")


@router.message(AddService.duration, F.text, not_menu_button)
async def add_service_duration(message: Message, state: FSMContext) -> None:
    if not message.text.isdigit() or not 5 <= int(message.text) <= 480:
        await message.answer("Введите число от 5 до 480.")
        return
    await state.update_data(duration=int(message.text))
    await state.set_state(AddService.price)
    await message.answer("Цена в рублях (например, 1500):")


@router.message(AddService.price, F.text, not_menu_button)
async def add_service_price(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not message.text.isdigit():
        await message.answer("Введите цену целым числом, например 1500.")
        return
    data = await state.get_data()
    await repo.add_service(session, data["title"], data["duration"], int(message.text))
    await state.clear()
    text, kb = await _render_services(session)
    await message.answer(f"✅ Услуга добавлена\n\n{text}", reply_markup=kb)


async def _render_services(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    services = await repo.list_services(session, only_active=False)
    lines = [
        f"{'✅' if s.is_active else '🚫'} {html.quote(s.title)} — {s.duration_min} мин, {s.price} ₽" for s in services
    ]
    text = "🛠 <b>Услуги</b>\n\n" + "\n".join(lines) + "\n\nНажмите на услугу, чтобы скрыть её из записи или вернуть."
    return text, admin_services_kb(services)


# ---------- Выходные и перерывы ----------

@router.callback_query(AdminCb.filter(F.action == "time_off"))
async def show_time_off(callback: CallbackQuery, session: AsyncSession, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    await edit_or_answer(callback, *await _render_time_off(session, settings))
    await callback.answer()


@router.callback_query(DeleteTimeOffCb.filter())
async def delete_time_off(
    callback: CallbackQuery, callback_data: DeleteTimeOffCb, session: AsyncSession, settings: Settings
) -> None:
    await repo.delete_time_off(session, callback_data.id)
    await edit_or_answer(callback, *await _render_time_off(session, settings))
    await callback.answer("Время снова открыто для записи")


@router.callback_query(AdminCb.filter(F.action == "add_time_off"))
async def add_time_off_start(callback: CallbackQuery, state: FSMContext, settings: Settings) -> None:
    await state.set_state(TimeOffForm.day)
    today = now_local(settings.tz).date()
    days = [today + timedelta(days=i) for i in range(settings.booking_days_ahead)]
    await edit_or_answer(callback, "🚫 Какой день закрыть?", time_off_days_kb(days))
    await callback.answer()


@router.callback_query(TimeOffForm.day, TimeOffDayCb.filter())
async def add_time_off_day(callback: CallbackQuery, callback_data: TimeOffDayCb, state: FSMContext) -> None:
    await state.update_data(day=callback_data.value)
    await state.set_state(TimeOffForm.period)
    await edit_or_answer(
        callback,
        f"📅 <b>{fmt_day(await _time_off_day(state))}</b>\n\n"
        "Закройте весь день или отправьте интервал, например <code>13:00-15:00</code>",
        whole_day_kb(),
    )
    await callback.answer()


@router.callback_query(TimeOffForm.period, AdminCb.filter(F.action == "whole_day"))
async def add_time_off_whole_day(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, settings: Settings
) -> None:
    start = datetime.combine(await _time_off_day(state), time.min)
    await edit_or_answer(callback, *await _save_time_off(session, state, settings, start, start + timedelta(days=1)))
    await callback.answer()


@router.message(TimeOffForm.period, F.text, not_menu_button)
async def add_time_off_period(message: Message, session: AsyncSession, state: FSMContext, settings: Settings) -> None:
    if (period := parse_time_range(message.text)) is None:
        await message.answer("Не понял интервал 🤔 Пример: <code>13:00-15:00</code>")
        return
    day = await _time_off_day(state)
    start, end = (datetime.combine(day, t) for t in period)
    text, kb = await _save_time_off(session, state, settings, start, end)
    await message.answer(text, reply_markup=kb)


async def _time_off_day(state: FSMContext) -> date:
    return datetime.strptime((await state.get_data())["day"], "%Y%m%d").date()


async def _save_time_off(
    session: AsyncSession, state: FSMContext, settings: Settings, start: datetime, end: datetime
) -> tuple[str, InlineKeyboardMarkup]:
    await repo.add_time_off(session, start, end)
    await state.clear()
    header = f"✅ Закрыто: {fmt_period(start, end)}"
    # Уже существующие записи не трогаем: мастер сам решит — перенести или принять клиента
    if conflicts := await repo.bookings_overlapping(session, start, end):
        lines = [
            f"• {b.starts_at:%H:%M} {html.quote(b.service.title)} — {user_link(b.user_id, b.user.full_name)}"
            for b in conflicts
        ]
        header += (
            f"\n\n⚠️ На это время уже есть записи ({len(conflicts)}). Они не отменены — "
            "свяжитесь с клиентами или отмените их в «📆 Ближайшие записи»:\n" + "\n".join(lines)
        )
    text, kb = await _render_time_off(session, settings)
    return f"{header}\n\n{text}", kb


async def _render_time_off(session: AsyncSession, settings: Settings) -> tuple[str, InlineKeyboardMarkup]:
    items = await repo.upcoming_time_off(session, now_local(settings.tz))
    lines = [f"• {fmt_period(t.starts_at, t.ends_at)}" for t in items] or ["Пока ничего не закрыто."]
    text = "🚫 <b>Выходные и перерывы</b>\n\n" + "\n".join(lines)
    if settings.daily_break:
        start, end = settings.daily_break
        text += f"\n\nЕжедневный перерыв: {start:%H:%M}–{end:%H:%M} (задаётся в настройках)"
    if items:
        text += "\n\nНажмите на период, чтобы снова открыть его для записи."
    return text, time_off_kb(items)


# ---------- Рассылка ----------

@router.callback_query(AdminCb.filter(F.action == "broadcast"))
async def broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Broadcast.message)
    await callback.message.answer(
        "📣 Отправьте сообщение для рассылки — текст, фото или видео с подписью.\n\n/cancel — отмена"
    )
    await callback.answer()


@router.message(Broadcast.message, not_menu_button)
async def broadcast_preview(message: Message, session: AsyncSession, state: FSMContext) -> None:
    recipients = len(await repo.broadcast_recipients(session))
    await state.update_data(chat_id=message.chat.id, message_id=message.message_id)
    await state.set_state(Broadcast.confirm)
    await message.answer(f"Отправить это сообщение {recipients} пользователям?", reply_markup=broadcast_confirm_kb())


@router.callback_query(Broadcast.confirm, BroadcastCb.filter(F.action == "abort"))
async def broadcast_abort(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_or_answer(callback, "Рассылка отменена.")
    await callback.answer()


@router.callback_query(Broadcast.confirm, BroadcastCb.filter(F.action == "send"))
async def broadcast_send(callback: CallbackQuery, session: AsyncSession, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    await state.clear()
    await edit_or_answer(callback, "📣 Рассылка запущена…")
    await callback.answer()
    # Апдейты обрабатываются конкурентно, поэтому долгая рассылка не блокирует других пользователей
    sent, failed = await broadcast(bot, session, data["chat_id"], data["message_id"])
    await callback.message.answer(f"✅ Рассылка завершена\n\nДоставлено: {sent}\nНе доставлено: {failed}")


# ---------- Статистика ----------

@router.callback_query(AdminCb.filter(F.action == "stats"))
async def show_stats(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    s = await repo.get_stats(session, now_local(settings.tz))
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: {s.users}\n"
        f"📅 Предстоящих записей: {s.upcoming}\n\n"
        "<b>За последние 30 дней</b>\n"
        f"✅ Визитов: {s.completed_30d}\n"
        f"💰 Выручка: {fmt_money(s.revenue_30d)}\n"
        f"❌ Отмен: {s.cancelled_30d}\n"
        f"🏆 Популярная услуга: {html.quote(s.top_service) if s.top_service else '—'}"
    )
    await edit_or_answer(callback, text, back_kb())
    await callback.answer()
