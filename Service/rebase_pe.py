"""Experimental pointer adjustment for one fingerprinted native DLL.

Not a general PE relocator: callers must restrict use to explicitly verified
input bytes. A successful LoadLibrary does not establish full API correctness.
"""
from pathlib import Path
import struct

MACHINE_X64 = 0x8664
HIGH_ENTROPY_VA = 0x0020
DYNAMIC_BASE = 0x0040
SAFE_BASE = 0x180000000  # SDEZ170's amdaemon_api.dll loads here under Wine.

SECTION_FLAGS = {'executable': 0x20000000, 'writeable': 0x80000000, 'readable': 0x40000000}


def _sections(blob, opt, nsec, size_opt):
    table = opt + size_opt
    sections = []
    for index in range(nsec):
        o = table + index * 40
        name = blob[o:o+8].split(b'\0', 1)[0].decode('ascii', errors='replace')
        vsize, va, rsize, roff = struct.unpack_from('<IIII', blob, o + 8)
        flags = struct.unpack_from('<I', blob, o + 36)[0]
        sections.append(dict(name=name, va=va, vsize=vsize, rsize=rsize, roff=roff, flags=flags))
    return sections


def pe_info(blob):
    if len(blob) < 0x40 or blob[:2] != b'MZ':
        raise ValueError('不是有效的 PE 文件。')
    e_lfanew = struct.unpack_from('<I', blob, 0x3c)[0]
    if e_lfanew < 0x40 or e_lfanew > len(blob)-24:
        raise ValueError('PE 文件头超出文件范围。')
    if blob[e_lfanew:e_lfanew+4] != b'PE\0\0':
        raise ValueError('不是有效的 PE 文件。')
    coff = e_lfanew + 4
    machine, nsec, _, _, _, size_opt, _ = struct.unpack_from('<HHIIIHH', blob, coff)
    opt = coff + 20
    if size_opt < 112 or opt+size_opt > len(blob) or not 1 <= nsec <= 96 or opt+size_opt+nsec*40 > len(blob):
        raise ValueError('PE 可选头或节表范围无效。')
    if struct.unpack_from('<H', blob, opt)[0] != 0x20b:
        raise ValueError('仅支持 x64 PE 镜像。')
    image_base = struct.unpack_from('<Q', blob, opt + 24)[0]
    size_of_image = struct.unpack_from('<I', blob, opt + 56)[0]
    dllchar = struct.unpack_from('<H', blob, opt + 70)[0]
    sections=_sections(blob,opt,nsec,size_opt)
    if not size_of_image or any(s['roff'] > len(blob) or s['rsize'] > len(blob)-s['roff']
            or s['va']+s['vsize'] > size_of_image for s in sections):
        raise ValueError('PE 节数据范围无效。')
    return dict(machine=machine, nsec=nsec, opt=opt, image_base=image_base,
                size_of_image=size_of_image, dllchar=dllchar,
                sections=sections)


def needs_rebase(blob):
    """Return candidate PE flags, not a compatibility verdict."""
    info = pe_info(blob)
    return (info['machine'] == MACHINE_X64
            and info['dllchar'] & HIGH_ENTROPY_VA
            and not info['dllchar'] & DYNAMIC_BASE
            and info['image_base'] >= 0x7ffe0000)


def rebase(blob, new_base=SAFE_BASE):
    """Return the rebased image, or None when no rebase is needed. Pure
    function; the caller writes the result to the owned copy."""
    info = pe_info(blob)
    if not needs_rebase(blob):
        return None
    old_base = info['image_base']
    if new_base == old_base:
        return None
    data = bytearray(blob)
    delta = new_base - old_base
    limit = old_base + info['size_of_image']
    changed = 0
    for section in info['sections']:
        if section['name'] in {'.pdata', '.reloc', '.rsrc'} or not section['rsize']:
            continue
        size = min(section['vsize'], section['rsize'])
        aligned = (section['roff'] + 7) & ~7
        size = max(0, size - (aligned-section['roff']))
        base_offset = aligned
        # Preserve file offsets: scan 8-aligned positions across the raw span.
        count = size // 8
        for i in range(count):
            o = base_offset + i * 8
            (word,) = struct.unpack_from('<Q', data, o)
            if old_base <= word < limit:
                struct.pack_into('<Q', data, o, word + delta)
                changed += 1
    struct.pack_into('<Q', data, info['opt'] + 24, new_base)
    struct.pack_into('<H', data, info['opt'] + 70, info['dllchar'] & ~HIGH_ENTROPY_VA)
    struct.pack_into('<I', data, info['opt'] + 64, 0)  # CheckSum
    if changed == 0:
        raise ValueError('未找到任何可重定位的绝对引用，拒绝生成无效副本。')
    return bytes(data), changed


def rebase_file(path):
    path = Path(path)
    original = path.read_bytes()
    result = rebase(original)
    if result is None:
        return None
    return result
