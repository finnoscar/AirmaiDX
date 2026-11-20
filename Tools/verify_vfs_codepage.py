"""Opt-in Wine regression: self-authored INI/PE only, no game or network.

Run after build_app.py. The fixture mirrors production's Prefix -> HDD symlink.
An optional preinitialized, game-free Prefix avoids repeating wineboot setup.
"""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Service'))
from runtime import environment, sandbox_path, stop_wine
from storage import windows_ini_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed-prefix', type=Path)
    args = parser.parse_args()
    runtime = ROOT / 'build/AirmaiDX.app/Contents/Resources/Runtime'
    work = ROOT / 'build/VFS 中文回归'
    work.mkdir(exist_ok=True)
    prefix = work / 'Prefix'
    if not prefix.exists():
        if args.seed_prefix:
            shutil.copytree(args.seed_prefix, prefix, symlinks=True)
        else:
            prefix.mkdir()
    env = environment(runtime, prefix)
    for key in list(env):
        if key == 'LANG' or key.startswith('LC_'):
            env.pop(key)
    socket_root = Path('/private/tmp') / ('.wine-' + str(os.getuid()))
    socket_root.mkdir(mode=0o700, exist_ok=True)
    info = prefix.stat()
    socket_dir = socket_root / ('server-' + format(info.st_dev, 'x') + '-' + format(info.st_ino, 'x'))
    rules = ['(version 1)', '(allow default)', '(deny network*)',
             '(allow network-outbound (remote unix-socket))',
             '(allow network-inbound (local unix-socket))',
             '(allow network-bind (local unix-socket))', '(deny file-write*)',
             '(allow file-write* (literal "/dev/null"))',
             '(allow file-write* (subpath ' + sandbox_path(work) + '))',
             '(allow file-write* (literal ' + sandbox_path(socket_root) + '))',
             '(allow file-write* (subpath ' + sandbox_path(socket_dir) + '))']
    policy = work / 'probe.sb'
    policy.write_text('\n'.join(rules) + '\n')

    def run(arguments, locale, cwd, timeout=40):
        current = dict(env, LANG=locale)
        command = ['/usr/bin/sandbox-exec', '-f', str(policy), '/usr/bin/env',
                   *[k + '=' + v for k, v in current.items() if k.startswith('DYLD_')],
                   str(runtime / 'wine/bin/wine'), *arguments]
        return subprocess.run(command, cwd=cwd, env=current, capture_output=True, timeout=timeout)

    try:
        stop_wine(runtime, prefix)
        if not (prefix / 'system.reg').exists():
            boot = run(['wineboot', '-u'], 'zh_CN.UTF-8', work, 180)
            (work / 'wineboot.log').write_bytes(boot.stdout + boot.stderr)
            boot.check_returncode()
        drive = prefix / 'drive_c'
        mapping = drive / 'AirmaiDX'
        if mapping.is_symlink():
            mapping.unlink()
        elif mapping.exists():
            shutil.rmtree(mapping)
        package = work / 'HDD/Package'
        package.mkdir(parents=True, exist_ok=True)
        mapping.symlink_to(work / 'HDD', target_is_directory=True)
        for name in ['amfs', 'appdata', 'options']:
            (package / name).mkdir(exist_ok=True)
        shutil.copy2(runtime / 'helpers/AirmaiConfigurationProbe.exe', drive / 'AirmaiConfigurationProbe.exe')
        text = '; 中文注释：目录配置\n[vfs]\namfs=amfs\nappdata=appdata\noption=options\n'
        config = package / 'segatools.ini'
        results = []
        for name, locale, data, expected in [
                ('utf8-chinese', 'zh_CN.UTF-8', text.encode('utf-8'), 6),
                ('utf8-english', 'en_US.UTF-8', text.encode('utf-8'), 0),
                ('unicode-chinese', 'zh_CN.UTF-8', windows_ini_bytes(text), 0),
                ('unicode-english', 'en_US.UTF-8', windows_ini_bytes(text), 0),
                ('unicode-missing-directory', 'zh_CN.UTF-8', windows_ini_bytes(text.replace('amfs=amfs', 'amfs=missing')), 6),
                ('missing-config', 'zh_CN.UTF-8', None, 6)]:
            config.unlink(missing_ok=True)
            if data is not None:
                config.write_bytes(data)
            result = run([r'C:\AirmaiConfigurationProbe.exe'], locale, package)
            (work / (name + '.log')).write_bytes(result.stdout + result.stderr)
            values = result.stdout.decode(errors='replace').splitlines()
            assert result.returncode == expected, (name, result.returncode, values)
            assert ('config_codepage=936' if 'chinese' in name or 'missing' in name else 'config_codepage=1252') in values
            if expected == 0:
                assert all(label + '=1' in values for label in ['config_file', 'config_amfs', 'config_appdata', 'config_option'])
            row = dict(case=name, exit=result.returncode, expected=expected, passed=True)
            results.append(row)
            print(json.dumps(row), flush=True)
        (work / 'results.json').write_text(json.dumps(dict(checks=results, game_executed=False,
                                                        external_network_allowed=False), indent=2) + '\n')
    finally:
        stop_wine(runtime, prefix)


if __name__ == '__main__':
    main()
