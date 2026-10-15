from __future__ import annotations

import math
import random
from typing import Dict, List, Tuple

from .models import FantasyTeam, Forecast, LeagueSettings, LeagueState, Player


POSITION_SLOTS = {
    "QB": (0, 7),
    "RB": (2, 7, 23),
    "WR": (4, 7, 23),
    "TE": (6, 7, 23),
    "D/ST": (16,),
    "K": (17,),
}


def build_demo_state(seed: int = 41, scenario: str = "bubble") -> LeagueState:
    if scenario not in {"contender", "bubble", "underdog"}:
        raise ValueError("scenario must be contender, bubble, or underdog")
    rng = random.Random(seed)
    settings = LeagueSettings(
        name=f"Insight Fantasy Football — {scenario.title()} model lab",
        current_week=6,
        regular_season_weeks=14,
        final_week=17,
        playoff_team_count=4,
        active_slot_ids=(0, 2, 2, 4, 4, 6, 23, 16, 17),
        faab_enabled=True,
        faab_budget=100,
        minimum_bid=0,
    )
    players: Dict[int, Player] = {}
    teams: Dict[int, FantasyTeam] = {}
    forecasts: Dict[Tuple[int, int], Forecast] = {}
    player_id = 1000
    roster_shape = ("QB", "QB", "RB", "RB", "RB", "RB", "WR", "WR", "WR", "WR", "WR", "TE", "TE", "K", "D/ST")

    def add_player(name: str, position: str, pro_team: int) -> Player:
        nonlocal player_id
        player_id += 1
        player = Player(
            player_id=player_id,
            name=name,
            position=position,
            pro_team_id=pro_team,
            eligible_slot_ids=POSITION_SLOTS[position],
        )
        players[player.player_id] = player
        return player

    base_by_position = {"QB": 17.0, "RB": 10.0, "WR": 10.0, "TE": 7.0, "K": 7.0, "D/ST": 7.0}
    stdev_by_position = {"QB": 7.0, "RB": 8.0, "WR": 8.5, "TE": 6.0, "K": 4.5, "D/ST": 5.0}
    for team_id in range(1, 9):
        roster: List[int] = []
        for roster_index, position in enumerate(roster_shape):
            player = add_player(
                f"{position} {team_id}-{roster_index + 1}", position, 1 + ((team_id * 3 + roster_index) % 16)
            )
            roster.append(player.player_id)
            depth_penalty = {"QB": roster_index % 2, "RB": max(0, roster_index - 3), "WR": max(0, roster_index - 7), "TE": roster_index % 2}.get(position, 0)
            talent = base_by_position[position] + rng.uniform(-2.0, 3.0) - depth_penalty * 1.5
            for week in range(settings.current_week, settings.final_week + 1):
                opponent = 1 + ((player.pro_team_id + week * 3) % 16)
                forecasts[(player.player_id, week)] = Forecast(
                    player=player,
                    week=week,
                    mean=max(0.0, talent + 0.8 * math.sin(week + player.player_id)),
                    stdev=stdev_by_position[position],
                    opponent_team_id=opponent,
                    source="demo-market",
                )
        games_played = settings.current_week - 1
        target_wins = {"contender": 5, "bubble": 3, "underdog": 1}[scenario]
        team_wins = target_wins if team_id == 1 else rng.randint(1, games_played)
        teams[team_id] = FantasyTeam(
            team_id=team_id,
            name="Insight" if team_id == 1 else f"Opponent {team_id}",
            roster=tuple(roster),
            wins=float(team_wins),
            losses=float(games_played - team_wins),
            points_for=(
                {"contender": 615.0, "bubble": 545.0, "underdog": 470.0}[scenario]
                if team_id == 1
                else rng.uniform(475.0, 620.0)
            ),
            faab_spent=8 if team_id == 1 else rng.randint(0, 20),
            waiver_rank=team_id,
        )
    free_agents: List[int] = []
    names = [
        # name, position, base mean, weekly stdev, persistent role uncertainty
        ("Breakout Back", "RB", 9.5, 9.5, 0.62),
        ("Safe Slot Receiver", "WR", 10.8, 4.0, 0.08),
        ("Win-Now Workhorse", "RB", 8.0, 7.0, 0.18),
        ("Playoff Hammer", "WR", 7.5, 8.0, 0.28),
        ("Boom/Bust Burner", "WR", 11.0, 13.0, 0.38),
        ("Streaming Tight End", "TE", 8.5, 6.0, 0.22),
        ("Mobile Quarterback", "QB", 18.5, 8.0, 0.20),
        ("Goal Line Back", "RB", 8.8, 10.0, 0.30),
        ("Sunday Streamer", "D/ST", 8.0, 5.0, 0.08),
        ("Reliable Kicker", "K", 8.0, 3.5, 0.05),
    ]
    for index, (name, position, base, weekly_stdev, role_persistence) in enumerate(names):
        player = add_player(name, position, 1 + ((index * 2 + 5) % 16))
        free_agents.append(player.player_id)
        for week in range(settings.current_week, settings.final_week + 1):
            role_change = 4.0 if name == "Breakout Back" and week >= 7 else 0.0
            win_now = 7.0 if name == "Win-Now Workhorse" and week <= 8 else 0.0
            playoff_boost = 8.5 if name == "Playoff Hammer" and week > settings.regular_season_weeks else 0.0
            forecasts[(player.player_id, week)] = Forecast(
                player=player,
                week=week,
                mean=base + role_change + win_now + playoff_boost + rng.uniform(-0.7, 0.7),
                stdev=weekly_stdev,
                opponent_team_id=1 + ((player.pro_team_id + week * 3) % 16),
                source="demo-market",
                role_persistence=role_persistence,
            )

    schedule: Dict[int, Tuple[Tuple[int, int], ...]] = {}
    team_ids = list(teams)
    for week in range(settings.current_week, settings.regular_season_weeks + 1):
        rotation = (week - 1) % (len(team_ids) - 1)
        rest = team_ids[1:]
        rotated = rest[rotation:] + rest[:rotation]
        arranged = [team_ids[0]] + rotated
        schedule[week] = tuple(
            (arranged[index], arranged[-1 - index]) for index in range(len(arranged) // 2)
        )

    return LeagueState(
        settings=settings,
        teams=teams,
        players=players,
        schedule=schedule,
        forecasts=forecasts,
        free_agent_ids=tuple(free_agents),
        observed_at="2026-10-14T12:00:00+00:00",
    )
