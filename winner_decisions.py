"""Evidence-bound historical winner decisions for a single violation report."""

from __future__ import annotations

from datetime import datetime
import re
from urllib.parse import quote


def _date(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except (TypeError, ValueError):
        return None


def _supplier_codes(award):
    return {re.sub(r"\D", "", str((item.get("identifier") or {}).get("id") or ""))
            for item in award.get("suppliers") or []}


def notice_document(award):
    notices = [document for document in award.get("documents") or []
               if document.get("documentType") == "notice"
               and _date(document.get("datePublished"))]
    return min(notices, key=lambda document: str(document["datePublished"]), default=None)


def electronic_protocol_url(tender_id, award_id, notice, *, decision):
    """Link an exact award's published electronic protocol, never a nearby award."""
    route = {"winner": "determining_winner_of_procurement",
             "rejection": "tender_rejection_protocol"}.get(decision)
    if not route or not re.fullmatch(r"[0-9a-f]{32}", str(tender_id or ""), re.I) \
            or not re.fullmatch(r"[0-9a-f]{32}", str(award_id or ""), re.I):
        return ""
    if not notice or str(notice.get("documentType") or notice.get("type") or "") != "notice" \
            or not str(notice.get("id") or ""):
        return ""
    published = str(notice.get("datePublished") or notice.get("date_published") or "")
    modified = str(notice.get("dateModified") or notice.get("date_modified") or published)
    try:
        parsed = datetime.fromisoformat(published.replace("Z", "+00:00"))
        modified_at = datetime.fromisoformat(modified.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None or modified_at.tzinfo is None:
        return ""
    award_url = ("https://public-api.prozorro.gov.ua/api/2.5/tenders/"
                 f"{tender_id}/awards/{award_id}")
    encoded_date = quote(quote(modified, safe=""), safe="")
    encoded_award = quote(quote(award_url, safe=""), safe="")
    return (f"https://prozorro.gov.ua/pdf/{route}?dateModified={encoded_date}"
            f"&url={encoded_award}")


def protocol_document(award):
    """An actual readable decision document on this award, never a signature."""
    documents = []
    for document in award.get("documents") or []:
        title = str(document.get("title") or "").casefold()
        url = str(document.get("url") or "")
        if (not url.startswith("https://") or title.endswith((".p7s", ".p7m"))
                or not (document.get("documentType") in {"rejectionProtocol", "evaluationReports"}
                        or any(word in title for word in ("протокол", "рішення", "protocol")))):
            continue
        documents.append(document)
    selected = max(documents, key=lambda document: str(document.get("datePublished") or ""), default=None)
    if not selected:
        return None
    return {"id": str(selected.get("id") or ""),
            "type": str(selected.get("documentType") or ""),
            "title": str(selected.get("title") or ""),
            "url": str(selected["url"])}


def relevant_awards(tender, report):
    supplier = re.sub(r"\D", "", str(report.get("defendant_code") or ""))
    matching = [award for award in tender.get("awards") or []
                if supplier and supplier in _supplier_codes(award)]
    lot = str(report.get("lot_id") or "").strip()
    if not lot and report.get("contract_id"):
        contract = next((item for item in tender.get("contracts") or []
                         if str(item.get("id") or "") == str(report["contract_id"])), None)
        linked = next((award for award in matching
                       if str(award.get("id") or "") == str((contract or {}).get("awardID") or "")), None)
        lot = str((linked or {}).get("lotID") or "")
    if lot:
        return [award for award in matching if str(award.get("lotID") or "") == lot]
    # A report without a lot identity must never borrow a decision from one of
    # several different lots awarded to the same supplier.
    if len({str(award.get("lotID") or "") for award in matching}) > 1:
        return []
    return matching


def historical_decision(tender, report, *, snapshot_at):
    """Return a date-precision decision only where an exact award notice proves it."""
    created_raw = report.get("date_created") or report.get("date_published")
    created = _date(created_raw)
    candidates = []
    for award in relevant_awards(tender, report):
        if award.get("status") not in {"active", "cancelled"}:
            continue
        if award.get("status") == "cancelled" and award.get("qualified") is not True:
            continue
        notice = notice_document(award)
        if not notice:
            continue
        decision_date = _date(notice.get("datePublished"))
        if award.get("status") == "cancelled":
            # A notice published at/after cancellation cannot prove the
            # earlier activation decision without a status revision history.
            cancellation_date = _date(award.get("date"))
            if not cancellation_date or decision_date > cancellation_date:
                continue
            if decision_date == cancellation_date and not _strictly_before(
                    notice.get("datePublished"), award.get("date")):
                continue
        if created and decision_date > created:
            continue
        try:
            published_at = datetime.fromisoformat(str(notice["datePublished"]).replace("Z", "+00:00"))
            report_at = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
            if published_at.tzinfo and report_at.tzinfo and published_at > report_at:
                continue
        except (TypeError, ValueError):
            pass
        candidates.append((decision_date, str(award.get("id") or ""), award, notice))
    if not candidates:
        return None
    decision_date, _, award, notice = max(candidates)
    supplier = re.sub(r"\D", "", str(report.get("defendant_code") or ""))
    return {
        "report_id": str(report.get("id") or report.get("report_id") or ""),
        "tender_id": str(report.get("tender_id") or ""),
        "award_id": str(award.get("id") or ""),
        "supplier_id": supplier,
        "lot_id": award.get("lotID") or None,
        "decision_date": decision_date,
        "decision_datetime": None,
        "precision": "date",
        "provenance": "award_notice_date_published_date_only",
        "snapshot_at": snapshot_at,
        "later_cancelled": award.get("status") == "cancelled",
        "evidence_document": {
            "id": str(notice.get("id") or ""),
            "type": "notice",
            "title": str(notice.get("title") or ""),
            "url": str(notice.get("url") or ""),
            "date_published": str(notice.get("datePublished") or ""),
            "date_modified": str(notice.get("dateModified") or ""),
        },
        "protocol_document": protocol_document(award),
    }


def current_winner_state(tender, report):
    awards = relevant_awards(tender, report)
    active = [award for award in awards if award.get("status") == "active"]
    current = max(active or awards, key=lambda award: str(award.get("date") or ""), default=None)
    return {
        "award_id": (current or {}).get("id"),
        "status": (current or {}).get("status"),
        "active_winner": bool(active),
    }


def relevant_rejection(tender, report):
    """Never bind a protocol to an arbitrary later/latest rejection award."""
    candidates = [award for award in relevant_awards(tender, report)
                  if award.get("status") == "unsuccessful" and award.get("qualified") is False]
    explicit = str(report.get("rejection_award_id") or "")
    if explicit:
        return next((award for award in candidates
                     if str(award.get("id") or "") == explicit), None)
    report_at_raw = report.get("date_created") or report.get("date_published")
    if report_at_raw:
        try:
            report_at = datetime.fromisoformat(str(report_at_raw).replace("Z", "+00:00"))
            candidates = [award for award in candidates
                          if not award.get("date") or _not_after(award["date"], report_at)]
        except (TypeError, ValueError):
            pass
    return candidates[0] if len(candidates) == 1 else None


def _not_after(value, boundary):
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if moment.date() > boundary.date():
            return False
        return not (moment.tzinfo and boundary.tzinfo and moment > boundary)
    except (TypeError, ValueError):
        return False


def _strictly_before(first, second):
    try:
        left = datetime.fromisoformat(str(first).replace("Z", "+00:00"))
        right = datetime.fromisoformat(str(second).replace("Z", "+00:00"))
        return bool(left.tzinfo and right.tzinfo and left < right)
    except (TypeError, ValueError):
        return False
