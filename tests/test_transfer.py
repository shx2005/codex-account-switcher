import contextlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from test_accounts import auth, m


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = m.Accounts(self.root / "source")
        self.target = m.Accounts(self.root / "target")
        for accounts in (self.source, self.target):
            lock = accounts.locked()
            lock.__enter__()
            self.addCleanup(lock.__exit__, None, None, None)
        self.file = self.root / "transfer.codex-accounts.json"
        self.stdout = io.StringIO()
        redirect = contextlib.redirect_stdout(self.stdout)
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)

    def bundle(self, records, **overrides):
        value = {"format": m.TRANSFER_FORMAT, "version": 1, "accounts": records}
        value.update(overrides)
        m.write_json(self.file, value)

    def record(self, name, user):
        return {"name": name, "auth": auth(user)}

    def test_all_profiles_round_trip_preserves_full_credentials_and_live_login(self):
        account = auth("a")
        account["future_metadata"] = {"keep": True}
        api = {"auth_mode": "apikey", "OPENAI_API_KEY": "fake-test-key"}
        self.source.save("main", account)
        self.source.save("api", api)
        m.write_json(self.source.auth, account)
        m.write_json(self.target.auth, auth("current"))
        before = self.target.auth.read_bytes()
        self.source.export_profiles(self.file, all_profiles=True)
        self.target.import_profiles(self.file)
        self.assertEqual(m.read_json(self.target.path("main")), account)
        self.assertEqual(m.read_json(self.target.path("api")), api)
        self.assertEqual(self.target.auth.read_bytes(), before)
        self.assertEqual(m.read_json(self.source.auth), account)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.target.path("main").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.target.profiles.stat().st_mode), 0o700)
        self.assertNotIn("fake-access", self.stdout.getvalue())
        self.assertNotIn("fake-refresh", self.stdout.getvalue())
        self.assertNotIn("fake-test-key", self.stdout.getvalue())

    def test_export_current_does_not_require_a_saved_profile(self):
        m.write_json(self.source.auth, auth("a"))
        self.source.export_profiles(self.file)
        records = m.read_json(self.file)["accounts"]
        self.assertEqual(records, [self.record("current", "a")])
        self.assertEqual(self.source.entries(), [])

    def test_export_named_profile_only(self):
        self.source.save("main", auth("a"))
        self.source.save("second", auth("b"))
        self.source.export_profiles(self.file, "second")
        self.assertEqual(m.read_json(self.file)["accounts"], [self.record("second", "b")])

    def test_all_exports_saved_profiles_only(self):
        self.source.save("main", auth("a"))
        m.write_json(self.source.auth, auth("unsaved"))
        self.source.export_profiles(self.file, all_profiles=True)
        self.assertEqual(m.read_json(self.file)["accounts"], [self.record("main", "a")])

    def test_export_uses_newest_active_credentials_in_all_modes(self):
        old = dict(auth("a", "old"), last_refresh="2026-10-19T00:00:00Z")
        new = dict(auth("a", "new"), last_refresh="2026-10-20T00:00:00Z")
        for saved, live in ((old, new), (new, old)):
            for options in ({}, {"name": "main"}, {"all_profiles": True}):
                with self.subTest(saved=saved["last_refresh"], options=options):
                    self.source.save("main", saved)
                    m.write_json(self.source.auth, live)
                    self.source.export_profiles(self.file, replace=True, **options)
                    self.assertEqual(m.read_json(self.file)["accounts"], [{"name": "main", "auth": new}])
                    self.assertEqual(m.read_json(self.source.auth), live)
                    self.assertEqual(m.read_json(self.source.path("main")), saved)

    def test_empty_or_missing_export_leaves_no_file(self):
        for options in ({}, {"name": "missing"}, {"all_profiles": True}):
            with self.subTest(options=options), self.assertRaises(m.Error):
                self.source.export_profiles(self.file, **options)
        self.assertFalse(self.file.exists())

    def test_existing_export_requires_explicit_replace(self):
        self.source.save("main", auth("a"))
        self.file.write_text("keep this file")
        with self.assertRaisesRegex(m.Error, "--replace"):
            self.source.export_profiles(self.file, "main")
        self.assertEqual(self.file.read_text(), "keep this file")
        self.file.chmod(0o644)
        self.source.export_profiles(self.file, "main", replace=True)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)

    def test_export_rejects_terminal_and_managed_directory(self):
        m.write_json(self.source.auth, auth("a"))
        original = self.source.auth.read_bytes()
        for output in (Path("-"), self.source.auth, self.source.profiles / "export.json"):
            with self.subTest(output=output), self.assertRaises(m.Error):
                self.source.export_profiles(output, replace=True)
        self.assertEqual(self.source.auth.read_bytes(), original)

    def test_transfer_rejects_symlinks(self):
        self.source.save("main", auth("a"))
        victim = self.root / "victim.json"
        m.write_json(victim, {"keep": True})
        self.file.symlink_to(victim)
        for replace in (False, True):
            with self.assertRaises(m.Error):
                self.source.export_profiles(self.file, "main", replace=replace)
        with self.assertRaises(m.Error):
            self.target.import_profiles(self.file)
        self.assertEqual(m.read_json(victim), {"keep": True})

    def test_import_renames_a_single_account(self):
        self.bundle([self.record("main", "a")])
        self.target.import_profiles(self.file, name="laptop")
        self.assertEqual(m.read_json(self.target.path("laptop")), auth("a"))
        self.assertFalse(self.target.path("main").exists())
        self.assertFalse(self.target.auth.exists())

    def test_raw_official_auth_requires_name_and_is_supported(self):
        m.write_json(self.file, auth("a"))
        with self.assertRaisesRegex(m.Error, "--name"):
            self.target.import_profiles(self.file)
        self.target.import_profiles(self.file, name="main")
        self.assertEqual(m.read_json(self.target.path("main")), auth("a"))

    def test_importing_multiple_accounts_cannot_use_one_name(self):
        self.bundle([self.record("main", "a"), self.record("second", "b")])
        with self.assertRaisesRegex(m.Error, "--name"):
            self.target.import_profiles(self.file, name="laptop")
        self.assertEqual(self.target.entries(), [])

    def test_invalid_bundle_format_or_version_changes_nothing(self):
        for changes in ({"format": "other"}, {"version": 2}, {"version": True}, {"version": "1"}, {"accounts": []}, {"accounts": {}}):
            with self.subTest(changes=changes):
                self.bundle([self.record("main", "a")], **changes)
                with self.assertRaises(m.Error):
                    self.target.import_profiles(self.file)
                self.assertEqual(self.target.entries(), [])

    def test_invalid_final_record_prevents_partial_import(self):
        cases = [None, {}, {"name": 1, "auth": auth("b")},
                 {"name": "bad", "auth": []}, {"name": "bad", "auth": {"tokens": {}}}]
        for bad in cases:
            with self.subTest(bad=bad):
                self.bundle([self.record("main", "a"), bad])
                with self.assertRaises(m.Error):
                    self.target.import_profiles(self.file)
                self.assertEqual(self.target.entries(), [])

    def test_duplicate_names_or_identities_prevent_partial_import(self):
        for second in (self.record("main", "b"), self.record("other", "a")):
            self.bundle([self.record("main", "a"), second])
            with self.assertRaises(m.Error):
                self.target.import_profiles(self.file, replace=True)
            self.assertEqual(self.target.entries(), [])

    def test_import_rejects_path_traversal(self):
        for name in ("../outside", "/tmp/outside", "a/b", "", "a" * 49):
            with self.subTest(name=name):
                self.bundle([self.record(name, "a")])
                with self.assertRaises(m.Error):
                    self.target.import_profiles(self.file)
        self.assertEqual(self.target.entries(), [])

    def test_name_conflict_preserves_all_profiles_without_replace(self):
        self.target.save("second", auth("local"))
        self.bundle([self.record("main", "a"), self.record("second", "b")])
        with self.assertRaisesRegex(m.Error, "--replace"):
            self.target.import_profiles(self.file)
        self.assertEqual(self.target.entries(), [("second", auth("local"))])

    def test_explicit_replace_changes_snapshot_but_not_live_login(self):
        self.target.save("main", auth("local"))
        m.write_json(self.target.auth, auth("local"))
        self.bundle([self.record("main", "a")])
        self.target.import_profiles(self.file, replace=True)
        self.assertEqual(m.read_json(self.target.path("main")), auth("a"))
        self.assertEqual(m.read_json(self.target.auth), auth("local"))

    def test_identity_saved_under_another_name_is_not_duplicated(self):
        self.target.save("original", auth("a"))
        self.bundle([self.record("renamed", "a")])
        with self.assertRaises(m.Error):
            self.target.import_profiles(self.file, replace=True)
        self.assertEqual(self.target.entries(), [("original", auth("a"))])

    def test_import_preserves_newest_same_account_credentials(self):
        old = dict(auth("a", "old"), last_refresh="2026-10-19T00:00:00Z")
        new = dict(auth("a", "new"), last_refresh="2026-10-20T00:00:00Z")
        for saved, imported, live in ((new, old, None), (old, new, None), (old, old, new)):
            with self.subTest(saved=saved["last_refresh"], imported=imported["last_refresh"], live=live is not None):
                self.target.save("main", saved)
                if live is not None:
                    m.write_json(self.target.auth, live)
                self.bundle([{"name": "main", "auth": imported}])
                self.target.import_profiles(self.file)
                self.assertEqual(m.read_json(self.target.path("main")), new)

    def test_import_with_no_timestamps_prefers_local_credentials(self):
        self.target.save("main", auth("a", "local"))
        self.bundle([self.record("main", "a")])
        self.target.import_profiles(self.file)
        self.assertEqual(m.read_json(self.target.path("main")), auth("a", "local"))

    def test_malformed_or_oversized_input_changes_nothing(self):
        for data in (b'not JSON', b'[]', b'{"value":' + b'[' * 1500 + b'0' + b']' * 1500 + b'}'):
            self.file.write_bytes(data)
            with self.assertRaises(m.Error):
                self.target.import_profiles(self.file)
        self.bundle([self.record("main", "a")])
        with patch.object(m, "MAX_TRANSFER_BYTES", 20), self.assertRaises(m.Error):
            self.target.import_profiles(self.file)
        self.assertEqual(self.target.entries(), [])

    def test_fifo_input_is_rejected_without_blocking(self):
        os.mkfifo(self.file)
        with self.assertRaises(m.Error):
            self.target.import_profiles(self.file)

    def test_oversized_export_does_not_create_a_file(self):
        self.source.save("main", auth("a"))
        with patch.object(m, "MAX_TRANSFER_BYTES", 20), self.assertRaises(m.Error):
            self.source.export_profiles(self.file, "main")
        self.assertFalse(self.file.exists())

    def test_failed_batch_write_rolls_back_new_and_existing_profiles(self):
        self.target.save("second", auth("local"))
        self.bundle([self.record("main", "a"), self.record("second", "b"), self.record("third", "c")])
        original = m.os.replace
        def fail_third(source, target):
            if Path(target) == self.target.path("third"):
                raise OSError("simulated disk failure")
            return original(source, target)
        with patch.object(m.os, "replace", side_effect=fail_third), self.assertRaises(OSError):
            self.target.import_profiles(self.file, replace=True)
        self.assertEqual(self.target.entries(), [("second", auth("local"))])
        self.assertEqual(list(self.target.root.glob("import-*")), [])

    def test_failed_rollback_keeps_recovery_backups(self):
        self.target.save("main", auth("local"))
        self.bundle([self.record("main", "a"), self.record("second", "b")])
        original = m.os.replace
        def fail_install_and_restore(source, target):
            restoring = Path(source).parent.name == "backup" and Path(target).parent == self.target.profiles
            if Path(target) == self.target.path("second") or restoring:
                raise OSError("simulated disk failure")
            return original(source, target)
        with patch.object(m.os, "replace", side_effect=fail_install_and_restore), self.assertRaisesRegex(m.Error, "恢复副本"):
            self.target.import_profiles(self.file, replace=True)
        staging = next(self.target.root.glob("import-*"))
        self.assertEqual(m.read_json(staging / "backup/main.json"), auth("local"))
        self.assertEqual(stat.S_IMODE(staging.stat().st_mode), 0o700)

    def test_staging_failure_leaves_existing_profiles_untouched(self):
        self.target.save("main", auth("local"))
        self.bundle([self.record("main", "a"), self.record("second", "b")])
        original = m.write_json
        def fail_preparation(path, value, **kwargs):
            if path.parent.name == "new" and path.name == "second.json":
                raise OSError("simulated disk failure")
            return original(path, value, **kwargs)
        with patch.object(m, "write_json", side_effect=fail_preparation), self.assertRaises(OSError):
            self.target.import_profiles(self.file, replace=True)
        self.assertEqual(self.target.entries(), [("main", auth("local"))])
        self.assertEqual(list(self.target.root.glob("import-*")), [])

    def test_cli_export_and_import_are_offline(self):
        self.source.save("main", auth("a"))
        # Release fixture locks so main() can acquire each home's lock itself.
        with tempfile.TemporaryDirectory(dir=self.root) as home:
            current = m.Accounts(Path(home))
            with current.locked():
                current.save("main", auth("a"))
            with patch.object(m.native_codex, "login") as login, patch.object(m.native_codex, "rate_limits") as usage:
                self.assertEqual(m.main(["--home", home, "export", "--all", "-o", str(self.file)]), 0)
                with tempfile.TemporaryDirectory(dir=self.root) as destination:
                    self.assertEqual(m.main(["--home", destination, "import", str(self.file), "--name", "laptop"]), 0)
                    self.assertEqual(m.read_json(m.Accounts(Path(destination)).path("laptop")), auth("a"))
                login.assert_not_called()
                usage.assert_not_called()

    def test_cli_rejects_name_combined_with_all(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            m.main(["export", "main", "--all", "-o", str(self.file)])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
