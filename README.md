# Brand Reviews — Django

Django replacement for the WordPress brand-reviews site
([ca-code-challenge-wordpress](../ca-code-challenge-wordpress)).

Work in progress. Done so far: Docker setup, models, WordPress import for both
services, tests. Not yet: pages, brand API, React component, SCSS, login/tokens,
shared library.

## Services

| Service | Port | Database | Owns |
|---|---|---|---|
| `main` | 8000 | `main-db` (Postgres 17) | industries, brands, reviewer profiles, reviews |
| `auth` | 8001 | `auth-db` (Postgres 17) | user accounts, passwords, roles (`reader`, `editor`) |
| `main-wp-import` | — | — | one-off job: WordPress → main |
| `auth-wp-import` | — | — | one-off job: WordPress users → auth |

```bash
cp .env.example .env
docker compose up -d          # main + auth; WordPress does not need to be running
```

## Importing from WordPress

The WordPress stack must be running (`docker compose up -d` in the WordPress
repo). The import jobs join its Docker network (`WP_NETWORK_NAME`) and read
its MariaDB directly; MariaDB has no host port.

```bash
docker compose run --rm main-wp-import --dry-run   # show what would change, write nothing
docker compose run --rm main-wp-import             # import
docker compose run --rm auth-wp-import             # import users and roles
```

The two imports are independent and can run in any order: both use the
WordPress user ID to link a reviewer profile (main) to its account (auth).

**Re-running is safe.** Every imported row stores its WordPress ID (`wp_id`).
A re-run updates the matching rows, writes only rows whose values changed, and
reports `created / updated / unchanged / missing` for each entity.

| | main (`import_wp`) | auth (`import_wp_users`) |
|---|---|---|
| Reads | published brands and reviews, industry terms, users who wrote reviews | all users and their WP role |
| Order | Industry → Brand → Reviewer → Review | User |
| Set only on create | `short_description` (Django owns it afterwards) | `role`, `password` |
| HTML | sanitized before saving (allowlist) | — |
| Not imported | Yoast SEO, ACF field-key rows, `reviewer_name` (copy of the author's name) | |
| `--prune` | deletes imported rows missing from WP (children first) | deactivates accounts missing from WP |
| Rows created in Django | never touched | never touched |

- **Transactions:** each run is one Postgres transaction. Invalid source data
  (all problems are listed), a database conflict or a blocked prune rolls back
  everything. A Postgres advisory lock makes a second run wait for the first.
- **Source reads:** one read-only, consistent-snapshot MariaDB transaction,
  so the run sees WordPress at a single moment.
- **Ratings:** average rating and review count are calculated from the reviews
  (`Brand.objects.with_rating_stats()`), not stored. WordPress's hand-entered
  average is kept as `wp_average_rating` for comparison only; the import prints
  both (4 of 5 brands differ).
- **Roles:** WP `administrator`/`editor` → `editor`, everything else → `reader`.
- **Passwords:** WordPress hashes are not copied. New accounts get
  `AUTH_IMPORT_PASSWORD` (hashed per account), or an unusable password if empty.

## Tests

```bash
docker compose run --rm main python manage.py test catalog
docker compose run --rm auth python manage.py test accounts

# Against the real WordPress MariaDB (WP stack running):
docker compose run --rm -e WP_INTEGRATION_TESTS=1 --entrypoint python \
  main-wp-import manage.py test catalog.tests.test_source_integration
docker compose run --rm -e WP_INTEGRATION_TESTS=1 --entrypoint python \
  auth-wp-import manage.py test accounts.tests.test_source_integration
```
