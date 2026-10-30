import { useCallback, useEffect, useId, useRef, useState } from "react";

import {
  ApiError,
  DEFAULT_ORDERING,
  fetchBrands,
  PAGE_SIZE,
  type BrandPage,
  type BrandQuery,
  type Ordering,
} from "./api";
import { BrandCard } from "./BrandCard";
import { Pagination } from "./Pagination";
import { pushQuery, readQuery, replaceQuery, toSearch } from "./urlState";

const ORDERING_LABELS: Record<Ordering, string> = {
  "-average_rating": "Highest rated",
  average_rating: "Lowest rated",
  "-review_count": "Most reviewed",
  review_count: "Fewest reviewed",
};

type Status =
  | { kind: "loading" }
  | { kind: "ready"; data: BrandPage }
  | { kind: "error"; error: unknown };

/**
 * Filterable, sortable, paginated brand cards from GET /api/brands/.
 *
 * State lives in the URL: every change pushes a history entry, and Back/
 * Forward (popstate) re-read it. Each query change aborts the request still
 * in flight, so a slow old response can never replace a newer one.
 */
export function BrandList({ apiUrl }: { apiUrl: string }) {
  const [query, setQuery] = useState<BrandQuery>(() => readQuery(window.location.search));
  const [status, setStatus] = useState<Status>({ kind: "loading" });
  // Last good response: keeps the filter options and the old cards on screen
  // (dimmed) while the next page loads, so the layout doesn't jump.
  const [lastData, setLastData] = useState<BrandPage | null>(null);
  const [attempt, setAttempt] = useState(0); // bumped by "Try again"
  const headingRef = useRef<HTMLHeadingElement>(null);
  const focusResultsAfterLoad = useRef(false);
  const ids = { industry: useId(), ordering: useId(), heading: useId() };

  // Clean up a URL whose values were normalised (e.g. ?page=abc), then follow Back/Forward.
  useEffect(() => {
    replaceQuery(readQuery(window.location.search));
    const onPopState = () => setQuery(readQuery(window.location.search));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setStatus({ kind: "loading" });
    fetchBrands(apiUrl, query, controller.signal).then(
      (data) => {
        setStatus({ kind: "ready", data });
        setLastData(data);
      },
      (error: unknown) => {
        if (!controller.signal.aborted) setStatus({ kind: "error", error });
      },
    );
    return () => controller.abort();
  }, [apiUrl, query, attempt]);

  // After paging, move focus to the results heading so keyboard and screen
  // reader users continue from the new results, not from the old link.
  useEffect(() => {
    if (status.kind !== "loading" && focusResultsAfterLoad.current) {
      focusResultsAfterLoad.current = false;
      headingRef.current?.focus();
      headingRef.current?.scrollIntoView?.({ block: "start" });
    }
  }, [status]);

  const navigate = useCallback((next: BrandQuery, { focusResults = false } = {}) => {
    focusResultsAfterLoad.current = focusResults;
    pushQuery(next);
    setQuery(next);
  }, []);

  // Filter and sort changes start again at page 1.
  const setIndustry = (industry: string) => navigate({ ...query, industry, page: 1 });
  const setOrdering = (ordering: Ordering) => navigate({ ...query, ordering, page: 1 });
  const goToPage = (page: number) => navigate({ ...query, page }, { focusResults: true });
  const reset = () => navigate({ industry: "", ordering: DEFAULT_ORDERING, page: 1 }, { focusResults: true });

  const loading = status.kind === "loading";
  const shown = status.kind === "ready" ? status.data : loading ? lastData : null;
  const industries = lastData?.industries ?? [];

  return (
    <div className="brand-list">
      <form className="brand-list__controls" aria-label="Filter and sort brands" onSubmit={(e) => e.preventDefault()}>
        <div className="field">
          <label className="field__label" htmlFor={ids.industry}>
            Industry
          </label>
          <select
            id={ids.industry}
            className="field__control"
            value={query.industry}
            onChange={(e) => setIndustry(e.target.value)}
          >
            <option value="">All industries</option>
            {industries.map((industry) => (
              <option key={industry.slug} value={industry.slug}>
                {industry.name}
              </option>
            ))}
            {/* An industry from the URL that isn't (yet) in the list. */}
            {query.industry && !industries.some((i) => i.slug === query.industry) && (
              <option value={query.industry}>{query.industry}</option>
            )}
          </select>
        </div>
        <div className="field">
          <label className="field__label" htmlFor={ids.ordering}>
            Sort by
          </label>
          <select
            id={ids.ordering}
            className="field__control"
            value={query.ordering}
            onChange={(e) => setOrdering(e.target.value as Ordering)}
          >
            {Object.entries(ORDERING_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
      </form>

      {/* Announces loading and result counts to screen readers. */}
      <p className="visually-hidden" role="status">
        {loading ? "Loading brands…" : status.kind === "ready" ? summary(status.data) : ""}
      </p>

      <section className="brand-list__results" aria-labelledby={ids.heading} aria-busy={loading}>
        <h2 id={ids.heading} className="brand-list__heading" tabIndex={-1} ref={headingRef}>
          {shown ? summary(shown) : loading ? "Loading brands…" : "Brands"}
        </h2>

        {status.kind === "error" && <ErrorMessage error={status.error} onRetry={() => setAttempt((n) => n + 1)} onReset={reset} />}

        {shown && shown.results.length === 0 && status.kind === "ready" && (
          <div className="brand-list__empty">
            <p>No brands match this filter.</p>
            {query.industry && (
              <button type="button" className="button" onClick={() => setIndustry("")}>
                Show all industries
              </button>
            )}
          </div>
        )}

        {shown && shown.results.length > 0 && status.kind !== "error" && (
          <>
            <ul className="grid" role="list">
              {shown.results.map((brand) => (
                <li key={brand.slug}>
                  <BrandCard brand={brand} />
                </li>
              ))}
            </ul>
            <Pagination
              page={shown.page}
              totalPages={shown.total_pages}
              hrefFor={(page) => `${window.location.pathname}${toSearch({ ...query, page })}`}
              onNavigate={goToPage}
            />
          </>
        )}
      </section>
    </div>
  );
}

function summary(data: BrandPage): string {
  if (data.count === 0) return "No brands found";
  const first = (data.page - 1) * PAGE_SIZE + 1;
  const last = first + data.results.length - 1;
  const noun = data.count === 1 ? "brand" : "brands";
  return data.total_pages > 1
    ? `Showing ${first}–${last} of ${data.count} ${noun}`
    : `Showing ${data.count} ${noun}`;
}

function ErrorMessage({ error, onRetry, onReset }: { error: unknown; onRetry: () => void; onReset: () => void }) {
  const status = error instanceof ApiError ? error.status : null;
  const [message, action] =
    status === 400
      ? ["The filters in this address aren't valid.", { label: "Reset filters", run: onReset }]
      : status === 404
        ? ["That page of results doesn't exist.", { label: "Go to the first page", run: onReset }]
        : ["Brands couldn't be loaded. Check your connection and try again.", { label: "Try again", run: onRetry }];
  return (
    <div className="brand-list__error" role="alert">
      <p>{message}</p>
      <button type="button" className="button" onClick={action.run}>
        {action.label}
      </button>
    </div>
  );
}
