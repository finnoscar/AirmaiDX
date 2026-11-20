"""ADX keyboard firmware's separate CDC touch input, not its CH340 LED port.

Only known 5767/5768 devices with CDC control 0/data 1 are candidates. Resolve
the callout afresh at open; never guess a TTY by its basename or USB hub. The
normal {STAT} streaming request is the only device command sent.
"""
import os
import stat
import termios
from hdx_touch_probe import usb_device_tree, registry_children
from controller_protocols import InputState


def endpoints(tree=None):
    found = {}
    def walk(node):
        vid, pid = node.get('idVendor'), node.get('idProduct')
        if vid == 0x2e3c and pid in (0x5767, 0x5768) and node.get('IOObjectClass') == 'IOUSBHostDevice':
            key = str(node['IORegistryEntryID'])
            children = registry_children(node)
            control = [n for n in children if n.get('bInterfaceNumber') == 0 and
                       n.get('bInterfaceClass') == 2 and n.get('bInterfaceSubClass') == 2]
            data = [n for n in children if n.get('bInterfaceNumber') == 1 and n.get('bInterfaceClass') == 10]
            ports = []
            def tty(n):
                if n.get('IOCalloutDevice'): ports.append(n['IOCalloutDevice'])
                for c in registry_children(n): tty(c)
            if len(control) == len(data) == 1: tty(data[0])
            if len(ports) == 1 and isinstance(ports[0], str) and ports[0].startswith('/dev/cu.usbmodem'):
                found[key] = dict(id='adx-serial-'+key, vendor=vid, product=pid,
                    profile='adx-serial', player=pid-0x5767, name='ADX 串口触摸',
                    channels=['touch'], status='candidate', port=ports[0],
                    detail='已匹配独立 CDC 触摸接口；外键继续使用系统键盘')
            return
        for child in registry_children(node): walk(child)
    for node in usb_device_tree() if tree is None else tree: walk(node)
    return list(found.values())


class Frames:
    def __init__(self):
        self.pending = bytearray()
        self.invalid = 0

    def feed(self, chunk):
        self.pending.extend(chunk)
        values = []
        while self.pending:
            at = self.pending.find(b'(')
            if at < 0:
                self.invalid += len(self.pending); self.pending.clear(); break
            if at:
                self.invalid += at; del self.pending[:at]
            if len(self.pending) < 9: break
            frame = self.pending[:9]
            # Seven five-bit groups; the last group's fifth bit is unused.
            if frame[8] != 0x29 or any(v > 31 for v in frame[1:7]) or frame[7] > 15:
                self.invalid += 1; del self.pending[0]; continue
            values.append(sum(value << (5*i) for i, value in enumerate(frame[1:8])))
            del self.pending[:9]
        return values


class Ports:
    def __init__(self, devices):
        self.devices = devices
        self.active = {}
        self.reports = self.invalid = 0
        self.nonzero = self.transitions = 0

    def __enter__(self):
        try:
            current = {d['id']: d for d in endpoints()} if self.devices else {}
            for selected in self.devices:
                device = current.get(selected['id'])
                if device is None or any(device[k] != selected[k] for k in ('vendor','product','player','profile')):
                    raise RuntimeError('ADX 触摸设备已变化，请重新启动游戏。')
                fd = os.open(device['port'], os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                original = None
                try:
                    if not stat.S_ISCHR(os.fstat(fd).st_mode): raise ValueError('ADX touch node is not a device')
                    original = termios.tcgetattr(fd)
                    attrs = termios.tcgetattr(fd)
                    attrs[0] = attrs[1] = attrs[3] = 0
                    attrs[2] = (attrs[2] & ~(termios.CSIZE | termios.PARENB | termios.CSTOPB | termios.HUPCL)) | termios.CS8 | termios.CREAD | termios.CLOCAL
                    if hasattr(termios, 'CRTSCTS'): attrs[2] &= ~termios.CRTSCTS
                    attrs[4] = attrs[5] = termios.B115200
                    attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
                    termios.tcsetattr(fd, termios.TCSANOW, attrs)
                    if os.write(fd, b'{STAT}') != 6: raise OSError('Short normal touch-start write')
                    self.active[fd] = dict(device=device, original=original, parser=Frames(),
                        latest=0, pending=0, received=None)
                except BaseException:
                    try:
                        if original is not None: termios.tcsetattr(fd, termios.TCSANOW, original)
                    finally: os.close(fd)
                    raise
        except BaseException:
            self.__exit__(); raise
        return self

    def close(self, fd):
        state = self.active.pop(fd)
        try: termios.tcsetattr(fd, termios.TCSANOW, state['original'])
        except (OSError, termios.error): pass
        finally: os.close(fd)

    def read(self, fd, now):
        state = self.active[fd]
        try:
            chunk = os.read(fd, 65536)
            if not chunk: self.close(fd); return
        except BlockingIOError: return
        except OSError: self.close(fd); return
        parser = state['parser']; previous = parser.invalid
        for bits in parser.feed(chunk):
            if bits: self.nonzero += 1
            if bits != state['latest']: self.transitions += 1
            state['latest'] = bits; state['pending'] |= bits; state['received'] = now
            self.reports += 1
        self.invalid += parser.invalid-previous

    def transport_reset(self):
        for state in self.active.values(): state['pending'] = 0

    def snapshot(self, now, consume=True):
        states = {}
        for state in self.active.values():
            if state['received'] is None or now-state['received'] > .2:
                state['latest'] = state['pending'] = 0; continue
            player = state['device']['player']
            if player in states: return {}, set()
            states[player] = InputState(touch=state['latest'] | state['pending'])
        if consume: self.transport_reset()
        return states, set(states)

    def __exit__(self, *_):
        for fd in list(self.active): self.close(fd)
