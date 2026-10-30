"""Domain models for the brand-reviews catalog.

Every model has a nullable, unique ``wp_id``: the WordPress ID of the row it
was imported from. It is the stable key the importer upserts on. Rows created
in Django later simply have ``wp_id = NULL``, and the importer never touches
them (not even with ``--prune``).

Foreign keys use PROTECT: nothing is deleted as a side effect. To delete a
brand you delete its reviews first, on purpose.
"""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Count, DecimalField, IntegerField, OuterRef, Subquery
from django.db.models.functions import Cast, Coalesce


class WordPressSourced(models.Model):
    wp_id = models.PositiveBigIntegerField(
        unique=True,
        null=True,
        blank=True,
        editable=False,
        help_text="ID of the source row in WordPress. NULL for rows created in Django.",
    )

    class Meta:
        abstract = True


class Industry(WordPressSourced):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True, allow_unicode=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "industries"

    def __str__(self):
        return self.name


class BrandQuerySet(models.QuerySet):
    def with_rating_stats(self):
        """Annotate ``review_count`` and ``average_rating`` from the reviews.

        Ratings are always derived, never stored, so they can't drift from the
        reviews. ``average_rating`` is a Decimal with 2 places (NULL when the
        brand has no reviews).

        Correlated subqueries rather than a JOIN + GROUP BY: the main query
        keeps one row per brand, and when the annotations aren't used (e.g.
        the paginator's COUNT) Django leaves them out of the SQL entirely.
        """
        per_brand = Review.objects.filter(brand=OuterRef("pk")).order_by().values("brand")
        return self.annotate(
            review_count=Coalesce(
                Subquery(per_brand.annotate(n=Count("id")).values("n"), output_field=IntegerField()),
                0,
            ),
            average_rating=Subquery(
                per_brand.annotate(
                    avg=Cast(Avg("rating"), DecimalField(max_digits=3, decimal_places=2))
                ).values("avg"),
                output_field=DecimalField(max_digits=3, decimal_places=2),
            ),
        )

    def with_top_review(self):
        """Prefetch each brand's top review in one extra query (any number of brands).

        Uses Postgres DISTINCT ON (brand_id): one row per brand, the first by
        TOP_REVIEW_ORDER. Read it with ``brand.top_review``.
        """
        top_reviews = (
            Review.objects.select_related("reviewer")
            .order_by("brand_id", *TOP_REVIEW_ORDER)
            .distinct("brand_id")
        )
        return self.prefetch_related(
            models.Prefetch("reviews", queryset=top_reviews, to_attr="_top_reviews")
        )

    def for_cards(self, *, top_review=True):
        """Everything a brand card shows: industry, rating stats and (unless
        ``top_review=False``) the top review.

        The brand body isn't shown on a card, so it isn't loaded.
        """
        brands = self.select_related("industry").defer("body_html").with_rating_stats()
        return brands.with_top_review() if top_review else brands

    def ordered_by(self, key):
        """Apply one of BRAND_ORDERINGS (needs with_rating_stats())."""
        return self.order_by(*BRAND_ORDERINGS[key])


# "Top" review: highest rating; on a tie the newest; then the highest id so
# the choice is always deterministic.
TOP_REVIEW_ORDER = ("-rating", "-published_at", "-id")

# Brand orderings shared by the API and the pages. Each ends with name and id,
# so the order is total (pages never overlap). Unrated brands sort last when
# ordering by rating.
_RATING_DESC = models.F("average_rating").desc(nulls_last=True)
_RATING_ASC = models.F("average_rating").asc(nulls_last=True)
_TIE_BREAK = ("name", "id")
BRAND_ORDERINGS = {
    "-average_rating": (_RATING_DESC, "-review_count", *_TIE_BREAK),
    "average_rating": (_RATING_ASC, "-review_count", *_TIE_BREAK),
    "-review_count": ("-review_count", _RATING_DESC, *_TIE_BREAK),
    "review_count": ("review_count", _RATING_DESC, *_TIE_BREAK),
}


class Brand(WordPressSourced):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, allow_unicode=True)
    industry = models.ForeignKey(Industry, on_delete=models.PROTECT, related_name="brands")
    body_html = models.TextField(blank=True, help_text="Sanitized HTML.")
    short_description = models.CharField(
        max_length=500,
        blank=True,
        help_text="Generated from the body on first import; owned by Django after that.",
    )
    website_url = models.URLField(max_length=500, blank=True)
    founded_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1800), MaxValueValidator(2100)],
    )
    headquarters = models.CharField(max_length=200, blank=True)
    wp_average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
        editable=False,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("5"))],
        help_text="WordPress's hand-entered average. For comparison only; never displayed.",
    )
    published_at = models.DateTimeField()

    objects = BrandQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(founded_year__isnull=True)
                | models.Q(founded_year__gte=1800, founded_year__lte=2100),
                name="brand_founded_year_range",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def top_review(self):
        """Highest-rated review, newest first on ties (see TOP_REVIEW_ORDER).

        Free when the queryset used with_top_review(); otherwise one query.
        """
        if hasattr(self, "_top_reviews"):
            return self._top_reviews[0] if self._top_reviews else None
        return self.reviews.select_related("reviewer").order_by(*TOP_REVIEW_ORDER).first()


class Reviewer(WordPressSourced):
    """Public profile of someone who writes reviews.

    The person's account (login, password, role) lives in the auth service.
    Both sides carry the same WordPress user ID, which links them.
    """

    username = models.CharField(max_length=150, unique=True)
    display_name = models.CharField(max_length=200)

    class Meta:
        ordering = ["display_name"]

    def __str__(self):
        return self.display_name


class ReviewQuerySet(models.QuerySet):
    def with_people(self):
        """Load the brand (and its industry) and the reviewer in the same query."""
        return self.select_related("brand__industry", "reviewer")

    def recent(self):
        return self.order_by("-published_at", "-id")


class Review(WordPressSourced):
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="reviews")
    reviewer = models.ForeignKey(Reviewer, on_delete=models.PROTECT, related_name="reviews")
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=200, unique=True, allow_unicode=True)
    body_html = models.TextField(help_text="Sanitized HTML.")
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Where the reviewer was when writing this review (varies per review).",
    )
    published_at = models.DateTimeField()

    objects = ReviewQuerySet.as_manager()

    class Meta:
        ordering = ["-published_at", "-id"]
        indexes = [
            models.Index(fields=["brand", "-published_at"], name="review_brand_recent_idx"),
            models.Index(fields=["-published_at"], name="review_recent_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5),
                name="review_rating_1_to_5",
            ),
        ]

    def __str__(self):
        return self.title
