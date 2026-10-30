from rest_framework.generics import GenericAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from catalog.models import Brand, Industry

from .params import ORDERINGS, BrandListParams
from .serializers import BrandCardSerializer, IndustrySerializer


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
        brands = brands.order_by(*ORDERINGS[ordering])

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
