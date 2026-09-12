"""Persistent, timezone-aware scheduler primitives for PQM background jobs."""
from __future__ import annotations

import sqlite3
import uuid
import logging
import threading
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
    current = as_kyiv(moment)
    candidate = current.replace(minute=5, second=0, microsecond=0)
    if candidate <= current:
        candidate += timedelta(hours=1)
    return candidate


def next_nazk_run(moment: datetime | None = None) -> datetime:
    current = as_kyiv(moment)
    candidate = current.replace(hour=9, minute=20, second=0, microsecond=0)
    if candidate <= current:
        candidate += timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def nazk_due_today(moment: datetime | None, last_finished_at: str | None) -> bool:
    current = as_kyiv(moment)
    if current.weekday() >= 5 or (current.hour, current.minute) < (9, 20):
        return False
    if not last_finished_at:
        return True
    try:
        last_day = datetime.fromisoformat(last_finished_at.replace("Z", "+00:00")).astimezone(KYIV).date()
    except ValueError:
        return True
    return last_day != current.date()


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
                 *, moment: datetime | None = None) -> None:
    if job_key not in SCHEDULES:
        raise ValueError(f"Unknown scheduler job: {job_key}")
    migrate(con)
    stamp = _iso((moment or utc_now()).astimezone(timezone.utc))
    con.execute("""INSERT INTO scheduler_job_settings(job_key,enabled,updated_at,updated_by)
      VALUES (?,?,?,?) ON CONFLICT(job_key) DO UPDATE SET enabled=excluded.enabled,
      updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
      (job_key, int(bool(enabled)), stamp, str(actor or "Administrator")))


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def claim(db_path, job_key: str, *, trigger: str, now: datetime | None = None,
          lease_seconds: int = 180, owner_id: str | None = None) -> str | None:
    if job_key not in SCHEDULES:
        raise ValueError(f"Unknown scheduler job: {job_key}")
    stamp = (now or utc_now()).astimezone(timezone.utc)
    owner = owner_id or uuid.uuid4().hex
    with closing(sqlite3.connect(db_path, timeout=30, isolation_level=None)) as con:
        con.execute("PRAGMA busy_timeout=30000")
        migrate(con)
        con.execute("BEGIN IMMEDIATE")
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
    items = []
    for job_key, schedule in SCHEDULES.items():
        is_enabled = bool(enabled.get(job_key))
        next_run = None
        if is_enabled:
            next_run = next_nazk_run(current) if job_key == "nazk_registry" else next_hourly_run(current)
        items.append({"job": job_key, "enabled": is_enabled, "schedule": schedule,
                      "timezone": "Europe/Kyiv", "next_run": next_run.isoformat() if next_run else None,
                      **stored.get(job_key, {})})
    return items
