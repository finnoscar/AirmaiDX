from pathlib import Path
import copy,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Service'))
from display_geometry import output_size,match_monitor

class DisplayGeometryTests(unittest.TestCase):
    def fixture(self,scale=2):
        screens=[dict(main=True,CG_frame=dict(x=0,y=0,width=1357,height=935)),
                 dict(main=False,CG_frame=dict(x=1357,y=-235,width=1080,height=1920),current_mode=dict(pixel_width=2160,pixel_height=3840))]
        monitors=[]
        for i,d in enumerate(screens):
            b=d['CG_frame'];monitors.append(dict(index=i,primary=d['main'],bounds=dict(left=b['x']*scale,top=b['y']*scale,right=(b['x']+b['width'])*scale,bottom=(b['y']+b['height'])*scale)))
        return screens,monitors
    def testRetinaPhysicalOutputAndIndependentLowerScene(self):
        displays,_=self.fixture()
        for scene in [(720,1280),(1080,1920),(2160,3840)]:
            self.assertEqual(output_size(displays[1],dict(fillDisplay=True,width=scene[0],height=scene[1])),(2160,3840))
    def testWindowedSizeFitsAndConvertsPointsToPixels(self):
        displays,_=self.fixture()
        width,height=output_size(displays[1],dict(fillDisplay=False,width=2160,height=3840))
        self.assertLess(width,2160);self.assertLess(height,3840);self.assertAlmostEqual(width/height,9/16,places=3)
    def testGeometryUsesBothOneAndTwoTimesWineCoordinates(self):
        for scale in (1,2):
            displays,monitors=self.fixture(scale)
            self.assertEqual(match_monitor(displays,displays[1],list(reversed(monitors)))['index'],1)
    def testNegativeOriginsAndMixedBackingScales(self):
        displays,monitors=self.fixture()
        displays[1]['CG_frame']['x']=-1080
        monitors[1]['bounds'].update(left=-2160,right=0)
        displays[0]['current_mode']=dict(pixel_width=1357,pixel_height=935)
        self.assertEqual(match_monitor(displays,displays[1],monitors)['index'],1)
        self.assertEqual(output_size(displays[0],dict(fillDisplay=True)),(1357,935))
    def testUnknownAndMirroredAmbiguousGeometryDoesNotPickWrongMonitor(self):
        displays,monitors=self.fixture()
        self.assertIsNone(match_monitor(displays,displays[1],monitors[:1]))
        self.assertIsNone(match_monitor(displays,displays[1],monitors+[copy.deepcopy(monitors[1])]))
    def testLegacyInventoryFallsBackToItsUnscaledBounds(self):
        self.assertEqual(output_size(dict(CG_frame=dict(width=1920,height=1080)),dict(fillDisplay=True)),(1920,1080))
if __name__=='__main__':unittest.main()
