"""CDC discovery, frame boundaries and real TTY lifecycle; not game acceptance."""
from pathlib import Path
import copy
import os
import pty
import select
import sys
import termios
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'Service'))
from adx_serial_touch import endpoints, Frames, Ports
from controller_bridge import combined_snapshot, Inputs
from controller_protocols import InputState
from controller_devices import public_inventory


def usb(identity=10, pid=0x5767):
    return dict(IOObjectClass='IOUSBHostDevice', IORegistryEntryID=identity,
        idVendor=0x2e3c, idProduct=pid, IORegistryEntryChildren=[
            dict(bInterfaceNumber=0, bInterfaceClass=2, bInterfaceSubClass=2),
            dict(bInterfaceNumber=1, bInterfaceClass=10, IORegistryEntryChildren=[
                dict(IOCalloutDevice='/dev/cu.usbmodemTest')]),
            dict(bInterfaceNumber=2, bInterfaceClass=3)])


def frame(bits):
    return b'('+bytes((bits >> (5*i)) & 31 for i in range(7))+b')'


class AdxSerialTouchTests(unittest.TestCase):
    def assertTTYRestored(self, slave, original):
        actual = termios.tcgetattr(slave)
        # Darwin PTYs force EXTPROC after raw mode, independently of the
        # saved tcsetattr flags. All configurable flags/speeds/cc must match.
        if sys.platform == 'darwin':
            actual[3] &= ~0x20000000
            original = copy.deepcopy(original); original[3] &= ~0x20000000
        self.assertEqual(actual, original)

    def testOnlyKnownCDCDeviceAndInterfacePairIsSelected(self):
        d = usb()
        # ioreg's recursive roots may repeat the same USB device.
        self.assertEqual(len(endpoints([d, copy.deepcopy(d)])), 1)
        self.assertEqual(endpoints([usb(pid=0x5768)])[0]['player'], 1)
        for mutate in [lambda n: n.update(idVendor=0x1a86, idProduct=0x7523),
                       lambda n: n.update(idProduct=0x5751),
                       lambda n: n['IORegistryEntryChildren'][1].update(bInterfaceNumber=5),
                       lambda n: n['IORegistryEntryChildren'].pop(0),
                       lambda n: n['IORegistryEntryChildren'][1]['IORegistryEntryChildren'].append(dict(IOCalloutDevice='/dev/cu.other'))]:
            changed = copy.deepcopy(d); mutate(changed)
            self.assertEqual(endpoints([changed]), [])
        public = public_inventory(dict(devices=endpoints([d]), errors=[]))
        self.assertNotIn('port', public['devices'][0])

    def testAll34RegionsFragmentationConcatenationAndMalformedFrames(self):
        parser = Frames()
        expected = [1 << i for i in range(34)] + [0, (1 << 34)-1]
        stream = b''.join(map(frame, expected))
        actual = []
        for byte in stream: actual.extend(parser.feed(bytes([byte])))
        self.assertEqual(actual, expected)
        self.assertEqual(parser.feed(b'noise'+b'(\xff'*20+frame(1<<33)+frame(0)), [1<<33, 0])
        self.assertGreater(parser.invalid, 0)
        self.assertEqual(parser.feed(frame(1<<34)), [])  # unused wire bit
        self.assertEqual(parser.feed(frame(1)), [1])
        self.assertLess(len(parser.pending), 9)

    def testTTYStartReadLatchTimeoutReleaseDisconnectAndRestore(self):
        master, slave = pty.openpty()
        original = termios.tcgetattr(slave)
        d = endpoints([usb()])[0]
        real_open = os.open
        try:
            with patch('adx_serial_touch.endpoints', return_value=[d]), patch('adx_serial_touch.os.open', side_effect=lambda *_: real_open(os.ttyname(slave), os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)):
                with Ports([d]) as ports:
                    self.assertEqual(os.read(master, 6), b'{STAT}')
                    self.assertEqual(ports.snapshot(1), ({}, set()))
                    fd = next(iter(ports.active))
                    os.write(master, frame(1<<33)+frame(0))
                    self.assertTrue(select.select([fd], [], [], 1)[0])
                    ports.read(fd, 1)
                    self.assertEqual(ports.snapshot(1.01), ({0:InputState(1<<33)}, {0}))
                    self.assertEqual(ports.snapshot(1.02), ({0:InputState()}, {0}))
                    self.assertEqual(ports.snapshot(1.21), ({}, set()))
                    os.write(master, frame(3)+frame(0)); select.select([fd], [], [], 1); ports.read(fd, 2)
                    ports.transport_reset()
                    self.assertEqual(ports.snapshot(2.01), ({0:InputState()}, {0}))
                    # A removed TTY must release input, even before the timer.
                    with patch('adx_serial_touch.os.read', side_effect=OSError('removed')): ports.read(fd, 2.02)
                    self.assertEqual(ports.snapshot(2.02), ({}, set()))
                    self.assertEqual(ports.active, {})
                self.assertTTYRestored(slave, original)
        finally: os.close(master); os.close(slave)

    def testReidentifiedDeviceCannotBeReplacedByStaleSelectedPort(self):
        d = endpoints([usb()])[0]
        with patch('adx_serial_touch.endpoints', return_value=[]), patch('adx_serial_touch.os.open') as opened:
            with self.assertRaises(RuntimeError):
                with Ports([d]): pass
            opened.assert_not_called()

    def testTTYOpenFailureClosesEarlierDeviceAndRestoresSettings(self):
        master, slave = pty.openpty()
        a = endpoints([usb()])[0]; b = endpoints([usb(11, 0x5768)])[0]
        fd = os.open(os.ttyname(slave), os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
        original = termios.tcgetattr(slave)
        try:
            with patch('adx_serial_touch.endpoints', return_value=[a,b]), patch('adx_serial_touch.os.open', side_effect=[fd, OSError('unplug')]):
                with self.assertRaises(OSError):
                    with Ports([a,b]): pass
            with self.assertRaises(OSError): os.fstat(fd)
            self.assertTTYRestored(slave, original)
        finally: os.close(master); os.close(slave)

    def testMixedSourcesKeepPlayersSeparateAndRejectConflicts(self):
        class Source:
            def __init__(self, player): self.player=player
            def snapshot(self, now, consume): return {self.player:InputState(8)}, {self.player}
        self.assertEqual(combined_snapshot(Inputs([]), Source(1), 1), ({1:InputState(8)}, {1}))
        self.assertEqual(combined_snapshot(Source(0), Source(1), 1), ({0:InputState(8),1:InputState(8)}, {0,1}))
        self.assertEqual(combined_snapshot(Source(0), Source(0), 1), ({},set()))


if __name__ == '__main__': unittest.main()
