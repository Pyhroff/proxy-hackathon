"""
Lightweight persisted index of every task ever started -- separate from
the per-task audit log (backend/audit_log.py), which stores the
step-by-step events for ONE task. This file answers "what tasks exist at
all," which the case-worker dashboard needs to list them.

Same "plain JSON file, no real database" scope choice as audit_log.py --
fine at hackathon scale, swap for SQLite later if needed.
"""

import json
import os
import threading
from datetime import datetime, timezone

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_INDEX_PATH = os.path.join(_DATA_DIR, "tasks_index.json")

# Guards the load-modify-save sequence in register_task()/update_status()
# so two tasks finishing at the same moment can't race and clobber each
# other's write (last-write-wins with no lock would silently drop one
# task's status update). A plain threading.Lock is fine here even though
# most callers run on the asyncio event loop -- the critical section is
# just a small synchronous file read+write, held for microseconds, not
# an async-aware lock's worth of complexity.
_lock = threading.Lock()


def _load() -> dict:
    if not os.path.exists(_INDEX_PATH):
        return {}
    with open(_INDEX_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save(index: dict) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)


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
    """status: 'running' | 'done' | 'halted'"""
    with _lock:
        index = _load()
        if task_id in index:
            index[task_id]["status"] = status
            _save(index)


def list_tasks() -> list[dict]:
    index = _load()
    return sorted(index.values(), key=lambda t: t["created_at"], reverse=True)
