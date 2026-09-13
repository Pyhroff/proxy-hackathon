import asyncio
import threading
import uuid
from dotenv import load_dotenv
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from proxy.browser.playwright_controller import PlaywrightController
from proxy.perception.page_perception import PagePerception
from proxy.agent.agent import Agent
from proxy.agent.actions import ActionExecutor


# ================================================================
# PATHS
# ================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

FRONTEND_DIR = PROJECT_ROOT / "frontend"

PROXY_DIR = Path(__file__).resolve().parent

DEMO_SITES_DIR = PROXY_DIR / "demo-sites"

load_dotenv(FRONTEND_DIR / ".env")


# ================================================================
# APP
# ================================================================

app = FastAPI()

tasks = {}


# ================================================================
# STATIC FRONTEND
# ================================================================

if FRONTEND_DIR.exists():

    app.mount(
        "/static",
        StaticFiles(directory=FRONTEND_DIR),
        name="static"
    )


# ================================================================
# TASK
# ================================================================

class Task:

    def __init__(
        self,
        task_id,
        goal,
        site
    ):

        self.task_id = task_id
        self.goal = goal
        self.site = site

        self.browser = None
        self.perception = None
        self.executor = None
        self.agent = None

        self.websocket = None

        self.thread = None

        self.loop = None

        self.running = False

        self.interrupt_event = threading.Event()


# ================================================================
# SEND EVENT TO FRONTEND
# ================================================================

def send_to_frontend(task, event):

    if task.websocket is None:
        print("No WebSocket connected")
        return

    if task.loop is None:
        print("No event loop available")
        return

    async def send():

        try:

            await task.websocket.send_json(event)

        except Exception as e:

            print(
                "WebSocket send error:",
                e
            )


    asyncio.run_coroutine_threadsafe(
        send(),
        task.loop
    )


# ================================================================
# CDP FRAME CALLBACK
# ================================================================
def browser_frame_callback(task, frame_data):

    print("Sending CDP frame to frontend")

    send_to_frontend(
        task,
        {
            "type": "browser_frame",
            "data": frame_data
        }
    )


# ================================================================
# RUN AGENT
# ================================================================

def run_agent(task):

    try:

        task.running = True


        # --------------------------------------------------------
        # CREATE BROWSER
        # --------------------------------------------------------

        task.browser = PlaywrightController()


        # --------------------------------------------------------
        # FIND DEMO SITE
        # --------------------------------------------------------

        demo_root = (
            DEMO_SITES_DIR
            / task.site
        )


        test_page = (
            demo_root
            / "index.html"
        )


        if not test_page.exists():

            raise FileNotFoundError(
                f"Demo page not found: {test_page}"
            )


        # --------------------------------------------------------
        # OPEN DEMO PAGE
        # --------------------------------------------------------

        task.browser.navigate(
            test_page.as_uri()
        )


        # --------------------------------------------------------
        # PERCEPTION
        # --------------------------------------------------------

        task.perception = PagePerception(
            task.browser
        )


        # --------------------------------------------------------
        # EXECUTOR
        # --------------------------------------------------------

        task.executor = ActionExecutor(
            task.browser,
            task.perception
        )


        # --------------------------------------------------------
        # AGENT
        # --------------------------------------------------------

        task.agent = Agent(
            task.perception,
            task.executor,
            task.goal
        )


        # --------------------------------------------------------
        # START CDP STREAM
        # --------------------------------------------------------

        task.browser.start_cdp_stream(
            lambda frame:
                browser_frame_callback(
                    task,
                    frame
                )
        )


        # --------------------------------------------------------
        # INFORM FRONTEND
        # --------------------------------------------------------

        send_to_frontend(
            task,
            {
                "type": "narration",
                "text": "Browser connected. Proxy is ready."
            }
        )


        # --------------------------------------------------------
        # RUN AGENT
        # --------------------------------------------------------

        task.agent.run_with_callback(

            callback=lambda event:
                send_to_frontend(
                    task,
                    event
                ),

            interrupt_event=
                task.interrupt_event
        )


    except Exception as e:

        send_to_frontend(
            task,
            {
                "type": "halted",
                "text": f"Proxy error: {str(e)}"
            }
        )


    finally:

        task.running = False


        if task.browser:

            try:

                task.browser.close()

            except Exception:

                pass


# ================================================================
# START TASK
# ================================================================

@app.post("/task/start")
async def start_task(
    data: dict
):

    task_id = str(
        uuid.uuid4()
    )


    task = Task(

        task_id,

        data.get(
            "task",
            ""
        ),

        data.get(
            "site",
            "clean"
        )

    )


    task.loop = (
        asyncio.get_running_loop()
    )


    tasks[task_id] = task


    return {
        "task_id": task_id
    }


# ================================================================
# WEBSOCKET
# ================================================================

@app.websocket("/ws/{task_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    task_id: str
):

    await websocket.accept()


    if task_id not in tasks:

        await websocket.close()

        return


    task = tasks[task_id]


    task.websocket = websocket

    task.loop = (
        asyncio.get_running_loop()
    )


    # ------------------------------------------------------------
    # START AGENT AFTER WEBSOCKET EXISTS
    # ------------------------------------------------------------

    task.thread = threading.Thread(

        target=run_agent,

        args=(task,),

        daemon=True
    )


    task.thread.start()


    try:

        while True:

            await websocket.receive_text()


    except Exception:

        task.interrupt_event.set()


    finally:

        task.websocket = None


# ================================================================
# APPROVAL
# ================================================================

@app.post("/task/{task_id}/approve")
async def approve_task(
    task_id: str,
    data: dict
):

    task = tasks.get(
        task_id
    )


    if not task or not task.agent:

        return {
            "error": "Task not found."
        }


    task.agent.set_approval(
        data.get(
            "approved",
            False
        )
    )


    return {
        "success": True
    }


# ================================================================
# PII
# ================================================================

@app.post("/task/{task_id}/provide-pii")
async def provide_pii(
    task_id: str,
    data: dict
):

    task = tasks.get(
        task_id
    )


    if not task or not task.agent:

        return {
            "error": "Task not found."
        }


    task.agent.set_pii(
        data.get(
            "value",
            ""
        )
    )


    return {
        "success": True
    }


# ================================================================
# FRONTEND
# ================================================================

@app.get("/")
async def index():

    index_file = (
        FRONTEND_DIR
        / "index.html"
    )


    if not index_file.exists():

        return {
            "error": "Frontend index.html not found.",
            "expected_path": str(index_file)
        }


    return FileResponse(
        index_file
    )


# ================================================================
# FRONTEND FILES
# ================================================================

@app.get("/dashboard.html")
async def dashboard():

    dashboard_file = (
        FRONTEND_DIR
        / "dashboard.html"
    )


    if not dashboard_file.exists():

        return {
            "error": "dashboard.html not found."
        }


    return FileResponse(
        dashboard_file
    )


@app.get("/style.css")
async def style():

    style_file = (
        FRONTEND_DIR
        / "style.css"
    )


    if not style_file.exists():

        return {
            "error": "style.css not found."
        }


    return FileResponse(
        style_file
    )