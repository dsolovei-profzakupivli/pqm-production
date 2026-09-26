import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

NAZK_URL = "https://corruptinfo.nazk.gov.ua/ep/1.0/corrupt/getAllData"
AMCU_PAGE = "https://amcu.gov.ua/napryami/oskarzhennya-publichnih-zakupivel/zvedeni-vidomosti-shchodo-spotvorennya-rezultativ-torgiv/zvedeni-vidomosti-shchodo-spotvorennia-rezultativ-torhiv-za-2026-rik"
AMCU_OPEN_DATA_ID = "1b98d102-0b52-44ba-882f-5f6a559ff81c"
AMCU_OPEN_DATA_ORG = "1f58f2d7-21b8-4d25-a4bf-9e7c31681b7e"
AMCU_OPEN_DATA_API = "https://data.gov.ua/api/3/action/package_show?id=2d328664-7603-4a6e-acf2-15afb4e47c15"
LOCK = threading.Lock()
START_LOCK = threading.Lock()
# The WEB server has one process. A persisted 'running' label is not a live
# worker: daemon threads disappear on restart. Never use that label as a lock.
AMCU_ACTIVE = set()
AMCU_ERRORS = {}
AMCU_LOCK = threading.Lock()
AMCU_WORKER_TIMEOUT = 300
AMCU_MAX_BYTES = 25 * 1024 * 1024
LOG = logging.getLogger("pqm.server")


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def init_reference_tables(db_path):
    with sqlite3.connect(db_path, timeout=60) as con:
        con.execute("PRAGMA busy_timeout=60000")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS reference_sync_state (
          source TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'idle', message TEXT DEFAULT '',
          updated_at TEXT DEFAULT '', source_updated_at TEXT DEFAULT '', row_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS nazk_registry (
          source_id TEXT PRIMARY KEY, punishment_type_code TEXT, punishment_type_name TEXT,
          entity_type_code TEXT, entity_type_name TEXT, last_name TEXT, first_name TEXT,
          patronymic TEXT, full_name TEXT, offense_id TEXT, offense_name TEXT, punishment TEXT,
          court_case_number TEXT, sentence_date TEXT, sentence_number TEXT, punishment_start TEXT,
          court_id TEXT, court_name TEXT, codex_articles TEXT, decision_url TEXT, raw_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_nazk_full_name ON nazk_registry(full_name);
        CREATE TABLE IF NOT EXISTS amcu_registry (
          row_key TEXT PRIMARY KEY, ordinal TEXT, division_no TEXT, sequence_no TEXT,
          decision_no TEXT, decision_date TEXT, authority TEXT, offender_name TEXT,
          offender_code TEXT, court_case_no TEXT, raw_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_amcu_code ON amcu_registry(offender_code);
        """)
        for source in ("nazk", "amcu"):
            con.execute("INSERT OR IGNORE INTO reference_sync_state(source) VALUES (?)", (source,))
        amcu_dates = [(normalized, key) for key, value in con.execute("SELECT row_key,decision_date FROM amcu_registry") if (normalized := _date_iso(value)) != (value or "")]
        nazk_dates = [(normalized, key) for key, value in con.execute("SELECT source_id,sentence_date FROM nazk_registry") if (normalized := _date_iso(value)) != (value or "")]
        if amcu_dates:
            con.executemany("UPDATE amcu_registry SET decision_date=? WHERE row_key=?", amcu_dates)
        if nazk_dates:
            con.executemany("UPDATE nazk_registry SET sentence_date=? WHERE source_id=?", nazk_dates)


def _state(db_path, source, status, message="", count=None, source_updated_at=None):
    fields = ["status=?", "message=?", "updated_at=?"]
    values = [status, message, _now()]
    if count is not None:
        fields.append("row_count=?"); values.append(int(count))
    if source_updated_at is not None:
        fields.append("source_updated_at=?"); values.append(source_updated_at)
    values.append(source)
    with sqlite3.connect(db_path) as con:
        con.execute(f"UPDATE reference_sync_state SET {','.join(fields)} WHERE source=?", values)


def reference_status(db_path):
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        result = {r["source"]: dict(r) for r in con.execute("SELECT * FROM reference_sync_state")}
    key = str(Path(db_path).resolve())
    state = result.get("amcu", {})
    if state.get("status") == "running" and key not in AMCU_ACTIVE:
        # Read-only projection: no registry/init/reconciliation side effects.
        state.update(status="error", interrupted=True, message=AMCU_ERRORS.get(key) or
                     "Попереднє оновлення перерване (процес завершився або сервер перезапущено). Повторіть оновлення. Збережений реєстр доступний.")
    return result


def _fetch(url, timeout=900, max_bytes=None):
    # The AMCU portal rejects non-browser user agents even for public files.
    # Keep the request read-only, but identify it like a normal browser and
    # provide the public portal as referer for its static-object downloads.
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.7",
        "Referer": "https://amcu.gov.ua/",
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read() if max_bytes is None else response.read(max_bytes + 1)
        if max_bytes is not None and len(raw) > max_bytes:
            raise ValueError("Файл АМКУ перевищує дозволений розмір 25 МБ")
        return raw


def refresh_nazk(db_path, on_complete=None, on_error=None):
    if not LOCK.acquire(blocking=False):
        if on_error:
            on_error("НАЗК: інше оновлення вже виконується")
        return
    succeeded = False
    failure = ""
    target_attested = False
    try:
        if os.environ.get('PQM_SANDBOX') == '1':
            import sandbox_runtime
            sandbox_runtime.attest_internal_target(db_path)
            if not sandbox_runtime.nazk_read_enabled():
                raise RuntimeError('STOP: SANDBOX NAZK read is disabled')
        target_attested = True
        _state(db_path, "nazk", "running", "Завантаження реєстру НАЗК")
        raw = (sandbox_runtime.fetch_nazk_bytes(NAZK_URL)
               if os.environ.get('PQM_SANDBOX') == '1' else _fetch(NAZK_URL))
        payload = json.loads(raw.decode("utf-8-sig"))
        items = payload if isinstance(payload, list) else payload.get("data", payload.get("items", []))
        if not isinstance(items, list) or not items:
            raise ValueError("Порожній або некоректний реєстр НАЗК; збережені дані не змінено")
        rows = []
        source_ids = set()
        for i, item in enumerate(items):
            if not isinstance(item, dict) or item.get("id") is None or not str(item["id"]).strip():
                raise ValueError("НАЗК: запис без explicit source ID; оновлення скасовано")
            source_id = str(item["id"]).strip()
            if source_id in source_ids:
                raise ValueError("НАЗК: duplicate source ID; оновлення скасовано")
            source_ids.add(source_id)
            pt = item.get("punishmentType") or {}; et = item.get("entityType") or {}
            names = [item.get("indLastNameOnOffenseMoment"), item.get("indFirstNameOnOffenseMoment"), item.get("indPatronymicOnOffenseMoment")]
            full_name = " ".join(str(x).strip() for x in names if x and str(x).strip()).upper()
            sentence = str(item.get("sentenceNumber") or "").strip()
            decision_url = f"https://reyestr.court.gov.ua/Review/{sentence}" if sentence.isdigit() else ""
            articles = item.get("codexArticles")
            if not isinstance(articles, str): articles = json.dumps(articles, ensure_ascii=False) if articles is not None else ""
            rows.append((source_id, str(pt.get("code") or ""), str(pt.get("name") or ""), str(et.get("code") or ""), str(et.get("name") or ""),
                *(str(x or "").strip() for x in names), full_name, str(item.get("offenseId") or ""), str(item.get("offenseName") or ""), str(item.get("punishment") or ""),
                str(item.get("courtCaseNumber") or ""), _date_iso(item.get("sentenceDate")), sentence, _date_iso(item.get("punishmentStart")), str(item.get("courtId") or ""),
                str(item.get("courtName") or ""), articles, decision_url, json.dumps(item, ensure_ascii=False)))
        with sqlite3.connect(db_path) as con:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("BEGIN IMMEDIATE")
            con.execute("PRAGMA defer_foreign_keys=ON")
            # Legacy schemas fail closed if a linked source vanishes. The
            # explicit evidence-FK migration allows disappearance without
            # deleting historical links or presenting old rows as current.
            con.execute("DELETE FROM nazk_registry")
            con.executemany("INSERT INTO nazk_registry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            if con.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("НАЗК: FK-перевірка не пройдена; збережені дані не змінено")
        _state(db_path, "nazk", "ok", "Оновлено", len(rows), _now())
        succeeded = True
    except Exception as exc:
        failure = str(exc) or type(exc).__name__
        if target_attested:
            _state(db_path, "nazk", "error", str(exc))
    finally:
        LOCK.release()
        if succeeded and on_complete:
            on_complete()
        elif not succeeded and on_error:
            on_error(failure or "НАЗК: оновлення не завершено")


def start_reference_refresh(db_path, source, raw=None, filename="", on_complete=None, on_error=None):
    """Claim a reference refresh and defer heavy work until after HTTP 202 is flushed."""
    if source not in {"nazk", "amcu"}:
        raise ValueError("Невідомий довідник")
    if os.environ.get('PQM_SANDBOX') == '1':
        import sandbox_runtime
        sandbox_runtime.attest_internal_target(db_path)
    if source == "amcu":
        return _start_amcu_refresh(db_path, raw, filename, on_complete)
    with START_LOCK:
        state = reference_status(db_path).get(source, {})
        if state.get("status") == "running" or LOCK.locked():
            return False
        _state(db_path, source, "running", "Підготовка фонового оновлення")
        target = refresh_nazk if source == "nazk" else refresh_amcu
        args = (db_path, on_complete, on_error) if source == "nazk" else (db_path, raw, filename)
        timer = threading.Timer(0.2, target, args=args)
        timer.daemon = True
        timer.start()
    return True


def _amcu_error(db_path, exc):
    message = str(exc) or type(exc).__name__
    AMCU_ERRORS[str(Path(db_path).resolve())] = message
    LOG.error("AMCU refresh failed: %s", message)
    try:
        _state(db_path, "amcu", "error", message)
    except sqlite3.Error:
        # Even a failed status write must not leave the UI polling forever.
        LOG.exception("AMCU terminal status could not be persisted")


def _start_amcu_refresh(db_path, raw, filename, on_complete=None):
    if os.environ.get('PQM_SANDBOX') == '1':
        import sandbox_runtime
        sandbox_runtime.attest_internal_target(db_path)
    key = str(Path(db_path).resolve())
    with START_LOCK:
        # Reserve before scheduling, including the 202 response delay. AMCU
        # must not acquire/release the unrelated NAZK workflow's lock.
        if key in AMCU_ACTIVE or not AMCU_LOCK.acquire(blocking=False):
            return False
        AMCU_ACTIVE.add(key)
        AMCU_ERRORS.pop(key, None)
        try:
            _state(db_path, "amcu", "running", "Підготовка фонового оновлення")
            timer = threading.Timer(0.2, refresh_amcu, args=(db_path, raw, filename),
                                    kwargs={"_claimed": True, "on_complete": on_complete})
            timer.daemon = True
            timer.start()
        except Exception as exc:
            _amcu_error(db_path, exc)
            AMCU_ACTIVE.discard(key)
            AMCU_LOCK.release()
            raise
    return True


def _cell(value):
    if value is None: return ""
    if isinstance(value, datetime): return value.date().isoformat()
    return str(value).strip()


def _date_iso(value):
    """Normalize registry dates to YYYY-MM-DD for reliable SQLite ordering."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value).strip()
    if not text:
        return ""
    for pattern in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y.%m.%d"):
        try:
            return datetime.strptime(text[:10], pattern).date().isoformat()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text


def _date_display(value):
    normalized = _date_iso(value)
    try:
        return datetime.strptime(normalized, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return normalized


def _find_col(headers, *needles):
    for idx, value in enumerate(headers):
        low = _cell(value).lower().replace("’", "'")
        if all(n in low for n in needles): return idx
    return None


def parse_amcu_xlsx(raw):
    from openpyxl import load_workbook
    import io
    import zipfile
    if len(raw) > AMCU_MAX_BYTES:
        raise ValueError("Файл АМКУ перевищує дозволений розмір 25 МБ")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) > 5000 or sum(item.file_size for item in members) > 128 * 1024 * 1024:
            raise ValueError("Завеликий розпакований файл АМКУ")
    wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    best = None
    try:
        for ws in wb.worksheets:
            values = list(ws.iter_rows(values_only=True))
            for pos, row in enumerate(values[:20]):
                headers = list(row)
                code_col = _find_col(headers, "ідентифікаційн")
                if code_col is None:
                    # data.gov.ua uses a machine header followed by Ukrainian
                    # labels. Accept only the tested, unambiguous exact alias.
                    aliases = [i for i, h in enumerate(headers) if _cell(h).casefold() == "єдрпоу"]
                    if len(aliases) == 1:
                        code_col = aliases[0]
                name_col = _find_col(headers, "суб'єкт", "поруш")
                if code_col is not None and name_col is not None:
                    best = (values, pos, headers, code_col, name_col); break
            if best: break
    finally:
        wb.close()
    if not best: raise ValueError("У файлі АМКУ не знайдено очікувані заголовки")
    values, pos, headers, code_col, name_col = best
    date_col = _find_col(headers, "дата", "рішення")
    no_col = _find_col(headers, "№", "рішення")
    authority_col = _find_col(headers, "орган", "прийняв")
    court_col = _find_col(headers, "судов", "справ")
    rows_by_key = {}
    for n, row in enumerate(values[pos + 1:], 1):
        code = re.sub(r"\D", "", _cell(row[code_col] if code_col < len(row) else ""))
        name = _cell(row[name_col] if name_col < len(row) else "").upper()
        if not code and not name: continue
        # Official workbooks occasionally repeat column numbers or other
        # service rows inside the data range.  Ukrainian identifiers have at
        # least eight digits; foreign identifiers may be longer.
        if name.isdigit() or (code and len(code) < 8):
            continue
        get = lambda col: _cell(row[col]) if col is not None and col < len(row) else ""
        raw_row = {_cell(headers[i]) or f"column_{i+1}": _cell(v) for i, v in enumerate(row) if v is not None}
        decision_no = get(no_col)
        decision_date = _date_iso(row[date_col] if date_col is not None and date_col < len(row) else "")
        key = "|".join((code, decision_no, decision_date, name))
        # The official workbook can contain repeated entries.  Keep one row
        # for an identical business key so a duplicate cannot abort the whole
        # registry refresh with a UNIQUE constraint error.
        rows_by_key[key] = (key, str(n), "", "", decision_no, decision_date, get(authority_col), name, code, get(court_col), json.dumps(raw_row, ensure_ascii=False))
    return list(rows_by_key.values())


def discover_amcu_xlsx():
    html = _fetch(AMCU_PAGE, 90).decode("utf-8", "ignore")
    links = re.findall(r'href=["\']([^"\']+\.(?:xlsx|xls)(?:\?[^"\']*)?)["\']', html, re.I)
    if not links: raise ValueError("На сторінці АМКУ не знайдено Excel-файл")
    return urllib.parse.urljoin(AMCU_PAGE, links[0])


def _amcu_public_get(url, max_bytes):
    """Bounded public GET, no credentials or automatic cross-host redirects."""
    parsed = urllib.parse.urlsplit(url)
    allowed = (url == AMCU_OPEN_DATA_API or
               (parsed.hostname == "data.gov.ua" and
                parsed.path.startswith(f"/dataset/{AMCU_OPEN_DATA_ID}/resource/") and
                "/download/" in parsed.path))
    if not allowed or parsed.scheme != "https" or parsed.username or parsed.password or parsed.port or parsed.fragment:
        raise ValueError("Непідтверджене джерело файлу АМКУ")
    if url != AMCU_OPEN_DATA_API and parsed.query:
        raise ValueError("Неочікувані параметри URL файлу АМКУ")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    request = urllib.request.Request(url, headers={
        "User-Agent": "PQM-WEB-TEST/1.0 (+https://pqm-production-1.onrender.com/)",
        "Accept": "application/json,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*;q=0.5",
    })
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
        raw = response.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("Відповідь джерела АМКУ перевищує дозволений розмір")
    return raw


def discover_amcu_open_data():
    """Discover the newest dated public XLSX in the verified AMCU dataset."""
    payload = json.loads(_amcu_public_get(AMCU_OPEN_DATA_API, 4 * 1024 * 1024))
    data = payload.get("result") or {}
    if (payload.get("success") is not True or data.get("id") != AMCU_OPEN_DATA_ID or
            data.get("private") is not False or data.get("state") != "active" or
            (data.get("organization") or {}).get("id") != AMCU_OPEN_DATA_ORG):
        raise ValueError("data.gov.ua не підтвердив публічний набір АМКУ")
    candidates = []
    for item in data.get("resources", []):
        if item.get("format", "").upper() != "XLSX" or item.get("state") != "active":
            continue
        resource_id = item.get("id", "")
        url = item.get("url", "")
        prefix = f"https://data.gov.ua/dataset/{AMCU_OPEN_DATA_ID}/resource/{resource_id}/download/"
        if (not re.fullmatch(r"[a-f0-9-]{36}", resource_id) or not url.startswith(prefix) or
                item.get("package_id") != AMCU_OPEN_DATA_ID or not url.lower().endswith(".xlsx")):
            continue
        text = " ".join(str(item.get(k) or "") for k in ("name", "description"))
        dates = set()
        for day, month, year in re.findall(r"\b(\d{2})[.\-](\d{2})[.\-](20\d{2})\b", text):
            try:
                dates.add(datetime(int(year), int(month), int(day)).date())
            except ValueError:
                pass
        if len(dates) == 1:
            published = dates.pop()
            if published <= datetime.now().date():
                candidates.append((published, str(item.get("last_modified") or item.get("created") or ""), url))
    if not candidates:
        raise ValueError("У публічному наборі АМКУ немає однозначно датованого XLSX")
    return max(candidates)[2]


def _download_amcu_rows():
    try:
        source = discover_amcu_xlsx()
        return source, parse_amcu_xlsx(_fetch(source, 60, AMCU_MAX_BYTES))
    except (urllib.error.URLError, TimeoutError, ValueError) as primary_error:
        # This is a separate publication by AMCU, not a proxy around its portal.
        LOG.warning("AMCU primary source unavailable: %s; checking official open data", primary_error)
        try:
            source = discover_amcu_open_data()
            return source, parse_amcu_xlsx(_amcu_public_get(source, AMCU_MAX_BYTES))
        except (urllib.error.URLError, TimeoutError, ValueError) as fallback_error:
            raise ValueError(f"Основне джерело АМКУ: {str(primary_error)[:180]}. "
                             f"Резервне data.gov.ua: {str(fallback_error)[:180]}. "
                             "Попередній реєстр збережено.") from fallback_error


def _validate_amcu_replacement(con, rows):
    """Validate inside the write transaction before deleting any current row."""
    if not rows:
        raise ValueError("АМКУ повернув порожній реєстр; попередні дані збережено")
    dates = []
    for row in rows:
        if len(row) != 11 or not all(str(row[i] or "").strip() for i in (0, 4, 5, 7, 8)):
            raise ValueError("Файл АМКУ містить неповні записи; попередній реєстр збережено")
        try:
            date = datetime.strptime(row[5], "%Y-%m-%d").date()
        except (ValueError, TypeError) as exc:
            raise ValueError("Некоректна дата рішення АМКУ; попередній реєстр збережено") from exc
        if date > datetime.now().date():
            raise ValueError("Майбутня дата рішення АМКУ; попередній реєстр збережено")
        dates.append(date.isoformat())
    new_max = max(dates)
    count, current_max = con.execute("SELECT COUNT(*),MAX(decision_date) FROM amcu_registry").fetchone()
    if current_max and new_max < current_max:
        raise ValueError(f"Джерело АМКУ застаріле: останнє рішення {_date_display(new_max)}, "
                         f"у PQM вже є {_date_display(current_max)}. Попередній реєстр збережено.")
    # A normal rolling three-year register can shrink; a large drop needs review.
    if count >= 100 and len({r[0] for r in rows}) < count * 0.9:
        raise ValueError("Новий реєстр АМКУ менший більш ніж на 10%; потрібна перевірка повноти. Попередній реєстр збережено.")


def _amcu_rows_bounded(raw=None, filename=""):
    """Fetch/parse in a killable child; socket timeouts alone are not a deadline.

    The child never opens a database or imports the application. A hung network
    response or workbook parser cannot retain the refresh lock indefinitely.
    """
    if os.environ.get('PQM_SANDBOX') == '1':
        import sandbox_amcu
        if raw is not None:
            return sandbox_amcu.upload_rows(raw, filename)
        return sandbox_amcu.download_rows()
    if raw is not None and len(raw) > AMCU_MAX_BYTES:
        raise ValueError("Файл АМКУ перевищує дозволений розмір 25 МБ")
    try:
        result = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
                                 "--amcu-worker", "upload" if raw is not None else "download", filename],
                                input=raw or b"", capture_output=True, timeout=AMCU_WORKER_TIMEOUT,
                                check=False)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("Оновлення АМКУ перевищило 5 хвилин. Спробуйте пізніше; попередній реєстр збережено.") from exc
    if result.returncode:
        raise RuntimeError("Не вдалося завантажити/прочитати АМКУ: " + result.stderr.decode("utf-8", "replace")[-500:])
    payload = json.loads(result.stdout)
    if not payload.get("rows"):
        raise ValueError("АМКУ повернув порожній реєстр; попередні дані збережено")
    return payload["source"], payload["rows"]


def refresh_amcu(db_path, raw=None, filename="", *, _claimed=False, on_complete=None):
    if not _claimed and not AMCU_LOCK.acquire(blocking=False): return
    key = str(Path(db_path).resolve())
    AMCU_ACTIVE.add(key)
    AMCU_ERRORS.pop(key, None)
    started = time.monotonic()
    finished = False
    target_attested = False
    try:
        if os.environ.get('PQM_SANDBOX') == '1':
            import sandbox_runtime
            sandbox_runtime.attest_internal_target(db_path)
        target_attested = True
        _state(db_path, "amcu", "running", "Завантаження реєстру АМКУ")
        LOG.info("AMCU refresh started")
        source, rows = _amcu_rows_bounded(raw, filename)
        fetched = time.monotonic()
        with sqlite3.connect(db_path, timeout=30) as con:
            con.execute("BEGIN IMMEDIATE")
            _validate_amcu_replacement(con, rows)
            con.execute("DELETE FROM amcu_registry")
            con.executemany("INSERT OR REPLACE INTO amcu_registry VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
            count = con.execute("SELECT COUNT(*) FROM amcu_registry").fetchone()[0]
            con.execute("""UPDATE reference_sync_state SET status='ok',message=?,row_count=?,
                        updated_at=?,source_updated_at=? WHERE source='amcu'""",
                        (f"Оновлено з {source}", count, _now(), _now()))
        if on_complete:
            on_complete()
        finished = True
        LOG.info("AMCU refresh completed rows=%d fetch_parse_seconds=%.3f db_seconds=%.3f total_seconds=%.3f",
                 count, fetched-started, time.monotonic()-fetched, time.monotonic()-started)
    except Exception as exc:
        if target_attested:
            _amcu_error(db_path, exc)
        else:
            AMCU_ERRORS[key] = str(exc)
            LOG.error('AMCU target attestation failed before DB write: %s', type(exc).__name__)
        finished = True
    finally:
        if not finished and target_attested:
            _amcu_error(db_path, "Фоновий процес АМКУ перервано; повторіть оновлення")
        AMCU_ACTIVE.discard(key)
        AMCU_LOCK.release()


def list_registry(db_path, source, query):
    q = (query.get("search", [""])[0] or "").strip()
    page = max(1, int(query.get("page", [1])[0])); size = min(200, max(1, int(query.get("size", [50])[0])))
    table = "nazk_registry" if source == "nazk" else "amcu_registry"
    cols = "full_name,offense_name,court_case_number,sentence_date,punishment_start,decision_url" if source == "nazk" else """offender_name,offender_code,decision_no,decision_date,authority,court_case_no,
      EXISTS(SELECT 1 FROM supplier_registry_summary srs WHERE srs.supplier_code=amcu_registry.offender_code) in_supplier_registry,
      COALESCE((SELECT MAX(srs.active_count) FROM supplier_registry_summary srs WHERE srs.supplier_code=amcu_registry.offender_code),0) active_qualifications,
      EXISTS(SELECT 1 FROM submissions s WHERE s.supplier_code=amcu_registry.offender_code) has_application"""
    conditions, params = [], []
    normalized_q = " ".join(re.sub(r"[’'`\-]+", " ", q.casefold()).split())
    if normalized_q:
        fields = ["full_name", "offense_name", "court_case_number"] if source == "nazk" else ["offender_name", "offender_code", "decision_no"]
        conditions.append("(" + " OR ".join(f"INSTR(NORMALIZE_SEARCH({f}),?)>0" for f in fields) + ")")
        params.extend([normalized_q] * len(fields))
    if source == "amcu":
        date_from = (query.get("date_from", [""])[0] or "").strip()
        date_to = (query.get("date_to", [""])[0] or "").strip()
        authority = (query.get("authority", [""])[0] or "").strip()
        supplier_scope = (query.get("supplier_scope", [""])[0] or "").strip()
        if date_from: conditions.append("decision_date>=?"); params.append(date_from)
        if date_to: conditions.append("decision_date<=?"); params.append(date_to)
        if authority: conditions.append("authority=?"); params.append(authority)
        if supplier_scope == "registered":
            conditions.append("EXISTS(SELECT 1 FROM supplier_registry_summary srs WHERE srs.supplier_code=amcu_registry.offender_code)")
        elif supplier_scope == "applicant":
            conditions.append("EXISTS(SELECT 1 FROM submissions s WHERE s.supplier_code=amcu_registry.offender_code)")
    else:
        date_from = (query.get("date_from", [""])[0] or "").strip()
        date_to = (query.get("date_to", [""])[0] or "").strip()
        court = (query.get("court", [""])[0] or "").strip()
        if date_from: conditions.append("sentence_date>=?"); params.append(date_from)
        if date_to: conditions.append("sentence_date<=?"); params.append(date_to)
        if court: conditions.append("court_name=?"); params.append(court)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    order_by = "decision_date DESC, offender_name, row_key" if source == "amcu" else "sentence_date DESC, full_name, source_id"
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        con.create_function("NORMALIZE_SEARCH", 1, lambda value: " ".join(
            re.sub(r"[’'`\-]+", " ", str(value or "").casefold()).split()
        ))
        total = con.execute(f"SELECT COUNT(*) FROM {table}{where}", params).fetchone()[0]
        rows = [dict(r) for r in con.execute(f"SELECT {cols} FROM {table}{where} ORDER BY {order_by} LIMIT ? OFFSET ?", params + [size, (page-1)*size])]
        date_field = "sentence_date" if source == "nazk" else "decision_date"
        for row in rows:
            row[date_field] = _date_display(row.get(date_field))
            if source == "nazk":
                row["punishment_start"] = _date_display(row.get("punishment_start"))
        authorities = [r[0] for r in con.execute("SELECT DISTINCT authority FROM amcu_registry WHERE authority<>'' ORDER BY authority")] if source == "amcu" else []
        courts = [r[0] for r in con.execute("SELECT DISTINCT court_name FROM nazk_registry WHERE court_name<>'' ORDER BY court_name")] if source == "nazk" else []
    return {"items": rows, "total": total, "page": page, "pages": max(1, (total+size-1)//size), "size": size, "authorities": authorities, "courts": courts}


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "--amcu-worker":
    try:
        uploaded = sys.argv[2] == "upload"
        if uploaded:
            source = sys.argv[3] or "АМКУ.xlsx"
            raw = sys.stdin.buffer.read(AMCU_MAX_BYTES + 1)
            if len(raw) > AMCU_MAX_BYTES:
                raise ValueError("Файл АМКУ перевищує дозволений розмір 25 МБ")
            rows = parse_amcu_xlsx(raw)
        else:
            source, rows = _download_amcu_rows()
        print(json.dumps({"source": source, "rows": rows}, ensure_ascii=False))
    except Exception as exc:
        detail = str(exc)
        if isinstance(exc, urllib.error.HTTPError) and exc.code == 403:
            detail = "Сайт АМКУ відмовив у доступі (HTTP 403). Спробуйте пізніше або завантажте офіційний Excel через кнопку «Завантажити Excel». Попередній реєстр збережено."
        print(detail, file=sys.stderr)
        sys.exit(1)
