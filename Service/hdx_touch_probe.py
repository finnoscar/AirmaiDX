"""Connected HDX touch transport probe; normal STAT request only, no calibration.

The device, interface label and CDC data node are resolved afresh from IORegistry.
9600 8N1 and {STAT} are evidenced by this HDD's IO.NewTouchPanel CIL;
the supplied manufacturer PDF specifies the touch channel and COM3 role.
Never opens the debug shell, LED channel or card reader.
"""
from pathlib import Path
import collections
import datetime
import json
import os
import plistlib
import select
import signal
import stat
import subprocess
import sys
import termios
import time
from xml.parsers.expat import ExpatError


def usb_device_tree():
    """Read one bounded IORegistry snapshot. No matching devices means empty stdout.

    ioreg exits successfully without emitting a plist when a class has no
    matches. Treat that as an empty inventory, not a corrupt game/runtime.
    """
    try:
        output = subprocess.check_output(
            ['/usr/sbin/ioreg', '-r', '-c', 'IOUSBHostDevice', '-a', '-l'],
            stderr=subprocess.PIPE, timeout=5)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('macOS USB 设备查询超时。') from error
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError('无法读取 macOS USB 设备列表。') from error
    if not output.strip():
        return []
    try:
        tree = plistlib.loads(output)
    except (ValueError, TypeError, OverflowError, ExpatError) as error:
        raise RuntimeError('macOS 返回的 USB 设备列表格式无效。') from error
    if not isinstance(tree, list) or any(not isinstance(node, dict) for node in tree):
        raise RuntimeError('macOS 返回的 USB 设备列表结构无效。')
    return tree


def registry_children(node):
    children = node.get('IORegistryEntryChildren', [])
    if not isinstance(children, list) or any(not isinstance(child, dict) for child in children):
        raise RuntimeError('macOS 返回的 USB 设备节点结构无效。')
    return children


def hdx_device(tree):
    matches = []
    def search(node):
        if node.get('idVendor') == 0x0ca3 and node.get('idProduct') == 0x0021:
            matches.append(node)
            return
        for child in registry_children(node):
            search(child)
    for node in tree:
        search(node)
    if not matches:
        raise RuntimeError('未检测到 HDX 手台。')
    if len(matches) != 1:
        raise RuntimeError('检测到多个 HDX 手台，请只连接一台。')
    return matches[0]


def resolve_touch(tree=None):
    device = hdx_device(usb_device_tree() if tree is None else tree)
    children = registry_children(device)
    control = [n for n in children if n.get('IORegistryEntryName') == 'HDX Touch channel'
               and n.get('bInterfaceClass') == 2 and n.get('bInterfaceNumber') == 4]
    data = [n for n in children if n.get('bInterfaceClass') == 10 and n.get('bInterfaceNumber') == 5]
    if len(control) != 1 or len(data) != 1:
        raise RuntimeError('Verified HDX touch control/data pair missing')
    ports = []
    def walk(node):
        if node.get('IOCalloutDevice'):
            ports.append(node['IOCalloutDevice'])
        for child in registry_children(node):
            walk(child)
    walk(data[0])
    if len(ports) != 1 or not isinstance(ports[0], str) or not ports[0].startswith('/dev/cu.usbmodem'):
        raise RuntimeError('Expected one macOS HDX touch callout node')
    if not stat.S_ISCHR(os.stat(ports[0]).st_mode):
        raise RuntimeError('Touch node is not a character device')
    return ports[0]


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Output directory required')
    root = Path(sys.argv[1]).resolve()
    if any((p/'Sinmai.exe').exists() or (p/'Package/Sinmai.exe').exists() for p in (root, *root.parents)):
        raise RuntimeError('Output may not be inside a game HDD')
    root.mkdir(parents=True, exist_ok=False)
    node = resolve_touch()
    manifest = {'role': 'HDX Touch channel', 'vid': 0x0ca3, 'pid': 0x0021,
                'control_interface': 4, 'data_interface': 5, 'baud': 9600, 'format': '8N1',
                'normal_start_command': '{STAT}', 'normal_start_command_hex': '7b535441547d',
                'other_device_commands': False, 'calibration_writes': False,
                'firmware_writes': False, 'led_or_card_reader_opened': False,
                'game_mapping_verified': False,
                'created': datetime.datetime.now().astimezone().isoformat()}
    (root/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    running = True
    reason = '180_second_limit'
    def stop(_sig, _frame):
        nonlocal running, reason
        running = False
        reason = 'operator_stop'
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    fd = os.open(node, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    original = termios.tcgetattr(fd)
    received = 0
    chunks = 0
    frames = collections.Counter()
    pending = bytearray()
    command_sent = False
    first_reported = False
    error = None
    started = time.monotonic()
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0
        attrs[1] = 0
        attrs[2] = (attrs[2] & ~(termios.CSIZE | termios.PARENB | termios.CSTOPB | termios.HUPCL)) | termios.CS8 | termios.CREAD | termios.CLOCAL
        if hasattr(termios, 'CRTSCTS'):
            attrs[2] &= ~termios.CRTSCTS
        attrs[3] = 0
        attrs[4] = attrs[5] = termios.B9600
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        print(json.dumps({'touch_port_open': True, 'role': 'HDX Touch channel', 'first_phase': '2-second passive read', 'session': str(root)}), flush=True)
        with (root/'raw-touch.bin').open('wb') as raw, (root/'touch-frames.jsonl').open('w') as log:
            while running and time.monotonic()-started < 180:
                if not command_sent and time.monotonic()-started >= 2:
                    # Normal report-start command, verified in the local game CIL.
                    payload = b'{STAT}'
                    if os.write(fd, payload) != len(payload):
                        raise RuntimeError('Short touch-start command write')
                    command_sent = True
                    print(json.dumps({'normal_start_sent': '{STAT}', 'no_reset_or_calibration_commands': True}), flush=True)
                ready, _, _ = select.select([fd], [], [], .2)
                if not ready:
                    continue
                data = os.read(fd, 4096)
                if not data:
                    reason = 'device_eof'
                    break
                if received + len(data) > 8*1024*1024:
                    reason = '8MB_limit'
                    break
                raw.write(data)
                chunks += 1
                received += len(data)
                pending.extend(data)
                while len(pending) >= 9:
                    at = pending.find(b'(')
                    if at < 0:
                        pending.clear()
                        break
                    if at:
                        del pending[:at]
                    if len(pending) < 9:
                        break
                    if pending[8] != 0x29:
                        del pending[0]
                        continue
                    frame = bytes(pending[:9])
                    del pending[:9]
                    frames[frame.hex()] += 1
                    log.write(json.dumps({'seq': sum(frames.values()), 'host_monotonic_ns': time.monotonic_ns(), 'hex': frame.hex()})+'\n')
                    if not first_reported:
                        first_reported = True
                        print(json.dumps({'first_9_byte_touch_frame': frame.hex(), 'touch_transport_received': True}), flush=True)
                if chunks % 100 == 0:
                    log.flush()
                    raw.flush()
    except Exception as exc:
        reason = 'error'
        error = str(exc)
        raise
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSANOW, original)
        finally:
            os.close(fd)
        summary = {'received_bytes': received, 'chunks': chunks, 'candidate_9_byte_frames': sum(frames.values()),
                   'distinct_frame_states': len(frames), 'state_samples': frames.most_common(32),
                   'normal_STAT_sent': command_sent, 'elapsed_seconds': round(time.monotonic()-started, 3),
                   'stop_reason': reason, 'error': error, 'touch_mapping_verified': False,
                   'game_integration_verified': False, 'no_reset_calibration_led_or_firmware_commands': True}
        (root/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
