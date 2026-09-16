"""Synthetic structural acceptance for AMKU short cases and decision hyperlinks."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docx_conditionals import render
import template_catalog
import template_runtime
from schema_catalog import catalog as schema_catalog


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".tmp" / "amcu_followup" / "amcu_synthetic.docx"
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def text(node):
    return "".join(node.xpath(".//w:t/text()", namespaces=NS))


def main():
    fields = template_catalog.validate(template_catalog.load(), schema_catalog(ROOT / "data" / "pqm.sqlite3"))
    source = template_runtime.template_path("amcu_exclusion_protocol")
    report = template_catalog.scan_docx(source, fields, "amcu_exclusion_protocol")
    context = {
        "decision.number": "701-TEST",
        "decision.date": "2026-09-15",
        "supplier.name_genitive": "ФІЗИЧНОЇ ОСОБИ-ПІДПРИЄМЦЯ ПРЕСЛІЦЬКОЇ КАТЕРИНИ КАЗИМИРІВНИ",
        "supplier.name_accusative": "ФІЗИЧНУ ОСОБУ-ПІДПРИЄМЦЯ ПРЕСЛІЦЬКУ КАТЕРИНУ КАЗИМИРІВНУ",
        "supplier.short_name_genitive": "ФОП ПРЕСЛІЦЬКОЇ К.К.",
        "supplier.short_name_accusative": "ФОП ПРЕСЛІЦЬКУ К.К.",
        "supplier.code": "2884318089",
        "supplier.code_label": "РНОКПП",
        "uo.full_name": "Світлана НАМЯСЕНКО",
        "amcu.decisions[]": [
            {"number": "72/130-р/к", "date": "2026-09-11", "authority": "", "extract_url": "https://example.test/one",
             "linked_reference": "від 11.09.2026 № 72/130-р/к"},
            {"number": "73/130-р/к", "date": "2026-09-12", "authority": "", "extract_url": "https://example.test/two",
             "linked_reference": "від 12.09.2026 № 73/130-р/к"},
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    render(source, OUTPUT, context, fields, "amcu_exclusion_protocol")
    with ZipFile(OUTPUT) as package:
        root = etree.fromstring(package.read("word/document.xml"))
        rels = etree.fromstring(package.read("word/_rels/document.xml.rels"))
        by_id = {row.get("Id"): row for row in rels}
        links = root.xpath(".//w:hyperlink", namespaces=NS)
        hyperlinks = []
        for link in links:
            relationship = by_id[link.get("{" + NS["r"] + "}id")]
            properties = link.xpath("./w:r/w:rPr", namespaces=NS)[0]
            hyperlinks.append({
                "text": text(link),
                "target": relationship.get("Target"),
                "target_mode": relationship.get("TargetMode"),
                "color": properties.xpath("./w:color/@w:val", namespaces=NS),
                "underline": properties.xpath("./w:u/@w:val", namespaces=NS),
                "font_size_half_points": properties.xpath("./w:sz/@w:val", namespaces=NS),
            })
        visible = "\n".join(text(paragraph) for paragraph in root.xpath(".//w:p", namespaces=NS))
    result = {
        "output": str(OUTPUT),
        "can_activate_canonical": report["can_activate_canonical"],
        "unknown": report["unknown"],
        "conditional_errors": report["conditional_errors"],
        "hyperlinks": hyperlinks,
        "marker_residue": "{{" in visible or "}}" in visible,
        "raw_url_visible": "https://" in visible,
        "accusative_sentence": "постачальника ФОП ПРЕСЛІЦЬКУ К.К. (РНОКПП: 2884318089) притягнуто" in visible,
        "genitive_sentence": "відповідальності ФОП ПРЕСЛІЦЬКОЇ К.К. (РНОКПП: 2884318089)" in visible,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
