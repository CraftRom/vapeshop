"""Small protocol helpers shared by external API adapters."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math


def retry_after_seconds(value, *, default=1.0, now=None):
    """Retry-After accepts seconds or an HTTP date; never shorten provider delays."""
    try:
        seconds = float(value)
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError()
        return seconds
    except (ValueError, TypeError):
        try:
            moment = parsedate_to_datetime(str(value))
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            return max(0.0, (moment - (now or datetime.now(timezone.utc))).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return float(default)
