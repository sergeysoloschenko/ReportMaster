import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Moscow")


def bounds(period, current=None):
    if not re.fullmatch(r"\d{4}-\d{2}", period or ""):
        raise ValueError("Период должен иметь формат ГГГГ-ММ")
    start = datetime.strptime(period, "%Y-%m").replace(tzinfo=TZ)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    current = current or datetime.now(TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=TZ)
    if end > current:
        raise ValueError("Отчётный месяц ещё не завершён")
    return start, end


def last_month(current=None):
    current = current or datetime.now(TZ)
    return (current.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


def utc(value):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
