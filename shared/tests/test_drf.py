from datetime import UTC, datetime, timedelta

import pytest
from django.test import override_settings
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from ca_shared import tokens
from ca_shared.drf import IsEditor, IsReader, JWTAuthentication, TokenUser

from .conftest import AUDIENCE, ISSUER


class EditorView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsEditor]

    def post(self, request):
        return Response({"user": request.user.id, "role": request.user.role})


class ReaderView(EditorView):
    permission_classes = [IsReader]


@pytest.fixture(autouse=True)
def auth_settings(public_key):
    pem = tokens.public_key_to_pem(public_key).decode()
    with override_settings(CA_SHARED_AUTH={"ISSUER": ISSUER, "AUDIENCE": AUDIENCE, "PUBLIC_KEY": pem}):
        yield


def call(view, authorization=None):
    factory = APIRequestFactory()
    headers = {"HTTP_AUTHORIZATION": authorization} if authorization else {}
    return view.as_view()(factory.post("/", {}, format="json", **headers))


def test_editor_token_is_allowed(issue):
    response = call(EditorView, f"Bearer {issue('editor')}")
    assert response.status_code == 200
    assert response.data == {"user": "42", "role": "editor"}


def test_reader_token_is_forbidden_for_editor_actions(issue):
    response = call(EditorView, f"Bearer {issue('reader')}")
    assert response.status_code == 403


def test_reader_and_editor_tokens_pass_reader_permission(issue):
    assert call(ReaderView, f"Bearer {issue('reader')}").status_code == 200
    assert call(ReaderView, f"Bearer {issue('editor')}").status_code == 200


def test_missing_token_is_unauthorized_with_challenge():
    response = call(EditorView)
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == 'Bearer realm="api"'


@pytest.mark.parametrize("header", ["Bearer", "Bearer a b", "Token abc", "Basic dXNlcjpwYXNz", "Bearer not-a-jwt"])
def test_malformed_credentials_are_unauthorized(header):
    response = call(EditorView, header)
    assert response.status_code == 401
    assert "WWW-Authenticate" in response


def test_expired_token_is_unauthorized(issue):
    token = issue(now=datetime.now(UTC) - timedelta(hours=1), lifetime=timedelta(minutes=15))
    response = call(EditorView, f"Bearer {token}")
    assert response.status_code == 401
    assert response.data["detail"] == "Token has expired."


def test_wrong_signature_is_unauthorized(issue):
    token = issue(key=tokens.generate_private_key())
    response = call(EditorView, f"Bearer {token}")
    assert response.status_code == 401
    assert response.data["detail"] == "Token is invalid."


def test_scheme_is_case_insensitive(issue):
    assert call(EditorView, f"bearer {issue()}").status_code == 200


def test_token_user():
    now = datetime.now(UTC)
    claims = tokens.TokenClaims("9", tokens.Role.READER, ISSUER, AUDIENCE, now, now, "jti")
    user = TokenUser(claims)
    assert (user.is_authenticated, user.is_anonymous, user.id, user.role) == (True, False, "9", "reader")


def test_public_key_can_come_from_a_file(tmp_path, issue, public_key):
    path = tmp_path / "public.pem"
    path.write_bytes(tokens.public_key_to_pem(public_key))
    with override_settings(CA_SHARED_AUTH={"ISSUER": ISSUER, "AUDIENCE": AUDIENCE, "PUBLIC_KEY_FILE": str(path)}):
        assert call(EditorView, f"Bearer {issue()}").status_code == 200


def test_missing_key_file_is_a_configuration_error(tmp_path, issue):
    from django.core.exceptions import ImproperlyConfigured

    config = {"ISSUER": ISSUER, "AUDIENCE": AUDIENCE, "PUBLIC_KEY_FILE": str(tmp_path / "nope.pem")}
    with override_settings(CA_SHARED_AUTH=config), pytest.raises(ImproperlyConfigured):
        call(EditorView, f"Bearer {issue()}")


def test_bearer_token_is_masked_in_error_reports(issue, tmp_path):
    """A server error during authentication must not put the token in the error report."""
    import sys

    from django.core.exceptions import ImproperlyConfigured
    from django.views.debug import ExceptionReporter

    token = issue()
    request = APIRequestFactory().post("/", {}, format="json", HTTP_AUTHORIZATION=f"Bearer {token}")
    config = {"ISSUER": ISSUER, "AUDIENCE": AUDIENCE, "PUBLIC_KEY_FILE": str(tmp_path / "missing.pem")}
    with override_settings(CA_SHARED_AUTH=config):
        try:
            JWTAuthentication().authenticate(request)
        except ImproperlyConfigured:
            frames = ExceptionReporter(request, *sys.exc_info()).get_traceback_data()["frames"]
        else:
            pytest.fail("expected the missing key file to raise")
    auth_frame = next(f for f in frames if f["function"] == "authenticate")
    shown = {name: value for name, value in auth_frame["vars"]}
    assert token not in str(shown)
    assert set(shown) >= {"header", "parts"}
