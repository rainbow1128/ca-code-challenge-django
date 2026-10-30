from django.urls import path

from catalog import views
from catalog.api.views import BrandListView, BrandUpdateView

# Page URLs match the WordPress permalinks. <str:slug> (not <slug:>) because
# imported slugs may contain non-ASCII letters.
urlpatterns = [
    path("", views.home, name="home"),
    path("brand/", views.brand_list, name="brand-list"),
    path("brand/<str:slug>/", views.brand_detail, name="brand-detail"),
    path("review/<str:slug>/", views.review_detail, name="review-detail"),
    path("api/brands/", BrandListView.as_view(), name="api-brand-list"),
    path("api/brands/<str:slug>/", BrandUpdateView.as_view(), name="api-brand-detail"),
]
