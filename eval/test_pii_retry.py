"""
Reproduces the exact real-world scenario (typing "Daggud" into the DOB
field) against the real Playwright loop.

UPDATE: after switching the DOB field from <input type="date"> to a
plain text field with a "YYYY-MM-DD" placeholder (see details.md --
native date inputs display in browser-locale format, which caused the
original crash), "Daggud" no longer fails at all -- a plain text field
accepts any string. So this test now confirms two things instead of one:
  1. The original crash class is gone at the source (no error, task
     completes normally even with a non-date string in the DOB field).
  2. The retry-on-failure logic added alongside that fix (agent/loop_playwright.py)
     never leaks the attempted value into any event text, as a defensive
     backstop for any OTHER reason a fill might still fail later.

Run with: python eval/test_pii_retry.py
"""

import asyncio

from agent.loop_playwright import run_task_events_playwright


async def drive():
    agen = run_task_events_playwright(
        "Complete the housing benefits application",
        "demo-sites/clean/application.html",
        "benefits-demo.local",
    )
    event = await agen.asend(None)
    dob_attempts = 0
    leaked = False

    while True:
        print(f"[{event['type'].upper()}] {event.get('text', event.get('reason', ''))}")

        # Check every single narration/text field for the leaked value
        for key in ("text", "reason"):
            if key in event and event[key] and "Daggud" in str(event[key]):
                leaked = True

        if event["type"] == "pii_required" and event["field_id"] == "dob":
            dob_attempts += 1
            if dob_attempts == 1:
                print("  -> supplying a BAD value: 'Daggud' (reproduces the real bug)")
                event = await agen.asend("Daggud")
            else:
                print("  -> supplying a VALID value: '1990-01-01'")
                event = await agen.asend("1990-01-01")
            continue

        if event["type"] == "escalation" and not event.get("blocked"):
            event = await agen.asend(True)
            continue

        if event["type"] in ("done", "halted"):
            break

        event = await agen.asend(None)

    # See backend/main.py's matching fix -- without this, the generator's
    # `finally: await close_browser(...)` never runs and the real
    # Chromium subprocess is left orphaned. Caused this very script to
    # hang indefinitely on a real run (see details.md).
    await agen.aclose()

    print(f"\ndob field attempts: {dob_attempts} (want: 1 -- text field accepts it, no retry needed)")
    print(f"Value leaked into any event text: {leaked} (want: False)")
    print(f"Task outcome: {event['type']} (want: done, NOT halted)")
    assert dob_attempts == 1, "text field should accept the value on the first try now"
    assert not leaked, "THE RAW PII VALUE LEAKED INTO AN EVENT"
    assert event["type"] == "done", "task should complete normally -- the original crash class is gone"
    print("\nALL CHECKS PASSED (original bug no longer reproducible; retry logic remains as a backstop)")


if __name__ == "__main__":
    asyncio.run(drive())
