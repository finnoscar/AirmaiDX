"""Run owned input receiver logic on macOS .NET, without loading game DLLs."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--sdk',type=Path,default=Path(os.environ.get('AIRMAIDX_DOTNET', shutil.which('dotnet') or 'dotnet')).resolve().parent)
    args=parser.parse_args();sdk=args.sdk.resolve()
    if not (sdk/'dotnet').is_file(): parser.error('Pass --sdk with the path to an installed .NET SDK directory.')
    version=sorted((sdk/'sdk').iterdir())[-1]
    runtime=sorted((sdk/'shared/Microsoft.NETCore.App').iterdir())[-1].name
    framework=sorted((sdk/'packs/Microsoft.NETCore.App.Ref').iterdir())[-1]
    refs=list(next((framework/'ref').iterdir()).glob('*.dll'))
    output=ROOT/'build/controller-native-test';output.mkdir(parents=True,exist_ok=True)
    subprocess.run([str(sdk/'dotnet'),str(version/'Roslyn/bincore/csc.dll'),'/nologo','/target:exe','/nostdlib+',
        '/out:'+str(output/'Test.dll'),*['/reference:'+str(r) for r in refs],str(ROOT/'Native/AirmaiControllerInput.cs'),
        str(ROOT/'Tests/Native/ControllerStubs.cs'),str(ROOT/'Tests/Native/ControllerInputTests.cs')],check=True)
    (output/'Test.runtimeconfig.json').write_text(json.dumps(dict(runtimeOptions=dict(framework=dict(name='Microsoft.NETCore.App',version=runtime)))))
    subprocess.run([str(sdk/'dotnet'),str(output/'Test.dll')],check=True)

if __name__=='__main__':main()
