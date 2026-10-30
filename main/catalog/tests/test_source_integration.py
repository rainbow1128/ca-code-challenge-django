"""Reads the real WordPress MariaDB. Opt-in, because it needs the WP stack:

    docker compose run --rm -e WP_INTEGRATION_TESTS=1 --entrypoint python \
        main-wp-import manage.py test catalog.tests.test_source_integration
"""

import os
import unittest
from decimal import Decimal

from django.conf import settings
from django.test import TestCase

from catalog.models import Brand, Review
from catalog.wp_import.runner import run_import
from catalog.wp_import.source import MariaDBSource


@unittest.skipUnless(os.environ.get("WP_INTEGRATION_TESTS") == "1", "set WP_INTEGRATION_TESTS=1")
class MariaDBSourceTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = MariaDBSource(**settings.WP_SOURCE)
        cls.snapshot = cls.source.read()

    def test_reads_seeded_counts(self):
        s = self.snapshot
        self.assertEqual(
            (len(s.industries), len(s.brands), len(s.reviewers), len(s.reviews)), (5, 5, 8, 60)
        )

    def test_industries_exclude_blog_categories(self):
        self.assertNotIn("uncategorized", {i.slug for i in self.snapshot.industries})

    def test_brand_meta_and_industry(self):
        acme = next(b for b in self.snapshot.brands if b.slug == "acme-insurance")
        self.assertEqual(acme.meta["founded_year"], "1985")
        self.assertEqual(acme.meta["average_rating"], "4.2")
        self.assertEqual(acme.industry_wp_ids, (2,))
        self.assertNotIn("_founded_year", acme.meta)  # ACF field-key rows are not read

    def test_review_meta(self):
        r = next(r for r in self.snapshot.reviews if r.wp_id == 12)
        self.assertEqual(r.meta["brand"], "7")
        self.assertEqual(r.meta["rating"], "5")
        self.assertEqual(r.author_wp_id, 2)

    def test_admin_is_not_a_reviewer(self):
        self.assertNotIn("admin", {u.login for u in self.snapshot.reviewers})

    def test_full_import_is_repeatable(self):
        first = run_import(self.source)
        second = run_import(self.source)
        self.assertEqual(first.results["reviews"].created, 60)
        self.assertEqual(
            {name: (r.created, r.updated) for name, r in second.results.items()},
            {name: (0, 0) for name in second.results},
        )
        self.assertEqual(Review.objects.count(), 60)
        home = Brand.objects.with_rating_stats().get(slug="homeshield-pro")
        self.assertEqual((home.average_rating, home.wp_average_rating), (Decimal("3.08"), Decimal("3.90")))
