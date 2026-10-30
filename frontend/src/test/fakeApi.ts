// An in-memory stand-in for GET /api/brands/ that filters, sorts and pages
// like the real endpoint, and honours AbortSignal like fetch does.

import type { BrandCard, BrandPage, Industry, Ordering } from "../brand-list/api";

export const INDUSTRIES: Industry[] = [
  { slug: "finance", name: "Finance" },
  { slug: "insurance", name: "Insurance" },
  { slug: "telecom", name: "Telecom" },
];

/** 14 brands: 10 insurance, 4 finance, none in telecom (for the empty state). */
export const BRANDS: BrandCard[] = Array.from({ length: 14 }, (_, i) => {
  const industry = i < 10 ? INDUSTRIES[1]! : INDUSTRIES[0]!;
  return {
    slug: `brand-${i}`,
    name: `Brand ${String(i).padStart(2, "0")}`,
    industry,
    headquarters: "Hartford, CT",
    short_description: `Description of brand ${i}.`,
    average_rating: Math.round((5 - i * 0.25) * 100) / 100,
    review_count: (i * 7) % 13,
    top_review: {
      slug: `review-${i}`,
      title: `Great service ${i}`,
      rating: 5,
      snippet: `Snippet for brand ${i}`,
      reviewer_name: "Sarah K.",
      location: "Denver, CO",
      published_at: "2026-05-19T20:29:26Z",
    },
  };
});

export function apiResponse(url: string): { status: number; body?: BrandPage } {
  const params = new URL(url, "http://test").searchParams;
  const industry = params.get("industry");
  const ordering = (params.get("ordering") ?? "-average_rating") as Ordering;
  const page = Number(params.get("page") ?? "1");
  if (industry && !INDUSTRIES.some((i) => i.slug === industry)) return { status: 400 };

  const key = ordering.replace("-", "") as "average_rating" | "review_count";
  const sign = ordering.startsWith("-") ? -1 : 1;
  const rows = BRANDS.filter((b) => !industry || b.industry.slug === industry).sort(
    (a, b) => sign * ((a[key] ?? 0) - (b[key] ?? 0)) || a.name.localeCompare(b.name),
  );
  const totalPages = Math.max(1, Math.ceil(rows.length / 12));
  if (!Number.isInteger(page) || page < 1 || page > totalPages) return { status: 404 };
  return {
    status: 200,
    body: {
      count: rows.length,
      page,
      total_pages: totalPages,
      next: page < totalPages ? `?page=${page + 1}` : null,
      previous: page > 1 ? `?page=${page - 1}` : null,
      ordering,
      industries: INDUSTRIES,
      results: rows.slice((page - 1) * 12, page * 12),
    },
  };
}

type Handler = (url: string) => { status: number; body?: unknown } | Promise<{ status: number; body?: unknown }>;

/** Replace global fetch. Returns the mock so tests can inspect calls. */
export function mockFetch(handler: Handler = apiResponse) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const signal = init?.signal;
    return new Promise<Response>((resolve, reject) => {
      const abort = () => reject(new DOMException("The operation was aborted.", "AbortError"));
      if (signal?.aborted) return abort();
      signal?.addEventListener("abort", abort);
      Promise.resolve(handler(url)).then(
        ({ status, body }) =>
          resolve(new Response(body === undefined ? null : JSON.stringify(body), { status })),
        reject,
      );
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Search part of each URL fetch was called with, e.g. ["", "?industry=finance"]. */
export function requestedSearches(fetchMock: ReturnType<typeof mockFetch>): string[] {
  return fetchMock.mock.calls.map(([input]) => {
    const search = new URL(String(input), "http://test").search;
    return search;
  });
}

/** A promise you resolve later, to hold a response back. */
export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}
