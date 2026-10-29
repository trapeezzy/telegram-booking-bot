import pytest

from bot.config import Settings
from bot.db import repo
from bot.db.engine import create_session_pool
from bot.db.models import Base


@pytest.fixture
def settings() -> Settings:
    return Settings(
        bot_token="42:TEST",
        admin_ids="999",
        work_weekdays="0,1,2,3,4,5,6",
        cancel_min_hours=0,
        throttle_seconds=0,  # тест «нажимает» кнопки быстрее любого человека
        _env_file=None,
    )


@pytest.fixture
async def session_pool(tmp_path):
    engine, pool = create_session_pool(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    # Тестам схема нужна быстро — создаём по моделям. Что миграции дают ту же схему, проверяет test_migrations.py
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with pool() as session:
        await repo.seed_services(session)
    yield pool
    await engine.dispose()


@pytest.fixture
async def session(session_pool):
    async with session_pool() as session:
        yield session
