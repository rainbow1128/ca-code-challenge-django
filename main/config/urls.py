from django.urls import path

from catalog.api.views import BrandListView

# Server-rendered pages are added in a later step.
urlpatterns = [
    path("api/brands/", BrandListView.as_view(), name="api-brand-list"),
]
