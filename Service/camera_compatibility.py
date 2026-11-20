"""Disable only the known crashing Sinmai-Assist camera override for a launch."""
import re
from pathlib import Path
import dnfile
import pefile
from game_identity import literal
from storage import decode_text

CONFIG='Sinmai-Assist/config.yml'


def affected_mod(path):
    if path.is_symlink() or not path.is_file() or not 0<path.stat().st_size<=32*1024*1024:return False
    try:
        with dnfile.dnPE(str(path),clr_lazy_load=True) as image:
            tables=image.net.mdtables
            rows={(str(t.TypeNamespace),str(t.TypeName)):t for t in tables.TypeDef}
            build=rows.get(('SinmaiAssist','BuildInfo'))
            camera=rows.get(('SinmaiAssist.Common','CustomCameraId'))
            if not build or not camera:return False
            commit=literal(tables,build,'CommitHash',14)
            return bool(commit and commit.decode('utf-16-le').lower() in ('787a437','787a4376b3b6642c4ce6622aad5ba3db28ab31de'))
    except (AttributeError,IndexError,TypeError,ValueError,OSError,pefile.PEFormatError):return False


def _block(text, key, indent=None):
    """Find one ordinary block mapping from the mod's own YAML serializer."""
    pattern=r'(?m)^( *)(?! )'+re.escape(key)+r':[ \t]*(?:#[^\r\n]*)?\r?$'
    found=[m for m in re.finditer(pattern,text) if indent is None or len(m[1])==indent]
    if len(found)!=1:return None
    start=found[0].end();prefix=len(found[0][1]);end=len(text)
    for row in re.finditer(r'(?m)^( *)([^ \t\r\n#][^\r\n]*)',text[start:]):
        if len(row[1])<=prefix:
            end=start+row.start();break
    return start,end


def disable_camera_override(data):
    text,encoding=decode_text(data)
    if re.search(r'(?m)^(?:---|\.\.\.)(?:[ \t\r]|$)',text):return None
    common=_block(text,'common',0)
    if not common:return None
    start,end=common; section=text[start:end]
    keys=[len(m[1]) for m in re.finditer(r'(?m)^( +)[A-Za-z_][\w-]*:',section)]
    if not keys:return None
    camera=_block(section,'customCameraId',min(keys))
    if not camera:return None
    a,b=camera; target=section[a:b]
    keys=[len(m[1]) for m in re.finditer(r'(?m)^( +)[A-Za-z_][\w-]*:',target)]
    if not keys:return None
    pattern=r'(?mi)^ {'+str(min(keys))+r'}enable:[ \t]*(true|false)(?=[ \t]*(?:#[^\r\n]*)?\r?$)'
    values=list(re.finditer(pattern,target))
    if len(values)!=1 or values[0][1].lower()!='true':return None
    lo,hi=values[0].span(1);loc=start+a
    return (text[:loc+lo]+'false'+text[loc+hi:]).encode(encoding)


def launch_override(package):
    package=Path(package).resolve()
    config=package/CONFIG
    if config.resolve()!=config or not config.is_file() or not 0<config.stat().st_size<=1024*1024:return None
    mod=package/'Mods/Sinmai-Assist.dll'
    if mod.resolve()!=mod or not affected_mod(mod):return None
    return disable_camera_override(config.read_bytes())
