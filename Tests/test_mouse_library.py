from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Service'))
from storage import Store, DEFAULT_SETTINGS
import runtime

class MouseAndLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.base=Path(self.temporary.name).resolve();self.store=Store(self.base/'private')
        self.game=dict(id='a'*32,name='test',ready=False,settings=dict(DEFAULT_SETTINGS))
        self.folder=self.store.game_root(self.game);self.pkg=self.folder/'HDD/Package';self.pkg.mkdir(parents=True)
        self.game['packagePath']=str(self.pkg)
        self.original=self.base/'original';self.original.mkdir();(self.original/'keep').write_bytes(b'original')
        self.game['sourcePath']=str(self.original);self.store.update(self.game)
        self.runtime=self.base/'runtime';(self.runtime/'helpers').mkdir(parents=True)
        (self.runtime/'helpers/AirmaiMouseInput.dll').write_bytes(b'owned module')
        self.drive=self.folder/'Prefix/drive_c';self.drive.mkdir(parents=True)
        (self.pkg/'Mods').mkdir()

    def testNewDefaultsAndOlderExplicitOptOut(self):
        self.assertTrue(DEFAULT_SETTINGS['networkEnabled']);self.assertTrue(DEFAULT_SETTINGS['mouseEnabled'])
        old=dict(self.game,settings=dict(networkEnabled=False,hdxEnabled=False))
        self.store.db.write_text(json.dumps([old]))
        settings=self.store.library()[0]['settings']
        self.assertFalse(settings['networkEnabled']);self.assertFalse(settings['hdxEnabled']);self.assertTrue(settings['mouseEnabled'])

    def testMouseStaysLoadedForLiveSwitchingAndRespectsOptOut(self):
        target=self.pkg/'Mods/AirmaiMouseInput.dll';cfg=self.drive/'AirmaiMouse.cfg'
        for hardware in [False,True,False]:
            active=runtime.configure_mouse(self.runtime,self.pkg,self.drive,self.game['settings'],hardware,'ja')
            self.assertTrue(active);self.assertTrue(target.exists());self.assertTrue(cfg.exists())
            if active:self.assertEqual(cfg.read_text().splitlines(),['AIRMAI_MOUSE_V1','ja'])
        settings=dict(self.game['settings'],mouseEnabled=False)
        self.assertFalse(runtime.configure_mouse(self.runtime,self.pkg,self.drive,settings,False))
        self.assertFalse(target.exists());self.assertFalse(cfg.exists())

    def testNewSessionDiscardsPreviousConsumerStatus(self):
        state=self.drive/'AirmaiMouse-state.txt';state.write_text('AIRMAI_MOUSE_STATE_V1\nhdx\n')
        runtime.configure_mouse(self.runtime,self.pkg,self.drive,self.game['settings'],True)
        self.assertFalse(state.exists())

    def testConsumerModeRejectsStaleMalformedAndMissingStatus(self):
        path=self.drive/'AirmaiMouse-state.txt'
        self.assertIsNone(runtime.mouse_mode(path))
        for mode in ['mouse','hdx','adx','keyboard']:
            path.write_text('AIRMAI_MOUSE_STATE_V1\n'+mode+'\n')
            self.assertEqual(runtime.mouse_mode(path),mode)
        os.utime(path,(1,1));self.assertIsNone(runtime.mouse_mode(path))
        for data in ['AIRMAI_MOUSE_STATE_V1\nunknown\n','other\nmouse\n','AIRMAI_MOUSE_STATE_V1\nmouse\nextra\n']:
            path.write_text(data);self.assertIsNone(runtime.mouse_mode(path))

    def testLiveSessionUsesConsumerModeInsteadOfStartupDetection(self):
        session=self.folder/'Sessions/test';session.mkdir(parents=True)
        (self.folder/'session.json').write_text(json.dumps(dict(manager_pid=123,phase='running',input_mode='mouse',session=str(session))))
        status=self.drive/'AirmaiMouse-state.txt'
        with patch('runtime.os.kill'),patch('runtime.subprocess.check_output',return_value='AirmaiDX --session '+self.game['id']):
            for mode in ['hdx','mouse','adx','mouse']:
                status.write_text('AIRMAI_MOUSE_STATE_V1\n'+mode+'\n')
                self.assertEqual(runtime.session_status(self.store,self.game)['inputMode'],mode)

    def testDeleteMovesOnlyOwnedGameAndRemovesRecord(self):
        (self.pkg/'save.dat').write_bytes(b'save')
        trash=self.base/'trash';trash.mkdir()
        def move(path):
            dest=trash/path.name;path.rename(dest);return dest
        self.assertTrue(self.store.delete_game(self.game['id'],move))
        self.assertFalse(self.folder.exists());self.assertEqual(self.store.library(),[])
        self.assertEqual((trash/self.game['id']/'HDD/Package/save.dat').read_bytes(),b'save')
        self.assertEqual((self.original/'keep').read_bytes(),b'original')

    def testRemovingDirectHDDEntryOnlyTrashesRuntimeMetadata(self):
        self.game.update(storageMode='direct',packagePath=str(self.original))
        self.store.update(self.game)
        trash=self.base/'removed-runtime'
        def move(path):
            self.assertEqual(path,self.folder)
            path.rename(trash)
            return trash
        self.store.delete_game(self.game['id'],move)
        self.assertEqual(self.store.library(),[])
        self.assertTrue(trash.is_dir())
        self.assertEqual((self.original/'keep').read_bytes(),b'original')

    def testWineMappingUsesAnExternalFolderWithAnyNameAndCanReconnect(self):
        package=self.base/'External SSD/音游 HDD'
        package.mkdir(parents=True)
        (package/'save.dat').write_bytes(b'save')
        (package.parent/'license').mkdir()
        runtime.map_game_directory(self.folder,package,self.drive)
        mapped=self.drive/'AirmaiDX/Package'
        self.assertEqual(mapped.resolve(),package)
        self.assertEqual((self.drive/'AirmaiDX/license').resolve(),package.parent/'license')
        self.assertEqual((mapped/'save.dat').read_bytes(),b'save')
        detached=package.parent.with_name('disconnected')
        package.parent.rename(detached)
        self.assertFalse(mapped.exists())
        detached.rename(package.parent)
        self.assertEqual((mapped/'save.dat').read_bytes(),b'save')
        runtime.map_game_directory(self.folder,package,self.drive)
        self.assertTrue(mapped.is_symlink())

    def testTrashOrDatabaseFailureRetainsGame(self):
        with patch('runtime.session_status',return_value=dict(running=False)):
            def denied(path):raise PermissionError('trash denied')
            with self.assertRaises(PermissionError):self.store.delete_game(self.game['id'],denied)
            self.assertTrue(self.folder.exists());self.assertEqual(len(self.store.library()),1)
            dest=self.base/'moved'
            def move(path):path.rename(dest);return dest
            with patch('storage.atomic_json',side_effect=OSError('database denied')):
                with self.assertRaises(OSError):self.store.delete_game(self.game['id'],move)
            self.assertTrue(self.folder.exists());self.assertFalse(dest.exists());self.assertEqual(len(self.store.library()),1)

    def testDeletionRefusesRunningGameAndEscapingPaths(self):
        with patch('runtime.session_status',return_value=dict(running=True)),patch('pathlib.Path.rename') as move:
            with self.assertRaises(ValueError):self.store.delete_game(self.game['id'],lambda p:p.rename(self.base/'trash'))
            move.assert_not_called()
        self.game['packagePath']=str(self.original);self.store.update(self.game)
        with self.assertRaisesRegex(ValueError,'路径异常'):self.store.delete_game(self.game['id'],lambda p:p)
        self.assertTrue((self.original/'keep').exists())

    def testDeletionRefusesLiveSessionLeaseEvenIfStatusLooksStopped(self):
        import fcntl
        with (self.store.root/'active-game.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with patch('runtime.session_status',return_value=dict(running=False)):
                with self.assertRaisesRegex(ValueError,'退出清理'):self.store.delete_game(self.game['id'],lambda p:p)
        self.assertTrue(self.folder.exists())
