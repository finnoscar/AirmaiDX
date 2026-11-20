"""Real HDX reader via native serial and a local PTY for Wine COM1.

Valid reader frames/responses are forwarded unchanged. No invented card IDs,
auto login or response fabrication. Diagnostics contain command numbers/counts,
never card UIDs, access codes, keys or complete payloads.
"""
from pathlib import Path
import argparse,collections,json,os,pty,select,signal,termios,time,tty
from hdx_aux_probe import AuxPort,Frames,escape,nfc_request,transact

NFC_NORMAL={0x30,0x32,0x40,0x41,0x42,0x43,0x50,0x52,0x54,0x55,0x62,0x71}

def read_ready(fd):
    # macOS PTYs can report readiness for a terminal-state change while a
    # subsequent nonblocking read legitimately has no bytes (EAGAIN).
    try:return os.read(fd,4096)
    except (BlockingIOError,InterruptedError):return None

def allowed(body):
    if len(body)<5 or body[0]!=len(body) or body[4]!=len(body)-5:return False
    address,command=body[1],body[3]
    if address==8:return command in {0xf0,0xf5,0x81}
    if address!=0 or command not in NFC_NORMAL:return False
    if command==0x71:
        # SG encapsulation has IDm[8], followed directly by the FeliCa opcode.
        payload=body[5:]
        return len(payload)>=9 and payload[8] in {0x00,0x02,0x04,0x06,0x0c,0xa4}
    return True


def run(private_state,output):
    output.mkdir(parents=True,exist_ok=False);os.chmod(output,0o700)
    running=True
    def stop(*_):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    counts=collections.Counter();commands=collections.Counter();blocked=collections.Counter()
    error=None;master=slave=None
    with AuxPort('reader') as port:
        version=transact(port,'reader',nfc_request(0x30),0x30)
        if not version['matching_responses']:raise RuntimeError('Real HDX reader did not answer version request')
        try:
            master,slave=pty.openpty();tty.setraw(slave)
            a=termios.tcgetattr(slave);a[2]|=termios.CLOCAL;a[2]&=~termios.HUPCL;a[4]=a[5]=termios.B115200;termios.tcsetattr(slave,termios.TCSANOW,a)
            os.set_blocking(master,False);os.chmod(os.ttyname(slave),0o600)
            private_state.write_text(json.dumps({'ready':True,'pid':os.getpid(),'pty_slave':os.ttyname(slave),'role':'HDX card reader channel','reader_version_response_verified':True},indent=2)+'\n');os.chmod(private_state,0o600)
            print(json.dumps({'native_reader_bridge':'ready','real_version_response_verified':True,'no_card_identifiers_logged':True}),flush=True)
            requests=Frames('reader');responses=Frames('reader');to_reader=bytearray();to_wine=bytearray();last_status=0
            while running:
                readable,writable,_=select.select([master,port.fd],([master] if to_wine else [])+([port.fd] if to_reader else []),[],.005)
                if master in readable:
                    chunk=read_ready(master)
                    if chunk is None:counts['pty_empty_read_notifications']+=1
                    counts['wine_request_bytes']+=len(chunk or b'')
                    for frame in requests.feed(chunk or b''):
                        key='%02x:%02x'%(frame[1],frame[3]) if len(frame)>=4 else 'invalid'
                        if allowed(frame):
                            to_reader.extend(escape(frame));commands[key]+=1;counts['forwarded_requests']+=1
                        else:
                            blocked[key]+=1;counts['blocked_requests']+=1
                if port.fd in readable:
                    chunk=read_ready(port.fd)
                    if chunk==b'':raise RuntimeError('Real HDX reader disconnected')
                    counts['real_response_bytes']+=len(chunk or b'')
                    for frame in responses.feed(chunk or b''):
                        to_wine.extend(escape(frame));counts['forwarded_responses']+=1
                if len(to_reader)>65536 or len(to_wine)>65536:raise RuntimeError('Reader forwarding queue limit exceeded')
                for fd,buffer,name in [(port.fd,to_reader,'real_request_bytes_written'),(master,to_wine,'wine_response_bytes_written')]:
                    if buffer and fd in writable:
                        try:n=os.write(fd,buffer);del buffer[:n];counts[name]+=n
                        except BlockingIOError:pass
                now=time.monotonic()
                if now-last_status>=1:
                    state=dict(counts,ready=True,request_commands=dict(commands),blocked_commands=dict(blocked),
                               pending_to_reader=len(to_reader),pending_to_wine=len(to_wine),
                               card_payloads_logged=False,firmware_or_card_write_commands_allowed=False)
                    temp=output/'status.tmp';temp.write_text(json.dumps(state,indent=2)+'\n');temp.replace(output/'status.json');last_status=now
        except BaseException as exc:
            error=type(exc).__name__+': '+str(exc);raise
        finally:
            private_state.unlink(missing_ok=True)
            for fd in [master,slave]:
                if fd is not None:os.close(fd)
            (output/'status.json').write_text(json.dumps(dict(counts,stopped=True,error=error,request_commands=dict(commands),blocked_commands=dict(blocked),card_payloads_logged=False),indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--private-state',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();run(a.private_state,a.output)
