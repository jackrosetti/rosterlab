from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from .models import Forecast, Player


@dataclass(frozen=True)
class Lineup:
    player_ids: Tuple[int, ...]
    slot_assignments: Tuple[Tuple[int, int], ...]
    expected_points: float


def optimize_lineup(
    roster: Sequence[int],
    players: Mapping[int, Player],
    forecasts: Mapping[Tuple[int, int], Forecast],
    week: int,
    active_slot_ids: Sequence[int],
) -> Lineup:
    """Maximize expected points with ESPN's player-to-slot eligibility.

    Dynamic programming over a bitmask keeps this exact without an external solver.
    Duplicate slot types are represented as separate bit positions.
    """
    return top_lineups(roster, players, forecasts, week, active_slot_ids, limit=1)[0]


def top_lineups(
    roster: Sequence[int],
    players: Mapping[int, Player],
    forecasts: Mapping[Tuple[int, int], Forecast],
    week: int,
    active_slot_ids: Sequence[int],
    limit: int = 40,
) -> List[Lineup]:
    """Return the strongest distinct legal lineups by expected points.

    Retaining several candidates lets the simulator choose the current-week
    lineup that maximizes empirical win probability against the actual opponent.
    """
    slots = tuple(active_slot_ids)
    if not slots:
        return [Lineup((), (), 0.0)]

    # mask -> [(score, ((player_id, slot_index), ...)), ...]
    states: Dict[int, List[Tuple[float, Tuple[Tuple[int, int], ...]]]] = {0: [(0.0, ())]}
    for player_id in roster:
        player = players.get(player_id)
        forecast = forecasts.get((player_id, week))
        if player is None or forecast is None:
            continue
        prior = [(mask, list(candidates)) for mask, candidates in states.items()]
        additions: Dict[int, List[Tuple[float, Tuple[Tuple[int, int], ...]]]] = {}
        for mask, candidates in prior:
            for score, assignments in candidates:
                for slot_index, slot_id in enumerate(slots):
                    bit = 1 << slot_index
                    if mask & bit or slot_id not in player.eligible_slot_ids:
                        continue
                    new_mask = mask | bit
                    additions.setdefault(new_mask, []).append(
                        (score + forecast.mean, assignments + ((player_id, slot_index),))
                    )
        for mask, candidates in additions.items():
            combined = states.get(mask, []) + candidates
            combined.sort(key=lambda item: item[0], reverse=True)
            states[mask] = combined[:limit]

    max_filled = max(_bit_count(mask) for mask in states)
    candidates = []
    seen = set()
    for mask, values in states.items():
        if _bit_count(mask) != max_filled:
            continue
        for score, raw_assignments in values:
            player_ids = tuple(sorted(player_id for player_id, _ in raw_assignments))
            if player_ids in seen:
                continue
            seen.add(player_ids)
            assignments = tuple(
                (player_id, slots[slot_index]) for player_id, slot_index in raw_assignments
            )
            candidates.append(
                Lineup(
                    player_ids=tuple(player_id for player_id, _ in raw_assignments),
                    slot_assignments=assignments,
                    expected_points=score,
                )
            )
    candidates.sort(key=lambda lineup: lineup.expected_points, reverse=True)
    return candidates[:limit]


def _bit_count(value: int) -> int:
    return bin(value).count("1")


def mean_lineup_value(
    roster: Sequence[int],
    players: Mapping[int, Player],
    forecasts: Mapping[Tuple[int, int], Forecast],
    weeks: Iterable[int],
    active_slot_ids: Sequence[int],
) -> float:
    return sum(
        optimize_lineup(roster, players, forecasts, week, active_slot_ids).expected_points
        for week in weeks
    )
