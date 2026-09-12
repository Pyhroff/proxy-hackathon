"""
Perception layer (Person 2's territory).

Right now this reads a static local HTML file to simulate "the agent
looked at a page" -- there is no real browser yet. When Playwright is
wired in (see learning/person1-security/07-playwright-output-format-for-tagging.md
for what that output actually looks like), swap read_page_content() and
extract_form_fields() to call Playwright's inner_text()/accessibility
snapshot instead of reading a file. Everything downstream (the loop,
the gate) does not need to change -- they only care about the
UntrustedContent list and the field/selector lists this module returns.
"""

import re

from policy.html_utils import extract_chunks_from_file, content_hash
from policy.models import UntrustedContent


def read_page_content(html_path: str) -> list[UntrustedContent]:
    """Extract every text chunk from the page and tag it as untrusted,
    exactly as the real Playwright-backed version will -- this is the
    step that makes 'never trust content, only trust code' real."""
    chunks = extract_chunks_from_file(html_path)
    return [
        UntrustedContent(
            content=chunk,
            source="scraped_page",
            trust_level="low",
            content_hash=content_hash(chunk),
        )
        for chunk in chunks
    ]


def extract_form_fields(html_path: str) -> list[str]:
    """Very small regex-based stand-in for 'what fields exist on this
    page.' Returns a list of input element ids in document order. A real
    Playwright-backed version would instead query the DOM/accessibility
    tree directly."""
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    return re.findall(r'<input[^>]*\bid="([^"]+)"', html)


def find_submit_selector(html_path: str) -> str | None:
    with open(html_path, encoding="utf-8") as f:
        html = f.read()
    match = re.search(r'<button[^>]*\btype="submit"[^>]*\bid="([^"]+)"', html)
    return match.group(1) if match else None
