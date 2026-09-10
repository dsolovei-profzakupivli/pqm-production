"""Controlled Ukrainian name declension for PQM document contexts.

Automatic genitive/accusative behaviour intentionally mirrors the approved
Google Apps Script ``ВІДМІНОК_УКР``.  Dative is override-only.
"""
from __future__ import annotations

import csv
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_OVERRIDES_PATH = ROOT / "config" / "declension_overrides.csv"
CASES = {"genitive": "Р", "accusative": "З", "dative": "Д"}
ENTITY_TYPES = {"legal_entity", "fop", "person", "other"}
LEGAL_MARKERS = ("ТОВАРИСТВО", "ПІДПРИЄМСТВО", "ТОВ ", "ПП ", "МКСП")
_QUOTE_TRANSLATION = str.maketrans({
    '"': '"', "'": "'", "“": '"', "”": '"', "„": '"', "‟": '"',
    "«": '"', "»": '"', "‹": '"', "›": '"',
})


@dataclass(frozen=True)
class DeclensionResult:
    value: str
    status: str
    source: str
    original: str
    entity_type: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def normalize_lookup(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().translate(_QUOTE_TRANSLATION)).casefold()


def normalize_document_name(value: str) -> str:
    """Normalize paired outer name quotes for document presentation only.

    Apostrophes inside a legal name are deliberately left untouched.  This
    function does not mutate source data and is intentionally separate from
    the more permissive normalization used for override lookup.
    """
    text = str(value or "").strip()
    # Only one unambiguous outer pair; nested/mixed quotes remain untouched.
    if text.count('"') != 2 or any(c in text for c in '«»“”„‟‹›'):
        return text
    return re.sub(r'"([^"\r\n]+)"', lambda match: f"«{match.group(1)}»", text)


class OverrideStore:
    def __init__(self, path: str | Path = DEFAULT_OVERRIDES_PATH):
        self.path = Path(path)
        self._signature: tuple[int, int] | None = None
        self._rows: dict[tuple[str, str], dict[str, str]] = {}
        self._lock = threading.Lock()

    def _current_signature(self) -> tuple[int, int] | None:
        try:
            stat = self.path.stat()
            return stat.st_mtime_ns, stat.st_size
        except FileNotFoundError:
            return None

    def _reload_if_needed(self) -> None:
        signature = self._current_signature()
        if signature == self._signature:
            return
        with self._lock:
            signature = self._current_signature()
            if signature == self._signature:
                return
            rows: dict[tuple[str, str], dict[str, str]] = {}
            if signature is not None:
                with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
                    for row in csv.DictReader(handle, delimiter=";"):
                        entity_type = str(row.get("entity_type") or "other").strip().casefold()
                        original = str(row.get("original") or "").strip()
                        if entity_type not in ENTITY_TYPES or not original:
                            continue
                        rows[(entity_type, normalize_lookup(original))] = {
                            key: str(row.get(key) or "").strip()
                            for key in ("genitive", "dative", "accusative", "comment")
                        }
            self._rows = rows
            self._signature = signature

    def form(self, original: str, entity_type: str, grammatical_case: str) -> str:
        self._reload_if_needed()
        key = normalize_lookup(original)
        row = self._rows.get((entity_type, key)) or self._rows.get(("other", key))
        return str((row or {}).get(grammatical_case) or "").strip()


DEFAULT_OVERRIDE_STORE = OverrideStore()


def infer_entity_type(original: str, identifier: str = "") -> str:
    upper = str(original or "").strip().upper()
    if "ФОП" in upper or "ФІЗИЧНА ОСОБА" in upper or "ПІДПРИЄМЕЦЬ" in upper:
        return "fop"
    if any(marker in upper for marker in LEGAL_MARKERS):
        return "legal_entity"
    digits = re.sub(r"\D", "", str(identifier or ""))
    if len(digits) == 8:
        return "legal_entity"
    if len(upper.split()) >= 2:
        return "person"
    return "other"


def _legal(original: str, grammatical_case: str) -> str | None:
    value = original.strip().upper()
    if not any(marker in value for marker in LEGAL_MARKERS):
        return None
    if grammatical_case == "accusative":
        return value
    if grammatical_case != "genitive":
        return None
    quoted = re.search(r'"[^"«»“”„‟‹›\r\n]+"|«[^"«»“”„‟‹›\r\n]+»', original)
    if any(c in original for c in '\"«»“”„‟‹›'):
        if not quoted or any(c in original[:quoted.start()]+original[quoted.end():] for c in '\"«»“”„‟‹›'):
            return None
        # Preserve the proper name exactly; inflect only the external legal form.
        value=original[:quoted.start()].upper()+'\x00'+original[quoted.end():].upper()
    result = (value.replace("ТОВАРИСТВО", "ТОВАРИСТВА")
                 .replace("ПІДПРИЄМСТВО", "ПІДПРИЄМСТВА")
                 .replace("КОМУНАЛЬНЕ", "КОМУНАЛЬНОГО")
                 .replace("ДЕРЖАВНЕ", "ДЕРЖАВНОГО")
                 .replace("ПРИВАТНЕ", "ПРИВАТНОГО"))
    return result.replace('\x00',quoted.group(0)) if quoted else result


def _person(original: str, grammatical_case: str, is_fop: bool) -> str | None:
    if grammatical_case not in {"genitive", "accusative"}:
        return None
    value = original.strip().upper()
    fop = ("ФОП" in value or "ФІЗИЧНА ОСОБА" in value or "ПІДПРИЄМЕЦЬ" in value) if is_fop else False
    name = re.sub(r"^ФОП\s+", "", value, flags=re.I)
    name = re.sub(r"^ФІЗИЧНА\s+ОСОБА\s*-\s*ПІДПРИЄМЕЦЬ\s+", "", name, flags=re.I)
    name = re.sub(r"^ФІЗИЧНА\s+ОСОБА\s+ПІДПРИЄМЕЦЬ\s+", "", name, flags=re.I).strip()
    parts = re.split(r"\s+", name)
    if len(parts) < 2:
        return None
    last, first = parts[0], parts[1]
    middle = parts[2] if len(parts) > 2 else ""
    female = any(middle.endswith(suffix) for suffix in ("НА", "НУ", "НІ", "ЇВНА"))
    if female:
        if grammatical_case == "genitive":
            if last.endswith("СЬКА"):
                last = re.sub(r"СЬКА$", "СЬКОЇ", last)
            elif last.endswith("ОВА"):
                last = re.sub(r"ОВА$", "ОВОЇ", last)
            elif last.endswith(("ИНА", "ІНА")):
                last = re.sub(r"ИНА$", "ИНОЇ", last)
                last = re.sub(r"ІНА$", "ІНОЇ", last)
            elif last.endswith(("А", "Я")):
                last = last[:-1] + ("И" if last.endswith("А") else "Ї")
            first = re.sub(r"ІЯ$", "ІЇ", first) if first.endswith("ІЯ") else re.sub(r"Я$", "Ї", re.sub(r"А$", "И", first))
            if middle:
                middle = re.sub(r"НА$", "НИ", middle)
        else:
            if last.endswith("СЬКА"):
                last = re.sub(r"СЬКА$", "СЬКУ", last)
            elif last.endswith("ОВА"):
                last = re.sub(r"ОВА$", "ОВУ", last)
            elif last.endswith(("ИНА", "ІНА")):
                last = re.sub(r"ИНА$", "ИНУ", last)
                last = re.sub(r"ІНА$", "ІНУ", last)
            elif last.endswith(("А", "Я")):
                last = last[:-1] + ("У" if last.endswith("А") else "Ю")
            first = re.sub(r"ІЯ$", "ІЮ", first) if first.endswith("ІЯ") else re.sub(r"Я$", "Ю", re.sub(r"А$", "У", first))
            if middle:
                middle = re.sub(r"НА$", "НУ", middle)
    else:
        if last.endswith(("ИЙ", "ІЙ")):
            last = last[:-2] + "ОГО"
        elif last.endswith(("ЕЙ", "АЙ", "ОЙ")):
            last = last[:-1] + "Я"
        elif last.endswith("ЕЦЬ"):
            last = last[:-3] + "ЦЯ"
        elif last.endswith("О"):
            last = last[:-1] + "А"
        elif last.endswith(("А", "Я")):
            last = last[:-1] + ("У" if grammatical_case == "accusative" else "И")
        elif last.endswith("Ь"):
            last = last[:-1] + "Я"
        elif not last.endswith(("ИХ", "Е", "І")):
            last += "А"
        if first == "МИКОЛА":
            first = "МИКОЛУ" if grammatical_case == "accusative" else "МИКОЛИ"
        elif first.endswith(("А", "Я")):
            ending = "У" if first.endswith("А") else "Ю"
            if grammatical_case == "genitive":
                ending = "И" if first.endswith("А") else "І"
            first = first[:-1] + ending
        elif first.endswith("ІЙ"):
            first = re.sub(r"ІЙ$", "ІЯ", first)
        elif first.endswith("Ь"):
            first = re.sub(r"Ь$", "Я", first)
        elif not first.endswith(("О", "Е")):
            first += "А"
        elif first.endswith("О"):
            first = first[:-1] + "А"
        if middle:
            middle = re.sub(r"ИЧ$", "ИЧА", middle)
    prefix = ""
    if fop:
        prefix = "ФІЗИЧНОЇ ОСОБИ-ПІДПРИЄМЦЯ " if grammatical_case == "genitive" else "ФІЗИЧНУ ОСОБУ-ПІДПРИЄМЦЯ "
    return (prefix + " ".join(part for part in (last, first, middle) if part)).strip().upper()


def decline_name(original: str, entity_type: str, grammatical_case: str,
                 override_store: OverrideStore | None = None) -> DeclensionResult:
    original = str(original or "").strip()
    entity_type = str(entity_type or "other").strip().casefold()
    grammatical_case = str(grammatical_case or "").strip().casefold()
    if entity_type not in ENTITY_TYPES or grammatical_case not in CASES or not original:
        return DeclensionResult("", "unresolved", "unresolved", original, entity_type or "other")
    store = override_store or DEFAULT_OVERRIDE_STORE
    override = store.form(original, entity_type, grammatical_case)
    if override:
        return DeclensionResult(override, "resolved", "override", original, entity_type)
    if grammatical_case == "dative":
        return DeclensionResult("", "unresolved", "unresolved", original, entity_type)
    if entity_type == "legal_entity":
        value = _legal(original, grammatical_case)
    elif entity_type in {"fop", "person"}:
        value = _person(original, grammatical_case, entity_type == "fop")
    else:
        value = None
    return DeclensionResult(value or "", "resolved" if value else "unresolved",
                            "automatic" if value else "unresolved", original, entity_type)
