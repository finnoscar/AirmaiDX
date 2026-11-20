"""Build the macOS preview; the game and runtime downloads stay outside the app."""
from pathlib import Path
import argparse, hashlib, json, os, plistlib, shutil, subprocess
from app_resources import preview_assets, service_fingerprint, native_fingerprint, worker_python, runtime_resource_source
from worker_bundle import worker_options, worker_tls_ready

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'build/AirmaiDX.app'
CONTENTS=APP/'Contents'
RUNTIME=CONTENTS/'Resources/Runtime'

def run(args,**kw):subprocess.run(list(map(str,args)),check=True,**kw)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def build_editor_preview_assets():
    preview_assets(ROOT,CONTENTS/'Resources',ROOT/'build')

def build_swift_app(skip=False):
    sdk_path=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()
    sdk_version=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-version'],text=True).strip()
    # SwiftBuild can record the deployment target as the linked SDK. AppKit
    # then uses legacy appearance even though the views use current APIs.
    # Keep macOS 15 support while recording the SDK actually used to build.
    command=['swift','build','-c','release','--sdk',sdk_path]
    if not skip:
        run([*command,'-j','2','-Xlinker','-platform_version','-Xlinker','macos',
             '-Xlinker','15.0','-Xlinker',sdk_version],cwd=ROOT)
    bindir=Path(subprocess.check_output([*command,'--show-bin-path'],cwd=ROOT,text=True).strip())
    executable=bindir/'AirmaiDX'
    metadata=subprocess.check_output(['xcrun','vtool','-show-build',executable],text=True)
    versions=[line.split()[1] for line in metadata.splitlines() if line.strip().startswith('sdk ')]
    if not versions or any(tuple(map(int,v.split('.'))) != tuple(map(int,sdk_version.split('.'))) for v in versions):
        raise RuntimeError('客户端的 SDK 标记与当前 Xcode 不一致，请去掉 --skip-swift 重新构建。')
    return executable

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--skip-swift', action='store_true')
    p.add_argument('--skip-worker', action='store_true')
    p.add_argument('--ui-only', action='store_true')
    p.add_argument('--game-references', type=Path, default=os.environ.get('AIRMAIDX_GAME_REFERENCES'),
                   help='Path to a user-provided Package folder; only compiler references are read.')
    p.add_argument('--mingw', default=os.environ.get('AIRMAIDX_MINGW', 'x86_64-w64-mingw32-gcc'))
    p.add_argument('--dotnet', default=os.environ.get('AIRMAIDX_DOTNET', 'dotnet'))
    a = p.parse_args()
    if not a.ui_only:
        if a.game_references is None:
            p.error('Specify --game-references for the managed bridge build. See docs/BUILDING.md.')
        pkg = Path(a.game_references).resolve()
        references = sorted((pkg / 'Sinmai_Data/Managed').glob('*.dll'))
        references += [pkg / 'MelonLoader/net35' / name for name in ('MelonLoader.dll', '0Harmony.dll')]
        if len(references) < 3 or not all(ref.is_file() for ref in references):
            p.error('Missing managed references or MelonLoader/net35 assemblies. See docs/BUILDING.md.')
        installed_sdks = subprocess.check_output([a.dotnet, '--list-sdks'], text=True).splitlines()
        if not installed_sdks:
            p.error('A .NET SDK with the Roslyn C# compiler is required.')
        version, folder = installed_sdks[-1].split(' [', 1)
        compiler = Path(folder.rstrip(']')) / version / 'Roslyn/bincore/csc.dll'
        if not compiler.is_file():
            p.error('Roslyn was not found in the selected .NET SDK.')
        if not a.skip_worker and APP.exists():
            shutil.rmtree(APP)
    if a.ui_only and not (RUNTIME/'manifest.json').exists():
        # Installation consumes the staging app, so reuse the verified installed
        # bundle on the next UI build instead of retaining a second full app.
        source,_=runtime_resource_source(ROOT,CONTENTS/'Resources')
        if (source/'ServiceSource.sha256').read_text().strip()!=service_fingerprint(ROOT):
            raise RuntimeError('已安装后台与源码不一致，请先完成一次完整应用构建。')
        run(['codesign','--verify','--deep','--strict',source.parent.parent])
        shutil.copytree(source.parent,CONTENTS,dirs_exist_ok=True,symlinks=True)
    for path in [CONTENTS/'MacOS',RUNTIME/'helpers']:path.mkdir(parents=True,exist_ok=True)
    executable = CONTENTS/'MacOS/AirmaiDX'
    shutil.copy2(build_swift_app(skip=a.skip_swift),executable)
    run(['xcrun','strip','-S',executable])
    build_editor_preview_assets()
    if a.ui_only:
        if not (RUNTIME/'manifest.json').exists():raise RuntimeError('请先完成一次完整应用构建。')
        run(['codesign','--force','--sign','-',APP],stdout=subprocess.DEVNULL)
        print(APP);return
    if not a.skip_worker:
        worker_fingerprint=service_fingerprint(ROOT)
        run([worker_python(ROOT),'-m','PyInstaller','--noconfirm','--clean','--onedir',*worker_options(worker_python(ROOT)),'--name','AirmaiDXService',
             '--distpath',ROOT/'build/Worker','--workpath',ROOT/'build/PyInstaller','--specpath',ROOT/'build',
             '--paths',ROOT/'Service',ROOT/'Service/service.py'],cwd=ROOT,stdout=(ROOT/'build/worker-build.log').open('w'),stderr=subprocess.STDOUT)
        dest=CONTENTS/'Resources/Service'
        if dest.exists():shutil.rmtree(dest)
        shutil.copytree(ROOT/'build/Worker/AirmaiDXService',dest)
        run([worker_python(ROOT),ROOT/'Tools/worker_bundle.py',dest])
        if not worker_tls_ready(dest):raise RuntimeError('打包后的后台 TLS 初始化失败，未生成可用构建。')
        if worker_fingerprint!=service_fingerprint(ROOT):raise RuntimeError('构建期间后台源码发生变化，请重新构建，避免封装混合版本。')
        (CONTENTS/'Resources/ServiceSource.sha256').write_text(worker_fingerprint+'\n')
        legacy=CONTENTS/'Helpers/AirmaiDXService'
        if legacy.exists():shutil.rmtree(legacy)
    cc=a.mingw
    common=['-O2','-Wall','-Wextra','-Werror','-ffreestanding','-fno-builtin','-nostdlib']
    for src,name,libs,entry in [
        ('GameLauncher.c','AirmaiGameLauncher.exe',['kernel32'],'WinMainCRTStartup'),
        ('PrerequisiteProbe.c','AirmaiProbe.exe',['kernel32','ws2_32'],'mainCRTStartup'),
        ('ConfigurationProbe.c','AirmaiConfigurationProbe.exe',['kernel32'],'mainCRTStartup'),
        ('windows-display-control.c','AirmaiDisplayControl-x64.exe',['kernel32','user32','gdi32','setupapi','hid','advapi32'],'WinMainCRTStartup')]:
        run([cc,*common,ROOT/'Native'/src,'-o',RUNTIME/'helpers'/name,'-Wl,--entry,'+entry,'-Wl,--subsystem,windows',*['-l'+x for x in libs]])
    for src,name in [('Transport.c','AirmaiTransport.dll'),('EOFCompatibility.c','AirmaiEOF.dll')]:
        run([cc,*common,'-shared',ROOT/'Native'/src,'-o',RUNTIME/'helpers'/name,'-Wl,--entry,DllMain','-lkernel32','-lws2_32'])
    run([cc,*common,'-shared',ROOT/'Native/PhoneReader.c','-o',RUNTIME/'helpers/AirmaiPhoneReader.dll','-Wl,--entry,DllMain','-lkernel32'])
    run(['swiftc','-target','arm64-apple-macos15.0',ROOT/'Native/PhoneReaderBonjour.swift','-o',RUNTIME/'helpers/phone-reader-bonjour'])
    run(['swiftc','-target','arm64-apple-macos15.0',ROOT/'Native/DisplayInventory.swift','-o',RUNTIME/'helpers/display-inventory'])
    run(['swiftc','-target','arm64-apple-macos15.0',ROOT/'Native/ControllerHID.swift','-o',RUNTIME/'helpers/controller-hid'])
    run(['swiftc','-target','arm64-apple-macos15.0',ROOT/'Native/SignedCacheVerifier.swift','-o',RUNTIME/'helpers/signed-cache-verifier'])
    run(['swiftc','-target','arm64-apple-macos15.0',ROOT/'Native/LibraryTrash.swift','-o',RUNTIME/'helpers/library-trash'])
    run(['clang','-arch','x86_64','-mmacosx-version-min=15.0','-dynamiclib','-Wl,-install_name,@rpath/AirmaiNetworkInterface.dylib','-O2','-Wall','-Wextra','-Werror',ROOT/'Native/NetworkInterface.c','-o',RUNTIME/'helpers/AirmaiNetworkInterface.dylib'])
    run(['codesign','--force','--sign','-',RUNTIME/'helpers/AirmaiNetworkInterface.dylib'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for source in ['AirmaiBootTrace','AirmaiHdxNativeTouch','AirmaiHdxNativeLed','AirmaiDisplayTrace','AirmaiDisplayBridge','AirmaiControllerInput','AirmaiMouseInput']:
        run([a.dotnet,compiler,
             '/nologo','/target:library','/nostdlib+','/optimize+','/deterministic+','/out:'+str(RUNTIME/'helpers'/(source+'.dll')),
             *['/reference:'+str(r) for r in references],ROOT/'Native'/(source+'.cs')])
    for name in ('sdez170-preset.json','runtime-downloads.json'):
        shutil.copy2(ROOT/'Resources/Runtime'/name,RUNTIME/name)
    shutil.copy2(ROOT/'LICENSE',RUNTIME/'Licenses/AirmaiDX-LICENSE.txt')
    shutil.copy2(ROOT/'docs/THIRD_PARTY_NOTICES.md',RUNTIME/'NOTICES.md')
    shutil.copy2(ROOT/'docs/ADX-PROTOCOL-NOTICE.md',RUNTIME/'ADX-PROTOCOL-NOTICE.md')
    from build_music_decoder import install as install_music_decoder
    install_music_decoder(ROOT,RUNTIME)
    profiles=json.loads((ROOT/'Resources/Runtime/compatibility-profiles.json').read_text())
    manifest=dict(version=1,native_source_sha256=native_fingerprint(ROOT),profile=profiles[0]['name'],
                  compatibility_profiles=profiles,critical_sha256={f'helpers/{p.name}':sha(p)
                  for p in sorted((RUNTIME/'helpers').iterdir()) if p.is_file()},game_included=False,prefix_included=False,gptk_included=False)
    (RUNTIME/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    info=dict(CFBundleName='AirmaiDX',CFBundleDisplayName='AirmaiDX',CFBundleIdentifier='com.airmai.AirmaiDX',CFBundleExecutable='AirmaiDX',
              CFBundlePackageType='APPL',CFBundleShortVersionString='0.2.14',CFBundleVersion='24',LSMinimumSystemVersion='15.0',NSHighResolutionCapable=True,
              CFBundleIconName='AppIcon',CFBundleIconFile='AppIcon',
              NSLocalNetworkUsageDescription='连接同一网络中的 iPhone 读卡伴侣。',NSBonjourServices=['_airmai-card._tcp.'],NSPrincipalClass='NSApplication',NSHumanReadableCopyright='AirmaiDX · Preview')
    with (CONTENTS/'Info.plist').open('wb') as f:plistlib.dump(info,f)
    from validate_portability import remove_build_rpaths
    remove_build_rpaths(APP)
    # install_name_tool and re-signing change bytes; hash the final owned files.
    manifest_path=RUNTIME/'manifest.json';final_manifest=json.loads(manifest_path.read_text())
    final_manifest['critical_sha256']={name:sha(RUNTIME/name) for name in final_manifest['critical_sha256']}
    manifest_path.write_text(json.dumps(final_manifest,indent=2)+'\n')
    run(['codesign','--force','--sign','-',APP],stdout=subprocess.DEVNULL)
    from validate_portability import validate
    (ROOT/'build/portability-check.json').write_text(json.dumps(validate(APP),indent=2)+'\n')
    print(APP)

if __name__=='__main__':main()
