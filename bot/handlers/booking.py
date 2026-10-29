"""Сценарий записи: услуга → дата → время → телефон → подтверждение."""

import asyncio
from datetime import datetime

from aiogram import Bot, F, Router, html
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db import repo
from bot.db.models import Service
from bot.keyboards.booking import back_to_services_kb, confirm_kb, days_kb, services_kb, slots_kb
from bot.keyboards.callbacks import BookNavCb, DayCb, ServiceCb, SlotCb
from bot.keyboards.menu import Btn, main_menu, not_menu_button, phone_request
from bot.services.notify import notify_admins
from bot.services.slots import slots_by_day
from bot.states import BookingForm
from bot.utils.formatting import fmt_day, fmt_dt, normalize_phone, now_local, user_link
from bot.utils.telegram import edit_or_answer

router = Router(name="booking")

SLOT_FMT = "%Y%m%d%H%M"

# Не даёт двум клиентам одновременно подтвердить один и тот же слот в рамках процесса.
# Если запускать несколько копий бота — нужен exclusion constraint в Postgres.
_booking_lock = asyncio.Lock()


# ---------- Шаг 1: услуга ----------

@router.message(F.text == Btn.BOOK)
@router.message(Command("book"))
async def start_booking(message: Message, session: AsyncSession, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    if await _limit_reached(session, settings, message.from_user.id):
        await message.answer(_limit_text(settings))
        return
    services = await repo.list_services(session)
    if not services:
        await message.answer("Сейчас нет доступных услуг. Загляните чуть позже 🙏")
        return
    await state.set_state(BookingForm.service)
    await message.answer("✂️ Выберите услугу:", reply_markup=services_kb(services))


@router.callback_query(StateFilter(BookingForm), BookNavCb.filter(F.action == "services"))
async def back_to_services(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.set_state(BookingForm.service)
    await edit_or_answer(callback, "✂️ Выберите услугу:", services_kb(await repo.list_services(session)))
    await callback.answer()


# ---------- Шаг 2: дата ----------

@router.callback_query(BookingForm.service, ServiceCb.filter())
async def choose_service(
    callback: CallbackQuery, callback_data: ServiceCb, session: AsyncSession, state: FSMContext, settings: Settings
) -> None:
    service = await repo.get_service(session, callback_data.id)
    if service is None or not service.is_active:
        await callback.answer("Эта услуга сейчас недоступна", show_alert=True)
        return
    await state.update_data(service_id=service.id)
    await _show_days(callback, session, state, settings, service)
    await callback.answer()


@router.callback_query(StateFilter(BookingForm), BookNavCb.filter(F.action == "days"))
async def back_to_days(callback: CallbackQuery, session: AsyncSession, state: FSMContext, settings: Settings) -> None:
    if (service := await _draft_service(session, state)) is None:
        await _restart(callback, state)
        return
    await _show_days(callback, session, state, settings, service)
    await callback.answer()


# ---------- Шаг 3: время ----------

@router.callback_query(BookingForm.day, DayCb.filter())
async def choose_day(
    callback: CallbackQuery, callback_data: DayCb, session: AsyncSession, state: FSMContext, settings: Settings
) -> None:
    if (service := await _draft_service(session, state)) is None:
        await _restart(callback, state)
        return
    day = datetime.strptime(callback_data.value, "%Y%m%d").date()
    slots = await _free_slots(session, settings, service, day)
    if not slots:
        await callback.answer("На этот день свободное время уже разобрали", show_alert=True)
        await _show_days(callback, session, state, settings, service)
        return
    await state.set_state(BookingForm.slot)
    await edit_or_answer(callback, f"{_service_line(service)}\n📅 {fmt_day(day)}\n\nВыберите время:", slots_kb(slots))
    await callback.answer()


# ---------- Шаг 4: телефон ----------

@router.callback_query(BookingForm.slot, SlotCb.filter())
async def choose_slot(
    callback: CallbackQuery, callback_data: SlotCb, session: AsyncSession, state: FSMContext, settings: Settings
) -> None:
    if (service := await _draft_service(session, state)) is None:
        await _restart(callback, state)
        return
    starts_at = datetime.strptime(callback_data.value, SLOT_FMT)
    # Проверяем, что слот всё ещё свободен и вообще существует (callback_data приходит от клиента)
    if starts_at not in await _free_slots(session, settings, service, starts_at.date()):
        await callback.answer("Это время уже занято, выберите другое", show_alert=True)
        await _show_days(callback, session, state, settings, service)
        return
    await state.update_data(starts_at=callback_data.value)

    user = await repo.get_user(session, callback.from_user.id)
    if user is not None and user.phone:
        await state.set_state(BookingForm.confirm)
        await edit_or_answer(callback, _summary(service, starts_at, user.phone), confirm_kb())
    else:
        await state.set_state(BookingForm.phone)
        await edit_or_answer(callback, f"{_service_line(service)}\n🕒 {fmt_dt(starts_at)}")
        await callback.message.answer(
            "📱 Оставьте номер телефона, чтобы мастер мог связаться с вами.\n"
            "Нажмите кнопку ниже или введите номер вручную.",
            reply_markup=phone_request(),
        )
    await callback.answer()


@router.message(BookingForm.phone, F.contact)
async def phone_from_contact(message: Message, session: AsyncSession, state: FSMContext, settings: Settings) -> None:
    if message.contact.user_id != message.from_user.id:
        await message.answer("Пожалуйста, отправьте свой номер — кнопкой ниже или текстом.")
        return
    await _save_phone_and_confirm(message, session, state, settings, normalize_phone(message.contact.phone_number))


@router.message(BookingForm.phone, F.text, not_menu_button)
async def phone_from_text(message: Message, session: AsyncSession, state: FSMContext, settings: Settings) -> None:
    if (phone := normalize_phone(message.text)) is None:
        await message.answer("Не похоже на номер телефона 🤔 Пример: +7 900 123-45-67")
        return
    await _save_phone_and_confirm(message, session, state, settings, phone)


# ---------- Шаг 5: подтверждение ----------

@router.callback_query(BookingForm.confirm, BookNavCb.filter(F.action == "confirm"))
async def confirm_booking(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, settings: Settings, bot: Bot
) -> None:
    service, starts_at = await _draft(session, state)
    now = now_local(settings.tz)
    if service is None or starts_at is None or not service.is_active or starts_at <= now:
        await _restart(callback, state)
        return

    tg_user = callback.from_user
    async with _booking_lock:
        # Повторная проверка лимита: клиент мог параллельно оформить запись в другом сообщении
        if await _limit_reached(session, settings, tg_user.id):
            await state.clear()
            await edit_or_answer(callback, _limit_text(settings))
            await callback.answer()
            return
        user = await repo.upsert_user(session, tg_user.id, tg_user.full_name, tg_user.username)
        booking = await repo.create_booking(session, tg_user.id, service, starts_at, now)

    if booking is None:
        await callback.answer("Это время только что заняли 😔 Выберите другое", show_alert=True)
        await _show_days(callback, session, state, settings, service)
        return

    await state.clear()
    details = f"{_service_line(service)}\n🕒 {fmt_dt(starts_at)}"
    deadline = f" не позже чем за {settings.cancel_min_hours} ч до визита" if settings.cancel_min_hours else ""
    await edit_or_answer(
        callback,
        f"✅ <b>Вы записаны!</b>\n\n{details}\n📍 {html.quote(settings.business_address)}\n\n"
        f"Напомню за сутки и за час до визита. Отменить запись можно{deadline} в разделе «{Btn.MY}».",
    )
    await callback.answer()

    username = f" (@{tg_user.username})" if tg_user.username else ""
    await notify_admins(
        bot,
        settings.admins,
        f"🆕 <b>Новая запись</b>\n\n{details}\n👤 {user_link(tg_user.id, tg_user.full_name)}{username}\n📱 {user.phone}",
    )


@router.callback_query(StateFilter(BookingForm), BookNavCb.filter(F.action == "abort"))
async def abort_booking(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_or_answer(callback, "Запись отменена. Возвращайтесь, когда будет удобно!")
    await callback.answer()


# ---------- Вспомогательное ----------

async def _show_days(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, settings: Settings, service: Service
) -> None:
    days = await slots_by_day(session, settings, service.duration_min, now_local(settings.tz))
    await state.set_state(BookingForm.day)
    if not days:
        await edit_or_answer(
            callback,
            f"{_service_line(service)}\n\nНа ближайшие {settings.booking_days_ahead} дней свободного времени нет 😔",
            back_to_services_kb(),
        )
        return
    await edit_or_answer(callback, f"{_service_line(service)}\n\n📅 Выберите дату:", days_kb(list(days)))


async def _free_slots(session: AsyncSession, settings: Settings, service: Service, day) -> list[datetime]:
    by_day = await slots_by_day(session, settings, service.duration_min, now_local(settings.tz), days=[day])
    return by_day.get(day, [])


async def _save_phone_and_confirm(
    message: Message, session: AsyncSession, state: FSMContext, settings: Settings, phone: str | None
) -> None:
    tg_user = message.from_user
    service, starts_at = await _draft(session, state)
    if service is None or starts_at is None or phone is None:
        await state.clear()
        await message.answer(
            "Что-то пошло не так, начните запись заново.", reply_markup=main_menu(settings.is_admin(tg_user.id))
        )
        return
    await repo.upsert_user(session, tg_user.id, tg_user.full_name, tg_user.username)
    await repo.set_phone(session, tg_user.id, phone)

    await state.set_state(BookingForm.confirm)
    await message.answer("Номер сохранён ✅", reply_markup=main_menu(settings.is_admin(tg_user.id)))
    await message.answer(_summary(service, starts_at, phone), reply_markup=confirm_kb())


async def _draft(session: AsyncSession, state: FSMContext) -> tuple[Service | None, datetime | None]:
    data = await state.get_data()
    service = await repo.get_service(session, data["service_id"]) if "service_id" in data else None
    starts_at = datetime.strptime(data["starts_at"], SLOT_FMT) if "starts_at" in data else None
    return service, starts_at


async def _draft_service(session: AsyncSession, state: FSMContext) -> Service | None:
    return (await _draft(session, state))[0]


async def _limit_reached(session: AsyncSession, settings: Settings, user_id: int) -> bool:
    upcoming = await repo.count_user_upcoming(session, user_id, now_local(settings.tz))
    return upcoming >= settings.max_active_bookings


def _limit_text(settings: Settings) -> str:
    return (
        f"Достигнут лимит предстоящих записей на одного клиента: {settings.max_active_bookings}.\n"
        f"Отмените одну из них в разделе «{Btn.MY}», чтобы записаться снова."
    )


async def _restart(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Эта запись уже неактуальна — начните заново через «📅 Записаться»", show_alert=True)


def _service_line(service: Service) -> str:
    return f"✂️ <b>{html.quote(service.title)}</b> · {service.duration_min} мин · {service.price} ₽"


def _summary(service: Service, starts_at: datetime, phone: str) -> str:
    return (
        "<b>Проверьте запись:</b>\n\n"
        f"{_service_line(service)}\n"
        f"🕒 {fmt_dt(starts_at)}\n"
        f"📱 {phone}\n\n"
        "Оплата на месте."
    )
