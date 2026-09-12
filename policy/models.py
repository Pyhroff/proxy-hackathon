"""
Data contracts for the Proxy policy/guardrail layer.

Every piece of code in this project that reads content from a web page,
proposes an action, or reports a security decision speaks these three
shapes. Person 2 (agent loop) and Person 4 (backend) import these directly
instead of passing raw dicts around, so a typo or shape-mismatch fails loudly
at the moment it's created, not three function calls later.
"""

from typing import Literal, Optional
from pydantic import BaseModel, field_validator


class UntrustedContent(BaseModel):
    """
    Wraps any string pulled from an external, untrusted source (a scraped
    web page, most of the time) before it is allowed to touch the agent's
    LLM context or be scanned for injection attempts.

    Why this exists: an LLM cannot reliably tell the difference between
    "the user's actual instructions" and "text I happened to read that is
    pretending to be an instruction." Wrapping every scraped string in this
    model is how the rest of the codebase enforces "never trust content,
    only trust code" structurally, instead of hoping a prompt reminds the
    model not to fall for tricks.
    """

    content: str
    source: Literal["scraped_page", "user_input", "system"]
    trust_level: str
    content_hash: str

    @field_validator("content_hash")
    @classmethod
    def _check_hash_length(cls, v: str) -> str:
        if len(v) != 64:
            raise ValueError("content_hash must be a 64-char sha256 hex digest")
        return v


class ActionRequest(BaseModel):
    """
    A proposed action the agent wants to take, translated from whatever the
    LLM's tool-use response looked like (see person1-security/02 for the
    translation step) into a shape the policy gate can evaluate.
    """

    action_type: str
    target_domain: str
    payload: dict
    content_seen: list[UntrustedContent] = []


class GateResult(BaseModel):
    """
    The verdict returned by policy.gate.evaluate() for a single
    ActionRequest. This is also the object Person 4's backend serializes
    and sends over WebSocket to the frontend when an action is blocked or
    needs human approval.
    """

    allowed: bool
    reason: str
    requires_human_review: bool = False
    blocked_pattern: Optional[str] = None

    # PII-gating (see policy/pii.py, THREAT_MODEL.md "PII Handling"):
    # distinct from requires_human_review because the human's role here
    # is not "approve or deny" but "supply the actual value directly" --
    # the agent's own proposed value for this field is discarded
    # entirely, never used, never logged.
    requires_pii_input: bool = False
    pii_field_id: Optional[str] = None
