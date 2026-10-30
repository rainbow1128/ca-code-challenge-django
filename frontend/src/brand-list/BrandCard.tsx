import type { BrandCard as BrandCardData } from "./api";

interface StarsProps {
  rating: number | null;
  /** 1 for brand averages ("4.0"), 0 for a single review's rating ("4"). */
  decimals?: 0 | 1;
  showValue?: boolean;
}

/**
 * Same markup and classes as the Django `stars` template tag, so both share
 * the SCSS: one screen-reader label, glyphs hidden, rounded to whole stars.
 */
export function Stars({ rating, decimals = 1, showValue = true }: StarsProps) {
  if (rating === null) return <span className="stars stars--none">No ratings yet</span>;
  // Half-up like the Django pages (3.85 -> "3.9"). The API sends two decimals,
  // so round from whole hundredths to avoid float error (3.85.toFixed(1) is "3.8").
  const label =
    decimals === 0 ? String(rating) : (Math.round(Math.round(rating * 100) / 10) / 10).toFixed(1);
  const full = Math.min(5, Math.max(0, Math.round(rating)));
  return (
    <span className="stars" role="img" aria-label={`Rated ${label} out of 5`}>
      <span className="stars__icons" aria-hidden="true">
        {Array.from({ length: 5 }, (_, i) =>
          i < full ? (
            <span key={i} className="star-full">★</span>
          ) : (
            <span key={i} className="star-empty">☆</span>
          ),
        )}
      </span>
      {showValue && (
        <span className="rating-value" aria-hidden="true">
          {label}
        </span>
      )}
    </span>
  );
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function BrandCard({ brand }: { brand: BrandCardData }) {
  const top = brand.top_review;
  return (
    <article className="card brand-card">
      <h3 className="card__title">
        <a href={`/brand/${encodeURIComponent(brand.slug)}/`}>{brand.name}</a>
      </h3>
      <p className="badge">{brand.industry.name}</p>
      <p className="card__rating">
        <Stars rating={brand.average_rating} />
        <span className="meta">({plural(brand.review_count, "review")})</span>
      </p>
      {brand.headquarters && <p className="meta">{brand.headquarters}</p>}
      {brand.short_description && <p className="excerpt">{brand.short_description}</p>}
      {top && (
        <figure className="card__quote">
          <blockquote>
            <p>“{top.snippet}”</p>
          </blockquote>
          <figcaption className="meta">
            <Stars rating={top.rating} decimals={0} showValue={false} />{" "}
            <cite>
              <a href={`/review/${encodeURIComponent(top.slug)}/`}>{top.title}</a>
            </cite>{" "}
            — {top.reviewer_name}
          </figcaption>
        </figure>
      )}
    </article>
  );
}
