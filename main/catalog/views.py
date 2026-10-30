"""Server-rendered pages. URLs and slugs match the WordPress permalinks:
/  ·  /brand/<slug>/  ·  /review/<slug>/

Query budget (asserted in tests): home 2, brand 2, review 2.
"""

from django.shortcuts import get_object_or_404, render

from catalog.models import Brand, Review

HOME_BRANDS = 6
HOME_REVIEWS = 6


def home(request):
    top_brands = Brand.objects.for_cards(top_review=False).ordered_by("-average_rating")
    recent_reviews = Review.objects.with_people().recent()
    return render(request, "catalog/home.html", {
        "top_brands": top_brands[:HOME_BRANDS],
        "recent_reviews": recent_reviews[:HOME_REVIEWS],
    })


def brand_detail(request, slug):
    brand = get_object_or_404(
        Brand.objects.select_related("industry").with_rating_stats(), slug=slug
    )
    # All reviews, newest first (as on the WordPress page). The brand is
    # already loaded, so only the reviewer is joined.
    reviews = list(brand.reviews.select_related("reviewer").recent())
    return render(request, "catalog/brand_detail.html", {"brand": brand, "reviews": reviews})


def review_detail(request, slug):
    review = get_object_or_404(Review.objects.select_related("reviewer"), slug=slug)
    # The brand is loaded on its own (not joined above) because the brand box
    # shows its rating, which needs the stats annotation.
    brand = Brand.objects.for_cards(top_review=False).get(pk=review.brand_id)
    return render(request, "catalog/review_detail.html", {"review": review, "brand": brand})
