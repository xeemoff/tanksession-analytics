#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Package a browser preview with prebuilt UI; no Node.js is needed to run it."""
import hashlib
from pathlib import Path
import zipfile

from build import project_metadata, ZIP_DATE

ROOT = Path(__file__).resolve().parents[1]


def build_preview():
    _, version = project_metadata()
    paths = [
        'LICENSE', 'demo_hangar.cmd',
        'tools/preview_ui.py', 'tools/dashboard.py',
        'sample_data/battles.jsonl', 'sample_data/goals.json',
        'ui/dist/index.html', 'ui/dist/app.js', 'ui/dist/app.css',
        'ui/dist/THIRD_PARTY_LICENSES.txt',
    ]
    package = 'src/res/scripts/client/gui/mods/tanksession_analytics/'
    paths.extend(package + name + '.py' for name in (
        '__init__', 'analytics', 'coach', 'core', 'economy', 'gameface', 'goals',
        'insights', 'presentation', 'recorder', 'storage', 'vehicles', 'workspace'))
    files = {path: (ROOT / path).read_bytes() for path in paths}
    files['PREVIEW_RU.txt'] = (
        'TankSession Analytics %s — просмотр интерфейса\n\n'
        'Нужны Python 3.9+ и браузер. Node.js не требуется.\n'
        'Распакуйте весь архив, затем запустите demo_hangar.cmd на Windows\n'
        'или python tools/preview_ui.py --demo в терминале.\n'
        'Если порт занят: python tools/preview_ui.py --demo --port 0\n'
        'Остановка: Ctrl+C в консоли сервера.\n\n'
        'Демо содержит вымышленные бои. Это браузерный просмотр,\n'
        'который не запускает Gameface и не устанавливает мод в игру.\n'
        'Проверка загрузки игрового окна выполняется отдельно.\n\n'
        'Своя история: python tools/preview_ui.py --data "путь к battles.jsonl" '
        '--account "ID своего аккаунта"\n'
        'Для сохранения целей, настроек и CSV в своей папке добавьте --allow-write.\n'
        'Демонстрационные настройки временные и не меняют sample_data.\n'
        'Данные обрабатываются локально; сервер слушает только 127.0.0.1.\n'
        'Исходный код: https://github.com/xeemoff/tanksession-analytics\n'
    ) % version
    files['PREVIEW_RU.txt'] = files['PREVIEW_RU.txt'].encode('utf-8')
    destination = ROOT / 'dist' / ('TankSession_Analytics_%s_Preview.zip' % version)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix('.zip.sha256').write_text(
        '%s  %s\n' % (digest, destination.name), encoding='ascii')
    print('Browser preview:', destination)
    print('SHA-256:', digest)
    return destination


if __name__ == '__main__':
    build_preview()
