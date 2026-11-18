#!/usr/bin/env python3
"""Compile Python 2.7 sources and package a .mtmod; never installs into game.

Requires an explicitly selected Python 2.7 executable because Python 3
bytecode cannot be loaded by this game client. No game files are modified.
"""
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


def main():
    parser = argparse.ArgumentParser(description='Build TankSession .mtmod using Python 2.7')
    parser.add_argument('--python2', required=True, help='Path to the Python 2.7 interpreter')
    args = parser.parse_args()
    version_check = subprocess.run([args.python2, '-c',
                                    'import sys; print("%d.%d" % sys.version_info[:2])'],
                                   capture_output=True, text=True, check=True)
    if version_check.stdout.strip() != '2.7':
        raise SystemExit('ERROR: --python2 must be an actual Python 2.7 executable')
    meta = ET.parse(os.path.join(SRC, 'meta.xml')).getroot()
    mod_id = meta.findtext('id')
    version = meta.findtext('version')
    if not mod_id or not version:
        raise SystemExit('ERROR: missing id/version in meta.xml')
    if not os.path.isdir(OUT):
        os.makedirs(OUT)
    with tempfile.TemporaryDirectory() as temp:
        stage = os.path.join(temp, 'stage')
        shutil.copytree(SRC, stage, ignore=shutil.ignore_patterns(
            '__pycache__', '*.pyc', '*.pyo', '.DS_Store'))
        code_root = os.path.join(stage, 'res', 'scripts', 'client', 'gui', 'mods')
        subprocess.run([args.python2, '-m', 'compileall', '-q', code_root], check=True)
        entry = os.path.join(code_root, 'mod_tanksession_analytics.pyc')
        if not os.path.isfile(entry):
            raise SystemExit('ERROR: compiled game entry point missing')
        for base, dirs, files in os.walk(stage):
            for file_name in files:
                if file_name.endswith('.py'):
                    os.remove(os.path.join(base, file_name))
        archive = os.path.join(OUT, '%s_%s.mtmod' % (mod_id, version))
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_STORED) as output:
            for base, dirs, files in os.walk(stage):
                for file_name in sorted(files):
                    full = os.path.join(base, file_name)
                    arcname = os.path.relpath(full, stage).replace(os.sep, '/')
                    output.write(full, arcname)
        with zipfile.ZipFile(archive) as check:
            assert 'res/scripts/client/gui/mods/mod_tanksession_analytics.pyc' in check.namelist()
            assert 'meta.xml' in check.namelist()
        print('Created: %s' % archive)
        print('Game compatibility remains untested; see docs/integration.md')


if __name__ == '__main__':
    main()
