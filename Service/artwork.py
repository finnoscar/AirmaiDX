"""Read version artwork from the user's own Unity files, never from the network."""
from pathlib import Path
import hashlib
import os
import re
import uuid
import xml.etree.ElementTree as ET

from storage import atomic_json
from game_identity import identity

CACHE_VERSION = 4


def texture_image(texture):
    """Decode Windows title textures without loading Unity audio/export tooling."""
    from PIL import Image
    import texture2ddecoder
    width, height = texture.m_Width, texture.m_Height
    data = bytes(texture.get_image_data())
    kind = int(texture.m_TextureFormat)
    if kind in [28, 29]:
        data = texture2ddecoder.unpack_unity_crunch(data)
        kind = 10 if kind == 28 else 12
    raw = {3: 'RGB', 4: 'RGBA', 5: 'ARGB', 14: 'BGRA'}
    if kind in raw:
        mode = 'RGB' if kind == 3 else 'RGBA'
        image = Image.frombytes(mode, (width, height), data[:width * height * (3 if kind == 3 else 4)], 'raw', raw[kind])
    else:
        decode = {10: texture2ddecoder.decode_bc1, 12: texture2ddecoder.decode_bc3,
                  25: texture2ddecoder.decode_bc7, 26: texture2ddecoder.decode_bc4,
                  27: texture2ddecoder.decode_bc5}.get(kind)
        if decode is None:
            raise ValueError('Unsupported title texture format')
        image = Image.frombytes('RGBA', (width, height), decode(data, width, height), 'raw', 'BGRA')
    return image.convert('RGBA').transpose(Image.Transpose.FLIP_TOP_BOTTOM)


def metadata(package, game, runtime=None):
    package = Path(package).resolve()
    title, region, version = '', '', game.get('gameVersion') or ''
    path = package / 'Sinmai_Data/StreamingAssets/RomConfig.xml'
    if path.is_file() and path.resolve().is_relative_to(package) and path.stat().st_size < 1024 * 1024:
        try:
            root = ET.fromstring(path.read_bytes())
            title = (root.findtext('projectName') or '').strip()
            region = (root.findtext('region') or '').strip().upper()
            parts = [root.findtext('version/' + key) for key in ['major', 'minor', 'release']]
            if all(value is not None and value.isdigit() for value in parts):
                version = f'{int(parts[0])}.{int(parts[1]):02d}.{int(parts[2]):02d}'
        except (ET.ParseError, ValueError):
            pass
    runtime_id, runtime_version = runtime if runtime is not None else identity(package)
    if (runtime_id or game.get('gameId')) == 'SDGB':
        verified_version = runtime_version if runtime_id == 'SDGB' else None
        if region != 'CHN' or (verified_version and verified_version != version):
            title = '舞萌 DX'
        region = 'CHN'
        version = verified_version or version
    return title, region, version


def select_logo(names, region, version, runtime_version=None):
    """Prefer complete regional title logos. Never choose an effect/mask or another region.

    A unique versioned title resource can correct a stale RomConfig. Multiple
    different versions require an exact match; the highest number is not proof.
    """
    candidates = []
    for name in names:
        if region == 'CHN':
            match = re.fullmatch(r'UI_ADV_Img_Logo(\d{3})', name, re.I)
            priority = 0
        elif region in ['JPN', 'EXP', 'TWN', 'KOR']:
            match = re.fullmatch(r'kari_LOGOv(\d{3})', name, re.I)
            priority = 0
            if not match:
                match = re.fullmatch(r'T_UI_LogoKariv(\d{3})', name, re.I)
                priority = 1
        else:
            continue
        if match:
            candidates.append((name, int(match[1]), priority))
    parts = version.split('.')
    code = int(parts[0]) * 100 + int(parts[1]) if len(parts) >= 2 and all(p.isdigit() for p in parts[:2]) else None
    if candidates:
        versions = {entry[1] for entry in candidates}
        matching = [entry for entry in candidates if entry[1] == code]
        if not matching and runtime_version and code is not None:
            # Regional artwork can use a series code one major lower than the
            # executable. Only accept it when this asset actually exists.
            matching = [entry for entry in candidates if entry[1] == code - 100]
        if not matching and not runtime_version and len(versions) == 1:
            matching = candidates
        if matching:
            selected = min(matching, key=lambda entry: (entry[2], entry[0]))
            return selected[0], f'{selected[1] // 100}.{selected[1] % 100:02d}.00'
    # Version tabs are complete labels in Japanese builds. China uses its own
    # annual logo and must never fall back to the Japanese version tab.
    if region == 'JPN' and code is not None:
        tab = f'UI_CMN_TabTitle_MaimaiTitle_Ver{code + 100}'
        if tab in names:
            return tab, version
    return None, version


def presentation(store, game):
    import json
    package = Path(game['packagePath']).resolve()
    runtime = identity(package)
    title, region, version = metadata(package, game, runtime)
    # SDEZ uses the established public-facing release in RomConfig/artwork.
    runtime_version = runtime[1] if runtime[0] == 'SDGB' else None
    sources = [package / 'Sinmai_Data' / name for name in ['resources.assets', 'sharedassets0.assets']]
    sources = [path for path in sources if path.is_file() and path.resolve().is_relative_to(package)
               and path.stat().st_size <= 512 * 1024 * 1024]
    fingerprint = hashlib.sha256(json.dumps([
        CACHE_VERSION, region, version, title, runtime_version,
        [(str(path.relative_to(package)), path.stat().st_size, path.stat().st_mtime_ns) for path in sources],
        [(p.name, p.stat().st_size, p.stat().st_mtime_ns)
         for p in sorted((package / 'Sinmai_Data').iterdir())
         if p.is_file() and p.suffix.lower() in ['.resource', '.ress']]
    ], ensure_ascii=False).encode()).hexdigest()
    cache = store.game_root(game) / 'Artwork'
    cache.mkdir(exist_ok=True)
    receipt = cache / 'title.json'
    if receipt.is_file():
        try:
            saved = json.loads(receipt.read_text())
            path = saved['result'].get('artworkPath')
            if saved.get('fingerprint') == fingerprint and (not path or
                    (Path(path).parent == cache and Path(path).is_file() and not Path(path).is_symlink())):
                return saved['result']
        except (KeyError, ValueError, TypeError):
            pass
    result = dict(title=title or ('舞萌 DX' if region == 'CHN' else 'maimai DX'),
                  region={'CHN': '中国大陆', 'JPN': '日本', 'EXP': '国际版', 'TWN': '台湾', 'KOR': '韩国'}.get(region, region or '地区未识别'),
                  version=version, artworkPath=None, artworkSource=None)
    try:
        import UnityPy
        for source in sources:
            environment = UnityPy.load(str(source))
            textures = {}
            for obj in environment.objects:
                if obj.type.name == 'Texture2D':
                    name = obj.peek_name()
                    if name:
                        textures[name] = obj
            selected, actual_version = select_logo(textures, region, version, runtime_version)
            if not selected:
                continue
            texture = textures[selected].read()
            if not (1 <= texture.m_Width <= 4096 and 1 <= texture.m_Height <= 4096):
                continue
            stream = getattr(texture, 'm_StreamData', None)
            if stream and stream.path:
                relative = Path(stream.path.replace('\\', '/'))
                if relative.is_absolute() or ':' in str(relative) or '..' in relative.parts:
                    continue
                resource = source.parent / relative
                if not resource.resolve().is_relative_to(package) or not resource.is_file():
                    continue
            image = texture_image(texture)
            bounds = image.getchannel('A').getbbox()
            if bounds:
                image = image.crop(bounds)
            image.thumbnail((1024, 512))
            output = cache / 'title.png'
            temporary = cache / ('.title-' + uuid.uuid4().hex + '.png')
            image.save(temporary)
            os.chmod(temporary, 0o600)
            temporary.replace(output)
            result.update(artworkPath=str(output), artworkSource=str(source.relative_to(package)) + '#' + selected,
                          version=version if runtime_version else actual_version)
            if actual_version != version:
                # This local build retains a stale Splash RomConfig while its
                # full title texture explicitly identifies MAGiCAL 1.70.
                result['title'] = ('maimai でらっくす MAGiCAL' if region == 'JPN' and actual_version == '1.70.00'
                                   else '舞萌 DX' if region == 'CHN' else 'maimai DX')
            break
    except Exception as error:
        # Failure to decode artwork must not prevent importing/starting a game.
        result['artworkIssue'] = type(error).__name__
    if 'artworkIssue' not in result:
        atomic_json(receipt, dict(fingerprint=fingerprint, result=result))
    return result
