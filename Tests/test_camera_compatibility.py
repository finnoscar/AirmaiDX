from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Service'))
import camera_compatibility as camera
import game_identity
from storage import Store


class CameraCompatibilityTests(unittest.TestCase):
    def testOnlyTheCameraToggleIsChangedAndExactOriginalIsRestored(self):
        text=('# camera settings\r\ncommon:\r\n  dummyLogin:\r\n    enable: false # normal login\r\n'
              '  customCameraId:\r\n    enable: true # physical mapping\r\n    chimeCameraId: 0\r\n'
              'fix:\r\n  enabled: true\r\n')
        raw=text.encode('utf-8-sig')
        expected=text.replace('true # physical mapping','false # physical mapping').encode('utf-8-sig')
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder); package=base/'HDD'; config=package/camera.CONFIG; config.parent.mkdir(parents=True)
            (package/'Mods').mkdir();(package/'Mods/Sinmai-Assist.dll').touch();config.write_bytes(raw)
            store=Store(base/'AirmaiDX');game=dict(id='a'*32,packagePath=str(package))
            root=store.game_root(game);session=root/'Sessions/20261120-220800-000000';session.mkdir(parents=True)
            with patch('camera_compatibility.affected_mod',return_value=True):
                result=camera.launch_override(package)
            self.assertEqual(result,expected)
            with self.assertRaises(ValueError):store.checked_file(game,camera.CONFIG)
            store.apply_launch_configs(game,session,[(camera.CONFIG,result)])
            self.assertEqual(config.read_bytes(),expected)
            store.restore_launch_configs(game)
            self.assertEqual(config.read_bytes(),raw)
            self.assertIn(camera.CONFIG,json.loads((session/'configuration-restored.json').read_text())['restored'])

    def testUnknownModAndLinkedConfigAreNotModified(self):
        with tempfile.TemporaryDirectory() as folder:
            package=Path(folder)/'HDD';config=package/camera.CONFIG;config.parent.mkdir(parents=True)
            (package/'Mods').mkdir();(package/'Mods/Sinmai-Assist.dll').write_bytes(b'not the recognized assembly')
            text='common:\n  customCameraId:\n    enable: true\n'
            config.write_text(text)
            self.assertIsNone(camera.launch_override(package))
            outside=Path(folder)/'outside';outside.write_text(text)
            config.unlink();config.symlink_to(outside)
            self.assertIsNone(camera.launch_override(package))
            store=Store(Path(folder)/'AirmaiDX');game=dict(id='a'*32,packagePath=str(package))
            with self.assertRaises(ValueError):store.checked_file(game,camera.CONFIG,launch=True)

    def testAmbiguousYamlIsNotRewritten(self):
        data=b'common:\n  customCameraId:\n    enable: true\n    enable: false\n'
        self.assertIsNone(camera.disable_camera_override(data))


class GameIdentityTests(unittest.TestCase):
    def testReadsOnlyLiteralRuntimeIdentityFieldsWithoutRunningTheAssembly(self):
        def field(name):return SimpleNamespace(Name=name,Flags=SimpleNamespace(fdLiteral=True))
        def constant(row,kind,data):
            return SimpleNamespace(Parent=SimpleNamespace(row=row),Type=kind,Value=SimpleNamespace(value=data))
        gid=field('GameIDStr');version=field('NowGameVersion')
        owner=SimpleNamespace(TypeName='ConstParameter',TypeNamespace='MAI2System',
                              FieldList=[SimpleNamespace(row=x) for x in [gid,version]])
        constants=[constant(gid,14,'SDGB'.encode('utf-16-le')),constant(version,9,(25500).to_bytes(4,'little'))]
        image=SimpleNamespace(net=SimpleNamespace(mdtables=SimpleNamespace(TypeDef=[owner],Constant=SimpleNamespace(rows=constants))))
        with tempfile.TemporaryDirectory() as folder,patch('game_identity.dnfile.dnPE') as pe:
            pkg=Path(folder);assembly=pkg/'Sinmai_Data/Managed/Assembly-CSharp.dll';assembly.parent.mkdir(parents=True);assembly.write_bytes(b'data')
            pe.return_value.__enter__.return_value=image
            self.assertEqual(game_identity.identity(pkg),('SDGB','2.55.00'))
