from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Service'))
from storage import Store
from music_assets import transfer, media, source_files


class MusicAssetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.store = Store(self.base / 'private')
        self.game = dict(id='a' * 32, name='fixture', packagePath='', settings={}, ready=False)
        self.package = self.store.game_root(self.game) / 'HDD/Package'
        self.game['packagePath'] = str(self.package)
        self.origin = self.package / 'Sinmai_Data/StreamingAssets/A000'
        self.target = self.package / 'option/A999'
        self.target.mkdir(parents=True)
        self.folder = self.origin / 'music/music000008'
        self.folder.mkdir(parents=True)
        self.xml = self.folder / 'Music.xml'
        self.xml.write_text('<MusicData><name><id>8</id><str>Song</str></name><cueName><id>8</id></cueName><movieName><id>9</id></movieName></MusicData>')
        (self.folder / '000008_00.ma2').write_bytes(b'original chart')
        for name, data in [('SoundData/music000008.awb', b'audio'), ('MovieData/000009.usm', b'movie'),
                           ('AssetBundleImages/jacket/ui_jacket_000008.png', b'not yet an image')]:
            file = self.origin / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        self.store.update(self.game)

    def request(self, action='copy', destination=None):
        return dict(path=str(self.xml), action=action, destination=str(destination or self.target))

    def testCopyIncludesSharedResourcesAndOneRestorePoint(self):
        originals = {str(p.relative_to(self.origin)): p.read_bytes() for p in self.origin.rglob('*') if p.is_file()}
        result = transfer(self.store, self.game, self.request())
        self.assertEqual(result['files'], 5)
        for name, data in originals.items():
            self.assertEqual((self.target / name).read_bytes(), data)
        backups = self.store.backups(self.game['id'])
        self.assertEqual(len(backups), 1)
        self.store.restore(self.game['id'], backups[0]['id'])
        self.assertEqual([p for p in self.target.rglob('*') if p.is_file()], [])
        for name, data in originals.items():
            self.assertEqual((self.origin / name).read_bytes(), data)

    def testConflictPreflightDoesNotPartiallyCopy(self):
        collision = self.target / 'MovieData/000009.usm'
        collision.parent.mkdir()
        collision.write_bytes(b'different movie')
        with self.assertRaisesRegex(ValueError, '同名文件'):
            transfer(self.store, self.game, self.request())
        self.assertEqual([p for p in self.target.rglob('*') if p.is_file()], [collision])
        self.assertEqual(collision.read_bytes(), b'different movie')

    def testExportPreservesLayoutAndRefusesOverwrite(self):
        destination = self.base / 'song.zip'
        transfer(self.store, self.game, self.request('export', destination))
        before = destination.read_bytes()
        with zipfile.ZipFile(destination) as archive:
            self.assertEqual(archive.read('music/music000008/000008_00.ma2'), b'original chart')
            self.assertEqual(archive.read('SoundData/music000008.awb'), b'audio')
            self.assertEqual(len(archive.namelist()), 5)
        with self.assertRaises(ValueError):
            transfer(self.store, self.game, self.request('export', destination))
        self.assertEqual(destination.read_bytes(), before)

    def testSourceAndTargetLinksAreRejected(self):
        (self.folder / 'linked.ma2').symlink_to(self.xml)
        with self.assertRaisesRegex(ValueError, '链接'):
            transfer(self.store, self.game, self.request())
        (self.folder / 'linked.ma2').unlink()
        (self.target / 'music').symlink_to(self.base, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, '链接'):
            transfer(self.store, self.game, self.request())

    def testSelectedPackMediaWinsOverOtherPacks(self):
        own = self.target / 'SoundData/music000008.awb'
        own.parent.mkdir()
        own.write_bytes(b'expansion audio')
        song = self.target / 'music/music000008'
        song.mkdir(parents=True)
        xml = song / 'Music.xml'
        xml.write_bytes(self.xml.read_bytes())
        self.assertEqual(source_files(self.package, xml)['SoundData/music000008.awb'], own)

    def testRunningGameBlocksCopyButAllowsReadOnlyExport(self):
        with patch.object(self.store, 'assert_stopped', side_effect=ValueError('游戏运行中')):
            with self.assertRaisesRegex(ValueError, '运行中'):
                transfer(self.store, self.game, self.request())
            transfer(self.store, self.game, self.request('export', self.base / 'song.zip'))
        self.assertFalse((self.target / 'music').exists())

    def testCopyFailureRollsBackFilesAndEmptyDirectories(self):
        original_replace = Path.replace
        def fail(path, destination):
            if str(destination).endswith('000008_00.ma2'):
                raise OSError('simulated write failure')
            return original_replace(path, destination)
        with patch.object(Path, 'replace', fail), self.assertRaises(OSError):
            transfer(self.store, self.game, self.request())
        self.assertEqual(list(self.target.iterdir()), [])

    def testCoverDecodesAndInvalidatesCache(self):
        from PIL import Image
        source = self.origin / 'AssetBundleImages/jacket/ui_jacket_000008.png'
        Image.new('RGB', (800, 800), 'red').save(source)
        request = dict(path=str(self.xml), kind='cover')
        first = media(self.store, self.game, self.base, request)
        with Image.open(first['path']) as result:
            self.assertEqual(result.size, (512, 512))
        Image.new('RGB', (200, 200), 'blue').save(source)
        second = media(self.store, self.game, self.base, request)
        self.assertNotEqual(first['path'], second['path'])
        self.assertIsNone(second['issue'])

    def testMissingDecoderProducesAnExplicitListeningIssue(self):
        result = media(self.store, self.game, self.base, dict(path=str(self.xml), kind='audio'))
        self.assertIsNone(result['path'])
        self.assertIn('试听组件', result['issue'])
