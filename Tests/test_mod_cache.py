"""Offline cache activation, failure reporting and transaction regression tests."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Service'))
from storage import Store, DEFAULT_SETTINGS
from mod_cache import activate_signed_cache
from runtime import startup_failure


class ModCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'private')
        self.package=self.store.root/'Games'/('a'*32)/'HDD/Package'
        (self.package/'Mods').mkdir(parents=True);(self.package/'LocalAssets').mkdir()
        self.loader=self.package/'Mods/MuMod.dll';self.loader.write_bytes(b'loader')
        self.payload=b'MZ'+b'fixture'*20;self.data=self.payload+b'fake-signature-trailer'
        self.cache=self.package/'LocalAssets/MuMod.cache';self.cache.write_bytes(self.data)
        self.game=dict(id='a'*32,packagePath=str(self.package),sourcePath='/source',ready=False,settings=dict(DEFAULT_SETTINGS))
        self.store.update(self.game)
        self.addCleanup(patch.stopall)
        patch('mod_cache.SUPPORTED_LOADERS',{hashlib.sha256(b'loader').hexdigest()}).start()
        result=dict(verified=True,payloadLength=len(self.payload),sha256=hashlib.sha256(self.payload).hexdigest(),cacheSHA256=hashlib.sha256(self.data).hexdigest())
        self.run=patch('mod_cache.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(result))).start()
        image=MagicMock();image.__enter__.return_value.net.mdtables.Assembly.rows=[SimpleNamespace(Name='AquaMai')]
        patch('mod_cache.dnfile.dnPE',return_value=image).start()

    def activate(self):return activate_signed_cache(self.store,self.game,Path('/verifier'))

    def testActivationCanBeRestoredAsOneTransaction(self):
        self.assertTrue(self.activate())
        self.assertFalse(self.loader.exists())
        target=self.package/'Mods/AquaMai.dll'
        self.assertEqual(target.read_bytes(),self.payload)
        self.assertEqual((self.package/'Mods/MuMod.dll.airmai-disabled').read_bytes(),b'loader')
        self.assertEqual(self.cache.read_bytes(),self.data)
        self.assertIsNone(self.activate())
        self.store.restore(self.game['id'],self.store.backups(self.game['id'])[0]['id'])
        self.assertEqual(self.loader.read_bytes(),b'loader');self.assertFalse(target.exists())
        self.assertFalse((self.package/'Mods/MuMod.dll.airmai-disabled').exists())

    def testInvalidSignatureAndMismatchedReceiptNeverModifyMods(self):
        for result in [SimpleNamespace(returncode=1,stdout=''),SimpleNamespace(returncode=0,stdout='{"verified":true,"payloadLength":2,"cacheSHA256":"wrong"}')]:
            self.run.return_value=result
            with self.assertRaises(ValueError):self.activate()
            self.assertEqual(self.loader.read_bytes(),b'loader')
            self.assertFalse((self.package/'Mods/AquaMai.dll').exists())

    def testNoSilentNetworkWhenMissingCache(self):
        self.cache.unlink()
        with self.assertRaisesRegex(ValueError,'缓存'):self.activate()
        self.run.assert_not_called()

    def testUnsupportedLoadersAndEscapingCachePathsRejected(self):
        self.loader.write_bytes(b'unknown')
        with self.assertRaisesRegex(ValueError,'尚未验证'):self.activate()
        self.loader.write_bytes(b'loader')
        for name in ['../outside','/tmp/cache','C:/cache']:
            (self.package/'MuMod.toml').write_text('CachePath = '+json.dumps(name))
            with self.assertRaises(ValueError):self.activate()
        self.run.assert_not_called()

    def testPartialWriteRollsBackBothLoaders(self):
        replace=Path.replace
        def fail(path,target):
            if Path(target).name=='AquaMai.dll':raise OSError('simulated full disk')
            return replace(path,target)
        with patch.object(Path,'replace',fail):
            with self.assertRaises(OSError):self.activate()
        self.assertEqual(self.loader.read_bytes(),b'loader')
        self.assertFalse((self.package/'Mods/MuMod.dll.airmai-disabled').exists())

    def testExistingAquaMaiIsPreserved(self):
        target=self.package/'Mods/AquaMai.dll';target.write_bytes(b'existing')
        self.assertIsNone(self.activate());self.run.assert_not_called()
        self.assertEqual(target.read_bytes(),b'existing')

    def testInterruptedActivationResumesWithoutDuplicateLoaders(self):
        disabled=self.package/'Mods/MuMod.dll.airmai-disabled'
        target=self.package/'Mods/AquaMai.dll'
        for phase in ['backupOnly','loaderRemoved','bothPresent']:
            disabled.write_bytes(b'loader')
            self.loader.write_bytes(b'loader')
            target.unlink(missing_ok=True)
            if phase=='loaderRemoved':self.loader.unlink()
            if phase=='bothPresent':target.write_bytes(self.payload)
            self.assertTrue(self.activate())
            self.assertFalse(self.loader.exists())
            self.assertEqual(target.read_bytes(),self.payload)
            self.assertEqual(disabled.read_bytes(),b'loader')

    def testBlackScreenFailuresAreActionable(self):
        self.assertIn('MuMod',startup_failure('Failed to load from cache: BCryptOpenAlgorithmProvider failed: 0xC0000002'))
        self.assertIn('AMDaemon',startup_failure('System.DllNotFoundException: amdaemon_api'))
        self.assertIsNone(startup_failure('Metal HUD initialized; 144 fps'))
        self.assertIn('0xC0000409',startup_failure('{"game_exit_code":3221226505}'))


if __name__=='__main__':unittest.main()
