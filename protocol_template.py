"""Data-only expansion of an operator-formatted DOCX. No layout decisions here."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import os
import re
import tempfile
from zipfile import ZipFile, BadZipFile

from lxml import etree

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
TOKEN = re.compile(r'\{\{\s*([a-z_]+(?:\.[a-z_]+)?)\s*\}\}')
SCALARS = {'protocol_number', 'protocol_date', 'officer_name', 'officer_signature_name',
           'officer_verb', 'period_start', 'period_end', 'count_all', 'count_admitted', 'count_rejected'}
GROUPS = ('applications_all', 'applications_admitted', 'applications_rejected')
ROW_FIELDS = {'row_number', 'supplier_name', 'supplier_code', 'framework_id_display',
              'cpv_category', 'submission_date'}
CPV_CODE = re.compile(r'^\d{8}-\d$')


class TemplateError(ValueError):
    pass


def template_path():
    explicit = os.environ.get('PQM_APPLICATION_PROTOCOL_TEMPLATE')
    if explicit:
        return Path(explicit)
    runtime = Path(os.environ.get('PQM_DATA_DIR', Path(__file__).parent / 'data')) / 'templates' / 'application_protocol.docx'
    return runtime if runtime.exists() else Path(__file__).parent / 'templates' / 'application_protocol.docx'


def date_text(value):
    try:
        return datetime.strptime((value or '')[:10], '%Y-%m-%d').strftime('%d.%m.%Y')
    except ValueError:
        return value or '—'


def canonical_cpv_code(value):
    """Return the canonical CPV token used for protocol sorting/display."""
    candidate = str(value or '').strip()
    return candidate if CPV_CODE.fullmatch(candidate) else candidate


def protocol_cpv_category(item):
    """Compose protocol-only CPV/title text without a duplicated leading CPV."""
    code = canonical_cpv_code(item.get('dk_code'))
    title = str(item.get('category_title') or '').strip()
    if code and title.startswith(code):
        suffix = title[len(code):]
        if not suffix or suffix[0].isspace() or suffix[0] in '-–—:':
            title = re.sub(r'^\s*[-–—:]?\s*', '', suffix)
    if code and title:
        return f'{code} — {title}'
    return code or title or '—'


def _submission_timestamp(value):
    raw = str(value or '').strip()
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return 0, parsed.astimezone(timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 1, raw.casefold()


def protocol_item_sort_key(item):
    code = canonical_cpv_code(item.get('dk_code'))
    return (
        0 if CPV_CODE.fullmatch(code) else 1,
        code,
        *_submission_timestamp(item.get('date_published')),
        str(item.get('id') or item.get('submission_id') or ''),
    )


def sorted_protocol_items(items):
    """Stable deterministic order: canonical CPV, full submission time, ID."""
    return sorted(items, key=protocol_item_sort_key)


def context(payload):
    items = sorted_protocol_items(payload['items'])
    admitted = [x for x in items if x.get('protocol_decision') == 'admit']
    rejected = [x for x in items if x.get('protocol_decision') == 'reject']
    if len(items) != len(admitted) + len(rejected):
        raise ValueError('Кількість заявок не узгоджена з рішеннями допуску/відхилення')
    officer = payload['officer']
    first_name = officer.split()[0].casefold() if officer else ''
    values = dict(protocol_number=payload['protocol_number'], protocol_date=date_text(payload['protocol_date']),
                  officer_name=officer, officer_signature_name=officer,
                  officer_verb='склала' if first_name.endswith(('а', 'я')) else 'склав',
                  period_start=date_text(payload['date_from']), period_end=date_text(payload['date_to']),
                  count_all=len(items), count_admitted=len(admitted), count_rejected=len(rejected))
    groups = {}
    for key, rows in zip(GROUPS, (items, admitted, rejected)):
        groups[key] = [dict(row_number=i, supplier_name=x.get('supplier_name') or '—',
                            supplier_code=x.get('supplier_code') or '—', framework_id_display=x.get('pretty_id') or '—',
                            cpv_category=protocol_cpv_category(x),
                            submission_date=date_text(x.get('date_published')),
                            protocol_remarks=x.get('protocol_remarks') or '—') for i, x in enumerate(rows, 1)]
    return values, groups


def paragraph_text(paragraph):
    return ''.join(paragraph.xpath('.//w:t/text()', namespaces=NS))


def replace_tokens(root, values):
    """Replace even run-split markers, preserving runs, properties and surrounding text."""
    for paragraph in root.xpath('.//w:p', namespaces=NS):
        nodes = paragraph.xpath('.//w:t', namespaces=NS)
        full = ''.join(n.text or '' for n in nodes)
        for match in reversed(list(TOKEN.finditer(full))):
            if match.group(1) not in values:
                continue
            offset = 0
            for node in nodes:
                text = node.text or ''
                start, end = offset, offset + len(text)
                offset = end
                if end <= match.start() or start >= match.end():
                    continue
                left, right = max(0, match.start()-start), min(len(text), match.end()-start)
                replacement = str(values[match.group(1)]) if start <= match.start() < end else ''
                node.text = text[:left] + replacement + text[right:]
                node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')


def validate(root):
    tokens = {m.group(1) for p in root.xpath('.//w:p', namespaces=NS) for m in TOKEN.finditer(paragraph_text(p))}
    if not SCALARS.issubset(tokens):
        raise TemplateError('У шаблоні відсутні змінні: ' + ', '.join(sorted(SCALARS-tokens)))
    prototypes = {}
    allowed = set(SCALARS)
    for group in GROUPS:
        fields = ROW_FIELDS | ({'protocol_remarks'} if group == GROUPS[2] else set())
        expected = {group+'.'+key for key in fields}
        allowed |= expected
        rows = [row for row in root.xpath('.//w:tr', namespaces=NS)
                if any(group+'.' in paragraph_text(p) for p in row.xpath('.//w:p', namespaces=NS))]
        if len(rows) != 1:
            raise TemplateError('Потрібен один рядок-зразок: ' + group)
        found = {m.group(1) for p in rows[0].xpath('.//w:p', namespaces=NS) for m in TOKEN.finditer(paragraph_text(p))}
        if found != expected:
            raise TemplateError('Некоректні змінні рядка: ' + group)
        prototypes[group] = rows[0]
    if tokens - allowed:
        raise TemplateError('Невідомі змінні шаблону: ' + ', '.join(sorted(tokens-allowed)))
    return prototypes


def build_from_template(payload, output_path, source=None):
    values, groups = context(payload)
    source = Path(source) if source is not None else template_path()
    try:
        with ZipFile(source) as archive:
            parts = {x.filename: (x, archive.read(x)) for x in archive.infolist()}
        root = etree.fromstring(parts['word/document.xml'][1])
        prototypes = validate(root)
    except TemplateError:
        raise
    except (OSError, BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
        raise TemplateError('Не вдалося прочитати DOCX-шаблон протоколу') from exc
    replace_tokens(root, values)
    for group, prototype in prototypes.items():
        for row in groups[group]:
            clone = deepcopy(prototype)
            replace_tokens(clone, {group+'.'+k: v for k, v in row.items()})
            prototype.addprevious(clone)
        prototype.getparent().remove(prototype)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(suffix='.docx', dir=output_path.parent)
    os.close(fd)
    try:
        with ZipFile(temporary, 'w') as archive:
            for name, (info, data) in parts.items():
                archive.writestr(info, etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
                                 if name == 'word/document.xml' else data)
        os.replace(temporary, output_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return output_path
