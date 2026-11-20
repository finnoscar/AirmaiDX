"""Fixed-base native rebase regression checks with a self-authored PE fixture."""
from pathlib import Path
import json
import hashlib
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Service'))
from rebase_pe import pe_info, needs_rebase, rebase, SAFE_BASE
from compatibility import apply_native_rebase


def build_pe(image_base=0x7ffa58ac0000, dllchar=0x20):
    """Minimal PE32+ with .text containing one absolute pointer to the image."""
    pointer = image_base + 0x1000
    section_alignment = 0x1000
    file_alignment = 0x200
    text_va = 0x1000
    text_raw = 0x200
    text_size = 0x10
    size_of_image = 0x2000
    blob = bytearray(0x400)
    blob[0:2] = b'MZ'
    struct.pack_into('<I', blob, 0x3c, 0x80)
    blob[0x80:0x84] = b'PE\0\0'
    coff = 0x84
    struct.pack_into('<HHIIIHH', blob, coff, 0x8664, 1, 0, 0, 0, 0xF0, 0x2022)
    opt = coff + 20
    struct.pack_into('<H', blob, opt, 0x20b)                      # Magic
    struct.pack_into('<Q', blob, opt + 24, image_base)            # ImageBase
    struct.pack_into('<I', blob, opt + 32, section_alignment)     # SectionAlignment
    struct.pack_into('<I', blob, opt + 36, file_alignment)        # FileAlignment
    struct.pack_into('<I', blob, opt + 56, size_of_image)         # SizeOfImage
    struct.pack_into('<I', blob, opt + 60, 0x200)                 # SizeOfHeaders
    struct.pack_into('<H', blob, opt + 68, 3)                     # Subsystem
    struct.pack_into('<H', blob, opt + 70, dllchar)               # DllCharacteristics
    struct.pack_into('<I', blob, opt + 108, 16)                   # NumberOfRvaAndSizes
    section = opt + 0xF0
    blob[section:section + 8] = b'.text\0\0\0'
    struct.pack_into('<IIII', blob, section + 8, text_size, text_va, text_raw, 0x200)
    struct.pack_into('<I', blob, section + 36, 0x60000020)
    struct.pack_into('<Q', blob, text_raw, pointer)
    return bytes(blob), pointer


class RebaseTests(unittest.TestCase):
    def testFixedBaseImageIsRebasedWithEveryAbsoluteReference(self):
        blob, pointer = build_pe()
        info = pe_info(blob)
        self.assertEqual(info['image_base'], 0x7ffa58ac0000)
        self.assertTrue(needs_rebase(blob))
        data, changed = rebase(blob)
        self.assertEqual(changed, 1)
        self.assertEqual(struct.unpack_from('<Q', data, 0x200)[0], pointer - 0x7ffa58ac0000 + SAFE_BASE)
        self.assertEqual(pe_info(data)['image_base'], SAFE_BASE)
        self.assertEqual(pe_info(data)['dllchar'] & 0x20, 0)
        self.assertIsNone(rebase(data))  # idempotent

    def testDynamicBaseAndNonHighImagesAreLeftUntouched(self):
        for dllchar in [0x60, 0x00, 0x160]:
            blob, _ = build_pe(dllchar=dllchar)
            self.assertFalse(needs_rebase(blob))
            self.assertIsNone(rebase(blob))

    def testMalformedOrNonPEFilesRaiseWithoutWrites(self):
        with self.assertRaises(ValueError):
            pe_info(b'not a PE')
        with self.assertRaises(ValueError):
            rebase(b'MZ' + b'\x00' * 100)

    def testApplyOnlyChangesOwnedCopiesWithBackupsAndIdempotence(self):
        from storage import Store
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'private')
            root = store.root / 'Games' / ('a' * 32)
            package = root / 'HDD/Package'
            package.mkdir(parents=True)
            plugins = package / 'Sinmai_Data/Plugins'
            plugins.mkdir(parents=True)
            target = plugins / 'amdaemon_api.dll'
            blob, pointer = build_pe()
            target.write_bytes(blob)
            game = dict(id='a' * 32, packagePath=str(package), sourcePath='/source', ready=True, settings={})
            store.update(game)
            # An unknown build must never be patched based on flags alone.
            self.assertEqual(apply_native_rebase(store, game), [])
            self.assertEqual(target.read_bytes(), blob)
            with patch.dict('compatibility.NATIVE_REBASE_BUILDS',
                            {'Sinmai_Data/Plugins/amdaemon_api.dll': hashlib.sha256(blob).hexdigest()}, clear=True):
                applied = apply_native_rebase(store, game)
            self.assertEqual(len(applied), 1)
            self.assertEqual(applied[0]['file'], 'Sinmai_Data/Plugins/amdaemon_api.dll')
            self.assertEqual(applied[0]['references'], 1)
            self.assertNotEqual(target.read_bytes(), blob)
            self.assertEqual(apply_native_rebase(store, game), [])
            backups = store.backups(game['id'])
            self.assertEqual(len(backups), 1)
            self.assertTrue(store.restore(game['id'], backups[0]['id']))
            self.assertEqual(target.read_bytes(), blob)

    def testTruncatedHeadersAndSectionsAreRejected(self):
        original, _ = build_pe()
        for length in [0, 32, 100, 150, 300, 800]:
            with self.assertRaises(ValueError):pe_info(original[:length])
        blob = bytearray(original)
        struct.pack_into('<I',blob,0x3c,0xffffffff)
        with self.assertRaises(ValueError):pe_info(blob)

    def testRepairsPreviousCakeCollisionFromVerifiedBackup(self):
        from storage import Store
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'private')
            package=store.root/'Games'/('a'*32)/'HDD/Package'
            plugins=package/'Sinmai_Data/Plugins';plugins.mkdir(parents=True)
            target=plugins/'Cake.dll';original,_=build_pe();target.write_bytes(original)
            game=dict(id='a'*32,packagePath=str(package),sourcePath='/source',ready=True,settings={})
            store.update(game)
            wrong,_=rebase(original);store.replace_with_backup(game,target,wrong)
            name='Sinmai_Data/Plugins/Cake.dll'
            with patch.dict('compatibility.NATIVE_REBASE_BUILDS',{name:hashlib.sha256(original).hexdigest()},clear=True), \
                    patch('compatibility.BROKEN_CAKE_REBASE',hashlib.sha256(wrong).hexdigest()):
                self.assertEqual(len(apply_native_rebase(store,game)),1)
                self.assertEqual(pe_info(target.read_bytes())['image_base'],0x1a0000000)
                self.assertEqual(apply_native_rebase(store,game),[])
                target.write_bytes(wrong)
                for record in (store.game_root(game)/'Backups').glob('*.json'):
                    if json.loads(record.read_text()).get('sha256')==hashlib.sha256(original).hexdigest():
                        record.with_suffix('.backup').write_bytes(b'corrupted')
                with self.assertRaisesRegex(RuntimeError,'有效备份'):apply_native_rebase(store,game)
                self.assertEqual(target.read_bytes(),wrong)


if __name__ == '__main__':
    unittest.main()
