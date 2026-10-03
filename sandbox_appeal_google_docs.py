"""SANDBOX-only native Google Docs protocol preparation (no network side effects)."""
from __future__ import annotations

import re
import json
import urllib.request

from sandbox_google_docs_access import TEMPLATES, SANDBOX_FOLDER_ID

PLACEHOLDER = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
INVALID_NAME = re.compile(r"[\x00-\x1f/\\]")
DOCUMENT_MIME = "application/vnd.google-apps.document"


def scenario_contract(protocol_type: str, rejection_required: bool = False) -> dict:
    if protocol_type not in TEMPLATES:
        raise ValueError("Unsupported appeal decision type")
    return {"scenario_type": protocol_type,
            "rejection_required": bool(rejection_required),
            "document_type": "protocol_decision",
            "document_template_id": TEMPLATES[protocol_type],
            "required_fields": ("report_id", "protocol_number", "customer_short_name",
                                "supplier_short_name", "supplier_code")}


def document_name(protocol_type: str, values: dict) -> str:
    contract = scenario_contract(protocol_type)
    missing = [key for key in contract["required_fields"]
               if not str(values.get(key) or "").strip()]
    if missing:
        raise ValueError("Missing confirmed short name or document identity: " + ", ".join(missing))
    parts = {key: str(values[key]).strip() for key in contract["required_fields"]}
    if any(INVALID_NAME.search(part) for part in parts.values()):
        raise ValueError("Document name contains an unsafe character")
    decision = "П" if protocol_type == "warning" else "В"
    return (f"{parts['report_id']}_{parts['protocol_number']}_{decision}_"
            f"{parts['customer_short_name']}_{parts['supplier_short_name']} "
            f"({parts['supplier_code']})")


def normalize_placeholder_key(raw: str) -> str:
    return re.sub(r"\s+", "_", raw.strip())


def prepare_replacements(protocol_type: str, values: dict, source_text: str,
                         *, rejection_required: bool = False) -> dict:
    """Preflight every placeholder before the template is copied."""
    contract = scenario_contract(protocol_type, rejection_required)
    document_name(protocol_type, values)
    if rejection_required and not str(values.get("rejection_date") or "").strip():
        raise ValueError("Rejection date is required for this scenario")
    found = sorted({match.group(0) for match in PLACEHOLDER.finditer(source_text)})
    keys = {literal: normalize_placeholder_key(PLACEHOLDER.fullmatch(literal).group(1))
            for literal in found}
    if protocol_type == "decline_p49_3" and any(key == "rejection_date" for key in keys.values()):
        raise ValueError("The p49.3 template must not acquire a rejection-date field")
    missing_keys = sorted({key for key in keys.values() if key not in values})
    if missing_keys:
        raise ValueError("Template placeholders lack source values: " + ", ".join(missing_keys))
    replacements = {}
    for literal, key in keys.items():
        value = str(values.get(key) or "").strip()
        if key == "rejection_date" and not value and not rejection_required:
            value = "—"
        elif not value:
            value = "—"
        if value in {"null", "None", "undefined", "01.01.1900"}:
            raise ValueError("Invalid placeholder value: " + key)
        replacements[literal] = value
    return {"template_id": contract["document_template_id"],
            "destination_folder_id": SANDBOX_FOLDER_ID,
            "name": document_name(protocol_type, values),
            "replacements": replacements}


def replace_requests(replacements: dict) -> list[dict]:
    return [{"replaceAllText": {"containsText": {"text": literal, "matchCase": True},
                                 "replaceText": value}}
            for literal, value in sorted(replacements.items())]


def verify_rendered_text(text: str) -> None:
    if PLACEHOLDER.search(text) or any(value in text for value in ("null", "undefined", "01.01.1900")):
        raise RuntimeError("Generated Google Doc contains unresolved or invalid content")


def document_text(document: dict) -> str:
    """Read native text from every tab, including tables, headers and footers."""
    roots = document.get("tabs") or [document.get("body") or {}]
    text = []
    def walk(value):
        if isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, dict):
            if isinstance(value.get("textRun"), dict):
                text.append(str(value["textRun"].get("content") or ""))
            for key, child in value.items():
                if key != "textRun":
                    walk(child)
    walk(roots)
    return "".join(text)


def _google_json(opener, token: str, url: str, *, method="GET", body=None,
                 generated_document_id=None) -> dict:
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if raw is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=raw, headers=headers, method=method)
    with opener(request, timeout=60, generated_document_id=generated_document_id) as response:
        content = response.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024:
        raise RuntimeError("Google Docs response exceeded limit")
    return json.loads(content.decode("utf-8"))


def preflight_document(protocol_type: str, values: dict, token: str, opener,
                       *, rejection_required=False) -> dict:
    """Read the pristine native template and validate all inputs before copy."""
    template_id = scenario_contract(protocol_type, rejection_required)["document_template_id"]
    source_url = f"https://docs.googleapis.com/v1/documents/{template_id}?includeTabsContent=true"
    source = _google_json(opener, token, source_url)
    if source.get("documentId") != template_id or not source.get("revisionId"):
        raise RuntimeError("Source template identity or revision unavailable")
    prepared = prepare_replacements(protocol_type, values, document_text(source),
                                    rejection_required=rejection_required)
    prepared["source_revision_id"] = source["revisionId"]
    return prepared


def create_document(protocol_type: str, values: dict, token: str, opener,
                    on_copied, *, rejection_required=False, preflight=None) -> dict:
    """Single controlled copy; caller must run access-check and persist copy ID.

    An unknown result after Drive copy is never retried automatically.
    """
    prepared = preflight or preflight_document(protocol_type, values, token, opener,
                                                rejection_required=rejection_required)
    template_id = prepared["template_id"]
    source_url = f"https://docs.googleapis.com/v1/documents/{template_id}?includeTabsContent=true"
    copied = _google_json(opener, token,
        f"https://www.googleapis.com/drive/v3/files/{template_id}/copy?fields=id%2Cname%2CmimeType%2Cparents",
        method="POST", body={"name": prepared["name"],
                             "parents": [SANDBOX_FOLDER_ID]})
    generated_id = copied.get("id")
    if (not isinstance(generated_id, str) or generated_id in TEMPLATES.values()
            or copied.get("mimeType") != DOCUMENT_MIME
            or copied.get("parents") != [SANDBOX_FOLDER_ID]):
        raise RuntimeError("Google copy outcome uncertain; manual reconciliation required")
    on_copied(generated_id, prepared)
    update = _google_json(opener, token,
        f"https://docs.googleapis.com/v1/documents/{generated_id}:batchUpdate",
        method="POST", body={"requests": replace_requests(prepared["replacements"])},
        generated_document_id=generated_id)
    if len(update.get("replies") or []) != len(prepared["replacements"]):
        raise RuntimeError("Google Docs replacement outcome uncertain; manual reconciliation required")
    generated = _google_json(opener, token,
        f"https://docs.googleapis.com/v1/documents/{generated_id}?includeTabsContent=true",
        generated_document_id=generated_id)
    if generated.get("documentId") != generated_id:
        raise RuntimeError("Generated document identity mismatch")
    verify_rendered_text(document_text(generated))
    source_after = _google_json(opener, token, source_url)
    if source_after.get("revisionId") != prepared["source_revision_id"]:
        raise RuntimeError("Source template revision changed during generation")
    return {"document_id": generated_id,
            "document_url": f"https://docs.google.com/document/d/{generated_id}/edit",
            "name": prepared["name"], "source_template_id": template_id,
            "destination_folder_id": SANDBOX_FOLDER_ID,
            "placeholders_replaced": len(prepared["replacements"])}
