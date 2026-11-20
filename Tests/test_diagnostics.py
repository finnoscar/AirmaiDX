from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Service'))
from storage import Store
from diagnostics import collect, redact, PER_FILE


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary.name) / 'private')
        self.game = dict(id='a' * 32, packagePath=str(self.store.root / 'Games' / ('a' * 32) / 'HDD/Package'),
                         sourcePath='/example/private-source', settings={})
        self.root = self.store.game_root(self.game)
        self.package = Path(self.game['packagePath']); self.package.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def testLatestSessionAndCurrentBootAreIncludedWithoutConfigsOrOldLogs(self):
        for stamp in ['20261108-010000', '20261108-020000']:
            folder = self.root / 'Sessions' / stamp; folder.mkdir(parents=True)
            (folder / 'game-stdout.log').write_text(stamp)
            (folder / 'OriginalConfig').mkdir()
            (folder / 'OriginalConfig/segatools.ini').write_text('DO NOT EXPORT')
        (self.package / 'AirmaiBootTrace.log').write_text('Current Unity boot')
        result = collect(self.store, self.game)
        self.assertEqual(result['session'], '20261108-020000')
        combined = json.dumps(result)
        self.assertIn('20261108-020000', combined)
        self.assertIn('Current Unity boot', combined)
        self.assertNotIn('20261108-010000', combined)
        self.assertNotIn('DO NOT EXPORT', combined)

    def testDirectPackageLogsUseRelativeIDsAndKeepTheSessionReport(self):
        external = Path(self.temporary.name) / 'ExternalSSD' / 'Package'
        (external / 'MelonLoader').mkdir(parents=True)
        game = dict(self.game, packagePath=str(external), sourcePath=str(external), storageMode='direct')
        (external / 'AirmaiBootTrace.log').write_text(f'Boot from {external}\n')
        (external / 'MelonLoader/Latest.log').write_text('Loader initialized\n')
        session = self.root / 'Sessions/20261108-020000'
        session.mkdir(parents=True)
        (session / 'game-stdout.log').write_text('Game process started')

        report = collect(self.store, game)
        logs = {log['id']: log['text'] for log in report['logs']}
        self.assertEqual(report['session'], session.name)
        self.assertIn('Boot from [SOURCE]', logs['HDD/Package/AirmaiBootTrace.log'])
        self.assertEqual(logs['HDD/Package/MelonLoader/Latest.log'], 'Loader initialized\n')
        self.assertEqual(logs['Sessions/20261108-020000/game-stdout.log'], 'Game process started')
        self.assertNotIn(str(external), json.dumps(report))

    def testReadsTailAndNeverFollowsSymlinksOrFIFO(self):
        folder = self.root / 'Sessions/20261108-010000'; folder.mkdir(parents=True)
        (folder / 'game-stdout.log').write_text('old' + 'x' * (PER_FILE + 1) + 'new-tail')
        outside = Path(self.temporary.name) / 'secret'; outside.write_text('OUTSIDE SECRET')
        (folder / 'game-stderr.log').symlink_to(outside)
        os.mkfifo(folder / 'service-error.log')
        report = collect(self.store, self.game)
        self.assertEqual(len(report['logs']), 1)
        log = report['logs'][0]
        self.assertTrue(log['truncated'])
        self.assertEqual(len(log['text']), PER_FILE)
        self.assertTrue(log['text'].endswith('new-tail'))
        self.assertNotIn('OUTSIDE SECRET', json.dumps(report))

    def testCommonMachineCardAuthFieldsAndPrivatePathsAreMasked(self):
        samples = [str(Path.home()) + '/Documents/private', self.game['packagePath'], self.game['sourcePath'],
                   'A000-00000000000', '12345678901234567890',
                   'token=private-token&next=ok', 'Authorization: Bearer private-bearer',
                   'Cookie: session=private-cookie', '{"uid_hex":"1122aabb", "accessCode":"private-access"}']
        samples += ['A0001234567', 'A6XE01C1234', 'A6XE-01C1234', 'A00001234567890',
                    '    00000010: 41 30 30 30 12 34 56 78 A000 private-bcd']
        output = redact('\n'.join(samples), self.store, self.game)
        for secret in [str(Path.home()), self.game['packagePath'], self.game['sourcePath'],
                       'A000-00000000000', '12345678901234567890', 'private-token',
                       'private-bearer', 'private-cookie', '1122aabb', 'private-access',
                       'A0001234567', 'A6XE01C1234', 'A6XE-01C1234', 'A00001234567890', 'private-bcd']:
            self.assertNotIn(secret, output)
        self.assertIn('next=ok', output)

    def testSetupLogsRemainAvailableBeforeFirstGameRun(self):
        setup = self.root / 'Setup'; setup.mkdir()
        (setup / '依赖检查.log').write_text('dependency failure')
        result = collect(self.store, self.game)
        self.assertIsNone(result['session'])
        self.assertEqual(result['logs'][0]['text'], 'dependency failure')

    def testModCapabilitiesAreVisibleInExistingDiagnostics(self):
        (self.root/'mod-compatibility.json').write_text(json.dumps(dict(modules=[dict(assembly='OrdinaryMod',version='1.0.0')],inputProviders=[],issues=[])))
        report=collect(self.store,self.game)
        self.assertEqual(report['logs'][0]['title'],'模组接口与冲突检查')
        self.assertIn('OrdinaryMod',report['logs'][0]['text'])


if __name__ == '__main__':
    unittest.main()
