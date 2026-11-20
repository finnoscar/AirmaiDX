"""Bounded static CLR inspection. Never load assemblies into a CLR or alter them."""
from pathlib import Path
import json
import zlib

import dnfile
import pefile

from managed_mods import Metadata, MOD_LIMIT, OWNED

LIMIT = 32 * 1024 * 1024
SCAN_ERRORS = (OSError, ValueError, IndexError, KeyError, AttributeError, TypeError, RecursionError,
               pefile.PEFormatError, dnfile.errors.dnFormatError, zlib.error)
OWNED_NAMES = {name.casefold() for name in OWNED}
API = 'UnityEngine.FullScreenMode'


def fullscreen_api(blob, label, embedded=True, budget=None):
    """Report actual TypeDef/TypeRef metadata, including AquaMai's packed DLLs."""
    if len(blob) > LIMIT:
        raise ValueError(label + ' 超出静态检查大小限制')
    budget = [2 * LIMIT] if budget is None else budget
    budget[0] -= len(blob)
    if budget[0] < 0:
        raise ValueError(label + ' 超出模组静态检查总大小限制')
    with dnfile.dnPE(data=blob, clr_lazy_load=True) as image:
        if image.net is None:
            return dict(defines=False, references=[], assembly=None)
        tables = image.net.mdtables
        if tables is None:
            raise ValueError(label + ' 缺少 CLR 元数据')
        defines = any(str(row.TypeNamespace) == 'UnityEngine' and str(row.TypeName) == 'FullScreenMode'
                      for table in ('TypeDef', 'ExportedType')
                      for row in getattr(getattr(tables, table, None), 'rows', []))
        def uses_fullscreen(row):
            scope = getattr(row.ResolutionScope, 'row', None)
            return (str(row.TypeNamespace) == 'UnityEngine' and str(row.TypeName) == 'FullScreenMode'
                    and isinstance(scope, dnfile.mdtable.AssemblyRefRow)
                    and str(scope.Name).casefold() in {'unityengine', 'unityengine.coremodule'})
        uses = any(uses_fullscreen(row) for row in getattr(getattr(tables, 'TypeRef', None), 'rows', []))
        module = Metadata(image).module()
        references = [label] if uses else []
        # AquaMai stores its own managed DLLs as raw Deflate resources. Read
        # one level only, with per-resource and aggregate expansion limits.
        total = 0
        if embedded:
            resources = image.net.resources
            if len(resources) > 128:
                raise ValueError(label + ' 内嵌资源数超出静态检查限制')
            for resource in resources:
                name = str(resource.name)
                kind = name.lower()
                data = resource.data
                if not isinstance(data, bytes) or not kind.endswith(('.dll', '.dll.compressed')):
                    continue
                if kind.endswith('.compressed'):
                    inflater = zlib.decompressobj(-15)
                    data = inflater.decompress(data, min(LIMIT, max(0, budget[0])) + 1)
                    if len(data) > LIMIT or not inflater.eof or inflater.unconsumed_tail:
                        raise ValueError(label + ' 内嵌 DLL 超出静态检查限制或内容损坏')
                total += len(data)
                if total > LIMIT:
                    raise ValueError(label + ' 内嵌 DLL 总大小超出静态检查限制')
                nested = fullscreen_api(data, label + ' → ' + name.removesuffix('.compressed'), False, budget)
                references.extend(nested['references'])
        return dict(defines=defines, references=references, assembly=module['assembly'])


def read_api(path, label):
    if path.is_symlink() or path.stat().st_size > LIMIT:
        raise ValueError(label + ' 不是可安全检查的本地 DLL')
    return fullscreen_api(path.read_bytes(), label)


def legacy_mod_check(package):
    """Report confirmed missing engine APIs; never infer that a mod is optional."""
    package = Path(package)
    report = dict(blockers=[], warnings=[])
    managed = package / 'Sinmai_Data/Managed'
    folder = package / 'Mods'
    engines = {'unityengine', 'unityengine.coremodule'}
    try:
        cores = [managed / name for name in ['UnityEngine.CoreModule.dll', 'UnityEngine.dll']]
        present = [read_api(p, p.relative_to(package).as_posix()) for p in cores if p.exists() or p.is_symlink()]
        if not present or any((api['assembly'] or '').casefold() not in engines for api in present):
            raise ValueError('Unity 核心程序集无法识别')
        if any(api['defines'] for api in present):
            return report
        folders = [folder, package / 'Plugins']
        if any(directory.is_symlink() for directory in folders):
            raise ValueError('Mods 或 Plugins 目录是文件链接')
        paths = sorted((p for directory in folders for p in directory.glob('*') if p.suffix.lower() == '.dll'),
                       key=lambda p: (p.parent.name, p.name.casefold()))
        if len(paths) > MOD_LIMIT:
            raise ValueError('模组数量超出静态检查限制')
    except SCAN_ERRORS as error:
        report['blockers'].append('Unity 2017 模组 API 检查未完成：' + str(error))
        return report

    budget = [2 * LIMIT]
    for path in paths:
        if path.parent == folder and path.stem.casefold() in OWNED_NAMES:
            continue  # The launcher replaces its own helpers during preparation.
        label = path.relative_to(package).as_posix()
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > LIMIT:
                raise ValueError('不是可安全检查的本地 DLL')
            meta = fullscreen_api(path.read_bytes(), label, budget=budget)
            if meta['assembly'] is None:
                raise ValueError('非托管 DLL')
            if meta['references']:
                report['blockers'].append('Unity 2017 核心缺少 ' + API + '，'
                                          + '、'.join(meta['references'][:4]) + ' 引用了该接口。'
                                          + '已保留模组，请使用与当前引擎匹配的版本。')
        except SCAN_ERRORS:
            report['warnings'].append(label + ' 无法完成静态检查；已保留原件。')
    return report


def previously_disabled_mods(package, report_path):
    """Keep previous releases’ Unity quarantine records visible for recovery."""
    from storage import digest
    previous = []
    try:
        if report_path.is_file() and not report_path.is_symlink() and report_path.stat().st_size <= LIMIT:
            previous = json.loads(report_path.read_text()).get('disabledUnsupportedModules', [])
    except (OSError, ValueError, AttributeError):
        pass
    result = {}
    if not isinstance(previous, list):
        previous = []
    for entry in previous[:MOD_LIMIT]:
        if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) for k in ('file', 'reason', 'sha256')):
            continue
        source = package / entry['file']
        saved = source.with_name(source.name + '.airmai-disabled') if source.name else source
        try:
            if (source.parent == package / 'Mods' and source.suffix.lower() == '.dll' and source.resolve() == source
                    and not source.exists() and saved.is_file() and not saved.is_symlink()
                    and saved.stat().st_size <= LIMIT and digest(saved) == entry['sha256']):
                result[entry['file']] = entry
        except OSError:
            continue
    return list(result.values())
