"""Read-only access to WordPress users and their roles.

The same connection rules as the main service's importer (read-only session,
one consistent snapshot). The few lines of connection code are repeated on
purpose: the two services read different tables, and WordPress goes away
after the migration, so this doesn't belong in the shared library.
"""

import re
from dataclasses import dataclass

import pymysql

_PREFIX = re.compile(r"^[A-Za-z0-9_]+$")


class SourceError(Exception):
    """The WordPress database could not be read."""


@dataclass(frozen=True)
class WPAccount:
    wp_id: int
    login: str
    email: str
    display_name: str
    capabilities: str | None  # raw PHP-serialized value of <prefix>capabilities, if any


class MariaDBUserSource:
    def __init__(self, *, host, port, database, user, password, table_prefix="wp_",
                 connect_timeout=10):
        if not _PREFIX.match(table_prefix):
            raise SourceError(f"Invalid WP table prefix: {table_prefix!r}")
        self.prefix = table_prefix
        self._connect_kwargs = dict(
            host=host, port=port, database=database, user=user, password=password,
            charset="utf8mb4", connect_timeout=connect_timeout,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def describe(self):
        kw = self._connect_kwargs
        return f"mysql://{kw['user']}@{kw['host']}:{kw['port']}/{kw['database']}"

    def read(self):
        try:
            conn = pymysql.connect(**self._connect_kwargs)
        except pymysql.MySQLError as exc:
            raise SourceError(f"Cannot connect to WordPress DB at {self.describe()}: {exc}") from exc
        try:
            with conn.cursor() as cur:
                cur.execute("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cur.execute("SET SESSION TRANSACTION READ ONLY")
                cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
                # The capabilities meta key includes the table prefix ("wp_capabilities").
                cur.execute(
                    f"""
                    SELECT u.ID, u.user_login, u.user_email, u.display_name,
                           (SELECT um.meta_value FROM `{self.prefix}usermeta` um
                            WHERE um.user_id = u.ID AND um.meta_key = %s
                            ORDER BY um.umeta_id LIMIT 1) AS capabilities
                    FROM `{self.prefix}users` u
                    ORDER BY u.ID
                    """,
                    [f"{self.prefix}capabilities"],
                )
                rows = cur.fetchall()
                cur.execute("COMMIT")
        except pymysql.MySQLError as exc:
            raise SourceError(f"Error reading WordPress DB: {exc}") from exc
        finally:
            conn.close()
        return [
            WPAccount(
                wp_id=r["ID"], login=r["user_login"], email=r["user_email"],
                display_name=r["display_name"], capabilities=r["capabilities"],
            )
            for r in rows
        ]
