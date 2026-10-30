"""Import WordPress users into the auth service.

Matched on wp_user_id, so it is safe to re-run.

On every run:      username, email, display_name are updated from WordPress.
Only on create:    role (from WP capabilities) and password. After the
                   migration the auth service owns them, so a re-import must
                   not undo a role change or password reset made here.
With --prune:      accounts no longer in WordPress are deactivated, not
                   deleted (keeps the account's history; it can't log in).
                   A re-import never reactivates an account: is_active is
                   owned by the auth service, like role and password.
"""

import re
from dataclasses import dataclass, field

from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from .models import User

ADVISORY_LOCK_KEY = 7_428_190_002

EDITOR_CAPABILITIES = {"administrator", "editor"}

# a:2:{s:13:"administrator";b:1;s:6:"editor";b:0;}
_PHP_ARRAY = re.compile(r"^a:(\d+):\{(.*)\}$", re.DOTALL)
_PHP_ENTRY = re.compile(r's:(\d+):"(.*?)";b:([01]);', re.DOTALL)

SYNCED_FIELDS = ("username", "email", "display_name")


class ValidationFailed(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__(f"{len(errors)} invalid user(s) in the WordPress data.")


class ImportFailed(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(errors) + ".")


@dataclass
class UserImportReport:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    missing: list[int] = field(default_factory=list)
    deactivated: int = 0
    roles: dict[str, str] = field(default_factory=dict)  # username -> role given on create
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False


def parse_capabilities(raw):
    """Roles granted in a PHP-serialized WP capabilities array.

    Only handles the shape WordPress writes for roles (string keys, boolean
    values). Anything else raises ValueError rather than being guessed at.
    """
    match = _PHP_ARRAY.match(raw.strip())
    if not match:
        raise ValueError(f"not a serialized PHP array: {raw!r}")
    count, body = int(match.group(1)), match.group(2)
    entries = _PHP_ENTRY.findall(body)
    if len(entries) != count or _PHP_ENTRY.sub("", body) != "":
        raise ValueError(f"unexpected capabilities format: {raw!r}")
    roles = set()
    for length, key, value in entries:
        if len(key.encode()) != int(length):
            raise ValueError(f"bad string length in capabilities: {raw!r}")
        if value == "1":
            roles.add(key)
    return roles


def role_for(wp_roles):
    return User.Role.EDITOR if wp_roles & EDITOR_CAPABILITIES else User.Role.READER


def build_rows(accounts):
    """{wp_id: values} for every WP user, or ValidationFailed with every problem."""
    errors, warnings, rows = [], [], {}
    seen_usernames = {}
    for account in accounts:
        label = f"user wp_id={account.wp_id} ({account.login})"
        if account.capabilities is None:
            warnings.append(f"{label}: has no role in WordPress; imported as reader")
            role = User.Role.READER
        else:
            try:
                role = role_for(parse_capabilities(account.capabilities))
            except ValueError as exc:
                errors.append(f"{label}: {exc}")
                role = None

        values = {
            "username": account.login.strip(),
            "email": (account.email or "").strip(),
            "display_name": (account.display_name or "").strip(),
            "role": role,
        }
        candidate = User(**{k: v for k, v in values.items() if v is not None})
        try:
            candidate.clean_fields(exclude=["password", "role"])
        except ValidationError as exc:
            for name, messages in exc.message_dict.items():
                errors.extend(f"{label}: {name}: {m}" for m in messages)

        if values["username"] in seen_usernames:
            errors.append(f"{label}: username also used by wp_id={seen_usernames[values['username']]}")
        seen_usernames[values["username"]] = account.wp_id
        rows[account.wp_id] = values

    if errors:
        raise ValidationFailed(errors)
    return rows, warnings


def run_user_import(source, *, password="", prune=False, dry_run=False):
    rows, warnings = build_rows(source.read())
    report = UserImportReport(warnings=warnings, dry_run=dry_run)

    try:
        with transaction.atomic():
            with connection.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", [ADVISORY_LOCK_KEY])
            _apply(rows, report, password, prune=prune)
            if dry_run:
                transaction.set_rollback(True)
    except IntegrityError as exc:
        raise ImportFailed([f"database rejected the import: {exc}"]) from exc
    return report


def _apply(rows, report, password, *, prune):
    existing = {u.wp_user_id: u for u in User.objects.filter(wp_user_id__in=list(rows))}
    to_create, to_update, changed_fields = [], [], set()

    for wp_id, values in rows.items():
        user = existing.get(wp_id)
        if user is None:
            # Hashed per account (own salt). make_password(None) = unusable password.
            to_create.append(User(wp_user_id=wp_id, password=make_password(password or None), **values))
            report.roles[values["username"]] = values["role"]
            continue
        changed = [f for f in SYNCED_FIELDS if getattr(user, f) != values[f]]
        if changed:
            for f in changed:
                setattr(user, f, values[f])
            changed_fields.update(changed)
            to_update.append(user)
        else:
            report.unchanged += 1

    User.objects.bulk_create(to_create)
    if to_update:
        User.objects.bulk_update(to_update, sorted(changed_fields))
    report.created, report.updated = len(to_create), len(to_update)

    gone = User.objects.filter(wp_user_id__isnull=False).exclude(wp_user_id__in=list(rows))
    report.missing = sorted(gone.values_list("wp_user_id", flat=True))
    if prune:
        report.deactivated = gone.filter(is_active=True).update(is_active=False)
