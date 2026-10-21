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
CAT_CONTRACT = ROOT / "test_sandbox_permanent_cat_integrity_variant.json"
CAT_CONTRACT_SHA256 = "8d6987a16dcefd471a142d3a5e18bb6e50d63f9589f2dd1f75fcdee546267a3c"
CAT_VARIANT_ID = "sandbox-permanent-cat-v1"
CAT_BASELINE = "20fe5a4c721ab60ae95ba44816b79d00a6e3df8d"
CAT_APPROVED_SCOPE = {
    "sandbox-only-permanent-cat-season-switch",
    "kyiv-season-transition-in-open-tab",
    "preserve-existing-personal-cat-preference",
    "season-independent-eye-tracking-and-blinking",
    "approved-no-hat-cat-asset",
}
CAT_PRODUCT_FILES = {
    "sandbox_runtime.py",
    "halloween_motion.js",
    "halloween_cat_season.js",
    "halloween_cat_season.css",
    "assets/pqm-cat-no-hat.png",
}
CAT_PROTECTED_FILES = {"app.js", "server.py"}
CAT_PROTECTED_SHA256 = {
    "app.js": "ed905909640e43cac001e5bce492aa5e43fdda40c798dcc22c7316aeaa44e9f6",
    "server.py": "8ad164eafb0caeefbd896a1584886bd24311634c416b64fe0cb10459f24236b9",
}
CAT_GUARDED_FILES = {
    "application_selection.js", "assets/halloween-witch-cat.webp",
    "assets/halloween-workqueue-dark.webp", "assets/halloween-workqueue-light.webp",
    "auth_access.py", "background_jobs.py", "bulk_application_save.js", "filters.css",
    "google_writer_execution.py", "halloween.css", "halloween.js", "halloween_motion.css",
    "halloween_season.js", "index.html", "metadata/template_legacy_tokens.v1.json",
    "modules.css", "operational_task_officers.js", "protocol_supplier_names.py",
    "registry_popovers.js", "sandbox_amcu.py", "sandbox_contrast.js", "sandbox_documents.py",
    "sandbox_theme.css", "scheduler_runtime.py", "styles.css", "template_catalog.py",
    "templates/violation_protocols/decline_individual_review.docx", "theme.css", "theme_ui.js",
    "ui_final.js", "ui_tz2.js", "violation_protocol_docx.py",
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
    cat_raw = CAT_CONTRACT.read_bytes()
    if sha256(cat_raw.replace(b"\r\n", b"\n")) != CAT_CONTRACT_SHA256:
        raise AssertionError("Змінено закріплений integrity-маніфест постійного котика")
    cat = json.loads(cat_raw.decode("utf-8"))
    if cat.get("variant_id") != CAT_VARIANT_ID or cat.get("baseline_sha") != CAT_BASELINE:
        raise AssertionError("Integrity-варіант котика не прив’язаний до погодженого Sandbox baseline")
    if cat.get("hash_format") != "Full-file SHA-256; text files use canonical LF line endings, binary assets are hashed byte-for-byte":
        raise AssertionError("Змінився формат повнофайлових SHA-256 integrity-варіанта котика")
    if set(cat.get("approved_scope", [])) != CAT_APPROVED_SCOPE:
        raise AssertionError("Змінився погоджений склад функціональності integrity-варіанта котика")
    if set(cat.get("product_files", {})) != CAT_PRODUCT_FILES:
        raise AssertionError("Змінився точний перелік product-файлів котика")
    if set(cat.get("protected_files", {})) != CAT_PROTECTED_FILES:
        raise AssertionError("Integrity-варіант котика має захищати app.js і server.py")
    if set(cat.get("guarded_files", {})) != CAT_GUARDED_FILES:
        raise AssertionError("Змінився точний перелік успадкованих захищених файлів котика")
    for path, digest in CAT_PROTECTED_SHA256.items():
        protected = cat["protected_files"][path]
        if protected.get("sha256") != digest or protected.get("halloween_normalized_sha256") != digest:
            raise AssertionError(f"Integrity-варіант котика змінює захищений файл {path}")
    if cat["protected_files"]["app.js"].get("personal_theme_normalized_sha256") != "9d0d22989de0875719b8da48e76665c2ffd446cd5797110ef6d7ea8b79b5325c":
        raise AssertionError("Integrity-варіант котика змінив захист персональної теми app.js")
    if cat["protected_files"]["server.py"].get("personal_theme_normalized_sha256") != "0a88cd31457a5aea015d76b4df48caffbdd2c3f1af04072197c2bdddfb6e5b60":
        raise AssertionError("Integrity-варіант котика змінив захист персональної теми server.py")
    contracts.append(cat)
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
