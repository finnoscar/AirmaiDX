"""Phone card session mailbox. Access codes only; no invented card identities."""
from pathlib import Path
import base64
import datetime
import json
import os
import secrets
import struct
import time
import uuid
from storage import atomic_json

EVENT=struct.Struct('<4sHHQQ16s32s')
ACK=struct.Struct('<4sQQ32s')
EPOCH=116444736000000000
NAMES=['AirmaiPhoneReader.cfg','AirmaiPhoneCard.dat','AirmaiPhoneReady.dat','AirmaiPhoneAck.dat']

class CardRejected(ValueError):
    def __init__(self,code):self.code=code;super().__init__(code)

def initialize(drive,session):
    clean(drive)
    token=secrets.token_bytes(32)
    (drive/NAMES[0]).write_bytes(b'AMCP'+struct.pack('<I',1)+token);os.chmod(drive/NAMES[0],0o600)
    atomic_json(session/'phone-reader-private.json',dict(token=token.hex()))

def clean(drive):
    for name in NAMES:(drive/name).unlink(missing_ok=True)

def checked_card(body,now=None):
    now=time.time() if now is None else now
    if not isinstance(body,dict) or type(body.get('version')) is not int or body['version']!=1:raise CardRejected('invalidCard')
    try:
        request=str(uuid.UUID(body['requestID']))
        stamp=datetime.datetime.fromisoformat(body['issuedAt'].replace('Z','+00:00'))
        if stamp.tzinfo is None or abs(now-stamp.timestamp())>30:raise ValueError()
        card=body['card']
        if not isinstance(card,dict) or card.get('technology') not in ('FeliCa','MIFARE','ISO 7816'):raise ValueError()
        raw=base64.b64decode(card['identifier'],validate=True)
        if (card['technology']=='FeliCa' and len(raw)!=8) or not 4<=len(raw)<=10:raise ValueError()
        code=card.get('accessCode')
        if not code:raise CardRejected('accessCodeRequired')
        if not isinstance(code,str) or len(code)!=20 or any(c not in '0123456789' for c in code):raise ValueError()
        return request,bytes.fromhex(code)
    except CardRejected:raise
    except (KeyError,TypeError,ValueError,AttributeError):raise CardRejected('invalidCard') from None

def active_reader(store):
    from runtime import session_status
    for game in store.library():
        if not game['settings'].get('phoneReaderEnabled'):continue
        state=session_status(store,game)
        if not state['running']:continue
        root=store.game_root(game);session=Path(state['sessionPath'])
        if not session.resolve().is_relative_to(root/'Sessions'):continue
        try:
            token=bytes.fromhex(json.loads((session/'phone-reader-private.json').read_text())['token'])
            drive=root/'Prefix/drive_c';record=(drive/'AirmaiPhoneReady.dat').read_bytes()
            magic,_,stamp,actual=ACK.unpack(record)
            now=int(time.time()*10000000)+EPOCH
            if len(token)==32 and secrets.compare_digest(actual,token) and magic==b'AMCR' and 0<=now-stamp<20000000:
                return drive,token
        except (OSError,ValueError,KeyError,struct.error):continue
    return None

def present(store,body):
    request,code=checked_card(body)
    active=active_reader(store)
    if active is None:raise CardRejected('readerNotReady')
    drive,token=active;target=drive/'AirmaiPhoneCard.dat'
    if target.exists() and time.time()-target.stat().st_mtime<3:raise CardRejected('readerBusy')
    sequence=time.time_ns()//1000;expires=int((time.time()+3)*10000000)+EPOCH
    temporary=target.with_suffix('.tmp')
    temporary.write_bytes(EVENT.pack(b'AMCE',1,1,sequence,expires,code+b'\0'*6,token))
    os.chmod(temporary,0o600);temporary.replace(target)
    deadline=time.monotonic()+2.2
    while time.monotonic()<deadline:
        try:
            magic,seq,_,actual=ACK.unpack((drive/'AirmaiPhoneAck.dat').read_bytes())
            if magic==b'AMCA' and seq==sequence and secrets.compare_digest(actual,token):
                return dict(requestID=request,status='presented')
        except (OSError,struct.error):pass
        time.sleep(.03)
    # A queued response is a short-lived presentation, never a login claim.
    return dict(requestID=request,status='queued')
