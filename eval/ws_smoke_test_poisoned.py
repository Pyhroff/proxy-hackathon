"""Same as ws_smoke_test.py but against the poisoned site -- this is the
path with the most content to scan (most judge API calls), so it's the
best stress test for the event-loop-blocking fix in backend/main.py."""

import asyncio
import json

import httpx
import websockets

BASE = "http://localhost:8000"
WS_BASE = "ws://localhost:8000"


async def main():
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE}/task/start",
            json={"task": "Complete the housing benefits application", "site": "poisoned"},
        )
        task_id = resp.json()["task_id"]
        print("task_id:", task_id)

    async with websockets.connect(f"{WS_BASE}/ws/{task_id}") as ws:
        async for raw in ws:
            event = json.loads(raw)
            print(event)
            if event["type"] in ("done", "halted"):
                break

    async with httpx.AsyncClient() as client:
        log = await client.get(f"{BASE}/task/{task_id}/log")
        events = log.json()["events"]
        print("\naudit log entries:", len(events))
        print("last event type:", events[-1]["type"] if events else None)


if __name__ == "__main__":
    asyncio.run(main())
