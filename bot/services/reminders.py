"""Напоминания о визите. Задача запускается планировщиком раз в минуту и сама ищет,
кому пора напомнить. Флаги в БД гарантируют, что напоминание уйдёт ровно один раз,
даже если бот перезапускали."""

import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import Settings
from bot.db import repo
from bot.db.models import Booking
from bot.utils.formatting import fmt_dt, now_local

logger = logging.getLogger(__name__)


async def send_reminders(bot: Bot, session_pool: async_sessionmaker[AsyncSession], settings: Settings) -> None:
    now = now_local(settings.tz)
    async with session_pool() as session:
        # Сначала «за час»: если бот лежал и пропустил «за сутки», второе уже неактуально
        for booking in await repo.bookings_to_remind(session, now, timedelta(hours=1), Booking.reminded_hour):
            await _send(bot, session, booking, "⏰ Через час у вас визит!", settings)
            booking.reminded_hour = booking.reminded_day = True
        await session.commit()

        for booking in await repo.bookings_to_remind(session, now, timedelta(hours=24), Booking.reminded_day):
            await _send(bot, session, booking, "🔔 Напоминаем о записи на завтра.", settings)
            booking.reminded_day = True
        await session.commit()


async def _send(bot: Bot, session: AsyncSession, booking: Booking, title: str, settings: Settings) -> None:
    text = (
        f"{title}\n\n"
        f"✂️ {booking.service.title}\n"
        f"🕒 {fmt_dt(booking.starts_at)}\n"
        f"📍 {settings.business_address}\n\n"
        "Если планы изменились — отмените запись в разделе «📋 Мои записи»."
    )
    try:
        await bot.send_message(booking.user_id, text)
    except TelegramForbiddenError:
        booking.user.is_blocked = True  # клиент заблокировал бота — исключаем из рассылок
    except TelegramAPIError:
        logger.warning("Не удалось отправить напоминание по записи %s", booking.id)
