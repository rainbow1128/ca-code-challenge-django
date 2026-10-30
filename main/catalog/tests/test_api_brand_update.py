from datetime import UTC, datetime, timedelta

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from ca_shared import tokens
from catalog.models import Brand, Industry, Review, Reviewer

ISSUER, AUDIENCE = "test-auth", "test-main"
URL = "/api/brands/acme/"


class BrandUpdateTests(TestCase):
    """PATCH /api/brands/<slug>/: editors only, verified with the public key."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.key = tokens.generate_private_key()  # stands in for the auth service's key
        public_pem = tokens.public_key_to_pem(cls.key).decode()
        cls._settings = override_settings(
            CA_SHARED_AUTH={"PUBLIC_KEY": public_pem, "ISSUER": ISSUER, "AUDIENCE": AUDIENCE}
        )
        cls._settings.enable()

    @classmethod
    def tearDownClass(cls):
        cls._settings.disable()
        super().tearDownClass()

    def setUp(self):
        self.client = APIClient()
        industry = Industry.objects.create(name="Insurance", slug="insurance")
        self.brand = Brand.objects.create(
            name="Acme", slug="acme", industry=industry, short_description="Original.",
            published_at=datetime(2026, 5, 19, tzinfo=UTC),
        )
        reviewer = Reviewer.objects.create(username="sarah_k", display_name="Sarah K.")
        Review.objects.create(brand=self.brand, reviewer=reviewer, title="Fine", slug="fine",
                              body_html="<p>Fine.</p>", rating=4, published_at=datetime(2026, 5, 20, tzinfo=UTC))

    def token(self, role="editor", *, key=None, lifetime=timedelta(minutes=15), **kwargs):
        token, _ = tokens.issue_token(
            key or self.key, user_id=kwargs.pop("user_id", 1), role=role,
            issuer=kwargs.pop("issuer", ISSUER), audience=kwargs.pop("audience", AUDIENCE),
            lifetime=lifetime, **kwargs,
        )
        return token

    def patch(self, body, token=None, url=URL, **headers):
        if token:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        return self.client.patch(url, body, format="json", **headers)

    def assert_unchanged(self):
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.short_description, "Original.")

    # -- Allowed -------------------------------------------------------------

    def test_editor_updates_the_short_description(self):
        response = self.patch({"short_description": "  New text.  "}, self.token("editor"))

        self.assertEqual(response.status_code, 200)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.short_description, "New text.")
        self.assertEqual(response.json()["short_description"], "New text.")
        # Same card shape as the list endpoint.
        self.assertEqual(response.json()["slug"], "acme")
        self.assertEqual((response.json()["average_rating"], response.json()["review_count"]), (4.0, 1))
        self.assertEqual(response.json()["top_review"]["slug"], "fine")

    def test_editor_can_clear_it(self):
        self.assertEqual(self.patch({"short_description": ""}, self.token()).status_code, 200)
        self.brand.refresh_from_db()
        self.assertEqual(self.brand.short_description, "")

    def test_update_is_logged_with_user_and_token_id(self):
        with self.assertLogs("catalog.api.views", "INFO") as logs:
            self.patch({"short_description": "New."}, self.token(user_id=7))
        self.assertIn("by user 7 (editor)", logs.output[0])

    def test_only_the_short_description_changes(self):
        self.patch({"short_description": "New."}, self.token())
        self.brand.refresh_from_db()
        self.assertEqual((self.brand.name, self.brand.slug), ("Acme", "acme"))

    # -- Forbidden (valid token, wrong role) -----------------------------------

    def test_reader_is_forbidden(self):
        response = self.patch({"short_description": "Hacked."}, self.token("reader"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "Your role doesn't allow this action."})
        self.assert_unchanged()

    # -- Unauthorized (no usable token) ------------------------------------------

    def assert_unauthorized(self, response, detail=None):
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["WWW-Authenticate"], 'Bearer realm="api"')
        if detail:
            self.assertEqual(response.json()["detail"], detail)
        self.assert_unchanged()

    def test_missing_token(self):
        self.assert_unauthorized(self.patch({"short_description": "x"}),
                                 "Authentication credentials were not provided.")

    def test_malformed_authorization_headers(self):
        for header in ["Bearer", "Token abc", "Bearer a b", f"Basic {self.token()}"]:
            with self.subTest(header=header):
                self.assert_unauthorized(self.patch({"short_description": "x"}, HTTP_AUTHORIZATION=header))

    def test_expired_token(self):
        old = self.token(now=datetime.now(UTC) - timedelta(minutes=30), lifetime=timedelta(minutes=15))
        self.assert_unauthorized(self.patch({"short_description": "x"}, old), "Token has expired.")

    def test_token_signed_with_another_key(self):
        forged = self.token(key=tokens.generate_private_key())
        self.assert_unauthorized(self.patch({"short_description": "x"}, forged), "Token is invalid.")

    def test_tampered_token(self):
        head, body, sig = self.token("reader").split(".")
        self.assert_unauthorized(self.patch({"short_description": "x"}, f"{head}.{body}x.{sig}"))

    def test_token_for_another_service_or_issuer(self):
        for kwargs in [{"audience": "other-service"}, {"issuer": "someone-else"}]:
            with self.subTest(**kwargs):
                self.assert_unauthorized(self.patch({"short_description": "x"}, self.token(**kwargs)))

    def test_unknown_brand_needs_authentication_first(self):
        self.assertEqual(self.patch({"short_description": "x"}, url="/api/brands/nope/").status_code, 401)
        self.assertEqual(self.patch({"short_description": "x"}, self.token("reader"),
                                    url="/api/brands/nope/").status_code, 403)
        self.assertEqual(self.patch({"short_description": "x"}, self.token(),
                                    url="/api/brands/nope/").status_code, 404)

    # -- Invalid body ------------------------------------------------------------

    def test_invalid_bodies(self):
        cases = {
            "missing field": ({}, "short_description"),
            "not a string": ({"short_description": 42}, "short_description"),
            "null": ({"short_description": None}, "short_description"),
            "too long": ({"short_description": "x" * 501}, "short_description"),
            "other field": ({"short_description": "ok", "name": "Evil"}, "name"),
        }
        for label, (body, field) in cases.items():
            with self.subTest(label):
                response = self.patch(body, self.token())
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
                self.assert_unchanged()

    def test_json_only(self):
        response = self.client.patch(URL, "short_description=x", content_type="application/x-www-form-urlencoded",
                                     HTTP_AUTHORIZATION=f"Bearer {self.token()}")
        self.assertEqual(response.status_code, 415)

    def test_only_patch(self):
        auth = {"HTTP_AUTHORIZATION": f"Bearer {self.token()}"}
        self.assertEqual(self.client.get(URL, **auth).status_code, 405)
        self.assertEqual(self.client.put(URL, {"short_description": "x"}, format="json", **auth).status_code, 405)

    # -- Public reads are unaffected ------------------------------------------------

    def test_list_and_pages_stay_public_and_ignore_bad_tokens(self):
        for url in ["/api/brands/", "/brand/acme/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
                self.assertEqual(self.client.get(url, HTTP_AUTHORIZATION="Bearer junk").status_code, 200)

    def test_edit_shows_on_the_public_list(self):
        self.patch({"short_description": "Edited."}, self.token())
        row = self.client.get("/api/brands/").json()["results"][0]
        self.assertEqual(row["short_description"], "Edited.")
