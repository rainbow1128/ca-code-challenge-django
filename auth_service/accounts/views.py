import json
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables

from ca_shared.tokens import issue_token

from .signing import private_key

log = logging.getLogger(__name__)


def _error(status, detail):
    return JsonResponse({"detail": detail}, status=status)


@csrf_exempt  # JSON API with credentials in the body; no cookies or sessions involved
@never_cache
# Keep the password and the issued token out of error pages and error reports
# (Django shows local variables of each stack frame there).
@sensitive_post_parameters()
@sensitive_variables("data", "password", "access_token")
def token(request):
    """POST /api/token/  {"username": "...", "password": "..."}

    200 {"access_token", "token_type": "Bearer", "expires_in", "role"}
    400 body isn't a JSON object with username and password strings
    401 wrong username or password, or the account is inactive (one message for all)
    405 any method but POST
    """
    if request.method != "POST":
        response = _error(405, "Use POST.")
        response["Allow"] = "POST"
        return response

    try:
        data = json.loads(request.body or b"null")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error(400, "Body must be JSON.")
    if not isinstance(data, dict):
        return _error(400, "Body must be a JSON object.")
    username, password = data.get("username"), data.get("password")
    if not isinstance(username, str) or not isinstance(password, str) or not username or not password:
        return _error(400, "Both username and password are required.")

    # ModelBackend: rejects inactive users, and hashes a dummy password for
    # unknown usernames so timing doesn't reveal which usernames exist.
    user = authenticate(request, username=username, password=password)
    if user is None:
        log.info("token refused for username %r", username)
        return _error(401, "Invalid username or password.")

    lifetime = timedelta(seconds=settings.ACCESS_TOKEN_LIFETIME_SECONDS)
    access_token, claims = issue_token(
        private_key(),
        user_id=user.pk,
        role=user.role,
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
        lifetime=lifetime,
    )
    log.info("token %s issued to user %s (%s), expires %s",
             claims.token_id, user.pk, claims.role, claims.expires_at.isoformat())
    return JsonResponse({
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": int(lifetime.total_seconds()),
        "role": claims.role.value,
    })
