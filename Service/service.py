"""AirmaiDX's bundled operation worker. JSON in/out; no shell command strings."""
from pathlib import Path
import argparse, json, re, sys
from storage import Store
from contextlib import nullcontext
from launch_guidance import LaunchRequirement
from machine_config import save_keychip
import runtime
import runtime_download

def emit(event,data):
    print(json.dumps(dict(event=event,data=data),ensure_ascii=False),flush=True)

def main():
    if len(sys.argv)>1 and sys.argv[1]=='--tls-self-test':
        import ssl
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        emit('result',dict(tlsReady=True));return
    if len(sys.argv)>1 and sys.argv[1].startswith('--hdx-'):
        role=sys.argv[1]
        if role=='--hdx-touch':
            from hdx_touch_bridge import run
            run(Path(sys.argv[2]),Path(sys.argv[3]))
        elif role=='--hdx-led':
            from hdx_led_bridge import run
            run(Path(sys.argv[2]),Path(sys.argv[3]))
        elif role=='--hdx-reader':
            from hdx_reader_bridge import run
            run(Path(sys.argv[2]),Path(sys.argv[3]))
        return
    if len(sys.argv)>1 and sys.argv[1]=='--phone-reader-server':
        from phone_reader_server import run
        run(Path(sys.argv[2]),Path(sys.argv[3]),int(sys.argv[4]),sys.argv[5]);return
    if len(sys.argv)>1 and sys.argv[1]=='--controller-input':
        from controller_bridge import run
        run(*map(Path,sys.argv[2:6]));return
    if len(sys.argv)>1 and sys.argv[1]=='--relay':
        import relay
        relay.run(json.loads(sys.argv[2]),ready_path=Path(sys.argv[3]));return
    p=argparse.ArgumentParser()
    p.add_argument('operation',nargs='?')
    p.add_argument('--session')
    p.add_argument('--root')
    p.add_argument('--runtime',required=True,type=Path)
    args=p.parse_args()
    args.runtime=args.runtime.resolve()
    store=Store(args.root)
    bundled_runtime=args.runtime
    args.runtime=runtime_download.resolve(bundled_runtime,store.root)
    if args.session:
        runtime.session_run(store,args.runtime,args.session);return
    request=json.loads(sys.stdin.read() or '{}')
    op=args.operation
    mutations={'installRuntime','import','prepare','start','saveConfig','restore','settings','allowStartupCheck','allowStartupChecks','saveKeychip','saveMusic','delete','transferMusic'}
    with store.operation() if op in mutations else nullcontext():
        if op=='installRuntime':result=runtime_download.install(bundled_runtime,store,emit)
        elif op=='list':result=store.library()
        elif op in ('phoneStatus','phoneStart','phonePair','phoneStop','phoneForget'):
            import phone_reader_server as phone
            if op=='phonePair':result=phone.new_code(store,args.runtime,request['parentPID'])
            elif op=='phoneStop':result=phone.stop(store)
            elif op=='phoneForget':result=phone.forget(store,request['clientID'])
            else:
                if op=='phoneStart' and phone.read(store.root/'PhoneReader/clients.json',[]):phone.start(store,args.runtime,request['parentPID'])
                result=phone.status(store)
        elif op=='components':result=runtime.components(args.runtime)
        elif op=='controllers':
            from controller_devices import inventory, public_inventory
            result=public_inventory(inventory(args.runtime))
        elif op=='gamePresentation':
            from artwork import presentation
            result=presentation(store,store.get(request['id']))
        elif op=='import':result=store.import_game(request['source'],emit)
        elif op=='prepare':result=runtime.prepare(store,args.runtime,request['id'],emit)
        elif op=='launchGuide':result=runtime.launch_guide(store,request['id'])
        elif op=='saveKeychip':result=save_keychip(store,request['id'],request['value'])
        elif op=='readConfig':result=store.read_config(request['id'],request['name'])
        elif op=='saveConfig':
            result=store.save_config(request['id'],request['name'],request['text'],request['sha256'],request['encoding'])
        elif op=='backups':result=store.backups(request['id'])
        elif op=='restore':result=store.restore(request['id'],request['backupID'])
        elif op=='status':result=runtime.session_status(store,store.get(request['id']))
        elif op=='diagnostics':
            from diagnostics import collect
            result=collect(store,store.get(request['id']))
        elif op=='start':result=runtime.start(store,args.runtime,request['id'],emit,ui_language=request.get('language','en'))
        elif op=='stop':result=runtime.stop(store,request['id'])
        elif op=='delete':result=runtime.delete_game(store,args.runtime,request['id'])
        elif op in ('allowStartupCheck','allowStartupChecks'):
            game=store.get(request['id'])
            from startup_checks import discover
            checks=discover(Path(game['packagePath']))
            urls=[request['url']] if op=='allowStartupCheck' else request['urls']
            if not isinstance(urls,list) or not urls or any(url not in [item['url'] for item in checks] for url in urls):
                raise ValueError('包内启动检查已变化，请重试。')
            allowed=set(game.get('allowedStartupChecks',[]))
            if request['allowed'] is True:allowed.update(urls)
            elif request['allowed'] is False:allowed.difference_update(urls)
            else:raise ValueError('请选择是否允许此启动检查。')
            game.update(allowedStartupChecks=sorted(allowed),startupChecks=checks);store.update(game);result=game
        elif op in ('settings','previewDisplay'):
            game=store.get(request['id']);settings=request['settings']
            if set(settings)!=set(game['settings']):raise ValueError('设置格式不完整。')
            w,h=settings['width'],settings['height']
            if type(w) is not int or type(h) is not int or not 360<=w<=4320 or not 640<=h<=7680 or abs(w/h-9/16)>.001:
                raise ValueError('请选择 9:16 的竖屏渲染分辨率。')
            if not isinstance(settings['displayUUID'],str) or len(settings['displayUUID'])>128:
                raise ValueError('请选择有效的显示器。')
            if not isinstance(settings['networkInterface'],str) or (settings['networkInterface'] and not re.fullmatch(r'en\d+',settings['networkInterface'])):
                raise ValueError('请选择有效的物理网络接口。')
            for key in ['fillDisplay','metalHUD','hdxEnabled','adxEnabled','mouseEnabled','phoneReaderEnabled','networkEnabled','transportCompatibility']:
                if not isinstance(settings[key],bool):raise ValueError('设置类型不正确。')
            if op=='previewDisplay':result=runtime.preview_display(store,args.runtime,game['id'],settings,emit)
            else:
                game['settings']=settings;store.update(game);result=game
        elif op=='saveMusic':
            from music import save_draft
            result=save_draft(store,store.get(request['id']),request)
        elif op=='musicMedia':
            from music_assets import media
            result=media(store,store.get(request['id']),args.runtime,request)
        elif op=='transferMusic':
            from music_assets import transfer
            result=transfer(store,store.get(request['id']),request)
        else:raise ValueError('不支持这个操作。')
    emit('result',result)

if __name__=='__main__':
    try:main()
    except LaunchRequirement as error:
        print(json.dumps(dict(event='error',message=str(error),guide=error.guide),ensure_ascii=False),flush=True)
        sys.exit(1)
    except Exception as error:
        print(json.dumps(dict(event='error',message=str(error)),ensure_ascii=False),flush=True)
        sys.exit(1)
