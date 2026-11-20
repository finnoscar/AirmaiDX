"""Build a pinned, self-contained macOS HCA/ADX decoder for song listening."""
from pathlib import Path
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import urllib.request

COMMIT = '6802153425adde134e49394fc653455166d7d2f2'
ARCHIVE_SHA256 = '7b80ebbbd32a07d0c7203cfff932cd3a0fca28b165c8f094469080ca1c150bc7'
URL = 'https://codeload.github.com/vgmstream/vgmstream/tar.gz/' + COMMIT


def install(root, runtime):
    work = root / 'work/music-management'
    work.mkdir(parents=True, exist_ok=True)
    archive = work / 'vgmstream-source.tar.gz'
    if not archive.is_file():
        archive.write_bytes(urllib.request.urlopen(URL, timeout=60).read())
    data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
        raise RuntimeError('音频解码组件源码哈希不匹配。')
    source = work / ('vgmstream-' + COMMIT)
    if not source.is_dir():
        with tarfile.open(fileobj=io.BytesIO(data)) as bundle:
            bundle.extractall(work, filter='data')
    build = work / 'decoder-build'
    flags = ['-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_OSX_DEPLOYMENT_TARGET=15.0', '-DCMAKE_OSX_ARCHITECTURES=arm64',
             '-DCMAKE_POLICY_VERSION_MINIMUM=3.5', '-DBUILD_SHARED_LIBS=OFF', '-DBUILD_V123=OFF', '-DBUILD_AUDACIOUS=OFF']
    flags += ['-DUSE_' + name + '=OFF' for name in ['MPEG', 'VORBIS', 'FFMPEG', 'G7221', 'G719', 'ATRAC9', 'CELT', 'SPEEX']]
    subprocess.run(['cmake', '-S', str(source), '-B', str(build), *flags], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['cmake', '--build', str(build), '-j', '4'], check=True, stdout=subprocess.DEVNULL)
    output = runtime / 'helpers/vgmstream-cli'
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(build / 'cli/vgmstream-cli', output)
    subprocess.run(['codesign', '--force', '--sign', '-', str(output)], check=True, capture_output=True)
    licenses = runtime / 'Licenses/vgmstream'
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / 'COPYING', licenses / 'COPYING')
    (licenses / 'source.json').write_text(json.dumps(dict(commit=COMMIT, url=URL, archiveSHA256=ARCHIVE_SHA256,
                                                        buildFlags=flags, binarySHA256=hashlib.sha256(output.read_bytes()).hexdigest()), indent=2) + '\n')
    return output


if __name__ == '__main__':
    import sys
    install(Path(__file__).resolve().parents[1], Path(sys.argv[1]))
