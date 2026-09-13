"""
Drives a full task through the REAL backend (WebSocket + REST), same as
ws_smoke_test.py, but specifically to prove the PII-gating endpoint
(/task/{id}/provide-pii) works over the actual network stack, not just
inside the generator directly.

Run with: python eval/ws_smoke_test_pii.py  (backend must be running)
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

    saw_pii_prompt = False
    async with websockets.connect(f"{WS_BASE}/ws/{task_id}") as ws:
        async for raw in ws:
            event = json.loads(raw)
            print(event)

            if event["type"] == "pii_required":
                saw_pii_prompt = True
                assert event["field_id"] == "dob"
                assert "value" not in event  # the event itself must never carry a value
                async with httpx.AsyncClient() as client:
                    await client.post(f"{BASE}/task/{task_id}/provide-pii", json={"value": "1990-01-01"})

            if event["type"] == "escalation" and not event.get("blocked"):
                async with httpx.AsyncClient() as client:
                    await client.post(f"{BASE}/task/{task_id}/approve", json={"approved": True})

            if event["type"] in ("done", "halted"):
                break

    assert saw_pii_prompt, "expected a pii_required event for the 'dob' field, never saw one"

    async with httpx.AsyncClient() as client:
        log = await client.get(f"{BASE}/task/{task_id}/log")
        events = log.json()["events"]
        raw_log_text = json.dumps(events)
        assert "1990-01-01" not in raw_log_text, "PII VALUE LEAKED INTO THE AUDIT LOG"
        print(f"\naudit log entries: {len(events)}")
        print("Confirmed: the actual DOB value does not appear anywhere in the audit log.")


if __name__ == "__main__":
    asyncio.run(main())
