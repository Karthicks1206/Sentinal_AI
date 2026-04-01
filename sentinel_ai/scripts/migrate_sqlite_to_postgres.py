#!/usr/bin/env python3
"""
One-shot migration: SQLite data/sentinel.db → PostgreSQL sentinel_ai
Run once after setting up PostgreSQL:

    source venv/bin/activate
    python scripts/migrate_sqlite_to_postgres.py
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

# ── ensure project root on path ──────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault('DATABASE_URL',
    'postgresql://sentinel_user:sentinel_pass@localhost:5432/sentinel_ai')

from core.database.db_postgres import get_postgres_database

SQLITE_PATH = ROOT / 'data' / 'sentinel.db'


def migrate():
    if not SQLITE_PATH.exists():
        print(f"SQLite file not found at {SQLITE_PATH} — nothing to migrate.")
        return

    src = sqlite3.connect(str(SQLITE_PATH))
    src.row_factory = sqlite3.Row
    pg  = get_postgres_database()
    print(f"Migrating {SQLITE_PATH} → PostgreSQL sentinel_ai")

    # ── incidents ──────────────────────────────────────────────────────────
    rows = src.execute("SELECT * FROM incidents").fetchall()
    ok = 0
    for r in rows:
        d = dict(r)
        for col in ('metrics', 'recovery_actions'):
            if isinstance(d.get(col), str):
                try:
                    d[col] = json.loads(d[col])
                except Exception:
                    d[col] = {}
        d['synced_to_cloud'] = bool(d.get('synced_to_cloud', 0))
        try:
            pg.store_incident(d)
            ok += 1
        except Exception as exc:
            print(f"  incident {d.get('incident_id')}: {exc}")
    print(f"  incidents:        {ok}/{len(rows)}")

    # ── metrics_history ────────────────────────────────────────────────────
    rows = src.execute("SELECT * FROM metrics_history").fetchall()
    ok = 0
    for r in rows:
        d = dict(r)
        meta = d.get('metadata')
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        try:
            pg.store_metric(d['device_id'], d['metric_type'],
                            d['metric_name'], d['value'], meta)
            ok += 1
        except Exception as exc:
            print(f"  metric row {d.get('id')}: {exc}")
    print(f"  metrics_history:  {ok}/{len(rows)}")

    # ── anomalies ─────────────────────────────────────────────────────────
    rows = src.execute("SELECT * FROM anomalies").fetchall()
    ok = 0
    for r in rows:
        try:
            pg.store_anomaly(dict(r))
            ok += 1
        except Exception as exc:
            print(f"  anomaly {dict(r).get('anomaly_id')}: {exc}")
    print(f"  anomalies:        {ok}/{len(rows)}")

    # ── recovery_actions ─────────────────────────────────────────────────
    rows = src.execute("SELECT * FROM recovery_actions").fetchall()
    ok = 0
    for r in rows:
        d = dict(r)
        if isinstance(d.get('parameters'), str):
            try:
                d['parameters'] = json.loads(d['parameters'])
            except Exception:
                d['parameters'] = {}
        try:
            pg.store_recovery_action(d)
            ok += 1
        except Exception as exc:
            print(f"  action {d.get('action_id')}: {exc}")
    print(f"  recovery_actions: {ok}/{len(rows)}")

    # ── learning_data ────────────────────────────────────────────────────
    rows = src.execute("SELECT * FROM learning_data").fetchall()
    ok = 0
    for r in rows:
        d = dict(r)
        val = d.get('value', '{}')
        try:
            val = json.loads(val)
        except Exception:
            pass
        meta = d.get('metadata')
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        try:
            pg.store_learning_data(d['data_type'], d['key'], val, meta)
            ok += 1
        except Exception as exc:
            print(f"  learning {d.get('data_type')}/{d.get('key')}: {exc}")
    print(f"  learning_data:    {ok}/{len(rows)}")

    src.close()
    pg.close()
    print("\nMigration complete.")


if __name__ == '__main__':
    migrate()
