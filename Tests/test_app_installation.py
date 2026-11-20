import importlib.util
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1] / 'Tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('install_app', TOOLS / 'install_app.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class AppInstallationTests(unittest.TestCase):
    def bundle(self, path, content, identifier=installer.IDENTIFIER):
        (path / 'Contents').mkdir(parents=True)
        (path / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': identifier}))
        (path / 'Contents/version').write_text(content)

    def test_success_retains_only_new_installed_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / 'build.app', root / 'AirmaiDX.app'
            self.bundle(source, 'new')
            self.bundle(destination, 'old')
            installer.replace_app(source, destination, verifier=lambda path: None)
            self.assertEqual((destination / 'Contents/version').read_text(), 'new')
            self.assertEqual(list(root.iterdir()), [destination])

    def test_failed_installed_verification_restores_old_and_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / 'build.app', root / 'AirmaiDX.app'
            self.bundle(source, 'new')
            self.bundle(destination, 'old')

            def verify(path):
                if path == destination:
                    raise RuntimeError('Installed verification failed')

            with self.assertRaises(RuntimeError):
                installer.replace_app(source, destination, verifier=verify)
            self.assertEqual((destination / 'Contents/version').read_text(), 'old')
            self.assertEqual((source / 'Contents/version').read_text(), 'new')
            self.assertEqual(set(root.iterdir()), {source, destination})

    def test_unrelated_app_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / 'build.app', root / 'AirmaiDX.app'
            self.bundle(source, 'new')
            self.bundle(destination, 'other', identifier='com.example.other')
            with self.assertRaises(RuntimeError):
                installer.replace_app(source, destination, verifier=lambda path: None)
            self.assertEqual((destination / 'Contents/version').read_text(), 'other')
            self.assertTrue(source.exists())


if __name__ == '__main__':
    unittest.main()
