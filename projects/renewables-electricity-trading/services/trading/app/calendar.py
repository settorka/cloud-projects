from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

GB = ZoneInfo("Europe/London")


def periods(day):
    start = datetime.combine(day, time.min, GB).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, GB).astimezone(timezone.utc)
    result = []
    while start < end:
        result.append(start)
        start += timedelta(minutes=30)
    return result


def interval_identity(start):
    day = start.astimezone(GB).date()
    return {"settlement_date": day.isoformat(), "settlement_period": periods(day).index(start) + 1}
