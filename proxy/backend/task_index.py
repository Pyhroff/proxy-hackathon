"""Small JSON task index for the dashboard."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent / "data"
_INDEX_PATH = _DATA_DIR / "tasks_index.json"
_lock = threading.Lock()


def _load() -> dict:
    if not _INDEX_PATH.exists():
        return {}
    with _INDEX_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _save(index: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _INDEX_PATH.open("w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=2)


def register_task(task_id: str, task_description: str, site: str) -> None:
    with _lock:
        index = _load()
        index[task_id] = {
            "task_id": task_id,
            "task_description": task_description,
            "site": site,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
        }
        _save(index)


def update_status(task_id: str, status: str) -> None:
    with _lock:
        index = _load()
        if task_id in index:
            index[task_id]["status"] = status
            _save(index)


def list_tasks() -> list[dict]:
    return sorted(_load().values(), key=lambda task: task["created_at"], reverse=True)
