from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Optional


DEFAULT_PROFILE = Path("data/rosterlab.json")


@dataclass(frozen=True)
class LocalProfile:
    league_id: Optional[int] = None
    season: Optional[int] = None
    team_id: Optional[int] = None
    league_name: str = ""
    last_sync_at: str = ""

    def with_updates(self, **updates: Any) -> "LocalProfile":
        return replace(self, **updates)


def load_profile(path: Path = DEFAULT_PROFILE) -> LocalProfile:
    path = Path(path)
    if not path.exists():
        return LocalProfile()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read RosterLab profile {path}: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise ValueError(f"RosterLab profile {path} must contain a JSON object")
    return LocalProfile(
        league_id=_optional_int(raw.get("league_id")),
        season=_optional_int(raw.get("season")),
        team_id=_optional_int(raw.get("team_id")),
        league_name=str(raw.get("league_name", "") or ""),
        last_sync_at=str(raw.get("last_sync_at", "") or ""),
    )


def save_profile(profile: LocalProfile, path: Path = DEFAULT_PROFILE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(asdict(profile), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return path


def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    return int(value)
