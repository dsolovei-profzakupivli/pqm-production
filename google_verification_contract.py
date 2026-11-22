"""Strict Google EDR verification-time parsing shared by preview and Apply."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import re
from zoneinfo import ZoneInfo


KYIV = ZoneInfo("Europe/Kyiv")


def verification_instant(value):
    """Return blank/invalid/datetime; reject ambiguous/nonexistent Kyiv wall times."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return {"kind": "blank", "value": None}
    try:
        if isinstance(value, bool):
            raise ValueError("boolean is not a date")
        if isinstance(value, (float, int)):
            if not math.isfinite(value) or not 2 <= value <= 2958465:
                raise ValueError("invalid serial")
            parsed = datetime(1899, 12, 30) + timedelta(milliseconds=round(value * 86400000))
        elif isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            text = value.strip()
            uk = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})(?:[ T](\d{2}:\d{2})(?::(\d{2}))?)?", text)
            if uk:
                text = f"{uk[3]}-{uk[2]}-{uk[1]}T{uk[4] or '00:00'}:{uk[5] or '00'}"
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)?", text):
                raise ValueError("unsupported datetime")
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            raise ValueError("unsupported type")
        if parsed.tzinfo is None:
            if parsed.year < 2000:
                raise ValueError("unsupported historical wall-time offset")
            possible = set()
            for fold in (0, 1):
                candidate = parsed.replace(tzinfo=KYIV, fold=fold).astimezone(timezone.utc)
                if candidate.astimezone(KYIV).replace(tzinfo=None) == parsed:
                    possible.add(candidate)
            if len(possible) != 1:
                raise ValueError("ambiguous or nonexistent Kyiv datetime")
            parsed = possible.pop()
        return {"kind": "datetime", "value": parsed.astimezone(timezone.utc)}
    except (ValueError, OverflowError, TypeError):
        return {"kind": "invalid", "value": None}


def has_observation_time(value):
    """Whether a source value proves time-of-day precision."""
    if isinstance(value, datetime):
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (float, int)):
        if not math.isfinite(value):
            return False
        millis = round((value % 1) * 86400000)
        return millis % 86400000 != 0
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(
        re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}", text)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?", text)
    )


def google_verification_instant(value):
    """Parse Google data; legacy date-only values are never treated as instants."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return {"kind": "blank", "value": None}
    if isinstance(value, str):
        text = value.strip()
        date_only = bool(re.fullmatch(r"\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2}", text))
        full_timestamp = bool(
            re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}", text)
            or re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?", text)
        )
        if not date_only and not full_timestamp:
            return {"kind": "invalid", "value": None}
    parsed = verification_instant(value)
    if parsed["kind"] != "datetime":
        return parsed
    if not has_observation_time(value):
        return {"kind": "date_only", "value": None}
    if isinstance(value, str) and not (
        re.fullmatch(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}", value.strip())
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?", value.strip())
    ):
        return {"kind": "invalid", "value": None}
    return parsed


def incoming_verification_gate(incoming, current, *, require_time=True):
    """Accept only a strictly newer source instant; date-only PQM needs a later day."""
    new = google_verification_instant(incoming) if require_time else verification_instant(incoming)
    old = verification_instant(current)
    if new["kind"] != "datetime":
        return {"accepted": False, "reason": "incoming_" + new["kind"]}
    if old["kind"] == "invalid":
        return {"accepted": False, "reason": "current_invalid"}
    if old["kind"] == "blank":
        return {"accepted": True, "reason": "initial"}
    if require_time and not has_observation_time(current):
        new_day = new["value"].astimezone(KYIV).date()
        old_day = old["value"].astimezone(KYIV).date()
        if new_day <= old_day:
            return {"accepted": False, "reason": "current_date_only_not_newer_by_day"}
        return {"accepted": True, "reason": "newer_than_date_only"}
    if new["value"] > old["value"]:
        return {"accepted": True, "reason": "newer"}
    return {"accepted": False, "reason": "equal" if new["value"] == old["value"] else "older"}


def google_verification_timestamp(value):
    parsed = google_verification_instant(value)
    return parsed["value"].astimezone(KYIV).isoformat(timespec="seconds") if parsed["kind"] == "datetime" else ""


def verification_timestamp(value):
    parsed = verification_instant(value)
    return parsed["value"].astimezone(KYIV).isoformat(timespec="milliseconds") if parsed["kind"] == "datetime" else ""
