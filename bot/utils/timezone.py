from datetime import datetime, timezone, timedelta
import pytz

KYIV_TZ = pytz.timezone('Europe/Kiev')


def now_kyiv() -> datetime:
    """Поточний час за Києвом (aware)"""
    return datetime.now(KYIV_TZ)


def utc_to_kyiv(dt: datetime) -> datetime:
    """Конвертувати UTC datetime (naive або aware) в київський час"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KYIV_TZ)


def kyiv_to_utc_naive(dt: datetime) -> datetime:
    """Конвертувати naive київський datetime в naive UTC datetime для зберігання в MongoDB"""
    localized = KYIV_TZ.localize(dt)
    return localized.astimezone(timezone.utc).replace(tzinfo=None)


def kyiv_start_of_today_utc() -> datetime:
    """Початок сьогодні за Києвом, повернутий як naive UTC (для запитів до MongoDB)"""
    kyiv_now = now_kyiv()
    start_kyiv = kyiv_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_kyiv.astimezone(timezone.utc).replace(tzinfo=None)


def kyiv_start_of_day_utc(kyiv_date: datetime) -> datetime:
    """Початок конкретного дня за Києвом, повернутий як naive UTC"""
    if kyiv_date.tzinfo is None:
        kyiv_date = KYIV_TZ.localize(kyiv_date)
    start_kyiv = kyiv_date.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_kyiv.astimezone(timezone.utc).replace(tzinfo=None)
