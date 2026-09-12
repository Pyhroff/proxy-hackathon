"""
Real-browser version of agent/loop.py's control flow.

This is an ASYNC GENERATOR (async def ... yield) instead of the plain
generator in loop.py, because every perception/execution step now
actually awaits a browser action. The event shape yielded is identical
to loop.py's, and policy.gate.evaluate() is called at exactly the same
point in the flow -- so backend/main.py only needs a thin adapter to
drive this instead of the mock version (see the note at the bottom of
this file).

Domain note: real navigation would use the page's actual URL (parsed
with urllib.parse) to get target_domain for the allowlist check. Since
this project's demo sites are opened as local files (file:// URLs, no
real domain), target_domain is passed in explicitly here and matched
against the SAME synthetic name used in policy/rules.yaml
("benefits-demo.local"). When demo sites are served over real HTTP
instead of opened as files, switch to reading page.url's real host.
"""

import asyncio
from typing import AsyncGenerator

from agent.browser_runtime import (
    launch_browser,
    close_browser,
    navigate,
    read_page_content,
    extract_form_fields,
    find_submit_selector,
    execute_action,
    capture_screenshot,
)
from agent.reasoner import decide_next_action
from policy.gate import evaluate
from policy.models import ActionRequest

MAX_STEPS = 20


async def _evaluate_safely(request: ActionRequest):
    """Runs policy.gate.evaluate() in a worker thread, not directly on
    the event loop.

    WHY THIS MATTERS: evaluate() can make a real, BLOCKING network call
    (the Groq judge layer in policy/scanner.py uses the sync Groq SDK,
    not an async client). Calling it directly inside this async
    generator's own frame would freeze the entire event loop for the
    duration of that call -- including this task's own screenshot
    captures and, if driven by a WebSocket, its keepalive pings. This is
    the EXACT bug documented in details.md (the "ping timeout" incident)
    that hit agent/loop.py's plain generator -- fixed there by wrapping
    the call in backend/main.py. This loop is async-native, so the same
    risk exists here too, just one level down -- fixed at the source so
    it's safe regardless of what drives this generator (CLI script or
    backend), not just when a particular caller remembers to wrap it."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, evaluate, request)


async def run_task_events_playwright(
    task_description: str,
    html_path: str,
    target_domain: str,
    headless: bool = True,
) -> AsyncGenerator[dict, bool]:
    """
    Async version of agent.loop.run_task_events -- same event shapes,
    same gate enforcement, but perceiving and acting on a REAL browser
    page via Playwright instead of a saved file + in-memory simulation.

    Usage from an async caller (see agent/loop.py's docstring for the
    generic drive pattern -- this works the same way but with
    `async for` / `await gen.asend(...)` instead of the sync equivalents):

        agen = run_task_events_playwright(task, html_path, domain)
        event = await agen.asend(None)   # prime the generator
        while True:
            ... handle event ...
            if event["type"] == "escalation" and not event.get("blocked"):
                event = await agen.asend(approved_bool)
            elif event["type"] == "pii_required":
                event = await agen.asend(raw_value_str)
            else:
                event = await agen.asend(None)
    """
    yield {"type": "narration", "text": f"Starting task: {task_description}"}

    playwright, browser, page = await launch_browser(headless=headless)
    try:
        await navigate(page, html_path)

        # --- PERCEIVE ---
        content_seen = await read_page_content(page)
        fields = await extract_form_fields(page)
        submit_selector = await find_submit_selector(page)
        screenshot = await capture_screenshot(page)  # for the split-screen right panel ONLY
        yield {
            "type": "narration",
            "text": f"Read the page. Found {len(fields)} field(s) and "
            f"{len(content_seen)} text chunk(s) to check.",
            "screenshot": screenshot,
        }

        filled_fields: set[str] = set()
        steps = 0

        while steps < MAX_STEPS:
            steps += 1

            # --- REASON --- (still the mock from agent/reasoner.py --
            # same swap point as the non-browser loop)
            action = decide_next_action(task_description, fields, filled_fields, submit_selector)

            # --- GATE --- (identical call, identical enforcement)
            request = ActionRequest(
                action_type=action["action_type"],
                target_domain=target_domain,
                payload=action["payload"],
                content_seen=content_seen,
            )
            gate_result = await _evaluate_safely(request)

            if not gate_result.allowed:
                # See advisor decision (Sept 2026 split-screen build): on a
                # block, the right panel switches from screenshot to a
                # "flagged content" view -- a screenshot here would show a
                # normal-looking form (the injection is invisible by
                # design) and undersell what actually happened. The
                # frontend makes this switch based on blocked=True, using
                # blocked_pattern, which was already being sent.
                yield {
                    "type": "escalation",
                    "reason": gate_result.reason,
                    "requires_human_review": gate_result.requires_human_review,
                    "blocked_pattern": gate_result.blocked_pattern,
                    "blocked": True,
                }
                yield {"type": "halted", "text": f"Stopped: {gate_result.reason}"}
                return

            if gate_result.requires_pii_input:
                # Same principle as agent/loop.py's mock version: the
                # reasoner's own proposed value for this field is
                # discarded entirely, never used. Only the selector
                # survives; the real value comes from a human via
                # .asend(). See THREAT_MODEL.md "PII Handling".
                #
                # The screenshot attached here is the page as it stood
                # BEFORE this field is filled -- deliberately static while
                # the human types into the separate PII input box, per
                # the user's own request: "the user should see the static
                # webpage and enter their stuff directly" (into the box,
                # not onto the image).
                from policy.pii import should_mask

                field_selector = action["payload"]["selector"]
                prompt_text = (
                    f"This field ('{gate_result.pii_field_id}') requires sensitive "
                    "information. Please enter it directly -- Proxy will not see or store the value."
                )
                field_mask = should_mask(gate_result.pii_field_id)

                # Retry loop: a wrong FORMAT (e.g. a date field expecting
                # YYYY-MM-DD) must not kill the whole task. Found on a
                # real run -- see details.md. Re-prompts for the SAME
                # field instead of halting.
                while True:
                    raw_value = yield {
                        "type": "pii_required",
                        "field_id": gate_result.pii_field_id,
                        "mask": field_mask,
                        "text": prompt_text,
                        "screenshot": screenshot,
                    }
                    pii_action = {"action_type": "type", "payload": {"selector": field_selector, "text": raw_value}}
                    try:
                        description = await execute_action(page, pii_action)  # never logs the value
                        break
                    except Exception:
                        # CRITICAL: do not include str(exception) here.
                        # Playwright's own error messages echo back the
                        # exact value that was attempted (e.g.
                        # `fill("Daggud")` appears verbatim in a real
                        # Playwright error) -- surfacing that text would
                        # leak the sensitive value into the narration
                        # feed and, from there, into the audit log. This
                        # was found on a real run with a test value; the
                        # same leak with a real DOB/SSN would be a
                        # genuine PII exposure, not a cosmetic bug. Only
                        # a fixed, generic message is ever shown.
                        prompt_text = (
                            f"That value wasn't accepted for '{gate_result.pii_field_id}' "
                            "(the form field rejected the format). Please try again."
                        )
                        # loop back and re-prompt for the same field

                filled_fields.add(gate_result.pii_field_id)
                screenshot = await capture_screenshot(page)  # refresh: field is now visibly filled
                yield {"type": "narration", "text": description, "screenshot": screenshot}
                continue  # re-loop: fresh decide_next_action() call against the current page

            if gate_result.requires_human_review:
                approved = yield {
                    "type": "escalation",
                    "reason": gate_result.reason,
                    "requires_human_review": True,
                    "blocked": False,
                    "proposed_action": action,
                    "screenshot": screenshot,
                }
                if not approved:
                    yield {"type": "halted", "text": "Stopped: human did not approve the action."}
                    return
                yield {"type": "narration", "text": "Human approved. Continuing."}

            # --- EXECUTE --- (real browser action now)
            description = await execute_action(page, action)
            if action["action_type"] == "type":
                field_id = action["payload"]["selector"].lstrip("#")
                filled_fields.add(field_id)
            screenshot = await capture_screenshot(page)  # refresh after every real action
            yield {"type": "narration", "text": description, "screenshot": screenshot}

            # --- OBSERVE / loop condition ---
            if action["action_type"] == "submit":
                yield {"type": "done", "text": "Task complete."}
                return
            if action["action_type"] == "ask_human":
                yield {"type": "halted", "text": "Stopped: agent is stuck and needs human input."}
                return

        yield {"type": "halted", "text": f"Stopped: exceeded step budget of {MAX_STEPS}."}

    finally:
        await close_browser(playwright, browser)


# --- Backend integration note ---
# As of the split-screen build, backend/main.py drives THIS generator
# (not agent.loop's mock version) via `await agen.asend(...)` /
# `StopAsyncIteration`. Note that backend/main.py no longer needs its own
# run_in_executor wrapping around advancing the generator -- that
# protection now lives inside THIS file (_evaluate_safely above), so it
# holds regardless of what drives this generator, not just the backend.
