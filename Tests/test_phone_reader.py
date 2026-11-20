"""Isolated pairing/TLS and native-mailbox tests. Never touches a user game."""
from pathlib import Path
import base64, datetime, hashlib, http.client, json, os, secrets, ssl, struct, sys, tempfile, threading, time, unittest, uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Service'))
from storage import Store, atomic_json
import phone_reader_server as server
import phone_cards as cards

def presentation():
    return dict(version=1,requestID=str(uuid.uuid4()),issuedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                card=dict(technology='FeliCa',identifier=base64.b64encode(bytes(range(8))).decode(),accessCode='01234567890123456789'))

class PhoneReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name));self.root=self.store.root/'PhoneReader';self.root.mkdir()
    def tearDown(self):self.temp.cleanup()
    def code(self,**changes):
        state=dict(code='001234',expires=time.time()+120,used=False,attempts=0);state.update(changes);atomic_json(self.root/'code.json',state)
    def testPairingCodeIsSingleUseAndOnlyHashIsSaved(self):
        self.code();reply=server.pair(self.root,dict(code='001234',deviceName='iPhone'))
        self.assertEqual(len(reply['token']),64);self.assertTrue(server.authorized(self.root,'Bearer '+reply['token']))
        self.assertNotIn(reply['token'],(self.root/'clients.json').read_text());self.assertNotIn('001234',(self.root/'code.json').read_text())
        with self.assertRaisesRegex(cards.CardRejected,'expiredCode'):server.pair(self.root,dict(code='001234',deviceName='iPhone'))
        self.assertFalse(server.authorized(self.root,'Bearer '+'a'*64))
    def testExpiryAndFiveWrongGuessesBlockPairing(self):
        self.code(expires=time.time()-1)
        with self.assertRaisesRegex(cards.CardRejected,'expiredCode'):server.pair(self.root,dict(code='001234',deviceName='iPhone'))
        self.code()
        for _ in range(5):
            with self.assertRaisesRegex(cards.CardRejected,'invalidCode'):server.pair(self.root,dict(code='991234',deviceName='iPhone'))
        with self.assertRaisesRegex(cards.CardRejected,'expiredCode'):server.pair(self.root,dict(code='001234',deviceName='iPhone'))
    def testCardIdentityFreshnessAndBCDValidate(self):
        body=presentation();request,bcd=cards.checked_card(body)
        self.assertEqual(request,body['requestID']);self.assertEqual(bcd,bytes.fromhex('01234567890123456789'))
        body['card'].pop('accessCode')
        with self.assertRaisesRegex(cards.CardRejected,'accessCodeRequired'):cards.checked_card(body)
        for mutate in [lambda b:b.update(issuedAt='2020-01-01T00:00:00Z'),lambda b:b.update(requestID='bad'),
                       lambda b:b['card'].update(accessCode='１２３４５６７８９０１２３４５６７８９０'),lambda b:b['card'].update(identifier='bad')]:
            body=presentation();mutate(body)
            with self.assertRaises(cards.CardRejected):cards.checked_card(body)
    def testSessionMailboxExpiresAndRequiresMatchingNativeReceipt(self):
        drive=self.store.root/'drive';session=self.store.root/'session';drive.mkdir();session.mkdir();cards.initialize(drive,session)
        cfg=(drive/'AirmaiPhoneReader.cfg').read_bytes();self.assertEqual(cfg[:8],b'AMCP\1\0\0\0');self.assertEqual(len(cfg),40)
        def native_receiver():
            deadline=time.time()+2
            while time.time()<deadline:
                path=drive/'AirmaiPhoneCard.dat'
                if path.exists():
                    data=path.read_bytes()
                    if len(data)==cards.EVENT.size:
                        magic,version,kind,seq,expires,card,token=cards.EVENT.unpack(data)
                        self.assertEqual(magic,b'AMCE');self.assertEqual(card[:10],bytes.fromhex('01234567890123456789'))
                        self.assertGreater(expires,int(time.time()*10000000)+cards.EPOCH)
                        (drive/'AirmaiPhoneAck.dat').write_bytes(cards.ACK.pack(b'AMCA',seq,0,b'x'*32))
                        time.sleep(.08)
                        (drive/'AirmaiPhoneAck.dat').write_bytes(cards.ACK.pack(b'AMCA',seq,0,token));return
                time.sleep(.01)
        thread=threading.Thread(target=native_receiver);thread.start()
        with patch.object(cards,'active_reader',return_value=(drive,cfg[8:])):receipt=cards.present(self.store,presentation())
        thread.join();self.assertEqual(receipt['status'],'presented');cards.clean(drive)
        self.assertEqual(list(drive.iterdir()),[])
    def testNoGameReaderDoesNotQueueCard(self):
        with self.assertRaisesRegex(cards.CardRejected,'readerNotReady'):cards.present(self.store,presentation())
    def testTLSHttpPairAuthAndReplay(self):
        cert,key,pin=server.certificate(self.root)
        self.assertEqual(pin,hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest())
        http=server.Server(('127.0.0.1',0),self.store)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key);http.socket=context.wrap_socket(http.socket,server_side=True)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        def post(path,body,token=None):
            # Test trusts only this isolated generated cert, not global trust.
            trust=ssl.create_default_context(cafile=str(cert));trust.check_hostname=False
            connection=http_client_factory(http.server_port,trust)
            headers={'Content-Type':'application/json'}
            if token:headers['Authorization']='Bearer '+token
            connection.request('POST',path,json.dumps(body),headers);response=connection.getresponse();result=response.status,json.loads(response.read());connection.close();return result
        def http_client_factory(port,trust):return __import__('http.client',fromlist=['HTTPSConnection']).HTTPSConnection('127.0.0.1',port,context=trust,timeout=3)
        try:
            self.code();status,reply=post('/v1/pair',dict(code='001234',deviceName='iPhone'));self.assertEqual(status,200)
            body=presentation();self.assertEqual(post('/v1/card',body)[0],401)
            with patch.object(server,'present',side_effect=lambda _,b:dict(requestID=b['requestID'],status='presented')):
                self.assertEqual(post('/v1/card',body,reply['token'])[1]['status'],'presented')
                self.assertEqual(post('/v1/card',body,reply['token'])[1]['error'],'duplicateRequest')
            with self.assertRaises(ssl.SSLError):
                connection=__import__('http.client',fromlist=['HTTPSConnection']).HTTPSConnection('127.0.0.1',http.server_port,timeout=3)
                connection.request('POST','/v1/pair')
        finally:http.shutdown();http.server_close();thread.join()

if __name__=='__main__':unittest.main()

class NativePhoneReaderTests(unittest.TestCase):
    def testNativeAccessCodeMailboxAndAPI(self):
        import subprocess
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            executable=Path(temporary)/'reader-test'
            result=subprocess.run(['/usr/bin/clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(root/'Tests/Native/PhoneReaderStub'),str(root/'Tests/Native/PhoneReaderTests.c'),'-o',str(executable)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(executable)],cwd=temporary,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('native reader checks passed',result.stdout)

@unittest.skipUnless(sys.platform=='darwin','Apple URLSession integration')
class AppleTLSCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess
        companion=os.environ.get('AIRMAIDX_CARD_COMPANION')
        if not companion:
            raise unittest.SkipTest('Set AIRMAIDX_CARD_COMPANION to test the standalone card companion.')
        ios=Path(companion)
        cls.build=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.build.cleanup)
        cls.client=Path(cls.build.name)/'apple-client'
        root=Path(__file__).resolve().parents[1]
        subprocess.run(['/usr/bin/swiftc','-parse-as-library',str(root/'Tests/Native/PhoneTLSClient.swift'),
            str(ios/'App/Services/MacConnection.swift'),str(ios/'App/Services/KeychainStore.swift'),str(ios/'Sources/AirmaiCardCore/Pairing.swift'),
            str(ios/'Sources/AirmaiCardCore/CardRecord.swift'),'-o',str(cls.client)],check=True,capture_output=True)
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.root=self.store.root/'PhoneReader';self.root.mkdir()
    def tearDown(self):self.temp.cleanup()
    def apple_pair(self,pin=None):
        import subprocess
        cert,key,actual=server.certificate(self.root)
        atomic_json(self.root/'code.json',dict(code='001234',expires=time.time()+120,attempts=0,used=False))
        http=server.Server(('127.0.0.1',0),self.store)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key);http.socket=context.wrap_socket(http.socket,server_side=True)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        try:return subprocess.run([str(self.client),str(http.server_port),pin or actual,'test'],capture_output=True,text=True,timeout=15)
        finally:http.shutdown();http.server_close();thread.join()
    def testAppleURLSessionCanPairAndStableIdentityIsPreserved(self):
        result=self.apple_pair();self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        first=server.certificate(self.root)[2];second=server.certificate(self.root)[2]
        self.assertEqual(first,second);self.assertEqual(len(server.read(self.root/'clients.json',[])),1)
    def testAppleClientRejectsWrongCertificateBeforeSendingCode(self):
        result=self.apple_pair(pin='0'*64);self.assertNotEqual(result.returncode,0)
        self.assertEqual(server.read(self.root/'code.json',{})['attempts'],0)
        self.assertEqual(server.read(self.root/'clients.json',[]),[])
    def testLegacyExplicitCurveMigratesAndPairsUsingAppleTLS(self):
        import subprocess
        cert=self.root/'certificate.pem';key=self.root/'key.pem'
        subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','ec','-pkeyopt','ec_paramgen_curve:prime256v1',
                        '-pkeyopt','ec_param_enc:explicit','-nodes','-keyout',str(key),'-out',str(cert),'-days','365',
                        '-subj','/CN=Airmai Card'],check=True,capture_output=True)
        before=hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
        atomic_json(self.root/'clients.json',[dict(id='old',name='old',hash='not-a-real-credential')])
        _,_,after=server.certificate(self.root)
        self.assertNotEqual(before,after);self.assertEqual(server.read(self.root/'clients.json',[]),[])
        self.assertEqual(len(list(self.root.glob('LegacyTLS-*'))),1)
        result=self.apple_pair();self.assertEqual(result.returncode,0,result.stdout+result.stderr)

class PhoneDeviceManagementTests(unittest.TestCase):
    def testRemovingOnePhoneRevokesOnlyItsTokenAndPreservesOtherPhone(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(temp);root=store.root/'PhoneReader';root.mkdir()
            first=str(uuid.uuid4());second=str(uuid.uuid4());a='a'*64;b='b'*64
            atomic_json(root/'clients.json',[dict(id=first,name='A',hash=hashlib.sha256(a.encode()).hexdigest()),dict(id=second,name='B',hash=hashlib.sha256(b.encode()).hexdigest())])
            result=server.forget(store,first)
            self.assertEqual([x['id'] for x in result['clients']],[second])
            self.assertFalse(server.authorized(root,'Bearer '+a));self.assertTrue(server.authorized(root,'Bearer '+b))
            with self.assertRaises(ValueError):server.forget(store,'../invalid')
            self.assertTrue(server.authorized(root,'Bearer '+b))

class PhoneStartupDiagnosticsTests(unittest.TestCase):
    def testTLSFailureHappensBeforeListenerAndDoesNotBlameNetworkPermission(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(temp);root=store.root/'PhoneReader';root.mkdir()
            atomic_json(root/'starting.json',dict(nonce='startup-check'))
            with patch.object(server,'certificate',return_value=(root/'cert',root/'key','0'*64)), \
                 patch.object(server.ssl,'SSLContext',side_effect=FileNotFoundError()), \
                 patch.object(server,'Server') as listener, patch.object(server.subprocess,'Popen') as publisher:
                server.run(store.root,Path(temp),100,'startup-check')
            failure=server.read(root/'failure.json',{})
            self.assertEqual(failure['stage'],'tls')
            listener.assert_not_called();publisher.assert_not_called()

    def testFailureMessageMatchesStartupStage(self):
        for stage, expected, network in [('tls','TLS',False),('bonjour','Mac 的本地网络权限',True),('listener','诊断',False)]:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                store=Store(temp);root=store.root/'PhoneReader'
                def failed_launch(args,**kwargs):
                    atomic_json(root/'failure.json',dict(nonce=args[-1],stage=stage,reason='test'))
                with patch.object(server,'live',return_value={}),patch.object(server.subprocess,'Popen',side_effect=failed_launch):
                    with self.assertRaises(ValueError) as caught:server.start(store,Path(temp),100)
                self.assertIn(expected,str(caught.exception))
                self.assertEqual('本地网络权限' in str(caught.exception),network)
