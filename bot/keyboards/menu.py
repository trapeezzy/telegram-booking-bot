from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder


class Btn:
    BOOK = "📅 Записаться"
    MY = "📋 Мои записи"
    ABOUT = "ℹ️ О нас"
    ADMIN = "⚙️ Админка"


MENU_BUTTONS = {Btn.BOOK, Btn.MY, Btn.ABOUT, Btn.ADMIN}


def not_menu_button(message: Message) -> bool:
    """Фильтр для хендлеров, ждущих ввод (телефон, название услуги): нажатие кнопки меню
    посреди диалога должно работать как навигация, а не считаться ответом."""
    return message.text not in MENU_BUTTONS


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=Btn.BOOK)
    builder.button(text=Btn.MY)
    builder.button(text=Btn.ABOUT)
    if is_admin:
        builder.button(text=Btn.ADMIN)
    builder.adjust(1, 2, 1)
    return builder.as_markup(resize_keyboard=True)


def phone_request() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="или введите номер вручную",
    )
