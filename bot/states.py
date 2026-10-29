"""Состояния многошаговых диалогов (FSM). Бот помнит, на каком шаге пользователь,
и какие данные он уже выбрал, — между сообщениями."""

from aiogram.fsm.state import State, StatesGroup


class BookingForm(StatesGroup):
    service = State()
    day = State()
    slot = State()
    phone = State()
    confirm = State()


class AddService(StatesGroup):
    title = State()
    duration = State()
    price = State()


class TimeOffForm(StatesGroup):
    day = State()
    period = State()


class Broadcast(StatesGroup):
    message = State()
    confirm = State()
