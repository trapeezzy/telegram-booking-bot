"""Типизированные callback_data. aiogram сам упаковывает их в строку вида 'svc:3'
и распаковывает обратно, а в хендлере доступен готовый объект с полями."""

from aiogram.filters.callback_data import CallbackData


class ServiceCb(CallbackData, prefix="svc"):
    id: int


class DayCb(CallbackData, prefix="day"):
    value: str  # YYYYMMDD


class SlotCb(CallbackData, prefix="slot"):
    value: str  # YYYYMMDDHHMM


class BookNavCb(CallbackData, prefix="bnav"):
    action: str  # services | days | confirm | abort


class CancelBookingCb(CallbackData, prefix="ucancel"):
    id: int


class AdminCb(CallbackData, prefix="adm"):
    action: str  # menu | bookings | services | add_service | time_off | add_time_off | whole_day | broadcast | stats


class TimeOffDayCb(CallbackData, prefix="today"):
    value: str  # YYYYMMDD


class DeleteTimeOffCb(CallbackData, prefix="todel"):
    id: int


class AdminCancelCb(CallbackData, prefix="acancel"):
    id: int


class ToggleServiceCb(CallbackData, prefix="tsvc"):
    id: int


class BroadcastCb(CallbackData, prefix="bcast"):
    action: str  # send | abort
