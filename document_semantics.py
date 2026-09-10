"""Shared document presentation semantics; no database or renderer dependencies."""
import re


def supplier_code_semantics(code: str) -> dict[str, str]:
    """One normalization/result for the approved document-only business rule.

    Preserve the legacy non-ten-digit fallback. This does not update registry
    identity or replace input validation; it selects document presentation.
    """
    normalized_code = re.sub(r"\D", "", code)
    label, entity_type = ("РНОКПП", "individual_entrepreneur") if len(normalized_code) == 10 else ("код ЄДРПОУ", "legal_entity")
    return {"normalized_code": normalized_code, "code_label": label, "entity_type": entity_type}


def supplier_code_label(code: str) -> str:
    return supplier_code_semantics(code)["code_label"]


def supplier_entity_type(code: str) -> str:
    return supplier_code_semantics(code)["entity_type"]
