"""Exercise real CryptoKit verification with a temporary, test-only trust key."""
from pathlib import Path
import hashlib
import json
import platform
import re
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(platform.system()=='Darwin','CryptoKit requires macOS')
class SignedCacheVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        cls.folder=Path(cls.temp.name)
        generator=cls.folder/'fixture'
        subprocess.run(['swiftc',str(ROOT/'Tests/Native/SignedCacheFixture.swift'),'-o',str(generator)],capture_output=True,check=True,timeout=45)
        key=subprocess.check_output([str(generator),str(cls.folder)],text=True,timeout=10).strip()
        source=(ROOT/'Native/SignedCacheVerifier.swift').read_text()
        # No runtime key overrides in production. Only this copied test source
        # trusts the fresh fixture key; no third-party binaries are used.
        source=re.sub(r'(let publisherKeys = \[\s*")[^"]+',lambda m:m[1]+key,source,count=1)
        path=cls.folder/'Verifier.swift';path.write_text(source)
        cls.helper=cls.folder/'verify'
        subprocess.run(['swiftc',str(path),'-o',str(cls.helper)],capture_output=True,check=True,timeout=45)
        cls.valid=(cls.folder/'valid.cache').read_bytes()

    def verify(self,data):
        path=self.folder/'input.cache';path.write_bytes(data)
        return subprocess.run([str(self.helper),str(path)],capture_output=True,text=True,timeout=10)

    def testValidSignatureProducesBoundContentReceipt(self):
        result=self.verify(self.valid);self.assertEqual(result.returncode,0,result.stderr)
        receipt=json.loads(result.stdout);payload=self.valid[:-144]
        self.assertTrue(receipt['verified']);self.assertEqual(receipt['payloadLength'],len(payload))
        self.assertEqual(receipt['sha256'],hashlib.sha256(payload).hexdigest())
        self.assertEqual(receipt['cacheSHA256'],hashlib.sha256(self.valid).hexdigest())

    def testTamperedContentSignatureKeyMagicAndTruncationAreRejected(self):
        for offset in [2,len(self.valid)-144,len(self.valid)-100,len(self.valid)-3]:
            data=bytearray(self.valid);data[offset]^=1
            result=self.verify(data);self.assertNotEqual(result.returncode,0)
            self.assertEqual(result.stdout,'')
        for length in [0,20,143,len(self.valid)-1]:
            self.assertNotEqual(self.verify(self.valid[:length]).returncode,0)

    def testValidSignatureForDifferentTrustedKeyCannotBeRelabeled(self):
        data=bytearray(self.valid);data[-144]=2
        self.assertNotEqual(self.verify(data).returncode,0)


if __name__=='__main__':unittest.main()
