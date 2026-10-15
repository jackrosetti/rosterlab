import tempfile
import unittest
from pathlib import Path

from rosterlab.snapshots import SnapshotStore


class SnapshotStoreTests(unittest.TestCase):
    def test_snapshots_are_append_only_and_support_as_of_queries(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SnapshotStore(Path(directory) / "snapshots.sqlite3")
            first = store.append(
                source="test",
                kind="league",
                league_id=10,
                season=2026,
                observed_at="2026-09-21T10:00:00+00:00",
                payload={"version": 1},
            )
            second = store.append(
                source="test",
                kind="league",
                league_id=10,
                season=2026,
                observed_at="2026-09-21T12:00:00+00:00",
                payload={"version": 2},
            )
            self.assertNotEqual(first.snapshot_id, second.snapshot_id)
            self.assertEqual(
                store.latest(kind="league", league_id=10, season=2026).payload["version"], 2
            )
            historical = store.latest(
                kind="league",
                league_id=10,
                season=2026,
                as_of="2026-09-21T11:00:00+00:00",
            )
            self.assertEqual(historical.payload["version"], 1)


if __name__ == "__main__":
    unittest.main()

