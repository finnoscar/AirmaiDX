"""Embed the local development runtime and rebuild the worker when its source changes.

Never reads a game, Prefix, credentials or Downloads. Xcode calls this script
automatically. Runtime binaries come from the already assembled local app.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys

from app_resources import (preview_assets, service_fingerprint, native_fingerprint,
                           worker_python, runtime_resource_source, check_runtime_resources)
from worker_bundle import worker_options, worker_tls_ready

ROOT = Path(__file__).resolve().parents[1]


def sync(source, destination):
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(['/usr/bin/rsync', '-a', '--delete', str(source) + '/', str(destination) + '/'], check=True)


def main():
    if os.environ.get('ACTION') == 'indexbuild':
        return
    destination = Path(os.environ['TARGET_BUILD_DIR']) / os.environ['UNLOCALIZED_RESOURCES_FOLDER_PATH']
    work = Path(os.environ['DERIVED_FILE_DIR']) / 'AirmaiDXResources'
    source, manifest = runtime_resource_source(ROOT, destination, os.environ.get('AIRMAIDX_RUNTIME_RESOURCES'))
    print('Using verified local runtime: ' + str(source), flush=True)

    work.mkdir(parents=True, exist_ok=True)
    fingerprint = service_fingerprint(ROOT)
    receipt = source / 'ServiceSource.sha256'
    worker = source / 'Service'
    if not receipt.is_file() or receipt.read_text().strip() != fingerprint or not worker_tls_ready(worker):
        cache = work / 'Worker'
        stamp = cache / 'source.sha256'
        worker = cache / 'dist/AirmaiDXService'
        if not stamp.is_file() or stamp.read_text().strip() != fingerprint or not worker_tls_ready(worker):
            python = worker_python(ROOT)
            if not python.is_file():
                raise RuntimeError('后台服务源码已改变，需要开发用 Tools/.venv 与 PyInstaller。可先完成一次完整打包来更新服务。')
            print('Rebuilding AirmaiDX background service…', flush=True)
            cache.mkdir(parents=True, exist_ok=True)
            subprocess.run([str(python), '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', *worker_options(python),
                            '--name', 'AirmaiDXService', '--distpath', str(cache / 'dist'),
                            '--workpath', str(cache / 'work'), '--specpath', str(cache),
                            '--paths', str(ROOT / 'Service'), str(ROOT / 'Service/service.py')], check=True, cwd=ROOT)
            subprocess.run([str(python), str(ROOT / 'Tools/worker_bundle.py'), str(worker)], check=True)
            if not worker_tls_ready(worker):
                raise RuntimeError('打包后的后台 TLS 初始化失败，请检查运行依赖。')
            if fingerprint != service_fingerprint(ROOT):
                raise RuntimeError('构建期间后台源码发生变化，请重新构建。')
            stamp.write_text(fingerprint + '\n')

    print('Embedding runtime and background service…', flush=True)
    sync(source / 'Runtime', destination / 'Runtime')
    sync(worker, destination / 'Service')
    check_runtime_resources(destination, manifest['native_source_sha256'])
    if manifest['native_source_sha256'] != native_fingerprint(ROOT) or fingerprint != service_fingerprint(ROOT):
        raise RuntimeError('构建期间源码发生变化，请重新构建，避免混合不同版本的组件。')
    (destination / 'ServiceSource.sha256').write_text(fingerprint + '\n')
    shutil.copy2(ROOT / 'docs/THIRD_PARTY_NOTICES.md', destination / 'Runtime/NOTICES.md')
    preview_assets(ROOT, destination, work)
    print('AirmaiDX resources ready.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('error: ' + str(error), file=sys.stderr)
        sys.exit(1)
