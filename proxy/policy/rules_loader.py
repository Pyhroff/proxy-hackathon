"""
Loads and queries policy/rules.yaml.

Always uses yaml.safe_load(), never yaml.load() — safe_load only ever
produces plain Python types (dict/list/str/int/bool) and cannot execute
arbitrary code embedded in the file. Since we're the security module,
this is exactly the kind of detail worth getting right and being able
to explain if asked.
"""

import os
import yaml

_RULES_PATH = os.path.join(os.path.dirname(__file__), "rules.yaml")
_RULES_CACHE: dict | None = None


def load_rules(path: str = _RULES_PATH) -> dict:
    """Load the policy file fresh from disk (bypasses the cache)."""
    with open(path) as f:
        return yaml.safe_load(f)


def get_rules(path: str = _RULES_PATH) -> dict:
    """Load once and cache in memory — avoids re-reading the file on every
    single evaluate() call during the agent loop."""
    global _RULES_CACHE
    if _RULES_CACHE is None:
        _RULES_CACHE = load_rules(path)
    return _RULES_CACHE


def is_domain_allowed(domain: str, rules: dict) -> bool:
    return domain in rules.get("allowed_domains", [])


def get_action_rule(action_type: str, rules: dict) -> dict:
    """Default-deny: an action type not explicitly listed in the policy
    file is treated as not allowed, never silently permitted."""
    return rules.get("actions", {}).get(action_type, {"allowed": False})
