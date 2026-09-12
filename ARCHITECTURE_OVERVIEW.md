# Proxy — Architecture Overview

The current, at-a-glance reference: system flow, full feature list, and the complete backend API surface. This is an **index**, not a replacement for the deeper docs — where something needs more explanation, it links out to `details.md` (full build history), `THREAT_MODEL.md` (security design), `glossary.md` (terms), or `learning/` (how-to lessons) rather than repeating them. If this file and one of those ever disagree, the deeper doc is the source of truth — update this one to match.

---

## 1. System Architecture Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (frontend/)                         │
│  ┌────────────────────────┐        ┌──────────────────────────────┐ │
│  │  LEFT: Agent Session    │        │  RIGHT: What Proxy Sees       │ │
│  │  - Task input           │        │  - Live screenshot (updates   │ │
│  │  - Live narration feed  │        │    after every step)          │ │
│  │  - Approve/deny prompts │        │  - Switches to a red          │ │
│  │  - PII input (masked    │        │    "Content Flagged" view     │ │
│  │    for SSN/account #s)  │        │    when the gate blocks       │ │
│  └────────────────────────┘        │    something -- shows the      │ │
│         index.html                  │    actual injected text        │ │
│                                      └──────────────────────────────┘ │
│  Separate page: dashboard.html -- case-worker view of every task     │
│  ever run + its full step-by-step log (text only, no screenshots)    │
└───────────────────────────────┬────────────────────────────────────┘
                                 │  REST (start/approve/provide-pii/log)
                                 │  WebSocket (live event stream)
┌───────────────────────────────▼────────────────────────────────────┐
│                    BACKEND (backend/main.py, FastAPI)                │
│  Drives agent/loop_playwright.py's async generator per task,         │
│  persists events (minus screenshots) to backend/audit_log.py and     │
│  backend/task_index.py, serves the frontend as static files.         │
└───────────────────────────────┬────────────────────────────────────┘
                                 │
┌───────────────────────────────▼────────────────────────────────────┐
│              AGENT LOOP (agent/loop_playwright.py)                   │
│                                                                        │
│   PERCEIVE ──▶ REASON ──▶ GATE ──▶ EXECUTE ──▶ OBSERVE ──▶ (repeat)  │
│                                                                        │
│   Perceive : agent/browser_runtime.py reads the live page (Playwright)│
│   Reason   : agent/reasoner.py -- decide_next_action()                │
│              (currently a mock; Devon's real LLM tool-calling         │
│              replaces this -- see DEVON_ARCHITECTURE.pdf)             │
│   Gate     : policy/gate.py's evaluate() -- see section 3 below       │
│   Execute  : agent/browser_runtime.py performs the real action        │
│   Observe  : screenshot captured, loop continues with new page state  │
└───────────────────────────────┬────────────────────────────────────┘
                                 │
┌───────────────────────────────▼────────────────────────────────────┐
│                  REAL BROWSER (Playwright + headless Chromium)       │
│         demo-sites/clean/application.html                            │
│         demo-sites/poisoned/application.html (3 hidden injections)   │
└──────────────────────────────────────────────────────────────────────┘
```

**Not a fixed script.** Every loop iteration re-decides the next action based on current state -- see `THREAT_MODEL.md`'s "three-layer defense" section for why this matters for the security story, and `glossary.md`'s "Orchestration (as distinct from 'agent')" entry for the underlying distinction.

**The one invariant that holds everywhere:** no action reaches the real browser without `policy.gate.evaluate()` approving it first. See `policy/gate.py`'s own docstring for the full rationale.

A second, simpler loop (`agent/loop.py`, file-based mock, no real browser) still exists purely for testing the reasoning function in isolation without needing Chromium — see `DEVON_ARCHITECTURE.pdf`.

---

## 2. Full Feature List

| Feature | Status | Where |
|---|---|---|
| Real browser automation (Playwright/Chromium) | ✅ Built, tested | `agent/browser_runtime.py`, `agent/loop_playwright.py` |
| Split-screen UI (agent session + live page view) | ✅ Built, tested | `frontend/index.html`, `frontend/style.css` |
| Live screenshot streaming | ✅ Built, tested | `agent/browser_runtime.py::capture_screenshot`, WebSocket events |
| Flagged-content attack view | ✅ Built, tested | `frontend/index.html::showFlaggedContent` |
| Injection scanner (heuristic + LLM-judge) | ✅ Built, tested, real Groq API | `policy/scanner.py` |
| Policy/allowlist gate | ✅ Built, tested | `policy/gate.py`, `policy/rules.yaml` |
| PII-gated human interrupt | ✅ Built, tested (3 execution paths) | `policy/pii.py`, `agent/loop*.py` |
| Human approval flow (e.g. before submit) | ✅ Built, tested | `policy/rules.yaml`, `agent/loop*.py` |
| Audit log per task | ✅ Built, tested | `backend/audit_log.py` |
| Task index / case-worker dashboard | ✅ Built, tested | `backend/task_index.py`, `frontend/dashboard.html` |
| Real LLM agent reasoning | ❌ Not built — mock in place | `agent/reasoner.py` (Devon's scope) |
| Docker packaging | ⚠️ Written, unverified (no Docker on this machine) | `Dockerfile`, `docker-compose.yml` |
| Direct prompt injection defense | 🗺️ Roadmap | `THREAT_MODEL.md` |
| Voice input/narration | 🗺️ Roadmap, deliberately cut | `THREAT_MODEL.md` |
| OAuth-scoped account integrations | 🗺️ Roadmap, deliberately out of scope for now | `THREAT_MODEL.md` |

For the reasoning behind every roadmap/out-of-scope item, see `THREAT_MODEL.md` — nothing there is an oversight, each is a documented decision.

---

## 3. Backend API Surface (current)

All endpoints live in `backend/main.py`. Base URL when running locally: `http://localhost:8000`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Redirects to `/app/index.html` |
| `GET` | `/health` | Liveness check, returns `{"status": "ok"}` |
| `GET` | `/app/*` | Static frontend files (mounted from `frontend/`) |
| `POST` | `/task/start` | Body: `{task: str, site: "clean"\|"poisoned"}` → `{task_id}`. Starts a new task. |
| `WS` | `/ws/{task_id}` | Live event stream for one task (see event contract below) |
| `POST` | `/task/{id}/approve` | Body: `{approved: bool}` → resumes a task paused on an `escalation` event |
| `POST` | `/task/{id}/provide-pii` | Body: `{value: str}` → resumes a task paused on a `pii_required` event. This value is never logged anywhere in this file. |
| `GET` | `/task/{id}/log` | Full audit log for one task (screenshots excluded) — used by the dashboard |
| `GET` | `/tasks` | List of every task ever started, with status — used by the dashboard's list view |

### Event contract (what the WebSocket sends)

Every event is a JSON object with at least a `type` field. Current types:

```
{"type": "narration", "text": "...", "screenshot": "<base64 png>"}
    -- informational; screenshot present on most narration events
       (absent only on the very first "Starting task..." event, before
       the browser has navigated anywhere yet)

{"type": "escalation", "reason": "...", "requires_human_review": bool,
 "blocked": bool, "blocked_pattern": str|null, "screenshot": "<base64>"|absent}
    -- blocked=true: hard stop, nothing to approve, frontend shows the
       flagged-content view instead of the screenshot (no screenshot key)
    -- blocked=false: needs .send()/POST /approve with true/false;
       screenshot IS present (the page as it stood before the paused action)

{"type": "pii_required", "field_id": "...", "mask": bool, "text": "...",
 "screenshot": "<base64>"}
    -- needs POST /provide-pii with the real value; the screenshot is the
       static pre-fill page state, deliberately not updated until resumed

{"type": "done", "text": "..."}
    -- task finished successfully, no further events follow

{"type": "halted", "text": "..."}
    -- task stopped (blocked, stuck, step-budget exceeded, or an error)
```

Screenshots are stripped before anything is written to the audit log (`backend/main.py::log_safe`) — they only ever exist in the live WebSocket stream, never in the persisted JSONL files or the dashboard.

---

## 4. Where to Go Deeper

| Question | Read |
|---|---|
| "Why is the security designed this way?" | `THREAT_MODEL.md` |
| "What was built, when, and how do I know it actually works?" | `details.md` (full history, every entry includes what was tested and how) |
| "What does [term] mean?" | `glossary.md` |
| "How do I pitch this?" | `SLIDE_DECK.md` |
| "What does Devon still need to build?" | `DEVON_ARCHITECTURE.pdf` |
| "How do I learn the underlying concepts (Pydantic, async, tool-use, etc.)?" | `learning/` |
