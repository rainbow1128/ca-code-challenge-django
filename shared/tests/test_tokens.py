import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from ca_shared import tokens
from ca_shared.roles import Role

from .conftest import AUDIENCE, ISSUER


def verify(token, public_key, **kwargs):
    kwargs.setdefault("issuer", ISSUER)
    kwargs.setdefault("audience", AUDIENCE)
    return tokens.verify_token(token, public_key, **kwargs)


def payload_of(token):
    body = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def header_of(token):
    head = token.split(".")[0]
    return json.loads(base64.urlsafe_b64decode(head + "=" * (-len(head) % 4)))


# -- Issuing ------------------------------------------------------------------


def test_token_has_all_required_claims(issue):
    token = issue("reader")
    payload = payload_of(token)
    assert set(payload) == {"sub", "role", "iss", "aud", "iat", "exp", "jti"}
    assert payload["sub"] == "42"
    assert payload["role"] == "reader"
    assert (payload["iss"], payload["aud"]) == (ISSUER, AUDIENCE)
    assert payload["exp"] - payload["iat"] == 15 * 60
    assert header_of(token) == {"alg": "EdDSA", "typ": "JWT"}


def test_every_token_gets_a_unique_id(issue):
    assert payload_of(issue())["jti"] != payload_of(issue())["jti"]


def test_lifetime_must_be_short_and_positive(private_key):
    for lifetime in [timedelta(0), timedelta(hours=2)]:
        with pytest.raises(ValueError):
            tokens.issue_token(private_key, user_id=1, role="reader", issuer=ISSUER,
                               audience=AUDIENCE, lifetime=lifetime)


def test_unknown_role_cannot_be_issued(private_key):
    with pytest.raises(ValueError):
        tokens.issue_token(private_key, user_id=1, role="admin", issuer=ISSUER,
                           audience=AUDIENCE, lifetime=timedelta(minutes=5))


# -- Verifying ----------------------------------------------------------------


def test_round_trip(private_key, public_key):
    now = datetime.now(UTC).replace(microsecond=0)
    token, issued = tokens.issue_token(private_key, user_id=7, role=Role.EDITOR, issuer=ISSUER,
                                       audience=AUDIENCE, lifetime=timedelta(minutes=5), now=now)
    claims = verify(token, public_key)
    assert claims == issued
    assert (claims.user_id, claims.role, claims.issued_at) == ("7", Role.EDITOR, now)
    assert claims.expires_at == now + timedelta(minutes=5)


def test_expired_token(issue, public_key):
    token = issue(now=datetime.now(UTC) - timedelta(minutes=20), lifetime=timedelta(minutes=15))
    with pytest.raises(tokens.ExpiredToken):
        verify(token, public_key)


def test_leeway_tolerates_small_clock_differences(issue, public_key):
    token = issue(now=datetime.now(UTC) - timedelta(minutes=15, seconds=5), lifetime=timedelta(minutes=15))
    verify(token, public_key, leeway=timedelta(seconds=10))
    with pytest.raises(tokens.ExpiredToken):
        verify(token, public_key, leeway=timedelta(0))


def test_token_issued_in_the_future_is_rejected(issue, public_key):
    token = issue(now=datetime.now(UTC) + timedelta(minutes=5))
    with pytest.raises(tokens.InvalidToken):
        verify(token, public_key)


def test_signed_with_another_key(issue, public_key):
    other = tokens.generate_private_key()
    with pytest.raises(tokens.InvalidToken):
        verify(issue(key=other), public_key)


def test_tampered_payload(issue, public_key):
    head, body, signature = issue("reader").split(".")
    payload = payload_of(f"{head}.{body}.{signature}")
    payload["role"] = "editor"
    forged_body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    with pytest.raises(tokens.InvalidToken):
        verify(f"{head}.{forged_body}.{signature}", public_key)


def test_wrong_issuer_or_audience(issue, public_key):
    with pytest.raises(tokens.InvalidToken):
        verify(issue(issuer="someone-else"), public_key)
    with pytest.raises(tokens.InvalidToken):
        verify(issue(audience="another-service"), public_key)


def test_algorithm_none_is_rejected(public_key):
    payload = {"sub": "1", "role": "editor", "iss": ISSUER, "aud": AUDIENCE,
               "iat": int(datetime.now(UTC).timestamp()), "exp": int(datetime.now(UTC).timestamp()) + 60,
               "jti": "x"}
    token = jwt.encode(payload, key=None, algorithm="none")
    with pytest.raises(tokens.InvalidToken):
        verify(token, public_key)


def test_hmac_signed_with_the_public_key_is_rejected(public_key):
    """Algorithm confusion: an attacker signs HS256 using the (public) key as the secret."""
    payload = {"sub": "1", "role": "editor", "iss": ISSUER, "aud": AUDIENCE,
               "iat": int(datetime.now(UTC).timestamp()), "exp": int(datetime.now(UTC).timestamp()) + 60,
               "jti": "x"}
    secret = tokens.public_key_to_pem(public_key)
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=")
    import hashlib
    import hmac
    sig = base64.urlsafe_b64encode(hmac.new(secret, header + b"." + body, hashlib.sha256).digest()).rstrip(b"=")
    with pytest.raises(tokens.InvalidToken):
        verify(b".".join([header, body, sig]).decode(), public_key)


@pytest.mark.parametrize("missing", ["sub", "role", "iss", "aud", "iat", "exp", "jti"])
def test_every_claim_is_required(private_key, public_key, missing):
    now = int(datetime.now(UTC).timestamp())
    payload = {"sub": "1", "role": "editor", "iss": ISSUER, "aud": AUDIENCE,
               "iat": now, "exp": now + 60, "jti": "abc"}
    del payload[missing]
    token = jwt.encode(payload, private_key, algorithm="EdDSA")
    with pytest.raises(tokens.TokenError):
        verify(token, public_key)


def test_unknown_role_in_a_validly_signed_token(private_key, public_key):
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode({"sub": "1", "role": "admin", "iss": ISSUER, "aud": AUDIENCE,
                        "iat": now, "exp": now + 60, "jti": "abc"}, private_key, algorithm="EdDSA")
    with pytest.raises(tokens.InvalidToken):
        verify(token, public_key)


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "Bearer x.y.z"])
def test_garbage(public_key, garbage):
    with pytest.raises(tokens.InvalidToken):
        verify(garbage, public_key)


# -- Keys -----------------------------------------------------------------------


def test_pem_round_trip(private_key):
    private_pem = tokens.private_key_to_pem(private_key)
    public_pem = tokens.public_key_to_pem(private_key)
    assert b"PRIVATE KEY" in private_pem and b"PRIVATE" not in public_pem
    loaded = tokens.load_private_key(private_pem)
    assert tokens.public_key_to_pem(loaded) == public_pem
    assert tokens.public_key_to_pem(tokens.load_public_key(public_pem.decode())) == public_pem


def test_other_key_types_are_refused():
    from cryptography.hazmat.primitives.asymmetric import ec

    ec_key = ec.generate_private_key(ec.SECP256R1())
    pem = tokens.serialization.Encoding.PEM
    with pytest.raises(ValueError):
        tokens.load_private_key(ec_key.private_bytes(pem, tokens.serialization.PrivateFormat.PKCS8,
                                                     tokens.serialization.NoEncryption()))
    with pytest.raises(ValueError):
        tokens.load_public_key(ec_key.public_key().public_bytes(
            pem, tokens.serialization.PublicFormat.SubjectPublicKeyInfo))
