"""HDX-only native touch transport for the isolated local game experiment.

One positively identified touch TTY, normal {STAT} request only, loopback IPC.
No keyboard capture, LED/card/debug ports, calibration or firmware operations.
"""
from pathlib import Path
import argparse
import collections
import datetime
import json
import os
import secrets
import select
import signal
import socket
import struct
import termios
import time

from hdx_touch_port_lease import TouchPortLease

PACKET = struct.Struct('<4sHHQQQII')
MASK = (1 << 35) - 1
STALE_SECONDS = .2


class TouchFrames:
    def __init__(self):
        self.pending = bytearray()
        self.dropped = 0

    def feed(self, chunk):
        self.pending.extend(chunk)
        result = []
        while len(self.pending) >= 9:
            at = self.pending.find(b'(')
            if at < 0:
                self.dropped += len(self.pending)
                self.pending.clear()
                break
            if at:
                self.dropped += at
                del self.pending[:at]
            if len(self.pending) < 9:
                break
            if self.pending[8] != 0x29:
                self.dropped += 1
                del self.pending[0]
                continue
            frame = bytes(self.pending[:9])
            del self.pending[:9]
            # Exact low-five-bits mapping verified in local GetSwitchData CIL.
            bits = sum((value & 31) << (5 * i) for i, value in enumerate(frame[1:8]))
            result.append(bits)
        return result


def packet(seq, bits, healthy, now_ns=None):
    if bits & ~MASK or seq < 1:
        raise ValueError('Invalid touch packet')
    return PACKET.pack(b'HDXT', 1, int(healthy), seq,
                       now_ns or time.monotonic_ns(), bits if healthy else 0, PACKET.size, 0)


def run(config, output, port=59184):
    output.mkdir(parents=True, exist_ok=False)
    os.chmod(output, 0o700)
    config.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_bytes(32)
    running = True
    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    parser = TouchFrames()
    stats = collections.Counter()
    latest = 0
    last_frame = 0.0
    last_send = 0.0
    client = None
    started = time.monotonic()
    status_path = output / 'status.json'
    last_status = 0.0
    last_health = False
    error = None
    with TouchPortLease() as lease, socket.socket() as listener, (output/'touch-transitions.jsonl').open('w') as events:
        listener.bind(('127.0.0.1', port))
        listener.listen(1)
        listener.setblocking(False)
        config.write_text('AIRMAI_HDX_TOUCH_V1\n'+str(port)+'\n'+token.hex()+'\n')
        os.chmod(config, 0o600)
        # This is the normal streaming request from the verified game protocol.
        if os.write(lease.fd, b'{STAT}') != 6:
            raise RuntimeError('Short normal touch-start write')
        last_start_request = time.monotonic()
        print(json.dumps({'native_touch_bridge': 'started', 'loopback_only': True,
                          'role': 'HDX Touch channel', 'normal_command': '{STAT}',
                          'session': str(output)}, ensure_ascii=False), flush=True)
        try:
            while running:
                now = time.monotonic()
                ready, _, _ = select.select([lease.fd, listener], [], [], .005)
                if lease.fd in ready:
                    chunk = os.read(lease.fd, 4096)
                    if not chunk:
                        raise RuntimeError('Touch device disconnected or returned EOF')
                    stats['serial_bytes'] += len(chunk)
                    for bits in parser.feed(chunk):
                        stats['valid_serial_frames'] += 1
                        last_frame = time.monotonic()
                        if bits != latest:
                            stats['transitions'] += 1
                            if stats['transitions'] <= 10000:
                                events.write(json.dumps({'host_monotonic_ns': time.monotonic_ns(), 'bitmap': bits})+'\n')
                                events.flush()
                        latest = bits
                if listener in ready:
                    candidate, _ = listener.accept()
                    candidate.settimeout(.3)
                    auth = bytearray()
                    try:
                        while len(auth) < 32:
                            part = candidate.recv(32-len(auth))
                            if not part:
                                break
                            auth.extend(part)
                        if len(auth) != 32 or not secrets.compare_digest(bytes(auth), token):
                            stats['rejected_local_clients'] += 1
                            candidate.close()
                        else:
                            if client:
                                client.close()
                            client = candidate
                            client.settimeout(.02)
                            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                            stats['authenticated_connections'] += 1
                    except (OSError, TimeoutError):
                        candidate.close()
                now = time.monotonic()
                healthy = last_frame > 0 and now-last_frame <= STALE_SECONDS
                if not healthy and now-last_start_request >= 2:
                    # A normal reader initialization can stop streaming on this
                    # composite device. Retry only the verified report-start.
                    try:
                        if os.write(lease.fd, b'{STAT}') == 6:
                            stats['normal_stream_restart_requests'] += 1
                    except BlockingIOError:
                        pass
                    last_start_request = now
                if client and now-last_send >= .004:
                    stats['wire_sequence'] += 1
                    try:
                        client.sendall(packet(stats['wire_sequence'], latest, healthy))
                        stats['ipc_packets'] += 1
                    except (OSError, TimeoutError):
                        client.close()
                        client = None
                    last_send = now
                if now-last_status >= 1 or healthy != last_health:
                    state = dict(stats, healthy=healthy, bitmap=latest if healthy else 0,
                                 client_connected=client is not None,
                                 dropped_serial_bytes=parser.dropped,
                                 elapsed_seconds=round(now-started, 3),
                                 player=1, physical_region_mapping_verified=False,
                                 game_touch_response_verified=False)
                    temporary = status_path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n')
                    temporary.replace(status_path)
                    if healthy != last_health:
                        print(json.dumps({'native_touch_healthy': healthy, 'valid_frames': stats['valid_serial_frames']}), flush=True)
                    last_status, last_health = now, healthy
        except BaseException as exc:
            error = type(exc).__name__+': '+str(exc)
            raise
        finally:
            if client:
                try:
                    client.sendall(packet(stats['wire_sequence']+1, 0, False))
                except OSError:
                    pass
                client.close()
            config.unlink(missing_ok=True)
            state = dict(stats, healthy=False, bitmap=0, stopped=True, error=error,
                         dropped_serial_bytes=parser.dropped,
                         elapsed_seconds=round(time.monotonic()-started,3))
            status_path.write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args=p.parse_args()
    run(args.config.resolve(), args.output.resolve())
