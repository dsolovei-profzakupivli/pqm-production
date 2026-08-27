"""PQM 0.1 local server: SQLite storage, Prozorro sync and browser API."""
from __future__ import annotations

import json
import base64
import binascii
import hmac
import csv
import hashlib
import html
import io
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
from reference_directories import (
    init_reference_tables, list_registry, reference_status,
    refresh_amcu, refresh_nazk,
)

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("PQM_DATA_DIR", str(ROOT / "data"))).expanduser().resolve()
DB_PATH = DATA_DIR / "pqm.sqlite3"
BIDS_DB_PATH = Path(os.environ.get("PQM_BIDS_DB", str(DATA_DIR / "prozorro_bids.db"))).expanduser()
BIDS_STATUS_CACHE: dict = {"at": 0.0, "value": None}
BIDS_STATUS_LOCK = threading.Lock()
BIDS_PROJECT_PATH = Path(os.environ.get("PQM_BIDS_PROJECT", str(DATA_DIR / "ProzorroBids"))).expanduser()
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
GOOGLE_OAUTH_DIR = Path(os.environ.get("PQM_GOOGLE_OAUTH_DIR", str(DATA_DIR / "google_oauth"))).expanduser()
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
TESSERACT_EXE = Path(os.environ.get("TESSERACT_EXE", "tesseract"))
TESSDATA_DIR = ROOT / "tools" / "tessdata"
PDFTOPPM_EXE = Path(os.environ.get("PDFTOPPM_EXE", "pdftoppm"))
API_ROOT = "https://public-api.prozorro.gov.ua/api/2.5"
ORGANIZER_EDRPOU = "40996564"
DEFAULT_FRAMEWORK_ID = "92e49fa487da40b3ab080b030f8a2b5d"
ANNOUNCEMENTS_CSV = "https://docs.google.com/spreadsheets/d/1kdjP1Yr5C5UuO-Otju8xC8eo7p5BMewTCDdkLyS6Ofg/export?format=csv&gid=1378255205"
REMARKS_CSV = "https://docs.google.com/spreadsheets/d/1S94-jj5ys-BIwiWeWhxVNwRFilMrq0erOuJGWMXci1w/export?format=csv&gid=1118329674"
REMARKS_CACHE = DATA_DIR / "remarks_catalog.json"
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
    allow_reuse_address = False

    def server_bind(self):
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if os.name == "nt" and exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        super().server_bind()
PROTOCOL_DECISIONS = {"", "admit", "reject"}
MARKETPLACE_DECISIONS = {"", "admit", "reject"}
COMPLIANCE_STATUSES = {"", "approved", "rejected"}
AUTHORITY_REVIEWS = {"", "approved", "missing", "not_required"}
PROTOCOL_OFFICERS = {"Світлана НАМЯСЕНКО", "Дмитро САВВА", "Тетяна ФЕДЧЕНКО", "Олена ЄРЬОМІНА"}
SYNC_STATE = {"running": False, "message": "Синхронізацію ще не запускали", "updated_at": None,
              "started_at": None, "next_run_at": None, "mode": None, "duration_seconds": None}
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
    names = {
        "Намясенко": "Світлана НАМЯСЕНКО",
        "Савва": "Дмитро САВВА",
        "Федченко": "Тетяна ФЕДЧЕНКО",
        "Єрьоміна": "Олена ЄРЬОМІНА",
        "Абросімова": "Олена АБРОСІМОВА",
    }
    clean = (value or "").strip()
    return names.get(clean, clean)


def sync_framework_officers() -> dict:
    rows = load_announcement_rows()
    assignments = {}
    for row in rows:
        pretty_id = (row.get("ID") or "").strip()
        officer = announcement_officer_name(row.get("Хто публікує") or "")
        marketplace_url = (row.get("Посилання на майданчик") or "").strip()
        status = (row.get("status") or "").strip().casefold()
        if pretty_id and officer and status == "активне":
            assignments[pretty_id] = (officer, marketplace_url)
    matched = 0
    with db() as con:
        con.execute("DELETE FROM framework_officers WHERE source=?", ("Google Sheets: Оголошення",))
        for pretty_id, (officer, marketplace_url) in assignments.items():
            framework = con.execute("SELECT id FROM frameworks WHERE pretty_id=?", (pretty_id,)).fetchone()
            if not framework:
                continue
            con.execute("""INSERT INTO framework_officers(framework_id,officer,marketplace_url,source,synced_at)
              VALUES (?,?,?,?,?) ON CONFLICT(framework_id) DO UPDATE SET
              officer=excluded.officer,marketplace_url=excluded.marketplace_url,
              source=excluded.source,synced_at=excluded.synced_at""",
              (framework[0], officer, marketplace_url, "Google Sheets: Оголошення", now_iso()))
            matched += 1
    return {"rows": len(rows), "assigned": len(assignments), "matched": matched}


def load_announcement_rows() -> list[dict]:
    request = urllib.request.Request(ANNOUNCEMENTS_CSV, headers={"User-Agent": "PQM/0.1"})
    with urllib.request.urlopen(request, timeout=30, context=ssl.create_default_context()) as response:
        return list(csv.DictReader(io.StringIO(response.read().decode("utf-8-sig"))))


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
    if not BIDS_DB_PATH.is_file():
        raise FileNotFoundError(f"ProzorroBids database not found: {BIDS_DB_PATH}")
    con = sqlite3.connect(f"file:{BIDS_DB_PATH.as_posix()}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    con.create_function("DIGITS", 1, lambda value: re.sub(r"\D", "", str(value or "")), deterministic=True)
    con.execute("PRAGMA query_only=ON")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
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
          notes TEXT DEFAULT '', updated_at TEXT, updated_by TEXT
        );
        CREATE TABLE IF NOT EXISTS framework_officers (
          framework_id TEXT PRIMARY KEY REFERENCES frameworks(id),
          officer TEXT NOT NULL, marketplace_url TEXT DEFAULT '',
          source TEXT DEFAULT 'Оголошення', synced_at TEXT NOT NULL
        );
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
          internal_decision TEXT DEFAULT '', review_notes TEXT DEFAULT '', protocol_number TEXT DEFAULT '',
          protocol_date TEXT DEFAULT '', reviewed_at TEXT DEFAULT '', updated_at TEXT NOT NULL, updated_by TEXT DEFAULT 'УО'
        );
        CREATE TABLE IF NOT EXISTS remarks_catalog (
          id INTEGER PRIMARY KEY AUTOINCREMENT, point TEXT NOT NULL, text TEXT NOT NULL,
          tag TEXT DEFAULT '', category TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
          updated_at TEXT NOT NULL
        );
        """)
        if con.execute("SELECT COUNT(*) FROM remarks_catalog").fetchone()[0] == 0:
            con.executemany("INSERT INTO remarks_catalog(point,text,tag,category,active,updated_at) VALUES (?,?,?,?,1,?)",
                            [(point, text, tag, "", now_iso()) for point, text, tag in DEFAULT_REMARKS])
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
        officer_columns = {row[1] for row in con.execute("PRAGMA table_info(framework_officers)")}
        if "marketplace_url" not in officer_columns:
            con.execute("ALTER TABLE framework_officers ADD COLUMN marketplace_url TEXT DEFAULT ''")
        violation_columns = {row[1] for row in con.execute("PRAGMA table_info(violation_reports)")}
        if "authority_code" not in violation_columns:
            con.execute("ALTER TABLE violation_reports ADD COLUMN authority_code TEXT DEFAULT ''")
        for row in con.execute("SELECT id,raw_json FROM violation_reports WHERE authority_code='' OR authority_code IS NULL").fetchall():
            try:
                authority_code = str((((json.loads(row[1] or "{}").get("authority") or {}).get("identifier") or {}).get("id") or ""))
                con.execute("UPDATE violation_reports SET authority_code=? WHERE id=?", (authority_code, row[0]))
            except (TypeError, ValueError, json.JSONDecodeError):
                pass


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
                con.execute("INSERT OR IGNORE INTO application_fields(submission_id) VALUES (?)", (item["id"],))
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
    if SYNC_STATE["running"]:
        return
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
        sync_incremental_worker()
    while True:
        target = next_hourly_run()
        SYNC_STATE["next_run_at"] = target.isoformat()
        while True:
            remaining = (target - datetime.now().astimezone()).total_seconds()
            if remaining <= 0:
                break
            time.sleep(min(30, remaining))
        sync_incremental_worker()


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
    where, args = ["1=1"], []
    if search:
        where.append("(INSTR(CASEFOLD(s.supplier_name), ?) > 0 OR INSTR(CASEFOLD(s.supplier_code), ?) > 0 OR INSTR(CASEFOLD(f.pretty_id), ?) > 0 OR INSTR(CASEFOLD(f.dk_code), ?) > 0 OR INSTR(CASEFOLD(af.manager_name), ?) > 0)")
        args.extend([search.casefold()] * 5)
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
    if officer:
        where.append("fo.officer=?")
        args.append(officer)
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
        officers = con.execute(f"""SELECT COALESCE(NULLIF(fo.officer,''),'Не визначено') officer, COUNT(*) applications
          FROM submissions s JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN qualifications q ON q.id=s.qualification_id
          LEFT JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id WHERE {officer_clause}
          GROUP BY COALESCE(NULLIF(fo.officer,''),'Не визначено') ORDER BY applications DESC""", officer_args).fetchall()
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
        records = con.execute(f"""SELECT s.id,f.pretty_id,f.title,f.dk_code,f.status framework_status,
          s.supplier_name,s.supplier_code,s.date_published,s.documents_json,
          COALESCE(q.status,'pending') decision_status,q.documents_json decision_documents,
          (SELECT rc.status FROM registry_contracts rc WHERE rc.qualification_id=q.id ORDER BY rc.synced_at DESC LIMIT 1) registry_status,
          (SELECT rc.milestones_json FROM registry_contracts rc WHERE rc.qualification_id=q.id ORDER BY rc.synced_at DESC LIMIT 1) registry_milestones,
          af.protocol_number,af.protocol_date,af.publication_date,af.protocol_officer,
          af.protocol_remarks,af.protocol_decision,af.marketplace_decision,af.compliance_status,af.compliance_comments,
          af.generated_protocol_number,af.generated_protocol_date,af.generated_protocol_decision,af.protocol_generated_at,
          af.manager_name,af.manager_name_source,af.manager_name_source_submission_id,
          af.document_package,af.contract_details,af.authority_review,af.mvs_seal_review,
          af.document_check_status,af.document_check_summary,af.document_checked_at,af.notes,COALESCE(fo.marketplace_url,'') marketplace_url
          FROM submissions s JOIN frameworks f ON f.id=s.framework_id
          LEFT JOIN qualifications q ON q.id=s.qualification_id
          LEFT JOIN application_fields af ON af.submission_id=s.id
          LEFT JOIN framework_officers fo ON fo.framework_id=s.framework_id WHERE {clause}
          ORDER BY {order_by} {sort_direction}, s.id ASC LIMIT ? OFFSET ?""", (*args, size, (page - 1) * size)).fetchall()
        amcu_codes = {re.sub(r"\D", "", row[0] or "") for row in con.execute(
            "SELECT DISTINCT offender_code FROM amcu_registry WHERE offender_code<>''"
        )}
        nazk_names = {" ".join(re.sub(r"[’'`\-]+", " ", (row[0] or "").casefold()).split()) for row in con.execute(
            "SELECT DISTINCT full_name FROM nazk_registry WHERE full_name<>''"
        )}
        nazk_reviews = {row[0]: dict(row) for row in con.execute("SELECT * FROM supplier_nazk_reviews")}
    items = []
    for row in records:
        item = dict(row); item["decision"] = decision_label(item.pop("decision_status"))
        supplier_code = re.sub(r"\D", "", item.get("supplier_code") or "")
        manager_name = " ".join(re.sub(r"[’'`\-]+", " ", (item.get("manager_name") or "").casefold()).split())
        item["amcu_match"] = bool(supplier_code and supplier_code in amcu_codes)
        item["nazk_match"] = bool(manager_name and manager_name in nazk_names)
        review = nazk_reviews.get(supplier_code)
        item["nazk_review"] = review or {}
        item["nazk_review_result"] = (review or {}).get("result", "")
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
          COALESCE(af.protocol_officer,'') protocol_officer,
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
            if row["source_status"] == "unsuccessful":
                errors.append("Розбіжність: Рішення УО = Так, але в Prozorro заявку відхилено")
        elif row["protocol_decision"] == "reject":
            rejected += 1
            if row["source_status"] == "active":
                errors.append("Розбіжність: Рішення УО = Ні, але в Prozorro заявку допущено")
            if not row["document_package"]: errors.append("Не заповнено варіант підтвердження")
            if not row["protocol_remarks"]: errors.append("Не заповнено зауваження до протоколу")
        if number and row["protocol_number"] and row["protocol_number"] != number:
            errors.append(f"Заявку вже віднесено до протоколу № {row['protocol_number']}")
        if not row["compliance_status"]:
            errors.append("Не визначено погодження комплаєнс")
        elif row["compliance_status"] == "rejected":
            if row["protocol_decision"] == "admit":
                errors.append("Заборонена комбінація: Комплаєнс = Не погоджено, Рішення УО = Так")
            if not row["compliance_comments"]:
                errors.append("Не заповнено коментар комплаєнс")
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
    output_path = DATA_DIR / "protocols" / filename
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


def framework_analytics(params: dict) -> dict:
    """Paged, indexed analytics over agreements/tenders/bids from ProzorroBids."""
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
    if search:
        where.append("(LOWER(a.agreement_id) LIKE ? OR LOWER(COALESCE(a.cpv_code,'')) LIKE ?)")
        args.extend([f"%{search}%", f"%{search}%"])
    if status == "active":
        where.append("LOWER(COALESCE(a.source_status,''))='active'")
    elif status == "inactive":
        where.append("LOWER(COALESCE(a.source_status,'')) IN ('closed','complete','inactive','disabled')")
    elif status:
        where.append("a.source_status=?"); args.append(status)
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
            normalized_status = "active" if row["status"] == "active" else "inactive"
            if status and status not in {row["status"], normalized_status}:
                continue
            if date_from or date_to:
                continue
            local_only.append({"agreement_id": row["agreement_id"] or "", "cpv_code": row["dk_code"] or "",
                "source_status": row["status"] or "", "last_search_at": "", "search_total": 0,
                "tender_count": 0, "bids_count": 0, "buyer_count": 0, "expected_amount": 0,
                "first_tender": "", "last_tender": "", "supplier_count": 0,
                "framework": framework, "agreement_pending": True})
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
        if agreement is None: raise KeyError(agreement_id)
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
    for item in suppliers:
        code = re.sub(r"\D", "", str(item.get("supplier_id") or ""))
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


def bids_sync_status(force: bool = False) -> dict:
    """Operational status and coverage of the attached ProzorroBids store."""
    with BIDS_STATUS_LOCK:
        cached = BIDS_STATUS_CACHE.get("value")
        if cached is not None and not force and time.time() - float(BIDS_STATUS_CACHE.get("at") or 0) < 600:
            return {**cached, "update": dict(BIDS_UPDATE_STATE)}
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
    with BIDS_STATUS_LOCK:
        BIDS_STATUS_CACHE.update(at=time.time(), value=result)
    return result


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
        log_path = DATA_DIR / "bids_manual_update.log"
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n[{now_iso()}] update {date_from} — {today}\n")
            subprocess.run([sys.executable, str(BIDS_PROJECT_PATH / "main.py"), "update", "--from", date_from.isoformat(),
                            "--to", today.isoformat(), "--no-export"], cwd=BIDS_PROJECT_PATH,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
            BIDS_UPDATE_STATE["message"] = "Повторна перевірка активних закупівель…"
            subprocess.run([sys.executable, str(BIDS_PROJECT_PATH / "main.py"), "refresh-active"], cwd=BIDS_PROJECT_PATH,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        BIDS_UPDATE_STATE["message"] = "Оновлення Bids завершено"
    except Exception as exc:
        BIDS_UPDATE_STATE.update(message=f"Помилка оновлення Bids: {exc}", error=str(exc))
    finally:
        BIDS_UPDATE_STATE.update(running=False, updated_at=now_iso())
        with BIDS_STATUS_LOCK:
            BIDS_STATUS_CACHE.update(at=0.0, value=None)


def powerbi_export_status() -> dict:
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


def _google_oauth_client() -> dict | None:
    if not GOOGLE_OAUTH_CLIENT_PATH.is_file():
        return None
    data = json.loads(GOOGLE_OAUTH_CLIENT_PATH.read_text(encoding="utf-8"))
    return data.get("installed") or data.get("web")


def _google_oauth_token() -> dict | None:
    if not GOOGLE_OAUTH_TOKEN_PATH.is_file():
        return None
    try:
        return json.loads(GOOGLE_OAUTH_TOKEN_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def google_oauth_status() -> dict:
    client = _google_oauth_client()
    token = _google_oauth_token()
    return {"configured": bool(client), "authorized": bool(token and token.get("refresh_token")),
            "client_path": str(GOOGLE_OAUTH_CLIENT_PATH),
            "message": ("Google підключено для читання таблиць" if token and token.get("refresh_token") else
                        "Потрібно увійти через Google" if client else
                        "Потрібен OAuth Client ID для локального застосунку")}


def google_oauth_authorization_url() -> str:
    client = _google_oauth_client()
    if not client:
        raise FileNotFoundError(f"OAuth client file not found: {GOOGLE_OAUTH_CLIENT_PATH}")
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    redirect_uri = os.environ.get("PQM_GOOGLE_OAUTH_REDIRECT_URI", "http://127.0.0.1:8080/api/google-oauth/callback")
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
    items = [dict(row) for row in rows]
    for item in items:
        code = re.sub(r"\D", "", item.get("code") or "")
        profile = edr_profiles.get(code) or edr_profiles.get(item.get("code")) or {}
        item["edr_profile"] = profile
        item["last_registry_event"] = latest_registry_events.get(item.get("code"), {})
        item["amcu_match"] = bool(code and code in amcu_codes)
        item["nazk_match"] = item.get("code") in manager_matches
        item["nazk_manager_name"] = manager_matches.get(item.get("code"), "")
        review = nazk_reviews.get(item.get("code"))
        item["nazk_review"] = review or {}
        if review:
            current_manager = " ".join(re.sub(r"[’'`\-]+", " ", ((item.get("edr_profile") or {}).get("manager_name") or "").casefold()).split())
            review_manager = " ".join(re.sub(r"[’'`\-]+", " ", (review.get("manager_name") or "").casefold()).split())
            review_is_current = bool(current_manager and review_manager and current_manager == review_manager)
            item["nazk_review_is_current"] = review_is_current
            item["nazk_match"] = review_is_current and review.get("result") in {"підтверджено", "на запит", "можливо"}
            item["nazk_manager_name"] = review.get("manager_name") or item["nazk_manager_name"]
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
        nazk_review = con.execute("SELECT * FROM supplier_nazk_reviews WHERE DIGITS(supplier_code)=?", (code,)).fetchone()
        qualifications = [dict(row) for row in con.execute("""WITH ranked AS (
          SELECT rc.id,CASE WHEN rc.status='active' AND NOT (
              LOWER(COALESCE(f.status,''))='active' AND
              (COALESCE(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),'')=''
                OR date(substr(json_extract(f.raw_json,'$.qualificationPeriod.endDate'),1,10))>=date('now')))
            THEN 'expired' ELSE rc.status END status,COALESCE(NULLIF(f.pretty_id,''),f.id) framework_id,
            f.title framework_title,f.dk_code,COALESCE(fo.marketplace_url,'') marketplace_url,
            COALESCE(NULLIF(json_extract(rc.raw_json,'$.dateModified'),''),NULLIF(json_extract(rc.raw_json,'$.date'),''),rc.synced_at) event_date,
            ROW_NUMBER() OVER (PARTITION BY rc.framework_id ORDER BY
              COALESCE(NULLIF(json_extract(rc.raw_json,'$.dateModified'),''),NULLIF(json_extract(rc.raw_json,'$.date'),''),rc.synced_at) DESC) rn
          FROM registry_contracts rc LEFT JOIN frameworks f ON f.id=rc.framework_id
          LEFT JOIN framework_officers fo ON fo.framework_id=rc.framework_id
          WHERE DIGITS(rc.supplier_code)=?)
          SELECT id,status,framework_id,framework_title,dk_code,marketplace_url,event_date FROM ranked
          WHERE rn=1 ORDER BY event_date DESC LIMIT 200""", (code,))]
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
        violation_reports = [dict(row) for row in con.execute("""SELECT report_id,status,date_published,
          reason,description,decision_resolution,decision_description,decision_date,tender_pretty_id,
          contract_pretty_id,authority_name FROM violation_reports WHERE DIGITS(defendant_code)=?
          ORDER BY COALESCE(NULLIF(decision_date,''),date_published) DESC LIMIT 100""", (code,))]
    bids_summary = {"participations": 0, "wins": 0, "bids": 0, "amount": 0}
    procurements = []
    try:
        with bids_db() as con:
            row = con.execute("""SELECT COUNT(DISTINCT tender_id) participations,COUNT(*) bids,
              COALESCE(SUM(amount),0) amount FROM bids WHERE supplier_id=?""", (code,)).fetchone()
            wins = con.execute("""SELECT COUNT(DISTINCT tender_id) FROM awards
              WHERE supplier_id=? AND LOWER(COALESCE(status,''))='active'""", (code,)).fetchone()[0]
            bids_summary = {**dict(row), "wins": int(wins or 0)}
            procurements = [dict(row) for row in con.execute("""SELECT b.tender_id,MAX(t.title) title,
              MAX(COALESCE(t.tender_start,t.date_created,b.bid_date)) tender_date,MAX(t.status) status,
              MAX(t.buyer_name) buyer_name,COUNT(*) bids_count,MAX(b.amount) amount,MAX(b.currency) currency,
              MAX(CASE WHEN aw.supplier_id IS NOT NULL THEN 1 ELSE 0 END) won
              FROM bids b LEFT JOIN tenders t ON t.tender_id=b.tender_id
              LEFT JOIN awards aw ON aw.tender_id=b.tender_id AND aw.supplier_id=? AND LOWER(COALESCE(aw.status,''))='active'
              WHERE b.supplier_id=? GROUP BY b.tender_id ORDER BY tender_date DESC LIMIT 100""", (code, code))]
    except (FileNotFoundError, sqlite3.Error):
        pass
    current_manager = " ".join(re.sub(r"[’'`\-]+", " ", ((profile["manager_name"] if profile else "") or "").casefold()).split())
    review_manager = " ".join(re.sub(r"[’'`\-]+", " ", ((nazk_review["manager_name"] if nazk_review else "") or "").casefold()).split())
    nazk_review_data = dict(nazk_review) if nazk_review else {}
    if nazk_review_data:
        nazk_review_data["is_current_manager"] = bool(current_manager and review_manager and current_manager == review_manager)
    return {"code": code, "summary": dict(summary) if summary else {}, "edr_profile": dict(profile) if profile else {},
            "qualifications": qualifications, "bids_summary": bids_summary, "procurements": procurements,
            "amcu": amcu, "nazk": nazk, "nazk_review": nazk_review_data,
            "violation_reports": violation_reports}


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
    selected_indexes = {int(index) for index in selection if str(index).isdigit()}
    selected_categories = {category for categories in selection.values() for category in categories}
    files, downloaded, extracted_texts = [], {}, {}
    for index, (_, document) in enumerate(documents):
        if selected_indexes and index not in selected_indexes:
            continue
        title = document.get("title") or document.get("title_en") or f"Документ {index + 1}"
        item = {"index": index, "title": title, "source_title": document.get("title_en") or document.get("title_ru") or title, "format": document.get("format", ""), "url": document.get("url", ""), "document_type": document.get("documentType", "")}
        try:
            data = download_document(document)
            downloaded[index] = data
            item["downloaded"] = True
            item["size"] = len(data)
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
    main_signature_index = next((i for i in signature_indexes if re.match(r"^sign(?:\s|\(|\.|$)", file_by_index[i]["title"], re.I)), signature_indexes[0] if signature_indexes else None)
    signature = certificate_details(downloaded.get(main_signature_index, b"")) if main_signature_index is not None else {}
    supplier_code = row["supplier_code"] or ""
    supplier_name = row["supplier_name"] or ""
    manager_name = row["manager_name"] or ""
    code_match = bool(signature.get("code") and signature["code"] == supplier_code)
    org_norm, supplier_norm = normalized_value(signature.get("organization", "")), normalized_value(supplier_name)
    name_match = bool(org_norm and supplier_norm and (org_norm in supplier_norm or supplier_norm in org_norm))
    signer_norm, manager_norm = normalized_value(signature.get("signer", "")), normalized_value(manager_name)
    signer_match = bool(signer_norm and manager_norm and (signer_norm in manager_norm or manager_norm in signer_norm))
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
    checks = [
        {"key": "main_signature", "label": "Основний файл sign.p7s", "status": "ok" if main_signature_index is not None else "error", "detail": file_by_index[main_signature_index]["title"] if main_signature_index is not None else "Не знайдено"},
        {"key": "certificate", "label": "Сертифікат підписувача", "status": "ok" if signature.get("certificate_found") else "warning", "detail": "Реквізити сертифіката прочитано" if signature.get("certificate_found") else "Потрібна перевірка через ЦЗО"},
        {"key": "code", "label": "Код ЄДРПОУ / РНОКПП", "status": "ok" if code_match else "error" if signature.get("code") else "warning", "detail": f"{signature.get('code') or 'Не прочитано'} · очікується {supplier_code}"},
        {"key": "organization", "label": "Назва організації", "status": "ok" if name_match else "warning", "detail": signature.get("organization") or "Не прочитано"},
        {"key": "signer", "label": "Підписант", "status": "ok" if signer_match else "warning", "detail": signature.get("signer") or "Не прочитано"},
        {"key": "authority", "label": "Повноваження підписанта", "status": "warning" if not signature.get("signer") or (authority_required and row["authority_review"] != "approved") else "ok", "detail": "Спочатку визначте підписанта через перевірку КЕП" if not signature.get("signer") else "Потрібна ручна перевірка" if authority_required and row["authority_review"] != "approved" else "Підтверджено"},
        {"key": "mvs_extract", "label": "Витяг МВС", "status": "ok" if mvs_docs else "error", "detail": ", ".join(item["title"] for item in mvs_docs) or "Не знайдено"},
        {"key": "mvs_extract_type", "label": "Тип витягу МВС", "status": "ok" if mvs_extract["type"] == "full" else "error" if mvs_extract["type"] == "short" else "warning", "detail": "ПОВНИЙ" if mvs_extract["type"] == "full" else "СКОРОЧЕНИЙ — не відповідає вимозі" if mvs_extract["type"] == "short" else "Не вдалося визначити тип витягу"},
        {"key": "mvs_person", "label": "ПІБ у витягу МВС", "status": "ok" if mvs_extract["person_matches_manager"] else "error" if mvs_extract["person_name"] and manager_name else "warning", "detail": f"{mvs_extract['person_name'] or 'Не прочитано'} · керівник: {manager_name or 'не визначений'}"},
        {"key": "mvs_age", "label": "Строк дії витягу — 30 к.д.", "status": "ok" if mvs_extract["within_30_days"] else "error" if mvs_extract["age_days"] is not None else "warning", "detail": (f"{mvs_extract['age_days']} к.д. · {mvs_extract['issue_date']} → {mvs_extract['submitted_date']}" if mvs_extract["age_days"] is not None else "Не вдалося визначити дату витягу або подання документів")},
        {"key": "mvs_signature", "label": "Підпис до витягу МВС", "status": "warning" if any(pair["signature"] for pair in mvs_pairs) else "error", "detail": (next((pair["signature"] for pair in mvs_pairs if pair["signature"]), "Не знайдено") + (" · потрібна криптографічна перевірка" if any(pair["signature"] for pair in mvs_pairs) else ""))},
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
    return {
        "submission_id": submission_id, "supplier_name": supplier_name, "supplier_code": supplier_code,
        "pretty_id": row["pretty_id"], "manager_name": manager_name, "authority_review": row["authority_review"], "mvs_seal_review": row["mvs_seal_review"],
        "signature": signature, "mvs_seal": mvs_seal, "mvs_extract": mvs_extract, "checks": checks, "files": files, "mvs_pairs": mvs_pairs,
        "counts": counts, "ready": counts["error"] == 0 and counts["warning"] == 0,
        "official_verification_url": "https://czo.gov.ua/verify",
        "notice": "Реквізити сертифіката зчитано локально. Криптографічну чинність КЕП необхідно підтвердити через ЦЗО або сертифікований модуль.",
    }


def document_check_worker(job_id: str, submission_id: str, selection: dict | None = None) -> None:
    try:
        result = analyze_application_documents(submission_id, selection)
        if not result:
            raise ValueError("Заявку не знайдено")
        counts = result.get("counts") or {}
        check_status = "error" if counts.get("error") else "warning" if counts.get("warning") else "ok"
        summary = f"Перевірено: {counts.get('ok', 0)}; попереджень: {counts.get('warning', 0)}; помилок: {counts.get('error', 0)}"
        with db() as con:
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


AUTH_REALM = os.environ.get("PQM_AUTH_REALM", "PQM")

def _pbkdf2_hash(password: str, iterations: int = 310_000) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.urlsafe_b64encode(salt).decode().rstrip('=')}${base64.urlsafe_b64encode(digest).decode().rstrip('=')}"

def _pbkdf2_verify(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_b64 + "===")
        expected = base64.urlsafe_b64decode(digest_b64 + "===")
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, binascii.Error):
        return False

def auth_users() -> dict:
    raw = os.environ.get("PQM_USERS_JSON", "{}")
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}

def get_auth_user(handler) -> dict | None:
    header = handler.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None
    record = auth_users().get(username)
    if not isinstance(record, dict):
        return None
    password_hash = str(record.get("password_hash") or "")
    if not password_hash or not _pbkdf2_verify(password, password_hash):
        return None
    role = str(record.get("role") or "viewer")
    if role not in {"viewer", "officer", "admin"}:
        role = "viewer"
    return {"username": username, "name": str(record.get("name") or username), "role": role}

def auth_configured() -> bool:
    return bool(auth_users())


class Handler(BaseHTTPRequestHandler):
    server_version = "PQM/0.1"

    def require_auth(self, *, write=False, admin=False):
        if self.path.startswith("/api/health"):
            return {"username": "health", "name": "health", "role": "admin"}
        user = get_auth_user(self)
        if not user:
            self.send_response(401)
            self.send_header("WWW-Authenticate", f'Basic realm="{AUTH_REALM}", charset="UTF-8"')
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = json.dumps({"error": "Потрібна авторизація"}, ensure_ascii=False).encode()
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            return None
        if admin and user["role"] != "admin":
            self.send_json({"error": "Потрібна роль адміністратора"}, 403)
            return None
        if write and user["role"] == "viewer":
            self.send_json({"error": "Роль «Перегляд» не може змінювати дані"}, 403)
            return None
        return user

    def send_json(self, data, status=200):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def read_json(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")

    def do_GET(self):
        user = self.require_auth()
        if not user: return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/auth/me":
            return self.send_json({"authenticated": True, "user": user})
        if parsed.path == "/api/health":
            with db() as con:
                counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("frameworks", "submissions", "qualifications")}
            return self.send_json({"ok": True, "counts": counts, "sync": SYNC_STATE})
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
        if parsed.path == "/api/violation-reports":
            return self.send_json(list_violation_reports(urllib.parse.parse_qs(parsed.query)))
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
            protocols_dir = (DATA_DIR / "protocols").resolve()
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

    def do_POST(self):
        user = self.require_auth(write=True)
        if not user: return
        parsed = urllib.parse.urlparse(self.path)
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
        if parsed.path == "/api/sync":
            if SYNC_STATE["running"]: return self.send_json(SYNC_STATE, 409)
            framework_id = self.read_json().get("framework_id")
            if framework_id:
                threading.Thread(target=sync_worker, args=(framework_id,), daemon=True).start()
                return self.send_json({"started": True, "framework_id": framework_id}, 202)
            threading.Thread(target=sync_all_worker, daemon=True).start()
            return self.send_json({"started": True, "scope": "active_and_closed"}, 202)
        if parsed.path == "/api/violation-reports/sync":
            if VIOLATION_SYNC_STATE["running"]:
                return self.send_json(VIOLATION_SYNC_STATE, 409)
            threading.Thread(target=sync_violation_reports_worker, daemon=True).start()
            return self.send_json({"started": True}, 202)
        if parsed.path == "/api/bids-sync":
            if BIDS_UPDATE_STATE["running"]:
                return self.send_json(BIDS_UPDATE_STATE, 409)
            BIDS_UPDATE_STATE.update(running=True, message="Підготовка оновлення Bids…", started_at=now_iso(), error=None)
            threading.Thread(target=bids_update_worker, daemon=True).start()
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
            try:
                return self.send_json({"authorization_url": google_oauth_authorization_url()}, 200)
            except FileNotFoundError as exc:
                return self.send_json({"error": str(exc), "oauth": google_oauth_status()}, 409)
        if parsed.path == "/api/powerbi-export":
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
        if parsed.path == "/api/nazk-registry/refresh":
            threading.Thread(target=refresh_nazk, args=(DB_PATH,), daemon=True).start()
            return self.send_json({"started": True}, 202)
        if parsed.path == "/api/amcu-registry/refresh":
            threading.Thread(target=refresh_amcu, args=(DB_PATH,), daemon=True).start()
            return self.send_json({"started": True}, 202)
        if parsed.path == "/api/amcu-registry/upload":
            payload = self.read_json()
            try:
                raw = base64.b64decode(payload.get("content") or "", validate=True)
            except Exception:
                return self.send_json({"error": "Не вдалося прочитати Excel-файл"}, 400)
            threading.Thread(target=refresh_amcu, args=(DB_PATH, raw, str(payload.get("filename") or "АМКУ.xlsx")), daemon=True).start()
            return self.send_json({"started": True}, 202)
        return self.send_error(404)

    def do_PATCH(self):
        user = self.require_auth(write=True)
        if not user: return
        parsed = urllib.parse.urlparse(self.path)
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
        role = user["role"]; user_name = user["name"]
        if "protocol_officer" in payload and payload["protocol_officer"] not in PROTOCOL_OFFICERS | {""}:
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
              generated_protocol_number,generated_protocol_date,generated_protocol_decision,protocol_generated_at
              FROM application_fields WHERE submission_id=?""", (submission_id,)).fetchone()
            current_protocol_decision, current_compliance_status, current_marketplace_decision = (current_controls[0] or "", current_controls[1] or "", current_controls[2] or "")
            effective_protocol_decision = payload.get("protocol_decision", current_protocol_decision)
            effective_compliance_status = payload.get("compliance_status", current_compliance_status)
            if effective_protocol_decision and not effective_compliance_status:
                return self.send_json({"error": "Спочатку визначте рішення комплаєнс"}, 409)
            if "compliance_status" in payload and payload["compliance_status"] != current_compliance_status and current_protocol_decision:
                return self.send_json({"error": "Щоб змінити комплаєнс, спочатку встановіть Рішення УО «Не визначено»"}, 409)
            if "protocol_decision" in payload and payload["protocol_decision"] != current_protocol_decision and current_marketplace_decision:
                return self.send_json({"error": "Щоб змінити Рішення УО, спочатку скиньте дію на майданчику"}, 409)
            if effective_protocol_decision == "admit" and effective_compliance_status == "rejected":
                return self.send_json({"error": "Рішення УО «Так» неможливе, коли комплаєнс не погоджено"}, 409)
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
                    con.execute(f"UPDATE application_fields SET {field}=?,updated_at=?,updated_by=? WHERE submission_id=?", (new, now_iso(), user_name, submission_id))
                    if field == "manager_name":
                        con.execute("""UPDATE application_fields SET manager_name_source='manual',
                          manager_name_source_submission_id='' WHERE submission_id=?""", (submission_id,))
                    con.execute("INSERT INTO audit_log(submission_id,changed_at,changed_by,field_name,old_value,new_value) VALUES (?,?,?,?,?,?)", (submission_id, now_iso(), user, field, old, new))
                    if field in {"protocol_number", "protocol_date", "protocol_decision", "manager_name", "compliance_status", "compliance_comments", "protocol_remarks", "document_package"}:
                        con.execute("""UPDATE application_fields SET generated_protocol_number='',generated_protocol_date='',
                          generated_protocol_decision='',protocol_generated_at='' WHERE submission_id=?""", (submission_id,))
        return self.send_json({"saved": True})

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}")


def main():
    init_db()
    init_reference_tables(DB_PATH)

    # External sources must never delay availability of the local application.
    # Refresh the officers directory in a background thread after the HTTP
    # server has started listening.
    def refresh_officers_directory():
        try:
            result = sync_framework_officers()
            print(f"Оголошення: {result['matched']} відборів із закріпленою УО")
        except Exception as exc:
            print(f"Оголошення: використано локальний довідник ({exc})")

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "10000"))
    print(f"PQM 0.1: http://{host}:{port}")
    threading.Thread(target=refresh_officers_directory, daemon=True).start()
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
    threading.Thread(target=reference_scheduler, daemon=True).start()
    ExclusiveThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
