"""Immutable accepted-v1 inputs for its original exact-byte/mutation checks."""
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

ARCHIVE_SHA256 = '2334f0539c8149ddcb1ae8afb69b000d7c331bd7c9bbe0e13907848cd1710b49'
_TEMP = None


def accepted_stage1_root(source):
    global _TEMP
    if _TEMP is not None:
        return Path(_TEMP.name)
    archive_path = Path(source) / 'validation/fixtures/memory_stage1_accepted_v1.zip'
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise AssertionError('Accepted stage1 archive changed')
    _TEMP = tempfile.TemporaryDirectory(prefix='pqm-stage1-accepted-integrity-')
    root = Path(_TEMP.name)
    with zipfile.ZipFile(archive_path) as archive:
        manifest_name = 'validation/memory_stage1_integrity.json'
        raw = archive.read(manifest_name).replace(b'\r\n', b'\n')
        if hashlib.sha256(raw).hexdigest() != '4b4543ae2a901a1711e489e0447e88e5a86ceb33098240d04735b198491b662c':
            raise AssertionError('Accepted stage1 manifest changed')
        manifest = json.loads(raw)
        names = set(manifest['files']) | {manifest_name}
        if len(archive.namelist()) != len(names) or set(archive.namelist()) != names:
            raise AssertionError('Unexpected accepted stage1 file set')
        for name in names:
            target = root / name
            target.resolve().relative_to(root.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    return root
