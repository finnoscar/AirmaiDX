"""Local, certificate-pinned iPhone reader. Never logs card data or credentials."""
from contextlib import contextmanager
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import traceback
import datetime, fcntl, hashlib, json, os, secrets, select, signal, socket, ssl, subprocess, threading, time, uuid
from storage import atomic_json, Store
from phone_cards import CardRejected, active_reader, checked_card, present

@contextmanager
def locked(root):
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (root/'control.lock').open('a+') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX);yield

def read(path,default):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return default

def live(root):
    state=read(root/'server.json',{})
    try:
        pid=state['pid'];os.kill(pid,0)
        command=subprocess.check_output(['/bin/ps','-ww','-p',str(pid),'-o','command='],text=True,timeout=2)
        if '--phone-reader-server' in command and str(root.parent) in command:return state
    except (KeyError,OSError,subprocess.SubprocessError):pass
    return {}

def status(store):
    root=store.root/'PhoneReader'
    with locked(root):
        state=live(root);code=read(root/'code.json',{})
        valid=bool(state and code.get('expires',0)>time.time() and code.get('attempts',5)<5 and not code.get('used'))
        clients=read(root/'clients.json',[])
        return dict(enabled=bool(state),code=code['code'] if valid else None,
                    expiresAt=code.get('expires',0) if valid else 0,
                    clients=[dict(id=x['id'],name=x['name']) for x in clients],
                    readerReady=active_reader(store) is not None)

def start(store,runtime,parent):
    from runtime import own_command
    if type(parent) is not int or parent<=1:raise ValueError('无法识别启动器进程。')
    root=store.root/'PhoneReader'
    with locked(root):
        if live(root):return
        nonce=secrets.token_hex(16)
        atomic_json(root/'starting.json',dict(nonce=nonce))
        subprocess.Popen(own_command('--phone-reader-server',str(store.root),str(runtime),str(parent),nonce),
                         stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    for _ in range(70):
        state=live(root)
        if state and state.get('nonce')==nonce:return
        if read(root/'failure.json',{}).get('nonce')==nonce:break
        time.sleep(.1)
    failure=read(root/'failure.json',{})
    if failure.get('nonce')==nonce and failure.get('stage')=='tls':
        raise ValueError('iPhone 读卡服务的 TLS 初始化失败。请更新或重新安装 Mac 版 AirmaiDX。')
    if failure.get('nonce')==nonce and failure.get('stage')=='bonjour':
        raise ValueError('iPhone 读卡服务无法发布网络连接。请检查 Mac 的本地网络权限后重试。')
    raise ValueError('iPhone 读卡服务启动失败。请在 Mac 的诊断页查看错误记录。')

def new_code(store,runtime,parent):
    start(store,runtime,parent);root=store.root/'PhoneReader'
    with locked(root):
        atomic_json(root/'code.json',dict(code=f'{secrets.randbelow(1000000):06d}',expires=time.time()+120,attempts=0,used=False))
    return status(store)

def forget(store,client_id):
    try:
        if not isinstance(client_id,str) or str(uuid.UUID(client_id))!=client_id:raise ValueError()
    except (ValueError,AttributeError):raise ValueError('请选择有效的已配对设备。') from None
    root=store.root/'PhoneReader'
    with locked(root):
        clients=read(root/'clients.json',[])
        atomic_json(root/'clients.json',[client for client in clients if client['id']!=client_id])
    return status(store)

def stop(store):
    root=store.root/'PhoneReader'
    with locked(root):
        state=live(root)
        atomic_json(root/'clients.json',[]);(root/'code.json').unlink(missing_ok=True)
        if state:
            try:os.kill(state['pid'],signal.SIGTERM)
            except ProcessLookupError:pass
        (root/'server.json').unlink(missing_ok=True)
    # Allow the old publisher/server to release its exclusive lifetime lock.
    with (root/'server.lock').open('a+') as lock:
        for _ in range(30):
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:time.sleep(.05)
    return status(store)

def pair(root,body,now=None):
    now=time.time() if now is None else now
    if not isinstance(body,dict):raise CardRejected('invalidCode')
    supplied=body.get('code');name=body.get('deviceName')
    if not isinstance(supplied,str) or len(supplied)!=6 or any(c not in '0123456789' for c in supplied):raise CardRejected('invalidCode')
    if not isinstance(name,str) or not 1<=len(name)<=80 or any(ord(c)<32 for c in name):raise CardRejected('invalidCode')
    with locked(root):
        state=read(root/'code.json',{})
        if state.get('expires',0)<=now or state.get('used') or state.get('attempts',5)>=5:raise CardRejected('expiredCode')
        state['attempts']+=1
        if not secrets.compare_digest(supplied,state['code']):
            atomic_json(root/'code.json',state);raise CardRejected('invalidCode')
        clients=read(root/'clients.json',[])
        if len(clients)>=16:raise CardRejected('tooManyDevices')
        token=secrets.token_hex(32)
        clients.append(dict(id=str(uuid.uuid4()),name=name,hash=hashlib.sha256(token.encode()).hexdigest()))
        state['used']=True;state.pop('code',None)
        atomic_json(root/'code.json',state);atomic_json(root/'clients.json',clients)
        return dict(token=token,name=socket.gethostname().removesuffix('.local'))

def authorized(root,header):
    if not isinstance(header,str) or len(header)!=71 or not header.startswith('Bearer '):return False
    digest=hashlib.sha256(header[7:].encode()).hexdigest()
    with locked(root):return any(secrets.compare_digest(digest,x['hash']) for x in read(root/'clients.json',[]))

class Server(ThreadingHTTPServer):
    daemon_threads=True;request_queue_size=8
    def __init__(self,address,store):
        self.store=store;self.root=store.root/'PhoneReader';self.present_lock=threading.Lock();self.slots=threading.BoundedSemaphore(8);self.seen={}
        super().__init__(address,Handler)
    def get_request(self):
        connection,address=super().get_request();connection.settimeout(5);return connection,address
    def process_request(self,request,address):
        if not self.slots.acquire(False):self.shutdown_request(request);return
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()
    def handle_error(self,*_):pass

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    def log_message(self,*_):pass
    def reply(self,code,body):
        data=json.dumps(body,separators=(',',':')).encode()
        self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
        try:
            if self.path not in ('/v1/pair','/v1/card'):self.reply(404,dict(error='notFound'));return
            if self.path=='/v1/card' and not authorized(self.server.root,self.headers.get('Authorization')):
                self.reply(401,dict(error='unauthorized'));return
            if self.headers.get('Transfer-Encoding') or self.headers.get_content_type()!='application/json':raise CardRejected('invalidRequest')
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=8192:raise CardRejected('invalidRequest')
            raw=self.rfile.read(length)
            if len(raw)!=length:raise CardRejected('invalidRequest')
            body=json.loads(raw)
            if self.path=='/v1/pair':self.reply(200,pair(self.server.root,body));return
            if not self.server.present_lock.acquire(False):raise CardRejected('readerBusy')
            try:
                request,_=checked_card(body);now=time.time()
                self.server.seen={key:value for key,value in self.server.seen.items() if value>now-60}
                if request in self.server.seen:raise CardRejected('duplicateRequest')
                if len(self.server.seen)>=256:raise CardRejected('readerBusy')
                self.server.seen[request]=now
                receipt=present(self.server.store,body)
                self.reply(200,receipt)
            finally:self.server.present_lock.release()
        except CardRejected as error:self.reply(422,dict(error=error.code))
        except (ValueError,UnicodeError,TypeError):self.reply(400,dict(error='invalidRequest'))
        except (OSError,TimeoutError):pass
        except Exception:self.reply(503,dict(error='unavailable'))

def certificate(root):
    cert=root/'certificate.pem';key=root/'key.pem'
    # macOS LibreSSL otherwise defaults to explicit EC parameters. Apple TLS
    # rejects that SPKI encoding before URLSession's certificate-pin callback.
    # Keep good identities stable; migrate only our legacy explicit EC profile.
    profile=root/'certificate-profile.json'
    current=read(profile,{})
    valid=False
    if cert.exists() and key.exists():
        fingerprint=hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
        if current.get('version')==2 and current.get('sha256')==fingerprint:valid=True
        else:
            details=subprocess.check_output(['/usr/bin/openssl','x509','-in',str(cert),'-text','-noout'],text=True,timeout=5)
            valid='ASN1 OID: prime256v1' in details and 'Field Type:' not in details
    if not valid:
        # Generate as a pair in a private staging directory. A failed generation
        # leaves the previous key/cert intact and never publishes a mixed pair.
        import tempfile
        with tempfile.TemporaryDirectory(dir=root,prefix='.tls-') as temporary:
            temporary=Path(temporary);new_cert=temporary/'certificate.pem';new_key=temporary/'key.pem'
            subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:prime256v1',
                            '-pkeyopt','ec_param_enc:named_curve','-sha256','-nodes','-keyout',str(new_key),'-out',str(new_cert),
                            '-days','365','-subj','/CN=Airmai Card'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
            os.chmod(new_key,0o600)
            if cert.exists() or key.exists():
                archive=root/('LegacyTLS-'+str(time.time_ns()));archive.mkdir(mode=0o700)
                for old in (cert,key):
                    if old.exists():old.replace(archive/old.name)
                # Pinned clients must explicitly pair again after key rotation.
                atomic_json(root/'clients.json',[])
            new_key.replace(key);new_cert.replace(cert)
        fingerprint=hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
    atomic_json(profile,dict(version=2,sha256=fingerprint))
    return cert,key,fingerprint

def run(root,runtime,parent,nonce):
    store=Store(root);root=store.root/'PhoneReader';publisher=None;server=None
    stage='starting'
    def finish(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,finish);signal.signal(signal.SIGINT,finish)
    try:
        with (root/'server.lock').open('a+') as instance:
            fcntl.flock(instance,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if read(root/'starting.json',{}).get('nonce')!=nonce:return
            stage='certificate';cert,key,fingerprint=certificate(root)
            stage='tls'
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2;context.load_cert_chain(cert,key)
            stage='listener';server=Server(('0.0.0.0',0),store)
            # Handshake per accepted socket, with timeout, outside accept loop.
            original=server.get_request
            def accept():
                connection,address=original()
                try:return context.wrap_socket(connection,server_side=True),address
                except BaseException:connection.close();raise
            server.get_request=accept
            stage='bonjour'
            publisher=subprocess.Popen([str(Path(runtime)/'helpers/phone-reader-bonjour'),str(server.server_port),fingerprint],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            readable,_,_=select.select([publisher.stdout],[],[],5)
            if not readable or publisher.stdout.readline().strip()!=b'ready':raise RuntimeError()
            atomic_json(root/'server.json',dict(pid=os.getpid(),parent=parent,port=server.server_port,nonce=nonce))
            stage='serving'
            server.timeout=.35
            while True:
                os.kill(parent,0)
                if publisher.poll() is not None:break
                server.handle_request()
    except KeyboardInterrupt:pass
    except Exception as error:atomic_json(root/'failure.json',dict(nonce=nonce,stage=stage,reason=type(error).__name__,component=Path(error.filename).name if isinstance(error,OSError) and error.filename else None,frames=[dict(file=Path(frame.filename).name,line=frame.lineno,function=frame.name) for frame in traceback.extract_tb(error.__traceback__)]))
    finally:
        if publisher:
            publisher.terminate()
            try:publisher.wait(timeout=2)
            except subprocess.TimeoutExpired:publisher.kill();publisher.wait()
        if server:server.server_close()
        if read(root/'server.json',{}).get('nonce')==nonce:(root/'server.json').unlink(missing_ok=True)
        (root/'code.json').unlink(missing_ok=True)
