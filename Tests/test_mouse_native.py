from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class MouseNativeTests(unittest.TestCase):
    def testOwnedMouseModuleAgainstLegacyAPIStubs(self):
        sdk=Path(os.environ.get('AIRMAIDX_DOTNET', shutil.which('dotnet') or 'dotnet')).resolve().parent
        if not (sdk/'dotnet').is_file():self.skipTest('development .NET SDK unavailable')
        compiler=sorted((sdk/'sdk').glob('*/Roslyn/bincore/csc.dll'))[-1]
        refs=sorted((sdk/'packs/Microsoft.NETCore.App.Ref').glob('*/ref/net*'))[-1]
        version=sorted((sdk/'shared/Microsoft.NETCore.App').iterdir())[-1].name
        with tempfile.TemporaryDirectory() as temporary:
            work=Path(temporary);output=work/'Test.dll'
            result=subprocess.run([str(sdk/'dotnet'),str(compiler),'/nologo','/target:exe','/nostdlib+',
                '/out:'+str(output),*['/reference:'+str(p) for p in refs.glob('*.dll')],
                str(ROOT/'Native/AirmaiMouseInput.cs'),str(ROOT/'Tests/Native/MouseStubs.cs'),
                str(ROOT/'Native/AirmaiControllerInput.cs'),str(ROOT/'Native/AirmaiHdxNativeTouch.cs'),
                str(ROOT/'Tests/Native/MouseInputTests.cs')],capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            (work/'Test.runtimeconfig.json').write_text(json.dumps(dict(runtimeOptions=dict(framework=dict(name='Microsoft.NETCore.App',version=version)))))
            result=subprocess.run([str(sdk/'dotnet'),str(output)],cwd=work,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('checks passed',result.stdout)
