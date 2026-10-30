"""HTML cleaning for content imported from WordPress.

WordPress post content is author-controlled HTML. It is cleaned once, before
it is saved, so everything in the database is safe to render with |safe.
"""

import html
import re

import nh3
from django.utils.html import strip_tags
from django.utils.text import Truncator

ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "code", "em", "h2", "h3", "h4", "i",
    "li", "ol", "p", "pre", "strong", "ul",
}
ALLOWED_ATTRIBUTES = {"a": {"href", "title"}}
ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}

SHORT_DESCRIPTION_WORDS = 25
SHORT_DESCRIPTION_MAX_CHARS = 500  # Brand.short_description max_length

_WHITESPACE = re.compile(r"\s+")


def sanitize_html(raw):
    """Keep a small allowlist of formatting tags; drop everything else.

    Scripts, styles, event handlers and javascript: links are removed. Links
    get rel="noopener noreferrer nofollow" (user-written content).
    """
    return nh3.clean(
        raw or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer nofollow",
    ).strip()


def to_plain_text(raw):
    """HTML (or text with entities) to a single line of plain text."""
    # Put a space between block elements so "<p>a</p><p>b</p>" -> "a b".
    spaced = re.sub(r"<(?:/p|br\s*/?|/li|/h[1-6])>", " ", raw or "", flags=re.IGNORECASE)
    return _WHITESPACE.sub(" ", html.unescape(strip_tags(spaced))).strip()


def excerpt(body_html, words, max_chars=None):
    """First ``words`` words as plain text, with an ellipsis if cut."""
    text = Truncator(to_plain_text(body_html)).words(words, truncate="…")
    return Truncator(text).chars(max_chars, truncate="…") if max_chars else text


def make_short_description(body_html, words=SHORT_DESCRIPTION_WORDS):
    """Brand short description generated on first import.

    Capped at the field's length, so a body with very long "words" (e.g.
    URLs) can't make the generated value invalid.
    """
    return excerpt(body_html, words, max_chars=SHORT_DESCRIPTION_MAX_CHARS)
