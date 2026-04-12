"""
XDART-Φ × XHEART — Perception Database (SQLite)

Two tables:
  world_events   — collected news/events from all sources
  economic_data  — structured numeric indicators
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "perception.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS world_events (
    id              TEXT PRIMARY KEY,
    collected_at    TEXT NOT NULL,
    published_at    TEXT,

    -- SOURCE METADATA
    source_name     TEXT NOT NULL,
    source_tier     INTEGER NOT NULL,
    source_region   TEXT NOT NULL,
    source_url      TEXT,

    -- CONTENT
    headline        TEXT NOT NULL,
    summary         TEXT,

    -- CLASSIFICATION
    content_type    TEXT NOT NULL DEFAULT 'FACT',
    domain          TEXT NOT NULL DEFAULT 'MULTI',
    region_focus    TEXT DEFAULT '[]',

    -- CORROBORATION
    corroborated_by TEXT DEFAULT '[]',
    contradicted_by TEXT DEFAULT '[]',
    event_hash      TEXT UNIQUE,

    -- XDART INTEGRATION
    injected_at     TEXT,
    injected_run    INTEGER,
    concepts_born   TEXT DEFAULT '[]',
    salience_score  REAL DEFAULT 0.5,

    -- PROVENANCE
    raw_payload     TEXT
);

CREATE TABLE IF NOT EXISTS economic_data (
    id              TEXT PRIMARY KEY,
    collected_at    TEXT NOT NULL,
    source          TEXT NOT NULL,
    indicator       TEXT NOT NULL,
    value           REAL,
    unit            TEXT,
    period          TEXT NOT NULL,
    previous_value  REAL,
    change_pct      REAL,
    raw_payload     TEXT,

    UNIQUE(source, indicator, period)
);

CREATE INDEX IF NOT EXISTS idx_events_domain ON world_events(domain);
CREATE INDEX IF NOT EXISTS idx_events_collected ON world_events(collected_at);
CREATE INDEX IF NOT EXISTS idx_events_hash ON world_events(event_hash);
CREATE INDEX IF NOT EXISTS idx_events_type ON world_events(content_type);
CREATE INDEX IF NOT EXISTS idx_events_salience ON world_events(salience_score);
CREATE INDEX IF NOT EXISTS idx_econ_indicator ON economic_data(indicator);
CREATE INDEX IF NOT EXISTS idx_econ_source ON economic_data(source);
"""


class PerceptionDB:
    """SQLite-backed storage for the perception layer.

    Lightweight, no server needed — matches the no-Docker philosophy.
    """

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path or DB_PATH)
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._conn() as conn:
            conn.executescript(SCHEMA_SQL)
        logger.info("[PerceptionDB] Initialized at %s", self.db_path)

    @contextmanager
    def _conn(self):
        """Context-managed connection with WAL mode for concurrent reads."""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── World Events ──

    def store_event(
        self,
        source_name: str,
        source_tier: int,
        source_region: str,
        headline: str,
        summary: str = "",
        content_type: str = "FACT",
        domain: str = "MULTI",
        region_focus: list[str] | None = None,
        salience_score: float = 0.5,
        event_hash: str = "",
        source_url: str = "",
        published_at: str = "",
        raw_payload: dict | None = None,
    ) -> bool:
        """Store a world event. Returns False if duplicate (event_hash exists)."""
        import uuid

        with self._conn() as conn:
            try:
                conn.execute(
                    """INSERT INTO world_events
                    (id, collected_at, published_at, source_name, source_tier,
                     source_region, source_url, headline, summary, content_type,
                     domain, region_focus, event_hash, salience_score, raw_payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        datetime.now(timezone.utc).isoformat(),
                        published_at or None,
                        source_name,
                        source_tier,
                        source_region,
                        source_url,
                        headline,
                        summary[:2000] if summary else "",
                        content_type,
                        domain,
                        json.dumps(region_focus or []),
                        event_hash,
                        salience_score,
                        json.dumps(raw_payload) if raw_payload else None,
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                return False  # Duplicate event_hash

    def store_economic(
        self,
        source: str,
        indicator: str,
        value: float | None,
        period: str,
        unit: str = "",
        previous_value: float | None = None,
        change_pct: float | None = None,
        raw_payload: dict | None = None,
    ) -> bool:
        """Store an economic data point. Returns False if duplicate."""
        import uuid

        with self._conn() as conn:
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO economic_data
                    (id, collected_at, source, indicator, value, unit,
                     period, previous_value, change_pct, raw_payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        datetime.now(timezone.utc).isoformat(),
                        source,
                        indicator,
                        value,
                        unit,
                        period,
                        previous_value,
                        change_pct,
                        json.dumps(raw_payload) if raw_payload else None,
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def get_recent_events(
        self,
        hours_back: int = 72,
        content_types: list[str] | None = None,
        domains: list[str] | None = None,
        max_events: int = 20,
    ) -> list[dict]:
        """Retrieve recent events, prioritizing corroborated facts."""
        from datetime import timedelta

        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=hours_back)
        ).isoformat()

        query = """
            SELECT * FROM world_events
            WHERE collected_at > ?
        """
        params: list = [cutoff]

        if content_types:
            placeholders = ",".join("?" for _ in content_types)
            query += f" AND content_type IN ({placeholders})"
            params.extend(content_types)

        if domains:
            domain_clauses = " OR ".join("domain = ?" for _ in domains)
            query += f" AND ({domain_clauses})"
            params.extend(domains)

        query += " ORDER BY salience_score DESC, collected_at DESC LIMIT ?"
        params.append(max_events)

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_recent_economic(
        self,
        max_indicators: int = 10,
    ) -> list[dict]:
        """Retrieve latest economic indicators."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM economic_data
                ORDER BY collected_at DESC
                LIMIT ?""",
                (max_indicators,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_all_recent(self, hours_back: int = 72, max_events: int = 300) -> tuple[list[dict], list[dict]]:
        """Retrieve recent events and economic indicators within the time window.

        Events are ordered by salience DESC, with un-injected events first.
        Capped at max_events to prevent context explosion.

        Returns (events, economic_data).
        """
        from datetime import timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()

        with self._conn() as conn:
            event_rows = conn.execute(
                """SELECT * FROM world_events
                WHERE collected_at > ?
                ORDER BY (injected_at IS NULL) DESC, salience_score DESC, collected_at DESC
                LIMIT ?""",
                (cutoff, max_events),
            ).fetchall()

            econ_rows = conn.execute(
                """SELECT * FROM economic_data
                ORDER BY collected_at DESC
                LIMIT 100""",
            ).fetchall()

        events = [self._row_to_dict(r) for r in event_rows]
        indicators = [self._row_to_dict(r) for r in econ_rows]
        return events, indicators

    def mark_injected(self, event_ids: list[str], run_number: int):
        """Mark events as used by a pipeline run."""
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            for eid in event_ids:
                conn.execute(
                    """UPDATE world_events
                    SET injected_at = ?, injected_run = ?
                    WHERE id = ?""",
                    (now, run_number, eid),
                )

    def event_count(self) -> int:
        """Total number of events stored."""
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM world_events").fetchone()
            return row[0] if row else 0

    def economic_count(self) -> int:
        """Total number of economic data points."""
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM economic_data").fetchone()
            return row[0] if row else 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        """Convert a sqlite3.Row to a plain dict with JSON fields parsed."""
        d = dict(row)
        for key in ("region_focus", "corroborated_by", "contradicted_by", "concepts_born", "raw_payload"):
            if key in d and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    d[key] = [] if key != "raw_payload" else {}
        return d
