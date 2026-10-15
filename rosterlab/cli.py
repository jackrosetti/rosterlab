from __future__ import annotations

import argparse
import getpass
import os
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from .auth import (
    CredentialError,
    ESPNCredentials,
    credentials_from_environment,
    delete_credentials,
    normalize_swid,
    prompt_credentials_native,
    resolve_credentials,
    save_credentials,
)
from .demo import build_demo_state
from .espn import ESPNClient, ESPNConfig, ESPNError
from .ingest import build_league_state
from .models import BENCH_SLOT_IDS
from .optimizer import recommend_moves
from .objectives import OBJECTIVES, OBJECTIVE_BY_KEY
from .profile import DEFAULT_PROFILE, LocalProfile, load_profile, save_profile
from .report import write_html_report
from .snapshots import SnapshotStore
from .sync import detect_owned_team_id, sync_league, validate_league_payload


DEFAULT_DB = Path("data/rosterlab.sqlite3")


def _int_env(name: str) -> Optional[int]:
    value = os.environ.get(name)
    return int(value) if value else None


def _league_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--league-id", type=int)
    parser.add_argument("--season", type=int)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rosterlab",
        description="Local, probability-first ESPN fantasy football decisions.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser(
        "login", help="Verify ESPN access and save session cookies in macOS Keychain"
    )
    _league_args(login)
    login.add_argument("--from-env", action="store_true", help="Import ESPN_S2 and ESPN_SWID")
    login.add_argument("--public", action="store_true", help="Connect without private-league cookies")
    login.add_argument("--no-browser", action="store_true", help="Do not open the ESPN league page")
    login.add_argument(
        "--native-dialog",
        action="store_true",
        help="Collect cookies with hidden macOS dialogs instead of terminal prompts",
    )

    status = subparsers.add_parser("status", help="Show local ESPN connection and snapshot status")
    _league_args(status)
    status.add_argument("--verify", action="store_true", help="Make a live read-only ESPN request")

    logout = subparsers.add_parser("logout", help="Remove stored ESPN cookies from macOS Keychain")
    _league_args(logout)

    sync = subparsers.add_parser("sync", help="Snapshot the ESPN league and projection inputs")
    _league_args(sync)
    sync.add_argument("--from-week", type=int)
    sync.add_argument("--through-week", type=int)
    sync.add_argument("--skip-offers", action="store_true")

    teams = subparsers.add_parser("teams", help="List teams in the latest snapshot")
    _league_args(teams)

    league = subparsers.add_parser("league", help="Inspect synced rosters and league rules")
    _league_args(league)
    league.add_argument("--show-scoring", action="store_true")

    recommend = subparsers.add_parser("recommend", help="Run conditional waiver counterfactuals")
    _league_args(recommend)
    recommend.add_argument("--team-id", type=int)
    recommend.add_argument("--iterations", type=int, default=750)
    recommend.add_argument("--seed", type=int, default=20260921)
    recommend.add_argument("--top-free-agents", type=int, default=24)
    recommend.add_argument("--simulate-pairs", type=int, default=72)
    recommend.add_argument("--objective", choices=tuple(OBJECTIVE_BY_KEY), default="title")
    recommend.add_argument("--as-of")
    recommend.add_argument("--output", type=Path, default=Path("reports/waiver-board.html"))

    demo = subparsers.add_parser("demo", help="Generate a complete report from synthetic league data")
    demo.add_argument("--iterations", type=int, default=500)
    demo.add_argument("--seed", type=int, default=20260921)
    demo.add_argument("--scenario", choices=("contender", "bubble", "underdog"), default="bubble")
    demo.add_argument("--objective", choices=tuple(OBJECTIVE_BY_KEY), default="title")
    demo.add_argument("--simulate-pairs", type=int, default=48)
    demo.add_argument("--output", type=Path, default=Path("reports/demo-waiver-board.html"))

    lab = subparsers.add_parser(
        "lab", help="Run contender, bubble, and underdog synthetic sensitivity scenarios"
    )
    lab.add_argument("--iterations", type=int, default=400)
    lab.add_argument("--seed", type=int, default=20260921)
    lab.add_argument("--simulate-pairs", type=int, default=48)
    lab.add_argument("--output-dir", type=Path, default=Path("reports/model-lab"))

    subparsers.add_parser("objectives", help="List every optimization objective and its semantics")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "login":
            _login(args)
        elif args.command == "logout":
            _logout(args)
        elif args.command == "status":
            _status(args)
        elif args.command == "sync":
            _sync(args)
        elif args.command == "teams":
            _teams(args)
        elif args.command == "league":
            _league(args)
        elif args.command == "recommend":
            _recommend(args)
        elif args.command == "demo":
            _demo(args)
        elif args.command == "objectives":
            _objectives()
        elif args.command == "lab":
            _lab(args)
    except (ValueError, CredentialError, ESPNError) as exc:
        raise SystemExit(f"Error: {exc}") from exc


def _connection(args: argparse.Namespace) -> tuple[int, int, LocalProfile]:
    profile = load_profile(args.profile)
    league_id = args.league_id or _int_env("ESPN_LEAGUE_ID") or profile.league_id
    season = args.season or _int_env("ESPN_SEASON") or profile.season or datetime.now().year
    if league_id is None:
        raise ValueError("Run `rosterlab login --league-id …` or pass --league-id.")
    return int(league_id), int(season), profile


def _espn_client(args: argparse.Namespace) -> tuple[ESPNClient, str, LocalProfile]:
    league_id, season, profile = _connection(args)
    credentials, source = resolve_credentials(league_id=league_id, season=season)
    return (
        ESPNClient(
            ESPNConfig(
                league_id=league_id,
                season=season,
                espn_s2=credentials.espn_s2 if credentials else "",
                swid=credentials.swid if credentials else "",
            )
        ),
        source,
        profile,
    )


def _login(args: argparse.Namespace) -> None:
    league_id, season, profile = _connection(args)
    selected_methods = sum((bool(args.public), bool(args.from_env), bool(args.native_dialog)))
    if selected_methods > 1:
        raise ValueError("Choose only one of --public, --from-env, or --native-dialog.")

    credentials: Optional[ESPNCredentials] = None
    if not args.public:
        if args.from_env:
            credentials = credentials_from_environment()
            if credentials is None:
                raise CredentialError("ESPN_S2 and ESPN_SWID are not set in this shell.")
        elif args.native_dialog:
            credentials = prompt_credentials_native()
        else:
            if not args.no_browser:
                webbrowser.open(
                    f"https://fantasy.espn.com/football/league?leagueId={league_id}"
                    f"&seasonId={season}"
                )
            if not sys.stdin.isatty():
                raise CredentialError(
                    "Interactive login needs a terminal. Use `rosterlab login --from-env` instead."
                )
            print("Sign into ESPN in the browser. RosterLab never asks for your ESPN password.")
            print("From ESPN's espn.com cookies, copy espn_s2 and SWID into these hidden prompts.")
            espn_s2 = getpass.getpass("espn_s2: ").strip()
            swid = normalize_swid(getpass.getpass("SWID: "))
            credentials = ESPNCredentials(espn_s2=espn_s2, swid=swid)

    client = ESPNClient(
        ESPNConfig(
            league_id=league_id,
            season=season,
            espn_s2=credentials.espn_s2 if credentials else "",
            swid=credentials.swid if credentials else "",
        )
    )
    print("Verifying read-only ESPN access …", flush=True)
    league = client.fetch_league()
    validate_league_payload(league, league_id=league_id)
    team_id = detect_owned_team_id(league, credentials.swid) if credentials else None
    if credentials:
        save_credentials(credentials, league_id=league_id, season=season)
    settings = league.get("settings", {})
    saved = profile.with_updates(
        league_id=league_id,
        season=season,
        team_id=team_id or profile.team_id,
        league_name=str(settings.get("name", "ESPN League")),
    )
    profile_path = save_profile(saved, args.profile)
    print(f"Connected: {saved.league_name} ({season}), {len(league.get('teams', []))} teams")
    if team_id is not None:
        print(f"Your ESPN team ID: {team_id}")
    else:
        print("Your team could not be inferred; use `rosterlab teams` after the first sync.")
    print(f"Profile: {profile_path.resolve()}")
    print("Credentials: macOS Keychain" if credentials else "Credentials: none (public league)")


def _logout(args: argparse.Namespace) -> None:
    league_id, season, _profile = _connection(args)
    removed = delete_credentials(league_id=league_id, season=season)
    if removed:
        print(f"Removed ESPN credentials for league {league_id}, season {season} from Keychain.")
    else:
        print("No matching Keychain credentials were found. Environment variables were not changed.")


def _status(args: argparse.Namespace) -> None:
    league_id, season, profile = _connection(args)
    credentials, source = resolve_credentials(league_id=league_id, season=season)
    print(f"League: {profile.league_name or league_id} ({league_id})")
    print(f"Season: {season}")
    print(f"Team ID: {profile.team_id if profile.team_id is not None else 'not selected'}")
    print(f"Credentials: {source}")
    print(f"Last successful sync: {profile.last_sync_at or 'never'}")
    latest = SnapshotStore(args.db).latest(kind="league", league_id=league_id, season=season)
    print(f"Latest local snapshot: {latest.observed_at if latest else 'none'}")
    if args.verify:
        client = ESPNClient(
            ESPNConfig(
                league_id=league_id,
                season=season,
                espn_s2=credentials.espn_s2 if credentials else "",
                swid=credentials.swid if credentials else "",
            )
        )
        live = client.fetch_league()
        validate_league_payload(live, league_id=league_id)
        print(f"Live verification: OK — {live.get('settings', {}).get('name', 'ESPN League')}")


def _sync(args: argparse.Namespace) -> None:
    client, credential_source, profile = _espn_client(args)
    league_id = client.config.league_id
    season = client.config.season
    store = SnapshotStore(args.db)
    result = sync_league(
        client,
        store,
        from_week=args.from_week,
        through_week=args.through_week,
        include_offers=not args.skip_offers,
        progress=lambda message: print(message, flush=True),
    )
    updated = profile.with_updates(
        league_id=league_id,
        season=season,
        team_id=result.owned_team_id or profile.team_id,
        league_name=result.league_name,
        last_sync_at=result.observed_at,
    )
    save_profile(updated, args.profile)
    state = build_league_state(store, league_id=league_id, season=season)
    print(
        f"Synced {result.league_name}: {result.team_count} teams, "
        f"weeks {result.player_pool_weeks[0]}–{result.player_pool_weeks[-1]}, "
        f"{result.snapshot_count} immutable snapshots."
    )
    print(f"Rules: {_rule_summary(state)}")
    print(f"Credentials: {credential_source}; cookies were not written to the snapshot database.")
    print(f"Database: {args.db.resolve()}")
    print(f"Observed at: {result.observed_at}")


def _teams(args: argparse.Namespace) -> None:
    league_id, season, profile = _connection(args)
    state = build_league_state(
        SnapshotStore(args.db), league_id=league_id, season=season
    )
    print(f"{state.settings.name} — week {state.settings.current_week}")
    for team_id, team in sorted(state.teams.items()):
        marker = "*" if profile.team_id == team_id else " "
        print(
            f"{marker}{team_id:>3}  {team.name:<30} {team.wins:g}-{team.losses:g}-{team.ties:g}  "
            f"PF {team.points_for:.1f}"
        )


def _league(args: argparse.Namespace) -> None:
    league_id, season, _profile = _connection(args)
    state = build_league_state(SnapshotStore(args.db), league_id=league_id, season=season)
    settings = state.settings
    print(f"{settings.name} — ESPN league {league_id}, {season}")
    print(f"Snapshot: {state.observed_at}")
    print(f"Teams: {len(state.teams)} | current week: {settings.current_week}")
    print(f"Roster: {_roster_summary(settings.roster_slot_counts)}")
    print(
        f"Season: {settings.regular_season_weeks} regular-season weeks; "
        f"{settings.playoff_team_count} playoff teams; final week {settings.final_week}; "
        f"{settings.playoff_matchup_period_length}-week playoff matchups"
    )
    print(
        f"Acquisitions: {settings.acquisition_type or 'unspecified'}; "
        f"FAAB {'$' + str(settings.faab_budget) if settings.faab_enabled else 'off'}; "
        f"minimum bid ${settings.minimum_bid}; waiver reset "
        f"{settings.waiver_order_reset_rule or 'unspecified'}"
    )
    if settings.waiver_process_days:
        print(
            "Waiver processing days: "
            + ", ".join(day.title() for day in settings.waiver_process_days)
        )
    print(
        f"Scoring: {settings.scoring_type}; {len(settings.scoring_rules)} scoring rules; "
        f"median matchup {'on' if settings.median_scoring else 'off'}"
    )
    print(
        f"Tiebreakers: matchup {settings.matchup_tiebreaker or 'unspecified'}; "
        f"playoff {settings.playoff_matchup_tiebreaker or 'unspecified'}; "
        f"seeding {settings.playoff_seeding_tiebreaker or 'unspecified'}"
    )
    if args.show_scoring:
        if not settings.scoring_rules:
            print("No scoring items were present in the ESPN mSettings payload.")
        for rule in settings.scoring_rules:
            suffix = " (reverse)" if rule.is_reverse else ""
            overrides = (
                " | slot overrides "
                + ", ".join(
                    f"{SLOT_LABELS.get(slot_id, f'slot {slot_id}')}:{points:+g}"
                    for slot_id, points in rule.slot_points_overrides
                )
                if rule.slot_points_overrides
                else ""
            )
            print(f"  {rule.stat_id:>3}  {rule.label:<42} {rule.points:+g}{suffix}{overrides}")
    print("\nRosters:")
    for team_id, team in sorted(state.teams.items()):
        names = [
            state.players[player_id].name
            for player_id in team.roster
            if player_id in state.players
        ]
        print(f"  {team_id:>3}  {team.name:<30} {len(names):>2} players")
        print(f"       {', '.join(names)}")


def _recommend(args: argparse.Namespace) -> None:
    league_id, season, profile = _connection(args)
    team_id = args.team_id or _int_env("ROSTERLAB_TEAM_ID") or profile.team_id
    if team_id is None:
        raise ValueError("Pass --team-id or run `rosterlab login`; use `rosterlab teams` to find it.")
    state = build_league_state(
        SnapshotStore(args.db),
        league_id=league_id,
        season=season,
        as_of=args.as_of,
    )
    if team_id not in state.teams:
        raise ValueError(f"Team ID {team_id} is not present in the latest league snapshot.")
    print(
        f"Simulating {args.iterations:,} paired seasons for {state.teams[team_id].name} …",
        flush=True,
    )
    recommendations = recommend_moves(
        state,
        team_id=team_id,
        iterations=args.iterations,
        seed=args.seed,
        top_free_agents=args.top_free_agents,
        simulate_pairs=args.simulate_pairs,
        primary_objective=args.objective,
    )
    report_path = write_html_report(args.output, state, team_id, recommendations)
    _print_summary(state, recommendations)
    print(f"Report: {report_path}")


def _demo(args: argparse.Namespace) -> None:
    state = build_demo_state(scenario=args.scenario)
    print(f"Simulating {args.iterations:,} paired demo seasons …", flush=True)
    recommendations = recommend_moves(
        state,
        team_id=1,
        iterations=args.iterations,
        seed=args.seed,
        top_free_agents=12,
        simulate_pairs=args.simulate_pairs,
        primary_objective=args.objective,
    )
    report_path = write_html_report(args.output, state, 1, recommendations)
    _print_summary(state, recommendations)
    print(f"Report: {report_path}")


def _lab(args: argparse.Namespace) -> None:
    for scenario in ("contender", "bubble", "underdog"):
        state = build_demo_state(scenario=scenario)
        print(f"\n{scenario.upper()}: simulating {args.iterations:,} paired worlds …", flush=True)
        recommendations = recommend_moves(
            state,
            team_id=1,
            iterations=args.iterations,
            seed=args.seed,
            top_free_agents=12,
            simulate_pairs=args.simulate_pairs,
            primary_objective="title",
        )
        report_path = write_html_report(
            args.output_dir / f"{scenario}.html", state, 1, recommendations
        )
        _print_objective_leaders(state, recommendations)
        print(f"Report: {report_path}")


def _print_summary(state, recommendations) -> None:
    baseline = recommendations.baseline
    print(
        f"Baseline: playoffs {baseline.playoff_probability * 100:.1f}% | "
        f"title {baseline.title_probability * 100:.1f}% | "
        f"this week {baseline.current_week_win_probability * 100:.1f}% | "
        f"weekly score {baseline.current_week_score.p10:.1f}/"
        f"{baseline.current_week_score.p50:.1f}/{baseline.current_week_score.p90:.1f} p10/p50/p90"
    )
    objective = OBJECTIVE_BY_KEY[recommendations.primary_objective]
    print(f"Top conditional moves — optimized for {objective.label}:")
    for rank, move in enumerate(recommendations.moves[:5], start=1):
        add_name = state.players[move.add_player_id].name
        drop_name = state.players[move.drop_player_id].name
        bid = (
            f"${move.bid_low}–${move.bid_high} (low confidence)"
            if move.bid_low is not None
            else "priority claim"
        )
        print(
            f"  {rank}. Add {add_name}; drop {drop_name} — "
            f"{_format_objective(move.objective_scores[objective.key], objective.unit)}, "
            f"Δ title {move.title_delta * 100:+.1f} pp, "
            f"Pareto {'yes' if move.pareto_optimal else 'no'}, {bid}"
        )


def _objectives() -> None:
    for objective in OBJECTIVES:
        print(f"{objective.key:<24} {objective.label:<24} {objective.horizon:<18} {objective.description}")


def _print_objective_leaders(state, recommendations) -> None:
    baseline = recommendations.baseline
    print(
        f"Baseline: playoffs {baseline.playoff_probability * 100:.1f}% | "
        f"title {baseline.title_probability * 100:.1f}%"
    )
    for objective in OBJECTIVES:
        leader = min(
            recommendations.moves,
            key=lambda move: move.objective_ranks[objective.key],
        )
        print(
            f"  {objective.key:<22} {state.players[leader.add_player_id].name:<24} "
            f"for {state.players[leader.drop_player_id].name:<12} "
            f"{_format_objective(leader.objective_scores[objective.key], objective.unit)}"
        )


def _format_objective(value: float, unit: str) -> str:
    if unit == "probability":
        return f"{value * 100:+.1f} pp"
    if unit == "wins":
        return f"{value:+.2f} wins"
    return f"{value:+.1f} pts"


SLOT_LABELS = {
    0: "QB",
    2: "RB",
    4: "WR",
    6: "TE",
    7: "OP",
    16: "D/ST",
    17: "K",
    20: "BE",
    21: "IR",
    23: "FLEX",
    24: "ER",
}


def _roster_summary(slot_counts) -> str:
    pieces = []
    for slot_id, count in sorted(slot_counts.items()):
        if int(count) <= 0:
            continue
        pieces.append(f"{int(count)} {SLOT_LABELS.get(int(slot_id), f'slot {slot_id}')}")
    return ", ".join(pieces) if pieces else "no roster slots imported"


def _rule_summary(state) -> str:
    settings = state.settings
    active_count = sum(
        count
        for slot_id, count in settings.roster_slot_counts.items()
        if slot_id not in BENCH_SLOT_IDS
    )
    bench_count = sum(
        count
        for slot_id, count in settings.roster_slot_counts.items()
        if slot_id in BENCH_SLOT_IDS
    )
    if settings.faab_enabled:
        acquisition = f"FAAB ${settings.faab_budget}"
    elif settings.acquisition_type == "WAIVERS_TRADITIONAL":
        acquisition = "traditional waivers"
    elif settings.acquisition_type:
        acquisition = settings.acquisition_type.lower().replace("_", " ")
    else:
        acquisition = "non-FAAB waivers"
    return (
        f"{active_count} starters + {bench_count} reserve slots, {settings.playoff_team_count}-team "
        f"playoffs, {acquisition}, {len(settings.scoring_rules)} scoring items"
    )
