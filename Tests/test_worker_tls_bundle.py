"""Frozen TLS dependencies must follow the worker Python, including Xcode builds."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Tools'))
from worker_bundle import WORKER_OPTIONS, worker_options, worker_tls_ready


class WorkerTLSBundleTests(unittest.TestCase):
    def testSelectedInterpreterControlsPolicyEvenWhenBuildPythonHasNone(self):
        with tempfile.TemporaryDirectory(prefix='python with spaces ') as temp:
            policy = Path(temp) / 'codex-rejected-cas.pem'
            policy.write_text('test policy')
            result = subprocess.CompletedProcess([], 0, stdout=json.dumps(str(policy)))
            with patch('worker_bundle.subprocess.run', return_value=result) as run:
                options = worker_options('/selected/python')
            self.assertEqual(run.call_args.args[0][:2], ['/selected/python', '-I'])
            self.assertEqual(options[-2:], ['--add-data', str(policy) + ':.'])
            self.assertNotIn('--add-data', WORKER_OPTIONS)

    def testStandardPythonNeedsNoExtraPolicy(self):
        result = subprocess.CompletedProcess([], 0, stdout='null')
        with patch('worker_bundle.subprocess.run', return_value=result):
            self.assertEqual(worker_options('/selected/python'), WORKER_OPTIONS)

    def testMissingSelectedPolicyIsNotSilentlyIgnored(self):
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps('/missing/codex-rejected-cas.pem'))
        with patch('worker_bundle.subprocess.run', return_value=result):
            with self.assertRaisesRegex(RuntimeError, 'TLS'):
                worker_options('/selected/python')

    def testFrozenSmokeRequiresSuccessfulStructuredResult(self):
        for code, output, expected in [
            (0, '{"event":"result","data":{"tlsReady":true}}', True),
            (1, '{"event":"result","data":{"tlsReady":true}}', False),
            (0, '{"event":"error","message":"tlsReady"}', False),
            (0, '', False),
        ]:
            with self.subTest(code=code, output=output):
                result = subprocess.CompletedProcess([], code, stdout=output)
                with patch('worker_bundle.subprocess.run', return_value=result):
                    self.assertEqual(worker_tls_ready('/frozen/worker'), expected)

if __name__ == '__main__':
    unittest.main()
