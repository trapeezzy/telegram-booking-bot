"""Сквозные тесты: апдейты прогоняются через настоящий Dispatcher со всеми роутерами,
а вместо Telegram API подставлена сессия, которая записывает исходящие запросы."""

import itertools
from datetime import datetime, timedelta
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import CopyMessage, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import Chat, InlineKeyboardMarkup, Message, MessageId
from sqlalchemy import select

from bot.__main__ import create_dispatcher
from bot.db import repo
from bot.db.models import Booking, BookingStatus, User
from bot.keyboards.menu import Btn
from bot.services.reminders import send_reminders
from bot.utils.formatting import fmt_day_short, now_local

CLIENT = {"id": 1, "is_bot": False, "first_name": "Иван", "last_name": "Петров", "username": "ivan"}
ADMIN = {"id": 999, "is_bot": False, "first_name": "Админ"}


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self.blocked_by: set[int] = set()  # чаты пользователей, заблокировавших бота
        self._ids = itertools.count(1000)

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        self.requests.append(method)
        if getattr(method, "chat_id", None) in self.blocked_by:
            raise TelegramForbiddenError(method=method, message="Forbidden: bot was blocked by the user")
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message(
                message_id=next(self._ids),
                date=datetime.now(),
                chat=Chat(id=method.chat_id or 0, type="private"),
                text=method.text,
                reply_markup=method.reply_markup if isinstance(method.reply_markup, InlineKeyboardMarkup) else None,
            )
        if isinstance(method, CopyMessage):
            return MessageId(message_id=next(self._ids))
        return True

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError

    async def close(self) -> None:
        pass


class BotHarness:
    """Имитирует пользователя: пишет боту, жмёт кнопки, читает ответы."""

    def __init__(self, settings, session_pool) -> None:
        self.session = FakeSession()
        self.bot = Bot("42:TEST", session=self.session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.dp = create_dispatcher(settings, session_pool)
        self._ids = itertools.count(1)

    async def send(self, user: dict, text: str | None = None, **extra: Any) -> None:
        message = {"message_id": next(self._ids), "date": int(datetime.now().timestamp()),
                   "chat": {"id": user["id"], "type": "private"}, "from": user, **extra}
        if text is not None:
            message["text"] = text
            if text.startswith("/"):
                message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        await self._feed({"message": message})

    async def click(self, user: dict, button_text: str) -> None:
        """Нажимает inline-кнопку из последнего сообщения бота этому пользователю."""
        for row in self.last_markup(user["id"]).inline_keyboard:
            for button in row:
                if button_text in button.text:
                    await self._feed({"callback_query": {
                        "id": str(next(self._ids)), "from": user, "chat_instance": "test", "data": button.callback_data,
                        "message": {"message_id": 1, "date": 0, "chat": {"id": user["id"], "type": "private"},
                                    "text": "..."},
                    }})
                    return
        raise AssertionError(f"Кнопка «{button_text}» не найдена")

    async def click_first(self, user: dict) -> str:
        button = self.last_markup(user["id"]).inline_keyboard[0][0]
        await self.click(user, button.text)
        return button.text

    def texts(self, chat_id: int) -> list[str]:
        return [m.text for m in self.session.requests
                if isinstance(m, (SendMessage, EditMessageText)) and m.chat_id == chat_id]

    def last_text(self, chat_id: int) -> str:
        return self.texts(chat_id)[-1]

    def last_markup(self, chat_id: int) -> InlineKeyboardMarkup:
        for m in reversed(self.session.requests):
            if isinstance(m, (SendMessage, EditMessageText)) and m.chat_id == chat_id:
                if isinstance(m.reply_markup, InlineKeyboardMarkup):
                    return m.reply_markup
        raise AssertionError("У бота нет сообщений с inline-кнопками")

    async def _feed(self, update: dict) -> None:
        await self.dp.feed_raw_update(self.bot, {"update_id": next(self._ids), **update})


@pytest.fixture
def make_harness(settings, session_pool):
    """Фабрика: make_harness(max_active_bookings=1) — бот с изменёнными настройками. Один бот на тест."""
    created: list[BotHarness] = []

    def factory(**overrides: Any) -> BotHarness:
        created.append(BotHarness(settings.model_copy(update=overrides), session_pool))
        return created[-1]

    yield factory
    # Роутеры объявлены на уровне модулей и могут быть прикреплены только к одному диспетчеру,
    # а в тестах диспетчер свой на каждый тест — отцепляем их обратно
    for h in created:
        for router in h.dp.sub_routers:
            router._parent_router = None


@pytest.fixture
def harness(make_harness) -> BotHarness:
    return make_harness()


async def _book(h: BotHarness, user: dict) -> str:
    await h.send(user, "/start")
    await h.send(user, Btn.BOOK)
    await h.click(user, "Мужская стрижка")
    await h.click_first(user)              # дата
    return await h.click_first(user)       # время


async def test_full_booking_flow(harness, session_pool):
    h = harness
    slot = await _book(h, CLIENT)
    assert "Оставьте номер телефона" in h.last_text(CLIENT["id"])

    await h.send(CLIENT, contact={"phone_number": "79001234567", "first_name": "Иван", "user_id": CLIENT["id"]})
    assert "Проверьте запись" in h.last_text(CLIENT["id"])
    assert "+79001234567" in h.last_text(CLIENT["id"])

    await h.click(CLIENT, "Подтвердить")
    assert "Вы записаны" in h.last_text(CLIENT["id"])
    assert slot in h.last_text(CLIENT["id"])
    assert "Новая запись" in h.last_text(ADMIN["id"])  # админ получил уведомление

    async with session_pool() as session:
        booking = (await session.scalars(select(Booking))).one()
        assert booking.status == BookingStatus.ACTIVE
        assert booking.user.phone == "+79001234567"


async def test_phone_is_asked_only_once(harness):
    h = harness
    await _book(h, CLIENT)
    await h.send(CLIENT, "8 900 123-45-67")
    await h.click(CLIENT, "Подтвердить")

    await _book(h, CLIENT)
    assert "Проверьте запись" in h.last_text(CLIENT["id"])  # сразу подтверждение, без шага с телефоном


async def test_taken_slot_is_not_offered_again(harness):
    h = harness
    first_slot = await _book(h, CLIENT)
    await h.send(CLIENT, "+79001234567")
    await h.click(CLIENT, "Подтвердить")

    other = {**CLIENT, "id": 2, "username": "petr", "first_name": "Пётр"}
    await h.send(other, Btn.BOOK)
    await h.click(other, "Мужская стрижка")
    await h.click_first(other)
    offered = [b.text for row in h.last_markup(other["id"]).inline_keyboard for b in row]
    assert first_slot not in offered


async def test_client_cancels_booking(harness, session_pool):
    h = harness
    await _book(h, CLIENT)
    await h.send(CLIENT, "+79001234567")
    await h.click(CLIENT, "Подтвердить")

    await h.send(CLIENT, Btn.MY)
    assert "Ваши записи" in h.last_text(CLIENT["id"])
    await h.click(CLIENT, "Отменить")
    assert "нет предстоящих записей" in h.last_text(CLIENT["id"])
    assert "Клиент отменил запись" in h.last_text(ADMIN["id"])

    async with session_pool() as session:
        booking = (await session.scalars(select(Booking))).one()
        assert booking.status == BookingStatus.CANCELLED


async def test_menu_button_works_in_the_middle_of_a_dialog(harness):
    h = harness
    await _book(h, CLIENT)               # бот ждёт телефон
    await h.send(CLIENT, Btn.MY)         # а пользователь передумал
    assert "нет предстоящих записей" in h.last_text(CLIENT["id"])


async def test_admin_panel_is_hidden_from_clients(harness):
    h = harness
    await h.send(CLIENT, "/admin")
    assert "Панель администратора" not in h.last_text(CLIENT["id"])

    await h.send(ADMIN, "/admin")
    assert "Панель администратора" in h.last_text(ADMIN["id"])
    await h.click(ADMIN, "Статистика")
    assert "Статистика" in h.last_text(ADMIN["id"])


async def test_admin_adds_service(harness):
    h = harness
    await h.send(ADMIN, "/admin")
    await h.click(ADMIN, "Услуги")
    await h.click(ADMIN, "Добавить услугу")
    await h.send(ADMIN, "Камуфляж седины")
    await h.send(ADMIN, "40")
    await h.send(ADMIN, "1200")
    assert "Камуфляж седины — 40 мин, 1200 ₽" in h.last_text(ADMIN["id"])

    await h.send(CLIENT, Btn.BOOK)
    assert any("Камуфляж седины" in b.text for row in h.last_markup(CLIENT["id"]).inline_keyboard for b in row)


async def test_admin_cancels_booking_and_client_is_notified(harness):
    h = harness
    await _book(h, CLIENT)
    await h.send(CLIENT, "+79001234567")
    await h.click(CLIENT, "Подтвердить")

    await h.send(ADMIN, "/admin")
    await h.click(ADMIN, "Ближайшие записи")
    assert "Иван Петров" in h.last_text(ADMIN["id"])
    await h.click(ADMIN, "Иван Петров")
    assert "отменена администратором" in h.last_text(CLIENT["id"])


async def test_broadcast(harness):
    h = harness
    await h.send(CLIENT, "/start")
    await h.send({**CLIENT, "id": 2}, "/start")
    await h.send(ADMIN, "/admin")
    await h.click(ADMIN, "Рассылка")
    await h.send(ADMIN, "Скидка 20% в эту пятницу!")
    assert "2 пользователям" in h.last_text(ADMIN["id"])
    await h.click(ADMIN, "Отправить")
    assert "Доставлено: 2" in h.last_text(ADMIN["id"])
    assert sum(isinstance(m, CopyMessage) for m in h.session.requests) == 2


async def _booking_in(session_pool, settings, minutes: int) -> None:
    """Запись клиента через `minutes` минут, созданная заранее (чтобы напоминания ещё не были отправлены)."""
    async with session_pool() as session:
        await repo.upsert_user(session, CLIENT["id"], "Иван Петров", "ivan")
        service = (await repo.list_services(session))[0]
        starts_at = now_local(settings.tz) + timedelta(minutes=minutes)
        await repo.create_booking(session, CLIENT["id"], service, starts_at, now=starts_at - timedelta(days=2))


async def test_reminder_is_sent_exactly_once(harness, session_pool, settings):
    await _booking_in(session_pool, settings, minutes=40)
    await send_reminders(harness.bot, session_pool, settings)
    await send_reminders(harness.bot, session_pool, settings)
    reminders = [t for t in harness.texts(CLIENT["id"]) if "Через час" in t]
    assert len(reminders) == 1


async def test_client_who_blocked_bot_is_excluded_from_broadcasts(harness, session_pool, settings):
    await _booking_in(session_pool, settings, minutes=40)
    harness.session.blocked_by.add(CLIENT["id"])
    await send_reminders(harness.bot, session_pool, settings)

    async with session_pool() as session:
        assert (await session.get(User, CLIENT["id"])).is_blocked
        assert await repo.broadcast_recipients(session) == []


async def test_booking_limit(make_harness):
    h = make_harness(max_active_bookings=1)
    await _book(h, CLIENT)
    await h.send(CLIENT, "+79001234567")
    await h.click(CLIENT, "Подтвердить")

    await h.send(CLIENT, Btn.BOOK)
    assert "Достигнут лимит" in h.last_text(CLIENT["id"])


async def test_late_cancellation_is_not_allowed(make_harness):
    h = make_harness(cancel_min_hours=48)  # ближайший слот всегда меньше чем через 48 ч
    await _book(h, CLIENT)
    await h.send(CLIENT, "+79001234567")
    await h.click(CLIENT, "Подтвердить")

    await h.send(CLIENT, Btn.MY)
    last = h.session.requests[-1]
    assert "позвоните нам" in last.text
    assert last.reply_markup is None  # кнопки отмены нет


async def test_throttling_drops_flood(make_harness):
    h = make_harness(throttle_seconds=10)
    for _ in range(5):
        await h.send(CLIENT, "/start")
    assert sum("Здравствуйте" in t for t in h.texts(CLIENT["id"])) == 1


async def _close(h: BotHarness, day_label: str, period: str | None = None) -> None:
    await h.send(ADMIN, "/admin")
    await h.click(ADMIN, "Выходные и перерывы")
    await h.click(ADMIN, "Закрыть время")
    await h.click(ADMIN, day_label)
    if period is None:
        await h.click(ADMIN, "Весь день")
    else:
        await h.send(ADMIN, period)


def _tomorrow(settings) -> str:
    return fmt_day_short(now_local(settings.tz).date() + timedelta(days=1))


async def test_closed_day_is_not_offered(harness, settings):
    h = harness
    await _close(h, _tomorrow(settings))
    assert "весь день" in h.last_text(ADMIN["id"])

    await h.send(CLIENT, Btn.BOOK)
    await h.click(CLIENT, "Мужская стрижка")
    offered_days = [b.text for row in h.last_markup(CLIENT["id"]).inline_keyboard for b in row]
    assert _tomorrow(settings) not in offered_days


async def test_closing_time_warns_about_existing_bookings(harness, settings):
    h = harness
    await h.send(CLIENT, Btn.BOOK)
    await h.click(CLIENT, "Мужская стрижка")
    await h.click(CLIENT, _tomorrow(settings))
    await h.click(CLIENT, "10:00")
    await h.send(CLIENT, "+79001234567")
    await h.click(CLIENT, "Подтвердить")

    await _close(h, _tomorrow(settings), "10:00-13:00")
    assert "уже есть записи (1)" in h.last_text(ADMIN["id"])

    await h.send(CLIENT, Btn.BOOK)
    await h.click(CLIENT, "Мужская стрижка")
    await h.click(CLIENT, _tomorrow(settings))
    first_slot = h.last_markup(CLIENT["id"]).inline_keyboard[0][0].text
    assert first_slot == "13:00"


async def test_admin_reopens_closed_time(harness, settings):
    h = harness
    await _close(h, _tomorrow(settings))
    await h.click(ADMIN, "🗑")
    assert "Пока ничего не закрыто" in h.last_text(ADMIN["id"])
