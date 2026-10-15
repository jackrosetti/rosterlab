from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ESPNError(RuntimeError):
    pass


class ESPNAuthenticationError(ESPNError):
    pass


@dataclass(frozen=True)
class ESPNConfig:
    league_id: int
    season: int
    espn_s2: str = ""
    swid: str = ""
    timeout_seconds: int = 30


class ESPNClient:
    """Small read-only client for ESPN's undocumented fantasy v3 endpoints.

    The transport is intentionally isolated: if ESPN changes its private API,
    snapshots and the simulation engine remain unaffected.
    """

    read_bases = (
        "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl",
        "https://fantasy.espn.com/apis/v3/games/ffl",
    )

    def __init__(self, config: ESPNConfig):
        self.config = config
        self._league_endpoint = (
            f"{self.read_bases[0]}/seasons/{config.season}/segments/0/leagues/{config.league_id}"
        )

    def fetch_league(self) -> Dict[str, Any]:
        return self._get(
            self._league_endpoint,
            params=[
                ("view", "mTeam"),
                ("view", "mRoster"),
                ("view", "mMatchup"),
                ("view", "mSettings"),
                ("view", "mStandings"),
                ("view", "mStatus"),
            ],
        )

    def fetch_pro_schedule(self) -> Dict[str, Any]:
        endpoint = f"{self.read_bases[0]}/seasons/{self.config.season}"
        return self._get(endpoint, params=[("view", "proTeamSchedules_wl")])

    def fetch_player_pool(self, scoring_period: int, page_size: int = 500) -> Dict[str, Any]:
        players: List[Dict[str, Any]] = []
        offset = 0
        template: Dict[str, Any] = {}
        # The fantasy.espn.com host handles the larger explicit-projection
        # payload more reliably; `_get` still falls back to lm-api-reads.
        endpoint = self._league_endpoint.replace(self.read_bases[0], self.read_bases[1], 1)
        while True:
            filter_value = {
                "players": {
                    "filterStatus": {"value": ["FREEAGENT", "WAIVERS", "ONTEAM"]},
                    "filterStatsForTopScoringPeriodIds": {
                        "value": 5,
                        "additionalValue": [
                            f"00{self.config.season}",
                            f"10{self.config.season}",
                            f"11{self.config.season}{scoring_period}",
                        ],
                    },
                    "limit": page_size,
                    "offset": offset,
                    "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                }
            }
            payload = self._get(
                endpoint,
                params=[("view", "kona_player_info"), ("scoringPeriodId", str(scoring_period))],
                headers={"x-fantasy-filter": json.dumps(filter_value, separators=(",", ":"))},
            )
            if not template:
                template = {key: value for key, value in payload.items() if key != "players"}
            batch = payload.get("players", []) if isinstance(payload, dict) else []
            if not isinstance(batch, list):
                raise ESPNError("ESPN returned an unexpected player-pool response")
            players.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        template["players"] = players
        template["requestedScoringPeriodId"] = scoring_period
        return template

    def fetch_waiver_offers(self, scoring_period: int) -> Dict[str, Any]:
        filter_value = {
            "transactions": {"filterType": {"value": ["WAIVER", "WAIVER_ERROR"]}}
        }
        return self._get(
            self._league_endpoint,
            params=[("view", "mTransactions2"), ("scoringPeriodId", str(scoring_period))],
            headers={"x-fantasy-filter": json.dumps(filter_value, separators=(",", ":"))},
        )

    def _get(
        self,
        endpoint: str,
        *,
        params: Iterable[Tuple[str, str]],
        headers: Optional[Mapping[str, str]] = None,
        attempts: int = 3,
    ) -> Dict[str, Any]:
        query = urlencode(list(params))
        request_headers = {
            "Accept": "application/json",
            "User-Agent": "RosterLab/0.1 local personal analytics",
        }
        if self.config.espn_s2 and self.config.swid:
            request_headers["Cookie"] = (
                f"espn_s2={self.config.espn_s2}; SWID={self.config.swid}"
            )
        request_headers.update(headers or {})
        last_error: Optional[Exception] = None
        source_base = next((base for base in self.read_bases if endpoint.startswith(base)), None)
        if source_base is None:
            endpoints = [endpoint]
        else:
            suffix = endpoint[len(source_base) :]
            endpoints = [endpoint]
            endpoints.extend(
                base + suffix for base in self.read_bases if base != source_base
            )
        total_attempts = max(attempts, len(endpoints))
        for attempt in range(total_attempts):
            try:
                active_endpoint = endpoints[attempt % len(endpoints)]
                active_url = f"{active_endpoint}?{query}" if query else active_endpoint
                request = Request(active_url, headers=request_headers, method="GET")
                with urlopen(request, timeout=self.config.timeout_seconds) as response:
                    raw = response.read()
                parsed = json.loads(raw.decode("utf-8"))
                if isinstance(parsed, list) and len(parsed) == 1:
                    parsed = parsed[0]
                if not isinstance(parsed, dict):
                    raise ESPNError("ESPN returned JSON in an unexpected shape")
                return parsed
            except HTTPError as exc:
                last_error = exc
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
            if attempt + 1 < total_attempts:
                time.sleep(0.25 * (2**attempt))
        if isinstance(last_error, HTTPError) and last_error.code in (401, 403):
            raise ESPNAuthenticationError(
                "ESPN rejected this session. Run `rosterlab login` to refresh the ESPN cookies."
            ) from last_error
        if isinstance(last_error, HTTPError) and last_error.code == 404:
            raise ESPNError(
                f"ESPN could not find league {self.config.league_id} for {self.config.season}."
            ) from last_error
        raise ESPNError(f"ESPN request failed after {total_attempts} attempts: {last_error}")
