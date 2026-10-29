import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repo

logger = logging.getLogger(__name__)


async def notify_admins(bot: Bot, admin_ids: set[int], text: str) -> None:
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except TelegramAPIError:
            logger.warning("Не удалось уведомить администратора %s", admin_id)


async def broadcast(bot: Bot, session: AsyncSession, from_chat_id: int, message_id: int) -> tuple[int, int]:
    """Копирует сообщение всем пользователям. Поддерживает любой тип контента (текст, фото, видео).
    Возвращает (доставлено, не доставлено)."""
    sent = failed = 0
    for user_id in await repo.broadcast_recipients(session):
        for _ in range(2):  # вторая попытка — после паузы, если упёрлись в лимит Telegram
            try:
                await bot.copy_message(user_id, from_chat_id, message_id)
                sent += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except TelegramForbiddenError:
                await repo.mark_blocked(session, user_id)
                failed += 1
                break
            except TelegramAPIError:
                failed += 1
                break
        else:
            failed += 1
        await asyncio.sleep(0.05)  # ~20 сообщений в секунду — с запасом до лимита в 30
    return sent, failed
