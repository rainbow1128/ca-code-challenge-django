# Brand Reviews — WordPress to Django

A WordPress brand-reviews site migrated to Django: the WordPress content imported
into a relational model, server-rendered pages on the same URLs, a brand listing
API with a React `<BrandList />`, SCSS source for the theme, a separate auth
service issuing JWTs, and a shared Python package used by both services. The
brief is [wordpress/CHALLENGE.md](wordpress/CHALLENGE.md).

## Quick start

Needs Docker with Compose v2. Nothing else (Node and Python run in containers).

```bash
./setup.sh
```

That one command (safe to run again):

1. creates `.env` from `.env.example` if it doesn't exist (development values);
2. `docker compose up -d --build`: starts the WordPress database (`wp-db`, loaded
   from `wordpress/db/dump.sql` on the first run), both Django services and their
   Postgres databases, and the one-off jobs that create the token signing keys and
   build the CSS/JS;
3. imports the WordPress content into main, then the WordPress users into auth.

Then open <http://localhost:8000/> (brand list: <http://localhost:8000/brand/>).
Log in with any WordPress user and the password `AUTH_IMPORT_PASSWORD` from `.env`
(`changeme`): `admin` is an editor, the eight reviewers are readers. See
[Authentication](#authentication) for getting a token.

The same steps by hand:

```bash
cp .env.example .env
docker compose up -d --build
docker compose run --rm main-wp-import
docker compose run --rm auth-wp-import
```

Optional: the original WordPress site for comparison, at <http://localhost:8080/>
(its URL is fixed in the dump): `docker compose --profile wordpress up -d wordpress`.

Start over from empty databases: `docker compose --profile wordpress down -v`, then `./setup.sh`.

## Repository layout

```
setup.sh            one-command setup (above)
docker-compose.yml  every service, including the WordPress database
.env.example        development settings (copied to .env)
main/               Django main service: catalog app (models, WP import, API, pages), templates
auth_service/       Django auth service: accounts app (users, roles, login, WP user import)
shared/             ca-shared Python package (tokens, roles, DRF classes) and its tests
frontend/           SCSS source, React BrandList (TypeScript, Vite, Vitest), assets image
wordpress/          the original WordPress source, unchanged (commit f9a0e4d of the
                    challenge repository): dump, theme, plugins, CHALLENGE.md
```

`wordpress/` is a byte-for-byte copy of the challenge repository; nothing in it is
edited. Compose uses its `db/dump.sql` (and, for the optional site, its theme and
plugins, mounted read-only).

## Services

| Service | Port | Database | Role |
|---|---|---|---|
| `main` | 8000 | `main-db` (Postgres 17) | pages and API; owns industries, brands, reviewer profiles, reviews |
| `auth` | 8001 | `auth-db` (Postgres 17) | login; owns user accounts, passwords, roles (`reader`, `editor`) |
| `wp-db` | — | MariaDB 11 | the original WordPress database, read only by the import jobs |
| `jwt-keys` | — | — | one-off on `up`: creates the token signing key pair (first run only) |
| `assets` | — | — | one-off on `up`: builds `frontend/` → `main/static/css/main.css`, `main/static/js/brand-list.js` |
| `main-wp-import` | — | — | one-off: WordPress content → main (run by `setup.sh`) |
| `auth-wp-import` | — | — | one-off: WordPress users → auth (run by `setup.sh`) |
| `wordpress` | 8080 | `wp-db` | optional, profile `wordpress`: the original site |
| `shared-tests` | — | — | runs the shared package's tests |

## Importing from WordPress

`setup.sh` runs both imports. They read the `wp-db` service directly (read-only),
in the same Compose project; MariaDB has no host port.

```bash
docker compose run --rm main-wp-import --dry-run   # show what would change, write nothing
docker compose run --rm main-wp-import             # import (again)
docker compose run --rm auth-wp-import             # import users and roles (again)
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

## Pages

Server-rendered, on the same URLs and slugs as the WordPress permalinks. The
opt-in live test (`test_every_wordpress_permalink_renders_after_import`, see
[Tests](#tests)) imports from `wp-db` and requests every published brand and
review URL.

| URL | Shows | Queries |
|---|---|---|
| `/` | hero, 6 top-rated brands (calculated ratings), 6 newest reviews | 2 |
| `/brand/` | the React `<BrandList />` (below); plain brand links when JavaScript is off | 1 |
| `/brand/<slug>/` | industry, rating and count, HQ, founded, website, description, all reviews newest first | 2 |
| `/review/<slug>/` | rating, reviewer, location, date, full text, link back to the brand, brand summary | 2 |

Unknown slugs return `404` with the site's own not-found page (`templates/404.html`;
Django shows its debug page instead while `DJANGO_DEBUG=1`). A missing trailing
slash redirects, as on WordPress. One `<h1>` per page, skip link, landmark
elements, star ratings with a single screen-reader label ("Rated 3.9 out of 5").
Stars are rounded to the nearest whole star; the number is shown next to them.

## Brand listing API

`GET /api/brands/` (public, JSON). Example: <http://localhost:8000/api/brands/?industry=insurance,finance&ordering=-review_count>

| Parameter | Values | Default |
|---|---|---|
| `industry` | one or more industry slugs, comma-separated or repeated; brands in any of them | all |
| `ordering` | `-average_rating`, `average_rating`, `-review_count`, `review_count` | `-average_rating` |
| `page` | page number, 12 brands per page (fixed) | `1` |

Unknown industry or ordering values return `400` with a message per parameter;
a page past the end returns `404`.

```json
{
  "count": 5, "page": 1, "total_pages": 1, "next": null, "previous": null,
  "ordering": "-average_rating",
  "industries": [{"slug": "finance", "name": "Finance"}, "..."],
  "results": [{
    "slug": "acme-insurance", "name": "Acme Insurance Co.",
    "industry": {"slug": "insurance", "name": "Insurance"},
    "headquarters": "Hartford, CT", "short_description": "Acme Insurance is…",
    "average_rating": 3.92, "review_count": 12,
    "top_review": {"slug": "…", "title": "…", "rating": 5, "snippet": "first 30 words…",
                   "reviewer_name": "Sarah K.", "location": "Denver, CO",
                   "published_at": "2026-05-19T20:29:26Z"}
  }]
}
```

- **Ratings** are calculated from the reviews on every request; `average_rating`
  is a number with 2 decimals, `null` (and `top_review` `null`) for a brand
  without reviews. Unrated brands sort last when ordering by rating.
- **Top review** = highest rating; on a tie the newest; then the highest id.
- **Stable order:** ties are broken by more reviews (or higher rating), then
  name, then id, so pages never overlap or skip a brand.
- **`industries`** lists the filter options, so a client needs no second request.
- **4 queries per request**, however many brands: industries, count, one page
  of brands with their ratings, and the top reviews for that page
  (Postgres `DISTINCT ON`).

## React brand list

[frontend/src/brand-list/](frontend/src/brand-list/), React 19.2 + TypeScript 5.9, no UI
framework, built with Vite 7 to `main/static/js/brand-list.js` and mounted on
`/brand/` (the WordPress brand archive URL) into
`<div id="brand-list" data-api-url="/api/brands/">`.

| File | |
|---|---|
| `BrandList.tsx` | state, URL sync, data loading, loading/empty/error states, filter and sort controls |
| `BrandCard.tsx` | card and stars (same markup and classes as the Django templates) |
| `Pagination.tsx` | page links with gaps for many pages |
| `api.ts` | API types, `fetchBrands`, query ↔ search params |
| `urlState.ts` | read/write the query in the page URL |

- **Controls:** one industry `<select>` (options come from the API's
  `industries`), a sort `<select>` (highest/lowest rated, most/fewest reviewed),
  pagination links. Changing the filter or sort goes back to page 1.
- **URL state:** the page URL holds the same parameters as the API
  (`/brand/?industry=finance&ordering=-review_count&page=2`, defaults left out).
  Every change adds a history entry; Back/Forward re-read it. Values the controls
  can't show (`?page=abc`, unknown ordering) are cleaned from the URL; an unknown
  industry gets the API's 400 and a "Reset filters" button.
- **Requests:** each change aborts the request still in flight
  (`AbortController`), so a slow old response can never replace a newer one.
- **States:** "Loading brands…" on first load; later loads keep the old cards,
  dimmed, with `aria-busy`. Empty: a message and "Show all industries". Errors:
  `role="alert"` with "Try again" (network/5xx), "Reset filters" (400) or
  "Go to the first page" (404).
- **Accessibility:** labelled controls, a live status message for loading and
  result counts, focus moves to the results heading after paging or reset,
  pagination is a `<nav>` with `aria-current`, real links (`?page=2`) that also
  work in a new tab, and the site's focus ring and tokens.

## Styles (SCSS)

Source in [frontend/scss/](frontend/scss/), compiled with Dart Sass to
`main/static/css/main.css`, which every page loads (the React list uses the same
classes). Built files are not committed; see [Frontend build](#frontend-build).

```
frontend/scss/
  main.scss                 entry; the only file that lists partials
  abstracts/                no CSS output
    _tokens.scss            every raw value: colors, spacing, type, radii, shadows, breakpoint
    _tools.scss             token lookups (color("primary"), space(4)…; unknown name = build
                            error), mixins (mq, motion, hover, focus-ring, panel), contrast math
    _checks.scss            WCAG contrast assertions for every color pair the site uses
  base/_base.scss           custom properties, reset, typography, focus ring, skip link
  layout/_layout.scss       page skeleton, container, site header and footer, card grid
  components/_card.scss     brand/review cards and the industry badge
  components/_stars.scss    star ratings
  components/_review-list.scss  full reviews on the brand page
  components/_controls.scss     form fields and buttons
  components/_brand-list.scss   React list: filter toolbar, loading/empty/error states, pagination
  pages/_home.scss          hero (also compact on /brand/) and home sections
  pages/_detail.scss        brand and review pages (header band, text panel, brand facts), 404
```

- **Tokens:** components use only token functions, never raw values. Colors
  become CSS custom properties (`--color-primary`, …), so they can be themed at
  runtime and reused by the React component.
- **Adding a component:** create `components/_name.scss` starting with
  `@use "../abstracts/tools" as *;`, style one block class (`.name`, `.name__part`),
  and add one `@use` line to `main.scss`.
- **Accessibility:** one `:focus-visible` ring for everything (yellow on the
  dark hero and footer via `--focus-color`), a skip link, motion only inside the
  `motion()` mixin (`prefers-reduced-motion: no-preference`), hover effects only
  on devices that hover, font size relative to the reader's setting.
- **Responsive:** mobile first with one breakpoint (`sm`, 640px, as in the
  WordPress theme); the card grid needs none (1 column on phones, up to 3 on desktop).
- **Contrast fixes vs. the WordPress theme:** stars `#f59e0b` → `#b45309`
  (2.1 → 5.0:1), empty stars `#d1d5db` → `#8a919c` (1.5 → 3.2:1), muted text
  `#6b7280` → `#5c6370` (4.5 → 5.6:1), hero text no longer at 92% opacity.

**`npm run check:css`** fails when the SCSS doesn't compile, when Sass prints any
warning, when a color pair drops below its WCAG contrast minimum, or when a
Django template or React component uses a class that no CSS rule styles.

## Frontend build

Node runs only inside Docker: the `assets` service is built from
[frontend/Dockerfile](frontend/Dockerfile) (Node 22 LTS + npm 11.6.2). It installs
the locked packages with `npm ci` when `package-lock.json` changes, then runs the
command.

```bash
docker compose run --rm assets                      # build CSS + JS (also runs on `docker compose up`)
docker compose run --rm assets npm run check        # CSS check + typecheck + frontend tests
docker compose run --rm assets npm test             # frontend tests only (Vitest + Testing Library)
docker compose run --rm assets npm run watch:css    # rebuild CSS on save (watch:js for the React bundle)
```

Without Docker: `cd frontend && npm ci && npm run build` (needs npm 11.6.2).

**Versions** are pinned exactly in `frontend/package.json`, on established
release lines that are supported together: React 19.2, TypeScript 5.9 (the
JavaScript compiler, not the 7.x native one), Vite 7 + `@vitejs/plugin-react` 5,
Vitest 4 + jsdom 27, Testing Library (React 16, DOM 10, jest-dom 6,
user-event 14), Dart Sass 1.101, on Node 22 LTS.

**npm is pinned too**, to 11.6.2: `"packageManager"` and `"engines"` in
`package.json`, enforced by `engine-strict=true` in `frontend/.npmrc` (any other
npm refuses to install), and installed in the `assets` image. The lockfile is
generated and installed by that same npm. (npm 10.9 also can't resolve this
dependency set: its resolver crashes on Vitest's optional `jsdom` peer.) To change
a dependency, edit `package.json`, then regenerate the lockfile with
`docker compose run --rm --entrypoint npm assets install`.

## Authentication

The **auth service** owns users, passwords, roles and the **private** signing key.
The **main service** gets only the **public** key and verifies tokens itself: it
never calls the auth service, so tokens already issued keep working while the
auth service is down (new logins don't).

```bash
# 1. Log in (imported WordPress users have AUTH_IMPORT_PASSWORD, "changeme" in .env.example;
#    admin is an editor, the reviewers are readers)
TOKEN=$(curl -s -X POST localhost:8001/api/token/ -H 'Content-Type: application/json' \
  -d '{"username": "admin", "password": "changeme"}' | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')

# 2. Call the protected endpoint
curl -X PATCH localhost:8000/api/brands/acme-insurance/ -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"short_description": "New text"}'
```

| Endpoint | | Responses |
|---|---|---|
| `POST :8001/api/token/` | `{"username", "password"}` | 200 `{"access_token", "token_type": "Bearer", "expires_in": 900, "role"}` · 400 bad body · 401 wrong credentials or inactive (one message) |
| `PATCH :8000/api/brands/<slug>/` | `{"short_description"}` (max 500, only field) | 200 updated brand card · 401 no/invalid/expired token · 403 not an editor · 400 bad body · 404 unknown brand (checked after auth) |

`GET /api/brands/` and the pages stay public and ignore the `Authorization` header.

**Tokens** are JWTs signed with Ed25519 (`EdDSA`), valid 15 minutes
(`ACCESS_TOKEN_LIFETIME_SECONDS`), with claims `sub` (user ID), `role`
(`reader`/`editor`), `iss`, `aud`, `iat`, `exp`, `jti`. Verification accepts only
`EdDSA` (no `none`, no HMAC with the public key), requires every claim, checks
issuer and audience, and allows 10 s of clock difference.

**Keys** are created by the `jwt-keys` job on the first `docker compose up`, into
Docker volumes: `jwt_private` is mounted only into the auth service, `jwt_public`
only into main (read-only). No key is in the repository (`*.pem` is ignored).
To rotate: `docker compose run --rm jwt-keys python manage.py generate_jwt_keys --force`,
then `docker compose restart auth main` (every issued token stops working).

**Roles and revocation.** The role is read from the auth database at login and
copied into the token. Changing a role or deactivating a user takes effect at
the next login, so within at most one token lifetime (15 min); there is no
per-request check and no deny-list (each token's `jti` is logged, so one could
be added).

## Shared library (`ca-shared`)

[shared/](shared/) is a small installable package, version `0.1.0`
(`shared/pyproject.toml`), used by both services:

| Module | Used by | |
|---|---|---|
| `ca_shared.tokens` | auth (issue), main (verify) | key generation/loading, `issue_token`, `verify_token`, `TokenClaims` |
| `ca_shared.roles` | both | `Role` (`reader`, `editor`), `has_role` (an editor can do what a reader can) |
| `ca_shared.drf` (extra `[drf]`) | main | `JWTAuthentication`, `IsReader`, `IsEditor`, `TokenUser` |

```bash
docker compose run --rm --build shared-tests      # its own tests, no Django project needed
```

**How a version reaches a service.** Each service's Dockerfile builds the
package from `shared/` into a wheel in `/wheels`, and the service's
`requirements.txt` installs exactly that file by direct reference:
`ca-shared @ file:///wheels/ca_shared-0.1.0-py3-none-any.whl` (main adds the
`[drf]` extra). pip never looks the name up on PyPI, so a public package called
`ca-shared` can't be installed instead (dependency confusion). The version is
part of the file name: if `shared/` and a service's requirement disagree, that
service's build fails.

To release a change: bump the version in `shared/pyproject.toml` and
`shared/src/ca_shared/__init__.py`, update the file name in
`main/requirements.txt` and `auth_service/requirements.txt`, then
`docker compose build main auth jwt-keys`. Here both services build from the
same `shared/`, so they move together. In production the wheels would be
published to a private package index (with that index as the only source for
`ca-shared`), so each service could stay on its version until it upgrades; a
breaking token change would then ship in two steps: verifiers first accept old
and new, then the issuer switches.

## Tests

```bash
docker compose run --rm main python manage.py test catalog      # main service
docker compose run --rm auth python manage.py test accounts     # auth service
docker compose run --rm --build shared-tests                    # shared package, no Django project
docker compose run --rm assets npm run check                    # CSS check, typecheck, React tests

# Opt-in tests against the real WordPress data in wp-db (it starts automatically):
docker compose run --rm -e WP_INTEGRATION_TESTS=1 --entrypoint python \
  main-wp-import manage.py test catalog.tests.test_source_integration
docker compose run --rm -e WP_INTEGRATION_TESTS=1 --entrypoint python \
  auth-wp-import manage.py test accounts.tests.test_source_integration
```

The Django tests use their own test databases; the live tests read `wp-db` but
write only to test databases.

## Decisions, trade-offs and what I'd do with more time

**Modeling.** A relational model instead of WordPress's posts + postmeta:
`Industry`, `Brand` (one required industry), `Reviewer` and `Review`. Every
imported row keeps its WordPress ID (`wp_id`, unique) so the import can re-run;
foreign keys use `PROTECT`, so nothing is deleted as a side effect.

- **Ratings are derived, not stored.** Average and count are calculated from the
  reviews on every query (per-brand subqueries). WordPress's hand-entered
  `average_rating` was wrong for 4 of 5 brands; it is kept as
  `wp_average_rating` only to compare. Trade-off: computed per request, which is
  cheap here and never stale; at much larger scale, cache or store it and update
  it when a review changes.
- **Reviewers are a separate model, not Django users.** The main service must not
  store passwords or roles, so `Reviewer` is a public profile (username, display
  name) linked to the auth account by the WordPress user ID. The reviewer's
  location is on each `Review`, because it differs between one person's reviews;
  the `reviewer_name` meta was a copy of the author's name and is not imported.
- **Postmeta.** First-class fields: `website_url`, `founded_year`, `headquarters`
  (brand); `rating`, `reviewer_location`, `brand` (review). Dropped: Yoast SEO
  (out of scope), ACF's `_field` key rows, `reviewer_name`. Nothing went into a
  JSON field: every field kept is queried or shown.
- **Content.** HTML is sanitized once, on import (allowlist), so it is safe to
  render. `short_description` doesn't exist in WordPress: it is generated from the
  body on the first import and then owned by Django (the editor endpoint), so a
  re-import never overwrites it.

**Migration.** Read the WordPress MariaDB directly, in one read-only consistent
snapshot, rather than the REST API (its users endpoint lists only users who have
published, roles aren't exposed, everything is paginated) or parsing the dump. Validate everything first (all errors listed), then upsert by `wp_id` in one
Postgres transaction, writing only changed rows; `--dry-run` and `--prune` exist.
At 100× the data I'd read in ID-ordered batches, write in bulk per batch and
commit per batch or per entity.

**Other trade-offs.** Tokens are verified locally with the public key: the main
service keeps working while auth is down, but a role change or deactivation only
takes effect at the next login (at most the 15-minute token lifetime). The API
rejects unknown filter values with 400 instead of ignoring them, and the page size
is fixed. The React bundle has no CSS of its own; it uses the site's SCSS classes.

**With more time:**

- Login rate limiting / lockout; refresh tokens and a deny-list by `jti` for
  immediate revocation; a JWKS endpoint with key IDs, so keys can rotate without
  restarting services.
- A production setup: gunicorn, `DEBUG` off, static files with hashed names
  (`ManifestStaticFilesStorage` or a CDN), migrations as a deploy step instead of
  at container start, secrets from a secret store, and a CI pipeline running every
  test suite plus automated browser tests (keyboard, focus, layout and Back/Forward
  were checked in a real browser with one-off scripts, which are not in the repo).
- A private package index for `ca-shared`, so services can upgrade independently.
- Redirects when a WordPress slug changes; pagination for reviews on brand pages;
  a server-rendered first page of the brand list (for no-JavaScript and SEO).
- Batched import and cached rating aggregates for much larger data.

**Where I accepted the AI's default over my own preference.**

> **TO COMPLETE (repository owner):** this paragraph is deliberately left for me
> to write. List the places where I kept a default the AI proposed instead of my
> own preference, and why.
