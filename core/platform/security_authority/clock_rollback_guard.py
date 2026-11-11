"""Persisted last-good clock must be supplied from trusted server storage."""
from datetime import datetime, timezone, timedelta

class ClockDenied(ValueError): pass

def require_monotonic_wallclock(now: datetime, previous_good: datetime,
                                maximum_skew_seconds: int = 30) -> datetime:
    if maximum_skew_seconds < 0:raise ClockDenied("NEGATIVE_SKEW_LIMIT")
    for value in (now, previous_good):
        if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ClockDenied("UNTRUSTED_CLOCK")
    current=now.astimezone(timezone.utc)
    old=previous_good.astimezone(timezone.utc)
    if current + timedelta(seconds=maximum_skew_seconds) < old:
        raise ClockDenied("CLOCK_ROLLBACK_DENIED")
    return max(current, old)
