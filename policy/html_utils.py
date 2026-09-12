"""
Shared HTML text-extraction helper.

Pulled out of eval/scan_demo_sites.py so both the standalone sanity
script AND the real agent loop (agent/perception.py) use the exact same
extraction logic -- one implementation of "how do we turn a page into a
list of text chunks to tag as UntrustedContent," not two that could
silently drift apart.
"""

import hashlib
from html.parser import HTMLParser


_SKIP_TEXT_TAGS = {"script", "style"}


class TextAndAttrExtractor(HTMLParser):
    """Pulls out element text, alt attributes, and HTML comments as
    separate chunks -- an injection can hide in any of these, per
    person1-security/04's steganographic-delivery list.

    Deliberately SKIPS the contents of <script> and <style> tags -- this
    was a real bug found during testing (see details.md): the judge
    model correctly-but-uselessly flagged ordinary JavaScript ("this
    script intercepts the form submission...") and CSS class names as
    suspicious, because raw code describing hiding/interception reads a
    lot like an attack description out of context. Since a real browser
    never renders script/style content as visible text or exposes it to
    inner_text()/accessibility trees, an agent perceiving the page
    genuinely never sees it -- so it's correct to exclude it here too,
    not just a hack to silence false positives.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TEXT_TAGS:
            self._skip_depth += 1
        for name, value in attrs:
            if name == "alt" and value:
                self.chunks.append(value)

    def handle_endtag(self, tag):
        if tag in _SKIP_TEXT_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        stripped = data.strip()
        if stripped:
            self.chunks.append(stripped)

    def handle_comment(self, data):
        stripped = data.strip()
        if stripped:
            self.chunks.append(stripped)


def extract_chunks(html: str) -> list[str]:
    parser = TextAndAttrExtractor()
    parser.feed(html)
    return parser.chunks


def extract_chunks_from_file(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return extract_chunks(f.read())


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
