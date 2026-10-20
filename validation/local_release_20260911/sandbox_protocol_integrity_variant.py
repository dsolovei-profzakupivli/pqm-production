"""Exact, baseline-bound integrity exception for the approved protocol work."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "test_sandbox_protocol_integrity_variant.json"
BASELINE = "565a2fff45675b6b49feb90edf67e83aa2af4a7b"
VARIANT_ID = "sandbox-universal-decline-p49-3-v1"
APPROVED_SCOPE = {
    "explicit_individual_decline_protocol_choice",
    "current_review_notes_confirmation",
    "server_validation_of_individual_decline_type",
    "p49_reference_from_request_basis",
    "individual_protocol_docx_context",
    "p49_3_winner_date_exemption_only",
}
PRODUCT_FILES = {
    "app.js",
    "server.py",
    "template_catalog.py",
    "violation_protocol_docx.py",
    "metadata/template_legacy_tokens.v1.json",
    "templates/violation_protocols/decline_individual_review.docx",
}
TEXT_PRODUCT_FILES = PRODUCT_FILES - {
    "templates/violation_protocols/decline_individual_review.docx",
}
PROTECTED_FILES = {"app.js", "server.py"}
HASH_FORMAT = "Full-file SHA-256; text files use canonical LF line endings, DOCX is hashed byte-for-byte"


def load_contract():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("variant_id") != VARIANT_ID or contract.get("baseline_sha") != BASELINE:
        raise AssertionError("Integrity-варіант не прив’язаний до погодженого Sandbox baseline")
    if contract.get("hash_format") != HASH_FORMAT:
        raise AssertionError("Змінився формат повнофайлових SHA-256 integrity-варіанта")
    if set(contract.get("approved_scope", [])) != APPROVED_SCOPE:
        raise AssertionError("Змінився погоджений склад функціональності integrity-варіанта")
    if set(contract.get("product_files", {})) != PRODUCT_FILES:
        raise AssertionError("Змінився точний перелік product-файлів integrity-варіанта")
    if set(contract.get("protected_files", {})) != PROTECTED_FILES:
        raise AssertionError("Integrity-варіант має захищати лише app.js і server.py")
    return contract


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical_content(relative, content):
    """Normalize checkout line endings, but never normalize binary templates."""
    if relative in TEXT_PRODUCT_FILES:
        return content.replace(b"\r\n", b"\n")
    return content


def exact_variant_file_matches(path, content):
    """Accept only the explicitly pinned full-file candidate bytes."""
    relative = str(path).replace("\\", "/")
    expected = load_contract()["product_files"].get(relative)
    return bool(expected and sha256(canonical_content(relative, content)) == expected["sha256"])


def exact_variant_tree_matches():
    """Require every approved product file to match; no partial variant."""
    contract = load_contract()
    for relative, expected in contract["product_files"].items():
        try:
            content = (ROOT / relative).read_bytes()
        except OSError:
            return False
        if sha256(canonical_content(relative, content)) != expected["sha256"]:
            return False
    return True


def protected_content_matches(path, content, actual_projection_sha256,
                              baseline_projection_sha256, projection_name):
    """Accept the immutable baseline digest or the complete pinned variant."""
    if actual_projection_sha256 == baseline_projection_sha256:
        return True
    if path not in PROTECTED_FILES or not exact_variant_file_matches(path, content):
        return False
    if not exact_variant_tree_matches():
        return False
    expected = load_contract()["protected_files"][path].get(projection_name)
    return bool(expected and expected == actual_projection_sha256)
