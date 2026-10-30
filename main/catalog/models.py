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
from django.db.models import Avg, Count, DecimalField
from django.db.models.functions import Cast


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
        """
        return self.annotate(
            review_count=Count("reviews"),
            average_rating=Cast(
                Avg("reviews__rating"),
                DecimalField(max_digits=3, decimal_places=2),
            ),
        )


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
