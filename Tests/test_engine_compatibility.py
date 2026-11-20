"""Static CLR fixtures and self-authored probes; no game or Wine execution."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Service'))
import compatibility
from unity_compatibility import fullscreen_api, legacy_mod_check, LIMIT
from storage import Store, atomic_json
import runtime


class EngineCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dotnet = Path(os.environ.get('AIRMAIDX_DOTNET', shutil.which('dotnet') or 'dotnet'))
        if not cls.dotnet.is_file():
            raise unittest.SkipTest('Native compatibility probes require the development .NET SDK')
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work = Path(cls.temp.name)
        sdk = sorted((cls.dotnet.parent / 'sdk').glob('*/Roslyn/bincore/csc.dll'))[-1]
        refs = sorted((cls.dotnet.parent / 'packs/Microsoft.NETCore.App.Ref').glob('*/ref/net*'))[-1]
        cls.runtime_version = sorted((cls.dotnet.parent / 'shared/Microsoft.NETCore.App').iterdir())[-1].name
        cls.compiler = [str(cls.dotnet), str(sdk), '/nologo', '/noconfig', '/nostdlib+',
                        *['/reference:' + str(p) for p in refs.glob('*.dll')]]
        cls.compile(cls.work / 'MelonLoader.dll', [ROOT / 'Tests/Native/ControllerStubs.cs'])
        for modern in [False, True]:
            folder = cls.work / ('modern' if modern else 'legacy'); folder.mkdir()
            cls.compile(folder / 'UnityEngine.CoreModule.dll', [ROOT / 'Tests/Native/UnityDisplayStubs.cs'], modern=modern)
            cls.compile(folder / 'DisplayTraceTests.dll', [ROOT / 'Native/AirmaiDisplayTrace.cs', ROOT / 'Tests/Native/DisplayTraceTests.cs'],
                        references=[folder / 'UnityEngine.CoreModule.dll', cls.work / 'MelonLoader.dll'], modern=modern, executable=True)
            (folder / 'MelonLoader.dll').write_bytes((cls.work / 'MelonLoader.dll').read_bytes())
            (folder / 'DisplayTraceTests.runtimeconfig.json').write_text(json.dumps({'runtimeOptions': {
                'tfm': refs.name, 'framework': {'name': 'Microsoft.NETCore.App', 'version': cls.runtime_version}}}))
        consumer = cls.work / 'Consumer.cs'
        consumer.write_text('public class Consumer { public static UnityEngine.FullScreenMode Read() { return UnityEngine.Screen.fullScreenMode; } }')
        cls.compile(cls.work / 'Consumer.dll', [consumer], references=[cls.work / 'modern/UnityEngine.CoreModule.dll'])
        compressor = zlib.compressobj(wbits=-15)
        compressed = cls.work / 'consumer.deflate'
        compressed.write_bytes(compressor.compress((cls.work / 'Consumer.dll').read_bytes()) + compressor.flush())
        wrapper = cls.work / 'Wrapper.cs'; wrapper.write_text('public class Wrapper {}')
        cls.compile(cls.work / 'PackedMod.dll', [wrapper], resources=[(compressed, 'AquaMai.Mods.dll.compressed')])
        melon = cls.work / 'MelonLoader.dll'
        wrapper.write_text('public class OptionalMod : MelonLoader.MelonMod {}')
        cls.compile(cls.work / 'OptionalMod.dll', [wrapper], references=[melon], resources=[(compressed, 'Addon.dll.compressed')])
        wrapper.write_text('public class AquaMaiMod : MelonLoader.MelonMod {}')
        cls.compile(cls.work / 'AquaMai.dll', [wrapper], references=[melon])

    @classmethod
    def compile(cls, output, sources, references=(), modern=False, executable=False, resources=()):
        args = [*cls.compiler, '/target:' + ('exe' if executable else 'library'), '/out:' + str(output)]
        if modern: args.append('/define:MODERN')
        args += ['/reference:' + str(p) for p in references]
        args += ['/resource:' + str(p) + ',' + name for p, name in resources]
        result = subprocess.run([*args, *map(str, sources)], capture_output=True, text=True, timeout=45)
        if result.returncode: raise AssertionError(result.stdout + result.stderr)

    def make_package(self, root, version='2017.4.23f1'):
        package = root / 'Package'
        for name in compatibility.REQUIRED:
            path = package / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{}' if name.endswith('.json') else '')
        core = package / 'Sinmai_Data/Managed/UnityEngine.CoreModule.dll'
        core.write_bytes((self.work / 'legacy/UnityEngine.CoreModule.dll').read_bytes())
        (package / 'Mods').mkdir(exist_ok=True)
        (package / 'Sinmai_Data/globalgamemanagers').write_bytes(b'\0' + version.encode() + b'\0')
        return package

    def testTraceExecutesWithOldAPIAndUsesNewAPIWhenAvailable(self):
        for name in ['legacy', 'modern']:
            folder = self.work / name
            result = subprocess.run([str(self.dotnet), str(folder / 'DisplayTraceTests.dll')],
                                    capture_output=True, text=True, timeout=10, cwd=folder)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('checks passed', result.stdout)
            metadata = fullscreen_api((folder / 'DisplayTraceTests.dll').read_bytes(), 'trace')
            self.assertEqual(metadata['references'], [])

    def testFindsActualMissingTypeReferencesIncludingPackedAquaMaiModules(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.make_package(Path(directory))
            (package / 'Mods/AquaMai.dll').write_bytes((self.work / 'PackedMod.dll').read_bytes())
            issues = legacy_mod_check(package)['blockers']
            self.assertEqual(len(issues), 1)
            self.assertIn('UnityEngine.FullScreenMode', issues[0])
            self.assertIn('AquaMai.Mods.dll', issues[0])
            (package / 'Sinmai_Data/Managed/UnityEngine.CoreModule.dll').write_bytes((self.work / 'modern/UnityEngine.CoreModule.dll').read_bytes())
            self.assertEqual(legacy_mod_check(package)['blockers'], [])

    def testMalformedOrOversizedAssembliesProduceAnActionableInspectionIssue(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.make_package(Path(directory))
            (package / 'Mods/AquaMai.dll').write_bytes(b'bad PE')
            plan = legacy_mod_check(package)
            self.assertEqual(plan['blockers'], [])
            self.assertIn('无法完成静态检查', plan['warnings'][0])
            self.assertTrue((package / 'Mods/AquaMai.dll').is_file())
            with self.assertRaises(ValueError): fullscreen_api(b'x' * (LIMIT + 1), 'too large')

    def install_fixture_mods(self, package, *names):
        for name in names:
            (package / 'Mods' / name).write_bytes((self.work / name).read_bytes())

    def testModWithNoStaticDependentsIsPreservedByStartup(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            package = self.make_package(workspace)
            self.install_fixture_mods(package, 'AquaMai.dll', 'OptionalMod.dll')
            store = Store(workspace / 'Data')
            game = dict(id='a'*32, packagePath=str(package), sourcePath=str(package), storageMode='direct', ready=True)
            runtime_dir = workspace / 'Runtime'; runtime_dir.mkdir()
            manifest = runtime_dir / 'manifest.json'; manifest.write_text('{}')
            store.db.write_text(json.dumps([game]))
            root = store.game_root(game)
            (root/'Setup').mkdir(parents=True)
            from contextlib import nullcontext
            from storage import digest
            atomic_json(root/'Setup/runtime-receipt.json', dict(manifest_sha256=digest(manifest)))
            (package/'segatools.ini').write_text('[keychip]\nid=TEST-A123\n')
            active = package / 'Mods/OptionalMod.dll'
            baseline = active.read_bytes()

            def metadata(path):
                return dict(present=path.is_file(), architecture='x64', version='0.6.4', imports=[])

            with (patch('runtime.active_lease', side_effect=lambda *args: nullcontext()),
                  patch('runtime.stop_wine'), patch('runtime.validate_runtime'),
                  patch('mod_cache.activate_signed_cache'),
                  patch('compatibility.pe_metadata', side_effect=metadata),
                  patch('runtime.session_status', return_value={'running':False}),
                  patch('runtime.subprocess.Popen') as spawn):
                with self.assertRaisesRegex(ValueError, 'Mods/OptionalMod.dll.*已保留模组'):
                    runtime.start(store, runtime_dir, game['id'])
                spawn.assert_not_called()
            self.assertEqual(active.read_bytes(), baseline)
            self.assertFalse(active.with_name(active.name+'.airmai-disabled').exists())
            self.assertTrue((package/'Mods/AquaMai.dll').is_file())
            self.assertFalse((root/'Backups').exists())
            self.assertIn('Addon.dll', (root/'compatibility.json').read_text())

    def test2017CanBePreparedWithoutFaking2018AndMismatchedPlayerIsRejected(self):
        def metadata(path):
            name = path.name
            version = '2017.4.23.1' if name == 'UnityPlayer.dll' else '0.6.4' if name == 'MelonLoader.dll' else '1.9.20'
            return dict(present=path.is_file(), architecture='x64', version=version, imports=[])
        with tempfile.TemporaryDirectory() as directory:
            package = self.make_package(Path(directory))
            (package / 'Mods/AquaMai.dll').write_bytes((self.work / 'MelonLoader.dll').read_bytes())
            (package / 'UnityPlayer.dll').write_bytes(b'player fixture')
            before = (package / 'Sinmai_Data/globalgamemanagers').read_bytes()
            with patch('compatibility.pe_metadata', side_effect=metadata):
                report = compatibility.inspect_package(package)
                self.assertTrue(report['canPrepare'], report['issues'])
                self.assertEqual(report['compatibilityState'], 'firstRun')
                self.assertEqual(report['unityVersion'], '2017.4.23f1')
                self.assertEqual(report['engineFamily'], 'unity2017-mono-ml06')
                self.assertIn('实测', report['compatibilityNote'])
                self.assertEqual((package / 'Sinmai_Data/globalgamemanagers').read_bytes(), before)
                (package / 'Sinmai_Data/globalgamemanagers').write_bytes(b'\0Unity 2018.4.23f1\0')
                report = compatibility.inspect_package(package)
                self.assertFalse(report['canPrepare'])
                self.assertTrue(any('不一致' in issue for issue in report['issues']))
