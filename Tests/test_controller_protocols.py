"""Synthetic protocol tests do not constitute physical controller acceptance."""
from pathlib import Path
import base64
import copy
import json
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'Service'))
from controller_protocols import report_layout, normalize, decode, select_endpoints, InputState
from controller_bridge import Inputs, packet, PACKET
from controller_devices import inventory, public_inventory
from storage import Store, DEFAULT_SETTINGS


def descriptor(count, report_id=0, feature_count=0):
    # Vendor usage collection. Field padding contributes to the report size too.
    data = b'\x06\x00\xff\x09\x01\xa1\x01' + (bytes([0x85, report_id]) if report_id else b'')
    data += bytes([0x75, 8, 0x95, count, 0x81, 2])
    if feature_count:
        data += bytes([0x85, 1, 0x95, feature_count, 0xb1, 2])
    return data + b'\xc0'


def row(vid=0x2e3c, pid=0x5751, count=8, report_id=0, identity='100'):
    return dict(id=identity, vendor=vid, product=pid, name='Test controller', usagePage=0xff00, usage=1,
                descriptor=base64.b64encode(descriptor(count, report_id)).decode())


def device(**kw):
    return select_endpoints([row(**kw)])[0]


class ControllerProtocolTests(unittest.TestCase):
    def testAllKnownIdentitiesAreClassifiedWithoutOpeningHardware(self):
        for vid, pid, count, expected, player in [
            (0x2e3c,0x5750,13,'adx-hid',0),(0x2e4c,0x5750,13,'adx-hid',1),
            (0x2e3c,0x5767,13,'adx-keyboard',0),(0x2e3c,0x5768,13,'adx-keyboard',1),
            (0x2e3c,0x5751,8,'npro-hid',0),(0x2e3c,0x5752,8,'npro-hid',1),
            (0x0e8f,0x1224,7,'maimoller-hid',None)]:
            with self.subTest(pid=pid):
                d=device(vid=vid,pid=pid,count=count)
                self.assertEqual((d['profile'],d['player']),(expected,player))
                self.assertEqual(d['status'],'keyboard' if expected=='adx-keyboard' else 'candidate')
        self.assertEqual(select_endpoints([row(vid=1)]),[])

    def testDescriptorIDsPaddingPushPopAndMalformedData(self):
        layout=report_layout(b'\x75\x01\x95\x03\x81\x02\xa4\x75\x08\x95\x02\x81\x01\xb4\x81\x03')
        self.assertEqual(layout[('input',0)],3)  #3+16+3 bits, constants count.
        for raw in [b'',b'\x75',b'\xb4',b'\xa4',b'\x85\x00',b'\x75\x08\x95\xff\x81\x02'*8,
                    b'\xfe\x04\x01\x00',descriptor(8)+b'\x85\x01\x81\x02']:
            with self.subTest(raw=raw),self.assertRaises(ValueError): report_layout(raw)

    def testReportIDIsNormalizedUsingDescriptorNotLeadingTouchByte(self):
        raw=b'\x00\x01\x02\x03\x00\x00\xff\x0f'
        for report_id in [0,1,7]:
            layout=report_layout(descriptor(8,report_id))
            self.assertEqual(normalize(layout,'input',report_id,raw),raw)
            self.assertEqual(normalize(layout,'input',report_id,bytes([report_id])+raw),raw)
            with self.assertRaises(ValueError): normalize(layout,'input',report_id,raw[:-1])
            with self.assertRaises(ValueError): normalize(layout,'input',99,raw)
        self.assertEqual(decode('npro-hid',raw).touch,0x03020100)

    def testADXEveryOuterButtonAuxiliaryAndRelease(self):
        order=[5,4,3,2,9,8,7,6]
        for index,source in enumerate(order):
            canonical=bytearray(14);canonical[source]=1
            self.assertEqual(decode('adx-hid',canonical[1:]).buttons,1<<index)
        for source,target in [(10,0),(11,2),(12,1),(13,3)]:
            canonical=bytearray(14);canonical[source]=1
            self.assertEqual(decode('adx-hid',canonical[1:]).auxiliary,1<<target)
        self.assertEqual(decode('adx-hid',bytes(13)),InputState())
        with self.assertRaises(ValueError): decode('adx-hid',bytes(12))

    def testNProMultiTouchOuterAuxAndTouchMask(self):
        state=decode('npro-hid',b'\xff'*8)
        self.assertEqual(state,InputState((1<<34)-1,255,15))
        self.assertEqual(decode('npro-hid',bytes(8)),InputState())
        with self.assertRaises(ValueError):decode('npro-hid',bytes(9))

    def testMaimollerRegionBoundariesCoinAndPlayerSelect(self):
        for index,bit in [(0,7),(1,15),(2,17),(3,25),(4,33)]:
            raw=bytearray(7);raw[index]=2 if index==2 else 128
            self.assertEqual(decode('maimoller-hid',raw).touch,1<<bit)
        self.assertEqual(decode('maimoller-hid',bytes([0,0,255,0,0,255,15]),player=1),InputState(3<<16,255,30))

    def testKeyboardCollectionsUnknownFirmwareAndDuplicatePlayersAreNotClaimed(self):
        keyboard=row();keyboard.update(usagePage=1,usage=6)
        self.assertEqual(select_endpoints([keyboard])[0]['status'],'keyboard')
        self.assertEqual(device(count=9)['status'],'unsupported')
        first=row();second=row(identity='101')
        self.assertEqual([d['status'] for d in select_endpoints([first,second])],['ambiguous']*2)
        second=row(pid=0x5752,identity='101')
        self.assertEqual([d['status'] for d in select_endpoints([first,second])],['candidate']*2)

    def testInputStateSurvivesIdleReportsButReleasesOnRemovalAndMissingHeartbeat(self):
        d=device();inputs=Inputs([d]);inputs.accept(dict(event='opened',id='100'),1)
        inputs.accept(dict(event='report',id='100',reportID=0,hex='0100000000000100'),1)
        inputs.accept(dict(event='heartbeat',ids=['100']),1.1)
        self.assertEqual(inputs.snapshot(1.2)[0][0],InputState(1,1,0))
        # Held state does not need another HID report, only a live helper.
        inputs.accept(dict(event='heartbeat',ids=['100']),100)
        self.assertEqual(inputs.snapshot(100.1)[0][0],InputState(1,1,0))
        self.assertEqual(inputs.snapshot(100.5),({},set()))
        inputs.accept(dict(event='removed',id='100'),100.6)
        inputs.accept(dict(event='heartbeat',ids=[]),100.6)
        self.assertEqual(inputs.snapshot(100.7),({},set()))

    def testShortPressBetweenGamePacketsIsLatchedOnceThenReleased(self):
        inputs=Inputs([device()]);inputs.accept(dict(event='opened',id='100'),1)
        inputs.accept(dict(event='heartbeat',ids=['100']),1)
        for value in ['0100000000000100','0000000000000000']:
            inputs.accept(dict(event='report',id='100',reportID=0,hex=value),1.01)
        self.assertEqual(inputs.snapshot(1.02)[0][0],InputState(1,1,0))
        self.assertEqual(inputs.snapshot(1.03)[0][0],InputState())

    def testNewGameConnectionDropsPressesDuringLoadingAndKeepsCurrentlyHeldInputs(self):
        inputs=Inputs([device()]);inputs.accept(dict(event='opened',id='100'),1)
        inputs.accept(dict(event='heartbeat',ids=['100']),1)
        for value in ['0100000000000100','0000000000000000']:
            inputs.accept(dict(event='report',id='100',reportID=0,hex=value),1.01)
        inputs.transport_reset()
        self.assertEqual(inputs.snapshot(1.02)[0][0],InputState())
        inputs.accept(dict(event='report',id='100',reportID=0,hex='0100000000000100'),1.03)
        inputs.transport_reset()
        self.assertEqual(inputs.snapshot(1.04)[0][0],InputState(1,1,0))

    def testMaimollerFeaturePlayerAndDuplicateRuntimeSlots(self):
        d=device(vid=0x0e8f,pid=0x1224,count=7,report_id=1)
        d['descriptor']=base64.b64encode(descriptor(7,1,32)).decode()
        inputs=Inputs([d,device(pid=0x5752,identity='101')])
        for identity in ['100','101']:inputs.accept(dict(event='opened',id=identity),1)
        inputs.accept(dict(event='heartbeat',ids=['100','101']),1)
        # Feature1 canonical byte4=2 => player2; data includes ReportID.
        data=bytearray(33);data[0]=1;data[4]=2
        inputs.accept(dict(event='feature',id='100',reportID=1,hex=data.hex()),1.01)
        self.assertEqual(inputs.devices['100']['player'],1)
        inputs.accept(dict(event='report',id='100',reportID=1,hex='0100000000000000'),1.02)
        inputs.accept(dict(event='report',id='101',reportID=0,hex='0000000000000000'),1.02)
        self.assertEqual(inputs.snapshot(1.03),({},set()))

    def testInvalidReportClearsPreviousStateAndPacketHasTwoPlayerIsolation(self):
        inputs=Inputs([device()]);inputs.accept(dict(event='opened',id='100'),1)
        inputs.accept(dict(event='heartbeat',ids=['100']),1)
        inputs.accept(dict(event='report',id='100',reportID=0,hex='0100000000000100'),1)
        inputs.accept(dict(event='report',id='100',reportID=0,hex='01'),1.1)
        self.assertEqual(inputs.snapshot(1.2),({},set()))
        self.assertEqual(inputs.invalid,1)
        raw=packet(3,{1:InputState(1<<33,128,8)},{1},now_ns=100)
        self.assertEqual(len(raw),56)
        self.assertEqual(PACKET.unpack(raw),(b'AMCI',1,10,3,100,0,1<<33,0,128,0,8,56,0))
        released=PACKET.unpack(packet(4,{},set(),now_ns=101))
        self.assertEqual(released[2],0);self.assertEqual(released[5:11],(0,0,0,0,0,0))

    def testInventoryFailureAndWinUSBOnlyDeviceDoNotOpenAnyPortsOrAbort(self):
        usb=[dict(idVendor=0x2e3c,idProduct=0x5751,IORegistryEntryID=2)]
        with patch('controller_devices.subprocess.run',side_effect=FileNotFoundError()),patch('controller_devices.usb_device_tree',return_value=usb):
            result=inventory(Path('/missing'))
        self.assertEqual(result['devices'][0]['status'],'unsupported')
        self.assertIn('WinUSB',result['devices'][0]['detail'])
        self.assertTrue(result['errors'])
        with patch('controller_devices.subprocess.run') as run,patch('controller_devices.usb_device_tree',return_value=[]):
            run.return_value.stdout=json.dumps([row()]).encode();result=inventory(Path('/runtime'))
        public=public_inventory(result)
        self.assertNotIn('descriptor',public['devices'][0])
        self.assertEqual(run.call_args.kwargs['timeout'],5)

    def testSettingsUpgradePreservesExplicitDisabledState(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            for old,expected in [({'hdxEnabled':False},True),({'adxEnabled':False},False)]:
                store.db.write_text(json.dumps([dict(settings=old)]))
                settings=store.library()[0]['settings']
                self.assertEqual(settings['adxEnabled'],expected)
                self.assertEqual(set(settings),set(DEFAULT_SETTINGS))
