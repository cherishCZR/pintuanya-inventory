import hashlib
import json
from pathlib import Path
from .config import resolve, validate_capture
from .pipeline import validate_event
from .storage import connect, write_event


def prefix_hash(f, size):
    f.seek(0)
    h = hashlib.sha256()
    left = size
    while left:
        chunk = f.read(min(left, 65536))
        if not chunk:
            break
        h.update(chunk)
        left -= len(chunk)
    return h.hexdigest()


def ingest(c, db_path):
    m = validate_capture(c)
    source = resolve(c, "queue_file", "../data/events.jsonl").resolve()
    if not source.exists():
        return {"inserted": 0, "rejected": 0, "note": "队列尚不存在，等待真实响应"}
    counts = {"inserted": 0, "rejected": 0, "duplicates": 0, "partial_tail": False}
    db = connect(db_path)
    try:
        checkpoint = db.execute("SELECT offset,prefix_hash FROM checkpoints WHERE source=?", (str(source),)).fetchone()
        with source.open("rb") as f:
            offset = checkpoint["offset"] if checkpoint else 0
            if checkpoint and (source.stat().st_size < offset or prefix_hash(f, offset) != checkpoint["prefix_hash"]):
                offset = 0  # truncation/replacement; event IDs still deduplicate
            f.seek(offset)
            while True:
                line = f.readline(2_097_153)
                if not line:
                    break
                if not line.endswith(b"\n"):
                    if len(line) > 2_097_152:
                        raise ValueError("队列行超过上限，请保留原文件并使用新队列")
                    counts["partial_tail"] = True
                    break
                end = f.tell()
                with db:
                    try:
                        e = validate_event(json.loads(line), c, m)
                    except (ValueError, KeyError, TypeError, OverflowError):
                        counts["rejected"] += 1  # no raw payload/error text in logs
                    else:
                        key = "inserted" if write_event(db, e) else "duplicates"
                        counts[key] += 1
                    # Hash once after processing this batch, below. Save an empty hash to force
                    # safe replay after a crash before finalization (dedup preserves atomicity).
                    db.execute("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)", (str(source), end, ""))
                offset = end
            with db:
                db.execute("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?)", (str(source), offset, prefix_hash(f, offset)))
    finally:
        db.close()
    return counts
