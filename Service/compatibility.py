"""Read-only package inspection and format-based compatibility preparation.

Executable hashes identify previously tested builds; they are not an admission
list. Nothing here loads a Windows DLL or executes a startup script.
"""
from pathlib import Path
import configparser, hashlib, json, os, re, struct, xml.etree.ElementTree as ET
import pefile
from startup_checks import discover
from unity_compatibility import legacy_mod_check
from game_identity import identity

REQUIRED=['Sinmai.exe','amdaemon.exe','inject.exe','mai2hook.dll','mai2.ini','segatools.ini',
          'config_common.json','config_server.json','config_client.json','version.dll',
          'Sinmai_Data/Plugins/amdaemon_api.dll','Sinmai_Data/Managed/AMDaemon.NET.dll',
          'Sinmai_Data/Managed/Assembly-CSharp.dll']
KEYS=['W','E','D','C','X','Z','A','Q','Return']
MOD_ASSEMBLIES={'AquaMai':'Mods/AquaMai.dll','MuMod':'Mods/MuMod.dll'}
NATIVE_REBASE_BUILDS={'Sinmai_Data/Plugins/amdaemon_api.dll':
                      '2f70f939142cb4daf11932acaf3b95f79fb7de05c061e7d1a5ee9856b9682086',
                      'Sinmai_Data/Plugins/Cake.dll':
                      'e16364ce7930214eb3e5a9286a9504ad32928257649651512bc8e9bcaca10c2a'}
NATIVE_REBASE_BASES={'Sinmai_Data/Plugins/amdaemon_api.dll':0x180000000,
                     'Sinmai_Data/Plugins/Cake.dll':0x1a0000000}
BROKEN_CAKE_REBASE='416415aaa5fd532d3fb97d65e5ce248d6c4bf665db9fd6daa70be10cfbc16520'

def detect_mod(package,files=None):
    """Recognize the AquaMai-compatible assembly a package actually ships."""
    package=Path(package)
    files=files or {name:pe_metadata(package/name) for name in MOD_ASSEMBLIES.values()}
    for kind,name in MOD_ASSEMBLIES.items():
        meta=files.get(name)
        if meta is None:meta=pe_metadata(package/name)
        if meta.get('present') and meta.get('version'):
            return dict(kind=kind,dll=name,version=meta['version'])
    from managed_mods import inspect_mods
    for module in inspect_mods(package)['modules']:
        if module['melonMod']:
            return dict(kind=module['assembly'], dll=module['file'], version=module['version'])
    return None

def text_file(path):
    from storage import decode_text
    return decode_text(path.read_bytes())[0]

def ini(path):
    parser=configparser.ConfigParser(strict=False,interpolation=None)
    if path.is_file():parser.read_string(text_file(path))
    return parser

def section(parser,name):
    return next((s for s in parser.sections() if s.lower()==name.lower()),name)

def get(parser,group,key,default=''):
    return parser.get(section(parser,group),key,fallback=default)

def pe_metadata(path):
    if not path.is_file():return dict(present=False)
    record=dict(present=True,architecture='unknown',version=None,imports=[])
    with path.open('rb') as stream:
        header=stream.read(64)
        if len(header)<64 or header[:2]!=b'MZ':return record
        offset=struct.unpack_from('<I',header,60)[0]
        if offset>path.stat().st_size-6:return record
        stream.seek(offset);signature=stream.read(6)
    if signature[:4]!=b'PE\0\0':return record
    record['architecture']={0x8664:'x64',0x14c:'x86',0xaa64:'arm64'}.get(int.from_bytes(signature[4:6],'little'),'unknown')
    try:
        with pefile.PE(str(path),fast_load=True) as image:
            image.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
            record['imports']=[entry.dll.decode(errors='replace') for entry in getattr(image,'DIRECTORY_ENTRY_IMPORT',[])]
            for group in getattr(image,'FileInfo',[]):
                for item in group:
                    for table in getattr(item,'StringTable',[]):
                        values=table.entries
                        version=values.get(b'FileVersion') or values.get(b'ProductVersion')
                        if version:record['version']=version.decode(errors='replace').strip()
    except (pefile.PEFormatError,OSError,ValueError):pass
    return record

def locate_package(source):
    source=Path(source)
    candidates=[];queue=[(source,0)];visited=0
    ignored={'Sinmai_Data','MelonLoader','MonoBleedingEdge','appdata','amfs','option','options','Mods','UserData','UploadData','Logs','.git'}
    while queue:
        folder,depth=queue.pop(0);visited+=1
        if visited>2000:raise ValueError('这个目录包含太多文件夹，请选择具体的 HDD 或 Package 文件夹。')
        if (folder/'Sinmai.exe').is_file() and (folder/'Sinmai_Data').is_dir():
            candidates.append(folder);continue
        if depth>=4:continue
        for child in sorted(folder.iterdir(),key=lambda p:p.name):
            if child.name not in ignored and not child.name.startswith('.') and child.is_dir() and not child.is_symlink():queue.append((child,depth+1))
    if not candidates:raise ValueError('没有找到 Sinmai.exe 与 Sinmai_Data。请选择已解压的游戏文件夹。')
    if len(candidates)>1:raise ValueError('找到了多份游戏，请选择其中一个 HDD 或 Package 文件夹。')
    return candidates[0]

def core_signature(package, *, ignored=()):
    result=hashlib.sha256()
    names={'Sinmai.exe','UnityPlayer.dll','amdaemon.exe','mai2hook.dll','Sinmai_Data/Plugins/amdaemon_api.dll','Sinmai_Data/Managed/AMDaemon.NET.dll','MelonLoader/net35/MelonLoader.dll','version.dll','Mods/AquaMai.dll'}
    # Replacing gameplay assemblies or a loader/plugin must invalidate reuse,
    # even when the launcher EXE and version label have not changed.
    names.update(p.name for p in package.iterdir() if p.suffix.lower() in ['.dll','.exe'])
    for folder in ['Sinmai_Data/Managed','Sinmai_Data/Plugins','MelonLoader','Mods','UserLibs','Plugins','UserData','Dependencies']:
        names.update(str(p.relative_to(package)) for p in (package/folder).rglob('*') if p.suffix.lower() in ['.dll','.exe'])
    names.difference_update('Mods/'+name+'.dll' for name in ['AirmaiBootTrace','AirmaiDisplayTrace','AirmaiDisplayBridge','AirmaiHdxNativeTouch','AirmaiHdxNativeLed','AirmaiControllerInput','AirmaiMouseInput'])
    names.difference_update(ignored)
    for name in sorted(names):
        path=package/name
        if path.is_symlink():raise ValueError('游戏组件包含文件链接，请先整理完整文件。')
        result.update(name.encode())
        if path.is_file():
            with path.open('rb') as stream:
                for block in iter(lambda:stream.read(1024*1024),b''):result.update(block)
    return result.hexdigest()

def asset_revision(package):
    """Do not reuse an import when the user has added/replaced source assets."""
    result=hashlib.sha256()
    for root in [package/'Sinmai_Data',package/'option',package/'options']:
        for folder,dirs,files in os.walk(root,followlinks=False):
            dirs.sort()
            for name in sorted(files):
                path=Path(folder)/name
                if name=='.DS_Store' or name.endswith('.log'):continue
                info=path.lstat()
                result.update(str(path.relative_to(package)).encode('utf-8',errors='surrogateescape'))
                result.update(struct.pack('<QQ',info.st_size,info.st_mtime_ns))
    return result.hexdigest()

def inspect_package(package,manifest=None):
    package=Path(package);problems=[]
    files={name:pe_metadata(package/name) for name in ['Sinmai.exe','amdaemon.exe','inject.exe','mai2hook.dll','version.dll','UnityPlayer.dll','Sinmai_Data/Plugins/amdaemon_api.dll','MelonLoader/net35/MelonLoader.dll','Mods/AquaMai.dll','Mods/MuMod.dll']}
    for name in REQUIRED:
        if not (package/name).is_file():problems.append('缺少 '+name)
    for name in ['Sinmai.exe','amdaemon.exe','inject.exe','mai2hook.dll','version.dll','Sinmai_Data/Plugins/amdaemon_api.dll']:
        if files[name]['present'] and files[name]['architecture']!='x64':problems.append(name+' 不是 x64 Windows 程序')
    for name in ['config_common.json','config_server.json','config_client.json']:
        path=package/name
        if path.is_file():
            try:
                from storage import decode_text
                if not isinstance(json.loads(decode_text(path.read_bytes())[0]),dict):raise ValueError()
            except (ValueError,UnicodeError):problems.append(name+' 不是有效的 JSON 对象')
    version='待识别';path=package/'Sinmai_Data/globalgamemanagers'
    if path.is_file():
        with path.open('rb') as stream:match=re.search(rb'20\d\d\.\d+\.\d+[abfp]\d+',stream.read(8192))
        if match:version=match.group().decode()
    game_version=None;project=None;rom=package/'Sinmai_Data/StreamingAssets/RomConfig.xml'
    if rom.is_file():
        try:
            xml=ET.fromstring(rom.read_bytes());parts=[xml.findtext('version/'+k) for k in ['major','minor','release']]
            if all(x is not None and x.isdigit() for x in parts):game_version=f'{int(parts[0])}.{int(parts[1]):02d}.{int(parts[2]):02d}'
            project=xml.findtext('projectName')
        except (ET.ParseError,ValueError):pass
    try:
        config=ini(package/'segatools.ini');game_id=get(config,'keychip','gameid').strip().upper()
    except (configparser.Error, UnicodeError):
        # Keep the library entry so the launcher can guide the user to the editor.
        game_id=None;problems.append('segatools.ini 的格式有误，请在「机台配置」中检查或从备份恢复。')
    if not re.fullmatch('[A-Z0-9]{4}',game_id):game_id=None
    runtime_id,runtime_version=identity(package)
    game_id=runtime_id or game_id
    if game_id=='SDGB':
        if runtime_id=='SDGB':game_version=runtime_version or game_version
        project='舞萌 DX'
    loader=files['MelonLoader/net35/MelonLoader.dll'].get('version');mod=detect_mod(package,files)
    legacy=version.startswith('2017.4.')
    if not version.startswith(('2017.4.','2018.4.')):
        problems.append('当前图形与游戏辅助组件尚未验证 Unity '+version)
    player_version=files['UnityPlayer.dll'].get('version')
    player_family=re.match(r'(20\d\d\.\d+)\.',player_version or '')
    resource_family=re.match(r'(20\d\d\.\d+)\.',version)
    if player_family and resource_family and player_family[1]!=resource_family[1]:
        problems.append('Unity 资源版本 '+version+' 与 UnityPlayer.dll '+player_version+' 不一致，请使用引擎与资源匹配的完整游戏包')
    mod_check=legacy_mod_check(package) if legacy else dict(blockers=[],warnings=[])
    problems.extend(mod_check['blockers'])
    if not (package/'Sinmai_Data/Managed').is_dir():problems.append('没有找到 Unity Mono Managed 目录')
    if not loader or not loader.startswith('0.6.'):
        problems.append('需要可识别的 MelonLoader 0.6 加载器')
    if not mod:problems.append('没有找到可识别的 MelonLoader 模组（如 AquaMai / MuMod）。')
    known=None
    for profile in (manifest or {}).get('compatibility_profiles',[]):
        if all((package/name).is_file() and hashlib.sha256((package/name).read_bytes()).hexdigest()==expected for name,expected in profile['fingerprints'].items()):
            known=profile['name'];break
    label=' '.join(filter(None,[game_id,game_version])) or project or package.parent.name
    mod_name=f'{mod["kind"]} {mod["version"]}' if mod else '模组待准备'
    name=f'{label} · Unity {version} · MelonLoader {loader or "待准备"} · {mod_name}'
    return dict(gameId=game_id,gameVersion=game_version,projectName=project,unityVersion=version,
                loaderVersion=loader,modVersion=mod['version'] if mod else None,modKind=mod['kind'] if mod else None,
                profileName=name,engineFamily='unity2017-mono-ml06' if legacy else 'unity2018-mono-ml06',
                compatibilityState='needsComponents' if problems else 'knownBuild' if known else 'firstRun',
                compatibilityNote='；'.join(problems) if problems else ('已识别 Unity 2017.4 运行结构，基础 API 静态检查通过；完整游戏、模组和硬件兼容性仍需首次启动实测。' if legacy else '已识别运行结构，初始化后进行首次启动验证。'),
                canPrepare=not problems,issues=problems,files=files,startupChecks=discover(package),modCheck=mod_check)

def apply_native_rebase(store,game):
    """Apply the locally startup-tested workaround to exact native builds.

    Pointer scanning is not a general PE relocation algorithm. Never apply it
    based only on PE flags or a filename to unknown imported components.
    """
    from rebase_pe import rebase
    package=Path(game['packagePath'])
    applied=[]
    for name,expected in NATIVE_REBASE_BUILDS.items():
        path=package/name
        if not path.is_file() or path.resolve()!=path:continue
        try:
            original=path.read_bytes()
            # Build 12 assigned Cake the AMDaemon base. Recover its original
            # bytes from the app's verified backup, then use a separate range.
            if name=='Sinmai_Data/Plugins/Cake.dll' and hashlib.sha256(original).hexdigest()==BROKEN_CAKE_REBASE:
                original=None
                backup=store.game_root(game)/'Backups'
                for record_path in sorted(backup.glob('*.json')):
                    record=json.loads(record_path.read_text())
                    if record.get('file')!=name or record.get('sha256')!=expected:continue
                    blob=record_path.with_suffix('.backup')
                    if blob.resolve()!=blob:continue
                    candidate=blob.read_bytes()
                    if hashlib.sha256(candidate).hexdigest()==expected:
                        original=candidate;break
                if original is None:
                    raise RuntimeError('旧版 Cake 地址适配需要恢复，但未找到有效备份。请重新导入原始游戏包。')
            if hashlib.sha256(original).hexdigest()!=expected:continue
            result=rebase(original,NATIVE_REBASE_BASES.get(name,0x180000000))
        except (OSError,ValueError):continue
        if result is None:continue
        data,count=result
        store.replace_with_backup(game,path,data)
        applied.append(dict(file=str(path.relative_to(package)),references=count))
    return applied

def existing_section_for_key(text,key,fallback):
    group=fallback
    for line in text.splitlines():
        header=re.match(r'\s*\[([^\]]+)\]',line)
        if header:group=header[1]
        elif re.match(r'\s*'+re.escape(key)+r'\s*=',line,re.I):return group
    return fallback

def prepare_configuration(store,game):
    """Normalize only application-managed fields; retain original backups."""
    from storage import decode_text,ini_set,windows_ini_bytes
    package=Path(game['packagePath']);seg=package/'segatools.ini';text,encoding=decode_text(seg.read_bytes())
    parser=ini(seg);button=section(parser,'button');values=[parser.get(button,'1p_btn'+str(i),fallback='') for i in range(1,10)]
    if not any(values) or all(x.lower()=='0x3a' for x in values):
        for i,key in enumerate(KEYS,1):
            code=13 if key=='Return' else ord(key)
            text=ini_set(text,'button','1p_btn'+str(i),f'0x{code:02X}')
    if not get(parser,'io4','coin'):text=ini_set(text,'io4','coin','0x30')
    # Map the user's existing VFS layout instead of imposing "options".
    for key,default in [('amfs','amfs'),('appdata','appdata'),('option','option' if (package/'option').is_dir() else 'options')]:
        value=get(parser,'vfs',key,default).strip() or default
        windows_absolute=bool(re.match(r'^[A-Za-z]:|^\\\\',value))
        relative=Path(value.replace('\\','/'))
        if windows_absolute or relative.is_absolute() or '..' in relative.parts:value=default
        # macOS treats backslashes as filename characters; Wine treats them as
        # separators. Normalize both the directory and the written INI value.
        value=value.replace('\\','/')
        target=package/value
        if not target.resolve().is_relative_to(package):raise ValueError('VFS 路径超出游戏副本。')
        target.mkdir(parents=True,exist_ok=True)
        text=ini_set(text,'vfs',key,value)
    data=windows_ini_bytes(text)
    if data!=seg.read_bytes():store.replace_with_backup(game,seg,data)
    mai=package/'mai2.ini';text,encoding=decode_text(mai.read_bytes())
    sound=existing_section_for_key(text,'Sound8Ch','Sound');text=ini_set(text,sound,'Sound8Ch','0')
    data=windows_ini_bytes(text)
    if data!=mai.read_bytes():store.replace_with_backup(game,mai,data)
    aqua=package/'AquaMai.toml'
    if not aqua.exists():return
    text,encoding=decode_text(aqua.read_bytes())
    # Both AquaMai 1.5.3 and 1.9.20 parse Disabled (verified statically).
    if re.search(r'(?m)^\s*\[GameSystem.Window\]',text):text=ini_set(text,'GameSystem.Window','Disabled','true')
    # Older packs use AquaMai DebugInput rather than Segatools' button map.
    if re.search(r'(?m)^\s*\[GameSystem.KeyMap\]',text):
        parser=ini(seg)
        text=ini_set(text,'GameSystem.KeyMap','DisableDebugInput','false')
        text=ini_set(text,'GameSystem.KeyMap','Disabled','false')
        controls=[('1p_btn'+str(i),'Button'+str(i)+'_1P') for i in range(1,9)]+[('1p_btn9','Select_1P')]
        for key,field in controls:
            raw=get(parser,'button',key)
            try:code=int(raw,16) if raw.lower().startswith('0x') else int(raw)
            except ValueError:continue
            name=chr(code) if 65<=code<=90 else 'Alpha'+chr(code) if 48<=code<=57 else 'F'+str(code-111) if 112<=code<=123 else {0:'None',13:'Return',32:'Space',37:'LeftArrow',38:'UpArrow',39:'RightArrow',40:'DownArrow'}.get(code)
            if name:text=ini_set(text,'GameSystem.KeyMap',field,json.dumps(name))
        for key,field in [('test','Test'),('service','Service')]:
            raw=get(parser,'io4',key)
            try:code=int(raw,16) if raw.lower().startswith('0x') else int(raw)
            except ValueError:continue
            name='F'+str(code-111) if 112<=code<=123 else 'Alpha'+chr(code) if 48<=code<=57 else None
            if name:text=ini_set(text,'GameSystem.KeyMap',field,json.dumps(name))
    if text.encode(encoding)!=aqua.read_bytes():store.replace_with_backup(game,aqua,text.encode(encoding))
