"""
The core perceive -> reason -> GATE -> execute -> observe loop.

This is a Python generator, not an async function -- it yields one event
dict per step, and the CALLER (the backend, or a plain for-loop in a
test script) decides what to do with each event: print it, stream it
over WebSocket, log it. When an event needs human approval, the caller
resumes the generator with .send(True/False) once a decision is made.
This keeps the loop itself framework-agnostic -- it doesn't know or
care whether it's being driven by FastAPI, a CLI script, or a test.

THE ONE RULE (see learning/00-shared/01-architecture-overview.md and
policy/gate.py's docstring): no action reaches "execute" without going
through policy.gate.evaluate() first, and its verdict is obeyed exactly.
That call is not decorative in this file -- follow the code below and
you'll see every single action pass through it, no exceptions.

Swap points for the real system, clearly marked below:
  - agent/perception.py: swap file-reading for real Playwright calls
  - agent/reasoner.py:   now calls real providers (Groq/Gemini/Ollama) --
    this file's perception (file-reading) is still the mock, not the reasoning
  - execute_action() in this file: swap the print-based simulation for
    real Playwright actions
Nothing in the loop's control flow or its use of the policy gate needs
to change when those swaps happen.
"""

from typing import Generator

from agent.perception import read_page_content, extract_form_fields, find_submit_selector
from agent.reasoner import decide_next_action
from policy.gate import evaluate
from policy.models import ActionRequest

MAX_STEPS = 20  # step-budget guard against infinite loops (see architecture doc's threat #7)


def execute_action(action: dict, filled_fields: set[str]) -> str:
    """Simulated execution -- no real browser yet. Returns a plain-language
    description of what happened, used for the narration feed."""
    action_type = action["action_type"]
    payload = action["payload"]

    if action_type == "type":
        selector = payload["selector"]
        field_id = selector.lstrip("#")
        filled_fields.add(field_id)
        return f"Filled in the '{field_id}' field."

    if action_type == "submit":
        return "Submitted the form."

    if action_type == "ask_human":
        return f"Stuck: {payload.get('reason', 'unknown reason')}. Asking for help."

    return f"Performed action: {action_type}"


def run_task_events(
    task_description: str,
    html_path: str,
    target_domain: str,
) -> Generator[dict, bool, None]:
    """
    Yields one event dict per loop step:
      {"type": "narration", "text": "..."}
      {"type": "escalation", "reason": "...", "requires_human_review": true, ...}
      {"type": "pii_required", "field_id": "...", "mask": bool, "text": "..."}
      {"type": "done", "text": "..."}
      {"type": "halted", "text": "..."}

    When an "escalation" event is yielded, the caller must resume with
    .send(approved: bool) before the loop continues.

    When a "pii_required" event is yielded, the caller must resume with
    .send(raw_value: str) -- the actual sensitive value, typed directly
    by a human. This value is used ONLY inside execute_action() below; it
    is never added to filled_fields' logging, never included in any
    narration text, and never seen by decide_next_action() (the
    reasoner's own proposed value for this field is discarded entirely,
    not just overwritten after the fact). See THREAT_MODEL.md's "PII
    Handling" section for why this is a stronger claim than "we detect
    misuse of sensitive fields."
    """
    yield {"type": "narration", "text": f"Starting task: {task_description}"}

    # --- PERCEIVE ---
    content_seen = read_page_content(html_path)
    fields = extract_form_fields(html_path)
    submit_selector = find_submit_selector(html_path)
    yield {
        "type": "narration",
        "text": f"Read the page. Found {len(fields)} field(s) and "
        f"{len(content_seen)} text chunk(s) to check.",
    }

    filled_fields: set[str] = set()
    steps = 0

    while steps < MAX_STEPS:
        steps += 1

        # --- REASON --- (real providers now, see agent/reasoner.py; this
        # loop's PERCEPTION is still file-based/mock, used for isolated tests)
        action = decide_next_action(task_description, fields, filled_fields, submit_selector)

        # --- GATE --- (this call is the entire security story of the project)
        request = ActionRequest(
            action_type=action["action_type"],
            target_domain=target_domain,
            payload=action["payload"],
            content_seen=content_seen,
        )
        gate_result = evaluate(request)

        if not gate_result.allowed:
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
            # The agent's own proposed value (action["payload"]["text"],
            # a mock/fake placeholder) is discarded here -- never read,
            # never logged, never referenced again. Only the field's
            # SELECTOR survives from the reasoner's decision; the VALUE
            # comes exclusively from the human via .send().
            from policy.pii import should_mask

            raw_value = yield {
                "type": "pii_required",
                "field_id": gate_result.pii_field_id,
                "mask": should_mask(gate_result.pii_field_id),
                "text": f"This field ('{gate_result.pii_field_id}') requires sensitive "
                "information. Please enter it directly -- Proxy will not see or store the value.",
            }
            pii_action = {
                "action_type": "type",
                "payload": {"selector": action["payload"]["selector"], "text": raw_value},
            }
            description = execute_action(pii_action, filled_fields)  # never logs the value, see execute_action()
            yield {"type": "narration", "text": description}
            continue  # re-loop: fresh decide_next_action() call, not a resumed script

        if gate_result.requires_human_review:
            approved = yield {
                "type": "escalation",
                "reason": gate_result.reason,
                "requires_human_review": True,
                "blocked": False,
                "proposed_action": action,
            }
            if not approved:
                yield {"type": "halted", "text": "Stopped: human did not approve the action."}
                return
            yield {"type": "narration", "text": "Human approved. Continuing."}

        # --- EXECUTE ---
        description = execute_action(action, filled_fields)
        yield {"type": "narration", "text": description}

        # --- OBSERVE / loop condition ---
        if action["action_type"] == "submit":
            yield {"type": "done", "text": "Task complete."}
            return
        if action["action_type"] == "ask_human":
            yield {"type": "halted", "text": "Stopped: agent is stuck and needs human input."}
            return

    yield {"type": "halted", "text": f"Stopped: exceeded step budget of {MAX_STEPS}."}
