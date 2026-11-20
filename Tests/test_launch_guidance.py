from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Service'))
import runtime
from launch_guidance import LaunchRequirement
from machine_config import save_keychip
from storage import Store


class LaunchGuidanceTests(unittest.TestCase):
    def setUp(self):
        work = self.enterContext(tempfile.TemporaryDirectory())
        base = Path(work).resolve()
        self.package = base / 'HDD'
        self.package.mkdir()
        self.config = self.package / 'segatools.ini'
        self.store = Store(base / 'AppData')
        self.game = dict(id='c'*32, packagePath=str(self.package), sourcePath=str(self.package), storageMode='direct', ready=False)
        self.store.game_root(self.game).mkdir(parents=True)
        self.store.update(self.game)
        self.enterContext(patch('runtime.host_preflight'))
        self.discover = self.enterContext(patch('runtime.startup_checks.discover', return_value=[]))

    def guide(self, expected):
        with self.assertRaises(LaunchRequirement) as pending:
            runtime.launch_guide(self.store, self.game['id'])
        self.assertEqual(pending.exception.guide['kind'], expected)
        return pending.exception.guide

    def testMissingKeychipIsFilledAndExistingFileIsBackedUp(self):
        original = '[DNS]\r\ndefault=example.test\r\n[KEYCHIP]\r\n; 保留配置\r\ngameid=SDGB\r\n'.encode('utf-8-sig')
        self.config.write_bytes(original)
        self.guide('keychipMissing')
        self.discover.assert_not_called()
        self.assertTrue(save_keychip(self.store, self.game['id'], 'A6XE01C1234'))
        self.assertEqual(self.config.read_bytes(), original + b'id=A6XE01C1234\r\n')
        self.assertTrue(runtime.launch_guide(self.store, self.game['id']))
        backups = self.store.game_root(self.game) / 'Backups'
        self.assertEqual([p.read_bytes() for p in backups.glob('*.backup')], [original])

    def testInvalidOrMalformedValuesNeverEnterGuideResponse(self):
        for text, issue in [('[keychip]\nid=private/identifier\n', 'keychipInvalid'), ('private/identifier\n', 'machineConfig')]:
            with self.subTest(issue=issue):
                self.config.write_text(text)
                self.assertNotIn('private/identifier', repr(self.guide(issue)))
                with self.assertRaises(ValueError):
                    save_keychip(self.store, self.game['id'], '0000')
                self.assertEqual(self.config.read_text(), text)

    def testDisplaysOnlyPendingRecognizedStartupChecksWithoutNetwork(self):
        self.config.write_text('[keychip]\nid=A6XE01C1234\n')
        checks = [dict(url=f'https://example.test/{i}', method='GET', purpose='test', sendsMachineData=False) for i in range(2)]
        self.game['allowedStartupChecks'] = [checks[0]['url']]
        self.store.update(self.game)
        self.discover.return_value = checks
        with patch('startup_checks.urllib.request.build_opener') as opener:
            self.assertEqual(self.guide('startupChecks')['checks'], checks[1:])
            opener.assert_not_called()

    def testDisconnectedHDDIsReportedBeforeReadingMachineSettings(self):
        self.package.rmdir()
        self.guide('packageUnavailable')
        self.discover.assert_not_called()
