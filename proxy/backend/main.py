import asyncio
import base64
import sys
import threading
import uuid

from pathlib import Path
from queue import Queue, Empty

if sys.platform == "win32":
    asyncio.set_event_loop_policy(
        asyncio.WindowsProactorEventLoopPolicy()
    )

from dotenv import load_dotenv

load_dotenv(override=True)

from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect
)

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from browser.playwright_controller import PlaywrightController
from perception.page_perception import PagePerception
from agent.agent import Agent
from agent.actions import ActionExecutor

from backend.audit_log import (
    append_event,
    read_log
)

from backend.task_index import (
    register_task,
    update_status,
    list_tasks
)


app = FastAPI(
    title="Proxy backend"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


BASE_DIR = Path(__file__).resolve().parent.parent


_SITE_PATHS = {
    "clean": (
        BASE_DIR
        / "demo-sites"
        / "clean"
        / "application.html"
    ),

    "poisoned": (
        BASE_DIR
        / "demo-sites"
        / "poisoned"
        / "application.html"
    )
}


_DEMO_DOMAIN = "benefits-demo.local"


_tasks = {}


class TaskState:

    def __init__(
        self,
        task_id,
        task,
        site,
        html_path
    ):

        self.task_id = task_id

        self.task = task

        self.site = site

        self.html_path = html_path

        self.browser = None

        self.perception = None

        self.executor = None

        self.agent = None

        self.interrupt_event = threading.Event()

        self.event_queue = Queue()

        self.thread = None

        self.running = False

        self.interrupted = False

        self.finished = False

        self.status = "created"

        self.lock = threading.Lock()

        self.cdp_streaming = False


class StartTaskRequest(BaseModel):

    task: str

    site: str = "clean"


class ApproveRequest(BaseModel):

    approved: bool


class ProvidePiiRequest(BaseModel):

    value: str


@app.get("/health")
def health():

    return {
        "status": "ok"
    }


@app.get("/")
def root():

    return RedirectResponse(
        url="/app/index.html"
    )


@app.post("/task/start")
def start_task(
    req: StartTaskRequest
):

    if req.site not in _SITE_PATHS:

        return {
            "error": (
                f"unknown site '{req.site}', "
                f"expected one of {list(_SITE_PATHS)}"
            )
        }

    html_path = _SITE_PATHS[req.site]

    if not html_path.exists():

        return {
            "error": (
                f"Demo page not found: "
                f"{html_path}"
            )
        }

    task_id = str(
        uuid.uuid4()
    )

    state = TaskState(
        task_id=task_id,
        task=req.task,
        site=req.site,
        html_path=html_path
    )

    _tasks[task_id] = state

    register_task(
        task_id,
        req.task,
        req.site
    )

    return {
        "task_id": task_id
    }


@app.get("/tasks")
def get_tasks():

    return {
        "tasks": list_tasks()
    }


@app.get("/task/{task_id}/log")
def get_log(
    task_id: str
):

    if task_id not in _tasks:

        return {
            "error": "unknown task_id"
        }

    return {
        "events": read_log(
            task_id
        )
    }


def make_cdp_callback(
    state
):

    def on_frame(
        frame_data
    ):

        if not state.cdp_streaming:
            return

        if not frame_data:
            return

        state.event_queue.put(
            {
                "type": "browser_frame",
                "data": frame_data
            }
        )

    return on_frame


def make_callback(
    state
):

    def callback(event):

        if not isinstance(event, dict):
            return

        state.event_queue.put(
            event
        )

    return callback


def start_cdp_stream(
    state
):

    if state.browser is None:
        return

    if state.cdp_streaming:
        return

    try:

        callback = make_cdp_callback(
            state
        )

        state.browser.start_cdp_stream(
            callback
        )

        state.cdp_streaming = True

        state.event_queue.put(
            {
                "type": "cdp_started",
                "text": "Live browser stream started."
            }
        )

    except Exception as e:

        state.cdp_streaming = False

        state.event_queue.put(
            {
                "type": "cdp_error",
                "text": (
                    "Browser live stream could not start: "
                    f"{e}"
                )
            }
        )


def stop_cdp_stream(
    state
):

    if state.browser is None:
        return

    if not state.cdp_streaming:
        return

    try:

        state.browser.stop_cdp_stream()

    except Exception:
        pass

    state.cdp_streaming = False


def run_agent_thread(
    state
):

    try:

        state.running = True

        state.status = "running"

        state.browser = PlaywrightController()

        state.perception = PagePerception(
            state.browser
        )

        state.executor = ActionExecutor(
            state.browser,
            state.perception
        )

        state.browser.navigate(
            state.html_path.as_uri()
        )

        state.agent = Agent(
            state.perception,
            state.executor,
            state.task
        )

        callback = make_callback(
            state
        )

        state.event_queue.put(
            {
                "type": "status",
                "status": "running",
                "text": "Proxy started."
            }
        )

        start_cdp_stream(
            state
        )

        completed = state.agent.run_with_callback(
            callback=callback,
            interrupt_event=state.interrupt_event
        )

        if state.interrupt_event.is_set():

            state.interrupted = True

            state.running = False

            state.status = "interrupted"

            state.event_queue.put(
                {
                    "type": "interrupted",
                    "text": (
                        "Agent interrupted. "
                        "Browser control has been handed "
                        "to the user."
                    )
                }
            )

        elif completed:

            state.finished = True

            state.running = False

            state.status = "done"

            state.event_queue.put(
                {
                    "type": "done",
                    "text": "Agent finished the task."
                }
            )

        else:

            state.running = False

            if state.status == "running":

                state.status = "halted"

                state.event_queue.put(
                    {
                        "type": "halted",
                        "text": (
                            "Agent stopped without "
                            "completing the task."
                        )
                    }
                )

    except Exception as e:

        state.running = False

        state.status = "halted"

        state.event_queue.put(
            {
                "type": "halted",
                "text": (
                    f"Unexpected error: {e}"
                )
            }
        )

    finally:

        if state.finished:

            stop_cdp_stream(
                state
            )

            try:

                if state.browser:

                    state.browser.close()

            except Exception:
                pass


def start_agent(
    state
):

    if state.thread is not None:
        return

    state.thread = threading.Thread(
        target=run_agent_thread,
        args=(state,),
        daemon=True
    )

    state.thread.start()


@app.post("/task/{task_id}/interrupt")
def interrupt_task(
    task_id: str
):

    state = _tasks.get(
        task_id
    )

    if state is None:

        return {
            "ok": False,
            "error": "unknown task_id"
        }

    with state.lock:

        if state.finished:

            return {
                "ok": False,
                "error": "task already finished"
            }

        if state.interrupted:

            return {
                "ok": True,
                "status": "interrupted"
            }

        state.interrupt_event.set()

        state.interrupted = True

        state.running = False

        state.status = "interrupted"

    state.event_queue.put(
        {
            "type": "interrupt_requested",
            "text": "Interrupt requested."
        }
    )

    return {
        "ok": True,
        "status": "interrupted"
    }


@app.post("/task/{task_id}/resume")
def resume_task(
    task_id: str
):

    state = _tasks.get(
        task_id
    )

    if state is None:

        return {
            "ok": False,
            "error": "unknown task_id"
        }

    with state.lock:

        if state.finished:

            return {
                "ok": False,
                "error": "task already finished"
            }

        if state.agent is None:

            return {
                "ok": False,
                "error": "agent has not started"
            }

        if not state.interrupted:

            return {
                "ok": False,
                "error": "task is not interrupted"
            }

        state.interrupt_event.clear()

        state.interrupted = False

        state.running = True

        state.status = "running"

    state.event_queue.put(
        {
            "type": "resumed",
            "text": (
                "Control returned to Proxy. "
                "Proxy is inspecting the current page."
            )
        }
    )

    thread = threading.Thread(
        target=resume_agent_thread,
        args=(state,),
        daemon=True
    )

    state.thread = thread

    thread.start()

    return {
        "ok": True,
        "status": "running"
    }


def resume_agent_thread(
    state
):

    try:

        callback = make_callback(
            state
        )

        start_cdp_stream(
            state
        )

        completed = state.agent.resume_from_current_state(
            callback=callback,
            interrupt_event=state.interrupt_event
        )

        if state.interrupt_event.is_set():

            state.interrupted = True

            state.running = False

            state.status = "interrupted"

            state.event_queue.put(
                {
                    "type": "interrupted",
                    "text": (
                        "Agent interrupted. "
                        "Browser control returned "
                        "to the user."
                    )
                }
            )

        elif completed:

            state.finished = True

            state.running = False

            state.status = "done"

            state.event_queue.put(
                {
                    "type": "done",
                    "text": "Agent finished the task."
                }
            )

        else:

            state.running = False

            if state.status == "running":

                state.status = "halted"

                state.event_queue.put(
                    {
                        "type": "halted",
                        "text": (
                            "Agent stopped without "
                            "completing the task."
                        )
                    }
                )

    except Exception as e:

        state.running = False

        state.status = "halted"

        state.event_queue.put(
            {
                "type": "halted",
                "text": (
                    f"Unexpected error: {e}"
                )
            }
        )

    finally:

        if state.finished:

            stop_cdp_stream(
                state
            )

            try:

                if state.browser:

                    state.browser.close()

            except Exception:
                pass


@app.post("/task/{task_id}/approve")
def approve_task(
    task_id: str,
    req: ApproveRequest
):

    state = _tasks.get(
        task_id
    )

    if state is None:

        return {
            "ok": False,
            "error": "unknown task_id"
        }

    if state.agent is None:

        return {
            "ok": False,
            "error": "agent has not started"
        }

    state.agent.set_approval(
        req.approved
    )

    return {
        "ok": True
    }


@app.post("/task/{task_id}/provide-pii")
def provide_pii(
    task_id: str,
    req: ProvidePiiRequest
):

    state = _tasks.get(
        task_id
    )

    if state is None:

        return {
            "ok": False,
            "error": "unknown task_id"
        }

    if state.agent is None:

        return {
            "ok": False,
            "error": "agent has not started"
        }

    state.agent.set_pii(
        req.value
    )

    return {
        "ok": True
    }


@app.websocket("/ws/{task_id}")
async def task_socket(
    websocket: WebSocket,
    task_id: str
):

    await websocket.accept()

    state = _tasks.get(
        task_id
    )

    if state is None:

        await websocket.send_json(
            {
                "type": "error",
                "text": "unknown task_id"
            }
        )

        await websocket.close()

        return

    if state.thread is None:

        start_agent(
            state
        )

    try:

        while True:

            try:

                event = state.event_queue.get(
                    timeout=0.1
                )

            except Empty:

                await asyncio.sleep(
                    0.05
                )

                if (
                    state.finished
                    and state.event_queue.empty()
                ):

                    break

                continue

            if not isinstance(
                event,
                dict
            ):
                continue

            event_type = event.get(
                "type"
            )

            if event_type == "browser_frame":

                try:

                    await websocket.send_json(
                        event
                    )

                except Exception:

                    break

                continue

            if event_type == "cdp_started":

                try:

                    await websocket.send_json(
                        event
                    )

                except Exception:

                    break

                continue

            if event_type == "cdp_error":

                append_event(
                    task_id,
                    event
                )

                try:

                    await websocket.send_json(
                        event
                    )

                except Exception:

                    break

                continue

            safe_event = dict(
                event
            )

            append_event(
                task_id,
                safe_event
            )

            try:

                await websocket.send_json(
                    safe_event
                )

            except Exception:

                break

            if event_type == "done":

                state.finished = True

                state.running = False

                state.status = "done"

                break

            elif event_type == "halted":

                state.running = False

                if state.status != "interrupted":

                    state.status = "halted"

            elif event_type == "interrupted":

                state.running = False

                state.interrupted = True

                state.status = "interrupted"

            elif event_type == "needs_user":

                state.running = False

                state.status = "needs_user"

            elif event_type == "pii_required":

                state.running = False

                state.status = "waiting_for_pii"

    except WebSocketDisconnect:

        pass

    except Exception as e:

        error_event = {
            "type": "halted",
            "text": (
                f"Unexpected error: {e}"
            )
        }

        try:

            append_event(
                task_id,
                error_event
            )

            await websocket.send_json(
                error_event
            )

        except Exception:
            pass


_frontend_dir = (
    BASE_DIR
    / "frontend"
)


if _frontend_dir.exists():

    app.mount(
        "/app",
        StaticFiles(
            directory=str(
                _frontend_dir
            ),
            html=True
        ),
        name="frontend"
    )
