# Proxy — 10-Slide Deck Content

Ready to drop into Google Slides/Canva/PowerPoint. Each slide has: the on-slide content (keep it terse — this is what's projected) and speaker notes (what you actually say, longer). Total deck should run under 5 minutes if you're talking through it live; adjust pacing notes accordingly.

---

## Slide 1 — Title

**On slide:**
> # Proxy
> An AI agent that acts on the web for people who can't — and knows when it's being manipulated.
>
> [Team names] | AI Builders Hackathon 2026

**Speaker notes:** Just say the tagline out loud, don't read the whole thing. "We built an agent that does real work for people who need it most, with a security layer most agents don't have." Move fast — this slide is 5 seconds.

---

## Slide 2 — The Problem

**On slide:**
> ## Bureaucracy locks people out of help they're entitled to
> - **$30B+ in benefits go unclaimed every year** — often because the forms are too complex for the people who need them most
> - Elderly users, people with disabilities, non-native speakers: locked out not by eligibility, but by a web form
> - They need someone to just *do it for them*

**Speaker notes:** Lead with the human, not the tech. "Every year, elderly and disabled Americans leave billions in benefits unclaimed — not because they don't qualify, but because the form itself is the barrier." Pause here — this is the emotional anchor for the whole pitch.

---

## Slide 3 — Why Existing Tools Don't Solve This

**On slide:**
> ## The landscape has a gap
> | | Built for | Missing |
> |---|---|---|
> | Claude in Chrome, Comet | Technically fluent power users | No one to supervise it for a vulnerable user |
> | Enterprise AI guardrails (Cisco, Palo Alto, Check Point) | IT admins, internal business agents | Not built for an end user or caregiver to see/trust |
> | GetSetUp & benefits-guidance tools | Explaining the form | Never *fills* or *submits* it |
>
> **Nobody occupies the intersection: an agent that acts, for a vulnerable population, with a security layer they can actually see.**

**Speaker notes:** This slide preempts the "isn't this just Claude in Chrome?" question before a judge asks it. Say explicitly: "We're not competing with Anthropic's agent — we're building the version for people who need an agent because they can't supervise one themselves." Don't linger — 15 seconds, then move.

---

## Slide 4 — What Proxy Does

**On slide:**
> ## Give it a goal. Watch it work — on the real page.
> 1. Type a plain-language task — "Complete my housing benefits application"
> 2. **Split screen:** left side is the conversation with Proxy, right side is a live view of the actual page it's working on
> 3. Proxy reads the real page, decides its next action, and acts — no fixed script
> 4. Pauses for your approval before anything final happens — and for sensitive fields (SSN, DOB), pauses and asks *you* to type it directly
> 5. Every step is logged for later review

**Speaker notes:** This is the product walkthrough slide — gesture at the split-screen layout specifically: "Left is the conversation, right is exactly what the agent sees, live, as it works." If you have time, this is where you cut to the live demo or the video. Keep bullets short; let the demo do the talking.

---

## Slide 5 — Architecture

**On slide:**
> ## Perceive → Reason → Gate → Execute → Observe
> ```
> Page state → LLM decides next action → SECURITY GATE → Playwright acts → repeat
> ```
> - Real agentic loop — every decision is made fresh, based on current state, not a hardcoded script
> - Every single action passes through the security gate before it executes — no exceptions

**Speaker notes:** "This is a real agent, not a scripted pipeline — the decision at every step is made dynamically." Point at the diagram, say the one-liner about "no action skips the gate," and move on. This slide exists to prove technical depth to judges who know what to look for.

---

## Slide 6 — The Security Differentiator (Three-Layer Defense)

**On slide:**
> ## We assume detection fails sometimes — and built for it anyway
> 1. **Detection** — heuristic + LLM-judge scanner catches known manipulation patterns
> 2. **Containment** — a strict allowlist caps what the agent can physically do, even if detection misses something
> 3. **Escalation** — anything uncertain pauses for a human, instead of guessing
>
> Plus: **PII fields (SSN, DOB, account numbers) never enter the agent's context at all** — a human types them directly. Even a fully-hijacked agent has nothing to leak.

**Speaker notes:** This is your strongest slide — spend real time here. Say: "Most AI security is 'we detect bad behavior.' Ours is: we assume detection sometimes fails, and two other layers still hold when it does." Then land the PII point hard: "For the most sensitive fields, we don't just watch for misuse — we make it structurally impossible, because the AI never sees the value in the first place." This is the line most judges will remember.

---

## Slide 7 — Threat Model & What's Deliberately Out of Scope

**On slide:**
> ## Mapped to OWASP's Top 10 for LLM Applications
> | Attack | Status |
> |---|---|
> | Indirect prompt injection | ✅ Core demo |
> | Excessive agency | ✅ Built structurally |
> | Data exfiltration via side channel | ✅ Covered |
> | Direct injection, tool manipulation, goal drift | 🗺️ Roadmap |
> | Credential/session attacks | ❌ Explicitly out — no login flows, by design |
>
> Naming what we didn't build is a design decision, not a gap.

**Speaker notes:** "We know exactly what this doesn't defend against yet, and we chose that boundary on purpose — a signed-in session turns a missed detection into real damage, so we stayed out of that until the security model is stricter." This slide is a credibility move — judges with a security background specifically look for teams who know their own limits.

---

## Slide 8 — Live Demo

**On slide:**
> ## Watch it work — then watch it get attacked
> [Embed video or "live demo now"]
> 1. Clean run: right panel shows the real live page as Proxy fills it, left panel narrates each step
> 2. PII moment: Proxy pauses, right panel freezes on the current page, left panel asks the human to type the sensitive value directly
> 3. Attack run: the right panel switches from a page view to a **red "Content Flagged" view** — showing the exact hidden text that tried to manipulate the agent

**Speaker notes:** If live, this is where you actually run it — rehearsed, both scenarios ready to go. If pre-recorded, this is where the video plays. Either way, narrate along the split screen: "Right side is exactly what the agent is looking at, live." Then: "Notice it just paused and asked me to type this myself, not the AI — that's the PII gate." Then trigger the attack run and let the panel visibly flip to red with the flagged text on screen — don't talk over that moment, let it land in silence for a second. This is the single most memorable beat in the whole pitch.

---

## Slide 9 — Team & Roles

**On slide:**
> ## The team
> - **[You]** — Security/Guardrail Engineer: injection scanner, policy engine, PII-gating flow
> - **[Devon]** — Agent Reasoning: the perceive-decide-act loop, LLM tool-calling
> - Frontend, backend, and demo infrastructure built collaboratively
>
> [Photos/names/short bios if you have them]

**Speaker notes:** Quick, human moment — put faces to the work. If it's just the two of you, say so plainly and own it: "A two-person team, and we still shipped a working agent with a security model most enterprise products don't have."

---

## Slide 10 — Impact & What's Next

**On slide:**
> ## This is the blueprint for trustworthy agentic AI
> - Real problem: agents that act on behalf of people who can't verify the action themselves
> - Real technical depth: a working agent + genuine security architecture, not a prompt wrapper
> - **Next:** direct prompt injection defense, OAuth-scoped account integrations, voice input/narration for accessibility, expansion beyond benefits forms to healthcare and appointment systems

**Speaker notes:** Close on the thesis, not a feature list: "AI agents are only going to get more capable. The question that matters is whether they're safe enough to act for the people who need them most. We think this is what that looks like." End there — don't trail off into more roadmap detail, let the line land and stop talking.

---

## Timing guide (if presenting live, ~5 min total)
- Slides 1-4: ~60 sec (fast, this is setup)
- Slide 5: ~20 sec
- Slide 6: ~45 sec (your best slide — don't rush it)
- Slide 7: ~25 sec
- Slide 8 (demo): ~2 min (the actual centerpiece)
- Slide 9: ~15 sec
- Slide 10: ~30 sec

## Notes on sourcing
Every claim above is pulled from what's actually built and tested in this repo (`details.md`, `THREAT_MODEL.md`) or from the market research done earlier in this project — nothing here is aspirational except Slide 10's "what's next," which is explicitly labeled as future work, not present capability. Don't let the deck imply anything is built that isn't (see `THREAT_MODEL.md`'s roadmap section for what's honestly still open).
