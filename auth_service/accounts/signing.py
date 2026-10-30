"""The private signing key. Loaded once from JWT_PRIVATE_KEY_FILE."""

import functools
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.signals import setting_changed

from ca_shared.tokens import load_private_key


@functools.cache
def private_key():
    path = Path(settings.JWT_PRIVATE_KEY_FILE)
    if not path.is_file():
        raise ImproperlyConfigured(
            f"JWT private key not found at {path}. Run: docker compose run --rm jwt-keys"
        )
    return load_private_key(path.read_bytes())


def _clear(*, setting, **kwargs):
    if setting == "JWT_PRIVATE_KEY_FILE":
        private_key.cache_clear()


setting_changed.connect(_clear)
