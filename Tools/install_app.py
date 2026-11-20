"""Install the local build, retaining one app after successful verification."""
from pathlib import Path
import json
import plistlib
import shutil
import subprocess

from app_resources import check_runtime_resources, native_fingerprint, service_fingerprint

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'build/AirmaiDX.app'
DESTINATION = Path('/Applications/AirmaiDX.app')
IDENTIFIER = 'com.airmai.AirmaiDX'


def verify(app):
    if app.is_symlink() or not app.is_dir():
        raise RuntimeError('应用路径无效：' + str(app))
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != IDENTIFIER:
        raise RuntimeError('应用标识不匹配：' + str(app))
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    resources = app / 'Contents/Resources'
    check_runtime_resources(resources, native_fingerprint(ROOT))
    if (resources / 'ServiceSource.sha256').read_text().strip() != service_fingerprint(ROOT):
        raise RuntimeError('后台源码校验失败：' + str(app))


def replace_app(source, destination, verifier=verify):
    """Keep the previous bundle until the new installed bundle passes checks."""
    if source.resolve() == destination.resolve():
        raise RuntimeError('安装来源与目标相同。')
    staging = destination.with_name('.AirmaiDX.installing.app')
    previous = destination.with_name('.AirmaiDX.previous.app')
    if any(p.exists() or p.is_symlink() for p in [staging, previous]):
        raise RuntimeError('发现未完成安装的暂存应用，请先检查后再安装。')
    verifier(source)
    if destination.exists():
        info = plistlib.loads((destination / 'Contents/Info.plist').read_bytes())
        if destination.is_symlink() or info.get('CFBundleIdentifier') != IDENTIFIER:
            raise RuntimeError('正式应用路径被其他内容占用。')
    moved = source.stat().st_dev == destination.parent.stat().st_dev
    replaced = installed = False
    try:
        if moved:
            source.rename(staging)
        else:
            shutil.copytree(source, staging, symlinks=True)
        verifier(staging)
        if destination.exists():
            destination.rename(previous)
            replaced = True
        staging.rename(destination)
        installed = True
        verifier(destination)
    except BaseException:
        if installed:
            destination.rename(staging)
        if replaced:
            previous.rename(destination)
        if staging.exists():
            if moved:
                staging.rename(source)
            else:
                shutil.rmtree(staging)
        raise
    if previous.exists():
        shutil.rmtree(previous)
    if not moved:
        shutil.rmtree(source)


def main():
    if subprocess.run(['pgrep', '-x', 'AirmaiDX'], capture_output=True).returncode == 0:
        raise RuntimeError('请先退出 AirmaiDX，再安装新版。')
    replace_app(SOURCE, DESTINATION)
    receipt = ROOT / 'build/installed-app-receipt.json'
    receipt.write_text(json.dumps({'app': str(DESTINATION), 'stagingRemoved': not SOURCE.exists(),
                                   'oldBundleRemoved': True}, ensure_ascii=False, indent=2) + '\n')
    print('已更新 /Applications/AirmaiDX.app，并清理旧副本与安装暂存。')


if __name__ == '__main__':
    main()
