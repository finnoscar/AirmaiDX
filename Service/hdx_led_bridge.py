"""Native HDX LED backend: authenticated loopback, normal RGB operations only."""
from pathlib import Path
import argparse,json,os,secrets,select,signal,socket,struct,time
from hdx_aux_probe import AuxPort,Frames,led_request,transact

LENGTHS={0x31:4,0x32:7,0x33:7,0x3c:0}

def validate_command(data):
    if not data or data[0] not in LENGTHS or len(data)!=LENGTHS[data[0]]+1:
        raise ValueError('Unsupported LED operation')
    if data[0]==0x31 and data[1]>=8:raise ValueError('Only eight verified button channels')
    if data[0] in (0x32,0x33) and not (0<=data[1]<data[2]<=8 and data[3]==0):
        raise ValueError('Invalid verified RGB group')
    return led_request(data[0],data[1:])


def run(config,output):
    output.mkdir(parents=True,exist_ok=False);os.chmod(output,0o700)
    token=secrets.token_bytes(32);running=True
    def stop(*_):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    counts={'commands':0,'serial_bytes_written':0,'response_frames':0,'connections':0,'invalid_commands':0}
    client=None;incoming=bytearray();outgoing=bytearray();last_status=0;last_rx=0;error=None
    with AuxPort('led') as led,socket.socket() as listener:
        info=transact(led,'led',led_request(0xf0),0xf0)
        if not any(r['metadata_hex'].startswith('31353037302d3034') for r in info['matching_responses']):
            raise RuntimeError('Verified LED board protocol not present')
        reset=transact(led,'led',led_request(0x10),0x10)
        if not reset['matching_responses']:raise RuntimeError('Normal LED reset not acknowledged')
        def off():
            for c,p in [(0x32,bytes([0,8,0,0,0,0,0])),(0x3c,b'')]:
                payload=led_request(c,p)
                try:os.write(led.fd,payload)
                except OSError:pass
        off()
        listener.bind(('127.0.0.1',59185));listener.listen(1);listener.setblocking(False)
        config.write_text('AIRMAI_HDX_LED_V1\n59185\n'+token.hex()+'\n');os.chmod(config,0o600)
        parser=Frames('led')
        print(json.dumps({'HDX_LED_bridge':'ready','normal_volatile_reset_acknowledged':True,'loopback_only':True,'brightness_scaling':False}),flush=True)
        try:
            while running:
                readers=[listener,led.fd]+([client] if client else [])
                readable,writable,_=select.select(readers,[led.fd] if outgoing else [],[],.01)
                if led.fd in readable:
                    data=os.read(led.fd,2048)
                    if not data:raise RuntimeError('LED device disconnected')
                    frames=parser.feed(data);counts['response_frames']+=len(frames)
                    if frames:last_rx=time.monotonic()
                if listener in readable:
                    c,_=listener.accept();c.settimeout(.3);auth=bytearray()
                    try:
                        while len(auth)<32:
                            d=c.recv(32-len(auth))
                            if not d:break
                            auth.extend(d)
                        if len(auth)!=32 or not secrets.compare_digest(bytes(auth),token):c.close()
                        else:
                            if client:client.close()
                            client=c;c.sendall(b'LED1');c.setblocking(False)
                            incoming.clear();outgoing.clear();counts['connections']+=1
                    except OSError:c.close()
                if client and client in readable:
                    data=client.recv(4096)
                    if not data:
                        client.close();client=None;incoming.clear();outgoing.clear();off()
                    else:
                        incoming.extend(data)
                        while len(incoming)>=2:
                            n=struct.unpack_from('<H',incoming)[0]
                            if n not in (1,5,8):raise ValueError('Invalid LED message length')
                            if len(incoming)<2+n:break
                            command=bytes(incoming[2:2+n]);del incoming[:2+n]
                            encoded=validate_command(command)
                            if len(outgoing)+len(encoded)>65536:raise RuntimeError('LED output queue overflow')
                            outgoing.extend(encoded);counts['commands']+=1
                if outgoing and led.fd in writable:
                    try:
                        n=os.write(led.fd,outgoing);del outgoing[:n];counts['serial_bytes_written']+=n
                    except BlockingIOError:pass
                now=time.monotonic()
                if now-last_status>=1:
                    state=dict(counts,native_port_open=True,client_connected=client is not None,
                               pending_serial_bytes=len(outgoing),last_response_age_seconds=round(now-last_rx,3) if last_rx else None,
                               normal_LED_commands_only=True,firmware_or_EEPROM_writes=False)
                    temp=output/'status.tmp';temp.write_text(json.dumps(state,indent=2)+'\n');temp.replace(output/'status.json');last_status=now
        except BaseException as exc:
            error=type(exc).__name__+': '+str(exc);raise
        finally:
            off()
            if client:client.close()
            config.unlink(missing_ok=True)
            (output/'status.json').write_text(json.dumps(dict(counts,stopped=True,error=error),indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();run(a.config,a.output)
