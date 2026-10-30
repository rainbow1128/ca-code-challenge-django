from datetime import datetime, timedelta, timezone

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from catalog.models import Brand, Industry, Review, Reviewer

URL = reverse("api-brand-list")
T0 = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)


class Data:
    """Small builders; every test creates exactly the rows it talks about."""

    def setUp(self):
        self.client = APIClient()
        self.insurance = Industry.objects.create(name="Insurance", slug="insurance")
        self.finance = Industry.objects.create(name="Finance", slug="finance")
        self.retail = Industry.objects.create(name="Retail", slug="retail")
        self.sarah = Reviewer.objects.create(username="sarah_k", display_name="Sarah K.")
        self._n = 0

    def brand(self, slug, industry=None, ratings=(), **fields):
        b = Brand.objects.create(
            name=fields.pop("name", slug.replace("-", " ").title()), slug=slug,
            industry=industry or self.insurance, published_at=T0, **fields,
        )
        for rating in ratings:
            self.review(b, rating)
        return b

    def review(self, brand, rating, minutes=None, **fields):
        self._n += 1
        return Review.objects.create(
            brand=brand, reviewer=self.sarah, rating=rating,
            slug=fields.pop("slug", f"review-{self._n}"),
            title=fields.pop("title", f"Review {self._n}"),
            body_html=fields.pop("body_html", "<p>Fine.</p>"),
            published_at=T0 + timedelta(minutes=self._n if minutes is None else minutes),
            **fields,
        )

    def get(self, **params):
        return self.client.get(URL, params)

    def slugs(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        return [row["slug"] for row in response.json()["results"]]


class ResponseDataTests(Data, TestCase):
    def test_card_contains_everything_needed(self):
        acme = self.brand("acme", headquarters="Hartford, CT",
                          short_description="A long-running insurer.")
        self.review(acme, 3)
        self.review(acme, 5, title="Smooth claim", slug="smooth-claim", location="Denver, CO",
                    body_html="<p>Filed <strong>online</strong> in 10 minutes &amp; done.</p>")

        body = self.get().json()

        self.assertEqual(body["results"], [{
            "slug": "acme",
            "name": "Acme",
            "industry": {"slug": "insurance", "name": "Insurance"},
            "headquarters": "Hartford, CT",
            "short_description": "A long-running insurer.",
            "average_rating": 4.0,
            "review_count": 2,
            "top_review": {
                "slug": "smooth-claim",
                "title": "Smooth claim",
                "rating": 5,
                "snippet": "Filed online in 10 minutes & done.",
                "reviewer_name": "Sarah K.",
                "location": "Denver, CO",
                "published_at": "2026-05-19T12:02:00Z",
            },
        }])

    def test_envelope(self):
        self.brand("acme", ratings=[4])
        body = self.get().json()
        self.assertEqual(
            {k: v for k, v in body.items() if k != "results"},
            {
                "count": 1, "page": 1, "total_pages": 1, "next": None, "previous": None,
                "ordering": "-average_rating",
                "industries": [
                    {"slug": "finance", "name": "Finance"},
                    {"slug": "insurance", "name": "Insurance"},
                    {"slug": "retail", "name": "Retail"},
                ],
            },
        )

    def test_rating_and_count_are_calculated_from_reviews(self):
        acme = self.brand("acme", ratings=[5, 4, 4], wp_average_rating="1.0")
        row = self.get().json()["results"][0]
        self.assertEqual((row["average_rating"], row["review_count"]), (4.33, 3))
        self.assertNotIn("wp_average_rating", row)

        self.review(acme, 1)
        row = self.get().json()["results"][0]
        self.assertEqual((row["average_rating"], row["review_count"]), (3.5, 4))

    def test_brand_without_reviews(self):
        self.brand("new-brand")
        row = self.get().json()["results"][0]
        self.assertEqual(
            (row["average_rating"], row["review_count"], row["top_review"]), (None, 0, None)
        )

    def test_long_review_snippet_is_cut_at_30_words(self):
        acme = self.brand("acme")
        self.review(acme, 5, body_html="<p>" + " ".join(f"w{i}" for i in range(50)) + "</p>")
        snippet = self.get().json()["results"][0]["top_review"]["snippet"]
        self.assertEqual(snippet, " ".join(f"w{i}" for i in range(30)) + "…")

    def test_only_get_is_allowed(self):
        self.assertEqual(self.client.post(URL, {}, format="json").status_code, 405)


class TopReviewTests(Data, TestCase):
    def top(self):
        return self.get().json()["results"][0]["top_review"]["slug"]

    def test_highest_rating_wins_even_if_older(self):
        acme = self.brand("acme")
        self.review(acme, 5, minutes=1, slug="old-five")
        self.review(acme, 4, minutes=9, slug="new-four")
        self.assertEqual(self.top(), "old-five")

    def test_newest_wins_a_rating_tie(self):
        acme = self.brand("acme")
        self.review(acme, 5, minutes=1, slug="old-five")
        self.review(acme, 5, minutes=9, slug="new-five")
        self.review(acme, 5, minutes=5, slug="mid-five")
        self.assertEqual(self.top(), "new-five")

    def test_same_rating_and_time_falls_back_to_latest_id(self):
        acme = self.brand("acme")
        self.review(acme, 5, minutes=1, slug="first")
        self.review(acme, 5, minutes=1, slug="second")
        self.assertEqual(self.top(), "second")

    def test_each_brand_gets_its_own_top_review(self):
        a, b = self.brand("a"), self.brand("b")
        self.review(a, 5, slug="a-top")
        self.review(b, 2, slug="b-low")
        self.review(b, 4, slug="b-top")
        self.review(a, 1, slug="a-low")
        tops = {r["slug"]: r["top_review"]["slug"] for r in self.get().json()["results"]}
        self.assertEqual(tops, {"a": "a-top", "b": "b-top"})

    def test_matches_model_property(self):
        acme = self.brand("acme", ratings=[3, 5, 5, 1])
        self.assertEqual(self.top(), acme.top_review.slug)


class FilterTests(Data, TestCase):
    def setUp(self):
        super().setUp()
        self.brand("acme", self.insurance, [4])
        self.brand("shield", self.insurance, [3])
        self.brand("bank", self.finance, [5])

    def test_single_industry(self):
        self.assertEqual(self.slugs(self.get(industry="insurance")), ["acme", "shield"])

    def test_several_industries_comma_separated_or_repeated(self):
        self.assertEqual(self.slugs(self.get(industry="insurance,finance")), ["bank", "acme", "shield"])
        response = self.client.get(f"{URL}?industry=finance&industry=insurance")
        self.assertEqual(self.slugs(response), ["bank", "acme", "shield"])

    def test_blank_industry_means_all(self):
        self.assertEqual(len(self.slugs(self.get(industry=""))), 3)

    def test_count_reflects_the_filter(self):
        self.assertEqual(self.get(industry="insurance").json()["count"], 2)

    def test_unknown_industry_is_a_400(self):
        response = self.get(industry="insurance,nope")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"industry": ["Unknown industry: nope."]})


class EmptyResultTests(Data, TestCase):
    def test_no_brands_at_all(self):
        body = self.get().json()
        self.assertEqual((body["count"], body["results"], body["total_pages"]), (0, [], 1))
        self.assertEqual(len(body["industries"]), 3)

    def test_industry_without_brands(self):
        self.brand("acme", self.insurance, [4])
        body = self.get(industry="retail").json()
        self.assertEqual((body["count"], body["results"], body["next"]), (0, [], None))


class SortingTests(Data, TestCase):
    def setUp(self):
        super().setUp()
        self.brand("high-few", ratings=[5])           # 5.00, 1
        self.brand("mid-many", ratings=[4, 4, 3, 3])  # 3.50, 4
        self.brand("low-some", ratings=[2, 1])        # 1.50, 2
        self.brand("no-reviews")                      # None, 0

    def test_default_is_highest_rated_first(self):
        response = self.get()
        self.assertEqual(response.json()["ordering"], "-average_rating")
        self.assertEqual(self.slugs(response), ["high-few", "mid-many", "low-some", "no-reviews"])

    def test_rating_ascending_keeps_unrated_last(self):
        self.assertEqual(self.slugs(self.get(ordering="average_rating")),
                         ["low-some", "mid-many", "high-few", "no-reviews"])

    def test_most_reviewed_first(self):
        self.assertEqual(self.slugs(self.get(ordering="-review_count")),
                         ["mid-many", "low-some", "high-few", "no-reviews"])

    def test_least_reviewed_first(self):
        self.assertEqual(self.slugs(self.get(ordering="review_count")),
                         ["no-reviews", "high-few", "low-some", "mid-many"])

    def test_ties_are_broken_by_name(self):
        self.brand("b-tie", ratings=[4], name="B tie")
        self.brand("a-tie", ratings=[4], name="A tie")
        slugs = self.slugs(self.get(ordering="-average_rating"))
        self.assertLess(slugs.index("a-tie"), slugs.index("b-tie"))

    def test_rating_tie_prefers_more_reviews(self):
        self.brand("five-twice", ratings=[5, 5])
        self.assertEqual(self.slugs(self.get())[:2], ["five-twice", "high-few"])

    def test_invalid_ordering_is_a_400(self):
        for value in ["rating", "name", "-id", ""]:
            with self.subTest(value=value):
                response = self.get(ordering=value)
                self.assertEqual(response.status_code, 400)
                self.assertIn("ordering", response.json())


class PaginationTests(Data, TestCase):
    def setUp(self):
        super().setUp()
        # 13 insurance brands with distinct ratings so the order is known: b00 is best.
        for i in range(13):
            self.brand(f"b{i:02}", ratings=[5] * (13 - i) + [1] * i)
        self.brand("other", self.finance, [3])

    def test_twelve_per_page(self):
        first = self.get(industry="insurance").json()
        self.assertEqual((first["count"], first["page"], first["total_pages"]), (13, 1, 2))
        self.assertEqual([r["slug"] for r in first["results"]], [f"b{i:02}" for i in range(12)])

        second = self.client.get(first["next"]).json()
        self.assertEqual(second["page"], 2)
        self.assertEqual([r["slug"] for r in second["results"]], ["b12"])
        self.assertIsNone(second["next"])

    def test_links_keep_filters_and_ordering(self):
        first = self.get(industry="insurance", ordering="-review_count").json()
        self.assertIn("industry=insurance", first["next"])
        self.assertIn("ordering=-review_count", first["next"])
        self.assertIn("page=2", first["next"])
        second = self.client.get(first["next"]).json()
        self.assertIn("industry=insurance", second["previous"])
        self.assertIsNone(first["previous"])

    def test_page_size_cannot_be_changed(self):
        body = self.get(page_size=50).json()
        self.assertEqual(len(body["results"]), 12)

    def test_page_out_of_range_or_invalid_is_a_404(self):
        for page in ["3", "0", "abc"]:
            with self.subTest(page=page):
                self.assertEqual(self.get(page=page).status_code, 404)

    def test_pages_do_not_overlap(self):
        Brand.objects.filter(slug__startswith="b").update(name="Same")
        seen = []
        url = f"{URL}?ordering=review_count"
        while url:
            body = self.client.get(url).json()
            seen += [r["slug"] for r in body["results"]]
            url = body["next"]
        self.assertEqual(sorted(seen), sorted(Brand.objects.values_list("slug", flat=True)))


class QueryCountTests(Data, TestCase):
    def queries_for(self, **params):
        with CaptureQueriesContext(connection) as ctx:
            response = self.get(**params)
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries)

    def test_query_count_does_not_grow_with_brands_or_reviews(self):
        self.brand("one", ratings=[5, 4])
        few = self.queries_for()
        for i in range(11):
            self.brand(f"more-{i}", self.finance, ratings=[3, 4, 5])
        many = self.queries_for(industry="insurance,finance", ordering="-review_count")
        self.assertEqual(few, 4)   # industries, count, brands page, top reviews
        self.assertEqual(many, 4)

    def test_empty_page_skips_the_review_query(self):
        self.assertLessEqual(self.queries_for(), 3)
