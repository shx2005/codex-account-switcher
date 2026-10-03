import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("accounts", Path(__file__).parents[1] / "scripts/codex_account.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def auth(user, refresh="fake-refresh"):
    claims = base64.urlsafe_b64encode(json.dumps({"sub": user}).encode()).decode().rstrip("=")
    return {"auth_mode": "chatgpt", "tokens": {"id_token": "fake." + claims + ".fake",
            "access_token": "fake-access", "refresh_token": refresh, "account_id": "workspace"}}


class AccountsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.a = m.Accounts(Path(self.tmp.name))
        self.lock = self.a.locked()
        self.lock.__enter__()
        self.addCleanup(self.lock.__exit__, None, None, None)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def test_round_trip_preserves_refreshed_token(self):
        self.a.save("main", auth("a"))
        self.a.save("second", auth("b"))
        m.write_json(self.a.auth, auth("a", "rotated"))
        self.a.switch("second")
        self.assertEqual(m.read_json(self.a.auth), auth("b"))
        self.a.switch("main")
        self.assertEqual(m.read_json(self.a.auth), auth("a", "rotated"))

    def test_same_account_does_not_restore_stale_token(self):
        self.a.save("main", auth("a"))
        m.write_json(self.a.auth, auth("a", "new"))
        self.a.switch("main")
        self.assertEqual(m.read_json(self.a.auth), auth("a", "new"))
        self.assertEqual(m.read_json(self.a.path("main")), auth("a", "new"))

    def test_newer_relogin_can_replace_active_same_account(self):
        old = dict(auth("a", "old"), last_refresh="2026-09-25T00:00:00Z")
        new = dict(auth("a", "new"), last_refresh="2026-09-26T00:00:00Z")
        m.write_json(self.a.auth, old)
        self.a.save("main", new)
        self.a.switch("main")
        self.assertEqual(m.read_json(self.a.auth), new)

    def test_switch_away_preserves_newer_relogin(self):
        old = dict(auth("a", "old"), last_refresh="2026-09-25T00:00:00Z")
        new = dict(auth("a", "new"), last_refresh="2026-09-26T00:00:00Z")
        m.write_json(self.a.auth, old)
        self.a.save("main", new)
        self.a.save("second", auth("b"))
        self.a.switch("second")
        self.assertEqual(m.read_json(self.a.path("main")), new)

    def test_unknown_live_account_is_saved(self):
        self.a.save("second", auth("b"))
        m.write_json(self.a.auth, auth("a"))
        self.a.switch("second")
        backups = list(self.a.profiles.glob("backup-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(m.read_json(backups[0]), auth("a"))

    def test_invalid_target_keeps_current(self):
        m.write_json(self.a.auth, auth("a"))
        m.write_json(self.a.path("bad"), {"tokens": {}})
        with self.assertRaises(m.Error):
            self.a.switch("bad")
        self.assertEqual(m.read_json(self.a.auth), auth("a"))

    def test_same_workspace_different_users_are_distinct(self):
        self.assertNotEqual(m.identity(auth("a")), m.identity(auth("b")))

    def test_duplicate_identity_rejected(self):
        self.a.save("main", auth("a"))
        with self.assertRaises(m.Error):
            self.a.save("duplicate", auth("a"))

    def test_name_collision_requires_replace(self):
        self.a.save("main", auth("a"))
        with self.assertRaises(m.Error):
            self.a.save("main", auth("b"))
        self.a.save("main", auth("b"), replace=True)

    def test_path_traversal_rejected(self):
        for name in ("../auth", "/tmp/evil", "x/y", "", "a" * 49):
            with self.assertRaises(m.Error):
                self.a.path(name)

    def test_symlink_rejected(self):
        victim = self.a.home / "victim"
        m.write_json(victim, auth("a"))
        self.a.auth.symlink_to(victim)
        with self.assertRaises(m.Error):
            m.read_json(self.a.auth)
        with self.assertRaises(m.Error):
            m.write_json(self.a.auth, auth("b"))
        self.assertEqual(m.read_json(victim), auth("a"))

    def test_permissions(self):
        self.a.save("main", auth("a"))
        self.assertEqual(stat.S_IMODE(self.a.path("main").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.a.profiles.stat().st_mode), 0o700)

    def test_keyring_rejected(self):
        (self.a.home / "config.toml").write_text('cli_auth_credentials_store="keyring"\n')
        with self.assertRaises(m.Error):
            self.a.check_store()

    def test_concurrent_operation_rejected(self):
        with self.assertRaises(m.Error):
            with m.Accounts(self.a.home).locked():
                pass

    def test_api_key_switch(self):
        self.a.save("api", {"auth_mode":"apikey", "OPENAI_API_KEY":"fake-test-key"})
        self.a.switch("api")
        self.assertEqual(m.read_json(self.a.auth)["OPENAI_API_KEY"], "fake-test-key")

    def test_atomic_write_failure_keeps_current(self):
        self.a.save("second", auth("b"))
        m.write_json(self.a.auth, auth("a"))
        original = os.replace
        def fail_final(source, target):
            if target == self.a.auth:
                raise OSError("simulated disk failure")
            original(source, target)
        with patch.object(m.os, "replace", side_effect=fail_final):
            with self.assertRaises(OSError):
                self.a.switch("second")
        self.assertEqual(m.read_json(self.a.auth), auth("a"))

    def test_login_failure_preserves_live_and_cleans_up(self):
        m.write_json(self.a.auth, auth("a"))
        with patch.object(m.native_codex, "login", return_value=1):
            with self.assertRaises(m.Error):
                self.a.login("second")
        self.assertEqual(m.read_json(self.a.auth), auth("a"))
        self.assertEqual(list(self.a.root.glob("login-*")), [])

    def test_login_success_is_isolated(self):
        m.write_json(self.a.auth, auth("a"))
        def fake_login(home, arguments):
            self.assertNotEqual(str(home), str(self.a.home))
            m.write_json(Path(home) / "auth.json", auth("b"))
            return 0
        with patch.object(m.native_codex, "login", side_effect=fake_login):
            self.a.login("second")
        self.assertEqual(m.read_json(self.a.auth), auth("a"))
        self.assertEqual(m.read_json(self.a.path("second")), auth("b"))

    def test_remove_active_snapshot_preserves_login(self):
        self.a.save("main", auth("a"))
        m.write_json(self.a.auth, auth("a"))
        self.a.remove("main")
        self.assertFalse(self.a.path("main").exists())
        self.assertEqual(m.read_json(self.a.auth), auth("a"))

    def test_remove_missing_and_traversal(self):
        for name in ("missing", "../auth"):
            with self.assertRaises(m.Error):
                self.a.remove(name)

    def test_native_login_argument_forwarding(self):
        def native(home, args):
            self.assertEqual(args, ["--future-option", "value", "--device-auth"])
            m.write_json(Path(home) / "auth.json", auth("b"))
            return 0
        with patch.object(m.native_codex, "login", side_effect=native):
            self.a.login("second", device=True, native_args=["--future-option", "value"])

    def test_native_help_does_not_save(self):
        with patch.object(m.native_codex, "login", return_value=0):
            self.a.login("new", native_args=["--help"])
        self.assertFalse(self.a.path("new").exists())

    def test_usage_active_uses_live_home(self):
        m.write_json(self.a.auth, auth("a", "fresh"))
        with patch.object(m.native_codex, "rate_limits", return_value={"rateLimits":{}}) as mock:
            result = self.a.record("main", auth("a"), True)
        mock.assert_called_once_with(self.a.home, 25)
        self.assertTrue(result["active"])

    def test_usage_inactive_keeps_current_and_saves_official_refresh(self):
        m.write_json(self.a.auth, auth("a"))
        self.a.save("second", auth("b"))
        def query(home, timeout):
            self.assertNotEqual(str(home), str(self.a.home))
            m.write_json(Path(home) / "auth.json", auth("b", "official-refresh"))
            return {"rateLimits": {"primary": {"usedPercent": 20}}}
        with patch.object(m.native_codex, "rate_limits", side_effect=query):
            result = self.a.record("second", auth("b"), True)
        self.assertEqual(m.read_json(self.a.auth), auth("a"))
        self.assertEqual(m.read_json(self.a.path("second")), auth("b", "official-refresh"))
        self.assertEqual(result["usage"]["buckets"][0]["windows"][0]["remaining_percent"], 80)
        self.assertEqual(list(self.a.root.glob("usage-*")), [])

    def test_quota_failure_is_not_zero(self):
        with patch.object(m.native_codex, "rate_limits", side_effect=m.native_codex.NativeError("超时")):
            result = self.a.record("main", auth("a"), True)
        self.assertEqual(result["usage"], {"error":"超时"})

    def test_api_key_does_not_request_subscription_quota(self):
        with patch.object(m.native_codex, "rate_limits") as mock:
            result = self.a.record("api", {"auth_mode":"apikey", "OPENAI_API_KEY":"fake"}, True)
        mock.assert_not_called()
        self.assertIn("API key", result["usage"]["error"])

    def test_normalize_multibucket_unknown_zero_and_clamping(self):
        result = m.normalize_usage({"rateLimits":{"primary":{"usedPercent":90}},
            "rateLimitsByLimitId":{"codex":{"primary":{"usedPercent":0}},
                                    "other":{"primary":{"usedPercent":120},"secondary":None}}})
        self.assertEqual(result["buckets"][0]["windows"][0]["remaining_percent"],100)
        self.assertEqual(result["buckets"][1]["windows"][0]["remaining_percent"],0)
        self.assertIsNone(result["buckets"][1]["windows"][1]["remaining_percent"])

    def test_unknown_invalid_percentage(self):
        for value in (None, "10", True, float("nan"), float("inf")):
            result=m.normalize_usage({"rateLimits":{"primary":{"usedPercent":value}}})
            self.assertIsNone(result["buckets"][0]["windows"][0]["remaining_percent"])

    def test_normalized_output_excludes_credentials(self):
        raw={"rateLimits":{"primary":{"usedPercent":10,"access_token":"secret"},"refresh_token":"secret"},"access_token":"secret"}
        self.assertNotIn("secret", json.dumps(m.normalize_usage(raw)))


if __name__ == "__main__":
    unittest.main()
