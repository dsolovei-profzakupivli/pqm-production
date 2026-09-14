"""Canonical plain-text handling for violation-review narratives."""
from __future__ import annotations


def normalize_justification_text(value: object) -> str:
    """Return one non-empty logical paragraph per LF-delimited line.

    The narrative remains plain text.  Visual indentation and spacing belong to
    the DOCX paragraph formatting, never to whitespace embedded in the value.
    """
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = []
    for line in text.split("\n"):
        normalized = line.strip(" \t")
        if normalized:
            paragraphs.append(normalized)
    return "\n".join(paragraphs)
