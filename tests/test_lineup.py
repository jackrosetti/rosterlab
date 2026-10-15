import unittest

from rosterlab.lineup import optimize_lineup, top_lineups
from rosterlab.models import Forecast, Player


class LineupTests(unittest.TestCase):
    def test_flex_assignment_is_globally_optimal(self):
        players = {
            1: Player(1, "RB One", "RB", 1, (2, 23)),
            2: Player(2, "RB Two", "RB", 2, (2, 23)),
            3: Player(3, "WR One", "WR", 3, (4, 23)),
            4: Player(4, "WR Two", "WR", 4, (4, 23)),
        }
        means = {1: 12.0, 2: 10.0, 3: 11.0, 4: 4.0}
        forecasts = {
            (player_id, 3): Forecast(player, 3, means[player_id], 5.0)
            for player_id, player in players.items()
        }
        lineup = optimize_lineup((1, 2, 3, 4), players, forecasts, 3, (2, 4, 23))
        self.assertEqual(set(lineup.player_ids), {1, 2, 3})
        self.assertEqual(lineup.expected_points, 33.0)

    def test_top_lineups_are_distinct(self):
        players = {
            player_id: Player(player_id, f"WR {player_id}", "WR", player_id, (4, 23))
            for player_id in range(1, 5)
        }
        forecasts = {
            (player_id, 3): Forecast(player, 3, float(12 - player_id), 5.0)
            for player_id, player in players.items()
        }
        lineups = top_lineups(tuple(players), players, forecasts, 3, (4, 23), limit=5)
        player_sets = [frozenset(lineup.player_ids) for lineup in lineups]
        self.assertEqual(len(player_sets), len(set(player_sets)))
        self.assertEqual(player_sets[0], frozenset({1, 2}))


if __name__ == "__main__":
    unittest.main()

