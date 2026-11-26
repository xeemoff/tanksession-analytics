#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Package an inspected game build and an offline Windows installer.

This operation never downloads code, changes a game installation, or treats
automated tests as evidence of native game compatibility. Stable publication
requires a recorded validation of these exact package bytes.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import zipfile

from build import project_metadata, verify_mtmod, ZIP_DATE

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*))?$')
CLIENT_VERSION = re.compile(r'^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$')
SHA256 = re.compile(r'^[0-9a-fA-F]{64}$')
CHECKS = frozenset((
    'normal_win', 'normal_loss', 'zero_damage', 'delayed_result',
    'deduplication', 'restart_preserves_history', 'account_isolation',
    'replay_exclusion', 'gameface_lifecycle', 'metrics_against_results',
    'settings_goals_export', 'installation_uninstallation', 'performance',
))


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def release_gate(version, digest, validation, tag=None):
    """Return the compatibility claim; reject an unsupported stable release."""
    match = VERSION.fullmatch(version)
    if match is None:
        raise ValueError('Release version must be a three-part semantic version')
    if tag is not None and tag != 'v' + version:
        raise ValueError('Tag must match src/meta.xml exactly')
    if not isinstance(validation, dict) or validation.get('schema') != 1:
        raise ValueError('Unsupported release validation manifest')
    target = validation.get('target_client_version')
    if not isinstance(target, str) or not CLIENT_VERSION.fullmatch(target):
        raise ValueError('A specific target client version is required')
    if match.group(4):
        return {'channel': 'prerelease', 'client_versions': [target],
                'native_validation': 'pending'}
    checks = validation.get('checks')
    if (validation.get('status') != 'verified'
            or validation.get('release_version') != version
            or validation.get('tested_client_version') != target
            or not isinstance(checks, dict)
            or set(checks) != CHECKS
            or any(checks.get(name) is not True for name in CHECKS)):
        raise ValueError('Stable release blocked: native validation is incomplete')
    recorded = validation.get('tested_package_sha256')
    if (not isinstance(recorded, str) or not SHA256.fullmatch(recorded)
            or recorded.lower() != digest.lower()):
        raise ValueError('Stable release blocked: tested package SHA-256 does not match')
    try:
        date = datetime.date.fromisoformat(validation.get('tested_at', ''))
    except (TypeError, ValueError):
        raise ValueError('Stable release requires a real YYYY-MM-DD validation date')
    if date > datetime.date.today():
        raise ValueError('Native validation cannot be dated in the future')
    evidence = validation.get('evidence')
    if (not isinstance(evidence, str) or not evidence
            or '\\' in evidence or ':' in evidence
            or any(part in ('', '.', '..') for part in evidence.split('/'))):
        raise ValueError('A repository-local validation report is required')
    report = ROOT / 'docs' / evidence
    if not report.is_file() or report.is_symlink():
        raise ValueError('Native validation report is missing')
    return {'channel': 'stable', 'client_versions': [target],
            'native_validation': 'verified'}


def _read_project_file(relative):
    path = ROOT / relative
    if not path.is_file() or path.is_symlink():
        raise ValueError('Missing regular release file: ' + relative)
    return path.read_bytes()


def build_release(package=None, output=None, tag=None, validation_path=None):
    mod_id, version = project_metadata()
    package = Path(package) if package else ROOT / 'dist' / ('%s_%s.mtmod' % (mod_id, version))
    expected_name = '%s_%s.mtmod' % (mod_id, version)
    if package.name != expected_name or package.is_symlink():
        raise ValueError('Package filename must match project metadata')
    verification = verify_mtmod(str(package))
    data = package.read_bytes()
    digest = _digest(data)
    checksum = package.with_suffix('.mtmod.sha256')
    if (not checksum.is_file() or checksum.is_symlink()
            or checksum.read_text(encoding='ascii').strip() != '%s  %s' % (digest, package.name)):
        raise ValueError('Package SHA-256 sidecar is missing or differs from its bytes')
    validation_path = Path(validation_path) if validation_path else ROOT / 'docs' / 'release-validation.json'
    if validation_path.is_symlink():
        raise ValueError('Validation manifest must be a regular file')
    validation = json.loads(validation_path.read_text(encoding='utf-8'))
    compatibility = release_gate(version, digest, validation, tag=tag)
    with zipfile.ZipFile(package) as archive:
        members = [{'path': name, 'size': len(archive.read(name)),
                    'sha256': _digest(archive.read(name))} for name in sorted(archive.namelist())]
    manifest = {
        'schema': 1, 'id': mod_id, 'version': version,
        'package': package.name, 'package_size': len(data), 'sha256': digest,
        'members': members,
        'channel': compatibility['channel'],
        'client_versions': compatibility['client_versions'],
        'native_validation': compatibility['native_validation'],
        'source_url': 'https://github.com/xeemoff/tanksession-analytics',
    }
    notes_path = 'docs/releases/v%s.md' % version
    files = {
        package.name: data,
        package.name + '.sha256': ('%s  %s\n' % (digest, package.name)).encode('ascii'),
        'manifest.json': (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8'),
        'install.cmd': _read_project_file('installer/install.cmd'),
        'Install-TankSession.ps1': _read_project_file('installer/Install-TankSession.ps1'),
        'INSTALL_RU.md': _read_project_file('docs/INSTALL_RU.md'),
        'RELEASE_NOTES_RU.md': _read_project_file(notes_path),
        'LICENSE': _read_project_file('LICENSE'),
    }
    # No recursive source-directory collection: real journals/configs, caches,
    # unrelated packages and native loader binaries cannot enter this bundle.
    destination = Path(output) if output else ROOT / 'dist' / ('TankSession_Analytics_%s_Windows.zip' % version)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.release-', dir=str(destination.parent))
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, contents in sorted(files.items()):
                info = zipfile.ZipInfo(name, ZIP_DATE)
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, contents)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    archive_digest = _digest(destination.read_bytes())
    destination.with_suffix('.zip.sha256').write_text(
        '%s  %s\n' % (archive_digest, destination.name), encoding='ascii')
    verification.update(compatibility)
    verification.update({'package_sha256': digest, 'archive_sha256': archive_digest})
    return destination, verification


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', help='Built .mtmod with its SHA-256 sidecar')
    parser.add_argument('--output', help='Destination Windows ZIP')
    parser.add_argument('--tag', help='Optional tag that must equal v + src/meta.xml version')
    parser.add_argument('--validation', help='Release-validation manifest; default docs/release-validation.json')
    args = parser.parse_args()
    try:
        destination, info = build_release(args.package, args.output, args.tag, args.validation)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.exit(1, 'Release packaging failed: %s\n' % error)
    print('Windows bundle:', destination)
    print('SHA-256:', info['archive_sha256'])
    print('Channel:', info['channel'], '| native validation:', info['native_validation'])


if __name__ == '__main__':
    main()
