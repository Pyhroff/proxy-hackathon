"""
FastAPI backend -- wires the frontend to agent/loop_playwright.py's real
Playwright-backed generator and persists everything to the audit log.
This is Person 4's territory; built here as a working, self-contained
system since the team isn't covering that role separately.

Runs the REAL browser now (switched from the mock agent/loop.py as part
of the split-screen build, see details.md) -- the mock version still
exists for Devon's isolated reasoning tests (eval/run_loop_demo.py), but
the live app now drives real Playwright end to end, since the
split-screen's right panel needs a real screenshot to show.

Run with: uvicorn backend.main:app --port 8000   (see note below about --reload on Windows)
Then open: http://localhost:8000/app/index.html      (task runner)
       or: http://localhost:8000/app/dashboard.html   (case worker view)

WINDOWS + --reload NOTE: don't use --reload for the actual demo. uvicorn's
--reload spawns the real server as a subprocess via WatchFiles, and on
Windows this can reset the asyncio event loop to the Selector
implementation, which does NOT support subprocess creation. Playwright
needs to launch a real Chromium subprocess -- under Selector, that call
raises a bare NotImplementedError with an EMPTY message, which shows up
in the UI as "Unexpected error: " with nothing after the colon. This bug
was found and confirmed on a real Windows machine, not hypothetical --
see details.md. The explicit policy set below is a defensive fix for
this regardless of how the server is started; dropping --reload is the
other half of the fix (and reload isn't needed for a demo anyway -- it's
a dev-only file-watching convenience).

Endpoints:
  POST /task/start              -> {task, site} -> {task_id}
  WS   /ws/{task_id}             -> streams narration/escalation/pii_required/done events
  POST /task/{id}/approve        -> {approved: bool} -> resumes a paused task
  POST /task/{id}/provide-pii    -> {value: str} -> resumes a task paused on a PII field
                                     (see policy/pii.py, THREAT_MODEL.md "PII Handling" --
                                     this value is NEVER written to the audit log or any
                                     log line in this file; it goes straight from this
                                     request body into the agent loop's execute step)
  GET  /task/{id}/log            -> full audit log for the caregiver dashboard
  GET  /tasks                    -> list of every task ever started, for the dashboard

Concurrency note: this uses one asyncio.Queue per in-flight task to
carry the human approve/deny decision from the REST endpoint into the
waiting WebSocket handler. This is a hackathon-scale simplification --
fine for one browser tab driving one task at a time, not meant to be a
production-grade task queue.
"""

import asyncio
import os
import sys
import uuid

# Must run before anything else creates an event loop. See the WINDOWS +
# --reload note above -- Playwright needs subprocess support (to launch
# Chromium), which the default asyncio Selector loop on Windows lacks.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from dotenv import load_dotenv

load_dotenv()  # must run before any policy/scanner.py code checks os.environ for GROQ_API_KEY

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.loop_playwright import run_task_events_playwright
from backend.audit_log import append_event, read_log
from backend.task_index import register_task, update_status, list_tasks

app = FastAPI(title="Proxy backend")

# Wide-open CORS for hackathon convenience -- tighten before this is
# ever exposed beyond localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_SITE_PATHS = {
    "clean": "demo-sites/clean/application.html",
    "poisoned": "demo-sites/poisoned/application.html",
}
_DEMO_DOMAIN = "benefits-demo.local"

_tasks: dict[str, dict] = {}
_approval_queues: dict[str, "asyncio.Queue[bool]"] = {}
_pii_queues: dict[str, "asyncio.Queue[str]"] = {}


class StartTaskRequest(BaseModel):
    task: str
    site: str = "clean"  # "clean" or "poisoned" -- which demo site to run against


class ApproveRequest(BaseModel):
    approved: bool


class ProvidePiiRequest(BaseModel):
    value: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return RedirectResponse(url="/app/index.html")


@app.post("/task/start")
def start_task(req: StartTaskRequest):
    if req.site not in _SITE_PATHS:
        return {"error": f"unknown site '{req.site}', expected one of {list(_SITE_PATHS)}"}

    task_id = str(uuid.uuid4())
    _tasks[task_id] = {
        "task": req.task,
        "html_path": _SITE_PATHS[req.site],
        "domain": _DEMO_DOMAIN,
    }
    register_task(task_id, req.task, req.site)
    return {"task_id": task_id}


@app.get("/tasks")
def get_tasks():
    return {"tasks": list_tasks()}


@app.post("/task/{task_id}/approve")
async def approve_task(task_id: str, req: ApproveRequest):
    queue = _approval_queues.setdefault(task_id, asyncio.Queue())
    await queue.put(req.approved)
    return {"ok": True}


@app.post("/task/{task_id}/provide-pii")
async def provide_pii(task_id: str, req: ProvidePiiRequest):
    # req.value is intentionally never passed to append_event() or any
    # logging call anywhere in this function -- it goes directly into the
    # queue the WebSocket handler is awaiting on, and nowhere else.
    queue = _pii_queues.setdefault(task_id, asyncio.Queue())
    await queue.put(req.value)
    return {"ok": True}


@app.get("/task/{task_id}/log")
def get_log(task_id: str):
    return {"events": read_log(task_id)}


async def _wait_for_approval(task_id: str) -> bool:
    queue = _approval_queues.setdefault(task_id, asyncio.Queue())
    return await queue.get()


async def _wait_for_pii_value(task_id: str) -> str:
    queue = _pii_queues.setdefault(task_id, asyncio.Queue())
    return await queue.get()


@app.websocket("/ws/{task_id}")
async def task_socket(websocket: WebSocket, task_id: str):
    await websocket.accept()

    info = _tasks.get(task_id)
    if not info:
        await websocket.send_json({"type": "error", "text": "unknown task_id"})
        await websocket.close()
        return

    # send_lock: ADDITIVE for the CDP live-view feature below. Two
    # independent code paths now write to this one WebSocket -- the main
    # loop (below) and frame_sink (fired from CDP frame callbacks, see
    # agent/browser_runtime.py::start_cdp_stream). Concurrent unlocked
    # sends on the same WebSocket can interleave/corrupt frames on the
    # wire; the lock serializes them. The original single-writer code
    # path (no frame_sink) never needed this, since only the main loop
    # ever wrote to the socket.
    send_lock = asyncio.Lock()

    async def frame_sink(jpeg_b64: str) -> None:
        # Deliberately NOT passed through append_event()/log_safe() --
        # continuous CDP frames are a live-view-only channel, same
        # principle as the existing per-step "screenshot" field already
        # being excluded from the audit log (see log_safe below).
        async with send_lock:
            try:
                await websocket.send_json({"type": "cdp_frame", "data": jpeg_b64})
            except Exception:
                pass

    agen = run_task_events_playwright(
        info["task"], info["html_path"], info["domain"], frame_sink=frame_sink
    )
    final_status = "halted"  # default if anything goes wrong before a clean "done"

    # run_task_events_playwright() is a native async generator -- driven
    # with .asend()/.athrow(), not next()/.send(). It handles its own
    # protection against blocking the event loop internally (see
    # agent/loop_playwright.py's _evaluate_safely) -- no run_in_executor
    # wrapping needed here anymore, unlike the old mock-loop version.
    async def advance(send_value=None):
        return await agen.asend(send_value)

    def log_safe(event: dict) -> dict:
        # Screenshots are large base64 blobs, useful live in the
        # WebSocket stream but not worth bloating the audit log file or
        # the case-worker dashboard with -- strip before persisting.
        return {k: v for k, v in event.items() if k != "screenshot"}

    try:
        event = await advance(None)
        while True:
            append_event(task_id, log_safe(event))
            async with send_lock:
                await websocket.send_json(event)

            if event["type"] == "done":
                final_status = "done"
                break
            if event["type"] == "halted":
                final_status = "halted"
                break

            if event["type"] == "escalation" and not event.get("blocked"):
                approved = await _wait_for_approval(task_id)
                event = await advance(approved)
            elif event["type"] == "pii_required":
                pii_value = await _wait_for_pii_value(task_id)
                event = await advance(pii_value)
            else:
                event = await advance(None)
    except StopAsyncIteration:
        pass
    except WebSocketDisconnect:
        pass
    except Exception as e:
        # Anything else -- a Groq API outage, a bug in the loop, a file
        # read error -- would otherwise kill the connection silently with
        # no explanation on screen. Tell the user something specific
        # instead of leaving them staring at a dead connection during a
        # live demo. The scanner's own fail-closed behavior (see
        # policy/scanner.py) already handles most API failures gracefully
        # before they'd ever reach here -- this is the last-resort catch
        # for anything that doesn't.
        error_event = {"type": "halted", "text": f"Unexpected error: {e}"}
        append_event(task_id, error_event)
        try:
            async with send_lock:
                await websocket.send_json(error_event)
        except Exception:
            pass  # connection may already be gone
    finally:
        # CRITICAL: agen's `finally: await close_browser(...)` (in
        # agent/loop_playwright.py) only runs on the generator's NEXT
        # advance -- but the loop above `break`s the instant it sees
        # "done"/"halted" and never advances again. Without this
        # explicit aclose(), that finally block never executes, the
        # headless Chromium instance for this task is NEVER closed, and
        # since this server process stays alive for the whole demo
        # session, every single task run silently leaves one more
        # orphaned browser process behind. Found via a real hang while
        # testing (see details.md) -- not a hypothetical concern.
        try:
            await agen.aclose()
        except Exception:
            pass
        update_status(task_id, final_status)
        _approval_queues.pop(task_id, None)  # avoid leaking one queue per task forever
        _pii_queues.pop(task_id, None)
        try:
            await websocket.close()
        except Exception:
            pass  # already closed, e.g. after WebSocketDisconnect


# Serve the frontend as static files so the whole system is one command
# to run -- no separate static-file server needed. Mounted at /app
# (not "/") so it doesn't shadow the API routes above.
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
app.mount("/app", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
