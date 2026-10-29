from datetime import datetime, timedelta

from aiogram import Bot, F, Router, html
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db import repo
from bot.db.models import Booking, BookingStatus
from bot.keyboards.booking import my_bookings_kb
from bot.keyboards.callbacks import CancelBookingCb
from bot.keyboards.menu import Btn
from bot.services.notify import notify_admins
from bot.utils.formatting import fmt_dt, now_local, user_link
from bot.utils.telegram import edit_or_answer

router = Router(name="my_bookings")


@router.message(F.text == Btn.MY)
@router.message(Command("my"))
async def my_bookings(message: Message, session: AsyncSession, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    text, kb = await _render(session, message.from_user.id, settings)
    await message.answer(text, reply_markup=kb)


@router.callback_query(CancelBookingCb.filter())
async def cancel_booking(
    callback: CallbackQuery, callback_data: CancelBookingCb, session: AsyncSession, settings: Settings, bot: Bot
) -> None:
    booking = await repo.get_booking(session, callback_data.id)
    now = now_local(settings.tz)
    if (
        booking is None
        or booking.user_id != callback.from_user.id
        or booking.status != BookingStatus.ACTIVE
        or booking.starts_at <= now
    ):
        await callback.answer("Эта запись уже неактуальна", show_alert=True)
    elif not _can_cancel(booking, now, settings):
        await callback.answer(_late_cancel_text(settings), show_alert=True)
    else:
        await repo.cancel_booking(session, booking)
        await callback.answer("Запись отменена")
        await notify_admins(
            bot,
            settings.admins,
            f"❌ <b>Клиент отменил запись</b>\n\n✂️ {html.quote(booking.service.title)}\n"
            f"🕒 {fmt_dt(booking.starts_at)}\n👤 {user_link(booking.user_id, booking.user.full_name)}",
        )

    text, kb = await _render(session, callback.from_user.id, settings)
    await edit_or_answer(callback, text, kb)


def _can_cancel(booking: Booking, now: datetime, settings: Settings) -> bool:
    return booking.starts_at - now >= timedelta(hours=settings.cancel_min_hours)


def _late_cancel_text(settings: Settings) -> str:
    return (
        f"Отменить запись через бота можно не позже чем за {settings.cancel_min_hours} ч до визита. "
        f"Пожалуйста, позвоните нам: {settings.business_phone}"
    )


async def _render(session: AsyncSession, user_id: int, settings: Settings) -> tuple[str, InlineKeyboardMarkup | None]:
    now = now_local(settings.tz)
    bookings = await repo.user_upcoming(session, user_id, now)
    if not bookings:
        return f"У вас нет предстоящих записей.\nНажмите «{Btn.BOOK}», чтобы выбрать время.", None

    lines = [f"• <b>{fmt_dt(b.starts_at)}</b> — {html.quote(b.service.title)}" for b in bookings]
    text = "📋 <b>Ваши записи:</b>\n\n" + "\n".join(lines)
    cancellable = [b for b in bookings if _can_cancel(b, now, settings)]
    if len(cancellable) < len(bookings):
        text += f"\n\nℹ️ {html.quote(_late_cancel_text(settings))}"
    return text, my_bookings_kb(cancellable) if cancellable else None
