# Proxy

An AI agent that completes real, multi-step web tasks on a user's behalf — with a security layer that detects and blocks prompt-injection attempts hidden in page content before it can hijack the agent, and a human-gated flow for sensitive fields (SSN, DOB, account numbers) that keeps those values out of the AI's context entirely.

Built for the AI Builders Hackathon 2026.

## What it does

Give Proxy a plain-language task (e.g. "Complete the housing benefits application") and it will:

1. Read the real page and decide its next action dynamically — no fixed script
2. Show a split-screen view: your conversation with the agent on the left, a live view of the actual page on the right
3. Pause for your approval before high-consequence actions (like submitting a form)
4. Pause and ask *you* to type sensitive fields (SSN, DOB, account numbers) directly — the AI never sees or stores that value
5. Detect and block indirect prompt injection hidden in page content (invisible text, white-on-white styling, malicious alt attributes) before it can manipulate the agent

## Architecture

```
Frontend (split-screen UI)
        │  WebSocket / REST
Backend (FastAPI)
        │
Agent loop: Perceive → Reason → Gate → Execute → Observe
        │
Real browser (Playwright + Chromium)
```

Every proposed action passes through a policy gate (allowlist + injection scanner) before it's allowed to execute. See `THREAT_MODEL.md` and `ARCHITECTURE_OVERVIEW.md` for the full design.

## Setup

```bash
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env   # add your GROQ_API_KEY
```

## Run

```bash
uvicorn backend.main:app --port 8000
```

Open `http://localhost:8000`.

**Windows:** don't use `--reload` — see `backend/main.py` for why (a Playwright/asyncio event-loop compatibility issue).

## Project structure

```
agent/          agent loop, reasoning, browser automation
policy/         security gate, injection scanner, PII field handling
backend/        FastAPI server, WebSocket streaming, audit log
frontend/       task runner UI + case-worker dashboard
demo-sites/     clean and injection-seeded demo forms
eval/           tests and standalone demo/verification scripts
```

## Tests

```bash
pytest eval/test_gate.py eval/test_pii.py -v
```
