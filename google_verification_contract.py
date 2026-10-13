"""Pure verification-instant policies; no I/O, application startup, or migrations."""
from datetime import datetime, timedelta, timezone
import math
import re
import json
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
            dt = datetime(1899, 12, 30) + timedelta(milliseconds=round(value * 86400000))
        elif isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            text = value.strip()
            uk = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})(?:[ T](\d{2}:\d{2})(?::(\d{2}))?)?", text)
            if uk:
                text = f"{uk[3]}-{uk[2]}-{uk[1]}T{uk[4] or '00:00'}:{uk[5] or '00'}"
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?(?:Z|[+-]\d{2}:\d{2})?)?", text):
                raise ValueError("unsupported datetime")
            suffix = re.search(r"([+-])(\d{2}):(\d{2})$", text)
            if suffix and (int(suffix[2]) > 14 or int(suffix[3]) > 59 or
                           (int(suffix[2]) == 14 and int(suffix[3]) != 0)):
                raise ValueError("invalid offset")
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            raise ValueError("unsupported type")
        if dt.tzinfo is None:
            if dt.year < 2000:
                raise ValueError("unsupported historical wall-time offset")
            possible = set()
            for fold in (0, 1):
                candidate = dt.replace(tzinfo=KYIV, fold=fold).astimezone(timezone.utc)
                if candidate.astimezone(KYIV).replace(tzinfo=None) == dt:
                    possible.add(candidate)
            if len(possible) != 1:
                raise ValueError("ambiguous or nonexistent Kyiv datetime")
            dt = possible.pop()
        return {"kind": "datetime", "value": dt.astimezone(timezone.utc)}
    except (ValueError, OverflowError, TypeError):
        return {"kind": "invalid", "value": None}


def incoming_verification_gate(incoming, current):
    """Shared directional gate: swap arguments for PQM→Google / Google→PQM."""
    new, old = verification_instant(incoming), verification_instant(current)
    if new["kind"] != "datetime":
        return {"accepted": False, "reason": "incoming_" + new["kind"]}
    if old["kind"] == "invalid":
        return {"accepted": False, "reason": "current_invalid"}
    if old["kind"] == "blank":
        return {"accepted": True, "reason": "initial"}
    if new["value"] > old["value"]:
        return {"accepted": True, "reason": "newer"}
    return {"accepted": False, "reason": "equal" if new["value"] == old["value"] else "older"}


def verification_timestamp(value):
    parsed = verification_instant(value)
    return parsed["value"].astimezone(KYIV).isoformat(timespec="milliseconds") if parsed["kind"] == "datetime" else ""


def decision_datetime_precision(value):
    """Describe the existing decision value, without demanding separate signature evidence."""
    if verification_instant(value)['kind'] != 'datetime':
        return 'missing'
    if isinstance(value, str) and not re.search(r'[ T]\d{2}:\d{2}', value):
        return 'day'
    return 'instant'


def verified_admission_signature(event):
    """Only a cached verification of the linked admission protocol, never application sign.p7s."""
    if event.get('event_type') != 'admission' or event.get('source') != 'verified_protocol_signature':
        return ''
    try:
        evidence=json.loads(event.get('snapshot_json') or '{}')
        if (evidence.get('document_kind') != 'admission_protocol' or evidence.get('verification_status') != 'valid' or
                not evidence.get('document_id') or not event.get('source_submission_id') or
                evidence.get('source_submission_id') != event['source_submission_id'] or
                not re.fullmatch('[0-9a-f]{64}',evidence.get('signed_document_sha256',''))):
            return ''
        value=evidence.get('signed_at','')
        if not re.search(r'(Z|[+-]\d{2}:\d{2})$',value) and evidence.get('timezone') != 'Europe/Kyiv': return ''
        parsed=verification_instant(value);occurred=verification_instant(event.get('occurred_at'))
        if parsed['kind']!='datetime' or occurred['kind']!='datetime' or parsed['value']!=occurred['value']:
            return ''
        return verification_timestamp(value)
    except (TypeError,ValueError,AttributeError):
        return ''
