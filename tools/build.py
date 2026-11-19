#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build reproducible CPython-2.7 packages; inspect structure without execution.

--verify deliberately does not deserialize or execute untrusted bytecode.
Only the build helper reads code objects it has just compiled from this checkout.
Neither operation proves compatibility with a live game client.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SRC = os.path.join(ROOT, 'src')
OUT = os.path.join(ROOT, 'dist')
GAME_ROOT = 'res/scripts/client/gui/mods/'
ENTRY = GAME_ROOT + 'mod_tanksession_analytics.pyc'
PY27_MAGIC = b'\x03\xf3\r\n'
ZIP_DATE = (2000, 1, 1, 0, 0, 0)
MAX_PACKAGE_BYTES = 16 * 1024 * 1024
MAX_MEMBER_BYTES = 2 * 1024 * 1024
# An explicit release manifest also detects an accidentally omitted dependency.
REQUIRED_MODULES = frozenset([ENTRY] + [
    GAME_ROOT + 'tanksession_analytics/' + name + '.pyc'
    for name in ('__init__', 'analytics', 'core', 'game', 'goals',
                 'recorder', 'recovery', 'storage')
])
_SAFE_METADATA = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')


def _metadata(raw):
    root = ET.fromstring(raw)
    if root.tag != 'root':
        raise ValueError('meta.xml root element must be <root>')
    mod_id, version = root.findtext('id'), root.findtext('version')
    if not mod_id or not version or not root.findtext('name'):
        raise ValueError('Incomplete mod metadata')
    if not _SAFE_METADATA.fullmatch(mod_id) or not _SAFE_METADATA.fullmatch(version):
        raise ValueError('Unsafe mod ID or version')
    return mod_id, version


def project_metadata():
    with open(os.path.join(SRC, 'meta.xml'), 'rb') as source:
        return _metadata(source.read())


def verify_mtmod(path, expected_id=None, expected_version=None):
    """Inspect the current project's manifest, metadata, CRCs and pyc headers.

    A forged header can pass this structural check. This function never treats
    an arbitrary archive as executable and never claims to validate game APIs.
    By default the ID/version must match src/meta.xml in this checkout.
    """
    project_id, project_version = project_metadata()
    expected_id = project_id if expected_id is None else expected_id
    expected_version = project_version if expected_version is None else expected_version
    if os.path.getsize(path) > MAX_PACKAGE_BYTES:
        raise ValueError('Package exceeds the size limit')
    with zipfile.ZipFile(path, 'r') as archive:
        members = archive.infolist()
        names = [item.filename for item in members]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate ZIP member names')
        if not members or any(item.compress_type != zipfile.ZIP_STORED for item in members):
            raise ValueError('An .mtmod must be a non-compressed ZIP')
        if (len(members) > 128 or
                sum(item.file_size for item in members) > MAX_PACKAGE_BYTES or
                any(item.file_size > MAX_MEMBER_BYTES for item in members)):
            raise ValueError('Package members exceed the size limit')
        for item in members:
            # ZipInfo normalizes separators on Windows even while reading.
            # Check the original central-directory name before trusting it.
            name = item.orig_filename
            if (name != item.filename or not name or name.startswith('/') or '\\' in name or
                    ':' in name or any(part in ('', '.', '..') for part in name.split('/'))):
                raise ValueError('Unsafe path in .mtmod: ' + name)
        if 'meta.xml' not in names or ENTRY not in names:
            raise ValueError('Missing meta.xml or mod entrypoint')
        if any(name.endswith('.py') for name in names):
            raise ValueError('Source .py files must not be shipped in this game package')
        missing = REQUIRED_MODULES.difference(names)
        if missing:
            raise ValueError('Missing required modules: ' + ', '.join(sorted(missing)))
        unexpected = set(names).difference(REQUIRED_MODULES | {'meta.xml'})
        if unexpected:
            raise ValueError('Unexpected package files: ' + ', '.join(sorted(unexpected)))
        mod_id, version = _metadata(archive.read('meta.xml'))
        if mod_id != expected_id:
            raise ValueError('Unexpected mod ID')
        if version != expected_version:
            raise ValueError('Unexpected version')
        # read() checks each member's CRC. No marshal.loads/import/exec here.
        for name in sorted(REQUIRED_MODULES):
            data = archive.read(name)
            if len(data) <= 8:
                raise ValueError('Missing or empty compiled game module: ' + name)
            if data[:4] != PY27_MAGIC:
                raise ValueError('Expected a CPython 2.7 bytecode header: ' + name)
            if data[8:9] != b'c':
                raise ValueError('Expected a marshalled code-object marker: ' + name)
        return {'id': mod_id, 'version': version,
                'compiled_modules': len(REQUIRED_MODULES),
                'validation': 'structure-and-headers-only'}


def _compiler_environment():
    environment = os.environ.copy()
    environment.pop('PYTHONPATH', None)
    environment.pop('PYTHONHOME', None)
    environment.pop('PYTHONOPTIMIZE', None)
    environment['PYTHONHASHSEED'] = '0'
    environment['PYTHONNOUSERSITE'] = '1'
    return environment


def _check_interpreter(python2, environment):
    code = ('import json, platform, sys; '
            'print(json.dumps({"implementation": platform.python_implementation(), '
            '"version": list(sys.version_info[:3])}))')
    result = subprocess.run([python2, '-S', '-B', '-c', code],
                            capture_output=True, text=True, check=True,
                            env=environment, timeout=30)
    try:
        info = json.loads(result.stdout)
        valid = info['implementation'] == 'CPython' and info['version'][:2] == [2, 7]
    except (ValueError, TypeError, KeyError):
        valid = False
    if not valid:
        raise ValueError('--python2 must point to a real CPython 2.7 interpreter')
    return info


def build(python2):
    environment = _compiler_environment()
    interpreter = _check_interpreter(python2, environment)
    mod_id, version = project_metadata()
    source_names = set()
    for base, folders, files in os.walk(SRC):
        folders[:] = sorted(name for name in folders if name != '__pycache__')
        for name in sorted(files):
            if not name.endswith('.py'):
                continue
            path = os.path.join(base, name)
            if os.path.islink(path):
                raise ValueError('Source symlinks are not supported')
            relative = os.path.relpath(path, SRC).replace(os.sep, '/')
            source_names.add(relative)
    if {name + 'c' for name in source_names} != REQUIRED_MODULES:
        raise ValueError('Source modules differ from the release manifest; update REQUIRED_MODULES')
    os.makedirs(OUT, exist_ok=True)
    target = os.path.join(OUT, '%s_%s.mtmod' % (mod_id, version))
    with tempfile.TemporaryDirectory(prefix='tanksession-build-') as temp:
        stage = os.path.join(temp, 'stage')
        os.makedirs(stage)
        shutil.copyfile(os.path.join(SRC, 'meta.xml'), os.path.join(stage, 'meta.xml'))
        for name in sorted(source_names):
            destination = os.path.join(stage, *name.split('/'))
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copyfile(os.path.join(SRC, *name.split('/')), destination)
        helper = os.path.join(ROOT, 'tools', 'verify_python2.py')
        compiled = subprocess.run(
            [python2, '-S', '-B', helper, '--compile-stage', stage],
            capture_output=True, text=True, check=True, env=environment, timeout=120)
        compiled_info = json.loads(compiled.stdout)
        if (compiled_info.get('compiled_modules') != len(REQUIRED_MODULES) or
                not compiled_info.get('code_objects_checked')):
            raise ValueError('Compiler did not verify every generated code object')
        # Use an adjacent temporary output so os.replace stays on one filesystem.
        temporary_fd, temporary_target = tempfile.mkstemp(prefix='.tanksession-', dir=OUT)
        os.close(temporary_fd)
        try:
            with zipfile.ZipFile(temporary_target, 'w', zipfile.ZIP_STORED) as archive:
                for name in sorted(REQUIRED_MODULES | {'meta.xml'}):
                    info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
                    info.compress_type = zipfile.ZIP_STORED
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    with open(os.path.join(stage, *name.split('/')), 'rb') as source:
                        archive.writestr(info, source.read())
            info = verify_mtmod(temporary_target, mod_id, version)
            with open(temporary_target, 'rb') as output:
                digest = hashlib.sha256(output.read()).hexdigest()
            os.replace(temporary_target, target)
        finally:
            if os.path.exists(temporary_target):
                os.remove(temporary_target)
    with open(target + '.sha256', 'w', encoding='ascii', newline='\n') as checksum:
        checksum.write('%s  %s\n' % (digest, os.path.basename(target)))
    info.update({'sha256': digest, 'code_objects_checked': True,
                 'build_interpreter': interpreter})
    return target, info


def main():
    parser = argparse.ArgumentParser(description='Build or structurally inspect TankSession .mtmod')
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--python2', help='Path to a real CPython 2.7 build interpreter')
    actions.add_argument('--verify', metavar='PATH', help='Inspect manifest/headers only; never executes code')
    args = parser.parse_args()
    try:
        if args.python2:
            target, info = build(args.python2)
            print('Created with CPython 2.7: %s' % target)
            print('Generated code objects checked; SHA-256: %s' % info['sha256'])
        else:
            info = verify_mtmod(args.verify)
        print('Structure and headers OK: %s %s; modules: %d' % (
            info['id'], info['version'], info['compiled_modules']))
        print('This does NOT verify bytecode behavior or live game compatibility.')
    except subprocess.CalledProcessError as error:
        details = (error.stderr or '').strip()
        parser.exit(1, 'Compiler failed: %s\n%s\n' % (error, details[-6000:]))
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile,
            subprocess.TimeoutExpired) as error:
        parser.exit(1, 'Build/verification failed: %s\n' % error)


if __name__ == '__main__':
    main()
