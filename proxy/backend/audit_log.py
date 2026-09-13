"""
Append-only audit log -- one JSON-lines file per task under backend/data/.
This is what the caregiver/case-worker dashboard reads from. Kept as
plain files instead of a database because a hackathon-scale demo doesn't
need one; swap for SQLite later if querying across tasks becomes useful.
"""

import json
import os
from datetime import datetime, timezone

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def _log_path(task_id: str) -> str:
    os.makedirs(_DATA_DIR, exist_ok=True)
    return os.path.join(_DATA_DIR, f"{task_id}.jsonl")


def append_event(task_id: str, event: dict) -> None:
    record = {**event, "timestamp": datetime.now(timezone.utc).isoformat()}
    with open(_log_path(task_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def read_log(task_id: str) -> list[dict]:
    path = _log_path(task_id)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
