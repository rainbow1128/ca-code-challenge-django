from django.contrib import admin
from django.urls import path

# Login and token endpoints are added in the auth step.
urlpatterns = [
    path("admin/", admin.site.urls),
]
