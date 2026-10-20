"""Exact, baseline-bound integrity exception for the approved protocol work."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "test_sandbox_protocol_integrity_variant.json"
ADDITIONAL_CONTRACTS = (ROOT / "test_sandbox_protocol_integrity_variant_protocol-fixes-v2.json",)
ADDITIONAL_CONTRACT_SHA256 = {
    "test_sandbox_protocol_integrity_variant_protocol-fixes-v2.json":
        "5e3f40aef120ebe39fcc87d0cdf2b368dec3fe3f3e28aa5ff71ffb9dac3bd2be"
}
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


def load_contracts():
    """Load the immutable original exception plus separately pinned additions."""
    contracts = [load_contract()]
    for path in ADDITIONAL_CONTRACTS:
        raw = path.read_bytes()
        expected_contract_sha = ADDITIONAL_CONTRACT_SHA256.get(path.name)
        if not expected_contract_sha or sha256(raw.replace(b"\r\n", b"\n")) != expected_contract_sha:
            raise AssertionError("Змінено закріплений integrity-маніфест протоколів")
        contract = json.loads(raw.decode("utf-8"))
        if contract.get("baseline_sha") != "b2027e6d687bc4018a2720f10fae228ccff7b201":
            raise AssertionError("Integrity-варіант протоколів не прив’язаний до погодженого baseline")
        if contract.get("variant_id") != "sandbox-protocol-fixes-v2":
            raise AssertionError("Невідомий integrity-варіант протоколів")
        if contract.get("hash_format") != HASH_FORMAT:
            raise AssertionError("Змінився формат повнофайлових SHA-256 integrity-варіанта")
        if set(contract.get("product_files", {})) != {
            "app.js", "protocol_supplier_names.py", "styles.css", "violation_protocol_docx.py"
        }:
            raise AssertionError("Змінився точний перелік погоджених product-файлів")
        if set(contract.get("approved_scope", [])) != {
            "preserve_manual_document_review_state_without_discarding_unsaved_fields",
            "normalize_supplier_protocol_filename_presentation_only",
            "render_customer_unavailable_document_note_with_approved_formatting",
            "present_supplier_name_provenance_and_review_notes_confirmation",
        }:
            raise AssertionError("Змінився погоджений склад виправлень")
        if set(contract.get("protected_files", {})) != PROTECTED_FILES:
            raise AssertionError("Integrity-варіант має зберігати захист app.js і server.py")
        contracts.append(contract)
    return contracts


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical_content(relative, content):
    """Normalize checkout line endings, but never normalize binary templates."""
    if not relative.endswith((".docx", ".webp", ".png", ".jpg", ".jpeg", ".gif")):
        return content.replace(b"\r\n", b"\n")
    return content


def manifest_tree_matches(contract, root=ROOT):
    """Check every pinned file in one manifest against an arbitrary read-only tree."""
    for section in ("product_files", "guarded_files", "protected_files"):
        for relative, expected in contract.get(section, {}).items():
            try:
                content = (Path(root) / relative).read_bytes()
            except OSError:
                return False
            expected_sha = expected.get("sha256")
            if expected_sha is None:
                continue
            if sha256(canonical_content(relative, content)) != expected_sha:
                return False
    return True


def exact_variant_file_matches(path, content):
    """Accept only bytes belonging to one currently exact, complete variant."""
    relative = str(path).replace("\\", "/")
    digest = sha256(canonical_content(relative, content))
    for contract in load_contracts():
        expected = contract.get("product_files", {}).get(relative)
        if expected is None:
            expected = contract.get("guarded_files", {}).get(relative)
        if expected is None:
            expected = contract.get("protected_files", {}).get(relative)
        if expected and digest == expected["sha256"] and manifest_tree_matches(contract):
            return True
    return False


def exact_variant_tree_matches():
    """Require a complete exact match to one prior or newly approved variant."""
    return any(manifest_tree_matches(contract) for contract in load_contracts())


def protected_content_matches(path, content, actual_projection_sha256,
                              baseline_projection_sha256, projection_name):
    """Accept the immutable baseline digest or the complete pinned variant."""
    if actual_projection_sha256 == baseline_projection_sha256:
        return True
    if path not in PROTECTED_FILES or not exact_variant_file_matches(path, content):
        return False
    if not exact_variant_tree_matches():
        return False
    for contract in load_contracts():
        if not manifest_tree_matches(contract):
            continue
        expected = contract["protected_files"].get(path, {}).get(projection_name)
        if expected and expected == actual_projection_sha256:
            return True
    return False
