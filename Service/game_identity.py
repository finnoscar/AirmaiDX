"""Read game identity from CLR constants without loading the game assembly."""
from functools import lru_cache
from pathlib import Path
import re
import dnfile
import pefile


def literal(tables, owner, name, kind):
    fields=[ref.row for ref in owner.FieldList if str(ref.row.Name)==name and ref.row.Flags.fdLiteral]
    if len(fields)!=1:return None
    rows=[c.Value.value for c in getattr(getattr(tables,'Constant',None),'rows',[])
          if c.Parent.row is fields[0] and c.Type==kind]
    return rows[0] if len(rows)==1 else None


@lru_cache(maxsize=32)
def _identity(path,size,modified):
    try:
        with dnfile.dnPE(str(path),clr_lazy_load=True) as image:
            tables=image.net.mdtables
            types=[t for t in tables.TypeDef if str(t.TypeNamespace)=='MAI2System' and str(t.TypeName)=='ConstParameter']
            if len(types)!=1:return None,None
            raw_id=literal(tables,types[0],'GameIDStr',14)
            raw_version=literal(tables,types[0],'NowGameVersion',9)
            game_id=raw_id.decode('utf-16-le') if raw_id else None
            if not game_id or not re.fullmatch(r'[A-Z0-9]{4}',game_id):game_id=None
            number=int.from_bytes(raw_version,'little') if raw_version and len(raw_version)==4 else 0
            version=f'{number//10000}.{number//100%100:02d}.{number%100:02d}' if 10000<=number<=999999 else None
            return game_id,version
    except (AttributeError,IndexError,TypeError,ValueError,OSError,pefile.PEFormatError):
        return None,None


def identity(package):
    package=Path(package).resolve()
    path=package/'Sinmai_Data/Managed/Assembly-CSharp.dll'
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(package) or not path.is_file():return None,None
        info=path.stat()
        if not 0<info.st_size<=64*1024*1024:return None,None
        return _identity(path,info.st_size,info.st_mtime_ns)
    except OSError:return None,None
