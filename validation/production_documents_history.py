"""Attested previous Production tree for unchanged contracts; no Git/DB access."""
import hashlib,json,tempfile,zipfile
from pathlib import Path
BASE='98c7f8a50840b1fed81d80f23740563d233d3207'
ARCHIVE='validation/fixtures/production_documents_parent_98c7f8a.zip'
PIN='b814fa63f7c7c8907c1893443c79290cf4f0d8c08e1709d5daa76d33d85f8c95'
_TEMPS=[]
_CACHE={}
def blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
def baseline_root(source):
 source=Path(source).resolve();raw=(source/ARCHIVE).read_bytes()
 if hashlib.sha256(raw).hexdigest()!=PIN:raise AssertionError('Production baseline archive changed')
 if source not in _CACHE:
  with zipfile.ZipFile(source/ARCHIVE) as z:
   index=json.loads(z.read('INDEX.json'))
   if z.comment.decode()!=BASE or index['sha']!=BASE:raise AssertionError('Wrong Production baseline SHA')
   if set(z.namelist())!={'INDEX.json',*('files/'+n for n in index['overrides'])}:raise AssertionError('Unexpected baseline members')
   tmp=tempfile.TemporaryDirectory(prefix='pqm-production-documents-parent-');_TEMPS.append(tmp);root=Path(tmp.name)
   for name,metadata in index['files'].items():
    target=root/name;target.resolve().relative_to(root.resolve())
    content=z.read('files/'+name) if name in index['overrides'] else (source/name).read_bytes()
    if blob(content)!=metadata['oid']:content=content.replace(b'\r\n',b'\n')
    if blob(content)!=metadata['oid']:raise AssertionError('Baseline Git blob changed: '+name)
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
  _CACHE[source]=root
 return _CACHE[source]
