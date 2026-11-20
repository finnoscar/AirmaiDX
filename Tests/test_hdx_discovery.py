"""USB discovery regressions. Never open a serial port or execute a game."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import copy
import plistlib
import stat
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Service'))
from hdx_aux_probe import resolve
from runtime import detect_hdx


def hdx_tree():
    interfaces = []
    for label, control, data, suffix in [('HDX Touch channel', 4, 5, 'touch'),
                                          ('HDX LED channel', 6, 7, 'led'),
                                          ('HDX card reader channel', 8, 9, 'reader')]:
        interfaces.extend([
            dict(IORegistryEntryName=label, bInterfaceClass=2, bInterfaceNumber=control),
            dict(bInterfaceClass=10, bInterfaceNumber=data,
                 IORegistryEntryChildren=[dict(IOCalloutDevice='/dev/cu.usbmodem-' + suffix)])])
    return [dict(idVendor=0x0ca3, idProduct=0x0021, IORegistryEntryChildren=interfaces)]


class HDXDiscoveryTests(unittest.TestCase):
    def testEmptySuccessfulIoregOutputUsesKeyboard(self):
        # Real ioreg returns b'' with status 0 when there are no matching nodes.
        for output in [b'', b'\n  ', plistlib.dumps([])]:
            with self.subTest(output=output), patch('hdx_touch_probe.subprocess.check_output', return_value=output), \
                    patch('hdx_touch_probe.os.open') as open_port:
                physical, report = detect_hdx(True)
                self.assertEqual(physical, [])
                self.assertEqual(report['mode'], 'keyboard')
                self.assertEqual(report['status'], 'unavailable')
                self.assertIn('未检测到', report['message'])
                open_port.assert_not_called()

    def testInvalidOrTruncatedPlistDoesNotEscapeIntoLaunch(self):
        for output in [b'not a plist', b'<?xml version="1.0"?><plist><array>', b'bplist00truncated']:
            with self.subTest(output=output), patch('hdx_touch_probe.subprocess.check_output', return_value=output):
                physical, report = detect_hdx(True)
                self.assertEqual((physical, report['mode']), ([], 'keyboard'))
                self.assertIn('格式无效', report['message'])
                # Standalone LED and reader probes share the same parser.
                for role in ['led', 'reader']:
                    with self.assertRaisesRegex(RuntimeError, '格式无效'):
                        resolve(role)

    def testUnexpectedRegistryShapesUseKeyboard(self):
        for tree in [{}, ['wrong node'], [dict(IORegistryEntryChildren={})]]:
            with self.subTest(tree=tree), patch('hdx_touch_probe.subprocess.check_output', return_value=plistlib.dumps(tree)):
                physical, report = detect_hdx(True)
                self.assertEqual((physical, report['mode']), ([], 'keyboard'))
                self.assertIn('结构无效', report['message'])

    def testIoregFailureAndTimeoutAreBoundedAndUseKeyboard(self):
        for error in [subprocess.TimeoutExpired('ioreg', 5),
                      subprocess.CalledProcessError(1, 'ioreg', stderr=b'private diagnostic'),
                      FileNotFoundError('ioreg')]:
            with self.subTest(error=type(error).__name__), \
                    patch('hdx_touch_probe.subprocess.check_output', side_effect=error) as query:
                physical, report = detect_hdx(True)
                self.assertEqual((physical, report['mode']), ([], 'keyboard'))
                self.assertNotIn('private diagnostic', str(report))
                self.assertEqual(query.call_args.kwargs['timeout'], 5)

    def testDisabledHardwareDoesNotQueryUSB(self):
        with patch('hdx_touch_probe.subprocess.check_output') as query:
            physical, report = detect_hdx(False)
        query.assert_not_called()
        self.assertEqual((physical, report['mode'], report['status']), ([], 'keyboard', 'disabled'))

    def testVerifiedHDXResolvesAllRolesFromOneSnapshotWithoutOpeningPorts(self):
        for fmt in [plistlib.FMT_XML, plistlib.FMT_BINARY]:
            with self.subTest(format=fmt), \
                    patch('hdx_touch_probe.subprocess.check_output', return_value=plistlib.dumps(hdx_tree(), fmt=fmt)) as query, \
                    patch('hdx_touch_probe.os.stat', return_value=SimpleNamespace(st_mode=stat.S_IFCHR)), \
                    patch('hdx_touch_probe.os.open') as open_port:
                physical, report = detect_hdx(True)
                self.assertEqual(physical, ['/dev/cu.usbmodem-touch', '/dev/cu.usbmodem-led', '/dev/cu.usbmodem-reader'])
                self.assertEqual((report['mode'], report['status']), ('hdx', 'connected'))
                query.assert_called_once()
                open_port.assert_not_called()

    def testWrongOrAmbiguousDevicesAreNeverUsed(self):
        wrong_vendor = hdx_tree(); wrong_vendor[0]['idVendor'] = 0xffff
        missing_reader = hdx_tree(); missing_reader[0]['IORegistryEntryChildren'] = missing_reader[0]['IORegistryEntryChildren'][:4]
        wrong_role = hdx_tree(); wrong_role[0]['IORegistryEntryChildren'][0]['IORegistryEntryName'] = 'HDX debug channel'
        for tree in [wrong_vendor, hdx_tree() + copy.deepcopy(hdx_tree()), missing_reader, wrong_role]:
            with self.subTest(tree=tree), \
                    patch('hdx_touch_probe.subprocess.check_output', return_value=plistlib.dumps(tree)), \
                    patch('hdx_touch_probe.os.stat', return_value=SimpleNamespace(st_mode=stat.S_IFCHR)), \
                    patch('hdx_touch_probe.os.open') as open_port:
                physical, report = detect_hdx(True)
                self.assertEqual((physical, report['mode']), ([], 'keyboard'))
                open_port.assert_not_called()

    def testDisappearingAndNonCharacterPortsUseKeyboard(self):
        for properties in [dict(side_effect=FileNotFoundError('device detached')),
                           dict(return_value=SimpleNamespace(st_mode=stat.S_IFREG))]:
            with self.subTest(properties=properties), \
                    patch('hdx_touch_probe.subprocess.check_output', return_value=plistlib.dumps(hdx_tree())), \
                    patch('hdx_touch_probe.os.stat', **properties):
                physical, report = detect_hdx(True)
                self.assertEqual((physical, report['mode']), ([], 'keyboard'))


if __name__ == '__main__':
    unittest.main()
