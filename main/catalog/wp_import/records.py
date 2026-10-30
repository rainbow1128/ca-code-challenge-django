"""Plain records read from WordPress, before any validation.

Values are kept as WordPress stores them (postmeta is always text), so the
validation step sees exactly what the source contains.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class WPIndustry:
    wp_id: int  # wp_terms.term_id
    name: str
    slug: str


@dataclass(frozen=True)
class WPBrand:
    wp_id: int  # wp_posts.ID
    title: str
    slug: str
    content: str
    published_at: datetime | str | None  # post_date_gmt; a str if MariaDB returns a zero date
    industry_wp_ids: tuple[int, ...]  # in the order WordPress returns them (by term name)
    meta: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WPUser:
    wp_id: int  # wp_users.ID
    login: str
    display_name: str


@dataclass(frozen=True)
class WPReview:
    wp_id: int
    title: str
    slug: str
    content: str
    published_at: datetime | str | None
    author_wp_id: int  # wp_posts.post_author
    meta: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WPSnapshot:
    """Everything one import run needs, read at a single point in time."""

    industries: list[WPIndustry]
    brands: list[WPBrand]
    reviewers: list[WPUser]  # only users who authored a published review
    reviews: list[WPReview]
