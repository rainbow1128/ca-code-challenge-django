"""Query parameters of GET /api/brands/.

    industry   one or more industry slugs, comma-separated or repeated
               (?industry=insurance,finance or ?industry=insurance&industry=finance).
               Brands in ANY of them are returned. Unknown slugs -> 400.
    ordering   -average_rating (default) | average_rating | -review_count | review_count
    page       1-based page number (12 brands per page)

Every ordering ends with name and id, so the order is total and pages never
overlap or skip a brand. Brands without reviews (no average) always sort last
when ordering by rating.
"""

from django.db.models import F
from rest_framework import serializers

_RATING_DESC = F("average_rating").desc(nulls_last=True)
_RATING_ASC = F("average_rating").asc(nulls_last=True)
_TIE_BREAK = ("name", "id")

ORDERINGS = {
    "-average_rating": (_RATING_DESC, "-review_count", *_TIE_BREAK),
    "average_rating": (_RATING_ASC, "-review_count", *_TIE_BREAK),
    "-review_count": ("-review_count", _RATING_DESC, *_TIE_BREAK),
    "review_count": ("review_count", _RATING_DESC, *_TIE_BREAK),
}
DEFAULT_ORDERING = "-average_rating"


class BrandListParams(serializers.Serializer):
    industry = serializers.CharField(required=False, allow_blank=True, default="")
    ordering = serializers.ChoiceField(
        choices=list(ORDERINGS), required=False, default=DEFAULT_ORDERING
    )

    @classmethod
    def from_query(cls, query_params, industries):
        data = {"industry": ",".join(query_params.getlist("industry"))}
        if "ordering" in query_params:
            data["ordering"] = query_params["ordering"]
        return cls(data=data, context={"industry_slugs": {i.slug for i in industries}})

    def validate_industry(self, value):
        slugs = list(dict.fromkeys(s.strip() for s in value.split(",") if s.strip()))
        unknown = [s for s in slugs if s not in self.context["industry_slugs"]]
        if unknown:
            raise serializers.ValidationError(f"Unknown industry: {', '.join(unknown)}.")
        return slugs
