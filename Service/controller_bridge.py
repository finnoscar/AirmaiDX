"""Known ADX HID/CDC input -> authenticated loopback.

Raw input exists only in the helper pipe. Diagnostics store counters, no input
history. HID state persists between reports, but helper/transport silence and
explicit removal release all buttons and touches.
"""
from pathlib import Path
import base64
import json
import os
import secrets
import select
import signal
import socket
import struct
import subprocess
import time
from controller_protocols import InputState, report_layout, normalize, decode
from storage import atomic_json
from adx_serial_touch import Ports

PACKET = struct.Struct('<4sHHQQQQHHHHII')
PORT = 59186


def packet(seq, states, touch_players, now_ns=None):
    flags = sum(1 << p for p in states) | sum(4 << p for p in touch_players if p in states)
    a, b = states.get(0, InputState()), states.get(1, InputState())
    return PACKET.pack(b'AMCI', 1, flags, seq, now_ns or time.monotonic_ns(),
                       a.touch, b.touch, a.buttons, b.buttons, a.auxiliary, b.auxiliary, PACKET.size, 0)


def combined_snapshot(inputs, serial, now, consume=True):
    states, touches = inputs.snapshot(now, consume)
    other, other_touches = serial.snapshot(now, consume)
    if states.keys() & other.keys(): return {}, set()
    return {**states, **other}, touches | other_touches


class Inputs:
    def __init__(self, devices):
        self.devices = {d['id']: d for d in devices}
        self.layouts = {d['id']: report_layout(base64.b64decode(d['descriptor'], validate=True)) for d in devices}
        self.opened = set(); self.live = set(); self.states = {}; self.pending = {}
        self.heartbeat = 0.; self.reports = self.invalid = 0

    def accept(self, event, now):
        kind = event.get('event'); identity = str(event.get('id', ''))
        if kind == 'heartbeat':
            self.heartbeat = now
            self.live = set(map(str, event.get('ids', []))) & self.opened
            for key in list(self.states):
                if key not in self.live: self.states.pop(key, None); self.pending.pop(key, None)
            return
        if identity not in self.devices: return
        device = self.devices[identity]
        if kind == 'opened': self.opened.add(identity); return
        if kind in ('removed', 'error'):
            self.opened.discard(identity); self.live.discard(identity)
            self.states.pop(identity, None); self.pending.pop(identity, None); return
        if identity not in self.opened: return
        if kind not in ('feature', 'report'): return
        try:
            data = bytes.fromhex(event['hex'])
            payload = normalize(self.layouts[identity], 'feature' if kind == 'feature' else 'input', event['reportID'], data)
            if kind == 'feature':
                canonical = bytes([event['reportID']]) + payload
                if device['profile'] != 'maimoller-hid' or len(canonical) <= 32 or canonical[4] not in (1, 2):
                    raise ValueError('Invalid Maimoller player metadata')
                device['player'] = canonical[4] - 1
                return
            if event['reportID'] != device['reportID']: return
            if device['player'] not in (0, 1): return
            state = decode(device['profile'], payload, event['reportID'], device['player'])
            self.states[identity] = state
            old = self.pending.get(identity, InputState())
            self.pending[identity] = InputState(old.touch | state.touch, old.buttons | state.buttons, old.auxiliary | state.auxiliary)
            self.reports += 1
        except (ValueError, KeyError, TypeError):
            self.invalid += 1
            self.states.pop(identity, None); self.pending.pop(identity, None)

    def transport_reset(self):
        # A newly attached game must see current held inputs only, never a
        # backlog of buttons pressed during loading or a previous connection.
        self.pending.clear()

    def snapshot(self, now, consume=True):
        states = {}; touches = set()
        if now - self.heartbeat > .35: return states, touches
        for identity in self.live:
            if identity not in self.states: continue
            device = self.devices[identity]; player = device['player']
            if player in states:
                # Includes player IDs discovered by feature report. Ambiguous
                # physical controllers never merge into one player silently.
                return {}, set()
            value = self.states[identity]; pending = self.pending.get(identity, InputState())
            states[player] = InputState(value.touch | pending.touch, value.buttons | pending.buttons, value.auxiliary | pending.auxiliary)
            if 'touch' in device['channels']: touches.add(player)
        if consume: self.pending.clear()
        return states, touches


def run(helper, selection, config, output):
    devices = json.loads(selection.read_text())
    if not 1 <= len(devices) <= 2 or any(d.get('status') != 'candidate' for d in devices):
        raise ValueError('Invalid controller selection')
    hid = [d for d in devices if d['profile'] != 'adx-serial']
    serial_devices = [d for d in devices if d['profile'] == 'adx-serial']
    players = [d['player'] for d in devices if d['player'] in (0, 1)]
    if len(set(players)) != len(players): raise ValueError('Ambiguous controller players')
    inputs = Inputs(hid); output.mkdir(parents=True, exist_ok=False); os.chmod(output, 0o700)
    token = secrets.token_bytes(32); running = True; client = None; seq = 0; buffer = b''
    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, stop); signal.signal(signal.SIGTERM, stop)
    process = None
    with Ports(serial_devices) as serial, socket.socket() as listener:
        listener.bind(('127.0.0.1', PORT)); listener.listen(1); listener.setblocking(False)
        touch_mask = sum(1 << d['player'] for d in devices if d['player'] in (0, 1) and 'touch' in d['channels'])
        # Maimoller player is discovered via Feature 1 after opening. Register
        # both provider slots without manufacturing any input for either.
        if any(d['profile'] == 'maimoller-hid' for d in devices): touch_mask = 3
        config.write_text('AIRMAI_CONTROLLER_V1\n'+str(PORT)+'\n'+token.hex()+'\n'+str(touch_mask)+'\n'); os.chmod(config, 0o600)
        try:
            if hid:
                process = subprocess.Popen([str(helper), '--stream', *[d['id'] for d in hid]], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                os.set_blocking(process.stdout.fileno(), False)
            last_send = last_status = 0.
            while running:
                now = time.monotonic()
                if process and process.poll() is not None: raise RuntimeError('原生 HID 输入服务已退出，输入已释放。')
                ready, _, _ = select.select(([process.stdout] if process else []) + [listener, *serial.active], [], [], .004)
                for fd in list(serial.active):
                    if fd in ready: serial.read(fd, time.monotonic())
                if process and process.stdout in ready:
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk: raise RuntimeError('原生 HID 输入服务连接已断开。')
                    buffer += chunk
                    if len(buffer) > 262144: raise RuntimeError('HID event buffer exceeded')
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        try: inputs.accept(json.loads(line), time.monotonic())
                        except (ValueError, TypeError, AttributeError): inputs.invalid += 1
                if listener in ready:
                    candidate, _ = listener.accept(); candidate.settimeout(.2)
                    try:
                        auth = b''
                        while len(auth) < 32:
                            data = candidate.recv(32-len(auth))
                            if not data: break
                            auth += data
                        if not secrets.compare_digest(auth, token): candidate.close()
                        else:
                            if client: client.close()
                            inputs.transport_reset()
                            serial.transport_reset()
                            client = candidate; client.settimeout(.02); client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    except OSError: candidate.close()
                if now-last_send >= .004:
                    states, touches = combined_snapshot(inputs, serial, now, consume=client is not None)
                    if client:
                        seq += 1
                        try: client.sendall(packet(seq, states, touches))
                        except OSError: client.close(); client = None
                    last_send = now
                if now-last_status >= 1:
                    states, touches = combined_snapshot(inputs, serial, now, consume=False)
                    atomic_json(output/'status.json', dict(ready=bool(inputs.opened) or bool(states), inputReceived=bool(states),
                        players=sorted(states), touchPlayers=sorted(touches), reports=inputs.reports+serial.reports,
                        serialTouchReports=serial.reports, serialNonzeroReports=serial.nonzero, serialTransitions=serial.transitions,
                        invalidReports=inputs.invalid+serial.invalid, connectedToGame=client is not None, hardwareVerified=False))
                    last_status = now
        finally:
            if client:
                try: client.sendall(packet(seq+1, {}, set()))
                except OSError: pass
                client.close()
            if process:
                process.terminate()
                try: process.wait(timeout=2)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=2)
                process.stdout.close()
            atomic_json(output/'status.json', dict(ready=False, stopped=True, hardwareVerified=False))
            config.unlink(missing_ok=True)
