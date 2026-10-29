from aiogram import F, Router, html
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db import repo
from bot.keyboards.menu import Btn, main_menu
from bot.utils.formatting import fmt_weekdays

router = Router(name="common")


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    user = message.from_user
    await repo.upsert_user(session, user.id, user.full_name, user.username)
    await message.answer(
        f"Здравствуйте, {html.quote(user.first_name)}! 👋\n\n"
        f"Я бот <b>{html.quote(settings.business_name)}</b>. Помогу записаться на стрижку "
        "за пару касаний — без звонков и ожидания на линии.\n\n"
        "Выберите действие в меню ниже 👇",
        reply_markup=main_menu(settings.is_admin(user.id)),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_menu(settings.is_admin(message.from_user.id)))


@router.message(F.text == Btn.ABOUT)
@router.message(Command("about"))
async def about(message: Message, state: FSMContext, settings: Settings) -> None:
    await state.clear()
    await message.answer(
        f"💈 <b>{html.quote(settings.business_name)}</b>\n\n"
        f"📍 {html.quote(settings.business_address)}\n"
        f"📞 {html.quote(settings.business_phone)}\n"
        f"🕒 {fmt_weekdays(settings.weekdays)}, "
        f"{settings.work_start:%H:%M}–{settings.work_end:%H:%M}"
    )
