from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .distributions import paired_deltas, probability_negative, probability_positive, summarize
from .lineup import mean_lineup_value
from .models import LeagueState, MoveEvaluation, SimulationResult
from .objectives import OBJECTIVES, OBJECTIVE_BY_KEY, ObjectiveDefinition, rank_moves
from .simulation import LeagueSimulator, OutcomeCube, paired_delta_standard_error


@dataclass(frozen=True)
class RecommendationSet:
    baseline: SimulationResult
    moves: Tuple[MoveEvaluation, ...]
    iterations: int
    seed: int
    primary_objective: str
    objectives: Tuple[ObjectiveDefinition, ...]


def recommend_moves(
    state: LeagueState,
    *,
    team_id: int,
    iterations: int = 750,
    seed: int = 20260921,
    top_free_agents: int = 24,
    simulate_pairs: int = 72,
    primary_objective: str = "title",
) -> RecommendationSet:
    if team_id not in state.teams:
        raise ValueError(f"Unknown fantasy team id {team_id}")
    if primary_objective not in OBJECTIVE_BY_KEY:
        raise ValueError(
            f"Unknown objective {primary_objective!r}. Choose from {', '.join(OBJECTIVE_BY_KEY)}"
        )
    target = state.teams[team_id]
    weeks = range(state.settings.current_week, state.settings.final_week + 1)

    def rest_mean(player_id: int) -> float:
        values = [
            state.forecasts[(player_id, week)].mean
            for week in weeks
            if (player_id, week) in state.forecasts
        ]
        return sum(values) / len(values) if values else 0.0

    candidates = _candidate_free_agents(
        state,
        limit=top_free_agents,
        value=rest_mean,
    )
    rest_weeks = tuple(weeks)
    short_weeks = tuple(week for week in rest_weeks if week <= state.settings.current_week + 2)
    current_weeks = (state.settings.current_week,)
    playoff_weeks = tuple(
        week for week in rest_weeks if week > state.settings.regular_season_weeks
    )
    value_cache: Dict[Tuple[Tuple[int, ...], Tuple[int, ...]], float] = {}

    def lineup_value(roster: Sequence[int], horizon: Sequence[int]) -> float:
        key = (tuple(roster), tuple(horizon))
        if key not in value_cache:
            value_cache[key] = mean_lineup_value(
                key[0], state.players, state.forecasts, key[1], state.settings.active_slot_ids
            )
        return value_cache[key]

    baseline_values = {
        "rest": lineup_value(target.roster, rest_weeks),
        "short": lineup_value(target.roster, short_weeks),
        "current": lineup_value(target.roster, current_weeks),
        "playoff": lineup_value(target.roster, playoff_weeks),
    }
    pair_candidates: List[Dict[str, float]] = []
    for add_player_id in candidates:
        for drop_player_id in target.roster:
            roster = target.with_transaction(add_player_id, drop_player_id).roster
            pair_candidates.append(
                {
                    "long": lineup_value(roster, rest_weeks) - baseline_values["rest"],
                    "short": lineup_value(roster, short_weeks) - baseline_values["short"],
                    "current": lineup_value(roster, current_weeks) - baseline_values["current"],
                    "playoff": lineup_value(roster, playoff_weeks) - baseline_values["playoff"],
                    "add": add_player_id,
                    "drop": drop_player_id,
                }
            )
    selected = _diverse_preselection(pair_candidates, simulate_pairs)

    cube = OutcomeCube(state, iterations=iterations, seed=seed)
    simulator = LeagueSimulator(state, cube)
    baseline = simulator.evaluate(team_id)
    unique_adds = {int(row["add"]) for row in selected}
    unique_drops = {int(row["drop"]) for row in selected}
    rival_gain_by_add = {
        add_player_id: _rival_asset_gains(
            state, team_id, add_player_id, rest_weeks, lineup_value
        )
        for add_player_id in unique_adds
    }
    drop_externality = {
        drop_player_id: max(
            _rival_asset_gains(state, team_id, drop_player_id, rest_weeks, lineup_value),
            default=0.0,
        )
        for drop_player_id in unique_drops
    }
    scarcity_by_add = {
        add_player_id: _positional_scarcity(state, add_player_id, rest_weeks)
        for add_player_id in unique_adds
    }
    moves: List[MoveEvaluation] = []
    for row in selected:
        mean_delta = float(row["long"])
        add_player_id = int(row["add"])
        drop_player_id = int(row["drop"])
        changed_roster = target.with_transaction(add_player_id, drop_player_id).roster
        candidate = simulator.evaluate(team_id, changed_roster)
        playoff_delta = candidate.playoff_probability - baseline.playoff_probability
        title_delta = candidate.title_probability - baseline.title_probability
        current_delta = (
            candidate.current_week_win_probability - baseline.current_week_win_probability
        )
        rest_deltas = paired_deltas(
            baseline.remaining_points_outcomes, candidate.remaining_points_outcomes
        )
        short_deltas = paired_deltas(
            baseline.short_horizon_points_outcomes, candidate.short_horizon_points_outcomes
        )
        rest_summary = summarize(rest_deltas)
        short_summary = summarize(short_deltas)
        playoff_deltas = tuple(
            sum(
                candidate.weekly_score_outcomes[week][index]
                - baseline.weekly_score_outcomes[week][index]
                for week in playoff_weeks
            )
            for index in range(iterations)
        )
        rival_gains = rival_gain_by_add[add_player_id]
        median_rival_gain = median(rival_gains) if rival_gains else 0.0
        bid_low, bid_high = _heuristic_bid_band(
            state, target.faab_spent, playoff_delta, title_delta, mean_delta
        )
        moves.append(
            MoveEvaluation(
                add_player_id=add_player_id,
                drop_player_id=drop_player_id,
                playoff_delta=playoff_delta,
                title_delta=title_delta,
                current_week_win_delta=current_delta,
                playoff_delta_se=paired_delta_standard_error(
                    baseline.playoff_outcomes, candidate.playoff_outcomes
                ),
                title_delta_se=paired_delta_standard_error(
                    baseline.title_outcomes, candidate.title_outcomes
                ),
                mean_lineup_delta=mean_delta,
                expected_wins_delta=(
                    candidate.expected_remaining_wins - baseline.expected_remaining_wins
                ),
                short_horizon_points_delta=short_summary.mean,
                playoff_window_points_delta=(
                    sum(playoff_deltas) / len(playoff_deltas) if playoff_deltas else 0.0
                ),
                remaining_points_delta=rest_summary.mean,
                floor_delta=rest_summary.p10,
                upside_delta=rest_summary.p90,
                lower_tail_delta=(
                    candidate.remaining_points.cvar10 - baseline.remaining_points.cvar10
                ),
                volatility_delta=(
                    candidate.remaining_points.stdev - baseline.remaining_points.stdev
                ),
                probability_points_improve=probability_positive(rest_deltas),
                probability_points_decline=probability_negative(rest_deltas),
                comparative_advantage=mean_delta - median_rival_gain,
                max_rival_gain=max(rival_gains, default=0.0),
                drop_externality=drop_externality[drop_player_id],
                positional_scarcity=scarcity_by_add[add_player_id],
                paired_points_delta=rest_summary,
                paired_short_delta=short_summary,
                weekly_score_deltas={
                    week: summarize(
                        paired_deltas(
                            baseline.weekly_score_outcomes[week],
                            candidate.weekly_score_outcomes[week],
                        )
                    )
                    for week in state.weeks_remaining
                },
                candidate_weekly_scores=candidate.weekly_scores,
                paired_points_delta_outcomes=rest_deltas,
                objective_scores={},
                objective_ranks={},
                objective_regret={},
                pareto_optimal=False,
                top_three_objectives=0,
                bid_low=bid_low,
                bid_high=bid_high,
            )
        )
    ranked_moves = rank_moves(moves, primary_objective)
    return RecommendationSet(
        baseline=baseline,
        moves=ranked_moves,
        iterations=iterations,
        seed=seed,
        primary_objective=primary_objective,
        objectives=OBJECTIVES,
    )


def _candidate_free_agents(
    state: LeagueState,
    *,
    limit: int,
    value,
) -> Tuple[int, ...]:
    """Build a credible, position-balanced waiver shortlist.

    Raw fantasy-point sorting floods a one-QB league with quarterbacks and can
    promote inactive players whose only estimate is a positional fallback. The
    rotation reflects ordinary one-QB roster demand while still preserving
    multiple candidates at every startable position.
    """
    fallback_only_sources = {"position-fallback", "carry-forward-fallback"}

    def has_credible_signal(player_id: int) -> bool:
        forecasts = [
            state.forecasts.get((player_id, week)) for week in state.weeks_remaining
        ]
        return any(
            forecast is not None
            and forecast.source not in fallback_only_sources
            and forecast.mean > 0.0
            for forecast in forecasts
        )

    qualified = [
        player_id for player_id in state.free_agent_ids if has_credible_signal(player_id)
    ]
    by_position: Dict[str, List[int]] = {}
    for player_id in qualified:
        by_position.setdefault(state.players[player_id].position, []).append(player_id)
    for players in by_position.values():
        players.sort(key=value, reverse=True)

    rotation = (
        "RB",
        "WR",
        "RB",
        "WR",
        "TE",
        "QB",
        "RB",
        "WR",
        "TE",
        "QB",
        "D/ST",
        "K",
    )
    selected: List[int] = []
    offsets = {position: 0 for position in by_position}
    while len(selected) < limit:
        added = False
        for position in rotation:
            players = by_position.get(position, [])
            offset = offsets.get(position, 0)
            if offset >= len(players):
                continue
            selected.append(players[offset])
            offsets[position] = offset + 1
            added = True
            if len(selected) >= limit:
                break
        if not added:
            break

    if len(selected) < limit:
        remaining = sorted(
            (player_id for player_id in qualified if player_id not in selected),
            key=value,
            reverse=True,
        )
        selected.extend(remaining[: limit - len(selected)])
    return tuple(selected)


def _diverse_preselection(
    pair_candidates: Sequence[Mapping[str, float]], limit: int
) -> Tuple[Mapping[str, float], ...]:
    if limit <= 0:
        raise ValueError("simulate_pairs must be positive")
    selected: List[Mapping[str, float]] = []
    seen = set()
    lenses = ("long", "short", "current", "playoff")
    per_lens = max(1, (limit + len(lenses) - 1) // len(lenses))
    for lens in lenses:
        for row in sorted(pair_candidates, key=lambda item: item[lens], reverse=True)[:per_lens]:
            key = (int(row["add"]), int(row["drop"]))
            if key not in seen:
                seen.add(key)
                selected.append(row)
    for row in sorted(pair_candidates, key=lambda item: item["long"], reverse=True):
        if len(selected) >= limit:
            break
        key = (int(row["add"]), int(row["drop"]))
        if key not in seen:
            seen.add(key)
            selected.append(row)
    return tuple(selected[:limit])


def _rival_asset_gains(
    state: LeagueState,
    target_team_id: int,
    asset_player_id: int,
    weeks: Sequence[int],
    lineup_value,
) -> Tuple[float, ...]:
    gains = []
    for rival_id, rival in state.teams.items():
        if rival_id == target_team_id or asset_player_id in rival.roster:
            continue
        baseline = lineup_value(rival.roster, weeks)
        # Add the asset to a temporary roster and let the lineup solver measure
        # its marginal starting value. This is the rival's roster-slot-free
        # upper bound; it avoids pretending we know which bench player they
        # would drop and is much cheaper than enumerating every rival drop.
        expanded = tuple(rival.roster) + (asset_player_id,)
        gains.append(lineup_value(expanded, weeks) - baseline)
    return tuple(gains)


def _positional_scarcity(
    state: LeagueState, add_player_id: int, weeks: Sequence[int]
) -> float:
    player = state.players[add_player_id]

    def average(player_id: int) -> float:
        values = [
            state.forecasts[(player_id, week)].mean
            for week in weeks
            if (player_id, week) in state.forecasts
        ]
        return sum(values) / len(values) if values else 0.0

    alternatives = [
        player_id
        for player_id in state.free_agent_ids
        if player_id != add_player_id and state.players[player_id].position == player.position
    ]
    return average(add_player_id) - max((average(player_id) for player_id in alternatives), default=0.0)


def _heuristic_bid_band(
    state: LeagueState,
    spent: int,
    playoff_delta: float,
    title_delta: float,
    mean_lineup_delta: float,
) -> Tuple[Optional[int], Optional[int]]:
    if not state.settings.faab_enabled:
        return None, None
    remaining = max(0, state.settings.faab_budget - spent)
    if remaining == 0:
        return 0, 0
    playoff_pp = max(0.0, playoff_delta * 100.0)
    title_pp = max(0.0, title_delta * 100.0)
    lineup_component = max(0.0, mean_lineup_delta) / max(1.0, len(state.weeks_remaining))
    center_fraction = min(0.65, 0.02 + 0.025 * playoff_pp + 0.05 * title_pp + 0.01 * lineup_component)
    center = remaining * center_fraction
    low = max(state.settings.minimum_bid, int(round(center * 0.70)))
    high = max(low, min(remaining, int(round(center * 1.35))))
    return low, high
