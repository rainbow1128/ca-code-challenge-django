"""Reads the real WordPress MariaDB (the wp-db service). Opt-in, because it needs wp-db running:

    docker compose run --rm -e WP_INTEGRATION_TESTS=1 --entrypoint python \
        auth-wp-import manage.py test accounts.tests.test_source_integration
"""

import os
import unittest

from django.conf import settings
from django.test import TestCase, override_settings

from accounts.models import User
from accounts.wp_import import run_user_import
from accounts.wp_source import MariaDBUserSource


@unittest.skipUnless(os.environ.get("WP_INTEGRATION_TESTS") == "1", "set WP_INTEGRATION_TESTS=1")
@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class MariaDBUserSourceTests(TestCase):
    def setUp(self):
        self.source = MariaDBUserSource(**settings.WP_SOURCE)

    def test_reads_all_users_with_capabilities(self):
        accounts = {a.login: a for a in self.source.read()}
        self.assertEqual(len(accounts), 9)
        self.assertEqual(accounts["admin"].capabilities, 'a:1:{s:13:"administrator";b:1;}')
        self.assertEqual(accounts["sarah_k"].display_name, "Sarah K.")

    def test_full_import_maps_roles_and_is_repeatable(self):
        run_user_import(self.source, password="changeme")
        second = run_user_import(self.source, password="changeme")
        self.assertEqual((second.created, second.updated, second.unchanged), (0, 0, 9))
        self.assertEqual(list(User.objects.filter(role="editor").values_list("username", flat=True)),
                         ["admin"])
        self.assertEqual(User.objects.filter(role="reader").count(), 8)
