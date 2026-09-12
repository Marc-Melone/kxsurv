"""Validate detector inputs without replacing missing observations with zero."""
from __future__ import annotations

import math
from datetime import datetime, timezone

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def timestamp_us(value: str | datetime) -> int:
    """An aware timestamp as exact integer microseconds since the Unix epoch."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid timestamp") from exc
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    delta = value.astimezone(timezone.utc) - EPOCH
    return ((delta.days * 86400 + delta.seconds) * 1_000_000
            + delta.microseconds)


def number(value, field: str, *, minimum=None, maximum=None,
           positive: bool = False) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError("{} requires a finite number".format(field))
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("{} requires a finite number".format(field)) from exc
    if not math.isfinite(result):
        raise ValueError("{} requires a finite number".format(field))
    if ((minimum is not None and result < minimum)
            or (maximum is not None and result > maximum)
            or (positive and result <= 0)):
        raise ValueError("{} is outside its valid range".format(field))
    return result


def price(value, field: str) -> float:
    return number(value, field, minimum=0, maximum=1)


def candle_timestamp(value) -> int:
    result = number(value, "end_period_ts", minimum=0)
    if not result.is_integer():
        raise ValueError("end_period_ts must be an integer")
    return int(result)
