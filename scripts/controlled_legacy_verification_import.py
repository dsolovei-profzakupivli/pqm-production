"""SANDBOX-only, controlled migration of Google I/L verification evidence.

The command-line entry point is PREVIEW ONLY. No command-line apply exists.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import urllib.parse
import urllib.request

_project_root = Path(__file__).resolve().parents[1]
if not (_project_root / "edr_sync_v2.py").is_file() and Path("/app/edr_sync_v2.py").is_file():
    _project_root = Path("/app")  # One-shot /tmp copy on the SANDBOX Render service.
sys.path.insert(0, str(_project_root))
import edr_sync_v2
import supplier_registry_integration


SANDBOX_SHEET_ID = "1lZtneKmCTvFcEL0erlJbegVzTTLNA-IKnjempn1G8Ww"
SANDBOX_DB = "/var/data/pqm_sandbox.sqlite3"
SOURCE = "legacy_google_registry"
TABS = ("ФОП", "ЮО")
HEADERS = (
    "Маркер актуальності", "Код ЄДРПОУ", "Найменування", "ПІБ для перевірки",
    "Статус в реєстрі (ЄДР)", "Статус (Prozorro)", "Реквізити рішення про припинення",
    "Дата останньої заявки", "Дата перевірки", "Дата запису", "Номер запису",
    "УО", "Примітки", "Повна назва з ЄДР", "Скорочена назва з ЄДР",
)
INVALID_OFFICER = {"-", "—", "не визначено", "не призначено", "невідомо", "n/a", "null"}
CONFIRMATION = "IMPORT MAX 10 LEGACY GOOGLE VERIFICATIONS TO PQM SANDBOX"


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _date(value):
    if value is None or str(value).strip() == "":
        return ""
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        try:
            return (date(1899, 12, 30) + timedelta(days=int(value))).isoformat()
        except (ValueError, OverflowError):
            return "!invalid"
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            return "!invalid"
    if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", text):
        try:
            return datetime.strptime(text, "%d.%m.%Y").date().isoformat()
        except ValueError:
            return "!invalid"
    return "!invalid"


def _officer(value):
    value = " ".join(str(value or "").split())
    return value if value and value.casefold() not in INVALID_OFFICER else ""


def _key(code, day, officer):
    return _digest({"identity": code, "date": day,
                    "officer": edr_sync_v2.normalize_person(officer), "source": SOURCE})


def _db_state(con, codes):
    projection = edr_sync_v2.current_verification_projections(con, codes)
    events = {code: [] for code in codes}
    for start in range(0, len(codes), 500):
        batch = codes[start:start + 500]
        placeholders = ",".join("?" for _ in batch)
        for row in con.execute("SELECT supplier_code,event_type,occurred_at,officer,source,snapshot_hash "
                               "FROM supplier_edr_verification_events WHERE supplier_code IN (" +
                               placeholders + ")", batch):
            events[row["supplier_code"]].append(dict(row))
    return projection, events


def build_preview(con, spreadsheet_id, tabs):
    if spreadsheet_id != SANDBOX_SHEET_ID:
        raise ValueError("SANDBOX_SPREADSHEET_MISMATCH")
    if set(tabs) != set(TABS):
        raise ValueError("TAB_CONTRACT_MISMATCH")
    google = {}
    invalid = Counter()
    source_state = []
    for tab in TABS:
        rows = tabs[tab]
        if not rows or tuple(rows[0][:15]) != HEADERS:
            raise ValueError("HEADER_CONTRACT_MISMATCH")
        for number, raw in enumerate(rows[1:], 2):
            row = list(raw) + [""] * max(0, 15 - len(raw))
            code = str(row[1] or "").strip()
            if not code:
                continue
            value = {"tab": tab, "row": number, "date": row[8], "officer": row[11],
                     "formula_date": row[15] if len(row) > 15 else "",
                     "formula_officer": row[16] if len(row) > 16 else ""}
            source_state.append((tab, number, code, row[8], row[11],
                                 value["formula_date"], value["formula_officer"]))
            google.setdefault(code, []).append(value)
    # Reuse exactly the full-registry routing and current verification projection.
    registry = supplier_registry_integration._build_full_registry(con)
    pqm = {}
    for item in registry["items"]:
        pqm.setdefault(str(item["supplier_code"]).strip(), []).append(item)
    codes = sorted(google)
    projection, events = _db_state(con, codes)
    candidates = []
    counts = Counter()
    state = []
    for code in codes:
        matches, items = google[code], pqm.get(code, [])
        if len(matches) != 1 or len(items) != 1:
            invalid["ambiguous_identity"] += 1
            continue
        row, item = matches[0], items[0]
        expected_tab = {"individual_entrepreneur": "ФОП", "legal_entity": "ЮО"}.get(item["entity_type"])
        if expected_tab != row["tab"]:
            invalid["unsupported_or_routing_mismatch"] += 1
            continue
        if row["formula_date"] or row["formula_officer"]:
            invalid["formula_date_or_officer"] += 1
            continue
        day, officer = _date(row["date"]), _officer(row["officer"])
        if day == "!invalid":
            invalid["invalid_date"] += 1
            continue
        if not day:
            continue
        if not officer:
            invalid["missing_officer"] += 1
            continue
        prior = projection[code]
        pqm_day = _date(prior["verification_date"])
        if pqm_day == "!invalid":
            invalid["invalid_pqm_date"] += 1
            continue
        equivalent = any(_date(e["occurred_at"]) == day and
                         edr_sync_v2.normalize_person(e["officer"]) == edr_sync_v2.normalize_person(officer)
                         for e in events[code])
        state.append((code, pqm_day, prior["verification_officer_raw"],
                      sorted((e["event_type"], e["occurred_at"], e["officer"],
                              e["source"], e["snapshot_hash"]) for e in events[code])))
        if equivalent:
            counts["already_imported_or_equivalent"] += 1
        elif not pqm_day or day > pqm_day:
            kind = "initial" if not pqm_day else "newer"
            counts["candidate_" + kind] += 1
            candidates.append({"code": code, "tab": row["tab"], "row": row["row"],
                               "date": day, "officer": officer, "kind": kind,
                               "key": _key(code, day, officer)})
        elif day == pqm_day:
            counts["same_date_excluded"] += 1
        else:
            counts["google_older_excluded"] += 1
    # Deterministic sample: one initial, then both tabs, then stable remaining order.
    candidates.sort(key=lambda x: (x["tab"], x["code"], x["date"]))
    selected = []
    for criterion in (lambda x: x["kind"] == "initial", lambda x: x["tab"] == "ФОП",
                      lambda x: x["tab"] == "ЮО"):
        found = next((x for x in candidates if x not in selected and criterion(x)), None)
        if found:
            selected.append(found)
    selected.extend(x for x in candidates if x not in selected and len(selected) < 10)
    selected = selected[:10]
    digest = _digest({"spreadsheet_id": spreadsheet_id, "source": sorted(source_state),
                      "pqm": sorted(state), "candidates": candidates, "selected": selected})
    output = {"dry_run": True, "source_spreadsheet_verified": True, "google_writes": 0,
              "db_writes": 0, "candidate_newer": counts["candidate_newer"],
              "candidate_initial": counts["candidate_initial"],
              "total_candidates": len(candidates), "already_imported_or_equivalent":
              counts["already_imported_or_equivalent"], "same_date_excluded":
              counts["same_date_excluded"], "google_older_excluded": counts["google_older_excluded"],
              "invalid_or_ambiguous": dict(invalid), "blocked": sum(invalid.values()),
              "planned_inserts": len(candidates), "selected_count": len(selected),
              "selected_by_tab": dict(Counter(x["tab"] for x in selected)),
              "selected_initial": sum(x["kind"] == "initial" for x in selected),
              "stale_since_previous_audit": (counts["candidate_newer"] != 8602 or
                                             counts["candidate_initial"] != 3),
              "scope_limit_exceeded": len(candidates) > 8605,
              "preview_digest": digest}
    return output, selected


def apply_controlled(con, source_loader, expected_digest, confirmation):
    """Not exposed by CLI. Caller must supply a fresh SANDBOX source reader."""
    if confirmation != CONFIRMATION or not expected_digest:
        raise ValueError("EXPLICIT_CONFIRMATION_REQUIRED")
    main_path = next((row[2] for row in con.execute("PRAGMA database_list") if row[1] == "main"), None)
    if main_path != SANDBOX_DB or con.execute("PRAGMA query_only").fetchone()[0]:
        raise ValueError("SANDBOX_WRITABLE_DB_REQUIRED")
    spreadsheet_id, tabs = source_loader()
    con.execute("BEGIN IMMEDIATE")
    try:
        preview, selected = build_preview(con, spreadsheet_id, tabs)
        if preview["preview_digest"] != expected_digest:
            raise ValueError("STALE_PREVIEW_OR_SOURCE")
        if preview["scope_limit_exceeded"]:
            raise ValueError("FIRST_IMPORT_SCOPE_EXCEEDED")
        if len(selected) > 10:
            raise ValueError("SAMPLE_LIMIT_EXCEEDED")
        codes = sorted({x["code"] for x in selected})
        def registry_state():
            return {item["supplier_code"]: (
                item.get("edr_status_current"), item.get("prozorro_status_google"),
                item.get("current_manager_name"))
                for item in supplier_registry_integration._build_full_registry(con)["items"]
                if item["supplier_code"] in codes}
        before_registry = registry_state()
        before = {c: tuple(tuple(row) for row in con.execute(
            "SELECT * FROM supplier_edr_profiles WHERE supplier_code=?", (c,))) for c in codes}
        inserted = []
        for item in selected:
            if con.execute("SELECT 1 FROM supplier_edr_verification_events WHERE supplier_code=? "
                           "AND event_type=? AND occurred_at=? AND source=? AND snapshot_hash=?",
                           (item["code"], SOURCE, item["date"], SOURCE, item["key"])).fetchone():
                raise ValueError("EQUIVALENT_EVENT_APPEARED")
            snapshot = _json({"verification_date": item["date"],
                              "verification_officer": item["officer"], "source": SOURCE})
            cursor = con.execute("""INSERT INTO supplier_edr_verification_events
              (supplier_code,event_type,occurred_at,officer,source,source_sheet,source_row,
               changed_fields,snapshot_hash,snapshot_json,created_at)
              VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
              (item["code"], SOURCE, item["date"], item["officer"], SOURCE,
               item["tab"], item["row"], '["verification_date","verification_officer"]',
               item["key"], snapshot, datetime.now(timezone.utc).isoformat()))
            if cursor.rowcount != 1:
                raise ValueError("INSERT_FAILED")
            inserted.append(item)
        for item in inserted:
            row = con.execute("SELECT occurred_at,officer,source,snapshot_hash FROM "
                              "supplier_edr_verification_events WHERE supplier_code=? AND "
                              "event_type=? AND snapshot_hash=?",
                              (item["code"], SOURCE, item["key"])).fetchone()
            if not row or tuple(row) != (item["date"], item["officer"], SOURCE, item["key"]):
                raise ValueError("AFTER_VERIFICATION_FAILED")
        projected = edr_sync_v2.current_verification_projections(con, codes)
        for item in inserted:
            current = projected[item["code"]]
            if (current["verification_date"] != item["date"] or
                edr_sync_v2.normalize_person(current["verification_officer_raw"]) !=
                    edr_sync_v2.normalize_person(item["officer"]) or
                current["selected_event"].get("source") != SOURCE):
                raise ValueError("PROJECTION_AFTER_VERIFICATION_FAILED")
        after = {c: tuple(tuple(row) for row in con.execute(
            "SELECT * FROM supplier_edr_profiles WHERE supplier_code=?", (c,))) for c in codes}
        if before != after:
            raise ValueError("PROFILE_CHANGED")
        if before_registry != registry_state():
            raise ValueError("STATUS_OR_MANAGER_CHANGED")
        if source_loader() != (spreadsheet_id, tabs):
            raise ValueError("GOOGLE_SOURCE_CHANGED")
        con.commit()
        return {"inserted": len(inserted), "verified": len(inserted)}
    except BaseException:
        con.rollback()
        raise


def open_read_only(path):
    if str(path) != SANDBOX_DB:
        raise ValueError("SANDBOX_DB_MISMATCH")
    con = sqlite3.connect("file:" + urllib.parse.quote(str(path), safe="/") + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    con.create_function("DIGITS", 1, lambda s: re.sub(r"\D", "", str(s or "")), deterministic=True)
    con.create_function("NORMALIZE_NAME", 1, lambda s: " ".join(re.sub(
        r"[’'`\-]+", " ", str(s or "").casefold()).split()), deterministic=True)
    return con


def load_sandbox_google():
    """Read exact SANDBOX sheet; never use the wide-sync spreadsheet default."""
    import server  # Existing OAuth reader only; do not call server.db/migrate/sync.
    result = {}
    for tab in TABS:
        rows = server._google_sheet_values(tab, spreadsheet_id=SANDBOX_SHEET_ID, columns="A:O")
        # B is read with formatted display to preserve literal leading-zero identities.
        display = server._google_sheet_values(tab, spreadsheet_id=SANDBOX_SHEET_ID, columns="B:B")
        if not rows or len(display) < len(rows):
            raise ValueError("INCOMPLETE_GOOGLE_READ")
        ranges = [f"'{tab}'!I1:I{len(rows)}", f"'{tab}'!L1:L{len(rows)}"]
        query = urllib.parse.urlencode([("ranges", item) for item in ranges] +
                                       [("valueRenderOption", "FORMULA")])
        url = ("https://sheets.googleapis.com/v4/spreadsheets/" + SANDBOX_SHEET_ID +
               "/values:batchGet?" + query)
        request = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + server._google_access_token(),
            "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:
            formula_ranges = json.loads(response.read().decode()).get("valueRanges", [])
        if len(formula_ranges) != 2:
            raise ValueError("INCOMPLETE_FORMULA_READ")
        for i, row in enumerate(rows):
            if i and len(row) > 1:
                row[1] = str((display[i] or [""])[0] or "")
                row.extend([""] * max(0, 17 - len(row)))
                for j, target in ((0, 15), (1, 16)):
                    formulas = formula_ranges[j].get("values", [])
                    value = (formulas[i] or [""])[0] if i < len(formulas) else ""
                    if isinstance(value, str) and value.startswith("="):
                        # FORMULA API cannot distinguish a literal leading '='.
                        # Reject this row conservatively; never import it automatically.
                        row[target] = value
        result[tab] = rows
    return SANDBOX_SHEET_ID, result


def main():
    if len(sys.argv) != 2 or sys.argv[1] != "--preview":
        raise SystemExit("Only --preview is exposed; controlled Apply is not a CLI command.")
    con = open_read_only(SANDBOX_DB)
    try:
        report, _ = build_preview(con, *load_sandbox_google())
        report.update(db_mode="ro", query_only=con.execute("PRAGMA query_only").fetchone()[0])
        print(_json(report))
    finally:
        con.close()


if __name__ == "__main__":
    main()
