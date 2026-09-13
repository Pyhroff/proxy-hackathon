"""
Standalone CDP-screencast vs. step-screenshot COMPARISON tool.

This is deliberately NOT wired into backend/main.py or agent/loop_playwright.py
-- it's a separate mini FastAPI app on its own port, running its own
Playwright session, so there is zero risk to the verified production
loop. It exists purely so you can watch both approaches side by side and
decide whether to adopt CDP screencast for real later.

Run with: python eval/cdp_live_compare.py
Then open: http://localhost:8002

Left panel  = LEGACY approach (current production code): one screenshot
              captured after each discrete action, via page.screenshot().
Right panel = CDP SCREENCAST: continuous frames pushed by Chrome's
              DevTools Protocol as the page actually repaints, independent
              of action boundaries.

Both panels drive the SAME browser tab through the SAME scripted sequence
on the real clean demo site, so the comparison is apples-to-apples.
"""

import asyncio
import base64
import json
import pathlib

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
import uvicorn
from playwright.async_api import async_playwright

app = FastAPI()

PAGE = """<!DOCTYPE html>
<html><head><title>CDP vs Legacy Screenshot Comparison</title>
<style>
  body { font-family: -apple-system, sans-serif; background: #111; color: #eee; margin: 0; padding: 20px; }
  h1 { font-size: 18px; }
  .row { display: flex; gap: 20px; }
  .col { flex: 1; }
  .col h2 { font-size: 15px; color: #aaa; }
  img { width: 100%; border: 1px solid #333; background: #fff; display: block; }
  .count { font-size: 13px; color: #6cf; margin-top: 6px; }
  button { font-size: 15px; padding: 10px 20px; margin-bottom: 16px; cursor: pointer; }
</style></head>
<body>
  <h1>Legacy step-screenshot (left) vs. CDP screencast (right)</h1>
  <button onclick="start()">Run comparison</button>
  <div class="row">
    <div class="col">
      <h2>Legacy — capture_screenshot() per action</h2>
      <img id="legacy" src="">
      <div class="count" id="legacy-count">0 frames</div>
    </div>
    <div class="col">
      <h2>CDP screencast — continuous frames</h2>
      <img id="cdp" src="">
      <div class="count" id="cdp-count">0 frames</div>
    </div>
  </div>
  <script>
    let legacyCount = 0, cdpCount = 0;
    function start() {
      legacyCount = 0; cdpCount = 0;
      const ws = new WebSocket("ws://localhost:8002/ws");
      ws.onmessage = (msg) => {
        const event = JSON.parse(msg.data);
        if (event.type === "legacy") {
          document.getElementById("legacy").src = "data:image/png;base64," + event.data;
          legacyCount++;
          document.getElementById("legacy-count").textContent = legacyCount + " frames";
        } else if (event.type === "cdp") {
          document.getElementById("cdp").src = "data:image/jpeg;base64," + event.data;
          cdpCount++;
          document.getElementById("cdp-count").textContent = cdpCount + " frames";
        } else if (event.type === "done") {
          document.getElementById("legacy-count").textContent = legacyCount + " frames (final)";
          document.getElementById("cdp-count").textContent = cdpCount + " frames (final)";
        }
      };
    }
  </script>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    html_path = pathlib.Path("demo-sites/clean/application.html").resolve().as_uri()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        cdp = await page.context.new_cdp_session(page)

        async def send_json_safe(payload):
            try:
                await websocket.send_json(payload)
            except Exception:
                pass

        def on_frame(params):
            asyncio.create_task(send_json_safe({"type": "cdp", "data": params["data"]}))
            asyncio.create_task(cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]}))

        cdp.on("Page.screencastFrame", on_frame)
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 60, "maxWidth": 900, "maxHeight": 700})

        async def legacy_capture():
            png = await page.screenshot(type="png")
            await send_json_safe({"type": "legacy", "data": base64.b64encode(png).decode("ascii")})

        await page.goto(html_path)
        await asyncio.sleep(0.4)
        await legacy_capture()

        fields = [("#full_name", "Jane Doe"), ("#dob", "1990-01-01"), ("#address", "123 Main St"), ("#income", "42000")]
        for selector, value in fields:
            await page.fill(selector, value)
            await asyncio.sleep(0.5)
            await legacy_capture()

        await asyncio.sleep(0.3)
        await page.click("#submit-application")
        await asyncio.sleep(0.4)
        await legacy_capture()

        await cdp.send("Page.stopScreencast")
        await asyncio.sleep(0.2)
        await send_json_safe({"type": "done"})
        await browser.close()

    await websocket.close()


if __name__ == "__main__":
    print("Open http://localhost:8002 and click 'Run comparison'")
    uvicorn.run(app, host="0.0.0.0", port=8002)
