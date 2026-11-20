"""Recognized package-supplied startup checks, with explicit per-game consent.

These checks are not bypassed, patched, cached as success, or replaced. The
game still performs its original HTTPS request and validates the real reply.
"""
from pathlib import Path
from urllib.parse import urlparse
import hashlib, ssl, sys, urllib.request, urllib.error
from launch_guidance import require_startup_checks

KNOWN_CHECKS={
    # Statically inspected GetJson/CheckValidity/IsValid in this exact assembly:
    # fixed HTTPS GET, no supplied headers/body/identity, successful value is 1.
    '0576c742b0935e5a438e317570add57217c37b8829bd2e2dcef416efefde4646':[
        dict(url='https://data.zhicheng233.top/sinmai/SDGB-1.50.json',method='GET',
             purpose='包内启动状态检查',sendsMachineData=False,expectedValue='1')
    ]
}

def discover(package):
    path=Path(package)/'Sinmai_Data/Managed/AMDaemon.NET.dll'
    if not path.is_file():return []
    checksum=hashlib.sha256(path.read_bytes()).hexdigest()
    return [dict(item,componentSHA256=checksum) for item in KNOWN_CHECKS.get(checksum,[])]

def tls_context():
    # The frozen Python was built with Homebrew OpenSSL. Its default CA path
    # points into /opt/homebrew, which is absent on a clean user's Mac.
    # Use Apple's system roots while retaining hostname/certificate validation.
    if sys.platform=='darwin':
        roots=Path('/etc/ssl/cert.pem')
        if not roots.is_file():raise RuntimeError('无法读取 macOS 系统证书，请检查系统更新后重试启动检查。')
        return ssl.create_default_context(cafile=str(roots))
    return ssl.create_default_context()

def preflight(game,checks):
    require_startup_checks(game,checks)
    for check in checks:
        expected=urlparse(check['url'])
        class ExactRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,request,fp,code,msg,headers,newurl):
                target=urlparse(newurl)
                if (target.scheme,target.hostname,target.port)!=(expected.scheme,expected.hostname,expected.port):
                    raise ValueError('启动检查跳转到了其他服务，已停止。')
                return super().redirect_request(request,fp,code,msg,headers,newurl)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),ExactRedirect(),
                                          urllib.request.HTTPSHandler(context=tls_context()))
        try:
            with opener.open(check['url'],timeout=12) as response:
                body=response.read(4097)
                if len(body)>4096:raise ValueError('启动状态响应超出预期大小，游戏尚未启动。')
                if body.decode('utf-8-sig').strip()!=check['expectedValue']:
                    raise ValueError('包内启动服务当前未允许启动，请向包的提供方核实。')
        except (OSError,UnicodeError,urllib.error.URLError) as error:
            raise RuntimeError('无法读取包内 HTTPS 启动状态，游戏尚未启动。请检查网络或代理后重试。') from error
