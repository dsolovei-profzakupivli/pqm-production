"""One-time, assertion-heavy patch for the user-edited AMKU runtime template."""
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


def paragraph_text(paragraph):
    return "".join(paragraph.xpath(".//w:t/text()", namespaces=NS))


def set_paragraph_text(paragraph, value):
    texts = paragraph.xpath(".//w:t", namespaces=NS)
    if not texts:
        raise RuntimeError("Repeat prototype has no ordinary Word text run")
    texts[0].text = value
    texts[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    for node in texts[1:]:
        node.text = ""


def replace_run_split_token(paragraph, old, new):
    texts = paragraph.xpath(".//w:t", namespaces=NS)
    full = "".join(node.text or "" for node in texts)
    if old not in full:
        return 0
    if full.count(old) != 1:
        raise RuntimeError(f"Ambiguous token count in paragraph: {old}")
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
        replacement = new if not inserted else ""
        inserted = True
        node.text = text[:a] + replacement + text[b:]
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return 1


def patch_document_xml(raw):
    root = etree.fromstring(raw)
    paragraphs = root.xpath(".//w:p", namespaces=NS)
    repeat_open = None
    repeat_count = 0
    short_count = 0
    for paragraph in paragraphs:
        text = paragraph_text(paragraph).strip()
        if text == "{{#repeat amcu.decisions[]}}":
            if repeat_open is not None:
                raise RuntimeError("Nested repeat is not supported")
            repeat_open = paragraph
            continue
        if text == "{{/repeat}}":
            if repeat_open is None:
                raise RuntimeError("Repeat close without open")
            parent = paragraph.getparent()
            if repeat_open.getparent() is not parent:
                raise RuntimeError("Repeat crosses Word containers")
            siblings = list(parent)
            prototypes = siblings[siblings.index(repeat_open) + 1:siblings.index(paragraph)]
            if len(prototypes) != 1 or etree.QName(prototypes[0]).localname != "p":
                raise RuntimeError("Each AMKU repeat must contain exactly one paragraph prototype")
            set_paragraph_text(prototypes[0], "{{linked_reference}}")
            repeat_count += 1
            repeat_open = None
            continue
        short_count += replace_run_split_token(
            paragraph, "{{supplier.short_name}}", "{{supplier.short_name_genitive}}")
    if repeat_open is not None:
        raise RuntimeError("Unclosed repeat")
    if repeat_count != 2:
        raise RuntimeError(f"Expected exactly 2 AMKU repeats, found {repeat_count}")
    if short_count != 2:
        raise RuntimeError(f"Expected exactly 2 supplier.short_name tokens, found {short_count}")
    final_text = "\n".join(paragraph_text(p) for p in paragraphs)
    for forbidden in ("{{authority}}", "{{extract_url}}", "посилання на витяг", "{{supplier.short_name}}"):
        if forbidden.casefold() in final_text.casefold():
            raise RuntimeError(f"Forbidden template residue: {forbidden}")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def main():
    if not RUNTIME.is_file():
        raise SystemExit(f"Runtime template missing: {RUNTIME}")
    with ZipFile(RUNTIME) as source:
        parts = [(item, source.read(item)) for item in source.infolist()]
    with tempfile.TemporaryDirectory(prefix="pqm-amcu-template-") as folder:
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
