"""Read-only access to the WordPress MariaDB.

This module knows WordPress's table layout and nothing about Django models.
It returns a WPSnapshot of raw records; validate.py decides what is valid.
"""

import re
from collections import defaultdict

import pymysql

from .records import WPBrand, WPIndustry, WPReview, WPSnapshot, WPUser

BRAND_META_KEYS = ("website_url", "founded_year", "headquarters", "average_rating")
REVIEW_META_KEYS = ("rating", "reviewer_name", "reviewer_location", "brand")

_PREFIX = re.compile(r"^[A-Za-z0-9_]+$")


class SourceError(Exception):
    """The WordPress database could not be read."""


class MariaDBSource:
    """Reads one consistent snapshot of the WP content.

    The session is READ ONLY and the reads happen inside one
    REPEATABLE READ transaction started WITH CONSISTENT SNAPSHOT, so an edit
    made in WordPress mid-run can't mix old and new rows.
    """

    def __init__(self, *, host, port, database, user, password, table_prefix="wp_",
                 connect_timeout=10):
        if not _PREFIX.match(table_prefix):
            # The prefix is put into SQL as an identifier, so it must be safe.
            raise SourceError(f"Invalid WP table prefix: {table_prefix!r}")
        self.prefix = table_prefix
        self._connect_kwargs = dict(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            charset="utf8mb4",
            connect_timeout=connect_timeout,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def describe(self):
        kw = self._connect_kwargs
        return f"mysql://{kw['user']}@{kw['host']}:{kw['port']}/{kw['database']}"

    def read(self):
        try:
            conn = pymysql.connect(**self._connect_kwargs)
        except pymysql.MySQLError as exc:
            raise SourceError(f"Cannot connect to WordPress DB at {self.describe()}: {exc}") from exc
        try:
            with conn.cursor() as cur:
                cur.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cur.execute("SET SESSION TRANSACTION READ ONLY")
                cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
                snapshot = WPSnapshot(
                    industries=self._industries(cur),
                    brands=self._brands(cur),
                    reviewers=self._reviewers(cur),
                    reviews=self._reviews(cur),
                )
                cur.execute("COMMIT")
                return snapshot
        except pymysql.MySQLError as exc:
            raise SourceError(f"Error reading WordPress DB: {exc}") from exc
        finally:
            conn.close()

    # -- queries ---------------------------------------------------------

    def _t(self, name):
        return f"`{self.prefix}{name}`"

    def _industries(self, cur):
        cur.execute(
            f"""
            SELECT t.term_id, t.name, t.slug
            FROM {self._t('terms')} t
            JOIN {self._t('term_taxonomy')} tt ON tt.term_id = t.term_id
            WHERE tt.taxonomy = 'industry'
            ORDER BY t.term_id
            """
        )
        return [WPIndustry(wp_id=r["term_id"], name=r["name"], slug=r["slug"]) for r in cur.fetchall()]

    def _published_posts(self, cur, post_type):
        cur.execute(
            f"""
            SELECT ID, post_author, post_title, post_name, post_content, post_date_gmt
            FROM {self._t('posts')}
            WHERE post_type = %s AND post_status = 'publish'
            ORDER BY ID
            """,
            [post_type],
        )
        return cur.fetchall()

    def _meta(self, cur, post_type, keys):
        """{post_id: {meta_key: meta_value}} for published posts of a type.

        If a key appears more than once, the first row (lowest meta_id) wins,
        the same as WordPress's get_post_meta($id, $key, true).
        """
        placeholders = ", ".join(["%s"] * len(keys))
        cur.execute(
            f"""
            SELECT pm.post_id, pm.meta_key, pm.meta_value
            FROM {self._t('postmeta')} pm
            JOIN {self._t('posts')} p ON p.ID = pm.post_id
            WHERE p.post_type = %s AND p.post_status = 'publish'
              AND pm.meta_key IN ({placeholders})
            ORDER BY pm.meta_id
            """,
            [post_type, *keys],
        )
        meta = defaultdict(dict)
        for row in cur.fetchall():
            meta[row["post_id"]].setdefault(row["meta_key"], row["meta_value"])
        return meta

    def _brand_industries(self, cur):
        # Ordered by term name, as WordPress's get_the_terms() returns them;
        # the WP theme shows the first one.
        cur.execute(
            f"""
            SELECT tr.object_id, t.term_id
            FROM {self._t('term_relationships')} tr
            JOIN {self._t('term_taxonomy')} tt ON tt.term_taxonomy_id = tr.term_taxonomy_id
            JOIN {self._t('terms')} t ON t.term_id = tt.term_id
            JOIN {self._t('posts')} p ON p.ID = tr.object_id
            WHERE tt.taxonomy = 'industry'
              AND p.post_type = 'brand' AND p.post_status = 'publish'
            ORDER BY tr.object_id, t.name, t.term_id
            """
        )
        industries = defaultdict(list)
        for row in cur.fetchall():
            industries[row["object_id"]].append(row["term_id"])
        return industries

    def _brands(self, cur):
        posts = self._published_posts(cur, "brand")
        meta = self._meta(cur, "brand", BRAND_META_KEYS)
        industries = self._brand_industries(cur)
        return [
            WPBrand(
                wp_id=p["ID"],
                title=p["post_title"],
                slug=p["post_name"],
                content=p["post_content"],
                published_at=p["post_date_gmt"],
                industry_wp_ids=tuple(industries.get(p["ID"], ())),
                meta=meta.get(p["ID"], {}),
            )
            for p in posts
        ]

    def _reviewers(self, cur):
        cur.execute(
            f"""
            SELECT u.ID, u.user_login, u.display_name
            FROM {self._t('users')} u
            WHERE u.ID IN (
                SELECT post_author FROM {self._t('posts')}
                WHERE post_type = 'review' AND post_status = 'publish'
            )
            ORDER BY u.ID
            """
        )
        return [
            WPUser(wp_id=r["ID"], login=r["user_login"], display_name=r["display_name"])
            for r in cur.fetchall()
        ]

    def _reviews(self, cur):
        posts = self._published_posts(cur, "review")
        meta = self._meta(cur, "review", REVIEW_META_KEYS)
        return [
            WPReview(
                wp_id=p["ID"],
                title=p["post_title"],
                slug=p["post_name"],
                content=p["post_content"],
                published_at=p["post_date_gmt"],
                author_wp_id=p["post_author"],
                meta=meta.get(p["ID"], {}),
            )
            for p in posts
        ]
