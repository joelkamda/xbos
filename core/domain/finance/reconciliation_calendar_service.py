"""Neutral business-date and shift-boundary attribution for M6.2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .reconciliation_window_contract import ReconciliationWindowValidationError


@dataclass(frozen=True)
class ReconciliationAttribution:
    business_date: date
    shift_code: str


@dataclass(frozen=True)
class ReconciliationWindowAttribution:
    business_date: date
    shift_code: str
    window_start: datetime
    window_end: datetime


class ReconciliationCalendarService:
    @staticmethod
    def attribute(policy, instant: datetime) -> ReconciliationAttribution:
        zone = ZoneInfo(policy.timezone_name)
        local = instant.astimezone(zone)
        local_clock = local.time().replace(tzinfo=None)
        business_date = local.date() if local_clock >= policy.business_day_boundary else local.date()-timedelta(days=1)
        shifts = tuple(sorted(policy.shifts, key=lambda item: item["starts_at"]))
        selected = next((item for item in reversed(shifts) if item["starts_at"] <= local_clock.isoformat(timespec="minutes")), shifts[-1])
        return ReconciliationAttribution(business_date, selected["code"])

    @classmethod
    def validate_window(cls, policy, window_start: datetime, window_end: datetime) -> ReconciliationWindowAttribution:
        zone = ZoneInfo(policy.timezone_name)
        local_start = window_start.astimezone(zone)
        start_clock = local_start.time().replace(tzinfo=None).isoformat(timespec="minutes")
        shifts = tuple(sorted(policy.shifts, key=lambda item: item["starts_at"]))
        positions = [index for index, item in enumerate(shifts) if item["starts_at"] == start_clock]
        if not positions:
            raise ReconciliationWindowValidationError("window_not_shift_aligned", "window_start is not a configured shift boundary")
        index = positions[0]
        next_index = (index+1) % len(shifts)
        next_date = local_start.date() + (timedelta(days=1) if next_index == 0 else timedelta())
        next_clock = datetime.strptime(shifts[next_index]["starts_at"], "%H:%M").time()
        expected_end = datetime.combine(next_date, next_clock, tzinfo=zone).astimezone(timezone.utc)
        if window_end.astimezone(timezone.utc) != expected_end:
            raise ReconciliationWindowValidationError("window_end_mismatch", "window_end must equal the next configured shift boundary")
        attribution = cls.attribute(policy, window_start)
        return ReconciliationWindowAttribution(attribution.business_date, attribution.shift_code, window_start, window_end)
