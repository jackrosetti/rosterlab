from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from .espn import ESPNClient, ESPNError
from .snapshots import SnapshotStore


ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class LeagueSyncResult:
    observed_at: str
    league_name: str
    current_week: int
    final_week: int
    team_count: int
    player_pool_weeks: Tuple[int, ...]
    waiver_weeks: Tuple[int, ...]
    owned_team_id: Optional[int]
    snapshot_count: int


def validate_league_payload(payload: Mapping[str, Any], *, league_id: int) -> None:
    if not isinstance(payload.get("settings"), Mapping):
        raise ESPNError("ESPN league response is missing settings (mSettings).")
    if not isinstance(payload.get("teams"), list) or not payload.get("teams"):
        raise ESPNError("ESPN league response is missing teams and rosters (mTeam/mRoster).")
    response_id = payload.get("id")
    if response_id is not None and int(response_id) != int(league_id):
        raise ESPNError(f"ESPN returned league {response_id}, expected {league_id}.")


def detect_owned_team_id(payload: Mapping[str, Any], swid: str) -> Optional[int]:
    owner = _canonical_owner_id(swid)
    if not owner:
        return None
    for team in payload.get("teams", []):
        if not isinstance(team, Mapping):
            continue
        owner_ids = [team.get("primaryOwner")]
        owners = team.get("owners", [])
        if isinstance(owners, list):
            owner_ids.extend(owners)
        if any(_canonical_owner_id(raw) == owner for raw in owner_ids):
            team_id = team.get("id")
            return int(team_id) if team_id is not None else None
    return None


def sync_league(
    client: ESPNClient,
    store: SnapshotStore,
    *,
    from_week: Optional[int] = None,
    through_week: Optional[int] = None,
    include_offers: bool = True,
    observed_at: Optional[str] = None,
    progress: Optional[ProgressCallback] = None,
) -> LeagueSyncResult:
    progress = progress or (lambda _message: None)
    observed_at = observed_at or datetime.now(timezone.utc).isoformat()
    league_id = client.config.league_id
    season = client.config.season

    progress("Fetching league settings, rosters, schedule, and standings …")
    league = client.fetch_league()
    validate_league_payload(league, league_id=league_id)
    progress("Fetching the NFL schedule …")
    pro_schedule = client.fetch_pro_schedule()

    status = league.get("status", {})
    current_week = int(league.get("scoringPeriodId", status.get("currentMatchupPeriod", 1)) or 1)
    final_week = int(status.get("finalScoringPeriod", current_week) or current_week)
    first_week = int(from_week or current_week)
    last_week = int(through_week or final_week)
    if first_week < 1 or last_week < 1:
        raise ValueError("Sync weeks must be positive integers")
    if first_week > last_week:
        raise ValueError("--from-week must not be after --through-week")

    pools: Dict[int, Dict[str, Any]] = {}
    for week in range(first_week, last_week + 1):
        progress(f"Fetching players and projections for week {week} …")
        pools[week] = client.fetch_player_pool(week)

    offers: Dict[int, Dict[str, Any]] = {}
    if include_offers:
        for week in range(1, current_week + 1):
            progress(f"Fetching waiver results for week {week} …")
            offers[week] = client.fetch_waiver_offers(week)

    records: List[Dict[str, Any]] = [
        {
            "source": "espn-v3",
            "kind": "league",
            "league_id": league_id,
            "season": season,
            "observed_at": observed_at,
            "payload": league,
        },
        {
            "source": "espn-v3",
            "kind": "pro_schedule",
            "league_id": league_id,
            "season": season,
            "observed_at": observed_at,
            "payload": pro_schedule,
        },
    ]
    records.extend(
        {
            "source": "espn-v3",
            "kind": "player_pool",
            "league_id": league_id,
            "season": season,
            "scoring_period": week,
            "observed_at": observed_at,
            "payload": payload,
        }
        for week, payload in pools.items()
    )
    records.extend(
        {
            "source": "espn-v3",
            "kind": "waiver_offers",
            "league_id": league_id,
            "season": season,
            "scoring_period": week,
            "observed_at": observed_at,
            "payload": payload,
        }
        for week, payload in offers.items()
    )
    store.append_many(records)

    settings = league.get("settings", {})
    owned_team_id = detect_owned_team_id(league, client.config.swid)
    return LeagueSyncResult(
        observed_at=observed_at,
        league_name=str(settings.get("name", "ESPN League")),
        current_week=current_week,
        final_week=final_week,
        team_count=len(league.get("teams", [])),
        player_pool_weeks=tuple(pools),
        waiver_weeks=tuple(offers),
        owned_team_id=owned_team_id,
        snapshot_count=len(records),
    )


def _canonical_owner_id(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        value = value.get("id", "")
    return str(value).strip().strip("{}").lower()
