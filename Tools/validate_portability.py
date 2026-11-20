"""Check actual Mach-O load commands, rather than trusting Info.plist alone."""
from pathlib import Path
import plistlib
import re
import subprocess

MAGIC={b'\xcf\xfa\xed\xfe',b'\xce\xfa\xed\xfe',b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca',b'\xca\xfe\xba\xbf'}

def version(value):
    parts=tuple(int(x) for x in value.split('.'))
    return (parts+(0,0,0))[:3]

def command_issues(text,minimum):
    issues=[]
    for block in re.split(r'Load command \d+',text):
        command=re.search(r'\bcmd (LC_\w+)',block)
        if not command:continue
        command=command[1]
        if command in ['LC_BUILD_VERSION','LC_VERSION_MIN_MACOSX']:
            value=re.search(r'\b(?:minos|version) ([\d.]+)',block)
            if value and version(value[1])>version(minimum):issues.append('最低系统版本 '+value[1]+' 高于 App 声明的 '+minimum)
        if command in ['LC_LOAD_DYLIB','LC_LOAD_WEAK_DYLIB','LC_REEXPORT_DYLIB','LC_LOAD_UPWARD_DYLIB','LC_RPATH']:
            path=re.search(r'\b(?:name|path) (.+?) \(offset \d+\)',block)
            if path and path[1].startswith('/') and not path[1].startswith(('/System/Library/','/usr/lib/')):
                issues.append('依赖构建机绝对路径 '+path[1])
    return issues

def validate(app):
    app=Path(app);info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
    minimum=info['LSMinimumSystemVersion'];issues=[];count=0
    for path in (app/'Contents').rglob('*'):
        if path.is_symlink() or not path.is_file():continue
        with path.open('rb') as stream:magic=stream.read(4)
        if magic not in MAGIC:continue
        count+=1
        result=subprocess.run(['/usr/bin/otool','-l',str(path)],capture_output=True,text=True,check=True,timeout=15)
        issues.extend(str(path.relative_to(app))+': '+issue for issue in command_issues(result.stdout,minimum))
    if issues:raise ValueError('跨机器运行检查未通过：\n'+'\n'.join(issues))
    return dict(mach_o_files=count,minimum_macos=minimum,issues=[])

def remove_build_rpaths(app):
    """Remove optional build-host search directories from the owned app copy."""
    changed=[]
    for path in (Path(app)/'Contents').rglob('*'):
        if path.is_symlink() or not path.is_file():continue
        with path.open('rb') as stream:magic=stream.read(4)
        if magic not in MAGIC:continue
        text=subprocess.check_output(['/usr/bin/otool','-l',str(path)],text=True,timeout=15)
        rpaths=set()
        for block in re.split(r'Load command \d+',text):
            if not re.search(r'\bcmd LC_RPATH\b',block):continue
            match=re.search(r'\bpath (.+?) \(offset \d+\)',block)
            if match and match[1].startswith('/') and not match[1].startswith(('/System/Library/','/usr/lib/')):rpaths.add(match[1])
        if not rpaths:continue
        subprocess.run(['/usr/bin/install_name_tool',*[arg for name in sorted(rpaths) for arg in ['-delete_rpath',name]],str(path)],check=True,capture_output=True)
        subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(path)],check=True,capture_output=True)
        changed.append(str(path.relative_to(app)))
    return changed

if __name__=='__main__':
    import json,sys
    print(json.dumps(validate(Path(sys.argv[1])),ensure_ascii=False,indent=2))
