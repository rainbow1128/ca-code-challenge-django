# Brand Reviews — Django

Django replacement for the WordPress brand-reviews site
([ca-code-challenge-wordpress](../ca-code-challenge-wordpress)).

Work in progress. Done so far: Docker setup, models, WordPress import for both
services, brand listing API, server-rendered pages, SCSS, tests. Not yet: React
component, login/tokens, shared library.

## Services

| Service | Port | Database | Owns |
|---|---|---|---|
| `main` | 8000 | `main-db` (Postgres 17) | industries, brands, reviewer profiles, reviews |
| `auth` | 8001 | `auth-db` (Postgres 17) | user accounts, passwords, roles (`reader`, `editor`) |
| `assets` | — | — | compiles `frontend/scss` → `main/static/css/main.css`, then exits |
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

## Pages

Server-rendered, same URLs and slugs as the WordPress permalinks (every WP
brand and review URL is checked to render):

| URL | Shows | Queries |
|---|---|---|
| `/` | hero, 6 top-rated brands (calculated ratings), 6 newest reviews | 2 |
| `/brand/<slug>/` | industry, rating and count, HQ, founded, website, description, all reviews newest first | 2 |
| `/review/<slug>/` | rating, reviewer, location, date, full text, link back to the brand, brand summary | 2 |

Unknown slugs return `404` with the site's own not-found page (`templates/404.html`;
Django shows its debug page instead while `DJANGO_DEBUG=1`). A missing trailing
slash redirects, as on WordPress. One `<h1>` per page, skip link, landmark
elements, star ratings with a single screen-reader label ("Rated 3.9 out of 5").
Stars are rounded to the nearest whole star; the number is shown next to them.

## Styles (SCSS)

Source in [frontend/scss/](frontend/scss/), compiled with Dart Sass (pinned in
`frontend/package.json`) to `main/static/css/main.css`, which every page loads.
The compiled file is not committed; `docker compose up` builds it (the `assets`
service), and so does:

```bash
docker compose run --rm assets                       # compile once (compressed)
docker compose run --rm assets npm run watch:css     # recompile on save (readable output)
docker compose run --rm assets npm run check:css     # the CSS check (below)
```

Each `assets` run installs the locked npm packages first, so Node is only
needed inside Docker. Without Docker: `cd frontend && npm ci && npm run build:css`.

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
  pages/_home.scss          hero and home sections
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
Django template uses a class that no CSS rule styles.

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
