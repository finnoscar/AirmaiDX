from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'Service'))
from storage import Store, DEFAULT_SETTINGS
from controller_compatibility import prepare_input_mods
from controller_devices import game_api_verified
from compatibility import core_signature


class ControllerCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name)/'private')
        self.package = self.store.root/'Games'/('a'*32)/'HDD/Package'
        (self.package/'Mods').mkdir(parents=True)
        self.runtime = Path(self.tmp.name)/'runtime'; self.runtime.mkdir()
        self.api = self.package/'Mods/AquaMai.dll'; self.api.write_bytes(b'checked API')
        self.legacy = self.package/'Mods/ADXHIDIOMod.dll'; self.legacy.write_bytes(b'audited legacy')
        self.disabled = self.legacy.with_name(self.legacy.name+'.airmai-disabled')
        self.game = dict(id='a'*32, packagePath=str(self.package), ready=True, settings=dict(DEFAULT_SETTINGS))
        self.store.update(self.game)
        self.sha = hashlib.sha256(b'audited legacy').hexdigest()
        self.addCleanup(patch.stopall)
        patch('controller_compatibility.LEGACY_INPUT_MODS', {'ADXHIDIOMod.dll':self.sha}).start()
        patch('controller_devices.ADDITIONAL_INPUT_APIS', {hashlib.sha256(b'checked API').hexdigest()}).start()
        (self.runtime/'manifest.json').write_text('{}')
        fingerprint = core_signature(self.package, ignored=('Mods/ADXHIDIOMod.dll',))
        patch('controller_compatibility.REVIEWED_INPUT_STACKS', {fingerprint}).start()

    def testKnownAPIAndLegacyModHaveOneRecoverableRestorePoint(self):
        self.assertEqual(prepare_input_mods(self.store,self.game,self.runtime), ['ADXHIDIOMod.dll'])
        self.assertFalse(self.legacy.exists()); self.assertEqual(self.disabled.read_bytes(),b'audited legacy')
        self.assertEqual(self.api.read_bytes(), b'checked API')
        self.assertEqual(prepare_input_mods(self.store,self.game,self.runtime), [])
        backups = self.store.backups(self.game['id']); self.assertEqual(len(backups),1)
        self.store.restore(self.game['id'],backups[0]['id'])
        self.assertEqual(self.legacy.read_bytes(),b'audited legacy');self.assertFalse(self.disabled.exists())

    def testUnknownModOrUnknownAPINeverAutomaticallyDisabled(self):
        self.legacy.write_bytes(b'unknown build')
        self.assertEqual(prepare_input_mods(self.store,self.game,self.runtime), [])
        self.legacy.write_bytes(b'audited legacy');self.api.write_bytes(b'unknown API')
        self.assertEqual(prepare_input_mods(self.store,self.game,self.runtime), [])
        self.assertTrue(self.legacy.exists());self.assertFalse(self.disabled.exists())

    def testMatchingAPIAndAuditedModCannotAuthorizeAnUnreviewedStack(self):
        changed = self.package / 'UserLibs' / 'RequiredIntegration.dll'
        changed.parent.mkdir()
        changed.write_bytes(b'user-supplied integration, may load legacy controller')
        warnings = []
        self.assertTrue(game_api_verified(self.runtime, self.package))
        self.assertEqual(prepare_input_mods(self.store,self.game,self.runtime,warnings), [])
        self.assertEqual(self.legacy.read_bytes(), b'audited legacy')
        self.assertFalse(self.disabled.exists())
        self.assertIn('未验证当前游戏', warnings[0])

    def testRequiredControllerWithNoOtherGameModIsPreserved(self):
        self.api.unlink()
        with patch('controller_compatibility.game_api_verified', return_value=True):
            self.assertEqual(prepare_input_mods(self.store,self.game,self.runtime), [])
        self.assertTrue(self.legacy.is_file())
        self.assertFalse(self.disabled.exists())

    def testUnknownFileUsingBuiltInHelperNamePreventsDisable(self):
        (self.package/'Mods/AirmaiMouseInput.dll').write_bytes(b'not bundled helper')
        self.assertEqual(prepare_input_mods(self.store,self.game,self.runtime), [])
        self.assertTrue(self.legacy.is_file())

    def testRestoreDoesNotReplaceNewUserMod(self):
        prepare_input_mods(self.store,self.game,self.runtime)
        backup, = self.store.backups(self.game['id'])
        self.legacy.write_bytes(b'new user mod')
        with self.assertRaisesRegex(ValueError, '已有新文件'):
            self.store.restore(self.game['id'],backup['id'])
        self.assertEqual(self.legacy.read_bytes(), b'new user mod')
        self.assertEqual(self.disabled.read_bytes(), b'audited legacy')

    def testOptOutPreservesLegacyMod(self):
        self.game['settings'].update(adxEnabled=False,mouseEnabled=False,hdxEnabled=False)
        self.assertEqual(prepare_input_mods(self.store,self.game,self.runtime), [])
        self.assertTrue(self.legacy.exists())

    def testConflictingPreservedCopyAbortsWithoutChangingOriginal(self):
        self.disabled.write_bytes(b'user copy')
        with self.assertRaises(ValueError):prepare_input_mods(self.store,self.game,self.runtime)
        self.assertEqual(self.legacy.read_bytes(),b'audited legacy')
        self.assertEqual(self.disabled.read_bytes(),b'user copy')

    def testInterruptedDisableRollsBackPreservedCopy(self):
        unlink = Path.unlink
        def fail_once(path,*args,**kwargs):
            if path == self.legacy: raise OSError('simulated failure')
            return unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',fail_once),self.assertRaises(OSError):
            prepare_input_mods(self.store,self.game,self.runtime)
        self.assertEqual(self.legacy.read_bytes(),b'audited legacy');self.assertFalse(self.disabled.exists())

    def testExistingIdenticalDisabledCopyResumes(self):
        self.disabled.write_bytes(b'audited legacy')
        self.assertEqual(prepare_input_mods(self.store,self.game,self.runtime), ['ADXHIDIOMod.dll'])
        self.assertFalse(self.legacy.exists());self.assertEqual(self.disabled.read_bytes(),b'audited legacy')

    def testRenamedAuditedLegacyModIsStillHandledByContent(self):
        renamed=self.legacy.with_name('LegacyController.DLL');self.legacy.rename(renamed)
        self.assertEqual(prepare_input_mods(self.store,self.game,self.runtime),['LegacyController.DLL'])
        self.assertFalse(renamed.exists())
        self.assertEqual(renamed.with_name(renamed.name+'.airmai-disabled').read_bytes(),b'audited legacy')

    def testAPIAdmissionKeepsManifestProfileAndRejectsUnknownDLL(self):
        self.assertTrue(game_api_verified(self.runtime,self.package))
        self.api.write_bytes(b'profile API')
        (self.runtime/'manifest.json').write_text(json.dumps(dict(compatibility_profiles=[dict(fingerprints={'Mods/AquaMai.dll':hashlib.sha256(b'profile API').hexdigest()})])))
        self.assertTrue(game_api_verified(self.runtime,self.package))
        self.api.write_bytes(b'unknown');self.assertFalse(game_api_verified(self.runtime,self.package))
        self.api.unlink();self.assertFalse(game_api_verified(self.runtime,self.package))


if __name__ == '__main__':unittest.main()
