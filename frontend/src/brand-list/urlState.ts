// The list's state lives in the page URL (?industry=…&ordering=…&page=…), so a
// view can be bookmarked or shared and the browser's Back/Forward buttons work.

import { DEFAULT_ORDERING, ORDERINGS, toSearchParams, type BrandQuery, type Ordering } from "./api";

/**
 * Read the query from a URL search string. Values the UI can't produce are
 * normalised: an unknown ordering falls back to the default, a page that isn't
 * a positive whole number to 1. The industry is kept as is; the API decides
 * whether it exists (400 -> the error state offers a reset).
 */
export function readQuery(search: string): BrandQuery {
  const params = new URLSearchParams(search);
  const ordering = params.get("ordering");
  const page = Number(params.get("page") ?? "1");
  return {
    industry: params.get("industry")?.trim() ?? "",
    ordering: ORDERINGS.includes(ordering as Ordering) ? (ordering as Ordering) : DEFAULT_ORDERING,
    page: Number.isInteger(page) && page >= 1 ? page : 1,
  };
}

/** "?industry=telecom&page=2", or "" when everything is at its default. */
export function toSearch(query: BrandQuery): string {
  const search = toSearchParams(query).toString();
  return search ? `?${search}` : "";
}

/** Add a history entry for the query (no entry if the URL wouldn't change). */
export function pushQuery(query: BrandQuery): void {
  const search = toSearch(query);
  if (search !== window.location.search) {
    window.history.pushState(null, "", `${window.location.pathname}${search}${window.location.hash}`);
  }
}

/** Rewrite the current entry, e.g. to clean up a URL that readQuery normalised. */
export function replaceQuery(query: BrandQuery): void {
  const search = toSearch(query);
  if (search !== window.location.search) {
    window.history.replaceState(null, "", `${window.location.pathname}${search}${window.location.hash}`);
  }
}
