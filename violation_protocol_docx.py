"""DOCX protocol generator for customer violation reports.

The module edits copies of the three approved Word packages.  It deliberately
contains no database or Prozorro access: readiness and freshness are enforced
by the HTTP/service layer.
"""
from __future__ import annotations

import re
import shutil
import os
import tempfile
import time
import uuid
import zipfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from lxml import etree
from protocol_template import validate as validate_application_template
from docx_conditionals import plan as plan_conditionals, render_conditionals
import template_catalog
from violation_text import normalize_justification_text


ROOT = Path(__file__).parent
PACKAGED_TEMPLATE_DIR = ROOT / "templates" / "violation_protocols"
DATA_DIR = Path(os.environ.get("PQM_DATA_DIR", ROOT / "data"))
TEMPLATE_DIR = DATA_DIR / "templates" / "violation_protocols"
TEMPLATES = {
    "warning": TEMPLATE_DIR / "warning.docx",
    "decline_p49_1_2": TEMPLATE_DIR / "decline_p49_1_2.docx",
    "decline_p49_3": TEMPLATE_DIR / "decline_p49_3.docx",
    "application_protocol": DATA_DIR / "templates" / "application_protocol.docx",
}
TOKEN_RE = re.compile(r"\{\{\s*(.*?)\s*\}\}")
LEGAL_REFERENCE_RE = re.compile(r"(?<!\w)(№|пп\.|п\.|ст\.|ч\.|абз\.)[ \u00a0]+(?=\d)", re.IGNORECASE)
ENTITY_NAME_TOKENS = {
    "customer_name", "customer_name_genitive", "customer_name_dative", "customer_name_accusative",
    "supplier_name", "supplier_short_name", "supplier_name_genitive", "supplier_name_dative",
    "supplier_name_accusative",
}


class ProtocolContextValidationError(ValueError):
    """Expected missing/unknown template data, safe to return as HTTP 422."""

    def __init__(self, message: str, *, missing=(), unknown=()):
        super().__init__(message)
        self.missing = tuple(sorted(set(missing)))
        self.unknown = tuple(sorted(set(unknown)))
CONDITIONAL_TOKEN_FLAGS = {
    "customer_documents": "has_customer_documents",
    "refusal_date": "has_written_refusal",
    "refusal_document": "has_written_refusal",
    "refusal_outgoing_number": "has_written_refusal",
    "contract_date": "has_contract",
    "contract_number": "has_contract",
}
DOCUMENT_TOKENS = {"customer_documents", "supplier_documents"}
FIELD_LABELS = {
    "protocol_number": "Номер протоколу", "protocol_date": "Дата протоколу",
    "report_id": "Номер звернення", "procurement_id": "Номер закупівлі",
    "procurement_date": "Дата оголошення закупівлі", "cpv_category": "Код ДК",
    "customer_name": "Назва замовника", "customer_name_genitive": "Назва замовника (родовий відмінок)",
    "customer_name_accusative": "Назва замовника (знахідний відмінок)",
    "customer_code": "ЄДРПОУ замовника", "supplier_name": "Назва постачальника",
    "supplier_name_genitive": "Назва постачальника (родовий відмінок)",
    "supplier_name_dative": "Назва постачальника (давальний відмінок)",
    "supplier_name_accusative": "Назва постачальника (знахідний відмінок)",
    "supplier_code": "ЄДРПОУ / РНОКПП постачальника", "supplier_code_label": "Тип коду постачальника",
    "officer_name": "Уповноважена особа", "decision_justification": "Обґрунтування рішення",
    "contract_number": "Номер договору", "contract_date": "Дата договору",
}
def _token_name(value: str) -> str:
    """Canonicalize whitespace around/inside a marker without changing its name."""
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


def ensure_runtime_templates() -> None:
    """Seed writable runtime storage without overwriting operator changes.

    Source-tree templates are immutable deployment seeds.  Keeping active files
    under DATA_DIR also avoids Windows ACL/ownership conflicts when the app and
    the source checkout are owned by different local identities.
    """
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    for key, target in TEMPLATES.items():
        source = (ROOT / "templates" / "application_protocol.docx"
                  if key == "application_protocol" else PACKAGED_TEMPLATE_DIR / target.name)
        if not target.exists() and source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def template_metadata() -> list[dict[str, Any]]:
    ensure_runtime_templates()
    labels = {
        "warning": "Попередження за зверненням",
        "decline_p49_1_2": "Відмова за пп. 1–2 п. 49",
        "decline_p49_3": "Відмова за пп. 3 п. 49",
        "application_protocol": "Протокол розгляду заявок / кваліфікації",
    }
    result = []
    for key, path in TEMPLATES.items():
        stat = path.stat() if path.exists() else None
        result.append({"key": key, "name": labels[key], "filename": path.name,
                       "exists": bool(stat),
                       "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds") if stat else None})
    return result


def _template_tokens(path: Path) -> set[str]:
    document = Document(path)
    return {token for paragraph in _all_paragraphs(document)
            for match in TOKEN_RE.finditer(paragraph.text)
            if not (token := _token_name(match.group(1))).startswith("#if ") and token != "/if"}


def _condition_fields() -> list[dict[str, Any]]:
    # The condition field is a document-only derived value with no physical
    # dependencies.  Full DB schema validation remains owned by the Admin API.
    return template_catalog.validate(template_catalog.load(), {"items": []})


def _condition_variants(path: Path, document_type: str) -> set[tuple[str, str]]:
    variants: set[tuple[str, str]] = set()
    fields = _condition_fields()
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not (name.startswith("word/") and name.endswith(".xml")):
                continue
            root = etree.fromstring(archive.read(name))
            blocks, _ = plan_conditionals(root, fields, document_type, validate_scalars=False)
            variants.update((condition.key, condition.literal) for condition, _ in blocks)
    return variants


def replace_runtime_template(key: str, source_path: str | Path) -> Path:
    """Validate and atomically activate a DOCX while retaining the previous version."""
    ensure_runtime_templates()
    target = TEMPLATES.get(key)
    source = Path(source_path)
    if not target or source.suffix.lower() != ".docx" or not zipfile.is_zipfile(source):
        raise ValueError("Потрібен коректний файл DOCX для вибраного шаблону")
    try:
        expected = _template_tokens(target)
        supplied = _template_tokens(source)
        document_type = template_catalog.RUNTIME_TYPES.get(key)
        if document_type and _condition_variants(target, document_type) != _condition_variants(source, document_type):
            raise ValueError("У DOCX змінено або втрачено declarative conditional blocks")
        if key == "application_protocol":
            with zipfile.ZipFile(source) as archive:
                validate_application_template(etree.fromstring(archive.read("word/document.xml")))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Не вдалося прочитати структуру DOCX") from exc
    missing = sorted(expected - supplied)
    if missing:
        raise ValueError("У DOCX відсутні обов’язкові маркери: " + ", ".join(missing))
    versions = TEMPLATE_DIR / "_versions"
    versions.mkdir(parents=True, exist_ok=True)
    backup = None
    if target.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup = versions / f"{target.stem}_{stamp}{target.suffix}"
        shutil.copy2(target, backup)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.stem}.", suffix=".tmp.docx")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        for attempt in range(8):
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                if attempt == 7:
                    if backup:
                        backup.unlink(missing_ok=True)
                    raise PermissionError(
                        f"Не вдалося активувати шаблон «{target.name}»: файл тимчасово заблокований Windows. "
                        "Закрийте відкриту копію шаблону у Word та повторіть дію."
                    )
                time.sleep(0.05 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _norm(value: str) -> str:
    return re.sub(r"[\s_.–—/-]+", " ", (value or "").strip().lower())


def _presentation_text(value: Any) -> str:
    """Keep a normative designator and its number together in Word."""
    return LEGAL_REFERENCE_RE.sub(lambda match: match.group(1) + "\u00a0", str(value or ""))


def _presentation_entity_name(value: Any) -> str:
    """Normalize only paired outer ASCII quotes; preserve apostrophes."""
    return re.sub(r'"([^"\r\n]+)"', lambda match: f"«{match.group(1)}»", str(value or ""))


def _copy_paragraph_properties(source, target) -> None:
    """Copy the complete template pPr instead of inheriting Word defaults."""
    target_ppr = target._p.pPr
    if target_ppr is not None:
        target._p.remove(target_ppr)
    if source._p.pPr is not None:
        target._p.insert(0, deepcopy(source._p.pPr))


def _all_paragraphs(document):
    yield from document.paragraphs
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs
    for section in document.sections:
        yield from section.header.paragraphs
        yield from section.footer.paragraphs


def _clear_resolved_run_marking(run) -> None:
    """Remove editor/service marking only from a resolved placeholder run."""
    rpr = run._r.rPr
    if rpr is None:
        return
    for name in ("w:highlight", "w:shd"):
        node = rpr.find(qn(name))
        if node is not None:
            rpr.remove(node)


def _replace_in_paragraph(paragraph, values: dict[str, str]):
    text = paragraph.text
    matches = list(TOKEN_RE.finditer(text))
    if not matches:
        return
    runs = list(paragraph.runs)
    if not runs:
        runs = [paragraph.add_run()]
    # A standalone multiline placeholder represents semantic Word paragraphs,
    # not a sequence of line-breaks inside one paragraph.  Clone the complete
    # template paragraph and run properties for every additional block.
    if len(matches) == 1 and text.strip() == matches[0].group(0):
        key = _token_name(matches[0].group(1))
        if key not in values:
            raise ValueError(f"Невідомий placeholder у DOCX: {matches[0].group(1).strip()}")
        blocks = [part.strip() for part in re.split(r"(?:\r?\n){2,}", str(values[key])) if part.strip()]
        if len(blocks) > 1:
            source_run = runs[0]
            base_ppr = deepcopy(paragraph._p.pPr) if paragraph._p.pPr is not None else None
            current = paragraph
            for index, block in enumerate(blocks):
                if index:
                    node = OxmlElement("w:p")
                    if base_ppr is not None:
                        node.append(deepcopy(base_ppr))
                    current._p.addnext(node)
                    from docx.text.paragraph import Paragraph
                    current = Paragraph(node, paragraph._parent)
                _clear_paragraph_content(current)
                run = current.add_run(block)
                if source_run._r.rPr is not None:
                    run._r.insert(0, deepcopy(source_run._r.rPr))
                _clear_resolved_run_marking(run)
            return
    ranges, position = [], 0
    for index, run in enumerate(runs):
        ranges.append((position, position + len(run.text), index))
        position += len(run.text)

    # Edit the original runs in place.  Rebuilding the paragraph from broad
    # text segments used to copy the formatting of the first character over
    # the whole segment.  A harmless shaded space next to p49_reference could
    # therefore paint the resolved/reference text orange.  Per-run edits keep
    # every static run and its author formatting at its original extent.
    edits: dict[int, list[tuple[int, int, str]]] = {}
    resolved_runs = set()
    adjacent_whitespace_runs = set()
    for match in matches:
        key = _token_name(match.group(1))
        if key not in values:
            raise ValueError(f"Невідомий placeholder у DOCX: {match.group(1).strip()}")
        overlaps = [(start, end, index) for start, end, index in ranges
                    if end > match.start() and start < match.end()]
        if not overlaps:
            continue
        first_run_index = overlaps[0][2]
        last_run_index = overlaps[-1][2]
        for neighbor_index in (first_run_index - 1, last_run_index + 1):
            if 0 <= neighbor_index < len(runs) and runs[neighbor_index].text.isspace():
                adjacent_whitespace_runs.add(neighbor_index)
        for overlap_index, (start, end, run_index) in enumerate(overlaps):
            local_start = max(0, match.start() - start)
            local_end = min(end, match.end()) - start
            replacement = str(values[key]) if overlap_index == 0 else ""
            edits.setdefault(run_index, []).append((local_start, local_end, replacement))
            if replacement:
                resolved_runs.add(run_index)
    for run_index, run_edits in edits.items():
        value = runs[run_index].text
        for start, end, replacement in sorted(run_edits, reverse=True):
            value = value[:start] + replacement + value[end:]
        runs[run_index].text = value
        if run_index in resolved_runs:
            _clear_resolved_run_marking(runs[run_index])
    # Some Word/editor exports keep review shading on a standalone separator
    # run next to a placeholder.  It is invisible in the source document but
    # becomes an orange strip after rendering.  A whitespace-only separator
    # carries no author-visible highlighted content, so discard only its
    # highlight/shading while preserving marked static text elsewhere.
    for run_index in adjacent_whitespace_runs:
        _clear_resolved_run_marking(runs[run_index])


def _font_run_properties(run_properties) -> Any:
    """Copy only typography inherited from a template run.

    Generated protocol text must not inherit editor highlights/review shading,
    but it does need the template's font family and size.  Restricting the
    copy to font properties also leaves emphasis and hyperlink decoration
    under the control of the generated semantic fragment.
    """
    result = OxmlElement("w:rPr")
    if run_properties is not None:
        for name in ("w:rFonts", "w:sz", "w:szCs", "w:lang"):
            node = run_properties.find(qn(name))
            if node is not None:
                result.append(deepcopy(node))
    if result.find(qn("w:sz")) is None:
        size = OxmlElement("w:sz")
        size.set(qn("w:val"), "24")
        result.append(size)
    if result.find(qn("w:szCs")) is None:
        size_cs = OxmlElement("w:szCs")
        size_cs.set(qn("w:val"), "24")
        result.append(size_cs)
    return result


def _protocol_body_run_properties(document) -> Any:
    """Resolve the approved template's main-body typography.

    The normative block is an explicit 12 pt body-style specimen in all
    approved protocol templates.  The decision heading is a safe fallback;
    only font properties are copied, so its bold/italic emphasis is ignored.
    """
    preferred = ("роз’яснень міністерства економіки україни",
                 "за результатами розгляду встановлено")
    for marker in preferred:
        for paragraph in document.paragraphs:
            if marker not in _presentation_text(paragraph.text).casefold():
                continue
            for run in paragraph.runs:
                if run.text.strip():
                    return _font_run_properties(run._r.rPr)
    return _font_run_properties(None)


def _add_body_run(paragraph, text: str, run_properties, *, bold: bool = False,
                  italic: bool = False):
    run = paragraph.add_run(text)
    current = run._r.rPr
    if current is not None:
        run._r.remove(current)
    run._r.insert(0, deepcopy(run_properties))
    run.bold = bold
    run.italic = italic
    return run


def _add_hyperlink(paragraph, label: str, url: str, font_name: str | None = None,
                   font_size: float | None = None, run_properties=None):
    part = paragraph.part
    rel_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), rel_id)
    run = OxmlElement("w:r")
    props = deepcopy(run_properties) if run_properties is not None else OxmlElement("w:rPr")
    for name in ("w:color", "w:u"):
        existing = props.find(qn(name))
        if existing is not None:
            props.remove(existing)
    color = OxmlElement("w:color"); color.set(qn("w:val"), "0563C1")
    underline = OxmlElement("w:u"); underline.set(qn("w:val"), "single")
    props.extend((color, underline))
    if font_name:
        fonts = OxmlElement("w:rFonts")
        for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
            fonts.set(qn(f"w:{attr}"), font_name)
        props.append(fonts)
    if font_size:
        size = OxmlElement("w:sz"); size.set(qn("w:val"), str(int(font_size * 2)))
        size_cs = OxmlElement("w:szCs"); size_cs.set(qn("w:val"), str(int(font_size * 2)))
        props.extend((size, size_cs))
    run.append(props)
    node = OxmlElement("w:t"); node.text = label
    run.append(node); hyperlink.append(run); paragraph._p.append(hyperlink)


def _display_document_datetime(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return raw


def _clear_paragraph_content(paragraph) -> None:
    for child in list(paragraph._p):
        if child.tag != qn("w:pPr"):
            paragraph._p.remove(child)


def _document_label(document: dict[str, Any]) -> str:
    return str(document.get("title") or document.get("name") or
               document.get("documentType") or "Документ").strip()


def _set_document_links(paragraph, documents: list[dict[str, Any]]):
    """Render one physical document per Word paragraph, without duplicates."""
    unique, seen = [], set()
    for document in documents:
        url = str(document.get("url") or "").strip()
        label = _presentation_text(_document_label(document))
        marker = (str(document.get("id") or ""), label, url)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append((label, url))
    if not unique:
        _clear_paragraph_content(paragraph)
        run = paragraph.add_run("не надано")
        _set_run_font(run, 11, italic=True)
        return
    current = paragraph
    base_ppr = deepcopy(paragraph._p.pPr) if paragraph._p.pPr is not None else None
    for index, (label, url) in enumerate(unique):
        if index:
            node = OxmlElement("w:p")
            if base_ppr is not None:
                node.append(deepcopy(base_ppr))
            current._p.addnext(node)
            from docx.text.paragraph import Paragraph
            current = Paragraph(node, paragraph._parent)
        _clear_paragraph_content(current)
        if url:
            _add_hyperlink(current, label, url, "Times New Roman")
        else:
            run = current.add_run(label)
            _set_run_font(run, 11)


def _normalized_documents(documents: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Preserve authoritative source order while dropping exact duplicates."""
    result, seen = [], set()
    for item in documents or []:
        marker = (str(item.get("id") or ""), str(item.get("url") or ""),
                  str(item.get("title") or item.get("name") or ""))
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


def _clear_paragraph(paragraph):
    for run in paragraph.runs:
        run.text = ""


def _configure_customer_document_block(document, documents: list[dict[str, Any]]):
    """Render source documents without inferring corruption from local access.

    ``file_unavailable`` is a manual PQM access check, not authoritative proof
    of zero bytes or source corruption, so it must not trigger the template's
    legal damaged-file statement.
    """
    for table in document.tables:
        for row in table.rows:
            row_tokens = {_token_name(match.group(1)) for cell in row.cells
                          for paragraph in cell.paragraphs
                          for match in TOKEN_RE.finditer(paragraph.text)}
            if "customer_documents" not in row_tokens:
                continue
            target = row.cells[-1]
            paragraphs = target.paragraphs
            token = next((p for p in paragraphs if any(
                _token_name(match.group(1)) == "customer_documents"
                for match in TOKEN_RE.finditer(p.text))), None)
            singular = next((p for p in paragraphs if "додано файл" in _norm(p.text)
                             and "технічно пошкоджен" in _norm(p.text)), None)
            plural = next((p for p in paragraphs if "додані файли" in _norm(p.text)
                           and "технічно пошкоджен" in _norm(p.text)), None)
            if not token:
                return
            if singular:
                singular._element.getparent().remove(singular._element)
            if plural:
                plural._element.getparent().remove(plural._element)
            # Remove empty separator paragraphs from the template.
            for paragraph in list(target.paragraphs):
                if paragraph is not token and not paragraph.text.strip():
                    paragraph._element.getparent().remove(paragraph._element)
            _set_document_links(token, documents)
            return


def _set_run_font(run, size: float, bold: bool = False, italic: bool = False):
    run.font.name = "Times New Roman"
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = RGBColor(0, 0, 0)
    fonts = run._element.get_or_add_rPr().get_or_add_rFonts()
    for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn(f"w:{attr}"), "Times New Roman")


def _clear_cell(cell):
    first = cell.paragraphs[0]
    for paragraph in list(cell.paragraphs[1:]):
        paragraph._element.getparent().remove(paragraph._element)
    for child in list(first._p):
        if child.tag != qn("w:pPr"):
            first._p.remove(child)
    return first


def _set_paragraph_geometry(paragraph, size: float, first_line: bool = False,
                            first_line_cm: float = 0.5):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(0)
    fmt.space_after = Pt(0)
    fmt.line_spacing = 1.0
    fmt.first_line_indent = Cm(first_line_cm) if first_line else None
    for run in paragraph.runs:
        _set_run_font(run, size, bool(run.bold), bool(run.italic))


def _format_reason_block(document, values: dict[str, str]):
    for table in document.tables:
        for index, row in enumerate(table.rows):
            if "причина звернення" not in " ".join(cell.text for cell in row.cells).lower():
                continue
            label_cell, value_cell = row.cells[0], row.cells[-1]
            label_cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
            value_cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
            label_p = _clear_cell(label_cell)
            label_run = label_p.add_run("Причина звернення:")
            _set_run_font(label_run, 10, bold=True)
            reason_label = _clear_cell(value_cell)
            label = reason_label.add_run(values.get("reason_label", ""))
            _set_run_font(label, 10, bold=True)
            reason_text = value_cell.add_paragraph()
            _copy_paragraph_properties(reason_label, reason_text)
            text_run = reason_text.add_run(values.get("reason_text", ""))
            _set_run_font(text_run, 10)
            if index + 1 >= len(table.rows):
                raise ValueError("У шаблоні немає рядка для опису Замовника")
            description_cell = table.rows[index + 1].cells[0]
            description_cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
            description_p = _clear_cell(description_cell)
            description = values.get("violation_description", "").strip()
            # Preserve an existing Ukrainian quotation (including punctuation
            # after the closing mark) and never create doubled quotation marks.
            quoted = description if description.startswith("«") and "»" in description else f"«{description}»"
            description_run = description_p.add_run(quoted)
            _set_run_font(description_run, 10, italic=True)
            return
    raise ValueError("У погодженому шаблоні не знайдено блок «Причина звернення»")


def _format_supplier_result_rows(document) -> None:
    """Keep supplier response/document outcomes visible in every protocol."""
    labels = ("відповідь постачальника на звернення", "документи подані постачальником")
    for table in document.tables:
        for row in table.rows:
            text = " ".join(cell.text for cell in row.cells).casefold()
            if not any(label in text for label in labels):
                continue
            unique_cells = []
            seen = set()
            for cell in row.cells:
                marker = id(cell._tc)
                if marker not in seen:
                    seen.add(marker); unique_cells.append(cell)
            label_cell, value_cell = unique_cells[0], unique_cells[-1]
            for paragraph in label_cell.paragraphs:
                for run in paragraph.runs:
                    if run.text:
                        _set_run_font(run, 11, bold=True)
            if value_cell.text.strip().casefold() == "не надано":
                for paragraph in value_cell.paragraphs:
                    for run in paragraph.runs:
                        if run.text:
                            _set_run_font(run, 11, italic=True)


def _justification_emphasis(protocol_type: str, values: dict[str, str]) -> list[str]:
    common = ["п. 51 Порядку № 822", "відмову в задоволенні звернення Замовника"]
    if protocol_type == "decline_p49_3":
        return ["рішенням суду, що набрало законної сили", "рішення про відмову в задоволенні звернення Замовника", *common]
    if protocol_type == "decline_p49_1_2":
        return ["пп. 1 п. 49 Порядку № 822", "пп. 2 п. 49 Порядку № 822",
                "після закінчення трьох календарних днів", "після спливу трьох календарних днів",
                values.get("supplier_deadline", ""), values.get("contract_deadline", ""), *common]
    return ["п. 66 Порядку № 822", "п’ять календарних днів", "пп. 1 п. 49 Порядку № 822", *common]


def _append_justification_text(paragraph, text: str, emphasis: list[str], run_properties):
    phrases = sorted({_presentation_text(phrase) for phrase in emphasis if phrase}, key=len, reverse=True)
    pattern_parts = [r"https?://[^\s]+"] + [re.escape(phrase) for phrase in phrases]
    pattern = re.compile("(" + "|".join(pattern_parts) + ")", re.IGNORECASE)
    cursor = 0
    for match in pattern.finditer(text):
        if match.start() > cursor:
            _add_body_run(paragraph, text[cursor:match.start()], run_properties)
        fragment = match.group(0)
        if re.match(r"https?://", fragment, re.IGNORECASE):
            _add_hyperlink(paragraph, fragment, fragment, run_properties=run_properties)
        else:
            _add_body_run(paragraph, fragment, run_properties, bold=True)
        cursor = match.end()
    if cursor < len(text):
        _add_body_run(paragraph, text[cursor:], run_properties)


def _set_thin_black_borders(cell):
    tc_pr = cell._tc.get_or_add_tcPr()
    shading = tc_pr.find(qn("w:shd"))
    if shading is not None:
        tc_pr.remove(shading)
    borders = tc_pr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = borders.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), "4")
        node.set(qn("w:color"), "000000")


def _normalize_all_text_run_fonts(document) -> None:
    """Pin every emitted text run to TNR without changing its other styling."""
    for part in document.part.package.parts:
        root = getattr(part, "_element", None)
        if root is None:
            continue
        for run in root.xpath(".//w:r[.//w:t[string-length(.) > 0]]"):
            r_pr = run.find(qn("w:rPr"))
            if r_pr is None:
                r_pr = OxmlElement("w:rPr")
                run.insert(0, r_pr)
            fonts = r_pr.find(qn("w:rFonts"))
            if fonts is None:
                fonts = OxmlElement("w:rFonts")
                r_pr.insert(0, fonts)
            for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
                fonts.set(qn(f"w:{attr}"), "Times New Roman")


def _normalize_legal_reference_spaces(document) -> None:
    """Apply non-breaking spaces to all visible template/generated text."""
    for part in document.part.package.parts:
        root = getattr(part, "_element", None)
        if root is None:
            continue
        for node in root.xpath(".//w:t"):
            if node.text:
                node.text = _presentation_text(node.text)


def _replace_justification(document, justification: str, protocol_type: str,
                           values: dict[str, str]):
    body_run_properties = _protocol_body_run_properties(document)
    for table in document.tables:
        for row in table.rows:
            row_text = " ".join(cell.text for cell in row.cells)
            if "обґрунтування рішення" not in row_text.lower():
                continue
            target = row.cells[-1]
            if len(row.cells) == 1:
                target = row.cells[0]
            label = row.cells[0]
            label.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
            target.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
            label_p = label.paragraphs[0]
            for run in label_p.runs:
                _set_run_font(run, 11, bold=True)
            _set_paragraph_geometry(label_p, 11)
            first = _clear_cell(target)
            template_paragraph = deepcopy(first._p.pPr) if first._p.pPr is not None else None
            blocks = normalize_justification_text(justification).split("\n")
            emphasis = _justification_emphasis(protocol_type, values)
            for index, block in enumerate(blocks):
                paragraph = first if index == 0 else target.add_paragraph()
                if index and template_paragraph is not None:
                    current_ppr = paragraph._p.pPr
                    if current_ppr is not None:
                        paragraph._p.remove(current_ppr)
                    paragraph._p.insert(0, deepcopy(template_paragraph))
                _append_justification_text(paragraph, block, emphasis, body_run_properties)
                _set_paragraph_geometry(paragraph, 12, first_line=True,
                                        first_line_cm=1.0)
            for cell in {label._tc: label, target._tc: target}.values():
                _set_thin_black_borders(cell)
            tr_pr = row._tr.get_or_add_trPr()
            for node in list(tr_pr):
                if node.tag in {qn("w:cantSplit"), qn("w:trHeight")}:
                    tr_pr.remove(node)
            return
    raise ValueError("У погодженому шаблоні не знайдено блок «Обґрунтування рішення»")


def _remove_optional_rows(document, flags: dict[str, bool]):
    labels = {
        "written_refusal": ("письмов", "відмов"),
        "contract": ("укладен", "договор"),
        "guarantee": ("забезпеченн", "договор"),
        "court": ("суд", "рішенн"),
    }
    for table in document.tables:
        for row in list(table.rows):
            text = " ".join(cell.text for cell in row.cells).lower()
            for key, needles in labels.items():
                if not flags.get(key, False) and all(needle in text for needle in needles):
                    row._element.getparent().remove(row._element)
                    break


def _remove_conditional_token_blocks(document, flags: dict[str, bool]):
    """Remove complete rows/paragraphs controlled by structured facts.

    The approved DOCX files contain no Jinja tags.  Each optional value occupies
    a dedicated table row, so removing that row is deterministic and leaves no
    empty legal sentence or synthetic dash.
    """
    for table in document.tables:
        for row in list(table.rows):
            tokens = {_token_name(match.group(1)) for cell in row.cells
                      for paragraph in cell.paragraphs for match in TOKEN_RE.finditer(paragraph.text)}
            if any(not flags.get(flag, False) for token, flag in CONDITIONAL_TOKEN_FLAGS.items() if token in tokens):
                row._element.getparent().remove(row._element)
    for paragraph in list(document.paragraphs):
        tokens = {_token_name(match.group(1)) for match in TOKEN_RE.finditer(paragraph.text)}
        if any(not flags.get(flag, False) for token, flag in CONDITIONAL_TOKEN_FLAGS.items() if token in tokens):
            paragraph._element.getparent().remove(paragraph._element)


def _validate_context(document, values: dict[str, str], justification: str) -> None:
    missing, unknown = set(), set()
    for paragraph in _all_paragraphs(document):
        for match in TOKEN_RE.finditer(paragraph.text):
            key = _token_name(match.group(1))
            if key in DOCUMENT_TOKENS:
                continue
            if key not in values:
                unknown.add(key)
            elif not str(values[key]).strip():
                missing.add(key)
    if unknown:
        raise ProtocolContextValidationError(
            "Невідомі placeholders у DOCX: " + ", ".join(sorted(unknown)), unknown=unknown)
    if not str(justification or "").strip():
        missing.add("decision_justification")
    if missing:
        labels = [FIELD_LABELS.get(key, key) for key in sorted(missing)]
        raise ProtocolContextValidationError(
            "Не заповнено обов’язкові поля: " + ", ".join(labels) + ". Заповніть їх перед формуванням протоколу.",
            missing=missing)


def build_violation_protocol_docx(
    protocol_type: str,
    output_path: str | Path,
    values: dict[str, str],
    justification: str,
    customer_documents: list[dict[str, Any]] | None = None,
    supplier_documents: list[dict[str, Any]] | None = None,
    flags: dict[str, bool] | None = None,
) -> Path:
    """Create a protocol by editing a copy and atomically publishing it.

    Writing directly to ``output_path`` is unsafe on Windows: an already-open
    protocol is exclusively locked by Word and ``copy2`` used to fail halfway
    through generation.  Build a complete sibling file first, then replace the
    public output in one operation.  A genuine external lock is reported as a
    controlled, user-facing conflict and never leaks the raw WinError.
    """
    ensure_runtime_templates()
    template = TEMPLATES.get(protocol_type)
    if not template or not template.exists():
        raise ValueError(f"Невідомий або відсутній шаблон протоколу: {protocol_type}")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.tmp.docx")
    try:
        document_type = template_catalog.RUNTIME_TYPES.get(protocol_type, protocol_type)
        render_conditionals(
            template,
            temporary,
            {"decision.civil_code_basis": (
                "applicable" if bool((flags or {}).get("has_civil_code_basis"))
                else "not_applicable"
            )},
            _condition_fields(),
            document_type,
        )
        document = Document(temporary)
        customer_documents = _normalized_documents(customer_documents)
        supplier_documents = _normalized_documents(supplier_documents)
        normalized_values = {
            _token_name(key): _presentation_text(
                _presentation_entity_name(value) if _token_name(key) in ENTITY_NAME_TOKENS else value
            ).strip()
            for key, value in values.items()
        }
        normalized_values["supplier_response"] = normalized_values.get("supplier_response") or "не надано"
        justification = _presentation_text(
            normalize_justification_text(justification)).strip()
        normalized_values.setdefault("decision_justification", justification)
        effective_flags = dict(flags or {})
        effective_flags.setdefault("has_customer_documents", bool(customer_documents))
        effective_flags.setdefault("has_supplier_documents", bool(supplier_documents))
        effective_flags.setdefault("has_supplier_response", bool(normalized_values.get("supplier_response")))
        effective_flags.setdefault("has_written_refusal", False)
        effective_flags.setdefault("has_contract", False)
        _remove_conditional_token_blocks(document, effective_flags)
        _remove_optional_rows(document, {
            "written_refusal": effective_flags["has_written_refusal"],
            "contract": effective_flags["has_contract"],
            "guarantee": effective_flags.get("has_contract_security", False),
            "civil_code": effective_flags.get("has_civil_code_basis", False),
            "court": effective_flags.get("has_court_decision", False),
        })
        _validate_context(document, normalized_values, justification)
        _format_reason_block(document, normalized_values)
        if customer_documents:
            _configure_customer_document_block(document, customer_documents)
        for paragraph in list(_all_paragraphs(document)):
            source = paragraph.text
            token_names = [_token_name(m.group(1)) for m in TOKEN_RE.finditer(source)]
            if "customer_documents" in token_names:
                _set_document_links(paragraph, customer_documents or [])
            elif "supplier_documents" in token_names:
                _set_document_links(paragraph, supplier_documents or [])
            else:
                _replace_in_paragraph(paragraph, normalized_values)
        _format_supplier_result_rows(document)
        _replace_justification(document, justification, protocol_type, normalized_values)
        _normalize_legal_reference_spaces(document)
        _normalize_all_text_run_fonts(document)
        unresolved = [p.text for p in _all_paragraphs(document) if "{{" in p.text or "}}" in p.text]
        if unresolved:
            raise ValueError("У DOCX залишилися незаповнені плейсхолдери")
        document.save(temporary)
        try:
            os.replace(temporary, output)
        except PermissionError as exc:
            raise PermissionError(
                f"Не вдалося оновити файл «{output.name}». "
                "Закрийте його у Microsoft Word або іншій програмі та повторіть формування."
            ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return output
