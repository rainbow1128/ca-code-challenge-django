from django.contrib import admin
from django.urls import path

from accounts import views

urlpatterns = [
    path("api/token/", views.token, name="token"),
    path("admin/", admin.site.urls),
]
