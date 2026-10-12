"""Store calendar boundaries: local midnight, exclusive next local day."""
from datetime import date, datetime, time, timedelta, timezone


def day_bounds(value: str, tz):
    day = date.fromisoformat(value)
    start = datetime.combine(day, time.min, tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def validate_dates(date_from=None, date_to=None):
    for value in (date_from, date_to):
        if value is not None:
            day = date.fromisoformat(value)
            if day.isoformat() != value or day == date.max:
                raise ValueError("Вкажіть коректну дату YYYY-MM-DD")
    if date_from and date_to and date_from > date_to:
        raise ValueError("Початкова дата має бути не пізніше кінцевої")
