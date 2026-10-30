from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlsplit

from django import template

from catalog.html import excerpt as make_excerpt

register = template.Library()

ONE_DECIMAL = Decimal("0.1")


@register.inclusion_tag("catalog/_stars.html")
def stars(rating, show_value=True):
    """Five stars for a rating (0-5), rounded to the nearest whole star.

    A review's rating (int) is labelled "5"; a brand average (Decimal) gets
    one decimal, "3.9". Screen readers get one label ("Rated 3.9 out of 5");
    the star glyphs are hidden from them. ``None`` (no reviews) renders
    "No ratings yet".
    """
    if rating is None:
        return {"rating": None}
    if isinstance(rating, int):
        label = str(rating)
    else:
        label = str(Decimal(rating).quantize(ONE_DECIMAL, rounding=ROUND_HALF_UP))
    full = int(Decimal(rating).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    full = max(0, min(5, full))
    return {
        "rating": rating,
        "label": label,
        "full": range(full),
        "empty": range(5 - full),
        "show_value": show_value,
    }


@register.filter
def excerpt(body_html, words=24):
    """Plain-text excerpt of sanitized HTML."""
    return make_excerpt(body_html, int(words))


@register.filter
def hostname(url):
    """https://acme.example.com/path -> acme.example.com"""
    return urlsplit(url or "").hostname or url
