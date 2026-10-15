from __future__ import annotations

import math
import random
from array import array
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from .distributions import summarize
from .lineup import Lineup, optimize_lineup, top_lineups
from .models import FantasyTeam, Forecast, LeagueState, SimulationResult


FloatArray = array


@dataclass(frozen=True)
class CorrelationCoefficients:
    game: float
    offense: float
    pass_factor: float
    rush_factor: float
    opponent_offense: float = 0.0


COEFFICIENTS = {
    "QB": CorrelationCoefficients(0.18, 0.42, 0.55, 0.00),
    "WR": CorrelationCoefficients(0.18, 0.30, 0.52, 0.00),
    "TE": CorrelationCoefficients(0.18, 0.30, 0.50, 0.00),
    "RB": CorrelationCoefficients(0.15, 0.38, 0.00, 0.48),
    "K": CorrelationCoefficients(0.24, 0.35, 0.00, 0.00),
    "D/ST": CorrelationCoefficients(0.12, 0.18, 0.00, 0.00, -0.35),
}


class OutcomeCube:
    """Common simulated player outcomes shared by every counterfactual move."""

    def __init__(self, state: LeagueState, iterations: int, seed: int = 20260921):
        if iterations < 50:
            raise ValueError("Use at least 50 iterations")
        self.state = state
        self.iterations = iterations
        self.seed = seed
        self.values: Dict[Tuple[int, int], FloatArray] = {}
        self._build()

    def _normals(self, rng: random.Random) -> FloatArray:
        return array("f", (rng.gauss(0.0, 1.0) for _ in range(self.iterations)))

    def _build(self) -> None:
        rng = random.Random(self.seed)
        weeks = self.state.weeks_remaining
        team_ids = sorted({p.pro_team_id for p in self.state.players.values() if p.pro_team_id > 0})
        game_latents: Dict[Tuple[int, Tuple[int, int]], FloatArray] = {}
        offense_latents: Dict[Tuple[int, int], FloatArray] = {}
        pass_latents: Dict[Tuple[int, int], FloatArray] = {}
        rush_latents: Dict[Tuple[int, int], FloatArray] = {}
        role_latents: Dict[int, FloatArray] = {
            player_id: self._normals(rng) for player_id in sorted(self.state.players)
        }

        for week in weeks:
            for team_id in team_ids:
                offense_latents[(week, team_id)] = self._normals(rng)
                pass_latents[(week, team_id)] = self._normals(rng)
                rush_raw = self._normals(rng)
                pass_values = pass_latents[(week, team_id)]
                rush_latents[(week, team_id)] = array(
                    "f",
                    (
                        -0.35 * pass_values[index] + math.sqrt(1.0 - 0.35**2) * rush_raw[index]
                        for index in range(self.iterations)
                    ),
                )
            game_keys = {
                tuple(sorted((forecast.player.pro_team_id, forecast.opponent_team_id)))
                for (player_id, forecast_week), forecast in self.state.forecasts.items()
                if forecast_week == week and forecast.player.pro_team_id > 0
            }
            for game_key in sorted(game_keys):
                game_latents[(week, game_key)] = self._normals(rng)

        for (player_id, week), forecast in sorted(self.state.forecasts.items()):
            if week not in weeks:
                continue
            if forecast.mean <= 0.001:
                self.values[(player_id, week)] = array("f", [0.0]) * self.iterations
                continue
            player = forecast.player
            coeff = COEFFICIENTS.get(
                player.position, CorrelationCoefficients(0.12, 0.25, 0.15, 0.15)
            )
            game_key = tuple(sorted((player.pro_team_id, forecast.opponent_team_id)))
            game = game_latents.get((week, game_key), array("f", [0.0]) * self.iterations)
            offense = offense_latents.get((week, player.pro_team_id), game)
            passing = pass_latents.get((week, player.pro_team_id), game)
            rushing = rush_latents.get((week, player.pro_team_id), game)
            opponent = offense_latents.get((week, forecast.opponent_team_id), game)
            idiosyncratic = self._normals(rng)
            role_weight = min(0.75, max(0.0, forecast.role_persistence))
            explained = (
                coeff.game**2
                + coeff.offense**2
                + coeff.pass_factor**2
                + coeff.rush_factor**2
                + coeff.opponent_offense**2
                + role_weight**2
            )
            residual = math.sqrt(max(0.05, 1.0 - explained))
            outcomes = array("f")
            for index in range(self.iterations):
                z_value = (
                    coeff.game * game[index]
                    + coeff.offense * offense[index]
                    + coeff.pass_factor * passing[index]
                    + coeff.rush_factor * rushing[index]
                    + coeff.opponent_offense * opponent[index]
                    + role_weight * role_latents[player_id][index]
                    + residual * idiosyncratic[index]
                )
                outcomes.append(self._sample_marginal(forecast, z_value))
            self.values[(player_id, week)] = outcomes

    @staticmethod
    def _sample_marginal(forecast: Forecast, z_value: float) -> float:
        distribution = forecast.distribution
        if distribution == "auto":
            distribution = "lognormal" if forecast.player.position in {"RB", "WR", "TE"} else "normal"
        if distribution == "lognormal" and forecast.mean > 0.0:
            # A Gaussian copula preserves the cross-player dependence while a
            # shifted lognormal captures the right-skew of skill-position scores.
            floor = -2.0
            shifted_mean = forecast.mean - floor
            variance_ratio = (forecast.stdev / max(0.25, shifted_mean)) ** 2
            sigma2 = math.log1p(variance_ratio)
            sigma = math.sqrt(sigma2)
            mu = math.log(max(0.25, shifted_mean)) - 0.5 * sigma2
            value = math.exp(mu + sigma * z_value) + floor
            return max(floor, min(forecast.mean + 7.0 * forecast.stdev, value))
        value = forecast.mean + forecast.stdev * z_value
        return max(-5.0, min(forecast.mean + 5.0 * forecast.stdev, value))

    def player_outcomes(self, player_id: int, week: int) -> FloatArray:
        return self.values.get((player_id, week), array("f", [0.0]) * self.iterations)


class LeagueSimulator:
    def __init__(self, state: LeagueState, cube: OutcomeCube):
        self.state = state
        self.cube = cube
        self.iterations = cube.iterations
        self._score_cache: Dict[Tuple[int, Tuple[int, ...], int], FloatArray] = {}

    def evaluate(self, team_id: int, roster_override: Optional[Sequence[int]] = None) -> SimulationResult:
        if team_id not in self.state.teams:
            raise ValueError(f"Unknown fantasy team id {team_id}")
        roster_by_team = {
            current_id: tuple(team.roster) for current_id, team in self.state.teams.items()
        }
        if roster_override is not None:
            roster_by_team[team_id] = tuple(roster_override)

        team_scores: Dict[Tuple[int, int], FloatArray] = {}
        for week in self.state.weeks_remaining:
            for current_id, roster in roster_by_team.items():
                team_scores[(current_id, week)] = self._score_array(current_id, roster, week)

        opponent_id = self._opponent(team_id, self.state.settings.current_week)
        if opponent_id is not None:
            target_roster = roster_by_team[team_id]
            team_scores[(team_id, self.state.settings.current_week)] = self._best_matchup_lineup_array(
                target_roster,
                self.state.settings.current_week,
                team_scores[(opponent_id, self.state.settings.current_week)],
            )

        weekly_score_outcomes = {
            week: tuple(float(value) for value in team_scores[(team_id, week)])
            for week in self.state.weeks_remaining
        }
        short_weeks = tuple(
            week
            for week in self.state.weeks_remaining
            if week <= self.state.settings.current_week + 2
        )
        short_horizon_points = tuple(
            sum(weekly_score_outcomes[week][iteration] for week in short_weeks)
            for iteration in range(self.iterations)
        )
        remaining_points = tuple(
            sum(weekly_score_outcomes[week][iteration] for week in self.state.weeks_remaining)
            for iteration in range(self.iterations)
        )
        current_scores = weekly_score_outcomes[self.state.settings.current_week]
        if opponent_id is not None:
            opponent_scores = team_scores[(opponent_id, self.state.settings.current_week)]
            current_margins = tuple(
                current_scores[index] - opponent_scores[index] for index in range(self.iterations)
            )
        else:
            current_margins = tuple(0.0 for _ in range(self.iterations))

        playoff_outcomes: List[int] = []
        title_outcomes: List[int] = []
        current_win_outcomes: List[int] = []
        remaining_wins_outcomes: List[float] = []
        finish_outcomes: List[int] = []
        for iteration in range(self.iterations):
            playoff, champion, current_win, remaining_wins, finish = self._run_iteration(
                team_id, team_scores, iteration, opponent_id
            )
            playoff_outcomes.append(1 if playoff else 0)
            title_outcomes.append(1 if champion == team_id else 0)
            current_win_outcomes.append(1 if current_win else 0)
            remaining_wins_outcomes.append(remaining_wins)
            finish_outcomes.append(finish)

        return SimulationResult(
            team_id=team_id,
            iterations=self.iterations,
            playoff_probability=sum(playoff_outcomes) / self.iterations,
            title_probability=sum(title_outcomes) / self.iterations,
            current_week_win_probability=sum(current_win_outcomes) / self.iterations,
            expected_remaining_wins=sum(remaining_wins_outcomes) / self.iterations,
            current_week_score=summarize(current_scores),
            current_week_margin=summarize(current_margins),
            short_horizon_points=summarize(short_horizon_points),
            remaining_points=summarize(remaining_points),
            regular_season_finish=summarize(finish_outcomes),
            weekly_scores={week: summarize(values) for week, values in weekly_score_outcomes.items()},
            playoff_outcomes=tuple(playoff_outcomes),
            title_outcomes=tuple(title_outcomes),
            current_week_win_outcomes=tuple(current_win_outcomes),
            remaining_wins_outcomes=tuple(remaining_wins_outcomes),
            current_week_score_outcomes=tuple(current_scores),
            current_week_margin_outcomes=tuple(current_margins),
            short_horizon_points_outcomes=short_horizon_points,
            remaining_points_outcomes=remaining_points,
            regular_season_finish_outcomes=tuple(finish_outcomes),
            weekly_score_outcomes=weekly_score_outcomes,
        )

    def _score_array(self, team_id: int, roster: Tuple[int, ...], week: int) -> FloatArray:
        cache_key = (team_id, roster, week)
        if cache_key in self._score_cache:
            return self._score_cache[cache_key]
        lineup = optimize_lineup(
            roster,
            self.state.players,
            self.state.forecasts,
            week,
            self.state.settings.active_slot_ids,
        )
        result = self._lineup_score_array(lineup, week)
        self._score_cache[cache_key] = result
        return result

    def _lineup_score_array(self, lineup: Lineup, week: int) -> FloatArray:
        result = array("f", [0.0]) * self.iterations
        for player_id in lineup.player_ids:
            player_values = self.cube.player_outcomes(player_id, week)
            for index in range(self.iterations):
                result[index] += player_values[index]
        return result

    def _best_matchup_lineup_array(
        self, roster: Tuple[int, ...], week: int, opponent_scores: FloatArray
    ) -> FloatArray:
        candidates = top_lineups(
            roster,
            self.state.players,
            self.state.forecasts,
            week,
            self.state.settings.active_slot_ids,
            limit=32,
        )
        best_values: Optional[FloatArray] = None
        best_wins = -1
        best_mean = -1.0
        for lineup in candidates:
            values = self._lineup_score_array(lineup, week)
            wins = sum(1 for index in range(self.iterations) if values[index] > opponent_scores[index])
            if wins > best_wins or (wins == best_wins and lineup.expected_points > best_mean):
                best_wins = wins
                best_mean = lineup.expected_points
                best_values = values
        return best_values if best_values is not None else array("f", [0.0]) * self.iterations

    def _run_iteration(
        self,
        target_team_id: int,
        team_scores: Mapping[Tuple[int, int], FloatArray],
        iteration: int,
        current_opponent_id: Optional[int],
    ) -> Tuple[bool, Optional[int], bool, float, int]:
        wins = {team_id: team.wins + 0.5 * team.ties for team_id, team in self.state.teams.items()}
        points = {team_id: team.points_for for team_id, team in self.state.teams.items()}
        current_win = current_opponent_id is None
        target_remaining_wins = 0.0

        for week in range(
            self.state.settings.current_week, self.state.settings.regular_season_weeks + 1
        ):
            scores = {
                team_id: team_scores[(team_id, week)][iteration] for team_id in self.state.teams
            }
            for first, second in self._week_pairs(week):
                first_score, second_score = scores[first], scores[second]
                points[first] += first_score
                points[second] += second_score
                if first_score > second_score:
                    wins[first] += 1.0
                    if first == target_team_id:
                        target_remaining_wins += 1.0
                elif second_score > first_score:
                    wins[second] += 1.0
                    if second == target_team_id:
                        target_remaining_wins += 1.0
                else:
                    wins[first] += 0.5
                    wins[second] += 0.5
                    if target_team_id in (first, second):
                        target_remaining_wins += 0.5
                if week == self.state.settings.current_week and target_team_id in (first, second):
                    target_score = scores[target_team_id]
                    opponent = second if target_team_id == first else first
                    current_win = target_score > scores[opponent]
            if self.state.settings.median_scoring:
                ordered = sorted(scores.values())
                median = ordered[len(ordered) // 2]
                for current_id, score in scores.items():
                    median_win = 1.0 if score > median else (0.5 if score == median else 0.0)
                    wins[current_id] += median_win
                    if current_id == target_team_id:
                        target_remaining_wins += median_win

        seeded = sorted(self.state.teams, key=lambda current_id: (wins[current_id], points[current_id]), reverse=True)
        playoff_ids = seeded[: self.state.settings.playoff_team_count]
        champion = self._simulate_playoffs(playoff_ids, team_scores, iteration)
        finish = seeded.index(target_team_id) + 1
        return target_team_id in playoff_ids, champion, current_win, target_remaining_wins, finish

    def _simulate_playoffs(
        self,
        seeded: Sequence[int],
        team_scores: Mapping[Tuple[int, int], FloatArray],
        iteration: int,
    ) -> Optional[int]:
        if not seeded:
            return None
        survivors = list(seeded)
        bracket_size = 1
        while bracket_size < len(survivors):
            bracket_size *= 2
        byes = bracket_size - len(survivors)
        week = self.state.settings.regular_season_weeks + 1
        round_index = 0
        while len(survivors) > 1:
            auto_advance = survivors[:byes] if round_index == 0 else []
            playing = survivors[byes:] if round_index == 0 else survivors
            winners = list(auto_advance)
            for index in range(len(playing) // 2):
                first = playing[index]
                second = playing[-1 - index]
                first_score = 0.0
                second_score = 0.0
                for offset in range(self.state.settings.playoff_matchup_period_length):
                    scoring_week = min(week + offset, self.state.settings.final_week)
                    first_score += team_scores[(first, scoring_week)][iteration]
                    second_score += team_scores[(second, scoring_week)][iteration]
                winners.append(first if first_score >= second_score else second)
            seed_order = {team_id: index for index, team_id in enumerate(seeded)}
            survivors = sorted(winners, key=lambda team_id: seed_order[team_id])
            week += self.state.settings.playoff_matchup_period_length
            round_index += 1
            byes = 0
        return survivors[0]

    def _week_pairs(self, week: int) -> Tuple[Tuple[int, int], ...]:
        pairs = self.state.schedule.get(week, ())
        valid = tuple(
            (first, second)
            for first, second in pairs
            if first in self.state.teams and second in self.state.teams
        )
        if valid:
            return valid
        team_ids = sorted(self.state.teams)
        rotation = (week - 1) % max(1, len(team_ids) - 1)
        if len(team_ids) % 2:
            team_ids.append(-1)
        fixed, rest = team_ids[0], team_ids[1:]
        rest = rest[rotation:] + rest[:rotation]
        arranged = [fixed] + rest
        return tuple(
            (arranged[index], arranged[-1 - index])
            for index in range(len(arranged) // 2)
            if arranged[index] != -1 and arranged[-1 - index] != -1
        )

    def _opponent(self, team_id: int, week: int) -> Optional[int]:
        for first, second in self._week_pairs(week):
            if first == team_id:
                return second
            if second == team_id:
                return first
        return None


def paired_delta_standard_error(baseline: Sequence[int], candidate: Sequence[int]) -> float:
    if len(baseline) != len(candidate) or len(baseline) < 2:
        return 0.0
    differences = [candidate[index] - baseline[index] for index in range(len(baseline))]
    mean = sum(differences) / len(differences)
    variance = sum((value - mean) ** 2 for value in differences) / (len(differences) - 1)
    return math.sqrt(variance / len(differences))
