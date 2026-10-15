import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from rosterlab.cli import main
from rosterlab.snapshots import SnapshotStore


def roster_entry(player_id, name, position_id, slots):
    return {
        "playerPoolEntry": {
            "id": player_id,
            "onTeamId": 1,
            "status": "ONTEAM",
            "player": {
                "id": player_id,
                "fullName": name,
                "defaultPositionId": position_id,
                "eligibleSlots": slots,
                "proTeamId": 1,
                "injuryStatus": "ACTIVE",
                "stats": [],
            },
        }
    }


class CLITests(unittest.TestCase):
    def test_league_command_audits_synced_rules_and_rosters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "league.sqlite3"
            store = SnapshotStore(db)
            league = {
                "id": 99,
                "scoringPeriodId": 3,
                "status": {"currentMatchupPeriod": 3, "finalScoringPeriod": 4},
                "settings": {
                    "name": "Insight",
                    "rosterSettings": {"lineupSlotCounts": {"0": 1, "2": 1, "20": 2}},
                    "scheduleSettings": {
                        "matchupPeriodCount": 3,
                        "playoffTeamCount": 2,
                        "playoffMatchupPeriodLength": 1,
                        "matchupPeriods": {"3": [3]},
                    },
                    "acquisitionSettings": {
                        "isUsingAcquisitionBudget": True,
                        "acquisitionBudget": 100,
                        "minimumBid": 1,
                    },
                    "scoringSettings": {
                        "scoringType": "H2H_POINTS",
                        "scoringItems": [{"statId": 41, "points": 1.0}],
                    },
                },
                "teams": [
                    {
                        "id": 1,
                        "name": "Insight Team",
                        "record": {"overall": {}},
                        "roster": {"entries": [roster_entry(10, "Test Runner", 2, [2, 20])]},
                    },
                    {"id": 2, "name": "Rival", "record": {"overall": {}}, "roster": {"entries": []}},
                ],
                "schedule": [
                    {"matchupPeriodId": 3, "home": {"teamId": 1}, "away": {"teamId": 2}}
                ],
            }
            store.append(source="test", kind="league", league_id=99, season=2026, payload=league)
            store.append(
                source="test",
                kind="pro_schedule",
                league_id=99,
                season=2026,
                payload={"settings": {"proTeams": []}},
            )

            output = io.StringIO()
            with redirect_stdout(output):
                main(
                    [
                        "league",
                        "--league-id",
                        "99",
                        "--season",
                        "2026",
                        "--db",
                        str(db),
                        "--profile",
                        str(root / "profile.json"),
                        "--show-scoring",
                    ]
                )
            rendered = output.getvalue()
            self.assertIn("Insight — ESPN league 99, 2026", rendered)
            self.assertIn("Roster: 1 QB, 1 RB, 2 BE", rendered)
            self.assertIn("41  Receptions", rendered)
            self.assertIn("Test Runner", rendered)


if __name__ == "__main__":
    unittest.main()
