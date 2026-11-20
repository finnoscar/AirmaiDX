"""Check static doc extraction and shipped localization coverage without a DLL."""
from pathlib import Path
import json
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Tools'))
from extract_aquamai_metadata import attribute, string_at


class LocalizationTests(unittest.TestCase):
    def testNamedEnglishIsNeverMistakenForChineseName(self):
        text = '[ConfigSection(defaultOn: true, en: "English", zh: "中文")]'
        attrs, end = attribute(text, 0)
        self.assertNotIn('name', attrs)
        self.assertEqual(attrs['en'], 'English')
        self.assertEqual(attrs['zh'], '中文')
        self.assertEqual(text[end:], ']')

    def testPositionalRawAndVerbatimDocumentation(self):
        text = '[ConfigEntry("名称", "English", zh: """\n    第一行\n    第二行\n    """)]'
        attrs, _ = attribute(text, 0)
        self.assertEqual(attrs['name'], '名称')
        self.assertEqual(attrs['en'], 'English')
        self.assertEqual(attrs['zh'], '第一行\n第二行')
        self.assertEqual(string_at('@"a ""quoted"" path"', 0)[0], 'a "quoted" path')

    def testResourcesCoverCompiledUIAndHaveMatchingFormatArguments(self):
        tables = []
        for code in ['zh-Hans', 'en', 'ja']:
            text = (ROOT / f'Sources/AirmaiCore/Resources/{code}.lproj/Localizable.strings').read_text()
            pairs = re.findall(r'("(?:[^"\\]|\\.)*")\s*=\s*("(?:[^"\\]|\\.)*");', text)
            table = {json.loads(k): json.loads(v) for k, v in pairs}
            self.assertEqual(len(table), len(pairs), 'duplicate key')
            self.assertGreater(len(table), 340)
            for key, value in table.items():
                self.assertEqual(sorted(re.findall(r'%(?:lld|@)', key)), sorted(re.findall(r'%(?:lld|@)', value)), key)
            tables.append(table)
        self.assertEqual(set(tables[0]), set(tables[1]))
        self.assertEqual(set(tables[0]), set(tables[2]))

    def testJapaneseDocsAndOriginalLicenseShipWithApp(self):
        resources = ROOT / 'Sources/AirmaiCore/Resources'
        metadata = json.loads((resources / 'AquaMaiMetadata.json').read_text())
        translations = json.loads((resources / 'AquaMaiTranslations.json').read_text())
        for key in metadata['sections']:
            self.assertTrue(translations['sections'][key]['title']['ja'], key)
            self.assertTrue(translations['sections'][key]['help']['ja'], key)
        self.assertGreaterEqual(len(translations['entryHelp']), 150)
        self.assertTrue((resources / 'AquaMai-Documentation-LICENSE.txt').is_file())
        self.assertIn('Apache', (resources / 'AquaMai-Documentation-NOTICE.txt').read_text())


if __name__ == '__main__': unittest.main()
