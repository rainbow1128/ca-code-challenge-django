"""Roles. The auth service decides who has which role; services only check them."""

from enum import StrEnum


class Role(StrEnum):
    READER = "reader"
    EDITOR = "editor"


# What each role may do. An editor can do everything a reader can.
_GRANTS: dict[Role, frozenset[Role]] = {
    Role.READER: frozenset({Role.READER}),
    Role.EDITOR: frozenset({Role.READER, Role.EDITOR}),
}


def has_role(actual: Role | str, required: Role | str) -> bool:
    """True if a user with role ``actual`` may do what ``required`` allows.

    Unknown role names are never granted anything.
    """
    try:
        return Role(required) in _GRANTS[Role(actual)]
    except ValueError:
        return False
