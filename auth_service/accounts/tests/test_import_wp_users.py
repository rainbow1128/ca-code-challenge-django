from dataclasses import replace
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.models import User
from accounts.wp_import import (
    ValidationFailed,
    parse_capabilities,
    role_for,
    run_user_import,
)
from accounts.wp_source import WPAccount

ADMIN_CAPS = 'a:1:{s:13:"administrator";b:1;}'
SUBSCRIBER_CAPS = 'a:1:{s:10:"subscriber";b:1;}'

FAST_HASHER = override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])


class FakeSource:
    def __init__(self, accounts):
        self.accounts = accounts

    def describe(self):
        return "fake://wordpress"

    def read(self):
        return self.accounts


def wp_accounts():
    return [
        WPAccount(1, "admin", "admin@example.com", "admin", ADMIN_CAPS),
        WPAccount(2, "sarah_k", "sarah@example.com", "Sarah K.", SUBSCRIBER_CAPS),
        WPAccount(3, "mike_t", "mike@example.com", "Mike T.", SUBSCRIBER_CAPS),
    ]


class CapabilitiesTests(SimpleTestCase):
    def test_parses_wordpress_role_arrays(self):
        self.assertEqual(parse_capabilities(ADMIN_CAPS), {"administrator"})
        self.assertEqual(
            parse_capabilities('a:2:{s:6:"editor";b:1;s:10:"subscriber";b:0;}'), {"editor"}
        )
        self.assertEqual(parse_capabilities("a:0:{}"), set())

    def test_rejects_anything_unexpected(self):
        for raw in ["", "nonsense", 'a:2:{s:6:"editor";b:1;}', 'a:1:{s:9:"editor";b:1;}',
                    'a:1:{i:0;s:6:"editor";}']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_capabilities(raw)

    def test_role_mapping(self):
        self.assertEqual(role_for({"administrator"}), User.Role.EDITOR)
        self.assertEqual(role_for({"editor"}), User.Role.EDITOR)
        self.assertEqual(role_for({"subscriber"}), User.Role.READER)
        self.assertEqual(role_for({"author", "contributor"}), User.Role.READER)
        self.assertEqual(role_for(set()), User.Role.READER)


@FAST_HASHER
class UserImportTests(TestCase):
    def run_import(self, accounts=None, **kwargs):
        kwargs.setdefault("password", "changeme")
        return run_user_import(FakeSource(accounts or wp_accounts()), **kwargs)

    def test_creates_accounts_with_roles_and_password(self):
        report = self.run_import()
        self.assertEqual(report.created, 3)
        admin = User.objects.get(wp_user_id=1)
        sarah = User.objects.get(username="sarah_k")
        self.assertEqual((admin.role, sarah.role), ("editor", "reader"))
        self.assertEqual((sarah.email, sarah.display_name), ("sarah@example.com", "Sarah K."))
        self.assertTrue(sarah.check_password("changeme"))
        self.assertFalse(admin.is_staff or admin.is_superuser)

    def test_each_account_gets_its_own_salt(self):
        self.run_import()
        hashes = set(User.objects.values_list("password", flat=True))
        self.assertEqual(len(hashes), 3)

    def test_empty_import_password_means_unusable_password(self):
        self.run_import(password="")
        self.assertFalse(User.objects.get(wp_user_id=2).has_usable_password())

    def test_rerun_changes_nothing(self):
        self.run_import()
        report = self.run_import()
        self.assertEqual((report.created, report.updated, report.unchanged), (0, 0, 3))
        self.assertEqual(User.objects.count(), 3)

    def test_rerun_updates_profile_fields(self):
        self.run_import()
        accounts = wp_accounts()
        accounts[1] = replace(accounts[1], email="sarah@new.example", display_name="Sarah King")
        report = self.run_import(accounts)
        self.assertEqual(report.updated, 1)
        sarah = User.objects.get(wp_user_id=2)
        self.assertEqual((sarah.email, sarah.display_name), ("sarah@new.example", "Sarah King"))

    def test_rerun_keeps_role_and_password_set_in_auth_service(self):
        self.run_import()
        sarah = User.objects.get(wp_user_id=2)
        sarah.role = User.Role.EDITOR
        sarah.set_password("new-secret-123")
        sarah.save()

        self.run_import(password="changeme")

        sarah.refresh_from_db()
        self.assertEqual(sarah.role, "editor")
        self.assertTrue(sarah.check_password("new-secret-123"))

    def test_missing_users_are_kept_unless_pruned(self):
        self.run_import()
        report = self.run_import(wp_accounts()[:2])
        self.assertEqual(report.missing, [3])
        self.assertTrue(User.objects.get(wp_user_id=3).is_active)

        report = self.run_import(wp_accounts()[:2], prune=True)
        self.assertEqual(report.deactivated, 1)
        self.assertFalse(User.objects.get(wp_user_id=3).is_active)
        self.assertEqual(User.objects.count(), 3)  # deactivated, not deleted

    def test_prune_ignores_accounts_created_in_auth_service(self):
        User.objects.create_user("native", password="x-long-password")
        self.run_import(prune=True)
        self.assertTrue(User.objects.get(username="native").is_active)

    def test_user_without_role_is_reader_with_warning(self):
        accounts = wp_accounts()
        accounts[2] = replace(accounts[2], capabilities=None)
        report = self.run_import(accounts)
        self.assertEqual(User.objects.get(wp_user_id=3).role, "reader")
        self.assertTrue(any("has no role" in w for w in report.warnings))

    def test_invalid_data_writes_nothing_and_lists_every_error(self):
        self.run_import()
        accounts = wp_accounts()
        accounts[0] = replace(accounts[0], capabilities="garbage")
        accounts[1] = replace(accounts[1], email="not-an-email", display_name="Changed")
        accounts.append(WPAccount(4, "bad login!", "x@example.com", "X", SUBSCRIBER_CAPS))

        with self.assertRaises(ValidationFailed) as ctx:
            self.run_import(accounts)

        errors = "\n".join(ctx.exception.errors)
        self.assertEqual(len(ctx.exception.errors), 3, errors)
        self.assertIn("user wp_id=1 (admin): not a serialized PHP array", errors)
        self.assertIn("user wp_id=2 (sarah_k): email:", errors)
        self.assertIn("user wp_id=4 (bad login!): username:", errors)
        self.assertEqual(User.objects.count(), 3)
        self.assertEqual(User.objects.get(wp_user_id=2).display_name, "Sarah K.")

    def test_dry_run_writes_nothing(self):
        report = self.run_import(dry_run=True)
        self.assertEqual(report.created, 3)
        self.assertEqual(User.objects.count(), 0)


@FAST_HASHER
@override_settings(AUTH_IMPORT_PASSWORD="changeme")
@mock.patch("accounts.management.commands.import_wp_users.source_from_settings")
class CommandTests(TestCase):
    def test_prints_summary(self, source_factory):
        source_factory.return_value = FakeSource(wp_accounts())
        out = StringIO()
        call_command("import_wp_users", stdout=out)
        text = out.getvalue()
        self.assertIn("users: created 3, updated 0, unchanged 0", text)
        self.assertIn("new account admin        role=editor", text)
        self.assertIn("Import committed.", text)

    def test_invalid_data_exits_with_error(self, source_factory):
        accounts = wp_accounts()
        accounts[0] = replace(accounts[0], capabilities="garbage")
        source_factory.return_value = FakeSource(accounts)
        with self.assertRaisesMessage(CommandError, "Nothing was written."):
            call_command("import_wp_users", stdout=StringIO(), stderr=StringIO())
        self.assertEqual(User.objects.count(), 0)
