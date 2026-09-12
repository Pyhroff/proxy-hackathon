"""
Quick smoke test for the backend WebSocket, driving a full task without
the frontend at all. Requires the backend running (uvicorn backend.main:app).

Run with: python eval/ws_smoke_test.py
"""

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
            json={"task": "Complete the housing benefits application", "site": "clean"},
        )
        task_id = resp.json()["task_id"]
        print("task_id:", task_id)

    async with websockets.connect(f"{WS_BASE}/ws/{task_id}") as ws:
        async for raw in ws:
            event = json.loads(raw)
            print(event)
            if event["type"] == "escalation" and not event.get("blocked"):
                async with httpx.AsyncClient() as client:
                    await client.post(f"{BASE}/task/{task_id}/approve", json={"approved": True})
            if event["type"] in ("done", "halted"):
                break

    async with httpx.AsyncClient() as client:
        log = await client.get(f"{BASE}/task/{task_id}/log")
        print("\naudit log entries:", len(log.json()["events"]))


if __name__ == "__main__":
    asyncio.run(main())
