from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Tools'))
from validate_portability import command_issues

class PortabilityTests(unittest.TestCase):
    def testHelperWithNewerDeploymentTargetBlocksPackaging(self):
        text='Load command 1\n cmd LC_BUILD_VERSION\n minos 27.0\n sdk 27.1\n'
        self.assertTrue(command_issues(text,'15.0'))

    def testSystemLibrariesAndIdentityDoNotCountAsExternalDependencies(self):
        text='Load command 1\n cmd LC_ID_DYLIB\n name /build/private/self.dylib (offset 24)\n'
        text+='Load command 2\n cmd LC_LOAD_DYLIB\n name /usr/lib/libSystem.B.dylib (offset 24)\n'
        text+='Load command 3\n cmd LC_BUILD_VERSION\n minos 15.0\n sdk 27.1\n'
        self.assertEqual(command_issues(text,'15.0'),[])

    def testAbsoluteLoadAndRpathAreRejected(self):
        for command,field in [('LC_LOAD_DYLIB','name'),('LC_RPATH','path')]:
            with self.subTest(command=command):
                text=f'Load command 1\n cmd {command}\n {field} /Users/developer/private/lib.dylib (offset 24)\n'
                self.assertTrue(command_issues(text,'15.0'))
