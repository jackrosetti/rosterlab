from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

from .models import (
    FantasyTeam,
    Forecast,
    LeagueSettings,
    LeagueState,
    Player,
    ScoringRule,
    active_slots,
    population_stdev,
)
from .snapshots import Snapshot, SnapshotStore


SLOT_POSITION = {
    0: "QB",
    2: "RB",
    4: "WR",
    6: "TE",
    16: "D/ST",
    17: "K",
}
DEFAULT_POSITION = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
POSITION_STDEV_PRIOR = {
    "QB": (5.5, 0.28),
    "RB": (4.5, 0.45),
    "WR": (4.5, 0.52),
    "TE": (3.5, 0.52),
    "K": (4.0, 0.20),
    "D/ST": (4.8, 0.20),
}
POSITION_MEAN_FALLBACK = {"QB": 14.0, "RB": 6.5, "WR": 6.5, "TE": 5.0, "K": 6.0, "D/ST": 6.0}
SCORING_STAT_LABELS = {
    3: "Passing yards",
    4: "Passing touchdowns",
    15: "40+ yard passing touchdown",
    16: "50+ yard passing touchdown",
    17: "300–399 passing-yard game",
    18: "400+ passing-yard game",
    19: "Passing two-point conversions",
    20: "Passing interceptions",
    23: "Rushing attempts",
    24: "Rushing yards",
    25: "Rushing touchdowns",
    26: "Rushing two-point conversions",
    35: "40+ yard rushing touchdown",
    36: "50+ yard rushing touchdown",
    37: "100–199 rushing-yard game",
    38: "200+ rushing-yard game",
    41: "Receptions",
    42: "Receiving yards",
    43: "Receiving touchdowns",
    44: "Receiving two-point conversions",
    45: "40+ yard receiving touchdown",
    46: "50+ yard receiving touchdown",
    53: "Receptions",
    56: "100–199 receiving-yard game",
    57: "200+ receiving-yard game",
    58: "Receiving targets",
    68: "Fumbles",
    72: "Fumbles lost",
    74: "Field goals made from 50+ yards",
    77: "Field goals made from 40–49 yards",
    80: "Field goals made under 40 yards",
    83: "Field goals made",
    85: "Field goals missed",
    86: "Extra points made",
    88: "Extra points missed",
    94: "Defensive touchdowns",
    95: "Defensive interceptions",
    96: "Defensive fumble recoveries",
    97: "Defensive blocked kicks",
    98: "Defensive safeties",
    99: "Defensive sacks",
    105: "Defense/special-teams touchdowns",
}


def _unwrap_player(container: Mapping[str, Any]) -> Tuple[Mapping[str, Any], Mapping[str, Any]]:
    pool = container.get("playerPoolEntry")
    if isinstance(pool, dict):
        inner = pool.get("player", {})
        return pool, inner if isinstance(inner, dict) else {}
    inner = container.get("player")
    if isinstance(inner, dict):
        return container, inner
    return container, container


def _position(inner: Mapping[str, Any], eligible: Sequence[int]) -> str:
    for slot_id in eligible:
        if slot_id in SLOT_POSITION:
            return SLOT_POSITION[slot_id]
    return DEFAULT_POSITION.get(int(inner.get("defaultPositionId", 0) or 0), "UNK")


def parse_player(container: Mapping[str, Any]) -> Optional[Player]:
    pool, inner = _unwrap_player(container)
    player_id = inner.get("id", pool.get("id", container.get("id")))
    if not isinstance(player_id, int) or player_id == 0:
        return None
    eligible = inner.get("eligibleSlots", container.get("eligibleSlots", []))
    eligible_ids = tuple(int(slot_id) for slot_id in eligible if isinstance(slot_id, (int, str)))
    return Player(
        player_id=player_id,
        name=str(inner.get("fullName", inner.get("name", f"Player {player_id}"))),
        position=_position(inner, eligible_ids),
        pro_team_id=int(inner.get("proTeamId", 0) or 0),
        eligible_slot_ids=eligible_ids,
        injury_status=str(inner.get("injuryStatus", "ACTIVE") or "ACTIVE"),
    )


def _stats(inner: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    stats = inner.get("stats", [])
    return stats if isinstance(stats, list) else []


def _projection_for_week(inner: Mapping[str, Any], season: int, week: int) -> Optional[float]:
    candidates = []
    for item in _stats(inner):
        if int(item.get("seasonId", season) or season) != season:
            continue
        if int(item.get("scoringPeriodId", -1) or -1) != week:
            continue
        if int(item.get("statSourceId", 0) or 0) != 1:
            continue
        candidates.append(float(item.get("appliedTotal", 0.0) or 0.0))
    return candidates[-1] if candidates else None


def _season_projection(inner: Mapping[str, Any], season: int) -> Optional[float]:
    candidates = []
    for item in _stats(inner):
        if int(item.get("seasonId", season) or season) != season:
            continue
        if int(item.get("scoringPeriodId", -1)) != 0:
            continue
        if int(item.get("statSourceId", 0) or 0) != 1:
            continue
        candidates.append(float(item.get("appliedTotal", 0.0) or 0.0))
    return candidates[-1] if candidates else None


def _actual_history(inner: Mapping[str, Any], season: int, before_week: int) -> Dict[int, float]:
    history: Dict[int, float] = {}
    for item in _stats(inner):
        if int(item.get("seasonId", season) or season) != season:
            continue
        week = int(item.get("scoringPeriodId", 0) or 0)
        if week <= 0 or week >= before_week or int(item.get("statSourceId", 0) or 0) != 0:
            continue
        history[week] = float(item.get("appliedTotal", 0.0) or 0.0)
    return history


def _schedule_map(raw: Mapping[str, Any]) -> Dict[Tuple[int, int], int]:
    result: Dict[Tuple[int, int], int] = {}
    pro_teams = raw.get("settings", {}).get("proTeams", [])
    for team in pro_teams if isinstance(pro_teams, list) else []:
        team_id = int(team.get("id", 0) or 0)
        games = team.get("proGamesByScoringPeriod", {})
        for raw_week, week_games in games.items():
            if not week_games:
                continue
            game = week_games[0]
            home = int(game.get("homeProTeamId", 0) or 0)
            away = int(game.get("awayProTeamId", 0) or 0)
            opponent = away if team_id == home else home
            result[(team_id, int(raw_week))] = opponent
    return result


def _bye_weeks(raw: Mapping[str, Any]) -> Set[Tuple[int, int]]:
    result: Set[Tuple[int, int]] = set()
    pro_teams = raw.get("settings", {}).get("proTeams", [])
    for team in pro_teams if isinstance(pro_teams, list) else []:
        team_id = int(team.get("id", 0) or 0)
        games = team.get("proGamesByScoringPeriod", {})
        for raw_week, week_games in games.items():
            if not week_games:
                result.add((team_id, int(raw_week)))
    return result


def _matchup_weeks(settings: Mapping[str, Any], matchup_period: int) -> Tuple[int, ...]:
    periods = settings.get("scheduleSettings", {}).get("matchupPeriods", {})
    raw = periods.get(str(matchup_period), periods.get(matchup_period)) if isinstance(periods, dict) else None
    if isinstance(raw, list) and raw:
        return tuple(int(week) for week in raw)
    return (matchup_period,)


def _scoring_rules(scoring: Mapping[str, Any]) -> Tuple[ScoringRule, ...]:
    rules: List[ScoringRule] = []
    raw_items = scoring.get("scoringItems", [])
    for item in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(item, Mapping) or item.get("statId") is None:
            continue
        stat_id = int(item["statId"])
        overrides = item.get("pointsOverrides", {})
        parsed_overrides: List[Tuple[int, float]] = []
        if isinstance(overrides, Mapping):
            for slot_id, points in overrides.items():
                try:
                    parsed_overrides.append((int(slot_id), float(points)))
                except (TypeError, ValueError):
                    continue
        label = str(
            item.get("label")
            or item.get("abbr")
            or SCORING_STAT_LABELS.get(stat_id, f"ESPN stat {stat_id}")
        )
        rules.append(
            ScoringRule(
                stat_id=stat_id,
                label=label,
                points=float(item.get("points", 0.0) or 0.0),
                is_reverse=bool(item.get("isReverseItem", False)),
                slot_points_overrides=tuple(sorted(parsed_overrides)),
            )
        )
    return tuple(sorted(rules, key=lambda rule: rule.stat_id))


def build_league_state(
    store: SnapshotStore,
    *,
    league_id: int,
    season: int,
    as_of: Optional[str] = None,
) -> LeagueState:
    league_snapshot = store.latest(kind="league", league_id=league_id, season=season, as_of=as_of)
    if league_snapshot is None:
        raise ValueError("No league snapshot found. Run the sync command first.")
    league_raw = league_snapshot.payload
    settings_raw = league_raw.get("settings", {})
    status_raw = league_raw.get("status", {})
    current_week = int(league_raw.get("scoringPeriodId", status_raw.get("currentMatchupPeriod", 1)) or 1)
    schedule_settings = settings_raw.get("scheduleSettings", {})
    regular_weeks = int(schedule_settings.get("matchupPeriodCount", 14) or 14)
    final_week = int(status_raw.get("finalScoringPeriod", regular_weeks + 3) or (regular_weeks + 3))
    playoff_length = int(schedule_settings.get("playoffMatchupPeriodLength", 1) or 1)
    lineup_counts = settings_raw.get("rosterSettings", {}).get("lineupSlotCounts", {})
    acquisition = settings_raw.get("acquisitionSettings", {})
    scoring = settings_raw.get("scoringSettings", {})
    raw_waiver_days = acquisition.get("waiverProcessDays", []) or []
    if isinstance(raw_waiver_days, (list, tuple)):
        waiver_process_days = tuple(str(day) for day in raw_waiver_days)
    else:
        waiver_process_days = (str(raw_waiver_days),)
    roster_slot_counts = {
        int(slot_id): int(count)
        for slot_id, count in lineup_counts.items()
        if int(count) > 0
    }
    league_settings = LeagueSettings(
        name=str(settings_raw.get("name", "ESPN League")),
        current_week=current_week,
        regular_season_weeks=regular_weeks,
        final_week=final_week,
        playoff_team_count=int(schedule_settings.get("playoffTeamCount", 4) or 4),
        active_slot_ids=active_slots(lineup_counts),
        faab_enabled=bool(acquisition.get("isUsingAcquisitionBudget", False)),
        faab_budget=int(acquisition.get("acquisitionBudget", 0) or 0),
        minimum_bid=int(acquisition.get("minimumBid", 0) or 0),
        median_scoring=scoring.get("scoringEnhancementType") == "WIN_BONUS_TOP_HALF",
        playoff_matchup_period_length=playoff_length,
        scoring_type=str(scoring.get("scoringType", "H2H_POINTS") or "H2H_POINTS"),
        matchup_tiebreaker=str(schedule_settings.get("matchupTieRule", "") or ""),
        playoff_matchup_tiebreaker=str(
            schedule_settings.get("playoffMatchupTieRule", "") or ""
        ),
        playoff_seeding_tiebreaker=str(
            schedule_settings.get("playoffSeedingRule", "") or ""
        ),
        acquisition_type=str(acquisition.get("acquisitionType", "") or ""),
        waiver_order_reset_rule=str(acquisition.get("waiverOrderResetRule", "") or ""),
        waiver_process_days=waiver_process_days,
        acquisition_limit=int(acquisition.get("acquisitionLimit", 0) or 0),
        acquisition_limit_per_week=int(acquisition.get("acquisitionLimitPerWeek", 0) or 0),
        trade_deadline_epoch_ms=int(settings_raw.get("tradeSettings", {}).get("deadlineDate", 0) or 0),
        roster_slot_counts=roster_slot_counts,
        scoring_rules=_scoring_rules(scoring),
    )

    players: Dict[int, Player] = {}
    teams: Dict[int, FantasyTeam] = {}
    for raw_team in league_raw.get("teams", []):
        roster_ids: List[int] = []
        entries = raw_team.get("roster", {}).get("entries", [])
        for entry in entries:
            player = parse_player(entry)
            if player is not None:
                players[player.player_id] = player
                roster_ids.append(player.player_id)
        record = raw_team.get("record", {}).get("overall", {})
        transaction_counter = raw_team.get("transactionCounter", {})
        team_id = int(raw_team["id"])
        name = raw_team.get("name")
        if not name:
            name = " ".join(
                piece for piece in (raw_team.get("location"), raw_team.get("nickname")) if piece
            )
        teams[team_id] = FantasyTeam(
            team_id=team_id,
            name=str(name or raw_team.get("abbrev", f"Team {team_id}")),
            roster=tuple(roster_ids),
            wins=float(record.get("wins", 0) or 0),
            losses=float(record.get("losses", 0) or 0),
            ties=float(record.get("ties", 0) or 0),
            points_for=float(record.get("pointsFor", 0.0) or 0.0),
            faab_spent=int(transaction_counter.get("acquisitionBudgetSpent", 0) or 0),
            waiver_rank=int(raw_team.get("waiverRank", 0) or 0),
        )

    fantasy_schedule: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
    for matchup in league_raw.get("schedule", []):
        period = int(matchup.get("matchupPeriodId", 0) or 0)
        home = int(matchup.get("home", {}).get("teamId", 0) or 0)
        away = int(matchup.get("away", {}).get("teamId", 0) or 0)
        if home <= 0 or away <= 0:
            continue
        for week in _matchup_weeks(settings_raw, period):
            if (home, away) not in fantasy_schedule[week] and (away, home) not in fantasy_schedule[week]:
                fantasy_schedule[week].append((home, away))

    pro_snapshot = store.latest(kind="pro_schedule", league_id=league_id, season=season, as_of=as_of)
    pro_schedule = _schedule_map(pro_snapshot.payload) if pro_snapshot else {}
    bye_weeks = _bye_weeks(pro_snapshot.payload) if pro_snapshot else set()

    wraps_by_week: Dict[int, List[Mapping[str, Any]]] = {}
    histories: Dict[int, Dict[int, float]] = defaultdict(dict)
    status_by_player: Dict[int, Tuple[str, int]] = {}
    for week in store.periods(kind="player_pool", league_id=league_id, season=season):
        if week < current_week or week > final_week:
            continue
        snapshot = store.latest(
            kind="player_pool", league_id=league_id, season=season, scoring_period=week, as_of=as_of
        )
        if snapshot is None:
            continue
        wraps = snapshot.payload.get("players", [])
        wraps_by_week[week] = wraps
        for wrap in wraps:
            pool, inner = _unwrap_player(wrap)
            player = parse_player(wrap)
            if player is None:
                continue
            players[player.player_id] = player
            histories[player.player_id].update(_actual_history(inner, season, current_week))
            if week == current_week:
                status = str(pool.get("status", wrap.get("status", "")) or "")
                on_team_id = int(pool.get("onTeamId", wrap.get("onTeamId", 0)) or 0)
                status_by_player[player.player_id] = (status, on_team_id)

    forecasts: Dict[Tuple[int, int], Forecast] = {}
    for week in range(current_week, final_week + 1):
        seen: Set[int] = set()
        for wrap in wraps_by_week.get(week, []):
            _, inner = _unwrap_player(wrap)
            player = parse_player(wrap)
            if player is None:
                continue
            seen.add(player.player_id)
            projection = _projection_for_week(inner, season, week)
            season_projection = _season_projection(inner, season)
            history_values = list(histories.get(player.player_id, {}).values())
            source = "espn"
            if (player.pro_team_id, week) in bye_weeks:
                projection = 0.0
                source = "bye"
            elif projection is None:
                if season_projection is not None:
                    projection = season_projection / max(1, final_week)
                    source = "espn-season-rate"
                elif history_values:
                    projection = sum(history_values[-4:]) / min(4, len(history_values))
                    source = "historical-fallback"
                else:
                    projection = POSITION_MEAN_FALLBACK.get(player.position, 3.0)
                    source = "position-fallback"
            prior_base, prior_slope = POSITION_STDEV_PRIOR.get(player.position, (4.0, 0.45))
            prior_stdev = prior_base + prior_slope * max(0.0, projection)
            observed_stdev = population_stdev(history_values[-6:])
            weight = len(history_values) / (len(history_values) + 4.0)
            stdev = max(1.0, weight * observed_stdev + (1.0 - weight) * prior_stdev)
            forecasts[(player.player_id, week)] = Forecast(
                player=player,
                week=week,
                mean=max(0.0, float(projection)),
                stdev=stdev,
                opponent_team_id=pro_schedule.get((player.pro_team_id, week), 0),
                source=source,
            )

        # If a future ESPN snapshot is missing a rostered player, carry the most
        # recent expectation forward. This is marked explicitly as a fallback.
        for player_id, player in players.items():
            if player_id in seen or (player_id, week) in forecasts:
                continue
            previous = next(
                (forecasts[(player_id, prior)] for prior in range(week - 1, current_week - 1, -1) if (player_id, prior) in forecasts),
                None,
            )
            mean = previous.mean if previous else POSITION_MEAN_FALLBACK.get(player.position, 3.0)
            stdev = previous.stdev if previous else POSITION_STDEV_PRIOR.get(player.position, (4.0, 0.45))[0]
            source = "carry-forward-fallback"
            if (player.pro_team_id, week) in bye_weeks:
                mean = 0.0
                source = "bye"
            forecasts[(player_id, week)] = Forecast(
                player=player,
                week=week,
                mean=mean,
                stdev=stdev,
                opponent_team_id=pro_schedule.get((player.pro_team_id, week), 0),
                source=source,
            )

    rostered = {player_id for team in teams.values() for player_id in team.roster}
    free_agents = []
    for player_id, (status, on_team_id) in status_by_player.items():
        if player_id in rostered:
            continue
        if status in {"FREEAGENT", "WAIVERS"} or on_team_id == 0:
            free_agents.append(player_id)

    return LeagueState(
        settings=league_settings,
        teams=teams,
        players=players,
        schedule={week: tuple(pairs) for week, pairs in fantasy_schedule.items()},
        forecasts=forecasts,
        free_agent_ids=tuple(free_agents),
        observed_at=league_snapshot.observed_at,
    )
