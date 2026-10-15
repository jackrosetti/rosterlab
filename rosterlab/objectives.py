from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, Iterable, Mapping, Sequence, Tuple

from .models import MoveEvaluation


@dataclass(frozen=True)
class ObjectiveDefinition:
    key: str
    label: str
    horizon: str
    unit: str
    description: str


OBJECTIVES: Tuple[ObjectiveDefinition, ...] = (
    ObjectiveDefinition("title", "Title odds", "Season", "probability", "Maximize championship probability."),
    ObjectiveDefinition("playoffs", "Playoff odds", "Season", "probability", "Maximize probability of qualifying for the playoffs."),
    ObjectiveDefinition("this_week", "Win now", "This week", "probability", "Maximize this matchup's win probability against the actual opponent."),
    ObjectiveDefinition("expected_wins", "Expected wins", "Regular season", "wins", "Maximize expected remaining standings wins."),
    ObjectiveDefinition("next_3_points", "Next 3 weeks", "Short run", "points", "Maximize expected optimal-lineup points over the next three weeks."),
    ObjectiveDefinition("playoff_window", "Playoff window", "Weeks after regular season", "points", "Maximize expected optimal-lineup points during fantasy playoff weeks."),
    ObjectiveDefinition("rest_points", "Rest-of-season points", "Season", "points", "Maximize expected optimal-lineup points across all remaining weeks."),
    ObjectiveDefinition("floor", "Downside protection", "Season", "points", "Maximize the 10th percentile of the paired rest-of-season point change."),
    ObjectiveDefinition("upside", "Upside capture", "Season", "points", "Maximize the 90th percentile of the paired rest-of-season point change."),
    ObjectiveDefinition("reliability", "Reliability", "Season", "probability", "Maximize P(move helps) minus P(move hurts) in paired simulated worlds."),
    ObjectiveDefinition("comparative_advantage", "Comparative advantage", "League market", "points", "Maximize your lineup gain relative to the median rival's gain from the same player."),
)

OBJECTIVE_BY_KEY = {objective.key: objective for objective in OBJECTIVES}


def scores_for_move(move: MoveEvaluation) -> Dict[str, float]:
    return {
        "title": move.title_delta,
        "playoffs": move.playoff_delta,
        "this_week": move.current_week_win_delta,
        "expected_wins": move.expected_wins_delta,
        "next_3_points": move.short_horizon_points_delta,
        "playoff_window": move.playoff_window_points_delta,
        "rest_points": move.remaining_points_delta,
        "floor": move.floor_delta,
        "upside": move.upside_delta,
        "reliability": move.probability_points_improve - move.probability_points_decline,
        "comparative_advantage": move.comparative_advantage,
    }


def rank_moves(
    moves: Sequence[MoveEvaluation], primary_objective: str
) -> Tuple[MoveEvaluation, ...]:
    if primary_objective not in OBJECTIVE_BY_KEY:
        raise ValueError(f"Unknown objective {primary_objective!r}")
    score_maps = [scores_for_move(move) for move in moves]
    ranks_by_objective: Dict[str, Dict[int, int]] = {}
    regrets_by_objective: Dict[str, Dict[int, float]] = {}
    for objective in OBJECTIVES:
        ordered = sorted(
            range(len(moves)), key=lambda index: score_maps[index][objective.key], reverse=True
        )
        best_value = score_maps[ordered[0]][objective.key] if ordered else 0.0
        ranks: Dict[int, int] = {}
        regrets: Dict[int, float] = {}
        prior_value = None
        dense_rank = 0
        for index in ordered:
            value = score_maps[index][objective.key]
            if prior_value is None or abs(value - prior_value) > 1e-12:
                dense_rank += 1
                prior_value = value
            ranks[index] = dense_rank
            regrets[index] = best_value - value
        ranks_by_objective[objective.key] = ranks
        regrets_by_objective[objective.key] = regrets

    pareto_keys = ("title", "playoffs", "this_week", "floor", "comparative_advantage")
    enriched = []
    for index, move in enumerate(moves):
        dominated = any(
            other_index != index
            and all(score_maps[other_index][key] >= score_maps[index][key] for key in pareto_keys)
            and any(score_maps[other_index][key] > score_maps[index][key] for key in pareto_keys)
            for other_index in range(len(moves))
        )
        objective_ranks = {
            objective.key: ranks_by_objective[objective.key][index] for objective in OBJECTIVES
        }
        objective_regret = {
            objective.key: regrets_by_objective[objective.key][index] for objective in OBJECTIVES
        }
        enriched.append(
            replace(
                move,
                objective_scores=score_maps[index],
                objective_ranks=objective_ranks,
                objective_regret=objective_regret,
                pareto_optimal=not dominated,
                top_three_objectives=sum(1 for rank in objective_ranks.values() if rank <= 3),
            )
        )
    return tuple(
        sorted(
            enriched,
            key=lambda move: (
                move.objective_scores[primary_objective],
                move.top_three_objectives,
                move.title_delta,
            ),
            reverse=True,
        )
    )
