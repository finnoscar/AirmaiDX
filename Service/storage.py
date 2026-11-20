"""Referenced HDD libraries and transactional configuration storage."""
from pathlib import Path
import codecs, configparser, ctypes, datetime, fcntl, hashlib, json, os, re, shutil, stat, uuid
from contextlib import contextmanager
from functools import wraps

DEFAULT_SETTINGS=dict(displayUUID='',width=1080,height=1920,fillDisplay=True,metalHUD=True,
                      hdxEnabled=True,adxEnabled=True,mouseEnabled=True,phoneReaderEnabled=False,networkEnabled=True,transportCompatibility=True,networkInterface='')

def serialized(action):
    @wraps(action)
    def run(store,*args,**kwargs):
        with store.operation():return action(store,*args,**kwargs)
    return run

def now():
    return datetime.datetime.now().astimezone().isoformat()

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()

def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name('.'+path.name+'.'+uuid.uuid4().hex)
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    os.chmod(temp, 0o600)
    temp.replace(path)

class Store:
    def __init__(self, root=None):
        self.root = Path(root or os.environ.get('AIRMAIDX_DATA_ROOT') or Path.home()/'Library/Application Support/AirmaiDX').resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self.db = self.root/'library.json'
        self._operation_depth = 0

    @contextmanager
    def operation(self):
        """Serialize mutations across worker processes and duplicate app windows."""
        if self._operation_depth:
            yield
            return
        with (self.root/'operation.lock').open('a+') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('另一项导入、配置或启动任务仍在处理，请稍后重试。')
            self._operation_depth += 1
            try:yield
            finally:self._operation_depth -= 1

    def library(self):
        if not self.db.exists():return []
        try:
            items=json.loads(self.db.read_text())
            if not isinstance(items,list):raise ValueError()
            for game in items:
                if not isinstance(game,dict) or not isinstance(game.get('settings',{}),dict):raise ValueError()
                # Add fields introduced by updates without resetting user values.
                game['settings']={key:game.get('settings',{}).get(key,value) for key,value in DEFAULT_SETTINGS.items()}
            return items
        except (ValueError,TypeError) as error:
            raise ValueError('游戏库记录无法读取，原文件已保留。请导出诊断记录后恢复游戏库。') from error

    def get(self, game_id):
        if not re.fullmatch('[a-f0-9]{32}', game_id):
            raise ValueError('游戏记录无效，请重新选择。')
        for game in self.library():
            if game['id'] == game_id:
                package=Path(game['packagePath'])
                if game.get('storageMode')=='direct':
                    if (not package.is_absolute() or package!=Path(game['sourcePath'])
                            or package.resolve()!=package or package.is_relative_to(self.root)
                            or self.root.is_relative_to(package)):
                        raise ValueError('HDD 路径异常，请重新选择游戏文件夹。')
                else:
                    expected = self.root/'Games'/game_id/'HDD/Package'
                    if package != expected or expected.resolve() != expected:
                        raise ValueError('游戏副本路径异常，请重新导入。')
                return game
        raise ValueError('找不到这个游戏，请重新导入。')

    def update(self, game):
        with (self.root/'library.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            items = self.library()
            items = [game if x['id'] == game['id'] else x for x in items]
            if not any(x['id'] == game['id'] for x in items):
                items.append(game)
            atomic_json(self.db, items)

    def game_root(self, game):
        return self.root/'Games'/game['id']

    @serialized
    def delete_game(self, game_id, trash):
        game=self.get(game_id)
        self.assert_stopped(game)
        root=self.game_root(game)
        if root.is_symlink() or root.resolve()!=root or not root.is_dir():
            raise ValueError('游戏资料路径异常，未删除任何文件。')
        self.restore_launch_configs(game)
        with (self.root/'library.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            items=self.library()
            destination=trash(root)
            try:atomic_json(self.db,[x for x in items if x['id']!=game_id])
            except BaseException:
                # Keep a failed library write from orphaning an imported game.
                Path(destination).rename(root)
                raise
        return True

    def require_package(self, game):
        package=Path(game['packagePath'])
        if not package.is_dir():
            raise ValueError('HDD 未连接或文件夹已移动，请接入磁盘后重试，或重新选择 HDD。')
        return package

    def checked_file(self, game, name, *, launch=False):
        allowed = {'mai2.ini', 'segatools.ini', 'AquaMai.toml', 'config_common.json', 'config_client.json', 'config_server.json'}
        if launch:allowed.add('Sinmai-Assist/config.yml')
        if name not in allowed:
            raise ValueError('不支持编辑这个配置文件。')
        root = self.require_package(game)
        p = root/name
        if p.is_symlink() or p.resolve()!=root.resolve()/name:
            raise ValueError('配置文件使用了链接，已停止修改。')
        return p

    def read_config(self, game_id, name):
        game = self.get(game_id)
        p = self.checked_file(game, name)
        if not p.is_file():
            raise ValueError('游戏包中没有这个配置文件。')
        data = p.read_bytes()
        text, encoding = decode_text(data)
        return dict(name=name, text=text, encoding=encoding, sha256=hashlib.sha256(data).hexdigest())

    @serialized
    def save_config(self, game_id, name, text, expected_hash, encoding):
        game = self.get(game_id)
        self.assert_stopped(game)
        p = self.checked_file(game, name)
        if digest(p) != expected_hash:
            raise ValueError('文件已被其他程序更新。请重新载入后再保存，避免覆盖新设置。')
        if '\0' in text:
            raise ValueError('配置内容包含无效字符。')
        if name.endswith('.json'):
            json.loads(text)
        if name.endswith('.toml'):
            import tomllib
            tomllib.loads(text)
        data = text.encode(encoding)
        self.replace_with_backup(game, p, data)
        return self.read_config(game_id, name)

    def replace_with_backup(self, game, path, data):
        root = Path(game['packagePath'])
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError('只能修改已添加 HDD 内的文件。')
        backup = self.game_root(game)/'Backups'
        backup.mkdir(exist_ok=True)
        token = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-'+uuid.uuid4().hex[:8]
        name = token+'.backup'
        if path.exists():
            shutil.copy2(path, backup/name)
            atomic_json(backup/(token+'.json'), dict(id=token, file=str(path.relative_to(root)), created=now(), sha256=digest(path)))
        temp = path.with_name('.'+path.name+'.airmai-'+uuid.uuid4().hex)
        temp.write_bytes(data)
        os.chmod(temp, 0o600)
        temp.replace(path)

    def backups(self, game_id):
        g = self.get(game_id)
        root = self.game_root(g)/'Backups'
        result = []
        for p in sorted(root.glob('*.json'), reverse=True):
            d = json.loads(p.read_text())
            result.append({k:d[k] for k in ['id','file','created']})
        return result

    @serialized
    def replace_batch(self, game, updates, title, *, allow_new=False, expected=None):
        """One restore point for interdependent files; roll back on partial failure."""
        self.assert_stopped(game)
        root=Path(game['packagePath']);backup=self.game_root(game)/'Backups';backup.mkdir(exist_ok=True)
        originals=[]
        for path,data in updates:
            if (path.resolve() != path or not path.is_relative_to(root) or not path.parent.is_dir()
                    or (path.exists() and not path.is_file()) or (not allow_new and not path.is_file())):
                raise ValueError('只能替换已添加 HDD 内的文件。')
            before = path.read_bytes() if path.is_file() else None
            if expected is not None and path in expected:
                actual = hashlib.sha256(before).hexdigest() if before is not None else None
                if actual != expected[path]:
                    raise ValueError('曲目或谱面在编辑期间已变化，请重新打开后再保存。')
            originals.append((path,before,data))
        token=datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-'+uuid.uuid4().hex[:8]
        records=[]
        for index,(path,before,data) in enumerate(originals):
            entry = dict(file=str(path.relative_to(root)))
            if before is None:
                entry.update(blob=None, applied=hashlib.sha256(data).hexdigest())
            else:
                blob = token+'-'+str(index)+'.blob'
                (backup/blob).write_bytes(before)
                os.chmod(backup/blob,0o600)
                entry.update(blob=blob, sha256=hashlib.sha256(before).hexdigest())
                if data is None:entry['removed']=True
            records.append(entry)
        atomic_json(backup/(token+'.json'),dict(id=token,file=title,created=now(),files=records))
        def write(path,data):
            if data is None:
                path.unlink(missing_ok=True)
                return
            temp=path.with_name('.'+path.name+'.airmai-'+uuid.uuid4().hex)
            try:
                temp.write_bytes(data);os.chmod(temp,0o600);temp.replace(path)
            finally:
                if temp.exists():temp.unlink()
        try:
            applied = []
            for path,before,data in originals:
                write(path,data)
                applied.append((path,before))
        except BaseException:
            for path,before in reversed(applied):write(path,before)
            raise

    @serialized
    def restore(self, game_id, backup_id):
        g = self.get(game_id)
        self.assert_stopped(g)
        if not re.fullmatch(r'[\d-]+-[a-f0-9]{8}', backup_id):
            raise ValueError('恢复点无效。')
        base = self.game_root(g)/'Backups'/backup_id
        record = json.loads(base.with_suffix('.json').read_text())
        if 'files' in record:
            updates=[];expected={}
            root=Path(g['packagePath'])
            for entry in record['files']:
                path=root/entry['file']
                if path.resolve()!=path or not path.is_relative_to(root):
                    raise ValueError('恢复点路径异常。')
                if entry['blob'] is None:
                    if not path.exists():continue
                    expected[path]=entry['applied']
                    updates.append((path,None))
                    continue
                blob=base.parent/entry['blob']
                if blob.parent!=base.parent:raise ValueError('恢复点路径异常。')
                data=blob.read_bytes()
                if hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('恢复点校验失败。')
                if entry.get('removed'):
                    if path.exists():
                        if not path.is_file() or digest(path)!=entry['sha256']:
                            raise ValueError(path.name+' 已有新文件，未覆盖。')
                        continue
                    expected[path]=None
                updates.append((path,data))
            if updates:self.replace_batch(g,updates,'恢复前的谱面与曲目资料',allow_new=True,expected=expected)
            return True
        p = Path(g['packagePath'])/record['file']
        data = base.with_suffix('.backup').read_bytes()
        if hashlib.sha256(data).hexdigest() != record['sha256']:
            raise ValueError('恢复点校验失败。')
        self.replace_with_backup(g, p, data)
        return True

    def assert_stopped(self, game):
        from runtime import session_status
        if session_status(self, game)['running']:
            raise ValueError('请先停止游戏，再保存或恢复配置。')
        # PID inspection is advisory. A live manager or its cleanup still owns
        # this lease even when ps/status is temporarily unavailable.
        if not getattr(self,'_active_lease_depth',0):
            with (self.root/'active-game.lock').open('a+') as lock:
                try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:raise ValueError('游戏仍在运行或退出清理，请稍后再保存或恢复配置。')

    def apply_launch_configs(self,game,session,updates):
        """Journal temporary launch settings separately from user edits."""
        root=self.game_root(game);journal=root/'launch-configs.json'
        if journal.exists():raise RuntimeError('上次运行的连接设置还未恢复，请先修复运行环境。')
        originals=session/'OriginalConfig';originals.mkdir()
        records=[]
        for name,data in updates:
            path=self.checked_file(game,name,launch=True);before=path.read_bytes()
            copy=originals/name;copy.parent.mkdir(parents=True,exist_ok=True)
            copy.write_bytes(before);os.chmod(copy,0o600)
            records.append(dict(name=name,original=str(copy.relative_to(root)),before=hashlib.sha256(before).hexdigest(),applied=hashlib.sha256(data).hexdigest()))
        atomic_json(journal,dict(session=str(session.relative_to(root)),files=records))
        try:
            for name,data in updates:self._atomic_file(self.checked_file(game,name,launch=True),data)
        except BaseException:
            self.restore_launch_configs(game)
            raise

    def restore_launch_configs(self,game):
        root=self.game_root(game);journal=root/'launch-configs.json'
        if not journal.exists():return
        record=json.loads(journal.read_text());restored=[];external=[]
        for entry in record['files']:
            path=self.checked_file(game,entry['name'],launch=True);source=root/entry['original']
            if not source.resolve().is_relative_to(root/'Sessions') or source.is_symlink():
                raise ValueError('运行设置的恢复记录路径异常。')
            before=source.read_bytes()
            if hashlib.sha256(before).hexdigest()!=entry['before']:raise ValueError('运行设置的恢复记录未通过校验。')
            current=digest(path)
            if current==entry['applied']:
                self._atomic_file(path,before);restored.append(entry['name'])
            elif current!=entry['before']:external.append(entry['name'])
        destination=root/record['session']
        if not destination.resolve().is_relative_to(root/'Sessions'):raise ValueError('运行记录路径异常。')
        atomic_json(destination/'configuration-restored.json',dict(restored=restored,externalChangesPreserved=external,time=now()))
        journal.unlink()

    @staticmethod
    def _atomic_file(path,data):
        temporary=path.with_name('.'+path.name+'.airmai-'+uuid.uuid4().hex)
        try:
            temporary.write_bytes(data);os.chmod(temporary,0o600);temporary.replace(path)
        finally:
            if temporary.exists():temporary.unlink()

    @serialized
    def import_game(self, source, emit=lambda *_: None):
        source = Path(source).expanduser().resolve()
        if not source.is_dir():
            raise ValueError('请选择解压后的游戏文件夹。')
        if source.is_relative_to(self.root) or self.root.is_relative_to(source):
            raise ValueError('请选择应用资料目录之外的原始游戏包。')
        from compatibility import locate_package,inspect_package
        package=locate_package(source)
        for name in ['Sinmai.exe', 'amdaemon.exe', 'inject.exe', 'mai2hook.dll', 'mai2.ini', 'segatools.ini']:
            if not (package/name).is_file():
                raise ValueError('游戏包缺少 '+name+'，请确认选择了完整本体。')
        # Validate PE without executing it.
        with (package/'Sinmai.exe').open('rb') as f:
            if f.read(2) != b'MZ':
                raise ValueError('Sinmai.exe 不是可识别的 Windows 程序。')
            f.seek(0x3c); offset = int.from_bytes(f.read(4),'little')
            f.seek(offset)
            if f.read(6) != b'PE\0\0\x64\x86':
                raise ValueError('目前已验证的运行环境仅支持 x64 Sinmai 本体。')
        # Inspect the selected directory in place. Runtime files and backups
        # remain under the stable game ID, including for removable SSDs.
        if any(p.is_symlink() for p in package.rglob('*')):
            raise ValueError('游戏包包含文件链接，请先整理完整的 HDD 文件夹。')
        previous=next((g for g in self.library() if g.get('sourcePath')==str(package)),None)
        if previous:
            self.assert_stopped(previous)
            self.restore_launch_configs(previous)
            game=dict(previous)
            game.update(packagePath=str(package),sourcePath=str(package),storageMode='direct',ready=False)
        else:
            game_id=uuid.uuid4().hex
            game=dict(id=game_id,name=source.name if source.name!='Package' else source.parent.name,
                      packagePath=str(package),sourcePath=str(package),storageMode='direct',
                      importedAt=now(),unityVersion='待识别',ready=False,settings=dict(DEFAULT_SETTINGS))
        version_file=package/'Sinmai_Data/globalgamemanagers'
        if version_file.is_file():
            with version_file.open('rb') as stream:blob=stream.read(4096)
            found=re.search(rb'20(?:1[7-9]|2[0-9])\.\d+\.\d+[abfp]\d+',blob)
            if found:game['unityVersion']=found.group().decode()
        game['hasAquaMai']=(package/'Mods/AquaMai.dll').is_file() or (package/'Mods/MuMod.dll').is_file()
        report=inspect_package(package)
        game.update({k:v for k,v in report.items() if k not in ['files','canPrepare','modCheck']})
        root=self.game_root(game)
        created=not root.exists()
        root.mkdir(parents=True,exist_ok=True)
        try:self.update(game)
        except BaseException:
            if created:root.rmdir()
            raise
        emit('progress',dict(message='已添加 HDD，直接使用所选目录',fraction=1))
        return game


def decode_text(data):
    candidates = ['utf-8-sig'] if data.startswith(codecs.BOM_UTF8) else ['utf-8']
    if data.startswith((codecs.BOM_UTF16_LE,codecs.BOM_UTF16_BE)):
        candidates=['utf-16']
    for encoding in candidates+['gb18030','shift_jis','cp1252']:
        try:return data.decode(encoding),encoding
        except UnicodeError:pass
    raise ValueError('暂时无法识别配置文件的文字编码。')

def windows_ini_bytes(text):
    """Win32 profile APIs recognize UTF-16 BOMs independently of the ANSI CP.

    UTF-8 comments in an otherwise ASCII INI can make Wine's CP936 decoder
    lose entire sections. Keep the text, but give native INI readers an
    unambiguous encoding. Do not apply this to TOML, JSON or game assets.
    """
    return codecs.BOM_UTF16_LE + text.encode('utf-16-le')

def clear_private_copy_locks(path):
    """Clear inherited user locks only on a file created/owned by this import."""
    info=Path(path).lstat()
    if stat.S_ISLNK(info.st_mode):
        return False
    locks=getattr(stat,'UF_IMMUTABLE',0) | getattr(stat,'UF_APPEND',0)
    flags=getattr(info,'st_flags',0)
    if flags & locks:
        os.chflags(path,flags & ~locks,follow_symlinks=False)
        return True
    return False

def remove_private_import(root):
    """Roll back the UUID-owned staging tree without following file links."""
    def retry(function,path,error):
        if function not in (os.unlink,os.rmdir) or not clear_private_copy_locks(path):
            raise error
        function(path)
    clear_private_copy_locks(root)
    shutil.rmtree(root,onexc=retry)

def clone_private(source,destination):
    lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
    lib.clonefile.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_int]
    # CLONE_NOFOLLOW | CLONE_NOOWNERCOPY; do not request source ACLs.
    if lib.clonefile(os.fsencode(source),os.fsencode(destination),0x0001 | 0x0002):
        raise OSError(ctypes.get_errno(),'clonefile',str(source))

def copy_private(source, destination):
    # clonefile copies BSD flags as well as file data. An immutable DLL must
    # remain locked in the original while its new private inode is writable.
    source=Path(source);destination=Path(destination)
    info=source.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('只能复制普通文件，不能复制链接或设备文件。')
    if os.path.lexists(destination):
        raise FileExistsError(str(destination))
    created=False
    try:
        try:
            clone_private(source,destination)
            created=True
        except (OSError,AttributeError):
            # copy2/copyfile metadata would reapply the same immutable flags.
            # Stream only data into an exclusively created destination instead.
            with source.open('rb') as incoming, destination.open('xb') as outgoing:
                created=True
                shutil.copyfileobj(incoming,outgoing,1024*1024)
            os.utime(destination,ns=(info.st_atime_ns,info.st_mtime_ns))
        if not stat.S_ISREG(destination.lstat().st_mode):
            raise ValueError('复制结果不是普通文件，已停止导入。')
        clear_private_copy_locks(destination)
        os.chmod(destination,(info.st_mode & 0o100) | 0o600)
    except BaseException:
        if created:
            try:
                clear_private_copy_locks(destination)
                destination.unlink()
            except OSError:
                pass  # The enclosing import also rolls back its owned tree.
        raise

def ini_set(text, section, key, value):
    newline='\r\n' if '\r\n' in text else '\n'
    lines=text.replace('\r\n','\n').split('\n')
    start=None;end=len(lines)
    for i,line in enumerate(lines):
        m=re.match(r'\s*\[([^\]]+)\]',line)
        if m:
            if start is not None:
                end=i;break
            if m[1].lower()==section.lower():start=i+1
    if start is None:
        lines += ['', '['+section+']',key+'='+value]
    else:
        found=[i for i in range(start,end) if re.match(r'\s*'+re.escape(key)+r'\s*=',lines[i],re.I)]
        if found:
            lines[found[0]]=key+'='+value
            for duplicate in reversed(found[1:]):del lines[duplicate]
        else:lines.insert(end,key+'='+value)
    return newline.join(lines)
