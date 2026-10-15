from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


BENCH_SLOT_IDS = {20, 21, 24}


@dataclass(frozen=True)
class Player:
    player_id: int
    name: str
    position: str
    pro_team_id: int
    eligible_slot_ids: Tuple[int, ...]
    injury_status: str = "ACTIVE"


@dataclass(frozen=True)
class Forecast:
    player: Player
    week: int
    mean: float
    stdev: float
    opponent_team_id: int = 0
    source: str = "espn"
    # Share of standardized weekly uncertainty driven by a player-level latent
    # role state that persists across the simulated season. Higher values model
    # uncertain breakouts, committee takeovers, and fragile roles.
    role_persistence: float = 0.18
    # "auto" uses skewed marginals for RB/WR/TE and normal marginals elsewhere.
    distribution: str = "auto"


@dataclass(frozen=True)
class FantasyTeam:
    team_id: int
    name: str
    roster: Tuple[int, ...]
    wins: float = 0.0
    losses: float = 0.0
    ties: float = 0.0
    points_for: float = 0.0
    faab_spent: int = 0
    waiver_rank: int = 0

    def with_transaction(self, add_player_id: int, drop_player_id: int) -> "FantasyTeam":
        if drop_player_id not in self.roster:
            raise ValueError("drop player is not on the roster")
        if add_player_id in self.roster:
            raise ValueError("add player is already on the roster")
        changed = tuple(add_player_id if pid == drop_player_id else pid for pid in self.roster)
        return replace(self, roster=changed)


@dataclass(frozen=True)
class ScoringRule:
    stat_id: int
    label: str
    points: float
    is_reverse: bool = False
    slot_points_overrides: Tuple[Tuple[int, float], ...] = ()


@dataclass(frozen=True)
class LeagueSettings:
    name: str
    current_week: int
    regular_season_weeks: int
    final_week: int
    playoff_team_count: int
    active_slot_ids: Tuple[int, ...]
    faab_enabled: bool = False
    faab_budget: int = 0
    minimum_bid: int = 0
    median_scoring: bool = False
    playoff_matchup_period_length: int = 1
    scoring_type: str = "H2H_POINTS"
    matchup_tiebreaker: str = ""
    playoff_matchup_tiebreaker: str = ""
    playoff_seeding_tiebreaker: str = ""
    acquisition_type: str = ""
    waiver_order_reset_rule: str = ""
    waiver_process_days: Tuple[str, ...] = ()
    acquisition_limit: int = 0
    acquisition_limit_per_week: int = 0
    trade_deadline_epoch_ms: int = 0
    roster_slot_counts: Mapping[int, int] = field(default_factory=dict)
    scoring_rules: Tuple[ScoringRule, ...] = ()


@dataclass(frozen=True)
class LeagueState:
    settings: LeagueSettings
    teams: Mapping[int, FantasyTeam]
    players: Mapping[int, Player]
    schedule: Mapping[int, Tuple[Tuple[int, int], ...]]
    forecasts: Mapping[Tuple[int, int], Forecast]
    free_agent_ids: Tuple[int, ...]
    observed_at: str = ""

    def with_team(self, team: FantasyTeam) -> "LeagueState":
        teams = dict(self.teams)
        teams[team.team_id] = team
        return replace(self, teams=teams)

    @property
    def weeks_remaining(self) -> Tuple[int, ...]:
        return tuple(range(self.settings.current_week, self.settings.final_week + 1))

    def forecast(self, player_id: int, week: int) -> Optional[Forecast]:
        return self.forecasts.get((player_id, week))


@dataclass(frozen=True)
class DistributionSummary:
    count: int
    mean: float
    stdev: float
    minimum: float
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    maximum: float
    cvar10: float
    cvar90: float


@dataclass(frozen=True)
class SimulationResult:
    team_id: int
    iterations: int
    playoff_probability: float
    title_probability: float
    current_week_win_probability: float
    expected_remaining_wins: float
    current_week_score: DistributionSummary
    current_week_margin: DistributionSummary
    short_horizon_points: DistributionSummary
    remaining_points: DistributionSummary
    regular_season_finish: DistributionSummary
    weekly_scores: Mapping[int, DistributionSummary]
    playoff_outcomes: Tuple[int, ...] = field(repr=False)
    title_outcomes: Tuple[int, ...] = field(repr=False)
    current_week_win_outcomes: Tuple[int, ...] = field(repr=False)
    remaining_wins_outcomes: Tuple[float, ...] = field(repr=False)
    current_week_score_outcomes: Tuple[float, ...] = field(repr=False)
    current_week_margin_outcomes: Tuple[float, ...] = field(repr=False)
    short_horizon_points_outcomes: Tuple[float, ...] = field(repr=False)
    remaining_points_outcomes: Tuple[float, ...] = field(repr=False)
    regular_season_finish_outcomes: Tuple[int, ...] = field(repr=False)
    weekly_score_outcomes: Mapping[int, Tuple[float, ...]] = field(repr=False)


@dataclass(frozen=True)
class MoveEvaluation:
    add_player_id: int
    drop_player_id: int
    playoff_delta: float
    title_delta: float
    current_week_win_delta: float
    playoff_delta_se: float
    title_delta_se: float
    mean_lineup_delta: float
    expected_wins_delta: float
    short_horizon_points_delta: float
    playoff_window_points_delta: float
    remaining_points_delta: float
    floor_delta: float
    upside_delta: float
    lower_tail_delta: float
    volatility_delta: float
    probability_points_improve: float
    probability_points_decline: float
    comparative_advantage: float
    max_rival_gain: float
    drop_externality: float
    positional_scarcity: float
    paired_points_delta: DistributionSummary
    paired_short_delta: DistributionSummary
    weekly_score_deltas: Mapping[int, DistributionSummary]
    candidate_weekly_scores: Mapping[int, DistributionSummary]
    paired_points_delta_outcomes: Tuple[float, ...] = field(repr=False)
    objective_scores: Mapping[str, float]
    objective_ranks: Mapping[str, int]
    objective_regret: Mapping[str, float]
    pareto_optimal: bool
    top_three_objectives: int
    bid_low: Optional[int]
    bid_high: Optional[int]
    bid_confidence: str = "LOW"


def active_slots(lineup_slot_counts: Mapping[str, int]) -> Tuple[int, ...]:
    slots: List[int] = []
    for raw_slot_id, raw_count in sorted(lineup_slot_counts.items(), key=lambda item: int(item[0])):
        slot_id = int(raw_slot_id)
        count = int(raw_count)
        if slot_id in BENCH_SLOT_IDS or count <= 0:
            continue
        slots.extend([slot_id] * count)
    return tuple(slots)


def population_stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5
