import html
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def now_local(tz: ZoneInfo) -> datetime:
    """Текущее время заведения без tzinfo — в том же виде, в каком время хранится в БД."""
    return datetime.now(tz).replace(tzinfo=None, microsecond=0)


def fmt_day_short(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d:%d.%m}"


def fmt_day(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}, {WEEKDAYS[d.weekday()].lower()}"


def fmt_dt(dt: datetime) -> str:
    return f"{fmt_day(dt)}, {dt:%H:%M}"


def fmt_money(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " ₽"


def fmt_weekdays(weekdays: set[int]) -> str:
    days = sorted(weekdays)
    if len(days) > 2 and days == list(range(days[0], days[-1] + 1)):
        return f"{WEEKDAYS[days[0]]}–{WEEKDAYS[days[-1]]}"
    return ", ".join(WEEKDAYS[d] for d in days)


def fmt_period(start: datetime, end: datetime) -> str:
    if start.time() == time.min and end == start + timedelta(days=1):
        return f"{fmt_day(start.date())} — весь день"
    return f"{fmt_day(start.date())}, {start:%H:%M}–{end:%H:%M}"


def user_link(user_id: int, name: str) -> str:
    """Кликабельное имя: открывает профиль клиента в Telegram."""
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


def parse_time_range(raw: str) -> tuple[time, time] | None:
    """'13:00-15:00' (также 13.00–15.00, 9:00 - 10:30) -> (13:00, 15:00). None, если формат неверный."""
    match = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*[-–—]\s*(\d{1,2})[:.](\d{2})\s*", raw)
    if not match:
        return None
    h1, m1, h2, m2 = map(int, match.groups())
    if not (h1 < 24 and h2 < 24 and m1 < 60 and m2 < 60):
        return None
    start, end = time(h1, m1), time(h2, m2)
    return (start, end) if start < end else None


def normalize_phone(raw: str) -> str | None:
    """'8 (900) 123-45-67' -> '+79001234567'. None, если это не похоже на номер."""
    if re.search(r"[^\d\s()+\-]", raw):
        return None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if not 10 <= len(digits) <= 15:
        return None
    return "+" + digits
