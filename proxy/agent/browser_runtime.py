"""
Real Playwright-backed perception + execution. This is the module that
replaces the file-reading simulation in agent/perception.py and the
print-based execute_action() in agent/loop.py, once you're ready to run
against an actual browser instead of a local HTML file.

Uses Playwright's ASYNC API (playwright.async_api), not the sync one --
this matters because the agent loop needs to run alongside a FastAPI
WebSocket connection, and the sync API blocks the whole event loop while
waiting on browser actions (see learning/00-shared/02-async-python-basics.md).

Everything here still calls policy content the same way the mock version
did: every string pulled off the page becomes an UntrustedContent before
it's allowed near the scanner or the agent's reasoning. Nothing about
the security model changes when you swap from file-reading to a real
browser -- that's the whole point of keeping perception and the gate as
separate, swappable modules.
"""

import asyncio
import base64
import pathlib

from playwright.async_api import async_playwright, Page, Browser, Playwright

from proxy.policy.html_utils import content_hash
from proxy.policy.models import UntrustedContent


def _to_file_url(html_path: str) -> str:
    """Playwright needs a real URL, not a bare filesystem path. Convert
    a local HTML file into a file:// URL it can navigate to. Swap this
    for a real http(s) URL once demo sites are served rather than opened
    as local files."""
    return pathlib.Path(html_path).resolve().as_uri()


async def launch_browser(headless: bool = True) -> tuple[Playwright, Browser, Page]:
    """Starts Playwright + Chromium and returns a ready page. Caller is
    responsible for calling close_browser() when done (see agent/loop_playwright.py
    for the pattern -- always in a try/finally)."""
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=headless)
    page = await browser.new_page()
    return playwright, browser, page


async def close_browser(playwright: Playwright, browser: Browser) -> None:
    await browser.close()
    await playwright.stop()


async def navigate(page: Page, html_path: str) -> None:
    await page.goto(_to_file_url(html_path))


async def capture_screenshot(page: Page) -> str:
    """Returns a base64-encoded PNG of the current page state -- this is
    what the frontend's split-screen right panel renders as
    <img src="data:image/png;base64,...">. Called after every step in
    agent/loop_playwright.py so the panel stays live.

    This is purely for the HUMAN to see -- it never touches the agent's
    own reasoning or the scanner. Do not confuse this with
    read_page_content() above, which is what the agent/scanner actually
    read (text only, no image)."""
    png_bytes = await page.screenshot(type="png")
    return base64.b64encode(png_bytes).decode("ascii")


# --- CDP live screencast -----------------------------------------------
# ADDITIVE, not a replacement: capture_screenshot() above is untouched and
# still called exactly where it always was (see agent/loop_playwright.py)
# -- every event still carries its "screenshot" field the same as before.
# This is a second, independent channel: Chrome's DevTools Protocol pushes
# a continuous stream of frames as the page actually repaints, instead of
# one still image per discrete action. See eval/cdp_live_compare.py for
# the side-by-side proof (6 discrete frames vs ~28 continuous frames for
# the same interaction) that motivated wiring this into the real app.

async def start_cdp_stream(page: Page, on_frame) -> "object":
    """Starts a live screencast on `page`. `on_frame` is an async callable
    receiving one base64-encoded JPEG string per frame, called continuously
    and independently of the agent loop's step boundaries -- a frame can
    arrive mid-action, not just after one completes. Returns the CDP
    session; pass it to stop_cdp_stream() when the task ends."""
    cdp = await page.context.new_cdp_session(page)

    def _on_frame(params: dict) -> None:
        async def _handle():
            try:
                await on_frame(params["data"])
            finally:
                # Chrome pauses sending more frames until each one is
                # acked -- forgetting this silently stalls the stream.
                try:
                    await cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
                except Exception:
                    pass
        asyncio.create_task(_handle())

    cdp.on("Page.screencastFrame", _on_frame)
    await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 60, "maxWidth": 1000, "maxHeight": 800})
    return cdp


async def stop_cdp_stream(cdp_session) -> None:
    try:
        await cdp_session.send("Page.stopScreencast")
    except Exception:
        pass


async def read_page_content(page: Page) -> list[UntrustedContent]:
    """Pulls visible text AND alt-attribute text off the live page, tags
    every chunk as UntrustedContent. Mirrors agent/perception.py's
    read_page_content() exactly in output shape, so the rest of the loop
    doesn't care which one produced it.

    Two extraction calls, matching the two hiding techniques discussed
    in learning/person1-security/07-playwright-output-format-for-tagging.md:
    inner_text() for the rendered body (picks up CSS-hidden text depending
    on method), and a small JS eval for alt attributes (accessibility-tree
    style hiding), plus HTML comments via the raw page content.
    """
    chunks: list[str] = []

    # 1. Rendered body text (this can include display:none content
    #    depending on Playwright version/method -- verify on your setup,
    #    see the Lesson 07 exercise).
    body_text = await page.inner_text("body")
    for line in body_text.split("\n"):
        stripped = line.strip()
        if stripped:
            chunks.append(stripped)

    # 2. alt attributes -- not part of inner_text(), have to query them
    #    separately via the DOM.
    alt_texts = await page.eval_on_selector_all(
        "[alt]", "elements => elements.map(el => el.getAttribute('alt'))"
    )
    chunks.extend(a for a in alt_texts if a)

    # 3. HTML comments -- Playwright has no direct API for these, so pull
    #    them out of the raw page source.
    import re

    html = await page.content()
    comments = re.findall(r"<!--(.*?)-->", html, re.DOTALL)
    chunks.extend(c.strip() for c in comments if c.strip())

    return [
        UntrustedContent(
            content=chunk,
            source="scraped_page",
            trust_level="low",
            content_hash=content_hash(chunk),
        )
        for chunk in chunks
    ]


async def extract_form_fields(page: Page) -> list[str]:
    """Returns input element ids in document order, via a real DOM query
    instead of regex over a saved file."""
    return await page.eval_on_selector_all(
        "input[id]", "elements => elements.map(el => el.id)"
    )


async def find_submit_selector(page: Page) -> str | None:
    ids = await page.eval_on_selector_all(
        "button[type=submit][id]", "elements => elements.map(el => el.id)"
    )
    return ids[0] if ids else None


async def execute_action(page: Page, action: dict) -> str:
    """The real version of agent/loop.py's execute_action() -- actually
    performs the action in the browser instead of just updating an
    in-memory set. Only called AFTER policy.gate.evaluate() has approved
    the action -- see agent/loop_playwright.py for the call site."""
    action_type = action["action_type"]
    payload = action["payload"]

    if action_type == "type":
        selector = payload["selector"]
        text = payload.get("text", "")
        await page.fill(selector, text)
        return f"Filled in the '{selector.lstrip('#')}' field."

    if action_type == "click" or action_type == "submit":
        selector = payload["selector"]
        await page.click(selector)
        return f"Clicked '{selector.lstrip('#')}'."

    if action_type == "navigate":
        url = payload["url"]
        await page.goto(url)
        return f"Navigated to {url}."

    if action_type == "read_page":
        return "Re-read the page."

    if action_type == "ask_human":
        return f"Stuck: {payload.get('reason', 'unknown reason')}. Asking for help."

    return f"Performed action: {action_type}"
