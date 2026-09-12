"""
THIS FILE IS A STAND-IN, NOT THE REAL AGENT REASONING.

decide_next_action() here is a deterministic mock: it looks at which
fields are already filled and picks the next unfilled one, or decides
to submit once all fields are filled. This exists so the full
perceive -> reason -> gate -> execute loop (agent/loop.py) can run
end-to-end TODAY, with no LLM API key, so everyone can see the real
integration shape before the real model call exists.

Replace this function's body with a real LLM tool-calling call once the
team picks a provider (see learning/person1-security/02-llm-tool-use-function-calling.md
for the exact wire format of a tool_use response). The function
signature below is deliberately written to match what that real version
should look like -- same inputs, same output shape -- so swapping the
implementation later doesn't require touching agent/loop.py at all.
"""


def _mock_value_for(field_id: str) -> str:
    """Guesses a plausible value shape from the field's id/name so the
    simulated 'type' action doesn't send garbage into typed inputs (e.g.
    an HTML <input type="date"> rejects free text like "<mock value>").
    A real LLM-driven reasoner would instead read the field's actual
    label/type from the page and generate an appropriate value -- this
    is a narrow stand-in just so the mock survives real browser
    validation during development."""
    lowered = field_id.lower()
    if "dob" in lowered or "birth" in lowered or "date" in lowered:
        return "1990-01-01"
    if "income" in lowered or "amount" in lowered:
        return "42000"
    if "email" in lowered:
        return "demo.user@example.com"
    if "phone" in lowered:
        return "5555550123"
    return f"Demo value for {field_id}"


def decide_next_action(
    task_description: str,
    fields: list[str],
    filled_fields: set[str],
    submit_selector: str | None,
) -> dict:
    """
    Returns an action dict shaped like a translated LLM tool_use block:
        {"action_type": "type" | "submit" | "ask_human", "payload": {...}}

    A real implementation would instead call an LLM with a tool schema
    (click/type/navigate/read_page/ask_human) and the current page state
    in its context, and return whatever tool_use block the model chose --
    see Lesson 02's tool_use_to_action_request() for that translation step.
    """
    for field_id in fields:
        if field_id not in filled_fields:
            return {
                "action_type": "type",
                "payload": {"selector": f"#{field_id}", "text": _mock_value_for(field_id)},
            }

    if submit_selector:
        return {"action_type": "submit", "payload": {"selector": f"#{submit_selector}"}}

    # nothing left to fill and no submit button found -- a real agent
    # would call ask_human here instead of guessing.
    return {"action_type": "ask_human", "payload": {"reason": "no submit button found on page"}}
