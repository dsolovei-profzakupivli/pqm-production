"""Persistent, timezone-aware scheduler primitives for PQM background jobs."""
from __future__ import annotations

import sqlite3
import uuid
import logging
import threading
import json
from contextlib import contextmanager, closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


KYIV = ZoneInfo("Europe/Kyiv")
SCHEDULES = {
    "prozorro": "Щогодини о :05",
    "violation_reports": "Щогодини о :05",
    "nazk_registry": "Пн–Пт о 09:20",
}


def enabled_by_default(environment: str) -> bool:
    """Deployment policy: automatic jobs run in LOCAL/WEB TEST, not implicit PROD."""
    return str(environment or "").strip().casefold() in {"local", "test", "test_web", "web"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_kyiv(moment: datetime | None = None) -> datetime:
    value = moment or utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=KYIV)
    return value.astimezone(KYIV)


def next_hourly_run(moment: datetime | None = None) -> datetime:
    return next_run(default_spec('prozorro'), moment)


def next_nazk_run(moment: datetime | None = None) -> datetime:
    return next_run(default_spec('nazk_registry'), moment)


def nazk_due_today(moment: datetime | None, last_finished_at: str | None) -> bool:
    return catchup_due(default_spec('nazk_registry'), moment, last_finished_at)


def hourly_catchup_due(moment: datetime | None, last_finished_at: str | None) -> bool:
    current = (moment or utc_now()).astimezone(timezone.utc)
    if not last_finished_at:
        return True
    try:
        last = datetime.fromisoformat(last_finished_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return True
    return (current - last).total_seconds() >= 3600


def migrate(con: sqlite3.Connection) -> None:
    con.executescript("""
    CREATE TABLE IF NOT EXISTS scheduler_job_state (
      job_key TEXT PRIMARY KEY,
      last_started_at TEXT,
      last_finished_at TEXT,
      last_status TEXT NOT NULL DEFAULT 'never',
      last_error TEXT NOT NULL DEFAULT '',
      last_trigger TEXT NOT NULL DEFAULT '',
      last_owner TEXT NOT NULL DEFAULT '',
      updated_at TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS scheduler_job_leases (
      job_key TEXT PRIMARY KEY,
      owner_id TEXT NOT NULL,
      acquired_at TEXT NOT NULL,
      lease_until TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS scheduler_job_settings (
      job_key TEXT PRIMARY KEY,
      enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
      updated_at TEXT NOT NULL,
      updated_by TEXT NOT NULL
    );
    """)
    con.executemany("INSERT OR IGNORE INTO scheduler_job_state(job_key) VALUES (?)",
                    [(key,) for key in SCHEDULES])
    columns = {r[1] for r in con.execute("PRAGMA table_info(scheduler_job_settings)")}
    for name, definition in (("schedule_json", "TEXT"), ("timezone", "TEXT NOT NULL DEFAULT 'Europe/Kyiv'"),
                             ("revision", "INTEGER NOT NULL DEFAULT 0")):
        if name not in columns:
            con.execute(f"ALTER TABLE scheduler_job_settings ADD COLUMN {name} {definition}")
    con.execute("""CREATE TABLE IF NOT EXISTS scheduler_schedule_audit (
      job_key TEXT NOT NULL, revision INTEGER NOT NULL, before_json TEXT NOT NULL,
      after_json TEXT NOT NULL, actor TEXT NOT NULL, changed_at TEXT NOT NULL,
      PRIMARY KEY(job_key,revision))""")


def effective_enabled(con: sqlite3.Connection, defaults: dict[str, bool]) -> dict[str, bool]:
    """Apply persistent Admin overrides on top of environment startup defaults."""
    try:
        overrides = {str(row[0]): bool(row[1]) for row in con.execute(
            "SELECT job_key,enabled FROM scheduler_job_settings"
        )}
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).casefold():
            raise
        overrides = {}
    return {key: overrides.get(key, bool(defaults.get(key))) for key in SCHEDULES}


def setting_sources(con: sqlite3.Connection) -> dict[str, str]:
    try:
        overridden = {str(row[0]) for row in con.execute("SELECT job_key FROM scheduler_job_settings")}
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).casefold():
            raise
        overridden = set()
    return {key: "runtime" if key in overridden else "environment" for key in SCHEDULES}


def save_enabled(con: sqlite3.Connection, job_key: str, enabled: bool, actor: str,
                 *, moment: datetime | None = None, default_enabled: bool = False) -> None:
    if job_key not in SCHEDULES:
        raise ValueError(f"Unknown scheduler job: {job_key}")
    migrate(con)
    current = schedule_model(con, job_key, default_enabled)
    apply_schedule(con, job_key, {"enabled": bool(enabled), "spec": current["spec"],
                   "timezone": "Europe/Kyiv"}, current["revision"], actor, moment=moment,
                   defaults={job_key: default_enabled})


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


class RevisionConflict(ValueError):
    pass


def default_spec(job_key):
    if job_key not in SCHEDULES:
        raise ValueError("Unknown scheduler job")
    return ({"kind": "weekly", "hour": 9, "minute": 20, "weekdays": [0, 1, 2, 3, 4]}
            if job_key == "nazk_registry" else {"kind": "hourly", "minute": 5})


def validate_spec(job_key, spec):
    expected = "weekly" if job_key == "nazk_registry" else "hourly"
    default_spec(job_key)
    if not isinstance(spec, dict) or spec.get("kind") != expected:
        raise ValueError("Invalid schedule kind")
    keys = {"kind", "minute"} if expected == "hourly" else {"kind", "hour", "minute", "weekdays"}
    if set(spec) != keys or type(spec.get("minute")) is not int or not 0 <= spec["minute"] <= 59:
        raise ValueError("Minute must be an integer 0–59; unknown fields are forbidden")
    result = {"kind": expected, "minute": spec["minute"]}
    if expected == "weekly":
        days = spec.get("weekdays")
        if type(spec.get("hour")) is not int or not 0 <= spec["hour"] <= 23:
            raise ValueError("Hour must be an integer 0–23")
        if not isinstance(days, list) or not days or any(type(d) is not int or not 0 <= d <= 6 for d in days) or len(set(days)) != len(days):
            raise ValueError("Select unique weekdays 0–6")
        result.update(hour=spec["hour"], weekdays=sorted(days))
    return result


def schedule_model(con, job_key, default_enabled=False):
    """Pure read: valid for legacy schemas and query_only connections."""
    spec = default_spec(job_key)
    columns = {r[1] for r in con.execute("PRAGMA table_info(scheduler_job_settings)")}
    row = None
    if columns:
        names = ["enabled"] + [n for n in ("schedule_json", "timezone", "revision", "updated_at") if n in columns]
        found = con.execute(f"SELECT {','.join(names)} FROM scheduler_job_settings WHERE job_key=?", (job_key,)).fetchone()
        row = dict(zip(names, found)) if found else None
    if row and row.get("timezone", "Europe/Kyiv") != "Europe/Kyiv":
        raise ValueError("Unsupported persisted timezone")
    if row and row.get("schedule_json"):
        spec = validate_spec(job_key, json.loads(row["schedule_json"]))
    return {"job": job_key, "enabled": bool(row["enabled"]) if row else bool(default_enabled),
            "spec": spec, "timezone": "Europe/Kyiv", "revision": row.get("revision", 0) if row else 0,
            "updated_at": row.get("updated_at") if row else None,
            "configuration_source": "runtime" if row else "environment"}


def _wall_instant(wall):
    """Skip nonexistent times; choose first occurrence only in an autumn fold."""
    first = wall.replace(tzinfo=KYIV, fold=0)
    if first.astimezone(timezone.utc).astimezone(KYIV).replace(tzinfo=None) != wall:
        return None
    return first


def next_run(spec, moment=None):
    current = as_kyiv(moment)
    if current.tzinfo is None:
        raise ValueError("Timezone required")
    wall = current.replace(tzinfo=None, second=0, microsecond=0)
    if spec["kind"] == "hourly":
        base = wall.replace(minute=spec["minute"])
        candidates = (base + timedelta(hours=i) for i in range(50))
    else:
        base = wall.replace(hour=spec["hour"], minute=spec["minute"])
        candidates = (base + timedelta(days=i) for i in range(15)
                      if (base + timedelta(days=i)).weekday() in spec["weekdays"])
    for candidate in candidates:
        instant = _wall_instant(candidate)
        if instant and instant.astimezone(timezone.utc) > current.astimezone(timezone.utc):
            return instant
    raise ValueError("No next schedule occurrence")


def schedule_label(spec):
    if spec["kind"] == "hourly":
        return f"Щогодини о :{spec['minute']:02d}"
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
    return f"{', '.join(days[d] for d in spec['weekdays'])} о {spec['hour']:02d}:{spec['minute']:02d}"


def catchup_due(spec, moment, last_finished_at):
    current = as_kyiv(moment)
    wall = current.replace(tzinfo=None, second=0, microsecond=0)
    if spec["kind"] == "weekly":
        if wall.weekday() not in spec["weekdays"]:
            return False
        slot = _wall_instant(wall.replace(hour=spec["hour"], minute=spec["minute"]))
    else:
        candidate = wall.replace(minute=spec["minute"])
        if candidate > wall:
            candidate -= timedelta(hours=1)
        slot = _wall_instant(candidate)
    if not slot or slot.astimezone(timezone.utc) > current.astimezone(timezone.utc):
        return False
    try:
        last = datetime.fromisoformat((last_finished_at or "").replace("Z", "+00:00"))
        if spec['kind'] == 'weekly' and last.astimezone(KYIV).date() == current.date():
            return False  # Preserve existing once-per-Kyiv-day restart protection.
        return last.astimezone(timezone.utc) < slot.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return True


def preview_schedule(con, job_key, payload, defaults=None, moment=None):
    if not isinstance(payload, dict) or set(payload) != {"enabled", "spec", "timezone"} or type(payload.get("enabled")) is not bool:
        raise ValueError("Expected enabled, spec and timezone")
    if payload["timezone"] != "Europe/Kyiv":
        raise ValueError("Timezone must remain Europe/Kyiv")
    defaults = defaults or {}
    before = schedule_model(con, job_key, defaults.get(job_key, False))
    after = {**before, "enabled": payload["enabled"], "spec": validate_spec(job_key, payload["spec"])}
    warnings = []
    occurrences = set()
    cursor = moment or utc_now()
    horizon = cursor.astimezone(timezone.utc) + timedelta(days=14)
    for _ in range(338):
        cursor = next_run(after["spec"], cursor)
        if cursor.astimezone(timezone.utc) > horizon:
            break
        occurrences.add(cursor.astimezone(timezone.utc))
    for other in SCHEDULES:
        if other == job_key:
            continue
        model = schedule_model(con, other, defaults.get(other, False))
        if not after["enabled"] or not model["enabled"]:
            continue
        cursor = moment or utc_now()
        for _ in range(338):
            cursor = next_run(model["spec"], cursor)
            if cursor.astimezone(timezone.utc) > horizon:
                break
            if cursor.astimezone(timezone.utc) in occurrences:
                warnings.append(f"Одночасний запланований старт: {other}")
                break
    warnings.append("Різний час старту не гарантує відсутності overlap довгих jobs")
    return {"before": before, "after": after, "expected_revision": before["revision"],
            "next_run": next_run(after["spec"], moment).isoformat() if after["enabled"] else None,
            "warnings": warnings, "immediate_run": False}


def apply_schedule(con, job_key, payload, expected_revision, actor, *, moment=None, defaults=None):
    """Caller holds BEGIN IMMEDIATE; never migrates, registers or touches leases."""
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("Invalid expected revision")
    preview = preview_schedule(con, job_key, payload, defaults, moment)
    before = preview["before"]
    if before["revision"] != expected_revision:
        raise RevisionConflict("Schedule changed; preview again")
    revision = expected_revision + 1
    stamp = _iso(moment or utc_now())
    after = {**preview["after"], "revision": revision, "updated_at": stamp, "configuration_source": "runtime"}
    body = lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    con.execute("""INSERT INTO scheduler_job_settings
        (job_key,enabled,updated_at,updated_by,schedule_json,timezone,revision)
        VALUES (?,?,?,?,?,?,?) ON CONFLICT(job_key) DO UPDATE SET
        enabled=excluded.enabled,updated_at=excluded.updated_at,updated_by=excluded.updated_by,
        schedule_json=excluded.schedule_json,timezone=excluded.timezone,revision=excluded.revision""",
        (job_key, int(after["enabled"]), stamp, actor, body(after["spec"]), "Europe/Kyiv", revision))
    con.execute("INSERT INTO scheduler_schedule_audit VALUES (?,?,?,?,?,?)",
                (job_key, revision, body(before), body(after), actor, stamp))
    return {**after, "updated_at": stamp}


def rollback_payload(con, job_key, revision):
    row = con.execute("SELECT before_json FROM scheduler_schedule_audit WHERE job_key=? AND revision=?",
                      (job_key, revision)).fetchone()
    if not row:
        raise ValueError("Previous revision not available")
    previous = json.loads(row[0])
    return {k: previous[k] for k in ("enabled", "spec", "timezone")}


def claim(db_path, job_key: str, *, trigger: str, now: datetime | None = None,
          lease_seconds: int = 180, owner_id: str | None = None,
          expected_revision: int | None = None) -> str | None:
    if job_key not in SCHEDULES:
        raise ValueError(f"Unknown scheduler job: {job_key}")
    stamp = (now or utc_now()).astimezone(timezone.utc)
    owner = owner_id or uuid.uuid4().hex
    with closing(sqlite3.connect(db_path, timeout=30, isolation_level=None)) as con:
        con.execute("PRAGMA busy_timeout=30000")
        migrate(con)
        con.execute("BEGIN IMMEDIATE")
        if expected_revision is not None:
            model = schedule_model(con, job_key, default_enabled=True)
            if model["revision"] != expected_revision or not model["enabled"]:
                con.rollback()
                return None
        lease = con.execute("SELECT owner_id,lease_until FROM scheduler_job_leases WHERE job_key=?",
                            (job_key,)).fetchone()
        if lease:
            try:
                active = datetime.fromisoformat(lease[1].replace("Z", "+00:00")) > stamp
            except ValueError:
                active = False
            if active:
                con.rollback()
                return None
        con.execute("REPLACE INTO scheduler_job_leases(job_key,owner_id,acquired_at,lease_until) VALUES (?,?,?,?)",
                    (job_key, owner, _iso(stamp), _iso(stamp + timedelta(seconds=lease_seconds))))
        con.execute("""UPDATE scheduler_job_state SET last_started_at=?,last_status='running',last_error='',
                       last_trigger=?,last_owner=?,updated_at=? WHERE job_key=?""",
                    (_iso(stamp), trigger, owner, _iso(stamp), job_key))
        con.commit()
    return owner


def renew(db_path, job_key: str, owner_id: str, *, now: datetime | None = None,
          lease_seconds: int = 180) -> bool:
    stamp = (now or utc_now()).astimezone(timezone.utc)
    with closing(sqlite3.connect(db_path, timeout=30)) as con, con:
        return con.execute("UPDATE scheduler_job_leases SET lease_until=? WHERE job_key=? AND owner_id=?",
                           (_iso(stamp + timedelta(seconds=lease_seconds)), job_key, owner_id)).rowcount == 1


@contextmanager
def keepalive(db_path, job_key: str, owner_id: str):
    """Renew a long-running job; a killed process releases its lease in <=3 min."""
    stopped = threading.Event()
    def heartbeat():
        while not stopped.wait(30):
            try:
                if not renew(db_path, job_key, owner_id):
                    logging.getLogger('pqm.server').error('Scheduler lease ownership lost job=%s', job_key)
                    return
            except Exception:
                logging.getLogger('pqm.server').exception('Scheduler lease renewal failed job=%s', job_key)
    thread = threading.Thread(target=heartbeat, name=f'pqm-lease-{job_key}', daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=1)


def finish(db_path, job_key: str, owner_id: str, *, status: str = "ok", error: str = "",
           now: datetime | None = None) -> bool:
    stamp = (now or utc_now()).astimezone(timezone.utc)
    with closing(sqlite3.connect(db_path, timeout=30, isolation_level=None)) as con:
        migrate(con)
        con.execute("BEGIN IMMEDIATE")
        lease = con.execute("SELECT owner_id FROM scheduler_job_leases WHERE job_key=?", (job_key,)).fetchone()
        if not lease or lease[0] != owner_id:
            con.rollback()
            return False
        con.execute("DELETE FROM scheduler_job_leases WHERE job_key=? AND owner_id=?", (job_key, owner_id))
        con.execute("""UPDATE scheduler_job_state SET last_finished_at=?,last_status=?,last_error=?,
                       updated_at=? WHERE job_key=?""", (_iso(stamp), status, str(error or ""), _iso(stamp), job_key))
        con.commit()
    return True


def release(db_path, job_key: str, owner_id: str) -> None:
    with closing(sqlite3.connect(db_path, timeout=30)) as con, con:
        migrate(con)
        con.execute("DELETE FROM scheduler_job_leases WHERE job_key=? AND owner_id=?", (job_key, owner_id))


def state(db_path, enabled: dict[str, bool], moment: datetime | None = None) -> list[dict]:
    current = as_kyiv(moment)
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)) as con:
        con.row_factory = sqlite3.Row
        stored = {row["job_key"]: dict(row) for row in con.execute("SELECT * FROM scheduler_job_state")}
        models = {key: schedule_model(con, key, enabled.get(key, False)) for key in SCHEDULES}
    items = []
    for job_key, schedule in SCHEDULES.items():
        is_enabled = bool(enabled.get(job_key))
        upcoming = None
        if is_enabled:
            upcoming = next_run(models[job_key]["spec"], current)
        duration = None
        saved = stored.get(job_key, {})
        try:
            if saved.get("last_status") != "running":
                delta = datetime.fromisoformat(saved["last_finished_at"]) - datetime.fromisoformat(saved["last_started_at"])
                if delta.total_seconds() >= 0:
                    duration = round(delta.total_seconds(), 3)
        except (KeyError, TypeError, ValueError):
            pass
        items.append({"job": job_key, "enabled": is_enabled, "schedule": schedule_label(models[job_key]["spec"]),
                      "schedule_model": models[job_key], "duration_seconds": duration,
                      "timezone": "Europe/Kyiv", "next_run": upcoming.isoformat() if upcoming else None,
                      **stored.get(job_key, {})})
    return items
