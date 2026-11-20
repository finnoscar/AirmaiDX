"""Build and verify an Apple silicon preview DMG."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
from validate_portability import validate as validate_portability

ROOT = Path(__file__).resolve().parents[1]


def run(*arguments, capture=False):
    return subprocess.run([str(a) for a in arguments], check=True,
                          stdout=subprocess.PIPE if capture else None)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate_app(app):
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != 'com.airmai.AirmaiDX':
        raise ValueError('Select a complete AirmaiDX.app.')
    runtime = app / 'Contents/Resources/Runtime'
    manifest = json.loads((runtime / 'manifest.json').read_text())
    if not (runtime / 'runtime-downloads.json').is_file():
        raise ValueError('The app must use the separate upstream runtime setup.')
    if any((runtime / name).exists() for name in ('wine', 'graphics', 'dependencies', 'vcredist2012_x64.exe')):
        raise ValueError('The public DMG must not embed upstream runtime downloads.')
    for key in ['game_included', 'prefix_included', 'gptk_included']:
        if manifest.get(key) is not False:
            raise ValueError('The manifest must exclude game data, prefixes, and GPTK.')
    for path in app.rglob('*'):
        if path.is_symlink() and not path.resolve().is_relative_to(app.resolve()):
            raise ValueError('Link leaves the app bundle: ' + str(path.relative_to(app)))
    for name, expected in manifest['critical_sha256'].items():
        path = runtime / name
        if not path.resolve().is_relative_to(runtime.resolve()) or sha(path) != expected:
            raise ValueError('Runtime component failed verification: ' + name)
    for name in ['Service/AirmaiDXService', 'Assets.car', 'Runtime/NOTICES.md']:
        if not (app / 'Contents/Resources' / name).is_file():
            raise ValueError('App resource missing: ' + name)
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', app)
    validate_portability(app)
    return info


def main():
    parser = argparse.ArgumentParser(description='Package AirmaiDX for Apple silicon.')
    parser.add_argument('--skip-build', action='store_true', help='Package the existing app')
    parser.add_argument('--app', type=Path, help='Package a specific app without rebuilding')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    if not args.skip_build and args.app is None:
        parser.error('Build the app first, then use --skip-build or --app. See docs/BUILDING.md.')
    app = (args.app or ROOT / 'build/AirmaiDX.app').resolve()
    info = validate_app(app)
    version = str(info['CFBundleShortVersionString'])
    build = str(info['CFBundleVersion'])
    if not all(re.fullmatch(r'[0-9A-Za-z._-]+', value) for value in [version, build]):
        raise ValueError('The version or build number cannot be used in the file name.')
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    name = f'AirmaiDX-{version}-{build}-arm64'
    image = output / (name + '.dmg')
    with tempfile.TemporaryDirectory(prefix='.airmaidx-dmg-', dir=output) as temporary:
        work = Path(temporary)
        stage = work / 'stage'
        stage.mkdir()
        run('/usr/bin/ditto', app, stage / 'AirmaiDX.app')
        os.symlink('/Applications', stage / 'Applications')
        (stage / 'Read Me.txt').write_text(
            'AirmaiDX for macOS\n\n'
            '1. Drag AirmaiDX.app into Applications.\n'
            '2. Open AirmaiDX and select your game folder.\n'
            '3. Follow the setup prompts to download the Windows runtime from GitHub and Microsoft.\n\n'
            'Requires an Apple silicon Mac, macOS 15 or later, and Rosetta 2.\n'
            'This preview is ad hoc signed and is not notarized.\n'
            'Apple instructions for opening a verified app: https://support.apple.com/102445\n\n'
            'No game files, accounts, or machine credentials are included.\n'
            'AirmaiDX is an independent project and is not affiliated with SEGA.\n', encoding='utf-8')
        temporary_image = work / (name + '.dmg')
        image_cli = subprocess.run(['/usr/sbin/diskutil', 'image', 'create', 'from', '--help'],
                                   capture_output=True, text=True)
        if 'USAGE: diskutil image create from' in image_cli.stdout:
            run('/usr/sbin/diskutil', 'image', 'create', 'from', '--format', 'UDZO',
                '--volumeName', 'AirmaiDX', stage, temporary_image)
        else:
            run('/usr/bin/hdiutil', 'create', '-srcfolder', stage, '-volname', 'AirmaiDX',
                '-fs', 'HFS+', '-format', 'UDZO', '-imagekey', 'zlib-level=6', temporary_image)
        run('/usr/bin/hdiutil', 'verify', temporary_image)
        mount = work / 'mounted'
        mount.mkdir()
        attached = False
        try:
            run('/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', mount, temporary_image)
            attached = True
            validate_app(mount / 'AirmaiDX.app')
            if os.readlink(mount / 'Applications') != '/Applications':
                raise ValueError('The Applications shortcut is invalid.')
        finally:
            if attached:
                run('/usr/bin/hdiutil', 'detach', mount)
        # Publish only after the compressed image and its mounted app verify.
        temporary_image.replace(image)
    checksum = sha(image)
    (output / (image.name + '.sha256')).write_text(checksum + '  ' + image.name + '\n')
    (output / (name + '.json')).write_text(json.dumps({
        'name': 'AirmaiDX', 'version': version, 'build': build, 'architecture': 'arm64',
        'image': image.name, 'bytes': image.stat().st_size, 'sha256': checksum,
        'signing': 'ad-hoc', 'notarized': False,
        'game_included': False, 'prefix_included': False, 'gptk_included': False
    }, ensure_ascii=False, indent=2) + '\n')
    print('Verified disk image: ' + str(image))
    print('Size: ' + f'{image.stat().st_size / 1024 / 1024:.1f} MiB')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('Packaging failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
