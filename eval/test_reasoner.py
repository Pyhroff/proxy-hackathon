from agent import reasoner


def test_provider_action_is_validated(monkeypatch):
    monkeypatch.setattr(reasoner, "_groq", lambda prompt: {
        "action_type": "type", "payload": {"selector": "full_name", "text": "Jane Doe"}
    })
    result = reasoner.decide_next_action("complete form", ["full_name"], set(), "submit")
    assert result["payload"]["selector"] == "#full_name"


def test_invalid_providers_use_synthetic_fallback(monkeypatch):
    def fail(prompt):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(reasoner, "_groq", fail)
    monkeypatch.setattr(reasoner, "_gemini", fail)
    monkeypatch.setattr(reasoner, "_ollama", fail)
    result = reasoner.decide_next_action("complete form", ["full_name"], set(), "submit")
    assert result == {"action_type": "type", "payload": {"selector": "#full_name", "text": "Jane Doe"}}


def test_submit_target_is_strict():
    try:
        reasoner._validate_action({"action_type": "submit", "payload": {"selector": "#other"}}, [], "submit")
    except ValueError:
        return
    assert False, "invalid submit target was accepted"
