#!/usr/bin/env python3
"""Package a tested, standalone native companion and its Python 3 adapter.

Only explicit public project files are included. No game installation, private
journal, profile, build cache, compiler or downloaded test dependency is read.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import zipfile

from build import _metadata, ZIP_DATE

ROOT = Path(__file__).resolve().parents[1]
MODULE_ROOT = 'src/res/scripts/client/gui/mods/tanksession_analytics/'
MODULES = ('__init__.py', 'analytics.py', 'core.py', 'economy.py', 'recorder.py',
           'storage.py', 'vehicles.py')
SOURCE_FILES = ('LICENSE', 'docs/NATIVE_CORE_RU.md', 'tools/native_report.py',
                'sample_data/battles.jsonl', 'native/benchmarks/baseline-linux.json') + tuple(MODULE_ROOT + name for name in MODULES)
PLATFORMS = {'windows-x64': ('Windows_x64', 'tanksession-native.exe'),
             'linux-x64': ('Linux_x64', 'tanksession-native')}
PLATFORM_ALIASES = {'Windows': 'windows-x64', 'Linux': 'linux-x64'}
MAX_BINARY_BYTES = 64 * 1024 * 1024
MAX_SOURCE_BYTES = 4 * 1024 * 1024


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _read_regular(path, limit):
    if not path.is_file() or path.is_symlink() or not 0 < path.stat().st_size <= limit:
        raise ValueError('Missing, linked, empty or oversized companion file: ' + path.name)
    with path.open('rb') as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Companion file exceeded the size limit')
    return data


def _verify_binary(path, data, platform_name):
    if platform_name == 'windows-x64':
        if len(data) < 64 or data[:2] != b'MZ':
            raise ValueError('Expected a Windows PE executable')
        offset = struct.unpack_from('<I', data, 0x3c)[0]
        if (offset > len(data) - 26 or data[offset:offset + 4] != b'PE\0\0'
                or struct.unpack_from('<H', data, offset + 4)[0] != 0x8664
                or struct.unpack_from('<H', data, offset + 24)[0] != 0x20b):
            raise ValueError('Expected a Windows x64 PE32+ executable')
    else:
        if (len(data) < 64 or data[:7] != b'\x7fELF\x02\x01\x01'
                or struct.unpack_from('<H', data, 18)[0] != 62):
            raise ValueError('Expected a Linux x64 ELF executable')
    try:
        result = subprocess.run([str(path.resolve()), '--version'], capture_output=True,
                                timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError('Companion binary protocol probe failed') from error
    if result.returncode != 0 or result.stdout.strip() != b'tanksession-native protocol 1':
        raise ValueError('Companion binary does not implement protocol 1')


def _launcher(platform_name):
    if platform_name == 'windows-x64':
        return 'native_report.cmd', (
            '@echo off\r\nsetlocal\r\n'
            'where py >nul 2>nul\r\n'
            'if errorlevel 1 (\r\n'
            '  python "%~dp0tools\\native_report.py" --binary "%~dp0bin\\tanksession-native.exe" %*\r\n'
            ') else (\r\n'
            '  py -3 "%~dp0tools\\native_report.py" --binary "%~dp0bin\\tanksession-native.exe" %*\r\n'
            ')\r\nexit /b %errorlevel%\r\n').encode('ascii')
    return 'native_report.sh', (
        '#!/bin/sh\nset -eu\n'
        'report_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        'exec python3 "$report_dir/tools/native_report.py" --binary '
        '"$report_dir/bin/tanksession-native" "$@"\n').encode('ascii')


def _start_text(version, platform_name):
    launcher = 'native_report.cmd' if platform_name == 'windows-x64' else './native_report.sh'
    return ('''TankSession Analytics %s — отдельный companion C++23

Требуется Python 3.9+ для чтения журнала. В Windows установите Python с py launcher
или командой python в PATH. C++ уже собран: CMake, компилятор и GoogleTest не нужны.
Ничего не копируйте в папку модов игры. Companion работает отдельно от клиента.

1. Распакуйте весь архив в отдельную папку.
2. Откройте терминал в этой папке. Пример на вымышленных данных:
   %s --data sample_data/battles.jsonl --account demo
3. Свой журнал: укажите полный путь к battles.jsonl и один подтверждённый ID
   аккаунта. Идентификатор не попадает в отчёт или C++ процесс.
   %s --data "PATH_TO_BATTLES.jsonl" --account ACCOUNT_ID --json --output report.json

Обычный вывод — читаемый текст, --json — полный контракт. --output сохраняет файл.
--vehicle принимает точный ключ/однозначную старую подпись; --from/--to — даты получения в UTC.
--engine python явно выбирает эталонный Python-расчёт. Ошибка native не скрывается.
Журнал, ожидания, настройки и цели не изменяются. Пропуск отличается от нуля.
Неоднозначные старые группы остаются отдельными и помеченными.

Для Linux права исполнения сохраняются в ZIP. Если распаковщик их убрал:
   chmod +x native_report.sh bin/tanksession-native

Содержимое и SHA-256 каждого файла: manifest.json. Полная спецификация:
docs/NATIVE_CORE_RU.md. Архив не содержит игрового мода и не доказывает нативную
совместимость Gameface или установленного клиента. Это независимый отчёт.
''' % (version, launcher, launcher)).encode('utf-8')


def build_bundle(binary, platform_name, output=None, root=None, source_commit=None):
    root = Path(root) if root is not None else ROOT
    binary = Path(binary)
    platform_name = PLATFORM_ALIASES.get(platform_name, platform_name)
    if platform_name not in PLATFORMS:
        raise ValueError('Unsupported companion platform')
    if source_commit is not None and re.fullmatch(r'[0-9a-fA-F]{40}', source_commit) is None:
        raise ValueError('Source commit must be a full SHA')
    mod_id, version = _metadata(_read_regular(root / 'src/meta.xml', MAX_SOURCE_BYTES))
    executable = _read_regular(binary, MAX_BINARY_BYTES)
    _verify_binary(binary, executable, platform_name)
    suffix, binary_name = PLATFORMS[platform_name]
    members = {}
    root_resolved = root.resolve()
    for relative in SOURCE_FILES:
        path = root / relative
        if not path.resolve().is_relative_to(root_resolved):
            raise ValueError('Companion source escapes the project root')
        members[relative] = _read_regular(path, MAX_SOURCE_BYTES)
    binary_member = 'bin/' + binary_name
    members[binary_member] = executable
    launcher_name, launcher = _launcher(platform_name)
    members[launcher_name] = launcher
    members['START_NATIVE_RU.txt'] = _start_text(version, platform_name)
    executable_members = {binary_member, launcher_name} if platform_name == 'linux-x64' else {binary_member}
    manifest = {'schema': 1, 'mod_id': mod_id, 'version': version, 'native_protocol': 1,
                'platform': platform_name, 'architecture': 'x86_64', 'python_minimum': '3.9',
                'source_commit': source_commit.lower() if source_commit else None,
                'binary_sha256': _sha(executable),
                'members': [{'path': name, 'size': len(data), 'sha256': _sha(data)}
                            for name, data in sorted(members.items())]}
    members['manifest.json'] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                          indent=2) + '\n').encode('utf-8')
    output = Path(output) if output is not None else root / 'dist'
    output.mkdir(parents=True, exist_ok=True)
    destination = output / ('TankSession_Analytics_%s_Native_%s.zip' % (version, suffix))
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=output, suffix='.zip.tmp', delete=False) as temporary:
            temporary_path = Path(temporary.name)
        with zipfile.ZipFile(temporary_path, 'w', compression=zipfile.ZIP_STORED) as archive:
            for name, data in sorted(members.items()):
                entry = zipfile.ZipInfo(name, date_time=ZIP_DATE)
                entry.create_system = 3
                entry.external_attr = (0o100755 if name in executable_members else 0o100644) << 16
                archive.writestr(entry, data)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    digest = _sha(destination.read_bytes())
    destination.with_suffix('.zip.sha256').write_text('%s  %s\n' % (digest, destination.name), encoding='ascii')
    return destination, dict(manifest, archive_sha256=digest)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--platform', required=True, choices=tuple(PLATFORMS) + tuple(PLATFORM_ALIASES))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--source-commit', default=os.environ.get('GITHUB_SHA'))
    args = parser.parse_args(argv)
    archive, info = build_bundle(args.binary, args.platform, args.output, source_commit=args.source_commit)
    print(archive)
    print('SHA-256:', info['archive_sha256'])


if __name__ == '__main__':
    main()
