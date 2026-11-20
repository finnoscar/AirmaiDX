"""Relocatable, instance-owned Wine lifecycle; no dependency on the lab folder."""
from pathlib import Path
import configparser, datetime, fcntl, hashlib, ipaddress, json, os, platform, re, shutil, signal, socket, struct, subprocess, sys, threading, time
from storage import atomic_json, digest, decode_text, ini_set, now, serialized
from contextlib import contextmanager
from compatibility import apply_native_rebase,detect_mod,inspect_package,prepare_configuration,existing_section_for_key
from launch_guidance import LaunchRequirement, require_package, require_startup_checks
from machine_config import require_keychip
import startup_checks
from runtime_download import require_installed
from display_geometry import output_size, match_monitor

def own_command(*args):
    if getattr(sys,'frozen',False):return [sys.executable,*args]
    return [sys.executable,str(Path(__file__).with_name('service.py')),*args]

def tail_text(path,count=12000):
    with path.open('rb') as stream:
        stream.seek(max(0,path.stat().st_size-count))
        return stream.read().decode(errors='replace')

def environment(runtime,prefix):
    env={k:v for k,v in os.environ.items() if not k.startswith(('WINE','CX_','DYLD_','PYTHON','AIRMAIDX_','SEGATOOLS_'))}
    env.update(PATH=str(runtime/'wine/bin')+':/usr/bin:/bin:/usr/sbin:/sbin',WINEPREFIX=str(prefix),
               WINESERVER=str(runtime/'wine/bin/wineserver'),WINELOADER=str(runtime/'wine/bin/wine'),
               DYLD_LIBRARY_PATH=str(runtime/'dependencies'),DYLD_FRAMEWORK_PATH=str(runtime/'dependencies'),
               WINEDEBUG='-all',WINEDLLOVERRIDES='mscoree,mshtml=;version,d3d11,dxgi,winemetal=n,b;msvcr110,msvcp110=n,b',
               OPENSSL_ia32cap='~0x200000200000000',
               SEGATOOLS_CONFIG_PATH=r'C:\AirmaiDX\Package\segatools.ini')
    for key in list(env):
        if key.lower().endswith('_proxy'):env.pop(key)
    return env

def validate_runtime(runtime):
    try:
        manifest=json.loads((runtime/'manifest.json').read_text())
        for name,expected in manifest['critical_sha256'].items():
            path=runtime/name
            if not path.resolve().is_relative_to(runtime.resolve()) or digest(path)!=expected:
                raise ValueError()
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        raise LaunchRequirement('reinstall', '运行组件校验失败，请重新安装 AirmaiDX。') from None
    return manifest

def host_preflight():
    if platform.system()=='Darwin' and platform.machine()=='arm64':
        try:
            subprocess.run(['/usr/bin/arch','-x86_64','/usr/bin/true'],
                           capture_output=True,check=True,timeout=10)
        except (OSError,subprocess.SubprocessError) as error:
            raise LaunchRequirement('rosetta', '这台 Mac 需要安装 Rosetta 2 才能运行游戏。') from error

@contextmanager
def active_lease(store):
    with (store.root/'active-game.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('另一个游戏仍在运行或退出清理，请等待停止后重试。')
        store._active_lease_depth=getattr(store,'_active_lease_depth',0)+1
        try:yield
        finally:store._active_lease_depth-=1

def stop_wine(runtime,prefix):
    if not prefix.exists():return
    env=environment(runtime,prefix)
    killed=subprocess.run([str(runtime/'wine/bin/wineserver'),'-k'],env=env,capture_output=True,timeout=10)
    # Wine returns 1 (without diagnostics) when there is no server to kill.
    # -w then independently confirms that no process retains the Prefix.
    if killed.returncode not in (0,1):killed.check_returncode()
    subprocess.run([str(runtime/'wine/bin/wineserver'),'-w'],env=env,capture_output=True,check=True,timeout=10)

def sandbox_path(path):
    # Seatbelt strings accept UTF-8, not JSON's ASCII-only \\uXXXX escapes.
    return json.dumps(str(path),ensure_ascii=False)

def map_game_directory(root,package,drive):
    directory=root/'GameDirectory'
    if directory.is_symlink():raise ValueError('运行环境的游戏映射目录异常。')
    directory.mkdir(exist_ok=True)
    targets={'Package':package}
    targets.update({name:package.parent/name for name in ['license','system_config.json','firewall.cfg']})
    for name,target in targets.items():
        link=directory/name
        if link.is_symlink():link.unlink()
        elif link.exists():raise ValueError('运行环境中存在冲突的游戏映射，请检查诊断记录。')
        if target.exists():link.symlink_to(target,target_is_directory=target.is_dir())
    mapping=drive/'AirmaiDX'
    if mapping.is_symlink():mapping.unlink()
    elif mapping.exists():raise ValueError('运行环境中存在冲突的游戏目录，请检查诊断记录。')
    mapping.symlink_to(directory,target_is_directory=True)

@serialized
def prepare(store,runtime,game_id,emit):
    require_installed(runtime)
    # The live-session lease also covers repair. A stale status/PID must never
    # allow runtime DLLs to be replaced while a game is still using its Prefix.
    with active_lease(store):
        game=store.get(game_id);root=store.game_root(game);prefix=root/'Prefix'
        require_package(store,game)
        game['ready']=False;store.update(game)
        failed=False
        try:
            host_preflight()
            stop_wine(runtime,prefix)
            prepared=_prepare(store,runtime,game_id,emit)
        except BaseException:
            failed=True
            raise
        finally:
            try:stop_wine(runtime,prefix)
            except Exception:
                if not failed:raise
        atomic_json(root/'Setup/runtime-receipt.json',dict(manifest_sha256=digest(runtime/'manifest.json'),time=now()))
        prepared['ready']=True;store.update(prepared)
        emit('progress',dict(message='运行环境已就绪',fraction=1))
        return prepared

def components(runtime):
    names=[('wine','Wine + DXMT','wine/bin/wine','已验证的 Direct3D 11 → Metal 运行环境'),
           ('mono','Mono','wine/share/wine/mono','随运行环境提供，无需手工安装 .NET'),
           ('vc2012','Visual C++ 2012','vcredist2012_x64.exe','从微软官方安装包自动初始化'),
           ('hdx','HDX 原生连接','helpers/AirmaiHdxNativeTouch.dll','触摸、灯光和实体读卡器'),
           ('display','显示与恢复','helpers/AirmaiDisplayControl-x64.exe','显示器选择、铺满与独立渲染')]
    return [dict(id=i,name=n,status='已内置' if (runtime/p).exists() else '缺失',detail=d) for i,n,p,d in names]

def _prepare(store,runtime,game_id,emit):
    manifest=validate_runtime(runtime)
    game=store.get(game_id);store.assert_stopped(game)
    store.restore_launch_configs(game)
    root=store.game_root(game);prefix=root/'Prefix';pkg=Path(game['packagePath'])
    from mod_cache import activate_signed_cache
    if activate_signed_cache(store,game,runtime/'helpers/signed-cache-verifier'):
        emit('progress',dict(message='已验证并启用包内 AquaMai 缓存',fraction=.1))
    report=inspect_package(pkg,manifest)
    game.update({k:v for k,v in report.items() if k not in ['files','canPrepare','modCheck']});store.update(game)
    atomic_json(root/'compatibility.json',report)
    if not report['canPrepare']:
        raise LaunchRequirement('packageComponents', report['compatibilityNote'])
    prefix.mkdir(exist_ok=True);env=environment(runtime,prefix)
    logs=root/'Setup';logs.mkdir(exist_ok=True)
    # Segatools requires these paths even when the imported directories are empty.
    for name in ['options','amfs','appdata']:
        (pkg/name).mkdir(exist_ok=True)
    def run(args,label,timeout=120):
        with (logs/(label+'.log')).open('wb') as out:
            result=subprocess.run([str(runtime/'wine/bin/wine'),*map(str,args)],cwd=pkg,env=env,stdout=out,stderr=out,timeout=timeout)
        if result.returncode not in (0,3010,1638):
            raise RuntimeError('运行环境的'+label+'没有完成，请在诊断页重试。')
    emit('progress',dict(message='正在创建独立运行环境',fraction=.15))
    if not (prefix/'system.reg').exists():
        run(['wineboot','-u'],'初始化',180)
    emit('progress',dict(message='正在配置图形与播放器兼容性',fraction=.4))
    run(['reg','add',r'HKCU\Software\Wine\Mac Driver','/v','RetinaMode','/t','REG_SZ','/d','y','/f'],'显示倍率')
    run(['reg','add',r'HKCU\Software\Wine','/v','Version','/t','REG_SZ','/d','win10','/f'],'系统版本')
    drive=prefix/'drive_c'
    map_game_directory(root,pkg,drive)
    for p in (runtime/'helpers').iterdir():
        if p.is_file() and p.suffix.lower() in ['.exe','.dll']:
            shutil.copy2(p,drive/p.name)
    native=runtime/'graphics'
    for p in native.iterdir():
        if p.is_file():shutil.copy2(p,drive/'windows/system32'/p.name)
    emit('progress',dict(message='正在自动准备 Visual C++ 运行库',fraction=.6))
    vc_stamp=logs/'vc2012-complete.json'
    try:vc_current=json.loads(vc_stamp.read_text()).get('installer_sha256')==digest(runtime/'vcredist2012_x64.exe')
    except (OSError,ValueError):vc_current=False
    vc_current=vc_current and all((drive/'windows/system32'/name).is_file() for name in ['msvcr110.dll','msvcp110.dll'])
    if not vc_current:
        run([runtime/'vcredist2012_x64.exe','/install','/quiet','/norestart'],'Visual C++',180)
        atomic_json(logs/'vc2012-complete.json',dict(installer_sha256=digest(runtime/'vcredist2012_x64.exe'),time=now()))
    # Only owned plugins are installed. Game/MelonLoader/AquaMai remain user supplied.
    mods=pkg/'Mods'
    if not detect_mod(pkg) or not (pkg/'MelonLoader/net35/MelonLoader.dll').is_file():
        raise ValueError('游戏包缺少 MelonLoader 或可识别的 MelonLoader 模组，请在诊断页查看缺失的组件。')
    for name in ['AirmaiBootTrace.dll','AirmaiDisplayTrace.dll','AirmaiDisplayBridge.dll']:
        shutil.copy2(runtime/'helpers'/name,mods/name)
    preset=json.loads((runtime/'sdez170-preset.json').read_text())
    config=pkg/'AquaMai.toml'
    if report['compatibilityState']=='knownBuild' and config.exists() and not (logs/'preset-complete.json').exists():
        text,encoding=decode_text(config.read_bytes())
        # A verified base profile avoids startup-incompatible optional features.
        # Keep user values; only compatibility section states are overlaid.
        for section,disabled in preset['section_disabled'].items():
            if re.search(r'(?m)^\['+re.escape(section)+r'\]',text):
                text=ini_set(text,section,'Disabled','true' if disabled else 'false')
        store.replace_with_backup(game,config,text.encode(encoding))
        atomic_json(logs/'preset-complete.json',dict(version=1,time=now()))
    prepare_configuration(store,game)
    rebased=apply_native_rebase(store,game)
    if rebased:
        emit('progress',dict(message='正在适配 Wine 无法按原始地址加载的原生组件',fraction=.8))
    emit('progress',dict(message='正在验证依赖与进程通信',fraction=.85))
    run([drive/'AirmaiProbe.exe'],'依赖检查',60)
    probe=(logs/'依赖检查.log').read_text(errors='replace')
    for label in ['load_msvcr110','load_msvcp110','parent_mapping_reply']:
        if not re.search(r'"test":"'+label+r'","value":1,',probe):
            if label.startswith('load_'):vc_stamp.unlink(missing_ok=True)
            raise RuntimeError('依赖检查未通过，请在诊断页查看运行环境记录。')
    version_file=pkg/'Sinmai_Data/globalgamemanagers'
    if version_file.exists():
        match=re.search(rb'20(?:1[7-9]|2[0-9])\.\d+\.\d+[abfp]\d+',version_file.read_bytes()[:4096])
        if match:game['unityVersion']=match.group().decode()
    return game

def session_status(store,game):
    path=store.game_root(game)/'session.json'
    result=dict(running=False,phase='ready' if game['ready'] else 'notPrepared',message='准备就绪' if game['ready'] else '等待准备运行环境')
    if not path.exists():return result
    try:record=json.loads(path.read_text())
    except (OSError,ValueError):return dict(result,phase='error',message='会话记录无法读取，请修复运行环境。')
    pid=record.get('manager_pid')
    alive=False
    if pid:
        try:
            os.kill(pid,0)
            command=subprocess.check_output(['/bin/ps','-ww','-p',str(pid),'-o','command='],text=True,timeout=3)
            alive='--session' in command and game['id'] in command
        except (OSError,subprocess.SubprocessError):pass
    result.update(running=alive,phase=record.get('phase','starting') if alive else record.get('phase','stopped'),message=record.get('message','游戏已停止'),pid=pid,sessionPath=record.get('session'))
    result['inputMode']=record.get('input_mode')
    result['controllerMessage']=record.get('controller_message')
    if not alive:
        if result['phase'] in ['starting','running','checking','title']:
            result.update(phase='error',message='上次运行意外中断；下次启动会清理遗留进程并恢复配置。')
        return result
    session=Path(record['session']);pkg=Path(game['packagePath'])
    trace=pkg/'AirmaiDisplayTrace.log'
    if trace.exists():
        line=tail_text(trace,5000)
        match=list(re.finditer(r'camera\[Main Camera\]=(\d+)x(\d+)',line))
        if match:result.update(renderWidth=int(match[-1][1]),renderHeight=int(match[-1][2]))
    for role,key,flag in [('touch','touch','healthy'),('led','led','native_port_open'),('reader','reader','ready')]:
        p=session/role/'status.json'
        if p.exists():
            try:
                d=json.loads(p.read_text());result[key]=bool(d.get(flag)) and not d.get('stopped') and time.time()-p.stat().st_mtime<5
            except ValueError:pass
    controller=session/'controller/status.json'
    if controller.exists():
        try:
            d=json.loads(controller.read_text())
            live=not d.get('stopped') and time.time()-controller.stat().st_mtime<5
            result['controllerInput']=live and bool(d.get('inputReceived')) and bool(d.get('connectedToGame'))
            if live and d.get('touchPlayers'):result['touch']=bool(d.get('inputReceived'))
        except (OSError,ValueError):pass
    # The consumer knows whether its provider actually registered and received
    # fresh input. Host enumeration alone must not claim mouse suspension.
    mode=mouse_mode(store.game_root(game)/'Prefix/drive_c/AirmaiMouse-state.txt')
    if mode:result['inputMode']=mode
    log=session/'game-stderr.log'
    if log.exists():
        try:
            with log.open('rb') as f:
                f.seek(max(0,log.stat().st_size-24000));text=f.read().decode(errors='replace')
            matches=re.findall(r'metal-HUD: ([\d.,-]+)',text)
            if matches:
                a=list(map(float,matches[-1].split(',')))
                iv=a[3::2];gpu=a[4::2]
                if iv and sum(iv)>0:result.update(fps=len(iv)*1000/sum(iv),gpuMS=sum(gpu)/len(gpu))
        except (ValueError,OSError,ZeroDivisionError):pass
    boot=pkg/'AirmaiBootTrace.log'
    if boot.exists():
        tail=tail_text(boot)
        networks=re.findall(r'Network available=(True|False) LAN=(True|False) location=(True|False) WAN=(True|False) AuthAvailable=(True|False) AuthGood=(True|False)',tail)
        if networks:result['networkOnline']=networks[-1][3]=='True' and networks[-1][5]=='True'
        stages=re.findall(r'after frame=\d+ .*?process=([^\r\n]+)',tail)
        if stages:
            if 'PowerOnProcess' in stages[-1]:result.update(phase='checking',message='游戏自检中')
            elif 'AdvertiseProcess' in stages[-1]:result.update(phase='title',message='游戏已进入标题演示')
        if 'IsException=True' in tail:
            result.update(phase='error',message='游戏报告异常，请打开诊断记录。')
    return result

def launch_guide(store,game_id):
    """Read-only check before preparing or starting; start checks again after recovery."""
    game=store.get(game_id)
    package=require_package(store,game)
    require_idle(store,game)
    host_preflight()
    require_keychip(store,game)
    require_startup_checks(game,startup_checks.discover(package))
    return True


def require_idle(store,game):
    for other in store.library():
        if other['id']!=game['id'] and session_status(store,other)['running']:
            raise LaunchRequirement('otherGame', '请先停止正在运行的游戏，再启动这个 HDD。', otherGameID=other['id'])


@serialized
def start(store,runtime,game_id,emit=lambda *_:None,ui_language='en'):
    game=store.get(game_id)
    if session_status(store,game)['running']:return dict(status='running')
    require_package(store,game)
    require_idle(store,game)
    require_installed(runtime)
    # Manager crashes can leave Wine children alive even when the saved PID is
    # gone. Stop only this game's Prefix before restoring temporary configs.
    with active_lease(store):
        stop_wine(runtime,store.game_root(game)/'Prefix')
        store.restore_launch_configs(game)
    if not game['ready']:raise ValueError('请先准备运行环境。')
    require_keychip(store,game)
    validate_runtime(runtime)
    receipt=store.game_root(game)/'Setup/runtime-receipt.json'
    try:current=json.loads(receipt.read_text()).get('manifest_sha256')
    except (OSError,ValueError):current=None
    if current!=digest(runtime/'manifest.json'):
        prepare(store,runtime,game_id,emit)
        game=store.get(game_id)
    from mod_cache import activate_signed_cache
    activate_signed_cache(store,game,runtime/'helpers/signed-cache-verifier')
    root=store.game_root(game)
    package=Path(game['packagePath'])
    report=inspect_package(package)
    atomic_json(root/'compatibility.json',report)
    if not report['canPrepare']:raise LaunchRequirement('packageComponents', report['compatibilityNote'])
    if report['startupChecks']:
        emit('progress',dict(message='正在检查包内启动状态',fraction=None))
        startup_checks.preflight(game,report['startupChecks'])
    prepare_configuration(store,game)
    apply_native_rebase(store,game)
    from unity_compatibility import previously_disabled_mods
    from controller_compatibility import prepare_input_mods
    from managed_mods import inspect_mods
    mod_report_path=root/'mod-compatibility.json'
    retained=previously_disabled_mods(package,mod_report_path)
    warnings=report['modCheck']['warnings'].copy()
    disabled_input_mods=prepare_input_mods(store,game,runtime,warnings)
    scanned=inspect_mods(package)
    scanned['issues']=list(dict.fromkeys(scanned['issues']+warnings))
    scanned['disabledUnsupportedModules']=retained # Previous builds only; keep recovery visible.
    scanned['disabledLegacyModules']=disabled_input_mods
    scanned['note']='静态接口匹配不代表模组全部功能或实机兼容性已经通过验证。'
    atomic_json(mod_report_path,scanned)
    disabled_count=len(disabled_input_mods)
    with (root/'manager.log').open('ab') as log:
        session_env=dict(os.environ,AIRMAIDX_UI_LANGUAGE=ui_language if ui_language in ['en','ja','zh-Hans'] else 'en')
        child=subprocess.Popen(own_command('--session',game_id,'--root',str(store.root),'--runtime',str(runtime)),stdout=log,stderr=log,start_new_session=True,env=session_env)
    for _ in range(50):
        if child.poll() is not None:raise RuntimeError('启动服务未能就绪，请检查诊断记录。')
        if session_status(store,game)['running']:
            return dict(status='starting',disabledMods=str(disabled_count))
        time.sleep(.1)
    child.terminate()
    try:child.wait(timeout=5)
    except subprocess.TimeoutExpired:child.kill();child.wait()
    raise RuntimeError('启动等待超时，启动服务已停止，请查看诊断页。')

def stop(store,game_id):
    game=store.get(game_id);state=session_status(store,game)
    if state['running']:
        pid=state['pid']
        if os.getpgid(pid)!=pid:raise RuntimeError('会话进程校验失败，未停止其他程序。')
        os.kill(pid,signal.SIGTERM)
        for _ in range(400):
            if not session_status(store,game)['running']:return True
            time.sleep(.1)
        raise RuntimeError('游戏仍在退出清理，请稍后重试；尚未开始新的启动。')
    return True

def delete_game(store,runtime,game_id):
    # Hold the same lease as preparation/startup until removal is committed.
    with active_lease(store):
        game=store.get(game_id)
        store.assert_stopped(game)
        stop_wine(runtime,store.game_root(game)/'Prefix')
        def trash(path):
            result=subprocess.run([str(runtime/'helpers/library-trash'),str(path)],
                                  capture_output=True,text=True,check=True,timeout=60)
            return json.loads(result.stdout)['path']
        return store.delete_game(game_id,trash)

def mouse_mode(path):
    try:
        with path.open() as stream:mode=stream.read(128).splitlines()
        if (0<=time.time()-path.stat().st_mtime<3 and len(mode)==2 and
                mode[0]=='AIRMAI_MOUSE_STATE_V1' and mode[1] in ('mouse','hdx','adx','keyboard')):
            return mode[1]
    except (OSError,ValueError):pass
    return None

def configure_mouse(runtime,pkg,drive,settings,hardware,language='en'):
    target=pkg/'Mods/AirmaiMouseInput.dll'
    config=drive/'AirmaiMouse.cfg'
    (drive/'AirmaiMouse-state.txt').unlink(missing_ok=True)
    if not settings.get('mouseEnabled',True):
        target.unlink(missing_ok=True);config.unlink(missing_ok=True)
        return False
    # Keep the module loaded with hardware too, so health failures can restore
    # mouse controls without restarting Unity or replacing a loaded assembly.
    shutil.copy2(runtime/'helpers/AirmaiMouseInput.dll',target)
    config.write_text('AIRMAI_MOUSE_V1'+chr(10)+(language if language in ['en','ja','zh-Hans'] else 'en')+chr(10))
    return True

def active_interface(preferred=''):
    try:interfaces=[name for _,name in socket.if_nameindex() if re.fullmatch(r'en\d+',name)]
    except OSError:return ''
    try:
        route=subprocess.run(['/sbin/route','-n','get','-inet','default'],capture_output=True,text=True,timeout=3)
        match=re.search(r'^\s*interface:\s*(en\d+)\s*$',route.stdout,re.M)
        default=match[1] if match else ''
    except (OSError,subprocess.SubprocessError):default=''
    # Keep the explicit choice first. In automatic mode, prefer the physical
    # default route over enumeration order, while excluding proxy tunnels.
    order=dict.fromkeys([preferred,default,*interfaces])
    for name in order:
        if name not in interfaces:continue
        try:info=subprocess.run(['/sbin/ifconfig',name],capture_output=True,text=True,timeout=3).stdout
        except (OSError,subprocess.SubprocessError):continue
        if 'status: active' in info and re.search(r'\binet (?!127\.|169\.254)',info):return name
    return ''

FAKE_IPV4=ipaddress.IPv4Network('198.18.0.0/15')

def resolve_ipv4(host,interface='',*,allow_proxy_route=False):
    host=host.strip().removesuffix('.')
    if not re.fullmatch(r'[A-Za-z0-9.-]{1,253}',host) or any(not 1<=len(s)<=63 for s in host.split('.')):
        raise ValueError('服务器地址格式不正确。')
    try:addresses=sorted({x[4][0] for x in socket.getaddrinfo(host,80,socket.AF_INET)})
    except socket.gaierror:addresses=[]
    ordinary=[x for x in addresses if ipaddress.IPv4Address(x) not in FAKE_IPV4]
    if ordinary:return ordinary[0],addresses
    if allow_proxy_route and not interface and addresses:return None,addresses
    # Resolve actual origin through a standard DNS request, not the proxy's fake-IP.
    query_id=os.urandom(2);labels=b''.join(bytes([len(s)])+s.encode('ascii') for s in host.split('.'))+b'\0'
    query=query_id+b'\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00'+labels+b'\0\x01\0\x01'
    failures=[]
    # Mobile hotspots and upstream networks can block individual public DNS
    # services. Keep each attempt bounded and retain the physical-interface pin.
    servers=['1.1.1.1','8.8.8.8','223.5.5.5','119.29.29.29',
             '1.0.0.1','8.8.4.4','223.6.6.6']
    for server in servers:
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as udp:
                if interface:udp.setsockopt(socket.IPPROTO_IP,25,socket.if_nametoindex(interface))
                udp.settimeout(2)
                udp.connect((server,53));udp.send(query);data=udp.recv(4096)
            if len(data)<12 or data[:2]!=query_id or not data[2]&0x80 or data[2]&0x02 or data[3]&15:
                raise ValueError('DNS 响应无效或不完整')
            position=12
            def skip(pos):
                while data[pos]:
                    if data[pos]&0xc0==0xc0:return pos+2
                    pos+=1+data[pos]
                return pos+1
            for _ in range(int.from_bytes(data[4:6],'big')):position=skip(position)+4
            origins=[]
            for _ in range(int.from_bytes(data[6:8],'big')):
                position=skip(position);kind,cls,ttl,size=struct.unpack('>HHIH',data[position:position+10]);position+=10
                if kind==1 and cls==1 and size==4:
                    origin=socket.inet_ntoa(data[position:position+4])
                    if ipaddress.IPv4Address(origin) not in FAKE_IPV4:origins.append(origin)
                position+=size
            if origins:return origins[0],sorted(set(addresses+origins))
            raise ValueError('服务器没有可用的真实 IPv4 地址')
        except (OSError,ValueError,IndexError,struct.error) as error:
            failures.append(server+'：'+str(error))
    if allow_proxy_route and addresses:return None,addresses
    raise RuntimeError('无法解析服务器的真实地址。'+'；'.join(failures))


def auth_routes(origin,addresses,interface,explicit):
    """Limited route candidates for a single configured authentication server."""
    ordered=list(dict.fromkeys([origin,*addresses] if origin else addresses))
    real=[ip for ip in ordered if ipaddress.IPv4Address(ip) not in FAKE_IPV4][:3]
    proxy=[ip for ip in ordered if ipaddress.IPv4Address(ip) in FAKE_IPV4][:3]
    direct=[(ip,interface) for ip in real]
    system=[(ip,'') for ip in proxy]
    if interface and not explicit:system.extend((ip,'') for ip in real)
    return list(dict.fromkeys(direct+system))


def configure_game_network(pkg,runtime,settings,session,env,child):
    messages=[]
    errors=(OSError,ValueError,RuntimeError,configparser.Error,subprocess.SubprocessError)
    try:
        cp=configparser.ConfigParser(strict=False,interpolation=None)
        cp.read_string(decode_text((pkg/'segatools.ini').read_bytes())[0])
        dns=next((cp[s] for s in cp.sections() if s.lower()=='dns'),{})
    except errors as error:
        (session/'network-setup.log').write_text(f'无法读取联网设置，使用游戏自身的联网流程。({type(error).__name__})\n')
        return
    if dns.get('enable','').strip()=='0':return
    default=dns.get('default','').strip()
    host=dns.get('startup','').strip() or default
    aime_host=dns.get('aimedb','').strip() or default
    shared_host=bool(host and host.lower().rstrip('.')==aime_host.lower().rstrip('.'))
    auth_resolution=None
    if not (host or aime_host):return
    preferred=settings.get('networkInterface','')
    interface=active_interface(preferred)
    messages.append(f'联网接口：{interface or "系统路由"}')
    if host:
        try:
            auth_resolution=resolve_ipv4(host,interface,allow_proxy_route=True)
            origin,addresses=auth_resolution
            routes=auth_routes(origin,addresses,interface,bool(preferred and preferred==interface))
            if not routes:raise RuntimeError('没有可连接的游戏服务地址。')
            candidates=','.join(list(dict.fromkeys([*(ip for ip,_ in routes),*addresses]))[:16])
            # Bind and report the port in the relay process to avoid a race with
            # any app already using the previous fixed port.
            ready=session/'relay-ready.json'
            relay_process=child('relay',['--relay',json.dumps(routes),str(ready)])
            for _ in range(50):
                if relay_process.poll() is not None:raise RuntimeError('本机网络连接服务未启动。')
                if ready.exists():
                    state=json.loads(ready.read_text())
                    port=state.get('port')
                    if state.get('pid')==relay_process.pid and state.get('ready') is True and type(port) is int and 1024<=port<=65535:break
                time.sleep(.1)
            else:raise RuntimeError('本机网络连接服务启动超时。')
            env.update(AIRMAIDX_TRANSPORT_FIX='1',AIRMAIDX_AUTH_IPV4=candidates,AIRMAIDX_RELAY_PORT=str(port))
            messages.append('游戏认证中继已就绪，等待游戏连接。')
            if not origin:messages.append('无法取得服务源地址，认证连接将沿用系统代理路由。')
        except errors as error:
            messages.append('游戏认证中继未就绪，使用游戏自身的联网流程。'+str(error))
    if interface:
        env['AIRMAIDX_BIND_INTERFACE']=interface
        env['DYLD_INSERT_LIBRARIES']=str(runtime/'helpers/AirmaiNetworkInterface.dylib')
        if aime_host:
            try:
                resolved=auth_resolution if shared_host else resolve_ipv4(aime_host,interface)
                if resolved and resolved[0]:
                    origin,addresses=resolved
                    env['AIRMAIDX_IP_MAP']=','.join(ip+'='+origin for ip in addresses if ipaddress.IPv4Address(ip) in FAKE_IPV4)
                    messages.append('Aime 地址已解析。')
                else:messages.append('Aime 未取得源地址，使用系统路由。')
            except errors as error:
                # A separate reader endpoint cannot disable the game auth relay.
                messages.append('Aime 地址解析失败；游戏认证连接独立处理。'+str(error))
    (session/'network-setup.log').write_text('\n'.join(messages)+'\n')

def display_inventory(runtime):
    try:
        displays=json.loads(subprocess.check_output([str(runtime/'helpers/display-inventory')],timeout=8))
        if not isinstance(displays,list) or not displays:raise ValueError()
        for display in displays:
            bounds=display['CG_frame']
            if not all(isinstance(bounds[k],(int,float)) for k in ['x','y','width','height']):raise ValueError()
            if bounds['width']<=0 or bounds['height']<=0:raise ValueError()
        return displays
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        raise RuntimeError('暂时无法读取可用显示器，请唤醒或重新连接显示器后重试。') from error

def select_display(displays,identity):
    selected=next((d for d in displays if d.get('display_uuid')==identity),None)
    if selected is None:
        selected=next((d for d in displays if d['CG_frame']['height']>d['CG_frame']['width']),
                      next((d for d in displays if d.get('main')),displays[0]))
    return selected

def preview_display(store,runtime,game_id,settings,emit):
    """Independent timed preview; restores even if the SwiftUI window closes."""
    game=store.get(game_id);state=session_status(store,game)
    if not state['running']:raise ValueError('先启动游戏，再预览显示效果。')
    if not settings['fillDisplay']:raise ValueError('显示预览需要启用「铺满选定显示器」。')
    root=store.game_root(game);prefix=root/'Prefix';drive=prefix/'drive_c'
    with (root/'display-preview.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('另一项显示预览还没有结束。')
        displays=display_inventory(runtime)
        target=select_display(displays,settings['displayUUID'])
        session=Path(state['sessionPath']);env=environment(runtime,prefix)
        assignments=[k+'='+v for k,v in env.items() if k.startswith('DYLD_')]
        command=['/usr/bin/sandbox-exec','-f',str(session/'game.sb'),'/usr/bin/env',*assignments,str(runtime/'wine/bin/wine'),str(drive/'AirmaiDisplayControl-x64.exe')]
        try:subprocess.run(command,cwd=game['packagePath'],env=env,capture_output=True,check=True,timeout=5)
        except (subprocess.SubprocessError,OSError):raise RuntimeError('游戏窗口尚未就绪，请进入标题画面后重试。')
        inventory=json.loads((drive/'AirmaiDisplay-control.json').read_text())
        bounds=target['CG_frame']
        monitor=match_monitor(displays,target,inventory['monitors'])
        if monitor is None:raise ValueError('目标显示器已变化，请刷新显示器后重试。')
        cfg=drive/'AirmaiDisplay.cfg';previous=cfg.read_bytes()
        child=None
        try:
            cfg.write_text('AIRMAI_DISPLAY_V1\n'+str(settings['width'])+'\n'+str(settings['height'])+'\n')
            env.update(AIRMAIDX_DISPLAY_ACTION='preview',AIRMAIDX_DISPLAY_MONITOR=str(monitor['index']))
            child=subprocess.Popen(command,cwd=game['packagePath'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            started=time.monotonic()
            while child.poll() is None:
                elapsed=time.monotonic()-started
                if elapsed>30:raise RuntimeError('显示预览超时，正在恢复。')
                emit('progress',dict(message='显示预览中，将在 '+str(max(0,20-int(elapsed)))+' 秒后自动恢复',fraction=min(1,elapsed/20)))
                time.sleep(1)
            if child.returncode:raise RuntimeError('显示预览未能完成，原设置已保留。')
        finally:
            cfg.write_bytes(previous)
            if child and child.poll() is None:
                child.terminate()
                try:child.wait(timeout=3)
                except subprocess.TimeoutExpired:child.kill();child.wait()
            if child:
                env['AIRMAIDX_DISPLAY_ACTION']='restore'
                try:subprocess.run(command,cwd=game['packagePath'],env=env,capture_output=True,timeout=5)
                except (OSError,subprocess.SubprocessError):pass
        return True

def detect_hdx(enabled):
    """Optional hardware discovery must not prevent keyboard-only play."""
    report=dict(requested=enabled,mode='keyboard',status='disabled',message='未启用 HDX，使用键盘。')
    if not enabled:return [],report
    from hdx_touch_probe import usb_device_tree, resolve_touch
    from hdx_aux_probe import resolve
    try:
        tree=usb_device_tree()
        physical=[resolve_touch(tree),resolve('led',tree),resolve('reader',tree)]
    except (RuntimeError,OSError,subprocess.SubprocessError) as error:
        report.update(status='unavailable',message=str(error),fallback='本次使用键盘模式。')
        return [],report
    report.update(mode='hdx',status='connected',message='已识别 HDX 触摸、灯光和读卡器接口。')
    return physical,report

def startup_failure(output):
    codes=re.findall(r'"game_exit_code"\s*:\s*(\d+)',output)
    if codes and int(codes[-1]) & 0xc0000000 == 0xc0000000:
        return f'游戏发生 Windows 原生异常（0x{int(codes[-1]):08X}），已保留诊断记录。'
    if 'Failed to load from cache: BCryptOpenAlgorithmProvider failed' in output or ('MuMod' in output and 'no valid cache available' in output):
        return 'MuMod 未能加载有效模组，游戏已停止。请重新准备运行环境，以检查包内已签名缓存。'
    if 'DllNotFoundException: amdaemon_api' in output:
        return '游戏无法加载 AMDaemon 原生接口，已停止并保留诊断记录。'
    if re.search(r'Vfs:\s*FATAL:',output,re.I):
        return 'Segatools 文件路径初始化失败，游戏已停止。请查看 configuration-check.log 和 game-stdout.log。'
    if '"launcher_error"' in output:
        return 'Windows 启动链未能完成，请查看 game-stdout.log 中的 launcher_error。'
    return None

def cleanup_session(store,runtime,game,session,record,game_process,children,files):
    """Every cleanup step runs even if an earlier process/driver has failed."""
    errors=[]
    def attempt(label,action):
        try:action()
        except Exception as error:errors.append(label+': '+type(error).__name__+': '+str(error))
    def terminate(process,group=False):
        if process.poll() is not None:return
        if group:os.killpg(process.pid,signal.SIGTERM)
        else:process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if group:os.killpg(process.pid,signal.SIGKILL)
            else:process.kill()
            process.wait(timeout=5)
    if game_process:attempt('game',lambda:terminate(game_process,True))
    attempt('wine',lambda:stop_wine(runtime,store.game_root(game)/'Prefix'))
    for child in reversed(children):attempt('bridge',lambda p=child:terminate(p))
    for stream in files:attempt('log',stream.close)
    attempt('configuration',lambda:store.restore_launch_configs(game))
    from phone_cards import clean
    attempt('phone-reader',lambda:clean(store.game_root(game)/'Prefix/drive_c'))
    (session/'phone-reader-private.json').unlink(missing_ok=True)
    if errors:
        record.update(phase='error',message='退出清理未全部完成，记录已保留；下次启动会重试清理和配置恢复。')
        attempt('cleanup-log',lambda:(session/'cleanup-error.log').write_text('\n'.join(errors)+'\n'))
    record['ended']=now()
    atomic_json(store.game_root(game)/'session.json',record)

def session_run(store,runtime,game_id):
    game=store.get(game_id);root=store.game_root(game);pkg=store.require_package(game);prefix=root/'Prefix'
    session=root/'Sessions'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f');session.mkdir(parents=True)
    record=dict(manager_pid=os.getpid(),session=str(session),phase='starting',message='正在启动',started=now())
    state_path=root/'session.json'
    children=[];files=[];game_process=None
    with (store.root/'active-game.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('另一个游戏正在启动。')
        atomic_json(state_path,record)
        def finish(*_):raise KeyboardInterrupt
        old_signals={s:signal.signal(s,finish) for s in (signal.SIGTERM,signal.SIGINT)}
        try:
            env=environment(runtime,prefix);settings=game['settings'];drive=prefix/'drive_c'
            for folder in [root/'ShaderCache',session/'Renderer']:
                folder.mkdir(exist_ok=True)
            env.update(DXMT_SHADER_CACHE_PATH=str(root/'ShaderCache'),DXMT_LOG_PATH=str(session/'Renderer'))
            for name in ['AirmaiBootTrace.log','AirmaiDisplayTrace.log','AirmaiDisplayBridge.log','AirmaiControllerInput.log','AirmaiMouseInput.log']:
                p=pkg/name
                if p.exists():shutil.copy2(p,session/('previous-'+name));p.unlink()
            phone_reader=bool(settings.get('phoneReaderEnabled',False))
            record['phone_reader']=phone_reader
            from phone_cards import initialize,clean
            if phone_reader:initialize(drive,session)
            else:clean(drive)
            physical,input_report=detect_hdx(settings['hdxEnabled'])
            from controller_devices import inventory, public_inventory, game_api_verified
            controller_inventory=inventory(runtime) if settings.get('adxEnabled',True) else dict(devices=[],errors=[])
            input_report['controllers']=public_inventory(controller_inventory)
            adx_devices=[d for d in controller_inventory['devices'] if d['status']=='candidate']
            native_input_api=game_api_verified(runtime,pkg) if physical or adx_devices else False
            if physical and not native_input_api:
                physical=None
                input_report.update(mode='keyboard',status='unsupportedAPI',message='原生输入接口尚未匹配，本次使用系统键盘。')
            if adx_devices and not native_input_api:
                adx_devices=[]
                input_report['controllerFallback']='ADX 输入需要兼容的原生输入接口，本次使用系统键盘。'
                record['controller_message']=input_report['controllerFallback']
            if physical:adx_devices=[]  # Preserve the validated HDX player-1 path.
            if len(adx_devices)>2:
                adx_devices=[]
                input_report['controllerFallback']='输入接口不唯一，使用系统键盘。'
            atomic_json(session/'input-detection.json',input_report)
            hdx=bool(physical)
            record['input_mode']='hdx' if hdx else 'keyboard';atomic_json(state_path,record)
            def child(role,args):
                out=(session/(role+'.log')).open('wb');files.append(out)
                p=subprocess.Popen(own_command(*args),stdout=out,stderr=out)
                children.append(p);return p
            adx=False
            (pkg/'Mods/AirmaiControllerInput.dll').unlink(missing_ok=True)
            if adx_devices:
                selection=session/'controller-selection-private.json'
                atomic_json(selection,adx_devices)
                cfg=drive/'AirmaiController.cfg'
                p=child('controller',['--controller-input',str(runtime/'helpers/controller-hid'),str(selection),str(cfg),str(session/'controller')])
                for _ in range(60):
                    if p.poll() is not None:break
                    status=session/'controller/status.json'
                    if status.exists() and json.loads(status.read_text()).get('ready'):
                        adx=True;break
                    time.sleep(.1)
                if adx:
                    shutil.copy2(runtime/'helpers/AirmaiControllerInput.dll',pkg/'Mods/AirmaiControllerInput.dll')
                    record['input_mode']='adx';atomic_json(state_path,record)
                    input_report.update(mode='adx',status='inputBridgeReady',message='已启动 ADX 原生输入桥接；等待游戏内实机验证。')
                    input_report.pop('fallback', None)
                    atomic_json(session/'input-detection.json',input_report)
                else:
                    if p.poll() is None:
                        p.terminate()
                        try:p.wait(timeout=3)
                        except subprocess.TimeoutExpired:p.kill();p.wait(timeout=3)
                    input_report['controllerFallback']='原生手台输入未就绪，本次使用系统键盘。'
                    record['controller_message']=input_report['controllerFallback'];atomic_json(state_path,record)
                    atomic_json(session/'input-detection.json',input_report)
            if hdx:
                for port in [59184,59185]:
                    with socket.socket() as check:
                        try:check.bind(('127.0.0.1',port))
                        except OSError:raise RuntimeError('另一个会话正在使用 HDX，请先停止它再启动。')
                for name in ['AirmaiHdxNativeTouch.dll','AirmaiHdxNativeLed.dll']:
                    shutil.copy2(runtime/'helpers'/name,pkg/'Mods'/name)
                reader_private=session/'reader-private.json'
                for role,args,flag in [
                    ('reader',['--hdx-reader',str(reader_private),str(session/'reader')],'ready'),
                    ('touch',['--hdx-touch',str(drive/'AirmaiHDXBridge.cfg'),str(session/'touch')],'healthy'),
                    ('led',['--hdx-led',str(drive/'AirmaiHDXLED.cfg'),str(session/'led')],'native_port_open')]:
                    if role=='reader' and phone_reader:continue
                    p=child(role,args)
                    for _ in range(150):
                        if p.poll() is not None:raise RuntimeError('HDX '+role+' 连接失败，请在诊断页检查。')
                        status=session/role/'status.json'
                        if status.exists() and json.loads(status.read_text()).get(flag):break
                        time.sleep(.1)
                    else:raise RuntimeError('HDX 连接等待超时。')
                node=json.loads(reader_private.read_text())['pty_slave'] if not phone_reader else None
                alias=prefix/'dosdevices/com1'
                if alias.is_symlink():alias.unlink()
                elif alias.exists():raise ValueError('读卡器端口映射冲突。')
                if node:alias.symlink_to(node)
                env['AIRMAIDX_NATIVE_HDX']='1'
            else:
                node=None
                for name in ['AirmaiHdxNativeTouch.dll','AirmaiHdxNativeLed.dll']:
                    (pkg/'Mods'/name).unlink(missing_ok=True)
                alias=prefix/'dosdevices/com1'
                if alias.is_symlink():alias.unlink()
            mai=pkg/'mai2.ini';text,encoding=decode_text(mai.read_bytes())
            native_touch=hdx or (adx and any('touch' in d['channels'] for d in adx_devices))
            for key,value in [('DummyTouchPanel','0' if native_touch else '1'),('DummyLED','1')]:
                text=ini_set(text,existing_section_for_key(text,key,'AM'),key,value)
            overrides=[('mai2.ini',text.encode(encoding))]
            if adx:
                aqua=pkg/'AquaMai.toml'
                if aqua.exists():
                    a,ae=decode_text(aqua.read_bytes())
                    # Native and Wine readers must not consume the same HID.
                    for section in ['GameSystem.AdxHidInput','GameSystem.MaimollerIO']:
                        a=ini_set(a,section,'Disabled','true')
                    overrides.append(('AquaMai.toml',a.encode(ae)))
            common=pkg/'config_common.json'
            data=json.loads(decode_text(common.read_bytes())[0]) if common.exists() else {}
            if hdx:
                # Some AMDaemon builds reject Aime outright. Rebind only
                # a reader that is already enabled by the imported game.
                if isinstance(data.get('aime'),dict) and data['aime'].get('enable') is True:
                    units=data['aime'].get('unit')
                    if isinstance(units,list) and units:units[0].update(port=1)
                    data['aime']['high_baudrate']=True
                    overrides.append(('config_common.json',(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode()))
            if phone_reader:
                aime=data.setdefault('aime',{})
                if not isinstance(aime,dict):raise ValueError('此 HDD 的读卡配置格式不支持 iPhone 读卡器。')
                aime['enable']=True
                units=aime.get('unit')
                if isinstance(units,list) and units and isinstance(units[0],dict):units[0]['port']=1
                overrides=[item for item in overrides if item[0]!='config_common.json']
                overrides.append(('config_common.json',(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode()))
            seg=pkg/'segatools.ini';s,e=decode_text(seg.read_bytes())
            # A keyboard map does not present a USB I/O board to AMDaemon.
            # If the imported daemon requires board 0, enable Segatools'
            # software board for this session even with no physical device.
            usb_io=data.get('usb_io')
            if isinstance(usb_io,dict) and usb_io.get('enable') is True:
                nodes=usb_io.get('node')
                if isinstance(nodes,list) and any(isinstance(n,dict) and n.get('id')==0 for n in nodes):
                    s=ini_set(s,'io4','enable','1')
            s=ini_set(s,'aime','enable','1' if phone_reader or not hdx else '0')
            if phone_reader:
                s=ini_set(s,'aimeio','path',r'C:\AirmaiPhoneReader.dll')
            if not hdx or phone_reader:
                # A responsive empty reader permits normal guest play. Never
                # turn Return into a virtual-card scan or generate a card ID.
                s=ini_set(s,'aime','scan','0');s=ini_set(s,'aime','felicaGen','0')
            overrides.append(('segatools.ini',s.encode(e)))
            from camera_compatibility import CONFIG as camera_config, launch_override as camera_override
            camera=None
            try:
                camera=camera_override(pkg)
                if camera is not None:
                    overrides.append((camera_config,camera))
            except (OSError,ValueError) as error:
                (session/'camera-compatibility.log').write_text(f'无法检查 Sinmai-Assist 摄像头设置：{type(error).__name__}\n')
            store.apply_launch_configs(game,session,overrides)
            if camera is not None:
                (session/'camera-compatibility.log').write_text('本次暂停 Sinmai-Assist 的自定义摄像头编号。保留游戏原有的摄像头和登录设置。\n')
            mouse=configure_mouse(runtime,pkg,drive,settings,hdx or adx,os.environ.get('AIRMAIDX_UI_LANGUAGE','en'))
            if mouse:
                record['input_mode']='mouse';atomic_json(state_path,record)
                input_report.update(mode='mouse',message='鼠标已就绪；手台输入正常后自动停用。')
                atomic_json(session/'input-detection.json',input_report)
            env.update(AIRMAIDX_WORKDIR=r'C:\AirmaiDX\Package',AIRMAIDX_SKIP_API_PRECHECK='1',AIRMAIDX_SHOW_GAME_WINDOW='1',AIRMAIDX_KEEP_GAME_OPEN='1',
                       MTL_HUD_ENABLED='1' if settings['metalHUD'] else '0',MTL_HUD_LOG_ENABLED='1',MTL_HUD_ALIGNMENT='topleft',MTL_HUD_SCALE='0.2',
                       MTL_HUD_ELEMENTS='device,layersize,fps,gputime,frameinterval,frameintervalgraph')
            inventory=display_inventory(runtime)
            selected=select_display(inventory,settings['displayUUID'])
            # Window backing size and internal scene rendering are independent.
            size=selected['CG_frame']
            w,h=output_size(selected,settings)
            atomic_json(session/'display-target.json',dict(displayUUID=selected.get('display_uuid'),desktopPoints=size,outputPixels=dict(width=w,height=h),scenePixels=dict(width=settings['width'],height=settings['height']),wineRetina=True))
            env['AIRMAIDX_GAME_COMMAND']=f'Sinmai.exe --melonloader.disablestartscreen --melonloader.hideconsole -force-d3d11 -screen-fullscreen 0 -screen-width {w} -screen-height {h}'
            (drive/'AirmaiDisplay.cfg').write_text('AIRMAI_DISPLAY_V1\n'+str(settings['width'])+'\n'+str(settings['height'])+'\n')
            network=settings['networkEnabled']
            if network and settings['transportCompatibility']:
                configure_game_network(pkg,runtime,settings,session,env,child)
            # A package can require a startup HTTPS check even in guest/offline
            # mode. Only explicitly approved, statically recognized checks are
            # added to the offline network policy; no payload is rewritten.
            check_addresses=[]
            checks=startup_checks.discover(pkg)
            interface=active_interface(settings.get('networkInterface','')) if checks else ''
            for check in checks:
                if check['url'] not in game.get('allowedStartupChecks',[]):
                    raise ValueError('尚未允许包内启动状态检查。')
                from urllib.parse import urlparse
                origin,addresses=resolve_ipv4(urlparse(check['url']).hostname,interface)
                check_addresses.extend(addresses+[origin])
                if interface:
                    env['AIRMAIDX_BIND_INTERFACE']=interface
                    env['DYLD_INSERT_LIBRARIES']=str(runtime/'helpers/AirmaiNetworkInterface.dylib')
                    mappings=[ip+'='+origin for ip in addresses if ip!=origin]
                    if env.get('AIRMAIDX_IP_MAP'):mappings.insert(0,env['AIRMAIDX_IP_MAP'])
                    env['AIRMAIDX_IP_MAP']=','.join(mappings)
            # Deny writes outside this instance and keep Wine off actual HDX TTYs.
            socket_root=Path('/private/tmp')/('.wine-'+str(os.getuid()))
            socket_root.mkdir(mode=0o700,exist_ok=True)
            st=prefix.stat();socket_dir=socket_root/('server-'+format(st.st_dev,'x')+'-'+format(st.st_ino,'x'))
            policy=['(version 1)','(allow default)','(deny file-write*)',
                    '(allow file-write* (subpath '+sandbox_path(root)+'))',
                    '(allow file-write* (literal "/dev/null"))',
                    '(allow file-write* (literal '+sandbox_path(socket_root)+'))',
                    '(allow file-write* (subpath '+sandbox_path(socket_dir)+'))']
            if game.get('storageMode')=='direct':
                policy.append('(allow file-write* (subpath '+sandbox_path(pkg.parent)+'))')
            else:
                policy.append('(deny file-read* file-write* (subpath '+sandbox_path(game['sourcePath'])+'))')
            if not network:
                policy += ['(deny network*)','(allow network-outbound (remote unix-socket))','(allow network-inbound (local unix-socket))',
                           '(allow network-bind (local unix-socket))','(allow network-outbound (remote tcp "localhost:*"))',
                           '(allow network-bind (local tcp "localhost:*"))','(allow network-inbound (local tcp "localhost:*"))']
                if checks:
                    policy += ['(allow network-outbound (remote udp "*:53"))','(allow network-bind (local udp))','(allow network-inbound (local udp))']
                    # Seatbelt can scope ports but cannot express numeric
                    # remote hosts. The signed interposer scopes destinations.
                    policy.append('(allow network-outbound (remote tcp "*:443"))')
                    resolvers=subprocess.run(['/usr/sbin/scutil','--dns'],capture_output=True,text=True).stdout
                    dns_ips=sorted(set(re.findall(r'nameserver\[\d+\]\s*:\s*(\d+\.\d+\.\d+\.\d+)',resolvers)))
                    env.update(AIRMAIDX_STARTUP_ONLY='1',AIRMAIDX_STARTUP_IPS=','.join(sorted(set(check_addresses))),AIRMAIDX_DNS_IPS=','.join(dns_ips),
                               DYLD_INSERT_LIBRARIES=str(runtime/'helpers/AirmaiNetworkInterface.dylib'))
            for real in physical:policy.append('(deny file-read* file-write* (literal '+sandbox_path(real)+'))')
            if node:policy.append('(allow file-read* file-write* (literal '+sandbox_path(node)+'))')
            sb=session/'game.sb';sb.write_text('\n'.join(policy)+'\n')
            assignments=[k+'='+v for k,v in env.items() if k.startswith('DYLD_')]
            config_command=['/usr/bin/sandbox-exec','-f',str(sb),'/usr/bin/env',*assignments,
                            str(runtime/'wine/bin/wine'),str(drive/'AirmaiConfigurationProbe.exe')]
            with (session/'configuration-check.log').open('wb') as out:
                try:checked=subprocess.run(config_command,cwd=pkg,env=env,stdout=out,stderr=out,timeout=20)
                except subprocess.TimeoutExpired:raise RuntimeError('Windows 配置读取检查超时，诊断记录已保留。')
            if checked.returncode:
                raise RuntimeError('Windows 未能读取游戏配置或 VFS 目录，请在诊断页查看 configuration-check.log。')
            command=['/usr/bin/sandbox-exec','-f',str(sb),'/usr/bin/env',*assignments,str(runtime/'wine/bin/wine'),str(drive/'AirmaiGameLauncher.exe')]
            for label in ['game-stdout','game-stderr']:
                f=(session/(label+'.log')).open('wb');files.append(f)
            game_process=subprocess.Popen(command,cwd=pkg,env=env,stdout=files[-2],stderr=files[-1],start_new_session=True)
            record.update(phase='starting',message='正在初始化游戏，请等待自检',game_pid=game_process.pid);atomic_json(state_path,record)
            placed=False;next_placement=time.monotonic()+15
            title_verified=False
            while game_process.poll() is None:
                stdout=session/'game-stdout.log'
                if stdout.exists():
                    with stdout.open('rb') as read:
                        head=read.read(8192).decode(errors='replace')
                        read.seek(max(0,stdout.stat().st_size-20000));tail=read.read().decode(errors='replace')
                    failure=startup_failure(head+tail)
                    if failure:
                        record.update(phase='error',message=failure)
                        break
                    if 'A crash has been intercepted by the crash handler' in tail:
                        record.update(phase='error',message='游戏发生原生异常，本次诊断记录已保留。')
                        break
                boot=pkg/'AirmaiBootTrace.log'
                if boot.exists():
                    observation=tail_text(boot,24000)
                    failure=startup_failure(observation)
                    if failure:
                        record.update(phase='error',message=failure)
                        break
                    if observation.count('Unity Exception: FormatException')>=3 and 'Authentication.CheckValidity' in observation:
                        record.update(phase='error',message='包内启动状态检查持续异常，已停止游戏并保留诊断。')
                        break
                    if not title_verified and 'AdvertiseProcess' in observation and 'IsException=True' not in observation:
                        title_verified=True
                        record.update(phase='running',message='游戏已进入标题');atomic_json(state_path,record)
                        latest=store.get(game_id)
                        latest.update(compatibilityState='localTitle',compatibilityNote='本机已进入标题；联网、手台与完整歌曲分别验收。')
                        store.update(latest)
                if settings['fillDisplay'] and not placed and time.monotonic()>=next_placement and (pkg/'AirmaiBootTrace.log').exists():
                    next_placement=time.monotonic()+5
                    try:
                        helper_env=dict(env)
                        helper=['/usr/bin/sandbox-exec','-f',str(sb),'/usr/bin/env',*assignments,str(runtime/'wine/bin/wine'),str(drive/'AirmaiDisplayControl-x64.exe')]
                        r=subprocess.run(helper,cwd=pkg,env=helper_env,capture_output=True,timeout=5)
                        q=drive/'AirmaiDisplay-control.json'
                        if r.returncode==0 and q.exists():
                            qd=json.loads(q.read_text())
                            target=match_monitor(inventory,selected,qd['monitors'])
                            if target:
                                helper_env.update(AIRMAIDX_DISPLAY_ACTION='apply',AIRMAIDX_DISPLAY_MONITOR=str(target['index']))
                                applied=subprocess.run(helper,cwd=pkg,env=helper_env,capture_output=True,timeout=5)
                                placed=applied.returncode==0
                    except (subprocess.TimeoutExpired,OSError,ValueError):
                        # A secondary window helper must never terminate the game.
                        with (session/'display-retries.log').open('a') as log:log.write(now()+' Window not ready; retry pending\n')
                time.sleep(1)
            if record.get('phase')!='error':
                output=tail_text(session/'game-stdout.log',20000)
                codes=re.findall(r'"game_exit_code"\s*:\s*(\d+)',output)
                if codes:record['windows_exit_code']=int(codes[-1])
                failure=startup_failure(output)
                if failure:record.update(phase='error',message=failure,returncode=game_process.returncode)
                elif not title_verified:
                    record.update(phase='error',message='游戏在启动阶段退出，诊断记录已保留。',returncode=game_process.returncode)
                else:record.update(phase='stopped',message='游戏已停止',returncode=game_process.returncode)
            boot=pkg/'AirmaiBootTrace.log'
            if boot.exists() and 'IsException=True' in tail_text(boot,15000):
                record.update(phase='error',message='游戏异常退出，诊断记录已保留。')
        except KeyboardInterrupt:
            record.update(phase='stopped',message='游戏已停止')
        except Exception as error:
            import traceback
            (session/'service-error.log').write_text(traceback.format_exc())
            text=str(error) if isinstance(error,(ValueError,RuntimeError)) else '运行组件未能完成，本次诊断记录已保留。'
            record.update(phase='error',message=text)
        finally:
            # A second click on Stop must not interrupt configuration recovery.
            for sig in old_signals:signal.signal(sig,signal.SIG_IGN)
            try:cleanup_session(store,runtime,game,session,record,game_process,children,files)
            finally:
                for sig,handler in old_signals.items():signal.signal(sig,handler)
