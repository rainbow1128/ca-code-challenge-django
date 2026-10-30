"""A small in-memory WordPress snapshot shaped like the real data."""

from dataclasses import replace
from datetime import datetime

from catalog.wp_import.records import WPBrand, WPIndustry, WPReview, WPSnapshot, WPUser


class FakeSource:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def describe(self):
        return "fake://wordpress"

    def read(self):
        return self.snapshot


def brand(wp_id=7, slug="acme-insurance", **overrides):
    values = dict(
        wp_id=wp_id,
        title="Acme Insurance Co.",
        slug=slug,
        content="<p>Acme Insurance is a long-running insurer.</p><p>Second paragraph.</p>",
        published_at=datetime(2026, 5, 19, 20, 29, 2),
        industry_wp_ids=(2,),
        meta={
            "website_url": "https://acme-insurance.example.com",
            "founded_year": "1985",
            "headquarters": "Hartford, CT",
            "average_rating": "4.2",
        },
    )
    values.update(overrides)
    return WPBrand(**values)


def review(wp_id=12, slug="smooth-claim", brand_wp_id=7, author_wp_id=2, rating="5", **overrides):
    values = dict(
        wp_id=wp_id,
        title="Smooth claim",
        slug=slug,
        content="<p>Filed online in 10 minutes.</p>",
        published_at=datetime(2026, 5, 19, 20, 29, 13),
        author_wp_id=author_wp_id,
        meta={
            "rating": rating,
            "reviewer_name": "Sarah K." if author_wp_id == 2 else "Mike T.",
            "reviewer_location": "Denver, CO",
            "brand": str(brand_wp_id),
        },
    )
    values.update(overrides)
    return WPReview(**values)


def snapshot(**overrides):
    values = dict(
        industries=[
            WPIndustry(wp_id=2, name="Insurance", slug="insurance"),
            WPIndustry(wp_id=5, name="Finance", slug="finance"),
        ],
        brands=[
            brand(),
            brand(
                wp_id=8, slug="primepath-bank", title="PrimePath Bank",
                content="<p>PrimePath Bank is a regional bank.</p>", industry_wp_ids=(5,),
                meta={"website_url": "", "founded_year": "", "headquarters": "New York, NY",
                      "average_rating": "4.0"},
            ),
        ],
        reviewers=[
            WPUser(wp_id=2, login="sarah_k", display_name="Sarah K."),
            WPUser(wp_id=3, login="mike_t", display_name="Mike T."),
        ],
        reviews=[
            review(),
            review(wp_id=13, slug="pricey", author_wp_id=3, rating="3"),
            review(wp_id=14, slug="bank-ok", brand_wp_id=8, rating="4"),
        ],
    )
    values.update(overrides)
    return WPSnapshot(**values)


def with_meta(record, **meta):
    return replace(record, meta={**record.meta, **meta})
