import re
from datetime import datetime, timedelta, timezone

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from catalog.models import Brand, Industry, Review, Reviewer

T0 = datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc)


class Data:
    def setUp(self):
        self.insurance = Industry.objects.create(name="Insurance", slug="insurance")
        self.finance = Industry.objects.create(name="Finance", slug="finance")
        self.sarah = Reviewer.objects.create(username="sarah_k", display_name="Sarah K.")
        self.mike = Reviewer.objects.create(username="mike_t", display_name="Mike T.")
        self._n = 0

    def brand(self, slug, ratings=(), industry=None, **fields):
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
            brand=brand, reviewer=fields.pop("reviewer", self.sarah), rating=rating,
            slug=fields.pop("slug", f"{brand.slug}-review-{self._n}"),
            title=fields.pop("title", f"Review {self._n}"),
            body_html=fields.pop("body_html", "<p>Fine.</p>"),
            published_at=T0 + timedelta(minutes=self._n if minutes is None else minutes),
            **fields,
        )

    def html(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    @staticmethod
    def section(html, heading_id):
        """HTML of the <section> labelled by heading_id."""
        start = html.index(f'aria-labelledby="{heading_id}"')
        end = html.find("</section>", start)
        return html[start:end]

    @staticmethod
    def links(html, prefix):
        return re.findall(rf'href="{prefix}([^"/]+)/"', html)

    def assert_query_count(self, url, expected):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(ctx.captured_queries), expected,
                         "\n".join(q["sql"][:120] for q in ctx.captured_queries))


class LayoutTests(Data, TestCase):
    def test_every_page_has_one_h1_a_skip_link_and_landmarks(self):
        acme = self.brand("acme", [5])
        review = acme.reviews.get()
        for url in ["/", "/brand/", "/brand/acme/", f"/review/{review.slug}/"]:
            with self.subTest(url=url):
                html = self.html(url)
                self.assertEqual(html.count("<h1"), 1)
                self.assertIn('<html lang="en">', html)
                self.assertIn('<a class="skip-link" href="#main">', html)
                self.assertIn('<main id="main"', html)
                self.assertIn('<nav class="site-nav" aria-label="Primary">', html)
                self.assertIn("<footer", html)
                self.assertIn('<link rel="stylesheet" href="/static/css/main.css">', html)

    def test_home_link_is_marked_current_on_home_only(self):
        self.brand("acme")
        self.assertIn('aria-current="page"', self.html("/"))
        self.assertNotIn('aria-current="page"', self.html("/brand/acme/"))


class HomePageTests(Data, TestCase):
    def test_hero(self):
        html = self.html("/")
        self.assertInHTML('<h1 id="hero-title">Honest reviews of consumer brands</h1>', html)

    def test_top_rated_brands_best_first_limited_to_six(self):
        for i in range(7):  # b0 best ... b6 worst
            self.brand(f"b{i}", [5] * (7 - i) + [1] * i)
        self.brand("unrated")
        top = self.section(self.html("/"), "top-brands-title")
        self.assertEqual(self.links(top, "/brand/"), [f"b{i}" for i in range(6)])

    def test_unrated_brands_come_after_rated_ones(self):
        self.brand("unrated")
        self.brand("rated", [1])
        top = self.section(self.html("/"), "top-brands-title")
        self.assertEqual(self.links(top, "/brand/"), ["rated", "unrated"])
        self.assertIn("No ratings yet", top)

    def test_brand_card_content(self):
        self.brand("acme", [5, 4], name="Acme Insurance", headquarters="Hartford, CT",
                   short_description="A long-running insurer.")
        card = self.section(self.html("/"), "top-brands-title")
        self.assertIn('<a href="/brand/acme/">Acme Insurance</a>', card)
        self.assertIn('<p class="badge">Insurance</p>', card)
        self.assertIn('aria-label="Rated 4.5 out of 5"', card)
        self.assertIn("(2 reviews)", card)
        self.assertIn("Hartford, CT", card)
        self.assertIn("A long-running insurer.", card)

    def test_recent_reviews_newest_first_limited_to_six(self):
        acme = self.brand("acme")
        for i in range(8):
            self.review(acme, 4, minutes=i, slug=f"r{i}")
        recent = self.section(self.html("/"), "recent-reviews-title")
        self.assertEqual(self.links(recent, "/review/"), ["r7", "r6", "r5", "r4", "r3", "r2"])

    def test_review_card_content_and_links(self):
        acme = self.brand("acme", name="Acme")
        self.review(acme, 4, slug="smooth-claim", title="Smooth claim", reviewer=self.mike,
                    location="Denver, CO", body_html="<p>Filed <em>online</em> in minutes.</p>")
        recent = self.section(self.html("/"), "recent-reviews-title")
        self.assertIn('<a href="/review/smooth-claim/">Smooth claim</a>', recent)
        self.assertIn('Review of <a href="/brand/acme/">Acme</a>', recent)
        self.assertIn('aria-label="Rated 4 out of 5"', recent)
        self.assertIn("Filed online in minutes.", recent)
        self.assertIn("Mike T., Denver, CO", recent)
        self.assertIn('<time datetime="2026-05-19T12:01:00+00:00">May 19, 2026</time>', recent)

    def test_empty_site(self):
        html = self.html("/")
        self.assertIn("No brands yet.", html)
        self.assertIn("No reviews yet.", html)

    def test_query_count_is_constant(self):
        self.brand("one", [5])
        self.assert_query_count("/", 2)  # top brands (with stats), recent reviews
        for i in range(10):
            self.brand(f"more-{i}", [3, 4], industry=self.finance)
        self.assert_query_count("/", 2)


class BrandListPageTests(Data, TestCase):
    """The /brand/ archive: a shell for the React list, plus plain links without JS."""

    def test_mounts_the_react_list_with_the_api_url(self):
        html = self.html("/brand/")
        self.assertInHTML('<h1 id="brands-title">Brands</h1>', html)
        self.assertIn('<div id="brand-list" data-api-url="/api/brands/">', html)
        self.assertIn('<script type="module" src="/static/js/brand-list.js"></script>', html)

    def test_lists_every_brand_as_a_link_without_javascript(self):
        self.brand("zeta", name="Zeta")
        self.brand("acme", name="Acme")
        noscript = self.html("/brand/").split("<noscript>")[1].split("</noscript>")[0]
        self.assertEqual(self.links(noscript, "/brand/"), ["acme", "zeta"])

    def test_nav_marks_brands_as_current(self):
        html = self.html("/brand/")
        self.assertIn('<a href="/brand/" aria-current="page">Brands</a>', html)
        self.assertNotIn('<a href="/" aria-current="page">', html)

    def test_home_links_to_all_brands(self):
        self.brand("acme", [5])
        top = self.section(self.html("/"), "top-brands-title")
        self.assertIn('<a href="/brand/">See all brands', top)

    def test_query_count(self):
        for i in range(5):
            self.brand(f"b{i}")
        self.assert_query_count("/brand/", 1)


class BrandPageTests(Data, TestCase):
    def setUp(self):
        super().setUp()
        self.acme = self.brand(
            "acme-insurance", name="Acme Insurance Co.", headquarters="Hartford, CT",
            founded_year=1985, website_url="https://acme-insurance.example.com/about",
            short_description="A long-running insurer.",
            body_html="<p>Acme is <strong>rated A</strong>.</p>",
        )

    def test_brand_information(self):
        html = self.html("/brand/acme-insurance/")
        self.assertInHTML('<h1 id="brand-title">Acme Insurance Co.</h1>', html)
        self.assertIn("<title>Acme Insurance Co. reviews — Brand Reviews</title>", html)
        self.assertIn('<meta name="description" content="A long-running insurer.">', html)
        self.assertIn('<p class="badge">Insurance</p>', html)
        self.assertInHTML("<div><dt>Headquarters</dt><dd>Hartford, CT</dd></div>", html)
        self.assertInHTML("<div><dt>Founded</dt><dd>1985</dd></div>", html)
        self.assertIn('<a href="https://acme-insurance.example.com/about" rel="nofollow noopener">'
                      "acme-insurance.example.com</a>", html)
        self.assertIn("<p>Acme is <strong>rated A</strong>.</p>", html)  # stored HTML rendered

    def test_rating_and_count_come_from_reviews(self):
        for rating in [5, 4, 4]:
            self.review(self.acme, rating)
        html = self.html("/brand/acme-insurance/")
        self.assertIn('aria-label="Rated 4.3 out of 5"', html)
        self.assertIn("(3 reviews)", html)

    def test_lists_all_reviews_newest_first(self):
        for i in range(15):
            self.review(self.acme, 3, minutes=i, slug=f"r{i:02}")
        other = self.brand("other")
        self.review(other, 5, slug="not-acme")
        reviews = self.section(self.html("/brand/acme-insurance/"), "reviews-title")
        self.assertEqual(self.links(reviews, "/review/"), [f"r{i:02}" for i in range(14, -1, -1)])

    def test_review_item_content(self):
        self.review(self.acme, 2, slug="slow", title="Slow claim", reviewer=self.mike,
                    location="Albany, NY", body_html="<p>Took <em>weeks</em>.</p>")
        reviews = self.section(self.html("/brand/acme-insurance/"), "reviews-title")
        self.assertIn('<a href="/review/slow/">Slow claim</a>', reviews)
        self.assertIn('aria-label="Rated 2 out of 5"', reviews)
        self.assertIn("Mike T., Albany, NY", reviews)
        self.assertIn("<p>Took <em>weeks</em>.</p>", reviews)

    def test_brand_without_reviews(self):
        html = self.html("/brand/acme-insurance/")
        self.assertIn("No ratings yet", html)
        self.assertIn("(0 reviews)", html)
        self.assertIn("No reviews yet.", self.section(html, "reviews-title"))

    def test_optional_fields_are_left_out_when_empty(self):
        self.brand("bare")
        html = self.html("/brand/bare/")
        self.assertNotIn("<dl", html)
        self.assertNotIn('aria-labelledby="about-title"', html)

    def test_unicode_slug(self):
        self.brand("café-co", name="Café Co")
        self.assertInHTML('<h1 id="brand-title">Café Co</h1>', self.html("/brand/café-co/"))

    def test_query_count_does_not_grow_with_reviews(self):
        self.review(self.acme, 4)
        self.assert_query_count("/brand/acme-insurance/", 2)  # brand (+industry, stats), reviews
        for _ in range(20):
            self.review(self.acme, 3, reviewer=self.mike)
        self.assert_query_count("/brand/acme-insurance/", 2)


class ReviewPageTests(Data, TestCase):
    def setUp(self):
        super().setUp()
        self.acme = self.brand("acme", [5, 3], name="Acme", short_description="A long-running insurer.")
        self.review_ = self.review(
            self.acme, 4, slug="smooth-claim", title="Smooth claim", reviewer=self.mike,
            location="Denver, CO", body_html="<p>Filed <strong>online</strong>.</p>",
        )

    def test_review_content(self):
        html = self.html("/review/smooth-claim/")
        self.assertInHTML('<h1 id="review-title">Smooth claim</h1>', html)
        self.assertIn("<title>Smooth claim — Acme review — Brand Reviews</title>", html)
        self.assertIn('aria-label="Rated 4 out of 5"', html)
        self.assertIn("By Mike T., Denver, CO", html)
        self.assertIn('<time datetime="2026-05-19T12:03:00+00:00">May 19, 2026</time>', html)
        self.assertIn("<p>Filed <strong>online</strong>.</p>", html)

    def test_brand_link_and_summary(self):
        html = self.html("/review/smooth-claim/")
        self.assertIn('<a href="/brand/acme/"><span aria-hidden="true">&larr; </span>Acme</a>', html)
        summary = html[html.index('<aside class="brand-summary"'):]
        self.assertIn('<h2 id="brand-summary-title">About Acme</h2>', summary)
        self.assertIn('<p class="badge">Insurance</p>', summary)
        self.assertIn('aria-label="Rated 4.0 out of 5"', summary)  # (5 + 3 + 4) / 3
        self.assertIn("(3 reviews)", summary)
        self.assertIn("A long-running insurer.", summary)
        self.assertIn('href="/brand/acme/#reviews-title">Read all 3 reviews of Acme</a>', summary)

    def test_titles_are_escaped(self):
        self.review(self.acme, 4, slug="odd", title="<b>Bold</b> & co")
        html = self.html("/review/odd/")
        self.assertIn("&lt;b&gt;Bold&lt;/b&gt; &amp; co", html)
        self.assertNotIn("<b>Bold</b>", html)

    def test_query_count(self):
        self.assert_query_count("/review/smooth-claim/", 2)  # review (+reviewer), brand (+industry, stats)


class NotFoundTests(Data, TestCase):
    def test_unknown_slugs_return_the_404_page(self):
        self.brand("acme", [5])
        for url in ["/brand/nope/", "/review/nope/", "/no-such-page/"]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 404)
                self.assertTemplateUsed(response, "404.html")
                html = response.content.decode()
                self.assertInHTML("<h1>Page not found</h1>", html)
                self.assertIn('<a href="/">Go to the home page</a>', html)
                self.assertIn('<a class="skip-link" href="#main">', html)
                self.assertIn('<link rel="stylesheet" href="/static/css/main.css">', html)

    def test_brand_slug_is_not_a_review_slug(self):
        self.brand("acme", [5])
        self.assertEqual(self.client.get("/review/acme/").status_code, 404)

    def test_missing_trailing_slash_redirects_like_wordpress(self):
        self.brand("acme")
        response = self.client.get("/brand/acme")
        self.assertRedirects(response, "/brand/acme/", status_code=301)
