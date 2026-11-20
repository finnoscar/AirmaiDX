from pathlib import Path
from contextlib import ExitStack, closing, redirect_stdout, suppress
from io import StringIO
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

SERVICE=Path(__file__).resolve().parents[1]/'Service'
sys.path.insert(0,str(SERVICE))
import relay


class RelayTests(unittest.TestCase):
    def testSocketFailureTriesNextRouteBeforeSendingAnyBytes(self):
        first=Mock();second=Mock()
        first.connect.side_effect=socket.timeout('timed out')
        with patch('relay.socket.socket',side_effect=[first,second]), \
                patch('relay.socket.if_nametoindex',return_value=9),redirect_stdout(StringIO()):
            connected,index,interface=relay.connect_upstream([('192.0.2.42','en8'),('198.18.0.73','')],80)
        first.close.assert_called_once()
        first.setsockopt.assert_called_once_with(socket.IPPROTO_IP,25,9)
        second.setsockopt.assert_not_called()
        second.connect.assert_called_once_with(('198.18.0.73',80))
        first.sendall.assert_not_called()
        second.sendall.assert_not_called()
        self.assertEqual((connected,index,interface),(second,2,''))

    def testIndependentListenersWithLegacyPortOccupiedAndBytesUnchanged(self):
        with tempfile.TemporaryDirectory() as directory,ExitStack() as stack:
            legacy=stack.enter_context(closing(socket.socket()))
            # Already in use also represents the intended condition.
            with suppress(OSError):
                legacy.bind(('127.0.0.1',59183));legacy.listen()
            origin=stack.enter_context(closing(socket.socket()))
            origin.bind(('127.0.0.1',0));origin.listen();origin.settimeout(4)
            children=[]
            try:
                for i in range(2):
                    ready=Path(directory)/f'ready-{i}.json'
                    process=subprocess.Popen([sys.executable,'-c',
                        'from pathlib import Path;import relay,sys; '
                        'relay.run([("127.0.0.1", "")], upstream_port=int(sys.argv[1]), ready_path=Path(sys.argv[2]))',
                        str(origin.getsockname()[1]),str(ready)],cwd=SERVICE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    children.append((process,ready))
                deadline=time.monotonic()+5
                while not all(f.exists() for _,f in children) and time.monotonic()<deadline:time.sleep(.02)
                states=[json.loads(f.read_text()) for _,f in children]
                ports=[s['port'] for s in states]
                self.assertEqual([s['pid'] for s in states],[p.pid for p,_ in children])
                self.assertEqual(len(set(ports+[59183])),3)
                for port in ports:
                    with socket.create_connection(('127.0.0.1',port),timeout=4) as client:
                        client.sendall(b'game request\0');client.shutdown(socket.SHUT_WR)
                        remote,_=origin.accept()
                        with remote:
                            remote.settimeout(4)
                            self.assertEqual(remote.makefile('rb').read(),b'game request\0')
                            remote.sendall(b'server response\xff');remote.shutdown(socket.SHUT_WR)
                        self.assertEqual(client.makefile('rb').read(),b'server response\xff')
            finally:
                for process,_ in children:
                    process.terminate()
                for process,_ in children:
                    try:process.wait(timeout=4)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
