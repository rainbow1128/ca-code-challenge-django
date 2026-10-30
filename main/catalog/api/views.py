import logging

from django.shortcuts import get_object_or_404
from rest_framework.generics import GenericAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from ca_shared.drf import IsEditor, JWTAuthentication
from catalog.models import Brand, Industry

from .params import BrandListParams
from .serializers import BrandCardSerializer, BrandUpdateSerializer, IndustrySerializer

log = logging.getLogger(__name__)


class BrandPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = None  # fixed size; clients can't ask for more


class BrandListView(GenericAPIView):
    """GET /api/brands/ — paginated brand cards. See params.py for the query string.

    Response:
        count, page, total_pages, next, previous   pagination (next/previous keep the filters)
        ordering                                   the ordering applied
        industries                                 filter options, [{slug, name}]
        results                                    brand cards

    Always 4 queries, however many brands: industries, count, one page of
    brands (with ratings), top reviews for that page.
    """

    serializer_class = BrandCardSerializer
    pagination_class = BrandPagination

    def get(self, request):
        industries = list(Industry.objects.order_by("name"))
        params = BrandListParams.from_query(request.query_params, industries)
        params.is_valid(raise_exception=True)
        industry_slugs = params.validated_data["industry"]
        ordering = params.validated_data["ordering"]

        brands = Brand.objects.for_cards()
        if industry_slugs:
            brands = brands.filter(industry__slug__in=industry_slugs)
        brands = brands.ordered_by(ordering)

        page = self.paginate_queryset(brands)
        paginator = self.paginator
        return Response({
            "count": paginator.page.paginator.count,
            "page": paginator.page.number,
            "total_pages": paginator.page.paginator.num_pages,
            "next": paginator.get_next_link(),
            "previous": paginator.get_previous_link(),
            "ordering": ordering,
            "industries": IndustrySerializer(industries, many=True).data,
            "results": self.get_serializer(page, many=True).data,
        })


class BrandUpdateView(GenericAPIView):
    """PATCH /api/brands/<slug>/  {"short_description": "..."}  (editors only)

    401 missing, malformed, expired or wrongly signed token (WWW-Authenticate: Bearer)
    403 valid token without the editor role
    400 invalid body (unknown fields, not a string, longer than 500 characters)
    404 unknown slug (only after authentication, so the endpoint can't be used
        to probe which brands exist)
    200 the updated brand card (same shape as a row of GET /api/brands/)
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsEditor]
    serializer_class = BrandUpdateSerializer

    def patch(self, request, slug):
        update = self.get_serializer(data=request.data)
        update.is_valid(raise_exception=True)
        brand = get_object_or_404(Brand, slug=slug)

        brand.short_description = update.validated_data["short_description"]
        brand.save(update_fields=["short_description"])
        log.info("brand %s short_description updated by %s (token %s)",
                 brand.slug, request.user, request.auth.token_id)

        card = Brand.objects.for_cards().get(pk=brand.pk)
        return Response(BrandCardSerializer(card).data)
