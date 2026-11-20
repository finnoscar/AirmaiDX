"""Activate publisher-signed, user-supplied AquaMai caches without Wine CNG.

No downloads, signature bypasses or redistributed mod/game assemblies.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile
import tomllib
import dnfile
from storage import decode_text, digest

LIMIT = 128 * 1024 * 1024
# This loader's block layout, keys and offline behavior were inspected locally.
SUPPORTED_LOADERS = {'e80baeba459e0c7ecb83cad5f84419cb5f708e63d43ba450d01cc88cf297cd86'}


def activate_signed_cache(store, game, verifier):
    package = Path(game['packagePath'])
    loader = package / 'Mods/MuMod.dll'
    target = package / 'Mods/AquaMai.dll'
    disabled = package / 'Mods/MuMod.dll.airmai-disabled'
    if target.exists() and (not loader.exists() or not disabled.exists()):
        return None
    source = loader if loader.exists() else disabled
    if not source.exists():return None
    store.assert_stopped(game)
    if source.resolve() != source or not source.is_file():
        raise ValueError('MuMod 文件路径异常，请重新导入。')
    original = source.read_bytes()
    original_sha = hashlib.sha256(original).hexdigest()
    if original_sha not in SUPPORTED_LOADERS:
        raise ValueError('这版 MuMod 尚未验证本地缓存兼容性；请提供诊断包，或使用包内原有的独立 AquaMai。')
    config = package / 'MuMod.toml'
    cache_name = r'LocalAssets/MuMod.cache'
    if config.is_file():
        if config.resolve() != config:
            raise ValueError('MuMod 配置路径异常。')
        cache_name = tomllib.loads(decode_text(config.read_bytes())[0]).get('CachePath', cache_name)
    if not isinstance(cache_name, str) or ':' in cache_name or '\x00' in cache_name:
        raise ValueError('MuMod 缓存路径无效。')
    cache = package / cache_name.replace(chr(92), '/')
    if cache.resolve() != cache or not cache.is_relative_to(package) or not cache.is_file():
        raise ValueError('包内缺少有效 MuMod 本地缓存。请在 Windows 更新后重新导入，或提供独立 AquaMai；应用不会静默联网下载。')
    if not 22 < cache.stat().st_size <= LIMIT:
        raise ValueError('MuMod 本地缓存大小异常。')
    with cache.open('rb') as stream:data = stream.read(LIMIT+1)
    if len(data)>LIMIT:raise ValueError('MuMod 本地缓存大小异常。')
    setup = store.game_root(game) / 'Setup'
    setup.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='signed-cache-', dir=setup) as temporary:
        snapshot = Path(temporary) / 'cache'
        snapshot.write_bytes(data)
        snapshot.chmod(0o600)
        result = subprocess.run([str(verifier), str(snapshot)], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError('MuMod 本地缓存签名验证失败；已保留原件，请更新有效缓存或提供独立 AquaMai。')
    verified = json.loads(result.stdout)
    length = verified.get('payloadLength')
    if (verified.get('verified') is not True or type(length) is not int or not 0 < length < len(data)
            or hashlib.sha256(data).hexdigest() != verified.get('cacheSHA256')):
        raise ValueError('MuMod 缓存验证结果不完整。')
    payload = data[:length]
    if hashlib.sha256(payload).hexdigest() != verified.get('sha256'):
        raise ValueError('MuMod 缓存内容校验失败。')
    with dnfile.dnPE(data=payload) as image:
        if not image.net or len(image.net.mdtables.Assembly.rows) != 1:
            raise ValueError('MuMod 缓存不是有效的 AquaMai 程序集。')
        assembly = image.net.mdtables.Assembly.rows[0]
        if str(assembly.Name) != 'AquaMai':
            raise ValueError('MuMod 缓存中的程序集名称异常。')
    if disabled.exists() and (disabled.resolve()!=disabled or digest(disabled)!=original_sha):
        raise ValueError('MuMod 适配备份不匹配，请先在诊断中恢复后重试。')
    if target.exists() and (target.resolve()!=target or digest(target)!=verified['sha256']):
        raise ValueError('AquaMai 在适配中断后已被修改，请先在诊断中恢复后重试。')
    updates=[];expected={}
    if not disabled.exists():updates.append((disabled,original));expected[disabled]=None
    if loader.exists():updates.append((loader,None));expected[loader]=original_sha
    if not target.exists():updates.append((target,payload));expected[target]=None
    # One restore point and rollback for the entire activation; never leave
    # both loaders enabled. The verified disabled copy also lets the next
    # launch resume safely if the manager was killed between atomic writes.
    if updates:store.replace_batch(game,updates,'MuMod 已签名本地缓存适配',allow_new=True,expected=expected)
    return dict(cacheSHA256=verified['cacheSHA256'], sha256=verified['sha256'])
