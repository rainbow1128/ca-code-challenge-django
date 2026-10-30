"""Django REST Framework integration (install ``ca-shared[drf]``).

Settings (the service's settings.py):

    CA_SHARED_AUTH = {
        "PUBLIC_KEY_FILE": "/run/keys/public/jwt_public.pem",  # or "PUBLIC_KEY": "<pem>"
        "ISSUER": "brand-reviews-auth",
        "AUDIENCE": "brand-reviews-main",
        "LEEWAY_SECONDS": 10,
    }

Use on a view:

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsEditor]

No token or a bad token -> 401 with ``WWW-Authenticate: Bearer``; a valid token
without the role -> 403. Verification is local (public key only), so it keeps
working while the auth service is down.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.signals import setting_changed
from django.views.decorators.debug import sensitive_variables
from rest_framework import authentication, exceptions, permissions

from .roles import Role, has_role
from .tokens import TokenClaims, TokenError, load_public_key, verify_token

KEYWORD = "Bearer"


@dataclass(frozen=True)
class TokenUser:
    """request.user for a verified token. The main service has no user table."""

    claims: TokenClaims

    is_authenticated = True
    is_anonymous = False

    @property
    def id(self) -> str:
        return self.claims.user_id

    @property
    def role(self) -> Role:
        return self.claims.role

    def __str__(self) -> str:
        return f"user {self.claims.user_id} ({self.claims.role})"


# -- Configuration --------------------------------------------------------------

_lock = threading.Lock()
_cache: dict[str, object] = {}


def _config() -> dict:
    config = getattr(settings, "CA_SHARED_AUTH", None)
    if not config or not config.get("ISSUER") or not config.get("AUDIENCE"):
        raise ImproperlyConfigured("CA_SHARED_AUTH needs ISSUER, AUDIENCE and a public key")
    return config


def _public_key():
    """Public key from settings, loaded once and cached (cleared when settings change)."""
    with _lock:
        if "key" not in _cache:
            config = _config()
            if config.get("PUBLIC_KEY"):
                pem = config["PUBLIC_KEY"]
            elif config.get("PUBLIC_KEY_FILE"):
                path = Path(config["PUBLIC_KEY_FILE"])
                if not path.is_file():
                    raise ImproperlyConfigured(f"JWT public key file not found: {path}")
                pem = path.read_bytes()
            else:
                raise ImproperlyConfigured("CA_SHARED_AUTH needs PUBLIC_KEY or PUBLIC_KEY_FILE")
            _cache["key"] = load_public_key(pem)
        return _cache["key"]


def _clear_cache(*, setting, **kwargs):
    if setting == "CA_SHARED_AUTH":
        with _lock:
            _cache.clear()


setting_changed.connect(_clear_cache)


# -- Authentication -----------------------------------------------------------


class JWTAuthentication(authentication.BaseAuthentication):
    """``Authorization: Bearer <token>`` -> TokenUser, verified with the public key."""

    # The bearer token must not show up in error pages/reports (frame locals).
    @sensitive_variables("header", "parts")
    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("latin-1")
        if not header:
            return None  # no credentials; the permission class turns this into 401
        parts = header.split()
        if len(parts) != 2 or parts[0].lower() != KEYWORD.lower():
            raise exceptions.AuthenticationFailed("Use 'Authorization: Bearer <token>'.")

        config = _config()
        try:
            claims = verify_token(
                parts[1],
                _public_key(),
                issuer=config["ISSUER"],
                audience=config["AUDIENCE"],
                leeway=timedelta(seconds=config.get("LEEWAY_SECONDS", 10)),
            )
        except TokenError as exc:
            raise exceptions.AuthenticationFailed(str(exc)) from exc
        return TokenUser(claims), claims

    def authenticate_header(self, request):
        # Makes DRF answer 401 (not 403) for missing/invalid credentials.
        return f'{KEYWORD} realm="api"'


# -- Permissions --------------------------------------------------------------


class HasRole(permissions.BasePermission):
    """Allow requests whose token grants ``required_role`` (editors include readers)."""

    required_role: Role
    message = "Your role doesn't allow this action."

    def has_permission(self, request, view):
        # No token: False here makes DRF answer 401 (it saw no successful
        # authenticator); a valid token with a too-low role gets 403.
        user = getattr(request, "user", None)
        return isinstance(user, TokenUser) and has_role(user.role, self.required_role)


class IsReader(HasRole):
    required_role = Role.READER


class IsEditor(HasRole):
    required_role = Role.EDITOR
