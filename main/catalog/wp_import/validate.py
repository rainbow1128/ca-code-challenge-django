"""Turn a raw WPSnapshot into model field values, or fail with every error.

Nothing here writes to the database. Either the whole snapshot is valid and
an ImportPlan comes back, or ValidationFailed lists every problem found, so
one run shows all of them instead of one per attempt.

Foreign keys are still WordPress IDs here (``industry_wp_id``,
``brand_wp_id``, ``reviewer_wp_id``); the runner swaps them for Django
primary keys after the parent rows are saved.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote

from django.core.exceptions import ValidationError

from catalog.html import make_short_description, sanitize_html, to_plain_text
from catalog.models import Brand, Industry, Review, Reviewer

_WHOLE_NUMBER = re.compile(r"^\d+$")


class ValidationFailed(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__(f"{len(errors)} invalid record(s) in the WordPress data.")


@dataclass
class ImportPlan:
    industries: dict[int, dict] = field(default_factory=dict)
    brands: dict[int, dict] = field(default_factory=dict)
    reviewers: dict[int, dict] = field(default_factory=dict)
    reviews: dict[int, dict] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class _Collector:
    def __init__(self):
        self.errors = []

    def add(self, label, message):
        self.errors.append(f"{label}: {message}")

    def check_fields(self, label, model, values, exclude=()):
        """Run the model's own field validation (max_length, URL, slug, ranges).

        None values are skipped: they are either allowed (optional fields) or
        already reported with a clearer message.
        """
        skip = set(exclude) | {k for k, v in values.items() if v is None}
        instance = model(**{k: v for k, v in values.items() if k not in skip})
        # Only validate fields supplied here; FKs are resolved at write time.
        not_supplied = {f.name for f in model._meta.fields if f.name not in values or f.name in skip}
        try:
            instance.clean_fields(exclude=list(not_supplied))
        except ValidationError as exc:
            for name, messages in exc.message_dict.items():
                for message in messages:
                    self.add(label, f"{name}: {message}")


def _label(kind, wp_id, slug=None):
    return f"{kind} wp_id={wp_id}" + (f" ({slug})" if slug else "")


def _slug(raw):
    # WordPress stores non-ASCII slugs percent-encoded ("caf%c3%a9"); the
    # URL Django sees is decoded, so store the decoded form.
    return unquote(raw or "").strip()


def _datetime_utc(value, label, errors):
    # post_date_gmt is UTC. A zero date comes back from MariaDB as a string.
    if not isinstance(value, datetime):
        errors.add(label, f"published date is missing or invalid ({value!r})")
        return None
    return value.replace(tzinfo=timezone.utc)


def _optional_int(raw, name, label, errors):
    text = (raw or "").strip()
    if not text:
        return None
    if not _WHOLE_NUMBER.match(text):
        errors.add(label, f"{name}: {text!r} is not a whole number")
        return None
    return int(text)


def _optional_decimal(raw, name, label, errors):
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        errors.add(label, f"{name}: {text!r} is not a number")
        return None


def _check_unique(kind, rows, key, errors):
    seen = {}
    for wp_id, values in rows.items():
        value = values[key]
        if value in seen:
            errors.add(_label(kind, wp_id), f"{key} {value!r} is also used by wp_id={seen[value]}")
        else:
            seen[value] = wp_id


def build_plan(snapshot):
    errors = _Collector()
    plan = ImportPlan()

    # -- industries ------------------------------------------------------
    for term in snapshot.industries:
        label = _label("industry", term.wp_id, term.slug)
        values = {"name": to_plain_text(term.name), "slug": _slug(term.slug)}
        errors.check_fields(label, Industry, values)
        plan.industries[term.wp_id] = values
    _check_unique("industry", plan.industries, "slug", errors)

    # -- brands ----------------------------------------------------------
    for post in snapshot.brands:
        label = _label("brand", post.wp_id, post.slug)
        body_html = sanitize_html(post.content)
        values = {
            "name": to_plain_text(post.title),
            "slug": _slug(post.slug),
            "body_html": body_html,
            "short_description": make_short_description(body_html),
            "website_url": (post.meta.get("website_url") or "").strip(),
            "founded_year": _optional_int(post.meta.get("founded_year"), "founded_year", label, errors),
            "headquarters": to_plain_text(post.meta.get("headquarters")),
            "wp_average_rating": _optional_decimal(
                post.meta.get("average_rating"), "average_rating", label, errors
            ),
            "published_at": _datetime_utc(post.published_at, label, errors),
        }
        if not post.industry_wp_ids:
            errors.add(label, "has no industry (every brand needs exactly one)")
            values["industry_wp_id"] = None
        else:
            values["industry_wp_id"] = post.industry_wp_ids[0]
            if values["industry_wp_id"] not in plan.industries:
                errors.add(label, f"industry wp_id={values['industry_wp_id']} was not found")
            if len(post.industry_wp_ids) > 1:
                plan.warnings.append(
                    f"{label}: has {len(post.industry_wp_ids)} industries; "
                    f"using the first by name (wp_id={post.industry_wp_ids[0]})"
                )
        errors.check_fields(label, Brand, values, exclude=("industry_wp_id",))
        plan.brands[post.wp_id] = values
    _check_unique("brand", plan.brands, "slug", errors)

    # -- reviewers -------------------------------------------------------
    for user in snapshot.reviewers:
        label = _label("reviewer", user.wp_id, user.login)
        values = {
            "username": user.login.strip(),
            "display_name": to_plain_text(user.display_name) or user.login.strip(),
        }
        errors.check_fields(label, Reviewer, values)
        plan.reviewers[user.wp_id] = values
    _check_unique("reviewer", plan.reviewers, "username", errors)

    # -- reviews ---------------------------------------------------------
    for post in snapshot.reviews:
        label = _label("review", post.wp_id, post.slug)
        rating_raw = (post.meta.get("rating") or "").strip()
        if not rating_raw:
            errors.add(label, "rating is missing")
            rating = None
        else:
            rating = _optional_int(rating_raw, "rating", label, errors)

        brand_raw = (post.meta.get("brand") or "").strip()
        brand_wp_id = _optional_int(brand_raw, "brand", label, errors) if brand_raw else None
        if brand_wp_id is None:
            if not brand_raw:
                errors.add(label, "brand is missing")
        elif brand_wp_id not in plan.brands:
            errors.add(label, f"brand wp_id={brand_wp_id} is not a published brand")

        if post.author_wp_id not in plan.reviewers:
            errors.add(label, f"author wp_id={post.author_wp_id} was not found in wp_users")
        else:
            reviewer_name = to_plain_text(post.meta.get("reviewer_name"))
            display_name = plan.reviewers[post.author_wp_id]["display_name"]
            if reviewer_name and reviewer_name != display_name:
                # reviewer_name is a copy of the author's name, so it isn't imported.
                plan.warnings.append(
                    f"{label}: reviewer_name {reviewer_name!r} differs from the author's "
                    f"display name {display_name!r}; the author's name is used"
                )

        values = {
            "title": to_plain_text(post.title),
            "slug": _slug(post.slug),
            "body_html": sanitize_html(post.content),
            "rating": rating,
            "location": to_plain_text(post.meta.get("reviewer_location")),
            "published_at": _datetime_utc(post.published_at, label, errors),
            "brand_wp_id": brand_wp_id,
            "reviewer_wp_id": post.author_wp_id,
        }
        errors.check_fields(label, Review, values, exclude=("brand_wp_id", "reviewer_wp_id"))
        plan.reviews[post.wp_id] = values
    _check_unique("review", plan.reviews, "slug", errors)

    if errors.errors:
        raise ValidationFailed(errors.errors)
    return plan
