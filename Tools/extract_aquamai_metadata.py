"""Read public AquaMai C# attribute text; never build or load an assembly.

Only localized documentation is exported. Defaults, patches and executable
implementation are deliberately absent from the generated UI reference.
"""
from pathlib import Path
import argparse
import json
import re
import textwrap


def string_at(text, start):
    if text.startswith('"""', start):
        end = text.index('"""', start + 3)
        return textwrap.dedent(text[start + 3:end]).strip(), end + 3
    if text.startswith('@"', start):
        cursor, out = start + 2, []
        while cursor < len(text):
            if text.startswith('""', cursor):
                out.append('"'); cursor += 2
            elif text[cursor] == '"':
                return ''.join(out), cursor + 1
            else:
                out.append(text[cursor]); cursor += 1
    if text[start] == '"':
        cursor = start + 1
        while cursor < len(text):
            if text[cursor] == '\\': cursor += 2
            elif text[cursor] == '"':
                return json.loads(text[start:cursor + 1]), cursor + 1
            else: cursor += 1
    raise ValueError('Unterminated C# attribute string')


def attribute(text, start):
    """Read scalar docs without treating a named description as a display name."""
    cursor = text.index('(', start) + 1
    arguments, position = {}, 0
    positional = ['name', 'en', 'zh']
    while cursor < len(text):
        if text[cursor].isspace() or text[cursor] == ',':
            cursor += 1; continue
        if text.startswith('//', cursor):
            newline = text.find('\n', cursor)
            if newline < 0: break
            cursor = newline + 1; continue
        if text.startswith('/*', cursor):
            cursor = text.index('*/', cursor + 2) + 2; continue
        if text[cursor] == ')': return arguments, cursor + 1
        match = re.match(r'(\w+)\s*:\s*', text[cursor:])
        if match:
            key = match[1]; cursor += match.end()
        else:
            key = positional[position] if position < len(positional) else str(position)
            position += 1
        if text[cursor] == '"' or text.startswith('@"', cursor):
            arguments[key], cursor = string_at(text, cursor)
        else:
            match = re.match(r'[^,)\s]+', text[cursor:])
            if not match: raise ValueError('Unsupported attribute argument')
            arguments[key] = match[0]; cursor += match.end()
    raise ValueError('Unterminated C# attribute')


def humanize(name):
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', name).replace('_', ' ')


def extract(root, commit):
    sections = {}
    for path in sorted((root / 'AquaMai.Mods').rglob('*.cs')):
        text = path.read_text(encoding='utf-8-sig')
        section_match = re.search(r'\[ConfigSection\s*\(', text)
        if not section_match: continue
        section, end = attribute(text, section_match.start())
        namespace = re.search(r'namespace\s+AquaMai\.Mods(?:\.([\w.]+))?\s*[;{]', text)
        typ = re.search(r'\bclass\s+(\w+)', text[end:])
        if not namespace or not typ: raise ValueError(f'Cannot identify config section: {path}')
        namespace_path = namespace[1] or ''
        name = namespace_path if namespace_path.split('.')[-1] == typ[1] else '.'.join(part for part in (namespace_path, typ[1]) if part)
        result = dict(title={'zh-Hans': section.get('name') or typ[1], 'en': humanize(typ[1])},
                      help={'zh-Hans': section.get('zh') or section.get('name') or '', 'en': section.get('en', '')},
                      entries={}, source=str(path.relative_to(root)), alwaysEnabled=section.get('alwaysEnabled') == 'true')
        for match in re.finditer(r'\[ConfigEntry\s*\(', text[end:]):
            entry, entry_end = attribute(text, end + match.start())
            # The attribute is followed by a field, never evaluated or compiled.
            declaration = re.search(r'(?:public|private|internal|protected)\s+(?:(?:static|readonly|const)\s+)*[\w.<>\[\], ?]+\s+(\w+)\s*[=;]', text[entry_end:])
            if not declaration: raise ValueError(f'Cannot identify entry: {path}')
            field = declaration[1]
            field = field[0].upper() + field[1:]
            result['entries'][field] = dict(title={'zh-Hans': entry.get('name') or field, 'en': humanize(field)},
                                            help={'zh-Hans': entry.get('zh') or entry.get('name') or '', 'en': entry.get('en', '')})
        sections[name] = result
    return dict(formatVersion=1, source=dict(repository='https://github.com/MewoLab/AquaMai', commit=commit,
                license='Apache-2.0', scope='Localized attribute documentation; reference only, not runtime defaults'), sections=sections)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    result = extract(args.source, args.commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(len(result['sections']), 'sections;', sum(len(s['entries']) for s in result['sections'].values()), 'entries')
