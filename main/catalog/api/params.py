"""Query parameters of GET /api/brands/.

    industry   one or more industry slugs, comma-separated or repeated
               (?industry=insurance,finance or ?industry=insurance&industry=finance).
               Brands in ANY of them are returned. Unknown slugs -> 400.
    ordering   -average_rating (default) | average_rating | -review_count | review_count
    page       1-based page number (12 brands per page)

The orderings themselves (and their tie-breaks) are catalog.models.BRAND_ORDERINGS,
shared with the server-rendered pages.
"""

from rest_framework import serializers

from catalog.models import BRAND_ORDERINGS

DEFAULT_ORDERING = "-average_rating"


class BrandListParams(serializers.Serializer):
    industry = serializers.CharField(required=False, allow_blank=True, default="")
    ordering = serializers.ChoiceField(
        choices=list(BRAND_ORDERINGS), required=False, default=DEFAULT_ORDERING
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
