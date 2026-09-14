"""
The Policy Gate.

THE THREE-LAYER DEFENSE (this file is Layer 2, not "the" defense):
This project's security story is NOT "we detect prompt injection." It's
"we assume detection sometimes fails, and the system still holds when it
does." Three independent layers, each covering for the others' blind spots:
  1. DETECTION   (policy/scanner.py)  -- heuristic + LLM-judge scanning of
     scraped content. Catches known/recognizable patterns. WILL miss novel
     phrasing, encoded payloads, split-payload attacks -- that's expected,
     not a design failure.
  2. CONTAINMENT (this file)          -- the allowlist doesn't need to
     recognize an attack. It caps what the agent can physically do
     regardless of whether it got tricked. This is the layer that holds
     even when Layer 1 fails completely.
  3. ESCALATION  (requires_human_review handling, backend/main.py)  -- when
     content is flagged, or an action falls outside policy, the agent
     stops and hands the decision to a human instead of guessing.
Put this on the OWASP slide as: not "we detect injection," but "we assume
detection fails sometimes, and these two other layers still hold when it
does."

This is the single function every proposed agent action must pass through
before it is allowed to execute via Playwright. Person 2's agent loop
calls evaluate() with an ActionRequest right after translating an LLM
tool_use block, and before calling execute_action(). See
person1-security/08-building-the-policy-gate-capstone.md for the full
integration walkthrough and the exact insertion point in the loop.

Checks run cheapest-first:
  1. Domain allowlist       (no network call, catches crude violations instantly)
  2. Injection scan         (potentially an LLM call -- only run once domain checks out)
  3. PII field check        (cheap regex -- catches sensitive fields before value ever exists)
  4. Per-action-type policy (e.g. "submit" always needs human review, even if clean)

THE ONE RULE: no code path anywhere in this project calls a Playwright
execute function without evaluate() having been called first and having
returned allowed=True (with requires_human_review handled if set). If you
ever find yourself writing "just for testing, skip the gate here" --
don't. That code path is the whole security story of this project.
"""

from proxy.policy.models import ActionRequest, GateResult
from proxy.policy.pii import is_pii_field
from proxy.policy.rules_loader import get_rules, is_domain_allowed, get_action_rule
from proxy.policy.scanner import scan


def _field_id_from_selector(selector: str) -> str:
    """'#dob' -> 'dob'. Selectors elsewhere in the project are always a
    bare '#<field_id>' (see agent/reasoner.py) -- this is deliberately
    simple, not a general CSS selector parser."""
    return selector.lstrip("#")


def evaluate(action: ActionRequest) -> GateResult:
    rules = get_rules()

    # 1. Domain check
    if not is_domain_allowed(action.target_domain, rules):
        return GateResult(
            allowed=False,
            reason=f"domain '{action.target_domain}' is not in the allowlist",
            requires_human_review=False,
        )

    # 2. Injection check on everything the agent has read recently
    for content in action.content_seen:
        is_suspicious, reason = scan(content)
        if is_suspicious:
            return GateResult(
                allowed=False,
                reason=f"suspected injection in recently-read content: {reason}",
                requires_human_review=True,
                blocked_pattern=reason,
            )

    # 3. PII field check -- BEFORE the general per-action-type policy below,
    # and regardless of what value the agent proposed to type. This check
    # doesn't care whether the proposed value looks sensitive (the agent's
    # mock/LLM-proposed value is discarded entirely either way, see
    # agent/loop.py) -- it cares whether the FIELD ITSELF is one that
    # should never have its real value pass through the agent's context.
    if action.action_type == "type" and "selector" in action.payload:
        field_id = _field_id_from_selector(action.payload["selector"])
        if is_pii_field(field_id):
            return GateResult(
                allowed=True,
                reason=f"field '{field_id}' is classified as sensitive (PII) -- "
                "value must be supplied directly by a human, not the agent",
                requires_human_review=False,
                requires_pii_input=True,
                pii_field_id=field_id,
            )

    # 4. Per-action-type policy
    action_rule = get_action_rule(action.action_type, rules)
    if not action_rule.get("allowed", False):
        return GateResult(
            allowed=False,
            reason=f"action type '{action.action_type}' is not permitted by policy",
            requires_human_review=False,
        )

    if action_rule.get("requires_human_review", False):
        return GateResult(
            allowed=True,
            reason=f"action '{action.action_type}' permitted but requires human approval before executing",
            requires_human_review=True,
        )

    return GateResult(allowed=True, reason="ok", requires_human_review=False)
