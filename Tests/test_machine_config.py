from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Service'))
from machine_config import validate_keychip


class MachineConfigTests(unittest.TestCase):
    def testAcceptsWireCapacityWithoutInventingAServiceSpecificLength(self):
        for value in ['A6XE01C1234', 'A6XE-01C1234', 'A000-01234567890', 'A00001234567890', 'abc123']:
            self.assertEqual(validate_keychip(value), value)
        self.assertEqual(validate_keychip(' A6XE01C1234 '), 'A6XE01C1234')

    def testRejectsTruncationControlCharactersUnicodeAndPlaceholders(self):
        for value in ['', ' ', 'none', 'NULL', 'unset', '0000000', '0-0', '-123', 'A' * 17,
                      'A6XE 01C1234', 'A6XE\n01C1234', 'A6XE\x0001C1234', 'Ａ6XE01C1234']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_keychip(value)
