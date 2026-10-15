import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rosterlab.auth import (
    CredentialError,
    ESPNCredentials,
    credentials_from_environment,
    _store_keychain_payload,
    normalize_swid,
    prompt_credentials_native,
    save_credentials,
)
from rosterlab.profile import LocalProfile, load_profile, save_profile


class AuthTests(unittest.TestCase):
    @patch("rosterlab.auth.subprocess.run")
    def test_keychain_helper_receives_secret_over_stdin_not_process_arguments(self, run):
        run.return_value.returncode = 0
        _store_keychain_payload(account="league:99:season:2026", payload="very-secret")
        command = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        self.assertNotIn("very-secret", command)
        self.assertEqual(kwargs["input"], "very-secret")

    def test_normalizes_swid_and_requires_cookie_pair(self):
        self.assertEqual(normalize_swid("abc-123"), "{abc-123}")
        self.assertEqual(normalize_swid("'{abc-123}'"), "{abc-123}")
        credentials = credentials_from_environment(
            {"ESPN_S2": "secret", "ESPN_SWID": "owner-id"}
        )
        self.assertEqual(credentials.swid, "{owner-id}")
        with self.assertRaises(CredentialError):
            credentials_from_environment({"ESPN_S2": "secret"})

    @patch("rosterlab.auth.keychain_supported", return_value=True)
    @patch("rosterlab.auth._store_keychain_payload")
    def test_keychain_save_sends_secret_over_stdin_not_process_arguments(
        self, store, _supported
    ):
        save_credentials(
            ESPNCredentials(espn_s2="very-secret", swid="{owner}"),
            league_id=99,
            season=2026,
        )
        kwargs = store.call_args.kwargs
        self.assertEqual(kwargs["account"], "league:99:season:2026")
        self.assertIn("very-secret", kwargs["payload"])

    def test_profile_contains_only_non_secret_connection_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            profile = LocalProfile(
                league_id=99,
                season=2026,
                team_id=4,
                league_name="Insight",
                last_sync_at="2026-10-14T12:00:00+00:00",
            )
            save_profile(profile, path)
            self.assertEqual(load_profile(path), profile)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertNotIn("espn_s2", path.read_text(encoding="utf-8"))

    @patch("rosterlab.auth.native_prompt_supported", return_value=True)
    @patch("rosterlab.auth.subprocess.run")
    def test_native_prompt_collects_hidden_values_without_putting_them_in_arguments(
        self, run, _supported
    ):
        run.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="s2-secret\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="owner-id\n", stderr=""),
        ]
        credentials = prompt_credentials_native()
        self.assertEqual(credentials, ESPNCredentials("s2-secret", "{owner-id}"))
        for call in run.call_args_list:
            command = call.args[0]
            self.assertNotIn("s2-secret", command)
            self.assertNotIn("owner-id", command)


if __name__ == "__main__":
    unittest.main()
