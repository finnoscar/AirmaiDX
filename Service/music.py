"""Validate and commit an AirmaiDX music draft in one recovery point."""
import base64
import hashlib
from pathlib import Path
import re
import xml.etree.ElementTree as ET

MAX_CHART_BYTES = 16 * 1024 * 1024
SHA256 = re.compile(r'[a-f0-9]{64}')
MA2_VERSION = re.compile(rb'(?m)^VERSION[ \t]+\S+[ \t]+1\.0([2-5])\.\d{2}[ \t]*\r?$')
NOTE_RECORD = re.compile(
    r'(?m)^(NM|BR|EX|BX|CN)?'
    r'(TAP|BRK|XTP|STR|BST|XST|HLD|XHO|TTP|THO|SI_|SCL|SCR|SUL|SUR|SSL|SSR|SV_|SXL|SXR|SLL|SLR|SF_)'
    r'[ \t]+\d+[ \t]+\d+[ \t]+[0-7](?:[ \t]|\r?$)'
)


def music_xml(package, path):
    path = Path(path)
    if path.resolve() != path or not path.is_relative_to(package) or not path.is_file():
        raise ValueError('只能编辑游戏副本中的曲目资料。')
    parts = path.relative_to(package).parts
    for prefix in [('Sinmai_Data', 'StreamingAssets'), ('option',), ('options',)]:
        suffix = parts[len(prefix):]
        if (parts[:len(prefix)] == prefix and len(suffix) == 4
                and suffix[1] == 'music' and suffix[-1] == 'Music.xml'):
            return path
    raise ValueError('曲目不在应用曲库的资源包中。')


def chart_path(folder, relative, side):
    # An MA2 belongs to its Music.xml directory, including a possible subdirectory.
    name = Path(relative)
    if not relative or '\\' in relative or name.is_absolute() or '..' in name.parts or name.suffix.lower() != '.ma2':
        raise ValueError('谱面文件路径无效。')
    if side:
        name = name.with_name(f'{name.stem}_{side}.ma2')
    path = folder / name
    if path.resolve() != path or not path.is_relative_to(folder) or not path.parent.is_dir():
        raise ValueError('谱面路径超出曲目目录或包含文件链接。')
    return path


def parse_xml(data):
    tree = ET.fromstring(data, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    if tree.tag != 'MusicData':
        raise ValueError('曲目资料格式不正确。')
    return tree


def chart_summary(data):
    if not 0 < len(data) <= MAX_CHART_BYTES or b'\0' in data:
        raise ValueError('请选择小于 16 MB 的有效 MA2 文件。')
    header = MA2_VERSION.search(data.removeprefix(b'\xef\xbb\xbf')[:2048])
    if not header:
        raise ValueError('请选择 MA2 1.02 至 1.05 文件。')
    text = data.decode('utf-8-sig')
    values = re.findall(r'(?m)^T_NUM_ALL[ \t]+(\d+)[ \t]*\r?$', text)
    if len(values) != 1 or not 0 < int(values[0]) <= 100000:
        raise ValueError('谱面缺少有效的 T_NUM_ALL 音符统计。')
    total = int(values[0])
    counted = sum(1 for row in NOTE_RECORD.finditer(text) if row[1] != 'CN')
    if counted != total:
        raise ValueError('谱面音符与 T_NUM_ALL 统计不一致。')
    return int(header[1]), total


def package_has_ma2_105(package):
    for root in ('Sinmai_Data/StreamingAssets', 'option', 'options'):
        for path in (package / root).glob('*/music/*/*.ma2'):
            if path.resolve() != path or not path.is_file():
                continue
            with path.open('rb') as stream:
                header = MA2_VERSION.search(stream.read(2048).removeprefix(b'\xef\xbb\xbf'))
            if header and header[1] == b'5':
                return True
    return False


def save_draft(store, game, request):
    store.assert_stopped(game)
    xml = music_xml(Path(game['packagePath']), request['path'])
    original = xml.read_bytes()
    if hashlib.sha256(original).hexdigest() != request['sha256']:
        raise ValueError('曲目资料已变化，请重新打开后再保存。')
    data = base64.b64decode(request['data'], validate=True)
    previous, edited = parse_xml(original), parse_xml(data)
    identity = previous.findtext('name/id')
    dual = previous.findtext('utagePlayStyle') == '1'
    if (edited.findtext('name/id') != identity
            or edited.findtext('utagePlayStyle') != previous.findtext('utagePlayStyle')):
        raise ValueError('曲目编号或宴谱类型已变化，请重新打开曲目。')
    old_charts = previous.findall('notesData/Notes')
    charts = edited.findall('notesData/Notes')
    if len(old_charts) != len(charts):
        raise ValueError('难度条目数量不一致。')
    if any(a.findtext('file/path', '') != b.findtext('file/path', '') for a, b in zip(old_charts, charts)):
        raise ValueError('请通过导入 MA2 更新谱面文件。')

    replacements = request.get('charts', [])
    updates = {}
    counts = {}
    expected = {xml: request['sha256']}
    touched = set()
    supports_105 = False
    for change in replacements:
        index = change['level']
        side = change.get('side', '')
        if type(index) is not int or not 0 <= index < len(charts) or side not in (('L', 'R') if dual else ('',)):
            raise ValueError('难度或宴谱侧别无效。')
        chart = charts[index]
        relative = chart.findtext('file/path', '').strip()
        if not relative:
            relative = f'{int(identity):06d}_{index:02d}.ma2'
            node = chart.find('file')
            if node is None:
                node = ET.SubElement(chart, 'file')
            path_node = node.find('path')
            if path_node is None:
                path_node = ET.SubElement(node, 'path')
            path_node.text = relative
        target = chart_path(xml.parent, relative, side)
        if target in updates:
            raise ValueError('同一谱面文件只能导入一次。')
        for other_index, other in enumerate(charts):
            if other_index == index:
                continue
            other_name = other.findtext('file/path', '').strip()
            if other_name and Path(other_name) == Path(relative):
                raise ValueError('多个难度共用这个谱面文件，请先检查曲目资料。')
        original_hash = change['sha256']
        if original_hash is not None and (not isinstance(original_hash, str) or not SHA256.fullmatch(original_hash)):
            raise ValueError('谱面校验值无效。')
        chart_data = base64.b64decode(change['data'], validate=True)
        version, count = chart_summary(chart_data)
        if version == 5 and not supports_105:
            supports_105 = package_has_ma2_105(Path(game['packagePath']))
            if not supports_105:
                raise ValueError('目标游戏没有发现 MA2 1.05 谱面，请导出与目标版本匹配的 MA2。')
        counts[target] = count
        updates[target] = chart_data
        expected[target] = original_hash
        touched.add(index)

    for index, chart in enumerate(charts):
        enabled = chart.findtext('isEnable', '').lower() in ('true', '1')
        previously_enabled = old_charts[index].findtext('isEnable', '').lower() in ('true', '1')
        if index not in touched and (not enabled or previously_enabled):
            continue
        sides = ('L', 'R') if dual else ('',)
        relative = chart.findtext('file/path', '').strip()
        targets = [chart_path(xml.parent, relative, side) for side in sides]
        if any(target not in updates and not target.is_file() for target in targets):
            raise ValueError('启用或替换该难度前，请补齐所需的 MA2 谱面。')
        if index in touched:
            total = sum(counts[target] if target in counts else chart_summary(target.read_bytes())[1] for target in targets)
            node = chart.find('maxNotes')
            if node is None:
                node = ET.SubElement(chart, 'maxNotes')
            node.text = str(total)

    if replacements:
        data = ET.tostring(edited, encoding='utf-8', xml_declaration=True)
    updates[xml] = data
    store.replace_batch(game, list(updates.items()), '曲目与谱面修改', allow_new=True, expected=expected)
    return True
