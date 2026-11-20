"""Frozen worker options shared by the Xcode and full-app builders."""
WORKER_OPTIONS = [
    '--collect-data', 'UnityPy',
    # Title artwork only. Do not include an unrelated FMOD audio extraction path.
    '--exclude-module', 'UnityPy.export',
    '--exclude-module', 'fmod_toolkit',
    '--exclude-module', 'pyfmodex',
    '--exclude-module', 'etcpak',
    '--exclude-module', 'astc_encoder',
    '--exclude-module', 'tkinter',
    '--exclude-module', 'PIL._imagingtk',
]


# Inspect the interpreter being frozen, not the interpreter running Xcode's
# resource script. They may use different Python distributions and TLS policy.
from pathlib import Path
import json
import subprocess


def worker_options(python):
    probe = subprocess.run([str(python), '-I', '-c',
        'import json,ssl; from pathlib import Path; '
        'p=Path(ssl.__file__).with_name("codex-rejected-cas.pem"); '
        'print(json.dumps(str(p) if p.is_file() else None))'],
        check=True, capture_output=True, text=True, timeout=15)
    policy = json.loads(probe.stdout)
    options = list(WORKER_OPTIONS)
    if policy is not None:
        if not isinstance(policy, str) or not Path(policy).is_file():
            raise RuntimeError('后台 Python 的 TLS 策略文件不可用。')
        options += ['--add-data', policy + ':.']
    return options


def worker_tls_ready(worker):
    """Exercise SSLContext in the frozen process without network or user data."""
    try:
        result = subprocess.run([str(Path(worker) / 'AirmaiDXService'), '--tls-self-test'],
                                capture_output=True, text=True, timeout=20)
        return result.returncode == 0 and any(
            json.loads(line) == {'event': 'result', 'data': {'tlsReady': True}}
            for line in result.stdout.splitlines() if line.startswith('{'))
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def licenses(destination):
    from pathlib import Path
    from importlib.metadata import distribution
    import json
    import shutil
    import sysconfig
    import sys
    root = Path(destination) / 'Licenses'
    index = []
    for name in ['UnityPy', 'Pillow', 'texture2ddecoder', 'fsspec', 'attrs', 'lz4', 'brotli', 'dnfile',
                 'pefile', 'PyInstaller', 'setuptools', 'packaging']:
        package = distribution(name)
        for entry in package.files or []:
            if entry.name.lower().startswith(('license', 'copying', 'notice')):
                source = Path(package.locate_file(entry))
                if source.is_file():
                    target = root / name / Path(*entry.parts[1:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        index.append(dict(name=name, version=package.version))
    root.mkdir(parents=True, exist_ok=True)
    python_license=Path(sysconfig.get_path('stdlib'))/'LICENSE.txt'
    if python_license.is_file():shutil.copy2(python_license,root/'PYTHON_LICENSE.txt')
    if sys.version.split()[0] == '3.12.16':
        notices = Path(__file__).resolve().parents[1] / 'Vendor/PythonNotices'
        shutil.copytree(notices, root / 'Python-build-standalone', dirs_exist_ok=True)
    index.append(dict(name='Python',version=sys.version.split()[0]))
    (root / 'components.json').write_text(json.dumps(index, indent=2) + '\n')


if __name__ == '__main__':
    import sys
    licenses(sys.argv[1])
