"""
Standalone proof-of-concept for CDP screencast -- NOT wired into the
real app yet. Opens the clean demo site, starts a CDP screencast, types
into a couple of fields (simulating agent actions with small delays so
you can see it's not instant), and saves every frame CDP sends us to
eval/cdp_frames/ so you can literally open them and see how many frames
you get for one short interaction, compared to the 1 screenshot-per-step
the current app takes.

Run with: python eval/cdp_screencast_test.py
Then look in: eval/cdp_frames/
"""

import asyncio
import base64
import os
import pathlib

from playwright.async_api import async_playwright

OUT_DIR = "eval/cdp_frames"


async def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for f in pathlib.Path(OUT_DIR).glob("*.jpg"):
        f.unlink()

    frame_count = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # CDP session -- this is the DevTools Protocol connection that
        # lets us ask Chrome to push frames to us continuously, instead
        # of us pulling one screenshot at a time.
        cdp = await page.context.new_cdp_session(page)

        def on_frame(params):
            nonlocal frame_count
            frame_count += 1
            data = base64.b64decode(params["data"])
            with open(f"{OUT_DIR}/frame_{frame_count:03d}.jpg", "wb") as f:
                f.write(data)
            # MUST ack every frame or Chrome stops sending more
            asyncio.create_task(
                cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
            )

        cdp.on("Page.screencastFrame", on_frame)

        await cdp.send("Page.startScreencast", {
            "format": "jpeg",
            "quality": 60,
            "maxWidth": 1000,
            "maxHeight": 800,
        })

        html_path = pathlib.Path("demo-sites/clean/application.html").resolve().as_uri()
        await page.goto(html_path)
        await asyncio.sleep(0.5)

        # Simulate what the agent does, slowly, so repaints actually happen
        await page.fill("#full_name", "Jane Doe")
        await asyncio.sleep(0.3)
        await page.fill("#dob", "1990-01-01")
        await asyncio.sleep(0.3)
        await page.fill("#address", "123 Main St")
        await asyncio.sleep(0.3)
        await page.fill("#income", "42000")
        await asyncio.sleep(0.5)

        await cdp.send("Page.stopScreencast")
        await asyncio.sleep(0.2)  # let any in-flight frame land
        await browser.close()

    print(f"\nCaptured {frame_count} frames into {OUT_DIR}/")
    print("Compare: the current app would have taken exactly 4 screenshots for this same interaction (one per fill).")


if __name__ == "__main__":
    asyncio.run(main())
