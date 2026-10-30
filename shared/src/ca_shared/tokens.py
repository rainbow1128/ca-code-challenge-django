"""Short-lived JWT access tokens signed with Ed25519 (JWT algorithm "EdDSA").

The auth service holds the private key and issues tokens; every other service
holds only the public key and verifies them locally, without calling the auth
service. A stolen public key can't mint tokens.

Claims (all required on verification):
    sub   user ID (string)          role  "reader" | "editor"
    iss   who issued the token      aud   which service it is for
    iat   issued at (unix time)     exp   expiry (unix time)
    jti   unique token ID (for logs; and a deny-list, if one is ever needed)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .roles import Role

ALGORITHM = "EdDSA"  # the only algorithm accepted; never taken from the token header
REQUIRED_CLAIMS = ("sub", "role", "iss", "aud", "iat", "exp", "jti")
MAX_LIFETIME = timedelta(hours=1)


class TokenError(Exception):
    """The token can't be used. The message is safe to show to the client."""


class ExpiredToken(TokenError):
    pass


class InvalidToken(TokenError):
    pass


@dataclass(frozen=True)
class TokenClaims:
    user_id: str
    role: Role
    issuer: str
    audience: str
    issued_at: datetime
    expires_at: datetime
    token_id: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "sub": self.user_id,
            "role": self.role.value,
            "iss": self.issuer,
            "aud": self.audience,
            "iat": int(self.issued_at.timestamp()),
            "exp": int(self.expires_at.timestamp()),
            "jti": self.token_id,
        }


# -- Keys ---------------------------------------------------------------------


def generate_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def private_key_to_pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def public_key_to_pem(key: Ed25519PrivateKey | Ed25519PublicKey) -> bytes:
    public = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    return public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def load_private_key(pem: bytes | str) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(_bytes(pem), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("expected an Ed25519 private key")
    return key


def load_public_key(pem: bytes | str) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(_bytes(pem))
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("expected an Ed25519 public key")
    return key


def _bytes(value: bytes | str) -> bytes:
    return value.encode() if isinstance(value, str) else value


# -- Issue --------------------------------------------------------------------


def issue_token(
    private_key: Ed25519PrivateKey,
    *,
    user_id: str | int,
    role: Role | str,
    issuer: str,
    audience: str,
    lifetime: timedelta,
    now: datetime | None = None,
) -> tuple[str, TokenClaims]:
    """Sign a new access token. Returns (token, claims)."""
    if not timedelta(0) < lifetime <= MAX_LIFETIME:
        raise ValueError(f"lifetime must be between 0 and {MAX_LIFETIME}")
    issued_at = (now or datetime.now(UTC)).replace(microsecond=0)
    claims = TokenClaims(
        user_id=str(user_id),
        role=Role(role),
        issuer=issuer,
        audience=audience,
        issued_at=issued_at,
        expires_at=issued_at + lifetime,
        token_id=uuid.uuid4().hex,
    )
    token = jwt.encode(claims.to_payload(), private_key, algorithm=ALGORITHM, headers={"typ": "JWT"})
    return token, claims


# -- Verify -------------------------------------------------------------------


def verify_token(
    token: str,
    public_key: Ed25519PublicKey,
    *,
    issuer: str,
    audience: str,
    leeway: timedelta = timedelta(seconds=10),
) -> TokenClaims:
    """Check signature, algorithm, issuer, audience, times and claims.

    Raises ExpiredToken or InvalidToken; never returns unverified data.
    ``leeway`` tolerates small clock differences between services.
    """
    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=[ALGORITHM],
            issuer=issuer,
            audience=audience,
            leeway=leeway,
            options={"require": list(REQUIRED_CLAIMS)},
        )
    except jwt.ExpiredSignatureError as exc:
        raise ExpiredToken("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidToken("Token is invalid.") from exc

    try:
        role = Role(payload["role"])
    except ValueError as exc:
        raise InvalidToken("Token is invalid.") from exc
    for name in ("sub", "jti"):
        if not isinstance(payload[name], str) or not payload[name]:
            raise InvalidToken("Token is invalid.")

    return TokenClaims(
        user_id=payload["sub"],
        role=role,
        issuer=payload["iss"],
        audience=payload["aud"] if isinstance(payload["aud"], str) else audience,
        issued_at=datetime.fromtimestamp(payload["iat"], UTC),
        expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        token_id=payload["jti"],
    )
