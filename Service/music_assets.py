"""Local song artwork, listening and lossless song transfer, independent of MCM."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import uuid
import wave
import zipfile

from music import music_xml, parse_xml

ROOTS = ('Sinmai_Data/StreamingAssets', 'option', 'options')


def packs(package):
    result = []
    for name in ROOTS:
        root = package / name
        if root.resolve() != root or not root.is_dir():
            continue
        result.extend(p for p in sorted(root.iterdir()) if p.resolve() == p and p.is_dir())
    return result


def source_files(package, xml):
    tree = parse_xml(xml.read_bytes())
    identity = int(tree.findtext('name/id'))
    pack = xml.parent.parent.parent
    candidates = [pack] + [p for p in reversed(packs(package)) if p != pack]
    result = {}
    for source in sorted(xml.parent.rglob('*')):
        if source.resolve() != source:
            raise ValueError('曲目包含文件链接，无法复制或导出。')
        if source.is_file():
            result[str(Path('music') / xml.parent.name / source.relative_to(xml.parent))] = source
    media = identity % 10000
    cue = int(tree.findtext('cueName/id', str(media)))
    movie = int(tree.findtext('movieName/id', str(media)))
    for directory, stem, extensions in [
        ('AssetBundleImages/jacket', f'ui_jacket_{media:06d}', ('.ab', '.png', '.jpg', '.jpeg', '.webp')),
        ('SoundData', f'music{cue:06d}', ('.acb', '.awb', '.wav', '.m4a', '.mp3', '.ogg')),
        ('MovieData', f'{movie:06d}', ('.dat', '.usm', '.mp4')),
    ]:
        # A selected expansion's own resources precede fallback packs.
        for extension in extensions:
            relative = str(Path(directory) / (stem + extension))
            for candidate in candidates:
                source = candidate / relative
                if source.is_file() and source.resolve() == source:
                    result[relative] = source
                    break
    return result


def cache_key(files):
    return hashlib.sha256(json.dumps([(str(p), p.stat().st_size, p.stat().st_mtime_ns)
                                      for p in files]).encode()).hexdigest()


def media(store, game, runtime, request):
    package = Path(game['packagePath'])
    xml = music_xml(package, request['path'])
    files = source_files(package, xml)
    kind = request['kind']
    if kind not in ('cover', 'audio'):
        raise ValueError('未知的曲目资源类型。')
    directory = 'AssetBundleImages/jacket/' if kind == 'cover' else 'SoundData/'
    sources = [p for relative, p in files.items() if relative.startswith(directory)]
    if not sources:
        return dict(path=None, issue='没有找到封面资源。' if kind == 'cover' else '没有找到原曲音频。')
    cache = store.game_root(game) / 'Artwork' / 'Music'
    cache.mkdir(parents=True, exist_ok=True)
    # Audio and texture sidecar changes invalidate decoded results too.
    companions = [p for source in sources for p in source.parent.iterdir()
                  if (p.stem == source.stem or p.name.startswith(source.name + '.')) and p.is_file() and p.resolve() == p]
    target = cache / (cache_key(sorted(set(sources + companions))) + ('.png' if kind == 'cover' else '.wav'))
    if target.is_file() and not target.is_symlink():
        return dict(path=str(target), issue=None)
    temporary = cache / (uuid.uuid4().hex + target.suffix)
    try:
        if kind == 'cover':
            image = cover_image(sources)
            image.thumbnail((512, 512))
            image.save(temporary, format='PNG')
        else:
            native = next((p for p in sources if p.suffix.lower() in ('.wav', '.m4a', '.mp3')), None)
            if native:
                return dict(path=str(native), issue=None)
            decoder = runtime / 'helpers/vgmstream-cli'
            if not decoder.is_file():
                raise ValueError('应用内缺少原曲试听组件，请重新安装完整应用。')
            source = next((p for p in sources if p.suffix.lower() == '.awb'), sources[0])
            if source.stat().st_size > 256 * 1024 * 1024:
                raise ValueError('音频资源过大，无法试听。')
            result = subprocess.run([str(decoder), '-i', '-s', '1', '-o', str(temporary), str(source)],
                                    capture_output=True, timeout=60)
            if result.returncode or not temporary.is_file():
                raise ValueError('无法解码该曲目的音频，请检查 ACB/AWB 是否完整或是否需要包内音频密钥。')
            with wave.open(str(temporary)) as audio:
                if not 0 < audio.getnframes() / audio.getframerate() <= 1200:
                    raise ValueError('音频时长超出试听范围。')
        os.chmod(temporary, 0o600)
        temporary.replace(target)
        return dict(path=str(target), issue=None)
    except Exception as error:
        return dict(path=None, issue=str(error))
    finally:
        temporary.unlink(missing_ok=True)


def cover_image(sources):
    from PIL import Image
    for source in sources:
        if source.stat().st_size > 64 * 1024 * 1024:
            continue
        if source.suffix.lower() != '.ab':
            with Image.open(source) as image:
                return image.convert('RGBA')
    import UnityPy
    from artwork import texture_image
    for source in sources:
        environment = UnityPy.load(str(source))
        for obj in environment.objects:
            if obj.type.name != 'Texture2D':
                continue
            texture = obj.read()
            if not (0 < texture.m_Width <= 8192 and 0 < texture.m_Height <= 8192):
                continue
            stream = getattr(texture, 'm_StreamData', None)
            if stream and stream.path:
                name = Path(stream.path)
                if name.is_absolute() or '..' in name.parts or (source.parent / name).resolve() != source.parent / name:
                    raise ValueError('封面纹理引用了资源包外的文件。')
            return texture_image(texture)
    raise ValueError('资源中没有可读取的封面纹理。')


def transfer(store, game, request):
    package = Path(game['packagePath'])
    xml = music_xml(package, request['path'])
    files = source_files(package, xml)
    operation = request['action']
    if operation == 'export':
        destination = Path(request['destination'])
        if (destination.suffix.lower() != '.zip' or destination.exists()
                or destination.parent.resolve() != destination.parent or not destination.parent.is_dir()
                or destination.is_relative_to(package)):
            raise ValueError('请选择游戏目录外尚不存在的 ZIP 文件。')
        # Exclusive publication prevents overwriting a file created after the dialog.
        temporary = destination.parent / ('.airmai-export-' + uuid.uuid4().hex)
        try:
            with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
                for relative, source in files.items():
                    archive.write(source, relative)
            os.chmod(temporary, 0o600)
            os.link(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return dict(path=str(destination), files=len(files))
    if operation != 'copy':
        raise ValueError('未知的曲目操作。')
    store.assert_stopped(game)
    target = Path(request['destination'])
    if target not in packs(package) or target.name.upper() == 'A000' or target == xml.parent.parent.parent:
        raise ValueError('请选择另一份非 A000 的扩展资源包。')
    # All conflicts are checked before creating folders or writing any file.
    updates = []
    total = 0
    for relative, source in files.items():
        destination = target / relative
        if destination.resolve() != destination:
            raise ValueError('目标资源包含文件链接。')
        total += source.stat().st_size
        if total > 512 * 1024 * 1024:
            raise ValueError('关联资源超过 512 MB，请使用 ZIP 导出。')
        data = source.read_bytes()
        if destination.exists():
            if not destination.is_file() or destination.read_bytes() != data:
                raise ValueError('目标包中存在不同内容的同名文件：' + relative + '。未写入任何文件。')
        else:
            updates.append((destination, data))
    created = []
    try:
        for destination, _ in updates:
            missing = []
            parent = destination.parent
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for parent in reversed(missing):
                parent.mkdir()
                created.append(parent)
        if updates:
            store.replace_batch(game, updates, '复制曲目及关联资源', allow_new=True,
                                expected={p: None for p, _ in updates})
    except BaseException:
        for directory in reversed(created):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    return dict(path=str(target / 'music' / xml.parent.name / 'Music.xml'), files=len(updates))
