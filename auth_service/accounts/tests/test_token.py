import json
import stat
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.models import User
from accounts.signing import private_key
from ca_shared import tokens
from ca_shared.roles import Role

ISSUER, AUDIENCE = "test-auth", "test-main"
FAST_HASHER = ["django.contrib.auth.hashers.MD5PasswordHasher"]


class KeyFiles:
    """A temporary key pair on disk, like the jwt-keys job creates."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._dir = tempfile.TemporaryDirectory()
        cls.key = tokens.generate_private_key()
        cls.private_file = Path(cls._dir.name) / "private.pem"
        cls.private_file.write_bytes(tokens.private_key_to_pem(cls.key))
        cls._settings = override_settings(
            JWT_PRIVATE_KEY_FILE=str(cls.private_file), JWT_ISSUER=ISSUER, JWT_AUDIENCE=AUDIENCE,
            ACCESS_TOKEN_LIFETIME_SECONDS=600, PASSWORD_HASHERS=FAST_HASHER,
        )
        cls._settings.enable()

    @classmethod
    def tearDownClass(cls):
        cls._settings.disable()
        cls._dir.cleanup()
        super().tearDownClass()


class LoginTests(KeyFiles, TestCase):
    URL = "/api/token/"

    def setUp(self):
        self.editor = User.objects.create_user("admin", password="s3cret-pass", role=User.Role.EDITOR)
        self.reader = User.objects.create_user("sarah_k", password="s3cret-pass", role=User.Role.READER)

    def login(self, body, content_type="application/json"):
        data = json.dumps(body) if not isinstance(body, (str, bytes)) else body
        return self.client.post(self.URL, data, content_type=content_type)

    def verify(self, token):
        return tokens.verify_token(token, self.key.public_key(), issuer=ISSUER, audience=AUDIENCE)

    def test_editor_gets_a_signed_token_with_all_claims(self):
        response = self.login({"username": "admin", "password": "s3cret-pass"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual((body["token_type"], body["expires_in"], body["role"]), ("Bearer", 600, "editor"))

        claims = self.verify(body["access_token"])
        self.assertEqual((claims.user_id, claims.role), (str(self.editor.pk), Role.EDITOR))
        self.assertEqual((claims.issuer, claims.audience), (ISSUER, AUDIENCE))
        self.assertEqual(claims.expires_at - claims.issued_at, timedelta(seconds=600))
        self.assertEqual(len(claims.token_id), 32)
        self.assertIn("no-store", response["Cache-Control"])

    def test_reader_gets_a_reader_token(self):
        body = self.login({"username": "sarah_k", "password": "s3cret-pass"}).json()
        self.assertEqual(self.verify(body["access_token"]).role, Role.READER)

    def test_role_comes_from_the_auth_database_at_login(self):
        self.reader.role = User.Role.EDITOR
        self.reader.save()
        body = self.login({"username": "sarah_k", "password": "s3cret-pass"}).json()
        self.assertEqual(self.verify(body["access_token"]).role, Role.EDITOR)

    def test_each_login_gets_a_new_token_id(self):
        creds = {"username": "admin", "password": "s3cret-pass"}
        a, b = (self.verify(self.login(creds).json()["access_token"]) for _ in range(2))
        self.assertNotEqual(a.token_id, b.token_id)

    def test_wrong_password_unknown_user_and_inactive_user_look_the_same(self):
        self.reader.is_active = False
        self.reader.save()
        for creds in [
            {"username": "admin", "password": "wrong"},
            {"username": "nobody", "password": "s3cret-pass"},
            {"username": "sarah_k", "password": "s3cret-pass"},  # inactive
        ]:
            with self.subTest(username=creds["username"]):
                response = self.login(creds)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json(), {"detail": "Invalid username or password."})
                self.assertNotIn("access_token", response.json())

    def test_bad_requests(self):
        cases = [
            ({}, "Both username and password are required."),
            ({"username": "admin"}, "Both username and password are required."),
            ({"username": "", "password": ""}, "Both username and password are required."),
            ({"username": "admin", "password": 123}, "Both username and password are required."),
            (["admin", "s3cret-pass"], "Body must be a JSON object."),
            ("not json", "Body must be JSON."),
            ("", "Body must be a JSON object."),
        ]
        for body, detail in cases:
            with self.subTest(body=body):
                response = self.login(body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {"detail": detail})

    def test_only_post(self):
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Allow"], "POST")

    def test_password_is_never_logged(self):
        with self.assertLogs("accounts.views", "INFO") as logs:
            self.login({"username": "admin", "password": "s3cret-pass"})
            self.login({"username": "admin", "password": "wrong-pass"})
        self.assertFalse(any("s3cret" in line or "wrong-pass" in line for line in logs.output))


class MissingKeyTests(TestCase):
    @override_settings(JWT_PRIVATE_KEY_FILE="/nonexistent/key.pem", PASSWORD_HASHERS=FAST_HASHER)
    def test_login_without_a_private_key_is_a_configuration_error(self):
        User.objects.create_user("admin", password="s3cret-pass")
        with self.assertRaisesMessage(ImproperlyConfigured, "docker compose run --rm jwt-keys"):
            self.client.post("/api/token/", {"username": "admin", "password": "s3cret-pass"},
                             content_type="application/json")


class ErrorReportTests(TestCase):
    """If login fails with an error, the error report must not contain the password."""

    @override_settings(JWT_PRIVATE_KEY_FILE="/nonexistent/key.pem", PASSWORD_HASHERS=FAST_HASHER)
    def test_password_is_masked_in_error_reports(self):
        import sys

        from django.test import RequestFactory
        from django.views.debug import ExceptionReporter

        from accounts.views import token

        User.objects.create_user("admin", password="s3cret-pass")
        request = RequestFactory().post("/api/token/", {"username": "admin", "password": "s3cret-pass"},
                                        content_type="application/json")
        try:
            token(request)
        except ImproperlyConfigured:
            reporter = ExceptionReporter(request, *sys.exc_info())
        else:
            self.fail("expected the missing key to raise")

        # The view's local variables, as an error report shows them.
        frame = next(f for f in reporter.get_traceback_data()["frames"] if f["function"] == "token")
        shown = dict(frame["vars"])
        self.assertIn("password", shown)
        self.assertNotIn("s3cret-pass", str(shown))


class GenerateKeysCommandTests(SimpleTestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.private = Path(self._dir.name) / "private" / "jwt_private.pem"
        self.public = Path(self._dir.name) / "public" / "jwt_public.pem"

    def run_command(self, *args):
        out = StringIO()
        call_command("generate_jwt_keys", "--private-key", str(self.private),
                     "--public-key", str(self.public), *args, stdout=out)
        return out.getvalue()

    def test_creates_a_matching_pair_with_safe_permissions(self):
        self.run_command()
        key = tokens.load_private_key(self.private.read_bytes())
        self.assertEqual(tokens.public_key_to_pem(key), self.public.read_bytes())
        self.assertEqual(stat.S_IMODE(self.private.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.public.stat().st_mode), 0o644)

    def test_second_run_keeps_the_existing_keys(self):
        self.run_command()
        before = self.private.read_bytes()
        self.assertIn("nothing to do", self.run_command())
        self.assertEqual(self.private.read_bytes(), before)

    def test_force_replaces_the_pair(self):
        self.run_command()
        before = self.private.read_bytes()
        self.run_command("--force")
        self.assertNotEqual(self.private.read_bytes(), before)

    def test_refuses_to_pair_with_a_lone_existing_file(self):
        self.run_command()
        self.public.unlink()
        with self.assertRaises(CommandError):
            self.run_command()

    def test_signing_key_loads_from_the_file(self):
        self.run_command()
        with override_settings(JWT_PRIVATE_KEY_FILE=str(self.private)):
            self.assertEqual(tokens.public_key_to_pem(private_key()), self.public.read_bytes())
