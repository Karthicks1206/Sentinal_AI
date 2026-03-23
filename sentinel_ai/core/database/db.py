"""
Database Layer - Local SQLite persistence for incidents and metrics
"""

import sqlite3
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from contextlib import contextmanager
import threading


class Database:
    """
    SQLite database manager for local persistence
    Thread-safe implementation
    """

    def __init__(self, db_path: str = "data/sentinel.db"):
        """
        Initialize database

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._local = threading.local()
        self._init_db()

    @property
    def connection(self) -> sqlite3.Connection:
        """Get thread-local database connection"""
        if not hasattr(self._local, 'connection'):
            self._local.connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False
            )
            self._local.connection.row_factory = sqlite3.Row
        return self._local.connection

    def _init_db(self):
        """Initialize database schema"""
        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    anomaly_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    metrics TEXT NOT NULL,
                    diagnosis TEXT,
                    root_cause TEXT,
                    recovery_actions TEXT,
                    recovery_status TEXT,
                    resolution_time_seconds INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    synced_to_cloud INTEGER DEFAULT 0
                )
            """)

            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS metrics_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    metric_type TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    value REAL NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS anomalies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    anomaly_id TEXT UNIQUE NOT NULL,
                    timestamp TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    anomaly_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    value REAL NOT NULL,
                    expected_value REAL,
                    deviation REAL,
                    confidence REAL,
                    created_at TEXT NOT NULL
                )
            """)

            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS recovery_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id TEXT UNIQUE NOT NULL,
                    incident_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    parameters TEXT,
                    status TEXT NOT NULL,
                    result TEXT,
                    execution_time_seconds REAL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (incident_id) REFERENCES incidents (incident_id)
                )
            """)

            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS learning_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    data_type TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(data_type, key)
                )
            """)

            self.connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_incidents_timestamp
                ON incidents(timestamp)
            """)
            self.connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_incidents_device
                ON incidents(device_id)
            """)
            self.connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_metrics_timestamp
                ON metrics_history(timestamp)
            """)
            self.connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_metrics_device_type
                ON metrics_history(device_id, metric_type)
            """)
            self.connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_anomalies_timestamp
                ON anomalies(timestamp)
            """)

    def store_incident(self, incident: Dict[str, Any]) -> int:
        """
        Store an incident

        Args:
            incident: Incident data dictionary

        Returns:
            Row ID of inserted incident
        """
        now = datetime.utcnow().isoformat()

        cursor = self.connection.execute("""
            INSERT INTO incidents (
                incident_id, timestamp, device_id, anomaly_type, severity,
                metrics, diagnosis, root_cause, recovery_actions, recovery_status,
                resolution_time_seconds, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            incident.get('incident_id'),
            incident.get('timestamp'),
            incident.get('device_id'),
            incident.get('anomaly_type'),
            incident.get('severity'),
            json.dumps(incident.get('metrics', {})),
            incident.get('diagnosis'),
            incident.get('root_cause'),
            json.dumps(incident.get('recovery_actions', [])),
            incident.get('recovery_status'),
            incident.get('resolution_time_seconds'),
            now,
            now
        ))

        self.connection.commit()
        return cursor.lastrowid

    def update_incident(self, incident_id: str, updates: Dict[str, Any]):
        """
        Update an existing incident

        Args:
            incident_id: Incident ID
            updates: Dictionary of fields to update
        """
        set_clause = []
        values = []

        for key, value in updates.items():
            if key in ['metrics', 'recovery_actions'] and isinstance(value, (dict, list)):
                value = json.dumps(value)
            set_clause.append(f"{key} = ?")
            values.append(value)

        set_clause.append("updated_at = ?")
        values.append(datetime.utcnow().isoformat())
        values.append(incident_id)

        query = f"UPDATE incidents SET {', '.join(set_clause)} WHERE incident_id = ?"
        self.connection.execute(query, values)
        self.connection.commit()

    def store_metric(self, device_id: str, metric_type: str, metric_name: str,
                    value: float, metadata: Optional[Dict] = None):
        """
        Store a metric value

        Args:
            device_id: Device identifier
            metric_type: Type of metric (cpu, memory, etc.)
            metric_name: Metric name
            value: Metric value
            metadata: Optional metadata
        """
        now = datetime.utcnow().isoformat()

        self.connection.execute("""
            INSERT INTO metrics_history (
                timestamp, device_id, metric_type, metric_name, value, metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            now,
            device_id,
            metric_type,
            metric_name,
            value,
            json.dumps(metadata) if metadata else None,
            now
        ))

        self.connection.commit()

    def store_anomaly(self, anomaly: Dict[str, Any]) -> int:
        """
        Store an anomaly detection

        Args:
            anomaly: Anomaly data

        Returns:
            Row ID
        """
        now = datetime.utcnow().isoformat()

        cursor = self.connection.execute("""
            INSERT INTO anomalies (
                anomaly_id, timestamp, device_id, metric_name, anomaly_type,
                severity, value, expected_value, deviation, confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            anomaly.get('anomaly_id'),
            anomaly.get('timestamp'),
            anomaly.get('device_id'),
            anomaly.get('metric_name'),
            anomaly.get('anomaly_type'),
            anomaly.get('severity'),
            anomaly.get('value'),
            anomaly.get('expected_value'),
            anomaly.get('deviation'),
            anomaly.get('confidence'),
            now
        ))

        self.connection.commit()
        return cursor.lastrowid

    def store_recovery_action(self, action: Dict[str, Any]) -> int:
        """
        Store a recovery action

        Args:
            action: Recovery action data

        Returns:
            Row ID
        """
        now = datetime.utcnow().isoformat()

        cursor = self.connection.execute("""
            INSERT INTO recovery_actions (
                action_id, incident_id, timestamp, action_type, parameters,
                status, result, execution_time_seconds, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            action.get('action_id'),
            action.get('incident_id'),
            action.get('timestamp'),
            action.get('action_type'),
            json.dumps(action.get('parameters', {})),
            action.get('status'),
            action.get('result'),
            action.get('execution_time_seconds'),
            now
        ))

        self.connection.commit()
        return cursor.lastrowid

    def get_recent_incidents(self, limit: int = 100, device_id: Optional[str] = None) -> List[Dict]:
        """
        Get recent incidents

        Args:
            limit: Maximum number of incidents
            device_id: Optional device filter

        Returns:
            List of incidents
        """
        query = "SELECT * FROM incidents"
        params = []

        if device_id:
            query += " WHERE device_id = ?"
            params.append(device_id)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = self.connection.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_metrics_history(
        self,
        device_id: str,
        metric_type: Optional[str] = None,
        hours: int = 24
    ) -> List[Dict]:
        """
        Get metrics history

        Args:
            device_id: Device ID
            metric_type: Optional metric type filter
            hours: Number of hours to look back

        Returns:
            List of metrics
        """
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        query = """
            SELECT * FROM metrics_history
            WHERE device_id = ? AND timestamp > ?
        """
        params = [device_id, cutoff]

        if metric_type:
            query += " AND metric_type = ?"
            params.append(metric_type)

        query += " ORDER BY timestamp ASC"

        cursor = self.connection.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def store_learning_data(self, data_type: str, key: str, value: Any, metadata: Optional[Dict] = None):
        """
        Store learning data (thresholds, patterns, etc.)

        Args:
            data_type: Type of learning data
            key: Data key
            value: Data value
            metadata: Optional metadata
        """
        now = datetime.utcnow().isoformat()

        if not isinstance(value, str):
            value = json.dumps(value)

        self.connection.execute("""
            INSERT OR REPLACE INTO learning_data (
                timestamp, data_type, key, value, metadata, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            now,
            data_type,
            key,
            value,
            json.dumps(metadata) if metadata else None,
            now,
            now
        ))

        self.connection.commit()

    def get_learning_data(self, data_type: str, key: str) -> Optional[Any]:
        """
        Retrieve learning data

        Args:
            data_type: Type of learning data
            key: Data key

        Returns:
            Stored value or None
        """
        cursor = self.connection.execute("""
            SELECT value FROM learning_data
            WHERE data_type = ? AND key = ?
        """, (data_type, key))

        row = cursor.fetchone()
        if row:
            try:
                return json.loads(row['value'])
            except:
                return row['value']
        return None

    def cleanup_old_data(self, retention_days: int = 90):
        """
        Clean up old data based on retention policy

        Args:
            retention_days: Number of days to retain
        """
        cutoff = (datetime.utcnow() - timedelta(days=retention_days)).isoformat()

        self.connection.execute("""
            DELETE FROM metrics_history WHERE timestamp < ?
        """, (cutoff,))

        self.connection.execute("""
            DELETE FROM anomalies WHERE timestamp < ?
        """, (cutoff,))

        self.connection.commit()

    def get_unsynced_incidents(self, limit: int = 100) -> List[Dict]:
        """
        Get incidents that haven't been synced to cloud

        Args:
            limit: Maximum number to retrieve

        Returns:
            List of unsynced incidents
        """
        cursor = self.connection.execute("""
            SELECT * FROM incidents
            WHERE synced_to_cloud = 0
            ORDER BY timestamp ASC
            LIMIT ?
        """, (limit,))

        return [dict(row) for row in cursor.fetchall()]

    def mark_incidents_synced(self, incident_ids: List[str]):
        """
        Mark incidents as synced to cloud

        Args:
            incident_ids: List of incident IDs
        """
        placeholders = ','.join('?' * len(incident_ids))
        self.connection.execute(f"""
            UPDATE incidents
            SET synced_to_cloud = 1
            WHERE incident_id IN ({placeholders})
        """, incident_ids)

        self.connection.commit()

    def close(self):
        """Close database connection"""
        if hasattr(self._local, 'connection'):
            self._local.connection.close()


_global_db: Optional[Database] = None


def get_database(config=None) -> Database:
    """
    Get global database instance

    Args:
        config: Optional configuration

    Returns:
        Database instance
    """
    global _global_db

    if _global_db is None:
        if config:
            db_path = config.get('learning.local_db.path', 'data/sentinel.db')
            _global_db = Database(db_path)
        else:
            _global_db = Database()

    return _global_db
