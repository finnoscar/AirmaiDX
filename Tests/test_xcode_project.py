"""Keep IDE navigation bounded to sources, never runtime/Prefix directories."""
from pathlib import Path
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Tools'))
import generate_xcode_project as project
from sync_editor_preview import sync, project_sources


@unittest.skipUnless(sys.platform=='darwin','OpenStep project validation uses plutil')
class XcodeProjectTests(unittest.TestCase):
    def testNativeProjectHasNoPackageRootAndOnlyExplicitSourceReferences(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for folder in ['Sources/AirmaiDX','Sources/AirmaiDXMobile','Sources/AirmaiCore','Sources/AirmaiEditorPreview',
                           'Sources/AirmaiTouchKit','Sources/AirmaiMobileCore','Generated/EditorPreview',
                           'Tests/AirmaiCoreTests','Tests/AirmaiTouchKitTests','Service','Native','Tools']:
                path=root/folder;path.mkdir(parents=True)
                if folder.startswith(('Sources','Generated','Tests')):(path/'Example.swift').write_text('// fixture\n')
            (root/'Generated/EditorPreview/StaleKernel.swift').write_text('// not in manifest\n')
            (root/'Sources/AirmaiDXMobile/Info.plist').write_text('<plist/>\n')
            (root/'Sources/AirmaiDXMobile/AirmaiDXMobile.entitlements').write_text('<plist/>\n')
            assets = root/'Sources/AirmaiDXMobile/Assets.xcassets';assets.mkdir()
            (assets/'Contents.json').write_text('{}\n')
            resources = root/'Sources/AirmaiCore/Resources'
            for code in ['zh-Hans', 'en', 'ja']:
                folder = resources/(code+'.lproj');folder.mkdir(parents=True)
                (folder/'Localizable.strings').write_text('"Key" = "Value";\n')
            for name in ['AquaMaiMetadata.json', 'AquaMaiTranslations.json', 'AquaMai-Documentation-LICENSE.txt', 'AquaMai-Documentation-NOTICE.txt']:
                (resources/name).write_text('{}')
            with patch.object(project,'ROOT',root),patch.object(project,'sync_project',return_value=[(root/'original.swift','Example.swift')]),contextlib.redirect_stdout(io.StringIO()):
                project.generate()
                path=root/'AirmaiDX.xcodeproj/project.pbxproj';before=path.read_bytes();modified=path.stat().st_mtime_ns
                project.generate()
                self.assertEqual(path.read_bytes(),before)
                self.assertEqual(path.stat().st_mtime_ns,modified)
            data=json.loads(subprocess.check_output(['/usr/bin/plutil','-convert','json','-o','-',str(path)]))
            objects=data['objects'];types={o['isa'] for o in objects.values()}
            self.assertNotIn('XCLocalSwiftPackageReference',types)
            self.assertNotIn('XCSwiftPackageProductDependency',types)
            self.assertNotIn('PBXFileSystemSynchronizedRootGroup',types)
            localization = [o for o in objects.values() if o['isa']=='PBXVariantGroup']
            self.assertEqual(len(localization), 1)
            self.assertEqual({objects[ref]['name'] for ref in localization[0]['children']}, {'zh-Hans', 'en', 'ja'})
            phases = [o for o in objects.values() if o['isa']=='PBXResourcesBuildPhase']
            self.assertEqual(len(phases), 3)  # macOS app/tests plus iOS assets
            self.assertEqual(sorted(len(o['files']) for o in phases), [1, 5, 6])
            icons=[o for o in objects.values() if o.get('lastKnownFileType')=='folder.iconcomposer.icon']
            self.assertEqual([o['path'] for o in icons], ['Resources/AppIcon.icon'])
            targets={o['name']:o for o in objects.values() if o['isa']=='PBXNativeTarget'}
            self.assertEqual(set(targets),{'AirmaiDX','AirmaiDX iOS','AirmaiDXTests','AirmaiTouchKitTests',
                                           'AirmaiCore','AirmaiEditorPreview','AirmaiTouchKit','AirmaiMobileCore'})
            configs=[o['buildSettings'] for o in objects.values() if o['isa']=='XCBuildConfiguration']
            self.assertEqual(sum(c.get('MACH_O_TYPE')=='staticlib' for c in configs),8)
            for o in objects.values():
                if o['isa']=='PBXBuildFile':self.assertIn(o['fileRef'],objects)
                if o['isa']=='PBXFileReference':
                    self.assertNotEqual(o.get('path'),'Package.swift')
                    self.assertNotEqual(o.get('path'),'StaleKernel.swift')
                    self.assertFalse(o.get('path','').startswith(('build/','dist/','Tools/.venv')))

    def testEditorSyncDoesNotRewriteUnchangedGeneratedSources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);original=root/'Kernel.swift';original.write_text('struct OriginalKernel {}\n')
            output=root/'Generated';sync(output,[(original,'Kernel.swift')])
            generated=output/'Kernel.swift';modified=generated.stat().st_mtime_ns
            sync(output,[(original,'Kernel.swift')]);self.assertEqual(generated.stat().st_mtime_ns,modified)
            original.write_text('struct OriginalKernel { let changed = true }\n')
            sync(output,[(original,'Kernel.swift')]);self.assertIn('changed = true',generated.read_text())

    def testOriginalEditorManifestHasUniqueExistingSourceFiles(self):
        sources=project_sources()
        self.assertEqual(len(sources),11)
        self.assertEqual(len({name for _,name in sources}),len(sources))
        self.assertTrue(all(path.is_file() for path,_ in sources))


if __name__=='__main__':unittest.main()
