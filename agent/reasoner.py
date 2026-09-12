"""Provider-routed LLM action selection for Proxy.

Routing order is Groq, Gemini, then local Ollama. Providers only propose an
action; the policy gate remains the final authority before execution.
"""
import json
import os
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

_SYSTEM = ("You are Proxy's action planner. Return exactly one JSON object with action_type, payload, and reason. "
           "Allowed action_type values: type, submit, ask_human. Never invent selectors. "
           "If any field is not already filled, choose type for the first unfilled field and provide a plausible "
           "non-sensitive placeholder text. If all fields are filled and a submit button exists, choose submit. "
           "Use ask_human only when the page has no actionable field or submit button, and include a specific reason. "
           "Never request or infer a real sensitive value. The policy gate makes the final decision. "
           "'reason' is always required: one short plain-language sentence explaining why you chose this action, "
           "shown directly to the end user -- keep it brief and non-technical.\n\n"
           "The 'payload' object's keys depend on action_type -- use EXACTLY these key names, no others:\n"
           "  type:    {\"selector\": \"#<field_id>\", \"text\": \"<value>\"}  "
           "-- selector is always the field id prefixed with '#', e.g. \"#full_name\"\n"
           "  submit:  {\"selector\": \"#<submit_button_id>\"}\n"
           "  ask_human: {\"reason\": \"<specific reason>\"}\n"
           "Example valid response: "
           "{\"action_type\": \"type\", \"payload\": {\"selector\": \"#full_name\", \"text\": \"Jane Doe\"}, "
           "\"reason\": \"Filling in the name field since it is empty.\"}")

_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action_type": {"type": "string", "enum": ["type", "submit", "ask_human"]},
        "payload": {"type": "object"},
        "reason": {"type": "string"},
    },
    "required": ["action_type", "payload", "reason"],
}


def _raise_http(response: httpx.Response) -> None:
    if response.is_error:
        detail = response.text[:240].replace("\n", " ")
        raise RuntimeError(f"provider HTTP {response.status_code}: {detail}")


def _prompt(task: str, fields: list[str], filled: set[str], submit: str | None) -> str:
    return json.dumps({"task": task, "available_field_ids": fields,
                       "already_filled_field_ids": sorted(filled), "submit_button_id": submit})


def _demo_value_for(field: str) -> str:
    """Synthetic non-PII values used only when providers are unavailable."""
    values = {"full_name": "Jane Doe", "address": "123 Demo Street, Springfield, 12345",
              "income": "42000", "annual_income": "42000"}
    return values.get(field, "Demo value")


def _validate_action(value: Any, fields: list[str], submit: str | None) -> dict:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("reasoner returned a non-object action")
    kind, payload = value.get("action_type"), value.get("payload")
    if kind not in {"type", "submit", "ask_human"} or not isinstance(payload, dict):
        raise ValueError("reasoner returned an invalid action shape")
    if kind == "type":
        selector = payload.get("selector")
        if selector in set(fields):
            payload["selector"] = f"#{selector}"
        if payload.get("selector") not in {f"#{field}" for field in fields}:
            raise ValueError("reasoner selected an unknown field")
        if not isinstance(payload.get("text", ""), str):
            raise ValueError("type action text must be a string")
    elif kind == "submit" and payload.get("selector") != (f"#{submit}" if submit else None):
        raise ValueError("reasoner selected an invalid submit target")
    elif kind == "ask_human" and (not isinstance(payload.get("reason"), str) or not payload["reason"].strip()):
        raise ValueError("ask_human reason must be a string")
    reason = value.get("reason", "")
    return {"action_type": kind, "payload": payload, "reason": reason if isinstance(reason, str) else ""}


def _json_text(text: str) -> dict:
    text = text.strip()
    # Models may wrap JSON in ```json fences or add a short explanation.
    if "```" in text:
        blocks = [b.strip() for b in text.split("```") if b.strip()]
        text = next((b[4:].strip() if b.lower().startswith("json") else b
                     for b in blocks if "{" in b and "}" in b), text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def _groq(prompt: str) -> dict:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY missing")
    model = os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile"
    r = httpx.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                   json={"model": model, "temperature": 0, "reasoning_format": "hidden",
                         "response_format": {"type": "json_object"},
                         "messages": [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}]}, timeout=30)
    _raise_http(r)
    return _json_text(r.json()["choices"][0]["message"]["content"])


def _gemini(prompt: str) -> dict:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY missing")
    model = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
    r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
                   json={"systemInstruction": {"parts": [{"text": _SYSTEM}]},
                         "contents": [{"parts": [{"text": prompt}]}],
                         "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                                               "responseSchema": _ACTION_SCHEMA}}, timeout=30)
    _raise_http(r)
    return _json_text(r.json()["candidates"][0]["content"]["parts"][0]["text"])


def _ollama(prompt: str) -> dict:
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL") or "qwen2.5:7b"
    r = httpx.post(f"{base}/api/chat", json={"model": model, "stream": False,
                   "format": _ACTION_SCHEMA, "messages": [{"role": "system", "content": _SYSTEM},
                   {"role": "user", "content": prompt}], "options": {"temperature": 0}, "think": False}, timeout=45)
    _raise_http(r)
    message = r.json()["message"]
    content = message.get("content", "")
    if content.strip():
        return _json_text(content)
    calls = message.get("tool_calls") or []
    if calls:
        return calls[0]["function"]["arguments"]
    raise ValueError("Ollama returned neither JSON content nor a tool call")


def decide_next_action(task_description: str, fields: list[str], filled_fields: set[str], submit_selector: str | None) -> dict:
    """Return one validated action, trying providers in configured order."""
    prompt = _prompt(task_description, fields, filled_fields, submit_selector)
    errors = []
    for name, provider in (("Groq", _groq), ("Gemini", _gemini), ("Ollama", _ollama)):
        try:
            result = _validate_action(provider(prompt), fields, submit_selector)
            result["provider"] = name
            return result
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = str(exc).replace("GROQ_API_KEY", "[key]").replace("GEMINI_API_KEY", "[key]")[:300]
            errors.append(f"{name}: {type(exc).__name__}" + (f"/{status}" if status else "") + (f" - {detail}" if detail else ""))
    # Availability/format failures must not make the agent unsafe or unusable.
    # This local fallback is intentionally narrow and still passes through the
    # policy gate; it is not allowed to invent selectors or bypass approval.
    for field in fields:
        if field not in filled_fields:
            return {"action_type": "type", "payload": {"selector": f"#{field}", "text": _demo_value_for(field)},
                    "provider": "Local Fallback", "reason": "All AI providers were unavailable; using a safe local placeholder."}
    if submit_selector:
        return {"action_type": "submit", "payload": {"selector": f"#{submit_selector}"},
                "provider": "Local Fallback", "reason": "All fields are filled and a submit control was found."}
    return {"action_type": "ask_human", "payload": {"reason": "No valid next action was returned by the providers."},
            "provider": "Local Fallback", "reason": "No actionable field or submit control was found on the page."}
