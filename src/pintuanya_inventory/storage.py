import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .models import utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS targets(target_id TEXT PRIMARY KEY, label TEXT, resolved_group_id TEXT);
CREATE TABLE IF NOT EXISTS collection_runs(
 run_id TEXT PRIMARY KEY, target_id TEXT NOT NULL, mode TEXT NOT NULL, role TEXT NOT NULL,
 started_at TEXT NOT NULL, finished_at TEXT NOT NULL, status TEXT NOT NULL, coverage TEXT NOT NULL,
 expected_count INTEGER, observed_count INTEGER NOT NULL, error_code TEXT, endpoint_alias TEXT,
 mapping_version TEXT NOT NULL, session_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observations(
 run_id TEXT NOT NULL, product_id TEXT NOT NULL, sku_id TEXT NOT NULL, data TEXT NOT NULL,
 PRIMARY KEY(run_id,product_id,sku_id), FOREIGN KEY(run_id) REFERENCES collection_runs(run_id));
CREATE TABLE IF NOT EXISTS checkpoints(source TEXT PRIMARY KEY, offset INTEGER NOT NULL, prefix_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS candidate_evidence(
 run_id TEXT NOT NULL, product_id TEXT NOT NULL, sku_id TEXT NOT NULL, field_alias TEXT NOT NULL, data TEXT NOT NULL,
 PRIMARY KEY(run_id,product_id,sku_id,field_alias), FOREIGN KEY(run_id) REFERENCES collection_runs(run_id));
"""


def connect(path, readonly=False):
    path = Path(path).resolve()
    if readonly:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path)
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def write_event(db, event):
    """Caller owns transaction, including queue offset. Event IDs are idempotent."""
    db.execute("INSERT OR IGNORE INTO targets VALUES(?,?,?)",
               (event["target_id"], event["target_label"], event["group_id"]))
    if db.execute("SELECT 1 FROM collection_runs WHERE run_id=?", (event["event_id"],)).fetchone():
        return False
    db.execute("INSERT INTO collection_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        event["event_id"], event["target_id"], event["mode"], event["role"], event["observed_at"], utcnow(),
        event["status"], event["coverage"], event.get("expected_count"), len(event["observations"]),
        event.get("error_code"), event["endpoint_alias"], event["mapping_version"], event["session_id"]))
    for row in event["observations"]:
        db.execute("INSERT INTO observations VALUES(?,?,?,?)", (
            event["event_id"], row["product_id"], row["sku_id"], json.dumps(row, ensure_ascii=False)))
    for row in event.get("candidates", []):
        db.execute("INSERT INTO candidate_evidence VALUES(?,?,?,?,?)", (
            event["event_id"], row["product_id"], row["sku_id"], row["field_alias"], json.dumps(row, ensure_ascii=False)))
    return True


def current(db, mode="passive", stale_seconds=600):
    runs = [dict(r) for r in db.execute(
        "SELECT * FROM collection_runs WHERE mode=? ORDER BY started_at, rowid", (mode,))]
    latest = {}
    success = {}
    last_quantity = {}
    attempts = {}
    for run in runs:
        attempts[(run["target_id"], run["endpoint_alias"])] = run
        for record in db.execute("SELECT data FROM observations WHERE run_id=?", (run["run_id"],)):
            row = json.loads(record[0])
            key = (run["target_id"], row["product_id"], row["sku_id"])
            row.update({"target_id": run["target_id"], "mode": mode, "endpoint_alias": run["endpoint_alias"],
                        "observed_at": run["started_at"], "mapping_version": run["mapping_version"],
                        "coverage": run["coverage"], "run_id": run["run_id"], "inventory_change": None})
            prior = last_quantity.get(key)
            if row["stock_remaining"] is not None:
                if prior and prior["mapping_version"] == row["mapping_version"]:
                    row["inventory_change"] = row["stock_remaining"] - prior["stock_remaining"]
                last_quantity[key] = row.copy()
            latest[key] = row
            if row["stock_remaining"] is not None or row["availability"] != "unknown":
                success[key] = run["started_at"]
    for key, row in latest.items():
        attempt = attempts[(key[0], row["endpoint_alias"])]
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(row["observed_at"])).total_seconds()
        failed_after = attempt["started_at"] > row["observed_at"] and attempt["error_code"] is not None
        row.update({"latest_attempt_at": attempt["started_at"], "latest_attempt_status": attempt["status"],
                    "latest_error": attempt["error_code"], "last_success_at": success.get(key),
                    "stale": failed_after or age > stale_seconds,
                    "server_timestamp": None, "cache_status": "unknown"})
    return list(latest.values())


def run_summary(db, mode):
    return [dict(r) for r in db.execute(
        "SELECT * FROM collection_runs WHERE mode=? ORDER BY started_at DESC, rowid DESC LIMIT 20", (mode,))]


def candidate_current(db, mode="passive"):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='candidate_evidence'").fetchone():
        return []
    latest = {}
    names = {(r["target_id"], r["product_id"], r["sku_id"]): r for r in current(db, mode)}
    for record in db.execute("SELECT c.data,r.target_id,r.started_at,r.endpoint_alias,r.mapping_version FROM candidate_evidence c "
                             "JOIN collection_runs r ON c.run_id=r.run_id WHERE r.mode=? ORDER BY r.started_at,r.rowid", (mode,)):
        row = json.loads(record["data"])
        key = (record["target_id"], row["product_id"], row["sku_id"])
        name = names.get(key, {})
        row.update({"mode": mode, "target_id": key[0], "observed_at": record["started_at"],
                    "endpoint_alias": record["endpoint_alias"], "mapping_version": record["mapping_version"],
                    "product_name": name.get("product_name", ""), "sku_name": name.get("sku_name", ""),
                    "latest_attempt_at": name.get("latest_attempt_at"), "latest_error": name.get("latest_error"),
                    "stale": bool(name.get("stale")) or (datetime.now(timezone.utc) - datetime.fromisoformat(record["started_at"])).total_seconds() > 600})
        latest[key + (row["field_alias"],)] = row
    return list(latest.values())
