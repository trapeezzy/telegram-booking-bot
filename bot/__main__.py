import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, ErrorEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import Settings
from bot.db import repo
from bot.db.engine import create_session_pool
from bot.db.migrate import upgrade_db
from bot.handlers import get_routers
from bot.middlewares import DbSessionMiddleware, ThrottlingMiddleware
from bot.services.reminders import send_reminders

logger = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="book", description="Записаться"),
    BotCommand(command="my", description="Мои записи"),
    BotCommand(command="about", description="Контакты и время работы"),
    BotCommand(command="cancel", description="Отменить текущее действие"),
]


def create_storage(settings: Settings) -> BaseStorage:
    if settings.redis_url:
        from aiogram.fsm.storage.redis import RedisStorage

        return RedisStorage.from_url(settings.redis_url)
    return MemoryStorage()


def create_dispatcher(settings: Settings, session_pool: async_sessionmaker[AsyncSession]) -> Dispatcher:
    # Всё, что передано в Dispatcher(...), доступно в хендлерах по имени аргумента (settings)
    dp = Dispatcher(storage=create_storage(settings), settings=settings)
    # outer-middleware срабатывает до фильтров: флуд отсекается раньше, чем бот полезет в БД
    throttling = ThrottlingMiddleware(settings.throttle_seconds)
    dp.message.outer_middleware(throttling)
    dp.callback_query.outer_middleware(throttling)
    dp.update.middleware(DbSessionMiddleware(session_pool))
    dp.include_routers(*get_routers())

    @dp.errors()
    async def on_error(event: ErrorEvent) -> None:
        logger.exception("Ошибка при обработке апдейта %s", event.update.update_id, exc_info=event.exception)

    return dp


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings()

    # Alembic внутри вызывает asyncio.run, поэтому запускаем его в отдельном потоке
    await asyncio.to_thread(upgrade_db, settings.database_url)
    engine, session_pool = create_session_pool(settings.database_url)
    async with session_pool() as session:
        await repo.seed_services(session)

    bot = Bot(settings.bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = create_dispatcher(settings, session_pool)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        send_reminders, "interval", minutes=1, kwargs={"bot": bot, "session_pool": session_pool, "settings": settings}
    )
    scheduler.start()

    await bot.set_my_commands(COMMANDS)
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
