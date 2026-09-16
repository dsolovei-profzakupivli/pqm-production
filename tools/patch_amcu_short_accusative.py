"""Assertion-heavy activation of the approved AMKU short accusative marker."""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import template_runtime
from schema_catalog import catalog as schema_catalog


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "data" / "templates" / "amcu_exclusion_protocol.docx"
PACKAGED = ROOT / "templates" / "amcu_exclusion_protocol.docx"
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
OLD = "{{supplier.short_name_genitive}}"
NEW = "{{supplier.short_name_accusative}}"
FIRST_CONTEXT = "На підставі зазначених рішень постачальника"
SECOND_CONTEXT = "У зв’язку з виявленням Адміністратором"


def paragraph_text(paragraph):
    return "".join(paragraph.xpath(".//w:t/text()", namespaces=NS))


def replace_split_token(paragraph, old, new):
    texts = paragraph.xpath(".//w:t", namespaces=NS)
    full = "".join(node.text or "" for node in texts)
    if full.count(old) != 1:
        raise RuntimeError(f"Expected one {old} in target paragraph")
    start, end = full.index(old), full.index(old) + len(old)
    offset = 0
    inserted = False
    for node in texts:
        text = node.text or ""
        left, right = offset, offset + len(text)
        offset = right
        if right <= start or left >= end:
            continue
        a, b = max(0, start - left), min(len(text), end - left)
        node.text = text[:a] + (new if not inserted else "") + text[b:]
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        inserted = True


def patch_document_xml(raw):
    root = etree.fromstring(raw)
    paragraphs = root.xpath(".//w:p", namespaces=NS)
    first = [paragraph for paragraph in paragraphs if FIRST_CONTEXT in paragraph_text(paragraph)]
    second = [paragraph for paragraph in paragraphs if SECOND_CONTEXT in paragraph_text(paragraph)]
    if len(first) != 1 or len(second) != 1:
        raise RuntimeError(f"Expected unique sentence contexts, got first={len(first)} second={len(second)}")
    replace_split_token(first[0], OLD, NEW)
    if OLD not in paragraph_text(second[0]) or NEW in paragraph_text(second[0]):
        raise RuntimeError("Second sentence must retain supplier.short_name_genitive")
    all_text = "\n".join(paragraph_text(paragraph) for paragraph in paragraphs)
    if all_text.count(NEW) != 1 or all_text.count(OLD) != 1:
        raise RuntimeError("AMKU short-name case markers are not exactly accusative + genitive")
    if all_text.count("{{linked_reference}}") != 2:
        raise RuntimeError("Both AMKU decision repeat prototypes must retain linked_reference")
    for forbidden in ("{{authority}}", "{{extract_url}}", "посилання на витяг"):
        if forbidden.casefold() in all_text.casefold():
            raise RuntimeError(f"Forbidden AMKU template residue: {forbidden}")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def main():
    with ZipFile(RUNTIME) as source:
        parts = [(item, source.read(item)) for item in source.infolist()]
    with tempfile.TemporaryDirectory(prefix="pqm-amcu-short-accusative-") as folder:
        candidate = Path(folder) / RUNTIME.name
        with ZipFile(candidate, "w", ZIP_DEFLATED) as target:
            for item, raw in parts:
                target.writestr(item, patch_document_xml(raw) if item.filename == "word/document.xml" else raw)
        schema = schema_catalog(ROOT / "data" / "pqm.sqlite3")
        diagnostics = {}
        activated = template_runtime.replace("amcu_exclusion_protocol", candidate, schema, diagnostics=diagnostics)
        shutil.copy2(activated, PACKAGED)
        print(f"runtime={activated}")
        print(f"packaged={PACKAGED}")
        print(f"diagnostics={diagnostics}")


if __name__ == "__main__":
    main()
