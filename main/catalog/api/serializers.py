from rest_framework import serializers

from catalog.html import excerpt
from catalog.models import Brand, Industry, Review

TOP_REVIEW_SNIPPET_WORDS = 30


class IndustrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Industry
        fields = ["slug", "name"]


class TopReviewSerializer(serializers.ModelSerializer):
    snippet = serializers.SerializerMethodField()
    reviewer_name = serializers.CharField(source="reviewer.display_name")

    class Meta:
        model = Review
        fields = ["slug", "title", "rating", "snippet", "reviewer_name", "location", "published_at"]

    def get_snippet(self, review):
        return excerpt(review.body_html, TOP_REVIEW_SNIPPET_WORDS)


class BrandCardSerializer(serializers.ModelSerializer):
    """One brand card. Expects a queryset from Brand.objects.for_cards()."""

    industry = IndustrySerializer()
    average_rating = serializers.DecimalField(
        max_digits=3, decimal_places=2, coerce_to_string=False, allow_null=True
    )
    review_count = serializers.IntegerField()
    top_review = TopReviewSerializer(allow_null=True)

    class Meta:
        model = Brand
        fields = [
            "slug", "name", "industry", "headquarters", "short_description",
            "average_rating", "review_count", "top_review",
        ]
        read_only_fields = fields


class StrictCharField(serializers.CharField):
    """A CharField that refuses numbers and booleans instead of converting them."""

    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class BrandUpdateSerializer(serializers.Serializer):
    """Body of PATCH /api/brands/<slug>/. Only the short description is editable."""

    short_description = StrictCharField(
        max_length=Brand._meta.get_field("short_description").max_length,
        allow_blank=True,
        trim_whitespace=True,
    )

    def validate(self, attrs):
        unknown = sorted(set(self.initial_data) - set(self.fields))
        if unknown:
            raise serializers.ValidationError(
                {name: ["This field can't be changed here."] for name in unknown}
            )
        return attrs
