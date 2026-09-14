"""Append-only JSONL audit log for task events."""

import json
from datetime import datetime, timezone
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent / "data"


def _log_path(task_id: str) -> Path:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    return _DATA_DIR / f"{task_id}.jsonl"


def append_event(task_id: str, event: dict) -> None:
    record = {**event, "timestamp": datetime.now(timezone.utc).isoformat()}
    with _log_path(task_id).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def read_log(task_id: str) -> list[dict]:
    path = _log_path(task_id)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]
