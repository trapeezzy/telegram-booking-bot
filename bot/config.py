from datetime import time
from zoneinfo import ZoneInfo

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from bot.utils.formatting import parse_time_range


def _parse_ints(raw: str) -> list[int]:
    return [int(part) for part in raw.replace(" ", "").split(",") if part]


class Settings(BaseSettings):
    """Настройки читаются из переменных окружения или файла .env (см. .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: SecretStr
    admin_ids: str = ""  # Telegram ID администраторов через запятую
    database_url: str = "sqlite+aiosqlite:///booking.db"
    redis_url: str | None = None  # если задан — FSM хранится в Redis и переживает рестарт

    business_name: str = "Barber Studio"
    business_address: str = "ул. Примерная, 1"
    business_phone: str = "+7 (900) 000-00-00"

    timezone: str = "Europe/Moscow"
    work_start: time = time(10, 0)
    work_end: time = time(20, 0)
    work_weekdays: str = "0,1,2,3,4,5"  # 0 — понедельник, 6 — воскресенье
    slot_step_minutes: int = 30
    booking_days_ahead: int = 14
    lunch_break: str = ""  # ежедневный перерыв, например 14:00-15:00

    max_active_bookings: int = 3  # сколько предстоящих записей может быть у одного клиента
    cancel_min_hours: int = 2  # клиент может отменить запись не позже чем за N часов; 0 — в любой момент
    throttle_seconds: float = 0.5  # антифлуд: минимальный интервал между действиями пользователя

    @field_validator("lunch_break")
    @classmethod
    def _check_lunch_break(cls, value: str) -> str:
        if value and parse_time_range(value) is None:
            raise ValueError("ожидается интервал вида 14:00-15:00")
        return value

    @property
    def daily_break(self) -> tuple[time, time] | None:
        return parse_time_range(self.lunch_break) if self.lunch_break else None

    @property
    def admins(self) -> set[int]:
        return set(_parse_ints(self.admin_ids))

    @property
    def weekdays(self) -> set[int]:
        return set(_parse_ints(self.work_weekdays))

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admins
