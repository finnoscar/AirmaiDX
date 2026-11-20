"""Bounded, read-only log snapshots for the native viewer and manual sharing."""
from pathlib import Path
import datetime
import os
import platform
import re
import stat

PER_FILE = 128 * 1024
TOTAL = 1024 * 1024


def redact(text, store, game):
    text = text.replace('\0', '')
    # Replace longer paths first so source/package paths do not reveal the user.
    paths = [(game.get('sourcePath', ''), '[SOURCE]'), (game['packagePath'], '[PACKAGE]'),
             (str(store.root), '[AIRMAIDX]'), (str(Path.home()), '[HOME]')]
    for path, replacement in sorted(paths, key=lambda item: len(item[0]), reverse=True):
        if path:
            text = text.replace(path, replacement)
    text = re.sub(r'(?i)\bA(?=[A-Z0-9-]*[0-9])[A-Z0-9]{3}(?:-[A-Z0-9]{7,11}|[A-Z0-9]{7,12})\b', '[KEYCHIP]', text)
    # Segatools can print identifiers both as ASCII and BCD in raw trace dumps.
    text = re.sub(r'(?m)^\s*[0-9a-fA-F]{8}:\s+(?:[0-9a-fA-F]{2}\s+){4,}[^\r\n]*',
                  '[HEX DUMP REDACTED]', text)
    text = re.sub(r'(?im)^(\s*(?:Authorization|Cookie|Set-Cookie)\s*:\s*).*$', r'\1[REDACTED]', text)
    names = (r'keychip(?:[ _-]*id)?|key_chip|chipid|serial(?:number)?|aime(?:id)?|'
             r'access[ _-]*code|card(?:[ _-]*(?:id|no|number|uid))?|uid(?:_hex)?|'
             r'felica(?:id|idm)?|idm|auth(?:key|token)?|token|password|passwd|secret|'
             r'authorization|cookie|set-cookie|session[ _-]*id')
    text = re.sub(r'(?i)([\"\']?\b(?:' + names + r')\b[\"\']?\s*[:=]\s*)'
                  r'(\"[^\"\r\n]*\"|\'[^\'\r\n]*\'|[^\s,;&}\]\r\n]+)',
                  r'\1[REDACTED]', text)
    return re.sub(r'\b\d{16,20}\b', '[CARD_OR_IDENTIFIER]', text)


def read_tail(path, base, limit):
    """Do not follow log symlinks or block on a FIFO/device masquerading as a log."""
    try:
        if not path.resolve().is_relative_to(base.resolve()):
            return None
        relative = path.relative_to(base)
        current = base
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return None
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                return None
            stream.seek(max(0, info.st_size - limit))
            data = stream.read(limit)
        text = data.decode('utf-8-sig', errors='replace')
        return text, len(data), info.st_size > limit, datetime.datetime.fromtimestamp(info.st_mtime).astimezone().isoformat()
    except (OSError, ValueError):
        return None


def collect(store, game):
    root = store.game_root(game)
    package = Path(game['packagePath'])
    candidates = [(store.root/'last-worker-error.log',store.root,'后台通信异常'),
                  (root / 'compatibility.json', root, '游戏组件检查'),
                  (root / 'mod-compatibility.json', root, '模组接口与冲突检查'),
                  (root / 'manager.log', root, '管理器'), (root / 'session.json', root, '会话状态'),
                  (root / 'Prefix/drive_c/AirmaiMouse-state.txt', root, '鼠标与手台切换')]
    sessions = root / 'Sessions'
    latest = None
    if sessions.is_dir() and not sessions.is_symlink():
        latest = next((p for p in sorted(sessions.iterdir(), reverse=True)
                       if re.fullmatch(r'\d{8}-\d{6}(?:-\d{6})?', p.name) and p.is_dir() and not p.is_symlink()), None)
    if latest:
        for name, title in [('service-error.log', '启动异常'), ('configuration-check.log', 'Windows 配置读取'),
                            ('cleanup-error.log', '退出清理'),
                            ('network-setup.log', '网络初始化'), ('camera-compatibility.log', '摄像头兼容'),
                            ('game-stdout.log', '游戏输出'),
                            ('game-stderr.log', 'Wine 与图形输出'), ('input-detection.json', '输入设备检测'),
                            ('display-retries.log', '窗口显示重试'), ('display-target.json', '显示像素与场景目标'),
                            ('configuration-recovery-error.log', '配置恢复异常'),
                            ('controller.log','ADX 输入连接'), ('controller/status.json','ADX 输入状态'),
                            ('touch.log', '触摸连接'), ('led.log', '灯光连接'),
                            ('reader.log', '读卡器连接'), ('relay.log', '网络连接')]:
            candidates.append((latest / name, root, title))
        renderer = latest / 'Renderer'
        if renderer.is_dir() and not renderer.is_symlink():
            for path in sorted(renderer.iterdir())[:8]:
                if path.suffix.lower() in ['.log', '.txt']:
                    candidates.append((path, root, '渲染器'))
    for name, title in [('AirmaiBootTrace.log', 'Unity 启动'), ('AirmaiDisplayTrace.log', '渲染尺寸'),
                        ('AirmaiDisplayBridge.log', '窗口控制'), ('AirmaiControllerInput.log','ADX 游戏接入'),
                        ('AirmaiMouseInput.log','鼠标输入'), ('MelonLoader/Latest.log', 'MelonLoader'),
                        ('Sinmai_Data/output_log.txt', 'Unity 播放器')]:
        candidates.append((package / name, package, title))
    setup = root / 'Setup'
    if setup.is_dir() and not setup.is_symlink():
        for path in sorted(setup.glob('*.log'))[:6]:
            candidates.append((path, root, '环境初始化'))
    remaining = TOTAL
    logs = []
    for path, base, title in candidates:
        if remaining <= 0:
            break
        result = read_tail(path, base, min(PER_FILE, remaining))
        if result is None:
            continue
        text, count, truncated, modified = result
        remaining -= count
        # HDD logs may be on an external volume. Keep their IDs independent
        # of the selected path and preserve the IDs used by managed copies.
        if base == package:
            identity=Path('HDD/Package') / path.relative_to(package)
        else:
            identity=path.relative_to(base) if base == store.root else path.relative_to(root)
        logs.append(dict(id=str(identity), title=title, text=redact(text, store, game),
                         modified=modified, truncated=truncated))
    settings = game.get('settings', {})
    return dict(created=datetime.datetime.now().astimezone().isoformat(),
                system='macOS ' + (platform.mac_ver()[0] or platform.release()) + ' / ' + platform.machine(),
                session=latest.name if latest else None,
                summary='\n'.join([
                    'Game: ' + str(game.get('gameId') or 'unknown') + ' ' + str(game.get('gameVersion') or ''),
                    'Unity: ' + str(game.get('unityVersion') or 'unknown'),
                    'Render: ' + str(settings.get('width', '?')) + ' x ' + str(settings.get('height', '?')),
                    'Fill display: ' + str(settings.get('fillDisplay', False)),
                    'Metal HUD: ' + str(settings.get('metalHUD', False)),
                    'HDX requested: ' + str(settings.get('hdxEnabled', False)),
                    'ADX requested: ' + str(settings.get('adxEnabled', True)),
                    'Mouse fallback enabled: ' + str(settings.get('mouseEnabled', True)),
                    'Network enabled: ' + str(settings.get('networkEnabled', False))]),
                logs=logs, limitReached=remaining <= 0)
