"""Version/region selection is based on actual resources, not folder naming."""
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Service'))
from artwork import metadata, select_logo


class ArtworkTests(unittest.TestCase):
    def testChinaDoesNotSelectJapaneseArtwork(self):
        names = ['kari_LOGOv170', 'UI_ADV_Img_Logo150', 'UI_ADV_Img_Logo150_Mask',
                 'UI_CMN_TabTitle_MaimaiTitle_Ver250']
        self.assertEqual(select_logo(names, 'CHN', '1.50.00'), ('UI_ADV_Img_Logo150', '1.50.00'))
        self.assertEqual(select_logo(names, 'JPN', '1.70.00'), ('kari_LOGOv170', '1.70.00'))
        self.assertIsNone(select_logo(['kari_LOGOv170'], 'CHN', '1.50.00')[0])

    def testUniqueCurrentTitleCorrectsStaleRomConfig(self):
        self.assertEqual(select_logo(['kari_LOGOv170', 'T_UI_LogoKariv170'], 'JPN', '1.10.00'),
                         ('kari_LOGOv170', '1.70.00'))
        self.assertIsNone(select_logo(['kari_LOGOv160', 'kari_LOGOv170'], 'JPN', '1.10.00')[0])

    def testUnknownRegionAndEffectAreNotAssumedToBeTheTitle(self):
        self.assertIsNone(select_logo(['UI_ADV_Img_Logo150_eff_00'], 'CHN', '1.50.00')[0])
        self.assertIsNone(select_logo(['UI_ADV_Img_Logo150'], '', '1.50.00')[0])

    def testRuntimeIdentityOverridesAStaleJapaneseSplashRomConfig(self):
        with tempfile.TemporaryDirectory() as temporary:
            package=Path(temporary)
            rom=package/'Sinmai_Data/StreamingAssets/RomConfig.xml';rom.parent.mkdir(parents=True)
            rom.write_text('<RomConfig><projectName>maimaiDx Splash</projectName><region>JPN</region>'
                           '<version><major>1</major><minor>10</minor><release>0</release></version></RomConfig>')
            self.assertEqual(metadata(package,{},('SDGB','2.55.00')),('舞萌 DX','CHN','2.55.00'))
            self.assertIsNone(select_logo(['UI_ADV_Img_Logo110'],'CHN','2.55.00','2.55.00')[0])
            self.assertEqual(select_logo(['UI_ADV_Img_Logo110','UI_ADV_Img_Logo155'], 'CHN', '2.55.00', '2.55.00'),
                             ('UI_ADV_Img_Logo155', '1.55.00'))

    def testSDEZUsesItsExistingPublicReleaseLabel(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            self.assertEqual(metadata(package, {'gameVersion': '1.65.00'}, ('SDEZ', '2.65.00')),
                             ('', '', '1.65.00'))

    def testRomRegionOverridesUserFolderName(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / 'SDEZ170'
            path = package / 'Sinmai_Data/StreamingAssets/RomConfig.xml'
            path.parent.mkdir(parents=True)
            path.write_text('<RomConfig><projectName>舞萌DX 2025</projectName><region>CHN</region>'
                            '<version><major>1</major><minor>50</minor><release>0</release></version></RomConfig>')
            self.assertEqual(metadata(package, {}), ('舞萌DX 2025', 'CHN', '1.50.00'))


if __name__ == '__main__':
    unittest.main()
