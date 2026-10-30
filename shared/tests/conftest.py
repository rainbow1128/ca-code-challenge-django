"""Standalone tests: no Django project needed. Django is configured minimally
here only for the DRF integration tests (ca_shared.drf)."""

from datetime import timedelta

import django
import pytest
from django.conf import settings

from ca_shared import tokens

ISSUER = "test-auth"
AUDIENCE = "test-main"


def pytest_configure():
    if not settings.configured:
        settings.configure(
            SECRET_KEY="test",
            INSTALLED_APPS=["rest_framework"],
            REST_FRAMEWORK={"UNAUTHENTICATED_USER": None},
            ROOT_URLCONF=__name__,
            CA_SHARED_AUTH={"ISSUER": ISSUER, "AUDIENCE": AUDIENCE, "PUBLIC_KEY": ""},
        )
        django.setup()


urlpatterns = []


@pytest.fixture(scope="session")
def private_key():
    return tokens.generate_private_key()


@pytest.fixture(scope="session")
def public_key(private_key):
    return private_key.public_key()


@pytest.fixture
def issue(private_key):
    """issue(role="editor", **overrides) -> token string."""

    def _issue(role="editor", *, key=None, lifetime=timedelta(minutes=15), **kwargs):
        token, _ = tokens.issue_token(
            key or private_key,
            user_id=kwargs.pop("user_id", 42),
            role=role,
            issuer=kwargs.pop("issuer", ISSUER),
            audience=kwargs.pop("audience", AUDIENCE),
            lifetime=lifetime,
            **kwargs,
        )
        return token

    return _issue
