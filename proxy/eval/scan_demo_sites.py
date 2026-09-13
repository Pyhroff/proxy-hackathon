"""
Standalone sanity check: does the heuristic scanner actually catch the
payloads seeded in demo-sites/poisoned/application.html, and does it
leave demo-sites/clean/application.html alone?

This does NOT use Playwright (that's the real agent's job) -- it uses
the shared policy/html_utils.py extractor, close enough to sanity-check
scanner logic without any browser automation.

Run with: python eval/scan_demo_sites.py
"""

from dotenv import load_dotenv

load_dotenv()

from policy.html_utils import extract_chunks_from_file, content_hash
from policy.models import UntrustedContent
from policy.scanner import scan


def scan_site(path: str, label: str):
    chunks = extract_chunks_from_file(path)
    print(f"\n=== {label} ({path}) ===")
    print(f"{len(chunks)} text chunks extracted")

    flagged = 0
    for chunk in chunks:
        content = UntrustedContent(
            content=chunk,
            source="scraped_page",
            trust_level="low",
            content_hash=content_hash(chunk),
        )
        is_suspicious, reason = scan(content)
        if is_suspicious:
            flagged += 1
            print(f"  [FLAGGED] {reason}")
            print(f"            chunk: {chunk[:80]!r}...")

    if flagged == 0:
        print("  no chunks flagged")
    return flagged


if __name__ == "__main__":
    clean_flags = scan_site("demo-sites/clean/application.html", "CLEAN SITE")
    poisoned_flags = scan_site("demo-sites/poisoned/application.html", "POISONED SITE")

    print("\n=== SUMMARY ===")
    print(f"Clean site false positives: {clean_flags} (want: 0)")
    print(f"Poisoned site catches:      {poisoned_flags} (want: >= 3, one per seeded payload)")
