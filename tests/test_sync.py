import tempfile
import unittest
from pathlib import Path

from rosterlab.espn import ESPNConfig
from rosterlab.snapshots import SnapshotStore
from rosterlab.sync import detect_owned_team_id, sync_league


class FakeESPNClient:
    def __init__(self):
        self.config = ESPNConfig(99, 2026, "secret", "{owner-id}")

    def fetch_league(self):
        return {
            "id": 99,
            "scoringPeriodId": 3,
            "status": {"currentMatchupPeriod": 3, "finalScoringPeriod": 4},
            "settings": {"name": "Insight"},
            "teams": [
                {"id": 1, "primaryOwner": "someone-else"},
                {"id": 7, "owners": ["owner-id"]},
            ],
        }

    def fetch_pro_schedule(self):
        return {"settings": {"proTeams": []}}

    def fetch_player_pool(self, scoring_period):
        return {"players": [], "requestedScoringPeriodId": scoring_period}

    def fetch_waiver_offers(self, scoring_period):
        return {"transactions": [], "requestedScoringPeriodId": scoring_period}


class SyncTests(unittest.TestCase):
    def test_detects_owned_team_across_swid_brace_formats(self):
        payload = FakeESPNClient().fetch_league()
        self.assertEqual(detect_owned_team_id(payload, "{OWNER-ID}"), 7)

    def test_sync_commits_one_timestamped_snapshot_set(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SnapshotStore(Path(directory) / "sync.sqlite3")
            result = sync_league(
                FakeESPNClient(),
                store,
                observed_at="2026-10-14T12:00:00+00:00",
            )
            self.assertEqual(result.owned_team_id, 7)
            self.assertEqual(result.player_pool_weeks, (3, 4))
            self.assertEqual(result.waiver_weeks, (1, 2, 3))
            self.assertEqual(result.snapshot_count, 7)
            league = store.latest(kind="league", league_id=99, season=2026)
            self.assertEqual(league.observed_at, result.observed_at)
            self.assertEqual(store.periods(kind="player_pool", league_id=99, season=2026), [3, 4])


if __name__ == "__main__":
    unittest.main()
