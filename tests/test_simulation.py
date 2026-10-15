import math
import unittest

from rosterlab.demo import build_demo_state
from rosterlab.optimizer import recommend_moves
from rosterlab.simulation import OutcomeCube


def correlation(first, second):
    first_mean = sum(first) / len(first)
    second_mean = sum(second) / len(second)
    covariance = sum((a - first_mean) * (b - second_mean) for a, b in zip(first, second))
    first_var = sum((value - first_mean) ** 2 for value in first)
    second_var = sum((value - second_mean) ** 2 for value in second)
    return covariance / math.sqrt(first_var * second_var)


class SimulationTests(unittest.TestCase):
    def test_same_team_pass_catchers_share_simulated_factors(self):
        state = build_demo_state()
        cube = OutcomeCube(state, iterations=400, seed=9)
        by_team = {}
        for player in state.players.values():
            by_team.setdefault(player.pro_team_id, {})[player.position] = player.player_id
        group = next(
            positions
            for positions in by_team.values()
            if "QB" in positions and "WR" in positions
        )
        qb = cube.player_outcomes(group["QB"], state.settings.current_week)
        receiver = cube.player_outcomes(group["WR"], state.settings.current_week)
        self.assertGreater(correlation(qb, receiver), 0.10)

    def test_persistent_role_uncertainty_creates_cross_week_dependence(self):
        state = build_demo_state()
        cube = OutcomeCube(state, iterations=600, seed=19)
        player_ids = {player.name: player.player_id for player in state.players.values()}
        current_week = state.settings.current_week
        breakout_correlation = correlation(
            cube.player_outcomes(player_ids["Breakout Back"], current_week),
            cube.player_outcomes(player_ids["Breakout Back"], current_week + 1),
        )
        safe_correlation = correlation(
            cube.player_outcomes(player_ids["Safe Slot Receiver"], current_week),
            cube.player_outcomes(player_ids["Safe Slot Receiver"], current_week + 1),
        )
        self.assertGreater(breakout_correlation, safe_correlation + 0.15)

    def test_recommendations_are_reproducible_and_probability_based(self):
        state = build_demo_state()
        first = recommend_moves(
            state, team_id=1, iterations=80, seed=77, top_free_agents=5, simulate_pairs=8
        )
        second = recommend_moves(
            state, team_id=1, iterations=80, seed=77, top_free_agents=5, simulate_pairs=8
        )
        self.assertEqual(first.baseline.title_probability, second.baseline.title_probability)
        self.assertEqual(first.moves, second.moves)
        self.assertTrue(any(move.playoff_delta > 0 or move.title_delta > 0 for move in first.moves))
        self.assertTrue(all(move.paired_points_delta.count == 80 for move in first.moves))
        self.assertTrue(any(move.pareto_optimal for move in first.moves))

    def test_short_and_playoff_objectives_select_different_archetypes(self):
        state = build_demo_state()
        recommendations = recommend_moves(
            state, team_id=1, iterations=80, seed=77, top_free_agents=10, simulate_pairs=24
        )
        short_leader = min(
            recommendations.moves, key=lambda move: move.objective_ranks["next_3_points"]
        )
        playoff_leader = min(
            recommendations.moves, key=lambda move: move.objective_ranks["playoff_window"]
        )
        self.assertEqual(state.players[short_leader.add_player_id].name, "Win-Now Workhorse")
        self.assertEqual(state.players[playoff_leader.add_player_id].name, "Playoff Hammer")
        self.assertEqual(short_leader.objective_regret["next_3_points"], 0.0)
        self.assertEqual(playoff_leader.objective_regret["playoff_window"], 0.0)


if __name__ == "__main__":
    unittest.main()
