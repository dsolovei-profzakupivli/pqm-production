"""Opt-in canonical DOCX provider. Existing runtime renderers stay unchanged."""
import os
import tempfile
from pathlib import Path
from zipfile import ZipFile
from lxml import etree
from protocol_template import NS, TOKEN, paragraph_text, replace_tokens
from template_conditions import ConditionalError, Condition, field_spec, parse_marker


def plan(root, fields, document_type, *, validate_scalars=True):
    """Validate all branches before mutation, including branches later excluded.

    Markers are standalone sibling paragraphs in body/header/footer/cell.
    A range may enclose paragraphs and whole tables, never cross containers.
    """
    pending = None
    blocks = []
    scalars = set()
    for p in root.xpath('.//w:p', namespaces=NS):
        text = paragraph_text(p)
        if '{{' not in text and '}}' not in text:
            continue
        if text.strip().startswith(('{{#', '{{/')):
            marker = parse_marker(text, fields, document_type)
            parent = p.getparent()
            if etree.QName(parent).localname not in ('body', 'hdr', 'ftr', 'tc'):
                raise ConditionalError('Непідтримуваний контейнер marker')
            # A paragraph style may legitimately define tab stops in w:pPr.
            # Only actual run-level tab/break content makes a marker non-standalone.
            if p.xpath('.//w:sectPr | .//w:drawing | .//w:r/w:br | .//w:r/w:tab', namespaces=NS):
                raise ConditionalError('Marker має бути окремим текстовим абзацом')
            if isinstance(marker, Condition):
                if pending:
                    raise ConditionalError('Вкладені if не підтримуються')
                pending = (p, marker)
            else:
                if not pending:
                    raise ConditionalError('Закриваючий if без opening marker')
                start, condition = pending
                if start.getparent() is not parent:
                    raise ConditionalError('If не може перетинати контейнери DOCX')
                siblings = list(parent)
                nodes = siblings[siblings.index(start):siblings.index(p)+1]
                if any(n.xpath('.//w:sectPr', namespaces=NS) for n in nodes):
                    raise ConditionalError('If не може видаляти межу секції')
                blocks.append((condition, nodes))
                pending = None
        elif validate_scalars:
            residual = TOKEN.sub('', text)
            if '{{' in residual or '}}' in residual:
                raise ConditionalError('Некоректний placeholder або inline conditional marker: ' + text)
            for match in TOKEN.finditer(text):
                field_spec(match[1], fields, document_type)
                scalars.add(match[1])
    if pending:
        raise ConditionalError('Незакритий if')
    return blocks, scalars


def render_conditionals(source, output, context, fields, document_type):
    """Apply the canonical conditional grammar while retaining legacy scalars.

    This is the migration bridge for approved DOCX templates whose scalar
    placeholders still use the legacy renderer.  Conditional markers use the
    same validated Catalog fields and range semantics as ``render``; retained
    paragraphs, runs, hyperlinks and relationships are never reconstructed.
    """
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ConditionalError('Source template не можна перезаписувати')
    with ZipFile(source) as archive:
        parts = [(info, archive.read(info)) for info in archive.infolist()]
    roots, original_trees, decisions = {}, {}, {}
    for info, raw in parts:
        if not (info.filename.startswith('word/') and info.filename.endswith('.xml')):
            continue
        root = etree.fromstring(raw)
        roots[info.filename] = root
        original_trees[info.filename] = etree.tostring(root)
        blocks, _ = plan(root, fields, document_type, validate_scalars=False)
        decisions[info.filename] = [
            (condition.evaluate(context, fields, document_type), nodes)
            for condition, nodes in blocks
        ]
    for name, root in roots.items():
        for keep, nodes in decisions[name]:
            for node in (nodes[0], nodes[-1]) if keep else nodes:
                node.getparent().remove(node)
        for cell in root.xpath('.//w:tc', namespaces=NS):
            if not len(cell) or etree.QName(cell[-1]).localname != 'p':
                cell.append(etree.Element('{'+NS['w']+'}p'))
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(suffix='.docx', dir=output.parent)
    os.close(fd)
    try:
        with ZipFile(temp, 'w') as archive:
            for info, raw in parts:
                root = roots.get(info.filename)
                archive.writestr(
                    info,
                    etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
                    if root is not None and etree.tostring(root) != original_trees[info.filename]
                    else raw,
                )
        os.replace(temp, output)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return output


def condition_keys(source, fields, document_type):
    """Return validated conditional discriminators without reading runtime data."""
    keys = set()
    with ZipFile(source) as archive:
        for info in archive.infolist():
            if info.filename.startswith('word/') and info.filename.endswith('.xml'):
                blocks, _ = plan(etree.fromstring(archive.read(info)), fields, document_type)
                keys.update(condition.key for condition, _ in blocks)
    return keys


def retained_scalar_keys(source, fields, document_type, context):
    """Return placeholders from the selected branches; all branches stay schema-validated."""
    keys = set()
    with ZipFile(source) as archive:
        for info in archive.infolist():
            if not (info.filename.startswith('word/') and info.filename.endswith('.xml')):
                continue
            root = etree.fromstring(archive.read(info)); blocks, _ = plan(root, fields, document_type)
            for condition, nodes in blocks:
                keep = condition.evaluate(context, fields, document_type)
                for node in (nodes[0], nodes[-1]) if keep else nodes:
                    node.getparent().remove(node)
            for p in root.xpath('.//w:p', namespaces=NS):
                for match in TOKEN.finditer(paragraph_text(p)):
                    field_spec(match[1], fields, document_type)
                    keys.add(match[1])
    return keys


def render(source, output, context, fields, document_type):
    """Flat canonical context; validate everything before atomic output creation."""
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ConditionalError('Source template не можна перезаписувати')
    with ZipFile(source) as archive:
        parts = [(info, archive.read(info)) for info in archive.infolist()]
    roots = {}
    original_trees = {}
    plans = {}
    for info, raw in parts:
        if info.filename.startswith('word/') and info.filename.endswith('.xml'):
            root = etree.fromstring(raw)
            roots[info.filename] = root
            original_trees[info.filename] = etree.tostring(root)
            plans[info.filename] = plan(root, fields, document_type)
    # Validate all condition values even if another branch would be false.
    decisions = {name: [(condition.evaluate(context, fields, document_type), nodes)
                        for condition, nodes in blocks]
                 for name, (blocks, _) in plans.items()}
    for field in fields:
        if document_type in field.get('required_for', []):
            field_spec(field['key'], fields, document_type)
            if context.get(field['key']) is None or context.get(field['key']) == '':
                raise ConditionalError('Не заповнено обов’язкове поле: ' + field['key'])
    for name, root in roots.items():
        for keep, nodes in decisions[name]:
            for node in (nodes[0], nodes[-1]) if keep else nodes:
                node.getparent().remove(node)
        # Resolve scalars only in retained content; reuse the existing run-safe engine.
        values = {}
        for p in root.xpath('.//w:p', namespaces=NS):
            for match in TOKEN.finditer(paragraph_text(p)):
                key = match[1]
                value = context.get(key)
                if value is None:
                    raise ConditionalError('Відсутнє значення placeholder: ' + key)
                if isinstance(value, (dict, list, tuple)):
                    raise ConditionalError('Scalar placeholder не підтримує object/array: ' + key)
                if '{{' in str(value) or '}}' in str(value):
                    raise ConditionalError('Значення містить службові markers: ' + key)
                values[key] = value
        replace_tokens(root, values)
        # Word requires a final paragraph in a cell; reuse one, not an empty row.
        for cell in root.xpath('.//w:tc', namespaces=NS):
            if not len(cell) or etree.QName(cell[-1]).localname != 'p':
                cell.append(etree.Element('{'+NS['w']+'}p'))
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(suffix='.docx', dir=output.parent)
    os.close(fd)
    try:
        with ZipFile(temp, 'w') as archive:
            for info, raw in parts:
                root = roots.get(info.filename)
                archive.writestr(info, etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
                                 if root is not None and etree.tostring(root) != original_trees[info.filename] else raw)
        os.replace(temp, output)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return output
