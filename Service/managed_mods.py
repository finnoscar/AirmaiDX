"""Bounded CLR metadata inspection; never execute a mod or its attributes.

Recognize Melon modules and the public input ABI by capabilities, independent
of packaging filename or release hash. Runtime registration remains checked.
"""
from pathlib import Path
import zlib
import dnfile
import pefile

FILE_LIMIT = 32 * 1024 * 1024
EXPANDED_LIMIT = 64 * 1024 * 1024
MOD_LIMIT = 64
OWNED = {'AirmaiBootTrace', 'AirmaiDisplayTrace', 'AirmaiDisplayBridge',
         'AirmaiHdxNativeTouch', 'AirmaiHdxNativeLed', 'AirmaiControllerInput', 'AirmaiMouseInput'}


class Metadata:
    def __init__(self, image):
        self.tables = image.net.mdtables
        self.types = self.tables.TypeDef.rows
        self.type_indices = {id(row):i for i,row in enumerate(self.types, 1)}
        self.signature_depth = 0
        self.parents = {r.NestedClass.row_index:r.EnclosingClass.row_index
                        for r in getattr(getattr(self.tables, 'NestedClass', None), 'rows', [])}

    def type_name(self, row, depth=0):
        if depth > 16: raise ValueError('Nested type limit')
        if isinstance(row, dnfile.mdtable.TypeDefRow):
            index = self.type_indices[id(row)]
            if index in self.parents:
                return self.type_name(self.types[self.parents[index]-1], depth+1)+'+'+str(row.TypeName)
        scope = getattr(row, 'ResolutionScope', None)
        if scope and isinstance(scope.row, dnfile.mdtable.TypeRefRow):
            return self.type_name(scope.row, depth+1)+'+'+str(row.TypeName)
        return '.'.join(filter(None, [str(row.TypeNamespace), str(row.TypeName)]))

    def coded_type(self, value):
        tables = [self.tables.TypeDef, self.tables.TypeRef, self.tables.TypeSpec]
        tag, index = value & 3, (value >> 2)-1
        if tag > 2 or index < 0 or index >= len(tables[tag].rows): raise ValueError('Invalid type token')
        row = tables[tag].rows[index]
        if tag != 2: return self.type_name(row)
        self.signature_depth += 1
        try:
            if self.signature_depth > 16: raise ValueError('Type specification nesting limit')
            return Signature(row.Signature.value, self).element()
        finally: self.signature_depth -= 1

    def method(self, row):
        return Signature(row.Signature.value, self).method()

    def module(self):
        assemblies = getattr(getattr(self.tables, 'Assembly', None), 'rows', [])
        if len(assemblies) != 1: raise ValueError('Missing assembly identity')
        assembly = assemblies[0]
        def melon_base(row, seen=None):
            seen = set() if seen is None else seen
            if id(row) in seen or len(seen) > 16: return False
            seen.add(id(row)); base = getattr(row, 'Extends', None)
            if not base or not base.row: return False
            if not isinstance(base.row, (dnfile.mdtable.TypeDefRow, dnfile.mdtable.TypeRefRow)): return False
            if self.type_name(base.row) == 'MelonLoader.MelonMod': return True
            return isinstance(base.row, dnfile.mdtable.TypeDefRow) and melon_base(base.row, seen)
        return dict(assembly=str(assembly.Name), version='.'.join(str(getattr(assembly, k)) for k in
                    ['MajorVersion','MinorVersion','BuildNumber','RevisionNumber']),
                    melonMod=any(melon_base(row) for row in self.types))

    def input_contract(self):
        named = {self.type_name(r):r for r in self.types}
        jvs = named.get('AquaMai.Core.Helpers.JvsSwitchHook')
        touch = named.get('AquaMai.Core.Helpers.TouchStatusProvider')
        if jvs is None or touch is None: return False
        def register(owner, name, prefix, result, arguments):
            methods = [m.row for m in owner.MethodList if str(m.row.Name) == name and m.row.Flags.mdPublic and m.row.Flags.mdStatic]
            if len(methods) != 1: return None
            static, ret, parameters = self.method(methods[0])
            if not static or ret != 'void' or len(parameters) != len(prefix)+1 or parameters[:-1] != prefix: return None
            delegate = named.get(parameters[-1])
            if delegate is None or not delegate.Extends or self.type_name(delegate.Extends.row) != 'System.MulticastDelegate': return None
            invokes = [m.row for m in delegate.MethodList if str(m.row.Name) == 'Invoke' and m.row.Flags.mdPublic]
            if len(invokes) != 1: return None
            is_static, output, params = self.method(invokes[0])
            if is_static or params != arguments or (result is not None and output != result): return None
            return output
        if register(jvs, 'RegisterButtonChecker', [], 'bool', ['int32','int32']) != 'bool': return False
        if register(touch, 'RegisterTouchStatusProvider', ['int32'], 'uint64', ['int32']) != 'uint64': return False
        auxiliary = register(jvs, 'RegisterAuxiliaryStateProvider', [], None, [])
        state = named.get(auxiliary)
        if state is None or not state.Extends or self.type_name(state.Extends.row) != 'System.ValueType': return False
        fields = {str(f.row.Name):f.row for f in state.FieldList}
        for name in ['select1P','select2P','service','test']:
            field = fields.get(name)
            if field is None or not field.Flags.fdPublic or field.Flags.fdStatic or field.Signature.value != b'\x06\x02': return False
        return True


class Signature:
    def __init__(self, data, metadata):
        self.data = data; self.at = 0; self.metadata = metadata

    def uint(self):
        if self.at >= len(self.data): raise ValueError('Truncated CLR signature')
        byte = self.data[self.at]; self.at += 1
        if byte < 128: return byte
        count = 1 if byte < 192 else 3 if byte < 224 else -1
        if count < 0 or self.at+count > len(self.data): raise ValueError('Invalid compressed CLR integer')
        value = byte & (63 if count == 1 else 31)
        for _ in range(count): value = (value << 8) | self.data[self.at]; self.at += 1
        return value

    def element(self, depth=0):
        if depth > 16: raise ValueError('CLR signature nesting limit')
        code = self.uint()
        primitives = {1:'void', 2:'bool', 8:'int32', 9:'uint32', 10:'int64', 11:'uint64', 14:'string', 28:'object'}
        if code in primitives: return primitives[code]
        if code in (17,18): return self.metadata.coded_type(self.uint())
        if code in (15,16,29): return ('ptr' if code == 15 else 'ref' if code == 16 else 'array', self.element(depth+1))
        raise ValueError('Unsupported input signature')

    def method(self):
        convention = self.uint()
        # Contract requires ordinary non-generic, non-varargs methods.
        if convention & ~0x20: raise ValueError('Unsupported method convention')
        count = self.uint()
        if count > 8: raise ValueError('Input parameter limit')
        result = self.element(); params = [self.element() for _ in range(count)]
        if self.at != len(self.data): raise ValueError('Trailing signature data')
        return not bool(convention & 0x20), result, params


def inspect_assembly(blob, label, budget=None, embedded=True):
    if not isinstance(blob, bytes) or len(blob) > FILE_LIMIT: raise ValueError('Assembly size limit')
    budget = [EXPANDED_LIMIT] if budget is None else budget
    budget[0] -= len(blob)
    if budget[0] < 0: raise ValueError('Embedded assembly total limit')
    with dnfile.dnPE(data=blob, clr_lazy_load=True) as image:
        if not image.net or not image.net.mdtables: raise ValueError('Not a CLR assembly')
        metadata = Metadata(image)
        module = metadata.module(); contracts = []
        try:
            if metadata.input_contract(): contracts.append(label)
        except (ValueError, IndexError, KeyError, AttributeError, TypeError):
            pass  # An unfamiliar ABI can still be a valid ordinary Melon mod.
        if embedded:
            resources = image.net.resources
            if len(resources) > 128: raise ValueError('Resource count limit')
            for resource in resources:
                name, data = str(resource.name), resource.data
                if not isinstance(data, bytes) or not name.lower().endswith(('.dll','.dll.compressed')): continue
                if name.lower().endswith('.compressed'):
                    inflater = zlib.decompressobj(-15)
                    data = inflater.decompress(data, min(FILE_LIMIT, max(0,budget[0]))+1)
                    if len(data) > FILE_LIMIT or not inflater.eof or inflater.unconsumed_tail: raise ValueError('Invalid or oversized packed assembly')
                _, nested = inspect_assembly(data, label+' → '+name, budget, False)
                contracts.extend(nested)
        return module, contracts


def inspect_mods(package):
    package = Path(package); modules = []; issues = []; providers = []
    folder = package/'Mods'
    if not folder.exists(): return dict(modules=[], inputProviders=[], issues=[])
    if folder.is_symlink(): return dict(modules=[], inputProviders=[], issues=['Mods 目录是文件链接，未检查模组。'])
    paths = sorted((p for p in folder.iterdir() if p.suffix.lower() == '.dll'), key=lambda p:p.name.casefold())
    if len(paths) > MOD_LIMIT: return dict(modules=[], inputProviders=[], issues=['模组数量超出静态检查上限。'])
    budget = [EXPANDED_LIMIT]
    for path in paths:
        if path.stem in OWNED: continue
        label = 'Mods/'+path.name
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > FILE_LIMIT: raise ValueError('Invalid mod path or size')
            module, contracts = inspect_assembly(path.read_bytes(), label, budget)
            if module['assembly'] in OWNED: continue
            module.update(file=label, inputAPI=bool(contracts))
            modules.append(module); providers.extend(contracts)
        except (OSError, ValueError, IndexError, KeyError, AttributeError, TypeError, RecursionError, pefile.PEFormatError, dnfile.errors.dnFormatError, zlib.error):
            issues.append(label+' 无法完成静态接口检查；已保留原件。')
    if len(providers) > 1: issues.append('存在多个原生输入 API 提供器，未自动选择。')
    return dict(modules=modules, inputProviders=providers, issues=issues)
