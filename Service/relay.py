"""Byte-preserving EOF relay. Endpoints come only from the user's game settings."""
import socket, socketserver, threading, signal, ipaddress, os, time
from pathlib import Path
from storage import atomic_json

def connect_upstream(routes,port):
    """Try another route only before transmitting any client bytes."""
    deadline=time.monotonic()+10
    last=None
    for index,(ip,interface) in enumerate(routes,1):
        remaining=deadline-time.monotonic()
        if remaining<=0:break
        upstream=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        try:
            upstream.settimeout(min(4,remaining/(len(routes)-index+1)))
            if interface:upstream.setsockopt(socket.IPPROTO_IP,25,socket.if_nametoindex(interface))
            upstream.connect((ip,port))
            upstream.settimeout(15)
            return upstream,index,interface
        except OSError as error:
            last=error
            upstream.close()
            print(f'Game auth route {index} unavailable: {type(error).__name__} (errno {error.errno}).',flush=True)
    raise last or TimeoutError('Game auth connection deadline expired.')


def run(routes,upstream_port=80,ready_path=None):
    if not routes:raise ValueError('Relay requires at least one upstream route.')
    for ip,_ in routes:ipaddress.IPv4Address(ip)
    class Relay(socketserver.BaseRequestHandler):
        def handle(self):
            downstream=self.request;downstream.settimeout(15)
            upstream=None
            done=threading.Event()
            stage='upstream connect';received=False
            try:
                upstream,index,interface=connect_upstream(routes,upstream_port)
                stage='relay'
                print(f"Game auth upstream connected via route {index} ({interface or 'system'}).",flush=True)
                def upload():
                    try:
                        while True:
                            chunk=downstream.recv(65536)
                            if not chunk:break
                            upstream.sendall(chunk)
                    except OSError:pass
                    finally:
                        done.set()
                        try:upstream.shutdown(socket.SHUT_WR)
                        except OSError:pass
                thread=threading.Thread(target=upload,daemon=True);thread.start()
                while True:
                    chunk=upstream.recv(65536)
                    if not chunk:
                        done.wait(1)
                        try:downstream.shutdown(socket.SHUT_WR)
                        except OSError:pass
                        break
                    received=True
                    downstream.sendall(chunk)
                thread.join(timeout=2)
            except OSError as error:
                print(f'Game auth {stage} failed: {type(error).__name__} (errno {error.errno}).',flush=True)
            finally:
                if stage=='relay':print(f'Game auth upstream response received: {received}.',flush=True)
                if upstream is not None:upstream.close()
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address=True;daemon_threads=True
    with Server(('127.0.0.1',0),Relay) as server:
        if ready_path:atomic_json(Path(ready_path),dict(pid=os.getpid(),ready=True,port=server.server_address[1]))
        signal.signal(signal.SIGTERM,lambda *_:(_ for _ in ()).throw(KeyboardInterrupt()))
        try:server.serve_forever(.2)
        except KeyboardInterrupt:pass
        finally:
            if ready_path:Path(ready_path).unlink(missing_ok=True)
