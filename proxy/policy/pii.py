"""
PII field classification -- hardcoded as always-high-risk in the policy
gate, regardless of scanner confidence. Not detected reactively (the
scanner watches page CONTENT for manipulation); this watches the agent's
own proposed ACTIONS for whether they'd write a sensitive value, and
intercepts before the value ever exists in the agent's context.

Field identification here is deliberately crude (id/name substring
matching) -- good enough for a hackathon demo where field ids are known
in advance. A production version would also inspect the field's label
text and input type (e.g. <input type="tel" pattern="\\d{3}-\\d{2}-\\d{4}">
hints), not just the id string.
"""

import re

# Patterns matched against a field's id/name (lowercased). Each category
# corresponds to one of the four sensitive-data types named in the spec
# this was scoped from: SSN, DOB, financial account numbers, medical info.
_PII_PATTERNS = [
    r"ssn", r"social[_-]?security",
    r"\bdob\b", r"date[_-]?of[_-]?birth", r"birth[_-]?date",
    r"account[_-]?number", r"routing[_-]?number", r"bank[_-]?account",
    r"medical", r"diagnosis", r"health[_-]?condition",
]

# Subset that should be masked (password-style input) rather than shown
# in plain text while typing -- numeric identifiers where shoulder-surfing
# risk is highest. DOB is intentionally NOT in this list: it's sensitive
# enough to gate, but masking a date entry is unusual UX friction most
# users wouldn't expect, and it's lower-value to an attacker than an SSN
# or account number on its own.
_MASK_PATTERNS = [
    r"ssn", r"social[_-]?security",
    r"account[_-]?number", r"routing[_-]?number", r"bank[_-]?account",
]

_pii_re = re.compile("|".join(_PII_PATTERNS), re.IGNORECASE)
_mask_re = re.compile("|".join(_MASK_PATTERNS), re.IGNORECASE)


def is_pii_field(field_id: str) -> bool:
    return bool(_pii_re.search(field_id))


def should_mask(field_id: str) -> bool:
    """Whether the frontend should render this as a password-style input
    rather than plain text."""
    return bool(_mask_re.search(field_id))
