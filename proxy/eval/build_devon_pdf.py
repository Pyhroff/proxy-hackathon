"""
Generates DEVON_ARCHITECTURE.pdf -- minimal, plain-text reference scoped
to ONLY Devon's work: reasoning + owning the Playwright integration.
Not part of the running application; a one-off doc-generation script.

Run with: python eval/build_devon_pdf.py
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Preformatted, HRFlowable
)
from reportlab.lib import colors

OUT_PATH = "DEVON_ARCHITECTURE.pdf"

styles = getSampleStyleSheet()

title_style = ParagraphStyle("TitleStyle", parent=styles["Title"], fontSize=20, spaceAfter=4)
subtitle_style = ParagraphStyle("SubtitleStyle", parent=styles["Normal"], fontSize=11,
                                 textColor=colors.grey, spaceAfter=20)
h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=15, spaceBefore=18, spaceAfter=8)
body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10.5, leading=15,
                       spaceAfter=8, alignment=TA_LEFT)
bullet = ParagraphStyle("Bullet", parent=body, leftIndent=16, bulletIndent=4, spaceAfter=4)
code = ParagraphStyle("Code", parent=styles["Code"], fontSize=9, leading=12,
                       backColor=colors.HexColor("#f5f5f5"), borderPadding=8,
                       spaceAfter=10, spaceBefore=2)
note = ParagraphStyle("Note", parent=body, textColor=colors.HexColor("#555555"),
                       fontSize=9.5, leftIndent=10, spaceAfter=10)

story = []

def h(text): story.append(Paragraph(text, h1))
def p(text): story.append(Paragraph(text, body))
def bul(items):
    for item in items:
        story.append(Paragraph(f"&bull;&nbsp;&nbsp;{item}", bullet))
def cd(text): story.append(Preformatted(text, code))
def n(text): story.append(Paragraph(text, note))
def hr(): story.append(HRFlowable(width="100%", color=colors.HexColor("#cccccc"), spaceBefore=10, spaceAfter=10))

# ---------------------------------------------------------------------------
story.append(Paragraph("Proxy — Devon's Scope", title_style))
story.append(Paragraph("Your two jobs: real reasoning, and owning the Playwright integration.", subtitle_style))

h("Your Two Jobs")
bul([
    "<b>Reasoning</b> — replace the mock decision function with real LLM tool-calling.",
    "<b>Playwright integration</b> — own the real-browser perception/execution layer: extend it, "
    "harden it, add stuck-detection and retry logic.",
])
p("A working version of both already exists (a mock reasoner, and a tested Playwright integration "
  "against real Chromium). <b>Your job is to OWN and EXTEND these, not rewrite them from scratch.</b> "
  "The Playwright code already passes real browser tests — read it first, then improve it. Don't "
  "throw it out and start over; with ~4 days left, a rewrite is the wrong call.")

h("Job 1 — Reasoning")
p("File: <b>agent/reasoner.py</b> — one function:")
cd(
"""def decide_next_action(
    task_description: str,
    fields: list[str],
    filled_fields: set[str],
    submit_selector: str | None,
) -> dict:
    \"\"\"Returns: {"action_type": "...", "payload": {...}}\"\"\"
"""
)
p("Replace the body with a real LLM call using tool-calling: give the model a tool schema "
  "(below), the task description, and current page state, and return whatever tool it chose, "
  "translated into this same {action_type, payload} shape. Signature stays the same.")

cd(
"""TOOL SCHEMA:
  click       {selector: str}
  type        {selector: str, text: str}
  navigate    {url: str}
  read_page   {}
  scroll      {}
  wait        {}
  ask_human   {reason: str}
  submit      {selector: str}"""
)
n("Reference: platform.claude.com/docs 'tool-use' overview. A tool_use block looks like "
  "{\"type\":\"tool_use\",\"name\":\"click\",\"input\":{\"selector\":\"#submit\"}} -- "
  "name -> action_type, input -> payload.")

h("Job 2 — Own the Playwright Integration")
p("Files: <b>agent/browser_runtime.py</b> (perception + execution) and "
  "<b>agent/loop_playwright.py</b> (the real-browser loop). Both currently work and are tested "
  "against real headless Chromium. Your job here:")
bul([
    "Read through both files end to end before changing anything.",
    "Add <b>stuck-detection / retry logic</b> -- if an action fails or the page doesn't change as "
    "expected, decide whether to retry, try something else, or call ask_human.",
    "Extend tool coverage if your reasoning logic needs actions beyond the current schema.",
    "Harden error handling around real-world page timing (elements not yet loaded, slow renders).",
])

h("The One Rule — Applies to Both Jobs")
p("Every action -- from reasoning OR from anything you add in the Playwright layer -- must pass "
  "through <b>policy.gate.evaluate()</b> before it executes. This already happens automatically "
  "inside the loop files. If you ever add a new code path that calls a Playwright action directly, "
  "bypassing the gate (even \"just for testing\") -- don't. That call is the entire security story "
  "of this project, and you're now the person closest to the code that could accidentally skip it.")

hr()

h("Test Your Work Alone")
cd(
"""cd proxy-hackathon
pip install -r requirements.txt
python -m playwright install chromium

# Test reasoning + mock perception (fast, no real browser):
PYTHONPATH=. python eval/run_loop_demo.py

# Test reasoning + REAL Playwright browser:
PYTHONPATH=. python eval/run_playwright_demo.py"""
)
p("Both run against demo-sites/clean and demo-sites/poisoned, printing every step. No backend or "
  "frontend needed to test your part in isolation.")

n("If something doesn't line up with this doc, check details.md (updated every time something "
  "changes) or ask.")

doc = SimpleDocTemplate(
    OUT_PATH, pagesize=letter,
    leftMargin=0.85 * inch, rightMargin=0.85 * inch,
    topMargin=0.75 * inch, bottomMargin=0.75 * inch,
)
doc.build(story)
print(f"wrote {OUT_PATH}")
