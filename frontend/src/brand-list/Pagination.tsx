import type { MouseEvent } from "react";

/**
 * Page numbers to show: all of them when there are few, otherwise the first,
 * the last and the current page with one neighbour each side; gaps are null.
 *   pageItems(5, 10) -> [1, null, 4, 5, 6, null, 10]
 */
export function pageItems(current: number, total: number): (number | null)[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const wanted = new Set([1, total, current - 1, current, current + 1]);
  const pages = [...wanted].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);
  const items: (number | null)[] = [];
  pages.forEach((p, i) => {
    if (i > 0 && p - pages[i - 1]! > 1) items.push(null);
    items.push(p);
  });
  return items;
}

interface Props {
  page: number;
  totalPages: number;
  hrefFor: (page: number) => string;
  onNavigate: (page: number) => void;
}

/**
 * Real links (?page=2), so they work with middle-click, "open in new tab" and
 * without JavaScript; a plain click is handled in place.
 */
export function Pagination({ page, totalPages, hrefFor, onNavigate }: Props) {
  if (totalPages <= 1) return null;

  const follow = (target: number) => (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onNavigate(target);
  };

  return (
    <nav className="pagination" aria-label="Pagination">
      <ul role="list">
        <li>
          {page > 1 ? (
            <a className="pagination__link" href={hrefFor(page - 1)} onClick={follow(page - 1)}>
              <span aria-hidden="true">← </span>Previous
            </a>
          ) : (
            <span className="pagination__link" aria-disabled="true">
              <span aria-hidden="true">← </span>Previous
            </span>
          )}
        </li>
        {pageItems(page, totalPages).map((item, i) =>
          item === null ? (
            <li key={`gap${i}`} className="pagination__gap" aria-hidden="true">
              …
            </li>
          ) : (
            <li key={item}>
              <a
                className="pagination__link"
                href={hrefFor(item)}
                onClick={follow(item)}
                aria-current={item === page ? "page" : undefined}
                aria-label={`Page ${item}`}
              >
                {item}
              </a>
            </li>
          ),
        )}
        <li>
          {page < totalPages ? (
            <a className="pagination__link" href={hrefFor(page + 1)} onClick={follow(page + 1)}>
              Next<span aria-hidden="true"> →</span>
            </a>
          ) : (
            <span className="pagination__link" aria-disabled="true">
              Next<span aria-hidden="true"> →</span>
            </span>
          )}
        </li>
      </ul>
    </nav>
  );
}
