# Proxy — Threat Model

Mapped to OWASP's Top 10 for LLM/Agentic Applications. This is the single source of truth for "what does Proxy defend against, and what does it explicitly not" — pull this table directly into the deck's security slide.

Naming what's out of scope explicitly is a credibility signal for judges, not a gap to hide. See [details.md](details.md) for the actual build history and test evidence backing each "in scope" row.

| # | Attack | In scope? | Mitigation | Where |
|---|---|---|---|---|
| 1 | Indirect prompt injection | ✅ Core demo | Content tagging + scanner + escalation | `policy/models.py` (`UntrustedContent`), `policy/scanner.py` |
| 2 | Excessive agency | ✅ Built structurally | Domain/action allowlist | `policy/rules.yaml`, `policy/gate.py` |
| 3 | Data exfiltration via side channel | ✅ Covered | Hard domain restriction (agent cannot navigate/submit outside the allowlisted domain) | `policy/gate.py`'s domain check |
| 4 | Direct prompt injection | 🗺️ Roadmap only | System-prompt hardening (not built) | -- |
| 5 | Tool/output manipulation | 🗺️ Roadmap only | Same content-tagging principle, applied to a different data source (e.g. a poisoned search-API result) | -- |
| 6 | Goal hijacking / task drift | 🗺️ Roadmap only | Per-step "does this action still serve the original goal?" check | -- |
| 7 | Denial-of-completion (infinite loop / stall) | ✅ Basic guard | Step-budget cap (`MAX_STEPS`) + stuck-detection (`ask_human` escalation) | `agent/loop.py`, `agent/loop_playwright.py` |
| 8 | Credential/session attacks | ❌ Explicitly out of scope | No login flows anywhere in the demo, by design (see "Session Scope Decision" below) | -- |

## The Three-Layer Defense (why no single layer is "the" defense)

Detection will sometimes miss things — that's expected, not a design failure. The architecture assumes detection can fail and contains the damage anyway:

1. **Detection layer** (`policy/scanner.py`) — heuristic regex + LLM-judge scans scraped content before it reaches the agent's context. Catches known/recognizable patterns; will miss novel phrasing, encoded payloads, split-payload attacks.
2. **Containment layer** (`policy/gate.py`) — the allowlist doesn't need to *recognize* an attack. It caps what the agent can physically do regardless of whether it got tricked. This is the layer that holds even when detection fails completely.
3. **Escalation layer** (`requires_human_review` flow, `backend/main.py`) — when content is flagged, or an action falls outside policy, the agent stops and hands the decision to a human instead of guessing.

**Slide framing:** not "we detect injection," but "we assume detection fails sometimes, and these two other layers still hold when it does."

## Session/Account Scope Decision

**Decision: Proxy stays on non-signed-in, no-account form flows. Do not extend to signed-in sessions (Google, etc.) without a separate, much stricter threat model.**

Reasoning:
- A signed-in session (Gmail/Drive/Calendar/payment methods) turns "excessive agency" from a slide bullet into real blast radius if the scanner misses an attack — one miss becomes "agent sends a real email," not "agent misclicks on a fake form."
- Credential/session attacks are explicitly out of scope (row 8 above) — the current architecture has zero mitigations for this category, and pretending otherwise would be dishonest in front of judges.
- SSO/OAuth automation is actively fought by providers on purpose: OTP steps, "is this you?" push confirmations, and bot-fingerprinting (e.g. Google's "This browser may not be secure" block) are designed specifically to stop automated login. This isn't a hackathon time constraint — it's adversarial by design.
- Google's ToS prohibits automated access to authenticated sessions outside official APIs.

**Three categories, not one blanket rule:**
- **Category A — no account at all.** Most government benefits/bill-dispute forms. This is Proxy's current scope, and it's the actual majority of the target user's real need — not a limitation, the correct wedge.
- **Category B — creates a new account on the target site itself** (not "sign in with Google"). Same risk profile as Category A, still just form-filling.
- **Category C — agent operates inside an existing broad-privilege session.** The dangerous one. Avoided entirely for now.

**If extending post-hackathon:** integrate via official OAuth-scoped APIs (Gmail API, Calendar API) with narrow, explicit, user-granted, revocable scopes — not "agent drives a signed-in browser session." Same tool-calling architecture, a genuinely safer credential model. Nontrivial but well-understood engineering (secure token storage, minimum scope requests, refresh/revocation handling via `google-auth-oauthlib` or Authlib) — a few focused days done right, not a recurring hard problem.

**Conclusion for the pitch:** staying non-signed-in does not diminish scope. It targets exactly the population and exactly the form-type the pitch is built around — highest need, lowest risk, simultaneously. Say this explicitly if a judge asks "why doesn't it use my Gmail/Calendar."

## PII Handling — Explicit Human-Gated Interrupt

**Built and tested** (see [details.md](details.md) Entry 12) — not on the roadmap, live in the codebase.

**Policy rule:** SSN, DOB, financial account numbers, and medical info are hardcoded as always-high-risk in the Action Policy Engine (`policy/pii.py`), regardless of scanner confidence score. Not detected reactively -- enforced proactively, purely from the field's identity, before any value exists.

**Mechanism (exact flow, as implemented):**
1. The agent proposes a `type` action targeting a field the gate classifies as PII (`policy/gate.py`, checked before the general per-action-type policy).
2. The gate returns `requires_pii_input=True` -- distinct from `requires_human_review`, because the human's role here isn't "approve or deny," it's "supply the actual value directly."
3. The agent loop (`agent/loop.py` / `agent/loop_playwright.py`) **discards the agent's own proposed value entirely** -- it's never read, never logged -- and yields a `pii_required` event, then blocks on `.send()`/`.asend()` waiting for a human-supplied string.
4. The backend (`backend/main.py`) exposes this as `POST /task/{id}/provide-pii` -- the raw value goes straight from that request body into the paused generator via `asyncio.Queue`, and is never passed to `append_event()` or any log call anywhere in the file.
5. The frontend (`frontend/index.html`) shows a dedicated input (password-masked for SSN/account-number-style fields, plain text for others like DOB) with an explicit **"Done — Continue"** button -- never auto-resumes on typing, since a false-positive resume (submitting before the user finished) is a real safety failure for this user base, not a minor UX bug.
6. On resume, the loop `continue`s to a fresh `decide_next_action()` call -- it does not resume a remembered script, it re-decides based on current state.

**Security framing for the slide:** "Sensitive fields never enter the agent's context at all" is a stronger claim than "we detect misuse of sensitive fields" -- even a fully-hijacked agent can't exfiltrate PII it never had access to.

**Verified, not just implemented:** a dedicated test (`eval/ws_smoke_test_pii.py`) drives a full task through the real backend and asserts programmatically that the actual value never appears anywhere in the audit log -- not a visual check, an `assert` that fails the test if it ever does. Confirmed working in all three execution paths: the mock generator directly, the real FastAPI+WebSocket backend, and a real headless Chromium browser via Playwright.

## Roadmap (deliberately not built, and why)

**Voice input/output (multimodal accessibility)** — cut for the hackathon build, kept on the roadmap. All four roles are fully allocated per the sprint plan, with a feature freeze Day 6 noon; voice wasn't worth displacing anything already in progress.
- If built later: browser-native `SpeechRecognition` (task input) and `SpeechSynthesis` (narration read aloud) — both client-side, free, no backend cost. Estimated ~4-6 hrs for basic input + read-aloud.
- Narration read-aloud is arguably the bigger UX win of the two, given the target user base — worth prioritizing over voice input if only one gets built.
- **Do NOT use voice for PII fields** (SSN, DOB, etc.), even post-hackathon. Voice transcription is an extra hop (audio → text → field) with its own error/leak surface — this isn't a shortcut to relax later, it's a permanent constraint given who this product serves.
