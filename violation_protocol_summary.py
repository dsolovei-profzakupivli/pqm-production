"""Read-only presentation of the current generated protocol; never infer its author."""
from functools import lru_cache
from pathlib import Path
from zipfile import ZipFile,BadZipFile
from xml.etree import ElementTree as ET
import json
from urllib.parse import quote

@lru_cache(maxsize=256)
def _signature(path,mtime,size):
    try:
        with ZipFile(path) as package:
            info=package.getinfo('word/document.xml')
            if info.file_size>4_000_000:return ''
            root=ET.fromstring(package.read(info))
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        # All three approved templates have a standalone body signature paragraph.
        # Never search free-text justifications, nested tables or current assignments.
        found=[]
        for paragraph in root.findall('w:body/w:p',ns):
            text=''.join(node.text or '' for node in paragraph.findall('.//w:t',ns)).strip()
            prefix='Уповноважена особа'
            if text.startswith(prefix):
                name=text[len(prefix):].strip()
                if 2<=len(name.split())<=6 and len(name)<160 and '{{' not in name and not any(c.isdigit() for c in name):found.append(name)
        return found[0] if len(found)==1 else ''
    except (OSError,BadZipFile,KeyError,ET.ParseError):return ''

def present(review,protocols_dir,json_ready):
    filename=str(review.get('generated_protocol_filename') or '')
    if not filename or Path(filename).name!=filename:return None
    root=Path(protocols_dir).resolve();path=(root/filename).resolve()
    if path.parent!=root or not path.is_file():return None
    try:stat=path.stat()
    except OSError:return None
    try:metadata=json.loads(review.get('generated_protocol_metadata_json') or '{}')
    except (ValueError,TypeError):metadata={}
    if not isinstance(metadata,dict):metadata={}
    subject=metadata.get('protocol_subject') or {}
    return dict(number=review.get('protocol_number') or '',date=review.get('protocol_date') or '',
        url='/api/protocol/files/'+quote(filename,safe=''),
        officer=_signature(str(path),stat.st_mtime_ns,stat.st_size),officer_source='generated_document',
        askod=subject.get('value','') if isinstance(subject,dict) else '',json_ready=bool(json_ready))
