"""Assemble the Windows runtime locally from checksum-pinned upstream assets."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile

from launch_guidance import LaunchRequirement
from storage import atomic_json, digest

LOCK = 'runtime-downloads.json'
MISSING = ('AirmaiDX needs Wine, DXMT, and the Visual C++ runtime to run this package. '
           'Setup downloads about 355 MB from GitHub and Microsoft.')


def _target(bundled, root):
    # Keep versions side by side while older game sessions exit. The hash also
    # covers the checksums of AirmaiDX's own helpers in the installed app.
    identity = hashlib.sha256((bundled / LOCK).read_bytes() + (bundled / 'manifest.json').read_bytes()).hexdigest()
    return root / 'Runtime' / identity[:24]


def resolve(bundled, root):
    if not (bundled / LOCK).is_file():
        return bundled
    target = _target(bundled, root)
    return target if (target / 'manifest.json').is_file() else bundled


def require_installed(runtime):
    if (runtime / LOCK).is_file():
        raise LaunchRequirement('runtimeDownload', MISSING)


def _archive(receipt, target):
    # Allow only HTTPS, even across redirects. The locked size and digest are
    # checked before any archive is opened or any downloaded program is run.
    subprocess.run(['/usr/bin/curl', '--disable', '--proto', '=https', '--proto-redir', '=https',
                    '--location', '--max-redirs', '8', '--fail', '--silent', '--show-error',
                    '--retry', '2', '--max-time', '420', '--max-filesize', str(receipt['bytes']),
                    '--output', str(target), receipt['url']], check=True, timeout=480)
    if target.stat().st_size != receipt['bytes'] or digest(target) != receipt['sha256']:
        raise ValueError(f'Checksum verification failed for {target.name}.')


def _extract(archive, output):
    output.mkdir()
    subprocess.run(['/usr/bin/tar', '-xf', str(archive), '-C', str(output)], check=True, timeout=120)


def _contained_links(directory):
    for path in directory.rglob('*'):
        if path.is_symlink() and not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError(f'An upstream link leaves the runtime directory: {path.name}')


def install(bundled, store, emit, fetch=_archive):
    if not (bundled / LOCK).is_file():
        return True
    target = _target(bundled, store.root)
    if (target / 'manifest.json').is_file():
        return True
    target.parent.mkdir(mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.setup-', dir=target.parent) as temp:
        work = Path(temp)
        assembled = work / 'Runtime'
        shutil.copytree(bundled, assembled, ignore=shutil.ignore_patterns(LOCK, 'manifest.json'))
        lock = json.loads((bundled / LOCK).read_text())
        if lock['schema'] != 1:
            raise ValueError('This app does not support the runtime download manifest.')
        items = [('engine.tar.xz', 'Downloading Wine…'), ('template-dxmt.tar.xz', 'Downloading DXMT…'),
                 ('template-libs.tar.xz', 'Downloading runtime libraries…'),
                 ('vcredist2012_x64.exe', 'Downloading the Visual C++ runtime…')]
        for i, (name, message) in enumerate(items):
            emit('progress', dict(message=message, fraction=i / len(items)))
            fetch(lock['archives'][name], work / name)
        emit('progress', dict(message='Installing runtime components…', fraction=0.85))
        for name in ('engine', 'template-dxmt', 'template-libs'):
            _extract(work / (name + '.tar.xz'), work / name)
        engine = work / 'engine/wswine.bundle'
        dxmt = work / 'template-dxmt/Template-1.0.11.app/Contents/Frameworks/renderer/dxmt'
        host = work / 'template-libs/Template-1.0.27.app/Contents/Frameworks'
        wine = assembled / 'wine'
        _contained_links(engine)
        shutil.copytree(engine, wine, symlinks=True)
        dep = assembled / 'dependencies'
        dep.mkdir()
        # These two directories and the top-level dylibs are the only host
        # inputs. In particular, no alternate renderer or Windows prefix is copied.
        for name in ('GStreamer.framework', 'SikarugirSdk.framework'):
            _contained_links(host / name)
            shutil.copytree(host / name, dep / name, symlinks=True)
        for path in sorted(host.glob('*.dylib')):
            if path.name in ('libpng.dylib', 'libvulkan_kosmickrisp.dylib'):
                continue
            if not path.resolve().is_relative_to(host.resolve()):
                raise ValueError('A host dependency points outside its upstream archive.')
            shutil.copy2(path, dep / path.name)
        graphics = assembled / 'graphics'
        graphics.mkdir()
        for name in ('d3d10core.dll', 'd3d11.dll', 'dxgi.dll', 'winemetal.dll'):
            original = dxmt / 'wine/x86_64-windows' / name
            shutil.copy2(original, wine / 'lib/wine/x86_64-windows' / name)
            if name != 'd3d10core.dll':
                shutil.copy2(original, graphics / name)
        shutil.copy2(dxmt / 'wine/x86_64-unix/winemetal.so', wine / 'lib/wine/x86_64-unix/winemetal.so')
        (work / 'vcredist2012_x64.exe').rename(assembled / 'vcredist2012_x64.exe')
        shutil.copy2(dxmt / 'LICENSE', assembled / 'Licenses/DXMT-LICENSE.txt')
        _contained_links(assembled)
        manifest = json.loads((bundled / 'manifest.json').read_text())
        for name in ('wine/bin/wine', 'wine/bin/wineserver', 'wine/lib/wine/x86_64-unix/winemetal.so',
                     'vcredist2012_x64.exe', 'graphics/d3d11.dll', 'graphics/dxgi.dll', 'graphics/winemetal.dll'):
            manifest['critical_sha256'][name] = digest(assembled / name)
        atomic_json(assembled / 'manifest.json', manifest)
        # Nothing points to the new runtime until all files and its manifest are ready.
        os.rename(assembled, target)
    emit('progress', dict(message='Runtime installed.', fraction=1))
    return True
