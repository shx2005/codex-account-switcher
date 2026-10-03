import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import native_codex as native


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def executable(self, body):
        script = self.home / "fake-codex"
        script.write_text("#!" + sys.executable + "\n" + body)
        script.chmod(0o700)
        return str(script)

    def test_official_login_inherits_terminal_and_forwards_args(self):
        with patch.object(native, "binary", return_value="/fake/codex"), \
             patch.object(native.subprocess, "run") as run:
            run.return_value.returncode=0
            native.login(self.home, ["--future-login", "value"])
        args, kwargs=run.call_args
        self.assertEqual(args[0], ["/fake/codex", "login", "--future-login", "value", "-c", 'cli_auth_credentials_store="file"'])
        self.assertNotIn("stdin", kwargs)
        self.assertNotIn("stdout", kwargs)
        self.assertNotIn("stderr", kwargs)
        self.assertNotIn("input", kwargs)

    def test_environment_does_not_override_saved_auth(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY":"secret", "CODEX_ACCESS_TOKEN":"secret"}):
            env=native.environment(self.home)
        self.assertNotIn("OPENAI_API_KEY",env)
        self.assertNotIn("CODEX_ACCESS_TOKEN",env)
        self.assertEqual(env["CODEX_HOME"],str(self.home))

    def test_rpc_handshake_and_notification_handling(self):
        script=self.executable('''import sys,json
for line in sys.stdin:
 m=json.loads(line)
 if m['method']=='initialize':
  print(json.dumps({'id':m['id'],'result':{}}),flush=True)
 elif m['method']=='account/rateLimits/read':
  print(json.dumps({'method':'account/updated','params':{}}),flush=True)
  print(json.dumps({'id':m['id'],'result':{'rateLimits':{'primary':{'usedPercent':25}}}}),flush=True)
''')
        with patch.object(native,"binary",return_value=script):
            result=native.rate_limits(self.home,5)
        self.assertEqual(result['rateLimits']['primary']['usedPercent'],25)

    def test_timeout_is_bounded(self):
        script=self.executable('import time\ntime.sleep(30)\n')
        start=time.monotonic()
        with patch.object(native,"binary",return_value=script):
            with self.assertRaisesRegex(native.NativeError,"超时"):
                native.rate_limits(self.home,0.1)
        self.assertLess(time.monotonic()-start,4)

    def test_error_text_cannot_leak_tokens(self):
        script=self.executable('''import sys,json
for line in sys.stdin:
 m=json.loads(line)
 print(json.dumps({'id':m.get('id'),'error':{'code':-1,'message':'secret-refresh-token'}}),flush=True)
''')
        with patch.object(native,"binary",return_value=script):
            with self.assertRaises(native.NativeError) as ctx:
                native.rate_limits(self.home,5)
        self.assertNotIn('secret',str(ctx.exception))

    def test_unsupported_native_version(self):
        script=self.executable('''import sys,json
for line in sys.stdin:
 m=json.loads(line)
 print(json.dumps({'id':m.get('id'),'error':{'code':-32601,'message':'no method'}}),flush=True)
''')
        with patch.object(native,"binary",return_value=script):
            with self.assertRaisesRegex(native.NativeError,"升级"):
                native.rate_limits(self.home,5)


if __name__ == '__main__':
    unittest.main()
