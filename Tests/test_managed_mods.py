"""Compile owned CLR fixtures and inspect metadata; no Windows code runs."""
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
sys.path.insert(0,str(ROOT/'Service'))
from managed_mods import inspect_mods, inspect_assembly, Signature
from controller_devices import game_api_verified
from compatibility import detect_mod
import compatibility

CONTRACT = '''
namespace AquaMai.Core.Helpers {
 public static class JvsSwitchHook {
  public delegate bool ButtonChecker(int player, int button);
  public struct AuxiliaryState { public bool select1P, select2P, service, test; }
  public delegate AuxiliaryState AuxiliaryStateProvider();
  public static void RegisterButtonChecker(ButtonChecker cb) {}
  public static void RegisterAuxiliaryStateProvider(AuxiliaryStateProvider cb) {}
 }
 public class TouchStatusProvider {
  public delegate ulong TouchStatusProviderDelegate(int player);
  public static void RegisterTouchStatusProvider(int player, TouchStatusProviderDelegate cb) {}
 }
}'''
ENTRY = 'public class Entry : MelonLoader.MelonMod {}'


class ManagedModTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dotnet = Path(os.environ.get('AIRMAIDX_DOTNET', shutil.which('dotnet') or 'dotnet')).resolve()
        if not dotnet.exists(): raise unittest.SkipTest('Requires local development .NET SDK')
        cls.tmp = tempfile.TemporaryDirectory();cls.addClassCleanup(cls.tmp.cleanup);cls.work=Path(cls.tmp.name)
        compiler=sorted((dotnet.parent/'sdk').glob('*/Roslyn/bincore/csc.dll'))[-1]
        refs=sorted((dotnet.parent/'packs/Microsoft.NETCore.App.Ref').glob('*/ref/net*'))[-1]
        cls.command=[str(dotnet),str(compiler),'/nologo','/noconfig','/nostdlib+','/target:library',*['/reference:'+str(p) for p in refs.glob('*.dll')]]
        cls.compile('MelonLoader','namespace MelonLoader { public class MelonMod {} }', melon=False)
        cls.compile('GoodInput',ENTRY+CONTRACT)
        cls.compile('AnotherVersion','[assembly:System.Reflection.AssemblyVersion("99.4.3.2")]'+ENTRY+CONTRACT)
        cls.compile('CoreOnly',CONTRACT)
        cls.compile('WrongTouch',ENTRY+CONTRACT.replace('delegate ulong','delegate uint'))
        cls.compile('WrongButton',ENTRY+CONTRACT.replace('int player, int button','int player, short button'))
        cls.compile('WrongAux',ENTRY+CONTRACT.replace('bool select1P, select2P, service, test','bool select1P, select2P, test; public int service'))
        cls.compile('HiddenRegister',ENTRY+CONTRACT.replace('public static void RegisterTouch','internal static void RegisterTouch'))
        cls.compile('OverloadedRegister',ENTRY+CONTRACT.replace('public class TouchStatusProvider {','public class TouchStatusProvider { public static void RegisterTouchStatusProvider(int p, string cb) {}'))
        cls.compile('OrdinaryMod','public class ListOfInts:System.Collections.Generic.List<int> {} public class Base:MelonLoader.MelonMod {} public class Ordinary:Base {}')
        cls.compile('Library','public class HelperLibrary {}')
        raw=(cls.work/'CoreOnly.dll').read_bytes();compressor=zlib.compressobj(wbits=-15)
        cls.compile('Packed',ENTRY,resources=[('Other.Core.dll.compressed',compressor.compress(raw)+compressor.flush())])
        compressor=zlib.compressobj(wbits=-15)
        cls.compile('Bomb',ENTRY,resources=[('Other.Core.dll.compressed',compressor.compress(b'x'*100000)+compressor.flush())])

    @classmethod
    def compile(cls,name,source,melon=True,resources=()):
        path=cls.work/(name+'.cs');path.write_text(source)
        args=[*cls.command,'/out:'+str(cls.work/(name+'.dll'))]
        if melon:args.append('/reference:'+str(cls.work/'MelonLoader.dll'))
        for i,(label,data) in enumerate(resources):
            resource=cls.work/(name+str(i)+'.data');resource.write_bytes(data);args.append('/resource:'+str(resource)+','+label)
        result=subprocess.run([*args,str(path)],capture_output=True,text=True,timeout=45)
        if result.returncode:raise AssertionError(result.stdout+result.stderr)

    def setUp(self):
        self.tmpcase=tempfile.TemporaryDirectory();self.addCleanup(self.tmpcase.cleanup)
        self.package=Path(self.tmpcase.name)/'Package';(self.package/'Mods').mkdir(parents=True)
        self.runtime=Path(self.tmpcase.name)/'runtime';self.runtime.mkdir();(self.runtime/'manifest.json').write_text('{}')

    def add(self,fixture,name=None):
        path=self.package/'Mods'/(name or fixture+'.dll');shutil.copy2(self.work/(fixture+'.dll'),path);return path

    def testDifferentVersionsAndRenamedPackedProviderNeedNoHashEntry(self):
        for fixture in ['GoodInput','AnotherVersion','Packed']:
            path=self.add(fixture,'UnrelatedName.DLL')
            report=inspect_mods(self.package)
            self.assertEqual(report['issues'],[]);self.assertEqual(len(report['inputProviders']),1)
            self.assertTrue(game_api_verified(self.runtime,self.package));path.unlink()

    def testWrongSignatureStateFieldsVisibilityAndOverloadsAreRejected(self):
        for fixture in ['WrongTouch','WrongButton','WrongAux','HiddenRegister','OverloadedRegister']:
            path=self.add(fixture)
            report=inspect_mods(self.package)
            self.assertEqual(report['inputProviders'],[],fixture)
            self.assertTrue(report['modules'][0]['melonMod'])
            self.assertFalse(game_api_verified(self.runtime,self.package));path.unlink()

    def testGenericMelonModIsDetectedWithoutAquaMaiOrMuMod(self):
        path=self.add('OrdinaryMod','Renamed.dll')
        mod=detect_mod(self.package)
        self.assertEqual(mod,dict(kind='OrdinaryMod',dll='Mods/Renamed.dll',version='0.0.0.0'))
        self.assertFalse(game_api_verified(self.runtime,self.package))
        self.assertEqual(path.read_bytes(),(self.work/'OrdinaryMod.dll').read_bytes())

    def testGenericMelonPackagePassesPreparationWithoutClaimingHardwareSupport(self):
        self.add('OrdinaryMod')
        for name in compatibility.REQUIRED:
            path=self.package/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('{}' if name.endswith('.json') else '[keychip]\nid=none\n' if name.endswith('.ini') else 'fixture')
        (self.package/'Sinmai_Data/globalgamemanagers').write_bytes(b'\0Unity 2018.4.7f1\0')
        def metadata(path):
            return dict(present=path.is_file(),architecture='x64',version='0.6.4' if path.name=='MelonLoader.dll' else None,imports=[])
        with patch('compatibility.pe_metadata',side_effect=metadata):report=compatibility.inspect_package(self.package)
        self.assertTrue(report['canPrepare'],report['issues'])
        self.assertEqual(report['modKind'],'OrdinaryMod')
        self.assertEqual(report['compatibilityState'],'firstRun')
        self.assertFalse(game_api_verified(self.runtime,self.package))

    def testHelperLibraryAndOwnedHelpersDoNotQualifyAsUserMod(self):
        self.add('Library');self.add('OrdinaryMod','AirmaiControllerInput.dll')
        self.assertIsNone(detect_mod(self.package))

    def testDuplicateProvidersAreNotSilentlySelected(self):
        self.add('GoodInput');self.add('AnotherVersion')
        self.assertEqual(len(inspect_mods(self.package)['inputProviders']),2)
        self.assertFalse(game_api_verified(self.runtime,self.package))

    def testBrokenUnrelatedModIsPreservedAndReportedWithoutHidingGoodMod(self):
        self.add('OrdinaryMod');bad=self.package/'Mods/Broken.dll';bad.write_bytes(b'not CLR')
        report=inspect_mods(self.package)
        self.assertEqual(len(report['modules']),1);self.assertEqual(len(report['issues']),1)
        self.assertEqual(detect_mod(self.package)['kind'],'OrdinaryMod')
        self.assertEqual(bad.read_bytes(),b'not CLR')

    def testSymlinkAndExpansionLimitsAreBounded(self):
        path=self.package/'Mods/Outside.dll';path.symlink_to(self.work/'GoodInput.dll')
        self.assertEqual(inspect_mods(self.package)['inputProviders'],[]);path.unlink()
        self.add('Bomb')
        with patch('managed_mods.FILE_LIMIT',65536):
            report=inspect_mods(self.package)
        self.assertEqual(report['inputProviders'],[]);self.assertTrue(report['issues'])

    def testAggregateAndModuleCountLimits(self):
        self.add('GoodInput')
        with patch('managed_mods.EXPANDED_LIMIT',100):self.assertTrue(inspect_mods(self.package)['issues'])
        for n in range(65):(self.package/'Mods'/('%02d.dll'%n)).write_bytes(b'')
        report=inspect_mods(self.package);self.assertTrue(report['issues']);self.assertEqual(report['modules'],[])

    def testMalformedSignaturesDoNotReadPastBounds(self):
        for data in [b'',b'\x00\xff',b'\x00\x01\x01',b'\x10\x00',b'\x00\x00\x01\x00']:
            with self.assertRaises(ValueError):Signature(data,None).method()


if __name__=='__main__':unittest.main()
