"""Import and configuration regression checks; never execute game binaries."""
from io import BytesIO
from pathlib import Path
import base64, json, os, stat, struct, sys, tempfile, unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'Service'))
from storage import Store, digest, copy_private
import runtime
import compatibility
import music
import startup_checks

class ImportAndConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        base=Path(self.temp.name).resolve()
        self.source=base/'source/Package';self.source.mkdir(parents=True)
        pe=bytearray(128);pe[:2]=b'MZ';pe[0x3c:0x40]=struct.pack('<I',64);pe[64:70]=b'PE\0\0\x64\x86'
        for name in ['Sinmai.exe','amdaemon.exe','inject.exe','mai2hook.dll']:(self.source/name).write_bytes(pe)
        for name in ['options','amfs','appdata','Sinmai_Data']:(self.source/name).mkdir()
        (self.source/'Sinmai_Data/globalgamemanagers').write_bytes(b'\0Unity 2018.4.7f1\0')
        (self.source/'mai2.ini').write_bytes(b'; comment\r\n[Sound]\r\nSound8Ch=1\r\n')
        (self.source/'segatools.ini').write_text('[keychip]\nid=none\n')
        self.store=Store(base/'private')
    def tearDown(self):self.temp.cleanup()
    def testDirectHDDConfigurationUsesTheSelectedFolderAndRestoresBackups(self):
        game=self.store.import_game(self.source.parent)
        package=Path(game['packagePath'])
        self.assertEqual(package,self.source)
        self.assertEqual(game['storageMode'],'direct')
        self.assertFalse((self.store.game_root(game)/'HDD').exists())
        self.assertTrue((package/'options').is_dir())
        self.assertEqual(game['unityVersion'],'2018.4.7f1')
        original=digest(self.source/'mai2.ini')
        file=self.store.read_config(game['id'],'mai2.ini')
        self.store.save_config(game['id'],'mai2.ini',file['text'].replace('Sound8Ch=1','Sound8Ch=0'),file['sha256'],file['encoding'])
        self.assertNotEqual(digest(self.source/'mai2.ini'),original)
        self.assertIn(b'\r\n', (package/'mai2.ini').read_bytes())
        with self.assertRaisesRegex(ValueError,'其他程序'):
            self.store.save_config(game['id'],'mai2.ini',file['text'],file['sha256'],file['encoding'])
        backup=self.store.backups(game['id'])[0]
        self.store.restore(game['id'],backup['id'])
        self.assertEqual(digest(package/'mai2.ini'),original)
    def testExternalSymlinkCannotBeImported(self):
        (self.source/'outside').symlink_to(Path(self.temp.name))
        with self.assertRaisesRegex(ValueError,'链接'):self.store.import_game(self.source)
        self.assertEqual(self.store.library(),[])

    @unittest.skipUnless(hasattr(os,'chflags'),'BSD file locks require macOS')
    def testAddingDirectHDDDoesNotChangeLockedGameAssets(self):
        managed=self.source/'Sinmai_Data/Managed';managed.mkdir()
        source=managed/'Assembly-CSharp.dll';source.write_bytes(b'locked managed fixture')
        os.chflags(source,stat.UF_IMMUTABLE)
        try:
            game=self.store.import_game(self.source)
            self.assertEqual(Path(game['packagePath']),self.source)
            self.assertEqual(source.stat().st_flags,stat.UF_IMMUTABLE)
            self.assertEqual(source.read_bytes(),b'locked managed fixture')
        finally:os.chflags(source,0)

    def testFailedLibraryWriteRemovesOnlyNewRuntimeMetadata(self):
        with patch.object(self.store,'update',side_effect=OSError('database unavailable')):
            with self.assertRaisesRegex(OSError,'database unavailable'):
                self.store.import_game(self.source)
        self.assertEqual(list((self.store.root/'Games').iterdir()),[])
        self.assertTrue((self.source/'Sinmai.exe').is_file())
        self.assertEqual(self.store.library(),[])

    def testReimportUsesTheSameHDDAndGameIdentityAfterAssetUpdates(self):
        assets=self.source/'Sinmai_Data/StreamingAssets';assets.mkdir()
        asset=assets/'example';asset.write_bytes(b'original')
        first=self.store.import_game(self.source.parent)
        identity=asset.stat().st_ino
        self.assertEqual(self.store.import_game(self.source)['id'],first['id'])
        asset.write_bytes(b'updated asset')
        second=self.store.import_game(self.source.parent)
        self.assertEqual(second['id'],first['id'])
        self.assertEqual(asset.stat().st_ino,identity)
        self.assertEqual((Path(second['packagePath'])/'Sinmai_Data/StreamingAssets/example').read_bytes(),b'updated asset')

    def testDisconnectedHDDRetainsItsEntryAndReportsHowToReconnect(self):
        game=self.store.import_game(self.source)
        game['ready']=True;self.store.update(game)
        self.source.rename(self.source.with_name('unplugged'))
        self.assertEqual(self.store.get(game['id'])['id'],game['id'])
        with patch('runtime.stop_wine') as stop:
            with self.assertRaisesRegex(ValueError,'HDD 未连接'):
                runtime.start(self.store,Path('/unused-runtime'),game['id'])
        stop.assert_not_called()

    def testLegacyConfigKeepsSingularOptionAndDisabledReader(self):
        (self.source/'option').mkdir()
        (self.source/'segatools.ini').write_text('[vfs]\noption=option\n[io4]\nenable=0\n')
        (self.source/'config_common.json').write_text('{"aime": {"enable": false}}')
        (self.source/'AquaMai.toml').write_text('[GameSystem.Window]\nDisabled = false\n[GameSystem.KeyMap]\nDisabled = false\n')
        game=self.store.import_game(self.source)
        package=Path(game['packagePath'])
        compatibility.prepare_configuration(self.store,game)
        parser=compatibility.ini(package/'segatools.ini')
        self.assertEqual(parser.get('vfs','option'),'option')
        self.assertFalse(parser.getboolean('io4','enable'))
        self.assertEqual((package/'config_common.json').read_bytes(),(self.source/'config_common.json').read_bytes())
        self.assertIn('Disabled=true',(package/'AquaMai.toml').read_text())
        self.assertEqual(package,self.source)

    def testEmptyVFSPathsUsePrivateDefaults(self):
        (self.source/'segatools.ini').write_text('[vfs]\namfs=\nappdata= \noption=\n')
        game=self.store.import_game(self.source)
        compatibility.prepare_configuration(self.store,game)
        package=Path(game['packagePath']);parser=compatibility.ini(package/'segatools.ini')
        for key,value in [('amfs','amfs'),('appdata','appdata'),('option','options')]:
            self.assertEqual(parser.get('vfs',key),value)
            self.assertTrue((package/value).is_dir())

    def testLaunchPinsSegatoolsConfigAndRejectsInheritedOverrides(self):
        with patch.dict('os.environ',{'SEGATOOLS_CONFIG_PATH':r'C:\wrong.ini','SEGATOOLS_VFS_RELATIVE_PATH':'unverified'}):
            env=runtime.environment(Path('/runtime'),Path('/prefix'))
        self.assertEqual(env['SEGATOOLS_CONFIG_PATH'],r'C:\AirmaiDX\Package\segatools.ini')
        self.assertNotIn('SEGATOOLS_VFS_RELATIVE_PATH',env)

    def testVFSFatalIsReportedWithoutTreatingNormalFallbackMessagesAsFatal(self):
        self.assertIsNotNone(runtime.startup_failure('Vfs: FATAL: AMFS path not specified in INI file'))
        self.assertIsNone(runtime.startup_failure('Fallback handler could not load library Mono/libc.dll'))
    def testInvalidMachineIDIsBlockedBeforeLaunchingWine(self):
        game=self.store.import_game(self.source)
        game['ready']=True;self.store.update(game)
        with self.assertRaises(runtime.LaunchRequirement) as blocked:
            runtime.start(self.store,Path('/nonexistent-runtime'),game['id'])
        self.assertIn(blocked.exception.guide['kind'], ['keychipMissing', 'keychipInvalid'])

    def testServiceIssuedShortAndCompactIdentifiersReachRuntimeValidationUnchanged(self):
        game=self.store.import_game(self.source)
        game['ready']=True;self.store.update(game)
        path=Path(game['packagePath'])/'segatools.ini'
        for value in ['A6XE01C1234','A6XE-01C1234','A000-01234567890','A00001234567890']:
            with self.subTest(identifier=value):
                path.write_text('[keychip]\nid='+value+'\n')
                original=path.read_bytes()
                with patch('runtime.validate_runtime',side_effect=RuntimeError('identifier accepted')) as validate, \
                        patch('runtime.subprocess.Popen') as launch:
                    with self.assertRaisesRegex(RuntimeError,'identifier accepted'):
                        runtime.start(self.store,Path('/nonexistent-runtime'),game['id'])
                validate.assert_called_once();launch.assert_not_called()
                self.assertEqual(path.read_bytes(),original)

    def testBadUSBInventoryReachesKeyboardConfigurationWithoutLaunchingAnything(self):
        game=self.store.import_game(self.source)
        game['settings']['hdxEnabled']=True;self.store.update(game)
        # Stop at the configuration boundary: no Wine, game, serial or network I/O.
        with patch('hdx_touch_probe.subprocess.check_output',return_value=b'not a plist'), \
                patch.object(self.store,'apply_launch_configs',side_effect=RuntimeError('test configuration boundary')) as configure, \
                patch('runtime.subprocess.run'),patch('runtime.subprocess.Popen') as launch:
            runtime.session_run(self.store,Path(self.temp.name)/'no-runtime',game['id'])
        launch.assert_not_called()
        configure.assert_called_once()
        changes=dict(configure.call_args.args[2])
        self.assertIn(b'DummyTouchPanel=1',changes['mai2.ini'])
        self.assertIn(b'scan=0',changes['segatools.ini'])
        state=json.loads((self.store.game_root(game)/'session.json').read_text())
        self.assertEqual(state['input_mode'],'keyboard')
        self.assertEqual(state['message'],'test configuration boundary')
        report=json.loads((Path(state['session'])/'input-detection.json').read_text())
        self.assertEqual(report['mode'],'keyboard')
        self.assertIn('格式无效',report['message'])
    def testBatchWriteRollsBackOnSecondFileFailureAndRestoresTogether(self):
        game=self.store.import_game(self.source)
        package=Path(game['packagePath']);a=package/'mai2.ini';b=package/'segatools.ini'
        before=(a.read_bytes(),b.read_bytes())
        import os
        real_replace=os.replace;failed=False
        def fail_once(src,dst):
            nonlocal failed
            if Path(dst)==b and not failed:
                failed=True;raise OSError('simulated disk failure')
            return real_replace(src,dst)
        with patch('os.replace',side_effect=fail_once):
            with self.assertRaises(OSError):self.store.replace_batch(game,[(a,b'changed A'),(b,b'changed B')],'test transaction')
        self.assertEqual((a.read_bytes(),b.read_bytes()),before)
        self.store.replace_batch(game,[(a,b'changed A'),(b,b'changed B')],'test transaction')
        backup=self.store.backups(game['id'])[0]
        self.store.restore(game['id'],backup['id'])
        self.assertEqual((a.read_bytes(),b.read_bytes()),before)

    def testTemporaryInputSettingsRecoverAfterAnInterruptedSession(self):
        game=self.store.import_game(self.source);root=self.store.game_root(game)
        session=root/'Sessions/test';session.mkdir(parents=True)
        original=(Path(game['packagePath'])/'mai2.ini').read_bytes()
        self.store.apply_launch_configs(game,session,[('mai2.ini',b'[Debug]\nDummyTouchPanel=1\n')])
        self.assertTrue((root/'launch-configs.json').exists())
        Store(self.store.root).restore_launch_configs(game)
        self.assertEqual((Path(game['packagePath'])/'mai2.ini').read_bytes(),original)
        self.assertFalse((root/'launch-configs.json').exists())

    def testInputRecoveryPreservesExternalChanges(self):
        game=self.store.import_game(self.source);root=self.store.game_root(game)
        session=root/'Sessions/test';session.mkdir(parents=True)
        self.store.apply_launch_configs(game,session,[('mai2.ini',b'temporary')])
        path=Path(game['packagePath'])/'mai2.ini';path.write_bytes(b'external edit')
        self.store.restore_launch_configs(game)
        self.assertEqual(path.read_bytes(),b'external edit')

    def testNewOptionChartAndMetadataShareOneRestorePoint(self):
        folder=self.source/'option/A007/music/music000123'
        folder.mkdir(parents=True)
        original=b'<MusicData><name><id>123</id><str>Old</str></name><notesData><Notes><file><path/></file><maxNotes>0</maxNotes><isEnable>false</isEnable></Notes></notesData></MusicData>'
        (folder/'Music.xml').write_bytes(original)
        game=self.store.import_game(self.source)
        xml=Path(game['packagePath'])/'option/A007/music/music000123/Music.xml'
        target=xml.with_name('000123_00.ma2')
        chart=b'VERSION\t0.00.00\t1.04.00\r\nNMTAP\t0\t0\t1\r\nT_NUM_ALL\t1\r\n'
        draft=original.replace(b'Old',b'New').replace(b'false',b'true')
        request=dict(path=str(xml),sha256=digest(xml),data=base64.b64encode(draft),
                     charts=[dict(level=0,side='',sha256=None,data=base64.b64encode(chart))])
        music.save_draft(self.store,game,request)
        self.assertEqual(target.read_bytes(),chart)
        self.assertIn(b'<maxNotes>1</maxNotes>',xml.read_bytes())
        self.assertIn(b'<str>New</str>',xml.read_bytes())
        self.assertEqual(xml,(folder/'Music.xml').resolve())
        with self.assertRaisesRegex(ValueError,'已变化'):
            music.save_draft(self.store,game,request)
        self.store.restore(game['id'],self.store.backups(game['id'])[0]['id'])
        self.assertFalse(target.exists())
        self.assertEqual(xml.read_bytes(),original)


    def testMuModOnlyPackageKeepsModFlagAndRecognizesTheCompatibleAssembly(self):
        from compatibility import detect_mod
        preferred={'Mods/AquaMai.dll':dict(present=True,version='1.9.20'),'Mods/MuMod.dll':dict(present=True,version='1.0.0')}
        fallback={'Mods/AquaMai.dll':dict(present=False),'Mods/MuMod.dll':dict(present=True,version='1.0.0')}
        self.assertEqual(detect_mod(self.source,preferred),dict(kind='AquaMai',dll='Mods/AquaMai.dll',version='1.9.20'))
        self.assertEqual(detect_mod(self.source,fallback),dict(kind='MuMod',dll='Mods/MuMod.dll',version='1.0.0'))
        self.assertIsNone(detect_mod(self.source,dict()))
        mods=self.source/'Mods';mods.mkdir(exist_ok=True)
        (mods/'MuMod.dll').write_bytes(b'user supplied MuMod')
        game=self.store.import_game(self.source)
        self.assertTrue(game['hasAquaMai'])

    def testReimportRefreshKeepsModFlagInSyncWithTheOwnedCopy(self):
        game=self.store.import_game(self.source)
        self.assertFalse(game['hasAquaMai'])
        for base in [self.source,Path(game['packagePath'])]:
            mods=base/'Mods';mods.mkdir(exist_ok=True)
            (mods/'MuMod.dll').write_bytes(b'user supplied MuMod')
        again=self.store.import_game(self.source)
        self.assertEqual(again['id'],game['id'])
        self.assertTrue(again['hasAquaMai'])

    def testInspectionReportsMuModWhenThatAssemblyIsShipped(self):
        (self.source/'Mods').mkdir(exist_ok=True)
        (self.source/'Mods/MuMod.dll').write_bytes(b'user supplied MuMod')
        def meta(path):
            name=path.name
            version={'MuMod.dll':'1.0.0','MelonLoader.dll':'0.6.4'}.get(name,'1.9.20' if name=='AquaMai.dll' else None)
            return dict(present=path.is_file(),architecture='x64' if name!='MuMod.dll' else 'x86',version=version,imports=[])
        with patch('compatibility.pe_metadata',side_effect=meta):
            report=compatibility.inspect_package(self.source)
        self.assertEqual(report['modKind'],'MuMod')
        self.assertEqual(report['modVersion'],'1.0.0')
        self.assertIn('MuMod 1.0.0',report['profileName'])
        self.assertNotIn('Mods/AquaMai.dll 或 Mods/MuMod.dll',report['issues'])

class StartupCheckTests(unittest.TestCase):
    def setUp(self):
        self.check=dict(url='https://example.test/check',expectedValue='1')

    def testRequiresConsentBeforeAnyNetwork(self):
        with patch('startup_checks.urllib.request.build_opener') as opener:
            with self.assertRaisesRegex(ValueError,'允许'):
                startup_checks.preflight({},[self.check])
            opener.assert_not_called()

    def testDisabledVendorResponseCannotPassPreflight(self):
        with patch('startup_checks.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=BytesIO(b'0\n')
            with self.assertRaisesRegex(ValueError,'未允许启动'):
                startup_checks.preflight({'allowedStartupChecks':[self.check['url']]},[self.check])
            opener.return_value.open.assert_called_once_with(self.check['url'],timeout=12)

if __name__=='__main__':unittest.main()
