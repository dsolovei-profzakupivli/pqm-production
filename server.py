"""PQM 0.1 local server: SQLite storage, Prozorro sync and browser API."""
from __future__ import annotations

import json
import auth_access
import table_widths
import navigation_settings
import supplier_activity
import supplier_registry_integration
import legacy_google_verification_preview
import edr_sync_v2
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
import urllib.error
import urllib.request
import uuid
import webbrowser
import zipfile
from xml.etree import ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from protocol_docx import build_protocol_docx
from protocol_template import sorted_protocol_items
from document_semantics import supplier_code_label, supplier_entity_type
from supplier_contacts import supplier_contacts
from declension import decline_name, infer_entity_type, normalize_document_name
from declension_overrides import (OverrideConflictError, delete_override,
                                  ensure_pending_overrides, list_overrides, save_override)
import formed_protocols
import operational_tasks
import nazk_evidence
import task_documents
import document_metadata
import document_bindings
import template_runtime
import template_catalog
import scheduler_runtime
import protocol_pdf
import historical_applications
from violation_text import normalize_justification_text
from violation_protocol_docx import (TEMPLATES, build_violation_protocol_docx,
                                     ensure_runtime_templates, replace_runtime_template,
                                     template_metadata, ProtocolContextValidationError)
from nazk_workflow import (
    submission_manager_tax_context, save_submission_manager_tax_id,
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
SUPPLIER_REGISTRY_INTEGRATION_PATH = "/api/integrations/suppliers/full-registry"
GOOGLE_VERIFICATION_PREVIEW_PATH = legacy_google_verification_preview.PATH
SUPPLIER_REGISTRY_INTEGRATION_TOKEN_ENV = "PQM_SUPPLIER_REGISTRY_TOKEN"
SANDBOX_SUPPLIER_REGISTRY_INTEGRATION_TOKEN_ENV = "PQM_SANDBOX_SUPPLIER_REGISTRY_TOKEN"


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
SANDBOX_MODE = env_flag("PQM_SANDBOX", False)
SAFE_MODE = env_flag("PQM_SAFE_MODE", False)
if SANDBOX_MODE:
    import sandbox_runtime
    sandbox_runtime.validate_environment()
    sandbox_runtime.install_outbound_guard()
DATA_DIR = Path(os.environ.get("PQM_DATA_DIR", str(ROOT / "data"))).resolve()
DB_PATH = Path(os.environ.get("PQM_DB_PATH", str(DATA_DIR / "pqm.sqlite3"))).resolve()
PROTOCOLS_DIR = Path(os.environ.get("PQM_PROTOCOLS_DIR", str(DATA_DIR / "protocols"))).resolve()
GENERATED_DOCUMENTS_DIR = DATA_DIR / "generated_documents"
RUNTIME_CACHE_DIR = Path(os.environ.get("PQM_CACHE_DIR", str(DATA_DIR / "cache"))).resolve()
HOST = os.environ.get("HOST", "0.0.0.0" if IS_WEB_ENV else "127.0.0.1")
PORT = int(os.environ.get("PORT", "10000" if IS_WEB_ENV else "8080"))
ENABLE_BROWSER = not IS_WEB_ENV and env_flag("PQM_ENABLE_BROWSER", True)
SCHEDULERS_ENABLED_BY_DEFAULT = scheduler_runtime.enabled_by_default(PQM_ENV)
_legacy_scheduler_default = env_flag("PQM_ENABLE_SCHEDULER", SCHEDULERS_ENABLED_BY_DEFAULT)
ENABLE_PROZORRO_SCHEDULER = env_flag("PQM_ENABLE_PROZORRO_SCHEDULER", _legacy_scheduler_default)
ENABLE_VIOLATION_SCHEDULER = env_flag("PQM_ENABLE_VIOLATION_SCHEDULER", _legacy_scheduler_default)
ENABLE_NAZK_SCHEDULER = env_flag("PQM_ENABLE_NAZK_SCHEDULER", not IS_WEB_ENV)
# Backward-compatible aggregate exposed to older UI/tests.
ENABLE_SCHEDULER = ENABLE_PROZORRO_SCHEDULER or ENABLE_VIOLATION_SCHEDULER
AUTH_ENABLED = env_flag("PQM_AUTH_ENABLED", IS_WEB_ENV)
LOCAL_ROLE_IMPERSONATION = not IS_WEB_ENV and env_flag("PQM_LOCAL_ROLE_IMPERSONATION", True)
BIDS_MODE = os.environ.get("PQM_BIDS_MODE", "disabled" if IS_WEB_ENV else "readonly").strip().casefold()
ENABLE_BIDS_UPDATE = not IS_WEB_ENV and env_flag("PQM_ENABLE_BIDS_UPDATE", True)
ENABLE_POWERBI = not IS_WEB_ENV and env_flag("PQM_ENABLE_POWERBI", True)
ENABLE_GOOGLE = env_flag("PQM_ENABLE_GOOGLE", not IS_WEB_ENV)
EDS_ADAPTER_PATH = ROOT / "tools" / "prozorro_eds_adapter" / "verify-signature.mjs"
EDS_TIMEOUT_SECONDS = max(5, int(os.environ.get("PQM_EDS_TIMEOUT_SECONDS", "35")))
BIDS_DB_PATH = Path(os.environ.get(
    "PQM_BIDS_DB",
    str(DATA_DIR / "prozorro_bids.db") if IS_WEB_ENV else r"D:\ProzorroBids\prozorro_bids.db",
))
BIDS_STATUS_CACHE: dict = {"at": 0.0, "value": None}
BIDS_STATUS_LOCK = threading.Lock()
BIDS_PROJECT_PATH = Path(os.environ.get(
    "PQM_BIDS_PROJECT_DIR",
    str(DATA_DIR) if IS_WEB_ENV else r"D:\ProzorroBids",
))
_bids_local = {}
if not IS_WEB_ENV:
    try:
        _bids_config = Path(os.environ.get("PQM_BIDS_CONFIG", str(DATA_DIR / "bids.local.json")))
        if _bids_config.is_file():
            _bids_local = json.loads(_bids_config.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        SERVER_LOG.exception("Cannot read LOCAL Bids configuration")
BIDS_SCRIPT = Path(os.environ.get("PQM_BIDS_SCRIPT", str(_bids_local.get("script") or BIDS_PROJECT_PATH / "main.py")))
BIDS_PYTHON = Path(os.environ.get(
    "PQM_BIDS_PYTHON",
    str(_bids_local.get("python") or BIDS_PROJECT_PATH / ".venv" / "Scripts" / "python.exe"),
))
BIDS_PYTHON_SOURCE = (
    "environment" if os.environ.get("PQM_BIDS_PYTHON")
    else "local_config" if _bids_local.get("python")
    else "project_venv_default"
)
BIDS_START_LOCK = threading.Lock()
BIDS_UPDATE_STATE = {"running": False, "message": "Ручне оновлення ще не запускали", "started_at": None,
                     "updated_at": None, "date_from": None, "date_to": None, "error": None,
                     "run_id": None, "status": "idle", "finished_at": None, "stage": None,
                     "processed": None, "total": None, "last_activity_at": None,
                     "current_run_errors": 0, "last_error": None, "pid": None,
                     "duplicate_attempts": 0}
BIDS_MANUAL_FEATURE_KEY = "manual_bids_update"
POWERBI_EXPORT_STATE = {"running": False, "message": "Експорт ще не запускали", "started_at": None,
                        "updated_at": None, "error": None}
POWERBI_START_LOCK = threading.Lock()
POWERBI_OUTPUT_ROOT = BIDS_PROJECT_PATH / "output"
POWERBI_CURRENT_PATH = POWERBI_OUTPUT_ROOT / "powerbi_current"
SUPPLIER_EDR_SHEET_ID = "1rqghaEduW8Aer4ri36aysMurEdK2UH5laXKw_Oo1FKA"
SUPPLIER_EDR_SHEETS = {"ФОП": "1278053622", "ЮО": "511647713"}
SUPPLIER_NAZK_REVIEW_SHEET_ID = "1hAgy_YQFWf8m6yHQTO4g22Et94Gm46dC9WTBaoyZloA"
SUPPLIER_NAZK_REVIEW_SHEET = "nazk_data"
CURRENT_USER = os.environ.get("PQM_CURRENT_USER", "Світлана НАМЯСЕНКО")
GOOGLE_OAUTH_DIR = Path(os.environ.get("PQM_GOOGLE_OAUTH_DIR", str((Path(os.environ.get("LOCALAPPDATA", str(DATA_DIR))) / "PQM") if not IS_WEB_ENV else (DATA_DIR / "google_oauth"))))
GOOGLE_OAUTH_CLIENT_PATH = Path(os.environ.get("PQM_GOOGLE_OAUTH_CLIENT", str(GOOGLE_OAUTH_DIR / "google_oauth_client.json")))
GOOGLE_OAUTH_TOKEN_PATH = Path(os.environ.get("PQM_GOOGLE_OAUTH_TOKEN", str(GOOGLE_OAUTH_DIR / "google_oauth_token.json")))
GOOGLE_SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
GOOGLE_RUNTIME_FEATURE_KEY = "google_integration"
GOOGLE_OAUTH_TRANSACTION_TTL_SECONDS = 600
GOOGLE_TOKEN_WRITE_LOCK = threading.RLock()
SUPPLIER_EDR_SYNC_STATE = {"running": False, "message": "Довідник ЄДР ще не синхронізували",
                           "started_at": None, "updated_at": None, "processed": 0,
                           "inserted": 0, "updated": 0, "error": None,
                           "last_completed_at": None, "last_result": None, "last_message": None}
SUPPLIER_NAZK_REVIEW_SYNC_STATE = {"running": False, "message": "Перевірки НАЗК ще не синхронізували",
                                   "started_at": None, "updated_at": None, "processed": 0,
                                   "inserted": 0, "updated": 0, "error": None,
                                   "last_completed_at": None, "last_result": None, "last_message": None}
TESSERACT_EXE = Path(os.environ.get(
    "PQM_TESSERACT_EXE",
    shutil.which("tesseract") or ("/usr/bin/tesseract" if IS_WEB_ENV else r"D:\Program Files\Tesseract-OCR\tesseract.exe"),
))
TESSDATA_DIR = ROOT / "tools" / "tessdata"
PDFTOPPM_EXE = Path(os.environ.get(
    "PQM_PDFTOPPM_EXE",
    shutil.which("pdftoppm") or ("/usr/bin/pdftoppm" if IS_WEB_ENV else r"C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe"),
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
# PQM Google OAuth integration and must not depend on the Codex session.
PROTOCOLS_DRIVE_FOLDER_ID = "1OFlBRzYFtJ8PZ7oAks7NpKb2ZnHds7XF"
PROTOCOLS_DRIVE_FOLDER_URL = f"https://drive.google.com/drive/folders/{PROTOCOLS_DRIVE_FOLDER_ID}"
EDITABLE_FIELDS = {
    "protocol_number", "protocol_date", "publication_date", "protocol_officer",
    "protocol_remarks", "protocol_decision", "marketplace_decision", "compliance_status", "compliance_comments",
    "manager_name", "document_package", "contract_details", "authority_review", "mvs_seal_review", "notes"
}


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """Prevent two PQM processes from sharing port 8080 on Windows."""
    # Render/POSIX restarts must be able to bind after a previous connection
    # enters TIME_WAIT. Windows keeps its exclusive socket binding behavior.
    allow_reuse_address = IS_WEB_ENV and os.name != "nt"

    def server_bind(self):
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if os.name == "nt" and exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()


class BidsUnavailableError(RuntimeError):
    """The optional read-only ProzorroBids source is unavailable."""


class ForeignAuthorityError(PermissionError):
    """The violation report belongs to another central purchasing body."""


class DeclensionValidationError(ValueError):
    """Expected unresolved exact form required by the selected DOCX."""

    def __init__(self, items: list[dict[str, str]]):
        self.items = items
        labels = {"genitive": "родовий", "dative": "давальний", "accusative": "знахідний"}
        message = "; ".join(
            f"Не визначено {labels.get(item['grammatical_case'], item['grammatical_case'])} відмінок для: {item['original']}"
            for item in items)
        super().__init__(message)

    def payload(self) -> dict:
        return {"error": str(self), "code": "declension_unresolved", "status": 422,
                "unresolved": self.items}


def unresolved_declension_items(missing_tokens, declined_names, report: dict | None = None) -> list[dict[str, str]]:
    case_by_token = {
        "customer_name_genitive": "genitive", "customer_name_accusative": "accusative",
        "supplier_name_genitive": "genitive", "supplier_name_dative": "dative",
        "supplier_name_accusative": "accusative",
    }
    context = report or {}
    result = []
    for token in missing_tokens:
        if token not in case_by_token or token not in declined_names or declined_names[token].status != "unresolved":
            continue
        subject_type = "customer" if token.startswith("customer_") else "supplier"
        identifier = (context.get("author_code") or context.get("customer_code") or ""
                      if subject_type == "customer" else
                      context.get("defendant_code") or context.get("supplier_code") or "")
        result.append({
            "token": token,
            "entity_type": declined_names[token].entity_type,
            "original": declined_names[token].original,
            "grammatical_case": case_by_token[token],
            "source": declined_names[token].source,
            "status": declined_names[token].status,
            "subject_type": subject_type,
            "subject_label": "Замовник" if subject_type == "customer" else "Постачальник",
            "entity_identifier": str(identifier or ""),
            "report_id": str(context.get("report_id") or context.get("id") or ""),
        })
    return result


AUTH_ROLES = {"admin", "officer", "viewer"}


AUTH_SESSIONS: dict[str, dict] = {}
AUTH_SESSIONS_LOCK = threading.Lock()
AUTH_SESSION_TTL = 12 * 60 * 60
AUTH_ONLINE_WINDOW = 90
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
    if path in {"/api/account", "/api/account/avatar"} or path == "/api/chats" or re.fullmatch(r"/api/chats/\d+/(?:messages|read)", path):
        return role in AUTH_ROLES
    # Account-owned presentation preferences only; never a business-data mutation.
    if method == 'POST' and path == '/api/history-columns' and role in AUTH_ROLES:
        return True
    # Read-only preview still requires tasks.read in the central permission gate.
    if method == 'POST' and path == '/api/edr-monitoring/termination-exclusions/preview':
        return role in AUTH_ROLES
    if method not in {"POST", "PATCH", "PUT", "DELETE"}:
        return True
    if role == "admin":
        return True
    if role != "officer":
        return False
    officer_patterns = (
        r"^/api/applications/[^/]+$",
        r"^/api/applications/[^/]+/(?:verify-documents|verify-documents/start|nazk-control)$",
        r"^/api/protocol/(?:readiness|generate|formed/[^/]+/cancel|legacy/[^/]+/cancel)$",
        r"^/api/violation-reports/[^/]+/(?:review|review/complete|protocol/generate)$",
        r"^/api/violation-reports/[^/]+/documents/(?:customer|supplier)/[^/]+$",
        r"^/api/suppliers/[^/]+/nazk-check$",
        r"^/api/suppliers/[^/]+/note$",
        r"^/api/application-profiles(?:/[^/]+)?$",
        r"^/api/applications/[^/]+/remark-selections$",
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
    """Validate active officer identity; assignment scope applies only to appeals.

    Application access is governed by the granular ``applications.edit`` and
    ``applications.check`` permissions.  The responsible officer is workflow
    metadata, not an ownership boundary for application review.
    """
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
            return True
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
    if configured.startswith("pbkdf2_sha256:"):
        return auth_access.verify_password(provided, configured)
    if configured.startswith("sha256:"):
        digest = hashlib.sha256(provided.encode("utf-8")).hexdigest()
        return hmac.compare_digest(digest, configured.removeprefix("sha256:"))
    return hmac.compare_digest(provided, configured)
PROTOCOL_DECISIONS = {"", "admit", "reject"}
MARKETPLACE_DECISIONS = {"", "admit", "reject"}
COMPLIANCE_STATUSES = {"", "approved", "rejected"}
AUTHORITY_REVIEWS = {"", "approved", "missing", "not_required"}
INITIAL_AUTHORIZED_OFFICERS = (
    ("СВІТЛАНА НАМЯСЕНКО", 1), ("ЯНА КАСЬЯН", 0),
    ("ОКСАНА АБРОСІМОВА", 0), ("ДМИТРО САВВА", 1),
    ("СЕРГІЙ ЛОЗИНСЬКИЙ", 0), ("ТЕТЯНА ФЕДЧЕНКО", 1),
    ("ОЛЕНА ЄРЬОМІНА", 1),
)


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


def canonical_officer_identity(con, username: str, officer_id=None) -> str:
    """Resolve the accountable officer name; never persist a login as business data."""
    row = None
    if officer_id:
        row = con.execute(
            "SELECT full_name FROM authorized_officers WHERE id=? AND active=1", (officer_id,)
        ).fetchone()
    if not row:
        row = con.execute("""SELECT o.full_name FROM auth_users u
          JOIN authorized_officers o ON o.id=u.officer_id
          WHERE u.username=? AND u.active=1 AND o.active=1""", (username,)).fetchone()
    if not row:
        row = con.execute(
            "SELECT full_name FROM authorized_officers WHERE active=1 AND NORMALIZE_NAME(full_name)=NORMALIZE_NAME(?)",
            (username,),
        ).fetchone()
    return formatted_officer_name(row[0]) if row else ""


def projected_officer_name(con, value: str) -> str:
    """Compatibility wrapper for the shared EDR verification presentation."""
    return edr_sync_v2.projected_verification_officer(con, value)
SYNC_STATE = {"running": False, "message": "Синхронізацію ще не запускали", "updated_at": None,
              "started_at": None, "next_run_at": None, "mode": None, "duration_seconds": None,
              "last_completed_at": None, "last_result": None, "last_message": None, "last_mode": None}
SYNC_STATE_LOCK = threading.Lock()
PROZORRO_SCHEDULER_THREAD = None
SCHEDULER_HEARTBEAT_AT = None
VIOLATION_SYNC_STATE = {"running": False, "message": "Звернення ще не синхронізувалися", "updated_at": None,
                        "processed": 0, "total": 0, "errors": 0, "stop_requested": False}
VIOLATION_SYNC_LOCK = threading.Lock()
SCHEDULER_REGISTRATION_LOCK = threading.Lock()
REGISTERED_SCHEDULER_JOBS: set[str] = set()
SCHEDULER_STOP_EVENTS: dict[str, threading.Event] = {}
SCHEDULER_THREADS: dict[str, threading.Thread] = {}
SCHEDULER_HEARTBEATS: dict[str, str] = {}
DOCUMENT_CHECK_JOBS = {}
DOCUMENT_CHECK_LOCK = threading.Lock()
CONTRACT_EXPERIENCE_CACHE: dict[tuple[str, str, str], dict] = {}
CONTRACT_EXPERIENCE_LOCK = threading.Lock()
CONTRACT_EXPERIENCE_CACHE_TTL = 6 * 60 * 60
CONTRACT_EXPERIENCE_UNAVAILABLE_CACHE_TTL = 60
CONTRACT_EXPERIENCE_REQUEST_INTERVAL = 0.4
CONTRACT_EXPERIENCE_HTTP_ATTEMPTS = 3
CONTRACT_EXPERIENCE_HTTP_BACKOFF = (0.5, 1.5)
CONTRACT_EXPERIENCE_EXACT_PAGE_LIMIT = 3
CONTRACT_EXPERIENCE_FALLBACK_PAGE_LIMIT = 20
CONTRACT_EXPERIENCE_MAX_CANDIDATES = 3
CONTRACT_EXPERIENCE_CPV_PREFIX_DIGITS = max(
    1, min(8, int(os.environ.get("PQM_EXPERIENCE_CPV_PREFIX_DIGITS", "4")))
)
CONTRACT_EXPERIENCE_RETRY_DELAY = 60
CONTRACT_EXPERIENCE_MAX_BACKGROUND_RETRIES = 2
CONTRACT_EXPERIENCE_LAST_REQUEST = 0.0
CONTRACT_EXPERIENCE_PENDING: set[str] = set()
CONTRACT_EXPERIENCE_PENDING_LOCK = threading.Lock()
CONTRACT_EXPERIENCE_RETRY_PENDING: set[str] = set()
CONTRACT_EXPERIENCE_RETRY_ATTEMPTS: dict[str, int] = {}
CONTRACT_EXPERIENCE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pqm-contracts")
CONTRACT_EXPERIENCE_ALGORITHM_VERSION = 3
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


def effective_officer_sql(q_alias: str = "q", af_alias: str = "af", fo_alias: str = "fo",
                          undefined: str = "") -> str:
    """Single business definition used by application lists, cards and filters."""
    fallback = str(undefined).replace("'", "''")
    return (f"CASE WHEN COALESCE({q_alias}.status,'pending')='pending' "
            f"THEN COALESCE(NULLIF({af_alias}.protocol_officer,''),NULLIF({fo_alias}.officer,''),'{fallback}') "
            f"WHEN {q_alias}.status IN ('active','unsuccessful') "
            f"THEN COALESCE(NULLIF({af_alias}.protocol_officer,''),'{fallback}') "
            f"ELSE '{fallback}' END")


def legal_reference_sort_key(item: dict) -> tuple:
    """Natural order for paragraph/subparagraph references without rewriting labels."""
    label = re.sub(r"\s+", " ", str(item.get("point") or "").strip().casefold())
    match = re.search(r"(?:абз\.?\s*(\d+)\s*)?п\.?\s*(\d+(?:\.\d+)*)", label)
    if not match:
        item_id = int(item.get("id") or 0) if str(item.get("id") or "").isdigit() else 0
        return (1, label, str(item.get("category") or "").casefold(), item_id)
    paragraph = int(match.group(1)) if match.group(1) else 0
    parts = tuple(int(value) for value in match.group(2).split("."))
    item_id = int(item.get("id") or 0) if str(item.get("id") or "").isdigit() else 0
    return (0, parts, 1 if paragraph else 0, paragraph,
            str(item.get("category") or "").casefold(), item_id)


def violation_threshold_summary(decision_dates, moment: datetime | None = None) -> dict:
    """Count satisfied reports in inclusive p. 52 rolling calendar-month windows."""
    today = (moment or datetime.now().astimezone()).date()
    month_start = operational_tasks.subtract_calendar_months(today, 1)
    three_month_start = operational_tasks.subtract_calendar_months(today, 3)
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


def remarks_catalog(force: bool = False, include_inactive: bool = False) -> dict:
    """Return the editable local directory; optionally import new Sheet rows."""
    if not force:
        with db() as con:
            rows = [dict(row) for row in con.execute("""SELECT id,point,text,tag,category,active,updated_at
              FROM remarks_catalog WHERE active=1 OR ?""", (int(include_inactive),))]
        rows.sort(key=legal_reference_sort_key)
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
            if isinstance(cached.get("items"), list):
                cached["items"].sort(key=legal_reference_sort_key)
            cached["source"] = "local-cache"; cached["warning"] = str(exc)
            return cached
        items = [{"id": f"local-{index}", "point": point, "text": text, "tag": tag,
                  "category": "", "source_row": None}
                 for index, (point, text, tag) in enumerate(DEFAULT_REMARKS, start=1)]
        items.sort(key=legal_reference_sort_key)
        return {"items": items, "refreshed_at": None, "source": "built-in", "warning": str(exc)}


def application_remark_selections(submission_id: str) -> list[int]:
    with db() as con:
        return [int(row[0]) for row in con.execute(
            "SELECT remark_id FROM application_protocol_remark_selections WHERE submission_id=? ORDER BY remark_id",
            (submission_id,),
        )]


def save_application_remark_selections(submission_id: str, remark_ids, user: str) -> list[int]:
    normalized = []
    for value in remark_ids if isinstance(remark_ids, list) else []:
        try: remark_id = int(value)
        except (TypeError, ValueError): continue
        if remark_id not in normalized: normalized.append(remark_id)
    with db() as con:
        if not con.execute("SELECT 1 FROM submissions WHERE id=?", (submission_id,)).fetchone():
            raise KeyError(submission_id)
        valid = {int(row[0]) for row in con.execute(
            f"SELECT id FROM remarks_catalog WHERE active=1 AND id IN ({','.join('?' for _ in normalized)})", normalized
        )} if normalized else set()
        if len(valid) != len(normalized):
            raise ValueError("Один або кілька пунктів конструктора більше недоступні")
        con.execute("DELETE FROM application_protocol_remark_selections WHERE submission_id=?", (submission_id,))
        con.executemany("""INSERT INTO application_protocol_remark_selections
          (submission_id,remark_id,selected_at,selected_by) VALUES (?,?,?,?)""",
          [(submission_id, remark_id, now_iso(), user) for remark_id in normalized])
    return normalized


def _profile_owner(user: str) -> str:
    return str(user or CURRENT_USER or "local").strip() or "local"


def list_application_view_profiles(user: str) -> dict:
    owner = _profile_owner(user)
    with db() as con:
        rows = con.execute("""SELECT id,owner_key,name,is_system,source_system_profile_id,
          columns_json,created_at,updated_at FROM application_view_profiles
          WHERE (is_system=1 OR owner_key=?) AND id NOT LIKE 'history-columns:%'
          ORDER BY is_system DESC,name COLLATE NOCASE""", (owner,)).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try: layout = json.loads(item.pop("columns_json") or "[]")
        except json.JSONDecodeError: layout = []
        if isinstance(layout, dict):
            item["columns"] = layout.get("columns") if isinstance(layout.get("columns"), list) else []
            item["kpis"] = layout.get("kpis") if isinstance(layout.get("kpis"), list) else None
            item["sorts"] = validated_application_sorts(layout.get("sorts", []))
        else:
            item["columns"] = layout if isinstance(layout, list) else []
            item["kpis"] = None
        item["is_system"] = bool(item["is_system"])
        item["owned"] = item["owner_key"] == owner
        items.append(item)
    return {"items": items}


HISTORY_COLUMN_KEYS = ('supplier','code','manager','date','cpv','framework','decision','officer','contract','remarks','documents')

def history_column_settings(user, columns=None):
    owner = _profile_owner(user)
    identity = 'history-columns:' + hashlib.sha256(owner.encode()).hexdigest()
    with db() as con:
        if columns is not None:
            if not isinstance(columns,list) or len(columns)!=len(HISTORY_COLUMN_KEYS):
                raise ValueError('Передайте налаштування всіх колонок історії')
            result=[]
            for index,c in enumerate(columns):
                if not isinstance(c,dict) or c.get('key') not in HISTORY_COLUMN_KEYS or not isinstance(c.get('visible'),bool):
                    raise ValueError('Некоректні налаштування колонок')
                width=c.get('width')
                if not isinstance(width,int) or not 60<=width<=1200:raise ValueError('Ширина має бути від 60 до 1200 px')
                result.append({'key':c['key'],'visible':c['visible'],'width':width,'order':index})
            if len({c['key'] for c in result})!=len(HISTORY_COLUMN_KEYS):raise ValueError('Повтор колонки')
            con.execute('''INSERT INTO application_view_profiles
              (id,owner_key,name,is_system,columns_json,created_at,updated_at,created_by,updated_by)
              VALUES (?,?,?,0,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET columns_json=excluded.columns_json,
              updated_at=excluded.updated_at,updated_by=excluded.updated_by''',
              (identity,owner,'__pqm_history_columns_v1__',json.dumps(result),now_iso(),now_iso(),user,user))
        row=con.execute('SELECT columns_json FROM application_view_profiles WHERE id=? AND owner_key=?',(identity,owner)).fetchone()
        return {'columns':json.loads(row[0]) if row else []}

def _validated_profile_columns(value) -> list[dict]:
    if not isinstance(value, list): raise ValueError("Налаштування колонок мають бути масивом")
    result, seen = [], set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict): continue
        key = str(raw.get("key") or "").strip()
        if not key or key in seen: continue
        seen.add(key)
        result.append({"key": key, "visible": bool(raw.get("visible", True)),
                       "order": int(raw.get("order", index)),
                       "width": max(40, min(500, int(raw.get("width", 120)))),
                       "pin": "left" if raw.get("pin") == "left" else ""})
    return result


APPLICATION_PROFILE_KPIS = {
    "applications", "suppliers", "pending", "admitted", "rejected",
    "registry_active", "registry_inactive", "officers",
    "decision_yes", "decision_no", "decision_undefined",
}


def _validated_profile_kpis(value) -> list[str]:
    if value is None: return []
    if not isinstance(value, list): raise ValueError("Налаштування KPI мають бути масивом")
    result = []
    for raw in value:
        key = str(raw or "").strip()
        if key in APPLICATION_PROFILE_KPIS and key not in result: result.append(key)
    return result


def validated_application_sorts(value) -> list[dict]:
    keys = {'participant','edrpou','qualificationId','dkCode','receivedDate','documents',
            'protocolNumber','protocolDate','publicationDate','protocolOfficer','protocolRemarks',
            'protocolDecision','marketplaceDecision','complianceStatus','complianceComments',
            'managerName','documentPackage','contractDetails','decision','registryStatus',
            'registryValidUntil','registryStatusDate','notes'}
    if not isinstance(value, list): raise ValueError('Сортування має бути масивом')
    result = []
    for item in value:
        if not isinstance(item, dict) or item.get('key') not in keys:
            raise ValueError('Невідома колонка сортування')
        if item['key'] not in {x['key'] for x in result}:
            result.append({'key': item['key'], 'direction': 'desc' if item.get('direction') == 'desc' else 'asc'})
    return result


def _profile_layout_json(columns, kpis, sorts=None) -> str:
    return json.dumps({"columns": _validated_profile_columns(columns),
                       "kpis": _validated_profile_kpis(kpis),
                       "sorts": validated_application_sorts(sorts or [])}, ensure_ascii=False)


def announcement_officer_name(value: str) -> str:
    names = {
        "Намясенко": "Світлана НАМЯСЕНКО",
        "Савва": "Дмитро САВВА",
        "Федченко": "Тетяна ФЕДЧЕНКО",
        "Єрьоміна": "Олена ЄРЬОМІНА",
        "Абросімова": "Оксана АБРОСІМОВА",
    }
    clean = (value or "").strip()
    return names.get(clean, clean)


def sync_framework_officers() -> dict:
    if SANDBOX_MODE:
        return {"matched": 0, "skipped": "sandbox_preserves_copied_directory"}
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
    con.create_function("NORMALIZED_DATE", 1, lambda value: edr_sync_v2.normalized_date(value), deterministic=True)
    con.create_function("EDR_FRESHNESS", 2, lambda status, checked: edr_sync_v2.freshness_state(
        str(status or ""), str(checked or ""))["bucket"], deterministic=True)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=60000")
    return con


def ensure_runtime_feature_settings(con: sqlite3.Connection) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS runtime_feature_settings (
      feature_key TEXT PRIMARY KEY,
      enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
      updated_at TEXT NOT NULL,
      updated_by TEXT NOT NULL
    )""")


def ensure_google_oauth_transactions(con: sqlite3.Connection) -> None:
    """Persist short-lived PKCE transactions so a LOCAL/WEB restart is safe."""
    con.execute("""CREATE TABLE IF NOT EXISTS google_oauth_transactions (
      state_hash TEXT PRIMARY KEY,
      code_verifier TEXT NOT NULL,
      redirect_uri TEXT NOT NULL,
      expected_origin TEXT NOT NULL,
      created_at REAL NOT NULL,
      expires_at REAL NOT NULL,
      created_by TEXT NOT NULL DEFAULT ''
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS ix_google_oauth_transactions_expiry ON google_oauth_transactions(expires_at)")


def runtime_feature_state(feature_key: str, environment_default: bool,
                          con: sqlite3.Connection | None = None) -> dict:
    own_connection = con is None
    if own_connection:
        con = db()
    try:
        ensure_runtime_feature_settings(con)
        row = con.execute(
            "SELECT enabled,updated_at,updated_by FROM runtime_feature_settings WHERE feature_key=?",
            (feature_key,),
        ).fetchone()
        enabled = bool(row[0]) if row else bool(environment_default)
        return {
            "feature_key": feature_key,
            "enabled": enabled and not SAFE_MODE,
            "configured_enabled": enabled,
            "configuration_source": "safe_mode" if SAFE_MODE else "runtime" if row else "environment",
            "updated_at": row[1] if row else None,
            "updated_by": row[2] if row else None,
        }
    finally:
        if own_connection:
            con.close()


def set_runtime_feature_enabled(feature_key: str, enabled: bool, actor: str,
                                environment_default: bool) -> dict:
    if SAFE_MODE:
        raise ValueError("Зміна інтеграцій недоступна в safe mode")
    with db() as con:
        ensure_runtime_feature_settings(con)
        before = runtime_feature_state(feature_key, environment_default, con)
        changed_at = now_iso()
        con.execute("""INSERT INTO runtime_feature_settings(feature_key,enabled,updated_at,updated_by)
          VALUES (?,?,?,?) ON CONFLICT(feature_key) DO UPDATE SET
          enabled=excluded.enabled,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
          (feature_key, int(enabled), changed_at, actor))
        if bool(before["enabled"]) != bool(enabled):
            con.execute("""INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value)
              VALUES (?,?,?,?,?,?)""", (f"runtime_feature:{feature_key}", changed_at, actor,
              "runtime_feature.enabled", "enabled" if before["enabled"] else "disabled",
              "enabled" if enabled else "disabled"))
        return runtime_feature_state(feature_key, environment_default, con)


def manual_bids_update_state(con: sqlite3.Connection | None = None) -> dict:
    own_connection = con is None
    if own_connection:
        con = db()
    try:
        ensure_runtime_feature_settings(con)
        row = con.execute(
            "SELECT enabled,updated_at,updated_by FROM runtime_feature_settings WHERE feature_key=?",
            (BIDS_MANUAL_FEATURE_KEY,),
        ).fetchone()
        configured = bool(row[0]) if row else bool(ENABLE_BIDS_UPDATE)
        mode_supported = BIDS_MODE in {"readonly", "read_only"}
        return {
            "feature_key": BIDS_MANUAL_FEATURE_KEY,
            "enabled": configured and mode_supported,
            "configured_enabled": configured,
            "configuration_source": "runtime" if row else "environment",
            "mode_supported": mode_supported,
            "updated_at": row[1] if row else None,
            "updated_by": row[2] if row else None,
        }
    finally:
        if own_connection:
            con.close()


def set_manual_bids_update_enabled(enabled: bool, actor: str) -> dict:
    if enabled and BIDS_MODE not in {"readonly", "read_only"}:
        raise ValueError("Ручне оновлення Bids недоступне для поточного режиму Bids")
    with db() as con:
        ensure_runtime_feature_settings(con)
        before = manual_bids_update_state(con)
        con.execute("""INSERT INTO runtime_feature_settings(feature_key,enabled,updated_at,updated_by)
          VALUES (?,?,?,?) ON CONFLICT(feature_key) DO UPDATE SET
          enabled=excluded.enabled,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
          (BIDS_MANUAL_FEATURE_KEY, int(enabled), now_iso(), actor))
        if bool(before["enabled"]) != bool(enabled):
            con.execute("""INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value)
              VALUES (?,?,?,?,?,?)""", (f"runtime_feature:{BIDS_MANUAL_FEATURE_KEY}", now_iso(), actor,
              "runtime_feature.enabled", "enabled" if before["enabled"] else "disabled",
              "enabled" if enabled else "disabled"))
        return manual_bids_update_state(con)


def google_runtime_state(con: sqlite3.Connection | None = None) -> dict:
    return runtime_feature_state(GOOGLE_RUNTIME_FEATURE_KEY, ENABLE_GOOGLE, con)


def google_effective_enabled() -> bool:
    return bool(google_runtime_state()["enabled"])


def set_google_runtime_enabled(enabled: bool, actor: str) -> dict:
    result = set_runtime_feature_enabled(GOOGLE_RUNTIME_FEATURE_KEY, enabled, actor, ENABLE_GOOGLE)
    if not enabled:
        with db() as con:
            ensure_google_oauth_transactions(con)
            con.execute("DELETE FROM google_oauth_transactions")
    return result


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
        import nazk_registry_evidence
        nazk_registry_evidence.ensure_schema(con)
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
        CREATE INDEX IF NOT EXISTS ix_submissions_integration_latest ON submissions(supplier_code,date_published DESC,id DESC);
        CREATE TABLE IF NOT EXISTS qualifications (
          id TEXT PRIMARY KEY, framework_id TEXT NOT NULL, submission_id TEXT,
          status TEXT, decision_date TEXT, documents_json TEXT NOT NULL DEFAULT '[]',
          raw_json TEXT NOT NULL, synced_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_qualifications_submission ON qualifications(submission_id);
        CREATE INDEX IF NOT EXISTS ix_qualifications_status_submission ON qualifications(status,submission_id);
        CREATE TABLE IF NOT EXISTS registry_contracts (
          id TEXT PRIMARY KEY, framework_id TEXT NOT NULL, qualification_id TEXT,
          supplier_code TEXT, status TEXT, milestones_json TEXT NOT NULL DEFAULT '[]',
          raw_json TEXT NOT NULL, synced_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_registry_contracts_qualification ON registry_contracts(qualification_id);
        CREATE INDEX IF NOT EXISTS ix_registry_contracts_supplier ON registry_contracts(supplier_code);
        CREATE INDEX IF NOT EXISTS ix_registry_contracts_integration_activity ON registry_contracts(supplier_code,status,framework_id);
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
        CREATE TABLE IF NOT EXISTS supplier_notes (
          supplier_code TEXT PRIMARY KEY, note TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL, updated_by TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS supplier_note_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_code TEXT NOT NULL,
          old_note TEXT NOT NULL DEFAULT '', new_note TEXT NOT NULL DEFAULT '',
          changed_at TEXT NOT NULL, changed_by TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_supplier_note_events_supplier
          ON supplier_note_events(supplier_code,changed_at);
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
          nazk_source_id TEXT NOT NULL REFERENCES nazk_registry_evidence_sources(source_id),
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
        CREATE TABLE IF NOT EXISTS application_protocol_remark_selections (
          submission_id TEXT NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
          remark_id INTEGER NOT NULL REFERENCES remarks_catalog(id),
          selected_at TEXT NOT NULL,
          selected_by TEXT NOT NULL DEFAULT '',
          PRIMARY KEY(submission_id,remark_id)
        );
        CREATE INDEX IF NOT EXISTS ix_application_remark_selections_submission
          ON application_protocol_remark_selections(submission_id);
        CREATE TABLE IF NOT EXISTS application_view_profiles (
          id TEXT PRIMARY KEY,
          owner_key TEXT NOT NULL,
          name TEXT NOT NULL,
          is_system INTEGER NOT NULL DEFAULT 0 CHECK(is_system IN (0,1)),
          source_system_profile_id TEXT REFERENCES application_view_profiles(id),
          columns_json TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          created_by TEXT NOT NULL DEFAULT '',
          updated_by TEXT NOT NULL DEFAULT '',
          UNIQUE(owner_key,name)
        );
        CREATE INDEX IF NOT EXISTS ix_application_view_profiles_owner
          ON application_view_profiles(owner_key,is_system,name);
        """)
        nazk_registry_evidence.install_capture_trigger(con)
        violation_review_columns = {row[1] for row in con.execute("PRAGMA table_info(violation_report_reviews)")}
        if "decision_justification" not in violation_review_columns:
            con.execute("ALTER TABLE violation_report_reviews ADD COLUMN decision_justification TEXT DEFAULT ''")
        edr_columns = {row[1] for row in con.execute("PRAGMA table_info(supplier_edr_profiles)")}
        for column in ("termination_decision_details", "edr_officer", "edr_notes"):
            if column not in edr_columns:
                con.execute(f"ALTER TABLE supplier_edr_profiles ADD COLUMN {column} TEXT DEFAULT ''")
        edr_sync_v2.migrate(con)
        if con.execute("SELECT COUNT(*) FROM remarks_catalog").fetchone()[0] == 0:
            con.executemany("INSERT INTO remarks_catalog(point,text,tag,category,active,updated_at) VALUES (?,?,?,?,1,?)",
                            [(point, text, tag, "", now_iso()) for point, text, tag in DEFAULT_REMARKS])
        for full_name, active in ([] if env_flag("PQM_RELEASE_SCHEMA_ONLY", IS_WEB_ENV) else INITIAL_AUTHORIZED_OFFICERS):
            con.execute("""INSERT INTO authorized_officers(full_name,role,active,created_at,updated_at)
              VALUES (?,'УО',?,?,?) ON CONFLICT(full_name) DO NOTHING""",
              (full_name, active, now_iso(), now_iso()))
        if con.execute("SELECT COUNT(*) FROM application_view_profiles WHERE is_system=1").fetchone()[0] == 0:
            default_columns = json.dumps([], ensure_ascii=False)
            for profile_id, profile_name in (("system-review", "Розгляд"), ("system-search", "Пошук"),
                                             ("system-publication", "Публікація")):
                con.execute("""INSERT INTO application_view_profiles
                  (id,owner_key,name,is_system,columns_json,created_at,updated_at,created_by,updated_by)
                  VALUES (?,'__system__',?,1,?,?,?,?,?)""",
                  (profile_id, profile_name, default_columns, now_iso(), now_iso(), "system", "system"))
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
        for row in ([] if env_flag("PQM_RELEASE_SCHEMA_ONLY", IS_WEB_ENV) else con.execute("SELECT id,raw_json FROM violation_reports WHERE authority_code='' OR authority_code IS NULL").fetchall()):
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
            "actual_contract_signed": "INTEGER NOT NULL DEFAULT 0",
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
            "generated_protocol_metadata_json": "TEXT NOT NULL DEFAULT '{}'",
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
        auth_access.migrate(con)
        table_widths.migrate(con)
        formed_protocols.migrate(con)
        operational_tasks.migrate(con)
        task_documents.migrate(con)
        navigation_settings.migrate(con)
        scheduler_runtime.migrate(con)
        ensure_runtime_feature_settings(con)
        ensure_google_oauth_transactions(con)


def rebuild_operational_tasks(actor: str = "PQM task builder") -> dict:
    """Generic rebuild: unrelated startup/sync paths must never mutate NAZK."""
    if SAFE_MODE:
        return {"skipped": "safe_mode"}
    with db() as con:
        return operational_tasks.build(con, actor, include_nazk=False)


def rebuild_nazk_tasks(actor: str, *, workflow: str) -> dict:
    """Explicit NAZK-only workflow; no external fetch and no unrelated tasks."""
    if SAFE_MODE:
        return {"skipped": "safe_mode", "created": 0}
    if workflow not in {"nazk_job", "maintenance"}:
        raise ValueError("Explicit NAZK workflow or maintenance action required")
    if workflow == "nazk_job" and not env_flag("PQM_ENABLE_NAZK_WORKFLOW", False):
        SERVER_LOG.info("NAZK materialization skipped: workflow not explicitly enabled")
        return {"skipped": "nazk_workflow_disabled", "created": 0}
    with db() as con:
        supplier_nazk = reconcile_active_supplier_nazk(con, apply=True)
        counts = operational_tasks.materialize_nazk_tasks(con, actor)
        counts["supplier_nazk_checks_created"] = sum(bool(item.get("created"))
                                                   for item in supplier_nazk.get("items", []))
        return counts


def reconcile_prozorro_task_lifecycles(actor: str = "PQM Prozorro qualification sync") -> dict:
    """Run post-sync task transitions from already persisted Prozorro facts."""
    with db() as con:
        return {"amcu": operational_tasks.reconcile_amcu_after_qualification_sync(con, actor),
                "termination": operational_tasks.reconcile_termination_after_qualification_sync(con, actor)}


def api_get(url: str) -> dict:
    last_error = None
    for attempt in range(3):
        try:
            if SANDBOX_MODE:
                return sandbox_runtime.fetch_prozorro_json(url)
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
        # A manually registered directory row is the canonical source of the
        # tracked selection before Prozorro exposes its factual payload. Link
        # it additively as soon as the matching framework becomes available.
        con.execute("""UPDATE framework_service_directory SET framework_id=?
          WHERE pretty_id=? AND framework_id IS NULL""",
          (item["id"], item.get("prettyID", "")))
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
    experience_submission_ids = []
    newly_active_qualification_ids = set()
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
                experience_submission_ids.append(item["id"])
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
                previous_qualification = con.execute(
                    "SELECT status FROM qualifications WHERE id=?", (item["id"],)).fetchone()
                con.execute("""INSERT INTO qualifications
                  (id,framework_id,submission_id,status,decision_date,documents_json,raw_json,synced_at)
                  VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                  submission_id=excluded.submission_id,status=excluded.status,
                  decision_date=excluded.decision_date,documents_json=excluded.documents_json,
                  raw_json=excluded.raw_json,synced_at=excluded.synced_at""",
                  (item["id"], framework_id, item.get("submissionID", ""), item.get("status", ""),
                   item.get("dateModified") or item.get("date", ""),
                   json.dumps(item.get("documents", []), ensure_ascii=False), json.dumps(item, ensure_ascii=False), now_iso()))
                if (item.get("status") == "active" and
                        (previous_qualification is None or previous_qualification[0] != "active")):
                    newly_active_qualification_ids.add(item["id"])
                qualification_count += 1
        agreement_id = framework.get("agreementID", "")
        if agreement_id:
            contracts_cursor = resource_cursor(framework_id, "registry_contracts") if incremental else None
            for batch in paginated_pages(f"{API_ROOT}/agreements/{agreement_id}/contracts", contracts_cursor):
                for item in batch:
                    supplier = (item.get("suppliers") or [{}])[0]
                    previous_contract = con.execute(
                        "SELECT status,qualification_id FROM registry_contracts WHERE id=?",
                        (item["id"],)).fetchone()
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
                    if (item.get("status") == "active" and
                            (previous_contract is None or previous_contract[0] != "active" or
                             previous_contract[1] != item.get("qualificationID", ""))):
                        edr_sync_v2.materialize_effective_admission(con, item["id"], now_iso())
                    contract_count += 1
        for qualification_id in newly_active_qualification_ids:
            for contract in con.execute(
                    "SELECT id FROM registry_contracts WHERE qualification_id=? AND status='active'",
                    (qualification_id,)).fetchall():
                edr_sync_v2.materialize_effective_admission(con, contract[0], now_iso())
    enqueue_contract_experience_search(experience_submission_ids)
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
    if SANDBOX_MODE:
        # Google remains isolated. Read the already copied WEB scope; do not
        # discover unrelated frameworks or pretend that Google was refreshed.
        with db() as con:
            ids = [row[0] for row in con.execute("SELECT id FROM frameworks ORDER BY pretty_id")]
        return [api_get(f"{API_ROOT}/frameworks/{identifier}")["data"] for identifier in ids]
    rows = load_announcement_rows()
    tracked_pretty_ids = sorted({
        (row.get("ID") or "").strip()
        for row in rows
        if (row.get("ID") or "").strip()
        and (row.get("status") or "").strip().casefold() in {"активне", "закрите"}
    })
    with db() as con:
        manually_registered = {str(row[0] or "").strip() for row in con.execute(
            "SELECT pretty_id FROM framework_service_directory WHERE source='PQM'"
        ) if str(row[0] or "").strip()}
    tracked_pretty_ids = sorted(set(tracked_pretty_ids) | manually_registered)
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
        # Keep the directory rows visible as "Не визначено". A future
        # idempotent refresh will link them when Prozorro starts returning data.
        SERVER_LOG.warning("Prozorro has no factual data for %s tracked frameworks: %s",
                           len(missing), ", ".join(missing[:5]))
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
            SERVER_LOG.exception("Framework synchronization failed framework=%s", pretty_id)
            totals["errors"].append({"framework": pretty_id, "error": str(exc)})
    try:
        totals["officer_assignments"] = sync_framework_officers()["matched"]
    except Exception as exc:
        SERVER_LOG.exception("Framework officer synchronization failed")
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
            SERVER_LOG.exception("Tracked framework synchronization failed framework=%s", pretty_id)
            totals["errors"].append({"framework": pretty_id, "error": str(exc)})
    try:
        totals["officer_assignments"] = sync_framework_officers()["matched"]
    except Exception as exc:
        SERVER_LOG.exception("Tracked framework officer synchronization failed")
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
            SERVER_LOG.exception("Incremental framework synchronization failed framework=%s", framework_id)
            totals["errors"].append({"framework": framework_id, "error": str(exc)})
    try:
        totals["officer_assignments"] = sync_framework_officers()["matched"]
    except Exception as exc:
        SERVER_LOG.exception("Incremental framework officer synchronization failed")
        totals["officer_assignments_error"] = str(exc)
    totals["supplier_registry"] = refresh_supplier_registry_summary()
    return totals


def sync_worker(framework_id: str) -> None:
    SYNC_STATE.update(running=True, message="Синхронізація триває…")
    try:
        result = sync_one_framework(framework_id)
        sync_framework_officers()
        result["supplier_registry"] = refresh_supplier_registry_summary()
        result["task_reconciliation"] = reconcile_prozorro_task_lifecycles()
        rebuild_operational_tasks()
        SYNC_STATE["message"] = f"{result['framework']}: {result['submissions']} заявок, {result['qualifications']} рішень, {result['contracts']} записів реєстру"
        SYNC_STATE.update(last_completed_at=now_iso(), last_result=result,
                          last_message=SYNC_STATE["message"], last_mode="single")
    except Exception as exc:
        SERVER_LOG.exception("Single framework synchronization failed framework=%s", framework_id)
        SYNC_STATE["message"] = f"Помилка: {exc}"
        SYNC_STATE.update(last_completed_at=now_iso(), last_result={"status": "failed"},
                          last_message=SYNC_STATE["message"], last_mode="single")
    finally:
        SYNC_STATE.update(running=False, updated_at=now_iso())


def sync_all_worker() -> None:
    started = datetime.now(timezone.utc)
    SYNC_STATE.update(running=True, mode="full", started_at=started.isoformat(), message="Пошук активних і закритих відборів…")
    try:
        result = sync_all_tracked_frameworks()
        result["task_reconciliation"] = reconcile_prozorro_task_lifecycles()
        rebuild_operational_tasks()
        SYNC_STATE["message"] = (
            f"Оновлено {result['completed']}/{result['frameworks']} відборів "
            f"(нових історичних: {result['new_frameworks']}): "
            f"{result['submissions']} заявок, {result['qualifications']} рішень, "
            f"{result['contracts']} записів реєстру; помилок: {len(result['errors'])}"
        )
        SYNC_STATE.update(last_completed_at=now_iso(), last_result=result,
                          last_message=SYNC_STATE["message"], last_mode="full")
    except Exception as exc:
        SERVER_LOG.exception("Full Prozorro synchronization failed")
        SYNC_STATE["message"] = f"Помилка: {exc}"
        SYNC_STATE.update(last_completed_at=now_iso(), last_result={"status": "failed"},
                          last_message=SYNC_STATE["message"], last_mode="full")
    finally:
        SYNC_STATE.update(running=False, updated_at=now_iso(), duration_seconds=round((datetime.now(timezone.utc) - started).total_seconds(), 1))


def sync_incremental_worker() -> None:
    started = datetime.now(timezone.utc)
    SYNC_STATE['last_automatic_started_at'] = started.isoformat()
    SERVER_LOG.info('Prozorro automatic sync started')
    SYNC_STATE.update(running=True, mode="incremental", started_at=started.isoformat(), message="Підготовка щогодинного оновлення…")
    try:
        result = sync_incremental_active_frameworks()
        result["task_reconciliation"] = reconcile_prozorro_task_lifecycles()
        rebuild_operational_tasks()
        SYNC_STATE["message"] = (
            f"Щогодинне оновлення: {result['completed']}/{result['frameworks']} відборів; "
            f"отримано {result['submissions']} заявок, {result['qualifications']} рішень, "
            f"{result['contracts']} записів реєстру; помилок: {len(result['errors'])}"
        )
        SYNC_STATE.update(last_completed_at=now_iso(), last_result=result,
                          last_message=SYNC_STATE["message"], last_mode="incremental")
    except Exception as exc:
        SERVER_LOG.exception("Incremental Prozorro synchronization failed")
        result = {'status': 'failed'}
        SYNC_STATE["message"] = f"Помилка щогодинного оновлення: {exc}"
        SYNC_STATE.update(last_completed_at=now_iso(), last_result={"status": "failed"},
                          last_message=SYNC_STATE["message"], last_mode="incremental")
    finally:
        summary = {'status': 'failed' if result.get('status') == 'failed' else ('partial' if result.get('errors') else 'ok'),
                   'frameworks': result.get('frameworks'), 'completed': result.get('completed'),
                   'errors': len(result.get('errors') or [])}
        SYNC_STATE.update(last_automatic_completed_at=now_iso(), last_automatic_result=summary,
                          updated_at=now_iso(), duration_seconds=round((datetime.now(timezone.utc) - started).total_seconds(), 1))
        SERVER_LOG.info('Prozorro automatic sync completed result=%s duration_seconds=%s', summary, SYNC_STATE['duration_seconds'])
        SYNC_STATE['running'] = False


def _finish_scheduler_lease(job_key: str, owner: str, status: str = "ok", error: str = "") -> None:
    try:
        scheduler_runtime.finish(DB_PATH, job_key, owner, status=status, error=error)
    except Exception:
        SERVER_LOG.exception("Cannot finish scheduler lease job=%s owner=%s", job_key, owner)


def start_prozorro_sync(target, *, mode: str, message: str, args: tuple = (),
                        trigger: str = "manual") -> bool:
    """Claim process and SQLite job locks before starting any Prozorro refresh."""
    with SYNC_STATE_LOCK:
        if SYNC_STATE.get("running"):
            return False
        owner = scheduler_runtime.claim(DB_PATH, "prozorro", trigger=trigger)
        if not owner:
            return False
        SYNC_STATE.update(running=True, mode=mode, started_at=now_iso(), message=message)
    def guarded_target():
        error = ""
        status = "ok"
        try:
            with scheduler_runtime.keepalive(DB_PATH, "prozorro", owner):
                target(*args)
            result = SYNC_STATE.get("last_result") or {}
            if result.get("status") == "failed" or result.get("errors"):
                status = "error" if result.get("status") == "failed" else "partial"
                error = str(SYNC_STATE.get("last_message") or SYNC_STATE.get("message") or "")
        except Exception as exc:
            error = str(exc)
            status = "error"
            raise
        finally:
            SYNC_STATE['running'] = False
            _finish_scheduler_lease("prozorro", owner, status, error)
    try:
        threading.Thread(target=guarded_target, daemon=True).start()
    except Exception:
        with SYNC_STATE_LOCK:
            SYNC_STATE.update(running=False, message="Не вдалося запустити синхронізацію", updated_at=now_iso())
        scheduler_runtime.release(DB_PATH, "prozorro", owner)
        raise
    return True


def next_hourly_run(moment: datetime | None = None) -> datetime:
    return scheduler_runtime.next_hourly_run(moment)


def restore_sync_data_timestamp() -> None:
    """Restore a data timestamp, not an invented successful full-run history."""
    try:
        with db() as con:
            last_value = con.execute('SELECT MAX(synced_at) FROM submissions').fetchone()[0]
        SYNC_STATE['last_data_sync_at'] = last_value
    except Exception:
        SERVER_LOG.exception('Could not restore persisted sync data timestamp')



def sync_status_payload() -> dict:
    payload = dict(SYNC_STATE)
    configured, _ = effective_scheduler_settings()
    thread = SCHEDULER_THREADS.get('prozorro')
    enabled = bool(configured.get('prozorro'))
    alive = bool(enabled and thread and thread.is_alive())
    payload.update(scheduler_enabled=enabled, scheduler_running=alive,
                   scheduler_heartbeat_at=SCHEDULER_HEARTBEATS.get('prozorro'),
                   next_run_at=payload.get('next_run_at') if alive else None)
    return payload



def _scheduler_is_configured(job_key: str) -> bool:
    enabled, _ = effective_scheduler_settings()
    return bool(enabled.get(job_key))


def _wait_until(target: datetime, stop_event: threading.Event | None = None,
                job_key: str | None = None) -> bool:
    while True:
        SCHEDULER_HEARTBEATS[job_key] = now_iso()
        remaining = (target.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return False
        if stop_event:
            if stop_event.wait(min(30, remaining)):
                return True
        else:
            time.sleep(min(30, remaining))
        if job_key and not _scheduler_is_configured(job_key):
            return True


def _trigger_scheduler_job(job_key: str, trigger: str) -> bool:
    """A failed/busy launch must not terminate either independent hourly loop."""
    try:
        if job_key == 'prozorro':
            started = start_prozorro_sync(sync_incremental_worker, mode='incremental',
                                         message='Підготовка щогодинного оновлення…', trigger=trigger)
        elif job_key == 'violation_reports':
            started = start_violation_reports_sync(trigger=trigger)
        else:
            raise ValueError('Unknown hourly job')
        SERVER_LOG.info('Scheduled sync trigger job=%s reason=%s started=%s', job_key, trigger, started)
        return started
    except Exception:
        SERVER_LOG.exception('Scheduled trigger failed job=%s; next cycle remains enabled', job_key)
        return False


def prozorro_scheduler(stop_event: threading.Event, *, catch_up: bool = True) -> None:
    """Independent Europe/Kyiv hourly scheduler with safe startup catch-up."""
    SYNC_STATE["next_run_at"] = next_hourly_run().isoformat()
    if stop_event.wait(10):
        SYNC_STATE["next_run_at"] = None
        return
    if not _scheduler_is_configured("prozorro"):
        SYNC_STATE["next_run_at"] = None
        return
    with db() as con:
        last_value = con.execute("SELECT MAX(synced_at) FROM submissions").fetchone()[0]
    try:
        last_sync = datetime.fromisoformat((last_value or "").replace("Z", "+00:00"))
    except ValueError:
        last_sync = None
    SYNC_STATE['last_data_sync_at'] = last_value
    if catch_up and SANDBOX_MODE and sandbox_runtime.prozorro_scheduler_enabled():
        while not stop_event.is_set() and _scheduler_is_configured('prozorro'):
            SCHEDULER_HEARTBEATS['prozorro'] = now_iso()
            delay = sandbox_runtime.prozorro_catchup_delay(DB_PATH, datetime.now(timezone.utc))
            if delay is None:
                break
            if delay == 0 and _trigger_scheduler_job('prozorro', 'startup_catchup'):
                break
            if stop_event.wait(delay or 30):
                break
    elif catch_up and scheduler_runtime.hourly_catchup_due(
            datetime.now(timezone.utc), last_sync.isoformat() if last_sync else None):
        _trigger_scheduler_job('prozorro', 'startup_catchup')
    while not stop_event.is_set():
        target = next_hourly_run()
        SYNC_STATE["next_run_at"] = target.isoformat()
        if _wait_until(target, stop_event, "prozorro"):
            break
        if not _scheduler_is_configured("prozorro"):
            break
        _trigger_scheduler_job('prozorro', 'scheduled')
    SYNC_STATE["next_run_at"] = None


def violation_reports_scheduler(stop_event: threading.Event, *, catch_up: bool = True) -> None:
    """Independent Europe/Kyiv hourly scheduler and persistent startup catch-up."""
    if stop_event.wait(10):
        VIOLATION_SYNC_STATE["next_run_at"] = None
        return
    if not _scheduler_is_configured("violation_reports"):
        VIOLATION_SYNC_STATE["next_run_at"] = None
        return
    state = next((row for row in scheduler_runtime.state(DB_PATH, {"violation_reports": True})
                  if row["job"] == "violation_reports"), {})
    try:
        last = datetime.fromisoformat(str(state.get("last_finished_at") or "").replace("Z", "+00:00"))
    except ValueError:
        last = None
    if catch_up and scheduler_runtime.hourly_catchup_due(
            datetime.now(timezone.utc), last.isoformat() if last else None):
        _trigger_scheduler_job('violation_reports', 'startup_catchup')
    while not stop_event.is_set():
        target = next_hourly_run()
        VIOLATION_SYNC_STATE["next_run_at"] = target.isoformat()
        if _wait_until(target, stop_event, "violation_reports"):
            break
        if not _scheduler_is_configured("violation_reports"):
            break
        _trigger_scheduler_job('violation_reports', 'scheduled')
    VIOLATION_SYNC_STATE["next_run_at"] = None


def nazk_registry_scheduler(stop_event: threading.Event, *, catch_up: bool = True) -> None:
    """Run once per Kyiv working day, with restart-safe persisted protection."""
    if not _scheduler_is_configured("nazk_registry"):
        return
    if catch_up and not stop_event.is_set():
        current = datetime.now(timezone.utc)
        jobs = scheduler_runtime.state(DB_PATH, {"nazk_registry": True}, current)
        persisted = next(row for row in jobs if row["job"] == "nazk_registry")
        source_day = str(reference_status(DB_PATH).get("nazk", {}).get("source_updated_at") or "")[:10]
        kyiv_day = scheduler_runtime.as_kyiv(current).date().isoformat()
        if (scheduler_runtime.nazk_due_today(current, persisted.get("last_finished_at"))
                and source_day != kyiv_day):
            start_nazk_registry_refresh(trigger="scheduled_catchup")
    while not stop_event.is_set():
        current = datetime.now(timezone.utc)
        target = scheduler_runtime.next_nazk_run(current)
        if _wait_until(target, stop_event, "nazk_registry"):
            break
        if not _scheduler_is_configured("nazk_registry"):
            break
        start_nazk_registry_refresh(trigger="scheduled")


def register_scheduler_job(job_key: str, target, *, catch_up: bool = True) -> bool:
    """Register one scheduler thread per process; SQLite lease protects instances."""
    with SCHEDULER_REGISTRATION_LOCK:
        if job_key in REGISTERED_SCHEDULER_JOBS:
            return False
        stop_event = threading.Event()
        def run():
            try:
                while not stop_event.is_set():
                    try:
                        target(stop_event, catch_up=catch_up)
                        return
                    except Exception:
                        SERVER_LOG.exception('Scheduler loop failed job=%s; retry in 30s', job_key)
                        if stop_event.wait(30):
                            return
            finally:
                with SCHEDULER_REGISTRATION_LOCK:
                    if SCHEDULER_STOP_EVENTS.get(job_key) is stop_event:
                        REGISTERED_SCHEDULER_JOBS.discard(job_key)
                        SCHEDULER_STOP_EVENTS.pop(job_key, None)
                        SCHEDULER_THREADS.pop(job_key, None)
        thread = threading.Thread(target=run, name=f"pqm-scheduler-{job_key}", daemon=True)
        REGISTERED_SCHEDULER_JOBS.add(job_key)
        SCHEDULER_STOP_EVENTS[job_key] = stop_event
        SCHEDULER_THREADS[job_key] = thread
        SCHEDULER_HEARTBEATS[job_key] = now_iso()
        try:
            thread.start()
        except Exception:
            REGISTERED_SCHEDULER_JOBS.discard(job_key)
            SCHEDULER_STOP_EVENTS.pop(job_key, None)
            SCHEDULER_THREADS.pop(job_key, None)
            raise
        SERVER_LOG.info('Scheduler started job=%s timezone=Europe/Kyiv schedule=%s',
                        job_key, scheduler_runtime.SCHEDULES[job_key])
        return True


def unregister_scheduler_job(job_key: str) -> bool:
    with SCHEDULER_REGISTRATION_LOCK:
        stop_event = SCHEDULER_STOP_EVENTS.pop(job_key, None)
        thread = SCHEDULER_THREADS.pop(job_key, None)
        was_registered = job_key in REGISTERED_SCHEDULER_JOBS
        REGISTERED_SCHEDULER_JOBS.discard(job_key)
        if stop_event:
            stop_event.set()
    if thread and thread is not threading.current_thread():
        thread.join(timeout=2)
    return was_registered


SCHEDULER_TARGETS = {
    "prozorro": prozorro_scheduler,
    "violation_reports": violation_reports_scheduler,
    "nazk_registry": nazk_registry_scheduler,
}


def scheduler_environment_defaults() -> dict[str, bool]:
    return {
        "prozorro": ENABLE_PROZORRO_SCHEDULER,
        "violation_reports": ENABLE_VIOLATION_SCHEDULER,
        "nazk_registry": ENABLE_NAZK_SCHEDULER,
    }


def effective_scheduler_settings() -> tuple[dict[str, bool], dict[str, str]]:
    if SANDBOX_MODE and sandbox_runtime.prozorro_scheduler_enabled():
        return ({key: key == 'prozorro' for key in SCHEDULER_TARGETS},
                {key: 'sandbox_environment' if key == 'prozorro' else 'safe_mode'
                 for key in SCHEDULER_TARGETS})
    if SAFE_MODE:
        return ({key: False for key in SCHEDULER_TARGETS},
                {key: "safe_mode" for key in SCHEDULER_TARGETS})
    with db() as con:
        return (scheduler_runtime.effective_enabled(con, scheduler_environment_defaults()),
                scheduler_runtime.setting_sources(con))


def apply_scheduler_settings(*, catch_up: bool) -> dict[str, bool]:
    enabled, _ = effective_scheduler_settings()
    for job_key, target in SCHEDULER_TARGETS.items():
        if enabled[job_key]:
            register_scheduler_job(job_key, target, catch_up=catch_up)
        else:
            unregister_scheduler_job(job_key)
    return enabled


def set_scheduler_job_enabled(job_key: str, enabled: bool, actor: str) -> dict:
    if SAFE_MODE:
        raise ValueError("Планувальники заблоковано в safe mode")
    if job_key not in SCHEDULER_TARGETS:
        raise ValueError("Невідома scheduler job")
    before, _ = effective_scheduler_settings()
    old_enabled = bool(before[job_key])
    if enabled:
        register_scheduler_job(job_key, SCHEDULER_TARGETS[job_key], catch_up=False)
    else:
        unregister_scheduler_job(job_key)
    try:
        if old_enabled != bool(enabled):
            with db() as con:
                scheduler_runtime.save_enabled(con, job_key, bool(enabled), actor)
                con.execute("""INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value)
                  VALUES (?,?,?,?,?,?)""", (f"scheduler_job:{job_key}", now_iso(), actor,
                  "scheduler_job.enabled", "enabled" if old_enabled else "disabled",
                  "enabled" if enabled else "disabled"))
        elif not enabled:
            # Heal an impossible stale process registration without creating a duplicate audit event.
            unregister_scheduler_job(job_key)
    except Exception:
        if old_enabled:
            register_scheduler_job(job_key, SCHEDULER_TARGETS[job_key], catch_up=False)
        else:
            unregister_scheduler_job(job_key)
        raise
    return next(item for item in scheduler_status_payload() if item["job"] == job_key)


def scheduler_status_payload(moment: datetime | None = None) -> list[dict]:
    configured, sources = effective_scheduler_settings()
    with SCHEDULER_REGISTRATION_LOCK:
        registered = set(REGISTERED_SCHEDULER_JOBS)
    factual = {key: configured[key] and key in registered for key in scheduler_runtime.SCHEDULES}
    rows = scheduler_runtime.state(DB_PATH, factual, moment)
    for row in rows:
        key = row['job']
        thread = SCHEDULER_THREADS.get(key)
        row['running'] = bool(configured[key] and key in registered and thread and thread.is_alive())
        row['heartbeat_at'] = SCHEDULER_HEARTBEATS.get(key)
        if not row['running']:
            row['enabled'] = False
            row['next_run'] = None
        row["configured_enabled"] = configured[key]
        row["registered"] = key in registered
        row["configuration_source"] = sources[key]
    return rows


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


def grouped_application_documents(submission_json: str | None, qualification_json: str | None,
                                  registry_json: str | None, qualification_status: str | None,
                                  registry_status: str | None) -> dict[str, list[dict]]:
    """Classify by persisted Prozorro resource relation, never by filename."""
    sources = [("supplier", json.loads(submission_json or "[]")),
               ("decision", json.loads(qualification_json or "[]"))]
    # Registry documents belong to the post-admission chain only after the
    # admitted application has factually become inactive in the registry.
    if qualification_status == "active" and registry_status == "terminated":
        sources.append(("registry", registry_details(registry_json, registry_status)["registry_documents"]))
    groups: dict[str, list[dict]] = {"supplier": [], "decision": [], "registry": []}
    seen = set()
    for group, documents in sources:
        for document in documents:
            key = document.get("url") or document.get("id")
            if not key or key in seen:
                continue
            seen.add(key)
            groups[group].append(document)
    return groups


def multi_param(params: dict, key: str) -> list[str]:
    return [value.strip() for raw in params.get(key, []) for value in raw.split(",") if value.strip()]


APPLICATION_SEARCH_FIELDS = (
    {"key": "supplier", "label": "учасник", "sql": "s.supplier_name"},
    {"key": "supplier_code", "label": "ЄДРПОУ / РНОКПП", "sql": "s.supplier_code"},
    {"key": "manager", "label": "ПІБ керівника", "sql": "af.manager_name"},
    {"key": "framework_id", "label": "ідентифікатор відбору", "sql": "f.pretty_id"},
    {"key": "framework", "label": "назва відбору", "sql": "f.title"},
    {"key": "dk", "label": "код ДК", "sql": "f.dk_code"},
    {"key": "contract", "label": "реквізити договору", "sql": "af.contract_details"},
)


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
    marketplace_decisions = multi_param(params, "marketplace_decision")
    where, args = ["1=1"], []
    protocol_number = params.get("protocol_number", [""])[0].strip()
    if protocol_number:
        where.append("af.protocol_number=?")
        args.append(protocol_number)
    if submission_id:
        where.append("s.id=?")
        args.append(submission_id)
    if protocol_decision in {"__empty__", "admit", "reject"}:
        where.append("COALESCE(af.protocol_decision,'')=?")
        args.append("" if protocol_decision == "__empty__" else protocol_decision)
    if compliance_status in {"__empty__", "approved", "rejected"}:
        where.append("COALESCE(af.compliance_status,'')=?")
        args.append("" if compliance_status == "__empty__" else compliance_status)
    valid_marketplace = ["" if value == "__empty__" else value for value in marketplace_decisions
                         if value in {"__empty__", "admit", "reject"}]
    if valid_marketplace:
        where.append(f"COALESCE(af.marketplace_decision,'') IN ({','.join('?' for _ in valid_marketplace)})")
        args.extend(valid_marketplace)
    if search:
        where.append("(" + " OR ".join(
            f"INSTR(CASEFOLD({field['sql']}), ?) > 0"
            for field in APPLICATION_SEARCH_FIELDS
        ) + ")")
        args.extend([search.casefold()] * len(APPLICATION_SEARCH_FIELDS))
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
    assigned_officer = effective_officer_sql()
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
          SUM(CASE WHEN af.protocol_decision='admit' THEN 1 ELSE 0 END) decision_yes,
          SUM(CASE WHEN af.protocol_decision='reject' THEN 1 ELSE 0 END) decision_no,
          SUM(CASE WHEN COALESCE(af.protocol_decision,'')='' THEN 1 ELSE 0 END) decision_undefined,
          SUM(CASE WHEN EXISTS (SELECT 1 FROM registry_contracts rc WHERE rc.qualification_id=q.id AND rc.status='active') THEN 1 ELSE 0 END) registry_active,
          SUM(CASE WHEN EXISTS (SELECT 1 FROM registry_contracts rc WHERE rc.qualification_id=q.id AND rc.status='terminated') THEN 1 ELSE 0 END) registry_inactive
          FROM submissions s JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN qualifications q ON q.id=s.qualification_id
          LEFT JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id WHERE {clause}""", args).fetchone()
        officer_expr = effective_officer_sql(undefined="Не визначено")
        officers = con.execute(f"""SELECT {officer_expr} officer, COUNT(*) applications
          FROM submissions s JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN qualifications q ON q.id=s.qualification_id
          LEFT JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id WHERE {officer_clause}
          GROUP BY {officer_expr} ORDER BY applications DESC""", officer_args).fetchall()
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
        "protocolOfficer": f"CASEFOLD({effective_officer_sql()})",
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
    sorts = validated_application_sorts(json.loads(params.get('sorts', ['[]'])[0]))
    order_sql = ','.join(f"{sort_expressions[item['key']]} {item['direction'].upper()}" for item in sorts)
    if not order_sql: order_sql = f'{order_by} {sort_direction}'
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
           {effective_officer_sql()} protocol_officer,
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
          ORDER BY {order_sql}, s.id ASC LIMIT ? OFFSET ?""", (*args, size, (page - 1) * size)).fetchall()]
        formed_protocols.enrich(con, records)
        supplier_codes = sorted({re.sub(r"\D", "", row.get("supplier_code") or "") for row in records
                                 if re.sub(r"\D", "", row.get("supplier_code") or "")})
        edr_profiles = {}
        supplier_notes = {}
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
            for note in con.execute(
                f"SELECT supplier_code,note,updated_at,updated_by FROM supplier_notes "
                f"WHERE DIGITS(supplier_code) IN ({placeholders})", supplier_codes):
                supplier_notes[re.sub(r"\D", "", note["supplier_code"] or "")] = dict(note)
        for row in records:
            normalized_code = re.sub(r"\D", "", row.get("supplier_code") or "")
            profile = edr_profiles.get(normalized_code)
            row["edr_fallback_manager"] = profile["manager_name"] if profile else ""
            row["edr_fallback_checked_at"] = profile["edr_checked_at"] if profile else ""
            note = supplier_notes.get(normalized_code) or {}
            row["supplier_note"] = note.get("note", "")
            row["supplier_note_updated_at"] = note.get("updated_at")
            row["supplier_note_updated_by"] = note.get("updated_by", "")
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
        item = dict(row)
        decision_status = item.pop("decision_status")
        item["decision"] = decision_label(decision_status)
        item["review_completed"] = decision_status in {"active", "unsuccessful"} or item.get("protocol_decision") in {"admit", "reject"}
        meddata = historical_applications.provenance(item["id"])
        item["historical_read_only"] = bool(meddata)
        item["historical_source"] = meddata or {}
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
        item["nazk_presentation_state"] = get_submission_nazk_presentation_state(
            submission_nazk,
            historical_read_only=bool(meddata),
            application_rejected=(
                item.get("protocol_decision") == "reject" or item.get("decision") == "Відхилено"
            ),
        )
        item["nazk_can_approve"] = bool(submission_nazk.get("can_approve", True))
        item["nazk_state_reason"] = submission_nazk.get("reason", "")
        # Historical MedData rows are application snapshots.  Never fill a
        # missing historical manager from a current supplier/control context.
        item["manager_name_display"] = (item.get("manager_name", "") if meddata else
                                        item.get("manager_name") or submission_nazk.get("manager_name", ""))
        item["manager_name_display_source"] = ""
        item["manager_name_display_source_date"] = ""
        if not meddata and not item.get("manager_name") and item["manager_name_display"]:
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


HISTORY_REMARKS_SQL = "COALESCE(NULLIF(af.protocol_remarks,''),af.compliance_comments,'')"
HISTORY_SORT_FIELDS = {
    'date': 's.date_published', 'supplier': 's.supplier_name', 'code': 's.supplier_code',
    'cpv': 'f.dk_code', 'framework': 'f.title',
    'decision': "CASE COALESCE(q.status,'pending') WHEN 'active' THEN 'Допущено' WHEN 'unsuccessful' THEN 'Відхилено' ELSE 'Очікує рішення' END",
    'contract': 'af.contract_details', 'manager': 'af.manager_name',
    'officer': 'af.protocol_officer', 'protocol': 'af.protocol_number',
    'protocol_date': 'af.protocol_date', 'remarks': HISTORY_REMARKS_SQL,
}


def history_order_sql(value: str) -> str:
    sorts = json.loads(value or '[]')
    if not isinstance(sorts, list) or len(sorts) > len(HISTORY_SORT_FIELDS):
        raise ValueError('Некоректне сортування історії заявок')
    clauses, seen = [], set()
    for item in sorts:
        if not isinstance(item, dict) or item.get('key') not in HISTORY_SORT_FIELDS or item.get('direction') not in {'asc','desc'}:
            raise ValueError('Некоректне сортування історії заявок')
        key = item['key']
        if key not in seen:
            clauses.append(f"CASEFOLD(COALESCE({HISTORY_SORT_FIELDS[key]},'')) {item['direction'].upper()}")
            seen.add(key)
    return ','.join(clauses or ['s.date_published DESC']) + ',s.id ASC'


def application_history(params: dict) -> dict:
    """Read-only paginated submission history; no EDR/NACP enrichment or writes."""
    page = max(1, int(params.get('page', ['1'])[0]))
    size = min(100, max(1, int(params.get('size', ['50'])[0])))
    where, args = ['1=1'], []
    fields = {'supplier':'s.supplier_name', 'cpv':'f.dk_code', 'framework':'f.title',
              'contract':'af.contract_details', 'manager':'af.manager_name', 'officer':'af.protocol_officer'}
    for key, sql in fields.items():
        value = params.get(key, [''])[0].strip()
        if value:
            where.append(f'INSTR(CASEFOLD(COALESCE({sql},\'\')),?)>0'); args.append(value.casefold())
    code = re.sub(r'\D', '', params.get('code', [''])[0])
    remarks = params.get('remarks', [''])[0].strip().casefold()
    if remarks:
        where.append(f'INSTR(CASEFOLD({HISTORY_REMARKS_SQL}),?)>0'); args.append(remarks)
    order = history_order_sql(params.get('sorts', ['[]'])[0])
    if code: where.append('DIGITS(s.supplier_code)=?'); args.append(code)
    for key, op in [('from','>='),('to','<=')]:
        value = params.get(key, [''])[0]
        if value: where.append(f'SUBSTR(s.date_published,1,10){op}?'); args.append(value)
    state = params.get('status', [''])[0]
    if state in {'pending','active','unsuccessful'}:
        where.append("COALESCE(q.status,'pending')=?"); args.append(state)
    search = params.get('search', [''])[0].strip().casefold()
    if search:
        search_fields = [*fields.values(), 's.supplier_code', 'af.protocol_remarks', 'f.pretty_id']
        where.append('('+' OR '.join(f"INSTR(CASEFOLD(COALESCE({f},'')),?)>0" for f in search_fields)+')')
        args.extend([search]*len(search_fields))
    source = """ FROM submissions s LEFT JOIN frameworks f ON f.id=s.framework_id
      LEFT JOIN application_fields af ON af.submission_id=s.id
      LEFT JOIN (SELECT id,submission_id,ROW_NUMBER() OVER (PARTITION BY submission_id ORDER BY
        CASE status WHEN 'active' THEN 3 WHEN 'unsuccessful' THEN 2 ELSE 1 END DESC,
        COALESCE(NULLIF(decision_date,''),synced_at) DESC,id DESC) rn FROM qualifications
        WHERE COALESCE(submission_id,'')<>'') final_q ON final_q.submission_id=s.id AND final_q.rn=1
      LEFT JOIN qualifications q ON q.id=COALESCE(final_q.id,s.qualification_id)
      WHERE """ + ' AND '.join(where)
    with db() as con:
        total = con.execute('SELECT COUNT(*)'+source, args).fetchone()[0]
        items = [dict(row) for row in con.execute("""SELECT s.id,s.supplier_name,s.supplier_code,
          s.date_published,s.framework_id,f.pretty_id,f.title framework_title,f.dk_code,
          COALESCE(q.status,'pending') status,af.protocol_decision,af.protocol_officer,
          af.protocol_number,af.protocol_date,af.protocol_remarks,af.compliance_comments,
          af.contract_details,af.manager_name,s.documents_json,q.documents_json decision_documents,
          q.status qualification_status,
          (SELECT rc.status FROM registry_contracts rc WHERE rc.qualification_id=q.id ORDER BY rc.synced_at DESC LIMIT 1) registry_status,
          (SELECT rc.milestones_json FROM registry_contracts rc WHERE rc.qualification_id=q.id ORDER BY rc.synced_at DESC LIMIT 1) registry_milestones
          """+source+' ORDER BY '+order+' LIMIT ? OFFSET ?',
          [*args,size,(page-1)*size])]
    for item in items:
        meddata = historical_applications.provenance(item["id"])
        item["historical_read_only"] = bool(meddata)
        item["historical_source"] = meddata or {}
    for item in items:
        groups = grouped_application_documents(item.pop('documents_json'), item.pop('decision_documents'),
                                               item.pop('registry_milestones'), item['qualification_status'],
                                               item['registry_status'])
        item['documents'], item['decision_documents'], item['registry_documents'] = groups['supplier'], groups['decision'], groups['registry']
        item['document_groups'] = groups
        item['decision'] = decision_label(item['status'])
    return {'items':items,'total':total,'page':page,'pages':max(1,(total+size-1)//size),'size':size}


def pqm_schema_metadata() -> dict:
    from schema_catalog import catalog
    from template_catalog import project
    return project(catalog(DB_PATH, BIDS_DB_PATH if BIDS_MODE in {'readonly', 'read_only'} else None))


def protocol_readiness(payload: dict) -> dict:
    number = str(payload.get("protocol_number") or "").strip()
    date_from = str(payload.get("date_from") or "").strip()
    date_to = str(payload.get("date_to") or "").strip()
    if not number and not (date_from and date_to):
        raise ValueError("Зазначте номер протоколу або повний період надходження заявок")
    scope, args = [], []
    selected_ids = payload.get('submission_ids')
    if selected_ids is not None:
        if not isinstance(selected_ids, list) or not selected_ids or len(selected_ids)>1000 or any(not isinstance(x,str) for x in selected_ids):
            raise ValueError('Некоректний список вибраних заявок')
        scope.append('s.id IN ('+','.join('?' for _ in selected_ids)+')'); args.extend(selected_ids)
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
          COALESCE(af.protocol_officer,'') protocol_officer,
          COALESCE(af.manager_name,'') manager_name,
          COALESCE(af.protocol_date,'') protocol_date,
          COALESCE(q.status,'pending') source_status
          FROM submissions s JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN qualifications q ON q.id=s.qualification_id
          LEFT JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id
          WHERE ({filter_clause}) AND ({' AND '.join(scope)}) ORDER BY s.date_published,s.id""", (*filter_args, *args)).fetchall()
    if selected_ids is not None and set(selected_ids)!={row['id'] for row in rows}:
        raise ValueError('Частина вибраних заявок більше не відповідає вибірці. Повторіть перевірку.')
    items, admitted, rejected, unresolved = [], 0, 0, 0
    for raw in rows:
        row, errors, warnings = dict(raw), [], []
        if historical_applications.is_read_only(row["id"]):
            errors.append("Історична заявка MedData доступна лише для перегляду")
        try: formed_protocols.available(con,row['id'])
        except ValueError as exc: errors.append(str(exc))
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


def generate_protocol(payload: dict, user='LOCAL', role='admin', officer_id=None) -> dict:
    result = protocol_readiness(payload)
    if not result["ready"]:
        raise ValueError(f"Протокол не готовий: {result['error_count']} помилок")
    # The immutable membership snapshot and both DOCX renderer paths share the
    # same deterministic business-facing order.
    items = sorted_protocol_items(result["items"])
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
    document_payload = {
        "items": items, "protocol_number": protocol_number, "protocol_date": protocol_date,
        "date_from": date_from, "date_to": date_to, "officer": next(iter(officers)),
    }
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        assert_protocol_scope(con,[item['id'] for item in items],role,officer_id)
        return formed_protocols.create(con,items,document_payload,PROTOCOLS_DIR,build_protocol_docx,user)


def assert_protocol_scope(con,ids,role,officer_id):
    if role=='admin': return
    if role!='officer': raise PermissionError('Недостатньо прав для протоколу')
    officer=con.execute('SELECT full_name FROM authorized_officers WHERE id=? AND active=1',(officer_id,)).fetchone()
    if not officer: raise PermissionError('Не визначено активну УО')
    for sid in ids:
        if not con.execute('SELECT 1 FROM submissions WHERE id=?',(sid,)).fetchone():
            raise PermissionError('Заявку не знайдено')


def list_frameworks() -> dict:
    with db() as con:
        rows = con.execute("""SELECT f.id, f.pretty_id, f.title, f.dk_code, f.date_modified,
          COUNT(s.id) AS applications_count
          FROM frameworks f LEFT JOIN submissions s ON s.framework_id=f.id
          GROUP BY f.id ORDER BY f.date_modified DESC, f.pretty_id""").fetchall()
    return {"items": [dict(row) for row in rows]}


def pending_directory_framework_rows(con: sqlite3.Connection) -> list[dict]:
    """Project PQM-owned selections before their first factual Prozorro match."""
    return [{
        "id": "", "pretty_id": row["pretty_id"], "title": row["source_title"] or "",
        "dk_code": row["dk_code"] or "", "status": "", "agreement_id": "",
        "date_modified": "", "raw_json": "{}", "applications_count": 0,
    } for row in con.execute("""SELECT pretty_id,dk_code,source_title
      FROM framework_service_directory
      WHERE framework_id IS NULL AND source='PQM' ORDER BY pretty_id""")]


def base_framework_analytics(params: dict) -> dict:
    """Serve authoritative framework metadata when ProzorroBids is intentionally disabled."""
    page = max(1, int(params.get("page", [1])[0]))
    size = min(100, max(1, int(params.get("size", [25])[0])))
    search = params.get("search", [""])[0].strip().casefold()
    status_filter = params.get("status", [""])[0].strip()
    dk_filter = params.get("dk_code", [""])[0].strip().casefold()
    direction = params.get("direction", ["asc"])[0].lower()
    with db() as con:
        rows = [dict(row) for row in con.execute("""SELECT f.id,f.pretty_id,f.title,f.dk_code,f.status,f.agreement_id,
          f.date_modified,f.raw_json,COUNT(s.id) applications_count
          FROM frameworks f LEFT JOIN submissions s ON s.framework_id=f.id
          GROUP BY f.id""").fetchall()]
        rows.extend(pending_directory_framework_rows(con))
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
        framework_rows = [dict(row) for row in con.execute("""SELECT f.id,f.pretty_id,f.title,f.dk_code,f.status,f.agreement_id,f.date_modified,f.raw_json,
          COUNT(s.id) applications_count FROM frameworks f LEFT JOIN submissions s ON s.framework_id=f.id
          GROUP BY f.id""").fetchall()]
        framework_rows.extend(pending_directory_framework_rows(con))
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
            sync_columns = {row[1] for row in con.execute("PRAGMA table_info(sync_log)")}
            has_run_observability = {"run_id", "last_activity_at", "stage", "process_id"}.issubset(sync_columns)
            open_logs = [dict(row) for row in con.execute("""SELECT * FROM sync_log WHERE status='running'
          ORDER BY started_at DESC""").fetchall()]
            runtime_run_id = str(BIDS_UPDATE_STATE.get("run_id") or "") if BIDS_UPDATE_STATE.get("running") else ""
            active_worker_runs = [row for row in open_logs
                                  if has_run_observability and runtime_run_id and row.get("run_id") == runtime_run_id]
            stale_open_logs = [row for row in open_logs if row not in active_worker_runs]
            history_counts = {str(row["status"]): int(row["total"])
                              for row in con.execute("SELECT status,COUNT(*) total FROM sync_log GROUP BY status")}
            abandoned_runs = [dict(row) for row in con.execute("""SELECT * FROM sync_log
          WHERE status='abandoned' ORDER BY COALESCE(finished_at,started_at) DESC LIMIT 20""").fetchall()]
            diagnostics = {
                "count": 0,
                "response_items": 0,
                "missing_start_dates": 0,
                "malformed_start_dates": 0,
                "last_recorded_at": None,
            }
            diagnostic_table = con.execute("""SELECT 1 FROM sqlite_master
              WHERE type='table' AND name='search_validation_diagnostics'""").fetchone()
            if diagnostic_table:
                row = con.execute("""SELECT COUNT(*) count,
                  COALESCE(SUM(response_item_count),0) response_items,
                  COALESCE(SUM(missing_start_date_count),0) missing_start_dates,
                  COALESCE(SUM(malformed_start_date_count),0) malformed_start_dates,
                  MAX(recorded_at) last_recorded_at
                  FROM search_validation_diagnostics""").fetchone()
                diagnostics = dict(row)
        complete = counts["pending_tenders"] == 0 and counts["tenders"] == counts["detailed_tenders"]
        result = {**counts, **coverage, **agreement_state, "history_complete": complete,
                   "last_completed": dict(completed) if completed else None,
                  "active_worker_runs": active_worker_runs,
                  "stale_open_logs": stale_open_logs,
                  "abandoned_runs": abandoned_runs,
                  "run_history_counts": history_counts,
                  "current_validation_errors": diagnostics,
                  "database": str(BIDS_DB_PATH), "checked_at": now_iso(),
                  "update": dict(BIDS_UPDATE_STATE)}
        BIDS_STATUS_CACHE.update(at=time.time(), value=result)
    except Exception as exc:
        BIDS_STATUS_CACHE.update(at=time.time(), error=str(exc))
    finally:
        BIDS_STATUS_LOCK.release()


def bids_run_snapshot() -> dict:
    result = dict(BIDS_UPDATE_STATE)
    try:
        start = datetime.fromisoformat(result['started_at'])
        end = datetime.fromisoformat(result['finished_at']) if result.get('finished_at') else datetime.now(timezone.utc)
        result['duration_seconds'] = max(0, int((end-start).total_seconds()))
    except (KeyError, ValueError, TypeError):
        result['duration_seconds'] = None
    return result


def bids_sync_status(force: bool = False) -> dict:
    """Return cached status immediately; refresh heavy counts once in background."""
    cached = BIDS_STATUS_CACHE.get("value")
    fresh = cached is not None and time.time() - float(BIDS_STATUS_CACHE.get("at") or 0) < 600
    if (force or not fresh) and BIDS_STATUS_LOCK.acquire(blocking=False):
        threading.Thread(target=_refresh_bids_status_cache, daemon=True).start()
    if cached is not None:
        return {**cached, "refreshing": BIDS_STATUS_LOCK.locked(), "update": bids_run_snapshot()}
    return {
        "database": str(BIDS_DB_PATH), "checked_at": None, "refreshing": True,
        "message": "Статистика ProzorroBids оновлюється у фоновому режимі",
        "error": BIDS_STATUS_CACHE.get("error", ""), "update": bids_run_snapshot(),
    }


def bids_runtime_check() -> dict:
    if not manual_bids_update_state()["enabled"]:
        raise RuntimeError("Оновлення ProzorroBids вимкнене в цьому середовищі")
    for path in (BIDS_PYTHON, BIDS_SCRIPT):
        if not path.is_file():
            raise FileNotFoundError(f"Не знайдено файл ProzorroBids: {path}")
    command = [str(BIDS_PYTHON), "-c", "import requests,openpyxl,main"]
    cwd = BIDS_SCRIPT.parent
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    SERVER_LOG.info("Bids preflight interpreter=%s source=%s script=%s cwd=%s",
                    BIDS_PYTHON, BIDS_PYTHON_SOURCE, BIDS_SCRIPT, cwd)
    try:
        with subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, encoding="utf-8",
                              errors="replace") as process:
            pid = process.pid
            stdout, stderr = process.communicate(timeout=20)
            return_code = process.returncode
    except PermissionError as exc:
        raise RuntimeError(
            f"Python interpreter ProzorroBids недоступний для запуску: {BIDS_PYTHON}. "
            "Налаштуйте PQM_BIDS_PYTHON або LOCAL bids.local.json на executable "
            "із правом Read & Execute для користувача PQM."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise RuntimeError("Preflight ProzorroBids перевищив ліміт 20 секунд") from exc
    except OSError as exc:
        raise RuntimeError(f"Не вдалося запустити Python interpreter ProzorroBids: {BIDS_PYTHON}: {exc}") from exc
    if return_code:
        detail = (stderr or stdout or "невідома помилка").strip()
        detail = re.sub(r"(?i)(token|password|authorization|api[_-]?key)(\s*[:=]\s*)\S+",
                        r"\1\2[redacted]", detail)[:500]
        raise RuntimeError(f"Preflight ProzorroBids завершився з кодом {return_code}: {detail}")
    return {
        "interpreter": str(BIDS_PYTHON),
        "interpreter_source": BIDS_PYTHON_SOURCE,
        "script": str(BIDS_SCRIPT),
        "cwd": str(cwd),
        "preflight_pid": pid,
    }


def bids_progress_line(line: str) -> None:
    text = line.strip()
    if not text:
        return
    BIDS_UPDATE_STATE.update(last_activity_at=now_iso(), message=text[:500])
    match = re.match(r'^\[(\d+)/(\d+)\]', text)
    if match:
        # The worker prints the item number BEFORE processing it.
        BIDS_UPDATE_STATE.update(processed=max(0,int(match[1])-1), total=int(match[2]))
    elif text.startswith('bids:') and BIDS_UPDATE_STATE.get('processed') is not None:
        BIDS_UPDATE_STATE['processed'] = min(BIDS_UPDATE_STATE['total'], BIDS_UPDATE_STATE['processed']+1)
    if text.startswith(('ПОМИЛКА:', 'КРИТИЧНА ПОМИЛКА:')):
        BIDS_UPDATE_STATE['current_run_errors'] = BIDS_UPDATE_STATE.get('current_run_errors',0)+1
        BIDS_UPDATE_STATE.update(last_error=text[:500])


def run_bids_command(arguments) -> None:
    BIDS_UPDATE_STATE.update(stage=arguments[0], processed=None, total=None, last_activity_at=now_iso())
    # Stream into the rotating server logger; do not keep the whole output in RAM.
    worker_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
                  "PQM_BIDS_RUN_ID": str(BIDS_UPDATE_STATE.get("run_id") or "")}
    with subprocess.Popen([str(BIDS_PYTHON), str(BIDS_SCRIPT), *arguments],
                          cwd=BIDS_SCRIPT.parent, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                          env=worker_env) as process:
        BIDS_UPDATE_STATE["pid"] = process.pid
        SERVER_LOG.info("Bids worker pid=%s interpreter=%s", process.pid, BIDS_PYTHON)
        for line in process.stdout:
            safe = re.sub(r"(?i)(token|password|authorization|api[_-]?key)(\s*[:=]\s*)\S+", r"\1\2[redacted]", line.rstrip())
            SERVER_LOG.info("Bids: %s", safe)
            bids_progress_line(safe)
        code = process.wait()
        if code:
            raise RuntimeError(f"ProzorroBids завершився з кодом {code}; див. logs/server.log")
        if BIDS_UPDATE_STATE.get('total') is not None:
            BIDS_UPDATE_STATE['processed'] = BIDS_UPDATE_STATE['total']


def bids_update_worker() -> None:
    today = datetime.now().astimezone().date()
    try:
        with bids_db() as con:
            value = con.execute("SELECT MAX(SUBSTR(date_modified,1,10)) FROM tenders").fetchone()[0]
        synchronized = datetime.strptime(value, "%Y-%m-%d").date() if value else today - timedelta(days=14)
        date_from = min(synchronized - timedelta(days=2), today)
        BIDS_UPDATE_STATE.update(running=True, message="Інкрементальне оновлення нових і змінених закупівель…",
                                 updated_at=None, date_from=date_from.isoformat(),
                                 date_to=today.isoformat(), error=None)
        bids_runtime_check()
        run_bids_command(["update", "--from", date_from.isoformat(), "--to", today.isoformat(), "--no-export"])
        BIDS_UPDATE_STATE["message"] = "Повторна перевірка активних закупівель…"
        run_bids_command(["refresh-active"])
        BIDS_UPDATE_STATE["message"] = "Оновлення Bids завершено"
        BIDS_UPDATE_STATE['status'] = 'completed'
    except Exception as exc:
        SERVER_LOG.exception("Bids update failed")
        BIDS_UPDATE_STATE.update(message=f"Помилка оновлення Bids: {exc}", error=str(exc))
        BIDS_UPDATE_STATE.update(status='failed', last_error=str(exc),
                                current_run_errors=BIDS_UPDATE_STATE.get('current_run_errors',0)+(0 if BIDS_UPDATE_STATE.get('last_error') else 1))
    finally:
        BIDS_UPDATE_STATE.update(running=False, updated_at=now_iso(), finished_at=now_iso())
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
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    build_name = f".powerbi_build_{stamp}"
    build_path = POWERBI_OUTPUT_ROOT / build_name
    previous_path = POWERBI_OUTPUT_ROOT / f".powerbi_previous_{stamp}"
    try:
        POWERBI_EXPORT_STATE.update(running=True, message="Формування файлів для Power BI…",
                                    started_at=now_iso(), updated_at=None, error=None)
        for path in (BIDS_PYTHON, BIDS_SCRIPT):
            if not path.is_file():
                raise FileNotFoundError(f"Не знайдено runtime ProzorroBids: {path}")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        tail = []
        command = [str(BIDS_PYTHON), str(BIDS_SCRIPT), "export-powerbi", "--dir", build_name]
        SERVER_LOG.info("Power BI export starting interpreter=%s script=%s build=%s", BIDS_PYTHON, BIDS_SCRIPT, build_name)
        with subprocess.Popen(command, cwd=BIDS_SCRIPT.parent, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace") as process:
            POWERBI_EXPORT_STATE.update(pid=process.pid, interpreter=str(BIDS_PYTHON))
            for line in process.stdout:
                line = line.strip()
                if line:
                    SERVER_LOG.info("Power BI [%s] %s", process.pid, line)
                    tail.append(line); tail = tail[-12:]
                    POWERBI_EXPORT_STATE.update(last_activity_at=now_iso())
            code = process.wait()
            POWERBI_EXPORT_STATE['exit_code'] = code
        if code:
            detail = next((s for s in reversed(tail) if 'Error' in s or 'ПОМИЛКА' in s), tail[-1] if tail else 'Експортер не надав пояснення; див. logs/server.log')
            raise RuntimeError(detail[:500])
        if not (build_path / "_COMPLETE.txt").is_file():
            raise RuntimeError("Експортер не створив маркер завершення")
        POWERBI_EXPORT_STATE["message"] = "Заміна попереднього набору…"
        if POWERBI_CURRENT_PATH.exists():
            POWERBI_CURRENT_PATH.rename(previous_path)
        try:
            build_path.rename(POWERBI_CURRENT_PATH)
        except Exception:
            if previous_path.exists() and not POWERBI_CURRENT_PATH.exists():
                previous_path.rename(POWERBI_CURRENT_PATH)
            raise
        POWERBI_EXPORT_STATE['previous_path'] = str(previous_path) if previous_path.exists() else None
        POWERBI_EXPORT_STATE["message"] = "Експорт Power BI успішно оновлено"
    except Exception as exc:
        SERVER_LOG.exception("Power BI export failed")
        POWERBI_EXPORT_STATE.update(message=f"Експорт Power BI не виконано: {exc}", error=str(exc), error_code="export_failed")
    finally:
        POWERBI_EXPORT_STATE.update(running=False, updated_at=now_iso(), finished_at=now_iso())


def start_powerbi_export():
    with POWERBI_START_LOCK:
        if POWERBI_EXPORT_STATE.get('running'):
            return {'error': 'Експорт Power BI вже триває', 'error_code': 'already_running', 'state': dict(POWERBI_EXPORT_STATE)}, 409
        POWERBI_EXPORT_STATE.update(running=True, message='Підготовка експорту Power BI…', started_at=now_iso(),
                                    error=None, error_code=None, exit_code=None, pid=None, finished_at=None)
        try:
            threading.Thread(target=powerbi_export_worker, daemon=True).start()
        except Exception:
            SERVER_LOG.exception('Cannot start Power BI worker')
            POWERBI_EXPORT_STATE.update(running=False, error='Не вдалося запустити процес експорту')
            return {'error': POWERBI_EXPORT_STATE['error'], 'error_code': 'start_failed'}, 503
        return {'started': True, 'state': dict(POWERBI_EXPORT_STATE)}, 202


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
        con.execute(f"""INSERT INTO supplier_registry_summary
          (supplier_code,supplier_name,qualifications_count,active_count,inactive_count,
           suspended_count,frameworks_count,dk_codes,last_qualification,refreshed_at)
          SELECT rc.supplier_code,MAX(COALESCE(s.supplier_name,'')),COUNT(DISTINCT rc.id),
          SUM(CASE WHEN {supplier_activity.effective_active_sql('rc','f')} THEN 1 ELSE 0 END),
          SUM(CASE WHEN {supplier_activity.effective_inactive_sql('rc','f')} THEN 1 ELSE 0 END),
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


class GooglePhaseError(RuntimeError):
    """Expose only allowlisted diagnostics, never raw Google response content."""

    def __init__(self, phase: str, exc: urllib.error.HTTPError):
        error, description = "", ""
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            detail = payload.get("error", {}) if isinstance(payload, dict) else {}
            if isinstance(detail, str):
                error, description = detail, payload.get("error_description", "")
            elif isinstance(detail, dict):
                error, description = detail.get("status", ""), detail.get("message", "")
        except (OSError, ValueError):
            pass
        allowed_errors = {"invalid_grant", "invalid_client", "invalid_request", "unauthorized_client",
                          "unsupported_grant_type", "access_denied", "temporarily_unavailable",
                          "INVALID_ARGUMENT", "UNAUTHENTICATED", "PERMISSION_DENIED", "NOT_FOUND",
                          "RESOURCE_EXHAUSTED", "INTERNAL", "UNAVAILABLE"}
        allowed_descriptions = {"Token has been revoked", "Token has been expired or revoked.",
                                "Bad Request", "Unable to parse range", "Invalid Credentials"}
        self.details = {"phase": phase, "google_http_status": int(exc.code),
                        "google_error": error if isinstance(error, str) and error in allowed_errors else "http_error",
                        "google_error_description": description if isinstance(description, str) and description in allowed_descriptions
                            else "Google API request failed; response details withheld"}
        super().__init__(f"Google {phase}: HTTP {exc.code} {self.details['google_error']}")

    def diagnostic_payload(self) -> dict:
        return dict(self.details)


def _raise_google_phase_error(phase: str, exc: urllib.error.HTTPError) -> None:
    error = GooglePhaseError(phase, exc)
    SERVER_LOG.warning("Google request failed %s", error.diagnostic_payload())
    raise error from None


def _google_oauth_redirect_uri() -> str:
    redirect_uri = os.environ.get(
        "PQM_GOOGLE_OAUTH_REDIRECT_URI", f"http://127.0.0.1:{PORT}/api/google-oauth/callback"
    ).strip()
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Некоректний Google OAuth callback URI")
    return redirect_uri


def _google_origin(uri: str) -> str:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Некоректний Google OAuth origin")
    return f"{parsed.scheme}://{parsed.netloc}"


def _google_state_hash(state: str) -> str:
    return hashlib.sha256(str(state or "").encode("utf-8")).hexdigest()


def _store_google_oauth_transaction(state: str, verifier: str, redirect_uri: str, actor: str) -> None:
    created_at = time.time()
    with db() as con:
        ensure_google_oauth_transactions(con)
        con.execute("DELETE FROM google_oauth_transactions WHERE expires_at<=?", (created_at,))
        con.execute("""INSERT INTO google_oauth_transactions
          (state_hash,code_verifier,redirect_uri,expected_origin,created_at,expires_at,created_by)
          VALUES (?,?,?,?,?,?,?)""", (_google_state_hash(state), verifier, redirect_uri,
          _google_origin(redirect_uri), created_at, created_at + GOOGLE_OAUTH_TRANSACTION_TTL_SECONDS, actor))


def _consume_google_oauth_transaction(state: str) -> dict:
    now = time.time()
    with db() as con:
        ensure_google_oauth_transactions(con)
        con.execute("BEGIN IMMEDIATE")
        con.execute("DELETE FROM google_oauth_transactions WHERE expires_at<=?", (now,))
        row = con.execute("""SELECT code_verifier,redirect_uri,expected_origin,created_at,expires_at,created_by
          FROM google_oauth_transactions WHERE state_hash=?""", (_google_state_hash(state),)).fetchone()
        if row:
            con.execute("DELETE FROM google_oauth_transactions WHERE state_hash=?", (_google_state_hash(state),))
        if not row:
            con.commit()
            raise ValueError("Сеанс авторизації недійсний, уже використаний або прострочений")
        return dict(row)


def _atomic_write_google_json(path: Path, payload: dict) -> None:
    """Publish secret JSON atomically; never expose its contents to logs."""
    with GOOGLE_TOKEN_WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            for attempt in range(5):
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        finally:
            temporary.unlink(missing_ok=True)


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
    feature = google_runtime_state()
    client = _google_oauth_client()
    token = _google_oauth_token()
    configuration_error = GOOGLE_OAUTH_CLIENT_ACCESS_ERROR or GOOGLE_OAUTH_TOKEN_ACCESS_ERROR
    if configuration_error:
        messages = {
            "access_denied": "Немає доступу до локальної конфігурації Google OAuth",
            "unavailable": "Локальна конфігурація Google OAuth недоступна",
            "invalid_configuration": "Локальна конфігурація Google OAuth пошкоджена",
        }
        result = {"configured": bool(client), "authorized": False, "enabled": feature["enabled"],
                  "available": False, "configuration_error": configuration_error,
                  "configuration_source": feature["configuration_source"],
                  "client_state": ("access_denied" if GOOGLE_OAUTH_CLIENT_ACCESS_ERROR else "configured" if client else "absent"),
                  "token_state": ("access_denied" if GOOGLE_OAUTH_TOKEN_ACCESS_ERROR else "present" if token else "absent"),
                  "message": messages.get(configuration_error, "Google OAuth недоступний")}
        if not IS_WEB_ENV and feature["enabled"]:
            result["client_path"] = str(GOOGLE_OAUTH_CLIENT_PATH)
        return result
    has_refresh_token = bool(token and token.get("refresh_token"))
    token_expired = bool(token and not has_refresh_token and token.get("access_token") and
                         time.time() >= float(token.get("obtained_at", 0)) + int(token.get("expires_in", 3600)) - 120)
    result = {"configured": bool(client), "authorized": has_refresh_token,
            "enabled": feature["enabled"], "available": True, "configuration_error": "",
            "configuration_source": feature["configuration_source"],
            "client_state": "configured" if client else "absent",
            "token_state": "authorized" if has_refresh_token else "expired" if token_expired else "authorization_required" if client else "absent",
            "message": ("Google integration вимкнено адміністратором" if not feature["enabled"] else
                        "Google підключено для читання таблиць" if has_refresh_token else
                        "Токен Google прострочений · потрібна повторна авторизація" if token_expired else
                        "Потрібно увійти через Google" if client else
                        "Потрібен OAuth Client ID для локального застосунку")}
    if not IS_WEB_ENV and feature["enabled"]:
        result["client_path"] = str(GOOGLE_OAUTH_CLIENT_PATH)
    return result


def google_oauth_authorization_url(actor: str = "") -> str:
    if not google_effective_enabled():
        raise RuntimeError("Google OAuth вимкнено у цьому середовищі")
    client = _google_oauth_client()
    if not client:
        if GOOGLE_OAUTH_CLIENT_ACCESS_ERROR:
            raise RuntimeError("Локальна конфігурація Google OAuth недоступна. Перевірте права доступу до файла налаштувань.")
        raise FileNotFoundError(f"OAuth client file not found: {GOOGLE_OAUTH_CLIENT_PATH}")
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    redirect_uri = _google_oauth_redirect_uri()
    _store_google_oauth_transaction(state, verifier, redirect_uri, actor)
    params = {"client_id": client["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
              "scope": GOOGLE_SHEETS_READONLY_SCOPE, "access_type": "offline", "prompt": "consent",
              "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    return (client.get("auth_uri") or "https://accounts.google.com/o/oauth2/auth") + "?" + urllib.parse.urlencode(params)


def google_oauth_exchange(code: str, state: str) -> dict:
    if not google_effective_enabled():
        raise RuntimeError("Google OAuth вимкнено у цьому середовищі")
    pending = _consume_google_oauth_transaction(state)
    client = _google_oauth_client()
    if not client:
        raise ValueError("Конфігурація Google OAuth недоступна")
    payload = {"code": code, "client_id": client["client_id"], "client_secret": client.get("client_secret", ""),
               "redirect_uri": pending["redirect_uri"], "grant_type": "authorization_code",
               "code_verifier": pending["code_verifier"]}
    request = urllib.request.Request(client.get("token_uri") or "https://oauth2.googleapis.com/token",
        data=urllib.parse.urlencode(payload).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=60) as response:
        token = json.loads(response.read().decode())
    token["obtained_at"] = time.time()
    with GOOGLE_TOKEN_WRITE_LOCK:
        _atomic_write_google_json(GOOGLE_OAUTH_TOKEN_PATH, token)
    return {"expected_origin": pending["expected_origin"]}


def _google_access_token() -> str:
    if not google_effective_enabled():
        raise PermissionError("Google integration вимкнено адміністратором")
    with GOOGLE_TOKEN_WRITE_LOCK:
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
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                refreshed = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            _raise_google_phase_error("oauth_token_refresh", exc)
        token.update(refreshed); token["obtained_at"] = time.time()
        _atomic_write_google_json(GOOGLE_OAUTH_TOKEN_PATH, token)
        return token["access_token"]


def _google_sheet_values(sheet_name: str, spreadsheet_id: str = SUPPLIER_EDR_SHEET_ID,
                         columns: str = "A:O") -> list[list]:
    if not google_effective_enabled():
        raise PermissionError("Google integration вимкнено адміністратором")
    cell_range = urllib.parse.quote(f"'{sheet_name}'!{columns}", safe="")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{cell_range}?majorDimension=ROWS"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {_google_access_token()}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode()).get("values", [])
    except urllib.error.HTTPError as exc:
        _raise_google_phase_error("sheets_values_read", exc)


def google_integration_status() -> dict:
    oauth = google_oauth_status()
    with db() as con:
        last = con.execute("""SELECT finished_at,status FROM supplier_edr_sync_log
          ORDER BY id DESC LIMIT 1""").fetchone()
    return {
        **google_runtime_state(),
        "client_configured": bool(oauth.get("configured")),
        "oauth_connected": bool(oauth.get("authorized")),
        "client_state": oauth.get("client_state", "absent"),
        "token_state": oauth.get("token_state", "absent"),
        "available": oauth.get("available", True),
        "message": oauth.get("message", ""),
        "last_edr_sync_at": last["finished_at"] if last else None,
        "last_edr_sync_status": last["status"] if last else None,
    }


def disconnect_google(actor: str) -> dict:
    with GOOGLE_TOKEN_WRITE_LOCK:
        existed = GOOGLE_OAUTH_TOKEN_PATH.is_file()
        if existed:
            GOOGLE_OAUTH_TOKEN_PATH.unlink()
    with db() as con:
        ensure_google_oauth_transactions(con)
        con.execute("DELETE FROM google_oauth_transactions")
        if existed:
            con.execute("""INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value)
              VALUES (?,?,?,?,?,?)""", (f"runtime_feature:{GOOGLE_RUNTIME_FEATURE_KEY}", now_iso(), actor,
              "google_oauth.connection", "connected", "removed_locally"))
    return google_integration_status()


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
    if incoming_is_edr and not normalized:
        return {"changed": False, "manager_id": current["id"] if current else None,
                "reason": "no_edr_manager_observation"}
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


def enrich_current_supplier_manager(con: sqlite3.Connection, supplier_code: str, manager_name: str,
                                    source: str = "ЄДР", observed_at: str | None = None) -> dict:
    """Improve the current manager display without opening a new identity cycle."""
    code = re.sub(r"\D", "", supplier_code or "")
    name = " ".join((manager_name or "").split())
    current = con.execute("""SELECT id,manager_name,source,updated_at FROM supplier_managers
      WHERE supplier_code=? AND is_current=1 ORDER BY id DESC LIMIT 1""", (code,)).fetchone()
    if not current or not name:
        return {"enriched": False, "manager_id": current["id"] if current else None,
                "reason": "current_manager_missing"}
    observed = observed_at or now_iso()
    incoming_is_edr = source.startswith("Google Sheets") or source == "ЄДР"
    current_is_manual = str(current["source"] or "").startswith("Підтверджено УО")
    if incoming_is_edr and current_is_manual:
        current_at = _parse_prozorro_date(current["updated_at"])
        incoming_at = _parse_prozorro_date(observed)
        if current_at and incoming_at and current_at >= incoming_at:
            return {"enriched": False, "manager_id": current["id"],
                    "reason": "newer_manual_value_preserved"}
    con.execute("""UPDATE supplier_managers
      SET manager_name=?,normalized_name=?,source=?,updated_at=? WHERE id=?""",
      (name, normalize_manager_name(name), source, observed, current["id"]))
    return {"enriched": True, "changed": False, "manager_id": current["id"],
            "reason": "representation_enriched"}


def establish_current_supplier_manager(con: sqlite3.Connection, supplier_code: str, manager_name: str,
                                       source: str = "ЄДР", observed_at: str | None = None) -> dict:
    """Create the first known manager without manufacturing a previous cycle."""
    code = re.sub(r"\D", "", supplier_code or "")
    name = " ".join((manager_name or "").split())
    normalized = normalize_manager_name(name)
    observed = observed_at or now_iso()
    current = con.execute("""SELECT id,manager_name,normalized_name FROM supplier_managers
      WHERE supplier_code=? AND is_current=1 ORDER BY id DESC LIMIT 1""", (code,)).fetchone()
    if not code or not normalized:
        return {"established": False, "manager_id": None, "reason": "missing_identity"}
    if current and normalize_manager_name(current["manager_name"]):
        return {"established": False, "manager_id": current["id"],
                "reason": "current_manager_already_exists"}
    if current:
        con.execute("""UPDATE supplier_managers SET manager_name=?,normalized_name=?,valid_from=?,
          valid_to=NULL,is_current=1,source=?,updated_at=? WHERE id=?""",
          (name, normalized, observed, source, observed, current["id"]))
        manager_id = current["id"]
    else:
        cursor = con.execute("""INSERT INTO supplier_managers
          (supplier_code,manager_name,normalized_name,valid_from,valid_to,is_current,source,created_at,updated_at)
          VALUES (?,?,?,?,NULL,1,?,?,?)""",
          (code, name, normalized, observed, source, observed, observed))
        manager_id = cursor.lastrowid
    return {"established": True, "changed": False, "manager_id": manager_id,
            "reason": "first_manager_established"}


def reestablish_current_supplier_manager(con: sqlite3.Connection, supplier_code: str, manager_name: str,
                                         source: str = "ЄДР", observed_at: str | None = None) -> dict:
    """Restore a known identity as current without rewriting its closed historical row."""
    result = establish_current_supplier_manager(con, supplier_code, manager_name, source, observed_at)
    if result.get("established"):
        return {**result, "reestablished": True, "reason": "known_manager_reestablished"}
    return {**result, "reestablished": False}


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
    created = changed = unchanged = removed = missing = skipped_blank = 0
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
            elif reason == "no_edr_manager_observation": skipped_blank += 1
    return {"profiles": len(profiles), "created": created, "changed": changed,
            "removed": removed, "missing": missing, "unchanged": unchanged,
            "skipped_blank": skipped_blank}


def supplier_edr_sync_status() -> dict:
    with db() as con:
        total = int(con.execute("SELECT COUNT(*) FROM supplier_edr_profiles").fetchone()[0])
        last = con.execute("""SELECT started_at,finished_at,status,processed,inserted,updated,error
          FROM supplier_edr_sync_log ORDER BY id DESC LIMIT 1""").fetchone()
    return {"total": total, "last": dict(last) if last else None, "oauth": google_oauth_status(),
            "source_url": f"https://docs.google.com/spreadsheets/d/{SUPPLIER_EDR_SHEET_ID}/edit",
            "state": dict(SUPPLIER_EDR_SYNC_STATE)}


EDR_EXPORT_HEADERS = [
    "Код ЄДРПОУ", "Стара Назва", "Старий Статус", "Старий ПІБ Керівника",
    "Фактична дата перевірки ЄДР",
]


def _export_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    parsed = parse_ukrainian_date(text)
    if parsed:
        return parsed
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def build_supplier_edr_export_rows(sheet_type: str, today=None, filters: dict | None = None) -> list[dict]:
    """Build the exact five-column ClarityChecker input without changing source data."""
    sheet_type = str(sheet_type or "").strip().upper()
    if sheet_type not in {"ФОП", "ЮО", "ALL"}:
        raise ValueError("Оберіть тип експорту: ФОП, ЮО або ALL")
    today = today or datetime.now().astimezone().date()
    profiles, latest, managers, admitted_dates, active, supplier_codes = {}, {}, {}, {}, {}, set()
    canonical_states = {}
    registry_member_codes = set()
    with db() as con:
        for raw in con.execute("SELECT * FROM supplier_edr_profiles"):
            item = dict(raw); code = _digits(item.get("supplier_code")); supplier_codes.add(code); profiles[code] = item
        for raw in con.execute("""SELECT s.supplier_code,s.supplier_name,s.date_published,s.synced_at,s.id,
          COALESCE(af.manager_name,'') manager_name FROM submissions s
          LEFT JOIN application_fields af ON af.submission_id=s.id
          ORDER BY COALESCE(NULLIF(s.date_published,''),s.synced_at) DESC,s.id DESC"""):
            item = dict(raw); code = _digits(item.get("supplier_code"))
            if code:
                supplier_codes.add(code); latest.setdefault(code, item)
        managers = {code: item.get("manager_name", "")
                    for code, item in edr_sync_v2.known_manager_map(con).items()}
        for raw in con.execute("""SELECT s.supplier_code,q.status,
          COALESCE(NULLIF(q.decision_date,''),s.date_published) event_date
          FROM submissions s LEFT JOIN qualifications q ON q.id=s.qualification_id"""):
            code = _digits(raw["supplier_code"])
            if not code:
                continue
            active[code] = active.get(code, 0) + (1 if raw["status"] == "active" else 0)
            if raw["status"] == "active" and str(raw["event_date"] or "") > admitted_dates.get(code, ""):
                admitted_dates[code] = str(raw["event_date"] or "")
        for raw in con.execute("""SELECT rc.supplier_code,q.status,
          COALESCE(NULLIF(q.decision_date,''),NULLIF(json_extract(rc.raw_json,'$.dateModified'),''),
                   NULLIF(json_extract(rc.raw_json,'$.date'),''),rc.synced_at) event_date
          FROM registry_contracts rc LEFT JOIN qualifications q ON q.id=rc.qualification_id
          WHERE COALESCE(rc.supplier_code,'')<>''"""):
            code = _digits(raw["supplier_code"])
            if not code:
                continue
            registry_member_codes.add(code)
            if raw["status"] == "active" and str(raw["event_date"] or "") > admitted_dates.get(code, ""):
                admitted_dates[code] = str(raw["event_date"] or "")
        has_code_filter = "supplier_codes" in (filters or {})
        requested_codes = {_digits(code) for code in (filters or {}).get("supplier_codes", set()) if _digits(code)}
        export_codes = requested_codes if has_code_filter else registry_member_codes
        canonical_states = edr_sync_v2.canonical_supplier_edr_states(con, export_codes, today=today)
    rows = []
    # The export contract is authoritative historical register membership, not
    # the current active count and not the potentially stale
    # submissions.qualification_id pointer.  This is the same population source
    # as the supplier KPI: registry_contracts -> qualifications.
    for code in sorted(requested_codes if has_code_filter else registry_member_codes):
        profile, last = profiles.get(code, {}), latest.get(code, {})
        rows.append({"code": code, "full_name": profile.get("full_name", ""),
          "short_name": profile.get("short_name", ""), "edr_manager": profile.get("manager_name", ""),
          "edr_status": profile.get("edr_status", ""), "edr_checked_at": profile.get("edr_checked_at", ""),
          "source_sheet": profile.get("source_sheet", ""),
          "termination_decision_details": profile.get("termination_decision_details", ""),
          "edr_officer": profile.get("edr_officer", ""), "edr_notes": profile.get("edr_notes", ""),
          "latest_name": last.get("supplier_name", ""), "latest_manager": last.get("manager_name", ""),
          "current_manager": managers.get(code, ""), "last_admit": admitted_dates.get(code, ""),
          "active_count": active.get(code, 0)})
    result = []
    for row in rows:
        source_type = str(row["source_sheet"] or "").strip().upper()
        name = str(row["full_name"] or row["latest_name"] or "")
        inferred_fop = bool(re.search(r"\bФОП\b|ФІЗИЧНА\s+ОСОБА[\s-]*ПІДПРИЄМЕЦЬ", name, re.I))
        canonical_type = supplier_entity_type(row["code"])
        actual_type = source_type if source_type in {"ФОП", "ЮО"} else (
            "ФОП" if canonical_type == "individual_entrepreneur" or inferred_fop else "ЮО")
        if sheet_type != "ALL" and actual_type != sheet_type:
            continue
        state = canonical_states.get(row["code"], {})
        verification = state.get("verification_event") or {}
        checked = _export_date(verification.get("occurred_at") or row["edr_checked_at"])
        effective_checked = checked
        prozorro_status = state.get("prozorro_status", "Неактивний")
        requested = filters or {}
        allowed_statuses = requested.get("prozorro_statuses") or (
            {"Активний", "Призупинений", "Неактивний", "Ще не в реєстрі"}
            if requested.get("selected_mode") else {"Активний", "Призупинений"})
        if prozorro_status not in allowed_statuses:
            continue
        if requested.get("freshness_bucket") and state.get("bucket") != requested["freshness_bucket"]:
            continue
        checked_iso = effective_checked.isoformat() if effective_checked else ""
        if requested.get("verification_from") and (not checked_iso or checked_iso < requested["verification_from"]):
            continue
        if requested.get("verification_to") and (not checked_iso or checked_iso > requested["verification_to"]):
            continue
        result.append(dict(zip(EDR_EXPORT_HEADERS, [
            row["code"], name, str(row["edr_status"] or ""),
            row["current_manager"] or row["edr_manager"] or row["latest_manager"],
            effective_checked.strftime("%Y-%m-%d 00:00:00") if effective_checked else "",
        ])))
    return result


def supplier_edr_export_csv(sheet_type: str, filters: dict | None = None) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=EDR_EXPORT_HEADERS, delimiter=",", lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(build_supplier_edr_export_rows(sheet_type, filters=filters))
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def edr_monitoring_export_csv(supplier_codes) -> bytes:
    """Serialize the exact monitoring population with the established ClarityChecker contract."""
    requested = {str(code or "") for code in supplier_codes if str(code or "")}
    source = {row["supplier_code"]: row for row in _edr_monitoring_rows()}
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=EDR_EXPORT_HEADERS, delimiter=",", lineterminator="\r\n")
    writer.writeheader()
    for code in sorted(requested):
        row = source.get(code)
        if not row: continue
        writer.writerow(dict(zip(EDR_EXPORT_HEADERS, [
            code, row["supplier_name"], row["edr_status"], row["manager_name"],
            f"{row['verification_date']} 00:00:00" if row["verification_date"] else "",
        ])))
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


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
            # Source verification date, never the PQM import timestamp.
            "edr_checked_at": clean.get("Дата перевірки", clean.get("Дата перевірки ЄДР", "")),
            "termination_decision_details": clean.get("Реквізити рішення про припинення", ""),
            "edr_officer": clean.get("УО", ""),
            "edr_notes": clean.get("Примітки", ""),
            "source_sheet": sheet_name,
            "source_row": row_number,
        })
    return rows


def supplier_edr_source_snapshot() -> dict:
    """Read both canonical tabs and fingerprint their exact values as one revision."""
    return edr_sync_v2.source_snapshot({
        sheet_name: _google_sheet_values(sheet_name)
        for sheet_name in SUPPLIER_EDR_SHEETS
    })


def supplier_edr_sync_preview() -> dict:
    """Return a compact, mutation-free preview for explicit user confirmation."""
    snapshot = supplier_edr_source_snapshot()
    with db() as con:
        preview = edr_sync_v2.build_preview(con, snapshot)
    return {
        "source_fingerprint": preview["source_fingerprint"],
        "previewed_at": preview["previewed_at"],
        "summary": preview["summary"],
        "conflicts": preview["conflicts"][:200],
        "conflicts_total": len(preview["conflicts"]),
        "changes": [
            {key: item[key] for key in ("supplier_code", "source_sheet", "source_row",
              "population", "apply_allowed", "changed_fields", "verification_event_change",
              "termination_explicit_clear", "manager_change_kind", "manager_previous_name",
              "manager_change_reason", "manager_resolution_source",
              "manager_conflicting_evidence", "conflicts")}
            for item in preview["items"]
            if item["changed_fields"] or item["verification_event_change"] or item["conflicts"]
        ][:500],
    }


def supplier_edr_sync_worker(expected_fingerprint: str, actor: str) -> None:
    started_at = now_iso()
    log_id = None
    try:
        SUPPLIER_EDR_SYNC_STATE.update(running=True, message="Завантаження вкладок ФОП та ЮО…",
                                       started_at=started_at, updated_at=None, processed=0,
                                       inserted=0, updated=0, error=None)
        with db() as con:
            log_id = con.execute("INSERT INTO supplier_edr_sync_log(started_at,status) VALUES (?,?)",
                                 (started_at, "running")).lastrowid
        snapshot = supplier_edr_source_snapshot()
        if snapshot["source_fingerprint"] != expected_fingerprint:
            raise RuntimeError("Google source змінився після preview. Виконайте новий preview")
        synced_at = now_iso()
        with db() as con:
            edr_sync_v2.migrate(con)
            con.commit()
            con.execute("BEGIN IMMEDIATE")
            result = edr_sync_v2.apply(
                con, snapshot, expected_fingerprint, confirmed=True, actor=actor,
                synced_at=synced_at, sync_manager=sync_current_supplier_manager,
                enrich_manager=enrich_current_supplier_manager,
                establish_manager=establish_current_supplier_manager,
                reestablish_manager=reestablish_current_supplier_manager,
                refresh_manager_controls=refresh_current_submission_nazk_controls,
            )
            con.execute("""UPDATE supplier_edr_sync_log SET finished_at=?,status='completed',processed=?,
              inserted=?,updated=?,source_fingerprint=?,unchanged=?,details_json=? WHERE id=?""",
              (synced_at, result["processed"], result["inserted"], result["updated_profiles"],
               result["source_fingerprint"], result["unchanged"],
               json.dumps(result, ensure_ascii=False), log_id))
        SUPPLIER_EDR_SYNC_STATE.update(running=False,
            message=f"Застосовано: {result['inserted']} нових, {result['updated_profiles']} змінених профілів",
            updated_at=synced_at, processed=result["processed"], inserted=result["inserted"],
            updated=result["updated_profiles"], changed_fields=result["changed_fields"], error=None,
            last_completed_at=synced_at, last_result="completed",
            last_message=f"Застосовано: {result['inserted']} нових, {result['updated_profiles']} змінених профілів")
    except Exception as exc:
        SERVER_LOG.exception("Supplier EDR synchronization failed")
        finished_at = now_iso()
        if log_id:
            with db() as con:
                con.execute("UPDATE supplier_edr_sync_log SET finished_at=?,status='failed',error=? WHERE id=?",
                            (finished_at, str(exc), log_id))
        SUPPLIER_EDR_SYNC_STATE.update(running=False, message=f"Помилка синхронізації ЄДР: {exc}",
                                       updated_at=finished_at, error=str(exc), last_completed_at=finished_at,
                                       last_result="failed", last_message=f"Помилка синхронізації ЄДР: {exc}")


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
          processed=len(source_rows), inserted=inserted, updated=updated, error=None,
          last_completed_at=synced_at, last_result="completed",
          last_message=f"Синхронізовано {len(source_rows)} перевірок НАЗК")
    except Exception as exc:
        SERVER_LOG.exception("Supplier NACP review synchronization failed")
        finished_at = now_iso()
        if log_id:
            with db() as con:
                con.execute("UPDATE supplier_nazk_review_sync_log SET finished_at=?,status='failed',error=? WHERE id=?",
                            (finished_at,str(exc),log_id))
        SUPPLIER_NAZK_REVIEW_SYNC_STATE.update(running=False,message=f"Помилка синхронізації перевірок НАЗК: {exc}",
                                               updated_at=finished_at,error=str(exc),last_completed_at=finished_at,
                                               last_result="failed",last_message=f"Помилка синхронізації перевірок НАЗК: {exc}")


_SUPPLIER_RISK_CACHE = {"fingerprint": None, "amcu_codes": set(), "nazk_codes": set()}
_SUPPLIER_RISK_CACHE_LOCK = threading.Lock()


def supplier_risk_projection(con=None) -> dict:
    """Independent aggregate for supplier KPI/risk filters, cached by source revisions."""
    owns_connection = con is None
    con = con or db()
    try:
        fingerprint = tuple(con.execute("""SELECT
          (SELECT COUNT(*)||':'||COALESCE(MAX(synced_at),'') FROM supplier_edr_profiles),
          (SELECT COUNT(*)||':'||COALESCE(MAX(updated_at),'') FROM application_fields
             WHERE COALESCE(manager_name,'')<>''),
          (SELECT COUNT(*)||':'||COALESCE(MAX(source_id),'') FROM nazk_registry),
          (SELECT COUNT(*)||':'||COALESCE(MAX(synced_at),'') FROM supplier_nazk_reviews),
          (SELECT COUNT(*)||':'||COALESCE(MAX(row_key),'') FROM amcu_registry)""").fetchone())
        with _SUPPLIER_RISK_CACHE_LOCK:
            if _SUPPLIER_RISK_CACHE["fingerprint"] == fingerprint:
                return {"amcu_codes": set(_SUPPLIER_RISK_CACHE["amcu_codes"]),
                        "nazk_codes": set(_SUPPLIER_RISK_CACHE["nazk_codes"])}
        amcu_codes = {_digits(row[0]) for row in con.execute(
            "SELECT DISTINCT offender_code FROM amcu_registry WHERE offender_code<>''") if _digits(row[0])}
        nazk_names = {" ".join(re.sub(r"[’'`\-]+", " ", (row[0] or "").casefold()).split())
                      for row in con.execute("SELECT DISTINCT full_name FROM nazk_registry WHERE full_name<>''")}
        nazk_codes = {row[0] for row in con.execute(
            "SELECT supplier_code,manager_name FROM supplier_edr_profiles WHERE COALESCE(manager_name,'')<>''")
            if " ".join(re.sub(r"[’'`\-]+", " ", (row[1] or "").casefold()).split()) in nazk_names}
        nazk_codes.update(row[0] for row in con.execute("""SELECT DISTINCT s.supplier_code,af.manager_name
            FROM submissions s JOIN application_fields af ON af.submission_id=s.id
            LEFT JOIN supplier_edr_profiles ep ON ep.supplier_code=s.supplier_code
            WHERE COALESCE(af.manager_name,'')<>'' AND COALESCE(ep.manager_name,'')=''""")
            if " ".join(re.sub(r"[’'`\-]+", " ", (row[1] or "").casefold()).split()) in nazk_names)
        reviews = {row[0]: dict(row) for row in con.execute("SELECT * FROM supplier_nazk_reviews")}
        current_managers = {row[0]: " ".join(re.sub(r"[’'`\-]+", " ", (row[1] or "").casefold()).split())
                            for row in con.execute("SELECT supplier_code,manager_name FROM supplier_edr_profiles")}
        nazk_codes.difference_update(reviews)
        nazk_codes.update(code for code, review in reviews.items()
            if review.get("result") in {"підтверджено", "на запит", "можливо"}
            and current_managers.get(code)
            and current_managers.get(code) == " ".join(re.sub(r"[’'`\-]+", " ",
                (review.get("manager_name") or "").casefold()).split()))
        with _SUPPLIER_RISK_CACHE_LOCK:
            _SUPPLIER_RISK_CACHE.update(fingerprint=fingerprint,
                amcu_codes=set(amcu_codes), nazk_codes=set(nazk_codes))
        return {"amcu_codes": amcu_codes, "nazk_codes": nazk_codes}
    finally:
        if owns_connection:
            con.close()


def supplier_risk_counts() -> dict:
    projection = supplier_risk_projection()
    with db() as con:
        population = {row[0] for row in con.execute("SELECT supplier_code FROM supplier_registry_summary")}
        population.update(row[0] for row in con.execute(
            "SELECT DISTINCT supplier_code FROM submissions WHERE COALESCE(supplier_code,'')<>''"))
    normalized_population = {_digits(code) for code in population if _digits(code)}
    return {"amcu_total": len(normalized_population & projection["amcu_codes"]),
            "nazk_total": len(population & projection["nazk_codes"])}


def _edr_monitoring_source_sql() -> str:
    """One-row-per-supplier operational projection; deliberately excludes dossier analytics."""
    return """
      WITH population AS MATERIALIZED (
      """ + edr_sync_v2.MONITORING_POPULATION_SQL + """
      ), registry AS MATERIALIZED (
        SELECT supplier_code,
          MAX(COALESCE(active_count,0)) active_count,
          MAX(COALESCE(suspended_count,0)) suspended_count,
          MAX(COALESCE(NULLIF(supplier_name,''),'')) registry_name
        FROM supplier_registry_summary GROUP BY supplier_code
      ), latest_application AS MATERIALIZED (
        SELECT supplier_code,supplier_name,manager_name,latest_application_date FROM (
          SELECT s.supplier_code,s.supplier_name,
            COALESCE(af.manager_name,'') manager_name,
            NORMALIZED_DATE(COALESCE(NULLIF(s.date_published,''),s.synced_at)) latest_application_date,
            ROW_NUMBER() OVER (PARTITION BY s.supplier_code
              ORDER BY COALESCE(NULLIF(s.date_published,''),s.synced_at) DESC,s.id DESC) rank
          FROM submissions s LEFT JOIN application_fields af ON af.submission_id=s.id
          JOIN population p ON p.supplier_code=s.supplier_code
        ) WHERE rank=1
      ), latest_admission AS MATERIALIZED (
        SELECT supplier_code,occurred_at,officer,submission_id FROM (
          SELECT s.supplier_code,
            NORMALIZED_DATE(COALESCE(NULLIF(af.protocol_date,''),NULLIF(q.decision_date,''),
              NULLIF(s.date_published,''))) occurred_at,
            COALESCE(af.protocol_officer,'') officer,s.id submission_id,
            ROW_NUMBER() OVER (PARTITION BY s.supplier_code ORDER BY
              NORMALIZED_DATE(COALESCE(NULLIF(af.protocol_date,''),NULLIF(q.decision_date,''),
                NULLIF(s.date_published,''))) DESC,s.id DESC) rank
          FROM submissions s JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN qualifications q ON q.id=s.qualification_id
          JOIN population p ON p.supplier_code=s.supplier_code
          WHERE af.protocol_decision='admit'
        ) WHERE rank=1 AND occurred_at<>''
      ), current_manager AS MATERIALIZED (
        SELECT supplier_code,manager_name FROM (
          SELECT sm.supplier_code,sm.manager_name,
            ROW_NUMBER() OVER (PARTITION BY sm.supplier_code
              ORDER BY COALESCE(sm.updated_at,sm.created_at,'') DESC,sm.id DESC) rank
          FROM supplier_managers sm JOIN population p ON p.supplier_code=sm.supplier_code
          WHERE sm.is_current=1 AND TRIM(COALESCE(sm.manager_name,''))<>''
        ) WHERE rank=1
      ), verification_candidates AS MATERIALIZED (
        SELECT e.supplier_code,NORMALIZED_DATE(e.occurred_at) occurred_at,
          COALESCE(e.officer,'') officer,e.event_type,COALESCE(e.source,'') source,
          CASE e.event_type WHEN 'manual_edr' THEN 4 WHEN 'google_clarity' THEN 3 ELSE 2 END priority,
          COALESCE(e.created_at,'') created_at
        FROM supplier_edr_verification_events e JOIN population p ON p.supplier_code=e.supplier_code
        WHERE NORMALIZED_DATE(e.occurred_at)<>''
        UNION ALL
        SELECT ep.supplier_code,NORMALIZED_DATE(ep.edr_checked_at),COALESCE(ep.edr_officer,''),
          'google_clarity_profile','Google/Clarity profile snapshot',2,COALESCE(ep.synced_at,'')
        FROM supplier_edr_profiles ep JOIN population p ON p.supplier_code=ep.supplier_code
        WHERE NORMALIZED_DATE(ep.edr_checked_at)<>''
        UNION ALL
        SELECT supplier_code,occurred_at,officer,'admission','PQM application',1,submission_id
        FROM latest_admission
      ), latest_verification AS MATERIALIZED (
        SELECT supplier_code,occurred_at,officer,event_type,source FROM (
          SELECT *,ROW_NUMBER() OVER (PARTITION BY supplier_code
            ORDER BY occurred_at DESC,priority DESC,created_at DESC) rank
          FROM verification_candidates
        ) WHERE rank=1
      ), projection AS (
        SELECT p.supplier_code,
          COALESCE(NULLIF(ep.full_name,''),NULLIF(la.supplier_name,''),NULLIF(r.registry_name,''),'') supplier_name,
          COALESCE(NULLIF(cm.manager_name,''),NULLIF(ep.manager_name,''),NULLIF(la.manager_name,''),'') manager_name,
          COALESCE(ep.edr_status,'') edr_status,
          CASE WHEN COALESCE(r.active_count,0)>0 THEN 'Активний'
            WHEN COALESCE(r.suspended_count,0)>0 THEN 'Призупинений'
            WHEN r.supplier_code IS NOT NULL THEN 'Неактивний' ELSE 'Ще не в реєстрі' END prozorro_status,
          TRIM(COALESCE(ep.termination_decision_details,'')) termination_details,
          TRIM(COALESCE(ep.termination_record_date,'')) termination_record_date,
          TRIM(COALESCE(ep.termination_record_number,'')) termination_record_number,
          TRIM(COALESCE(ep.edr_notes,'')) google_note,
          COALESCE(ad.occurred_at,'') last_admission_date,
          COALESCE(la.latest_application_date,'') latest_application_date,
          COALESCE(v.occurred_at,'') verification_date,COALESCE(v.officer,'') verification_officer,
          COALESCE(v.event_type,'') verification_event_type,COALESCE(v.source,'') verification_source,
          EDR_FRESHNESS(CASE WHEN COALESCE(r.active_count,0)>0 THEN 'Активний'
            WHEN COALESCE(r.suspended_count,0)>0 THEN 'Призупинений'
            WHEN r.supplier_code IS NOT NULL THEN 'Неактивний' ELSE 'Ще не в реєстрі' END,
            COALESCE(v.occurred_at,'')) freshness
        FROM population p LEFT JOIN registry r ON r.supplier_code=p.supplier_code
        LEFT JOIN supplier_edr_profiles ep ON ep.supplier_code=p.supplier_code
        LEFT JOIN latest_application la ON la.supplier_code=p.supplier_code
        LEFT JOIN latest_admission ad ON ad.supplier_code=p.supplier_code
        LEFT JOIN current_manager cm ON cm.supplier_code=p.supplier_code
        LEFT JOIN latest_verification v ON v.supplier_code=p.supplier_code
      )
    """


EDR_MONITORING_CACHE = {"fingerprint": None, "rows": []}
EDR_MONITORING_DK_CACHE = {"fingerprint": None, "codes": {}}
EDR_MONITORING_CACHE_LOCK = threading.Lock()


def _edr_monitoring_revision() -> tuple:
    paths = [DB_PATH, Path(str(DB_PATH) + "-wal")]
    return tuple((path.stat().st_mtime_ns, path.stat().st_size) if path.exists() else (0, 0)
                 for path in paths)


def _edr_monitoring_rows() -> list[dict]:
    """Cache the set-based projection; every request still filters and paginates on the server."""
    fingerprint = _edr_monitoring_revision()
    with EDR_MONITORING_CACHE_LOCK:
        if EDR_MONITORING_CACHE["fingerprint"] == fingerprint:
            return EDR_MONITORING_CACHE["rows"]
        with db() as con:
            profiles = {row["supplier_code"]: dict(row) for row in con.execute(
                "SELECT * FROM supplier_edr_profiles WHERE supplier_code<>''")}
            registry = {row["supplier_code"]: dict(row) for row in con.execute(
                "SELECT * FROM supplier_registry_summary WHERE supplier_code<>''")}
            latest_app = {row["supplier_code"]: dict(row) for row in con.execute("""SELECT * FROM (
              SELECT s.supplier_code,s.supplier_name,COALESCE(af.manager_name,'') manager_name,
                COALESCE(NULLIF(s.date_published,''),s.synced_at) latest_application_date,
                ROW_NUMBER() OVER(PARTITION BY s.supplier_code ORDER BY
                  COALESCE(NULLIF(s.date_published,''),s.synced_at) DESC,s.id DESC) rank
              FROM submissions s LEFT JOIN application_fields af ON af.submission_id=s.id
              WHERE s.supplier_code<>'') WHERE rank=1""")}
            active_qualification_dates = edr_sync_v2.active_qualification_dates(con)
            managers = {row["supplier_code"]: row["manager_name"] for row in con.execute("""SELECT supplier_code,manager_name FROM (
              SELECT supplier_code,manager_name,ROW_NUMBER() OVER(PARTITION BY supplier_code ORDER BY
                COALESCE(updated_at,created_at,'') DESC,id DESC) rank FROM supplier_managers
               WHERE is_current=1 AND TRIM(COALESCE(manager_name,''))<>'') WHERE rank=1""")}
            ledger = {}
            for raw in con.execute("SELECT * FROM supplier_edr_verification_events"):
                item = dict(raw); code = item["supplier_code"]
                if edr_sync_v2.normalized_date(item.get("occurred_at")):
                    ledger.setdefault(code, []).append(item)
            eligible = {row[0] for row in con.execute("""SELECT DISTINCT s.supplier_code FROM submissions s
              JOIN application_fields af ON af.submission_id=s.id
              WHERE s.supplier_code<>'' AND af.protocol_decision IN ('admit','reject')""")}
            population = edr_sync_v2.monitoring_population_codes(con)
            verifications = edr_sync_v2.current_verification_projections(con, population)
            canonical_statuses = edr_sync_v2.canonical_prozorro_statuses(con, population)
            rows = []
            for code in population:
                profile, reg, application = profiles.get(code, {}), registry.get(code, {}), latest_app.get(code, {})
                verification = verifications[code]
                status = canonical_statuses[code]
                checked = verification["verification_date"]
                officer_raw = verification["verification_officer_raw"]
                displayed_edr_status = edr_sync_v2.operational_edr_status(
                    status, active_qualification_dates.get(code, ""), ledger.get(code, []),
                    profile.get("edr_status", ""))
                rows.append({"supplier_code": code,
                  "supplier_name": profile.get("full_name") or application.get("supplier_name") or reg.get("supplier_name", ""),
                  "edr_full_name": str(profile.get("full_name") or "").strip(),
                  "edr_short_name": str(profile.get("short_name") or "").strip(),
                  "manager_name": managers.get(code) or profile.get("manager_name") or application.get("manager_name", ""),
                  "edr_status": displayed_edr_status, "prozorro_status": status,
                  "termination_details": str(profile.get("termination_decision_details") or "").strip(),
                  "termination_record_date": str(profile.get("termination_record_date") or "").strip(),
                  "termination_record_number": str(profile.get("termination_record_number") or "").strip(),
                  "last_admission_date": verification["last_admission_date"],
                  "latest_application_date": edr_sync_v2.normalized_date(application.get("latest_application_date")),
                  "verification_date": checked,
                  "verification_officer": verification["verification_officer"],
                  "verification_officer_raw": officer_raw,
                  "verification_event_type": verification["verification_event_type"],
                  "verification_source": verification["verification_source"],
                  "google_note": str(profile.get("edr_notes") or "").strip(),
                  "freshness": edr_sync_v2.freshness_state(status, checked)["bucket"]})
        # Re-read after building: a concurrent mutation invalidates rather than blessing stale rows.
        final_fingerprint = _edr_monitoring_revision()
        if final_fingerprint == fingerprint:
            EDR_MONITORING_CACHE.update(fingerprint=fingerprint, rows=rows)
        return rows


def _edr_monitoring_dk_map() -> dict[str, set[str]]:
    fingerprint = _edr_monitoring_revision()
    if EDR_MONITORING_DK_CACHE["fingerprint"] == fingerprint:
        return EDR_MONITORING_DK_CACHE["codes"]
    result: dict[str, set[str]] = {}
    with db() as con:
        for row in con.execute("""SELECT supplier_code,dk_code FROM (
          SELECT rc.supplier_code,f.dk_code FROM registry_contracts rc
            JOIN frameworks f ON f.id=rc.framework_id WHERE COALESCE(f.dk_code,'')<>''
          UNION SELECT s.supplier_code,f.dk_code FROM submissions s
            JOIN frameworks f ON f.id=s.framework_id WHERE COALESCE(f.dk_code,'')<>'')"""):
            result.setdefault(str(row[0] or ""), set()).add(str(row[1] or ""))
    if _edr_monitoring_revision() == fingerprint:
        EDR_MONITORING_DK_CACHE.update(fingerprint=fingerprint, codes=result)
    return result


def _filter_edr_monitoring_rows(rows: list[dict], params: dict, *, include_freshness=True) -> list[dict]:
    value = lambda key: str((params.get(key) or [""])[0] or "").strip()
    values = lambda key: {part.strip() for raw in (params.get(key) or []) for part in str(raw or "").split(",") if part.strip()}
    search, dk_code = value("search").casefold(), value("dk_code")
    entity_type = value("entity_type")
    prozorro_statuses, edr_statuses = values("prozorro_status"), values("edr_status")
    freshness = value("freshness") if include_freshness else ""
    verified_from, verified_to = value("verification_from"), value("verification_to")
    application_from, application_to = value("application_from"), value("application_to")
    names_completeness = value("edr_names")
    if entity_type and entity_type not in {"individual_entrepreneur", "legal_entity"}:
        raise ValueError("Невідомий тип постачальника")
    result = []
    dk_map = _edr_monitoring_dk_map() if dk_code else {}
    for row in rows:
        if search and search not in " ".join((row["supplier_code"], row["supplier_name"], row["manager_name"], str(row.get("google_note") or ""))).casefold(): continue
        if dk_code and dk_code not in dk_map.get(row["supplier_code"], set()): continue
        if entity_type and supplier_entity_type(row["supplier_code"]) != entity_type: continue
        if prozorro_statuses and row["prozorro_status"] not in prozorro_statuses: continue
        if edr_statuses and row["edr_status"] not in edr_statuses: continue
        full_name, short_name = bool(row.get("edr_full_name")), bool(row.get("edr_short_name"))
        if names_completeness == "complete" and not (full_name and short_name): continue
        if names_completeness == "missing_any" and full_name and short_name: continue
        if names_completeness == "missing_full" and full_name: continue
        if names_completeness == "missing_short" and short_name: continue
        if names_completeness and names_completeness not in {"complete", "missing_any", "missing_full", "missing_short"}:
            raise ValueError("Невідомий фільтр повноти назв ЄДР")
        if freshness and row["freshness"] != freshness: continue
        if verified_from and row["verification_date"] < verified_from: continue
        if verified_to and row["verification_date"] > verified_to: continue
        if application_from and row["latest_application_date"] < application_from: continue
        if application_to and row["latest_application_date"] > application_to: continue
        result.append(row)
    return result


def _edr_monitoring_filters(params: dict, *, include_freshness: bool = True) -> tuple[str, list]:
    search = params.get("search", [""])[0].strip().casefold()
    dk_code = params.get("dk_code", [""])[0].strip()
    entity_type = params.get("entity_type", [""])[0].strip()
    multi_values = lambda key: [part.strip() for raw in (params.get(key) or []) for part in str(raw or "").split(",") if part.strip()]
    prozorro_statuses = multi_values("prozorro_status")
    edr_statuses = multi_values("edr_status")
    freshness = params.get("freshness", [""])[0].strip() if include_freshness else ""
    verified_from = params.get("verification_from", [""])[0].strip()
    verified_to = params.get("verification_to", [""])[0].strip()
    application_from = params.get("application_from", [""])[0].strip()
    application_to = params.get("application_to", [""])[0].strip()
    where, args = ["1=1"], []
    if search:
        where.append("(INSTR(CASEFOLD(supplier_code),?)>0 OR INSTR(CASEFOLD(supplier_name),?)>0 OR INSTR(CASEFOLD(manager_name),?)>0 OR INSTR(CASEFOLD(COALESCE(google_note,'')),?)>0)")
        args.extend([search] * 4)
    if entity_type:
        if entity_type not in {"individual_entrepreneur", "legal_entity"}:
            raise ValueError("Невідомий тип постачальника")
        where.append("SUPPLIER_ENTITY_TYPE(supplier_code)=?"); args.append(entity_type)
    if prozorro_statuses:
        where.append(f"prozorro_status IN ({','.join('?' for _ in prozorro_statuses)})"); args.extend(prozorro_statuses)
    if edr_statuses:
        where.append(f"edr_status IN ({','.join('?' for _ in edr_statuses)})"); args.extend(edr_statuses)
    if verified_from:
        where.append("verification_date>=?"); args.append(verified_from)
    if verified_to:
        where.append("verification_date<=?"); args.append(verified_to)
    if application_from:
        where.append("latest_application_date>=?"); args.append(application_from)
    if application_to:
        where.append("latest_application_date<=?"); args.append(application_to)
    if dk_code:
        where.append("""(EXISTS (SELECT 1 FROM registry_contracts rc JOIN frameworks f ON f.id=rc.framework_id
          WHERE rc.supplier_code=projection.supplier_code AND f.dk_code=?) OR EXISTS
          (SELECT 1 FROM submissions s JOIN frameworks f ON f.id=s.framework_id
           WHERE s.supplier_code=projection.supplier_code AND f.dk_code=?))""")
        args.extend([dk_code, dk_code])
    if freshness:
        where.append("freshness=?"); args.append(freshness)
    return " AND ".join(where), args


def edr_monitoring_filtered_codes(params: dict) -> list[str]:
    return sorted(row["supplier_code"] for row in _filter_edr_monitoring_rows(_edr_monitoring_rows(), params))


def list_edr_monitoring(params: dict) -> dict:
    """Fast operational EDR register with independent server-side pagination and KPI."""
    page = max(1, int(params.get("page", ["1"])[0] or 1))
    size = min(200, max(10, int(params.get("size", ["100"])[0] or 100)))
    started = time.perf_counter()
    projection = _edr_monitoring_rows()
    filtered = _filter_edr_monitoring_rows(projection, params)
    kpi_population = _filter_edr_monitoring_rows(projection, params, include_freshness=False)
    kpis = {}
    for row in kpi_population: kpis[row["freshness"]] = kpis.get(row["freshness"], 0) + 1
    sort_key = str((params.get("sort") or ["freshness"])[0] or "freshness").strip()
    sort_direction = str((params.get("direction") or ["asc"])[0] or "asc").strip().lower()
    allowed_sorts = {
        "freshness", "supplier_code", "supplier_name", "manager_name", "edr_status",
        "prozorro_status", "termination_details", "latest_application_date",
        "verification_date", "verification_officer", "google_note",
    }
    if sort_key not in allowed_sorts or sort_direction not in {"asc", "desc"}:
        raise ValueError("Невідоме сортування")
    freshness_order = {"not_checked": 0, "gt90": 1, "gt60": 2, "gt30": 3, "lt30": 4, "not_current": 5}
    def sortable(row):
        value = freshness_order.get(row.get("freshness"), 6) if sort_key == "freshness" else row.get(sort_key, "")
        if isinstance(value, str): value = value.casefold()
        return (value, row["supplier_code"])
    filtered.sort(key=sortable, reverse=sort_direction == "desc")
    total = len(filtered); offset = (page - 1) * size
    page_rows = filtered[offset:offset + size]
    statuses = sorted({row["edr_status"] for row in projection if row["edr_status"]})
    return {"items": [{key: value for key, value in row.items() if not key.startswith("_")}
                      for row in page_rows],
            "total": total, "page": page, "size": size,
            "pages": max(1, (total + size - 1) // size), "kpis": kpis,
            "edr_statuses": statuses, "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)}


def list_qualified_suppliers(params: dict) -> dict:
    """Return registered suppliers and applicants that have not entered a register yet."""
    search = params.get("search", [""])[0].strip().casefold()
    status = params.get("status", [""])[0].strip()
    risk = params.get("risk", [""])[0].strip()
    dk_code = params.get("dk_code", [""])[0].strip()
    edr_status = params.get("edr_status", [""])[0].strip()
    entity_type = params.get("entity_type", [""])[0].strip()
    freshness = params.get("freshness", [""])[0].strip()
    verification_from = params.get("verification_from", [""])[0].strip()
    verification_to = params.get("verification_to", [""])[0].strip()
    admission_from = params.get("admission_from", [""])[0].strip()
    admission_to = params.get("admission_to", [""])[0].strip()
    include_codes = params.get("_include_codes", [""])[0] == "1"
    if entity_type and entity_type not in {"individual_entrepreneur", "legal_entity"}:
        raise ValueError("Невідомий тип постачальника")
    page = max(1, int(params.get("page", ["1"])[0] or 1))
    size = min(200, max(10, int(params.get("size", ["100"])[0] or 100)))
    if risk in {"amcu", "nazk"}:
        with db() as risk_con:
            risk_projection = supplier_risk_projection(risk_con)
    else:
        risk_projection = {"amcu_codes": set(), "nazk_codes": set()}
    amcu_match_codes = risk_projection["amcu_codes"]
    nazk_match_codes = risk_projection["nazk_codes"]
    where, args = ["1=1"], []
    if search:
        where.append("(INSTR(CASEFOLD(supplier_code),?)>0 OR INSTR(CASEFOLD(supplier_name),?)>0 OR EXISTS "
          "(SELECT 1 FROM supplier_edr_profiles ep WHERE ep.supplier_code=combined.supplier_code "
          "AND INSTR(CASEFOLD(ep.full_name),?)>0))")
        args.extend([search, search, search])
    if status == "active":
        where.append("active_count>0")
    elif status == "suspended":
        where.append("active_count=0 AND suspended_count>0")
    elif status == "terminated":
        where.append("registry_state='registered' AND active_count=0 AND suspended_count=0")
    elif status == "not_registered":
        where.append("registry_state='not_registered'")
    if freshness:
        where.append("CANONICAL_FRESHNESS(DIGITS(combined.supplier_code))=?")
        args.append(freshness)
    if verification_from:
        where.append("CANONICAL_VERIFICATION_DATE(DIGITS(combined.supplier_code))>=?")
        args.append(verification_from)
    if verification_to:
        where.append("CANONICAL_VERIFICATION_DATE(DIGITS(combined.supplier_code))<=?")
        args.append(verification_to)
    if admission_from:
        where.append("CANONICAL_LAST_ADMISSION(DIGITS(combined.supplier_code))>=?")
        args.append(admission_from)
    if admission_to:
        where.append("CANONICAL_LAST_ADMISSION(DIGITS(combined.supplier_code))<=?")
        args.append(admission_to)
    if risk == "amcu":
        codes = sorted(code for code in amcu_match_codes if code)
        where.append("DIGITS(combined.supplier_code) IN (" + ",".join("?" for _ in codes) + ")" if codes else "0=1")
        args.extend(codes)
    elif risk == "nazk":
        codes = sorted(code for code in nazk_match_codes if code)
        where.append("combined.supplier_code IN (" + ",".join("?" for _ in codes) + ")" if codes else "0=1")
        args.extend(codes)
    if edr_status:
        # Same current, one-row-per-code snapshot as supplier_profile; never history/sync date.
        where.append("EXISTS (SELECT 1 FROM supplier_edr_profiles ep WHERE ep.supplier_code=DIGITS(combined.supplier_code) AND ep.edr_status=?)")
        args.append(edr_status)
    if entity_type:
        where.append("SUPPLIER_ENTITY_TYPE(combined.supplier_code)=?")
        args.append(entity_type)
    clause = " AND ".join(where)
    # Aggregate inside the selected CPV first.  Filtering the already
    # materialized supplier summary would mix a CPV from one qualification
    # with a status from another qualification of the same supplier.
    source = f"""
      WITH applicants AS (
        SELECT s.supplier_code,
          MAX(COALESCE(NULLIF(s.supplier_name,''),'Назву не отримано')) supplier_name,
          COUNT(*) applications_count, MAX(s.date_published) last_application,
          GROUP_CONCAT(DISTINCT NULLIF(f.dk_code,'')) application_dk_codes
        FROM submissions s LEFT JOIN frameworks f ON f.id=s.framework_id
        WHERE COALESCE(s.supplier_code,'')<>'' AND (?='' OR f.dk_code=?) GROUP BY s.supplier_code
      ), scoped_registry AS (
        SELECT rc.supplier_code,
          MAX(COALESCE(NULLIF(r.supplier_name,''),'Назву не отримано')) supplier_name,
          COUNT(DISTINCT rc.id) qualifications_count,
          SUM(CASE WHEN {supplier_activity.effective_active_sql('rc','f')} THEN 1 ELSE 0 END) active_count,
          COUNT(DISTINCT rc.id)-SUM(CASE WHEN {supplier_activity.effective_active_sql('rc','f')} THEN 1 ELSE 0 END) inactive_count,
          SUM(CASE WHEN rc.status='suspended' THEN 1 ELSE 0 END) suspended_count,
          COUNT(DISTINCT rc.framework_id) frameworks_count,
          GROUP_CONCAT(DISTINCT NULLIF(f.dk_code,'')) dk_codes,
          MAX(COALESCE(NULLIF(json_extract(rc.raw_json,'$.dateModified'),''),
              NULLIF(json_extract(rc.raw_json,'$.date'),''),r.last_qualification,rc.synced_at)) last_qualification
        FROM registry_contracts rc
        LEFT JOIN frameworks f ON f.id=rc.framework_id
        LEFT JOIN supplier_registry_summary r ON r.supplier_code=rc.supplier_code
        WHERE COALESCE(rc.supplier_code,'')<>'' AND (?='' OR f.dk_code=?) GROUP BY rc.supplier_code
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
    source_args = [dk_code, dk_code, dk_code, dk_code]
    query_args = source_args + args
    with db() as con:
        con.create_function("SUPPLIER_ENTITY_TYPE", 1, lambda code: supplier_entity_type(str(code or "")), deterministic=True)
        canonical_states = (edr_sync_v2.canonical_supplier_edr_states(con)
                            if freshness or verification_from or verification_to
                            or admission_from or admission_to else {})
        if canonical_states:
            con.create_function("CANONICAL_FRESHNESS", 1, lambda code: (canonical_states.get(_digits(code)) or {}).get("bucket", "not_checked"), deterministic=True)
            con.create_function("CANONICAL_VERIFICATION_DATE", 1, lambda code: (canonical_states.get(_digits(code)) or {}).get("verification_date", ""), deterministic=True)
            con.create_function("CANONICAL_LAST_ADMISSION", 1, lambda code: (canonical_states.get(_digits(code)) or {}).get("last_admission_date", ""), deterministic=True)
        edr_statuses = [r[0] for r in con.execute("SELECT DISTINCT edr_status FROM supplier_edr_profiles WHERE TRIM(COALESCE(edr_status,''))<>'' ORDER BY edr_status")]
        if not con.execute("SELECT 1 FROM supplier_registry_summary LIMIT 1").fetchone():
            return {"items": [], "total": 0, "registered_total": 0, "not_registered": 0,
                    "active": 0, "page": 1, "size": size, "pages": 0, "building": True, "edr_statuses": edr_statuses}
        filtered_codes = []
        if include_codes:
            filtered_codes = [row[0] for row in con.execute(
                source + f" SELECT supplier_code FROM combined WHERE {clause} ORDER BY supplier_code",
                query_args)]
        rows = con.execute(source + f""" SELECT supplier_code code,supplier_name name,qualifications_count,
          active_count,inactive_count,suspended_count,frameworks_count,dk_codes,last_qualification,
          applications_count,last_application,registry_state,
          COUNT(*) OVER() __total,COALESCE(SUM(active_count) OVER(),0) __active_total,
          COALESCE(SUM(registry_state='registered') OVER(),0) __registered_total,
          COALESCE(SUM(registry_state='not_registered') OVER(),0) __not_registered
          FROM combined WHERE {clause}
          ORDER BY CASE registry_state WHEN 'registered' THEN 0 ELSE 1 END,
            CASE WHEN active_count>0 THEN 0 ELSE 1 END,supplier_code LIMIT ? OFFSET ?""",
          (*query_args, size, (page - 1) * size)).fetchall()
        if rows:
            total = int(rows[0]["__total"] or 0)
            active_total = int(rows[0]["__active_total"] or 0)
            registered_total = int(rows[0]["__registered_total"] or 0)
            not_registered = int(rows[0]["__not_registered"] or 0)
        else:
            total = active_total = registered_total = not_registered = 0
        amcu_codes = {re.sub(r"\D", "", row[0] or "") for row in con.execute(
            "SELECT DISTINCT offender_code FROM amcu_registry WHERE offender_code<>''"
        )}
        nazk_names = {" ".join(re.sub(r"[’'`\-]+", " ", (row[0] or "").casefold()).split()) for row in con.execute(
            "SELECT DISTINCT full_name FROM nazk_registry WHERE full_name<>''"
        )}
        supplier_codes = [row["code"] for row in rows]
        page_application_stats = {}
        if supplier_codes:
            placeholders = ",".join("?" for _ in supplier_codes)
            dk_clause = " AND f.dk_code=?" if dk_code else ""
            stats_args = [*supplier_codes, *([dk_code] if dk_code else [])]
            page_application_stats = {row["supplier_code"]: dict(row) for row in con.execute(f"""
              SELECT s.supplier_code,COUNT(*) applications_count,MAX(s.date_published) last_application,
                GROUP_CONCAT(DISTINCT NULLIF(f.dk_code,'')) application_dk_codes
              FROM submissions s LEFT JOIN frameworks f ON f.id=s.framework_id
              WHERE s.supplier_code IN ({placeholders}){dk_clause}
              GROUP BY s.supplier_code""", stats_args)}
        if not canonical_states:
            canonical_states = edr_sync_v2.canonical_supplier_edr_states(con, supplier_codes)
        manager_matches = {}
        known_managers = edr_sync_v2.known_manager_map(con, supplier_codes)
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
        nazk_reviews = {}
        current_manager_registry_matches = set()
        missing_registry_cancelled = set()
        if supplier_codes:
            placeholders = ",".join("?" for _ in supplier_codes)
            nazk_reviews = {row["supplier_code"]: dict(row) for row in con.execute(
                f"SELECT * FROM supplier_nazk_reviews WHERE supplier_code IN ({placeholders})", supplier_codes)}
            # Avoid a page-managers × full-NАЗК-registry function join.  The
            # normalized registry-name set is already loaded once above.
            current_manager_registry_matches = {row[0] for row in con.execute(f"""SELECT supplier_code,normalized_name
              FROM supplier_managers WHERE is_current=1
                AND supplier_code IN ({placeholders})""", supplier_codes)
                if str(row[1] or "") in nazk_names}
            missing_registry_cancelled = {row[0] for row in con.execute(f"""SELECT DISTINCT supplier_code
              FROM operational_tasks WHERE task_type='nazk_check'
                AND status='cancelled' AND resolution_code='nazk_record_no_longer_present'
                AND supplier_code IN ({placeholders})""", supplier_codes)}
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
            relevant_states = get_submission_nazk_states(
                con, [submission["id"] for submission in relevant_by_supplier.values()], nazk_names)
            for code, submission in relevant_by_supplier.items():
                state = relevant_states.get(submission["id"], {
                    "state": "not_required", "can_approve": True, "required": False,
                    "submission_id": submission["id"], "supplier_code": code,
                })
                application_nazk_states[code] = {
                    **state, "date_published": submission["date_published"] or ""
                }
    items = [dict(row) for row in rows]
    for item in items:
        for key in ("__total", "__active_total", "__registered_total", "__not_registered"):
            item.pop(key, None)
        application_stats = page_application_stats.get(item.get("code"), {})
        item["applications_count"] = int(application_stats.get("applications_count") or 0)
        item["last_application"] = application_stats.get("last_application") or ""
        if item.get("registry_state") == "not_registered":
            item["dk_codes"] = application_stats.get("application_dk_codes") or item.get("dk_codes") or ""
    for item in items:
        code = re.sub(r"\D", "", item.get("code") or "")
        profile = edr_profiles.get(code) or edr_profiles.get(item.get("code")) or {}
        canonical_state = canonical_states.get(code, {})
        verification = canonical_state.get("verification_event")
        if verification:
            profile = {**profile, "edr_checked_at": verification.get("occurred_at") or "",
                       "edr_officer": verification.get("officer") or "",
                       "verification_event_type": verification.get("event_type") or ""}
        item["name"] = edr_sync_v2.current_supplier_name(profile.get("full_name"), item.get("name"))
        item["edr_profile"] = profile
        item["current_manager"] = (known_managers.get(code) or {}).get("manager_name", "")
        item["current_manager_source"] = (known_managers.get(code) or {}).get("resolution_source", "")
        item["prozorro_status"] = canonical_state.get("prozorro_status", "Ще не в реєстрі")
        item["edr_freshness_marker"] = canonical_state.get("marker", "⚪ Не перевірено")
        item["edr_freshness_bucket"] = canonical_state.get("bucket", "not_checked")
        item["edr_verification_date"] = canonical_state.get("verification_date", "")
        item["edr_verification_officer"] = canonical_state.get("verification_officer", "")
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
        record_no_longer_present = (
            item.get("code") in missing_registry_cancelled
            and item.get("code") not in current_manager_registry_matches
        )
        item["nazk_presentation_state"] = get_supplier_nazk_presentation_state(
            item["nazk_application_state"].get("state"),
            (item["nazk_supplier_workflow"].get("workflow_status")
              or (latest_supplier_check.get("workflow_status")
                  if latest_supplier_check.get("workflow_status") == "not_current" else "")),
            registry_match=bool(item["nazk_match"]) and not record_no_longer_present,
            legacy_result=(latest_supplier_check.get("result")
              if latest_supplier_check.get("workflow_status") == "completed"
              else ((review or {}).get("result") if item.get("nazk_review_is_current", not review) else "")),
            registry_record_no_longer_present=record_no_longer_present,
        )
    return {"items": items, "total": total, "filtered_codes": filtered_codes,
            "edr_statuses": edr_statuses,
            "registered_total": registered_total, "not_registered": not_registered, "active": active_total,
            "page": page, "size": size, "pages": (total + size - 1) // size}


def latest_supplier_submission_name(con, code):
    row=con.execute('''SELECT supplier_name FROM submissions WHERE DIGITS(supplier_code)=?
      ORDER BY julianday(date_published) DESC,id DESC LIMIT 1''',(code,)).fetchone()
    return row[0] if row else ''

def supplier_profile(supplier_code: str) -> dict:
    """Full local PQM/Bids/registry card for one supplier."""
    code = re.sub(r"\D", "", urllib.parse.unquote(supplier_code or ""))
    if not code:
        raise KeyError(supplier_code)
    with db() as con:
        latest_submission_name = latest_supplier_submission_name(con,code)
        summary = con.execute("SELECT * FROM supplier_registry_summary WHERE DIGITS(supplier_code)=?", (code,)).fetchone()
        profile = con.execute("SELECT * FROM supplier_edr_profiles WHERE DIGITS(supplier_code)=?", (code,)).fetchone()
        supplier_note = con.execute("SELECT * FROM supplier_notes WHERE DIGITS(supplier_code)=?", (code,)).fetchone()
        current_manager_row = edr_sync_v2.resolve_known_manager(con, code)
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
        nazk_check_columns = {row[1] for row in con.execute("PRAGMA table_info(supplier_nazk_checks)")}
        canonical_select = {
          "result_at": "chk.result_at" if "result_at" in nazk_check_columns else "NULL",
          "result_by": "chk.result_by" if "result_by" in nazk_check_columns else "''",
          "person_tax_id": "chk.person_tax_id" if "person_tax_id" in nazk_check_columns else "''",
          "responsible_officer_id": "chk.responsible_officer_id" if "responsible_officer_id" in nazk_check_columns else "NULL",
          "responsible_officer_name": "chk.responsible_officer_name" if "responsible_officer_name" in nazk_check_columns else "''",
        }
        officer_join = ("LEFT JOIN authorized_officers officer ON officer.id=chk.responsible_officer_id"
          if "responsible_officer_id" in nazk_check_columns else "LEFT JOIN authorized_officers officer ON 1=0")
        supplier_nazk_checks = [dict(row) for row in con.execute(f"""SELECT
          chk.id,chk.manager_name,chk.workflow_status,chk.result,chk.started_at,chk.completed_at,
          chk.evidence_date,{canonical_select['result_at']} result_at,{canonical_select['result_by']} result_by,
          {canonical_select['person_tax_id']} person_tax_id,
          {canonical_select['responsible_officer_id']} responsible_officer_id,
          COALESCE(officer.full_name,{canonical_select['responsible_officer_name']},'') responsible_uo_name,
          chk.comment,chk.is_legacy,chk.created_by,chk.updated_by,
          doc.title document_title,doc.url document_url,doc.document_date
          FROM supplier_nazk_checks chk
          {officer_join}
          LEFT JOIN supplier_nazk_check_documents doc ON doc.id=(
            SELECT d.id FROM supplier_nazk_check_documents d WHERE d.check_id=chk.id
            ORDER BY d.created_at DESC,d.id DESC LIMIT 1)
          WHERE DIGITS(chk.supplier_code)=?
          ORDER BY COALESCE(chk.completed_at,chk.updated_at,chk.started_at) DESC,chk.id DESC""", (code,))]
        evidence_tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for check in supplier_nazk_checks:
            check["nazk_evidence"] = (nazk_evidence.get(con, int(check["id"]))
              if {"supplier_nazk_check_channels", "supplier_nazk_check_evidence"} <= evidence_tables
              else {**check, "nazk_check_id": check["id"], "registry_records": [],
                    "channels": {}, "evidence": [], "documents": []})
            check["evidence_set"] = check["nazk_evidence"]  # compatibility alias
        supplier_nazk_workflow = next((row for row in supplier_nazk_checks
          if row["workflow_status"] in ("needs_review","request_to_supplier","request_to_nazk","waiting_response")), {})
        qualifications = [dict(row) for row in con.execute("""WITH contract_events AS (
          SELECT rc.id,CASE WHEN rc.status='active' AND NOT (
              __EFFECTIVE_ACTIVE__)
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
          WHERE rn=1 ORDER BY COALESCE(dk_code,''),COALESCE(framework_title,''),framework_id""".replace(
              "__EFFECTIVE_ACTIVE__", supplier_activity.effective_active_sql('rc','f')), (code,))]
        # Current card KPIs and its qualification rows share one projection.
        # Never use the asynchronously refreshed registry summary for these counts.
        summary = dict(summary) if summary else {}
        summary["qualifications_count"] = len(qualifications)
        summary["active_count"] = sum(row["status"] == "active" for row in qualifications)
        summary["inactive_count"] = summary["qualifications_count"] - summary["active_count"]
        qualification_by_framework = {row["framework_id"]: row for row in qualifications}
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
        current_registry_match = bool(current_manager_row and con.execute(
            "SELECT 1 FROM nazk_registry WHERE NORMALIZE_NAME(full_name)=NORMALIZE_NAME(?) LIMIT 1",
            (current_manager_row["manager_name"],),
        ).fetchone())
        missing_registry_cancelled = bool(con.execute("""SELECT 1 FROM operational_tasks
          WHERE task_type='nazk_check' AND DIGITS(supplier_code)=?
            AND status='cancelled' AND resolution_code='nazk_record_no_longer_present' LIMIT 1""",
          (code,)).fetchone())
        record_no_longer_present = missing_registry_cancelled and not current_registry_match
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
        contacts = supplier_contacts(con, code)
        application_rows = [dict(row) for row in con.execute("""SELECT s.id,s.framework_id,
          COALESCE(NULLIF(f.pretty_id,''),f.id) framework_pretty_id,f.dk_code,f.title framework_title,
          COALESCE(fo.marketplace_url,'') marketplace_url,
          s.date_published,COALESCE(q.status,'pending') qualification_status,
          COALESCE(af.protocol_decision,'') protocol_decision,COALESCE(af.protocol_remarks,'') protocol_remarks,
          COALESCE(af.compliance_status,'') compliance_status,COALESCE(af.compliance_comments,'') compliance_comments,
          COALESCE(af.protocol_number,'') protocol_number,COALESCE(af.protocol_date,'') protocol_date,
          COALESCE(af.protocol_officer,'') protocol_officer,COALESCE(af.contract_details,'') contract_details
          FROM submissions s LEFT JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN qualifications q ON q.id=COALESCE((
            SELECT q2.id FROM qualifications q2 WHERE q2.submission_id=s.id
            ORDER BY CASE q2.status WHEN 'active' THEN 3 WHEN 'unsuccessful' THEN 2 ELSE 1 END DESC,
              COALESCE(NULLIF(q2.decision_date,''),q2.synced_at) DESC,q2.id DESC LIMIT 1
          ),s.qualification_id)
          LEFT JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id
          WHERE DIGITS(s.supplier_code)=?
          ORDER BY COALESCE(f.dk_code,''),COALESCE(f.title,''),s.framework_id,
            COALESCE(NULLIF(s.date_published,''),s.synced_at) DESC,s.id DESC""", (code,))]
        application_history_groups = []
        for framework_id, grouped_rows in itertools.groupby(application_rows, key=lambda row: row["framework_id"]):
            attempts = list(grouped_rows)
            for attempt in attempts:
                meddata = historical_applications.provenance(attempt["id"])
                attempt["historical_read_only"] = bool(meddata)
                attempt["historical_source"] = meddata or {}
            admitted = sum(1 for row in attempts if row["qualification_status"] == "active")
            rejected = sum(1 for row in attempts if row["qualification_status"] == "unsuccessful")
            latest = attempts[0]
            latest_remark = (latest["protocol_remarks"] or latest["compliance_comments"] or "").strip()
            application_history_groups.append({
                "framework_id": framework_id,
                "framework_pretty_id": latest["framework_pretty_id"],
                "marketplace_url": latest["marketplace_url"],
                "dk_code": latest["dk_code"], "framework_title": latest["framework_title"],
                "applications_count": len(attempts), "admitted_count": admitted,
                "rejected_count": rejected, "latest_date": latest["date_published"],
                "latest_status": latest["qualification_status"], "latest_remark": latest_remark,
                "current_qualification": dict(qualification_by_framework.get(latest["framework_pretty_id"], {})),
                "applications": attempts,
            })
        application_history_groups.sort(key=lambda group: ((group["dk_code"] or "").casefold(),
                                                            (group["framework_title"] or "").casefold(),
                                                            group["framework_pretty_id"] or ""))
    bids_summary = {"participations": 0, "wins": 0, "last_participation_date": ""}
    try:
        with bids_db() as con:
            row = con.execute("""SELECT COUNT(DISTINCT b.tender_id) participations,
              MAX(COALESCE(t.tender_start,t.date_created,b.bid_date)) last_participation_date
              FROM bids b LEFT JOIN tenders t ON t.tender_id=b.tender_id
              WHERE b.supplier_id=?""", (code,)).fetchone()
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
    latest_current_supplier_cycle = next((item for item in supplier_nazk_checks
        if " ".join(re.sub(r"[’'`\-]+", " ", str(item.get("manager_name") or "").casefold()).split()) == normalized_current_manager), {})
    latest_current_supplier_check = next((item for item in supplier_nazk_checks
        if item.get("workflow_status") == "completed"
        and " ".join(re.sub(r"[’'`\-]+", " ", str(item.get("manager_name") or "").casefold()).split()) == normalized_current_manager), {})
    nazk_presentation_state = get_supplier_nazk_presentation_state(
        nazk_application_state.get("state"),
        (supplier_nazk_workflow.get("workflow_status")
          or (latest_current_supplier_cycle.get("workflow_status")
              if latest_current_supplier_cycle.get("workflow_status") == "not_current" else "")),
        registry_match=bool(nazk) and not record_no_longer_present,
        legacy_result=(latest_current_supplier_check.get("result")
          or (nazk_review_data.get("result") if nazk_review_data.get("is_current_manager") else "")),
        registry_record_no_longer_present=record_no_longer_present,
    )
    profile_data = dict(profile) if profile else {}
    with db() as event_con:
        canonical_edr = edr_sync_v2.canonical_supplier_edr_states(event_con, [code]).get(code, {})
        verification = canonical_edr.get("verification_event")
    if verification:
        profile_data.update(edr_checked_at=verification.get("occurred_at") or "",
                            edr_officer=verification.get("officer") or "",
                            verification_event_type=verification.get("event_type") or "")
    return {"code": code, "latest_submission_name": latest_submission_name, "summary": dict(summary) if summary else {}, "edr_profile": profile_data,
            "edr_canonical": canonical_edr,
            "supplier_note": dict(supplier_note) if supplier_note else {"supplier_code": code, "note": "", "updated_at": None, "updated_by": ""},
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
            "contacts": contacts,
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
            # A manually registered selection has no factual Prozorro status
            # until the first successful metadata sync.
            item["status"] = "Не визначено"
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


def sync_violation_reports_worker(claimed: bool = False) -> None:
    if not claimed:
        with VIOLATION_SYNC_LOCK:
            if VIOLATION_SYNC_STATE["running"]:
                return
            VIOLATION_SYNC_STATE.update(running=True, message="Отримання переліку звернень…",
                                        processed=0, total=0, errors=0)
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
                SERVER_LOG.exception("Violation report synchronization failed report=%s", report_id)
                VIOLATION_SYNC_STATE["errors"] += 1
                VIOLATION_SYNC_STATE["last_error"] = f"{report_id}: {exc}"
            VIOLATION_SYNC_STATE.update(processed=index, message=f"Оновлено {index}/{len(pending)} звернень")
        error_note = f"; остання помилка: {VIOLATION_SYNC_STATE.get('last_error')}" if VIOLATION_SYNC_STATE["errors"] else ""
        VIOLATION_SYNC_STATE["message"] = f"Готово: у базі {len(feed)} звернень; оновлено {len(pending) - VIOLATION_SYNC_STATE['errors']}; помилок {VIOLATION_SYNC_STATE['errors']}{error_note}"
        rebuild_operational_tasks()
    except Exception as exc:
        SERVER_LOG.exception("Violation report synchronization worker failed")
        VIOLATION_SYNC_STATE["message"] = f"Помилка синхронізації звернень: {exc}"
    finally:
        VIOLATION_SYNC_STATE.update(running=False, updated_at=now_iso())
        SERVER_LOG.info('Appeals sync completed processed=%s total=%s errors=%s failed=%s',
                        VIOLATION_SYNC_STATE['processed'], VIOLATION_SYNC_STATE['total'],
                        VIOLATION_SYNC_STATE['errors'], VIOLATION_SYNC_STATE['message'].startswith('Помилка'))


def start_violation_reports_sync(*, trigger: str = "manual") -> bool:
    """Share process and SQLite locks between manual and scheduled refreshes."""
    with VIOLATION_SYNC_LOCK:
        if VIOLATION_SYNC_STATE["running"]:
            return False
        owner = scheduler_runtime.claim(DB_PATH, "violation_reports", trigger=trigger)
        if not owner:
            return False
        VIOLATION_SYNC_STATE.update(running=True, message="Отримання переліку звернень…",
                                    processed=0, total=0, errors=0)
        def guarded_worker():
            error = ''
            try:
                with scheduler_runtime.keepalive(DB_PATH, 'violation_reports', owner):
                    sync_violation_reports_worker(True)
                if VIOLATION_SYNC_STATE.get('errors'):
                    error = str(VIOLATION_SYNC_STATE.get('last_error') or VIOLATION_SYNC_STATE.get('message') or 'Sync errors')
            except Exception as exc:
                error = str(exc)
                raise
            finally:
                VIOLATION_SYNC_STATE['running'] = False
                _finish_scheduler_lease("violation_reports", owner, "error" if error else "ok", error)
        try:
            threading.Thread(target=guarded_worker, daemon=True).start()
        except Exception:
            scheduler_runtime.release(DB_PATH, "violation_reports", owner)
            VIOLATION_SYNC_STATE["running"] = False
            raise
        return True


def start_nazk_registry_refresh(*, trigger: str = "manual") -> bool:
    owner = scheduler_runtime.claim(DB_PATH, "nazk_registry", trigger=trigger)
    if not owner:
        return False
    heartbeat = scheduler_runtime.keepalive(DB_PATH, 'nazk_registry', owner)
    def failed(error):
        # A failed fetch must release the lease/heartbeat without reconciling
        # checks or tasks. Success-only workflow callbacks keep their contract.
        try:
            _finish_scheduler_lease("nazk_registry", owner, "error", str(error))
        finally:
            heartbeat.__exit__(None, None, None)
    def completed():
        try:
            state = reference_status(DB_PATH).get("nazk", {})
            error = str(state.get("message") or "") if state.get("status") == "error" else ""
            if not error:
                rebuild_nazk_tasks("PQM NAZK job", workflow="nazk_job")
            _finish_scheduler_lease("nazk_registry", owner, "error" if error else "ok", error)
        except Exception as exc:
            _finish_scheduler_lease("nazk_registry", owner, "error", str(exc))
            SERVER_LOG.exception("Explicit NAZK workflow failed")
        finally:
            heartbeat.__exit__(None, None, None)
    try:
        heartbeat.__enter__()
        if start_reference_refresh(DB_PATH, "nazk", on_complete=completed, on_error=failed):
            return True
    except Exception:
        scheduler_runtime.release(DB_PATH, "nazk_registry", owner)
        heartbeat.__exit__(None, None, None)
        raise
    scheduler_runtime.release(DB_PATH, "nazk_registry", owner)
    heartbeat.__exit__(None, None, None)
    return False


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
        order_sql = "date_published ASC,report_id ASC" if status == "pending" else "date_published DESC,report_id DESC"
        rows = con.execute(f"""SELECT id,report_id,status,date_published,date_modified,tender_pretty_id,contract_pretty_id,
          author_name,author_code,defendant_name,defendant_code,authority_name,authority_code,reason,description,
          defendant_period_start,defendant_period_end,decision_resolution,decision_description,decision_date,
          evidence_documents_json,decision_documents_json,raw_json
          FROM violation_reports WHERE {clause} ORDER BY {order_sql} LIMIT ? OFFSET ?""",
          (*args, size, (page - 1) * size)).fetchall()
        statuses = [row[0] for row in con.execute("SELECT DISTINCT status FROM violation_reports WHERE status<>'' ORDER BY status")]
        reasons = [row[0] for row in con.execute("SELECT DISTINCT reason FROM violation_reports WHERE reason<>'' ORDER BY reason")]
        status_counts = {row[0]: row[1] for row in con.execute(
            "SELECT status,COUNT(*) FROM violation_reports GROUP BY status")}
        pending, satisfied, declined = (status_counts.get("pending", 0), status_counts.get("satisfied", 0),
                                        status_counts.get("declined", 0))
        authorities = [dict(row) for row in con.execute(f"""SELECT authority_code,authority_name,COUNT(*) count
          FROM violation_reports WHERE {authority_clause} AND authority_code<>''
          GROUP BY authority_code,authority_name ORDER BY count DESC,authority_name""", authority_args).fetchall()]
        warning_markers = operational_tasks.warning_marker_map(con)
    items = []
    for row in rows:
        item = dict(row)
        item["evidence_documents"] = json.loads(item.pop("evidence_documents_json") or "[]")
        item["decision_documents"] = json.loads(item.pop("decision_documents_json") or "[]")
        raw = json.loads(item.pop("raw_json") or "{}")
        item["defendant_statements"] = raw.get("defendantStatements") or []
        item["blocking_marker"] = warning_markers.get(item["report_id"])
        items.append(item)
    return {"items": items, "total": total, "pending": pending, "satisfied": satisfied, "declined": declined, "page": page, "size": size,
            "pages": (total + size - 1) // size, "statuses": statuses, "reasons": reasons,
            "authorities": authorities,
            "sync": dict(VIOLATION_SYNC_STATE)}


VIOLATION_REVIEW_FIELDS = {
    "review_status", "assigned_officer", "assigned_officer_id", "internal_decision", "decision_justification", "review_notes",
    "protocol_number", "protocol_date", "contract_deadline_extended",
    "written_refusal_date", "written_refusal_number", "written_refusal_url",
    "court_decision_final_present", "customer_verified_full_name",
    "customer_verified_short_name", "actual_contract_signed", "actual_contract_date", "actual_contract_number",
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
    result = {
        "calendar_day": _iso_date(calendar_day),
        "weekday": calendar_day.strftime("%A"),
        "shifted": deadline.date() != calendar_day.date(),
        "deadline": _iso_date(deadline),
    }
    return result


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
        "performance_security_required": context.get(
            "performance_security_required", context.get("contract_guarantee_required")),
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
    if (reason == "contractBreach" and decision == "decline"
            and context.get("rejection_present")
            and context.get("rejected_before_deadline") is True):
        return ("p49_1_decline_before_deadline_civil_shift"
                if context.get("day_5_shifted") else "p49_1_decline_before_deadline")
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
    if template_key in {"p49_1_decline_before_deadline", "p49_1_decline_before_deadline_civil_shift"}:
        security_required = bool(context.get(
            "performance_security_required", context.get("contract_guarantee_required")))
        paragraphs = [
            "За результатами розгляду звернення Замовника та аналізу матеріалів закупівлі Адміністратором встановлено наступне.",
            f"Повідомлення про намір укласти договір з Постачальником було оприлюднено в електронній системі закупівель {winner_date}.",
            "Відповідно до п. 66 Порядку № 822, договір про закупівлю укладається не пізніше ніж через п’ять календарних днів з дня оприлюднення в електронній системі закупівель повідомлення про намір укласти договір.",
        ]
        rejection_date = _display_legal_date(context.get("rejection_date"))
        contract_deadline = _display_legal_date(context.get("contract_deadline"))
        if template_key.endswith("civil_shift"):
            paragraphs.append(
                f"Оскільки п’ятий календарний день припадає на {_display_legal_date(context.get('day_5'))} "
                f"({context.get('day_5_weekday_uk') or 'вихідний день'}), при обрахунку строків підлягають застосуванню "
                "норми ч. 5 ст. 254 ЦК України."
            )
            paragraphs.append(
                "Таким чином, граничний строк для укладення договору, а також для вчинення супутніх дій, зокрема "
                "надання забезпечення виконання договору (якщо це передбачено умовами закупівлі), переноситься на "
                f"{context.get('contract_deadline_weekday_uk') or 'перший робочий день'} {contract_deadline}."
            )
        else:
            paragraphs.append(
                f"Граничним днем для укладення договору у цій закупівлі є {contract_deadline}."
            )
        paragraphs.append(
            f"Згідно з інформацією, наявною в електронній системі закупівель, Замовник відхилив пропозицію "
            f"Постачальника {rejection_date}, тобто до спливу граничного строку для укладення договору, встановленого "
            "Порядком № 822. З огляду на те, що на дату відхилення пропозиції визначений Порядком № 822 строк для "
            "укладення договору не закінчився, факт порушення з боку Постачальника не може бути встановлений."
        )
        if security_required:
            paragraphs.append(
                "Враховуючи, що забезпечення виконання договору надається постачальником до або під час укладення "
                "договору про закупівлю, строк для виконання цієї дії також вважається таким, що не закінчився."
            )
        paragraphs.append(
            "За таких обставин, керуючись п. 51 Порядку № 822, Адміністратор приймає рішення про відмову в "
            "задоволенні звернення Замовника, оскільки наведені факти не підтверджують наявність порушення, "
            "передбаченого пп. 1 п. 49 Порядку № 822."
        )
        return normalize_justification_text("\n".join(paragraphs))
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
        return normalize_justification_text("\n".join(paragraphs))
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
        return normalize_justification_text("\n".join(paragraphs))
    return ""


def violation_scenario_summary(report: dict, context: dict) -> str:
    """Derived officer-only acceptance hint; never persisted or sent to DOCX."""
    reason = report.get("reason")
    statements = report.get("defendant_statements") or []
    supplier_response_present = any(str(
        statement.get("description") or statement.get("title") or "").strip()
        for statement in statements)
    supplier_response = "надані" if supplier_response_present else "відсутні"

    if reason == "contractBreach":
        if context.get("rejected_before_deadline"):
            timing = "дострокове відхилення"
        elif context.get("rejection_present"):
            timing = "відхилення після закінчення строку, визначеного п. 66 Порядку № 822"
        elif context.get("contract_deadline_expired") is True:
            timing = "строк, визначений п. 66 Порядку № 822, сплив; відхилення не зафіксовано"
        elif context.get("contract_deadline_expired") is False:
            timing = "строк, визначений п. 66 Порядку № 822, ще не сплив; відхилення не зафіксовано"
        else:
            timing = "стан строку, визначеного п. 66 Порядку № 822, не визначено"
        security_value = context.get(
            "performance_security_required", context.get("contract_guarantee_required"))
        security = ("вимагається" if security_value is True else
                    "не вимагається" if security_value is False else "не визначено")
        civil = ("застосовується (перенесення граничного строку)"
                 if context.get("day_5_shifted") is True else "не застосовується")
        return (f"Сценарій: {timing}; забезпечення виконання договору — {security}; "
                f"пояснення постачальника — {supplier_response}; ЦКУ — {civil}.")

    if reason == "signingRefusal":
        review = report.get("review") or {}
        refusal_present = any(str(review.get(key) or "").strip() for key in (
            "written_refusal_date", "written_refusal_number", "written_refusal_url"))
        refusal_date_present = bool(str(review.get("written_refusal_date") or "").strip())
        within_deadline = context.get("written_refusal_within_deadline")
        # For an actual refusal, the legally relevant state is its relation to
        # the deadline — the same canonical flag used by the rules engine.
        # Current wall-clock expiry is only meaningful while no refusal exists.
        deadline_expired = ((not within_deadline)
                            if refusal_date_present and within_deadline is not None else None)
        deadline = "сплив" if deadline_expired is True else "не сплив" if deadline_expired is False else "не визначено"
        civil = ("застосовується (перенесення граничного строку)"
                 if context.get("day_3_shifted") is True else "не застосовується")
        return (f"Сценарій: пп. 2 п. 49; триденний строк — {deadline}; письмова відмова "
                f"постачальника — {'надана' if refusal_present else 'відсутня'}; пояснення "
                f"постачальника — {supplier_response}; ЦКУ — {civil}.")

    if reason == "goodsNonCompliance":
        court_value = (report.get("review") or {}).get("court_decision_final_present")
        court = "наявне" if court_value is True else "відсутнє" if court_value is False else "не визначено"
        return (f"Сценарій: пп. 3 п. 49; рішення суду, що набрало законної сили — {court}; "
                f"пояснення постачальника — {supplier_response}.")
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
    result["decision_justification"] = normalize_justification_text(
        result.get("decision_justification"))
    try:
        result["generated_protocol_metadata"] = json.loads(
            result.pop("generated_protocol_metadata_json", "{}") or "{}")
    except (TypeError, json.JSONDecodeError):
        result["generated_protocol_metadata"] = {}
    result["generated_protocol_resolved_metadata"] = document_metadata.resolved_items(
        result["generated_protocol_metadata"])
    result["contract_deadline_extended"] = bool(result.get("contract_deadline_extended"))
    if result.get("court_decision_final_present") is not None:
        result["court_decision_final_present"] = bool(result["court_decision_final_present"])
    for key in ("additional_check_required", "justification_manually_edited"):
        result[key] = bool(result.get(key))
    if result.get("guarantee_documents_visible") is not None:
        result["guarantee_documents_visible"] = bool(result["guarantee_documents_visible"])
    return result


def _reuse_customer_names(con: sqlite3.Connection, report: sqlite3.Row, review: dict | None) -> dict:
    """Fill missing manual names from the newest saved review for this customer code."""
    result = dict(review or {})
    missing = [key for key in ("customer_verified_full_name", "customer_verified_short_name")
               if not str(result.get(key) or "").strip()]
    code = re.sub(r"\D", "", str(report["author_code"] or ""))
    if not missing or not code:
        return result
    candidates = con.execute("""SELECT vr.report_id source_report_id,
          rr.customer_verified_full_name,rr.customer_verified_short_name,
          rr.updated_at,vr.date_published
        FROM violation_report_reviews rr
        JOIN violation_reports vr ON vr.id=rr.report_id
        WHERE vr.id<>? AND DIGITS(vr.author_code)=?
          AND (TRIM(COALESCE(rr.customer_verified_full_name,''))<>''
               OR TRIM(COALESCE(rr.customer_verified_short_name,''))<>'')
        ORDER BY COALESCE(NULLIF(rr.updated_at,''),vr.date_published) DESC,
                 vr.date_published DESC,vr.report_id DESC""",
        (report["id"], code)).fetchall()
    sources = {}
    for candidate in candidates:
        for key in tuple(missing):
            value = str(candidate[key] or "").strip()
            if value:
                result[key] = value
                sources[key] = candidate["source_report_id"]
                missing.remove(key)
        if not missing:
            break
    if sources:
        result["customer_name_reuse_sources"] = sources
    return result


def _resolve_violation_protocol_metadata(item: dict, values: dict) -> dict:
    """Resolve configured metadata through the shared Catalog binding engine."""
    document_type = document_metadata.VIOLATION_REVIEW_PROTOCOL
    fields = template_catalog.validate(template_catalog.load(), pqm_schema_metadata())
    index = {field["key"]: field for field in fields}
    context = {
        "report": {
            "report_id": values["report_id"],
            "tender_id": str(item.get("tender_pretty_id") or ""),
        },
        "customer": {"short_name": str((item.get("review") or {}).get("customer_verified_short_name") or "")},
        "supplier": {
            "supplier_code": values["supplier_code"],
            "document_short_name": values["supplier_short_name"] or values["supplier_name"],
        },
    }
    resolve_binding = document_bindings.resolver(context)
    def resolve(keys):
        return {key: resolve_binding(index[key]) for key in keys}
    with db() as con:
        return document_metadata.resolve_all(con, document_type, fields, resolve)


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
                    "recommendation_reason": "Пропозицію постачальника відхилено до закінчення строку, передбаченого п. 66 Порядку № 822 для укладення договору."}
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
        "contract_guarantee_required": bool(guarantee),
        "performance_security_required": bool(guarantee), "contract_guarantee_value": guarantee_value,
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
    context["contract_deadline_expired"] = (_deadline_passed(context.get("contract_deadline"))
                                             if context.get("contract_deadline") else None)
    context["written_refusal_deadline_expired"] = (_deadline_passed(day3.get("deadline"))
                                                    if day3.get("deadline") else None)
    context["day_5_weekday_uk"] = weekday_uk.get(context.get("day_5_weekday"), context.get("day_5_weekday"))
    deadline_weekday = None
    try:
        deadline_weekday = datetime.strptime(str(context.get("contract_deadline") or ""), "%Y-%m-%d").strftime("%A")
    except ValueError:
        pass
    context["contract_deadline_weekday_uk"] = weekday_uk.get(deadline_weekday, deadline_weekday)
    refusal_date = _parse_prozorro_date((review or {}).get("written_refusal_date"))
    context["written_refusal_within_deadline"] = _within_calendar_deadline(refusal_date, day3["deadline"])
    return context


def _normalized_violation_procurement_context(context: dict | None) -> dict:
    """Expose stable presentation/export aliases without mutating a frozen snapshot."""
    resolved = dict(context or {})
    resolved["cpv"] = str(resolved.get("cpv") or resolved.get("dk_code") or "").strip()
    resolved["rejection_at"] = resolved.get("rejection_at") or resolved.get("rejection_date")
    resolved["rejection_reason"] = str(
        resolved.get("rejection_reason") or resolved.get("rejection_title")
        or resolved.get("rejection_description") or ""
    ).strip()
    return resolved


def resolve_violation_procurement_context(
    item: dict, review: dict | None = None, *, prefer_snapshot: bool = True,
) -> tuple[dict, str]:
    """Resolve one report's frozen decision or current factual procurement context."""
    if prefer_snapshot:
        snapshot = item.get("decision_context_snapshot") or {}
        frozen = snapshot.get("procurement_context") if isinstance(snapshot, dict) else None
        if frozen:
            return _normalized_violation_procurement_context(frozen), "completion_snapshot"
    try:
        resolved = build_procurement_context(item, review or {})
        return _normalized_violation_procurement_context(resolved), "case_scoped_resolver"
    except Exception as exc:
        SERVER_LOG.warning(
            "violation_context_unavailable report=%s error=%s",
            item.get("report_id") or item.get("id"), type(exc).__name__,
        )
        return {"available": False, "error": str(exc), "cpv": "",
                "rejection_at": None, "rejection_reason": ""}, "unavailable"


def _violation_sheets_json_eligible(review: dict | None) -> bool:
    review = review or {}
    return bool(
        review.get("review_status") in {"reviewed", "completed"}
        and str(review.get("internal_decision") or "").strip()
    )


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
        effective_review = _reuse_customer_names(con, row, _review_dict(review_row))
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
        effective_review)
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
    snapshot_event = next((event for event in events
                           if event.get("event_type") == "decision_context_snapshotted"
                           and event.get("field_name") == "decision_context_snapshot"), None)
    try:
        item["decision_context_snapshot"] = json.loads((snapshot_event or {}).get("new_value") or "null")
    except (TypeError, ValueError):
        item["decision_context_snapshot"] = None
    item["read_only_reason"] = (
        "official_decision" if item["has_official_decision"] else
        "local_completion" if item["local_review_completed"] else
        "foreign_authority" if item["foreign_authority_read_only"] else ""
    )
    # A completed LOCAL review keeps its immutable decision context even when a
    # later Prozorro sync adds the authoritative decisions[] state.  The two
    # states are presented separately; the official decision must not erase
    # the officer's saved CPV/DK, recommendation or justification inputs.
    if item["is_read_only"] and item["decision_context_snapshot"]:
        snapshot = item["decision_context_snapshot"] or {}
        item["procurement_context"], item["decision_context_source"] = (
            resolve_violation_procurement_context(item, item["review"])
        )
        item["recommendation"] = snapshot.get("recommendation")
        if not item["recommendation"]:
            recommendation_context = dict(item["procurement_context"] or {})
            recommendation_context["supplier_deadline_ready"] = bool(item["deadline_control"].get("supplier_ready"))
            recommendation_context["defendant_statements_present"] = bool(item["defendant_statements"])
            item["recommendation"] = violation_rules_engine(item["reason"], recommendation_context, item["review"])
        item["justification_draft"] = ""
        item["justification_template_key"] = str(item["review"].get("decision_template_key") or "")
        item["justification_generation_ready"] = False
        item["justification_stale"] = False
        item["protocol_readiness"] = {"ready": False, "reasons": ["Розгляд доступний лише для перегляду"]}
    elif item["is_read_only"] and _violation_sheets_json_eligible(item["review"]):
        # Legacy reviewed cases may predate decision-context snapshots. Resolve
        # only this report, read-only, through the same backend path used by
        # its case-scoped JSON export.
        item["procurement_context"], item["decision_context_source"] = (
            resolve_violation_procurement_context(item, item["review"])
        )
        recommendation_context = dict(item["procurement_context"] or {})
        recommendation_context["supplier_deadline_ready"] = bool(item["deadline_control"].get("supplier_ready"))
        recommendation_context["defendant_statements_present"] = bool(item["defendant_statements"])
        item["recommendation"] = violation_rules_engine(
            item["reason"], recommendation_context, item["review"])
        item["justification_draft"] = ""
        item["justification_template_key"] = str(item["review"].get("decision_template_key") or "")
        item["justification_generation_ready"] = False
        item["justification_stale"] = False
        item["protocol_readiness"] = {"ready": False, "reasons": ["Розгляд доступний лише для перегляду"]}
    elif not item["is_read_only"]:
        item["procurement_context"], item["decision_context_source"] = (
            resolve_violation_procurement_context(item, item["review"])
        )
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
    # The upper procurement card is factual, not a decision/review artefact.
    # It therefore resolves for every report, including official historical
    # reports which have never been reviewed in PQM and are not JSON-eligible.
    # Keep this separate from the immutable decision context used below.
    if item.get("procurement_context"):
        item["factual_procurement_context"] = item["procurement_context"]
        item["factual_procurement_context_source"] = item.get("decision_context_source") or "resolved_context"
    else:
        (item["factual_procurement_context"],
         item["factual_procurement_context_source"]) = resolve_violation_procurement_context(
            item, item["review"], prefer_snapshot=False)
    item["scenario_summary"] = violation_scenario_summary(
        item, item.get("procurement_context") or {})
    # JSON export follows the canonical status presented by the case card, not
    # only the historical LOCAL completion marker.  An official Prozorro
    # decision projects the review as ``completed`` even when the older local
    # row still says ``in_review``; rewriting that historical row is neither
    # required nor desirable.
    item["sheets_json_available"] = _violation_sheets_json_eligible(item["review"])
    return item


VIOLATION_SHEETS_DECISION_LABELS = {
    "warning": "Попередження",
    "decline": "Відмова в задоволенні звернення",
    "individual_review": "Індивідуальний розгляд",
}


def _violation_sheets_date(value) -> str:
    """Format one factual case date for the manual Google Sheets JSON contract."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", raw):
        return raw
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return datetime.strptime(raw, "%Y-%m-%d").strftime("%d.%m.%Y")
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=scheduler_runtime.KYIV)
    else:
        moment = moment.astimezone(scheduler_runtime.KYIV)
    return moment.strftime("%d.%m.%Y")


def violation_protocol_output_name(report_id: str, protocol_number: str,
                                   internal_decision: str) -> str:
    """Return the existing business filename stem shared by PDF and sheet export."""
    suffix = "П" if str(internal_decision or "") == "warning" else "В"
    pretty_report = safe_archive_name(str(report_id or ""), "report")
    number = safe_archive_name(str(protocol_number or "без номера"), "без номера")
    return f"{pretty_report}_{number}_{suffix}"


def violation_report_sheets_json(report_id: str) -> dict:
    """Build one sparse, case-scoped JSON object for manual Sheets transfer."""
    item = violation_report_detail(report_id, refresh=False)
    review = item.get("review") or {}
    if not item.get("sheets_json_available"):
        raise PermissionError(
            "JSON доступний зі стадії «Розглянуто», коли збережено рішення УО"
        )

    # ``violation_report_detail`` resolves this once through the shared
    # snapshot/case-scoped resolver. Export never has a second projection path.
    context = item.get("procurement_context") or {}

    supplier = item.get("supplier_verified") or {}
    reason_metadata = VIOLATION_REASON_PROTOCOL_METADATA.get(item.get("reason"), {})
    protocol_number = str(review.get("protocol_number") or "").strip()
    factual = {
        "report_id": str(item.get("report_id") or "").strip(),
        "received_at": _violation_sheets_date(item.get("date_published")),
        "cpv": str(context.get("cpv") or "").strip(),
        "tender_id": str(item.get("tender_pretty_id") or context.get("tender_pretty_id") or "").strip(),
        "customer_name": str(review.get("customer_verified_full_name") or item.get("author_name") or "").strip(),
        "customer_code": str(item.get("author_code") or "").strip(),
        "supplier_name": str(supplier.get("full_name") or item.get("defendant_name") or "").strip(),
        "supplier_code": str(item.get("defendant_code") or "").strip(),
        "description": str(item.get("description") or "").strip(),
        "winner_selected_at": _violation_sheets_date(context.get("winner_selected_at")),
        "rejection_at": _violation_sheets_date(context.get("rejection_at")),
        "contract_date": (_violation_sheets_date(review.get("actual_contract_date"))
                          if review.get("actual_contract_signed") else ""),
        "contract_number": (str(review.get("actual_contract_number") or "").strip()
                            if review.get("actual_contract_signed") else ""),
        "rejection_reason": str(context.get("rejection_reason") or "").strip(),
        "uo_decision": VIOLATION_SHEETS_DECISION_LABELS.get(
            str(review.get("internal_decision") or ""), ""),
        "written_refusal_at": _violation_sheets_date(review.get("written_refusal_date")),
        "protocol_number": protocol_number,
        "protocol_date": _violation_sheets_date(review.get("protocol_date")),
        "output_name": (violation_protocol_output_name(
            item.get("report_id") or item.get("id"), protocol_number,
            review.get("internal_decision")) if protocol_number else ""),
        "customer_short_name": str(review.get("customer_verified_short_name") or "").strip(),
        "supplier_short_name": str(supplier.get("short_name") or "").strip(),
        "violation_type": str(item.get("reason") or "").strip(),
        "legal_basis_short": (f"пп. {reason_metadata['number']} п. 49"
                              if reason_metadata.get("number") else ""),
        "responsible_officer": str(review.get("assigned_officer_display")
                                   or review.get("assigned_officer") or "").strip(),
    }
    return {key: value for key, value in factual.items()
            if value is not None and (not isinstance(value, str) or value.strip())}


def save_violation_document_review(report_id: str, source: str, document_id: str,
                                   file_unavailable: bool, checked_by: str = "УО") -> dict:
    if source not in {"customer", "supplier"}:
        raise ValueError("Невідоме джерело документа")
    with db() as con:
        report = con.execute("SELECT * FROM violation_reports WHERE id=? OR report_id=?", (report_id, report_id)).fetchone()
        if not report:
            raise KeyError(report_id)
        completed = con.execute("SELECT completed_at FROM violation_report_reviews WHERE report_id=?", (report["id"],)).fetchone()
        if completed and completed["completed_at"]:
            raise PermissionError("Локальний розгляд уже завершено. Зміни в режимі перегляду не зберігаються.")
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
        if existing.get("completed_at"):
            raise PermissionError("Локальний розгляд уже завершено. Повторне відкриття або зміна завершеного review заборонені.")
        values = {key: payload[key] for key in VIOLATION_REVIEW_FIELDS if key in payload}
        if "decision_justification" in values:
            values["decision_justification"] = normalize_justification_text(
                values["decision_justification"])
        if values.get("review_status", "") not in {"", "not_reviewed", "in_review", "reviewed"}:
            raise ValueError("Невідомий статус розгляду")
        if values.get("internal_decision", "") not in VIOLATION_INTERNAL_DECISIONS:
            raise ValueError("Невідоме внутрішнє рішення УО")
        for key in ("contract_deadline_extended", "additional_check_required", "actual_contract_signed"):
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
        elif ("decision_justification" in values and
              values["decision_justification"] != normalize_justification_text(
                  existing.get("decision_justification", ""))):
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


VIOLATION_REASON_PROTOCOL_METADATA = {
    "contractBreach": {
        "number": "1",
        "label": ("Підпункт 1 пункту 49 Постанови Кабінету Міністрів України від 14.09.2020 № 822 "
                  "«Про затвердження Порядку формування та використання електронного каталогу»"),
        "text": ("Не підписав договір на умовах, визначених замовником у запиті пропозицій постачальників "
                 "шляхом заповнення електронних форм із окремими полями та у проекті договору, що є "
                 "складовою частиною запиту пропозицій постачальників, та/або не надав забезпечення "
                 "виконання договору у строк, визначений пунктом 66 цього Порядку"),
    },
    "signingRefusal": {
        "number": "2",
        "label": ("Підпункт 2 пункту 49 Постанови Кабінету Міністрів України від 14.09.2020 № 822 "
                  "«Про затвердження Порядку формування та використання електронного каталогу»"),
        "text": ("Письмово відмовився від укладення договору на умовах, визначених замовником у запиті "
                 "пропозицій постачальників шляхом заповнення електронних форм із окремими полями та у "
                 "проекті договору, що є складовою частиною запиту пропозицій постачальників, після спливу "
                 "трьох календарних днів з дня оприлюднення в електронній системі закупівель повідомлення "
                 "про намір укласти договір"),
    },
    "goodsNonCompliance": {
        "number": "3",
        "label": ("Підпункт 3 пункту 49 Постанови Кабінету Міністрів України від 14.09.2020 № 822 "
                  "«Про затвердження Порядку формування та використання електронного каталогу»"),
        "text": ("Не виконав свої зобов’язання за раніше укладеним договором, із цим самим замовником, що "
                 "призвело до його дострокового розірвання, і було застосовано санкції у вигляді штрафів "
                 "та/або відшкодування збитків протягом трьох років з дати дострокового розірвання такого "
                 "договору, що підтверджується рішенням суду, що набрало законної сили."),
    },
}


def violation_has_complete_rejection(context: dict | None) -> bool:
    context = context or {}
    reason = str(context.get("rejection_reason") or context.get("rejection_title") or
                 context.get("rejection_description") or "").strip()
    return bool(context.get("rejection_date") and reason)


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
    rejected = violation_has_complete_rejection(context)
    if not context.get("available"):
        reasons.append("Не отримано актуальні відомості закупівлі")
    if item.get("reason") in {"contractBreach", "signingRefusal"} and not context.get("winner_selected_at"):
        reasons.append("Не визначено дату визначення переможцем")
    if item.get("reason") == "signingRefusal":
        missing_refusal = []
        if not str(review.get("written_refusal_date") or "").strip():
            missing_refusal.append("Дата письмової відмови")
        if not str(review.get("written_refusal_number") or "").strip():
            missing_refusal.append("Вихідний номер письмової відмови")
        if not str(review.get("written_refusal_url") or "").strip():
            missing_refusal.append("Документ письмової відмови")
        if missing_refusal:
            reasons.append("Не заповнено обов’язкові поля: " + ", ".join(missing_refusal))
    contract_required = violation_protocol_type(item, review) == "decline_p49_3" and not rejected
    if contract_required and not review.get("actual_contract_signed"):
        reasons.append("Не підтверджено ручне поле «Договір укладено»")
    if review.get("actual_contract_signed") and not rejected:
        missing_contract = []
        if not str(review.get("actual_contract_number") or "").strip():
            missing_contract.append("Номер договору")
        if not str(review.get("actual_contract_date") or "").strip():
            missing_contract.append("Дата договору")
        if missing_contract:
            reasons.append("Не заповнено обов’язкові поля: " + ", ".join(missing_contract))
    declensions=violation_protocol_declensions(item)
    unresolved=[entry for entry in declensions if entry['status']!='resolved']
    if unresolved:reasons.append('Потрібні перевірені відмінкові форми')
    return {"ready": not reasons, "reasons": reasons, "protocol_type": violation_protocol_type(item, review),
            "protocol_number": number, "protocol_date": date,
            "declensions":declensions,"unresolved":unresolved}


def violation_protocol_declensions(item: dict) -> list[dict]:
    """Expose the same template-dependent forms for review before generation."""
    protocol_type=violation_protocol_type(item,item.get('review') or {})
    path=TEMPLATES.get(protocol_type)
    if not path or not Path(path).is_file():return []
    tokens=set()
    with zipfile.ZipFile(path) as package:
        for name in package.namelist():
            if name.startswith('word/') and name.endswith('.xml'):
                root=ET.fromstring(package.read(name))
                word='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                for paragraph in root.iter(word+'p'):
                    text=''.join(node.text or '' for node in paragraph.iter(word+'t'))
                    tokens.update(re.findall(r'\{\{\s*([a-z_]+)\s*\}\}',text))
    customer=normalize_document_name((item.get('review') or {}).get('customer_verified_full_name') or item.get('author_name') or '')
    supplier=normalize_document_name((item.get('supplier_verified') or {}).get('full_name') or item.get('defendant_name') or '')
    specs={'customer_name_genitive':(customer,infer_entity_type(customer,item.get('author_code')),'genitive','Замовник'),
           'customer_name_accusative':(customer,infer_entity_type(customer,item.get('author_code')),'accusative','Замовник'),
           'supplier_name_genitive':(supplier,infer_entity_type(supplier,item.get('defendant_code')),'genitive','Постачальник'),
           'supplier_name_dative':(supplier,infer_entity_type(supplier,item.get('defendant_code')),'dative','Постачальник'),
           'supplier_name_accusative':(supplier,infer_entity_type(supplier,item.get('defendant_code')),'accusative','Постачальник')}
    result=[]
    for token,(original,entity_type,grammatical_case,label) in specs.items():
        if token not in tokens:continue
        resolved=decline_name(original,entity_type,grammatical_case)
        result.append({'subject_label':label,'original':original,'entity_type':entity_type,
          'grammatical_case':grammatical_case,'entity_identifier':item.get('author_code') if label=='Замовник' else item.get('defendant_code'),
          'report_id':item.get('id'),'context_type':'violation_report','status':resolved.status,
          'source':resolved.source,'resolved_value':resolved.value})
    return result


def _protocol_date(value) -> str:
    raw = str(value or "")[:10]
    return ".".join(reversed(raw.split("-"))) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) else raw


def _protocol_officer_name(value: str) -> str:
    """Render stored `FIRST LAST` officer names as `Ім'я ПРІЗВИЩЕ`."""
    parts = str(value or "").strip().split()
    if len(parts) < 2:
        return str(value or "").strip()
    return " ".join([part.title() for part in parts[:-1]] + [parts[-1].upper()])


def merged_review_requires_discrepancy(report: dict, review: dict) -> bool:
    """Require a discrepancy only when the UO explicitly uses that factual scenario."""
    if str(review.get("internal_decision") or "") != "decline":
        return False
    return bool(review.get("additional_check_required") or str(review.get("established_discrepancy") or "").strip())


def violation_decision_context_snapshot(item: dict, review: dict, captured_at: str) -> dict:
    """Freeze the derived facts used for the completed local decision."""
    context = item.get("procurement_context") or {}
    recommendation = item.get("recommendation") or {}
    return {
        "version": 1,
        "captured_at": captured_at,
        "report_id": item.get("report_id") or item.get("id"),
        "reason": item.get("reason"),
        "prozorro_status_at_completion": item.get("status"),
        "procurement_context": context,
        "recommendation": recommendation,
        "deadline_control": item.get("deadline_control") or {},
        "justification_basis": _justification_basis(item, context, review),
        "decision": {
            "internal_decision": review.get("internal_decision"),
            "decision_template_key": review.get("decision_template_key"),
            "justification_source_hash": review.get("justification_source_hash"),
        },
    }


def complete_violation_review(report_id: str, completed_by: str, payload: dict | None = None) -> dict:
    """Atomically save the current form, snapshot derived facts and complete the review."""
    require_local_violation_report_owned(report_id)
    item = violation_report_detail(report_id, refresh=True)
    require_owned_violation_report(item)
    if item.get("has_official_decision"):
        raise PermissionError("У Prozorro вже є офіційне рішення адміністратора. Картка доступна лише для перегляду.")
    deadline = item.get("deadline_control") or {}
    if not deadline.get("supplier_ready"):
        raise ValueError("Завершення розгляду недоступне до завершення офіційного строку постачальника")
    now = now_iso()
    with db() as con:
        report = con.execute("SELECT id FROM violation_reports WHERE id=? OR report_id=?", (report_id, report_id)).fetchone()
        if not report:
            raise KeyError(report_id)
        current = con.execute("SELECT * FROM violation_report_reviews WHERE report_id=?", (report["id"],)).fetchone()
        if not current:
            raise ValueError("Робочу картку звернення не знайдено")
        if current["completed_at"]:
            return {"review_status": "reviewed", "completed_at": current["completed_at"],
                    "completed_by": current["completed_by"], "already_completed": True}
        baseline = dict(current)
        values = {key: payload[key] for key in VIOLATION_REVIEW_FIELDS if payload and key in payload}
        if "decision_justification" in values:
            values["decision_justification"] = normalize_justification_text(
                values["decision_justification"])
        if values.get("review_status", "") not in {"", "not_reviewed", "in_review"}:
            raise ValueError("Статус «Розглянуто» встановлюється лише дією «Завершити розгляд»")
        if values.get("internal_decision", "") not in VIOLATION_INTERNAL_DECISIONS:
            raise ValueError("Невідоме внутрішнє рішення УО")
        for key in ("contract_deadline_extended", "additional_check_required", "actual_contract_signed"):
            if key in values:
                values[key] = int(bool(values[key]))
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
            values["assigned_officer"] = officer["full_name"] if officer else baseline.get("assigned_officer", "")
        if ("decision_justification" in values and
                values["decision_justification"] != normalize_justification_text(
                    baseline.get("decision_justification", ""))):
            values["justification_manually_edited"] = 1
        merged = {**baseline, **values, "review_status": "reviewed"}
    if not merged.get("internal_decision"):
        raise ValueError("Для завершення розгляду оберіть рішення УО")
    if merged_review_requires_discrepancy(item, merged) and not str(merged.get("established_discrepancy") or "").strip():
        raise ValueError("Для обраного сценарію зафіксуйте встановлену невідповідність")
    try:
        context = build_procurement_context(item, merged)
    except Exception as exc:
        raise ConnectionError(f"Не вдалося зафіксувати контекст рішення: {exc}") from exc
    recommendation_context = dict(context)
    recommendation_context["supplier_deadline_ready"] = bool(deadline.get("supplier_ready"))
    recommendation_context["defendant_statements_present"] = bool(item.get("defendant_statements"))
    item["procurement_context"] = context
    item["recommendation"] = violation_rules_engine(item.get("reason", ""), recommendation_context, merged)
    snapshot_json = json.dumps(violation_decision_context_snapshot(item, merged, now),
                               ensure_ascii=False, sort_keys=True, default=str)
    with db() as con:
        report = con.execute("SELECT id FROM violation_reports WHERE id=? OR report_id=?", (report_id, report_id)).fetchone()
        if not report:
            raise KeyError(report_id)
        current = con.execute("SELECT * FROM violation_report_reviews WHERE report_id=?", (report["id"],)).fetchone()
        if not current:
            raise ValueError("Робочу картку звернення не знайдено")
        if current["completed_at"]:
            return {"review_status": "reviewed", "completed_at": current["completed_at"], "completed_by": current["completed_by"], "already_completed": True}
        if current["updated_at"] != baseline.get("updated_at"):
            raise RuntimeError("Review змінився під час завершення. Оновіть картку та повторіть дію.")
        if values:
            assignments = ",".join(f"{key}=?" for key in values)
            con.execute(f"UPDATE violation_report_reviews SET {assignments} WHERE report_id=?",
                        (*values.values(), report["id"]))
            for key, value in values.items():
                old = baseline.get(key)
                if old != value:
                    con.execute("""INSERT INTO violation_report_review_events
                      (report_id,event_type,field_name,old_value,new_value,changed_at,changed_by)
                      VALUES (?,?,?,?,?,?,?)""", (report["id"], "review_updated", key,
                      None if old is None else str(old), None if value is None else str(value), now, completed_by))
        con.execute("""INSERT INTO violation_report_review_events
          (report_id,event_type,field_name,old_value,new_value,changed_at,changed_by)
          VALUES (?,?,?,?,?,?,?)""", (report["id"], "decision_context_snapshotted",
          "decision_context_snapshot", None, snapshot_json, now, completed_by))
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
                                  for statement in statements
                                  if str(statement.get("description") or statement.get("title") or "").strip()).strip()
    reason_metadata = VIOLATION_REASON_PROTOCOL_METADATA.get(item.get("reason"), {})
    reason_number = reason_metadata.get("number", "")
    customer_name = normalize_document_name(
        review.get("customer_verified_full_name") or item.get("author_name") or "")
    supplier_name = normalize_document_name(
        (item.get("supplier_verified") or {}).get("full_name") or item.get("defendant_name") or "")
    supplier_short_name = normalize_document_name(
        (item.get("supplier_verified") or {}).get("short_name") or supplier_name)
    supplier_code = str(item.get("defendant_code") or "").strip()
    customer_code = str(item.get("author_code") or "").strip()
    customer_entity_type = infer_entity_type(customer_name, customer_code)
    supplier_entity_type = infer_entity_type(supplier_name, supplier_code)
    declined_names = {
        "customer_name_genitive": decline_name(customer_name, customer_entity_type, "genitive"),
        "customer_name_accusative": decline_name(customer_name, customer_entity_type, "accusative"),
        "supplier_name_genitive": decline_name(supplier_name, supplier_entity_type, "genitive"),
        "supplier_name_dative": decline_name(supplier_name, supplier_entity_type, "dative"),
        "supplier_name_accusative": decline_name(supplier_name, supplier_entity_type, "accusative"),
    }
    for token, result in declined_names.items():
        log = SERVER_LOG.warning if result.status == "unresolved" else SERVER_LOG.info
        log("violation_protocol_declension token=%s entity_type=%s source=%s status=%s original=%r",
            token, result.entity_type, result.source, result.status, result.original)
    rejected = violation_has_complete_rejection(context)
    values = {
        "protocol_number": gate["protocol_number"], "protocol_date": _protocol_date(gate["protocol_date"]),
        "report_id": str(item.get("report_id") or item.get("id") or ""),
        "procurement_id": str(item.get("tender_pretty_id") or ""),
        "procurement_date": _protocol_date(context.get("tender_date_published") or item.get("date_created")),
        "cpv_category": str(context.get("dk_code") or ""),
        "customer_name": customer_name, "customer_name_genitive": normalize_document_name(declined_names["customer_name_genitive"].value),
        "customer_name_accusative": normalize_document_name(declined_names["customer_name_accusative"].value), "customer_code": customer_code,
        "supplier_name": supplier_name, "supplier_short_name": supplier_short_name,
        "supplier_name_genitive": normalize_document_name(declined_names["supplier_name_genitive"].value),
        "supplier_name_dative": normalize_document_name(declined_names["supplier_name_dative"].value),
        "supplier_name_accusative": normalize_document_name(declined_names["supplier_name_accusative"].value), "supplier_code": supplier_code,
        "supplier_code_label": supplier_code_label(supplier_code),
        "officer_name": _protocol_officer_name(str(review.get("assigned_officer") or CURRENT_USER)),
        "p49_reference": f"пп. {reason_number} п. 49" if reason_number else "",
        "reason_label": reason_metadata.get("label", ""),
        "reason_text": reason_metadata.get("text", ""),
        "violation_description": str(item.get("description") or ""),
        "winner_date": _protocol_date(context.get("winner_selected_at")),
        "supplier_deadline": _protocol_date((item.get("deadline_control") or {}).get("supplier_deadline")),
        "contract_deadline": _protocol_date(context.get("contract_deadline")),
        "rejection_date": _protocol_date(context.get("rejection_date")),
        "rejection_reason": str(context.get("rejection_title") or context.get("rejection_description") or ""),
        "refusal_date": _protocol_date(review.get("written_refusal_date")),
        "refusal_outgoing_number": str(review.get("written_refusal_number") or ""),
        "refusal_document": str(review.get("written_refusal_url") or ""),
        "supplier_response": supplier_text,
        "contract_date": "" if rejected else _protocol_date(review.get("actual_contract_date")),
        "contract_number": "" if rejected else str(review.get("actual_contract_number") or ""),
        "decision_justification": normalize_justification_text(
            review.get("decision_justification")),
    }
    protocol_metadata = _resolve_violation_protocol_metadata(item, values)
    flags = {
        "has_written_refusal": bool(review.get("written_refusal_date") or review.get("written_refusal_number") or review.get("written_refusal_url")),
        "has_contract": bool(review.get("actual_contract_signed")) and not rejected,
        "has_contract_security": bool(context.get("contract_guarantee_required")),
        "has_civil_code_basis": bool(
            context.get("day_5_shifted") if item.get("reason") == "contractBreach"
            else context.get("day_3_shifted") if item.get("reason") == "signingRefusal"
            else False),
        "has_court_decision": item.get("reason") == "goodsNonCompliance",
        "has_customer_documents": bool(item.get("evidence_documents")),
        "has_supplier_response": bool(supplier_text),
        "has_supplier_documents": bool(supplier_documents),
    }
    safe_report = safe_archive_name(str(item.get("report_id") or item.get("id")), "report")
    decision_name = "Попередження" if gate["protocol_type"] == "warning" else "Відмова"
    safe_customer = safe_archive_name(customer_name, "Замовник")[:48]
    safe_supplier = safe_archive_name(supplier_name, "Постачальник")[:48]
    safe_date = str(gate["protocol_date"] or "").replace(".", "-")
    filename = f"{safe_report}_{decision_name}_{safe_customer}_{safe_supplier}_{safe_date}.docx"
    PROTOCOLS_DIR.mkdir(parents=True, exist_ok=True)
    output = PROTOCOLS_DIR / filename
    # Regeneration can happen while the current file is open in desktop Word.
    # Windows locks that path and rejects os.replace(). Publish a new physical
    # version instead; the DB pointer changes only after the new DOCX exists.
    if output.exists():
        output = output.with_name(f"{output.stem}__{uuid.uuid4().hex[:8]}{output.suffix}")
        filename = output.name
    temporary = PROTOCOLS_DIR / f".{safe_report}.{uuid.uuid4().hex}.tmp.docx"
    renderer_module = Path(sys.modules[build_violation_protocol_docx.__module__].__file__).resolve()
    SERVER_LOG.info(
        "violation_protocol_generate endpoint=/api/violation-reports/%s/protocol/generate "
        "renderer=%s module=%s template=%s reason=%s customer_documents=%d structured_renderer=1",
        safe_report, getattr(build_violation_protocol_docx, "__name__", type(build_violation_protocol_docx).__name__), renderer_module,
        Path(TEMPLATES[gate["protocol_type"]]).resolve(), reason_metadata.get("label", ""),
        len(item.get("evidence_documents") or []),
    )
    try:
        build_violation_protocol_docx(gate["protocol_type"], temporary, values,
            normalize_justification_text(review.get("decision_justification")),
            item.get("evidence_documents") or [], supplier_documents,
            flags)
        if not temporary.is_file():
            raise RuntimeError("Генератор не створив DOCX")
        os.replace(temporary, output)
    except ProtocolContextValidationError as exc:
        temporary.unlink(missing_ok=True)
        unresolved = unresolved_declension_items(exc.missing, declined_names, item)
        if unresolved:
            try:
                ensure_pending_overrides(unresolved)
            except Exception:
                SERVER_LOG.exception("declension_pending_autosave_failed report_id=%s", safe_report)
            raise DeclensionValidationError(unresolved) from exc
        raise
    except PermissionError as exc:
        temporary.unlink(missing_ok=True)
        raise ValueError("Не вдалося зберегти нову версію протоколу: перевірте доступ до папки документів.") from exc
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
                       SET protocol_number=?,protocol_date=?,generated_protocol_filename=?,generated_protocol_metadata_json=?,protocol_generated_at=?,updated_at=?,updated_by=?
                       WHERE report_id=?""",
                    (gate["protocol_number"], gate["protocol_date"], filename,
                     json.dumps(protocol_metadata, ensure_ascii=False), now, now, generated_by, report["id"]))
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
            "pdf_download_url": f"/api/violation-reports/{urllib.parse.quote(str(item['id']))}/protocol/pdf",
            "metadata": protocol_metadata,
            "resolved_metadata": document_metadata.resolved_items(protocol_metadata),
            "review_status": review.get("review_status") or "in_review"}


def violation_protocol_pdf(report_id: str) -> tuple[Path, str]:
    """Resolve the current generated protocol and export its cached PDF copy."""
    with db() as con:
        row = con.execute("""SELECT v.id,v.report_id,r.internal_decision,r.protocol_number,
          r.generated_protocol_filename FROM violation_reports v
          JOIN violation_report_reviews r ON r.report_id=v.id
          WHERE v.id=? OR v.report_id=?""", (report_id, report_id)).fetchone()
    if not row or not str(row["generated_protocol_filename"] or "").strip():
        raise FileNotFoundError("Сформований протокол не знайдено")
    protocols_root = PROTOCOLS_DIR.resolve()
    source = (protocols_root / Path(row["generated_protocol_filename"]).name).resolve()
    if protocols_root not in source.parents or not source.is_file():
        raise FileNotFoundError("DOCX протоколу не знайдено")
    filename = violation_protocol_output_name(
        row["report_id"] or row["id"], row["protocol_number"], row["internal_decision"]
    ) + ".pdf"
    output = protocols_root / "_pdf" / filename
    return protocol_pdf.ensure_pdf(source, output), filename


def safe_archive_name(value: str, fallback: str) -> str:
    name = (value or fallback).strip().replace("\\", "_").replace("/", "_")
    name = "".join("_" if char in '<>:"|?*' or ord(char) < 32 else char for char in name)
    return name[:180] or fallback


def application_documents(submission_id: str) -> tuple[str, list[tuple[str, dict]]] | None:
    with db() as con:
        row = con.execute("""SELECT s.supplier_name, s.documents_json,
          q.documents_json qualification_documents,q.status qualification_status,
          (SELECT rc.status FROM registry_contracts rc
           WHERE rc.qualification_id=q.id ORDER BY rc.synced_at DESC LIMIT 1) registry_status,
          (SELECT rc.milestones_json FROM registry_contracts rc
           WHERE rc.qualification_id=q.id ORDER BY rc.synced_at DESC LIMIT 1) registry_milestones
          FROM submissions s
          LEFT JOIN (SELECT id,submission_id,ROW_NUMBER() OVER (PARTITION BY submission_id ORDER BY
            CASE status WHEN 'active' THEN 3 WHEN 'unsuccessful' THEN 2 ELSE 1 END DESC,
            COALESCE(NULLIF(decision_date,''),synced_at) DESC,id DESC) rn FROM qualifications
            WHERE COALESCE(submission_id,'')<>'') final_q ON final_q.submission_id=s.id AND final_q.rn=1
          LEFT JOIN qualifications q ON q.id=COALESCE(final_q.id,s.qualification_id)
          WHERE s.id=?""", (submission_id,)).fetchone()
    if not row:
        return None
    groups = grouped_application_documents(row["documents_json"], row["qualification_documents"],
                                           row["registry_milestones"], row["qualification_status"],
                                           row["registry_status"])
    documents = [(folder, document) for key, folder in (("supplier", "01-документи-постачальника"),
                 ("decision", "02-документи-розгляду"), ("registry", "03-документи-реєстру"))
                 for document in groups[key]]
    return row["supplier_name"] or submission_id, documents


def _download_archive_document(document: dict, opener=urllib.request.urlopen, sleeper=time.sleep,
                               max_attempts: int = 5, base_delay: float = 2.0) -> tuple[bytes, int]:
    """Download one archive member, retrying only HTTP 429 for this document."""
    request = urllib.request.Request(document["url"], headers={"User-Agent": "PQM/0.1"})
    for attempt in range(1, max_attempts + 1):
        try:
            with opener(request, timeout=60, context=ssl.create_default_context()) as response:
                return response.read(), attempt
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt >= max_attempts:
                raise
            retry_after = str((exc.headers or {}).get("Retry-After") or "").strip()
            try:
                server_delay = max(0.0, float(retry_after))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    server_delay = max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    server_delay = 0.0
            sleeper(max(base_delay * (2 ** (attempt - 1)), server_delay))
    raise RuntimeError("Не вдалося завантажити документ")


def build_application_archive(submission_id: str, opener=urllib.request.urlopen, sleeper=time.sleep):
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
                content, attempts = _download_archive_document(document, opener=opener, sleeper=sleeper)
                bundle.writestr(entry_name, content)
                record.update(status="downloaded", attempts=attempts)
            except Exception as exc:
                record.update(status="error", error=str(exc),
                              attempts=5 if isinstance(exc, urllib.error.HTTPError) and exc.code == 429 else 1)
            manifest.append(record)
        failed = [record for record in manifest if record["status"] == "error"]
        if failed:
            bundle.writestr("ПОМИЛКИ_ЗАВАНТАЖЕННЯ.txt", "\n".join(
                f"- {record['title'] or record['file']}: {record['error']}" for record in failed
            ))
        bundle.writestr("manifest.json", json.dumps({
            "submission_id": submission_id,
            "supplier_name": supplier_name,
            "created_at": now_iso(),
            "documents": manifest,
        }, ensure_ascii=False, indent=2))
    archive.seek(0, os.SEEK_END)
    size = archive.tell()
    archive.seek(0)
    return archive, size, failed


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


def _contract_experience_http_json(url: str, payload: dict | None = None) -> dict:
    global CONTRACT_EXPERIENCE_LAST_REQUEST
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"User-Agent": "PQM/0.1", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    for attempt in range(1, CONTRACT_EXPERIENCE_HTTP_ATTEMPTS + 1):
        wait = CONTRACT_EXPERIENCE_REQUEST_INTERVAL - (time.monotonic() - CONTRACT_EXPERIENCE_LAST_REQUEST)
        if wait > 0:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(request, timeout=30, context=ssl.create_default_context()) as response:
                result = json.loads(response.read().decode("utf-8"))
            if not isinstance(result, dict):
                raise ValueError("Prozorro повернув некоректну відповідь пошуку договорів")
            return result
        except urllib.error.HTTPError as exc:
            transient = exc.code == 429 or 500 <= exc.code < 600
            SERVER_LOG.warning(
                "Contract experience HTTP error endpoint=%s status=%s attempt=%s type=%s",
                url, exc.code, attempt, type(exc).__name__,
            )
            if not transient or attempt >= CONTRACT_EXPERIENCE_HTTP_ATTEMPTS:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = float(retry_after) if retry_after is not None else CONTRACT_EXPERIENCE_HTTP_BACKOFF[attempt - 1]
            except (TypeError, ValueError):
                delay = CONTRACT_EXPERIENCE_HTTP_BACKOFF[attempt - 1]
            time.sleep(max(0.0, delay))
        except (urllib.error.URLError, TimeoutError, ConnectionError, socket.timeout) as exc:
            SERVER_LOG.warning(
                "Contract experience network error endpoint=%s attempt=%s type=%s",
                url, attempt, type(exc).__name__,
            )
            if attempt >= CONTRACT_EXPERIENCE_HTTP_ATTEMPTS:
                raise
            time.sleep(CONTRACT_EXPERIENCE_HTTP_BACKOFF[attempt - 1])
        finally:
            CONTRACT_EXPERIENCE_LAST_REQUEST = time.monotonic()
    raise RuntimeError("Пошук договорів Prozorro недоступний")


def _contract_experience_cutoff(value: str):
    moment = _document_date(value)
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def normalize_experience_cpv(value: str) -> str:
    compact = re.sub(r"\s+", "", str(value or ""))
    match = re.search(r"(?<!\d)(\d{8}-\d)(?!\d)", compact)
    return match.group(1) if match else ""


def cpv_matches_experience(framework_cpv: str, candidate_cpv: str) -> tuple[bool, str]:
    """Apply the single configurable experience CPV policy."""
    framework = normalize_experience_cpv(framework_cpv)
    candidate = normalize_experience_cpv(candidate_cpv)
    if not framework or not candidate:
        return False, "missing"
    if framework == candidate:
        return True, "exact"
    prefix = CONTRACT_EXPERIENCE_CPV_PREFIX_DIGITS
    if framework[:prefix] == candidate[:prefix]:
        return True, f"cpv_prefix_{prefix}"
    return False, "unrelated"


def supplier_matches_experience(expected_supplier: str, parties) -> bool:
    expected = _digits(expected_supplier)
    identifiers = [
        _digits((party.get("identifier") or {}).get("id"))
        for party in (parties or []) if isinstance(party, dict)
    ]
    return bool(expected and expected in identifiers)


def _experience_item_cpvs(items, lot_id: str = "") -> list[str]:
    result = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        related_lot = str(item.get("relatedLot") or "")
        if lot_id and related_lot and related_lot != lot_id:
            continue
        classification = item.get("classification") or {}
        cpv = normalize_experience_cpv(classification.get("id") or classification.get("description") or "")
        if cpv and cpv not in result:
            result.append(cpv)
    return result


def resolve_contract_context(detail: dict) -> dict:
    """Resolve canonical contract → award → tender → lot/items context."""
    internal_id = str(detail.get("id") or "").strip()
    if not internal_id:
        raise ValueError("contract_internal_id_missing")
    raw_response = _contract_experience_http_json(
        f"https://public-api.prozorro.gov.ua/api/2.5/contracts/{urllib.parse.quote(internal_id, safe='')}"
    )
    contract = raw_response.get("data") if isinstance(raw_response.get("data"), dict) else raw_response
    if not isinstance(contract, dict):
        raise ValueError("contract_raw_detail_invalid")
    tender_internal_id = str(contract.get("tender_id") or "").strip()
    award_id = str(contract.get("awardID") or "").strip()
    contract_lots = {
        str(item.get("relatedLot") or "") for item in contract.get("items") or []
        if isinstance(item, dict) and item.get("relatedLot")
    }
    lot_id = next(iter(contract_lots), "") if len(contract_lots) == 1 else ""
    context = {
        "contract": contract,
        "award": None,
        "tender": None,
        "lot_id": lot_id,
        "candidate_cpvs": _experience_item_cpvs(contract.get("items"), lot_id),
    }
    if not tender_internal_id or not award_id:
        return context
    tender_response = _contract_experience_http_json(
        f"https://public-api.prozorro.gov.ua/api/2.5/tenders/{urllib.parse.quote(tender_internal_id, safe='')}"
    )
    tender = tender_response.get("data") if isinstance(tender_response.get("data"), dict) else tender_response
    if not isinstance(tender, dict):
        raise ValueError("tender_detail_invalid")
    award = next((item for item in tender.get("awards") or []
                  if isinstance(item, dict) and str(item.get("id") or "") == award_id), None)
    if award is None:
        raise ValueError("contract_award_not_found")
    related_lots = award.get("relatedLots") or []
    if isinstance(related_lots, str):
        related_lots = [related_lots]
    award_lots = [str(value) for value in related_lots if value]
    award_lot = str(award.get("lotID") or award.get("relatedLot")
                    or (award_lots[0] if len(award_lots) == 1 else ""))
    if award_lot:
        lot_id = award_lot
    tender_cpvs = _experience_item_cpvs(tender.get("items"), lot_id)
    context.update({
        "award": award,
        "tender": tender,
        "lot_id": lot_id,
        "candidate_cpvs": tender_cpvs or _experience_item_cpvs(contract.get("items"), lot_id),
    })
    return context


def validate_contract_candidate(detail: dict, supplier: str, framework_cpv: str,
                                cutoff, discovery_mode: str) -> tuple[dict | None, str]:
    if not isinstance(detail, dict) or detail.get("status") != "terminated":
        return None, "detail_status"
    termination_details = detail.get("terminationDetails")
    if ((isinstance(termination_details, str) and termination_details.strip())
            or (not isinstance(termination_details, str) and termination_details not in (None, [], {}))):
        return None, "termination_details"
    modified = _contract_experience_cutoff(detail.get("dateModified"))
    if modified is None:
        return None, "date_parse"
    if modified > cutoff:
        return None, "date_modified_cutoff"
    resolved = {"lot_id": "", "resolved_cpvs": [framework_cpv], "cpv_match": "external_exact"}
    if discovery_mode == "fallback":
        context = resolve_contract_context(detail)
        contract = context["contract"]
        award = context.get("award")
        if not supplier_matches_experience(supplier, contract.get("suppliers")):
            return None, "supplier_identifier"
        if award is not None and not supplier_matches_experience(supplier, award.get("suppliers")):
            return None, "award_supplier_identifier"
        matches = [(candidate_cpv, cpv_matches_experience(framework_cpv, candidate_cpv))
                   for candidate_cpv in context.get("candidate_cpvs") or []]
        matched = next(((candidate_cpv, mode) for candidate_cpv, (ok, mode) in matches if ok), None)
        if not matched:
            return None, "cpv_unrelated"
        resolved = {
            "lot_id": context.get("lot_id") or "",
            "resolved_cpvs": context.get("candidate_cpvs") or [],
            "cpv_match": matched[1],
            "resolved_cpv": matched[0],
        }
    return resolved, "accepted"


def _discover_contract_summaries(supplier: str, cpv: str | None, page_limit: int,
                                 mode: str, submission_id: str = "") -> tuple[list[dict], bool]:
    summaries = []
    had_success = False
    for page in range(1, page_limit + 1):
        payload = {"supplier": [supplier], "page": page}
        if cpv:
            payload["cpv"] = [cpv]
        try:
            search = _contract_experience_http_json("https://prozorro.gov.ua/api/search/contracts", payload)
        except Exception:
            SERVER_LOG.exception(
                "Contract experience discovery failed submission=%s supplier=%s cpv=%s mode=%s page=%s",
                submission_id, supplier, cpv or "", mode, page,
            )
            break
        had_success = True
        rows = search.get("data") if isinstance(search.get("data"), list) else []
        SERVER_LOG.info(
            "Contract experience discovery submission=%s supplier=%s cpv=%s mode=%s page=%s total=%s",
            submission_id, supplier, cpv or "", mode, page, search.get("total", 0),
        )
        summaries.extend(item for item in rows if isinstance(item, dict))
        if not rows or page * int(search.get("per_page") or 20) >= int(search.get("total") or 0):
            break
    return summaries, had_success


def search_supplier_contract_experience(supplier_code: str, cpv_code: str, submitted_at: str,
                                        submission_id: str = "") -> dict:
    """Return locally validated neutral candidates; dateModified remains a technical cutoff proxy."""
    supplier = _digits(supplier_code)
    cpv = normalize_experience_cpv(cpv_code)
    cutoff = _contract_experience_cutoff(submitted_at)
    if not supplier or not cpv or cutoff is None:
        return {"status": "unavailable", "symbol": "−", "candidates": [],
                "message": "Недостатньо даних для допоміжного пошуку договорів"}
    cache_key = (str(CONTRACT_EXPERIENCE_ALGORITHM_VERSION), supplier, cpv, cutoff.isoformat())
    now = time.monotonic()
    cached = CONTRACT_EXPERIENCE_CACHE.get(cache_key)
    if cached and now - float(cached.get("cached_at", 0)) < (
            CONTRACT_EXPERIENCE_UNAVAILABLE_CACHE_TTL
            if cached.get("value", {}).get("status") == "unavailable" else CONTRACT_EXPERIENCE_CACHE_TTL):
        return dict(cached["value"])
    with CONTRACT_EXPERIENCE_LOCK:
        cached = CONTRACT_EXPERIENCE_CACHE.get(cache_key)
        now = time.monotonic()
        if cached and now - float(cached.get("cached_at", 0)) < (
                CONTRACT_EXPERIENCE_UNAVAILABLE_CACHE_TTL
                if cached.get("value", {}).get("status") == "unavailable" else CONTRACT_EXPERIENCE_CACHE_TTL):
            return dict(cached["value"])
        candidates = []
        inspected_ids = set()
        discovery_success = False
        detail_attempts = detail_successes = 0
        technical_failures = 0

        def inspect(summaries, mode):
            nonlocal detail_attempts, detail_successes, technical_failures
            for summary in summaries:
                if len(candidates) >= CONTRACT_EXPERIENCE_MAX_CANDIDATES:
                    break
                if summary.get("status") != "terminated":
                    continue
                public_id = str(summary.get("contractID") or "").strip()
                if not public_id or public_id in inspected_ids:
                    continue
                inspected_ids.add(public_id)
                detail_attempts += 1
                try:
                    detail_response = _contract_experience_http_json(
                        f"https://prozorro.gov.ua/api/contracts/{urllib.parse.quote(public_id, safe='')}"
                    )
                    detail = detail_response.get("data") if isinstance(detail_response.get("data"), dict) else detail_response
                    resolved, reason = validate_contract_candidate(detail, supplier, cpv, cutoff, mode)
                    detail_successes += 1
                except Exception as exc:
                    technical_failures += 1
                    SERVER_LOG.warning(
                        "Contract experience candidate error submission=%s supplier=%s cpv=%s mode=%s contract=%s type=%s",
                        submission_id, supplier, cpv, mode, public_id, type(exc).__name__, exc_info=True,
                    )
                    continue
                SERVER_LOG.info(
                    "Contract experience candidate submission=%s supplier=%s cpv=%s mode=%s contract=%s "
                    "resolved_cpv=%s lot=%s supplier_match=%s cpv_match=%s reject=%s",
                    submission_id, supplier, cpv, mode, public_id,
                    (resolved or {}).get("resolved_cpv", ""), (resolved or {}).get("lot_id", ""),
                    reason not in {"supplier_identifier", "award_supplier_identifier"},
                    (resolved or {}).get("cpv_match", ""), "" if resolved else reason,
                )
                if not resolved:
                    continue
                contract_id = str(detail.get("id") or "")
                canonical_public_id = str(detail.get("contractID") or public_id)
                candidates.append({
                    "id": contract_id,
                    "contract_id": canonical_public_id,
                    "url": f"https://prozorro.gov.ua/uk/contract/{urllib.parse.quote(canonical_public_id)}",
                    "date_modified": str(detail.get("dateModified") or ""),
                    "date_signed": str(detail.get("dateSigned") or summary.get("dateSigned") or ""),
                    "buyer": str((detail.get("buyer") or summary.get("buyer") or {}).get("name") or ""),
                    "discovery_mode": mode,
                    **resolved,
                })

        exact, exact_ok = _discover_contract_summaries(
            supplier, cpv, CONTRACT_EXPERIENCE_EXACT_PAGE_LIMIT, "exact", submission_id
        )
        discovery_success = discovery_success or exact_ok
        inspect(exact, "exact")
        if not candidates:
            fallback, fallback_ok = _discover_contract_summaries(
                supplier, None, CONTRACT_EXPERIENCE_FALLBACK_PAGE_LIMIT, "fallback", submission_id
            )
            discovery_success = discovery_success or fallback_ok
            inspect(fallback, "fallback")
        if candidates:
            result = {
                "status": "found", "symbol": "+",
                "candidates": candidates,
                "message": f"Знайдено договорів-кандидатів: {len(candidates)}",
                "cpv": cpv,
                "cutoff": cutoff.isoformat(),
                "cutoff_note": "dateModified використано лише як технічний proxy cutoff",
                "algorithm_version": CONTRACT_EXPERIENCE_ALGORITHM_VERSION,
            }
        elif not discovery_success or (detail_attempts and detail_successes == 0 and technical_failures == detail_attempts):
            result = {"status": "unavailable", "symbol": "−", "candidates": [],
                      "message": "Пошук договорів Prozorro тимчасово недоступний",
                      "cpv": cpv, "cutoff": cutoff.isoformat(),
                      "cutoff_note": "Нейтральний стан; автоматичний висновок не формується",
                      "algorithm_version": CONTRACT_EXPERIENCE_ALGORITHM_VERSION}
        else:
            result = {"status": "none", "symbol": "−", "candidates": [],
                      "message": "Валідних договорів-кандидатів за кодом постачальника та CPV не знайдено",
                      "cpv": cpv, "cutoff": cutoff.isoformat(),
                      "cutoff_note": "dateModified використано лише як технічний proxy cutoff",
                      "algorithm_version": CONTRACT_EXPERIENCE_ALGORITHM_VERSION}
        SERVER_LOG.info(
            "Contract experience completed submission=%s supplier=%s cpv=%s status=%s candidates=%s",
            submission_id, supplier, cpv, result["status"], len(candidates),
        )
        CONTRACT_EXPERIENCE_CACHE[cache_key] = {"cached_at": time.monotonic(), "value": result}
        return dict(result)


def analyze_application_documents(submission_id: str, selection: dict | None = None) -> dict | None:
    with db() as con:
        row = con.execute("""SELECT s.supplier_name,s.supplier_code,s.date_published,f.pretty_id,COALESCE(f.dk_code,'') dk_code,
          COALESCE(af.manager_name,'') manager_name,COALESCE(af.contract_details,'') contract_details,COALESCE(af.authority_review,'') authority_review,
          COALESCE(af.mvs_seal_review,'') mvs_seal_review
          FROM submissions s JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN application_fields af ON af.submission_id=s.id WHERE s.id=?""", (submission_id,)).fetchone()
    collected = application_documents(submission_id)
    if not row or not collected:
        return None
    _, documents = collected
    selection = selection or {}
    selected_indexes = {int(index) for index in selection if str(index).isdigit()}
    selected_categories = {category for categories in selection.values() for category in categories}
    main_signature_index, signature_selection_source = (None, "none")
    if "signature" in selected_categories:
        main_signature_index, signature_selection_source = select_main_signature_document(documents, selection)
    included_indexes = set(selected_indexes)
    if main_signature_index is not None:
        included_indexes.add(main_signature_index)
    files, downloaded, extracted_texts = [], {}, {}
    for index, (_, document) in enumerate(documents):
        if index not in included_indexes:
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
    mvs_doc_indexes = [int(index) for index, categories in selection.items()
                       if str(index).isdigit() and "mvs" in (categories if isinstance(categories, list) else [])]
    mvs_signature_indexes = [int(index) for index, categories in selection.items()
                             if str(index).isdigit() and "mvs_signature" in (categories if isinstance(categories, list) else [])]
    if len(mvs_signature_indexes) > 1:
        raise ValueError("Залиште позначку «Печатка МВС» лише біля одного документа.")
    mvs_docs = [file_by_index[index] for index in mvs_doc_indexes if index in file_by_index and not is_signature(file_by_index[index])]
    mvs_signature_index = mvs_signature_indexes[0] if mvs_signature_indexes and mvs_signature_indexes[0] in file_by_index else None
    mvs_pairs = [{"document": document["title"],
                  "signature": file_by_index[mvs_signature_index]["title"] if mvs_signature_index is not None else "",
                  "signature_index": mvs_signature_index, "association": "manual" if mvs_signature_index is not None else ""}
                 for document in mvs_docs]
    primary_mvs_doc = mvs_docs[0] if mvs_docs else None
    mvs_extract = analyze_mvs_extract(
        extracted_texts.get(primary_mvs_doc["index"], "") if primary_mvs_doc else "",
        manager_name,
        row["date_published"] or "",
    )
    mvs_eds = verify_prozorro_eds(file_by_index[mvs_signature_index].get("url", "")) if mvs_signature_index is not None else {}
    mvs_signers = mvs_eds.get("signers") if isinstance(mvs_eds.get("signers"), list) else []
    mvs_signer = mvs_signers[0] if mvs_signers and isinstance(mvs_signers[0], dict) else {}
    mvs_code = _digits(mvs_signer.get("subjectEDRPOUCode", ""))
    mvs_org = str(mvs_signer.get("subjectOrg") or mvs_signer.get("subjectCN") or "")
    mvs_verified = mvs_eds.get("status") == "success"
    mvs_code_ok = mvs_code == "00032684"
    mvs_org_ok = "міністерствовнутрішніхсправукраїни" in normalized_value(mvs_org)
    mvs_seal = {"technical_status": mvs_eds.get("status", "not_checked"), "code": mvs_code,
                "organization": mvs_org, "error": mvs_eds.get("error", "")}
    if mvs_verified:
        mvs_seal_status = "ok" if mvs_code_ok and mvs_org_ok else "error"
        mvs_seal_detail = f"{mvs_org or 'Організацію не прочитано'} · {mvs_code or 'код не прочитано'}"
    elif row["mvs_seal_review"] == "approved":
        mvs_seal_status, mvs_seal_detail = "warning", "Печатку підтверджено вручну; автоматичну перевірку підпису не завершено"
    elif row["mvs_seal_review"] == "rejected":
        mvs_seal_status, mvs_seal_detail = "error", "Електронна печатка не належить МВС або не підтверджена"
    else:
        mvs_seal_status, mvs_seal_detail = "warning", (mvs_eds.get("error") or "Печатку МВС не перевірено")
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
        {"key": "main_signature", "label": "Основний файл sign.p7s", "status": "ok" if main_signature_index is not None else "warning", "detail": file_by_index[main_signature_index]["title"] if main_signature_index is not None else "Не вибрано"},
        {"key": "eds_verification", "label": "Автоматичне читання КЕП", "status": "ok" if eds_success else "warning", "detail": eds_technical_detail},
        {"key": "certificate_issuer", "label": "Видавець сертифіката", "status": "ok" if signature.get("issuer") else "warning", "detail": signature.get("issuer") or "Не прочитано"},
        {"key": "code", "label": "Код ЄДРПОУ / РНОКПП", "status": "ok" if code_match else "warning", "detail": code_detail},
        {"key": "organization", "label": "Назва організації", "status": "ok", "informational": True, "detail": organization or ("Не зазначено у КЕП (допустимо для ФОП)" if is_fop else "Не прочитано")},
        {"key": "signer", "label": "Підписант", "status": "ok" if signer_match else "warning", "detail": signer_detail},
        {"key": "signer_drfo", "label": "РНОКПП підписанта", "status": "ok" if drfo_code else "warning", "detail": drfo_code or "Не прочитано"},
        {"key": "signing_time", "label": "Дата/час підписання", "status": "ok" if signature.get("signing_time") else "warning", "detail": signature.get("signing_time") or "Не прочитано"},
        {"key": "authority", "label": "Повноваження підписанта", "status": "warning" if not signature.get("signer") or (authority_required and row["authority_review"] != "approved") else "ok", "detail": "Спочатку визначте підписанта через перевірку КЕП" if not signature.get("signer") else "Потрібна ручна перевірка" if authority_required and row["authority_review"] != "approved" else "Підтверджено"},
        {"key": "mvs_extract", "label": "Витяг МВС", "status": "ok" if mvs_docs else "warning", "detail": ", ".join(item["title"] for item in mvs_docs) or "Не вибрано"},
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
    # Experience is refreshed separately after submission sync. This manual
    # workflow remains strictly KEP/MVS-only.
    if selected_categories:
        def selected_check(item):
            key = item["key"]
            if key == "contract_experience":
                return "experience" in selected_categories
            if key.startswith("mvs_"):
                return bool({"mvs", "mvs_signature"} & selected_categories)
            return "signature" in selected_categories
        checks = [item for item in checks if selected_check(item)]
    else:
        checks = []
    counts = {status: sum(item["status"] == status for item in checks) for status in ("ok", "warning", "error", "neutral")}
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
    if key == "contract_experience" or key.startswith("business_") or key == "contract_history":
        return "experience"
    if key.startswith("mvs_"):
        return "mvs"
    return "signature"


def document_check_status(checks: list[dict]) -> tuple[dict, str]:
    counts = {status: sum(item.get("status") == status for item in checks)
              for status in ("ok", "warning", "error", "neutral")}
    status = ("error" if counts["error"] else "warning" if counts["warning"] else
              "ok" if counts["ok"] else "neutral")
    return counts, status


def document_check_category_summaries(result: dict) -> dict:
    stored = result.get("category_results") if isinstance(result, dict) else None
    if isinstance(stored, dict):
        summaries = {key: value.get("status", "warning") for key, value in stored.items()
                     if isinstance(value, dict) and (key != "experience" or any(
                         isinstance(item, dict) and item.get("key") == "contract_experience"
                         for item in value.get("checks", [])))}
        experience = stored.get("experience")
        if isinstance(experience, dict):
            contract_check = next((item for item in experience.get("checks", [])
                                   if isinstance(item, dict) and item.get("key") == "contract_experience"), None)
            if contract_check is not None:
                # Green means only that at least one candidate was found; every
                # other search outcome stays neutral and is not a verdict.
                summaries["experience"] = "ok" if contract_check.get("search_status") == "found" else "neutral"
        return summaries
    summaries = {}
    for check in result.get("checks", []) if isinstance(result, dict) else []:
        if not isinstance(check, dict):
            continue
        category = document_check_category(str(check.get("key") or ""))
        if category == "experience" and check.get("key") == "contract_experience":
            summaries[category] = "ok" if check.get("search_status") == "found" else "neutral"
            continue
        current = summaries.get(category, "neutral")
        status = check.get("status", "warning")
        summaries[category] = ("error" if "error" in {current, status} else
                               "warning" if "warning" in {current, status} else
                               "ok" if "ok" in {current, status} else "neutral")
    return summaries


def current_document_check_result(result: dict) -> dict:
    """Hide legacy document-based experience verdicts without rewriting stored history."""
    if not isinstance(result, dict):
        return {}
    # Work on an isolated presentation copy: old cached candidates may contain
    # an internal UUID URL even though their public contractID is correct.
    visible = json.loads(json.dumps(result, ensure_ascii=False))
    def normalize_contract_rows(rows):
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            contract_id = str(row.get("contract_id") or "").strip()
            if contract_id:
                row["url"] = f"https://prozorro.gov.ua/uk/contract/{urllib.parse.quote(contract_id)}"
    for check in visible.get("checks", []):
        if isinstance(check, dict) and check.get("key") == "contract_experience":
            normalize_contract_rows(check.get("rows"))
    experience = (visible.get("category_results") or {}).get("experience")
    if isinstance(experience, dict):
        for check in experience.get("checks", []):
            if isinstance(check, dict) and check.get("key") == "contract_experience":
                normalize_contract_rows(check.get("rows"))
    normalize_contract_rows((visible.get("contract_experience") or {}).get("candidates"))
    checks = [item for item in visible.get("checks", []) if isinstance(item, dict)
              and not (str(item.get("key") or "").startswith("business_")
                       or item.get("key") == "contract_history")]
    visible["checks"] = checks
    categories = dict(visible.get("category_results") or {})
    experience = categories.get("experience")
    if isinstance(experience, dict) and not any(
            isinstance(item, dict) and item.get("key") == "contract_experience"
            for item in experience.get("checks", [])):
        categories.pop("experience", None)
    visible["category_results"] = categories
    visible["counts"], _ = document_check_status(checks)
    visible["ready"] = not visible["counts"]["error"] and not visible["counts"]["warning"]
    return visible


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
                counts, status = document_check_status(checks)
                category_results[category] = {"checks": checks, "counts": counts, "status": status}
    selected = set(current.get("selected_categories") or [])
    if not selected:
        selected = {document_check_category(str(item.get("key") or "")) for item in current.get("checks", []) if isinstance(item, dict)}
    for category in selected:
        checks = [item for item in current.get("checks", []) if isinstance(item, dict) and document_check_category(str(item.get("key") or "")) == category]
        counts, status = document_check_status(checks)
        if category == "experience":
            contract_check = next((item for item in checks if item.get("key") == "contract_experience"), None)
            status = "ok" if contract_check and contract_check.get("search_status") == "found" else "neutral"
        category_results[category] = {"checks": checks, "counts": counts, "status": status, "checked_at": now_iso()}
    combined_checks = [item for category in ("signature", "mvs", "experience") for item in category_results.get(category, {}).get("checks", [])]
    combined_counts, _ = document_check_status(combined_checks)
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


def _stored_experience_is_fresh(existing: dict) -> bool:
    experience = (existing.get("category_results") or {}).get("experience") if isinstance(existing, dict) else None
    if not isinstance(experience, dict):
        return False
    checks = experience.get("checks") if isinstance(experience.get("checks"), list) else []
    contract_check = next((item for item in checks if isinstance(item, dict)
                           and item.get("key") == "contract_experience"), {})
    if int(contract_check.get("algorithm_version") or 0) < CONTRACT_EXPERIENCE_ALGORITHM_VERSION:
        return False
    if contract_check.get("search_status") == "unavailable":
        return False
    checked_at = _contract_experience_cutoff(experience.get("checked_at"))
    return bool(checked_at and (datetime.now(timezone.utc) - checked_at).total_seconds() < CONTRACT_EXPERIENCE_CACHE_TTL)


def _store_document_check_result(submission_id: str, current: dict, updated_by: str) -> dict:
    """Merge one category without losing a concurrent KEP/MVS result."""
    with DOCUMENT_CHECK_LOCK:
        with db() as con:
            stored = con.execute("SELECT document_check_result_json FROM application_fields WHERE submission_id=?", (submission_id,)).fetchone()
            try:
                existing = json.loads(stored[0] or "{}") if stored else {}
            except (TypeError, ValueError):
                existing = {}
            result = merge_document_check_results(existing, current)
            counts = result.get("counts") or {}
            check_status = ("error" if counts.get("error") else "warning" if counts.get("warning") else
                            "ok" if counts.get("ok") else "neutral")
            summary = (f"Перевірено: {counts.get('ok', 0)}; попереджень: {counts.get('warning', 0)}; "
                       f"помилок: {counts.get('error', 0)}; довідково: {counts.get('neutral', 0)}")
            con.execute("""INSERT INTO application_fields
              (submission_id,document_check_status,document_check_summary,document_checked_at,document_check_result_json,updated_at,updated_by)
              VALUES (?,?,?,?,?,?,?) ON CONFLICT(submission_id) DO UPDATE SET
              document_check_status=excluded.document_check_status,
              document_check_summary=excluded.document_check_summary,
              document_checked_at=excluded.document_checked_at,
              document_check_result_json=excluded.document_check_result_json,
              updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
              (submission_id, check_status, summary, now_iso(), json.dumps(result, ensure_ascii=False), now_iso(), updated_by))
    return result


def _schedule_contract_experience_retry(submission_id: str) -> bool:
    with CONTRACT_EXPERIENCE_PENDING_LOCK:
        attempts = CONTRACT_EXPERIENCE_RETRY_ATTEMPTS.get(submission_id, 0)
        if attempts >= CONTRACT_EXPERIENCE_MAX_BACKGROUND_RETRIES or submission_id in CONTRACT_EXPERIENCE_RETRY_PENDING:
            return False
        CONTRACT_EXPERIENCE_RETRY_ATTEMPTS[submission_id] = attempts + 1
        CONTRACT_EXPERIENCE_RETRY_PENDING.add(submission_id)

    def retry():
        with CONTRACT_EXPERIENCE_PENDING_LOCK:
            CONTRACT_EXPERIENCE_RETRY_PENDING.discard(submission_id)
        enqueue_contract_experience_search([submission_id])

    timer = threading.Timer(CONTRACT_EXPERIENCE_RETRY_DELAY, retry)
    timer.daemon = True
    timer.start()
    return True


def contract_experience_worker(submission_ids: list[str]) -> None:
    try:
        for submission_id in submission_ids:
            try:
                with db() as con:
                    row = con.execute("""SELECT s.supplier_name,s.supplier_code,s.date_published,
                      COALESCE(f.dk_code,'') dk_code,COALESCE(f.pretty_id,'') pretty_id,
                      COALESCE(af.document_check_result_json,'') stored_result
                      FROM submissions s JOIN frameworks f ON f.id=s.framework_id
                      LEFT JOIN application_fields af ON af.submission_id=s.id WHERE s.id=?""",
                      (submission_id,)).fetchone()
                if not row:
                    continue
                try:
                    existing = json.loads(row["stored_result"] or "{}")
                except (TypeError, ValueError):
                    existing = {}
                if _stored_experience_is_fresh(existing):
                    continue
                search = search_supplier_contract_experience(
                    row["supplier_code"], row["dk_code"], row["date_published"] or "", submission_id
                )
                check = {"key": "contract_experience", "label": "Договори постачальника в Prozorro",
                         "status": "neutral", "detail": f"{search['symbol']} · {search['message']}",
                         "rows": search.get("candidates") or [], "search_status": search.get("status"),
                         "cutoff_note": search.get("cutoff_note", ""),
                         "algorithm_version": CONTRACT_EXPERIENCE_ALGORITHM_VERSION}
                current = {"submission_id": submission_id, "supplier_name": row["supplier_name"],
                           "supplier_code": row["supplier_code"], "pretty_id": row["pretty_id"],
                           "checks": [check], "selected_categories": ["experience"],
                           "contract_experience": search,
                           "counts": {"ok": 0, "warning": 0, "error": 0, "neutral": 1},
                           "ready": True, "notice": ""}
                _store_document_check_result(submission_id, current, "PQM background contract search")
                if search.get("status") == "unavailable":
                    _schedule_contract_experience_retry(submission_id)
                else:
                    with CONTRACT_EXPERIENCE_PENDING_LOCK:
                        CONTRACT_EXPERIENCE_RETRY_ATTEMPTS.pop(submission_id, None)
                        CONTRACT_EXPERIENCE_RETRY_PENDING.discard(submission_id)
            except Exception:
                SERVER_LOG.exception("Background contract experience failed submission=%s", submission_id)
    finally:
        with CONTRACT_EXPERIENCE_PENDING_LOCK:
            CONTRACT_EXPERIENCE_PENDING.difference_update(submission_ids)


def enqueue_contract_experience_search(submission_ids) -> int:
    if SANDBOX_MODE:
        # Separate document/tender integration is not part of the approved
        # framework API scope; do not queue failing retries or overwrite checks.
        return 0
    unique = list(dict.fromkeys(str(value) for value in submission_ids if value))
    with CONTRACT_EXPERIENCE_PENDING_LOCK:
        queued = [value for value in unique if value not in CONTRACT_EXPERIENCE_PENDING]
        CONTRACT_EXPERIENCE_PENDING.update(queued)
    if queued:
        CONTRACT_EXPERIENCE_EXECUTOR.submit(contract_experience_worker, queued)
    return len(queued)


def document_check_worker(job_id: str, submission_id: str, selection: dict | None = None) -> None:
    try:
        result = analyze_application_documents(submission_id, selection)
        if not result:
            raise ValueError("Заявку не знайдено")
        result = _store_document_check_result(submission_id, result, "PQM manual document check")
        update = {"status": "complete", "result": result}
    except Exception as exc:
        SERVER_LOG.exception("Document check worker failed submission=%s", submission_id)
        update = {"status": "error", "error": f"Не вдалося перевірити документи: {exc}"}
    with DOCUMENT_CHECK_LOCK:
        if job_id in DOCUMENT_CHECK_JOBS:
            DOCUMENT_CHECK_JOBS[job_id].update(update)


class Handler(BaseHTTPRequestHandler):
    server_version = "PQM/0.1"

    def end_headers(self):
        if SANDBOX_MODE:
            self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
        super().end_headers()

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

    def chat_member(self, con, chat_id: int) -> bool:
        return bool(con.execute("SELECT 1 FROM chat_members WHERE chat_id=? AND username=?",
                                (chat_id, self.auth_user)).fetchone())

    def online_users(self) -> dict[str, float]:
        now = time.time(); result = {}
        with AUTH_SESSIONS_LOCK:
            for token, session in list(AUTH_SESSIONS.items()):
                if session["expires_at"] <= now:
                    AUTH_SESSIONS.pop(token, None); continue
                username = str(session.get("username") or ""); last_seen = float(session.get("last_seen") or 0)
                if username and last_seen > result.get(username, 0): result[username] = last_seen
        return result

    def chat_users(self, con, usernames=None):
        online, now = self.online_users(), time.time()
        params = tuple(usernames or ()); where = f"WHERE u.username IN ({','.join('?' * len(params))})" if params else "WHERE u.active=1"
        rows = con.execute(f"""SELECT u.username,u.role,u.active,COALESCE(NULLIF(p.display_name,''),o.full_name,u.username) display_name,
          p.presence_status,CASE WHEN a.username IS NULL THEN 0 ELSE 1 END has_avatar
          FROM auth_users u LEFT JOIN user_preferences p ON p.username=u.username
          LEFT JOIN authorized_officers o ON o.id=u.officer_id LEFT JOIN user_avatars a ON a.username=u.username
          {where} ORDER BY display_name COLLATE NOCASE""", params).fetchall()
        return [{**dict(row), "online": now-online.get(row["username"], 0) <= AUTH_ONLINE_WINDOW} for row in rows]

    def send_error(self, code, message=None, explain=None):
        if urllib.parse.urlparse(self.path).path.startswith("/api/"):
            return self.send_json({"error": message or "Запит не виконано", "status": code}, code)
        return super().send_error(code, message, explain)

    def _authorize(self) -> bool:
        self.auth_user = CURRENT_USER
        self.auth_role = "admin" if not AUTH_ENABLED else "viewer"
        self.auth_officer_id = None
        if not AUTH_ENABLED:
            if IS_WEB_ENV:
                self.send_json({"error": "WEB authentication must be enabled"}, 503)
                return False
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
            if session and session["expires_at"] > time.time() and accounts.get(session["username"], {}).get("active", False):
                seen_now = time.time(); session["last_seen"] = seen_now
                if seen_now - float(session.get("last_seen_persisted") or 0) >= 60:
                    session["last_seen_persisted"] = seen_now
                    try:
                        with db() as con:
                            con.execute("UPDATE auth_users SET last_seen_at=? WHERE username=?",
                                        (datetime.fromtimestamp(seen_now, timezone.utc).isoformat(), session["username"]))
                    except sqlite3.OperationalError:
                        pass
                self.auth_user = session["username"]; self.auth_role = accounts[self.auth_user]["role"]
                self.auth_officer_id = accounts[self.auth_user].get("officer_id"); return True
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

    def _authorize_supplier_registry_integration(self) -> bool:
        token_env = (SANDBOX_SUPPLIER_REGISTRY_INTEGRATION_TOKEN_ENV
                     if SANDBOX_MODE else SUPPLIER_REGISTRY_INTEGRATION_TOKEN_ENV)
        configured = str(os.environ.get(token_env) or "")
        if not configured:
            self.send_json({"error": "Integration token не налаштовано", "status": 503}, 503)
            return False
        header = str(self.headers.get("Authorization") or "")
        scheme, _, supplied = header.partition(" ")
        valid = scheme.casefold() == "bearer" and bool(supplied) and hmac.compare_digest(supplied, configured)
        if not valid:
            self.send_json({"error": "Потрібен чинний Bearer integration token", "status": 401}, 401)
            return False
        return True

    def _dispatch(self, method) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == GOOGLE_VERIFICATION_PREVIEW_PATH:
            if not SANDBOX_MODE:
                return self.send_json({"error": "SANDBOX only", "status": 404}, 404)
            if self.command != "POST":
                return self.send_json({"error": "Endpoint підтримує тільки POST", "status": 405}, 405)
            if not self._authorize_supplier_registry_integration():
                return
            self.auth_user = "integration:google-verification-preview"
            self.auth_role = "integration"
            return method()
        if path == SUPPLIER_REGISTRY_INTEGRATION_PATH:
            if self.command != "GET":
                return self.send_json({"error": "Endpoint підтримує тільки GET", "status": 405}, 405)
            if not self._authorize_supplier_registry_integration():
                return
            self.auth_user = "integration:suppliers-full-registry"
            self.auth_role = "integration"
            return method()
        # This exact GET uses the existing persisted state/PKCE transaction.
        if path == "/api/google-oauth/callback" and self.command == "GET":
            return method()
        if not self._authorize():
            return
        path = urllib.parse.urlparse(self.path).path
        if path in {"/api/login", "/api/logout"}:
            return method()
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        sandbox_local_edit = SANDBOX_MODE and sandbox_runtime.local_edit_allowed(self.command, path)
        sandbox_manual_sync = SANDBOX_MODE and sandbox_runtime.manual_sync_allowed(self.command, path)
        sandbox_document = SANDBOX_MODE and sandbox_runtime.sandbox_documents.route_allowed(self.command, path)
        sandbox_amcu = SANDBOX_MODE and sandbox_runtime.sandbox_amcu.route_allowed(self.command, path)
        if SAFE_MODE and ((self.command in {"POST", "PATCH", "PUT", "DELETE"} and not (sandbox_local_edit or sandbox_manual_sync or sandbox_document or sandbox_amcu))
                          or any(query.get(key, [""])[0].lower() in {"1", "true", "yes"}
                                 for key in ("refresh", "force"))
                          or re.fullmatch(r"/api/applications/[^/]+/verify-documents/start", path)):
            length = int(self.headers.get("Content-Length", "0"))
            if 0 < length <= 1024 * 1024:
                self.rfile.read(length)
            message = ("Sandbox: ця дія заблокована. Дозволені лише локальні тестові зміни; інтеграції та jobs вимкнено"
                       if SANDBOX_MODE and sandbox_runtime.local_edits_enabled()
                       else "WEB працює в safe mode: зміни й оновлення вимкнено")
            return self.send_json({"error": message,
                                   "code": "safe_mode", "status": 503}, 503)
        with db() as con:
            self.auth_access = auth_access.effective(con, self.auth_user, self.auth_role)
        permission = auth_access.permission_key(self.command, path)
        if not self.auth_access['active'] or (permission and not self.auth_access['permissions'].get(permission, False)):
            length = int(self.headers.get('Content-Length', '0'))
            if 0 < length <= 1024 * 1024:
                self.rfile.read(length)
            return self.send_json({'error': 'Недостатньо прав для цієї дії', 'status': 403}, 403)
        if not admin_read_allowed(self.auth_role, path, query):
            return self.send_json({"error": "Недостатньо прав для перегляду цього розділу", "status": 403}, 403)
        managed_grant = (self.auth_role == 'officer' and permission
                         and not permission.startswith('admin.')
                         and self.auth_access['permissions'].get(permission, False))
        if not mutation_allowed(self.auth_role, self.command, path) and not managed_grant:
            # Drain the small mutation body before closing the connection on Windows.
            # Otherwise the client may see a TCP reset instead of the JSON 403.
            length = int(self.headers.get("Content-Length", "0"))
            if 0 < length <= 1024 * 1024:
                self.rfile.read(length)
            return self.send_json({"error": "Недостатньо прав для цієї дії", "status": 403}, 403)
        if (self.auth_role == "officer" and path not in {'/api/history-columns','/api/account','/api/account/avatar'} and not path.startswith('/api/chats') and (self.command in {"POST", "PATCH", "PUT", "DELETE"} or permission == 'applications.check')
                and not officer_mutation_scope_allowed(path, self.auth_officer_id)):
            return self.send_json({"error": "Дія доступна лише для призначених вам заявок або звернень",
                                   "status": 403}, 403)
        application_mutation = re.fullmatch(r"/api/applications/([^/]+)(?:/.*)?", path)
        if self.command in {"POST", "PATCH", "PUT", "DELETE"} and application_mutation:
            submission_id = urllib.parse.unquote(application_mutation.group(1))
            with db() as con:
                status = con.execute("""SELECT COALESCE(q.status,'pending') FROM submissions s
                  LEFT JOIN qualifications q ON q.id=s.qualification_id WHERE s.id=?""",
                  (submission_id,)).fetchone()
            if status and status[0] in {"active", "unsuccessful"}:
                label = "Допущено" if status[0] == "active" else "Відхилено"
                return self.send_json({"error": f"Заявка має фінальний статус «{label}». Будь-які зміни рядка заблоковано для всіх ролей.",
                                       "code": "application_final_locked", "status": 409}, 409)
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
        if parsed.path == "/api/account":
            with db() as con:
                row = con.execute("SELECT display_name,start_view,density,presence_status,updated_at FROM user_preferences WHERE username=?", (self.auth_user,)).fetchone()
                managed = bool(con.execute("SELECT 1 FROM auth_users WHERE username=?", (self.auth_user,)).fetchone())
                has_avatar = bool(con.execute("SELECT 1 FROM user_avatars WHERE username=?", (self.auth_user,)).fetchone())
            return self.send_json({"username": self.auth_user, "role": self.auth_role, "managed": managed,
              "has_avatar": has_avatar, "color_scheme": "light", **(dict(row) if row else {"display_name":"","start_view":"applications","density":"comfortable","presence_status":"working","updated_at":None})})
        avatar_match = re.fullmatch(r"/api/users/([^/]+)/avatar", parsed.path)
        if avatar_match:
            username = urllib.parse.unquote(avatar_match.group(1))
            with db() as con:
                row = con.execute("SELECT content_type,content FROM user_avatars WHERE username=?", (username,)).fetchone()
            if not row:
                return self.send_error(404, "Аватар не знайдено")
            raw = bytes(row["content"])
            self.send_response(200); self.send_header("Content-Type", row["content_type"])
            self.send_header("Cache-Control", "private, max-age=300")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if parsed.path == "/api/admin/users":
            now = time.time()
            online_users: dict[str, float] = {}
            with AUTH_SESSIONS_LOCK:
                for token, session in list(AUTH_SESSIONS.items()):
                    if session["expires_at"] <= now:
                        AUTH_SESSIONS.pop(token, None)
                        continue
                    last_seen = float(session.get("last_seen") or 0)
                    username = str(session.get("username") or "")
                    if username and last_seen > online_users.get(username, 0):
                        online_users[username] = last_seen
            with db() as con:
                rows = con.execute("""SELECT u.username,u.role,u.officer_id,u.active,u.created_at,u.updated_at,u.last_seen_at,
                  p.display_name,COALESCE(ur.role_code,u.role) role_code,o.full_name officer_name
                  FROM auth_users u LEFT JOIN authorized_officers o ON o.id=u.officer_id
                  LEFT JOIN user_preferences p ON p.username=u.username
                  LEFT JOIN auth_user_roles ur ON ur.username=u.username
                  ORDER BY u.active DESC,u.username""").fetchall()
                avatars = {row["username"] for row in con.execute("SELECT username FROM user_avatars")}
                officer_names = {row["id"]: row["full_name"] for row in con.execute("SELECT id,full_name FROM authorized_officers")}
            items = [{**dict(row), "managed": True, "has_avatar": row["username"] in avatars,
                      "online": now - online_users.get(row["username"], 0) <= AUTH_ONLINE_WINDOW,
                      "last_seen_at": datetime.fromtimestamp(online_users[row["username"]], timezone.utc).isoformat()
                        if row["username"] in online_users else row["last_seen_at"]} for row in rows]
            present = {item["username"] for item in items}
            for username, account in configured_auth_accounts().items():
                if username in present:
                    continue
                officer_id = account.get("officer_id")
                items.append({"username": username, "role": account["role"], "officer_id": officer_id,
                              "officer_name": officer_names.get(officer_id), "active": True,
                              "managed": False, "has_avatar": username in avatars,
                              "online": now - online_users.get(username, 0) <= AUTH_ONLINE_WINDOW,
                              "last_seen_at": datetime.fromtimestamp(online_users[username], timezone.utc).isoformat()
                                if username in online_users else None})
            items.sort(key=lambda item: (not item["active"], item["username"].casefold()))
            return self.send_json({"items": items})
        if parsed.path == SUPPLIER_REGISTRY_INTEGRATION_PATH:
            with db() as con:
                result=supplier_registry_integration.full_registry(con)
            return self.send_json(result)
        if parsed.path == '/api/navigation-settings':
            with db() as con: return self.send_json(navigation_settings.get(con))
        if parsed.path == '/api/navigation-icons':
            with db() as con: return self.send_json(navigation_settings.list_icons(con))
        if parsed.path == '/api/table-widths':
            with db() as con: return self.send_json({'tables':table_widths.list_all(con)})
        if parsed.path == "/api/chats/users":
            with db() as con:
                return self.send_json({"items": self.chat_users(con)})
        if parsed.path == "/api/chats":
            with db() as con:
                rows = con.execute("""SELECT t.*,m.last_read_message_id,
                  (SELECT COUNT(*) FROM chat_messages x WHERE x.chat_id=t.id AND x.id>m.last_read_message_id AND x.sender_username<>?) unread_count,
                  (SELECT body FROM chat_messages x WHERE x.chat_id=t.id ORDER BY x.id DESC LIMIT 1) last_body,
                  (SELECT sender_username FROM chat_messages x WHERE x.chat_id=t.id ORDER BY x.id DESC LIMIT 1) last_sender,
                  (SELECT created_at FROM chat_messages x WHERE x.chat_id=t.id ORDER BY x.id DESC LIMIT 1) last_message_at
                  FROM chat_threads t JOIN chat_members m ON m.chat_id=t.id
                  WHERE m.username=? ORDER BY COALESCE(last_message_at,t.updated_at) DESC""",
                  (self.auth_user,self.auth_user)).fetchall()
                items=[]
                for row in rows:
                    item=dict(row); names=[x[0] for x in con.execute(
                        "SELECT username FROM chat_members WHERE chat_id=? ORDER BY username",(row["id"],))]
                    item["members"]=self.chat_users(con,names); items.append(item)
                return self.send_json({"items":items,"unread":sum(int(x["unread_count"] or 0) for x in items)})
        message_match=re.fullmatch(r"/api/chats/(\d+)/messages",parsed.path)
        if message_match:
            chat_id=int(message_match.group(1))
            with db() as con:
                if not self.chat_member(con,chat_id): return self.send_json({"error":"Чат не знайдено"},404)
                rows=con.execute("SELECT * FROM chat_messages WHERE chat_id=? ORDER BY id LIMIT 300",(chat_id,)).fetchall()
                positions={r["username"]:int(r["last_read_message_id"] or 0) for r in con.execute(
                    "SELECT username,last_read_message_id FROM chat_members WHERE chat_id=?",(chat_id,))}
                items=[]
                for row in rows:
                    item=dict(row); reads=[v for k,v in positions.items() if k!=row["sender_username"]]
                    item["read_by_all"]=bool(reads) and all(v>=row["id"] for v in reads)
                    item["attachments"]=[dict(x) for x in con.execute(
                        "SELECT id,filename,content_type,size FROM chat_attachments WHERE message_id=?",(row["id"],))]
                    item["submission"]=None
                    if row["submission_id"]:
                        submission=con.execute("""SELECT s.id,s.supplier_name,s.supplier_code,f.pretty_id framework_pretty_id
                          FROM submissions s LEFT JOIN frameworks f ON f.id=s.framework_id WHERE s.id=?""",(row["submission_id"],)).fetchone()
                        item["submission"]=dict(submission) if submission else {"id":row["submission_id"]}
                    items.append(item)
                return self.send_json({"items":items})
        attachment_match=re.fullmatch(r"/api/chats/attachments/(\d+)",parsed.path)
        if attachment_match:
            with db() as con:
                row=con.execute("""SELECT a.*,m.chat_id FROM chat_attachments a JOIN chat_messages m ON m.id=a.message_id
                  WHERE a.id=?""",(int(attachment_match.group(1)),)).fetchone()
                if not row or not self.chat_member(con,row["chat_id"]): return self.send_json({"error":"Файл не знайдено"},404)
                raw=bytes(row["content"]); content_type=row["content_type"]
                filename=re.sub(r"[^A-Za-z0-9._-]","_",row["filename"]) or "attachment"
            self.send_response(200); self.send_header("Content-Type",content_type)
            self.send_header("Content-Disposition",f'attachment; filename="{filename}"')
            self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if parsed.path == '/api/history-columns':
            return self.send_json(history_column_settings(self.auth_user))
        if parsed.path == "/api/health":
            with db() as con:
                counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("frameworks", "submissions", "qualifications")}
            return self.send_json({"ok": True, "counts": counts, "sync": sync_status_payload()})
        if parsed.path == "/api/auth/me":
            return self.send_json({"username": self.auth_user, "role": self.auth_role,
                                   "managed_role": self.auth_access['code'],
                                   "permissions": self.auth_access['permissions'],
                                   "officer_id": self.auth_officer_id,
                                   "authenticated": bool(AUTH_ENABLED),
                                   "local_impersonation": bool(not AUTH_ENABLED and LOCAL_ROLE_IMPERSONATION)})
        if parsed.path in {'/api/admin/access-roles', '/api/admin/users'}:
            with db() as con:
                return self.send_json(auth_access.roles_payload(con) if parsed.path.endswith('access-roles') else auth_access.users_payload(con))
        if parsed.path == "/api/application-profiles":
            return self.send_json(list_application_view_profiles(self.auth_user))
        if parsed.path == '/api/application-history':
            try:
                return self.send_json(application_history(urllib.parse.parse_qs(parsed.query)))
            except ValueError as exc:
                return self.send_json({'error':str(exc)}, 400)
        if parsed.path == '/api/admin/schema':
            return self.send_json(pqm_schema_metadata())
        if parsed.path == "/api/applications/search-fields":
            return self.send_json({"items": [{"key": field["key"], "label": field["label"]}
                                             for field in APPLICATION_SEARCH_FIELDS]})
        remark_selection_match = re.fullmatch(r"/api/applications/([^/]+)/remark-selections", parsed.path)
        if remark_selection_match:
            submission_id = urllib.parse.unquote(remark_selection_match.group(1))
            return self.send_json({"submission_id": submission_id,
                                   "remark_ids": application_remark_selections(submission_id)})
        if parsed.path == "/api/runtime-features":
            # Reconcile this process with the shared persistent setting. This never
            # performs startup catch-up, so a status read cannot trigger a sync.
            apply_scheduler_settings(catch_up=False)
            scheduler_jobs = scheduler_status_payload()
            scheduler_flags = {item["job"]: bool(item["enabled"]) for item in scheduler_jobs}
            manual_bids = manual_bids_update_state()
            google = google_integration_status()
            return self.send_json({
                "environment": PQM_ENV,
                "sandbox_mode": SANDBOX_MODE,
                "sandbox_local_edits": SANDBOX_MODE and sandbox_runtime.local_edits_enabled(),
                "sandbox_documents": SANDBOX_MODE and sandbox_runtime.sandbox_documents.enabled(),
                "sandbox_amcu_read": SANDBOX_MODE and sandbox_runtime.sandbox_amcu.enabled(),
                "sandbox_prozorro_read": SANDBOX_MODE and sandbox_runtime.prozorro_read_enabled(),
                "sandbox_prozorro_scheduler": SANDBOX_MODE and sandbox_runtime.prozorro_scheduler_enabled(),
                "safe_mode": SAFE_MODE,
                "bids_mode": BIDS_MODE,
                "bids_update": manual_bids["enabled"],
                "manual_bids_update": manual_bids,
                "powerbi": ENABLE_POWERBI,
                "google": google["enabled"],
                "google_integration": google,
                "scheduler": any(scheduler_flags.values()),
                "prozorro_scheduler": scheduler_flags.get("prozorro", False),
                "violation_reports_scheduler": scheduler_flags.get("violation_reports", False),
                "nazk_scheduler": scheduler_flags.get("nazk_registry", False),
                "scheduler_jobs": scheduler_jobs,
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
            result = current_document_check_result(json.loads(row[3]))
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
                    historical_read_only = historical_applications.is_read_only(submission_id)
                    if not control and not historical_read_only and not SAFE_MODE:
                        control = ensure_submission_nazk_control(con, submission_id)
                    state = get_submission_nazk_state(con, submission_id)
                    context = submission_nazk_context(con, submission_id)
                    context['manager_tax_id']=submission_manager_tax_context(con,submission_id)
                    documents = con.execute(
                        "SELECT documents_json FROM submissions WHERE id=?", (submission_id,)
                    ).fetchone()
                return self.send_json({"control": control, "state": state,
                    "documents": json.loads((documents or ["[]"])[0] or "[]"),
                    "context": context,
                    "coverage_status": "legal_date_field_unresolved",
                    "historical_read_only": historical_read_only})
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
            try:
                historical_applications.assert_editable(submission_id)
            except historical_applications.HistoricalApplicationReadOnlyError as exc:
                return self.send_json({"error": str(exc), "historical_read_only": True}, 409)
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
        if parsed.path == "/api/suppliers-registry-risk-counts":
            return self.send_json(supplier_risk_counts())
        if parsed.path == "/api/edr-monitoring":
            try:
                return self.send_json(list_edr_monitoring(urllib.parse.parse_qs(parsed.query)))
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
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
            return self.send_json({"items": template_runtime.metadata(pqm_schema_metadata())})
        if parsed.path == "/api/admin/document-metadata":
            try:
                with db() as con:
                    fields=template_catalog.validate(template_catalog.load(),pqm_schema_metadata())
                    return self.send_json(document_metadata.admin_catalog(
                        con,fields,template_runtime.configurations()))
            except ValueError as exc:return self.send_json({'error':str(exc)},400)
        if parsed.path == '/api/admin/template-fields':
            from template_catalog import catalog
            query=urllib.parse.parse_qs(parsed.query)
            try:
                return self.send_json(catalog(pqm_schema_metadata(),query.get('document_type',[''])[0],query.get('search',[''])[0]))
            except ValueError as exc:return self.send_json({'error':str(exc)},400)
        if parsed.path == "/api/declension-overrides":
            return self.send_json({"items": list_overrides()})
        template_download = re.fullmatch(r"/api/admin/templates/([^/]+)/download", parsed.path)
        if template_download:
            key = urllib.parse.unquote(template_download.group(1))
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key):
                return self.send_json({"error": "Некоректний ключ шаблону", "code": "invalid_template_key"}, 400)
            try: path = template_runtime.template_path(key)
            except ValueError: return self.send_json({"error": "Шаблон не знайдено"}, 404)
            if not path or not path.is_file():
                return self.send_json({"error": "Шаблон не знайдено"}, 404)
            return self.send_file(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", path.name)
        if parsed.path == "/api/violation-reports":
            return self.send_json(list_violation_reports(urllib.parse.parse_qs(parsed.query)))
        if parsed.path == "/api/uo-work-queue":
            query = {key: values[0] if values else "" for key, values in urllib.parse.parse_qs(parsed.query).items()}
            with db() as con:
                return self.send_json(get_uo_work_queue(
                    con, query, self.auth_user, violation_report_owned_by_pqm))
        if parsed.path == "/api/operational-tasks":
            with db() as con:
                return self.send_json(operational_tasks.list_tasks(con, urllib.parse.parse_qs(parsed.query)))
        operational_detail = re.fullmatch(r"/api/operational-tasks/([a-f0-9]{32})", parsed.path)
        if operational_detail:
            try:
                with db() as con:
                    item=operational_tasks.detail(con, operational_detail.group(1))
                    if item['task_type']=='nazk_check':
                        item['document_generation']=task_documents.readiness(con,item,pqm_schema_metadata())
                        item['document_generation']['can_manage']=bool(self.auth_access['permissions'].get('tasks.manage'))
                    elif item['task_type']=='amcu_exclusion':
                        item['document_generation']=task_documents.amcu_readiness(con,item,pqm_schema_metadata())
                        item['document_generation']['can_manage']=bool(self.auth_access['permissions'].get('tasks.manage'))
                    elif item['task_type']=='termination_exclusion':
                        item['document_generation']=task_documents.termination_readiness(con,item,pqm_schema_metadata())
                        item['document_generation']['can_manage']=bool(self.auth_access['permissions'].get('tasks.manage'))
                    return self.send_json(item)
            except KeyError: return self.send_json({"error":"Задачу не знайдено"},404)
        generated_download=re.fullmatch(r"/api/operational-tasks/([a-f0-9]{32})/documents/([a-f0-9]{32})/download",parsed.path)
        if generated_download:
            try:
                with db() as con: path,filename=task_documents.download(con,*generated_download.groups(),GENERATED_DOCUMENTS_DIR)
                raw=path.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type','application/vnd.openxmlformats-officedocument.wordprocessingml.document')
                self.send_header('Content-Disposition',"attachment; filename=request.docx; filename*=UTF-8''"+urllib.parse.quote(filename))
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
            except KeyError:return self.send_json({'error':'Документ не знайдено'},404)
        generated_pdf=re.fullmatch(r"/api/operational-tasks/([a-f0-9]{32})/documents/([a-f0-9]{32})/pdf",parsed.path)
        if generated_pdf:
            try:
                with db() as con:
                    source,filename=task_documents.amcu_pdf_source(con,*generated_pdf.groups(),GENERATED_DOCUMENTS_DIR)
                target=protocol_pdf.ensure_pdf(source,source.with_suffix('.pdf'))
                raw=target.read_bytes();self.send_response(200)
                self.send_header('Content-Type','application/pdf')
                self.send_header('Content-Disposition',"attachment; filename=protocol.pdf; filename*=UTF-8''"+urllib.parse.quote(filename))
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
            except KeyError:return self.send_json({'error':'Документ не знайдено'},404)
            except RuntimeError as exc:
                SERVER_LOG.exception('AMCU protocol PDF generation failed task=%s document=%s error=%s',*generated_pdf.groups(),exc)
                return self.send_json({'error':'Не вдалося сформувати PDF. Повторіть спробу або зверніться до адміністратора.',
                  'code':'protocol_pdf_generation_failed'},503)
        violation_sheets_json = re.fullmatch(
            r"/api/violation-reports/([^/]+)/sheets-json", parsed.path)
        if violation_sheets_json:
            report_id = urllib.parse.unquote(violation_sheets_json.group(1))
            try:
                return self.send_json(violation_report_sheets_json(report_id))
            except KeyError:
                return self.send_json({"error": "Звернення не знайдено"}, 404)
            except PermissionError as exc:
                return self.send_json({"error": str(exc), "code": "review_not_reviewed"}, 409)
        violation_detail = re.fullmatch(r"/api/violation-reports/([^/]+)", parsed.path)
        if violation_detail:
            report_id = urllib.parse.unquote(violation_detail.group(1))
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
            archive, size, failed = result
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                suffix = "-INCOMPLETE" if failed else ""
                self.send_header("Content-Disposition", f'attachment; filename="PQM-{submission_id}{suffix}.zip"')
                self.send_header("Content-Length", str(size))
                self.send_header("X-PQM-Archive-Complete", "false" if failed else "true")
                self.send_header("X-PQM-Failed-Count", str(len(failed)))
                if failed:
                    titles = [record.get("title") or record.get("file") for record in failed[:10]]
                    self.send_header("X-PQM-Failed-Documents",
                                     urllib.parse.quote(json.dumps(titles, ensure_ascii=False)))
                self.end_headers()
                while chunk := archive.read(1024 * 1024):
                    self.wfile.write(chunk)
            finally:
                archive.close()
            return
        formed_match = re.fullmatch(r'/api/protocol/formed/([a-f0-9]{32})(/download)?',parsed.path)
        if formed_match:
            try:
                with db() as con:
                    data=formed_protocols.detail(con,formed_match.group(1),PROTOCOLS_DIR)
                    if not formed_match.group(2): return self.send_json(data)
                    relative=con.execute('SELECT document_path FROM formed_protocols WHERE id=?',(data['id'],)).fetchone()[0]
                target=(PROTOCOLS_DIR/relative).resolve()
                if PROTOCOLS_DIR not in target.parents or not target.is_file(): return self.send_json({'error':'DOCX не знайдено'},404)
                raw=target.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type','application/vnd.openxmlformats-officedocument.wordprocessingml.document')
                self.send_header('Content-Disposition',"attachment; filename=protocol.docx; filename*=UTF-8''"+urllib.parse.quote(data['filename']))
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
                return
            except ValueError as exc: return self.send_json({'error':str(exc)},404)
        violation_pdf = re.fullmatch(r"/api/violation-reports/([^/]+)/protocol/pdf", parsed.path)
        if violation_pdf:
            try:
                target, filename = violation_protocol_pdf(urllib.parse.unquote(violation_pdf.group(1)))
            except FileNotFoundError as exc:
                return self.send_json({"error": str(exc)}, 404)
            except RuntimeError as exc:
                SERVER_LOG.exception(
                    "Protocol PDF generation failed report=%s error=%s",
                    urllib.parse.unquote(violation_pdf.group(1)), exc,
                )
                return self.send_json({
                    "error": "Не вдалося сформувати PDF. Повторіть спробу або зверніться до адміністратора.",
                    "code": "protocol_pdf_generation_failed",
                }, 503)
            raw = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", "attachment; filename=protocol.pdf; filename*=UTF-8''" + urllib.parse.quote(filename))
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers(); self.wfile.write(raw)
            return
        if parsed.path.startswith("/api/protocol/files/"):
            filename = urllib.parse.unquote(parsed.path[len("/api/protocol/files/"):])
            protocols_dir = PROTOCOLS_DIR
            target = (protocols_dir / filename).resolve()
            if not target.is_relative_to(protocols_dir) or '_formed' in target.relative_to(protocols_dir).parts:
                return self.send_json({'error':'Використайте посилання чинного сформованого протоколу'},404)
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
            return self.send_json(remarks_catalog(force=query.get("refresh") == ["1"],
                include_inactive=self.auth_role == 'admin' and query.get('all') == ['1']))
        if parsed.path == "/api/reference-status":
            return self.send_json(reference_status(DB_PATH))
        if parsed.path == "/api/supplier-edr-sync-status":
            return self.send_json(supplier_edr_sync_status())
        if parsed.path == "/api/supplier-edr-export":
            query = urllib.parse.parse_qs(parsed.query)
            sheet_type = (query.get("type") or ["ALL"])[0].upper()
            mode = (query.get("mode") or ["filtered"])[0]
            selected_codes = {_digits(value) for raw in query.get("codes", [])
                              for value in raw.split(",") if _digits(value)}
            if mode == "selected" and not selected_codes:
                return self.send_json({"error": "Оберіть щонайменше одного постачальника"}, 400)
            status_map = {"active": "Активний", "suspended": "Призупинений",
                          "terminated": "Неактивний", "not_registered": "Ще не в реєстрі"}
            requested_status = (query.get("status") or [""])[0]
            status_values = {status_map[requested_status]} if requested_status in status_map else set()
            monitoring_status = (query.get("prozorro_status") or [""])[0]
            if monitoring_status in set(status_map.values()):
                status_values = {monitoring_status}
            if not status_values and (mode == "selected" or (query.get("freshness") or [""])[0] in {"not_current", "not_checked"}):
                status_values = set(status_map.values())
            if not status_values and query.get("view") == ["edr_monitoring"]:
                status_values = set(status_map.values())
            filtered_codes = selected_codes
            if mode != "selected":
                listing_params = {key: list(values) for key, values in query.items()
                                  if key in {"search", "entity_type", "status", "prozorro_status", "edr_status", "freshness",
                                             "verification_from", "verification_to", "application_from",
                                             "application_to", "admission_from", "admission_to", "dk_code", "risk"}}
                if query.get("view") == ["edr_monitoring"]:
                    if "status" in listing_params:
                        listing_params["prozorro_status"] = listing_params.pop("status")
                    filtered_codes = set(edr_monitoring_filtered_codes(listing_params))
                else:
                    if sheet_type == "ФОП":
                        listing_params["entity_type"] = ["individual_entrepreneur"]
                    elif sheet_type == "ЮО":
                        listing_params["entity_type"] = ["legal_entity"]
                    listing_params["_include_codes"] = ["1"]
                    listing_params["page"] = ["1"]
                    listing_params["size"] = ["10"]
                    filtered_codes = set(list_qualified_suppliers(listing_params).get("filtered_codes") or [])
            filters = {
                "prozorro_statuses": status_values or {"Активний", "Призупинений"},
                "freshness_bucket": (query.get("freshness") or [""])[0],
                "verification_from": (query.get("verification_from") or [""])[0],
                "verification_to": (query.get("verification_to") or [""])[0],
                "supplier_codes": filtered_codes,
                "selected_mode": mode == "selected",
            }
            try:
                raw = (edr_monitoring_export_csv(filtered_codes)
                       if mode != "selected" and query.get("view") == ["edr_monitoring"]
                       else supplier_edr_export_csv(sheet_type, filters))
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
            filename = (f"{sheet_type}_ЄДР.csv" if sheet_type in {"ФОП", "ЮО"}
                        else "ClarityChecker_відфільтровані.csv")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(filename))
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers(); self.wfile.write(raw); return
        if parsed.path == "/api/supplier-nazk-review-sync-status":
            return self.send_json(supplier_nazk_review_sync_status())
        if parsed.path == "/api/google-oauth/status":
            return self.send_json(google_oauth_status())
        if parsed.path == "/api/google-oauth/callback":
            query = urllib.parse.parse_qs(parsed.query)
            expected_origin = _google_origin(_google_oauth_redirect_uri())
            try:
                if query.get("error"):
                    if query.get("state"):
                        try:
                            pending = _consume_google_oauth_transaction(query["state"][0])
                            expected_origin = pending["expected_origin"]
                        except ValueError:
                            pass
                    raise ValueError(query["error"][0])
                exchange = google_oauth_exchange(query.get("code", [""])[0], query.get("state", [""])[0])
                expected_origin = exchange["expected_origin"]
                message = "Google успішно підключено. Це вікно можна закрити."
                ok = True
            except Exception as exc:
                message = f"Помилка підключення Google: {exc}"
                ok = False
            callback_message = json.dumps({"type": "pqm-google-oauth", "ok": ok}, ensure_ascii=False)
            target_origin = json.dumps(expected_origin)
            raw = ("<!doctype html><meta charset='utf-8'><title>Google OAuth — PQM</title>"
                   f"<body style='font:16px system-ui;padding:40px'><h2>{'Готово' if ok else 'Помилка'}</h2>"
                   f"<p>{html.escape(message)}</p><script>if(window.opener)window.opener.postMessage({callback_message},{target_origin})</script></body>").encode("utf-8")
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
        if (ROOT not in target.parents or not target.is_file()
                or not (path in {"index.html"} or (target.parent == ROOT and target.suffix in {".js", ".css"})
                        or (ROOT / "assets") in target.parents)):
            return self.send_error(404)
        raw = target.read_bytes()
        if SANDBOX_MODE and path == "index.html":
            raw = sandbox_runtime.decorate_html(raw)
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def _do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == GOOGLE_VERIFICATION_PREVIEW_PATH:
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 32768:
                    return self.send_json({"error": "Preview payload size invalid"}, 413)
                payload = json.loads(self.rfile.read(size))
                con = legacy_google_verification_preview.open_read_only(DB_PATH)
                try:
                    result = legacy_google_verification_preview.preview(con, payload)
                    result["query_only"] = con.execute("PRAGMA query_only").fetchone()[0]
                finally:
                    con.close()
                return self.send_json(result)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.send_json({"error": str(exc)}, 400)
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
            now = time.time()
            session = {"username": username, "role": account["role"], "officer_id": account.get("officer_id"),
                       "expires_at": now + AUTH_SESSION_TTL, "last_seen": now, "last_seen_persisted": now}
            with db() as con:
                con.execute("UPDATE auth_users SET last_seen_at=? WHERE username=?", (now_iso(), username))
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
        if parsed.path == "/api/account/avatar":
            payload = self.read_json(); content_type = str(payload.get("content_type") or "").casefold()
            if content_type not in {"image/png", "image/jpeg", "image/webp"}:
                return self.send_json({"error": "Дозволено лише PNG, JPEG або WebP"}, 400)
            try: raw = base64.b64decode(payload.get("content") or "", validate=True)
            except Exception: return self.send_json({"error": "Не вдалося прочитати зображення"}, 400)
            signatures = {"image/png": raw.startswith(b"\x89PNG\r\n\x1a\n"), "image/jpeg": raw.startswith(b"\xff\xd8\xff"),
                          "image/webp": raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"}
            if not raw or len(raw) > 2 * 1024 * 1024 or not signatures[content_type]:
                return self.send_json({"error": "Некоректне зображення або розмір перевищує 2 МБ"}, 400)
            with db() as con:
                con.execute("""INSERT INTO user_avatars(username,content_type,content,updated_at,updated_by)
                  VALUES (?,?,?,?,?) ON CONFLICT(username) DO UPDATE SET content_type=excluded.content_type,
                  content=excluded.content,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                  (self.auth_user,content_type,raw,now_iso(),self.auth_user))
            return self.send_json({"saved": True})
        if parsed.path == "/api/admin/users":
            payload = self.read_json()
            if "role_code" in payload:
                try:
                    with db() as con:
                        con.execute("BEGIN IMMEDIATE")
                        auth_access.save_user(con, payload, self.auth_user, configured_auth_accounts())
                    return self.send_json({"saved": True})
                except (ValueError, sqlite3.IntegrityError) as exc:
                    return self.send_json({"error": str(exc) if isinstance(exc, ValueError)
                                           else "Конфлікт облікового запису або УО"}, 400)
            username = str(payload.get("username") or "").strip()
            password = str(payload.get("password") or ""); role = str(payload.get("role") or "officer").casefold()
            officer_id = payload.get("officer_id") or None
            if not re.fullmatch(r"[A-Za-z0-9._-]{3,50}", username):
                return self.send_json({"error": "Логін: 3–50 латинських літер, цифр або . _ -"}, 400)
            if username in configured_auth_accounts():
                return self.send_json({"error": "Цей системний логін уже налаштований через Render"}, 409)
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
        avatar_match = re.fullmatch(r"/api/admin/users/([^/]+)/avatar", parsed.path)
        if avatar_match:
            username = urllib.parse.unquote(avatar_match.group(1)); payload = self.read_json()
            if username not in auth_accounts():
                return self.send_json({"error": "Користувача не знайдено"}, 404)
            content_type = str(payload.get("content_type") or "").casefold()
            if content_type not in {"image/png", "image/jpeg", "image/webp"}:
                return self.send_json({"error": "Дозволено лише PNG, JPEG або WebP"}, 400)
            try:
                raw = base64.b64decode(payload.get("content") or "", validate=True)
            except Exception:
                return self.send_json({"error": "Не вдалося прочитати зображення"}, 400)
            signatures = {"image/png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
                          "image/jpeg": raw.startswith(b"\xff\xd8\xff"),
                          "image/webp": raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"}
            if not raw or len(raw) > 2 * 1024 * 1024 or not signatures[content_type]:
                return self.send_json({"error": "Некоректне зображення або розмір перевищує 2 МБ"}, 400)
            with db() as con:
                con.execute("""INSERT INTO user_avatars(username,content_type,content,updated_at,updated_by)
                  VALUES (?,?,?,?,?) ON CONFLICT(username) DO UPDATE SET content_type=excluded.content_type,
                  content=excluded.content,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                  (username, content_type, raw, now_iso(), self.auth_user))
            return self.send_json({"saved": True, "username": username})
        if parsed.path in {"/api/edr-monitoring/termination-exclusions/preview",
                           "/api/edr-monitoring/termination-exclusions/create"}:
            try:
                payload=self.read_json(); codes=payload.get("supplier_codes")
                if not isinstance(codes,list) or not codes:
                    raise ValueError("Оберіть щонайменше одного постачальника")
                if len(codes)>1000: raise ValueError("За одну дію можна опрацювати не більше 1000 постачальників")
                with db() as con:
                    if parsed.path.endswith("/preview"):
                        return self.send_json(operational_tasks.preview_termination_exclusions(con,codes))
                    if not payload.get("confirmed"):
                        raise ValueError("Потрібне явне підтвердження створення задач")
                    con.execute("BEGIN IMMEDIATE")
                    result=operational_tasks.create_termination_exclusions(con,codes,self.auth_user)
                return self.send_json(result,201)
            except ValueError as exc:return self.send_json({"error":str(exc)},400)
        if parsed.path == "/api/admin/runtime-features/google":
            payload = self.read_json()
            if type(payload.get("enabled")) is not bool:
                return self.send_json({"error": "Поле enabled має бути true або false"}, 400)
            set_google_runtime_enabled(payload["enabled"], self.auth_user)
            return self.send_json({"saved": True, "feature": google_integration_status()})
        if parsed.path == "/api/admin/google/disconnect":
            self.read_json()
            return self.send_json({"saved": True, "feature": disconnect_google(self.auth_user)})
        if parsed.path == "/api/admin/runtime-features/manual-bids-update":
            payload = self.read_json()
            if type(payload.get("enabled")) is not bool:
                return self.send_json({"error": "Поле enabled має бути true або false"}, 400)
            try:
                feature = set_manual_bids_update_enabled(payload["enabled"], self.auth_user)
                return self.send_json({"saved": True, "feature": feature})
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
        scheduler_toggle = re.fullmatch(r"/api/admin/scheduler-jobs/([a-z_]+)", parsed.path)
        if scheduler_toggle:
            payload = self.read_json()
            if type(payload.get("enabled")) is not bool:
                return self.send_json({"error": "Поле enabled має бути true або false"}, 400)
            try:
                item = set_scheduler_job_enabled(scheduler_toggle.group(1), payload["enabled"], self.auth_user)
                return self.send_json({"saved": True, "job": item})
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
        generate_request=re.fullmatch(r"/api/operational-tasks/([a-f0-9]{32})/documents/nazk-supplier-request",parsed.path)
        if generate_request:
            try:
                payload=self.read_json()
                if payload:raise ValueError('Дія не приймає template key, path або document context від клієнта')
                schema=pqm_schema_metadata()
                with db() as con:
                    con.execute('BEGIN IMMEDIATE')
                    item=operational_tasks.detail(con,generate_request.group(1))
                    document=task_documents.generate(con,item,schema,GENERATED_DOCUMENTS_DIR,self.auth_user)
                    docs=task_documents.documents(con,item['id'])
                    event=dict(con.execute('SELECT * FROM operational_task_events WHERE task_id=? ORDER BY id DESC LIMIT 1',(item['id'],)).fetchone())
                    event['metadata']=json.loads(event['metadata'])
                return self.send_json({'document':document,'documents':docs,'event':event},201)
            except KeyError:return self.send_json({'error':'Задачу не знайдено'},404)
            except (ValueError,OSError) as exc:return self.send_json({'error':str(exc)},422)
        generate_amcu=re.fullmatch(r"/api/operational-tasks/([a-f0-9]{32})/documents/(amcu-exclusion-protocol|termination-exclusion-protocol)",parsed.path)
        if generate_amcu:
            try:
                payload=self.read_json()
                if payload:raise ValueError('Дія не приймає template key, path або document context від клієнта')
                schema=pqm_schema_metadata()
                with db() as con:
                    con.execute('BEGIN IMMEDIATE')
                    item=operational_tasks.detail(con,generate_amcu.group(1))
                    termination=generate_amcu.group(2)=='termination-exclusion-protocol'
                    generator=task_documents.generate_termination if termination else task_documents.generate_amcu
                    document=generator(con,item,schema,GENERATED_DOCUMENTS_DIR,self.auth_user)
                    docs=[doc for doc in task_documents.documents(con,item['id'])
                          if doc['document_type']==(task_documents.TERMINATION_PROTOCOL_KEY if termination else task_documents.AMCU_PROTOCOL_KEY)]
                    event=dict(con.execute('SELECT * FROM operational_task_events WHERE task_id=? ORDER BY id DESC LIMIT 1',(item['id'],)).fetchone())
                    event['metadata']=json.loads(event['metadata'])
                return self.send_json({'document':document,'documents':docs,'event':event},201)
            except KeyError:return self.send_json({'error':'Задачу не знайдено'},404)
            except task_documents.DeclensionRequired as exc:
                return self.send_json({'error':str(exc),'code':'declension_unresolved','unresolved':exc.unresolved},422)
            except (ValueError,OSError) as exc:return self.send_json({'error':str(exc)},422)
        operational_channel = re.fullmatch(r"/api/operational-tasks/([a-f0-9]{32})/channels/(supplier|nazk)/sent", parsed.path)
        if operational_channel:
            try:
                with db() as con: result=operational_tasks.record_channel_sent(
                    con,operational_channel.group(1),operational_channel.group(2),self.read_json(),self.auth_user)
                return self.send_json(result)
            except KeyError: return self.send_json({"error":"Задачу не знайдено"},404)
            except ValueError as exc: return self.send_json({"error":str(exc)},400)
        operational_response = re.fullmatch(r"/api/operational-tasks/([a-f0-9]{32})/responses", parsed.path)
        if operational_response:
            try:
                with db() as con: result=operational_tasks.add_response(
                    con,operational_response.group(1),self.read_json(),self.auth_user)
                return self.send_json(result)
            except KeyError: return self.send_json({"error":"Задачу не знайдено"},404)
            except ValueError as exc: return self.send_json({"error":str(exc)},400)
        operational_nazk_result = re.fullmatch(r"/api/operational-tasks/([a-f0-9]{32})/nazk-result", parsed.path)
        if operational_nazk_result:
            try:
                payload=self.read_json()
                with db() as con: result=operational_tasks.set_nazk_result(con,operational_nazk_result.group(1),str(payload.get("result") or ""),self.auth_user,str(payload.get("comment") or ""))
                return self.send_json(result)
            except KeyError: return self.send_json({"error":"Задачу не знайдено"},404)
            except ValueError as exc: return self.send_json({"error":str(exc)},400)
        operational_manager_tax = re.fullmatch(r"/api/operational-tasks/([a-f0-9]{32})/manager-tax-id", parsed.path)
        if operational_manager_tax:
            try:
                payload=self.read_json()
                with db() as con: result=operational_tasks.set_task_manager_tax_id(con,operational_manager_tax.group(1),payload.get("manager_tax_id"),self.auth_user)
                return self.send_json(result)
            except KeyError: return self.send_json({"error":"Задачу не знайдено"},404)
            except ValueError as exc: return self.send_json({"error":str(exc)},400)
        operational_blocking_decision = re.fullmatch(r"/api/operational-tasks/([a-f0-9]{32})/blocking-decision", parsed.path)
        if operational_blocking_decision:
            try:
                with db() as con: result=operational_tasks.attach_blocking_decision(con,operational_blocking_decision.group(1),self.read_json(),self.auth_user)
                return self.send_json(result)
            except KeyError: return self.send_json({"error":"Задачу не знайдено"},404)
            except ValueError as exc: return self.send_json({"error":str(exc)},400)
        operational_blocking_complete = re.fullmatch(r"/api/operational-tasks/([a-f0-9]{32})/blocking-complete", parsed.path)
        if operational_blocking_complete:
            try:
                with db() as con: result=operational_tasks.complete_legacy_blocking(con,operational_blocking_complete.group(1),self.auth_user)
                return self.send_json(result)
            except KeyError: return self.send_json({"error":"Задачу не знайдено"},404)
            except ValueError as exc: return self.send_json({"error":str(exc)},400)
        if parsed.path == '/api/admin/template-fields/derived':
            from template_catalog import save_derived
            try:
                data=save_derived(pqm_schema_metadata(),self.read_json(),self.auth_user,self.auth_role)
                return self.send_json({'saved':True,'revision':data['revision']})
            except PermissionError as exc:return self.send_json({'error':str(exc)},403)
            except (ValueError,KeyError,TypeError) as exc:return self.send_json({'error':str(exc)},400)
        if parsed.path == '/api/admin/template-fields/update':
            from template_catalog import update_field
            payload=self.read_json()
            try:
                data=update_field(pqm_schema_metadata(),payload.get('key'),payload.get('changes',{}),self.auth_user,self.auth_role,payload.get('revision'))
                return self.send_json({'saved':True,'revision':data['revision']})
            except PermissionError as exc:return self.send_json({'error':str(exc)},403)
            except (ValueError,KeyError,TypeError) as exc:return self.send_json({'error':str(exc)},400)
        if parsed.path == '/api/admin/navigation-settings':
            payload=self.read_json()
            try:
                with db() as con: result=navigation_settings.save(con,payload.get('overrides'),self.auth_user)
            except ValueError as exc: return self.send_json({'error':str(exc)},400)
            return self.send_json(result)
        if parsed.path == '/api/admin/navigation-icons':
            payload=self.read_json()
            try:
                with db() as con: result=navigation_settings.save_icon(con,payload,self.auth_user)
            except ValueError as exc: return self.send_json({'error':str(exc)},400)
            return self.send_json(result)
        if parsed.path == '/api/admin/navigation-icons/preview':
            payload=self.read_json()
            try:result=navigation_settings.icon_preview(payload.get('svg'),payload.get('color_mode','original'))
            except ValueError as exc:return self.send_json({'error':str(exc)},400)
            return self.send_json(result)
        if parsed.path == "/api/operational-tasks/rebuild":
            return self.send_json({"ok":True,"counts":rebuild_operational_tasks(self.auth_user)})
        if parsed.path == '/api/admin/table-widths':
            payload=self.read_json()
            try:
                with db() as con: widths=table_widths.save(con,payload.get('table_key'),payload.get('widths'),self.auth_user,payload.get('visible'))
            except (TypeError,ValueError) as exc: return self.send_json({'error':str(exc)},400)
            return self.send_json({'saved':True,'widths':widths})
        if parsed.path == "/api/chats":
            payload=self.read_json(); members=[]
            for value in payload.get("members") or []:
                username=str(value or "").strip()
                if username and username!=self.auth_user and username not in members: members.append(username)
            if not members or len(members)>49: return self.send_json({"error":"Оберіть від 1 до 49 учасників"},400)
            with db() as con:
                marks=','.join('?'*len(members)); valid={r[0] for r in con.execute(
                    f"SELECT username FROM auth_users WHERE active=1 AND username IN ({marks})",tuple(members))}
                if valid!=set(members): return self.send_json({"error":"Один або кілька акаунтів недоступні"},400)
                all_members=[self.auth_user,*members]; is_group=len(all_members)>2
                title=str(payload.get("title") or "").strip()[:100]
                if is_group and not title: return self.send_json({"error":"Вкажіть назву групового чату"},400)
                stamp=now_iso(); cur=con.execute("INSERT INTO chat_threads(title,is_group,created_by,created_at,updated_at) VALUES (?,?,?,?,?)",
                    (title,int(is_group),self.auth_user,stamp,stamp)); chat_id=cur.lastrowid
                con.executemany("INSERT INTO chat_members(chat_id,username,joined_at) VALUES (?,?,?)",
                    [(chat_id,name,stamp) for name in all_members])
            return self.send_json({"id":chat_id},201)
        send_match=re.fullmatch(r"/api/chats/(\d+)/messages",parsed.path)
        if send_match:
            chat_id=int(send_match.group(1)); payload=self.read_json(); body=str(payload.get("body") or "").strip()[:10000]
            submission_id=str(payload.get("submission_id") or "").strip(); attachment=payload.get("attachment")
            raw=b""; filename=""; content_type=""
            if attachment:
                filename=Path(str(attachment.get("filename") or "attachment")).name[:180]
                content_type=str(attachment.get("content_type") or "application/octet-stream").casefold()[:100]
                try: raw=base64.b64decode(attachment.get("content") or "",validate=True)
                except Exception: return self.send_json({"error":"Не вдалося прочитати вкладення"},400)
                if not raw or len(raw)>5*1024*1024: return self.send_json({"error":"Файл порожній або перевищує 5 МБ"},400)
            if not body and not submission_id and not raw: return self.send_json({"error":"Напишіть повідомлення або додайте вкладення"},400)
            with db() as con:
                if not self.chat_member(con,chat_id): return self.send_json({"error":"Чат не знайдено"},404)
                stamp=now_iso(); cur=con.execute("INSERT INTO chat_messages(chat_id,sender_username,body,submission_id,created_at) VALUES (?,?,?,?,?)",
                    (chat_id,self.auth_user,body,submission_id,stamp)); message_id=cur.lastrowid
                if raw: con.execute("INSERT INTO chat_attachments(message_id,filename,content_type,content,size,created_at) VALUES (?,?,?,?,?,?)",
                                    (message_id,filename,content_type,raw,len(raw),stamp))
                con.execute("UPDATE chat_threads SET updated_at=? WHERE id=?",(stamp,chat_id))
                con.execute("UPDATE chat_members SET last_read_message_id=? WHERE chat_id=? AND username=?",(message_id,chat_id,self.auth_user))
            return self.send_json({"id":message_id},201)
        read_match=re.fullmatch(r"/api/chats/(\d+)/read",parsed.path)
        if read_match:
            chat_id=int(read_match.group(1))
            with db() as con:
                if not self.chat_member(con,chat_id): return self.send_json({"error":"Чат не знайдено"},404)
                latest=con.execute("SELECT COALESCE(MAX(id),0) FROM chat_messages WHERE chat_id=?",(chat_id,)).fetchone()[0]
                con.execute("UPDATE chat_members SET last_read_message_id=? WHERE chat_id=? AND username=?",(latest,chat_id,self.auth_user))
            return self.send_json({"read":True,"message_id":latest})
        if parsed.path == '/api/history-columns':
            try:
                payload=self.read_json()
                if 'columns' not in payload:raise ValueError('Відсутні налаштування колонок')
                return self.send_json(history_column_settings(self.auth_user,payload['columns']))
            except ValueError as exc:
                return self.send_json({'error':str(exc)},400)
        if parsed.path in {'/api/admin/access-roles', '/api/admin/users'}:
            payload = self.read_json()
            try:
                with db() as con:
                    con.execute('BEGIN IMMEDIATE')
                    if parsed.path.endswith('access-roles'):
                        auth_access.save_role(con, payload, self.auth_user)
                    else:
                        auth_access.save_user(con, payload, self.auth_user, configured_auth_accounts())
                return self.send_json({'saved': True})
            except (ValueError, sqlite3.IntegrityError) as exc:
                return self.send_json({'error': str(exc) if isinstance(exc, ValueError) else 'Конфлікт облікового запису або УО'}, 400)
        if parsed.path == "/api/application-profiles":
            payload = self.read_json(); name = str(payload.get("name") or "").strip()
            if not name: return self.send_json({"error": "Вкажіть назву профілю"}, 400)
            is_system = bool(payload.get("is_system"))
            if is_system and self.auth_role != "admin":
                return self.send_json({"error": "Системні профілі може створювати лише адміністратор"}, 403)
            layout_json = _profile_layout_json(payload.get("columns"), payload.get("kpis"), payload.get("sorts"))
            profile_id = str(uuid.uuid4())
            owner = "__system__" if is_system else _profile_owner(self.auth_user)
            source = str(payload.get("source_system_profile_id") or "").strip() or None
            with db() as con:
                try:
                    con.execute("""INSERT INTO application_view_profiles
                      (id,owner_key,name,is_system,source_system_profile_id,columns_json,
                       created_at,updated_at,created_by,updated_by) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      (profile_id, owner, name, int(is_system), source,
                       layout_json, now_iso(), now_iso(), self.auth_user, self.auth_user))
                except sqlite3.IntegrityError:
                    return self.send_json({"error": "Профіль із такою назвою вже існує"}, 409)
            return self.send_json({"saved": True, "id": profile_id}, 201)
        if parsed.path.startswith("/api/violation-reports/") and parsed.path.endswith("/protocol/generate"):
            report_id = urllib.parse.unquote(parsed.path[len("/api/violation-reports/"):-len("/protocol/generate")]).rstrip("/")
            payload = self.read_json()
            try:
                return self.send_json(generate_violation_protocol(report_id, payload, self.auth_user))
            except DeclensionValidationError as exc:
                return self.send_json(exc.payload(), 422)
            except KeyError:
                return self.send_json({"error": "Звернення не знайдено"}, 404)
            except ConnectionError as exc:
                return self.send_json({"error": str(exc)}, 503)
            except ForeignAuthorityError as exc:
                return self.send_json({"error": str(exc), "is_read_only": True}, 403)
        if parsed.path.startswith("/api/violation-reports/") and parsed.path.endswith("/review/complete"):
            report_id = urllib.parse.unquote(parsed.path[len("/api/violation-reports/"):-len("/review/complete")]).rstrip("/")
            payload = self.read_json()
            try:
                return self.send_json(complete_violation_review(report_id, self.auth_user, payload))
            except KeyError:
                return self.send_json({"error": "Звернення не знайдено"}, 404)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
            except PermissionError as exc:
                status = 403 if isinstance(exc, ForeignAuthorityError) else 409
                return self.send_json({"error": str(exc), "is_read_only": True}, status)
            except ConnectionError as exc:
                return self.send_json({"error": str(exc)}, 503)
            except RuntimeError as exc:
                return self.send_json({"error": str(exc)}, 409)
            except (ValueError, PermissionError) as exc:
                return self.send_json({"error": str(exc)}, 409)
        if parsed.path.startswith("/api/applications/") and parsed.path.endswith("/verify-documents"):
            submission_id = urllib.parse.unquote(parsed.path.split("/")[3])
            try:
                historical_applications.assert_editable(submission_id)
            except historical_applications.HistoricalApplicationReadOnlyError as exc:
                return self.send_json({"error": str(exc), "historical_read_only": True}, 409)
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
                return self.send_json(generate_protocol(self.read_json(),self.auth_user,self.auth_role,self.auth_officer_id))
            except PermissionError as exc:
                return self.send_json({'error':str(exc)},403)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 409)
        cancel_match=re.fullmatch(r'/api/protocol/(formed|legacy)/([^/]+)/cancel',parsed.path)
        if cancel_match:
            payload=self.read_json();kind,identifier=cancel_match.groups();identifier=urllib.parse.unquote(identifier)
            try:
                with db() as con:
                    con.execute('BEGIN IMMEDIATE')
                    ids=([x['id'] for x in formed_protocols.detail(con,identifier)['items']] if kind=='formed' else [identifier])
                    if any(historical_applications.is_read_only(submission_id) for submission_id in ids):
                        raise historical_applications.HistoricalApplicationReadOnlyError(
                            "Історична заявка MedData доступна лише для перегляду"
                        )
                    assert_protocol_scope(con,ids,self.auth_role,self.auth_officer_id)
                    fn=formed_protocols.cancel if kind=='formed' else formed_protocols.release_legacy
                    result=fn(con,identifier,self.auth_user,payload.get('confirmed'),payload.get('reason',''))
                return self.send_json(result)
            except historical_applications.HistoricalApplicationReadOnlyError as exc:
                return self.send_json({'error':str(exc),'historical_read_only':True},409)
            except PermissionError as exc: return self.send_json({'error':str(exc)},403)
            except ValueError as exc: return self.send_json({'error':str(exc)},409)
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
            if not start_violation_reports_sync():
                return self.send_json(VIOLATION_SYNC_STATE, 409)
            return self.send_json({"started": True}, 202)
        if parsed.path == "/api/bids-sync":
            payload = self.read_json()
            if not manual_bids_update_state()["enabled"]:
                return self.send_json({"error": "Оновлення ProzorroBids вимкнене в цьому середовищі"}, 403)
            with BIDS_START_LOCK:
                if BIDS_UPDATE_STATE["running"]:
                    BIDS_UPDATE_STATE['duplicate_attempts'] = BIDS_UPDATE_STATE.get('duplicate_attempts',0)+1
                    SERVER_LOG.info('Bids duplicate launch rejected run_id=%s pid=%s', BIDS_UPDATE_STATE.get('run_id'), BIDS_UPDATE_STATE.get('pid'))
                    return self.send_json({**bids_run_snapshot(), 'code':'already_running'}, 409)
                try:
                    preflight = bids_runtime_check()
                    if payload.get("check_only") is True:
                        return self.send_json({"started": False, "runtime_ready": True,
                                               "preflight": preflight}, 200)
                    BIDS_UPDATE_STATE.update(running=True, status='running', run_id=uuid.uuid4().hex,
                        message="Підготовка оновлення Bids…", started_at=now_iso(), error=None,
                        finished_at=None, updated_at=None, stage='preparing', processed=None, total=None,
                        last_activity_at=now_iso(), current_run_errors=0, last_error=None, pid=None, duplicate_attempts=0)
                    worker = threading.Thread(target=bids_update_worker, daemon=True)
                    worker.start()
                except Exception as exc:
                    SERVER_LOG.exception("Bids startup failed")
                    if BIDS_UPDATE_STATE.get('status') != 'running':
                        BIDS_UPDATE_STATE.update(run_id=uuid.uuid4().hex,started_at=now_iso(),
                                                stage='preflight',current_run_errors=1,pid=None,
                                                processed=None,total=None,last_activity_at=now_iso())
                    message = f"Не вдалося запустити ProzorroBids: {exc}"
                    BIDS_UPDATE_STATE.update(running=False, status='failed', finished_at=now_iso(),
                        last_error=str(exc), error=str(exc), message=message)
                    return self.send_json({"started": False, "code": "bids_start_failed", "error": BIDS_UPDATE_STATE["message"]}, 503)
            return self.send_json({"started": True}, 202)
        if parsed.path == "/api/supplier-edr-sync":
            payload = self.read_json()
            if not google_effective_enabled():
                return self.send_json({"error": "Google integration вимкнено адміністратором"}, 403)
            if SUPPLIER_EDR_SYNC_STATE["running"]:
                return self.send_json(SUPPLIER_EDR_SYNC_STATE, 409)
            fingerprint = str(payload.get("source_fingerprint") or "").strip().lower()
            if payload.get("confirmed") is not True or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                return self.send_json({"error": "Спочатку виконайте preview і явно підтвердьте той самий source fingerprint"}, 409)
            SUPPLIER_EDR_SYNC_STATE.update(running=True, message="Підготовка синхронізації довідника ЄДР…",
                                           started_at=now_iso(), updated_at=None, error=None)
            threading.Thread(target=supplier_edr_sync_worker,
                             args=(fingerprint, self.auth_user), daemon=True).start()
            return self.send_json({"started": True}, 202)
        if parsed.path == "/api/supplier-edr-export":
            payload = self.read_json()
            selected_codes = {_digits(value) for value in (payload.get("supplier_codes") or []) if _digits(value)}
            if not selected_codes:
                return self.send_json({"error": "Оберіть щонайменше одного постачальника"}, 400)
            if len(selected_codes) > 5000:
                return self.send_json({"error": "За один раз можна експортувати до 5000 вибраних постачальників"}, 400)
            raw = supplier_edr_export_csv("ALL", {"supplier_codes": selected_codes, "selected_mode": True,
                                                   "prozorro_statuses": {"Активний", "Призупинений", "Неактивний", "Ще не в реєстрі"}})
            filename = "ClarityChecker_вибрані.csv"
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(filename))
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers(); self.wfile.write(raw); return
        if parsed.path == "/api/supplier-edr-sync/preview":
            self.read_json()
            if not google_effective_enabled():
                return self.send_json({"error": "Google integration вимкнено адміністратором"}, 403)
            if SUPPLIER_EDR_SYNC_STATE["running"]:
                return self.send_json(SUPPLIER_EDR_SYNC_STATE, 409)
            try:
                return self.send_json(supplier_edr_sync_preview())
            except GooglePhaseError as exc:
                return self.send_json({"error": str(exc), **exc.diagnostic_payload()}, 409)
            except (ValueError, RuntimeError, OSError) as exc:
                return self.send_json({"error": str(exc)}, 409)
        if parsed.path == "/api/supplier-nazk-review-sync":
            self.read_json()
            if not google_effective_enabled():
                return self.send_json({"error": "Google integration вимкнено адміністратором"}, 403)
            if SUPPLIER_NAZK_REVIEW_SYNC_STATE["running"]:
                return self.send_json(SUPPLIER_NAZK_REVIEW_SYNC_STATE, 409)
            SUPPLIER_NAZK_REVIEW_SYNC_STATE.update(running=True,
                message="Підготовка синхронізації перевірок НАЗК…", started_at=now_iso(),
                updated_at=None, error=None)
            threading.Thread(target=supplier_nazk_review_sync_worker, daemon=True).start()
            return self.send_json({"started": True}, 202)
        if parsed.path == "/api/google-oauth/start":
            self.read_json()
            if not google_effective_enabled():
                return self.send_json({"error": "Google OAuth вимкнено в цьому середовищі"}, 403)
            try:
                return self.send_json({"authorization_url": google_oauth_authorization_url(self.auth_user)}, 200)
            except (FileNotFoundError, RuntimeError, OSError, ValueError) as exc:
                return self.send_json({"error": str(exc), "oauth": google_oauth_status()}, 409)
        if parsed.path == "/api/powerbi-export":
            if not ENABLE_POWERBI:
                return self.send_json({"error": "Power BI export вимкнено в цьому середовищі"}, 403)
            result, status = start_powerbi_export()
            return self.send_json(result, status)
        if parsed.path == "/api/remarks-catalog":
            payload = self.read_json(); point = str(payload.get("point") or "").strip(); text = str(payload.get("text") or "").strip()
            if not point or not text: return self.send_json({"error": "Заповніть пункт і текст шаблону"}, 400)
            with db() as con:
                con.execute('BEGIN IMMEDIATE')
                normalize = lambda value: ' '.join(str(value or '').casefold().split())
                duplicate = next((row for row in con.execute('SELECT id,point,text FROM remarks_catalog')
                                  if normalize(row['point']) == normalize(point) and normalize(row['text']) == normalize(text)), None)
                if duplicate:
                    return self.send_json({'error':'Такий пункт і текст уже є у довіднику', 'duplicate_id':duplicate['id']},409)
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
        if parsed.path == "/api/admin/declension-overrides":
            try:
                return self.send_json({"saved": True, "item": save_override(self.read_json())}, 201)
            except OverrideConflictError as exc:
                return self.send_json({"error": str(exc), "code": "duplicate_declension"}, 409)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
        if parsed.path == "/api/admin/document-metadata":
            try:
                payload=self.read_json()
                fields=template_catalog.validate(template_catalog.load(),pqm_schema_metadata())
                runtime=document_metadata.registered_document_types(template_runtime.configurations())
                used=document_metadata.validate_definition(payload.get('document_type'),payload.get('metadata_key'),
                    payload.get('label'),payload.get('template_text'),fields,runtime)
                if payload.get('validate_only'):
                    with db() as con:
                        if con.execute("SELECT 1 FROM document_metadata_templates WHERE document_type=? AND metadata_key=?",
                          (str(payload.get('document_type') or '').strip(),str(payload.get('metadata_key') or '').strip())).fetchone():
                            return self.send_json({'error':'Метадані з таким key уже існують для цього типу документа',
                              'code':'duplicate_document_metadata'},409)
                    return self.send_json({'valid':True,'used_fields':used})
                with db() as con:
                    item,used=document_metadata.create(con,payload,fields,runtime,self.auth_user)
                return self.send_json({'saved':True,'changed':True,'item':item,'used_fields':used},201)
            except document_metadata.MetadataConflict as exc:
                return self.send_json({'error':str(exc),'code':'duplicate_document_metadata'},409)
            except ValueError as exc:return self.send_json({'error':str(exc)},400)
        metadata_save = re.fullmatch(r"/api/admin/document-metadata/([a-z][a-z0-9_]{0,63})/([a-z][a-z0-9_]{0,63})", parsed.path)
        if metadata_save:
            document_type,metadata_key=metadata_save.groups()
            try:
                payload=self.read_json()
                fields=template_catalog.validate(template_catalog.load(),pqm_schema_metadata())
                runtime=document_metadata.registered_document_types(template_runtime.configurations())
                if payload.get('validate_only'):
                    used=document_metadata.validate_definition(document_type,metadata_key,
                      payload.get('label') or metadata_key,payload.get('template_text'),fields,runtime)
                    return self.send_json({'valid':True,'used_fields':used})
                with db() as con:
                    item,changed,used=document_metadata.update(con,document_type,metadata_key,
                      payload,fields,runtime,self.auth_user)
                return self.send_json({'saved':True,'changed':changed,'item':item,'used_fields':used})
            except KeyError:return self.send_json({'error':'Метадані документа не знайдено'},404)
            except ValueError as exc:return self.send_json({'error':str(exc)},400)
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
            diagnostics = {'original_filename':str(payload.get('filename') or ''),
                'file_size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'template_key':key,
                'validation_result':'not_run','failure_stage':'candidate_save'}
            response_item = None
            def finalize_template(target):
                nonlocal response_item
                diagnostics['failure_stage']='metadata'
                response_item=next(x for x in template_runtime.metadata(pqm_schema_metadata()) if x['key']==key)
                if diagnostics.get('unchanged'):return
                diagnostics['failure_stage']='audit'
                with db() as con:
                    con.execute("""INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value)
                      VALUES (?,?,?,?,?,?)""", (f"document_template:{key}", now_iso(), self.auth_user,
                      "document_template.replaced", "", target.name))
            try:
                temporary.write_bytes(raw)
                target = template_runtime.replace(key, temporary, pqm_schema_metadata(),
                    finalize=finalize_template,diagnostics=diagnostics)
                if response_item is None:finalize_template(target)  # legacy adapter
            except ValueError as exc:
                diagnostics['exception_type']=type(exc).__name__
                SERVER_LOG.warning('Template upload failed %s',json.dumps(diagnostics,ensure_ascii=False))
                return self.send_json({"error": str(exc)}, 400)
            except Exception as exc:
                diagnostics['exception_type']=type(exc).__name__
                SERVER_LOG.exception('Template upload failed %s',json.dumps(diagnostics,ensure_ascii=False))
                raise
            finally:
                temporary.unlink(missing_ok=True)
            return self.send_json({"saved": True, "item": response_item})
        if parsed.path == "/api/nazk-registry/refresh":
            if not start_nazk_registry_refresh(trigger="manual"):
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
        if parsed.path == "/api/account":
            payload = self.read_json()
            display_name = str(payload.get("display_name") or "").strip()[:100]
            start_view = str(payload.get("start_view") or "applications")
            color_scheme = "light"
            density = str(payload.get("density") or "comfortable")
            presence_status = str(payload.get("presence_status") or "working")
            if start_view not in {"workQueue","applications","suppliers","frameworks","procurements","references","requests"}:
                return self.send_json({"error": "Некоректний стартовий розділ"}, 400)
            if density not in {"comfortable","compact"}:
                return self.send_json({"error": "Некоректні налаштування вигляду"}, 400)
            if presence_status not in {"working","away","vacation"}:
                return self.send_json({"error": "Некоректний статус присутності"}, 400)
            with db() as con:
                current = con.execute("SELECT * FROM auth_users WHERE username=?", (self.auth_user,)).fetchone()
                new_password = str(payload.get("new_password") or "")
                if new_password:
                    if not current:
                        return self.send_json({"error": "Пароль цього акаунта керується через Render"}, 409)
                    old_password = str(payload.get("current_password") or "")
                    if not verify_basic_auth_secret(old_password, current["password_hash"]):
                        return self.send_json({"error": "Поточний пароль неправильний"}, 403)
                    try: password_hash = hash_password(new_password)
                    except ValueError as exc: return self.send_json({"error": str(exc)}, 400)
                    con.execute("UPDATE auth_users SET password_hash=?,updated_at=? WHERE username=?", (password_hash,now_iso(),self.auth_user))
                con.execute("""INSERT INTO user_preferences(username,display_name,start_view,color_scheme,density,presence_status,updated_at)
                  VALUES (?,?,?,?,?,?,?) ON CONFLICT(username) DO UPDATE SET display_name=excluded.display_name,
                  start_view=excluded.start_view,color_scheme='light',density=excluded.density,
                  presence_status=excluded.presence_status,updated_at=excluded.updated_at""",
                  (self.auth_user,display_name,start_view,color_scheme,density,presence_status,now_iso()))
            if new_password:
                with AUTH_SESSIONS_LOCK:
                    for token, session in list(AUTH_SESSIONS.items()):
                        if session["username"] == self.auth_user: AUTH_SESSIONS.pop(token, None)
            return self.send_json({"saved": True, "reauthenticate": bool(new_password)})
        user_match = re.fullmatch(r"/api/admin/users/([^/]+)", parsed.path)
        if user_match:
            username = urllib.parse.unquote(user_match.group(1)); payload = self.read_json()
            with db() as con:
                current = con.execute("SELECT * FROM auth_users WHERE username=?", (username,)).fetchone()
                if not current: return self.send_json({"error": "Користувача не знайдено"}, 404)
                role = str(payload.get("role", current["role"])).casefold()
                officer_id = payload.get("officer_id", current["officer_id"]) or None
                active = 1 if payload.get("active", bool(current["active"])) else 0
                if username == self.auth_user and not active:
                    return self.send_json({"error": "Не можна призупинити власний акаунт"}, 409)
                password_hash = current["password_hash"]
                if payload.get("password"):
                    try: password_hash = hash_password(str(payload["password"]))
                    except ValueError as exc: return self.send_json({"error": str(exc)}, 400)
                if role not in AUTH_ROLES or (role == "officer" and not officer_id):
                    return self.send_json({"error": "Для officer потрібно вибрати конкретну УО"}, 400)
                if current["role"] == "admin" and (role != "admin" or not active):
                    managed_admins = con.execute("SELECT COUNT(*) FROM auth_users WHERE role='admin' AND active=1 AND username<>?", (username,)).fetchone()[0]
                    configured_admins = sum(1 for item in configured_auth_accounts().values() if item.get("role") == "admin")
                    if managed_admins + configured_admins == 0:
                        return self.send_json({"error": "Не можна вимкнути останнього активного адміністратора"}, 409)
                try:
                    con.execute("UPDATE auth_users SET password_hash=?,role=?,officer_id=?,active=?,updated_at=? WHERE username=?",
                                (password_hash,role,officer_id,active,now_iso(),username))
                except sqlite3.IntegrityError:
                    return self.send_json({"error": "Ця УО вже має активний акаунт"}, 409)
            with AUTH_SESSIONS_LOCK:
                for token, session in list(AUTH_SESSIONS.items()):
                    if session["username"] == username: AUTH_SESSIONS.pop(token, None)
            return self.send_json({"saved": True})
        operational_response = re.fullmatch(
            r"/api/operational-tasks/([a-f0-9]{32})/responses/(\d+)", parsed.path)
        if operational_response:
            try:
                with db() as con:
                    result=operational_tasks.update_response(
                        con,operational_response.group(1),int(operational_response.group(2)),
                        self.read_json(),self.auth_user)
                return self.send_json(result)
            except KeyError: return self.send_json({"error":"Інформацію не знайдено"},404)
            except ValueError as exc: return self.send_json({"error":str(exc)},400)
        operational_extract = re.fullmatch(r"/api/operational-tasks/([a-f0-9]{32})/amcu-decisions/(.+)", parsed.path)
        if operational_extract:
            try:
                with db() as con: result=operational_tasks.set_amcu_extract(con,operational_extract.group(1),urllib.parse.unquote(operational_extract.group(2)),self.read_json().get("extract_url"),self.auth_user)
                return self.send_json(result)
            except KeyError: return self.send_json({"error":"Рішення АМКУ не знайдено"},404)
        operational_match = re.fullmatch(r"/api/operational-tasks/([a-f0-9]{32})", parsed.path)
        if operational_match:
            try:
                with db() as con: result=operational_tasks.update(con,operational_match.group(1),self.read_json(),self.auth_user)
                return self.send_json(result)
            except KeyError: return self.send_json({"error":"Задачу не знайдено"},404)
            except ValueError as exc: return self.send_json({"error":str(exc)},400)
        declension_match = re.fullmatch(r"/api/admin/declension-overrides/([^/]+)", parsed.path)
        if declension_match:
            try:
                item = save_override(self.read_json(), urllib.parse.unquote(declension_match.group(1)))
                return self.send_json({"saved": True, "item": item})
            except KeyError:
                return self.send_json({"error": "Запис відмінювання не знайдено"}, 404)
            except OverrideConflictError as exc:
                return self.send_json({"error": str(exc), "code": "duplicate_declension"}, 409)
            except ValueError as exc:
                return self.send_json({"error": str(exc)}, 400)
        profile_match = re.fullmatch(r"/api/application-profiles/([^/]+)", parsed.path)
        if profile_match:
            profile_id = urllib.parse.unquote(profile_match.group(1)); payload = self.read_json()
            with db() as con:
                current = con.execute("SELECT * FROM application_view_profiles WHERE id=?", (profile_id,)).fetchone()
                if not current: return self.send_json({"error": "Профіль не знайдено"}, 404)
                if current["is_system"] and self.auth_role != "admin":
                    return self.send_json({"error": "Системний профіль може змінювати лише адміністратор"}, 403)
                if not current["is_system"] and current["owner_key"] != _profile_owner(self.auth_user):
                    return self.send_json({"error": "Можна змінювати лише власні профілі"}, 403)
                fields, values = [], []
                if "name" in payload:
                    name = str(payload.get("name") or "").strip()
                    if not name: return self.send_json({"error": "Вкажіть назву профілю"}, 400)
                    fields.append("name=?"); values.append(name)
                if "columns" in payload or "kpis" in payload or "sorts" in payload:
                    try: current_layout = json.loads(current["columns_json"] or "[]")
                    except json.JSONDecodeError: current_layout = []
                    old_columns = current_layout.get("columns", []) if isinstance(current_layout, dict) else current_layout
                    old_kpis = current_layout.get("kpis", []) if isinstance(current_layout, dict) else []
                    old_sorts = current_layout.get("sorts", []) if isinstance(current_layout, dict) else []
                    fields.append("columns_json=?")
                    values.append(_profile_layout_json(payload.get("columns", old_columns),
                                                       payload.get("kpis", old_kpis), payload.get("sorts", old_sorts)))
                if fields:
                    fields.extend(["updated_at=?", "updated_by=?"]); values.extend([now_iso(), self.auth_user, profile_id])
                    try: con.execute(f"UPDATE application_view_profiles SET {','.join(fields)} WHERE id=?", values)
                    except sqlite3.IntegrityError: return self.send_json({"error": "Профіль із такою назвою вже існує"}, 409)
            return self.send_json({"saved": True, "id": profile_id})
        remark_selection_match = re.fullmatch(r"/api/applications/([^/]+)/remark-selections", parsed.path)
        if remark_selection_match:
            submission_id = urllib.parse.unquote(remark_selection_match.group(1)); payload = self.read_json()
            try:
                historical_applications.assert_editable(submission_id)
            except historical_applications.HistoricalApplicationReadOnlyError as exc:
                return self.send_json({"error": str(exc), "historical_read_only": True}, 409)
            try: ids = save_application_remark_selections(submission_id, payload.get("remark_ids"), self.auth_user)
            except KeyError: return self.send_json({"error": "Заявку не знайдено"}, 404)
            except ValueError as exc: return self.send_json({"error": str(exc)}, 400)
            return self.send_json({"saved": True, "remark_ids": ids})
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
        supplier_note_match = re.fullmatch(r"/api/suppliers/([^/]+)/note", parsed.path)
        if supplier_note_match:
            supplier_code = re.sub(r"\D", "", urllib.parse.unquote(supplier_note_match.group(1)))
            if not supplier_code:
                return self.send_json({"error": "Не визначено код постачальника"}, 400)
            payload = self.read_json()
            note = str(payload.get("note") or "").strip()
            changed_at = now_iso()
            with db() as con:
                current = con.execute("SELECT note FROM supplier_notes WHERE DIGITS(supplier_code)=?",
                                      (supplier_code,)).fetchone()
                old_note = str(current["note"] or "") if current else ""
                if old_note != note:
                    con.execute("""INSERT INTO supplier_notes(supplier_code,note,updated_at,updated_by)
                      VALUES (?,?,?,?) ON CONFLICT(supplier_code) DO UPDATE SET
                      note=excluded.note,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                      (supplier_code, note, changed_at, self.auth_user))
                    con.execute("""INSERT INTO supplier_note_events
                      (supplier_code,old_note,new_note,changed_at,changed_by) VALUES (?,?,?,?,?)""",
                      (supplier_code, old_note, note, changed_at, self.auth_user))
            return self.send_json({"saved": True, "supplier_code": supplier_code, "note": note,
                                   "updated_at": changed_at, "updated_by": self.auth_user})
        if parsed.path.startswith("/api/applications/") and parsed.path.endswith("/nazk-control"):
            submission_id = urllib.parse.unquote(parsed.path.split("/")[3])
            payload = self.read_json()
            try:
                historical_applications.assert_editable(submission_id)
                with db() as con:
                    if payload.get('action') == 'save_manager_tax_id':
                        result={'manager_tax_id':save_submission_manager_tax_id(con,submission_id,
                            payload.get('manager_tax_id'),self.auth_user,payload.get('manager_id'))}
                    elif payload.get("action") == "complete_refuted":
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
            except historical_applications.HistoricalApplicationReadOnlyError as exc:
                return self.send_json({"error": str(exc), "historical_read_only": True}, 409)
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
        try:
            historical_applications.assert_editable(submission_id)
        except historical_applications.HistoricalApplicationReadOnlyError as exc:
            return self.send_json({"error": str(exc), "historical_read_only": True}, 409)
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
            con.execute('BEGIN IMMEDIATE')
            try: formed_protocols.guard_edit(con,submission_id,payload)
            except ValueError as exc: return self.send_json({'error':str(exc)},409)
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
                        review_officer = canonical_officer_identity(con, user, self.auth_officer_id)
                        if not review_officer:
                            con.rollback()
                            return self.send_json({
                                "error": "Обліковий запис не прив’язаний до активної уповноваженої особи"
                            }, 409)
                        review_old = con.execute(
                            "SELECT COALESCE(review_officer,'') FROM application_fields WHERE submission_id=?",
                            (submission_id,),
                        ).fetchone()[0]
                        con.execute(
                            "UPDATE application_fields SET review_officer=? WHERE submission_id=?",
                            (review_officer, submission_id),
                        )
                        if review_old != review_officer:
                            con.execute(
                                "INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value) VALUES (?,?,?,?,?,?)",
                                (submission_id, now_iso(), user, "review_officer", review_old, review_officer),
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
        if parsed.path == "/api/account/avatar":
            with db() as con:
                con.execute("DELETE FROM user_avatars WHERE username=?", (self.auth_user,))
            return self.send_json({"deleted": True})
        user_match = re.fullmatch(r"/api/admin/users/([^/]+)", parsed.path)
        if user_match:
            username = urllib.parse.unquote(user_match.group(1))
            if username == self.auth_user:
                return self.send_json({"error": "Не можна видалити власний акаунт"}, 409)
            with db() as con:
                current = con.execute("SELECT role,active FROM auth_users WHERE username=?", (username,)).fetchone()
                if not current: return self.send_json({"error": "Цей акаунт керується через Render або вже видалений"}, 409)
                if current["role"] == "admin" and current["active"]:
                    managed_admins = con.execute("SELECT COUNT(*) FROM auth_users WHERE role='admin' AND active=1 AND username<>?", (username,)).fetchone()[0]
                    configured_admins = sum(1 for item in configured_auth_accounts().values() if item.get("role") == "admin")
                    if managed_admins + configured_admins == 0:
                        return self.send_json({"error": "Не можна видалити останнього активного адміністратора"}, 409)
                con.execute("DELETE FROM user_avatars WHERE username=?", (username,))
                con.execute("DELETE FROM user_preferences WHERE username=?", (username,))
                con.execute("DELETE FROM auth_user_roles WHERE username=?", (username,))
                con.execute("DELETE FROM auth_users WHERE username=?", (username,))
            with AUTH_SESSIONS_LOCK:
                for token, session in list(AUTH_SESSIONS.items()):
                    if session["username"] == username: AUTH_SESSIONS.pop(token, None)
            return self.send_json({"deleted": True, "username": username})
        avatar_match = re.fullmatch(r"/api/admin/users/([^/]+)/avatar", parsed.path)
        if avatar_match:
            username = urllib.parse.unquote(avatar_match.group(1))
            with db() as con:
                con.execute("DELETE FROM user_avatars WHERE username=?", (username,))
            return self.send_json({"deleted": True, "username": username})
        if parsed.path == '/api/admin/navigation-settings':
            with db() as con: result=navigation_settings.reset(con)
            return self.send_json(result)
        declension_match = re.fullmatch(r"/api/admin/declension-overrides/([^/]+)", parsed.path)
        if declension_match:
            try:
                delete_override(urllib.parse.unquote(declension_match.group(1)))
                return self.send_json({"deleted": True})
            except KeyError:
                return self.send_json({"error": "Запис відмінювання не знайдено"}, 404)
        if parsed.path == '/api/admin/table-widths':
            key=urllib.parse.parse_qs(parsed.query).get('table_key',[''])[0]
            with db() as con: table_widths.reset(con,key)
            return self.send_json({'reset':True})
        profile_match = re.fullmatch(r"/api/application-profiles/([^/]+)", parsed.path)
        if profile_match:
            profile_id = urllib.parse.unquote(profile_match.group(1))
            with db() as con:
                current = con.execute("SELECT owner_key,is_system FROM application_view_profiles WHERE id=?", (profile_id,)).fetchone()
                if not current: return self.send_json({"error": "Профіль не знайдено"}, 404)
                if current["is_system"] and self.auth_role != "admin":
                    return self.send_json({"error": "Системний профіль може видаляти лише адміністратор"}, 403)
                if not current["is_system"] and current["owner_key"] != _profile_owner(self.auth_user):
                    return self.send_json({"error": "Можна видаляти лише власні профілі"}, 403)
                con.execute("UPDATE application_view_profiles SET source_system_profile_id=NULL WHERE source_system_profile_id=?", (profile_id,))
                con.execute("DELETE FROM application_view_profiles WHERE id=?", (profile_id,))
            return self.send_json({"deleted": True, "id": profile_id})
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
    if IS_WEB_ENV and not DB_PATH.is_file():
        raise RuntimeError('Existing persistent WEB database missing. STOP; do not create an empty replacement.')
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROTOCOLS_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    init_reference_tables(DB_PATH)
    restore_sync_data_timestamp()
    with db() as con:
        scheduler_runtime.migrate(con)
    try:
        counts = {} if env_flag("PQM_RELEASE_SCHEMA_ONLY", IS_WEB_ENV) else rebuild_operational_tasks()
        SERVER_LOG.info("Operational task builder completed counts=%s", counts)
    except Exception:
        SERVER_LOG.exception("Operational task builder failed during startup")

    scheduler_enabled = apply_scheduler_settings(catch_up=True)
    print(f"PQM 0.1 ({PQM_ENV}): http://{HOST}:{PORT}")
    print(f"Data: {DATA_DIR} · DB: {DB_PATH}")
    print(f"Features: prozorro_scheduler={scheduler_enabled['prozorro']}, "
          f"violation_scheduler={scheduler_enabled['violation_reports']}, nazk_scheduler={scheduler_enabled['nazk_registry']}, "
          f"bids={BIDS_MODE}, bids_update={ENABLE_BIDS_UPDATE}, powerbi={ENABLE_POWERBI}, "
          f"google={google_effective_enabled()}, auth={AUTH_ENABLED}")
    SERVER_LOG.info("PQM startup environment=%s host=%s port=%s data_dir=%s db=%s",
                    PQM_ENV, HOST, PORT, DATA_DIR, DB_PATH)
    if ENABLE_BROWSER:
        threading.Timer(1, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    ExclusiveThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
