#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a Python-2.7 compiled .mtmod or verify package structure offline."""
import argparse
import os
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


def verify_mtmod(path, expected_id=None, expected_version=None):
    """Verify archive layout; this is NOT a test of game compatibility."""
    with zipfile.ZipFile(path, 'r') as archive:
        members = archive.infolist()
        names = [item.filename for item in members]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate ZIP member names')
        if not members or any(item.compress_type != zipfile.ZIP_STORED for item in members):
            raise ValueError('An .mtmod must be a non-compressed ZIP')
        for name in names:
            if (not name or name.startswith('/') or '\\' in name or
                    ':' in name or any(part in ('', '..') for part in name.rstrip('/').split('/'))):
                raise ValueError('Unsafe path in .mtmod: ' + name)
        if 'meta.xml' not in names or ENTRY not in names:
            raise ValueError('Missing meta.xml or mod entrypoint')
        if any(name.endswith('.py') for name in names):
            raise ValueError('Source .py files must not be shipped in this game package')
        root = ET.fromstring(archive.read('meta.xml'))
        if root.tag != 'root':
            raise ValueError('meta.xml root element must be <root>')
        mod_id = root.findtext('id')
        version = root.findtext('version')
        if not mod_id or not version or not root.findtext('name'):
            raise ValueError('Incomplete mod metadata')
        if expected_id and mod_id != expected_id:
            raise ValueError('Unexpected mod ID')
        if expected_version and version != expected_version:
            raise ValueError('Unexpected version')
        compiled = [name for name in names if name.endswith('.pyc')]
        if len(compiled) < 2 or any(archive.getinfo(name).file_size < 8 for name in compiled):
            raise ValueError('Missing or empty compiled game modules')
        return {'id': mod_id, 'version': version, 'compiled_modules': len(compiled)}


def build(python2):
    version_check = subprocess.run(
        [python2, '-c', 'import sys; print("%d.%d" % sys.version_info[:2])'],
        capture_output=True, text=True, check=True)
    if version_check.stdout.strip() != '2.7':
        raise ValueError('--python2 must point to a real Python 2.7 interpreter')
    metadata = ET.parse(os.path.join(SRC, 'meta.xml')).getroot()
    mod_id, version = metadata.findtext('id'), metadata.findtext('version')
    if metadata.tag != 'root' or not mod_id or not version:
        raise ValueError('Invalid src/meta.xml')
    os.makedirs(OUT, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        stage = os.path.join(temp, 'stage')
        shutil.copytree(SRC, stage, ignore=shutil.ignore_patterns(
            '__pycache__', '*.pyc', '*.pyo', '.DS_Store'))
        code_root = os.path.join(stage, *GAME_ROOT.rstrip('/').split('/'))
        subprocess.run([python2, '-m', 'compileall', '-q', code_root], check=True)
        source_paths = []
        for base, _, files in os.walk(stage):
            for name in files:
                if name.endswith('.py'):
                    source_paths.append(os.path.join(base, name))
        if not source_paths:
            raise ValueError('No Python source code to compile')
        for source in source_paths:
            if not os.path.isfile(source + 'c'):
                raise ValueError('Python 2.7 did not compile ' + os.path.relpath(source, stage))
            os.remove(source)
        target = os.path.join(OUT, '%s_%s.mtmod' % (mod_id, version))
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_STORED) as archive:
            for base, _, files in os.walk(stage):
                for name in sorted(files):
                    full = os.path.join(base, name)
                    archive.write(full, os.path.relpath(full, stage).replace(os.sep, '/'))
    info = verify_mtmod(target, mod_id, version)
    return target, info


def main():
    parser = argparse.ArgumentParser(description='Compile or verify TankSession .mtmod (offline)')
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument('--python2', help='Path to a real Python 2.7 interpreter for build')
    actions.add_argument('--verify', metavar='PATH', help='Inspect an existing .mtmod, without compiling')
    args = parser.parse_args()
    try:
        if args.python2:
            target, info = build(args.python2)
            print('Created: %s' % target)
        else:
            info = verify_mtmod(args.verify)
        print('Package OK: %s %s; modules: %d' % (
            info['id'], info['version'], info['compiled_modules']))
        print('WARNING: real game compatibility has NOT been verified.')
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        parser.exit(1, 'Build/verification failed: %s\n' % error)


if __name__ == '__main__':
    main()
