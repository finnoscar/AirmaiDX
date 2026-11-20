"""Recoverable removal of an audited legacy provider that replaces Jvs.Execute.

An audited DLL is only optional in the package where its replacement was
verified. A matching input ABI alone does not prove that the HDD can lose it.
"""
from pathlib import Path
from storage import digest
from controller_devices import game_api_verified
from managed_mods import OWNED

LEGACY_INPUT_MODS = {
    'ADXHIDIOMod.dll': '848889c67c29a2abffdc7409009554aa3b3e1c473328b04dd9eafcad9c996832',
}


# Reviewed 1.65 after native rebasing and signed-cache activation. The code
# signature excludes only the audited conflict DLL and AirmaiDX-owned helpers.
REVIEWED_INPUT_STACKS = {'fbce2448c48600c815e726a3538bedd1a011644f02b86b48d55166a0ee47748b'}


def reviewed_stack(package, runtime, source):
    from compatibility import core_signature
    try:
        for name in OWNED:
            filename = name + '.dll'
            installed = package / 'Mods' / filename
            if installed.exists() or installed.is_symlink():
                if installed.is_symlink() or not installed.is_file() or installed.stat().st_size > 32*1024*1024:
                    return False
                if digest(installed) != digest(runtime / 'helpers' / filename):
                    return False
        return core_signature(package, ignored=(source.relative_to(package).as_posix(),)) in REVIEWED_INPUT_STACKS
    except (OSError, ValueError):
        return False


def prepare_input_mods(store, game, runtime, warnings=None):
    if not any(game['settings'].get(k, False) for k in ('adxEnabled', 'mouseEnabled', 'hdxEnabled')):
        return []
    package = Path(game['packagePath'])
    matched = []
    known = set(LEGACY_INPUT_MODS.values())
    for source in sorted((package/'Mods').glob('*'), key=lambda p:p.name.casefold()):
        if source.suffix.lower() != '.dll': continue
        if source.resolve() != source or not source.is_file(): raise ValueError('手台模组路径异常。')
        if source.stat().st_size > 32*1024*1024: continue
        fingerprint = digest(source)
        if fingerprint not in known: continue
        matched.append((source, fingerprint))
    if not matched:
        return []

    reviewed = (len(matched) == 1 and game_api_verified(runtime, package)
                and reviewed_stack(package, runtime, matched[0][0]))
    if not reviewed:
        if warnings is not None:
            warnings.append('已保留 ' + '、'.join(path.name for path, _ in matched[:4])
                            + '：未验证当前游戏、其余模组和输入接入可以在没有它的情况下运行。')
        return []

    source, fingerprint = matched[0]
    disabled = source.with_name(source.name+'.airmai-disabled')
    changes = []; expected = {}
    if disabled.is_symlink() or (disabled.exists() and (not disabled.is_file()
                                                       or disabled.stat().st_size > 32*1024*1024
                                                       or digest(disabled) != fingerprint)):
        raise ValueError('旧手台模组的保留副本发生变化，请先在诊断页检查恢复记录。')
    if not disabled.exists():
        changes.append((disabled, source.read_bytes())); expected[disabled] = None
    changes.append((source, None)); expected[source] = fingerprint
    store.replace_batch(game, changes, '旧手台输入模组冲突适配', allow_new=True, expected=expected)
    return [source.name]
