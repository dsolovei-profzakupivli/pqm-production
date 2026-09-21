"""Linux-only PDF worker. Install inherited kernel network denial before exec.

This is not a filesystem sandbox: the caller supplies a generated DOCX in an
owned sandbox path. No application modules, credentials or DB are loaded here.
"""
import ctypes
import os
from pathlib import Path
import socket
import sys


def deny_network():
    if sys.platform != 'linux':
        raise RuntimeError('Sandbox PDF requires Linux seccomp')
    lib = ctypes.CDLL('libseccomp.so.2', use_errno=True)
    class Compare(ctypes.Structure):
        _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_int),
                    ('datum_a', ctypes.c_uint64), ('datum_b', ctypes.c_uint64)]
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                         ctypes.c_int, ctypes.c_uint, ctypes.POINTER(Compare)]
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = lib.seccomp_init(0x7fff0000)
    if not ctx:
        raise RuntimeError('Cannot initialize PDF network filter')
    try:
        for name in (b'socket', b'socketpair', b'io_uring_setup'):
            number = lib.seccomp_syscall_resolve_name(name)
            comparison = Compare(0, 1, socket.AF_UNIX, 0)
            count = 0 if name == b'io_uring_setup' else 1
            if number < 0 or lib.seccomp_rule_add_array(
                    ctx, 0x50001, number, count, ctypes.byref(comparison) if count else None):
                raise RuntimeError('Cannot configure PDF network filter')
        if lib.seccomp_load(ctx):
            raise RuntimeError('Cannot activate PDF network filter')
    finally:
        lib.seccomp_release(ctx)


def main():
    source, folder = map(lambda s: Path(s).resolve(strict=True), sys.argv[1:])
    if source.suffix.lower() != '.docx' or not source.is_file() or not folder.is_dir():
        raise RuntimeError('Invalid PDF fixture paths')
    deny_network()
    executable = '/usr/bin/soffice'
    os.execve(executable, [executable, '-env:UserInstallation=' + (folder / 'profile').as_uri(),
                          '--headless', '--convert-to', 'pdf', '--outdir', str(folder), str(source)],
              {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})


if __name__ == '__main__':
    main()
