"""Runtime selection survives moving the app without accepting stale payloads."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Tools'))
from app_resources import native_fingerprint, runtime_resource_source


class RuntimeSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / 'Native').mkdir()
        (self.root / 'Native/Helper.c').write_text('// owned helper\n')
        (self.root / 'Tools').mkdir()
        (self.root / 'Tools/build_app.py').write_text('# owned builder\n')
        self.default = self.root / 'build/AirmaiDX.app/Contents/Resources'
        self.installed = self.root / 'Applications/AirmaiDX.app/Contents/Resources'
        self.destination = self.root / 'DerivedData/Product.app/Contents/Resources'
        self.make_source(self.installed)

    def tearDown(self):
        self.temporary.cleanup()

    def make_source(self, source, **changes):
        runtime = source / 'Runtime'
        helper = runtime / 'helpers/input.dll'
        helper.parent.mkdir(parents=True)
        helper.write_bytes(b'owned helper fixture')
        manifest = dict(native_source_sha256=native_fingerprint(self.root),
                        critical_sha256={'helpers/input.dll': hashlib.sha256(helper.read_bytes()).hexdigest()},
                        game_included=False, prefix_included=False, gptk_included=False)
        manifest.update(changes)
        (runtime / 'manifest.json').write_text(json.dumps(manifest))

    def choose(self, configured=None, installed=None):
        return runtime_resource_source(self.root, self.destination, configured,
                                       [self.installed] if installed is None else installed)[0]

    def testMovedBuildAppUsesVerifiedInstalledCopyEvenWithGeneratedDefaultSetting(self):
        self.assertFalse(self.default.exists())
        self.assertEqual(self.choose(), self.installed)
        self.assertEqual(self.choose(str(self.default)), self.installed)

    def testCurrentBuildAppIsPreferredAndStaleOneCanUseMatchingInstalledCopy(self):
        self.make_source(self.default)
        self.assertEqual(self.choose(), self.default)
        (self.default / 'Runtime/helpers/input.dll').write_bytes(b'corrupt')
        self.assertEqual(self.choose(), self.installed)
        self.make_source(self.root / 'other', native_source_sha256='stale')
        with self.assertRaisesRegex(RuntimeError, '原生辅助组件'):
            self.choose(str(self.root / 'other'))

    def testExplicitCustomPathDoesNotSilentlyFallBack(self):
        custom = self.root / 'custom'
        with self.assertRaisesRegex(RuntimeError, '指定的运行组件来源不可用'):
            self.choose(str(custom))
        self.make_source(custom)
        self.assertEqual(self.choose(str(custom)), custom)

    def testCannotCopyOutputBackOntoItselfIncludingSymlinkAlias(self):
        self.make_source(self.destination)
        with self.assertRaisesRegex(RuntimeError, '来源与 Xcode 输出目录相同'):
            self.choose(str(self.destination))
        alias = self.root / 'output-alias'
        alias.symlink_to(self.destination, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, '来源与 Xcode 输出目录相同'):
            self.choose(str(alias))

    def testStaleNativeCodeCorruptPayloadAndIncompleteManifestAreRejected(self):
        for changes in [dict(native_source_sha256='stale'), dict(critical_sha256={}),
                        dict(game_included=True), dict(prefix_included=True), dict(gptk_included=True)]:
            with self.subTest(changes=changes):
                custom = self.root / ('case' + str(len(list(self.root.iterdir()))))
                self.make_source(custom, **changes)
                with self.assertRaises(RuntimeError): self.choose(str(custom))
        (self.installed / 'Runtime/helpers/input.dll').write_bytes(b'corrupt')
        with self.assertRaisesRegex(RuntimeError, '文件校验失败'):
            self.choose()

    def testExternalManifestPathsAndSymlinksCannotImportOutsideFiles(self):
        outside = self.root / 'outside.dll'
        outside.write_bytes(b'outside fixture')
        for name in ['../../../../outside.dll', str(outside)]:
            custom = self.root / ('unsafe' + str(len(list(self.root.iterdir()))))
            self.make_source(custom, critical_sha256={name: hashlib.sha256(outside.read_bytes()).hexdigest()})
            with self.assertRaisesRegex(RuntimeError, '路径无效'):
                self.choose(str(custom))
        helper = self.installed / 'Runtime/helpers/input.dll'
        helper.unlink(); helper.symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, '路径无效'):
            self.choose()

    def testMalformedManifestAndMissingSourcesProvideActionableErrors(self):
        (self.installed / 'Runtime/manifest.json').write_text('[]')
        with self.assertRaisesRegex(RuntimeError, '清单格式无效'):
            self.choose()
        with self.assertRaisesRegex(RuntimeError, 'Tools/build_app.py'):
            self.choose(installed=[])


if __name__ == '__main__': unittest.main()
