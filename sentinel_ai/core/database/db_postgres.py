"""
PostgreSQL Database Layer — Sentinel AI
Replaces the SQLite backend with a proper relational database.

Schema highlights:
  • SERIAL PRIMARY KEY on every table
  • UNIQUE natural-key constraints (incident_id, anomaly_id, action_id)
  • FOREIGN KEY recovery_actions.incident_id → incidents.incident_id  CASCADE DELETE
  • JSONB columns for metrics, recovery_actions, parameters, metadata
    (native binary JSON — indexable, queryable via ->> operator)
  • TIMESTAMPTZ timestamps (timezone-aware, stored as UTC)
  • Covering indexes for every common query pattern

Connection management:
  • psycopg2 ThreadedConnectionPool (min=2, max=20)
  • One connection checked out per database call, returned immediately after
  • Thread-safe — multiple agents write concurrently without locking
"""

import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool


# ── DDL ───────────────────────────────────────────────────────────────────────

_DDL = """
-- ── incidents ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS incidents (
    id                      SERIAL          PRIMARY KEY,
    incident_id             TEXT            NOT NULL,
    timestamp               TIMESTAMPTZ     NOT NULL,
    device_id               TEXT            NOT NULL,
    anomaly_type            TEXT            NOT NULL,
    severity                TEXT            NOT NULL,
    metrics                 JSONB           NOT NULL  DEFAULT '{}',
    diagnosis               TEXT,
    root_cause              TEXT,
    recovery_actions        JSONB                     DEFAULT '[]',
    recovery_status         TEXT,
    resolution_time_seconds INTEGER,
    created_at              TIMESTAMPTZ     NOT NULL  DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL  DEFAULT NOW(),
    synced_to_cloud         BOOLEAN         NOT NULL  DEFAULT FALSE,

    CONSTRAINT uq_incidents_incident_id UNIQUE (incident_id)
);

CREATE INDEX IF NOT EXISTS idx_incidents_timestamp
    ON incidents (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_device_ts
    ON incidents (device_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_incidents_severity
    ON incidents (severity);
CREATE INDEX IF NOT EXISTS idx_incidents_unsynced
    ON incidents (synced_to_cloud)
    WHERE synced_to_cloud = FALSE;

-- ── metrics_history ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS metrics_history (
    id          SERIAL          PRIMARY KEY,
    timestamp   TIMESTAMPTZ     NOT NULL,
    device_id   TEXT            NOT NULL,
    metric_type TEXT            NOT NULL,
    metric_name TEXT            NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    metadata    JSONB                     DEFAULT '{}',
    created_at  TIMESTAMPTZ     NOT NULL  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_metrics_device_type_ts
    ON metrics_history (device_id, metric_type, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_timestamp
    ON metrics_history (timestamp DESC);

-- ── anomalies ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS anomalies (
    id             SERIAL           PRIMARY KEY,
    anomaly_id     TEXT             NOT NULL,
    timestamp      TIMESTAMPTZ      NOT NULL,
    device_id      TEXT             NOT NULL,
    metric_name    TEXT             NOT NULL,
    anomaly_type   TEXT             NOT NULL,
    severity       TEXT             NOT NULL,
    value          DOUBLE PRECISION NOT NULL,
    expected_value DOUBLE PRECISION,
    deviation      DOUBLE PRECISION,
    confidence     DOUBLE PRECISION,
    created_at     TIMESTAMPTZ      NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_anomalies_anomaly_id UNIQUE (anomaly_id)
);

CREATE INDEX IF NOT EXISTS idx_anomalies_device_ts
    ON anomalies (device_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_anomalies_timestamp
    ON anomalies (timestamp DESC);

-- ── recovery_actions ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS recovery_actions (
    id                     SERIAL           PRIMARY KEY,
    action_id              TEXT             NOT NULL,
    incident_id            TEXT             NOT NULL,
    timestamp              TIMESTAMPTZ      NOT NULL,
    action_type            TEXT             NOT NULL,
    parameters             JSONB                     DEFAULT '{}',
    status                 TEXT             NOT NULL,
    result                 TEXT,
    execution_time_seconds DOUBLE PRECISION,
    created_at             TIMESTAMPTZ      NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_recovery_action_id    UNIQUE (action_id),
    CONSTRAINT fk_recovery_incident     FOREIGN KEY (incident_id)
        REFERENCES incidents (incident_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_recovery_incident
    ON recovery_actions (incident_id);
CREATE INDEX IF NOT EXISTS idx_recovery_timestamp
    ON recovery_actions (timestamp DESC);

-- ── learning_data ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS learning_data (
    id         SERIAL       PRIMARY KEY,
    timestamp  TIMESTAMPTZ  NOT NULL,
    data_type  TEXT         NOT NULL,
    key        TEXT         NOT NULL,
    value      JSONB        NOT NULL,
    metadata   JSONB                 DEFAULT '{}',
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_learning_type_key UNIQUE (data_type, key)
);

CREATE INDEX IF NOT EXISTS idx_learning_type_key
    ON learning_data (data_type, key);
"""


# ── PostgreSQL database class ─────────────────────────────────────────────────

class PostgresDatabase:
    """
    PostgreSQL-backed persistent store for Sentinel AI.

    Implements exactly the same public interface as the SQLite Database class
    so no agent or dashboard code needs to change.
    """

    def __init__(self, dsn: str, min_conn: int = 2, max_conn: int = 20):
        """
        Args:
            dsn:      libpq connection string,
                      e.g. "postgresql://sentinel_user:pass@localhost:5432/sentinel_ai"
            min_conn: minimum connections kept open in the pool
            max_conn: maximum connections allowed in the pool
        """
        self._pool = ThreadedConnectionPool(min_conn, max_conn, dsn)
        self._init_schema()

    # ------------------------------------------------------------------ pool

    @contextmanager
    def _conn(self):
        """Yield a connection from the pool; return it when done."""
        conn = self._pool.getconn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._pool.putconn(conn)

    # ------------------------------------------------------------------ schema

    def _init_schema(self):
        """Create tables and indexes if they don't already exist."""
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_DDL)

    # ================================================================== writes

    def store_incident(self, incident: Dict[str, Any]) -> int:
        now = _now()
        sql = """
            INSERT INTO incidents (
                incident_id, timestamp, device_id, anomaly_type, severity,
                metrics, diagnosis, root_cause, recovery_actions,
                recovery_status, resolution_time_seconds,
                created_at, updated_at
            ) VALUES (
                %(incident_id)s, %(timestamp)s, %(device_id)s,
                %(anomaly_type)s, %(severity)s,
                %(metrics)s, %(diagnosis)s, %(root_cause)s,
                %(recovery_actions)s, %(recovery_status)s,
                %(resolution_time_seconds)s,
                %(created_at)s, %(updated_at)s
            )
            ON CONFLICT (incident_id) DO NOTHING
            RETURNING id
        """
        params = {
            'incident_id'              : incident.get('incident_id'),
            'timestamp'                : _parse_ts(incident.get('timestamp', now)),
            'device_id'                : incident.get('device_id'),
            'anomaly_type'             : incident.get('anomaly_type'),
            'severity'                 : incident.get('severity'),
            'metrics'                  : _jsonb(incident.get('metrics', {})),
            'diagnosis'                : incident.get('diagnosis'),
            'root_cause'               : incident.get('root_cause'),
            'recovery_actions'         : _jsonb(incident.get('recovery_actions', [])),
            'recovery_status'          : incident.get('recovery_status'),
            'resolution_time_seconds'  : incident.get('resolution_time_seconds'),
            'created_at'               : now,
            'updated_at'               : now,
        }
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                return row[0] if row else 0

    def update_incident(self, incident_id: str, updates: Dict[str, Any]):
        if not updates:
            return
        set_parts = []
        params: Dict[str, Any] = {}
        for key, value in updates.items():
            if key in ('metrics', 'recovery_actions') and isinstance(value, (dict, list)):
                value = _jsonb(value)
            params[key] = value
            set_parts.append(f"{key} = %({key})s")

        set_parts.append("updated_at = %(updated_at)s")
        params['updated_at'] = _now()
        params['incident_id'] = incident_id

        sql = f"UPDATE incidents SET {', '.join(set_parts)} WHERE incident_id = %(incident_id)s"
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)

    def store_metric(self, device_id: str, metric_type: str, metric_name: str,
                     value: float, metadata: Optional[Dict] = None):
        now = _now()
        sql = """
            INSERT INTO metrics_history
                (timestamp, device_id, metric_type, metric_name, value, metadata, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (
                    now, device_id, metric_type, metric_name, value,
                    _jsonb(metadata or {}), now,
                ))

    def store_anomaly(self, anomaly: Dict[str, Any]) -> int:
        now = _now()
        sql = """
            INSERT INTO anomalies (
                anomaly_id, timestamp, device_id, metric_name, anomaly_type,
                severity, value, expected_value, deviation, confidence, created_at
            ) VALUES (
                %(anomaly_id)s, %(timestamp)s, %(device_id)s, %(metric_name)s,
                %(anomaly_type)s, %(severity)s, %(value)s, %(expected_value)s,
                %(deviation)s, %(confidence)s, %(created_at)s
            )
            ON CONFLICT (anomaly_id) DO NOTHING
            RETURNING id
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {
                    'anomaly_id'    : anomaly.get('anomaly_id'),
                    'timestamp'     : _parse_ts(anomaly.get('timestamp', now)),
                    'device_id'     : anomaly.get('device_id'),
                    'metric_name'   : anomaly.get('metric_name'),
                    'anomaly_type'  : anomaly.get('anomaly_type'),
                    'severity'      : anomaly.get('severity'),
                    'value'         : anomaly.get('value'),
                    'expected_value': anomaly.get('expected_value'),
                    'deviation'     : anomaly.get('deviation'),
                    'confidence'    : anomaly.get('confidence'),
                    'created_at'    : now,
                })
                row = cur.fetchone()
                return row[0] if row else 0

    def store_recovery_action(self, action: Dict[str, Any]) -> int:
        now = _now()
        sql = """
            INSERT INTO recovery_actions (
                action_id, incident_id, timestamp, action_type,
                parameters, status, result, execution_time_seconds, created_at
            ) VALUES (
                %(action_id)s, %(incident_id)s, %(timestamp)s, %(action_type)s,
                %(parameters)s, %(status)s, %(result)s,
                %(execution_time_seconds)s, %(created_at)s
            )
            ON CONFLICT (action_id) DO NOTHING
            RETURNING id
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {
                    'action_id'             : action.get('action_id'),
                    'incident_id'           : action.get('incident_id'),
                    'timestamp'             : _parse_ts(action.get('timestamp', now)),
                    'action_type'           : action.get('action_type'),
                    'parameters'            : _jsonb(action.get('parameters', {})),
                    'status'                : action.get('status'),
                    'result'                : action.get('result'),
                    'execution_time_seconds': action.get('execution_time_seconds'),
                    'created_at'            : now,
                })
                row = cur.fetchone()
                return row[0] if row else 0

    def store_learning_data(self, data_type: str, key: str,
                             value: Any, metadata: Optional[Dict] = None):
        now  = _now()
        val  = value if isinstance(value, str) else json.dumps(value)
        # Parse back to dict/list so it's stored as JSONB (not a JSON string)
        try:
            val_obj = json.loads(val)
        except (TypeError, json.JSONDecodeError):
            val_obj = val

        sql = """
            INSERT INTO learning_data
                (timestamp, data_type, key, value, metadata, created_at, updated_at)
            VALUES (%(ts)s, %(dt)s, %(key)s, %(val)s, %(meta)s, %(ts)s, %(ts)s)
            ON CONFLICT (data_type, key)
            DO UPDATE SET
                value      = EXCLUDED.value,
                metadata   = EXCLUDED.metadata,
                updated_at = EXCLUDED.updated_at
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, {
                    'ts'  : now,
                    'dt'  : data_type,
                    'key' : key,
                    'val' : _jsonb(val_obj),
                    'meta': _jsonb(metadata or {}),
                })

    # ================================================================== reads

    def get_recent_incidents(self, limit: int = 100,
                              device_id: Optional[str] = None) -> List[Dict]:
        sql = "SELECT * FROM incidents"
        params: list = []
        if device_id:
            sql += " WHERE device_id = %s"
            params.append(device_id)
        sql += " ORDER BY timestamp DESC LIMIT %s"
        params.append(limit)

        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_metrics_history(self, device_id: str,
                             metric_type: Optional[str] = None,
                             hours: int = 24) -> List[Dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        sql = """
            SELECT * FROM metrics_history
            WHERE device_id = %s AND timestamp > %s
        """
        params: list = [device_id, cutoff]
        if metric_type:
            sql += " AND metric_type = %s"
            params.append(metric_type)
        sql += " ORDER BY timestamp ASC"

        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_learning_data(self, data_type: str, key: str) -> Optional[Any]:
        sql = "SELECT value FROM learning_data WHERE data_type = %s AND key = %s"
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (data_type, key))
                row = cur.fetchone()
        if row is None:
            return None
        val = row[0]
        # JSONB comes back as a Python object already; strings stay strings
        return val

    def get_unsynced_incidents(self, limit: int = 100) -> List[Dict]:
        sql = """
            SELECT * FROM incidents
            WHERE synced_to_cloud = FALSE
            ORDER BY timestamp ASC
            LIMIT %s
        """
        with self._conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]

    def mark_incidents_synced(self, incident_ids: List[str]):
        if not incident_ids:
            return
        sql = "UPDATE incidents SET synced_to_cloud = TRUE WHERE incident_id = ANY(%s)"
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (incident_ids,))

    def cleanup_old_data(self, retention_days: int = 90):
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM metrics_history WHERE timestamp < %s", (cutoff,))
                cur.execute("DELETE FROM anomalies       WHERE timestamp < %s", (cutoff,))

    def close(self):
        self._pool.closeall()


# ── helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime:
    """Convert ISO string or datetime to timezone-aware datetime."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    return _now()


def _jsonb(value: Any) -> psycopg2.extras.Json:
    """Wrap a Python object for psycopg2 JSONB insertion."""
    return psycopg2.extras.Json(value)


def _row_to_dict(row) -> Dict:
    """Convert a RealDictRow to a plain dict, serialising any remaining non-JSON types."""
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


# ── factory ───────────────────────────────────────────────────────────────────

_global_pg_db: Optional[PostgresDatabase] = None


def get_postgres_database(config=None) -> PostgresDatabase:
    """
    Return the singleton PostgresDatabase instance.
    Reads DATABASE_URL from the environment (preferred) or assembles
    it from individual PG_* variables.
    """
    global _global_pg_db
    if _global_pg_db is not None:
        return _global_pg_db

    dsn = os.environ.get('DATABASE_URL', '').strip()
    if not dsn:
        host   = os.environ.get('PG_HOST',     'localhost')
        port   = os.environ.get('PG_PORT',     '5432')
        dbname = os.environ.get('PG_DBNAME',   'sentinel_ai')
        user   = os.environ.get('PG_USER',     'sentinel_user')
        passwd = os.environ.get('PG_PASSWORD', 'sentinel_pass')
        dsn    = f"postgresql://{user}:{passwd}@{host}:{port}/{dbname}"

    _global_pg_db = PostgresDatabase(dsn)
    return _global_pg_db
