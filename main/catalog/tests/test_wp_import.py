from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from catalog.models import Brand, Industry, Review, Reviewer
from catalog.wp_import.runner import ImportFailed, run_import
from catalog.wp_import.validate import ValidationFailed

from .wp_fixtures import FakeSource, brand, review, snapshot, with_meta


def counts():
    return (Industry.objects.count(), Brand.objects.count(),
            Reviewer.objects.count(), Review.objects.count())


def summary(report):
    return {name: (r.created, r.updated, r.unchanged) for name, r in report.results.items()}


class FirstImportTests(TestCase):
    def setUp(self):
        self.report = run_import(FakeSource(snapshot()))

    def test_creates_every_entity(self):
        self.assertEqual(counts(), (2, 2, 2, 3))
        self.assertEqual(summary(self.report), {
            "industries": (2, 0, 0), "brands": (2, 0, 0),
            "reviewers": (2, 0, 0), "reviews": (3, 0, 0),
        })

    def test_maps_brand_fields(self):
        acme = Brand.objects.get(wp_id=7)
        self.assertEqual(acme.slug, "acme-insurance")
        self.assertEqual(acme.industry.slug, "insurance")
        self.assertEqual(acme.founded_year, 1985)
        self.assertEqual(acme.headquarters, "Hartford, CT")
        self.assertEqual(acme.website_url, "https://acme-insurance.example.com")
        self.assertEqual(acme.wp_average_rating, Decimal("4.20"))
        self.assertEqual(acme.published_at, datetime(2026, 5, 19, 20, 29, 2, tzinfo=timezone.utc))
        self.assertEqual(acme.short_description,
                         "Acme Insurance is a long-running insurer. Second paragraph.")

    def test_blank_optional_meta_is_stored_empty(self):
        bank = Brand.objects.get(wp_id=8)
        self.assertIsNone(bank.founded_year)
        self.assertEqual(bank.website_url, "")

    def test_links_reviews_to_brand_and_reviewer(self):
        r = Review.objects.get(wp_id=13)
        self.assertEqual(r.brand.wp_id, 7)
        self.assertEqual(r.reviewer.username, "mike_t")
        self.assertEqual(r.rating, 3)
        self.assertEqual(r.location, "Denver, CO")

    def test_reports_wp_average_against_calculated(self):
        by_brand = {c.brand: c for c in self.report.ratings}
        acme = by_brand["Acme Insurance Co."]
        self.assertEqual((acme.wp_average, acme.average, acme.review_count),
                         (Decimal("4.20"), Decimal("4.00"), 2))
        self.assertTrue(acme.differs)
        self.assertFalse(by_brand["PrimePath Bank"].differs)  # WP 4.0, reviews 4.00


class ReRunTests(TestCase):
    def setUp(self):
        run_import(FakeSource(snapshot()))

    def test_second_run_writes_nothing(self):
        before = list(Review.objects.values().order_by("wp_id"))
        report = run_import(FakeSource(snapshot()))
        self.assertEqual(counts(), (2, 2, 2, 3))
        self.assertEqual(summary(report), {
            "industries": (0, 0, 2), "brands": (0, 0, 2),
            "reviewers": (0, 0, 2), "reviews": (0, 0, 3),
        })
        self.assertEqual(list(Review.objects.values().order_by("wp_id")), before)

    def test_changed_values_update_the_same_row(self):
        pk = Brand.objects.get(wp_id=7).pk
        changed = snapshot()
        changed.brands[0] = with_meta(changed.brands[0], headquarters="Boston, MA")
        changed.reviews[0] = with_meta(changed.reviews[0], rating="2")

        report = run_import(FakeSource(changed))

        self.assertEqual(report.results["brands"].updated, 1)
        self.assertEqual(report.results["brands"].changed_fields, {"headquarters"})
        self.assertEqual(report.results["reviews"].changed_fields, {"rating"})
        acme = Brand.objects.get(wp_id=7)
        self.assertEqual((acme.pk, acme.headquarters), (pk, "Boston, MA"))
        self.assertEqual(Review.objects.get(wp_id=12).rating, 2)

    def test_slug_change_updates_the_same_row(self):
        changed = snapshot()
        changed.brands[0] = replace(changed.brands[0], slug="acme")
        run_import(FakeSource(changed))
        self.assertEqual(Brand.objects.get(wp_id=7).slug, "acme")
        self.assertEqual(Brand.objects.count(), 2)

    def test_short_description_is_owned_by_django_after_create(self):
        Brand.objects.filter(wp_id=7).update(short_description="Edited in Django")
        changed = snapshot()
        changed.brands[0] = replace(changed.brands[0], content="<p>New body from WordPress.</p>")

        run_import(FakeSource(changed))

        acme = Brand.objects.get(wp_id=7)
        self.assertEqual(acme.body_html, "<p>New body from WordPress.</p>")
        self.assertEqual(acme.short_description, "Edited in Django")

    def test_review_can_move_to_another_brand(self):
        changed = snapshot()
        changed.reviews[0] = with_meta(changed.reviews[0], brand="8")
        run_import(FakeSource(changed))
        self.assertEqual(Review.objects.get(wp_id=12).brand.wp_id, 8)


class MissingAndPruneTests(TestCase):
    def setUp(self):
        run_import(FakeSource(snapshot()))
        self.without_bank = snapshot(
            brands=[brand()],
            reviews=[review(), review(wp_id=13, slug="pricey", author_wp_id=3, rating="3")],
        )

    def test_missing_rows_are_kept_and_reported(self):
        report = run_import(FakeSource(self.without_bank))
        self.assertEqual(report.results["brands"].missing, [8])
        self.assertEqual(report.results["reviews"].missing, [14])
        self.assertEqual(counts(), (2, 2, 2, 3))

    def test_prune_deletes_missing_imported_rows(self):
        report = run_import(FakeSource(self.without_bank), prune=True)
        self.assertEqual(report.results["brands"].pruned, 1)
        self.assertEqual(report.results["reviews"].pruned, 1)
        self.assertFalse(Brand.objects.filter(wp_id=8).exists())
        self.assertEqual(counts(), (2, 1, 2, 2))

    def test_prune_never_deletes_rows_created_in_django(self):
        native = Industry.objects.create(name="Travel", slug="travel")
        run_import(FakeSource(self.without_bank), prune=True)
        self.assertTrue(Industry.objects.filter(pk=native.pk).exists())

    def test_prune_refuses_when_django_rows_depend_on_the_row(self):
        bank = Brand.objects.get(wp_id=8)
        Review.objects.create(
            brand=bank, reviewer=Reviewer.objects.get(wp_id=2), title="Native",
            slug="native-review", body_html="<p>x</p>", rating=4,
            published_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        changed = snapshot(brands=[brand()], reviews=[review()])
        changed.brands[0] = with_meta(changed.brands[0], headquarters="Changed")

        with self.assertRaises(ImportFailed) as ctx:
            run_import(FakeSource(changed), prune=True)

        self.assertIn("model 'Brand'", ctx.exception.errors[0])
        self.assertIn("Review id=", ctx.exception.errors[0])
        # Whole run rolled back: nothing pruned, nothing updated.
        self.assertEqual(counts(), (2, 2, 2, 4))
        self.assertEqual(Brand.objects.get(wp_id=7).headquarters, "Hartford, CT")


class InvalidDataTests(TestCase):
    def setUp(self):
        run_import(FakeSource(snapshot()))

    def assert_rejected(self, bad_snapshot):
        before = counts()
        with self.assertRaises(ValidationFailed) as ctx:
            run_import(FakeSource(bad_snapshot))
        self.assertEqual(counts(), before)
        return ctx.exception.errors

    def test_every_error_is_reported_and_nothing_is_written(self):
        bad = snapshot()
        bad.brands[0] = with_meta(bad.brands[0], founded_year="nineteen", headquarters="Moved")
        bad.brands[1] = with_meta(bad.brands[1], website_url="not a url")
        bad.reviews[0] = with_meta(bad.reviews[0], rating="6")
        bad.reviews[1] = with_meta(bad.reviews[1], rating="4.5")
        bad.reviews[2] = with_meta(bad.reviews[2], brand="999")

        errors = self.assert_rejected(bad)

        joined = "\n".join(errors)
        self.assertEqual(len(errors), 5, joined)
        self.assertIn("brand wp_id=7 (acme-insurance): founded_year: 'nineteen' is not a whole number", joined)
        self.assertIn("brand wp_id=8 (primepath-bank): website_url:", joined)
        self.assertIn("review wp_id=12 (smooth-claim): rating:", joined)
        self.assertIn("review wp_id=13 (pricey): rating: '4.5' is not a whole number", joined)
        self.assertIn("review wp_id=14 (bank-ok): brand wp_id=999 is not a published brand", joined)
        # The valid change in the same run was not applied either.
        self.assertEqual(Brand.objects.get(wp_id=7).headquarters, "Hartford, CT")

    def test_brand_needs_an_industry(self):
        bad = snapshot()
        bad.brands[0] = replace(bad.brands[0], industry_wp_ids=())
        self.assertIn("has no industry", self.assert_rejected(bad)[0])

    def test_review_needs_rating_and_known_author(self):
        bad = snapshot()
        bad.reviews[0] = replace(with_meta(bad.reviews[0], rating=""), author_wp_id=42)
        errors = self.assert_rejected(bad)
        self.assertTrue(any("rating is missing" in e for e in errors))
        self.assertTrue(any("author wp_id=42 was not found" in e for e in errors))

    def test_zero_date_is_invalid(self):
        bad = snapshot()
        bad.reviews[0] = replace(bad.reviews[0], published_at="0000-00-00 00:00:00")
        self.assertIn("published date is missing or invalid", self.assert_rejected(bad)[0])

    def test_duplicate_slugs_in_source_are_invalid(self):
        bad = snapshot()
        bad.reviews[1] = replace(bad.reviews[1], slug="smooth-claim")
        self.assertIn("is also used by wp_id=12", self.assert_rejected(bad)[0])

    def test_database_conflict_rolls_back_everything(self):
        # A Django-created brand already owns the slug WordPress now wants.
        Brand.objects.create(
            name="Native", slug="taken", industry=Industry.objects.get(wp_id=2),
            published_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        changed = snapshot(industries=[
            *snapshot().industries, replace(snapshot().industries[0], wp_id=99, slug="new"),
        ])
        changed.brands[0] = replace(changed.brands[0], slug="taken")

        with self.assertRaises(ImportFailed):
            run_import(FakeSource(changed))

        self.assertFalse(Industry.objects.filter(wp_id=99).exists())


class WarningAndDryRunTests(TestCase):
    def test_multiple_industries_use_the_first_and_warn(self):
        snap = snapshot()
        snap.brands[0] = replace(snap.brands[0], industry_wp_ids=(5, 2))
        report = run_import(FakeSource(snap))
        self.assertEqual(Brand.objects.get(wp_id=7).industry.wp_id, 5)
        self.assertTrue(any("has 2 industries" in w for w in report.warnings))

    def test_reviewer_name_mismatch_warns_and_uses_author(self):
        snap = snapshot()
        snap.reviews[0] = with_meta(snap.reviews[0], reviewer_name="Someone Else")
        report = run_import(FakeSource(snap))
        self.assertTrue(any("differs from the author's display name" in w for w in report.warnings))
        self.assertEqual(Review.objects.get(wp_id=12).reviewer.display_name, "Sarah K.")

    def test_dry_run_reports_but_writes_nothing(self):
        report = run_import(FakeSource(snapshot()), dry_run=True)
        self.assertEqual(report.results["reviews"].created, 3)
        self.assertEqual(counts(), (0, 0, 0, 0))

    def test_html_is_sanitized_before_saving(self):
        snap = snapshot()
        snap.reviews[0] = replace(
            snap.reviews[0],
            content='<p onclick="x()">Hi<script>alert(1)</script> <a href="javascript:x">a</a></p>',
            title="Fish &amp; <b>chips</b>",
        )
        run_import(FakeSource(snap))
        r = Review.objects.get(wp_id=12)
        self.assertEqual(r.body_html, '<p>Hi <a rel="noopener noreferrer nofollow">a</a></p>')
        self.assertEqual(r.title, "Fish & chips")


@mock.patch("catalog.management.commands.import_wp.source_from_settings")
class CommandTests(TestCase):
    def test_prints_summary(self, source_factory):
        source_factory.return_value = FakeSource(snapshot())
        out = StringIO()
        call_command("import_wp", stdout=out)
        text = out.getvalue()
        self.assertIn("reviews             3        0          0", text)
        self.assertIn("Acme Insurance Co.", text)
        self.assertIn("<- differs", text)
        self.assertIn("Import committed.", text)

    def test_invalid_data_exits_with_error(self, source_factory):
        bad = snapshot()
        bad.reviews[0] = with_meta(bad.reviews[0], rating="9")
        source_factory.return_value = FakeSource(bad)
        err = StringIO()
        with self.assertRaisesMessage(CommandError, "Nothing was written."):
            call_command("import_wp", stdout=StringIO(), stderr=err)
        self.assertIn("review wp_id=12", err.getvalue())
        self.assertEqual(counts(), (0, 0, 0, 0))

    def test_dry_run_flag(self, source_factory):
        source_factory.return_value = FakeSource(snapshot())
        out = StringIO()
        call_command("import_wp", "--dry-run", stdout=out)
        self.assertIn("Dry run: all changes rolled back.", out.getvalue())
        self.assertEqual(counts(), (0, 0, 0, 0))
