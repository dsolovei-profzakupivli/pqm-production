"""Opt-in canonical DOCX provider. Existing runtime renderers stay unchanged."""
import os
import re
import tempfile
from copy import deepcopy
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
from lxml import etree
from protocol_template import NS, TOKEN, paragraph_text, replace_tokens
from template_conditions import ConditionalError, Condition, field_spec, parse_marker

REPEAT_OPEN = re.compile(r'\{\{#repeat\s+([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+\[\])\s*\}\}')
REPEAT_CLOSE = '{{/repeat}}'
SCOPED_TOKEN = re.compile(r'\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}')
REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
HYPERLINK_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink'


@dataclass(frozen=True)
class Repeat:
    key: str
    nodes: tuple
    scoped_keys: tuple


def _paragraphs(node):
    return ([node] if etree.QName(node).localname=='p' else [])+node.xpath('.//w:p',namespaces=NS)


def _standalone_marker(paragraph):
    if paragraph.xpath('.//w:sectPr | .//w:drawing | .//w:r/w:br | .//w:r/w:tab', namespaces=NS):
        raise ConditionalError('Repeat marker має бути окремим текстовим абзацом')
    parent=paragraph.getparent()
    if etree.QName(parent).localname not in ('body','hdr','ftr','tc'):
        raise ConditionalError('Непідтримуваний контейнер repeat marker')
    return parent


def repeat_plan(root, fields, document_type):
    """Validate standalone paragraph-group repeats before any DOCX mutation."""
    pending=None; repeats=[]
    for paragraph in root.xpath('.//w:p',namespaces=NS):
        text=paragraph_text(paragraph).strip()
        opening=REPEAT_OPEN.fullmatch(text)
        if opening:
            if pending:raise ConditionalError('Вкладені repeat не підтримуються')
            collection=field_spec(opening.group(1),fields,document_type)
            if collection.get('value_type')!='array<object>':
                raise ConditionalError('Repeat потребує array<object>: '+opening.group(1))
            pending=(paragraph,collection);_standalone_marker(paragraph);continue
        if text==REPEAT_CLOSE:
            if not pending:raise ConditionalError('Закриваючий repeat без opening marker')
            start,collection=pending;parent=_standalone_marker(paragraph)
            if start.getparent() is not parent:raise ConditionalError('Repeat не може перетинати контейнери DOCX')
            siblings=list(parent);nodes=tuple(siblings[siblings.index(start):siblings.index(paragraph)+1])
            if any(node.xpath('.//w:sectPr',namespaces=NS) for node in nodes):
                raise ConditionalError('Repeat не може містити межу секції')
            if any('{{#if' in paragraph_text(p) or '{{/if}}' in paragraph_text(p)
                   for node in nodes[1:-1] for p in node.xpath('.//w:p',namespaces=NS)):
                raise ConditionalError('Вкладені if у repeat не підтримуються')
            allowed={item['key'].rsplit('.',1)[-1] for item in collection.get('item_schema',[])}
            scoped=set()
            for node in nodes[1:-1]:
                for p in _paragraphs(node):
                    scoped.update(SCOPED_TOKEN.findall(paragraph_text(p)))
            unknown=scoped-allowed
            if unknown:raise ConditionalError('Невідоме поле repeat scope: '+', '.join(sorted(unknown)))
            if not scoped:raise ConditionalError('Repeat block не містить полів елемента: '+collection['key'])
            for name in scoped:field_spec(collection['key']+'.'+name,fields,document_type)
            repeats.append(Repeat(collection['key'],nodes,tuple(sorted(scoped))));pending=None
    if pending:raise ConditionalError('Незакритий repeat')
    return repeats


def _format_value(field,value):
    if value is None:return value
    if field.get('default_format')=='dd.MM.yyyy':
        raw=str(value).strip()
        try:return datetime.fromisoformat(raw[:10]).strftime('%d.%m.%Y')
        except ValueError:return raw
    return value


def _hyperlink_run(source_run, value, relationship_id):
    hyperlink=etree.Element('{'+NS['w']+'}hyperlink')
    hyperlink.set('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id',relationship_id)
    hyperlink.set('{'+NS['w']+'}history','1')
    run=etree.SubElement(hyperlink,'{'+NS['w']+'}r')
    properties=source_run.find('{'+NS['w']+'}rPr')
    properties=deepcopy(properties) if properties is not None else etree.Element('{'+NS['w']+'}rPr')
    # Keep the template's font, size, emphasis and language, but make the
    # generated external relationship visibly identifiable as a hyperlink.
    for name in ('color','u'):
        for node in properties.findall('{'+NS['w']+'}'+name):properties.remove(node)
    color=etree.SubElement(properties,'{'+NS['w']+'}color');color.set('{'+NS['w']+'}val','0563C1')
    underline=etree.SubElement(properties,'{'+NS['w']+'}u');underline.set('{'+NS['w']+'}val','single')
    run.append(properties)
    text=etree.SubElement(run,'{'+NS['w']+'}t');text.text=str(value)
    text.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
    return hyperlink


def _replace_with_hyperlink(paragraph, nodes, match, value, relationship_id):
    """Replace one run-split token with a real external hyperlink in-place."""
    offsets=[];offset=0
    for node in nodes:
        text=node.text or '';offsets.append((node,offset,offset+len(text),text));offset+=len(text)
    touched=[entry for entry in offsets if entry[2]>match.start() and entry[1]<match.end()]
    if not touched:raise ConditionalError('Не вдалося знайти URL placeholder у paragraph')
    first, last=touched[0],touched[-1]
    first_run=first[0].getparent();last_run=last[0].getparent()
    if etree.QName(first_run).localname!='r' or etree.QName(last_run).localname!='r':
        raise ConditionalError('URL placeholder має бути звичайним текстом Word')
    prefix=first[3][:max(0,match.start()-first[1])]
    suffix=last[3][max(0,match.end()-last[1]):]
    for node,start,end,text in touched:
        if node is first[0]:node.text=prefix
        elif node is last[0]:node.text=suffix
        else:node.text=''
    hyperlink=_hyperlink_run(first_run,value,relationship_id)
    if first_run is last_run:
        # A token embedded in one run needs a separate suffix run so document
        # order remains prefix -> hyperlink -> suffix.
        suffix_run=deepcopy(first_run)
        for child in list(suffix_run):
            if etree.QName(child).localname!='rPr':suffix_run.remove(child)
        if suffix:
            text=etree.SubElement(suffix_run,'{'+NS['w']+'}t');text.text=suffix
            text.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
        first[0].text=prefix
        first_run.addnext(suffix_run);first_run.addnext(hyperlink)
    else:
        first_run.addnext(hyperlink)


def _replace_scoped_tokens(root, values, specs=None, hyperlink_id=None, hyperlink_targets=None):
    """Replace repeat-local tokens while preserving source runs and formatting."""
    for paragraph in _paragraphs(root):
        nodes=paragraph.xpath('.//w:t',namespaces=NS);full=''.join(node.text or '' for node in nodes)
        for match in reversed(list(SCOPED_TOKEN.finditer(full))):
            if match.group(1) not in values:continue
            value=str(values[match.group(1)])
            if '{{' in value or '}}' in value:raise ConditionalError('Repeat value містить службові markers')
            field=(specs or {}).get(match.group(1),{})
            target=(hyperlink_targets or {}).get(match.group(1))
            if target:
                if not hyperlink_id:raise ConditionalError('Hyperlink placeholder не має relationship provider')
                _replace_with_hyperlink(paragraph,nodes,match,value,hyperlink_id(target))
                continue
            if field.get('value_type')=='url':
                if not hyperlink_id:raise ConditionalError('URL placeholder не має relationship provider')
                _replace_with_hyperlink(paragraph,nodes,match,value,hyperlink_id(value))
                continue
            offset=0
            for node in nodes:
                text=node.text or '';start,end=offset,offset+len(text);offset=end
                if end<=match.start() or start>=match.end():continue
                left,right=max(0,match.start()-start),min(len(text),match.end()-start)
                replacement=value if start<=match.start()<end else ''
                node.text=text[:left]+replacement+text[right:]
                node.set('{http://www.w3.org/XML/1998/namespace}space','preserve')


def _expand_repeats(root, repeats, context, fields, document_type, hyperlink_id=None):
    lookup={field['key']:field for field in fields}
    for repeat in repeats:
        items=context.get(repeat.key)
        if not isinstance(items,list):raise ConditionalError('Відсутній або некоректний repeat context: '+repeat.key)
        start=repeat.nodes[0]
        for item in items:
            if not isinstance(item,dict):raise ConditionalError('Некоректний елемент repeat context: '+repeat.key)
            values={}
            for name in repeat.scoped_keys:
                value=item.get(name)
                if value is None:raise ConditionalError('Відсутнє значення repeat placeholder: '+name)
                if isinstance(value,(dict,list,tuple)):raise ConditionalError('Repeat placeholder не підтримує object/array: '+name)
                values[name]=_format_value(lookup[repeat.key+'.'+name],value)
            specs={name:lookup[repeat.key+'.'+name] for name in repeat.scoped_keys}
            hyperlink_targets={}
            for name,field in specs.items():
                target_key=field.get('hyperlink_target_field')
                if target_key:
                    target_name=target_key.rsplit('.',1)[-1]
                    target=str(item.get(target_name) or '').strip()
                    if not re.match(r'^https?://',target,re.I):
                        raise ConditionalError('Некоректна адреса hyperlink для repeat placeholder: '+name)
                    hyperlink_targets[name]=target
            for prototype in repeat.nodes[1:-1]:
                clone=deepcopy(prototype)
                _replace_scoped_tokens(clone,values,specs,hyperlink_id,hyperlink_targets)
                start.addprevious(clone)
        for node in repeat.nodes:node.getparent().remove(node)


def plan(root, fields, document_type, *, validate_scalars=True):
    """Validate all branches before mutation, including branches later excluded.

    Markers are standalone sibling paragraphs in body/header/footer/cell.
    A range may enclose paragraphs and whole tables, never cross containers.
    """
    repeats = repeat_plan(root,fields,document_type)
    repeat_paragraphs={p for repeat in repeats for node in repeat.nodes[1:-1]
                       for p in _paragraphs(node)}
    repeat_markers={p for repeat in repeats for p in (repeat.nodes[0],repeat.nodes[-1])}
    pending = None
    blocks = []
    scalars = set()
    for p in root.xpath('.//w:p', namespaces=NS):
        text = paragraph_text(p)
        if '{{' not in text and '}}' not in text:
            continue
        if p in repeat_markers:
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
            if p in repeat_paragraphs:
                residual = SCOPED_TOKEN.sub('',residual)
            if '{{' in residual or '}}' in residual:
                raise ConditionalError('Некоректний placeholder або inline conditional marker: ' + text)
            for match in TOKEN.finditer(text):
                if p in repeat_paragraphs and '.' not in match[1]:
                    continue
                field_spec(match[1], fields, document_type)
                scalars.add(match[1])
    if pending:
        raise ConditionalError('Незакритий if')
    for repeat in repeats:
        repeat_nodes=set(repeat.nodes)
        if any(repeat_nodes.intersection(nodes) for _,nodes in blocks):
            raise ConditionalError('Repeat та if blocks не можуть перетинатися')
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


def render(source, output, context, fields, document_type, aliases=None):
    """Flat canonical context; validate everything before atomic output creation."""
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ConditionalError('Source template не можна перезаписувати')
    with ZipFile(source) as archive:
        parts = [(info, archive.read(info)) for info in archive.infolist()]
    roots = {}
    original_trees = {}
    plans = {}
    repeat_plans = {}
    part_map={info.filename:(info,raw) for info,raw in parts}
    relationship_roots={}
    def relationship_part(part_name):
        folder,filename=part_name.rsplit('/',1)
        return folder+'/_rels/'+filename+'.rels'
    def add_hyperlink(part_name,url):
        rel_name=relationship_part(part_name)
        if rel_name not in relationship_roots:
            raw=part_map.get(rel_name,(None,None))[1]
            relationship_roots[rel_name]=(etree.fromstring(raw) if raw is not None else
                etree.Element('{'+REL_NS+'}Relationships',nsmap={None:REL_NS}))
        rels=relationship_roots[rel_name]
        existing={rel.get('Id') for rel in rels};number=1
        while 'rIdPqmHyperlink'+str(number) in existing:number+=1
        relationship_id='rIdPqmHyperlink'+str(number)
        rel=etree.SubElement(rels,'{'+REL_NS+'}Relationship',Id=relationship_id,
                            Type=HYPERLINK_REL,Target=str(url),TargetMode='External')
        return relationship_id
    for info, raw in parts:
        if info.filename.startswith('word/') and info.filename.endswith('.xml'):
            root = etree.fromstring(raw)
            if aliases:
                replace_tokens(root,{key:'{{'+value+'}}' for key,value in aliases.items()},
                               re.compile(r'\{\{\s*(.*?)\s*\}\}'))
            roots[info.filename] = root
            original_trees[info.filename] = etree.tostring(root)
            plans[info.filename] = plan(root, fields, document_type)
            repeat_plans[info.filename] = repeat_plan(root,fields,document_type)
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
        _expand_repeats(root,repeat_plans[name],context,fields,document_type,
                        lambda url,part=name:add_hyperlink(part,url))
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
                values[key] = _format_value(field_spec(key,fields,document_type),value)
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
                relationship_root=relationship_roots.get(info.filename)
                if relationship_root is not None:
                    archive.writestr(info,etree.tostring(relationship_root,xml_declaration=True,encoding='UTF-8',standalone=True))
                else:
                    archive.writestr(info, etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
                                     if root is not None and etree.tostring(root) != original_trees[info.filename] else raw)
            for name,root in relationship_roots.items():
                if name in part_map:continue
                info=ZipInfo(name);info.compress_type=ZIP_DEFLATED
                archive.writestr(info,etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True))
        os.replace(temp, output)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return output
