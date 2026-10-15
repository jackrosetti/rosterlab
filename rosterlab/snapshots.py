from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    league_id INTEGER NOT NULL,
    season INTEGER NOT NULL,
    scoring_period INTEGER,
    observed_at TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_lookup
ON snapshots (league_id, season, kind, scoring_period, observed_at DESC, id DESC);
"""


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: int
    source: str
    kind: str
    league_id: int
    season: int
    scoring_period: Optional[int]
    observed_at: str
    content_sha256: str
    payload: Any


class SnapshotStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        return connection

    def append(
        self,
        *,
        source: str,
        kind: str,
        league_id: int,
        season: int,
        payload: Any,
        scoring_period: Optional[int] = None,
        observed_at: Optional[str] = None,
    ) -> Snapshot:
        observed_at = observed_at or datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO snapshots
                    (source, kind, league_id, season, scoring_period, observed_at, content_sha256, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source, kind, league_id, season, scoring_period, observed_at, digest, payload_json),
            )
            snapshot_id = int(cursor.lastrowid)
        return Snapshot(snapshot_id, source, kind, league_id, season, scoring_period, observed_at, digest, payload)

    def append_many(self, records: Iterable[Mapping[str, Any]]) -> List[Snapshot]:
        prepared = []
        for record in records:
            payload = record["payload"]
            payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            prepared.append(
                (
                    str(record["source"]),
                    str(record["kind"]),
                    int(record["league_id"]),
                    int(record["season"]),
                    int(record["scoring_period"]) if record.get("scoring_period") is not None else None,
                    str(record.get("observed_at") or datetime.now(timezone.utc).isoformat()),
                    hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                    payload_json,
                    payload,
                )
            )
        created: List[Snapshot] = []
        with self._connect() as connection:
            for source, kind, league_id, season, period, observed_at, digest, payload_json, payload in prepared:
                cursor = connection.execute(
                    """
                    INSERT INTO snapshots
                        (source, kind, league_id, season, scoring_period, observed_at, content_sha256, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (source, kind, league_id, season, period, observed_at, digest, payload_json),
                )
                created.append(
                    Snapshot(
                        int(cursor.lastrowid), source, kind, league_id, season,
                        period, observed_at, digest, payload,
                    )
                )
        return created

    def latest(
        self,
        *,
        kind: str,
        league_id: int,
        season: int,
        scoring_period: Optional[int] = None,
        as_of: Optional[str] = None,
    ) -> Optional[Snapshot]:
        clauses = ["kind = ?", "league_id = ?", "season = ?"]
        params: List[Any] = [kind, league_id, season]
        if scoring_period is None:
            clauses.append("scoring_period IS NULL")
        else:
            clauses.append("scoring_period = ?")
            params.append(scoring_period)
        if as_of is not None:
            clauses.append("observed_at <= ?")
            params.append(as_of)
        query = (
            "SELECT * FROM snapshots WHERE "
            + " AND ".join(clauses)
            + " ORDER BY observed_at DESC, id DESC LIMIT 1"
        )
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return self._row_to_snapshot(row) if row else None

    def periods(self, *, kind: str, league_id: int, season: int) -> List[int]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT scoring_period FROM snapshots
                WHERE kind = ? AND league_id = ? AND season = ? AND scoring_period IS NOT NULL
                ORDER BY scoring_period
                """,
                (kind, league_id, season),
            ).fetchall()
        return [int(row[0]) for row in rows]

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> Snapshot:
        return Snapshot(
            snapshot_id=int(row["id"]),
            source=str(row["source"]),
            kind=str(row["kind"]),
            league_id=int(row["league_id"]),
            season=int(row["season"]),
            scoring_period=int(row["scoring_period"]) if row["scoring_period"] is not None else None,
            observed_at=str(row["observed_at"]),
            content_sha256=str(row["content_sha256"]),
            payload=json.loads(row["payload_json"]),
        )
