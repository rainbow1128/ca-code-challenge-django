"""Run one WordPress import: read, validate, then write in one transaction.

Order of writes (parents before children):
    Industry -> Brand -> Reviewer -> Review
With --prune, rows missing from WordPress are deleted first, children before
parents (Review -> Reviewer -> Brand -> Industry), which also frees their
slugs for the upserts that follow.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError

from catalog.models import Brand, Industry, Review, Reviewer

from .sync import SyncResult, missing_wp_ids, sync_by_wp_id
from .validate import build_plan

# Arbitrary constant: pg_advisory_xact_lock key for "WP import running".
ADVISORY_LOCK_KEY = 7_428_190_001


class ImportFailed(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(errors) + ".")


@dataclass
class RatingComparison:
    brand: str
    wp_average: Decimal | None
    average: Decimal | None  # derived from reviews
    review_count: int

    @property
    def differs(self):
        if self.wp_average is None or self.average is None:
            return self.wp_average != self.average
        # WordPress stores one decimal place; compare at that precision.
        rounded = self.average.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        return rounded != self.wp_average


@dataclass
class ImportReport:
    results: dict[str, SyncResult] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    ratings: list[RatingComparison] = field(default_factory=list)
    dry_run: bool = False


def run_import(source, *, prune=False, dry_run=False):
    """Import everything from ``source`` (anything with ``read() -> WPSnapshot``).

    Raises ValidationFailed (bad source data), ImportFailed (database refused
    the writes) or SourceError (WordPress unreachable). In every failure case
    nothing has been written.
    """
    snapshot = source.read()
    plan = build_plan(snapshot)  # raises before any write if anything is invalid

    report = ImportReport(warnings=list(plan.warnings), dry_run=dry_run)
    try:
        with transaction.atomic():
            with connection.cursor() as cur:
                # A second import waits here until the first one commits.
                cur.execute("SELECT pg_advisory_xact_lock(%s)", [ADVISORY_LOCK_KEY])
            _apply(plan, report, prune=prune)
            if dry_run:
                transaction.set_rollback(True)
    except ProtectedError as exc:
        blockers = sorted({f"{type(o).__name__} id={o.pk}" for o in exc.protected_objects})
        raise ImportFailed([
            f"--prune stopped: {exc.args[0]} Blocking rows (not from WordPress): {', '.join(blockers)}"
        ]) from exc
    except IntegrityError as exc:
        raise ImportFailed([f"database rejected the import: {exc}"]) from exc
    return report


def _apply(plan, report, *, prune):
    models_in_order = [
        ("industries", Industry, plan.industries),
        ("brands", Brand, plan.brands),
        ("reviewers", Reviewer, plan.reviewers),
        ("reviews", Review, plan.reviews),
    ]

    missing = {name: missing_wp_ids(model, rows) for name, model, rows in models_in_order}
    pruned = {}
    if prune:
        for name, model, _ in reversed(models_in_order):
            pruned[name], _ = model.objects.filter(wp_id__in=missing[name]).delete()

    def record(name, result):
        result.missing = [] if prune else missing[name]
        result.pruned = pruned.get(name, 0)
        report.results[name] = result

    result, industry_ids = sync_by_wp_id(Industry, plan.industries)
    record("industries", result)

    brand_rows = {
        wp_id: _swap_fk(values, "industry_wp_id", "industry_id", industry_ids)
        for wp_id, values in plan.brands.items()
    }
    result, brand_ids = sync_by_wp_id(Brand, brand_rows, create_only={"short_description"})
    record("brands", result)

    result, reviewer_ids = sync_by_wp_id(Reviewer, plan.reviewers)
    record("reviewers", result)

    review_rows = {}
    for wp_id, values in plan.reviews.items():
        values = _swap_fk(values, "brand_wp_id", "brand_id", brand_ids)
        review_rows[wp_id] = _swap_fk(values, "reviewer_wp_id", "reviewer_id", reviewer_ids)
    result, _ = sync_by_wp_id(Review, review_rows)
    record("reviews", result)

    brands = Brand.objects.filter(wp_id__in=list(plan.brands)).with_rating_stats().order_by("name")
    report.ratings = [
        RatingComparison(b.name, b.wp_average_rating, b.average_rating, b.review_count)
        for b in brands
    ]


def _swap_fk(values, wp_key, fk_attname, ids):
    values = dict(values)
    values[fk_attname] = ids[values.pop(wp_key)]
    return values
