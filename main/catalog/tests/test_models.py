from datetime import datetime, timezone
from decimal import Decimal

from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import TestCase

from catalog.models import Brand, Industry, Review, Reviewer

WHEN = datetime(2026, 5, 19, tzinfo=timezone.utc)


class ModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.industry = Industry.objects.create(name="Insurance", slug="insurance")
        cls.brand = Brand.objects.create(name="Acme", slug="acme", industry=cls.industry,
                                         published_at=WHEN)
        cls.empty = Brand.objects.create(name="Empty", slug="empty", industry=cls.industry,
                                         published_at=WHEN)
        cls.reviewer = Reviewer.objects.create(username="sarah_k", display_name="Sarah K.")
        for i, rating in enumerate([5, 4, 4]):
            cls.add_review(f"r{i}", rating)

    @classmethod
    def add_review(cls, slug, rating, brand=None):
        return Review.objects.create(
            brand=brand or cls.brand, reviewer=cls.reviewer, title=slug, slug=slug,
            body_html="<p>x</p>", rating=rating, published_at=WHEN,
        )

    def test_rating_stats_are_derived_from_reviews(self):
        stats = {b.slug: (b.review_count, b.average_rating) for b in Brand.objects.with_rating_stats()}
        self.assertEqual(stats["acme"], (3, Decimal("4.33")))
        self.assertEqual(stats["empty"], (0, None))

    def test_rating_stats_follow_review_changes(self):
        self.add_review("r9", 1)
        acme = Brand.objects.with_rating_stats().get(slug="acme")
        self.assertEqual((acme.review_count, acme.average_rating), (4, Decimal("3.50")))

    def test_database_rejects_rating_outside_1_to_5(self):
        with self.assertRaises(IntegrityError):
            self.add_review("bad", 6)

    def test_brand_with_reviews_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            self.brand.delete()
