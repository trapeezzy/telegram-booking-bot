from aiogram import Router

from bot.handlers import admin, booking, common, fallback, my_bookings


def get_routers() -> list[Router]:
    # Порядок важен: апдейт уходит в первый подходящий хендлер, fallback — всегда последним
    return [common.router, booking.router, my_bookings.router, admin.router, fallback.router]
