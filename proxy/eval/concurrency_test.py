"""
Fires several tasks at the backend concurrently and confirms every one
of them ends up correctly recorded in the task index -- a real test for
the register_task()/update_status() race condition fix in
backend/task_index.py, not just a code-review argument.

Run with: python eval/concurrency_test.py  (backend must be running)
"""

import asyncio
import json

import httpx
import websockets

BASE = "http://localhost:8000"
WS_BASE = "ws://localhost:8000"
N = 8  # concurrent tasks -- enough to make a race condition likely if one exists


async def run_one(i: int, client: httpx.AsyncClient):
    resp = await client.post(f"{BASE}/task/start", json={"task": f"concurrency test #{i}", "site": "clean"})
    task_id = resp.json()["task_id"]

    async with websockets.connect(f"{WS_BASE}/ws/{task_id}") as ws:
        async for raw in ws:
            event = json.loads(raw)
            if event["type"] == "escalation" and not event.get("blocked"):
                await client.post(f"{BASE}/task/{task_id}/approve", json={"approved": True})
            if event["type"] in ("done", "halted"):
                break
    return task_id


async def main():
    async with httpx.AsyncClient(timeout=60) as client:
        task_ids = await asyncio.gather(*[run_one(i, client) for i in range(N)])

        resp = await client.get(f"{BASE}/tasks")
        all_tasks = {t["task_id"]: t for t in resp.json()["tasks"]}

        missing = [tid for tid in task_ids if tid not in all_tasks]
        wrong_status = [tid for tid in task_ids if tid in all_tasks and all_tasks[tid]["status"] != "done"]

        print(f"Started {N} tasks concurrently.")
        print(f"Missing from index entirely: {len(missing)} (want: 0)")
        print(f"Present but wrong status: {len(wrong_status)} (want: 0)")
        if missing:
            print("  missing:", missing)
        if wrong_status:
            for tid in wrong_status:
                print(f"  {tid}: status={all_tasks[tid]['status']}")


if __name__ == "__main__":
    asyncio.run(main())
