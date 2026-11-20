"""Metadata-only queries to verified HDX LED and reader CDC interfaces.

Commands are local-game LED GetBoardInfo and documented SG NFC version reads.
No RF polling, card reads/writes, reset, boot, EEPROM, firmware or debug calls.
"""
from pathlib import Path
import json
import os
import select
import stat
import sys
import termios
import time
from hdx_touch_probe import usb_device_tree, hdx_device, registry_children

ROLES = {'led': ('HDX LED channel', 6, 7),
         'reader': ('HDX card reader channel', 8, 9)}


def resolve(role, tree=None):
    label, control, data = ROLES[role]
    device=hdx_device(usb_device_tree() if tree is None else tree)
    children=registry_children(device)
    if sum(c.get('bInterfaceNumber')==control and c.get('bInterfaceClass')==2
           and c.get('IORegistryEntryName')==label for c in children)!=1:
        raise RuntimeError('Verified interface role absent')
    matches=[c for c in children if c.get('bInterfaceNumber')==data and c.get('bInterfaceClass')==10]
    if len(matches)!=1:raise RuntimeError('Verified CDC data interface absent')
    nodes=[]
    def ports(n):
        if n.get('IOCalloutDevice'):nodes.append(n['IOCalloutDevice'])
        for c in registry_children(n):ports(c)
    ports(matches[0])
    if len(nodes)!=1 or not isinstance(nodes[0],str) or not nodes[0].startswith('/dev/cu.usbmodem') or not stat.S_ISCHR(os.stat(nodes[0]).st_mode):
        raise RuntimeError('Expected a single callout character device')
    return nodes[0]


class AuxPort:
    def __init__(self,role):self.role=role
    def __enter__(self):
        self.node=resolve(self.role)
        self.fd=os.open(self.node,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
        try:
            self.original=termios.tcgetattr(self.fd)
            a=termios.tcgetattr(self.fd)
            a[0]=a[1]=a[3]=0
            a[2]=(a[2]&~(termios.CSIZE|termios.PARENB|termios.CSTOPB|termios.HUPCL))|termios.CS8|termios.CREAD|termios.CLOCAL
            if hasattr(termios,'CRTSCTS'):a[2]&=~termios.CRTSCTS
            a[4]=a[5]=termios.B115200
            a[6][termios.VMIN]=a[6][termios.VTIME]=0
            termios.tcsetattr(self.fd,termios.TCSANOW,a)
        except BaseException:
            os.close(self.fd);raise
        return self
    def __exit__(self,*_):
        try:termios.tcsetattr(self.fd,termios.TCSANOW,self.original)
        except (OSError,termios.error):pass
        finally:os.close(self.fd)


def escape(body):
    result=bytearray([0xe0])
    for b in body+bytes([sum(body)&255]):
        if b in (0xd0,0xe0):result.extend((0xd0,b-1))
        else:result.append(b)
    return bytes(result)


def led_request(command,payload=b''):
    return escape(bytes([17,1,1+len(payload),command])+payload)


def nfc_request(command,sequence=1,payload=b''):
    return escape(bytes([5+len(payload),0,sequence,command,len(payload)])+payload)


class Frames:
    def __init__(self,kind):self.kind=kind;self.data=None;self.escaped=False
    def feed(self,chunk):
        frames=[]
        for b in chunk:
            if b==0xe0 and not self.escaped:
                self.data=bytearray();continue
            if self.data is None:continue
            if self.escaped:b=(b+1)&255;self.escaped=False
            elif b==0xd0:self.escaped=True;continue
            self.data.append(b)
            expected=None
            if self.kind=='reader' and self.data:expected=self.data[0]+1
            if self.kind=='led' and len(self.data)>=3:expected=self.data[2]+4
            if expected and (expected<5 or expected>256):self.data=None;continue
            if expected and len(self.data)==expected:
                if sum(self.data[:-1])&255==self.data[-1]:frames.append(bytes(self.data[:-1]))
                self.data=None
        return frames


def transact(port,kind,request,command):
    parser=Frames(kind)
    if os.write(port.fd,request)!=len(request):raise RuntimeError('Short metadata query')
    frames=[];end=time.monotonic()+1
    while time.monotonic()<end:
        ready,_,_=select.select([port.fd],[],[],.1)
        if ready:
            chunk=os.read(port.fd,1024)
            if not chunk:break
            for f in parser.feed(chunk):
                # Persist only matching metadata responses; no unsolicited card data.
                if kind=='reader' and len(f)>=6 and f[1]==0 and f[3]==command:
                    frames.append({'command':command,'status':f[4],'metadata_hex':f[6:].hex(),
                                   'metadata_ascii':f[6:].decode('ascii','replace')})
                elif kind=='led' and len(f)>=6 and f[4]==command:
                    frames.append({'command':command,'status':f[3],'report':f[5],
                                   'metadata_hex':f[6:].hex(),'metadata_ascii':f[6:].decode('ascii','replace')})
        if frames:break
    return {'command':command,'request_hex':request.hex(),'matching_responses':frames}


def main():
    root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=False)
    result={'vid':'0CA3','pid':'0021','baud':115200,'format':'8N1',
            'metadata_only':True,'card_polling':False,'card_data_read':False,
            'reset_or_firmware_commands':False,'LED_colors_written':False}
    for role in ['led','reader']:
        print('Opening verified HDX '+role+' interface for metadata only.',flush=True)
        with AuxPort(role) as port:
            queries=[0xf0] if role=='led' else [0x30,0x32]
            result[role]=[transact(port,role,led_request(c) if role=='led' else nfc_request(c),c) for c in queries]
        print(json.dumps({role:result[role]},ensure_ascii=False),flush=True)
    (root/'metadata-only.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
