import tempfile
import unittest
from pathlib import Path

from rosterlab.ingest import build_league_state
from rosterlab.snapshots import SnapshotStore


def player_wrapper(player_id, name, position_id, eligible, on_team_id, status, projections):
    stats = [
        {
            "seasonId": 2026,
            "scoringPeriodId": week,
            "statSourceId": 1,
            "appliedTotal": points,
        }
        for week, points in projections.items()
    ]
    stats.extend(
        [
            {"seasonId": 2026, "scoringPeriodId": 1, "statSourceId": 0, "appliedTotal": 8.0},
            {"seasonId": 2026, "scoringPeriodId": 2, "statSourceId": 0, "appliedTotal": 12.0},
        ]
    )
    return {
        "id": player_id,
        "onTeamId": on_team_id,
        "status": status,
        "player": {
            "id": player_id,
            "fullName": name,
            "defaultPositionId": position_id,
            "eligibleSlots": eligible,
            "proTeamId": player_id,
            "injuryStatus": "ACTIVE",
            "stats": stats,
        },
    }


class IngestTests(unittest.TestCase):
    def test_builds_state_from_timestamped_raw_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SnapshotStore(Path(directory) / "db.sqlite3")
            roster_player = player_wrapper(101, "Roster Runner", 2, [2, 23], 1, "ONTEAM", {3: 11.0})
            free_agent = player_wrapper(202, "Free Agent", 3, [4, 23], 0, "WAIVERS", {3: 13.0})
            league = {
                "scoringPeriodId": 3,
                "status": {"currentMatchupPeriod": 3, "finalScoringPeriod": 6},
                "settings": {
                    "name": "Insight Fantasy Football",
                    "rosterSettings": {"lineupSlotCounts": {"2": 1, "4": 1, "23": 1, "20": 3}},
                    "scheduleSettings": {
                        "matchupPeriodCount": 4,
                        "playoffTeamCount": 2,
                        "playoffMatchupPeriodLength": 1,
                        "matchupTieRule": "NONE",
                        "playoffMatchupTieRule": "HIGHER_SEED",
                        "playoffSeedingRule": "TOTAL_POINTS_SCORED",
                        "matchupPeriods": {"3": [3], "4": [4]},
                    },
                    "acquisitionSettings": {
                        "isUsingAcquisitionBudget": True,
                        "acquisitionBudget": 100,
                        "minimumBid": 0,
                        "acquisitionType": "WAIVERS_TRADITIONAL",
                        "waiverOrderResetRule": "MOVE_TO_END_AFTER_CLAIM",
                        "waiverProcessDays": ["MONDAY", "WEDNESDAY", "FRIDAY"],
                    },
                    "scoringSettings": {
                        "scoringType": "H2H_POINTS",
                        "scoringItems": [
                            {"statId": 3, "points": 0.04, "isReverseItem": False},
                            {"statId": 41, "points": 1.0, "isReverseItem": False},
                        ],
                    },
                },
                "teams": [
                    {
                        "id": 1,
                        "name": "Insight",
                        "record": {"overall": {"wins": 1, "losses": 1, "ties": 0, "pointsFor": 200}},
                        "transactionCounter": {"acquisitionBudgetSpent": 7},
                        "waiverRank": 2,
                        "roster": {"entries": [{"playerPoolEntry": roster_player}]},
                    },
                    {
                        "id": 2,
                        "name": "Rival",
                        "record": {"overall": {"wins": 1, "losses": 1, "ties": 0, "pointsFor": 190}},
                        "roster": {"entries": []},
                    },
                ],
                "schedule": [
                    {"matchupPeriodId": 3, "home": {"teamId": 1}, "away": {"teamId": 2}},
                    {"matchupPeriodId": 4, "home": {"teamId": 2}, "away": {"teamId": 1}},
                ],
            }
            store.append(source="test", kind="league", league_id=1, season=2026, payload=league)
            store.append(
                source="test",
                kind="pro_schedule",
                league_id=1,
                season=2026,
                payload={"settings": {"proTeams": []}},
            )
            for week in range(3, 7):
                roster = player_wrapper(101, "Roster Runner", 2, [2, 23], 1, "ONTEAM", {week: 11.0})
                agent_projections = {} if week == 4 else {week: 13.0}
                agent = player_wrapper(
                    202, "Free Agent", 3, [4, 23], 0, "WAIVERS", agent_projections
                )
                agent["player"]["stats"].append(
                    {
                        "seasonId": 2026,
                        "scoringPeriodId": 0,
                        "statSourceId": 1,
                        "appliedTotal": 60.0,
                    }
                )
                store.append(
                    source="test",
                    kind="player_pool",
                    league_id=1,
                    season=2026,
                    scoring_period=week,
                    payload={"players": [roster, agent]},
                )
            state = build_league_state(store, league_id=1, season=2026)
            self.assertEqual(state.settings.name, "Insight Fantasy Football")
            self.assertEqual(state.settings.active_slot_ids, (2, 4, 23))
            self.assertEqual(state.settings.roster_slot_counts[20], 3)
            self.assertEqual(state.settings.scoring_type, "H2H_POINTS")
            self.assertEqual(state.settings.scoring_rules[0].label, "Passing yards")
            self.assertEqual(state.settings.scoring_rules[1].points, 1.0)
            self.assertEqual(state.settings.playoff_seeding_tiebreaker, "TOTAL_POINTS_SCORED")
            self.assertEqual(
                state.settings.waiver_process_days,
                ("MONDAY", "WEDNESDAY", "FRIDAY"),
            )
            self.assertEqual(state.teams[1].roster, (101,))
            self.assertIn(202, state.free_agent_ids)
            self.assertEqual(state.forecasts[(202, 3)].mean, 13.0)
            self.assertEqual(state.forecasts[(202, 4)].mean, 10.0)
            self.assertEqual(state.forecasts[(202, 4)].source, "espn-season-rate")
            self.assertEqual(state.schedule[3], ((1, 2),))


if __name__ == "__main__":
    unittest.main()
