# Brand Reviews — Django

Django replacement for the WordPress brand-reviews site
([ca-code-challenge-wordpress](../ca-code-challenge-wordpress)).

Work in progress. Done so far: Docker setup, models, WordPress import for both
services, brand listing API, server-rendered pages, SCSS, React brand list,
tests. Not yet: login/tokens, shared library.

## Services

| Service | Port | Database | Owns |
|---|---|---|---|
| `main` | 8000 | `main-db` (Postgres 17) | industries, brands, reviewer profiles, reviews |
| `auth` | 8001 | `auth-db` (Postgres 17) | user accounts, passwords, roles (`reader`, `editor`) |
| `assets` | — | — | builds `frontend/` → `main/static/css/main.css` and `main/static/js/brand-list.js`, then exits |
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
| `/brand/` | the React `<BrandList />` (below); plain brand links when JavaScript is off | 1 |
| `/brand/<slug>/` | industry, rating and count, HQ, founded, website, description, all reviews newest first | 2 |
| `/review/<slug>/` | rating, reviewer, location, date, full text, link back to the brand, brand summary | 2 |

Unknown slugs return `404` with the site's own not-found page (`templates/404.html`;
Django shows its debug page instead while `DJANGO_DEBUG=1`). A missing trailing
slash redirects, as on WordPress. One `<h1>` per page, skip link, landmark
elements, star ratings with a single screen-reader label ("Rated 3.9 out of 5").
Stars are rounded to the nearest whole star; the number is shown next to them.

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
docker compose run --rm assets npm run check

# Against the real WordPress MariaDB (WP stack running):
docker compose run --rm -e WP_INTEGRATION_TESTS=1 --entrypoint python \
  main-wp-import manage.py test catalog.tests.test_source_integration
docker compose run --rm -e WP_INTEGRATION_TESTS=1 --entrypoint python \
  auth-wp-import manage.py test accounts.tests.test_source_integration
```
