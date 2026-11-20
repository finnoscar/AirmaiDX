"""Shared resource assembly for the standalone and Xcode app builds."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

def worker_python(root):
    portable=root/'Tools/.venv-portable/bin/python'
    return portable if portable.is_file() else root/'Tools/.venv/bin/python'

def native_fingerprint(root):
    digest=hashlib.sha256()
    for path in sorted((root/'Native').iterdir()):
        if path.suffix in ['.c','.cs','.swift']:
            digest.update(path.name.encode());digest.update(path.read_bytes())
    digest.update((root/'Tools/build_app.py').read_bytes())
    return digest.hexdigest()


def service_fingerprint(root):
    digest = hashlib.sha256()
    for path in sorted((root / 'Service').glob('*.py')):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    digest.update((root / 'Tools/worker_bundle.py').read_bytes())
    return digest.hexdigest()


def check_runtime_resources(source, expected_native):
    """Verify an existing local runtime before it enters an Xcode product."""
    runtime = source / 'Runtime'
    manifest = json.loads((runtime / 'manifest.json').read_text())
    if not isinstance(manifest, dict):
        raise ValueError('运行组件清单格式无效。')
    if manifest.get('native_source_sha256') != expected_native:
        raise ValueError('原生辅助组件与当前源码不一致，需先运行 Tools/build_app.py 更新组件。')
    if any(manifest.get(key) is not False for key in ['game_included', 'prefix_included', 'gptk_included']):
        raise ValueError('运行组件来源未明确排除游戏、用户 Prefix 或 GPTK。')
    critical = manifest.get('critical_sha256')
    if not isinstance(critical, dict) or not critical:
        raise ValueError('运行组件缺少完整性校验清单。')
    for name, expected in critical.items():
        if not isinstance(name, str) or not isinstance(expected, str) or len(expected) != 64:
            raise ValueError('运行组件校验清单格式无效。')
        path = runtime / name
        if not path.resolve().is_relative_to(runtime.resolve()) or not path.is_file():
            raise ValueError('运行组件文件缺失或路径无效：' + name)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError('运行组件文件校验失败：' + name)
    return manifest


def runtime_resource_source(root, destination, configured=None, installed=None):
    """Use the assembled app or a verified installed copy, never self-copy.

    A deliberate custom Build Setting stays authoritative. The generated
    default is a preference, so moving that app does not break the project.
    """
    default = root / 'build/AirmaiDX.app/Contents/Resources'
    custom = Path(configured).expanduser() if configured else None
    explicit = custom is not None and custom.resolve() != default.resolve()
    if installed is None:
        installed = [Path('/Applications/AirmaiDX.app/Contents/Resources'),
                     Path.home() / 'Applications/AirmaiDX.app/Contents/Resources']
    candidates = [custom] if explicit else [default, *installed]
    failures = []
    expected_native = native_fingerprint(root)
    for source in candidates:
        if source.resolve() == destination.resolve():
            failures.append(str(source) + '：来源与 Xcode 输出目录相同。')
            continue
        try:
            manifest = check_runtime_resources(source, expected_native)
        except (OSError, ValueError, TypeError) as error:
            failures.append(str(source) + '：' + str(error))
            continue
        return source, manifest
    message = ('指定的运行组件来源不可用。' if explicit else '没有找到与当前源码匹配的本机运行组件。')
    raise RuntimeError(message + '请先运行 python3 Tools/build_app.py，或设置 AIRMAIDX_RUNTIME_RESOURCES。\n' + '\n'.join(failures))


def preview_assets(root, destination, work):
    source = root / 'Vendor/EditorPreview/Resources'
    catalog = work / 'EditorPreviewAssets.xcassets'
    catalog.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / 'Assets.xcassets/Contents.json', catalog / 'Contents.json')
    for name in ['SimaiSensor.imageset', 'SimaiAnswer.dataset']:
        shutil.copytree(source / 'Assets.xcassets' / name, catalog / name, dirs_exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(['xcrun', 'actool', '--compile', str(destination), '--platform', 'macosx',
                    '--minimum-deployment-target', '15.0', '--app-icon', 'AppIcon',
                    '--output-partial-info-plist', str(work / 'app-icon-info.plist'),
                    str(catalog), str(root / 'Resources/SidebarArtwork.xcassets'),
                    str(root / 'Resources/AppIcon.icon')], check=True,
                   stdout=subprocess.DEVNULL)
    licenses = destination / 'Runtime/Licenses'
    licenses.mkdir(parents=True, exist_ok=True)
    for name in ['AIRMAI_LICENSE.txt', 'SIMAI_FLUTTER_LICENSE.txt']:
        shutil.copy2(source / name, licenses / name)
    for path in (root / 'Sources/AirmaiCore/Resources').glob('AquaMai-Documentation-*.txt'):
        shutil.copy2(path, licenses / path.name)
    # SwiftPM's Bundle.module and SwiftUI's default main bundle both need their
    # resources in a standalone app. Native Xcode targets copy their resources
    # through a normal Resources build phase instead.
    if destination.resolve() == (root / 'build/AirmaiDX.app/Contents/Resources').resolve():
        resources = root / 'Sources/AirmaiCore/Resources'
        for path in resources.iterdir():
            if path.is_dir(): shutil.copytree(path, destination / path.name, dirs_exist_ok=True)
            else: shutil.copy2(path, destination / path.name)
        module_bundle = root / '.build/release/AirmaiDX_AirmaiCore.bundle'
        if not module_bundle.is_dir():
            raise RuntimeError('缺少 SwiftPM 本地化资源包，请重新构建 Swift 应用。')
        shutil.copytree(module_bundle, destination / module_bundle.name, dirs_exist_ok=True)
