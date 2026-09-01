"""PQM 0.1 local server: SQLite storage, Prozorro sync and browser API."""
from __future__ import annotations

import json
import base64
import csv
import hashlib
import html
import io
import itertools
import hmac
import logging
from logging.handlers import RotatingFileHandler
import mimetypes
import os
import re
import secrets
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import urllib.request
import uuid
import webbrowser
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from protocol_docx import build_protocol_docx
from violation_protocol_docx import (TEMPLATES, build_violation_protocol_docx,
                                     ensure_runtime_templates, replace_runtime_template,
                                     template_metadata)
from nazk_workflow import (
    complete_submission_nazk_check, complete_supplier_nazk_check,
    ensure_submission_nazk_control, mark_supplier_nazk_request_sent,
    get_submission_nazk_control, get_submission_nazk_state, get_submission_nazk_states,
    get_submission_nazk_presentation_state,
    get_supplier_application_nazk_state, get_supplier_nazk_presentation_state,
    registry_matches,
    reconcile_active_supplier_nazk,
    transitional_submission_backfill_dry_run,
)
from reference_directories import (
    init_reference_tables, list_registry, reference_status,
    refresh_amcu, refresh_nazk, start_reference_refresh,
)
from uo_work_queue import get_uo_work_queue

ROOT = Path(__file__).resolve().parent


def configure_file_logging() -> logging.Logger:
    """Persist LOCAL diagnostics without recording payloads or credentials."""
    logger = logging.getLogger("pqm.server")
    if logger.handlers:
        return logger
    log_dir = Path(os.environ.get("PQM_LOG_DIR", str(ROOT / "logs"))).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "server.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


SERVER_LOG = configure_file_logging()


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


PQM_ENV = os.environ.get("PQM_ENV", "local").strip().casefold() or "local"
IS_WEB_ENV = PQM_ENV in {"test", "test_web", "web", "production"}
DATA_DIR = Path(os.environ.get("PQM_DATA_DIR", str(ROOT / "data"))).resolve()
DB_PATH = Path(os.environ.get("PQM_DB_PATH", str(DATA_DIR / "pqm.sqlite3"))).resolve()
PROTOCOLS_DIR = Path(os.environ.get("PQM_PROTOCOLS_DIR", str(DATA_DIR / "protocols"))).resolve()
RUNTIME_CACHE_DIR = Path(os.environ.get("PQM_CACHE_DIR", str(DATA_DIR / "cache"))).resolve()
HOST = os.environ.get("HOST", "0.0.0.0" if IS_WEB_ENV else "127.0.0.1")
PORT = int(os.environ.get("PORT", "10000" if IS_WEB_ENV else "8080"))
ENABLE_BROWSER = env_flag("PQM_ENABLE_BROWSER", not IS_WEB_ENV)
ENABLE_SCHEDULER = env_flag("PQM_ENABLE_SCHEDULER", not IS_WEB_ENV)
ENABLE_NAZK_SCHEDULER = env_flag("PQM_ENABLE_NAZK_SCHEDULER", not IS_WEB_ENV)
AUTH_ENABLED = env_flag("PQM_AUTH_ENABLED", False)
LOCAL_ROLE_IMPERSONATION = env_flag("PQM_LOCAL_ROLE_IMPERSONATION", not IS_WEB_ENV)
BIDS_MODE = os.environ.get("PQM_BIDS_MODE", "disabled" if IS_WEB_ENV else "readonly").strip().casefold()
ENABLE_BIDS_UPDATE = env_flag("PQM_ENABLE_BIDS_UPDATE", not IS_WEB_ENV)
ENABLE_POWERBI = env_flag("PQM_ENABLE_POWERBI", not IS_WEB_ENV)
ENABLE_GOOGLE = env_flag("PQM_ENABLE_GOOGLE", not IS_WEB_ENV)
EDS_ADAPTER_PATH = ROOT / "tools" / "prozorro_eds_adapter" / "verify-signature.mjs"
EDS_TIMEOUT_SECONDS = max(5, int(os.environ.get("PQM_EDS_TIMEOUT_SECONDS", "35")))
BIDS_DB_PATH = Path(os.environ.get(
    "PQM_BIDS_DB",
    str(DATA_DIR / "prozorro_bids.db"),
))
BIDS_STATUS_CACHE: dict = {"at": 0.0, "value": None}
BIDS_STATUS_LOCK = threading.Lock()
BIDS_PROJECT_PATH = Path(os.environ.get(
    "PQM_BIDS_PROJECT_DIR",
    str(DATA_DIR),
))
BIDS_PYTHON = Path(os.environ.get(
    "PQM_BIDS_PYTHON",
    sys.executable,
))
BIDS_UPDATE_STATE = {"running": False, "message": "Ручне оновлення ще не запускали", "started_at": None,
                     "updated_at": None, "date_from": None, "date_to": None, "error": None}
POWERBI_EXPORT_STATE = {"running": False, "message": "Експорт ще не запускали", "started_at": None,
                        "updated_at": None, "error": None}
POWERBI_OUTPUT_ROOT = BIDS_PROJECT_PATH / "output"
POWERBI_CURRENT_PATH = POWERBI_OUTPUT_ROOT / "powerbi_current"
SUPPLIER_EDR_SHEET_ID = "1rqghaEduW8Aer4ri36aysMurEdK2UH5laXKw_Oo1FKA"
SUPPLIER_EDR_SHEETS = {"ФОП": "1278053622", "ЮО": "511647713"}
SUPPLIER_NAZK_REVIEW_SHEET_ID = "1hAgy_YQFWf8m6yHQTO4g22Et94Gm46dC9WTBaoyZloA"
SUPPLIER_NAZK_REVIEW_SHEET = "nazk_data"
CURRENT_USER = os.environ.get("PQM_CURRENT_USER", "PQM System")
GOOGLE_OAUTH_DIR = Path(os.environ.get("PQM_GOOGLE_OAUTH_DIR", str((Path(os.environ.get("LOCALAPPDATA", str(DATA_DIR))) / "PQM") if not IS_WEB_ENV else (DATA_DIR / "google_oauth"))))
GOOGLE_OAUTH_CLIENT_PATH = Path(os.environ.get("PQM_GOOGLE_OAUTH_CLIENT", str(GOOGLE_OAUTH_DIR / "google_oauth_client.json")))
GOOGLE_OAUTH_TOKEN_PATH = Path(os.environ.get("PQM_GOOGLE_OAUTH_TOKEN", str(GOOGLE_OAUTH_DIR / "google_oauth_token.json")))
GOOGLE_SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
GOOGLE_OAUTH_PENDING: dict[str, dict] = {}
SUPPLIER_EDR_SYNC_STATE = {"running": False, "message": "Довідник ЄДР ще не синхронізували",
                           "started_at": None, "updated_at": None, "processed": 0,
                           "inserted": 0, "updated": 0, "error": None}
SUPPLIER_NAZK_REVIEW_SYNC_STATE = {"running": False, "message": "Перевірки НАЗК ще не синхронізували",
                                   "started_at": None, "updated_at": None, "processed": 0,
                                   "inserted": 0, "updated": 0, "error": None}
TESSERACT_EXE = Path(os.environ.get(
    "PQM_TESSERACT_EXE",
    shutil.which("tesseract") or ("/usr/bin/tesseract" if IS_WEB_ENV else "tesseract"),
))
TESSDATA_DIR = ROOT / "tools" / "tessdata"
PDFTOPPM_EXE = Path(os.environ.get(
    "PQM_PDFTOPPM_EXE",
    shutil.which("pdftoppm") or ("/usr/bin/pdftoppm" if IS_WEB_ENV else "pdftoppm"),
))
API_ROOT = "https://public-api.prozorro.gov.ua/api/2.5"
ORGANIZER_EDRPOU = "40996564"
DEFAULT_FRAMEWORK_ID = "92e49fa487da40b3ab080b030f8a2b5d"
ANNOUNCEMENTS_CSV = "https://docs.google.com/spreadsheets/d/1kdjP1Yr5C5UuO-Otju8xC8eo7p5BMewTCDdkLyS6Ofg/export?format=csv&gid=1378255205"
ANNOUNCEMENTS_SHEET_ID = "1kdjP1Yr5C5UuO-Otju8xC8eo7p5BMewTCDdkLyS6Ofg"
REMARKS_CSV = "https://docs.google.com/spreadsheets/d/1S94-jj5ys-BIwiWeWhxVNwRFilMrq0erOuJGWMXci1w/export?format=csv&gid=1118329674"
REMARKS_CACHE = Path(os.environ.get("PQM_REMARKS_CACHE", str(DATA_DIR / "remarks_catalog.json")))
# Destination selected by the administrator for finished review protocols.
# The local MVP still generates files on disk first; Drive upload requires the
# PQM Google OAuth integration and must not depend on a local interactive session.
PROTOCOLS_DRIVE_FOLDER_ID = "1OFlBRzYFtJ8PZ7oAks7NpKb2ZnHds7XF"
PROTOCOLS_DRIVE_FOLDER_URL = f"https://drive.google.com/drive/folders/{PROTOCOLS_DRIVE_FOLDER_ID}"
EDITABLE_FIELDS = {
    "protocol_number", "protocol_date", "publication_date", "protocol_officer",
    "protocol_remarks", "protocol_decision", "marketplace_decision", "compliance_status", "compliance_comments",
    "manager_name", "document_package", "contract_details", "authority_review", "mvs_seal_review", "notes"
}


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """Prevent two PQM processes from sharing port 8080 on Windows."""
    allow_reuse_address = False

    def server_bind(self):
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if os.name == "nt" and exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


class BidsUnavailableError(RuntimeError):
    """The optional read-only ProzorroBids source is unavailable."""


class ForeignAuthorityError(PermissionError):
    """The violation report belongs to another central purchasing body."""


AUTH_ROLES = {"admin", "officer", "viewer"}
AUTH_SESSIONS: dict[str, dict] = {}
AUTH_SESSIONS_LOCK = threading.Lock()
AUTH_SESSION_TTL = 12 * 60 * 60
AUTH_COOKIE = "pqm_session"


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Пароль має містити щонайменше 10 символів")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260_000)
    return f"pbkdf2_sha256:260000:{salt.hex()}:{digest.hex()}"


def configured_auth_accounts() -> dict[str, dict]:
    """Parse TEST/LOCAL accounts. Legacy username:secret entries remain admin."""
    raw = os.environ.get("PQM_USERS_JSON", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("PQM_USERS_JSON містить некоректний JSON") from exc
    if isinstance(payload, dict) and isinstance(payload.get("users"), list):
        payload = payload["users"]
    accounts = {}
    if isinstance(payload, dict):
        for name, value in payload.items():
            if not str(name).strip():
                continue
            if isinstance(value, dict):
                secret = value.get("password") if "password" in value else value.get("password_hash")
                role = str(value.get("role") or "").strip().casefold()
                if secret is not None and role in AUTH_ROLES:
                    accounts[str(name)] = {"secret": str(secret), "role": role,
                                           "officer_id": value.get("officer_id")}
            else:
                accounts[str(name)] = {"secret": str(value), "role": "admin"}
        return accounts
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = str(item.get("username") or item.get("user") or "").strip()
            secret = item.get("password") if "password" in item else item.get("password_hash")
            role = str(item.get("role") or "").strip().casefold()
            # Legacy list entries had no role. Preserve access as admin during migration.
            if name and secret is not None and (role in AUTH_ROLES or not role):
                accounts[name] = {"secret": str(secret), "role": role or "admin",
                                  "officer_id": item.get("officer_id")}
        return accounts
    raise RuntimeError("PQM_USERS_JSON має містити object або масив users")


def configured_basic_auth_users() -> dict[str, str]:
    """Read Basic Auth users from the environment without writing credentials to disk."""
    return {name: account["secret"] for name, account in configured_auth_accounts().items()}


def auth_accounts() -> dict[str, dict]:
    accounts = configured_auth_accounts()
    try:
        with db() as con:
            for row in con.execute("SELECT username,password_hash,role,officer_id,active FROM auth_users"):
                accounts[row["username"]] = {"secret": row["password_hash"], "role": row["role"],
                                              "officer_id": row["officer_id"], "active": bool(row["active"])}
    except sqlite3.OperationalError:
        pass
    return accounts


def mutation_allowed(role: str, method: str, path: str) -> bool:
    if method not in {"POST", "PATCH", "PUT", "DELETE"}:
        return True
    if role == "admin":
        return True
    if role != "officer":
        return False
    officer_patterns = (
        r"^/api/applications/[^/]+$",
        r"^/api/applications/[^/]+/(?:verify-documents|verify-documents/start|nazk-control)$",
        r"^/api/protocol/(?:readiness|generate)$",
        r"^/api/violation-reports/[^/]+/(?:review|review/complete|protocol/generate)$",
        r"^/api/violation-reports/[^/]+/documents/(?:customer|supplier)/[^/]+$",
        r"^/api/suppliers/[^/]+/nazk-check$",
    )
    return any(re.fullmatch(pattern, path) for pattern in officer_patterns)


def admin_read_allowed(role: str, path: str, query: dict[str, list[str]] | None = None) -> bool:
    """Protect administration reads while keeping work-filter data available."""
    if role == "admin":
        return True
    if path == "/api/admin/officers" and (query or {}).get("active") == ["1"]:
        return True
    if path == "/api/admin/frameworks":
        return True
    return not (path.startswith("/api/admin/") or path == "/api/audit")


def officer_mutation_scope_allowed(path: str, officer_id) -> bool:
    """Restrict officer mutations to assigned work; unassigned appeals may be claimed."""
    try:
        officer_id = int(officer_id)
    except (TypeError, ValueError):
        return False
    with db() as con:
        officer = con.execute("SELECT full_name,active FROM authorized_officers WHERE id=?", (officer_id,)).fetchone()
        if not officer or not officer["active"]:
            return False
        application = re.fullmatch(r"/api/applications/([^/]+)(?:/.*)?", path)
        if application:
            row = con.execute("""SELECT COALESCE(NULLIF(af.protocol_officer,''),fo.officer,'') officer
              FROM submissions s LEFT JOIN application_fields af ON af.submission_id=s.id
              LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id WHERE s.id=?""",
              (urllib.parse.unquote(application.group(1)),)).fetchone()
            return bool(row and normalized_officer_name(row["officer"]) == normalized_officer_name(officer["full_name"]))
        report = re.fullmatch(r"/api/violation-reports/([^/]+)/(?:review(?:/complete)?|protocol/generate|documents/.*)", path)
        if report:
            row = con.execute("""SELECT r.assigned_officer_id FROM violation_report_reviews r
              JOIN violation_reports v ON v.id=r.report_id
              WHERE v.id=? OR v.report_id=?""", (urllib.parse.unquote(report.group(1)),
              urllib.parse.unquote(report.group(1)))).fetchone()
            return not row or row["assigned_officer_id"] in (None, officer_id)
    # Non-row officer actions (for example protocol readiness) remain allowed.
    return True


def verify_basic_auth_secret(provided: str, configured: str) -> bool:
    """Support current env passwords and an explicit sha256: digest for secret rotation."""
    if configured.startswith("sha256:"):
        digest = hashlib.sha256(provided.encode("utf-8")).hexdigest()
        return hmac.compare_digest(digest, configured.removeprefix("sha256:"))
    if configured.startswith("pbkdf2_sha256:"):
        try:
            _, iterations, salt, expected = configured.split(":", 3)
            digest = hashlib.pbkdf2_hmac("sha256", provided.encode(), bytes.fromhex(salt), int(iterations)).hex()
            return hmac.compare_digest(digest, expected)
        except (ValueError, TypeError):
            return False
    return hmac.compare_digest(provided, configured)
PROTOCOL_DECISIONS = {"", "admit", "reject"}
MARKETPLACE_DECISIONS = {"", "admit", "reject"}
COMPLIANCE_STATUSES = {"", "approved", "rejected"}
AUTHORITY_REVIEWS = {"", "approved", "missing", "not_required"}
# The public TEST WEB package never seeds personal data. Existing officers live
# on the persistent disk and a clean environment is configured via the admin UI.
INITIAL_AUTHORIZED_OFFICERS = ()


def normalized_officer_name(value: str) -> str:
    return " ".join(str(value or "").split()).upper()


def formatted_officer_name(value: str) -> str:
    """Canonical presentation/storage form: Ім'я ПРІЗВИЩЕ."""
    parts = " ".join(str(value or "").split()).split()
    if not parts:
        return ""
    titled = [part.lower().capitalize() for part in parts[:-1]]
    return " ".join([*titled, parts[-1].upper()])


def authorized_officers(active_only: bool = False) -> list[dict]:
    with db() as con:
        where = "WHERE active=1" if active_only else ""
        rows = [dict(row) for row in con.execute(
            f"SELECT id,full_name,role,active,created_at,updated_at FROM authorized_officers {where} ORDER BY active DESC,full_name"
        )]
    active_frameworks = framework_service_directory()["items"] if rows else []
    counts = {}
    for framework in active_frameworks:
        if framework.get("status") == "Активний" and framework.get("responsible_officer"):
            key = normalized_officer_name(framework["responsible_officer"])
            counts[key] = counts.get(key, 0) + 1
    for row in rows:
        row["active"] = bool(row["active"])
        row["active_frameworks"] = counts.get(normalized_officer_name(row["full_name"]), 0)
        row["usage_count"] = officer_usage_count(row["id"], row["full_name"])
        row["can_delete"] = row["usage_count"] == 0
        row["full_name"] = formatted_officer_name(row["full_name"])
    return rows


def officer_usage_count(officer_id: int, full_name: str) -> int:
    """Count subject references; creation/deactivation audit is intentionally preserved."""
    queries = (
        ("violation_report_reviews", "assigned_officer_id", officer_id),
        ("violation_report_reviews", "assigned_officer", full_name),
        ("application_fields", "protocol_officer", full_name),
        ("application_fields", "review_officer", full_name),
        ("framework_officers", "officer", full_name),
        ("framework_service_directory", "responsible_officer", full_name),
        ("supplier_nazk_reviews", "officer", full_name),
    )
    with db() as con:
        return sum(con.execute(f"SELECT COUNT(*) FROM {table} WHERE {column}=?", (value,)).fetchone()[0]
                   for table, column, value in queries)


def valid_active_officer(value: str) -> bool:
    normalized = normalized_officer_name(value)
    if not normalized:
        return True
    with db() as con:
        return bool(con.execute(
            "SELECT 1 FROM authorized_officers WHERE UPPER(full_name)=? AND active=1", (normalized,)
        ).fetchone())
SYNC_STATE = {"running": False, "message": "Синхронізацію ще не запускали", "updated_at": None,
              "started_at": None, "next_run_at": None, "mode": None, "duration_seconds": None}
SYNC_STATE_LOCK = threading.Lock()
VIOLATION_SYNC_STATE = {"running": False, "message": "Звернення ще не синхронізувалися", "updated_at": None,
                        "processed": 0, "total": 0, "errors": 0, "stop_requested": False}
DOCUMENT_CHECK_JOBS = {}
DOCUMENT_CHECK_LOCK = threading.Lock()
DEFAULT_REMARKS = [
    ("п. 1", "заявку підписано за допомогою особистого КЕП/УЕП представника Учасника", "КЕП"),
    ("п. 1", "ідентифікаційний код у підписі не відповідає ідентифікаційному коду Учасника", "КЕП"),
    ("п. 1", "не надано документів на підтвердження повноважень особи на підписання та подання документів", "Повноваження"),
    ("п. 2", "відсутня інформація про виконаний договір в електронній системі закупівель prozorro.gov.ua", "Досвід"),
    ("п. 2", "не надано копію виконаного договору разом з документами, що підтверджують його виконання", "Досвід"),
    ("п. 2", "наданий договір не містить інформації про аналогічний товар, його обсяг та строк постачання", "Досвід"),
    ("п. 2", "не надано видаткові накладні, що підтверджують виконання договору", "Досвід"),
    ("п. 2", "не надано документи, що підтверджують розрахунки за договором у повному обсязі", "Досвід"),
    ("п. 2", "загальна вартість видаткових накладних не відповідає вартості документів, що підтверджують оплату", "Досвід"),
    ("п. 2", "платіжна інструкція не містить інформації, яка дозволяє ідентифікувати договір або видаткову накладну", "Досвід"),
    ("п. 3.1", "не надано витяг з інформаційно-аналітичної системи «Облік відомостей про притягнення особи до кримінальної відповідальності та наявності судимості»", "Витяг МВС"),
    ("п. 3.1", "не надано файл електронної печатки Міністерства внутрішніх справ України до витягу", "Витяг МВС"),
    ("п. 3.1", "надано скорочений витяг з інформаційно-аналітичної системи МВС", "Витяг МВС"),
    ("п. 3.1", "ПІБ у витягу МВС не відповідає ПІБ керівника Учасника", "Витяг МВС"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def violation_threshold_summary(decision_dates, moment: datetime | None = None) -> dict:
    """Count satisfied reports in inclusive p. 52 calendar windows."""
    today = (moment or datetime.now().astimezone()).date()
    month_start = today.replace(day=1)
    three_month_index = today.year * 12 + today.month - 3
    three_month_start = today.replace(
        year=three_month_index // 12,
        month=three_month_index % 12 + 1,
        day=1,
    )
    parsed_dates = []
    for value in decision_dates:
        text = str(value or "").strip()
        if not text:
            continue
        parsed = None
        for candidate, pattern in ((text[:10], "%Y-%m-%d"), (text[:10], "%d.%m.%Y")):
            try:
                parsed = datetime.strptime(candidate, pattern).date()
                break
            except ValueError:
                pass
        if parsed is not None and parsed <= today:
            parsed_dates.append(parsed)
    return {
        "current_month": sum(month_start <= value <= today for value in parsed_dates),
        "three_calendar_months": sum(three_month_start <= value <= today for value in parsed_dates),
        "current_month_limit": 3,
        "three_calendar_months_limit": 5,
        "current_month_from": month_start.isoformat(),
        "three_calendar_months_from": three_month_start.isoformat(),
        "calculated_to": today.isoformat(),
        "thresholds_available": True,
        "date_basis": "decision_date",
    }


def remarks_catalog(force: bool = False) -> dict:
    """Return the editable local directory; optionally import new Sheet rows."""
    if not force:
        with db() as con:
            rows = [dict(row) for row in con.execute("""SELECT id,point,text,tag,category,active,updated_at
              FROM remarks_catalog WHERE active=1 ORDER BY point,category,id""")]
        return {"items": rows, "refreshed_at": max((row["updated_at"] for row in rows), default=None), "source": "local-database"}
    cached = None
    if REMARKS_CACHE.exists():
        try:
            cached = json.loads(REMARKS_CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = None
    if cached and not force:
        try:
            if datetime.fromisoformat(cached.get("refreshed_at", "")).timestamp() > time.time() - 3600:
                return cached
        except ValueError:
            pass
    try:
        request = urllib.request.Request(REMARKS_CSV, headers={"User-Agent": "PQM/0.1"})
        with urllib.request.urlopen(request, timeout=20) as response:
            text = response.read().decode("utf-8-sig")
        items, seen = [], set()
        for row_number, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
            point = str(row.get("Пункти") or "").strip()
            remark = str(row.get("Текст зауваження") or "").strip()
            if not point or not remark:
                continue
            key = (point.casefold(), re.sub(r"\s+", " ", remark).casefold())
            if key in seen:
                continue
            seen.add(key)
            items.append({"id": f"sheet-{row_number}", "point": point, "text": remark,
                          "tag": str(row.get("Доки") or "").strip(),
                          "category": str(row.get("категорії") or "").strip(),
                          "source_row": row_number})
        result = {"items": items, "refreshed_at": now_iso(), "source": "google-sheet"}
        REMARKS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        REMARKS_CACHE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        with db() as con:
            for item in items:
                exists = con.execute("SELECT 1 FROM remarks_catalog WHERE point=? AND text=?", (item["point"], item["text"])).fetchone()
                if not exists:
                    con.execute("INSERT INTO remarks_catalog(point,text,tag,category,active,updated_at) VALUES (?,?,?,?,1,?)",
                                (item["point"], item["text"], item["tag"], item["category"], now_iso()))
        return remarks_catalog(False)
    except Exception as exc:
        if cached:
            cached["source"] = "local-cache"; cached["warning"] = str(exc)
            return cached
        items = [{"id": f"local-{index}", "point": point, "text": text, "tag": tag,
                  "category": "", "source_row": None}
                 for index, (point, text, tag) in enumerate(DEFAULT_REMARKS, start=1)]
        return {"items": items, "refreshed_at": None, "source": "built-in", "warning": str(exc)}


def announcement_officer_name(value: str) -> str:
    clean = (value or "").strip()
    if not clean:
        return ""
    normalized = normalized_officer_name(clean)
    with db() as con:
        candidates = [row[0] for row in con.execute(
            "SELECT full_name FROM authorized_officers ORDER BY active DESC, full_name"
        )]
    matches = [name for name in candidates
               if normalized_officer_name(name).split()[-1:] == normalized.split()[-1:]]
    return formatted_officer_name(matches[0]) if len(matches) == 1 else clean


def sync_framework_officers() -> dict:
    rows = load_announcement_rows()
    assignments = {}
    for row in rows:
        pretty_id = (row.get("ID") or "").strip()
        # The service owner of a framework is the officer who publishes it.
        # "Хто розглядає" describes operational review and must not overwrite
        # the framework-level responsibility during the bootstrap import.
        officer = announcement_officer_name(row.get("Хто публікує") or "")
        marketplace_url = (row.get("Посилання на майданчик") or "").strip()
        category = (row.get("Категорія") or row.get("КАТЕГ") or "").strip()
        status = (row.get("status") or "").strip()
        dk_code = (row.get("ДК") or "").strip()
        source_title = (row.get("Назва фреймворку") or row.get("Інформація про категорію товару") or "").strip()
        if pretty_id:
            assignments[pretty_id] = (officer, marketplace_url, category, status, dk_code, source_title)
    matched = 0
    status_counts = {}
    with db() as con:
        for pretty_id, (officer, marketplace_url, category, status, dk_code, source_title) in assignments.items():
            normalized_status = status.casefold() or "не визначено"
            status_counts[normalized_status] = status_counts.get(normalized_status, 0) + 1
            framework = con.execute("SELECT id FROM frameworks WHERE pretty_id=?", (pretty_id,)).fetchone()
            framework_id = framework[0] if framework else None
            con.execute("""INSERT INTO framework_service_directory(
              pretty_id,framework_id,dk_code,category,marketplace_url,responsible_officer,
              source_title,source,synced_at)
              VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(pretty_id) DO UPDATE SET
              framework_id=excluded.framework_id,
              dk_code=CASE WHEN framework_service_directory.source='PQM' THEN framework_service_directory.dk_code ELSE excluded.dk_code END,
              category=CASE WHEN framework_service_directory.source='PQM' THEN framework_service_directory.category ELSE excluded.category END,
              marketplace_url=CASE WHEN framework_service_directory.source='PQM' THEN framework_service_directory.marketplace_url ELSE excluded.marketplace_url END,
              responsible_officer=CASE WHEN framework_service_directory.source='PQM' THEN framework_service_directory.responsible_officer ELSE excluded.responsible_officer END,
              source_title=excluded.source_title,
              source=CASE WHEN framework_service_directory.source='PQM' THEN framework_service_directory.source ELSE excluded.source END,
              synced_at=excluded.synced_at""",
              (pretty_id, framework_id, dk_code, category, marketplace_url, officer,
               source_title, "Google Sheets: Оголошення", now_iso()))
            if not framework:
                continue
            con.execute("""INSERT INTO framework_officers(framework_id,officer,marketplace_url,category,source,synced_at)
              VALUES (?,?,?,?,?,?) ON CONFLICT(framework_id) DO UPDATE SET
              officer=CASE WHEN framework_officers.source='PQM' THEN framework_officers.officer ELSE excluded.officer END,
              marketplace_url=CASE WHEN framework_officers.source='PQM' THEN framework_officers.marketplace_url ELSE excluded.marketplace_url END,
              category=CASE WHEN framework_officers.source='PQM' THEN framework_officers.category ELSE excluded.category END,
              source=CASE WHEN framework_officers.source='PQM' THEN framework_officers.source ELSE excluded.source END,
              synced_at=excluded.synced_at""",
              (framework_id, officer, marketplace_url, category, "Google Sheets: Оголошення", now_iso()))
            matched += 1
    return {"rows": len(rows), "unique": len(assignments), "matched": matched,
            "unmatched": len(assignments) - matched, "statuses": status_counts}


def load_announcement_rows() -> list[dict]:
    try:
        request = urllib.request.Request(ANNOUNCEMENTS_CSV, headers={"User-Agent": "PQM/0.1"})
        with urllib.request.urlopen(request, timeout=30, context=ssl.create_default_context()) as response:
            return list(csv.DictReader(io.StringIO(response.read().decode("utf-8-sig"))))
    except Exception:
        # The directory is private. Reuse the existing read-only OAuth token;
        # do not require public link sharing and do not write to Google Sheets.
        values = _google_sheet_values("Оголошення", ANNOUNCEMENTS_SHEET_ID, "A:Z")
        if not values:
            return []
        headers = [str(value or "").strip() for value in values[0]]
        return [dict(zip(headers, list(row) + [""] * (len(headers) - len(row)))) for row in values[1:]]


def unicode_casefold(value: str | None) -> str:
    return (value or "").casefold()


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=60)
    con.row_factory = sqlite3.Row
    con.create_function("CASEFOLD", 1, unicode_casefold, deterministic=True)
    con.create_function("DIGITS", 1, lambda value: re.sub(r"\D", "", str(value or "")), deterministic=True)
    con.create_function(
        "NORMALIZE_NAME", 1,
        lambda value: " ".join(re.sub(r"[’'`\-]+", " ", str(value or "").casefold()).split()),
        deterministic=True,
    )
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=60000")
    return con


def bids_db() -> sqlite3.Connection:
    """Open the large ProzorroBids database read-only."""
    if BIDS_MODE not in {"readonly", "read_only"}:
        raise BidsUnavailableError("Аналітика ProzorroBids вимкнена в цьому середовищі")
    if not BIDS_DB_PATH.is_file():
        raise BidsUnavailableError("Локальна база ProzorroBids недоступна в цьому середовищі")
    try:
        con = sqlite3.connect(f"file:{BIDS_DB_PATH.as_posix()}?mode=ro", uri=True, timeout=30)
    except sqlite3.Error as exc:
        raise BidsUnavailableError("Не вдалося відкрити базу ProzorroBids у read-only режимі") from exc
    con.row_factory = sqlite3.Row
    con.create_function("DIGITS", 1, lambda value: re.sub(r"\D", "", str(value or "")), deterministic=True)
    con.execute("PRAGMA query_only=ON")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS frameworks (
          id TEXT PRIMARY KEY, pretty_id TEXT UNIQUE NOT NULL, title TEXT, dk_code TEXT,
          status TEXT, organizer_edrpou TEXT, agreement_id TEXT, date_modified TEXT,
          raw_json TEXT NOT NULL, synced_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS submissions (
          id TEXT PRIMARY KEY, framework_id TEXT NOT NULL REFERENCES frameworks(id),
          supplier_name TEXT, supplier_code TEXT, date_published TEXT, status TEXT,
          qualification_id TEXT, documents_json TEXT NOT NULL DEFAULT '[]',
          raw_json TEXT NOT NULL, synced_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_submissions_framework ON submissions(framework_id);
        CREATE INDEX IF NOT EXISTS ix_submissions_supplier ON submissions(supplier_code);
        CREATE TABLE IF NOT EXISTS qualifications (
          id TEXT PRIMARY KEY, framework_id TEXT NOT NULL, submission_id TEXT,
          status TEXT, decision_date TEXT, documents_json TEXT NOT NULL DEFAULT '[]',
          raw_json TEXT NOT NULL, synced_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_qualifications_submission ON qualifications(submission_id);
        CREATE TABLE IF NOT EXISTS registry_contracts (
          id TEXT PRIMARY KEY, framework_id TEXT NOT NULL, qualification_id TEXT,
          supplier_code TEXT, status TEXT, milestones_json TEXT NOT NULL DEFAULT '[]',
          raw_json TEXT NOT NULL, synced_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_registry_contracts_qualification ON registry_contracts(qualification_id);
        CREATE INDEX IF NOT EXISTS ix_registry_contracts_supplier ON registry_contracts(supplier_code);
        CREATE TABLE IF NOT EXISTS supplier_registry_summary (
          supplier_code TEXT PRIMARY KEY, supplier_name TEXT DEFAULT '',
          qualifications_count INTEGER DEFAULT 0, active_count INTEGER DEFAULT 0,
          inactive_count INTEGER DEFAULT 0, suspended_count INTEGER DEFAULT 0,
          frameworks_count INTEGER DEFAULT 0, dk_codes TEXT DEFAULT '',
          last_qualification TEXT DEFAULT '', refreshed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS supplier_edr_profiles (
          supplier_code TEXT PRIMARY KEY, full_name TEXT DEFAULT '', short_name TEXT DEFAULT '',
          manager_name TEXT DEFAULT '', edr_status TEXT DEFAULT '', edr_checked_at TEXT DEFAULT '',
          source_sheet TEXT DEFAULT '', source_row INTEGER DEFAULT 0, synced_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_supplier_edr_manager ON supplier_edr_profiles(manager_name);
        CREATE TABLE IF NOT EXISTS supplier_edr_sync_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
          status TEXT NOT NULL, processed INTEGER DEFAULT 0, inserted INTEGER DEFAULT 0,
          updated INTEGER DEFAULT 0, error TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS supplier_nazk_reviews (
          supplier_code TEXT PRIMARY KEY, supplier_name TEXT DEFAULT '', manager_name TEXT DEFAULT '',
          decision_date TEXT DEFAULT '', case_number TEXT DEFAULT '', result TEXT DEFAULT '',
          evidence_url TEXT DEFAULT '', comment TEXT DEFAULT '', checked_at TEXT DEFAULT '',
          officer TEXT DEFAULT '', source_row INTEGER DEFAULT 0, synced_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_supplier_nazk_review_result ON supplier_nazk_reviews(result);
        CREATE TABLE IF NOT EXISTS supplier_nazk_review_sync_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT,
          status TEXT NOT NULL, processed INTEGER DEFAULT 0, inserted INTEGER DEFAULT 0,
          updated INTEGER DEFAULT 0, error TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS supplier_managers (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          supplier_code TEXT NOT NULL,
          manager_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          manager_tax_id TEXT,
          manager_tax_id_source TEXT,
          manager_tax_id_verified_at TEXT,
          manager_tax_id_verified_by TEXT,
          valid_from TEXT,
          valid_to TEXT,
          is_current INTEGER NOT NULL DEFAULT 0,
          source TEXT DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_supplier_managers_supplier
          ON supplier_managers(supplier_code);
        CREATE INDEX IF NOT EXISTS ix_supplier_managers_name
          ON supplier_managers(normalized_name);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_supplier_managers_current
          ON supplier_managers(supplier_code) WHERE is_current=1;
        CREATE TABLE IF NOT EXISTS supplier_nazk_checks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          supplier_code TEXT NOT NULL,
          manager_id INTEGER REFERENCES supplier_managers(id),
          manager_name TEXT NOT NULL,
          workflow_status TEXT NOT NULL,
          result TEXT,
          started_at TEXT NOT NULL,
          completed_at TEXT,
          evidence_date TEXT,
          covered_nazk_date TEXT,
          comment TEXT DEFAULT '',
          is_legacy INTEGER NOT NULL DEFAULT 0,
          legacy_source_row INTEGER,
          legacy_key TEXT,
          created_at TEXT NOT NULL,
          created_by TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          updated_by TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_supplier_nazk_checks_supplier
          ON supplier_nazk_checks(supplier_code,started_at DESC);
        CREATE INDEX IF NOT EXISTS ix_supplier_nazk_checks_manager
          ON supplier_nazk_checks(manager_id,started_at DESC);
        CREATE INDEX IF NOT EXISTS ix_supplier_nazk_checks_state
          ON supplier_nazk_checks(workflow_status,result);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_supplier_nazk_checks_legacy
          ON supplier_nazk_checks(legacy_key) WHERE legacy_key IS NOT NULL;
        CREATE TABLE IF NOT EXISTS supplier_nazk_check_matches (
          check_id INTEGER NOT NULL REFERENCES supplier_nazk_checks(id) ON DELETE CASCADE,
          nazk_source_id TEXT NOT NULL REFERENCES nazk_registry(source_id),
          match_status TEXT NOT NULL DEFAULT 'candidate',
          created_at TEXT NOT NULL,
          PRIMARY KEY(check_id,nazk_source_id)
        );
        CREATE INDEX IF NOT EXISTS ix_supplier_nazk_matches_source
          ON supplier_nazk_check_matches(nazk_source_id);
        CREATE TABLE IF NOT EXISTS supplier_nazk_check_documents (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          check_id INTEGER NOT NULL REFERENCES supplier_nazk_checks(id) ON DELETE CASCADE,
          document_type TEXT NOT NULL,
          document_date TEXT,
          document_number TEXT,
          title TEXT DEFAULT '',
          url TEXT DEFAULT '',
          source TEXT DEFAULT '',
          submission_id TEXT REFERENCES submissions(id),
          prozorro_document_id TEXT,
          created_at TEXT NOT NULL,
          created_by TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_supplier_nazk_documents_check
          ON supplier_nazk_check_documents(check_id,created_at);
        CREATE TABLE IF NOT EXISTS supplier_nazk_check_requests (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          check_id INTEGER NOT NULL REFERENCES supplier_nazk_checks(id) ON DELETE CASCADE,
          request_type TEXT,
          request_date TEXT,
          request_number TEXT,
          request_document_url TEXT DEFAULT '',
          request_status TEXT NOT NULL DEFAULT 'prepared',
          response_date TEXT,
          created_at TEXT NOT NULL,
          created_by TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          updated_by TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_supplier_nazk_requests_check
          ON supplier_nazk_check_requests(check_id,created_at);
        CREATE TABLE IF NOT EXISTS supplier_nazk_check_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          check_id INTEGER NOT NULL REFERENCES supplier_nazk_checks(id) ON DELETE CASCADE,
          event_type TEXT NOT NULL,
          event_at TEXT NOT NULL,
          event_by TEXT NOT NULL,
          old_workflow_status TEXT,
          new_workflow_status TEXT,
          old_result TEXT,
          new_result TEXT,
          details_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS ix_supplier_nazk_events_check
          ON supplier_nazk_check_events(check_id,event_at,id);
        CREATE TABLE IF NOT EXISTS submission_nazk_controls (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          submission_id TEXT NOT NULL UNIQUE REFERENCES submissions(id),
          supplier_code TEXT NOT NULL,
          manager_id INTEGER REFERENCES supplier_managers(id),
          manager_name TEXT DEFAULT '',
          nazk_certificate_required INTEGER NOT NULL DEFAULT 0,
          nazk_certificate_checked INTEGER NOT NULL DEFAULT 0,
          selected_document_id TEXT,
          selected_document_url TEXT,
          supplier_nazk_check_id INTEGER REFERENCES supplier_nazk_checks(id),
          checked_at TEXT,
          checked_by TEXT,
          comment TEXT DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_submission_nazk_controls_supplier
          ON submission_nazk_controls(supplier_code);
        CREATE INDEX IF NOT EXISTS ix_submission_nazk_controls_manager
          ON submission_nazk_controls(manager_id);
        CREATE INDEX IF NOT EXISTS ix_submission_nazk_controls_required
          ON submission_nazk_controls(nazk_certificate_required);
        CREATE INDEX IF NOT EXISTS ix_submission_nazk_controls_checked
          ON submission_nazk_controls(nazk_certificate_checked);
        CREATE TABLE IF NOT EXISTS application_fields (
          submission_id TEXT PRIMARY KEY REFERENCES submissions(id),
          protocol_number TEXT DEFAULT '', protocol_date TEXT DEFAULT '',
          publication_date TEXT DEFAULT '', protocol_officer TEXT DEFAULT '',
          protocol_remarks TEXT DEFAULT '', protocol_decision TEXT DEFAULT '', marketplace_decision TEXT DEFAULT '',
          compliance_status TEXT DEFAULT '', compliance_comments TEXT DEFAULT '',
          manager_name TEXT DEFAULT '', manager_name_source TEXT DEFAULT '', manager_name_source_submission_id TEXT DEFAULT '',
          document_package TEXT DEFAULT '', contract_details TEXT DEFAULT '', authority_review TEXT DEFAULT '', mvs_seal_review TEXT DEFAULT '',
          document_check_status TEXT DEFAULT '', document_check_summary TEXT DEFAULT '',
          document_checked_at TEXT DEFAULT '', document_check_result_json TEXT DEFAULT '',
          generated_protocol_number TEXT DEFAULT '', generated_protocol_date TEXT DEFAULT '',
          generated_protocol_decision TEXT DEFAULT '', protocol_generated_at TEXT DEFAULT '',
          notes TEXT DEFAULT '', review_officer TEXT DEFAULT '', updated_at TEXT, updated_by TEXT
        );
        CREATE TABLE IF NOT EXISTS framework_officers (
          framework_id TEXT PRIMARY KEY REFERENCES frameworks(id),
          officer TEXT NOT NULL, marketplace_url TEXT DEFAULT '', category TEXT DEFAULT '',
          source TEXT DEFAULT 'Оголошення', synced_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS framework_service_directory (
          pretty_id TEXT PRIMARY KEY,
          framework_id TEXT REFERENCES frameworks(id),
          dk_code TEXT DEFAULT '', category TEXT DEFAULT '', marketplace_url TEXT DEFAULT '',
          responsible_officer TEXT DEFAULT '', source_title TEXT DEFAULT '',
          source TEXT DEFAULT 'Google Sheets: Оголошення', synced_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_framework_service_directory_framework
          ON framework_service_directory(framework_id);
        CREATE TABLE IF NOT EXISTS authorized_officers (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          full_name TEXT NOT NULL UNIQUE,
          role TEXT NOT NULL DEFAULT 'УО',
          active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_authorized_officers_active
          ON authorized_officers(active,full_name);
        CREATE TABLE IF NOT EXISTS auth_users (
          username TEXT PRIMARY KEY,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('admin','officer','viewer')),
          officer_id INTEGER REFERENCES authorized_officers(id),
          active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, created_by TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ix_auth_users_officer
          ON auth_users(officer_id) WHERE officer_id IS NOT NULL AND active=1;
        CREATE TABLE IF NOT EXISTS audit_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT, submission_id TEXT, changed_at TEXT NOT NULL,
          changed_by TEXT NOT NULL, field_name TEXT NOT NULL, old_value TEXT, new_value TEXT
        );
        CREATE TABLE IF NOT EXISTS application_contracts (
          submission_id TEXT PRIMARY KEY REFERENCES submissions(id), supplier_code TEXT DEFAULT '',
          contract_number TEXT DEFAULT '', contract_date TEXT DEFAULT '', amount TEXT DEFAULT '',
          buyer_code TEXT DEFAULT '', fingerprint TEXT DEFAULT '', updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_application_contracts_lookup
          ON application_contracts(supplier_code,contract_number);
        CREATE TABLE IF NOT EXISTS violation_reports (
          id TEXT PRIMARY KEY, report_id TEXT DEFAULT '', status TEXT DEFAULT '',
          date_created TEXT DEFAULT '', date_published TEXT DEFAULT '', date_modified TEXT DEFAULT '',
          tender_id TEXT DEFAULT '', tender_pretty_id TEXT DEFAULT '', contract_id TEXT DEFAULT '', contract_pretty_id TEXT DEFAULT '',
          author_name TEXT DEFAULT '', author_code TEXT DEFAULT '', defendant_name TEXT DEFAULT '', defendant_code TEXT DEFAULT '',
          authority_name TEXT DEFAULT '', authority_code TEXT DEFAULT '', reason TEXT DEFAULT '', description TEXT DEFAULT '',
          defendant_period_start TEXT DEFAULT '', defendant_period_end TEXT DEFAULT '',
          decision_resolution TEXT DEFAULT '', decision_description TEXT DEFAULT '', decision_date TEXT DEFAULT '',
          evidence_documents_json TEXT NOT NULL DEFAULT '[]', decision_documents_json TEXT NOT NULL DEFAULT '[]',
          raw_json TEXT NOT NULL, synced_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_violation_reports_report_id ON violation_reports(report_id);
        CREATE INDEX IF NOT EXISTS ix_violation_reports_defendant ON violation_reports(defendant_code);
        CREATE INDEX IF NOT EXISTS ix_violation_reports_status ON violation_reports(status);
        CREATE INDEX IF NOT EXISTS ix_violation_reports_date ON violation_reports(date_published);
        CREATE TABLE IF NOT EXISTS violation_report_reviews (
          report_id TEXT PRIMARY KEY REFERENCES violation_reports(id) ON DELETE CASCADE,
          review_status TEXT DEFAULT 'not_reviewed', assigned_officer TEXT DEFAULT '',
          internal_decision TEXT DEFAULT '', decision_justification TEXT DEFAULT '', review_notes TEXT DEFAULT '', protocol_number TEXT DEFAULT '',
          protocol_date TEXT DEFAULT '', reviewed_at TEXT DEFAULT '', updated_at TEXT NOT NULL, updated_by TEXT DEFAULT 'УО'
        );
        CREATE TABLE IF NOT EXISTS violation_report_document_reviews (
          report_id TEXT NOT NULL REFERENCES violation_reports(id) ON DELETE CASCADE,
          document_source TEXT NOT NULL CHECK(document_source IN ('customer','supplier')),
          document_id TEXT NOT NULL,
          original_title TEXT NOT NULL DEFAULT '',
          original_url TEXT NOT NULL DEFAULT '',
          file_unavailable INTEGER NOT NULL DEFAULT 0 CHECK(file_unavailable IN (0,1)),
          checked_at TEXT NOT NULL,
          checked_by TEXT NOT NULL DEFAULT '',
          PRIMARY KEY(report_id,document_source,document_id)
        );
        CREATE INDEX IF NOT EXISTS ix_violation_document_reviews_report
          ON violation_report_document_reviews(report_id,document_source);
        CREATE TABLE IF NOT EXISTS remarks_catalog (
          id INTEGER PRIMARY KEY AUTOINCREMENT, point TEXT NOT NULL, text TEXT NOT NULL,
          tag TEXT DEFAULT '', category TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
          updated_at TEXT NOT NULL
        );
        """)
        violation_review_columns = {row[1] for row in con.execute("PRAGMA table_info(violation_report_reviews)")}
        if "decision_justification" not in violation_review_columns:
            con.execute("ALTER TABLE violation_report_reviews ADD COLUMN decision_justification TEXT DEFAULT ''")
        if con.execute("SELECT COUNT(*) FROM remarks_catalog").fetchone()[0] == 0:
            con.executemany("INSERT INTO remarks_catalog(point,text,tag,category,active,updated_at) VALUES (?,?,?,?,1,?)",
                            [(point, text, tag, "", now_iso()) for point, text, tag in DEFAULT_REMARKS])
        for full_name, active in INITIAL_AUTHORIZED_OFFICERS:
            con.execute("""INSERT INTO authorized_officers(full_name,role,active,created_at,updated_at)
              VALUES (?,'УО',?,?,?) ON CONFLICT(full_name) DO NOTHING""",
              (full_name, active, now_iso(), now_iso()))
        application_columns = {row[1] for row in con.execute("PRAGMA table_info(application_fields)")}
        if "protocol_remarks" not in application_columns:
            con.execute("ALTER TABLE application_fields ADD COLUMN protocol_remarks TEXT DEFAULT ''")
        if "protocol_decision" not in application_columns:
            con.execute("ALTER TABLE application_fields ADD COLUMN protocol_decision TEXT DEFAULT ''")
        if "marketplace_decision" not in application_columns:
            con.execute("ALTER TABLE application_fields ADD COLUMN marketplace_decision TEXT DEFAULT ''")
        if "compliance_status" not in application_columns:
            con.execute("ALTER TABLE application_fields ADD COLUMN compliance_status TEXT DEFAULT ''")
        if "compliance_comments" not in application_columns:
            con.execute("ALTER TABLE application_fields ADD COLUMN compliance_comments TEXT DEFAULT ''")
        if "authority_review" not in application_columns:
            con.execute("ALTER TABLE application_fields ADD COLUMN authority_review TEXT DEFAULT ''")
        if "mvs_seal_review" not in application_columns:
            con.execute("ALTER TABLE application_fields ADD COLUMN mvs_seal_review TEXT DEFAULT ''")
        if "contract_details" not in application_columns:
            con.execute("ALTER TABLE application_fields ADD COLUMN contract_details TEXT DEFAULT ''")
        for field in ("manager_name_source", "manager_name_source_submission_id"):
            if field not in application_columns:
                con.execute(f"ALTER TABLE application_fields ADD COLUMN {field} TEXT DEFAULT ''")
        for field in ("document_check_status", "document_check_summary", "document_checked_at", "document_check_result_json"):
            if field not in application_columns:
                con.execute(f"ALTER TABLE application_fields ADD COLUMN {field} TEXT DEFAULT ''")
        for field in ("generated_protocol_number", "generated_protocol_date", "generated_protocol_decision", "protocol_generated_at"):
            if field not in application_columns:
                con.execute(f"ALTER TABLE application_fields ADD COLUMN {field} TEXT DEFAULT ''")
        if "review_officer" not in application_columns:
            con.execute("ALTER TABLE application_fields ADD COLUMN review_officer TEXT DEFAULT ''")
        officer_columns = {row[1] for row in con.execute("PRAGMA table_info(framework_officers)")}
        if "marketplace_url" not in officer_columns:
            con.execute("ALTER TABLE framework_officers ADD COLUMN marketplace_url TEXT DEFAULT ''")
        if "category" not in officer_columns:
            con.execute("ALTER TABLE framework_officers ADD COLUMN category TEXT DEFAULT ''")
        violation_columns = {row[1] for row in con.execute("PRAGMA table_info(violation_reports)")}
        if "authority_code" not in violation_columns:
            con.execute("ALTER TABLE violation_reports ADD COLUMN authority_code TEXT DEFAULT ''")
        for row in con.execute("SELECT id,raw_json FROM violation_reports WHERE authority_code='' OR authority_code IS NULL").fetchall():
            try:
                authority_code = str((((json.loads(row[1] or "{}").get("authority") or {}).get("identifier") or {}).get("id") or ""))
                con.execute("UPDATE violation_reports SET authority_code=? WHERE id=?", (authority_code, row[0]))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        review_columns = {row[1] for row in con.execute("PRAGMA table_info(violation_report_reviews)")}
        review_additions = {
            "contract_deadline_extended": "INTEGER NOT NULL DEFAULT 0",
            "written_refusal_date": "TEXT DEFAULT ''",
            "written_refusal_number": "TEXT DEFAULT ''",
            "written_refusal_url": "TEXT DEFAULT ''",
            "court_decision_final_present": "INTEGER",
            "customer_verified_full_name": "TEXT DEFAULT ''",
            "customer_verified_short_name": "TEXT DEFAULT ''",
            "actual_contract_date": "TEXT DEFAULT ''",
            "actual_contract_number": "TEXT DEFAULT ''",
            "actual_contract_url": "TEXT DEFAULT ''",
            "assigned_officer_id": "INTEGER REFERENCES authorized_officers(id)",
            "additional_check_required": "INTEGER NOT NULL DEFAULT 0",
            "guarantee_documents_visible": "INTEGER",
            "supplier_explanation_assessment": "TEXT NOT NULL DEFAULT ''",
            "established_discrepancy": "TEXT NOT NULL DEFAULT ''",
            "decision_template_key": "TEXT NOT NULL DEFAULT ''",
            "justification_source_hash": "TEXT NOT NULL DEFAULT ''",
            "justification_generated_at": "TEXT NOT NULL DEFAULT ''",
            "justification_manually_edited": "INTEGER NOT NULL DEFAULT 0",
            "customer_protocol_decision_date": "TEXT DEFAULT ''",
            "customer_protocol_decision_number": "TEXT DEFAULT ''",
            "customer_protocol_decision_url": "TEXT DEFAULT ''",
            "generated_protocol_filename": "TEXT DEFAULT ''",
            "protocol_generated_at": "TEXT DEFAULT ''",
            "completed_at": "TEXT DEFAULT ''",
            "completed_by": "TEXT DEFAULT ''",
        }
        for field, definition in review_additions.items():
            if field not in review_columns:
                con.execute(f"ALTER TABLE violation_report_reviews ADD COLUMN {field} {definition}")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS violation_report_review_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          report_id TEXT NOT NULL REFERENCES violation_reports(id) ON DELETE CASCADE,
          event_type TEXT NOT NULL,
          field_name TEXT NOT NULL DEFAULT '',
          old_value TEXT,
          new_value TEXT,
          changed_at TEXT NOT NULL,
          changed_by TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS ix_violation_review_events_report
          ON violation_report_review_events(report_id,changed_at);
        """)
        nazk_document_columns = {row[1] for row in con.execute("PRAGMA table_info(supplier_nazk_check_documents)")}
        if "submission_id" not in nazk_document_columns:
            con.execute("ALTER TABLE supplier_nazk_check_documents ADD COLUMN submission_id TEXT REFERENCES submissions(id)")
        if "prozorro_document_id" not in nazk_document_columns:
            con.execute("ALTER TABLE supplier_nazk_check_documents ADD COLUMN prozorro_document_id TEXT")
        con.execute("CREATE INDEX IF NOT EXISTS ix_supplier_nazk_documents_submission ON supplier_nazk_check_documents(submission_id)")


def api_get(url: str) -> dict:
    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PQM/0.1"})
            with urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context()) as res:
                return json.load(res)
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1 + attempt * 2)
    raise last_error


def paginated_pages(base: str, offset: str | None = None):
    url = f"{base}?offset={urllib.parse.quote(offset, safe='')}" if offset else base
    seen = set()
    while True:
        payload = api_get(url)
        batch = payload.get("data", [])
        yield batch
        offset = payload.get("next_page", {}).get("offset")
        if not offset or offset in seen or len(batch) < 100:
            break
        seen.add(offset)
        url = f"{base}?offset={urllib.parse.quote(offset, safe='')}"


def scoped_pages(framework_id: str, resource: str, offset: str | None = None):
    yield from paginated_pages(f"{API_ROOT}/frameworks/{framework_id}/{resource}", offset)


def resource_cursor(framework_id: str, table: str) -> str | None:
    where = "framework_id=?"
    with db() as con:
        rows = con.execute(f"SELECT id,raw_json FROM {table} WHERE {where}", (framework_id,)).fetchall()
    latest = None
    for row in rows:
        try:
            item = json.loads(row["raw_json"] or "{}")
            value = item.get("dateModified") or item.get("datePublished") or item.get("date")
            moment = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
            key = (moment.timestamp(), row["id"])
            if latest is None or key > latest:
                latest = key
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    if latest is None:
        return None
    seconds = f"{latest[0]:.3f}".rstrip("0").rstrip(".")
    digest = hashlib.md5(latest[1].encode()).hexdigest()
    return f"{seconds}.1.{digest}"


def save_framework(item: dict) -> bool:
    organizer = str(item.get("procuringEntity", {}).get("identifier", {}).get("id", ""))
    if organizer != ORGANIZER_EDRPOU:
        return False
    with db() as con:
        con.execute("""INSERT INTO frameworks
          (id,pretty_id,title,dk_code,status,organizer_edrpou,agreement_id,date_modified,raw_json,synced_at)
          VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
          pretty_id=excluded.pretty_id,title=excluded.title,dk_code=excluded.dk_code,
          status=excluded.status,agreement_id=excluded.agreement_id,date_modified=excluded.date_modified,
          raw_json=excluded.raw_json,synced_at=excluded.synced_at""",
          (item["id"], item.get("prettyID", ""), item.get("title", ""),
           item.get("classification", {}).get("id", ""), item.get("status", ""), organizer,
           item.get("agreementID", ""), item.get("dateModified", ""),
           json.dumps(item, ensure_ascii=False), now_iso()))
    return True


def effective_framework_status(status: str, raw: dict | None = None) -> str:
    """Return the operational framework status from Prozorro metadata, never from Bids."""
    official = str(status or "").strip().casefold()
    if official == "complete":
        return "closed"
    if official == "active":
        valid_until = str((((raw or {}).get("qualificationPeriod") or {}).get("endDate") or ""))[:10]
        if valid_until and valid_until < datetime.now().date().isoformat():
            return "closed"
        return "active"
    return official


def refresh_framework_metadata() -> dict:
    """Refresh official framework fields without loading submissions or registry contracts."""
    frameworks = discover_tracked_frameworks()
    updated = 0
    for index, framework in enumerate(frameworks, 1):
        SYNC_STATE["message"] = f"Оновлення відборів з Prozorro {index}/{len(frameworks)}"
        if save_framework(framework):
            updated += 1
    return {"frameworks": len(frameworks), "updated": updated}


def refresh_framework_metadata_worker() -> None:
    started = datetime.now(timezone.utc)
    SYNC_STATE.update(running=True, mode="framework_metadata", started_at=started.isoformat(),
                      message="Отримання актуальних відборів із Prozorro…")
    try:
        result = refresh_framework_metadata()
        SYNC_STATE["message"] = f"Відбори оновлено з Prozorro: {result['updated']}/{result['frameworks']}"
    except Exception as exc:
        SYNC_STATE["message"] = f"Помилка оновлення відборів: {exc}"
    finally:
        SYNC_STATE.update(running=False, updated_at=now_iso(),
                          duration_seconds=round((datetime.now(timezone.utc) - started).total_seconds(), 1))


def sync_one_framework(framework_id: str, framework: dict | None = None, incremental: bool = False) -> dict:
    framework = framework or api_get(f"{API_ROOT}/frameworks/{framework_id}")["data"]
    if not save_framework(framework):
        raise ValueError("Відбір не належить організатору 40996564")
    submission_count = qualification_count = contract_count = 0
    with db() as con:
        submissions_cursor = resource_cursor(framework_id, "submissions") if incremental else None
        for batch in scoped_pages(framework_id, "submissions", submissions_cursor):
            for item in batch:
                tenderer = (item.get("tenderers") or [{}])[0]
                con.execute("""INSERT INTO submissions
                  (id,framework_id,supplier_name,supplier_code,date_published,status,qualification_id,
                   documents_json,raw_json,synced_at) VALUES (?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(id) DO UPDATE SET supplier_name=excluded.supplier_name,
                  supplier_code=excluded.supplier_code,date_published=excluded.date_published,
                  status=excluded.status,qualification_id=excluded.qualification_id,
                  documents_json=excluded.documents_json,raw_json=excluded.raw_json,synced_at=excluded.synced_at""",
                  (item["id"], framework_id, tenderer.get("name") or tenderer.get("identifier", {}).get("legalName", ""),
                   tenderer.get("identifier", {}).get("id", ""), item.get("datePublished") or item.get("date", ""),
                   item.get("status", ""), item.get("qualificationID", ""),
                   json.dumps(item.get("documents", []), ensure_ascii=False), json.dumps(item, ensure_ascii=False), now_iso()))
                application_cursor = con.execute(
                    "INSERT OR IGNORE INTO application_fields(submission_id) VALUES (?)", (item["id"],)
                )
                if application_cursor.rowcount:
                    assignment = con.execute("""SELECT responsible_officer FROM framework_service_directory
                      WHERE framework_id=? AND COALESCE(responsible_officer,'')<>'' LIMIT 1""",
                      (framework_id,)).fetchone()
                    if assignment:
                        con.execute("""UPDATE application_fields SET protocol_officer=?,updated_at=?,updated_by=?
                          WHERE submission_id=? AND COALESCE(protocol_officer,'')=''""",
                          (assignment[0], now_iso(), "PQM default from framework", item["id"]))
                previous_manager = con.execute("""SELECT af.manager_name,s.id
                  FROM submissions s JOIN application_fields af ON af.submission_id=s.id
                  WHERE s.supplier_code=? AND s.id<>? AND COALESCE(af.manager_name,'')<>''
                    AND COALESCE(s.date_published,'') < ?
                  ORDER BY s.date_published DESC,s.id DESC LIMIT 1""",
                  (tenderer.get("identifier", {}).get("id", ""), item["id"], item.get("datePublished") or item.get("date", ""))).fetchone()
                if previous_manager:
                    con.execute("""UPDATE application_fields SET manager_name=?,manager_name_source='previous_application',
                      manager_name_source_submission_id=?,updated_at=?,updated_by='PQM auto-fill'
                      WHERE submission_id=? AND COALESCE(manager_name,'')='' AND COALESCE(manager_name_source,'')<>'manual'""",
                      (previous_manager[0], previous_manager[1], now_iso(), item["id"]))
                else:
                    supplier_code = tenderer.get("identifier", {}).get("id", "")
                    submission_day = str(item.get("datePublished") or item.get("date") or "")[:10]
                    trusted_manager = con.execute("""SELECT manager_name,'edr_profile' source,'' source_submission_id
                      FROM supplier_edr_profiles WHERE DIGITS(supplier_code)=DIGITS(?)
                        AND COALESCE(manager_name,'')<>''
                        AND (?='' OR COALESCE(SUBSTR(edr_checked_at,1,10),'')='' OR SUBSTR(edr_checked_at,1,10)<=?)
                      UNION ALL
                      SELECT manager_name,'supplier_manager' source,'' source_submission_id
                      FROM supplier_managers WHERE DIGITS(supplier_code)=DIGITS(?) AND is_current=1
                        AND COALESCE(manager_name,'')<>''
                        AND (?='' OR COALESCE(SUBSTR(valid_from,1,10),'')='' OR SUBSTR(valid_from,1,10)<=?)
                      LIMIT 1""", (supplier_code, submission_day, submission_day,
                                    supplier_code, submission_day, submission_day)).fetchone()
                    if trusted_manager:
                        con.execute("""UPDATE application_fields SET manager_name=?,manager_name_source=?,
                          manager_name_source_submission_id=?,updated_at=?,updated_by='PQM auto-fill'
                          WHERE submission_id=? AND COALESCE(manager_name,'')=''
                            AND COALESCE(manager_name_source,'')<>'manual'""",
                          (trusted_manager[0], trusted_manager[1], trusted_manager[2], now_iso(), item["id"]))
                # Existing submissions must also be reconciled: their manager/profile
                # can become known after the submission was first synchronized.
                ensure_submission_nazk_control(con, item["id"])
                submission_count += 1
        latest_manager_by_supplier = {}
        manager_rows = con.execute("""SELECT s.id,s.supplier_code,s.date_published,
          COALESCE(af.manager_name,''),COALESCE(af.manager_name_source,'')
          FROM submissions s JOIN application_fields af ON af.submission_id=s.id
          ORDER BY s.supplier_code,s.date_published,s.id""").fetchall()
        for submission_id, supplier_code, _, manager_name, manager_source in manager_rows:
            if not supplier_code:
                continue
            if manager_name:
                latest_manager_by_supplier[supplier_code] = (manager_name, submission_id)
            elif manager_source != "manual" and supplier_code in latest_manager_by_supplier:
                inherited_name, source_submission_id = latest_manager_by_supplier[supplier_code]
                con.execute("""UPDATE application_fields SET manager_name=?,manager_name_source='previous_application',
                  manager_name_source_submission_id=?,updated_at=?,updated_by='PQM auto-fill' WHERE submission_id=?""",
                  (inherited_name, source_submission_id, now_iso(), submission_id))
                latest_manager_by_supplier[supplier_code] = (inherited_name, submission_id)
        qualifications_cursor = resource_cursor(framework_id, "qualifications") if incremental else None
        for batch in scoped_pages(framework_id, "qualifications", qualifications_cursor):
            for item in batch:
                con.execute("""INSERT INTO qualifications
                  (id,framework_id,submission_id,status,decision_date,documents_json,raw_json,synced_at)
                  VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                  submission_id=excluded.submission_id,status=excluded.status,
                  decision_date=excluded.decision_date,documents_json=excluded.documents_json,
                  raw_json=excluded.raw_json,synced_at=excluded.synced_at""",
                  (item["id"], framework_id, item.get("submissionID", ""), item.get("status", ""),
                   item.get("dateModified") or item.get("date", ""),
                   json.dumps(item.get("documents", []), ensure_ascii=False), json.dumps(item, ensure_ascii=False), now_iso()))
                qualification_count += 1
        agreement_id = framework.get("agreementID", "")
        if agreement_id:
            contracts_cursor = resource_cursor(framework_id, "registry_contracts") if incremental else None
            for batch in paginated_pages(f"{API_ROOT}/agreements/{agreement_id}/contracts", contracts_cursor):
                for item in batch:
                    supplier = (item.get("suppliers") or [{}])[0]
                    con.execute("""INSERT INTO registry_contracts
                      (id,framework_id,qualification_id,supplier_code,status,milestones_json,raw_json,synced_at)
                      VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                      framework_id=excluded.framework_id,qualification_id=excluded.qualification_id,
                      supplier_code=excluded.supplier_code,status=excluded.status,
                      milestones_json=excluded.milestones_json,raw_json=excluded.raw_json,
                      synced_at=excluded.synced_at""",
                      (item["id"], framework_id, item.get("qualificationID", ""),
                       supplier.get("identifier", {}).get("id", ""), item.get("status", ""),
                       json.dumps(item.get("milestones", []), ensure_ascii=False),
                       json.dumps(item, ensure_ascii=False), now_iso()))
                    contract_count += 1
    return {"framework": framework.get("prettyID"), "submissions": submission_count, "qualifications": qualification_count, "contracts": contract_count}


def discover_active_frameworks() -> list[dict]:
    framework_ids = [
        item["id"]
        for batch in paginated_pages(f"{API_ROOT}/frameworks")
        for item in batch
    ]
    active = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {
            pool.submit(api_get, f"{API_ROOT}/frameworks/{framework_id}"): framework_id
            for framework_id in framework_ids
        }
        for future in as_completed(futures):
            item = future.result()["data"]
            organizer = str(item.get("procuringEntity", {}).get("identifier", {}).get("id", ""))
            if organizer == ORGANIZER_EDRPOU and item.get("status") == "active":
                active.append(item)
    return sorted(active, key=lambda item: item.get("prettyID", ""))


def discover_tracked_frameworks() -> list[dict]:
    """Load every active and closed PQM category listed in the announcements directory."""
    rows = load_announcement_rows()
    tracked_pretty_ids = sorted({
        (row.get("ID") or "").strip()
        for row in rows
        if (row.get("ID") or "").strip()
        and (row.get("status") or "").strip().casefold() in {"активне", "закрите"}
    })
    framework_ids = [
        item["id"]
        for batch in paginated_pages(f"{API_ROOT}/frameworks")
        for item in batch
    ]
    tracked = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {
            pool.submit(api_get, f"{API_ROOT}/frameworks/{framework_id}"): framework_id
            for framework_id in framework_ids
        }
        for future in as_completed(futures):
            try:
                item = future.result()["data"]
            except Exception as exc:
                framework_id = futures[future]
                raise RuntimeError(f"Не вдалося отримати відбір {framework_id}: {exc}") from exc
            organizer = str(item.get("procuringEntity", {}).get("identifier", {}).get("id", ""))
            if organizer == ORGANIZER_EDRPOU and item.get("prettyID") in tracked_pretty_ids:
                tracked.append(item)
    found_pretty_ids = {item.get("prettyID") for item in tracked}
    missing = sorted(set(tracked_pretty_ids) - found_pretty_ids)
    if missing:
        raise RuntimeError(f"API Prozorro не повернув {len(missing)} відборів із довідника: {', '.join(missing[:5])}")
    return sorted(tracked, key=lambda item: item.get("prettyID", ""))


def sync_all_active_frameworks() -> dict:
    frameworks = discover_active_frameworks()
    totals = {"frameworks": len(frameworks), "completed": 0, "submissions": 0, "qualifications": 0, "contracts": 0, "errors": []}
    for index, framework in enumerate(frameworks, 1):
        pretty_id = framework.get("prettyID") or framework["id"]
        SYNC_STATE["message"] = f"{index}/{len(frameworks)}: {pretty_id}"
        try:
            result = sync_one_framework(framework["id"], framework)
            totals["completed"] += 1
            for key in ("submissions", "qualifications", "contracts"):
                totals[key] += result[key]
        except Exception as exc:
            totals["errors"].append({"framework": pretty_id, "error": str(exc)})
    try:
        totals["officer_assignments"] = sync_framework_officers()["matched"]
    except Exception as exc:
        totals["officer_assignments_error"] = str(exc)
    totals["supplier_registry"] = refresh_supplier_registry_summary()
    return totals


def sync_all_tracked_frameworks() -> dict:
    frameworks = discover_tracked_frameworks()
    with db() as con:
        known_ids = {row[0] for row in con.execute("SELECT id FROM frameworks")}
    totals = {"frameworks": len(frameworks), "completed": 0, "new_frameworks": 0,
              "submissions": 0, "qualifications": 0, "contracts": 0, "errors": []}
    for index, framework in enumerate(frameworks, 1):
        pretty_id = framework.get("prettyID") or framework["id"]
        is_new = framework["id"] not in known_ids
        SYNC_STATE["message"] = f"{index}/{len(frameworks)}: {pretty_id}"
        try:
            # Existing categories need only changes after their stored cursor.
            # A new historical category has no cursor, so the same path loads it fully.
            result = sync_one_framework(framework["id"], framework, incremental=True)
            totals["completed"] += 1
            if is_new:
                totals["new_frameworks"] += 1
            for key in ("submissions", "qualifications", "contracts"):
                totals[key] += result[key]
        except Exception as exc:
            totals["errors"].append({"framework": pretty_id, "error": str(exc)})
    try:
        totals["officer_assignments"] = sync_framework_officers()["matched"]
    except Exception as exc:
        totals["officer_assignments_error"] = str(exc)
    totals["supplier_registry"] = refresh_supplier_registry_summary()
    return totals


def sync_incremental_active_frameworks() -> dict:
    with db() as con:
        framework_ids = [row[0] for row in con.execute("SELECT id FROM frameworks WHERE status='active' ORDER BY pretty_id")]
    totals = {"frameworks": len(framework_ids), "completed": 0, "submissions": 0,
              "qualifications": 0, "contracts": 0, "errors": []}
    for index, framework_id in enumerate(framework_ids, 1):
        SYNC_STATE["message"] = f"Інкрементальне оновлення {index}/{len(framework_ids)}"
        try:
            framework = api_get(f"{API_ROOT}/frameworks/{framework_id}")["data"]
            result = sync_one_framework(framework_id, framework, incremental=True)
            totals["completed"] += 1
            for key in ("submissions", "qualifications", "contracts"):
                totals[key] += result[key]
        except Exception as exc:
            totals["errors"].append({"framework": framework_id, "error": str(exc)})
    try:
        totals["officer_assignments"] = sync_framework_officers()["matched"]
    except Exception as exc:
        totals["officer_assignments_error"] = str(exc)
    totals["supplier_registry"] = refresh_supplier_registry_summary()
    return totals


def sync_worker(framework_id: str) -> None:
    SYNC_STATE.update(running=True, message="Синхронізація триває…")
    try:
        result = sync_one_framework(framework_id)
        sync_framework_officers()
        SYNC_STATE["message"] = f"{result['framework']}: {result['submissions']} заявок, {result['qualifications']} рішень, {result['contracts']} записів реєстру"
    except Exception as exc:
        SYNC_STATE["message"] = f"Помилка: {exc}"
    finally:
        SYNC_STATE.update(running=False, updated_at=now_iso())


def sync_all_worker() -> None:
    started = datetime.now(timezone.utc)
    SYNC_STATE.update(running=True, mode="full", started_at=started.isoformat(), message="Пошук активних і закритих відборів…")
    try:
        result = sync_all_tracked_frameworks()
        SYNC_STATE["message"] = (
            f"Оновлено {result['completed']}/{result['frameworks']} відборів "
            f"(нових історичних: {result['new_frameworks']}): "
            f"{result['submissions']} заявок, {result['qualifications']} рішень, "
            f"{result['contracts']} записів реєстру; помилок: {len(result['errors'])}"
        )
    except Exception as exc:
        SYNC_STATE["message"] = f"Помилка: {exc}"
    finally:
        SYNC_STATE.update(running=False, updated_at=now_iso(), duration_seconds=round((datetime.now(timezone.utc) - started).total_seconds(), 1))


def sync_incremental_worker() -> None:
    started = datetime.now(timezone.utc)
    SYNC_STATE.update(running=True, mode="incremental", started_at=started.isoformat(), message="Підготовка щогодинного оновлення…")
    try:
        result = sync_incremental_active_frameworks()
        SYNC_STATE["message"] = (
            f"Щогодинне оновлення: {result['completed']}/{result['frameworks']} відборів; "
            f"отримано {result['submissions']} заявок, {result['qualifications']} рішень, "
            f"{result['contracts']} записів реєстру; помилок: {len(result['errors'])}"
        )
    except Exception as exc:
        SYNC_STATE["message"] = f"Помилка щогодинного оновлення: {exc}"
    finally:
        SYNC_STATE.update(running=False, updated_at=now_iso(), duration_seconds=round((datetime.now(timezone.utc) - started).total_seconds(), 1))


def start_prozorro_sync(target, *, mode: str, message: str, args: tuple = ()) -> bool:
    """Atomically claim the single Prozorro sync slot before starting a worker."""
    with SYNC_STATE_LOCK:
        if SYNC_STATE.get("running"):
            return False
        SYNC_STATE.update(running=True, mode=mode, started_at=now_iso(), message=message)
    try:
        threading.Thread(target=target, args=args, daemon=True).start()
    except Exception:
        with SYNC_STATE_LOCK:
            SYNC_STATE.update(running=False, message="Не вдалося запустити синхронізацію", updated_at=now_iso())
        raise
    return True


def next_hourly_run(moment: datetime | None = None) -> datetime:
    current = moment or datetime.now().astimezone()
    candidate = current.replace(minute=5, second=0, microsecond=0)
    if candidate <= current:
        candidate = candidate.replace(hour=(candidate.hour + 1) % 24)
        if candidate.hour == 0:
            candidate = candidate.replace(day=candidate.day) + timedelta(days=1)
    return candidate


def hourly_sync_scheduler() -> None:
    # Run a missed update shortly after startup, then every hour at :05 local time.
    SYNC_STATE["next_run_at"] = next_hourly_run().isoformat()
    time.sleep(10)
    with db() as con:
        last_value = con.execute("SELECT MAX(synced_at) FROM submissions").fetchone()[0]
    try:
        last_sync = datetime.fromisoformat((last_value or "").replace("Z", "+00:00"))
    except ValueError:
        last_sync = None
    if last_value and not SYNC_STATE["updated_at"]:
        SYNC_STATE["updated_at"] = last_value
    if last_sync is None or (datetime.now(timezone.utc) - last_sync.astimezone(timezone.utc)).total_seconds() >= 3600:
        start_prozorro_sync(sync_incremental_worker, mode="incremental",
                            message="Підготовка щогодинного оновлення…")
    while True:
        target = next_hourly_run()
        SYNC_STATE["next_run_at"] = target.isoformat()
        while True:
            remaining = (target - datetime.now().astimezone()).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(30, remaining))
        start_prozorro_sync(sync_incremental_worker, mode="incremental",
                            message="Підготовка щогодинного оновлення…")


def decision_label(status: str | None) -> str:
    return {"active": "Допущено", "unsuccessful": "Відхилено", "pending": "Очікує рішення"}.get(status or "", "Очікує рішення")


def registry_status_label(status: str | None) -> str:
    return {"active": "Активний", "terminated": "Неактивний", "suspended": "Призупинений"}.get(status or "", "")


def registry_details(milestones_json: str | None, status: str | None) -> dict:
    milestones = json.loads(milestones_json or "[]")
    activation = next((item for item in milestones if item.get("type") == "activation"), {})
    ban = next((item for item in milestones if item.get("type") == "ban"), {})
    documents = []
    seen = set()
    for milestone in milestones:
        source = milestone.get("documents") or []
        if isinstance(source, dict):
            source = [doc for versions in source.values() for doc in versions]
        for document in source:
            key = document.get("id") or document.get("url")
            if key not in seen:
                seen.add(key)
                documents.append(document)
    status_date = ""
    if status == "terminated":
        status_date = activation.get("dateModified", "")
    elif status == "suspended":
        status_date = ban.get("dateModified") or ban.get("dueDate", "")
    return {
        "registry_valid_until": activation.get("dueDate", ""),
        "registry_status_date": status_date,
        "registry_documents": documents,
    }


def multi_param(params: dict, key: str) -> list[str]:
    return [value.strip() for raw in params.get(key, []) for value in raw.split(",") if value.strip()]


def application_filter(params: dict) -> tuple[str, list]:
    search = params.get("search", [""])[0].strip()
    statuses = multi_param(params, "status")
    registry_statuses = multi_param(params, "registry_status")
    supplier_codes = multi_param(params, "supplier_codes")
    framework_ids = multi_param(params, "framework_id")
    dk_codes = multi_param(params, "dk_code")
    date_from = params.get("date_from", [""])[0].strip()
    date_to = params.get("date_to", [""])[0].strip()
    officer = params.get("officer", [""])[0].strip()
    category = params.get("category", [""])[0].strip()
    submission_id = params.get("submission_id", [""])[0].strip()
    protocol_decision = params.get("protocol_decision", [""])[0].strip()
    compliance_status = params.get("compliance_status", [""])[0].strip()
    where, args = ["1=1"], []
    if submission_id:
        where.append("s.id=?")
        args.append(submission_id)
    if protocol_decision in {"__empty__", "admit", "reject"}:
        where.append("COALESCE(af.protocol_decision,'')=?")
        args.append("" if protocol_decision == "__empty__" else protocol_decision)
    if compliance_status in {"__empty__", "approved", "rejected"}:
        where.append("COALESCE(af.compliance_status,'')=?")
        args.append("" if compliance_status == "__empty__" else compliance_status)
    if search:
        where.append("(INSTR(CASEFOLD(s.supplier_name), ?) > 0 OR INSTR(CASEFOLD(s.supplier_code), ?) > 0 OR INSTR(CASEFOLD(f.pretty_id), ?) > 0 OR INSTR(CASEFOLD(f.dk_code), ?) > 0 OR INSTR(CASEFOLD(f.title), ?) > 0 OR INSTR(CASEFOLD(af.manager_name), ?) > 0)")
        args.extend([search.casefold()] * 6)
    if supplier_codes:
        where.append(f"s.supplier_code IN ({','.join('?' for _ in supplier_codes)})")
        args.extend(supplier_codes)
    if framework_ids:
        where.append(f"s.framework_id IN ({','.join('?' for _ in framework_ids)})")
        args.extend(framework_ids)
    if dk_codes:
        where.append(f"f.dk_code IN ({','.join('?' for _ in dk_codes)})")
        args.extend(dk_codes)
    if date_from:
        where.append("SUBSTR(s.date_published,1,10)>=?")
        args.append(date_from)
    if date_to:
        where.append("SUBSTR(s.date_published,1,10)<=?")
        args.append(date_to)
    assigned_officer = "COALESCE(NULLIF(af.protocol_officer,''),NULLIF(fo.officer,''),'')"
    if officer == "__unassigned__":
        where.append(f"{assigned_officer}=''")
    elif officer:
        where.append(f"{assigned_officer}=?")
        args.append(officer)
    if category:
        where.append("COALESCE(fo.category,'')=?")
        args.append(category)
    status_codes = [{"Допущено": "active", "Відхилено": "unsuccessful", "Очікує рішення": "pending"}[value] for value in statuses if value in {"Допущено", "Відхилено", "Очікує рішення"}]
    if status_codes:
        where.append(f"COALESCE(q.status,'pending') IN ({','.join('?' for _ in status_codes)})")
        args.extend(status_codes)
    registry_status_codes = [{"Активний": "active", "Неактивний": "terminated", "Призупинений": "suspended"}[value] for value in registry_statuses if value in {"Активний", "Неактивний", "Призупинений"}]
    if registry_status_codes:
        where.append(f"EXISTS (SELECT 1 FROM registry_contracts rc WHERE rc.qualification_id=q.id AND rc.status IN ({','.join('?' for _ in registry_status_codes)}))")
        args.extend(registry_status_codes)
    return " AND ".join(where), args


def application_stats(params: dict) -> dict:
    clause, args = application_filter(params)
    officer_params = {key: value for key, value in params.items() if key != "officer"}
    officer_clause, officer_args = application_filter(officer_params)
    with db() as con:
        row = con.execute(f"""SELECT COUNT(*) applications,
          COUNT(DISTINCT NULLIF(s.supplier_code,'')) suppliers,
          SUM(CASE WHEN COALESCE(q.status,'pending')='pending' THEN 1 ELSE 0 END) pending,
          SUM(CASE WHEN q.status='active' THEN 1 ELSE 0 END) admitted,
          SUM(CASE WHEN q.status='unsuccessful' THEN 1 ELSE 0 END) rejected,
          SUM(CASE WHEN EXISTS (SELECT 1 FROM registry_contracts rc WHERE rc.qualification_id=q.id AND rc.status='active') THEN 1 ELSE 0 END) registry_active,
          SUM(CASE WHEN EXISTS (SELECT 1 FROM registry_contracts rc WHERE rc.qualification_id=q.id AND rc.status='terminated') THEN 1 ELSE 0 END) registry_inactive
          FROM submissions s JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN qualifications q ON q.id=s.qualification_id
          LEFT JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id WHERE {clause}""", args).fetchone()
        officers = con.execute(f"""SELECT COALESCE(NULLIF(af.protocol_officer,''),NULLIF(fo.officer,''),'Не визначено') officer, COUNT(*) applications
          FROM submissions s JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN qualifications q ON q.id=s.qualification_id
          LEFT JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id WHERE {officer_clause}
          GROUP BY COALESCE(NULLIF(af.protocol_officer,''),NULLIF(fo.officer,''),'Не визначено') ORDER BY applications DESC""", officer_args).fetchall()
    result = {key: (value or 0) for key, value in dict(row).items()}
    result["officers"] = [dict(item) for item in officers]
    return result


def list_applications(params: dict) -> dict:
    page = max(1, int(params.get("page", ["1"])[0] or 1))
    size = min(200, max(10, int(params.get("size", ["50"])[0] or 50)))
    sort_key = params.get("sort", ["receivedDate"])[0].strip()
    sort_direction = "ASC" if params.get("direction", ["desc"])[0].lower() == "asc" else "DESC"
    clause, args = application_filter(params)
    sort_expressions = {
        "participant": "CASEFOLD(s.supplier_name)",
        "edrpou": "s.supplier_code",
        "qualificationId": "f.pretty_id",
        "dkCode": "f.dk_code",
        "receivedDate": "s.date_published",
        "documents": "JSON_ARRAY_LENGTH(s.documents_json)",
        "protocolNumber": "af.protocol_number",
        "protocolDate": "af.protocol_date",
        "publicationDate": "af.publication_date",
        "protocolOfficer": "CASEFOLD(af.protocol_officer)",
        "protocolRemarks": "CASEFOLD(af.protocol_remarks)",
        "protocolDecision": "CASE af.protocol_decision WHEN '' THEN 1 WHEN 'admit' THEN 2 WHEN 'reject' THEN 3 ELSE 4 END",
        "marketplaceDecision": "CASE af.marketplace_decision WHEN '' THEN 1 WHEN 'admit' THEN 2 WHEN 'reject' THEN 3 ELSE 4 END",
        "complianceStatus": "CASE af.compliance_status WHEN '' THEN 1 WHEN 'approved' THEN 2 WHEN 'rejected' THEN 3 ELSE 4 END",
        "complianceComments": "CASEFOLD(af.compliance_comments)",
        "managerName": "CASEFOLD(af.manager_name)",
        "documentPackage": "CASEFOLD(af.document_package)",
        "contractDetails": "CASEFOLD(af.contract_details)",
        "decision": "CASE COALESCE(q.status,'pending') WHEN 'pending' THEN 1 WHEN 'active' THEN 2 WHEN 'unsuccessful' THEN 3 ELSE 4 END",
        "registryStatus": "(SELECT rc.status FROM registry_contracts rc WHERE rc.qualification_id=q.id ORDER BY rc.synced_at DESC LIMIT 1)",
        "registryValidUntil": "(SELECT JSON_EXTRACT(rc.milestones_json,'$[0].dueDate') FROM registry_contracts rc WHERE rc.qualification_id=q.id ORDER BY rc.synced_at DESC LIMIT 1)",
        "registryStatusDate": "(SELECT JSON_EXTRACT(rc.milestones_json,'$[0].dateModified') FROM registry_contracts rc WHERE rc.qualification_id=q.id ORDER BY rc.synced_at DESC LIMIT 1)",
        "notes": "CASEFOLD(af.notes)",
    }
    order_by = sort_expressions.get(sort_key, "s.date_published")
    with db() as con:
        total = con.execute(f"""SELECT COUNT(*) FROM submissions s JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN qualifications q ON q.id=s.qualification_id LEFT JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id WHERE {clause}""", args).fetchone()[0]
        records = [dict(row) for row in con.execute(f"""SELECT s.id,f.pretty_id,f.title framework_title,f.dk_code,f.status framework_status,
          s.supplier_name,s.supplier_code,s.date_published,s.documents_json,
          COALESCE(q.status,'pending') decision_status,q.documents_json decision_documents,
          (SELECT rc.status FROM registry_contracts rc WHERE rc.qualification_id=q.id ORDER BY rc.synced_at DESC LIMIT 1) registry_status,
          (SELECT rc.milestones_json FROM registry_contracts rc WHERE rc.qualification_id=q.id ORDER BY rc.synced_at DESC LIMIT 1) registry_milestones,
           af.protocol_number,af.protocol_date,af.publication_date,
           COALESCE(NULLIF(af.protocol_officer,''),NULLIF(fo.officer,''),'') protocol_officer,
           af.review_officer,
          af.protocol_remarks,af.protocol_decision,af.marketplace_decision,af.compliance_status,af.compliance_comments,
          af.generated_protocol_number,af.generated_protocol_date,af.generated_protocol_decision,af.protocol_generated_at,
          af.manager_name,af.manager_name_source,af.manager_name_source_submission_id,
          af.document_package,af.contract_details,af.authority_review,af.mvs_seal_review,
           af.document_check_status,af.document_check_summary,af.document_checked_at,af.document_check_result_json,af.notes,COALESCE(fo.marketplace_url,'') marketplace_url,
           COALESCE(fo.category,'') category
          ,snc.nazk_certificate_required,snc.nazk_certificate_checked,snc.id nazk_control_id,
          COALESCE(snc.manager_name,'') nazk_control_manager
          FROM submissions s JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN qualifications q ON q.id=s.qualification_id
          LEFT JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN submission_nazk_controls snc ON snc.submission_id=s.id
          LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id WHERE {clause}
          ORDER BY {order_by} {sort_direction}, s.id ASC LIMIT ? OFFSET ?""", (*args, size, (page - 1) * size)).fetchall()]
        supplier_codes = sorted({re.sub(r"\D", "", row.get("supplier_code") or "") for row in records
                                 if re.sub(r"\D", "", row.get("supplier_code") or "")})
        edr_profiles = {}
        if supplier_codes:
            placeholders = ",".join("?" for _ in supplier_codes)
            for profile in con.execute(
                f"""SELECT supplier_code,COALESCE(manager_name,'') manager_name,
                           COALESCE(edr_checked_at,'') edr_checked_at
                    FROM supplier_edr_profiles
                    WHERE DIGITS(supplier_code) IN ({placeholders})""",
                supplier_codes,
            ):
                edr_profiles[re.sub(r"\D", "", profile["supplier_code"] or "")] = profile
        for row in records:
            profile = edr_profiles.get(re.sub(r"\D", "", row.get("supplier_code") or ""))
            row["edr_fallback_manager"] = profile["manager_name"] if profile else ""
            row["edr_fallback_checked_at"] = profile["edr_checked_at"] if profile else ""
        amcu_codes = {re.sub(r"\D", "", row[0] or "") for row in con.execute(
            "SELECT DISTINCT offender_code FROM amcu_registry WHERE offender_code<>''"
        )}
        nazk_names = {" ".join(re.sub(r"[’'`\-]+", " ", (row[0] or "").casefold()).split()) for row in con.execute(
            "SELECT DISTINCT full_name FROM nazk_registry WHERE full_name<>''"
        )}
        nazk_reviews = {row[0]: dict(row) for row in con.execute("SELECT * FROM supplier_nazk_reviews")}
        submission_nazk_states = get_submission_nazk_states(
            con, [row["id"] for row in records], nazk_names
        )
    items = []
    for row in records:
        item = dict(row); item["decision"] = decision_label(item.pop("decision_status"))
        try:
            stored_check = json.loads(item.pop("document_check_result_json") or "{}")
        except (TypeError, ValueError):
            stored_check = {}
        item["document_check_categories"] = document_check_category_summaries(stored_check)
        supplier_code = re.sub(r"\D", "", item.get("supplier_code") or "")
        manager_name = " ".join(re.sub(r"[’'`\-]+", " ", (item.get("manager_name") or "").casefold()).split())
        item["amcu_match"] = bool(supplier_code and supplier_code in amcu_codes)
        item["nazk_match"] = bool(manager_name and manager_name in nazk_names)
        review = nazk_reviews.get(supplier_code)
        item["nazk_review"] = review or {}
        item["nazk_review_result"] = (review or {}).get("result", "")
        submission_nazk = submission_nazk_states.get(item["id"], {})
        item["nazk_state"] = submission_nazk.get("state", "not_required")
        item["nazk_can_approve"] = bool(submission_nazk.get("can_approve", True))
        item["nazk_state_reason"] = submission_nazk.get("reason", "")
        item["manager_name_display"] = item.get("manager_name") or submission_nazk.get("manager_name", "")
        item["manager_name_display_source"] = ""
        item["manager_name_display_source_date"] = ""
        if not item.get("manager_name") and item["manager_name_display"]:
            control_manager = normalize_manager_name(item.get("nazk_control_manager", ""))
            edr_manager = normalize_manager_name(item.get("edr_fallback_manager", ""))
            if control_manager and control_manager == edr_manager:
                item["manager_name_display_source"] = "edr_fallback"
                item["manager_name_display_source_date"] = item.get("edr_fallback_checked_at", "")
            else:
                item["manager_name_display_source"] = "nazk_control"
        if review:
            review_manager = " ".join(re.sub(r"[’'`\-]+", " ", (review.get("manager_name") or "").casefold()).split())
            review_is_current = bool(manager_name and review_manager and manager_name == review_manager)
            item["nazk_review_is_current"] = review_is_current
            item["nazk_match"] = review_is_current and review.get("result") in {"підтверджено", "на запит", "можливо"}
        raw_registry_status = item["registry_status"]
        item.update(registry_details(item.pop("registry_milestones"), raw_registry_status))
        item["registry_status"] = registry_status_label(raw_registry_status)
        item["documents"] = json.loads(item.pop("documents_json") or "[]")
        item["decision_documents"] = json.loads(item["decision_documents"] or "[]")
        items.append(item)
    return {"items": items, "total": total, "page": page, "size": size, "pages": (total + size - 1) // size}


def protocol_readiness(payload: dict) -> dict:
    number = str(payload.get("protocol_number") or "").strip()
    date_from = str(payload.get("date_from") or "").strip()
    date_to = str(payload.get("date_to") or "").strip()
    if not number and not (date_from and date_to):
        raise ValueError("Зазначте номер протоколу або повний період надходження заявок")
    scope, args = [], []
    if number:
        scope.append("af.protocol_number=?"); args.append(number)
    if date_from and date_to:
        scope.append("SUBSTR(s.date_published,1,10) BETWEEN ? AND ?"); args.extend([date_from, date_to])
    raw_filters = payload.get("filters") or {}
    filter_params = {key: [str(value or "")] for key, value in raw_filters.items()} if isinstance(raw_filters, dict) else {}
    filter_clause, filter_args = application_filter(filter_params)
    with db() as con:
        rows = con.execute(f"""SELECT s.id,s.supplier_name,s.supplier_code,s.date_published,
          f.pretty_id,f.dk_code,COALESCE(f.title,'') category_title,COALESCE(af.protocol_number,'') protocol_number,
          COALESCE(af.protocol_decision,'') protocol_decision,
          COALESCE(af.compliance_status,'') compliance_status,
          COALESCE(af.compliance_comments,'') compliance_comments,
          COALESCE(af.document_package,'') document_package,
          COALESCE(af.protocol_remarks,'') protocol_remarks,
          COALESCE(NULLIF(af.protocol_officer,''),NULLIF(fo.officer,''),'') protocol_officer,
          COALESCE(af.manager_name,'') manager_name,
          COALESCE(af.protocol_date,'') protocol_date,
          COALESCE(q.status,'pending') source_status
          FROM submissions s JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN qualifications q ON q.id=s.qualification_id
          LEFT JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id
          WHERE ({filter_clause}) AND ({' AND '.join(scope)}) ORDER BY s.date_published,s.id""", (*filter_args, *args)).fetchall()
    items, admitted, rejected, unresolved = [], 0, 0, 0
    for raw in rows:
        row, errors, warnings = dict(raw), [], []
        if not row["manager_name"]:
            errors.append("Не заповнено ПІБ керівника")
        if not row["protocol_number"]:
            errors.append("Не заповнено № протоколу")
        if not row["protocol_date"]:
            errors.append("Не заповнено дату протоколу")
        if not row["protocol_decision"]:
            errors.append("Не визначено Рішення УО (Так/Ні)"); unresolved += 1
        elif row["protocol_decision"] == "admit":
            admitted += 1
            if row["protocol_remarks"].strip() != "Без зауважень":
                errors.append("Рішення УО «Так» неможливе: заявка має зауваження до протоколу")
            if row["source_status"] == "unsuccessful":
                errors.append("Розбіжність: Рішення УО = Так, але в Prozorro заявку відхилено")
        elif row["protocol_decision"] == "reject":
            rejected += 1
            if row["protocol_remarks"].strip() == "Без зауважень" and row["compliance_status"] == "approved":
                errors.append("Немає підстав для відхилення згідно з рішенням комплаєнс та відсутністю зауважень.")
            if row["source_status"] == "active":
                errors.append("Розбіжність: Рішення УО = Ні, але в Prozorro заявку допущено")
            if not row["protocol_remarks"]: errors.append("Не заповнено зауваження до протоколу")
        if number and row["protocol_number"] and row["protocol_number"] != number:
            errors.append(f"Заявку вже віднесено до протоколу № {row['protocol_number']}")
        if not row["compliance_status"]:
            errors.append("Не визначено погодження комплаєнс")
        elif row["compliance_status"] == "rejected":
            if row["protocol_decision"] == "admit":
                errors.append("Заборонена комбінація: Комплаєнс = Не погоджено, Рішення УО = Так")
            if not row["compliance_comments"]:
                errors.append("Не заповнено коментар комплаєнс. Для заявки зі статусом “Не погоджено” необхідно зазначити причину непогодження.")
        if row["source_status"] != "pending":
            warnings.append("Рішення вже оприлюднено в Prozorro")
        row.update(errors=errors, warnings=warnings)
        items.append(row)
    # Normally one authorised officer processes and publishes all applications
    # for the same DK code received on the same day. More than one officer is
    # possible, so this is an explicit warning rather than a blocker.
    officer_groups: dict[tuple[str, str], list[dict]] = {}
    for item in items:
        day = str(item.get("date_published") or "")[:10]
        dk_code = str(item.get("dk_code") or "").strip()
        if day and dk_code:
            officer_groups.setdefault((day, dk_code), []).append(item)
    for (day, dk_code), group in officer_groups.items():
        officers = sorted({str(item.get("protocol_officer") or "").strip() for item in group if str(item.get("protocol_officer") or "").strip()})
        if len(officers) <= 1:
            continue
        display_day = ".".join(reversed(day.split("-"))) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else day
        warning = f"За {display_day} для коду ДК {dk_code} зазначено кілька УО: {', '.join(officers)}"
        for item in group:
            item["warnings"].append(warning)
    error_count = sum(len(item["errors"]) for item in items)
    warning_count = sum(len(item["warnings"]) for item in items)
    return {"ready": bool(items) and error_count == 0, "total": len(items), "admitted": admitted,
            "rejected": rejected, "unresolved": unresolved, "error_count": error_count,
            "warning_count": warning_count, "items": items}


def generate_protocol(payload: dict) -> dict:
    result = protocol_readiness(payload)
    if not result["ready"]:
        raise ValueError(f"Протокол не готовий: {result['error_count']} помилок")
    items = result["items"]
    numbers = {str(item.get("protocol_number") or "").strip() for item in items}
    dates = {str(item.get("protocol_date") or "").strip() for item in items}
    officers = {str(item.get("protocol_officer") or "").strip() for item in items}
    if len(numbers) != 1 or "" in numbers:
        raise ValueError("У заявках мають збігатися номери протоколу")
    if len(dates) != 1 or "" in dates:
        raise ValueError("У заявках мають збігатися дати протоколу")
    if len(officers) != 1 or "" in officers:
        raise ValueError("У заявках має бути визначена одна УО протоколу")
    protocol_number = next(iter(numbers))
    protocol_date = next(iter(dates))
    received_dates = sorted(str(item.get("date_published") or "")[:10] for item in items)
    date_from = str(payload.get("date_from") or "").strip() or received_dates[0]
    date_to = str(payload.get("date_to") or "").strip() or received_dates[-1]
    safe_number = re.sub(r"[^0-9A-Za-zА-ЯІЇЄҐа-яіїєґ_-]+", "_", protocol_number).strip("_") or "protocol"
    safe_date = protocol_date.replace(".", "-").replace("/", "-")
    filename = f"Протокол_{safe_number}_від_{safe_date}.docx"
    output_path = PROTOCOLS_DIR / filename
    build_protocol_docx({
        "items": items, "protocol_number": protocol_number, "protocol_date": protocol_date,
        "date_from": date_from, "date_to": date_to, "officer": next(iter(officers)),
    }, output_path)
    generated_at = now_iso()
    with db() as con:
        for item in items:
            con.execute("""UPDATE application_fields SET generated_protocol_number=?,generated_protocol_date=?,
              generated_protocol_decision=protocol_decision,protocol_generated_at=? WHERE submission_id=?""",
                        (protocol_number, protocol_date, generated_at, item["id"]))
    return {
        "generated": True, "protocol_number": protocol_number, "protocol_date": protocol_date,
        "total": len(items), "admitted": result["admitted"], "rejected": result["rejected"],
        "filename": filename, "download_url": "/api/protocol/files/" + urllib.parse.quote(filename),
    }


def list_frameworks() -> dict:
    with db() as con:
        rows = con.execute("""SELECT f.id, f.pretty_id, f.title, f.dk_code, f.date_modified,
          COUNT(s.id) AS applications_count
          FROM frameworks f LEFT JOIN submissions s ON s.framework_id=f.id
          GROUP BY f.id ORDER BY f.date_modified DESC, f.pretty_id""").fetchall()
    return {"items": [dict(row) for row in rows]}


def base_framework_analytics(params: dict) -> dict:
    """Serve authoritative framework metadata when ProzorroBids is intentionally disabled."""
    page = max(1, int(params.get("page", [1])[0]))
    size = min(100, max(1, int(params.get("size", [25])[0])))
    search = params.get("search", [""])[0].strip().casefold()
    status_filter = params.get("status", [""])[0].strip()
    dk_filter = params.get("dk_code", [""])[0].strip().casefold()
    direction = params.get("direction", ["asc"])[0].lower()
    with db() as con:
        rows = con.execute("""SELECT f.id,f.pretty_id,f.title,f.dk_code,f.status,f.agreement_id,
          f.date_modified,f.raw_json,COUNT(s.id) applications_count
          FROM frameworks f LEFT JOIN submissions s ON s.framework_id=f.id
          GROUP BY f.id""").fetchall()
    items = []
    for row in rows:
        framework = dict(row)
        raw = json.loads(framework.pop("raw_json") or "{}")
        framework["official_status"] = framework.get("status") or ""
        framework["status"] = effective_framework_status(framework.get("status") or "", raw)
        framework.update({
            "published_at": raw.get("date") or raw.get("dateCreated") or "",
            "clarifications_until": (raw.get("enquiryPeriod") or {}).get("clarificationsUntil") or "",
            "applications_until": (raw.get("period") or {}).get("endDate") or "",
            "valid_until": (raw.get("qualificationPeriod") or {}).get("endDate") or "",
            "organizer_name": (raw.get("procuringEntity") or {}).get("name") or "",
            "organizer_code": ((raw.get("procuringEntity") or {}).get("identifier") or {}).get("id") or "",
        })
        haystack = " ".join(str(framework.get(key) or "") for key in
                            ("id", "pretty_id", "title", "dk_code", "agreement_id")).casefold()
        if search and search not in haystack:
            continue
        if dk_filter and dk_filter not in str(framework.get("dk_code") or "").casefold():
            continue
        normalized = "active" if framework["status"] == "active" else "inactive"
        if status_filter and status_filter not in {framework["status"], normalized}:
            continue
        qualified = int(framework.get("applications_count") or 0)
        items.append({"agreement_id": framework.get("agreement_id") or "",
                      "cpv_code": framework.get("dk_code") or "",
                      "source_status": framework.get("status") or "",
                      "last_search_at": "", "search_total": 0,
                      "tender_count": 0, "complete_count": 0, "unsuccessful_count": 0,
                      "bids_count": 0, "buyer_count": 0, "expected_amount": 0,
                      "first_tender": "", "last_tender": "", "supplier_count": 0,
                      "qualified_supplier_count": qualified, "suppliers_current_year": 0,
                      "suppliers_without_bids": qualified, "framework": framework,
                      "agreement_pending": not bool(framework.get("agreement_id"))})
    items.sort(key=lambda item: (item["cpv_code"], item["framework"].get("pretty_id") or ""),
               reverse=direction == "desc")
    total = len(items); offset = (page - 1) * size
    return {"items": items[offset:offset + size], "total": total, "page": page,
            "pages": max(1, (total + size - 1) // size), "size": size,
            "summary": {"tenders": 0, "bids": 0}, "database": "",
            "updated_at": "", "bids_available": False,
            "message": "Аналітика ProzorroBids доступна лише в LOCAL"}


def framework_analytics(params: dict) -> dict:
    """Paged, indexed analytics over agreements/tenders/bids from ProzorroBids."""
    if BIDS_MODE == "disabled":
        return base_framework_analytics(params)
    page = max(1, int(params.get("page", [1])[0]))
    size = min(100, max(1, int(params.get("size", [25])[0])))
    search = params.get("search", [""])[0].strip().casefold()
    status = params.get("status", [""])[0].strip()
    dk_code = params.get("dk_code", [""])[0].strip()
    date_from = params.get("date_from", [""])[0].strip()
    date_to = params.get("date_to", [""])[0].strip()
    sort = params.get("sort", ["cpv_code"])[0]
    direction = "DESC" if params.get("direction", ["asc"])[0].lower() == "desc" else "ASC"
    sort_columns = {"cpv_code": "a.cpv_code", "status": "a.source_status", "updated": "a.last_search_at", "total": "a.search_total"}
    order_by = sort_columns.get(sort, "a.cpv_code")
    where, args = ["1=1"], []
    title_match_agreement_ids = []
    if search:
        # ProzorroBids has agreement IDs and CPV codes, but not the
        # authoritative framework title. Resolve title matches in PQM first
        # and include their agreement IDs in the same Bids query.
        with db() as framework_con:
            for framework_row in framework_con.execute(
                    "SELECT id,pretty_id,title,dk_code,agreement_id FROM frameworks"):
                haystack = " ".join(str(framework_row[key] or "") for key in
                                    ("id", "pretty_id", "title", "dk_code", "agreement_id")).casefold()
                if search in haystack and framework_row["agreement_id"]:
                    title_match_agreement_ids.append(framework_row["agreement_id"])
        search_parts = ["LOWER(a.agreement_id) LIKE ?", "LOWER(COALESCE(a.cpv_code,'')) LIKE ?"]
        args.extend([f"%{search}%", f"%{search}%"])
        if title_match_agreement_ids:
            search_parts.append("a.agreement_id IN (" + ",".join("?" for _ in title_match_agreement_ids) + ")")
            args.extend(title_match_agreement_ids)
        where.append("(" + " OR ".join(search_parts) + ")")
    if status:
        with db() as framework_con:
            status_agreement_ids = []
            for framework_row in framework_con.execute(
                    "SELECT agreement_id,status,raw_json FROM frameworks WHERE COALESCE(agreement_id,'')<>''"):
                raw = json.loads(framework_row["raw_json"] or "{}")
                effective = effective_framework_status(framework_row["status"] or "", raw)
                matches = (status == "active" and effective == "active") or (
                    status == "inactive" and effective != "active") or status == effective
                if matches:
                    status_agreement_ids.append(framework_row["agreement_id"])
        if status_agreement_ids:
            where.append("a.agreement_id IN (" + ",".join("?" for _ in status_agreement_ids) + ")")
            args.extend(status_agreement_ids)
        else:
            where.append("0=1")
    if dk_code:
        where.append("a.cpv_code LIKE ?"); args.append(f"%{dk_code}%")
    date_clauses, date_args = [], []
    if date_from:
        date_clauses.append("COALESCE(tender_start,date_created)>=?"); date_args.append(date_from)
    if date_to:
        date_clauses.append("COALESCE(tender_start,date_created)<?"); date_args.append(date_to + "T23:59:59.999999")
    if date_clauses:
        where.append("EXISTS (SELECT 1 FROM tenders tx WHERE tx.agreement_id=a.agreement_id AND " + " AND ".join(c.replace("tender_start", "tx.tender_start").replace("date_created", "tx.date_created") for c in date_clauses) + ")")
        args.extend(date_args)
    where_sql = " AND ".join(where)
    with bids_db() as con:
        known_agreement_ids = {row[0] for row in con.execute("SELECT agreement_id FROM agreements")}
        filtered_agreement_ids = [row[0] for row in con.execute(
            f"SELECT agreement_id FROM agreements a WHERE {where_sql}", args)]
        total = len(filtered_agreement_ids)
        agreement_total = total
        agreements = [dict(r) for r in con.execute(
            f"SELECT a.* FROM agreements a WHERE {where_sql} ORDER BY {order_by} {direction}, a.agreement_id LIMIT ? OFFSET ?",
            [*args, size, (page - 1) * size],
        ).fetchall()]
        items = []
        tender_filter = (" AND " + " AND ".join(date_clauses)) if date_clauses else ""
        bid_filter, bid_args = [], []
        if date_from: bid_filter.append("bid_date>=?"); bid_args.append(date_from)
        if date_to: bid_filter.append("bid_date<?"); bid_args.append(date_to + "T23:59:59.999999")
        bid_suffix = (" AND " + " AND ".join(bid_filter)) if bid_filter else ""
        page_ids = [item["agreement_id"] for item in agreements]
        page_placeholders = ",".join("?" for _ in page_ids)
        tender_by, bid_filtered_by, bid_all_by = {}, {}, {}
        if page_ids:
            tender_by = {r["agreement_id"]: dict(r) for r in con.execute(f"""SELECT agreement_id,
              COUNT(*) tender_count,
              SUM(CASE WHEN LOWER(COALESCE(status,''))='complete' THEN 1 ELSE 0 END) complete_count,
              SUM(CASE WHEN LOWER(COALESCE(status,''))='unsuccessful' THEN 1 ELSE 0 END) unsuccessful_count,
              COALESCE(SUM(bids_count),0) bids_count,COUNT(DISTINCT buyer_id) buyer_count,
              COALESCE(SUM(amount),0) expected_amount,MIN(COALESCE(tender_start,date_created)) first_tender,
              MAX(COALESCE(tender_start,date_created)) last_tender FROM tenders
              WHERE agreement_id IN ({page_placeholders}){tender_filter} GROUP BY agreement_id""",
              [*page_ids, *date_args])}
            bid_filtered_by = {r["agreement_id"]: int(r["supplier_count"] or 0) for r in con.execute(f"""
              SELECT agreement_id,COUNT(DISTINCT supplier_id) supplier_count FROM bids
              WHERE agreement_id IN ({page_placeholders}){bid_suffix} GROUP BY agreement_id""",
              [*page_ids, *bid_args])}
            bid_all_by = {r["agreement_id"]: dict(r) for r in con.execute(f"""SELECT agreement_id,
              COUNT(DISTINCT CASE WHEN substr(bid_date,1,4)=? THEN supplier_id END) suppliers_current_year,
              GROUP_CONCAT(DISTINCT supplier_id) bidder_codes FROM bids
              WHERE agreement_id IN ({page_placeholders}) GROUP BY agreement_id""",
              [str(datetime.now().year), *page_ids])}
        for agreement in agreements:
            agreement_id = agreement["agreement_id"]
            aggregate = tender_by.get(agreement_id, {"tender_count": 0, "complete_count": 0,
              "unsuccessful_count": 0, "bids_count": 0, "buyer_count": 0, "expected_amount": 0,
              "first_tender": "", "last_tender": ""})
            bid_all = bid_all_by.get(agreement_id, {})
            bidder_codes = [re.sub(r"\D", "", code) for code in str(bid_all.get("bidder_codes") or "").split(",") if code]
            items.append({**agreement, **aggregate, "supplier_count": bid_filtered_by.get(agreement_id, 0),
                          "suppliers_current_year": int(bid_all.get("suppliers_current_year") or 0),
                          "_bidder_codes": bidder_codes})
        summary_tender_where = []
        summary_tender_args = []
        if filtered_agreement_ids:
            summary_tender_where.append("t.agreement_id IN (" + ",".join("?" for _ in filtered_agreement_ids) + ")")
            summary_tender_args.extend(filtered_agreement_ids)
        else:
            summary_tender_where.append("0=1")
        if date_from:
            summary_tender_where.append("COALESCE(t.tender_start,t.date_created)>=?"); summary_tender_args.append(date_from)
        if date_to:
            summary_tender_where.append("COALESCE(t.tender_start,t.date_created)<?"); summary_tender_args.append(date_to + "T23:59:59.999999")
        if where_sql == "1=1" and not date_from and not date_to:
            summary_row = con.execute("""SELECT COALESCE(SUM(search_total),0) tenders,
              COALESCE((SELECT MAX(rowid) FROM bids),0) bids FROM agreements""").fetchone()
        else:
            summary_row = con.execute(f"""SELECT COUNT(*) tenders,COALESCE(SUM(t.bids_count),0) bids
              FROM tenders t WHERE {' AND '.join(summary_tender_where)}""", summary_tender_args).fetchone()
        summary = {"tenders": int(summary_row["tenders"]), "bids": int(summary_row["bids"])}
    local = {}
    qualified_by_agreement = {}
    local_only = []
    with db() as con:
        framework_rows = con.execute("""SELECT f.id,f.pretty_id,f.title,f.dk_code,f.status,f.agreement_id,f.date_modified,f.raw_json,
          COUNT(s.id) applications_count FROM frameworks f LEFT JOIN submissions s ON s.framework_id=f.id
          GROUP BY f.id""").fetchall()
        for agreement, supplier_code in con.execute("""SELECT f.agreement_id,rc.supplier_code
          FROM frameworks f JOIN registry_contracts rc ON rc.framework_id=f.id
          WHERE COALESCE(f.agreement_id,'')<>'' AND COALESCE(rc.supplier_code,'')<>''"""):
            qualified_by_agreement.setdefault(agreement, set()).add(re.sub(r"\D", "", supplier_code or ""))
        for row in framework_rows:
            framework = dict(row)
            raw = json.loads(framework.pop("raw_json") or "{}")
            framework["official_status"] = framework.get("status") or ""
            framework["status"] = effective_framework_status(framework.get("status") or "", raw)
            framework.update({
                "published_at": raw.get("date") or raw.get("dateCreated") or "",
                "clarifications_until": (raw.get("enquiryPeriod") or {}).get("clarificationsUntil") or (raw.get("enquiryPeriod") or {}).get("endDate") or "",
                "applications_until": (raw.get("period") or {}).get("endDate") or "",
                "valid_until": (raw.get("qualificationPeriod") or {}).get("endDate") or "",
                "organizer_name": (raw.get("procuringEntity") or {}).get("name") or "",
                "organizer_code": ((raw.get("procuringEntity") or {}).get("identifier") or {}).get("id") or "",
            })
            if row["agreement_id"]:
                local[row["agreement_id"]] = framework
            if row["agreement_id"] and row["agreement_id"] in known_agreement_ids:
                continue
            haystack = " ".join(str(framework.get(key) or "") for key in ("id", "pretty_id", "title", "dk_code", "agreement_id")).casefold()
            if search and search not in haystack:
                continue
            if dk_code and dk_code.casefold() not in str(row["dk_code"] or "").casefold():
                continue
            normalized_status = "active" if framework["status"] == "active" else "inactive"
            if status and status not in {framework["status"], normalized_status}:
                continue
            if date_from or date_to:
                continue
            local_only.append({"agreement_id": row["agreement_id"] or "", "cpv_code": row["dk_code"] or "",
                "source_status": framework["status"] or "", "last_search_at": "", "search_total": 0,
                "tender_count": 0, "bids_count": 0, "buyer_count": 0, "expected_amount": 0,
                "first_tender": "", "last_tender": "", "supplier_count": 0,
                "qualified_supplier_count": len(qualified_by_agreement.get(row["agreement_id"], set())),
                "suppliers_current_year": 0,
                "suppliers_without_bids": len(qualified_by_agreement.get(row["agreement_id"], set())),
                "framework": framework, "agreement_pending": not bool(row["agreement_id"])})
    for item in items:
        item["framework"] = local.get(item["agreement_id"])
        if item["framework"]:
            item["source_status"] = item["framework"].get("status") or item.get("source_status")
        item["agreement_pending"] = False
        qualified_codes = qualified_by_agreement.get(item["agreement_id"], set())
        bidder_codes = set(item.pop("_bidder_codes", []))
        item["qualified_supplier_count"] = len(qualified_codes)
        item["suppliers_without_bids"] = len(qualified_codes - bidder_codes)
    local_only.sort(key=lambda item: (item["cpv_code"], item["framework"].get("pretty_id") or ""), reverse=direction == "DESC")
    offset = (page - 1) * size
    if offset + len(items) >= agreement_total and len(items) < size:
        local_start = max(0, offset - agreement_total)
        items.extend(local_only[local_start:local_start + (size - len(items))])
    total += len(local_only)
    pages = max(1, (total + size - 1) // size)
    return {"items": items, "total": total, "page": page, "pages": pages, "size": size, "summary": summary,
            "database": str(BIDS_DB_PATH), "updated_at": max((x.get("last_search_at") or "" for x in items), default="")}


def framework_analytics_details(agreement_id: str, params: dict) -> dict:
    date_from = params.get("date_from", [""])[0].strip()
    date_to = params.get("date_to", [""])[0].strip()
    clauses, args = ["b.agreement_id=?"], [agreement_id]
    if date_from: clauses.append("b.bid_date>=?"); args.append(date_from)
    if date_to: clauses.append("b.bid_date<?"); args.append(date_to + "T23:59:59.999999")
    award_clauses, award_args = ["agreement_id=?", "LOWER(COALESCE(status,''))='active'"], [agreement_id]
    if date_from: award_clauses.append("award_date>=?"); award_args.append(date_from)
    if date_to: award_clauses.append("award_date<?"); award_args.append(date_to + "T23:59:59.999999")
    tender_clauses, tender_args = ["agreement_id=?"], [agreement_id]
    if date_from: tender_clauses.append("COALESCE(tender_start,date_created)>=?"); tender_args.append(date_from)
    if date_to: tender_clauses.append("COALESCE(tender_start,date_created)<?"); tender_args.append(date_to + "T23:59:59.999999")
    with bids_db() as con:
        agreement = con.execute("SELECT * FROM agreements WHERE agreement_id=?", (agreement_id,)).fetchone()
        agreement = agreement or {"agreement_id": agreement_id, "cpv_code": "", "source_status": "",
                                  "last_search_at": "", "search_total": 0}
        tender_stats = dict(con.execute("""SELECT COUNT(*) total,
          SUM(CASE WHEN LOWER(COALESCE(status,''))='complete' THEN 1 ELSE 0 END) complete,
          SUM(CASE WHEN LOWER(COALESCE(status,''))='unsuccessful' THEN 1 ELSE 0 END) unsuccessful
          FROM tenders WHERE agreement_id=?""", (agreement_id,)).fetchone())
        all_bidder_codes = {str(r[0] or "") for r in con.execute(
            "SELECT DISTINCT supplier_id FROM bids WHERE agreement_id=? AND COALESCE(supplier_id,'')<>''", (agreement_id,))}
        current_year_bidder_codes = {str(r[0] or "") for r in con.execute("""SELECT DISTINCT supplier_id FROM bids
          WHERE agreement_id=? AND COALESCE(supplier_id,'')<>'' AND substr(bid_date,1,4)=?""",
          (agreement_id, str(datetime.now().year)))}
        suppliers = [dict(r) for r in con.execute(f"""SELECT b.supplier_id,MAX(b.supplier_name) supplier_name,
          COUNT(DISTINCT b.tender_id) participations,COUNT(*) bids_count,COALESCE(SUM(b.amount),0) amount,
          COALESCE(MAX(w.wins),0) wins
          FROM bids b LEFT JOIN (
            SELECT supplier_id,COUNT(DISTINCT tender_id) wins FROM awards
            WHERE {' AND '.join(award_clauses)} GROUP BY supplier_id
          ) w ON w.supplier_id=b.supplier_id
          WHERE {' AND '.join(clauses)} GROUP BY b.supplier_id
          ORDER BY participations DESC,bids_count DESC,supplier_name LIMIT 100""", [*award_args, *args])]
        tenders = [dict(r) for r in con.execute(f"""SELECT tender_id,title,status,amount,currency,
          COALESCE(tender_start,date_created) tender_date,buyer_name,bids_count
          FROM tenders WHERE {' AND '.join(tender_clauses)} ORDER BY tender_date DESC LIMIT 100""", tender_args)]
    framework = None
    qualified_supplier_rows = []
    with db() as con:
        row = con.execute("SELECT * FROM frameworks WHERE agreement_id=?", (agreement_id,)).fetchone()
        if row:
            framework = dict(row)
            raw = json.loads(framework.pop("raw_json") or "{}")
            framework.update({
                "published_at": raw.get("date") or raw.get("dateCreated") or "",
                "clarifications_until": (raw.get("enquiryPeriod") or {}).get("clarificationsUntil") or (raw.get("enquiryPeriod") or {}).get("endDate") or "",
                "applications_until": (raw.get("period") or {}).get("endDate") or "",
                "valid_until": (raw.get("qualificationPeriod") or {}).get("endDate") or "",
                "organizer_name": (raw.get("procuringEntity") or {}).get("name") or "",
                "organizer_code": ((raw.get("procuringEntity") or {}).get("identifier") or {}).get("id") or "",
            })
        framework_id = (framework or {}).get("id") or ""
        qualified_codes = {re.sub(r"\D", "", str(r[0] or "")) for r in con.execute(
            "SELECT DISTINCT supplier_code FROM registry_contracts WHERE framework_id=? AND COALESCE(supplier_code,'')<>''",
            (framework_id,))} if framework_id else set()
        if framework_id:
            qualified_supplier_rows = [dict(r) for r in con.execute("""SELECT rc.supplier_code,
              COALESCE(MAX(s.supplier_name),'') supplier_name FROM registry_contracts rc
              LEFT JOIN submissions s ON s.qualification_id=rc.qualification_id
              WHERE rc.framework_id=? AND COALESCE(rc.supplier_code,'')<>''
              GROUP BY rc.supplier_code ORDER BY supplier_name""", (framework_id,)).fetchall()]
        existing_supplier_codes = {re.sub(r"\D", "", str(item.get("supplier_id") or "")) for item in suppliers}
        for qualified in qualified_supplier_rows:
            code = re.sub(r"\D", "", str(qualified.get("supplier_code") or ""))
            if code and code not in existing_supplier_codes:
                suppliers.append({"supplier_id": code, "supplier_name": qualified.get("supplier_name") or "",
                                  "participations": 0, "bids_count": 0, "amount": 0, "wins": 0,
                                  "qualified_supplier": True})
        supplier_codes = {re.sub(r"\D", "", str(item.get("supplier_id") or "")) for item in suppliers}
        placeholders = ",".join("?" for _ in supplier_codes)
        selected_codes = tuple(sorted(supplier_codes))
        amcu_codes = {re.sub(r"\D", "", str(r[0] or "")) for r in con.execute(
            f"SELECT DISTINCT offender_code FROM amcu_registry WHERE DIGITS(offender_code) IN ({placeholders})",
            selected_codes)} if selected_codes else set()
        active_counts = {re.sub(r"\D", "", str(r[0] or "")): int(r[1] or 0) for r in con.execute(
            f"SELECT supplier_code,active_count FROM supplier_registry_summary WHERE DIGITS(supplier_code) IN ({placeholders})",
            selected_codes)} if selected_codes else {}
        profiles = {re.sub(r"\D", "", str(r[0] or "")): dict(r) for r in con.execute(
            f"SELECT * FROM supplier_edr_profiles WHERE DIGITS(supplier_code) IN ({placeholders})",
            selected_codes)} if selected_codes else {}
        reviews = {re.sub(r"\D", "", str(r[0] or "")): dict(r) for r in con.execute(
            f"SELECT * FROM supplier_nazk_reviews WHERE DIGITS(supplier_code) IN ({placeholders})",
            selected_codes)} if selected_codes else {}
        nazk_names = {" ".join(re.sub(r"[’'`\-]+", " ", str(r[0] or "").casefold()).split()) for r in con.execute(
            "SELECT DISTINCT full_name FROM nazk_registry WHERE COALESCE(full_name,'')<>''")}
        framework_submissions = {}
        if framework_id and selected_codes:
            for submission in con.execute(f"""SELECT s.id,s.supplier_code,s.date_published
              FROM submissions s
              WHERE s.framework_id=? AND DIGITS(s.supplier_code) IN ({placeholders})
              ORDER BY COALESCE(s.date_published,'') DESC,s.id DESC""", (framework_id, *selected_codes)):
                code = re.sub(r"\D", "", str(submission["supplier_code"] or ""))
                framework_submissions.setdefault(code, submission["id"])
        submission_nazk = {
            code: get_submission_nazk_state(con, submission_id, nazk_names)
            for code, submission_id in framework_submissions.items()
        }
    for item in suppliers:
        code = re.sub(r"\D", "", str(item.get("supplier_id") or ""))
        item["qualified_supplier"] = code in qualified_codes
        profile = profiles.get(code) or {}; review = reviews.get(code) or {}
        current_manager = " ".join(re.sub(r"[’'`\-]+", " ", str(profile.get("manager_name") or "").casefold()).split())
        review_manager = " ".join(re.sub(r"[’'`\-]+", " ", str(review.get("manager_name") or "").casefold()).split())
        review_is_current = bool(current_manager and review_manager and current_manager == review_manager)
        item["amcu_match"] = code in amcu_codes
        item["active_qualifications"] = active_counts.get(code, 0)
        item["nazk_review"] = review
        item["nazk_review_is_current"] = review_is_current
        item["nazk_match"] = (review_is_current and review.get("result") in {"підтверджено", "на запит", "можливо"}) \
            if review else bool(current_manager and current_manager in nazk_names)
        item["submission_id"] = framework_submissions.get(code, "")
        item["nazk_submission_state"] = submission_nazk.get(code) or {}
        item["nazk_submission_presentation"] = get_submission_nazk_presentation_state(
            item["nazk_submission_state"]
        )
    bidder_digits = {re.sub(r"\D", "", code) for code in all_bidder_codes}
    analytics = {**tender_stats, "suppliers_with_bids": len(bidder_digits),
                 "suppliers_current_year": len({re.sub(r'\D', '', code) for code in current_year_bidder_codes}),
                 "qualified_suppliers": len(qualified_codes),
                 "suppliers_without_bids": len(qualified_codes - bidder_digits)}
    agreement_data = dict(agreement)
    if framework:
        agreement_data["source_status"] = framework.get("status") or agreement_data.get("source_status")
    return {"agreement": agreement_data, "framework": framework, "suppliers": suppliers, "tenders": tenders,
            "analytics": analytics}


def _refresh_bids_status_cache() -> None:
    """Build the expensive 30+ GB Bids snapshot once, outside the HTTP request."""
    try:
        with bids_db() as con:
            counts = dict(con.execute("""SELECT
          (SELECT COUNT(*) FROM agreements) agreements,
          (SELECT COUNT(*) FROM agreements WHERE last_search_at IS NOT NULL) searched_agreements,
          (SELECT COUNT(*) FROM tenders) tenders,
          (SELECT COUNT(*) FROM tenders WHERE detail_loaded=1) detailed_tenders,
          (SELECT COUNT(*) FROM tenders WHERE detail_loaded=0 OR last_error IS NOT NULL) pending_tenders,
          (SELECT COUNT(*) FROM bids) bids,
          (SELECT COUNT(*) FROM awards) awards,
          (SELECT COUNT(*) FROM tenders WHERE last_error IS NOT NULL) tender_errors""").fetchone())
            coverage = dict(con.execute("""SELECT
          MIN(SUBSTR(COALESCE(tender_start,date_created),1,10)) tender_from,
          MAX(SUBSTR(COALESCE(tender_start,date_created),1,10)) tender_to,
          MAX(SUBSTR(date_modified,1,10)) modified_to,
          MAX(last_detail_at) last_detail_at FROM tenders""").fetchone())
            agreement_state = dict(con.execute("""SELECT MAX(last_search_at) last_search_at,
          SUM(CASE WHEN last_error IS NOT NULL AND last_error<>'' THEN 1 ELSE 0 END) agreement_errors
          FROM agreements""").fetchone())
            completed = con.execute("""SELECT * FROM sync_log WHERE status='completed'
          ORDER BY COALESCE(finished_at,started_at) DESC LIMIT 1""").fetchone()
            open_logs = [dict(row) for row in con.execute("""SELECT * FROM sync_log WHERE status='running'
          ORDER BY started_at DESC""").fetchall()]
        complete = counts["pending_tenders"] == 0 and counts["tenders"] == counts["detailed_tenders"]
        result = {**counts, **coverage, **agreement_state, "history_complete": complete,
                  "last_completed": dict(completed) if completed else None,
                  "stale_open_logs": open_logs, "database": str(BIDS_DB_PATH), "checked_at": now_iso(),
                  "update": dict(BIDS_UPDATE_STATE)}
        BIDS_STATUS_CACHE.update(at=time.time(), value=result)
    except Exception as exc:
        BIDS_STATUS_CACHE.update(at=time.time(), error=str(exc))
    finally:
        BIDS_STATUS_LOCK.release()


def bids_sync_status(force: bool = False) -> dict:
    """Return cached status immediately; refresh heavy counts once in background."""
    cached = BIDS_STATUS_CACHE.get("value")
    fresh = cached is not None and time.time() - float(BIDS_STATUS_CACHE.get("at") or 0) < 600
    if (force or not fresh) and BIDS_STATUS_LOCK.acquire(blocking=False):
        threading.Thread(target=_refresh_bids_status_cache, daemon=True).start()
    if cached is not None:
        return {**cached, "refreshing": BIDS_STATUS_LOCK.locked(), "update": dict(BIDS_UPDATE_STATE)}
    return {
        "database": str(BIDS_DB_PATH), "checked_at": None, "refreshing": True,
        "message": "Статистика ProzorroBids оновлюється у фоновому режимі",
        "error": BIDS_STATUS_CACHE.get("error", ""), "update": dict(BIDS_UPDATE_STATE),
    }


def bids_update_worker() -> None:
    today = datetime.now().astimezone().date()
    try:
        with bids_db() as con:
            value = con.execute("SELECT MAX(SUBSTR(date_modified,1,10)) FROM tenders").fetchone()[0]
        synchronized = datetime.strptime(value, "%Y-%m-%d").date() if value else today - timedelta(days=14)
        date_from = min(synchronized - timedelta(days=2), today)
        BIDS_UPDATE_STATE.update(running=True, message="Інкрементальне оновлення нових і змінених закупівель…",
                                 started_at=now_iso(), updated_at=None, date_from=date_from.isoformat(),
                                 date_to=today.isoformat(), error=None)
        if not BIDS_PYTHON.is_file():
            raise FileNotFoundError(f"Не знайдено робочий Python ProzorroBids: {BIDS_PYTHON}")
        subprocess.run([str(BIDS_PYTHON), "-c", "import requests"], cwd=BIDS_PROJECT_PATH,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=20)
        log_path = DATA_DIR / "bids_manual_update.log"
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n[{now_iso()}] update {date_from} — {today}\n")
            subprocess.run([str(BIDS_PYTHON), str(BIDS_PROJECT_PATH / "main.py"), "update", "--from", date_from.isoformat(),
                            "--to", today.isoformat(), "--no-export"], cwd=BIDS_PROJECT_PATH,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
            BIDS_UPDATE_STATE["message"] = "Повторна перевірка активних закупівель…"
            subprocess.run([str(BIDS_PYTHON), str(BIDS_PROJECT_PATH / "main.py"), "refresh-active"], cwd=BIDS_PROJECT_PATH,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        BIDS_UPDATE_STATE["message"] = "Оновлення Bids завершено"
    except Exception as exc:
        BIDS_UPDATE_STATE.update(message=f"Помилка оновлення Bids: {exc}", error=str(exc))
    finally:
        BIDS_UPDATE_STATE.update(running=False, updated_at=now_iso())
        with BIDS_STATUS_LOCK:
            BIDS_STATUS_CACHE.update(at=0.0, value=None)


def powerbi_export_status() -> dict:
    if not ENABLE_POWERBI:
        return {"available": False, "path": "", "exists": False, "complete": False,
                "updated_at": None, "size_bytes": 0, "total_rows": 0, "datasets": [],
                "state": {"running": False, "message": "Power BI вимкнено у цьому середовищі",
                          "error": None}}
    manifest = POWERBI_CURRENT_PATH / "manifest.csv"
    datasets, total_rows = [], 0
    if manifest.is_file():
        with manifest.open("r", encoding="utf-8-sig", newline="") as source:
            for row in csv.DictReader(source, delimiter=";"):
                count = int(row.get("Кількість рядків") or 0)
                total_rows += count
                datasets.append({"name": row.get("Набір") or "", "rows": count,
                                 "files": int(row.get("Кількість файлів") or 0), "time": row.get("Час") or ""})
    size = sum(path.stat().st_size for path in POWERBI_CURRENT_PATH.rglob("*") if path.is_file()) if POWERBI_CURRENT_PATH.is_dir() else 0
    completed = POWERBI_CURRENT_PATH / "_COMPLETE.txt"
    return {"path": str(POWERBI_CURRENT_PATH), "exists": POWERBI_CURRENT_PATH.is_dir(),
            "complete": completed.is_file(), "updated_at": datetime.fromtimestamp(completed.stat().st_mtime).astimezone().isoformat() if completed.is_file() else None,
            "size_bytes": size, "total_rows": total_rows, "datasets": datasets, "state": dict(POWERBI_EXPORT_STATE)}


def powerbi_export_worker() -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    build_name = f".powerbi_build_{stamp}"
    build_path = POWERBI_OUTPUT_ROOT / build_name
    previous_path = POWERBI_OUTPUT_ROOT / ".powerbi_previous"
    try:
        POWERBI_EXPORT_STATE.update(running=True, message="Формування файлів для Power BI…",
                                    started_at=now_iso(), updated_at=None, error=None)
        log_path = DATA_DIR / "powerbi_export.log"
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n[{now_iso()}] export-powerbi {build_name}\n")
            subprocess.run([sys.executable, str(BIDS_PROJECT_PATH / "main.py"), "export-powerbi", "--dir", build_name],
                           cwd=BIDS_PROJECT_PATH, stdout=log, stderr=subprocess.STDOUT, check=True)
        if not (build_path / "_COMPLETE.txt").is_file():
            raise RuntimeError("Експортер не створив маркер завершення")
        POWERBI_EXPORT_STATE["message"] = "Заміна попереднього набору…"
        if previous_path.exists():
            shutil.rmtree(previous_path)
        if POWERBI_CURRENT_PATH.exists():
            POWERBI_CURRENT_PATH.rename(previous_path)
        try:
            build_path.rename(POWERBI_CURRENT_PATH)
        except Exception:
            if previous_path.exists() and not POWERBI_CURRENT_PATH.exists():
                previous_path.rename(POWERBI_CURRENT_PATH)
            raise
        if previous_path.exists():
            shutil.rmtree(previous_path)
        POWERBI_EXPORT_STATE["message"] = "Експорт Power BI успішно оновлено"
    except Exception as exc:
        POWERBI_EXPORT_STATE.update(message=f"Помилка експорту Power BI: {exc}", error=str(exc))
    finally:
        POWERBI_EXPORT_STATE.update(running=False, updated_at=now_iso())


def supplier_options(params: dict) -> dict:
    search = params.get("search", [""])[0].strip().casefold()
    framework_id = params.get("framework_id", [""])[0].strip()
    where, args = ["s.supplier_code<>''"], []
    if framework_id:
        where.append("s.framework_id=?"); args.append(framework_id)
    if search:
        where.append("(INSTR(CASEFOLD(s.supplier_code),?)>0 OR INSTR(CASEFOLD(s.supplier_name),?)>0)")
        args.extend([search, search])
    with db() as con:
        rows = con.execute(f"""SELECT s.supplier_code code, MIN(s.supplier_name) name, COUNT(*) applications_count
          FROM submissions s WHERE {' AND '.join(where)} GROUP BY s.supplier_code
          ORDER BY applications_count DESC, code LIMIT 50""", args).fetchall()
    return {"items": [dict(row) for row in rows]}


def refresh_supplier_registry_summary() -> int:
    """Materialize the cross-framework supplier register after synchronization."""
    refreshed_at = now_iso()
    with db() as con:
        con.execute("DELETE FROM supplier_registry_summary")
        con.execute("""INSERT INTO supplier_registry_summary
          (supplier_code,supplier_name,qualifications_count,active_count,inactive_count,
           suspended_count,frameworks_count,dk_codes,last_qualification,refreshed_at)
          SELECT rc.supplier_code,MAX(COALESCE(s.supplier_name,'')),COUNT(DISTINCT rc.id),
          SUM(CASE WHEN rc.status='active' AND LOWER(COALESCE(f.status,''))='active'
            AND (COALESCE(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),'')=''
              OR date(substr(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),1,10))>=date('now'))
            THEN 1 ELSE 0 END),
          SUM(CASE WHEN rc.status='terminated' OR (rc.status='active' AND NOT (
            LOWER(COALESCE(f.status,''))='active' AND
            (COALESCE(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),'')=''
              OR date(substr(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),1,10))>=date('now'))))
            THEN 1 ELSE 0 END),
          SUM(CASE WHEN rc.status='suspended' THEN 1 ELSE 0 END),
          COUNT(DISTINCT rc.framework_id),GROUP_CONCAT(DISTINCT f.dk_code),
          MAX(COALESCE(NULLIF(json_extract(rc.raw_json,'$.dateModified'),''),
              NULLIF(json_extract(rc.raw_json,'$.date'),''),q.decision_date,rc.synced_at)),?
          FROM registry_contracts rc
          LEFT JOIN qualifications q ON q.id=rc.qualification_id
          LEFT JOIN submissions s ON s.id=q.submission_id
          LEFT JOIN frameworks f ON f.id=rc.framework_id
          WHERE COALESCE(rc.supplier_code,'')<>'' GROUP BY rc.supplier_code""", (refreshed_at,))
        return con.execute("SELECT COUNT(*) FROM supplier_registry_summary").fetchone()[0]


GOOGLE_OAUTH_CLIENT_ACCESS_ERROR = ""
GOOGLE_OAUTH_TOKEN_ACCESS_ERROR = ""


def _google_oauth_client() -> dict | None:
    global GOOGLE_OAUTH_CLIENT_ACCESS_ERROR
    GOOGLE_OAUTH_CLIENT_ACCESS_ERROR = ""
    inline = os.environ.get("PQM_GOOGLE_OAUTH_CLIENT_JSON", "").strip()
    if inline:
        try:
            data = json.loads(inline)
            return data.get("installed") or data.get("web") or data
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            GOOGLE_OAUTH_CLIENT_ACCESS_ERROR = "invalid_configuration"
            SERVER_LOG.warning("Google OAuth client configuration is invalid type=%s", type(exc).__name__)
            return None
    try:
        if not GOOGLE_OAUTH_CLIENT_PATH.is_file():
            return None
        data = json.loads(GOOGLE_OAUTH_CLIENT_PATH.read_text(encoding="utf-8"))
    except PermissionError as exc:
        GOOGLE_OAUTH_CLIENT_ACCESS_ERROR = "access_denied"
        SERVER_LOG.warning("Google OAuth client configuration is inaccessible path=%s type=%s",
                       GOOGLE_OAUTH_CLIENT_PATH, type(exc).__name__)
        return None
    except OSError as exc:
        GOOGLE_OAUTH_CLIENT_ACCESS_ERROR = "unavailable"
        SERVER_LOG.warning("Google OAuth client configuration is unavailable path=%s type=%s",
                       GOOGLE_OAUTH_CLIENT_PATH, type(exc).__name__)
        return None
    except (ValueError, json.JSONDecodeError) as exc:
        GOOGLE_OAUTH_CLIENT_ACCESS_ERROR = "invalid_configuration"
        SERVER_LOG.warning("Google OAuth client configuration is invalid path=%s type=%s",
                       GOOGLE_OAUTH_CLIENT_PATH, type(exc).__name__)
        return None
    return data.get("installed") or data.get("web")


def _google_oauth_token() -> dict | None:
    global GOOGLE_OAUTH_TOKEN_ACCESS_ERROR
    GOOGLE_OAUTH_TOKEN_ACCESS_ERROR = ""
    try:
        if not GOOGLE_OAUTH_TOKEN_PATH.is_file():
            return None
        return json.loads(GOOGLE_OAUTH_TOKEN_PATH.read_text(encoding="utf-8"))
    except PermissionError as exc:
        GOOGLE_OAUTH_TOKEN_ACCESS_ERROR = "access_denied"
        SERVER_LOG.warning("Google OAuth token is inaccessible path=%s type=%s",
                       GOOGLE_OAUTH_TOKEN_PATH, type(exc).__name__)
        return None
    except OSError as exc:
        GOOGLE_OAUTH_TOKEN_ACCESS_ERROR = "unavailable"
        SERVER_LOG.warning("Google OAuth token is unavailable path=%s type=%s",
                       GOOGLE_OAUTH_TOKEN_PATH, type(exc).__name__)
        return None
    except (ValueError, json.JSONDecodeError) as exc:
        GOOGLE_OAUTH_TOKEN_ACCESS_ERROR = "invalid_configuration"
        SERVER_LOG.warning("Google OAuth token is invalid path=%s type=%s",
                       GOOGLE_OAUTH_TOKEN_PATH, type(exc).__name__)
        return None


def google_oauth_status() -> dict:
    if not ENABLE_GOOGLE:
        return {"configured": False, "authorized": False, "enabled": False,
                "message": "Google OAuth вимкнено у цьому середовищі"}
    client = _google_oauth_client()
    token = _google_oauth_token()
    configuration_error = GOOGLE_OAUTH_CLIENT_ACCESS_ERROR or GOOGLE_OAUTH_TOKEN_ACCESS_ERROR
    if configuration_error:
        messages = {
            "access_denied": "Немає доступу до локальної конфігурації Google OAuth",
            "unavailable": "Локальна конфігурація Google OAuth недоступна",
            "invalid_configuration": "Локальна конфігурація Google OAuth пошкоджена",
        }
        result = {"configured": bool(client), "authorized": False, "enabled": True,
                  "available": False, "configuration_error": configuration_error,
                  "message": messages.get(configuration_error, "Google OAuth недоступний")}
        if not IS_WEB_ENV:
            result["client_path"] = str(GOOGLE_OAUTH_CLIENT_PATH)
        return result
    result = {"configured": bool(client), "authorized": bool(token and token.get("refresh_token")),
            "enabled": True, "available": True, "configuration_error": "",
            "message": ("Google підключено для читання таблиць" if token and token.get("refresh_token") else
                        "Потрібно увійти через Google" if client else
                        "Потрібен OAuth Client ID для локального застосунку")}
    if not IS_WEB_ENV:
        result["client_path"] = str(GOOGLE_OAUTH_CLIENT_PATH)
    return result


def google_oauth_authorization_url() -> str:
    if not ENABLE_GOOGLE:
        raise RuntimeError("Google OAuth вимкнено у цьому середовищі")
    client = _google_oauth_client()
    if not client:
        if GOOGLE_OAUTH_CLIENT_ACCESS_ERROR:
            raise RuntimeError("Локальна конфігурація Google OAuth недоступна. Перевірте права доступу до файла налаштувань.")
        raise FileNotFoundError(f"OAuth client file not found: {GOOGLE_OAUTH_CLIENT_PATH}")
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    redirect_uri = os.environ.get(
        "PQM_GOOGLE_OAUTH_REDIRECT_URI", f"http://127.0.0.1:{PORT}/api/google-oauth/callback"
    ).strip()
    GOOGLE_OAUTH_PENDING[state] = {"verifier": verifier, "redirect_uri": redirect_uri, "created_at": time.time()}
    params = {"client_id": client["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
              "scope": GOOGLE_SHEETS_READONLY_SCOPE, "access_type": "offline", "prompt": "consent",
              "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    return (client.get("auth_uri") or "https://accounts.google.com/o/oauth2/auth") + "?" + urllib.parse.urlencode(params)


def google_oauth_exchange(code: str, state: str) -> None:
    pending = GOOGLE_OAUTH_PENDING.pop(state, None)
    client = _google_oauth_client()
    if not pending or not client or time.time() - pending["created_at"] > 600:
        raise ValueError("Сеанс авторизації недійсний або прострочений")
    payload = {"code": code, "client_id": client["client_id"], "client_secret": client.get("client_secret", ""),
               "redirect_uri": pending["redirect_uri"], "grant_type": "authorization_code",
               "code_verifier": pending["verifier"]}
    request = urllib.request.Request(client.get("token_uri") or "https://oauth2.googleapis.com/token",
        data=urllib.parse.urlencode(payload).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=60) as response:
        token = json.loads(response.read().decode())
    token["obtained_at"] = time.time()
    GOOGLE_OAUTH_DIR.mkdir(parents=True, exist_ok=True)
    GOOGLE_OAUTH_TOKEN_PATH.write_text(json.dumps(token, ensure_ascii=False), encoding="utf-8")


def _google_access_token() -> str:
    token = _google_oauth_token()
    client = _google_oauth_client()
    if not token or not client or not token.get("refresh_token"):
        raise PermissionError("Google не авторизовано. Спочатку підключіть Google у модулі постачальників.")
    if token.get("access_token") and time.time() < float(token.get("obtained_at", 0)) + int(token.get("expires_in", 3600)) - 120:
        return token["access_token"]
    payload = {"client_id": client["client_id"], "client_secret": client.get("client_secret", ""),
               "refresh_token": token["refresh_token"], "grant_type": "refresh_token"}
    request = urllib.request.Request(client.get("token_uri") or "https://oauth2.googleapis.com/token",
        data=urllib.parse.urlencode(payload).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=60) as response:
        refreshed = json.loads(response.read().decode())
    token.update(refreshed); token["obtained_at"] = time.time()
    GOOGLE_OAUTH_TOKEN_PATH.write_text(json.dumps(token, ensure_ascii=False), encoding="utf-8")
    return token["access_token"]


def _google_sheet_values(sheet_name: str, spreadsheet_id: str = SUPPLIER_EDR_SHEET_ID,
                         columns: str = "A:O") -> list[list]:
    cell_range = urllib.parse.quote(f"'{sheet_name}'!{columns}", safe="")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{cell_range}?majorDimension=ROWS"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {_google_access_token()}", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode()).get("values", [])


def normalize_manager_name(value: str) -> str:
    """Normalize a person's name for identity-safe exact text matching."""
    return " ".join(re.sub(r"[’'`\-]+", " ", (value or "").casefold()).split())


def sync_current_supplier_manager(con: sqlite3.Connection, supplier_code: str, manager_name: str,
                                  source: str = "ЄДР", observed_at: str | None = None) -> dict:
    """Keep one current manager while preserving every observed previous manager."""
    code = re.sub(r"\D", "", supplier_code or "")
    name = " ".join((manager_name or "").split())
    normalized = normalize_manager_name(name)
    observed = observed_at or now_iso()
    current = con.execute("""SELECT id,manager_name,normalized_name,source,updated_at FROM supplier_managers
      WHERE supplier_code=? AND is_current=1 ORDER BY id DESC LIMIT 1""", (code,)).fetchone()
    if not code:
        return {"changed": False, "manager_id": None, "reason": "missing_supplier_code"}
    incoming_is_edr = source.startswith("Google Sheets") or source == "ЄДР"
    current_is_manual = bool(current and str(current["source"] or "").startswith("Підтверджено УО"))
    if current and incoming_is_edr and current_is_manual:
        current_at = _parse_prozorro_date(current["updated_at"])
        incoming_at = _parse_prozorro_date(observed)
        if current["normalized_name"] == normalized or (current_at and incoming_at and current_at >= incoming_at):
            return {"changed": False, "manager_id": current["id"], "reason": "newer_manual_value_preserved"}
    if current and current["normalized_name"] == normalized and normalized:
        con.execute("""UPDATE supplier_managers SET manager_name=?,source=?,updated_at=? WHERE id=?""",
                    (name, source, observed, current["id"]))
        return {"changed": False, "manager_id": current["id"], "reason": "unchanged"}
    if current:
        con.execute("""UPDATE supplier_managers SET is_current=0,valid_to=?,updated_at=? WHERE id=?""",
                    (observed, observed, current["id"]))
    if not normalized:
        return {"changed": bool(current), "manager_id": None, "previous_manager_id": current["id"] if current else None,
                "reason": "manager_removed" if current else "missing_manager"}
    cursor = con.execute("""INSERT INTO supplier_managers
      (supplier_code,manager_name,normalized_name,valid_from,valid_to,is_current,source,created_at,updated_at)
      VALUES (?,?,?,?,NULL,1,?,?,?)""", (code, name, normalized, observed, source, observed, observed))
    return {"changed": True, "manager_id": cursor.lastrowid,
            "previous_manager_id": current["id"] if current else None, "reason": "manager_changed" if current else "manager_created"}


def refresh_current_submission_nazk_controls(con: sqlite3.Connection, supplier_code: str) -> int:
    """Refresh only actionable submissions after the authoritative EDR manager changes.

    Historical/closed submissions are intentionally excluded: an old submission result must
    never be transferred to another manager or used to close a future submission.
    """
    code = re.sub(r"\D", "", supplier_code or "")
    if not code:
        return 0
    rows = con.execute("""SELECT DISTINCT s.id
      FROM submissions s
      JOIN qualifications q ON q.submission_id=s.id
      JOIN frameworks f ON f.id=s.framework_id
      WHERE DIGITS(s.supplier_code)=? AND q.status='active'
        AND LOWER(COALESCE(f.status,''))='active'
        AND (COALESCE(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),'')=''
          OR date(substr(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),1,10))>=date('now'))""",
      (code,)).fetchall()
    for row in rows:
        ensure_submission_nazk_control(con, row[0])
    return len(rows)


def sync_supplier_managers_from_edr() -> dict:
    """Idempotently seed/update manager history from the current EDR directory."""
    created = changed = unchanged = removed = missing = 0
    with db() as con:
        profiles = con.execute("""SELECT supplier_code,manager_name,source_sheet,synced_at
          FROM supplier_edr_profiles ORDER BY supplier_code""").fetchall()
        for profile in profiles:
            result = sync_current_supplier_manager(
                con, profile["supplier_code"], profile["manager_name"],
                f"Google Sheets: {profile['source_sheet'] or 'ЄДР'}", profile["synced_at"] or now_iso())
            reason = result["reason"]
            if reason == "manager_created": created += 1
            elif reason == "manager_changed": changed += 1
            elif reason == "manager_removed": removed += 1
            elif reason == "missing_manager": missing += 1
            elif reason == "unchanged": unchanged += 1
    return {"profiles": len(profiles), "created": created, "changed": changed,
            "removed": removed, "missing": missing, "unchanged": unchanged}


def supplier_edr_sync_status() -> dict:
    with db() as con:
        total = int(con.execute("SELECT COUNT(*) FROM supplier_edr_profiles").fetchone()[0])
        last = con.execute("""SELECT started_at,finished_at,status,processed,inserted,updated,error
          FROM supplier_edr_sync_log ORDER BY id DESC LIMIT 1""").fetchone()
    return {"total": total, "last": dict(last) if last else None, "oauth": google_oauth_status(),
            "source_url": f"https://docs.google.com/spreadsheets/d/{SUPPLIER_EDR_SHEET_ID}/edit",
            "state": dict(SUPPLIER_EDR_SYNC_STATE)}


def _supplier_edr_rows(sheet_name: str, gid: str) -> list[dict]:
    values = _google_sheet_values(sheet_name)
    if not values:
        return []
    headers = [(value or "").lstrip("\ufeff").strip() for value in values[0]]
    rows = []
    for row_number, values_row in enumerate(values[1:], start=2):
        clean = {header: (str(values_row[index]).strip() if index < len(values_row) else "")
                 for index, header in enumerate(headers)}
        code = re.sub(r"\D", "", clean.get("Код ЄДРПОУ", ""))
        if not code:
            continue
        rows.append({
            "supplier_code": code,
            "full_name": clean.get("Повна назва з ЄДР", ""),
            "short_name": clean.get("Скорочена назва з ЄДР", ""),
            "manager_name": clean.get("ПІБ для перевірки", ""),
            "edr_status": clean.get("Статус в реєстрі (ЄДР)", ""),
            "edr_checked_at": clean.get("Дата перевірки ЄДР", ""),
            "source_sheet": sheet_name,
            "source_row": row_number,
        })
    return rows


def supplier_edr_sync_worker() -> None:
    started_at = now_iso()
    log_id = None
    try:
        SUPPLIER_EDR_SYNC_STATE.update(running=True, message="Завантаження вкладок ФОП та ЮО…",
                                       started_at=started_at, updated_at=None, processed=0,
                                       inserted=0, updated=0, error=None)
        with db() as con:
            log_id = con.execute("INSERT INTO supplier_edr_sync_log(started_at,status) VALUES (?,?)",
                                 (started_at, "running")).lastrowid
        source_rows = []
        for sheet_name, gid in SUPPLIER_EDR_SHEETS.items():
            SUPPLIER_EDR_SYNC_STATE["message"] = f"Завантаження вкладки {sheet_name}…"
            source_rows.extend(_supplier_edr_rows(sheet_name, gid))
        synced_at = now_iso()
        inserted = updated = 0
        with db() as con:
            existing = {row[0] for row in con.execute("SELECT supplier_code FROM supplier_edr_profiles")}
            for item in source_rows:
                if item["supplier_code"] in existing:
                    updated += 1
                else:
                    inserted += 1
                    existing.add(item["supplier_code"])
                con.execute("""INSERT INTO supplier_edr_profiles
                  (supplier_code,full_name,short_name,manager_name,edr_status,edr_checked_at,
                   source_sheet,source_row,synced_at) VALUES (?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(supplier_code) DO UPDATE SET
                    full_name=CASE WHEN excluded.full_name<>'' THEN excluded.full_name ELSE supplier_edr_profiles.full_name END,
                    short_name=CASE WHEN excluded.short_name<>'' THEN excluded.short_name ELSE supplier_edr_profiles.short_name END,
                    manager_name=CASE WHEN excluded.manager_name<>'' THEN excluded.manager_name ELSE supplier_edr_profiles.manager_name END,
                    edr_status=CASE WHEN excluded.edr_status<>'' THEN excluded.edr_status ELSE supplier_edr_profiles.edr_status END,
                    edr_checked_at=CASE WHEN excluded.edr_checked_at<>'' THEN excluded.edr_checked_at ELSE supplier_edr_profiles.edr_checked_at END,
                    source_sheet=excluded.source_sheet,source_row=excluded.source_row,synced_at=excluded.synced_at""",
                  (item["supplier_code"], item["full_name"], item["short_name"], item["manager_name"],
                   item["edr_status"], item["edr_checked_at"], item["source_sheet"], item["source_row"], synced_at))
                effective_manager = con.execute("SELECT manager_name FROM supplier_edr_profiles WHERE supplier_code=?",
                                                (item["supplier_code"],)).fetchone()[0]
                manager_result = sync_current_supplier_manager(
                    con, item["supplier_code"], effective_manager,
                    f"Google Sheets: {item['source_sheet']}", synced_at)
                if manager_result.get("changed"):
                    refresh_current_submission_nazk_controls(con, item["supplier_code"])
            con.execute("""UPDATE supplier_edr_sync_log SET finished_at=?,status='completed',processed=?,inserted=?,updated=?
              WHERE id=?""", (synced_at, len(source_rows), inserted, updated, log_id))
        SUPPLIER_EDR_SYNC_STATE.update(running=False,
            message=f"Синхронізовано {len(source_rows):,} записів ЄДР".replace(",", " "),
            updated_at=synced_at, processed=len(source_rows), inserted=inserted, updated=updated, error=None)
    except Exception as exc:
        finished_at = now_iso()
        if log_id:
            with db() as con:
                con.execute("UPDATE supplier_edr_sync_log SET finished_at=?,status='failed',error=? WHERE id=?",
                            (finished_at, str(exc), log_id))
        SUPPLIER_EDR_SYNC_STATE.update(running=False, message=f"Помилка синхронізації ЄДР: {exc}",
                                       updated_at=finished_at, error=str(exc))


def supplier_nazk_review_sync_status() -> dict:
    with db() as con:
        total = int(con.execute("SELECT COUNT(*) FROM supplier_nazk_reviews").fetchone()[0])
        last = con.execute("""SELECT started_at,finished_at,status,processed,inserted,updated,error
          FROM supplier_nazk_review_sync_log ORDER BY id DESC LIMIT 1""").fetchone()
    return {"total": total, "last": dict(last) if last else None, "oauth": google_oauth_status(),
            "source_url": f"https://docs.google.com/spreadsheets/d/{SUPPLIER_NAZK_REVIEW_SHEET_ID}/edit",
            "state": dict(SUPPLIER_NAZK_REVIEW_SYNC_STATE)}


def _supplier_nazk_review_rows() -> list[dict]:
    values = _google_sheet_values(SUPPLIER_NAZK_REVIEW_SHEET, SUPPLIER_NAZK_REVIEW_SHEET_ID, "A:J")
    if not values:
        return []
    headers = [(str(value) if value is not None else "").lstrip("\ufeff").strip() for value in values[0]]
    rows = []
    for row_number, values_row in enumerate(values[1:], start=2):
        clean = {header: (str(values_row[index]).strip() if index < len(values_row) else "")
                 for index, header in enumerate(headers)}
        code = re.sub(r"\D", "", clean.get("Код ЄДРПОУ", ""))
        if not code:
            continue
        rows.append({"supplier_code": code, "supplier_name": clean.get("Найменування", ""),
          "manager_name": clean.get("ПІБ для перевірки", ""),
          "decision_date": clean.get("НАЗК_Дата_Рішення", ""),
          "case_number": clean.get("НАЗК_Номер_Справи", ""),
          "result": clean.get("Результати перевірки", "").strip().casefold(),
          "evidence_url": clean.get("Посилання на документ підтвердження", ""),
          "comment": clean.get("Коментар", ""), "checked_at": clean.get("Дата перевірки", ""),
          "officer": clean.get("УО", ""), "source_row": row_number})
    return rows


def supplier_nazk_review_sync_worker() -> None:
    started_at = now_iso(); log_id = None
    try:
        SUPPLIER_NAZK_REVIEW_SYNC_STATE.update(running=True, message="Завантаження перевірок НАЗК…",
            started_at=started_at, updated_at=None, processed=0, inserted=0, updated=0, error=None)
        with db() as con:
            log_id = con.execute("INSERT INTO supplier_nazk_review_sync_log(started_at,status) VALUES (?,?)",
                                 (started_at, "running")).lastrowid
        source_rows = _supplier_nazk_review_rows()
        if not source_rows:
            raise ValueError("У вкладці nazk_data не знайдено записів з кодом ЄДРПОУ")
        synced_at = now_iso(); inserted = updated = 0
        with db() as con:
            existing = {row[0] for row in con.execute("SELECT supplier_code FROM supplier_nazk_reviews")}
            con.execute("DELETE FROM supplier_nazk_reviews")
            for item in source_rows:
                updated += item["supplier_code"] in existing
                inserted += item["supplier_code"] not in existing
                con.execute("""INSERT OR REPLACE INTO supplier_nazk_reviews
                  (supplier_code,supplier_name,manager_name,decision_date,case_number,result,evidence_url,
                   comment,checked_at,officer,source_row,synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (item["supplier_code"],item["supplier_name"],item["manager_name"],item["decision_date"],
                   item["case_number"],item["result"],item["evidence_url"],item["comment"],item["checked_at"],
                   item["officer"],item["source_row"],synced_at))
            con.execute("""UPDATE supplier_nazk_review_sync_log SET finished_at=?,status='completed',
              processed=?,inserted=?,updated=? WHERE id=?""", (synced_at,len(source_rows),inserted,updated,log_id))
        SUPPLIER_NAZK_REVIEW_SYNC_STATE.update(running=False,
          message=f"Синхронізовано {len(source_rows)} перевірок НАЗК", updated_at=synced_at,
          processed=len(source_rows), inserted=inserted, updated=updated, error=None)
    except Exception as exc:
        finished_at = now_iso()
        if log_id:
            with db() as con:
                con.execute("UPDATE supplier_nazk_review_sync_log SET finished_at=?,status='failed',error=? WHERE id=?",
                            (finished_at,str(exc),log_id))
        SUPPLIER_NAZK_REVIEW_SYNC_STATE.update(running=False,message=f"Помилка синхронізації перевірок НАЗК: {exc}",
                                               updated_at=finished_at,error=str(exc))


def list_qualified_suppliers(params: dict) -> dict:
    """Return registered suppliers and applicants that have not entered a register yet."""
    search = params.get("search", [""])[0].strip().casefold()
    status = params.get("status", [""])[0].strip()
    risk = params.get("risk", [""])[0].strip()
    dk_code = params.get("dk_code", [""])[0].strip()
    page = max(1, int(params.get("page", ["1"])[0] or 1))
    size = min(200, max(10, int(params.get("size", ["100"])[0] or 100)))
    with db() as match_con:
        amcu_match_codes = {re.sub(r"\D", "", row[0] or "") for row in match_con.execute(
            "SELECT DISTINCT offender_code FROM amcu_registry WHERE offender_code<>''")}
        nazk_names_all = {" ".join(re.sub(r"[’'`\-]+", " ", (row[0] or "").casefold()).split()) for row in match_con.execute(
            "SELECT DISTINCT full_name FROM nazk_registry WHERE full_name<>''")}
        nazk_match_codes = {row[0] for row in match_con.execute(
            "SELECT supplier_code,manager_name FROM supplier_edr_profiles WHERE COALESCE(manager_name,'')<>''")
            if " ".join(re.sub(r"[’'`\-]+", " ", (row[1] or "").casefold()).split()) in nazk_names_all}
        nazk_match_codes.update(row[0] for row in match_con.execute("""SELECT DISTINCT s.supplier_code,af.manager_name
            FROM submissions s JOIN application_fields af ON af.submission_id=s.id
            WHERE COALESCE(af.manager_name,'')<>''""")
            if " ".join(re.sub(r"[’'`\-]+", " ", (row[1] or "").casefold()).split()) in nazk_names_all)
        nazk_reviews = {row[0]: dict(row) for row in match_con.execute(
            "SELECT * FROM supplier_nazk_reviews")}
        current_managers = {row[0]: " ".join(re.sub(r"[’'`\-]+", " ", (row[1] or "").casefold()).split())
                            for row in match_con.execute("SELECT supplier_code,manager_name FROM supplier_edr_profiles")}
        nazk_match_codes.difference_update(nazk_reviews)
        nazk_match_codes.update(code for code, review in nazk_reviews.items()
            if review.get("result") in {"підтверджено", "на запит", "можливо"}
            and current_managers.get(code)
            and current_managers.get(code) == " ".join(re.sub(r"[’'`\-]+", " ", (review.get("manager_name") or "").casefold()).split()))
    where, args = ["1=1"], []
    if search:
        where.append("(INSTR(CASEFOLD(supplier_code),?)>0 OR INSTR(CASEFOLD(supplier_name),?)>0)")
        args.extend([search, search])
    if status in {"active", "terminated", "suspended"}:
        field = {"active": "active_count", "terminated": "inactive_count", "suspended": "suspended_count"}[status]
        where.append(f"{field}>0")
    elif status == "not_registered":
        where.append("registry_state='not_registered'")
    if risk == "amcu":
        codes = sorted(code for code in amcu_match_codes if code)
        where.append("DIGITS(combined.supplier_code) IN (" + ",".join("?" for _ in codes) + ")" if codes else "0=1")
        args.extend(codes)
    elif risk == "nazk":
        codes = sorted(code for code in nazk_match_codes if code)
        where.append("combined.supplier_code IN (" + ",".join("?" for _ in codes) + ")" if codes else "0=1")
        args.extend(codes)
    clause = " AND ".join(where)
    if dk_code:
        # Aggregate inside the selected CPV first.  Filtering the already
        # materialized supplier summary would mix a CPV from one qualification
        # with a status from another qualification of the same supplier.
        source = """
          WITH applicants AS (
            SELECT s.supplier_code,
              MAX(COALESCE(NULLIF(s.supplier_name,''),'Назву не отримано')) supplier_name,
              COUNT(*) applications_count, MAX(s.date_published) last_application,
              GROUP_CONCAT(DISTINCT NULLIF(f.dk_code,'')) application_dk_codes
            FROM submissions s LEFT JOIN frameworks f ON f.id=s.framework_id
            WHERE COALESCE(s.supplier_code,'')<>'' AND f.dk_code=? GROUP BY s.supplier_code
          ), scoped_registry AS (
            SELECT rc.supplier_code,
              MAX(COALESCE(NULLIF(s.supplier_name,''),NULLIF(r.supplier_name,''),'Назву не отримано')) supplier_name,
              COUNT(DISTINCT rc.id) qualifications_count,
              SUM(CASE WHEN rc.status='active' AND LOWER(COALESCE(f.status,''))='active'
                AND (COALESCE(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),'')=''
                  OR date(substr(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),1,10))>=date('now'))
                THEN 1 ELSE 0 END) active_count,
              SUM(CASE WHEN rc.status='terminated' OR (rc.status='active' AND NOT (
                LOWER(COALESCE(f.status,''))='active' AND
                (COALESCE(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),'')=''
                  OR date(substr(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),1,10))>=date('now'))))
                THEN 1 ELSE 0 END) inactive_count,
              SUM(CASE WHEN rc.status='suspended' THEN 1 ELSE 0 END) suspended_count,
              COUNT(DISTINCT rc.framework_id) frameworks_count,
              GROUP_CONCAT(DISTINCT NULLIF(f.dk_code,'')) dk_codes,
              MAX(COALESCE(NULLIF(json_extract(rc.raw_json,'$.dateModified'),''),
                  NULLIF(json_extract(rc.raw_json,'$.date'),''),q.decision_date,rc.synced_at)) last_qualification
            FROM registry_contracts rc
            LEFT JOIN qualifications q ON q.id=rc.qualification_id
            LEFT JOIN submissions s ON s.id=q.submission_id
            LEFT JOIN frameworks f ON f.id=rc.framework_id
            LEFT JOIN supplier_registry_summary r ON r.supplier_code=rc.supplier_code
            WHERE COALESCE(rc.supplier_code,'')<>'' AND f.dk_code=? GROUP BY rc.supplier_code
          ), combined AS (
            SELECT r.supplier_code,r.supplier_name,r.qualifications_count,r.active_count,
              r.inactive_count,r.suspended_count,r.frameworks_count,r.dk_codes,r.last_qualification,
              COALESCE(a.applications_count,0) applications_count,COALESCE(a.last_application,'') last_application,
              'registered' registry_state
            FROM scoped_registry r LEFT JOIN applicants a ON a.supplier_code=r.supplier_code
            UNION ALL
            SELECT a.supplier_code,a.supplier_name,0,0,0,0,0,
              COALESCE(a.application_dk_codes,''),'',a.applications_count,a.last_application,'not_registered'
            FROM applicants a LEFT JOIN scoped_registry r ON r.supplier_code=a.supplier_code
            WHERE r.supplier_code IS NULL
          )
        """
        source_args = [dk_code, dk_code]
    else:
        source = """
      WITH applicants AS (
        SELECT s.supplier_code,
          MAX(COALESCE(NULLIF(s.supplier_name,''),'Назву не отримано')) supplier_name,
          COUNT(*) applications_count, MAX(s.date_published) last_application,
          GROUP_CONCAT(DISTINCT NULLIF(f.dk_code,'')) application_dk_codes
        FROM submissions s LEFT JOIN frameworks f ON f.id=s.framework_id
        WHERE COALESCE(s.supplier_code,'')<>'' GROUP BY s.supplier_code
      ), combined AS (
        SELECT r.supplier_code,r.supplier_name,r.qualifications_count,r.active_count,
          r.inactive_count,r.suspended_count,r.frameworks_count,r.dk_codes,r.last_qualification,
          COALESCE(a.applications_count,0) applications_count,COALESCE(a.last_application,'') last_application,
          'registered' registry_state
        FROM supplier_registry_summary r LEFT JOIN applicants a ON a.supplier_code=r.supplier_code
        UNION ALL
        SELECT a.supplier_code,a.supplier_name,0,0,0,0,0,
          COALESCE(a.application_dk_codes,''),'',a.applications_count,a.last_application,'not_registered'
        FROM applicants a LEFT JOIN supplier_registry_summary r ON r.supplier_code=a.supplier_code
        WHERE r.supplier_code IS NULL
      )
        """
        source_args = []
    query_args = source_args + args
    with db() as con:
        if not con.execute("SELECT 1 FROM supplier_registry_summary LIMIT 1").fetchone():
            return {"items": [], "total": 0, "registered_total": 0, "not_registered": 0,
                    "active": 0, "page": 1, "size": size, "pages": 0, "building": True}
        total = con.execute(source + f" SELECT COUNT(*) FROM combined WHERE {clause}", query_args).fetchone()[0]
        active_total = con.execute(source + f" SELECT COALESCE(SUM(active_count),0) FROM combined WHERE {clause}", query_args).fetchone()[0]
        registered_total = con.execute(
            source + f" SELECT COUNT(*) FROM combined WHERE {clause} AND registry_state='registered'", query_args
        ).fetchone()[0]
        not_registered = con.execute(
            source + f" SELECT COUNT(*) FROM combined WHERE {clause} AND registry_state='not_registered'", query_args
        ).fetchone()[0]
        all_supplier_codes = {row[0] for row in con.execute("SELECT supplier_code FROM supplier_registry_summary")}
        all_supplier_codes.update(row[0] for row in con.execute("SELECT DISTINCT supplier_code FROM submissions WHERE COALESCE(supplier_code,'')<>''"))
        all_supplier_digits = {re.sub(r"\D", "", code or "") for code in all_supplier_codes}
        amcu_total = len(all_supplier_digits & amcu_match_codes)
        nazk_total = len(all_supplier_codes & nazk_match_codes)
        rows = con.execute(source + f""" SELECT supplier_code code,supplier_name name,qualifications_count,
          active_count,inactive_count,suspended_count,frameworks_count,dk_codes,last_qualification,
          applications_count,last_application,registry_state
          FROM combined WHERE {clause}
          ORDER BY CASE registry_state WHEN 'registered' THEN 0 ELSE 1 END,
            CASE WHEN active_count>0 THEN 0 ELSE 1 END,supplier_code LIMIT ? OFFSET ?""",
          (*query_args, size, (page - 1) * size)).fetchall()
        amcu_codes = {re.sub(r"\D", "", row[0] or "") for row in con.execute(
            "SELECT DISTINCT offender_code FROM amcu_registry WHERE offender_code<>''"
        )}
        nazk_names = {" ".join(re.sub(r"[’'`\-]+", " ", (row[0] or "").casefold()).split()) for row in con.execute(
            "SELECT DISTINCT full_name FROM nazk_registry WHERE full_name<>''"
        )}
        supplier_codes = [row["code"] for row in rows]
        manager_matches = {}
        edr_profiles = {}
        latest_registry_events = {}
        if supplier_codes:
            placeholders = ",".join("?" for _ in supplier_codes)
            for event in con.execute(f"""SELECT supplier_code,status,
              COALESCE(NULLIF(json_extract(raw_json,'$.dateModified'),''),
                       NULLIF(json_extract(raw_json,'$.date'),''),synced_at) event_date
              FROM registry_contracts WHERE supplier_code IN ({placeholders})
              ORDER BY event_date DESC""", supplier_codes):
                if event["supplier_code"] not in latest_registry_events:
                    latest_registry_events[event["supplier_code"]] = {"status": event["status"], "date": event["event_date"]}
            for profile in con.execute(f"""SELECT supplier_code,full_name,short_name,manager_name,
              edr_status,edr_checked_at,source_sheet,source_row,synced_at
              FROM supplier_edr_profiles WHERE supplier_code IN ({placeholders})""", supplier_codes):
                edr_profiles[profile["supplier_code"]] = dict(profile)
                normalized = " ".join(re.sub(r"[’'`\-]+", " ", (profile["manager_name"] or "").casefold()).split())
                if normalized and normalized in nazk_names:
                    manager_matches[profile["supplier_code"]] = profile["manager_name"]
            for code, manager_name in con.execute(f"""SELECT s.supplier_code,af.manager_name
              FROM submissions s JOIN application_fields af ON af.submission_id=s.id
              WHERE s.supplier_code IN ({placeholders}) AND COALESCE(af.manager_name,'')<>''
              ORDER BY s.date_published DESC""", supplier_codes):
                normalized = " ".join(re.sub(r"[’'`\-]+", " ", (manager_name or "").casefold()).split())
                if normalized and normalized in nazk_names and code not in manager_matches:
                    manager_matches[code] = manager_name
        application_nazk_states = {
            supplier_code: {"state": "not_required", "can_approve": True,
                            "required": False, "supplier_code": supplier_code,
                            "submission_id": ""}
            for supplier_code in supplier_codes
        }
        open_supplier_nazk_workflows = {}
        latest_supplier_nazk_checks = {}
        if supplier_codes:
            placeholders = ",".join("?" for _ in supplier_codes)
            for check in con.execute(f"""SELECT sc.id,sc.supplier_code,sc.manager_name,
              sc.workflow_status,sc.result,sc.started_at,sc.completed_at,sc.is_legacy
              FROM supplier_nazk_checks sc
              JOIN supplier_managers sm ON sm.id=sc.manager_id AND sm.is_current=1
              WHERE sc.supplier_code IN ({placeholders})
              ORDER BY sc.supplier_code,COALESCE(sc.completed_at,sc.updated_at,sc.started_at) DESC,sc.id DESC""",
              supplier_codes):
                if check["supplier_code"] not in latest_supplier_nazk_checks:
                    latest_supplier_nazk_checks[check["supplier_code"]] = dict(check)
            for workflow in con.execute(f"""SELECT sc.id,sc.supplier_code,sc.manager_name,
              sc.workflow_status,sc.started_at,sc.is_legacy
              FROM supplier_nazk_checks sc
              JOIN supplier_registry_summary srs ON srs.supplier_code=sc.supplier_code
              JOIN supplier_managers sm ON sm.id=sc.manager_id AND sm.is_current=1
              WHERE sc.supplier_code IN ({placeholders})
                AND sc.workflow_status IN ('needs_review','request_to_supplier','request_to_nazk','waiting_response')
                AND srs.active_count>0
              ORDER BY sc.supplier_code,COALESCE(sc.started_at,sc.created_at) DESC,sc.id DESC""",
              supplier_codes):
                if workflow["supplier_code"] not in open_supplier_nazk_workflows:
                    open_supplier_nazk_workflows[workflow["supplier_code"]] = dict(workflow)
            relevant_by_supplier = {}
            for submission in con.execute(f"""SELECT s.id,s.supplier_code,s.date_published,
              COALESCE(af.manager_name,'') manager_name,
              COALESCE(ctrl.nazk_certificate_required,0) control_required
              FROM submissions s
              LEFT JOIN qualifications q ON q.id=s.qualification_id
              JOIN frameworks f ON f.id=s.framework_id
              LEFT JOIN application_fields af ON af.submission_id=s.id
              LEFT JOIN submission_nazk_controls ctrl ON ctrl.submission_id=s.id
              WHERE s.supplier_code IN ({placeholders})
                AND ctrl.id IS NOT NULL
                AND ctrl.nazk_certificate_required=1
                AND LOWER(COALESCE(f.status,'')) IN ('active','active.tendering','active.enquiries')
                AND COALESCE(
                  SUBSTR(JSON_EXTRACT(f.raw_json,'$.qualificationPeriod.endDate'),1,10),
                  SUBSTR(JSON_EXTRACT(f.raw_json,'$.period.endDate'),1,10),
                  '9999-12-31')>=DATE('now')
                AND (
                  LOWER(COALESCE(q.status,'pending'))='pending'
                  OR (LOWER(COALESCE(q.status,''))='active' AND EXISTS (
                    SELECT 1 FROM registry_contracts rc
                    WHERE rc.qualification_id=q.id AND LOWER(COALESCE(rc.status,''))='active'
                  ))
                )
              ORDER BY s.supplier_code,
                COALESCE(NULLIF(s.date_published,''),s.synced_at) DESC,s.id DESC""", supplier_codes):
                code = submission["supplier_code"]
                if code in relevant_by_supplier:
                    continue
                relevant_by_supplier[code] = submission
            for code, submission in relevant_by_supplier.items():
                state = get_submission_nazk_state(con, submission["id"], nazk_names)
                application_nazk_states[code] = {
                    **state, "date_published": submission["date_published"] or ""
                }
    items = [dict(row) for row in rows]
    for item in items:
        code = re.sub(r"\D", "", item.get("code") or "")
        profile = edr_profiles.get(code) or edr_profiles.get(item.get("code")) or {}
        item["edr_profile"] = profile
        item["last_registry_event"] = latest_registry_events.get(item.get("code"), {})
        item["amcu_match"] = bool(code and code in amcu_codes)
        item["nazk_match"] = item.get("code") in manager_matches
        item["nazk_manager_name"] = manager_matches.get(item.get("code"), "")
        item["nazk_application_state"] = application_nazk_states.get(
            item.get("code"), {"state": "not_required", "can_approve": True}
        )
        item["nazk_supplier_workflow"] = open_supplier_nazk_workflows.get(item.get("code"), {})
        latest_supplier_check = latest_supplier_nazk_checks.get(item.get("code"), {})
        item["nazk_supplier_check"] = latest_supplier_check
        review = nazk_reviews.get(item.get("code"))
        item["nazk_review"] = review or {}
        if review:
            current_manager = " ".join(re.sub(r"[’'`\-]+", " ", ((item.get("edr_profile") or {}).get("manager_name") or "").casefold()).split())
            review_manager = " ".join(re.sub(r"[’'`\-]+", " ", (review.get("manager_name") or "").casefold()).split())
            review_is_current = bool(current_manager and review_manager and current_manager == review_manager)
            item["nazk_review_is_current"] = review_is_current
            item["nazk_match"] = review_is_current and review.get("result") in {"підтверджено", "на запит", "можливо"}
            item["nazk_manager_name"] = review.get("manager_name") or item["nazk_manager_name"]
        item["nazk_presentation_state"] = get_supplier_nazk_presentation_state(
            item["nazk_application_state"].get("state"),
            item["nazk_supplier_workflow"].get("workflow_status"),
            registry_match=bool(item["nazk_match"]),
            legacy_result=(latest_supplier_check.get("result")
              if latest_supplier_check.get("workflow_status") == "completed"
              else ((review or {}).get("result") if item.get("nazk_review_is_current", not review) else "")),
        )
    return {"items": items, "total": total,
            "registered_total": registered_total, "not_registered": not_registered, "active": active_total,
            "amcu_total": amcu_total, "nazk_total": nazk_total,
            "page": page, "size": size, "pages": (total + size - 1) // size}


def supplier_profile(supplier_code: str) -> dict:
    """Full local PQM/Bids/registry card for one supplier."""
    code = re.sub(r"\D", "", urllib.parse.unquote(supplier_code or ""))
    if not code:
        raise KeyError(supplier_code)
    with db() as con:
        summary = con.execute("SELECT * FROM supplier_registry_summary WHERE DIGITS(supplier_code)=?", (code,)).fetchone()
        profile = con.execute("SELECT * FROM supplier_edr_profiles WHERE DIGITS(supplier_code)=?", (code,)).fetchone()
        current_manager_row = con.execute("""SELECT manager_name,source,valid_from,updated_at
          FROM supplier_managers WHERE DIGITS(supplier_code)=? AND is_current=1
          ORDER BY updated_at DESC,id DESC LIMIT 1""", (code,)).fetchone()
        nazk_review = con.execute("SELECT * FROM supplier_nazk_reviews WHERE DIGITS(supplier_code)=?", (code,)).fetchone()
        nazk_check_history = [dict(row) for row in con.execute("""SELECT
          ctrl.submission_id,ctrl.manager_name,ctrl.checked_at,ctrl.checked_by,ctrl.comment,
          chk.id check_id,chk.workflow_status,chk.result,chk.evidence_date,
          doc.title document_title,doc.url document_url,doc.prozorro_document_id,
          s.supplier_name,s.date_published,COALESCE(NULLIF(f.pretty_id,''),f.id) framework_id
          FROM submission_nazk_controls ctrl
          JOIN supplier_nazk_checks chk ON chk.id=ctrl.supplier_nazk_check_id
          JOIN submissions s ON s.id=ctrl.submission_id
          LEFT JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN supplier_nazk_check_documents doc ON doc.check_id=chk.id
            AND doc.submission_id=ctrl.submission_id
            AND ((COALESCE(doc.prozorro_document_id,'')<>'' AND doc.prozorro_document_id=ctrl.selected_document_id)
              OR (COALESCE(doc.url,'')<>'' AND doc.url=ctrl.selected_document_url))
          WHERE DIGITS(ctrl.supplier_code)=? AND chk.workflow_status='completed'
            AND chk.result IN ('refuted','confirmed')
          ORDER BY COALESCE(ctrl.checked_at,chk.completed_at,chk.created_at) DESC,chk.id DESC""", (code,))]
        supplier_nazk_checks = [dict(row) for row in con.execute("""SELECT
          chk.id,chk.manager_name,chk.workflow_status,chk.result,chk.started_at,chk.completed_at,
          chk.evidence_date,chk.comment,chk.is_legacy,chk.created_by,chk.updated_by,
          doc.title document_title,doc.url document_url,doc.document_date
          FROM supplier_nazk_checks chk
          LEFT JOIN supplier_nazk_check_documents doc ON doc.id=(
            SELECT d.id FROM supplier_nazk_check_documents d WHERE d.check_id=chk.id
            ORDER BY d.created_at DESC,d.id DESC LIMIT 1)
          WHERE DIGITS(chk.supplier_code)=?
          ORDER BY COALESCE(chk.completed_at,chk.updated_at,chk.started_at) DESC,chk.id DESC""", (code,))]
        supplier_nazk_workflow = next((row for row in supplier_nazk_checks
          if row["workflow_status"] in ("needs_review","request_to_supplier","request_to_nazk","waiting_response")), {})
        qualifications = [dict(row) for row in con.execute("""WITH contract_events AS (
          SELECT rc.id,CASE WHEN rc.status='active' AND NOT (
              LOWER(COALESCE(f.status,''))='active' AND
              (COALESCE(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),'')=''
                OR date(substr(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),1,10))>=date('now')))
            THEN 'expired' ELSE rc.status END status,COALESCE(NULLIF(f.pretty_id,''),f.id) framework_id,
            f.title framework_title,f.dk_code,COALESCE(fo.marketplace_url,'') marketplace_url,
            COALESCE(
              (SELECT COALESCE(NULLIF(json_extract(doc.value,'$.datePublished'),''),
                               NULLIF(json_extract(doc.value,'$.dateModified'),''))
                 FROM json_each(COALESCE(rc.raw_json,'{}'),'$.milestones') milestone
                 JOIN json_each(milestone.value,'$.documents') doc
                WHERE COALESCE(NULLIF(json_extract(doc.value,'$.datePublished'),''),
                               NULLIF(json_extract(doc.value,'$.dateModified'),'')) IS NOT NULL
                ORDER BY COALESCE(NULLIF(json_extract(doc.value,'$.datePublished'),''),
                                  NULLIF(json_extract(doc.value,'$.dateModified'),'')) DESC LIMIT 1),
              (SELECT NULLIF(json_extract(milestone.value,'$.dateModified'),'')
                 FROM json_each(COALESCE(rc.raw_json,'{}'),'$.milestones') milestone
                WHERE NULLIF(json_extract(milestone.value,'$.dateModified'),'') IS NOT NULL
                ORDER BY json_extract(milestone.value,'$.dateModified') DESC LIMIT 1),
              NULLIF(json_extract(rc.raw_json,'$.date'),''),NULLIF(q.decision_date,'')
            ) event_date,
            CASE WHEN rc.status='terminated' THEN 'Рішення про виключення'
                 WHEN rc.status='active' THEN 'Рішення про включення'
                 ELSE 'Рішення / зміна статусу' END event_label
          FROM registry_contracts rc LEFT JOIN frameworks f ON f.id=rc.framework_id
          LEFT JOIN framework_officers fo ON fo.framework_id=rc.framework_id
          LEFT JOIN qualifications q ON q.id=rc.qualification_id
          WHERE DIGITS(rc.supplier_code)=?), ranked AS (
          SELECT contract_events.*,ROW_NUMBER() OVER (PARTITION BY framework_id
            ORDER BY COALESCE(event_date,'') DESC,id DESC) rn FROM contract_events)
          SELECT id,status,framework_id,framework_title,dk_code,marketplace_url,event_date,event_label FROM ranked
          WHERE rn=1 ORDER BY COALESCE(event_date,'') DESC LIMIT 200""", (code,))]
        amcu = [dict(row) for row in con.execute("""SELECT offender_name,offender_code,decision_no,
          decision_date,authority,court_case_no FROM amcu_registry
          WHERE DIGITS(offender_code)=? ORDER BY decision_date DESC""", (code,))]
        manager_names = []
        if profile and profile["manager_name"]:
            manager_names.append(profile["manager_name"])
        manager_names.extend(row[0] for row in con.execute("""SELECT DISTINCT af.manager_name
          FROM submissions s JOIN application_fields af ON af.submission_id=s.id
          WHERE DIGITS(s.supplier_code)=? AND COALESCE(af.manager_name,'')<>''""", (code,)))
        normalized_managers = {" ".join(re.sub(r"[’'`\-]+", " ", name.casefold()).split()) for name in manager_names if name}
        nazk = []
        if normalized_managers:
            placeholders = ",".join("?" for _ in normalized_managers)
            nazk = [dict(row) for row in con.execute(f"""SELECT full_name,offense_name,court_case_number,
              sentence_date,punishment_start,court_name,decision_url FROM nazk_registry
              WHERE NORMALIZE_NAME(full_name) IN ({placeholders}) ORDER BY sentence_date DESC""", tuple(normalized_managers))]
        nazk_application_state = get_supplier_application_nazk_state(con, code)
        violation_reports = [dict(row) for row in con.execute("""SELECT report_id,status,date_published,
          reason,description,decision_resolution,decision_description,decision_date,tender_pretty_id,
          contract_pretty_id,authority_name FROM violation_reports WHERE DIGITS(defendant_code)=?
          ORDER BY COALESCE(NULLIF(decision_date,''),date_published) DESC LIMIT 100""", (code,))]
        violation_summary_row = con.execute("""SELECT COUNT(*) submitted,
          SUM(CASE WHEN status='satisfied' THEN 1 ELSE 0 END) satisfied,
          SUM(CASE WHEN status='satisfied' AND COALESCE(decision_date,'')='' THEN 1 ELSE 0 END) satisfied_without_decision_date
          FROM violation_reports WHERE DIGITS(defendant_code)=?""", (code,)).fetchone()
        violation_summary = {
            key: int((violation_summary_row[key] if violation_summary_row else 0) or 0)
            for key in ("submitted", "satisfied", "satisfied_without_decision_date")
        }
        satisfied_decision_dates = [row[0] for row in con.execute(
            "SELECT decision_date FROM violation_reports "
            "WHERE DIGITS(defendant_code)=? AND status='satisfied' "
            "AND COALESCE(decision_date,'')<>''",
            (code,),
        )]
        violation_summary.update(violation_threshold_summary(satisfied_decision_dates))
        violation_summary["thresholds_note"] = (
            "П. 52: враховано задоволені звернення за датою рішення; межі періодів включні."
        )
        contact_variants = []
        seen_contacts = set()
        for contact_row in con.execute("""SELECT s.id,s.date_published,s.raw_json,
          COALESCE(NULLIF(f.pretty_id,''),f.id) framework_id
          FROM submissions s LEFT JOIN frameworks f ON f.id=s.framework_id
          WHERE DIGITS(s.supplier_code)=?
          ORDER BY COALESCE(NULLIF(s.date_published,''),s.synced_at) DESC,s.id DESC""", (code,)):
            try:
                payload = json.loads(contact_row["raw_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}
            tenderers = payload.get("tenderers") or []
            contact = (tenderers[0].get("contactPoint") or {}) if tenderers and isinstance(tenderers[0], dict) else {}
            values = tuple(" ".join(str(contact.get(field) or "").split())
                           for field in ("name", "email", "telephone", "fax", "url"))
            key = tuple(value.casefold() for value in values)
            if not any(values) or key in seen_contacts:
                continue
            seen_contacts.add(key)
            contact_variants.append({
                "name": values[0], "email": values[1], "telephone": values[2],
                "fax": values[3], "url": values[4], "submission_id": contact_row["id"],
                "submission_date": contact_row["date_published"],
                "framework_id": contact_row["framework_id"],
            })
        application_rows = [dict(row) for row in con.execute("""SELECT s.id,s.framework_id,
          COALESCE(NULLIF(f.pretty_id,''),f.id) framework_pretty_id,f.dk_code,f.title framework_title,
          s.date_published,COALESCE(q.status,'pending') qualification_status,
          COALESCE(af.protocol_decision,'') protocol_decision,COALESCE(af.protocol_remarks,'') protocol_remarks,
          COALESCE(af.compliance_status,'') compliance_status,COALESCE(af.compliance_comments,'') compliance_comments,
          COALESCE(af.protocol_number,'') protocol_number,COALESCE(af.protocol_date,'') protocol_date,
          COALESCE(af.protocol_officer,'') protocol_officer
          FROM submissions s LEFT JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN qualifications q ON q.id=s.qualification_id
          LEFT JOIN application_fields af ON af.submission_id=s.id
          WHERE DIGITS(s.supplier_code)=?
          ORDER BY s.framework_id,COALESCE(NULLIF(s.date_published,''),s.synced_at) DESC,s.id DESC""", (code,))]
        application_history_groups = []
        for framework_id, grouped_rows in itertools.groupby(application_rows, key=lambda row: row["framework_id"]):
            attempts = list(grouped_rows)
            admitted = sum(1 for row in attempts if row["qualification_status"] == "active")
            rejected = sum(1 for row in attempts if row["qualification_status"] == "unsuccessful")
            latest = attempts[0]
            latest_remark = (latest["protocol_remarks"] or latest["compliance_comments"] or "").strip()
            application_history_groups.append({
                "framework_id": framework_id,
                "framework_pretty_id": latest["framework_pretty_id"],
                "dk_code": latest["dk_code"], "framework_title": latest["framework_title"],
                "applications_count": len(attempts), "admitted_count": admitted,
                "rejected_count": rejected, "latest_date": latest["date_published"],
                "latest_status": latest["qualification_status"], "latest_remark": latest_remark,
                "applications": attempts,
            })
        application_history_groups.sort(key=lambda group: group["latest_date"] or "", reverse=True)
    bids_summary = {"participations": 0, "wins": 0}
    try:
        with bids_db() as con:
            row = con.execute("""SELECT COUNT(DISTINCT tender_id) participations
              FROM bids WHERE supplier_id=?""", (code,)).fetchone()
            wins = con.execute("""SELECT COUNT(DISTINCT tender_id) FROM awards
              WHERE supplier_id=? AND LOWER(COALESCE(status,''))='active'""", (code,)).fetchone()[0]
            bids_summary = {**dict(row), "wins": int(wins or 0)}
    except (BidsUnavailableError, FileNotFoundError, sqlite3.Error):
        pass
    normalized_current_manager = " ".join(re.sub(r"[’'`\-]+", " ", ((profile["manager_name"] if profile else "") or "").casefold()).split())
    review_manager = " ".join(re.sub(r"[’'`\-]+", " ", ((nazk_review["manager_name"] if nazk_review else "") or "").casefold()).split())
    nazk_review_data = dict(nazk_review) if nazk_review else {}
    if nazk_review_data:
        nazk_review_data["is_current_manager"] = bool(normalized_current_manager and review_manager and normalized_current_manager == review_manager)
    latest_current_supplier_check = next((item for item in supplier_nazk_checks
        if item.get("workflow_status") == "completed"
        and " ".join(re.sub(r"[’'`\-]+", " ", str(item.get("manager_name") or "").casefold()).split()) == normalized_current_manager), {})
    nazk_presentation_state = get_supplier_nazk_presentation_state(
        nazk_application_state.get("state"),
        supplier_nazk_workflow.get("workflow_status"),
        registry_match=bool(nazk),
        legacy_result=(latest_current_supplier_check.get("result")
          or (nazk_review_data.get("result") if nazk_review_data.get("is_current_manager") else "")),
    )
    return {"code": code, "summary": dict(summary) if summary else {}, "edr_profile": dict(profile) if profile else {},
            "current_manager": dict(current_manager_row) if current_manager_row else {},
            "qualifications": qualifications, "bids_summary": bids_summary,
            "amcu": amcu, "nazk": nazk, "nazk_review": nazk_review_data,
            "nazk_check_history": nazk_check_history,
            "supplier_nazk_checks": supplier_nazk_checks,
            "supplier_nazk_workflow": supplier_nazk_workflow,
            "nazk_application_state": nazk_application_state,
            "nazk_presentation_state": nazk_presentation_state,
            "violation_reports": violation_reports,
            "violation_summary": violation_summary,
            "contacts": {"current": contact_variants[0] if contact_variants else None,
                         "history": contact_variants[1:]},
            "application_history_groups": application_history_groups}


def supplier_procurements(supplier_code: str, params: dict) -> dict:
    """On-demand, paged ProzorroBids rows. Supplier profile never calls this."""
    code = re.sub(r"\D", "", urllib.parse.unquote(supplier_code or ""))
    if not code:
        raise KeyError(supplier_code)
    page = max(1, int(params.get("page", ["1"])[0] or 1))
    size = min(200, max(10, int(params.get("size", ["50"])[0] or 50)))
    result = params.get("result", [""])[0].strip().lower()
    wins_only = params.get("wins", [""])[0].strip().lower() in {"1", "true", "yes"} or result == "wins"
    dk_codes = [value.strip() for value in params.get("dk_code", [""])[0].split(",") if value.strip()]
    search = params.get("search", [""])[0].strip().casefold()
    date_from = params.get("date_from", [""])[0].strip()
    date_to = params.get("date_to", [""])[0].strip()
    year = params.get("year", [""])[0].strip()
    where = "b.supplier_id=?"
    args = [code]
    if wins_only:
        where += " AND EXISTS (SELECT 1 FROM awards aw WHERE aw.tender_id=b.tender_id AND aw.supplier_id=? AND LOWER(COALESCE(aw.status,''))='active')"
        args.append(code)
    elif result == "participations":
        where += " AND NOT EXISTS (SELECT 1 FROM awards aw WHERE aw.tender_id=b.tender_id AND aw.supplier_id=? AND LOWER(COALESCE(aw.status,''))='active')"
        args.append(code)
    if dk_codes:
        where += f" AND t.cpv_code IN ({','.join('?' for _ in dk_codes)})"
        args.extend(dk_codes)
    tender_date = "SUBSTR(COALESCE(t.tender_start,t.date_created,b.bid_date,''),1,10)"
    if year:
        where += f" AND SUBSTR({tender_date},1,4)=?"; args.append(year)
    if date_from:
        where += f" AND {tender_date}>=?"; args.append(date_from)
    if date_to:
        where += f" AND {tender_date}<=?"; args.append(date_to)
    if search:
        where += " AND (INSTR(LOWER(COALESCE(b.tender_id,'')),?)>0 OR INSTR(LOWER(COALESCE(t.title,'')),?)>0 OR INSTR(LOWER(COALESCE(t.buyer_name,'')),?)>0)"
        args.extend([search] * 3)
    with bids_db() as con:
        total = int(con.execute(f"SELECT COUNT(DISTINCT b.tender_id) FROM bids b LEFT JOIN tenders t ON t.tender_id=b.tender_id WHERE {where}", args).fetchone()[0] or 0)
        top_dk = [dict(row) for row in con.execute("""SELECT COALESCE(t.cpv_code,'') dk_code,
          COALESCE(MAX(t.cpv_name),'') dk_name,COUNT(DISTINCT b.tender_id) procurements
          FROM bids b LEFT JOIN tenders t ON t.tender_id=b.tender_id
          WHERE b.supplier_id=? AND COALESCE(t.cpv_code,'')<>''
          GROUP BY t.cpv_code ORDER BY procurements DESC,t.cpv_code LIMIT 12""", (code,))]
        summary_row = con.execute("""SELECT COUNT(DISTINCT b.tender_id) participations,
          COUNT(DISTINCT CASE WHEN EXISTS (SELECT 1 FROM awards aw WHERE aw.tender_id=b.tender_id
            AND aw.supplier_id=? AND LOWER(COALESCE(aw.status,''))='active') THEN b.tender_id END) wins
          FROM bids b WHERE b.supplier_id=?""", (code, code)).fetchone()
        rows = [dict(row) for row in con.execute(f"""SELECT b.tender_id,MAX(t.title) title,
          MAX(t.cpv_code) dk_code,MAX(t.cpv_name) dk_name,
          MAX(COALESCE(t.tender_start,t.date_created,b.bid_date)) tender_date,MAX(t.status) status,
          MAX(t.buyer_name) buyer_name,COUNT(*) bids_count,MAX(b.amount) amount,MAX(b.currency) currency,
          MAX(CASE WHEN aw.supplier_id IS NOT NULL THEN 1 ELSE 0 END) won
          FROM bids b LEFT JOIN tenders t ON t.tender_id=b.tender_id
          LEFT JOIN awards aw ON aw.tender_id=b.tender_id AND aw.supplier_id=? AND LOWER(COALESCE(aw.status,''))='active'
          WHERE {where} GROUP BY b.tender_id ORDER BY tender_date DESC LIMIT ? OFFSET ?""",
          (code, *args, size, (page - 1) * size))]
    return {"items": rows, "supplier_code": code, "wins_only": wins_only, "result": result,
            "filters": {"dk_code": dk_codes, "search": search, "date_from": date_from,
                        "date_to": date_to, "year": year},
            "summary": {"participations": int(summary_row[0] or 0), "wins": int(summary_row[1] or 0)},
            "top_dk": top_dk, "total": total, "page": page, "size": size,
            "pages": max(1, (total + size - 1) // size)}


def framework_service_directory() -> dict:
    with db() as con:
        raw_items = [dict(row) for row in con.execute("""SELECT d.pretty_id directory_id,d.framework_id,
          d.pretty_id,COALESCE(NULLIF(d.dk_code,''),f.dk_code,'') dk_code,
          COALESCE(NULLIF(f.title,''),d.source_title,'') title,
          COALESCE(f.status,'') official_status,COALESCE(f.raw_json,'{}') framework_raw_json,
          d.category,d.marketplace_url,d.responsible_officer,d.source,d.synced_at updated_at
          FROM framework_service_directory d LEFT JOIN frameworks f ON f.id=d.framework_id
          ORDER BY d.pretty_id""")]
    items, counts = [], {"active": 0, "closed": 0, "unknown": 0}
    for item in raw_items:
        try:
            raw = json.loads(item.pop("framework_raw_json") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = {}
        valid_until = str(((raw.get("qualificationPeriod") or {}).get("endDate") or ""))[:10]
        effective = effective_framework_status(item.get("official_status") or "", raw)
        item["missing_end_date"] = item.get("official_status") == "active" and not valid_until
        if not item.get("framework_id"):
            item["status"] = "Не відбувся"
            counts["unknown"] += 1
        elif effective == "active":
            item["status"] = "Активний"
            counts["active"] += 1
        elif effective == "closed":
            item["status"] = "Закритий"
            counts["closed"] += 1
        else:
            item["status"] = "Статус не визначено"
            counts["unknown"] += 1
        item["valid_until"] = valid_until
        items.append(item)
    items.sort(key=lambda row: (row["status"] != "Активний", row["pretty_id"]))
    return {"items": items, "total": len(items), "statuses": counts}


def create_framework_service_entry(payload: dict, changed_by: str) -> dict:
    pretty_id = str(payload.get("pretty_id") or "").strip()
    dk_code = str(payload.get("dk_code") or "").strip()
    category = str(payload.get("category") or "").strip()
    marketplace_url = str(payload.get("marketplace_url") or "").strip()
    officer = formatted_officer_name(payload.get("responsible_officer"))
    if not pretty_id or not dk_code:
        raise ValueError("Вкажіть ID відбору та Код ДК")
    if officer and not valid_active_officer(officer):
        raise ValueError("Невідома відповідальна УО")
    now = now_iso()
    with db() as con:
        if con.execute("SELECT 1 FROM framework_service_directory WHERE pretty_id=?", (pretty_id,)).fetchone():
            raise ValueError("Відбір із таким ID уже є у службовому довіднику")
        framework = con.execute("SELECT id FROM frameworks WHERE pretty_id=?", (pretty_id,)).fetchone()
        framework_id = framework["id"] if framework else None
        con.execute("""INSERT INTO framework_service_directory
          (pretty_id,framework_id,dk_code,category,marketplace_url,responsible_officer,
           source_title,source,synced_at) VALUES (?,?,?,?,?,?,?,?,?)""",
          (pretty_id, framework_id, dk_code, category, marketplace_url, officer,
           str(payload.get("source_title") or "").strip(), "PQM", now))
        if framework_id:
            con.execute("""INSERT INTO framework_officers(framework_id,officer,marketplace_url,category,source,synced_at)
              VALUES (?,?,?,?,?,?) ON CONFLICT(framework_id) DO UPDATE SET officer=excluded.officer,
              marketplace_url=excluded.marketplace_url,category=excluded.category,source='PQM',synced_at=excluded.synced_at""",
              (framework_id, officer, marketplace_url, category, "PQM", now))
        con.execute("""INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value)
          VALUES (?,?,?,?,?,?)""", (pretty_id, now, changed_by, "framework_directory.created", "", "PQM"))
    return {"created": True, "pretty_id": pretty_id, "framework_matched": bool(framework_id)}


def import_new_framework_service_entries(changed_by: str) -> dict:
    """Import only absent Google rows; never update an existing PQM directory record."""
    rows = load_announcement_rows()
    imported, conflicts, skipped = [], [], 0
    with db() as con:
        existing = {row[0] for row in con.execute("SELECT pretty_id FROM framework_service_directory")}
    for row in rows:
        pretty_id = str(row.get("ID") or "").strip()
        if not pretty_id:
            skipped += 1; continue
        if pretty_id in existing:
            conflicts.append(pretty_id); continue
        try:
            create_framework_service_entry({
                "pretty_id": pretty_id, "dk_code": row.get("ДК"),
                "category": row.get("Категорія") or row.get("КАТЕГ"),
                "marketplace_url": row.get("Посилання на майданчик"),
                "responsible_officer": announcement_officer_name(row.get("Хто публікує") or ""),
                "source_title": row.get("Назва фреймворку") or row.get("Інформація про категорію товару"),
            }, changed_by)
            # This record came from the initial-import source, but its future
            # editable fields are already PQM-owned and cannot be overwritten.
            imported.append(pretty_id); existing.add(pretty_id)
        except ValueError:
            skipped += 1
    return {"source_rows": len(rows), "imported": len(imported), "imported_ids": imported,
            "existing_conflicts": len(conflicts), "conflict_ids": conflicts, "skipped": skipped}


def submission_nazk_context(con: sqlite3.Connection, submission_id: str) -> dict:
    """Existing registry/supplier context for one application; performs no writes."""
    row = con.execute("""SELECT s.supplier_code,COALESCE(ctrl.manager_name,''),
      COALESCE(af.manager_name,''),COALESCE(af.manager_name_source,''),
      COALESCE(af.manager_name_source_submission_id,''),s.date_published,s.synced_at
      FROM submissions s LEFT JOIN submission_nazk_controls ctrl ON ctrl.submission_id=s.id
      LEFT JOIN application_fields af ON af.submission_id=s.id WHERE s.id=?""", (submission_id,)).fetchone()
    if not row:
        raise ValueError("Заявку не знайдено")
    manager_name = row[1] or row[2]
    matches = registry_matches(con, manager_name) if manager_name else []
    current_date = _parse_prozorro_date(row[5] or row[6])
    current_day = current_date.date() if current_date else None

    def valid_manager(value: str | None) -> bool:
        return bool(value and value.strip() not in {"-", "—"})

    previous_manager = ""
    previous_source = ""
    previous_date = ""
    previous_submission = con.execute("""SELECT af.manager_name,s.date_published,s.synced_at,s.id
      FROM submissions s JOIN application_fields af ON af.submission_id=s.id
      WHERE DIGITS(s.supplier_code)=DIGITS(?) AND s.id<>? AND COALESCE(af.manager_name,'')<>''
        AND COALESCE(NULLIF(s.date_published,''),s.synced_at)<COALESCE(NULLIF(?,''),?)
      ORDER BY COALESCE(NULLIF(s.date_published,''),s.synced_at) DESC,s.id DESC LIMIT 1""",
      (row[0], submission_id, row[5], row[6])).fetchone()
    if previous_submission and valid_manager(previous_submission[0]):
        previous_manager = previous_submission[0].strip()
        previous_source = "previous_submission"
        previous_date = previous_submission[1] or previous_submission[2] or ""
    if not previous_manager:
        edr = con.execute("""SELECT manager_name,edr_checked_at,source_sheet,source_row
          FROM supplier_edr_profiles WHERE DIGITS(supplier_code)=DIGITS(?)""", (row[0],)).fetchone()
        edr_parsed = _parse_prozorro_date(edr[1]) if edr else None
        edr_day = (parse_ukrainian_date(edr[1]) or (edr_parsed.date() if edr_parsed else None)) if edr else None
        if edr and valid_manager(edr[0]) and current_day and edr_day and edr_day < current_day:
            previous_manager = edr[0].strip()
            previous_source = "edr_profile"
            previous_date = edr[1]
    if not previous_manager:
        historical = con.execute("""SELECT manager_name,source,created_at,updated_at FROM supplier_managers
          WHERE DIGITS(supplier_code)=DIGITS(?) ORDER BY is_current DESC,updated_at DESC,id DESC""",
          (row[0],)).fetchall()
        for candidate in historical:
            known_at = _parse_prozorro_date(candidate[2] or candidate[3])
            if (valid_manager(candidate[0]) and current_date and known_at
                    and known_at.date() < current_day):
                previous_manager = candidate[0].strip()
                previous_source = candidate[1] or "supplier_manager_history"
                previous_date = candidate[2] or candidate[3] or ""
                break
    supplier_check = con.execute("""SELECT chk.id,chk.workflow_status,chk.result,chk.completed_at,
      chk.evidence_date,chk.comment,chk.updated_by checked_by,doc.title document_title,doc.url document_url
      FROM supplier_nazk_checks chk LEFT JOIN supplier_nazk_check_documents doc ON doc.id=(
        SELECT d.id FROM supplier_nazk_check_documents d WHERE d.check_id=chk.id
        ORDER BY d.created_at DESC,d.id DESC LIMIT 1)
      WHERE chk.supplier_code=? AND NORMALIZE_NAME(chk.manager_name)=NORMALIZE_NAME(?)
        AND chk.workflow_status='completed' AND chk.result IN ('refuted','confirmed')
      ORDER BY COALESCE(chk.completed_at,chk.updated_at,chk.started_at) DESC,chk.id DESC LIMIT 1""",
      (row[0], manager_name)).fetchone()
    return {"manager": {"current": manager_name, "previous": previous_manager,
                         "previous_source": previous_source, "previous_date": previous_date,
                         "source": row[3], "source_submission_id": row[4]},
            "registry_matches": matches,
            "latest_supplier_check": dict(supplier_check) if supplier_check else None}


def _organization_fields(organization: dict | None) -> tuple[str, str]:
    organization = organization or {}
    identifier = organization.get("identifier") or {}
    return str(organization.get("name") or identifier.get("legalName") or ""), str(identifier.get("id") or "")


def _resolve_violation_tender(tender_id: str, contract_id: str) -> tuple[str, str]:
    if not tender_id:
        return "", ""
    try:
        tender = (api_get(f"{API_ROOT}/tenders/{tender_id}").get("data") or {})
        tender_pretty_id = str(tender.get("tenderID") or "")
        contract_pretty_id = ""
        for contract in tender.get("contracts") or []:
            if str(contract.get("id") or "") == contract_id:
                contract_pretty_id = str(contract.get("contractID") or "")
                break
        return tender_pretty_id, contract_pretty_id
    except Exception:
        return "", ""


def save_violation_report(payload: dict) -> bool:
    details = payload.get("details") or {}
    author_name, author_code = _organization_fields(payload.get("author"))
    defendant = (payload.get("defendants") or [{}])[0]
    defendant_name, defendant_code = _organization_fields(defendant)
    authority_name, authority_code = _organization_fields(payload.get("authority"))
    decisions = payload.get("decisions") or []
    decision = decisions[-1] if decisions else {}
    tender_id, contract_id = str(payload.get("tender_id") or ""), str(payload.get("contract_id") or "")
    with db() as con:
        existing = con.execute("SELECT tender_pretty_id,contract_pretty_id FROM violation_reports WHERE id=?", (payload.get("id"),)).fetchone()
    tender_pretty_id = existing[0] if existing else ""
    contract_pretty_id = existing[1] if existing else ""
    if not tender_pretty_id:
        tender_pretty_id, contract_pretty_id = _resolve_violation_tender(tender_id, contract_id)
    period = payload.get("defendantPeriod") or {}
    with db() as con:
        con.execute("""INSERT INTO violation_reports (
          id,report_id,status,date_created,date_published,date_modified,tender_id,tender_pretty_id,
          contract_id,contract_pretty_id,author_name,author_code,defendant_name,defendant_code,
          authority_name,authority_code,reason,description,defendant_period_start,defendant_period_end,
          decision_resolution,decision_description,decision_date,evidence_documents_json,
          decision_documents_json,raw_json,synced_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(id) DO UPDATE SET report_id=excluded.report_id,status=excluded.status,
          date_created=excluded.date_created,date_published=excluded.date_published,date_modified=excluded.date_modified,
          tender_id=excluded.tender_id,tender_pretty_id=excluded.tender_pretty_id,contract_id=excluded.contract_id,
          contract_pretty_id=excluded.contract_pretty_id,author_name=excluded.author_name,author_code=excluded.author_code,
          defendant_name=excluded.defendant_name,defendant_code=excluded.defendant_code,authority_name=excluded.authority_name,
          authority_code=excluded.authority_code,
          reason=excluded.reason,description=excluded.description,defendant_period_start=excluded.defendant_period_start,
          defendant_period_end=excluded.defendant_period_end,decision_resolution=excluded.decision_resolution,
          decision_description=excluded.decision_description,decision_date=excluded.decision_date,
          evidence_documents_json=excluded.evidence_documents_json,decision_documents_json=excluded.decision_documents_json,
          raw_json=excluded.raw_json,synced_at=excluded.synced_at""", (
            str(payload.get("id") or ""), str(payload.get("violationReportID") or ""), str(payload.get("status") or ""),
            str(payload.get("dateCreated") or ""), str(payload.get("datePublished") or ""), str(payload.get("dateModified") or ""),
            tender_id, tender_pretty_id, contract_id, contract_pretty_id, author_name, author_code,
            defendant_name, defendant_code, authority_name, authority_code, str(details.get("reason") or ""), str(details.get("description") or ""),
            str(period.get("startDate") or ""), str(period.get("endDate") or ""), str(decision.get("resolution") or ""),
            str(decision.get("description") or ""), str(decision.get("datePublished") or decision.get("dateModified") or ""),
            json.dumps(details.get("documents") or [], ensure_ascii=False),
            json.dumps(decision.get("documents") or [], ensure_ascii=False), json.dumps(payload, ensure_ascii=False), now_iso()))
    return True


def save_violation_report_with_retry(payload: dict, attempts: int = 5) -> bool:
    """Retry transient SQLite writer contention without losing a Prozorro update."""
    for attempt in range(attempts):
        try:
            return save_violation_report(payload)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt + 1 >= attempts:
                raise
            time.sleep(1.5 * (attempt + 1))
    return False


def sync_violation_reports_worker() -> None:
    if VIOLATION_SYNC_STATE["running"]:
        return
    VIOLATION_SYNC_STATE.update(running=True, message="Отримання переліку звернень…", processed=0, total=0, errors=0)
    try:
        feed = []
        for batch in paginated_pages(f"{API_ROOT}/violation_reports"):
            feed.extend(batch)
            VIOLATION_SYNC_STATE.update(total=len(feed), message=f"Знайдено {len(feed)} звернень…")
        with db() as con:
            known = {row[0]: row[1] for row in con.execute("SELECT id,date_modified FROM violation_reports")}
        pending = [item for item in feed if not known.get(str(item.get("id") or "")) or known.get(str(item.get("id") or "")) != str(item.get("dateModified") or "")]
        for index, item in enumerate(pending, 1):
            report_id = str(item.get("id") or "")
            try:
                detail = api_get(f"{API_ROOT}/violation_reports/{report_id}").get("data") or {}
                if detail:
                    save_violation_report_with_retry(detail)
            except Exception as exc:
                VIOLATION_SYNC_STATE["errors"] += 1
                VIOLATION_SYNC_STATE["last_error"] = f"{report_id}: {exc}"
            VIOLATION_SYNC_STATE.update(processed=index, message=f"Оновлено {index}/{len(pending)} звернень")
        error_note = f"; остання помилка: {VIOLATION_SYNC_STATE.get('last_error')}" if VIOLATION_SYNC_STATE["errors"] else ""
        VIOLATION_SYNC_STATE["message"] = f"Готово: у базі {len(feed)} звернень; оновлено {len(pending) - VIOLATION_SYNC_STATE['errors']}; помилок {VIOLATION_SYNC_STATE['errors']}{error_note}"
    except Exception as exc:
        VIOLATION_SYNC_STATE["message"] = f"Помилка синхронізації звернень: {exc}"
    finally:
        VIOLATION_SYNC_STATE.update(running=False, updated_at=now_iso())


def list_violation_reports(params: dict) -> dict:
    search = params.get("search", [""])[0].strip().casefold()
    status = params.get("status", [""])[0].strip()
    reason = params.get("reason", [""])[0].strip()
    date_from = params.get("date_from", [""])[0].strip()
    date_to = params.get("date_to", [""])[0].strip()
    supplier_code = params.get("supplier_code", [""])[0].strip()
    authority_code = params.get("authority_code", [""])[0].strip()
    page = max(1, int(params.get("page", ["1"])[0] or 1))
    size = min(200, max(10, int(params.get("size", ["100"])[0] or 100)))
    where, args = ["1=1"], []
    if search:
        where.append("(INSTR(CASEFOLD(report_id),?)>0 OR INSTR(CASEFOLD(author_name),?)>0 OR INSTR(CASEFOLD(author_code),?)>0 OR INSTR(CASEFOLD(defendant_name),?)>0 OR INSTR(CASEFOLD(defendant_code),?)>0 OR INSTR(CASEFOLD(tender_pretty_id),?)>0 OR INSTR(CASEFOLD(description),?)>0)")
        args.extend([search] * 7)
    if status:
        where.append("status=?"); args.append(status)
    if reason:
        where.append("reason=?"); args.append(reason)
    if date_from:
        where.append("SUBSTR(date_published,1,10)>=?"); args.append(date_from)
    if date_to:
        where.append("SUBSTR(date_published,1,10)<=?"); args.append(date_to)
    if supplier_code:
        where.append("defendant_code=?"); args.append(supplier_code)
    authority_clause = " AND ".join(where)
    authority_args = list(args)
    if authority_code:
        where.append("authority_code=?"); args.append(authority_code)
    clause = " AND ".join(where)
    with db() as con:
        total = con.execute(f"SELECT COUNT(*) FROM violation_reports WHERE {clause}", args).fetchone()[0]
        rows = con.execute(f"""SELECT id,report_id,status,date_published,date_modified,tender_pretty_id,contract_pretty_id,
          author_name,author_code,defendant_name,defendant_code,authority_name,authority_code,reason,description,
          defendant_period_start,defendant_period_end,decision_resolution,decision_description,decision_date,
          evidence_documents_json,decision_documents_json,raw_json
          FROM violation_reports WHERE {clause} ORDER BY date_published DESC,report_id DESC LIMIT ? OFFSET ?""",
          (*args, size, (page - 1) * size)).fetchall()
        statuses = [row[0] for row in con.execute("SELECT DISTINCT status FROM violation_reports WHERE status<>'' ORDER BY status")]
        reasons = [row[0] for row in con.execute("SELECT DISTINCT reason FROM violation_reports WHERE reason<>'' ORDER BY reason")]
        satisfied = con.execute(f"SELECT COUNT(*) FROM violation_reports WHERE {clause} AND status='satisfied'", args).fetchone()[0]
        authorities = [dict(row) for row in con.execute(f"""SELECT authority_code,authority_name,COUNT(*) count
          FROM violation_reports WHERE {authority_clause} AND authority_code<>''
          GROUP BY authority_code,authority_name ORDER BY count DESC,authority_name""", authority_args).fetchall()]
    items = []
    for row in rows:
        item = dict(row)
        item["evidence_documents"] = json.loads(item.pop("evidence_documents_json") or "[]")
        item["decision_documents"] = json.loads(item.pop("decision_documents_json") or "[]")
        raw = json.loads(item.pop("raw_json") or "{}")
        item["defendant_statements"] = raw.get("defendantStatements") or []
        items.append(item)
    return {"items": items, "total": total, "satisfied": satisfied, "page": page, "size": size,
            "pages": (total + size - 1) // size, "statuses": statuses, "reasons": reasons,
            "authorities": authorities,
            "sync": dict(VIOLATION_SYNC_STATE)}


VIOLATION_REVIEW_FIELDS = {
    "review_status", "assigned_officer", "assigned_officer_id", "internal_decision", "decision_justification", "review_notes",
    "protocol_number", "protocol_date", "contract_deadline_extended",
    "written_refusal_date", "written_refusal_number", "written_refusal_url",
    "court_decision_final_present", "customer_verified_full_name",
    "customer_verified_short_name", "actual_contract_date", "actual_contract_number",
    "actual_contract_url", "additional_check_required", "guarantee_documents_visible",
    "supplier_explanation_assessment", "established_discrepancy", "decision_template_key",
    "customer_protocol_decision_date", "customer_protocol_decision_number",
    "customer_protocol_decision_url",
}
VIOLATION_INTERNAL_DECISIONS = {"", "warning", "decline", "individual_review"}


def _parse_prozorro_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso_date(value: datetime | None) -> str | None:
    return value.date().isoformat() if value else None


def _calendar_deadline(start: datetime | None, days: int) -> dict:
    if not start:
        return {"calendar_day": None, "weekday": None, "shifted": False, "deadline": None}
    calendar_day = start + timedelta(days=days)
    deadline = calendar_day
    while deadline.weekday() >= 5:
        deadline += timedelta(days=1)
    return {
        "calendar_day": _iso_date(calendar_day),
        "weekday": calendar_day.strftime("%A"),
        "shifted": deadline.date() != calendar_day.date(),
        "deadline": _iso_date(deadline),
    }


def _within_calendar_deadline(moment: datetime | None, deadline_date: str | None) -> bool | None:
    """Compare legal calendar dates; the whole deadline day remains available."""
    if not moment or not deadline_date:
        return None
    try:
        boundary = datetime.strptime(deadline_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    return moment.date() <= boundary


def _add_working_days(start: datetime | None, days: int) -> str | None:
    """Return the date after `days` Mon-Fri days; weekends are not counted."""
    if not start:
        return None
    current = start.date()
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current.isoformat()


def _deadline_passed(deadline: str | None, moment: datetime | None = None) -> bool:
    if not deadline:
        return False
    raw = str(deadline).strip()
    boundary = _parse_prozorro_date(raw)
    if boundary and ("T" in raw or " " in raw):
        current = moment or datetime.now().astimezone()
        if boundary.tzinfo is None:
            boundary = boundary.replace(tzinfo=current.tzinfo)
        elif current.tzinfo is None:
            current = current.replace(tzinfo=boundary.tzinfo)
        return current >= boundary
    try:
        boundary_date = datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    return (moment or datetime.now()).date() > boundary_date


def violation_deadline_control(report: dict, moment: datetime | None = None) -> dict:
    """Separate the supplier response term from the Administrator review term."""
    received = _parse_prozorro_date(report.get("date_published") or report.get("date_created"))
    official = str(report.get("defendant_period_end") or "").strip() or None
    local_control = _add_working_days(received, 3)
    admin_deadline = _add_working_days(received, 10)
    return {
        "supplier_official_deadline": official,
        "supplier_local_control_deadline": local_control,
        "supplier_deadline": official,
        "supplier_ready": _deadline_passed(official, moment),
        "supplier_deadline_missing": not bool(official),
        "admin_deadline": admin_deadline,
        "admin_overdue": _deadline_passed(admin_deadline, moment),
    }


def violation_report_owned_by_pqm(report: dict | sqlite3.Row) -> bool:
    code = report["authority_code"] if isinstance(report, sqlite3.Row) else report.get("authority_code")
    return re.sub(r"\D", "", str(code or "")) == ORGANIZER_EDRPOU


def require_owned_violation_report(report: dict | sqlite3.Row) -> None:
    if not violation_report_owned_by_pqm(report):
        raise ForeignAuthorityError(
            "Інформаційний перегляд. Звернення належить іншій ЦЗО — розгляд у PQM недоступний."
        )


def require_local_violation_report_owned(report_id: str) -> None:
    """Fail closed before any network refresh can persist data for a foreign CPO report."""
    with db() as con:
        report = con.execute(
            "SELECT authority_code FROM violation_reports WHERE id=? OR report_id=?",
            (report_id, report_id),
        ).fetchone()
    if not report:
        raise KeyError(report_id)
    require_owned_violation_report(report)


def _justification_basis(report: dict, context: dict, review: dict) -> dict:
    return {
        "reason": report.get("reason"), "description": report.get("description"),
        "statements": report.get("defendant_statements") or [],
        "evidence": report.get("evidence_documents") or [],
        "winner": context.get("winner_selected_at"), "rejection": context.get("rejection_date"),
        "rejection_reason": context.get("rejection_reason_classification"),
        "contract": [context.get("contract_status"), context.get("contract_date"), context.get("contract_pretty_id")],
        "review": {key: review.get(key) for key in (
            "internal_decision", "additional_check_required", "guarantee_documents_visible",
            "supplier_explanation_assessment", "established_discrepancy", "written_refusal_date",
            "written_refusal_number", "written_refusal_url", "court_decision_final_present")},
    }


def _justification_hash(report: dict, context: dict, review: dict) -> str:
    raw = json.dumps(_justification_basis(report, context, review), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _identifier_code(organization: dict) -> str:
    return re.sub(r"\D", "", str(((organization.get("identifier") or {}).get("id") or "")))


def _award_matches_supplier(award: dict, defendant_code: str) -> bool:
    wanted = re.sub(r"\D", "", defendant_code or "")
    return bool(wanted) and any(_identifier_code(item) == wanted for item in award.get("suppliers") or [])


def _award_sort_key(award: dict) -> str:
    return str((award.get("period") or {}).get("startDate") or award.get("date") or "")


def _documents_without_signature(documents: list[dict]) -> list[dict]:
    return sorted(documents or [], key=lambda item: str(item.get("datePublished") or ""), reverse=True)


def classify_award_rejection_reason(award: dict | None) -> str:
    """Conservatively classify only explicit non-signing/guarantee wording."""
    text = " ".join(str((award or {}).get(key) or "") for key in ("title", "description")).casefold()
    non_signing = any(token in text for token in (
        "непідпис", "не підпис", "відмовився від підпис", "відмова від підпис",
        "неуклад", "не уклад", "відмовився укласти", "відмова від уклад",
    ))
    guarantee = any(token in text for token in (
        "ненадан", "не надан", "відсутн", "не внес",
    )) and any(token in text for token in ("забезпечен", "гаранті"))
    if non_signing and guarantee:
        return "non_signing_and_guarantee"
    if non_signing:
        return "non_signing"
    if guarantee:
        return "guarantee_missing"
    return "other" if text.strip() else "unknown"


def _display_legal_date(value) -> str:
    raw = str(value or "")[:10]
    return ".".join(reversed(raw.split("-"))) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) else raw


def violation_decision_template_key(report: dict, context: dict, review: dict | None = None) -> str:
    """Return only a legally approved template key; unsupported combinations have no draft."""
    review = review or {}
    reason = report.get("reason") or ""
    decision = review.get("internal_decision") or ""
    statements = report.get("defendant_statements") or []
    if (reason == "contractBreach" and decision == "warning"
            and context.get("rejection_present") and not statements
            and context.get("rejected_before_deadline") is False):
        if context.get("contract_guarantee_required"):
            if review.get("guarantee_documents_visible") == 0:
                return "p49_1_warning_guarantee_no_documents_no_explanation"
            return ""
        return "p49_1_warning"
    if (reason == "signingRefusal" and decision == "decline"
            and context.get("written_refusal_within_deadline") is True):
        return ("p49_2_decline_timely_refusal_civil_shift"
                if context.get("day_3_shifted") else "p49_2_decline_timely_refusal")
    return ""


def build_violation_decision_justification(report: dict, context: dict, review: dict | None = None) -> str:
    """Render an approved template only; never invent or persist additional legal reasoning."""
    review = review or {}
    template_key = violation_decision_template_key(report, context, review)
    winner_date = _display_legal_date(context.get("winner_selected_at"))
    if template_key in {"p49_1_warning", "p49_1_warning_guarantee_no_documents_no_explanation"}:
        paragraphs = [
            "За результатами розгляду звернення Замовника та аналізу матеріалів закупівлі Адміністратором встановлено наступне.",
            f"Повідомлення про намір укласти договір з Постачальником було оприлюднено в електронній системі закупівель {winner_date}.",
            f"Відповідно до п. 66 Порядку № 822, граничний строк для укладення договору – {_display_legal_date(context.get('contract_deadline'))}.",
            f"Станом на дату відхилення замовником пропозиції ({_display_legal_date(context.get('rejection_date'))}) договір Постачальником не підписано, що підтверджується даними електронної системи закупівель.",
        ]
        if template_key == "p49_1_warning_guarantee_no_documents_no_explanation":
            paragraphs.append(
                "Крім того, в електронній системі закупівель відсутні документи/відомості, що підтверджують надання Постачальником забезпечення виконання договору."
            )
        paragraphs.extend((
            "З боку Постачальника не надано жодних доказів або пояснень, які б спростували інформацію Замовника про вказане порушення.",
            "З огляду на відсутність підстав для відмови в задоволенні звернення, Адміністратор, керуючись п. 51 Порядку № 822, приймає рішення про наявність порушення постачальника, що передбачене пп. 1 п. 49 Порядку № 822.",
        ))
        return "\n\n".join(paragraphs)
    if template_key in {"p49_2_decline_timely_refusal", "p49_2_decline_timely_refusal_civil_shift"}:
        paragraphs = [
            "За результатами розгляду звернення Замовника та аналізу матеріалів закупівлі Адміністратором встановлено наступне.",
            f"Повідомлення про намір укласти договір з Постачальником було оприлюднене в електронній системі закупівель {winner_date}.",
            "Відповідно до пп. 2 п. 49 Порядку № 822, порушенням вважається надання постачальником письмової відмови від укладення договору після закінчення трьох календарних днів з дня оприлюднення повідомлення про намір укласти договір.",
        ]
        if template_key.endswith("civil_shift"):
            paragraphs.extend((
                f"Оскільки третій календарний день припадає на {_display_legal_date(context.get('day_3'))} ({context.get('day_3_weekday_uk_accusative') or context.get('day_3_weekday_uk') or 'вихідний день'}), при обрахунку строків підлягають застосуванню норми ч. 5 ст. 254 ЦК України.",
                f"Отже, граничний строк для правомірного надання письмової відмови переноситься на понеділок – {_display_legal_date(context.get('written_refusal_deadline'))}.",
            ))
        paragraphs.extend((
            f"Згідно з інформацією, наявною в електронній системі закупівель, письмову відмову надано Постачальником {_display_legal_date(review.get('written_refusal_date'))}, тобто у межах встановленого законодавством строку.",
            "Оскільки наведені факти не підтверджують наявність порушення, передбаченого пп. 2 п. 49 Порядку № 822, Адміністратор, керуючись п. 51 Порядку № 822, приймає рішення про відмову в задоволенні звернення Замовника.",
        ))
        return "\n\n".join(paragraphs)
    return ""


def _guarantee_requirements(tender: dict, awards: list[dict]) -> list[dict]:
    found = []
    seen = set()

    def walk(value, criterion=False):
        if isinstance(value, dict):
            classification = value.get("classification") or {}
            here = criterion or classification.get("id") == "CRITERION.OTHER.CONTRACT.GUARANTEE"
            if here and any(key in value for key in ("value", "unit", "requirement", "requirementID", "title")):
                marker = json.dumps(value, ensure_ascii=False, sort_keys=True)
                if marker not in seen:
                    seen.add(marker); found.append(value)
            for child in value.values():
                walk(child, here)
        elif isinstance(value, list):
            for child in value:
                walk(child, criterion)

    walk(tender.get("criteria") or [])
    for award in awards:
        walk(award.get("requirementResponses") or [])
    return found


def procurement_dk_classifications(tender: dict, contract: dict | None) -> list[dict]:
    """Use contract items first and tender items only as a fallback; preserve every distinct DK."""
    source_items = (contract or {}).get("items") or tender.get("items") or []
    result, seen = [], set()
    for item in source_items:
        classification = item.get("classification") or {}
        code = str(classification.get("id") or "").strip()
        description = str(classification.get("description") or "").strip()
        marker = (code, description)
        if not code or marker in seen:
            continue
        seen.add(marker)
        result.append({"code": code, "description": description})
    return result


def _review_dict(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    result = dict(row)
    result["contract_deadline_extended"] = bool(result.get("contract_deadline_extended"))
    if result.get("court_decision_final_present") is not None:
        result["court_decision_final_present"] = bool(result["court_decision_final_present"])
    for key in ("additional_check_required", "justification_manually_edited"):
        result[key] = bool(result.get(key))
    if result.get("guarantee_documents_visible") is not None:
        result["guarantee_documents_visible"] = bool(result["guarantee_documents_visible"])
    return result


def _violation_review_officer_presentation(review: dict | None) -> tuple[dict | None, list[dict]]:
    """Resolve managed officer ID without rewriting the historical review snapshot."""
    officers = authorized_officers(active_only=False)
    if not review:
        return review, [officer for officer in officers if officer["active"]]
    result = dict(review)
    stored_id = result.get("assigned_officer_id")
    snapshot = str(result.get("assigned_officer") or "").strip()
    matched = next((officer for officer in officers if officer["id"] == stored_id), None)
    if not matched and snapshot:
        normalized = normalized_officer_name(snapshot)
        matched = next((officer for officer in officers
                        if normalized_officer_name(officer["full_name"]) == normalized), None)
    if matched:
        result["assigned_officer_effective_id"] = matched["id"]
        result["assigned_officer_display"] = matched["full_name"]
        result["assigned_officer_is_historical"] = not matched["active"]
    else:
        result["assigned_officer_effective_id"] = None
        result["assigned_officer_display"] = snapshot
        result["assigned_officer_is_historical"] = bool(snapshot)
    selectable = [officer for officer in officers if officer["active"]]
    if matched and not matched["active"]:
        selectable.append(matched)
    return result, selectable


def violation_rules_engine(reason: str, context: dict, review: dict | None) -> dict:
    review = review or {}
    if reason == "contractBreach":
        if not context.get("rejection_present"):
            return {"recommended_decision": None, "recommended_scenario": "review_without_rejection",
                    "recommendation_reason": "Пропозицію переможця не відхилено; автоматична перевірка дострокового відхилення не застосовується. Потрібна оцінка інших обставин."}
        if context.get("rejected_before_deadline"):
            return {"recommended_decision": "decline", "recommended_scenario": "rejected_before_deadline",
                    "recommendation_reason": "Пропозицію відхилено до закінчення допустимого строку для укладення договору."}
        statements_present = bool(context.get("defendant_statements_present"))
        supplier_ready = bool(context.get("supplier_deadline_ready"))
        if statements_present:
            reason_text = ("Строк для укладення договору закінчився до відхилення пропозиції; "
                           "пояснення від постачальника надано, для прийняття рішення потрібно "
                           "проаналізувати надані пояснення/документи.")
        elif supplier_ready:
            reason_text = ("Строк для укладення договору закінчився до відхилення пропозиції; "
                           "пояснень від постачальника не надано.")
        else:
            reason_text = ("Строк для укладення договору закінчився до відхилення пропозиції; "
                           "потрібно дочекатися пояснень для прийняття рішення.")
        return {"recommended_decision": "warning", "recommended_scenario": "contract_deadline_expired",
                "recommendation_reason": reason_text}
    if reason == "signingRefusal":
        within = context.get("written_refusal_within_deadline")
        if within is None:
            return {"recommended_decision": None, "recommended_scenario": "written_refusal_missing",
                    "recommendation_reason": "Вкажіть дату письмової відмови для автоматичної рекомендації."}
        return {"recommended_decision": "decline" if within else "warning",
                "recommended_scenario": "written_refusal_within_deadline" if within else "written_refusal_late",
                "recommendation_reason": "Письмову відмову надано в межах строку." if within else "Письмову відмову надано після закінчення строку."}
    if reason == "goodsNonCompliance":
        present = review.get("court_decision_final_present")
        if present is None:
            return {"recommended_decision": None, "recommended_scenario": "court_decision_unknown",
                    "recommendation_reason": "Вкажіть, чи є рішення суду, що набрало законної сили."}
        return {"recommended_decision": "individual_review" if present else "decline",
                "recommended_scenario": "court_decision_present" if present else "court_decision_absent",
                "recommendation_reason": "Потрібен індивідуальний розгляд." if present else "Рішення суду, що набрало законної сили, відсутнє."}
    return {"recommended_decision": None, "recommended_scenario": "unsupported_reason",
            "recommendation_reason": "Для цієї підстави автоматичну рекомендацію не налаштовано."}


def build_procurement_context(report: dict, review: dict | None = None) -> dict:
    tender_id = str(report.get("tender_id") or "")
    if not tender_id:
        return {"available": False, "error": "У зверненні відсутній tender_id"}
    tender = api_get(f"{API_ROOT}/tenders/{tender_id}").get("data") or {}
    defendant_code = str(report.get("defendant_code") or "")
    supplier_awards = [award for award in tender.get("awards") or [] if _award_matches_supplier(award, defendant_code)]
    winner_candidates = [award for award in supplier_awards if award.get("qualified") is True]
    winner = max(winner_candidates, key=_award_sort_key, default=None)
    rejected_candidates = [award for award in supplier_awards
                           if award.get("status") == "unsuccessful" and award.get("qualified") is False]
    rejected = max(rejected_candidates, key=_award_sort_key, default=None)
    winner_selected = _parse_prozorro_date(((winner or {}).get("period") or {}).get("startDate"))
    extended = bool((review or {}).get("contract_deadline_extended"))
    deadline = _calendar_deadline(winner_selected, 10 if extended else 5)
    rejection_date = _parse_prozorro_date((rejected or {}).get("date"))
    rejection_classification = classify_award_rejection_reason(rejected)
    explicit_non_signing = rejection_classification in {
        "non_signing", "guarantee_missing", "non_signing_and_guarantee"
    }
    contract_award = rejected if explicit_non_signing and rejected else winner
    contract = next((item for item in tender.get("contracts") or []
                     if contract_award and str(item.get("awardID") or "") == str(contract_award.get("id") or "")
                     and (not item.get("suppliers") or any(
                         _identifier_code(org) == re.sub(r"\D", "", defendant_code)
                         for org in item.get("suppliers") or []))), None)
    report_relevant = report.get("reason") in {"contractBreach", "signingRefusal"}
    contract_info_required = not (report_relevant and bool(rejected) and explicit_non_signing and not contract)
    guarantee = _guarantee_requirements(tender, supplier_awards)
    dk_classifications = procurement_dk_classifications(tender, contract)
    guarantee_value = next((item.get("value") for item in guarantee if item.get("value") is not None), None)
    guarantee_unit = next((((item.get("unit") or {}).get("name")) for item in guarantee if item.get("unit")), None)
    context = {
        "available": True, "tender_id": tender_id, "tender_pretty_id": tender.get("tenderID") or report.get("tender_pretty_id"),
        "defendant_code": defendant_code, "supplier_awards_count": len(supplier_awards),
        "winner_award_id": (winner or {}).get("id"), "winner_selected_at": ((winner or {}).get("period") or {}).get("startDate"),
        "winner_award_status": (winner or {}).get("status"),
        "rejection_present": bool(rejected), "rejection_award_id": (rejected or {}).get("id"),
        "rejection_date": (rejected or {}).get("date"), "rejection_title": (rejected or {}).get("title"),
        "rejection_description": (rejected or {}).get("description"),
        "rejection_documents": _documents_without_signature((rejected or {}).get("documents") or []),
        "contract_internal_id": (contract or {}).get("id"), "contract_pretty_id": (contract or {}).get("contractID"),
        "contract_status": (contract or {}).get("status"),
        "contract_date": (contract or {}).get("dateSigned") or (contract or {}).get("date"),
        "contract_url": (f"https://prozorro.gov.ua/uk/contract/{(contract or {}).get('contractID')}"
                         if (contract or {}).get("contractID") else ""),
        "related_contract_found": bool(contract),
        "contract_signed": bool(contract) and str((contract or {}).get("status") or "").lower() != "cancelled",
        "rejection_reason_classification": rejection_classification,
        "contract_info_required": contract_info_required,
        "contract_warning": ("Виявлено договір із постачальником, щодо якого подано звернення про "
                             "непідписання. Потрібна ручна перевірка."
                             if explicit_non_signing and contract else ""),
        "contract_guarantee_required": bool(guarantee), "contract_guarantee_value": guarantee_value,
        "contract_guarantee_unit": guarantee_unit, "contract_guarantee_related_requirements": guarantee,
        "dk_classifications": dk_classifications,
        "dk_code": "; ".join(f"{item['code']} — {item['description']}" if item["description"] else item["code"]
                              for item in dk_classifications),
        "requirement_responses": [response for award in supplier_awards for response in award.get("requirementResponses") or []],
        "contract_deadline_extended": extended,
        "day_5": _calendar_deadline(winner_selected, 5)["calendar_day"],
        "day_5_weekday": _calendar_deadline(winner_selected, 5)["weekday"],
        "day_5_shifted": _calendar_deadline(winner_selected, 5)["shifted"],
        "day_10": _calendar_deadline(winner_selected, 10)["calendar_day"] if extended else None,
        "contract_deadline": deadline["deadline"],
        "rejected_before_deadline": _within_calendar_deadline(rejection_date, deadline["deadline"]),
    }
    day3 = _calendar_deadline(winner_selected, 3)
    weekday_uk = {"Monday": "понеділок", "Tuesday": "вівторок", "Wednesday": "середа",
                  "Thursday": "четвер", "Friday": "п’ятниця", "Saturday": "субота", "Sunday": "неділя"}
    weekday_uk_accusative = {"Saturday": "суботу", "Sunday": "неділю"}
    context.update(day_3=day3["calendar_day"], day_3_weekday=day3["weekday"],
                   day_3_weekday_uk=weekday_uk.get(day3["weekday"], day3["weekday"]),
                   day_3_weekday_uk_accusative=weekday_uk_accusative.get(day3["weekday"], weekday_uk.get(day3["weekday"], day3["weekday"])),
                   day_3_shifted=day3["shifted"], written_refusal_deadline=day3["deadline"])
    refusal_date = _parse_prozorro_date((review or {}).get("written_refusal_date"))
    context["written_refusal_within_deadline"] = _within_calendar_deadline(refusal_date, day3["deadline"])
    return context


def _fresh_violation_report(report_id: str) -> dict:
    payload = api_get(f"{API_ROOT}/violation_reports/{report_id}").get("data") or {}
    if not payload:
        raise ValueError("Prozorro не повернуло актуальне звернення")
    save_violation_report_with_retry(payload)
    return payload


def violation_report_detail(report_id: str, refresh: bool = True) -> dict:
    refresh_error = ""
    if refresh:
        try:
            _fresh_violation_report(report_id)
        except Exception as exc:
            refresh_error = str(exc)
    with db() as con:
        row = con.execute("SELECT * FROM violation_reports WHERE id=? OR report_id=?", (report_id, report_id)).fetchone()
        if not row:
            raise KeyError(report_id)
        review_row = con.execute("SELECT * FROM violation_report_reviews WHERE report_id=?", (row["id"],)).fetchone()
        supplier = con.execute("SELECT full_name,short_name FROM supplier_edr_profiles WHERE DIGITS(supplier_code)=DIGITS(?)", (row["defendant_code"],)).fetchone()
        warning_dates = [value[0] for value in con.execute(
            "SELECT decision_date FROM violation_reports WHERE DIGITS(defendant_code)=DIGITS(?) AND status='satisfied' AND decision_date<>''",
            (row["defendant_code"],)).fetchall()]
        events = [dict(event) for event in con.execute(
            "SELECT * FROM violation_report_review_events WHERE report_id=? ORDER BY changed_at DESC,id DESC", (row["id"],)).fetchall()]
        document_reviews = [dict(document) for document in con.execute(
            "SELECT * FROM violation_report_document_reviews WHERE report_id=?", (row["id"],)).fetchall()]
    item = dict(row); raw = json.loads(item.pop("raw_json") or "{}")
    item["evidence_documents"] = json.loads(item.pop("evidence_documents_json") or "[]")
    item["decision_documents"] = json.loads(item.pop("decision_documents_json") or "[]")
    item["defendant_statements"] = raw.get("defendantStatements") or []
    reviewed = {(entry["document_source"], entry["document_id"]): entry for entry in document_reviews}
    for document in item["evidence_documents"]:
        state = reviewed.get(("customer", str(document.get("id") or "")))
        document["manual_reviewed"] = bool(state)
        document["file_unavailable"] = bool(state and state["file_unavailable"])
        if state:
            document["checked_at"], document["checked_by"] = state["checked_at"], state["checked_by"]
    for statement in item["defendant_statements"]:
        for document in statement.get("documents") or []:
            state = reviewed.get(("supplier", str(document.get("id") or "")))
            document["manual_reviewed"] = bool(state)
            document["file_unavailable"] = bool(state and state["file_unavailable"])
            if state:
                document["checked_at"], document["checked_by"] = state["checked_at"], state["checked_by"]
    item["official_decisions"] = raw.get("decisions") or []
    item["has_official_decision"] = bool(item["official_decisions"])
    item["review"], item["active_officers"] = _violation_review_officer_presentation(
        _review_dict(review_row))
    item["review"] = item["review"] or {}
    item["local_review_completed"] = bool(
        item["review"].get("completed_at")
        or item["review"].get("review_status") in {"reviewed", "completed"}
    )
    item["owned_by_pqm"] = violation_report_owned_by_pqm(item)
    item["foreign_authority_read_only"] = not item["owned_by_pqm"]
    item["is_read_only"] = (item["has_official_decision"] or item["local_review_completed"]
                            or item["foreign_authority_read_only"])
    # ``completed`` used to mean that the local review was finished.  Keep the
    # stored legacy value intact, but present it as ``reviewed``.  ``completed``
    # is now reserved for an official Prozorro decision and is derived from the
    # current decisions[] payload rather than written into the local review.
    if item["has_official_decision"]:
        item["review"]["review_status"] = "completed"
    elif item["review"].get("review_status") == "completed":
        item["review"]["review_status"] = "reviewed"
    item["supplier_verified"] = dict(supplier) if supplier else None
    item["warning_summary"] = violation_threshold_summary(warning_dates)
    item["warning_summary"]["month"] = item["warning_summary"]["current_month"]
    item["warning_summary"]["three_months"] = item["warning_summary"]["three_calendar_months"]
    item["review_events"] = events
    item["deadline_control"] = violation_deadline_control(item)
    item["refresh_error"] = refresh_error
    item["procurement_context"] = None
    if not item["is_read_only"]:
        try:
            item["procurement_context"] = build_procurement_context(item, item["review"])
        except Exception as exc:
            item["procurement_context"] = {"available": False, "error": str(exc)}
        supplier_ready = bool(item["deadline_control"].get("supplier_ready"))
        recommendation_context = dict(item["procurement_context"] or {})
        recommendation_context["supplier_deadline_ready"] = supplier_ready
        recommendation_context["defendant_statements_present"] = bool(item["defendant_statements"])
        item["recommendation"] = violation_rules_engine(
            item["reason"], recommendation_context, item["review"])
        item["justification_draft"] = (build_violation_decision_justification(
            item, item["procurement_context"] or {}, item["review"]
        ) if supplier_ready else "")
        item["justification_template_key"] = (violation_decision_template_key(
            item, item["procurement_context"] or {}, item["review"]
        ) if supplier_ready else "")
        saved_review = item["review"] or {}
        automatic_saved_draft = bool(
            saved_review.get("decision_justification")
            and not saved_review.get("justification_manually_edited")
            and (saved_review.get("decision_template_key")
                 or saved_review.get("justification_source_hash")
                 or saved_review.get("justification_generated_at"))
        )
        item["justification_generation_ready"] = supplier_ready
        item["hide_saved_automatic_justification"] = bool(not supplier_ready and automatic_saved_draft)
        current_hash = _justification_hash(item, item["procurement_context"] or {}, item["review"] or {})
        item["justification_source_hash_current"] = current_hash
        item["justification_stale"] = bool(supplier_ready
            and item["review"] and item["review"].get("justification_source_hash")
            and item["review"].get("justification_source_hash") != current_hash)
        item["protocol_readiness"] = violation_protocol_readiness(item)
    else:
        item["recommendation"] = None
        item["justification_draft"] = ""
        item["justification_template_key"] = ""
    return item


def save_violation_document_review(report_id: str, source: str, document_id: str,
                                   file_unavailable: bool, checked_by: str = "УО") -> dict:
    if source not in {"customer", "supplier"}:
        raise ValueError("Невідоме джерело документа")
    with db() as con:
        report = con.execute("SELECT * FROM violation_reports WHERE id=? OR report_id=?", (report_id, report_id)).fetchone()
        if not report:
            raise KeyError(report_id)
        require_owned_violation_report(report)
        raw = json.loads(report["raw_json"] or "{}")
        if raw.get("decisions"):
            raise PermissionError("У Prozorro вже є офіційне рішення адміністратора. Картка доступна лише для перегляду.")
        documents = (json.loads(report["evidence_documents_json"] or "[]") if source == "customer" else
                     [document for statement in raw.get("defendantStatements") or []
                      for document in statement.get("documents") or []])
        document = next((item for item in documents if str(item.get("id") or "") == document_id), None)
        if not document:
            raise ValueError("Документ не знайдено у складі звернення")
        previous = con.execute("""SELECT file_unavailable FROM violation_report_document_reviews
                                  WHERE report_id=? AND document_source=? AND document_id=?""",
                               (report["id"], source, document_id)).fetchone()
        now, actor, value = now_iso(), str(checked_by or CURRENT_USER), int(bool(file_unavailable))
        con.execute("""INSERT INTO violation_report_document_reviews
          (report_id,document_source,document_id,original_title,original_url,file_unavailable,checked_at,checked_by)
          VALUES (?,?,?,?,?,?,?,?)
          ON CONFLICT(report_id,document_source,document_id) DO UPDATE SET
            original_title=excluded.original_title,original_url=excluded.original_url,
            file_unavailable=excluded.file_unavailable,checked_at=excluded.checked_at,checked_by=excluded.checked_by""",
          (report["id"], source, document_id, str(document.get("title") or ""),
           str(document.get("url") or ""), value, now, actor))
        old_value = None if previous is None else str(int(previous["file_unavailable"]))
        if old_value != str(value):
            con.execute("""INSERT INTO violation_report_review_events
              (report_id,event_type,field_name,old_value,new_value,changed_at,changed_by)
              VALUES (?,?,?,?,?,?,?)""", (report["id"], "document_reviewed",
              f"document_unavailable:{source}:{document_id}", old_value, str(value), now, actor))
    return violation_report_detail(report["id"], refresh=False)


def save_violation_review(report_id: str, payload: dict, updated_by: str = "УО") -> dict:
    require_local_violation_report_owned(report_id)
    try:
        fresh = _fresh_violation_report(report_id)
    except Exception as exc:
        raise ConnectionError(f"Не вдалося перевірити актуальний стан у Prozorro: {exc}") from exc
    require_owned_violation_report({"authority_code": _organization_fields(fresh.get("authority"))[1]})
    if fresh.get("decisions"):
        raise PermissionError("У Prozorro вже є офіційне рішення адміністратора. Картку переведено в режим лише для перегляду.")
    action = str(payload.get("action") or "save")
    with db() as con:
        report = con.execute("SELECT * FROM violation_reports WHERE id=? OR report_id=?", (report_id, report_id)).fetchone()
        if not report:
            raise KeyError(report_id)
        existing_row = con.execute("SELECT * FROM violation_report_reviews WHERE report_id=?", (report["id"],)).fetchone()
        existing = dict(existing_row) if existing_row else {}
        values = {key: payload[key] for key in VIOLATION_REVIEW_FIELDS if key in payload}
        if values.get("review_status", "") not in {"", "not_reviewed", "in_review", "reviewed"}:
            raise ValueError("Невідомий статус розгляду")
        if values.get("internal_decision", "") not in VIOLATION_INTERNAL_DECISIONS:
            raise ValueError("Невідоме внутрішнє рішення УО")
        for key in ("contract_deadline_extended", "additional_check_required"):
            if key in values: values[key] = int(bool(values[key]))
        for key in ("court_decision_final_present", "guarantee_documents_visible"):
            if key in values:
                if values[key] in (None, ""):
                    values[key] = None
                elif isinstance(values[key], str):
                    values[key] = int(values[key].strip().lower() in {"1", "true", "yes", "так"})
                else:
                    values[key] = int(bool(values[key]))
        if "assigned_officer_id" in values:
            officer_id = values["assigned_officer_id"]
            officer = con.execute("SELECT id,full_name,active FROM authorized_officers WHERE id=?", (officer_id,)).fetchone() if officer_id else None
            if officer_id and (not officer or not officer["active"]):
                raise ValueError("Оберіть активну уповноважену особу")
            values["assigned_officer_id"] = officer["id"] if officer else None
            values["assigned_officer"] = officer["full_name"] if officer else existing.get("assigned_officer", "")
        meaningful = any(str(value or "").strip() for key, value in values.items() if key != "review_status")
        if meaningful and values.get("review_status", existing.get("review_status", "not_reviewed")) == "not_reviewed":
            values["review_status"] = "in_review"
        report_dict = dict(report)
        report_dict["evidence_documents"] = json.loads(report_dict.pop("evidence_documents_json") or "[]")
        report_dict["decision_documents"] = json.loads(report_dict.pop("decision_documents_json") or "[]")
        raw = json.loads(report_dict.pop("raw_json") or "{}")
        report_dict["defendant_statements"] = raw.get("defendantStatements") or []
        deadlines = violation_deadline_control(report_dict)
        final_status = values.get("review_status", existing.get("review_status", "not_reviewed"))
        final_decision = values.get("internal_decision", existing.get("internal_decision", ""))
        discrepancy = str(values.get("established_discrepancy", existing.get("established_discrepancy", "")) or "").strip()
        if final_status == "reviewed":
            raise ValueError("Статус «Розглянуто» встановлюється лише окремою дією «Завершити розгляд»")
        now = now_iso()
        con.execute("INSERT OR IGNORE INTO violation_report_reviews(report_id,updated_at,updated_by) VALUES (?,?,?)",
                    (report["id"], now, updated_by))
        if action == "regenerate_justification":
            if not deadlines["supplier_ready"]:
                raise ValueError("Обґрунтування рішення буде доступне після завершення строку для надання пояснень та документів постачальника.")
            merged = {**existing, **values}
            try:
                context = build_procurement_context(report_dict, merged)
            except Exception:
                context = {}
            draft = build_violation_decision_justification(report_dict, context, merged)
            template_key = violation_decision_template_key(report_dict, context, merged)
            if not draft or not template_key:
                raise ValueError("Для цієї комбінації підстави, рішення та фактів погоджений шаблон ще не налаштовано")
            values["decision_justification"] = draft
            values["decision_template_key"] = template_key
            values["justification_source_hash"] = _justification_hash(report_dict, context, {**merged, **values})
            values["justification_generated_at"] = now
            values["justification_manually_edited"] = 0
        elif "decision_justification" in values and values["decision_justification"] != existing.get("decision_justification", ""):
            values["justification_manually_edited"] = 1
        if values:
            assignments = ",".join(f"{key}=?" for key in values)
            con.execute(f"UPDATE violation_report_reviews SET {assignments},updated_at=?,updated_by=? WHERE report_id=?",
                        (*values.values(), now, updated_by, report["id"]))
            event_type = "justification_regenerated" if action == "regenerate_justification" else "review_updated"
            for key, value in values.items():
                old = existing.get(key)
                if old != value:
                    con.execute("""INSERT INTO violation_report_review_events
                      (report_id,event_type,field_name,old_value,new_value,changed_at,changed_by)
                      VALUES (?,?,?,?,?,?,?)""", (report["id"], event_type, key,
                      None if old is None else str(old), None if value is None else str(value), now, updated_by))
    return violation_report_detail(report["id"], refresh=False)


def violation_protocol_type(report: dict, review: dict) -> str:
    decision, reason = str(review.get("internal_decision") or ""), str(report.get("reason") or "")
    if decision == "warning":
        return "warning"
    if decision == "decline" and reason in {"contractBreach", "signingRefusal"}:
        return "decline_p49_1_2"
    if decision == "decline" and reason == "goodsNonCompliance":
        return "decline_p49_3"
    return ""


def violation_protocol_readiness(item: dict, protocol_number: str = "", protocol_date: str = "") -> dict:
    review, deadline = item.get("review") or {}, item.get("deadline_control") or {}
    number = str(protocol_number or review.get("protocol_number") or "").strip()
    date = str(protocol_date or review.get("protocol_date") or "").strip()
    reasons = []
    if item.get("refresh_error"):
        reasons.append("Неможливо перевірити актуальний стан Prozorro")
    if item.get("has_official_decision"):
        reasons.append("У Prozorro вже оприлюднено рішення")
    if not deadline.get("supplier_ready"):
        reasons.append("Не завершився офіційний строк постачальника")
    if not (review.get("assigned_officer_id") or review.get("assigned_officer")):
        reasons.append("Не призначена відповідальна УО")
    if not violation_protocol_type(item, review):
        reasons.append("Не визначено підтримуваний тип протоколу для рішення і підстави")
    if not str(review.get("decision_justification") or "").strip():
        reasons.append("Не заповнене обґрунтування рішення")
    if not number:
        reasons.append("Не введено номер протоколу")
    if not date:
        reasons.append("Не введено дату протоколу")
    context = item.get("procurement_context") or {}
    if not context.get("available"):
        reasons.append("Не отримано актуальні відомості закупівлі")
    if item.get("reason") in {"contractBreach", "signingRefusal"} and not context.get("winner_selected_at"):
        reasons.append("Не визначено дату визначення переможцем")
    if item.get("reason") == "signingRefusal" and not review.get("written_refusal_date"):
        reasons.append("Не вказано дату письмової відмови")
    return {"ready": not reasons, "reasons": reasons, "protocol_type": violation_protocol_type(item, review),
            "protocol_number": number, "protocol_date": date}


def _protocol_date(value) -> str:
    raw = str(value or "")[:10]
    return ".".join(reversed(raw.split("-"))) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) else raw


def merged_review_requires_discrepancy(report: dict, review: dict) -> bool:
    """Require a discrepancy only when the UO explicitly uses that factual scenario."""
    if str(review.get("internal_decision") or "") != "decline":
        return False
    return bool(review.get("additional_check_required") or str(review.get("established_discrepancy") or "").strip())


def complete_violation_review(report_id: str, completed_by: str) -> dict:
    """Complete the internal review without changing any official Prozorro state."""
    require_local_violation_report_owned(report_id)
    item = violation_report_detail(report_id, refresh=True)
    require_owned_violation_report(item)
    if item.get("has_official_decision"):
        raise PermissionError("У Prozorro вже є офіційне рішення адміністратора. Картка доступна лише для перегляду.")
    review = item.get("review") or {}
    deadline = item.get("deadline_control") or {}
    if not deadline.get("supplier_ready"):
        raise ValueError("Завершення розгляду недоступне до завершення офіційного строку постачальника")
    if not review.get("internal_decision"):
        raise ValueError("Для завершення розгляду оберіть рішення УО")
    if merged_review_requires_discrepancy(item, review) and not str(review.get("established_discrepancy") or "").strip():
        raise ValueError("Для обраного сценарію зафіксуйте встановлену невідповідність")
    now = now_iso()
    with db() as con:
        report = con.execute("SELECT id FROM violation_reports WHERE id=? OR report_id=?", (report_id, report_id)).fetchone()
        if not report:
            raise KeyError(report_id)
        current = con.execute("SELECT review_status,completed_at,completed_by FROM violation_report_reviews WHERE report_id=?", (report["id"],)).fetchone()
        if not current:
            raise ValueError("Робочу картку звернення не знайдено")
        if current["completed_at"]:
            return {"review_status": "reviewed", "completed_at": current["completed_at"], "completed_by": current["completed_by"], "already_completed": True}
        con.execute("""UPDATE violation_report_reviews SET review_status='reviewed',reviewed_at=?,
          completed_at=?,completed_by=?,updated_at=?,updated_by=? WHERE report_id=?""",
          (now, now, completed_by, now, completed_by, report["id"]))
        con.execute("""INSERT INTO violation_report_review_events
          (report_id,event_type,field_name,old_value,new_value,changed_at,changed_by)
          VALUES (?,?,?,?,?,?,?)""", (report["id"], "review_completed", "review_status",
          current["review_status"], "reviewed", now, completed_by))
    return {"review_status": "reviewed", "completed_at": now, "completed_by": completed_by}


def generate_violation_protocol(report_id: str, payload: dict, generated_by: str = CURRENT_USER) -> dict:
    # violation_report_detail performs the mandatory fail-closed fresh Prozorro read.
    require_local_violation_report_owned(report_id)
    item = violation_report_detail(report_id, refresh=True)
    require_owned_violation_report(item)
    gate = violation_protocol_readiness(item, payload.get("protocol_number", ""), payload.get("protocol_date", ""))
    if not gate["ready"]:
        raise ValueError("; ".join(gate["reasons"]))
    review, context = item.get("review") or {}, item.get("procurement_context") or {}
    statements = item.get("defendant_statements") or []
    supplier_documents = [doc for statement in statements for doc in statement.get("documents") or []]
    supplier_text = "\n\n".join(str(statement.get("description") or statement.get("title") or "").strip()
                                  for statement in statements).strip() or "Пояснення постачальника не надано"
    reason_number = {"contractBreach": "1", "signingRefusal": "2", "goodsNonCompliance": "3"}.get(item.get("reason"), "")
    customer_name = str(review.get("customer_verified_full_name") or item.get("author_name") or "—")
    supplier_name = str((item.get("supplier_verified") or {}).get("full_name") or item.get("defendant_name") or "—")
    values = {
        "протокол уо номер": gate["protocol_number"], "номер протоколу": gate["protocol_number"],
        "дата протоколу": _protocol_date(gate["protocol_date"]), "дата": _protocol_date(gate["protocol_date"]),
        "уо": str(review.get("assigned_officer") or CURRENT_USER), "піб уо": str(review.get("assigned_officer") or CURRENT_USER),
        "№ рядка джерела": str(item.get("report_id") or item.get("id")), "номер звернення": str(item.get("report_id") or item.get("id")),
        "дата звернення": _protocol_date(item.get("date_published")), "номер закупівлі": str(item.get("tender_pretty_id") or "—"),
        "дата оголошення": _protocol_date(context.get("tender_date_published") or item.get("date_created")),
        "предмет закупівлі": str(context.get("tender_title") or item.get("description") or "—"),
        "код дк": str(context.get("dk_code") or "—"), "дк": str(context.get("dk_code") or "—"),
        "замовник": customer_name, "замовник в р в": customer_name, "замовника": customer_name,
        "єдрпоу замовника": str(item.get("author_code") or "—"),
        "постачальник": supplier_name, "постачальника": supplier_name, "постачальнику": supplier_name,
        "постачальником": supplier_name, "постачальник а": supplier_name,
        "єдрпоу/рнокпп постачальника": str(item.get("defendant_code") or "—"), "єдрпоу постачальника": str(item.get("defendant_code") or "—"),
        "пп п 49": reason_number, "пп. п. 49": reason_number, "тип порушення": str(item.get("reason") or "—"),
        "суть порушення": str(item.get("description") or "—"),
        "дата визначення переможцем": _protocol_date(context.get("winner_selected_at")),
        "граничний строк": _protocol_date(context.get("contract_deadline") or context.get("written_refusal_deadline")),
        "дата відхилення": _protocol_date(context.get("rejection_date")), "підстава відхилення": str(context.get("rejection_title") or context.get("rejection_description") or "—"),
        "дата письмової відмови": _protocol_date(review.get("written_refusal_date")), "вих. №": str(review.get("written_refusal_number") or "—"),
        "дата рішення замовника": _protocol_date(review.get("customer_protocol_decision_date")),
        "№ рішення замовника": str(review.get("customer_protocol_decision_number") or "—"),
        "посилання на рішення замовника": str(review.get("customer_protocol_decision_url") or ""),
        "дата договору": _protocol_date(review.get("actual_contract_date") or context.get("contract_date")),
        "номер договору": str(review.get("actual_contract_number") or context.get("contract_pretty_id") or "—"),
        "пояснення постачальника": supplier_text, "рішення": "Попередження" if gate["protocol_type"] == "warning" else "Відмова",
        "3 к.д.": _protocol_date(context.get("day_3")), "5 к.д.": _protocol_date(context.get("day_5")),
    }
    flags = {
        "written_refusal": item.get("reason") == "signingRefusal" or bool(review.get("written_refusal_url")),
        "contract": bool(review.get("actual_contract_date") or review.get("actual_contract_number") or context.get("contract_info_required")),
        "guarantee": bool(context.get("contract_guarantee_required")),
        "civil_code": bool(context.get("day_3_shifted")),
        "court": item.get("reason") == "goodsNonCompliance",
    }
    safe_report = safe_archive_name(str(item.get("report_id") or item.get("id")), "report")
    decision_name = "Попередження" if gate["protocol_type"] == "warning" else "Відмова"
    safe_customer = safe_archive_name(customer_name, "Замовник")[:48]
    safe_supplier = safe_archive_name(supplier_name, "Постачальник")[:48]
    safe_date = str(gate["protocol_date"] or "").replace(".", "-")
    filename = f"{safe_report}_{decision_name}_{safe_customer}_{safe_supplier}_{safe_date}.docx"
    output = PROTOCOLS_DIR / filename
    PROTOCOLS_DIR.mkdir(parents=True, exist_ok=True)
    temporary = PROTOCOLS_DIR / f".{safe_report}.{uuid.uuid4().hex}.tmp.docx"
    try:
        build_violation_protocol_docx(gate["protocol_type"], temporary, values,
            str(review.get("decision_justification") or ""), item.get("evidence_documents") or [], supplier_documents,
            flags, {"замовник в р в", "замовника", "постачальника", "постачальнику", "постачальником"})
        if not temporary.is_file():
            raise RuntimeError("Генератор не створив DOCX")
        os.replace(temporary, output)
    except PermissionError as exc:
        temporary.unlink(missing_ok=True)
        raise ValueError("Не вдалося оновити протокол: закрийте поточний DOCX у Word та повторіть формування.") from exc
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    # Generation creates/updates the current document only. Internal completion
    # is a separate explicit UO action.
    now = now_iso()
    with db() as con:
        report = con.execute("SELECT id FROM violation_reports WHERE id=? OR report_id=?",
                             (report_id, report_id)).fetchone()
        if not report:
            raise KeyError(report_id)
        con.execute("INSERT OR IGNORE INTO violation_report_reviews(report_id,updated_at,updated_by) VALUES (?,?,?)",
                    (report["id"], now, CURRENT_USER))
        previous = con.execute("SELECT review_status,protocol_number,protocol_date,generated_protocol_filename FROM violation_report_reviews WHERE report_id=?",
                               (report["id"],)).fetchone()
        con.execute("""UPDATE violation_report_reviews
                       SET protocol_number=?,protocol_date=?,generated_protocol_filename=?,protocol_generated_at=?,updated_at=?,updated_by=?
                       WHERE report_id=?""",
                    (gate["protocol_number"], gate["protocol_date"], filename, now, now, generated_by, report["id"]))
        changes = {
            "protocol_number": (previous["protocol_number"], gate["protocol_number"]),
            "protocol_date": (previous["protocol_date"], gate["protocol_date"]),
            "generated_protocol_filename": (previous["generated_protocol_filename"], filename),
        }
        for field, (old, new) in changes.items():
            if old != new:
                con.execute("""INSERT INTO violation_report_review_events
                  (report_id,event_type,field_name,old_value,new_value,changed_at,changed_by)
                  VALUES (?,?,?,?,?,?,?)""",
                  (report["id"], "protocol_generated", field,
                   None if old is None else str(old), str(new), now, generated_by))
    previous_filename = str(previous["generated_protocol_filename"] or "")
    if previous_filename and previous_filename != filename:
        previous_path = PROTOCOLS_DIR / Path(previous_filename).name
        try:
            previous_path.unlink(missing_ok=True)
        except PermissionError:
            SERVER_LOG.warning("Previous generated protocol remains locked report=%s file=%s",
                               safe_report, previous_path.name)
    return {**gate, "filename": filename,
            "download_url": "/api/protocol/files/" + urllib.parse.quote(filename),
            "review_status": review.get("review_status") or "in_review"}


def safe_archive_name(value: str, fallback: str) -> str:
    name = (value or fallback).strip().replace("\\", "_").replace("/", "_")
    name = "".join("_" if char in '<>:"|?*' or ord(char) < 32 else char for char in name)
    return name[:180] or fallback


def application_documents(submission_id: str) -> tuple[str, list[tuple[str, dict]]] | None:
    with db() as con:
        row = con.execute("""SELECT s.supplier_name, s.documents_json,
          q.documents_json qualification_documents,
          (SELECT rc.milestones_json FROM registry_contracts rc
           WHERE rc.qualification_id=q.id ORDER BY rc.synced_at DESC LIMIT 1) registry_milestones
          FROM submissions s LEFT JOIN qualifications q ON q.id=s.qualification_id
          WHERE s.id=?""", (submission_id,)).fetchone()
    if not row:
        return None
    grouped = [
        ("01-заявка", json.loads(row["documents_json"] or "[]")),
        ("02-кваліфікація", json.loads(row["qualification_documents"] or "[]")),
        ("03-реєстр", registry_details(row["registry_milestones"], None)["registry_documents"]),
    ]
    documents, seen = [], set()
    for folder, items in grouped:
        for document in items:
            key = document.get("url") or document.get("id")
            if key and key not in seen:
                seen.add(key)
                documents.append((folder, document))
    return row["supplier_name"] or submission_id, documents


def build_application_archive(submission_id: str, opener=urllib.request.urlopen):
    collected = application_documents(submission_id)
    if not collected:
        return None
    supplier_name, documents = collected
    archive = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
    manifest, used_names = [], set()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for index, (folder, document) in enumerate(documents, 1):
            title = safe_archive_name(document.get("title", ""), f"document-{index}")
            entry_name = f"{folder}/{title}"
            stem, suffix = os.path.splitext(entry_name)
            counter = 2
            while entry_name.casefold() in used_names:
                entry_name = f"{stem} ({counter}){suffix}"
                counter += 1
            used_names.add(entry_name.casefold())
            record = {"folder": folder, "title": document.get("title", ""), "url": document.get("url", ""), "file": entry_name}
            try:
                request = urllib.request.Request(document["url"], headers={"User-Agent": "PQM/0.1"})
                with opener(request, timeout=60, context=ssl.create_default_context()) as response:
                    bundle.writestr(entry_name, response.read())
                record["status"] = "downloaded"
            except Exception as exc:
                record.update(status="error", error=str(exc))
            manifest.append(record)
        bundle.writestr("manifest.json", json.dumps({
            "submission_id": submission_id,
            "supplier_name": supplier_name,
            "created_at": now_iso(),
            "documents": manifest,
        }, ensure_ascii=False, indent=2))
    archive.seek(0, os.SEEK_END)
    size = archive.tell()
    archive.seek(0)
    return archive, size


def normalized_value(value: str) -> str:
    return "".join(char for char in (value or "").casefold() if char.isalnum())


def download_document(document: dict, limit: int = 25 * 1024 * 1024) -> bytes:
    request = urllib.request.Request(document["url"], headers={"User-Agent": "PQM/0.1"})
    with urllib.request.urlopen(request, timeout=60, context=ssl.create_default_context()) as response:
        length = int(response.headers.get("Content-Length") or 0)
        if length > limit:
            raise ValueError("Файл перевищує 25 МБ")
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Файл перевищує 25 МБ")
        return data


def pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        return "\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages[:30])[:250000]
    except Exception:
        return ""


def pdf_has_unreadable_pages(data: bytes, max_pages: int = 12) -> bool:
    """Detect mixed PDFs where only some pages have a usable text layer."""
    try:
        from pypdf import PdfReader
        pages = PdfReader(io.BytesIO(data)).pages[:max_pages]
        if len(pages) < 2:
            return False
        lengths = [len(re.sub(r"\s+", "", page.extract_text() or "")) for page in pages]
        return any(length < 40 for length in lengths) and any(length >= 80 for length in lengths)
    except Exception:
        return False


def pdf_ocr_text(data: bytes, max_pages: int = 12) -> str:
    if not (TESSERACT_EXE.is_file() and (TESSDATA_DIR / "ukr.traineddata").is_file() and PDFTOPPM_EXE.is_file()):
        return ""
    with tempfile.TemporaryDirectory(prefix="pqm-ocr-") as folder:
        folder_path = Path(folder)
        source = folder_path / "source.pdf"
        source.write_bytes(data)
        prefix = folder_path / "page"
        subprocess.run([str(PDFTOPPM_EXE), "-png", "-r", "220", "-f", "1", "-l", str(max_pages), str(source), str(prefix)],
                       check=True, capture_output=True, timeout=120)
        pages = sorted(folder_path.glob("page-*.png"))
        chunks = []
        for page in pages:
            result = subprocess.run([str(TESSERACT_EXE), str(page), "stdout", "-l", "ukr",
                                     "--tessdata-dir", str(TESSDATA_DIR), "--psm", "6"],
                                    check=True, capture_output=True, timeout=90)
            chunks.append(result.stdout.decode("utf-8", errors="replace"))
        return "\n".join(chunks)[:250000]


def _needs_ukrainian_ocr(text: str) -> bool:
    """Detect broken/transliterated PDF text layers before analysing content."""
    letters = re.findall(r"[A-Za-zА-Яа-яІіЇїЄєҐґ]", text or "")
    if not letters:
        return True
    cyrillic = sum(char.lower() in "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя" for char in letters)
    return cyrillic / len(letters) < 0.35


def _money_values(text: str) -> set[float]:
    values = set()
    for raw in re.findall(r"(?<!\d)(\d+(?:[ \u00a0]\d{3})*[,.]\d{2})(?!\d)", text or ""):
        try:
            values.add(round(float(raw.replace(" ", "").replace("\u00a0", "").replace(",", ".")), 2))
        except ValueError:
            pass
    return values


def _document_total(text: str, kind: str) -> float | None:
    """Prefer an explicitly labelled total over the largest number found."""
    normalized = re.sub(r"\s+", " ", text or "").casefold()
    # OCR often drops one trailing zero (for example, 88000.0 instead of
    # 88000.00). This remains safe because values are accepted only next to
    # explicit total labels below; arbitrary largest numbers are never used.
    # Limit the first digit group so a long IBAN followed by an amount cannot
    # be swallowed as one gigantic monetary value by the OCR parser.
    money_pattern = r"(?<!\d)(\d{1,10}(?:[ \u00a0]\d{3})*[,.]\d{1,2})(?!\d)"
    if kind == "payment":
        # Bank forms commonly place a standalone «СУМА» header on one line and
        # the amount on the next line beside an IBAN. Read that small block first.
        lines = (text or "").splitlines()
        for index, line in enumerate(lines):
            if not re.search(r"(?iu)\bсума\s*$", line.strip()):
                continue
            block = " ".join(lines[index:index + 3])
            candidates = []
            for match in re.finditer(money_pattern, block):
                try:
                    value = float(match.group(1).replace(" ", "").replace("\u00a0", "").replace(",", "."))
                except ValueError:
                    continue
                if 10 <= value <= 10_000_000_000:
                    candidates.append(value)
            if candidates:
                return round(max(candidates), 2)
    if kind == "invoice":
        # Typical VAT invoice footer: "Разом: 727,50 873,00" where the
        # second value is the payable total including VAT.
        dual_total = re.search(
            r"(?:разом|всього)\s*:?\s*" + money_pattern + r"[ \t]+" + money_pattern,
            (text or "").casefold(),
        )
        if dual_total:
            return round(float(dual_total.group(2).replace(" ", "").replace("\u00a0", "").replace(",", ".")), 2)
    labels = {
        "contract": (
            "всього з пдв", "всього із пдв", "разом з пдв",
            "загальна вартість", "загальна сума", "сума договору",
            "ціна договору", "вартість договору",
        ),
        "invoice": (
            "всього до сплати", "всього з пдв", "всього із пдв",
            "разом з пдв", "сума з пдв", "всього", "разом", "сума",
        ),
        "payment": ("сума платежу", "сума", "всього"),
    }.get(kind, ())
    for label in labels:
        start = 0
        while True:
            pos = normalized.find(label, start)
            if pos < 0:
                break
            window = normalized[pos:pos + 180]
            matches = list(re.finditer(money_pattern, window))
            if matches:
                candidates = []
                for match in matches:
                    try:
                        value = float(match.group(1).replace(" ", "").replace("\u00a0", "").replace(",", "."))
                    except ValueError:
                        continue
                    # IBAN/account numbers split by OCR can look like an enormous
                    # monetary value; section numbers and dates can look like 4.10.
                    if 10 <= value <= 10_000_000_000:
                        candidates.append(value)
                if candidates:
                    # A labelled area may also contain VAT or a unit price. The
                    # payable/contract total is the largest plausible amount there.
                    return round(max(candidates), 2)
            start = pos + len(label)
    # Do not guess from the largest number: it may be VAT, a unit price,
    # an address fragment, account details, or an OCR hallucination.
    return None


def _party_name_after_label(text: str, labels: tuple[str, ...]) -> str:
    """Read a buyer/payer name while tolerating OCR spacing and punctuation."""
    compact = re.sub(r"[\t\r]+", " ", text or "")
    for label in labels:
        match = re.search(rf"(?i)\b{label}\s*[:\-]?\s*([^\n]{{3,120}})", compact)
        if not match:
            continue
        value = re.split(
            r"(?i)\s+(?:адреса|код\s+(?:платника|за\s+єдрпоу)|єдрпоу|рнокпп|рахунок|р/р|договір)\b",
            match.group(1), maxsplit=1,
        )[0]
        value = re.sub(r"^[\s:;,.\-]+|[\s:;,.\-]+$", "", value)
        if value:
            return value
    return ""


def _normalized_person_name(value: str) -> tuple[str, ...]:
    value = re.sub(r"(?i)\b(?:фоп|фізична\s+особа[\s-]*підприємець)\b", " ", value or "")
    words = re.findall(r"[А-ЯІЇЄҐA-Z][А-ЯІЇЄҐа-яіїєґA-Za-z'’\-]+", value.upper())
    return tuple(word.replace("’", "'") for word in words if len(word) > 1)


def _document_counterparty_name(text: str, kind: str) -> str:
    if kind in ("contract", "invoice"):
        match = re.search(
            r"(?i)(?:фоп|фізична\s+особа\s*[\-–]?\s*підприємець)\s+"
            r"([А-ЯІЇЄҐA-Z][А-ЯІЇЄҐа-яіїєґA-Za-z'’\-]+\s+"
            r"[А-ЯІЇЄҐA-Z][А-ЯІЇЄҐа-яіїєґA-Za-z'’\-]+\s+"
            r"[А-ЯІЇЄҐA-Z][А-ЯІЇЄҐа-яіїєґA-Za-z'’\-]+)",
            text or "",
        )
        if match:
            return "ФОП " + re.sub(r"\s+", " ", match.group(1)).strip()
    return _party_name_after_label(text, (r"платник",) if kind == "payment" else (r"покупець",))


def _contract_reference(text: str) -> tuple[str, str] | None:
    """Return normalized contract number/date, ignoring punctuation and spaces."""
    for match in re.finditer(r"(?i)(?:договір|договор|дог\.?)(?P<body>.{0,100})", text or ""):
        body = re.sub(r"\s+", " ", match.group("body"))
        # Tesseract commonly reads the numero sign as "М" or "Мо".
        body = re.sub(r"(?i)(?<![А-ЯІЇЄҐA-Z])Мо?\s*(?=\d)", "№", body)
        number = re.search(r"(?i)(?:№|N)?\s*([A-ZА-ЯІЇЄҐ0-9][A-ZА-ЯІЇЄҐ0-9/_\-]*)", body)
        date = re.search(r"(?<!\d)(\d{1,2})\s*[./\-]\s*(\d{1,2})\s*[./\-]\s*(\d{4})(?!\d)", body)
        if number and date:
            normalized_number = re.sub(r"[^A-ZА-ЯІЇЄҐ0-9]", "", number.group(1).upper())
            normalized_date = f"{int(date.group(1)):02d}.{int(date.group(2)):02d}.{date.group(3)}"
            return normalized_number, normalized_date
    return None


def _business_document_rows(matches: list[dict], extracted_texts: dict[int, str], kind: str) -> tuple[list[dict], float | None]:
    """Build an auditable row per invoice/payment; never total unreadable rows silently."""
    rows = []
    for item in matches:
        text = extracted_texts.get(item["index"], "")
        amount = _document_total(text, kind) if text.strip() else None
        reference = _contract_reference(text) if text.strip() else None
        notes = []
        if not text.strip():
            notes.append("текст не прочитано")
        elif amount is None:
            notes.append("суму не визначено надійно")
        else:
            notes.append("підсумок прочитано")
        if not reference:
            notes.append("посилання на договір не визначено")
        rows.append({
            "document": item["title"],
            "amount": amount,
            "contract_reference": f"№ {reference[0]} від {reference[1]}" if reference else "",
            "notes": "; ".join(notes),
            "reliable": amount is not None,
        })
    total = round(sum(row["amount"] for row in rows), 2) if rows and all(row["amount"] is not None for row in rows) else None
    return rows, total


def analyze_business_document_set(files: list[dict], extracted_texts: dict[int, str], supplier_code: str) -> list[dict]:
    def find(*needles):
        return [item for item in files if any(word in (
            item["title"] + " " + item.get("source_title", "") + " " + extracted_texts.get(item["index"], "")[:12000]
        ).casefold() for word in needles)]

    contract = [item for item in find("договір", "договор", "dohovir", "dogovir", "contract")
                if not any(word in (item["title"] + " " + item.get("source_title", "")).casefold()
                           for word in ("довідка", "лист-відгук", "відгук"))]
    invoice = find("накладн", "видатков", "vydatkova", "vidatkova", "nakladna", "invoice")
    payment = find("платіж", "плат доруч", "платіжне доруч", "платеж", "platizh", "platij", "payment")
    bill = [item for item in files if (
        re.search(r"(?iu)\bрахунок(?:\s*-?\s*фактура)?\s*(?:№|N|#|Ме|Ne)", extracted_texts.get(item["index"], ""))
        or any(word in (item["title"] + " " + item.get("source_title", "")).casefold()
               for word in ("рахунок", "рахунок-фактура", "invoice"))
    )]
    checks = []
    for key, label, matches in (
        ("business_contract", "Файл договору", contract),
        ("business_invoice", "Файл видаткової накладної", invoice),
        ("business_payment", "Файл платіжного доручення", payment),
    ):
        checks.append({"key": key, "label": label, "status": "ok" if matches else "warning",
                       "detail": ("Знайдено: " + ", ".join(item["title"] for item in matches)) if matches else "Не знайдено у комплекті"})

    # Рахунок є додатковим, а не обов'язковим документом досвіду: показуємо його,
    # коли він знайдений, але не створюємо зайвого попередження за його відсутності.
    if bill:
        checks.append({"key": "business_bill", "label": "Файл рахунку", "status": "ok",
                       "detail": "Знайдено: " + ", ".join(item["title"] for item in bill)})

    business_summaries = {}
    for kind, label, matches in (
        ("invoice", "Таблиця видаткових накладних", invoice),
        ("payment", "Таблиця оплат", payment),
    ):
        if not matches:
            continue
        document_rows, document_total = _business_document_rows(matches, extracted_texts, kind)
        business_summaries[kind] = {"rows": document_rows, "total": document_total}
        unreadable_count = sum(row["amount"] is None for row in document_rows)
        checks.append({
            "key": f"business_{kind}_table",
            "label": label,
            "status": "ok" if document_total is not None else "warning",
            "detail": (f"Загальна сума: {document_total:.2f} грн" if document_total is not None else
                       f"Потрібна ручна перевірка: суму не визначено у {unreadable_count} з {len(document_rows)} документів"),
            "rows": document_rows,
            "total": document_total,
        })

    selected = {}
    if contract: selected["contract"] = contract[0]
    if invoice: selected["invoice"] = invoice[0]
    if payment: selected["payment"] = payment[0]
    texts = {kind: extracted_texts.get(item["index"], "") for kind, item in selected.items()}
    unreadable = [selected[kind]["title"] for kind, text in texts.items() if not text.strip()]
    for kind, label in (("contract", "Зміст договору"), ("invoice", "Зміст накладної"), ("payment", "Зміст платіжного доручення")):
        if kind not in selected:
            continue
        text = texts[kind]
        if not text.strip():
            checks.append({"key": f"business_{kind}_content", "label": label, "status": "warning",
                           "detail": "PDF є сканом або не має текстового шару — потрібне OCR/перевірка УО"})
            continue
        codes = set(re.findall(r"(?<!\d)(?:\d{8}|\d{10})(?!\d)", text))
        amounts = _money_values(text)
        total = _document_total(text, kind)
        # Keep the existing UI detail formatter, but feed it the labelled
        # document total instead of an unrelated largest numeric value.
        if total is not None:
            amounts = {total}
        details = ["прочитано через OCR" if selected[kind].get("ocr_used") else "прочитано з текстового шару",
                   f"код постачальника {supplier_code} " + ("знайдено" if supplier_code in codes else "не знайдено")]
        if amounts: details.append(f"визначена підсумкова сума {max(amounts):.2f}")
        checks.append({"key": f"business_{kind}_content", "label": label,
                       "status": "ok" if supplier_code and supplier_code in codes else "warning",
                       "detail": " · ".join(details)})
    if not (contract and invoice and payment):
        missing_kinds = []
        if not contract: missing_kinds.append("договір")
        if not invoice: missing_kinds.append("видаткові накладні")
        if not payment: missing_kinds.append("оплата")
        checks.append({
            "key": "business_parties",
            "label": "Ідентифікація постачальника та отримувача",
            "status": "warning",
            "detail": "Не виконано між трьома видами документів: не знайдено " + ", ".join(missing_kinds),
        })
        return checks
    if unreadable:
        checks.append({
            "key": "business_parties",
            "label": "Ідентифікація постачальника та отримувача",
            "status": "warning",
            "detail": "Не виконано: не вдалося прочитати " + ", ".join(unreadable),
        })
        return checks

    codes = {kind: set(re.findall(r"(?<!\d)(?:\d{8}|\d{10})(?!\d)", text)) for kind, text in texts.items()}
    supplier_everywhere = all(supplier_code in values for values in codes.values()) if supplier_code else False
    checks.append({"key": "business_supplier", "label": "Постачальник у трьох документах",
                   "status": "ok" if supplier_everywhere else "warning",
                   "detail": f"Код {supplier_code} знайдено в усіх документах" if supplier_everywhere else f"Перевірте код постачальника {supplier_code}"})
    counterparty_codes = {
        kind: values - ({supplier_code} if supplier_code else set()) for kind, values in codes.items()
    }
    names = {kind: _document_counterparty_name(text, kind) for kind, text in texts.items()}
    normalized_names = {kind: set(_normalized_person_name(value)) for kind, value in names.items()}
    shared_name_words = set.intersection(*normalized_names.values()) if all(normalized_names.values()) else set()
    names_match = len(shared_name_words) >= 3
    contract_payment_codes = counterparty_codes["contract"] & counterparty_codes["payment"]
    recipient_ok = names_match and bool(contract_payment_codes)
    recipient_detail = "Не вдалося автоматично підтвердити спільного отримувача"
    if recipient_ok:
        display_name = names["contract"] or names["invoice"] or names["payment"]
        recipient_detail = f"{display_name} · код {sorted(contract_payment_codes)[0]}"
    elif names_match:
        recipient_detail = f"ПІБ збігається: {names['contract'] or names['invoice']}; код потребує перевірки"
    checks.append({"key": "business_recipient", "label": "Отримувач / покупець",
                   "status": "ok" if recipient_ok else "warning", "detail": recipient_detail})
    totals = {
        "contract": _document_total(texts["contract"], "contract"),
        "invoice": (business_summaries.get("invoice") or {}).get("total"),
        "payment": (business_summaries.get("payment") or {}).get("total"),
    }
    common_total = totals["contract"] is not None and len(set(totals.values())) == 1
    checks.append({"key": "business_amount", "label": "Сума договору, накладної та оплати",
                   "status": "ok" if common_total else "error",
                   "detail": f"Збігається: {totals['contract']:.2f}" if common_total else
                             " · ".join(f"{kind}: {value:.2f}" if value is not None else f"{kind}: не прочитано" for kind, value in totals.items())})
    invoice_ref = _contract_reference(texts["invoice"])
    payment_ref = _contract_reference(texts["payment"])
    reference_ok = bool(invoice_ref and payment_ref == invoice_ref)
    reference_detail = "Не знайдено однакові реквізити договору в накладній та платіжці"
    if reference_ok:
        reference_detail = f"Договір № {invoice_ref[0]} від {invoice_ref[1]} збігається в накладній та платіжці"
    checks.append({"key": "business_payment_reference", "label": "Посилання на договір",
                   "status": "ok" if reference_ok else "warning", "detail": reference_detail})
    return checks


def compare_manual_contract_history(submission_id: str, supplier_code: str, contract_details: str) -> list[dict]:
    if not contract_details.strip():
        return [{"key": "contract_history", "label": "Попередні подання договору", "status": "warning",
                 "detail": "Заповніть вручну поле «Реквізити договору»"}]
    normalized = normalized_value(contract_details)
    with db() as con:
        rows = con.execute("""SELECT s.id,f.pretty_id,f.dk_code,s.documents_json,s.date_published,
          COALESCE(af.contract_details,'') contract_details
          FROM submissions s JOIN frameworks f ON f.id=s.framework_id
          JOIN application_fields af ON af.submission_id=s.id
          WHERE s.supplier_code=? AND s.id<>? AND af.contract_details<>''""", (supplier_code, submission_id)).fetchall()
    matches = []
    for row in rows:
        if normalized_value(row["contract_details"]) != normalized:
            continue
        documents = json.loads(row["documents_json"] or "[]")
        contract_docs = [doc for doc in documents if "договор" in (doc.get("title") or "").casefold() or "договір" in (doc.get("title") or "").casefold()]
        revision = ", ".join(f"{doc.get('title') or 'договір'} ({doc.get('dateModified') or doc.get('datePublished') or 'дата невідома'})" for doc in contract_docs) or "файл договору не ідентифіковано"
        matches.append(f"{row['pretty_id']} · ДК {row['dk_code'] or '—'} · {revision}")
    return [{"key": "contract_history", "label": "Попередні подання договору",
             "status": "warning" if matches else "ok",
             "detail": "; ".join(matches) if matches else "З такими реквізитами попередніх заявок цього контрагента не знайдено"}]


def certificate_details(data: bytes) -> dict:
    try:
        from cryptography.hazmat.primitives.serialization import pkcs7
        from cryptography.x509.oid import NameOID, ObjectIdentifier
        loaders = (pkcs7.load_der_pkcs7_certificates, pkcs7.load_pem_pkcs7_certificates)
        certificates = []
        for loader in loaders:
            try:
                certificates = loader(data)
                if certificates:
                    break
            except Exception:
                continue
        if not certificates:
            return {}
        certificate = certificates[0]
        def first(oid):
            values = certificate.subject.get_attributes_for_oid(oid)
            return values[0].value if values else ""
        organization = first(NameOID.ORGANIZATION_NAME)
        common_name = first(NameOID.COMMON_NAME)
        serial = first(NameOID.SERIAL_NUMBER)
        signer = " ".join(filter(None, [first(NameOID.SURNAME), first(NameOID.GIVEN_NAME)])) or common_name
        subject_text = certificate.subject.rfc4514_string()
        issuer_text = certificate.issuer.rfc4514_string()
        code_candidates = re.findall(r"(?<!\d)(?:\d{8}|\d{10})(?!\d)", " ".join([serial, organization, common_name, subject_text, issuer_text]))
        return {
            "signer": signer, "common_name": common_name, "organization": organization,
            "code": code_candidates[0] if code_candidates else "", "serial": serial,
            "valid_from": certificate.not_valid_before_utc.isoformat(),
            "valid_to": certificate.not_valid_after_utc.isoformat(),
            "subject": subject_text, "issuer": issuer_text,
            "certificate_found": True,
        }
    except Exception as exc:
        return {"certificate_found": False, "error": str(exc)}


def _node_binary() -> str:
    configured = os.environ.get("PQM_NODE_BINARY", "").strip()
    candidates = [
        configured,
        shutil.which("node") or "",
        str(Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("Node.js для перевірки КЕП не знайдено")


def verify_prozorro_eds(sign_url: str) -> dict:
    """Call the official Prozorro EDS package without exposing its raw response."""
    if not EDS_ADAPTER_PATH.is_file():
        return {"status": "technical_error", "error": "Адаптер перевірки КЕП не знайдено"}
    try:
        process = subprocess.run(
            [_node_binary(), str(EDS_ADAPTER_PATH)],
            input=json.dumps({"signUrl": sign_url}, ensure_ascii=False),
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=EDS_TIMEOUT_SECONDS,
            cwd=str(EDS_ADAPTER_PATH.parent),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "service_unavailable", "error": "Сервіс перевірки підпису не відповів вчасно"}
    except Exception:
        return {"status": "technical_error", "error": "Не вдалося запустити автоматичну перевірку підпису"}
    try:
        payload = json.loads((process.stdout or "").strip())
    except (TypeError, ValueError, json.JSONDecodeError):
        return {"status": "technical_error", "error": "Сервіс перевірки підпису повернув некоректну відповідь"}
    if not isinstance(payload, dict):
        return {"status": "technical_error", "error": "Сервіс перевірки підпису повернув некоректну відповідь"}
    return payload


def _document_date(value: str):
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def select_main_signature_document(documents: list[tuple[str, dict]], selection: dict | None) -> tuple[int | None, str]:
    """Resolve the exact submission signature selected by the UO, or a strict sign.p7s fallback."""
    selection = selection or {}
    manual = sorted(
        int(index) for index, categories in selection.items()
        if str(index).isdigit() and "signature" in (categories if isinstance(categories, list) else [])
    )
    if len(manual) > 1:
        raise ValueError("Залиште позначку «Підпис заявки» лише біля одного документа.")
    if manual:
        index = manual[0]
        if index < 0 or index >= len(documents):
            raise ValueError("Вибраний файл підпису не знайдено у поточній заявці.")
        return index, "manual"

    candidates = []
    for index, (_, document) in enumerate(documents):
        title = str(document.get("title") or document.get("title_en") or "").strip()
        if title.casefold() == "sign.p7s":
            candidates.append((index, _document_date(document.get("datePublished"))))
    if not candidates:
        return None, "none"
    if len(candidates) == 1:
        return candidates[0][0], "automatic"
    dated = [(index, published) for index, published in candidates if published is not None]
    if not dated:
        raise ValueError("Знайдено кілька файлів sign.p7s без коректної дати публікації. Виберіть підпис заявки вручну.")
    latest = max(published for _, published in dated)
    latest_indexes = [index for index, published in dated if published == latest]
    if len(latest_indexes) != 1:
        raise ValueError("Кілька файлів sign.p7s мають однакову останню дату публікації. Виберіть підпис заявки вручну.")
    return latest_indexes[0], "automatic"


def _digits(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _eds_signing_time(value: dict | None) -> str:
    value = value if isinstance(value, dict) else {}
    try:
        moment = datetime(
            int(value["year"]), int(value["month"]), int(value["day"]),
            int(value.get("hour", 0)), int(value.get("minute", 0)), int(value.get("second", 0)),
        )
        return moment.strftime("%d.%m.%Y %H:%M:%S")
    except (KeyError, TypeError, ValueError):
        return ""


def parse_ukrainian_date(value: str):
    for pattern in (r"(?<!\d)(\d{2})[.](\d{2})[.](\d{4})(?!\d)", r"(?<!\d)(\d{2})/(\d{2})/(\d{4})(?!\d)"):
        match = re.search(pattern, value or "")
        if match:
            try:
                return datetime(int(match.group(3)), int(match.group(2)), int(match.group(1))).date()
            except ValueError:
                return None
    return None


def analyze_mvs_extract(text: str, manager_name: str, submitted_at: str) -> dict:
    compact = re.sub(r"[ \t]+", " ", text or "")
    upper = compact.upper()
    extract_type = "full" if re.search(r"\bПОВНИЙ\b", upper) else "short" if re.search(r"\bСКОРОЧЕНИЙ\b", upper) else "unknown"

    person = ""
    person_match = re.search(
        r"ГРОМАДЯНИН\s*\(?КА\)?[^\r\n]*[\r\n]+\s*(.+?)\s*[\r\n]+\s*\d{2}[.]\d{2}[.]\d{4}\s+РОКУ\s+НАРОДЖЕННЯ",
        upper,
        re.DOTALL,
    )
    if person_match:
        candidate = re.sub(r"\([^)]*\)", "", person_match.group(1), flags=re.DOTALL)
        candidate = re.sub(r"\s+", " ", candidate).strip(" .,:;\t")
        if not re.search(r"\d", candidate) and 2 <= len(candidate.split()) <= 5:
            person = candidate

    manager_norm = normalized_value(manager_name)
    person_norm = normalized_value(person)
    person_match_status = bool(manager_norm and person_norm and manager_norm == person_norm)

    issue_date = None
    for pattern in (
        r"СТАНОМ\s+НА\s+(\d{2}[./]\d{2}[./]\d{4})",
        r"ДАТА\s+(?:ВИДАЧІ|ФОРМУВАННЯ)\s*[:\-]?\s*(\d{2}[./]\d{2}[./]\d{4})",
        r"ВИДАН(?:ИЙ|О)\s+(\d{2}[./]\d{2}[./]\d{4})",
    ):
        match = re.search(pattern, upper)
        if match:
            issue_date = parse_ukrainian_date(match.group(1))
            if issue_date:
                break
    submitted_date = None
    try:
        submitted_date = datetime.fromisoformat((submitted_at or "").replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        submitted_date = parse_ukrainian_date(submitted_at or "")
    age_days = (submitted_date - issue_date).days if issue_date and submitted_date else None

    def statement(pattern: str) -> dict:
        match = re.search(pattern + r"\s*[:\-]?\s*([^\r\n]+)", upper)
        value = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;\t") if match else ""
        return {"found": bool(match), "value": value, "absent": "ВІДСУТНІ" in value}

    criminal_liability = statement(r"ВІДОМОСТІ\s+ПРО\s+ПРИТЯГНЕННЯ\s+ДО\s+КРИМІНАЛЬНОЇ\s+ВІДПОВІДАЛЬНОСТІ")
    unspent_conviction = statement(r"ВІДОМОСТІ\s+ПРО\s+НАЯВНІСТЬ\s+НЕЗНЯТОЇ\s+ЧИ\s+НЕПОГАШЕНОЇ\s+СУДИМОСТІ")
    wanted_status = statement(r"ВІДОМОСТІ\s+ПРО\s+РОЗШУК")

    return {
        "type": extract_type,
        "person_name": person,
        "manager_name": manager_name or "",
        "person_matches_manager": person_match_status,
        "issue_date": issue_date.isoformat() if issue_date else "",
        "submitted_date": submitted_date.isoformat() if submitted_date else "",
        "age_days": age_days,
        "within_30_days": age_days is not None and 0 <= age_days <= 30,
        "criminal_liability": criminal_liability,
        "unspent_conviction": unspent_conviction,
        "wanted_status": wanted_status,
    }


def analyze_application_documents(submission_id: str, selection: dict | None = None) -> dict | None:
    with db() as con:
        row = con.execute("""SELECT s.supplier_name,s.supplier_code,s.date_published,f.pretty_id,
          COALESCE(af.manager_name,'') manager_name,COALESCE(af.contract_details,'') contract_details,COALESCE(af.authority_review,'') authority_review,
          COALESCE(af.mvs_seal_review,'') mvs_seal_review
          FROM submissions s JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN application_fields af ON af.submission_id=s.id WHERE s.id=?""", (submission_id,)).fetchone()
    collected = application_documents(submission_id)
    if not row or not collected:
        return None
    _, documents = collected
    selection = selection or {}
    main_signature_index, signature_selection_source = select_main_signature_document(documents, selection)
    selected_indexes = {int(index) for index in selection if str(index).isdigit()}
    selected_categories = {category for categories in selection.values() for category in categories}
    included_indexes = set(selected_indexes)
    if main_signature_index is not None:
        included_indexes.add(main_signature_index)
    files, downloaded, extracted_texts = [], {}, {}
    for index, (_, document) in enumerate(documents):
        if included_indexes and index not in included_indexes:
            continue
        title = document.get("title") or document.get("title_en") or f"Документ {index + 1}"
        item = {
            "index": index,
            "document_id": document.get("id", ""),
            "title": title,
            "source_title": document.get("title_en") or document.get("title_ru") or title,
            "format": document.get("format", ""),
            "url": document.get("url", ""),
            "document_type": document.get("documentType", ""),
            "hash": document.get("hash", ""),
            "datePublished": document.get("datePublished", ""),
            "dateModified": document.get("dateModified", ""),
        }
        try:
            data = download_document(document)
            downloaded[index] = data
            item["downloaded"] = True
            item["size"] = len(data)
            item["content_sha256"] = hashlib.sha256(data).hexdigest()
            if title.casefold().endswith(".pdf") or data[:4] == b"%PDF":
                text = pdf_text(data)
                if not text.strip() or _needs_ukrainian_ocr(text) or pdf_has_unreadable_pages(data):
                    try:
                        ocr_text = pdf_ocr_text(data)
                        if ocr_text.strip():
                            text = ocr_text
                            item["ocr_used"] = True
                    except Exception as exc:
                        item["ocr_error"] = str(exc)
                extracted_texts[index] = text
                item["text_available"] = bool(text.strip())
                item["text_preview"] = re.sub(r"\s+", " ", text)[:500]
        except Exception as exc:
            item.update(downloaded=False, error=str(exc))
        files.append(item)
    def is_signature(item):
        names = " ".join((item.get("title", ""), item.get("source_title", ""))).casefold()
        media_type = item.get("format", "").casefold()
        return names.endswith((".p7s", ".pk7")) or "pkcs7" in media_type or "pkcs-7" in media_type

    file_by_index = {item["index"]: item for item in files}
    signature_indexes = [item["index"] for item in files if is_signature(item)]
    selected_signature_document = file_by_index.get(main_signature_index) if main_signature_index is not None else None
    eds_result = verify_prozorro_eds(selected_signature_document.get("url", "")) if selected_signature_document else {
        "status": "unsupported_or_invalid", "error": "Файл sign.p7s не знайдено"
    }
    eds_signers = eds_result.get("signers") if isinstance(eds_result.get("signers"), list) else []
    eds_signer = eds_signers[0] if eds_signers and isinstance(eds_signers[0], dict) else {}
    supplier_code = row["supplier_code"] or ""
    supplier_name = row["supplier_name"] or ""
    manager_name = row["manager_name"] or ""
    supplier_digits = _digits(supplier_code)
    edrpou_code = _digits(eds_signer.get("subjectEDRPOUCode", ""))
    drfo_code = _digits(eds_signer.get("subjectDRFOCode", ""))
    signature_code = drfo_code if len(supplier_digits) == 10 else edrpou_code
    if not signature_code and len(supplier_digits) == 10:
        signature_code = edrpou_code
    code_comparison = "match" if signature_code and signature_code == supplier_digits else "mismatch" if signature_code else "unreadable"
    code_match = code_comparison == "match"
    organization = str(eds_signer.get("subjectOrg") or "")
    signer_name = str(eds_signer.get("subjectCN") or "")
    org_norm, supplier_norm = normalized_value(organization), normalized_value(supplier_name)
    name_match = bool(org_norm and supplier_norm and (org_norm in supplier_norm or supplier_norm in org_norm))
    signer_norm, manager_norm = normalized_value(signer_name), normalized_value(manager_name)
    signer_match = bool(signer_norm and manager_norm and signer_norm == manager_norm)
    signer_comparison = "match" if signer_match else "manager_missing" if not manager_norm else "signer_unreadable" if not signer_norm else "mismatch"
    signature = {
        "technical_status": eds_result.get("status", "technical_error"),
        "technical_error": eds_result.get("error", ""),
        "signer_count": int(eds_result.get("signer_count") or len(eds_signers)),
        "signer": signer_name,
        "organization": organization,
        "edrpou_code": edrpou_code,
        "drfo_code": drfo_code,
        "code": signature_code,
        "signing_time": _eds_signing_time(eds_signer.get("time")),
        "issuer": str(eds_signer.get("issuerCN") or ""),
        "serial": str(eds_signer.get("serial") or ""),
        "is_time_available": eds_signer.get("isTimeAvail") is True,
        "is_timestamp": eds_signer.get("isTimeStamp") is True,
        "code_comparison": code_comparison,
        "signer_comparison": signer_comparison,
        "qualified_certificate": None,
    }
    mvs_docs = [item for item in files if not is_signature(item) and any(word in (item["title"] + " " + item.get("source_title", "") + " " + item.get("text_preview", "")).casefold() for word in ("мвс", "несудим", "витяг"))]
    def signature_base(title):
        clean = re.sub(r"\.(p7s|pk7)$", "", title, flags=re.I)
        return normalized_value(re.sub(r"(?:файл\s*підпису|підпис|sign)", "", clean, flags=re.I))
    mvs_pairs = []
    for document in mvs_docs:
        base = normalized_value(re.sub(r"\.pdf$", "", document["title"], flags=re.I))
        related = []
        for i in signature_indexes:
            signature_name = signature_base(file_by_index[i]["title"])
            if base and signature_name and (base in signature_name or signature_name in base):
                related.append(file_by_index[i])
        method = "name" if related else ""
        if not related:
            adjacent = next((file_by_index[i] for i in signature_indexes if i == document["index"] + 1 and any(word in (file_by_index[i]["title"] + " " + file_by_index[i].get("source_title", "")).casefold() for word in ("підпис", "sign", ".p7s"))), None)
            if adjacent:
                related = [adjacent]
                method = "adjacent"
        if not related:
            # Generic filenames cannot be associated by name. The MVS seal is
            # identified reliably by the organisation code in its certificate.
            certified_mvs = next((file_by_index[i] for i in signature_indexes
                                  if certificate_details(downloaded.get(i, b"")).get("code") == "00032684"), None)
            if certified_mvs:
                related = [certified_mvs]
                method = "mvs_certificate"
        mvs_pairs.append({"document": document["title"], "signature": related[0]["title"] if related else "", "signature_index": related[0]["index"] if related else None, "association": method})
    mvs_signature_index = next((pair["signature_index"] for pair in mvs_pairs if pair["signature_index"] is not None), None)
    primary_mvs_doc = mvs_docs[0] if mvs_docs else None
    mvs_extract = analyze_mvs_extract(
        extracted_texts.get(primary_mvs_doc["index"], "") if primary_mvs_doc else "",
        manager_name,
        row["date_published"] or "",
    )
    mvs_seal = certificate_details(downloaded.get(mvs_signature_index, b"")) if mvs_signature_index is not None else {}
    mvs_code_ok = mvs_seal.get("code") == "00032684"
    mvs_org_ok = "міністерствовнутрішніхсправукраїни" in normalized_value(mvs_seal.get("organization", "") or mvs_seal.get("common_name", ""))
    if mvs_seal.get("certificate_found"):
        mvs_seal_status = "ok" if mvs_code_ok and mvs_org_ok else "error"
        mvs_seal_detail = f"{mvs_seal.get('organization') or mvs_seal.get('common_name') or 'Організацію не прочитано'} · {mvs_seal.get('code') or 'код не прочитано'}"
    elif row["mvs_seal_review"] == "approved":
        mvs_seal_status, mvs_seal_detail = "ok", "Електронну печатку МВС підтверджено вручну через ЦЗО"
    elif row["mvs_seal_review"] == "rejected":
        mvs_seal_status, mvs_seal_detail = "error", "Електронна печатка не належить МВС або не підтверджена"
    else:
        mvs_seal_status, mvs_seal_detail = "warning", "Перевірте через ЦЗО: МВС України · ЄДРПОУ 00032684 · електронна печатка"
    authority_required = bool(signature.get("signer")) and (not manager_name or not signer_match)
    is_fop = len(supplier_digits) == 10 or normalized_value(supplier_name).startswith("фоп")
    eds_success = signature.get("technical_status") == "success"
    eds_technical_detail = signature.get("technical_error") or "Автоматичну перевірку виконано"
    code_detail = (
        f"{signature_code} · ✓ Відповідає коду Учасника" if code_comparison == "match" else
        f"{signature_code} · ⚠ Не відповідає коду Учасника (очікується {supplier_digits or '—'})" if code_comparison == "mismatch" else
        "⚠ Код не прочитано"
    )
    signer_detail = (
        f"{signer_name} · ✓ Збігається з ПІБ керівника" if signer_comparison == "match" else
        f"{signer_name} · ⚠ Не збігається з ПІБ керівника — перевірити повноваження" if signer_comparison == "mismatch" else
        f"{signer_name} · ⚠ ПІБ керівника не визначено" if signer_comparison == "manager_missing" else
        "⚠ ПІБ підписанта не прочитано"
    )
    checks = [
        {"key": "main_signature", "label": "Основний файл sign.p7s", "status": "ok" if main_signature_index is not None else "error", "detail": file_by_index[main_signature_index]["title"] if main_signature_index is not None else "Не знайдено"},
        {"key": "eds_verification", "label": "Автоматичне читання КЕП", "status": "ok" if eds_success else "warning", "detail": eds_technical_detail},
        {"key": "certificate_issuer", "label": "Видавець сертифіката", "status": "ok" if signature.get("issuer") else "warning", "detail": signature.get("issuer") or "Не прочитано"},
        {"key": "code", "label": "Код ЄДРПОУ / РНОКПП", "status": "ok" if code_match else "warning", "detail": code_detail},
        {"key": "organization", "label": "Назва організації", "status": "ok", "informational": True, "detail": organization or ("Не зазначено у КЕП (допустимо для ФОП)" if is_fop else "Не прочитано")},
        {"key": "signer", "label": "Підписант", "status": "ok" if signer_match else "warning", "detail": signer_detail},
        {"key": "signer_drfo", "label": "РНОКПП підписанта", "status": "ok" if drfo_code else "warning", "detail": drfo_code or "Не прочитано"},
        {"key": "signing_time", "label": "Дата/час підписання", "status": "ok" if signature.get("signing_time") else "warning", "detail": signature.get("signing_time") or "Не прочитано"},
        {"key": "authority", "label": "Повноваження підписанта", "status": "warning" if not signature.get("signer") or (authority_required and row["authority_review"] != "approved") else "ok", "detail": "Спочатку визначте підписанта через перевірку КЕП" if not signature.get("signer") else "Потрібна ручна перевірка" if authority_required and row["authority_review"] != "approved" else "Підтверджено"},
        {"key": "mvs_extract", "label": "Витяг МВС", "status": "ok" if mvs_docs else "error", "detail": ", ".join(item["title"] for item in mvs_docs) or "Не знайдено"},
        {"key": "mvs_extract_type", "label": "Тип витягу МВС", "status": "ok" if mvs_extract["type"] == "full" else "error" if mvs_extract["type"] == "short" else "warning", "detail": "ПОВНИЙ" if mvs_extract["type"] == "full" else "СКОРОЧЕНИЙ — не відповідає вимозі" if mvs_extract["type"] == "short" else "Не вдалося визначити тип витягу"},
        {"key": "mvs_person", "label": "ПІБ у витягу МВС", "status": "ok" if mvs_extract["person_matches_manager"] else "error" if mvs_extract["person_name"] and manager_name else "warning", "detail": f"{mvs_extract['person_name'] or 'Не прочитано'} · керівник: {manager_name or 'не визначений'}"},
        {"key": "mvs_age", "label": "Строк дії витягу — 30 к.д.", "status": "ok" if mvs_extract["within_30_days"] else "error" if mvs_extract["age_days"] is not None else "warning", "detail": (f"{mvs_extract['age_days']} к.д. · {mvs_extract['issue_date']} → {mvs_extract['submitted_date']}" if mvs_extract["age_days"] is not None else "Не вдалося визначити дату витягу або подання документів")},
        {"key": "mvs_seal", "label": "Електронна печатка МВС", "status": mvs_seal_status, "detail": mvs_seal_detail},
    ]
    for key, label in (
        ("criminal_liability", "МВС: притягнення до кримінальної відповідальності"),
        ("unspent_conviction", "МВС: незнята чи непогашена судимість"),
        ("wanted_status", "МВС: розшук"),
    ):
        statement = mvs_extract[key]
        checks.append({
            "key": f"mvs_{key}",
            "label": label,
            "status": "ok" if statement["absent"] else "error" if statement["found"] else "warning",
            "detail": statement["value"] if statement["found"] else "Не вдалося прочитати відповідний рядок у витягу",
        })
    checks.extend(analyze_business_document_set(files, extracted_texts, supplier_code))
    checks.extend(compare_manual_contract_history(submission_id, supplier_code, row["contract_details"]))
    if selected_categories:
        def selected_check(item):
            key = item["key"]
            if key.startswith("business_") or key == "contract_history":
                return "experience" in selected_categories
            if key.startswith("mvs_"):
                return bool({"mvs", "mvs_signature"} & selected_categories)
            return "signature" in selected_categories
        checks = [item for item in checks if selected_check(item)]
    counts = {status: sum(item["status"] == status for item in checks) for status in ("ok", "warning", "error")}
    checked_signature_document = None
    if selected_signature_document:
        checked_signature_document = {
            "index": selected_signature_document.get("index"),
            "document_id": selected_signature_document.get("document_id", ""),
            "title": selected_signature_document.get("title", ""),
            "url": selected_signature_document.get("url", ""),
            "hash": selected_signature_document.get("hash", ""),
            "content_sha256": selected_signature_document.get("content_sha256", ""),
            "datePublished": selected_signature_document.get("datePublished", ""),
            "selection_source": signature_selection_source,
        }
    return {
        "submission_id": submission_id, "supplier_name": supplier_name, "supplier_code": supplier_code,
        "pretty_id": row["pretty_id"], "manager_name": manager_name, "authority_review": row["authority_review"], "mvs_seal_review": row["mvs_seal_review"],
        "signature": signature, "checked_signature_document": checked_signature_document,
        "mvs_seal": mvs_seal, "mvs_extract": mvs_extract, "checks": checks, "files": files, "mvs_pairs": mvs_pairs,
        "counts": counts, "ready": counts["error"] == 0 and counts["warning"] == 0,
        "official_verification_url": "https://czo.gov.ua/verify",
        "selected_categories": sorted(selected_categories),
        "notice": "",
    }


def document_check_category(key: str) -> str:
    if key.startswith("business_") or key == "contract_history":
        return "experience"
    if key.startswith("mvs_"):
        return "mvs"
    return "signature"


def document_check_category_summaries(result: dict) -> dict:
    stored = result.get("category_results") if isinstance(result, dict) else None
    if isinstance(stored, dict):
        return {key: value.get("status", "warning") for key, value in stored.items() if isinstance(value, dict)}
    summaries = {}
    for check in result.get("checks", []) if isinstance(result, dict) else []:
        if not isinstance(check, dict):
            continue
        category = document_check_category(str(check.get("key") or ""))
        current = summaries.get(category, "ok")
        status = check.get("status", "warning")
        summaries[category] = "error" if "error" in {current, status} else "warning" if "warning" in {current, status} else "ok"
    return summaries


def merge_document_check_results(existing: dict, current: dict) -> dict:
    """Replace only categories checked in the current run; preserve all others."""
    category_results = {}
    existing_checks = existing.get("checks", []) if isinstance(existing, dict) else []
    if isinstance(existing.get("category_results") if isinstance(existing, dict) else None, dict):
        category_results.update(existing["category_results"])
    else:
        for category in ("signature", "mvs", "experience"):
            checks = [item for item in existing_checks if isinstance(item, dict) and document_check_category(str(item.get("key") or "")) == category]
            if checks:
                counts = {status: sum(item.get("status") == status for item in checks) for status in ("ok", "warning", "error")}
                category_results[category] = {"checks": checks, "counts": counts, "status": "error" if counts["error"] else "warning" if counts["warning"] else "ok"}
    selected = set(current.get("selected_categories") or [])
    if not selected:
        selected = {document_check_category(str(item.get("key") or "")) for item in current.get("checks", []) if isinstance(item, dict)}
    for category in selected:
        checks = [item for item in current.get("checks", []) if isinstance(item, dict) and document_check_category(str(item.get("key") or "")) == category]
        counts = {status: sum(item.get("status") == status for item in checks) for status in ("ok", "warning", "error")}
        category_results[category] = {"checks": checks, "counts": counts, "status": "error" if counts["error"] else "warning" if counts["warning"] else "ok", "checked_at": now_iso()}
    combined_checks = [item for category in ("signature", "mvs", "experience") for item in category_results.get(category, {}).get("checks", [])]
    combined_counts = {status: sum(item.get("status") == status for item in combined_checks) for status in ("ok", "warning", "error")}
    existing = existing or {}
    merged = dict(existing)
    merged.update(current)
    # A run for one document category must not replace detailed results of
    # another category that were saved earlier.
    if "signature" not in selected:
        for key in ("signature", "checked_signature_document"):
            if key in existing:
                merged[key] = existing[key]
    if "mvs" not in selected:
        for key in ("mvs_seal", "mvs_extract", "mvs_pairs"):
            if key in existing:
                merged[key] = existing[key]
    merged["category_results"] = category_results
    merged["checks"] = combined_checks
    merged["counts"] = combined_counts
    merged["ready"] = not combined_counts["error"] and not combined_counts["warning"]
    merged["checked_categories"] = sorted(category_results)
    return merged


def document_check_worker(job_id: str, submission_id: str, selection: dict | None = None) -> None:
    try:
        result = analyze_application_documents(submission_id, selection)
        if not result:
            raise ValueError("Заявку не знайдено")
        with db() as con:
            stored = con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id=?", (submission_id,)).fetchone()
            try:
                existing = json.loads(stored[0] or "{}") if stored else {}
            except (TypeError, ValueError):
                existing = {}
            result = merge_document_check_results(existing, result)
            counts = result.get("counts") or {}
            check_status = "error" if counts.get("error") else "warning" if counts.get("warning") else "ok"
            summary = f"Перевірено: {counts.get('ok', 0)}; попереджень: {counts.get('warning', 0)}; помилок: {counts.get('error', 0)}"
            con.execute("""INSERT INTO application_fields
              (submission_id,document_check_status,document_check_summary,document_checked_at,document_check_result_json,updated_at,updated_by)
              VALUES (?,?,?,?,?,?,?) ON CONFLICT(submission_id) DO UPDATE SET
              document_check_status=excluded.document_check_status,
              document_check_summary=excluded.document_check_summary,
              document_checked_at=excluded.document_checked_at,
              document_check_result_json=excluded.document_check_result_json,
              updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
              (submission_id, check_status, summary, now_iso(), json.dumps(result, ensure_ascii=False), now_iso(), "PQM auto-check"))
        update = {"status": "complete", "result": result}
    except Exception as exc:
        update = {"status": "error", "error": f"Не вдалося перевірити документи: {exc}"}
    with DOCUMENT_CHECK_LOCK:
        if job_id in DOCUMENT_CHECK_JOBS:
            DOCUMENT_CHECK_JOBS[job_id].update(update)


class Handler(BaseHTTPRequestHandler):
    server_version = "PQM/0.1"

    def send_json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def send_session(self, data, token: str, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode()
        secure = "; Secure" if IS_WEB_ENV else ""
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", f"{AUTH_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={AUTH_SESSION_TTL}{secure}")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def clear_session(self):
        secure = "; Secure" if IS_WEB_ENV else ""
        self.send_response(204); self.send_header("Set-Cookie", f"{AUTH_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0{secure}")
        self.end_headers()

    def send_file(self, path: Path, content_type: str, filename: str):
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")

    def send_error(self, code, message=None, explain=None):
        if urllib.parse.urlparse(self.path).path.startswith("/api/"):
            return self.send_json({"error": message or "Запит не виконано", "status": code}, code)
        return super().send_error(code, message, explain)

    def _authorize(self) -> bool:
        self.auth_user = CURRENT_USER
        self.auth_role = "admin" if not AUTH_ENABLED else "viewer"
        self.auth_officer_id = None
        if not AUTH_ENABLED:
            requested = str(self.headers.get("X-PQM-Local-Role") or "").strip().casefold()
            client_host = str((self.client_address or ("",))[0])
            if (LOCAL_ROLE_IMPERSONATION and client_host in {"127.0.0.1", "::1", "localhost"}
                    and requested in AUTH_ROLES):
                self.auth_role = requested
            return True
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/health" or path == "/api/login" or not path.startswith("/api/"):
            return True
        try:
            accounts = auth_accounts()
        except RuntimeError as exc:
            self.send_json({"error": str(exc), "status": 503}, 503)
            return False
        cookie = {}
        for item in self.headers.get("Cookie", "").split(";"):
            if "=" in item:
                key, value = item.strip().split("=", 1); cookie[key] = value
        token = cookie.get(AUTH_COOKIE, "")
        with AUTH_SESSIONS_LOCK:
            session = AUTH_SESSIONS.get(token)
            if session and session["expires_at"] > time.time():
                self.auth_user = session["username"]; self.auth_role = session["role"]
                self.auth_officer_id = session.get("officer_id"); return True
            if token:
                AUTH_SESSIONS.pop(token, None)
        header = self.headers.get("Authorization", "")
        try:
            scheme, encoded = header.split(" ", 1)
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            username = password = ""
            scheme = ""
        account = accounts.get(username)
        valid = bool(scheme.casefold() == "basic" and account and account.get("active", True)
                     and verify_basic_auth_secret(password, account["secret"]))
        if not valid:
            raw = json.dumps({"error": "Потрібна авторизація", "status": 401}, ensure_ascii=False).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return False
        self.auth_user = username
        self.auth_role = account["role"]
        self.auth_officer_id = account.get("officer_id")
        return True

    def _dispatch(self, method) -> None:
        if not self._authorize():
            return
        path = urllib.parse.urlparse(self.path).path
        if path in {"/api/login", "/api/logout"}:
            return method()
        if (path == "/api/admin/users" or re.fullmatch(r"/api/admin/users/[^/]+", path)) and self.auth_user != "manager":
            return self.send_json({"error": "Керування користувачами доступне лише manager", "status": 403}, 403)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if not admin_read_allowed(self.auth_role, path, query):
            return self.send_json({"error": "Недостатньо прав для перегляду цього розділу", "status": 403}, 403)
        if not mutation_allowed(self.auth_role, method, path):
            return self.send_json({"error": "Недостатньо прав для цієї дії", "status": 403}, 403)
        if (self.auth_role == "officer" and method in {"POST", "PATCH", "PUT", "DELETE"}
                and not officer_mutation_scope_allowed(path, self.auth_officer_id)):
            return self.send_json({"error": "Дія доступна лише для призначених вам заявок або звернень",
                                   "status": 403}, 403)
        try:
            method()
        except BidsUnavailableError as exc:
            self.send_json({"error": str(exc), "code": "bids_unavailable", "available": False}, 503)
        except json.JSONDecodeError:
            self.send_json({"error": "Некоректний JSON у запиті", "status": 400}, 400)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            path = urllib.parse.urlparse(self.path).path
            SERVER_LOG.exception("Unhandled HTTP exception method=%s path=%s type=%s",
                                 self.command, path, type(exc).__name__)
            traceback.print_exc()
            self.send_json({"error": "Внутрішня помилка сервера", "code": "internal_error", "status": 500}, 500)

    def do_GET(self):
        return self._dispatch(self._do_GET)

    def do_POST(self):
        return self._dispatch(self._do_POST)

    def do_PATCH(self):
        return self._dispatch(self._do_PATCH)

    def do_DELETE(self):
        return self._dispatch(self._do_DELETE)

    def _do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/health":
            with db() as con:
                counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("frameworks", "submissions", "qualifications")}
            return self.send_json({"ok": True, "counts": counts, "sync": SYNC_STATE})
        if parsed.path == "/api/auth/me":
            return self.send_json({"username": self.auth_user, "role": self.auth_role,
                                   "officer_id": self.auth_officer_id,
                                   "authenticated": bool(AUTH_ENABLED),
                                   "local_impersonation": bool(not AUTH_ENABLED and LOCAL_ROLE_IMPERSONATION)})
        if parsed.path == "/api/admin/users":
            with db() as con:
                rows = con.execute("""SELECT u.username,u.role,u.officer_id,u.active,u.created_at,u.updated_at,
                  o.full_name officer_name FROM auth_users u LEFT JOIN authorized_officers o ON o.id=u.officer_id
                  ORDER BY u.active DESC,u.username""").fetchall()
            return self.send_json({"items": [dict(row) for row in rows]})
        if parsed.path == "/api/runtime-features":
            return self.send_json({
                "environment": PQM_ENV,
                "bids_mode": BIDS_MODE,
                "bids_update": ENABLE_BIDS_UPDATE and BIDS_MODE in {"readonly", "read_only"},
                "powerbi": ENABLE_POWERBI,
                "google": ENABLE_GOOGLE,
                "scheduler": ENABLE_SCHEDULER,
                "nazk_scheduler": ENABLE_NAZK_SCHEDULER,
            })
        if parsed.path.startswith("/api/document-check-jobs/"):
            job_id = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1])
            with DOCUMENT_CHECK_LOCK:
                job = DOCUMENT_CHECK_JOBS.get(job_id)
                payload = dict(job) if job else None
            if not payload:
                return self.send_json({"error": "Завдання перевірки не знайдено"}, 404)
            return self.send_json(payload)
        if parsed.path.startswith("/api/applications/") and parsed.path.endswith("/document-check-result"):
            submission_id = urllib.parse.unquote(parsed.path.split("/")[3])
            with db() as con:
                row = con.execute("""SELECT document_check_status,document_check_summary,
                  document_checked_at,document_check_result_json,authority_review,mvs_seal_review
                  FROM application_fields WHERE submission_id=?""", (submission_id,)).fetchone()
            if not row or not row[3]:
                return self.send_json({"error": "Збереженого результату перевірки ще немає"}, 404)
            result = json.loads(row[3])
            result["authority_review"] = row[4] or ""
            result["mvs_seal_review"] = row[5] or ""
            result["saved_status"] = row[0] or ""
            result["saved_summary"] = row[1] or ""
            result["checked_at"] = row[2] or ""
            return self.send_json(result)
        if parsed.path.startswith("/api/applications/") and parsed.path.endswith("/nazk-control"):
            submission_id = urllib.parse.unquote(parsed.path.split("/")[3])
            try:
                with db() as con:
                    control = get_submission_nazk_control(con, submission_id)
                    if not control:
                        control = ensure_submission_nazk_control(con, submission_id)
                    state = get_submission_nazk_state(con, submission_id)
                    context = submission_nazk_context(con, submission_id)
                    documents = con.execute(
                        "SELECT documents_json FROM submissions WHERE id=?", (submission_id,)
                    ).fetchone()
                return self.send_json({"control": control, "state": state,
                    "documents": json.loads((documents or ["[]"])[0] or "[]"),
                    "context": context,
                    "coverage_status": "legal_date_field_unresolved"})
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 404)
        if parsed.path == "/api/nazk/reconciliation/dry-run":
            with db() as con:
                return self.send_json(reconcile_active_supplier_nazk(con, apply=False))
        if parsed.path == "/api/nazk/transitional-backfill/dry-run":
            query = urllib.parse.parse_qs(parsed.query)
            year = int((query.get("year") or ["2026"])[0] or 2026)
            with db() as con:
                return self.send_json(transitional_submission_backfill_dry_run(con, year))
        if parsed.path.startswith("/api/applications/") and parsed.path.endswith("/verify-documents/start"):
            parts = parsed.path.split("/")
            submission_id = urllib.parse.unquote(parts[3])
            raw_selection = urllib.parse.parse_qs(parsed.query).get("selection", [""])[0]
            try:
                selection = json.loads(raw_selection) if raw_selection else {}
                if not isinstance(selection, dict):
                    selection = {}
            except (TypeError, ValueError, json.JSONDecodeError):
                selection = {}
            job_id = uuid.uuid4().hex
            with DOCUMENT_CHECK_LOCK:
                DOCUMENT_CHECK_JOBS[job_id] = {"job_id": job_id, "submission_id": submission_id, "status": "running"}
            threading.Thread(target=document_check_worker, args=(job_id, submission_id, selection), daemon=True).start()
            return self.send_json({"job_id": job_id, "status": "running"}, 202)
        if parsed.path == "/api/applications":
            return self.send_json(list_applications(urllib.parse.parse_qs(parsed.query)))
        if parsed.path == "/api/suppliers-registry":
            return self.send_json(list_qualified_suppliers(urllib.parse.parse_qs(parsed.query)))
        if parsed.path.startswith("/api/supplier-profile/"):
            code = parsed.path.removeprefix("/api/supplier-profile/")
            try:
                return self.send_json(supplier_profile(code))
            except KeyError:
                return self.send_json({"error": "Постачальника не знайдено"}, 404)
        if parsed.path.startswith("/api/supplier-procurements/"):
            code = parsed.path.removeprefix("/api/supplier-procurements/")
            try:
                return self.send_json(supplier_procurements(code, urllib.parse.parse_qs(parsed.query)))
            except KeyError:
                return self.send_json({"error": "Постачальника не знайдено"}, 404)
        if parsed.path == "/api/admin/frameworks":
            return self.send_json(framework_service_directory())
        if parsed.path == "/api/admin/officers":
            query = urllib.parse.parse_qs(parsed.query)
            return self.send_json({"items": authorized_officers(query.get("active") == ["1"])})
        if parsed.path == "/api/admin/templates":
            return self.send_json({"items": template_metadata()})
        template_download = re.fullmatch(r"/api/admin/templates/([^/]+)/download", parsed.path)
        if template_download:
            key = urllib.parse.unquote(template_download.group(1))
            ensure_runtime_templates()
            path = TEMPLATES.get(key)
            if not path or not path.exists():
                return self.send_json({"error": "Шаблон не знайдено"}, 404)
            return self.send_file(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", path.name)
        if parsed.path == "/api/violation-reports":
            return self.send_json(list_violation_reports(urllib.parse.parse_qs(parsed.query)))
        if parsed.path == "/api/uo-work-queue":
            query = {key: values[0] if values else "" for key, values in urllib.parse.parse_qs(parsed.query).items()}
            with db() as con:
                return self.send_json(get_uo_work_queue(con, query, self.auth_user))
        if parsed.path.startswith("/api/violation-reports/") and not parsed.path.endswith("/sync"):
            report_id = urllib.parse.unquote(parsed.path.removeprefix("/api/violation-reports/"))
            try:
                return self.send_json(violation_report_detail(report_id))
            except KeyError:
                return self.send_json({"error": "Звернення не знайдено"}, 404)
        if parsed.path == "/api/stats":
            return self.send_json(application_stats(urllib.parse.parse_qs(parsed.query)))
        if parsed.path.startswith("/api/applications/") and parsed.path.endswith("/archive"):
            submission_id = urllib.parse.unquote(parsed.path.split("/")[3])
            result = build_application_archive(submission_id)
            if not result:
                return self.send_json({"error": "Заявку не знайдено"}, 404)
            archive, size = result
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="PQM-{submission_id}.zip"')
                self.send_header("Content-Length", str(size))
                self.end_headers()
                while chunk := archive.read(1024 * 1024):
                    self.wfile.write(chunk)
            finally:
                archive.close()
            return
        if parsed.path.startswith("/api/protocol/files/"):
            filename = urllib.parse.unquote(parsed.path[len("/api/protocol/files/"):])
            protocols_dir = PROTOCOLS_DIR
            target = (protocols_dir / filename).resolve()
            if protocols_dir not in target.parents or not target.is_file():
                return self.send_error(404)
            raw = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            self.send_header("Content-Disposition", "attachment; filename=protocol.docx; filename*=UTF-8''" + urllib.parse.quote(target.name))
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if parsed.path == "/api/frameworks":
            return self.send_json(list_frameworks())
        if parsed.path == "/api/framework-analytics":
            return self.send_json(framework_analytics(urllib.parse.parse_qs(parsed.query)))
        if parsed.path == "/api/bids-sync-status":
            query = urllib.parse.parse_qs(parsed.query)
            return self.send_json(bids_sync_status(force=query.get("refresh") == ["1"]))
        if parsed.path == "/api/powerbi-export-status":
            return self.send_json(powerbi_export_status())
        if parsed.path.startswith("/api/framework-analytics/"):
            agreement_id = urllib.parse.unquote(parsed.path[len("/api/framework-analytics/"):])
            try:
                result = framework_analytics_details(agreement_id, urllib.parse.parse_qs(parsed.query))
            except KeyError:
                return self.send_error(404)
            return self.send_json(result)
        if parsed.path == "/api/remarks-catalog":
            query = urllib.parse.parse_qs(parsed.query)
            return self.send_json(remarks_catalog(force=query.get("refresh") == ["1"]))
        if parsed.path == "/api/reference-status":
            return self.send_json(reference_status(DB_PATH))
        if parsed.path == "/api/supplier-edr-sync-status":
            return self.send_json(supplier_edr_sync_status())
        if parsed.path == "/api/supplier-nazk-review-sync-status":
            return self.send_json(supplier_nazk_review_sync_status())
        if parsed.path == "/api/google-oauth/status":
            return self.send_json(google_oauth_status())
        if parsed.path == "/api/google-oauth/callback":
            query = urllib.parse.parse_qs(parsed.query)
            try:
                if query.get("error"):
                    raise ValueError(query["error"][0])
                google_oauth_exchange(query.get("code", [""])[0], query.get("state", [""])[0])
                message = "Google успішно підключено. Це вікно можна закрити."
                ok = True
            except Exception as exc:
                message = f"Помилка підключення Google: {exc}"
                ok = False
            raw = ("<!doctype html><meta charset='utf-8'><title>Google OAuth — PQM</title>"
                   f"<body style='font:16px system-ui;padding:40px'><h2>{'Готово' if ok else 'Помилка'}</h2>"
                   f"<p>{html.escape(message)}</p><script>if(window.opener)window.opener.postMessage('pqm-google-oauth','*')</script></body>").encode("utf-8")
            self.send_response(200 if ok else 400); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if parsed.path == "/api/nazk-registry":
            return self.send_json(list_registry(DB_PATH, "nazk", urllib.parse.parse_qs(parsed.query)))
        if parsed.path == "/api/amcu-registry":
            return self.send_json(list_registry(DB_PATH, "amcu", urllib.parse.parse_qs(parsed.query)))
        if parsed.path == "/api/supplier-options":
            return self.send_json(supplier_options(urllib.parse.parse_qs(parsed.query)))
        if parsed.path == "/api/audit":
            query = urllib.parse.parse_qs(parsed.query)
            page = max(1, int(query.get("page", [1])[0]))
            size = min(200, max(1, int(query.get("size", [100])[0])))
            with db() as con:
                total = int(con.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0])
                rows = [dict(r) for r in con.execute(
                    "SELECT * FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
                    (size, (page - 1) * size),
                )]
            pages = max(1, (total + size - 1) // size)
            return self.send_json({"items": rows, "total": total, "page": page, "pages": pages, "size": size})
        path = parsed.path.lstrip("/") or "index.html"
        target = (ROOT / path).resolve()
        if ROOT not in target.parents or not target.is_file():
            return self.send_error(404)
        raw = target.read_bytes(); self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def _do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/login":
            payload = self.read_json(); username = str(payload.get("username") or "").strip()
            password = str(payload.get("password") or "")
            try:
                account = auth_accounts().get(username)
            except RuntimeError as exc:
                return self.send_json({"error": str(exc)}, 503)
            if not account or not account.get("active", True) or not verify_basic_auth_secret(password, account["secret"]):
                time.sleep(0.25)
                return self.send_json({"error": "Невірний логін або пароль"}, 401)
            token = secrets.token_urlsafe(32)
            session = {"username": username, "role": account["role"], "officer_id": account.get("officer_id"),
                       "expires_at": time.time() + AUTH_SESSION_TTL}
            with AUTH_SESSIONS_LOCK:
                AUTH_SESSIONS[token] = session
            return self.send_session({"username": username, "role": account["role"],
                                      "officer_id": account.get("officer_id")}, token)
        if parsed.path == "/api/logout":
            token = next((item.split("=", 1)[1] for item in self.headers.get("Cookie", "").split(";")
                          if item.strip().startswith(AUTH_COOKIE + "=")), "")
            with AUTH_SESSIONS_LOCK:
                AUTH_SESSIONS.pop(token, None)
            return self.clear_session()
        if parsed.path == "/api/admin/users":
            payload = self.read_json(); username = str(payload.get("username") or "").strip()
            password = str(payload.get("password") or ""); role = str(payload.get("role") or "officer").casefold()
            officer_id = payload.get("officer_id") or None
            if not re.fullmatch(r"[A-Za-z0-9._-]{3,50}", username):
                return self.send_json({"error": "Логін: 3–50 латинських літер, цифр або . _ -"}, 400)
            if role not in AUTH_ROLES: return self.send_json({"error": "Некоректна роль"}, 400)
            if role == "officer" and not officer_id: return self.send_json({"error": "Оберіть конкретну УО"}, 400)
            try: password_hash = hash_password(password)
            except ValueError as exc: return self.send_json({"error": str(exc)}, 400)
            try:
                with db() as con:
                    con.execute("""INSERT INTO auth_users(username,password_hash,role,officer_id,active,created_at,updated_at,created_by)
                      VALUES (?,?,?,?,1,?,?,?)""", (username,password_hash,role,officer_id,now_iso(),now_iso(),self.auth_user))
            except sqlite3.IntegrityError:
                return self.send_json({"error": "Логін або акаунт цієї УО вже існує"}, 409)
            return self.send_json({"saved": True, "username": username}, 201)
        if parsed.path.startswith("/api/violation-reports/") and parsed.path.endswith("/protocol/generate"):
            report_id = urllib.parse.unquote(parsed.path[len("/api/violation-reports/"):-len("/protocol/generate")]).rstrip("/")
            payload = self.read_json()
            try:
                return self.send_json(generate_violation_protocol(report_id, payload, self.auth_user))
            except KeyError:
                return self.send_json({"error": "Звернення не знайдено"}, 404)
            except ConnectionError as exc:
                return self.send_json({"error": str(exc)}, 503)
            except ForeignAuthorityError as exc:
                return self.send_json({"error": str(exc), "is_read_only": True}, 403)
        if parsed.path.startswith("/api/violation-reports/") and parsed.path.endswith("/review/complete"):
            report_id = urllib.parse.unquote(parsed.path[len("/api/violation-reports/"):-len("/review/complete")]).rstrip("/")
            try:
                return self.send_json(complete_violation_review(report_id, self.auth_user))
            except KeyError:
                return self.send_json({"error": "Звернення не знайдено"}, 404)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
            except PermissionError as exc:
                status = 403 if isinstance(exc, ForeignAuthorityError) else 409
                return self.send_json({"error": str(exc), "is_read_only": True}, status)
            except ConnectionError as exc:
                return self.send_json({"error": str(exc)}, 503)
            except (ValueError, PermissionError) as exc:
                return self.send_json({"error": str(exc)}, 409)
        if parsed.path.startswith("/api/applications/") and parsed.path.endswith("/verify-documents"):
            submission_id = urllib.parse.unquote(parsed.path.split("/")[3])
            job_id = uuid.uuid4().hex
            with DOCUMENT_CHECK_LOCK:
                DOCUMENT_CHECK_JOBS[job_id] = {"job_id": job_id, "submission_id": submission_id, "status": "running"}
            threading.Thread(target=document_check_worker, args=(job_id, submission_id), daemon=True).start()
            return self.send_json({"job_id": job_id, "status": "running"}, 202)
        if parsed.path == "/api/protocol/readiness":
            try:
                return self.send_json(protocol_readiness(self.read_json()))
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
        if parsed.path == "/api/protocol/generate":
            try:
                return self.send_json(generate_protocol(self.read_json()))
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 409)
        if parsed.path == "/api/admin/frameworks":
            try:
                return self.send_json(create_framework_service_entry(self.read_json(), self.auth_user), 201)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 409)
        if parsed.path == "/api/admin/frameworks/import-new":
            try:
                return self.send_json(import_new_framework_service_entries(self.auth_user))
            except (ValueError, ConnectionError) as exc:
                return self.send_json({"error": str(exc)}, 503)
        if parsed.path == "/api/sync":
            framework_id = self.read_json().get("framework_id")
            if framework_id:
                if not start_prozorro_sync(sync_worker, mode="single",
                                           message="Підготовка синхронізації відбору…",
                                           args=(framework_id,)):
                    return self.send_json(SYNC_STATE, 409)
                return self.send_json({"started": True, "framework_id": framework_id}, 202)
            if not start_prozorro_sync(sync_all_worker, mode="full",
                                       message="Пошук активних і закритих відборів…"):
                return self.send_json(SYNC_STATE, 409)
            return self.send_json({"started": True, "scope": "active_and_closed"}, 202)
        if parsed.path == "/api/frameworks/refresh":
            if not start_prozorro_sync(refresh_framework_metadata_worker,
                                       mode="framework_metadata",
                                       message="Отримання актуальних відборів із Prozorro…"):
                return self.send_json(SYNC_STATE, 409)
            return self.send_json({"started": True, "scope": "framework_metadata"}, 202)
        if parsed.path == "/api/violation-reports/sync":
            if VIOLATION_SYNC_STATE["running"]:
                return self.send_json(VIOLATION_SYNC_STATE, 409)
            threading.Thread(target=sync_violation_reports_worker, daemon=True).start()
            return self.send_json({"started": True}, 202)
        if parsed.path == "/api/bids-sync":
            if not ENABLE_BIDS_UPDATE or BIDS_MODE not in {"readonly", "read_only"}:
                return self.send_json({"error": "Оновлення ProzorroBids вимкнене в цьому середовищі"}, 403)
            if BIDS_UPDATE_STATE["running"]:
                return self.send_json(BIDS_UPDATE_STATE, 409)
            BIDS_UPDATE_STATE.update(running=True, message="Підготовка оновлення Bids…", started_at=now_iso(), error=None)
            timer = threading.Timer(0.2, bids_update_worker); timer.daemon = True; timer.start()
            return self.send_json({"started": True}, 202)
        if parsed.path == "/api/supplier-edr-sync":
            if SUPPLIER_EDR_SYNC_STATE["running"]:
                return self.send_json(SUPPLIER_EDR_SYNC_STATE, 409)
            SUPPLIER_EDR_SYNC_STATE.update(running=True, message="Підготовка синхронізації довідника ЄДР…",
                                           started_at=now_iso(), updated_at=None, error=None)
            threading.Thread(target=supplier_edr_sync_worker, daemon=True).start()
            return self.send_json({"started": True}, 202)
        if parsed.path == "/api/supplier-nazk-review-sync":
            if SUPPLIER_NAZK_REVIEW_SYNC_STATE["running"]:
                return self.send_json(SUPPLIER_NAZK_REVIEW_SYNC_STATE, 409)
            SUPPLIER_NAZK_REVIEW_SYNC_STATE.update(running=True,
                message="Підготовка синхронізації перевірок НАЗК…", started_at=now_iso(),
                updated_at=None, error=None)
            threading.Thread(target=supplier_nazk_review_sync_worker, daemon=True).start()
            return self.send_json({"started": True}, 202)
        if parsed.path == "/api/google-oauth/start":
            if not ENABLE_GOOGLE:
                return self.send_json({"error": "Google OAuth вимкнено в цьому середовищі"}, 403)
            try:
                return self.send_json({"authorization_url": google_oauth_authorization_url()}, 200)
            except FileNotFoundError as exc:
                return self.send_json({"error": str(exc), "oauth": google_oauth_status()}, 409)
        if parsed.path == "/api/powerbi-export":
            if not ENABLE_POWERBI:
                return self.send_json({"error": "Power BI export вимкнено в цьому середовищі"}, 403)
            if POWERBI_EXPORT_STATE["running"]:
                return self.send_json(POWERBI_EXPORT_STATE, 409)
            POWERBI_EXPORT_STATE.update(running=True, message="Підготовка експорту Power BI…", started_at=now_iso(), error=None)
            threading.Thread(target=powerbi_export_worker, daemon=True).start()
            return self.send_json({"started": True, "path": str(POWERBI_CURRENT_PATH)}, 202)
        if parsed.path == "/api/remarks-catalog":
            payload = self.read_json(); point = str(payload.get("point") or "").strip(); text = str(payload.get("text") or "").strip()
            if not point or not text: return self.send_json({"error": "Заповніть пункт і текст шаблону"}, 400)
            with db() as con:
                cursor = con.execute("INSERT INTO remarks_catalog(point,text,tag,category,active,updated_at) VALUES (?,?,?,?,1,?)",
                                     (point, text, str(payload.get("tag") or "").strip(), str(payload.get("category") or "").strip(), now_iso()))
            return self.send_json({"saved": True, "id": cursor.lastrowid}, 201)
        if parsed.path == "/api/admin/officers":
            payload = self.read_json()
            full_name = formatted_officer_name(payload.get("full_name"))
            role_name = str(payload.get("role") or "УО").strip() or "УО"
            if not full_name or full_name == "НЕ ВИЗНАЧЕНО":
                return self.send_json({"error": "Вкажіть ПІБ фізичної уповноваженої особи"}, 400)
            with db() as con:
                if con.execute("SELECT 1 FROM authorized_officers WHERE UPPER(full_name)=?", (normalized_officer_name(full_name),)).fetchone():
                    return self.send_json({"error": "Така УО вже є у довіднику"}, 409)
                cursor = con.execute("""INSERT INTO authorized_officers(full_name,role,active,created_at,updated_at)
                  VALUES (?,?,1,?,?)""", (full_name, role_name, now_iso(), now_iso()))
                con.execute("""INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value)
                  VALUES (?,?,?,?,?,?)""", (f"authorized_officer:{cursor.lastrowid}", now_iso(), self.auth_user,
                  "authorized_officer.created", "", full_name))
            return self.send_json({"saved": True, "id": cursor.lastrowid}, 201)
        template_replace = re.fullmatch(r"/api/admin/templates/([^/]+)/replace", parsed.path)
        if template_replace:
            key = urllib.parse.unquote(template_replace.group(1))
            payload = self.read_json()
            try:
                raw = base64.b64decode(payload.get("content") or "", validate=True)
            except Exception:
                return self.send_json({"error": "Не вдалося прочитати DOCX"}, 400)
            temporary = DATA_DIR / "tmp" / f"template_{uuid.uuid4().hex}.docx"
            temporary.parent.mkdir(parents=True, exist_ok=True)
            try:
                temporary.write_bytes(raw)
                target = replace_runtime_template(key, temporary)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
            finally:
                temporary.unlink(missing_ok=True)
            with db() as con:
                con.execute("""INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value)
                  VALUES (?,?,?,?,?,?)""", (f"document_template:{key}", now_iso(), self.auth_user,
                  "document_template.replaced", "", target.name))
            return self.send_json({"saved": True, "item": next(x for x in template_metadata() if x["key"] == key)})
        if parsed.path == "/api/nazk-registry/refresh":
            if not start_reference_refresh(DB_PATH, "nazk"):
                return self.send_json({"error": "Оновлення довідника НАЗК уже виконується"}, 409)
            return self.send_json({"started": True}, 202)
        if parsed.path == "/api/amcu-registry/refresh":
            if not start_reference_refresh(DB_PATH, "amcu"):
                return self.send_json({"error": "Оновлення довідника АМКУ уже виконується"}, 409)
            return self.send_json({"started": True}, 202)
        if parsed.path == "/api/amcu-registry/upload":
            payload = self.read_json()
            try:
                raw = base64.b64decode(payload.get("content") or "", validate=True)
            except Exception:
                return self.send_json({"error": "Не вдалося прочитати Excel-файл"}, 400)
            if not start_reference_refresh(DB_PATH, "amcu", raw, str(payload.get("filename") or "АМКУ.xlsx")):
                return self.send_json({"error": "Оновлення довідника АМКУ уже виконується"}, 409)
            return self.send_json({"started": True}, 202)
        return self.send_error(404)

    def _do_PATCH(self):
        parsed = urllib.parse.urlparse(self.path)
        user_match = re.fullmatch(r"/api/admin/users/([^/]+)", parsed.path)
        if user_match:
            username = urllib.parse.unquote(user_match.group(1)); payload = self.read_json()
            with db() as con:
                current = con.execute("SELECT * FROM auth_users WHERE username=?", (username,)).fetchone()
                if not current: return self.send_json({"error": "Користувача не знайдено"}, 404)
                role = str(payload.get("role", current["role"])).casefold()
                officer_id = payload.get("officer_id", current["officer_id"]) or None
                active = 1 if payload.get("active", bool(current["active"])) else 0
                password_hash = current["password_hash"]
                if payload.get("password"):
                    try: password_hash = hash_password(str(payload["password"]))
                    except ValueError as exc: return self.send_json({"error": str(exc)}, 400)
                if role not in AUTH_ROLES or (role == "officer" and not officer_id):
                    return self.send_json({"error": "Для officer потрібно вибрати конкретну УО"}, 400)
                try:
                    con.execute("UPDATE auth_users SET password_hash=?,role=?,officer_id=?,active=?,updated_at=? WHERE username=?",
                                (password_hash,role,officer_id,active,now_iso(),username))
                except sqlite3.IntegrityError:
                    return self.send_json({"error": "Ця УО вже має активний акаунт"}, 409)
            with AUTH_SESSIONS_LOCK:
                for token, session in list(AUTH_SESSIONS.items()):
                    if session["username"] == username: AUTH_SESSIONS.pop(token, None)
            return self.send_json({"saved": True})
        document_match = re.fullmatch(r"/api/violation-reports/([^/]+)/documents/(customer|supplier)/([^/]+)", parsed.path)
        if document_match:
            report_id, source, document_id = (urllib.parse.unquote(value) for value in document_match.groups())
            payload = self.read_json()
            try:
                return self.send_json(save_violation_document_review(
                    report_id, source, document_id, bool(payload.get("file_unavailable")),
                    str(payload.get("checked_by") or self.auth_user)))
            except KeyError:
                return self.send_json({"error": "Звернення не знайдено"}, 404)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
            except PermissionError as exc:
                status = 403 if isinstance(exc, ForeignAuthorityError) else 409
                return self.send_json({"error": str(exc), "is_read_only": True}, status)
        if parsed.path.startswith("/api/admin/officers/"):
            try:
                officer_id = int(parsed.path.rsplit("/", 1)[-1])
            except ValueError:
                return self.send_json({"error": "Некоректний ID УО"}, 400)
            payload = self.read_json()
            with db() as con:
                current = con.execute("SELECT * FROM authorized_officers WHERE id=?", (officer_id,)).fetchone()
                if not current:
                    return self.send_json({"error": "УО не знайдено"}, 404)
                role_name = str(payload.get("role", current["role"]) or "УО").strip() or "УО"
                active = 1 if payload.get("active", bool(current["active"])) else 0
                for field_name, old_value, new_value in (
                    ("role", str(current["role"] or ""), role_name),
                    ("active", str(int(current["active"])), str(active)),
                ):
                    if old_value != new_value:
                        con.execute("""INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value)
                          VALUES (?,?,?,?,?,?)""", (f"authorized_officer:{officer_id}", now_iso(), self.auth_user,
                          f"authorized_officer.{field_name}", old_value, new_value))
                con.execute("UPDATE authorized_officers SET role=?,active=?,updated_at=? WHERE id=?",
                            (role_name, active, now_iso(), officer_id))
            item = next((row for row in authorized_officers() if row["id"] == officer_id), None)
            return self.send_json({"saved": True, "item": item})
        if parsed.path.startswith("/api/admin/frameworks/"):
            directory_id = urllib.parse.unquote(parsed.path.removeprefix("/api/admin/frameworks/"))
            payload = self.read_json()
            officer = formatted_officer_name(payload.get("responsible_officer"))
            category = str(payload.get("category") or "").strip()
            marketplace_url = str(payload.get("marketplace_url") or "").strip()
            if officer and not valid_active_officer(officer):
                return self.send_json({"error": "Невідома відповідальна УО"}, 400)
            with db() as con:
                current = con.execute("SELECT * FROM framework_service_directory WHERE pretty_id=?", (directory_id,)).fetchone()
                if not current:
                    return self.send_json({"error": "Відбір не знайдено"}, 404)
                changes = {"category": category, "marketplace_url": marketplace_url, "responsible_officer": officer}
                for field_name, new_value in changes.items():
                    old_value = str(current[field_name] or "")
                    if old_value != new_value:
                        con.execute("""INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value)
                          VALUES (?,?,?,?,?,?)""", (directory_id, now_iso(), self.auth_user,
                          f"framework_directory.{field_name}", old_value, new_value))
                con.execute("""UPDATE framework_service_directory SET category=?,marketplace_url=?,
                  responsible_officer=?,source='PQM',synced_at=? WHERE pretty_id=?""",
                  (category, marketplace_url, officer, now_iso(), directory_id))
                framework_id = current["framework_id"]
                if framework_id:
                    con.execute("""INSERT INTO framework_officers(framework_id,officer,marketplace_url,category,source,synced_at)
                      VALUES (?,?,?,?,?,?) ON CONFLICT(framework_id) DO UPDATE SET officer=excluded.officer,
                      marketplace_url=excluded.marketplace_url,category=excluded.category,source=excluded.source,synced_at=excluded.synced_at""",
                      (framework_id, officer, marketplace_url, category, "PQM", now_iso()))
            return self.send_json({"saved": True})
        if parsed.path.startswith("/api/suppliers/") and parsed.path.endswith("/nazk-check"):
            supplier_code = re.sub(r"\D", "", urllib.parse.unquote(parsed.path.split("/")[3]))
            payload = self.read_json()
            try:
                check_id = int(payload.get("check_id") or 0)
                with db() as con:
                    owner = con.execute("SELECT supplier_code FROM supplier_nazk_checks WHERE id=?", (check_id,)).fetchone()
                    if not owner or re.sub(r"\D", "", owner["supplier_code"] or "") != supplier_code:
                        raise ValueError("Перевірку НАЗК цього постачальника не знайдено")
                    if payload.get("action") == "request_sent":
                        result = mark_supplier_nazk_request_sent(
                            con, check_id, changed_by=str(payload.get("checked_by") or self.auth_user),
                            comment=str(payload.get("comment") or ""),
                        )
                    elif payload.get("action") == "complete":
                        result = complete_supplier_nazk_check(
                            con, check_id, result=str(payload.get("result") or ""),
                            evidence_date=str(payload.get("evidence_date") or ""),
                            document_url=str(payload.get("document_url") or ""),
                            document_title=str(payload.get("document_title") or ""),
                            checked_by=str(payload.get("checked_by") or self.auth_user),
                            comment=str(payload.get("comment") or ""),
                        )
                    else:
                        raise ValueError("Невідома дія supplier-level перевірки НАЗК")
                return self.send_json(result)
            except (TypeError, ValueError) as exc:
                return self.send_json({"error": str(exc)}, 400)
        if parsed.path.startswith("/api/applications/") and parsed.path.endswith("/nazk-control"):
            submission_id = urllib.parse.unquote(parsed.path.split("/")[3])
            payload = self.read_json()
            try:
                with db() as con:
                    if payload.get("action") == "complete_refuted":
                        result = complete_submission_nazk_check(
                            con, submission_id,
                            document_id=str(payload.get("selected_document_id") or ""),
                            document_url=str(payload.get("selected_document_url") or ""),
                            evidence_date=str(payload.get("evidence_date") or ""),
                            checked_by=str(payload.get("checked_by") or self.auth_user),
                            comment=str(payload.get("comment") or ""),
                            manager_tax_id=str(payload.get("manager_tax_id") or ""),
                        )
                    else:
                        result = {"control": ensure_submission_nazk_control(
                            con, submission_id, str(payload.get("manager_name"))
                            if "manager_name" in payload else None)}
                return self.send_json(result)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
        if parsed.path.startswith("/api/violation-reports/") and parsed.path.endswith("/review"):
            report_id = urllib.parse.unquote(parsed.path[len("/api/violation-reports/"):-len("/review")]).rstrip("/")
            payload = self.read_json()
            try:
                return self.send_json(save_violation_review(report_id, payload, str(payload.pop("updated_by", "УО") or "УО")))
            except KeyError:
                return self.send_json({"error": "Звернення не знайдено"}, 404)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
            except PermissionError as exc:
                status = 403 if isinstance(exc, ForeignAuthorityError) else 409
                return self.send_json({"error": str(exc), "is_read_only": True}, status)
            except ConnectionError as exc:
                return self.send_json({"error": str(exc)}, 503)
        if parsed.path.startswith("/api/remarks-catalog/"):
            try: remark_id = int(parsed.path.rsplit("/", 1)[-1])
            except ValueError: return self.send_json({"error": "Невідомий пункт довідника"}, 400)
            payload = self.read_json(); fields=[]; values=[]
            for key in ("point", "text", "tag", "category", "active"):
                if key in payload:
                    value = int(bool(payload[key])) if key == "active" else str(payload[key] or "").strip()
                    if key in {"point", "text"} and not value: return self.send_json({"error": "Пункт і текст не можуть бути порожніми"}, 400)
                    fields.append(f"{key}=?"); values.append(value)
            if not fields: return self.send_json({"saved": True})
            values.extend([now_iso(), remark_id])
            with db() as con:
                cursor = con.execute(f"UPDATE remarks_catalog SET {','.join(fields)},updated_at=? WHERE id=?", values)
            if not cursor.rowcount: return self.send_json({"error": "Пункт довідника не знайдено"}, 404)
            return self.send_json({"saved": True})
        if not parsed.path.startswith("/api/applications/"): return self.send_error(404)
        submission_id = parsed.path.rsplit("/", 1)[-1]; payload = self.read_json()
        # Browser payload is never an authorization source. In LOCAL mode the
        # effective role is resolved by ``_authorize`` from the loopback-only
        # impersonation header; in authenticated mode it comes from the account.
        payload.pop("role", None)
        payload.pop("user", None)
        role = self.auth_role
        user = self.auth_user
        if "protocol_officer" in payload and not valid_active_officer(payload["protocol_officer"]):
            return self.send_json({"error": "Невідома відповідальна особа протоколу"}, 400)
        if "protocol_decision" in payload and payload["protocol_decision"] not in PROTOCOL_DECISIONS:
            return self.send_json({"error": "Невідоме рішення до протоколу"}, 400)
        if "marketplace_decision" in payload and payload["marketplace_decision"] not in MARKETPLACE_DECISIONS:
            return self.send_json({"error": "Невідома дія на майданчику"}, 400)
        if "compliance_status" in payload and payload["compliance_status"] not in COMPLIANCE_STATUSES:
            return self.send_json({"error": "Невідомий статус комплаєнс"}, 400)
        if "authority_review" in payload and payload["authority_review"] not in AUTHORITY_REVIEWS:
            return self.send_json({"error": "Невідомий висновок щодо повноважень"}, 400)
        if "mvs_seal_review" in payload and payload["mvs_seal_review"] not in {"", "approved", "rejected"}:
            return self.send_json({"error": "Невідомий висновок щодо електронної печатки МВС"}, 400)
        with db() as con:
            decision = con.execute("SELECT COALESCE(q.status,'pending') FROM submissions s LEFT JOIN qualifications q ON q.id=s.qualification_id WHERE s.id=?", (submission_id,)).fetchone()
            if not decision: return self.send_json({"error": "Заявку не знайдено"}, 404)
            current_controls = con.execute("""SELECT protocol_decision,compliance_status,marketplace_decision,
              protocol_number,protocol_date,manager_name,compliance_comments,
              generated_protocol_number,generated_protocol_date,generated_protocol_decision,protocol_generated_at,protocol_remarks
              FROM application_fields WHERE submission_id=?""", (submission_id,)).fetchone()
            current_protocol_decision, current_compliance_status, current_marketplace_decision = (current_controls[0] or "", current_controls[1] or "", current_controls[2] or "")
            effective_protocol_decision = payload.get("protocol_decision", current_protocol_decision)
            effective_compliance_status = payload.get("compliance_status", current_compliance_status)
            effective_protocol_remarks = str(payload.get("protocol_remarks", current_controls[11]) or "").strip()
            if payload.get("compliance_status") == "approved":
                nazk_state = get_submission_nazk_state(con, submission_id)
                if not nazk_state.get("can_approve"):
                    return self.send_json({
                        "error": "Неможливо погодити Комплаєнс. Для цієї заявки не завершено перевірку довідки НАЗК.",
                        "nazk_state": nazk_state.get("state", "needs_check"),
                    }, 409)
            if effective_protocol_decision and not effective_compliance_status:
                return self.send_json({"error": "Спочатку визначте рішення комплаєнс"}, 409)
            if "compliance_status" in payload and payload["compliance_status"] != current_compliance_status and current_protocol_decision:
                return self.send_json({"error": "Щоб змінити комплаєнс, спочатку встановіть Рішення УО «Не визначено»"}, 409)
            if "protocol_decision" in payload and payload["protocol_decision"] != current_protocol_decision and current_marketplace_decision:
                return self.send_json({"error": "Щоб змінити Рішення УО, спочатку скиньте дію на майданчику"}, 409)
            if effective_protocol_decision == "admit" and effective_compliance_status == "rejected":
                return self.send_json({"error": "Рішення УО «Так» неможливе, коли комплаєнс не погоджено"}, 409)
            if effective_protocol_decision == "admit" and effective_protocol_remarks != "Без зауважень":
                return self.send_json({"error": "Неможливо встановити “Так”: для заявки зазначено зауваження до протоколу."}, 409)
            if (effective_protocol_decision == "reject" and effective_protocol_remarks == "Без зауважень"
                    and effective_compliance_status == "approved"):
                return self.send_json({"error": "Немає підстав для відхилення: комплаєнс погоджено та зауваження до протоколу відсутні."}, 409)
            marketplace_decision = payload.get("marketplace_decision")
            if marketplace_decision and not current_protocol_decision:
                return self.send_json({"error": "Спочатку визначте Рішення УО"}, 409)
            if marketplace_decision and marketplace_decision != current_protocol_decision:
                return self.send_json({"error": "Дія на майданчику має відповідати Рішенню УО"}, 409)
            if marketplace_decision:
                effective = {
                    "protocol_number": str(payload.get("protocol_number", current_controls[3]) or "").strip(),
                    "protocol_date": str(payload.get("protocol_date", current_controls[4]) or "").strip(),
                    "manager_name": str(payload.get("manager_name", current_controls[5]) or "").strip(),
                    "compliance_comments": str(payload.get("compliance_comments", current_controls[6]) or "").strip(),
                }
                missing = []
                if not effective["manager_name"]: missing.append("ПІБ керівника")
                if not effective["protocol_number"]: missing.append("№ протоколу")
                if not effective["protocol_date"]: missing.append("дата протоколу")
                if effective_compliance_status == "rejected" and not effective["compliance_comments"]:
                    missing.append("коментар комплаєнс")
                if missing:
                    return self.send_json({"error": "Дія недоступна. Заповніть: " + ", ".join(missing)}, 409)
                generated_matches = (
                    bool(current_controls[10])
                    and current_controls[7] == effective["protocol_number"]
                    and current_controls[8] == effective["protocol_date"]
                    and current_controls[9] == current_protocol_decision
                )
                if not generated_matches:
                    return self.send_json({"error": f"Спочатку сформуйте протокол № {effective['protocol_number']} з поточними даними"}, 409)
            if marketplace_decision and decision[0] == "active" and marketplace_decision != "admit":
                return self.send_json({"error": "У Prozorro заявку вже допущено"}, 409)
            if marketplace_decision and decision[0] == "unsuccessful" and marketplace_decision != "reject":
                return self.send_json({"error": "У Prozorro заявку вже відхилено"}, 409)
            for field, value in payload.items():
                if field not in EDITABLE_FIELDS: continue
                if role == "viewer": return self.send_json({"error": "Роль не може редагувати"}, 403)
                if current_marketplace_decision and role != "admin":
                    return self.send_json({"error": "Рядок заблоковано виконаною дією на майданчику"}, 409)
                old = con.execute(f"SELECT {field} FROM application_fields WHERE submission_id=?", (submission_id,)).fetchone()[0] or ""
                new = str(value or "")
                if old != new:
                    con.execute(f"UPDATE application_fields SET {field}=?,updated_at=?,updated_by=? WHERE submission_id=?", (new, now_iso(), user, submission_id))
                    if field == "protocol_decision":
                        review_old = con.execute(
                            "SELECT COALESCE(review_officer,'') FROM application_fields WHERE submission_id=?",
                            (submission_id,),
                        ).fetchone()[0]
                        con.execute(
                            "UPDATE application_fields SET review_officer=? WHERE submission_id=?",
                            (user, submission_id),
                        )
                        if review_old != user:
                            con.execute(
                                "INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value) VALUES (?,?,?,?,?,?)",
                                (submission_id, now_iso(), user, "review_officer", review_old, user),
                            )
                    if field == "manager_name":
                        con.execute("""UPDATE application_fields SET manager_name_source='manual',
                          manager_name_source_submission_id='' WHERE submission_id=?""", (submission_id,))
                        supplier = con.execute(
                            "SELECT supplier_code FROM submissions WHERE id=?", (submission_id,)
                        ).fetchone()
                        if supplier:
                            sync_current_supplier_manager(
                                con, supplier[0], new,
                                source=f"Підтверджено УО у заявці {submission_id}", observed_at=now_iso(),
                            )
                    con.execute("INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value) VALUES (?,?,?,?,?,?)", (submission_id, now_iso(), user, field, old, new))
                    if field in {"protocol_number", "protocol_date", "protocol_decision", "manager_name", "compliance_status", "compliance_comments", "protocol_remarks", "document_package"}:
                        con.execute("""UPDATE application_fields SET generated_protocol_number='',generated_protocol_date='',
                          generated_protocol_decision='',protocol_generated_at='' WHERE submission_id=?""", (submission_id,))
            if "manager_name" in payload:
                ensure_submission_nazk_control(con, submission_id)
        return self.send_json({"saved": True})

    def _do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        match = re.fullmatch(r"/api/admin/officers/(\d+)", parsed.path)
        if not match:
            return self.send_error(404)
        officer_id = int(match.group(1))
        with db() as con:
            current = con.execute("SELECT id,full_name FROM authorized_officers WHERE id=?", (officer_id,)).fetchone()
        if not current:
            return self.send_json({"error": "УО не знайдено"}, 404)
        if officer_usage_count(officer_id, current["full_name"]):
            return self.send_json({"error": "УО вже використовувалась. Доступна лише деактивація."}, 409)
        with db() as con:
            con.execute("DELETE FROM authorized_officers WHERE id=?", (officer_id,))
        return self.send_json({"deleted": True, "id": officer_id})

    def log_message(self, fmt, *args):
        message = fmt % args
        print(f"[{self.log_date_time_string()}] {message}")
        SERVER_LOG.info("HTTP %s", message)


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROTOCOLS_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    init_reference_tables(DB_PATH)

    print(f"PQM 0.1 ({PQM_ENV}): http://{HOST}:{PORT}")
    print(f"Data: {DATA_DIR} · DB: {DB_PATH}")
    print(f"Features: scheduler={ENABLE_SCHEDULER}, nazk_scheduler={ENABLE_NAZK_SCHEDULER}, "
          f"bids={BIDS_MODE}, bids_update={ENABLE_BIDS_UPDATE}, powerbi={ENABLE_POWERBI}, "
          f"google={ENABLE_GOOGLE}, auth={AUTH_ENABLED}")
    SERVER_LOG.info("PQM startup environment=%s host=%s port=%s data_dir=%s db=%s",
                    PQM_ENV, HOST, PORT, DATA_DIR, DB_PATH)
    if ENABLE_SCHEDULER:
        threading.Thread(target=hourly_sync_scheduler, daemon=True).start()
    def reference_scheduler():
        last_date = ""
        while True:
            now = datetime.now()
            if now.weekday() < 5 and (now.hour, now.minute) >= (9, 20) and last_date != now.date().isoformat():
                state = reference_status(DB_PATH).get("nazk", {})
                updated = str(state.get("source_updated_at") or "")[:10]
                if updated != now.date().isoformat():
                    refresh_nazk(DB_PATH)
                last_date = now.date().isoformat()
            time.sleep(60)
    if ENABLE_NAZK_SCHEDULER:
        threading.Thread(target=reference_scheduler, daemon=True).start()
    if ENABLE_BROWSER:
        threading.Timer(1, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    ExclusiveThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
