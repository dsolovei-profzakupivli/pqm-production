"""Bounded, read-only experience search. No database, scheduler or app imports.

Version 3 remains a historical contract. Version 4 uses one canonical validator
for both CPV discovery and supplier-only discovery; incomplete is never none.
"""
from __future__ import annotations

import email.utils
import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

VERSION = 4
SEARCH_URL = "https://prozorro.gov.ua/api/search/contracts"
PORTAL = "https://prozorro.gov.ua/api/contracts/"
RAW = "https://public-api.prozorro.gov.ua/api/2.5/"
PARTIAL_MESSAGE = "Пошук виконано частково. Відсутність договорів не підтверджена"
_SLOT = threading.Semaphore(1)
_RATE_LOCK = threading.Lock()
_LAST_REQUEST = 0.0


@dataclass(frozen=True)
class Limits:
    requests: int = 64
    seconds: float = 120.0
    pages: int = 30
    fallback_pages: int = 20
    attempts: int = 3
    candidates: int = 3
    interval: float = 0.4
    response_bytes: int = 8 * 1024 * 1024


class Interrupted(Exception):
    pass


class EvidenceError(Exception):
    pass


def identifier(value):
    # NFC and edge whitespace only. No case folding, transliteration or digits().
    return unicodedata.normalize("NFC", str(value or "")).strip()


def moment(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def cpv(value):
    value = str(value or "").strip()
    return value if re.fullmatch(r"[0-9]{8}-[0-9]", value) else ""


def supplier_matches(expected, parties, scheme=None):
    matches = [(p.get("identifier") or {}) for p in parties or []
               if isinstance(p, dict) and identifier((p.get("identifier") or {}).get("id")) == identifier(expected)]
    if scheme:
        return any(x.get("scheme") == scheme for x in matches)
    schemes = {x.get("scheme") for x in matches if x.get("scheme")}
    return bool(matches and len(schemes) == 1)


def require_supplier_evidence(expected, parties, scheme=None):
    """Missing identity is incomplete evidence, not a conclusive mismatch."""
    if not isinstance(parties, list) or not parties:
        raise EvidenceError("supplier_evidence_missing")
    for party in parties:
        value = party.get("identifier") if isinstance(party, dict) else None
        if not isinstance(value, dict) or not identifier(value.get("id")) or not value.get("scheme"):
            raise EvidenceError("supplier_evidence_incomplete")
    matching_schemes = {p["identifier"]["scheme"] for p in parties
                        if identifier(p["identifier"]["id"]) == identifier(expected)}
    if scheme is None and len(matching_schemes) > 1:
        raise EvidenceError("supplier_scheme_ambiguous")


def body(response):
    value = response.get("data", response) if isinstance(response, dict) else None
    if not isinstance(value, dict):
        raise EvidenceError("invalid_detail")
    return value


def termination_ok(value):
    return value is None or value in ("", [], {}) or isinstance(value, str) and not value.strip()


def canonical_candidate(detail, raw, tender, supplier, framework_cpv, cutoff, scheme=None):
    """Return (candidate, predicate); ambiguous evidence raises, never proves none."""
    for source in (detail, raw):
        if source.get("status") != "terminated":
            return None, "detail_status"
        if not termination_ok(source.get("terminationDetails")):
            return None, "termination_details"
        modified = moment(source.get("dateModified"))
        if modified is None:
            raise EvidenceError("date_parse")
        if modified > cutoff:
            return None, "date_modified_cutoff"
    if not raw.get("id") or raw.get("id") != detail.get("id") or raw.get("contractID") != detail.get("contractID"):
        raise EvidenceError("contract_identity")
    if raw.get("tender_id") != tender.get("id"):
        raise EvidenceError("tender_identity")
    require_supplier_evidence(supplier, raw.get("suppliers"), scheme)
    if not supplier_matches(supplier, raw.get("suppliers"), scheme):
        return None, "supplier_identifier"
    award = next((a for a in tender.get("awards", []) if a.get("id") == raw.get("awardID")), None)
    if not award:
        raise EvidenceError("contract_award_not_found")
    require_supplier_evidence(supplier, award.get("suppliers"), scheme)
    if not supplier_matches(supplier, award.get("suppliers"), scheme):
        return None, "award_supplier_identifier"
    contract_schemes = {(p.get("identifier") or {}).get("scheme") for p in raw.get("suppliers", [])
                        if identifier((p.get("identifier") or {}).get("id")) == identifier(supplier)}
    award_schemes = {(p.get("identifier") or {}).get("scheme") for p in award.get("suppliers", [])
                     if identifier((p.get("identifier") or {}).get("id")) == identifier(supplier)}
    if contract_schemes != award_schemes:
        raise EvidenceError("supplier_scheme_conflict")
    award_lots = award.get("relatedLots") or []
    if isinstance(award_lots, str):
        award_lots = [award_lots]
    award_lots = {str(x) for x in award_lots if x} | {str(award[k]) for k in ("lotID", "relatedLot") if award.get(k)}
    contract_items = raw.get("items") or []
    contract_lots = {str(x["relatedLot"]) for x in contract_items if x.get("relatedLot")}
    if len(award_lots) > 1 or len(contract_lots) > 1 or award_lots and contract_lots and award_lots != contract_lots:
        raise EvidenceError("ambiguous_lot")
    lots = award_lots or contract_lots
    tender_items = tender.get("items") or []
    tender_lots = {str(x.get("id")) for x in tender.get("lots", []) if x.get("id")}
    if not lots and len(tender_lots) > 1:
        ids = {x.get("id") for x in contract_items if x.get("id")}
        inferred = {str(x["relatedLot"]) for x in tender_items if x.get("id") in ids and x.get("relatedLot")}
        if len(inferred) != 1:
            raise EvidenceError("lot_unresolved")
        lots = inferred
    if lots and tender_lots and not lots.issubset(tender_lots):
        raise EvidenceError("lot_not_in_tender")
    lot = next(iter(lots), next(iter(tender_lots), "") if len(tender_lots) == 1 else "")
    scoped = [x for x in tender_items if not lot or x.get("relatedLot") == lot]
    # Contract items are canonical when old tenders lack scoped tender items.
    if not scoped:
        scoped = [x for x in contract_items if not x.get("relatedLot") or x.get("relatedLot") == lot]
    codes = sorted({cpv((x.get("classification") or {}).get("id")) for x in scoped} - {""})
    if not codes:
        raise EvidenceError("cpv_missing")
    matching = next((x for x in codes if x[:4] == framework_cpv[:4]), None)
    if not matching:
        return None, "cpv_unrelated"
    public_id = raw["contractID"]
    return {"id": raw["id"], "contract_id": public_id,
            "url": "https://prozorro.gov.ua/uk/contract/" + urllib.parse.quote(public_id, safe=""),
            "date_modified": detail["dateModified"], "date_signed": detail.get("dateSigned", ""),
            "buyer": (detail.get("buyer") or {}).get("name", ""), "lot_id": lot,
            "resolved_cpvs": codes, "resolved_cpv": matching,
            "cpv_match": "exact" if matching == framework_cpv else "cpv_prefix_4"}, "accepted"


def retry_after(value, now=None):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            when = email.utils.parsedate_to_datetime(value)
            return max(0.0, when.timestamp() - (time.time() if now is None else now))
        except (TypeError, ValueError, OverflowError):
            return 0.0


class Search:
    def __init__(self, *, transport=None, limits=Limits(), cancelled=None, clock=time.monotonic, sleep=time.sleep):
        self.transport = transport or self.http
        self.limits, self.cancelled, self.clock, self.sleep = limits, cancelled or (lambda: False), clock, sleep
        self.started, self.requests = clock(), 0
        self.cache, self.errors, self.rejected, self.retries = {}, [], {}, []
        self.stop_reason = ""

    def check(self):
        reason = "cancelled" if self.cancelled() else "time_limit" if self.clock() - self.started >= self.limits.seconds else ""
        if reason:
            self.stop_reason = reason
            raise Interrupted(reason)

    def pause(self, seconds):
        # Cooperative cancellation also during Retry-After/rate-limit sleeps.
        end = self.clock() + seconds
        while self.clock() < end:
            self.check()
            self.sleep(min(0.1, end - self.clock()))

    def http(self, url, payload, timeout):
        global _LAST_REQUEST
        with _RATE_LOCK:
            self.pause(max(0.0, self.limits.interval - (self.clock() - _LAST_REQUEST)))
            self.check()
            _LAST_REQUEST = self.clock()
        request = urllib.request.Request(url, data=json.dumps(payload).encode() if payload is not None else None,
                                         headers={"Content-Type": "application/json", "Accept": "application/json",
                                                  "User-Agent": "PQM-experience/4"})
        timeout = min(timeout, max(0.01, self.limits.seconds - (self.clock() - self.started)))
        with urllib.request.urlopen(request, timeout=timeout) as response:
            chunks, size = [], 0
            while True:
                self.check()
                sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                if sock is not None:
                    sock.settimeout(min(15.0, max(0.01, self.limits.seconds - (self.clock() - self.started))))
                chunk = response.read1(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > self.limits.response_bytes:
                    raise EvidenceError("response_too_large")
                chunks.append(chunk)
        return json.loads(b"".join(chunks))

    def get(self, url, payload=None):
        key = json.dumps([url, payload], sort_keys=True)
        if key in self.cache:
            return self.cache[key]
        for attempt in range(self.limits.attempts):
            self.check()
            if self.requests >= self.limits.requests:
                self.stop_reason = "request_limit"
                raise Interrupted(self.stop_reason)
            self.requests += 1
            try:
                result = self.transport(url, payload, min(15.0, self.limits.seconds - (self.clock() - self.started)))
                self.check()
                if not isinstance(result, dict):
                    raise EvidenceError("invalid_response")
                self.cache[key] = result
                return result
            except Interrupted:
                raise
            except Exception as exc:
                retryable = isinstance(exc, (TimeoutError, ConnectionError, urllib.error.URLError))
                delay = 0.5 * (2 ** attempt)
                if isinstance(exc, urllib.error.HTTPError):
                    retryable = exc.code == 429 or 500 <= exc.code <= 599
                    delay = max(delay, retry_after((exc.headers or {}).get("Retry-After")))
                if not retryable or attempt + 1 == self.limits.attempts:
                    raise
                self.retries.append({"type": type(exc).__name__, "http_status": getattr(exc, "code", None),
                                     "attempt": attempt + 1, "delay": delay})
                try:
                    self.pause(delay)
                except Interrupted:
                    self.errors.append({"type": type(exc).__name__, "reason": "retry_interrupted"})
                    raise

    def candidate(self, summary, supplier, framework, cutoff, mode, scheme):
        public_id = str(summary.get("contractID") or "")
        detail = body(self.get(PORTAL + urllib.parse.quote(public_id, safe="")))
        # Reject only conclusive status/date/termination evidence before more GETs.
        if detail.get("status") != "terminated":
            return None, "detail_status"
        if not termination_ok(detail.get("terminationDetails")):
            return None, "termination_details"
        modified = moment(detail.get("dateModified"))
        if modified and modified > cutoff:
            return None, "date_modified_cutoff"
        internal = str(detail.get("id") or "")
        if not internal:
            raise EvidenceError("contract_internal_id_missing")
        raw = body(self.get(RAW + "contracts/" + urllib.parse.quote(internal, safe="")))
        tender_id = str(raw.get("tender_id") or "")
        if not tender_id:
            raise EvidenceError("tender_missing")
        tender = body(self.get(RAW + "tenders/" + urllib.parse.quote(tender_id, safe="")))
        result, reason = canonical_candidate(detail, raw, tender, supplier, framework, cutoff, scheme)
        if result:
            result["discovery_mode"] = mode
        return result, reason

    def run(self, supplier, framework, submitted_at, *, scheme=None):
        supplier, framework, cutoff = identifier(supplier), cpv(framework), moment(submitted_at)
        candidates, inspected, page_signatures, observed_statuses = [], set(), set(), {}
        coverage = {"complete": False, "pages": 0, "routes": {}, "stop_reason": "", "snapshot_isolation": False}
        if not supplier or not framework or cutoff is None:
            return self.result("unavailable", candidates, coverage, "missing_input")
        try:
            catalog = json.loads(Path(__file__).with_name("experience_cpv_codes.json").read_text(encoding="utf-8"))
            codes = [x for x in catalog["codes"] if x[:4] == framework[:4]]
            if framework not in codes:
                raise EvidenceError("cpv_not_in_pinned_catalog")
            # One OR query for every full CPV in the agreed four-digit family.
            for mode, query in (("exact", [framework]), ("cpv_group", codes), ("fallback", None)):
                total, per_page, page, route_ids, anchor = None, None, 1, set(), None
                route = coverage["routes"][mode] = {"pages": 0, "complete": False, "total": None}
                while True:
                    self.check()
                    if mode == "exact" and page > 3:
                        # Spend the next request on the whole CPV family rather
                        # than walking the same narrow parent code indefinitely.
                        break
                    if coverage["pages"] >= self.limits.pages or mode == "fallback" and page > self.limits.fallback_pages:
                        self.stop_reason = "page_limit"
                        raise Interrupted(self.stop_reason)
                    payload = {"supplier": [supplier], "page": page}
                    if query:
                        payload["cpv"] = query
                    search = self.get(SEARCH_URL, payload)
                    rows = search.get("data")
                    current_total, current_size = search.get("total"), search.get("per_page")
                    if not isinstance(rows, list) or type(current_total) is not int or type(current_size) is not int or current_total < 0 or current_size <= 0:
                        raise EvidenceError("invalid_pagination")
                    if total is not None and (total != current_total or per_page != current_size):
                        self.stop_reason = "pagination_changed"
                        raise Interrupted(self.stop_reason)
                    total, per_page = current_total, current_size
                    route["total"] = total
                    coverage["pages"] += 1
                    route["pages"] += 1
                    expected = min(per_page, max(0, total - (page - 1) * per_page))
                    if len(rows) != expected or search.get("page", page) != page:
                        raise EvidenceError("incomplete_page")
                    ids = [x.get("contractID") for x in rows if isinstance(x, dict)]
                    if len(ids) != len(rows) or not all(ids) or len(set(ids)) != len(ids):
                        raise EvidenceError("invalid_page_identifiers")
                    signature = (mode, tuple(ids))
                    if rows and signature in page_signatures:
                        self.stop_reason = "pagination_cycle"
                        raise Interrupted(self.stop_reason)
                    page_signatures.add(signature)
                    if any(x in route_ids for x in ids):
                        self.stop_reason = "pagination_overlap"
                        raise Interrupted(self.stop_reason)
                    route_ids.update(ids)
                    if page == 1:
                        anchor = (total, per_page, tuple(ids))
                    for summary in rows:
                        public_id = summary["contractID"]
                        if public_id in observed_statuses and observed_statuses[public_id] != summary.get("status"):
                            self.stop_reason = "pagination_changed"
                            raise Interrupted(self.stop_reason)
                        observed_statuses[public_id] = summary.get("status")
                        if public_id in inspected:
                            continue
                        inspected.add(public_id)
                        if summary.get("status") not in {"active", "pending", "cancelled", "terminated"}:
                            raise EvidenceError("summary_status_missing_or_unknown")
                        if summary.get("status") != "terminated":
                            continue
                        try:
                            candidate, reason = self.candidate(summary, supplier, framework, cutoff, mode, scheme)
                            self.rejected[reason] = self.rejected.get(reason, 0) + 1
                            if candidate and candidate["id"] not in {x["id"] for x in candidates}:
                                candidates.append(candidate)
                        except Interrupted:
                            raise
                        except Exception as exc:
                            self.errors.append({"contract_id": public_id, "type": type(exc).__name__})
                        if len(candidates) >= self.limits.candidates:
                            self.stop_reason = "sufficient_candidates"
                            raise Interrupted(self.stop_reason)
                    if page * per_page >= total:
                        route["complete"] = True
                        break
                    page += 1
                if candidates:
                    break
            coverage["complete"] = bool(coverage["routes"].get("fallback", {}).get("complete") and not self.errors)
            if coverage["complete"] and not candidates:
                # Page-number search has no snapshot cursor. Recheck the boundary
                # rather than calling a moving/overlapping traversal complete.
                payload = {"supplier": [supplier], "page": 1}
                self.cache.pop(json.dumps([SEARCH_URL, payload], sort_keys=True), None)
                boundary = self.get(SEARCH_URL, payload)
                if (boundary.get("total"), boundary.get("per_page"),
                        tuple(x.get("contractID") for x in boundary.get("data", []))) != anchor:
                    coverage["complete"] = False
                    self.stop_reason = "pagination_changed"
                else:
                    coverage["boundary_rechecked"] = True
        except Interrupted:
            coverage["complete"] = False
        except Exception as exc:
            coverage["complete"] = False
            self.errors.append({"type": type(exc).__name__, "reason": str(exc)[:100]})
        coverage.update(stop_reason=self.stop_reason, inspected=len(inspected), rejected=self.rejected,
                        requests=self.requests, seconds=round(self.clock() - self.started, 3), errors=self.errors,
                        retries=self.retries,
                        cpv_group_complete=coverage["routes"].get("cpv_group", {}).get("complete", False))
        status = "found" if candidates else "unavailable" if self.errors else "none" if coverage["complete"] else "partial"
        result = self.result(status, candidates, coverage)
        result.update(supplier=supplier, supplier_scheme=scheme, cpv=framework, cutoff=cutoff.isoformat(),
                      cutoff_note="dateModified використано лише як технічний proxy cutoff")
        return result

    def result(self, status, candidates, coverage, reason=""):
        message = {"found": f"Знайдено договорів-кандидатів: {len(candidates)}",
                   "none": "Пошук завершено. Валідних договорів-кандидатів не знайдено",
                   "partial": PARTIAL_MESSAGE, "unavailable": "Технічна помилка пошуку Prozorro. Відсутність договорів не підтверджена"}[status]
        if status == "found" and not coverage.get("complete"):
            message += ". Перелік не є вичерпним"
        return {"status": status, "symbol": "+" if candidates else "…" if status == "partial" else "−",
                "message": message, "algorithm_version": VERSION, "candidates": candidates,
                "coverage": coverage, "reason": reason,
                "restart": {"mode": "replay_from_first_page", "reason": "Search API page numbers are not stable snapshot cursors"}}


def search(supplier, framework, submitted_at, *, cancelled=None, **kwargs):
    """One concurrent v4 search; queue waiting consumes the same time budget."""
    job = Search(cancelled=cancelled, **kwargs)
    acquired = False
    try:
        while not acquired:
            job.check()
            acquired = _SLOT.acquire(timeout=0.1)
        return job.run(supplier, framework, submitted_at)
    except Interrupted:
        return job.result("partial", [], {"complete": False, "stop_reason": job.stop_reason})
    finally:
        if acquired:
            _SLOT.release()
