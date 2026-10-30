// Types and fetch for GET /api/brands/ (see the README's API section).

export const ORDERINGS = ["-average_rating", "average_rating", "-review_count", "review_count"] as const;
export type Ordering = (typeof ORDERINGS)[number];
export const DEFAULT_ORDERING: Ordering = "-average_rating";

export interface Industry {
  slug: string;
  name: string;
}

export interface TopReview {
  slug: string;
  title: string;
  rating: number;
  snippet: string;
  reviewer_name: string;
  location: string;
  published_at: string;
}

export interface BrandCard {
  slug: string;
  name: string;
  industry: Industry;
  headquarters: string;
  short_description: string;
  average_rating: number | null;
  review_count: number;
  top_review: TopReview | null;
}

export interface BrandPage {
  count: number;
  page: number;
  total_pages: number;
  next: string | null;
  previous: string | null;
  ordering: Ordering;
  industries: Industry[];
  results: BrandCard[];
}

/** What the list shows; also exactly what is in the page URL. */
export interface BrandQuery {
  industry: string; // "" = all industries
  ordering: Ordering;
  page: number;
}

export const PAGE_SIZE = 12; // fixed by the API

/** The API answered with an error status (400 bad filter, 404 bad page, 5xx). */
export class ApiError extends Error {
  constructor(readonly status: number) {
    super(`Brand API returned ${status}`);
    this.name = "ApiError";
  }
}

/** Query string shared by the page URL and the API URL. Defaults are left out. */
export function toSearchParams(query: BrandQuery): URLSearchParams {
  const params = new URLSearchParams();
  if (query.industry) params.set("industry", query.industry);
  if (query.ordering !== DEFAULT_ORDERING) params.set("ordering", query.ordering);
  if (query.page > 1) params.set("page", String(query.page));
  return params;
}

export async function fetchBrands(
  apiUrl: string,
  query: BrandQuery,
  signal: AbortSignal,
): Promise<BrandPage> {
  const search = toSearchParams(query).toString();
  const response = await fetch(search ? `${apiUrl}?${search}` : apiUrl, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as BrandPage;
}
